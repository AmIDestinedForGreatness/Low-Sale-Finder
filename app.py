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
import engine
from version import VERSION

STATUS_PATH = os.path.join(os.path.dirname(__file__), "feed_status.json")


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
                                   "Check the 'Sniper Feed' window on the PC.",
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
@app.route("/")
def index():
    return Response(HTML.replace("__VERSION__", VERSION), mimetype="text/html")

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
    return jsonify({
        "online": online,
        "state": s.get("state", "unknown"),
        "next_scan_at": s.get("next_scan_at") or 0,
        "last_scan_end": s.get("last_scan_end"),
        "last_new": s.get("last_new"),
        "recent": (s.get("recent") or [])[:8],
        "poll_minutes": config.POLL_INTERVAL_MINUTES,
        "version": VERSION,
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
        "usd_to_local": config.USD_TO_LOCAL_RATE,
        "default_below_pct": round((1 - config.ALERT_AT_OR_BELOW_FRACTION) * 100),
    })

@app.route("/api/webhook", methods=["POST"])
def set_webhook():
    """Link a Discord webhook from the UI: validate, send a test ping,
    persist into config.py (gitignored) and the running process."""
    url = (request.get_json(force=True).get("url") or "").strip()
    if not re.match(r"^https://(discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)/api/webhooks/\d+/", url):
        return jsonify({"error": "That doesn't look like a Discord webhook URL. It should start with https://discord.com/api/webhooks/…"}), 400
    try:
        r = requests.post(url, json={"content": "✅ Carousell Sniper linked — deal alerts will arrive in this channel."}, timeout=10)
        if r.status_code not in (200, 204):
            return jsonify({"error": f"Discord rejected it (status {r.status_code}) — copy the URL again."}), 400
    except Exception as e:
        return jsonify({"error": f"Couldn't reach Discord: {e}"}), 400
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
    --bg:#0a0e1e; --panel:#121730; --panel2:#1a2140; --line:#252d52;
    --ink:#e8eaed; --muted:#8f9ab8; --accent:#2ab8f6; --accent2:#3b6cff;
    --green:#2ecc71; --red:#e74c3c; --radius:14px;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  header{padding:22px 28px;border-bottom:1px solid var(--line);
    display:flex;align-items:center;gap:14px}
  header h1{font-size:18px;margin:0;font-weight:650;letter-spacing:.2px}
  .badge{font-size:12px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
  .badge.ok{color:var(--green);border-color:#1f5132}
  .badge.no{color:var(--red);border-color:#5a2520}
  main{max-width:980px;margin:0 auto;padding:24px;display:grid;gap:20px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:20px}
  .card h2{margin:0 0 14px;font-size:14px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}
  label{display:block;font-size:13px;color:var(--muted);margin:0 0 5px}
  input[type=text],input[type=number],textarea{
    width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--ink);
    border-radius:10px;padding:10px 12px;font:inherit;outline:none}
  input:focus,textarea:focus{border-color:var(--accent2)}
  textarea{resize:vertical;min-height:70px}
  .row{display:flex;gap:14px;flex-wrap:wrap}
  .row>div{flex:1;min-width:130px}
  .slider-val{color:var(--accent);font-weight:700}
  button{cursor:pointer;border:none;border-radius:10px;padding:11px 18px;font:inherit;font-weight:600}
  .btn-primary{background:var(--accent);color:#1a1a00}
  .btn-primary:hover{filter:brightness(1.08)}
  .btn-ghost{background:var(--panel2);color:var(--ink);border:1px solid var(--line)}
  .btn-ghost:hover{border-color:var(--accent2)}
  .btn-row{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}
  .check{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}
  .check input{width:auto}
  .deal{border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:10px;
    display:flex;justify-content:space-between;gap:14px;align-items:flex-start;background:var(--panel2)}
  .deal.steal{border-color:#7a3128;box-shadow:0 0 0 1px #7a312855 inset}
  .deal a{color:var(--ink);text-decoration:none;font-weight:600}
  .deal a:hover{color:var(--accent)}
  .deal .meta{font-size:13px;color:var(--muted);margin-top:4px}
  .pct{font-size:20px;font-weight:800;white-space:nowrap}
  .pct.steal{color:var(--red)} .pct.deal{color:var(--green)}
  .tag{font-size:11px;padding:2px 8px;border-radius:999px;background:#0c0e12;border:1px solid var(--line);color:var(--muted);margin-left:6px}
  #log{font:12px/1.45 ui-monospace,Menlo,monospace;background:#0b0d11;border:1px solid var(--line);
    border-radius:10px;padding:12px;max-height:180px;overflow:auto;color:#8fa1bd;white-space:pre-wrap}
  .wl-item{display:flex;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line)}
  .wl-item:last-child{border-bottom:none}
  .wl-item .q{flex:1}
  .muted{color:var(--muted);font-size:13px}
  .spin{display:inline-block;width:13px;height:13px;border:2px solid var(--muted);
    border-top-color:var(--accent);border-radius:50%;animation:s .7s linear infinite;vertical-align:-2px}
  @keyframes s{to{transform:rotate(360deg)}}
  .hidden{display:none}
</style></head>
<body>
<main>

  <div style="text-align:center;padding:10px 0 4px">
    <img src="/logo" alt="Yujin's Pokestop" style="height:190px;max-width:90%;display:none"
         onload="this.style.display='inline-block'">
    <div style="display:flex;gap:8px;justify-content:center;margin-top:10px;flex-wrap:wrap">
      <span class="badge" style="color:var(--accent);border-color:var(--accent)">V__VERSION__</span>
      <span id="webhookBadge" class="badge">checking…</span>
      <span id="srcBadge" class="badge"></span>
      <span id="ctryBadge" class="badge"></span>
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
    <h2>📈 Last 7 days</h2>
    <div id="statDays" style="display:flex;gap:8px;align-items:flex-end;height:90px;margin-top:6px"></div>
    <div id="statCats" style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap"></div>
  </section>

  <section class="card">
    <h2>Discord alerts</h2>
    <p class="muted" style="margin:0 0 12px">
      In Discord: your server → <b>⚙ Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL</b> — then paste it here.
    </p>
    <div class="row">
      <div style="flex:3"><input type="text" id="whUrl" placeholder="https://discord.com/api/webhooks/…"></div>
      <div style="flex:0;min-width:auto"><button class="btn-primary" id="whSave">Link + test ping</button></div>
    </div>
    <div id="whMsg" class="muted" style="margin-top:8px"></div>
  </section>

  <section class="card">
    <h2>Scan categories</h2>
    <div class="row" style="margin-top:14px">
      <div>
        <label>Alert when listing is <span id="belowLbl" class="slider-val">20%</span> under market</label>
        <input type="range" id="below" min="1" max="95" value="20" style="width:100%">
      </div>
    </div>
    <div class="btn-row">
      <button class="btn-primary" id="scrapeBtn">Scan categories</button>
      <label class="check"><input type="checkbox" id="push"> Send results to Discord</label>
      <span id="status" class="muted"></span>
    </div>
  </section>

  <section class="card">
    <h2>Results <span id="resLabel" class="muted"></span></h2>
    <div id="results"><p class="muted">No scan run yet.</p></div>
  </section>

  <section class="card">
    <h2>Activity log</h2>
    <div id="log">idle.</div>
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
  $('#below').value = s.default_below_pct; $('#belowLbl').textContent = s.default_below_pct + '%';
}
$('#below').oninput = e => $('#belowLbl').textContent = e.target.value + '%';

$('#whSave').onclick = async ()=>{
  const url = $('#whUrl').value.trim();
  if(!url){ alert('Paste your webhook URL first.'); return; }
  $('#whSave').disabled = true; $('#whMsg').textContent = 'testing…';
  try{
    const r = await fetch('/api/webhook',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url})});
    const d = await r.json();
    if(r.ok){
      $('#whMsg').textContent = '✅ Linked and saved — check your Discord channel for the test ping.';
      $('#whUrl').value = '';
      loadSettings();
    } else {
      $('#whMsg').textContent = '❌ ' + (d.error || 'failed');
    }
  } catch(e){ $('#whMsg').textContent = '❌ ' + e; }
  $('#whSave').disabled = false;
};

function renderDeals(deals, label){
  $('#resLabel').textContent = label ? '· ' + label : '';
  const box = $('#results');
  if(!deals.length){ box.innerHTML = '<p class="muted">No listings under your threshold this run.</p>'; return; }
  box.innerHTML = deals.map(d => `
    <div class="deal ${d.steal?'steal':''}">
      <div style="flex:1">
        <a href="${d.url}" target="_blank" rel="noopener">${escapeHtml(d.title)}</a>
        ${d.pushed?'<span class="tag">sent ✓</span>':''}
        <div class="meta">Listed <b>${fmt(d.price)}</b> · market ~${fmt(d.market)}${d.posted?' · '+(d.bumped?'bumped · ':'')+escapeHtml(d.posted):''} · <span class="muted">${escapeHtml(d.label)}</span></div>
      </div>
      <div class="pct ${d.steal?'steal':'deal'}">${Math.round(d.pct_off)}%<div style="font-size:11px;font-weight:500;color:var(--muted)">off</div></div>
    </div>`).join('');
}
function fmt(n){ return Number(n).toLocaleString(undefined,{maximumFractionDigits:0}); }
function escapeHtml(s){ return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function startPolling(){
  if(poll) clearInterval(poll);
  poll = setInterval(async ()=>{
    const s = await (await fetch('/api/scrape/status')).json();
    $('#log').textContent = (s.log||[]).join('\n') || 'idle.';
    $('#log').scrollTop = $('#log').scrollHeight;
    if(s.running){
      $('#status').innerHTML = '<span class="spin"></span> scanning…';
    } else {
      $('#status').textContent = '';
      renderDeals(s.deals||[], s.label);
      $('#scrapeBtn').disabled = false;
      clearInterval(poll); poll = null;
    }
  }, 1200);
}

$('#scrapeBtn').onclick = async ()=>{
  $('#scrapeBtn').disabled = true;
  const r = await fetch('/api/scrape',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({queries: [], below_pct:+$('#below').value, push:$('#push').checked})});
  if(!r.ok){ alert((await r.json()).error||'error'); $('#scrapeBtn').disabled=false; return; }
  startPolling();
};

// ── live status: feed heartbeat + ticking countdown ──
let nextScanAt = 0, clockSkew = 0;
const CAT_ICON = {graded:'💎', sealed:'📦', bulk:'🗃️', collection:'📚', single:'🃏'};
async function loadFeedStatus(){
  try{
    const s = await (await fetch('/api/feedstatus')).json();
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
    box.innerHTML = (s.recent && s.recent.length) ? s.recent.map(r=>`
      <div class="wl-item">
        <div class="q">${CAT_ICON[r.category]||'🃏'} <a href="${r.url}" target="_blank" rel="noopener">${escapeHtml(r.title)}</a></div>
        <div class="muted" style="white-space:nowrap">₱${fmt(r.price)} · ${escapeHtml(r.category)}</div>
      </div>`).join('') : '<p class="muted">no listings sent yet — updates after the next scan.</p>';
  }catch(e){}
}
setInterval(loadFeedStatus, 5000); loadFeedStatus();

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

// ── stats ──
async function loadStats(){
  try{
    const s = await (await fetch('/api/stats')).json();
    const max = Math.max(1, ...s.days.map(d=>d.count));
    $('#statDays').innerHTML = s.days.map(d=>`
      <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">
        <div class="muted" style="font-size:11px">${d.count}</div>
        <div style="width:100%;background:var(--accent);opacity:.85;border-radius:4px 4px 0 0;height:${Math.max(3, d.count/max*60)}px"></div>
        <div class="muted" style="font-size:11px">${d.day}</div>
      </div>`).join('');
    const IC = {graded:'💎', sealed:'📦', bulk:'🗃️', collection:'📚', single:'🃏'};
    $('#statCats').innerHTML = s.cats.length ? s.cats.map(c=>
      `<span class="badge">${IC[c.category]||'🃏'} ${escapeHtml(c.category)}: ${c.count} · avg ₱${fmt(c.avg)}</span>`).join('')
      : '<span class="muted">no data yet — fills as the feed runs.</span>';
  }catch(e){}
}
loadStats(); setInterval(loadStats, 60000);
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
