#!/bin/bash
set -e

# Auto login neu co PIKPAK_USER va PIKPAK_PASS
if [ -n "$PIKPAK_USER" ] && [ -n "$PIKPAK_PASS" ]; then
    echo "[ENTRYPOINT] Logging in as $PIKPAK_USER..."
    PIKPAK_USER="$PIKPAK_USER" PIKPAK_PASS="$PIKPAK_PASS" pikpaktui login
    echo "[ENTRYPOINT] Login done."
else
    echo "[ENTRYPOINT] No PIKPAK_USER/PIKPAK_PASS set, skipping login."
fi

# Start dashboard (background)
echo "[ENTRYPOINT] Starting dashboard..."
python -u /app/dashboard.py &

exec python -u main.py