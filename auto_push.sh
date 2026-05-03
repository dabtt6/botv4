#!/bin/bash

REPO_DIR="/docker/media-stack/botv4"

cd $REPO_DIR || exit

while true; do
    /usr/bin/inotifywait -r -e modify,create,delete,move --exclude '(\.git|\.swp|\.log|\.db)' .

    echo "[WAIT] batching changes..."
    sleep 5

    git add .

    # nếu không có thay đổi thì skip
    git diff --cached --quiet && continue

    echo "[AUTO PUSH] committing..."
    git commit -m "auto update $(date '+%Y-%m-%d %H:%M:%S')"

    echo "[AUTO PUSH] pushing..."
    git push origin main
done
