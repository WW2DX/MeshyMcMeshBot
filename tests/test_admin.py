import asyncio
import time

import pytest

from meshymcmeshbot import config, settings
from meshymcmeshbot.bot import Bot
from meshymcmeshbot.db import DB
from meshymcmeshbot.features import admin
from meshymcmeshbot.settings import BY_KEY
from meshymcmeshbot.transport import ConsoleTransport, Incoming


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
    path.write_text(f"bot: {{db_path: '{tmp_path}/t.db', quiet_hours: {{}}}}\n")
    cfg = config.load(path)
    b = Bot(cfg, ConsoleTransport(cfg))
    admin.setup(b)
    return b


def dm(bot, name, text):
    key = bot.t._key_for(name)
    run(bot._on_message(Incoming(kind="dm", sender_name=name, sender_key=key, text=text, ts=int(time.time()))))
    return drain(bot)


def test_unclaimed_bot_writes_setup_code(bot, tmp_path):
    code = bot.db.get_meta("setup_code")
    assert code and len(code) == 6
    assert (tmp_path / "setup-code.txt").read_text().strip() == code


def test_claim_with_code_makes_admin_once(bot, tmp_path):
    code = bot.db.get_meta("setup_code")
    assert "not the setup code" in dm(bot, "Mallory", "claim 000000")[0]
    assert "admin" in dm(bot, "Lee", f"claim {code[:3]}-{code[3:]}")[0]
    assert bot.is_admin(bot.t._key_for("Lee"))
    assert not (tmp_path / "setup-code.txt").exists()
    assert "already set up" in dm(bot, "Mallory", f"claim {code}")[0]


def test_claim_locks_out_after_repeated_failures(bot):
    code = bot.db.get_meta("setup_code")
    for _ in range(admin.MAX_CLAIM_FAILURES_PER_HOUR):
        dm(bot, "Mallory", "claim 111111")
    assert "Too many" in dm(bot, "Mallory", f"claim {code}")[0]


def test_admin_settings_persist_and_layer(bot):
    code = bot.db.get_meta("setup_code")
    dm(bot, "Lee", f"claim {code}")
    assert "Admins only" in dm(bot, "Mallory", "set quiet off")[0]
    assert "✅ quiet = off" in dm(bot, "Lee", "set quiet off")[0]
    assert bot.restart_pending
    assert "wxtimes = 06:00,12:30" in dm(bot, "Lee", "set wxtimes 12:30, 6")[0]
    assert "one of" in dm(bot, "Lee", "set floodlevel huge")[0]

    # A fresh start (what the restart does) sees the stored values.
    cfg = config.load(None)
    cfg["bot"]["db_path"] = bot.bcfg["db_path"]
    settings.apply(cfg, DB(cfg["bot"]["db_path"]))
    assert cfg["bot"]["quiet_hours"] == {}
    assert cfg["weather"]["post_times"] == ["06:00", "12:30"]
    assert cfg["bot"]["admins"] == [bot.t._key_for("Lee")]


def test_list_add_del_and_last_admin_guard(bot):
    dm(bot, "Lee", f"claim {bot.db.get_meta('setup_code')}")
    assert "Added feed #1" in dm(bot, "Lee", "add feed Town Herald https://example.com/rss")[0]
    assert bot.cfg["news"]["feeds"] == [{"name": "Town Herald", "url": "https://example.com/rss"}]
    dm(bot, "Lee", "add cal abc123@group.calendar.google.com")
    assert bot.cfg["events"]["ical_urls"][0].endswith("abc123%40group.calendar.google.com/public/basic.ics")
    assert "Removed feed #1" in dm(bot, "Lee", "del feed 1")[0]
    assert "last admin" in dm(bot, "Lee", "del admin 1")[0]
    dm(bot, "Al", "hi")  # Al's node is now known
    assert "now an admin" in dm(bot, "Lee", "add admin al")[0]
    assert "Al" in dm(bot, "Lee", "list admins")[0]


def test_hello_world_only_once(bot):
    run(bot.startup_hooks[0]())
    assert "Hello world" in drain(bot)[0]
    run(bot.startup_hooks[0]())
    assert drain(bot) == []


def test_setting_parsers():
    assert settings.parse(BY_KEY["quiet"], "22:30-5") == {"start": "22:30", "end": "05:00"}
    assert settings.parse(BY_KEY["weather"], "off") is False
    assert settings.parse(BY_KEY["statstimes"], "off") == []
    with pytest.raises(ValueError):
        settings.parse(BY_KEY["wxtimes"], "25")
    assert settings.show(BY_KEY["airnowkey"], "secret123") == "(set)"
