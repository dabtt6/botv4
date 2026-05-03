#!/bin/bash

REPO_DIR="/docker/media-stack/botv4"

cd $REPO_DIR || exit

while true; do
    inotifywait -r -e modify,create,delete,move .

    echo "[AUTO PUSH] Detected change..."

    git add .
    git commit -m "auto update $(date '+%Y-%m-%d %H:%M:%S')" || true
    git push origin main
done
