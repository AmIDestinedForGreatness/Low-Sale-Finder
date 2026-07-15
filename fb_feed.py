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
    });
  }
  return out;
}
"""

GROUP_JS = r"""
() => {
  const out = [];
  const seenKeys = new Set();
  for (const art of document.querySelectorAll('div[role="article"]')) {
    // permalink of the post
    let link = '';
    for (const a of art.querySelectorAll('a[href]')) {
      const h = a.getAttribute('href') || '';
      if (/\/groups\/[^/]+\/(posts|permalink)\//.test(h)) { link = h.split('?')[0]; break; }
    }
    if (!link || seenKeys.has(link)) continue;
    seenKeys.add(link);
    const text = (art.innerText || '').trim();
    if (!text) continue;
    const priceMatch = text.match(/(?:₱|PHP|P)\s?[\d.,]+/i);
    let image = '';
    for (const im of art.querySelectorAll('img')) {
      const src = im.currentSrc || im.src || '';
      // skip tiny avatars; post photos are served from scontent
      if (src.startsWith('http') && src.includes('scontent') && (im.width || 100) > 80) {
        image = src; break;
      }
    }
    out.push({
      url: link.startsWith('http') ? link : ('https://www.facebook.com' + link),
      title: text.split('\n').map(s => s.trim()).filter(Boolean).slice(0, 4).join(' · ').slice(0, 200),
      price_text: priceMatch ? priceMatch[0] : '',
      image: image,
    });
  }
  return out;
}
"""


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
    human_scroll(page)
    try:
        items = page.evaluate(js)
    except Exception as e:
        print(f"  [extract error] {e}")
        return []
    print(f"  {len(items)} item(s) on page")
    return items


def notify(item, source):
    wh = config.DISCORD_WEBHOOK_URL
    cat, cat_color, icon = scraper.classify(item.get("title", ""))
    embed = {
        # title is the clickable link — no raw URL in the body
        "title": f"[{source}] {icon} {item['title'][:190]}",
        "url": item["url"],
        "description": f"{item['price_text'] or 'no price shown'} · {cat.upper()}",
        "color": cat_color,
    }
    if item.get("image"):
        embed["image"] = {"url": item["image"]}
    if not wh or "PASTE" in wh:
        print(f"    {item['title'][:60]} | {item['price_text']} | {item['url']}")
        return
    try:
        r = requests.post(wh, json={"embeds": [embed]}, timeout=15)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 5)))
            requests.post(wh, json={"embeds": [embed]}, timeout=15)
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
            print(f"  {len(new)} new")
            for i in new:
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
