"""Mock Stitch service for local development.

Stitch has no test/sandbox environment. This mock simulates the full payment
flow with realistic GraphQL response structures. Toggled via STITCH_MOCK_MODE=true.

Payment IDs starting with "fail-" will simulate failed payments.
All others simulate success.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

log = logging.getLogger("mzansiedge.stitch.mock")

# In-memory payment store for mock mode
_mock_payments: dict[str, dict] = {}


class MockStitchService:
    """Mock implementation of StitchService for local development."""

    async def get_client_token(self) -> str:
        """Return a fake client token."""
        log.info("[MOCK] Returning mock Stitch client token")
        return "mock_stitch_token_for_local_dev"

    async def create_payment(
        self,
        user_id: int,
        amount_cents: int = 9900,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Simulate payment creation. Returns a mock LinkPay checkout URL."""
        if not reference:
            reference = f"mze-{user_id}-{uuid.uuid4().hex[:8]}"

        payment_id = f"mock-pir-{uuid.uuid4().hex[:12]}"

        # Store for later status checks
        _mock_payments[payment_id] = {
            "payment_id": payment_id,
            "user_id": user_id,
            "reference": reference,
            "amount_cents": amount_cents,
            "status": "pending",
        }
        _mock_payments[reference] = _mock_payments[payment_id]

        result = {
            "payment_url": f"https://mock.stitch.money/checkout/{payment_id}",
            "payment_id": payment_id,
            "reference": reference,
        }
        log.info("[MOCK] Created payment: %s for user %s (R%.2f)", payment_id, user_id, amount_cents / 100)
        return result

    async def get_payment_status(self, payment_id: str) -> dict[str, Any]:
        """Simulate payment status check.

        In mock mode, payments auto-complete (simulate success).
        Payment IDs containing "fail" return cancelled status.
        """
        stored = _mock_payments.get(payment_id, {})

        if "fail" in payment_id:
            status = "cancelled"
            raw = "PaymentInitiationRequestCancelled"
        else:
            # Auto-complete in mock mode
            status = "success"
            raw = "PaymentInitiationRequestCompleted"

        if stored:
            stored["status"] = status

        log.info("[MOCK] Payment status for %s: %s", payment_id, status)
        return {
            "status": status,
            "payment_id": payment_id,
            "raw_status": raw,
        }

    async def create_subscription(
        self,
        *,
        user_id: int,
        plan_code: str,
        amount_cents: int,
        period: str,
        payer_name: str,
        payer_email: str,
        reference: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Simulate subscription creation."""
        if not reference:
            reference = f"mze-{user_id}-{plan_code.replace('_', '-')}-mocksub"
        sub_id = f"mock-sub-{uuid.uuid4().hex[:12]}"
        _mock_payments[sub_id] = {
            "payment_id": sub_id,
            "user_id": user_id,
            "reference": reference,
            "amount_cents": amount_cents,
            "status": "pending",
            "is_subscription": True,
            "plan_code": plan_code,
        }
        _mock_payments[reference] = _mock_payments[sub_id]
        result = {
            "subscription_id": sub_id,
            "checkout_url": f"https://mock.stitch.money/subscriptions/{sub_id}",
            "status": "PENDING",
            "reference": reference,
        }
        log.info("[MOCK] Created subscription: %s for user %s (%s)", sub_id, user_id, plan_code)
        return result

    async def get_subscription_status(self, subscription_id: str) -> dict[str, Any]:
        """Simulate recurring subscription status checks."""
        stored = _mock_payments.get(subscription_id, {})
        if "fail" in subscription_id:
            status = "error"
            raw = "FAILED"
        elif "cancel" in subscription_id:
            status = "cancelled"
            raw = "CANCELLED"
        elif "expire" in subscription_id:
            status = "expired"
            raw = "EXPIRED"
        else:
            status = "success"
            raw = "ACTIVE"
            if stored:
                stored["status"] = status

        log.info("[MOCK] Subscription status for %s: %s", subscription_id, status)
        return {
            "status": status,
            "payment_id": subscription_id,
            "raw_status": raw,
        }

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Return stored mock payment metadata."""
        return dict(_mock_payments.get(payment_id, {}))

    async def simulate_webhook_event(
        self,
        payment_id: str,
        *,
        status: str = "complete",
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a mock Stitch webhook using stored payment metadata."""
        stored = _mock_payments.get(payment_id, {})
        user_id = int(stored.get("user_id", 0))
        amount_cents = int(stored.get("amount_cents", 0))
        reference = stored.get("reference", payment_id)
        event = simulate_webhook_payload(
            payment_id=payment_id,
            user_id=user_id,
            status=status,
            amount_cents=amount_cents,
            reference=reference,
            event_id=event_id,
        )
        if stored.get("is_subscription"):
            event["type"] = "subscription.created" if status == "complete" else "subscription.cancelled"
            event["data"]["merchantReference"] = reference
        return event


def simulate_webhook_payload(
    payment_id: str,
    user_id: int,
    status: str = "complete",
    *,
    amount_cents: int = 0,
    reference: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Generate a mock Stitch webhook payload for testing.

    Matches the structure Stitch sends via Svix webhooks.
    """
    return {
        "id": event_id or f"mock-event-{payment_id}-{status}",
        "type": "payment.complete" if status == "complete" else "payment.cancelled",
        "data": {
            "id": payment_id,
            "status": {
                "__typename": (
                    "PaymentInitiationRequestCompleted"
                    if status == "complete"
                    else "PaymentInitiationRequestCancelled"
                ),
            },
            "externalReference": str(user_id),
            "beneficiaryReference": reference or payment_id,
            "amount": {"quantity": f"{amount_cents / 100:.2f}", "currency": "ZAR"},
        },
    }
