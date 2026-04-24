"""BUILD-CONTRACT-TESTS-01 — Test 4: Subscription Tier Reconciliation

W84-ACC1 invariants:
  (a) get_user_tier() returns the correct derived tier when user_tier='bronze'
      AND subscription_status='active', for every STITCH_PRODUCTS plan code.
  (b) /qa reset does NOT call db.set_user_tier() — subscription state is never
      mutated by QA commands (W84-ACC1 comment).
"""
from __future__ import annotations

import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import config
from db import _resolve_tier_from_subscription


def _make_user(
    user_tier: str = "bronze",
    subscription_status: str = "active",
    plan_code: str = "",
    tier_expires_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        user_tier=user_tier,
        subscription_status=subscription_status,
        plan_code=plan_code,
        tier_expires_at=tier_expires_at,
    )


# ── Tier reconciliation from STITCH_PRODUCTS ──────────────────────────────────

@pytest.mark.parametrize("plan_code,expected_tier", [
    (plan_code, plan_meta["tier"])
    for plan_code, plan_meta in config.STITCH_PRODUCTS.items()
])
def test_resolve_tier_from_stitch_products(plan_code: str, expected_tier: str):
    """_resolve_tier_from_subscription returns correct tier for every STITCH_PRODUCTS plan."""
    user = _make_user(
        user_tier="bronze",
        subscription_status="active",
        plan_code=plan_code,
    )
    result = _resolve_tier_from_subscription(user)
    assert result == expected_tier, (
        f"Expected tier '{expected_tier}' for plan_code='{plan_code}', got '{result}'"
    )


def test_resolve_tier_legacy_stitch_premium():
    """'stitch_premium' legacy plan code maps to 'gold'."""
    user = _make_user(plan_code="stitch_premium", subscription_status="active")
    result = _resolve_tier_from_subscription(user)
    assert result == "gold"


def test_resolve_tier_no_active_subscription():
    """Returns None when subscription_status != 'active'."""
    user = _make_user(plan_code="gold_monthly", subscription_status="cancelled")
    result = _resolve_tier_from_subscription(user)
    assert result is None


def test_resolve_tier_unknown_plan_code():
    """Returns None for an unrecognised plan code even if subscription is active."""
    user = _make_user(plan_code="unknown_plan_xyz", subscription_status="active")
    result = _resolve_tier_from_subscription(user)
    assert result is None


def test_resolve_tier_bronze_not_overridden():
    """When user_tier='bronze' and subscription inactive, stays bronze."""
    user = _make_user(user_tier="bronze", subscription_status="inactive", plan_code="")
    result = _resolve_tier_from_subscription(user)
    assert result is None


# ── /qa reset does NOT call db.set_user_tier() ────────────────────────────────

def test_qa_reset_does_not_call_set_user_tier():
    """W84-ACC1: /qa reset must NEVER call db.set_user_tier().

    Static analysis of the bot.py /qa reset handler block.
    """
    bot_py = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
    with open(bot_py, encoding="utf-8") as f:
        source = f.read()

    # Find the reset handler block: from 'if cmd == "reset":' to the next 'if cmd ==' or return
    m = re.search(
        r'if cmd == ["\']reset["\']:(.+?)(?=\n    if cmd ==|\Z)',
        source,
        re.DOTALL,
    )
    assert m, '"reset" cmd handler not found in bot.py /qa handler'

    reset_block = m.group(1)

    # Strip comment lines before checking — the block may contain comments that
    # document the old bug (e.g. "# was: db.set_user_tier(...)") which are harmless.
    non_comment_lines = [
        line for line in reset_block.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_block = "\n".join(non_comment_lines)

    assert "set_user_tier" not in non_comment_block, (
        "W84-ACC1 VIOLATION: /qa reset handler calls db.set_user_tier(). "
        "QA reset must NEVER mutate the real subscription tier — only clear "
        "_QA_TIER_OVERRIDES in-memory dict."
    )
