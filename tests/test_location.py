import json

import pytest

from meshymcmeshbot import config, location

FOUND = {"zip": "68102", "lat": 41.259, "lon": -95.9409, "place": "Omaha, NE",
         "county": "Douglas County", "timezone": "America/Chicago"}


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(f"bot: {{db_path: '{tmp_path}/t.db'}}\nlocation: {{zip: '68102'}}\n")
    return config.load(path)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(zip_code=None, lat=None, lon=None):
        seen.append(zip_code)
        return dict(FOUND)
    monkeypatch.setattr(location, "lookup", fake)
    return seen


def test_zip_fills_location_and_caches(cfg, calls):
    location.resolve(cfg)
    loc = cfg["location"]
    assert (loc["lat"], loc["lon"], loc["timezone"], loc["name"]) == \
        (41.259, -95.9409, "America/Chicago", "Douglas County")
    cfg["location"].update(lat=None, lon=None, timezone="", name="")
    location.resolve(cfg)  # second start: served from the cache
    assert calls == ["68102"]


def test_explicit_fields_override_lookup(cfg, calls):
    cfg["location"].update(name="Riverbend Mesh", timezone="America/Denver")
    location.resolve(cfg)
    assert cfg["location"]["name"] == "Riverbend Mesh"
    assert cfg["location"]["timezone"] == "America/Denver"
    assert cfg["location"]["lat"] == 41.259


def test_changing_zip_ignores_old_cache(cfg, calls, tmp_path):
    (tmp_path / "t.location.json").write_text(json.dumps(dict(FOUND, key="10001")))
    location.resolve(cfg)
    assert calls == ["68102"]


def test_zip_forms():
    assert location.normalize_zip("68102-1234") == "68102"
    assert location.normalize_zip(68102) == "68102"
    with pytest.raises(SystemExit):
        location.normalize_zip(1116)  # unquoted 02134, read by YAML as octal
    with pytest.raises(SystemExit):
        location.normalize_zip("6810")


def test_no_location_means_wait_for_admin(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(f"bot: {{db_path: '{tmp_path}/t.db'}}\n")
    cfg = config.load(path)
    assert location.resolve(cfg) is False
    assert cfg["location"]["lat"] is None
