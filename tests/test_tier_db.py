"""Unit tests for tier-related DB helpers in db.py."""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio

import db


class TestGetUserTier:
    """Test get_user_tier() returns correct tier or default."""

    @pytest.mark.asyncio
    async def test_default_bronze(self, test_db):
        """New user defaults to bronze tier."""
        user = await db.upsert_user(1001, "test", "Test")
        tier = await db.get_user_tier(1001)
        assert tier == "bronze"

    @pytest.mark.asyncio
    async def test_returns_set_tier(self, test_db):
        """Returns tier after set_user_tier."""
        await db.upsert_user(1002, "test2", "Test2")
        await db.set_user_tier(1002, "gold")
        tier = await db.get_user_tier(1002)
        assert tier == "gold"

    @pytest.mark.asyncio
    async def test_nonexistent_user_returns_bronze(self, test_db):
        """Non-existent user returns bronze."""
        tier = await db.get_user_tier(99999)
        assert tier == "bronze"


class TestSetUserTier:
    """Test set_user_tier() updates tier and expiry."""

    @pytest.mark.asyncio
    async def test_sets_tier(self, test_db):
        """Sets user tier to diamond."""
        await db.upsert_user(2001, "diamonduser", "Diamond")
        await db.set_user_tier(2001, "diamond")

        user = await db.get_user(2001)
        assert user.user_tier == "diamond"

    @pytest.mark.asyncio
    async def test_sets_expiry(self, test_db):
        """Sets tier_expires_at when provided."""
        await db.upsert_user(2002, "golduser", "Gold")
        expiry = dt.datetime(2027, 3, 28, tzinfo=dt.timezone.utc)
        await db.set_user_tier(2002, "gold", expires_at=expiry)

        user = await db.get_user(2002)
        assert user.user_tier == "gold"
        assert user.tier_expires_at is not None

    @pytest.mark.asyncio
    async def test_paid_tier_activates_subscription(self, test_db):
        """Gold/Diamond tier sets subscription_status to active."""
        await db.upsert_user(2003, "paiduser", "Paid")
        await db.set_user_tier(2003, "gold")

        user = await db.get_user(2003)
        assert user.subscription_status == "active"


class TestSetFoundingMember:
    """Test set_founding_member() and get_founding_member_count()."""

    @pytest.mark.asyncio
    async def test_set_founding(self, test_db):
        """Sets is_founding_member flag."""
        await db.upsert_user(3001, "founder", "Founder")
        await db.set_founding_member(3001, True)

        user = await db.get_user(3001)
        assert user.is_founding_member is True

    @pytest.mark.asyncio
    async def test_count_founding(self, test_db):
        """Counts founding members correctly."""
        await db.upsert_user(3002, "founder1", "F1")
        await db.upsert_user(3003, "founder2", "F2")
        await db.upsert_user(3004, "regular", "R1")

        await db.set_founding_member(3002, True)
        await db.set_founding_member(3003, True)

        count = await db.get_founding_member_count()
        assert count == 2


class TestIsPremium:
    """Test is_premium() checks tier instead of just subscription_status."""

    @pytest.mark.asyncio
    async def test_bronze_not_premium(self, test_db):
        """Bronze user is not premium."""
        user = await db.upsert_user(4001, "free", "Free")
        assert db.is_premium(user) is False

    @pytest.mark.asyncio
    async def test_gold_is_premium(self, test_db):
        """Gold user is premium."""
        await db.upsert_user(4002, "gold", "Gold")
        await db.set_user_tier(4002, "gold")
        user = await db.get_user(4002)
        assert db.is_premium(user) is True

    @pytest.mark.asyncio
    async def test_diamond_is_premium(self, test_db):
        """Diamond user is premium."""
        await db.upsert_user(4003, "diamond", "Diamond")
        await db.set_user_tier(4003, "diamond")
        user = await db.get_user(4003)
        assert db.is_premium(user) is True

    def test_none_user(self):
        """None user is not premium."""
        assert db.is_premium(None) is False


class TestActivateSubscription:
    """Test activate_subscription() sets tier correctly."""

    @pytest.mark.asyncio
    async def test_activate_with_tier(self, test_db):
        """activate_subscription sets user_tier and expiry."""
        await db.upsert_user(5001, "sub", "Sub")
        expiry = dt.datetime(2027, 4, 1, tzinfo=dt.timezone.utc)
        await db.activate_subscription(
            5001, "sub_code_123", "gold_monthly",
            user_tier="gold", tier_expires_at=expiry,
        )

        user = await db.get_user(5001)
        assert user.subscription_status == "active"
        assert user.user_tier == "gold"
        assert user.subscription_code == "sub_code_123"
        assert user.plan_code == "gold_monthly"


class TestDeactivateSubscription:
    """Test deactivate_subscription() resets tier to bronze."""

    @pytest.mark.asyncio
    async def test_deactivate_resets_tier(self, test_db):
        """Deactivation resets to bronze and clears expiry."""
        await db.upsert_user(6001, "cancel", "Cancel")
        await db.set_user_tier(6001, "diamond")
        await db.deactivate_subscription(6001)

        user = await db.get_user(6001)
        assert user.user_tier == "bronze"
        assert user.tier_expires_at is None
        assert user.subscription_status == "cancelled"


class TestApplyPaymentEventSubscriptionFailures:
    """Provider failure events must not leave stale paid entitlements active."""

    @pytest.mark.asyncio
    async def test_matching_subscription_cancel_downgrades_active_user(self, test_db):
        await db.upsert_user(6101, "cancel-sub", "Cancel Sub")
        expiry = dt.datetime(2027, 4, 1, tzinfo=dt.timezone.utc)
        await db.activate_subscription(
            6101,
            "sub_cancel_6101",
            "diamond_monthly",
            user_tier="diamond",
            tier_expires_at=expiry,
            payment_reference="mze-6101-diamond-monthly-aa",
        )
        await db.create_payment_record(
            user_id=6101,
            plan_code="diamond_monthly",
            amount_cents=19900,
            provider_reference="mze-6101-diamond-monthly-aa",
            provider="stitch",
            provider_payment_id="sub_cancel_6101",
            checkout_url="https://mock.stitch.money/subscriptions/sub_cancel_6101",
            billing_status="active",
        )

        outcome = await db.apply_payment_event(
            provider="stitch",
            provider_reference="mze-6101-diamond-monthly-aa",
            provider_payment_id="sub_cancel_6101",
            provider_event_id="evt-sub-cancel-6101",
            plan_code="diamond_monthly",
            amount_cents=19900,
            event_status="cancelled",
            billing_status="cancelled",
            raw_event="{}",
        )

        user = await db.get_user(6101)
        payment = await db.get_payment_by_reference("stitch", "mze-6101-diamond-monthly-aa")
        assert outcome["outcome"] == "cancelled"
        assert outcome["subscription_deactivated"] is True
        assert user.subscription_status == "cancelled"
        assert user.user_tier == "bronze"
        assert user.tier_expires_at is None
        assert user.billing_status == "cancelled"
        assert payment.status == "cancelled"
        assert payment.billing_status == "cancelled"

    @pytest.mark.asyncio
    async def test_unmatched_payment_failure_does_not_downgrade_active_user(self, test_db):
        await db.upsert_user(6102, "failed-pay", "Failed Pay")
        expiry = dt.datetime(2027, 4, 1, tzinfo=dt.timezone.utc)
        await db.activate_subscription(
            6102,
            "sub_active_6102",
            "gold_monthly",
            user_tier="gold",
            tier_expires_at=expiry,
            payment_reference="mze-6102-gold-monthly-active",
        )
        await db.create_payment_record(
            user_id=6102,
            plan_code="gold_monthly",
            amount_cents=9900,
            provider_reference="mze-6102-gold-monthly-failed",
            provider="stitch",
            provider_payment_id="pay_failed_6102",
            checkout_url="https://mock.stitch.money/checkout/pay_failed_6102",
            billing_status="awaiting_webhook",
        )

        outcome = await db.apply_payment_event(
            provider="stitch",
            provider_reference="mze-6102-gold-monthly-failed",
            provider_payment_id="pay_failed_6102",
            provider_event_id="evt-pay-failed-6102",
            plan_code="gold_monthly",
            amount_cents=9900,
            event_status="failed",
            billing_status="failed",
            raw_event="{}",
        )

        user = await db.get_user(6102)
        assert outcome["outcome"] == "failed"
        assert "subscription_deactivated" not in outcome
        assert user.subscription_status == "active"
        assert user.user_tier == "gold"
        assert user.tier_expires_at == expiry.replace(tzinfo=None)
        assert user.billing_status == "active"

    @pytest.mark.asyncio
    async def test_subscription_renewal_extends_existing_confirmed_access(self, test_db):
        await db.upsert_user(6103, "renew-sub", "Renew Sub")
        await db.create_payment_record(
            user_id=6103,
            plan_code="gold_monthly",
            amount_cents=9900,
            provider_reference="mze-6103-gold-monthly-renew",
            provider="stitch",
            provider_payment_id="sub_renew_6103",
            checkout_url="https://mock.stitch.money/subscriptions/sub_renew_6103",
            billing_status="awaiting_webhook",
        )

        first = await db.apply_payment_event(
            provider="stitch",
            provider_reference="mze-6103-gold-monthly-renew",
            provider_payment_id="sub_renew_6103",
            provider_event_id="evt-sub-created-6103",
            plan_code="gold_monthly",
            amount_cents=9900,
            event_status="confirmed",
            billing_status="active",
            raw_event="{}",
            event_type="subscription.created",
        )
        first_user = await db.get_user(6103)
        first_expiry = first_user.tier_expires_at

        renewed = await db.apply_payment_event(
            provider="stitch",
            provider_reference="mze-6103-gold-monthly-renew",
            provider_payment_id="sub_renew_6103",
            provider_event_id="evt-sub-renewed-6103",
            plan_code="gold_monthly",
            amount_cents=9900,
            event_status="confirmed",
            billing_status="active",
            raw_event="{}",
            event_type="subscription.renewed",
        )

        user = await db.get_user(6103)
        assert first["outcome"] == "confirmed"
        assert renewed["outcome"] == "renewed"
        assert user.subscription_status == "active"
        assert user.user_tier == "gold"
        assert user.tier_expires_at >= first_expiry + dt.timedelta(days=29)

    @pytest.mark.asyncio
    async def test_founding_subscription_cancel_clears_founding_entitlement(self, test_db):
        await db.upsert_user(6104, "cancel-founder", "Cancel Founder")
        await db.create_payment_record(
            user_id=6104,
            plan_code="founding_diamond",
            amount_cents=69900,
            provider_reference="mze-6104-founding-diamond-aa",
            provider="stitch",
            provider_payment_id="sub_found_6104",
            checkout_url="https://mock.stitch.money/subscriptions/sub_found_6104",
            is_founding=True,
            billing_status="awaiting_webhook",
        )

        confirmed = await db.apply_payment_event(
            provider="stitch",
            provider_reference="mze-6104-founding-diamond-aa",
            provider_payment_id="sub_found_6104",
            provider_event_id="evt-founder-created-6104",
            plan_code="founding_diamond",
            amount_cents=69900,
            event_status="confirmed",
            billing_status="active",
            raw_event="{}",
            event_type="subscription.created",
        )
        assert confirmed["outcome"] == "confirmed"

        cancelled = await db.apply_payment_event(
            provider="stitch",
            provider_reference="mze-6104-founding-diamond-aa",
            provider_payment_id="sub_found_6104",
            provider_event_id="evt-founder-cancelled-6104",
            plan_code="founding_diamond",
            amount_cents=69900,
            event_status="cancelled",
            billing_status="cancelled",
            raw_event="{}",
            event_type="subscription.cancelled",
        )

        user = await db.get_user(6104)
        assert cancelled["subscription_deactivated"] is True
        assert user.subscription_status == "cancelled"
        assert user.user_tier == "bronze"
        assert user.is_founding_member is False
        assert user.founding_slot_number is None
