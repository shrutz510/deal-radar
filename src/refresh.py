"""A refresh: read deal feeds and the profile's stores, check wishlist product pages, then rebuild
wishlist matches and send alerts. Refresher runs refreshes one at a time on a background thread."""
import threading
import time
import urllib.error

import db
import stores
import wishlist
from config import REQUEST_GAP_S, RETRY_AFTER_MAX_S, STORE_GAP_S
from feeds import FEEDS
from net import fetch

BLOCKED = {403: "blocks automated requests", 429: "refusing requests for now (too many requests)"}


def _ok(count, **extra):
    return {"ok": True, "count": count, "at": db.now_iso(), **extra}


def _failed(error, **extra):
    return {"ok": False, "error": error, "at": db.now_iso(), **extra}


def read_feeds(conn, status, log):
    for name, (url, parse) in FEEDS.items():
        try:
            items = parse(fetch(url))
            db.upsert_items(conn, items)
            status[name] = _ok(len(items))
        except Exception as e:
            status[name] = _failed(f"{type(e).__name__}: {e}"[:200])
        log(f"{name}: {status[name]}")
        time.sleep(REQUEST_GAP_S)


def read_stores(conn, profile, status, log):
    shops = set(profile.get("shops") or [])
    for name, emits, read in stores.readers(profile.get("department", "all")):
        if shops and not shops & set(emits):
            status.pop(name, None)  # not one of this profile's stores
            continue
        try:
            try:
                items = read(fetch, db.now_iso(), REQUEST_GAP_S)
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                time.sleep(min(int(e.headers.get("Retry-After") or 5), RETRY_AFTER_MAX_S))  # one polite retry
                items = read(fetch, db.now_iso(), REQUEST_GAP_S)
            db.upsert_items(conn, items)
            status[name] = _ok(len(items), store=True)
        except urllib.error.HTTPError as e:
            status[name] = _failed(BLOCKED.get(e.code, f"HTTP {e.code}"), store=True)
        except Exception as e:
            status[name] = _failed(f"{type(e).__name__}: {e}"[:200], store=True)
        log(f"{name}: {status[name]}")
        time.sleep(STORE_GAP_S)


def run(conn, wish_id=None, log=print):
    """Full refresh, or (with wish_id) just that wishlist item's product page and matches."""
    profile = db.get_meta(conn, "profile")
    if profile is None:
        log("no profile yet; finish setup in the UI first")
        return
    if wish_id is None:
        status = db.get_meta(conn, "sources", {})
        read_feeds(conn, status, log)
        read_stores(conn, profile, status, log)
    query = "SELECT * FROM wishlist WHERE product_url IS NOT NULL" + (" AND id=?" if wish_id else "")
    for w in conn.execute(query, (wish_id,) if wish_id else ()).fetchall():
        wishlist.check_page(conn, w)
        time.sleep(REQUEST_GAP_S)
    wishlist.recompute(conn)
    wishlist.notify_hits(conn)
    if wish_id is None:
        db.set_meta(conn, "sources", status)
        db.set_meta(conn, "last_refresh", db.now_iso())


class Refresher:
    """Queues refresh jobs (None = full, or a wishlist id) and drains them on one background thread,
    with its own DB connection so the UI's reads never wait on the network."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = []
        self.running = False

    def request(self, wish_id=None):
        with self.lock:
            if wish_id is None:
                self.jobs = [None]  # a full refresh covers any queued single-item jobs
            elif None not in self.jobs and wish_id not in self.jobs:
                self.jobs.append(wish_id)
            if self.running:
                return
            self.running = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        conn = db.connect()
        while True:
            with self.lock:
                if not self.jobs:
                    self.running = False
                    break
                job = self.jobs.pop(0)
            try:
                run(conn, job, log=lambda m: print("[refresh]", m))
            except Exception as e:
                print("[refresh] error:", e)
        conn.close()
