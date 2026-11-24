"""Read side: the JSON the UI renders. The profile is applied here, at read time, so editing it takes
effect immediately without re-fetching anything."""
import re
from datetime import datetime, timedelta, timezone

import profiles
import stores
from config import FEED_DAYS, PRODUCT_STALE_H, REFRESH_EVERY_S
from db import get_meta, now_iso, rows
from wishlist import is_used

RECENT_DAYS = 14  # what counts as a price "now" for the wishlist
MULTIPACK_RX = re.compile(r"\b(\d{1,2})\s*(?:pairs?|pack|pk|pieces?|pcs)?\s*(?:for|/)\s*\$\s?(\d+(?:\.\d\d)?)", re.I)


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def unit_price(title):
    """'10 Pairs for $38' / '10/$31 panties' -> price per item."""
    m = MULTIPACK_RX.search(title)
    return round(float(m.group(2)) / int(m.group(1)), 2) if m and int(m.group(1)) > 1 else None


def score(d):
    """Roughly 0-80: discount carries most weight, staff picks and freshness add on top."""
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(d["posted_at"])).total_seconds() / 3600
    return round(min(d["discount_pct"] or 0, 90) * 0.6 + (8 if d["staff_pick"] else 0) + max(0, 10 - age_h / 12), 1)


def deals(conn, profile):
    """Items that fit the profile (or match a wishlist entry), with their feed section and score."""
    found = rows(conn, """
        SELECT d.*, (SELECT GROUP_CONCAT(m.wish_id) FROM wish_matches m WHERE m.deal_id=d.id) AS wish_ids
        FROM deals d WHERE (kind = 'product' AND last_seen >= ?) OR (kind != 'product' AND posted_at >= ?)
        ORDER BY posted_at DESC LIMIT 5000""", (_ago(hours=PRODUCT_STALE_H), _ago(days=FEED_DAYS)))
    featured = {i["name"] for i in profile.get("interests", []) if i.get("focus")}
    out = []
    for d in found:
        d["wish_ids"] = [int(x) for x in d["wish_ids"].split(",")] if d["wish_ids"] else []
        d["category"] = profiles.section_for(profile, d) or ("Wishlist" if d["wish_ids"] else None)
        if d["category"]:
            d["unit_price"] = unit_price(d["title"])
            d["score"] = score(d) + (10 if d["category"] in featured else 0)
            out.append(d)
    return out


def last_season_window(profile):
    """Dates around the countdown date one year earlier, e.g. last year's Black Friday season."""
    try:
        d = datetime.fromisoformat((profile.get("countdown") or {})["date"])
    except (KeyError, TypeError, ValueError):
        return None
    d = d.replace(year=d.year - 1)
    return (d - timedelta(days=26)).date().isoformat(), (d + timedelta(days=8)).date().isoformat()


def wish_status(w, now_price, best_now):
    target = w["target_price"]
    if now_price is None:
        return "waiting"
    if target and now_price <= target:
        return "hit"
    store_sale = bool(w["page_regular"] and w["page_price"] and w["page_price"] < w["page_regular"])
    if store_sale or (best_now and (best_now["discount_pct"] or 0) >= 15):
        return "sale"
    return "close" if target and now_price <= target * 1.1 else "watching"


def wishes(conn, profile):
    window, recent = last_season_window(profile), _ago(days=RECENT_DAYS)
    out = []
    for w in rows(conn, "SELECT * FROM wishlist ORDER BY priority, created_at DESC"):
        found = rows(conn, """SELECT d.* FROM wish_matches m JOIN deals d ON d.id=m.deal_id
                              WHERE m.wish_id=? ORDER BY d.posted_at DESC LIMIT 200""", (w["id"],))
        for d in found:
            d["used"] = is_used(d["title"])
        priced = [d for d in found if d["price"] and not d["used"]]
        current = [d for d in priced if (d["last_seen"] if d["kind"] == "product" else d["posted_at"]) >= recent]
        last_season = [d for d in priced if window and window[0] <= d["posted_at"][:10] <= window[1]]
        best_now = min(current, key=lambda d: d["price"], default=None)
        now_price = min(filter(None, [w["page_price"], best_now and best_now["price"]]), default=None)
        history = rows(conn, "SELECT day, price, source FROM price_points WHERE wish_id=? ORDER BY day", (w["id"],))
        out.append({**w, "matches": found[:12], "match_count": len(found), "best_now": best_now,
                    "now_price": now_price, "lowest": min((h["price"] for h in history), default=None),
                    "history": history, "status": wish_status(w, now_price, best_now),
                    "last_year": min(last_season, key=lambda d: d["price"], default=None)})
    return out


def state(conn, refreshing):
    profile = get_meta(conn, "profile")
    return {
        "profile": profile,
        "needs_setup": profile is None,
        "setup_options": {  # everything the setup form offers
            "departments": profiles.DEPARTMENTS,
            "categories": profiles.CATEGORIES,
            "stores": stores.STORE_INFO,
            "presets": profiles.PRESETS,
            "sale_dates": list(profiles.SALE_DATE_PRESETS),
        },
        "events": rows(conn, "SELECT * FROM events ORDER BY start"),
        "wishlist": wishes(conn, profile or {}),
        "deals": deals(conn, profile) if profile else [],
        "meta": {
            "feed_days": FEED_DAYS,
            "last_refresh": get_meta(conn, "last_refresh"),
            "sources": get_meta(conn, "sources", {}),
            "refreshing": refreshing,
            "refresh_every_min": REFRESH_EVERY_S // 60,
            "now": now_iso(),
        },
    }
