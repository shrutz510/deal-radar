"""Store readers: products straight from retailer websites.

A reader is a function (fetch, ts, pause, dept) -> list of product dicts:
  fetch(url) -> bytes  shared HTTP helper (honest User-Agent, timeout); raise on HTTP errors
  ts                   ISO timestamp to use as posted_at for new items
  pause                seconds to sleep between requests inside one reader
  dept                 "women" | "men" | "all", from the profile; read only the matching departments
Build each dict with product(); it fills the same fields scraper.upsert_deals stores for feed posts,
plus kind="product" and a section from classify(). Register the reader in readers() and describe the
store(s) in STORE_INFO (what they sell and for whom; setup uses it to suggest stores). Shopify stores
need no reader code: add a row to SHOPIFY and to STORE_INFO.

Only public, unauthenticated endpoints are used. A store that refuses (403/429) is reported in the
refresh status and skipped; readers must not try to get around blocking.
"""
import json
import re
import time
import urllib.parse

# Sections a product can land in. Profiles must use these exact names for store products to show.
JEANS, CLOTHES, UNDER, PERFUME, MAKEUP, SKIN, SHOES, TECH, HAIR = (
    "Jeans", "Clothes", "Undergarments", "Perfume", "Makeup", "Skincare", "Shoes & bags", "Earphones & tech", "Hair tools")
SECTIONS = [CLOTHES, JEANS, UNDER, PERFUME, MAKEUP, SKIN, SHOES, TECH, HAIR]


def wants(dept, side):
    """Should a reader include the "women" or "men" side of a store for this department?"""
    return dept in (side, "all")

# First match wins, so the specific kinds come before the catch-all clothes words.
CLASSIFY = [
    (JEANS, r"\bjeans?\b|\bdenim\b"),
    (UNDER, r"\b(bra|bras|bralette|underwear|panty|panties|thong|briefs?|lingerie|boyshorts?|cheeky|slip|boxers?|trunks)\b"),
    (PERFUME, r"\b(perfume|parfum|eau de|edp|edt|fragrance|body mist|cologne)\b"),
    (HAIR, r"\b(hair dryer|airwrap|flexstyle|straightener|curling|flat iron|hair styler)\b"),
    (MAKEUP, r"\b(lip|lips|lipstick|gloss|mascara|foundation|concealer|blush|bronzer|highlighter|eyeshadow|"
             r"eyeliner|liner|brow|primer|setting spray|powder|makeup|brush|palette|tint)\b"),
    (SKIN, r"\b(serum|moisturi[sz]er|cleanser|sunscreen|spf|toner|cream|mask|skincare|exfoliat\w*|retinol|balm)\b"),
    (SHOES, r"\b(shoes?|boots?|booties|heels?|sneakers?|loafers?|sandals?|flats|mules?|pumps|bag|tote|purse|"
            r"crossbody|clutch|wallet)\b"),
    (TECH, r"\b(earbuds|headphones|airpods|speaker)\b"),
]


def classify(text, fallback):
    t = text.lower()
    for section, rx in CLASSIFY:
        if re.search(rx, t):
            return section
    return fallback


def nice(name):
    """ZARA SHOUTS ITS NAMES -> Zara Shouts Its Names (keeps short words like 'of' lower)."""
    if name and name.isupper():
        small = {"of", "and", "with", "in", "the", "a", "to"}
        return " ".join(w if i and w.lower() in small else w.capitalize() for i, w in enumerate(name.lower().split()))
    return name


def product(store, pid, title, url, image, price, regular, section, posted_at):
    on_sale = bool(regular and price and regular > price)
    return {
        "guid": f"{store}:{pid}", "source": store, "retailer": store, "kind": "product",
        "title": nice(title), "url": url, "image": image, "category": section,
        "price": price, "orig_price": regular if on_sale else None,
        "discount_pct": round(100 * (1 - price / regular), 1) if on_sale else None,
        "popularity": 0, "staff_pick": 0, "summary": "", "coupon": None,
        "posted_at": posted_at, "frontpage": 1,
    }


# ---------------------------------------------------------------- Zara (and Massimo Dutti, listed on zara.com)

ZARA_BASE = "https://www.zara.com/us/en"
SALE = re.compile(r"SPECIAL PRICES|SALE|% OFF")  # Zara renames its sale list; match it by pattern
# department -> (path in Zara's category tree, section hint, how many to keep; None = all).
# A path element that is SALE matches whichever category name looks like the sale list.
ZARA_LISTS = {
    "women": [
        (("WOMAN", "COLLECTION", SALE, "VIEW ALL"), None, None),
        (("WOMAN", "NEW ARRIVALS", "THE NEW"), None, 40),
        (("WOMAN", "COLLECTION", "BEST SELLERS", "VIEW ALL"), None, 40),
        (("WOMAN", "COLLECTION", "JEANS", "VIEW ALL"), JEANS, 30),
        (("WOMAN", "COLLECTION", "LINGERIE", "VIEW ALL"), UNDER, 24),
        (("WOMAN", "PERFUMES", "PERFUMES", "VIEW ALL"), PERFUME, 24),
        (("BEAUTY", "WOMAN", "MAKEUP", "VIEW ALL"), MAKEUP, 24),
        (("MASSIMO DUTTI", "WOMAN", "DISCOVER THE COLLECTION", SALE, "VIEW ALL"), None, None),
        (("MASSIMO DUTTI", "WOMAN", "THE NEW"), None, 24),
    ],
    "men": [
        (("MAN", "COLLECTION", SALE, "VIEW ALL"), None, None),
        (("MAN", "NEW ARRIVALS", "THE NEW"), None, 40),
        (("MAN", "COLLECTION", "BEST SELLERS", "VIEW ALL"), None, 40),
        (("MAN", "COLLECTION", "JEANS", "VIEW ALL"), JEANS, 30),
        (("MAN", "SHOES | ACCESSORIES", "UNDERWEAR | SOCKS", "UNDERWEAR"), UNDER, 24),
        (("MAN", "COLLECTION", "COLOGNES", "VIEW ALL"), PERFUME, 24),
        (("MAN", "SHOES | ACCESSORIES", "SHOES", "VIEW ALL"), SHOES, 24),
    ],
}


def _zara_find(ids, pattern):
    """Category id for a path, where pattern elements are names or compiled regexes."""
    for path, cid in ids.items():
        if len(path) == len(pattern) and all(p.search(x) if hasattr(p, "search") else p == x
                                             for p, x in zip(pattern, path)):
            return cid
    return None


def _zara_ids(tree):
    ids = {}

    def walk(cats, path):
        for c in cats:
            p = path + (c.get("name", "").strip().upper(),)
            ids[p] = c.get("id")
            walk(c.get("subcategories") or [], p)
    walk(tree.get("categories", []), ())
    return ids


def read_zara(fetch, ts, pause, dept):
    ids = _zara_ids(json.loads(fetch(f"{ZARA_BASE}/categories?ajax=true")))
    lists = [entry for side in ("women", "men") if wants(dept, side) for entry in ZARA_LISTS[side]]
    out, seen = [], set()
    for path, hint, limit in lists:
        cid = _zara_find(ids, path)
        if not cid:
            continue
        time.sleep(pause)
        data = json.loads(fetch(f"{ZARA_BASE}/category/{cid}/products?ajax=true"))
        kept = 0
        for group in data.get("productGroups", []):
            for el in group.get("elements", []):
                for c in el.get("commercialComponents") or []:
                    seo = c.get("seo") or {}
                    key = seo.get("seoProductId")
                    if not key or key in seen or not c.get("price") or (limit and kept >= limit):
                        continue
                    seen.add(key)
                    colors = (c.get("detail") or {}).get("colors") or []
                    media = (colors[0].get("xmedia") if colors else None) or c.get("xmedia") or []
                    image = media[0].get("url", "").replace("{width}", "600") if media else None
                    store = "Massimo Dutti" if path[0] == "MASSIMO DUTTI" else "Zara"
                    url = f"{ZARA_BASE}/{seo.get('keyword')}-p{key}.html?v1={seo.get('discernProductId', c.get('id'))}"
                    name = c.get("name", "")
                    old = c.get("oldPrice")
                    out.append(product(store, key, name, url, image, c["price"] / 100, old / 100 if old else None,
                                       hint or classify(f"{name} {c.get('familyName', '')}", CLOTHES), ts))
                    kept += 1
    return out


# ---------------------------------------------------------------- Uniqlo (newest items per department; markdowns show as deals)

UNIQLO_API = "https://www.uniqlo.com/us/api/commerce/v5/en/products?q={q}&sort=1&offset={offset}&limit=100"
UNIQLO_KEEP = 40  # per department


def read_uniqlo(fetch, ts, pause, dept):
    out = []
    for side, q, gender in (("women", "women", "WOMEN"), ("men", "men", "MEN")):
        if not wants(dept, side):
            continue
        kept, names = 0, set()
        for offset in (0, 100):
            items = json.loads(fetch(UNIQLO_API.format(q=q, offset=offset)))["result"]["items"]
            for it in items:
                name = it.get("name", "")
                if it.get("genderCategory") != gender or name in names or kept >= UNIQLO_KEEP:
                    continue
                prices = it.get("prices") or {}
                base = (prices.get("base") or {}).get("value")
                promo = (prices.get("promo") or {}).get("value") or base
                if not promo:
                    continue
                names.add(name)
                imgs = (it.get("images") or {}).get("main") or {}
                image = next(iter(imgs.values()), {}).get("image") if imgs else None
                pid = it["productId"]
                out.append(product("Uniqlo", pid, name, f"https://www.uniqlo.com/us/en/products/{pid}/00",
                                   image, promo, base, classify(name, CLOTHES), ts))
                kept += 1
            if kept >= UNIQLO_KEEP or len(items) < 100:
                break
            time.sleep(pause)
        time.sleep(pause)
    return out


# ---------------------------------------------------------------- Ulta (sale page; product cards are in the page data)

ULTA_SALE = "https://www.ulta.com/promotion/sale?page={page}"
ULTA_CARD = re.compile(
    r'"productId":"(?P<id>[^"]+)".{0,1500}?"imageUrl":"(?P<img>[^"]+)".{0,1500}?"brandName":"(?P<brand>[^"]*)",'
    r'"productName":"(?P<name>[^"]+)".{0,200}?"listPrice":"\$?(?P<list>[\d.,]*)","salePrice":"\$?(?P<sale>[\d.,]*)"', re.S)


def _unescape(s):
    return json.loads(f'"{s}"') if "\\" in s else s


def read_ulta(fetch, ts, pause, dept):
    out, seen = [], set()
    for page in (1, 2):
        page_html = fetch(ULTA_SALE.format(page=page)).decode("utf-8", "ignore")
        for m in ULTA_CARD.finditer(page_html):
            pid = m["id"]
            if pid in seen:
                continue
            seen.add(pid)
            link = re.search(r'https:\\u002F\\u002Fwww\.ulta\.com\\u002Fp\\u002F[^"]*' + re.escape(pid) + r'[^"]*', page_html)
            url = _unescape(link.group(0)) if link else f"https://www.ulta.com/search?search={urllib.parse.quote(pid)}"
            price = float(m["sale"].replace(",", "")) if m["sale"] else None
            regular = float(m["list"].replace(",", "")) if m["list"] else None
            if not price:
                price, regular = regular, None
            if not price:
                continue
            name = f"{_unescape(m['brand'])} {_unescape(m['name'])}".strip()
            out.append(product("Ulta", pid, name, url, _unescape(m["img"]), price, regular, classify(name, MAKEUP), ts))
        time.sleep(pause)
    return out


# ---------------------------------------------------------------- Shopify brands (public /products.json)

# store name, domain, section when the product type doesn't say
SHOPIFY = [
    ("Oh Polly", "www.ohpolly.com", CLOTHES),
    ("Motel Rocks", "www.motelrocks.com", CLOTHES),
    ("Edikted", "edikted.com", CLOTHES),
    ("Steve Madden", "www.stevemadden.com", SHOES),
    ("Parade", "yourparade.com", UNDER),
    ("Glossier", "www.glossier.com", MAKEUP),
    ("Fenty Beauty", "fentybeauty.com", MAKEUP),
    ("Rare Beauty", "www.rarebeauty.com", MAKEUP),
    ("Rhode", "www.rhodeskin.com", SKIN),
    ("Kylie Cosmetics", "www.kyliecosmetics.com", MAKEUP),
    ("Summer Fridays", "www.summerfridays.com", SKIN),
    ("Tower 28", "www.tower28beauty.com", MAKEUP),
    ("Dossier", "www.dossier.co", PERFUME),
]
SKIP_RX = re.compile(r"\b(gift card|e-gift|sample|mystery|bundle builder|kids?|shipping protection|insurance|"
                     r"phone case|case|keychain|holder|charm|sticker|tote bag)\b", re.I)
NEW_PER_STORE = 10  # full-price newest items kept for inspiration, next to everything on sale


GENDER_RX = {"women": re.compile(r"\b(women'?s?|womens|ladies)\b", re.I), "men": re.compile(r"\b(men'?s?|mens)\b", re.I)}


def read_shopify(name, domain, fallback, fetch, ts, pause, dept):
    items = json.loads(fetch(f"https://{domain}/products.json?limit=250"))["products"]
    # drop items explicitly marked for the other department (most of these stores sell to one anyway)
    other = None if dept == "all" else GENDER_RX["men" if dept == "women" else "women"]
    out, fresh = [], 0
    for p in items:
        text = f"{p.get('title', '')} {p.get('product_type', '')}"
        marks = " ".join([text] + list(p.get("tags") or []))
        if SKIP_RX.search(text) or (other and other.search(marks)) or not p.get("variants"):
            continue
        v = min(p["variants"], key=lambda v: float(v.get("price") or 1e9))
        price = float(v.get("price") or 0)
        regular = float(v["compare_at_price"]) if v.get("compare_at_price") else None
        on_sale = bool(regular and regular > price)
        if not price or (not on_sale and fresh >= NEW_PER_STORE):
            continue
        fresh += not on_sale
        img = (p.get("images") or [{}])[0].get("src")
        if img:
            img += ("&" if "?" in img else "?") + "width=600"
        out.append(product(name, p["id"], p.get("title", ""), f"https://{domain}/products/{p['handle']}", img,
                           price, regular, classify(text, fallback), ts))
    return out


# What each store sells and for whom ("women", "men" or "all"); setup suggests stores from this.
STORE_INFO = {
    "Zara": {"sells": [CLOTHES, JEANS, UNDER, PERFUME, MAKEUP, SHOES], "for": "all"},
    "Massimo Dutti": {"sells": [CLOTHES, JEANS, SHOES], "for": "women"},
    "Uniqlo": {"sells": [CLOTHES, JEANS], "for": "all"},
    "Ulta": {"sells": [MAKEUP, SKIN, PERFUME, HAIR], "for": "all"},
    "Oh Polly": {"sells": [CLOTHES], "for": "women"},
    "Motel Rocks": {"sells": [CLOTHES, JEANS], "for": "women"},
    "Edikted": {"sells": [CLOTHES, JEANS], "for": "women"},
    "Steve Madden": {"sells": [SHOES], "for": "all"},
    "Parade": {"sells": [UNDER], "for": "women"},
    "Glossier": {"sells": [MAKEUP, SKIN, PERFUME], "for": "all"},
    "Fenty Beauty": {"sells": [MAKEUP, SKIN], "for": "all"},
    "Rare Beauty": {"sells": [MAKEUP], "for": "all"},
    "Rhode": {"sells": [SKIN, MAKEUP], "for": "all"},
    "Kylie Cosmetics": {"sells": [MAKEUP], "for": "all"},
    "Summer Fridays": {"sells": [SKIN, MAKEUP], "for": "all"},
    "Tower 28": {"sells": [MAKEUP, SKIN], "for": "all"},
    "Dossier": {"sells": [PERFUME], "for": "all"},
}
STORE_NAMES = list(STORE_INFO)


def readers(dept="all"):
    """Yields (status name, store names it can emit, reader(fetch, ts, pause)) in refresh order."""
    yield "Zara", ["Zara", "Massimo Dutti"], lambda fetch, ts, pause: read_zara(fetch, ts, pause, dept)
    yield "Uniqlo", ["Uniqlo"], lambda fetch, ts, pause: read_uniqlo(fetch, ts, pause, dept)
    yield "Ulta", ["Ulta"], lambda fetch, ts, pause: read_ulta(fetch, ts, pause, dept)
    for name, domain, fallback in SHOPIFY:
        yield name, [name], (lambda n, d, f: lambda fetch, ts, pause: read_shopify(n, d, f, fetch, ts, pause, dept))(
            name, domain, fallback)
