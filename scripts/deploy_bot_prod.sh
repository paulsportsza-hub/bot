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

# Returns the highest numeric prefix across migrations/*.py files in a tree, or 0.
_schema_version_of() {
    local tree="$1" migdir highest=0 num f
    migdir="$tree/migrations"
    [ -d "$migdir" ] || { echo 0; return; }
    for f in "$migdir"/[0-9]*.py; do
        [ -f "$f" ] || continue
        num=$(basename "$f" | grep -oE '^[0-9]+' || true)
        num=$(printf '%s' "$num" | sed 's/^0*//')
        [ -z "$num" ] && continue
        [ "$num" -gt "$highest" ] 2>/dev/null && highest=$num
    done
    echo "$highest"
}

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

# bot.py opens "bot.log" relative to CWD (= bot-prod, read-only after step 6).
# Symlink it to the shared logs volume so RotatingFileHandler writes succeed.
# Pre-create the file so the rotation lock-test in RotatingFileHandler.__init__
# does not fail on first deploy.
touch "$SHARED/logs/bot.log"
rm -f "$STAGING/bot.log"
ln -s "$SHARED/logs/bot.log" "$STAGING/bot.log"

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
    if [ -d "$PREV" ]; then
        # Previous PREV was chmod -R u-w'd — restore writability before rm,
        # otherwise rm leaves a partial tree behind and trips set -e.
        chmod -R u+w "$PREV" 2>/dev/null || true
        rm -rf "$PREV"
    fi
    mv "$PROD_TREE" "$PREV"
fi
mv "$STAGING" "$PROD_TREE"

# === 6. Read-only enforcement =============================================
# CRITICAL: chmod must not follow our symlinks into the shared volume.
# `find -not -type l` excludes symlinks themselves; `find` does not descend
# through symlinks unless -L is given, so the SHARED targets are never touched.
log "applying chmod u-w to non-symlink contents of $PROD_TREE"
find "$PROD_TREE" -not -type l -exec chmod u-w {} + 2>/dev/null || true

# Pre-compute schema_version; recorded only after confirmed startup below
# (or immediately when DEPLOY_SKIP_RESTART=1 skips the readiness gate).
SCHEMA_VERSION=$(_schema_version_of "$PROD_TREE")

if [ "${DEPLOY_SKIP_RESTART:-0}" = "1" ]; then
    printf '%s\n' "$SCHEMA_VERSION" > "$SHARED/schema_version"
    log "schema_version ${SCHEMA_VERSION} recorded to $SHARED/schema_version"
    log "DEPLOY_SKIP_RESTART=1 — leaving service alone"
    log "deploy ok (no restart): $TARGET_SHA"
    exit 0
fi

# === 7. Restart + readiness wait ==========================================
log "restarting mzansi-bot.service"
# Anchor the readiness scan to a journal cursor captured *before* the
# restart. Cursor-based filtering is independent of seconds-resolution
# timestamps, so a Startup Truth emitted in the same wall-clock second
# as RESTART_TS (Codex round-2 P2) cannot falsely satisfy readiness.
PRE_CURSOR=$(sudo -n journalctl -u mzansi-bot --no-pager --show-cursor -n 1 2>/dev/null \
              | awk '/^-- cursor:/{print $3}')
sudo /bin/systemctl restart mzansi-bot.service

DEADLINE=$(( $(date +%s) + STARTUP_TIMEOUT ))
WAIT_RC=1
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    # Only break-on-failure for terminal failed state. Transient
    # deactivating / inactive / activating during the systemd restart
    # cycle is normal and must not trigger a false rollback.
    # `is-active` prints `failed` and exits 3 for failed units; the
    # previous `... || echo unknown` form was concatenating both
    # outputs (`failed\nunknown`), so the equality test never fired.
    # Keep stderr discarded but capture stdout-only and only fall back
    # to "unknown" when stdout is empty (pgrep-style).
    state=$(systemctl is-active mzansi-bot.service 2>/dev/null)
    state="${state:-unknown}"
    if [ "$state" = "failed" ]; then
        log "service entered failed state during startup wait"
        WAIT_RC=2
        break
    fi
    # journalctl needs sudo: paulsportsza is not in systemd-journal group, so a
    # non-sudo invocation only sees user-session logs and misses the system
    # service entirely. --since pinned to RESTART_TS so a stale Startup Truth
    # from the previous run cannot match (Codex P1).
    # `grep -c` (not -q) so the pipeline consumes all of journalctl's
    # output. Combined with `set -o pipefail`, an early-exit grep would
    # send SIGPIPE to journalctl, fail the pipeline, and falsely keep
    # waiting even after a real Startup Truth match. Anchored at
    # PRE_CURSOR so we only match events emitted *after* this restart.
    if [ -n "$PRE_CURSOR" ]; then
        journal_st=$(sudo -n journalctl -u mzansi-bot --no-pager --after-cursor="$PRE_CURSOR" 2>/dev/null | grep -c 'Startup Truth' || true)
    else
        # First-ever boot has no prior cursor; fall back to a generous
        # since window. Strictly less safe but only hit on machines with
        # an empty journal.
        journal_st=$(sudo -n journalctl -u mzansi-bot --since "@$(( $(date +%s) - STARTUP_TIMEOUT ))" --no-pager 2>/dev/null | grep -c 'Startup Truth' || true)
    fi
    log "wait state=$state startup_truth=$journal_st"
    if [ "$journal_st" -gt 0 ]; then
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

# Record schema_version only after startup is confirmed — prevents the shared
# file from being advanced for a deploy that ultimately failed and was
# auto-rolled-back (Codex sub-agent P1).
printf '%s\n' "$SCHEMA_VERSION" > "$SHARED/schema_version"
log "schema_version ${SCHEMA_VERSION} recorded to $SHARED/schema_version"

log "deploy ok: $TARGET_SHA (active sha: $(git -C "$PROD_TREE" rev-parse --short HEAD 2>/dev/null || echo '?'))"
