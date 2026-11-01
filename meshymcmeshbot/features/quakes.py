"""Nearby earthquakes from the USGS (earthquake.usgs.gov, no key)."""

import logging
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

API = "https://earthquake.usgs.gov/fdsnws/event/1/query"
# Only announce quakes this recent, so a restart or first install doesn't
# dump a day's worth of old ones on the channel.
FRESH_SECONDS = 2 * 3600


class Quakes:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["quakes"]
        self.loc = bot.cfg["location"]

    async def recent(self, days: float) -> list[dict]:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        r = await self.bot.http.get(API, params={
            "format": "geojson", "orderby": "time", "eventtype": "earthquake",
            "latitude": self.loc["lat"], "longitude": self.loc["lon"],
            "maxradiuskm": self.cfg["radius_km"], "minmagnitude": self.cfg["min_magnitude"],
            "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        r.raise_for_status()
        return [dict(f["properties"], id=f["id"]) for f in r.json().get("features", [])]

    def fmt(self, q: dict) -> str:
        when = self.bot.fmt_time(q["time"] / 1000)
        return f"M{q['mag']:.1f} {q['place']}, {when}"

    async def poll(self):
        quiet = self.bot.in_quiet_hours()
        for q in reversed(await self.recent(1)):
            if self.bot.db.seen("quake", q["id"]):
                continue
            self.bot.db.mark_seen("quake", q["id"])
            if time.time() - q["time"] / 1000 > FRESH_SECONDS:
                continue
            if quiet and q["mag"] < self.cfg["urgent_magnitude"]:
                continue
            log.info("Quake: %s", q.get("title"))
            await self.bot.post(f"🌎 Earthquake {self.fmt(q)} (USGS)")


def setup(bot):
    cfg = bot.cfg["quakes"]
    if not cfg["enabled"]:
        return
    quakes = Quakes(bot)

    @bot.command("quakes", "quakes: recent nearby earthquakes", aliases=("eq",))
    async def _quakes(ctx):
        found = await quakes.recent(7)
        if not found:
            return f"🌎 No M{cfg['min_magnitude']:g}+ quakes within {cfg['radius_km']}km this week."
        return "🌎 " + "\n".join(quakes.fmt(q) for q in found[: 5 if ctx.is_dm else 2])

    # The poll handles quiet hours itself (big quakes still go out).
    bot.schedule("quakes", quakes.poll, every_seconds=cfg["poll_minutes"] * 60,
                 respect_quiet_hours=False)
