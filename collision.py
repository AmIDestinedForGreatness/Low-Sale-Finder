"""Adversarial candidate collision analysis.

This module asks the inverse of the old picker: not "what supports the
chosen card?" but "what other real printing could fit the evidence?"  It is
local-only and deterministic so every A/B/C result can run it before an
Evidence Level is assigned.
"""
from difflib import SequenceMatcher
from functools import lru_cache
import os
import re
import sqlite3


HERE = os.path.dirname(os.path.abspath(__file__))
FP_DB = os.path.join(HERE, "fingerprints.sqlite")


def norm_number(value):
    """Canonical comparison form while preserving printing suffixes."""
    text = re.sub(r"[\s#]", "", str(value or "").lower())
    text = text.replace("_", "-")
    if "/" in text:
        left, right = text.split("/", 1)
        m = re.fullmatch(r"0*(\d+)([a-z]*)", left)
        if m:
            left = str(int(m.group(1))) + m.group(2)
        m = re.fullmatch(r"0*(\d+)([a-z]*)", right)
        if m:
            right = str(int(m.group(1))) + m.group(2)
        text = left + "/" + right
    else:
        m = re.fullmatch(r"([a-z-]+)0*(\d+)([a-z]*)", text)
        if m:
            text = m.group(1) + str(int(m.group(2))) + m.group(3)
    return text


def _number_aliases(value):
    n = norm_number(value)
    if not n:
        return set()
    aliases = {n, re.sub(r"[^a-z0-9]", "", n)}
    if "/" in n:
        left, right = n.split("/", 1)
        # 034/XY-P and XY34 are two common ways catalogs represent the
        # same promo number.  The alias is deliberately only an alternative,
        # never an exact match.
        promo = re.fullmatch(r"(xy|sm|swsh|bw|hgss|svp?)-?p", right)
        if promo:
            aliases.add(promo.group(1).replace("svp", "sv") + re.sub(r"[^0-9]", "", left))
        # A/b suffixed printings must be surfaced beside the base number.
        aliases.add(re.sub(r"(?<=\d)[a-z](?=/)", "", n))
    else:
        promo = re.fullmatch(r"(xy|sm|swsh|bw|hgss|svp?)(\d+)[a-z]?", n)
        if promo:
            prefix = promo.group(1)
            denom = "sv-p" if prefix in ("sv", "svp") else prefix + "-p"
            aliases.add(str(int(promo.group(2))) + "/" + denom)
    return {a for a in aliases if a}


def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def number_relation(left, right):
    a, b = norm_number(left), norm_number(right)
    if not a or not b:
        return "missing"
    if a == b:
        return "exact"
    if _number_aliases(a) & _number_aliases(b):
        return "normalized_variant"
    aa, bb = re.sub(r"[^a-z0-9]", "", a), re.sub(r"[^a-z0-9]", "", b)
    if abs(len(aa) - len(bb)) <= 1 and _lev(aa, bb) == 1:
        return "ocr_substitution"
    return "different"


def _norm_name(value):
    text = str(value or "").split(" - ", 1)[0]
    # Catalog display annotations such as ``(Full Art)`` or ``(63)`` are
    # product labels, not part of the printed card name.
    text = re.sub(r"\([^)]*\)", " ", text).lower().replace("-", " ")
    return " ".join(re.sub(r"[^a-z0-9& ]", " ", text).split())


def _name_similarity(left, right):
    a, b = _norm_name(left), _norm_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _name_anchor(value):
    ignored = {"m", "mega", "ex", "gx", "v", "vmax", "vstar",
               "tag", "team", "full", "art", "promo"}
    tokens = [token for token in _norm_name(value).split() if token not in ignored]
    return tokens[0] if tokens else ""


def _direct_name_compatible(name_read, candidate_name):
    """Return whether a direct OCR name fragment can belong to a candidate.

    OCR often reads the species but misses the mechanic suffix (``Mew`` vs
    ``Mew V``). That fragment still excludes ``Wyrdeer`` at the same number,
    but does not exclude ``M Altaria-EX`` when only ``Altaria`` was read.
    """
    read_tokens = _norm_name(name_read).split()
    candidate_tokens = set(_norm_name(candidate_name).split())
    if not read_tokens or not candidate_tokens:
        return False
    generic = {"m", "mega", "ex", "gx", "v", "vmax", "vstar",
               "tag", "team", "full", "art", "promo"}
    if not any(token not in generic for token in read_tokens):
        return False
    return all(token in candidate_tokens for token in read_tokens)


def _safe_candidate(candidate, source=None):
    out = dict(candidate or {})
    if source and not out.get("source"):
        out["source"] = source
    # Sets are JSON-unsafe and occasionally arrive from helper indexes.
    for key, value in list(out.items()):
        if isinstance(value, set):
            out[key] = sorted(value)
    return out


def _candidate_key(candidate):
    return (_norm_name(candidate.get("name")),
            norm_number(candidate.get("number")),
            str(candidate.get("set") or candidate.get("setname") or "").lower())


@lru_cache(maxsize=1)
def _catalog_rows():
    if not os.path.exists(FP_DB):
        return []
    conn = sqlite3.connect(FP_DB)
    try:
        rows = conn.execute(
            "SELECT id, name, hp, damages, subtypes, setname, number, rarity FROM fp"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": row[0], "name": row[1], "hp": row[2],
         "damages": row[3], "subtypes": row[4], "set": row[5],
         "number": row[6], "rarity": row[7], "source": "local_fingerprint_catalog"}
        for row in rows
    ]


_INDEX_CACHE = {}


def _catalog_indexes(rows):
    """Index the 20k local rows once; live identification must not rescan
    every card just to find one collector-number neighborhood."""
    key = id(rows)
    cached = _INDEX_CACHE.get(key)
    if cached is not None and cached[0] is rows:
        return cached[1]
    by_alias, by_anchor = {}, {}
    for row in rows:
        for alias in _number_aliases(row.get("number")):
            by_alias.setdefault(alias, []).append(row)
        anchor = _name_anchor(row.get("name"))
        if anchor:
            by_anchor.setdefault(anchor, []).append(row)
    indexes = by_alias, by_anchor
    _INDEX_CACHE[key] = (rows, indexes)
    # Patched unit-test lists are short-lived. Avoid an unbounded cache.
    if len(_INDEX_CACHE) > 12:
        oldest = next(iter(_INDEX_CACHE))
        _INDEX_CACHE.pop(oldest, None)
    return indexes


def _status(evidence, fallback="not_checked"):
    return evidence.get("status", fallback) if isinstance(evidence, dict) else fallback


def analyze(name, number, norm_number_value, language_evidence, set_evidence,
            card_type, attacks, abilities, existing_candidates):
    """Return the structured contradiction search required by NEXT-STEPS.

    ``language_evidence`` may also carry ``name_status`` and
    ``number_status``.  This keeps the accepted public signature while
    allowing the analyzer to distinguish a directly-read name from one
    inferred by a fingerprint or catalog lookup.
    """
    observed_number = number or norm_number_value
    context = language_evidence if isinstance(language_evidence, dict) else {}
    name_direct = context.get("name_status") == "confirmed"
    number_direct = context.get("number_status") == "confirmed"
    name_via = context.get("name_via")
    name_read = context.get("name_read")
    independent_name_vias = {"attack fingerprint", "fingerprint x number",
                             "fingerprint × number", "dex number", "attack names"}
    direct_name_fragment = name_read or (name if name_direct else None)
    direct_fragment_supports_chosen = _direct_name_compatible(direct_name_fragment, name)
    name_independent = (name_direct or direct_fragment_supports_chosen
                        or name_via in independent_name_vias)
    set_direct = _status(set_evidence) == "confirmed"
    language_direct = _status(language_evidence) == "confirmed" and bool(context.get("explicit"))

    supplied = [_safe_candidate(c, "existing_candidates")
                for c in (existing_candidates or [])]
    rows = _catalog_rows()
    search_performed = bool(rows) or bool(supplied)

    # Pull the useful slice out of indexed number/name neighborhoods. Same-
    # number rows are tested even when the names differ; same-name rows are
    # retained when one OCR substitution could point at them.
    widened = list(supplied)
    by_alias, by_anchor = _catalog_indexes(rows)
    local_pool, local_seen = [], set()
    for alias in _number_aliases(observed_number):
        for row in by_alias.get(alias, []):
            if row.get("id") not in local_seen:
                local_seen.add(row.get("id")); local_pool.append(row)
    for row in by_anchor.get(_name_anchor(name), []):
        if row.get("id") not in local_seen:
            local_seen.add(row.get("id")); local_pool.append(row)
    for row in local_pool:
        relation = number_relation(observed_number, row.get("number"))
        similarity = _name_similarity(name, row.get("name"))
        if relation in ("exact", "normalized_variant") or (
                relation == "ocr_substitution" and similarity >= 0.78):
            widened.append(row)

    deduped = {}
    for candidate in widened:
        deduped.setdefault(_candidate_key(candidate), candidate)
    widened = list(deduped.values())

    chosen = next((c for c in widened
                   if _norm_name(c.get("name")) == _norm_name(name)
                   and number_relation(observed_number, c.get("number")) == "exact"), None)
    chosen_set = str((chosen or {}).get("set") or (chosen or {}).get("setname") or "")
    same_identity = [c for c in widened
                     if _norm_name(c.get("name")) == _norm_name(name)
                     and number_relation(observed_number, c.get("number")) == "exact"]

    competing, excluded = [], []
    aggregate_shared, aggregate_conflicts, missing = set(), set(), set()
    for candidate in widened:
        cname, cnum = candidate.get("name"), candidate.get("number")
        relation = number_relation(observed_number, cnum)
        similarity = _name_similarity(name, cname)
        cset = str(candidate.get("set") or candidate.get("setname") or "")

        # The exact chosen product is not its own alternative. Duplicate
        # local/API representations of the same name+number+set collapse here.
        same_exact_identity = (_norm_name(cname) == _norm_name(name)
                               and relation == "exact")
        # A single API representation plus one local-index representation
        # often use a display set name ("Paldea Evolved") versus a set code
        # ("sv2"). They are corroborating copies of one product, not a
        # collision. Three or more representations still expose a real
        # duplicate-printing possibility and are tested below.
        api_local_pair = (same_exact_identity and len(same_identity) == 2
                          and {c.get("source") for c in same_identity}
                          == {"existing_candidates", "local_fingerprint_catalog"})
        if candidate is chosen or api_local_pair or (
                same_exact_identity
                and (not chosen_set or not cset or cset.lower() == chosen_set.lower())):
            continue

        shared, conflicts = [], []
        if similarity == 1.0:
            shared.append("card_name")
        elif similarity >= 0.78:
            shared.append("similar_card_name")
        elif name:
            conflicts.append("card_name")
        if relation == "exact":
            shared.append("card_number")
        elif relation == "normalized_variant":
            shared.append("normalized_card_number")
        elif relation == "ocr_substitution":
            shared.append("one_ocr_substitution_from_card_number")
        else:
            conflicts.append("card_number")
        if chosen_set and cset and chosen_set.lower() == cset.lower():
            shared.append("set")
        elif chosen_set and cset:
            conflicts.append("set")

        plausible = False
        unresolved_reason = ""
        if relation in ("exact", "normalized_variant"):
            if similarity >= 0.78:
                plausible = True
                unresolved_reason = "name and collector-number evidence overlap"
            elif not name_independent:
                plausible = True
                unresolved_reason = "collector number overlaps and the chosen name was inferred"
        elif relation == "ocr_substitution" and similarity >= 0.78:
            plausible = True
            unresolved_reason = "one OCR substitution reaches another similar-name printing"

        resolved = False
        resolution = ""
        direct_fragment_excludes = (direct_fragment_supports_chosen
                                    and not _direct_name_compatible(
                                        direct_name_fragment, cname))
        if plausible and direct_fragment_excludes:
            resolved, resolution = True, "directly-read name fragment excludes this product"
        elif (plausible and similarity < 1.0
              and name_via in independent_name_vias
              and _name_anchor(name) != _name_anchor(cname)):
            resolved, resolution = True, f"independent {name_via} evidence excludes this product"
        elif (not plausible and relation in ("exact", "normalized_variant")
              and similarity < 1.0 and name_independent):
            resolution_kind = ("directly-read name fragment"
                               if direct_fragment_supports_chosen or name_direct
                               else f"independent {name_via} evidence")
            resolution = f"{resolution_kind} excludes this product"
        if plausible and set_direct and chosen_set and cset and chosen_set.lower() != cset.lower():
            resolved, resolution = True, "directly-read set evidence excludes this product"
        if plausible and language_direct:
            line = str(candidate.get("line") or candidate.get("language") or "").lower()
            wanted_jp = bool(context.get("jp"))
            is_jp = "japan" in line or "japanese" in line
            if line and wanted_jp != is_jp:
                resolved, resolution = True, "direct language evidence excludes this regional product"

        annotated = _safe_candidate(candidate)
        annotated["collision_basis"] = shared
        annotated["collision_conflicts"] = conflicts
        annotated["number_relation"] = relation
        annotated["name_similarity"] = round(similarity, 3)
        if plausible and not resolved:
            annotated["unresolved_reason"] = unresolved_reason
            competing.append(annotated)
            aggregate_shared.update(shared)
            aggregate_conflicts.update(conflicts)
            if relation in ("exact", "normalized_variant") and similarity >= 0.78:
                missing.update(("expansion_symbol", "language", "artwork"))
            if relation == "ocr_substitution":
                missing.update(("higher_resolution_card_number", "artwork"))
        elif shared:
            annotated["excluded_by"] = resolution or "available direct evidence"
            excluded.append(annotated)

    # Strongest contradictions first: exact number, then normalized variants,
    # then one-character OCR alternatives.
    order = {"exact": 0, "normalized_variant": 1, "ocr_substitution": 2,
             "different": 3, "missing": 4}
    competing.sort(key=lambda c: (order.get(c.get("number_relation"), 9),
                                  -c.get("name_similarity", 0)))
    excluded.sort(key=lambda c: (order.get(c.get("number_relation"), 9),
                                 -c.get("name_similarity", 0)))

    exact_unresolved = any(c.get("number_relation") == "exact"
                           for c in competing)
    if exact_unresolved:
        status = "confirmed"
    elif competing:
        status = "possible"
    else:
        status = "none"

    exact_names = {
        _norm_name(c.get("name")) for c in supplied
        if c.get("name") and norm_number(c.get("number")) == norm_number(observed_number)
    }
    unique_inferred_name = (
        name_via in ("attack fingerprint", "attack names") and len({_norm_name(c.get("name")) for c in supplied if c.get("name")}) == 1
    ) or (
        name_via == "candidate consensus" and len(exact_names) == 1
    )
    if not name or not observed_number:
        recommended = "D"
    elif not search_performed:
        recommended = "C"
        status = "possible"
        missing.add("local_catalog_collision_search")
    elif status == "confirmed":
        recommended = "D"
    elif status == "possible":
        recommended = "C"
    elif (name_direct or unique_inferred_name) and number_direct:
        recommended = "A"
    else:
        recommended = "C"

    if status == "none":
        reason = (f"Adversarial search tested {len(widened)} catalog row(s); "
                  "no plausible competing printing survived the direct evidence.")
    elif status == "possible":
        reason = (f"{len(competing)} plausible OCR-neighbor printing(s) remain; "
                  "more direct visual evidence is required for Level A.")
    else:
        reason = (f"{len(competing)} catalog printing(s) share overlapping name/number "
                  "evidence and cannot be excluded by the checked dimensions.")

    limitations = []
    if not rows:
        limitations.append("local fingerprint catalog unavailable")
    else:
        limitations.append("local catalog may not contain every regional or newly released printing")
    limitations.append("artwork/holo authenticity is outside collision search")

    return {
        "collision_status": status,
        "selected_candidate": _safe_candidate(chosen) if chosen else None,
        "candidate_count": (1 if name or observed_number else 0) + len(competing),
        "competing_candidates": competing[:20],
        "alternatives_tested": excluded[:20],
        "evidence_shared": sorted(aggregate_shared),
        "evidence_conflicts": sorted(aggregate_conflicts),
        "evidence_missing": sorted(missing),
        "reason": reason,
        "recommended_evidence_level": recommended,
        "search_performed": search_performed,
        "catalog_rows_examined": len(widened),
        "search_limitations": limitations,
        "input_context": {
            "name_direct": name_direct,
            "name_read": name_read,
            "name_via": name_via,
            "name_independent_of_number": name_independent,
            "number_direct": number_direct,
            "set_direct": set_direct,
            "language_direct": language_direct,
            "card_type": card_type,
            "attacks_considered": list(attacks or []),
            "abilities_considered": list(abilities or []),
        },
    }
