"""
app.py — local web dashboard.
Run:  python app.py   →  open http://127.0.0.1:5000 in your browser.

Endpoints:
  GET  /                  -> dashboard UI
  GET  /api/settings      -> current config (webhook set?, price source, country, rate)
  POST /api/scrape        -> run a one-off scrape {queries, below_pct, steal_pct, push}
  GET  /api/scrape/status -> poll progress + results of the running/last scrape
  GET/POST/DELETE /api/watchlist -> manage saved cards
  POST /api/watchlist/run -> scrape every watchlist item with its own threshold
"""
import datetime
import json
import os
import re
import socket
import sqlite3
import threading
import time

import requests

from flask import Flask, request, jsonify, Response, send_file

import config
import exchange_rate
import engine
import valuator
from version import VERSION

STATUS_PATH = os.path.join(os.path.dirname(__file__), "feed_status.json")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DATASET_DIR = os.path.join(os.path.dirname(__file__), "dataset")


def _build_id():
    """Git short SHA of the running code — shown next to the version so a
    stale browser copy is visibly different from the live build."""
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10,
                           cwd=os.path.dirname(os.path.abspath(__file__)))
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


BUILD = _build_id()


def _feed_online():
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        return False, {}
    now = time.time()
    nxt = s.get("next_scan_at") or 0
    scanning = s.get("state") == "scanning" and now - (s.get("heartbeat") or 0) < 30 * 60
    return bool(scanning or (nxt and now < nxt + 180)), s


def _lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _watchdog():
    """Dead-man switch: if the feed goes offline, ping Discord once; ping
    again when it recovers. (Can't help if the whole PC is off — then this
    thread is dead too.)"""
    wh = config.DISCORD_WEBHOOK_URL
    if not wh or "PASTE" in wh:
        return
    last = None
    while True:
        try:
            online, _ = _feed_online()
            if last is True and not online:
                requests.post(wh, json={"embeds": [{
                    "title": "⚠️ Yujin's Pokestop — feed OFFLINE",
                    "description": "The scan loop missed its scheduled pass. "
                                   "Check the 'Pokestop Carousell' / 'Pokestop Facebook' windows on the PC.",
                    "color": 0xE74C3C}]}, timeout=15)
            if last is False and online:
                requests.post(wh, json={"embeds": [{
                    "title": "✅ Yujin's Pokestop — feed back ONLINE",
                    "color": 0x2ECC71}]}, timeout=15)
            last = online
        except Exception:
            pass
        time.sleep(60)

app = Flask(__name__)

# ── shared state for the async scrape (single job at a time) ──────────
_job = {"running": False, "log": [], "deals": [], "label": ""}
_lock = threading.Lock()

def _progress(msg):
    with _lock:
        _job["log"].append(msg)

def _run_job(queries, below, steal, push, label):
    with _lock:
        _job.update(running=True, log=[], deals=[], label=label)
    try:
        deals = engine.run_scan(
            queries,
            below_fraction=below,
            steal_fraction=steal,
            push_discord=push,
            respect_seen=push,   # if just previewing, show everything; if pushing, dedup
            progress=_progress,
        )
        with _lock:
            _job["deals"] = deals
    finally:
        with _lock:
            _job["running"] = False


# ── routes ────────────────────────────────────────────────────────────
@app.after_request
def _no_cache(resp):
    # the dashboard is one server-rendered page — a cached copy means the
    # user sees an OLD build after we ship a fix ("#2 did not work")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    return Response(HTML.replace("__VERSION__", VERSION)
                        .replace("__BUILD__", BUILD), mimetype="text/html")

@app.route("/logo")
def logo():
    for ext in ("png", "jpg", "jpeg", "webp", "gif"):
        p = os.path.join(os.path.dirname(__file__), f"logo.{ext}")
        if os.path.exists(p):
            return send_file(p)
    return ("", 404)

@app.route("/api/feedstatus")
def feedstatus():
    """The feed loop (main.py --feed) writes feed_status.json every pass.
    ONLINE = currently scanning, or the promised next scan hasn't been
    missed by more than 3 minutes. A killed feed process goes OFFLINE
    automatically once its next_scan_at deadline passes."""
    online, s = _feed_online()
    # recent = last sends from BOTH feeds (Carousell + FB groups) via feed_log
    recent = (s.get("recent") or [])[:8]  # fallback: old status-file list
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT url,title,price,category,ts,source,posted_ts FROM feed_log "
            "ORDER BY ts DESC LIMIT 10").fetchall()
        if rows:
            recent = [{"url": u, "title": t, "price": p, "category": c, "ts": ts,
                       "source": src or "carousell", "posted_ts": pts}
                      for u, t, p, c, ts, src, pts in rows]
    except sqlite3.Error:
        pass  # pre-migration db — fallback stays
    finally:
        conn.close()
    return jsonify({
        "online": online,
        "state": s.get("state", "unknown"),
        "next_scan_at": s.get("next_scan_at") or 0,
        "last_scan_end": s.get("last_scan_end"),
        "last_new": s.get("last_new"),
        "recent": recent,
        "poll_minutes": config.POLL_INTERVAL_MINUTES,
        "version": VERSION,
        "build": BUILD,
        "server_now": time.time(),
        "lan_url": f"http://{_lan_ip()}:5000",
    })


@app.route("/api/restart", methods=["POST"])
def restart():
    """Kill the chosen process; loop.bat relaunches it ~30s later."""
    target = (request.get_json(force=True).get("target") or "feed").strip()
    if target == "feed":
        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*--feed*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, timeout=30)
        return jsonify({"ok": True, "msg": "feed restarting (~30s)"})
    if target == "dashboard":
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return jsonify({"ok": True, "msg": "dashboard restarting (~30s)"})
    return jsonify({"error": "unknown target"}), 400


# ── card valuator: photo -> OCR -> candidates -> real-sold valuation ──
@app.route("/api/valuator/ocr", methods=["POST"])
def valuator_ocr():
    f = request.files.get("photo")
    if not f:
        return jsonify({"error": "no photo"}), 400
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(f.filename or "")[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        return jsonify({"error": "not an image"}), 400
    path = os.path.join(UPLOAD_DIR, f"card_{int(time.time())}{ext}")
    f.save(path)
    lines = valuator.ocr_lines(path)
    # BINDER MODE (V0.9): 3+ distinct real card names in one photo = a
    # binder page (2x2); 2 names in a LANDSCAPE frame = two cards side by
    # side (1x2). Each cell runs the full identification stack.
    import folder_dataset
    import profile_dataset
    from PIL import Image as _Img
    n_names = len(folder_dataset.distinct_names(lines))
    n_numbers = folder_dataset.distinct_collector_fractions(lines)
    _im = _Img.open(path)
    pair = n_names == 2 and _im.width > _im.height
    probe_cells, probe_ocr = [], []
    contour_probe = False
    grid_worth_trying = (not pair and n_names < 3
                         and folder_dataset.should_probe_grid(
                             _im.width, _im.height, n_names, n_numbers))
    if (not pair and n_names < 3
            and (grid_worth_trying or min(_im.width, _im.height) >= 900)):
        # CONTOUR-FIRST: try actual card-shape detection before falling back
        # to a blind fixed 2x2 quarter-split. A blind split assumes exactly
        # 4 cards — wrong for anything else (a real 12-card 3x4 page got
        # quartered into 4 cells each fusing 3 different cards, and still
        # "succeeded" by probe_grid()'s own evidence-count gate because each
        # fused cell had SOME readable fragment, locking in a wrong answer
        # before a better split was ever tried). Contour detection looks at
        # the real geometry, so prefer it whenever it finds something usable.
        probe_cells, probe_ocr = folder_dataset.probe_contours(path, UPLOAD_DIR)
        contour_probe = bool(probe_cells)
    if not probe_cells and grid_worth_trying:
        probe_cells, probe_ocr = folder_dataset.probe_grid(path, UPLOAD_DIR)
    if n_names >= 3 or pair or probe_cells:
        if contour_probe:
            cols = 2 if len(probe_cells) > 1 else 1
            rows = -(-len(probe_cells) // cols)
        else:
            rows, cols = (1, 2) if pair else (2, 2)
        cards = []
        cells = probe_cells or folder_dataset.split_grid(
            path, UPLOAD_DIR, rows=rows, cols=cols)
        cell_ocr = probe_ocr or [valuator.ocr_lines(cell) for cell in cells]
        for cell, cell_lines in zip(cells, cell_ocr):
            ident = profile_dataset.identify([cell], [cell_lines],
                                             set())
            ident.pop("ocr", None)
            # keep candidates when the printing is AMBIGUOUS (no number) —
            # that's exactly when the eye-gate needs them; drop them once
            # a card is fully pinned, where they're just dead weight
            if ident.get("evidence_level") in ("A", "B"):
                ident.pop("candidates", None)
            ident["cell"] = "/uploads/" + os.path.basename(cell)
            cards.append(ident)
        return jsonify({"multi": True, "cards": cards,
                        "rows": rows, "cols": cols,
                        "file": "/uploads/" + os.path.basename(path)})
    name, number = valuator.guess_query(lines)
    if not name and not number:
        # first pass unusable (glare/holo) -> deep scan: zoomed region crops
        deep = valuator.ocr_deep(path)
        if deep:
            lines = lines + [ln for ln in deep if ln not in lines]
            name, number = valuator.guess_query(lines)
    name_read = name
    via = None
    aid = None
    if not name:
        # name unreadable (Japanese / blur) -> identify by attack fingerprint
        fp = valuator.fingerprint_names(lines)
        if fp:
            name, via = fp[0], "attack fingerprint"
    if not name:
        # LAYER D: JP vintage prints the National Dex number ("NO.398")
        dx = valuator.dex_names(lines)
        if len(dx) == 1:
            name, via = dx[0], "dex number"
    if not name:
        # LAYER E: attack/ability names pin the card ("Victory Ball" only
        # exists on Victini)
        aid = valuator.attack_id(lines)
        if aid:
            name, via = aid[0], "attack names"
            if not number and len(aid[1]) == 1:
                number = aid[1][0]
    if not name and number:
        # TIE-BREAK: tied fingerprint × the number's own catalog matches
        cross = valuator.crosscheck_name(lines, number)
        if cross:
            name, via = cross, "fingerprint × number"
    if name and not number:
        # PROCEDURE RULE (Yujin): identification = name AND printing ID.
        # Success on the name must not end the hunt for the number —
        # zoom-scan the footer region too.
        deep = valuator.ocr_deep(path)
        if deep:
            _, number = valuator.guess_query(lines + deep)
    # LANGUAGE is a claim — only POSITIVE evidence sets it (mirrors
    # profile_dataset.py's identify(), which fixed this same bug already:
    # "identified via unique number match" says nothing about language,
    # it mislabeled English cards Japanese and buried their real candidate
    # past the [:6] display cutoff when prefer_jp reordered results).
    jp = (bool(name and valuator._SET_RE.fullmatch(name))
          or bool(re.search(r"[A-Za-z]-P$", str(number or "")))
          or via in ("attack fingerprint", "dex number", "fingerprint × number"))
    # for SEARCH RANKING an unreadable name is still a useful JP hint, even
    # when it's not strong enough evidence for the language CLAIM above
    # (mirrors profile_dataset.py's identify() prefer_jp split exactly).
    prefer_jp = jp or bool(number and not name)
    # LAYER B: a number must be a real printing of the identified card —
    # snap 1-digit OCR errors (015/173 -> 016/173) against actual printings
    number_read, snapped = number, False
    cands = valuator.search_candidates(name, prefer_jp=prefer_jp) if name else []
    if via and name and number:
        fixed = valuator.snap_number(number, [c["number"] for c in cands])
        if fixed and valuator._norm_num(fixed) != valuator._norm_num(number):
            number, snapped = fixed, True
        elif fixed:
            number = fixed               # canonical zero-padding
    if name and number and not any(
            valuator._norm_num(c["number"]) == valuator._norm_num(str(number)) for c in cands):
        # the name-only search above may not carry the exact-number product —
        # re-search with the number too so catalog_match evidence is real
        cands = valuator.search_candidates(f"{name} {number}", prefer_jp=prefer_jp) or cands
    if name and number and not any(
            valuator._norm_num(c["number"]) == valuator._norm_num(str(number)) for c in cands):
        # MECHANIC-VARIANT RETRY: OCR often drops the stylized V/GX/EX glyph
        # ("Altaria" 123/124 is really Altaria EX) — try suffixed forms, same
        # pattern profile_dataset.py's identify() already uses for this exact
        # failure mode. This route has its own inline logic (doesn't call
        # identify()), so it needs its own copy of this retry.
        for suf in ("V", "VMAX", "GX", "EX", "ex"):
            c2 = valuator.search_candidates(f"{name} {suf} {number}", prefer_jp=prefer_jp)
            exact = [c for c in c2
                     if valuator._norm_num(c["number"]) == valuator._norm_num(str(number))]
            if exact:
                cands, name = c2, exact[0]["name"].split(" - ")[0]
                via = via or "number-variant match"
                break
    graded = any(re.search(r"\b(psa|bgs|cgc|beckett|black label|"
                           r"gem ?mint|pristine)", ln, re.I) for ln in lines)
    result = {"query": (name + " " + (number or "")).strip(),
              "name": name, "name_read": name_read,
              "number": number, "number_read": number_read,
              "snapped": snapped, "lines": lines[:12],
              "via": via, "jp": jp, "graded": bool(name or number) and graded,
              "candidates": cands[:6],
              "file": "/uploads/" + os.path.basename(path)}
    # DIRECTIVE.md, Rule 1/2: every identification carries its Evidence
    # Level + chain. This route has its own inline identification logic
    # (doesn't call profile_dataset.identify()) so it builds evidence here too.
    import evidence
    result.update(evidence.build_evidence(result, lines, aid,
                                          image_paths=[path]))
    evidence.log_failure(result)
    return jsonify(result)


@app.route("/api/valuator/from_url", methods=["POST"])
def valuator_from_url():
    """LINK AS SOURCE: paste a Carousell listing URL — the system fetches
    the listing's photos itself and runs the full identification stack
    (multi-photo evidence merge, same as the dataset pipeline)."""
    url = ((request.get_json(silent=True) or {}).get("url") or "").strip()
    if not re.match(r"https?://", url):
        return jsonify({"error": "not a link"}), 400
    if not re.search(r"(carousell|facebook\.com|fb\.com|fb\.watch)", url):
        return jsonify({"error": "Carousell / FB links only (for now)"}), 400
    try:
        import profile_dataset
        page = profile_dataset.scrape_listing_page(url)
    except Exception as e:
        return jsonify({"error": f"could not open that page: {e}"}), 502
    imgs = (page or {}).get("images") or []
    if not imgs:
        return jsonify({"error": "no photos found on that page — FB usually "
                        "needs login; save the photo and drop it in the box "
                        "instead"}), 422
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stamp, paths = int(time.time()), []
    for n, u in enumerate(imgs[:6]):
        try:
            r = requests.get(profile_dataset._fullsize(u), timeout=30,
                             headers={"User-Agent": profile_dataset.UA})
            if r.status_code == 200 and len(r.content) > 4000:
                p = os.path.join(UPLOAD_DIR, f"link_{stamp}_{n}.jpg")
                with open(p, "wb") as f:
                    f.write(r.content)
                paths.append(p)
        except Exception:
            pass
    if not paths:
        return jsonify({"error": "the photos would not download"}), 422
    # cap at 4 photos — identify() deep-scans when evidence is missing and
    # this runs inside a web request
    ident = profile_dataset.identify(paths[:4],
                                     [valuator.ocr_lines(p) for p in paths[:4]],
                                     set())
    ident.pop("ocr", None)
    ident.pop("candidates", None)
    ident["file"] = "/uploads/" + os.path.basename(paths[0])
    ident["title"] = (page.get("title") or "")[:120]   # for HIS eye only
    return jsonify(ident)


@app.route("/uploads/<name>")
def valuator_upload_file(name):
    # serve back uploaded card photos (click-to-enlarge on the dashboard)
    safe = os.path.basename(name)
    p = os.path.join(UPLOAD_DIR, safe)
    if os.path.exists(p):
        return send_file(p)
    return ("", 404)


@app.route("/api/valuator/search")
def valuator_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"candidates": []})
    jp = request.args.get("jp") == "1"
    return jsonify({"candidates": valuator.search_candidates(q, prefer_jp=jp)})


@app.route("/api/valuator/value")
def valuator_value():
    try:
        pid = int(request.args.get("pid", ""))
    except ValueError:
        return jsonify({"error": "bad pid"}), 400
    try:
        ph = float(request.args.get("ph_factor", 1.2))
    except ValueError:
        ph = 1.2
    return jsonify(valuator.valuate(pid, ph_factor=max(0.5, min(3.0, ph))))


@app.route("/api/pricecharting")
def pricecharting_lookup():
    title = (request.args.get("title") or "").strip()
    if len(title) < 3:
        return jsonify({"url": None})
    import pc_price
    _, label = pc_price.market_value(title)
    marker = "|url:"
    url = label.split(marker, 1)[1].strip() if label and marker in label else None
    return jsonify({"url": url})


@app.route("/api/valuator/confirm", methods=["POST"])
def valuator_confirm():
    payload = request.get_json(silent=True) or {}
    image = str(payload.get("image") or "")
    candidate = payload.get("candidate") or {}
    name, number = candidate.get("name"), candidate.get("number")
    if not image.startswith("/uploads/") or not name or not number:
        return jsonify({"error": "image, candidate.name, and candidate.number are required"}), 400
    image_path = os.path.join(UPLOAD_DIR, os.path.basename(image))
    if not os.path.isfile(image_path):
        return jsonify({"error": "confirmed image is unavailable"}), 404
    path = os.path.join(DATASET_DIR, "confirmed_by_user.json")
    os.makedirs(DATASET_DIR, exist_ok=True)
    rows = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                rows = json.load(handle)
        except (OSError, ValueError):
            rows = []
    if not isinstance(rows, list):
        rows = []
    record = {"ident": {"name": str(name), "number": str(number)},
              "images": [image_path]}
    if not any(r.get("ident") == record["ident"] and image_path in (r.get("images") or [])
               for r in rows if isinstance(r, dict)):
        rows.append(record)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
    from providers.artwork import _dataset_references
    _dataset_references.cache_clear()
    return jsonify({"ok": True, "record": record})


@app.route("/api/stats")
def stats():
    conn = sqlite3.connect(config.SEEN_DB_PATH)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS feed_log "
                     "(url TEXT, title TEXT, price REAL, category TEXT, ts REAL)")
        days = []
        today = datetime.date.today()
        for i in range(6, -1, -1):
            d = today - datetime.timedelta(days=i)
            start = time.mktime(d.timetuple())
            n = conn.execute("SELECT COUNT(*) FROM feed_log WHERE ts>=? AND ts<?",
                             (start, start + 86400)).fetchone()[0]
            days.append({"day": d.strftime("%a"), "count": n})
        cats = conn.execute(
            "SELECT category, COUNT(*), AVG(price) FROM feed_log "
            "WHERE ts>=? GROUP BY category ORDER BY 2 DESC",
            (time.time() - 7 * 86400,)).fetchall()
        return jsonify({"days": days,
                        "cats": [{"category": c, "count": n, "avg": a or 0}
                                 for c, n, a in cats]})
    finally:
        conn.close()

@app.route("/api/settings")
def settings():
    return jsonify({
        "webhook_set": bool(config.DISCORD_WEBHOOK_URL) and "PASTE" not in config.DISCORD_WEBHOOK_URL,
        "price_source": config.PRICE_SOURCE,
        "country": config.CAROUSELL_COUNTRY,
        "usd_to_local": exchange_rate.get_usd_to_php_rate(),
        "default_below_pct": round((1 - config.ALERT_AT_OR_BELOW_FRACTION) * 100),
    })

@app.route("/api/webhook", methods=["POST"])
def set_webhook():
    """Link a Discord webhook from the UI: validate, send a test ping,
    persist into config.py (gitignored) and the running process."""
    url = (request.get_json(force=True).get("url") or "").strip()
    if not re.match(r"^https://(discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)/api/webhooks/\d+/", url):
        return jsonify({"error": "That doesn't look like a Discord webhook URL. It should start with https://discord.com/api/webhooks/…"}), 400
    cfg_path = os.path.join(os.path.dirname(__file__), "config.py")
    with open(cfg_path, encoding="utf-8") as f:
        src = f.read()
    new_src, n = re.subn(r'^DISCORD_WEBHOOK_URL\s*=.*$',
                         f'DISCORD_WEBHOOK_URL = "{url}"', src, count=1, flags=re.M)
    if n == 0:
        new_src = f'DISCORD_WEBHOOK_URL = "{url}"\n' + src
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(new_src)
    config.DISCORD_WEBHOOK_URL = url
    return jsonify({"ok": True})

@app.route("/api/webhook/test", methods=["POST"])
def webhook_test():
    wh = config.DISCORD_WEBHOOK_URL
    if not wh or "PASTE" in wh:
        return jsonify({"error": "no webhook linked yet"}), 400
    try:
        r = requests.post(wh, json={"content": "✅ Test ping from Yujin's Pokestop."}, timeout=10)
        if r.status_code in (200, 204):
            return jsonify({"ok": True})
        return jsonify({"error": f"Discord returned {r.status_code}"}), 400
    except Exception as e:
        return jsonify({"error": f"Couldn't reach Discord: {e}"}), 400

RELAY_PATH = os.path.join(os.path.dirname(__file__), "AGENT-RELAY.md")


def _parse_relay():
    """AGENT-RELAY.md entries look like:
      ### CC | 2026-07-17 15:45 SGT | relayed by Marvin
      <body...>
    Split on '### ' headers; '|'-separated header fields are who/when/note."""
    try:
        # errors="replace": one bad byte anywhere in this file (e.g. a
        # non-UTF-8 dash from a copy-paste) must never silently blank the
        # entire relay panel — replace the bad byte, keep every real entry.
        with open(RELAY_PATH, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return []
    entries = []
    for i, part in enumerate(re.split(r"(?m)^### ", text)[1:]):
        lines = part.split("\n")
        header = [p.strip() for p in lines[0].split("|")]
        who = (header[0] if header else "?") or "?"
        when = header[1] if len(header) > 1 else ""
        note = header[2] if len(header) > 2 else ""
        body = "\n".join(lines[1:]).strip()
        entries.append({"i": i, "who": who, "when": when, "note": note, "body": body})
    return entries


@app.route("/api/relay")
def relay():
    """Live feed for the dashboard's CC<->Codex chatroom panel."""
    entries = _parse_relay()
    try:
        mtime = os.path.getmtime(RELAY_PATH)
    except Exception:
        mtime = 0
    return jsonify({"entries": entries, "mtime": mtime})


@app.route("/api/scrape", methods=["POST"])
def scrape():
    if _job["running"]:
        return jsonify({"error": "a scan is already running"}), 409
    data = request.get_json(force=True)
    queries = [q.strip() for q in data.get("queries", []) if q.strip()]
    categories = getattr(config, "CAROUSELL_CATEGORY_URLS", [])
    queries.extend(categories)
    if not queries:
        queries = list(config.SEARCH_QUERIES)
    if not queries:
        return jsonify({"error": "no queries provided"}), 400
    # dedupe while preserving order
    queries = list(dict.fromkeys(queries))
    below_pct = float(data.get("below_pct", 20))    # "20% under market"
    push = bool(data.get("push", False))
    below = 1 - below_pct / 100.0
    steal = 0.0
    t = threading.Thread(target=_run_job,
                         args=(queries, below, steal, push, "category scan"),
                         daemon=True)
    t.start()
    return jsonify({"started": True})

@app.route("/api/scrape/status")
def scrape_status():
    with _lock:
        return jsonify({
            "running": _job["running"],
            "log": _job["log"][-50:],
            "deals": _job["deals"],
            "label": _job["label"],
        })



# ── the single-page UI (kept in one string so it's one file to run) ───
HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yujin's Pokestop</title>
<style>
  :root{
    --bg:#05070f; --panel:rgba(15,21,40,.78); --panel2:#0c1224; --line:rgba(42,184,246,.13);
    --line2:rgba(42,184,246,.38); --ink:#d9e6f5; --muted:#66779c; --accent:#2ab8f6; --accent2:#3b6cff;
    --green:#2ee6a8; --red:#ff5470; --viz-series-1:#2ab8f6; --viz-series-2:#3b6cff; --radius:14px;
    --mono:'Cascadia Code','Consolas',ui-monospace,Menlo,monospace;
  }
  *{box-sizing:border-box}
  .ph-axis{fill:var(--muted);font-size:10px}
  body{margin:0;color:var(--ink);
    font:15px/1.55 'Segoe UI',system-ui,-apple-system,sans-serif;
    background:
      radial-gradient(1000px 460px at 50% -120px, rgba(42,184,246,.13), transparent 62%),
      linear-gradient(rgba(42,184,246,.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(42,184,246,.03) 1px, transparent 1px),
      var(--bg);
    background-size:auto, 34px 34px, 34px 34px, auto;
    -webkit-font-smoothing:antialiased}
  .hero{text-align:center;padding:44px 16px 6px}
  .hero img{height:112px;filter:drop-shadow(0 0 26px rgba(42,184,246,.5))}
  .wordmark{font-size:27px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;margin-top:14px}
  .wordmark b{color:var(--accent);text-shadow:0 0 18px rgba(42,184,246,.55)}
  .hero .sub{color:var(--muted);font-family:var(--mono);font-size:11px;
    letter-spacing:.3em;text-transform:uppercase;margin-top:6px}
  .badges{display:flex;gap:8px;justify-content:center;margin-top:16px;flex-wrap:wrap}
  .badge{font-family:var(--mono);font-size:11px;letter-spacing:.06em;padding:4px 11px;
    border-radius:6px;border:1px solid var(--line);color:var(--muted);background:rgba(12,18,36,.6)}
  .badge.ok{color:var(--green);border-color:rgba(46,230,168,.35)}
  .badge.no{color:var(--red);border-color:rgba(255,84,112,.35)}
  main{max-width:1020px;margin:0 auto;padding:22px;display:grid;gap:18px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
    padding:22px;position:relative;overflow:hidden;backdrop-filter:blur(8px)}
  .card::before{content:"";position:absolute;top:0;left:0;right:0;height:1px;
    background:linear-gradient(90deg,transparent,var(--line2),transparent)}
  .card h2{margin:0 0 16px;font-family:var(--mono);font-size:11.5px;
    text-transform:uppercase;letter-spacing:.24em;color:var(--accent)}
  .card h2::before{content:"// ";color:var(--muted)}
  label{display:block;font-size:13px;color:var(--muted);margin:0 0 5px}
  input[type=text],input[type=number],textarea{
    width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);
    border-radius:9px;padding:10px 12px;font:inherit;outline:none;transition:border .15s, box-shadow .15s}
  input:focus,textarea:focus{border-color:var(--line2);box-shadow:0 0 0 3px rgba(42,184,246,.08)}
  .row{display:flex;gap:14px;flex-wrap:wrap}
  .row>div{flex:1;min-width:130px}
  .slider-val{color:var(--accent);font-weight:700;font-family:var(--mono)}
  button{cursor:pointer;border:none;border-radius:9px;padding:11px 18px;font:inherit;font-weight:600;
    transition:filter .15s, box-shadow .15s, border-color .15s}
  .btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#03101d;
    box-shadow:0 0 18px rgba(42,184,246,.25)}
  .btn-primary:hover{filter:brightness(1.12);box-shadow:0 0 26px rgba(42,184,246,.4)}
  .btn-ghost{background:rgba(12,18,36,.7);color:var(--ink);border:1px solid var(--line)}
  .btn-ghost:hover{border-color:var(--line2);box-shadow:0 0 14px rgba(42,184,246,.15)}
  .btn-row{display:flex;gap:10px;align-items:center;margin-top:16px;flex-wrap:wrap}
  .check{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}
  .check input{width:auto}
  #feedState{font-family:var(--mono);font-size:13px;letter-spacing:.12em;text-transform:uppercase}
  #countdown{font-size:17px}
  #feedDot{animation:pulse 2s ease-in-out infinite}
  @keyframes pulse{50%{opacity:.45}}
  .deal{border:1px solid var(--line);border-radius:11px;padding:14px;margin-top:10px;
    display:flex;justify-content:space-between;gap:14px;align-items:flex-start;background:var(--panel2)}
  .deal.steal{border-color:rgba(255,84,112,.4);box-shadow:0 0 0 1px rgba(255,84,112,.15) inset}
  .deal a{color:var(--ink);text-decoration:none;font-weight:600}
  .deal a:hover{color:var(--accent)}
  .deal .meta{font-size:13px;color:var(--muted);margin-top:4px}
  .pct{font-size:20px;font-weight:800;white-space:nowrap;font-family:var(--mono)}
  .pct.steal{color:var(--red)} .pct.deal{color:var(--green)}
  .tag{font-size:11px;padding:2px 8px;border-radius:999px;background:#0a0f1e;border:1px solid var(--line);color:var(--muted);margin-left:6px}
  #log{font:12px/1.5 var(--mono);background:#04060d;border:1px solid var(--line);
    border-radius:9px;padding:12px;max-height:180px;overflow:auto;color:#5d7ba6;white-space:pre-wrap}
  .wl-item{display:flex;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line)}
  .wl-item:last-child{border-bottom:none}
  .wl-item .q{flex:1}
  .wl-item a{color:var(--ink);text-decoration:none}
  .wl-item a:hover{color:var(--accent)}
  .cand{transition:transform .12s, border-color .12s, box-shadow .12s}
  .cand:hover{transform:translateY(-3px);border-color:var(--accent)!important;
    box-shadow:0 4px 18px rgba(42,184,246,.25)}
  .cmp-imgwrap{overflow:hidden;border-radius:10px;width:min(340px,42vw);aspect-ratio:63/88;
    background:#000;border:1px solid var(--line)}
  .cmp-imgwrap img{width:100%;height:100%;object-fit:contain;transition:transform .08s;cursor:zoom-in}
  .muted{color:var(--muted);font-size:13px}
  .spin{display:inline-block;width:13px;height:13px;border:2px solid var(--muted);
    border-top-color:var(--accent);border-radius:50%;animation:s .7s linear infinite;vertical-align:-2px}
  @keyframes s{to{transform:rotate(360deg)}}
  .hidden{display:none}
  .pricebar-wrap{display:flex;align-items:flex-end;gap:2px;height:44px;margin-top:10px}
  .pricebar{flex:1;background:var(--accent);border-radius:3px 3px 0 0;min-height:3px;
    transition:filter .12s;cursor:default}
  .pricebar:hover{filter:brightness(1.35)}
  .vol-badge{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid;font-weight:700}
  #relayLog{font:12.5px/1.55 var(--mono);background:#04060d;border:1px solid var(--line);
    border-radius:9px;padding:12px;max-height:360px;overflow-y:auto}
  .relay-msg{padding:7px 0;border-bottom:1px solid rgba(42,184,246,.07)}
  .relay-msg:last-child{border-bottom:none}
  .relay-head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
  .relay-who{font-weight:800;letter-spacing:.04em}
  .relay-who.cc{color:var(--accent)}
  .relay-who.cx{color:#ffb454}
  .relay-who.other{color:var(--green)}
  .relay-when{color:var(--muted);font-size:11px}
  .relay-note{color:var(--muted);font-size:11px;font-style:italic}
  .relay-body{color:var(--ink);white-space:pre-wrap;margin-top:3px;word-break:break-word}
  .relay-body code{background:rgba(42,184,246,.1);border-radius:4px;padding:0 4px}
  #relayDot{width:8px;height:8px;border-radius:50%;background:var(--muted);display:inline-block;margin-right:6px}
  #relayDot.live{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 2s ease-in-out infinite}
</style></head>
<body>
<main>

  <div class="hero">
    <img src="/logo" alt="" style="display:none" onload="this.style.display='inline-block'">
    <div class="wordmark">Yujin's <b>Pokestop</b></div>
    <div class="sub">Multi-source card scraper · AI identification · live feed</div>
    <div class="badges">
      <span class="badge" style="color:var(--accent);border-color:var(--line2)" title="version · build (git)">V__VERSION__ · #__BUILD__</span>
      <span class="badge" style="color:#ffb454;border-color:rgba(255,180,84,.4)" title="still actively evolving — expect rough edges">BETA</span>
      <span id="webhookBadge" class="badge">checking…</span>
      <span id="srcBadge" class="badge"></span>
      <span id="ctryBadge" class="badge"></span>
      <span class="badge ok" title="Facebook groups feed — live">Facebook ✓</span>
      <span class="badge" style="color:var(--muted);border-color:var(--line)" title="not enabled yet — needs a real Marketplace search URL, coming soon">FB Marketplace (soon)</span>
    </div>
  </div>

  <section class="card">
    <h2>Live status</h2>
    <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
      <div style="display:flex;gap:9px;align-items:center">
        <div id="feedDot" style="width:13px;height:13px;border-radius:50%;background:var(--muted)"></div>
        <div id="feedState" style="font-weight:700">checking…</div>
      </div>
      <div class="muted">next scan in <span id="countdown" class="slider-val" style="font-variant-numeric:tabular-nums">--:--</span></div>
      <div class="muted" id="lastScan"></div>
      <div class="muted" id="lanUrl" style="margin-left:auto"></div>
    </div>
    <div class="btn-row">
      <button class="btn-ghost" id="restartFeed">🔄 Restart feed</button>
      <button class="btn-ghost" id="restartDash">🔄 Restart dashboard</button>
      <span id="restartMsg" class="muted"></span>
    </div>
    <div id="recentBox" style="margin-top:12px"><p class="muted">loading…</p></div>
  </section>

  <section class="card">
    <h2>Card valuator</h2>
    <p class="muted" style="margin:4px 0 10px">Drop a card photo — I read it, you confirm the exact card, it prices from <b>real recent sales</b>.</p>
    <div id="dropZone" style="border:2px dashed var(--line);border-radius:10px;padding:22px;text-align:center;cursor:pointer">
      <div style="font-size:26px">🃏</div>
      <div>Drop card photo here or <b>click to choose</b></div>
      <input type="file" id="cardFile" accept="image/*" style="display:none">
    </div>
    <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
      <input type="text" id="valUrl" placeholder="…or paste a Carousell listing link — I'll pull its photos myself"
             style="flex:1;min-width:220px">
      <button class="btn-primary" id="valFromUrl">From link</button>
    </div>
    <div id="valQueryRow" class="hidden" style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <img id="valThumb" style="height:56px;border-radius:6px" alt="">
      <input type="text" id="valQuery" placeholder="card name + number" style="flex:1;min-width:200px">
      <button class="btn-primary" id="valSearch">Find card</button>
      <button id="valClear" title="remove uploaded images and reset everything"
              style="background:none;border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:7px 12px;cursor:pointer">✕ Clear</button>
      <span id="valMsg" class="muted"></span>
    </div>
    <!-- DIRECTIVE.md: every identification shows its Evidence Level +
         chain here — never just a bare name/number claim -->
    <div id="valEvidence" style="margin-top:8px"></div>
    <!-- uploaded images live HERE and persist until ✕ Clear — search results
         render below in #valCands and never touch this container -->
    <div id="valBinder" style="margin-top:12px"></div>
    <div id="valCands" style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px"></div>
    <div id="valResult" style="margin-top:12px"></div>
  </section>

  <!-- display toggled by JS only: inline display:flex here overrode the
       .hidden class (inline > class) and blacked out the whole page -->
  <div id="lightbox" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99;align-items:center;justify-content:center;cursor:zoom-out">
    <img id="lightboxImg" style="max-width:92vw;max-height:92vh;border-radius:8px" alt="">
  </div>

  <!-- side-by-side confirmation: the FINAL identification authority is the
       user's eye (stamps, promo marks, 1st edition). display via JS only. -->
  <div id="cmpModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:98;align-items:center;justify-content:center">
    <div class="card" style="max-width:880px;width:94vw;max-height:94vh;overflow:auto;margin:0">
      <div id="cmpTitle" style="font-weight:700;font-size:17px"></div>
      <div class="muted" style="font-size:12px;margin:4px 0 14px">
        Final check is <b>your eye</b> — hover (or tap) to magnify. Compare art, stamps
        (promo / 1st edition), collector number, holo pattern.
      </div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;justify-content:center">
        <div><div class="muted" style="font-size:11px;margin-bottom:4px">📷 YOUR CARD</div>
          <div class="cmp-imgwrap"><img id="cmpMine" alt=""></div></div>
        <div><div class="muted" style="font-size:11px;margin-bottom:4px">🗄 DATABASE SCAN</div>
          <div class="cmp-imgwrap"><img id="cmpTheir" alt=""></div></div>
        <div style="display:flex;flex-direction:column;align-items:center;gap:8px;justify-content:center">
          <div class="muted" style="font-size:11px">🔍 ZOOM</div>
          <input type="range" id="cmpZoom" min="1.5" max="6" step="0.5" value="2.5"
                 style="writing-mode:vertical-lr;direction:rtl;height:150px">
          <span id="cmpZoomLbl" class="slider-val">2.5×</span>
          <div class="muted" style="font-size:10px;max-width:70px;text-align:center">click a card to zoom, move mouse to pan</div>
        </div>
      </div>
      <div class="btn-row" style="justify-content:center;margin-top:16px">
        <button class="btn-primary" id="cmpYes">✅ Yes — this is my card</button>
        <button class="btn-ghost" id="cmpNo">↩ Not this one</button>
      </div>
    </div>
  </div>

  <section class="card">
    <h2>Discord alerts</h2>
    <p class="muted" style="margin:0 0 12px">
      In Discord: your server → <b>⚙ Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL</b> — then paste it here.
    </p>
    <input type="text" id="whUrl" placeholder="https://discord.com/api/webhooks/…">
    <div class="btn-row">
      <button class="btn-primary" id="whSave">Link webhook</button>
      <button class="btn-ghost" id="whTest">Send test ping</button>
      <span id="whMsg" class="muted"></span>
    </div>
  </section>

  <section class="card">
    <h2>CC ⇄ Codex relay</h2>
    <p class="muted" style="margin:0 0 12px">
      <span id="relayDot"></span><span id="relayState">checking…</span> — live view of
      <code style="background:rgba(42,184,246,.1);border-radius:4px;padding:0 4px">AGENT-RELAY.md</code>,
      the shared handoff log between Claude Code and Codex on this repo.
    </p>
    <div id="relayLog"><p class="muted">loading…</p></div>
  </section>

</main>
<script>
const $ = s => document.querySelector(s);
let poll = null;

async function loadSettings(){
  const s = await (await fetch('/api/settings')).json();
  const wb = $('#webhookBadge');
  wb.textContent = s.webhook_set ? 'Discord ✓' : 'Discord not set';
  wb.className = 'badge ' + (s.webhook_set ? 'ok' : 'no');
  $('#srcBadge').textContent = 'price: ' + s.price_source;
  $('#ctryBadge').textContent = 'carousell.' + s.country;
  if(s.webhook_set && !$('#whMsg').textContent)
    $('#whMsg').textContent = 'Already linked ✓ — paste a new URL only if you want to replace it.';
}

$('#whSave').onclick = async ()=>{
  const url = $('#whUrl').value.trim();
  if(!url){ alert('Paste your webhook URL first.'); return; }
  $('#whSave').disabled = true; $('#whMsg').textContent = 'saving…';
  try{
    const r = await fetch('/api/webhook',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url})});
    const d = await r.json();
    $('#whMsg').textContent = r.ok ? '✅ Linked and saved.' : '❌ ' + (d.error || 'failed');
    if(r.ok){ $('#whUrl').value=''; loadSettings(); }
  } catch(e){ $('#whMsg').textContent = '❌ ' + e; }
  $('#whSave').disabled = false;
};
$('#whTest').onclick = async ()=>{
  $('#whTest').disabled = true; $('#whMsg').textContent = 'pinging…';
  try{
    const r = await fetch('/api/webhook/test',{method:'POST'});
    const d = await r.json();
    $('#whMsg').textContent = r.ok ? '✅ Test sent — check your Discord channel.' : '❌ ' + (d.error || 'failed');
  } catch(e){ $('#whMsg').textContent = '❌ ' + e; }
  $('#whTest').disabled = false;
};

function fmt(n){ return Number(n).toLocaleString(undefined,{maximumFractionDigits:0}); }
function escapeHtml(s){ return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// ── stale-page detector: this page's build vs the server's build ──
const PAGE_BUILD = '__BUILD__';
function checkBuild(server){
  if(!server || server === '?' || server === PAGE_BUILD) return;
  if($('#staleBanner')) return;
  const b = document.createElement('div');
  b.id = 'staleBanner';
  b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:100;background:#c0392b;color:#fff;'
    + 'padding:8px 14px;text-align:center;font-weight:700;cursor:pointer';
  b.textContent = '⚠ This page is an OLD build (#' + PAGE_BUILD + ' vs #' + server + ') — click here to reload';
  b.onclick = ()=>location.reload();
  document.body.prepend(b);
}

// ── live status: feed heartbeat + ticking countdown ──
let nextScanAt = 0, clockSkew = 0;
const CAT_ICON = {graded:'💎', sealed:'📦', bulk:'🗃️', collection:'📚', single:'🃏'};
async function loadFeedStatus(){
  try{
    const s = await (await fetch('/api/feedstatus')).json();
    checkBuild(s.build);
    clockSkew = Date.now()/1000 - s.server_now;
    nextScanAt = s.next_scan_at || 0;
    const on = s.online;
    $('#feedDot').style.background = on ? 'var(--green)' : 'var(--red)';
    $('#feedDot').style.boxShadow = on ? '0 0 8px var(--green)' : '0 0 8px var(--red)';
    $('#feedState').textContent = on ? (s.state === 'scanning' ? 'ONLINE — scanning now' : 'ONLINE') : 'OFFLINE — feed not running';
    $('#lastScan').textContent = s.last_scan_end
      ? 'last scan ' + new Date(s.last_scan_end*1000).toLocaleTimeString() + ' · ' + (s.last_new ?? 0) + ' new sent'
      : '';
    $('#lanUrl').textContent = s.lan_url ? '📱 phone (same WiFi): ' + s.lan_url : '';
    const box = $('#recentBox');
    // re-render ONLY when the list actually changed — replacing innerHTML on
    // every poll destroyed the <a> mid-click, which made links "not work"
    const sig = JSON.stringify((s.recent||[]).map(r=>r.url + (r.ts||0)));
    if(sig !== box.dataset.sig){
      box.dataset.sig = sig;
      // times shown in GMT+8 (Asia/Manila) regardless of viewing device
      const fmtPH = t => new Date(t*1000).toLocaleString('en-PH',
        {timeZone:'Asia/Manila',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true});
      const srcTag = s => (s||'').startsWith('fb:')
        ? '📘 ' + escapeHtml(s.slice(3)) : '🛒 Carousell';
      box.innerHTML = (s.recent && s.recent.length) ? s.recent.map(r=>`
        <div class="wl-item">
          <div class="q">${CAT_ICON[r.category]||'🃏'} <a href="${r.url}" target="_blank" rel="noopener">${escapeHtml(r.title)}</a>
            <div class="muted" style="font-size:11px;margin-top:2px">${srcTag(r.source)}</div></div>
          <div class="muted" style="white-space:nowrap;text-align:right">${r.posted_ts ? '↑ posted ' + fmtPH(r.posted_ts) : 'seen ' + fmtPH(r.ts)}</div>
        </div>`).join('') : '<p class="muted">no listings sent yet — updates after the next scan.</p>';
    }
  }catch(e){}
}
setInterval(loadFeedStatus, 5000); loadFeedStatus();

// ── CC <-> Codex relay chatroom ──
function relayFmt(body){
  // trusted local file content (not user input) -> light markdown only,
  // still escaped first so a stray '<' in code/paths can't break the page
  let h = escapeHtml(body);
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  return h;
}
function relayWhoClass(who){
  const w = (who||'').trim().toUpperCase();
  if(w === 'CC') return 'cc';
  if(w === 'CX') return 'cx';
  return 'other';
}
let relaySig = '';
async function loadRelay(){
  try{
    const r = await (await fetch('/api/relay')).json();
    const dot = $('#relayDot'), state = $('#relayState');
    const entries = r.entries || [];
    dot.className = entries.length ? 'live' : '';
    state.textContent = r.mtime
      ? entries.length + ' messages · last update ' + new Date(r.mtime*1000).toLocaleTimeString('en-PH',{timeZone:'Asia/Manila',hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true})
      : 'AGENT-RELAY.md not found yet';
    const sig = r.mtime + ':' + entries.length;
    if(sig === relaySig) return;   // avoid nuking scroll position on unchanged polls
    relaySig = sig;
    const log = $('#relayLog');
    const wasNearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.innerHTML = entries.length ? entries.map(e => `
      <div class="relay-msg">
        <div class="relay-head">
          <span class="relay-who ${relayWhoClass(e.who)}">${escapeHtml(e.who)}</span>
          <span class="relay-when">${escapeHtml(e.when)}</span>
          ${e.note ? `<span class="relay-note">${escapeHtml(e.note)}</span>` : ''}
        </div>
        <div class="relay-body">${relayFmt(e.body)}</div>
      </div>`).join('') : '<p class="muted">no relay entries yet.</p>';
    if(wasNearBottom) log.scrollTop = log.scrollHeight;
  }catch(e){
    $('#relayState').textContent = 'offline';
    $('#relayDot').className = '';
  }
}
setInterval(loadRelay, 6000); loadRelay();

// ── card valuator ──
const dz = $('#dropZone'), cf = $('#cardFile');
dz.onclick = ()=>cf.click();
dz.ondragover = e=>{ e.preventDefault(); dz.style.borderColor='var(--accent)'; };
dz.ondragleave = ()=>{ dz.style.borderColor='var(--line)'; };
dz.ondrop = e=>{ e.preventDefault(); dz.style.borderColor='var(--line)';
  if(e.dataTransfer.files.length) valUpload(e.dataTransfer.files[0]); };
cf.onchange = ()=>{ if(cf.files.length) valUpload(cf.files[0]); };

// click the thumbnail -> full-size overlay (right-click to copy the photo)
$('#valThumb').style.cursor = 'zoom-in';
$('#valThumb').title = 'click to enlarge (right-click the big view to copy)';
$('#valThumb').onclick = ()=>{
  if(!$('#valThumb').src) return;
  $('#lightboxImg').src = $('#valThumb').dataset.full || $('#valThumb').src;
  $('#lightbox').style.display = 'flex';
};
$('#lightbox').onclick = ()=>{ $('#lightbox').style.display = 'none'; };

// shared by BOTH sources (photo upload / listing link): apply the OCR
// identification result to the UI and kick off the candidate search
async function valApplyOcr(d){
  if(d.file) $('#valThumb').dataset.full = d.file;   // server copy, survives refresh
  if(d.multi){
    // BINDER MODE: render results IN THE BINDER'S OWN LAYOUT (his spec) —
    // each pocket clickable to identify/value, 🔍 zoomable, and the
    // side-by-side eye-gate compares THAT CELL as "your card"
    const cards = d.cards || [];
    const cols = d.cols || 2;
    $('#valMsg').textContent = '📒 binder page — ' + cards.length
      + ' cards. Tap a pocket to identify & value that card; 🔍 zooms it for stamps/edges.';
    // COMPACT (his fix list #1): capped width, ~55% smaller pockets — the
    // page must fit a normal monitor at 100% zoom. Renders into #valBinder
    // (fix #2): searches never touch it; only ✕ Clear removes it.
    $('#valBinder').innerHTML = `
      <div style="max-width:${cols === 1 ? 240 : 480}px;background:linear-gradient(180deg,#23272f,#1a1d24);border:1px solid var(--line);border-radius:14px;padding:12px;box-shadow:inset 0 0 24px rgba(0,0,0,.45)">
        <div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:10px">
        ${cards.map((c,i)=>`
          <div class="bcell" data-i="${i}"
               style="position:relative;background:#14171c;border:1px solid var(--line);border-radius:9px;padding:6px;cursor:pointer;text-align:center;transition:transform .12s"
               onmouseover="this.style.transform='translateY(-2px)'" onmouseout="this.style.transform=''">
            <img src="${c.cell||''}" style="width:100%;max-height:200px;object-fit:contain;border-radius:5px" loading="lazy"
                 onerror="this.style.display='none'">
            <div style="font-size:11px;margin-top:4px;font-weight:600">${escapeHtml(c.name||'(unread — tap 🔍, then type it)')}</div>
            <div class="muted" style="font-size:10px">${c.number
                ? '#'+escapeHtml(c.number)+(c.via?' · '+escapeHtml(c.via):'')
                : (c.candidates && c.candidates.length)
                  ? `⚠ ${c.candidates.length} possible printings — tap to pick`
                  : (c.name ? 'printing unread — tap to search' : '#?')}</div>
            <div style="margin-top:3px">${evidenceBadge(c, true)}</div>
            <button class="bzoom" data-img="${c.cell||''}" title="zoom this card"
              style="position:absolute;top:4px;right:4px;border:none;border-radius:6px;padding:1px 6px;cursor:zoom-in;background:rgba(0,0,0,.55);color:#fff;font-size:12px">🔍</button>
          </div>`).join('')}
        </div>
      </div>`;
    window._binderCards = cards;
    document.querySelectorAll('.bzoom').forEach(el=>el.onclick=(ev)=>{
      ev.stopPropagation();
      $('#lightboxImg').src = el.dataset.img;
      $('#lightbox').style.display = 'flex';
    });
    document.querySelectorAll('.bcell').forEach(el=>el.onclick=()=>{
      if(window._valBusy) return;              // fix #5: no mid-search starts
      const c = (window._binderCards||[])[+el.dataset.i] || {};
      valResetSearch();                        // fix #4: clean search state
      // the eye-gate must compare THIS card's crop, not the whole page
      if(c.cell){ $('#valThumb').src = c.cell; $('#valThumb').dataset.full = c.cell; }
      window._jpHint = !!c.jp;
      $('#valQuery').value = c.query || '';
      if(c.number && c.candidates && c.candidates.length){
        // fully pinned — server already dropped candidates, so a plain
        // Find-card search is fine and cheap
        if(c.query) valFind();
      } else if(!c.number && c.candidates && c.candidates.length){
        // AMBIGUOUS: render the server's GUARANTEED candidates directly —
        // a fresh name-only search can miss the real promo entirely
        renderCandidateGrid(c.candidates, true);
      } else if(c.query){
        valFind();
      } else {
        $('#valMsg').textContent = 'that card did not read — type its name or the footer, then Find card';
      }
    });
    return;
  }
  window._jpHint = !!d.jp;   // unreadable name = non-English card, rank JP first
  $('#valQuery').value = d.query || '';
  // the message always states BOTH what was identified and what's missing,
  // so name-path vs number-path never looks arbitrary
  if(d.via && d.number)
    $('#valMsg').textContent = '✅ card: "' + d.name + '" (' + d.via + ') + printing #' + d.number
      + (d.snapped ? ' (read #' + d.number_read + ', auto-corrected — only valid printing)' : '')
      + (d.jp ? ' · Japanese' : '');
  else if(d.via)
    $('#valMsg').textContent = '✅ card identified by ' + d.via + ': "' + d.name + '"'
      + (d.jp ? ' (Japanese)' : '') + ' — exact PRINTING unknown: tap yours below, or drop a footer close-up';
  else if(d.number && !d.name)
    $('#valMsg').textContent = '✅ printing number ' + d.number + ' read — card NAME unknown: '
      + 'tap yours below, or add the set code (e.g. m1s ' + d.number + ')';
  else if(d.query)
    $('#valMsg').textContent = 'read: "' + d.query + '" — fix it if wrong, then Find card';
  else
    $('#valMsg').textContent = 'could not read it — type the name, or the set code + number from the card\'s bottom edge (e.g. sm12a 016/173)';
  $('#valEvidence').innerHTML = evidenceBadge(d, false);
  if(d.query) await valFind();
}

// fix #4: every NEW search starts from a clean slate — but NEVER touches
// the uploaded images (#valThumb / #valBinder); those are ✕ Clear-only
function valResetSearch(){
  $('#valQuery').value = '';
  $('#valCands').innerHTML = '';
  $('#valResult').innerHTML = '';
  $('#valMsg').textContent = '';
  $('#valEvidence').innerHTML = '';
  window._cands = {};
}

// fix #3: the ONLY thing that removes uploaded images
function valClearAll(){
  valResetSearch();
  $('#valBinder').innerHTML = '';
  $('#valThumb').src = ''; $('#valThumb').removeAttribute('src');
  delete $('#valThumb').dataset.full;
  $('#valQueryRow').classList.add('hidden');
  $('#valUrl').value = '';
  cf.value = '';                              // same file re-uploadable
  dz.style.borderColor = 'var(--line)';       // reset drag state
  window._binderCards = null; window._jpHint = false;
}
$('#valClear').onclick = valClearAll;

async function valUpload(file){
  if(window._valBusy) return;
  $('#valQueryRow').classList.remove('hidden');
  valResetSearch();
  $('#valThumb').src = URL.createObjectURL(file);
  $('#valMsg').innerHTML = '<span class="spin"></span> reading card…';
  valBusy(true);
  const fd = new FormData(); fd.append('photo', file);
  try{
    const d = await (await fetch('/api/valuator/ocr',{method:'POST',body:fd})).json();
    await valApplyOcr(d);
  }catch(e){ $('#valMsg').textContent = 'upload failed: ' + e; }
  finally{ valBusy(false); }
}

// LINK AS SOURCE (his 7/17 request): paste a Carousell listing link —
// the system pulls the listing's photos itself, then the same stack runs
async function valFromUrl(){
  if(window._valBusy) return;
  const url = $('#valUrl').value.trim();
  if(!/^https?:\/\//.test(url)){ $('#valMsg').textContent = 'paste a full link (https://…)'; return; }
  $('#valQueryRow').classList.remove('hidden');
  valResetSearch();
  valBusy(true);
  $('#valMsg').innerHTML = '<span class="spin"></span> fetching listing photos + reading (can take ~30s)…';
  try{
    const r = await fetch('/api/valuator/from_url', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({url})});
    const d = await r.json();
    if(d.error){ $('#valMsg').textContent = '⚠ ' + d.error; return; }
    if(d.file){ $('#valThumb').src = d.file; }
    await valApplyOcr(d);
  }catch(e){ $('#valMsg').textContent = 'link fetch failed: ' + e; }
  finally{ valBusy(false); }
}
$('#valFromUrl').onclick = valFromUrl;
$('#valUrl').onkeydown = e=>{ if(e.key==='Enter') valFromUrl(); };

// DIRECTIVE.md: Evidence Level badge + chain + failure/inference detail.
// "Users should never need to inspect logs to understand why a card was
// classified" — this is the whole reason this function exists.
const EV_COLOR = {A:'#3ddc84', B:'#5b9cff', C:'#e8a33d', D:'#ff8a3d', E:'#ff5c5c'};
const EV_MARK  = {confirmed:'✓', inferred:'≈', failed:'✗', seen_not_itemized:'~', not_verified:'?', not_checked:'·'};
const EV_MARKCOLOR = {confirmed:'#3ddc84', inferred:'#e8a33d', failed:'#ff5c5c', seen_not_itemized:'#5b9cff', not_verified:'#8f98a8', not_checked:'#666'};
function evidenceBadge(d, compact){
  if(!d || !d.evidence_level) return '';
  const color = EV_COLOR[d.evidence_level] || '#888';
  const coverage = Number.isFinite(+d.evidence_coverage) ? +d.evidence_coverage : 0;
  const prediction = Number.isFinite(+d.provisional_prediction_confidence) ? +d.provisional_prediction_confidence : 0;
  const badge = `<span title="${escapeHtml(d.evidence_level_meaning||'')}" style="display:inline-flex;align-items:center;gap:4px;background:${color}22;border:1px solid ${color};color:${color};border-radius:999px;padding:1px 8px;font-size:11px;font-weight:700;letter-spacing:.02em;white-space:nowrap">Level ${d.evidence_level} · coverage ${coverage}% · provisional prediction ${prediction}%</span>`;
  if(compact) return badge;
  const chain = d.evidence_chain || {};
  const chainRows = Object.keys(chain).map(k=>{
    const v = chain[k];
    return `<tr><td style="padding:2px 8px;color:${EV_MARKCOLOR[v.status]||'#666'};font-weight:700">${EV_MARK[v.status]||'·'}</td>`
      + `<td style="padding:2px 8px;text-transform:capitalize;white-space:nowrap">${k.replace(/_/g,' ')}</td>`
      + `<td style="padding:2px 8px;font-size:11px" class="muted">${escapeHtml(v.note||'')}</td></tr>`;
  }).join('');
  let extra = '';
  if(d.inference_explanation){
    const ie = d.inference_explanation;
    extra = `<div style="margin-top:6px;font-size:11px" class="muted">`
      + `<b>Why OCR needed forcing:</b> ${escapeHtml(ie.why_ocr_failed||'')}<br>`
      + `<b>Forcing logic:</b> ${escapeHtml(ie.why_only_one_candidate_remained||'')}<br>`
      + `<b>Remaining uncertainty:</b> ${escapeHtml(ie.remaining_uncertainty||'')}</div>`;
  }
  if(d.failure_report){
    const fr = d.failure_report;
    const helps = Object.keys(fr).filter(k=>k.startsWith('would_') && fr[k])
      .map(k=>k.replace('would_','').replace(/_/g,' ').replace(' help',''));
    extra = `<div style="margin-top:6px;font-size:11px" class="muted">`
      + `<b>Missing:</b> ${escapeHtml(fr.missing_feature||'')}<br>`
      + `<b>Blocked by:</b> ${escapeHtml(fr.blocking_evidence||'')}<br>`
      + (helps.length ? `<b>Would help:</b> ${escapeHtml(helps.join(', '))}` : '') + `</div>`;
  }
  const collision = d.collision_analysis || {};
  const adversarial = d.adversarial_validation || {};
  const strongest = adversarial.strongest_alternative;
  extra += `<div style="margin-top:6px;font-size:11px" class="muted">`
    + `<b>Collision search:</b> ${escapeHtml(collision.collision_status||'not run')} — ${escapeHtml(collision.reason||'')}<br>`
    + `<b>Strongest alternative:</b> ${strongest ? escapeHtml((strongest.name||'?')+' #'+(strongest.number||'?')+' ('+(strongest.set||'?')+')') : 'none found'}<br>`
    + `<b>What would overturn this:</b> ${escapeHtml(adversarial.what_would_overturn_this||'')}</div>`;
  const factors = d.provisional_prediction_confidence_factors || [];
  if(factors.length){
    extra += `<div style="margin-top:6px;font-size:11px" class="muted"><b>Provisional prediction factors:</b><br>${factors.map(escapeHtml).join('<br>')}</div>`;
  }
  return `<details style="border:1px solid var(--line);border-radius:8px;padding:6px 10px">
    <summary style="cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px">${badge}
      <span class="muted" style="font-size:11px">evidence chain — click to expand</span></summary>
    <table style="margin-top:6px;border-collapse:collapse">${chainRows}</table>
    ${extra}
  </details>`;
}

// shared by valFind() AND binder-pocket taps — renders a candidate grid
// for eye-gate picking. Binder taps pass server-guaranteed candidates
// directly (bypassing a fresh search) because a bare-name TCGplayer search
// can bury or omit the real promo printing entirely (confirmed live:
// Victini/Manaphy's actual promos never appeared in the default top 12
// results for their plain names) — the merge that fixes this lives in
// identify(), not in the plain /api/valuator/search route, so re-searching
// from a tapped pocket would silently lose it.
function renderCandidateGrid(c, ambiguousNumberHint){
  const sameName = c.filter(x=>x.name.split(' - ')[0] === (c[0]&&c[0].name.split(' - ')[0])).length;
  $('#valMsg').textContent = c.length
    ? (ambiguousNumberHint ? 'multiple printings read off this card — tap YOUR exact one:'
       : sameName >= 4 ? 'tap YOUR exact printing — or drop a CLOSE-UP of the card\'s bottom-left footer to pin it automatically:'
                     : 'tap YOUR exact card:')
    : 'nothing found — check the name, or type the set code + number from the card\'s bottom edge (e.g. sm12a 016/173)';
  window._cands = {};
  c.forEach(x=>window._cands[x.pid]=x);
  $('#valCands').innerHTML = c.map(x=>`
    <div class="cand" data-pid="${x.pid}" style="cursor:pointer;text-align:center;border:1px solid var(--line);border-radius:8px;padding:8px">
      <img src="${x.img}" style="width:100%;border-radius:6px" loading="lazy"
           onerror="this.style.display='none'">
      <div style="font-size:12px;margin-top:5px">${escapeHtml(cardLabel(x))}</div>
      <div class="muted" style="font-size:11px">${escapeHtml(x.set)}<br>#${escapeHtml(x.number)}${x.market?' · $'+x.market:''}</div>
    </div>`).join('');
  document.querySelectorAll('.cand').forEach(el=>el.onclick=()=>valConfirm(+el.dataset.pid));
}

async function valFind(){
  const q = $('#valQuery').value.trim();
  if(q.length < 2) return;
  valBusy(true);            // lock the box — typing mid-search interrupts it
  $('#valMsg').innerHTML = '<span class="spin"></span> searching…';
  $('#valResult').innerHTML = '';
  let d = {};
  try{
    d = await (await fetch('/api/valuator/search?q=' + encodeURIComponent(q)
                               + (window._jpHint ? '&jp=1' : ''))).json();
  }catch(e){}
  finally{ valBusy(false); }
  renderCandidateGrid(d.candidates || []);
}
// fixes #5/#6: user-initiated triggers are hard-blocked while processing
$('#valSearch').onclick = ()=>{ if(!window._valBusy) valFind(); };
$('#valQuery').onkeydown = e=>{ if(e.key==='Enter' && !window._valBusy) valFind(); };

// searching state: lock everything so a second search can't start, and
// SAY WHY on hover instead of looking broken (fix #6)
const BUSY_TIP = 'Please wait. Card identification is currently in progress. '
  + 'Searching is temporarily disabled until processing is complete.';
function valBusy(b){
  window._valBusy = b;
  for(const id of ['valQuery','valSearch','valUrl','valFromUrl']){
    const el = $('#'+id);
    el.disabled = b;
    if(b) el.title = BUSY_TIP;
    else el.removeAttribute('title');
  }
}

// language-aware full display name ("Japanese Mega Manectric ex")
function cardLabel(cd){
  // NB: TCGplayer returns the DISPLAY name 'Pokemon Japan', not the slug
  // 'pokemon-japan' — exact-compare never matched (V0.6 missing-prefix bug)
  const jp = /japan/i.test(cd.line||'') || /japan/i.test(cd.set||'');
  return (jp ? 'Japanese ' : '') + (cd.name||'').split(' - ')[0];
}

// side-by-side confirmation before valuation — user's eye is the last gate
let cmpPid = null;
function valConfirm(pid){
  const cd = (window._cands||{})[pid] || {};
  cmpPid = pid;
  $('#cmpTitle').textContent = cardLabel(cd) + ' — ' + (cd.set||'') + ' #' + (cd.number||'?');
  $('#cmpMine').src = $('#valThumb').dataset.full || $('#valThumb').src || '';
  // full-size scan for stamp inspection; fall back to the thumbnail
  const big = 'https://product-images.tcgplayer.com/fit-in/874x1214/' + pid + '.jpg';
  $('#cmpTheir').onerror = ()=>{ $('#cmpTheir').onerror=null; $('#cmpTheir').src = cd.img||''; };
  $('#cmpTheir').src = big;
  cmpResetZoom();                        // every confirm starts unzoomed
  $('#cmpModal').style.display = 'flex';
}
$('#cmpYes').onclick = async ()=>{
  $('#cmpModal').style.display='none';
  const cd = (window._cands||{})[cmpPid] || {};
  const image = $('#valThumb').dataset.full || '';
  try{ await fetch('/api/valuator/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image,candidate:{name:cd.name,number:cd.number}})}); }catch(e){}
  if(cmpPid) valPick(cmpPid);
};
$('#cmpNo').onclick  = ()=>{ $('#cmpModal').style.display='none'; };
$('#cmpModal').onclick = e=>{ if(e.target === $('#cmpModal')) $('#cmpModal').style.display='none'; };

// magnifying glass: CLICK to zoom in/out (no surprise hover zoom), slider
// sets the level, mouse-move pans while zoomed
let cmpZoom = 2.5;
$('#cmpZoom').oninput = e=>{
  cmpZoom = +e.target.value;
  $('#cmpZoomLbl').textContent = cmpZoom.toFixed(1) + '×';
  document.querySelectorAll('.cmp-imgwrap img').forEach(img=>{
    if(img.dataset.zoomed) img.style.transform = 'scale(' + cmpZoom + ')';
  });
};
function cmpResetZoom(){
  document.querySelectorAll('.cmp-imgwrap img').forEach(img=>{
    img.dataset.zoomed=''; img.style.transform='scale(1)'; img.style.cursor='zoom-in';
  });
}
document.querySelectorAll('.cmp-imgwrap').forEach(w=>{
  const img = w.querySelector('img');
  w.onmousemove = e=>{
    if(!img.dataset.zoomed) return;      // pan only while zoomed
    const r = w.getBoundingClientRect();
    img.style.transformOrigin = ((e.clientX-r.left)/r.width*100)+'% '+((e.clientY-r.top)/r.height*100)+'%';
  };
  w.onclick = ()=>{                      // click toggles the lens
    img.dataset.zoomed = img.dataset.zoomed ? '' : '1';
    img.style.transform = img.dataset.zoomed ? 'scale('+cmpZoom+')' : 'scale(1)';
    img.style.cursor = img.dataset.zoomed ? 'zoom-out' : 'zoom-in';
  };
});

const VOL_C = {Stable:'var(--green)', Moderate:'#ffb454', Volatile:'var(--red)', Unknown:'var(--muted)'};

function priceHistoryChart(sales){
  const asc = [...sales].filter(s=>s.usd !== null && s.usd !== undefined && s.date)
    .sort((a,b)=>(a.date||'').localeCompare(b.date||''));
  if(!asc.length) return '';
  const width=640, left=42, right=10, top=12, lineBottom=112, volumeTop=134, bottom=178;
  const plotW=width-left-right, max=Math.max(...asc.map(s=>+s.usd),1);
  const counts={}; asc.forEach(s=>{counts[s.date]=(counts[s.date]||0)+1;});
  const dates=Object.keys(counts), maxCount=Math.max(...Object.values(counts),1);
  // Keep same-day sales visible as separate observations. Dates remain the
  // axis buckets, but observations within a bucket get a small deterministic
  // spread so the plotted count matches the caption.
  const xFor=(dateIndex, ordinal)=>{
    const center=left+(dates.length===1?plotW/2:dateIndex*plotW/(dates.length-1));
    const bucket=counts[dates[dateIndex]];
    const spread=Math.min(14, Math.max(4, plotW/(Math.max(dates.length,2)*8)));
    return bucket<=1 ? center : center-spread/2 + ordinal*spread/(bucket-1);
  };
  const y=v=>lineBottom-(+v/max)*(lineBottom-top);
  let seen={};
  const points=asc.map(s=>{const di=dates.indexOf(s.date), oi=seen[s.date]||0; seen[s.date]=oi+1; return `${xFor(di,oi).toFixed(1)},${y(s.usd).toFixed(1)}`;}).join(' ');
  seen={};
  const dots=asc.map(s=>{const di=dates.indexOf(s.date), oi=seen[s.date]||0; seen[s.date]=oi+1; return `<circle cx="${xFor(di,oi).toFixed(1)}" cy="${y(s.usd).toFixed(1)}" r="3" fill="var(--viz-series-1)" aria-label="${escapeHtml(s.date)} $${s.usd}"/>`;}).join('');
  const bars=dates.map((d,i)=>{const h=Math.max(3,counts[d]/maxCount*28);return `<rect x="${(xFor(i,0)-5).toFixed(1)}" y="${(volumeTop+28-h).toFixed(1)}" width="10" height="${h.toFixed(1)}" fill="var(--viz-series-2)" opacity=".7"><title>${escapeHtml(d)}: ${counts[d]} sale${counts[d]===1?'':'s'}</title></rect>`;}).join('');
  const labels=dates.map((d,i)=>`<text x="${xFor(i,0).toFixed(1)}" y="${bottom}" text-anchor="middle" class="ph-axis">${escapeHtml(d.slice(5))}</text>`).join('');
  return `<div style="margin-top:10px;font-size:11px"><span class="muted">price history · ${asc.length} real sales</span>
    <svg viewBox="0 0 ${width} ${bottom+8}" role="img" aria-label="TCGplayer-style price history line graph with sale volume" style="width:100%;height:auto;display:block">
      <line x1="${left}" y1="${top}" x2="${left}" y2="${lineBottom}" stroke="var(--line)"/><line x1="${left}" y1="${lineBottom}" x2="${width-right}" y2="${lineBottom}" stroke="var(--line)"/><line x1="${left}" y1="${volumeTop+28}" x2="${width-right}" y2="${volumeTop+28}" stroke="var(--line)"/>
      <text x="2" y="${top+4}" class="ph-axis">$${max.toFixed(2)}</text><text x="2" y="${lineBottom+4}" class="ph-axis">$0</text><text x="2" y="${volumeTop+24}" class="ph-axis">sales</text>
      ${bars}<polyline points="${points}" fill="none" stroke="var(--viz-series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>${dots}${labels}
    </svg></div>`;
}

async function valPick(pid){
  $('#valResult').innerHTML = '<p class="muted"><span class="spin"></span> pricing from real sales…</p>';
  const v = await (await fetch('/api/valuator/value?pid=' + pid)).json();
  const CONF_C = {HIGH:'var(--green)', MED:'var(--accent)', LOW:'var(--red)'};
  const conds = Object.entries(v.by_condition||{});
  const cd = (window._cands||{})[pid] || {};
  let pcUrl = v.pricecharting_url || '';
  if(!pcUrl && cd.name){
    try{
      const pcResp = await fetch('/api/pricecharting?title=' + encodeURIComponent(cardLabel(cd)+' '+(cd.number||'')));
      const pcData = await pcResp.json();
      pcUrl = pcData.url || '';
    }catch(e){}
  }
  const vol = v.volatility || {label:'Unknown', note:''};
  $('#valResult').innerHTML = `
    <div style="border:1px solid var(--line);border-radius:10px;padding:14px">
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:10px">
        ${cd.img?`<img src="${cd.img}" style="height:86px;border-radius:6px">`:''}
        <div>
          <div style="font-weight:700">${escapeHtml(cardLabel(cd))}</div>
          <div class="muted" style="font-size:12px">${escapeHtml(cd.set||'')} · #${escapeHtml(cd.number||'')}
            ${cd.url?` · <a href="${cd.url}" target="_blank" rel="noopener" style="color:var(--accent)">TCGplayer ↗</a>`:''}
            ${pcUrl?` · <a href="${pcUrl}" target="_blank" rel="noopener" style="color:var(--accent)">PriceCharting ↗</a>`:''}</div>
        </div>
      </div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <b>Market ${v.market_php?('₱'+fmt(v.market_php)+' ($'+v.market_usd+' TCGplayer)'):'—'}</b>
        <span class="badge" style="color:${CONF_C[v.confidence]||''}">confidence: ${v.confidence}</span>
        ${v.usd_rate?`<span class="muted" style="font-size:12px" title="${v.usd_rate_stale?'Last-known-good rate; refresh failed':'Fetched live'}">USD/PHP ${v.usd_rate.toFixed(2)}${v.usd_rate_stale?' (stale)':''}</span>`:''}
        <span class="vol-badge" style="color:${VOL_C[vol.label]};border-color:${VOL_C[vol.label]}" title="${escapeHtml(vol.note||'')}">${vol.label==='Unknown'?'volatility: unknown':'volatility: '+vol.label}</span>
        <span class="muted" style="font-size:12px">${escapeHtml(v.confidence_why||'')}</span>
      </div>
      ${(v.market_fetch&&v.market_fetch.status==='failed')?`<div style="margin-top:8px;color:var(--red);font-size:12px">Market price unavailable: ${escapeHtml(v.market_fetch.error||'TCGplayer fetch failed after retry')}.</div>`:''}
      ${(v.sales_fetch&&v.sales_fetch.status==='failed')?`<div style="margin-top:10px;color:var(--red)">Sales history unavailable: ${escapeHtml(v.sales_fetch.error||'TCGplayer fetch failed after retry')}. This does not mean the card has no sales.</div>`:priceHistoryChart(v.sales||[])}
      <table style="width:100%;margin-top:10px;font-size:13px;border-collapse:collapse">
        <tr class="muted"><td>Condition</td><td>Worth</td><td>List (×${v.ph_factor})</td><td>Steal ≤</td><td>Based on</td></tr>
        ${conds.map(([c,x])=>`<tr>
          <td style="padding:3px 0">${c}</td><td>₱${fmt(x.php)} <span class="muted">($${x.usd})</span></td>
          <td>₱${fmt(v.suggest[c].list_php)}</td><td>₱${fmt(v.suggest[c].steal_php)}</td>
          <td class="muted">${x.from}</td></tr>`).join('')}
      </table>
      ${(v.sales_fetch&&v.sales_fetch.status==='failed')?'':(v.sales&&v.sales.length)?`<div class="muted" style="margin-top:10px;font-size:12px">
        last real sales: ${v.sales.slice(0,6).map(s=>`${s.date} $${s.usd} <i>${(s.condition||'').split(' ').map(w=>w[0]).join('')}</i>`).join(' · ')}
      </div>`:'<div class="muted" style="margin-top:10px;font-size:12px">no recorded recent sales — prices are estimates.</div>'}
      <div class="muted" style="margin-top:8px;font-size:12px">⚠️ check condition yourself: corners/edges for whitening FIRST — assume LP until it proves NM.</div>
    </div>`;
}

// ── restart buttons ──
async function restartTarget(target){
  if(!confirm('Restart the ' + target + '? It comes back automatically in ~30 seconds.')) return;
  const r = await fetch('/api/restart',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({target})});
  const d = await r.json().catch(()=>({}));
  $('#restartMsg').textContent = d.msg || d.error || 'requested';
  setTimeout(()=>{ $('#restartMsg').textContent=''; }, 40000);
}
$('#restartFeed').onclick = ()=>restartTarget('feed');
$('#restartDash').onclick = ()=>restartTarget('dashboard');

setInterval(()=>{
  const el = $('#countdown');
  if(!nextScanAt){ el.textContent = '--:--'; return; }
  const left = Math.max(0, Math.round(nextScanAt - (Date.now()/1000 - clockSkew)));
  el.textContent = String(Math.floor(left/60)).padStart(2,'0') + ':' + String(left%60).padStart(2,'0');
}, 1000);

loadSettings();
</script>
</body></html>"""

if __name__ == "__main__":
    threading.Thread(target=_watchdog, daemon=True).start()
    print("Dashboard running at  http://127.0.0.1:5000")
    print(f"Phone (same WiFi):    http://{_lan_ip()}:5000")
    # 0.0.0.0 exposes the dashboard on the local network (phone access).
    app.run(host="0.0.0.0", port=5000, debug=False)
