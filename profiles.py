"""Turns setup answers into a profile.

Nothing about who the tracker is for is hard-coded: on first run the UI asks a few questions (who you
shop for, which categories, stores, brands, what to hide, an optional countdown) and build_profile()
turns the answers into the profile the rest of the app reads. The answers are kept on the profile
under "setup", so the form can be reopened pre-filled. PRESETS are just example answers.

Profile fields (stored as JSON in meta.profile):
  title       name shown in the UI
  about       free text
  department  "women" | "men" | "all": which sections store readers pull from
  countdown   {"label", "date"} or None
  interests   feed sections: {name, keywords, focus}. Store products show in the section whose name
              matches their classification (stores.SECTIONS); feed posts match the keywords
  brands      a feed post naming one lands in "Your brands"; order also ranks stores in the UI
  stores      multi-brand retailers whose posts show only if they fit a section or are a store-wide sale
  shops       store readers to use; empty means all
  avoid       words that drop any item, checked first
"""
from stores import (CLOTHES, HAIR, JEANS, MAKEUP, PERFUME, SHOES, SKIN, TECH, UNDER)

DEPARTMENTS = {"women": "Women's", "men": "Men's", "all": "Everyone"}


def _for(dept, *phrases):
    """'{d} jeans' -> "women's jeans" / "men's jeans" / both, depending on the department."""
    prefixes = {"women": ["women's"], "men": ["men's"], "all": ["women's", "men's"]}[dept]
    return [p.replace("{d}", d) for p in phrases for d in (prefixes if "{d}" in p else [""])]


def category_keywords(name, dept):
    """Keywords that put a feed post (deal-site title) into this category."""
    women, men = dept in ("women", "all"), dept in ("men", "all")
    kw = {
        CLOTHES: _for(dept, "{d} sweater", "{d} jacket", "{d} coat", "{d} shirt", "{d} hoodie", "{d} pants",
                      "{d} clothing", "{d} apparel") + (["women's dress", "women's top"] if women else []),
        JEANS: _for(dept, "{d} jeans") + ["wide leg jeans", "straight leg jeans", "slim fit jeans", "levi's"],
        UNDER: (["bra", "bras", "bralette", "lingerie", "panties", "thong", "women's underwear"] if women else [])
               + (["boxer briefs", "boxers", "trunks", "men's underwear"] if men else []),
        PERFUME: ["perfume", "eau de parfum", "eau de toilette", "fragrance", "parfum", "body mist"]
                 + (["cologne"] if men else []),
        MAKEUP: ["makeup", "lipstick", "lip gloss", "lip oil", "lip tint", "mascara", "foundation", "concealer",
                 "blush", "bronzer", "setting spray", "brush set", "eyeshadow palette"],
        SKIN: ["skincare", "serum", "moisturizer", "sunscreen", "cleanser", "retinol", "face mask"],
        SHOES: _for(dept, "{d} boots", "{d} sneakers", "{d} shoes") + ["sneakers", "loafers", "ankle boots",
                                                                      "handbag", "purse", "crossbody", "backpack"],
        TECH: ["airpods", "earbuds", "headphones", "beats", "sony wh-1000xm5", "sony wh-1000xm6",
               "bose quietcomfort", "apple watch", "ipad", "kindle", "macbook"],
        HAIR: ["airwrap", "supersonic", "hair dryer", "flat iron", "flexstyle", "curling iron", "hair styler"],
    }
    return kw[name]


CATEGORIES = [CLOTHES, JEANS, UNDER, PERFUME, MAKEUP, SKIN, SHOES, TECH, HAIR]

# Words that hide the other department's items from deal-site posts.
DEPARTMENT_AVOID = {
    "women": ["men", "men's", "mens", "for men", "for him", "pour homme", "cologne", "boxer", "boxers",
              "boxer briefs", "trunks"],
    "men": ["women", "women's", "womens", "for women", "for her", "pour femme", "bra", "bralette", "lingerie",
            "dress", "skirt", "panties"],
    "all": [],
}
# "Hide kids', home and other off-topic deals" in setup.
COMMON_AVOID = ["kids", "kid's", "toddler", "baby", "boys", "girls'", "youth", "family",
                "gift card", "egift", "tv", "wall mount", "home", "household", "kitchen", "cookware", "bakeware",
                "bedding", "sheets", "towel", "towels", "furniture", "mattress", "vacuum", "rug", "decor",
                "curtain", "storage", "cleaning", "detergent", "paper towels", "toilet", "appliance",
                "air fryer", "blender", "coffee maker", "cigar", "drill", "tool kit", "lawn", "mower",
                "snow blower", "tire", "tires", "automotive", "fishing", "hunting", "dog", "cat litter", "pet",
                "grocery", "membership", "cruise", "golf", "ebook", "kindle ebook", "sweepstakes"]
# Multi-brand retailers whose deal-site posts are kept only when they fit a section or are store-wide sales.
RETAILERS = ["Amazon", "Walmart", "Target", "Best Buy", "Costco", "Macy's", "Nordstrom", "Sephora", "Ulta",
             "Kohl's", "Old Navy"]


def _words(xs):
    return [x.strip() for x in xs or [] if isinstance(x, str) and x.strip()]


def build_profile(answers):
    """Setup answers -> profile. Unknown or missing answers fall back to safe defaults."""
    dept = answers.get("department") if answers.get("department") in DEPARTMENTS else "all"
    chosen = [c for c in answers.get("categories") or [] if c in CATEGORIES]
    featured = answers.get("featured") or ""
    interests = [{"name": c, "keywords": category_keywords(c, dept), "focus": c == featured} for c in chosen]
    for custom in answers.get("custom") or []:
        name = (custom.get("name") or "").strip()
        if name and name not in chosen:
            interests.append({"name": name, "keywords": _words(custom.get("keywords")), "focus": name == featured})
    countdown = answers.get("countdown") or {}
    countdown = ({"label": countdown.get("label", "").strip() or "Countdown", "date": countdown["date"]}
                 if countdown.get("date") else None)
    return {
        "title": (answers.get("title") or "").strip() or "Deal Radar",
        "about": (answers.get("about") or "").strip(),
        "department": dept,
        "countdown": countdown,
        "brands": _words(answers.get("brands")),
        "stores": RETAILERS,
        "shops": _words(answers.get("shops")),
        "interests": interests,
        "avoid": DEPARTMENT_AVOID[dept] + (COMMON_AVOID if answers.get("hide_common", True) else [])
                 + _words(answers.get("avoid")),
        "setup": answers,
    }


# Built-in sale calendars a setup can load; events added in the UI are never touched.
# status: confirmed = announced by the retailer; expected = based on past years, not announced yet.
SALE_DATE_PRESETS = {
    "US Black Friday 2026": [
        ("Everyone", "Thanksgiving", "2026-11-26", "2026-11-26", "confirmed", "Many stores start Black Friday pricing online tonight or earlier.", ""),
        ("Everyone", "Black Friday", "2026-11-27", "2026-11-27", "confirmed", "", ""),
        ("Everyone", "Small Business Saturday", "2026-11-28", "2026-11-28", "confirmed", "", ""),
        ("Everyone", "Cyber Monday", "2026-11-30", "2026-11-30", "confirmed", "Last call for most sitewide codes.", ""),
        ("Sephora", "Holiday Savings Event", "2026-10-31", "2026-11-10", "expected",
         "Not announced. Past years ran about Nov 1-11, tiered by loyalty level.", "https://www.sephora.com/beauty/sephora-savings-event"),
        ("Apple", "Black Friday shopping event", "2026-11-27", "2026-11-30", "expected",
         "Not announced. Usually a gift card with purchase rather than a price cut.", "https://www.apple.com/shop/gifts/shopping-event"),
        ("Amazon", "Black Friday week", "2026-11-20", "2026-12-01", "expected",
         "Not announced. Dates are a guess from 2025.", "https://www.amazon.com/blackfriday"),
        ("Best Buy", "Early Black Friday doorbusters", "2026-11-06", "2026-11-18", "confirmed", "", "https://www.bestbuy.com/site/misc/black-friday/pcmcat225600050002.c"),
        ("Best Buy", "Black Friday sale", "2026-11-19", "2026-11-28", "confirmed", "", "https://www.bestbuy.com/site/misc/black-friday/pcmcat225600050002.c"),
        ("Best Buy", "Cyber Monday sale", "2026-11-29", "2026-11-30", "confirmed", "", ""),
    ],
}

# Example setup answers the UI offers as starting points.
PRESETS = {
    "Trend-loving twenty-something": {
        "title": "Deal Radar",
        "about": "Mid-20s, into trendy fashion, jeans, perfume, soft-glam makeup and wireless earbuds.",
        "department": "women",
        "categories": [CLOTHES, JEANS, UNDER, PERFUME, MAKEUP, SKIN, SHOES, TECH, HAIR],
        "shops": [],
        "brands": ["Zara", "H&M", "Uniqlo", "Aritzia", "Reformation", "Abercrombie", "Madewell", "Free People",
                   "Levi's", "Edikted", "Oh Polly", "Motel Rocks", "Steve Madden", "Skims", "Rare Beauty",
                   "Fenty Beauty", "Glossier", "Rhode", "Summer Fridays", "Sol de Janeiro"],
        "hide_common": True,
        "avoid": [],
        "countdown": {"label": "Black Friday", "date": "2026-11-27"},
        "sale_dates": "US Black Friday 2026",
    },
    "Gadget & self-care minimalist": {
        "title": "Deal Radar",
        "about": "Early 30s, buys one great thing over five okay ones: headphones and gadgets, simple skincare, "
                 "a signature scent, comfy basics and good sneakers.",
        "department": "all",
        "categories": [TECH, SKIN, PERFUME, CLOTHES, SHOES, HAIR],
        "custom": [{"name": "Fitness", "keywords": ["garmin", "fitbit", "smart scale", "yoga mat", "foam roller",
                                                    "running shoes", "massage gun"]}],
        "featured": TECH,
        "shops": ["Uniqlo", "Ulta", "Glossier", "Summer Fridays", "Rhode", "Dossier"],
        "brands": ["Apple", "Sony", "Bose", "Garmin", "Anker", "Dyson", "Uniqlo", "Everlane", "New Balance", "Hoka",
                   "Glossier", "Summer Fridays", "Rhode", "Dossier", "La Roche-Posay", "CeraVe"],
        "hide_common": True,
        "avoid": ["screen protector", "phone case"],
        "countdown": {"label": "Black Friday", "date": "2026-11-27"},
        "sale_dates": "US Black Friday 2026",
    },
}
