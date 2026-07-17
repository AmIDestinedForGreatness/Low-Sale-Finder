"""
pc_price.py — PriceCharting fallback for cards TCGplayer doesn't carry
(vintage, Japanese/Meiji/McDonald's promos, etc.). Scrapes the public search
results table and returns the UNGRADED (raw) price, matched to the card by
name/set token overlap.

Chained after TCGplayer in prices.market_value.
"""
import re
import sqlite3
import time
import requests

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SEARCH = "https://www.pricecharting.com/search-products"
_GRADE = re.compile(r"\b(psa|bgs|cgc)\s*\d", re.I)
_STOP = re.compile(r"\b(pokemon|pokemom|card|tcg|holo|full ?art|fullart|secret|"
                   r"rare|rainbow|vintage|promo|mint|nm|condition)\b", re.I)
# one search-result row -> (product name, set/console, ungraded price).
# NB: PriceCharting uses absolute URLs and puts the name in <td class="title">.
_ROW = re.compile(
    r'<td class="title">\s*<a [^>]*>\s*([^<]+?)\s*</a>.*?'
    r'/console/[^"]*"[^>]*>\s*([^<]+?)\s*</a>.*?'
    r'used_price"[^>]*>\s*<span[^>]*>\$([\d,]+\.\d{2})',
    re.S)
_MAX_HTML_CHARS = 2_000_000
_MAX_ROW_CHARS = 100_000


def _parse_rows(html):
    """Parse PriceCharting rows without running `_ROW` across a whole page.

    The old whole-document `findall()` could catastrophically backtrack on a
    large search page that contained many partial title cells but no matching
    price cell. Bound both the document and each table-row search.
    """
    html = (html or "")[:_MAX_HTML_CHARS]
    lowered = html.lower()
    rows = []
    cursor = 0
    while len(rows) < 500:
        start = lowered.find("<tr", cursor)
        if start < 0:
            break
        end = lowered.find("</tr>", start)
        if end < 0:
            break
        segment = html[start:min(end + 5, start + _MAX_ROW_CHARS)]
        match = _ROW.search(segment)
        if match:
            rows.append(match.groups())
        cursor = end + 5
    return rows


def _tokens(s):
    return set(w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 1)


# words that describe EVERY listing, not THIS card — matching on these
# priced a toy Lucario as a P22k booster box ("pokemon"+"box", 2 tokens)
_GENERIC = {
    "pokemon", "pokemom", "pokemons", "card", "cards", "tcg", "japanese",
    "japan", "korean", "english", "eng", "jp", "box", "pack", "packs", "set",
    "sets", "sale", "price", "holo", "rare", "promo", "promos", "vintage",
    "mint", "psa", "bgs", "cgc", "edition", "1st", "first", "booster",
    "bundle", "lot", "collection", "collections", "with", "and", "the",
    "for", "fs", "wts", "lf", "na", "ng", "sa", "ko", "po", "nalang",
    "lang", "only", "new", "authentic", "original", "legit", "rush",
    "starts", "start", "paubos", "secret", "full", "art", "fullart"}


def _specific(tokens):
    """Tokens that actually identify a card (Pokémon name, etc.)."""
    return {t for t in tokens if t not in _GENERIC and len(t) >= 3
            and not t.isdigit()}


def _pick(rows, title):
    """Choose the PriceCharting row for this title, or None.
    The match must share a SPECIFIC token with the product NAME itself —
    generic overlap ('pokemon box') is how plushies got booster-box prices,
    and name-vs-console overlap is how Combee got Combusken's price."""
    want = _specific(_tokens(title))
    if not want:
        return None                      # nothing identifying to match on
    best, best_score = None, 0
    for name, console, usd in rows:
        name_hit = _specific(_tokens(name)) & want
        if not name_hit:
            continue
        score = (len(name_hit) * 10
                 + len(_tokens(name + " " + console) & _tokens(title)))
        if score > best_score:
            best, best_score = (name, console, usd), score
    return best


def _cache():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS pc_cache "
                 "(key TEXT PRIMARY KEY, price REAL, label TEXT, ts REAL)")
    return conn


def market_value(title: str):
    """(price_local, label) or (None, None). Raw/ungraded price only."""
    if _GRADE.search(title or ""):
        return None, None
    clean = _STOP.sub(" ", re.sub(r"\d+\s*/\s*\S+", " ", title or ""))
    query = " ".join(re.sub(r"[^A-Za-z0-9' -]", " ", clean).split())[:60]
    if len(query) < 3:
        return None, None

    key = query.lower()
    conn = _cache()
    try:
        row = conn.execute("SELECT price,label,ts FROM pc_cache WHERE key=?",
                           (key,)).fetchone()
        if row and time.time() - row[2] < (3 * 86400 if row[0] else 86400):
            return (row[0], row[1]) if row[0] else (None, None)

        price, label = None, None
        try:
            r = requests.get(SEARCH, params={"q": query, "type": "prices"},
                             headers={"User-Agent": UA}, timeout=20)
            best = _pick(_parse_rows(r.text), title)
            if best:
                usd = float(best[2].replace(",", ""))
                price = usd * config.USD_TO_LOCAL_RATE
                label = f"pc:{best[0]} [{best[1]}] (${usd})"
        except Exception as e:
            print(f"  [pricecharting error] {e}")

        conn.execute("INSERT OR REPLACE INTO pc_cache VALUES (?,?,?,?)",
                     (key, price, label, time.time()))
        conn.commit()
        return (price, label)
    finally:
        conn.close()
