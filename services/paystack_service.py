"""Paystack subscription service for MzansiEdge Premium."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import aiohttp

import config

log = logging.getLogger("mzansiedge.paystack")

PAYSTACK_BASE = config.PAYSTACK_BASE_URL
SECRET_KEY = config.PAYSTACK_SECRET_KEY


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SECRET_KEY}",
        "Content-Type": "application/json",
    }


async def _post(endpoint: str, data: dict) -> dict[str, Any]:
    """POST to Paystack API. Returns parsed JSON response."""
    url = f"{PAYSTACK_BASE}{endpoint}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=_headers()) as resp:
            body = await resp.json()
            if not body.get("status"):
                log.error("Paystack POST %s failed: %s", endpoint, body.get("message"))
            return body


async def _get(endpoint: str) -> dict[str, Any]:
    """GET from Paystack API. Returns parsed JSON response."""
    url = f"{PAYSTACK_BASE}{endpoint}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=_headers()) as resp:
            return await resp.json()


# ── Plan Management ──────────────────────────────────────

# Cached plan code — fetched/created once at startup
_plan_code: str | None = None


async def ensure_plan() -> str:
    """Get or create the MzansiEdge Premium plan. Returns plan_code."""
    global _plan_code
    if _plan_code:
        return _plan_code

    # Check existing plans
    result = await _get("/plan")
    if result.get("status") and result.get("data"):
        for plan in result["data"]:
            if (
                plan.get("name") == config.PREMIUM_PLAN_NAME
                and plan.get("amount") == config.PREMIUM_PLAN_AMOUNT
                and plan.get("interval") == "monthly"
            ):
                _plan_code = plan["plan_code"]
                log.info("Found existing Paystack plan: %s", _plan_code)
                return _plan_code

    # Create new plan
    result = await _post("/plan", {
        "name": config.PREMIUM_PLAN_NAME,
        "amount": config.PREMIUM_PLAN_AMOUNT,
        "interval": "monthly",
        "currency": "ZAR",
    })
    if result.get("status") and result.get("data"):
        _plan_code = result["data"]["plan_code"]
        log.info("Created Paystack plan: %s", _plan_code)
        return _plan_code

    raise RuntimeError(f"Failed to create Paystack plan: {result.get('message')}")


# ── Transaction Initialization ───────────────────────────

async def initialize_transaction(
    email: str, user_id: int,
) -> dict[str, Any]:
    """Start a subscription transaction. Returns {authorization_url, reference, access_code}."""
    plan_code = await ensure_plan()
    result = await _post("/transaction/initialize", {
        "email": email,
        "amount": config.PREMIUM_PLAN_AMOUNT,
        "plan": plan_code,
        "currency": "ZAR",
        "metadata": {
            "telegram_user_id": str(user_id),
            "custom_fields": [
                {"display_name": "Telegram User ID", "variable_name": "telegram_user_id", "value": str(user_id)},
            ],
        },
    })
    if result.get("status") and result.get("data"):
        data = result["data"]
        return {
            "authorization_url": data["authorization_url"],
            "reference": data["reference"],
            "access_code": data["access_code"],
        }

    raise RuntimeError(f"Paystack init failed: {result.get('message')}")


# ── Transaction Verification ─────────────────────────────

async def verify_transaction(reference: str) -> dict[str, Any]:
    """Verify a transaction by reference. Returns full transaction data."""
    result = await _get(f"/transaction/verify/{reference}")
    if result.get("status") and result.get("data"):
        return result["data"]
    return {}


# ── Webhook Signature Verification ───────────────────────

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify Paystack webhook HMAC-SHA512 signature."""
    expected = hmac.new(
        SECRET_KEY.encode("utf-8"),
        body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_webhook_event(body: bytes) -> dict[str, Any]:
    """Parse webhook JSON body into event dict."""
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}
