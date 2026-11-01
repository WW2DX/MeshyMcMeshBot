"""Config loading: YAML file merged over defaults."""

import copy
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "radio": {
        # "auto" tries /dev/meshbot, then every USB serial port, until a MeshCore
        # companion answers.
        "port": "auto",
        "baudrate": 115200,
    },
    "bot": {
        # If set, the companion node is renamed to this at startup.
        "name": "",
        # The channel the bot posts and listens on, e.g. "#mycounty". A #hashtag
        # channel is added to the radio if missing. The bot never posts on
        # Public; until this is set it only talks over DM.
        "channel": "",
        "prefix": "!",
        # Byte budget per message. Channel messages lose room to "<name>: ".
        "max_msg_bytes": 140,
        "max_channel_parts": 2,
        "max_dm_parts": 6,
        # Minimum seconds between transmissions so the bot never hogs airtime.
        "tx_gap_seconds": 4,
        # Per-sender cooldown for channel commands.
        "channel_cooldown_seconds": 30,
        # Public key prefixes (hex, at least 12 chars) allowed to run admin commands.
        "admins": [],
        # Re-advertise the bot so people can find it and DM it.
        "advert_hours": 12,
        # Scheduled posts are skipped in quiet hours; severe weather alerts still go out.
        "quiet_hours": {"start": "22:30", "end": "05:30"},
        # systemd's StateDirectory= sets STATE_DIRECTORY (/var/lib/meshbot).
        "db_path": os.path.join(os.environ.get("STATE_DIRECTORY", "."), "meshbot.sqlite3"),
    },
    "location": {
        # A US ZIP code fills in everything below (see location.py). Fields set
        # explicitly override the lookup.
        "zip": "",
        "name": "",
        "lat": None,
        "lon": None,
        "timezone": "",
    },
    "weather": {
        "enabled": True,
        # NWS requires a User-Agent with contact info.
        "user_agent": "MeshyMcMeshBot (github.com/WW2DX/MeshyMcMeshBot)",
        "post_times": ["06:00", "10:00", "14:00", "18:00", "22:00"],
        "periods": 2,
        "alerts": {
            "enabled": True,
            "poll_minutes": 5,
            # Minor < Moderate < Severe < Extreme
            "min_severity": "Severe",
        },
    },
    "news": {
        "enabled": True,
        "post_times": ["08:00", "17:00"],
        "items_per_post": 2,
        "feeds": [],
    },
    "events": {
        "enabled": True,
        "post_times": ["07:30"],
        "days_ahead": 7,
        "ical_urls": [],
    },
    "mailbox": {
        "enabled": True,
        "max_per_recipient": 20,
        "max_sent_per_day": 15,
        "expire_days": 30,
        "notify_cooldown_hours": 6,
    },
    "bbs": {
        "enabled": True,
        "max_posts": 50,
        "expire_days": 14,
    },
    "stats": {
        # Nightly "mesh today" digest on the channel. Empty list disables it.
        "post_times": ["21:00"],
    },
    "welcome": {
        "enabled": True,
        # {name} = their node name, {area} = location.name, {bot} = bot name.
        "message": "👋 Welcome to the {area} mesh, {name}! I'm {bot}, the community bot. "
                   "DM me 'help' for weather, news, events & mail.",
        # After a fresh install, wait this long before welcoming anyone, so the bot
        # learns who's already on the mesh instead of greeting everyone at once.
        "settle_days": 3,
        "max_per_hour": 6,
    },
    "repeaters": {
        "enabled": True,
        # MeshCore repeaters to watch: public-key prefixes (8+ hex chars) or exact names.
        "watch": [],
        "offline_hours": 24,
        # "admins" (DM each admin) or "channel".
        "notify": "admins",
        "check_minutes": 15,
    },
    "quakes": {
        "enabled": True,
        "radius_km": 250,
        "min_magnitude": 3.0,
        # Smaller quakes aren't posted during quiet hours.
        "urgent_magnitude": 5.0,
        "poll_minutes": 5,
    },
    "rivers": {
        "enabled": True,
        # NWS gauge IDs from https://water.noaa.gov (e.g. "OMHN1").
        "gauges": [],
        # Post when observed or forecast stage reaches: action | minor | moderate | major
        "alert_category": "minor",
        "poll_minutes": 30,
    },
    "air": {
        "enabled": True,
        # Optional free key from https://docs.airnowapi.org. Without one, the bot
        # uses Open-Meteo's modeled air quality (no key needed).
        "airnow_api_key": "",
        # Post when the US AQI reaches this (101 = unhealthy for sensitive groups,
        # 151 = unhealthy for everyone).
        "alert_aqi": 151,
        "poll_minutes": 60,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# Looked for, in order, when no config file is given. None is required.
CONFIG_PATHS = ["config.yaml", "/etc/meshbot/config.yaml"]


def find_config() -> str | None:
    return next((p for p in CONFIG_PATHS if Path(p).is_file()), None)


def load(path: str | Path | None = None) -> dict:
    user = {}
    if path:
        with open(path) as f:
            user = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, user)
    cfg["bot"]["admins"] = [a.lower() for a in cfg["bot"]["admins"]]
    return cfg
