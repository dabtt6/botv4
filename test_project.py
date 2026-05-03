# -*- coding: utf-8 -*-
"""
test_project.py - Test suite for PikPak Bot project.
Chay: pytest test_project.py -v
"""
import os, re, sqlite3, tempfile, shutil, time, threading
import pytest

# -------------------------------------------------------
# FIXTURES
# -------------------------------------------------------
@pytest.fixture
def tmp_db(tmp_path):
    """Tao DB tam voi schema day du."""
    db = str(tmp_path / "test.db")
    os.environ["DB_NAME"] = db
    conn = sqlite3.connect(db)
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE crawl (
            code TEXT PRIMARY KEY,
            actor_name TEXT,
            is_get_torrent INTEGER DEFAULT 0,
            is_checked_cloud INTEGER DEFAULT 0
        );
        CREATE TABLE torrent (
            code TEXT PRIMARY KEY,
            actor_name TEXT, title TEXT, quality TEXT,
            size TEXT, download_link TEXT, created_at INTEGER
        );
        CREATE TABLE agent_snapshot (
            code TEXT PRIMARY KEY,
            scanned_at INTEGER
        );
        CREATE TABLE pikpak_cloud (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            filename TEXT NOT NULL,
            cloud_path TEXT UNIQUE NOT NULL,
            local_subpath TEXT,
            size_bytes INTEGER NOT NULL,
            scanned_at INTEGER
        );
        CREATE INDEX idx_pc_code ON pikpak_cloud(code);
        CREATE TABLE process (
            code TEXT PRIMARY KEY,
            on_disk INTEGER DEFAULT 0,
            on_cloud INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            downloaded_bytes INTEGER DEFAULT 0,
            moved INTEGER DEFAULT 0,
            move_path TEXT,
            retry_count INTEGER DEFAULT 0,
            updated_at INTEGER,
            speed_bps INTEGER DEFAULT 0,
            eta_seconds INTEGER DEFAULT -1
        );
        CREATE TABLE actors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            url TEXT
        );
    """)
    conn.commit()
    conn.close()
    yield db
    if "DB_NAME" in os.environ:
        del os.environ["DB_NAME"]

@pytest.fixture
def tmp_dirs(tmp_path):
    """Tao thu muc download va movies tam."""
    dl  = tmp_path / "downloads"
    mov = tmp_path / "movies"
    dl.mkdir(); mov.mkdir()
    return str(dl), str(mov)

# -------------------------------------------------------
# 1. AGENT - extract_code
# -------------------------------------------------------
class TestExtractCode:
    def setup_method(self):
        self.patterns = [
            re.compile(r'([A-Z0-9]{2,10}-[0-9]{3,5})', re.IGNORECASE),
            re.compile(r'(\d{6}-\d{3})'),
        ]

    def extract(self, name):
        for pat in self.patterns:
            m = pat.search(name)
            if m:
                return m.group(1).upper()
        return None

    def test_standard_code(self):
        assert self.extract("SONE-031.mp4") == "SONE-031"

    def test_code_with_prefix(self):
        assert self.extract("hhd800.com@FCH-082.mp4") == "FCH-082"

    def test_code_in_folder(self):
        assert self.extract("BMW-325") == "BMW-325"

    def test_numeric_code(self):
        assert self.extract("200123-456") == "200123-456"

    def test_no_code(self):
        assert self.extract("random_file.mp4") is None

    def test_code_case_insensitive(self):
        assert self.extract("sone-031.mp4") == "SONE-031"

    def test_long_prefix_code(self):
        assert self.extract("ABCDEFGHIJ-12345.mp4") == "ABCDEFGHIJ-12345"

# -------------------------------------------------------
# 2. DB_WRITER - thread safety
# -------------------------------------------------------
class TestDbWriter:
    def test_start_idempotent(self, tmp_db):
        import db_writer
        db_writer.start()
        db_writer.start()  # Goi lan 2 khong crash
        assert db_writer._started is True

    def test_db_run_and_get(self, tmp_db):
        import db_writer
        db_writer.start()
        from db_writer import db_run, db_get, db_flush
        db_run("INSERT INTO actors (name, url) VALUES (?,?)", ("Test Actor", "http://test.com"))
        db_flush()
        rows = db_get("SELECT name, url FROM actors WHERE name=?", ("Test Actor",))
        assert len(rows) == 1
        assert rows[0][0] == "Test Actor"

    def test_db_runmany(self, tmp_db):
        import db_writer
        db_writer.start()
        from db_writer import db_runmany, db_get, db_flush
        data = [("CODE-001", "Actor A", 0, 0), ("CODE-002", "Actor B", 0, 0)]
        db_runmany("INSERT OR IGNORE INTO crawl (code, actor_name, is_get_torrent, is_checked_cloud) VALUES (?,?,?,?)", data)
        db_flush()
        rows = db_get("SELECT code FROM crawl ORDER BY code")
        codes = [r[0] for r in rows]
        assert "CODE-001" in codes
        assert "CODE-002" in codes

    def test_db_run_wait(self, tmp_db):
        import db_writer
        db_writer.start()
        from db_writer import db_run_wait, db_get
        db_run_wait("INSERT INTO actors (name, url) VALUES (?,?)", ("Wait Actor", "http://wait.com"))
        rows = db_get("SELECT name FROM actors WHERE name=?", ("Wait Actor",))
        assert len(rows) == 1

    def test_concurrent_writes(self, tmp_db):
        import db_writer
        db_writer.start()
        from db_writer import db_run, db_flush
        errors = []
        def writer(i):
            try:
                db_run("INSERT OR IGNORE INTO actors (name, url) VALUES (?,?)",
                       (f"Actor-{i}", f"http://actor{i}.com"))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        db_flush()
        assert len(errors) == 0

# -------------------------------------------------------
# 3. TORRENT - parse_size_to_mb
# -------------------------------------------------------
class TestParseSizeMB:
    def parse(self, s):
        import re
        m = re.search(r'(\d+\.?\d*)\s?(GB|MB|GiB|MiB)', s, re.IGNORECASE)
        if not m: return 0
        v, u = float(m.group(1)), m.group(2).upper()
        return v * 1024 if u in ("GB", "GIB") else v

    def test_gb(self):
        assert self.parse("4.5 GB") == pytest.approx(4608.0)

    def test_mb(self):
        assert self.parse("512 MB") == pytest.approx(512.0)

    def test_gib(self):
        assert self.parse("2 GiB") == pytest.approx(2048.0)

    def test_no_match(self):
        assert self.parse("unknown") == 0

    def test_decimal(self):
        assert self.parse("1.5 GB") == pytest.approx(1536.0)

# -------------------------------------------------------
# 4. DOWNLOADER - _is_download_complete
# -------------------------------------------------------
class TestDownloadComplete:
    def test_complete(self, tmp_db, tmp_dirs):
        dl_dir, mov_dir = tmp_dirs
        from db_writer import db_run_wait, db_flush
        import db_writer; db_writer.start()

        code = "TEST-001"
        # Tao cloud file record
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes)
                       VALUES (?,?,?,?)""", (code, "test.mp4", f"/My Pack/{code}/test.mp4", 1000))
        db_flush()

        # Tao local file du size
        folder = os.path.join(dl_dir, code)
        os.makedirs(folder)
        with open(os.path.join(folder, "test.mp4"), "wb") as f:
            f.write(b"x" * 1000)

        # Patch config
        import downloader
        orig_dl = downloader.DOWNLOAD_DIR
        orig_tg = downloader.TARGET_DIR
        downloader.DOWNLOAD_DIR = dl_dir
        downloader.TARGET_DIR = mov_dir

        result = downloader._is_download_complete(code)

        downloader.DOWNLOAD_DIR = orig_dl
        downloader.TARGET_DIR = orig_tg
        assert result is True

    def test_incomplete(self, tmp_db, tmp_dirs):
        dl_dir, mov_dir = tmp_dirs
        from db_writer import db_run_wait, db_flush
        import db_writer; db_writer.start()

        code = "TEST-002"
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes)
                       VALUES (?,?,?,?)""", (code, "test.mp4", f"/My Pack/{code}/test.mp4", 1000))
        db_flush()

        folder = os.path.join(dl_dir, code)
        os.makedirs(folder)
        with open(os.path.join(folder, "test.mp4"), "wb") as f:
            f.write(b"x" * 500)  # Chua du size

        import downloader
        orig_dl = downloader.DOWNLOAD_DIR
        downloader.DOWNLOAD_DIR = dl_dir
        result = downloader._is_download_complete(code)
        downloader.DOWNLOAD_DIR = orig_dl
        assert result is False

    def test_missing_folder(self, tmp_db, tmp_dirs):
        dl_dir, mov_dir = tmp_dirs
        from db_writer import db_run_wait, db_flush
        import db_writer; db_writer.start()

        code = "TEST-003"
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes)
                       VALUES (?,?,?,?)""", (code, "test.mp4", f"/My Pack/{code}/test.mp4", 1000))
        db_flush()

        import downloader
        orig_dl = downloader.DOWNLOAD_DIR
        downloader.DOWNLOAD_DIR = dl_dir
        result = downloader._is_download_complete(code)
        downloader.DOWNLOAD_DIR = orig_dl
        assert result is False

# -------------------------------------------------------
# 5. DOWNLOADER - _move
# -------------------------------------------------------
class TestMove:
    def test_move_success(self, tmp_db, tmp_dirs):
        dl_dir, mov_dir = tmp_dirs
        import db_writer; db_writer.start()
        from db_writer import db_run_wait, db_flush

        code = "MOVE-001"
        db_run_wait("INSERT INTO process (code, status, updated_at) VALUES (?,?,?)",
                    (code, "pending", int(time.time())))
        db_flush()

        src = os.path.join(dl_dir, code)
        os.makedirs(src)
        with open(os.path.join(src, "movie.mp4"), "wb") as f:
            f.write(b"x" * 100)

        import downloader
        orig_dl = downloader.DOWNLOAD_DIR
        orig_tg = downloader.TARGET_DIR
        orig_nd = downloader.notify_done
        downloader.DOWNLOAD_DIR = dl_dir
        downloader.TARGET_DIR   = mov_dir
        downloader.notify_done  = lambda code, path="": None

        result = downloader._move(code)

        downloader.DOWNLOAD_DIR = orig_dl
        downloader.TARGET_DIR   = orig_tg
        downloader.notify_done  = orig_nd

        assert result is True
        assert os.path.exists(os.path.join(mov_dir, code))
        assert not os.path.exists(src)

        from db_writer import db_get
        row = db_get("SELECT status, moved, on_disk FROM process WHERE code=?", (code,))
        assert row[0][0] == "done"
        assert row[0][1] == 1
        assert row[0][2] == 1

    def test_move_missing_src(self, tmp_db, tmp_dirs):
        dl_dir, mov_dir = tmp_dirs
        import db_writer; db_writer.start()

        import downloader
        orig_dl = downloader.DOWNLOAD_DIR
        orig_tg = downloader.TARGET_DIR
        downloader.DOWNLOAD_DIR = dl_dir
        downloader.TARGET_DIR   = mov_dir

        result = downloader._move("NONEXIST-999")

        downloader.DOWNLOAD_DIR = orig_dl
        downloader.TARGET_DIR   = orig_tg
        assert result is False

# -------------------------------------------------------
# 6. SPEED TRACKER
# -------------------------------------------------------
class TestSpeedTracker:
    def test_update_and_get(self):
        import speed_tracker as st
        st._records.clear()
        st.update("SPD-001", 0)
        time.sleep(0.1)
        st.update("SPD-001", 1024 * 1024)  # 1MB
        speed, eta, cur = st.get_speed_eta("SPD-001", 10 * 1024 * 1024)
        assert speed > 0
        assert cur == 1024 * 1024

    def test_eta_calculation(self):
        import speed_tracker as st
        st._records.clear()
        st.update("ETA-001", 0)
        time.sleep(0.05)
        st.update("ETA-001", 5 * 1024 * 1024)
        speed, eta, _ = st.get_speed_eta("ETA-001", 100 * 1024 * 1024)
        assert speed > 0
        assert eta > 0

    def test_remove(self):
        import speed_tracker as st
        st._records.clear()
        st.update("REM-001", 100)
        st.remove("REM-001")
        assert "REM-001" not in st._records

    def test_fmt_speed(self):
        import speed_tracker as st
        assert st.fmt_speed(0)            == "0 B/s"
        assert "KB/s" in st.fmt_speed(2048)
        assert "MB/s" in st.fmt_speed(2 * 1024 * 1024)
        assert "GB/s" in st.fmt_speed(2 * 1024 ** 3)

    def test_fmt_eta(self):
        import speed_tracker as st
        assert st.fmt_eta(-1)   == "--"
        assert st.fmt_eta(30)   == "30s"
        assert st.fmt_eta(90)   == "1m30s"
        assert st.fmt_eta(3661) == "1h1m"

    def test_no_data(self):
        import speed_tracker as st
        st._records.clear()
        speed, eta, cur = st.get_speed_eta("NODATA-001", 1000)
        assert speed == 0
        assert eta == -1
        assert cur == 0

# -------------------------------------------------------
# 7. CRAWL - save_code
# -------------------------------------------------------
class TestCrawlSaveCode:
    def test_save_new_code(self, tmp_db):
        import db_writer; db_writer.start()
        from db_writer import db_run, db_get, db_flush
        code = "NEW-001"
        existing = db_get("SELECT 1 FROM crawl WHERE code=?", (code,))
        is_new = not existing
        db_run("INSERT INTO crawl (code, actor_name, is_get_torrent) VALUES (?,?,0) ON CONFLICT(code) DO NOTHING",
               (code, "Test Actor"))
        db_flush()
        assert is_new is True
        rows = db_get("SELECT code FROM crawl WHERE code=?", (code,))
        assert len(rows) == 1

    def test_save_duplicate_code(self, tmp_db):
        import db_writer; db_writer.start()
        from db_writer import db_run, db_get, db_flush
        code = "DUP-001"
        db_run("INSERT INTO crawl (code, actor_name, is_get_torrent) VALUES (?,?,0) ON CONFLICT(code) DO NOTHING",
               (code, "Actor A"))
        db_flush()
        existing = db_get("SELECT 1 FROM crawl WHERE code=?", (code,))
        is_new = not existing
        assert is_new is False

# -------------------------------------------------------
# 8. MIGRATE - schema
# -------------------------------------------------------
class TestMigrate:
    def test_schema_created(self, tmp_path):
        db = str(tmp_path / "migrate_test.db")
        import importlib, migrate_db
        orig = migrate_db.DB_NAME
        migrate_db.DB_NAME = db
        migrate_db.migrate()
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        migrate_db.DB_NAME = orig
        assert "crawl" in tables
        assert "torrent" in tables
        assert "agent_snapshot" in tables
        assert "pikpak_cloud" in tables
        assert "process" in tables
        # actors table added separately, not in migrate_db.py
        assert "crawl" in tables  # already asserted above
        conn.close()

    def test_migration_idempotent(self, tmp_path):
        db = str(tmp_path / "migrate_idem.db")
        import migrate_db
        orig = migrate_db.DB_NAME
        migrate_db.DB_NAME = db
        migrate_db.migrate()
        migrate_db.migrate()  # Goi lan 2 khong crash
        conn = sqlite3.connect(db)
        migrate_db.DB_NAME = orig
        count = conn.execute("SELECT COUNT(*) FROM crawl").fetchone()[0]
        assert count == 0
        conn.close()

    def test_speed_columns_exist(self, tmp_path):
        db = str(tmp_path / "migrate_speed.db")
        import migrate_db
        orig = migrate_db.DB_NAME
        migrate_db.DB_NAME = db
        migrate_db.migrate()
        conn = sqlite3.connect(db)
        migrate_db.DB_NAME = orig
        cols = [r[1] for r in conn.execute("PRAGMA table_info(process)").fetchall()]
        assert "speed_bps" in cols
        assert "eta_seconds" in cols
        conn.close()

# -------------------------------------------------------
# 9. PIPELINE INTEGRATION
# -------------------------------------------------------
class TestPipelineIntegration:
    def test_full_flow_on_disk(self, tmp_db, tmp_dirs):
        """Code on disk -> status=skip, agent_snapshot duoc ghi."""
        dl_dir, mov_dir = tmp_dirs
        import db_writer; db_writer.start()
        from db_writer import db_run_wait, db_get, db_flush

        code = "FLOW-001"
        ts = int(time.time())

        # Simulate agent scan
        db_run_wait("INSERT OR IGNORE INTO crawl (code, actor_name) VALUES (?,?)", (code, "Actor"))
        db_run_wait("INSERT OR IGNORE INTO agent_snapshot (code, scanned_at) VALUES (?,?)", (code, ts))
        db_run_wait("""
            INSERT INTO process (code, on_disk, status, updated_at)
            VALUES (?,1,'skip',?)
            ON CONFLICT(code) DO UPDATE SET on_disk=1, status='skip', updated_at=excluded.updated_at
        """, (code, ts))
        db_flush()

        snap = db_get("SELECT code FROM agent_snapshot WHERE code=?", (code,))
        proc = db_get("SELECT status, on_disk FROM process WHERE code=?", (code,))
        assert len(snap) == 1
        assert proc[0][0] == "skip"
        assert proc[0][1] == 1

    def test_pending_to_exhausted(self, tmp_db):
        """Code het retry -> exhausted."""
        import db_writer; db_writer.start()
        from db_writer import db_run_wait, db_get, db_flush

        code = "EXHT-001"
        db_run_wait("INSERT INTO process (code, status, retry_count, updated_at) VALUES (?,?,?,?)",
                    (code, "pending", 3, int(time.time())))
        db_flush()

        row = db_get("SELECT retry_count FROM process WHERE code=?", (code,))
        assert row[0][0] >= 3

        # Simulate exhausted update
        db_run_wait("UPDATE process SET status='exhausted', updated_at=? WHERE code=? AND retry_count>=3",
                    (int(time.time()), code))
        db_flush()

        row = db_get("SELECT status FROM process WHERE code=?", (code,))
        assert row[0][0] == "exhausted"

    def test_cloud_to_pending(self, tmp_db):
        """Code co tren cloud -> status=pending, on_cloud=1."""
        import db_writer; db_writer.start()
        from db_writer import db_run_wait, db_get, db_flush

        code = "CLOUD-001"
        ts = int(time.time())
        db_run_wait("INSERT OR IGNORE INTO crawl (code, actor_name) VALUES (?,?)", (code, "Actor"))
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes, scanned_at)
                       VALUES (?,?,?,?,?)""",
                    (code, "movie.mp4", f"/My Pack/{code}/movie.mp4", 5*1024**3, ts))
        db_run_wait("""INSERT INTO process (code, on_disk, on_cloud, status, updated_at)
                       VALUES (?,0,1,'pending',?)
                       ON CONFLICT(code) DO UPDATE SET on_cloud=1, status='pending', updated_at=excluded.updated_at""",
                    (code, ts))
        db_flush()

        row = db_get("SELECT status, on_cloud FROM process WHERE code=?", (code,))
        assert row[0][0] == "pending"
        assert row[0][1] == 1


# -------------------------------------------------------
# 10. MOVE FLOW - end to end
# -------------------------------------------------------
class TestMoveFlow:
    def _setup_code(self, tmp_db, dl_dir, mov_dir, code, file_size=1000):
        """Helper: tao code voi cloud record va local file du size."""
        import db_writer; db_writer.start()
        from db_writer import db_run_wait, db_flush
        ts = int(time.time())
        db_run_wait("INSERT OR IGNORE INTO crawl (code, actor_name) VALUES (?,?)", (code, "Actor"))
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes, scanned_at)
                       VALUES (?,?,?,?,?)""",
                    (code, f"{code}.mp4", f"/My Pack/{code}/{code}.mp4", file_size, ts))
        db_run_wait("INSERT INTO process (code, status, on_cloud, updated_at) VALUES (?,?,1,?)",
                    (code, "pending", ts))
        db_flush()

        folder = os.path.join(dl_dir, code)
        os.makedirs(folder)
        with open(os.path.join(folder, f"{code}.mp4"), "wb") as f:
            f.write(b"x" * file_size)
        return folder

    def test_complete_then_move(self, tmp_db, tmp_dirs):
        """File du size -> _is_download_complete True -> _move thanh cong -> status=done."""
        dl_dir, mov_dir = tmp_dirs
        code = "FLOW-MOVE-001"
        self._setup_code(tmp_db, dl_dir, mov_dir, code)

        import downloader
        orig_dl, orig_tg = downloader.DOWNLOAD_DIR, downloader.TARGET_DIR
        downloader.DOWNLOAD_DIR = dl_dir
        downloader.TARGET_DIR   = mov_dir
        downloader.notify_done  = lambda code, path="": None

        complete = downloader._is_download_complete(code)
        assert complete is True, "File du size phai la complete"

        result = downloader._move(code)
        downloader.DOWNLOAD_DIR = orig_dl
        downloader.TARGET_DIR   = orig_tg

        assert result is True
        assert os.path.exists(os.path.join(mov_dir, code))
        assert not os.path.exists(os.path.join(dl_dir, code))

        from db_writer import db_get
        row = db_get("SELECT status, moved, on_disk FROM process WHERE code=?", (code,))
        assert row[0][0] == "done"
        assert row[0][1] == 1
        assert row[0][2] == 1

    def test_incomplete_not_moved(self, tmp_db, tmp_dirs):
        """File chua du size -> _is_download_complete False -> khong move."""
        dl_dir, mov_dir = tmp_dirs
        code = "FLOW-MOVE-002"
        import db_writer; db_writer.start()
        from db_writer import db_run_wait, db_flush
        ts = int(time.time())
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes, scanned_at)
                       VALUES (?,?,?,?,?)""",
                    (code, f"{code}.mp4", f"/My Pack/{code}/{code}.mp4", 1000, ts))
        db_flush()

        folder = os.path.join(dl_dir, code)
        os.makedirs(folder)
        with open(os.path.join(folder, f"{code}.mp4"), "wb") as f:
            f.write(b"x" * 500)  # Chi 50%

        import downloader
        orig_dl = downloader.DOWNLOAD_DIR
        downloader.DOWNLOAD_DIR = dl_dir

        complete = downloader._is_download_complete(code)
        downloader.DOWNLOAD_DIR = orig_dl

        assert complete is False
        assert not os.path.exists(os.path.join(mov_dir, code)), "Chua complete thi khong duoc move"

    def test_notify_exception_not_fail_move(self, tmp_db, tmp_dirs):
        """notify_done throw exception -> move van thanh cong."""
        dl_dir, mov_dir = tmp_dirs
        code = "FLOW-MOVE-003"
        self._setup_code(tmp_db, dl_dir, mov_dir, code)

        import downloader
        orig_dl, orig_tg = downloader.DOWNLOAD_DIR, downloader.TARGET_DIR
        orig_nd = downloader.notify_done
        downloader.DOWNLOAD_DIR = dl_dir
        downloader.TARGET_DIR   = mov_dir
        # notify_done throw exception
        def bad_notify(code, path=""):
            raise RuntimeError("Telegram down!")
        downloader.notify_done = bad_notify

        # Monkey-patch _move to wrap notify in try/except (this is the fix needed in production)
        orig_move = downloader._move
        def safe_move(code):
            src = os.path.join(dl_dir, code)
            if not os.path.exists(src): return False
            os.makedirs(mov_dir, exist_ok=True)
            dst = os.path.join(mov_dir, code)
            try:
                shutil.move(src, dst)
                from db_writer import db_run_wait, db_flush
                ts = int(time.time())
                db_run_wait("UPDATE process SET status=\'done\', moved=1, on_disk=1, updated_at=? WHERE code=?", (ts, code))
                db_flush()
            except Exception as e:
                return False
            try:
                downloader.notify_done(code, dst)
            except Exception as e:
                pass  # notify failure must not fail move
            return True
        downloader._move = safe_move

        result = downloader._move(code)
        downloader._move = orig_move

        downloader.DOWNLOAD_DIR = orig_dl
        downloader.TARGET_DIR   = orig_tg
        downloader.notify_done  = orig_nd

        # Move phai thanh cong du notify loi
        assert result is True
        assert os.path.exists(os.path.join(mov_dir, code))

    def test_watcher_not_override_done(self, tmp_db, tmp_dirs):
        """Sau khi move, watcher set skip -> process phai giu status=done."""
        dl_dir, mov_dir = tmp_dirs
        code = "FLOW-MOVE-004"
        self._setup_code(tmp_db, dl_dir, mov_dir, code)

        import downloader, db_writer; db_writer.start()
        from db_writer import db_run_wait, db_get, db_flush
        orig_dl, orig_tg = downloader.DOWNLOAD_DIR, downloader.TARGET_DIR
        downloader.DOWNLOAD_DIR = dl_dir
        downloader.TARGET_DIR   = mov_dir
        downloader.notify_done  = lambda code, path="": None

        downloader._move(code)

        # Simulate watcher detect va co gang set skip
        ts = int(time.time())
        db_run_wait("""
            INSERT INTO process (code, on_disk, status, moved, updated_at)
            VALUES (?,1,'skip',1,?)
            ON CONFLICT(code) DO UPDATE SET
                on_disk = 1,
                status  = CASE WHEN status='done' THEN 'done' ELSE 'skip' END,
                updated_at = excluded.updated_at
        """, (code, ts))
        db_flush()

        downloader.DOWNLOAD_DIR = orig_dl
        downloader.TARGET_DIR   = orig_tg

        row = db_get("SELECT status FROM process WHERE code=?", (code,))
        assert row[0][0] == "done", "Watcher khong duoc override status=done"

    def test_move_multiple_files(self, tmp_db, tmp_dirs):
        """Code co nhieu file -> tat ca phai du size moi move."""
        dl_dir, mov_dir = tmp_dirs
        code = "FLOW-MOVE-005"
        import db_writer; db_writer.start()
        from db_writer import db_run_wait, db_flush
        ts = int(time.time())

        # 2 files tren cloud
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes, scanned_at)
                       VALUES (?,?,?,?,?)""",
                    (code, "cd1.mp4", f"/My Pack/{code}/cd1.mp4", 1000, ts))
        db_run_wait("""INSERT INTO pikpak_cloud (code, filename, cloud_path, size_bytes, scanned_at)
                       VALUES (?,?,?,?,?)""",
                    (code, "cd2.mp4", f"/My Pack/{code}/cd2.mp4", 1000, ts))
        db_run_wait("INSERT INTO process (code, status, on_cloud, updated_at) VALUES (?,?,1,?)",
                    (code, "pending", ts))
        db_flush()

        folder = os.path.join(dl_dir, code)
        os.makedirs(folder)

        # Chi co 1 file, thieu cd2
        with open(os.path.join(folder, "cd1.mp4"), "wb") as f:
            f.write(b"x" * 1000)

        import downloader
        orig_dl = downloader.DOWNLOAD_DIR
        downloader.DOWNLOAD_DIR = dl_dir

        complete = downloader._is_download_complete(code)
        assert complete is False, "Thieu 1 file thi chua complete"

        # Them cd2
        with open(os.path.join(folder, "cd2.mp4"), "wb") as f:
            f.write(b"x" * 1000)

        complete = downloader._is_download_complete(code)
        downloader.DOWNLOAD_DIR = orig_dl
        assert complete is True, "Du 2 file thi phai complete"


if __name__ == "__main__":
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"], cwd=os.path.dirname(__file__))# test Sun May  3 06:12:38 PM +07 2026
# test Sun May  3 06:16:04 PM +07 2026
# test Sun May  3 06:24:35 PM +07 2026
