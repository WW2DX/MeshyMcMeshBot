"""Settings an admin can change over the mesh.

Values are stored in the database and layered over the defaults (and the
optional config file) at startup, so nothing needs editing on the Pi.
"""

import json
import re
from dataclasses import dataclass

FEATURES = ("weather", "news", "events", "mailbox", "bbs", "welcome",
            "repeaters", "quakes", "rivers", "air")


@dataclass
class Setting:
    key: str  # what admins type
    path: str  # dotted path in the config dict
    kind: str  # str | int | float | bool | times | quiet | choice | secret | zip
    help: str
    choices: tuple = ()


SETTINGS = [
    Setting("zip", "location.zip", "zip", "US ZIP code for weather & alerts"),
    Setting("area", "location.name", "str", "area name used in welcomes"),
    Setting("botname", "bot.name", "str", "the bot's node name"),
    Setting("channel", "bot.channel_idx", "int", "channel slot the bot uses (0 = Public)"),
    Setting("prefix", "bot.prefix", "str", "channel command prefix"),
    Setting("quiet", "bot.quiet_hours", "quiet", "quiet hours, e.g. 22:30-05:30, or off"),
    Setting("adverthours", "bot.advert_hours", "float", "hours between bot adverts"),
    Setting("wxtimes", "weather.post_times", "times", "forecast times, e.g. 6,10,14,18,22"),
    Setting("newstimes", "news.post_times", "times", "headline times"),
    Setting("eventtimes", "events.post_times", "times", "events digest times"),
    Setting("statstimes", "stats.post_times", "times", "mesh stats times (off to disable)"),
    Setting("alertlevel", "weather.alerts.min_severity", "choice", "lowest NWS alert to post",
            ("Minor", "Moderate", "Severe", "Extreme")),
    Setting("aqi", "air.alert_aqi", "int", "AQI that triggers an air alert"),
    Setting("airnowkey", "air.airnow_api_key", "secret", "AirNow API key (optional)"),
    Setting("quakeradius", "quakes.radius_km", "int", "earthquake radius in km"),
    Setting("quakemag", "quakes.min_magnitude", "float", "smallest quake to post"),
    Setting("floodlevel", "rivers.alert_category", "choice", "flood stage that triggers alerts",
            ("action", "minor", "moderate", "major")),
    Setting("rptoffline", "repeaters.offline_hours", "float", "hours before a repeater counts as down"),
    Setting("rptnotify", "repeaters.notify", "choice", "who hears about repeater outages",
            ("admins", "channel")),
    Setting("welcomemsg", "welcome.message", "str", "welcome DM ({name} {area} {bot})"),
] + [Setting(f, f"{f}.enabled", "bool", f"turn {f} on/off") for f in FEATURES]

BY_KEY = {s.key: s for s in SETTINGS}

# List-valued settings managed with add/del/list.
LISTS = {
    "feed": ("news.feeds", "add feed <name> <rss url>"),
    "cal": ("events.ical_urls", "add cal <ical url or google calendar id>"),
    "gauge": ("rivers.gauges", "add gauge <NWS gauge id, e.g. OMHN1>"),
    "repeater": ("repeaters.watch", "add repeater <name or key prefix>"),
    "admin": ("bot.admins", "add admin <name or @keyprefix>"),
}

TRUE = {"on", "yes", "true", "1", "enable", "enabled"}
FALSE = {"off", "no", "false", "0", "disable", "disabled"}


def parse_time(t: str) -> str:
    t = t.strip()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?$", t)
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise ValueError(f"'{t}' isn't a time like 6 or 06:30")
    return f"{int(m.group(1)):02d}:{m.group(2) or '00'}"


def parse(setting: Setting, raw: str):
    raw = raw.strip()
    low = raw.lower()
    if setting.kind in ("str", "secret"):
        if not raw:
            raise ValueError("needs a value")
        return raw
    if setting.kind == "zip":
        from .location import normalize_zip
        try:
            return normalize_zip(raw)
        except SystemExit as e:
            raise ValueError(str(e))
    if setting.kind == "int":
        return int(raw)
    if setting.kind == "float":
        return float(raw)
    if setting.kind == "bool":
        if low in TRUE:
            return True
        if low in FALSE:
            return False
        raise ValueError("use on or off")
    if setting.kind == "choice":
        for c in setting.choices:
            if c.lower() == low:
                return c
        raise ValueError("one of: " + ", ".join(setting.choices))
    if setting.kind == "times":
        if low in FALSE or low == "none":
            return []
        return sorted({parse_time(t) for t in re.split(r"[,\s]+", raw) if t})
    if setting.kind == "quiet":
        if low in FALSE or low == "none":
            return {}
        start, sep, end = raw.partition("-")
        if not sep:
            raise ValueError("use start-end, e.g. 22:30-05:30, or off")
        return {"start": parse_time(start), "end": parse_time(end)}
    raise ValueError(f"unknown kind {setting.kind}")


def show(setting: Setting, value) -> str:
    if setting.kind == "secret":
        return "(set)" if value else "(not set)"
    if setting.kind == "bool":
        return "on" if value else "off"
    if setting.kind == "times":
        return ",".join(value) if value else "off"
    if setting.kind == "quiet":
        return f"{value['start']}-{value['end']}" if value else "off"
    return "(not set)" if value in (None, "") else str(value)


def parse_list_item(kind: str, raw: str):
    raw = raw.strip()
    if not raw:
        raise ValueError(LISTS[kind][1])
    if kind == "feed":
        name, _, url = raw.rpartition(" ")
        if "://" not in url:
            raise ValueError(LISTS[kind][1])
        return {"name": name.strip() or "News", "url": url}
    if kind == "cal":
        if "://" in raw:
            return raw
        if "@" in raw:  # a Google Calendar ID; the full iCal URL won't fit in a DM
            cid = raw.replace("@", "%40")
            return f"https://calendar.google.com/calendar/ical/{cid}/public/basic.ics"
        raise ValueError(LISTS[kind][1])
    if kind == "gauge":
        if not re.match(r"^[A-Za-z0-9]{4,6}$", raw):
            raise ValueError("gauge IDs look like OMHN1 (see water.noaa.gov)")
        return raw.upper()
    return raw


def show_item(kind: str, item) -> str:
    if kind == "feed":
        return f"{item['name']}: {item['url']}"
    return str(item)


# --- storage & layering ---------------------------------------------------

def get_path(cfg: dict, path: str):
    node = cfg
    for part in path.split("."):
        node = node[part]
    return node


def set_path(cfg: dict, path: str, value):
    *parents, last = path.split(".")
    node = cfg
    for part in parents:
        node = node.setdefault(part, {})
    node[last] = value


def stored(db) -> dict:
    return {r["key"]: json.loads(r["value"]) for r in db.all("SELECT key, value FROM settings")}


def save(db, path: str, value):
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (path, json.dumps(value)))


def delete(db, path: str):
    db.execute("DELETE FROM settings WHERE key=?", (path,))


def apply(cfg: dict, db):
    """Layer mesh-set values over the config. Unknown paths are ignored."""
    for path, value in stored(db).items():
        try:
            get_path(cfg, path)
        except (KeyError, TypeError):
            continue
        set_path(cfg, path, value)
    if "bot" in cfg:
        cfg["bot"]["admins"] = [a.lower() for a in cfg["bot"]["admins"]]
