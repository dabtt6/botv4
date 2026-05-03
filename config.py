# -*- coding: utf-8 -*-
"""
config.py - Doc cau hinh tu bot.env.
Tat ca module import tu day thay vi hardcode.
"""
import os

ENV_FILE = os.path.join(os.path.dirname(__file__), "bot.env")

def _load():
    cfg = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.split("#")[0].strip()
    except FileNotFoundError:
        print(f"[CONFIG] {ENV_FILE} not found, dung gia tri mac dinh.", flush=True)
    return cfg

_c = _load()

def _str(key, default): return _c.get(key, default)
def _int(key, default): 
    try: return int(_c[key])
    except: return default
def _set(key, default):
    raw = _c.get(key, "")
    return set(raw.split(",")) if raw else default

# --- PATHS ---
DOWNLOAD_DIR = _str("DOWNLOAD_DIR", "/data/downloads")
MOVIES_DIR   = _str("MOVIES_DIR",   "/data/movies")

# --- DOWNLOADER ---
BATCH_SIZE             = _int("BATCH_SIZE",             3)
MAX_RETRY              = _int("MAX_RETRY",              3)
MAX_NO_FILE            = _int("MAX_NO_FILE",            5)
STALL_TICKS            = _int("STALL_TICKS",            18)
POLL_INTERVAL          = _int("POLL_INTERVAL",          10)
DOWNLOAD_LOOP_INTERVAL = _int("DOWNLOAD_LOOP_INTERVAL", 60)

# --- CLOUD SCANNER ---
SCAN_INTERVAL   = _int("SCAN_INTERVAL",   1800)
MIN_VIDEO_BYTES = _int("MIN_VIDEO_MB",    500) * 1024 * 1024

# --- CLASSIFIER ---
CLASSIFY_INTERVAL = _int("CLASSIFY_INTERVAL", 300)

# --- CRAWL ---
CRAWL_INTERVAL       = _int("CRAWL_INTERVAL",       86400)
CRAWL_MAX_THREADS    = _int("CRAWL_MAX_THREADS",    5)
CRAWL_STOP_THRESHOLD = _int("CRAWL_STOP_THRESHOLD", 10)

# --- TORRENT ---
TORRENT_MAX_THREADS = _int("TORRENT_MAX_THREADS", 10)

# --- VIDEO ---
VIDEO_EXTS = _set("VIDEO_EXTS", {'.mp4','.avi','.mkv','.wmv','.m4v','.ts','.mov'})
