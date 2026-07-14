"""
engine.py — the reusable scan engine.
Both the CLI (main.py) and the web app (app.py) call run_scan().
A scan = scrape one or more queries, price-match, filter by threshold, return deals
(and optionally push them to Discord). Thresholds can be passed per-call, overriding config.
"""
import time
import sqlite3

import config
import scraper
import prices
import requests


def _db():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS seen (url TEXT PRIMARY KEY, ts REAL)")
    return conn

def _seen(conn, url):
    return conn.execute("SELECT 1 FROM seen WHERE url=?", (url,)).fetchone() is not None

def _mark(conn, url):
    conn.execute("INSERT OR IGNORE INTO seen (url, ts) VALUES (?, ?)", (url, time.time()))
    conn.commit()


def discord_post(deal):
    wh = config.DISCORD_WEBHOOK_URL
    if not wh or "PASTE" in wh:
        return False, "no webhook configured"
    pct_off = deal["pct_off"]
    steal = deal["steal"]
    embed = {
        "title": f"{'🔥 STEAL' if steal else '💰 Deal'}: {deal['title'][:230]}",
        "url": deal["url"],
        "color": 0xE74C3C if steal else 0x2ECC71,
        "fields": [
            {"name": "Listing price", "value": f"{deal['price']:.0f}", "inline": True},
            {"name": "Market (est.)", "value": f"{deal['market']:.0f}", "inline": True},
            {"name": "Discount", "value": f"{pct_off:.0f}% off", "inline": True},
            {"name": "Match source", "value": deal["label"], "inline": False},
        ],
    }
    if deal.get("posted"):
        ep = scraper.posted_epoch(deal["posted"])
        val = f"<t:{ep}:R>" if ep else deal["posted"]
        embed["fields"].append({"name": "Posted", "value": ("bumped · " if deal.get("bumped") else "") + val, "inline": False})
    if deal.get("image"):
        embed["image"] = {"url": deal["image"]}
    try:
        r = requests.post(wh, json={"embeds": [embed]}, timeout=15)
        return (r.status_code in (200, 204)), f"status {r.status_code}"
    except Exception as e:
        return False, str(e)


def run_scan(queries, *, below_fraction=None, steal_fraction=None,
             min_price=None, max_price=None, min_savings=None,
             push_discord=True, respect_seen=True, progress=None):
    """
    Scrape + evaluate. Returns a list of deal dicts.
    Threshold args default to config values when None.
    `progress` is an optional callable(str) for status updates (used by the web UI).
    """
    below = config.ALERT_AT_OR_BELOW_FRACTION if below_fraction is None else below_fraction
    steal_f = config.ALERT_STEAL_FRACTION if steal_fraction is None else steal_fraction
    minp = config.MIN_LISTING_PRICE if min_price is None else min_price
    maxp = config.MAX_LISTING_PRICE if max_price is None else max_price
    minsav = config.MIN_ABSOLUTE_SAVINGS if min_savings is None else min_savings

    def log(msg):
        if progress:
            progress(msg)
        print(msg)

    conn = _db()
    deals = []
    for q in queries:
        log(f"Searching: {q}")
        try:
            listings = scraper.search(q)
        except Exception as e:
            log(f"  scrape failed: {e}")
            continue
        log(f"  {len(listings)} priced listings found")

        for L in listings:
            p = L["price"]
            if minp and p < minp:
                continue
            if maxp and p > maxp:
                continue
            if p in getattr(config, "PLACEHOLDER_PRICES", set()):
                continue
            if L.get("status") in ("sold", "reserved"):
                continue  # nothing to snipe
            if respect_seen and _seen(conn, L["url"]):
                continue

            market, label = prices.market_value(L["title"])
            if not market or market <= 0:
                continue
            fraction = p / market
            savings = market - p
            if savings < minsav:
                continue
            if fraction > below:   # not under threshold -> skip
                continue

            deal = {
                "title": L["title"],
                "url": L["url"],
                "price": p,
                "market": market,
                "fraction": fraction,
                "pct_off": (1 - fraction) * 100,
                "steal": fraction <= steal_f,
                "label": label,
                "image": L.get("image", ""),
                "posted": L.get("posted", ""),
                "bumped": L.get("bumped", False),
            }
            deals.append(deal)

            pushed = False
            if push_discord:
                pushed, _ = discord_post(deal)
            if respect_seen:
                _mark(conn, L["url"])
            deal["pushed"] = pushed
            log(f"  DEAL: {L['title'][:50]} @ {p:.0f} ({deal['pct_off']:.0f}% off)"
                + (" [sent]" if pushed else ""))
        time.sleep(config.REQUEST_DELAY_SECONDS)

    deals.sort(key=lambda d: d["fraction"])  # best deals first
    log(f"Done. {len(deals)} deal(s).")
    return deals
