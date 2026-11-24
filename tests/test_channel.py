import asyncio
from types import SimpleNamespace

import pytest
from meshcore import EventType

from meshymcmeshbot import config, settings
from meshymcmeshbot.bot import Bot
from meshymcmeshbot.settings import BY_KEY
from meshymcmeshbot.transport import PUBLIC_CHANNEL_SECRET, ConsoleTransport, Incoming, MeshCoreTransport


class FakeCommands:
    def __init__(self, slots):
        self.slots = list(slots)  # (name, secret) per slot
        self.added = []
        self.sent = []

    async def send_device_query(self):
        return SimpleNamespace(type=EventType.DEVICE_INFO, payload={"max_channels": len(self.slots)})

    async def get_channel(self, i):
        name, secret = self.slots[i]
        return SimpleNamespace(type=EventType.CHANNEL_INFO,
                               payload={"channel_name": name, "channel_secret": secret})

    async def set_channel(self, i, name):
        self.added.append((i, name))
        return SimpleNamespace(type=EventType.OK, payload={})

    async def send_chan_msg(self, i, text):
        self.sent.append((i, text))
        return SimpleNamespace(type=EventType.OK, payload={}, is_error=lambda: False)


def transport(slots, main, **routes):
    cfg = config.load(None)
    cfg["bot"]["channel"] = main
    cfg["routes"].update(routes)
    t = MeshCoreTransport(cfg)
    t.mc = SimpleNamespace(commands=FakeCommands(slots))
    asyncio.run(t._find_channels())
    return t


EMPTY = ("", bytes(16))
PUBLIC = ("Public", PUBLIC_CHANNEL_SECRET)


def test_finds_existing_channel_by_name():
    t = transport([PUBLIC, ("#dutchess-county", b"k" * 16), EMPTY], "dutchess-county")
    assert t.channel_name == "#dutchess-county"
    assert t.channel_names() == ["#dutchess-county"]


def test_adds_missing_hashtag_channels_to_free_slots():
    t = transport([PUBLIC, EMPTY, EMPTY], "#dutchess-county", weather=["#weather"])
    assert t.mc.commands.added == [(1, "#dutchess-county"), (2, "#weather")]
    assert t.channel_names() == ["#dutchess-county", "#weather"]


def test_never_uses_public_or_unset():
    assert transport([PUBLIC], "").channel_names() == []
    # A renamed Public channel is still Public.
    t = transport([("#town", PUBLIC_CHANNEL_SECRET)], "#town")
    assert (t.channel_name, t.channel_names()) == ("", [])


def test_sends_to_the_named_channel_or_main():
    t = transport([PUBLIC, ("#main", b"m" * 16), ("#weather", b"w" * 16)], "#main", weather=["#weather"])
    asyncio.run(t.send_channel("a"))
    asyncio.run(t.send_channel("b", "Weather"))
    assert not asyncio.run(t.send_channel("c", "#elsewhere"))
    assert t.mc.commands.sent == [(1, "a"), (2, "b")]


def test_channels_setting_parses_lists():
    assert settings.parse(BY_KEY["wxchan"], "#weather, #dutchess-county") == ["#weather", "#dutchess-county"]
    with pytest.raises(ValueError):
        settings.parse(BY_KEY["alertchan"], "#weather public")


@pytest.fixture
def bot(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(f"bot: {{db_path: '{tmp_path}/t.db', channel: '#main', quiet_hours: {{}}}}\n"
                    "routes: {weather: ['#weather'], alerts: ['#main', '#weather']}\n")
    cfg = config.load(path)
    return Bot(cfg, ConsoleTransport(cfg))


def queued(bot):
    out = []
    while not bot._queue.empty():
        _, channel, text = bot._queue.get_nowait()
        out.append((channel, text))
    return out


def test_posts_follow_routes(bot):
    asyncio.run(bot.post("forecast", kind="weather"))
    asyncio.run(bot.post("alert", kind="alerts"))
    asyncio.run(bot.post("headlines", kind="news"))
    assert queued(bot) == [("#weather", "forecast"), ("#main", "alert"), ("#weather", "alert"),
                           (None, "headlines")]


def test_replies_go_back_to_the_channel_asked_on(bot):
    @bot.command("hi", "hi")
    async def _hi(ctx):
        return "hello"
    asyncio.run(bot._on_message(Incoming(kind="chan", sender_name="Ann", text="!hi", channel="#weather")))
    # Cooldown is per channel, so the same person can ask on another channel right away.
    asyncio.run(bot._on_message(Incoming(kind="chan", sender_name="Ann", text="!hi", channel="#main")))
    asyncio.run(bot._on_message(Incoming(kind="chan", sender_name="Ann", text="!hi", channel="#main")))
    assert queued(bot) == [("#weather", "hello"), ("#main", "hello")]
