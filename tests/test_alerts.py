import asyncio
import time

import pytest

from meshymcmeshbot import config
from meshymcmeshbot.bot import Bot
from meshymcmeshbot.features import airquality, quakes, repeaters, rivers, welcome
from meshymcmeshbot.transport import NODE_CHAT, NODE_REPEATER, Advert, ConsoleTransport, split_path


def run(coro):
    return asyncio.run(coro)


def drain(bot) -> list[str]:
    out = []
    while not bot._queue.empty():
        out.append(bot._queue.get_nowait()[2])
    return out


@pytest.fixture
def bot(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(f"bot: {{db_path: '{tmp_path}/t.db', quiet_hours: {{}}}}\nlocation: {{lat: 41.26, lon: -95.94, timezone: America/Chicago, name: Test}}\n")
    return Bot(config.load(path), ConsoleTransport(config.load(path)))


# --- transport / db plumbing -------------------------------------------------

def test_split_path_by_hash_size():
    assert split_path("a1b2c3", 1) == ["a1", "b2", "c3"]
    assert split_path("a1b2c3d4", 2) == ["a1b2", "c3d4"]


def test_relay_hash_matches_pubkey_prefix(bot):
    bot.db.mark_relays(["ab"])
    assert bot.db.relay_seen("abcdef0123") > 0
    assert bot.db.relay_seen("cdef") == 0


def test_contact_sync_does_not_trust_sender_clock(bot):
    future = int(time.time()) + 10 * 86400  # a node with its clock set wrong
    bot.db.sync_node("aa" * 32, "Clocky", last_advert=future)
    assert bot.db.node("aa" * 32)["last_seen"] <= time.time()
    bot.db.upsert_node("bb" * 32, "Bob")
    heard = bot.db.node("bb" * 32)["last_seen"]
    bot.db.sync_node("bb" * 32, "Bob", last_advert=future)
    assert bot.db.node("bb" * 32)["last_seen"] == heard


# --- welcome ------------------------------------------------------------------

def test_welcome_only_new_chat_nodes_after_settling(bot):
    bot.cfg["welcome"]["settle_days"] = 0
    welcome.setup(bot)
    key = bot.t._key_for("Carol")
    run(bot._on_advert(Advert(key, "Carol", NODE_CHAT)))
    run(bot._on_advert(Advert(key, "Carol", NODE_CHAT)))
    run(bot._on_advert(Advert("ee" * 32, "Hilltop", NODE_REPEATER)))
    msgs = drain(bot)
    assert len(msgs) == 1 and "Carol" in msgs[0]


def test_welcome_waits_during_settle_period(bot):
    welcome.setup(bot)  # default settle_days=3, DB was just created
    run(bot._on_advert(Advert(bot.t._key_for("Dan"), "Dan", NODE_CHAT)))
    assert drain(bot) == []


# --- repeaters ----------------------------------------------------------------

def test_repeater_down_then_back(bot, monkeypatch):
    bot.cfg["repeaters"].update(watch=["Hilltop"], offline_hours=1, notify="channel")
    rpt = repeaters.Repeaters(bot)
    key = "cd" * 32
    bot.db.upsert_node(key, "Hilltop", node_type=NODE_REPEATER)
    bot.started = time.time() - 7200
    bot.db.execute("UPDATE nodes SET last_seen=? WHERE pubkey=?", (int(time.time()) - 7200, key))

    run(rpt.check())
    assert "not heard" in drain(bot)[0]
    run(rpt.check())
    assert drain(bot) == []  # no repeat alarm

    bot.db.mark_relays(["cd"])
    run(rpt.check())
    assert "is back" in drain(bot)[0]


def test_repeater_restart_does_not_fake_recovery(bot):
    bot.cfg["repeaters"].update(watch=["Hilltop"], offline_hours=1, notify="channel")
    rpt = repeaters.Repeaters(bot)
    key = "cd" * 32
    bot.db.upsert_node(key, "Hilltop", node_type=NODE_REPEATER)
    bot.db.execute("UPDATE nodes SET last_seen=? WHERE pubkey=?", (int(time.time()) - 7200, key))
    bot.db.set_meta(f"rpt_down:{key}", "1")  # was down before the bot restarted
    bot.started = time.time()
    run(rpt.check())
    assert drain(bot) == []


# --- rivers -------------------------------------------------------------------

def gauge(obs_cat, obs, fc_cat="no_flooding", fc=None):
    return {"name": "Big River at Town",
            "status": {"observed": {"primary": obs, "floodCategory": obs_cat},
                       "forecast": {"primary": fc if fc is not None else obs, "floodCategory": fc_cat}},
            "flood": {"categories": {"minor": {"stage": 27}}}}


def test_river_alerts_on_rise_and_recovery(bot, monkeypatch):
    bot.cfg["rivers"]["gauges"] = ["TOWN1"]
    r = rivers.Rivers(bot)
    readings = iter([
        gauge("action", 22),               # below alert level (minor): quiet
        gauge("action", 25, "minor", 28),  # forecast to flood
        gauge("minor", 28),                # now flooding (same level as forecast: no repeat)
        gauge("no_flooding", 15),          # receded
    ])

    async def fake(lid):
        return next(readings)
    monkeypatch.setattr(r, "gauge", fake)

    run(r.poll()); assert drain(bot) == []
    run(r.poll()); assert "forecast to reach 28.0ft: MINOR" in drain(bot)[0]
    run(r.poll()); assert drain(bot) == []
    run(r.poll()); assert "back below minor" in drain(bot)[0]


# --- air quality --------------------------------------------------------------

def test_aqi_alert_with_hysteresis(bot, monkeypatch):
    air = airquality.Air(bot)
    values = iter([160, 155, 140, 120])

    async def fake():
        return next(values), "test"
    monkeypatch.setattr(air, "current", fake)

    run(air.poll()); assert "Unhealthy (AQI 160)" in drain(bot)[0]
    run(air.poll()); assert drain(bot) == []
    run(air.poll()); assert drain(bot) == []  # 140 is within hysteresis of 151
    run(air.poll()); assert "improved" in drain(bot)[0]


# --- quakes -------------------------------------------------------------------

def test_quakes_skip_stale_and_small_ones_in_quiet_hours(bot, monkeypatch):
    q = quakes.Quakes(bot)
    now_ms = time.time() * 1000
    found = [
        {"id": "new-big", "mag": 5.4, "place": "10 km N of A", "time": now_ms - 60_000},
        {"id": "new-small", "mag": 3.1, "place": "5 km S of B", "time": now_ms - 60_000},
        {"id": "old", "mag": 4.0, "place": "C", "time": now_ms - 6 * 3600_000},
    ]

    async def fake(days):
        return found
    monkeypatch.setattr(q, "recent", fake)
    monkeypatch.setattr(bot, "in_quiet_hours", lambda: True)

    run(q.poll())
    msgs = drain(bot)
    assert len(msgs) == 1 and "M5.4" in msgs[0]
    run(q.poll())
    assert drain(bot) == []  # all marked seen
