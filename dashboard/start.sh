#!/usr/bin/env bash
# MzansiEdge Health Dashboard — start script
# Usage: bash dashboard/start.sh
# Runs on port 8501 in background, logs to /tmp/dashboard.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$BOT_DIR/.venv/bin/python"
LOG="/tmp/dashboard.log"
PIDFILE="/tmp/dashboard.pid"

# Load env
ENV_FILE="$BOT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$ENV_FILE"
  set +a
fi

# Kill existing dashboard process if running
if [[ -f "$PIDFILE" ]]; then
  OLD_PID=$(cat "$PIDFILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping existing dashboard (PID $OLD_PID)..."
    kill "$OLD_PID" || true
    sleep 1
  fi
  rm -f "$PIDFILE"
fi

# Verify Flask is installed
if ! "$VENV" -c "import flask" 2>/dev/null; then
  echo "Flask not found in venv — installing..."
  "$BOT_DIR/.venv/bin/pip" install flask --quiet
fi

echo "Starting MzansiEdge Health Dashboard on port ${DASHBOARD_PORT:-8501}..."
nohup "$VENV" "$SCRIPT_DIR/health_dashboard.py" >> "$LOG" 2>&1 &
DASHBOARD_PID=$!
echo "$DASHBOARD_PID" > "$PIDFILE"

sleep 1
if kill -0 "$DASHBOARD_PID" 2>/dev/null; then
  echo "✓ Dashboard started (PID $DASHBOARD_PID)"
  echo "  URL:  http://localhost:${DASHBOARD_PORT:-8501}/ops/health"
  echo "  Log:  $LOG"
  echo "  User: ${DASHBOARD_USER:-admin}"
else
  echo "✗ Dashboard failed to start — check $LOG"
  cat "$LOG" | tail -20
  exit 1
fi

# ── Auto-restart notes ────────────────────────────────────────────────────────
# To add to cron for auto-start on reboot:
#   @reboot cd /home/paulsportsza/bot && bash dashboard/start.sh
#
# Or create a systemd service:
#   sudo systemctl edit --force --full mzansiedge-dashboard.service
#   [Unit]
#   Description=MzansiEdge Health Dashboard
#   After=network.target
#
#   [Service]
#   User=paulsportsza
#   WorkingDirectory=/home/paulsportsza/bot
#   ExecStart=/home/paulsportsza/bot/.venv/bin/python dashboard/health_dashboard.py
#   EnvironmentFile=/home/paulsportsza/bot/.env
#   Restart=always
#   RestartSec=10
#
#   [Install]
#   WantedBy=multi-user.target
#
#   sudo systemctl enable mzansiedge-dashboard
#   sudo systemctl start mzansiedge-dashboard
