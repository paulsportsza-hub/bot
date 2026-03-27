#!/usr/bin/env bash
# run_drift_monitors.sh — Run all drift monitors and alert EdgeOps private group on breaches.
# Monitors: null_rate, bookmaker_coverage, join_health, odds_freshness
# Alerts sent to: EdgeOps private group (chat_id: -1003877525865)

set -uo pipefail

cd /home/paulsportsza/bot

# Load environment variables from .env
if [ -f .env ]; then
    set -a
    # shellcheck source=.env
    source .env
    set +a
fi

# Alert-specific bot token (separate from main @mzansiedge_bot) — must be set in .env
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:?"TELEGRAM_BOT_TOKEN is required — set it in .env"}"
export TELEGRAM_ALERT_CHAT_ID="-1003877525865"
export DB_PATH="${ODDS_DB_PATH:-/home/paulsportsza/scrapers/odds.db}"

echo "[$(date -Iseconds)] drift-monitors: starting"

.venv/bin/python -c "
import sys, logging, os
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
log = logging.getLogger('drift_monitors')
sys.path.insert(0, '/home/paulsportsza/bot')
from scrapers.monitors import run_all_monitors
db = os.environ['DB_PATH']
log.info('running all monitors against %s', db)
results = run_all_monitors(db)
log.info('results: %s', results)
failures = [k for k, v in results.items() if not v]
if failures:
    log.warning('monitors with alerts sent: %s', failures)
else:
    log.info('all monitors OK')
"

RC=$?
echo "[$(date -Iseconds)] drift-monitors: done (exit $RC)"
exit $RC
