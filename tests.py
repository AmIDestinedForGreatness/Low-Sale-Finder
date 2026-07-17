r"""
tests.py — the system's permanent memory of its own mistakes.

Every case here exists because something REAL went wrong in the feed and got
fixed. This file is the compound-interest mechanism: a bug fixed without a
test here can silently come back; a bug encoded here can never return without
this suite screaming. Pair each test with its entry in LESSONS.md.

Run:  E:\python.exe tests.py     (offline — no network, no Discord, no FB)
"""
import os
import sys
import time
import unittest
from unittest import mock

import collision
import evidence
import fb_feed
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


class TestFacebookFeedPace(unittest.TestCase):
    """7/17 live failure: one monolithic 15-group pass took hours, starving
    later groups and blocking auction maintenance."""

    def test_blank_marketplace_is_explicitly_disabled(self):
        targets, state = fb_feed.configured_targets(
            marketplace_url="",
            group_urls=["https://www.facebook.com/groups/123"])
        self.assertIn("Marketplace DISABLED", state)
        self.assertIn("FB_MARKETPLACE_URL is blank", state)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][2], "FB-GROUP")

    def test_invalid_marketplace_url_is_not_navigated(self):
        targets, state = fb_feed.configured_targets(
            marketplace_url="https://example.com/marketplace/pokemon",
            group_urls=[])
        self.assertEqual(targets, [])
        self.assertIn("invalid", state)

    def test_valid_marketplace_url_is_scanned_first(self):
        url = "https://www.facebook.com/marketplace/manila/search?query=pokemon"
        targets, state = fb_feed.configured_targets(
            marketplace_url=url,
            group_urls=["https://www.facebook.com/groups/123"])
        self.assertIn("Marketplace ENABLED", state)
        self.assertEqual(targets[0], (url, fb_feed.MARKETPLACE_JS, "FB-MP"))
        self.assertEqual(targets[1][2], "FB-GROUP")

    def test_fixed_sale_runs_expensive_valuation_once(self):
        item = {
            "url": "https://facebook.test/post/1",
            "title": "Pikachu 025/165",
            "body": "Pikachu 025/165 P100",
        }
        with mock.patch.object(
                fb_feed.prices, "market_value",
                return_value=(500.0, "test-market")) as market_value:
            result = fb_feed.analyze(item)
        market_value.assert_called_once()
        self.assertEqual(result["market"], 500.0)

    def test_collection_budget_stops_pathological_group(self):
        class Clock:
            def __init__(self):
                self.value = 0.0

            def __call__(self):
                return self.value

        class Anchor:
            def hover(self, timeout=None):
                return None

        class Mouse:
            def wheel(self, _x, _y):
                return None

        class Page:
            def __init__(self, clock):
                self.clock = clock
                self.url = ""
                self.mouse = Mouse()
                self.evaluations = 0

            def goto(self, url, **_kwargs):
                self.url = url

            def wait_for_timeout(self, milliseconds):
                self.clock.value += milliseconds / 1000.0

            def query_selector_all(self, _selector):
                return [Anchor() for _ in range(15)]

            def evaluate(self, _js):
                self.evaluations += 1
                return [{"url": f"https://facebook.test/{self.evaluations}"}]

        clock = Clock()
        page = Page(clock)
        with mock.patch.object(fb_feed.random, "randint",
                               side_effect=lambda _low, high: high):
            items = fb_feed.collect(
                page, "https://www.facebook.com/groups/123", "ignored",
                "FB-GROUP", want=20, time_budget_seconds=12, clock=clock)
        self.assertLess(page.evaluations, 16)
        self.assertLessEqual(clock.value, 12.001)
        self.assertGreaterEqual(len(items), 1)

    def test_permalink_hover_never_inherits_long_default_timeout(self):
        class Clock:
            def __init__(self):
                self.value = 0.0

            def __call__(self):
                return self.value

        class Anchor:
            def __init__(self, clock, timeouts):
                self.clock = clock
                self.timeouts = timeouts

            def hover(self, timeout=None):
                self.timeouts.append(timeout)
                self.clock.value += timeout / 1000.0

        class Page:
            def __init__(self, clock):
                self.clock = clock
                self.timeouts = []

            def query_selector_all(self, _selector):
                return [Anchor(self.clock, self.timeouts) for _ in range(40)]

            def wait_for_timeout(self, milliseconds):
                self.clock.value += milliseconds / 1000.0

        clock = Clock()
        page = Page(clock)
        with mock.patch.object(fb_feed.random, "randint",
                               side_effect=lambda _low, high: high):
            fb_feed.hydrate_permalinks(
                page, max_hovers=40, deadline=4.0, clock=clock,
                hover_timeout_ms=500)
        self.assertTrue(page.timeouts)
        self.assertLessEqual(max(page.timeouts), 500)
        self.assertLessEqual(clock.value, 4.001)

    def test_auction_maintenance_runs_between_targets(self):
        events = []
        targets = [
            ("https://facebook.test/1", "js", "FB-GROUP"),
            ("https://facebook.test/2", "js", "FB-GROUP"),
        ]

        def scan(_conn, _page, target, collection_budget_seconds=None):
            events.append(("scan", target[0], collection_budget_seconds))
            return {"sent": 0}

        def maintain(_conn):
            events.append(("auction-maintenance",))

        fb_feed.scan_targets(
            object(), object(), targets, collection_budget_seconds=45,
            scan_target_fn=scan, auction_check_fn=maintain,
            sleep_fn=lambda seconds: events.append(("pause", seconds)),
            pause_picker=lambda: 8)

        self.assertEqual(events, [
            ("scan", "https://facebook.test/1", 45),
            ("auction-maintenance",),
            ("pause", 8),
            ("scan", "https://facebook.test/2", 45),
            ("auction-maintenance",),
        ])


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

    def test_pricecharting_parser_never_regexes_the_whole_page(self):
        # Live 7/17 CPU runaway: a generic FB sale query returned a large page
        # whose partial rows kept `_ROW.findall(full_html)` backtracking for
        # hours. Row-bounded parsing must stay linear on adversarial HTML.
        incomplete = (
            '<tr><td class="title"><a href="#">Noise</a></td>' +
            ("x" * 1800) + "</tr>")
        valid = (
            '<tr><td class="title"><a href="/game/pokemon/staraptor">'
            'Staraptor #26</a></td><td><a href="/console/pokemon-japanese">'
            'Pokemon Japanese Diamond &amp; Pearl</a></td>'
            '<td class="used_price"><span>$5.58</span></td></tr>')
        html = incomplete * 500 + valid
        started = time.perf_counter()
        rows = pc_price._parse_rows(html)
        elapsed = time.perf_counter() - started
        self.assertEqual(rows[-1][0], "Staraptor #26")
        self.assertLess(elapsed, 1.0)


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
        # gallery numbering letters BOTH sides (training-scrape catch);
        # OCR glue on the prefix is trimmed via prefix-equality
        _, number = valuator.guess_query(["Gloria", "TG26/TG30"])
        self.assertEqual(number, "TG26/TG30")
        _, number = valuator.guess_query(["Deoxys", "WGG12/GG70"])
        self.assertEqual(number, "GG12/GG70")

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

    def test_layer_e_attack_names(self):
        # binder-page breakthrough: attack names are big readable English
        # OCR nails even on cell crops, and near-unique per species
        nm, nums = valuator.attack_id(["BASIC", "Victini", "Victory Ball", "50"])
        self.assertEqual(nm, "Victini")
        self.assertTrue(all(n.startswith("XY") for n in nums))
        # one OCR slip still matches ("Soprane Wave")
        nm2, _ = valuator.attack_id(["Soprane Wave", "80"])
        self.assertEqual(nm2, "Meloetta")
        # ambiguous/no evidence = no claim
        self.assertIsNone(valuator.attack_id(["Flip a coin.", "50"]))

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


class TestL32AttackNumberAdoption(unittest.TestCase):
    """L32: Layer E may adopt a number only when the species has exactly
    ONE candidate printing. The retired promo-format preference picked
    SM38 over an actual 27/149 (Incineroar) and TG16 over an actual
    068/172 (Mimikyu V) — both eye-adjudicated wrong the same day."""

    def test_single_printing_adopted(self):
        import profile_dataset
        self.assertEqual(profile_dataset.adopt_attack_number(["XY117"]), "XY117")

    def test_multiple_printings_never_picked_even_with_one_promo(self):
        import profile_dataset
        # the exact Incineroar shape: one promo-format token among numbered
        # reprints — the OLD code returned "SM38" here; the card was 27/149
        self.assertIsNone(profile_dataset.adopt_attack_number(["27/149", "SM38"]))
        # and the Mimikyu shape (TG-gallery token among regular numbers)
        self.assertIsNone(profile_dataset.adopt_attack_number(["068/172", "TG16"]))

    def test_empty_is_none(self):
        import profile_dataset
        self.assertIsNone(profile_dataset.adopt_attack_number([]))


class TestEvidence(unittest.TestCase):
    """DIRECTIVE.md (L31): no identification may omit its Evidence Level.
    These guard the pipeline ITSELF, not one card's result — a card whose
    output is missing evidence_level/evidence_chain is a Rule-1 violation
    regardless of whether the name/number happen to be right."""

    def _ident(self, **kw):
        base = {"name": None, "number": None, "number_read": None,
                "snapped": False, "via": None, "jp": False, "query": "",
                "graded": False, "candidates": []}
        base.update(kw)
        return base

    def test_every_result_has_the_required_fields(self):
        ident = self._ident(name="Pikachu ex", number="063/193",
                            candidates=[{"pid": 1, "name": "Pikachu ex", "set": "Paldea Evolved",
                                        "number": "063/193"}])
        ev = evidence.build_evidence(ident, ["Pikachu ex", "063/193"], None)
        for field in ("evidence_level", "evidence_chain", "evidence_coverage",
                      "evidence_coverage_reason", "provisional_prediction_confidence",
                      "provisional_prediction_confidence_factors",
                      "collision_analysis", "adversarial_validation"):
            self.assertIn(field, ev)
        self.assertEqual(set(ev["evidence_chain"]), set(evidence.CHAIN_STEPS))
        self.assertIn(ev["evidence_level"], evidence.LEVELS)

    def test_clean_direct_read_is_level_a(self):
        ident = self._ident(name="Pikachu ex", number="063/193",
                            candidates=[{"pid": 1, "name": "Pikachu ex", "set": "Paldea Evolved",
                                        "number": "063/193"}])
        ev = evidence.build_evidence(ident, ["Pikachu ex", "063/193"], None)
        self.assertEqual(ev["evidence_level"], "A")
        # even Level A must show the structural gap honestly, not hide it
        self.assertEqual(ev["evidence_chain"]["artwork"]["status"], "not_checked")
        self.assertEqual(ev["evidence_chain"]["holo_pattern"]["status"], "not_checked")

    def test_eye_read_is_level_b_not_a(self):
        ident = self._ident(name="Coalossal", number="117/100",
                            via="visual read (assistant eye)",
                            candidates=[{"pid": 2, "name": "Coalossal", "set": "S3",
                                        "number": "117/100"}])
        ev = evidence.build_evidence(ident, ["117/100"], None)
        self.assertEqual(ev["evidence_level"], "B")

    def test_snapped_number_is_level_c_with_inference_explanation(self):
        # the directive's OWN worked example: M Manectric-EX 024a/119
        ident = self._ident(name="M Manectric-EX", number="024a/119",
                            number_read="24a/19", snapped=True,
                            candidates=[{"pid": 3, "name": "M Manectric EX", "set": "Promo",
                                        "number": "024a/119"}])
        ev = evidence.build_evidence(ident, ["M Manectric-EX", "24a/19"], None)
        self.assertEqual(ev["evidence_level"], "C")
        ie = ev["inference_explanation"]
        for field in ("original_ocr_text", "why_ocr_failed", "candidate_search_process",
                     "why_only_one_candidate_remained", "remaining_uncertainty"):
            self.assertIn(field, ie)

    def test_name_only_is_level_d(self):
        ident = self._ident(name="Yveltal", number=None)
        ev = evidence.build_evidence(ident, ["Yveltal"], None)
        self.assertEqual(ev["evidence_level"], "D")

    def test_nothing_readable_is_level_e_with_failure_report(self):
        ident = self._ident(name=None, number=None)
        ev = evidence.build_evidence(ident, ["HP50", "blur"], None)
        self.assertEqual(ev["evidence_level"], "E")
        fr = ev["failure_report"]
        for field in ("missing_feature", "blocking_evidence",
                     "would_another_image_angle_help", "would_removing_glare_help"):
            self.assertIn(field, fr)

    def test_graded_slab_never_reaches_level_a(self):
        # slabs are region-ambiguous by construction (L-series bug: a
        # Beckett'd CHINESE promo unique-matched a JAPANESE card sharing
        # its number) — must never claim the gold standard
        ident = self._ident(name="Pikachu", number="004/SV-P", graded=True,
                            candidates=[{"pid": 4, "name": "Pikachu", "set": "SV-P",
                                        "number": "004/SV-P"}])
        ev = evidence.build_evidence(ident, ["PSA 10", "004/SV-P"], None)
        self.assertNotEqual(ev["evidence_level"], "A")

    def test_coverage_never_counts_an_unchecked_step(self):
        ident = self._ident(name="Pikachu ex", number="063/193",
                            candidates=[{"pid": 1, "name": "Pikachu ex", "set": "Paldea Evolved",
                                        "number": "063/193"}])
        ev = evidence.build_evidence(ident, ["Pikachu ex", "063/193"], None)
        confirmed = sum(1 for s in evidence.CHAIN_STEPS
                        if ev["evidence_chain"][s]["status"] == "confirmed")
        self.assertEqual(ev["evidence_coverage"],
                         round(100 * confirmed / len(evidence.CHAIN_STEPS)))
        self.assertLess(ev["evidence_coverage"], 100)
        self.assertNotIn("confidence", ev)  # the old mislabeled field must stay gone

    def test_log_failure_skips_level_a_but_seeds_structural_gap(self):
        # Capture the write in memory; tests never touch the real database.
        database = {}
        with mock.patch("evidence._load_failures", return_value=database), \
             mock.patch("evidence._save_failures") as save:
            ident = self._ident(name="Pikachu ex", number="063/193",
                                candidates=[{"pid": 1, "name": "Pikachu ex", "set": "Paldea Evolved",
                                            "number": "063/193"}])
            ident.update(evidence.build_evidence(ident, ["Pikachu ex", "063/193"], None))
            evidence.log_failure(ident)
            db_after = save.call_args.args[0]
            self.assertIn(evidence._STRUCTURAL_GAP_ID, db_after)
            self.assertNotIn(evidence._card_key(ident), db_after)  # Level A -> no per-card record


class TestCandidateCollisionAnalyzer(unittest.TestCase):
    """The adversarial stage must try to disprove a printing before A/B/C."""

    def _run(self, name="Testmon ex", number="010/100", candidates=None,
             rows=None, name_status="confirmed", number_status="confirmed"):
        context = {"status": "inferred", "name_status": name_status,
                   "number_status": number_status, "explicit": False,
                   "jp": False}
        with mock.patch("collision._catalog_rows", return_value=rows or []):
            return collision.analyze(
                name, number, collision.norm_number(number), context,
                {"status": "not_checked"}, None, [], [], candidates or [])

    def test_clean_candidate_can_remain_level_a(self):
        candidate = {"pid": 1, "name": "Testmon ex", "number": "010/100",
                     "set": "Only Set"}
        result = self._run(candidates=[candidate])
        self.assertEqual(result["collision_status"], "none")
        self.assertEqual(result["recommended_evidence_level"], "A")
        self.assertTrue(result["search_performed"])
        self.assertIn("no plausible", result["reason"])

    def test_same_name_number_across_sets_is_confirmed_collision(self):
        candidates = [
            {"pid": 1, "name": "Testmon ex", "number": "010/100", "set": "Set A"},
            {"pid": 2, "name": "Testmon ex", "number": "010/100", "set": "Set B"},
        ]
        result = self._run(candidates=candidates)
        self.assertEqual(result["collision_status"], "confirmed")
        self.assertEqual(result["recommended_evidence_level"], "D")
        self.assertEqual(result["competing_candidates"][0]["set"], "Set B")
        self.assertIn("expansion_symbol", result["evidence_missing"])

    def test_valid_ocr_number_one_edit_from_wrong_real_product_is_possible(self):
        candidates = [
            {"pid": 1, "name": "Testmon ex", "number": "010/100", "set": "Set A"},
            {"pid": 2, "name": "Testmon ex", "number": "018/100", "set": "Set A"},
        ]
        result = self._run(candidates=candidates)
        self.assertEqual(result["collision_status"], "possible")
        self.assertEqual(result["recommended_evidence_level"], "C")
        self.assertEqual(result["competing_candidates"][0]["number_relation"],
                         "ocr_substitution")

    def test_direct_name_excludes_unrelated_same_number_but_records_test(self):
        candidates = [
            {"pid": 1, "name": "Testmon ex", "number": "010/100", "set": "Set A"},
            {"pid": 2, "name": "Othermon", "number": "010/100", "set": "Set Z"},
        ]
        result = self._run(candidates=candidates)
        self.assertEqual(result["collision_status"], "none")
        self.assertEqual(result["alternatives_tested"][0]["name"], "Othermon")
        self.assertIn("directly-read name", result["alternatives_tested"][0]["excluded_by"])

    def test_inferred_name_cannot_exclude_same_number_other_language(self):
        candidates = [
            {"pid": 1, "name": "Testmon ex", "number": "010/100",
             "set": "English Set", "line": "Pokemon"},
            {"pid": 2, "name": "Othermon", "number": "010/100",
             "set": "Japanese Set", "line": "Pokemon Japan"},
        ]
        result = self._run(candidates=candidates, name_status="inferred")
        self.assertEqual(result["collision_status"], "confirmed")
        self.assertEqual(result["recommended_evidence_level"], "D")

    def test_promo_leading_zero_and_suffix_variants_are_searched(self):
        self.assertEqual(collision.number_relation("XY117", "117/XY-P"),
                         "normalized_variant")
        self.assertEqual(collision.number_relation("010/100", "10/100"), "exact")
        self.assertEqual(collision.number_relation("024a/119", "24/119"),
                         "normalized_variant")

    def test_previous_attack_preference_cases_are_adversarially_exposed(self):
        for name, number, old_wrong in (
                ("Incineroar", "27/149", "SM38"),
                ("Mimikyu V", "068/172", "TG16")):
            candidates = [
                {"pid": 1, "name": name, "number": number, "set": "actual"},
                {"pid": 2, "name": name, "number": old_wrong, "set": "old heuristic"},
            ]
            result = self._run(name=name, number=number, candidates=candidates)
            tested = result["alternatives_tested"]
            self.assertTrue(any(c["number"] == old_wrong for c in tested), name)


class TestCollisionEvidenceIntegration(unittest.TestCase):
    def _ident(self, candidates, **changes):
        base = {"name": "Testmon ex", "number": "010/100",
                "number_read": "010/100", "snapped": False, "via": None,
                "jp": False, "query": "Testmon ex 010/100", "graded": False,
                "candidates": candidates}
        base.update(changes)
        return base

    def test_multiple_candidates_land_level_d_not_silent_pick(self):
        candidates = [
            {"pid": 1, "name": "Testmon ex", "number": "010/100", "set": "A"},
            {"pid": 2, "name": "Testmon ex", "number": "010/100", "set": "B"},
        ]
        with mock.patch("collision._catalog_rows", return_value=[]):
            result = evidence.build_evidence(self._ident(candidates),
                                             ["Testmon ex", "010/100"])
        self.assertEqual(result["evidence_level"], "D")
        self.assertEqual(result["collision_analysis"]["collision_status"], "confirmed")
        self.assertIsNotNone(result["adversarial_validation"]["strongest_alternative"])

    def test_preserved_direct_name_excludes_unrelated_same_number(self):
        candidates = [
            {"pid": 1, "name": "Testmon ex", "number": "010/100", "set": "A"},
            {"pid": 2, "name": "Othermon", "number": "010/100", "set": "B"},
        ]
        ident = self._ident(candidates, name_read="Testmon ex",
                            via="local index: number is a printing")
        with mock.patch("collision._catalog_rows", return_value=[]):
            result = evidence.build_evidence(ident, ["Testmon ex", "010/100"])
        self.assertEqual(result["collision_analysis"]["collision_status"], "none")
        self.assertNotEqual(result["evidence_level"], "D")
        excluded = result["collision_analysis"]["alternatives_tested"]
        self.assertTrue(any(c["name"] == "Othermon" for c in excluded))

    def test_partial_direct_name_excludes_unrelated_same_number(self):
        # Live re-audit catch: OCR read ``Mew`` and the catalog refined it to
        # ``Mew V``. The direct fragment still excludes Wyrdeer at the same
        # number, even though the mechanic suffix remains inferred.
        candidates = [
            {"pid": 1, "name": "Mew V", "number": "069/189", "set": "A"},
            {"pid": 2, "name": "Wyrdeer", "number": "069/189", "set": "B"},
        ]
        ident = self._ident(candidates, name="Mew V", name_read="Mew",
                            number="069/189", number_read="069/189",
                            via="local index: number is a printing")
        with mock.patch("collision._catalog_rows", return_value=[]):
            result = evidence.build_evidence(ident, ["Mew", "069/189"])
        self.assertEqual(result["collision_analysis"]["collision_status"], "none")
        self.assertEqual(result["evidence_level"], "C")

    def test_partial_name_does_not_exclude_a_real_mechanic_variant(self):
        candidates = [
            {"pid": 1, "name": "Altaria EX (Full Art)",
             "number": "123/124", "set": "A"},
            {"pid": 2, "name": "M Altaria-EX", "number": "121/124", "set": "A"},
        ]
        ident = self._ident(candidates, name="Altaria-EX", name_read="Altaria",
                            number="123/124", number_read="123/124",
                            via="local index: number is a printing")
        with mock.patch("collision._catalog_rows", return_value=[]):
            result = evidence.build_evidence(ident, ["Altaria", "123/124"])
        self.assertEqual(result["collision_analysis"]["collision_status"], "possible")
        self.assertEqual(result["evidence_level"], "C")
        self.assertTrue(any(c["name"] == "M Altaria-EX"
                            for c in result["collision_analysis"]["competing_candidates"]))

    def test_catalog_display_annotation_is_not_a_self_collision(self):
        candidates = [
            {"pid": 1, "name": "Altaria-EX", "number": "123/124", "set": "A"},
            {"pid": 2, "name": "Altaria EX (Full Art)",
             "number": "123/124", "set": "A"},
        ]
        context = {"status": "inferred", "name_status": "confirmed",
                   "number_status": "confirmed", "explicit": False, "jp": False}
        with mock.patch("collision._catalog_rows", return_value=[]):
            result = collision.analyze(
                "Altaria-EX", "123/124", "123/124", context,
                {"status": "not_checked"}, None, [], [], candidates)
        self.assertEqual(result["collision_status"], "none")

    def test_graded_slab_region_collision_runs_through_general_analyzer(self):
        candidates = [
            {"pid": 1, "name": "Pikachu", "number": "004/SV-P",
             "set": "Chinese promo", "line": "Pokemon"},
            {"pid": 2, "name": "Pikachu", "number": "004/SV-P",
             "set": "Japanese promo", "line": "Pokemon Japan"},
        ]
        ident = self._ident(candidates, name="Pikachu", number="004/SV-P",
                            number_read="004/SV-P", graded=True)
        with mock.patch("collision._catalog_rows", return_value=[]):
            result = evidence.build_evidence(ident, ["BGS 10", "004/SV-P"])
        self.assertEqual(result["collision_analysis"]["collision_status"], "confirmed")
        self.assertEqual(result["evidence_level"], "D")

    def test_every_decision_contains_falsification_block_even_when_clean(self):
        candidates = [{"pid": 1, "name": "Testmon ex", "number": "010/100",
                       "set": "Only Set"}]
        with mock.patch("collision._catalog_rows", return_value=[]):
            result = evidence.build_evidence(self._ident(candidates),
                                             ["Testmon ex", "010/100"])
        self.assertEqual(result["evidence_level"], "A")
        for field in ("strongest_alternative", "evidence_supporting_alternative",
                      "evidence_excluding_alternative",
                      "could_ocr_substitution_explain_alt",
                      "could_collision_be_undetected", "what_would_overturn_this"):
            self.assertIn(field, result["adversarial_validation"])


class TestEvidenceProviders(unittest.TestCase):
    def _ident(self):
        return {"name": "Testmon ex", "number": "010/100",
                "number_read": "010/100", "snapped": False, "via": None,
                "jp": False, "query": "Testmon ex 010/100", "graded": False,
                "candidates": [{"pid": 1, "name": "Testmon ex",
                                "number": "010/100", "set": "Only Set"}]}

    def test_artwork_match_raises_coverage_but_not_prediction_confidence(self):
        image, reference = "synthetic-input.png", "synthetic-reference.png"
        with mock.patch("providers.artwork.os.path.exists", return_value=True), \
             mock.patch("providers.artwork._hash_similarity", return_value=1.0), \
             mock.patch("collision._catalog_rows", return_value=[]):
            baseline = evidence.build_evidence(self._ident(),
                                               ["Testmon ex", "010/100"])
            matched = evidence.build_evidence(
                self._ident(), ["Testmon ex", "010/100"], image_paths=[image],
                provider_context={"reference_images": [reference]})
        self.assertEqual(matched["evidence_chain"]["artwork"]["status"], "confirmed")
        self.assertEqual(matched["evidence_coverage"], baseline["evidence_coverage"] + 10)
        self.assertEqual(matched["provisional_prediction_confidence"],
                         baseline["provisional_prediction_confidence"])

    def test_no_reference_is_not_verified_never_guessed(self):
        image = "synthetic-input.png"
        with mock.patch("providers.artwork.os.path.exists", return_value=True), \
             mock.patch("providers.artwork._dataset_references", return_value={}), \
             mock.patch("collision._catalog_rows", return_value=[]):
            result = evidence.build_evidence(
                self._ident(), ["Testmon ex", "010/100"], image_paths=[image])
        art = result["evidence_chain"]["artwork"]
        self.assertEqual(art["status"], "not_verified")
        self.assertIsNone(art["provider_result"]["matched_reference"])

    def test_future_provider_stubs_are_honest(self):
        from providers import AbilityProvider, ExpansionProvider, HoloProvider, HPProvider
        for provider in (HPProvider(), AbilityProvider(), ExpansionProvider(), HoloProvider()):
            self.assertEqual(provider.verify(None, [], {})["status"], "not_checked")


class TestReauditHandoffEdges(unittest.TestCase):
    def test_lot_path_resolves_renamed_file_before_legacy_name(self):
        import reaudit
        row = {"file": "Eevee VMAX  English.png",
               "renamed_to": "Eevee VMAX SWSH087 English.png"}
        with mock.patch("reaudit.os.path.exists",
                        side_effect=lambda path: path.endswith("SWSH087 English.png")):
            path = reaudit._lot_image(row, "missing-key.png")
        self.assertTrue(path.endswith("Eevee VMAX SWSH087 English.png"))

    def test_durable_eye_read_skips_expensive_automated_reidentification(self):
        import reaudit
        old = {"name": "Coalossal", "name_read": "Coalossal",
               "number": "117/100", "number_read": "117/100",
               "via": "visual read (assistant eye)", "snapped": False,
               "jp": True, "graded": False,
               "confidence": 50, "confidence_reason": "legacy",
               "candidates": [{"name": "Coalossal", "number": "117/100",
                               "set": "s3"}]}
        with mock.patch("reaudit.profile_dataset.identify") as identify, \
             mock.patch("collision._catalog_rows", return_value=[]), \
             mock.patch("reaudit.evidence.log_failure"):
            result = reaudit._identify_with_retry(
                [], [["Coalossal", "117/100"]], set(), old, "test")
        identify.assert_not_called()
        self.assertEqual(result["evidence_level"], "B")
        self.assertNotIn("confidence", result)
        self.assertNotIn("confidence_reason", result)

    def test_cached_exact_number_reuses_transparent_inference(self):
        import reaudit
        old = {"name": "Combusken", "name_read": None,
               "number": "065/PCG-P", "number_read": "065/PCG-P",
               "via": "unique number match", "snapped": False,
               "jp": True, "graded": False,
               "candidates": [{"name": "Combusken", "number": "065/PCG-P",
                               "set": "PCG Promo"}]}
        with mock.patch("reaudit.profile_dataset.identify") as identify, \
             mock.patch("collision._catalog_rows", return_value=[]):
            result = reaudit._identify_with_retry(
                [], [["065/PCG-P"]], set(), old, "test")
        identify.assert_not_called()
        self.assertEqual(result["evidence_level"], "C")
        self.assertEqual(result["number_read"], "065/PCG-P")

    def test_cached_number_keeps_a_compatible_direct_name_fragment(self):
        import reaudit
        old = {"name": "Zoroark-GX", "name_read": None,
               "number": "53/73", "number_read": "53/73",
               "via": "local index: number is a printing", "snapped": False,
               "jp": False, "graded": False,
               "candidates": [{"name": "Zoroark GX", "number": "53/73",
                               "set": "Shining Legends"}]}
        rows = [{"id": "hop", "name": "Hop", "number": "53/73",
                 "set": "swsh35"}]
        with mock.patch("reaudit.profile_dataset.identify") as identify, \
             mock.patch("collision._catalog_rows", return_value=rows):
            result = reaudit._identify_with_retry(
                [], [["Zoroark", "53/73"]], set(), old, "test")
        identify.assert_not_called()
        self.assertEqual(result["name_read"], "Zoroark")
        self.assertEqual(result["collision_analysis"]["collision_status"], "none")
        self.assertEqual(result["evidence_level"], "C")

    def test_fresh_more_specific_name_overrides_committed_inference(self):
        import reaudit
        old = {"name": "Pikachu", "name_read": None,
               "number": "10/18", "number_read": "10/18",
               "via": "dex number", "snapped": False, "jp": False,
               "graded": False, "candidates": []}
        replacement = {"name": "Detective Pikachu",
                       "name_read": "Detective Pikachu", "number": "10/18",
                       "number_read": "10/18", "via": None,
                       "candidates": [{"name": "Detective Pikachu",
                                       "number": "10/18", "set": "Detective"}]}
        with mock.patch("reaudit.profile_dataset.identify",
                        return_value=replacement) as identify:
            result = reaudit._identify_with_retry(
                [], [["Detective Pikachu", "10/18"]], set(), old, "test")
        identify.assert_called_once()
        self.assertEqual(result["name"], "Detective Pikachu")


class TestBinderDashboardFallback(unittest.TestCase):
    def test_narrow_four_card_photo_gets_bounded_grid_probe(self):
        import folder_dataset
        self.assertTrue(folder_dataset.should_probe_grid(720, 1280, 0))
        self.assertFalse(folder_dataset.should_probe_grid(965, 1280, 0))

        groups = [["Weavile"], ["Excadrill"], ["Stoutland"], ["Wishiwashi"]]
        with mock.patch("folder_dataset.split_grid",
                        return_value=["c0", "c1", "c2", "c3"]):
            cells, ocr = folder_dataset.probe_grid(
                "binder.jpg", ".", ocr_reader=lambda cell: groups[int(cell[-1])])
        self.assertEqual(cells, ["c0", "c1", "c2", "c3"])
        self.assertEqual(len(ocr), 4)

    def test_valid_looking_non_catalog_footer_stays_partial(self):
        # Live dashboard catch from the supplied binder: Stoutland 248/236
        # was OCR'd as 240/250. A syntactically valid number is not a printing
        # unless an exact catalog product corroborates it.
        ident = {"name": "Stoutland", "name_read": "Stoutland",
                 "number": "240/250", "number_read": "240/250",
                 "snapped": False, "via": "attack names", "jp": False,
                 "graded": False, "candidates": []}
        rows = [{"id": "real", "name": "Stoutland", "number": "248/236",
                 "set": "sm12"}]
        with mock.patch("collision._catalog_rows", return_value=rows):
            result = evidence.build_evidence(
                ident, ["Stoutland", "240/250"], ("Stoutland", ["248/236"]))
        self.assertEqual(result["evidence_level"], "D")
        self.assertEqual(result["evidence_chain"]["catalog_match"]["status"],
                         "not_checked")
        self.assertIn("exact catalog product",
                      result["failure_report"]["missing_feature"])
        self.assertIn("no exact API or local catalog product",
                      result["failure_report"]["blocking_evidence"])

    def test_exact_local_catalog_product_corroborates_without_api_candidate(self):
        ident = {"name": "Testmon ex", "name_read": "Testmon ex",
                 "number": "010/100", "number_read": "010/100",
                 "snapped": False, "via": None, "jp": False,
                 "graded": False, "candidates": []}
        rows = [{"id": "real", "name": "Testmon ex", "number": "010/100",
                 "set": "only"}]
        with mock.patch("collision._catalog_rows", return_value=rows):
            result = evidence.build_evidence(ident, ["Testmon ex", "010/100"])
        self.assertEqual(result["evidence_chain"]["catalog_match"]["status"],
                         "confirmed")
        self.assertEqual(result["evidence_level"], "A")


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    n = result.testsRun
    bad = len(result.failures) + len(result.errors)
    print(f"\n{'PASS' if bad == 0 else 'FAIL'}: {n - bad}/{n} lessons hold")
    sys.exit(1 if bad else 0)
