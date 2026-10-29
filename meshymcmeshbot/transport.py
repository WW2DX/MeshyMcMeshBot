"""Radio transports.

MeshCoreTransport talks to a MeshCore *USB companion* node over serial.
ConsoleTransport fakes a mesh on stdin/stdout so the bot can be tried
without a radio.
"""

import asyncio
import hashlib
import logging
import sys
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


@dataclass
class Incoming:
    kind: str  # "chan" or "dm"
    sender_name: str
    text: str
    sender_key: str | None = None  # full pubkey hex when known (DMs only)
    hops: int | None = None  # None = unknown / direct route
    snr: float | None = None
    ts: int = 0


Handler = Callable[[Incoming], Awaitable[None]]
AdvertHandler = Callable[[str], Awaitable[None]]


class Transport:
    on_message: Handler
    on_advert: AdvertHandler
    self_name: str = "bot"

    async def start(self): ...
    async def send_channel(self, text: str) -> bool: ...
    async def send_dm(self, pubkey: str, text: str) -> bool: ...
    async def advert(self): ...
    async def status(self) -> str:
        return ""

    def contacts(self) -> dict[str, dict]:
        """pubkey -> {"name", "last_advert", "lat", "lon"}"""
        return {}

    def find_contact_by_prefix(self, prefix: str) -> str | None:
        prefix = prefix.lower()
        for key in self.contacts():
            if key.startswith(prefix):
                return key
        return None

    def is_connected(self) -> bool:
        return True


class MeshCoreTransport(Transport):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mc = None
        self.channel_idx = cfg["bot"]["channel_idx"]

    async def start(self):
        from meshcore import EventType, MeshCore

        port = self.cfg["radio"]["port"]
        log.info("Connecting to MeshCore companion on %s", port)
        self.mc = await MeshCore.create_serial(
            port,
            self.cfg["radio"]["baudrate"],
            auto_reconnect=True,
            max_reconnect_attempts=10,
        )
        if self.mc is None:
            raise RuntimeError(
                f"No MeshCore companion answered on {port}. "
                "Is the L1 flashed with *USB Companion* firmware?"
            )

        info = self.mc.self_info or {}
        self.self_name = info.get("name", "bot")
        want = self.cfg["bot"]["name"]
        if want and want != self.self_name:
            await self.mc.commands.set_name(want)
            self.self_name = want
        log.info("Connected as %r (%s)", self.self_name, info.get("public_key", "")[:12])

        # The Pi has NTP; the radio may not. Message timestamps come from the radio.
        await self.mc.commands.set_time(int(time.time()))

        chan = await self.mc.commands.get_channel(self.channel_idx)
        if chan.type != EventType.ERROR:
            log.info("Bot channel %d is %r", self.channel_idx, chan.payload.get("channel_name"))

        self.mc.auto_update_contacts = True
        await self.mc.ensure_contacts()

        self.mc.subscribe(EventType.CHANNEL_MSG_RECV, self._on_channel)
        self.mc.subscribe(EventType.CONTACT_MSG_RECV, self._on_dm)
        self.mc.subscribe(EventType.ADVERTISEMENT, self._on_advert)
        await self.mc.start_auto_message_fetching()

    @staticmethod
    def _hops(p: dict) -> int | None:
        # path_hash_mode -1 means a direct (non-flood) route; hop count isn't meaningful.
        if p.get("path_hash_mode", 0) < 0:
            return None
        return p.get("path_len")

    async def _on_channel(self, event):
        p = event.payload
        if p.get("channel_idx") != self.channel_idx:
            return
        raw = p.get("text", "")
        # The firmware sends group text as "<sender name>: <message>".
        name, sep, text = raw.partition(": ")
        if not sep:
            name, text = "?", raw
        await self.on_message(Incoming(
            kind="chan", sender_name=name.strip(), text=text.strip(),
            hops=self._hops(p), snr=p.get("SNR"), ts=p.get("sender_timestamp", 0),
        ))

    async def _on_dm(self, event):
        p = event.payload
        if p.get("txt_type", 0) != 0:  # skip CLI/signed-data replies
            return
        prefix = p.get("pubkey_prefix", "")
        contact = self.mc.get_contact_by_key_prefix(prefix)
        if contact is None:
            await self.mc.ensure_contacts(follow=True)
            contact = self.mc.get_contact_by_key_prefix(prefix)
        await self.on_message(Incoming(
            kind="dm",
            sender_name=contact["adv_name"] if contact else prefix,
            sender_key=contact["public_key"] if contact else prefix,
            text=p.get("text", "").strip(),
            hops=self._hops(p), snr=p.get("SNR"), ts=p.get("sender_timestamp", 0),
        ))

    async def _on_advert(self, event):
        # Let the library pull the updated contact list first so names are fresh.
        await self.mc.ensure_contacts(follow=True)
        await self.on_advert(event.payload["public_key"])

    def contacts(self) -> dict[str, dict]:
        out = {}
        for key, c in (self.mc.contacts or {}).items():
            out[key] = {
                "name": c.get("adv_name", ""),
                "last_advert": c.get("last_advert", 0),
                "lat": c.get("adv_lat") or None,
                "lon": c.get("adv_lon") or None,
            }
        return out

    async def send_channel(self, text: str) -> bool:
        res = await self.mc.commands.send_chan_msg(self.channel_idx, text)
        if res.is_error():
            log.warning("Channel send failed: %s", res.payload)
            return False
        return True

    async def send_dm(self, pubkey: str, text: str) -> bool:
        contact = self.mc.get_contact_by_key_prefix(pubkey)
        if contact is None:
            log.warning("Can't DM %s: not in the radio's contact list", pubkey[:12])
            return False
        res = await self.mc.commands.send_msg_with_retry(contact, text)
        if res is None:
            log.info("DM to %s not acknowledged", contact.get("adv_name"))
            return False
        return True

    async def advert(self):
        await self.mc.commands.send_advert(flood=True)

    async def status(self) -> str:
        from meshcore import EventType

        res = await self.mc.commands.get_bat()
        if res.type == EventType.ERROR:
            return ""
        mv = res.payload.get("level", 0)
        return f"batt {mv / 1000:.2f}V"

    def is_connected(self) -> bool:
        return self.mc is not None and self.mc.is_connected


class ConsoleTransport(Transport):
    """Type lines to simulate the mesh:

        Alice: !wx              Alice posts on the channel
        dm Alice: mail Bob hi   Alice DMs the bot
        advert Bob              Bob's node advertises (triggers mail notices)
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.self_name = cfg["bot"]["name"] or "MeshyMcMeshBot"
        self._contacts: dict[str, dict] = {}

    def _key_for(self, name: str) -> str:
        key = hashlib.sha256(name.lower().encode()).hexdigest()
        if key not in self._contacts:
            self._contacts[key] = {"name": name, "last_advert": int(time.time()), "lat": None, "lon": None}
        return key

    async def start(self):
        print(self.__doc__)
        asyncio.get_running_loop().create_task(self._read_stdin())

    async def _read_stdin(self):
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                await asyncio.sleep(3600)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                await self._handle_line(line)
            except Exception:
                log.exception("Error handling console input")

    async def _handle_line(self, line: str):
        if line.startswith("advert "):
            key = self._key_for(line[7:].strip())
            self._contacts[key]["last_advert"] = int(time.time())
            await self.on_advert(key)
            return
        kind = "chan"
        if line.startswith("dm "):
            kind, line = "dm", line[3:]
        name, sep, text = line.partition(": ")
        if not sep:
            print("  (format is 'Name: message' or 'dm Name: message')")
            return
        key = self._key_for(name.strip())
        await self.on_message(Incoming(
            kind=kind, sender_name=name.strip(), text=text.strip(),
            sender_key=key if kind == "dm" else None,
            hops=1, snr=7.5, ts=int(time.time()),
        ))

    def contacts(self) -> dict[str, dict]:
        return self._contacts

    async def send_channel(self, text: str) -> bool:
        print(f"[CHAN] {self.self_name}: {text}", flush=True)
        return True

    async def send_dm(self, pubkey: str, text: str) -> bool:
        name = self._contacts.get(pubkey, {}).get("name", pubkey[:12])
        print(f"[DM -> {name}] {text}", flush=True)
        return True

    async def advert(self):
        print("[ADVERT]", flush=True)
