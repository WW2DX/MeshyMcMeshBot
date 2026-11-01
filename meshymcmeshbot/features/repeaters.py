"""Repeater health: notice when a MeshCore repeater goes quiet, and when it's back.

A repeater counts as heard when we receive its advert, or when its path hash
shows up in a flood packet it relayed. Path hashes are short (often 1 byte),
so two repeaters can share one; in that case either one's traffic keeps both
looking alive. Watching by advert alone avoids that, but adverts can be hours apart.
"""

import logging
import re
import time

from ..transport import NODE_REPEATER

log = logging.getLogger(__name__)
HEX = re.compile(r"^[0-9a-fA-F]{8,64}$")


class Repeaters:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["repeaters"]

    def known(self, days: int = 7) -> list:
        cutoff = int(time.time()) - days * 86400
        rows = self.bot.db.all("SELECT * FROM nodes WHERE type=?", (NODE_REPEATER,))
        out = [(r, self.last_heard(r["pubkey"], r["last_seen"])) for r in rows]
        return sorted([x for x in out if x[1] >= cutoff], key=lambda x: -x[1])

    def last_heard(self, pubkey: str, advert_ts: int | None) -> int:
        return max(advert_ts or 0, self.bot.db.relay_seen(pubkey))

    def watched(self) -> list:
        """Rows for each configured repeater we've heard of (unknown entries are skipped)."""
        rows = []
        for entry in self.cfg["watch"]:
            if HEX.match(entry):
                row = self.bot.db.one(
                    "SELECT * FROM nodes WHERE pubkey LIKE ?", (entry.lower() + "%",)
                )
            else:
                row = self.bot.db.one(
                    "SELECT * FROM nodes WHERE name=? AND type=? ORDER BY last_seen DESC",
                    (entry, NODE_REPEATER),
                )
            if row:
                rows.append(row)
            else:
                log.debug("Watched repeater %r not heard yet", entry)
        return rows

    async def notify(self, text: str):
        if self.cfg["notify"] == "channel":
            await self.bot.post(text)
            return
        for prefix in self.bot.bcfg["admins"]:
            key = self.bot.t.find_contact_by_prefix(prefix)
            if key:
                await self.bot.dm(key, text)
            else:
                log.warning("Admin %s isn't in the radio's contacts; can't send: %s", prefix, text)

    async def check(self):
        limit = self.cfg["offline_hours"] * 3600
        now = time.time()
        for row in self.watched():
            key, name = row["pubkey"], row["name"]
            last = self.last_heard(key, row["last_seen"])
            # After a restart, give each repeater a full window before alarming.
            grace = max(last, int(self.bot.started))
            state_key = f"rpt_down:{key}"
            down = self.bot.db.get_meta(state_key) == "1"
            if now - grace > limit and not down:
                self.bot.db.set_meta(state_key, "1")
                seen = f"last {self.bot.ago(last)}" if last else "never heard by me"
                await self.notify(f"⚠️ Repeater {name} not heard for {self.cfg['offline_hours']}h+ ({seen}).")
            elif now - last <= limit and down:
                self.bot.db.set_meta(state_key, "0")
                await self.notify(f"✅ Repeater {name} is back (heard {self.bot.ago(last)}).")


def setup(bot):
    cfg = bot.cfg["repeaters"]
    if not cfg["enabled"]:
        return
    rpt = Repeaters(bot)

    @bot.command("repeaters", "repeaters: repeaters heard lately", aliases=("rpt",))
    async def _repeaters(ctx):
        known = rpt.known()
        if not known:
            return "📡 No repeaters heard in the last week."
        watched = {r["pubkey"] for r in rpt.watched()}
        limit = cfg["offline_hours"] * 3600
        parts = []
        for row, last in known[: 8 if ctx.is_dm else 4]:
            flag = "⚠️" if row["pubkey"] in watched and time.time() - last > limit else ""
            parts.append(f"{flag}{row['name']} {bot.ago(last)}")
        return "📡 " + ", ".join(parts)

    bot.schedule("repeaters", rpt.check, every_seconds=cfg["check_minutes"] * 60,
                 respect_quiet_hours=cfg["notify"] == "channel")
