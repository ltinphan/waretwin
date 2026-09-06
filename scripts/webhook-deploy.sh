#!/usr/bin/env bash
# WareTwin auto-deploy webhook - run on the host as a systemd service.
# GET /deploy?token=$DEPLOY_TOKEN -> git pull + docker compose up -d --build
# Netcat one-shot server: nothing to install beyond bash+nc.
set -euo pipefail

token_ok() { [[ "$1" == "$2" ]]; }   # exact literal compare (both sides quoted): no glob, no substring
get_path() {  # path of "GET /deploy?token=x HTTP/1.1" -> /deploy
    local p="${1#GET }"; p="${p%%\?*}"; p="${p% HTTP/*}"; printf '%s' "$p"
}
authorize() {  # <path> <got-token> <want-token>: only /deploy, alnum token, exact match
    [[ "$1" == "/deploy" && "$2" =~ ^[A-Za-z0-9_-]+$ ]] && token_ok "$2" "$3"
}
url_decode() {
    local s="${1//+/ }"
    printf '%b' "${s//%/\\x}"
}
parse_token() {
    local encoded
    encoded="$(printf '%s' "$1" | sed -n 's/.*[?&]token=\([^&]*\).*/\1/p')"
    [[ -n "$encoded" ]] || return 0
    url_decode "$encoded"
}

self_test() {
    [[ "$(parse_token '/deploy?token=abc')" == abc ]] || return 1
    [[ "$(parse_token '/deploy?x=1&token=abc&y=2')" == abc ]] || return 1
    [[ "$(parse_token '/deploy?token=abc&y=2')" == abc ]] || return 1
    [[ "$(parse_token '/deploy?token=a%26b')" == 'a&b' ]] || return 1
    [[ "$(parse_token '/deploy?token=a%20b')" == 'a b' ]] || return 1
    [[ "$(parse_token '/deploy?token=a%2Ac')" == 'a*c' ]] || return 1
    [[ "$(parse_token '/deploy?tokenx=abc')" == '' ]] || return 1
    [[ "$(parse_token '/deploy')" == '' ]] || return 1
    [[ "$(get_path 'GET /deploy?token=abc HTTP/1.1')" == /deploy ]] || return 1
    [[ "$(get_path 'GET /foo?token=abc HTTP/1.1')" == /foo ]] || return 1
    authorize /deploy abc abc || return 1
    authorize /foo abc abc && return 1      # only /deploy routes deploys
    authorize /deploy 'a*b' 'a*b' && return 1  # charset gate (tokens are alnum; rotate accordingly)
    authorize '' abc abc && return 1
    token_ok abc abc || return 1
    token_ok 'a*c' 'a*c' || return 1
    token_ok axxxc 'a*c' && return 1   # glob chars must not match
    token_ok abcd abc && return 1      # no substring match
    token_ok '' abc && return 1        # empty never matches
    return 0
}

if [[ "${1:-}" == "--self-test" ]]; then self_test; echo "self-test OK"; exit 0; fi

PORT="${DEPLOY_PORT:-8712}"
TOKEN="${DEPLOY_TOKEN:?set DEPLOY_TOKEN}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${DEPLOY_DIR:-$(dirname "$SCRIPT_DIR")}"
LOG="${DEPLOY_LOG:-/var/log/waretwin-deploy.log}"
LOCK="${DEPLOY_LOCK:-/run/waretwin-deploy.lock}"   # ponytail: root-only /run, not world-writable /tmp

mkdir -p "$(dirname "$LOG")"

respond() {  # respond <status> <fd> - minimal HTTP response to the client
    printf 'HTTP/1.1 %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' "$1" >&"$2" || true
}

while true; do
    coproc NC { nc -l -p "$PORT" 2>/dev/null; }
    NC_IN=${NC[0]} NC_OUT=${NC[1]} NC_PID_SAVE=$NC_PID   # scalars: bash clears NC[]/NC_PID when the coproc exits

    REQ_LINE=""
    IFS= read -r -t 10 REQ_LINE <&"$NC_IN" || sleep 1   # -t 10: silent client can't hang us; sleep: no tight loop if nc died
    URL="${REQ_LINE#GET }"; URL="${URL% HTTP/*}"
    GOT="$(parse_token "$URL")"

    if authorize "$(get_path "$REQ_LINE")" "$GOT" "$TOKEN"; then
        respond "202 Accepted" "$NC_OUT"
        echo "[$(date -Is)] deploy triggered" >> "$LOG"
        (
            flock -n 9 || { echo "[$(date -Is)] deploy already running, skipped"; exit 0; }
            echo "[$(date -Is)] === deploy start ==="
            cd "$REPO_DIR"
            git pull --ff-only
            docker compose up -d --build
            sleep 5
            docker inspect -f '{{.Name}} {{.State.Status}}' waretwin-backend waretwin-frontend
            echo "[$(date -Is)] === deploy done ==="
        ) 9>"$LOCK" >>"$LOG" 2>&1 &
    else
        respond "403 Forbidden" "$NC_OUT"
        echo "[$(date -Is)] rejected: $REQ_LINE" >> "$LOG"
    fi

    # Bounded cleanup every iteration (incl. read timeout): up to 2s for the client to close, then reap nc and its fds.
    for _ in {1..20}; do kill -0 "$NC_PID_SAVE" 2>/dev/null || break; sleep 0.1; done
    kill "$NC_PID_SAVE" 2>/dev/null || true
    wait "$NC_PID_SAVE" 2>/dev/null || true
    eval "exec ${NC_IN}<&- ${NC_OUT}>&-" 2>/dev/null || true
done
