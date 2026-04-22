"""Stitch Express payment service for MzansiEdge Premium subscriptions.

Stitch Express provides a simplified REST payment API:
  https://express.stitch.money

Auth flow: POST /api/v1/token with JSON body containing clientId + clientSecret
+ scope. Returns a short-lived (15 min) accessToken.

Payment creation: POST /api/v1/payment-links — REST, amount in cents (integer).
Returns a payment link URL at data.payment.link.

Payment status: GET /api/v1/payment/{paymentId} — returns data.payment.status
(PENDING / COMPLETED / CANCELLED / EXPIRED).

Webhook verification: Stitch Express delivers webhooks via Svix. The
STITCH_WEBHOOK_SECRET env var holds the full whsec_... string (Express-issued).
Verification is performed by svix.webhooks.Webhook.verify() which checks
svix-id, svix-timestamp, and svix-signature headers with ±5 min replay protection.

When STITCH_MOCK_MODE=true, delegates to stitch_mock for local development.

NOTE: STITCH_CLIENT_ID and STITCH_CLIENT_SECRET must be Express credentials
(not Enterprise). The Express token endpoint rejects Enterprise credentials.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import aiohttp

try:
    import sentry_sdk as _sentry_sdk
except ImportError:
    _sentry_sdk = None

import config

log = logging.getLogger("mzansiedge.stitch")

# Cloudflare blocks default Python/aiohttp UA — all Stitch requests use this factory.
_STITCH_HEADERS = {"User-Agent": "MzansiEdge/1.0"}


def _stitch_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(headers=_STITCH_HEADERS)


# ── Per-scope token cache ────────────────────────────────
# Keyed by scope string: {scope: {"token": str, "expires_at": float}}
_token_cache: dict[str, dict[str, Any]] = {}

_EXPRESS_TOKEN_TTL = 900  # Express tokens are 15 min; cache until 60s before expiry


class StitchService:
    """Async Stitch Express payment service."""

    BASE_URL = "https://express.stitch.money"
    TOKEN_URL = "https://express.stitch.money/api/v1/token"
    PAYMENT_LINKS_URL = "https://express.stitch.money/api/v1/payment-links"
    PAYMENT_URL = "https://express.stitch.money/api/v1/payment"
    SUBSCRIPTIONS_URL = "https://express.stitch.money/api/v1/subscriptions"

    def __init__(self) -> None:
        self.client_id = config.STITCH_CLIENT_ID
        self.client_secret = config.STITCH_CLIENT_SECRET
        self.webhook_secret = config.STITCH_WEBHOOK_SECRET

    def _is_mock(self) -> bool:
        return config.STITCH_MOCK_MODE

    @staticmethod
    def build_checkout_url(payment_url: str) -> str:
        """Append whitelisted redirect URL when configured.

        Express uses ?redirect_url= (not redirect_uri as in Enterprise).
        """
        redirect_uri = config.STITCH_REDIRECT_URI.strip()
        if not redirect_uri:
            return payment_url

        parsed = urlparse(payment_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["redirect_url"] = redirect_uri
        return urlunparse(parsed._replace(query=urlencode(query)))

    async def get_client_token(self, scope: str = "client_paymentrequest") -> str:
        """Fetch Express OAuth2 token for the given scope.

        POST /api/v1/token with JSON body. Returns accessToken (15-min TTL).
        Caches per-scope until 60s before expiry. Express requires a single scope
        per token request — do NOT combine scopes.
        """
        if self._is_mock():
            from services.stitch_mock import MockStitchService
            return await MockStitchService().get_client_token()

        entry = _token_cache.get(scope, {})
        if entry.get("token") and time.time() < entry.get("expires_at", 0):
            return entry["token"]

        async with _stitch_session() as session:
            async with session.post(
                self.TOKEN_URL,
                json={
                    "clientId": self.client_id,
                    "clientSecret": self.client_secret,
                    "scope": scope,
                },
                headers={"Content-Type": "application/json"},
            ) as resp:
                body = await resp.json()
                if resp.status != 200 or not body.get("success"):
                    log.error("Stitch Express token error %s: %s", resp.status, body)
                    raise RuntimeError(f"Stitch Express token failed: {body}")

                token = body["data"]["accessToken"]
                _token_cache[scope] = {
                    "token": token,
                    "expires_at": time.time() + _EXPRESS_TOKEN_TTL - 60,
                }
                log.info("Stitch Express token acquired scope=%s (TTL ~15 min)", scope)
                return token

    async def create_payment(
        self,
        user_id: int,
        amount_cents: int = config.TIER_PRICES.get("gold", 9900),
        reference: str | None = None,
        payer_name: str | None = None,
        payer_email: str | None = None,
    ) -> dict[str, Any]:
        """Create a payment link via POST /api/v1/payment-links.

        Returns {payment_url, payment_id, reference}.
        amount_cents must be an integer (Express takes cents directly).
        payer_name is required by Express; falls back to "MzansiEdge Member".
        """
        if self._is_mock():
            from services.stitch_mock import MockStitchService
            result = await MockStitchService().create_payment(user_id, amount_cents, reference)
            result["payment_url"] = self.build_checkout_url(result["payment_url"])
            return result

        import uuid
        if not reference:
            reference = f"mze-{user_id}-{uuid.uuid4().hex[:8]}"

        token = await self.get_client_token()

        payload: dict[str, Any] = {
            "amount": amount_cents,
            "merchantReference": reference,
            "payerName": payer_name or "MzansiEdge Member",
        }
        if payer_email:
            payload["payerEmailAddress"] = payer_email

        async with _stitch_session() as session:
            async with session.post(
                self.PAYMENT_LINKS_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                body = await resp.json()

                if resp.status != 200 or not body.get("success"):
                    log.error("Stitch Express payment error %s: %s", resp.status, body)
                    raise RuntimeError(
                        f"Stitch Express payment failed: {body.get('generalErrors', body)}"
                    )

                payment = body["data"]["payment"]
                result = {
                    "payment_url": self.build_checkout_url(payment["link"]),
                    "payment_id": payment["id"],
                    "reference": reference,
                }
                log.info("Stitch Express payment created: %s", result["payment_id"])
                return result

    async def get_payment_status(self, payment_id: str) -> dict[str, Any]:
        """Query payment status for a payment link or completed payment.

        Express creates a payment LINK (pending) and a PAYMENT (when money moves).
        We try GET /api/v1/payment-links/{id} first (covers all link states).
        Falls back to GET /api/v1/payment/{id} for completed payment records.

        Returns {status, payment_id} where status is one of:
        success / cancelled / expired / pending / error / unknown.
        """
        if self._is_mock():
            from services.stitch_mock import MockStitchService
            return await MockStitchService().get_payment_status(payment_id)

        token = await self.get_client_token()

        status_map = {
            "COMPLETED": "success",
            "CANCELLED": "cancelled",
            "EXPIRED": "expired",
            "PENDING": "pending",
        }

        async with _stitch_session() as session:
            # Primary: payment-links endpoint (covers PENDING → COMPLETED arc)
            async with session.get(
                f"{self.PAYMENT_LINKS_URL}/{payment_id}",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if body.get("success"):
                        payment = body.get("data", {}).get("payment", {})
                        raw_status = payment.get("status", "")
                        return {
                            "status": status_map.get(raw_status, "pending"),
                            "payment_id": payment_id,
                            "raw_status": raw_status,
                        }

            # Fallback: payment record endpoint (for already-completed payments)
            async with session.get(
                f"{self.PAYMENT_URL}/{payment_id}",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if body.get("success"):
                        payment = body.get("data", {}).get("payment", {})
                        raw_status = payment.get("status", "")
                        return {
                            "status": status_map.get(raw_status, "pending"),
                            "payment_id": payment_id,
                            "raw_status": raw_status,
                        }

        log.error("Stitch Express: could not retrieve status for %s", payment_id)
        return {"status": "unknown", "payment_id": payment_id}

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Stitch Express webhook Svix signature.

        Stitch Express uses Svix for webhook delivery. STITCH_WEBHOOK_SECRET
        must be the Express-issued whsec_... string (from the Express dashboard).
        Svix enforces ±5 min replay protection automatically.
        """
        if not self.webhook_secret:
            return False
        from svix.webhooks import Webhook, WebhookVerificationError
        try:
            Webhook(self.webhook_secret).verify(body, headers)
            return True
        except WebhookVerificationError:
            if _sentry_sdk:
                _sentry_sdk.add_breadcrumb(
                    category="stitch.webhook.verify",
                    message="Express webhook signature verification failed",
                    level="warning",
                    data={
                        "svix_id": headers.get("svix-id", "missing"),
                        "has_timestamp": bool(headers.get("svix-timestamp")),
                    },
                )
            return False

    @staticmethod
    def parse_webhook_event(body: bytes) -> dict[str, Any]:
        """Parse webhook JSON body."""
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    async def create_subscription(
        self,
        *,
        user_id: int,
        plan_code: str,
        amount_cents: int,
        initial_amount_cents: int | None = None,
        period: str,
        payer_name: str,
        payer_email: str,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Create a recurring subscription via POST /api/v1/subscriptions.

        period must be "monthly" or "annual". Builds recurrence block per INV
        report §4.3–4.4. Token scope: client_recurringpaymentconsentrequest.

        Returns {subscription_id, checkout_url, status, reference}.
        On 400: raises RuntimeError with fieldErrors from response body.
        """
        if self._is_mock():
            from services.stitch_mock import MockStitchService
            return await MockStitchService().create_subscription(
                user_id=user_id,
                plan_code=plan_code,
                amount_cents=amount_cents,
                period=period,
                payer_name=payer_name,
                payer_email=payer_email,
                reference=reference,
            )

        import uuid
        from datetime import datetime, timezone

        if not reference:
            reference = f"mze-{user_id}-{plan_code.replace('_', '-')}-{uuid.uuid4().hex[:8]}"

        now = datetime.now(timezone.utc)
        billing_day = now.day
        billing_month = now.month
        start_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        if period == "monthly":
            recurrence = {
                "frequency": "MONTHLY",
                "interval": 1,
                "byMonthDay": billing_day,
            }
        else:
            recurrence = {
                "frequency": "YEARLY",
                "interval": 1,
                "byMonth": billing_month,
                "byMonthDay": billing_day,
            }

        payload: dict[str, Any] = {
            "amount": amount_cents,
            "merchantReference": reference,
            "payerId": str(user_id),
            "payerName": payer_name,
            "payerEmailAddress": payer_email,
            "startDate": start_date,
            "recurrence": recurrence,
        }
        if initial_amount_cents is not None:
            payload["initialAmount"] = initial_amount_cents

        token = await self.get_client_token(scope="client_recurringpaymentconsentrequest")

        async with _stitch_session() as session:
            async with session.post(
                self.SUBSCRIPTIONS_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                body = await resp.json()

                if resp.status == 400:
                    field_errors = body.get("fieldErrors") or body.get("generalErrors") or body
                    raise RuntimeError(f"Stitch subscription 400: {field_errors}")

                if resp.status != 200 or not body.get("success"):
                    log.error("Stitch subscription error %s: %s", resp.status, body)
                    raise RuntimeError(f"Stitch subscription failed: {body}")

                data = body["data"]["subscription"]
                result = {
                    "subscription_id": data["id"],
                    "checkout_url": data["url"],
                    "status": data["status"],
                    "reference": data["merchantReference"],
                }
                log.info("Stitch subscription created: %s", result["subscription_id"])
                return result

    async def build_mock_webhook_event(
        self,
        payment_id: str,
        *,
        status: str = "complete",
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate a mock webhook event through the same provider facade."""
        from services.stitch_mock import MockStitchService
        return await MockStitchService().simulate_webhook_event(
            payment_id,
            status=status,
            event_id=event_id,
        )


# Module-level singleton
stitch = StitchService()
