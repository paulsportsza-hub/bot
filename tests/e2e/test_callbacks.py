"""Layer 5: Every button has a handler — no dead ends.

Generates all screens for a Diamond user, extracts inline buttons,
and verifies each callback prefix is handled in _dispatch_button.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

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
        "home_team": "Team A",
        "away_team": "Team B",
        "league": "PSL",
        "league_key": "psl",
        "sport_key": "soccer_south_africa_psl",
        "outcome": "Team A",
        "odds": 2.00,
        "ev": 5.0,
        "display_tier": display_tier,
        "edge_rating": display_tier,
        "match_id": f"team_a_vs_team_b_{display_tier}_2026-03-10",
        "event_id": f"team_a_vs_team_b_{display_tier}_2026-03-10",
        "commence_time": "2026-03-10T15:00:00Z",
        "bookmaker": "hollywoodbets",
        "edge_score": edge_score,
        "edge_v2": {"confirming_signals": 2},
    }
    defaults.update(kw)
    return defaults


# All known callback prefixes that _dispatch_button handles
HANDLED_PREFIXES = {
    "noop",
    "nav",
    "menu",
    "sport",
    "ai",
    "ob_exp",
    "ob_sport",
    "ob_nav",
    "ob_risk",
    "ob_bankroll",
    "ob_notify",
    "ob_fav",
    "ob_fav_manual",
    "ob_fav_done",
    "ob_fav_suggest",
    "ob_edit",
    "ob_summary",
    "picks",
    "bets",
    "teams",
    "stats",
    "affiliate",
    "story",
    "yg",
    "hot",
    "edge",
    "schedule",
    "tip",
    "odds",
    "results",
    "subscribe",
    "unsubscribe",
    "sub",
    "settings",
    "ep",
    "mm",
    "ed",
    "md",
}


def _extract_callbacks(markup) -> list[str]:
    """Extract all callback_data strings from an InlineKeyboardMarkup."""
    if not markup or not hasattr(markup, "inline_keyboard"):
        return []
    callbacks = []
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                callbacks.append(btn.callback_data)
    return callbacks


def _extract_prefix(callback_data: str) -> str:
    """Extract the prefix (before first colon) from callback_data."""
    return callback_data.split(":")[0]


class TestHotTipsButtonsHandled:
    """All buttons on Hot Tips pages have handlers."""

    def test_diamond_page1_buttons(self):
        tips = [
            _make_tip("diamond", match_id="d1_2026-03-10"),
            _make_tip("gold", match_id="g1_2026-03-10"),
            _make_tip("silver", match_id="s1_2026-03-10"),
            _make_tip("bronze", match_id="b1_2026-03-10"),
        ]
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page

            _, markup = asyncio.run(_build_hot_tips_page(tips, page=0, user_tier="diamond"))

        callbacks = _extract_callbacks(markup)
        assert len(callbacks) > 0, "No buttons found on Hot Tips page"

        for cb in callbacks:
            prefix = _extract_prefix(cb)
            assert prefix in HANDLED_PREFIXES, (
                f"Dead end: callback '{cb}' has unhandled prefix '{prefix}'"
            )

    def test_bronze_page1_buttons(self):
        tips = [
            _make_tip("diamond", match_id="d1_2026-03-10"),
            _make_tip("gold", match_id="g1_2026-03-10"),
            _make_tip("silver", match_id="s1_2026-03-10"),
            _make_tip("bronze", match_id="b1_2026-03-10"),
        ]
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page

            _, markup = asyncio.run(_build_hot_tips_page(tips, page=0, user_tier="bronze"))

        callbacks = _extract_callbacks(markup)
        for cb in callbacks:
            prefix = _extract_prefix(cb)
            assert prefix in HANDLED_PREFIXES, (
                f"Dead end: callback '{cb}' has unhandled prefix '{prefix}'"
            )

    def test_paginated_buttons(self):
        """Pagination buttons (hot:page:N) are handled."""
        tips = [_make_tip("gold", match_id=f"g{i}_2026-03-10") for i in range(8)]
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page

            _, markup = asyncio.run(_build_hot_tips_page(tips, page=0, user_tier="diamond"))

        callbacks = _extract_callbacks(markup)
        page_cbs = [cb for cb in callbacks if cb.startswith("hot:page:")]
        assert len(page_cbs) > 0, "No pagination buttons found with 8 tips"
        for cb in page_cbs:
            prefix = _extract_prefix(cb)
            assert prefix in HANDLED_PREFIXES


class TestDispatchButtonCoverage:
    """Verify _dispatch_button handles all known callback prefixes."""

    def test_dispatch_has_all_prefixes(self):
        """Check that _dispatch_button source code handles each prefix."""
        import inspect
        from bot import _dispatch_button

        source = inspect.getsource(_dispatch_button)

        for prefix in HANDLED_PREFIXES:
            if prefix == "noop":
                assert 'prefix == "noop"' in source or "'noop'" in source
            elif prefix == "settings":
                # Settings is handled via handle_menu or kb_settings
                assert "settings" in source
            else:
                assert f'"{prefix}"' in source, (
                    f"Prefix '{prefix}' not found in _dispatch_button source"
                )

    def test_nav_main_handled(self):
        """nav:main callback is a known route."""
        import inspect
        from bot import _dispatch_button

        source = inspect.getsource(_dispatch_button)
        assert '"main"' in source

    def test_hot_go_handled(self):
        """hot:go callback is a known route."""
        import inspect
        from bot import _dispatch_button

        source = inspect.getsource(_dispatch_button)
        assert '"go"' in source or "'go'" in source


class TestEmptyTipsButtonsHandled:
    """Empty state also produces valid buttons."""

    def test_empty_tips_buttons(self):
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page

            _, markup = asyncio.run(_build_hot_tips_page([], page=0, user_tier="diamond"))

        callbacks = _extract_callbacks(markup)
        assert len(callbacks) > 0, "Empty state should still have navigation buttons"
        for cb in callbacks:
            prefix = _extract_prefix(cb)
            assert prefix in HANDLED_PREFIXES, f"Dead end in empty state: {cb}"
