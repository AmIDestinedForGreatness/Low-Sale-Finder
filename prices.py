"""
prices.py — looks up market value for a card given its listing title.
Supports four backends, chosen in config.PRICE_SOURCE.

Returns market value already converted to LOCAL currency, or None if unknown.
"""
import csv
import os
import re
import sqlite3
import time
import requests
from functools import lru_cache
from rapidfuzz import fuzz

import config


# ── grade / edition detection from a messy listing title ──────────────
GRADE_RE = re.compile(r'\b(?:psa|bgs|cgc|ace)\s*([0-9]{1,2}(?:\.5)?)\b', re.I)

def detect_grade(title: str):
    """Returns a string like 'PSA 10', 'BGS 9.5', or None for raw/ungraded."""
    m = GRADE_RE.search(title)
    if not m:
        return None
    label = re.search(r'\b(psa|bgs|cgc|ace)\b', title, re.I).group(1).upper()
    return f"{label} {m.group(1)}"


# ══════════════════════════════════════════════════════════════════════
# BACKEND 1: manual CSV
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def _load_manual():
    path = os.path.join(os.path.dirname(__file__), "manual_prices.csv")
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["keyword"].strip().lower(), float(r["market_local"])))
            except (KeyError, ValueError):
                continue
    return rows

def _manual_lookup(title: str):
    """Match a listing title to a manual_prices.csv row.
    A row only matches when (a) its grade matches the title's grade exactly
    (raw keyword ↔ raw listing, PSA 10 keyword ↔ PSA 10 listing) and
    (b) every non-grade word of the keyword appears in the title. Fuzzy score
    is only used to rank multiple surviving rows — never to admit a loose one.
    token_set_ratio alone was matching 'PSA 10 Gardevoir ... Base Set' to the
    'charizard base set psa 10' row (shared tokens score high)."""
    rows = _load_manual()
    if not rows:
        return None, None
    t = title.lower()
    t_grade = (detect_grade(title) or "").upper()
    best = None  # (score, keyword, price)
    for kw, price in rows:
        k_grade = (detect_grade(kw) or "").upper()
        if k_grade != t_grade:
            continue  # graded and raw are different markets; so are PSA 9 vs 10
        kw_clean = GRADE_RE.sub(" ", kw)
        tokens = [w for w in re.split(r"[^a-z0-9]+", kw_clean) if len(w) > 1]
        if not tokens:
            continue
        if not all(re.search(rf"\b{re.escape(w)}\b", t) for w in tokens):
            continue
        score = fuzz.token_set_ratio(t, kw)
        if best is None or score > best[0]:
            best = (score, kw, price)
    if best:
        return best[2], f"manual:{best[1]} ({best[0]}%)"
    return None, None


# ══════════════════════════════════════════════════════════════════════
# BACKEND 2: PokemonPriceTracker
# ══════════════════════════════════════════════════════════════════════
def _ppt_lookup(title: str):
    key = config.POKEMONPRICETRACKER_API_KEY
    if not key or "PASTE" in key:
        return None, None
    try:
        # parse-title turns a messy title into a matched card + price
        r = requests.post(
            "https://www.pokemonpricetracker.com/api/v2/parse-title",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"title": title},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        grade = detect_grade(title)
        usd = None
        # graded price if available and a grade was detected
        if grade and grade.upper().startswith("PSA"):
            num = grade.split()[1].replace(".5", "")
            usd = (data.get("ebay", {}).get(f"psa{num}", {}) or {}).get("avg")
        if usd is None:
            usd = (data.get("prices", {}) or {}).get("market")
        if usd is None:
            return None, None
        name = data.get("name", "?")
        return float(usd) * config.USD_TO_LOCAL_RATE, f"PPT:{name} {grade or 'raw'}"
    except Exception as e:
        print(f"  [PPT error] {e}")
        return None, None


# ══════════════════════════════════════════════════════════════════════
# BACKEND 3: PriceCharting
# ══════════════════════════════════════════════════════════════════════
def _pc_lookup(title: str):
    tok = config.PRICECHARTING_TOKEN
    if not tok or "PASTE" in tok:
        return None, None
    try:
        r = requests.get(
            "https://www.pricecharting.com/api/product",
            params={"t": tok, "q": title},
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()
        if d.get("status") != "success":
            return None, None
        grade = detect_grade(title)
        # PriceCharting prices are in pennies. Pick a field based on grade.
        #  loose-price = ungraded;  graded fields vary by plan/category.
        field = "loose-price"
        if grade:
            g = grade.split()[1]
            field = {"10": "manual-only-price", "9": "graded-price"}.get(g, "graded-price")
        pennies = d.get(field) or d.get("loose-price")
        if not pennies:
            return None, None
        usd = pennies / 100.0
        return usd * config.USD_TO_LOCAL_RATE, f"PC:{d.get('product-name','?')} {grade or 'raw'}"
    except Exception as e:
        print(f"  [PriceCharting error] {e}")
        return None, None


# ══════════════════════════════════════════════════════════════════════
# BACKEND 4: pokemontcg.io — free card database with TCGplayer market prices
# ══════════════════════════════════════════════════════════════════════
# Identification strategy: a card is only priced when the title contains a
# collector number like "163/132" — name + number + printed-total pins the
# exact card, which keeps false matches (and false "deals") near zero.
# Titles without a number (binders, bulk, vague posts) return None.
# Graded (PSA/BGS) listings return None: TCGplayer market = RAW price.
# Limitation: the database covers international (EN) sets — JP-exclusive
# sets won't match; keep those in manual_prices.csv.

_PTCGIO_URL = "https://api.pokemontcg.io/v2/cards"
_NUM_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
_NOISE = {
    "pokemon", "pokémon", "card", "cards", "tcg", "trading", "japanese", "japan",
    "korean", "english", "authentic", "legit", "mint", "nm", "near", "condition",
    "holo", "holofoil", "reverse", "full", "art", "rare", "promo", "sale", "dib",
    "dibs", "steal", "cheap", "rush", "onhand", "hand", "original", "vintage",
    "edition", "1st", "first", "set", "base", "illustration", "special", "secret",
    "alt", "sealed", "slab", "graded", "gem",
}
_CACHE_OK_TTL = 3 * 86400   # found prices: refresh every 3 days
_CACHE_MISS_TTL = 86400     # misses: retry daily (protects the rate limit)


def _ptcgio_cache():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS price_cache "
                 "(key TEXT PRIMARY KEY, price REAL, label TEXT, ts REAL)")
    return conn


def _ptcgio_lookup(title: str):
    if detect_grade(title):
        return None, None
    m = _NUM_RE.search(title)
    if not m:
        return None, None
    number = str(int(m.group(1)))
    printed_total = str(int(m.group(2)))

    key = f"{number}/{printed_total}|" + " ".join(sorted(
        w for w in re.findall(r"[a-z']{4,}", title.lower()) if w not in _NOISE))
    conn = _ptcgio_cache()
    try:
        row = conn.execute("SELECT price, label, ts FROM price_cache WHERE key=?",
                           (key,)).fetchone()
        if row:
            price, label, ts = row
            ttl = _CACHE_OK_TTL if price else _CACHE_MISS_TTL
            if time.time() - ts < ttl:
                return (price, label) if price else (None, None)

        headers = {}
        api_key = getattr(config, "POKEMONTCGIO_API_KEY", "")
        if api_key and "PASTE" not in api_key:
            headers["X-Api-Key"] = api_key

        candidates = [w for w in re.findall(r"[a-z']{4,}", title.lower())
                      if w not in _NOISE][:4]
        result = (None, None)
        for word in candidates:
            # printed-total first (pins the exact set), then number-only
            for q in (f'name:"{word}" number:{number} set.printedTotal:{printed_total}',
                      f'name:"{word}" number:{number}'):
                r = None
                for attempt in (1, 2):  # the API is slow when cold; retry once
                    try:
                        r = requests.get(_PTCGIO_URL, headers=headers, timeout=30,
                                         params={"q": q, "pageSize": 3,
                                                 "orderBy": "-set.releaseDate"})
                        break
                    except Exception as e:
                        if attempt == 2:
                            print(f"  [ptcgio error] {e}")
                            return None, None
                if r.status_code == 429:
                    print("  [ptcgio rate-limited — get a free key at dev.pokemontcg.io]")
                    return None, None
                if r.status_code != 200:
                    continue
                data = r.json().get("data", [])
                if not data:
                    continue
                card = data[0]
                tp = (card.get("tcgplayer") or {}).get("prices") or {}
                for variant in ("holofoil", "normal", "reverseHolofoil",
                                "1stEditionHolofoil", "unlimitedHolofoil"):
                    usd = (tp.get(variant) or {}).get("market")
                    if usd:
                        set_name = (card.get("set") or {}).get("name", "?")
                        label = (f"ptcgio:{card.get('name','?')} "
                                 f"{card.get('number','?')}/{printed_total} "
                                 f"{set_name} [{variant}]")
                        result = (float(usd) * config.USD_TO_LOCAL_RATE, label)
                        break
                if result[0]:
                    break
            if result[0]:
                break

        conn.execute("INSERT OR REPLACE INTO price_cache (key, price, label, ts) "
                     "VALUES (?,?,?,?)", (key, result[0], result[1], time.time()))
        conn.commit()
        return result
    finally:
        conn.close()


# ── dispatcher ────────────────────────────────────────────────────────
def market_value(title: str):
    """Returns (market_value_local, source_label) or (None, None)."""
    src = config.PRICE_SOURCE
    if src == "manual":
        return _manual_lookup(title)
    if src == "tcgplayer":
        # manual CSV overrides (real PH prices); else TCGplayer direct (covers
        # JP/Korean/current sets, strict number match). NOTE: TCGplayer is the
        # US/global market — see the PH-gap caveat; treat as a reference anchor.
        price, label = _manual_lookup(title)
        if price:
            return price, label
        import tcg_price
        price, label = tcg_price.market_value(title)
        if price:
            return price, label
        # fallback: PriceCharting covers vintage/promo TCGplayer lacks
        import pc_price
        return pc_price.market_value(title)
    if src == "pokemontcgio":
        # manual CSV is the override (real PH prices); API is the wide net
        price, label = _manual_lookup(title)
        if price:
            return price, label
        return _ptcgio_lookup(title)
    if src == "pokemonpricetracker":
        return _ppt_lookup(title)
    if src == "pricecharting":
        return _pc_lookup(title)
    return None, None
