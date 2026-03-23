#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# bot_watchdog.sh — Live bot health monitor + auto-restart
#
# Checks every 60s:
#   1. Is bot.py running?
#   2. Is /tmp/mzansiedge.pid alive?
#   3. Is available RAM above critical floor?
#
# Auto-restarts the bot if it is down AND RAM is sufficient.
# Writes status to /tmp/bot_watchdog.log
#
# Run as: nohup bash scripts/bot_watchdog.sh &
# or add to crontab: * * * * * bash /home/paulsportsza/bot/scripts/bot_watchdog.sh >> /tmp/bot_watchdog.log 2>&1
# ─────────────────────────────────────────────────────────────
set -euo pipefail

BOT_DIR="/home/paulsportsza/bot"
LOG="/tmp/bot_watchdog.log"
MEM_FLOOR_MB=2000   # don't restart bot if RAM is critically low

ts() { date '+%Y-%m-%d %H:%M:%S'; }

bot_pids() {
    ps -eo pid=,comm=,args= | awk '
        $2 ~ /^python/ && $0 ~ /(^|[[:space:]])([^[:space:]]*\/)?bot\.py([[:space:]]|$)/ {print $1}
    '
}

# ── Check if bot is running ──────────────────────────────────
BOT_PIDS=$(bot_pids || true)
BOT_PID=$(printf '%s\n' "$BOT_PIDS" | sed '/^$/d' | head -1)
BOT_COUNT=$(printf '%s\n' "$BOT_PIDS" | sed '/^$/d' | wc -l | xargs)

if [ "$BOT_COUNT" -gt 1 ]; then
    echo "$(ts) [HOLD] Duplicate bot processes detected — PIDs: $(echo "$BOT_PIDS" | xargs)" >> "$LOG"
    exit 1
fi

if [ -n "$BOT_PID" ]; then
    echo "$(ts) [OK] Bot running — PID $BOT_PID" >> "$LOG"
    exit 0
fi

# ── Bot is DOWN ──────────────────────────────────────────────
echo "$(ts) [DOWN] Bot not running — checking RAM before restart" >> "$LOG"

AVAILABLE_MB=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)

if [ "$AVAILABLE_MB" -lt "$MEM_FLOOR_MB" ]; then
    echo "$(ts) [HOLD] RAM critically low (${AVAILABLE_MB}MB available, floor ${MEM_FLOOR_MB}MB) — NOT restarting" >> "$LOG"
    echo "$(ts) [HOLD] Kill unused Claude/Codex sessions then restart manually" >> "$LOG"
    exit 1
fi

# ── Respect systemd ownership ────────────────────────────────
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet mzansiedge.service 2>/dev/null || systemctl is-enabled --quiet mzansiedge.service 2>/dev/null; then
        echo "$(ts) [HOLD] systemd owns mzansiedge.service — watchdog will not perform manual restart" >> "$LOG"
        exit 1
    fi
fi

# ── Enforced preflight ───────────────────────────────────────
if ! bash "$BOT_DIR/scripts/live_status.sh" --enforce >> "$LOG" 2>&1; then
    echo "$(ts) [HOLD] live_status preflight failed — NOT restarting" >> "$LOG"
    exit 1
fi

# ── Clean stale lock/pid files ───────────────────────────────
STALE_PID=$(cat /tmp/mzansiedge.pid 2>/dev/null || echo "")
if [ -n "$STALE_PID" ] && ! kill -0 "$STALE_PID" 2>/dev/null; then
    echo "$(ts) [CLEAN] Removing stale /tmp/mzansiedge.pid (PID $STALE_PID dead)" >> "$LOG"
    rm -f /tmp/mzansiedge.pid
fi
STALE_QA=$(cat /tmp/mzansiedge_qa.lock 2>/dev/null || echo "")
if [ -n "$STALE_QA" ] && ! kill -0 "$STALE_QA" 2>/dev/null; then
    echo "$(ts) [CLEAN] Removing stale /tmp/mzansiedge_qa.lock (PID $STALE_QA dead)" >> "$LOG"
    rm -f /tmp/mzansiedge_qa.lock
fi
STALE_PREGEN=$(cat /home/paulsportsza/logs/pregen.pid 2>/dev/null || echo "")
if [ -n "$STALE_PREGEN" ] && ! kill -0 "$STALE_PREGEN" 2>/dev/null; then
    echo "$(ts) [CLEAN] Removing stale /home/paulsportsza/logs/pregen.pid (PID $STALE_PREGEN dead)" >> "$LOG"
    rm -f /home/paulsportsza/logs/pregen.pid
fi
SCRAPER_PID=$(cat /tmp/mzansi_scraper.lock 2>/dev/null || echo "")
if [ -n "$SCRAPER_PID" ] && ! kill -0 "$SCRAPER_PID" 2>/dev/null; then
    echo "$(ts) [CLEAN] Removing stale /tmp/mzansi_scraper.lock (PID $SCRAPER_PID dead)" >> "$LOG"
    rm -f /tmp/mzansi_scraper.lock
fi

# ── Verify required assets ───────────────────────────────────
for asset in "$BOT_DIR/data/prose_exemplars.json" "$BOT_DIR/data/mzansiedge.db" "$BOT_DIR/.env"; do
    if [ ! -f "$asset" ]; then
        echo "$(ts) [ABORT] Missing required asset: $asset — NOT restarting" >> "$LOG"
        exit 1
    fi
done

# ── Restart bot ──────────────────────────────────────────────
echo "$(ts) [RESTART] Restarting bot via guarded wrapper (RAM: ${AVAILABLE_MB}MB available)" >> "$LOG"
if bash "$BOT_DIR/scripts/restart_bot_safe.sh" >> "$LOG" 2>&1; then
    NEW_PID=$(bot_pids | head -1 || true)
    echo "$(ts) [RESTART] Bot started — PID ${NEW_PID:-unknown}" >> "$LOG"
else
    echo "$(ts) [HOLD] Guarded restart failed — inspect $LOG" >> "$LOG"
    exit 1
fi
