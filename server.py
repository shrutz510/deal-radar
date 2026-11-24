"""Deal Radar server: JSON API, static UI and a background refresh scheduler (stdlib only).

Run:  python3 server.py   then open http://localhost:8787
"""
import json
import re
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import scraper
import stores

PORT = 8787
REFRESH_EVERY_S = 30 * 60
STATIC = Path(__file__).with_name("static")

conn = scraper.connect()
db_lock = threading.Lock()
refresh_state = {"running": False}
refresh_queue = []
queue_lock = threading.Lock()


def rows(sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


LAST_BF_WINDOW = ("2025-11-01", "2025-12-05")  # last year's Black Friday season


def wishlist_view():
    out = []
    recent = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    for w in rows("SELECT * FROM wishlist ORDER BY priority, created_at DESC"):
        matches = rows(
            """SELECT d.* FROM wish_matches m JOIN deals d ON d.id=m.deal_id
               WHERE m.wish_id=? ORDER BY d.posted_at DESC LIMIT 200""", (w["id"],))
        for d in matches:
            d["used"] = scraper.is_used(d["title"])
        priced = [d for d in matches if d["price"] and not d["used"]]
        current = [d for d in priced if (d["last_seen"] if d["kind"] == "product" else d["posted_at"]) >= recent]
        last_season = [d for d in priced if LAST_BF_WINDOW[0] <= d["posted_at"][:10] <= LAST_BF_WINDOW[1]]
        last_bf = min(last_season, key=lambda d: d["price"]) if last_season else None
        best_now = min(current, key=lambda d: d["price"]) if current else None
        history = rows("SELECT day, price, source FROM price_points WHERE wish_id=? ORDER BY day", (w["id"],))
        lowest = min((h["price"] for h in history), default=None)
        if w["page_price"] and (best_now is None or w["page_price"] < best_now["price"]):
            now_price = w["page_price"]
        else:
            now_price = best_now["price"] if best_now else None
        target = w["target_price"]
        store_sale = bool(w["page_price"] and w["page_regular"] and w["page_price"] < w["page_regular"])
        deal_sale = bool(best_now and (best_now["discount_pct"] or 0) >= 15)
        if now_price is None:
            status = "waiting"
        elif target and now_price <= target:
            status = "hit"
        elif store_sale or deal_sale:
            status = "sale"
        elif target and now_price <= target * 1.1:
            status = "close"
        else:
            status = "watching"
        out.append({**w, "matches": matches[:12], "match_count": len(matches), "best_now": best_now,
                    "now_price": now_price, "lowest": lowest, "history": history, "status": status,
                    "last_bf": last_bf})
    return out


FEED_DAYS = 14
PRODUCT_STALE_H = 26  # a store product not seen in this long is gone (sold out or off sale)
MULTIPACK_RX = re.compile(r"\b(\d{1,2})\s*(?:pairs?|pack|pk|pieces?|pcs)?\s*(?:for|/)\s*\$\s?(\d+(?:\.\d\d)?)", re.I)


def unit_price(title):
    """"10 Pairs for $38" / "10/$31 panties" -> price per item."""
    m = MULTIPACK_RX.search(title)
    if m and int(m.group(1)) > 1:
        return round(float(m.group(2)) / int(m.group(1)), 2)
    return None


def deals_view(profile):
    """Recent deals that fit the profile (or match a wishlist item); everything else is dropped."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=FEED_DAYS)).isoformat()
    seen = (now - timedelta(hours=PRODUCT_STALE_H)).isoformat()
    deals = rows(
        """SELECT d.*, (SELECT GROUP_CONCAT(m.wish_id) FROM wish_matches m WHERE m.deal_id=d.id) AS wish_ids
           FROM deals d WHERE (d.kind = 'product' AND d.last_seen >= ?) OR (d.kind != 'product' AND d.posted_at >= ?)
           ORDER BY d.posted_at DESC LIMIT 5000""", (seen, cutoff))
    focus = {i["name"] for i in profile.get("interests", []) if i.get("focus")}
    sections = {i["name"] for i in profile.get("interests", [])}
    shops = {s.lower() for s in profile.get("shops") or []}
    avoid = scraper._words_rx(profile.get("avoid", []))
    out = []
    for d in deals:
        d["wish_ids"] = [int(x) for x in d["wish_ids"].split(",")] if d["wish_ids"] else []
        if d["kind"] == "product":
            # the store already said what it is; it shows if the profile has that section (and browses that
            # store), and the profile's "never show" words still get a veto (men's, kids, ...)
            wanted = d["category"] in sections and (not shops or (d["retailer"] or "").lower() in shops)
            if not wanted or (avoid and avoid.search(d["title"].replace("\u2019", "'"))):
                d["category"] = None
        else:
            d["category"] = scraper.profile_section(profile, d["title"], d["retailer"] or "")
        if not d["category"] and not d["wish_ids"]:
            continue
        d["category"] = d["category"] or "Wishlist"
        d["unit_price"] = unit_price(d["title"])
        d["score"] = deal_score(d) + (10 if d["category"] in focus else 0)
        out.append(d)
    return out


def deal_score(d):
    """0-100ish: discount carries most weight, community heat and staff picks add on top."""
    disc = min(d["discount_pct"] or 0, 90)
    heat = min(max(d["popularity"] or 0, 0), 150) / 150 * 30
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(d["posted_at"])).total_seconds() / 3600
    fresh = max(0, 10 - age_h / 12)
    return round(disc * 0.6 + heat + (8 if d["staff_pick"] else 0) + fresh, 1)


def state():
    with db_lock:
        profile = scraper.get_profile(conn)
        return {
            "profile": profile,
            "samples": list(scraper.SAMPLE_PROFILES),
            "shops": stores.STORE_NAMES,
            "events": rows("SELECT * FROM events ORDER BY start"),
            "wishlist": wishlist_view(),
            "deals": deals_view(profile),
            "meta": {
                "feed_days": FEED_DAYS,
                "last_refresh": scraper.get_meta(conn, "last_refresh"),
                "sources": scraper.get_meta(conn, "sources", {}),
                "refreshing": refresh_state["running"],
                "refresh_every_min": REFRESH_EVERY_S // 60,
                "now": scraper.now_iso(),
            },
        }


def refresh(only_wish_id=None):
    """Queue a full refresh (None) or a single-wish search; one worker drains the queue."""
    with queue_lock:
        refresh_queue.append(only_wish_id)
        if refresh_state["running"]:
            return True
        refresh_state["running"] = True

    def work():
        # Scrape on its own connection so the UI's reads aren't blocked by network waits.
        c = scraper.connect()
        while True:
            with queue_lock:
                if not refresh_queue:
                    refresh_state["running"] = False
                    break
                job = None if None in refresh_queue else refresh_queue[0]
                refresh_queue[:] = [] if job is None else refresh_queue[1:]
            try:
                scraper.run_scrape(c, job, log=lambda m: print("[scrape]", m))
            except Exception as e:
                print("[scrape] error", e)
        c.close()

    threading.Thread(target=work, daemon=True).start()
    return True


def scheduler():
    while True:
        last = scraper.get_meta(conn, "last_refresh")
        due = not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() > REFRESH_EVERY_S
        if due:
            refresh()
        time.sleep(60)


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (str(args[0]) if args else ""):
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        # always revalidate the UI files, so an edited app.js/styles.css shows up on a normal reload
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/api/state":
            return self.send_json(state())
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/refresh":
            return self.send_json({"started": refresh()})
        if self.path == "/api/wishlist":
            b = self.body()
            query = (b.get("query") or "").strip()
            if not query:
                return self.send_json({"error": "query required"}, 400)
            url = (b.get("product_url") or "").strip() or None
            if url and not re.match(r"https?://", url):
                return self.send_json({"error": "product URL must start with http(s)://"}, 400)
            with db_lock:
                cur = conn.execute(
                    "INSERT INTO wishlist (query, target_price, product_url, priority, note, created_at) VALUES (?,?,?,?,?,?)",
                    (query, num(b.get("target_price")), url, int(b.get("priority") or 2),
                     (b.get("note") or "").strip() or None, scraper.now_iso()))
                conn.commit()
                scraper.recompute_matches(conn, [cur.lastrowid])
            refresh(cur.lastrowid)  # go search for it right away
            return self.send_json({"id": cur.lastrowid})
        if self.path == "/api/events":
            b = self.body()
            if not b.get("name") or not b.get("start"):
                return self.send_json({"error": "name and start required"}, 400)
            with db_lock:
                conn.execute("INSERT INTO events (retailer, name, start, end, status, note, url) VALUES (?,?,?,?,?,?,?)",
                             (b.get("retailer") or "Custom", b["name"], b["start"], b.get("end") or b["start"],
                              "mine", b.get("note") or "", b.get("url") or ""))
                conn.commit()
            return self.send_json({"ok": True})
        self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        if self.path == "/api/profile":
            b = self.body()
            clean = lambda xs: [x.strip() for x in xs if isinstance(x, str) and x.strip()]
            profile = {
                "about": str(b.get("about") or "")[:500],
                "brands": clean(b.get("brands") or []),
                "stores": clean(b.get("stores") or []),
                "shops": clean(b.get("shops") or []),
                "interests": [{"name": i["name"].strip(), "keywords": clean(i.get("keywords") or []),
                               "focus": bool(i.get("focus"))}
                              for i in b.get("interests") or [] if (i.get("name") or "").strip()],
                "avoid": clean(b.get("avoid") or []),
            }
            with db_lock:
                scraper.set_meta(conn, "profile", profile)
            refresh()  # run the new brand searches
            return self.send_json({"ok": True})
        if self.path == "/api/profile/sample":
            sample = scraper.SAMPLE_PROFILES.get(self.body().get("name"))
            if not sample:
                return self.send_json({"error": "no such sample"}, 404)
            with db_lock:
                scraper.set_meta(conn, "profile", sample)
            return self.send_json({"ok": True})
        if self.path == "/api/profile/reset":
            with db_lock:
                conn.execute("DELETE FROM meta WHERE key='profile'")
                conn.commit()
            return self.send_json({"ok": True})
        m = re.fullmatch(r"/api/wishlist/(\d+)", self.path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        b = self.body()
        with db_lock:
            if "target_price" in b:
                conn.execute("UPDATE wishlist SET target_price=? WHERE id=?", (num(b["target_price"]), int(m.group(1))))
            if "note" in b:
                conn.execute("UPDATE wishlist SET note=? WHERE id=?", ((b["note"] or "").strip() or None, int(m.group(1))))
            if "priority" in b:
                conn.execute("UPDATE wishlist SET priority=? WHERE id=?", (int(b["priority"]), int(m.group(1))))
            conn.commit()
        self.send_json({"ok": True})

    def do_DELETE(self):
        m = re.fullmatch(r"/api/(wishlist|events)/(\d+)", self.path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        i = int(m.group(2))
        with db_lock:
            if m.group(1) == "wishlist":
                conn.execute("DELETE FROM wishlist WHERE id=?", (i,))
                conn.execute("DELETE FROM wish_matches WHERE wish_id=?", (i,))
                conn.execute("DELETE FROM price_points WHERE wish_id=?", (i,))
            else:
                conn.execute("DELETE FROM events WHERE id=?", (i,))
            conn.commit()
        self.send_json({"ok": True})


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Deal Radar running at {url}  (auto-refresh every {REFRESH_EVERY_S // 60} min, Ctrl+C to stop)")
    if "--no-browser" not in __import__("sys").argv:
        webbrowser.open(url)
    server.serve_forever()
