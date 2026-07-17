# Yujin's Pokestop — Progress

> "We are nowhere near, but we are closer than where we were yesterday." — 2026-07-16

The compounding rule: every mistake becomes a permanent test (`tests.py`) and a
written lesson (`LESSONS.md`). Current: **53 tests, 29 lessons.**

## Version history

| Ver | Shipped | What |
|---|---|---|
| V0.1 | 7/15 | Status dashboard: ON/OFF heartbeat, 10-min countdown, recent sends |
| V0.2 | 7/15 | Dead-man Discord ping, price-drop alerts, phone LAN access, stats |
| V0.3 | 7/15 | Logo hero, cards-only filter, restart buttons (watchlist/grails removed) |
| V0.4 | 7/16 | GMT+8 upload times, FB groups in recent list, link-click fix, no stats cards |
| V0.5 | 7/16 | **Card Valuator**: photo → OCR → confirm → real-sold valuation |
| V0.6 | 7/16 | Build identity badge (#git-sha) + stale-page auto-detector |
| V0.7 | 7/17 | **The dataset run**: all 20 shop listings identified image-first (19/20). New layers: name vocabulary snap (C), dex number (D), fingerprint ambiguity guard + tie-break, promo footers, watermark defense, `profile_dataset.py` |
| V0.8 | 7/17 | **Overnight (the overnight lot, 38 cards)**: LINK AS SOURCE on the dashboard (paste a Carousell listing URL → photos fetched → identified); orientation auto-righting; binder-page 2×2 splitting; squashed-form name matching; variant-letter numerators (24a/119); language-claim discipline; identity-strict lot pricing; `folder_dataset.py` |
| V0.9 | 7/17 | **Training shift**: Layer E attack-name ID (31,908 indexed — the binder breakthrough); local-index join + full collector numbers; mechanic-variant retry; candidate consensus; pair split; BINDER MODE on the dashboard; slab region-ambiguity guard; gallery numbers (TG/GG); 20-listing live training set graded 6 exact/8 partial/0 wrong. Lot final: 39/39 named, 27 priced (₱16,957) |

## The system (4 always-on processes)

1. **Carousell feed** (`main.py --feed`) — every new TCG listing → Discord;
   categories color-coded; sold/reserved edits; price-drop alerts;
   "♻ resurfaced" tag on bumped old posts; mismatch-guarded deal alerts
2. **FB groups feed** (`fb_feed.py`) — 15 PH TCG groups (headless burner);
   sale/timed-auction/bidding split; auction channel; 10-min end reminders
   (react-to-track); auto-delete ended auctions
3. **Discord bot** (`bot.py`, Pokestop#6681) — react-to-track,
   /dashboard /help /status + owner-only "." commands
4. **Dashboard** (`app.py`, V0.6) — live status, merged recent list,
   Card Valuator, webhook manager, self-identifying builds

## Card Valuator — identification stack (the core IP)

Photo in → exact printing out:

1. **RapidOCR** (local onnx; reads 9px footers Windows OCR can't; JP-safe)
2. **Name guess** — junk-shape filtering (proper-case words; glued Mega/EX
   forms allowed: MCameruptEX, HydreigonEX; two-line TAG TEAM names joined)
3. **Layer C: name vocabulary snap** — a name must be (or snap uniquely to)
   one of 4,428 REAL card names (Pikachue→Pikachu, arizardex→Charizard);
   watermark/garbage text is rejected so deeper layers take over (L21)
4. **JP footer path** — set code + collector number = unique global ID
   ("sm12a 016/173" → exactly one card); promo LETTER footers too
   ("034/XY-P", "197/SV-P") — unique catalog match = the card (L24)
5. **Attack fingerprint** — damage numbers (standalone regions only) + HP
   vs local index of 20,324 cards; ambiguity-guarded (corroboration + clear
   winner, L23); corroborated ties break against the collector number's own
   catalog matches ("fingerprint × number")
6. **Layer D: dex number** — JP vintage prints "NO.398" in the Pokédex
   strip → species ID when nothing else is readable (L24)
7. **Deep-scan** — zoomed region crops × contrast variants for glare photos
8. **Layer-B constraint snap** — the number must be a real printing of the
   identified card; unique 1-edit errors auto-correct (015/173→016/173),
   only when the name is certain/specific (L25), reported honestly
9. **Grid** — cards only (no boxes/merch), nearest-to-farthest, JP-first
   when the card is non-English, language-prefixed names
10. **The eye gate** — side-by-side confirm (your photo vs 874×1214 scan),
    click-zoom with level slider, stamps/1st-ed check. **The user's eye is
    the final identification authority.**

## The dataset (`dataset/carousell_profile.json` + `profile_dataset.py`)

His task (7/16): identify all 20 shop listings from IMAGES ONLY — titles
used only to verify afterward. Result: **19/20 identified image-first**
(18 with exact printing), 1 partial (Coalossal: printing read, name
ambiguous), 1 unreadable (Rota's Mime Jr. — footer never resolves in any
photo). In 3 cases the images beat the metadata (exact printings the
titles don't carry; one title typo corrected). Five identification runs,
each failure → a new layer (L21-L25). Batch watermark defense
(cross-listing token frequency) lives in the dataset pipeline; everything
else is shared with the dashboard valuator.

Valuation: TCGplayer market + latest real sales (per-condition medians,
labeled real vs estimated) + sales-velocity confidence (HIGH/MED/LOW) +
PH sell suggestion (× factor) + steal price (≤72%).

## Pricing chain (feeds)

manual CSV → TCGplayer (strict number match, Mega-promo name variants) →
PriceCharting (specific-token matching only — L20). Coverage on his 20
Carousell listings: 19/20 (Raichu GX Korean = no public data anywhere).

## Known limits (honest)

- 810px uploads: 5/6 digit ambiguity is in the pixels (Layer-B absorbs it;
  original-resolution photos would eliminate it)
- Trainer/item cards have no attack fingerprint (name OCR carries them)
- Graded slabs: no dedicated path yet (PSA cert OCR = planned)
- Vintage (no set codes): untested
- FB comment reading (live current-bid): not built (embedded JSON, high risk)
- Korean cards: no public price data — ×0.65 JP heuristic unvalidated
- fingerprints.sqlite needs a rebuild when new sets release
  (`build_fingerprints.py`)

## Roadmap

- Composite pricer step 2: blended TCG+PC × PH factor (step 1/PC precision ✅ 7/16)
- PH price index from the sniper's own accumulated data (the real snipe engine)
- Slab path (cert OCR), vintage support, condition checker (whitening-first, L17)
- eBay/Shopee/Lazada as future data sources; FB Marketplace = his decision
