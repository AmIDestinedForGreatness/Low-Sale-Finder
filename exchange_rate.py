"""Persistent hourly USD/PHP rate cache with honest stale fallback."""
import json
import os
import tempfile
import time

import requests

API_URL = "https://open.er-api.com/v6/latest/USD"
TTL_SECONDS = 3600
_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.environ.get("EXCHANGE_RATE_CACHE_PATH", os.path.join(_HERE, "data", "exchange_rate_cache.json"))


def _read_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as fh:
            item = json.load(fh)
        rate = float(item["rate"])
        fetched_at = float(item["fetched_at"])
        return {"rate": rate, "fetched_at": fetched_at} if rate > 0 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(item):
    parent = os.path.dirname(CACHE_PATH)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="exchange-rate-", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(item, fh)
        os.replace(tmp, CACHE_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get_usd_to_php_rate(now=None, fetcher=requests.get):
    now = time.time() if now is None else now
    cached = _read_cache()
    if cached and now - cached["fetched_at"] < TTL_SECONDS:
        return {**cached, "stale": False, "source": "cache", "error": None}
    try:
        response = fetcher(API_URL, timeout=10, headers={"Accept": "application/json"})
        response.raise_for_status()
        rate = float(response.json()["rates"]["PHP"])
        if rate <= 0:
            raise ValueError("invalid PHP rate")
        item = {"rate": rate, "fetched_at": now}
        _write_cache(item)
        return {**item, "stale": False, "source": "open.er-api.com", "error": None}
    except Exception as exc:
        if cached:
            return {**cached, "stale": True, "source": "last-known-good", "error": str(exc)}
        return {"rate": None, "fetched_at": None, "stale": True, "source": "unavailable", "error": str(exc)}
