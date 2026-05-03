# -*- coding: utf-8 -*-
import os, re, time
import db_writer
db_writer.start()
from db_writer import db_run, db_runmany, db_get

from config import MOVIES_DIR as SCAN_PATH

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

def agent_scan():
    try:
        if not os.path.exists(SCAN_PATH):
            print(f"[AGENT] {SCAN_PATH} not found, skip.", flush=True)
            return

        found_codes = set()
        for root, dirs, files in os.walk(SCAN_PATH):
            for item in dirs + files:
                code = extract_code(item)
                if code:
                    found_codes.add(code)

        if not found_codes:
            print("[AGENT] No codes found.", flush=True)
            return

        ts = int(time.time())

        # Ghi vao agent_snapshot
        db_runmany(
            "INSERT OR IGNORE INTO agent_snapshot (code, scanned_at) VALUES (?, ?)",
            [(c, ts) for c in found_codes]
        )
        db_runmany(
            "UPDATE agent_snapshot SET scanned_at=? WHERE code=?",
            [(ts, c) for c in found_codes]
        )

        # Update process: on_disk=1, status='skip'
        # Chi update neu chua done (tranh ghi de nhung gi da done)
        for code in found_codes:
            db_run("""
                INSERT INTO process (code, on_disk, status, updated_at)
                VALUES (?, 1, 'skip', ?)
                ON CONFLICT(code) DO UPDATE SET
                    on_disk    = 1,
                    status     = 'skip',
                    updated_at = excluded.updated_at
            """, (code, ts))

        db_writer.db_flush()
        print(f"[AGENT] Done. Found {len(found_codes)} codes on disk.", flush=True)

    except Exception as e:
        print(f"[AGENT] ERROR: {e}", flush=True)

if __name__ == "__main__":
    agent_scan()
    os._exit(0)
