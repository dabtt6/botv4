# -*- coding: utf-8 -*-
"""
dashboard.py - Flask API server cho PikPak Bot Dashboard.
Doc config tu dashboard_config.json, expose REST API + serve HTML.
"""

import json, os, re, sqlite3, subprocess, threading, time
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "dashboard_config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

cfg = load_config()

DB_PATH        = cfg["database"]["path"]
DOWNLOAD_DIR   = cfg["paths"]["download_dir"]
MOVIES_DIR     = cfg["paths"]["movies_dir"]
CONTAINER_NAME = cfg["docker"]["container_name"]
LOG_LINES      = cfg["docker"]["log_lines"]
HOST           = cfg["server"]["host"]
PORT           = cfg["server"]["port"]

app = Flask(__name__, static_folder=os.path.dirname(__file__))

# -------------------------------------------------------
# DB HELPERS
# -------------------------------------------------------
def db_query(sql, params=()):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception as e:
        return []

# -------------------------------------------------------
# DISK SIZE HELPER
# -------------------------------------------------------
def dir_size_mb(path):
    total = 0
    try:
        for r, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(r, f))
                except:
                    pass
    except:
        pass
    return round(total / 1024 / 1024, 1)

def dir_size_gb(path):
    return round(dir_size_mb(path) / 1024, 2)

# -------------------------------------------------------
# LOG CACHE (tai load moi 5 giay)
# -------------------------------------------------------
_log_cache = {"lines": [], "ts": 0}
_log_lock  = threading.Lock()

def get_logs():
    global _log_cache
    now = time.time()
    with _log_lock:
        if now - _log_cache["ts"] < 5:
            return _log_cache["lines"]
        try:
            r = subprocess.run(
                ["docker", "logs", "--tail", str(LOG_LINES), CONTAINER_NAME],
                capture_output=True, text=True, timeout=5
            )
            raw = (r.stdout + r.stderr).splitlines()
            # Strip ANSI
            ansi = re.compile(r'\x1b\[[0-9;]*m')
            lines = [ansi.sub("", l) for l in raw if l.strip()][-LOG_LINES:]
            _log_cache = {"lines": lines, "ts": now}
            return lines
        except Exception as e:
            return [f"[ERROR] Cannot read logs: {e}"]

# -------------------------------------------------------
# API: /api/stats
# -------------------------------------------------------
@app.route("/api/stats")
def api_stats():
    # Process stats
    status_rows = db_query("SELECT status, COUNT(*) FROM process GROUP BY status")
    status_map  = {s: c for s, c in status_rows}

    # Crawl stats
    crawl_total   = (db_query("SELECT COUNT(*) FROM crawl") or [[0]])[0][0]
    torrent_total = (db_query("SELECT COUNT(*) FROM torrent") or [[0]])[0][0]
    cloud_codes   = (db_query("SELECT COUNT(DISTINCT code) FROM pikpak_cloud") or [[0]])[0][0]
    on_disk       = (db_query("SELECT COUNT(*) FROM agent_snapshot") or [[0]])[0][0]

    # Download progress: doc size thuc tu disk (downloaded_bytes trong DB co the lag)
    pending_codes = db_query("""
        SELECT p.code, p.retry_count,
               COALESCE((SELECT SUM(size_bytes) FROM pikpak_cloud WHERE code=p.code), 0) as total_bytes,
               COALESCE(p.speed_bps, 0) as speed_bps,
               COALESCE(p.eta_seconds, -1) as eta_seconds
        FROM process p
        WHERE p.status IN ('pending','downloading') AND p.on_disk=0
        ORDER BY p.updated_at DESC
    """)

    dl_items = []
    for code, retry, total, db_speed, db_eta in pending_codes:
        folder = os.path.join(DOWNLOAD_DIR, code)
        if not os.path.exists(folder):
            continue
        disk_bytes = 0
        try:
            for r, _, fs in os.walk(folder):
                for f in fs:
                    try:
                        disk_bytes += os.path.getsize(os.path.join(r, f))
                    except:
                        pass
        except:
            pass
        if disk_bytes == 0:
            continue
        pct = round(disk_bytes / total * 100, 1) if total > 0 else 0
        import speed_tracker as st
        speed_str = st.fmt_speed(db_speed) if db_speed > 0 else "0 B/s"
        eta_str   = st.fmt_eta(db_eta)
        dl_items.append({
            "code": code,
            "downloaded_mb": round(disk_bytes / 1024 / 1024, 1),
            "total_mb": round((total or 0) / 1024 / 1024, 1),
            "percent": min(pct, 100),
            "retry": retry,
            "speed": speed_str,
            "eta": eta_str,
        })
    dl_items.sort(key=lambda x: x["downloaded_mb"], reverse=True)

    # Disk usage
    dl_size_gb  = dir_size_gb(DOWNLOAD_DIR)
    mov_size_gb = dir_size_gb(MOVIES_DIR)

    # Recent done
    recent_done = db_query("""
        SELECT code, move_path, updated_at FROM process
        WHERE status='done'
        ORDER BY updated_at DESC LIMIT 8
    """)

    # Exhausted codes
    exhausted = db_query("""
        SELECT code, retry_count FROM process
        WHERE status='exhausted'
        ORDER BY updated_at DESC LIMIT 10
    """)

    return jsonify({
        "ts": int(time.time()),
        "process": {
            "pending":     status_map.get("pending", 0),
            "downloading": status_map.get("downloading", 0),
            "downloaded":  status_map.get("downloaded", 0),
            "done":        status_map.get("done", 0),
            "skip":        status_map.get("skip", 0),
            "exhausted":   status_map.get("exhausted", 0),
        },
        "crawl_total":   crawl_total,
        "torrent_total": torrent_total,
        "cloud_codes":   cloud_codes,
        "on_disk":       on_disk,
        "disk": {
            "downloads_gb": dl_size_gb,
            "movies_gb":    mov_size_gb,
        },
        "downloading": dl_items,
        "recent_done": [{"code": c, "path": p, "ts": t} for c, p, t in recent_done],
        "exhausted":   [{"code": c, "retry": r} for c, r in exhausted],
    })

# -------------------------------------------------------
# API: /api/logs
# -------------------------------------------------------
@app.route("/api/logs")
def api_logs():
    lines = get_logs()
    limit = int(request.args.get("n", cfg["ui"]["log_lines_display"]))
    return jsonify({"lines": lines[-limit:]})

# -------------------------------------------------------
# API: /api/config (reload config)
# -------------------------------------------------------
@app.route("/api/config")
def api_config():
    global cfg, DB_PATH, DOWNLOAD_DIR, MOVIES_DIR, CONTAINER_NAME, LOG_LINES
    cfg = load_config()
    DB_PATH        = cfg["database"]["path"]
    DOWNLOAD_DIR   = cfg["paths"]["download_dir"]
    MOVIES_DIR     = cfg["paths"]["movies_dir"]
    CONTAINER_NAME = cfg["docker"]["container_name"]
    LOG_LINES      = cfg["docker"]["log_lines"]
    return jsonify({"ok": True, "config": cfg})



# -------------------------------------------------------
# API: /api/actors/stats
# -------------------------------------------------------
@app.route("/api/actors/stats")
def api_actors_stats():
    rows = db_query("""
        SELECT 
            a.name,
            COUNT(c.code) as total,
            SUM(CASE WHEN p.status='done'      THEN 1 ELSE 0 END) as done,
            SUM(CASE WHEN p.status='pending'   THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN p.status='exhausted' THEN 1 ELSE 0 END) as exhausted,
            SUM(CASE WHEN p.status='skip'      THEN 1 ELSE 0 END) as skip,
            COALESCE(SUM(
                CASE WHEN p.status='done' 
                THEN (SELECT SUM(size_bytes) FROM pikpak_cloud WHERE code=c.code)
                ELSE 0 END
            ),0) as done_bytes
        FROM actors a
        LEFT JOIN crawl c ON c.actor_name = a.name
        LEFT JOIN process p ON p.code = c.code
        GROUP BY a.name
        ORDER BY total DESC
    """)
    return jsonify([{
        "name":      r[0],
        "total":     r[1] or 0,
        "done":      r[2] or 0,
        "pending":   r[3] or 0,
        "exhausted": r[4] or 0,
        "skip":      r[5] or 0,
        "done_gb":   round((r[6] or 0) / 1024**3, 2),
    } for r in rows])

@app.route("/api/actors/films")
def api_actors_films():
    name = request.args.get("name", "")
    if not name:
        return jsonify([])
    rows = db_query("""
        SELECT c.code, COALESCE(p.status,'?') as status,
               COALESCE((SELECT SUM(size_bytes) FROM pikpak_cloud WHERE code=c.code),0) as size_bytes,
               COALESCE(p.move_path,'') as path,
               COALESCE(t.quality,'') as quality,
               COALESCE(t.size,'') as size_str
        FROM crawl c
        LEFT JOIN process p ON p.code=c.code
        LEFT JOIN torrent t ON t.code=c.code
        WHERE c.actor_name=?
        ORDER BY c.code DESC
    """, (name,))
    return jsonify([{
        "code":     r[0],
        "status":   r[1],
        "size_gb":  round(r[2] / 1024**3, 2) if r[2] else 0,
        "path":     r[3],
        "quality":  r[4],
        "size_str": r[5],
    } for r in rows])

# -------------------------------------------------------
# API: /api/actors
# -------------------------------------------------------
@app.route("/api/actors")
def api_actors():
    rows = db_query("SELECT id, name, url FROM actors ORDER BY name")
    return jsonify([{"id": r[0], "name": r[1], "url": r[2]} for r in rows])

@app.route("/api/actors/add", methods=["POST"])
def api_actors_add():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    url  = (data.get("url")  or "").strip()
    if not name or not url:
        return jsonify({"ok": False, "error": "name and url required"}), 400
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("INSERT INTO actors (name, url) VALUES (?, ?)", (name, url))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/actors/delete", methods=["POST"])
def api_actors_delete():
    data = request.get_json()
    actor_id = data.get("id")
    if not actor_id:
        return jsonify({"ok": False, "error": "id required"}), 400
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("DELETE FROM actors WHERE id=?", (actor_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# -------------------------------------------------------
# SERVE HTML
# -------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "dashboard.html")

# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
if __name__ == "__main__":
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    print(f"[DASHBOARD] Starting on {HOST}:{PORT}", flush=True)
    print(f"[DASHBOARD] DB: {DB_PATH}", flush=True)
    print(f"[DASHBOARD] Container: {CONTAINER_NAME}", flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)