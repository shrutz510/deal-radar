"""Data collection and storage for Deal Radar.

Reads products straight from store websites (stores.py: Zara, Uniqlo, Ulta, Shopify brands), pulls the
DealNews and Ben's Bargains RSS feeds for big-retailer deals (earphones, perfume, makeup), and optionally
checks a wishlist item's product page price (Shopify JSON or schema.org JSON-LD). Standard library only.
"""
import html
import json
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import profiles
import stores

DB_PATH = Path(__file__).with_name("deals.db")
USER_AGENT = "DealRadar/1.0 (personal deal tracker; RSS reader)"
REQUEST_GAP_S = 1.5  # be polite between requests
STORE_GAP_S = 5  # between stores; Shopify rate-limits many stores hit back to back from one address

FEEDS = {
    "DealNews": "https://www.dealnews.com/?rss=1",
    "Ben's Bargains": "https://bensbargains.com/rss/",
}

# What the feed shows is decided by the profile, which is built from setup answers (see profiles.py).
STORE_SALE_RX = re.compile(r"\b(sale|sitewide|site-wide|event|clearance|extra \d+% off|\d+% off|off \$\d+|code|coupon|gift with purchase|gwp)\b", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY,
    guid TEXT UNIQUE,
    source TEXT, title TEXT, url TEXT, image TEXT, retailer TEXT, category TEXT,
    price REAL, orig_price REAL, discount_pct REAL, popularity INTEGER, staff_pick INTEGER,
    summary TEXT, coupon TEXT,
    posted_at TEXT, first_seen TEXT, last_seen TEXT, frontpage INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY,
    query TEXT NOT NULL, target_price REAL, product_url TEXT, priority INTEGER DEFAULT 2,
    created_at TEXT, page_price REAL, page_checked_at TEXT, page_status TEXT,
    note TEXT, page_regular REAL
);
CREATE TABLE IF NOT EXISTS wish_matches (
    wish_id INTEGER, deal_id INTEGER, notified INTEGER DEFAULT 0,
    PRIMARY KEY (wish_id, deal_id)
);
CREATE TABLE IF NOT EXISTS price_points (
    wish_id INTEGER, day TEXT, price REAL, source TEXT,
    PRIMARY KEY (wish_id, day)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    retailer TEXT, name TEXT, start TEXT, end TEXT, status TEXT, note TEXT, url TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(wishlist)")}
    for col, typ in (("note", "TEXT"), ("page_regular", "REAL")):
        if col not in cols:
            conn.execute(f"ALTER TABLE wishlist ADD COLUMN {col} {typ}")
    if "kind" not in {r[1] for r in conn.execute("PRAGMA table_info(deals)")}:
        conn.execute("ALTER TABLE deals ADD COLUMN kind TEXT DEFAULT 'post'")
    conn.commit()
    return conn


# ---------------------------------------------------------------- fetching

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def strip_html(s):
    s = re.sub(r"<br\s*/?>|</p>|</div>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def money(s):
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


PRICE_RE = r"\$\s?([\d,]+(?:\.\d{1,2})?)"
ORIG_PATTERNS = [
    rf"{PRICE_RE} off (?:the |a |its |their )?{PRICE_RE}",                       # "$14 off the $35 regular price" -> group 2
    rf"(?:down from|list(?:ed)?|regular(?:ly)?|reg\.?|was|originally|MSRP|retails? (?:for|at)|normally)\s*(?:price\s*)?(?:of\s*|at\s*|is\s*)?{PRICE_RE}",
    rf"{PRICE_RE}\s*(?:list|regular|reg\.|MSRP)",
]


def find_orig_price(text, price):
    if not price:
        return None
    for i, pat in enumerate(ORIG_PATTERNS):
        for m in re.finditer(pat, text, flags=re.I):
            val = money(m.group(2) if i == 0 else m.group(1))
            if val and price < val < price * 20:
                return val
    # "is $30 off" / "$18 OFF" (but not spend thresholds like "$10 off orders of $50")
    for m in re.finditer(rf"{PRICE_RE}\s*off\b(?!\s*(?:orders?|your|purchases?|when|w/|with|\$|select|sitewide))", text, flags=re.I):
        amt = money(m.group(1))
        if amt and amt < price * 5:
            return round(price + amt, 2)
    return None


def find_percent(text):
    m = re.search(r"(\d{1,2})%\s*off", text, flags=re.I)
    return float(m.group(1)) if m else None


def parse_date(s):
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return now_iso()


def title_price(text):
    """First price in a title that isn't a shipping/spend threshold like "on $35+" or "w/ $49"."""
    for m in re.finditer(PRICE_RE, text):
        before = text[max(0, m.start() - 14):m.start()].lower()
        after = text[m.end():m.end() + 6]
        if after.startswith("+") or re.match(r"\s*off\b", after, re.I) or re.search(r"(?:\bon|orders?|over|w/|with|spend|\boff|\+)\s*$", before):
            continue
        return money(m.group(1))
    return None


def child(item, name):
    for c in item:
        if c.tag.split("}")[-1] == name:
            return c
    return None


def text_of(item, name):
    c = child(item, name)
    return (c.text or "").strip() if c is not None else ""


def finish(deal):
    """Fill derived fields: discount, category."""
    full = f"{deal['title']} {deal['summary']}"
    if not deal.get("orig_price"):
        deal["orig_price"] = find_orig_price(full, deal["price"])
    if deal["price"] and deal["orig_price"]:
        deal["discount_pct"] = round(100 * (1 - deal["price"] / deal["orig_price"]), 1)
    else:
        deal["discount_pct"] = find_percent(full)
    deal["category"] = None  # assigned at view time from the profile
    m = re.search(r"(?:code|coupon)\s*:?\s*\*?([A-Z0-9]{4,20})\b", deal["summary"])
    deal["coupon"] = m.group(1) if m else None
    deal["summary"] = deal["summary"][:400]
    return deal


def parse_dealnews(xml_bytes):
    deals = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        title = text_of(item, "title")
        summary = strip_html(text_of(item, "description"))
        summary = re.split(r"\bBuy Now at\b", summary)[0].strip()
        img = child(item, "content")
        price = money(text_of(item, "price")) or title_price(title)
        deals.append(finish({
            "guid": "dn-" + text_of(item, "guid"), "source": "DealNews", "title": title,
            "url": text_of(item, "link").split("?")[0], "image": img.get("url") if img is not None else None,
            "retailer": text_of(item, "retailer") or None, "price": price, "orig_price": None,
            "popularity": 0, "staff_pick": 1 if text_of(item, "staffPick") == "true" else 0,
            "summary": summary, "posted_at": parse_date(text_of(item, "pubDate")), "frontpage": 1,
        }))
    return deals


def parse_bens(xml_bytes):
    deals = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        title = re.sub(r"\s+", " ", text_of(item, "title"))
        raw = text_of(item, "description")
        summary = strip_html(raw)
        img = re.search(r'<img[^>]+src="([^"]+)"', raw)
        image = img.group(1) if img else None
        if image and image.startswith("//"):
            image = "https:" + image
        m = re.search(rf"{PRICE_RE}\s+at\s+(.+)$", title)
        price = money(m.group(1)) if m else title_price(title)
        # "has X for $6.99 - 50% off with coupon ... = $3.49": the first "for $" is the pre-coupon price
        orig = re.search(rf"\bfor {PRICE_RE}\s*-", summary)
        orig_price = money(orig.group(1)) if orig else None
        deals.append(finish({
            "guid": "bb-" + text_of(item, "guid"), "source": "Ben's Bargains", "title": title,
            "url": text_of(item, "link").split("#")[0], "image": image,
            "retailer": m.group(2).strip() if m else None, "price": price,
            "orig_price": orig_price if orig_price and price and orig_price > price else None,
            "popularity": 0, "staff_pick": 0, "summary": summary,
            "posted_at": parse_date(text_of(item, "pubDate")), "frontpage": 1,
        }))
    return deals


PARSERS = {"DealNews": parse_dealnews, "Ben's Bargains": parse_bens}


def shopify_price(url):
    """Shopify stores publish /products/<handle>.js; it carries the sale price and the compare-at (regular) price."""
    parts = urllib.parse.urlsplit(url)
    if "/products/" not in parts.path:
        return None
    try:
        data = json.loads(fetch(f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}.js"))
    except Exception:
        return None
    variants = [v for v in data.get("variants", []) if v.get("available")] or data.get("variants", [])
    if not variants:
        return None
    cheapest = min(variants, key=lambda v: v["price"])
    price = cheapest["price"] / 100
    regular = (cheapest.get("compare_at_price") or 0) / 100
    return price, regular if regular > price else None


def fetch_product_page_price(url):
    """Returns (price, regular_price, status) from the product page itself: Shopify JSON, schema.org JSON-LD,
    or price meta tags. Many big retailers block automated requests; we report that rather than work around it."""
    found = shopify_price(url)
    if found:
        return found[0], found[1], "ok"
    try:
        page = fetch(url).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, None, f"store blocks automated checks (HTTP {e.code})"
    except Exception as e:
        return None, None, f"error: {type(e).__name__}"

    def walk(node):
        if isinstance(node, dict):
            offers = node.get("offers")
            if offers:
                for o in offers if isinstance(offers, list) else [offers]:
                    if isinstance(o, dict):
                        p = o.get("price") or o.get("lowPrice")
                        if p is not None:
                            return money(str(p))
            for v in node.values():
                r = walk(v)
                if r:
                    return r
        elif isinstance(node, list):
            for v in node:
                r = walk(v)
                if r:
                    return r
        return None

    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, flags=re.S | re.I):
        try:
            price = walk(json.loads(block))
        except json.JSONDecodeError:
            continue
        if price:
            return price, None, "ok"
    m = re.search(r'(?:product:price:amount|og:price:amount|itemprop="price")[^>]*content="([\d.,]+)"', page)
    if m:
        return money(m.group(1)), None, "ok"
    return None, None, "price not readable on this page"


# ---------------------------------------------------------------- storage

def upsert_deals(conn, deals):
    ts = now_iso()
    for d in deals:
        if not d["title"]:
            continue
        cur = conn.execute("SELECT id, frontpage FROM deals WHERE guid=?", (d["guid"],)).fetchone()
        if cur:
            conn.execute(
                """UPDATE deals SET popularity=?, last_seen=?, price=?, orig_price=?, discount_pct=?,
                   frontpage=MAX(frontpage, ?), image=COALESCE(?, image), category=COALESCE(?, category) WHERE id=?""",
                (d["popularity"], ts, d["price"], d["orig_price"], d["discount_pct"], d["frontpage"],
                 d["image"], d["category"], cur["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO deals (guid, source, title, url, image, retailer, category, price, orig_price,
                   discount_pct, popularity, staff_pick, summary, coupon, posted_at, first_seen, last_seen, frontpage, kind)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d["guid"], d["source"], d["title"], d["url"], d["image"], d["retailer"], d["category"],
                 d["price"], d["orig_price"], d["discount_pct"], d["popularity"], d["staff_pick"],
                 d["summary"], d["coupon"], d["posted_at"], ts, ts, d["frontpage"], d.get("kind", "post")),
            )
    conn.commit()


def query_terms(query):
    words = re.findall(r'-?"[^"]+"|-?\S+', query.lower())
    include = [w.strip('"') for w in words if not w.startswith("-")]
    exclude = [w[1:].strip('"') for w in words if w.startswith("-") and len(w) > 1]
    return include, exclude


# Titles that mention the product but aren't it (accessories, games, giveaways).
NOISE_WORDS = ["charger", "charging station", "charging stand", "stand for", "case for", "cover for", "screen protector",
               "compatible", "replacement", "skin", "sweepstakes", "giveaway", "digital download", "videogame",
               "for iphone", "for apple", "for samsung", "mount for", "strap for", "band for",
               "attachment", "attachments", "accessory", "accessories", "refill", "sample", "samples"]
USED_RE = re.compile(r"\b(refurb\w*|renewed|used|open[- ]box|resale|reconditioned|pre-owned)\b", re.I)


def is_used(title):
    return bool(USED_RE.search(title))


def title_matches(title, query):
    t = title.lower()
    include, exclude = query_terms(query)
    if not all(w in t for w in include) or any(w in t for w in exclude):
        return False
    q = query.lower()
    if re.search(r"(?<!charging )\b(case|cover|sleeve)\b", t) and not re.search(r"\b(case|cover|sleeve)\b", q):
        return False
    return not any(n in t and n not in q for n in NOISE_WORDS)


def recompute_matches(conn, wish_ids=None):
    """Rebuild matches + daily lowest prices from scratch, keeping which hits were already notified."""
    wishes = conn.execute("SELECT * FROM wishlist").fetchall()
    # ~13 months back, so prices from the same time last year count as history
    cutoff = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    deals = conn.execute("SELECT id, title, price, posted_at, source, retailer, kind FROM deals WHERE posted_at >= ?",
                         (cutoff,)).fetchall()
    for w in wishes:
        if wish_ids and w["id"] not in wish_ids:
            continue
        notified = {r[0] for r in conn.execute("SELECT deal_id FROM wish_matches WHERE wish_id=? AND notified=1", (w["id"],))}
        conn.execute("DELETE FROM wish_matches WHERE wish_id=?", (w["id"],))
        conn.execute("DELETE FROM price_points WHERE wish_id=? AND source != 'product page'", (w["id"],))
        for d in deals:
            name = f"{d['retailer']} {d['title']}" if d["kind"] == "product" else d["title"]
            if title_matches(name, w["query"]):
                conn.execute("INSERT INTO wish_matches (wish_id, deal_id, notified) VALUES (?,?,?)",
                             (w["id"], d["id"], int(d["id"] in notified)))
                if d["price"] and not is_used(d["title"]):
                    day = d["posted_at"][:10]
                    conn.execute(
                        """INSERT INTO price_points (wish_id, day, price, source) VALUES (?,?,?,?)
                           ON CONFLICT(wish_id, day) DO UPDATE SET price=MIN(price, excluded.price),
                           source=CASE WHEN excluded.price < price THEN excluded.source ELSE source END""",
                        (w["id"], day, d["price"], d["source"]),
                    )
    conn.commit()


def notify_new_hits(conn):
    rows = conn.execute(
        """SELECT m.wish_id, m.deal_id, w.query, w.target_price, d.price, d.title FROM wish_matches m
           JOIN wishlist w ON w.id=m.wish_id JOIN deals d ON d.id=m.deal_id
           WHERE m.notified=0 AND w.target_price IS NOT NULL AND d.price IS NOT NULL AND d.price <= w.target_price
             AND d.posted_at >= ?""",  # only fresh deals; old matches are history, not alerts
        ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),),
    ).fetchall()
    rows = [r for r in rows if not is_used(r["title"])]
    for r in rows[:5]:
        msg = f"${r['price']:.2f} (target ${r['target_price']:.0f}): {r['title'][:80]}"
        try:
            subprocess.run(["osascript", "-e", f'display notification {json.dumps(msg)} with title "Deal Radar: {r["query"][:30]}" sound name "Glass"'],
                           timeout=5, check=False, capture_output=True)
        except Exception:
            pass
    conn.execute(
        """UPDATE wish_matches SET notified=1 WHERE notified=0 AND EXISTS (
           SELECT 1 FROM wishlist w JOIN deals d ON d.id=wish_matches.deal_id
           WHERE w.id=wish_matches.wish_id AND w.target_price IS NOT NULL AND d.price <= w.target_price)"""
    )
    conn.commit()
    return len(rows)


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


# ---------------------------------------------------------------- profile

def get_profile(conn):
    """The active profile, or None until setup has been completed."""
    return get_meta(conn, "profile")


def apply_profile(conn, answers):
    """Build and save a profile from setup answers, and load the chosen sale-date preset (if any).
    Events added by hand (status 'mine') are kept."""
    profile = profiles.build_profile(answers)
    set_meta(conn, "profile", profile)
    conn.execute("DELETE FROM events WHERE status != 'mine'")
    conn.executemany("INSERT INTO events (retailer, name, start, end, status, note, url) VALUES (?,?,?,?,?,?,?)",
                     profiles.SALE_DATE_PRESETS.get(answers.get("sale_dates") or "", []))
    conn.commit()
    return profile


_rx_cache = {}


def _words_rx(words):
    key = tuple(words)
    if key not in _rx_cache:
        alts = "|".join(re.escape(w.strip().lower()) for w in words if w.strip())
        _rx_cache[key] = re.compile(rf"(?<![\w'])(?:{alts})(?![\w])", re.I) if alts else None
    return _rx_cache[key]


def profile_section(profile, title, retailer=""):
    """Which profile section a feed post belongs to, or None if the profile filters it out."""
    title = title.replace("\u2019", "'")  # curly apostrophes: Men’s -> Men's
    avoid = _words_rx(profile.get("avoid", []))
    if avoid and avoid.search(title):
        return None
    for interest in profile.get("interests", []):
        rx = _words_rx(interest.get("keywords", []))
        if rx and rx.search(title):
            return interest["name"]
    # Title only: matching on the seller would pull in everything a department store sells.
    brands = _words_rx(profile.get("brands", []))
    if brands and brands.search(title):
        return "Your brands"
    stores = _words_rx(profile.get("stores", []))
    if stores and stores.search(title) and STORE_SALE_RX.search(title):
        return "Store sales"
    return None


# ---------------------------------------------------------------- run

def check_wish_page(conn, wish):
    price, regular, status = fetch_product_page_price(wish["product_url"])
    conn.execute("UPDATE wishlist SET page_price=?, page_regular=?, page_checked_at=?, page_status=? WHERE id=?",
                 (price, regular, now_iso(), status, wish["id"]))
    if price:
        conn.execute(
            """INSERT INTO price_points (wish_id, day, price, source) VALUES (?,?,?,'product page')
               ON CONFLICT(wish_id, day) DO UPDATE SET price=MIN(price, excluded.price)""",
            (wish["id"], now_iso()[:10], price),
        )
    conn.commit()


def run_scrape(conn, only_wish_id=None, log=print):
    profile = get_profile(conn)
    if profile is None:
        log("no profile yet; finish setup in the UI first")
        return 0
    status = get_meta(conn, "sources", {})
    if only_wish_id is None:
        for name, url in FEEDS.items():
            try:
                deals = PARSERS[name](fetch(url))
                upsert_deals(conn, deals)
                status[name] = {"ok": True, "count": len(deals), "at": now_iso()}
                log(f"{name}: {len(deals)} deals")
            except Exception as e:
                status[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "at": now_iso()}
                log(f"{name}: FAILED {e}")
            time.sleep(REQUEST_GAP_S)

    wishes = conn.execute("SELECT * FROM wishlist" + (" WHERE id=?" if only_wish_id else ""),
                          (only_wish_id,) if only_wish_id else ()).fetchall()
    for w in wishes:
        if w["product_url"]:
            check_wish_page(conn, w)
            time.sleep(REQUEST_GAP_S)

    if only_wish_id is None:
        shops = set(profile.get("shops") or [])
        for name, emits, read in stores.readers(profile.get("department", "all")):
            if shops and not shops & set(emits):
                status.pop(name, None)  # not part of this profile
                continue
            try:
                try:
                    found = read(fetch, now_iso(), REQUEST_GAP_S)
                except urllib.error.HTTPError as e:
                    if e.code != 429:
                        raise
                    # rate limited: wait as long as the store asks (within reason), then try once more
                    wait = min(int(e.headers.get("Retry-After") or 5), 15)
                    log(f"{name}: rate limited, retrying in {wait}s")
                    time.sleep(wait)
                    found = read(fetch, now_iso(), REQUEST_GAP_S)
                upsert_deals(conn, found)
                status[name] = {"ok": True, "count": len(found), "at": now_iso(), "store": True}
                log(f"{name}: {len(found)} products")
            except urllib.error.HTTPError as e:
                why = {403: "blocks automated requests", 429: "refusing requests for now (too many requests)"}.get(
                    e.code, f"HTTP {e.code}")
                status[name] = {"ok": False, "error": why, "at": now_iso(), "store": True}
                log(f"{name}: FAILED {why}")
            except Exception as e:
                status[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "at": now_iso(), "store": True}
                log(f"{name}: FAILED {e}")
            time.sleep(STORE_GAP_S)

    recompute_matches(conn)
    hits = notify_new_hits(conn)
    if only_wish_id is None:
        set_meta(conn, "sources", status)
        set_meta(conn, "last_refresh", now_iso())
    return hits


if __name__ == "__main__":
    c = connect()
    run_scrape(c)
    print(c.execute("SELECT COUNT(*) FROM deals").fetchone()[0], "deals stored")
