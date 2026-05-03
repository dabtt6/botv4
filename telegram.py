import os, requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send(msg: str):
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(f"{API}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM] Failed: {e}", flush=True)

def notify_done(code: str):
    send(f"? Download xong: <b>{code}</b>")

def notify_failed(code: str, reason: str = ""):
    msg = f"? Download that bai: <b>{code}</b>"
    if reason:
        msg += f"\n{reason}"
    send(msg)

def notify_added(code: str):
    send(f"?? Da add cloud: <b>{code}</b>")

def notify_cycle_done(total: int):
    send(f"?? Cycle hoan tat - Da xu ly: <b>{total}</b> code")