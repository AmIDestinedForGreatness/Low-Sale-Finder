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
| `HASH-FIRST-NEXT.md` | The ACTIVE next work unit (perspective-warp before hashing) |
| `AGENT-RELAY.md` | Chronological work log between CC (Claude Code) and CX (Codex). Read bottom-up |
| `LESSONS.md` | 39 permanent lessons — every closed mistake, L1–L39 |
| `FAILURES.md` | Per-card failure database (auto-maintained; every non-Level-A ID gets a record) |
| `VISION.md` | Product vision / where this is going |
| `docs/archive/` | Completed unit specs, kept for their acceptance criteria |

## Working agreement (CC ↔ CX)

- Every unit: implement → verify against REAL data (not just unit tests) →
  honest numbers in `AGENT-RELAY.md` (numbers, not adjectives) → local commit.
- **Never push without Yujin's explicit instruction.**
- Every closed mistake becomes a permanent test in `tests.py` + a lesson in
  `LESSONS.md`. Nothing fails twice.
- Full suite must stay green: `python tests.py` (123 tests as of 2026-07-18).

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
