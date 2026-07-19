"""Offline, fail-closed runner for the frozen identification corpus.

The runner measures the assets that actually exist.  It never turns an
unavailable, corrupt, or unsupported sample into a pass, and it keeps footer
micro-benchmarks separate from full-card identification.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
from unittest import mock


CORPUS_VERSION = "corpus-v1"
MANIFEST_SCHEMA = "identification-acceptance-manifest-v1"
REPORT_SCHEMA = "identification-acceptance-report-v1"
EXPECTED_FIELDS = ("name", "set", "number", "language", "finish", "variant")
BENCHMARK_TYPES = {
    "full-card": "full-card",
    "footer-ocr": "footer-crop",
    "synthetic-robustness": "synthetic",
    "dataset-image": "dataset-image",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The corpus manifest cannot be trusted or interpreted."""


class NetworkBlocked(RuntimeError):
    """A corpus evaluator attempted a live network operation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _resolve_inside(root: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ManifestError(f"{label} must be a non-empty relative path")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ManifestError(f"{label} escapes the corpus directory") from exc
    return candidate


def _require_object(record: dict, key: str, sample_id: str) -> dict:
    value = record.get(key)
    if not isinstance(value, dict):
        raise ManifestError(f"{sample_id}: {key} must be an object")
    return value


def _validate_record(record: object, line_number: int) -> dict:
    if not isinstance(record, dict):
        raise ManifestError(f"line {line_number}: record must be an object")
    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise ManifestError(f"line {line_number}: sample_id is required")
    if record.get("manifest_schema") != MANIFEST_SCHEMA:
        raise ManifestError(f"{sample_id}: unsupported manifest_schema")
    if record.get("corpus_version") != CORPUS_VERSION:
        raise ManifestError(f"{sample_id}: unsupported corpus_version")

    benchmark = record.get("benchmark")
    asset_type = record.get("asset_type")
    if benchmark not in BENCHMARK_TYPES:
        raise ManifestError(f"{sample_id}: unsupported benchmark {benchmark!r}")
    if BENCHMARK_TYPES[benchmark] != asset_type:
        raise ManifestError(
            f"{sample_id}: {asset_type!r} cannot enter {benchmark!r}; "
            "benchmark and asset type must remain separate")

    asset_path = record.get("asset_path")
    if not isinstance(asset_path, str) or not asset_path:
        raise ManifestError(f"{sample_id}: asset_path is required")
    checksum = record.get("sha256")
    if not isinstance(checksum, str) or not _SHA256_RE.fullmatch(checksum):
        raise ManifestError(f"{sample_id}: sha256 must be 64 lowercase hex digits")

    provenance = _require_object(record, "provenance", sample_id)
    for field in ("source_uri", "retrieval_date", "source_classification"):
        if not isinstance(provenance.get(field), str) or not provenance[field]:
            raise ManifestError(f"{sample_id}: provenance.{field} is required")

    retention = _require_object(record, "retention", sample_id)
    if retention.get("status") != "permitted":
        raise ManifestError(
            f"{sample_id}: executable corpus assets require permitted retention")
    if not retention.get("basis"):
        raise ManifestError(f"{sample_id}: retention.basis is required")

    truth = _require_object(record, "ground_truth", sample_id)
    if not isinstance(truth.get("authority"), list) or not truth["authority"]:
        raise ManifestError(f"{sample_id}: ground_truth.authority is required")
    if truth.get("confidence") not in ("high", "medium", "low"):
        raise ManifestError(f"{sample_id}: ground_truth.confidence is invalid")
    if truth.get("system_prediction_used") is not False:
        raise ManifestError(
            f"{sample_id}: system predictions cannot establish ground truth")
    if truth.get("listing_title_used") is not False:
        raise ManifestError(
            f"{sample_id}: listing titles alone cannot establish ground truth")

    expected = _require_object(record, "expected", sample_id)
    missing = [field for field in EXPECTED_FIELDS if field not in expected]
    if missing:
        raise ManifestError(f"{sample_id}: expected fields missing: {missing}")
    unknown = expected.get("unknown_fields")
    if not isinstance(unknown, list):
        raise ManifestError(f"{sample_id}: expected.unknown_fields must be a list")
    null_fields = sorted(field for field in EXPECTED_FIELDS
                         if expected.get(field) is None)
    if sorted(unknown) != null_fields:
        raise ManifestError(
            f"{sample_id}: unknown_fields must exactly name null expected fields")

    tags = record.get("difficulty_tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ManifestError(f"{sample_id}: difficulty_tags must be a string list")
    if not isinstance(record.get("known_failure_category"), str):
        raise ManifestError(f"{sample_id}: known_failure_category is required")

    replay = record.get("parser_replay")
    if replay is not None:
        if benchmark != "footer-ocr" or not isinstance(replay, dict):
            raise ManifestError(
                f"{sample_id}: parser_replay is only valid for footer-ocr records")
        for field in ("ocr_trace_path", "sha256", "json_path"):
            if not isinstance(replay.get(field), str) or not replay[field]:
                raise ManifestError(f"{sample_id}: parser_replay.{field} is required")
        if not _SHA256_RE.fullmatch(replay["sha256"]):
            raise ManifestError(
                f"{sample_id}: parser_replay.sha256 must be lowercase SHA-256")
    return record


def load_manifest(corpus_dir) -> list[dict]:
    """Load and validate manifest JSONL without inspecting asset bytes."""
    root = Path(corpus_dir).resolve()
    manifest_path = root / "manifest.jsonl"
    if not manifest_path.is_file():
        raise ManifestError(f"manifest not found: {manifest_path}")
    records = []
    seen = set()
    with manifest_path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ManifestError(
                    f"manifest line {line_number} is malformed JSON: {exc.msg}") from exc
            record = _validate_record(parsed, line_number)
            sample_id = record["sample_id"]
            if sample_id in seen:
                raise ManifestError(f"duplicate sample_id: {sample_id}")
            seen.add(sample_id)
            _resolve_inside(root, record["asset_path"],
                            f"{sample_id}.asset_path")
            replay = record.get("parser_replay")
            if replay:
                _resolve_inside(root, replay["ocr_trace_path"],
                                f"{sample_id}.parser_replay.ocr_trace_path")
            records.append(record)
    return records


def _protected_snapshot(repo_root: Path) -> dict[str, str]:
    """Hash production state the acceptance run is forbidden to mutate."""
    paths = []
    failures = repo_root / "FAILURES.md"
    if failures.is_file():
        paths.append(failures)
    for directory in ("dataset", "uploads", "data"):
        base = repo_root / directory
        if base.is_dir():
            paths.extend(path for path in base.rglob("*") if path.is_file())
    for pattern in ("*.sqlite", "*.db"):
        paths.extend(path for path in repo_root.glob(pattern) if path.is_file())
    result = {}
    for path in sorted(set(paths)):
        result[path.relative_to(repo_root).as_posix()] = _sha256(path)
    return result


class _NetworkBoundary:
    def __init__(self):
        self.attempts = []
        self._patches = []

    def _requests(self, *args, **kwargs):
        # A bound method is installed on Session.request, so Requests may
        # supply method/url as keywords without a Session positional value.
        method = kwargs.get("method") or (args[-2] if len(args) >= 2 else "?")
        url = kwargs.get("url") or (args[-1] if args else "?")
        self.attempts.append({"kind": "requests", "method": str(method),
                              "target": str(url)})
        raise NetworkBlocked(f"live HTTP blocked: {method} {url}")

    def _connect(self, *args, **kwargs):
        address = kwargs.get("address") or (args[-1] if args else "?")
        self.attempts.append({"kind": "socket", "method": "connect",
                              "target": repr(address)})
        raise NetworkBlocked(f"live socket blocked: {address!r}")

    def _connect_ex(self, *args, **kwargs):
        address = kwargs.get("address") or (args[-1] if args else "?")
        self.attempts.append({"kind": "socket", "method": "connect_ex",
                              "target": repr(address)})
        raise NetworkBlocked(f"live socket blocked: {address!r}")

    def __enter__(self):
        import requests
        self._patches = [
            mock.patch.object(requests.sessions.Session, "request",
                              self._requests),
            mock.patch.object(socket.socket, "connect", self._connect),
            mock.patch.object(socket.socket, "connect_ex", self._connect_ex),
        ]
        for patcher in self._patches:
            patcher.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self._patches):
            patcher.stop()
        return False


def _verify_image(path: Path) -> tuple[bool, str | None, list[int] | None]:
    try:
        from PIL import Image
        with Image.open(path) as image:
            dimensions = [int(image.width), int(image.height)]
            image.verify()
        with Image.open(path) as image:
            image.load()
        return True, None, dimensions
    except Exception as exc:
        return False, f"undecodable image: {type(exc).__name__}: {exc}", None


def _json_path(value, dotted: str):
    current = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted)
        current = current[part]
    return current


def _default_footer_evaluator(record: dict, asset_path: Path,
                              corpus_root: Path, temp_root: Path) -> dict:
    import valuator

    expected_number = record["expected"]["number"]
    cache_path = temp_root / f"{record['sample_id']}-ocr.sqlite"
    started = time.perf_counter()
    with mock.patch.object(valuator, "_OCR_CACHE_DB", str(cache_path)):
        ocr_started = time.perf_counter()
        lines = valuator.ocr_lines(str(asset_path))
        ocr_ms = (time.perf_counter() - ocr_started) * 1000
        observed_name, observed_number = valuator.guess_query(lines)
    total_ms = (time.perf_counter() - started) * 1000
    image_exact = bool(expected_number and observed_number
                       and valuator._norm_num(str(observed_number))
                       == valuator._norm_num(str(expected_number)))

    replay_result = {"executed": False, "exact_number": False,
                     "observed_number": None, "latency_ms": None}
    replay = record.get("parser_replay")
    if replay:
        trace_path = _resolve_inside(corpus_root, replay["ocr_trace_path"],
                                     f"{record['sample_id']}.parser_replay")
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        frozen_lines = _json_path(trace, replay["json_path"])
        if not isinstance(frozen_lines, list) \
                or not all(isinstance(line, str) for line in frozen_lines):
            raise ManifestError(
                f"{record['sample_id']}: frozen OCR trace is not a string list")
        replay_started = time.perf_counter()
        _, replay_number = valuator.guess_query(frozen_lines)
        replay_ms = (time.perf_counter() - replay_started) * 1000
        replay_result = {
            "executed": True,
            "exact_number": bool(replay_number and expected_number
                                 and valuator._norm_num(str(replay_number))
                                 == valuator._norm_num(str(expected_number))),
            "observed_number": replay_number,
            "latency_ms": round(replay_ms, 3),
            "input_line_count": len(frozen_lines),
        }

    return {
        "executed": True,
        "status": "passed" if image_exact else "failed",
        "image_ocr": {
            "executed": True,
            "exact_number": image_exact,
            "observed_name": observed_name or None,
            "observed_number": observed_number,
            "raw_lines": lines,
            "latency_ms": round(ocr_ms, 3),
            "cache": "isolated temporary cache; no production cache read",
        },
        "parser_replay": replay_result,
        "final_identification": {
            "executed": False,
            "reason": "footer-crop samples cannot enter the full-card benchmark",
        },
        "evidence": {
            "catalog_inference_used": False,
            "zero_inference_exact_number": image_exact,
            "level": None,
            "high_confidence": False,
        },
        "latency_ms": round(total_ms, 3),
    }


def _default_evaluator(record: dict, asset_path: Path, corpus_root: Path,
                       temp_root: Path) -> dict:
    if record["benchmark"] == "footer-ocr":
        return _default_footer_evaluator(
            record, asset_path, corpus_root, temp_root)
    raise ManifestError(
        f"{record['sample_id']}: no frozen offline full-card dependency bundle; "
        "refusing to report partial identification as full-card acceptance")


def _without_timing(value):
    if isinstance(value, dict):
        return {key: _without_timing(item) for key, item in sorted(value.items())
                if key not in ("latency_ms", "generated_at")}
    if isinstance(value, list):
        return [_without_timing(item) for item in value]
    return value


def _ratio(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "display": f"{numerator}/{denominator}",
        "representative_rate": None,
    }


def _build_metrics(records: list[dict], outcomes: list[dict]) -> dict:
    by_id = {record["sample_id"]: record for record in records}
    executed = [outcome for outcome in outcomes if outcome.get("executed")]
    full = [outcome for outcome in executed
            if by_id[outcome["sample_id"]]["benchmark"] == "full-card"]
    footer = [outcome for outcome in executed
              if by_id[outcome["sample_id"]]["benchmark"] == "footer-ocr"]
    synthetic = [outcome for outcome in executed
                 if by_id[outcome["sample_id"]]["benchmark"]
                 == "synthetic-robustness"]
    footer_exact = sum(bool(outcome.get("image_ocr", {}).get("exact_number"))
                       for outcome in footer)
    replayed = [outcome for outcome in footer
                if outcome.get("parser_replay", {}).get("executed")]
    replay_exact = sum(bool(outcome["parser_replay"].get("exact_number"))
                       for outcome in replayed)
    full_correct = sum(bool(outcome.get("final_identification", {})
                            .get("exact_printing_correct")) for outcome in full)
    full_identified = sum(bool(outcome.get("final_identification", {})
                               .get("identified")) for outcome in full)
    abstained = sum(bool(outcome.get("final_identification", {})
                         .get("abstained")) for outcome in full)
    high_fp = sum(bool(outcome.get("final_identification", {})
                       .get("high_confidence_false_positive")) for outcome in full)
    catalog_inferred = sum(bool(outcome.get("evidence", {})
                                .get("catalog_inference_used")) for outcome in executed)
    zero_inference = sum(bool(outcome.get("evidence", {})
                              .get("zero_inference_exact_number"))
                         for outcome in executed)
    raw_latencies = [{
        "sample_id": outcome["sample_id"],
        "benchmark": by_id[outcome["sample_id"]]["benchmark"],
        "total_latency_ms": outcome.get("latency_ms"),
        "image_ocr_latency_ms": outcome.get("image_ocr", {}).get("latency_ms"),
        "parser_replay_latency_ms": outcome.get("parser_replay", {})
                                     .get("latency_ms"),
    } for outcome in executed]
    return {
        "full_card": {
            "executed": len(full),
            "exact_printing_correct": _ratio(full_correct, len(full)),
            "exact_printing_precision": _ratio(full_correct, full_identified),
            "coverage": _ratio(full_identified, len(full)),
            "abstention": _ratio(abstained, len(full)),
            "high_confidence_false_positive": _ratio(high_fp, len(full)),
        },
        "footer_ocr": {
            "executed": len(footer),
            "exact_collector_number": _ratio(footer_exact, len(footer)),
            "frozen_parser_replay_exact": _ratio(replay_exact, len(replayed)),
            "full_card_identification_counted": 0,
        },
        "synthetic_robustness": {"executed": len(synthetic)},
        "evidence": {
            "catalog_inference_used": _ratio(catalog_inferred, len(executed)),
            "zero_inference_exact_number": _ratio(zero_inference, len(executed)),
            "f06_level_a_policy": "unresolved; measured, not changed",
        },
        "performance": {
            "sample_count": len(raw_latencies),
            "raw_per_sample_latencies": raw_latencies,
            "p50_ms": None,
            "p90_ms": None,
            "p95_ms": None,
            "percentile_note": "percentiles not meaningful at this sample size",
        },
        "hash_first": {
            "executed": False,
            "reason": "no retained full-card asset and no fingerprints.sqlite/catalog images",
        },
    }


def _git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            capture_output=True, text=True, timeout=10, check=True)
        return result.stdout.strip()
    except Exception:
        return None


def _source_inventory(corpus_root: Path) -> dict | None:
    path = corpus_root / "source-inventory.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"source inventory is malformed: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") \
            != "identification-acceptance-source-inventory-v1":
        raise ManifestError("source inventory schema is invalid")
    if not isinstance(data.get("summary"), dict) \
            or not isinstance(data.get("records"), list):
        raise ManifestError("source inventory summary/records are invalid")
    decisions = {}
    for record in data["records"]:
        if not isinstance(record, dict) or not isinstance(record.get("decision"), str):
            raise ManifestError("source inventory record is invalid")
        decision = record["decision"]
        decisions[decision] = decisions.get(decision, 0) + 1
    return {
        "path": "source-inventory.json",
        "sha256": _sha256(path),
        "summary": data["summary"],
        "decision_counts": decisions,
    }


def run_corpus(corpus_dir, *, repo_root=None, evaluator=None,
               generated_at=None, commit=None) -> dict:
    """Execute the frozen corpus in memory and return a versioned report."""
    corpus_root = Path(corpus_dir).resolve()
    repo = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
    manifest_path = corpus_root / "manifest.jsonl"
    records = load_manifest(corpus_root)
    source_inventory = _source_inventory(corpus_root)
    evaluator = evaluator or _default_evaluator
    generated_at = generated_at or dt.datetime.now(dt.timezone.utc).isoformat()
    commit = commit or _git_commit(repo)
    before = _protected_snapshot(repo)
    outcomes = []

    with tempfile.TemporaryDirectory(prefix="identification-corpus-") as temp_dir:
        temp_root = Path(temp_dir)
        with _NetworkBoundary() as network:
            for record in records:
                sample_id = record["sample_id"]
                base = {
                    "sample_id": sample_id,
                    "benchmark": record["benchmark"],
                    "asset_type": record["asset_type"],
                    "executed": False,
                    "status": "unavailable",
                    "counted_as_pass": False,
                }
                asset_path = _resolve_inside(
                    corpus_root, record["asset_path"], f"{sample_id}.asset_path")
                if not asset_path.is_file():
                    base["reason"] = "asset missing"
                    outcomes.append(base)
                    continue
                actual_hash = _sha256(asset_path)
                base["asset_sha256_actual"] = actual_hash
                if actual_hash != record["sha256"]:
                    base["reason"] = "asset checksum mismatch"
                    outcomes.append(base)
                    continue
                replay = record.get("parser_replay")
                if replay:
                    replay_path = _resolve_inside(
                        corpus_root, replay["ocr_trace_path"],
                        f"{sample_id}.parser_replay.ocr_trace_path")
                    if not replay_path.is_file():
                        base["reason"] = "parser replay trace missing"
                        outcomes.append(base)
                        continue
                    if _sha256(replay_path) != replay["sha256"]:
                        base["reason"] = "parser replay checksum mismatch"
                        outcomes.append(base)
                        continue
                decodable, decode_error, dimensions = _verify_image(asset_path)
                base["image_dimensions"] = dimensions
                if not decodable:
                    base["reason"] = decode_error
                    outcomes.append(base)
                    continue
                try:
                    measured = evaluator(record, asset_path, corpus_root, temp_root)
                    if not isinstance(measured, dict) or not measured.get("executed"):
                        raise ManifestError(
                            f"{sample_id}: evaluator did not report an execution")
                    outcome = {**base, **measured, "sample_id": sample_id,
                               "benchmark": record["benchmark"],
                               "asset_type": record["asset_type"]}
                    outcome["counted_as_pass"] = outcome.get("status") == "passed"
                    outcomes.append(outcome)
                except Exception as exc:
                    base["status"] = "error"
                    base["reason"] = f"{type(exc).__name__}: {exc}"
                    outcomes.append(base)
            network_attempts = copy.deepcopy(network.attempts)

    after = _protected_snapshot(repo)
    state_changes = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            state_changes.append({"path": key, "before": before.get(key),
                                  "after": after.get(key)})

    executed = sum(bool(outcome.get("executed")) for outcome in outcomes)
    passed = sum(outcome.get("status") == "passed" for outcome in outcomes)
    failed = sum(outcome.get("status") == "failed" for outcome in outcomes)
    unavailable = sum(outcome.get("status") == "unavailable" for outcome in outcomes)
    errors = sum(outcome.get("status") == "error" for outcome in outcomes)
    measurement_valid = bool(executed and not errors and not network_attempts
                             and not state_changes)
    acceptance_pass = bool(measurement_valid and not failed and not unavailable
                           and passed == executed)
    metrics = _build_metrics(records, outcomes)
    report = {
        "report_schema": REPORT_SCHEMA,
        "corpus_version": CORPUS_VERSION,
        "generated_at": generated_at,
        "evaluated_commit": commit,
        "manifest_sha256": _sha256(manifest_path),
        "asset_availability": {
            "manifest_records": len(records),
            "verified_and_executed": executed,
            "unavailable": unavailable,
            "errors": errors,
            "skipped": 0,
        },
        "source_inventory": source_inventory,
        "execution_accounting": {
            "executed": executed,
            "passed": passed,
            "failed": failed,
            "unavailable": unavailable,
            "errors": errors,
            "skipped": 0,
            "zero_executed_cases": executed == 0,
        },
        "measurement_valid": measurement_valid,
        "acceptance_pass": acceptance_pass,
        "sample_outcomes": outcomes,
        "metrics": metrics,
        "network": {
            "allowed": False,
            "attempt_count": len(network_attempts),
            "attempts": network_attempts,
            "boundary": "in-process Requests and socket connect/connect_ex",
        },
        "cache": {
            "production_cache_used": False,
            "ocr_cache": "per-run temporary directory",
        },
        "production_state": {
            "modified": bool(state_changes),
            "changes": state_changes,
            "protected_file_count": len(before),
        },
        "unresolved_policy_contradictions": [
            "F-06: Level A zero-inference wording conflicts with catalog-derived behavior; not resolved by this unit"
        ],
    }
    fingerprint_payload = {
        "report_schema": report["report_schema"],
        "corpus_version": report["corpus_version"],
        "manifest_sha256": report["manifest_sha256"],
        "source_inventory_sha256": ((report.get("source_inventory") or {})
                                    .get("sha256")),
        "execution_accounting": report["execution_accounting"],
        "sample_outcomes": _without_timing(report["sample_outcomes"]),
        "network_attempt_count": report["network"]["attempt_count"],
        "production_state_changes": report["production_state"]["changes"],
    }
    report["deterministic_evaluation_sha256"] = hashlib.sha256(
        _canonical_json(fingerprint_payload).encode("utf-8")).hexdigest()
    return report


def render_markdown(report: dict) -> str:
    account = report["execution_accounting"]
    full = report["metrics"]["full_card"]
    footer = report["metrics"]["footer_ocr"]
    evidence = report["metrics"]["evidence"]
    performance = report["metrics"]["performance"]
    lines = [
        "# Identification acceptance corpus v1",
        "",
        f"- Report schema: `{report['report_schema']}`",
        f"- Corpus version: `{report['corpus_version']}`",
        f"- Evaluated commit: `{report['evaluated_commit']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Manifest SHA-256: `{report['manifest_sha256']}`",
        f"- Deterministic evaluation SHA-256: `{report['deterministic_evaluation_sha256']}`",
        "",
        "## Execution accounting",
        "",
        f"- Manifest records: {report['asset_availability']['manifest_records']}",
        f"- Executed: {account['executed']}",
        f"- Passed: {account['passed']}",
        f"- Failed: {account['failed']}",
        f"- Unavailable: {account['unavailable']}",
        f"- Errors: {account['errors']}",
        f"- Skipped: {account['skipped']}",
        f"- Measurement valid: `{str(report['measurement_valid']).lower()}`",
        f"- Acceptance pass: `{str(report['acceptance_pass']).lower()}`",
        "",
        "Missing, changed, malformed, or undecodable assets are unavailable. "
        "They never count as passes.",
        "",
        "## Source inventory",
        "",
    ]
    inventory = report.get("source_inventory")
    if inventory:
        summary = inventory["summary"]
        lines += [
            f"- Inventory SHA-256: `{inventory['sha256']}`",
            "- Durable real full-card assets: "
            f"{summary['durable_real_full_card_assets']}",
            "- Durable real footer crops: "
            f"{summary['durable_real_footer_crop_assets']}",
            "- Historical card failure records without a durable asset: "
            f"{summary['historical_card_failure_records_without_durable_asset']}/"
            f"{summary['historical_card_failure_records']}",
            "- Blastoise eBay front/back pair: unavailable; retention/commit "
            "permission was not established, so no image or derivative was used.",
            "",
        ]
    else:
        lines += ["No source inventory file was supplied.", ""]
    lines += [
        "## Separated metrics",
        "",
        f"- Full-card samples executed: {full['executed']}",
        f"- Full-card exact printing: {full['exact_printing_correct']['display']}",
        f"- Full-card precision: {full['exact_printing_precision']['display']}",
        f"- Full-card coverage: {full['coverage']['display']}",
        f"- Full-card abstention: {full['abstention']['display']}",
        "- Full-card high-confidence false positives: "
        f"{full['high_confidence_false_positive']['display']}",
        f"- Footer-only samples executed: {footer['executed']}",
        "- Footer exact collector-number OCR: "
        f"{footer['exact_collector_number']['display']}",
        "- Frozen footer parser replay exact: "
        f"{footer['frozen_parser_replay_exact']['display']}",
        "- Footer samples counted as full-card successes: 0",
        "",
        "## Evidence and policy",
        "",
        "- Catalog inference used: "
        f"{evidence['catalog_inference_used']['display']}",
        "- Zero-inference exact number: "
        f"{evidence['zero_inference_exact_number']['display']}",
        "- F-06: unresolved and preserved for owner review.",
        "- HASH-FIRST executed: false; no retained full-card sample and no "
        "fingerprint/catalog-image assets exist.",
        "",
        "## Raw performance",
        "",
        f"{performance['percentile_note']}.",
        "",
    ]
    if performance["raw_per_sample_latencies"]:
        lines += ["| Sample | Benchmark | Total ms | OCR ms | Parser replay ms |",
                  "|---|---|---:|---:|---:|"]
        for sample in performance["raw_per_sample_latencies"]:
            lines.append(
                f"| `{sample['sample_id']}` | {sample['benchmark']} | "
                f"{sample['total_latency_ms']} | {sample['image_ocr_latency_ms']} | "
                f"{sample['parser_replay_latency_ms']} |")
    else:
        lines.append("No sample executed; no success or performance claim is made.")
    lines += [
        "",
        "## Sample outcomes",
        "",
    ]
    for outcome in report["sample_outcomes"]:
        lines.append(
            f"- `{outcome['sample_id']}`: status `{outcome['status']}`, "
            f"executed `{str(outcome.get('executed', False)).lower()}`, "
            f"counted as pass `{str(outcome.get('counted_as_pass', False)).lower()}`.")
        if outcome.get("reason"):
            lines.append(f"  Reason: {outcome['reason']}")
        if outcome.get("image_ocr"):
            lines.append(
                "  Image OCR observed number: "
                f"`{outcome['image_ocr'].get('observed_number')}`; exact: "
                f"`{str(outcome['image_ocr'].get('exact_number')).lower()}`.")
        if outcome.get("parser_replay", {}).get("executed"):
            lines.append(
                "  Frozen parser replay observed number: "
                f"`{outcome['parser_replay'].get('observed_number')}`; exact: "
                f"`{str(outcome['parser_replay'].get('exact_number')).lower()}`.")
    lines += [
        "",
        "## Isolation",
        "",
        f"- Network attempts: {report['network']['attempt_count']}",
        f"- Production state modified: `{str(report['production_state']['modified']).lower()}`",
        "- Production OCR cache used: `false`",
        "",
        "Exact counts above describe this corpus only. They are not population estimates.",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                     dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def write_report(report: dict, json_path, markdown_path) -> None:
    _atomic_write(Path(json_path), json.dumps(
        report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_write(Path(markdown_path), render_markdown(report))


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    default_corpus = here / "corpus-v1"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", default=str(default_corpus))
    parser.add_argument("--json-out")
    parser.add_argument("--markdown-out")
    parser.add_argument("--generated-at")
    parser.add_argument("--commit")
    args = parser.parse_args(argv)
    corpus_dir = Path(args.corpus_dir).resolve()
    json_out = Path(args.json_out) if args.json_out else (
        corpus_dir / "reports" / "identification-acceptance-corpus-v1.json")
    markdown_out = Path(args.markdown_out) if args.markdown_out else (
        corpus_dir / "reports" / "IDENTIFICATION-ACCEPTANCE-CORPUS-V1.md")
    try:
        report = run_corpus(
            corpus_dir, generated_at=args.generated_at, commit=args.commit)
        write_report(report, json_out, markdown_out)
    except ManifestError as exc:
        print(f"CORPUS INVALID: {exc}")
        return 1
    account = report["execution_accounting"]
    print("CORPUS MEASURED: "
          f"executed={account['executed']} passed={account['passed']} "
          f"failed={account['failed']} unavailable={account['unavailable']} "
          f"errors={account['errors']} acceptance_pass={report['acceptance_pass']}")
    return 0 if report["measurement_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
