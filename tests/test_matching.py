import unittest

import profiles
import stores
import wishlist


class WishlistQueries(unittest.TestCase):
    def test_terms(self):
        self.assertEqual(wishlist.query_terms('airpods pro -case "usb c"'), (["airpods", "pro", "usb c"], ["case"]))

    def test_matches(self):
        self.assertTrue(wishlist.matches("Apple AirPods Pro 3", "airpods pro 3"))
        self.assertFalse(wishlist.matches("Apple AirPods Pro 3", "airpods pro 3 -apple"))
        self.assertFalse(wishlist.matches("Silicone Case for AirPods Pro 3", "airpods pro 3"))   # accessory
        self.assertTrue(wishlist.matches("AirPods Pro 3 with MagSafe Charging Case", "airpods pro 3"))
        self.assertTrue(wishlist.matches("Zara Wide Leg Jeans", "zara wide leg"))

    def test_used(self):
        self.assertTrue(wishlist.is_used("Refurbished AirPods"))
        self.assertFalse(wishlist.is_used("AirPods Pro 3"))


class Stores(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(stores.classify("High Rise Straight Jeans", stores.CLOTHES), stores.JEANS)
        self.assertEqual(stores.classify("Lace Bralette", stores.CLOTHES), stores.UNDER)
        self.assertEqual(stores.classify("Red Vanilla EDP 100ml", stores.CLOTHES), stores.PERFUME)
        self.assertEqual(stores.classify("Cropped Cardigan", stores.CLOTHES), stores.CLOTHES)

    def test_product(self):
        p = stores.product("Zara", "1", "RUFFLE BLOUSE", "https://x", None, 29.94, 49.9, stores.CLOTHES, "2026-11-24")
        self.assertEqual((p["title"], p["kind"], p["guid"]), ("Ruffle Blouse", "product", "Zara:1"))
        self.assertEqual((p["orig_price"], p["discount_pct"]), (49.9, 40.0))
        full = stores.product("Zara", "2", "Tee", "https://x", None, 20, 20, stores.CLOTHES, "2026-11-24")
        self.assertIsNone(full["orig_price"])

    def test_zara_sale_list_found_by_pattern(self):
        ids = {("MAN", "COLLECTION", "SELECTED ITEMS 40% OFF", "VIEW ALL"): 7, ("MAN", "COLLECTION", "JEANS", "VIEW ALL"): 8}
        self.assertEqual(stores._zara_find(ids, ("MAN", "COLLECTION", stores.SALE, "VIEW ALL")), 7)

    def test_store_info_covers_every_reader(self):
        names = {n for _, emits, _ in stores.readers() for n in emits}
        self.assertEqual(names, set(stores.STORE_INFO))


class Profiles(unittest.TestCase):
    def test_build_profile(self):
        p = profiles.build_profile({
            "department": "men", "categories": ["Jeans", "Nope"], "featured": "Board games",
            "custom": [{"name": "Board games", "keywords": ["catan"]}], "brands": [" Sony ", ""],
            "countdown": {"label": "", "date": "2026-12-12"}, "avoid": ["phone case"]})
        self.assertEqual([i["name"] for i in p["interests"]], ["Jeans", "Board games"])
        self.assertIn("men's jeans", p["interests"][0]["keywords"])
        self.assertNotIn("women's jeans", p["interests"][0]["keywords"])
        self.assertTrue(p["interests"][1]["focus"])
        self.assertEqual(p["brands"], ["Sony"])
        self.assertEqual(p["countdown"], {"label": "Countdown", "date": "2026-12-12"})
        self.assertIn("women's", p["avoid"])        # the other department's words
        self.assertIn("kids", p["avoid"])           # hide_common defaults on
        self.assertIn("phone case", p["avoid"])
        self.assertEqual(p["title"], "Deal Radar")

    def test_presets_build(self):
        for name, answers in profiles.PRESETS.items():
            with self.subTest(name):
                self.assertTrue(profiles.build_profile(answers)["interests"])
            self.assertIn(answers.get("sale_dates", ""), list(profiles.SALE_DATE_PRESETS) + [""])

    def test_section_for(self):
        p = profiles.build_profile({"department": "women", "categories": ["Jeans", "Earphones & tech"],
                                    "shops": ["Zara"], "brands": ["Uniqlo"]})
        product = {"kind": "product", "title": "Wide Leg Jeans", "category": "Jeans", "retailer": "Zara"}
        self.assertEqual(profiles.section_for(p, product), "Jeans")
        self.assertIsNone(profiles.section_for(p, {**product, "retailer": "Uniqlo"}))     # store not chosen
        self.assertIsNone(profiles.section_for(p, {**product, "category": "Makeup"}))      # section not chosen
        self.assertIsNone(profiles.section_for(p, {**product, "title": "Men's Wide Leg Jeans"}))  # avoided

        post = {"kind": "post", "title": "Apple AirPods Pro 3 for $199", "category": None, "retailer": "Amazon"}
        self.assertEqual(profiles.section_for(p, post), "Earphones & tech")
        self.assertEqual(profiles.section_for(p, {**post, "title": "Uniqlo cashmere for $50"}), "Your brands")
        self.assertEqual(profiles.section_for(p, {**post, "title": "Target sitewide sale: 30% off"}), "Store sales")
        self.assertIsNone(profiles.section_for(p, {**post, "title": "Kitchen blender $30"}))


if __name__ == "__main__":
    unittest.main()
