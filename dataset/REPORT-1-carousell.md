# Report 1 — Yujin's Pokestop: 20 listings identified IMAGE-FIRST
2026-07-17 · system V0.7 (`6694265`) · full evidence: `dataset/carousell_profile.json`

**The rule of this task:** identification from IMAGES ONLY. Titles/descriptions
were never read by the identifier — they were used exactly once, at the end,
to grade the answers.

## Summary

| Metric | Result |
|---|---|
| Listings processed | **20/20** |
| Identified image-first (name) | **18/20** |
| Exact printing (collector number) image-first | **17/20** |
| Verified against listing titles | 18/18 names agree |
| Images BEAT the metadata | **3 listings** (see below) |
| Partial (printing read, name ambiguous) | 1 — Coalossal |
| Currently unidentifiable from images | 1 — Rota's Mime Jr. |
| Identification runs it took | 5 (each failure → a permanent layer, L21-L25) |
| Tests after this task | 50/50 (was 43) |

Where the images beat his own titles:
- **L15 Korean Raichu GX** — title has no number; the footer reads `SM3+ 079/072 HR`
  (Korean printings mirror the Japanese set numbering) → exact printing found.
- **L18 JP Black Kyurem** — title has no number; resolved to `045/059` (BW6 Freeze Bolt).
- **L5 Chespin** — title says "034/X-P" (typo); the card actually reads **034/XY-P**.

## Individual reports

Evidence-path key: **read** = OCR'd directly · **vote** = same value read on
multiple photos · **snap** = Layer-B corrected against real printings ·
**fp** = attack-damage fingerprint · **dex** = National-Dex number ·
**unique#** = exactly one catalog product carries the read number.

| # | Image-first identification | Path | Conf | Title check |
|---|---|---|---|---|
| 1 | **Pikachu ex** #063/193 (Paldea Evolved), EN | name read ("Pikachue"/"Pikachuex" → Layer-C snap), footer vote | 95% | ✅ exact |
| 2 | **Charizard ex** #006/165 (SV 151), EN | name + footer read clean | 95% | ✅ exact |
| 3 | **Lillie's Clefairy ex** #173/159 (Journey Together FA), EN | full name + footer read | 95% | ✅ exact |
| 4 | **Japanese Mega Manectric ex** #077/063 SR | **fp** {120,200+}+HP220-retry → unique; footer read | 95% | ✅ exact |
| 5 | **Japanese Chespin promo** #034/XY-P | promo footer ×3 photos + **unique#**; fp correctly refused ({10,20} too generic) | 90% | ✅ (fixed his typo) |
| 6 | **M Camerupt-EX** #XY198a promo, EN | glued name "MCameruptEX" → Layer-C; promo number read | 95% | ✅ exact |
| 7 | **Japanese Pikachu promo** #197/SV-P | promo footer ×4 photos + **unique#** + dex NO.0025 corroborates | 90% | ✅ exact |
| 8 | **[PARTIAL]** printing #117/100 JP UR read; name unresolved | footer read; JP name unreadable; fp had 1 damage; 5 same-number candidates, none Coalossal | 40% | ⚠ title says Coalossal — catalog probe confirms Coalossal 117/100 JP EXISTS (s2a); needs the eye gate or a set-code close-up |
| 9 | **Japanese Staraptor** (D&P holo, LV.54) | **dex** NO.398 → Staraptor; JP D&P-era cards print NO collector number | 85% | ✅ name (title has no number either) |
| 10 | **Japanese Combusken promo** #065/PCG-P (Meiji) | promo footer ×3 + **unique#** | 90% | ✅ exact |
| 11 | **Japanese Combee promo** #081/DP-P (Meiji) | **dex** NO.415 + footer read | 90% | ✅ exact |
| 12 | **[UNIDENTIFIED]** — see below | 6 photos: only "HP50" + JP body text ever resolves | — | title: Rota's Mime Jr. 086/PCG-P (product exists on TCGplayer) |
| 13 | **Japanese Croagunk promo** #032/DP-P (McDonald's) | **dex** + footer read | 90% | ✅ exact |
| 14 | **Weakness Policy** #164/160 (Primal Clash secret) | name + footer read (Trainer path) | 95% | ✅ exact |
| 15 | **Korean Raichu GX** #079/072 HR | footer "SM3+079/072HR" + **unique#** (KR mirrors JP numbering) | 90% | ✅ name; number is NEW info |
| 16 | **M Tyranitar-EX** #43/98 (Ancient Origins) | glued "MTyranitar" → Layer-C; read 13/98 → **snap** 43/98 (only real printing 1 edit away) | 90% | ✅ exact — snap verified right |
| 17 | **M Beedrill-EX** #XY158 promo | glued "MBeedrillEX" → Layer-C; promo number read | 95% | ✅ exact |
| 18 | **Japanese Black Kyurem-EX** #045/059 (BW6) | **fp×number**: {60,150}+HP180 ties 4 cards → crossed with #045/059 catalog matches → exactly one | 90% | ✅ name; number is NEW info |
| 19 | **Hydreigon-EX** #103/108 (Roaring Skies FA) | glued "HydreigonEX" → Layer-C; footer read | 90% | ✅ exact |
| 20 | **Naganadel & Guzzlord-GX** #158/236 (Cosmic Eclipse) | two-line TAG-TEAM name join + footer read | 95% | ✅ exact |

## The two hard cases (per task rules: WHY, and what would resolve them)

### L8 — Coalossal 117/100 (JP secret rare) — printing read, name not
- **Why:** the name is printed in Japanese (no Latin name to read); the gold
  UR footer yields `117/100 UR` but no set code resolved; the fingerprint got
  only one damage (130) — below the 2-damage floor; TCGplayer text-search on
  "117/100" returns five DIFFERENT cards with that number (Leon, Boltund VMAX…),
  and the JP Coalossal product doesn't text-match its own number.
- **Resolves it:** one close-up of the bottom-left footer (set code `s2a` +
  number = unique global ID — the proven JP path), or the dashboard eye gate.
- **Verified:** `Coalossal 117/100 · Pokemon Japan` exists in the catalog, so
  the listing title is plausible — but image-first honesty means we don't claim
  it without image evidence.

### L12 — Rota's Mime Jr. 086/PCG-P (McDonald's vintage) — unidentified
- **Why:** across all 6 photos the ONLY stable reads are `HP50` and JP body
  text. The name is Japanese ("ロータの…"), there's no dex strip in frame, no
  set code, and the `086/PCG-P` footer never resolves at the photos'
  resolution/blur even under deep-zoom scans of every photo. PCG-era promos
  also predate the fingerprint index's English card pool (no EN equivalent —
  a real coverage boundary for Layer-fp).
- **Resolves it:** one footer close-up photo, or one Pokédex-strip photo
  (dex NO.439 → Mime Jr. instantly via Layer D).
- **Verified:** `Rota's Mime Jr. - 086/PCG-P · Pokemon Japan` exists on
  TCGplayer — the listing is real; only the PHOTOS are insufficient.

## What the system learned (L21-L25 — each now a permanent test)

1. **L21 · Layer C:** a guessed name must be a REAL card name (4,428-name
   vocabulary; snap unique near-misses, reject everything else).
2. **L22 · Watermark defense:** seller overlays repeat across LISTINGS, not
   across one listing's photos — and "Pokestop" is literally a real card
   (PokéStop, Pokémon GO set), so only cross-listing frequency tells them apart.
3. **L23 · Fingerprint honesty:** 2 generic damages = coin flip ("Arbok"/"Lucario"
   incidents); corroboration + clear winner required; a corroborated TIE is
   still evidence when crossed with the collector number ("fingerprint × number").
4. **L24 · Promo footers + Layer D:** `NNN/XX-P` letter denominators are
   collector numbers (6 of these 20 were invisible before); JP vintage prints
   the National Dex number — a species ID when nothing else reads.
5. **L25 · Snap needs a strong name:** a base-name match must never drive
   number "correction" (the Pikachu ex 063→062 backward-snap); vote evidence
   across all photos, prefer the most specific validated read.
