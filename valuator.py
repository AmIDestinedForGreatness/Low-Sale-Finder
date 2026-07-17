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

# Real promo series suffixes are a small, closed vocabulary.  OCR can turn
# DP-P into EP-P; correcting only an edit-distance-1 suffix keeps the query
# narrow while avoiding broad name-only fallback searches.
_PROMO_SERIES = frozenset({"DP-P", "HGSS-P", "BW-P", "XY-P", "SM-P",
                           "SWSH-P", "S-P", "SV-P", "SV-P"})


_RAPID = None


def _rapid():
    """RapidOCR (local onnx models) — reads the tiny footer text and the
    damage numbers that Windows OCR can't (proven on the 810px Reshiram
    photo: footer 'sm12a C 016/173 RR' readable only with this engine).
    Lazy singleton: model load costs ~8s once per process."""
    global _RAPID
    if _RAPID is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _RAPID = RapidOCR()
        except Exception:
            _RAPID = False
    return _RAPID


def ocr_lines(image_path):
    """OCR the photo: RapidOCR first, Windows OCR as fallback."""
    eng = _rapid()
    if eng:
        try:
            res, _ = eng(image_path)
            lines = [str(r[1]).strip() for r in (res or []) if str(r[1]).strip()]
            if lines:
                return lines
        except Exception:
            pass
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", os.path.join(_HERE, "ocr_card.ps1"), image_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60)  # utf-8: JP glyphs crashed the default cp1252 decode
        return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception:
        return []


def ocr_deep(image_path):
    """Second-pass OCR for hard photos (glare/holo/angle): zoomed region
    crops with contrast variants, merged with the full-frame read. Slower
    (~10s) — only runs when the first pass came back unusable."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return []
    try:
        im = Image.open(image_path).convert("RGB")
    except Exception:
        return []
    W, H = im.size
    regions = [(0, 0.10, 1.0, 0.45, 2),      # name + HP band
               (0, 0.40, 1.0, 0.80, 2),      # attacks / damage numbers
               (0, 0.70, 1.0, 1.00, 2),      # footer band
               (0, 0.75, 0.6, 1.00, 3),      # bottom-left set code, extra zoom
               # XY-era prints the number bottom-RIGHT; binder-cell crops
               # halve resolution — both sides get a high-zoom pass
               (0.4, 0.78, 1.0, 1.00, 4),
               (0.0, 0.82, 0.55, 1.00, 4)]
    lines, seen, tmp = [], set(), image_path + ".crop.png"
    for x1, y1, x2, y2, zoom in regions:
        crop = im.crop((int(x1 * W), int(y1 * H), int(x2 * W), int(y2 * H)))
        crop = crop.resize((crop.width * zoom, crop.height * zoom), Image.LANCZOS)
        g = ImageOps.autocontrast(ImageOps.grayscale(crop))
        for variant in (g, ImageOps.invert(g)):
            try:
                variant.save(tmp)
            except Exception:
                continue
            for ln in ocr_lines(tmp):
                key = ln.lower()
                if key not in seen:
                    seen.add(key)
                    lines.append(ln)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return lines


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
            mod = m.group(2) or ""
            # damage numbers are BIG standalone OCR regions ('230', '30+',
            # '…GX200+'); a bare number inside garbled text is body prose
            # ('…100ダメージ…', '130??') — phantoms broke Reshiram AND
            # Manectric fingerprints live. Standalone = PURELY number+mod.
            standalone = re.fullmatch(r"\d{2,3}[+x×]?", ln.strip()) is not None
            if not (mod or standalone):
                continue
            if 10 <= v <= 400 and v % 5 == 0 and v != hp:
                # NB: `mod in "x×"` is True for "" — must compare exactly
                dmgs.add(m.group(1) + ("x" if mod in ("x", "×") else mod))
    return dmgs, hp, tags


def fingerprint_names(lines, limit=5, ties=False):
    """OCR lines -> candidate card NAMES via the damage-profile index.
    ties=True: when the evidence is corroborated but the winner is TIED
    ({60,150}+HP180 fits Black Kyurem-EX, White Kyurem-EX, Charizard-EX
    AND Dialga-EX), return the tied set so the caller can break the tie
    with independent evidence (e.g. the collector number)."""
    dmgs, hp, tags = _extract_damages(lines)
    if len(dmgs) < 2 or not os.path.exists(FP_DB):
        return []
    conn = sqlite3.connect(FP_DB)

    def match(dmgs, hp):
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
        return best

    def guard(scored, used_dmgs, used_hp):
        """AMBIGUITY GUARD (live catch: {10,20} named a Chespin 'Arbok', a
        Pikachu promo 'Lucario'): tiny generic profiles match hundreds of
        cards. Claim a fingerprint only when the evidence is CORROBORATED
        (matched HP, or 3+ damages) and the winner is clear of rivals."""
        ranked = sorted(scored.items(), key=lambda kv: -kv[1])
        if not ranked:
            return []
        top = ranked[0][1]
        corroborated = ((used_hp and top >= len(used_dmgs) + 2)
                        or len(used_dmgs) >= 3)
        rivals = [n for n, s in ranked if s > top - 0.45]
        if not corroborated:
            return []
        if len(rivals) > 1:
            return rivals[:limit] if ties else []
        return [n for n, _ in ranked[:limit]]

    try:
        names = guard(match(dmgs, hp), dmgs, hp)
        if not names and not hp and len(dmgs) >= 2:
            # OCR often reads the HP number without its 'HP' label, which
            # poisons the profile with a phantom damage ('330' on a card
            # whose attacks are 120/200+). Retry treating each big plain
            # number as the HP instead.
            for d in sorted((x for x in dmgs if x.isdigit()),
                            key=int, reverse=True):
                if int(d) >= 120 and len(dmgs - {d}) >= 2:
                    names = guard(match(dmgs - {d}, int(d)), dmgs - {d}, int(d))
                    if names:
                        break
        return names
    finally:
        conn.close()


_ATK_IDX = None
_ATK_IDX_NS = None                        # no-space squashed keys


def _squash(s):
    return re.sub(r"[^a-z]", "", s.lower())


def _atk_index():
    """attack/ability name -> [(card, number)] from the local index."""
    global _ATK_IDX, _ATK_IDX_NS
    if _ATK_IDX is None:
        idx, idx_ns = {}, {}
        if os.path.exists(FP_DB):
            conn = sqlite3.connect(FP_DB)
            try:
                for a, kind, card, num, s in conn.execute("SELECT * FROM atk"):
                    idx.setdefault(a, []).append((card, num))
            except sqlite3.OperationalError:
                pass                      # index predates the atk table
            finally:
                conn.close()
            for a in idx:
                idx_ns.setdefault(_squash(a), []).append(a)
        _ATK_IDX, _ATK_IDX_NS = idx, idx_ns
    return _ATK_IDX


# OCR glues stacked/adjacent attack-name words with NO space ("Soprano
# Wave" -> "SopranoWave") — camelCase-shaped run of 2+ capitalized words
_GLUED_RUN = re.compile(r"[A-Z][a-z]{2,}(?:[A-Z][a-z]{2,}){1,3}")


def attack_id(lines):
    """LAYER E: attack/ability NAMES -> the card. They are the big readable
    English text OCR nails even on binder-cell crops, and near-unique per
    species ("Victory Ball" exists only on Victini). Multiple hits
    intersect; returns (card_name, [possible numbers]) or None."""
    idx = _atk_index()
    if not idx:
        return None
    matched = []
    for ln in lines:
        t = " ".join(re.sub(r"[^A-Za-z' -]", " ", ln.lower()).split())
        ent = None
        if len(t) >= 6 and " " in t:
            ent = idx.get(t)
            if not ent and len(t) >= 8:   # 1 OCR slip ("Soprane Wave")
                close = [k for k in idx
                         if abs(len(k) - len(t)) <= 1 and _lev(k, t) <= 1]
                if len(close) == 1:
                    ent = idx[close[0]]
        if not ent:
            # GLUED FORM: binder-cell OCR usually drops the space entirely
            # ("SopranoWave", "PrismaticWave", "MarineGuidance")
            for run in _GLUED_RUN.findall(ln):
                sq = _squash(run)
                if len(sq) < 8:
                    continue
                keys = _ATK_IDX_NS.get(sq)
                if not keys:
                    budget = 1 if len(sq) <= 11 else 2
                    close = [k for k, ks in _ATK_IDX_NS.items()
                             if abs(len(k) - len(sq)) <= budget
                             and _lev(k, sq) <= budget]
                    if len(close) == 1:
                        keys = _ATK_IDX_NS[close[0]]
                if keys and len(keys) == 1:
                    ent = idx[keys[0]]
                    break
        if ent:
            matched.append(ent)
    if not matched:
        return None
    names = set.intersection(*[{c for c, _ in ent} for ent in matched])
    if len(names) != 1:
        return None                       # ambiguous or noisy = no claim
    nm = names.pop()
    nums = set.intersection(*[{n for c, n in ent if c == nm}
                              for ent in matched]) - {""}
    return nm, sorted(nums)


def local_printings(name):
    """All real printings of a card name AND its mechanic variants, from
    the local index ('Scizor' -> Scizor, Scizor-EX, Scizor ex, M Scizor-EX
    -> {name: {numbers}}). TCGplayer text search often never surfaces promo
    and Full Art products — the local index is complete."""
    if not name or not os.path.exists(FP_DB):
        return {}
    conn = sqlite3.connect(FP_DB)
    try:
        rows = conn.execute(
            "SELECT DISTINCT name, number FROM fp WHERE name = ? "
            "OR name LIKE ? OR name LIKE ? OR name LIKE ?",
            (name, name + " %", name + "-%", "M " + name + "%")).fetchall()
        out = {}
        for n, num in rows:
            if num:
                out.setdefault(n, set()).add(num)
        return out
    finally:
        conn.close()


def crosscheck_name(lines, number):
    """TIE-BREAK: a corroborated-but-tied fingerprint ({60,150}+HP180 fits
    Black Kyurem-EX, White Kyurem-EX, Charizard-EX AND Dialga-EX) crossed
    with the collector number's own TCGplayer matches — exactly one card
    in both sets = identified with real evidence."""
    if not number:
        return None
    tie = fingerprint_names(lines, ties=True)
    if len(tie) <= 1:
        return None
    cands = search_candidates(str(number), prefer_jp=True)

    def _toks(s):
        return set(re.sub(r"[^a-z& ]", " ",
                          s.split(" - ")[0].lower().replace("-", " ")).split())
    hits = {t for t in tie if any(_toks(t) <= _toks(c["name"]) for c in cands)}
    return hits.pop() if len(hits) == 1 else None


# JP set codes are printed in LATIN on the card (sm12a, s4a, xy10…) and,
# with the collector number, uniquely identify the card on TCGplayer —
# the searchable ID for Japanese cards whose names our OCR can't read
_SET_RE = re.compile(r"\b(?:sm|sv|swsh|xy|bw|dp|pcg|cp|m)\d{1,2}[a-z]?\b", re.I)  # m1S = Mega era
# lines that are card MECHANIC labels, never a name ("TAG TEAM" -> "TEAM")
_MECH = re.compile(r"^(tag\s*)?(team|gx|ex|v(max|star)?|hp\s*\d*)$", re.I)


def _is_junk(text):
    """True when OCR produced gibberish, not a name ('li&DhJ', 'y- JV .M GX').
    A line counts as a name only if it has at least one PLAUSIBLE word:
    3+ letters, contains a vowel, no scrambled inner capitals (Mc names ok)."""
    for w in re.findall(r"[A-Za-z]+", text):
        # real words are proper-case or lowercase ('Reshiram', 'ex') — OCR
        # junk has impossible case shapes (DhJ, IBO, YEjj, COifi)
        shape_ok = (re.fullmatch(r"[A-Z]?[a-z]+", w)
                    or re.fullmatch(r"Mc[A-Z][a-z]+", w)
                    # Mega full-arts OCR as one glued token ('MCameruptEX',
                    # 'MBeedrillEX', 'MTyranitar') — M + name + mechanic
                    or re.fullmatch(r"M[A-Z][a-z]{3,}(?:EX|GX)?", w)
                    # ...and EX/GX/V-mechanics glue onto ANY name
                    # ('HydreigonEX', 'EeveeVax' = VMAX misread)
                    or re.fullmatch(r"[A-Z][a-z]{3,}(?:EX|GX|V[A-Za-z]{0,4})", w))
        plausible = (shape_ok and len(w) >= 3
                     and re.search(r"[aeiouyAEIOUY]", w)
                     and re.search(r"[^aeiouAEIOU]", w)      # 'ooo' is not a word
                     and len(set(w.lower())) >= 2)
        if plausible:
            return False
    return True


# mechanic suffix on a NAME ("Pikachu ex", glued OCR "arizardex") — stripped
# to reach the base name when matching against the vocabulary
_MECH_SUFFIX = re.compile(r"[\s-]*(?:tag team\s+)?(?:gx|ex|v|vmax|vstar|break)\.?$",
                          re.I)
_VOCAB = None


def _name_vocab():
    """lowercase name -> canonical, from the local all-cards index (4,428
    distinct real card names), plus mechanic-suffix-stripped base forms."""
    global _VOCAB
    if _VOCAB is None:
        vocab = {}
        if os.path.exists(FP_DB):
            conn = sqlite3.connect(FP_DB)
            names = [n for (n,) in conn.execute("SELECT DISTINCT name FROM fp")]
            conn.close()
            for n in names:
                vocab.setdefault(n.lower(), n)
            for n in names:                    # "Pikachu ex" -> "pikachu"
                base = _MECH_SUFFIX.sub("", n.lower()).strip()
                if base:
                    vocab.setdefault(base, n)
                # cards SAY "Mega", TCG data says "M ..." (same trap as the
                # Mega-promo pricing miss) — alias both forms
                if base.startswith("m "):
                    vocab.setdefault("mega " + base[2:], n)
        _VOCAB = vocab
    return _VOCAB


_VOCAB_NS = None


def _vocab_nospace():
    """separator-stripped vocab keys -> canonical (None when two different
    canonicals collide on the same squashed form)."""
    global _VOCAB_NS
    if _VOCAB_NS is None:
        ns = {}
        for k, canon in _name_vocab().items():
            sk = re.sub(r"[ .'&-]", "", k)
            if sk in ns and ns[sk] != canon:
                ns[sk] = None                      # ambiguous — never match
            else:
                ns.setdefault(sk, canon)
        _VOCAB_NS = ns
    return _VOCAB_NS


def snap_name(raw):
    """LAYER-C identification: a guessed NAME must be a real card name.
    Snaps OCR misreads to the unique nearest real name ('Pikachue' ->
    Pikachu, 'arizardex' -> Charizard) and REJECTS text that matches
    nothing — seller watermarks stamped on listing photos ('Yojins
    Pokestop') were passing the shape filter and becoming search queries.
    Returns the canonical name, or None when raw is not a card name."""
    if not raw:
        return None
    vocab = _name_vocab()
    if not vocab:
        return raw           # no index on disk -> can't validate, pass through
    q = " ".join(re.sub(r"[^a-z'&. -]", " ", raw.lower()).split())
    if q in vocab:
        return vocab[q]
    # spacing-insensitive exact match: glued 'MManectricEX' is EXACTLY
    # 'M Manectric-EX' minus separators — fuzzy matching saw a tie between
    # 'manectric' and 'm manectric' (both distance 1, both start 'm')
    ns = _vocab_nospace()
    hit = ns.get(re.sub(r"[ .'&-]", "", q))
    if hit:
        return hit
    stripped = _MECH_SUFFIX.sub("", q).strip()
    if stripped and stripped != q:
        # glued mechanic ('pikachuex') — prefer the FULL mechanic form
        # ('pikachu ex') over the bare base name
        suf = q[len(stripped):].strip(" -.")
        for k in (stripped + " " + suf, stripped + "-" + suf, stripped):
            if k in vocab:
                return vocab[k]
    variants = {q, stripped} - {""}
    best, best_d, ties = [], 99, 0
    for v in variants:
        # OCR on blurry/glare cells drops MULTIPLE letters from short names
        # ("Meaeta" for "Meloetta" — 2 letters lost, not 1); scale budget by
        # how much of the word survived rather than a flat length cutoff
        budget = 0 if len(v) <= 3 else max(1, min(3, (len(v) - 1) // 3))
        for k, canon in vocab.items():
            if not budget or abs(len(k) - len(v)) > budget:
                continue
            d = _lev(v, k)
            if d <= budget:
                if d < best_d:
                    best, best_d, ties = [(k, canon)], d, 1
                elif d == best_d and canon not in (c for _, c in best):
                    best.append((k, canon))
                    ties += 1
    if not best:
        return None
    if ties == 1:
        return best[0][1]
    # tie-break 1: OCR rarely loses the FIRST letter — 'mcamerupt' is 1 edit
    # from both 'camerupt' and 'm camerupt'; keep same-first-letter matches
    first = {c for k, c in best if k[:1] == q[:1]}
    if len(first) == 1:
        return first.pop()
    # tie-break 2: distance on separator-stripped forms — glue misreads
    # ('EeveeVax') sit closer to their true name once spacing is ignored
    strip = lambda s: re.sub(r"[ .'&-]", "", s)
    scored = sorted((_lev(strip(q), strip(k)), c) for k, c in best)
    if len(scored) > 1 and scored[0][0] < scored[1][0]:
        return scored[0][1]
    return None                                       # still ambiguous = no snap


# JP vintage cards (DP era, promos) print the National Dex number in the
# Pokédex data strip — "NO.398 ムクホーク" — a direct species ID when neither
# the (Japanese) name nor a set code is readable
# NB: no \b on either side — JP text around the token ("図鑑NO.0025走…")
# is word characters, which kills both boundaries; lookarounds instead
_DEX_RE = re.compile(r"(?<![A-Za-z0-9])NO\.?\s*(\d{1,4})(?!\d)", re.I)


def dex_names(lines):
    """LAYER-D identification: OCR lines -> species name via the National
    Dex number ('NO.398' -> Staraptor). Returns the plain species name(s)."""
    if not os.path.exists(FP_DB):
        return []
    dexes = {int(m.group(1)) for ln in lines for m in _DEX_RE.finditer(ln)
             if 1 <= int(m.group(1)) <= 1200}
    if not dexes:
        return []
    conn = sqlite3.connect(FP_DB)
    try:
        names = set()
        for d in dexes:
            rows = conn.execute("SELECT DISTINCT name FROM fp WHERE dex=?",
                                (d,)).fetchall()
            if rows:   # shortest form = the plain species name (not ex/GX)
                names.add(min((r[0] for r in rows), key=len))
        return sorted(names)
    finally:
        conn.close()


def guess_query(lines):
    """Best-guess card name + collector number from OCR lines.
    The name is printed big near the top; body text is filtered by _NOISE.
    Names are vocabulary-validated (Layer C) — unvalidatable reads are
    skipped so the setcode / fingerprint paths can take over."""
    number, setcode = None, None
    for ln in lines:
        if not number:  # prefer the slash form (016/173) over promo tokens
            # numerator may carry a variant letter: alternate-art "24a/119"
            m = re.search(r"\b\d{1,3}[a-z]?\s*/\s*\d{1,3}\b", ln, re.I)
            if m:
                number = m.group(0).replace(" ", "")
        if not setcode:
            m = _SET_RE.search(ln)
            if m:
                setcode = m.group(0).lower()
    if not number:
        # JP/KR PROMO footers use a LETTER denominator ("034/XY-P",
        # "197/SV-P", "065/PCG-P") — the digit-only patterns never saw them
        for ln in lines:
            m = re.search(r"(?<!\d)(\d{1,3})\s*/\s*([A-Za-z]{1,4}\s*-\s*[Pp])\b", ln)
            if m:
                number = m.group(1) + "/" + m.group(2).upper().replace(" ", "")
                break
    if not number:
        # GALLERY numbering letters BOTH sides ("TG26/TG30", "GG12/GG70").
        # Both sides share the same prefix — trim OCR glue ("WGG12/GG70")
        for ln in lines:
            m = re.search(r"\b([A-Za-z]{1,3})(\d{1,3})\s*/\s*([A-Za-z]{1,3})(\d{1,3})\b", ln)
            if m:
                p1, n1, p2, n2 = (m.group(1).upper(), m.group(2),
                                  m.group(3).upper(), m.group(4))
                if p1 != p2 and p1.endswith(p2):
                    p1 = p2
                if p1 == p2:
                    number = f"{p1}{n1}/{p2}{n2}"
                    break
    if not number:
        # relaxed pass: OCR glues rarity glyphs onto the number ('016/173RR'
        # read as '015/1738R') — printed totals are 2-3 digits, trim the rest
        for ln in lines:
            # no \b: OCR glues the footer into one token ('Sm120C015/1738R')
            m = re.search(r"(?<![\d/])(\d{1,3})\s*/\s*(\d{2,4})", ln)
            if m:
                number = m.group(1) + "/" + m.group(2)[:3]
                break
    if not number:
        for ln in lines:
            m = _NUM_RE.search(ln)
            if m:
                number = m.group(0).replace(" ", "")
                break
    name = ""
    for i, ln in enumerate(lines[:6]):        # name sits in the top lines
        if _SET_RE.search(ln) or re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", ln):
            continue  # footer line (set code / collector number), never the name
        if re.search(r"[A-Za-z]\d[A-Za-z]", ln):
            continue  # digits inside a word = OCR mash, never a name
        cand = re.sub(r"[^A-Za-z' .&-]", " ", ln)
        cand = " ".join(cand.split()).strip()
        if len(cand) < 3 or _NOISE.match(cand) or _MECH.match(cand) or _is_junk(cand):
            continue
        # TAG TEAM names span TWO stacked lines ("Naganadel&" / "Guzzlord")
        # — join with the next non-mechanic line before single-line matching
        if cand.endswith("&"):
            for j in (i + 1, i + 2):
                if j >= len(lines) or _MECH.match(lines[j].strip()):
                    continue
                nxt = " ".join(re.sub(r"[^A-Za-z' .&-]", " ", lines[j]).split())
                joined = snap_name((cand + " " + nxt).strip())
                if joined:
                    name = joined
                    break
            if name:
                break
        # LAYER C: must be (or snap to) a REAL card name — keep scanning
        # otherwise; the real name may sit below a watermark line
        cand = snap_name(cand)
        if cand:
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
                cand = snap_name(cand)
                if cand:
                    name = cand
                    break
    if not name and setcode:
        # Japanese card: no readable Latin name, but setcode+number IS the
        # unique ID (verified: "sm12a 016/173" -> exactly Reshiram&Charizard)
        name = setcode
    return name, number


def snap_promo_number(number):
    """Correct a one-edit OCR error in a known promo series suffix."""
    if not number:
        return number
    m = re.fullmatch(r"(\d{1,3})/([A-Za-z]{1,4}-P)", number.strip(), re.I)
    if not m:
        return number
    raw = m.group(2).upper()
    if raw in _PROMO_SERIES:
        return f"{m.group(1)}/{raw}"
    close = [series for series in _PROMO_SERIES if _lev(raw, series) == 1]
    return f"{m.group(1)}/{close[0]}" if len(close) == 1 else number


def _norm_num(n):
    """'016/173' -> '16/173' (leading zeros differ between printings/OCR)."""
    parts = (n or "").lower().replace(" ", "").split("/")
    return "/".join(p.lstrip("0") or "0" for p in parts)


def _lev(a, b):
    """Levenshtein distance (tiny strings only)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def snap_number(number, valid_numbers):
    """LAYER-B identification: the number must be a real printing of the
    identified card. If the OCR'd number isn't, but exactly ONE valid
    printing is a single edit away (016/173 read as 015/173 at low res),
    snap to it. Returns the corrected number or None."""
    if not number:
        return None
    want = _norm_num(number)
    valid = {_norm_num(v): v for v in valid_numbers if v}
    if want in valid:
        return valid[want]               # already valid (canonical form)
    close = {v for k, v in valid.items() if _lev(want, k) == 1}
    return close.pop() if len(close) == 1 else None


def search_candidates(query, size=12, prefer_jp=False):
    """TCGplayer candidates for the picker grid (image = user's eyes).
    TCGplayer's search returns nothing when the collector number is in the
    query text — so search by NAME only, then rank number-matches first."""
    query = re.sub(
        r"(?<!\d)(\d{1,3})\s*/\s*([A-Za-z]{1,4}-P)\b",
        lambda m: snap_promo_number(f"{m.group(1)}/{m.group(2)}"), query,
        flags=re.I)
    m = (re.search(r"\b\d{1,3}[a-z]?\s*/\s*\d{1,3}\b", query, re.I)
         or re.search(r"\b\d{1,3}\s*/\s*[A-Za-z]{1,4}-P\b", query, re.I)
         or _NUM_RE.search(query))
    number = (m.group(0).replace(" ", "") if m else "").lower()
    if _SET_RE.search(query) and number and "/" in number:
        # JP set-code query: TCGplayer resolves "sm12a 016/173" directly —
        # send it whole, don't strip the number. Slash REQUIRED: a promo
        # token like "XY79" also matches the setcode shape, and sending
        # "Snorlax XY79" whole → zero hits → retry dropped "Snorlax" and
        # returned a LATIOS (the real XY79; his card was XY179 misread)
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
    # boxes/collections/merch have no collector number — they are not cards
    # and never belong in an identification grid (Yujin: "remove completely")
    out = [c for c in out if c["number"]]

    want = _norm_num(number) if number else None
    out = _close_only(out, want, query)

    def rank(c):
        # nearest-to-farthest by number distance (his ordering spec)
        dist = _lev(want, _norm_num(c["number"])) if want else 0
        # 'line' is the DISPLAY name ('Pokemon Japan'), not the slug
        is_jp = ("japan" in (c["line"] or "").lower()
                 or "japan" in c["set"].lower())
        return (dist, (0 if is_jp else 1) if prefer_jp else 0)

    out.sort(key=rank)
    return out


def _close_only(cands, want, query=""):
    """When the printing number is known, show ONLY close/identical
    printings (Yujin: 'remove unnecessary searches') — a Jumbo promo and a
    far-numbered variant are noise once the number is pinned. Falls back to
    the full list rather than showing nothing."""
    if "jumbo" not in (query or "").lower():
        non_j = [c for c in cands if "jumbo" not in c["set"].lower()]
        if non_j:
            cands = non_j
    if not want:
        return cands
    for maxd in (1, 2):
        close = [c for c in cands if _lev(want, _norm_num(c["number"])) <= maxd]
        if close:
            return close
    return cands


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

    # volatility: how much real sold prices actually swing, not a guess —
    # coefficient of variation (stdev/mean) over the same real USD sales
    # already captured above. Niche/new cards with few or wildly-spread
    # sales should read as volatile; a thick, tight sales history reads
    # stable. Needs >=2 priced sales to say anything at all.
    priced = [float(s["purchasePrice"]) for s in sales if s.get("purchasePrice")]
    if len(priced) >= 2 and statistics.mean(priced) > 0:
        cv = statistics.stdev(priced) / statistics.mean(priced)
        if cv < 0.15:
            vol_label, vol_note = "Stable", "recent sales cluster tightly"
        elif cv < 0.35:
            vol_label, vol_note = "Moderate", "some real spread in recent sales"
        else:
            vol_label, vol_note = "Volatile", "recent sales swing widely — niche/new-set risk"
        out["volatility"] = {"label": vol_label, "cv": round(cv, 3), "note": vol_note}
    else:
        out["volatility"] = {"label": "Unknown", "cv": None,
                             "note": "not enough real sales yet to judge"}

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
