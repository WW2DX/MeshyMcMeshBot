"""Bot core: command routing, airtime-friendly send queue, and scheduling."""

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx

from .db import DB
from .text import paginate
from .transport import Incoming, Transport

log = logging.getLogger(__name__)

# Channel commands received this soon after startup and older than STALE_SECONDS
# were sitting in the radio's queue while the bot was down. Don't answer them.
STARTUP_GRACE_SECONDS = 20
STALE_SECONDS = 300


@dataclass
class Command:
    name: str
    fn: Callable[["Ctx"], Awaitable[str | None]]
    help: str
    aliases: tuple[str, ...] = ()
    dm_only: bool = False
    admin: bool = False


@dataclass
class Ctx:
    bot: "Bot"
    msg: Incoming
    args: str

    @property
    def is_dm(self) -> bool:
        return self.msg.kind == "dm"

    @property
    def is_admin(self) -> bool:
        return self.bot.is_admin(self.msg.sender_key)

    async def reply(self, text: str):
        await self.bot.reply(self.msg, text)


@dataclass
class Job:
    name: str
    fn: Callable[[], Awaitable[None]]
    times: list[str] = field(default_factory=list)  # "HH:MM" local
    every_seconds: int = 0
    respect_quiet_hours: bool = True
    _last_run: float = 0.0
    _last_slot: str = ""


class Bot:
    def __init__(self, cfg: dict, transport: Transport):
        self.cfg = cfg
        self.bcfg = cfg["bot"]
        self.t = transport
        self.t.on_message = self._on_message
        self.t.on_advert = self._on_advert
        self.db = DB(self.bcfg["db_path"])
        self.tz = ZoneInfo(cfg["location"]["timezone"])
        self.http = httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": cfg["weather"]["user_agent"]},
            follow_redirects=True,
        )
        self.commands: dict[str, Command] = {}
        self.jobs: list[Job] = []
        self.advert_hooks: list[Callable[[str], Awaitable[None]]] = []
        self.message_hooks: list[Callable[[Incoming], Awaitable[None]]] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._cooldowns: dict[str, float] = {}
        self.started = time.time()

    # --- registration -------------------------------------------------------

    def command(self, name, help, aliases=(), dm_only=False, admin=False):
        def deco(fn):
            cmd = Command(name, fn, help, tuple(aliases), dm_only, admin)
            for n in (name, *aliases):
                self.commands[n] = cmd
            return fn
        return deco

    def schedule(self, name, fn, times=None, every_seconds=0, respect_quiet_hours=True):
        self.jobs.append(Job(name, fn, list(times or []), every_seconds, respect_quiet_hours))

    # --- helpers ------------------------------------------------------------

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def is_admin(self, key: str | None) -> bool:
        if not key:
            return False
        key = key.lower()
        return any(key.startswith(a[:12]) for a in self.bcfg["admins"])

    def in_quiet_hours(self) -> bool:
        q = self.bcfg.get("quiet_hours") or {}
        if not q.get("start") or not q.get("end"):
            return False
        start = dtime.fromisoformat(q["start"])
        end = dtime.fromisoformat(q["end"])
        now = self.now().time()
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    def fmt_time(self, ts: float) -> str:
        dt = datetime.fromtimestamp(ts, self.tz)
        if dt.date() == self.now().date():
            return dt.strftime("%-I:%M%p").lower()
        return dt.strftime("%a %-m/%-d %-I:%M%p").replace("AM", "am").replace("PM", "pm")

    @staticmethod
    def ago(ts: float) -> str:
        s = int(time.time() - ts)
        if s < 90:
            return "just now"
        if s < 5400:
            return f"{s // 60}m ago"
        if s < 2 * 86400:
            return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"

    # --- sending ------------------------------------------------------------

    def _budget(self, kind: str) -> int:
        # Channel messages carry "<bot name>: " in the same payload.
        budget = self.bcfg["max_msg_bytes"]
        if kind == "chan":
            budget -= len(self.t.self_name.encode()) + 2
        return budget

    async def post(self, text: str):
        """Queue a message for the channel."""
        for part in paginate(text, self._budget("chan"), self.bcfg["max_channel_parts"]):
            await self._queue.put(("chan", None, part))

    async def dm(self, pubkey: str, text: str):
        for part in paginate(text, self._budget("dm"), self.bcfg["max_dm_parts"]):
            await self._queue.put(("dm", pubkey, part))

    async def reply(self, msg: Incoming, text: str):
        if msg.kind == "dm" and msg.sender_key:
            await self.dm(msg.sender_key, text)
        else:
            await self.post(text)

    async def _sender(self):
        while True:
            kind, key, text = await self._queue.get()
            try:
                if kind == "chan":
                    await self.t.send_channel(text)
                else:
                    await self.t.send_dm(key, text)
            except Exception:
                log.exception("Send failed")
            await asyncio.sleep(self.bcfg["tx_gap_seconds"])

    # --- receiving ----------------------------------------------------------

    async def _on_message(self, msg: Incoming):
        log.info("%s <%s> %s", msg.kind, msg.sender_name, msg.text)
        if msg.kind == "chan":
            self.db.execute(
                "INSERT INTO chan_activity (ts, sender) VALUES (?,?)",
                (int(time.time()), msg.sender_name),
            )
        elif msg.sender_key:
            self.db.upsert_node(msg.sender_key, msg.sender_name)

        for hook in self.message_hooks:
            try:
                await hook(msg)
            except Exception:
                log.exception("Message hook failed")

        text = msg.text
        prefix = self.bcfg["prefix"]
        if text.startswith(prefix):
            text = text[len(prefix):]
        elif msg.kind == "chan":
            return  # on the channel only prefixed messages are commands

        name, _, args = text.strip().partition(" ")
        cmd = self.commands.get(name.lower())
        if cmd is None:
            if msg.kind == "dm":
                await self.reply(msg, f"Unknown command '{name}'. Send 'help'.")
            return

        if msg.kind == "chan":
            if self._is_stale(msg) or self._on_cooldown(msg.sender_name):
                return
            if cmd.dm_only:
                await self.reply(msg, f"@[{msg.sender_name}] DM me '{cmd.name}' for that.")
                return
        if cmd.admin and not self.is_admin(msg.sender_key):
            if msg.kind == "dm":
                await self.reply(msg, "Admins only.")
            return

        try:
            out = await cmd.fn(Ctx(self, msg, args.strip()))
        except Exception:
            log.exception("Command %s failed", cmd.name)
            out = f"Sorry, '{cmd.name}' hit an error."
        if out:
            await self.reply(msg, out)

    def _is_stale(self, msg: Incoming) -> bool:
        in_grace = time.time() - self.started < STARTUP_GRACE_SECONDS
        return in_grace and msg.ts and time.time() - msg.ts > STALE_SECONDS

    def _on_cooldown(self, sender: str) -> bool:
        now = time.monotonic()
        last = self._cooldowns.get(sender, 0)
        if now - last < self.bcfg["channel_cooldown_seconds"]:
            return True
        self._cooldowns[sender] = now
        return False

    async def _on_advert(self, pubkey: str):
        c = self.t.contacts().get(pubkey)
        if c:
            self.db.upsert_node(pubkey, c["name"], c.get("lat"), c.get("lon"))
        for hook in self.advert_hooks:
            try:
                await hook(pubkey)
            except Exception:
                log.exception("Advert hook failed")

    # --- scheduling ---------------------------------------------------------

    async def _scheduler(self):
        while True:
            now = self.now()
            slot = now.strftime("%H:%M")
            for job in self.jobs:
                due = False
                if job.times and slot in job.times and job._last_slot != f"{now.date()} {slot}":
                    job._last_slot = f"{now.date()} {slot}"
                    due = True
                if job.every_seconds and time.monotonic() - job._last_run >= job.every_seconds:
                    due = True
                if not due:
                    continue
                job._last_run = time.monotonic()
                if job.respect_quiet_hours and self.in_quiet_hours():
                    log.info("Skipping %s (quiet hours)", job.name)
                    continue
                log.info("Running job %s", job.name)
                asyncio.create_task(self._run_job(job))
            await asyncio.sleep(15)

    async def _run_job(self, job: Job):
        try:
            res = job.fn()
            if inspect.isawaitable(res):
                await res
        except Exception:
            log.exception("Job %s failed", job.name)

    def _sync_contacts(self):
        for key, c in self.t.contacts().items():
            if c["name"]:
                self.db.upsert_node(key, c["name"], c.get("lat"), c.get("lon"), c.get("last_advert") or None)

    async def run(self):
        await self.t.start()
        self.started = time.time()
        self._sync_contacts()

        async def housekeeping():
            self._sync_contacts()
            self.db.prune()

        self.schedule("housekeeping", housekeeping, every_seconds=600, respect_quiet_hours=False)
        if self.bcfg["advert_hours"]:
            self.schedule("advert", self.t.advert,
                          every_seconds=int(self.bcfg["advert_hours"] * 3600),
                          respect_quiet_hours=False)

        log.info("Bot running with %d commands, %d jobs",
                 len({c.name for c in self.commands.values()}), len(self.jobs))
        await asyncio.gather(self._sender(), self._scheduler(), self._watchdog())

    async def _watchdog(self):
        """Exit if the radio stays gone; systemd restarts us with a fresh connection."""
        down_since = None
        while True:
            await asyncio.sleep(30)
            if self.t.is_connected():
                down_since = None
            elif down_since is None:
                down_since = time.monotonic()
                log.warning("Radio disconnected, waiting for reconnect")
            elif time.monotonic() - down_since > 180:
                raise SystemExit("Radio connection lost")
