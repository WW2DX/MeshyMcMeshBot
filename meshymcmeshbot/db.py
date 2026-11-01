"""SQLite persistence. Everything the bot remembers across restarts lives here."""

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    pubkey     TEXT PRIMARY KEY,
    name       TEXT,
    last_seen  INTEGER,
    lat        REAL,
    lon        REAL,
    type       INTEGER,
    first_seen INTEGER
);
-- Last time a repeater's path hash showed up in a flood packet we received.
CREATE TABLE IF NOT EXISTS relay_seen (
    hash TEXT PRIMARY KEY,
    ts   INTEGER
);
-- Settings changed by admins over the mesh (dotted config path -> JSON value).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
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
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()
        if self.get_meta("installed") is None:
            self.set_meta("installed", str(int(time.time())))

    def _migrate(self):
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(nodes)")}
        for col in ("type INTEGER", "first_seen INTEGER"):
            if col.split()[0] not in cols:
                self.conn.execute(f"ALTER TABLE nodes ADD COLUMN {col}")

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def all(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    # --- nodes -------------------------------------------------------------

    def node(self, pubkey: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM nodes WHERE pubkey=?", (pubkey,))

    def upsert_node(self, pubkey: str, name: str, lat=None, lon=None, node_type=None):
        """Record that we heard this node just now (by our clock)."""
        now = int(time.time())
        self.execute(
            """INSERT INTO nodes (pubkey, name, last_seen, lat, lon, type, first_seen)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(pubkey) DO UPDATE SET
                 name=COALESCE(NULLIF(excluded.name, ''), nodes.name),
                 last_seen=excluded.last_seen,
                 lat=COALESCE(excluded.lat, nodes.lat),
                 lon=COALESCE(excluded.lon, nodes.lon),
                 type=COALESCE(excluded.type, nodes.type)""",
            (pubkey, name, now, lat, lon, node_type, now),
        )

    def sync_node(self, pubkey: str, name: str, lat=None, lon=None, node_type=None, last_advert=0):
        """Record a node from the radio's contact list without claiming we just heard it.

        last_advert comes from the *sender's* clock, which may be wrong, so it
        only seeds last_seen for nodes we've never recorded (capped at now).
        """
        now = int(time.time())
        seed = min(last_advert or 0, now) or None
        self.execute(
            """INSERT INTO nodes (pubkey, name, last_seen, lat, lon, type, first_seen)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(pubkey) DO UPDATE SET
                 name=COALESCE(NULLIF(excluded.name, ''), nodes.name),
                 lat=COALESCE(excluded.lat, nodes.lat),
                 lon=COALESCE(excluded.lon, nodes.lon),
                 type=COALESCE(excluded.type, nodes.type)""",
            (pubkey, name, seed, lat, lon, node_type, now),
        )

    def mark_relays(self, hashes: list[str]):
        now = int(time.time())
        self.conn.executemany(
            "INSERT OR REPLACE INTO relay_seen (hash, ts) VALUES (?,?)", [(h, now) for h in hashes]
        )
        self.conn.commit()

    def relay_seen(self, pubkey: str) -> int:
        """Last time a path hash matching this pubkey was seen (0 if never)."""
        row = self.one(
            "SELECT MAX(ts) ts FROM relay_seen WHERE ? LIKE hash || '%'", (pubkey.lower(),)
        )
        return row["ts"] or 0

    # --- meta ---------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        self.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))

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
