# Carousell Pokémon Card Sniper

Scans Carousell for Pokémon card listings, compares each to its market value,
and pings a Discord webhook when a listing is **≥20% below market** (configurable),
with a louder **🔥 STEAL** alert when it's **≥75% off**.

## What you get
- `config.py` — all your settings (edit this).
- `scraper.py` — Carousell scraper (Playwright).
- `prices.py` — market-value lookup (3 backends).
- `main.py` — the loop + Discord alerts.
- `manual_prices.csv` — fallback price list when you have no API key.

---

## 1. Install (one time)

You need Python 3.10+.

```bash
pip install playwright rapidfuzz requests
python -m playwright install chromium
```

## 2. Get a Discord webhook
In your Discord server: **Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.**
Paste it into `DISCORD_WEBHOOK_URL` in `config.py`.

## 3. Pick a price source (in `config.py` → `PRICE_SOURCE`)

| Option | What it is | Cost | Notes |
|---|---|---|---|
| `"manual"` | You list cards + values in `manual_prices.csv` | free | Best for testing. Fuzzy-matches listing titles to your keywords. |
| `"pokemonpricetracker"` | Pokémon-specific API w/ title parsing | free tier | Get a key at pokemonpricetracker.com. Best automated option. |
| `"pricecharting"` | PriceCharting API | paid sub | 40-char token from your account settings. Video-game-centric. |

API prices come back in **USD** — set `USD_TO_LOCAL_RATE` to convert
(e.g. ~58 for PHP, ~1.35 for SGD). Check a live rate.

## 4. Set your country + searches
- `CAROUSELL_COUNTRY`: `"ph"`, `"sg"`, `"my"`, etc.
- `SEARCH_QUERIES`: the searches to run.
- `CAROUSELL_CATEGORY_URLS`: optional full Carousell category page URLs to scan in addition to keyword searches.

## 5. Tune the deal rule
- `ALERT_AT_OR_BELOW_FRACTION = 0.80` → alert at ≥20% under market.
- `ALERT_STEAL_FRACTION = 0.25` → "STEAL" alert at ≥75% off.
- `MIN_ABSOLUTE_SAVINGS` → ignore trivially small savings.

## 6. Run

Test a single pass first (watch the browser by setting `HEADLESS = False`):
```bash
python main.py --once
```
Then run continuously:
```bash
python main.py
```

---

## Notes & gotchas
- **Carousell markup changes.** If you stop getting results, set `HEADLESS = False`,
  run `--once`, watch what loads, and update the selectors in `scraper.py → extract_listings()`.
- **Matching is the hard part.** Grade (PSA/BGS) and edition drastically change value.
  `prices.py` detects grades from titles; manual mode relies on your keywords being specific.
- **Be polite.** Don't drop `POLL_INTERVAL_MINUTES` too low — aggressive polling risks
  IP/account blocks and violates Carousell's ToS. This is for personal use.
- **First run** will alert on a backlog of existing listings; after that it only pings new ones (tracked in `seen.sqlite`).
