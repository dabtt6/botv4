# -*- coding: utf-8 -*-
"""
cloud_scanner.py - Thread rieng: scan /My Pack tren Pikpak cloud,
lay size thuc cua tung file video, ghi vao pikpak_cloud + process.

Chay doc lap, khong anh huong download hay crawl.
Moi SCAN_INTERVAL giay: scan toan bo /My Pack mot lan.
Chi scan lai code chua co trong pikpak_cloud hoac chua is_checked_cloud.
"""

import os, re, subprocess, threading, time

import db_writer
db_writer.start()
from db_writer import db_run, db_run_wait, db_runmany, db_get, db_flush

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
from config import SCAN_INTERVAL, MOVIES_DIR as TARGET_DIR, VIDEO_EXTS, MIN_VIDEO_BYTES

# -------------------------------------------------------
# ANSI STRIP
# -------------------------------------------------------
_ESC = re.compile(
    r'\x1b\[[0-9;]*m'
    r'|\x1b\][^\x1b]*\x1b\\'
    r'|\x1b\][^\x07]*\x07'
)
def _strip(s):
    return _ESC.sub('', s).strip()

# -------------------------------------------------------
# PIKPAKTUI HELPERS
# -------------------------------------------------------
_UNITS = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}

def _parse_ls(stdout):
    items = []
    for line in stdout.splitlines():
        clean = _strip(line)
        if not clean:
            continue
        parts = clean.split()
        if len(parts) < 5:
            continue
        if parts[1] == '-':                        # folder
            name = ' '.join(parts[4:])
            if name:
                items.append((name, True, None))
            continue
        if len(parts) < 6:
            continue
        unit = parts[2]
        if unit not in _UNITS:
            continue
        try:
            approx = int(float(parts[1]) * _UNITS[unit])
        except ValueError:
            continue
        name = ' '.join(parts[5:])
        if name:
            items.append((name, False, approx))
    return items

def _ls(path, timeout=30):
    """Tra ve list (name, is_folder, approx_bytes) hoac raise RuntimeError."""
    try:
        r = subprocess.run(
            ["pikpaktui", "ls", "-l", path],
            capture_output=True, text=True, timeout=timeout
        )
        return _parse_ls(r.stdout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ls timeout: {path}")
    except Exception as e:
        raise RuntimeError(f"ls error: {path}: {e}")

def _info_size(cloud_path, retries=2):
    """Lay size chinh xac (bytes) cua 1 file. None neu that bai."""
    for attempt in range(retries):
        try:
            r = subprocess.run(
                ["pikpaktui", "info", cloud_path],
                capture_output=True, text=True, timeout=30
            )
            m = re.search(r'Size:\s+[\d.]+\s+\w+\s+\((\d+)\)', _strip(r.stdout))
            if m:
                return int(m.group(1))
        except subprocess.TimeoutExpired:
            print(f"  [SCANNER] info timeout ({attempt+1}/{retries}): {cloud_path}", flush=True)
        except Exception as e:
            print(f"  [SCANNER] info error: {cloud_path}: {e}", flush=True)
            break
    return None

# -------------------------------------------------------
# RECURSIVE SCAN
# -------------------------------------------------------
def _scan_recursive(cloud_path, local_subpath, depth=0):
    """
    De quy scan mot folder.
    Tra ve list (filename, cloud_path, size_bytes, local_subpath).
    Raise RuntimeError neu cloud unreachable.
    """
    if depth > 10:
        print(f"  [SCANNER] Max depth: {cloud_path}", flush=True)
        return []

    items = _ls(cloud_path)   # raises RuntimeError if unreachable
    result = []
    for name, is_folder, approx in items:
        child_path = f"{cloud_path}/{name}"
        child_sub  = f"{local_subpath}/{name}" if local_subpath else name

        if is_folder:
            result.extend(_scan_recursive(child_path, child_sub, depth + 1))
            continue

        ext = os.path.splitext(name)[1].lower()
        if ext not in VIDEO_EXTS:
            continue
        if approx is not None and approx == 0:
            continue

        sz = _info_size(child_path)
        if sz is None:
            print(f"  [SCANNER] Cannot get size: {child_path}", flush=True)
            continue
        if sz >= MIN_VIDEO_BYTES:
            print(f"  [SCANNER] OK {sz:,}B: {child_path}", flush=True)
            result.append((name, child_path, sz, child_sub))
        else:
            print(f"  [SCANNER] SKIP {sz:,}B < 500MB: {child_path}", flush=True)
    return result

def scan_one_code(code):
    """
    Scan /My Pack/{code}.
    Tra ve:
        list  -> co file hop le
        []    -> khong co file hop le
        None  -> cloud unreachable
    """
    root = f"/My Pack/{code}"
    try:
        root_items = _ls(root)
    except RuntimeError as e:
        print(f"  [SCANNER] {e}", flush=True)
        return None

    result = []
    try:
        for name, is_folder, approx in root_items:
            child_path = f"{root}/{name}"
            child_sub  = name
            if is_folder:
                result.extend(_scan_recursive(child_path, child_sub, depth=1))
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in VIDEO_EXTS:
                continue
            if approx is not None and approx == 0:
                continue
            sz = _info_size(child_path)
            if sz is None:
                continue
            if sz >= MIN_VIDEO_BYTES:
                result.append((name, child_path, sz, child_sub))
    except RuntimeError as e:
        print(f"  [SCANNER] {e}", flush=True)
        return None

    return result

# -------------------------------------------------------
# DB HELPERS
# -------------------------------------------------------
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

def _save_cloud_files(code, files):
    ts = int(time.time())
    db_run_wait("DELETE FROM pikpak_cloud WHERE code=?", (code,))
    for fname, cloud_path, size, local_sub in files:
        db_run_wait("""
            INSERT OR REPLACE INTO pikpak_cloud
                (code, filename, cloud_path, local_subpath, size_bytes, scanned_at)
            VALUES (?,?,?,?,?,?)
        """, (code, fname, cloud_path, local_sub, size, ts))

def _upsert_process(code, on_disk, on_cloud, status):
    ts = int(time.time())
    db_run_wait("""
        INSERT INTO process (code, on_disk, on_cloud, status, updated_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(code) DO UPDATE SET
            on_disk    = excluded.on_disk,
            on_cloud   = excluded.on_cloud,
            status     = CASE
                WHEN status IN ('downloading','downloaded','done') THEN status
                ELSE excluded.status
            END,
            updated_at = excluded.updated_at
    """, (code, on_disk, on_cloud, status, ts))

# -------------------------------------------------------
# MAIN SCAN CYCLE
# -------------------------------------------------------
def _scan_cycle():
    """
    1. Lay toan bo code chua is_checked_cloud tu crawl
    2. Quet /My Pack tren cloud
    3. Voi moi code tren cloud: neu chua scan -> scan + ghi pikpak_cloud
    4. Voi code trong crawl chua co tren cloud: check disk -> ghi process
    """
    print(f"\n[SCANNER] Cycle start {time.ctime()}", flush=True)

    # --- Lay danh sach /My Pack ---
    try:
        top_items = _ls("/My Pack")
    except RuntimeError as e:
        print(f"[SCANNER] /My Pack unreachable: {e}", flush=True)
        return

    cloud_codes = {name.upper() for name, _, _ in top_items}
    print(f"[SCANNER] {len(cloud_codes)} codes on cloud.", flush=True)

    # --- Scan tung code tren cloud chua co trong pikpak_cloud ---
    for name, is_folder, _ in top_items:
        code = name.upper()

        # Da co trong pikpak_cloud roi -> skip (da scan truoc do)
        if db_get("SELECT 1 FROM pikpak_cloud WHERE code=?", (code,)):
            # Dam bao is_checked_cloud duoc mark neu code co trong crawl
            db_run("UPDATE crawl SET is_checked_cloud=1 WHERE code=? AND is_checked_cloud=0", (code,))
            continue

        # Da check roi (co trong crawl va da mark) -> skip
        if db_get("SELECT 1 FROM crawl WHERE code=? AND is_checked_cloud=1", (code,)):
            continue

        # Code nay khong co trong crawl va chua scan -> van scan de ghi pikpak_cloud
        # nhung khong can mark is_checked_cloud (khong co trong crawl)
        in_crawl = bool(db_get("SELECT 1 FROM crawl WHERE code=?", (code,)))

        if _is_on_disk(code):
            print(f"  [SCANNER] On disk: {code}", flush=True)
            _upsert_process(code, 1, 1, 'skip')
            if in_crawl:
                db_run("UPDATE crawl SET is_checked_cloud=1 WHERE code=?", (code,))
            continue

        print(f"  [SCANNER] Scanning: {code}", flush=True)
        files = scan_one_code(code)
        if files is None:
            continue   # cloud unreachable, thu lai sau
        if files:
            _save_cloud_files(code, files)
            _upsert_process(code, 0, 1, 'pending')
        else:
            _upsert_process(code, 0, 1, 'exhausted')
        if in_crawl:
            db_run("UPDATE crawl SET is_checked_cloud=1 WHERE code=?", (code,))

    # --- Check code trong crawl chua co tren cloud ---
    unchecked = db_get("SELECT code FROM crawl WHERE is_checked_cloud=0")
    for (code,) in unchecked:
        if code in cloud_codes:
            continue   # Da xu ly o buoc tren
        if _is_on_disk(code):
            _upsert_process(code, 1, 0, 'skip')
            db_run("UPDATE crawl SET is_checked_cloud=1 WHERE code=?", (code,))
        # Neu khong co tren cloud va khong co tren disk:
        # giu is_checked_cloud=0 de classifier xu ly (add cloud)

    db_flush()
    print(f"[SCANNER] Cycle done.", flush=True)

# -------------------------------------------------------
# THREAD ENTRY
# -------------------------------------------------------
def run_scanner_thread():
    """Chay lien tuc, moi SCAN_INTERVAL giay scan lai mot lan."""
    while True:
        try:
            _scan_cycle()
        except Exception as e:
            print(f"[SCANNER] Unexpected error: {e}", flush=True)
        time.sleep(SCAN_INTERVAL)

def start_scanner_thread():
    t = threading.Thread(target=run_scanner_thread, daemon=True, name="cloud-scanner")
    t.start()
    return t

if __name__ == "__main__":
    _scan_cycle()
