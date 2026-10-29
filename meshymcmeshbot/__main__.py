import argparse
import asyncio
import logging

from . import config
from .bot import Bot
from .features import setup_all
from .transport import ConsoleTransport, MeshCoreTransport


def main():
    ap = argparse.ArgumentParser(prog="meshymcmeshbot")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--console", action="store_true",
                    help="simulate the mesh on stdin/stdout instead of using the radio")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # The meshcore library logs every frame at INFO; keep it quieter.
    logging.getLogger("meshcore").setLevel(logging.DEBUG if args.verbose else logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = config.load(args.config)
    transport = ConsoleTransport(cfg) if args.console else MeshCoreTransport(cfg)
    bot = Bot(cfg, transport)
    setup_all(bot)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
