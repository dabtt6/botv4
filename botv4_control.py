"""
BotV4 Control Panel - Windows Desktop App
Kết nối tới Flask API (port 8888) chạy trong Docker Ubuntu

Cài đặt:
  pip install requests

Chạy:
  python botv4_control.py

Đóng gói thành .exe:
  pip install pyinstaller
  pyinstaller --onefile --windowed --name "BotV4 Control" botv4_control.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, scrolledtext
import threading
import time
import requests
import json
from datetime import datetime


# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8888
REFRESH_SEC  = 10

# Dark theme colors
BG        = "#0d1117"
SURFACE   = "#161b22"
SURFACE2  = "#21262d"
BORDER    = "#30363d"
ACCENT    = "#58a6ff"
GREEN     = "#3fb950"
RED       = "#f85149"
YELLOW    = "#d29922"
PURPLE    = "#bc8cff"
TEXT      = "#e6edf3"
MUTED     = "#8b949e"
FONT_MONO = ("Consolas", 10)
FONT_SM   = ("Consolas", 9)
FONT_LG   = ("Segoe UI", 11, "bold")
FONT_HEAD = ("Segoe UI", 10, "bold")


# ──────────────────────────────────────────────
# API CLIENT
# ──────────────────────────────────────────────
class BotAPI:
    def __init__(self):
        self.host = DEFAULT_HOST
        self.port = DEFAULT_PORT
        self.timeout = 5

    @property
    def base(self):
        return f"http://{self.host}:{self.port}"

    def get(self, path, params=None):
        r = requests.get(f"{self.base}{path}", params=params, timeout=self.timeout)
        return r.json()

    def post(self, path, data):
        r = requests.post(f"{self.base}{path}", json=data, timeout=self.timeout)
        return r.json()

    def stats(self):
        return self.get("/api/stats")

    def logs(self, n=100):
        return self.get("/api/logs", params={"n": n})

    def actors(self):
        return self.get("/api/actors")

    def actors_stats(self):
        return self.get("/api/actors/stats")

    def actors_films(self, name):
        return self.get("/api/actors/films", params={"name": name})

    def add_actor(self, name, url):
        return self.post("/api/actors/add", {"name": name, "url": url})

    def delete_actor(self, actor_id):
        return self.post("/api/actors/delete", {"id": actor_id})

    def reload_config(self):
        return self.get("/api/config")


api = BotAPI()


# ──────────────────────────────────────────────
# HELPER WIDGETS
# ──────────────────────────────────────────────
def make_frame(parent, **kw):
    kw.setdefault("bg", SURFACE)
    kw.setdefault("relief", "flat")
    return tk.Frame(parent, **kw)

def make_label(parent, text, **kw):
    kw.setdefault("bg", SURFACE)
    kw.setdefault("fg", TEXT)
    kw.setdefault("font", FONT_MONO)
    return tk.Label(parent, text=text, **kw)

def make_button(parent, text, cmd, color=ACCENT, **kw):
    btn = tk.Button(
        parent, text=text, command=cmd,
        bg=SURFACE2, fg=color,
        activebackground=BORDER, activeforeground=color,
        relief="flat", bd=0,
        font=("Segoe UI", 9, "bold"),
        padx=12, pady=5,
        cursor="hand2",
        **kw
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=BORDER))
    btn.bind("<Leave>", lambda e: btn.config(bg=SURFACE2))
    return btn

def stat_card(parent, title, var, color=ACCENT):
    """Một card hiển thị số liệu"""
    f = make_frame(parent, bg=SURFACE2, padx=16, pady=12)
    tk.Label(f, text=title, bg=SURFACE2, fg=MUTED,
             font=("Segoe UI", 8)).pack(anchor="w")
    tk.Label(f, textvariable=var, bg=SURFACE2, fg=color,
             font=("Segoe UI", 22, "bold")).pack(anchor="w")
    return f

def sep(parent, horizontal=True):
    if horizontal:
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=4)
    else:
        tk.Frame(parent, bg=BORDER, width=1).pack(fill="y", padx=4, side="left")


# ──────────────────────────────────────────────
# MAIN APP
# ──────────────────────────────────────────────
class BotControlApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("🤖 PikPak Bot V4 — Control Panel")
        self.geometry("1200x760")
        self.minsize(900, 600)
        self.configure(bg=BG)

        # Apply dark title bar on Windows
        try:
            self.wm_attributes("-alpha", 1.0)
        except:
            pass

        # State
        self.connected = False
        self._auto_refresh = True
        self._refresh_job = None

        # StringVars for stats
        self.sv = {k: tk.StringVar(value="—") for k in [
            "pending", "downloading", "downloaded", "done",
            "skip", "exhausted", "crawl_total", "torrent_total",
            "cloud_codes", "on_disk", "dl_gb", "mov_gb",
            "conn_status", "last_update"
        ]}

        self._build_ui()
        self._schedule_refresh()

    # ─── BUILD UI ──────────────────────────────
    def _build_ui(self):
        # ── Top bar ──
        topbar = tk.Frame(self, bg=SURFACE, height=50)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="⚡ PikPak Bot V4", bg=SURFACE, fg=ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=16, pady=10)

        # Connection
        conn_f = tk.Frame(topbar, bg=SURFACE)
        conn_f.pack(side="right", padx=12)

        tk.Label(conn_f, text="Host:", bg=SURFACE, fg=MUTED,
                 font=FONT_SM).pack(side="left", padx=(0,4))
        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        tk.Entry(conn_f, textvariable=self.host_var, width=14,
                 bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=FONT_SM,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left")

        tk.Label(conn_f, text="Port:", bg=SURFACE, fg=MUTED,
                 font=FONT_SM).pack(side="left", padx=(8,4))
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        tk.Entry(conn_f, textvariable=self.port_var, width=6,
                 bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=FONT_SM,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left")

        make_button(conn_f, "Connect", self._connect, color=GREEN).pack(side="left", padx=(8,0))

        # Status
        self.status_dot = tk.Label(topbar, text="●", bg=SURFACE, fg=RED,
                                   font=("Segoe UI", 14))
        self.status_dot.pack(side="right", padx=(0,4))
        tk.Label(topbar, textvariable=self.sv["conn_status"], bg=SURFACE,
                 fg=MUTED, font=FONT_SM).pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── Notebook tabs ──
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Dark.TNotebook", background=BG, borderwidth=0)
        style.configure("Dark.TNotebook.Tab",
                        background=SURFACE, foreground=MUTED,
                        padding=[14, 7], font=("Segoe UI", 9, "bold"),
                        borderwidth=0)
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", BG)],
                  foreground=[("selected", ACCENT)])

        nb = ttk.Notebook(self, style="Dark.TNotebook")
        nb.pack(fill="both", expand=True, padx=0, pady=0)

        # Tabs
        self.tab_overview = self._build_overview(nb)
        self.tab_downloads = self._build_downloads(nb)
        self.tab_actors = self._build_actors(nb)
        self.tab_logs = self._build_logs(nb)

        nb.add(self.tab_overview,  text="  📊 Overview  ")
        nb.add(self.tab_downloads, text="  ⬇️  Downloads  ")
        nb.add(self.tab_actors,    text="  🎬 Actors  ")
        nb.add(self.tab_logs,      text="  📋 Logs  ")

        # ── Bottom bar ──
        bot = tk.Frame(self, bg=SURFACE, height=26)
        bot.pack(fill="x", side="bottom")
        bot.pack_propagate(False)

        tk.Label(bot, textvariable=self.sv["last_update"],
                 bg=SURFACE, fg=MUTED, font=FONT_SM).pack(side="right", padx=12)

        self.auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(bot, text="Auto refresh", variable=self.auto_var,
                       bg=SURFACE, fg=MUTED, selectcolor=SURFACE2,
                       activebackground=SURFACE, font=FONT_SM,
                       command=self._toggle_auto).pack(side="right", padx=8)

        make_button(bot, "↻ Refresh Now", self._manual_refresh,
                    color=ACCENT).pack(side="left", padx=8, pady=3)
        make_button(bot, "⚙ Reload Config", self._reload_config,
                    color=PURPLE).pack(side="left", padx=2, pady=3)

    # ─── TAB: OVERVIEW ─────────────────────────
    def _build_overview(self, nb):
        f = make_frame(nb, bg=BG)

        # Stat cards row 1 — Process
        r1 = tk.Frame(f, bg=BG)
        r1.pack(fill="x", padx=16, pady=(16, 8))

        cards1 = [
            ("Pending",     "pending",     YELLOW),
            ("Downloading", "downloading", ACCENT),
            ("Downloaded",  "downloaded",  PURPLE),
            ("Done",        "done",        GREEN),
            ("Skip",        "skip",        MUTED),
            ("Exhausted",   "exhausted",   RED),
        ]
        for i, (title, key, color) in enumerate(cards1):
            c = stat_card(r1, title, self.sv[key], color)
            c.grid(row=0, column=i, padx=6, sticky="ew")
            r1.columnconfigure(i, weight=1)

        # Stat cards row 2 — Data
        r2 = tk.Frame(f, bg=BG)
        r2.pack(fill="x", padx=16, pady=(0, 12))

        cards2 = [
            ("Crawled Titles", "crawl_total",   TEXT),
            ("Torrents Found", "torrent_total",  TEXT),
            ("Cloud Codes",    "cloud_codes",   PURPLE),
            ("On Disk",        "on_disk",       GREEN),
            ("Downloads Disk", "dl_gb",         YELLOW),
            ("Movies Disk",    "mov_gb",        ACCENT),
        ]
        for i, (title, key, color) in enumerate(cards2):
            c = stat_card(r2, title, self.sv[key], color)
            c.grid(row=0, column=i, padx=6, sticky="ew")
            r2.columnconfigure(i, weight=1)

        sep(f)

        # Bottom split: Recent Done | Exhausted
        bottom = tk.Frame(f, bg=BG)
        bottom.pack(fill="both", expand=True, padx=16, pady=8)

        # Recent done
        left = make_frame(bottom, bg=SURFACE, padx=0, pady=0)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        tk.Label(left, text="✅ Recent Done", bg=SURFACE, fg=GREEN,
                 font=FONT_HEAD, anchor="w").pack(fill="x", padx=12, pady=(10,4))

        cols_done = ("Code", "Path", "Time")
        self.tree_done = self._make_tree(left, cols_done, heights={0:120, 1:300, 2:130})
        self.tree_done.pack(fill="both", expand=True, padx=8, pady=(0,8))

        # Exhausted
        right = make_frame(bottom, bg=SURFACE, padx=0, pady=0)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        tk.Label(right, text="❌ Exhausted", bg=SURFACE, fg=RED,
                 font=FONT_HEAD, anchor="w").pack(fill="x", padx=12, pady=(10,4))

        cols_ex = ("Code", "Retry")
        self.tree_ex = self._make_tree(right, cols_ex, heights={0:180, 1:60})
        self.tree_ex.pack(fill="both", expand=True, padx=8, pady=(0,8))

        return f

    # ─── TAB: DOWNLOADS ────────────────────────
    def _build_downloads(self, nb):
        f = make_frame(nb, bg=BG)

        tk.Label(f, text="⬇️  Active Downloads", bg=BG, fg=ACCENT,
                 font=FONT_LG, anchor="w").pack(fill="x", padx=16, pady=(14, 6))

        cols = ("Code", "Downloaded MB", "Total MB", "%", "Speed", "ETA", "Retry")
        self.tree_dl = self._make_tree(f, cols, heights={
            0: 150, 1: 100, 2: 100, 3: 60, 4: 90, 5: 90, 6: 60
        })
        self.tree_dl.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Progress bars panel
        self.progress_frame = tk.Frame(f, bg=BG)
        # (populated dynamically)

        return f

    # ─── TAB: ACTORS ───────────────────────────
    def _build_actors(self, nb):
        f = make_frame(nb, bg=BG)

        # Toolbar
        tb = tk.Frame(f, bg=BG)
        tb.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(tb, text="🎬 Actors Management", bg=BG, fg=ACCENT,
                 font=FONT_LG).pack(side="left")

        make_button(tb, "+ Add Actor", self._add_actor, color=GREEN).pack(side="right", padx=4)
        make_button(tb, "🗑 Delete Selected", self._delete_actor, color=RED).pack(side="right", padx=4)
        make_button(tb, "🔍 View Films", self._view_actor_films, color=PURPLE).pack(side="right", padx=4)
        make_button(tb, "↻ Refresh", self._load_actors, color=ACCENT).pack(side="right", padx=4)

        # Split: actor list | stats
        split = tk.Frame(f, bg=BG)
        split.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Actor list
        left = make_frame(split, bg=SURFACE)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left, text="Actors List", bg=SURFACE, fg=MUTED,
                 font=FONT_HEAD).pack(anchor="w", padx=10, pady=(8,4))

        cols_a = ("ID", "Name", "URL")
        self.tree_actors = self._make_tree(left, cols_a, heights={0:40, 1:160, 2:300})
        self.tree_actors.pack(fill="both", expand=True, padx=8, pady=(0,8))

        # Stats
        right = make_frame(split, bg=SURFACE)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        tk.Label(right, text="Actors Stats", bg=SURFACE, fg=MUTED,
                 font=FONT_HEAD).pack(anchor="w", padx=10, pady=(8,4))

        cols_as = ("Name", "Total", "Done", "Pending", "Exhausted", "Skip", "Done GB")
        self.tree_actor_stats = self._make_tree(right, cols_as, heights={
            0:140, 1:55, 2:55, 3:65, 4:75, 5:55, 6:65
        })
        self.tree_actor_stats.pack(fill="both", expand=True, padx=8, pady=(0,8))

        return f

    # ─── TAB: LOGS ─────────────────────────────
    def _build_logs(self, nb):
        f = make_frame(nb, bg=BG)

        tb = tk.Frame(f, bg=BG)
        tb.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(tb, text="📋 Docker Logs", bg=BG, fg=ACCENT,
                 font=FONT_LG).pack(side="left")

        self.log_lines_var = tk.IntVar(value=100)
        tk.Label(tb, text="Lines:", bg=BG, fg=MUTED, font=FONT_SM).pack(side="right", padx=(8,4))
        tk.Spinbox(tb, from_=20, to=500, increment=20,
                   textvariable=self.log_lines_var, width=5,
                   bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                   relief="flat", font=FONT_SM).pack(side="right")
        make_button(tb, "↻ Refresh Logs", self._refresh_logs, color=ACCENT).pack(side="right", padx=4)
        make_button(tb, "🗑 Clear", self._clear_logs, color=MUTED).pack(side="right", padx=4)

        self.log_auto_scroll = tk.BooleanVar(value=True)
        tk.Checkbutton(tb, text="Auto scroll", variable=self.log_auto_scroll,
                       bg=BG, fg=MUTED, selectcolor=SURFACE,
                       activebackground=BG, font=FONT_SM).pack(side="right", padx=8)

        self.log_text = scrolledtext.ScrolledText(
            f,
            bg="#0a0c10", fg="#c9d1d9",
            font=("Consolas", 9),
            relief="flat",
            padx=12, pady=8,
            state="disabled",
            insertbackground=TEXT,
            selectbackground=ACCENT,
            wrap="none"
        )
        self.log_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Tag colors for log lines
        self.log_text.tag_config("error",   foreground=RED)
        self.log_text.tag_config("warn",    foreground=YELLOW)
        self.log_text.tag_config("done",    foreground=GREEN)
        self.log_text.tag_config("info",    foreground=ACCENT)
        self.log_text.tag_config("default", foreground="#c9d1d9")

        return f

    # ─── TREE HELPER ───────────────────────────
    def _make_tree(self, parent, cols, heights=None):
        style = ttk.Style()
        uid = f"Dark{id(parent)}.Treeview"
        style.configure(uid,
                        background=SURFACE2,
                        foreground=TEXT,
                        fieldbackground=SURFACE2,
                        borderwidth=0,
                        rowheight=26,
                        font=FONT_SM)
        style.configure(f"{uid}.Heading",
                        background=SURFACE,
                        foreground=MUTED,
                        font=("Segoe UI", 8, "bold"),
                        relief="flat")
        style.map(uid,
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "#000")])

        tree = ttk.Treeview(parent, columns=cols, show="headings",
                             style=uid)

        for c in cols:
            w = (heights or {}).get(cols.index(c), 100)
            tree.heading(c, text=c)
            tree.column(c, width=w, minwidth=40)

        sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        return tree

    # ─── CONNECT ───────────────────────────────
    def _connect(self):
        api.host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            api.port = int(self.port_var.get())
        except:
            api.port = DEFAULT_PORT

        self.sv["conn_status"].set("Connecting…")
        threading.Thread(target=self._do_connect, daemon=True).start()

    def _do_connect(self):
        try:
            api.stats()
            self.after(0, self._on_connected)
        except Exception as e:
            self.after(0, lambda: self._on_disconnected(str(e)))

    def _on_connected(self):
        self.connected = True
        self.status_dot.config(fg=GREEN)
        self.sv["conn_status"].set(f"Connected  {api.host}:{api.port}")
        self._refresh_all()

    def _on_disconnected(self, err=""):
        self.connected = False
        self.status_dot.config(fg=RED)
        self.sv["conn_status"].set(f"Offline — {err[:40]}" if err else "Offline")

    # ─── REFRESH ───────────────────────────────
    def _schedule_refresh(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        if self._auto_refresh and self.connected:
            self._refresh_job = self.after(REFRESH_SEC * 1000, self._auto_tick)

    def _auto_tick(self):
        if self._auto_refresh:
            self._refresh_all()
        self._schedule_refresh()

    def _toggle_auto(self):
        self._auto_refresh = self.auto_var.get()
        self._schedule_refresh()

    def _manual_refresh(self):
        threading.Thread(target=self._bg_refresh_all, daemon=True).start()

    def _refresh_all(self):
        threading.Thread(target=self._bg_refresh_all, daemon=True).start()

    def _bg_refresh_all(self):
        try:
            data = api.stats()
            self.after(0, lambda: self._update_stats(data))
        except Exception as e:
            self.after(0, lambda: self._on_disconnected(str(e)))

    def _update_stats(self, d):
        p = d.get("process", {})
        self.sv["pending"].set(str(p.get("pending", 0)))
        self.sv["downloading"].set(str(p.get("downloading", 0)))
        self.sv["downloaded"].set(str(p.get("downloaded", 0)))
        self.sv["done"].set(str(p.get("done", 0)))
        self.sv["skip"].set(str(p.get("skip", 0)))
        self.sv["exhausted"].set(str(p.get("exhausted", 0)))
        self.sv["crawl_total"].set(str(d.get("crawl_total", 0)))
        self.sv["torrent_total"].set(str(d.get("torrent_total", 0)))
        self.sv["cloud_codes"].set(str(d.get("cloud_codes", 0)))
        self.sv["on_disk"].set(str(d.get("on_disk", 0)))
        disk = d.get("disk", {})
        self.sv["dl_gb"].set(f"{disk.get('downloads_gb', 0)} GB")
        self.sv["mov_gb"].set(f"{disk.get('movies_gb', 0)} GB")
        self.sv["last_update"].set(f"Last update: {datetime.now().strftime('%H:%M:%S')}")

        # Recent done
        for row in self.tree_done.get_children():
            self.tree_done.delete(row)
        for item in d.get("recent_done", []):
            ts = item.get("ts", "")
            try:
                ts = datetime.fromtimestamp(int(ts)).strftime("%m/%d %H:%M")
            except:
                pass
            self.tree_done.insert("", "end", values=(
                item.get("code", ""),
                item.get("path", "")[:40] or "—",
                ts
            ))

        # Exhausted
        for row in self.tree_ex.get_children():
            self.tree_ex.delete(row)
        for item in d.get("exhausted", []):
            self.tree_ex.insert("", "end", values=(
                item.get("code", ""),
                item.get("retry", "")
            ))

        # Downloads
        for row in self.tree_dl.get_children():
            self.tree_dl.delete(row)
        for item in d.get("downloading", []):
            tag = ""
            pct = item.get("percent", 0)
            if pct >= 90:
                tag = "done"
            elif pct >= 50:
                tag = "mid"
            self.tree_dl.insert("", "end", values=(
                item.get("code", ""),
                f"{item.get('downloaded_mb', 0):.1f}",
                f"{item.get('total_mb', 0):.1f}",
                f"{item.get('percent', 0):.1f}%",
                item.get("speed", "—"),
                item.get("eta", "—"),
                item.get("retry", 0),
            ))

        self.connected = True
        self.status_dot.config(fg=GREEN)
        self._schedule_refresh()

    # ─── ACTORS ────────────────────────────────
    def _load_actors(self):
        if not self.connected:
            messagebox.showwarning("Not connected", "Connect to bot first.")
            return
        threading.Thread(target=self._bg_load_actors, daemon=True).start()

    def _bg_load_actors(self):
        try:
            actors = api.actors()
            stats  = api.actors_stats()
            self.after(0, lambda: self._update_actors(actors, stats))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _update_actors(self, actors, stats):
        for row in self.tree_actors.get_children():
            self.tree_actors.delete(row)
        for a in actors:
            self.tree_actors.insert("", "end", values=(
                a.get("id"), a.get("name"), a.get("url", "")[:50]
            ))

        for row in self.tree_actor_stats.get_children():
            self.tree_actor_stats.delete(row)
        for s in stats:
            self.tree_actor_stats.insert("", "end", values=(
                s.get("name", ""),
                s.get("total", 0),
                s.get("done", 0),
                s.get("pending", 0),
                s.get("exhausted", 0),
                s.get("skip", 0),
                f"{s.get('done_gb', 0):.2f}",
            ))

    def _add_actor(self):
        if not self.connected:
            messagebox.showwarning("Not connected", "Connect to bot first.")
            return
        dlg = ActorDialog(self, "Add Actor")
        self.wait_window(dlg)
        if dlg.result:
            name, url = dlg.result
            threading.Thread(
                target=lambda: self._do_add_actor(name, url), daemon=True
            ).start()

    def _do_add_actor(self, name, url):
        try:
            r = api.add_actor(name, url)
            if r.get("ok"):
                self.after(0, lambda: (
                    messagebox.showinfo("Success", f"Added: {name}"),
                    self._load_actors()
                ))
            else:
                err = r.get("error", "Unknown error")
                self.after(0, lambda: messagebox.showerror("Error", err))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _delete_actor(self):
        sel = self.tree_actors.selection()
        if not sel:
            messagebox.showinfo("Select", "Chọn actor muốn xoá.")
            return
        item = self.tree_actors.item(sel[0])
        actor_id, name = item["values"][0], item["values"][1]
        if not messagebox.askyesno("Confirm", f"Xoá actor:\n{name} (ID={actor_id})?"):
            return
        threading.Thread(
            target=lambda: self._do_delete_actor(actor_id), daemon=True
        ).start()

    def _do_delete_actor(self, actor_id):
        try:
            r = api.delete_actor(actor_id)
            if r.get("ok"):
                self.after(0, lambda: (
                    messagebox.showinfo("Success", "Đã xoá."),
                    self._load_actors()
                ))
            else:
                self.after(0, lambda: messagebox.showerror("Error", r.get("error")))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _view_actor_films(self):
        sel = self.tree_actors.selection()
        if not sel:
            messagebox.showinfo("Select", "Chọn actor để xem phim.")
            return
        item = self.tree_actors.item(sel[0])
        name = item["values"][1]
        threading.Thread(
            target=lambda: self._do_view_films(name), daemon=True
        ).start()

    def _do_view_films(self, name):
        try:
            films = api.actors_films(name)
            self.after(0, lambda: FilmsWindow(self, name, films))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    # ─── LOGS ──────────────────────────────────
    def _refresh_logs(self):
        if not self.connected:
            messagebox.showwarning("Not connected", "Connect to bot first.")
            return
        n = self.log_lines_var.get()
        threading.Thread(target=lambda: self._bg_refresh_logs(n), daemon=True).start()

    def _bg_refresh_logs(self, n):
        try:
            data = api.logs(n)
            lines = data.get("lines", [])
            self.after(0, lambda: self._update_logs(lines))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _update_logs(self, lines):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        for line in lines:
            tag = "default"
            ll = line.lower()
            if "error" in ll or "exception" in ll or "fail" in ll:
                tag = "error"
            elif "warn" in ll or "stall" in ll or "retry" in ll:
                tag = "warn"
            elif "done" in ll or "moved" in ll or "success" in ll:
                tag = "done"
            elif "[main]" in ll or "[dashboard]" in ll or "start" in ll:
                tag = "info"
            self.log_text.insert("end", line + "\n", tag)
        if self.log_auto_scroll.get():
            self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_logs(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ─── RELOAD CONFIG ─────────────────────────
    def _reload_config(self):
        if not self.connected:
            messagebox.showwarning("Not connected", "Connect to bot first.")
            return
        threading.Thread(target=self._do_reload_config, daemon=True).start()

    def _do_reload_config(self):
        try:
            r = api.reload_config()
            if r.get("ok"):
                self.after(0, lambda: messagebox.showinfo(
                    "Config Reloaded", json.dumps(r.get("config", {}), indent=2)[:500]
                ))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))


# ──────────────────────────────────────────────
# DIALOG: Add Actor
# ──────────────────────────────────────────────
class ActorDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.result = None

        tk.Label(self, text="Actor Name:", bg=SURFACE, fg=TEXT,
                 font=FONT_MONO).grid(row=0, column=0, padx=16, pady=(16,4), sticky="w")
        self.name_e = tk.Entry(self, width=30, bg=SURFACE2, fg=TEXT,
                               insertbackground=TEXT, relief="flat",
                               font=FONT_MONO,
                               highlightthickness=1, highlightbackground=BORDER,
                               highlightcolor=ACCENT)
        self.name_e.grid(row=0, column=1, padx=(0,16), pady=(16,4))

        tk.Label(self, text="URL:", bg=SURFACE, fg=TEXT,
                 font=FONT_MONO).grid(row=1, column=0, padx=16, pady=4, sticky="w")
        self.url_e = tk.Entry(self, width=30, bg=SURFACE2, fg=TEXT,
                              insertbackground=TEXT, relief="flat",
                              font=FONT_MONO,
                              highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=ACCENT)
        self.url_e.grid(row=1, column=1, padx=(0,16), pady=4)

        btns = tk.Frame(self, bg=SURFACE)
        btns.grid(row=2, column=0, columnspan=2, pady=16)

        make_button(btns, "Add", self._ok, color=GREEN).pack(side="left", padx=8)
        make_button(btns, "Cancel", self.destroy, color=MUTED).pack(side="left")

        self.name_e.focus()
        self.grab_set()
        self.transient(parent)

    def _ok(self):
        name = self.name_e.get().strip()
        url  = self.url_e.get().strip()
        if not name or not url:
            messagebox.showwarning("Required", "Nhập đủ Name và URL.", parent=self)
            return
        self.result = (name, url)
        self.destroy()


# ──────────────────────────────────────────────
# WINDOW: Films of an actor
# ──────────────────────────────────────────────
class FilmsWindow(tk.Toplevel):
    def __init__(self, parent, actor_name, films):
        super().__init__(parent)
        self.title(f"🎬 Films — {actor_name}")
        self.geometry("800x500")
        self.configure(bg=BG)

        tk.Label(self, text=f"Films of: {actor_name}",
                 bg=BG, fg=ACCENT, font=FONT_LG).pack(padx=16, pady=(12,6), anchor="w")

        # Stats summary
        total = len(films)
        done = sum(1 for f in films if f.get("status") == "done")
        pending = sum(1 for f in films if f.get("status") == "pending")
        total_gb = sum(f.get("size_gb", 0) for f in films if f.get("status") == "done")

        summary = f"  Total: {total}   Done: {done}   Pending: {pending}   Downloaded: {total_gb:.2f} GB"
        tk.Label(self, text=summary, bg=BG, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=16)

        cols = ("Code", "Status", "Quality", "Size (str)", "Size (GB)", "Path")
        style = ttk.Style(self)
        uid = "FilmTree.Treeview"
        style.configure(uid, background=SURFACE2, foreground=TEXT,
                        fieldbackground=SURFACE2, rowheight=24, font=FONT_SM)
        style.configure(f"{uid}.Heading", background=SURFACE,
                        foreground=MUTED, font=("Segoe UI", 8, "bold"))
        style.map(uid, background=[("selected", ACCENT)])

        tree = ttk.Treeview(self, columns=cols, show="headings", style=uid)
        widths = [130, 90, 70, 90, 80, 280]
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w)

        # Color tags by status
        tree.tag_configure("done",      foreground=GREEN)
        tree.tag_configure("pending",   foreground=YELLOW)
        tree.tag_configure("exhausted", foreground=RED)
        tree.tag_configure("skip",      foreground=MUTED)

        for f in films:
            status = f.get("status", "?")
            tree.insert("", "end", values=(
                f.get("code", ""),
                status,
                f.get("quality", "—"),
                f.get("size_str", "—"),
                f"{f.get('size_gb', 0):.2f}",
                f.get("path", "")[:50] or "—",
            ), tags=(status,))

        sb = ttk.Scrollbar(self, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0,8), pady=8)
        tree.pack(fill="both", expand=True, padx=(16,0), pady=(4,16))


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app_win = BotControlApp()

    # Try auto-connect on startup
    def auto_connect():
        time.sleep(0.5)
        try:
            api.stats()
            app_win.after(0, app_win._on_connected)
        except:
            app_win.after(0, lambda: app_win.sv["conn_status"].set(
                f"Offline — enter host:port and click Connect"
            ))

    threading.Thread(target=auto_connect, daemon=True).start()
    app_win.mainloop()
