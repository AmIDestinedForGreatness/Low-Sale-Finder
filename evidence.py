"""
evidence.py — the Evidence Level engine (DIRECTIVE.md, adopted 2026-07-17).

Builds a per-card Evidence Level (A-E), a 10-step evidence chain, a
confidence NUMBER earned from that chain (not asserted), and — for
non-Verified results — either an inference_explanation (Level C) or a
Required Failure Report (Level D/E). Every field here is derived from
signals the identification pipeline actually produced. Nothing is invented
after the fact; a dimension the pipeline never checked is reported as
not_checked, not silently marked passing.

STRUCTURAL LIMITATION (load-bearing, do not paper over — this is the #1
open item in FAILURES.md): the pipeline is TEXT-FIRST. It reads names,
numbers and attack/ability text via OCR, and confirms identity by forcing
against a catalog. It has NO independent artwork-match, holo-pattern
detector, or structured HP/ability parser. Those five chain dimensions
(artwork, hp, ability, expansion_symbol, holo_pattern) are reported
not_checked for every automated identification. This means Evidence Level
A ("every identifying feature directly visible") is assignable to a clean,
unforced, uniquely-matched name+number read — but the chain output will
STILL show 5/10 steps unchecked, because a text match, however clean,
is not the same claim as a verified artwork match. That gap is real and
tracked, not hidden — see build_failure_record() and FAILURES.md.
"""
import json
import os
import re

DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
FAILURES_JSON = os.path.join(DATASET_DIR, "failures.json")
FAILURES_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FAILURES.md")

LEVELS = {
    "A": "Verified — name and number both read directly, uniquely matched, no forcing/inference",
    "B": "Human Eye Verified — OCR failed; a manual (assistant) visual read succeeded and is exact",
    "C": "Catalog Forced — OCR incomplete or number corrected; exactly one catalog candidate fits",
    "D": "Partial — identity (name) known, printing (exact number) not established",
    "E": "Unknown — insufficient evidence for even a partial identification",
}

CHAIN_STEPS = ["artwork", "pokemon_name", "hp", "attack_names", "ability",
               "expansion_symbol", "card_number", "language", "holo_pattern",
               "catalog_match"]

_UNCHECKED_VISUAL = {
    "artwork": "no automated code path visually matches card artwork yet",
    "hp": "OCR does not structurally parse an HP value (only attack DAMAGE numbers, for fingerprinting)",
    "ability": "no automated code path separately extracts/verifies ability text",
    "expansion_symbol": "set is inferred from the matched catalog product's metadata, not from visually reading the printed expansion symbol",
    "holo_pattern": "no automated code path detects holo/foil pattern",
}


def _eye_read(via):
    # matches all real suffixed forms: "visual read (assistant eye)",
    # "… + index constraint", "… — dark-holo footer"
    return "visual read (assistant eye)" in str(via or "")


def _name_status(ident):
    name, via = ident.get("name"), ident.get("via")
    if not name:
        return "failed", "no name could be read or derived by any layer"
    if _eye_read(via):
        return "confirmed", "read directly off the card by the assistant (manual visual read, OCR had failed)"
    if via in (None, "unique number match", "candidate consensus"):
        # unique number match / candidate consensus still derive the NAME
        # from the number's catalog membership, not a direct name text read
        if via is None:
            return "confirmed", "read directly from OCR text on the card"
        return "inferred", f"name derived because exactly one/only matching catalog product(s) share the read number ({via})"
    if via == "attack fingerprint":
        return "inferred", "derived from an attack-damage fingerprint matching exactly one species — not a direct name text read"
    if via == "fingerprint × number":
        return "inferred", "derived by crossing a tied fingerprint against the read number's own catalog matches"
    if via == "dex number":
        return "inferred", "derived from a National Dex number (JP vintage cards print no Latin name) — a species ID, not a name text read"
    if via == "attack names":
        return "inferred", "derived from a matched attack/ability name unique to one species — not a direct name text read"
    if via in ("local index: number is a printing", "local index snap", "number-variant match"):
        return "inferred", f"derived by joining the read number against the local printings index ({via}) — the number is the evidence, not a direct name text read"
    return "inferred", f"derived via {via}"


def _number_status(ident):
    number, snapped, via = ident.get("number"), ident.get("snapped"), ident.get("via")
    if not number:
        return "failed", "no collector number could be read"
    if _eye_read(via):
        return "confirmed", "read directly off the footer by the assistant (manual visual read, OCR had failed)"
    if snapped:
        return "inferred", (f"OCR read '{ident.get('number_read')}', which is not a real printing — "
                            f"corrected to '{number}' as the only real printing within edit distance")
    return "confirmed", "read directly from OCR text"


def _catalog_status(ident):
    cands = ident.get("candidates") or []
    number = ident.get("number")
    if not cands:
        return "not_checked", "no catalog search returned candidates for this query"
    if not number:
        return "not_checked", f"{len(cands)} candidate(s) returned but no number to narrow against — identity is a partial (name-only) match"
    exact = [c for c in cands
             if _norm(c.get("number", "")) == _norm(str(number))]
    if len(exact) == 1:
        return "confirmed", f"exactly one catalog product matches name+number: {exact[0]['name']} ({exact[0].get('set', '?')})"
    if len(exact) > 1:
        return "inferred", f"{len(exact)} catalog products share this exact number — narrowed by name/context, not a unique catalog key alone"
    return "not_checked", f"{len(cands)} candidate(s) returned, none carry an exact number match"


def _norm(n):
    n = str(n or "").strip().lower()
    n = re.sub(r"^0+(?=\d)", "", n)
    return n


def _language_status(ident, merged_lines):
    jp, via = ident.get("jp"), ident.get("via")
    number = str(ident.get("number") or "")
    if jp and (bool(re.search(r"[A-Za-z]-P$", number)) or _eye_read(via)):
        return "confirmed", "positive JP evidence: JP-style promo footer format (…/XY-P) or direct visual read"
    if jp:
        return "inferred", f"language claim follows from the identification path ({via}), not a directly read language marker"
    if not jp and (ident.get("name") or ident.get("number")):
        return "confirmed", "no positive Japanese/Korean evidence found (JP set code, JP promo footer, or JP-only ID path) — defaults to English/unspecified per the 'language is a claim' rule"
    return "not_checked", "no identity established yet"


def _attack_status(ident, aid, merged_lines):
    if aid:
        return "confirmed", f"attack/ability text matched against the 31,908-entry index: '{aid[0]}'"
    if any(re.search(r"[A-Z][a-z]{3,}\s[A-Z][a-z]{3,}", ln) for ln in merged_lines):
        return "not_checked", "attack-shaped text present in OCR but did not resolve to a unique index match"
    return "not_checked", "no attack/ability text usable in this OCR pass"


def build_evidence(ident, merged_lines, aid=None):
    """ident: the dict identify() already computed. merged_lines: the OCR
    text actually available to the identifier. aid: attack_id() result if
    Layer E ran (or None). Mutates nothing; returns a new dict to merge
    into the identify() result."""
    merged_lines = merged_lines or []
    name, number = ident.get("name"), ident.get("number")
    graded = ident.get("graded")

    chain = {s: {"status": "not_checked", "note": _UNCHECKED_VISUAL.get(s, "")}
             for s in CHAIN_STEPS}
    chain["pokemon_name"]["status"], chain["pokemon_name"]["note"] = _name_status(ident)
    chain["card_number"]["status"], chain["card_number"]["note"] = _number_status(ident)
    chain["catalog_match"]["status"], chain["catalog_match"]["note"] = _catalog_status(ident)
    chain["language"]["status"], chain["language"]["note"] = _language_status(ident, merged_lines)
    chain["attack_names"]["status"], chain["attack_names"]["note"] = _attack_status(ident, aid, merged_lines)
    if _eye_read(ident.get("via")):
        for dim in _UNCHECKED_VISUAL:
            chain[dim]["status"] = "seen_not_itemized"
            chain[dim]["note"] = ("the assistant looked directly at this photo to confirm name/number, "
                                  "but did not separately itemize this feature — re-check explicitly if this card is contested")

    # ── Evidence Level ────────────────────────────────────────────────
    name_ok = chain["pokemon_name"]["status"] in ("confirmed", "inferred")
    num_ok = chain["card_number"]["status"] in ("confirmed", "inferred")
    if not name_ok:
        level = "E"
    elif not num_ok:
        level = "D"
    elif graded:
        level = "C"          # slabs are region-ambiguous by construction — never A
    elif _eye_read(ident.get("via")):
        level = "B"
    elif (chain["pokemon_name"]["status"] == "confirmed"
          and chain["card_number"]["status"] == "confirmed"
          and chain["catalog_match"]["status"] == "confirmed"):
        level = "A"
    else:
        level = "C"

    confirmed_n = sum(1 for s in CHAIN_STEPS if chain[s]["status"] == "confirmed")
    confidence = round(100 * confirmed_n / len(CHAIN_STEPS))
    confidence_reason = (
        f"{confirmed_n}/{len(CHAIN_STEPS)} evidence-chain steps independently confirmed: "
        + ", ".join(s for s in CHAIN_STEPS if chain[s]["status"] == "confirmed")
        + (". No chain step counts toward confidence unless it was actually checked — "
           "artwork/HP/ability/expansion-symbol/holo-pattern have no automated code path "
           "yet, so they never contribute even on a Level A identification."
           if confirmed_n < len(CHAIN_STEPS) else "")
    )

    out = {"evidence_level": level, "evidence_level_meaning": LEVELS[level],
           "evidence_chain": chain, "confidence": confidence,
           "confidence_reason": confidence_reason}

    if level == "C":
        out["inference_explanation"] = build_inference_explanation(ident, merged_lines)
    if level in ("D", "E"):
        out["failure_report"] = build_failure_report(ident, merged_lines)
    return out


def build_inference_explanation(ident, merged_lines):
    """Rule 1, required fields for every Level C card."""
    number_read = ident.get("number_read")
    via = ident.get("via")
    ocr_snippet = [ln for ln in merged_lines
                   if re.search(r"\d", ln) or (number_read and str(number_read)[:2] in ln)][:6]
    why_failed = ("OCR read a number that is not a real catalog printing (misread/blur)"
                  if ident.get("snapped") else
                  "OCR could not resolve a full name/number pair on its own; a downstream layer forced the identity")
    cands = ident.get("candidates") or []
    return {
        "original_ocr_text": ocr_snippet or merged_lines[:6],
        "why_ocr_failed": why_failed,
        "candidate_search_process": f"via={via}; {len(cands)} catalog candidate(s) considered",
        "why_only_one_candidate_remained": (
            f"'{ident.get('number_read')}' does not exist in the catalog; "
            f"'{ident.get('number')}' is the only real printing within edit distance"
            if ident.get("snapped") else
            f"the read fragment(s) matched exactly one catalog entry via {via}"
        ),
        "remaining_uncertainty": ("number was corrected, not read — confirm against the physical card's footer before listing"
                                  if ident.get("snapped") else
                                  "identity was forced by elimination, not by directly reading every field — artwork/holo unconfirmed"),
    }


def build_failure_report(ident, merged_lines):
    """Rule 4, required questions for every Level D/E card."""
    name, number = ident.get("name"), ident.get("number")
    missing = ("card number / exact printing" if name and not number
              else "pokemon name" if number and not name
              else "both name and number")
    has_text = any(re.search(r"[A-Za-z]{3,}", ln) for ln in merged_lines)
    has_digits = any(re.search(r"\d", ln) for ln in merged_lines)
    return {
        "missing_feature": missing,
        "would_another_image_angle_help": True,
        "would_different_ocr_pass_help": not has_text or not has_digits,
        "would_removing_glare_help": True,
        "would_different_language_db_help": not ident.get("jp"),
        "would_scan_instead_of_photo_help": True,
        "blocking_evidence": (
            "no readable text at all in this crop" if not has_text and not has_digits
            else "text present but no name-shaped or number-shaped fragment resolved"
        ),
    }


# ── Failure Database (DIRECTIVE.md Rule 4/6) ────────────────────────────
# Every non-Level-A identification becomes a permanent, structured
# improvement record: Problem -> Cause -> Current Solution -> Future
# Solution -> Status. Keyed so reruns update in place instead of growing
# unbounded duplicate entries for the same card.

_STRUCTURAL_GAP_ID = "STRUCTURAL-000"


def _load_failures():
    if os.path.exists(FAILURES_JSON):
        with open(FAILURES_JSON, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_failures(db):
    os.makedirs(DATASET_DIR, exist_ok=True)
    with open(FAILURES_JSON, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    _render_md(db)


def _card_key(ident):
    return f"{ident.get('name')}|{ident.get('number')}|{ident.get('query')}"


def _record_for(ident):
    level = ident.get("evidence_level")
    chain = ident.get("evidence_chain", {})
    if level == "C":
        ie = ident.get("inference_explanation", {})
        return {
            "problem": f"{ident.get('name')} {ident.get('number')} — identity forced by inference, not directly read",
            "cause": ie.get("why_ocr_failed", "?"),
            "current_solution": f"catalog-forced match ({ident.get('via')}) — {ie.get('why_only_one_candidate_remained', '')}",
            "future_solution": ("re-OCR this footer region at higher zoom, or add a targeted preprocessing "
                                "pass for this failure pattern" if ident.get("snapped") else
                                "widen the automated evidence chain so this stops depending on elimination alone"),
            "status": "Pending — mitigated by inference, not solved",
        }
    if level == "B":
        return {
            "problem": f"{ident.get('name')} {ident.get('number')} — automated OCR could not read this card at all",
            "cause": chain.get("card_number", {}).get("note", "?") if not ident.get("number_read") else "OCR produced no usable text on the identifying region",
            "current_solution": "manual assistant visual read (eye-gate)",
            "future_solution": "train footer-specific OCR preprocessing for this failure pattern (glare/dark-holo/micro-text — see LESSONS.md)",
            "status": "Pending — mitigated by manual read, automated path unsolved",
        }
    if level in ("D", "E"):
        fr = ident.get("failure_report", {})
        helps = [k.replace("would_", "").replace("_", " ")
                for k, v in fr.items() if k.startswith("would_") and v]
        return {
            "problem": f"{ident.get('name') or '(unknown)'} {ident.get('number') or '(unknown)'} — {fr.get('missing_feature', 'identity incomplete')}",
            "cause": fr.get("blocking_evidence", "?"),
            "current_solution": "none — unidentified",
            "future_solution": "; ".join(helps) or "needs additional evidence of an unknown kind",
            "status": "Open",
        }
    return None


def log_failure(ident):
    """Called once per identify() result. No-op for Level A. Idempotent —
    reruns update the existing record for this card rather than duplicating."""
    db = _load_failures()
    if _STRUCTURAL_GAP_ID not in db:
        db[_STRUCTURAL_GAP_ID] = {
            "problem": "Evidence chain has 5/10 structurally unchecked dimensions on EVERY identification, including Level A: artwork, hp, ability, expansion_symbol, holo_pattern",
            "cause": "the pipeline is text/OCR-first; it has never had an independent visual-artwork match, holo-pattern detector, or structured HP/ability parser",
            "current_solution": "assistant manual eye-read covers these implicitly but un-itemized when it runs (Level B path only)",
            "future_solution": "build a visual-match step (perceptual hash or vision-model call against reference card images) — cost/API implications, needs sign-off before wiring into the automated pipeline",
            "status": "Open — single highest-priority engineering item from DIRECTIVE.md adoption",
        }
    rec = _record_for(ident)
    if rec:
        db[_card_key(ident)] = rec
    _save_failures(db)


def _render_md(db):
    lines = ["# FAILURES.md — the Failure Database (DIRECTIVE.md Rule 4/6)",
             "",
             "Auto-generated by `evidence.py:log_failure()`. Do not hand-edit — ",
             "edit `dataset/failures.json` or fix the underlying cause instead.",
             "Every identification that is not Level A produces a record here.",
             "", "---", ""]
    structural = db.get(_STRUCTURAL_GAP_ID)
    if structural:
        lines += [f"## {_STRUCTURAL_GAP_ID} — structural (applies to every card)", ""]
        for k, v in structural.items():
            lines.append(f"**{k.replace('_', ' ').title()}:** {v}")
        lines += ["", "---", ""]
    others = {k: v for k, v in db.items() if k != _STRUCTURAL_GAP_ID}
    lines.append(f"## Per-card records ({len(others)})")
    lines.append("")
    for key, rec in sorted(others.items()):
        lines.append(f"### {key}")
        for k, v in rec.items():
            lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        lines.append("")
    with open(FAILURES_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
