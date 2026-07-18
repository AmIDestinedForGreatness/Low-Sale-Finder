# Next unit: perspective-normalize card crops before hashing (make hash-first actually HIT)

## Why this unit exists

Yujin found `github.com/NolanAmblard/Pokemon-Card-Scanner` and asked us to
"level up" from it. Read what it actually does — it identifies cards in
seconds with NO OCR at all:

1. Find the card contour in the photo (edges -> biggest rectangle contour).
2. **Find the 4 corners and perspective-warp the card to a flat canonical
   rectangle** — like a phone document scanner flattens a page.
3. Perceptual-hash the flattened card and look it up in a hash database
   (they store 4 orientation variants per card).

We already have steps 1 and 3: `folder_dataset.detect_card_regions()`
(contours) and `fingerprints.sqlite`'s `visual_phash`/`visual_dhash` (19,705
cards) with `VisualCatalogProvider.match_image()` (now numpy-vectorized,
~0.02s per lookup).

**What we're missing is step 2, and it's why our hash lookups miss.** We
hash raw axis-aligned bounding-box crops: tilted card + sleeve edges +
background + neighbor slivers all pollute the hash. The catalog hashes were
computed from clean flat reference scans (via `providers.artwork._art_region`).
A tilted noisy crop vs a clean flat scan won't land within the match gate.
Every cell on today's real 12-card test page missed the catalog for exactly
this reason, forcing the slow OCR path (~104s/weak cell for deep scans).

Confirmed today (see AGENT-RELAY.md 2026-07-18 evening entries): trimming
the OCR deep-scan loses real identifications — OCR cost cannot be cut
safely. The only way to make multi-card pages fast is to not need OCR for
most cells. That's this unit.

## The task

In `folder_dataset.py` (or a small new module if cleaner):

1. **Corner detection per card region.** For each contour that
   `detect_card_regions()` accepts, get the actual quadrilateral corners —
   `cv2.approxPolyDP` on the contour (epsilon ~2% of perimeter) for a clean
   4-point fit; fall back to `cv2.minAreaRect` box points when approx
   doesn't yield exactly 4 points. Order the points consistently
   (top-left, top-right, bottom-right, bottom-left).

2. **Perspective warp** each card to a canonical flat rectangle with
   `cv2.getPerspectiveTransform` + `cv2.warpPerspective`. Target size:
   keep the real card aspect ratio (63:88) — e.g. 630x880. This is the
   NolanAmblard "scanner" step.

3. **Hash the WARPED image** through the same pipeline the catalog used
   (`providers.artwork._art_region` -> phash/dhash) and look it up with
   `VisualCatalogProvider.match_image()`. Wire this into
   `probe_contours()`'s existing hash-first block (it already exists —
   currently hashing the raw crop; hash the warped version instead, or
   both, warped first).

4. **Orientation robustness:** a binder card can be upside down. Cheap
   version of NolanAmblard's 4-variant trick: if the warped hash misses,
   try the 180° rotation of the warped image before falling back to OCR
   (90/270 aren't needed — the warp already normalizes to portrait).

5. **Do NOT loosen the match gate to force hits.** `max_distance` /
   `nearest_slack` stay as they are. If normalization alone doesn't produce
   hits, report that honestly — a false identification is worse than a slow
   one (system rule L20).

## Acceptance criteria

1. **Primary test, the real photo:** `uploads/card_1784372012.jpg`
   (12-card JP binder page). Report per-cell: warped-hash hit or miss, at
   what distance, vs the current all-miss baseline. Any confident hit MUST
   be verified correct against the visible card in the photo (Yujin can
   eye-check; the Blastoise and Mega Froslass ex are known-identified by
   OCR already — if the hash disagrees with a Level-A OCR identity, that's
   a red flag to investigate, not to ship).
2. **Timing through the real Flask route** (test client), cold cache, same
   photo, before/after. Every hash hit skips that cell's OCR+deep-scan
   (~30-100s saved per cell) — report the real number, no projections.
3. **0/199 false-positive check** on `dataset/images` through
   `probe_contours()` directly — unchanged requirement.
4. Full suite green (`E:\python.exe tests.py`, currently 122/122 + add
   tests for corner-ordering and the warp with a synthetic quadrilateral).
5. `reaudit.py` (no time cap — it needs ~6-8 min): 0 identity changes.
6. Honest failure report if warping doesn't produce hits: include 2-3
   sample distances (warped vs raw crop) so the next session can judge
   whether the gap is alignment (fixable) or catalog coverage (the 739
   upstream-404 cards, not fixable locally).

Local commit only, never push. Post real findings to AGENT-RELAY.md,
numbers not adjectives.

## Context files

- `folder_dataset.py` — `detect_card_regions()`, `probe_contours()` (the
  hash-first block to modify)
- `providers/visual_catalog.py` — `match_image()` (vectorized; reuse, don't
  duplicate)
- `providers/artwork.py` — `_art_region`, hashing helpers the catalog used
- `AGENT-RELAY.md` 2026-07-18 evening — full history of today's binder
  work, including why the OCR-trimming approach was tried and reverted
