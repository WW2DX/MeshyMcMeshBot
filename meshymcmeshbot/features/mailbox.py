"""Store-and-forward mailbox.

Mail is addressed to a node's *public key*, not its name, and can only be
read over a DM (which MeshCore authenticates), so a node that copies someone's
name can't read their mail. When the recipient's node shows up (advert, DM, or
channel post) the bot DMs it a "you have mail" notice.
"""

import time

from ..text import truncate


class Mailbox:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["mailbox"]
        self.db = bot.db

    def unread(self, key: str) -> list:
        return self.db.all(
            "SELECT * FROM mail WHERE to_key=? AND delivered IS NULL ORDER BY created", (key,)
        )

    def known_nodes(self) -> list[tuple[str, str]]:
        """(pubkey, name) for every node we know a name for."""
        nodes = {r["pubkey"]: r["name"] for r in self.db.all("SELECT pubkey, name FROM nodes")}
        for key, c in self.bot.t.contacts().items():
            if c["name"]:
                nodes[key] = c["name"]
        return [(k, n) for k, n in nodes.items() if n]

    def resolve(self, args: str) -> tuple[list[tuple[str, str]], str]:
        """Split "<recipient> <message>" -> (matching nodes, message).

        Names may contain spaces, so try the longest known name first.
        "@a1b2c3" addresses by public key prefix.
        """
        if args.startswith("@"):
            prefix, _, body = args[1:].partition(" ")
            matches = [(k, n) for k, n in self.known_nodes() if k.startswith(prefix.lower())]
            return matches, body.strip()
        low = args.lower()
        nodes = sorted(self.known_nodes(), key=lambda kn: -len(kn[1]))
        for key, name in nodes:
            if low.startswith(name.lower() + " "):
                matches = [(k, n) for k, n in nodes if n.lower() == name.lower()]
                return matches, args[len(name):].strip()
        return [], ""

    def send(self, from_key: str, from_name: str, to_key: str, body: str) -> str | None:
        """Store a message. Returns an error string, or None on success."""
        day_ago = int(time.time()) - 86400
        sent = self.db.one(
            "SELECT COUNT(*) n FROM mail WHERE from_key=? AND created > ?", (from_key, day_ago)
        )["n"]
        if sent >= self.cfg["max_sent_per_day"]:
            return "You've hit today's mail limit."
        if len(self.unread(to_key)) >= self.cfg["max_per_recipient"]:
            return "Their mailbox is full."
        self.db.execute(
            "INSERT INTO mail (to_key, from_key, from_name, body, created) VALUES (?,?,?,?,?)",
            (to_key, from_key, from_name, body, int(time.time())),
        )
        # A fresh message deserves a fresh notice.
        self.db.execute("DELETE FROM mail_notify WHERE to_key=?", (to_key,))
        return None

    async def maybe_notify(self, key: str):
        msgs = self.unread(key)
        if not msgs:
            return
        row = self.db.one("SELECT last_notified FROM mail_notify WHERE to_key=?", (key,))
        cooldown = self.cfg["notify_cooldown_hours"] * 3600
        if row and time.time() - row["last_notified"] < cooldown:
            return
        self.db.execute(
            "INSERT OR REPLACE INTO mail_notify (to_key, last_notified) VALUES (?,?)",
            (key, int(time.time())),
        )
        senders = ", ".join(sorted({m["from_name"] for m in msgs}))
        await self.bot.dm(key, f"📬 You have {len(msgs)} msg(s) from {senders}. Reply 'read'.")

    def expire(self):
        cutoff = int(time.time()) - self.cfg["expire_days"] * 86400
        self.db.execute("DELETE FROM mail WHERE created < ?", (cutoff,))


def setup(bot):
    if not bot.cfg["mailbox"]["enabled"]:
        return
    box = Mailbox(bot)

    @bot.command("mail", "mail <name> <msg> (or mail @keyprefix <msg>)", aliases=("m",), dm_only=True)
    async def _mail(ctx):
        matches, body = box.resolve(ctx.args)
        if not matches:
            return "Who's that? I only know nodes I've heard. Try: mail <name> <msg>"
        if len(matches) > 1:
            opts = " ".join(f"@{k[:6]}" for k, _ in matches[:4])
            return f"Several nodes are named that. Use one: {opts}"
        if not body:
            return "Message is empty."
        to_key, to_name = matches[0]
        err = box.send(ctx.msg.sender_key, ctx.msg.sender_name, to_key, body)
        if err:
            return err
        # If they're reachable right now, tell them.
        await box.maybe_notify(to_key)
        return f"✉️ Saved for {to_name}. I'll let them know when their node shows up."

    @bot.command("inbox", "inbox: how many messages are waiting", dm_only=True)
    async def _inbox(ctx):
        msgs = box.unread(ctx.msg.sender_key)
        if not msgs:
            return "📭 No mail."
        senders = ", ".join(sorted({m["from_name"] for m in msgs}))
        return f"📬 {len(msgs)} msg(s) from {senders}. Send 'read'."

    @bot.command("read", "read: deliver your waiting messages", aliases=("r",), dm_only=True)
    async def _read(ctx):
        msgs = box.unread(ctx.msg.sender_key)
        if not msgs:
            return "📭 No mail."
        batch = msgs[:3]
        budget = bot.bcfg["max_msg_bytes"]
        for m in batch:
            head = f"From {m['from_name']} ({bot.ago(m['created'])}): "
            await ctx.reply(head + truncate(m["body"], budget * 3))
            bot.db.execute("UPDATE mail SET delivered=? WHERE id=?", (int(time.time()), m["id"]))
        left = len(msgs) - len(batch)
        return f"{left} more - send 'read' again." if left else None

    async def on_seen(key: str):
        await box.maybe_notify(key)

    async def on_message(msg):
        if msg.kind == "dm" and msg.sender_key:
            word = msg.text.lower().lstrip(bot.bcfg["prefix"]).split(" ")[0]
            if word not in ("read", "r", "inbox"):
                await box.maybe_notify(msg.sender_key)
        elif msg.kind == "chan":
            # Channel posts only carry a name; DM the matching node(s), never the channel.
            for key, name in box.known_nodes():
                if name == msg.sender_name:
                    await box.maybe_notify(key)

    bot.advert_hooks.append(on_seen)
    bot.message_hooks.append(on_message)
    bot.schedule("mail-expire", box.expire, every_seconds=6 * 3600, respect_quiet_hours=False)
