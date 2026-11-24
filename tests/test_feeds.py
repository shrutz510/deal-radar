import unittest

import feeds

DEALNEWS_XML = b"""<?xml version="1.0"?>
<rss xmlns:dn="https://www.dealnews.com/rss" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item>
  <title>Levi's Women's 501 Jeans for $39 + free shipping</title>
  <link>https://www.dealnews.com/x?ref=rss</link>
  <guid>123</guid>
  <description>&lt;p&gt;That's $30 off the $69 list price. Use code SAVE20 at checkout. Buy Now at Levi's&lt;/p&gt;</description>
  <dn:retailer>Levi's</dn:retailer>
  <dn:price>$39</dn:price>
  <dn:staffPick>true</dn:staffPick>
  <media:content url="https://img.example/jeans.jpg"/>
  <pubDate>Tue, 24 Nov 2026 10:00:00 GMT</pubDate>
</item>
</channel></rss>"""

BENS_XML = b"""<?xml version="1.0"?><rss><channel>
<item>
  <title>Sony WH-1000XM5 Headphones $248 at Best Buy</title>
  <link>https://bensbargains.com/deal/1#top</link>
  <guid>bb1</guid>
  <description>&lt;img src="//img.example/xm5.jpg"&gt; Best Buy has them for $298 - $50 off with coupon = $248</description>
  <pubDate>Tue, 24 Nov 2026 09:00:00 GMT</pubDate>
</item>
</channel></rss>"""


class PriceParsing(unittest.TestCase):
    def test_title_price_skips_shipping_and_spend_thresholds(self):
        self.assertEqual(feeds.title_price("Free shipping on $35+ orders: Socks $5"), 5)
        self.assertEqual(feeds.title_price("Jeans for $19.99 w/ $49 order"), 19.99)
        self.assertEqual(feeds.title_price("Extra $10 off $50: Sweater $25"), 25)
        self.assertIsNone(feeds.title_price("Sitewide sale, no prices here"))

    def test_original_price_patterns(self):
        self.assertEqual(feeds.find_orig_price("Shirt for $20, was $40", 20), 40)
        self.assertEqual(feeds.find_orig_price("$14 off the $35 regular price", 21), 35)
        self.assertEqual(feeds.find_orig_price("That's $18 off", 30), 48)
        self.assertIsNone(feeds.find_orig_price("$10 off orders of $50", 20))

    def test_percent(self):
        self.assertEqual(feeds.find_percent("Up to 60% off coats"), 60)
        self.assertIsNone(feeds.find_percent("Big sale"))


class FeedParsers(unittest.TestCase):
    def test_dealnews(self):
        [d] = feeds.parse_dealnews(DEALNEWS_XML)
        self.assertEqual(d["guid"], "dn-123")
        self.assertEqual(d["url"], "https://www.dealnews.com/x")
        self.assertEqual((d["price"], d["orig_price"], d["discount_pct"]), (39, 69, 43.5))
        self.assertEqual((d["retailer"], d["staff_pick"], d["coupon"]), ("Levi's", 1, "SAVE20"))
        self.assertEqual(d["image"], "https://img.example/jeans.jpg")
        self.assertNotIn("Buy Now", d["summary"])
        self.assertTrue(d["posted_at"].startswith("2026-11-24T10:00"))

    def test_bens(self):
        [d] = feeds.parse_bens(BENS_XML)
        self.assertEqual((d["price"], d["orig_price"], d["retailer"]), (248, 298, "Best Buy"))
        self.assertEqual(d["image"], "https://img.example/xm5.jpg")
        self.assertEqual(d["url"], "https://bensbargains.com/deal/1")


if __name__ == "__main__":
    unittest.main()
