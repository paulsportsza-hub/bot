#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# qa_guard_hook.sh — Claude PreToolUse hook for Bash commands
#
# Blocks bare pytest/python -m pytest invocations that bypass
# the safe QA wrapper (scripts/qa_safe.sh).
#
# Also blocks commands when the server is under memory pressure
# (available RAM < MEM_FLOOR_MB) to prevent OOM incidents.
# Root cause: 9 concurrent Claude instances caused OOM on
# 2026-03-22, killing the bot's tmux session via dbus/systemd.
#
# Reads the tool input JSON from stdin (Claude hook protocol).
# Exits 0 to allow, exits 2 with BLOCK message to reject.
# ─────────────────────────────────────────────────────────────

# ── Memory floor: block heavy ops when RAM is critically low ──
MEM_FLOOR_MB=1500

# Read the hook input JSON from stdin
INPUT=$(cat)

# Extract the command field from the tool input
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('command', ''))
except:
    print('')
" 2>/dev/null)

# ── Memory pressure gate ─────────────────────────────────────
# Block heavy operations when available RAM is critically low.
AVAILABLE_MB=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 9999)
if [ "$AVAILABLE_MB" -lt "$MEM_FLOOR_MB" ]; then
    if echo "$COMMAND" | grep -qE '(pytest|python\s+-m\s+pytest|pregenerate_narratives|opus_audit|shadow_review)'; then
        echo "BLOCKED: Server memory pressure — ${AVAILABLE_MB}MB available (floor: ${MEM_FLOOR_MB}MB)."
        echo ""
        echo "Check RAM consumers before running QA:"
        echo "  ps aux --sort=-%rss | head -12"
        echo "  free -h"
        echo ""
        echo "Close unused Claude/Codex sessions, then retry."
        exit 2
    fi
fi

# Allow if not a pytest command
if ! echo "$COMMAND" | grep -qE '(^|\s)(pytest|python\s+-m\s+pytest)(\s|$)'; then
    exit 0
fi

# Allow if it's already using qa_safe.sh
if echo "$COMMAND" | grep -q 'qa_safe'; then
    exit 0
fi

# Allow if it's a pip install or --version/--help check
if echo "$COMMAND" | grep -qE '(pip\s+install|--version|--help)'; then
    exit 0
fi

# Allow if it's a single targeted test file (not a full suite run)
# Pattern: pytest tests/some_file.py or pytest tests/dir/some_file.py
if echo "$COMMAND" | grep -qP 'pytest\s+tests/\S+\.py(\s|$)'; then
    exit 0
fi

# Block unbounded pytest runs
echo "BLOCKED: Use scripts/qa_safe.sh instead of bare pytest."
echo ""
echo "Examples:"
echo "  bash scripts/qa_safe.sh                  # full suite (bounded)"
echo "  bash scripts/qa_safe.sh contracts        # layer 1 only"
echo "  bash scripts/qa_safe.sh gate             # wave completion gate"
echo "  bash scripts/qa_safe.sh tests/foo.py     # specific file"
echo ""
echo "The safe wrapper enforces: flock serialisation, 5min timeout,"
echo "nice +15 priority, and per-test 30s timeout."
exit 2
