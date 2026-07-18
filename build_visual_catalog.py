"""Resumable local visual catalog downloader and perceptual-hash index.

Usage: E:\\python.exe build_visual_catalog.py [--limit N] [--delay 0.05]
The image CDN is public; this job is deliberately bounded, resumable, and
rate-limited. It never changes candidate identity by itself.
"""
import argparse
import os
import sqlite3
import time

import requests

from providers.artwork import _art_region

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "fingerprints.sqlite")
ROOT = os.path.join(HERE, "dataset", "visual_catalog")
URL = "https://images.pokemontcg.io/{set_id}/{number}.png"


def _safe_name(value):
    return str(value or "").replace("/", "_").replace("\\", "_")


def _hash_file(path):
    import imagehash
    from PIL import Image
    with Image.open(path) as image:
        art = _art_region(image)
        return str(imagehash.phash(art)), str(imagehash.dhash(art))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="process at most N rows this run (0 means all)")
    ap.add_argument("--delay", type=float, default=.08,
                    help="seconds between CDN requests")
    ap.add_argument("--timeout", type=float, default=30)
    args = ap.parse_args()
    os.makedirs(ROOT, exist_ok=True)
    conn = sqlite3.connect(DB)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(fp)")}
    if "visual_path" not in cols:
        conn.execute("ALTER TABLE fp ADD COLUMN visual_path TEXT")
    if "visual_phash" not in cols:
        conn.execute("ALTER TABLE fp ADD COLUMN visual_phash TEXT")
    if "visual_dhash" not in cols:
        conn.execute("ALTER TABLE fp ADD COLUMN visual_dhash TEXT")
    rows = conn.execute(
        "SELECT id, setname, number FROM fp ORDER BY id").fetchall()
    session = requests.Session()
    done = failed = skipped = hashed = 0
    started = time.monotonic()
    for card_id, set_id, number in rows:
        if args.limit and done + failed + skipped >= args.limit:
            break
        safe = _safe_name(card_id)
        path = os.path.join(ROOT, safe + ".png")
        row = conn.execute(
            "SELECT visual_phash, visual_dhash FROM fp WHERE id=?", (card_id,)
        ).fetchone()
        if row and row[0] and row[1] and os.path.exists(path):
            skipped += 1
            continue
        if not os.path.exists(path):
            url = URL.format(set_id=set_id, number=number.split("/")[0])
            try:
                response = session.get(url, timeout=args.timeout)
                response.raise_for_status()
                if not response.headers.get("content-type", "").lower().startswith("image/"):
                    raise ValueError("CDN response was not an image")
                with open(path, "wb") as handle:
                    handle.write(response.content)
                time.sleep(max(0, args.delay))
            except Exception as exc:
                failed += 1
                print(f"FAIL {card_id}: {exc}", flush=True)
                continue
        try:
            phash, dhash = _hash_file(path)
            conn.execute("UPDATE fp SET visual_path=?, visual_phash=?, visual_dhash=? WHERE id=?",
                         (path, phash, dhash, card_id))
            hashed += 1
            done += 1
            if done % 100 == 0:
                conn.commit()
                print(f"progress hashed={done} failed={failed} skipped={skipped}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"HASH FAIL {card_id}: {exc}", flush=True)
    conn.commit()
    conn.close()
    elapsed = time.monotonic() - started
    print(f"complete hashed={hashed} failed={failed} skipped={skipped} seconds={elapsed:.2f}")


if __name__ == "__main__":
    main()
