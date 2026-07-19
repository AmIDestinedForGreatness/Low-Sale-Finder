"""Backfill missing visual hashes from exact-number TCGplayer products.

The primary visual-catalog builder uses images.pokemontcg.io, whose M-era
images currently return 404.  The fingerprint rows still contain authoritative
name/set/number metadata, so this companion pass performs a targeted
``valuator.search_candidates`` lookup for each missing row and downloads a
TCGplayer product image only when its collector number is an exact normalized
match.  No exact match means no database change.

Usage:
    E:\\python.exe backfill_visual_catalog_tcgplayer.py [--limit N]
        [--set-id me2pt5] [--delay 0.08]

The pass is resumable: rows with an existing visual phash are not selected.
"""
import argparse
import os
import sqlite3
import time

import requests

import network_safety
import valuator
from build_visual_catalog import DB, ROOT, _hash_file, _safe_name


def _exact_candidate(name, number, setname, search_fn):
    """Return the first search-ranked exact-number product, or ``None``."""
    query = " ".join(str(value or "").strip()
                     for value in (name, number, setname)
                     if str(value or "").strip())
    want = valuator._norm_num(number)
    if not query or not want:
        return query, None
    candidates = search_fn(query, size=50)
    match = next((candidate for candidate in candidates
                  if candidate.get("pid")
                  and valuator._norm_num(candidate.get("number")) == want), None)
    return query, match


def _missing_rows(conn, set_ids=None):
    where = "(visual_phash IS NULL OR TRIM(visual_phash) = '')"
    params = []
    if set_ids:
        marks = ",".join("?" for _ in set_ids)
        where += f" AND setname IN ({marks})"
        params.extend(set_ids)
    return conn.execute(
        "SELECT id, name, setname, number FROM fp "
        f"WHERE {where} ORDER BY id", params).fetchall()


def backfill(db_path=DB, root=ROOT, *, limit=0, delay=.08, timeout=30,
             set_ids=None, search_fn=None, fetch_fn=None, hash_fn=None,
             sleep_fn=None, session=None, report_fn=print):
    """Backfill missing rows and return counters for an auditable run.

    Dependencies are injectable so the regression suite exercises the full
    database/download/hash path without touching the network.
    """
    search_fn = search_fn or valuator.search_candidates
    fetch_fn = fetch_fn or network_safety.fetch_public_bytes
    hash_fn = hash_fn or _hash_file
    sleep_fn = sleep_fn or time.sleep
    session = session or requests.Session()
    os.makedirs(root, exist_ok=True)

    stats = {"processed": 0, "hashed": 0, "no_exact": 0, "failed": 0}
    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(fp)")}
        required = {"id", "name", "setname", "number", "visual_path",
                    "visual_phash", "visual_dhash"}
        missing = required - columns
        if missing:
            raise RuntimeError("fp is missing required columns: "
                               + ", ".join(sorted(missing)))
        rows = _missing_rows(conn, set_ids=set_ids)
        for card_id, name, setname, number in rows:
            if limit and stats["processed"] >= limit:
                break
            stats["processed"] += 1
            temporary = None
            try:
                query, candidate = _exact_candidate(
                    name, number, setname, search_fn)
                if candidate is None:
                    stats["no_exact"] += 1
                    continue

                pid = int(candidate["pid"])
                url = valuator.IMG.format(pid)
                response = fetch_fn(url, timeout=timeout,
                                    requester=session.get)
                if response.status_code < 200 or response.status_code >= 300:
                    raise ValueError(
                        f"TCGplayer image returned HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith("image/"):
                    raise ValueError("TCGplayer response was not an image")

                path = os.path.join(
                    root, f"{_safe_name(card_id)}_tcgplayer_{pid}.jpg")
                temporary = path + ".tmp"
                with open(temporary, "wb") as handle:
                    handle.write(response.content)
                phash, dhash = hash_fn(temporary)
                os.replace(temporary, path)
                temporary = None
                cursor = conn.execute(
                    "UPDATE fp SET visual_path=?, visual_phash=?, visual_dhash=? "
                    "WHERE id=? AND (visual_phash IS NULL OR TRIM(visual_phash)='')",
                    (path, phash, dhash, card_id))
                if cursor.rowcount != 1:
                    raise RuntimeError("row changed before visual update")
                stats["hashed"] += 1
                if stats["hashed"] % 25 == 0:
                    conn.commit()
                    report_fn(
                        f"progress processed={stats['processed']} "
                        f"hashed={stats['hashed']} no_exact={stats['no_exact']} "
                        f"failed={stats['failed']}")
            except Exception as exc:
                stats["failed"] += 1
                report_fn(f"FAIL {card_id}: {exc}")
            finally:
                if temporary and os.path.exists(temporary):
                    try:
                        os.remove(temporary)
                    except OSError:
                        pass
                if delay > 0:
                    sleep_fn(delay)
        conn.commit()
    finally:
        conn.close()
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="process at most N missing rows (0 means all)")
    parser.add_argument("--set-id", action="append", default=[],
                        help="restrict to an exact fp.setname; repeatable")
    parser.add_argument("--delay", type=float, default=.08,
                        help="seconds between targeted rows")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--root", default=ROOT)
    args = parser.parse_args()
    started = time.monotonic()
    stats = backfill(
        args.db, args.root, limit=max(0, args.limit),
        delay=max(0, args.delay), timeout=args.timeout,
        set_ids=args.set_id or None)
    stats["seconds"] = round(time.monotonic() - started, 2)
    print("complete " + " ".join(f"{key}={value}"
                                  for key, value in stats.items()))


if __name__ == "__main__":
    main()
