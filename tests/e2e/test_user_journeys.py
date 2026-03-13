"""Layer 5: Synthetic user journeys — 3 core flows.

Tests the full path a user takes through the bot at each tier level.
All tests use controlled data (no live API/DB calls).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _make_tip(display_tier: str = "gold", **kw) -> dict:
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
    }
    defaults.update(kw)
    return defaults


def _multi_tier_tips() -> list[dict]:
    """Tips spanning all 4 tiers."""
    return [
        _make_tip("diamond", home_team="Arsenal", away_team="Chelsea",
                  match_id="ars_vs_che_2026-03-10", odds=1.85, ev=16.0),
        _make_tip("gold", home_team="Bulls", away_team="Stormers",
                  match_id="bul_vs_sto_2026-03-10", odds=1.65, ev=9.0),
        _make_tip("silver", home_team="Liverpool", away_team="Spurs",
                  match_id="liv_vs_spu_2026-03-10", odds=2.40, ev=5.0),
        _make_tip("bronze", home_team="Pirates", away_team="Stellenbosch",
                  match_id="pir_vs_ste_2026-03-10", odds=2.80, ev=1.5),
    ]


_BROADCAST_PATCH = patch("bot._get_broadcast_details", return_value={"broadcast": "", "kickoff": "Sat 10 Mar · 17:30"})
_PORTFOLIO_PATCH = patch("bot._get_portfolio_line", return_value="")
_FOUNDING_PATCH = patch("bot._founding_days_left", return_value=8)


class TestBronzeJourney:
    """Bronze user: sees locks, upgrade CTAs, never sees paid data."""

    def test_bronze_sees_locked_edges(self):
        """Bronze user sees 🔒 on Diamond edges."""
        from tier_gate import get_edge_access_level
        assert get_edge_access_level("bronze", "diamond") == "locked"
        assert get_edge_access_level("bronze", "gold") == "blurred"

    def test_bronze_tips_page_has_locks(self):
        """Bronze tips page contains lock indicators."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = _build_hot_tips_page(
                tips, page=0, user_tier="bronze",
            )
        # Must have lock line for diamond edge
        assert "Our highest-conviction pick." in text
        # Must have footer with /subscribe
        assert "/subscribe" in text

    def test_bronze_locked_button_goes_to_upgrade(self):
        """Locked/blurred edge button has hot:upgrade callback (shows upgrade prompt with Back)."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            _, markup = _build_hot_tips_page(
                tips, page=0, user_tier="bronze",
            )
        callbacks = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data
        ]
        # W84-P0: locked/blurred edges route to hot:upgrade:{page} (page-encoded since W84-HT2)
        assert any(cb.startswith("hot:upgrade") for cb in callbacks)
        # Accessible (silver/bronze) edges still route to edge:detail
        assert any(cb.startswith("edge:detail:") for cb in callbacks)

    def test_bronze_never_sees_diamond_odds(self):
        """Bronze Hot Tips text never reveals diamond edge odds."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, _ = _build_hot_tips_page(
                tips, page=0, user_tier="bronze",
            )
        # Diamond tip (Arsenal vs Chelsea, odds=1.85) should NOT show odds
        # The locked card should show "Our highest-conviction pick." not "@ 1.85"
        lines = text.split("\n")
        for line in lines:
            if "Arsenal" in line or "Chelsea" in line:
                # Find the card block for this edge
                idx = lines.index(line)
                card_block = "\n".join(lines[idx:idx+4])
                assert "1.85" not in card_block, f"Diamond odds leaked to bronze: {card_block}"

    def test_bronze_upgrade_message(self):
        """Bronze locked detail shows plan comparison."""
        from tier_gate import get_upgrade_message
        msg = get_upgrade_message("bronze", context="diamond_edge")
        assert "Diamond" in msg
        assert "/subscribe" in msg


class TestGoldJourney:
    """Gold user: full access to Gold edges, Diamond locked."""

    def test_gold_sees_gold_odds(self):
        """Gold user can see Gold edge odds (full access)."""
        from tier_gate import get_edge_access_level
        assert get_edge_access_level("gold", "gold") == "full"
        assert get_edge_access_level("gold", "silver") == "full"
        assert get_edge_access_level("gold", "bronze") == "full"

    def test_gold_diamond_locked(self):
        """Gold user sees Diamond edges as locked."""
        from tier_gate import get_edge_access_level
        assert get_edge_access_level("gold", "diamond") == "locked"

    def test_gold_tips_page(self):
        """Gold tips page shows odds for Gold edges, locks Diamond."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = _build_hot_tips_page(
                tips, page=0, user_tier="gold",
            )
        # Gold edge (Bulls vs Stormers) should show odds
        assert "1.65" in text
        # Diamond edge (Arsenal vs Chelsea) should be locked
        assert "Our highest-conviction pick." in text
        # Footer mentions Diamond locked count
        assert "Diamond" in text or "💎" in text

    def test_gold_no_subscribe_in_accessible_buttons(self):
        """Gold user's accessible edge buttons go to edge:detail, not sub:plans."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            _, markup = _build_hot_tips_page(
                tips, page=0, user_tier="gold",
            )
        callbacks = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data
        ]
        # Gold/Silver/Bronze edges should use edge:detail
        detail_callbacks = [cb for cb in callbacks if cb.startswith("edge:detail:")]
        assert len(detail_callbacks) >= 3  # Gold + Silver + Bronze


class TestDiamondJourney:
    """Diamond user: full access everywhere, zero locks, zero CTAs."""

    def test_diamond_full_access_all_tiers(self):
        """Diamond has full access to every edge tier."""
        from tier_gate import get_edge_access_level
        for tier in ("diamond", "gold", "silver", "bronze"):
            assert get_edge_access_level("diamond", tier) == "full"

    def test_diamond_zero_locks(self):
        """Diamond tips page has no lock indicators."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = _build_hot_tips_page(
                tips, page=0, user_tier="diamond",
            )
        assert "🔒" not in text
        assert "Our highest-conviction pick." not in text

    def test_diamond_zero_ctas(self):
        """Diamond tips page has no upgrade CTAs."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = _build_hot_tips_page(
                tips, page=0, user_tier="diamond",
            )
        assert "/subscribe" not in text
        assert "━━━" not in text
        assert "Unlock" not in text

    def test_diamond_all_buttons_are_detail(self):
        """Diamond user: every edge button goes to edge:detail."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            _, markup = _build_hot_tips_page(
                tips, page=0, user_tier="diamond",
            )
        edge_buttons = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data and (btn.callback_data.startswith("edge:") or btn.callback_data == "sub:plans")
        ]
        # All should be edge:detail, none should be sub:plans
        for cb in edge_buttons:
            assert cb.startswith("edge:detail:"), f"Diamond button goes to {cb}, not edge:detail"

    def test_diamond_sees_all_odds(self):
        """Diamond sees odds on every card."""
        tips = _multi_tier_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, _ = _build_hot_tips_page(
                tips, page=0, user_tier="diamond",
            )
        # All tips should show odds values
        assert "1.85" in text  # Diamond edge
        assert "1.65" in text  # Gold edge
        assert "2.40" in text  # Silver edge
        assert "2.80" in text  # Bronze edge
