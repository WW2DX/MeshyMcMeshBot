"""River levels and flood alerts from NOAA's National Water Prediction Service.

NWPS serves the USGS gauge readings plus each gauge's official flood stages
and the river forecast, which is what flood alerts need.
"""

import logging

log = logging.getLogger(__name__)

API = "https://api.water.noaa.gov/nwps/v1/gauges"
LEVELS = ["action", "minor", "moderate", "major"]
LABELS = {"action": "near flood stage", "minor": "MINOR flooding",
          "moderate": "MODERATE flooding", "major": "MAJOR flooding"}


def ft(x: float | None) -> str:
    return "?" if x is None else f"{x:.1f}ft"


def rank(category: str | None) -> int:
    """0 = no flooding (or unknown), 1 = action ... 4 = major."""
    return LEVELS.index(category) + 1 if category in LEVELS else 0


class Rivers:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["rivers"]
        self.alert_rank = rank(self.cfg["alert_category"])

    async def gauge(self, lid: str) -> dict:
        r = await self.bot.http.get(f"{API}/{lid}")
        r.raise_for_status()
        return r.json()

    @staticmethod
    def reading(g: dict) -> tuple[float | None, float | None, str]:
        """(observed ft, forecast ft, trend word)"""
        obs = (g.get("status") or {}).get("observed") or {}
        fc = (g.get("status") or {}).get("forecast") or {}
        o, f = obs.get("primary"), fc.get("primary")
        o = o if o is not None and o > -999 else None
        f = f if f is not None and f > -999 else None
        trend = ""
        if o is not None and f is not None:
            trend = "rising" if f - o > 0.3 else "falling" if o - f > 0.3 else "steady"
        return o, f, trend

    def summary(self, g: dict) -> str:
        o, f, trend = self.reading(g)
        flood = ((g.get("flood") or {}).get("categories") or {}).get("minor", {}).get("stage")
        if o is None:
            return f"{g['name']}: no current reading"
        text = f"{g['name']} {ft(o)}"
        if flood and flood > 0:
            text += f" (flood {flood:g}ft)"
        return f"{text}, {trend}" if trend else text

    async def poll(self):
        for lid in self.cfg["gauges"]:
            try:
                g = await self.gauge(lid)
            except Exception as e:
                log.warning("Gauge %s failed: %s", lid, e)
                continue
            status = g.get("status") or {}
            obs_cat = (status.get("observed") or {}).get("floodCategory")
            fc_cat = (status.get("forecast") or {}).get("floodCategory")
            level = max(rank(obs_cat), rank(fc_cat))
            state_key = f"river:{lid}"
            last = int(self.bot.db.get_meta(state_key) or 0)
            if level == last:
                continue
            self.bot.db.set_meta(state_key, str(level))
            o, f, _ = self.reading(g)
            if level >= self.alert_rank and level > last:
                if rank(obs_cat) >= rank(fc_cat):
                    msg = f"🌊 {g['name']} at {ft(o)}: {LABELS[obs_cat]}."
                else:
                    msg = f"🌊 {g['name']} forecast to reach {ft(f)}: {LABELS[fc_cat]} (now {ft(o)})."
                await self.bot.post(msg)
            elif last >= self.alert_rank and level < self.alert_rank:
                await self.bot.post(f"🌊 {g['name']} back below {self.cfg['alert_category']} flood stage ({ft(o)}).")


def setup(bot):
    cfg = bot.cfg["rivers"]
    if not cfg["enabled"] or not cfg["gauges"]:
        return
    rivers = Rivers(bot)

    @bot.command("river", "river: current river levels", aliases=("rivers",))
    async def _river(ctx):
        out = []
        for lid in cfg["gauges"][: 4 if ctx.is_dm else 2]:
            try:
                out.append(rivers.summary(await rivers.gauge(lid)))
            except Exception:
                out.append(f"{lid}: unavailable")
        return "🌊 " + "\n".join(out)

    # Flooding is a safety issue, so these alerts ignore quiet hours.
    bot.schedule("rivers", rivers.poll, every_seconds=cfg["poll_minutes"] * 60,
                 respect_quiet_hours=False)
