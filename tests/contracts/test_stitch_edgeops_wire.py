"""Contract tests for BUILD-STITCH-EDGEOPS-WIRE-01.

Verifies that:
1. _send_edgeops_payment_alert is defined in bot.py and is async
2. _STITCH_FAILURE_EVENT_TYPES covers all expected failure events
3. The webhook handler wires failure events to _send_edgeops_payment_alert
4. EdgeOps alert targets the correct chat ID (Standing Order #20)
5. _stitch_payment_summary in the daily digest includes failure count query
"""

from __future__ import annotations

import ast
import subprocess


class TestEdgeOpsAlertFunction:
    """AC-1: _send_edgeops_payment_alert function exists and is async."""

    def test_alert_function_defined(self):
        out = subprocess.run(
            ["grep", "-n", "async def _send_edgeops_payment_alert", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "_send_edgeops_payment_alert" in out.stdout, (
            "_send_edgeops_payment_alert async function must be defined in bot.py"
        )

    def test_alert_function_uses_edgeops_chat_id(self):
        out = subprocess.run(
            ["grep", "-n", "_EDGEOPS_CHAT_ID", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "_EDGEOPS_CHAT_ID" in out.stdout, (
            "_EDGEOPS_CHAT_ID must be referenced in bot.py for the EdgeOps alert"
        )

    def test_edgeops_chat_id_value_correct(self):
        """Standing Order #20: must always target -1003877525865."""
        out = subprocess.run(
            ["grep", "-n", "_EDGEOPS_CHAT_ID = -1003877525865", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "-1003877525865" in out.stdout, (
            "_EDGEOPS_CHAT_ID in bot.py must equal -1003877525865 (SO #20)"
        )

    def test_alert_function_logs_brief_id(self):
        out = subprocess.run(
            ["grep", "-n", "BUILD-STITCH-EDGEOPS-WIRE-01", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "BUILD-STITCH-EDGEOPS-WIRE-01" in out.stdout, (
            "The brief ID BUILD-STITCH-EDGEOPS-WIRE-01 must appear in bot.py log markers"
        )


class TestFailureEventTypes:
    """AC-2: _STITCH_FAILURE_EVENT_TYPES covers all failure event types."""

    def _get_failure_types(self) -> set[str]:
        out = subprocess.run(
            ["grep", "-A", "10", "_STITCH_FAILURE_EVENT_TYPES", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        return out.stdout

    def test_payment_failed_in_failure_set(self):
        assert "payment.failed" in self._get_failure_types()

    def test_payment_cancelled_in_failure_set(self):
        assert "payment.cancelled" in self._get_failure_types()

    def test_payment_expired_in_failure_set(self):
        assert "payment.expired" in self._get_failure_types()

    def test_subscription_cancelled_in_failure_set(self):
        assert "subscription.cancelled" in self._get_failure_types()

    def test_subscription_expired_in_failure_set(self):
        assert "subscription.expired" in self._get_failure_types()


class TestWebhookHandlerWiring:
    """AC-3: handle_stitch_webhook fires EdgeOps alert for failure events."""

    def test_failure_event_types_check_in_webhook_handler(self):
        """The webhook handler must check _STITCH_FAILURE_EVENT_TYPES."""
        out = subprocess.run(
            ["grep", "-n", "_STITCH_FAILURE_EVENT_TYPES", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        lines = out.stdout.strip().splitlines()
        # Should appear at definition AND in the webhook handler
        assert len(lines) >= 2, (
            "_STITCH_FAILURE_EVENT_TYPES must appear at definition and in the webhook handler"
        )

    def test_create_task_alert_call_present(self):
        """asyncio.create_task(_send_edgeops_payment_alert ...) must be in webhook handler."""
        out = subprocess.run(
            ["grep", "-n", "_send_edgeops_payment_alert", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "_send_edgeops_payment_alert" in out.stdout, (
            "_send_edgeops_payment_alert must be referenced in the webhook handler"
        )
        # Should appear at least twice: definition + call site
        lines = out.stdout.strip().splitlines()
        assert len(lines) >= 2, (
            "_send_edgeops_payment_alert must have at least a definition and a call site"
        )


class TestDailyDigestFailureStats:
    """AC-4: _stitch_payment_summary in the daily digest reports 24h failures."""

    def test_failure_count_query_present(self):
        out = subprocess.run(
            ["grep", "-n", "status IN.*failed.*cancelled.*expired", "scripts/edgeops_daily_digest.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "failed" in out.stdout, (
            "_stitch_payment_summary must query 24h failure count from payments table"
        )

    def test_24h_window_in_query(self):
        out = subprocess.run(
            ["grep", "-n", "24 hours", "scripts/edgeops_daily_digest.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "24 hours" in out.stdout, (
            "_stitch_payment_summary must use a 24-hour window for failure counts"
        )

    def test_brief_comment_removed(self):
        """Confirm the 'no EdgeOps wiring yet' TODO comment is gone."""
        out = subprocess.run(
            ["grep", "-n", "no EdgeOps wiring yet", "scripts/edgeops_daily_digest.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert out.stdout.strip() == "", (
            "The 'no EdgeOps wiring yet' placeholder comment must be removed"
        )

    def test_alert_function_imported_or_referenced(self):
        """The digest module docstring or comments must reference the wire."""
        out = subprocess.run(
            ["grep", "-n", "BUILD-STITCH-EDGEOPS-WIRE-01", "scripts/edgeops_daily_digest.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "BUILD-STITCH-EDGEOPS-WIRE-01" in out.stdout, (
            "BUILD-STITCH-EDGEOPS-WIRE-01 should be referenced in edgeops_daily_digest.py"
        )
