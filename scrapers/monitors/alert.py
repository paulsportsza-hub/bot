"""Shared Telegram alerting for drift monitors."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

ALERT_CHAT_ID = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "-1003789410835")
ALERT_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def send_alert(monitor_name: str, message: str, severity: str = "WARNING") -> bool:
    """Send a monitor alert to the Telegram admin channel."""
    emoji = "⚠️" if severity == "WARNING" else "🚨"
    text = f"{emoji} DRIFT ALERT [{severity}]\n\nMonitor: {monitor_name}\n{message}"

    if not ALERT_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN configured; alert not sent")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ALERT_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.error("Alert send failed: %s", exc)
        return False

    if not response.ok:
        logger.error("Alert send failed with status %s", response.status_code)
    return response.ok


def send_all_clear(monitor_name: str) -> bool:
    """Send an all-clear message for a monitor."""
    text = f"✅ DRIFT CLEAR\n\nMonitor: {monitor_name}\nAll checks passed."

    if not ALERT_BOT_TOKEN:
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage",
            json={"chat_id": ALERT_CHAT_ID, "text": text},
            timeout=10,
        )
    except requests.RequestException:
        return False

    return response.ok
