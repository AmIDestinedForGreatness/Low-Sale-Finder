# Report 3 — System update, overnight 7/16 → 7/17 (V0.6 → V0.8)

> "We are nowhere near, but we are closer than where we were yesterday."

## What shipped while you slept

### V0.7 — the Carousell dataset run (`6694265`)
- **Layer C — name vocabulary snap**: every guessed name must be (or snap
  uniquely to) one of 4,428 real card names; watermarks and OCR garbage are
  rejected instead of searched.
- **Layer D — dex number**: JP vintage identifies by its Pokédex strip
  ("NO.398" → Staraptor). Fingerprint index rebuilt with a dex column.
- **Fingerprint honesty**: ambiguity guard (corroboration + clear winner) +
  the "fingerprint × number" tie-break.
- **Promo letter footers** (034/XY-P, 197/SV-P, 065/PCG-P…).
- **Batch watermark defense** (cross-listing token frequency, fuzzy).
- `profile_dataset.py` — reusable: any Carousell profile → scrape →
  identify image-first → verify against titles → dataset JSON.

### V0.8 — the overnight build (the overnight lot + your requests)
- **LINK AS SOURCE — live on the dashboard now**: paste a Carousell listing
  URL next to the drop-box → the system fetches the listing's photos itself
  and runs the full identification stack. Verified end-to-end on your Mega
  Manectric listing (photo fetch → "Mega Manectric ex #077/063 · Japanese ·
  attack fingerprint"). This is step one of your "scrape links to feed the
  system" plan — the ingestion path exists; profile-wide and FB-post
  ingestion ride the same rails next.
- **Orientation auto-righting** (sideways phone photos).
- **Binder-page splitting** (multi-card photos → per-card crops).
- **Squashed-form name matching + variant-letter numerators + V-glue shapes**
  (MManectricEX, EeveeVax, 24a/119).
- **Language-claim discipline** (L27) and **identity-strict pricing** for
  lots (name+number must agree with the priced product).
- `folder_dataset.py` — reusable: any folder of photos (consignments!) →
  identified + priced + renamed as proof.

## Numbers

| | before tonight | now |
|---|---|---|
| Tests | 43 | **51** (all green) |
| Lessons | 20 | **27** |
| Identification layers | 8 | **12** |
| Datasets (ground truth) | 0 | **2** (58 cards with evidence trails) |
| Dashboard input sources | photo | **photo + listing link** |

## Watch items for when you wake
1. **Post #2 (tins/ETBs)** — prepared last night, not yet posted. Evidence = the link.
2. Grade the renamed folder + both reports; corrections become the next lesson batch.
3. Coalossal + Mime Jr. each need ONE footer close-up photo to close Report 1's gaps.
4. Next build (your call): profile/FB-link batch ingestion feeding the dataset automatically.
