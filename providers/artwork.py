"""Zero-cost, local-only perceptual-hash artwork evidence provider."""
from functools import lru_cache
import json
import os

from .base import EvidenceProvider


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_DIR = os.path.join(HERE, "dataset")


def _norm_name(value):
    return " ".join(str(value or "").split(" - ", 1)[0].lower().replace("-", " ").split())


def _norm_number(value):
    try:
        from collision import norm_number
        return norm_number(value)
    except Exception:
        return str(value or "").lower().replace(" ", "").lstrip("0")


def _ident_key(ident):
    return _norm_name(ident.get("name")), _norm_number(ident.get("number"))


@lru_cache(maxsize=1)
def _scan_dataset_refs():
    """One disk walk shared by both callers below: (key, raw_name, raw_number,
    image) for every dataset row with a real identity and a real photo."""
    rows = []
    for filename in ("carousell_profile.json", "for_u_to_do_while_im_asleep.json",
                     "confirmed_by_user.json"):
        path = os.path.join(DATASET_DIR, filename)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        if isinstance(data, list):
            for row in data:
                ident = row.get("ident") or {}
                key = _ident_key(ident)
                for image in row.get("images") or []:
                    if all(key) and os.path.exists(image):
                        rows.append((key, ident.get("name"), ident.get("number"), image))
        elif isinstance(data, dict):
            # The folder dataset's keys are the real filenames.  They live in
            # Downloads; no reference image is downloaded or scraped here.
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            dataset_folder = os.path.join(
                downloads, os.path.splitext(filename)[0].replace("_", " "))
            for filename_key, row in data.items():
                basename = row.get("file") or filename_key
                image = next((path for path in (
                    os.path.join(dataset_folder, basename),
                    os.path.join(downloads, basename)) if os.path.exists(path)), "")
                if not os.path.exists(image):
                    continue
                for ident in row.get("cards") or []:
                    key = _ident_key(ident)
                    if all(key):
                        rows.append((key, ident.get("name"), ident.get("number"), image))
    return rows


@lru_cache(maxsize=1)
def _dataset_references():
    """Map known, already-local dataset identifications to their photos."""
    refs = {}
    for key, _name, _number, image in _scan_dataset_refs():
        refs.setdefault(key, []).append(image)
    return refs


def _art_region(image):
    """Conservative inner-art crop for an already card-shaped reference."""
    from PIL import ImageOps
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    # On a canonical card this isolates the illustration. On a scene photo it
    # remains deliberately weak; a no-match is evidence of provider limits,
    # not evidence that the selected identity is false.
    if height >= width:
        return image.crop((int(width * .08), int(height * .16),
                           int(width * .92), int(height * .57)))
    return image


@lru_cache(maxsize=1024)
def _file_hashes(path, mtime_ns, size):
    import imagehash
    from PIL import Image
    with Image.open(path) as image:
        artwork = _art_region(image)
        return imagehash.phash(artwork), imagehash.dhash(artwork)


def _hash_similarity(left, right):
    left_stat, right_stat = os.stat(left), os.stat(right)
    ap, ad = _file_hashes(left, left_stat.st_mtime_ns, left_stat.st_size)
    bp, bd = _file_hashes(right, right_stat.st_mtime_ns, right_stat.st_size)
    bits = ap.hash.size
    phash_score = 1.0 - ((ap - bp) / bits)
    dhash_score = 1.0 - ((ad - bd) / bits)
    return max(0.0, min(1.0, .7 * phash_score + .3 * dhash_score))


def discover_from_confirmed(image_path, threshold=0.90):
    """DISCOVERY (not verification): find the nearest confirmed reference by
    artwork alone, with no name/number candidate required to key against.

    ArtworkProvider.verify() only re-checks candidates identify() already
    proposed by OCR text — useless for a card whose printed name never
    survives OCR (unreadable JP script) and whose bare collector number
    returns nothing from TCGplayer's name-only search (the exact "(unread)"
    binder-pocket case, live catch 2026-07-19: Yujin confirmed a Misdreavus
    cell by hand, but re-scanning the same photo still showed it unnamed,
    because nothing had ever pointed the artwork check at that reference).
    A HIGHER threshold than verify()'s 0.86 is used here on purpose: this
    result gets ADOPTED as the name, not just used to nudge confidence.
    """
    if not image_path or not os.path.exists(image_path):
        return None
    best = None
    # NOTE: deliberately no self-path skip. Re-uploads reuse a content-hash
    # filename, so the identical, previously-confirmed file is the common
    # real case (rescanning the same binder photo) — a same-file match is
    # ground truth, not a false positive, and must resolve just like any
    # other reference would.
    for _key, raw_name, raw_number, ref in _scan_dataset_refs():
        try:
            score = _hash_similarity(image_path, ref)
        except Exception:
            continue
        if best is None or score > best[0]:
            best = (score, raw_name, raw_number, ref)
    if best is None or best[0] < threshold:
        return None
    score, name, number, ref = best
    return {"name": name, "number": number, "score": round(score, 4),
            "matched_reference": ref}


class ArtworkProvider(EvidenceProvider):
    dimension = "artwork"

    def __init__(self, match_threshold=.86):
        self.match_threshold = float(match_threshold)

    def _references(self, candidates, context):
        refs = []
        explicit = (context or {}).get("reference_images") or []
        for item in explicit:
            if isinstance(item, str):
                refs.append((item, None))
            elif isinstance(item, dict):
                refs.append((item.get("path"), item.get("candidate")))
        known = _dataset_references()
        for candidate in candidates or []:
            key = _ident_key(candidate)
            for path in known.get(key, []):
                refs.append((path, candidate))
            for path in candidate.get("reference_images") or []:
                refs.append((path, candidate))
            if candidate.get("reference_image"):
                refs.append((candidate["reference_image"], candidate))
        unique = []
        seen = set()
        for path, candidate in refs:
            if not path:
                continue
            norm = os.path.normcase(os.path.abspath(path))
            if norm not in seen:
                seen.add(norm)
                unique.append((path, candidate))
        return unique[:8]   # bounded cheap provider, not an exhaustive visual DB

    def verify(self, image_path, candidates, context):
        result = {"provider": "ArtworkProvider:perceptual_hash",
                  "dimension": self.dimension, "match_score": 0.0,
                  "matched_reference": None, "confidence_note": "",
                  "status": "not_verified"}
        if not image_path or not os.path.exists(image_path):
            result["confidence_note"] = "input image is unavailable; artwork was not checked"
            return result
        input_norm = os.path.normcase(os.path.abspath(image_path))
        references = [(p, c) for p, c in self._references(candidates, context)
                      if os.path.exists(p)
                      and os.path.normcase(os.path.abspath(p)) != input_norm]
        if not references:
            result["confidence_note"] = (
                "no independent local reference image exists for any candidate; no match was guessed")
            return result
        best = None
        for path, candidate in references:
            try:
                score = _hash_similarity(image_path, path)
            except Exception:
                continue
            if best is None or score > best[0]:
                best = (score, path, candidate)
        if best is None:
            result["confidence_note"] = "local references could not be decoded; artwork was not verified"
            return result
        score, path, candidate = best
        result.update({"match_score": round(score, 4),
                       "matched_reference": path,
                       "matched_candidate": candidate})
        if score >= self.match_threshold:
            result["status"] = "matched"
            result["confidence_note"] = (
                f"local perceptual hashes matched at {score:.1%}; this adds coverage only, "
                "not calibrated prediction confidence")
        else:
            result["status"] = "no_match"
            result["confidence_note"] = (
                f"best local perceptual-hash similarity was {score:.1%}, below the "
                f"{self.match_threshold:.0%} threshold; provider limitations may explain this")
        return result
