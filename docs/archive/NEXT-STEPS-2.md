# NEXT-STEPS-2.md — active spec, queued behind the fb_feed.py pace unit (2026-07-17)

Repo: `C:\Users\Marvin\low-sale-finder` (GitHub: AmIDestinedForGreatness/Low-Sale-Finder)
Written by CC while CX was mid-unit on the `fb_feed.py` pace/Marketplace fix — do not
start this until that unit is committed and reviewed. This is the full accepted spec,
not a summary; resume from here if a session ends mid-build.

## Status: SPEC ONLY, NOT STARTED

Origin: Yujin dropped a live binder photo (Victini/Meloetta/Magearna/Manaphy) into the
dashboard tonight and got a correct-but-low-confidence result — Meloetta XY120 landed at
Level D, 10% coverage, 35% provisional prediction, despite being visually obvious to him
instantly. He then ran the same card crop through TinEye's public reverse-image search
and got 10 real matches (eBay listings of the exact same card) in seconds. His ask:
build that capability into the pipeline. This spec is the concrete "how."

This is not a new idea grafted on — `NEXT-STEPS.md`'s original Evidence Provider diagram
(V0.10.0) already named the path: `ArtworkProvider <- perceptual hash today, vision API
later`. This spec is "later."

## The actual gap, verified against real data (not assumed)

Pulled the live evidence chain for the exact Meloetta crop Yujin uploaded
(`uploads/card_1784300842_r0c1.png`), via `profile_dataset.identify()` directly:

```
attack_names: confirmed     <- the only fully-verified dimension
pokemon_name: inferred      card_number: failed
artwork: not_verified       hp: not_checked
ability: not_checked        expansion_symbol: not_checked
holo_pattern: not_checked   catalog_match: not_checked
```

`providers/artwork.py` exists but is **local-only perceptual hash against images already
on disk** (its own docstring: "Zero-cost, local-only"). It returned `not_verified` here
because there was no independent local reference photo of this exact printing to compare
against — not a bug, the provider is honestly reporting its own limit (`"no independent
local reference image exists for any candidate; no match was guessed"`). TinEye's result
proves independent reference images DO exist — just not on this machine. The fix is
giving `artwork` a second backend that can reach them.

## Backend choice: Google Cloud Vision (Web Detection), not TinEye

Checked pricing for both before recommending one:

| | TinEye API | Google Cloud Vision Web Detection |
|---|---|---|
| Entry cost | ~$200/mo minimum commitment (enterprise-oriented) | **First 1,000 units/month free, does not expire** |
| Cost beyond free tier | ~$0.04-0.20+/search | ~$0.0035/search ($3.50 per 1,000 units) |
| Fit | Built for high-volume commercial use | Fits this project's actual (low, personal-scale) volume almost entirely inside the free tier |

Google Vision's `WEB_DETECTION` feature returns the same category of result TinEye just
demonstrated working: `fullMatchingImages`, `partialMatchingImages`, and
`pagesWithMatchingImages` (each page has a URL and, often, a page title) — enough to find
a matching listing and extract candidate name/set/number text from its title/description,
the same way `search_candidates()` already parses TCGplayer results today.

## Setup required (Yujin's part, not code)

1. Create/use a Google Cloud account, create a project, enable the **Cloud Vision API**.
2. Google requires a billing account attached even to stay inside the free tier (same
   non-charging guarantee shape as Oracle tonight — nothing bills without exceeding the
   free 1,000/month, and even past that it's fractions of a cent per call). Set a
   **budget alert** in GCP Billing at a low threshold (e.g. $1) as a tripwire, same
   spirit as double-checking Oracle's estimator earlier tonight.
3. Create a restricted API key (Vision API only, no other scopes) or a service-account
   JSON key.
4. Store it in `C:\Users\Marvin\.claude\local-secrets\low-sale-finder.env.local` as
   `GOOGLE_VISION_API_KEY=...` — same vault, same rule as every other secret in this
   project: never in code, never in the repo, never in the brain.

CC will not do this step — it needs Yujin's own Google account. CX should treat this key
as absent until Yujin confirms it's in the vault, and the provider must degrade to
`not_checked` (not crash, not fake a result) if the key is missing, same pattern
`_load_bot_token()` already uses for the Discord bot token.

## Architecture

New file: `providers/web_artwork.py`, a **second backend for the existing `artwork`
dimension**, not a new dimension. `evidence.py` should try the network backend when the
local perceptual-hash backend (`providers/artwork.py`) returns `not_verified` or
`no_match` due to missing local references specifically (not when it already found a
confident local match — don't spend an API call when a free local match already worked).

```python
class WebArtworkProvider(EvidenceProvider):
    dimension = "artwork"

    def verify(self, image_path, candidates, context):
        # 1. Load GOOGLE_VISION_API_KEY from local-secrets; if absent, return
        #    not_checked (never crash the pipeline over a missing key).
        # 2. Cache key: perceptual hash of image_path (reuse providers/artwork.py's
        #    _file_hashes) -> cached Vision result. Re-scanning the same photo
        #    (re-audits, dashboard re-checks) must NOT re-spend quota.
        # 3. Call Vision's annotate_image with WEB_DETECTION feature.
        # 4. Parse pagesWithMatchingImages: for each page (bounded, e.g. top 5),
        #    extract candidate name/number text from title/URL the same way
        #    search_candidates() parses TCGplayer results today.
        # 5. Run the extracted candidate(s) through collision.py's EXISTING
        #    widening/dedup logic - do not build a second, parallel matching
        #    system. A web-found candidate is just another candidate.
        # 6. Track monthly usage in a local counter file (reset monthly); if
        #    within ~50 of the free 1,000 limit, log a warning to FAILURES.md
        #    equivalent so Yujin gets a heads-up before any real charge could
        #    land, not after.
```

## The guardrail that matters most — do not skip this

A visual match proves an image exists somewhere that looks like this card. It does
**not** prove the exact printing/set, because Pokémon reprints identical artwork across
sets and promos constantly (this project already has real examples of that exact
collision pattern — see `collision.py`'s handling of same-art/different-set cases).

Required behavior:
- A Web Detection match that AGREES with the current best local/catalog candidate:
  raises `artwork` to `matched`, raises Coverage. Does not by itself force Level A -
  still needs the existing name+number+catalog agreement the pipeline already requires.
- A Web Detection match that CONFLICTS with the current candidate (different set/number
  in the matched page's text): feed it into `collision.py` as a genuine alternative,
  exactly like an existing-candidate collision today. Never silently prefer one over the
  other without the existing adjudication logic deciding.
- No matches found: `not_verified`, same honest-failure posture the rest of this
  pipeline already uses. Never treat "no web match" as evidence the card doesn't exist.

## Acceptance criteria (mirrors V0.11's bar, same standard)

1. `providers/web_artwork.py` built as a real second backend, wired into `evidence.py`'s
   artwork-dimension resolution (tries local pHash first, falls back to Vision only when
   local has no reference).
2. Missing API key degrades cleanly to `not_checked` - verified by a regression test that
   asserts no crash and no fabricated result when the key is absent.
3. Caching by perceptual hash - a regression test proving a second identical-image call
   does not re-hit the network (mock the API client, assert call count).
4. A conflicting web match correctly produces a `collision_analysis` entry, not a silent
   override - regression test using a synthetic conflicting match.
5. Live re-run of tonight's exact Meloetta case (`uploads/card_1784300842_r0c1.png`) shows
   Coverage genuinely higher than the current 10% (artwork dimension resolved), with the
   before/after numbers reported honestly - if it's still not Level A, say why, don't
   force it.
6. Monthly usage counter exists and logs a warning approaching the free-tier limit.
7. `deploy/README.md`'s secrets checklist gets a line added for
   `GOOGLE_VISION_API_KEY` once this ships, so the Oracle migration checklist stays
   accurate.

## Sequencing

Behind the `fb_feed.py` pace unit currently in progress - do not context-switch onto
this until that unit is committed and CC has reviewed it. This file is the full spec so
nothing needs re-deriving from chat when CX is ready to start.
