#!/usr/bin/env bash
# install-service.sh — Install and enable the MzansiEdge systemd service
set -euo pipefail

SERVICE_FILE="$(dirname "$(realpath "$0")")/../mzansiedge.service"
DEST="/etc/systemd/system/mzansiedge.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root (use sudo)." >&2
    exit 1
fi

if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: Service file not found at $SERVICE_FILE" >&2
    exit 1
fi

echo "Copying $SERVICE_FILE → $DEST"
cp "$SERVICE_FILE" "$DEST"

echo "Reloading systemd daemon…"
systemctl daemon-reload

echo "Enabling mzansiedge.service…"
systemctl enable mzansiedge.service

echo "Starting mzansiedge.service…"
systemctl start mzansiedge.service

echo ""
echo "Done. Check status with:"
echo "  systemctl status mzansiedge.service"
echo "  journalctl -u mzansiedge.service -f"
