"""Evidence-first decision engine (DIRECTIVE.md).

Every identification emits:
* an Evidence Level (A-E),
* a ten-dimension evidence chain,
* Evidence Coverage (how much was actually checked),
* provisional Prediction Confidence (how likely the chosen candidate is),
* an adversarial collision search and falsification report.

Coverage and prediction confidence are intentionally separate. Missing or
unimplemented providers lower coverage only; their absence is never treated
as evidence against a candidate.
"""
import json
import os
import re


HERE = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(HERE, "dataset")
FAILURES_JSON = os.path.join(DATASET_DIR, "failures.json")
FAILURES_MD = os.path.join(HERE, "FAILURES.md")

LEVELS = {
    "A": "Verified - direct name/number read, catalog agreement, and adversarial collision search clean",
    "B": "Human Eye Verified - OCR failed; a manual visual read succeeded and is exact",
    "C": "Catalog Forced - one or more identifying steps remain inferred or collision-sensitive",
    "D": "Partial/Ambiguous - exact printing is not established",
    "E": "Unknown - insufficient evidence for even a partial identification",
}

CHAIN_STEPS = ["artwork", "pokemon_name", "hp", "attack_names", "ability",
               "expansion_symbol", "card_number", "language", "holo_pattern",
               "catalog_match"]

_UNCHECKED_VISUAL = {
    "artwork": "ArtworkProvider did not run or had no independent local reference",
    "hp": "HPProvider is an honest stub; no structured HP verification ran",
    "ability": "AbilityProvider is an honest stub; no structured ability verification ran",
    "expansion_symbol": "ExpansionProvider is an honest stub; the printed set symbol was not read",
    "holo_pattern": "HoloProvider is an honest stub; no foil-pattern verification ran",
}


def _eye_read(via):
    return "visual read (assistant eye)" in str(via or "")


def _norm(value):
    text = str(value or "").strip().lower()
    return re.sub(r"^0+(?=\d)", "", text)


def _norm_card_name(value):
    text = str(value or "").split(" - ", 1)[0].lower().replace("-", " ")
    return " ".join(re.sub(r"[^a-z0-9& ]", " ", text).split())


def _name_status(ident):
    name, via = ident.get("name"), ident.get("via")
    if not name:
        return "failed", "no name could be read or derived by any layer"
    if _eye_read(via):
        return "confirmed", "read directly from the card by a human eye after OCR failed"
    if ident.get("name_read"):
        if _norm_card_name(ident.get("name_read")) == _norm_card_name(name):
            return "confirmed", "read directly from OCR text before downstream catalog refinement"
        return "inferred", (f"OCR directly read '{ident.get('name_read')}', then catalog logic "
                            f"refined the identity to '{name}'")
    if via is None:
        return "confirmed", "read directly from OCR text on the card"
    messages = {
        "unique number match": "name derived from the read number's catalog membership",
        "candidate consensus": "name derived because every number-matched candidate shares it",
        "attack fingerprint": "name derived from an attack/damage fingerprint, not name text",
        "fingerprint x number": "name derived by crossing a tied fingerprint with number matches",
        "fingerprint × number": "name derived by crossing a tied fingerprint with number matches",
        "dex number": "name derived from a National Dex number, not name text",
        "attack names": "name derived from indexed attack/ability text, not name text",
        "local index: number is a printing": "name derived by joining the number to the printings index",
        "local index snap": "name derived while correcting a number against the local index",
        "number-variant match": "mechanic variant derived from the number's catalog product",
    }
    return "inferred", messages.get(via, f"name derived via {via}")


def _number_status(ident):
    number, via = ident.get("number"), ident.get("via")
    if not number:
        return "failed", "no collector number could be read"
    if _eye_read(via):
        return "confirmed", "read directly from the footer by a human eye after OCR failed"
    if ident.get("snapped"):
        return "inferred", (f"OCR read '{ident.get('number_read')}', which was corrected to "
                            f"'{number}' by a unique edit-distance catalog constraint")
    return "confirmed", "read directly from OCR text"


def _catalog_status(ident):
    candidates = ident.get("candidates") or []
    number = ident.get("number")
    if not candidates:
        return "not_checked", "no catalog search returned a candidate"
    if not number:
        return "not_checked", (f"{len(candidates)} candidate(s) returned but no number "
                               "was available to identify an exact printing")
    exact = [c for c in candidates if _norm(c.get("number")) == _norm(number)]
    if len(exact) == 1:
        return "confirmed", (f"catalog agrees with name+number: {exact[0].get('name')} "
                             f"({exact[0].get('set', '?')}); uniqueness alone is not proof")
    if len(exact) > 1:
        return "inferred", f"{len(exact)} returned products share this number"
    return "not_checked", f"{len(candidates)} candidate(s) returned; none exactly match the number"


def _language_status(ident, merged_lines):
    jp, via = ident.get("jp"), ident.get("via")
    number = str(ident.get("number") or "")
    if jp and (re.search(r"[A-Za-z]-P$", number) or _eye_read(via)):
        return "confirmed", "positive JP evidence: printed promo format or a direct visual read"
    if jp:
        return "inferred", f"language follows from identification route '{via}', not a read marker"
    if ident.get("name") or ident.get("number"):
        return "inferred", "English/unspecified is a default after no positive JP/KR marker was found"
    return "not_checked", "no identity was established"


def _attack_status(ident, aid, merged_lines):
    if aid:
        return "confirmed", f"attack/ability text resolved through the local index to '{aid[0]}'"
    if any(re.search(r"[A-Z][a-z]{3,}\s[A-Z][a-z]{3,}", line)
           for line in merged_lines):
        return "not_checked", "attack-shaped OCR text did not resolve to a unique indexed match"
    return "not_checked", "no attack/ability text was usable in this OCR pass"


def _artwork_evidence(image_paths, candidates, provider_context):
    if not image_paths:
        return {"provider": "ArtworkProvider:perceptual_hash",
                "dimension": "artwork", "status": "not_verified",
                "match_score": 0.0, "matched_reference": None,
                "confidence_note": "no input image was supplied to the evidence engine"}
    try:
        from providers import ArtworkProvider
        provider = ArtworkProvider()
    except Exception as exc:
        return {"provider": "ArtworkProvider:perceptual_hash",
                "dimension": "artwork", "status": "not_verified",
                "match_score": 0.0, "matched_reference": None,
                "confidence_note": f"provider unavailable: {exc}"}
    # At most two inputs and eight references: this is a cheap partial
    # provider, so it must stay bounded even on six-photo listings.
    results = [provider.verify(path, candidates, provider_context or {})
               for path in list(image_paths)[:2] if path]
    if not results:
        return provider.verify(None, candidates, provider_context or {})
    matched = [r for r in results if r.get("status") == "matched"]
    if matched:
        return max(matched, key=lambda r: r.get("match_score", 0))
    tested = [r for r in results if r.get("status") == "no_match"]
    if tested:
        return max(tested, key=lambda r: r.get("match_score", 0))
    local = results[0]
    if local.get("status") in ("not_verified", "no_match"):
        try:
            from providers import WebArtworkProvider
            web = WebArtworkProvider().verify(image_paths[0], candidates, provider_context or {})
            if web.get("status") == "matched":
                local = web
        except Exception as exc:
            local["web_error"] = str(exc)
    return local


def _provisional_confidence(level, chain, ident, collision_result,
                            artwork_result):
    """Transparent rules, explicitly not a calibrated probability."""
    score, factors = 5, ["+5 candidate proposed"]
    name_status = chain["pokemon_name"]["status"]
    number_status = chain["card_number"]["status"]
    catalog_status = chain["catalog_match"]["status"]
    if name_status == "confirmed":
        score += 28; factors.append("+28 card name directly read")
    elif name_status == "inferred":
        score += 12; factors.append("+12 card name inferred from structured evidence")
    if number_status == "confirmed":
        score += 30; factors.append("+30 collector number directly read")
    elif number_status == "inferred":
        score += 10; factors.append("+10 collector number inferred/corrected")
    if catalog_status == "confirmed":
        score += 8; factors.append("+8 catalog agrees with name+number (not proof by itself)")
    elif catalog_status == "inferred":
        score += 3; factors.append("+3 catalog partially agrees but is not unique")

    collision_status = collision_result.get("collision_status")
    if collision_status == "none" and collision_result.get("search_performed"):
        score += 18; factors.append("+18 adversarial search found no plausible competitor")
    elif collision_status == "possible":
        score -= 12; factors.append("-12 an OCR-neighbor alternative remains possible")
    elif collision_status == "confirmed":
        score -= 35; factors.append("-35 competing printings remain unresolved")
    if ident.get("snapped"):
        score -= 12; factors.append("-12 number was corrected rather than read")
    if ident.get("graded"):
        score -= 12; factors.append("-12 slab region/language ambiguity")

    if artwork_result.get("status") == "matched":
        factors.append("+0 artwork matched a local reference (coverage only)")
    elif artwork_result.get("status") == "no_match":
        factors.append("+0 artwork did not match (weak provider result; score unchanged)")
    else:
        factors.append("+0 artwork unavailable/not verified (no prediction penalty)")

    caps = {"A": 96, "B": 92, "C": 74, "D": 49, "E": 15}
    return max(0, min(caps[level], score)), factors


def build_adversarial_validation(collision_result):
    competitors = collision_result.get("competing_candidates") or []
    tested = collision_result.get("alternatives_tested") or []
    alternative = (competitors or tested or [None])[0]
    relation = (alternative or {}).get("number_relation")
    exclusions = []
    if alternative and alternative.get("excluded_by"):
        exclusions.append(alternative["excluded_by"])
    elif alternative:
        exclusions.extend(alternative.get("collision_conflicts") or [])
    if competitors:
        missing = collision_result.get("evidence_missing") or [
            "set/expansion symbol", "language", "artwork"]
        overturn = "Directly read one of: " + ", ".join(missing)
    else:
        overturn = ("A higher-resolution footer, set/language marker, or independent artwork "
                    "reference that conflicts with the selected printing")
    limitations = collision_result.get("search_limitations") or []
    return {
        "strongest_alternative": alternative,
        "evidence_supporting_alternative": (alternative or {}).get("collision_basis", []),
        "evidence_excluding_alternative": exclusions,
        "could_ocr_substitution_explain_alt": relation in (
            "ocr_substitution", "normalized_variant"),
        "could_collision_be_undetected": bool(limitations),
        "what_would_overturn_this": overturn,
        "alternative_search_result": collision_result.get("reason", ""),
        "search_limitations": limitations,
    }


def build_evidence(ident, merged_lines, aid=None, image_paths=None,
                   provider_context=None):
    """Build evidence without mutating ``ident``."""
    merged_lines = merged_lines or []
    name, number = ident.get("name"), ident.get("number")

    chain = {step: {"status": "not_checked",
                    "note": _UNCHECKED_VISUAL.get(step, "")}
             for step in CHAIN_STEPS}
    chain["pokemon_name"]["status"], chain["pokemon_name"]["note"] = _name_status(ident)
    chain["card_number"]["status"], chain["card_number"]["note"] = _number_status(ident)
    chain["catalog_match"]["status"], chain["catalog_match"]["note"] = _catalog_status(ident)
    chain["language"]["status"], chain["language"]["note"] = _language_status(ident, merged_lines)
    chain["attack_names"]["status"], chain["attack_names"]["note"] = _attack_status(
        ident, aid, merged_lines)
    if _eye_read(ident.get("via")):
        for dimension in _UNCHECKED_VISUAL:
            chain[dimension]["status"] = "seen_not_itemized"
            chain[dimension]["note"] = (
                "a human inspected the photo for name/number but did not separately itemize this feature")

    artwork_result = _artwork_evidence(image_paths, ident.get("candidates") or [],
                                       provider_context)
    if artwork_result.get("status") == "matched":
        chain["artwork"] = {"status": "confirmed",
                            "note": artwork_result.get("confidence_note", ""),
                            "provider_result": artwork_result}
    elif artwork_result.get("status") == "no_match":
        chain["artwork"] = {"status": "failed",
                            "note": artwork_result.get("confidence_note", ""),
                            "provider_result": artwork_result}
    elif image_paths:
        chain["artwork"] = {"status": "not_verified",
                            "note": artwork_result.get("confidence_note", ""),
                            "provider_result": artwork_result}

    import collision
    language_context = dict(chain["language"])
    language_context.update({
        "name_status": chain["pokemon_name"]["status"],
        "number_status": chain["card_number"]["status"],
        "name_read": ident.get("name_read"),
        "name_via": ident.get("via"),
        "jp": bool(ident.get("jp")),
        "explicit": chain["language"]["note"].startswith("positive JP evidence"),
    })
    collision_result = collision.analyze(
        name, number, collision.norm_number(number), language_context,
        chain["expansion_symbol"], ident.get("card_type"),
        ident.get("attacks") or [], ident.get("abilities") or [],
        (ident.get("candidates") or []) + (artwork_result.get("web_candidates") or []))

    # API text search is not the only catalog. If the widened local catalog
    # contains the exact selected identity, record that corroboration in the
    # evidence chain. Conversely, a valid-looking OCR number with no exact
    # product anywhere is not a Level-C printing; it remains partial (D).
    selected_catalog = collision_result.get("selected_candidate")
    if (chain["catalog_match"]["status"] == "not_checked"
            and selected_catalog):
        chain["catalog_match"] = {
            "status": "confirmed",
            "note": (f"local catalog agrees with name+number: "
                     f"{selected_catalog.get('name')} "
                     f"({selected_catalog.get('set', '?')}); uniqueness alone is not proof"),
        }

    name_ok = chain["pokemon_name"]["status"] in ("confirmed", "inferred")
    number_ok = chain["card_number"]["status"] in ("confirmed", "inferred")
    collision_status = collision_result.get("collision_status")
    if not name_ok:
        level = "E"
    elif not number_ok:
        level = "D"
    elif collision_status == "confirmed":
        level = "D"
    elif ident.get("graded"):
        level = "C"
    elif _eye_read(ident.get("via")):
        level = "B"
    elif chain["catalog_match"]["status"] not in ("confirmed", "inferred"):
        level = "D"
    elif collision_status != "none" or not collision_result.get("search_performed"):
        level = "C"
    elif (chain["pokemon_name"]["status"] == "confirmed"
          and chain["card_number"]["status"] == "confirmed"
          and chain["catalog_match"]["status"] == "confirmed"
          and collision_result.get("recommended_evidence_level") == "A"):
        level = "A"
    else:
        level = "C"

    confirmed = [step for step in CHAIN_STEPS
                 if chain[step]["status"] == "confirmed"]
    coverage = round(100 * len(confirmed) / len(CHAIN_STEPS))
    coverage_reason = (f"{len(confirmed)}/{len(CHAIN_STEPS)} dimensions independently "
                       f"confirmed: {', '.join(confirmed) or 'none'}. "
                       "Unchecked/unavailable providers affect coverage only, not prediction confidence.")
    prediction, prediction_factors = _provisional_confidence(
        level, chain, ident, collision_result, artwork_result)

    out = {
        "evidence_level": level,
        "evidence_level_meaning": LEVELS[level],
        "evidence_chain": chain,
        "evidence_coverage": coverage,
        "evidence_coverage_reason": coverage_reason,
        "provisional_prediction_confidence": prediction,
        "provisional_prediction_confidence_factors": prediction_factors,
        "collision_analysis": collision_result,
        "adversarial_validation": build_adversarial_validation(collision_result),
    }
    if level == "C":
        out["inference_explanation"] = build_inference_explanation(
            ident, merged_lines, collision_result)
    if level in ("D", "E"):
        out["failure_report"] = build_failure_report(
            ident, merged_lines, collision_result, chain)
    return out


def build_inference_explanation(ident, merged_lines, collision_result=None):
    number_read, via = ident.get("number_read"), ident.get("via")
    snippets = [line for line in merged_lines
                if re.search(r"\d", line) or
                (number_read and str(number_read)[:2] in line)][:6]
    why_failed = ("OCR read a number that is not a real catalog printing"
                  if ident.get("snapped") else
                  "OCR did not directly establish every field needed for an exact printing")
    collision_result = collision_result or {}
    competitors = collision_result.get("competing_candidates") or []
    if competitors:
        forcing = collision_result.get("reason", "competing candidates remain")
    elif ident.get("snapped"):
        forcing = (f"'{ident.get('number_read')}' was corrected to '{ident.get('number')}' "
                   "as the unique nearby real printing; collision search then ran")
    else:
        forcing = (f"the available fragments resolved via {via}; adversarial search: "
                   f"{collision_result.get('reason', 'not available')}")
    return {
        "original_ocr_text": snippets or merged_lines[:6],
        "why_ocr_failed": why_failed,
        "candidate_search_process": (f"via={via}; {len(ident.get('candidates') or [])} API "
                                     f"candidate(s); {collision_result.get('catalog_rows_examined', 0)} "
                                     "widened rows examined"),
        "why_only_one_candidate_remained": forcing,
        "remaining_uncertainty": ("directly read the missing distinguishing evidence before listing"
                                  if competitors else
                                  "identity still depends on inference rather than every field being read"),
    }


def build_failure_report(ident, merged_lines, collision_result=None,
                         evidence_chain=None):
    name, number = ident.get("name"), ident.get("number")
    collision_result = collision_result or {}
    evidence_chain = evidence_chain or {}
    catalog_status = (evidence_chain.get("catalog_match") or {}).get("status")
    catalog_gap = bool(name and number and catalog_status not in (
        "confirmed", "inferred"))
    if collision_result.get("collision_status") == "confirmed":
        missing = "distinguishing evidence between competing printings"
    elif catalog_gap:
        missing = "an exact catalog product matching the read name and number"
    elif name and not number:
        missing = "card number / exact printing"
    elif number and not name:
        missing = "card name"
    else:
        missing = "both name and number"
    has_text = any(re.search(r"[A-Za-z]{3,}", line) for line in merged_lines)
    has_digits = any(re.search(r"\d", line) for line in merged_lines)
    if collision_result.get("collision_status") == "confirmed":
        blocker = collision_result.get("reason")
    elif catalog_gap:
        blocker = (f"no exact API or local catalog product corroborates "
                   f"{name} #{number}; the footer may be misread or the local catalog incomplete")
    else:
        blocker = ("no readable text in this crop" if not has_text and not has_digits
                   else "text exists but no complete name/number evidence resolved")
    return {
        "missing_feature": missing,
        "would_another_image_angle_help": True,
        "would_different_ocr_pass_help": catalog_gap or not has_text or not has_digits,
        "would_removing_glare_help": True,
        "would_different_language_db_help": not ident.get("jp"),
        "would_scan_instead_of_photo_help": True,
        "blocking_evidence": blocker,
    }


# Failure Database ---------------------------------------------------------

_STRUCTURAL_GAP_ID = "STRUCTURAL-000"


def _structural_record():
    return {
        "problem": ("Four evidence dimensions are unimplemented (hp, ability, expansion_symbol, "
                    "holo_pattern); artwork is partial when a local reference exists"),
        "cause": "the pipeline remains primarily text/OCR-first",
        "current_solution": ("local perceptual-hash ArtworkProvider and honest not_checked stubs "
                             "for the other providers"),
        "future_solution": "add independent providers in response to measured collision failures",
        "status": "Open - artwork partially closed; four provider gaps remain",
    }


def _load_failures():
    if os.path.exists(FAILURES_JSON):
        with open(FAILURES_JSON, encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def _save_failures(database):
    os.makedirs(DATASET_DIR, exist_ok=True)
    with open(FAILURES_JSON, "w", encoding="utf-8") as handle:
        json.dump(database, handle, ensure_ascii=False, indent=1)
    _render_md(database)


def _card_key(ident):
    return f"{ident.get('name')}|{ident.get('number')}|{ident.get('query')}"


def _record_for(ident):
    level = ident.get("evidence_level")
    chain = ident.get("evidence_chain", {})
    collision_result = ident.get("collision_analysis", {})
    adversarial = ident.get("adversarial_validation", {})
    common = {
        "evidence_missing": "; ".join(collision_result.get("evidence_missing") or []) or "none recorded",
        "strongest_alternative": str(adversarial.get("strongest_alternative")),
        "regression_test_requirement": "required for the failure class when closed",
    }
    if level == "C":
        inference = ident.get("inference_explanation", {})
        return {
            "problem": f"{ident.get('name')} {ident.get('number')} - identity still uses inference",
            "cause": inference.get("why_ocr_failed", "unknown"),
            "current_solution": inference.get("why_only_one_candidate_remained", "catalog forcing"),
            "future_solution": "obtain direct evidence for the missing or collision-sensitive dimension",
            "status": "Pending - mitigated, not fully solved",
            **common,
        }
    if level == "B":
        return {
            "problem": f"{ident.get('name')} {ident.get('number')} - automated OCR required a human read",
            "cause": chain.get("card_number", {}).get("note", "OCR failure"),
            "current_solution": "manual human eye gate",
            "future_solution": "add targeted preprocessing/provider coverage for this failure pattern",
            "status": "Pending - manual path works; automated path incomplete",
            **common,
        }
    if level in ("D", "E"):
        report = ident.get("failure_report", {})
        helps = [key.replace("would_", "").replace("_", " ")
                 for key, value in report.items()
                 if key.startswith("would_") and value]
        return {
            "problem": (f"{ident.get('name') or '(unknown)'} "
                        f"{ident.get('number') or '(unknown)'} - "
                        f"{report.get('missing_feature', 'identity incomplete')}"),
            "cause": report.get("blocking_evidence", "unknown"),
            "current_solution": "none - result remains ambiguous/unknown",
            "future_solution": "; ".join(helps) or "obtain additional independent evidence",
            "status": "Open",
            **common,
        }
    return None


def log_failure(ident):
    """Idempotently persist every non-A result plus the structural gap."""
    database = _load_failures()
    database[_STRUCTURAL_GAP_ID] = _structural_record()
    record = _record_for(ident)
    if record:
        database[_card_key(ident)] = record
    _save_failures(database)


def rebuild_failures(idents):
    """Atomically rebuild the audited failure database from result objects."""
    database = {_STRUCTURAL_GAP_ID: _structural_record()}
    for ident in idents:
        record = _record_for(ident)
        if record:
            database[_card_key(ident)] = record
    _save_failures(database)


def _render_md(database):
    lines = ["# FAILURES.md - Failure Database", "",
             "Auto-generated by `evidence.py:log_failure()`. Do not hand-edit.",
             "Every non-Level-A identification produces an improvement record.",
             "", "---", ""]
    structural = database.get(_STRUCTURAL_GAP_ID)
    if structural:
        lines += [f"## {_STRUCTURAL_GAP_ID} - structural", ""]
        for key, value in structural.items():
            lines.append(f"**{key.replace('_', ' ').title()}:** {value}")
        lines += ["", "---", ""]
    others = {key: value for key, value in database.items()
              if key != _STRUCTURAL_GAP_ID}
    lines += [f"## Per-card records ({len(others)})", ""]
    for key, record in sorted(others.items()):
        lines.append(f"### {key}")
        for field, value in record.items():
            lines.append(f"- **{field.replace('_', ' ').title()}:** {value}")
        lines.append("")
    with open(FAILURES_MD, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
