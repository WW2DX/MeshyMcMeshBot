"""Community events from iCal feeds (Google Calendar works) plus admin-added events."""

import asyncio
import logging
from datetime import date, datetime, timedelta

import icalendar
import recurring_ical_events

log = logging.getLogger(__name__)


class Events:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["events"]

    async def _ical(self, url: str, start: datetime, end: datetime) -> list[tuple[datetime, str]]:
        try:
            r = await self.bot.http.get(url)
            r.raise_for_status()
        except Exception as e:
            log.warning("Calendar %s failed: %s", url, e)
            return []

        def parse():
            cal = icalendar.Calendar.from_ical(r.content)
            out = []
            for ev in recurring_ical_events.of(cal).between(start, end):
                dt = ev.get("DTSTART").dt
                if not isinstance(dt, datetime):  # all-day event
                    dt = datetime.combine(dt, datetime.min.time())
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=self.bot.tz)
                title = str(ev.get("SUMMARY", "")).strip()
                loc = str(ev.get("LOCATION", "")).split(",")[0].strip()
                out.append((dt.astimezone(self.bot.tz), f"{title} @ {loc}" if loc else title))
            return out

        return await asyncio.to_thread(parse)

    async def upcoming(self, days: int) -> list[tuple[datetime, str]]:
        start = self.bot.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=days)
        results = await asyncio.gather(*(self._ical(u, start, end) for u in self.cfg["ical_urls"]))
        events = [e for r in results for e in r]
        for row in self.bot.db.all(
            "SELECT start_ts, title FROM events WHERE start_ts BETWEEN ? AND ?",
            (int(start.timestamp()), int(end.timestamp())),
        ):
            events.append((datetime.fromtimestamp(row["start_ts"], self.bot.tz), row["title"]))
        return sorted(events)

    def fmt(self, dt: datetime, title: str) -> str:
        today = self.bot.now().date()
        if dt.date() == today:
            day = "Today"
        elif dt.date() == today + timedelta(days=1):
            day = "Tmrw"
        else:
            day = dt.strftime("%a %-m/%-d")
        when = "" if (dt.hour, dt.minute) == (0, 0) else dt.strftime(" %-I:%M%p").replace(":00", "").lower()
        return f"{day}{when} {title}"

    async def summary(self, days: int, limit: int) -> str | None:
        evs = await self.upcoming(days)
        if not evs:
            return None
        return "📅 " + "\n".join(self.fmt(dt, t) for dt, t in evs[:limit])

    async def post_digest(self):
        text = await self.summary(self.cfg["days_ahead"], 4)
        if text:
            await self.bot.post(text)


def setup(bot):
    cfg = bot.cfg["events"]
    if not cfg["enabled"]:
        return
    events = Events(bot)

    @bot.command("events", "events: upcoming community events", aliases=("cal",))
    async def _events(ctx):
        text = await events.summary(cfg["days_ahead"], 6 if ctx.is_dm else 3)
        return text or f"Nothing on the calendar for the next {cfg['days_ahead']} days."

    @bot.command("addevent", "addevent YYYY-MM-DD [HH:MM] title", admin=True, dm_only=True)
    async def _add(ctx):
        parts = ctx.args.split(" ", 2)
        try:
            d = date.fromisoformat(parts[0])
            if len(parts) >= 2 and ":" in parts[1]:
                h, m = map(int, parts[1].split(":"))
                title = parts[2] if len(parts) > 2 else ""
            else:
                h = m = 0
                title = " ".join(parts[1:])
        except (ValueError, IndexError):
            return "Usage: addevent 2026-11-08 09:00 Farmers Market @ Town Sq"
        if not title:
            return "Event needs a title."
        dt = datetime(d.year, d.month, d.day, h, m, tzinfo=bot.tz)
        cur = bot.db.execute(
            "INSERT INTO events (start_ts, title, added_by) VALUES (?,?,?)",
            (int(dt.timestamp()), title, ctx.msg.sender_name),
        )
        return f"Added #{cur.lastrowid}: {events.fmt(dt, title)}"

    @bot.command("delevent", "delevent <id>", admin=True, dm_only=True)
    async def _del(ctx):
        n = bot.db.execute("DELETE FROM events WHERE id=?", (ctx.args.lstrip("#"),)).rowcount
        return "Deleted." if n else "No such event."

    bot.schedule("events", events.post_digest, times=cfg["post_times"])
