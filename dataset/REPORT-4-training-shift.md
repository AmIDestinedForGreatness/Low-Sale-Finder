# Report 4 — the training shift (7/17, ~1:30-4AM) · V0.8.1 → V0.9

His orders: *"Figure out why u can't identify the ones from the lot and
Carousell. Improve our system. Gather, identify cards you can scrape.
Learn how binder identification should work."* Every failure was
autopsied; each became a permanent layer.

## The overnight lot — final score

| Metric | at Report 2 | **now** |
|---|---|---|
| Cards named | 36/38 | **39/39** (photo set held 39 cards — one photo was a hidden two-card pair) |
| Exact printings | 28 | **29** |
| Identity-verified prices | 15 (₱13.4k) | **27 (₱16,957 market / ₱21k+ NM-list)** |
| Binder cards named | 7/8 | **8/8** (Weavile cracked; Meloetta via attack names) |

New IDs this shift: Mimikyu V 068/172 · Lycanroc-GX 82/181 · Incineroar-GX
27/149 · Hoopa-GX 96/181 · Zoroark-GX 53/73 · Mew V 069/189 · Pikachu VMAX
SWSH286 · Altaria-EX FA 123/124 · Alolan Ninetales-GX 22/145 · Scizor-EX
119/122 · **Snorlax XY179** (read "XY79"; snapped against Snorlax's real
printings) · **Volcanion-EX 26/114 + Golem-EX 46/83** (one landscape photo,
two cards — the system had fused Golem's name with Volcanion's number).
Folder re-renamed accordingly (proof format kept).

## New identification layers (V0.9 = 13 layers total)

1. **Layer E — attack/ability names** *(the binder breakthrough)*: attack
   names are the big readable English text OCR nails even on blurry cell
   crops, and they're near-unique per species ("Victory Ball" exists only
   on Victini; "Soprane Wave" fuzzy-matches Meloetta's Soprano Wave).
   31,908 attack/ability names indexed.
2. **Local-index join**: when no search candidate carries the read number,
   join it against the local index's printings of the name + mechanic
   variants — unique owner IS the card (Scizor #119/122 → Scizor-EX);
   promo tokens snap within the family (XY79 → XY179). Index rebuilt with
   full `num/total` collector numbers.
3. **Mechanic-variant retry**: OCR drops stylized V/GX glyphs; suffixed
   searches recovered 8 exact IDs in one pass.
4. **Candidate consensus** (all number-matches share one name = the name)
   and **side-by-side pair split** (2 names in a landscape frame = 2 cards).
5. **BINDER MODE on the dashboard (V0.9)**: drop a binder-page photo →
   auto-split → every card identified at once, tap a card to value it.
   Cells upscale 2× (quadrant crops halve resolution); deep-scan gained
   bottom-RIGHT + 4× zoom regions (XY-era numbers sit bottom-right).

## Fresh training scrape (20 live Carousell listings, graded vs titles)

Result: **6 exact / 8 partial / 0 wrong / 6 correctly-skipped** (bulk lots,
sleeves, a Switch game — not single cards). Zero hallucinated
identifications: everything claimed was right or honestly partial.
Catches that became rules:
- **Seller trailer photos**: one seller appends the same Mimikyu ex promo
  shot to every listing — it out-voted the real card until the name vote
  became frequency-first (read on more photos > longer name).
- **Gallery numbering** (TG26/TG30, GG12/GG70) — letters both sides, now a
  first-class number format, with OCR-glue trimming (WGG12→GG12).
- **Graded slabs are region-ambiguous**: a Beckett'd CHINESE Pikachu promo
  #004/SV-P unique-matched the JAPANESE SV-P 004 (Dondozo). Slab detected
  → number-only name adoption disabled. (PSA10-style glued tokens count.)
- Honest limits found: JP TRAINER cards (no attacks, no dex, JP name) stay
  number-only; multi-card LISTINGS need the binder split ported into the
  listing pipeline (folder + dashboard have it).

## Roadmap confirmed by Yujin tonight
Identification accuracy first → then **card condition comparison** (L17
whitening-first doctrine). Logged.
