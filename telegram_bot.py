# -*- coding: utf-8 -*-
import os, re, threading, time, sqlite3, shutil
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import db_writer
db_writer.start()
from db_writer import db_run, db_run_wait, db_get, db_flush
import speed_tracker as st

def _load_env():
    cfg = {}
    env_file = os.path.join(os.path.dirname(__file__), "bot.env")
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.split("#")[0].strip()
    except: pass
    return cfg

_cfg = _load_env()
TOKEN        = _cfg.get("TELEGRAM_TOKEN", "")
CHAT_ID      = _cfg.get("TELEGRAM_CHAT_ID", "")
DOWNLOAD_DIR = _cfg.get("DOWNLOAD_DIR", "/data/downloads")
MOVIES_DIR   = _cfg.get("MOVIES_DIR",   "/data/movies")
DISK_PATH    = _cfg.get("DISK_PATH",    "/data")
DB_PATH      = os.environ.get("DB_NAME", _cfg.get("DB_NAME", "crawler_master_full.db"))

def notify(msg):
    pass
def notify_done(code, path=""):
    pass
def notify_stall(code):
    pass
def notify_added(code):
    pass
def start_bot_thread():
    return None

if not TOKEN or not CHAT_ID:
    print("[TELEGRAM] No TOKEN/CHAT_ID in bot.env, bot disabled.", flush=True)
else:
    bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

    def _db(sql, params=()):
        return db_get(sql, params)

    def _dir_gb(path):
        total = 0
        try:
            for r, _, fs in os.walk(path):
                for f in fs:
                    try: total += os.path.getsize(os.path.join(r, f))
                    except: pass
        except: pass
        return round(total / 1024**3, 2)

    def _disk_free_gb():
        try:
            u = shutil.disk_usage(DISK_PATH)
            return round(u.free / 1024**3, 1)
        except: return -1

    def _fmt_status():
        rows = _db("SELECT status, COUNT(*) FROM process GROUP BY status")
        s = {r[0]: r[1] for r in rows}
        crawl   = (_db("SELECT COUNT(*) FROM crawl") or [[0]])[0][0]
        torrent = (_db("SELECT COUNT(*) FROM torrent") or [[0]])[0][0]
        cloud   = (_db("SELECT COUNT(DISTINCT code) FROM pikpak_cloud") or [[0]])[0][0]
        on_disk = (_db("SELECT COUNT(*) FROM agent_snapshot") or [[0]])[0][0]
        free_gb = _disk_free_gb()
        dl_gb   = _dir_gb(DOWNLOAD_DIR)
        mov_gb  = _dir_gb(MOVIES_DIR)
        return (
            "*PikPak Bot Status*\n"
            "-----------------\n"
            f"Crawled:   `{crawl}`\n"
            f"Torrent:   `{torrent}`\n"
            f"Cloud:     `{cloud}`\n"
            f"On disk:   `{on_disk}`\n"
            "-----------------\n"
            f"Done:      `{s.get('done',0)}`\n"
            f"Pending:   `{s.get('pending',0)}`\n"
            f"Exhausted: `{s.get('exhausted',0)}`\n"
            f"Skip:      `{s.get('skip',0)}`\n"
            "-----------------\n"
            f"Downloads: `{dl_gb} GB`\n"
            f"Movies:    `{mov_gb} GB`\n"
            f"Free:      `{free_gb} GB`"
        )

    def _fmt_downloading():
        rows = _db("""
            SELECT p.code, p.retry_count,
                   COALESCE((SELECT SUM(size_bytes) FROM pikpak_cloud WHERE code=p.code),0),
                   COALESCE(p.speed_bps,0), COALESCE(p.eta_seconds,-1)
            FROM process p
            WHERE p.status IN ('pending','downloading') AND p.on_disk=0
            ORDER BY p.updated_at DESC
        """)
        lines = []
        for code, retry, total, spd, eta in rows:
            folder = os.path.join(DOWNLOAD_DIR, code)
            if not os.path.exists(folder): continue
            disk = sum(
                os.path.getsize(os.path.join(r,f))
                for r,_,fs in os.walk(folder) for f in fs
                if os.path.exists(os.path.join(r,f))
            )
            if disk == 0: continue
            pct   = f"{disk/total*100:.1f}%" if total > 0 else "?"
            speed = st.fmt_speed(spd)
            eta_s = st.fmt_eta(eta)
            tgb   = f"{total/1024**3:.1f}GB" if total > 0 else "?"
            lines.append(f"`{code}` {pct} - {disk/1024**2:.0f}MB/{tgb} - {speed} - ETA {eta_s}")
        if not lines:
            return "No files downloading."
        return "*Downloading:*\n\n" + "\n".join(lines)

    @bot.message_handler(commands=["start","help"])
    def cmd_help(msg):
        bot.reply_to(msg,
            "*PikPak Bot Commands*\n\n"
            "/status - Pipeline overview\n"
            "/downloading - Active downloads\n"
            "/done - Last 10 completed\n"
            "/exhausted - Exhausted codes\n"
            "/pending - Pending codes\n"
            "/retry CODE - Reset exhausted\n"
            "/skip CODE - Skip a code\n"
            "/actors - List actors\n"
            "/addactor Name|URL - Add actor\n"
            "/disk - Disk usage\n"
            "/crawlnow - Trigger crawl\n"
        )

    @bot.message_handler(commands=["status"])
    def cmd_status(msg):
        bot.reply_to(msg, _fmt_status())

    @bot.message_handler(commands=["downloading"])
    def cmd_downloading(msg):
        bot.reply_to(msg, _fmt_downloading())

    @bot.message_handler(commands=["done"])
    def cmd_done(msg):
        rows = _db("SELECT code, move_path, updated_at FROM process WHERE status='done' ORDER BY updated_at DESC LIMIT 10")
        if not rows:
            bot.reply_to(msg, "No done codes yet."); return
        lines = []
        for code, path, ts in rows:
            t = time.strftime("%d/%m %H:%M", time.localtime(ts)) if ts else "--"
            lines.append(f"`{code}` - {t}")
        bot.reply_to(msg, "*Last 10 done:*\n\n" + "\n".join(lines))

    @bot.message_handler(commands=["exhausted"])
    def cmd_exhausted(msg):
        rows = _db("SELECT code, retry_count FROM process WHERE status='exhausted' ORDER BY updated_at DESC LIMIT 20")
        if not rows:
            bot.reply_to(msg, "No exhausted codes."); return
        kb = InlineKeyboardMarkup()
        lines = []
        for code, retry in rows:
            lines.append(f"`{code}` (retry {retry})")
            kb.add(InlineKeyboardButton(f"Retry {code}", callback_data=f"retry:{code}"))
        bot.reply_to(msg, "*Exhausted:*\n\n" + "\n".join(lines), reply_markup=kb)

    @bot.message_handler(commands=["pending"])
    def cmd_pending(msg):
        rows = _db("SELECT code FROM process WHERE status='pending' AND on_disk=0 ORDER BY updated_at DESC LIMIT 15")
        if not rows:
            bot.reply_to(msg, "No pending codes."); return
        lines = [f"`{r[0]}`" for r in rows]
        bot.reply_to(msg, "*Pending:*\n\n" + "\n".join(lines))

    @bot.message_handler(commands=["retry"])
    def cmd_retry(msg):
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(msg, "Usage: /retry CODE"); return
        code = parts[1].strip().upper()
        db_run_wait("UPDATE process SET status='pending', retry_count=0, updated_at=? WHERE code=?", (int(time.time()), code))
        db_flush()
        bot.reply_to(msg, f"Reset `{code}` -> pending")

    @bot.message_handler(commands=["skip"])
    def cmd_skip(msg):
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(msg, "Usage: /skip CODE"); return
        code = parts[1].strip().upper()
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("Confirm skip", callback_data=f"skip:{code}"),
            InlineKeyboardButton("Cancel", callback_data="cancel")
        )
        bot.reply_to(msg, f"Skip code `{code}`?", reply_markup=kb)

    @bot.message_handler(commands=["actors"])
    def cmd_actors(msg):
        rows = _db("SELECT id, name, url FROM actors ORDER BY name")
        if not rows:
            bot.reply_to(msg, "No actors yet."); return
        kb = InlineKeyboardMarkup(row_width=1)
        lines = []
        for aid, name, url in rows:
            lines.append(f"*{name}*\n`{url}`")
            kb.add(InlineKeyboardButton(f"Delete {name}", callback_data=f"delactor:{aid}"))
        bot.reply_to(msg, "*Actors:*\n\n" + "\n\n".join(lines), reply_markup=kb)

    @bot.message_handler(commands=["addactor"])
    def cmd_addactor(msg):
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2 or "|" not in parts[1]:
            bot.reply_to(msg, "Usage: /addactor Name|https://url..."); return
        name, _, url = parts[1].partition("|")
        name, url = name.strip(), url.strip()
        if not name or not url:
            bot.reply_to(msg, "Missing name or URL"); return
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute("INSERT INTO actors (name, url) VALUES (?,?)", (name, url))
            conn.commit(); conn.close()
            bot.reply_to(msg, f"Added actor `{name}`")
        except Exception as e:
            bot.reply_to(msg, f"Error: {e}")

    @bot.message_handler(commands=["disk"])
    def cmd_disk(msg):
        try:
            u = shutil.disk_usage(DISK_PATH)
            total = u.total / 1024**3
            used  = u.used  / 1024**3
            free  = u.free  / 1024**3
            pct   = used / total * 100
            bar   = "#" * int(pct/5) + "-" * (20 - int(pct/5))
            bot.reply_to(msg,
                f"*Disk {DISK_PATH}*\n\n"
                f"`[{bar}]` {pct:.1f}%\n\n"
                f"Total: `{total:.1f} GB`\n"
                f"Used:  `{used:.1f} GB`\n"
                f"Free:  `{free:.1f} GB`\n\n"
                f"Downloads: `{_dir_gb(DOWNLOAD_DIR)} GB`\n"
                f"Movies:    `{_dir_gb(MOVIES_DIR)} GB`"
            )
        except Exception as e:
            bot.reply_to(msg, f"Error: {e}")

    @bot.message_handler(commands=["crawlnow"])
    def cmd_crawlnow(msg):
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("Confirm crawl", callback_data="crawlnow"),
            InlineKeyboardButton("Cancel", callback_data="cancel")
        )
        bot.reply_to(msg, "Trigger crawl now?", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: True)
    def on_callback(call):
        data = call.data
        bot.answer_callback_query(call.id)
        cid = call.message.chat.id
        mid = call.message.message_id

        if data == "cancel":
            bot.edit_message_text("Cancelled.", cid, mid)

        elif data.startswith("retry:"):
            code = data.split(":",1)[1]
            db_run_wait("UPDATE process SET status='pending', retry_count=0, updated_at=? WHERE code=?", (int(time.time()), code))
            db_flush()
            bot.edit_message_text(f"Reset `{code}` -> pending", cid, mid, parse_mode="Markdown")

        elif data.startswith("skip:"):
            code = data.split(":",1)[1]
            db_run_wait("UPDATE process SET status='skip', updated_at=? WHERE code=?", (int(time.time()), code))
            db_flush()
            bot.edit_message_text(f"Skipped `{code}`", cid, mid, parse_mode="Markdown")

        elif data.startswith("delactor:"):
            aid = data.split(":",1)[1]
            conn = sqlite3.connect(DB_PATH, timeout=10)
            row = conn.execute("SELECT name FROM actors WHERE id=?", (aid,)).fetchone()
            name = row[0] if row else aid
            conn.execute("DELETE FROM actors WHERE id=?", (aid,))
            conn.commit(); conn.close()
            bot.edit_message_text(f"Deleted actor `{name}`", cid, mid, parse_mode="Markdown")

        elif data == "crawlnow":
            bot.edit_message_text("Triggering crawl...", cid, mid)
            import subprocess, sys
            threading.Thread(
                target=lambda: subprocess.run([sys.executable, "-u", "crawl.py"], timeout=7200),
                daemon=True
            ).start()
            bot.send_message(CHAT_ID, "Crawl triggered!")

    def notify(msg_text):
        try: bot.send_message(CHAT_ID, msg_text, parse_mode="Markdown")
        except Exception as e: print(f"[TELEGRAM] notify error: {e}", flush=True)

    def notify_done(code, path=""):
        notify(f"Done: `{code}`\n`{path}`")

    def notify_added(code):
        notify(f"Added to cloud: `{code}`")

    def notify_stall(code):
        notify(f"Stall detected: `{code}`")

    def _periodic_report():
        DISK_WARN_GB = int(_cfg.get("DISK_WARN_GB", 200))
        last_disk_warn = 0
        while True:
            time.sleep(1800)
            try:
                free = shutil.disk_usage(DISK_PATH).free / 1024**3
                if free < DISK_WARN_GB and time.time() - last_disk_warn > 3600:
                    notify(f"WARNING: Disk low! Only {free:.1f} GB free")
                    last_disk_warn = time.time()
            except: pass

    def start_bot_thread():
        def _run():
            print("[TELEGRAM] Bot started.", flush=True)
            threading.Thread(target=_periodic_report, daemon=True, name="tg-report").start()
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        t = threading.Thread(target=_run, daemon=True, name="telegram-bot")
        t.start()
        return t

if __name__ == "__main__":
    if TOKEN and CHAT_ID:
        print("[TELEGRAM] Running bot...")
        bot.infinity_polling()
    else:
        print("[TELEGRAM] Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in bot.env")