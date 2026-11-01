"""Air quality (US AQI): AirNow observations with an API key, else Open-Meteo's model."""

import logging

log = logging.getLogger(__name__)

AIRNOW = "https://www.airnowapi.org/aq/observation/latLong/current/"
OPEN_METEO = "https://air-quality-api.open-meteo.com/v1/air-quality"
# Back below the alert level by this much before announcing an improvement,
# so a reading hovering at the threshold doesn't flip-flop.
HYSTERESIS = 20

CATEGORIES = [
    (50, "Good", ""),
    (100, "Moderate", ""),
    (150, "Unhealthy for sensitive groups", "Sensitive folks: take it easy outdoors."),
    (200, "Unhealthy", "Limit time outdoors."),
    (300, "Very unhealthy", "Avoid outdoor activity."),
    (10_000, "Hazardous", "Stay indoors."),
]


def category(aqi: int) -> tuple[str, str]:
    for limit, name, advice in CATEGORIES:
        if aqi <= limit:
            return name, advice
    return CATEGORIES[-1][1:]


class Air:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["air"]
        self.loc = bot.cfg["location"]

    async def current(self) -> tuple[int, str]:
        """(US AQI, source)"""
        if self.cfg["airnow_api_key"]:
            r = await self.bot.http.get(AIRNOW, params={
                "format": "application/json", "latitude": self.loc["lat"],
                "longitude": self.loc["lon"], "distance": 50, "API_KEY": self.cfg["airnow_api_key"],
            })
            r.raise_for_status()
            readings = [o for o in r.json() if o.get("AQI", -1) >= 0]
            if readings:
                worst = max(readings, key=lambda o: o["AQI"])
                return worst["AQI"], "AirNow"
            log.info("AirNow had no readings nearby; falling back to Open-Meteo")
        r = await self.bot.http.get(OPEN_METEO, params={
            "latitude": self.loc["lat"], "longitude": self.loc["lon"], "current": "us_aqi",
        })
        r.raise_for_status()
        return round(r.json()["current"]["us_aqi"]), "Open-Meteo"

    async def poll(self):
        aqi, _ = await self.current()
        alerted = self.bot.db.get_meta("aqi_alerted") == "1"
        name, advice = category(aqi)
        if aqi >= self.cfg["alert_aqi"] and not alerted:
            self.bot.db.set_meta("aqi_alerted", "1")
            await self.bot.post(f"😷 Air quality is {name} (AQI {aqi}). {advice}".strip())
        elif alerted and aqi < self.cfg["alert_aqi"] - HYSTERESIS:
            self.bot.db.set_meta("aqi_alerted", "0")
            await self.bot.post(f"🌤 Air quality has improved: {name} (AQI {aqi}).")


def setup(bot):
    cfg = bot.cfg["air"]
    if not cfg["enabled"]:
        return
    air = Air(bot)

    @bot.command("aqi", "aqi: current air quality", aliases=("air",))
    async def _aqi(ctx):
        aqi, source = await air.current()
        name, advice = category(aqi)
        text = f"🌫 AQI {aqi}: {name}."
        if advice:
            text += f" {advice}"
        return f"{text} ({source})"

    bot.schedule("air", air.poll, every_seconds=cfg["poll_minutes"] * 60)
