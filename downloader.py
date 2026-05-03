# -*- coding: utf-8 -*-
"""
downloader.py - Thread rieng: download file tu Pikpak cloud ve local.

Nhiem vu:
  - Resume sau khi reboot (check DOWNLOAD_DIR khi khoi dong)
  - Download BATCH_SIZE code song song
  - Poll tien do, detect stall, retry
  - Verify size sau khi download xong
  - Move sang TARGET_DIR
  - Notify Telegram
"""

import os, re, shutil, subprocess, threading, time

import db_writer
db_writer.start()
from db_writer import db_run, db_run_wait, db_get, db_flush
import speed_tracker as st
try:
    from telegram_bot import notify_done, notify_stall
except ImportError:
    def notify_done(code, path=""): pass
    def notify_stall(code): pass

try:
    from telegram import notify_done, notify_failed
except ImportError:
    def notify_done(c): pass
    def notify_failed(c): pass

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
from config import (
    DOWNLOAD_DIR, MOVIES_DIR as TARGET_DIR,
    BATCH_SIZE, MAX_RETRY, MAX_NO_FILE,
    STALL_TICKS, POLL_INTERVAL, DOWNLOAD_LOOP_INTERVAL,
    VIDEO_EXTS
)

# -------------------------------------------------------
# DB HELPERS
# -------------------------------------------------------
def _set_status(code, status):
    db_run_wait("UPDATE process SET status=?, updated_at=? WHERE code=?",
                (status, int(time.time()), code))

def _is_on_disk(code):
    if db_get("SELECT 1 FROM agent_snapshot WHERE code=?", (code,)):
        return True
    if os.path.isdir(os.path.join(TARGET_DIR, code)):
        ts = int(time.time())
        db_run_wait("""
            INSERT INTO agent_snapshot (code, scanned_at) VALUES (?,?)
            ON CONFLICT(code) DO UPDATE SET scanned_at=excluded.scanned_at
        """, (code, ts))
        return True
    return False

def _get_cloud_files(code):
    """Lay file list tu pikpak_cloud DB. Khong scan realtime."""
    rows = db_get(
        "SELECT filename, cloud_path, size_bytes, local_subpath FROM pikpak_cloud WHERE code=?",
        (code,)
    )
    return [(f, p, s, l) for f, p, s, l in rows] if rows else []

# -------------------------------------------------------
# SIZE VERIFY
# -------------------------------------------------------
def _is_download_complete(code):
    """
    True  = tat ca file local >= cloud size
    False = chua xong
    """
    cloud_files = _get_cloud_files(code)
    if not cloud_files:
        return False

    folder = os.path.join(DOWNLOAD_DIR, code)
    if not os.path.exists(folder):
        return False

    local_map = {}
    for r, _, fs in os.walk(folder):
        for f in fs:
            local_map[f] = os.path.getsize(os.path.join(r, f))

    matched = 0
    for fname, _, cloud_size, _ in cloud_files:
        local_size = local_map.get(fname)
        if local_size and local_size >= cloud_size:
            print(f"  [DL] CHECK OK {fname} ({local_size}/{cloud_size}B)", flush=True)
            matched += 1
        else:
            pct = f"{local_size/cloud_size*100:.1f}%" if local_size and cloud_size else "missing"
            print(f"  [DL] CHECK MISMATCH {fname}: {pct}", flush=True)

    return matched > 0 and matched == len(cloud_files)

# -------------------------------------------------------
# MOVE
# -------------------------------------------------------
def _move(code):
    src = os.path.join(DOWNLOAD_DIR, code)
    if not os.path.exists(src):
        return False
    os.makedirs(TARGET_DIR, exist_ok=True)
    dst = os.path.join(TARGET_DIR, code)
    try:
        shutil.move(src, dst)
        ts = int(time.time())
        db_run_wait("""
            UPDATE process SET status='done', moved=1, move_path=?, on_disk=1, updated_at=?
            WHERE code=?
        """, (dst, ts, code))
        db_run_wait("""
            INSERT INTO agent_snapshot (code, scanned_at) VALUES (?,?)
            ON CONFLICT(code) DO UPDATE SET scanned_at=excluded.scanned_at
        """, (code, ts))
        db_flush()
        st.remove(code)
        notify_done(code, dst)
        print(f"  [DL] MOVED: {code} -> {dst}", flush=True)
        return True
    except Exception as e:
        print(f"  [DL] MOVE FAILED {code}: {e}", flush=True)
        return False

# -------------------------------------------------------
# POLL & STALL DETECTION
# -------------------------------------------------------
def _run_and_poll(code, proc, label=""):
    """
    Poll tien do download. Tra ve True neu co loi.
    Terminate process neu stall > STALL_TICKS.
    """
    folder = os.path.join(DOWNLOAD_DIR, code)
    prev_size = -1
    stall = 0
    error_flag = []

    def _drain():
        for line in proc.stdout:
            decoded = line.decode(errors='ignore').rstrip()
            tag = f"[{label}]" if label else ""
            print(f"    [{code}]{tag} {decoded}", flush=True)
            low = decoded.lower()
            if '[error]' in low or 'download failed' in low:
                error_flag.append(True)

    threading.Thread(target=_drain, daemon=True).start()

    while proc.poll() is None:
        time.sleep(POLL_INTERVAL)
        cur_size = (
            sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(folder) for f in fs)
            if os.path.exists(folder) else 0
        )
        if cur_size > 0 and cur_size == prev_size:
            stall += 1
        else:
            stall = 0
        prev_size = cur_size

        # Progress log + speed tracking
        cloud_files = _get_cloud_files(code)
        total = sum(s for _, _, s, _ in cloud_files) if cloud_files else 0
        st.update(code, cur_size)
        speed, eta, _ = st.get_speed_eta(code, total)
        pct  = f"{cur_size/total*100:.1f}%" if total > 0 else "?"
        spd  = st.fmt_speed(speed)
        eta_ = st.fmt_eta(eta)
        tag  = f"[{label}]" if label else ""
        print(f"  [DL]{tag} {code} | {cur_size/1024/1024:.1f}/{total/1024/1024:.1f} MB ({pct}) | {spd} ETA {eta_} | stall={stall}/{STALL_TICKS}", flush=True)

        # Ghi speed/eta vao DB de dashboard doc
        db_run("UPDATE process SET downloaded_bytes=?, speed_bps=?, eta_seconds=?, updated_at=? WHERE code=?",
               (cur_size, int(speed), int(eta), int(time.time()), code))
        if stall >= STALL_TICKS:
            print(f"  [DL] STALL detected, terminating: {code}", flush=True)
            notify_stall(code)
            proc.terminate()
            proc.wait()
            break

    return bool(error_flag)

# -------------------------------------------------------
# DOWNLOAD ONE CODE
# -------------------------------------------------------
def _start_downloads(code):
    """
    Khoi dong cac subprocess download.
    Tra ve list (fname, proc) hoac [] neu da complete, None neu khong co cloud file.
    """
    cloud_files = _get_cloud_files(code)
    if not cloud_files:
        return None   # cloud_scanner chua scan xong

    base_dir = os.path.join(DOWNLOAD_DIR, code)
    os.makedirs(base_dir, exist_ok=True)

    local_map = {}
    for r, _, fs in os.walk(base_dir):
        for f in fs:
            local_map[f] = os.path.getsize(os.path.join(r, f))

    procs = []
    for fname, cloud_path, size, local_subpath in cloud_files:
        local_size = local_map.get(fname)
        if local_size and local_size >= size:
            print(f"  [DL] Already complete: {fname}", flush=True)
            continue
        if local_size:
            print(f"  [DL] Resume {fname}: {local_size/size*100:.1f}%", flush=True)
        else:
            print(f"  [DL] Start: {cloud_path}", flush=True)

        p = subprocess.Popen(
            ["pikpaktui", "download", "-t", base_dir, cloud_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        procs.append((local_subpath or fname, p))

    return procs

def _do_one(code):
    """
    Download 1 code, KHONG retry inline.
    Neu loi/stall/mat ket noi -> set pending ngay, worker lay task moi.
    Retry duoc xu ly boi _download_loop qua retry_count.
    """
    if _is_on_disk(code):
        print(f"  [DL] Already on disk: {code}", flush=True)
        db_run_wait("""
            UPDATE process SET status='done', moved=1, on_disk=1, updated_at=? WHERE code=?
        """, (int(time.time()), code))
        notify_done(code)
        return

    # Kiem tra retry count
    row = db_get("SELECT retry_count FROM process WHERE code=?", (code,))
    retry_count = row[0][0] if row else 0
    if retry_count >= MAX_RETRY:
        print(f"  [DL] EXHAUSTED {code} (retry={retry_count})", flush=True)
        db_run_wait("UPDATE process SET status='exhausted', updated_at=? WHERE code=?",
                    (int(time.time()), code))
        notify_failed(code)
        return

    _set_status(code, 'downloading')

    # --- Lay cloud files ---
    procs = _start_downloads(code)
    if procs is None:
        # Cloud file chua co trong pikpak_cloud DB
        nf = retry_count + 1
        if nf >= MAX_NO_FILE:
            print(f"  [DL] No cloud files after {nf} tries, exhausted: {code}", flush=True)
            db_run_wait("UPDATE process SET status='exhausted', retry_count=?, updated_at=? WHERE code=?",
                        (nf, int(time.time()), code))
            notify_failed(code)
        else:
            print(f"  [DL] No cloud files yet ({nf}/{MAX_NO_FILE}), requeue: {code}", flush=True)
            db_run_wait("UPDATE process SET status='pending', retry_count=?, updated_at=? WHERE code=?",
                        (nf, int(time.time()), code))
        return

    if not procs:
        # Tat ca file da du size -> verify va move ngay
        if _is_download_complete(code):
            _set_status(code, 'downloaded')
            if _move(code):
                print(f"  [DL] DONE (already complete): {code}", flush=True)
                notify_done(code)
            else:
                _set_status(code, 'pending')
        else:
            _set_status(code, 'pending')
        return

    # --- Poll song song, KHONG block lau ---
    had_error = False
    lock = threading.Lock()
    threads = []
    for fname, p in procs:
        def _wait(p=p, f=fname):
            nonlocal had_error
            if _run_and_poll(code, p, label=f):
                with lock:
                    had_error = True
        t = threading.Thread(target=_wait, daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    if had_error:
        # Loi hoac stall -> tang retry_count, set pending, WORKER LAY TASK MOI NGAY
        new_retry = retry_count + 1
        print(f"  [DL] Error/stall, requeue ({new_retry}/{MAX_RETRY}): {code}", flush=True)
        db_run_wait("UPDATE process SET status='pending', retry_count=?, updated_at=? WHERE code=?",
                    (new_retry, int(time.time()), code))
        return

    # --- Thanh cong: verify & move ---
    if _is_download_complete(code):
        _set_status(code, 'downloaded')
        if _move(code):
            print(f"  [DL] DONE: {code}", flush=True)
            notify_done(code)
        else:
            print(f"  [DL] MOVE FAILED, requeue: {code}", flush=True)
            _set_status(code, 'pending')
    else:
        new_retry = retry_count + 1
        print(f"  [DL] Size mismatch, requeue ({new_retry}/{MAX_RETRY}): {code}", flush=True)
        db_run_wait("UPDATE process SET status='pending', retry_count=?, updated_at=? WHERE code=?",
                    (new_retry, int(time.time()), code))

# -------------------------------------------------------
# RESUME ON STARTUP
# -------------------------------------------------------
def resume():
    """
    Chay 1 lan khi khoi dong.
    Check DOWNLOAD_DIR va process table de tiep tuc download do.
    """
    print("[DOWNLOADER] Resume check...", flush=True)

    # Migration: them cot reset_count neu chua co
    try:
        db_run_wait("ALTER TABLE process ADD COLUMN reset_count INTEGER DEFAULT 0")
        print("[DOWNLOADER] Migration: added reset_count column.", flush=True)
    except Exception:
        pass  # Da ton tai, bo qua

    # Check process table
    rows = db_get("SELECT code FROM process WHERE status IN ('downloading','downloaded')")
    for (code,) in rows:
        done_folder = os.path.join(TARGET_DIR, code)
        dl_folder   = os.path.join(DOWNLOAD_DIR, code)
        status = (db_get("SELECT status FROM process WHERE code=?", (code,)) or [('pending',)])[0][0]

        if os.path.exists(done_folder) or _is_on_disk(code):
            print(f"  [RESUME] Already in movies: {code}", flush=True)
            db_run_wait("""
                UPDATE process SET status='done', moved=1, on_disk=1, updated_at=? WHERE code=?
            """, (int(time.time()), code))
            notify_done(code)
            continue

        if status == 'downloaded' and os.path.exists(dl_folder):
            print(f"  [RESUME] Re-moving: {code}", flush=True)
            if not _move(code):
                _set_status(code, 'pending')
            continue

        if status == 'downloading' and os.path.exists(dl_folder):
            if _is_download_complete(code):
                print(f"  [RESUME] Complete, moving: {code}", flush=True)
                _set_status(code, 'downloaded')
                if not _move(code):
                    _set_status(code, 'pending')
            else:
                print(f"  [RESUME] Incomplete, requeue: {code}", flush=True)
                _set_status(code, 'pending')
            continue

        # Khong co folder -> reset pending
        _set_status(code, 'pending')

    # Check orphan folders trong DOWNLOAD_DIR
    if os.path.exists(DOWNLOAD_DIR):
        known = {r[0] for r in db_get("SELECT code FROM process")}
        for name in os.listdir(DOWNLOAD_DIR):
            if name in known:
                continue
            folder = os.path.join(DOWNLOAD_DIR, name)
            if not os.path.isdir(folder):
                continue
            has_video = any(
                os.path.splitext(f)[1].lower() in VIDEO_EXTS
                and os.path.getsize(os.path.join(r, f)) > 50 * 1024 * 1024
                for r, _, fs in os.walk(folder) for f in fs
            )
            if has_video:
                print(f"  [RESUME] Orphan with video: {name}", flush=True)
                db_run_wait("""
                    INSERT OR IGNORE INTO process (code, on_disk, on_cloud, status, updated_at)
                    VALUES (?,0,1,'pending',?)
                """, (name, int(time.time())))
            else:
                print(f"  [RESUME] Orphan no video, skip: {name}", flush=True)

    db_flush()
    print("[DOWNLOADER] Resume done.", flush=True)

# -------------------------------------------------------
# DOWNLOAD LOOP
# -------------------------------------------------------
def _download_loop():
    """
    Loop chinh: moi vong lay BATCH_SIZE pending codes, download song song.
    Sau khi batch xong, lap lai ngay (khong sleep lau) de pick up code moi.
    """
    import queue as _queue

    while True:
        # Reset exhausted neu khong con pending nao.
        # Gioi han MAX_RESETS lan: qua nguong -> giu nguyen exhausted de control panel xu ly.
        MAX_RESETS = 3
        pending_count = db_get("SELECT COUNT(*) FROM process WHERE status='pending' AND on_disk=0")[0][0]
        if pending_count == 0:
            resettable = db_get(
                "SELECT COUNT(*) FROM process WHERE status='exhausted' AND COALESCE(reset_count,0) < ?",
                (MAX_RESETS,)
            )[0][0]
            stuck = db_get(
                "SELECT COUNT(*) FROM process WHERE status='exhausted' AND COALESCE(reset_count,0) >= ?",
                (MAX_RESETS,)
            )[0][0]
            if resettable > 0:
                print(f"[DOWNLOADER] No pending, resetting {resettable} exhausted -> pending (will try {MAX_RESETS} more times).", flush=True)
                db_run_wait("""
                    UPDATE process
                    SET status='pending',
                        retry_count=0,
                        reset_count=COALESCE(reset_count,0)+1,
                        updated_at=?
                    WHERE status='exhausted' AND COALESCE(reset_count,0) < ?
                """, (int(time.time()), MAX_RESETS))
            if stuck > 0:
                print(f"[DOWNLOADER] {stuck} code(s) permanently exhausted (hit {MAX_RESETS}-reset limit), skipping.", flush=True)
            time.sleep(DOWNLOAD_LOOP_INTERVAL)
            continue

        # Chi lay BATCH_SIZE code moi vong -> pick up code moi nhanh hon
        codes = [r[0] for r in db_get("""
            SELECT code FROM process
            WHERE status='pending' AND on_disk=0
            ORDER BY updated_at ASC
            LIMIT ?
        """, (BATCH_SIZE,))]

        if not codes:
            time.sleep(DOWNLOAD_LOOP_INTERVAL)
            continue

        print(f"\n[DOWNLOADER] Batch {len(codes)} codes (pending={pending_count})", flush=True)

        q = _queue.Queue()
        for c in codes:
            q.put(c)

        def _worker():
            while True:
                try:
                    code = q.get_nowait()
                except _queue.Empty:
                    break
                try:
                    _do_one(code)
                except Exception as e:
                    print(f"  [WORKER] ERROR {code}: {e}", flush=True)
                    try:
                        _set_status(code, 'pending')
                    except Exception:
                        pass
                finally:
                    q.task_done()

        workers = [
            threading.Thread(target=_worker, daemon=True, name=f"dl-worker-{i}")
            for i in range(BATCH_SIZE)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

        print("[DOWNLOADER] Batch done.", flush=True)
        # Khong sleep, lap lai ngay de pick up code moi

# -------------------------------------------------------
# THREAD ENTRY
# -------------------------------------------------------
def run_downloader_thread():
    resume()
    _download_loop()

def start_downloader_thread():
    t = threading.Thread(target=run_downloader_thread, daemon=True, name="downloader")
    t.start()
    return t

if __name__ == "__main__":
    run_downloader_thread()