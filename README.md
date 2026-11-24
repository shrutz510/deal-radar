# Deal Radar

A local Black Friday 2026 shopping tracker: sale and new-in items straight from the stores you like, a wishlist that watches prices, and sale dates. It runs on Python's standard library only, so there's nothing to install.

```bash
python3 server.py        # opens http://localhost:8787
```

## What it does
- **Shop the edit.** Products from store websites, sorted into sections (Clothes, Jeans, Undergarments, Perfume, Makeup, Earphones & tech, Skincare, Shoes & bags, Hair tools). Filter by section or store, search ("black dress", "wide leg"), show only items on sale, or pick **Surprise me** for a random mix. **Picked for me** takes turns between stores, favourite brands first, so one big sale can't fill the page.
- **Wishlist.** For each item you want, it shows the best price now, your dream price and how close it is, and the store's own price when you give a product link. It sends a macOS notification when something reaches your dream price.
- **Sale dates.** A countdown in the top bar, plus each retailer's sale window at the bottom of the page. Use **+ Add a date** to add your own; double-click one you added to delete it.
- **Theme.** The ◐ button cycles Auto (follows your Mac), Light and Dark, and remembers your choice.

## Sources
| Source | How |
|---|---|
| Zara, Massimo Dutti | zara.com's public category JSON: special prices (sale), new arrivals, best sellers, jeans, lingerie, perfume, makeup |
| Uniqlo | Uniqlo's public product search (newest women's items; markdowns show as deals) |
| Ulta | the sale page's product data |
| Oh Polly, Motel Rocks, Edikted, Steve Madden, Parade, Glossier, Fenty Beauty, Rare Beauty, Rhode, Kylie Cosmetics, Summer Fridays, Tower 28, Dossier | each Shopify store's public `/products.json` (everything on sale, plus the 10 newest full-price items) |
| DealNews, Ben's Bargains | RSS, for big-retailer deals on earphones, perfume and makeup |
| Product page (optional, per wishlist item) | Shopify product JSON, otherwise the page's schema.org price |

Stores that block automated requests (H&M, Aritzia, Reformation, Sephora, Levi's, Urban Outfitters, Free People, Madewell, Mango, COS, & Other Stories, Aerie, Macy's, J.Crew) are left out rather than worked around. Store readers live in `stores.py`; adding another Shopify brand is one line in `SHOPIFY`.

The app refreshes every 30 minutes while the server runs, with a short pause between requests. A store item disappears once the store stops listing it. Data is stored in `deals.db` (SQLite). Delete that file to start over.

## Profile
The app ships with two sample profiles; switch between them under **My profile → Start from a sample**, then tweak:
- **Trend-loving twenty-something**: fun fashion, jeans, perfume, makeup and earbuds, browsing every store.
- **Gadget & self-care minimalist**: headphones and gadgets, skincare, a signature scent, basics and sneakers, browsing only Uniqlo, Massimo Dutti and the beauty stores.

What you can edit:
- **Brands I love**: their order sets which stores come first in "Picked for me". Any DealNews or Ben's Bargains deal naming them shows.
- **Stores to browse**: which store websites' items show. Leave it empty to browse them all.
- **Big stores** (Sephora, Ulta, Macy's, Nordstrom): their deal posts only show if they fit a section or are a store-wide sale.
- **Sections**: store items show when the profile has a section with their name (Clothes, Jeans, Undergarments, Perfume, Makeup, Earphones & tech, Skincare, Shoes & bags, Hair tools); the keywords sort DealNews and Ben's Bargains posts. Tick ★ Featured to pin a section's best deals at the top.
- **Never show**: words that hide an item (men's, kids, home, …).

**Reset to default** brings back the first sample. Your profile and wishlist live only in your local `deals.db`.

## Wishlist query tips
- All words must appear in the item's name (the store name counts): `zara wide leg jeans`
- Exclude a word: `airpods -case`
- Exact phrase: `"wide leg"`
- Accessories (cases, chargers, "for iPhone"…) and used/refurb listings are kept out of "best price" automatically.

Edit `SEED_EVENTS` in `scraper.py` to change the built-in sale dates.
