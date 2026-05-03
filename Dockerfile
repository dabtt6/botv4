FROM python:3.10-slim

# System tools
RUN apt-get update && apt-get install -y \
    curl bash ca-certificates sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# pikpaktui
RUN curl -fsSL https://app.snaix.homes/pikpaktui/install.sh | bash

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source code
COPY db_writer.py .
COPY migrate_db.py .
COPY agent.py .
COPY crawl.py .
COPY torrent.py .
COPY watcher.py .
COPY cloud_scanner.py .
COPY classifier.py .
COPY downloader.py .
COPY main.py .
COPY telegram.py .
COPY dashboard.py .
COPY dashboard.html .
COPY dashboard_config.json .
COPY config.py .
COPY bot.env .
COPY speed_tracker.py .
COPY telegram_bot.py .

# Data dirs
RUN mkdir -p /data/downloads /data/movies

# Auto login khi container start
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]