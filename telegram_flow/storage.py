"""SQLite 存储：建表、迁移与过滤词表。"""
from __future__ import annotations

import sqlite3

from .config import BLOCKLIST, DATA, DB, DEFAULT_BLOCK
from .learning import MODEL_VERSION, retrain


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_storage() -> None:
    DATA.mkdir(mode=0o700, exist_ok=True)
    if not BLOCKLIST.exists():
        BLOCKLIST.write_text("# 命中任一词的帖子不进入视频流；一行一个，可自行增删。\n" + "\n".join(DEFAULT_BLOCK) + "\n")
    with db() as c:
        c.executescript("""
        PRAGMA journal_mode=DELETE;
        CREATE TABLE IF NOT EXISTS channel(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, username TEXT, kind TEXT NOT NULL,
          selected INTEGER NOT NULL DEFAULT 0, last_msg_id INTEGER NOT NULL DEFAULT 0,
          oldest_msg_id INTEGER NOT NULL DEFAULT 0, synced_at REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS item(
          chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, gkey TEXT NOT NULL, date REAL NOT NULL,
          text TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, duration REAL, size INTEGER, mime TEXT,
          width INTEGER, height INTEGER, features TEXT NOT NULL DEFAULT '[]', blocked INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(chat_id, msg_id));
        CREATE INDEX IF NOT EXISTS idx_item_gkey ON item(gkey);
        CREATE INDEX IF NOT EXISTS idx_item_date ON item(date DESC);
        CREATE TABLE IF NOT EXISTS event(
          id INTEGER PRIMARY KEY, gkey TEXT NOT NULL, kind TEXT NOT NULL, value REAL, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_event_gkey ON event(gkey, kind);
        CREATE TABLE IF NOT EXISTS weight(feature TEXT PRIMARY KEY, w REAL NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0);
        """)
        cols = {r[1] for r in c.execute("PRAGMA table_info(item)")}
        for col in ("reactions", "replies"):
            if col not in cols:
                c.execute(f"ALTER TABLE item ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        ver = c.execute("SELECT v FROM meta WHERE k='model'").fetchone()
        if not ver or ver[0] != MODEL_VERSION:
            retrain(c)


def blocklist() -> list[str]:
    return [w.strip().casefold() for w in BLOCKLIST.read_text().splitlines() if w.strip() and not w.startswith("#")]
