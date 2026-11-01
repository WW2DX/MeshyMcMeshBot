import asyncio
from types import SimpleNamespace

from meshcore import EventType

from meshymcmeshbot import config
from meshymcmeshbot.transport import PUBLIC_CHANNEL_SECRET, MeshCoreTransport


class FakeCommands:
    def __init__(self, slots):
        self.slots = slots  # list of (name, secret)
        self.added = None

    async def send_device_query(self):
        return SimpleNamespace(type=EventType.DEVICE_INFO, payload={"max_channels": len(self.slots)})

    async def get_channel(self, i):
        name, secret = self.slots[i]
        return SimpleNamespace(type=EventType.CHANNEL_INFO,
                               payload={"channel_name": name, "channel_secret": secret})

    async def set_channel(self, i, name):
        self.added = (i, name)
        return SimpleNamespace(type=EventType.OK, payload={})


def find(want, slots):
    cfg = config.load(None)
    cfg["bot"]["channel"] = want
    t = MeshCoreTransport(cfg)
    t.mc = SimpleNamespace(commands=FakeCommands(slots))
    asyncio.run(t._find_channel())
    return t


EMPTY = ("", bytes(16))
PUBLIC = ("Public", PUBLIC_CHANNEL_SECRET)


def test_finds_existing_channel_by_name():
    t = find("dutchess-county", [PUBLIC, ("#dutchess-county", b"k" * 16), EMPTY])
    assert (t.channel_idx, t.channel_name) == (1, "#dutchess-county")


def test_adds_missing_hashtag_channel_to_first_free_slot():
    t = find("#dutchess-county", [PUBLIC, EMPTY, EMPTY])
    assert t.mc.commands.added == (1, "#dutchess-county")
    assert t.channel_idx == 1


def test_never_uses_public_or_unset():
    assert find("", [PUBLIC]).channel_idx is None
    # A renamed Public channel is still Public.
    assert find("#town", [("#town", PUBLIC_CHANNEL_SECRET)]).channel_idx is None
