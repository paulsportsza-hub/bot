"""W92-VERDICT-QUALITY P2 — pre-write quality gate on _store_verdict_cache_sync.

Verifies that ``bot._store_verdict_cache_sync`` enforces ``min_verdict_quality``
BEFORE attempting to INSERT/UPDATE the narrative_cache row. Failing verdicts are
silently skipped (no DB write, no exception) with a Sentry breadcrumb logged for
observability. Passing verdicts take the normal persist path.

This gate is the last line of defence: if Sonnet ignores the P1 prompt rules and
the quality gate is absent at write time, trivial verdicts end up in the cache.
Regression guard — if any test fails, the gate has been weakened or removed.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import bot as _bot


# Deterministic values used across tests.
_MATCH_KEY = "arsenal_vs_chelsea_2026-05-01"


def _rejected_verdict() -> str:
    """A 30-char trivial verdict that fails every tier floor."""
    return "At 1.85 on Betway for Arsenal."


def _gold_pass_verdict() -> str:
    """A Gold-tier verdict that passes the unified validator stack.

    Updated under FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 — the
    new validator enforces verdict closure rule (action verb + team + odds in
    closing sentence), telemetry vocabulary ban, vague-content ban, char range
    [100, 260], and tier-band tone in addition to the legacy
    ``min_verdict_quality`` floor. The old fixture closed with "moving in the
    opposite direction" (no action verb + team + odds in last sentence) and
    leaked telemetry ("the model gives", "a clear signal", "supported by",
    "line is moving") — all blocked under the new contract.
    """
    return (
        "Arsenal's form is solid and the line is too long for what we see. "
        "Back Arsenal at 1.85 with Betway, even with the rotation concern — "
        "standard stake on this one."
    )


class TestVerdictCachePreWriteGate(unittest.TestCase):
    """W92-VERDICT-QUALITY P2: pre-write gate on _store_verdict_cache_sync."""

    def test_short_verdict_is_rejected_and_no_db_write_happens(self):
        """30-char verdict at gold tier fails the quality gate — DB is untouched."""
        fake_conn = MagicMock()
        with patch("db_connection.get_connection", return_value=fake_conn) as mock_conn:
            _bot._store_verdict_cache_sync(
                _MATCH_KEY,
                _rejected_verdict(),
                {"edge_tier": "gold"},
            )
        # Gate rejected BEFORE reaching the DB — connection factory never invoked.
        assert mock_conn.call_count == 0
        assert fake_conn.execute.call_count == 0
        assert fake_conn.commit.call_count == 0

    def test_short_verdict_logs_sentry_breadcrumb(self):
        """Rejected verdict must emit the ``verdict_cache_rejected`` breadcrumb."""
        fake_sentry = MagicMock()
        with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}):
            _bot._store_verdict_cache_sync(
                _MATCH_KEY,
                _rejected_verdict(),
                {"edge_tier": "gold"},
            )
        assert fake_sentry.add_breadcrumb.called, "breadcrumb must fire on rejection"
        call_kwargs = fake_sentry.add_breadcrumb.call_args.kwargs
        assert call_kwargs.get("message") == "verdict_cache_rejected"
        assert call_kwargs.get("category") == "verdict"
        data = call_kwargs.get("data") or {}
        assert data.get("match_id") == _MATCH_KEY
        assert data.get("tier") == "gold"

    def test_short_verdict_returns_cleanly_does_not_raise(self):
        """Gate failure must be a silent skip, never a raised exception."""
        # Should not raise anything.
        _bot._store_verdict_cache_sync(
            _MATCH_KEY,
            _rejected_verdict(),
            {"edge_tier": "gold"},
        )

    def test_passing_verdict_proceeds_to_db_write(self):
        """A 180-char verdict passes the gate and reaches the DB layer.

        Updated under FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01:
        the new validator's closure-rule gate (Gate 10) requires the closing
        sentence to contain action verb + team or selection + odds. The
        team-name match runs against ``evidence_pack['home_team']`` and
        ``evidence_pack['away_team']``, so tip_data must carry an
        ``evidence_pack`` dict for the gate to recognise the team.
        """
        fake_conn = MagicMock()
        # Simulate "row does not exist yet" so INSERT path runs.
        fake_conn.execute.return_value.fetchone.return_value = None
        with patch("db_connection.get_connection", return_value=fake_conn) as mock_conn, \
             patch("bot._compute_odds_hash", return_value="hash_xyz"):
            _bot._store_verdict_cache_sync(
                _MATCH_KEY,
                _gold_pass_verdict(),
                {
                    "edge_tier": "gold",
                    "evidence_pack": {
                        "home_team": "Arsenal",
                        "away_team": "Chelsea",
                    },
                },
            )
        # Connection factory was invoked — gate did NOT reject.
        assert mock_conn.call_count == 1
        # At least one execute (the existence SELECT + the INSERT).
        assert fake_conn.execute.call_count >= 2
        assert fake_conn.commit.called

    def test_tier_derived_from_tip_data_fallback_keys(self):
        """Tier lookup must accept ``edge_tier`` / ``tier`` / ``display_tier``."""
        fake_sentry = MagicMock()
        # ``tier`` key should be picked up and surface in the breadcrumb.
        with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}):
            _bot._store_verdict_cache_sync(
                _MATCH_KEY,
                _rejected_verdict(),
                {"tier": "diamond"},
            )
        data = fake_sentry.add_breadcrumb.call_args.kwargs.get("data") or {}
        assert data.get("tier") == "diamond"

    def test_missing_tier_defaults_to_bronze(self):
        """Absent tier keys should fall back to bronze — still gates, never raises."""
        fake_sentry = MagicMock()
        with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}):
            _bot._store_verdict_cache_sync(
                _MATCH_KEY,
                _rejected_verdict(),
                {},  # no edge_tier / tier / display_tier
            )
        # Bronze floor (60 chars) still rejects a 30-char verdict.
        data = fake_sentry.add_breadcrumb.call_args.kwargs.get("data") or {}
        assert data.get("tier") == "bronze"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
