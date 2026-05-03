# -*- coding: utf-8 -*-
"""
watcher.py - Monitor /data/movies realtime.
Khi co folder/file moi xuat hien -> update agent_snapshot + process ngay.
"""
import os, re, time, threading, logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import db_writer
db_writer.start()
from db_writer import db_run, db_runmany, db_get

from config import MOVIES_DIR as WATCH_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WATCHER] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('watcher')

CODE_PATTERNS = [
    re.compile(r'([A-Z0-9]{2,10}-[0-9]{3,5})', re.IGNORECASE),
    re.compile(r'(\d{6}-\d{3})'),
]

def extract_code(name):
    for pat in CODE_PATTERNS:
        m = pat.search(name)
        if m:
            return m.group(1).upper()
    return None

def save_code(code, path):
    ts = int(time.time())
    # agent_snapshot
    db_run("""
        INSERT INTO agent_snapshot (code, scanned_at)
        VALUES (?, ?)
        ON CONFLICT(code) DO UPDATE SET scanned_at=excluded.scanned_at
    """, (code, ts))
    # process: on_disk=1, status='skip', moved=1
    db_run("""
        INSERT INTO process (code, on_disk, status, moved, move_path, updated_at)
        VALUES (?, 1, 'skip', 1, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            on_disk    = 1,
            status     = 'skip',
            moved      = 1,
            move_path  = excluded.move_path,
            updated_at = excluded.updated_at
    """, (code, path, ts))
    log.info(f"Saved: {code} @ {path}")

class MovieHandler(FileSystemEventHandler):
    def on_created(self, event):
        name = os.path.basename(event.src_path)
        code = extract_code(name)
        if code:
            log.info(f"Detected: {name} -> {code}")
            save_code(code, event.src_path)

    def on_moved(self, event):
        name = os.path.basename(event.dest_path)
        code = extract_code(name)
        if code:
            log.info(f"Moved in: {name} -> {code}")
            save_code(code, event.dest_path)

def initial_scan():
    if not os.path.exists(WATCH_PATH):
        return
    ts = int(time.time())
    found = []
    for item in os.listdir(WATCH_PATH):
        code = extract_code(item)
        if code:
            path = os.path.join(WATCH_PATH, item)
            found.append((code, path, ts))

    if not found:
        return

    db_runmany("""
        INSERT INTO agent_snapshot (code, scanned_at)
        VALUES (?, ?)
        ON CONFLICT(code) DO UPDATE SET scanned_at=excluded.scanned_at
    """, [(c, ts) for c, _, ts in found])

    for code, path, ts in found:
        db_run("""
            INSERT INTO process (code, on_disk, status, moved, move_path, updated_at)
            VALUES (?, 1, 'skip', 1, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                on_disk=1, status='skip', moved=1,
                move_path=excluded.move_path,
                updated_at=excluded.updated_at
        """, (code, path, ts))

    db_writer.db_flush()
    log.info(f"Initial scan: {len(found)} codes in {WATCH_PATH}")

def start_watcher():
    os.makedirs(WATCH_PATH, exist_ok=True)
    initial_scan()

    observer = Observer()
    observer.schedule(MovieHandler(), WATCH_PATH, recursive=True)
    observer.start()
    log.info(f"Watching: {WATCH_PATH}")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

def start_watcher_thread():
    t = threading.Thread(target=start_watcher, daemon=True, name='watcher')
    t.start()
    return t

if __name__ == "__main__":
    start_watcher()
