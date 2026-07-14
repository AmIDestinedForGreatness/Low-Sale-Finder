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
        // climb to a reasonable card container
        let card = a;
        for (let i = 0; i < 4 && card.parentElement; i++) card = card.parentElement;
        const text = (card.innerText || '').trim();
        if (!text) continue;
        // find a price token ($ or P or RM or numbers near currency)
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
        out.push({
          url: url.split('?')[0],
          title: title.slice(0, 200),
          price_text: priceMatch ? priceMatch[0] : '',
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
        })
    return results
