# -*- coding: utf-8 -*-
"""
migrate_db.py - Chay 1 lan khi khoi dong, tao/migrate schema moi.
"""
import sqlite3, os

DB_NAME = os.environ.get("DB_NAME", "crawler_master_full.db")

def migrate():
    with sqlite3.connect(DB_NAME, timeout=30) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        # -------------------------------------------------------
        # crawl
        # -------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crawl (
                code           TEXT PRIMARY KEY,
                actor_name     TEXT,
                is_get_torrent INTEGER DEFAULT 0
            )
        """)

        # -------------------------------------------------------
        # torrent
        # -------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS torrent (
                code          TEXT PRIMARY KEY,
                actor_name    TEXT,
                title         TEXT,
                quality       TEXT,
                size          TEXT,
                download_link TEXT,
                created_at    INTEGER
            )
        """)

        # -------------------------------------------------------
        # agent_snapshot
        # -------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_snapshot (
                code       TEXT PRIMARY KEY,
                scanned_at INTEGER
            )
        """)

        # -------------------------------------------------------
        # pikpak_cloud: tung file video cua tung code tren cloud
        # -------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pikpak_cloud (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                code          TEXT NOT NULL,
                filename      TEXT NOT NULL,
                cloud_path    TEXT UNIQUE NOT NULL,
                local_subpath TEXT,
                size_bytes    INTEGER NOT NULL,
                scanned_at    INTEGER
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_code ON pikpak_cloud(code)")
        # Migration: them cot local_subpath neu chua co (DB cu)
        try:
            conn.execute("ALTER TABLE pikpak_cloud ADD COLUMN local_subpath TEXT")
            print("[MIGRATE] Added local_subpath to pikpak_cloud.", flush=True)
        except:
            pass

        # -------------------------------------------------------
        # Migration: them cot is_checked_cloud vao crawl neu chua co
        # -------------------------------------------------------
        try:
            conn.execute("ALTER TABLE crawl ADD COLUMN is_checked_cloud INTEGER DEFAULT 0")
            print("[MIGRATE] Added is_checked_cloud to crawl.", flush=True)
        except:
            pass

        # -------------------------------------------------------
        # process: tracking toan bo flow cho tung code
        # -------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS process (
                code             TEXT PRIMARY KEY,
                on_disk          INTEGER DEFAULT 0,
                on_cloud         INTEGER DEFAULT 0,
                status           TEXT DEFAULT 'pending',
                downloaded_bytes INTEGER DEFAULT 0,
                moved            INTEGER DEFAULT 0,
                move_path        TEXT,
                retry_count      INTEGER DEFAULT 0,
                updated_at       INTEGER
            )
        """)

        # -------------------------------------------------------
        # -------------------------------------------------------
        # Migration: chi fix schema cu neu can, khong migrate data
        # -------------------------------------------------------

        # agent_snapshot cu co the co them cot -> migrate sang schema moi
        try:
            old_cols = [r[1] for r in conn.execute("PRAGMA table_info(agent_snapshot)")]
            if 'source_type' in old_cols or 'real_name' in old_cols:
                print("[MIGRATE] Fixing agent_snapshot schema...", flush=True)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_snapshot_new (
                        code       TEXT PRIMARY KEY,
                        scanned_at INTEGER
                    )
                """)
                conn.execute("""
                    INSERT OR IGNORE INTO agent_snapshot_new (code, scanned_at)
                    SELECT code, scanned_at FROM agent_snapshot
                """)
                conn.execute("DROP TABLE agent_snapshot")
                conn.execute("ALTER TABLE agent_snapshot_new RENAME TO agent_snapshot")
                print("[MIGRATE] agent_snapshot done.", flush=True)
        except Exception as e:
            print(f"[MIGRATE] agent_snapshot skip: {e}", flush=True)

        # Migration: them speed_bps, eta_seconds vao process
        try:
            conn.execute("ALTER TABLE process ADD COLUMN speed_bps INTEGER DEFAULT 0")
            print("[MIGRATE] Added speed_bps to process.", flush=True)
        except: pass
        try:
            conn.execute("ALTER TABLE process ADD COLUMN eta_seconds INTEGER DEFAULT -1")
            print("[MIGRATE] Added eta_seconds to process.", flush=True)
        except: pass

        conn.commit()
        print("[MIGRATE] Schema ready.", flush=True)

if __name__ == "__main__":
    migrate()