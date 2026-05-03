# -*- coding: utf-8 -*-
"""
speed_tracker.py - Track download speed + ETA cho tung code.
Thread-safe, luu trong memory (khong can DB).
"""
import threading, time
from collections import deque

_lock    = threading.Lock()
_records = {}

SAMPLE_WINDOW = 30
MAX_SAMPLES   = 60

def update(code, current_bytes):
    now = time.time()
    with _lock:
        if code not in _records:
            _records[code] = {
                "samples": deque(maxlen=MAX_SAMPLES),
                "start_ts": now,
                "start_bytes": current_bytes,
            }
        _records[code]["samples"].append((now, current_bytes))

def get_speed_eta(code, total_bytes):
    with _lock:
        rec = _records.get(code)
        if not rec or len(rec["samples"]) < 2:
            return 0, -1, 0
        samples = list(rec["samples"])

    now = time.time()
    cutoff = now - SAMPLE_WINDOW
    window = [(t, b) for t, b in samples if t >= cutoff]
    if len(window) < 2:
        window = samples[-2:]

    dt = window[-1][0] - window[0][0]
    db = window[-1][1] - window[0][1]
    if dt <= 0:
        return 0, -1, window[-1][1]

    speed   = max(db / dt, 0)
    current = window[-1][1]
    remaining = max(total_bytes - current, 0)
    eta = (remaining / speed) if speed > 0 and remaining > 0 else -1
    return speed, eta, current

def remove(code):
    with _lock:
        _records.pop(code, None)

def get_all_codes():
    with _lock:
        return list(_records.keys())

def fmt_speed(bps):
    if bps <= 0:       return "0 B/s"
    if bps < 1024:     return f"{bps:.0f} B/s"
    if bps < 1024**2:  return f"{bps/1024:.1f} KB/s"
    if bps < 1024**3:  return f"{bps/1024**2:.1f} MB/s"
    return f"{bps/1024**3:.2f} GB/s"

def fmt_eta(seconds):
    if seconds < 0:    return "--"
    if seconds < 60:   return f"{int(seconds)}s"
    if seconds < 3600: return f"{int(seconds//60)}m{int(seconds%60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m}m"
