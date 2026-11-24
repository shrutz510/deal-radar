"""Wishlist: match stored items against wishlist queries, keep price history, alert on target hits,
and read a wishlist item's own product page for its current price."""
import json
import re
import subprocess
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

from db import now_iso
from feeds import money
from net import fetch

# Titles that mention the product but aren't it (accessories, games, giveaways).
NOISE_WORDS = ["charger", "charging station", "charging stand", "stand for", "case for", "cover for",
               "screen protector", "compatible", "replacement", "skin", "sweepstakes", "giveaway", "digital download",
               "videogame", "for iphone", "for apple", "for samsung", "mount for", "strap for", "band for",
               "attachment", "attachments", "accessory", "accessories", "refill", "sample", "samples"]
USED_RE = re.compile(r"\b(refurb\w*|renewed|used|open[- ]box|resale|reconditioned|pre-owned)\b", re.I)
HISTORY_DAYS = 400  # ~13 months, so prices from the same time last year count as history
ALERT_DAYS = 3      # only fresh matches notify; older ones are history


def is_used(title):
    return bool(USED_RE.search(title))


def query_terms(query):
    """'airpods pro -case "usb c"' -> (["airpods", "pro", "usb c"], ["case"])"""
    words = re.findall(r'-?"[^"]+"|-?\S+', query.lower())
    include = [w.strip('"') for w in words if not w.startswith("-")]
    exclude = [w[1:].strip('"') for w in words if w.startswith("-") and len(w) > 1]
    return include, exclude


def matches(name, query):
    t, q = name.lower(), query.lower()
    include, exclude = query_terms(query)
    if not all(w in t for w in include) or any(w in t for w in exclude):
        return False
    if re.search(r"(?<!charging )\b(case|cover|sleeve)\b", t) and not re.search(r"\b(case|cover|sleeve)\b", q):
        return False
    return not any(n in t and n not in q for n in NOISE_WORDS)


def recompute(conn, wish_ids=None):
    """Rebuild matches and daily lowest prices from scratch, remembering which hits already notified."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).isoformat()
    items = conn.execute("SELECT id, title, price, posted_at, source, retailer, kind FROM deals WHERE posted_at >= ?",
                         (cutoff,)).fetchall()
    for w in conn.execute("SELECT id, query FROM wishlist").fetchall():
        if wish_ids and w["id"] not in wish_ids:
            continue
        notified = {r[0] for r in conn.execute("SELECT deal_id FROM wish_matches WHERE wish_id=? AND notified=1",
                                               (w["id"],))}
        conn.execute("DELETE FROM wish_matches WHERE wish_id=?", (w["id"],))
        conn.execute("DELETE FROM price_points WHERE wish_id=? AND source != 'product page'", (w["id"],))
        for d in items:
            # store products don't repeat the brand in their name, so the store counts as part of it
            name = f"{d['retailer']} {d['title']}" if d["kind"] == "product" else d["title"]
            if not matches(name, w["query"]):
                continue
            conn.execute("INSERT INTO wish_matches (wish_id, deal_id, notified) VALUES (?,?,?)",
                         (w["id"], d["id"], int(d["id"] in notified)))
            if d["price"] and not is_used(d["title"]):
                conn.execute(
                    """INSERT INTO price_points (wish_id, day, price, source) VALUES (?,?,?,?)
                       ON CONFLICT(wish_id, day) DO UPDATE SET price=MIN(price, excluded.price),
                       source=CASE WHEN excluded.price < price THEN excluded.source ELSE source END""",
                    (w["id"], d["posted_at"][:10], d["price"], d["source"]))
    conn.commit()


def notify_hits(conn):
    """Desktop notification for fresh matches at or under target (macOS; silently skipped elsewhere)."""
    since = (datetime.now(timezone.utc) - timedelta(days=ALERT_DAYS)).isoformat()
    hits = [r for r in conn.execute(
        """SELECT w.query, w.target_price, d.price, d.title FROM wish_matches m
           JOIN wishlist w ON w.id=m.wish_id JOIN deals d ON d.id=m.deal_id
           WHERE m.notified=0 AND d.price <= w.target_price AND d.posted_at >= ?""", (since,)) if not is_used(r["title"])]
    for r in hits[:5]:
        msg = f"${r['price']:.2f} (target ${r['target_price']:.0f}): {r['title'][:80]}"
        script = f'display notification {json.dumps(msg)} with title "Deal Radar: {r["query"][:30]}" sound name "Glass"'
        try:
            subprocess.run(["osascript", "-e", script], timeout=5, check=False, capture_output=True)
        except Exception:
            pass
    conn.execute("""UPDATE wish_matches SET notified=1 WHERE notified=0 AND EXISTS (
                    SELECT 1 FROM wishlist w JOIN deals d ON d.id=wish_matches.deal_id
                    WHERE w.id=wish_matches.wish_id AND d.price <= w.target_price)""")
    conn.commit()
    return len(hits)


# ---------------------------------------------------------------- product page prices

def _shopify_price(url):
    """Shopify serves /products/<handle>.js with the sale price and the compare-at (regular) price, in cents."""
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
    price, regular = cheapest["price"] / 100, (cheapest.get("compare_at_price") or 0) / 100
    return price, regular if regular > price else None


def _offer_price(node):
    """First offers.price / lowPrice anywhere in a schema.org JSON-LD tree."""
    if isinstance(node, dict):
        offers = node.get("offers")
        for o in (offers if isinstance(offers, list) else [offers]) if offers else []:
            if isinstance(o, dict) and (o.get("price") or o.get("lowPrice")) is not None:
                return money(str(o.get("price") or o.get("lowPrice")))
        node = list(node.values())
    if isinstance(node, list):
        return next((p for p in map(_offer_price, node) if p), None)
    return None


def page_price(url):
    """(price, regular_price, status) from the product page: Shopify JSON, then schema.org JSON-LD, then
    price meta tags. Stores that block automated requests are reported, not worked around."""
    found = _shopify_price(url)
    if found:
        return found[0], found[1], "ok"
    try:
        page = fetch(url).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, None, f"store blocks automated checks (HTTP {e.code})"
    except Exception as e:
        return None, None, f"error: {type(e).__name__}"
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, flags=re.S | re.I):
        try:
            price = _offer_price(json.loads(block))
        except json.JSONDecodeError:
            continue
        if price:
            return price, None, "ok"
    m = re.search(r'(?:product:price:amount|og:price:amount|itemprop="price")[^>]*content="([\d.,]+)"', page)
    return (money(m.group(1)), None, "ok") if m else (None, None, "price not readable on this page")


def check_page(conn, wish):
    price, regular, status = page_price(wish["product_url"])
    conn.execute("UPDATE wishlist SET page_price=?, page_regular=?, page_checked_at=?, page_status=? WHERE id=?",
                 (price, regular, now_iso(), status, wish["id"]))
    if price:
        conn.execute("""INSERT INTO price_points (wish_id, day, price, source) VALUES (?,?,?,'product page')
                        ON CONFLICT(wish_id, day) DO UPDATE SET price=MIN(price, excluded.price)""",
                     (wish["id"], now_iso()[:10], price))
    conn.commit()
