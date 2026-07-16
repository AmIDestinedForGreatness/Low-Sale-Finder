"""
main.py — ties it together: scrape → price-match → filter → Discord alert.
Run with:  python main.py                 (continuous deal-alert loop)
           python main.py --once          (single deal pass, good for testing)
           python main.py --feed          (continuous feed: EVERY new listing → Discord, photo + price + link)
           python main.py --feed --once   (single feed pass)
"""
import datetime
import json
import os
import sys
import time
import sqlite3
import requests
from collections import Counter

import config
import scraper
import prices
from version import VERSION

# heartbeat/status file the dashboard reads to show ONLINE/OFFLINE + countdown
STATUS_PATH = os.path.join(os.path.dirname(__file__), "feed_status.json")

def _read_status():
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_status(**kw):
    s = _read_status()
    s.update(kw, heartbeat=time.time(), version=VERSION)
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f)
    os.replace(tmp, STATUS_PATH)


# ── seen DB so we don't re-alert the same listing ─────────────────────
def db():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS seen (url TEXT PRIMARY KEY, ts REAL)")
    # feed mode tracks separately so a feed pass doesn't suppress future deal alerts
    conn.execute("CREATE TABLE IF NOT EXISTS seen_feed (url TEXT PRIMARY KEY, ts REAL)")
    # feed message ids, so sold/reserved changes can edit the original Discord message
    conn.execute("CREATE TABLE IF NOT EXISTS feed_msgs (url TEXT PRIMARY KEY, msg_id TEXT, status TEXT, ts REAL)")
    try:  # v0.2 migration: track prices for drop detection
        conn.execute("ALTER TABLE feed_msgs ADD COLUMN price REAL")
    except sqlite3.OperationalError:
        pass
    # every sent listing, for the daily digest + stats history
    conn.execute("CREATE TABLE IF NOT EXISTS feed_log "
                 "(url TEXT, title TEXT, price REAL, category TEXT, ts REAL)")
    for mig in ("ALTER TABLE feed_log ADD COLUMN source TEXT",
                "ALTER TABLE feed_log ADD COLUMN posted_ts REAL"):
        try:  # v0.4: dashboard recent-list shows source + real upload time
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass
    return conn



def already_seen(conn, url, table="seen"):
    return conn.execute(f"SELECT 1 FROM {table} WHERE url=?", (url,)).fetchone() is not None

def mark_seen(conn, url, table="seen"):
    conn.execute(f"INSERT OR IGNORE INTO {table} (url, ts) VALUES (?, ?)", (url, time.time()))
    conn.commit()

def claim(conn, url, table="seen"):
    """Atomically claim a listing before sending it. Returns True only for the
    caller that actually inserted the row — so a second process (or pass)
    racing the same URL gets False and skips, preventing duplicate posts."""
    cur = conn.execute(f"INSERT OR IGNORE INTO {table} (url, ts) VALUES (?, ?)",
                       (url, time.time()))
    conn.commit()
    return cur.rowcount == 1


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
    if scraper.is_merch(listing.get("title", "") + " " + listing.get("raw", "")):
        return  # merch, not cards

    market, label = prices.market_value(listing["title"])
    if not market or market <= 0:
        return  # can't price it -> skip (don't spam unknowns)

    fraction = p / market
    savings = market - p
    if savings < config.MIN_ABSOLUTE_SAVINGS:
        return
    if fraction < 0.15:
        # a "1% of market" listing is a WRONG MATCH, not a snipe (a toy
        # Lucario got priced as a P22k booster box) — never @everyone on it
        print(f"  [mismatch guard] {listing['title'][:50]} @ {p:.0f} vs "
              f"{market:.0f} ({fraction*100:.0f}%) — implausible, skipping")
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
    # classify on title + the rest of the card text (condition/snippet) —
    # sellers often only say "bulk"/"take all"/"binder" outside the title
    cat, cat_color, icon = scraper.classify(
        (L.get("title", "") + " " + L.get("raw", "")).strip())
    prefix, status_color = STATUS_STYLE.get(L.get("status", ""), ("", None))
    epoch = scraper.posted_epoch(L.get("posted", ""))
    # <t:..:R> renders as Discord's native "5 hours ago" (auto-updating,
    # hover shows the full date); fall back to raw text if unparseable
    when = f"<t:{epoch}:R>" if epoch else (L.get("posted") or "time unknown")
    when = ("bumped " if L.get("bumped") else "posted ") + when
    e = {
        # title is already the clickable link — no raw URL in the body
        "title": (prefix + icon + " " + L["title"])[:230],
        "url": L["url"],
        "description": f"₱{L['price']:,.0f} · {cat.upper()} · {when}",
        "color": status_color if status_color else cat_color,
    }
    if L.get("image"):
        e["image"] = {"url": L["image"]}
    return e


def feed_once(conn):
    targets = list(config.SEARCH_QUERIES) + getattr(config, "CAROUSELL_CATEGORY_URLS", [])
    wh = config.DISCORD_WEBHOOK_URL
    have_wh = wh and "PASTE" not in wh
    sent = []
    for q in targets:
        print(f"[feed] {q}")
        try:
            listings = scraper.search(q)
        except Exception as e:
            print(f"  [scrape failed] {e}")
            continue

        # 1) previously-sent listings: sold/reserved edits + price-drop alerts
        if have_wh:
            for L in listings:
                row = conn.execute("SELECT msg_id, status, price FROM feed_msgs WHERE url=?",
                                   (L["url"],)).fetchone()
                if not row or not row[0]:
                    continue
                msg_id, old_status, old_price = row
                if (L.get("status") or "") != (old_status or ""):
                    try:
                        r = requests.patch(f"{wh}/messages/{msg_id}",
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
                # price drop: seller lowered the price since we posted it
                if old_price and L["price"] < old_price - 0.5 and not L.get("status"):
                    e = feed_embed(L)
                    cut = (1 - L["price"] / old_price) * 100
                    e["title"] = ("\U0001F4B8 PRICE DROP — " + e["title"])[:230]
                    e["description"] = (f"~~₱{old_price:,.0f}~~ → **₱{L['price']:,.0f}** "
                                        f"({cut:.0f}% cut)\n" + e["description"])
                    e["color"] = 0xE91E63
                    try:
                        requests.post(wh, json={"embeds": [e]}, timeout=15)
                        print(f"  PRICE DROP: {L['title'][:45]} {old_price:.0f} -> {L['price']:.0f}".encode("ascii", "replace").decode())
                    except Exception as ex:
                        print(f"  [discord error] {ex}")
                if L["price"] != old_price:
                    conn.execute("UPDATE feed_msgs SET price=? WHERE url=?",
                                 (L["price"], L["url"]))
                    conn.commit()

        # 2) send new listings (one message each so we can edit them later)
        new = [L for L in listings if not already_seen(conn, L["url"], "seen_feed")]
        # cards only — Pokémon merch (plush/hats/figures...) never hits the feed
        merch = [L for L in new
                 if scraper.is_merch(L.get("title", "") + " " + L.get("raw", ""))]
        for L in merch:
            mark_seen(conn, L["url"], "seen_feed")  # don't re-inspect next pass
        new = [L for L in new if L not in merch]
        print(f"  {len(new)} new listing(s)"
              + (f" ({len(merch)} merch filtered)" if merch else ""))
        for L in new:
            # atomic claim: only the process that inserts the row sends it,
            # so a duplicate/racing feed process can't double-post
            if not claim(conn, L["url"], "seen_feed"):
                continue
            if not have_wh:
                print(f"    P{L['price']:,.0f} | {L['title'][:60]} | {L['url']}")
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
                conn.execute("INSERT OR REPLACE INTO feed_msgs (url, msg_id, status, ts, price) VALUES (?,?,?,?,?)",
                             (L["url"], msg_id, L.get("status") or "", time.time(), L["price"]))
                conn.commit()
            except Exception as e:
                print(f"  [discord error] {e}")
            cat = scraper.classify((L.get("title", "") + " " + L.get("raw", "")).strip())[0]
            # real upload time (Carousell's "5 hours ago" → epoch), for the dashboard
            posted_ts = scraper.posted_epoch(L.get("posted", "")) or None
            conn.execute("INSERT INTO feed_log (url, title, price, category, ts, source, posted_ts)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (L["url"], L["title"], L["price"], cat, time.time(),
                          "carousell", posted_ts))
            conn.commit()
            sent.append({
                "title": L["title"], "price": L["price"], "url": L["url"],
                "category": cat, "ts": time.time(),
            })
            time.sleep(1.3)  # ~30 messages/min webhook budget
        time.sleep(config.REQUEST_DELAY_SECONDS)
    recent = (sent[::-1] + (_read_status().get("recent") or []))[:20]  # newest first
    write_status(state="idle", last_scan_end=time.time(), last_new=len(sent), recent=recent)


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
        if feed:
            write_status(state="scanning", scan_started=time.time())
        step(conn)
        if feed:
            write_status(state="idle",
                         next_scan_at=time.time() + config.POLL_INTERVAL_MINUTES * 60)
        print(f"[sleep] {config.POLL_INTERVAL_MINUTES} min…")
        time.sleep(config.POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
