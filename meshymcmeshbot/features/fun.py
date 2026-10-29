"""Everyday utility commands, a bulletin board, mesh stats, and admin tools."""

import time
from astral import LocationInfo, moon
from astral.sun import sun

# astral's moon.phase() runs 0-28: 0 new, 7 first quarter, 14 full, 21 last quarter.
MOON_PHASES = [
    (1, "🌑 New"), (6, "🌒 Waxing crescent"), (8, "🌓 First quarter"),
    (13, "🌔 Waxing gibbous"), (15, "🌕 Full"), (20, "🌖 Waning gibbous"),
    (22, "🌗 Last quarter"), (27, "🌘 Waning crescent"),
]
SYNODIC_DAYS = 29.53


def moon_name(phase: float) -> str:
    for limit, name in MOON_PHASES:
        if phase < limit:
            return name
    return "🌑 New"


def setup(bot):
    loc = bot.cfg["location"]
    where = LocationInfo(loc["name"], "", loc["timezone"], loc["lat"], loc["lon"])
    started = time.time()

    @bot.command("help", "help [cmd]: list commands", aliases=("?", "cmds"))
    async def _help(ctx):
        if ctx.args:
            cmd = bot.commands.get(ctx.args.lower().lstrip(bot.bcfg["prefix"]))
            return cmd.help if cmd else f"No command '{ctx.args}'."
        names = sorted({
            c.name for c in bot.commands.values()
            if not c.admin and (ctx.is_dm or not c.dm_only)
        })
        p = "" if ctx.is_dm else bot.bcfg["prefix"]
        text = "Cmds: " + " ".join(p + n for n in names)
        if not ctx.is_dm:
            text += " | DM me for mail & bbs"
        return text

    @bot.command("ping", "ping: check your signal to the bot", aliases=("test",))
    async def _ping(ctx):
        m = ctx.msg
        bits = []
        if m.hops is not None:
            bits.append("direct" if m.hops == 0 else f"{m.hops} hop{'s' * (m.hops != 1)}")
        if m.snr is not None:
            bits.append(f"SNR {m.snr:.1f}dB")
        detail = f" ({', '.join(bits)})" if bits else ""
        return f"🏓 pong @[{m.sender_name}]{detail}"

    @bot.command("sun", "sun: sunrise & sunset")
    async def _sun(ctx):
        s = sun(where.observer, date=bot.now().date(), tzinfo=bot.tz)
        f = lambda d: d.strftime("%-I:%M%p").lower()
        length = s["sunset"] - s["sunrise"]
        h, rem = divmod(int(length.total_seconds()), 3600)
        return f"☀️ Rise {f(s['sunrise'])}, set {f(s['sunset'])} ({h}h{rem // 60:02d}m of daylight)"

    @bot.command("moon", "moon: current moon phase")
    async def _moon(ctx):
        today = bot.now().date()
        phase = moon.phase(today)
        days = round((14 - phase) % 28 * SYNODIC_DAYS / 28)
        tail = f", full in {days}d" if 0 < days < 28 else ""
        return f"{moon_name(phase)} moon{tail}"

    @bot.command("time", "time: local date & time")
    async def _time(ctx):
        return bot.now().strftime("🕰 %a %b %-d, %-I:%M%p %Z")

    @bot.command("seen", "seen <name>: when a node was last heard")
    async def _seen(ctx):
        name = ctx.args.strip()
        if not name:
            return "Usage: seen <name>"
        node = bot.db.one(
            "SELECT name, last_seen FROM nodes WHERE name LIKE ? ORDER BY last_seen DESC", (name,)
        )
        chan = bot.db.one(
            "SELECT sender, MAX(ts) ts FROM chan_activity WHERE sender LIKE ?", (name,)
        )
        best = max(
            [(node["last_seen"], node["name"]) if node else (0, ""),
             (chan["ts"], chan["sender"]) if chan and chan["ts"] else (0, "")]
        )
        if not best[0]:
            return f"Haven't heard {name}."
        return f"👀 {best[1]} last heard {bot.ago(best[0])}"

    def stats_text() -> str:
        day_ago = int(time.time()) - 86400
        heard = bot.db.one("SELECT COUNT(*) n FROM nodes WHERE last_seen > ?", (day_ago,))["n"]
        row = bot.db.one(
            "SELECT COUNT(*) n, COUNT(DISTINCT sender) s FROM chan_activity WHERE ts > ?", (day_ago,)
        )
        top = bot.db.one(
            """SELECT sender, COUNT(*) n FROM chan_activity WHERE ts > ?
               GROUP BY sender ORDER BY n DESC LIMIT 1""", (day_ago,)
        )
        text = f"📊 Last 24h: {heard} nodes heard, {row['n']} channel msgs from {row['s']} {'person' if row['s'] == 1 else 'people'}"
        if top:
            text += f". Chattiest: {top['sender']} ({top['n']})"
        return text

    @bot.command("stats", "stats: mesh activity in the last 24h", aliases=("nodes",))
    async def _stats(ctx):
        return stats_text()

    @bot.command("about", "about: what is this bot", aliases=("info",))
    async def _about(ctx):
        up = int(time.time() - started)
        return (f"🤖 {bot.t.self_name}: community bot for {loc['name'] or 'the local mesh'}. "
                f"Send {bot.bcfg['prefix']}help. Up {up // 86400}d{up % 86400 // 3600}h")

    if bot.cfg["stats"]["post_times"]:
        async def post_stats():
            await bot.post(stats_text())
        bot.schedule("stats", post_stats, times=bot.cfg["stats"]["post_times"])

    # --- bulletin board -----------------------------------------------------

    bcfg = bot.cfg["bbs"]
    if bcfg["enabled"]:
        @bot.command("post", "post <text>: pin a note to the bulletin board", dm_only=True)
        async def _post(ctx):
            if not ctx.args:
                return "Usage: post <text>"
            bot.db.execute(
                "INSERT INTO bbs (author_key, author_name, body, created) VALUES (?,?,?,?)",
                (ctx.msg.sender_key, ctx.msg.sender_name, ctx.args[:300], int(time.time())),
            )
            bot.db.execute(
                "DELETE FROM bbs WHERE id NOT IN (SELECT id FROM bbs ORDER BY id DESC LIMIT ?)",
                (bcfg["max_posts"],),
            )
            return "📌 Posted. Others can see it with 'bbs'."

        @bot.command("bbs", "bbs: read the newest bulletin board notes", dm_only=True)
        async def _bbs(ctx):
            cutoff = int(time.time()) - bcfg["expire_days"] * 86400
            rows = bot.db.all(
                "SELECT * FROM bbs WHERE created > ? ORDER BY id DESC LIMIT 5", (cutoff,)
            )
            if not rows:
                return "📌 Board is empty. Add a note with: post <text>"
            return "\n".join(f"#{r['id']} {r['author_name']} ({bot.ago(r['created'])}): {r['body']}" for r in rows)

        @bot.command("unpost", "unpost <id>: remove your note", dm_only=True)
        async def _unpost(ctx):
            pid = ctx.args.lstrip("#")
            if ctx.is_admin:
                n = bot.db.execute("DELETE FROM bbs WHERE id=?", (pid,)).rowcount
            else:
                n = bot.db.execute(
                    "DELETE FROM bbs WHERE id=? AND author_key=?", (pid, ctx.msg.sender_key)
                ).rowcount
            return "Removed." if n else "Not found (you can only remove your own)."

    # --- admin --------------------------------------------------------------

    @bot.command("say", "say <text>: broadcast on the channel", admin=True, dm_only=True)
    async def _say(ctx):
        if ctx.args:
            await bot.post(f"📢 {ctx.args}")
            return "Sent."
        return "Usage: say <text>"

    @bot.command("status", "status: bot health", admin=True, dm_only=True)
    async def _status(ctx):
        up = int(time.time() - started)
        radio = await bot.t.status()
        mail = bot.db.one("SELECT COUNT(*) n FROM mail WHERE delivered IS NULL")["n"]
        return (f"up {up // 3600}h, {len(bot.t.contacts())} contacts, "
                f"{bot._queue.qsize()} queued, {mail} undelivered mail {radio}").strip()
