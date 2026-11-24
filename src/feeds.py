"""Deal-site RSS feeds and the price parsing their free-text titles need.

A feed is a name in FEEDS mapped to (url, parser); a parser turns the RSS bytes into item dicts
(see db.upsert_items for the fields). Which profile section a post lands in is decided at read time
(profiles.section_for), so posts are stored without one.
"""
import html
import re
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

from db import now_iso

PRICE_RE = r"\$\s?([\d,]+(?:\.\d{1,2})?)"
ORIG_PATTERNS = [
    rf"{PRICE_RE} off (?:the |a |its |their )?{PRICE_RE}",  # "$14 off the $35 regular price" -> group 2
    rf"(?:down from|list(?:ed)?|regular(?:ly)?|reg\.?|was|originally|MSRP|retails? (?:for|at)|normally)\s*"
    rf"(?:price\s*)?(?:of\s*|at\s*|is\s*)?{PRICE_RE}",
    rf"{PRICE_RE}\s*(?:list|regular|reg\.|MSRP)",
]


def money(s):
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def title_price(text):
    """First price in a title that isn't a shipping/spend threshold like "on $35+" or "w/ $49"."""
    for m in re.finditer(PRICE_RE, text):
        before = text[max(0, m.start() - 14):m.start()].lower()
        after = text[m.end():m.end() + 6]
        if after.startswith("+") or re.match(r"\s*off\b", after, re.I) or \
                re.search(r"(?:\bon|orders?|over|w/|with|spend|\boff|\+)\s*$", before):
            continue
        return money(m.group(1))
    return None


def find_orig_price(text, price):
    if not price:
        return None
    for i, pat in enumerate(ORIG_PATTERNS):
        for m in re.finditer(pat, text, flags=re.I):
            val = money(m.group(2) if i == 0 else m.group(1))
            if val and price < val < price * 20:
                return val
    # "is $30 off" / "$18 OFF" (but not spend thresholds like "$10 off orders of $50")
    for m in re.finditer(rf"{PRICE_RE}\s*off\b(?!\s*(?:orders?|your|purchases?|when|w/|with|\$|select|sitewide))",
                         text, flags=re.I):
        amt = money(m.group(1))
        if amt and amt < price * 5:
            return round(price + amt, 2)
    return None


def find_percent(text):
    m = re.search(r"(\d{1,2})%\s*off", text, flags=re.I)
    return float(m.group(1)) if m else None


def strip_html(s):
    s = re.sub(r"<br\s*/?>|</p>|</div>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_date(s):
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return now_iso()


def child(item, name):
    return next((c for c in item if c.tag.split("}")[-1] == name), None)


def text_of(item, name):
    c = child(item, name)
    return (c.text or "").strip() if c is not None else ""


def post(**d):
    """Complete a parsed post: original price, discount and coupon code from the title and summary."""
    full = f"{d['title']} {d['summary']}"
    d["orig_price"] = d.get("orig_price") or find_orig_price(full, d["price"])
    d["discount_pct"] = (round(100 * (1 - d["price"] / d["orig_price"]), 1) if d["price"] and d["orig_price"]
                         else find_percent(full))
    code = re.search(r"(?:code|coupon)\s*:?\s*\*?([A-Z0-9]{4,20})\b", d["summary"])
    d["coupon"] = code.group(1) if code else None
    d["summary"] = d["summary"][:400]
    return d


def parse_dealnews(xml_bytes):
    items = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        title = text_of(item, "title")
        summary = re.split(r"\bBuy Now at\b", strip_html(text_of(item, "description")))[0].strip()
        img = child(item, "content")
        items.append(post(
            guid="dn-" + text_of(item, "guid"), source="DealNews", title=title, summary=summary,
            url=text_of(item, "link").split("?")[0], image=img.get("url") if img is not None else None,
            retailer=text_of(item, "retailer") or None, price=money(text_of(item, "price")) or title_price(title),
            staff_pick=int(text_of(item, "staffPick") == "true"), posted_at=parse_date(text_of(item, "pubDate"))))
    return items


def parse_bens(xml_bytes):
    items = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        title = re.sub(r"\s+", " ", text_of(item, "title"))
        raw = text_of(item, "description")
        summary = strip_html(raw)
        img = re.search(r'<img[^>]+src="([^"]+)"', raw)
        image = img.group(1) if img else None
        if image and image.startswith("//"):
            image = "https:" + image
        m = re.search(rf"{PRICE_RE}\s+at\s+(.+)$", title)  # "... $29.99 at Store"
        price = money(m.group(1)) if m else title_price(title)
        # "has X for $6.99 - 50% off with coupon ... = $3.49": the first "for $" is the pre-coupon price
        orig = re.search(rf"\bfor {PRICE_RE}\s*-", summary)
        orig_price = money(orig.group(1)) if orig else None
        items.append(post(
            guid="bb-" + text_of(item, "guid"), source="Ben's Bargains", title=title, summary=summary,
            url=text_of(item, "link").split("#")[0], image=image, retailer=m.group(2).strip() if m else None,
            price=price, orig_price=orig_price if orig_price and price and orig_price > price else None,
            posted_at=parse_date(text_of(item, "pubDate"))))
    return items


FEEDS = {
    "DealNews": ("https://www.dealnews.com/?rss=1", parse_dealnews),
    "Ben's Bargains": ("https://bensbargains.com/rss/", parse_bens),
}
