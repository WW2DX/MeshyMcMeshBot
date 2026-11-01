import logging

from . import admin, airquality, events, fun, intro, mailbox, news, quakes, repeaters, rivers, weather, welcome

log = logging.getLogger(__name__)

ALL = [admin, fun, weather, news, events, mailbox, welcome, intro, repeaters, quakes, rivers, airquality]
# These need to know where the bot is; they switch on once an admin sets a ZIP.
NEEDS_LOCATION = {weather, quakes, rivers, airquality}


def setup_all(bot):
    for mod in ALL:
        if mod in NEEDS_LOCATION and not bot.has_location:
            log.info("%s waits for a location", mod.__name__.rsplit(".", 1)[-1])
            continue
        mod.setup(bot)
