"""NWS forecasts and severe-weather alerts (api.weather.gov, US only, no key)."""

import logging
import re
from datetime import datetime

log = logging.getLogger(__name__)

API = "https://api.weather.gov"
SEVERITY = {"Unknown": 0, "Minor": 1, "Moderate": 2, "Severe": 3, "Extreme": 4}
DIRS = {"N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"}


# NWS phrasing is long; airtime is precious.
ABBREV = [
    ("Showers And Thunderstorms", "T-storms"), ("Thunderstorms", "T-storms"),
    ("Slight Chance", "Sl chc"), ("Chance", "Chc"), ("Likely", "likely"),
    ("Partly", "Ptly"), ("Light", "Lt"), ("Heavy", "Hvy"),
]


def short_forecast(text: str) -> str:
    # "Chance Rain then Mostly Sunny" -> keep the first clause.
    text = text.split(" then ")[0]
    for long, short in ABBREV:
        text = text.replace(long, short)
    return text


def short_wind(speed: str, direction: str) -> str:
    # "5 to 10 mph" -> "5-10mph"
    s = re.sub(r"\s*to\s*", "-", speed or "").replace(" mph", "mph").strip()
    d = direction if direction in DIRS else ""
    return f"{d} {s}".strip()


def format_period(p: dict) -> str:
    hilo = "Hi" if p.get("isDaytime") else "Lo"
    parts = [f"{p['name']}: {short_forecast(p['shortForecast'])}", f"{hilo} {p['temperature']}°{p.get('temperatureUnit', 'F')}"]
    wind = short_wind(p.get("windSpeed", ""), p.get("windDirection", ""))
    if wind:
        parts.append(wind)
    pop = (p.get("probabilityOfPrecipitation") or {}).get("value")
    if pop and pop >= 20:
        parts.append(f"{pop}% precip")
    return ", ".join(parts)


def format_alert(props: dict, fmt_time) -> str:
    text = f"⚠️ NWS {props['event']}"
    ends = props.get("ends") or props.get("expires")
    if ends:
        text += f" until {fmt_time(datetime.fromisoformat(ends).timestamp())}"
    headline = (props.get("parameters", {}).get("NWSheadline") or [""])[0]
    if headline:
        text += f". {headline.capitalize()}"
    return text


class Weather:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["weather"]
        loc = bot.cfg["location"]
        self.point = f"{loc['lat']:.4f},{loc['lon']:.4f}"
        self._forecast_url = None

    async def _get(self, url: str, **params) -> dict:
        r = await self.bot.http.get(url, params=params or None,
                                    headers={"Accept": "application/geo+json"})
        r.raise_for_status()
        return r.json()

    async def periods(self) -> list[dict]:
        if not self._forecast_url:
            pts = await self._get(f"{API}/points/{self.point}")
            self._forecast_url = pts["properties"]["forecast"]
        data = await self._get(self._forecast_url)
        return data["properties"]["periods"]

    async def forecast(self, n: int) -> str:
        periods = (await self.periods())[:n]
        return "WX " + " | ".join(format_period(p) for p in periods)

    async def active_alerts(self) -> list[dict]:
        data = await self._get(f"{API}/alerts/active", point=self.point)
        return [f["properties"] for f in data.get("features", [])]

    async def post_forecast(self):
        await self.bot.post(await self.forecast(self.cfg["periods"]))

    async def poll_alerts(self):
        min_sev = SEVERITY.get(self.cfg["alerts"]["min_severity"], 3)
        for a in await self.active_alerts():
            aid = a["id"]
            if self.bot.db.seen("alert", aid):
                continue
            self.bot.db.mark_seen("alert", aid)
            # Updates/extensions reference the original alert; don't repost those.
            refs = [r.get("identifier") for r in a.get("references", [])]
            if any(self.bot.db.seen("alert", r) for r in refs):
                continue
            if a.get("messageType") == "Cancel" or SEVERITY.get(a.get("severity"), 0) < min_sev:
                continue
            log.info("New alert: %s", a.get("headline"))
            await self.bot.post(format_alert(a, self.bot.fmt_time))


def setup(bot):
    cfg = bot.cfg["weather"]
    if not cfg["enabled"]:
        return
    wx = Weather(bot)

    @bot.command("wx", "wx: forecast for the next few periods", aliases=("weather",))
    async def _wx(ctx):
        n = 4 if ctx.is_dm else cfg["periods"]
        return await wx.forecast(n)

    @bot.command("alerts", "alerts: active NWS alerts here")
    async def _alerts(ctx):
        alerts = await wx.active_alerts()
        if not alerts:
            return "No active NWS alerts. 👍"
        return " | ".join(format_alert(a, bot.fmt_time) for a in alerts[:3])

    @bot.command("wxnow", "wxnow: post the forecast to the channel now", admin=True)
    async def _wxnow(ctx):
        await wx.post_forecast()
        return "Posted." if ctx.is_dm else None

    bot.schedule("weather", wx.post_forecast, times=cfg["post_times"])
    if cfg["alerts"]["enabled"]:
        # Alerts go out even during quiet hours. Seen IDs persist in the DB,
        # so restarts don't re-post.
        bot.schedule("wx-alerts", wx.poll_alerts,
                     every_seconds=cfg["alerts"]["poll_minutes"] * 60,
                     respect_quiet_hours=False)
