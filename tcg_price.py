"""
tcg_price.py — market price straight from TCGplayer's own data (covers JP,
Korean and current sets that the outdated pokemontcg.io misses).

Uses TCGplayer's internal endpoints (same ones their website calls):
  - search  : mp-search-api.tcgplayer.com/v1/search/request   (name -> products)
  - price   : mpapi.tcgplayer.com/v2/product/{id}/pricepoints  (market price USD)

STRICT matching: a card is priced only when a result's collector number
matches the listing's number. No number match -> None (a wrong price is
worse than no price — it triggers false snipes).
"""
import re
import sqlite3
import time
import requests

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SEARCH = "https://mp-search-api.tcgplayer.com/v1/search/request"
PRICE = "https://mpapi.tcgplayer.com/v2/product/{}/pricepoints"
_H = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
      "Origin": "https://www.tcgplayer.com", "Referer": "https://www.tcgplayer.com/"}

# card number token: "077/063", "034/XY-P", "065/PCG-P", "197/SV-P",
# "XY158", "XY198a" (promo numbers may carry a trailing letter)
_NUM = re.compile(r"\b(\d{1,3})\s*/\s*(?:\d{1,3}|[A-Za-z]{1,4}-?[A-Za-z]?)|"
                  r"\b(?:XY|SM|SWSH|BW|HGSS)\d{1,3}[A-Za-z]?\b", re.I)
_GRADE = re.compile(r"\b(psa|bgs|cgc)\s*\d", re.I)
# 'pokemom' etc: tolerate the common misspelling of 'pokemon' in listings
_NAME_STOP = re.compile(r"\b(pokemon|pokemom|pokémon|card|tcg|japanese|japan|"
                        r"korean|english|vintage|promo|holo|full ?art|"
                        r"secret ?rare|rare|fullart|rainbow|meiji|mcdonald'?s?|"
                        r"choco(?:late)?)\b", re.I)


def _lead(number_token: str):
    m = re.match(r"(\d{1,3})", number_token.lstrip("XYySMswhbBWHG"))
    if m:
        return m.group(1).lstrip("0") or "0"
    m2 = re.search(r"(\d{1,3})", number_token)
    return (m2.group(1).lstrip("0") or "0") if m2 else None


def _extract(title: str):
    """Return (name, number_token) or (None, None)."""
    m = _NUM.search(title or "")
    if not m:
        return None, None
    number_token = m.group(0)
    # name = words before the number, minus stop-words
    name = title[:m.start()]
    name = _NAME_STOP.sub(" ", name)
    name = re.sub(r"[^A-Za-z' .-]", " ", name)
    name = " ".join(name.split()).strip()
    return (name or None), number_token


def _cache():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS tcg_cache "
                 "(key TEXT PRIMARY KEY, price REAL, label TEXT, ts REAL)")
    return conn


def _market(pid):
    try:
        r = requests.get(PRICE.format(int(pid)), headers={"User-Agent": UA}, timeout=15)
        best = None
        for p in r.json():
            m = p.get("marketPrice")
            if m and (best is None or m > best):
                best = m
        return best
    except Exception:
        return None


def _search(name, want_lead, prefer_jp):
    try:
        r = requests.post(
            SEARCH + "?q=" + requests.utils.quote(name) + "&isList=false",
            headers=_H, timeout=20, json={
                "algorithm": "sales_synonym_v2", "from": 0, "size": 25,
                "filters": {"term": {"productLineName": ["pokemon", "pokemon-japan"]},
                            "range": {}},
                "context": {"shippingCountry": "US"}, "query": name})
        results = (r.json().get("results") or [{}])[0].get("results", [])
    except Exception:
        return None
    # keep only exact leading-number matches
    hits = []
    for it in results:
        num = str((it.get("customAttributes") or {}).get("number") or "")
        if _lead(num) == want_lead:
            hits.append(it)
    if not hits:
        return None
    if prefer_jp:
        jp = [h for h in hits if h.get("productLineName") == "pokemon-japan"
              or "japan" in (h.get("setName", "").lower())]
        if jp:
            hits = jp
    return hits[0]


def market_value(title: str):
    """(price_local, label) or (None, None). Grades skipped (raw market only)."""
    if _GRADE.search(title or ""):
        return None, None
    name, number_token = _extract(title)
    if not name or not number_token:
        return None, None
    want = _lead(number_token)
    prefer_jp = bool(re.search(r"japan|jp\b|korean", title, re.I))

    key = f"{name.lower()}|{number_token.lower()}|{int(prefer_jp)}"
    conn = _cache()
    try:
        row = conn.execute("SELECT price,label,ts FROM tcg_cache WHERE key=?",
                           (key,)).fetchone()
        if row and time.time() - row[2] < (3 * 86400 if row[0] else 86400):
            return (row[0], row[1]) if row[0] else (None, None)
        it = _search(name, want, prefer_jp)
        price, label = None, None
        if it:
            usd = it.get("marketPrice") or _market(it.get("productId"))
            if usd:
                price = float(usd) * config.USD_TO_LOCAL_RATE
                label = f"tcg:{it.get('productName','?')} {it.get('setName','?')} (${usd})"
        conn.execute("INSERT OR REPLACE INTO tcg_cache VALUES (?,?,?,?)",
                     (key, price, label, time.time()))
        conn.commit()
        return (price, label)
    finally:
        conn.close()
