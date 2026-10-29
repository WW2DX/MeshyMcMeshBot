import asyncio
import time

import pytest

from meshymcmeshbot import config
from meshymcmeshbot.bot import Bot
from meshymcmeshbot.features import mailbox
from meshymcmeshbot.features.weather import format_period, short_forecast
from meshymcmeshbot.text import blen, chunk, paginate, truncate
from meshymcmeshbot.transport import ConsoleTransport, Incoming


def test_chunk_respects_byte_budget_with_emoji():
    s = "📬 " * 100
    parts = chunk(s, 40)
    assert all(blen(p) <= 40 for p in parts)
    assert "".join(parts).count("📬") == 100


def test_truncate_adds_ellipsis():
    assert truncate("hello world", 8) == "hello…"
    assert truncate("short", 80) == "short"


def test_paginate_caps_parts():
    parts = paginate("word " * 200, 60, 2)
    assert len(parts) == 2
    assert parts[0].startswith("1/2 ")
    assert "DM me for more" in parts[-1]
    assert all(blen(p) <= 60 for p in parts)


def test_weather_formatting_is_compact():
    p = {"name": "Tonight", "isDaytime": False, "temperature": 52, "temperatureUnit": "F",
         "windSpeed": "5 to 10 mph", "windDirection": "E",
         "shortForecast": "Slight Chance Showers And Thunderstorms then Chance Rain",
         "probabilityOfPrecipitation": {"value": 61}}
    assert format_period(p) == "Tonight: Sl chc T-storms, Lo 52°F, E 5-10mph, 61% precip"
    assert short_forecast("Sunny") == "Sunny"


@pytest.fixture
def bot(tmp_path, monkeypatch):
    path = tmp_path / "c.yaml"
    path.write_text(f"bot: {{db_path: '{tmp_path}/t.db', quiet_hours: {{start: '22:00', end: '06:00'}}}}\n")
    cfg = config.load(path)
    b = Bot(cfg, ConsoleTransport(cfg))
    mailbox.setup(b)
    return b


def test_mail_resolves_names_with_spaces(bot):
    box = mailbox.Mailbox(bot)
    bob = bot.t._key_for("Bob K")
    bot.t._key_for("Bob")
    matches, body = box.resolve("bob k see you at the net")
    assert matches == [(bob, "Bob K")]
    assert body == "see you at the net"


def test_mail_is_bound_to_pubkey(bot):
    box = mailbox.Mailbox(bot)
    alice, bob = bot.t._key_for("Alice"), bot.t._key_for("Bob")
    assert box.send(alice, "Alice", bob, "hi") is None
    assert len(box.unread(bob)) == 1
    assert box.unread(alice) == []


def test_mail_notify_respects_cooldown(bot):
    box = mailbox.Mailbox(bot)
    alice, bob = bot.t._key_for("Alice"), bot.t._key_for("Bob")
    box.send(alice, "Alice", bob, "hi")

    async def go():
        await box.maybe_notify(bob)
        await box.maybe_notify(bob)
    asyncio.run(go())
    assert bot._queue.qsize() == 1


def test_channel_dm_only_command_redirects(bot):
    async def go():
        await bot._on_message(Incoming(kind="chan", sender_name="Al", text="!mail Bob hi", ts=int(time.time())))
    asyncio.run(go())
    kind, _, text = bot._queue.get_nowait()
    assert kind == "chan" and "DM me" in text


def test_channel_ignores_unprefixed_chatter(bot):
    async def go():
        await bot._on_message(Incoming(kind="chan", sender_name="Al", text="mail is slow today"))
    asyncio.run(go())
    assert bot._queue.empty()
