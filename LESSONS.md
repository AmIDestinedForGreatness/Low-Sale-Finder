# LESSONS.md — what this system learned the hard way

Every entry is a real mistake that happened in production, the rule it taught,
and the test that now guards it. **The rule: no bug is "fixed" until its
lesson is encoded here AND in `tests.py`.** That's how the system compounds —
each error makes it permanently smarter, not temporarily patched.

Run the guard suite: `E:\python.exe tests.py`

---

## Pricing

### L1 — Never declare a "data gap" from one query phrasing (2026-07-15)
**Mistake:** Mega Camerupt XY198a & Mega Beedrill XY158 were reported as
"unpriced — data-source limit." Both had TCGplayer prices the whole time.
The search queried "Mega Camerupt"; TCGplayer stores XY-era Mega promos as
**"M Camerupt EX"** and its synonym search doesn't bridge the two spellings.
**Rule:** before calling anything unavailable, run the raw search and read
the results. Cast a WIDE name net (`_name_variants`), let the strict number
match keep precision. Platforms name the same card differently.
**Guard:** `TestTcgMatching.test_mega_name_variants`

### L2 — Promo numbers match in FULL, never by leading digits (2026-07-15)
**Mistake:** `XY198a` (Alt-Art Promo, $27.44) collapsed to "198" and matched
`XY198` (Jumbo, $11) — different collectibles, 2.5× price gap.
**Rule:** promo-form tokens (XY…, SM…, SWSH…) require exact-token equality;
Jumbo/oversized sets are dropped unless the listing says "jumbo."
**Guard:** `TestTcgMatching.test_promo_number_exact`

### L3 — A "wrong-looking" price isn't always a bug (2026-07-15)
**Mistake:** Mega Manectric JP at ₱102 (~$1.76) was declared a wrong-match
bug. The match was correct — the card genuinely crashed on TCGplayer.
**Rule:** before blaming the matcher, check the card's actual market page.
Verify against reality, in both directions.

### L4 — Graded slabs never get raw-card prices
**Rule:** PSA/BGS/CGC in the title → skip auto-valuation entirely. A slab
price from raw-market data is garbage in both directions.
**Guard:** `TestTcgMatching.test_grade_skipped`

### L5 — US market ≠ PH market; there is no fixed multiplier (2026-07-15)
**Finding (Yujin's own listings as ground truth):** PH ask as % of TCGplayer
market ranged **41%–313%**. Modern EN meta sells ABOVE US in PH; JP promos
below; crashed cards stay sticky in PH.
**Rule:** TCGplayer/PriceCharting are global *anchors*, not PH truth. The
real PH market can only come from accumulated PH listing data (the price
index — the standing long-term build).

## Deal detection

### L6 — Marketing words are clickbait, not distress (2026-07-15, Yujin)
**Mistake:** "below market," "mura na," "dirt cheap," "giveaway price"
triggered @everyone snipe pings. Those are seller *claims*.
**Rule:** distress = verifiable seller SITUATION only (rush, quitting,
need cash, downsizing). A real snipe is a PRICE ≤ ~72–78% of market by
valuation, never an adjective.
**Guard:** `TestAuctionVsDistress.test_marketing_claims_are_not_distress`

### L7 — "Steal" is an auction mechanic in PH TCG (2026-07-15, Yujin)
**Mistake:** "STEAL" pinged as underpriced. In PH claim sales,
DIBS/Steal/Buy-Out are bidding mechanics.
**Rule:** dib/key/steal/buyout/claim → auction channel, never distress.
**Guard:** `TestAuctionVsDistress.test_steal_is_auction_mechanic_not_distress`

### L8 — Auctions are never "under market" (2026-07-15)
**Mistake:** starting bids (always below market by design) fired UNDER MARKET
@everyone pings.
**Rule:** only fixed-price SALES get valued. An auction's real price is only
knowable at its end.

## Parsing

### L9 — Numbers near prices aren't prices
**Mistakes:** "60 days" → ₱60; "70%" → ₱70; auction end-time "6:30PM" → ₱30.
**Rule:** parse_price requires currency context; auction price = parsed
starting bid, never a stray number.
**Guards:** `TestParsePrice`, `TestParseAuction`

### L10 — "Bundle" is a card lot in PH; only "booster bundle" is sealed
**Guard:** `TestClassify.test_generic_bundle_is_bulk_not_sealed`

## Scraping

### L11 — Never assert a platform limitation without probing it (2026-07-15)
**Mistake:** claimed "FB scrambles post text against scrapers." Wrong — I had
grabbed the wrong DOM nodes. Body text reads clean from `div[dir="auto"]`.
Same failure family as L1: a confident "the platform blocks this" that was
never verified.
**Rule:** prove a limitation with a probe before reporting it as fact.

### L12 — FB sort order: CHRONOLOGICAL, not RECENT_ACTIVITY (2026-07-15)
**Mistake:** RECENT_ACTIVITY bumped comment-active posts → yield crashed to
~1/scan and multi-card gallery auctions fragmented (the Numel bug).
**Rule:** CHRONOLOGICAL reliably yields ~20 clean parent posts.

### L13 — run_sniper.bat is not idempotent (2026-07-15)
**Mistake:** running it twice stacked duplicate feed loops → duplicate
Discord posts.
**Rule:** to restart, kill python + loop.bat cmd windows first, launch ONCE.
Code-side guard: `claim()` atomic INSERT-OR-IGNORE dedup.

### L14 — Detection risk is behavioral volume, not order (2026-07-15)
**Rule:** randomizing scrape *order* doesn't reduce ban risk; lower VOLUME,
randomized DELAYS, slower cadence do. Scope expensive reads (comments) to
the smallest honest set (e.g. only claim-sale posts / reacted auctions).

### L16 — a market price without sales VELOCITY is unstable (2026-07-15, Yujin)
**Lesson (his grading of the Magcargo test, worth 7.5/10):** "$12.42 market"
means little by itself. A $10 card that sells 2-3×/YEAR has an unstable,
barely-real valuation; one that sells 20-100×/day has an earned one.
**Rule:** valuation = price × confidence, where confidence comes from sales
volume/recency. Check "how many sold" alongside "for how much." Build target:
pull TCGplayer latest-sales / PriceCharting volume and tag every price
HIGH/MED/LOW confidence.

### L17 — condition: whitening first, NM is earned, not the default (2026-07-15, Yujin)
**Mistake:** called his Magcargo GX back "corners sharp, no visible whitening
→ consistent with NM." He circled visible whitening at multiple corners and
edges in the SAME photos. I read the photos optimistically — treating
"I can't clearly see damage" as "there is no damage."
**Rule:** absence of evidence ≠ evidence of absence, and the bias must run
the OTHER way: scan corners/edges for white flecks FIRST, assume LP until
the card proves NM. This inverts the burden of proof — exactly what a real
grader does. (His NM price ₱1.2k; whitening knocks it down a tier.)

## Meta

### L15 — Scratchpad tests are not tests (2026-07-15, Yujin's compound-interest rule)
**Mistake:** every "8/8 / 12/12 tests pass" earlier in this build was an
ad-hoc scratchpad script, discarded after passing. The repo had ZERO
permanent tests — the system had no memory of its own mistakes.
**Rule:** a fix isn't done until its regression case lives in `tests.py`
and its lesson lives here. This file and that suite ARE the compounding.

### L18 — verify the rendered page, not just the API (2026-07-15)
**Mistake:** shipped the photo lightbox with `class="hidden"` PLUS inline
`display:flex` — inline styles beat classes, so the "hidden" overlay
covered the whole dashboard and ate every click on reload. I had verified
the API endpoint after the change but never reloaded the PAGE itself.
**Rule:** after any UI change, load the actual page and look at it (or
assert on the served HTML) — an endpoint returning 200 says nothing about
what the user sees. Element visibility that JS toggles should have ONE
source of truth (JS sets style.display), never a class fighting an inline style.

### L19 — an API's request slug is not its response value (2026-07-16)
**Mistake:** requests FILTER on `productLineName: ["pokemon-japan"]` (slug),
but RESULTS return `"Pokemon Japan"` (display name). Code compared results
against the slug — never matched — so the "Japanese" prefix and JP-first
ranking silently did nothing. Yujin caught it on a verified-V0.6 page.
**Rule:** never assume a response field's format from the request's format —
print an actual response value before comparing against it. (L1/L11 family:
verify, don't assume.) Language checks now case-insensitively substring-match.

### L20 — a valuation needs an IDENTITY, and absurd ratios mean wrong match (2026-07-16)
**Mistake (two live @everyone false snipes):** a toy Lucario ("FS pokemon
with box") priced as a ₱22k booster box; plushies ("Paubos Sale!!") priced
at ₱846 — PriceCharting matched on generic tokens ("pokemon"+"box"), then
1%/30%-of-market fired UNDER MARKET pings.
**Rules:** (1) a price match requires a SPECIFIC identifying token (the
Pokémon's name) in the product NAME itself — generic words and console-text
overlap don't count (also kills the Combee←Combusken dup bug); a title with
no specific tokens is unpriceable, full stop. (2) A listing under 15% of
"market" is a wrong MATCH, not a snipe — mismatch guard, never ping.
**Guard:** `TestPriceChartingPrecision`

## The 20-listing dataset run (2026-07-16→17, his task: identify every
## Pokestop listing from IMAGES ONLY, titles used only to verify after)

### L21 — a guessed name must be a REAL card name (Layer C) (2026-07-17)
**Mistake:** the name guesser accepted any plausible-shaped text. His photo
watermark "Yujin's Pokestop" became the searched card name in 14/20
listings (as "Yojins Pokestop", "Pokestop", "Yoins"…), and OCR misreads
("Pikachue", "arizardex") searched as-is → dead ends.
**Rule:** validate every name against the local all-cards vocabulary
(4,428 names): snap unique near-misses (Pikachue→Pikachu,
arizardex→Charizard, MCameruptEX→M Camerupt-EX, glued-suffix priority
pikachuex→Pikachu ex), REJECT what matches nothing — rejection is
information: it hands control to the setcode/fingerprint/dex layers.
**Guard:** `ValuatorLayerCD.test_layer_c_*`

### L22 — seller watermarks are cross-LISTING repeats, not cross-photo (2026-07-17)
**Mistake #1:** filtered text appearing on 3+ photos of one listing — wrong:
6 photos of the SAME card repeat the card's own text (it deleted the attack
damages and killed fingerprints), while the overlay OCR'd differently every
photo ("Yojins"/"Yoins"/"Poke stop") and escaped.
**Rule:** watermark = high document-frequency tokens ACROSS listings
(≥40% of different cards), minus universal card terms (weakness/retreat/…
— else "Weakness Policy" loses its name), matched fuzzily (lev ≤1-2) and
on joined letters ("Poke stop"→pokestop). Bonus trap: "Pokestop" itself is
a REAL card (PokéStop, Pokémon GO set) — only cross-listing frequency can
tell the overlay from the card.

### L23 — a 2-damage fingerprint with no corroboration is a coin flip (2026-07-17)
**Mistake:** {10,20} named a Chespin promo "Arbok"; a Pikachu promo became
"Lucario"; and the {60,150}+HP180 profile that "identified" Black Kyurem-EX
actually fits FOUR cards — it had won by alphabet, not evidence.
**Rules:** (1) claim a fingerprint only with corroboration (matched HP or
3+ damages) AND a clear winner — ambiguity returns nothing; (2) a
corroborated TIE is still usable evidence: cross it with the collector
number's own catalog matches — exactly one card in both = identified
("fingerprint × number", how Black Kyurem was legitimately resolved).
**Guard:** `ValuatorLayerCD.test_fingerprint_ambiguity_guard`

### L24 — JP promos number with LETTER denominators; JP vintage prints the
### DEX number (Layers footer+D) (2026-07-17)
**Mistake:** 6 of his 20 listings are promos numbered "034/XY-P",
"197/SV-P", "065/PCG-P" — the digit-only footer regexes read NOTHING off
them. And his JP D&P Staraptor has no collector number at all.
**Rules:** (1) promo footer pattern `NNN/<LETTERS>-P` is a first-class
collector number — and TCGplayer resolves most uniquely (unique catalog
match = the card, still eye-gated); (2) JP vintage prints the National Dex
number in the Pokédex strip ("NO.398" → Staraptor) — a species ID when
nothing else is readable (needed the dex column added to the fingerprint DB).
**Guard:** `ValuatorLayerCD.test_promo_letter_footer`, `test_layer_d_dex_number`

### L25 — Layer-B number snapping needs a STRONG name (2026-07-17)
**Mistake:** with weak name "Pikachu" (base of "Pikachu ex"), snap
"corrected" a correctly-read 063/193 BACKWARD to 062/193 — the plain
Pikachu's printing. The snap direction was driven by an under-specified
name, not by OCR error.
**Rule:** snap numbers only when the name is CERTAIN (fingerprint/dex) or
SPECIFIC (full mechanic form / multi-word). And harvest names from EVERY
photo, voting for the most specific validated read ("Pikachu ex" beats
"Pikachu"; two-line TAG TEAM names join: "Naganadel&"+"Guzzlord").
**Guard:** `ValuatorLayerCD.test_tag_team_name_spans_two_lines` + the
Pikachu-ex snap case in the dataset itself (`dataset/carousell_profile.json`)

## the overnight lot (2026-07-17 overnight, 38 cards incl. binder pages)

### L26 — real-world photos: orientation, glue, variant letters, grids (2026-07-17)
**Mistakes (one run, five classes):** sideways phone photos OCR'd scrambled;
'MManectricEX' fuzzy-tied between 'manectric'/'m manectric' (both d1, both
start 'm'); 'EeveeVax' (VMAX glue misread) failed the junk shape; '24a/119'
alternate-art numerators were invisible to `\d{1,3}/\d{1,3}`; a 2×2 binder
page OCR'd as one soup.
**Rules:** (1) landscape photo → retry 90°/270°, best evidence wins;
(2) separator-SQUASHED exact match before fuzzy ('mmanectricex' ==
'm manectric-ex' squashed), and squashed distance as the final tie-break;
(3) junk-shape allows Name+mechanic glue incl. V-forms; (4) numerators may
carry a variant letter; (5) 3+ distinct vocabulary-validated names in one
photo = multi-card → quadrant crops identified separately.
**Guards:** `ValuatorLayerCD.test_layer_c_snaps_ocr_misreads` (MManectricEX,
EeveeVax), `test_variant_letter_numerator`

### L27 — language is a CLAIM; a price needs name+number AGREEMENT (2026-07-17)
**Mistakes:** (1) `jp` was inferred from ANY identification-path evidence —
"unique number match" says nothing about language; 4 English cards got
renamed "…Japanese" before correction. (2) The lot pricer picked the sole
candidate even when its NUMBER disagreed with the read one, and picked
number-matches whose NAME disagreed — a "Snorlax" priced ₱6,850 off a
LATIOS promo (L20's ghost, back through a new door).
**Rules:** (1) "Japanese" only with positive evidence: JP set code, JP promo
footer (…/XY-P), or the unreadable-name paths (fingerprint/dex); the weak
"number-without-name" hint may rank searches but never label language.
(2) `price_confident`: the priced product's name must CONTAIN the identified
name's tokens AND its number must match the read number — else no price.
Wrong prices are worse than no prices, doubly so when selling on 
someone's behalf.

### L28 — the number is evidence; the LOCAL index is complete (2026-07-17, training shift)
**Mistakes (one per rule):** "Mimikyu #068/172" claimed nothing — the card
is Mimikyu V, OCR drops the stylized V/GX glyph, and the base-name search
never surfaces the variant product; "Snorlax XY79" became a LATIOS (XY79
promo-token matched the JP-setcode regex → whole-query search → zero hits
→ retry dropped "Snorlax"); "Golem #26/114" fused TWO cards' evidence —
the photo held Volcanion EX + Golem EX side by side; TCGplayer text search
simply never returns some promo/Full-Art products at any size.
**Rules:** (1) when no candidate carries the read number, JOIN the number
against the LOCAL index's printings of the name + its mechanic variants —
a unique owner IS the card (Scizor #119/122 → Scizor-EX); unique 1-edit
promo snaps ride the same printings (XY79→XY179). Index rebuilt with FULL
collector numbers (numerators alone are ambiguous across variants).
(2) The setcode fast-path requires a slash-number beside it — bare promo
tokens are not set codes. (3) TWO validated names in a LANDSCAPE frame =
two cards side by side → 1×2 split (tag-teams are portrait). (4) Candidate
consensus: all number-matching products sharing ONE name = the name.
**Guards:** `ValuatorLayerCD.test_local_printings_join`
