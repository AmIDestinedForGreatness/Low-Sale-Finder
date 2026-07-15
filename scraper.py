"""
scraper.py — fetches Carousell listings for a search query using Playwright.

Carousell has no public API and its HTML changes periodically. This uses a few
fallback strategies to pull listing cards. If Carousell changes their markup and
results stop coming back, run with HEADLESS=False to see the page and update the
selectors in extract_listings().
"""
import re
import time
import urllib.parse
from playwright.sync_api import sync_playwright

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


def _price_to_float(text: str):
    if not text:
        return None
    # grab the first number group, handle commas/decimals
    m = re.search(r'([\d][\d,]*(?:\.\d+)?)', text.replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


# listing categories for the Discord feed: (name, embed color, icon, title pattern)
# order matters — first match wins (graded beats sealed beats bulk...)
CATEGORY_RULES = [
    ("graded",     0xF1C40F, "💎", re.compile(r"\b(psa|bgs|cgc|ace\s*\d|slab|graded)\b", re.I)),
    ("sealed",     0x2ECC71, "📦", re.compile(r"\b(sealed|boosters?|etb|elite trainer|tins?|packs?|upc|display|bundles?|premium collection|booster box)\b", re.I)),
    ("bulk",       0xE67E22, "🗃️", re.compile(r"\b(bulk|lots?|take ?all|assorted|wholesale|mixed|randoms?)\b", re.I)),
    ("collection", 0x1ABC9C, "📚", re.compile(r"\b(binders?|collections?|albums?|dibs?)\b", re.I)),
]

def classify(title: str):
    """Returns (category_name, embed_color, icon) for a listing title."""
    for name, color, icon, pat in CATEGORY_RULES:
        if pat.search(title or ""):
            return name, color, icon
    return "single", 0x3B6CFF, "🃏"


def posted_epoch(posted: str):
    """Convert Carousell's '5 hours ago' / 'just now' / 'yesterday' into a unix
    epoch, so Discord can render its native auto-updating timestamp (<t:..:R>)."""
    if not posted:
        return None
    p = posted.lower().strip()
    now = int(time.time())
    if "just now" in p:
        return now
    if "yesterday" in p:
        return now - 86400
    m = re.match(r"(\d+)\s*(second|minute|hour|day|week|month|year)", p)
    if not m:
        return None
    mult = {"second": 1, "minute": 60, "hour": 3600, "day": 86400,
            "week": 604800, "month": 2592000, "year": 31536000}[m.group(2)]
    return now - int(m.group(1)) * mult


def build_url(query: str) -> str:
    query = query.strip()
    if query.lower().startswith("http://") or query.lower().startswith("https://"):
        return query
    q = urllib.parse.quote(query)
    base = f"https://www.carousell.{config.CAROUSELL_COUNTRY}/search/{q}"
    # sort by newest so we catch fresh listings first
    return f"{base}?sort_by=3"


def extract_listings(page):
    """Pull listing dicts from the current page via injected JS.
    Strategy: find anchors that link to /p/ (product pages), then read the
    nearest price-looking text and title text within the card."""
    js = r"""
    () => {
      const out = [];
      const seen = new Set();
      const anchors = Array.from(document.querySelectorAll('a[href*="/p/"]'));
      for (const a of anchors) {
        const href = a.getAttribute('href') || '';
        if (!href.includes('/p/')) continue;
        // climb to the listing card: highest ancestor that still contains ONLY
        // this product link. A fixed climb merged neighboring cards, so every
        // listing inherited the grid's first price.
        let card = a;
        while (card.parentElement &&
               card.parentElement.querySelectorAll('a[href*="/p/"]').length === 1) {
          card = card.parentElement;
        }
        const text = (card.innerText || '').trim();
        if (!text) continue;
        // find a price token ($ or ₱ or RM or numbers near currency)
        const priceMatch = text.match(/(?:[$₱]|RM|S\$|PHP)\s?[\d.,]+/i);
        const url = href.startsWith('http') ? href : ('https://www.carousell.' + location.hostname.split('.').pop() + href);
        const key = href.split('?')[0];
        if (seen.has(key)) continue;
        seen.add(key);
        // title: prefer the anchor's own text, fallback to first line of card
        let title = (a.innerText || '').trim().split('\n')[0];
        if (!title || title.length < 3) {
          const lines = text.split('\n').map(s=>s.trim()).filter(Boolean);
          title = lines.find(l => l.length > 8) || lines[0] || '';
        }
        // listing photo (for Discord embeds): prefer the product photo —
        // cards also contain the seller's avatar (/photos/profiles/)
        let image = '';
        let fallback = '';
        for (const im of card.querySelectorAll('img')) {
          const src = im.currentSrc || im.src || im.getAttribute('data-src') || '';
          if (!src.startsWith('http')) continue;
          if (src.includes('/photos/products/')) { image = src; break; }
          if (!fallback && !src.includes('/photos/profiles/')) fallback = src;
        }
        if (!image) image = fallback;
        // freshness: Carousell shows "5 hours ago" / "Just now" on each card,
        // plus a bump marker when the seller re-upped the listing
        const timeMatch = text.match(/\b(just now|yesterday|\d+\s*(?:second|minute|hour|day|week|month|year)s?\s+ago)\b/i);
        const bumped = /\bbump/i.test(text);
        // listing state badge (Reserved / Sold) when Carousell still shows it
        const statusMatch = text.match(/\b(reserved|sold)\b/i);
        out.push({
          url: url.split('?')[0],
          title: title.slice(0, 200),
          price_text: priceMatch ? priceMatch[0] : '',
          image: image,
          posted: timeMatch ? timeMatch[0] : '',
          bumped: bumped,
          status: statusMatch ? statusMatch[0].toLowerCase() : '',
          raw: text.slice(0, 300)
        });
      }
      return out;
    }
    """
    try:
        return page.evaluate(js)
    except Exception as e:
        print(f"  [extract error] {e}")
        return []


def search(query: str):
    """Returns a list of listing dicts: {url, title, price, price_text}."""
    url = build_url(query)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900},
                                  locale="en-US")
        page = ctx.new_page()
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            # let listings render / lazy-load
            page.wait_for_timeout(4000)
            for _ in range(3):  # scroll to load more
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1500)
            raw = extract_listings(page)
        except Exception as e:
            print(f"  [navigation error] {e}")
            raw = []
        finally:
            browser.close()

    for item in raw:
        # only trust prices that came with a currency marker; falling back to
        # "first number in the card text" was picking up card numbers (163/132)
        # and set counts as prices
        price = _price_to_float(item.get("price_text"))
        if price is None:
            continue
        results.append({
            "url": item["url"],
            "title": item["title"],
            "price": price,
            "price_text": item.get("price_text", ""),
            "image": item.get("image", ""),
            "posted": item.get("posted", ""),
            "bumped": item.get("bumped", False),
            "status": item.get("status", ""),
        })
    return results
