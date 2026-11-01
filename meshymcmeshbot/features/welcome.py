"""Welcome DM for nodes the bot has never heard before."""

import logging
import time

from ..transport import NODE_CHAT

log = logging.getLogger(__name__)


def setup(bot):
    cfg = bot.cfg["welcome"]
    if not cfg["enabled"]:
        return
    sent: list[float] = []

    async def on_advert(adv, is_new):
        if not is_new or adv.node_type != NODE_CHAT or not adv.name:
            return
        installed = int(bot.db.get_meta("installed") or 0)
        if time.time() - installed < cfg["settle_days"] * 86400:
            return
        # A bus full of new nodes shouldn't turn into a burst of DMs.
        now = time.time()
        sent[:] = [t for t in sent if now - t < 3600]
        if len(sent) >= cfg["max_per_hour"]:
            log.info("Welcome rate limit hit; skipping %s", adv.name)
            return
        sent.append(now)
        area = bot.cfg["location"]["name"] or "local"
        await bot.dm(adv.pubkey, cfg["message"].format(name=adv.name, area=area, bot=bot.t.self_name))

    bot.advert_hooks.append(on_advert)
