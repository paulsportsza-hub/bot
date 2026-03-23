#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# live_status.sh — Quick server health snapshot + lightweight preflight
#
# Run this FIRST before any debugging/restart session to understand
# what is running and whether the box is healthy.
#
# Usage:
#   bash scripts/live_status.sh
#   bash scripts/live_status.sh --enforce   # exit non-zero on unsafe live state
# ─────────────────────────────────────────────────────────────
set -u

ENFORCE=0
for arg in "$@"; do
    case "$arg" in
        --enforce) ENFORCE=1 ;;
        -h|--help)
            echo "Usage: bash scripts/live_status.sh [--enforce]"
            exit 0
            ;;
    esac
done

red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
cyan()   { printf '\033[0;36m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

UNSAFE=0
mark_unsafe() {
    UNSAFE=1
}

have_systemctl() {
    command -v systemctl >/dev/null 2>&1
}

has_tmux_session() {
    command -v tmux >/dev/null 2>&1 && tmux ls >/dev/null 2>&1
}

tmux_bot_owner() {
    pgrep -af "tmux .*bot\.py" >/dev/null 2>&1
}

bot_pids() {
    ps -eo pid=,comm=,args= | awk '
        $2 ~ /^python/ && $0 ~ /(^|[[:space:]])([^[:space:]]*\/)?bot\.py([[:space:]]|$)/ {print $1}
    '
}

bold "══════════════════════════════════════════"
bold " MzansiEdge — Live Status"
bold " $(date '+%Y-%m-%d %H:%M:%S %Z')"
bold "══════════════════════════════════════════"
echo ""

# ── RAM ───────────────────────────────────────────────────────
AVAILABLE_MB=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
USED_MB=$((TOTAL_MB - AVAILABLE_MB))
bold "MEMORY"
if [ "$AVAILABLE_MB" -lt 1000 ]; then
    red   "  Available: ${AVAILABLE_MB}MB / ${TOTAL_MB}MB  ← CRITICAL"
elif [ "$AVAILABLE_MB" -lt 2000 ]; then
    yellow "  Available: ${AVAILABLE_MB}MB / ${TOTAL_MB}MB  ← LOW"
else
    green "  Available: ${AVAILABLE_MB}MB / ${TOTAL_MB}MB"
fi
echo "  Load: $(cat /proc/loadavg | cut -d' ' -f1-3)"
echo ""

# ── Bot ──────────────────────────────────────────────────────
bold "BOT"
BOT_PIDS=$(bot_pids || true)
BOT_COUNT=$(printf '%s\n' "$BOT_PIDS" | sed '/^$/d' | wc -l | xargs)
BOT_PID=$(printf '%s\n' "$BOT_PIDS" | sed '/^$/d' | head -1)

SYSTEMD_ACTIVE=0
SYSTEMD_ENABLED=0
if have_systemctl && systemctl is-active --quiet mzansiedge.service 2>/dev/null; then
    SYSTEMD_ACTIVE=1
fi
if have_systemctl && systemctl is-enabled --quiet mzansiedge.service 2>/dev/null; then
    SYSTEMD_ENABLED=1
fi

TMUX_OWNER=0
if has_tmux_session && tmux_bot_owner; then
    TMUX_OWNER=1
fi

OWNER_SURFACES=0
OWNER_LABELS=()
if [ "$SYSTEMD_ACTIVE" -eq 1 ] || [ "$SYSTEMD_ENABLED" -eq 1 ]; then
    OWNER_SURFACES=$((OWNER_SURFACES + 1))
    OWNER_LABELS+=("systemd")
fi
if [ "$TMUX_OWNER" -eq 1 ]; then
    OWNER_SURFACES=$((OWNER_SURFACES + 1))
    OWNER_LABELS+=("tmux")
fi
if [ "$BOT_COUNT" -gt 0 ] && [ "$SYSTEMD_ACTIVE" -eq 0 ] && [ "$TMUX_OWNER" -eq 0 ]; then
    OWNER_SURFACES=$((OWNER_SURFACES + 1))
    OWNER_LABELS+=("manual")
fi

if [ "$BOT_COUNT" -gt 1 ]; then
    red "  ✗ Duplicate bot processes detected — count: $BOT_COUNT | PIDs: $(echo "$BOT_PIDS" | xargs)"
    mark_unsafe
elif [ -n "$BOT_PID" ]; then
    BOT_START=$(ps -p "$BOT_PID" -o lstart= 2>/dev/null)
    BOT_MEM=$(ps -p "$BOT_PID" -o rss= 2>/dev/null | awk '{print int($1/1024)}')
    green "  ✓ Running — PID $BOT_PID | started: $BOT_START | RSS: ${BOT_MEM}MB"

    BOT_MTIME=$(stat -c %Y /home/paulsportsza/bot/bot.py 2>/dev/null || echo 0)
    BOT_START_EPOCH=$(date -d "$BOT_START" +%s 2>/dev/null || echo 0)
    if [ "$BOT_MTIME" -gt "$BOT_START_EPOCH" ] 2>/dev/null; then
        yellow "  ⚠ bot.py modified AFTER process started — bot is running stale code"
        mark_unsafe
    fi
else
    red "  ✗ NOT RUNNING"
    STALE_PID=$(cat /tmp/mzansiedge.pid 2>/dev/null || echo "")
    [ -n "$STALE_PID" ] && yellow "  Stale PID file: /tmp/mzansiedge.pid ($STALE_PID)"
fi

if [ "$OWNER_SURFACES" -gt 1 ]; then
    red "  ✗ Mixed runtime owners detected — ${OWNER_LABELS[*]}"
    mark_unsafe
elif [ "${#OWNER_LABELS[@]}" -gt 0 ]; then
    echo "  Owner: ${OWNER_LABELS[0]}"
else
    echo "  Owner: none"
fi
echo ""

# ── Scraper ──────────────────────────────────────────────────
bold "SCRAPER CRON"
SCRAPER_PID=$(cat /tmp/mzansi_scraper.lock 2>/dev/null || echo "")
if [ -n "$SCRAPER_PID" ] && kill -0 "$SCRAPER_PID" 2>/dev/null; then
    yellow "  ⚡ Lock active — PID $SCRAPER_PID (scraper writing to odds.db)"
else
    green "  ✓ Idle (no active scraper lock)"
    [ -f /tmp/mzansi_scraper.lock ] && yellow "  Stale lock file — removing" && rm -f /tmp/mzansi_scraper.lock
fi
echo ""

# ── Pregen ───────────────────────────────────────────────────
bold "PREGEN"
PREGEN_PID=$(pgrep -f "pregenerate_narratives" 2>/dev/null | head -1)
PREGEN_LOCK=$(cat /home/paulsportsza/logs/pregen.pid 2>/dev/null || echo "")
if [ -n "$PREGEN_PID" ]; then
    yellow "  ⚡ Running — PID $PREGEN_PID"
elif [ -n "$PREGEN_LOCK" ] && kill -0 "$PREGEN_LOCK" 2>/dev/null; then
    yellow "  ⚡ Running via PID lock — PID $PREGEN_LOCK"
else
    green "  ✓ Idle"
fi
echo ""

# ── Claude/Codex instances ───────────────────────────────────
bold "AGENT PROCESSES"
CLAUDE_COUNT=$(pgrep -c -f "claude" 2>/dev/null || echo 0)
CODEX_COUNT=$(pgrep -c -f "codex" 2>/dev/null || echo 0)
TOTAL_AGENTS=$((CLAUDE_COUNT + CODEX_COUNT))
CLAUDE_MEM=$(ps aux | grep claude | grep -v grep | awk '{sum += $6} END {print int(sum/1024)}')
CODEX_MEM=$(ps aux | grep codex | grep -v grep | awk '{sum += $6} END {print int(sum/1024)}')
if [ "$CLAUDE_COUNT" -gt 5 ]; then
    red   "  Claude instances: $CLAUDE_COUNT (RSS: ${CLAUDE_MEM}MB)  ← HIGH — risk of OOM"
elif [ "$CLAUDE_COUNT" -gt 3 ]; then
    yellow "  Claude instances: $CLAUDE_COUNT (RSS: ${CLAUDE_MEM}MB)  ← elevated"
else
    green "  Claude instances: $CLAUDE_COUNT (RSS: ${CLAUDE_MEM}MB)"
fi
[ "$CODEX_COUNT" -gt 0 ] && echo "  Codex instances: $CODEX_COUNT (RSS: ${CODEX_MEM}MB)"
if [ "$TOTAL_AGENTS" -gt 3 ]; then
    red "  ✗ Total agent processes: $TOTAL_AGENTS  ← exceeds live-safe max 3"
    mark_unsafe
else
    green "  ✓ Total agent processes: $TOTAL_AGENTS / 3 max"
fi
echo ""

# ── QA lock ──────────────────────────────────────────────────
bold "QA LOCK"
QA_PID=$(cat /tmp/mzansiedge_qa.lock 2>/dev/null || echo "")
if [ -n "$QA_PID" ] && kill -0 "$QA_PID" 2>/dev/null; then
    yellow "  ⚡ QA run in progress — PID $QA_PID"
elif [ -f /tmp/mzansiedge_qa.lock ]; then
    yellow "  Stale QA lock (PID $QA_PID dead) — safe to remove: rm /tmp/mzansiedge_qa.lock"
else
    green "  ✓ No active QA run"
fi
echo ""

bold "══════════════════════════════════════════"
if [ "$ENFORCE" -eq 1 ]; then
    if [ "$UNSAFE" -ne 0 ]; then
        red "Preflight: UNSAFE"
        exit 1
    fi
    green "Preflight: SAFE"
fi
