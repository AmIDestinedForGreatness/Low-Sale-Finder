"""
profile_dataset.py — dataset builder: identify every card in a Carousell
seller's profile IMAGE-FIRST, using the same identification stack as the
dashboard Card Valuator (/api/valuator/ocr), then verify against the
listing title only afterwards.

Purpose (Yujin, 7/16): train/evaluate the system's VISUAL recognition —
minimize dependence on titles/descriptions. Every listing's images +
image-only identification + metadata verification go into
dataset/<profile>.json, which becomes ground-truth training data.

Usage:
    python profile_dataset.py https://www.carousell.ph/u/yujins-pokestop/
    python profile_dataset.py --identify-only    (skip scrape, reuse dataset)
"""
import json
import os
import re
import sys
import time
import urllib.parse

import network_safety

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
IMG_DIR = os.path.join(DATASET_DIR, "images")


# ── phase 1: scrape the profile ────────────────────────────────────────
def scrape_profile(url):
    """All listings on a seller profile: url, title, price_text, status."""
    url = network_safety.validate_marketplace_url(url)
    from playwright.sync_api import sync_playwright
    listings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  locale="en-US", service_workers="block")
        page = ctx.new_page()
        page.route("**/*", lambda route: network_safety.guard_marketplace_navigation(
            route, page.main_frame))
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        network_safety.validate_marketplace_url(page.url)
        page.wait_for_timeout(4000)
        for _ in range(6):                    # profiles paginate on scroll
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1200)
        js = r"""
        () => {
          const out = []; const seen = new Set();
          for (const a of document.querySelectorAll('a[href*="/p/"]')) {
            const href = (a.getAttribute('href')||'').split('?')[0];
            if (!href.includes('/p/') || seen.has(href)) continue;
            seen.add(href);
            let card = a;
            while (card.parentElement &&
                   card.parentElement.querySelectorAll('a[href*="/p/"]').length === 1)
              card = card.parentElement;
            const text = (card.innerText||'').trim();
            const priceMatch = text.match(/(?:[$₱]|PHP)\s?[\d.,]+/i);
            const statusMatch = text.match(/\b(reserved|sold)\b/i);
            out.push({
              url: href.startsWith('http') ? href : 'https://www.carousell.ph' + href,
              title: (a.innerText||'').trim().split('\n')[0].slice(0,200),
              price_text: priceMatch ? priceMatch[0] : '',
              status: statusMatch ? statusMatch[0].toLowerCase() : '',
              raw: text.slice(0,300),
            });
          }
          return out;
        }"""
        listings = page.evaluate(js)
        browser.close()
    return listings


def scrape_listing_page(url):
    """Open one product page: full title, description, ALL product images."""
    url = network_safety.validate_marketplace_url(url)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  locale="en-US", service_workers="block")
        page = ctx.new_page()
        page.route("**/*", lambda route: network_safety.guard_marketplace_navigation(
            route, page.main_frame))
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        network_safety.validate_marketplace_url(page.url)
        page.wait_for_timeout(3500)
        js = r"""
        () => {
          const imgs = new Set();
          for (const im of document.querySelectorAll('img')) {
            const srcset = (im.getAttribute('srcset')||'').split(/[\s,]+/)
                             .filter(s=>s.startsWith('http'));
            const src = srcset.length ? srcset[srcset.length-2]||srcset[0]
                                      : (im.currentSrc || im.src || '');
            if (src.includes('/photos/products/')) imgs.add(src);
          }
          const og = document.querySelector('meta[property="og:image"]');
          if (og && og.content) imgs.add(og.content);
          const title = (document.querySelector('h1')||{}).innerText || '';
          // description: the longest <p>/<div> text block on the page
          let desc = '';
          for (const el of document.querySelectorAll('p'))
            if ((el.innerText||'').length > desc.length) desc = el.innerText;
          return {title: title.trim(), desc: desc.trim().slice(0,1500),
                  images: Array.from(imgs)};
        }"""
        data = page.evaluate(js)
        browser.close()
    return data


def _fullsize(u):
    """Carousell serves thumbnails via a resize proxy — request the biggest
    rendition we can. media.karousell.com progressive URLs accept no params;
    the cdn 'fit-in' style embeds size in the path."""
    u = re.sub(r"\?.*$", "", u)
    u = re.sub(r"/fit-in/\d+x\d+/", "/fit-in/1080x1440/", u)
    return u


def download_images(listing_idx, urls, prefix=""):
    os.makedirs(IMG_DIR, exist_ok=True)
    paths = []
    seen_size = set()
    for n, u in enumerate(urls[:6]):
        try:
            r = network_safety.fetch_public_bytes(
                _fullsize(u), headers={"User-Agent": UA}, timeout=30)
            if r.status_code != 200 or len(r.content) < 4000:
                continue
            if len(r.content) in seen_size:      # og:image dup of gallery img
                continue
            seen_size.add(len(r.content))
            ext = ".png" if r.content[:4] == b"\x89PNG" else ".jpg"
            path = os.path.join(IMG_DIR, f"{prefix}L{listing_idx:02d}_{n}{ext}")
            with open(path, "wb") as f:
                f.write(r.content)
            paths.append(path)
        except Exception as e:
            print(f"    [img {n} failed] {e}")
    return paths


# ── phase 2: image-first identification (the dashboard's exact stack) ──
# words printed on essentially EVERY Pokémon card — high document-frequency
# for card reasons, so they can never be watermark evidence (and dropping
# their lines would kill real names like "Weakness Policy")
_CARD_TERMS = {
    "weakness", "resistance", "retreat", "ability", "abilities", "pokemon",
    "energy", "trainer", "item", "supporter", "stage", "basic", "evolves",
    "evolve", "evolution", "attack", "attacks", "damage", "this", "that",
    "when", "your", "from", "with", "illus", "llus", "card", "cards", "more",
    "each", "coin", "flip", "heads", "tails", "turn", "opponent", "prize",
    "bench", "benched", "active", "discard", "attached", "attach", "team",
}


def batch_watermarks(per_listing_lines):
    """Seller-overlay text is stamped on photos of MANY DIFFERENT cards;
    real card text is not. Letter tokens (4+) present in >=40% of the
    listings — minus universal card terms — are watermark vocabulary.
    (First attempt counted repeats WITHIN one listing's photos — wrong:
    6 photos of the same card repeat the card's own text; the overlay OCRs
    differently each time — Yujin's/Yojin's/Yojins — and escaped. Across
    listings it can't hide.)"""
    from collections import Counter
    df = Counter()
    for lines in per_listing_lines:
        toks = set()
        for ln in lines:
            toks |= {t.lower() for t in re.findall(r"[A-Za-z]{4,}", ln)}
        df.update(toks)
    n = len(per_listing_lines)
    if n < 5:
        return set()                # too few listings to tell overlay apart
    return {t for t, c in df.items()
            if c >= max(3, int(n * 0.4)) and t not in _CARD_TERMS}


def _is_wm_token(t, wm):
    """The overlay OCRs differently every photo (Pokestop/Pkestop/Poketop/
    Phestop, Yojins/Yoins, glued 'YujinPokesiop') — exact matching missed
    most of them. Fuzzy + substring against the watermark vocabulary."""
    import valuator
    if t in wm:
        return True
    for w in wm:
        if len(w) >= 5 and w in t:                    # glued: yujinpokestop
            return True
        big = max(len(t), len(w))
        if abs(len(t) - len(w)) <= 2 and big >= 6:
            if valuator._lev(t, w) <= (2 if big >= 8 else 1):
                return True
    return False


def _strip_wm(lines, wm):
    """Drop lines carrying a watermark token ('Pokestop' even snaps to a
    REAL card — PokéStop, Pokémon GO set — so these must never reach the
    name guesser). Numbers are never watermark tokens, footers survive."""
    out = []
    for ln in lines:
        toks = {t.lower() for t in re.findall(r"[A-Za-z]{4,}", ln)}
        # the overlay also splits ('Poke stop') or glues ('YujinsPokestop')
        # — check the line's letters joined as one token too
        joined = "".join(re.findall(r"[A-Za-z]+", ln)).lower()
        if len(joined) >= 4:
            toks.add(joined)
        if any(_is_wm_token(t, wm) for t in toks):
            continue
        out.append(ln)
    return out


def adopt_attack_number(cand_nums):
    """L32: a number that was never READ may only be adopted from Layer E
    when the species has exactly one candidate printing. Any 'preference'
    among several real printings is a prior, not evidence (the old
    promo-format preference picked SM38 over an actual 27/149 and TG16
    over an actual 068/172 — both eye-adjudicated wrong)."""
    if len(cand_nums) == 1:
        return cand_nums[0]
    return None


def resolve_catalog_identity(name, number, via, candidates, graded=False):
    """Apply the shared safe name upgrade from already-fetched candidates.

    This is intentionally narrow: searching, local-index joins, snapping, and
    evidence remain with their callers. The dashboard and dataset must agree
    when a number has one exact product or several exact products with one
    normalized card name.
    """
    import valuator
    exact = [candidate for candidate in candidates
             if (number and valuator._norm_num(str(candidate.get("number") or ""))
                 == valuator._norm_num(str(number)))]
    if (not graded and (not name or valuator._SET_RE.fullmatch(str(name)))
            and number and len(candidates) == 1 and len(exact) == 1):
        return candidates[0]["name"].split(" - ")[0], via or "unique number match"
    if not graded and not name and number and len(candidates) >= 2:
        bases = {re.sub(r"\s*\(.*\)$", "", candidate["name"].split(" - ")[0]).strip()
                 for candidate in exact}
        if len(bases) == 1:
            return bases.pop(), via or "candidate consensus"
    return name, via


def presented_identity_name(name, via):
    """A set code may guide search but must never be presented as a name."""
    import valuator
    if name and not via and valuator._SET_RE.fullmatch(str(name)):
        return None
    return name


def identify(image_paths, ocr_raw, wm):
    """Run the valuator identification stack over a listing's images.
    Mirrors /api/valuator/ocr, but uses EVERY photo (front, back, closeup)
    and merges evidence across them. Returns a full evidence dict."""
    import valuator
    per_lines = [_strip_wm(lines, wm) for lines in ocr_raw]
    per_img = [{"img": os.path.basename(p), "lines": raw[:14]}
               for p, raw in zip(image_paths, ocr_raw)]
    dropped = sorted({ln for raw, flt in zip(ocr_raw, per_lines)
                      for ln in raw if ln not in flt})
    def _strong(n):
        """A name specific enough to trust for Layer-B number snapping:
        full mechanic form or multi-word. Base-only reads are NOT ('Pikachu'
        snapped a correct 063/193 BACKWARD to plain-Pikachu 062/193 when
        the card was Pikachu ex)."""
        return bool(re.search(r"(?i)[\s-](ex|gx|v|vmax|vstar)$", n)
                    or " " in n.strip())

    # evidence per photo, then VOTE — the same footer is read 4-6 times
    names, numbers = [], []
    for lines in per_lines:
        n2, num2 = valuator.guess_query(lines)
        if n2:
            names.append(n2)
        if num2:
            numbers.append(num2)
    name = via = None
    real = [n for n in names if not valuator._SET_RE.fullmatch(n)]
    if real:
        # FREQUENCY first — sellers append the same promo/trailer photo to
        # every listing ("Mimikyu ex" named 3 different cards because the
        # vote preferred the LONGER name over the name read on MORE photos)
        # — then specificity ("Pikachu ex" > "Pikachu"), then length
        name = sorted(real, key=lambda n: (real.count(n), _strong(n), len(n)))[-1]
    elif names:
        name = names[0]                          # JP setcode-as-name path
    name_read = name                             # preserve independent OCR evidence
    number = None
    if numbers:
        from collections import Counter
        best_norm = Counter(valuator._norm_num(x) for x in numbers).most_common(1)[0][0]
        number = next(x for x in numbers if valuator._norm_num(x) == best_norm)
    merged = []
    for lines in per_lines:
        merged += [ln for ln in lines if ln not in merged]
    if not name:
        # merged first (all evidence), then photo-by-photo — one bad
        # photo's phantom numbers must not sink a clean front photo
        for cand_lines in [merged] + per_lines:
            fp = valuator.fingerprint_names(cand_lines)
            if fp:
                name, via = fp[0], "attack fingerprint"
                break
    if not name:
        # LAYER D: JP vintage prints the National Dex number ("NO.398")
        dx = valuator.dex_names(merged)
        if len(dx) == 1:
            name, via = dx[0], "dex number"
    # LAYER E: attack/ability names — determines binder-cell cards whose
    # footers are below OCR resolution, and can pin the exact printing
    aid = valuator.attack_id(merged)
    if aid:
        if not name:
            name, via = aid[0], "attack names"
        if not number and str(name).lower() in aid[0].lower():
            adopted = adopt_attack_number(aid[1])   # L32: single printing only
            if adopted:
                number = adopted
                via = via or "attack names"
    if not name:
        # LAYER F: nearest-neighbor match against every photo Yujin has
        # already manually confirmed (dataset/confirmed_by_user.json).
        # ArtworkProvider.verify() (in evidence.py) only re-checks a
        # candidate identify() already proposed by OCR text — no use for a
        # card whose printed name never survives OCR (unreadable JP script)
        # and whose bare collector number returns nothing from TCGplayer's
        # name-only search (live catch 2026-07-19: a JP binder page's cells
        # showed a number but stayed "(unread)" forever, even after Yujin
        # hand-confirmed one of those exact cells, because nothing had ever
        # pointed an artwork check at that reference). This is DISCOVERY —
        # it runs on the raw image with no candidate list required.
        from providers.artwork import discover_from_confirmed
        for p in image_paths:
            disc = discover_from_confirmed(p)
            if disc:
                name = str(disc["name"] or "").split(" - ")[0].strip()
                via = "confirmed reference match"
                if not number:
                    number = disc.get("number")
                break
    if not name:
        # LAYER G: candidate-free discovery against the full local visual
        # catalog. VisualCatalogProvider.verify() only corroborates an
        # identity text/OCR already proposed; match_image() uses the same
        # conservative absolute-distance + nearest-neighbor-lead gates as
        # the hash-first contour path, and returns None for catalog gaps.
        # Keep the provider defaults unchanged: an M2a/M-era card missing
        # from fingerprints.sqlite must stay unread, never be force-matched
        # to the merely-nearest indexed artwork.
        from providers.visual_catalog import VisualCatalogProvider
        visual_catalog = VisualCatalogProvider()
        for p in image_paths:
            disc = visual_catalog.match_image(p)
            if disc:
                name = str(disc["name"] or "").split(" - ")[0].strip()
                via = "visual catalog match"
                if not number:
                    number = disc.get("number")
                break
    if not name and number:
        # TIE-BREAK: tied fingerprint × the number's own catalog matches
        cross = valuator.crosscheck_name(merged, number)
        if cross:
            name, via = cross, "fingerprint × number"
    if (not name or not number):
        for p in image_paths:                    # deep-zoom scan, per photo
            deep = _strip_wm(valuator.ocr_deep(p), wm)
            if not deep:
                continue
            n2, num2 = valuator.guess_query(merged + deep)
            name, number = name or n2, number or num2
            if not name:
                fp = valuator.fingerprint_names(merged + deep)
                if fp:
                    name, via = fp[0], "attack fingerprint"
            if not name:
                dx = valuator.dex_names(merged + deep)
                if len(dx) == 1:
                    name, via = dx[0], "dex number"
            if name and number:
                break
    all_lines = merged
    # LANGUAGE is a claim — only POSITIVE evidence sets it: a JP set code,
    # a JP promo footer (…/XY-P), or the paths that only fire when the name
    # isn't Latin-readable. "identified via unique number match" says
    # nothing about language (it mislabeled 4 English cards Japanese).
    jp = (bool(name and valuator._SET_RE.fullmatch(str(name or "")))
          or bool(re.search(r"[A-Za-z]-P$", str(number or "")))
          or via in ("attack fingerprint", "dex number", "fingerprint × number"))
    # …but for SEARCH RANKING an unreadable name is still a useful JP hint
    prefer_jp = jp or bool(number and not name)
    number_read, snapped = number, False
    cands = []
    query = (str(name or "") + " " + str(number or "")).strip()
    if query:
        cands = valuator.search_candidates(query, prefer_jp=prefer_jp)
        if not cands and name:                   # number may be misread
            cands = valuator.search_candidates(str(name), prefer_jp=prefer_jp)
        # AMBIGUOUS PROMO NUMBERS: Layer E narrowed to a name but couldn't
        # pick ONE number (e.g. Victini's XY117 vs XY189, both promo-format).
        # ROOT CAUSE (confirmed against the raw API): appending a promo
        # token to the query does nothing — search_candidates() strips any
        # slash-less number-shaped token via _NUM_RE before it ever reaches
        # TCGplayer, so "Victini XY117" silently becomes a bare "Victini"
        # search. And TCGplayer's OWN relevance ranking buries promos deep:
        # Victini's XY117 card is real and present, but only surfaces
        # around position ~40 of its own results — invisible at the
        # default size=12 (confirmed: absent at 12 and 30, present at 50).
        # Fix: search deep (size=50) directly by name and pull out an
        # EXACT number match — this is a targeted lookup for a known
        # number, not a relevance-ranked discovery search, so depth is safe.
        if aid and not number and len(aid[1]) > 1 and name:
            # collect first, merge once — prepending inside the loop pushed
            # an EARLIER ambiguous candidate out of the eventual top-5 slice
            # when a LATER one got inserted in front of it (live catch:
            # fixing Meloetta's XY193 pushed her own XY120 out of view)
            by_num = {valuator._norm_num(c["number"]): c for c in cands}
            deep = valuator.search_candidates(str(name), size=50,
                                              prefer_jp=prefer_jp)
            found = []
            for cand_num in aid[1]:
                key = valuator._norm_num(cand_num)
                if key in by_num:
                    found.append(by_num[key])
                    continue
                hit = next((c for c in deep
                           if valuator._norm_num(c["number"]) == key), None)
                if hit:
                    found.append(hit)
                    by_num[key] = hit
            if found:
                keys = {valuator._norm_num(c["number"]) for c in found}
                cands = found + [c for c in cands
                                 if valuator._norm_num(c["number"]) not in keys]
        # GRADED SLABS: label numbers are region-ambiguous (a Beckett'd
        # CHINESE Pikachu promo #004/SV-P unique-matched the JAPANESE SV-P
        # 004 — Dondozo). Never adopt a name from a bare number on a slab.
        # NB: no trailing \b — grades glue on ("PSA10")
        graded = any(re.search(r"\b(psa|bgs|cgc|beckett|black label|"
                               r"gem ?mint|pristine)", ln, re.I)
                     for ln in merged)
        # promo/JP numbers are near-unique: exactly ONE catalog product with
        # the read number = the card ("197/SV-P" -> Pikachu). Also upgrades
        # a setcode-only name ("sm3" -> Raichu GX). Still eye-gated.
        # CROSS-REGION COLLISION (live catch, 2026-07-18): full collector
        # fractions are NOT globally unique either — "224/193" is Orthworm
        # in EN Paldea Evolved AND Mega Froslass ex in the JP M2a set. The
        # len(cands)==1 requirement is what keeps this gate safe; never
        # relax it to "all candidates share a number".
        name, via = resolve_catalog_identity(
            name, number, via, cands, graded=graded)
        # CANDIDATE CONSENSUS: several products share the read number but
        # they are all the SAME card (Alolan Ninetales GX 22/145 appeared
        # twice; the system claimed nothing). One name in all candidates =
        # the name is determined even without a readable title.
        # LOCAL-INDEX JOIN: the number is EVIDENCE and the local index is
        # COMPLETE (TCGplayer text search often never surfaces promos/Full
        # Arts). If the read number is a real printing of exactly one
        # mechanic variant of the name, that variant IS the card ("Scizor"
        # #119/122 -> Scizor-EX). If not, snap promo tokens against the
        # family's real printings (Snorlax "XY79" -> XY179).
        if (name and number and via is None
                and not any(valuator._norm_num(c["number"]) == valuator._norm_num(str(number))
                            for c in cands)):
            lp = valuator.local_printings(str(name))
            hit = sorted(n for n, nums in lp.items()
                         if any(valuator._norm_num(x) == valuator._norm_num(str(number))
                                for x in nums))
            if len(hit) == 1:
                name, via = hit[0], "local index: number is a printing"
                cands = valuator.search_candidates(f"{name} {number}",
                                                   prefer_jp=prefer_jp) or cands
            elif lp:
                allnums = sorted(set().union(*lp.values()))
                fixed = valuator.snap_number(number, allnums)
                if fixed and valuator._norm_num(fixed) != valuator._norm_num(str(number)):
                    owners = sorted(n for n, nums in lp.items() if fixed in nums)
                    if len(owners) == 1:
                        number, snapped = fixed, True
                        name, via = owners[0], "local index snap"
                        cands = valuator.search_candidates(f"{name} {number}",
                                                           prefer_jp=prefer_jp) or cands
        # MECHANIC-VARIANT RETRY (TCGplayer-side): the read name is usually
        # missing its mechanic (OCR drops the stylized V/GX glyph:
        # "Mimikyu" #068/172 is Mimikyu V). Try suffixed forms; keep the
        # first that yields an exact-number product.
        if (name and number and via is None
                and not any(valuator._norm_num(c["number"]) == valuator._norm_num(str(number))
                            for c in cands)):
            for suf in ("V", "VMAX", "GX", "EX", "ex"):
                c2 = valuator.search_candidates(f"{name} {suf} {number}",
                                                prefer_jp=prefer_jp)
                exact = [c for c in c2
                         if valuator._norm_num(c["number"]) == valuator._norm_num(str(number))]
                if exact:
                    cands, name = c2, exact[0]["name"].split(" - ")[0]
                    via = "number-variant match"
                    break
        # Layer-B snap when the name is CERTAIN (fingerprint/dex), specific
        # (full mechanic form) — or when EVERY candidate already shares the
        # read name (snapping among one card's own printings is safe:
        # Snorlax "XY79" → XY179, the only Snorlax printing 1 edit away)
        def _ntoks(s):
            return set(re.sub(r"[^a-z& ]", " ",
                              s.split(" - ")[0].lower().replace("-", " ")).split())
        same_base = bool(cands) and all(
            _ntoks(str(name)) <= _ntoks(c["name"]) for c in cands)
        if name and number and cands and (via or _strong(str(name)) or same_base):
            fixed = valuator.snap_number(number, [c["number"] for c in cands])
            if fixed and valuator._norm_num(fixed) != valuator._norm_num(number):
                number, snapped = fixed, True
    # A set-code-shaped token ("m20", "sm3") is a SEARCH HINT, never a card
    # name. The upgrade path above turns it into a real name when a unique
    # catalog match exists; when no upgrade happened it must not be
    # PRESENTED as the identification (live catch: a JP M2a-set card
    # displayed name "m20" at Level C — a garbage name shown confidently is
    # worse than an honest unread).
    name = presented_identity_name(name, via)
    result = {"name": name, "name_read": name_read,
              "number": number, "number_read": number_read,
              "snapped": snapped, "via": via, "jp": jp, "query": query,
              "graded": bool(query) and graded,
              "watermark_dropped": dropped[:8],
              "candidates": [{"pid": c["pid"], "name": c["name"], "set": c["set"],
                              "number": c["number"], "line": c.get("line", ""),
                              "img": c.get("img", ""), "url": c.get("url", ""),
                              "market": c.get("market")}
                             for c in cands[:6]],
              "ocr": per_img}
    # DIRECTIVE.md, Rule 1/2: every identification carries its Evidence
    # Level + chain, generated by the pipeline itself — never a post-hoc label.
    import evidence
    result.update(evidence.build_evidence(result, all_lines, aid,
                                          image_paths=image_paths))
    evidence.log_failure(result)
    return result


# ── main ────────────────────────────────────────────────────────────────
def _argval(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    os.makedirs(DATASET_DIR, exist_ok=True)
    # --out <slug>: any Carousell page with listings (profile OR search)
    # can be a dataset — search pages are the TRAINING-DATA firehose
    slug = _argval("--out", "carousell_profile")
    meta_path = os.path.join(DATASET_DIR, f"{slug}.json")
    max_n = int(_argval("--max", "60"))
    identify_only = "--identify-only" in sys.argv

    if not identify_only:
        url = next((a for a in sys.argv[1:] if a.startswith("http")),
                   "https://www.carousell.ph/u/yujins-pokestop/")
        print(f"[1/3] scraping listings page: {url}")
        listings = scrape_profile(url)[:max_n]
        print(f"      {len(listings)} listings kept")
        for i, L in enumerate(listings):
            print(f"[2/3] listing {i+1}/{len(listings)}: {L['url']}")
            try:
                page = scrape_listing_page(L["url"])
                L["full_title"] = page["title"] or L["title"]
                L["desc"] = page["desc"]
                L["images"] = download_images(
                    i, page["images"],
                    prefix="" if slug == "carousell_profile" else slug + "_")
                print(f"      {len(L['images'])} images saved")
            except Exception as e:
                print(f"      [page failed] {e}")
                L["images"] = []
            time.sleep(1.5)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(listings, f, ensure_ascii=False, indent=1)
    else:
        with open(meta_path, encoding="utf-8") as f:
            listings = json.load(f)

    print("[3/3] image-first identification")
    import valuator

    def save():
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(listings, f, ensure_ascii=False, indent=1)

    # pass 1: OCR every photo once (cached in the dataset for re-runs)
    for i, L in enumerate(listings):
        if "ocr_raw" not in L:
            print(f"  OCR {i+1}/{len(listings)} ({len(L.get('images', []))} imgs)")
            L["ocr_raw"] = [valuator.ocr_lines(p) for p in L.get("images", [])]
            save()
    # pass 2: watermark vocabulary needs ALL listings' text first
    wm = batch_watermarks([[ln for img in L["ocr_raw"] for ln in img]
                           for L in listings])
    print(f"  watermark tokens: {sorted(wm)}")
    for i, L in enumerate(listings):
        if L.get("ident"):
            continue
        print(f"  identifying {i+1}/{len(listings)}")
        try:
            L["ident"] = identify(L.get("images", []), L["ocr_raw"], wm)
        except Exception as e:
            L["ident"] = {"error": str(e)}
        save()
        print(f"    -> {L['ident'].get('name')} #{L['ident'].get('number')} "
              f"via={L['ident'].get('via')} jp={L['ident'].get('jp')} "
              f"cands={len(L['ident'].get('candidates', []))}")
    print(f"done -> {meta_path}")


if __name__ == "__main__":
    main()
