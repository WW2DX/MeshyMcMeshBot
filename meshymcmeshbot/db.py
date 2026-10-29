"""SQLite persistence. Everything the bot remembers across restarts lives here."""

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    pubkey    TEXT PRIMARY KEY,
    name      TEXT,
    last_seen INTEGER,
    lat       REAL,
    lon       REAL
);
CREATE TABLE IF NOT EXISTS chan_activity (
    ts     INTEGER,
    sender TEXT
);
CREATE INDEX IF NOT EXISTS chan_activity_ts ON chan_activity(ts);
CREATE TABLE IF NOT EXISTS mail (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    to_key    TEXT NOT NULL,
    from_key  TEXT NOT NULL,
    from_name TEXT,
    body      TEXT NOT NULL,
    created   INTEGER NOT NULL,
    delivered INTEGER
);
CREATE INDEX IF NOT EXISTS mail_to ON mail(to_key, delivered);
CREATE TABLE IF NOT EXISTS mail_notify (
    to_key        TEXT PRIMARY KEY,
    last_notified INTEGER
);
CREATE TABLE IF NOT EXISTS bbs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    author_key  TEXT,
    author_name TEXT,
    body        TEXT NOT NULL,
    created     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_items (
    kind    TEXT,
    item_id TEXT,
    ts      INTEGER,
    PRIMARY KEY (kind, item_id)
);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts INTEGER NOT NULL,
    title    TEXT NOT NULL,
    added_by TEXT
);
"""


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def all(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    # --- nodes -------------------------------------------------------------

    def upsert_node(self, pubkey: str, name: str, lat=None, lon=None, ts=None):
        self.execute(
            """INSERT INTO nodes (pubkey, name, last_seen, lat, lon) VALUES (?,?,?,?,?)
               ON CONFLICT(pubkey) DO UPDATE SET
                 name=excluded.name,
                 last_seen=MAX(COALESCE(nodes.last_seen,0), excluded.last_seen),
                 lat=COALESCE(excluded.lat, nodes.lat),
                 lon=COALESCE(excluded.lon, nodes.lon)""",
            (pubkey, name, ts or int(time.time()), lat, lon),
        )

    def touch_node(self, pubkey: str, ts=None):
        self.execute(
            "UPDATE nodes SET last_seen=? WHERE pubkey=?", (ts or int(time.time()), pubkey)
        )

    # --- seen-item dedupe (alerts, news) ------------------------------------

    def seen(self, kind: str, item_id: str) -> bool:
        return self.one(
            "SELECT 1 FROM seen_items WHERE kind=? AND item_id=?", (kind, item_id)
        ) is not None

    def mark_seen(self, kind: str, item_id: str):
        self.execute(
            "INSERT OR IGNORE INTO seen_items (kind, item_id, ts) VALUES (?,?,?)",
            (kind, item_id, int(time.time())),
        )

    def prune(self):
        now = int(time.time())
        self.execute("DELETE FROM chan_activity WHERE ts < ?", (now - 8 * 86400,))
        self.execute("DELETE FROM seen_items WHERE ts < ?", (now - 60 * 86400,))
        self.execute("DELETE FROM events WHERE start_ts < ?", (now - 86400,))
