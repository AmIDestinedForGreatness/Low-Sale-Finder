# CODEX TASK — FROZEN, REPLAYABLE IDENTIFICATION ACCEPTANCE CORPUS (v1, trimmed)

Built at: Mom's PC, 2026-07-19 ~12:40PM.
Origin: drafted by ChatGPT (Sol 5.6 Extra High, agentic), revised here by
Claude Code after independently re-verifying repo state. Merge, not a
rewrite — ChatGPT's structure and rigor were sound; this trims scope and
corrects three stale assumptions found by direct inspection tonight.

## WHY THIS EXISTS

F-07 in `docs/CLAUDE-CODE-AGENT-EVALUATION.md`: nobody can currently state
this system's real accuracy, false-positive rate, or coverage, because no
frozen, checksummed, reproducible test corpus exists. This unit builds the
measurement foundation — not an accuracy improvement. Do not optimize
identification logic before the baseline is frozen and reported.

## CORRECTIONS TO THE ORIGINAL DRAFT (verified directly, just now)

1. **Test totals are stale — re-run, don't trust the quoted numbers.**
   The `145/142/3/0` test snapshot came from the `801885b` relay entry.
   Five commits have landed since then: `b3d227d`, `a5ca3a9`, `9f04482`,
   `65c8f0c`, `e3a435a`. `65c8f0c` ("fix: align dashboard identification
   and isolate regressions") touched `app.py` (+22/-lines), `tests.py`
   (+98 lines), and `dataset/failures.json`. Treat every quoted number in
   this doc as a claim to reproduce, not a fact — run `python tests.py`
   fresh and record what you actually get.

2. **`uploads/` was checked byte-for-byte tonight — confirmed still
   synthetic-only.** All three JPEGs (`card_1784393390.jpg`,
   `card_1784393401.jpg`, `card_1784394217.jpg`) are byte-identical
   placeholders (8227 bytes each, 600x800 blank), and their four crop
   PNGs each are byte-identical too (3178 bytes). This is not real card
   inventory. Confirm this still holds when you check, but don't spend a
   unit rediscovering it — it's gitignored and was already the case at
   the last audit.

3. **The Coalossal originals are gone, not just unused.**
   `docs/FOOTER-OCR-AUDIT-2026-07-19.md` retrieved 6 Coalossal source
   photos into a temporary audit directory that was not committed or
   retained — only the Mime Jr. footer crop survived permanently, under
   `tests/fixtures/footer_ocr/` with its manifest. Going in, assume
   **exactly one durable real asset** (Mime Jr. footer crop) unless you
   find more. Do not expect Coalossal photos to still be on disk.

Read `AGENT-RELAY.md` bottom-up starting from your own most recent entry,
then `65c8f0c`'s relay entry and diff, before doing anything else — that
commit changed `app.py` identification behavior and added
`docs/CLAUDE-CODE-AGENT-EVALUATION.md`, which this unit directly serves.

## SCOPE (trimmed from the original draft)

The original draft is well-designed but sized for a corpus with dozens of
real samples. Given the actual asset reality (≈1 durable real sample plus
whatever you newly acquire), keep the **schema and integrity guarantees**
full-strength, but simplify **statistics**:

- With n<5 real samples, do not compute p50/p90/p95 — list raw per-sample
  runtimes instead and say so explicitly ("percentiles not meaningful at
  this sample size").
- Precision/coverage/abstention-rate numbers must be reported as exact
  counts ("1/1", "0/2"), not implied as statistically representative.
- Keep all corpus-record schema fields (checksum, provenance, ground-truth
  authority, asset type, retention basis) — these matter even at n=1,
  they're what make the *next* sample addable without re-deriving trust.
- Keep the full-card vs. footer-crop separation rule exactly as drafted —
  this is the most important single rule in the corpus, because the only
  durable real asset right now is a footer crop and it must never be
  reported as a full-card identification success.

Everything else from the original draft — corpus manifest structure,
checksum/immutability rules, offline/state-isolation requirements, the
metric categories (execution accounting, full-card, footer-OCR, evidence,
performance), the required tests, F-06 exposure-not-resolution, the
primary/secondary unit split, and the full out-of-scope list — stands as
written below.

---

## PRIMARY UNIT

1. Verify current repo state fresh (`git status`, `git log --oneline -10`,
   `python tests.py`). Record exact numbers.
2. Inventory real assets: `uploads/`, `tests/fixtures/footer_ocr/`,
   anything referenced in `FAILURES.md`/`dataset/failures.json`/
   `AGENT-RELAY.md`. Determine which have independent ground truth and can
   be committed vs. are local-only.
3. Create `acceptance/corpus-v1/manifest.jsonl` + `README.md` +
   `assets/` + `reports/`. Every record: `sample_id`, corpus version,
   asset path, SHA-256, asset type (full-card / footer-crop / synthetic /
   dataset-image), provenance + retrieval date, retention/commit
   permission, ground-truth authority/confidence, expected fields (name,
   set, number, language, finish, variant — mark genuinely unknown fields
   as unknown, never guessed), difficulty tags, known failure category.
   Never derive ground truth from the system's own prediction or from a
   seller's listing title alone.
4. Separate corpus types — full-card acceptance corpus, footer-OCR
   micro-corpus, optional synthetic-robustness corpus. Never blend them
   into one score.
5. Build an offline, state-isolated runner: checksum-verifies every asset
   before use, fails closed (missing/changed/malformed/undecodable →
   marked unavailable, never counted as a pass), never touches
   `FAILURES.md`/production JSON/`uploads/`/cached marketplace data, blocks
   live network, uses temp dirs.
6. Produce a machine-readable report (versioned schema: corpus version,
   commit, timestamp, asset availability, sample outcomes, aggregate +
   performance + evidence metrics, network/cache status, skips, errors,
   unresolved policy contradictions) and a human-readable
   `reports/IDENTIFICATION-ACCEPTANCE-CORPUS-V1.md` — numbers only, no
   "excellent/strong/production-ready" adjectives.
7. Expose F-06 (Level-A policy contradiction) as measurable data — which
   samples relied on catalog inference, whether zero-inference was
   actually achieved — without resolving it. That's an owner decision.
8. Add permanent integrity tests to `tests.py` (valid/malformed manifest,
   duplicate sample_id, missing asset ≠ pass, checksum mismatch rejected,
   footer crop can't enter full-card benchmark, network blocked, zero
   executed cases can't report success, re-run determinism, etc.) — do
   not create a second test command.
9. One focused local commit for the corpus framework. **Do not push.**
   Do not fix any identification defect in this commit.

## SECONDARY UNIT (only after the primary commit exists)

Run the frozen corpus, pick exactly one reproduced defect, add a failing
regression test first, implement the smallest fix, re-run the corpus
before/after, confirm false-positive safety didn't regress, update
`LESSONS.md` + `AGENT-RELAY.md`, separate local commit. Do not push.

## OUT OF SCOPE

Marketplace/pricing/Track B/Kino/multi-TCG/mobile/large `app.py`
refactors/new OCR providers/new paid services/further unscoped security
work/resolving F-06. Same boundaries as every prior unit tonight.

## RELAY ENTRY REQUIRED

Same structure as your `801885b` entry: verified starting state, corpus
contents, integrity, baseline metrics (exact counts, not rounded),
policy findings, HASH-FIRST status, tests, commit hash, next task.

## FINAL SELF-AUDIT (answer before ending session)

Real full-card images executed? Footer-only samples executed? Synthetic
samples? Historical cases unavailable? Did any missing/skipped case count
as a pass? Any network request attempted? Any production state modified?
Exact high-confidence false-positive count? Exact-printing precision and
coverage (as raw counts)? Abstention rate? Raw per-sample latencies (not
percentiles, given n)? Was HASH-FIRST genuinely exercised? Was F-06
preserved for owner review, not resolved? What part of the corpus ground
truth should the next agent challenge first? What single defect should be
fixed next?
