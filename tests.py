"""
tests.py — the system's permanent memory of its own mistakes.

Every case here exists because something REAL went wrong in the feed and got
fixed. This file is the compound-interest mechanism: a bug fixed without a
test here can silently come back; a bug encoded here can never return without
this suite screaming. Pair each test with its entry in LESSONS.md.

Run:  E:\python.exe tests.py     (offline — no network, no Discord, no FB)
"""
import sys
import unittest

import scraper
import tcg_price
from fb_feed import parse_price, parse_end_time, parse_auction


class TestClassify(unittest.TestCase):
    """Category color-coding (7/15: 'divide feed by categories')."""

    def test_graded(self):
        self.assertEqual(scraper.classify("PSA 10 Charizard slab")[0], "graded")

    def test_sealed(self):
        self.assertEqual(scraper.classify("Booster box 151 sealed")[0], "sealed")

    def test_generic_bundle_is_bulk_not_sealed(self):
        # 7/15 live catch: in PH selling, a generic 'bundle' is a card lot;
        # only 'booster bundle' is sealed product.
        self.assertEqual(scraper.classify("Pokemon card bundle sale")[0], "bulk")
        self.assertEqual(scraper.classify("Booster bundle SV 151")[0], "sealed")

    def test_collection(self):
        self.assertEqual(scraper.classify("Pokemon binder collection sale")[0],
                         "collection")

    def test_single_default(self):
        self.assertEqual(scraper.classify("Charizard ex 006/165")[0], "single")


class TestMerchFilter(unittest.TestCase):
    """TCG-only feed (7/15: 'my target is only TCG pokemon cards')."""

    def test_plush_dropped(self):
        self.assertTrue(scraper.is_merch("Pokemon plush pikachu 12 inch"))

    def test_pokemon_go_dropped(self):
        # the 'PC FUKOUKA BG Pokemon GO ₱100' leak
        self.assertTrue(scraper.is_merch("Pokemon GO account lvl 40"))

    def test_painting_dropped(self):
        # the 'PAINTING FOR AUCTION' leak — art of a Pokémon is not a card
        self.assertTrue(scraper.is_merch("Pokemon painting for auction, acrylic"))

    def test_card_signal_keeps_it(self):
        # 'plush' in text but an actual card number present -> keep
        self.assertFalse(scraper.is_merch("Pikachu plush pattern card 025/165 TCG"))


class TestAuctionVsDistress(unittest.TestCase):
    """The clickbait lessons (7/15, Yujin's business logic)."""

    def test_steal_is_auction_mechanic_not_distress(self):
        # 'DIBS/Steal/Buy Out' is a claim-sale mechanic in PH TCG; 'steal'
        # falsely @everyone-pinged until 9b9df3d.
        self.assertTrue(scraper.is_auction("DIBS / STEAL / BUYOUT tonight"))
        self.assertEqual(scraper.distress_terms("steal price!"), [])

    def test_marketing_claims_are_not_distress(self):
        # 'below market 90-95%' is CLICKBAIT, not a snipe (905c61e)
        for bait in ["below market!", "mura na", "dirt cheap",
                     "giveaway price", "priced to sell"]:
            self.assertEqual(scraper.distress_terms(bait), [], bait)

    def test_real_seller_situation_is_distress(self):
        self.assertTrue(scraper.distress_terms("rush sale, quitting the hobby"))

    def test_dib_key_are_auctions(self):
        self.assertTrue(scraper.is_auction("KEY SALE! leave a dot"))
        self.assertTrue(scraper.is_auction("dib sale starts 8pm"))


class TestMetaAndDeadend(unittest.TestCase):
    """'not a snipe! this is just a post' (7e16191)."""

    def test_rules_post_skipped(self):
        self.assertTrue(scraper.is_meta("GROUP RULES: VIOLATORS will be banned"))

    def test_wtb_skipped(self):
        self.assertTrue(scraper.is_meta("WTB: looking for moonbreon, budget 5k"))


class TestParsePrice(unittest.TestCase):
    """Price parsing traps (all real leaks)."""

    def test_k_notation(self):
        self.assertEqual(parse_price("selling at 2.5k firm"), 2500)

    def test_days_is_not_a_price(self):
        # '60 days' was read as ₱60
        self.assertIsNone(parse_price("lay-away up to 60 days"))

    def test_percent_is_not_a_price(self):
        # '70%' was read as ₱70
        self.assertIsNone(parse_price("all cards 70% off retail-ish deals only"))

    def test_currency_marked(self):
        self.assertEqual(parse_price("P1,500 only"), 1500)


class TestParseEndTime(unittest.TestCase):
    """Auction end-time traps."""

    def test_absolute_date_with_filler(self):
        # 'End: July 15, 2026 (Wednesday 9:00 PM)' — filler between date and
        # time broke parsing until d3c7e5d
        self.assertIsNotNone(
            parse_end_time("End: July 15, 2026 (Wednesday 9:00 PM)"))

    def test_absolute_datetime(self):
        self.assertIsNotNone(
            parse_end_time("End: July 17, 2026 6:30:59PM"))


class TestParseAuction(unittest.TestCase):
    def test_sb_not_confused_with_end_time(self):
        # 'SB 50 ... 6:30PM' once showed ₱30 as the price (9c232a9)
        a = parse_auction("SB: 50 pesos, ends 6:30PM, inc 10")
        self.assertEqual(a.get("start_bid"), 50)


class TestTcgMatching(unittest.TestCase):
    """The Mega-promo lesson (1c8bd4b, 7/15): never conclude 'data gap' from
    one query phrasing; match promo numbers in FULL."""

    def test_extract(self):
        name, num = tcg_price._extract("Pokemon Card Mega Camerupt Full art XY198a")
        self.assertEqual(name, "Mega Camerupt")
        self.assertEqual(num, "XY198a")

    def test_mega_name_variants(self):
        # TCGplayer stores XY Mega promos as 'M <Name> EX', not 'Mega <Name>'
        v = tcg_price._name_variants("Mega Beedrill")
        self.assertIn("M Beedrill EX", v)
        self.assertEqual(v[0], "Mega Beedrill")  # original tried first

    def test_promo_number_exact(self):
        # XY198a (Alt-Art $27) must NOT match XY198 (Jumbo $11)
        self.assertTrue(tcg_price._num_ok("XY198a", "XY198a", "198"))
        self.assertFalse(tcg_price._num_ok("XY198", "XY198a", "198"))
        self.assertFalse(tcg_price._num_ok("XY158", "XY198a", "198"))

    def test_slash_number_lead_match(self):
        self.assertTrue(tcg_price._num_ok("077/063", "077/063", "77"))

    def test_grade_skipped(self):
        # graded slabs must never get a raw-card price
        self.assertEqual(tcg_price.market_value("PSA 9 Charizard 4/102"),
                         (None, None))


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    n = result.testsRun
    bad = len(result.failures) + len(result.errors)
    print(f"\n{'PASS' if bad == 0 else 'FAIL'}: {n - bad}/{n} lessons hold")
    sys.exit(1 if bad else 0)
