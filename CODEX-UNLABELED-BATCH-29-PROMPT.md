# Codex Next Unit: Unlabeled 29-Image Production-Pipeline Evaluation

Built at: Mom's PC, 2026-07-20 ~1:45AM.
Origin: drafted by ChatGPT (Sol 5.6 Extra High), finalized here by Claude Code
with Yujin's explicit authorization to reword/improvise for function. Three
real additions from the original draft, three adjustments — see the end of
this doc if you want the diff explained; otherwise just execute this.

## Status check (do this first, don't skip)

The contour-first fix this doc originally gated on is **already done** —
commit `d24f9ef`, working tree was clean when this was written. Confirm that
still holds (`git log --oneline -3`, `git status --short`) and move straight
into this unit. Don't re-do it, don't look for reasons to touch it further.

## Mission

Evaluate the real production identification pipeline against an **unlabeled
batch of 29 real marketplace card photos** at:

```
C:\Users\MARVIN-LI\Downloads\To test\
```

Expected inventory: 26 `.jpg`, 3 `.jfif`, 29 total. These filenames resemble
scraped Facebook-listing filenames. **They are not labels, metadata, hints,
or ground truth.**

This unit is an evaluation of system behavior under real-world images. It is
**not** an exercise in maximizing the number of resolved cards. A lower
resolution rate with honest abstentions is preferable to a higher rate
containing unsupported answers — same rule as every unit tonight.

## Priority order if anything has to give

Getting through all 29 images with an honest, simple log beats a perfect
schema covering 10. If time/budget forces a tradeoff, spend it on **actually
running the batch**, not on polishing the manifest/report format below.
Everything under "Required result schema" and "Required batch artifacts" is
the target shape, not a blocker to starting.

## Non-negotiable constraints

Do not:
- Use filenames as identification evidence.
- Read listing titles, descriptions, or external marketplace metadata.
- Loosen thresholds to improve the apparent resolution rate.
- Force a candidate when multiple printings remain plausible.
- Promote any result into verified ground truth.
- Add any sample to `acceptance/corpus-v1/`.
- Commit source images or derived crops.
- Build a second, approximate identification path.
- Push commits, or begin Marketplace/Track B/Kino/paid-API/scraping/unrelated work.
- Treat the system's own prediction as proof that the prediction is correct.

## Phase 1 — Controlled intake

1. Enumerate the source folder. Build a local intake manifest: basename,
   extension, byte size, image dimensions, SHA-256, duplicate-hash status,
   intake timestamp. Verify exactly 29 supported files (26 jpg / 3 jfif). If
   the count differs, record the discrepancy in `AGENT-RELAY.md` and figure
   out whether it's harmless before continuing — don't silently proceed.
   Don't modify, rename, or move the originals.
2. Copy into a local-only, explicitly gitignored workspace (e.g.
   `local-data/unlabeled-batch-29/`, or wherever fits existing convention).
   Verify with git tooling that neither raw images nor generated crops can be
   staged accidentally. Any review crops stay in that same local-only area —
   committed artifacts contain hashes and structured records, never image
   bytes.

## Phase 2 — Production-path execution

3. Run every image through the real production path. Concretely: this
   already exists as `profile_dataset.identify()` — both `app.py` (line 381)
   and `folder_dataset.py` (line 31) import and call it directly. **Call that
   function directly; don't stand up or depend on a live Flask server running
   all night** — that would be a needless single point of failure for an
   unattended batch. A thin batch harness may call it, but must not bypass
   preprocessing, contour detection, pair/binder logic, collision analysis,
   evidence grading, or introduce batch-only heuristics. If you find the
   route still duplicates identification logic instead of sharing this
   function cleanly, report that as architectural debt — don't silently
   write a third copy.
4. Process one image at a time, appending to a durable JSONL checkpoint so
   an interruption doesn't lose completed work. Every one of the 29 source
   hashes ends in exactly one terminal status: `processed`,
   `processing_error`, or `unsupported_or_corrupt` — no file silently
   disappears from the report. Multi-card/binder/pair images preserve both
   the source-image-level status and each individual detected-card result.
   After completion, reconcile the output against the intake manifest and
   prove all 29 source hashes are accounted for exactly once.
5. **Post a lightweight interim checkpoint to `AGENT-RELAY.md` roughly every
   10 images (or every ~15-20 minutes, whichever comes first)** — just a
   running count (processed/errors/abstentions so far) is enough. I'm
   reviewing this file on a ~10-minute cycle overnight and want something to
   check against mid-batch, not only a report hours from now.

## Required result schema (target shape, see priority note above)

For every detected card or pocket, record at least: `processed` /
`processing_error` / `unsupported_or_corrupt`, `source_hash`,
`source_basename`, `source_index`, `detection_index`, `crop_hash`,
`crop_local_path`, `pipeline_entrypoint`, `detected_name`, `detected_number`,
`detected_set`, `detected_language`, `internal_evidence_level`. Use explicit
`null`/`not_checked` rather than omitting a field that would weaken the
result.

## Ground-truth discipline

This batch has no trusted labels. Every identification, regardless of
confidence or internal evidence level, stays externally classified as either
`unverified_candidate_pending_Yujin` or `abstained_pending_better_evidence`.
The system's internal Evidence Level is not human confirmation.

**Level B rule — read this carefully.** Level B means *Human Eye Verified*
per `DIRECTIVE.md`. An unattended automated batch must never mint a new
Level B result — Codex inspecting an image is not Yujin's verification. If
the production path emits Level B here without a recorded human adjudicator,
that itself is an evidence-contract bug, log it as one.

For strong candidates, create a local review queue entry: source hash, crop
hash, local-only crop path, proposed identification, internal evidence
level, supporting evidence, strongest competing candidate, and the exact
question Yujin needs to answer to confirm or reject it. Never add the crop
to git. Only Yujin's explicit later confirmation/rejection changes review
state.

## Abstention requirements

An abstention needs to be specific — not just `unknown`/`not found`/`could
not identify`. Record: what was successfully observed, what distinguishing
evidence was missing, remaining candidates if any, whether the cause was
image quality/segmentation/OCR/collision/language/catalog-coverage/other,
what would resolve it, and whether the limitation is the system's or the
evidence's. Never lower a threshold to eliminate an abstention.

## Bug classification

No ground truth means "wrong" can't mean "Codex's visual opinion disagrees
with the system." A real bug needs objective evidence: crash/unhandled
exception, skipped or double-processed file, corrupt output state,
production-route vs. batch-harness disagreement, an evidence-contract
violation (including the Level B rule above), an impossible/contradictory
card number, a selected candidate contradicting directly readable text, a
silent winner chosen over an unresolved collision, confidence rising from
evidence marked `not_checked`, miscalculated evidence coverage, a binder/pair
split losing cards, stale state leaking between images, or the same
deterministic input producing inconsistent output. A catalog-coverage gap is
**not** automatically a bug — record it separately unless the product should
already exist in the configured catalog and retrieval demonstrably failed.

For every demonstrated bug: preserve the failing input hash + minimal
repro, document expected vs. actual, write a regression test that fails
first and confirm it fails for the right reason, apply the smallest
root-cause fix without weakening any global threshold, run the focused test
then the full suite, reprocess every batch item the fix could have touched,
record before/after, update the relevant lesson/failure record, commit as
one atomic local commit. No filename-specific/hash-specific/species-specific
exceptions.

## Required batch artifacts

Committed, privacy-safe, no raw image bytes:
`reports/unlabeled-batch-29-manifest.json`,
`reports/unlabeled-batch-29-results.jsonl`,
`reports/unlabeled-batch-29-summary.md` (existing project conventions win if
they fit better). Manifest holds basenames + hashes, never image data.

Summary reports: expected vs. discovered input count, processed/errors/
corrupt-unsupported/duplicates, total detected cards, resolved-internally
count, abstentions, candidates awaiting Yujin, Evidence Level distribution,
evidence-coverage distribution, collision count, catalog-coverage gaps,
objective bugs found/fixed, regression tests added, full-suite result,
remaining highest-risk failure mode. All totals reconcile; explain any that
don't.

## `AGENT-RELAY.md` handoff

Commit hash(es); exact 29-file reconciliation; resolution/abstention
totals; count awaiting Yujin; Evidence Level distribution; every objective
bug found and fixed with its regression test; catalog gaps intentionally not
chased; full-suite result; local review-queue location; remaining
assumptions; recommended next unit and why. Never describe a candidate as
correct before Yujin confirms it.

## Commit and sync rules

Local commits only, no push, no remote branch changes, never stage raw
images/crops, `git status` before every commit, keep unrelated changes out,
never claim a clean tree without checking.

## Additional-unit policy

After this batch is complete/reconciled/tested/committed/relayed, only
continue to another unit if it's directly justified by a confirmed failure
from this batch, already the approved next relay item, independently
boundable/testable, and in-scope. Before starting one, write:

```
Next unit:
Observed problem:
Evidence:
Proposed smallest fix:
Acceptance test:
Explicit non-goals:
```

One unit at a time. Don't start broad architecture work just because it'd
be useful eventually.

If the next decision needs Yujin's judgment, paid resources, new scraping,
new external data, or a product-direction call — leave a clear handoff
instead of guessing.

## Definition of done

All 29 source hashes reconciled; real production path used (direct function
call, not a live-server dependency); no raw images/crops tracked; all
predictions remain unverified; abstentions are actionable; every
demonstrated bug has a regression test; affected images reprocessed after
fixes; full suite passes; privacy-safe reports exist; interim checkpoints
were posted during the run, not just at the end; `AGENT-RELAY.md` has the
complete handoff; everything committed locally; nothing pushed.

Optimize the report to be reproducible, falsifiable, and honest — not to
sound successful.
