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
import scraper  # classify() + posted_epoch() are shared with the Carousell feed


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
    """PH listings use k-notation ('26.5k', '₱75k') and plain numbers."""
    if not text:
        return None
    m = re.search(r"(?:₱|php|p)?\s*([\d]{1,3}(?:[.,]\d{1,3})?)\s*k\b", text, re.I)
    if m:
        return float(m.group(1).replace(",", "")) * 1000
    m = re.search(r"(?:₱|php)\s*([\d][\d,]*(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1).replace(",", ""))
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


def collect(page, url, js, label):
    print(f"[fb] {label}: {url}")
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(random.randint(3500, 6000))
    if "login" in page.url:
        print("  [!] Redirected to login — session expired or checkpointed. Run fb_login.py again.")
        return []
    human_scroll(page, rounds=6)
    if "/groups/" in url:
        hydrate_permalinks(page)
    try:
        items = page.evaluate(js)
    except Exception as e:
        print(f"  [extract error] {e}")
        return []
    print(f"  {len(items)} item(s) on page")
    return items


def notify(item, source):
    wh = config.DISCORD_WEBHOOK_URL
    imgs = item.get("images") or ([item["image"]] if item.get("image") else [])
    body = item.get("body", "")
    cat, cat_color, icon = scraper.classify(body or item.get("title", ""))
    price = parse_price(body)
    price_s = f"₱{price:,.0f}" if price else "price in post/photos"
    head = f"{price_s} · {cat.upper()} · {item.get('poster', 'seller')}"
    # first ~3 lines of the body as context (purple = Facebook)
    snippet = "\n".join(body.split("\n")[:3])[:300]
    embeds = [{
        "title": f"[{source}] {icon} {item.get('title', 'Listing')[:180]}",
        "url": item["url"],
        "description": f"{head}\n{snippet}\n[open post]({item['url']})"
                       + (f" · +{len(imgs)-1} photos" if len(imgs) > 1 else ""),
        "color": cat_color,
    }]
    if imgs:
        embeds[0]["image"] = {"url": imgs[0]}
        for extra in imgs[1:4]:
            embeds.append({"url": item["url"], "image": {"url": extra}})
    if not wh or "PASTE" in wh:
        print(f"    {price_s} | {cat} | {item.get('title','')[:50]} | {len(imgs)} photo(s)")
        return
    try:
        r = requests.post(wh, json={"embeds": embeds}, timeout=15)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 5)))
            requests.post(wh, json={"embeds": embeds}, timeout=15)
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
            # TCG cards only — drop merch / Pokémon GO / video-game posts
            kept = []
            for i in new:
                if scraper.is_merch(i.get("body", "") or i.get("title", "")):
                    mark(conn, i["url"])  # remember so we don't re-check it
                else:
                    kept.append(i)
            print(f"  {len(kept)} new"
                  + (f" ({len(new)-len(kept)} non-TCG filtered)" if len(new) != len(kept) else ""))
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
