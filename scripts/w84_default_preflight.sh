#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# w84_default_preflight.sh — Combined live-safe + W84-default check
#
# Usage:
#   bash scripts/w84_default_preflight.sh
#   bash scripts/w84_default_preflight.sh --hours 12 --min-recent 5
# ─────────────────────────────────────────────────────────────
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOURS=12
MIN_RECENT=5

while [ $# -gt 0 ]; do
    case "$1" in
        --hours)
            HOURS="$2"
            shift 2
            ;;
        --min-recent)
            MIN_RECENT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: bash scripts/w84_default_preflight.sh [--hours N] [--min-recent N]"
            exit 0
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

bash "$BOT_DIR/scripts/live_status.sh" --enforce
echo ""
bash "$BOT_DIR/scripts/w84_source_status.sh" --hours "$HOURS" --min-recent "$MIN_RECENT" --enforce
