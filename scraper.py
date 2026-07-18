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
import network_safety

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
    ("sealed",     0x2ECC71, "📦", re.compile(r"\b(sealed|boosters?|etb|elite trainer|tins?|packs?|upc|display|booster bundle|premium collection|booster box)\b", re.I)),
    ("bulk",       0xE67E22, "🗃️", re.compile(r"\b(bulk|lots?|take ?all|assorted|wholesale|mixed|randoms?|bundles?)\b", re.I)),
    ("collection", 0x1ABC9C, "📚", re.compile(r"\b(binders?|collections?|albums?|dibs?)\b", re.I)),
]

# TCG-cards-only filter. Two ways a listing gets dropped:
#  (1) it's physical merch (plush, hats, figures...), or
#  (2) it's a Pokémon *video game / GO* item (accounts, digital goods),
# UNLESS it carries a clear trading-card signal.
_MERCH_RE = re.compile(
    r"\b(plush(?:ie)?s?|stuffed|hats?|caps?|beanies?|shirts?|t-?shirts?|hoodies?|"
    r"jackets?|figures?|figurines?|funko|nendoroid|mugs?|"
    r"tumblers?|stickers?|decals?|toys?|lego|squishmallows?|backpacks?|bags?|"
    r"wallets?|lanyards?|costumes?|cosplay|onesies?|pajamas?|slippers?|crocs|"
    r"phone ?cases?|posters?|tarps?|clocks?|lamps?|pillows?|blankets?|towels?|"
    r"umbrellas?|plates?|bowls?|bottles?|jewelry|necklaces?|earrings?|charms?|"
    r"keychains?|key ?chains?|paintings?|artworks?|commissions?|handmade|"
    r"hand ?painted|hand ?drawn|acrylic|canvas|fan ?art|sketch(?:es)?|"
    r"crochet|clay|resin|button ?pins?|standees?)\b", re.I)
# Pokémon GO / video-game / digital-account terms — never TCG cards.
_GAME_RE = re.compile(
    r"pok[eé]mon ?go\b|\bpogo\b|\bpoke ?go\b|\bpc fukouka\b|\baccount\b|\bacct\b|"
    r"\blvl\b|\blevel \d|\bnintendo\b|\bswitch\b|\b3ds\b|\brom\b|\bemulator\b|"
    r"\bcfw\b|\bpksm\b|genned|\bshiny 6iv\b|\bgame ?card\b|\bcartridge\b|\bgba\b|"
    r"\bvideo ?game\b|\bplaystation\b|\bdigital\b|\btrainer club\b", re.I)
_CARDY_RE = re.compile(
    r"\bcards?\b|\btcg\b|\bpsa\b|\bbgs\b|\bcgc\b|\bslab\b|booster|\betb\b|"
    r"elite trainer|\bvmax\b|\bvstar\b|\bgx\b|\bholo\b|\bfoil\b|binder|"
    r"\bpromo\b|\bsealed\b|\bpack\b|\d{1,3}\s*/\s*\d{1,3}", re.I)

def is_merch(text: str) -> bool:
    """True when the listing is NOT a Pokémon trading card (merch or a
    video-game/GO item) — used to keep the feed TCG-only."""
    t = text or ""
    if _CARDY_RE.search(t):
        return False  # clear trading-card signal wins
    return bool(_MERCH_RE.search(t) or _GAME_RE.search(t))


def classify(title: str):
    """Returns (category_name, embed_color, icon) for a listing title."""
    for name, color, icon, pat in CATEGORY_RULES:
        if pat.search(title or ""):
            return name, color, icon
    return "single", 0x3B6CFF, "🃏"


# ── FB post analysis: auction vs sale, deadends, distress, location ────
# PH TCG auction lingo: SB=starting bid, MI=min increment, EB=early bird,
# BIN=buy it now, OB=overbid, "ends"/"bid"/"auction".
# Auctions AND claim/dib sales — in PH TCG these use the same channel:
# people comment "dib"/"key"/"steal"/"BO" to claim/buy-out. "steal" and
# "buy out" here are claim MECHANICS (end-the-claim price), not deal quality.
_AUCTION_RE = re.compile(
    r"\bauction\b|\bbidding\b|\bbid(?:s|ding)?\b|\bsb\s*[:=]?\s*\d|\bstarting bid\b|"
    r"\bmi\s*[:=]?\s*\d|\bmin(?:imum)? increment\b|\beb\s*[:=]?\s*\d|\bearly bird\b|"
    r"\bbin\s*[:=]?\s*\d|\bbuy ?it ?now\b|\boverbid\b|\bends?\s*(?:in|at|on)\b|"
    r"\bend ?time\b|\bhighest bid|\bdibs?\b|\bkey\b|\bsteal\b|\bbuy ?out\b|\bb\.?o\.?\b|"
    r"\bclaim\b|leave a dot|drop a dot", re.I)
# Deadends: no committed price — the seller wants you to negotiate in DMs.
_DEADEND_RE = re.compile(
    r"\bpm\b(?:[^.\n]{0,15})?(?:price|offer|na|me|to offer|for price)|"
    r"\bpm ?(?:for|to|na|me)\b|\bmake ?(?:an )?offer\b|\bbest offer\b|\bobo\b|"
    r"\bor best offer\b|price\?\s*$|\bhmu\b|\bdm\b(?:[^.\n]{0,10})?(?:price|offer)", re.I)
# Distress / urgency = likely underpriced. This is the primary deal signal.
# Genuine seller-SITUATION signals only (circumstances force a real low price).
# Deliberately EXCLUDED as clickbait marketing claims, NOT snipes:
#   'steal' (PH claim-sale buy-out mechanic), 'below market/srp/cost',
#   'mura na', 'dirt cheap', 'giveaway price', 'priced to sell', 'sulit' —
#   sellers slap these on 90-95%-of-market listings. A real snipe is the
#   PRICE being <=78%, judged by valuation, not the seller's adjectives.
_DISTRESS_RE = re.compile(
    r"\brush\b|\basap\b|\burgent\b|quitting|\bquit\b|leaving the hobby|"
    r"need(?:s)? (?:to go|gone|cash)|must go|letting go|let go|fire ?sale|"
    r"cutting loss|downsiz|moving out|closing shop", re.I)
# PH locations near Sikatuna Village (Quezon City) rank highest.
_NEAR = re.compile(r"\b(quezon city|\bqc\b|cubao|katipunan|sikatuna|diliman|"
                   r"kamuning|new manila|project \d|fairview|commonwealth)\b", re.I)
# Only trust an explicit "loc: <place>" tag, and reject obvious non-places.
_LOC_RE = re.compile(r"\b(?:loc|location|meet ?up|mu)\s*[:\-]\s*"
                     r"([A-Za-z][A-Za-z .]{2,24})", re.I)
_NOT_PLACE = re.compile(r"collectr|japanese|english|only|pm|price|market|comps?", re.I)

def is_auction(text: str) -> bool:
    return bool(_AUCTION_RE.search(text or ""))

# Claim-sale announcements: the post itself says the real listings will drop
# in the comment thread ("leave a dot", "claim below", "mine na"...). These are
# the ONLY posts worth reading comments on.
_CLAIM_RE = re.compile(
    r"leave a dot|drop a dot|\bdot\b(?:[^.\n]{0,15})?(?:for|below|updates|claim|notif)|"
    r"claim sale|claim(?:ing)? below|claim(?:ing)? in the comment|for claiming|"
    r"mine na\b|\bmine\b\s*\+|comment mine|claim(?:ing)? (?:will|drops?|starts?)|"
    r"cards?(?:[^.\n]{0,20})?(?:below|in the comment)|listings?(?:[^.\n]{0,15})?"
    r"(?:below|in the comment)|sabay claim|massive claim|posting below", re.I)

def is_claim_sale(text: str) -> bool:
    """Post announces a claim sale where listings drop in the comments."""
    return bool(_CLAIM_RE.search(text or ""))

def is_deadend(text: str) -> bool:
    """No committed price to work with — PM-to-offer / make-offer posts."""
    return bool(_DEADEND_RE.search(text or ""))

# Not-a-sale posts: want-to-buy threads, "looking for", group rules /
# admin announcements, megathreads. These are never listings.
_META_RE = re.compile(
    r"\blooking for\b|\blf\b\s|\bwtb\b|\biso\b|\bin search of\b|want to buy|"
    r"looking for (?:thread|buyer|seller)|\bmegathread\b|please read|"
    r"group rules|\brules\b thread|violat(?:or|ion)|banned permanently|"
    r"admin (?:post|announcement)|for approval|\bwts thread\b|feedback thread|"
    r"\brant\b|\bhelp\b\s|is this legit|legit check", re.I)

def is_meta(text: str) -> bool:
    """True for WTB/looking-for/rules/announcement posts (not a sale)."""
    return bool(_META_RE.search(text or ""))

def distress_terms(text: str):
    return sorted(set(m.group(0).lower() for m in _DISTRESS_RE.finditer(text or "")))

def location_hint(text: str):
    """Returns (location_string_or_'', is_near_bool). Prefers a QC/near match;
    otherwise an explicit 'loc: <place>' tag that isn't an obvious non-place."""
    near_m = _NEAR.search(text or "")
    if near_m:
        return near_m.group(0), True
    m = _LOC_RE.search(text or "")
    if m and not _NOT_PLACE.search(m.group(1)):
        return m.group(1).strip(), False
    return "", False


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
        return network_safety.validate_marketplace_url(query)
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
          // lazy-loaded cards sometimes only carry srcset/data-src
          const srcset = (im.getAttribute('srcset') || im.getAttribute('data-srcset') || '').split(/[\s,]+/)[0] || '';
          const src = im.currentSrc || im.src || im.getAttribute('data-src') || srcset;
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
    network_safety.validate_marketplace_url(url)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900},
                                  locale="en-US", service_workers="block")
        page = ctx.new_page()
        page.route("**/*", lambda route: network_safety.guard_marketplace_navigation(
            route, page.main_frame))
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            network_safety.validate_marketplace_url(page.url)
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
            # card text beyond the title (condition line, snippet) — used by
            # classify(); full descriptions would need opening each listing
            "raw": item.get("raw", ""),
        })
    return results
