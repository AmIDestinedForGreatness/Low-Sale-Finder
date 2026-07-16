"""
valuator.py — the dashboard's card valuator: photo → card → valuation.

Flow (human-in-the-loop by design — the honest fix for image matching):
  1. OCR the uploaded photo (Windows built-in OCR, ocr_card.ps1)
  2. Guess a search query (card name + collector number when readable)
  3. Return TCGplayer CANDIDATES with product images — the user taps the
     right one instead of trusting a fuzzy auto-match (LESSONS.md: image
     hashing failed on real photos; a wrong match is worse than one tap)
  4. Valuate the confirmed product:
       - market price (pricepoints)
       - REAL recent solds, per condition (latestsales)  [LESSONS L16/L17]
       - sales velocity -> confidence tag (a price with no sales is a rumor)
"""
import os
import re
import sqlite3
import statistics
import subprocess
import time

import requests

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_H = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
      "Origin": "https://www.tcgplayer.com", "Referer": "https://www.tcgplayer.com/"}
SEARCH = "https://mp-search-api.tcgplayer.com/v1/search/request"
PRICE = "https://mpapi.tcgplayer.com/v2/product/{}/pricepoints"
SALES = "https://mpapi.tcgplayer.com/v2/product/{}/latestsales"
IMG = "https://product-images.tcgplayer.com/{}.jpg"

_HERE = os.path.dirname(os.path.abspath(__file__))

# words OCR reads off card BODIES that are never part of the card's name
_NOISE = re.compile(
    r"^(stage|basic|evolves|ability|weakness|resistance|retreat|hp\s*\d*|"
    r"illus|item|trainer|supporter|energy|put\b|discard|draw|search|once|"
    r"when|attach|flip|this|the|your?|d?amage|"
    r"pok[e�]mon\b|nintendo|creatures|game\s*freak)\b", re.I)
_NUM_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b|"
                     r"\b((?:XY|SM|SWSH|BW|HGSS|SVP?)\d{1,3}[A-Za-z]?)\b", re.I)


def ocr_lines(image_path):
    """Run Windows OCR on the photo; [] if the engine/scan fails."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", os.path.join(_HERE, "ocr_card.ps1"), image_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60)  # utf-8: JP glyphs crashed the default cp1252 decode
        return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception:
        return []


# ── attack-damage fingerprint (the auto-ID path) ──────────────────────
# Attack damage numbers (30+, 230, 200+…) are the biggest, boldest text on a
# card — the one thing OCR reads reliably even on Japanese cards. Very few
# cards share an exact profile (often exactly ONE), so damages + HP work as
# a fingerprint against the local index built by build_fingerprints.py.
FP_DB = os.path.join(_HERE, "fingerprints.sqlite")
_DMG = re.compile(r"(?<![\d/.,])(\d{2,3})\s*([+x×])?(?![\d/.,])")


def _extract_damages(lines):
    dmgs, hp, tags = set(), None, set()
    for ln in lines:
        if re.search(r"\d{1,3}\s*/\s*\d{1,3}", ln):
            continue                      # collector number, not damage
        low = ln.lower()
        if "tag team" in low:
            tags.add("TAG TEAM")
        m = re.search(r"hp\s*(\d{2,3})", low)
        if m:
            hp = int(m.group(1))
        for m in _DMG.finditer(ln):
            v = int(m.group(1))
            if 10 <= v <= 400 and v % 5 == 0 and v != hp:
                mod = m.group(2) or ""
                # NB: `mod in "x×"` is True for "" — must compare exactly
                dmgs.add(m.group(1) + ("x" if mod in ("x", "×") else mod))
    return dmgs, hp, tags


def fingerprint_names(lines, limit=5):
    """OCR lines -> candidate card NAMES via the damage-profile index."""
    dmgs, hp, tags = _extract_damages(lines)
    if len(dmgs) < 2 or not os.path.exists(FP_DB):
        return []
    conn = sqlite3.connect(FP_DB)
    try:
        best = {}
        for name, chp, cd, subs in conn.execute(
                "SELECT name, hp, damages, subtypes FROM fp WHERE damages != ''"):
            cds = set(cd.split(","))
            if not dmgs <= cds:           # every OCR'd damage must be on the card
                continue
            score = (len(dmgs)
                     + (2 if hp and chp == hp else 0)
                     + (1 if tags and tags <= set(subs.split(",")) else 0)
                     - 0.1 * max(0, len(cds) - len(dmgs)))
            if name not in best or score > best[name]:
                best[name] = score
        return [n for n, _ in sorted(best.items(), key=lambda kv: -kv[1])][:limit]
    finally:
        conn.close()


# JP set codes are printed in LATIN on the card (sm12a, s4a, xy10…) and,
# with the collector number, uniquely identify the card on TCGplayer —
# the searchable ID for Japanese cards whose names our OCR can't read
_SET_RE = re.compile(r"\b(?:sm|sv|swsh|xy|bw|dp|pcg|cp)\d{1,2}[a-z]?\b", re.I)
# lines that are card MECHANIC labels, never a name ("TAG TEAM" -> "TEAM")
_MECH = re.compile(r"^(tag\s*)?(team|gx|ex|v(max|star)?|hp\s*\d*)$", re.I)


def _is_junk(text):
    """True when OCR produced gibberish, not a name (e.g. 'li&DhJ' from a
    Japanese card). Junk word = 3+ letters with no vowel, or random inner
    capitals. A line is junk when most of its words are."""
    words = re.findall(r"[A-Za-z]+", text)
    if not words:
        return True
    junk = 0
    for w in words:
        no_vowel = len(w) >= 3 and not re.search(r"[aeiouyAEIOUY]", w)
        # short scrambled-case fragments ("DhJ") — long Mc/Mac names are real
        inner_caps = len(w) <= 4 and re.search(r"[a-z][A-Z]", w) is not None
        if no_vowel or inner_caps:
            junk += 1
    return junk * 2 >= len(words)


def guess_query(lines):
    """Best-guess card name + collector number from OCR lines.
    The name is printed big near the top; body text is filtered by _NOISE."""
    number, setcode = None, None
    for ln in lines:
        if not number:  # prefer the slash form (016/173) over promo tokens
            m = re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", ln)
            if m:
                number = m.group(0).replace(" ", "")
        if not setcode:
            m = _SET_RE.search(ln)
            if m:
                setcode = m.group(0).lower()
    if not number:
        for ln in lines:
            m = _NUM_RE.search(ln)
            if m:
                number = m.group(0).replace(" ", "")
                break
    name = ""
    for ln in lines[:6]:                      # name sits in the top lines
        if _SET_RE.search(ln) or re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", ln):
            continue  # footer line (set code / collector number), never the name
        cand = re.sub(r"[^A-Za-z' .&-]", " ", ln)
        cand = " ".join(cand.split()).strip()
        if len(cand) < 3 or _NOISE.match(cand) or _MECH.match(cand) or _is_junk(cand):
            continue
        # OCR often drops the stylized GX/EX/V suffix — keep what it read
        name = cand
        break
    if not name:
        # fallback: ITEM cards are legitimately NAMED with "noise" words
        # ("Weakness Policy") — accept a multi-word top line after all
        for ln in lines[:6]:
            if _SET_RE.search(ln) or re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", ln):
                continue  # footer line here too — "sm12a c 016/173 RR" is not a name
            cand = " ".join(re.sub(r"[^A-Za-z' .&-]", " ", ln).split()).strip()
            if (len(cand) >= 3 and len(cand.split()) >= 2
                    and not _MECH.match(cand) and not _is_junk(cand)):
                name = cand
                break
    if not name and setcode:
        # Japanese card: no readable Latin name, but setcode+number IS the
        # unique ID (verified: "sm12a 016/173" -> exactly Reshiram&Charizard)
        name = setcode
    return name, number


def search_candidates(query, size=12):
    """TCGplayer candidates for the picker grid (image = user's eyes).
    TCGplayer's search returns nothing when the collector number is in the
    query text — so search by NAME only, then rank number-matches first."""
    m = (re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", query) or _NUM_RE.search(query))
    number = (m.group(0).replace(" ", "") if m else "").lower()
    if _SET_RE.search(query) and number:
        # JP set-code query: TCGplayer resolves "sm12a 016/173" directly —
        # send it whole, don't strip the number
        name_q = query
    else:
        name_q = " ".join(_NUM_RE.sub(" ", query).split()) or query

    def _hit(q):
        try:
            r = requests.post(
                SEARCH + "?q=" + requests.utils.quote(q) + "&isList=false",
                headers=_H, timeout=20, json={
                    "algorithm": "sales_synonym_v2", "from": 0, "size": size,
                    "filters": {"term": {"productLineName": ["pokemon", "pokemon-japan"]},
                                "range": {}},
                    "context": {"shippingCountry": "US"}, "query": q})
            return (r.json().get("results") or [{}])[0].get("results", [])
        except Exception:
            return []

    # OCR chops leading letters ("eakness Policy") — when a query finds
    # nothing, retry with the first word dropped, then the last
    results, words = _hit(name_q), name_q.split()
    if not results and len(words) >= 2:
        results = _hit(" ".join(words[1:]))
    if not results and len(words) >= 2:
        results = _hit(" ".join(words[:-1]))
    out = []
    for it in results:
        pid = it.get("productId")
        if not pid:
            continue
        pid = int(pid)
        out.append({
            "pid": pid,
            "name": it.get("productName", "?"),
            "set": it.get("setName", "?"),
            "number": str((it.get("customAttributes") or {}).get("number") or ""),
            "line": it.get("productLineName", ""),
            "market": it.get("marketPrice"),
            "img": IMG.format(pid),
            "url": f"https://www.tcgplayer.com/product/{pid}",
        })
    if number:  # user's number: bubble exact matches to the front
        lead = number.split("/")[0].lstrip("0")
        out.sort(key=lambda c: (0 if c["number"].lower() == number else
                                1 if c["number"].split("/")[0].lstrip("0") == lead else 2))
    return out


def _confidence(n_sales, days_span):
    """L16: valuation = price x confidence; confidence comes from velocity."""
    if n_sales < 3:
        return "LOW", "under 3 recorded sales — price is a rumor, not a market"
    rate = n_sales / max(days_span, 1)
    if rate >= 0.5:
        return "HIGH", f"~{rate:.1f} sales/day — value is market-proven"
    if rate >= 0.1:
        return "MED", f"~{rate*30:.0f} sales/month — reasonably traded"
    return "LOW", f"~{rate*30:.1f} sales/month — thin market, price unstable"


# fallback multipliers when a condition has no real solds (industry-typical)
_COND_FALLBACK = {"Near Mint": 1.0, "Lightly Played": 0.80,
                  "Moderately Played": 0.60, "Heavily Played": 0.45,
                  "Damaged": 0.30}


def valuate(pid, ph_factor=1.2):
    """Full valuation of a confirmed TCGplayer product."""
    rate = getattr(config, "USD_TO_LOCAL_RATE", 58)
    out = {"pid": pid, "usd_rate": rate, "ph_factor": ph_factor}

    # market price (highest printing marketPrice, same rule as tcg_price)
    market = None
    try:
        r = requests.get(PRICE.format(int(pid)), headers={"User-Agent": UA}, timeout=15)
        for p in r.json():
            m = p.get("marketPrice")
            if m and (market is None or m > market):
                market = m
    except Exception:
        pass
    out["market_usd"] = market
    out["market_php"] = round(market * rate) if market else None

    # real recent solds, grouped by condition  [L16 + L17]
    sales, conds = [], {}
    try:
        r = requests.post(SALES.format(int(pid)), headers=_H, timeout=20,
                          json={"listingType": "All", "limit": 25, "offset": 0})
        sales = (r.json().get("data") or []) if r.status_code == 200 else []
    except Exception:
        pass
    ts = []
    for s in sales:
        cond = s.get("condition") or "?"
        price = s.get("purchasePrice")
        if price:
            conds.setdefault(cond, []).append(float(price))
        d = (s.get("orderDate") or "")[:10]
        if d:
            try:
                ts.append(time.mktime(time.strptime(d, "%Y-%m-%d")))
            except ValueError:
                pass
    days_span = max(1, round((max(ts) - min(ts)) / 86400)) if len(ts) >= 2 else 1
    level, why = _confidence(len(sales), days_span)
    out["sales"] = [{"date": (s.get("orderDate") or "")[:10],
                     "usd": s.get("purchasePrice"),
                     "condition": s.get("condition")} for s in sales[:10]]
    out["n_sales"] = len(sales)
    out["days_span"] = days_span
    out["confidence"] = level
    out["confidence_why"] = why

    # per-condition price: REAL sold median when we have it, fallback % of
    # market when we don't (flagged, so the UI can say which is which)
    base = market
    by_cond = {}
    for cond, mult in _COND_FALLBACK.items():
        real = conds.get(cond) or []
        if real:
            usd = statistics.median(real)
            by_cond[cond] = {"usd": round(usd, 2), "php": round(usd * rate),
                             "from": f"{len(real)} real sold"}
        elif base:
            usd = base * mult
            by_cond[cond] = {"usd": round(usd, 2), "php": round(usd * rate),
                             "from": "est. % of market"}
    out["by_condition"] = by_cond

    # sell suggestion (his formula: TCG x rate x PH factor), per condition
    out["suggest"] = {
        cond: {"list_php": round(v["php"] * ph_factor),
               "steal_php": round(v["php"] * 0.72)}
        for cond, v in by_cond.items()}
    return out
