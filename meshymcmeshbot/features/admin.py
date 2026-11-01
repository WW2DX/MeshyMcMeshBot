"""Zero-config setup: hello world, claiming the bot, and changing settings over DM.

On first start the bot has no admin. It writes a one-time setup code to the
data directory (the installer prints it), and the first node to DM
`claim <code>` becomes admin. From then on, admins configure everything over
the mesh. Most changes restart the bot a few seconds later to take effect.
"""

import asyncio
import logging
import os
import re
import secrets
import time
from pathlib import Path

from .. import location, settings
from ..settings import BY_KEY, LISTS

log = logging.getLogger(__name__)

CODE_FILE = "setup-code.txt"
MAX_CLAIM_FAILURES_PER_HOUR = 5
APPLY_DELAY = 15


def code_path(bot) -> Path:
    return Path(bot.bcfg["db_path"]).parent / CODE_FILE


def ensure_setup_code(bot) -> str | None:
    """The current one-time setup code, creating it if the bot is unclaimed."""
    path = code_path(bot)
    if bot.bcfg["admins"]:
        path.unlink(missing_ok=True)
        return None
    code = bot.db.get_meta("setup_code")
    if not code:
        code = f"{secrets.randbelow(10**6):06d}"
        bot.db.set_meta("setup_code", code)
    try:
        path.write_text(code + "\n")
        os.chmod(path, 0o600)
    except OSError as e:
        log.warning("Couldn't write %s: %s", path, e)
    log.warning("Not claimed yet. Setup code %s-%s: DM the bot 'claim %s'", code[:3], code[3:], code)
    return code


def reset_admins(db):
    """Recovery from the Pi: forget all admins and issue a new setup code."""
    settings.delete(db, "bot.admins")
    db.execute("DELETE FROM meta WHERE key='setup_code'")


def setup(bot):
    ensure_setup_code(bot)

    def save(path: str, value):
        settings.save(bot.db, path, value)
        settings.set_path(bot.cfg, path, value)

    def known_nodes() -> dict[str, str]:
        nodes = {r["pubkey"]: r["name"] for r in bot.db.all("SELECT pubkey, name FROM nodes")}
        nodes.update({k: c["name"] for k, c in bot.t.contacts().items() if c["name"]})
        return nodes

    def node_label(key: str) -> str:
        name = known_nodes().get(key) or next(
            (n for k, n in known_nodes().items() if k.startswith(key)), "?")
        return f"{name} ({key[:8]})"

    # --- first start ---------------------------------------------------------

    async def hello():
        if not bot.db.get_meta("hello_sent"):
            await bot.post(f"👋 Hello world! I'm {bot.t.self_name}, a new community bot for this mesh. "
                           "Getting set up - more soon!")
            bot.db.set_meta("hello_sent", str(int(time.time())))
        area = bot.cfg["location"]["name"]
        if bot.has_location and area and bot.db.get_meta("announced_area") != area:
            await bot.post(f"📍 Now serving {area}! Send {bot.bcfg['prefix']}help to see what I can do.")
            bot.db.set_meta("announced_area", area)

    bot.startup_hooks.append(hello)

    @bot.command("claim", "claim <setup code>: become the bot's first admin", dm_only=True)
    async def _claim(ctx):
        if bot.bcfg["admins"]:
            return "I'm already set up. Ask an admin to 'add admin' you."
        now = time.time()
        fails = [float(t) for t in (bot.db.get_meta("claim_failures") or "").split(",") if t]
        fails = [t for t in fails if now - t < 3600]
        if len(fails) >= MAX_CLAIM_FAILURES_PER_HOUR:
            return "Too many wrong codes. Try again in an hour."
        code = bot.db.get_meta("setup_code") or ""
        if not code or not secrets.compare_digest(re.sub(r"\D", "", ctx.args), code):
            fails.append(now)
            bot.db.set_meta("claim_failures", ",".join(str(t) for t in fails))
            return "That's not the setup code. It's printed at the end of the install."
        save("bot.admins", [ctx.msg.sender_key.lower()])
        bot.db.execute("DELETE FROM meta WHERE key IN ('setup_code', 'claim_failures')")
        code_path(bot).unlink(missing_ok=True)
        log.info("Claimed by %s (%s)", ctx.msg.sender_name, ctx.msg.sender_key[:12])
        nxt = "send 'zip <your ZIP code>'" if not bot.has_location else "send 'setup' for the checklist"
        return f"🔑 You're the admin, {ctx.msg.sender_name}! Next, {nxt}."

    # --- location ------------------------------------------------------------

    @bot.command("zip", "zip <code>: set the bot's area from a US ZIP code", admin=True, dm_only=True)
    async def _zip(ctx):
        try:
            z = location.normalize_zip(ctx.args)
        except SystemExit as e:
            return str(e)
        try:
            found = await asyncio.to_thread(location.lookup, z)
        except SystemExit as e:
            return str(e)
        except Exception as e:
            log.warning("ZIP lookup failed: %s", e)
            return "Couldn't look that up right now (is the Pi online?). Try again shortly."
        location.save_cache(bot.cfg, z, found)
        save("location.zip", z)
        bot.request_restart(5)
        area = settings.stored(bot.db).get("location.name") or found["county"] or found["place"]
        return (f"📍 {found['place']} ({found['county'] or 'county unknown'}), {found['timezone']}. "
                f"Area name: {area} (change with 'set area <name>'). Restarting to apply...")

    # --- settings ------------------------------------------------------------

    @bot.command("settings", "settings: list what can be changed", admin=True, dm_only=True)
    async def _settings(ctx):
        return ("Settings: " + " ".join(s.key for s in settings.SETTINGS) +
                " | 'set <name>' shows one, 'set <name> <value>' changes it, 'unset <name>' resets it. "
                "Lists: " + " ".join(LISTS) + " (add/del/list)")

    @bot.command("set", "set <name> [value]: show or change a setting", aliases=("get",),
                 admin=True, dm_only=True)
    async def _set(ctx):
        key, _, raw = ctx.args.partition(" ")
        s = BY_KEY.get(key.lower())
        if s is None:
            return "Unknown setting. Send 'settings' for the list."
        if not raw.strip():
            return f"{s.key} = {settings.show(s, settings.get_path(bot.cfg, s.path))} ({s.help})"
        if s.key == "zip":
            ctx.args = raw
            return await _zip(ctx)
        try:
            value = settings.parse(s, raw)
        except ValueError as e:
            return f"{s.key}: {e}"
        save(s.path, value)
        bot.request_restart(APPLY_DELAY)
        return f"✅ {s.key} = {settings.show(s, value)}. Applying in {APPLY_DELAY}s."

    @bot.command("unset", "unset <name>: put a setting back to default", admin=True, dm_only=True)
    async def _unset(ctx):
        s = BY_KEY.get(ctx.args.strip().lower())
        if s is None:
            return "Unknown setting. Send 'settings' for the list."
        settings.delete(bot.db, s.path)
        bot.request_restart(APPLY_DELAY)
        return f"↩️ {s.key} back to default. Applying in {APPLY_DELAY}s."

    # --- lists ---------------------------------------------------------------

    def resolve_admin(arg: str) -> tuple[str | None, str]:
        nodes = known_nodes()
        if arg.startswith("@"):
            matches = [k for k in nodes if k.startswith(arg[1:].lower())]
        else:
            matches = [k for k, n in nodes.items() if n.lower() == arg.lower()]
        if not matches:
            return None, "I don't know that node. It needs to advertise first."
        if len(matches) > 1:
            return None, "Several match: " + " ".join(f"@{k[:8]}" for k in matches[:4])
        return matches[0], ""

    @bot.command("add", "add <feed|cal|gauge|repeater|admin> <value>", admin=True, dm_only=True)
    async def _add(ctx):
        kind, _, raw = ctx.args.partition(" ")
        kind = kind.lower().rstrip("s")
        if kind not in LISTS:
            return "Add what? feed, cal, gauge, repeater or admin."
        path, usage = LISTS[kind]
        if kind == "admin":
            item, err = resolve_admin(raw.strip())
            if err:
                return err
        else:
            try:
                item = settings.parse_list_item(kind, raw)
            except ValueError as e:
                return f"Usage: {e}"
        items = list(settings.get_path(bot.cfg, path))
        if item in items:
            return "Already on the list."
        items.append(item)
        save(path, items)
        if kind == "admin":  # takes effect immediately, no restart needed
            return f"➕ {node_label(item)} is now an admin."
        bot.request_restart(APPLY_DELAY)
        return f"➕ Added {kind} #{len(items)}. Applying in {APPLY_DELAY}s."

    @bot.command("del", "del <feed|cal|gauge|repeater|admin> <number>", aliases=("remove",),
                 admin=True, dm_only=True)
    async def _del(ctx):
        kind, _, raw = ctx.args.partition(" ")
        kind = kind.lower().rstrip("s")
        if kind not in LISTS:
            return "Delete what? feed, cal, gauge, repeater or admin."
        path = LISTS[kind][0]
        items = list(settings.get_path(bot.cfg, path))
        raw = raw.strip().lstrip("#")
        if not raw.isdigit() or not 1 <= int(raw) <= len(items):
            return f"Send 'list {kind}' and use the number, e.g. del {kind} 1"
        if kind == "admin" and len(items) == 1:
            return "Can't remove the last admin."
        removed = items.pop(int(raw) - 1)
        save(path, items)
        if kind == "admin":
            return f"➖ {node_label(removed)} is no longer an admin."
        bot.request_restart(APPLY_DELAY)
        return f"➖ Removed {kind} #{raw}. Applying in {APPLY_DELAY}s."

    @bot.command("list", "list <feed|cal|gauge|repeater|admin>", admin=True, dm_only=True)
    async def _list(ctx):
        kind = ctx.args.strip().lower().rstrip("s")
        if kind not in LISTS:
            return "List what? " + ", ".join(LISTS)
        path, usage = LISTS[kind]
        items = settings.get_path(bot.cfg, path)
        if not items:
            return f"No {kind}s yet. {usage}"
        show = node_label if kind == "admin" else lambda i: settings.show_item(kind, i)
        return "\n".join(f"{n}) {show(i)}" for n, i in enumerate(items, 1))

    # --- overview ------------------------------------------------------------

    @bot.command("setup", "setup: configuration checklist", admin=True, dm_only=True)
    async def _setup(ctx):
        c = bot.cfg
        loc = c["location"]
        if bot.has_location:
            where = f"✅ {loc['name']} ({loc['zip'] or 'lat/lon'})"
        elif loc.get("zip"):
            where = f"⏳ ZIP {loc['zip']} (applying)"
        else:
            where = "❌ no ZIP"
        n = lambda path: len(settings.get_path(c, path))
        text = (f"Setup: {where} | admins {n('bot.admins')} | feeds {n('news.feeds')} | "
                f"cals {n('events.ical_urls')} | gauges {n('rivers.gauges')} | "
                f"repeaters {n('repeaters.watch')}")
        if bot.restart_pending:
            text += " | ⏳ changes apply shortly"
        elif not bot.has_location:
            text += " | Next: zip <code>"
        elif not c["news"]["feeds"]:
            text += " | Next: add feed <name> <rss url>"
        return text

    @bot.command("restart", "restart: restart the bot", admin=True, dm_only=True)
    async def _restart(ctx):
        bot.request_restart(2)
        return "♻️ Restarting..."
