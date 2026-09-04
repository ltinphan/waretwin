#!/usr/bin/env bash
# WareTwin auto-deploy webhook - run on the host as a systemd service.
# GET /deploy?token=$DEPLOY_TOKEN -> git pull + docker compose up -d --build
# Netcat one-shot server: nothing to install beyond bash+nc.
set -uo pipefail

PORT="${DEPLOY_PORT:-8712}"
TOKEN="${DEPLOY_TOKEN:?set DEPLOY_TOKEN}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${DEPLOY_DIR:-$(dirname "$SCRIPT_DIR")}"
LOG="${DEPLOY_LOG:-/var/log/waretwin-deploy.log}"

mkdir -p "$(dirname "$LOG")"

while true; do
    REQ=$(nc -l -p "$PORT" 2>/dev/null) || { sleep 1; continue; }
    URL=$(echo "$REQ" | head -1 | awk '{print $2}')
    case "$URL" in
        *token="$TOKEN"*)
            echo "[$(date -Is)] deploy triggered" >> "$LOG"
            {
                echo "[$(date -Is)] === deploy start ==="
                cd "$REPO_DIR" && git pull --ff-only
                docker compose up -d --build
                sleep 5
                docker inspect -f '{{.Name}} {{.State.Status}}' waretwin-backend waretwin-frontend
                echo "[$(date -Is)] === deploy done ==="
            } >> "$LOG" 2>&1 &
            ;;
        *) : ;;
    esac
done
