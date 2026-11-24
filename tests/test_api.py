"""End to end through HTTP: the real server and handlers on a temp database, with refreshes switched off."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import db
import server


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.refresher.request = lambda *a, **kw: None  # no network in tests
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, method=method, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def state(self):
        return self.call("GET", "/api/state")[1]

    def test_full_flow(self):
        self.call("PUT", "/api/profile/reset")
        self.assertTrue(self.state()["needs_setup"])
        self.assertEqual(self.state()["deals"], [])

        # setup builds the profile and loads the chosen sale dates
        answers = {"title": "Test Radar", "department": "women", "categories": ["Jeans", "Earphones & tech"],
                   "shops": ["Zara"], "countdown": {"label": "Payday", "date": "2026-12-01"},
                   "sale_dates": "US Black Friday 2026"}
        self.assertEqual(self.call("PUT", "/api/setup", answers), (200, {"ok": True}))
        s = self.state()
        self.assertFalse(s["needs_setup"])
        self.assertEqual(s["profile"]["title"], "Test Radar")
        self.assertEqual(s["profile"]["setup"]["shops"], ["Zara"])
        self.assertTrue(any(e["name"] == "Black Friday" for e in s["events"]))

        # items are filtered and classified by the profile
        db.upsert_items(server.conn, [
            {"guid": "Zara:1", "kind": "product", "source": "Zara", "retailer": "Zara", "title": "Wide Leg Jeans",
             "url": "https://x/1", "image": None, "category": "Jeans", "price": 30, "orig_price": 50,
             "discount_pct": 40, "posted_at": db.now_iso()},
            {"guid": "Zara:2", "kind": "product", "source": "Zara", "retailer": "Zara", "title": "Lipstick",
             "url": "https://x/2", "image": None, "category": "Makeup", "price": 9, "orig_price": None,
             "discount_pct": None, "posted_at": db.now_iso()},
            {"guid": "dn-1", "source": "DealNews", "retailer": "Amazon", "title": "AirPods Pro 3 for $199",
             "url": "https://x/3", "image": None, "price": 199, "orig_price": 249, "discount_pct": 20,
             "posted_at": db.now_iso()},
        ])
        cats = {d["title"]: d["category"] for d in self.state()["deals"]}
        self.assertEqual(cats, {"Wide Leg Jeans": "Jeans", "AirPods Pro 3 for $199": "Earphones & tech"})

        # wishlist: add, match, status, edit, delete
        self.assertEqual(self.call("POST", "/api/wishlist", {"query": ""})[0], 400)
        self.assertEqual(self.call("POST", "/api/wishlist", {"query": "x", "product_url": "ftp://x"})[0], 400)
        code, made = self.call("POST", "/api/wishlist", {"query": "zara wide leg", "target_price": "35"})
        self.assertEqual(code, 200)
        [w] = self.state()["wishlist"]
        self.assertEqual((w["match_count"], w["now_price"], w["status"]), (1, 30, "hit"))
        self.call("PUT", f"/api/wishlist/{made['id']}", {"target_price": "20", "note": " black ", "priority": 1})
        [w] = self.state()["wishlist"]
        self.assertEqual((w["target_price"], w["note"], w["priority"], w["status"]), (20, "black", 1, "sale"))
        self.call("DELETE", f"/api/wishlist/{made['id']}")
        self.assertEqual(self.state()["wishlist"], [])

        # hand-added events survive a new setup; preset ones are replaced
        self.assertEqual(self.call("POST", "/api/events", {"name": "x"})[0], 400)
        self.call("POST", "/api/events", {"retailer": "Me", "name": "My sale", "start": "2026-12-05"})
        self.call("PUT", "/api/setup", {**answers, "sale_dates": ""})
        names = [e["name"] for e in self.state()["events"]]
        self.assertEqual(names, ["My sale"])
        mine = self.state()["events"][0]["id"]
        self.call("DELETE", f"/api/events/{mine}")
        self.assertEqual(self.state()["events"], [])

        # preferences edit keeps what the form doesn't touch
        self.call("PUT", "/api/profile", {"about": "hi", "brands": ["Zara"], "interests": [{"name": "Jeans", "keywords": []}]})
        p = self.state()["profile"]
        self.assertEqual((p["about"], p["title"], p["department"]), ("hi", "Test Radar", "women"))

    def test_unknown_routes(self):
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)
        self.assertEqual(self.call("DELETE", "/api/state")[0], 404)  # right path, wrong method

    def test_serves_ui(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b'src="js/main.js"', r.read())
            self.assertEqual(r.headers["Cache-Control"], "no-cache")


if __name__ == "__main__":
    unittest.main()
