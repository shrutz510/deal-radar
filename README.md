# Deal Radar

A self-hosted deal finder. It collects products and prices from retailer websites and deal feeds on a schedule, filters them through a configurable profile, tracks wishlist items against target prices, and serves everything through a small web UI.

- Python 3.9+ standard library only: no dependencies, no build step
- SQLite storage, a JSON API and a vanilla-JS front end
- Pluggable store readers; adding a Shopify store is one line

Out of the box it's set up for the 2026 Black Friday season, with two sample shopping profiles. Everything about what it looks for is data you can change.

## Quick start

```bash
git clone https://github.com/shrutz510/deal-radar.git
cd deal-radar
python3 server.py              # serves http://localhost:8787 and opens a browser
python3 server.py --no-browser
python3 scraper.py             # one refresh from the command line, no server
```

The first refresh starts right away and takes a couple of minutes. Data lands in `deals.db` next to the code; delete it to start over.

## How it works

```
 store readers (stores.py) ─┐
 RSS feeds (scraper.py) ────┼─> upsert into deals ─> recompute wishlist matches ─> notify on target hits
 wishlist product pages ────┘            │
                                         ▼
                 server.py: /api/state = deals filtered by the active profile + wishlist + events
                                         │
                                         ▼
                            static/: index.html, app.js, styles.css
```

1. **Collect.** `scraper.run_scrape()` runs on a background scheduler (every 30 minutes by default) or on `POST /api/refresh`. It reads:
   - **RSS feeds** listed in `FEEDS` (currently DealNews and Ben's Bargains)
   - **every store reader** from `stores.readers()`
   - **wishlist product pages** that have a URL, using Shopify product JSON, then schema.org JSON-LD, then price meta tags
2. **Store.** Every item is upserted into the `deals` table by `guid`. Feed posts have `kind = 'post'`; store items have `kind = 'product'` and arrive with a section already assigned.
3. **Match.** `recompute_matches()` matches every item against each wishlist query and records a daily lowest price per item. When a fresh match reaches its target price, `notify_new_hits()` sends a desktop notification (macOS `osascript`; a no-op elsewhere).
4. **Filter at read time.** `server.deals_view()` applies the active profile on every `/api/state` call, so profile edits take effect immediately without a re-scrape:
   - **Feed posts** are classified by `scraper.profile_section()`.
   - **Store products** show when the profile has a section with their name and, if `shops` is set, they come from one of those stores.
   - Anything matching an `avoid` word is dropped.
5. **Expire.** A product not seen for `PRODUCT_STALE_H` hours is hidden, because the store stopped listing it. Feed posts are shown for `FEED_DAYS`.

### Files

| File | What's in it |
|---|---|
| `server.py` | HTTP server (`ThreadingHTTPServer`), JSON API, feed/wishlist views, scoring, refresh queue and scheduler |
| `scraper.py` | DB schema and migrations, RSS parsers, price parsing, product-page price checks, wishlist matching, profiles, sale-date seeds, `run_scrape()` |
| `stores.py` | Store readers and the product classifier |
| `static/` | Single-page UI, no framework |

## Configuration

### Profiles
A profile is plain data, editable in the UI (**My profile**) and stored as JSON in the `meta` table. Starting points live in `SAMPLE_PROFILES` in `scraper.py`; the first one is the default, and the UI lists all of them under **Start from a sample**.

| Field | Effect |
|---|---|
| `about` | Free text shown in the UI |
| `interests` | The feed's sections: `{name, keywords, focus}`. Store products land in the section with the matching name (see `stores.CLASSIFY`). Feed posts go to the first section whose keywords appear in the title (whole-word match). `focus: true` pins that section's best deals in a row at the top |
| `brands` | A feed post naming one of these shows under "Your brands". The list order also ranks stores in the default sort |
| `stores` | Multi-brand retailers: their posts show only if they fit a section or read as a store-wide sale (`STORE_SALE_RX`) |
| `shops` | Store readers whose products to show; empty means all of them |
| `avoid` | Words that drop any item, checked first |

To ship a different audience (a home cook, a runner, a gamer), add an entry to `SAMPLE_PROFILES`. If it needs product categories that don't exist yet, add them to `stores.CLASSIFY` too.

### Store readers
A reader is `read(fetch, ts, pause) -> list[dict]`. Build each item with `stores.product(store, id, title, url, image, price, regular_price, section, ts)`. Then register it in `readers()` and add its name(s) to `STORE_NAMES`.

- **Shopify stores:** add `(name, domain, fallback_section)` to `SHOPIFY`. The generic reader takes every on-sale product from `/products.json`, plus the `NEW_PER_STORE` newest full-price ones.
- **Other stores:** look for a public JSON endpoint the site's own pages use (see `read_zara`, `read_uniqlo`), or structured data embedded in the HTML (see `read_ulta`).
- **Classification:** `classify(text, fallback)` sorts a product into a section by regex on its name and type. The first match in `CLASSIFY` wins, so specific kinds come before catch-alls.

Readers use only public, unauthenticated endpoints with the honest `USER_AGENT`. When a store answers 403 or 429, the refresh records it in the status shown in the UI and moves on. 429s get one retry after `Retry-After`, capped at 15 seconds. Don't add header spoofing or other workarounds. Some stores block automated clients entirely (H&M, Sephora and Aritzia, among others). Shopify may also refuse non-browser clients for a while.

### Feeds
`FEEDS` in `scraper.py` maps a source name to an RSS URL, with a parser in `PARSERS`. Each parser returns dicts in the shape `finish()` produces. Helpers handle the messy parts of deal titles:
- `title_price()` skips shipping and spend thresholds
- `find_orig_price()` finds the original price
- `find_percent()` finds the discount

### Sale dates
`SEED_EVENTS` in `scraper.py` holds built-in retailer events: `(retailer, name, start, end, status, note, url)`, where `status` is `confirmed` or `expected`. After editing it, bump `EVENTS_VERSION`; built-in events are then replaced on next start, and ones added through the UI are kept. The countdown dates are `BLACK_FRIDAY` and `CYBER_MONDAY` at the top of `static/app.js`. Last season's price window is `LAST_BF_WINDOW` in `server.py`.

### Tuning knobs

| Constant | Where | Default |
|---|---|---|
| `PORT` | server.py | 8787 |
| `REFRESH_EVERY_S` | server.py | 30 min |
| `FEED_DAYS` | server.py | 14 (how long feed posts stay visible) |
| `PRODUCT_STALE_H` | server.py | 26 (hours before an unseen product is hidden) |
| `REQUEST_GAP_S` / `STORE_GAP_S` | scraper.py | 1.5 s / 5 s between requests and between stores |
| `NEW_PER_STORE` | stores.py | 10 full-price items per Shopify store |
| `PAGE` | static/app.js | 24 items per "Show more" |

Scoring (`server.deal_score`) weights the discount, community votes (feeds only) and freshness. The UI's default sort takes turns between stores, so one big sale can't fill the page.

## API

All JSON. The server binds to `127.0.0.1` only.

| Method | Path | Body / notes |
|---|---|---|
| GET | `/api/state` | Everything the UI needs: profile, sample names, store names, events, wishlist (with matches and price history), filtered deals, refresh status |
| POST | `/api/refresh` | Queue a full refresh |
| POST | `/api/wishlist` | `{query, target_price?, priority?, note?, product_url?}`; matched against stored items and its product page checked right away |
| PUT | `/api/wishlist/<id>` | `{target_price?, note?, priority?}` |
| DELETE | `/api/wishlist/<id>` | |
| POST | `/api/events` | `{retailer, name, start, end?, note?, url?}` |
| DELETE | `/api/events/<id>` | Deletes any event (the UI only offers it for events added through the API) |
| PUT | `/api/profile` | Full profile object (see above); triggers a refresh |
| PUT | `/api/profile/sample` | `{name}`: replace the profile with a sample |
| PUT | `/api/profile/reset` | Back to the default sample |

## Wishlist queries
- Every word must appear in the item name. For store products, the store name counts as part of the name: `zara wide leg jeans`
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
| `events` | Sale dates |
| `meta` | Active profile, refresh status, schema/seed versions |
