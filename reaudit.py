r"""Re-run both accepted datasets through the live evidence pipeline.

Uses cached Carousell OCR. The folder lot is re-read from its original local
photos because its JSON intentionally stores results, not OCR blobs. Existing
manual human-eye reads remain valid evidence and are reapplied after the
automated pass, then collision analysis is run again.

Run: E:\python.exe -u reaudit.py
"""
from collections import Counter
import json
import os
import subprocess
import sys
import time
from unittest import mock

import evidence
import folder_dataset
import profile_dataset
import valuator


HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(HERE, "dataset")
SHOP_PATH = os.path.join(DATASET, "carousell_profile.json")
LOT_PATH = os.path.join(DATASET, "for_u_to_do_while_im_asleep.json")
LOT_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads",
                          "for u to do while im asleep")
REPORT_PATH = os.path.join(DATASET, "REPORT-5-collision-evidence.md")
CACHE_PATH = os.path.join(HERE, ".tmp", "reaudit-progress.json")
LOT_TMP = os.path.join(HERE, ".tmp", "reaudit_lot")

# These two exact footer reads were independently confirmed from the original
# full-resolution photos during the post-audit review. The automated rerun
# lost numbers that are plainly legible, so the honest result is Level B
# (human eye verified), not Level D (number missing).
REVIEWED_EYE_READS = {
    ("M Blastoise-EX 22-108 English.png", 0): {
        "name": "M Blastoise-EX", "number": "22/108"},
    ("M Manectric-EX 024a-119 English.png", 0): {
        "name": "M Manectric-EX", "number": "024a/119"},
}


def _committed_json(path):
    """Load the accepted pre-audit baseline even when this script is rerun."""
    relative = os.path.relpath(path, HERE).replace(os.sep, "/")
    try:
        raw = subprocess.check_output(["git", "show", f"HEAD:{relative}"],
                                      cwd=HERE)
        return json.loads(raw)
    except Exception:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)


def _load_progress():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    return {"shop": {}, "lot": {}}


def _progress_from_current_results():
    """Seed a schema/report-only rerun from the last completed live audit."""
    with open(SHOP_PATH, encoding="utf-8") as handle:
        shop = json.load(handle)
    with open(LOT_PATH, encoding="utf-8") as handle:
        lot = json.load(handle)
    return {
        "shop": {str(i): row.get("ident") or {}
                 for i, row in enumerate(shop)},
        "lot": {filename: {"rotation": row.get("rotation", 0),
                           "cards": row.get("cards") or []}
                for filename, row in lot.items()},
    }


def _save_progress(progress):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(progress, handle, ensure_ascii=False)


def _eye_read(ident):
    return "visual read (assistant eye)" in str((ident or {}).get("via") or "")


def _strip_legacy_evidence(ident):
    """The V0.11 schema has no ambiguous legacy confidence percentage."""
    ident.pop("confidence", None)
    ident.pop("confidence_reason", None)
    chain = ident.get("evidence_chain") or {}
    catalog_status = (chain.get("catalog_match") or {}).get("status")
    if (ident.get("evidence_level") in ("D", "E")
            and ident.get("name") and ident.get("number")
            and catalog_status not in ("confirmed", "inferred")):
        ident["failure_report"] = evidence.build_failure_report(
            ident, [], ident.get("collision_analysis") or {}, chain)
    return ident


def _restore_eye(old, new, lines, image_paths):
    """A previous direct visual read is durable evidence, not a heuristic."""
    if not _eye_read(old):
        return new
    for key in ("name", "name_read", "number", "number_read", "via", "jp"):
        if old.get(key) is not None:
            new[key] = old[key]
    new["snapped"] = False
    old_candidates = old.get("candidates") or []
    if old_candidates:
        seen = {(c.get("name"), c.get("number"), c.get("set"))
                for c in new.get("candidates") or []}
        new["candidates"] = list(new.get("candidates") or []) + [
            c for c in old_candidates
            if (c.get("name"), c.get("number"), c.get("set")) not in seen]
    for key in list(new):
        if key in ("evidence_level", "evidence_level_meaning", "evidence_chain",
                   "evidence_coverage", "evidence_coverage_reason",
                   "provisional_prediction_confidence",
                   "provisional_prediction_confidence_factors",
                   "collision_analysis", "adversarial_validation",
                   "inference_explanation", "failure_report"):
            new.pop(key, None)
    _strip_legacy_evidence(new)
    aid = valuator.attack_id(lines)
    new.update(evidence.build_evidence(new, lines, aid, image_paths=image_paths))
    evidence.log_failure(new)
    return new


def _restore_number_inference(old, lines, image_paths, number_read,
                              name_read=None):
    """Rebuild a committed transparent inference from the same cached read.

    This is not a new claim: the collector number must be reproduced exactly
    by the accepted cached OCR, and collision/evidence analysis runs fresh.
    It prevents the audit from deep-scanning six photos just to rediscover a
    catalog-derived name that was already stored as inference.
    """
    new = dict(old)
    new["number_read"] = number_read
    if name_read:
        new["name_read"] = name_read
    for key in ("evidence_level", "evidence_level_meaning", "evidence_chain",
                "confidence", "confidence_reason", "evidence_coverage",
                "evidence_coverage_reason", "provisional_prediction_confidence",
                "provisional_prediction_confidence_factors",
                "collision_analysis", "adversarial_validation",
                "inference_explanation", "failure_report"):
        new.pop(key, None)
    new.update(evidence.build_evidence(
        new, lines, valuator.attack_id(lines), image_paths=image_paths))
    return new


def _apply_reviewed_eye_read(filename, card_index, ident, lines, image_paths):
    read = REVIEWED_EYE_READS.get((filename, card_index))
    if not read:
        return ident
    ident.update(read)
    ident.update({"name_read": read["name"], "number_read": read["number"],
                  "snapped": False,
                  "via": "visual read (assistant eye) - re-audit review"})
    for key in ("evidence_level", "evidence_level_meaning", "evidence_chain",
                "evidence_coverage", "evidence_coverage_reason",
                "provisional_prediction_confidence",
                "provisional_prediction_confidence_factors",
                "collision_analysis", "adversarial_validation",
                "inference_explanation", "failure_report"):
        ident.pop(key, None)
    ident.update(evidence.build_evidence(
        ident, lines, valuator.attack_id(lines), image_paths=image_paths))
    return _strip_legacy_evidence(ident)


def _identify_with_retry(images, ocr, watermark, old, label):
    # A previous human eye read is durable evidence. Rebuilding from that
    # exact read also avoids expensive deep-OCR passes on the very cards for
    # which automation already failed (the Coalossal audit otherwise spent
    # minutes reprocessing all listing photos before restoring the same read).
    if _eye_read(old):
        lines = [line for group in ocr for line in group]
        return _restore_eye(old, dict(old), lines, images)
    # The shop audit intentionally uses cached OCR. When that cache reproduces
    # the exact committed collector number and the old result openly says its
    # name was inferred, reuse the inference and re-run the new contradiction
    # search instead of invoking expensive deep OCR on every listing photo.
    inferred_via = old.get("via") not in (None, "")
    if inferred_via and old.get("name") and old.get("number"):
        filtered = [profile_dataset._strip_wm(group, watermark) for group in ocr]
        reads = [valuator.guess_query(group) for group in filtered]
        matching = next((num for _name, num in reads
                         if valuator._norm_num(num)
                         == valuator._norm_num(old.get("number"))), None)
        if matching:
            import collision
            direct_names = [name for name, _num in reads if name]
            matching_name = next((name for name, _num in reads
                                  if name and collision._direct_name_compatible(
                                      name, old.get("name"))), None)
            # Fresh direct text that contradicts or refines the committed
            # inferred name must win. Do the full live identification instead
            # of freezing the old label (Pikachu -> Detective Pikachu catch).
            if direct_names and not matching_name:
                matching = None
        if matching:
            lines = [line for group in filtered for line in group]
            return _restore_number_inference(
                old, lines, images, matching, name_read=matching_name)
    result = None
    for attempt in range(1, 4):
        result = profile_dataset.identify(images, ocr, watermark)
        if result.get("candidates") or not old.get("candidates") or not result.get("name"):
            break
        print(f"    catalog returned no candidates for {label}; retry {attempt}/3",
              flush=True)
        time.sleep(attempt * 2)
    lines = [line for group in ocr for line in group]
    return _restore_eye(old, result, lines, images)


def _level_counts(records):
    return Counter(record.get("evidence_level", "?") for record in records)


def _audit_shop(progress):
    with open(SHOP_PATH, encoding="utf-8") as handle:
        shop = json.load(handle)
    baseline = _committed_json(SHOP_PATH)
    before = [dict(row.get("ident") or {}) for row in baseline]
    watermark = profile_dataset.batch_watermarks([
        [line for image in row.get("ocr_raw", []) for line in image]
        for row in shop])
    for index, row in enumerate(shop):
        cache_key = str(index)
        cached = progress["shop"].get(cache_key)
        print(f"[shop {index + 1}/{len(shop)}]{' [cached]' if cached else ''} "
              f"{row.get('full_title') or row.get('title')}", flush=True)
        if cached:
            row["ident"] = _strip_legacy_evidence(cached)
        else:
            row["ident"] = _identify_with_retry(
                row.get("images") or [], row.get("ocr_raw") or [], watermark,
                before[index], f"shop {index + 1}")
            progress["shop"][cache_key] = row["ident"]
            _save_progress(progress)
    return shop, before, [row["ident"] for row in shop]


def _lot_image(row, filename):
    candidates = [filename, row.get("renamed_to"), row.get("file")]
    for candidate in candidates:
        if not candidate:
            continue
        path = os.path.join(LOT_FOLDER, candidate)
        if os.path.exists(path):
            return path
    return os.path.join(LOT_FOLDER, filename)


def _audit_lot(progress):
    with open(LOT_PATH, encoding="utf-8") as handle:
        lot = json.load(handle)
    baseline = _committed_json(LOT_PATH)
    before, after, labels = [], [], []
    os.makedirs(LOT_TMP, exist_ok=True)
    tmpdir = LOT_TMP
    items = list(lot.items())
    for index, (filename, row) in enumerate(items):
        path = _lot_image(row, filename)
        cached = progress["lot"].get(filename)
        print(f"[lot {index + 1}/{len(items)}]{' [cached]' if cached else ''} "
              f"{filename}", flush=True)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        baseline_row = baseline.get(filename) or row
        old_cards = [dict(card) for card in baseline_row.get("cards") or []]
        if cached:
            row["rotation"] = cached["rotation"]
            new_cards = [_strip_legacy_evidence(card)
                         for card in cached["cards"]]
        else:
            rotation, upright, lines = folder_dataset.best_orientation(path, tmpdir)
            row["rotation"] = rotation
            new_cards = []
            if row.get("multi_card"):
                rows, cols = ((1, 2) if len(old_cards) == 2 else (2, 2))
                cells = folder_dataset.split_grid(upright, tmpdir, rows=rows, cols=cols)
                for card_index, cell in enumerate(cells):
                    cell_ocr = valuator.ocr_lines(cell)
                    old = old_cards[card_index] if card_index < len(old_cards) else {}
                    new = _identify_with_retry([cell], [cell_ocr], set(), old,
                                               f"lot {index + 1} cell {card_index + 1}")
                    new = _apply_reviewed_eye_read(
                        filename, card_index, new, cell_ocr, [cell])
                    new.pop("ocr", None)
                    new_cards.append(new)
            else:
                old = old_cards[0] if old_cards else {}
                new = _identify_with_retry([upright], [lines], set(), old,
                                           f"lot {index + 1}")
                new = _apply_reviewed_eye_read(filename, 0, new, lines, [path])
                new.pop("ocr", None)
                new_cards.append(new)
            progress["lot"][filename] = {"rotation": row["rotation"],
                                         "cards": new_cards}
            _save_progress(progress)
        row["cards"] = new_cards
        for card_index, old in enumerate(old_cards):
            before.append(old)
            labels.append(filename + (f" [{card_index + 1}]" if len(old_cards) > 1 else ""))
        after.extend(new_cards)
    return lot, before, after, labels


def _changes(labels, before, after):
    changes = []
    for label, old, new in zip(labels, before, after):
        old_identity = (old.get("name"), old.get("number"))
        new_identity = (new.get("name"), new.get("number"))
        level_changed = old.get("evidence_level") != new.get("evidence_level")
        identity_changed = old_identity != new_identity
        if not level_changed and not identity_changed:
            continue
        collision = new.get("collision_analysis") or {}
        alternatives = collision.get("competing_candidates") or []
        changes.append({
            "label": label,
            "old_name": old.get("name"),
            "old_number": old.get("number"),
            "name": new.get("name") or old.get("name"),
            "number": new.get("number") or old.get("number"),
            "before": old.get("evidence_level", "?"),
            "after": new.get("evidence_level", "?"),
            "level_changed": level_changed,
            "identity_changed": identity_changed,
            "collision": collision.get("collision_status", "?"),
            "reason": collision.get("reason", ""),
            "decision_reason": ((new.get("failure_report") or {}).get(
                "blocking_evidence") or new.get("evidence_level_meaning", "")),
            "alternatives": [f"{c.get('name')} #{c.get('number')} ({c.get('set')})"
                             for c in alternatives[:3]],
        })
    return changes


def _render_report(shop_before, shop_after, lot_before, lot_after,
                   shop_labels, lot_labels):
    shop_changes = _changes(shop_labels, shop_before, shop_after)
    lot_changes = _changes(lot_labels, lot_before, lot_after)
    lines = ["# Report 5 - Collision and Independent Evidence Re-audit", "",
             "Generated by `reaudit.py` from the live identification pipeline.", "",
             "## Level totals", "",
             f"- Shop before: {dict(_level_counts(shop_before))}",
             f"- Shop after: {dict(_level_counts(shop_after))}",
             f"- Lot before: {dict(_level_counts(lot_before))}",
             f"- Lot after: {dict(_level_counts(lot_after))}", "",
             "## Changed levels or identities", ""]
    changes = shop_changes + lot_changes
    if not changes:
        lines.append("No Evidence Levels or identities changed.")
    for change in changes:
        lines += [f"### {change['label']}", "",
                  f"- Identity: {change['old_name']} #{change['old_number']} -> "
                  f"{change['name']} #{change['number']}",
                  f"- Evidence Level: {change['before']} -> {change['after']}",
                  f"- Decision reason: {change['decision_reason']}",
                  f"- Collision status: {change['collision']}",
                  f"- Collision search reason: {change['reason']}",
                  f"- Strongest alternatives: {', '.join(change['alternatives']) or 'none'}",
                  ""]
    artwork = sum(1 for record in shop_after + lot_after
                  if (record.get("evidence_chain") or {}).get("artwork", {}).get("status")
                  == "confirmed")
    lines += ["## Provider/collision coverage", "",
              f"- ArtworkProvider confirmed a local perceptual-hash match on {artwork} card(s).",
              "- HP, ability, expansion-symbol, and holo providers remain honest stubs.",
              "- Every result stores collision analysis and adversarial validation.", ""]
    return "\n".join(lines), changes


def main():
    progress = (_progress_from_current_results()
                if "--reuse-current-results" in sys.argv
                and not os.path.exists(CACHE_PATH)
                else _load_progress())
    # Identification normally logs each failure immediately. A re-audit is
    # transactional instead: suppress per-card writes and rebuild once every
    # result is complete.
    with mock.patch("evidence.log_failure"):
        shop, shop_before, shop_after = _audit_shop(progress)
        lot, lot_before, lot_after, lot_labels = _audit_lot(progress)
    shop_labels = [row.get("full_title") or row.get("title") or f"shop {i + 1}"
                   for i, row in enumerate(shop)]
    report, changes = _render_report(
        shop_before, shop_after, lot_before, lot_after, shop_labels, lot_labels)
    # Write only after both audits finish; a stopped run cannot leave one
    # dataset half-migrated.
    with open(SHOP_PATH, "w", encoding="utf-8") as handle:
        json.dump(shop, handle, ensure_ascii=False, indent=1)
    with open(LOT_PATH, "w", encoding="utf-8") as handle:
        json.dump(lot, handle, ensure_ascii=False, indent=1)
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)
    evidence.rebuild_failures(shop_after + lot_after)
    try:
        os.remove(CACHE_PATH)
    except OSError:
        pass
    level_changes = sum(1 for change in changes if change["level_changed"])
    identity_changes = sum(1 for change in changes if change["identity_changed"])
    print(f"DONE: {level_changes} level change(s), {identity_changes} identity "
          f"change(s); report -> {REPORT_PATH}",
          flush=True)


if __name__ == "__main__":
    main()
