"""
folder_dataset.py — identify every card photo in a folder, IMAGE-ONLY.

Built for consignment lots (first run: the overnight lot, 2026-07-17): a folder
of single-card photos and/or binder-page photos. Two capabilities the
system learned from that lot:

- ORIENTATION: phone photos come in sideways; RapidOCR reads rotated text
  scrambled and misses the footer. Landscape photos retry at 90/270 and
  the best-evidence rotation wins.
- BINDER PAGES: one photo, 2x2 cards. Auto-detected (3+ distinct
  vocabulary-validated names in the whole-image OCR, or "binder" in the
  filename) and split into overlapping quadrant crops, each identified
  independently.

Usage:  python folder_dataset.py "<folder>" [--price]
Output: dataset/<folder-slug>.json + console lines.
"""
import json
import os
import re
import sys
import tempfile
import time

from PIL import Image

import valuator
from profile_dataset import identify

EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _evidence_score(lines):
    name, number = valuator.guess_query(lines)
    return 2 * bool(name) + 2 * bool(number) + 0.05 * len(lines), name, number


def best_orientation(path, tmpdir):
    """Landscape photo of a portrait card reads scrambled — try upright
    rotations, keep the one with the strongest evidence."""
    img = Image.open(path)
    variants = [(0, path)]
    if img.width > img.height:
        for deg, t in ((90, Image.ROTATE_90), (270, Image.ROTATE_270)):
            out = os.path.join(tmpdir, f"rot{deg}_{os.path.basename(path)}.png")
            img.transpose(t).save(out)
            variants.append((deg, out))
    best = None
    for deg, p in variants:
        lines = valuator.ocr_lines(p)
        score = _evidence_score(lines)[0]
        if best is None or score > best[0]:
            best = (score, deg, p, lines)
    return best[1], best[2], best[3]          # rotation, path, lines


def distinct_names(lines):
    """How many DIFFERENT real card names appear? (>=3 = multi-card photo;
    tag-team cards legitimately read 2, so 2 is still a single card)"""
    names = set()
    for ln in lines:
        cand = " ".join(re.sub(r"[^A-Za-z' .&-]", " ", ln).split()).strip()
        if len(cand) < 3 or valuator._is_junk(cand):
            continue
        snapped = valuator.snap_name(cand)
        if snapped:
            names.add(snapped.split(" & ")[0])
    return names


def split_grid(path, tmpdir, rows=2, cols=2, pad=0.03):
    """Binder page -> overlapping cell crops, one card each. Cells are
    UPSCALED 2x — a quadrant crop halves effective resolution, which is
    exactly why tiny promo footers (XY117) died in cell OCR."""
    img = Image.open(path)
    w, h = img.size
    cells = []
    for r in range(rows):
        for c in range(cols):
            pw, ph = w / cols * pad, h / rows * pad
            box = (int(max(0, c * w / cols - pw)),
                   int(max(0, r * h / rows - ph)),
                   int(min(w, (c + 1) * w / cols + pw)),
                   int(min(h, (r + 1) * h / rows + ph)))
            out = os.path.join(tmpdir,
                               f"{os.path.splitext(os.path.basename(path))[0]}_r{r}c{c}.png")
            cell = img.crop(box)
            cell = cell.resize((cell.width * 2, cell.height * 2), Image.LANCZOS)
            cell.save(out)
            cells.append(out)
    return cells


def price_confident(ident):
    """Market price ONLY when the catalog product AGREES with the evidence:
    its name contains the identified name's tokens AND (when a number was
    read) the numbers match. First run priced a Snorlax off a Latios promo
    and four cards off neighbor numbers — L20 all over again: a price
    without an identity match is worse than no price."""
    cands = ident.get("candidates") or []
    number = ident.get("number")
    name = ident.get("name") or ""
    if not name or not cands:
        return None

    def toks(s):
        return set(re.sub(r"[^a-z& ]", " ",
                          s.split(" - ")[0].lower().replace("-", " ")).split()) \
               - {"full", "art", "promo"}
    want = toks(name)
    pick = None
    for cd in cands:
        num_ok = bool(number) and \
            valuator._norm_num(cd["number"]) == valuator._norm_num(str(number))
        name_ok = bool(want) and want <= toks(cd["name"])
        if name_ok and (num_ok or (not number and len(cands) == 1)):
            pick = cd
            break
    if not pick:
        return None
    try:
        val = valuator.valuate(pick["pid"])
        val["pid"] = pick["pid"]
        val["product"] = pick["name"]
        return val
    except Exception as e:
        return {"error": str(e)}


def main():
    folder = next((a for a in sys.argv[1:] if not a.startswith("--")), "")
    do_price = "--price" in sys.argv
    if not os.path.isdir(folder):
        sys.exit(f"not a folder: {folder}")
    slug = re.sub(r"[^a-z0-9]+", "_", os.path.basename(folder.rstrip("\\/")).lower()).strip("_")
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "dataset", f"{slug}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    results = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
    tmpdir = tempfile.mkdtemp(prefix="cards_")

    files = sorted(f for f in os.listdir(folder)
                   if f.lower().endswith(EXTS))
    print(f"{len(files)} photos in {folder}")
    for i, fn in enumerate(files):
        if fn in results:
            continue
        path = os.path.join(folder, fn)
        rot, upath, lines = best_orientation(path, tmpdir)
        n_names = len(distinct_names(lines))
        land = Image.open(upath).width > Image.open(upath).height
        # 3+ names = binder page (2x2). TWO names in a LANDSCAPE frame =
        # two cards side by side (live catch: a Volcanion EX + Golem EX
        # photo fused Golem's name with Volcanion's number). Tag-team
        # cards also read 2 names but are portrait — excluded. PAIR is
        # decided BEFORE the filename hint: a renamed "BINDER - …" pair
        # photo got force-quartered on a re-run.
        pair = n_names == 2 and land
        multi = (not pair) and (n_names >= 3 or "binder" in fn.lower())
        entry = {"file": fn, "rotation": rot,
                 "multi_card": multi or pair, "cards": []}
        if multi or pair:
            rows, cols = (1, 2) if pair else (2, 2)
            print(f"[{i+1}/{len(files)}] {fn} -> "
                  f"{'SIDE-BY-SIDE (1x2)' if pair else 'BINDER PAGE (2x2)'}")
            for cell in split_grid(upath, tmpdir, rows=rows, cols=cols):
                ident = identify([cell], [valuator.ocr_lines(cell)], set())
                ident.pop("ocr", None)
                if do_price:
                    ident["value"] = price_confident(ident)
                entry["cards"].append(ident)
                print(f"    cell -> {ident.get('name')} #{ident.get('number')} "
                      f"via={ident.get('via')} cands={len(ident.get('candidates', []))}")
            # BLEED SUPPRESSION: overlap crops can catch the NEIGHBOR's
            # title band — when two cells claim one name, keep only the
            # stronger evidence (via/number); the weaker becomes honest-unknown
            seen_names = {}
            for c in entry["cards"]:
                nm = c.get("name")
                if not nm:
                    continue
                score = 2 * bool(c.get("via")) + bool(c.get("number"))
                if nm in seen_names:
                    weaker = c if score <= seen_names[nm][1] else seen_names[nm][0]
                    weaker["name"] = None
                    weaker["bleed_suspected"] = nm
                    if c is not weaker:
                        seen_names[nm] = (c, score)
                else:
                    seen_names[nm] = (c, score)
        else:
            ident = identify([upath], [lines], set())
            ident.pop("ocr", None)
            if do_price:
                ident["value"] = price_confident(ident)
            entry["cards"].append(ident)
            print(f"[{i+1}/{len(files)}] {fn} (rot {rot}) -> {ident.get('name')} "
                  f"#{ident.get('number')} via={ident.get('via')} "
                  f"cands={len(ident.get('candidates', []))}")
        results[fn] = entry
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
        time.sleep(0.4)
    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
