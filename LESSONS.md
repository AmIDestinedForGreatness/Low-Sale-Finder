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
