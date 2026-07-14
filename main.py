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
    # feed message ids, so sold/reserved changes can edit the original Discord message
    conn.execute("CREATE TABLE IF NOT EXISTS feed_msgs (url TEXT PRIMARY KEY, msg_id TEXT, status TEXT, ts REAL)")
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
        ep = scraper.posted_epoch(listing["posted"])
        val = f"<t:{ep}:R>" if ep else listing["posted"]
        embed["fields"].append({"name": "Posted", "value": ("bumped · " if listing.get("bumped") else "") + val, "inline": False})
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
    if listing.get("status") in ("sold", "reserved"):
        return  # nothing to snipe

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
STATUS_STYLE = {
    "reserved": ("🔒 RESERVED — ", 0xF39C12),  # orange
    "sold":     ("✅ SOLD — ", 0x95A5A6),      # gray
}

def feed_embed(L):
    prefix, color = STATUS_STYLE.get(L.get("status", ""), ("", 0x3B6CFF))
    epoch = scraper.posted_epoch(L.get("posted", ""))
    # <t:..:R> renders as Discord's native "5 hours ago" (auto-updating,
    # hover shows the full date); fall back to raw text if unparseable
    when = f"<t:{epoch}:R>" if epoch else (L.get("posted") or "time unknown")
    if L.get("bumped"):
        when = f"bumped {when}"
    else:
        when = f"posted {when}"
    e = {
        "title": (prefix + L["title"])[:230],
        "url": L["url"],
        "description": f"₱{L['price']:,.0f} · {when}\n{L['url']}",
        "color": color,
    }
    if L.get("image"):
        e["image"] = {"url": L["image"]}
    return e


def feed_once(conn):
    targets = list(config.SEARCH_QUERIES) + getattr(config, "CAROUSELL_CATEGORY_URLS", [])
    wh = config.DISCORD_WEBHOOK_URL
    have_wh = wh and "PASTE" not in wh
    for q in targets:
        print(f"[feed] {q}")
        try:
            listings = scraper.search(q)
        except Exception as e:
            print(f"  [scrape failed] {e}")
            continue

        # 1) edit previously-sent messages whose sold/reserved state changed
        if have_wh:
            for L in listings:
                row = conn.execute("SELECT msg_id, status FROM feed_msgs WHERE url=?",
                                   (L["url"],)).fetchone()
                if not row or not row[0]:
                    continue
                if (L.get("status") or "") == (row[1] or ""):
                    continue
                try:
                    r = requests.patch(f"{wh}/messages/{row[0]}",
                                       json={"embeds": [feed_embed(L)]}, timeout=15)
                    if r.status_code == 200:
                        conn.execute("UPDATE feed_msgs SET status=? WHERE url=?",
                                     (L.get("status") or "", L["url"]))
                        conn.commit()
                        print(f"  STATUS -> {(L.get('status') or 'active').upper()}: {L['title'][:50]}".encode("ascii", "replace").decode())
                    else:
                        print(f"  [discord edit {r.status_code}] {r.text[:120]}")
                except Exception as e:
                    print(f"  [discord edit error] {e}")

        # 2) send new listings (one message each so we can edit them later)
        new = [L for L in listings if not already_seen(conn, L["url"], "seen_feed")]
        print(f"  {len(new)} new listing(s)")
        for L in new:
            if not have_wh:
                print(f"    P{L['price']:,.0f} | {L['title'][:60]} | {L['url']}")
                mark_seen(conn, L["url"], "seen_feed")
                continue
            try:
                r = requests.post(wh + "?wait=true", json={"embeds": [feed_embed(L)]}, timeout=15)
                if r.status_code == 429:
                    wait = float(r.json().get("retry_after", 5))
                    print(f"  [discord rate-limited, waiting {wait}s]")
                    time.sleep(wait)
                    r = requests.post(wh + "?wait=true", json={"embeds": [feed_embed(L)]}, timeout=15)
                msg_id = r.json().get("id") if r.status_code == 200 else None
                if r.status_code not in (200, 204):
                    print(f"  [discord {r.status_code}] {r.text[:150]}")
                conn.execute("INSERT OR REPLACE INTO feed_msgs (url, msg_id, status, ts) VALUES (?,?,?,?)",
                             (L["url"], msg_id, L.get("status") or "", time.time()))
                conn.commit()
            except Exception as e:
                print(f"  [discord error] {e}")
            mark_seen(conn, L["url"], "seen_feed")
            time.sleep(1.3)  # ~30 messages/min webhook budget
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
