#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---core}"

# Core env vars (always required)
CORE_VARS=("ANTHROPIC_API_KEY" "TELEGRAM_BOT_TOKEN" "ODDS_API_KEY")

# E2E env vars (required for full gate)
E2E_VARS=("TELEGRAM_E2E_BOT_TOKEN" "TELEGRAM_E2E_TEST_CHAT_ID")

missing=0
for v in "${CORE_VARS[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    echo "MISSING core env: $v"
    missing=1
  fi
done

if [[ "$MODE" == "--full" ]]; then
  for v in "${E2E_VARS[@]}"; do
    if [[ -z "${!v:-}" ]]; then
      echo "MISSING E2E env: $v -> FAIL (not skip)"
      missing=1
    fi
  done
fi

if [[ $missing -ne 0 ]]; then
  echo "ENV GUARD FAILED"
  exit 1
fi
echo "ENV GUARD PASSED ($MODE)"
