# 🤖 PikPak Bot v4

> Pipeline tự động hóa tải và quản lý media: Crawl → Torrent → PikPak Cloud → Local NAS → Jellyfin

## 📋 Mô tả

**botv4** là hệ thống tự động hóa media chạy 24/7 trên Ubuntu Server, được đóng gói bằng Docker. Hệ thống crawl danh sách phim, tải torrent qua qBittorrent, đẩy lên PikPak Cloud, sau đó tải về NAS và phục vụ qua Jellyfin — toàn bộ có thể điều khiển qua Telegram bot.

## 🏗️ Kiến trúc hệ thống

```
crawl.py ──► torrent.py ──► pikpak_cloud ──► downloader.py ──► /data/movies ──► Jellyfin
                                   ▲                                   ▲
                          cloud_scanner.py                       agent.py / watcher.py
                                              
                          Tất cả điều khiển qua: telegram_bot.py + dashboard.py
```

### Các luồng chạy song song (Daemon Threads)

| Thread | Vai trò | Tần suất |
|--------|---------|----------|
| `db_writer` | Singleton writer thread — tất cả ghi DB đi qua đây, tránh conflict | Luôn chạy |
| `agent.py` | Scan disk lần đầu khi khởi động, đồng bộ `agent_snapshot` | 1 lần/start |
| `watcher.py` | Monitor realtime `/data/movies` | Liên tục (inotify) |
| `crawl_thread` | Chạy `crawl.py` + `torrent.py` tuần tự | 1 lần/ngày |
| `cloud_scanner` | Scan thư mục `/My Pack` trên PikPak → cập nhật `pikpak_cloud` | Mỗi 30 phút |
| `classifier` | Phân loại hàng đợi `crawl` → `process` | Mỗi 5 phút |
| `downloader` | Download + verify + move file về NAS | Liên tục |
| `telegram_bot` | Nhận lệnh và gửi thông báo qua Telegram | Luôn chạy |

## 📁 Cấu trúc project

```
botv4/
├── main.py               # Orchestrator — khởi động tất cả thread
├── config.py             # Cấu hình tập trung (interval, path, ...)
├── bot.env               # Credentials (TOKEN, PASS, ...) — không commit
│
├── crawl.py              # Crawl danh sách phim từ nguồn
├── torrent.py            # Thêm torrent vào qBittorrent
├── classifier.py         # Phân loại crawl → hàng đợi xử lý
├── downloader.py         # Download từ PikPak về local
├── cloud_scanner.py      # Scan PikPak cloud storage
├── agent.py              # Scan disk, build agent_snapshot
├── watcher.py            # Realtime monitor /data/movies
│
├── db_writer.py          # Thread-safe SQLite writer singleton
├── migrate_db.py         # Schema migration
├── speed_tracker.py      # Theo dõi tốc độ download / ETA
│
├── telegram_bot.py       # Bot Telegram — điều khiển & thông báo
├── telegram.py           # Helper gửi tin nhắn Telegram
│
├── dashboard.py          # Flask web dashboard (backend)
├── dashboard.html        # Flask web dashboard (frontend)
├── dashboard_config.json # Cấu hình dashboard
│
├── botv4_control.py      # Remote control (LAN GUI client)
├── v.py                  # Utility script
│
├── Dockerfile            # Image build
├── docker-compose.yml    # Stack deployment (bot + Jellyfin)
├── entrypoint.sh         # Container entrypoint
├── requirements.txt      # Python dependencies
├── test_project.py       # Test suite (41 tests)
│
└── jellyfin/config/      # Jellyfin persistent config
```

## ⚙️ Cài đặt & Triển khai

### Yêu cầu

- Ubuntu Server (hoặc Debian-based)
- Docker + Docker Compose
- Tài khoản PikPak
- Telegram Bot Token + Chat ID

### 1. Clone repo

```bash
git clone https://github.com/dabtt6/botv4.git
cd botv4
```

### 2. Tạo file `bot.env`

```env
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
PIKPAK_USER=your_pikpak_email
PIKPAK_PASS=your_pikpak_password
DOWNLOAD_DIR=/data/downloads
MOVIES_DIR=/data/movies
DISK_PATH=/data
DB_NAME=/app/crawler_master_full.db
DISK_WARN_GB=200
```

### 3. Khởi động

```bash
docker compose up -d --build
```

### 4. Xem logs

```bash
docker logs -f pikpak-bot-v4
```

## 🗄️ Database

File SQLite: `crawler_master_full.db`

| Bảng | Mô tả |
|------|-------|
| `crawl` | Danh sách phim đã crawl |
| `torrent` | Torrent links |
| `process` | Trạng thái xử lý mỗi code (pending/downloading/done/exhausted/skip) |
| `pikpak_cloud` | Files trên PikPak cloud |
| `agent_snapshot` | Snapshot file trên disk |
| `actors` | Danh sách diễn viên/nguồn crawl |

**Trạng thái `process`:**

```
pending → downloading → done
       ↘ exhausted (retry quá nhiều)
       ↘ skip (bỏ qua thủ công)
```

## 📱 Telegram Bot Commands

| Lệnh | Chức năng |
|------|-----------|
| `/status` | Tổng quan pipeline (crawl, cloud, disk, done/pending) |
| `/downloading` | Danh sách file đang download với % và tốc độ |
| `/done` | 10 code hoàn thành gần nhất |
| `/pending` | 15 code đang chờ xử lý |
| `/exhausted` | Code đã retry quá nhiều (có nút Retry inline) |
| `/retry CODE` | Reset code về pending |
| `/skip CODE` | Bỏ qua một code (có xác nhận) |
| `/actors` | Danh sách nguồn crawl (có nút Delete) |
| `/addactor Name\|URL` | Thêm nguồn crawl mới |
| `/disk` | Dung lượng disk với progress bar |
| `/crawlnow` | Trigger crawl ngay (có xác nhận) |

Bot cũng tự động gửi cảnh báo khi disk còn dưới ngưỡng `DISK_WARN_GB`.

## 🐳 Docker Services

```yaml
# docker-compose.yml
services:
  pikpak-bot:     # Bot chính — network_mode: host
  jellyfin:       # Media server — network_mode: host, GPU passthrough /dev/dri
```

**Volumes được mount:**
- `crawler_master_full.db` — SQLite database
- `/data/downloads` — Thư mục tải về
- `/data/movies` — Thư mục media Jellyfin
- `/root/.config/pikpaktui` — PikPak session cache
- `/var/run/docker.sock` — Quản lý Docker từ bên trong container

## 🧪 Testing

```bash
# Chạy toàn bộ test suite (41 tests)
python test_project.py

# Hoặc trong container
docker exec pikpak-bot-v4 python test_project.py
```

## 📊 Dashboard

Flask web dashboard chạy cùng container, xem trạng thái pipeline qua trình duyệt trên LAN.

```
http://<server-ip>:<DASHBOARD_PORT>
```

## 🔄 Luồng hoạt động đầy đủ

```
1. crawl.py        — Crawl danh sách code/torrent từ nguồn (actors table)
2. torrent.py      — Thêm magnet/torrent vào qBittorrent
3. classifier.py   — Đọc crawl → tạo record trong process (status=pending)
4. cloud_scanner   — Detect file trên PikPak → cập nhật pikpak_cloud
5. downloader.py   — Kéo file từ PikPak về /data/downloads → move sang /data/movies
6. watcher.py      — Detect file mới trong /data/movies → update agent_snapshot
7. Jellyfin        — Tự detect media mới và cập nhật thư viện
```

## 📝 Ghi chú

- `bot.env` chứa credentials nhạy cảm — đã được `.gitignore` loại trừ
- `db_writer` là thread DUY NHẤT ghi DB → không bao giờ có write conflict
- Tất cả thread là daemon → `main.py` giữ tiến trình sống bằng vòng lặp `sleep(60)`
- Khi shutdown (Ctrl+C), `db_flush()` được gọi để đảm bảo không mất dữ liệu

## 🛠️ Tech Stack

- **Python 3** — asyncio, threading, sqlite3, subprocess
- **pyTelegramBotAPI** — Telegram bot
- **Flask** — Web dashboard
- **SQLite** — Database duy nhất, thread-safe qua db_writer
- **Docker / Docker Compose** — Deployment
- **Jellyfin** — Media server

---

*botv4 — Personal media automation pipeline. Self-hosted, 24/7.*
