#!/usr/bin/env bash
# deploy_bot_prod_rollback.sh — restore the previous bot-prod tree.
#
# Brief: FIX-BOT-RUNTIME-WORKTREE-ISOLATION-01 (AC-7).
#
# Pipeline:
#   1. Refuse if no bot-prod-prev exists
#   2. Move current bot-prod aside as bot-prod-failed (overwriting any prior failed)
#   3. Move bot-prod-prev back to bot-prod
#   4. systemctl restart, wait <=30s for "Startup Truth"
#
# After running, manually inspect bot-prod-failed and decide whether to
# rm -rf it or keep for debugging.

set -euo pipefail

PROD="${DEPLOY_PROD_TREE:-/home/paulsportsza/bot-prod}"
PREV="${PROD}-prev"
FAILED="${PROD}-failed"
STARTUP_TIMEOUT="${DEPLOY_STARTUP_TIMEOUT:-30}"

log() { printf '[rollback %s] %s\n' "$(date -Is)" "$*"; }
fail() { log "FAIL: $*" >&2; exit "${2:-1}"; }

[ -d "$PREV" ] || fail "no $PREV to roll back to" 2

log "moving current $PROD aside to $FAILED"
if [ -d "$FAILED" ]; then
    # Previous FAILED was chmod -R u-w'd — restore writability before rm,
    # otherwise rm partial-fails and trips set -e.
    chmod -R u+w "$FAILED" 2>/dev/null || true
    rm -rf "$FAILED"
fi
mv "$PROD" "$FAILED"

log "promoting $PREV -> $PROD"
mv "$PREV" "$PROD"

if [ "${DEPLOY_SKIP_RESTART:-0}" = "1" ]; then
    log "DEPLOY_SKIP_RESTART=1 — leaving service alone"
    log "rollback ok (no restart)"
    exit 0
fi

log "restarting mzansi-bot.service"
sudo /bin/systemctl restart mzansi-bot.service

DEADLINE=$(( $(date +%s) + STARTUP_TIMEOUT ))
WAIT_RC=1
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    if ! systemctl is-active --quiet mzansi-bot.service; then
        log "service is not active during startup wait"
        WAIT_RC=2
        break
    fi
    if sudo -n journalctl -u mzansi-bot --since "${STARTUP_TIMEOUT} sec ago" --no-pager 2>/dev/null \
            | grep -q 'Startup Truth'; then
        WAIT_RC=0
        break
    fi
    sleep 1
done

if [ "$WAIT_RC" -ne 0 ]; then
    log "post-rollback service did not emit 'Startup Truth' within ${STARTUP_TIMEOUT}s"
    log "MANUAL INTERVENTION REQUIRED — inspect journalctl -u mzansi-bot"
    exit 3
fi

log "rolled back to $(git -C "$PROD" rev-parse --short HEAD 2>/dev/null || echo '?')"
