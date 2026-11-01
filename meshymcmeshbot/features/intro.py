"""Weekly intro post, so people who just joined the channel learn the bot is there.

MeshCore doesn't say who joins a channel, so the welcome DM can't catch
everyone. This posts a short "here's how to use me" once a week, skipping
weeks when no new nodes have shown up since the last one.
"""

import logging
import time

from ..transport import NODE_CHAT

log = logging.getLogger(__name__)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def setup(bot):
    cfg = bot.cfg["intro"]

    def intro_text() -> str:
        return cfg["message"].format(bot=bot.t.self_name, prefix=bot.bcfg["prefix"],
                                     area=bot.cfg["location"]["name"] or "local")

    async def post_intro():
        if DAYS[bot.now().weekday()] != cfg["day"]:
            return
        last = int(bot.db.get_meta("intro_last") or 0)
        if cfg["only_if_new"] and last:
            new = bot.db.one("SELECT COUNT(*) n FROM nodes WHERE type=? AND first_seen > ?",
                             (NODE_CHAT, last))["n"]
            if not new:
                log.info("Skipping the weekly intro: no new nodes since the last one")
                return
        await bot.post(intro_text())
        bot.db.set_meta("intro_last", str(int(time.time())))

    if cfg["enabled"] and cfg["times"]:
        bot.schedule("intro", post_intro, times=cfg["times"])

    @bot.command("intronow", "intronow: post the intro to the channel now", admin=True)
    async def _intronow(ctx):
        await bot.post(intro_text())
        bot.db.set_meta("intro_last", str(int(time.time())))
        return "Posted." if ctx.is_dm else None
