# -*- coding: utf-8 -*-
import requests, re, time, random
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import db_writer
db_writer.start()
from db_writer import db_run, db_runmany, db_get

from config import CRAWL_MAX_THREADS as MAX_THREADS, CRAWL_STOP_THRESHOLD as STOP_THRESHOLD

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_all_actors():
    return db_get("SELECT name, url FROM actors")

def save_code(actor_name, code):
    """
    Tra ve True neu la code moi.
    """
    existing = db_get("SELECT 1 FROM crawl WHERE code=?", (code,))
    is_new = not existing
    db_run("""
        INSERT INTO crawl (code, actor_name, is_get_torrent)
        VALUES (?, ?, 0)
        ON CONFLICT(code) DO NOTHING
    """, (code, actor_name))
    return is_new

def crawl_worker(actor_info):
    actor_name, actor_url = actor_info
    page = 1
    consecutive_old = 0

    while True:
        url = actor_url if page == 1 else f"{actor_url}page/{page}/"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                break

            soup = BeautifulSoup(res.text, "html.parser")
            articles = soup.select("article, .post, .inside-article")
            if not articles:
                break

            for item in articles:
                link_tag = item.select_one("h2 a")
                if not (link_tag and link_tag.get("title")):
                    continue
                code_match = re.search(r'[A-Z0-9]{2,10}-\d+', link_tag["title"])
                if not code_match:
                    continue

                code = code_match.group(0)
                is_new = save_code(actor_name, code)

                if is_new:
                    print(f"  NEW: [{actor_name}] {code}", flush=True)
                    consecutive_old = 0
                else:
                    consecutive_old += 1
                    print(f"  SKIP: {code} ({consecutive_old}/{STOP_THRESHOLD})", flush=True)

                if consecutive_old >= STOP_THRESHOLD:
                    print(f"  STOP {actor_name}: {STOP_THRESHOLD} old in a row.", flush=True)
                    db_writer.db_flush()
                    return

            page += 1
            time.sleep(random.uniform(0.1, 0.3))

        except Exception as e:
            print(f"  ERROR {actor_name}: {e}", flush=True)
            break

    db_writer.db_flush()

def main():
    actors = db_get("SELECT name, url FROM actors")
    if not actors:
        print("[CRAWL] Bang actors trong!", flush=True)
        return

    print(f"[CRAWL] {len(actors)} actors, nguong dung={STOP_THRESHOLD}.", flush=True)
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        executor.map(crawl_worker, actors)
    print("[CRAWL] Done.", flush=True)

if __name__ == "__main__":
    main()
