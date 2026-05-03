# -*- coding: utf-8 -*-
import re, time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import db_writer
db_writer.start()
from db_writer import db_run, db_runmany, db_get

from config import TORRENT_MAX_THREADS as MAX_THREADS

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def parse_size_to_mb(size_str):
    m = re.search(r'(\d+\.?\d*)\s?(GB|MB|GiB|MiB)', size_str, re.IGNORECASE)
    if not m:
        return 0
    v, u = float(m.group(1)), m.group(2).upper()
    return v * 1024 if u in ("GB", "GIB") else v

def save_torrent(actor_name, code, title, quality, size, dl_link):
    db_run("""
        INSERT INTO torrent (code, actor_name, title, quality, size, download_link, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            title=excluded.title, quality=excluded.quality,
            size=excluded.size, download_link=excluded.download_link,
            created_at=excluded.created_at
    """, (code, actor_name, title, quality, size, dl_link, int(time.time())))

def actor_thread_worker(actor_name, code_list):
    session = requests.Session()
    session.headers.update(headers)

    for code in code_list:
        try:
            res = session.get(
                f"https://sukebei.nyaa.si/?q={code}&f=0&c=0_0",
                timeout=10
            )
            soup = BeautifulSoup(res.text, "lxml")
            items = soup.select("table.torrent-list tbody tr")

            best = None
            max_weight = -1

            for item in items:
                cols = item.find_all("td")
                if len(cols) < 4:
                    continue
                title = cols[1].select_one("a:not(.comments)").get("title", "").strip()
                q_val = (3 if re.search(r'FHD|1080p', title, re.IGNORECASE)
                         else 2 if re.search(r'HD|720p', title, re.IGNORECASE) else 1)
                weight = q_val * 1_000_000 + parse_size_to_mb(cols[3].text.strip())

                if weight > max_weight:
                    mag = cols[2].select_one('a[href^="magnet:?"]')
                    dl  = cols[2].select_one('a[href*=".torrent"]')
                    link = (mag["href"] if mag
                            else ("https://sukebei.nyaa.si" + dl["href"] if dl else ""))
                    if link:
                        max_weight = weight
                        best = {
                            'title': title,
                            'quality': 'FHD' if q_val == 3 else 'HD',
                            'size': cols[3].text.strip(),
                            'link': link
                        }

            if best:
                save_torrent(actor_name, code,
                             best['title'], best['quality'],
                             best['size'], best['link'])
                print(f"  OK: {code}", flush=True)

            # Danh dau da lay torrent
            db_run("UPDATE crawl SET is_get_torrent=1 WHERE code=?", (code,))

        except Exception as e:
            print(f"  ERROR {code}: {e}", flush=True)

        time.sleep(0.1)

    db_writer.db_flush()

def main():
    # Chi lay code chua co torrent, chua co tren disk, chua co tren cloud
    rows = db_get("""
        SELECT c.actor_name, c.code FROM crawl c
        WHERE c.is_get_torrent = 0
          AND c.code NOT IN (SELECT code FROM agent_snapshot)
    """)

    if not rows:
        print("[TORRENT] Nothing to process.", flush=True)
        return

    # Danh dau code da co tren disk -> skip luon
    db_run("""
        UPDATE crawl SET is_get_torrent=1
        WHERE is_get_torrent=0
          AND code IN (SELECT code FROM agent_snapshot)
    """)
    db_writer.db_flush()

    data = {}
    for actor, code in rows:
        data.setdefault(actor, []).append(code)

    print(f"[TORRENT] Processing {len(rows)} codes...", flush=True)
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as ex:
        for actor, codes in data.items():
            ex.submit(actor_thread_worker, actor, codes)

    print("[TORRENT] Done.", flush=True)

if __name__ == "__main__":
    main()