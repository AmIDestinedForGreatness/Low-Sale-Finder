"""
main.py — ties it together: scrape → price-match → filter → Discord alert.
Run with:  python main.py                 (continuous deal-alert loop)
           python main.py --once          (single deal pass, good for testing)
           python main.py --feed          (continuous feed: EVERY new listing → Discord, photo + price + link)
           python main.py --feed --once   (single feed pass)
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
    # feed mode tracks separately so a feed pass doesn't suppress future deal alerts
    conn.execute("CREATE TABLE IF NOT EXISTS seen_feed (url TEXT PRIMARY KEY, ts REAL)")
    return conn

def already_seen(conn, url, table="seen"):
    return conn.execute(f"SELECT 1 FROM {table} WHERE url=?", (url,)).fetchone() is not None

def mark_seen(conn, url, table="seen"):
    conn.execute(f"INSERT OR IGNORE INTO {table} (url, ts) VALUES (?, ?)", (url, time.time()))
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
    if listing.get("posted"):
        embed["fields"].append({"name": "Posted", "value": ("bumped · " if listing.get("bumped") else "") + listing["posted"], "inline": False})
    if listing.get("image"):
        embed["image"] = {"url": listing["image"]}
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


# ── feed mode: EVERY new listing → Discord (photo + price + link) ─────
def feed_once(conn):
    targets = list(config.SEARCH_QUERIES) + getattr(config, "CAROUSELL_CATEGORY_URLS", [])
    wh = config.DISCORD_WEBHOOK_URL
    for q in targets:
        print(f"[feed] {q}")
        try:
            listings = scraper.search(q)
        except Exception as e:
            print(f"  [scrape failed] {e}")
            continue
        new = [L for L in listings if not already_seen(conn, L["url"], "seen_feed")]
        print(f"  {len(new)} new listing(s)")
        if not wh or "PASTE" in wh:
            for L in new:
                print(f"    P{L['price']:,.0f} | {L['title'][:60]} | {L['url']}")
                mark_seen(conn, L["url"], "seen_feed")
            continue
        # Discord allows up to 10 embeds per message; batch + pause for rate limits
        for i in range(0, len(new), 10):
            batch = new[i:i + 10]
            embeds = []
            for L in batch:
                when = L.get("posted") or "time unknown"
                if L.get("bumped"):
                    when = f"bumped · {when}"
                e = {
                    "title": L["title"][:230],
                    "url": L["url"],
                    "description": f"₱{L['price']:,.0f} · {when}\n{L['url']}",
                    "color": 0x3B6CFF,
                }
                if L.get("image"):
                    e["image"] = {"url": L["image"]}
                embeds.append(e)
            try:
                r = requests.post(wh, json={"embeds": embeds}, timeout=15)
                if r.status_code == 429:
                    wait = float(r.json().get("retry_after", 5))
                    print(f"  [discord rate-limited, waiting {wait}s]")
                    time.sleep(wait)
                    r = requests.post(wh, json={"embeds": embeds}, timeout=15)
                if r.status_code not in (200, 204):
                    print(f"  [discord {r.status_code}] {r.text[:150]}")
            except Exception as e:
                print(f"  [discord error] {e}")
            for L in batch:
                mark_seen(conn, L["url"], "seen_feed")
            time.sleep(2)
        time.sleep(config.REQUEST_DELAY_SECONDS)


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
    feed = "--feed" in sys.argv
    step = feed_once if feed else run_once
    label = "feed (all new listings)" if feed else "deal alerts"
    if once:
        step(conn)
        print("Done (single pass).")
        return
    print(f"Starting {label} loop — scanning every {config.POLL_INTERVAL_MINUTES} min. Ctrl+C to stop.")
    while True:
        step(conn)
        print(f"[sleep] {config.POLL_INTERVAL_MINUTES} min…")
        time.sleep(config.POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
