# Deal Radar

A self-hosted deal finder you configure for yourself. On first run it asks what you shop for:
- who you're shopping for
- categories
- stores
- brands
- what to hide
- an optional countdown and sale calendar

It then builds the app from your answers: a feed of products and prices collected from retailer websites and deal feeds, a wishlist that tracks target prices, and a sale-date calendar.

- Python 3.9+ standard library only: no dependencies, no build step
- SQLite storage, a JSON API and a vanilla-JS front end
- Setup-driven: nothing about the user is hard-coded; profiles are data built from setup answers
- Pluggable store readers; adding a Shopify store is one line

## Quick start

```bash
git clone https://github.com/shrutz510/deal-radar.git
cd deal-radar
python3 server.py              # serves http://localhost:8787 and opens a browser
python3 server.py --no-browser
```

The first visit opens the setup screen. Answer the questions or start from a preset, then click **Build my deal finder**. The first refresh starts immediately and takes a minute or two. Nothing is fetched until setup is done.

To change your answers later, open **Preferences → Run setup again**. **Start over** clears them and reopens setup; the wishlist is kept. All data lives in `deals.db` next to the code; delete it for a completely fresh start.

## How it works

```
 setup answers ──build_profile()──> profile (meta table)
                                       │ department, shops
 store readers (stores.py) ─┐          ▼
 RSS feeds (scraper.py) ────┼─> upsert into deals ─> recompute wishlist matches ─> notify on target hits
 wishlist product pages ────┘            │
                                         ▼
           server.py: /api/state = deals filtered by the profile + wishlist + events + setup options
                                         │
                                         ▼
                            static/: index.html, app.js, styles.css
```

1. **Setup.** The UI posts the answers to `PUT /api/setup`. `profiles.build_profile()` turns them into a profile:
   - feed sections with keywords, adjusted for the department
   - the store list, brands and avoid words
   - the countdown

   The answers are stored on the profile under `setup`, so the form can reopen pre-filled. A chosen sale-date preset is loaded into `events`.
2. **Collect.** `scraper.run_scrape()` runs on a background scheduler (every 30 minutes by default) or on `POST /api/refresh`. It reads:
   - **RSS feeds** listed in `FEEDS`
   - **the store readers the profile selected**, for the profile's department
   - **wishlist product pages** that have a URL, using Shopify product JSON, then schema.org JSON-LD, then price meta tags
3. **Store.** Every item is upserted into `deals` by `guid`. Feed posts have `kind = 'post'`; store items have `kind = 'product'` and arrive pre-classified into a section.
4. **Match.** `recompute_matches()` matches every item against each wishlist query and records a daily lowest price per item. When a fresh match reaches its target price, `notify_new_hits()` sends a desktop notification (macOS `osascript`; a no-op elsewhere).
5. **Filter at read time.** `server.deals_view()` applies the profile on every `/api/state` call, so edits take effect without a re-scrape:
   - **Feed posts** are classified by `scraper.profile_section()`.
   - **Store products** show when the profile has a section of the same name and they come from a selected store.
   - Anything matching an `avoid` word is dropped.
6. **Expire.** A product not seen for `PRODUCT_STALE_H` hours is hidden, because the store stopped listing it. Feed posts stay for `FEED_DAYS`.

### Files

| File | What's in it |
|---|---|
| `profiles.py` | Setup → profile: category catalog and keywords, department rules, default avoid list, sale-date presets, example presets |
| `stores.py` | Store readers, store metadata (`STORE_INFO`) and the product classifier |
| `scraper.py` | DB schema and migrations, RSS parsers, price parsing, product-page price checks, wishlist matching, profile storage, `run_scrape()` |
| `server.py` | HTTP server, JSON API, feed and wishlist views, scoring, refresh queue and scheduler |
| `static/` | Single-page UI (setup screen, feed, wishlist, calendar), no framework |

## Customizing

### Setup answers
This is what the setup form sends, and what `PRESETS` entries look like:

```json
{
  "title": "Gift Hunter",
  "about": "optional note",
  "department": "women | men | all",
  "categories": ["Clothes", "Jeans", "Earphones & tech"],
  "custom": [{"name": "Board games", "keywords": ["board game", "catan"]}],
  "featured": "Earphones & tech",
  "shops": ["Zara", "Uniqlo"],
  "brands": ["Levi's", "Sony"],
  "hide_common": true,
  "avoid": ["phone case"],
  "countdown": {"label": "Dad's birthday", "date": "2026-12-12"},
  "sale_dates": "US Black Friday 2026"
}
```

| Answer | Effect |
|---|---|
| `categories` | Built-in categories from `profiles.CATEGORIES`. Each becomes a feed section with keywords from `category_keywords()`, which adjusts phrases like "women's jeans" to the department |
| `custom` | Your own sections, matched by keywords in deal-feed titles |
| `department` | Which side of each store the readers pull from (e.g. Zara's women's or men's lists), and words that hide the other side's posts |
| `shops` | Store readers to run. Empty means all. The form pre-selects stores whose `STORE_INFO` says they sell your categories for your department |
| `brands` | A feed post naming one shows under "Your brands"; the order also ranks stores in the default sort |
| `hide_common` / `avoid` | `COMMON_AVOID` (kids, home, auto…) plus your own words |
| `countdown` | Countdown shown in the top bar. Its date also sets the "same time last year" window used for wishlist price history |
| `sale_dates` | Name of an entry in `SALE_DATE_PRESETS` to load into the calendar. Events added by hand are kept |

To offer more starting points, add entries to `PRESETS`. To add a built-in category:
1. add it to `stores.SECTIONS` and `CLASSIFY`, so store products can land in it
2. add it to `profiles.CATEGORIES` and `category_keywords()`, so feed posts can

**Preferences** in the UI edits the generated profile directly: sections, keywords, brands, retailers, stores and avoid words.

### Store readers
A reader is `read(fetch, ts, pause, dept) -> list[dict]`. `dept` is `"women"`, `"men"` or `"all"`; read only the matching parts of the store. Build each item with `stores.product(store, id, title, url, image, price, regular_price, section, ts)`. Then:
- register the reader in `readers()`
- describe the store in `STORE_INFO` (`sells`: sections, `for`: `"women"`, `"men"` or `"all"`), so setup can suggest it

Ways to add a store:
- **Shopify stores:** add `(name, domain, fallback_section)` to `SHOPIFY` and a `STORE_INFO` entry. The generic reader takes every on-sale product from `/products.json`, plus the `NEW_PER_STORE` newest full-price ones, and drops items tagged for the other department.
- **Other stores:** look for a public JSON endpoint the site's own pages use (see `read_zara`, `read_uniqlo`), or structured data embedded in the HTML (see `read_ulta`).
- **Classification:** `classify(text, fallback)` sorts a product into a section by regex on its name and type. The first match in `CLASSIFY` wins.

Readers use only public, unauthenticated endpoints with the honest `USER_AGENT`. When a store answers 403 or 429, the refresh records it in the status shown in the UI and moves on. 429s get one retry after `Retry-After`, capped at 15 seconds. Don't add header spoofing or other workarounds. Some stores block automated clients entirely, and Shopify may refuse non-browser clients for a while.

### Feeds
`FEEDS` in `scraper.py` maps a source name to an RSS URL, with a parser in `PARSERS`. Each parser returns dicts in the shape `finish()` produces. Helpers handle the messy parts of deal titles:
- `title_price()` skips shipping and spend thresholds
- `find_orig_price()` finds the original price
- `find_percent()` finds the discount

### Sale-date presets
`SALE_DATE_PRESETS` in `profiles.py` maps a name to a list of `(retailer, name, start, end, status, note, url)` rows, where `status` is `confirmed` or `expected`. Use the retailer `Everyone` for days that apply to every store; they're highlighted in the calendar. Users can also add their own dates in the UI.

### Tuning knobs

| Constant | Where | Default |
|---|---|---|
| `PORT` | server.py | 8787 |
| `REFRESH_EVERY_S` | server.py | 30 min |
| `FEED_DAYS` | server.py | 14 (how long feed posts stay visible) |
| `PRODUCT_STALE_H` | server.py | 26 (hours before an unseen product is hidden) |
| `REQUEST_GAP_S` / `STORE_GAP_S` | scraper.py | 1.5 s / 5 s between requests and between stores |
| `NEW_PER_STORE` | stores.py | 10 full-price items per Shopify store |
| `UNIQLO_KEEP` | stores.py | 40 newest items per department |
| `PAGE` | static/app.js | 24 items per "Show more" |

Scoring (`server.deal_score`) weights the discount, community votes (feeds only) and freshness. The UI's default sort takes turns between stores, so one big sale can't fill the page.

## API

All JSON. The server binds to `127.0.0.1` only.

| Method | Path | Body / notes |
|---|---|---|
| GET | `/api/state` | Everything the UI needs: profile (or `needs_setup: true`), setup options (departments, categories, stores, presets, sale-date presets), events, wishlist with matches and price history, filtered deals, refresh status |
| PUT | `/api/setup` | Setup answers (see above): builds and saves the profile, loads sale dates, starts a refresh |
| PUT | `/api/profile` | Edits to the generated profile (`about`, `brands`, `stores`, `shops`, `interests`, `avoid`); other fields are kept |
| PUT | `/api/profile/reset` | Clears the profile, so the UI shows setup again |
| POST | `/api/refresh` | Queue a full refresh |
| POST | `/api/wishlist` | `{query, target_price?, priority?, note?, product_url?}`; matched against stored items and its product page checked right away |
| PUT | `/api/wishlist/<id>` | `{target_price?, note?, priority?}` |
| DELETE | `/api/wishlist/<id>` | |
| POST | `/api/events` | `{retailer, name, start, end?, note?, url?}` |
| DELETE | `/api/events/<id>` | Deletes any event (the UI only offers it for events added by hand) |

## Wishlist queries
- Every word must appear in the item name. For store products, the store name counts as part of the name: `uniqlo wide leg jeans`
- `-word` excludes: `airpods -case`
- `"quoted phrase"` matches exactly
- Accessories (`NOISE_WORDS`) and used/refurbished listings (`USED_RE`) never count as the best price

## Data model
SQLite tables, created and migrated in `scraper.connect()`:

| Table | Holds |
|---|---|
| `deals` | Every collected item (feed post or store product): price, original price, discount, image, timestamps |
| `wishlist` | Wishlist items, plus the latest product-page price check |
| `wish_matches` | Which items matched which wishlist entry, and whether a notification went out |
| `price_points` | Daily lowest price per wishlist item |
| `events` | Sale dates (from a preset or added by hand) |
| `meta` | Profile (with its setup answers) and refresh status |
