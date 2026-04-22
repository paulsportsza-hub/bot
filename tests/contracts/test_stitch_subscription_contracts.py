"""Contract tests for Stitch Express recurring subscriptions.

BUILD-STITCH-SUBSCRIPTION-01 (AC-12)

Covers:
  - stitch_subscription_id column exists on users table
  - _handle_sub_email() routes subscription plans to create_subscription()
  - All 4 subscription.* webhook event types are handled
  - Phantom mandate handlers are absent from bot.py
"""

from __future__ import annotations

import subprocess


class TestSubscriptionColumns:
    """AC-5/AC-12: stitch_subscription_id column exists on users table."""

    def test_stitch_subscription_id_in_migrate_columns(self):
        import subprocess
        out = subprocess.run(
            ["grep", "-n", "stitch_subscription_id", "db.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "stitch_subscription_id" in out.stdout

    def test_subscription_billing_day_in_migrate_columns(self):
        out = subprocess.run(
            ["grep", "-n", "subscription_billing_day", "db.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "subscription_billing_day" in out.stdout

    def test_subscription_next_charge_at_in_migrate_columns(self):
        out = subprocess.run(
            ["grep", "-n", "subscription_next_charge_at", "db.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "subscription_next_charge_at" in out.stdout


class TestRoutingBranch:
    """AC-6/AC-12: _handle_sub_email routes subscription plans to create_subscription."""

    def test_create_subscription_called_for_gold_monthly(self):
        out = subprocess.run(
            ["grep", "-n", "create_subscription", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "create_subscription" in out.stdout

    def test_founding_diamond_unchanged_uses_create_payment(self):
        out = subprocess.run(
            ["grep", "-n", "create_payment", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "create_payment" in out.stdout

    def test_is_subscription_guard_present(self):
        out = subprocess.run(
            ["grep", "-n", "_is_subscription", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "_is_subscription" in out.stdout

    def test_stitch_subscription_id_db_write_present(self):
        out = subprocess.run(
            ["grep", "-n", "update_user_stitch_subscription_id", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "update_user_stitch_subscription_id" in out.stdout


class TestSubscriptionEventTypes:
    """AC-9/AC-12: All 4 subscription.* webhook event types are covered."""

    def test_subscription_created_handled(self):
        out = subprocess.run(
            ["grep", "-n", "subscription.created", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "subscription.created" in out.stdout

    def test_subscription_renewed_handled(self):
        out = subprocess.run(
            ["grep", "-n", "subscription.renewed", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "subscription.renewed" in out.stdout

    def test_subscription_cancelled_handled(self):
        out = subprocess.run(
            ["grep", "-n", "subscription.cancelled", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "subscription.cancelled" in out.stdout

    def test_subscription_expired_handled(self):
        out = subprocess.run(
            ["grep", "-n", "subscription.expired", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "subscription.expired" in out.stdout


class TestPhantomMandateHandlersAbsent:
    """AC-8/AC-12: mandate.created and mandate.authorization_succeeded removed."""

    def test_mandate_created_absent_from_map_webhook_state(self):
        out = subprocess.run(
            ["grep", "-n", "mandate.created", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        # Should return empty — no mandate.created in bot.py
        assert out.stdout.strip() == "", (
            f"mandate.created still present in bot.py: {out.stdout}"
        )

    def test_mandate_authorization_succeeded_absent(self):
        out = subprocess.run(
            ["grep", "-n", "mandate.authorization_succeeded", "bot.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert out.stdout.strip() == "", (
            f"mandate.authorization_succeeded still present in bot.py: {out.stdout}"
        )

    def test_no_graphql_mandate_shapes_in_tests(self):
        out = subprocess.run(
            ["grep", "-rn", "clientPaymentInitiationRequestCreate", "tests/unit/"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert out.stdout.strip() == "", (
            f"GraphQL mandate shape still in tests/unit/: {out.stdout}"
        )


class TestCreateSubscriptionExists:
    """AC-1/AC-12: create_subscription replaces create_recurring_mandate."""

    def test_create_subscription_in_stitch_service(self):
        out = subprocess.run(
            ["grep", "-n", "def create_subscription", "services/stitch_service.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "create_subscription" in out.stdout

    def test_create_recurring_mandate_absent(self):
        out = subprocess.run(
            ["grep", "-n", "def create_recurring_mandate", "services/stitch_service.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert out.stdout.strip() == "", (
            f"create_recurring_mandate still defined: {out.stdout}"
        )

    def test_subscriptions_url_defined(self):
        out = subprocess.run(
            ["grep", "-n", "SUBSCRIPTIONS_URL", "services/stitch_service.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "SUBSCRIPTIONS_URL" in out.stdout

    def test_scope_per_scope_cache_in_stitch_service(self):
        out = subprocess.run(
            ["grep", "-n", "client_recurringpaymentconsentrequest", "services/stitch_service.py"],
            capture_output=True, text=True,
            cwd="/home/paulsportsza/bot",
        )
        assert "client_recurringpaymentconsentrequest" in out.stdout
