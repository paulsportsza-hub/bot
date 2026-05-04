"""
Contract: FIX-ARBITER-EDGEOPS-SENDER-UNIFY-01

Verifies:
  1. arbiter_qa.py ops-alert uses Bot API (urllib.request), not client.send_message
  2. Telethon client.send_message(bot_entity) calls (probes) are still present
  3. health_alerter.py prefixes all alert text with [health]
"""
from __future__ import annotations

import re
from pathlib import Path

ARBITER = Path("/home/paulsportsza/arbiter_qa.py").read_text()
HEALTH  = Path("/home/paulsportsza/scripts/health_alerter.py").read_text()


def test_ops_alert_uses_bot_api_not_telethon():
    """The EdgeOps ops-alert block must call urllib.request, not client.send_message(EDGEOPS_CHAT_ID, ...)."""
    # Must contain urllib.request (Bot API path)
    assert "urllib.request.urlopen" in ARBITER, (
        "arbiter_qa.py: expected urllib.request.urlopen call for ops-alert"
    )
    # The old Telethon send to EDGEOPS_CHAT_ID must be gone
    assert not re.search(
        r"client\.send_message\s*\(\s*EDGEOPS_CHAT_ID",
        ARBITER,
    ), "arbiter_qa.py: client.send_message(EDGEOPS_CHAT_ID, ...) must be removed"


def test_telethon_probe_calls_remain():
    """Telethon client.send_message(entity, ...) calls for probes A/B/C/D must stay."""
    probe_calls = re.findall(
        r"await\s+client\.send_message\s*\(\s*entity\b",
        ARBITER,
    )
    assert len(probe_calls) >= 3, (
        f"arbiter_qa.py: expected ≥3 probe send_message(entity, ...) calls, found {len(probe_calls)}"
    )


def test_health_alerter_prefixes_health_tag():
    """_send_telegram must prepend [health] to every alert message."""
    # Find the _send_telegram function body
    match = re.search(
        r"def _send_telegram\(text.*?(?=\ndef |\Z)",
        HEALTH,
        re.DOTALL,
    )
    assert match, "health_alerter.py: _send_telegram function not found"
    body = match.group(0)
    assert "[health]" in body, (
        "health_alerter.py: _send_telegram must prefix text with [health]"
    )
