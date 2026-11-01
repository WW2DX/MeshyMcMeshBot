import argparse
import asyncio
import logging
import os
import sys

from . import config, location, settings
from .bot import Bot, RestartRequested
from .db import DB
from .features import admin, setup_all
from .transport import ConsoleTransport, MeshCoreTransport


def main():
    ap = argparse.ArgumentParser(prog="meshymcmeshbot")
    ap.add_argument("-c", "--config",
                    help="optional YAML config (default: ./config.yaml or /etc/meshbot/config.yaml "
                         "if present). Everything can be set over the mesh instead.")
    ap.add_argument("--console", action="store_true",
                    help="simulate the mesh on stdin/stdout instead of using the radio")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--lookup", metavar="ZIP",
                    help="show what a ZIP code resolves to, then exit")
    ap.add_argument("--setup-code", action="store_true",
                    help="print the one-time setup code for claiming the bot, then exit")
    ap.add_argument("--reset-admins", action="store_true",
                    help="forget all mesh-set admins and issue a new setup code, then exit")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # The meshcore library logs every frame at INFO; keep it quieter.
    logging.getLogger("meshcore").setLevel(logging.DEBUG if args.verbose else logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.lookup:
        found = location.lookup(location.normalize_zip(args.lookup))
        print(f"{found['place']} ({found['county'] or 'county unknown'})\n"
              f"  lat {found['lat']}, lon {found['lon']}, timezone {found['timezone']}")
        return

    cfg = config.load(args.config or config.find_config())
    db = DB(cfg["bot"]["db_path"])
    if args.reset_admins:
        admin.reset_admins(db)
        print("Admins cleared. Restart the bot to get a new setup code (or run --setup-code).")
        return
    settings.apply(cfg, db)

    if args.setup_code:
        if cfg["bot"]["admins"]:
            print("Already claimed. Use --reset-admins to start over.")
        else:
            bot = Bot(cfg, ConsoleTransport(cfg), db)
            code = admin.ensure_setup_code(bot)
            print(f"Setup code: {code[:3]}-{code[3:]}  (DM the bot: claim {code})")
        return

    location.resolve(cfg)
    transport = ConsoleTransport(cfg) if args.console else MeshCoreTransport(cfg)
    bot = Bot(cfg, transport, db)
    setup_all(bot)
    try:
        asyncio.run(bot.run())
    except RestartRequested:
        # Start over in-place so new settings apply (works with or without systemd).
        os.execv(sys.executable, [sys.executable, "-m", "meshymcmeshbot", *sys.argv[1:]])


if __name__ == "__main__":
    main()
