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
    return conn

def seen(conn, url):
    return conn.execute("SELECT 1 FROM fb_seen WHERE url=?", (url,)).fetchone() is not None

def mark(conn, url):
    conn.execute("INSERT OR IGNORE INTO fb_seen (url, ts) VALUES (?, ?)", (url, time.time()))
    conn.commit()


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
    # reasonable price range. Take the first plausible one.
    for m in re.finditer(r"(?<![\d/])(\d{2,3}(?:,\d{3})+|\d{2,6})(?![\d/])", text):
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
    price = parse_price(body)
    # deadends: no price, or 'PM to offer' — skip entirely
    if price is None or scraper.is_deadend(body):
        return None
    item["price"] = price
    item["auction"] = scraper.is_auction(body)
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
    item["market"] = market
    item["undervalued"] = bool(market and price <= market * config.FB_DEAL_FRACTION)
    return item


def notify(item, source):
    wh = config.DISCORD_WEBHOOK_URL
    imgs = item.get("images") or ([item["image"]] if item.get("image") else [])
    body = item.get("body", "")
    price = item.get("price")
    _, cat_color, icon = scraper.classify(body or item.get("title", ""))
    kind = "AUCTION" if item.get("auction") else "SALE"
    kind_icon = "\U0001F528" if item.get("auction") else icon  # 🔨 for auctions
    cat = item.get("category", "single")

    tags = [f"₱{price:,.0f}", kind, cat.upper()]
    if item.get("loc"):
        tags.append(("\U0001F4CD " if item.get("near") else "") + item["loc"])
    if item.get("market"):
        tags.append(f"mkt ~₱{item['market']:,.0f}")
    head = " · ".join(tags)

    # loud signals get a mention + colour
    flags = []
    color = 0xF39C12 if item.get("auction") else cat_color
    ping = ""
    if item.get("undervalued"):
        flags.append(f"\U0001F6A8 UNDER MARKET ({price/item['market']*100:.0f}% of ~₱{item['market']:,.0f})")
        color = 0xE91E63; ping = "@everyone"
    if item.get("distress"):
        flags.append("\U0001F525 " + ", ".join(item["distress"][:3]))
        color = 0xE91E63; ping = "@everyone"
    if item.get("near"):
        flags.append("\U0001F4CD near you")

    snippet = "\n".join(body.split("\n")[:3])[:300]
    desc = head + "\n" + ("**" + " · ".join(flags) + "**\n" if flags else "") \
        + snippet + f"\n[open post]({item['url']})" \
        + (f" · +{len(imgs)-1} photos" if len(imgs) > 1 else "")
    embeds = [{"title": f"[{kind_icon}] {item.get('title', 'Listing')[:180]}",
               "url": item["url"], "description": desc, "color": color}]
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
        r = requests.post(wh, json=payload, timeout=15)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 5)))
            requests.post(wh, json=payload, timeout=15)
        elif r.status_code not in (200, 204):
            print(f"  [discord {r.status_code}] {r.text[:120]}")
    except Exception as e:
        print(f"  [discord error] {e}")


def run_once(conn):
    targets = []
    mp = getattr(config, "FB_MARKETPLACE_URL", "")
    if mp:
        targets.append((mp, MARKETPLACE_JS, "FB-MP"))
    for g in getattr(config, "FB_GROUP_URLS", []):
        # /?sorting_setting=CHRONOLOGICAL shows newest posts first
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
            for i in new:
                text = i.get("body", "") or i.get("title", "")
                # drop merch / Pokémon GO / video-game, then deadends/no-price
                if scraper.is_merch(text) or analyze(i) is None:
                    mark(conn, i["url"]); dropped += 1
                else:
                    kept.append(i)
            print(f"  {len(kept)} new" + (f" ({dropped} filtered: merch/no-price/PM-offer)" if dropped else ""))
            for i in kept:
                notify(i, label)
                mark(conn, i["url"])
                time.sleep(1.3)
            time.sleep(random.randint(8, 20))  # human-ish pause between pages
        ctx.close()


def main():
    conn = db()
    if "--once" in sys.argv:
        run_once(conn)
        print("Done (single pass).")
        return
    base = getattr(config, "FB_POLL_MINUTES", 45)
    print(f"Starting FB feed loop — ~every {base} min (jittered). Ctrl+C to stop.")
    while True:
        run_once(conn)
        wait = base * random.uniform(0.85, 1.35)
        print(f"[sleep] {wait:.0f} min")
        time.sleep(wait * 60)


if __name__ == "__main__":
    main()
