import asyncio
import time

import pytest

from meshymcmeshbot import config
from meshymcmeshbot.bot import Bot
from meshymcmeshbot.features import intro
from meshymcmeshbot.text import paginate
from meshymcmeshbot.transport import NODE_CHAT, ConsoleTransport


def drain(bot) -> list[str]:
    out = []
    while not bot._queue.empty():
        out.append(bot._queue.get_nowait()[2])
    return out


@pytest.fixture
def bot(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(f"bot: {{db_path: '{tmp_path}/t.db', name: DutchessCounty_MeshBot}}\n"
                    "location: {name: Dutchess County, lat: 41.7, lon: -73.9, timezone: America/New_York}\n")
    b = Bot(config.load(path), ConsoleTransport(config.load(path)))
    intro.setup(b)
    return b


def run_job(bot):
    job = next(j for j in bot.jobs if j.name == "intro")
    asyncio.run(job.fn())
    return drain(bot)


def test_default_intro_fits_one_channel_message(bot):
    asyncio.run(bot.commands["intronow"].fn(type("C", (), {"is_dm": True})()))
    parts = drain(bot)
    assert len(parts) == 1 and "!help" in parts[0] and "Dutchess County" in parts[0]
    assert paginate(parts[0], bot._budget("chan"), 2) == parts


def test_weekly_and_only_when_someone_new(bot):
    today = intro.DAYS[bot.now().weekday()]
    bot.cfg["intro"]["day"] = intro.DAYS[(bot.now().weekday() + 1) % 7]
    assert run_job(bot) == []  # wrong day

    bot.cfg["intro"]["day"] = today
    assert len(run_job(bot)) == 1  # first intro ever
    bot.db.set_meta("intro_last", str(int(time.time()) - 7 * 86400))
    assert run_job(bot) == []  # nobody new since

    bot.db.upsert_node("ab" * 32, "Newbie", node_type=NODE_CHAT)
    assert len(run_job(bot)) == 1
