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

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
IMG_DIR = os.path.join(DATASET_DIR, "images")


# ── phase 1: scrape the profile ────────────────────────────────────────
def scrape_profile(url):
    """All listings on a seller profile: url, title, price_text, status."""
    from playwright.sync_api import sync_playwright
    listings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  locale="en-US")
        page = ctx.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
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
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  locale="en-US")
        page = ctx.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
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


def download_images(listing_idx, urls):
    os.makedirs(IMG_DIR, exist_ok=True)
    paths = []
    seen_size = set()
    for n, u in enumerate(urls[:6]):
        try:
            r = requests.get(_fullsize(u), headers={"User-Agent": UA}, timeout=30)
            if r.status_code != 200 or len(r.content) < 4000:
                continue
            if len(r.content) in seen_size:      # og:image dup of gallery img
                continue
            seen_size.add(len(r.content))
            ext = ".png" if r.content[:4] == b"\x89PNG" else ".jpg"
            path = os.path.join(IMG_DIR, f"L{listing_idx:02d}_{n}{ext}")
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
    if real:      # most SPECIFIC validated read wins: "Pikachu ex" > "Pikachu"
        name = sorted(real, key=lambda n: (_strong(n), len(n), real.count(n)))[-1]
    elif names:
        name = names[0]                          # JP setcode-as-name path
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
    jp = (bool(via) or bool(name and valuator._SET_RE.fullmatch(name))
          or bool(number and not name))
    number_read, snapped = number, False
    cands = []
    query = (str(name or "") + " " + str(number or "")).strip()
    if query:
        cands = valuator.search_candidates(query, prefer_jp=jp)
        if not cands and name:                   # number may be misread
            cands = valuator.search_candidates(str(name), prefer_jp=jp)
        # promo/JP numbers are near-unique: exactly ONE catalog product with
        # the read number = the card ("197/SV-P" -> Pikachu). Also upgrades
        # a setcode-only name ("sm3" -> Raichu GX). Still eye-gated.
        if ((not name or valuator._SET_RE.fullmatch(str(name)))
                and number and len(cands) == 1
                and valuator._norm_num(cands[0]["number"]) == valuator._norm_num(str(number))):
            name = cands[0]["name"].split(" - ")[0]
            via = via or "unique number match"
        # Layer-B snap only when the name is CERTAIN (fingerprint/dex) or
        # specific (full mechanic form) — see _strong's live catch
        if name and number and cands and (via or _strong(str(name))):
            fixed = valuator.snap_number(number, [c["number"] for c in cands])
            if fixed and valuator._norm_num(fixed) != valuator._norm_num(number):
                number, snapped = fixed, True
    return {"name": name, "number": number, "number_read": number_read,
            "snapped": snapped, "via": via, "jp": jp, "query": query,
            "watermark_dropped": dropped[:8],
            "candidates": [{"pid": c["pid"], "name": c["name"], "set": c["set"],
                            "number": c["number"], "line": c.get("line", "")}
                           for c in cands[:5]],
            "ocr": per_img}


# ── main ────────────────────────────────────────────────────────────────
def main():
    os.makedirs(DATASET_DIR, exist_ok=True)
    meta_path = os.path.join(DATASET_DIR, "carousell_profile.json")
    identify_only = "--identify-only" in sys.argv

    if not identify_only:
        url = next((a for a in sys.argv[1:] if a.startswith("http")),
                   "https://www.carousell.ph/u/yujins-pokestop/")
        print(f"[1/3] scraping profile: {url}")
        listings = scrape_profile(url)
        print(f"      {len(listings)} listings found")
        for i, L in enumerate(listings):
            print(f"[2/3] listing {i+1}/{len(listings)}: {L['url']}")
            try:
                page = scrape_listing_page(L["url"])
                L["full_title"] = page["title"] or L["title"]
                L["desc"] = page["desc"]
                L["images"] = download_images(i, page["images"])
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
