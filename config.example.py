"""
config.py — all your settings live here. Edit this, not the other files.
"""

# ─────────────────────────────────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────────────────────────────────
# Paste your Discord webhook URL here (Server Settings → Integrations → Webhooks → New Webhook → Copy URL)
DISCORD_WEBHOOK_URL = "PASTE_YOUR_DISCORD_WEBHOOK_URL_HERE"

# ─────────────────────────────────────────────────────────────────────
# WHAT TO SEARCH ON CAROUSELL
# ─────────────────────────────────────────────────────────────────────
# Each string is one Carousell search. Add/remove freely.
# Broad terms catch more but need good price-matching; specific terms are cleaner.
SEARCH_QUERIES = [
    "pokemon",
    "pokemon card",
    "pokemon psa",
    "pokemon booster",
    "pokemon holo",
]

# Optional Carousell category page URLs to scan in addition to keyword searches.
# Use this when you want to scan a full category or collection page for Pokémon cards.
CAROUSELL_CATEGORY_URLS = [
    "https://www.carousell.ph/search/pokemon%20cards?sort_by=3&t-search_query_source=ss_dropdown",
]

# Carousell country site. "sg" = Singapore, "ph" = Philippines, "my" = Malaysia, etc.
CAROUSELL_COUNTRY = "ph"

# Only consider listings at or below this price (in local currency). Set None to disable.
MAX_LISTING_PRICE = None
# Ignore listings below this price (filters junk/bulk lots priced at 1). Set None to disable.
MIN_LISTING_PRICE = 5
# Fake "message me" prices sellers use instead of a real number — never alert on these.
PLACEHOLDER_PRICES = {123, 1234, 12345, 123456, 1234567, 111111, 999999}

# ─────────────────────────────────────────────────────────────────────
# THE DEAL RULE — when do you get pinged?
# ─────────────────────────────────────────────────────────────────────
# Alert if the listing price is AT OR BELOW this fraction of market value.
# 0.25  => "75% off"  (price is 25% of market)
# 0.80  => "20% below market" (price is 80% of market)
# The tool alerts if EITHER condition below is met.
ALERT_AT_OR_BELOW_FRACTION = 0.80   # i.e. >=20% under market
ALERT_STEAL_FRACTION       = 0.25   # i.e. >=75% off  (separate louder alert)

# Don't bother alerting on tiny absolute savings even if the % looks good.
MIN_ABSOLUTE_SAVINGS = 3.0  # in local currency

# ─────────────────────────────────────────────────────────────────────
# PRICE SOURCE — pick one: "pokemonpricetracker", "pricecharting", or "manual"
# ─────────────────────────────────────────────────────────────────────
PRICE_SOURCE = "manual"

# For PokemonPriceTracker (free tier available at pokemonpricetracker.com)
POKEMONPRICETRACKER_API_KEY = "PASTE_KEY_HERE"

# For PriceCharting (paid subscription -> 40-char token in account settings)
PRICECHARTING_TOKEN = "PASTE_40_CHAR_TOKEN_HERE"

# Currency conversion: market APIs return USD. Multiply by this to compare to local listings.
# e.g. for PHP set ~58.0; for SGD ~1.35. Check a live rate.
USD_TO_LOCAL_RATE = 58.0

# If PRICE_SOURCE == "manual", prices are read from manual_prices.csv (see that file).

# ─────────────────────────────────────────────────────────────────────
# RUNTIME
# ─────────────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES = 20      # how often to re-scan
HEADLESS = True                 # set False to watch the browser (useful first run / debugging)
SEEN_DB_PATH = "seen.sqlite"    # tracks already-alerted listings so you aren't spammed
REQUEST_DELAY_SECONDS = 4       # polite pause between searches
