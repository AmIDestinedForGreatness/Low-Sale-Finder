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
    # set id -> printedTotal, so numbers become full "119/122" collector
    # numbers (bare numerators are ambiguous across a card's variants)
    totals = {}
    sets_file = next((n for n in zf.namelist() if n.endswith("/sets/en.json")), None)
    if sets_file:
        for s in json.loads(zf.read(sets_file)):
            totals[s.get("id")] = s.get("printedTotal")

    conn = sqlite3.connect(DB)
    # Preserve visual_* columns (perceptual-hash catalog, ~2hrs to build) across
    # a refresh: stash the old fp table's visual data keyed by id, rebuild fp
    # fresh from upstream, then restore whatever visual data still matches.
    visual_backup = {}
    has_old_fp = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='fp'"
    ).fetchone()[0]
    if has_old_fp:
        try:
            for row in conn.execute(
                    "SELECT id, visual_path, visual_phash, visual_dhash FROM fp "
                    "WHERE visual_phash IS NOT NULL"):
                visual_backup[row[0]] = row[1:]
        except sqlite3.OperationalError:
            pass  # old schema had no visual_* columns yet
    conn.execute("DROP TABLE IF EXISTS fp")
    conn.execute("CREATE TABLE fp (id TEXT PRIMARY KEY, name TEXT, hp INTEGER, "
                 "damages TEXT, subtypes TEXT, setname TEXT, number TEXT, "
                 "rarity TEXT, dex INTEGER, visual_path TEXT, visual_phash TEXT, "
                 "visual_dhash TEXT)")
    # LAYER E: attack/ability NAMES — big readable English text that OCR
    # nails even on binder-cell crops, and near-unique per card
    conn.execute("DROP TABLE IF EXISTS atk")
    conn.execute("CREATE TABLE atk (atk TEXT, kind TEXT, card TEXT, "
                 "number TEXT, setname TEXT)")
    conn.execute("CREATE INDEX idx_atk ON atk (atk)")
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
            # National Dex number: JP vintage cards print "NO.398" — a direct
            # species ID when the name itself is unreadable (Layer D)
            dex = (c.get("nationalPokedexNumbers") or [None])[0]
            num = str(c.get("number") or "")
            total = totals.get(setname)
            if num.isdigit() and total:
                num = f"{num}/{total}"     # full collector number
            vpath, vphash, vdhash = visual_backup.get(c.get("id"), (None, None, None))
            conn.execute("INSERT OR REPLACE INTO fp VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (c.get("id"), c.get("name"), hp, ",".join(dmgs),
                          ",".join(c.get("subtypes") or []), setname,
                          num, c.get("rarity") or "", dex, vpath, vphash, vdhash))
            for a in (c.get("attacks") or []):
                if a.get("name"):
                    conn.execute("INSERT INTO atk VALUES (?,?,?,?,?)",
                                 (a["name"].lower().strip(), "attack",
                                  c.get("name"), num, setname))
            for a in (c.get("abilities") or []):
                if a.get("name"):
                    conn.execute("INSERT INTO atk VALUES (?,?,?,?,?)",
                                 (a["name"].lower().strip(), "ability",
                                  c.get("name"), num, setname))
            n += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM fp").fetchone()[0]
    with_dmg = conn.execute("SELECT COUNT(*) FROM fp WHERE damages != ''").fetchone()[0]
    conn.close()
    print(f"indexed {total:,} cards ({with_dmg:,} with attack damage) -> {DB}")


if __name__ == "__main__":
    main()
