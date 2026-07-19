# Yujin's Pokestop

A multi-purpose Pokémon TCG deal-finding and card-identification system.
Started as a Carousell sniper; now four always-on processes plus the Card
Valuator identification engine (the core IP).

> Mission (see `DIRECTIVE.md`): minimize the probability of an incorrect
> identification. Accuracy > speed. Evidence > confidence.

## The system — 4 processes

| # | Process | Entry point | What it does |
|---|---|---|---|
| 1 | Carousell feed | `python main.py --feed` | Every new TCG listing → Discord; price-drop alerts; sold/reserved edits; deal + STEAL alerts |
| 2 | FB groups feed | `python fb_feed.py` | 15 PH TCG groups via headless burner; sale/auction split; auction end-reminders |
| 3 | Discord bot | `python bot.py` | Pokestop#6681 — react-to-track, /dashboard /help /status |
| 4 | Dashboard | `python app.py` | Live status, recent sends, **Card Valuator** (photo → exact printing), webhook manager |

## Card Valuator — identification stack

Photo in → exact printing out, through layered evidence (full detail in
`PROGRESS.md`): RapidOCR → name vocabulary snap → JP set-code footers →
attack fingerprint (20,444-card local index) → dex number → deep-scan →
constraint snap → adversarial collision search → A–E evidence level with the
user's eye as final authority. Multi-card binder pages are detected by
contour geometry (`folder_dataset.py`) and each card is identified
separately.

## Document map — read these, in this order

| File | What it is |
|---|---|
| `PROGRESS.md` | **Start here.** Version history, the system, current limits, roadmap |
| `DIRECTIVE.md` | The governing rules: evidence levels A–E, no silent inference, banned language |
| `HASH-FIRST-NEXT.md` | Perspective-warp unit: code/synthetic tests complete; real-photo/catalog acceptance still pending |
| `docs/CLAUDE-CODE-AGENT-EVALUATION.md` | 2026-07-19 independent code, evidence, safety, and agent-work evaluation |
| `docs/FOOTER-OCR-AUDIT-2026-07-19.md` | Source-backed audit of the claimed footer failures, real Mime Jr. regression, and unavailable-case handoff |
| `AGENT-RELAY.md` | Chronological work log between CC (Claude Code) and CX (Codex). Read bottom-up |
| `LESSONS.md` | 49 permanent lessons — every closed mistake, L1–L49 |
| `FAILURES.md` | Per-card failure database (auto-maintained; every non-Level-A ID gets a record) |
| `VISION.md` | Product vision / where this is going |
| `docs/archive/` | Completed unit specs, kept for their acceptance criteria |

## Working agreement (CC ↔ CX)

- Every unit: implement → verify against REAL data (not just unit tests) →
  honest numbers in `AGENT-RELAY.md` (numbers, not adjectives) → local commit.
- **Never push without Yujin's explicit instruction.**
- Every closed mistake becomes a permanent test in `tests.py` + a lesson in
  `LESSONS.md`. Nothing fails twice.
- Full suite must stay green: `python tests.py` (145 total: 142 passed,
  3 explicit skips, 0 failed on this checkout as of 2026-07-19; see
  `PROGRESS.md` for environment limits).

## Dashboard access

The safe default is localhost-only. If `DASHBOARD_AUTH_TOKEN` is empty or
absent, `app.py` binds to `127.0.0.1`; direct local use needs no login and all
remote requests are rejected. For trusted phone/LAN access, put a long random
token in gitignored `config.py` (or the environment), restart the dashboard,
and use browser Basic Auth with username `pokestop` and the token as password.

Do not expose raw port 5000 to the internet. On a remote VM, keep it closed and
use the SSH tunnel in `deploy/README.md`. The server ignores forwarding headers
for its localhost exception so a proxy assertion cannot silently grant access.

User-entered listing/search URLs are HTTPS-only and restricted to parsed
Carousell/Facebook host boundaries with public-DNS checks. Scraped image
downloads revalidate redirects and enforce a byte budget. This is defense in
depth, not a claim of DNS-rebinding-proof transport or a general-purpose URL
fetcher; keep the dashboard on a trusted/private network.

Direct uploads are capped at 12 MB before OCR. Direct and listing-photo images
must decode as JPEG/PNG/BMP/WebP, stay within a 12,000-pixel edge and 40-million
pixel area, and pass integrity plus bounded decode checks. Accepted files use
UUID names and their actual image type; rejected temporary files are removed.
Automated upload retention and resource metrics are not implemented yet.

Failure records and user-confirmed reference JSON use `state_store.py`: one
thread/process lock covers the full mutation and same-directory fsync + atomic
replace prevents partial documents. This guarantee has not yet been migrated
to every JSON/SQLite writer; see F-10 in the evaluation and `PROGRESS.md`.

The test module snapshots `FAILURES.md` and every top-level `dataset/*.json`
before and after a run. A content/file-set change fails the suite, while source
edits and private upload contents stay outside this guard.

Deterministic tests also block Requests and in-process socket connections and
fail at module teardown even when application fallback catches the error. Live
integration tests must opt in explicitly with `POKESTOP_TEST_ALLOW_NETWORK=1`.

## Per-machine setup notes

Machine-local files that are **NOT in git** (each machine needs its own):

| File | How to get it |
|---|---|
| `config.py` | Copy `config.example.py`, fill in webhook/token. Keep keys current — new settings are added to the example |
| `fingerprints.sqlite` | Build with `python build_fingerprints.py` (downloads pokemon-tcg-data), then `python build_visual_catalog.py` for the perceptual-hash columns (long; resumable) |
| `uploads/`, `ocr_cache.sqlite`, `seen.sqlite` | Created at runtime |
| Secrets | `local-secrets/low-sale-finder.env.local` (bot token etc.) — never in the repo |

Deps: `pip install -r requirements.txt` plus `python -m playwright install chromium`.

## Original Carousell sniper configuration (still applies to process 1)

- `SEARCH_QUERIES` / `CAROUSELL_CATEGORY_URLS` / `CAROUSELL_COUNTRY` in `config.py`
- Deal rule: `ALERT_AT_OR_BELOW_FRACTION` (default 0.80 = 20% under market),
  `ALERT_STEAL_FRACTION` (0.25 = STEAL), `MIN_ABSOLUTE_SAVINGS`
- Price chain: `manual_prices.csv` → TCGplayer → PriceCharting; USD→PHP now
  uses a live hourly-cached rate (`exchange_rate.py`) with honest fallbacks
- Test one pass: `python main.py --once`. Don't lower `POLL_INTERVAL_MINUTES`
  aggressively — ToS/IP-ban risk. First run alerts on backlog; dedup lives in
  `seen.sqlite`
