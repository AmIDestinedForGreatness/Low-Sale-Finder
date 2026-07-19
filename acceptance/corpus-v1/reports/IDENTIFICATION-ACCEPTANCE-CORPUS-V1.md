# Identification acceptance corpus v1

- Report schema: `identification-acceptance-report-v1`
- Corpus version: `corpus-v1`
- Evaluated commit: `d35f82224893c50ee71299286b998abbbdae5380`
- Generated at: `2026-07-19T05:30:00+00:00`
- Manifest SHA-256: `72292b8047dd3132478c50eb65b8d4107b832c1817fce18ffde272aa379dc724`
- Deterministic evaluation SHA-256: `58603a8c61e168b6aa914761e3368836e8b135169a08e2f8a93293f86e83cf13`

## Execution accounting

- Manifest records: 1
- Executed: 1
- Passed: 0
- Failed: 1
- Unavailable: 0
- Errors: 0
- Skipped: 0
- Measurement valid: `true`
- Acceptance pass: `false`

Missing, changed, malformed, or undecodable assets are unavailable. They never count as passes.

## Source inventory

- Inventory SHA-256: `e795f00a5b2e3cad7d4d812742aba4952e101da43549ed428c9e1685b8e14b5d`
- Durable real full-card assets: 0
- Durable real footer crops: 1
- Historical card failure records without a durable asset: 44/45
- Blastoise eBay front/back pair: unavailable; retention/commit permission was not established, so no image or derivative was used.

## Separated metrics

- Full-card samples executed: 0
- Full-card exact printing: 0/0
- Full-card precision: 0/0
- Full-card coverage: 0/0
- Full-card abstention: 0/0
- Full-card high-confidence false positives: 0/0
- Footer-only samples executed: 1
- Footer exact collector-number OCR: 0/1
- Frozen footer parser replay exact: 1/1
- Footer samples counted as full-card successes: 0

## Evidence and policy

- Catalog inference used: 0/1
- Zero-inference exact number: 0/1
- F-06: unresolved and preserved for owner review.
- HASH-FIRST executed: false; no retained full-card sample and no fingerprint/catalog-image assets exist.

## Raw performance

percentiles not meaningful at this sample size.

| Sample | Benchmark | Total ms | OCR ms | Parser replay ms |
|---|---|---:|---:|---:|
| `footer-rota-mime-jr-086-pcg-p-001` | footer-ocr | 2116.891 | 2115.841 | 0.132 |

## Sample outcomes

- `footer-rota-mime-jr-086-pcg-p-001`: status `failed`, executed `true`, counted as pass `false`.
  Image OCR observed number: `None`; exact: `false`.
  Frozen parser replay observed number: `086/PCG-P`; exact: `true`.

## Isolation

- Network attempts: 0
- Production state modified: `false`
- Production OCR cache used: `false`

Exact counts above describe this corpus only. They are not population estimates.
