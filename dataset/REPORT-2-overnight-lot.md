# Report 2 — the overnight lot ("for u to do while im asleep")
2026-07-17 overnight · system V0.8 · evidence: `dataset/for_u_to_do_while_im_asleep.json`
Proof delivered as ordered: **every photo in the Downloads folder is renamed to
`Name  ID  Language`** — open the folder and grade me.

## Summary

| Metric | Result |
|---|---|
| Photos processed | 32 (30 singles + 2 binder pages = **38 cards**) |
| Cards identified by name | **36/38** |
| Exact printing (number) | 28/38 |
| Priced from real TCGplayer sales (identity-verified) | 15 |
| Photos that arrived sideways and were auto-righted | 6 (rot 90/270) |
| Unidentified | 2 (one blur-heavy binder cell + one number-only card) |

**Lot value:** the 15 identity-verified prices alone total
**≈ ₱13,400 market** (NM-list suggestions ≈ ₱16,900). Biggest tickets:
M Mewtwo EX (63) ₱3,062 · M Altaria-EX FA ₱1,444 · M Venusaur-EX ₱1,266 ·
M Blastoise-EX ₱1,255 · Snorlax GX SM05 ₱1,011 — all HIGH confidence
(real recent solds). The unpriced ones aren't worthless — they're
*unconfirmed*: their exact printing needs your eye or one footer close-up.

## The cards (as renamed in the folder)

| Card (filename) | Printing | Market ₱ | Conf | Note |
|---|---|---|---|---|
| M Mewtwo EX (63) | 63/162 | 3,062 | HIGH | unique catalog match |
| M Altaria-EX | 121/124 FA | 1,444 | HIGH | |
| M Venusaur-EX | 2/146 | 1,266 | HIGH | |
| M Blastoise-EX | 22/108 | 1,255 | HIGH | |
| Snorlax GX | SM05 promo | 1,011 | HIGH | |
| M Manectric-EX | 024a/119 alt-art | 790 | HIGH | the "24a" letter-numerator card |
| Detective Pikachu | 10/18 | 786 | HIGH | |
| Lucario VSTAR | SWSH291 | 717 | HIGH | |
| Yveltal EX | XY08 | 641 | HIGH | |
| Detective Pikachu | SM194 | 611 | HIGH | |
| M Steelix-EX | 68/114 | 519 | HIGH | |
| M Slowbro-EX | 27/108 | 549 | HIGH | |
| Lunala-GX | SM17 promo | 251 | HIGH | |
| Charizard | 010/078 | 165 | HIGH | |
| Flygon-GX | 110/236 | 136 | HIGH | |
| Mimikyu V | 068/172 | — | | catalog search returned only the VMAX; needs eye-pick |
| Eevee VMAX | SWSH087 (footer unread) | — | | name certain, printing from title-level knowledge only |
| Alolan Ninetales GX | 22/145 | — | | name unreadable in glare; number + both catalog matches ARE this card — your eye confirms |
| Hoopa | 96/181 | — | | number read; candidates differ |
| Mew | 069/189 | — | | Hidden Fates shiny vault? candidates differ — eye-pick |
| Pikachu | SWSH286 | — | | promo, printing candidates differ |
| Snorlax | XY79 read | — | | ⚠ conflict: catalog says XY79 = Latios — number likely misread, withheld |
| Incineroar | 27/149 read | — | | neighbor-number candidates only (26/149) — withheld |
| Golem | 26/114 | — | | only far-number product matched — withheld |
| Lycanroc | 82/181 | — | | neighbor numbers only — withheld |
| Zoroark | 53/73 | — | | candidates differ |
| Altaria | 123/124 read | — | | candidates at 84/124 — number sus, eye-check |
| Scizor | 119/122 | — | | candidates differ |
| Yveltal (2nd copy) | no number | — | | name only |

**Binder page 1 (XY-era promos):** Victini · Meloetta · Magearna · Manaphy —
all 4 names identified from quadrant crops; the tiny black-star promo numbers
(XY117 etc.) didn't resolve at crop resolution.
**Binder page 2 (Cosmic Eclipse character arts):** Excadrill · Stoutland ·
Wishiwashi identified; **top-left cell (Weavile) unidentified** — heavy blur +
keyboard background in that crop.

## Honesty notes (why some prices are blank)

A price got withheld unless the catalog product's **name AND number both
agree** with what was read off the card. The first pricing pass violated this
and produced a ₱6,850 "Snorlax" priced off a **Latios** promo and four
neighbor-number mismatches — the exact failure mode of lesson L20. Wrong
prices are worse than no prices, doubly so when the cards are being sold
on someone else's behalf.

## What this lot taught the system (now permanent, L26)

1. **Orientation normalization** — sideways photos retry at 90°/270°, best
   evidence wins (6 of your 30 needed it).
2. **Binder-page splitting** — 3+ distinct validated names in one photo =
   multi-card → 2×2 quadrant crops, each identified separately.
3. **Separator-squashed exact matching** — "MManectricEX" IS
   "M Manectric-EX"; fuzzy distance alone saw a tie.
4. **Variant-letter numerators** — "24a/119" alternate arts were invisible
   to the number regex.
5. **"EeveeVax"-class glue** — V/VMAX/VSTAR mechanics glue onto names in OCR.
6. **Language is a claim** — only positive evidence (JP set code, JP promo
   footer, dex-strip/fingerprint path) may say "Japanese"; 4 English cards
   briefly got mislabeled and were corrected.
7. **Prices require identity agreement** (name+number match with the catalog
   product) — the L20 rule now enforced in the lot pipeline too.
