"""
build_card_index.py — one-time (resumable) build of the card-image index used
to identify a card from a photo. Pulls every card's metadata + price from
pokemontcg.io, downloads its reference image (from the CDN, no API limit),
computes perceptual hashes, and stores everything in card_index.sqlite.

Run:  python build_card_index.py            (all sets — big, ~20k cards)
      python build_card_index.py swsh7 sv1  (only these set ids — fast)

Resumable: re-running skips cards already hashed. Kill/restart anytime.
"""
import io
import sqlite3
import sys
import time

import requests
from PIL import Image
import imagehash

import config

API = "https://api.pokemontcg.io/v2/cards"
INDEX_PATH = "card_index.sqlite"


def db():
    conn = sqlite3.connect(INDEX_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS cards (
        id TEXT PRIMARY KEY, name TEXT, number TEXT, set_name TEXT,
        price REAL, phash TEXT, dhash TEXT, ts REAL)""")
    return conn


def price_of(card):
    tp = (card.get("tcgplayer") or {}).get("prices") or {}
    for variant in ("holofoil", "normal", "reverseHolofoil",
                    "1stEditionHolofoil", "unlimitedHolofoil"):
        m = (tp.get(variant) or {}).get("market")
        if m:
            return float(m)
    return None


def build(set_ids=None):
    conn = db()
    headers = {}
    key = getattr(config, "POKEMONTCGIO_API_KEY", "")
    if key and "PASTE" not in key:
        headers["X-Api-Key"] = key

    query = " OR ".join(f"set.id:{s}" for s in set_ids) if set_ids else "*"
    page, total_new = 1, 0
    while True:
        try:
            r = requests.get(API, headers=headers, timeout=60, params={
                "q": query, "page": page, "pageSize": 250,
                "select": "id,name,number,set,images,tcgplayer"})
            r.raise_for_status()
        except Exception as e:
            print(f"[page {page}] api error: {e}; retrying in 10s")
            time.sleep(10); continue
        cards = r.json().get("data", [])
        if not cards:
            break
        for c in cards:
            cid = c["id"]
            if conn.execute("SELECT 1 FROM cards WHERE id=? AND phash IS NOT NULL",
                            (cid,)).fetchone():
                continue
            url = (c.get("images") or {}).get("small")
            if not url:
                continue
            try:
                ir = requests.get(url, timeout=30); ir.raise_for_status()
                img = Image.open(io.BytesIO(ir.content)).convert("RGB")
            except Exception:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?,?,?,?)",
                (cid, c.get("name"), c.get("number"),
                 (c.get("set") or {}).get("name"), price_of(c),
                 str(imagehash.phash(img)), str(imagehash.dhash(img)), time.time()))
            total_new += 1
            if total_new % 50 == 0:
                conn.commit()
                print(f"  indexed {total_new} new (page {page})...")
            time.sleep(0.03)
        conn.commit()
        print(f"[page {page}] done — {total_new} new so far")
        page += 1
    n = conn.execute("SELECT COUNT(*) FROM cards WHERE phash IS NOT NULL").fetchone()[0]
    print(f"DONE. index holds {n} cards -> {INDEX_PATH}")


if __name__ == "__main__":
    build(sys.argv[1:] or None)
