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
    "pokemon tcg",
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
# PRICE SOURCE — "manual", "pokemontcgio", "pokemonpricetracker", "pricecharting"
#   "pokemontcgio" = manual CSV first (your PH prices win), then the free
#   pokemontcg.io card database (TCGplayer market prices, EN sets only,
#   needs a collector number like 163/132 in the title to match).
# ─────────────────────────────────────────────────────────────────────
PRICE_SOURCE = "tcgplayer"

# Optional free API key from https://dev.pokemontcg.io — raises the rate
# limit a lot; without one you get ~1000 requests/day (cache softens this).
POKEMONTCGIO_API_KEY = ""

# For PokemonPriceTracker (free tier available at pokemonpricetracker.com)
POKEMONPRICETRACKER_API_KEY = "PASTE_KEY_HERE"

# For PriceCharting (paid subscription -> 40-char token in account settings)
PRICECHARTING_TOKEN = "PASTE_40_CHAR_TOKEN_HERE"

# Currency conversion: market APIs return USD. Multiply by this to compare to local listings.
# e.g. for PHP set ~58.0; for SGD ~1.35. Check a live rate.
USD_TO_LOCAL_RATE = 58.0

# If PRICE_SOURCE == "manual", prices are read from manual_prices.csv (see that file).

# ─────────────────────────────────────────────────────────────────────
# FACEBOOK (BURNER ACCOUNT ONLY — never the main account)
# The burner WILL eventually get checkpointed/banned; it is disposable.
# Login: run `python fb_login.py` once (manual login, session saved locally).
# ─────────────────────────────────────────────────────────────────────
FB_PROFILE_DIR = "fb_profile"   # saved browser session (gitignored)
FB_MARKETPLACE_URL = ""         # marketplace off for now; groups are the target
FB_GROUP_URLS = [
    "https://www.facebook.com/groups/712817202659840",       # PH Pokemon Collectibles Buy And Sell (100k+) — main
    "https://www.facebook.com/groups/1220161206001059",      # PH Pokemon TCG Buy And Sell
    "https://www.facebook.com/groups/pokemoncardsph",        # Pokemon Cards and Collectibles PH
    "https://www.facebook.com/groups/757662856831328",       # PH Pokémon Trading Card Buy And Sell
    "https://www.facebook.com/groups/255062901835978",       # TCG Pokemon PH - Buy, Sell, Trade
    "https://www.facebook.com/groups/1428808095151910",      # Pokemon TCG Buy and Sell
    "https://www.facebook.com/groups/856851463654793",       # PH Pokemon TCG Buy & Sell
    "https://www.facebook.com/groups/2147623355529187",      # Pokemon Cards Buy and Sell PH
    "https://www.facebook.com/groups/1231187172158802",      # Pokémon TCG Community Philippines
    "https://www.facebook.com/groups/707983542163899",       # PH Pokemon Collectibles (BackUp)
    "https://www.facebook.com/groups/573677660024569",       # POKEMON MARKET PH
    "https://www.facebook.com/groups/1503039711219183",      # Pokemon's Collectors Club PH
    "https://www.facebook.com/groups/635711927366699",       # Pokemon TCG PH Buy And Sell
    "https://www.facebook.com/groups/1279723869863691",      # The Pokemon Center PH
    "https://www.facebook.com/groups/1635366023985175",      # POKEMON TCG PH
]
FB_POLL_MINUTES = 30            # cycle through all groups; jitter added
FB_HEADLESS = True              # background operation (aged logged-in account)
FB_DEAL_FRACTION = 0.78         # mass-ping when price <= 78% of TCGplayer market x rate
FB_MAX_POSTS_PER_GROUP = 20     # recent posts to inspect per group per pass
# Separate Discord webhook for AUCTIONS (own channel). Blank = use the main one.
FB_AUCTION_WEBHOOK = ""
# Ping this many minutes before an auction's parsed end time.
FB_AUCTION_WARN_MINUTES = 10

# ─────────────────────────────────────────────────────────────────────
# RUNTIME
# ─────────────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES = 10      # how often to re-scan
HEADLESS = True                 # set False to watch the browser (useful first run / debugging)
SEEN_DB_PATH = "seen.sqlite"    # tracks already-alerted listings so you aren't spammed
REQUEST_DELAY_SECONDS = 4       # polite pause between searches

# Discord bot token for react-to-track — loaded from local-secrets (never in repo)
def _load_bot_token():
    import os
    p = os.path.expanduser(r"~/.claude/local-secrets/low-sale-finder.env.local")
    try:
        for line in open(p, encoding="utf-8"):
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""
DISCORD_BOT_TOKEN = _load_bot_token()
