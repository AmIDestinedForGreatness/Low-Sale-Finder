"""
main.py — ties it together: scrape → price-match → filter → Discord alert.
Run with:  python main.py            (continuous loop)
           python main.py --once     (single pass, good for testing)
"""
import sys
import time
import sqlite3
import requests

import config
import scraper
import prices


# ── seen DB so we don't re-alert the same listing ─────────────────────
def db():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS seen (url TEXT PRIMARY KEY, ts REAL)")
    return conn

def already_seen(conn, url):
    return conn.execute("SELECT 1 FROM seen WHERE url=?", (url,)).fetchone() is not None

def mark_seen(conn, url):
    conn.execute("INSERT OR IGNORE INTO seen (url, ts) VALUES (?, ?)", (url, time.time()))
    conn.commit()


# ── Discord ───────────────────────────────────────────────────────────
def notify(listing, market, fraction, label, steal):
    wh = config.DISCORD_WEBHOOK_URL
    if not wh or "PASTE" in wh:
        print("  [!] No Discord webhook set — printing instead:")
        print(f"      {listing['title']} | {listing['price']} vs market {market:.0f} "
              f"({fraction*100:.0f}% of market) | {listing['url']}")
        return
    pct_off = (1 - fraction) * 100
    color = 0xE74C3C if steal else 0x2ECC71  # red for steals, green otherwise
    title_prefix = "🔥 STEAL" if steal else "💰 Deal"
    embed = {
        "title": f"{title_prefix}: {listing['title'][:230]}",
        "url": listing["url"],
        "color": color,
        "fields": [
            {"name": "Listing price", "value": f"{listing['price']:.0f}", "inline": True},
            {"name": "Market (est.)", "value": f"{market:.0f}", "inline": True},
            {"name": "Discount", "value": f"{pct_off:.0f}% off", "inline": True},
            {"name": "Match source", "value": label, "inline": False},
        ],
    }
    try:
        r = requests.post(wh, json={"embeds": [embed]}, timeout=15)
        if r.status_code not in (200, 204):
            print(f"  [discord {r.status_code}] {r.text[:200]}")
    except Exception as e:
        print(f"  [discord error] {e}")


# ── evaluate one listing against the rules ────────────────────────────
def evaluate(listing, conn):
    if already_seen(conn, listing["url"]):
        return
    p = listing["price"]
    if config.MIN_LISTING_PRICE and p < config.MIN_LISTING_PRICE:
        return
    if config.MAX_LISTING_PRICE and p > config.MAX_LISTING_PRICE:
        return
    if p in getattr(config, "PLACEHOLDER_PRICES", set()):
        return

    market, label = prices.market_value(listing["title"])
    if not market or market <= 0:
        return  # can't price it -> skip (don't spam unknowns)

    fraction = p / market
    savings = market - p
    if savings < config.MIN_ABSOLUTE_SAVINGS:
        return

    steal = fraction <= config.ALERT_STEAL_FRACTION
    deal = fraction <= config.ALERT_AT_OR_BELOW_FRACTION
    if deal or steal:
        print(f"  ALERT {'STEAL' if steal else 'deal'}: {listing['title'][:60]} "
              f"@ {p:.0f} vs {market:.0f} ({fraction*100:.0f}%)")
        notify(listing, market, fraction, label, steal)
        mark_seen(conn, listing["url"])


def run_once(conn):
    targets = list(config.SEARCH_QUERIES) + getattr(config, "CAROUSELL_CATEGORY_URLS", [])
    for q in targets:
        print(f"[search] {q}")
        try:
            listings = scraper.search(q)
        except Exception as e:
            print(f"  [scrape failed] {e}")
            continue
        print(f"  found {len(listings)} priced listings")
        for L in listings:
            evaluate(L, conn)
        time.sleep(config.REQUEST_DELAY_SECONDS)


def main():
    conn = db()
    once = "--once" in sys.argv
    if once:
        run_once(conn)
        print("Done (single pass).")
        return
    print(f"Starting loop — scanning every {config.POLL_INTERVAL_MINUTES} min. Ctrl+C to stop.")
    while True:
        run_once(conn)
        print(f"[sleep] {config.POLL_INTERVAL_MINUTES} min…")
        time.sleep(config.POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
