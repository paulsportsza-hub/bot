#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# restart_bot_safe.sh — Minimal guarded restart wrapper
#
# Enforces:
#   1. live_status preflight passes
#   2. no active scraper writer window
#   3. no active pregen sweep
#   4. stale lock cleanup before restart
#   5. one consistent runtime owner (tmux), unless systemd owns prod
#
# Usage:
#   bash scripts/restart_bot_safe.sh
#   bash scripts/restart_bot_safe.sh --check
# ─────────────────────────────────────────────────────────────
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION_NAME="bot"
CHECK_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --check) CHECK_ONLY=1 ;;
        -h|--help)
            echo "Usage: bash scripts/restart_bot_safe.sh [--check]"
            exit 0
            ;;
    esac
done

ts() { date '+%Y-%m-%d %H:%M:%S'; }
note() { echo "$(ts) [INFO] $*"; }
hold() { echo "$(ts) [HOLD] $*" >&2; }

bot_pid() {
    ps -eo pid=,comm=,args= | awk '
        $2 ~ /^python/ && $0 ~ /(^|[[:space:]])([^[:space:]]*\/)?bot\.py([[:space:]]|$)/ {print $1; exit}
    '
}

cleanup_stale_lock() {
    local path="$1"
    [ -f "$path" ] || return 0
    local pid
    pid=$(cat "$path" 2>/dev/null || true)
    if [ -z "${pid:-}" ]; then
        rm -f "$path"
        note "Removed empty lock: $path"
        return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$path"
        note "Removed stale lock: $path (dead PID $pid)"
    fi
}

cd "$BOT_DIR"

if ! bash "$BOT_DIR/scripts/live_status.sh" --enforce; then
    hold "live_status preflight failed"
    exit 1
fi

cleanup_stale_lock /tmp/mzansiedge.pid
cleanup_stale_lock /tmp/mzansi_scraper.lock
cleanup_stale_lock /tmp/mzansiedge_qa.lock
cleanup_stale_lock /home/paulsportsza/logs/pregen.pid

SCRAPER_PID=$(cat /tmp/mzansi_scraper.lock 2>/dev/null || true)
if [ -n "${SCRAPER_PID:-}" ] && kill -0 "$SCRAPER_PID" 2>/dev/null; then
    hold "scraper writer window active (PID $SCRAPER_PID)"
    exit 1
fi

PREGEN_PID=$(cat /home/paulsportsza/logs/pregen.pid 2>/dev/null || true)
if [ -n "${PREGEN_PID:-}" ] && kill -0 "$PREGEN_PID" 2>/dev/null; then
    hold "manual/cron pregen sweep active (PID $PREGEN_PID)"
    exit 1
fi

if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet mzansiedge.service 2>/dev/null || systemctl is-enabled --quiet mzansiedge.service 2>/dev/null; then
        hold "systemd owns mzansiedge.service on this host; use sudo systemctl restart mzansiedge.service"
        exit 1
    fi
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
    note "restart preflight passed"
    exit 0
fi

if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux kill-session -t "$SESSION_NAME" || true
    sleep 1
fi

pkill -f "python.*bot\.py" 2>/dev/null || true
sleep 2

tmux new-session -d -s "$SESSION_NAME" \
    "cd $BOT_DIR && exec .venv/bin/python $BOT_DIR/bot.py >> /tmp/bot_latest.log 2>&1"

sleep 6
BOT_PID=$(bot_pid || true)
if [ -z "$BOT_PID" ]; then
    hold "restart completed but bot.py is not running"
    exit 1
fi

note "bot restarted under tmux session $SESSION_NAME — PID $BOT_PID"
tail -20 /tmp/bot_latest.log || true
