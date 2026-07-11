"""
prices.py — looks up market value for a card given its listing title.
Supports three backends, chosen in config.PRICE_SOURCE.

Returns market value already converted to LOCAL currency, or None if unknown.
"""
import csv
import os
import re
import requests
from functools import lru_cache
from rapidfuzz import fuzz, process

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
    rows = _load_manual()
    if not rows:
        return None, None
    keywords = [k for k, _ in rows]
    match = process.extractOne(title.lower(), keywords, scorer=fuzz.token_set_ratio)
    if match and match[1] >= 75:        # 75% fuzzy confidence
        kw = match[0]
        for k, price in rows:
            if k == kw:
                return price, f"manual:{kw} ({match[1]}%)"
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


# ── dispatcher ────────────────────────────────────────────────────────
def market_value(title: str):
    """Returns (market_value_local, source_label) or (None, None)."""
    src = config.PRICE_SOURCE
    if src == "manual":
        return _manual_lookup(title)
    if src == "pokemonpricetracker":
        return _ppt_lookup(title)
    if src == "pricecharting":
        return _pc_lookup(title)
    return None, None
