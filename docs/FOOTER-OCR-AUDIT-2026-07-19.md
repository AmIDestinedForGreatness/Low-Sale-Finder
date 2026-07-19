# Footer OCR evidence audit - 2026-07-19

This audit was performed before changing footer OCR logic. It distinguishes a
historical failure record from a failure that can still be reproduced from its
original source image on this checkout.

## Verified repository counts

- `dataset/failures.json` contains 45 per-card records plus one structural
  record.
- Before this unit, 16 of 45 per-card records had the exact cause `read
  directly from the footer by a human eye after OCR failed`.
- Those 16 records represented 15 unique `(card name, collector number)`
  pairs because Coalossal `117/100` appeared twice under different query keys.
- Ten of 45 per-card records cite `artwork` in `evidence_missing`.
- After the real Mime Jr. replay and record refresh, the footer-human cause is
  attached to 15 of 45 records / 14 unique card-number pairs. The total
  non-Level-A record count remains 45 because Mime Jr. is now Level C: the
  number is direct, but the name is derived from its one exact catalog product.

These are record counts, not a current measured failure rate. The database
does not preserve a source image or raw OCR trace for every record, so the
other records cannot be assumed to fail under the current pipeline.

## Machine state

- `fingerprints.sqlite`: absent.
- `dataset/images`: absent.
- `uploads`: three identical blank synthetic JPEGs plus their synthetic crop
  outputs; no private real card photo was present.
- The original Coalossal and Rota's Mime Jr. listing pages remained publicly
  readable. Six source photos from each were retrieved into an isolated
  temporary audit directory. They were not copied into `uploads` or
  `dataset/images`.
- Only a privacy-minimized Mime Jr. footer crop is retained under
  `tests/fixtures/footer_ocr/`, with source URL, source/crop hashes, expected
  identity, OCR trace, and retention basis in the adjacent JSON manifest.

## Six-record evidence sample

| Failure record | Expected identity | Source / footer evidence | Raw and normalized number | Crop / candidate / final result | Artwork and metadata | Reproducible here? |
|---|---|---|---|---|---|---|
| `Coalossal|117/100|Coalossal 117/100` | Historical target: Coalossal, S3, `117/100`, Japanese | Six original listing photos retrieved; footer visibly present. Current full-frame RapidOCR read exact `117/100` on 2/6 photos. Historical JSON also preserved an exact read on 3/6 photos. | Raw exact `117/100UR`; normalized `117/100`. | Existing full-frame/deep regions; historical crop coordinates were not preserved. Live number-only search returned six exact-number Japanese products, including Coalossal at rank 6. Final result safely abstained at Level E because no direct name separated the collision. | No local visual catalog; listing title was not passed to the replay. | Yes, but it does **not** reproduce the claimed unresolved footer OCR failure. It reproduces a name/collision limitation. |
| `Rota's Mime Jr.|086/PCG-P|Rota's Mime Jr. 086/PCG-P` | Rota's Mime Jr., PCG-P promo `086/PCG-P`, Japanese | Six original listing photos retrieved; footer visibly present. Initial OCR: 0/6 exact, 1/6 partial (`086/PC`). Existing deep sweep: exact text present on 1/6. | Deep lines contained earlier corrupt `O86/PCG-P` and later exact `086/PCG-P`. Before: parser emitted `86/PCG-P`. After: `086/PCG-P`. | Retained crop `[80,760,730,950]` from 810x1080 source. Before: 0 candidates, Level E. After: one exact TCGplayer product, Level C, provisional confidence 73, name explicitly derived via `unique number match`. | No local visual catalog; listing metadata was not passed to identification. | Yes. This is the one confirmed real defect closed by this unit. |
| `M Blastoise-EX|22/108|M Blastoise-EX` | M Blastoise-EX `22/108`, English | Structured record preserves only final human-adjudicated fields and the old filename. No original file, source URL, raw OCR, or crop coordinates are present. | Historical final number `22/108`; raw/normalized OCR unavailable. | Candidate/final replay unavailable. | `evidence_missing` says none; artwork cannot be checked here. Metadata influence cannot be reconstructed. | No - source unavailable; no replacement fabricated. |
| `M Manectric-EX|024a/119|M Manectric-EX` | M Manectric-EX `024a/119`, English | Final human-adjudicated record and filename only; no source image/raw OCR/crop. | Historical final `024a/119`; raw OCR unavailable. | Replay unavailable. | Historical record cites artwork, expansion symbol, and language as missing. | No - source unavailable. |
| `Mimikyu V|068/172|Mimikyu 068/172` | Mimikyu V `068/172`, English | Final record says `visual read (assistant eye)`; original image and raw OCR are absent. | Historical final `068/172`; raw OCR unavailable. | Replay unavailable. | Historical artwork provider was not verified; metadata influence cannot be reconstructed. | No - source unavailable. |
| `Victini|XY117|Victini XY117` | Victini `XY117`, English promo | The structured dataset names a four-card binder file, but the file, raw OCR, per-card crop, and coordinates are absent. | Historical final `XY117`; raw OCR unavailable. | Replay unavailable. | No independent local reference; exact metadata influence cannot be reconstructed. | No - source unavailable. |

Result: 2/6 sampled historical records had retrievable original sources, 4/6
were non-reproducible on this machine, and only 1/6 exposed a current footer
pipeline defect. This does not satisfy a five- or six-unique-real-case corpus;
claiming otherwise would fabricate evidence.

## Confirmed pipeline trace and correction

For the Mime Jr. source:

1. Card/footer visibility: present to a human.
2. Initial local OCR: one partial read (`086/PC`), no complete collector token.
3. Existing deep footer sweep: returned both `O86/PCG-P` and `086/PCG-P`.
4. Collector extraction: accepted the first regex substring as `86/PCG-P`
   even though it began inside an alphanumeric OCR token.
5. Candidate search: `86/PCG-P` returned zero products; `086/PCG-P` returned
   exactly one product, Rota's Mime Jr.
6. Correction: prefer the first direct promo token with a clean boundary,
   retaining a letter-glued substring only when no clean direct read exists.
   No leading zero is created and no catalog-nearest rewrite is performed.

Safety checks preserve a sole `O86/PCG-P` as the observed `86/PCG-P`, retain
first-clean behavior when two clean promo numbers are visible, and reject HP,
attack/year digits, partial denominators, and missing slashes. On the two
source-backed records, incorrect identifications and incorrect
high-confidence identifications were 0 before and 0 after. Coalossal remained
an abstention rather than being forced to the sixth same-number candidate.

## Baseline and after metrics

| Metric | Before | After |
|---|---:|---:|
| Unique historical records with live source in the six-record sample | 2 | 2 |
| Correct initial raw number, Coalossal photos | 2/6 | unchanged |
| Correct initial raw number, Mime Jr. photos | 0/6 | unchanged |
| Correct number present in bounded deep OCR, Mime Jr. photos | 1/6 | unchanged |
| Correct parsed normalized Mime Jr. number | 0/1 record | 1/1 record |
| Correct exact Mime Jr. candidate present/ranked first | 0/1 | 1/1 |
| Correct exact final printing | 0/1 | 1/1 at Level C |
| Incorrect final printing | 0 | 0 |
| Incorrect high-confidence printing | 0 | 0 |
| Coalossal forced from number collision | 0 | 0 |

OCR was local RapidOCR/ONNX; external OCR calls were zero. Read-only live
network was used to retrieve the two source listings/photos and to validate
candidate-search behavior. No message, offer, purchase, webhook, account
action, deployment, or push occurred.

## Open handoff

The next highest-value footer unit needs original files for another named
record, preferably M Blastoise-EX `22/108`, M Manectric-EX `024a/119`, Mimikyu
V `068/172`, or one of the two binder pages. On the Personal PC, copy the
original into an isolated fixture workspace, preserve its source hash and raw
OCR trace, and repeat the same baseline before changing OCR. HASH-FIRST remains
unaccepted here because `fingerprints.sqlite` and `dataset/images` are absent.
