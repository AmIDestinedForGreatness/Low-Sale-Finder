"""
build_fingerprints.py — build the local card-fingerprint index.

A card's ATTACK DAMAGE numbers (30+, 230, 200+…) + HP are printed big and
bold — the one thing OCR reads reliably off any photo, English OR Japanese.
Very few cards share an exact damage profile, so it works as a fingerprint:
photo → damage numbers → this index → card name → TCGplayer.

Data: github.com/PokemonTCG/pokemon-tcg-data (cards/en/*.json).
Run once (and re-run when new sets release):  E:\python.exe build_fingerprints.py
"""
import io
import json
import os
import re
import sqlite3
import zipfile

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ZIP_URL = "https://codeload.github.com/PokemonTCG/pokemon-tcg-data/zip/refs/heads/master"
DB = os.path.join(HERE, "fingerprints.sqlite")


def norm_damage(d):
    """'30+' -> '30+', '20×' -> '20x', '230' -> '230' (keep the modifier —
    30 and 30+ are different attacks)."""
    d = (d or "").strip().replace("×", "x")
    return d if re.match(r"^\d{1,3}[+x-]?$", d) else None


def main():
    zip_path = os.path.join(HERE, "fp_data.zip")
    if os.path.exists(zip_path):
        raw = open(zip_path, "rb").read()
        print(f"using cached fp_data.zip ({len(raw):,} bytes)")
    else:
        print("downloading card data…")
        raw = requests.get(ZIP_URL, timeout=120).content
        open(zip_path, "wb").write(raw)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    card_files = [n for n in zf.namelist()
                  if re.search(r"/cards/en/[^/]+\.json$", n)]
    print(f"{len(card_files)} set files")

    conn = sqlite3.connect(DB)
    conn.execute("DROP TABLE IF EXISTS fp")
    conn.execute("CREATE TABLE fp (id TEXT PRIMARY KEY, name TEXT, hp INTEGER, "
                 "damages TEXT, subtypes TEXT, setname TEXT, number TEXT, "
                 "rarity TEXT)")
    n = 0
    for fn in card_files:
        try:
            cards = json.loads(zf.read(fn))
        except Exception:
            continue
        setname = os.path.basename(fn)[:-5]
        for c in cards:
            dmgs = [norm_damage(a.get("damage")) for a in (c.get("attacks") or [])]
            dmgs = [d for d in dmgs if d]
            hp = None
            try:
                hp = int(re.sub(r"\D", "", c.get("hp") or "") or 0) or None
            except ValueError:
                pass
            conn.execute("INSERT OR REPLACE INTO fp VALUES (?,?,?,?,?,?,?,?)",
                         (c.get("id"), c.get("name"), hp, ",".join(dmgs),
                          ",".join(c.get("subtypes") or []), setname,
                          str(c.get("number") or ""), c.get("rarity") or ""))
            n += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM fp").fetchone()[0]
    with_dmg = conn.execute("SELECT COUNT(*) FROM fp WHERE damages != ''").fetchone()[0]
    conn.close()
    print(f"indexed {total:,} cards ({with_dmg:,} with attack damage) -> {DB}")


if __name__ == "__main__":
    main()
