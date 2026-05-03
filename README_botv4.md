# BotV4 Control Panel — Windows Desktop App

App Python dùng để theo dõi và quản lý PikPak Bot V4 đang chạy trên Docker Ubuntu.

## Yêu cầu

```
pip install requests
```

## Chạy trực tiếp

```
python botv4_control.py
```

## Đóng gói thành .exe (không cần cài Python)

```
pip install pyinstaller
pyinstaller --onefile --windowed --name "BotV4 Control" botv4_control.py
```
File .exe sẽ nằm trong thư mục `dist/`.

## Cấu hình kết nối

- **Host**: IP máy Ubuntu chạy Docker (ví dụ `192.168.1.10` hoặc `localhost` nếu dùng cùng máy)
- **Port**: `8888` (mặc định theo `dashboard_config.json`)
- Nhấn **Connect** để kết nối

## Tính năng

### 📊 Overview
- Xem số liệu realtime: Pending / Downloading / Done / Exhausted
- Xem tổng số title đã crawl, torrent, cloud codes
- Dung lượng disk downloads & movies
- Danh sách phim Done gần đây
- Danh sách code Exhausted (hết retry)

### ⬇️ Downloads
- Xem tất cả download đang chạy
- Hiển thị: MB đã tải, tổng MB, %, tốc độ, ETA, số lần retry

### 🎬 Actors
- Xem danh sách tất cả actor đang theo dõi
- Thêm actor mới (Name + URL)
- Xoá actor
- Xem toàn bộ phim của một actor và trạng thái từng phim

### 📋 Logs
- Đọc Docker logs realtime từ container `pikpak-bot-v4`
- Màu sắc theo loại log: Error (đỏ), Warning (vàng), Done (xanh), Info (xanh lam)
- Auto scroll, tuỳ chọn số dòng

## Auto Refresh

App tự động refresh mỗi **10 giây**. Có thể tắt ở góc dưới phải.

## Lưu ý

- Đảm bảo port 8888 được mở trên máy Ubuntu (hoặc dùng SSH tunnel)
- Docker container phải đang chạy: `docker ps | grep pikpak-bot-v4`
- Nếu dùng qua mạng: `ssh -L 8888:localhost:8888 user@ubuntu-server`
