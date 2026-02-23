#!/bin/bash
# Setup script for MzansiEdge E2E testing with Playwright
# Run with: sudo bash scripts/setup_e2e.sh

set -e

echo "=== Installing Chromium system dependencies ==="
apt-get update -qq
apt-get install -y --no-install-recommends \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    libcups2 \
    libpango-1.0-0 \
    libcairo2 \
    libnspr4 \
    fonts-liberation \
    xdg-utils

echo ""
echo "=== System dependencies installed ==="
echo ""
echo "Next steps:"
echo "  1. Run: python save_telegram_session.py"
echo "     (requires a display — use X forwarding or run locally)"
echo "  2. Run: python tests/e2e_telegram.py"
echo ""
