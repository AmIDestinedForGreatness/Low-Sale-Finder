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


def _name_variants(name: str):
    """Names to try on TCGplayer, widest-net-first. TCGplayer stores XY-era
    Mega promos as 'M <Name> EX' (e.g. 'M Camerupt EX'), NOT 'Mega <Name>',
    and its synonym search does NOT bridge the two — so a 'Mega Camerupt'
    query silently never returns the XY198a promo. Emit both spellings; the
    strict number match downstream is what keeps precision, so casting a wider
    search net is safe."""
    seen, out = set(), []
    def add(v):
        v = " ".join((v or "").split())
        if v and v.lower() not in seen:
            seen.add(v.lower()); out.append(v)
    add(name)
    low = name.lower()
    if low.startswith("mega "):
        rest = name[5:].strip()
        add("M " + rest + " EX")   # 'M Camerupt EX' — the TCGplayer promo spelling
        add("M " + rest)
    return out


def _num_ok(result_num, token, want_lead):
    """True if a search result's number matches the listing's number.
    Promo-form tokens (XY158, XY198a, SM…) must match in FULL — so XY198a
    (Alt-Art Promo) is NOT confused with XY198 (Jumbo / XY Promos). Slash-form
    numbers (077/063) keep leading-number matching."""
    rn = (result_num or "").strip().lower()
    tk = (token or "").strip().lower()
    if re.match(r"(xy|sm|swsh|bw|hgss)\d", tk):
        return rn == tk
    return _lead(result_num or "") == want_lead


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


def _search(name, number_token, want_lead, prefer_jp, want_jumbo):
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
    # keep only exact number matches (full token for promos, lead for slash form)
    hits = []
    for it in results:
        num = str((it.get("customAttributes") or {}).get("number") or "")
        if _num_ok(num, number_token, want_lead):
            hits.append(it)
    if not hits:
        return None
    # Jumbo/oversized cards are a different collectible from the real card —
    # drop them unless the listing itself says jumbo.
    if not want_jumbo:
        non_jumbo = [h for h in hits if "jumbo" not in (h.get("setName", "").lower())]
        if non_jumbo:
            hits = non_jumbo
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
    want_jumbo = bool(re.search(r"\bjumbo\b", title, re.I))

    key = f"{name.lower()}|{number_token.lower()}|{int(prefer_jp)}"
    conn = _cache()
    try:
        row = conn.execute("SELECT price,label,ts FROM tcg_cache WHERE key=?",
                           (key,)).fetchone()
        if row and time.time() - row[2] < (3 * 86400 if row[0] else 86400):
            return (row[0], row[1]) if row[0] else (None, None)
        it = None
        for variant in _name_variants(name):
            it = _search(variant, number_token, want, prefer_jp, want_jumbo)
            if it:
                break
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
