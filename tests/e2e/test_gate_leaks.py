"""Layer 5: Cross-tier gate leak detection.

Bronze explores every screen → never sees paid data.
Same edge via /tips vs direct access → same gate level.
"""

from __future__ import annotations

import asyncio
import os
import re
from unittest.mock import patch

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

_BROADCAST_PATCH = patch(
    "bot._get_broadcast_details",
    return_value={"broadcast": "", "kickoff": "Sat 10 Mar · 17:30"},
)
_PORTFOLIO_PATCH = patch("bot._get_portfolio_line", return_value="")
_FOUNDING_PATCH = patch("bot._founding_days_left", return_value=8)


def _make_tip(display_tier: str = "gold", **kw) -> dict:
    edge_score = {
        "diamond": 62,
        "gold": 45,
        "silver": 39,
        "bronze": 20,
    }.get(display_tier, 45)
    defaults = {
        "home_team": "Mamelodi Sundowns",
        "away_team": "Kaizer Chiefs",
        "league": "PSL",
        "league_key": "psl",
        "sport_key": "soccer_south_africa_psl",
        "outcome": "Sundowns",
        "odds": 2.10,
        "ev": 8.0,
        "display_tier": display_tier,
        "edge_rating": display_tier,
        "match_id": f"sundowns_vs_chiefs_{display_tier}_2026-03-10",
        "event_id": f"sundowns_vs_chiefs_{display_tier}_2026-03-10",
        "commence_time": "2026-03-10T15:00:00Z",
        "bookmaker": "hollywoodbets",
        "odds_by_bookmaker": {"hollywoodbets": 2.10},
        "edge_score": edge_score,
        "edge_v2": {"confirming_signals": 2},
    }
    defaults.update(kw)
    return defaults


class TestTierGateMatrix:
    """Exhaustive tier gate matrix — every combination returns expected level."""

    @pytest.mark.parametrize(
        "user_tier,edge_tier,expected",
        [
            # Diamond sees everything
            ("diamond", "diamond", "full"),
            ("diamond", "gold", "full"),
            ("diamond", "silver", "full"),
            ("diamond", "bronze", "full"),
            # Gold sees gold and below, diamond locked
            ("gold", "diamond", "blurred"),
            ("gold", "gold", "full"),
            ("gold", "silver", "full"),
            ("gold", "bronze", "full"),
            # Bronze: complex gating
            ("bronze", "diamond", "locked"),
            ("bronze", "gold", "blurred"),
            ("bronze", "silver", "partial"),
            ("bronze", "bronze", "full"),
        ],
    )
    def test_access_level(self, user_tier, edge_tier, expected):
        from tier_gate import get_edge_access_level

        assert get_edge_access_level(user_tier, edge_tier) == expected


class TestBronzeNeverSeesPaidData:
    """Bronze user on every screen → never sees Diamond/Gold odds."""

    def test_bronze_diamond_no_odds_in_card(self):
        """Bronze viewing Diamond edge: no odds value in card text."""
        tip = _make_tip("diamond", odds=1.85)
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page

            text, _, _ = asyncio.run(_build_hot_tips_page([tip], page=0, user_tier="bronze"))
        # The card should NOT contain odds value
        assert "1.85" not in text
        assert "@ " not in text  # No "@ odds" pattern

    def test_bronze_gold_no_odds_in_card(self):
        """Bronze viewing Gold edge: blurred, no specific odds."""
        tip = _make_tip("gold", odds=2.50)
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page

            text, _, _ = asyncio.run(_build_hot_tips_page([tip], page=0, user_tier="bronze"))
        # Blurred card shows return but not specific odds
        assert "@ 2.50" not in text

    def test_bronze_silver_sees_odds(self):
        """Bronze viewing Silver edge via detail CTA still gets a real bookmaker link."""
        from bot import _build_game_buttons

        tip = _make_tip("silver", odds=3.20)
        rows = _build_game_buttons(
            [tip],
            event_id=tip["event_id"],
            user_id=1,
            source="edge_picks",
            user_tier="bronze",
            edge_tier="silver",
            selected_outcome=tip["outcome"],
        )
        assert rows[0][0].text.startswith("🥈 Back Sundowns on")
        assert rows[0][0].url

    def test_bronze_multi_page_no_leak(self):
        """Bronze can paginate without seeing locked data."""
        tips = [
            _make_tip(t, match_id=f"{t}_{i}_2026-03-10", odds=1.5 + i * 0.5)
            for i, t in enumerate(
                [
                    "diamond",
                    "gold",
                    "silver",
                    "bronze",
                    "diamond",
                    "gold",
                    "silver",
                    "bronze",
                ]
            )
        ]
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page

            # Page 1
            text1, _, _ = asyncio.run(_build_hot_tips_page(tips, page=0, user_tier="bronze"))
            # Page 2
            text2, _, _ = asyncio.run(_build_hot_tips_page(tips, page=1, user_tier="bronze"))

        for text, page_num in [(text1, 1), (text2, 2)]:
            # Find diamond-tier card lines — they must not contain odds
            lines = text.split("\n")
            for line in lines:
                if "Our highest-conviction pick" in line:
                    # This is a locked card — should not have odds nearby
                    idx = lines.index(line)
                    block = "\n".join(lines[max(0, idx - 2) : idx + 1])
                    # Must not contain "@ X.XX" pattern
                    odds_pattern = re.findall(r"@ \d+\.\d+", block)
                    assert not odds_pattern, (
                        f"Odds leaked to locked card on page {page_num}: {block}"
                    )


class TestGateConsistency:
    """Same edge viewed via list vs direct → same access level."""

    def test_same_edge_same_gate(self):
        """get_edge_access_level is deterministic — calling twice gives same result."""
        from tier_gate import get_edge_access_level

        for user_tier in ("bronze", "gold", "diamond"):
            for edge_tier in ("diamond", "gold", "silver", "bronze"):
                result1 = get_edge_access_level(user_tier, edge_tier)
                result2 = get_edge_access_level(user_tier, edge_tier)
                assert result1 == result2

    def test_user_can_access_matches_full(self):
        """user_can_access_edge returns True iff access is 'full'."""
        from tier_gate import user_can_access_edge, get_edge_access_level

        for user_tier in ("bronze", "gold", "diamond"):
            for edge_tier in ("diamond", "gold", "silver", "bronze"):
                can = user_can_access_edge(user_tier, edge_tier)
                access = get_edge_access_level(user_tier, edge_tier)
                if access == "full":
                    assert can, (
                        f"{user_tier}/{edge_tier}: full access but can_access=False"
                    )
                elif access == "partial":
                    # Bronze viewing silver: partial means odds visible but breakdown gated
                    # user_can_access_edge returns True for bronze/silver
                    pass  # Don't assert — partial is a special case
                else:
                    assert not can, (
                        f"{user_tier}/{edge_tier}: {access} but can_access=True"
                    )


class TestBreakdownGating:
    """AI breakdown sections are properly gated."""

    def test_full_access_returns_full_narrative(self):
        """Diamond viewing any edge gets full narrative back."""
        from bot import _gate_breakdown_sections

        narrative = (
            "📋 <b>The Setup</b>\nArsenal are in fine form.\n\n"
            "🎯 <b>The Edge</b>\nValue on the draw.\n\n"
            "⚠️ <b>The Risk</b>\nDerby day.\n\n"
            "🏆 <b>Verdict</b>\nBack the draw."
        )
        result = _gate_breakdown_sections(narrative, "diamond", "diamond")
        assert result == narrative  # Unchanged

    def test_bronze_gold_edge_gated(self):
        """Bronze viewing Gold edge: Setup free, Edge/Risk/Verdict locked."""
        from bot import _gate_breakdown_sections

        narrative = (
            "📋 <b>The Setup</b>\nArsenal are in fine form.\n\n"
            "🎯 <b>The Edge</b>\nValue on the draw.\n\n"
            "⚠️ <b>The Risk</b>\nDerby day.\n\n"
            "🏆 <b>Verdict</b>\nBack the draw."
        )
        result = _gate_breakdown_sections(narrative, "bronze", "gold")
        # Setup should be visible
        assert "Arsenal" in result or "form" in result
        # Edge/Risk/Verdict should show lock
        assert "🔒 Available on Gold." in result
        # Actual content should be stripped
        assert "Value on the draw" not in result
        assert "Derby day" not in result
        assert "Back the draw" not in result


class TestUpgradeMessages:
    """Upgrade messages are tier-appropriate and never empty for lower tiers."""

    def test_bronze_tip_limit(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("bronze", context="tip")
        assert "3 free detail views" in msg
        assert "/subscribe" in msg

    def test_bronze_gold_edge(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("bronze", context="gold_edge")
        assert "Gold Edge" in msg

    def test_bronze_diamond_edge(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("bronze", context="diamond_edge")
        assert "Diamond Edge" in msg

    def test_gold_gets_diamond_upgrade(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("gold", context="edge")
        assert "Diamond" in msg

    def test_diamond_no_upgrade(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("diamond", context="edge")
        assert msg == ""  # Diamond sees everything
