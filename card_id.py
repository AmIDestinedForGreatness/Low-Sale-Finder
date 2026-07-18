"""
card_id.py — identify a Pokémon card from a photo using the perceptual-hash
index built by build_card_index.py. Returns the matched card + TCGplayer price,
or None when no confident match (messy/multi-card/unknown photos).
"""
import io
import os
import sqlite3
from functools import lru_cache

from PIL import Image
import imagehash
import network_safety

INDEX_PATH = os.path.join(os.path.dirname(__file__), "card_index.sqlite")
# max combined (phash+dhash) hamming distance to accept a match. Tighter =
# fewer false IDs. ~28 is a reasonable start; tune against real photos.
MATCH_THRESHOLD = 28


@lru_cache(maxsize=1)
def _load():
    if not os.path.exists(INDEX_PATH):
        return []
    conn = sqlite3.connect(INDEX_PATH)
    rows = conn.execute("SELECT id,name,number,set_name,price,phash,dhash "
                        "FROM cards WHERE phash IS NOT NULL").fetchall()
    conn.close()
    out = []
    for cid, name, num, setn, price, ph, dh in rows:
        out.append((cid, name, num, setn, price,
                    imagehash.hex_to_hash(ph), imagehash.hex_to_hash(dh)))
    return out


def identify(image):
    """image: a PIL.Image or an image-URL string. Returns dict or None."""
    idx = _load()
    if not idx:
        return None
    if isinstance(image, str):
        try:
            r = network_safety.fetch_public_bytes(image, timeout=30)
            if r.status_code < 200 or r.status_code >= 300:
                return None
            image = Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception:
            return None
    qp, qd = imagehash.phash(image), imagehash.dhash(image)
    best, best_dist = None, 999
    for cid, name, num, setn, price, ph, dh in idx:
        dist = (qp - ph) + (qd - dh)
        if dist < best_dist:
            best, best_dist = (cid, name, num, setn, price), dist
    if best is None or best_dist > MATCH_THRESHOLD:
        return None
    cid, name, num, setn, price = best
    return {"id": cid, "name": name, "number": num, "set": setn,
            "price_usd": price, "distance": best_dist}


def ready():
    return len(_load())
