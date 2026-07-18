"""Read-only perceptual-hash evidence from the partial visual catalog.

This provider can corroborate an identity already proposed by text evidence.
It deliberately never adds, replaces, or removes identification candidates:
different printings can reuse the same artwork.
"""
import os
import sqlite3
from contextlib import closing
from functools import lru_cache
from heapq import nsmallest

import numpy as np

from .artwork import _file_hashes, _norm_name, _norm_number
from .base import EvidenceProvider


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(HERE, "fingerprints.sqlite")
_PREPARED_ROWS = {}


def _hash_distance(left_phash, left_dhash, right_phash, right_dhash):
    """Weighted 64-bit Hamming distance, matching ArtworkProvider's weights."""
    return (.7 * (int(str(left_phash), 16) ^ int(str(right_phash), 16)).bit_count()
            + .3 * (int(str(left_dhash), 16) ^ int(str(right_dhash), 16)).bit_count())


def _db_token(path):
    token = []
    for candidate in (path, path + "-wal"):
        try:
            stat = os.stat(candidate)
            token.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            token.append((0, 0))
    return tuple(token)


@lru_cache(maxsize=4)
def _read_index(db_path, token):
    del token  # cache invalidation input; the query itself needs only the path
    uri = "file:" + os.path.abspath(db_path).replace("\\", "/") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=.25)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(fp)")}
        required = {"id", "name", "setname", "number", "visual_path",
                    "visual_phash", "visual_dhash"}
        if not required <= columns:
            return ()
        return tuple(conn.execute(
            "SELECT id, name, setname, number, visual_path, visual_phash, visual_dhash "
            "FROM fp WHERE visual_phash IS NOT NULL AND visual_dhash IS NOT NULL"
        ).fetchall())


@lru_cache(maxsize=4)
def _hash_arrays(db_path, token):
    """phash/dhash columns as numpy uint64 arrays, same rows/order as
    _read_index(db_path, token) — built once per index version so a
    candidate-free full-catalog scan (match_image) is a vectorized XOR +
    popcount instead of a 19k-row Python loop (was ~2-9s/call, dominated
    match_image() end-to-end and made probe_contours() net SLOWER than
    OCR-only despite skipping OCR on hits — see AGENT-RELAY.md 2026-07-18)."""
    rows = _read_index(db_path, token)
    if not rows:
        return np.array([], dtype=np.uint64), np.array([], dtype=np.uint64)
    phashes = np.array([int(str(r[5]), 16) for r in rows], dtype=np.uint64)
    dhashes = np.array([int(str(r[6]), 16) for r in rows], dtype=np.uint64)
    return phashes, dhashes


def _prepared_row(row):
    signature = (row[0], row[1], row[3], row[5], row[6])
    prepared = _PREPARED_ROWS.get(signature)
    if prepared is None:
        prepared = ((_norm_name(row[1]), _norm_number(row[3])),
                    int(str(row[5]), 16), int(str(row[6]), 16))
        _PREPARED_ROWS[signature] = prepared
    return prepared


class VisualCatalogProvider(EvidenceProvider):
    dimension = "artwork"

    def __init__(self, db_path=None, max_distance=9.0, nearest_slack=2.0):
        self.db_path = db_path or DB_PATH
        self.max_distance = float(max_distance)
        self.nearest_slack = float(nearest_slack)

    def _indexed_rows(self):
        # URI read-only mode is intentional: the background catalog builder
        # owns all writes, and a partially populated index is valid input.
        return _read_index(self.db_path, _db_token(self.db_path))

    def match_image(self, image_path):
        """Return a confident catalog match for an image, or ``None``.

        Uses the same max-distance and nearest-slack gates as ``verify``.
        """
        if not image_path or not os.path.exists(image_path):
            return None
        try:
            rows = self._indexed_rows()
            if not rows:
                return None
            token = _db_token(self.db_path)
            phashes, dhashes = _hash_arrays(self.db_path, token)
            stat = os.stat(image_path)
            input_phash, input_dhash = _file_hashes(
                image_path, stat.st_mtime_ns, stat.st_size)
            p_xor = phashes ^ np.uint64(int(str(input_phash), 16))
            d_xor = dhashes ^ np.uint64(int(str(input_dhash), 16))
            distances = (.7 * np.bitwise_count(p_xor).astype(np.float64)
                         + .3 * np.bitwise_count(d_xor).astype(np.float64))
        except (OSError, ValueError, TypeError, sqlite3.Error):
            return None
        k = min(2, len(distances))
        nearest_idx = np.argpartition(distances, k - 1)[:k]
        nearest_idx = nearest_idx[np.argsort(distances[nearest_idx])]
        best_distance = float(distances[nearest_idx[0]])
        next_distance = float(distances[nearest_idx[1]]) if k > 1 else float("inf")
        if (best_distance > self.max_distance
                or best_distance > next_distance - self.nearest_slack):
            return None
        row = rows[int(nearest_idx[0])]
        return {"id": row[0], "name": row[1], "set": row[2],
                "number": row[3], "visual_path": row[4],
                "distance": round(best_distance, 2)}

    @staticmethod
    def _candidate_keys(candidates):
        keyed = {}
        for candidate in candidates or []:
            key = (_norm_name(candidate.get("name")),
                   _norm_number(candidate.get("number")))
            if all(key):
                keyed.setdefault(key, candidate)
        return keyed

    def verify(self, image_path, candidates, context):
        result = {
            "provider": "VisualCatalogProvider:partial_perceptual_index",
            "dimension": self.dimension,
            "status": "not_checked",
            "match_score": 0.0,
            "hash_distance": None,
            "matched_reference": None,
            "matched_candidate": None,
            "matched_catalog": None,
            "nearest_matches": [],
            "indexed_rows": 0,
            "confidence_note": "",
        }
        if not image_path or not os.path.exists(image_path):
            result["confidence_note"] = "input image is unavailable; visual catalog was not checked"
            return result
        candidate_keys = self._candidate_keys(candidates)
        if not candidate_keys:
            result["confidence_note"] = (
                "no text-based name+number candidate exists; visual catalog cannot propose one")
            return result
        try:
            rows = self._indexed_rows()
        except (OSError, sqlite3.Error) as exc:
            result["confidence_note"] = f"visual catalog is temporarily unavailable: {exc}"
            return result
        result["indexed_rows"] = len(rows)
        if not rows:
            result["confidence_note"] = "visual catalog has no indexed hashes yet"
            return result

        prepared_rows = [(row, _prepared_row(row)) for row in rows]
        indexed_candidates = [(row, prepared) for row, prepared in prepared_rows
                              if prepared[0] in candidate_keys]
        if not indexed_candidates:
            result["confidence_note"] = (
                f"none of the text candidates is among the {len(rows)} currently indexed cards; "
                "partial-index coverage is not evidence against the identification")
            return result
        try:
            stat = os.stat(image_path)
            input_phash, input_dhash = _file_hashes(
                image_path, stat.st_mtime_ns, stat.st_size)
            input_phash_int = int(str(input_phash), 16)
            input_dhash_int = int(str(input_dhash), 16)
            scored = [(.7 * (input_phash_int ^ prepared[1]).bit_count()
                       + .3 * (input_dhash_int ^ prepared[2]).bit_count(),
                       row, prepared[0])
                      for row, prepared in prepared_rows]
        except (OSError, ValueError, TypeError) as exc:
            result["confidence_note"] = f"input or catalog hashes could not be compared: {exc}"
            return result

        nearest = nsmallest(5, scored, key=lambda item: item[0])
        result["nearest_matches"] = [
            {"distance": round(distance, 2), "id": row[0], "name": row[1],
             "set": row[2], "number": row[3]}
            for distance, row, _ in nearest]
        best_distance = nearest[0][0]
        candidate_distance, candidate_row, key = min(
            (distance, row, key) for distance, row, key in scored
            if key in candidate_keys)
        candidate = candidate_keys[key]
        result.update({
            "hash_distance": round(candidate_distance, 2),
            "match_score": round(max(0.0, 1.0 - candidate_distance / 64.0), 4),
            "matched_reference": candidate_row[4],
            "matched_candidate": candidate,
            "matched_catalog": {"id": candidate_row[0], "name": candidate_row[1],
                                "set": candidate_row[2], "number": candidate_row[3]},
        })
        globally_nearest = candidate_distance <= best_distance + self.nearest_slack
        if candidate_distance <= self.max_distance and globally_nearest:
            result["status"] = "matched"
            result["confidence_note"] = (
                f"partial visual index corroborated the text candidate at weighted hash distance "
                f"{candidate_distance:.1f} across {len(rows)} indexed cards; matching artwork "
                "does not distinguish reprints or override collision analysis")
        else:
            result["status"] = "no_match"
            reason = (f"above the {self.max_distance:.1f} threshold"
                      if candidate_distance > self.max_distance
                      else f"not within {self.nearest_slack:.1f} bits of the global nearest card")
            result["confidence_note"] = (
                f"text candidate's best indexed artwork was distance {candidate_distance:.1f}, "
                f"{reason}; no identity change was made")
        return result
