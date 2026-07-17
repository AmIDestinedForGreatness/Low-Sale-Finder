# LESSONS.md — what this system learned the hard way

Every entry is a real mistake that happened in production, the rule it taught,
and the test that now guards it. **The rule: no bug is "fixed" until its
lesson is encoded here AND in `tests.py`.** That's how the system compounds —
each error makes it permanently smarter, not temporarily patched. **32 lessons.**

**Governing standard as of L31: `DIRECTIVE.md`.** Every lesson from here on
must classify its card(s) by Evidence Level (A-E), not a bare confidence %,
and every "couldn't identify" must be a Required Failure Report, not a shrug.

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

### L29 — attack names identify cards; frequency beats length; slabs are
### region-ambiguous (2026-07-17 training shift)
**Mistakes:** a seller's TRAILER photo (same Mimikyu ex shot appended to
every listing) named 3 different cards — the vote preferred the LONGER
name over the one read on MORE photos; binder-cell footers sit below OCR
resolution and names alone tied (Melaeta = Meloetta or Melmetal?); a
Beckett'd CHINESE Pikachu promo #004/SV-P unique-matched the JAPANESE
SV-P 004 (Dondozo); TG26/TG30-style gallery numbers had no pattern; my
own "BINDER -" rename force-quartered a two-card pair on re-run; 5% cell
overlap bled the neighbor's title into the blurred Weavile cell.
**Rules:** (1) LAYER E: attack/ability names (31,908 indexed) are big
readable English text, near-unique per species — exact + 1-slip fuzzy,
multiple hits intersect, ambiguity claims nothing. (2) Name vote =
frequency first, then specificity, then length. (3) Slab detected (psa/
bgs/cgc/beckett…, glued grades count) → never adopt a name from a bare
number; label numbers are region-ambiguous. (4) Gallery numbering
letters-both-sides with prefix-equality glue-trimming. (5) Layout
detection precedes filename hints; duplicate names across cells = bleed,
keep the stronger evidence. (6) Evidence merged across runs is MARKED as
merged, never presented as a single-run read.
**Guards:** `ValuatorLayerCD.test_layer_e_attack_names`,
`test_promo_letter_footer` (gallery+glue)

### L30 — glued attack names, and ambiguous promos need a DEEPER search, not a smarter guess (2026-07-17, live dashboard bug report)
**Mistake #1:** his live binder-mode screenshot showed 3/4 cards unread. Root
cause, found by replaying his exact photo through the exact live code path:
attack names OCR'd with NO space ("SopranoWave", "PrismaticWave",
"MarineGuidance") — Layer E only matched space-joined tokens.
**Fix:** camelCase-shaped glued runs are squash-matched against a no-space
attack index (exact, then 1-2 edit fuzzy).
**Mistake #2 (deeper, found chasing #1):** even once the NAME resolved,
promo NUMBERS stayed blank. Two stacked root causes, both verified against
the raw API, not assumed: (a) `search_candidates()` silently STRIPS any
slash-less number-shaped token via `_NUM_RE` before the query ever reaches
TCGplayer — `"Victini XY117"` was silently becoming a bare `"Victini"`
search; (b) TCGplayer's own relevance ranking buries promos deep — Victini's
real XY117 card is present in TCGplayer's own results but only surfaces
around position ~40; invisible at the default `size=12` (confirmed absent
at 12 and 30, present at 50).
**Fix:** when Layer E narrows to a name but can't pick ONE number among
2+ real candidates, run one targeted `size=50` search by name and pull out
EXACT number matches — safe because this is a confirm-a-known-number
lookup, not a relevance-ranked discovery search.
**Mistake #3 (self-introduced, caught same session):** the first version of
this fix prepended found candidates ONE AT A TIME inside the loop — fixing
Meloetta's 2nd candidate (XY193) pushed her 1st (XY120) out of the eventual
top-5 slice. **Fix:** collect all ambiguous hits FIRST, dedupe, place them
all at the front in one pass, THEN append the rest — guarantees every
known ambiguous candidate survives truncation regardless of merge order.
**Also fixed:** the dashboard's binder route was unconditionally discarding
`candidates` from the JSON response (`ident.pop("candidates", None)`) —
even when a card couldn't be pinned to one printing, so the UI had nothing
to show but a bare "#?". Now candidates are kept exactly when ambiguous,
the binder pocket shows "N possible printings — tap to pick" instead of a
dead end, and the tap renders the SERVER'S guaranteed candidates directly
— re-searching from the tap would silently re-lose the size=50 fix, since
the plain `/api/valuator/search` route doesn't carry it.
**Guard:** manual live verification (documented in this session; the API
call is non-deterministic enough that a hardcoded regression test would be
flaky — the structural fix is what's covered, not one exact card's result).

### L31 — "Confidence %" hid inference; replaced with Evidence Levels + explicit failure reports (2026-07-17)
**Problem:** the system reported cards like `M Manectric-EX 024a/119 — 90%`
and `Snorlax XY179 — snapped`. The number is CORRECT (verified: it's the
only real printing within 1 edit of the misread), but the output presented
it identically to a card whose number was read letter-for-letter off the
card. A confidence percentage collapsed two different epistemic states
(directly observed vs. logically forced) into one indistinguishable number.
**Cause:** the identification pipeline tracks `via` (`"local index snap"`,
`"unique number match"`, `"visual read (assistant eye)"`, `null`) but the
user-facing output never surfaced it — only a rounded percentage did.
**Solution — adopted `DIRECTIVE.md` as governing standard, replacing 0-100%
confidence with 5 Evidence Levels:**
- **A — Verified:** every feature (artwork, HP, attacks, ability, set
  symbol, number, language, holo) directly read. Zero inference.
- **B — Human Eye Verified:** OCR failed; assistant's manual visual read
  succeeded and is exact (`via: "visual read (assistant eye)"`).
- **C — Catalog Forced:** OCR got a fragment; exactly one catalog candidate
  fits it (`via` contains `"snap"`, `"unique number match"`,
  `"local index"`, `"number-variant match"`, `"attack names"`,
  `"fingerprint"`). Must state the forcing logic, not just the number.
- **D — Partial:** name known, printing not. Never final.
- **E — Unknown:** insufficient evidence; triggers the Required Failure
  Report (which feature is missing, would another angle/OCR pass/UV/less
  glare/different language DB/a scan instead of a photo solve it).
**Retroactively applied** to the two live datasets as the first real test
(see chat log 2026-07-17): 5 lot cards + 2 shop cards graded **B** (Victini,
Meloetta, Magearna, Manaphy, Weavile/Excadrill/Stoutland/Wishiwashi binder
pages; Coalossal, Rota's Mime Jr.); 3 lot cards graded **C** with the
forcing logic now stated explicitly (M Manectric-EX 024a/119, Snorlax
XY179, Volcanion-EX 26/114 — each is literally the directive's own
worked example of what NOT to present bare). The rest of the pre-directive
dataset (52 cards) is graded provisionally **A/C by `via`-field proxy only**
— it predates evidence-chain logging, so a full per-feature re-audit
(artwork/HP/attack/ability/set-symbol/language/holo, not just name+number)
has NOT been run on it yet. That full retroactive audit is open work,
not assumed done.
**Detect automatically next time:** any card whose `via` is non-null but
whose output doesn't carry an Evidence Level tag is a Rule-1 violation —
silent inference. `tests.py` should assert every `identify()` result
includes an `evidence_level` key before this is considered closed in code
(not yet built — currently DIRECTIVE.md + this entry are documentation-only;
the pipeline itself does not emit Evidence Levels yet).
**Guard:** none yet — this is the open item. Next build step: add
`evidence_level` + `evidence_chain` fields to `identify()`'s output schema
in `profile_dataset.py`/`folder_dataset.py`, surface them on the dashboard,
and write `tests.py` assertions that reject any result missing them.
**Update (same day):** built. `evidence.py` + pipeline wiring + dashboard
badges + 9 tests + auto Failure Database (`FAILURES.md`). See L32 for the
first bug the new standard caught in its own first full run.

### L32 — the promo-preference heuristic was a prior, not evidence (2026-07-17)
**Mistake:** when Layer E (attack names) narrowed a card to one species
with MULTIPLE real printings and no directly-read number, identify()
"preferred the promo-format token" among the candidates and adopted it
as the number. In the full-directive re-audit this silently picked
**SM38** for an Incineroar-GX whose footer plainly reads **27/149**, and
**TG16** for a Mimikyu V that is **068/172** — both caught the same day
by eye-adjudication of the actual photos (2/2 wrong). The heuristic's own
comment claimed it was safe "when every OTHER card in this same photo
also reads as a promo" — but that context condition was NEVER CODED; it
fired unconditionally on standalone singles.
**Rule:** a number that was not read (directly or by snap) may only be
adopted from Layer E when the species has EXACTLY ONE candidate printing.
Multiple printings + no read = Level D with candidates exposed for the
eye-gate — never a heuristic pick. (This is the directive's mission
statement in code: an uncertain answer with a complete evidence trail
beats an unjustified high-confidence prediction.)
**Also caught in the same re-audit:** a process-hygiene failure — a
stopped background job's Python child survived and raced the corrected
re-run on the same JSON, interleaving stale watermark-less results with
good ones. Verify the actual saved state, never the log line.
**Guard:** `test_attack_number_needs_single_printing` (tests.py).

### L33 - catalog uniqueness is not contradiction search (2026-07-17)
**Mistake:** the first evidence engine graded a picked catalog product without
searching for real printings that could fit the same OCR. Mega Camerupt
`XY198a` had `XY198` suffix neighbors; M Mewtwo `63/162` had `64/162` one
OCR slip away; identical collector numbers exist across unrelated sets.
**Rule:** before A/B/C, independently widen by exact/normalized/promo/suffix/
one-slip number plus name anchors and try to disprove the chosen printing.
Multiple unresolved exact-number products are D; OCR-neighbor alternatives
are C; A requires that the search ran and survived. Every result stores the
strongest alternative, exclusions, limitations, and overturn condition.
**Guards:** `TestCandidateCollisionAnalyzer` and
`TestCollisionEvidenceIntegration`.

### L34 - Coverage is not Confidence; absent providers are not negative evidence (2026-07-17)
**Mistake:** `confidence` was literally confirmed evidence steps divided by
ten. It measured how many providers ran, not how likely the selected printing
was. An unimplemented holo detector therefore looked like evidence against a
correct card.
**Rule:** `evidence_coverage` is the confirmed-dimension count;
`provisional_prediction_confidence` is a separate transparent rules score
driven by direct reads, catalog agreement, collision results, snaps, and slab
risk. Missing HP/ability/set-symbol/holo providers affect Coverage only.
Artwork perceptual hash is local-only, bounded, and adds Coverage but +0 to
prediction until calibrated. **Guards:** `TestEvidenceProviders`.

### L35 - re-audits are transactions; old evidence must not become stale truth (2026-07-17)
**Mistakes:** a stopped audit could leave only one dataset migrated; a renamed
lot image broke path lookup; fresh OCR temporarily lost the plainly visible
Blastoise `22/108` and Manectric `024a/119`; cached inferred `Pikachu` tried to
override a fresh direct read of `Detective Pikachu`; durable eye-read cards
wasted minutes repeating deep OCR before restoring the same result.
**Rules:** checkpoint after each card, write datasets only after both finish,
rebuild failures atomically, resolve current/renamed/legacy paths, preserve an
exact human read as B, reuse a cached-number inference only when the exact
number repeats, and force live identification when fresh direct name text
conflicts or refines the old inference. Reports compare against committed
baseline and separately show identity and level changes.
**Guards:** `TestReauditHandoffEdges`.

### L36 - a valid-looking footer is not a real printing (2026-07-17)
**Mistake:** the supplied 2x2 binder photo OCR'd Stoutland `248/236` as the
syntactically plausible `240/250`. With no exact catalog product, the engine
still left it at C. That is not catalog forcing; exact printing is unproven.
**Rule:** outside a human eye read, no exact API or widened-local catalog
product means D even when the string looks like a collector number. A local
exact product can corroborate the catalog step, but uniqueness alone never
proves the decision. **Guards:**
`test_valid_looking_non_catalog_footer_stays_partial` and
`test_exact_local_catalog_product_corroborates_without_api_candidate`.

### L37 - whole-image OCR failure does not mean a phone photo holds one card (2026-07-17)
**Mistake:** dashboard binder mode required 3 readable whole-image names. The
real 720x1280 Weavile/Excadrill/Stoutland/Wishiwashi photo produced zero names
and one bad footer, so four cards rendered as one Level-E result even though
the existing crop pipeline could name every pocket.
**Rule:** for a narrow portrait with fewer than three whole-image names, run
one bounded 2x2 probe and enter binder mode only when 3+ cells contain direct
name/number evidence. This avoids treating every tall single card as a binder.
Keep unresolved candidates; only A/B pockets may discard them.
**Guard:** `TestBinderDashboardFallback` plus live upload of the supplied photo
(`multi=True`, four correct names; ~186s remains a performance limit).

### L38 - direct partial name text is independent evidence, but only within its scope (2026-07-17)
**Mistake:** `Mew` refined to `Mew V`, `Hydreigon` refined to
`Hydreigon-EX`, and `Zoroark` refined to `Zoroark-GX` were treated as if the
names came entirely from their numbers. Unrelated Wyrdeer/Hop/same-number
cards survived as false collisions. Separately, catalog display text such as
`Altaria EX (Full Art)` collided with `Altaria-EX`, its own product.
**Rule:** a directly read species fragment excludes candidates that cannot
contain it, but does not exclude mechanic variants that still contain it
(`Altaria` cannot rule out `M Altaria-EX`). Strip parenthetical product labels
before identity comparison. **Guards:** partial-name and catalog-annotation
tests in `TestCollisionEvidenceIntegration`.
