"""Checkpointed evaluation of an unlabeled image batch through production code.

The adapter composes the existing ``folder_dataset`` preprocessing/layout
functions with ``profile_dataset.identify``. It never uses a source filename as
evidence and never turns a pipeline prediction into ground truth.

The app route and folder CLI still duplicate some layout orchestration. This
runner deliberately reuses their existing predicates and functions rather than
adding a new image heuristic; that pre-existing duplication is reportable
architecture debt, not something to conceal inside this evaluation.
"""
import argparse
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

import evidence
import folder_dataset
import profile_dataset
import valuator


SCHEMA = "unlabeled-production-evaluation-v1"
TERMINAL_STATUSES = {"processed", "processing_error",
                     "unsupported_or_corrupt"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_jsonl(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                       start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return records


def validate_checkpoint(records):
    seen = set()
    for record in records:
        digest = record.get("source_hash")
        if not digest or digest in seen:
            raise ValueError(f"duplicate or missing source_hash in checkpoint: {digest}")
        seen.add(digest)
        if record.get("status") not in TERMINAL_STATUSES:
            raise ValueError(f"non-terminal checkpoint status for {digest}")
    return seen


def configure_local_state(workspace):
    """Keep failure-ledger side effects local without altering identification."""
    state_dir = Path(workspace) / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    evidence.FAILURES_JSON = str(state_dir / "failures.json")
    evidence.FAILURES_MD = str(state_dir / "FAILURES.md")


def _layout(path, crop_dir):
    """Use existing production predicates/functions, never filename hints."""
    rotation, oriented_path, whole_ocr = folder_dataset.best_orientation(
        path, str(crop_dir))
    n_names = len(folder_dataset.distinct_names(whole_ocr))
    n_numbers = folder_dataset.distinct_collector_fractions(whole_ocr)
    with Image.open(oriented_path) as image:
        width, height = image.size

    pair = n_names == 2 and width > height
    named_multi = not pair and n_names >= 3
    grid_worth_trying = (not pair and n_names < 3
                         and folder_dataset.should_probe_grid(
                             width, height, n_names, n_numbers))
    contour_worth_trying = (not pair and (
        named_multi
        or (n_names < 3
            and (grid_worth_trying or min(width, height) >= 900))))

    cells, cell_ocr = [], []
    if contour_worth_trying:
        cells, cell_ocr = folder_dataset.probe_contours(
            oriented_path, str(crop_dir))
    if cells:
        mode = "contours"
    elif pair:
        mode = "pair_grid_1x2"
        cells = folder_dataset.split_grid(oriented_path, str(crop_dir),
                                          rows=1, cols=2)
        cell_ocr = [valuator.ocr_lines(cell) for cell in cells]
    elif named_multi:
        mode = "named_multi_fallback_grid_2x2"
        cells = folder_dataset.split_grid(oriented_path, str(crop_dir),
                                          rows=2, cols=2)
        cell_ocr = [valuator.ocr_lines(cell) for cell in cells]
    elif grid_worth_trying:
        cells, cell_ocr = folder_dataset.probe_grid(
            oriented_path, str(crop_dir))
        mode = "bounded_grid_2x2" if cells else "single"
    else:
        mode = "single"

    if not cells:
        cells, cell_ocr = [oriented_path], [whole_ocr]
    return {
        "rotation": rotation,
        "oriented_path": oriented_path,
        "whole_image_ocr_line_count": len(whole_ocr),
        "distinct_name_signal_count": n_names,
        "distinct_collector_fraction_count": len(n_numbers),
        "image_width": width,
        "image_height": height,
        "pair_signal": pair,
        "named_multi_signal": named_multi,
        "grid_worth_trying": grid_worth_trying,
        "contour_worth_trying": contour_worth_trying,
        "mode": mode,
        "cells": cells,
        "cell_ocr": cell_ocr,
    }


def _safe_candidate(candidate):
    if not isinstance(candidate, dict):
        return None
    return {key: candidate.get(key) for key in
            ("pid", "name", "set", "number", "line")}


def _detected_set(result):
    selected = (result.get("collision_analysis") or {}).get("selected_candidate")
    if isinstance(selected, dict) and selected.get("set"):
        return selected.get("set")
    exact_sets = {
        candidate.get("set") for candidate in result.get("candidates") or []
        if candidate.get("set")
        and candidate.get("name")
        and result.get("name")
        and candidate.get("number")
        and result.get("number")
        and candidate["name"].split(" - ")[0].strip().casefold()
        == str(result["name"]).strip().casefold()
        and valuator._norm_num(candidate["number"])
        == valuator._norm_num(str(result["number"]))
    }
    return next(iter(exact_sets)) if len(exact_sets) == 1 else None


def _abstention(result):
    failure = result.get("failure_report") or {}
    collision = result.get("collision_analysis") or {}
    missing = failure.get("missing_feature")
    if not missing:
        if not result.get("name") and not result.get("number"):
            missing = "both name and exact printing"
        elif not result.get("name"):
            missing = "card name"
        elif not result.get("number"):
            missing = "card number / exact printing"
        else:
            missing = "independent evidence resolving the remaining ambiguity"
    blocker = failure.get("blocking_evidence") or collision.get("reason") or \
        "the production evidence chain did not establish an exact printing"
    blocker_lower = str(blocker).lower()
    if collision.get("collision_status") == "confirmed":
        cause = "collision"
    elif "catalog" in blocker_lower or "product" in blocker_lower:
        cause = "catalog_coverage"
    elif "readable text" in blocker_lower or "ocr" in blocker_lower:
        cause = "ocr_or_image_quality"
    elif result.get("jp") and not result.get("name"):
        cause = "language_or_ocr"
    else:
        cause = "insufficient_evidence"
    remedies = [key.removeprefix("would_").replace("_", " ")
                for key, value in failure.items()
                if key.startswith("would_") and value]
    observed = {
        "name_fragment": result.get("name_read"),
        "number_fragment": result.get("number_read"),
        "pipeline_name_candidate": result.get("name"),
        "pipeline_number_candidate": result.get("number"),
        "via": result.get("via"),
    }
    return {
        "observed": observed,
        "missing_distinguishing_evidence": missing,
        "remaining_candidates": [_safe_candidate(candidate)
                                 for candidate in (result.get("candidates") or [])[:3]],
        "cause_category": cause,
        "blocking_evidence": blocker,
        "what_would_resolve_it": remedies or [
            "a clearer front/footer image or Yujin's exact printing confirmation"],
        "limitation_owner": ("evidence" if cause == "ocr_or_image_quality"
                             else "system_or_catalog" if cause == "catalog_coverage"
                             else "mixed"),
    }


def _detection_record(source, index, crop_path, ocr_lines, result):
    level = result.get("evidence_level")
    collision = result.get("collision_analysis") or {}
    complete = bool(result.get("name") and result.get("number"))
    unresolved_collision = collision.get("collision_status") == "confirmed"
    candidate_for_review = complete and level in ("A", "B", "C") \
        and not unresolved_collision
    external_status = ("unverified_candidate_pending_Yujin"
                       if candidate_for_review
                       else "abstained_pending_better_evidence")
    chain = result.get("evidence_chain") or {}
    support = {
        key: value for key, value in chain.items()
        if isinstance(value, dict) and value.get("status") != "not_checked"
    }
    return {
        "status": "processed",
        "source_hash": source["sha256"],
        "source_basename": source["basename"],
        "source_index": source["source_index"],
        "detection_index": index,
        "crop_hash": sha256(crop_path),
        "crop_local_path": str(Path(crop_path).resolve()),
        "pipeline_entrypoint": "profile_dataset.identify",
        "detected_name": result.get("name"),
        "detected_number": result.get("number"),
        "detected_set": _detected_set(result),
        "detected_language": "Japanese" if result.get("jp") else None,
        "language_evidence_status": (chain.get("language") or {}).get("status",
                                                                          "not_checked"),
        "internal_evidence_level": level,
        "evidence_coverage": result.get("evidence_coverage"),
        "external_review_status": external_status,
        "supporting_evidence": support,
        "strongest_competing_candidate": _safe_candidate(
            (result.get("adversarial_validation") or {}).get(
                "strongest_alternative")),
        "candidate_count": len(result.get("candidates") or []),
        "candidates": [_safe_candidate(candidate)
                       for candidate in (result.get("candidates") or [])],
        "collision_status": collision.get("collision_status", "not_checked"),
        "identification_via": result.get("via"),
        "provisional_prediction_confidence": result.get(
            "provisional_prediction_confidence"),
        "ocr_line_count": len(ocr_lines),
        "abstention": None if candidate_for_review else _abstention(result),
        "contract_violations": (["automated_batch_emitted_level_B"]
                                if level == "B" else []),
    }


def process_source(source, workspace):
    started = time.perf_counter()
    started_at = utc_now()
    source_path = Path(source["local_copy_path"])
    crop_dir = Path(workspace) / "crops" / source["sha256"]
    crop_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "schema": SCHEMA,
        "source_hash": source["sha256"],
        "source_basename": source["basename"],
        "source_index": source["source_index"],
        "pipeline_entrypoint": "profile_dataset.identify",
        "started_at": started_at,
    }
    if source.get("decode_error"):
        return {
            **common,
            "status": "unsupported_or_corrupt",
            "error": source["decode_error"],
            "detections": [],
            "completed_at": utc_now(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    try:
        layout = _layout(str(source_path), crop_dir)
        detections = []
        for index, (cell, lines) in enumerate(
                zip(layout.pop("cells"), layout.pop("cell_ocr")), start=1):
            result = profile_dataset.identify([cell], [lines], set())
            detections.append(_detection_record(source, index, cell, lines, result))
        return {
            **common,
            "status": "processed",
            "error": None,
            "layout": layout,
            "detections": detections,
            "completed_at": utc_now(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    except Exception as exc:
        return {
            **common,
            "status": "processing_error",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "detections": [],
            "completed_at": utc_now(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


def rebuild_review_queue(checkpoint_records, path):
    entries = []
    for record in checkpoint_records:
        for detection in record.get("detections") or []:
            if detection.get("external_review_status") != \
                    "unverified_candidate_pending_Yujin":
                continue
            name = detection.get("detected_name") or "the proposed card"
            number = detection.get("detected_number") or "unread number"
            card_set = detection.get("detected_set") or "unverified set"
            entries.append({
                "source_hash": detection["source_hash"],
                "crop_hash": detection["crop_hash"],
                "crop_local_path": detection["crop_local_path"],
                "proposed_identification": {
                    "name": detection.get("detected_name"),
                    "number": detection.get("detected_number"),
                    "set": detection.get("detected_set"),
                    "language": detection.get("detected_language"),
                },
                "internal_evidence_level": detection.get(
                    "internal_evidence_level"),
                "supporting_evidence": detection.get("supporting_evidence"),
                "strongest_competing_candidate": detection.get(
                    "strongest_competing_candidate"),
                "review_state": "pending_Yujin",
                "question_for_Yujin": (
                    f"Does this crop show {name} #{number} from {card_set}? "
                    "If not, what exact card name and printed collector number do you see?"),
            })
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for entry in entries:
            stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)
    return entries


def summary_counts(records):
    detections = [detection for record in records
                  for detection in record.get("detections") or []]
    statuses = Counter(record.get("status") for record in records)
    levels = Counter(detection.get("internal_evidence_level") or "not_checked"
                     for detection in detections)
    coverage = Counter(str(detection.get("evidence_coverage"))
                       if detection.get("evidence_coverage") is not None
                       else "not_checked" for detection in detections)
    awaiting = sum(detection.get("external_review_status")
                   == "unverified_candidate_pending_Yujin"
                   for detection in detections)
    violations = sum(len(detection.get("contract_violations") or [])
                     for detection in detections)
    collisions = sum(detection.get("collision_status") == "confirmed"
                     for detection in detections)
    catalog_gaps = sum((detection.get("abstention") or {}).get("cause_category")
                       == "catalog_coverage" for detection in detections)
    return {
        "sources": len(records),
        "source_statuses": dict(sorted(statuses.items())),
        "detections": len(detections),
        "awaiting_Yujin": awaiting,
        "abstentions": len(detections) - awaiting,
        "evidence_levels": dict(sorted(levels.items())),
        "evidence_coverage": dict(sorted(coverage.items())),
        "confirmed_collisions": collisions,
        "catalog_coverage_gaps": catalog_gaps,
        "contract_violations": violations,
    }


def run(args):
    workspace = Path(args.workspace).resolve()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    checkpoint = workspace / "checkpoints" / "results.jsonl"
    review_queue = workspace / "review-queue.jsonl"
    records = load_jsonl(checkpoint)
    completed = validate_checkpoint(records)
    configure_local_state(workspace)
    processed_now = 0
    for source in manifest["files"]:
        if source["sha256"] in completed:
            continue
        if args.max_new is not None and processed_now >= args.max_new:
            break
        print(f"[{source['source_index']}/29] processing {source['sha256'][:12]}",
              flush=True)
        record = process_source(source, workspace)
        append_jsonl(checkpoint, record)
        records.append(record)
        completed.add(source["sha256"])
        processed_now += 1
        print(json.dumps({
            "source_index": source["source_index"],
            "status": record["status"],
            "detections": len(record.get("detections") or []),
            "elapsed_seconds": record["elapsed_seconds"],
            "running": summary_counts(records),
        }, ensure_ascii=False), flush=True)
    entries = rebuild_review_queue(records, review_queue)
    print(json.dumps({
        "checkpoint": str(checkpoint),
        "review_queue": str(review_queue),
        "processed_now": processed_now,
        "review_entries": len(entries),
        "totals": summary_counts(records),
    }, indent=2, ensure_ascii=False))


def status(args):
    records = load_jsonl(Path(args.workspace) / "checkpoints" / "results.jsonl")
    validate_checkpoint(records)
    print(json.dumps(summary_counts(records), indent=2, ensure_ascii=False))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--manifest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--max-new", type=int)
    subparsers.add_parser("status")
    args = parser.parse_args()
    if args.command == "run" and not args.manifest:
        parser.error("--manifest is required for run")
    return args


if __name__ == "__main__":
    parsed = parse_args()
    if parsed.command == "run":
        run(parsed)
    else:
        status(parsed)
