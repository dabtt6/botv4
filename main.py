# -*- coding: utf-8 -*-
"""
main.py - Orchestrator production.

Architecture:
  db_writer       : singleton DB writer thread (khoi dong truoc tien)
  agent.py        : scan disk lan dau, chay 1 lan khi start
  watcher         : daemon thread, monitor /data/movies realtime
  crawl_thread    : chay crawl.py + torrent.py, 1 lan/ngay
  cloud_scanner   : daemon thread, scan /My Pack -> pikpak_cloud, moi 30 phut
  classifier      : daemon thread, classify crawl -> process, moi 5 phut
  downloader      : daemon thread, download + verify + move, lien tuc

Tat ca thread la daemon -> main thread giu song bang sleep loop.
DB writer la thread duy nhat ghi DB -> khong bao gio conflict.
"""

import subprocess, sys, time, os, threading

from config import CRAWL_INTERVAL

def run_script(script_name, timeout=900):
    if not os.path.exists(script_name):
        print(f"[MAIN] SKIP (not found): {script_name}", flush=True)
        return True
    print(f"\n{'='*45}\n[MAIN] RUN: {script_name}\n{'='*45}", flush=True)
    try:
        subprocess.run(
            [sys.executable, "-u", script_name],
            stdout=sys.stdout, stderr=sys.stderr,
            check=True, timeout=timeout
        )
        print(f"[MAIN] DONE: {script_name}", flush=True)
        return True
    except subprocess.TimeoutExpired:
        print(f"[MAIN] TIMEOUT: {script_name}", flush=True)
        return False
    except subprocess.CalledProcessError as e:
        print(f"[MAIN] ERROR: {script_name} (exit {e.returncode})", flush=True)
        return False

def _crawl_thread():
    last_crawl = 0
    while True:
        now = time.time()
        if now - last_crawl >= CRAWL_INTERVAL:
            print(f"\n[CRAWL THREAD] Start {time.ctime()}", flush=True)
            run_script("crawl.py", timeout=7200)
            time.sleep(5)
            run_script("torrent.py", timeout=7200)
            last_crawl = time.time()
            print(f"[CRAWL THREAD] Done. Next in 24h.", flush=True)
        next_in = int(CRAWL_INTERVAL - (time.time() - last_crawl))
        time.sleep(min(300, max(next_in, 10)))

def main():
    print(f"\n{'='*45}", flush=True)
    print(f"[MAIN] PikPak Bot starting {time.ctime()}", flush=True)
    print(f"{'='*45}\n", flush=True)

    # 1. DB writer
    import db_writer
    db_writer.start()
    print("[MAIN] DB writer started.", flush=True)

    # 2. Migrate
    run_script("migrate_db.py", timeout=60)

    # 3. Agent scan disk lan dau (blocking)
    print("[MAIN] Initial disk scan...", flush=True)
    run_script("agent.py", timeout=300)

    # 4. Watcher
    try:
        from watcher import start_watcher_thread
        start_watcher_thread()
        print("[MAIN] Watcher started.", flush=True)
    except ImportError:
        print("[MAIN] watcher.py not found, skipping.", flush=True)

    # 5. Cloud scanner
    try:
        from cloud_scanner import start_scanner_thread
        start_scanner_thread()
        print("[MAIN] Cloud scanner started.", flush=True)
    except ImportError:
        print("[MAIN] cloud_scanner.py not found, skipping.", flush=True)

    # 6. Classifier
    try:
        from classifier import start_classifier_thread
        start_classifier_thread()
        print("[MAIN] Classifier started.", flush=True)
    except ImportError:
        print("[MAIN] classifier.py not found, skipping.", flush=True)

    # 7. Downloader
    try:
        from downloader import start_downloader_thread
        start_downloader_thread()
        print("[MAIN] Downloader started.", flush=True)
    except ImportError:
        print("[MAIN] downloader.py not found, skipping.", flush=True)

    # 8. Crawl thread
    t_crawl = threading.Thread(target=_crawl_thread, daemon=True, name="crawl-thread")
    t_crawl.start()
    print("[MAIN] Crawl thread started.", flush=True)

    # Telegram bot
    try:
        from telegram_bot import start_bot_thread
        start_bot_thread()
        print("[MAIN] Telegram bot started.", flush=True)
    except ImportError:
        print("[MAIN] telegram_bot.py not found, skipping.", flush=True)

    print(f"\n[MAIN] All systems running. {time.ctime()}\n", flush=True)

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[MAIN] Shutdown requested.", flush=True)
        from db_writer import db_flush
        db_flush()

if __name__ == "__main__":
    main()
