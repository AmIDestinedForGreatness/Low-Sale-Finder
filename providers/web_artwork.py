"""Optional Google Vision Web Detection backend for artwork evidence."""
import json
import os
import re
from datetime import datetime

from .artwork import _file_hashes
from .base import EvidenceProvider

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(HERE, "dataset", "web_artwork_cache.json")
USAGE_PATH = os.path.join(HERE, "dataset", "web_artwork_usage.json")


def _load_vision_key():
    """Load the Vision key from the process environment or local secrets vault."""
    key = os.environ.get("GOOGLE_VISION_API_KEY", "").strip()
    if key:
        return key
    path = os.path.expanduser(r"~/.claude/local-secrets/low-sale-finder.env.local")
    try:
        with open(path, encoding="utf-8") as secrets:
            for line in secrets:
                if line.startswith("GOOGLE_VISION_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _key(path):
    stat = os.stat(path)
    phash, _ = _file_hashes(path, stat.st_mtime_ns, stat.st_size)
    return str(phash)


def _candidate(text):
    text = re.sub(r"[_|+]+", " ", str(text or ""))
    match = re.search(r"([A-Za-z][A-Za-z .'-]{2,})\s+(\d{1,3}\s*/\s*[A-Za-z0-9-]+)", text)
    if not match:
        return None
    return {"name": " ".join(match.group(1).split()), "number": match.group(2).replace(" ", ""),
            "source": "web_artwork", "line": text}


class WebArtworkProvider(EvidenceProvider):
    dimension = "artwork"

    def __init__(self, client=None, cache_path=CACHE_PATH, usage_path=USAGE_PATH):
        self.client = client
        self.cache_path, self.usage_path = cache_path, usage_path

    def _load(self, path, default):
        try:
            with open(path, encoding="utf-8") as f: return json.load(f)
        except (OSError, ValueError): return default

    def _save(self, path, value):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f: json.dump(value, f, indent=2)

    def verify(self, image_path, candidates, context):
        result = {"provider": "WebArtworkProvider:google_vision", "dimension": "artwork",
                  "status": "not_checked", "match_score": 0.0, "web_candidates": []}
        if not image_path or not os.path.exists(image_path):
            result["confidence_note"] = "input image unavailable; web artwork was not checked"; return result
        vision_key = _load_vision_key()
        if self.client is None and not vision_key:
            result["confidence_note"] = "GOOGLE_VISION_API_KEY is absent; web artwork was not checked"; return result
        key = _key(image_path); cache = self._load(self.cache_path, {})
        if key in cache: return cache[key]
        client = self.client
        if client is None:
            try:
                from google.cloud import vision
                client = vision.ImageAnnotatorClient(client_options={"api_key": vision_key})
            except Exception as exc:
                result["confidence_note"] = f"Vision client unavailable: {exc}"; return result
        response = client.annotate_image({"image": {"source": {"image_uri": image_path}},
                                          "features": [{"type": "WEB_DETECTION"}]})
        if isinstance(response, dict):
            web = response.get("web_detection", {})
        else:
            web = getattr(response, "web_detection", {})
        pages = (web.get("pages_with_matching_images", []) if isinstance(web, dict)
                 else getattr(web, "pages_with_matching_images", []))
        found = []
        for page in list(pages)[:5]:
            title = getattr(page, "page_title", page.get("page_title", "") if isinstance(page, dict) else "")
            url = getattr(page, "url", page.get("url", "") if isinstance(page, dict) else "")
            item = _candidate(f"{title} {url}")
            if item: found.append(item)
        result.update({"status": "matched" if found else "not_verified", "web_candidates": found,
                       "confidence_note": "Google Web Detection corroborated a candidate; collision analysis remains authoritative" if found else "no usable web match found"})
        cache[key] = result; self._save(self.cache_path, cache)
        usage = self._load(self.usage_path, {}); month = datetime.now().strftime("%Y-%m")
        usage[month] = int(usage.get(month, 0)) + 1; self._save(self.usage_path, usage)
        return result
