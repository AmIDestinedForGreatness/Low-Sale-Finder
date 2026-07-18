# Next unit: make `probe_contours()` hash-first instead of OCR-first

## Context

`folder_dataset.probe_contours()` (added 2026-07-18, see AGENT-RELAY.md CC entry
same date "Two units shipped") detects card-shaped regions on mixed-set binder
pages via OpenCV contour detection, then runs full RapidOCR on each detected
region to identify it. It's wired into `app.py`'s `/api/valuator/ocr` route as
a third fallback, only tried when the existing text-based signals
(`should_probe_grid`) find nothing.

**It works — verified on the real failing photo, 0/199 false positives on the
known single-card dataset, full suite green.** But it's slow: ~170s for a
4-card upload in live route testing. Root cause, verified directly (not
assumed): RapidOCR itself takes ~29s per whole-image OCR call on this machine
for a text-dense photo. Threading the 4 cell OCR calls barely helped (171.6s
vs 167s sequential) — onnxruntime isn't giving real parallelism here.

Yujin surfaced two real projects mid-session that do this differently:
- `github.com/NolanAmblard/Pokemon-Card-Scanner` — OpenCV contour detection
  (same technique we independently built) to find card regions, then **pure
  perceptual hashing** (average/whash/phash/dhash via the `ImageHash`
  library) against a card database. **No OCR at all.**
- `github.com/prateekt/pokemon-card-recognizer` — OCR + a trained classifier,
  reference hashes per set, GPU-accelerated.

## The task

We already built the hash infrastructure today, it's just underused for this
path:
- `fingerprints.sqlite`'s `fp` table has `visual_path`, `visual_phash`,
  `visual_dhash` columns — 19,705 of 20,444 cards hashed (the 739 gap is
  upstream `images.pokemontcg.io` 404s for the newest "Mega Evolution" era
  sets, not fixable from our side, see relay entry).
- `providers/visual_catalog.py`'s `VisualCatalogProvider` already does
  weighted phash/dhash matching with a `nearest_slack` anti-false-positive
  gate. Right now it's wired as **corroborating-only** evidence elsewhere in
  the pipeline.

For `probe_contours()` specifically: after cropping each detected card region,
compute its perceptual hash (reuse `providers.artwork._art_region`/`phash`/
`dhash`, same functions `build_visual_catalog.py` already uses) and look it up
against the catalog FIRST. Hash comparison is a lookup, not neural inference —
should be low milliseconds per cell instead of ~30s.

- If the hash match is confident (tight distance, matches
  `VisualCatalogProvider`'s existing `nearest_slack` philosophy — don't
  invent a new threshold, reuse or directly call into the existing gate
  logic), use it as the identification directly, skip OCR on that cell
  entirely.
- If the hash match is absent/ambiguous, fall back to the current OCR path
  for that cell only (not a global fallback — per-cell, so a mix of
  hash-hit and hash-miss cells in the same upload is fine).
- Keep the existing majority-evidence acceptance gate in `probe_contours()`
  (currently `signals >= max(2, ceil(0.75*N))`) — a confident hash match
  should count as a signal exactly like a confident OCR read does now.

## Acceptance criteria (same standard as everything else in this repo)

1. Real speed measurement, not a guess: time the SAME real photo
   (`uploads/card_1784362145.jpg`) through the actual `/api/valuator/ocr`
   Flask route (test client, not a script that skips the route) before and
   after, report both numbers.
2. Zero regression: full suite (`E:\python.exe tests.py`) stays green, AND
   re-run the 199-image false-positive check directly through
   `probe_contours()` (not just box-counting) — must stay 0/199.
3. `reaudit.py` on both accepted datasets — 0 identity changes (evidence
   level changes are fine and expected to note, identity changes are not).
4. Don't invent a second hash-matching implementation — reuse
   `VisualCatalogProvider`'s matching/threshold logic rather than
   duplicating it with different numbers; if that means refactoring a shared
   helper out of `providers/visual_catalog.py`, that's the right call, not a
   copy-paste.
5. Honest report either way: if the hash-first approach doesn't actually
   move the needle on THIS specific photo (e.g., its 4 cards happen to fall
   in the 739-card upstream-404 gap and have no hash to match against),
   say so plainly rather than reporting a synthetic win. Test against a
   couple of the OTHER real single-card photos in `dataset/images` that DO
   have hashes to confirm the hash-hit path itself is fast and correct, even
   if this specific photo can't fully exercise it.

Local commit only, don't push. Post real findings to AGENT-RELAY.md the same
way every other unit this session has been — evidence-based, numbers not
adjectives.
