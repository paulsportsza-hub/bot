"""Stitch payment service for MzansiEdge Premium subscriptions.

Stitch (stitch.money) provides Pay By Bank, Card, Apple Pay, and Google Pay
via their LinkPay checkout. Uses GraphQL API with OAuth2 client credentials.

When STITCH_MOCK_MODE=true, delegates to stitch_mock for local development
(Stitch has no test environment).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

import config

log = logging.getLogger("mzansiedge.stitch")

# ── Cached client token ──────────────────────────────────
_token_cache: dict[str, Any] = {}  # {"token": str, "expires_at": float}


class StitchService:
    """Async Stitch payment service."""

    GRAPHQL_URL = "https://api.stitch.money/graphql"
    TOKEN_URL = "https://secure.stitch.money/connect/token"

    def __init__(self) -> None:
        self.client_id = config.STITCH_CLIENT_ID
        self.client_secret = config.STITCH_CLIENT_SECRET
        self.webhook_secret = config.STITCH_WEBHOOK_SECRET

    def _is_mock(self) -> bool:
        return config.STITCH_MOCK_MODE

    @staticmethod
    def build_checkout_url(payment_url: str) -> str:
        """Append a whitelisted Stitch redirect URI when configured."""
        redirect_uri = config.STITCH_REDIRECT_URI.strip()
        if not redirect_uri:
            return payment_url

        parsed = urlparse(payment_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["redirect_uri"] = redirect_uri
        return urlunparse(parsed._replace(query=urlencode(query)))

    async def get_client_token(self) -> str:
        """Fetch OAuth2 client token with client_paymentrequest scope.

        Caches the token until 60s before expiry.
        """
        if self._is_mock():
            from services.stitch_mock import MockStitchService
            return await MockStitchService().get_client_token()

        # Return cached token if still valid
        cached = _token_cache.get("token")
        expires_at = _token_cache.get("expires_at", 0)
        if cached and time.time() < expires_at:
            return cached

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "client_paymentrequest",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                body = await resp.json()
                if resp.status != 200:
                    log.error("Stitch token error: %s", body)
                    raise RuntimeError(f"Stitch token failed: {body}")

                token = body["access_token"]
                expires_in = body.get("expires_in", 3600)
                _token_cache["token"] = token
                _token_cache["expires_at"] = time.time() + expires_in - 60
                log.info("Stitch client token acquired (expires in %ds)", expires_in)
                return token

    async def create_payment(
        self,
        user_id: int,
        amount_cents: int = config.TIER_PRICES.get("gold", 9900),
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Create a PaymentInitiationRequest via Stitch GraphQL.

        Returns {payment_url, payment_id, reference}.
        The payment_url is a LinkPay checkout supporting Card, EFT, Apple/Google Pay.
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

        amount_rands = amount_cents / 100
        mutation = """
        mutation CreatePaymentRequest(
            $amount: MoneyInput!,
            $payerReference: String!,
            $beneficiaryReference: String!,
            $externalReference: String
        ) {
            clientPaymentInitiationRequestCreate(input: {
                amount: $amount,
                payerReference: $payerReference,
                beneficiaryReference: $beneficiaryReference,
                externalReference: $externalReference
            }) {
                paymentInitiationRequest {
                    id
                    url
                    status {
                        __typename
                    }
                }
            }
        }
        """

        variables = {
            "amount": {"quantity": str(amount_rands), "currency": "ZAR"},
            "payerReference": f"MzansiEdge-{user_id}",
            "beneficiaryReference": reference,
            "externalReference": str(user_id),
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.GRAPHQL_URL,
                json={"query": mutation, "variables": variables},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                body = await resp.json()

                errors = body.get("errors")
                if errors:
                    log.error("Stitch GraphQL errors: %s", errors)
                    raise RuntimeError(f"Stitch payment failed: {errors[0].get('message', errors)}")

                pir = body["data"]["clientPaymentInitiationRequestCreate"]["paymentInitiationRequest"]
                result = {
                    "payment_url": self.build_checkout_url(pir["url"]),
                    "payment_id": pir["id"],
                    "reference": reference,
                }
                log.info("Stitch payment created: %s", result["payment_id"])
                return result

    async def get_payment_status(self, payment_id: str) -> dict[str, Any]:
        """Query payment status from Stitch.

        Returns {status, payment_id, ...}.
        """
        if self._is_mock():
            from services.stitch_mock import MockStitchService
            return await MockStitchService().get_payment_status(payment_id)

        token = await self.get_client_token()

        query = """
        query GetPaymentStatus($paymentId: ID!) {
            node(id: $paymentId) {
                ... on PaymentInitiationRequest {
                    id
                    status {
                        __typename
                        ... on PaymentInitiationRequestCompleted {
                            date
                            amount {
                                quantity
                                currency
                            }
                            payer {
                                ... on PaymentInitiationBankAccountPayer {
                                    accountNumber
                                    bankId
                                }
                            }
                        }
                        ... on PaymentInitiationRequestCancelled {
                            date
                            reason
                        }
                        ... on PaymentInitiationRequestExpired {
                            date
                        }
                    }
                }
            }
        }
        """

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.GRAPHQL_URL,
                json={"query": query, "variables": {"paymentId": payment_id}},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                body = await resp.json()

                errors = body.get("errors")
                if errors:
                    log.error("Stitch status query error: %s", errors)
                    return {"status": "error", "payment_id": payment_id}

                node = body.get("data", {}).get("node")
                if not node:
                    return {"status": "unknown", "payment_id": payment_id}

                status_obj = node.get("status", {})
                type_name = status_obj.get("__typename", "Unknown")

                # Map Stitch status types to simple statuses
                status_map = {
                    "PaymentInitiationRequestCompleted": "success",
                    "PaymentInitiationRequestCancelled": "cancelled",
                    "PaymentInitiationRequestExpired": "expired",
                    "PaymentInitiationRequestPending": "pending",
                }
                return {
                    "status": status_map.get(type_name, "pending"),
                    "payment_id": payment_id,
                    "raw_status": type_name,
                }

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Stitch webhook HMAC-SHA256 signature (Svix delivery)."""
        signature = headers.get("x-stitch-signature", headers.get("X-Stitch-Signature", ""))
        if not signature or not self.webhook_secret:
            return False

        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def parse_webhook_event(body: bytes) -> dict[str, Any]:
        """Parse webhook JSON body."""
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

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
