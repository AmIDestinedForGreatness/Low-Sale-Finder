# NEXT-STEPS.md — active spec, save point for handoff (2026-07-17)

Repo: `C:\Users\Marvin\low-sale-finder` (GitHub: AmIDestinedForGreatness/Low-Sale-Finder)
Last shipped commit: `9b8f9d3` (V0.10.0 — Evidence Engine).
This file exists because Yujin flagged a session-limit risk mid-spec — if
work stops here, this is the FULL accepted spec to resume from, not a
summary. Do not re-derive it from chat; it's all here.

## Status: NOT YET BUILT. This is the accepted spec, verbatim intent.

Yujin's decision on the two open questions from V0.10.0's report:
1. **Cross-print collision check: build now, zero-cost, this iteration.**
2. **Artwork verification: "Cheap partial version"** — perceptual-hash
   ArtworkVerifier using only images already on disk (no scraping, no API
   cost), built as a swappable Evidence Provider, not a one-off.

## Terminology change (Yujin's call, adopt it)
Rename the verifier concept from "Verifier" to **Evidence Provider** —
more future-proof since a dimension (e.g. Artwork) may have multiple
backends over time (perceptual hash today, vision API later).

```
Evidence Providers
├── OCRProvider
├── NumberProvider
├── LanguageProvider
├── CatalogProvider
├── ArtworkProvider      <- build now (perceptual hash backend only)
├── ExpansionProvider    <- stub only, not_checked
├── HoloProvider         <- stub only, not_checked
└── (HP/Ability providers <- stub only, not_checked)
        │
        ▼
CandidateCollisionAnalyzer   <- build now, the main deliverable
        │
        ▼
Evidence Fusion Engine → Evidence-Based Decision
```

## 1. CandidateCollisionAnalyzer — the primary deliverable

New file: `collision.py`. NOT buried in identify()'s conditionals — a
distinct, independently testable component. Runs BEFORE evidence_level
and confidence are assigned (called from evidence.py's build_evidence,
or from identify() just before calling build_evidence — decide based on
what needs the widened candidate list).

**Signature:**
```python
def analyze(name, number, norm_number, language_evidence, set_evidence,
            card_type, attacks, abilities, existing_candidates) -> dict
```

**Returns:**
```python
{
  "collision_status": "none | possible | confirmed",
  "candidate_count": int,
  "competing_candidates": [...],   # full candidate dicts, not just names
  "evidence_shared": [...],        # which fields the competitors share
  "evidence_conflicts": [...],     # which fields distinguish them
  "evidence_missing": [...],       # what would resolve it if we had it
  "reason": "...",
  "recommended_evidence_level": "A | B | C | D",
}
```

**Widened search — for every proposed A/B/C result, search beyond the
first-picked product:**
- same collector number across ALL sets (not just the matched one)
- normalized number variants (leading zero, no-slash promo forms)
- suffix variants (a/b letter, alt-numbering)
- same or highly similar name, any language/region in the local catalog
- same attacks/abilities where indexed (valuator._atk_index() already
  has this — reuse it, don't rebuild)
Purpose is explicitly to find a CONTRADICTION, not more support — mirror
the phrasing Yujin used, this is adversarial by design, not confirmatory.

**Level rules (this changes evidence.py's level logic — read carefully):**
- Level A requires: fields directly read (existing rule) AND collision
  search found NOTHING competing AND enough distinguishing evidence
  exists to exclude alternatives found. "Unique in catalog" is NOT
  sufficient by itself anymore — collision search must have RUN and
  come back clean.
- If the printing was reached by eliminating competitors via INDIRECT
  evidence (not a direct read) → Level C, and the elimination logic
  must be exposed in evidence_chain/inference_explanation.
- If multiple candidates remain and there isn't enough evidence to
  pick → Level D. Never silently pick "most likely."
- The existing graded-slab guard (profile_dataset.py's `graded` check,
  forces non-A) becomes a SPECIAL CASE of this general collision logic
  going forward — keep the slab regex check (still useful, cheap
  pre-filter) but the general collision search should independently
  catch the same class of bug even without a slab marker.

## 2. Evidence Coverage vs Prediction Confidence — SPLIT, don't merge

Current `evidence.py` bug (per Yujin, must fix): `confidence` is
literally `confirmed_steps / 10` — that's Coverage, mislabeled as
Confidence. Fix:

- **`evidence_coverage`**: keep the current calculation (confirmed
  chain steps / 10 dimensions), rename it correctly. Document which of
  the 10 dimensions have an automated path today (5 do: pokemon_name,
  card_number, language, attack_names, catalog_match; 5 don't yet:
  artwork [partial after this build], hp, ability, expansion_symbol,
  holo_pattern).
- **`provisional_prediction_confidence`**: a NEW, separate, explicitly
  provisional rules-based score — "how likely is the CHOSEN candidate
  correct given what collision analysis found," not "how many boxes
  got checked." Must list the factors that raised/lowered it (e.g.
  "+ no competing candidates found", "- number was corrected not
  read", "+ artwork hash matched reference"). Label it
  `provisional_` in the key name per Yujin's explicit instruction —
  do not present it as calibrated/final.
- Absence of an unimplemented provider (holo, expansion symbol) must
  NEVER lower prediction_confidence — only affects coverage. This is
  an explicit rule from the spec; get it right, it's easy to get
  backwards.

## 3. Adversarial validation block — store on every result

For every final candidate, answer and store:
```python
{
  "strongest_alternative": {...},          # the best competing candidate, or null
  "evidence_supporting_alternative": [...],
  "evidence_excluding_alternative": [...],
  "could_ocr_substitution_explain_alt": bool,  # e.g. 6/8, 1/7 confusions
  "could_collision_be_undetected": bool,       # honest — collision search has limits
  "what_would_overturn_this": "...",
}
```
If no alternative was tested, verification is INCOMPLETE — this block
must always be populated (even if strongest_alternative is null with a
reason), never omitted.

## 4. ArtworkProvider (cheap partial version — build now)

New file: `providers/artwork.py` (or fold into collision.py if smaller
— decide based on actual size once written).

- Interface first, so a vision-API backend can slot in later without
  touching callers:
  ```python
  class EvidenceProvider:
      def verify(self, image_path, candidates, context) -> dict: ...
  ```
- `ArtworkProvider` implementation: perceptual hash (use `imagehash`
  library + Pillow — check if `imagehash` is already installed;
  `E:\python.exe -m pip show imagehash`, install if missing) comparing
  the uploaded photo's artwork region against LOCAL reference images
  already on disk (`dataset/images/`, the lot's Downloads folder) —
  NO scraping, NO new downloads, NO API calls per Yujin's explicit
  zero-cost constraint.
- Return structured evidence: `{"match_score": float, "matched_reference":
  path_or_None, "confidence_note": str, "status": "matched|no_match|
  not_verified"}`. If no reference image exists for the candidate
  printing, return `not_verified` — never guess.
- Wire into evidence_chain: artwork dimension goes from permanently
  `not_checked` to `confirmed`/`failed`/`not_verified` when this
  provider ran. Per Yujin's explicit rule: this can raise
  evidence_coverage, must NEVER by itself raise
  provisional_prediction_confidence beyond what collision analysis
  already established — it's one more coverage point, not a trust
  multiplier. (Re-read his message if this reasoning feels
  backwards when implementing — get this rule right.)
- Stub-only (return `not_checked` always, do NOT fake output) for:
  HPProvider, AbilityProvider, ExpansionProvider, HoloProvider. Honesty
  requirement carries over from V0.10.0 — a stub must say so, not
  pretend to have run.

## 5. Required regression tests (tests.py) — minimum set from the spec
- graded-slab language collision (already exists, keep, extend to go
  through collision.py now)
- Incineroar 27/149 vs wrongly-preferred SM38 (L32 — already exists,
  point it at collision analysis too if applicable)
- Mimikyu V 068/172 vs wrongly-preferred TG16 (L32 — same)
- a valid OCR read mapping to the WRONG real product (new — construct
  a synthetic case, two real catalog numbers one edit apart)
- same collector number across different sets (new)
- same/similar card name across languages (new)
- promo-number normalization edge case (new)
- leading-zero / suffix variant (new)
- multiple candidates remaining → must land Level D, not a silent pick
  (new)
- a genuinely clean case with NO collision → may still reach Level A
  (new — prove the analyzer doesn't just downgrade everything)
- ArtworkProvider: match found -> raises coverage; match found -> does
  NOT by itself raise prediction_confidence past what collision
  analysis set (new)
- ArtworkProvider: no reference available -> not_verified, never a
  guessed match (new)

## 6. Re-audit requirement (do this AFTER the above is built and tested)
Re-run both datasets (`dataset/carousell_profile.json`,
`dataset/for_u_to_do_while_im_asleep.json`) through the updated live
pipeline exactly like the V0.10.0 audit (see git log `9b8f9d3` commit
message and the reaudit scripts pattern used then — OCR is cached,
network calls needed for search). Report BEFORE/AFTER evidence_level
per card that changed, not just new totals.

## 7. Completion criteria (Yujin's own words, do not weaken these)
- Every A/B/C identification passes through collision analysis — no
  exceptions, no path that skips it.
- Every result exposes competing candidates OR explicitly states none
  were found (never a silent empty list with no explanation).
- No catalog-unique match is treated as proof by itself anywhere in
  the codebase.
- Ambiguous printings are downgraded, never silently picked.
- evidence_coverage and provisional_prediction_confidence appear as
  SEPARATE fields, both in the identify() output AND on the dashboard.
- Every newly discovered failure during this build gets a regression
  test, no exceptions.
- Both datasets re-run through the live pipeline, changed cards
  reported with before/after.

## Explicitly OUT of scope this iteration (do not drift into this)
Scraping reference images at scale, any paid vision-model API call,
counterfeit/forgery authentication, full artwork matching (only
perceptual-hash-vs-local-images), full holo-pattern recognition.

## End-of-iteration report format required when this is done
files changed / architecture added / tests added / datasets re-audited
/ cards whose levels changed / remaining assumptions / strongest
remaining failure mode / next highest-impact task after this one.
Same format as the V0.10.0 report — Yujin wants this every iteration
going forward, not just this once.
