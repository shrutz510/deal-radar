"""Deal Radar: JSON API + static UI + background refresh. Standard library only.

Run:  python3 src/server.py [--no-browser]   then open http://localhost:8787
"""
import json
import re
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import db
import profiles
import views
import wishlist
from config import HOST, PORT, REFRESH_EVERY_S, STATIC_DIR
from refresh import Refresher

conn = db.connect()
lock = threading.Lock()  # one request at a time on the shared connection
refresher = Refresher()


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def words(xs):
    return [x.strip() for x in xs or [] if isinstance(x, str) and x.strip()]


# ---------------------------------------------------------------- API handlers: (body, *url groups) -> JSON

def get_state(_):
    return views.state(conn, refresher.running)


def start_refresh(_):
    refresher.request()
    return {"started": True}


def save_setup(answers):
    profiles.save_setup(conn, answers)
    refresher.request()
    return {"ok": True}


def save_profile(b):
    """Fine-tune the generated profile; fields this form doesn't edit (title, department, ...) are kept."""
    interests = [{"name": i["name"].strip(), "keywords": words(i.get("keywords")), "focus": bool(i.get("focus"))}
                 for i in b.get("interests") or [] if (i.get("name") or "").strip()]
    db.set_meta(conn, "profile", {**(db.get_meta(conn, "profile") or {}), "about": str(b.get("about") or "")[:500],
                                  "brands": words(b.get("brands")), "stores": words(b.get("stores")),
                                  "shops": words(b.get("shops")), "avoid": words(b.get("avoid")), "interests": interests})
    refresher.request()
    return {"ok": True}


def reset_profile(_):
    conn.execute("DELETE FROM meta WHERE key='profile'")
    conn.commit()
    return {"ok": True}


def add_wish(b):
    query, url = (b.get("query") or "").strip(), (b.get("product_url") or "").strip() or None
    if not query:
        return {"error": "query required"}, 400
    if url and not re.match(r"https?://", url):
        return {"error": "product URL must start with http(s)://"}, 400
    cur = conn.execute(
        "INSERT INTO wishlist (query, target_price, product_url, priority, note, created_at) VALUES (?,?,?,?,?,?)",
        (query, num(b.get("target_price")), url, int(b.get("priority") or 2), (b.get("note") or "").strip() or None,
         db.now_iso()))
    conn.commit()
    wishlist.recompute(conn, [cur.lastrowid])
    refresher.request(cur.lastrowid)  # check its product page right away
    return {"id": cur.lastrowid}


def edit_wish(b, wish_id):
    fields = {"target_price": num, "note": lambda v: (v or "").strip() or None, "priority": int}
    for col, conv in fields.items():
        if col in b:
            conn.execute(f"UPDATE wishlist SET {col}=? WHERE id=?", (conv(b[col]), int(wish_id)))
    conn.commit()
    return {"ok": True}


def delete_wish(_, wish_id):
    for table, col in (("wishlist", "id"), ("wish_matches", "wish_id"), ("price_points", "wish_id")):
        conn.execute(f"DELETE FROM {table} WHERE {col}=?", (int(wish_id),))
    conn.commit()
    return {"ok": True}


def add_event(b):
    if not b.get("name") or not b.get("start"):
        return {"error": "name and start required"}, 400
    conn.execute("INSERT INTO events (retailer, name, start, end, status, note, url) VALUES (?,?,?,?,?,?,?)",
                 (b.get("retailer") or "Custom", b["name"], b["start"], b.get("end") or b["start"], "mine",
                  b.get("note") or "", b.get("url") or ""))
    conn.commit()
    return {"ok": True}


def delete_event(_, event_id):
    conn.execute("DELETE FROM events WHERE id=?", (int(event_id),))
    conn.commit()
    return {"ok": True}


ROUTES = [
    ("GET", r"/api/state", get_state),
    ("POST", r"/api/refresh", start_refresh),
    ("PUT", r"/api/setup", save_setup),
    ("PUT", r"/api/profile", save_profile),
    ("PUT", r"/api/profile/reset", reset_profile),
    ("POST", r"/api/wishlist", add_wish),
    ("PUT", r"/api/wishlist/(\d+)", edit_wish),
    ("DELETE", r"/api/wishlist/(\d+)", delete_wish),
    ("POST", r"/api/events", add_event),
    ("DELETE", r"/api/events/(\d+)", delete_event),
]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC_DIR), **kw)

    def api(self, method):
        for m, pattern, handler in ROUTES:
            match = re.fullmatch(pattern, self.path)
            if m == method and match:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                with lock:
                    result = handler(body, *match.groups())
                return self.send_json(*(result if isinstance(result, tuple) else (result,)))
        self.send_json({"error": "not found"}, 404)

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")  # edited UI files show up on a normal reload
        super().end_headers()

    def log_message(self, fmt, *args):
        if "/api/" not in str(args[0] if args else ""):  # keep the polling out of the log
            super().log_message(fmt, *args)

    def do_GET(self):
        return self.api("GET") if self.path.startswith("/api/") else super().do_GET()

    def do_POST(self):
        self.api("POST")

    def do_PUT(self):
        self.api("PUT")

    def do_DELETE(self):
        self.api("DELETE")


def scheduler():
    """Kick off a full refresh whenever the last one is older than REFRESH_EVERY_S (once setup is done)."""
    while True:
        with lock:
            last, has_profile = db.get_meta(conn, "last_refresh"), db.get_meta(conn, "profile") is not None
        stale = not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() > REFRESH_EVERY_S
        if has_profile and stale and not refresher.running:
            refresher.request()
        time.sleep(60)


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
    url = f"http://localhost:{PORT}"
    print(f"Deal Radar running at {url}  (refresh every {REFRESH_EVERY_S // 60} min, Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
