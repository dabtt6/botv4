# -*- coding: utf-8 -*-
import cloudscraper
from bs4 import BeautifulSoup
import sqlite3
import os
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor
import threading

# ===== CONFIG =====
DB_PATH = "crawler_master_full.db"
TABLE_NAME = "agent_snapshot"
CODE_COLUMN = "code"
BASE_MOVIES_DIR = "/data/movies"
BAN_WAIT_TIME = 20
MAX_THREADS = 2

last_ban_time = 0
ban_lock = threading.Lock()

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)

def normalize(text):
    if not text: return ""
    return re.sub(r'[^a-z0-9]', '', text.lower())

def check_global_pause():
    global last_ban_time
    with ban_lock:
        elapsed = time.time() - last_ban_time
        if elapsed < BAN_WAIT_TIME:
            time.sleep(BAN_WAIT_TIME - elapsed)

def trigger_ban():
    global last_ban_time
    with ban_lock:
        if time.time() - last_ban_time > 2:
            last_ban_time = time.time()
            print(f"!!! BAN DETECTED: Sleeping {BAN_WAIT_TIME}s !!!")

# ===== LOGIC TẠO NFO =====
def create_nfo(folder_path, code, title, actresses):
    nfo_path = os.path.join(folder_path, "movie.nfo")
    actor_xml = ""
    for name in actresses:
        actor_xml += f"""    <actor>
        <name>{name}</name>
        <role>Actress</role>
    </actor>\n"""

    nfo_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<movie>
    <title>[{code}] {title}</title>
    <uniqueid type="num" default="true">{code}</uniqueid>
{actor_xml}</movie>"""
    
    with open(nfo_path, "w", encoding="utf-8") as f:
        f.write(nfo_content)

# ===== MAIN CRAWLER =====
def get_movie_data(detail_url, code):
    check_global_pause()
    try:
        r = scraper.get(detail_url, timeout=20)
        if r.status_code == 403:
            trigger_ban()
            return "RETRY"
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # 1. Lấy thông tin diễn viên (Actress) từ cấu trúc <li><strong>Actress:</strong>...
        actresses = []
        info_lis = soup.find_all("li")
        for li in info_lis:
            if li.strong and "Actress" in li.strong.get_text():
                links = li.find_all("a")
                for a in links:
                    actresses.append(a.get_text(strip=True))

        # 2. Lấy tiêu đề phim
        title = soup.find("h1").get_text(strip=True) if soup.find("h1") else code

        # 3. Tìm poster (ưu tiên javmiku)
        poster_url = None
        imgs = soup.find_all("img")
        code_norm = normalize(code)
        for img in imgs:
            src = img.get("src") or img.get("data-src") or ""
            if code_norm in normalize(img.get("alt", "")) or code_norm in normalize(src):
                if "javmiku.com" in src:
                    poster_url = src
                    break
        if not poster_url:
            for img in imgs:
                src = img.get("src") or img.get("data-src") or ""
                if "javmiku.com" in src and "avatar" not in src.lower():
                    poster_url = src
                    break

        return {"title": title, "actresses": actresses, "poster_url": poster_url}
    except:
        return None

def download_image(url, path):
    check_global_pause()
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://jav.guru/"}
        r = scraper.get(url, headers=headers, timeout=30)
        if r.status_code == 403:
            trigger_ban()
            return False
        if r.status_code == 200:
            with open(path, "wb") as f:
                f.write(r.content)
            return True
    except: pass
    return False

def process_code(code):
    code = str(code).strip()
    movie_folder = os.path.join(BASE_MOVIES_DIR, code)
    poster_path = os.path.join(movie_folder, "poster.jpg")
    nfo_path = os.path.join(movie_folder, "movie.nfo")

    if os.path.exists(poster_path) and os.path.exists(nfo_path):
        return

    success = False
    while not success:
        check_global_pause()
        print(f"PROCESS: {code}")
        
        # Search link bài viết
        search_url = f"https://jav.guru/?s={code}"
        r_search = scraper.get(search_url, timeout=20)
        if r_search.status_code == 403:
            trigger_ban(); continue
            
        soup_search = BeautifulSoup(r_search.text, "html.parser")
        detail_link = None
        code_norm = normalize(code)
        for h2 in soup_search.find_all("h2"):
            a = h2.find("a")
            if a and code_norm in normalize(a.get("title", "") + a.get_text()):
                detail_link = a["href"]; break
        
        if not detail_link: break

        # Lấy data (Actress, Title, Poster)
        data = get_movie_data(detail_link, code)
        if data == "RETRY": continue
        if not data: break

        os.makedirs(movie_folder, exist_ok=True)

        # Tạo file NFO
        create_nfo(movie_folder, code, data['title'], data['actresses'])
        
        # Tải Poster
        if data['poster_url']:
            if download_image(data['poster_url'], poster_path):
                print(f"OK: {code} (Poster + NFO)")
                success = True
            else:
                if time.time() - last_ban_time < BAN_WAIT_TIME: continue
                break
        else:
            print(f"OK: {code} (NFO Only - No Poster)")
            success = True

def main():
    try:
        conn = sqlite3.connect(DB_PATH)
        codes = [r[0] for r in conn.execute(f"SELECT {CODE_COLUMN} FROM {TABLE_NAME}").fetchall() if r[0]]
        conn.close()
    except: return

    print(f"STARTING: {len(codes)} codes")
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as exe:
        exe.map(process_code, codes)

if __name__ == "__main__":
    main()