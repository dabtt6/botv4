"""
db_writer.py - Singleton DB writer cho toan project.

Moi module chi can:
    from db_writer import db_run, db_runmany, db_get

- db_run / db_runmany : ghi DB qua queue (thread-safe, khong bao gio corrupt)
- db_get              : doc DB truc tiep (WAL cho phep doc song song voi writer)
- start()             : goi 1 lan khi khoi dong app (tu dong goi neu chua start)
"""

import sqlite3
import threading
import queue
import os

DB_NAME = os.environ.get("DB_NAME", "crawler_master_full.db")

# -------------------------------------------------------
# INTERNAL STATE
# -------------------------------------------------------
_queue    = queue.Queue()
_started  = False
_start_lock = threading.Lock()


# -------------------------------------------------------
# WRITER THREAD
# -------------------------------------------------------
def _writer_loop():
    conn = sqlite3.connect(DB_NAME, timeout=60, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")   # 8MB cache
    conn.commit()

    while True:
        item = _queue.get()

        # Sentinel: shutdown
        if item is None:
            _queue.task_done()
            break

        sql, params, many, event, result_box = item
        try:
            if many:
                conn.executemany(sql, params)
            else:
                conn.execute(sql, params)
            conn.commit()
            result_box.append(True)
        except Exception as e:
            result_box.append(e)
            print(f"[DB_WRITER] ERROR: {e} | sql={sql[:80]}", flush=True)

        _queue.task_done()
        if event:
            event.set()


# -------------------------------------------------------
# PUBLIC API
# -------------------------------------------------------
def start():
    """
    Khoi dong writer thread. Goi 1 lan khi app start.
    An toan khi goi nhieu lan (idempotent).
    """
    global _started
    with _start_lock:
        if _started:
            return
        t = threading.Thread(target=_writer_loop, daemon=True, name="db-writer")
        t.start()
        _started = True


def _ensure_started():
    if not _started:
        start()


def db_run(sql, params=()):
    """
    Ghi 1 lenh SQL. Non-blocking, fire-and-forget.
    """
    _ensure_started()
    _queue.put((sql, params, False, None, []))


def db_run_wait(sql, params=()):
    """
    Ghi 1 lenh SQL va cho den khi hoan thanh.
    Tra ve True neu thanh cong, Exception neu loi.
    """
    _ensure_started()
    event = threading.Event()
    result_box = []
    _queue.put((sql, params, False, event, result_box))
    event.wait()
    r = result_box[0]
    if isinstance(r, Exception):
        raise r
    return True


def db_runmany(sql, params_list):
    """
    Ghi nhieu dong. Non-blocking.
    """
    _ensure_started()
    if not params_list:
        return
    _queue.put((sql, params_list, True, None, []))


def db_runmany_wait(sql, params_list):
    """
    Ghi nhieu dong va cho den khi hoan thanh.
    """
    _ensure_started()
    if not params_list:
        return True
    event = threading.Event()
    result_box = []
    _queue.put((sql, params_list, True, event, result_box))
    event.wait()
    r = result_box[0]
    if isinstance(r, Exception):
        raise r
    return True


def db_get(sql, params=()):
    """
    Doc DB. Mo connection rieng (WAL cho phep doc song song voi writer).
    """
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def db_flush():
    """
    Cho tat ca lenh dang pending trong queue hoan thanh.
    Dung truoc khi shutdown hoac khi can dam bao data da ghi xong.
    """
    _ensure_started()
    _queue.join()


def stop():
    """Shutdown writer thread sach se."""
    _queue.put(None)
    _queue.join()


# -------------------------------------------------------
# USAGE EXAMPLE
# -------------------------------------------------------
if __name__ == "__main__":
    start()

    db_run("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, val TEXT)")
    db_runmany_wait("INSERT OR IGNORE INTO test (id, val) VALUES (?, ?)",
                    [(1, "hello"), (2, "world")])

    rows = db_get("SELECT * FROM test")
    print("Rows:", rows)

    db_flush()
    print("Done.")
