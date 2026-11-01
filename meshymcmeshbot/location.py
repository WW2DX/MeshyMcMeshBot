"""Fill in the bot's location (lat/lon, timezone, area name) from a US ZIP code.

Lookups use free, keyless services and are cached next to the database, so
the bot still starts if they're down later. Anything set explicitly in the
config wins over the lookup.
"""

import json
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

ZIP_API = "https://api.zippopotam.us/us/{zip}"
TZ_API = "https://api.open-meteo.com/v1/forecast"
COUNTY_API = "https://geo.fcc.gov/api/census/area"


def normalize_zip(value) -> str:
    if isinstance(value, int):
        # YAML reads an unquoted 02134 as an octal number; there's no getting it back.
        if value < 10000:
            raise SystemExit(f"location.zip looks mangled ({value}). Put it in quotes: zip: \"0{value:o}\"")
        value = str(value)
    m = re.match(r"^\s*(\d{5})(-\d{4})?\s*$", str(value))
    if not m:
        raise SystemExit(f"location.zip must be a 5-digit US ZIP code, got {value!r}")
    return m.group(1)


def lookup(zip_code: str | None = None, lat: float | None = None, lon: float | None = None) -> dict:
    """Return {"zip", "lat", "lon", "place", "county", "timezone"}; raises on failure."""
    out = {"zip": zip_code, "lat": lat, "lon": lon, "place": "", "county": ""}
    with httpx.Client(timeout=15) as http:
        if zip_code:
            r = http.get(ZIP_API.format(zip=zip_code))
            if r.status_code == 404:
                raise SystemExit(f"ZIP code {zip_code} wasn't found.")
            r.raise_for_status()
            place = r.json()["places"][0]
            out.update(lat=float(place["latitude"]), lon=float(place["longitude"]),
                       place=f"{place['place name']}, {place['state abbreviation']}")

        r = http.get(TZ_API, params={"latitude": out["lat"], "longitude": out["lon"],
                                     "timezone": "auto", "forecast_days": 1})
        r.raise_for_status()
        out["timezone"] = r.json()["timezone"]

        # The county is nice-to-have for the area name; don't fail without it.
        try:
            r = http.get(COUNTY_API, params={"lat": out["lat"], "lon": out["lon"], "format": "json"})
            r.raise_for_status()
            out["county"] = r.json()["results"][0]["county_name"]
        except Exception as e:
            log.warning("County lookup failed: %s", e)
    return out


def cache_path(cfg: dict) -> Path:
    return Path(cfg["bot"]["db_path"]).with_suffix(".location.json")


def save_cache(cfg: dict, key: str, found: dict):
    found["key"] = key
    try:
        cache_path(cfg).write_text(json.dumps(found, indent=2))
    except OSError as e:
        log.warning("Couldn't cache location to %s: %s", cache_path(cfg), e)


def resolve(cfg: dict) -> bool:
    """Fill missing location fields in cfg in place.

    Returns False when no location is configured yet (an admin sets it over
    the mesh with `zip`). A lookup failure without a cache raises SystemExit
    so systemd retries once the network is up.
    """
    loc = cfg["location"]
    have_coords = loc.get("lat") is not None and loc.get("lon") is not None
    if have_coords and loc.get("timezone") and loc.get("name"):
        return True
    zip_code = normalize_zip(loc["zip"]) if loc.get("zip") else None
    if not zip_code and not have_coords:
        log.info("No location yet; waiting for an admin to send 'zip <code>'")
        return False

    key = zip_code or f"{loc['lat']},{loc['lon']}"
    try:
        cached = json.loads(cache_path(cfg).read_text())
    except (OSError, ValueError):
        cached = {}

    if cached.get("key") == key:
        found = cached
    else:
        try:
            found = lookup(zip_code, None if zip_code else loc["lat"], None if zip_code else loc["lon"])
        except SystemExit:
            raise
        except Exception as e:
            raise SystemExit(f"Couldn't look up location {key} ({e}). Check the network, "
                             "or set location.lat, lon, timezone and name in the config.")
        save_cache(cfg, key, found)

    if not have_coords:
        loc["lat"], loc["lon"] = found["lat"], found["lon"]
    loc["timezone"] = loc.get("timezone") or found["timezone"]
    loc["name"] = loc.get("name") or found.get("county") or found.get("place", "")
    log.info("Location: %s (%.4f, %.4f, %s)", loc["name"], loc["lat"], loc["lon"], loc["timezone"])
    return True
