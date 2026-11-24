"""SQLite storage: schema, small migrations, and helpers shared by every module."""
import json
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (          -- every collected item: deal-feed post or store product
    id INTEGER PRIMARY KEY, guid TEXT UNIQUE, kind TEXT DEFAULT 'post',
    source TEXT, title TEXT, url TEXT, image TEXT, retailer TEXT, category TEXT,
    price REAL, orig_price REAL, discount_pct REAL, staff_pick INTEGER, summary TEXT, coupon TEXT,
    posted_at TEXT, first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY, query TEXT NOT NULL, target_price REAL, product_url TEXT, priority INTEGER DEFAULT 2,
    note TEXT, created_at TEXT, page_price REAL, page_regular REAL, page_checked_at TEXT, page_status TEXT
);
CREATE TABLE IF NOT EXISTS wish_matches (
    wish_id INTEGER, deal_id INTEGER, notified INTEGER DEFAULT 0, PRIMARY KEY (wish_id, deal_id)
);
CREATE TABLE IF NOT EXISTS price_points (   -- lowest price per wishlist item per day
    wish_id INTEGER, day TEXT, price REAL, source TEXT, PRIMARY KEY (wish_id, day)
);
CREATE TABLE IF NOT EXISTS events (         -- sale dates; status 'mine' = added by hand
    id INTEGER PRIMARY KEY, retailer TEXT, name TEXT, start TEXT, end TEXT, status TEXT, note TEXT, url TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
# Columns added after the first release; older databases get them on connect.
MIGRATIONS = [("wishlist", "note", "TEXT"), ("wishlist", "page_regular", "REAL"), ("deals", "kind", "TEXT DEFAULT 'post'")]


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, col, typ in MIGRATIONS:
        if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    conn.commit()
    return conn


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()


def upsert_items(conn, items):
    """Insert new items by guid; for known ones refresh price fields, image, section and last_seen."""
    ts = now_iso()
    for d in items:
        if not d["title"]:
            continue
        cur = conn.execute("SELECT id FROM deals WHERE guid=?", (d["guid"],)).fetchone()
        if cur:
            conn.execute(
                """UPDATE deals SET last_seen=?, price=?, orig_price=?, discount_pct=?,
                   image=COALESCE(?, image), category=COALESCE(?, category) WHERE id=?""",
                (ts, d["price"], d["orig_price"], d["discount_pct"], d["image"], d.get("category"), cur["id"]))
        else:
            conn.execute(
                """INSERT INTO deals (guid, kind, source, title, url, image, retailer, category, price, orig_price,
                   discount_pct, staff_pick, summary, coupon, posted_at, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d["guid"], d.get("kind", "post"), d["source"], d["title"], d["url"], d["image"], d["retailer"],
                 d.get("category"), d["price"], d["orig_price"], d["discount_pct"], d.get("staff_pick", 0),
                 d.get("summary", ""), d.get("coupon"), d["posted_at"], ts, ts))
    conn.commit()
