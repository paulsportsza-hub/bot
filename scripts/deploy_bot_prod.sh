#!/usr/bin/env bash
# deploy_bot_prod.sh — atomic deploy of bot-prod runtime tree from origin/main.
#
# Brief: FIX-BOT-RUNTIME-WORKTREE-ISOLATION-01.
#
# Usage: deploy_bot_prod.sh <SHA>          # SHA must be reachable from origin/main
#
# Pipeline:
#   1. Verify SHA reachable from origin/main
#   2. Build staging tree from a fresh clone of the dev .git, checkout SHA
#   3. Replace writable subdirs (data/ reports/ logs/ bet_log/) with symlinks
#      to the shared volume; symlink .venv to dev tree
#   4. AST-parse bot.py from staging (cheap structural check)
#   5. Atomic-ish swap: mv bot-prod -> bot-prod-prev, mv staging -> bot-prod
#   6. chmod u-w on every NON-symlink under bot-prod (preserves writable shared volume)
#   7. systemctl restart mzansi-bot, wait <=30s for "Startup Truth" log
#   8. On regression: invoke deploy_bot_prod_rollback.sh and exit non-zero
#
# Layout post-cutover:
#   /home/paulsportsza/bot/                ← dev tree (writable, owned by paulsportsza)
#   /home/paulsportsza/bot-prod/           ← prod tree (read-only .py files)
#   /home/paulsportsza/bot-prod-prev/      ← previous prod tree (rollback target)
#   /home/paulsportsza/bot-data-shared/    ← shared writable volume (data/, reports/, logs/, bet_log/, pycache/)
#
# AC mapping:
#   AC-4 — ExecStart points at bot-prod/.venv/bin/python (set by systemd drop-in)
#   AC-5 — Read-only enforcement (chmod step 6)
#   AC-6 — End-to-end deploy verified by this script's own exit code
#   AC-7 — Rollback path implemented as deploy_bot_prod_rollback.sh
#
# Environment overrides:
#   DEPLOY_DEV_TREE=/home/paulsportsza/bot
#   DEPLOY_PROD_TREE=/home/paulsportsza/bot-prod
#   DEPLOY_SHARED=/home/paulsportsza/bot-data-shared
#   DEPLOY_STARTUP_TIMEOUT=30
#   DEPLOY_SKIP_RESTART=1   build the staging swap but skip the systemctl restart
#                           (used by the systemd-less first-deploy rehearsal)

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: $(basename "$0") <SHA>" >&2
    exit 64
fi

TARGET_SHA="$1"

DEV_TREE="${DEPLOY_DEV_TREE:-/home/paulsportsza/bot}"
PROD_TREE="${DEPLOY_PROD_TREE:-/home/paulsportsza/bot-prod}"
STAGING="${PROD_TREE}-staging"
PREV="${PROD_TREE}-prev"
SHARED="${DEPLOY_SHARED:-/home/paulsportsza/bot-data-shared}"
STARTUP_TIMEOUT="${DEPLOY_STARTUP_TIMEOUT:-30}"

log() { printf '[deploy %s] %s\n' "$(date -Is)" "$*"; }
fail() { log "FAIL: $*" >&2; exit "${2:-1}"; }

# === 1. Verify SHA reachable from origin/main =============================
log "verifying SHA $TARGET_SHA reachable from origin/main"
git -C "$DEV_TREE" fetch origin --quiet
git -C "$DEV_TREE" merge-base --is-ancestor "$TARGET_SHA" origin/main \
    || fail "SHA $TARGET_SHA is not reachable from origin/main" 2

# === 2. Build staging =====================================================
log "building staging at $STAGING"
rm -rf "$STAGING"
git clone --quiet "$DEV_TREE" "$STAGING"
git -C "$STAGING" checkout --quiet "$TARGET_SHA"

# === 3. Symlink farm ======================================================
log "provisioning shared volume at $SHARED"
mkdir -p "$SHARED/data" "$SHARED/reports" "$SHARED/logs" \
         "$SHARED/bet_log" "$SHARED/pycache"

# First-deploy seed: copy any existing dev-tree state into the shared volume
# only if the shared volume is empty. After cutover, dev tree state diverges
# from prod state, so re-running this script does NOT re-seed.
for sub in data reports logs; do
    if [ -d "$DEV_TREE/$sub" ] && [ -z "$(ls -A "$SHARED/$sub" 2>/dev/null || true)" ]; then
        log "first-deploy seed: $DEV_TREE/$sub -> $SHARED/$sub"
        # cp -a preserves metadata; ignore failures for symlinks pointing
        # outside dev tree.
        cp -a "$DEV_TREE/$sub/." "$SHARED/$sub/" 2>/dev/null || true
    fi
done

for sub in data reports logs bet_log; do
    rm -rf "$STAGING/$sub"
    ln -s "$SHARED/$sub" "$STAGING/$sub"
done

# .venv: symlink to the dev tree's .venv to avoid duplicating ~700 MB per deploy.
# Trade-off documented in ops/RUNTIME-ISOLATION.md.
rm -rf "$STAGING/.venv"
ln -s "$DEV_TREE/.venv" "$STAGING/.venv"

# === 4. AST sanity check ==================================================
log "AST-parsing staging bot.py"
"$DEV_TREE/.venv/bin/python" - <<PY || fail "bot.py in staging failed AST parse" 3
import ast, sys
with open("$STAGING/bot.py") as f:
    src = f.read()
ast.parse(src)
print(f"AST parse OK ({len(src)} chars)")
PY

# === 5. Atomic swap =======================================================
log "swapping prod tree"
if [ -d "$PROD_TREE" ]; then
    rm -rf "$PREV"
    mv "$PROD_TREE" "$PREV"
fi
mv "$STAGING" "$PROD_TREE"

# === 6. Read-only enforcement =============================================
# CRITICAL: chmod must not follow our symlinks into the shared volume.
# `find -not -type l` excludes symlinks themselves; `find` does not descend
# through symlinks unless -L is given, so the SHARED targets are never touched.
log "applying chmod u-w to non-symlink contents of $PROD_TREE"
find "$PROD_TREE" -not -type l -exec chmod u-w {} + 2>/dev/null || true

if [ "${DEPLOY_SKIP_RESTART:-0}" = "1" ]; then
    log "DEPLOY_SKIP_RESTART=1 — leaving service alone"
    log "deploy ok (no restart): $TARGET_SHA"
    exit 0
fi

# === 7. Restart + readiness wait ==========================================
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
    if journalctl -u mzansi-bot --since "${STARTUP_TIMEOUT} sec ago" --no-pager 2>/dev/null \
            | grep -q 'Startup Truth'; then
        WAIT_RC=0
        break
    fi
    sleep 1
done

if [ "$WAIT_RC" -ne 0 ]; then
    log "did not see 'Startup Truth' within ${STARTUP_TIMEOUT}s — rolling back"
    bash "$(dirname "$0")/deploy_bot_prod_rollback.sh" || true
    exit 4
fi

log "deploy ok: $TARGET_SHA (active sha: $(git -C "$PROD_TREE" rev-parse --short HEAD 2>/dev/null || echo '?'))"
