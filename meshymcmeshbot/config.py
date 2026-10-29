"""Config loading: YAML file merged over defaults."""

import copy
from pathlib import Path

import yaml

DEFAULTS = {
    "radio": {
        "port": "/dev/meshbot",
        "baudrate": 115200,
    },
    "bot": {
        # If set, the companion node is renamed to this at startup.
        "name": "",
        # Index of the channel the bot lives on (0 is usually "Public").
        "channel_idx": 0,
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
        "db_path": "meshbot.sqlite3",
    },
    "location": {
        "name": "",
        "lat": 0.0,
        "lon": 0.0,
        "timezone": "America/Chicago",
    },
    "weather": {
        "enabled": True,
        # NWS requires a User-Agent with contact info.
        "user_agent": "MeshyMcMeshBot (you@example.com)",
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
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | Path) -> dict:
    with open(path) as f:
        user = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, user)
    cfg["bot"]["admins"] = [a.lower() for a in cfg["bot"]["admins"]]
    return cfg
