"""
tests.py — the system's permanent memory of its own mistakes.

Every case here exists because something REAL went wrong in the feed and got
fixed. This file is the compound-interest mechanism: a bug fixed without a
test here can silently come back; a bug encoded here can never return without
this suite screaming. Pair each test with its entry in LESSONS.md.

Run:  E:\python.exe tests.py     (offline — no network, no Discord, no FB)
"""
import os
import sys
import unittest

import pc_price
import scraper
import tcg_price
import valuator
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


class TestPriceChartingPrecision(unittest.TestCase):
    """Two live @everyone false snipes (2026-07-16 screenshots): a toy
    Lucario priced as a P22k booster box, plushies priced at P846 —
    both from generic-token matching."""

    BOX = [("Pokemon Booster Box", "Pokemon Sealed", "380.00")]

    def test_toy_with_box_never_matches_booster_box(self):
        t = "FS pokemon with box na 200 nalang, sagot ko na bubble wrap"
        self.assertIsNone(pc_price._pick(self.BOX, t))

    def test_plush_sale_title_matches_nothing(self):
        rows = [("Pikachu", "Pokemon Promo", "5.00")] + self.BOX
        self.assertIsNone(pc_price._pick(rows, "Paubos Sale!! Price starts at 250!!"))

    def test_combee_never_gets_combusken_price(self):
        # the original dup-mismatch: overlap lived in the console text
        rows = [("Combusken #65", "Pokemon Meiji Promo", "3.95")]
        self.assertIsNone(
            pc_price._pick(rows, "Pokemon Card Combee 081/DP-P Vintage Meiji"))

    def test_real_card_still_matches(self):
        rows = [("Staraptor #26", "Pokemon Japanese Diamond & Pearl", "5.58")]
        best = pc_price._pick(rows, "Pokemon Card Staraptor Holo Japanese D&P")
        self.assertIsNotNone(best)
        self.assertEqual(best[0], "Staraptor #26")


class TestValuator(unittest.TestCase):
    """Card valuator (V0.5): OCR-guess + velocity confidence (L16)."""

    def test_guess_query_from_real_ocr(self):
        # actual Windows-OCR output from the Magcargo GX scan
        lines = ["Magcargo", "STAGEI", "Evolves from Slugma",
                 "Crushing Charge", "Ability", "Hp2100"]
        name, number = valuator.guess_query(lines)
        self.assertEqual(name, "Magcargo")
        self.assertIsNone(number)

    def test_guess_query_reads_number(self):
        name, number = valuator.guess_query(["Charizard", "006/165"])
        self.assertEqual(number, "006/165")

    def test_body_text_never_becomes_the_name(self):
        name, _ = valuator.guess_query(
            ["Evolves from Slugma", "Discard the top card", "Pikachu"])
        self.assertEqual(name, "Pikachu")

    def test_item_card_named_with_noise_word(self):
        # live catch (Yujin's screenshot): "Weakness Policy" is a real ITEM
        # card name, but "weakness" was on the body-noise list -> rejected
        name, number = valuator.guess_query(["Weakness Policy", "164/160"])
        self.assertEqual(name, "Weakness Policy")
        self.assertEqual(number, "164/160")

    def test_japanese_card_via_setcode(self):
        # live catch (Reshiram & Charizard GX JP): OCR can't read Japanese
        # names — but the Latin footer "sm12a … 016/173" uniquely IDs the
        # card on TCGplayer. Footer/mechanic/copyright lines must never
        # become the name; setcode+number is the query.
        name, number = valuator.guess_query(
            ["TAG TEAM", "HP270", "sm12a c 016/173 RR", "2019 Pokemon"])
        self.assertEqual(name, "sm12a")
        self.assertEqual(number, "016/173")

    def test_mechanic_labels_never_the_name(self):
        # "TAG TEAM" alone must not become the search ("TEAM" -> Rocket tins)
        name, _ = valuator.guess_query(["TAG TEAM", "GX"])
        self.assertEqual(name, "")

    def test_gibberish_ocr_never_becomes_the_query(self):
        # live catch: JP name OCR'd as "li&DhJ" -> searched as-is -> dead end.
        # Junk reads must be rejected so the footer/manual path can take over.
        self.assertTrue(valuator._is_junk("li&DhJ"))
        # each of these shipped a live dead-end before being caught:
        self.assertTrue(valuator._is_junk("y- JV .M GX"))   # short fragments
        self.assertTrue(valuator._is_junk("ooo"))           # energy symbols
        self.assertTrue(valuator._is_junk("IBO"))           # all-caps junk
        self.assertTrue(valuator._is_junk("YEjj"))          # impossible case
        self.assertFalse(valuator._is_junk("Weakness Policy"))
        self.assertFalse(valuator._is_junk("McDonalds Pikachu"))
        self.assertFalse(valuator._is_junk("Mew ex"))
        name, _ = valuator.guess_query(["li&DhJ", "TAG TEAM", "HP270"])
        self.assertEqual(name, "")

    def test_attack_fingerprint_identifies_jp_card(self):
        # THE identification path (Yujin: "identification is the most
        # important part"): JP name unreadable, but damages 30+/230/200+
        # match exactly ONE card in the whole game.
        if not os.path.exists(valuator.FP_DB):
            self.skipTest("fingerprint index not built")
        names = valuator.fingerprint_names(
            ["TEAM", "li&DhJ", "30+", "230", "+ 200+", "TAG TEAM"])
        self.assertEqual(names, ["Reshiram & Charizard-GX"])

    def test_manectric_fingerprint_from_real_lines(self):
        # his 8PM catch: '130??' (body prose) + unlabeled HP 330 = TWO
        # phantoms; standalone damages must be PURELY number+modifier
        lines = ["330", "120", "200+", "130??", "???", "ex?",
                 "llusSbanGraplhites", "077/063SR"]
        if not os.path.exists(valuator.FP_DB):
            self.skipTest("fingerprint index not built")
        d, hp, _ = valuator._extract_damages(lines)
        self.assertEqual(sorted(d), ["120", "200+", "330"])  # 130?? rejected
        self.assertEqual(valuator.fingerprint_names(lines), ["Mega Manectric ex"])

    def test_snap_number_layer_b(self):
        # HIS CATCH: 016/173 read as 015/173 at 810px -> Kartana. The number
        # must be a real printing of the identified card; snap 1-digit errors.
        printings = ["016/173", "220/173", "096/095", "097/095", "20/214"]
        self.assertEqual(valuator.snap_number("015/173", printings), "016/173")
        self.assertEqual(valuator.snap_number("016/173", printings), "016/173")
        # ambiguous (two printings both 1 edit away) -> no guess
        self.assertIsNone(valuator.snap_number("098/095", ["096/095", "099/095"]))
        # nothing close -> no guess
        self.assertIsNone(valuator.snap_number("555/555", printings))

    def test_close_only_pruning(self):
        # number pinned -> Jumbos and far-numbered variants are noise
        mk = lambda num, set_: {"number": num, "set": set_}
        cands = [mk("016/173", "SM12a: Tag All Stars"),
                 mk("220/173", "SM12a: Tag All Stars"),
                 mk("SM201", "Jumbo Cards"),
                 mk("097/095", "SM10: Double Blaze")]
        out = valuator._close_only(cands, "16/173")
        self.assertEqual([c["number"] for c in out], ["016/173"])
        # no number -> keep everything except Jumbos
        out2 = valuator._close_only(cands, None)
        self.assertNotIn("SM201", [c["number"] for c in out2])
        # nothing close -> honest fallback to the full (non-jumbo) list
        out3 = valuator._close_only(cands, "555/555")
        self.assertEqual(len(out3), 3)

    def test_confidence_thresholds(self):
        # L16: a price with almost no sales is a rumor, not a market
        self.assertEqual(valuator._confidence(2, 30)[0], "LOW")     # <3 sales
        self.assertEqual(valuator._confidence(25, 20)[0], "HIGH")   # >0.5/day
        self.assertEqual(valuator._confidence(5, 14)[0], "MED")
        self.assertEqual(valuator._confidence(3, 300)[0], "LOW")    # thin


class ValuatorLayerCD(unittest.TestCase):
    """V0.7 layers, born from the 20-listing dataset run (L21-L25):
    name vocabulary snap (C), dex number (D), fingerprint ambiguity guard,
    watermark rejection, promo footers, two-line TAG TEAM names."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(valuator.FP_DB):
            raise unittest.SkipTest("fingerprint index not built")

    def test_layer_c_snaps_ocr_misreads(self):
        # live catches: glued/chopped OCR reads snap to REAL card names
        self.assertEqual(valuator.snap_name("Pikachue"), "Pikachu")
        self.assertEqual(valuator.snap_name("Pikachuex"), "Pikachu ex")
        self.assertEqual(valuator.snap_name("arizardex"), "Charizard")
        self.assertEqual(valuator.snap_name("MCameruptEX"), "M Camerupt-EX")
        self.assertEqual(valuator.snap_name("MTyranitar"), "M Tyranitar-EX")
        self.assertEqual(valuator.snap_name("Mega Tyranitar"), "M Tyranitar-EX")
        # Nathan's lot: 'MManectricEX' squashes EXACTLY to 'M Manectric-EX'
        # (fuzzy alone tied manectric/m-manectric); 'EeveeVax' = VMAX glue
        self.assertEqual(valuator.snap_name("MManectricEX"), "M Manectric-EX")
        self.assertEqual(valuator.snap_name("EeveeVax"), "Eevee VMAX")
        self.assertFalse(valuator._is_junk("EeveeVax"))

    def test_variant_letter_numerator(self):
        # Nathan's lot: alternate-art numbers carry a letter ('24a/119')
        name, number = valuator.guess_query(["MManectricEX", "HP210", "24a/119"])
        self.assertEqual(name, "M Manectric-EX")
        self.assertEqual(number, "24a/119")

    def test_layer_c_rejects_watermarks(self):
        # live catch: "Yujin's Pokestop" photo overlay became the card name
        # in 14/20 dataset listings — anything matching NO real name is out
        self.assertIsNone(valuator.snap_name("Yojins Pokestop"))
        self.assertIsNone(valuator.snap_name("Yojins"))
        name, number = valuator.guess_query(
            ["Yujin's Pokestop", "Pikachue", "063/193"])
        self.assertEqual(name, "Pikachu")
        self.assertEqual(number, "063/193")

    def test_glued_mechanic_shapes_not_junk(self):
        # 'HydreigonEX' / 'MBeedrillEX' are real reads, 'YEjj' is still junk
        self.assertFalse(valuator._is_junk("HydreigonEX"))
        self.assertFalse(valuator._is_junk("MBeedrillEX"))
        self.assertTrue(valuator._is_junk("YEjj"))
        self.assertTrue(valuator._is_junk("BASIG"))

    def test_promo_letter_footer(self):
        # JP/KR promos number with LETTER denominators — 6 of his 20
        # listings were numberless until this pattern existed
        _, number = valuator.guess_query(["Chespin", "034/XY-P"])
        self.assertEqual(number, "034/XY-P")
        _, number = valuator.guess_query(["70", "197/SV-P"])
        self.assertEqual(number, "197/SV-P")

    def test_fingerprint_ambiguity_guard(self):
        # live catch: {10,20} named a Chespin promo "Arbok" — tiny generic
        # profiles with no corroboration must not claim an identity
        self.assertEqual(valuator.fingerprint_names(["10", "20", "MP60"]), [])
        # corroborated but TIED ({60,150}+HP180 fits 4 cards): silent by
        # default, exposed with ties=True for cross-evidence resolution
        lines = ["180", "60", "150", "P180"]
        self.assertEqual(valuator.fingerprint_names(lines), [])
        tie = valuator.fingerprint_names(lines, ties=True)
        self.assertIn("Black Kyurem-EX", tie)
        self.assertGreater(len(tie), 1)

    def test_layer_d_dex_number(self):
        # JP vintage (his Staraptor DP holo): no Latin name, no set code,
        # but the Pokédex strip prints "NO.398" = the species
        self.assertEqual(valuator.dex_names(["NO.398走毛高：1.2m"]),
                         ["Staraptor"])
        # CJK on EITHER side of the token is a word char — \b never matched
        # ("図鑑NO.0025"); leading zeros must parse too
        self.assertEqual(valuator.dex_names(["全国网建NO.0025扫高04m"]),
                         ["Pikachu"])

    def test_tag_team_name_spans_two_lines(self):
        name, _ = valuator.guess_query(
            ["P280", "Naganadel&", "Guzzlord", "BASIC", "TAG TEAM"])
        self.assertEqual(name, "Naganadel & Guzzlord-GX")

    def test_local_printings_join(self):
        # lot catches: the local index is COMPLETE where TCGplayer text
        # search is not. A read number that is a real printing of exactly
        # one mechanic variant determines the name; promo tokens snap
        # against the family's real printings.
        lp = valuator.local_printings("Scizor")
        owners = [n for n, nums in lp.items()
                  if any(valuator._norm_num(x) == valuator._norm_num("119/122")
                         for x in nums)]
        self.assertEqual(owners, ["Scizor-EX"])
        lp2 = valuator.local_printings("Snorlax")
        allnums = sorted(set().union(*lp2.values()))
        self.assertEqual(valuator.snap_number("XY79", allnums), "XY179")
        # 26/114 is VOLCANION's number — Golem's family must NOT claim it
        # (it came from a two-card photo that fused both cards' evidence)
        lp3 = valuator.local_printings("Golem")
        self.assertEqual([n for n, nums in lp3.items()
                          if any(valuator._norm_num(x) == valuator._norm_num("26/114")
                                 for x in nums)], [])


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    n = result.testsRun
    bad = len(result.failures) + len(result.errors)
    print(f"\n{'PASS' if bad == 0 else 'FAIL'}: {n - bad}/{n} lessons hold")
    sys.exit(1 if bad else 0)
