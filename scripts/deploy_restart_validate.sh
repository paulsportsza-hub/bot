#!/usr/bin/env bash
set -euo pipefail

TMUX_SESSION="bot"
BOT_DIR="/home/paulsportsza/bot"
LOG_DIR="/var/log/mzansiedge"
LEDGER="$LOG_DIR/deploy_ledger.log"
BOT_LOG="/tmp/bot_latest.log"

# Ensure log directory exists
sudo mkdir -p "$LOG_DIR"
sudo chown paulsportsza:paulsportsza "$LOG_DIR"

echo "========================================"
echo "  DEPLOY PIPELINE — $(date -Is)"
echo "========================================"

# Step 1: Record old state
echo ""
echo "=== STEP 1: Record old state ==="
old_pid=$(pgrep -f 'python bot.py' || echo "none")
echo "Old PID: $old_pid"

# Step 2: Pull latest code
echo ""
echo "=== STEP 2: Pull latest code ==="
cd "$BOT_DIR" && git pull origin main
new_sha=$(git rev-parse HEAD)
echo "New SHA: $new_sha"

# Step 3: Kill old bot process
echo ""
echo "=== STEP 3: Stop old bot ==="
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  tmux kill-session -t "$TMUX_SESSION"
  echo "Killed tmux session: $TMUX_SESSION"
  sleep 2
else
  echo "No existing tmux session found"
fi

# Step 4: Start new bot
echo ""
echo "=== STEP 4: Start new bot ==="
tmux new-session -d -s "$TMUX_SESSION" "cd $BOT_DIR && exec .venv/bin/python bot.py >> $BOT_LOG 2>&1"
sleep 5

# Step 5: Verify new PID
echo ""
echo "=== STEP 5: Verify new process ==="
new_pid=$(pgrep -f 'python bot.py' || echo "none")
if [[ "$new_pid" == "none" || "$new_pid" == "$old_pid" ]]; then
  echo "DEPLOY FAILED — new_pid=$new_pid old_pid=$old_pid"
  echo "$(date -Is) FAILED old=$old_pid new=$new_pid sha=$new_sha" | tee -a "$LEDGER"
  exit 1
fi
echo "New PID: $new_pid (confirmed different from old)"

# Step 6: Post-deploy validation
echo ""
echo "=== STEP 6: Post-deploy validation ==="
cd "$BOT_DIR" && .venv/bin/python -m tests.post_deploy_validate

# Step 7: Write to immutable deploy ledger
echo ""
echo "=== STEP 7: Write ledger entry ==="
entry="$(date -Is) PASS old=$old_pid new=$new_pid sha=$new_sha"
echo "$entry" | tee -a "$LEDGER"

# Step 8: Post deploy entry to Notion Release Ledger (non-blocking)
echo ""
echo "=== STEP 8: Notion Release Ledger ==="
WAVE_ID="${WAVE_ID:-}"
$BOT_DIR/.venv/bin/python "$BOT_DIR/scripts/notify_notion_deploy.py" "PASS" "$WAVE_ID" || echo "WARN: Notion ledger write failed (non-blocking)"

echo ""
echo "========================================"
echo "  DEPLOY SUCCEEDED"
echo "========================================"
