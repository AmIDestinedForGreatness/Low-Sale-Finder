"""
fb_feed.py — Facebook Marketplace + group feeds → Discord (photo, price, link).

Uses the burner session saved by fb_login.py (persistent fb_profile/).
BURNER ACCOUNT ONLY — expect it to get checkpointed or banned eventually;
when that happens, recreate the burner and run fb_login.py again.

Run:  python fb_feed.py --once     (single pass)
      python fb_feed.py            (slow jittered loop — deliberately slower
                                    than the Carousell poll to look human)

First-run note: FB markup changes constantly and can't be tested without a
live logged-in session, so expect to tune the selectors below on the first
real run. Bring the console output back to Claude.
"""
import random
import re
import sqlite3
import sys
import time

import requests
from playwright.sync_api import sync_playwright

import config
import scraper  # classify()/is_merch()/auction/deadend/distress — shared logic
import prices   # best-effort card valuation


def db():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS fb_seen (url TEXT PRIMARY KEY, ts REAL)")
    # active auctions we're tracking for the 10-min-before-end ping
    conn.execute("CREATE TABLE IF NOT EXISTS fb_auctions "
                 "(url TEXT PRIMARY KEY, title TEXT, end_ts REAL, "
                 " under_market INTEGER, warned INTEGER, ts REAL)")
    for col, decl in (("msg_id", "TEXT"), ("tracked", "INTEGER DEFAULT 0"),
                      ("channel_id", "TEXT")):
        try:
            conn.execute(f"ALTER TABLE fb_auctions ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
    return conn

def seen(conn, url):
    return conn.execute("SELECT 1 FROM fb_seen WHERE url=?", (url,)).fetchone() is not None

def mark(conn, url):
    conn.execute("INSERT OR IGNORE INTO fb_seen (url, ts) VALUES (?, ?)", (url, time.time()))
    conn.commit()

def claim(conn, url):
    """Atomic claim — True only for the inserter, so racing processes/passes
    can't double-post the same listing."""
    cur = conn.execute("INSERT OR IGNORE INTO fb_seen (url, ts) VALUES (?, ?)",
                       (url, time.time()))
    conn.commit()
    return cur.rowcount == 1


# ── extraction (first-pass selectors; FB churns markup, tune on first run) ──
MARKETPLACE_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/marketplace/item/"]')) {
    const href = (a.getAttribute('href') || '').split('?')[0];
    if (!href || seen.has(href)) continue;
    seen.add(href);
    // climb while the container still holds only this item link
    let card = a;
    while (card.parentElement &&
           card.parentElement.querySelectorAll('a[href*="/marketplace/item/"]').length === 1) {
      card = card.parentElement;
    }
    const text = (card.innerText || '').trim();
    const priceMatch = text.match(/(?:₱|PHP|P)\s?[\d.,]+/i);
    const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
    const title = lines.find(l => l.length > 6 && !/^(?:₱|PHP|P)\s?[\d.,]+$/i.test(l)) || lines[0] || '';
    let image = '';
    for (const im of card.querySelectorAll('img')) {
      const src = im.currentSrc || im.src || '';
      if (src.startsWith('http')) { image = src; break; }
    }
    out.push({
      url: 'https://www.facebook.com' + href,
      title: title.slice(0, 200),
      price_text: priceMatch ? priceMatch[0] : '',
      image: image,
      raw: text.slice(0, 400),
    });
  }
  return out;
}
"""

# Group post extraction. The post BODY reads cleanly from dir="auto" blocks
# (earlier "scramble" was a wrong-selector mistake). We pull body text +
# price + photos + poster + permalink.
GROUP_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const BOILER = /^(welcome to|feel free to post|group rules|members|admin|see more$)/i;
  for (const kid of document.querySelectorAll('div[role="feed"] > div')) {
    // permalink (hover pass hydrates these); normalise to base post url
    let link = '';
    for (const a of kid.querySelectorAll('a[href]')) {
      const m = (a.getAttribute('href') || '').match(/\/groups\/\d+\/(?:posts|permalink)\/(\d+)/);
      if (m) { link = `https://www.facebook.com/groups/${location.pathname.split('/')[2]}/posts/${m[1]}/`; break; }
    }
    if (!link || seen.has(link)) continue;

    // poster name
    let poster = '';
    for (const a of kid.querySelectorAll('a[href*="/user/"]')) {
      const t = (a.innerText || '').trim();
      if (t && t.length > 1 && !/^online status/i.test(t)) { poster = t; break; }
    }

    // body text: the meatiest dir=auto block that isn't group boilerplate
    let body = '';
    for (const el of kid.querySelectorAll('div[dir="auto"]')) {
      let t = (el.innerText || '').trim();
      if (t.length < 4 || BOILER.test(t)) continue;
      t = t.replace(/\s*See more\s*$/i, '').trim();
      if (t.length > body.length) body = t;
    }

    // photos: real listing images (scontent, sizeable, not avatars)
    const imgs = [];
    for (const im of kid.querySelectorAll('img')) {
      const src = im.currentSrc || im.src || '';
      if (src.includes('scontent') && (im.naturalHeight || im.height || 0) > 130
          && !/\/s\d{2,3}x\d{2,3}\//.test(src) && !imgs.includes(src)) {
        imgs.push(src);
      }
    }

    if (!body && !imgs.length) continue;  // empty/UI card
    seen.add(link);
    out.push({url: link, poster: poster || "Facebook seller",
              body: body.slice(0, 500),
              title: (body.split('\n')[0] || poster || 'Listing').slice(0, 180),
              images: imgs.slice(0, 4), image: imgs[0] || ''});
  }
  return out;
}
"""


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"], 1)}

def parse_end_time(text, now=None):
    """Best-effort auction end time -> unix epoch. Handles absolute dates
    ('End: July 17, 2026 6:30:59PM'), clock-only ('ends 9pm'), and relative
    ('24h'). Returns None when not confident."""
    import datetime
    if not text:
        return None
    now = now or time.time()
    t = text.lower()

    # absolute date: "end: july 17, 2026 6:30:59pm",
    # "end: july 15, 2026 (wednesday 9:00 pm)", "end july 17 9pm".
    # [^\d]{0,25}? skips filler like " (wednesday " between date and time.
    m = re.search(r"end[a-z: ]*?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                  r"[a-z]*\s+(\d{1,2})(?:,?\s*(\d{4}))?[^\d]{0,25}?"
                  r"(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap])\.?m", t)
    if m:
        mon = _MONTHS[m.group(1)]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else datetime.datetime.fromtimestamp(now).year
        hr = int(m.group(4)) % 12 + (12 if m.group(6) == "p" else 0)
        minute = int(m.group(5) or 0)
        try:
            return datetime.datetime(year, mon, day, hr, minute).timestamp()
        except ValueError:
            return None

    # relative: "24 hours", "ends in 3 hrs", "12h"
    m = re.search(r"(?:ends?\s*(?:in|after)?\s*)?(\d{1,3})\s*(?:hours?|hrs?|h)\b", t)
    if m and ("end" in t or "auction" in t or "hour" in t or "hr" in t):
        hrs = int(m.group(1))
        if 1 <= hrs <= 168:
            return now + hrs * 3600

    # clock only: "ends 9pm", "end time 9:30 pm"
    m = re.search(r"(?:ends?|end ?time|closes?|closing)\s*(?:at|by|:)?\s*"
                  r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m", t)
    if m:
        hr = int(m.group(1)) % 12 + (12 if m.group(3) == "p" else 0)
        minute = int(m.group(2) or 0)
        dt = datetime.datetime.fromtimestamp(now)
        end = dt.replace(hour=hr, minute=minute, second=0, microsecond=0)
        if end.timestamp() <= now:
            end += datetime.timedelta(days=1)
        return end.timestamp()
    return None


def parse_auction(text):
    """Pull an auction's starting bid, buyout and increment from the body."""
    t = text or ""
    def num(pat):
        m = re.search(pat, t, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                return None
        return None
    sb = num(r"(?:starting bid|start(?:ing)? ?price|\bsb)\s*[:=]?\s*(?:₱|php|p)?\s*([\d,]+)")
    bo = num(r"(?:buy ?out|buyout|\bbo\b|yours na)\s*[:=]?\s*(?:₱|php|p)?\s*([\d,]+)")
    inc = re.search(r"(?:increment|inc(?:rements?)?)\s*[:=of]*\s*"
                    r"([\d]+(?:\s*[,/]\s*\d+)*)", t, re.I)
    return {"start_bid": sb, "buyout": bo,
            "increment": inc.group(1).strip() if inc else None}


def parse_price(text):
    """PH listings price in peso: '₱75k', '26.5k', '₱1,200', or a bare '400'.
    Skip collector numbers (199/165) and tiny quantity-like numbers."""
    if not text:
        return None
    # k-notation: 26.5k, ₱75k
    m = re.search(r"(?:₱|php|p)?\s*([\d]{1,3}(?:[.,]\d{1,3})?)\s*k\b", text, re.I)
    if m:
        return float(m.group(1).replace(",", "")) * 1000
    # explicit currency marker
    m = re.search(r"(?:₱|php)\s*([\d][\d,]*(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1).replace(",", ""))
    # bare peso number (FB posts often omit ₱): not part of a x/y set number,
    # reasonable price range, and NOT a quantity/age ("60 days", "550 pcs").
    for m in re.finditer(r"(?<![\d/])(\d{2,3}(?:,\d{3})+|\d{2,6})(?![\d/])", text):
        tail = text[m.end():m.end() + 14].lower()
        if tail[:1] == "%":                      # "70%-90%" is not a price
            continue
        if re.match(r"\s*(day|days|month|mos|year|yr|yrs|pc|pcs|piece|cards?|"
                    r"sets?|hrs?|hours?|mins?|percent)\b", tail):
            continue
        val = float(m.group(1).replace(",", ""))
        if 30 <= val <= 500000:
            return val
    return None


def hydrate_permalinks(page, max_hovers=40):
    """FB withholds post permalinks until the post is hovered. Hovering the
    anchors in each feed child surfaces the real /posts/<id>/ links."""
    try:
        links = page.query_selector_all('div[role="feed"] > div a')
    except Exception:
        return
    hovers = 0
    for a in links:
        if hovers >= max_hovers:
            break
        try:
            a.hover()
            page.wait_for_timeout(random.randint(60, 140))
            hovers += 1
        except Exception:
            continue


def human_scroll(page, rounds=4):
    for _ in range(rounds):
        page.mouse.wheel(0, random.randint(1500, 3500))
        page.wait_for_timeout(random.randint(1200, 3200))


def collect(page, url, js, label, want=None):
    """FB virtual-scrolls (off-screen posts are removed from the DOM), so we
    extract incrementally while scrolling and accumulate by URL until we have
    `want` posts or run out of new ones."""
    if want is None:
        want = getattr(config, "FB_MAX_POSTS_PER_GROUP", 20)
    print(f"[fb] {label}: {url}")
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(random.randint(3500, 6000))
    if "login" in page.url:
        print("  [!] Redirected to login — session expired or checkpointed. Run fb_login.py again.")
        return []
    is_group = "/groups/" in url
    acc = {}
    stale = 0
    for step in range(16):
        if is_group:
            hydrate_permalinks(page, max_hovers=15)
        try:
            batch = page.evaluate(js)
        except Exception as e:
            print(f"  [extract error] {e}")
            batch = []
        before = len(acc)
        for it in batch:
            acc.setdefault(it["url"], it)
        stale = stale + 1 if len(acc) == before else 0
        if len(acc) >= want or stale >= 3:
            break
        page.mouse.wheel(0, random.randint(2200, 3600))
        page.wait_for_timeout(random.randint(1400, 2600))
    items = list(acc.values())[:want]
    print(f"  {len(items)} item(s) collected")
    return items


def analyze(item):
    """Enrich a raw FB post: price, category, auction/sale, distress,
    location, and an undervalued verdict. Returns the item or None if it's
    a deadend (no committed price) that should be skipped."""
    body = item.get("body", "") or item.get("title", "")
    if scraper.is_meta(body):        # WTB/looking-for/rules — never a listing
        return None
    item["auction"] = scraper.is_auction(body)
    if item["auction"]:
        item["auc"] = parse_auction(body)
        item["end_ts"] = parse_end_time(body)
        # auction "price" = starting bid (fall back to buyout, then scan)
        price = item["auc"]["start_bid"] or item["auc"]["buyout"] or parse_price(body)
    else:
        item["end_ts"] = None
        price = parse_price(body)
    # skip deadends: no committed price, or PM-to-offer
    if price is None or scraper.is_deadend(body):
        return None
    item["price"] = price
    item["category"] = scraper.classify(body)[0]
    item["distress"] = scraper.distress_terms(body)
    item["loc"], item["near"] = scraper.location_hint(body)
    # best-effort valuation: only fires for raw, identifiable cards
    market, label = (None, None)
    if not item["auction"]:
        try:
            market, label = prices.market_value(item.get("title", "") + " " + body)
        except Exception:
            market = None
    # value ONLY fixed-price sales. Auctions/claim sales open below market by
    # design (starting bid / dib price), so an "under market" flag there is a
    # false snipe every time — a real auction snipe is only known at the end.
    market = None
    if not item["auction"]:
        try:
            market, label = prices.market_value(item.get("title", "") + " " + body)
        except Exception:
            market = None
    item["market"] = market
    item["undervalued"] = bool(market and price <= market * config.FB_DEAL_FRACTION)
    return item


def notify(item, source, conn=None):
    is_auction = item.get("auction")
    # auctions go to their own channel when configured
    wh = (getattr(config, "FB_AUCTION_WEBHOOK", "") or config.DISCORD_WEBHOOK_URL) \
        if is_auction else config.DISCORD_WEBHOOK_URL
    imgs = item.get("images") or ([item["image"]] if item.get("image") else [])
    body = item.get("body", "")
    price = item.get("price")
    _, cat_color, icon = scraper.classify(body or item.get("title", ""))
    timed = bool(is_auction and item.get("end_ts"))
    if timed:
        kind, kind_icon = "TIMED AUCTION", "⏰"       # ⏰ ends at a set time
    elif is_auction:
        kind, kind_icon = "BIDDING/CLAIM", "\U0001F528"   # 🔨 dib/open bid, no end
    else:
        kind, kind_icon = "SALE", icon
    cat = item.get("category", "single")

    tags = [f"₱{price:,.0f}", kind, cat.upper()]
    if item.get("loc"):
        tags.append(("\U0001F4CD " if item.get("near") else "") + item["loc"])
    if item.get("market"):
        tags.append(f"mkt ~₱{item['market']:,.0f}")
    # live countdown timer for auctions with a parsed end time
    if is_auction and item.get("end_ts"):
        tags.append(f"ends <t:{int(item['end_ts'])}:R>")
    head = " · ".join(tags)

    # loud signals get a mention + colour
    flags = []
    color = 0xF39C12 if timed else (0x9B59B6 if is_auction else cat_color)  # orange / purple / category
    ping = ""
    if item.get("undervalued"):
        flags.append(f"\U0001F6A8 UNDER MARKET ({price/item['market']*100:.0f}% of ~₱{item['market']:,.0f})")
        color = 0xE91E63; ping = "@everyone"
    if item.get("distress"):
        flags.append("\U0001F525 " + ", ".join(item["distress"][:3]))
        color = 0xE91E63; ping = "@everyone"
    if item.get("near"):
        flags.append("\U0001F4CD near you")

    # single link (the embed title = "View post"), then post title, then body
    post_title = (item.get("title", "") or "Listing").strip()[:180]
    parts = [f"**{post_title}**", head]
    if flags:
        parts.append("**" + " · ".join(flags) + "**")
    if is_auction:
        # auctions: show the auction facts, NOT the rules-spam body
        a = item.get("auc", {})
        det = []
        if item.get("end_ts"):
            det.append(f"⏰ Ends <t:{int(item['end_ts'])}:F> (<t:{int(item['end_ts'])}:R>)")
        else:
            det.append("⏰ End time: see post")
        if a.get("start_bid"):
            det.append(f"🏁 Start ₱{a['start_bid']:,.0f}")
        if a.get("buyout"):
            det.append(f"💰 Buyout ₱{a['buyout']:,.0f}")
        if a.get("increment"):
            det.append(f"➕ Increment {a['increment']}")
        parts.append("\n".join(det))
    else:
        desc_body = "\n".join(body.split("\n")[1:4]).strip()[:300]  # skip title line
        if desc_body:
            parts.append(desc_body)
    if len(imgs) > 1:
        parts.append(f"+{len(imgs)-1} more photos")
    embeds = [{"title": f"{kind_icon} View post", "url": item["url"],
               "description": "\n".join(parts)[:1000], "color": color}]
    if imgs:
        embeds[0]["image"] = {"url": imgs[0]}
        for extra in imgs[1:4]:
            embeds.append({"url": item["url"], "image": {"url": extra}})

    if not wh or "PASTE" in wh:
        print(f"    P{price:,.0f} | {kind} {cat} | {'/'.join(flags)[:40]} | {item.get('title','')[:40]}")
        return
    payload = {"embeds": embeds}
    if ping:
        payload["content"] = ping + (f" {flags[0]}" if flags else "")
    try:
        # ?wait=true returns the created message so we can capture its id and
        # let the bot map your reaction back to this auction
        post_url = wh + ("&wait=true" if "?" in wh else "?wait=true")
        r = requests.post(post_url, json=payload, timeout=15)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 5)))
            r = requests.post(post_url, json=payload, timeout=15)
        elif r.status_code not in (200, 204):
            print(f"  [discord {r.status_code}] {r.text[:120]}")
        # register auctions with a parsed end time for react-to-track
        if is_auction and item.get("end_ts") and conn is not None:
            try:
                msg = r.json()
                msg_id = str(msg.get("id")) if isinstance(msg, dict) else None
                chan_id = str(msg.get("channel_id")) if isinstance(msg, dict) else None
            except Exception:
                msg_id = chan_id = None
            conn.execute(
                "INSERT OR REPLACE INTO fb_auctions "
                "(url,title,end_ts,under_market,warned,ts,msg_id,tracked,channel_id) "
                "VALUES (?,?,?,?,COALESCE((SELECT warned FROM fb_auctions WHERE url=?),0),"
                "?,?,COALESCE((SELECT tracked FROM fb_auctions WHERE url=?),0),?)",
                (item["url"], item.get("title", "")[:120], item["end_ts"],
                 int(bool(item.get("undervalued"))), item["url"], time.time(),
                 msg_id, item["url"], chan_id))
            conn.commit()
    except Exception as e:
        print(f"  [discord error] {e}")


def run_once(conn):
    targets = []
    mp = getattr(config, "FB_MARKETPLACE_URL", "")
    if mp:
        targets.append((mp, MARKETPLACE_JS, "FB-MP"))
    for g in getattr(config, "FB_GROUP_URLS", []):
        # CHRONOLOGICAL (newest posts) — reliable ~20-item yield and clean
        # post structure. RECENT_ACTIVITY bumped comments into the feed which
        # tanked yield (~1 item) and fragmented multi-card gallery posts.
        # Fresh auctions still appear here when posted (when bidding early
        # matters most); the react-to-track flow handles live bid updates.
        u = g.rstrip("/") + "/?sorting_setting=CHRONOLOGICAL"
        targets.append((u, GROUP_JS, "FB-GROUP"))
    if not targets:
        print("Nothing to scan — set FB_MARKETPLACE_URL / FB_GROUP_URLS in config.py")
        return

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            config.FB_PROFILE_DIR,
            headless=getattr(config, "FB_HEADLESS", False),
            viewport={"width": 1280, "height": 850},
            locale="en-US",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for url, js, label in targets:
            try:
                items = collect(page, url, js, label)
            except Exception as e:
                print(f"  [fb error] {e}")
                continue
            new = [i for i in items if not seen(conn, i["url"])]
            kept, dropped = [], 0
            now = time.time()
            for i in new:
                text = i.get("body", "") or i.get("title", "")
                # drop merch / Pokémon GO / video-game, then deadends/no-price
                if scraper.is_merch(text) or analyze(i) is None:
                    mark(conn, i["url"]); dropped += 1
                    continue
                # auction channel: only still-available auctions (not ended)
                if i.get("auction") and i.get("end_ts") and i["end_ts"] < now:
                    mark(conn, i["url"]); dropped += 1
                    continue
                kept.append(i)
            print(f"  {len(kept)} new" + (f" ({dropped} filtered: merch/no-price/PM-offer)" if dropped else ""))
            for i in kept:
                if not claim(conn, i["url"]):   # skip if another pass grabbed it
                    continue
                notify(i, label, conn)
                time.sleep(1.3)
            time.sleep(random.randint(8, 20))  # human-ish pause between pages
        ctx.close()
    check_auction_warnings(conn)


def check_auction_warnings(conn):
    """Ping the auction channel ~10 min before a tracked auction ends."""
    warn_wh = getattr(config, "FB_AUCTION_WEBHOOK", "") or config.DISCORD_WEBHOOK_URL
    if not warn_wh or "PASTE" in warn_wh:
        return
    now = time.time()
    window = getattr(config, "FB_AUCTION_WARN_MINUTES", 10) * 60
    # only auctions you reacted to on Discord (tracked=1) get the reminder
    rows = conn.execute("SELECT url,title,end_ts,under_market FROM fb_auctions "
                        "WHERE warned=0 AND tracked=1 AND end_ts BETWEEN ? AND ?",
                        (now, now + window)).fetchall()
    for url, title, end_ts, under in rows:
        tag = " \U0001F6A8 UNDER MARKET" if under else ""
        embed = {"title": f"⏰ ENDING SOON: {title[:150]}",
                 "url": url, "color": 0xE91E63,
                 "description": f"Auction ends <t:{int(end_ts)}:R> — <t:{int(end_ts)}:t>\n"
                                f"[open post]({url})"}
        try:
            requests.post(warn_wh, json={"content": f"@everyone auction ending soon{tag}",
                                         "embeds": [embed]}, timeout=15)
            conn.execute("UPDATE fb_auctions SET warned=1 WHERE url=?", (url,))
            conn.commit()
            print(f"  AUCTION WARN: {title[:45]}".encode("ascii", "replace").decode())
        except Exception as e:
            print(f"  [auction warn error] {e}")
    # purge auctions that ended over an hour ago
    conn.execute("DELETE FROM fb_auctions WHERE end_ts < ?", (now - 3600,))
    conn.commit()


def main():
    conn = db()
    if "--once" in sys.argv:
        run_once(conn)
        print("Done (single pass).")
        return
    base = getattr(config, "FB_POLL_MINUTES", 45)
    print(f"Starting FB feed loop — groups ~every {base} min, auction check every 2 min. Ctrl+C to stop.")
    next_scan = 0
    while True:
        now = time.time()
        if now >= next_scan:
            run_once(conn)                       # full group scan (also checks warnings)
            next_scan = now + base * random.uniform(0.85, 1.35) * 60
            print(f"[next group scan in {(next_scan-time.time())/60:.0f} min]")
        else:
            check_auction_warnings(conn)         # frequent, cheap, no scraping
        time.sleep(120)


if __name__ == "__main__":
    main()
