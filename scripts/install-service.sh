#!/usr/bin/env bash
# install-service.sh — Symlink and enable the MzansiEdge systemd service
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

echo "Symlinking $SERVICE_FILE → $DEST"
ln -sf "$SERVICE_FILE" "$DEST"

echo "Reloading systemd daemon…"
systemctl daemon-reload

echo "Enabling mzansiedge.service…"
systemctl enable mzansiedge.service

echo ""
echo "Done. Service is enabled but NOT started."
echo "When ready, start it with:"
echo "  sudo systemctl start mzansiedge.service"
echo ""
echo "Monitor with:"
echo "  systemctl status mzansiedge.service"
echo "  journalctl -u mzansiedge.service -f"
