"""Headlines from RSS/Atom feeds (local paper, county site, school district...)."""

import asyncio
import logging

import feedparser

log = logging.getLogger(__name__)


class News:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg["news"]

    async def _fetch(self, feed: dict) -> list[dict]:
        try:
            r = await self.bot.http.get(feed["url"])
            r.raise_for_status()
        except Exception as e:
            log.warning("Feed %s failed: %s", feed.get("name"), e)
            return []
        parsed = await asyncio.to_thread(feedparser.parse, r.content)
        return [
            {"source": feed.get("name", ""), "title": " ".join(e.get("title", "").split()),
             "id": e.get("id") or e.get("link") or e.get("title")}
            for e in parsed.entries
            if e.get("title")
        ]

    async def latest(self) -> list[dict]:
        """Newest entries, interleaved across feeds so one busy feed can't dominate."""
        per_feed = await asyncio.gather(*(self._fetch(f) for f in self.cfg["feeds"]))
        out = []
        for i in range(max((len(f) for f in per_feed), default=0)):
            out.extend(f[i] for f in per_feed if i < len(f))
        return out

    @staticmethod
    def fmt(item: dict) -> str:
        return f"[{item['source']}] {item['title']}" if item["source"] else item["title"]

    async def post_new(self):
        fresh = [i for i in await self.latest() if not self.bot.db.seen("news", i["id"])]
        fresh = fresh[: self.cfg["items_per_post"]]
        for item in fresh:
            self.bot.db.mark_seen("news", item["id"])
        if fresh:
            await self.bot.post("📰 " + " | ".join(self.fmt(i) for i in fresh))


def setup(bot):
    cfg = bot.cfg["news"]
    if not cfg["enabled"] or not cfg["feeds"]:
        return
    news = News(bot)

    @bot.command("news", "news: latest local headlines")
    async def _news(ctx):
        items = (await news.latest())[: 5 if ctx.is_dm else 2]
        if not items:
            return "No headlines right now."
        return "📰 " + "\n".join(news.fmt(i) for i in items)

    @bot.command("newsnow", "newsnow: post new headlines to the channel", admin=True)
    async def _newsnow(ctx):
        await news.post_new()
        return "Done." if ctx.is_dm else None

    bot.schedule("news", news.post_new, times=cfg["post_times"])
