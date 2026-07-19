# Identification acceptance corpus v1

This directory freezes the identification evidence that is actually retained
and permitted for replay. It measures the current pipeline; it does not improve
identification logic and it does not convert historical claims into samples.

## Current corpus

- Full-card acceptance: 0 retained real samples.
- Footer-OCR micro-corpus: 1 retained real sample, Rota's Mime Jr.
  `086/PCG-P`.
- Synthetic robustness: 0 corpus samples. The blank files in `uploads/` are
  excluded placeholders.
- Historical failure records without a durable source asset: 44/45 card
  records. They are inventory facts, not executed failures.

The footer crop is never counted as a full-card identification. The runner
measures image-to-number OCR separately from a frozen raw-OCR parser replay.
This distinction exposes the present baseline: a parser can succeed on a
captured exact OCR line even when OCR of the retained crop does not reproduce
that line.

## Files

- `manifest.jsonl` is the executable, checksummed sample list.
- `source-inventory.json` records admitted, excluded, and unavailable sources.
- `assets/` contains only retained assets and frozen provenance required for
  replay.
- `reports/` contains versioned machine- and human-readable output.
- `../corpus_runner.py` verifies and executes the corpus offline.

Every executable record includes provenance, retention basis, independent
ground-truth authority, all six expected identity fields, unknown-field
markers, difficulty tags, and failure category. Ground truth cannot come from
the system prediction or a seller title alone.

## Integrity and isolation

The runner:

1. validates manifest schema and unique sample IDs;
2. confines asset paths to this corpus directory;
3. rejects missing, changed, malformed, or undecodable assets as unavailable;
4. rejects asset-type/benchmark mixing;
5. blocks in-process Requests and socket connections;
6. uses a temporary OCR cache rather than `ocr_cache.sqlite`;
7. snapshots `FAILURES.md`, `dataset/`, `uploads/`, `data/`, and root database
   files before and after execution;
8. reports zero executed cases as no measurement, never success; and
9. emits raw per-sample latency because percentiles are not meaningful at the
   current sample size.

Run from the repository root with the installed Python interpreter:

```text
python -m acceptance.corpus_runner
```

This is a corpus command, not a second test suite. Permanent integrity tests
remain part of `tests.py`.

## Adding a sample

Acquire retention/commit permission before copying an asset here. Record the
original source and retrieval date, preserve SHA-256, remove unrelated private
scene content only when the permission still allows the derivative, and use an
authority independent of the system prediction and listing title. Full-card
samples also need a frozen offline dependency bundle before the runner will
allow them into full-card acceptance; otherwise they remain unavailable.

The newly acquired eBay M Blastoise-EX front/back pair did not clear this gate:
no explicit reusable license or seller permission was found. Cropping would
reduce privacy exposure but would not create retention rights, so only hashes
and the rejection decision appear in `source-inventory.json`.
