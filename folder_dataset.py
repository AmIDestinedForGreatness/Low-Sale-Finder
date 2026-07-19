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

import cv2
import numpy as np
from PIL import Image

import valuator
from profile_dataset import identify

EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_FRACTION_RE = re.compile(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)")

# Real Pokemon card ratio is 63mm x 88mm (~0.716); allow slop for perspective/
# crop noise, portrait or its landscape inverse.
_CARD_AR_RANGE = ((0.55, 0.85), (1.15, 1.85))


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


def distinct_collector_fractions(lines):
    """Return OCR collector fractions, preserving only distinct values."""
    return {(int(a), int(b)) for ln in lines for a, b in _FRACTION_RE.findall(ln)
            if int(b) >= 10}


def _iou(a, b):
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _order_corners(pts):
    """Order 4 points as top-left, top-right, bottom-right, bottom-left.
    (x+y) is smallest at TL / largest at BR; (x-y) is largest at TR /
    smallest at BL. Standard document-scanner ordering, needed so the
    perspective warp never mirrors or twists the card."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = (pts[:, 0] - pts[:, 1])
    return np.array([pts[np.argmin(s)], pts[np.argmax(d)],
                     pts[np.argmax(s)], pts[np.argmin(d)]], dtype=np.float32)


def _contour_quad(contour):
    """Best-effort 4-corner fit for a card contour: approxPolyDP at ~2% of
    perimeter (clean rectangle fit) with cv2.minAreaRect box points as the
    fallback when the polygon doesn't reduce to exactly 4 points."""
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
    if len(approx) == 4:
        return approx.reshape(4, 2).astype(np.float32)
    return cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)


# Real card is 63x88mm; 630x880 keeps the true aspect ratio at a resolution
# comparable to the catalog's reference scans.
_WARP_SIZE = (630, 880)


def warp_card(image_bgr, quad, size=_WARP_SIZE):
    """Perspective-flatten a detected card quadrilateral to a canonical
    portrait rectangle — the NolanAmblard 'document scanner' step. The
    catalog's hashes came from clean flat reference scans; hashing a tilted
    noisy crop against them misses, hashing the flattened card can hit.

    A landscape quad (card lying sideways in the photo) is warped to
    landscape then rotated 90° — which of the two 90° directions is correct
    is unknowable from geometry alone, so callers must treat the 180°
    rotation of the result as a fallback variant (probe_contours does)."""
    quad = _order_corners(quad)
    tl, tr, br, bl = quad
    qw = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    qh = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    w, h = size
    if qw > qh:  # card is sideways in the photo
        dst = np.array([[0, 0], [h - 1, 0], [h - 1, w - 1], [0, w - 1]],
                       dtype=np.float32)
        m = cv2.getPerspectiveTransform(quad, dst)
        flat = cv2.warpPerspective(image_bgr, m, (h, w))
        return cv2.rotate(flat, cv2.ROTATE_90_CLOCKWISE)
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]],
                   dtype=np.float32)
    m = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(image_bgr, m, (w, h))


def detect_card_regions(path, with_quads=False):
    """Find card-shaped rectangles by edge/contour detection, for pages where
    the cards AREN'T a clean grid (mixed-set consignment binders: different
    products, different sizes, no shared name/number repetition for the
    text-based signals in should_probe_grid to key off). Real cards have a
    fixed ~0.716 aspect ratio regardless of language or set, so this signal
    is language- and content-agnostic — it only looks at shape.

    Returns boxes in reading order (top-to-bottom, then left-to-right), or
    [] if fewer than 2 plausible card shapes are found. With
    ``with_quads=True`` returns ``(boxes, quads)`` where each quad is the
    detected 4-corner outline in original-image coordinates (``None`` for
    boxes synthesized by grid completion — those have no contour).
    """
    img = cv2.imread(path)
    if img is None:
        return ([], []) if with_quads else []
    h, w = img.shape[:2]
    img_area = h * w
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    # 2 dilation passes bridges the gap between ADJACENT cards on a dense
    # grid page (a real 3x4=12-card page merged its top row into one blob
    # spanning 3 cards, which then correctly failed the size-consistency
    # check below and vanished entirely instead of being split). 1 pass
    # still closes gaps within a single card's own border but stops
    # bridging separate neighboring cards (verified: recovers 11/12 real
    # cards on that page, up from 8/12, with no new false positives on the
    # known single-card dataset).
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < img_area * 0.03 or area > img_area * 0.5:
            continue          # too small to be a whole card / too big (the page itself)
        ar = cw / max(ch, 1)
        if not any(lo <= ar <= hi for lo, hi in _CARD_AR_RANGE):
            continue
        boxes.append((x, y, cw, ch, area, _contour_quad(c)))

    # NON-MAX SUPPRESSION: a card's outer border and its inner artwork frame
    # are nested, highly-overlapping contours from the SAME card, not two
    # cards — keep only the larger of any pair that overlaps heavily.
    boxes.sort(key=lambda b: -b[4])
    kept = []
    for b in boxes:
        if all(_iou(b, k) < 0.3 for k in kept):
            kept.append(b)

    # SIZE CONSISTENCY: real multi-card layouts have similarly-sized cards
    # (same rough distance-from-camera); a stray unrelated contour (a
    # thumbnail, a price tag) is usually a very different size.
    if len(kept) >= 2:
        areas = sorted(b[4] for b in kept)
        median = areas[len(areas) // 2]
        kept = [b for b in kept if 0.5 <= b[4] / median <= 2.0]

    if len(kept) < 2:
        return ([], []) if with_quads else []

    # GRID COMPLETION: a card whose light borders blend into a light
    # background (live catch: a pale tent-artwork JP card on a white desk,
    # 2026-07-18) breaks into non-card-shaped contour fragments and gets
    # filtered out — but when the OTHER cards form a clear row/column
    # lattice, the missing slot's position is fully determined by the grid
    # geometry. Synthesize a box for any empty lattice intersection instead
    # of silently dropping that card (a 12-card page must never come back
    # as 11). Single-card photos never form a >=2x2 lattice, so this can't
    # create false splits.
    def _cluster(vals, tol):
        groups = []
        for v in sorted(vals):
            if groups and v - groups[-1][-1] <= tol:
                groups[-1].append(v)
            else:
                groups.append([v])
        return [sum(g) / len(g) for g in groups]

    med_w = sorted(b[2] for b in kept)[len(kept) // 2]
    med_h = sorted(b[3] for b in kept)[len(kept) // 2]
    col_xs = _cluster([b[0] + b[2] / 2 for b in kept], med_w * 0.5)
    row_ys = _cluster([b[1] + b[3] / 2 for b in kept], med_h * 0.5)
    if len(col_xs) >= 2 and len(row_ys) >= 2 \
            and len(col_xs) * len(row_ys) > len(kept):
        for cy in row_ys:
            for cx in col_xs:
                occupied = any(abs(b[0] + b[2] / 2 - cx) <= med_w * 0.5
                               and abs(b[1] + b[3] / 2 - cy) <= med_h * 0.5
                               for b in kept)
                if not occupied:
                    x = int(max(0, cx - med_w / 2))
                    y = int(max(0, cy - med_h / 2))
                    kept.append((x, y, int(min(med_w, w - x)),
                                 int(min(med_h, h - y)), int(med_w * med_h),
                                 None))  # synthesized: no contour, no quad

    kept.sort(key=lambda b: (round(b[1] / (h * 0.15)), b[0]))  # reading order
    if with_quads:
        return [b[:4] for b in kept], [b[5] for b in kept]
    return [b[:4] for b in kept]


def probe_contours(path, tmpdir, ocr_reader=None, pad=0.06):
    """Like probe_grid(), but crops the ACTUAL detected card regions instead
    of a blind 2x2 quadrant split — for pages where cards aren't evenly
    gridded (mixed sizes/products). Requires evidence in a strong majority
    of cells before accepting the split, same philosophy as probe_grid().

    HASH-FIRST with perspective normalization (HASH-FIRST-NEXT.md,
    2026-07-19): each detected quad is perspective-warped to a flat
    canonical 630x880 card (the NolanAmblard scanner step) and looked up in
    the visual catalog BEFORE any OCR — variants tried per cell:
    warped -> warped rotated 180° (binder cards can be upside down; the
    warp itself can't know which way is up for sideways cards) -> the raw
    padded crop (preserves any hit the pre-warp code could produce). Only
    cells that miss all three pay the OCR cost. Match gates are unchanged
    (max_distance/nearest_slack) — a false identification is worse than a
    slow one."""
    boxes, quads = detect_card_regions(path, with_quads=True)
    if not boxes:
        return [], []
    reader = ocr_reader or valuator.ocr_lines
    from providers.visual_catalog import VisualCatalogProvider
    visual_catalog = VisualCatalogProvider()
    cv_img = cv2.imread(path)
    img = Image.open(path)
    w, h = img.size
    cells = []
    warp_variants = []   # per cell: list of (variant_name, path) to hash-try
    stem = os.path.splitext(os.path.basename(path))[0]
    for i, (x, y, cw, ch) in enumerate(boxes):
        quad = quads[i]
        if quad is None and cv_img is not None:
            # Synthesized lattice box (grid completion) — no contour to
            # warp, but a flat axis-aligned "warp" is still a clean crop at
            # canonical size, so the hash path gets a fair shot.
            quad = np.array([[x, y], [x + cw, y], [x + cw, y + ch],
                             [x, y + ch]], dtype=np.float32)
        variants = []
        if cv_img is not None and quad is not None:
            flat = warp_card(cv_img, quad)
            wp = os.path.join(tmpdir, f"{stem}_warp{i}.png")
            cv2.imwrite(wp, flat)
            variants.append(("warp", wp))
            wp180 = os.path.join(tmpdir, f"{stem}_warp{i}_r180.png")
            cv2.imwrite(wp180, cv2.rotate(flat, cv2.ROTATE_180))
            variants.append(("warp180", wp180))
        warp_variants.append(variants)
        px, py = cw * pad, ch * pad
        box = (int(max(0, x - px)), int(max(0, y - py)),
               int(min(w, x + cw + px)), int(min(h, y + ch + py)))
        out = os.path.join(tmpdir,
                           f"{os.path.splitext(os.path.basename(path))[0]}_box{i}.png")
        cell = img.crop(box)
        # split_grid()'s blind quadrant crop halves both dimensions, so its
        # unconditional 2x upscale just restores native resolution. A
        # detected card region is already near-native size (it IS one
        # card, not a quarter of the page) — blindly 2x-ing it on top made
        # OCR run on an image bigger than the whole original photo (~230s/
        # upload). But skipping upscale entirely lost a real identification
        # (Mr. Mime GX went from a confirmed number match to nothing) — small
        # printed text still benefits from some upsampling. Split the
        # difference: cap the target short side well under the original
        # photo's resolution instead of blindly doubling it.
        target = 900
        if min(cell.width, cell.height) < target:
            scale = target / max(1, min(cell.width, cell.height))
            cell = cell.resize((int(cell.width * scale), int(cell.height * scale)),
                               Image.LANCZOS)
        cell.save(out)
        cells.append(out)
    # Cells are independent — RapidOCR's onnxruntime inference releases the
    # GIL during its C++ compute, so threading gives real wall-clock
    # parallelism on this OCR-bound path instead of running 4 full OCR
    # passes back to back.
    hash_matches = []
    for i, cell in enumerate(cells):
        match = None
        for variant, vpath in warp_variants[i] + [("raw", cell)]:
            match = visual_catalog.match_image(vpath)
            if match is not None:
                match["matched_via"] = variant
                break
        hash_matches.append(match)
    ocr_indices = [i for i, match in enumerate(hash_matches) if match is None]
    ocr_groups = [None] * len(cells)
    from concurrent.futures import ThreadPoolExecutor
    if ocr_indices:
        with ThreadPoolExecutor(max_workers=min(4, len(ocr_indices))) as pool:
            ocr_results = list(pool.map(reader, [cells[i] for i in ocr_indices]))
        for i, lines in zip(ocr_indices, ocr_results):
            ocr_groups[i] = lines
    signals = 0
    for i, (match, lines) in enumerate(zip(hash_matches, ocr_groups)):
        if match is not None:
            signals += 1
            ocr_groups[i] = [match["name"], match["number"]]
            continue
        name, number = valuator.guess_query(lines)
        # detected-contour crops are tighter than blind grid quadrants, so a
        # card's name is often unreadable (glare/JP/holo) even though its
        # attack/ability text and damage numbers are perfectly legible —
        # check the same fingerprint layers identify() itself relies on
        # before writing off a cell as "no evidence".
        if (name or number or distinct_names(lines)
                or valuator.fingerprint_names(lines)
                or valuator.attack_id(lines)):
            signals += 1
    # STRICT MAJORITY, not a supermajority — a real card can still have a bad
    # OCR read (glare, tiny JP text on a dense grid), and requiring 75% was
    # too strict: a real 11-card page (dilation fix recovered 11 of 12 real
    # cards) had 7/11 cells with real, individually-plausible evidence
    # (matching collector fractions, a confirmed name+attack-fingerprint
    # hit) but got REJECTED by the old 9-of-11 bar, silently falling back to
    # the wrong blind 2x2 split. >50% is still a real safety margin — a
    # split that's mostly noise won't clear it.
    if signals >= max(2, len(cells) // 2 + 1):
        return cells, ocr_groups
    return [], []


def should_probe_grid(width, height, distinct_name_count, number_fractions=None):
    """Whether a portrait upload deserves a bounded 2x2 binder probe.

    A phone photo of a binder can be too low-resolution for whole-image OCR
    to read three names. The observed failure was 720x1280: four real cards,
    one bad footer read, and zero whole-image names. Ordinary single-card
    photos are materially wider, so the narrow portrait ratio keeps this
    fallback from quadrupling OCR work for every upload.
    """
    portrait_fallback = (height > width and width / max(height, 1) <= 0.68)
    if distinct_name_count < 3 and portrait_fallback:
        return True
    # A square/wide, high-resolution page with 3+ distinct fractions sharing
    # a denominator is a language-independent binder signal. The size guard
    # avoids treating a single landscape card's footer as a 2x2 page.
    fractions = number_fractions or set()
    totals = {}
    for _, total in fractions:
        totals[total] = totals.get(total, 0) + 1
    number_signal = max(totals.values(), default=0) >= 3
    return (distinct_name_count < 3 and number_signal
            and min(width, height) >= 900)


def probe_grid(path, tmpdir, ocr_reader=None):
    """Split/inspect a likely 2x2 page; require evidence in 3+ cells."""
    reader = ocr_reader or valuator.ocr_lines
    cells = split_grid(path, tmpdir, rows=2, cols=2)
    ocr_groups = [reader(cell) for cell in cells]
    signals = 0
    for lines in ocr_groups:
        name, number = valuator.guess_query(lines)
        if name or number or distinct_names(lines):
            signals += 1
    return (cells, ocr_groups) if signals >= 3 else ([], [])


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
