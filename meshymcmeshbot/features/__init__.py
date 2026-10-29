from . import events, fun, mailbox, news, weather

ALL = [fun, weather, news, events, mailbox]


def setup_all(bot):
    for mod in ALL:
        mod.setup(bot)
