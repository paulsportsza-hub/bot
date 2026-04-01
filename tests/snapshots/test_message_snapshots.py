"""Layer 4: Output snapshot regression — golden file tests.

Calls _build_hot_tips_page, handle_tip_detail, and tier_gate rendering
with controlled data, then compares against golden JSON files.

First run creates golden files. Subsequent runs compare.
Use --snapshot-update to regenerate after intentional changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
from unittest.mock import MagicMock, patch

import pytest

# Force test env before importing app modules
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"
GOLDEN_DIR.mkdir(exist_ok=True)


# ── Fixtures ──────────────────────────────────────────────────


def _make_tip(
    home: str = "Mamelodi Sundowns",
    away: str = "Kaizer Chiefs",
    league: str = "PSL",
    league_key: str = "psl",
    sport_key: str = "soccer_south_africa_psl",
    outcome: str = "Sundowns",
    odds: float = 1.85,
    ev: float = 5.2,
    display_tier: str = "gold",
    match_id: str = "mamelodi_sundowns_vs_kaizer_chiefs_2026-03-10",
    event_id: str = "mamelodi_sundowns_vs_kaizer_chiefs_2026-03-10",
    commence_time: str = "2026-03-10T15:00:00Z",
    bookmaker: str = "hollywoodbets",
    edge_v2: dict | None = None,
) -> dict:
    edge_score = {
        "diamond": 62.0,
        "gold": 46.0,
        "silver": 39.0,
        "bronze": 22.0,
    }.get(display_tier, 40.0)
    edge_v2 = edge_v2 or {
        "match_key": match_id,
        "tier": display_tier,
        "composite_score": edge_score,
        "confirming_signals": 4 if display_tier in ("gold", "diamond") else 2,
        "contradicting_signals": 1 if display_tier in ("gold", "diamond") else 0,
        "edge_pct": ev,
        "best_bookmaker": bookmaker,
        "best_odds": odds,
        "signals": {
            "price_edge": {
                "available": True,
                "signal_strength": 0.82,
                "edge_pct": ev,
                "best_odds": odds,
                "best_bookmaker": bookmaker,
                "sharp_source": "pinnacle",
            },
            "market_agreement": {
                "available": True,
                "signal_strength": 0.71,
                "agreeing_bookmakers": 4,
                "total_bookmakers": 6,
            },
            "movement": {
                "available": True,
                "signal_strength": 0.69,
                "movement_pct": 2.4,
                "steam_confirms": True,
                "n_bks_moving": 3,
            },
            "form_h2h": {
                "available": True,
                "signal_strength": 0.66,
                "home_form_string": "WWDLW",
                "away_form_string": "LDWWW",
            },
            "tipster": {"available": False, "signal_strength": 0.5},
            "lineup_injury": {"available": False, "signal_strength": 0.5},
            "weather": {"available": False, "signal_strength": 0.5},
        },
    }
    return {
        "home_team": home,
        "away_team": away,
        "league": league,
        "league_key": league_key,
        "sport_key": sport_key,
        "outcome": outcome,
        "odds": odds,
        "ev": ev,
        "display_tier": display_tier,
        "edge_rating": display_tier,
        "edge_score": edge_score,
        "match_id": match_id,
        "event_id": event_id,
        "commence_time": commence_time,
        "bookmaker": bookmaker,
        "odds_by_bookmaker": {bookmaker: odds},
        "edge_v2": edge_v2,
    }


def _sample_tips() -> list[dict]:
    """8 tips spanning all 4 tiers for a realistic page."""
    return [
        _make_tip(display_tier="diamond", outcome="Sundowns", odds=1.85, ev=16.0,
                  match_id="sundowns_vs_chiefs_2026-03-10"),
        _make_tip(display_tier="gold", home="Arsenal", away="Chelsea",
                  league="Premier League", league_key="epl",
                  sport_key="soccer_epl", outcome="Arsenal", odds=2.10, ev=9.0,
                  match_id="arsenal_vs_chelsea_2026-03-10"),
        _make_tip(display_tier="gold", home="Bulls", away="Stormers",
                  league="URC", league_key="urc", sport_key="rugby_urc",
                  outcome="Bulls", odds=1.65, ev=8.5,
                  match_id="bulls_vs_stormers_2026-03-10"),
        _make_tip(display_tier="silver", home="Liverpool", away="Man City",
                  league="Premier League", league_key="epl",
                  sport_key="soccer_epl", outcome="Draw", odds=3.40, ev=5.1,
                  match_id="liverpool_vs_man_city_2026-03-10"),
        _make_tip(display_tier="silver", home="Sharks", away="Lions",
                  league="URC", league_key="urc", sport_key="rugby_urc",
                  outcome="Sharks", odds=1.90, ev=4.8,
                  match_id="sharks_vs_lions_2026-03-10"),
        _make_tip(display_tier="bronze", home="Orlando Pirates", away="Stellenbosch",
                  league="PSL", league_key="psl",
                  sport_key="soccer_south_africa_psl", outcome="Pirates", odds=2.30, ev=2.1,
                  match_id="orlando_pirates_vs_stellenbosch_2026-03-10"),
        _make_tip(display_tier="bronze", home="Real Madrid", away="Barcelona",
                  league="La Liga", league_key="la_liga",
                  sport_key="soccer_spain_la_liga", outcome="Madrid", odds=2.50, ev=1.5,
                  match_id="real_madrid_vs_barcelona_2026-03-10"),
        _make_tip(display_tier="bronze", home="India", away="Australia",
                  league="T20 World Cup", league_key="t20_world_cup",
                  sport_key="cricket_t20_world_cup", outcome="India", odds=1.70, ev=1.2,
                  match_id="india_vs_australia_2026-03-10"),
    ]


def _make_settled_edge(
    match_key: str,
    *,
    result: str = "hit",
    edge_tier: str = "gold",
    league: str = "psl",
    sport: str = "soccer",
    bet_type: str = "Home Win",
    recommended_odds: float = 2.10,
    actual_return: float = 210.0,
    match_date: str = "2026-03-13",
) -> dict:
    return {
        "match_key": match_key,
        "result": result,
        "edge_tier": edge_tier,
        "league": league,
        "sport": sport,
        "bet_type": bet_type,
        "recommended_odds": recommended_odds,
        "actual_return": actual_return,
        "match_date": match_date,
    }


def _snapshot_data(text: str, markup) -> dict:
    """Serialise text + InlineKeyboardMarkup to a comparable dict."""
    buttons = []
    if markup and hasattr(markup, "inline_keyboard"):
        for row in markup.inline_keyboard:
            buttons.append([
                {"text": btn.text, "callback_data": btn.callback_data or "", "url": btn.url or ""}
                for btn in row
            ])
    return {"text": text, "buttons": buttons}


def _load_or_create_golden(name: str, actual: dict) -> dict:
    """Load golden file or create it on first run. Returns golden data."""
    path = GOLDEN_DIR / f"{name}.json"
    if path.exists() and os.environ.get("UPDATE_JSON_SNAPSHOTS") != "1":
        return json.loads(path.read_text())
    # First run or explicit refresh: create golden file
    path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n")
    return actual


# ── Broadcast/portfolio mocks ────────────────────────────────

_BROADCAST_PATCH = patch("bot._get_broadcast_details", return_value={"broadcast": "", "kickoff": "Sat 10 Mar · 17:30"})
_PORTFOLIO_PATCH = patch("bot._get_portfolio_line", return_value="📈 <b>R100 on our top 5</b> → R487 total return")
_FOUNDING_PATCH = patch("bot._founding_days_left", return_value=8)
# W84-Q9: tier_gate computes founding days independently — patch at source for date-stability
_TIER_GATE_FOUNDING_PATCH = patch(
    "tier_gate._founding_member_line",
    return_value="\n🎁 Founding Member: R699/yr Diamond — 8 days left",
)


# ── Tests ─────────────────────────────────────────────────────


class TestHotTipsHeader:
    """Snapshot: Hot Tips header block above and below hit-rate threshold."""

    def test_header_above_threshold(self):
        """Header with hit rate >= 50% shows percentage."""
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            tips = _sample_tips()[:4]
            text, markup = asyncio.run(_build_hot_tips_page(
                tips, page=0, user_tier="diamond",
                hit_rate_7d=62.0, resource_count=347043,
            ))
        actual = _snapshot_data(text, markup)
        golden = _load_or_create_golden("header_above_threshold", actual)
        assert actual["text"] == golden["text"], (
            f"Header snapshot mismatch.\n\nACTUAL:\n{actual['text']}\n\nGOLDEN:\n{golden['text']}"
        )


class TestResultProofHotTips:
    """Snapshot: Hot Tips page with track-record proof, yesterday block, and settled badges."""

    def test_page_with_result_proof(self):
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            tips = _sample_tips()[:4]
            text, markup = asyncio.run(_build_hot_tips_page(
                tips,
                page=0,
                user_tier="diamond",
                hit_rate_7d=38.0,
                resource_count=347043,
                last_10_results=["hit", "miss", "hit", "hit", "miss", "hit", "miss", "hit", "hit", "miss"],
                roi_7d=-4.2,
                recently_settled=[
                    _make_settled_edge("kaizer_chiefs_vs_orlando_pirates_2026-03-13"),
                    _make_settled_edge(
                        "mamelodi_sundowns_vs_cape_town_city_2026-03-13",
                        result="miss",
                        edge_tier="bronze",
                        bet_type="Away Win",
                        recommended_odds=1.80,
                        actual_return=0.0,
                    ),
                ],
                yesterday_results=[
                    _make_settled_edge("kaizer_chiefs_vs_orlando_pirates_2026-03-13"),
                    _make_settled_edge(
                        "mamelodi_sundowns_vs_cape_town_city_2026-03-13",
                        result="miss",
                        edge_tier="bronze",
                        bet_type="Away Win",
                        recommended_odds=1.80,
                        actual_return=0.0,
                    ),
                ],
            ))
        actual = _snapshot_data(text, markup)
        golden = _load_or_create_golden("page_with_result_proof", actual)
        assert actual["text"] == golden["text"]

    def test_header_below_threshold(self):
        """Header with hit rate < 50% shows edge count instead."""
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            tips = _sample_tips()[:4]
            text, markup = asyncio.run(_build_hot_tips_page(
                tips, page=0, user_tier="diamond",
                hit_rate_7d=38.0, resource_count=347043,
            ))
        actual = _snapshot_data(text, markup)
        golden = _load_or_create_golden("header_below_threshold", actual)
        assert actual["text"] == golden["text"], (
            f"Header snapshot mismatch.\n\nACTUAL:\n{actual['text']}\n\nGOLDEN:\n{golden['text']}"
        )


class TestEdgeCardAccessLevels:
    """Snapshot: Edge card at each access level (full, partial, blurred, locked)."""

    def _build_single_card(self, user_tier: str, edge_tier: str) -> dict:
        """Build a page with 1 tip and return snapshot data."""
        tip = _make_tip(display_tier=edge_tier, odds=2.10, ev=10.0)
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = asyncio.run(_build_hot_tips_page(
                [tip], page=0, user_tier=user_tier,
                hit_rate_7d=0.0, resource_count=100000,
            ))
        return _snapshot_data(text, markup)

    def test_card_full_access(self):
        """Diamond user viewing gold edge = full access card."""
        actual = self._build_single_card("diamond", "gold")
        golden = _load_or_create_golden("card_full_access", actual)
        assert actual["text"] == golden["text"]

    def test_card_partial_access(self):
        """Bronze user viewing silver edge = partial access card."""
        actual = self._build_single_card("bronze", "silver")
        golden = _load_or_create_golden("card_partial_access", actual)
        assert actual["text"] == golden["text"]

    def test_card_blurred_access(self):
        """Bronze user viewing gold edge = blurred card."""
        actual = self._build_single_card("bronze", "gold")
        golden = _load_or_create_golden("card_blurred_access", actual)
        assert actual["text"] == golden["text"]

    def test_card_locked_access(self):
        """Bronze user viewing diamond edge = locked card."""
        actual = self._build_single_card("bronze", "diamond")
        golden = _load_or_create_golden("card_locked_access", actual)
        assert actual["text"] == golden["text"]


class TestFooterCTA:
    """Snapshot: Footer CTA block for each tier."""

    def test_bronze_footer_with_locks(self):
        """Bronze footer shows locked count + portfolio + subscribe."""
        tips = _sample_tips()  # Mix of tiers
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = asyncio.run(_build_hot_tips_page(
                tips[:4], page=0, user_tier="bronze",
                consecutive_misses=0,
                hit_rate_7d=55.0, resource_count=347043,
            ))
        actual = _snapshot_data(text, markup)
        golden = _load_or_create_golden("footer_bronze_locks", actual)
        assert actual["text"] == golden["text"]

    def test_bronze_footer_losing_streak(self):
        """Bronze footer with 3+ misses shows educational message."""
        tips = _sample_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = asyncio.run(_build_hot_tips_page(
                tips[:4], page=0, user_tier="bronze",
                consecutive_misses=4,
                hit_rate_7d=55.0, resource_count=347043,
            ))
        actual = _snapshot_data(text, markup)
        golden = _load_or_create_golden("footer_bronze_losing_streak", actual)
        assert actual["text"] == golden["text"]

    def test_gold_footer_diamond_locked(self):
        """Gold footer shows Diamond locked count."""
        tips = _sample_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = asyncio.run(_build_hot_tips_page(
                tips[:4], page=0, user_tier="gold",
                hit_rate_7d=55.0, resource_count=347043,
            ))
        actual = _snapshot_data(text, markup)
        golden = _load_or_create_golden("footer_gold_diamond_locked", actual)
        assert actual["text"] == golden["text"]

    def test_diamond_no_footer(self):
        """Diamond has no footer CTA."""
        tips = _sample_tips()
        with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
            from bot import _build_hot_tips_page
            text, markup = asyncio.run(_build_hot_tips_page(
                tips[:4], page=0, user_tier="diamond",
                hit_rate_7d=55.0, resource_count=347043,
            ))
        actual = _snapshot_data(text, markup)
        golden = _load_or_create_golden("footer_diamond_none", actual)
        assert actual["text"] == golden["text"]
        # Diamond should never have ━━━ divider or /subscribe
        assert "━━━" not in text
        assert "/subscribe" not in text


class TestDetailView:
    """Snapshot: Detail view for full-access edge."""

    def test_locked_detail_view(self):
        """Locked detail shows plan comparison, no bookmaker link."""
        with _TIER_GATE_FOUNDING_PATCH:
            from tier_gate import get_edge_access_level, get_upgrade_message
            access = get_edge_access_level("bronze", "diamond")
            assert access == "locked"
            msg = get_upgrade_message("bronze", context="diamond_edge")
        golden = _load_or_create_golden("detail_locked_bronze_diamond", {"text": msg})
        assert msg == golden["text"]

    def test_blurred_detail_view(self):
        """Blurred detail shows plan comparison for Gold edge."""
        with _TIER_GATE_FOUNDING_PATCH:
            from tier_gate import get_upgrade_message
            msg = get_upgrade_message("bronze", context="gold_edge")
        golden = _load_or_create_golden("detail_blurred_bronze_gold", {"text": msg})
        assert msg == golden["text"]


class TestSanitizeAiResponse:
    """Snapshot: sanitize_ai_response produces stable output."""

    def test_sanitize_markdown_input(self):
        """AI response with markdown is sanitised to stable HTML."""
        from bot import sanitize_ai_response
        raw = (
            "## The Setup\n"
            "**Arsenal** are in fine form with WDWWW.\n"
            "# The Edge\n"
            "The bookies have undervalued the draw.\n"
            "## The Risk\n"
            "- Key player rotation possible\n"
            "- Weather could play a role\n"
            "## Verdict\n"
            "Back the draw with Medium conviction.\n"
        )
        result = sanitize_ai_response(raw)
        golden = _load_or_create_golden("sanitize_markdown", {"text": result})
        assert result == golden["text"]

    def test_sanitize_clean_input(self):
        """Already-clean input with section emojis passes through."""
        from bot import sanitize_ai_response
        raw = (
            "📋 <b>The Setup</b>\n"
            "Arsenal sit 2nd in the table.\n\n"
            "🎯 <b>The Edge</b>\n"
            "Value on the draw at 3.40.\n\n"
            "⚠️ <b>The Risk</b>\n"
            "Derby day unpredictability.\n\n"
            "🏆 <b>Verdict</b>\n"
            "Draw is the pick."
        )
        result = sanitize_ai_response(raw)
        golden = _load_or_create_golden("sanitize_clean", {"text": result})
        assert result == golden["text"]
