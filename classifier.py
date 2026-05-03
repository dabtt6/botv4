# -*- coding: utf-8 -*-
"""
classifier.py - Thread rieng: doc bang crawl, classify tung code,
add torrent len cloud neu can.

Flow moi code:
  1. On disk?         -> process.status = skip, mark done
  2. On cloud (DB)?   -> process.status = pending, mark done
  3. Co torrent link? -> add cloud -> process.status = pending, mark done
  4. Khong co gi?     -> giu is_checked_cloud=0, lan sau thu lai
     (cloud_scanner se scan va mark neu code xuat hien tren cloud)
"""

import subprocess, threading, time

import db_writer
db_writer.start()
from db_writer import db_run, db_run_wait, db_get, db_flush

try:
    from telegram import notify_added
except ImportError:
    def notify_added(c): pass

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
from config import CLASSIFY_INTERVAL

# -------------------------------------------------------
# DB HELPERS
# -------------------------------------------------------
def _is_on_disk(code):
    return bool(db_get("SELECT 1 FROM agent_snapshot WHERE code=?", (code,)))

def _is_on_cloud_db(code):
    """Chi check DB (pikpak_cloud), KHONG scan realtime."""
    return bool(db_get("SELECT 1 FROM pikpak_cloud WHERE code=?", (code,)))

def _upsert_process(code, on_disk, on_cloud, status):
    ts = int(time.time())
    db_run_wait("""
        INSERT INTO process (code, on_disk, on_cloud, status, updated_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(code) DO UPDATE SET
            on_disk    = excluded.on_disk,
            on_cloud   = excluded.on_cloud,
            status     = excluded.status,
            updated_at = excluded.updated_at
    """, (code, on_disk, on_cloud, status, ts))

def _mark_checked(code):
    db_run("UPDATE crawl SET is_checked_cloud=1 WHERE code=?", (code,))

# -------------------------------------------------------
# ADD TO CLOUD
# -------------------------------------------------------
def _add_to_cloud(code, dl_link):
    """
    Tao folder /My Pack/{code} va add offline torrent/magnet.
    Tra ve True neu thanh cong.
    """
    try:
        subprocess.run(
            ["pikpaktui", "mkdir", "/My Pack", code],
            check=True, capture_output=True, timeout=30
        )
        subprocess.run(
            ["pikpaktui", "offline", dl_link, "--to", f"/My Pack/{code}"],
            check=True, capture_output=True, timeout=30
        )
        return True
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b'').decode(errors='ignore').strip()
        print(f"  [CLASSIFIER] ADD FAILED {code}: {err}", flush=True)
        return False
    except subprocess.TimeoutExpired:
        print(f"  [CLASSIFIER] ADD TIMEOUT {code}", flush=True)
        return False

# -------------------------------------------------------
# CLASSIFY CYCLE
# -------------------------------------------------------
def _classify_cycle():
    # Chi lay code chua check va chua co trong process voi trang thai final
    rows = db_get("SELECT code FROM crawl WHERE is_checked_cloud=0")
    if not rows:
        return

    print(f"\n[CLASSIFIER] {len(rows)} codes to classify...", flush=True)
    to_add = []

    for (code,) in rows:
        # 1. On disk
        if _is_on_disk(code):
            print(f"  [CLASSIFIER] SKIP (disk): {code}", flush=True)
            _upsert_process(code, 1, 0, 'skip')
            _mark_checked(code)
            continue

        # 2. Da co tren cloud (da duoc scanner ghi vao pikpak_cloud)
        if _is_on_cloud_db(code):
            print(f"  [CLASSIFIER] PENDING (cloud): {code}", flush=True)
            _upsert_process(code, 0, 1, 'pending')
            _mark_checked(code)
            continue

        # 3. Can torrent de add cloud
        torrent = db_get("SELECT download_link FROM torrent WHERE code=?", (code,))
        if not torrent or not torrent[0][0]:
            # Chua co torrent, giu is_checked_cloud=0 de lan sau thu lai
            print(f"  [CLASSIFIER] WAIT (no torrent): {code}", flush=True)
            continue

        to_add.append((code, torrent[0][0]))

    # --- Add cloud ---
    for code, dl_link in to_add:
        print(f"  [CLASSIFIER] Adding to cloud: {code}", flush=True)
        if _add_to_cloud(code, dl_link):
            notify_added(code)
            print(f"  [CLASSIFIER] ADDED: {code}, scanning cloud...", flush=True)
            # Goi scanner ngay de ghi pikpak_cloud truoc khi downloader chay
            # KHONG mark is_checked_cloud=1 o day, de scanner mark sau khi scan xong
            try:
                from cloud_scanner import scan_one_code, _save_cloud_files, _upsert_process as _sc_upsert
                files = scan_one_code(code)
                if files:
                    _save_cloud_files(code, files)
                    _sc_upsert(code, 0, 1, 'pending')
                    _mark_checked(code)
                    print(f"  [CLASSIFIER] Scanned {len(files)} files: {code}", flush=True)
                elif files is not None:
                    # Add thanh cong nhung pikpak chua xu ly xong (files=[])
                    # Giu is_checked_cloud=0, cloud_scanner se thu lai sau
                    print(f"  [CLASSIFIER] Cloud processing, will retry scan: {code}", flush=True)
                else:
                    print(f"  [CLASSIFIER] Cloud unreachable after add: {code}", flush=True)
            except Exception as e:
                print(f"  [CLASSIFIER] Scan after add failed {code}: {e}", flush=True)
        # Neu add that bai: giu is_checked_cloud=0, lan sau thu lai

    db_flush()
    print(f"[CLASSIFIER] Done. Added {sum(1 for c,_ in to_add if _is_on_cloud_db(c))} codes.", flush=True)

# -------------------------------------------------------
# THREAD ENTRY
# -------------------------------------------------------
def run_classifier_thread():
    while True:
        try:
            _classify_cycle()
        except Exception as e:
            print(f"[CLASSIFIER] Unexpected error: {e}", flush=True)
        time.sleep(CLASSIFY_INTERVAL)

def start_classifier_thread():
    t = threading.Thread(target=run_classifier_thread, daemon=True, name="classifier")
    t.start()
    return t

if __name__ == "__main__":
    _classify_cycle()
