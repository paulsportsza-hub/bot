"""Tests for picks functionality — EV calculation, value bet scanning, pick cards, admin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot
import config
import db
from scripts.odds_client import (
    OddsEntry,
    ValueBet,
    calculate_ev,
    ev_confidence,
    fair_probabilities,
    find_best_odds,
    format_pick_card,
    get_quota,
    kelly_stake,
    scan_value_bets,
)


# ── Sample fixtures ───────────────────────────────────────

SAMPLE_EVENT = {
    "id": "abc123",
    "sport_key": "soccer_epl",
    "commence_time": "2025-03-01T15:00:00Z",
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "bookmakers": [
        {
            "key": "bet365",
            "title": "Bet365",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Arsenal", "price": 2.10},
                        {"name": "Chelsea", "price": 3.40},
                        {"name": "Draw", "price": 3.05},
                    ],
                }
            ],
        },
        {
            "key": "hollywoodbets",
            "title": "Hollywoodbets",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Arsenal", "price": 2.30},
                        {"name": "Chelsea", "price": 3.20},
                        {"name": "Draw", "price": 3.10},
                    ],
                }
            ],
        },
        {
            "key": "betway",
            "title": "Betway",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Arsenal", "price": 2.15},
                        {"name": "Chelsea", "price": 3.35},
                        {"name": "Draw", "price": 3.00},
                    ],
                }
            ],
        },
    ],
}


# ── EV calculation tests ─────────────────────────────────

class TestCalculateEV:
    def test_positive_ev(self):
        # If fair prob is 0.5 and odds are 2.20, EV = (2.20*0.5 - 1)*100 = 10%
        ev = calculate_ev(2.20, 0.5)
        assert abs(ev - 10.0) < 0.01

    def test_negative_ev(self):
        # If fair prob is 0.4 and odds are 2.00, EV = (2.0*0.4 - 1)*100 = -20%
        ev = calculate_ev(2.00, 0.4)
        assert ev < 0

    def test_zero_ev(self):
        ev = calculate_ev(2.00, 0.5)
        assert abs(ev) < 0.01

    def test_high_ev(self):
        ev = calculate_ev(3.00, 0.5)
        assert ev > 40


class TestKellyStake:
    def test_positive_edge(self):
        # odds=2.20, prob=0.5: b=1.2, kelly = (1.2*0.5 - 0.5)/1.2 = 0.1/1.2
        ks = kelly_stake(2.20, 0.5)
        assert ks > 0
        assert ks < 1

    def test_negative_edge_returns_zero(self):
        ks = kelly_stake(1.50, 0.3)
        assert ks == 0.0

    def test_fractional_kelly(self):
        full = kelly_stake(2.20, 0.5, fraction=1.0)
        half = kelly_stake(2.20, 0.5, fraction=0.5)
        assert abs(half - full * 0.5) < 0.001

    def test_zero_odds_returns_zero(self):
        ks = kelly_stake(1.0, 0.5)  # b = 0
        assert ks == 0.0


class TestEVConfidence:
    def test_high(self):
        assert "High" in ev_confidence(10.0)

    def test_medium(self):
        assert "Medium" in ev_confidence(5.0)

    def test_low(self):
        assert "Low" in ev_confidence(2.0)


# ── Fair probability tests ────────────────────────────────

class TestFairProbabilities:
    def test_returns_normalised(self):
        probs = fair_probabilities(SAMPLE_EVENT)
        assert len(probs) == 3
        total = sum(probs.values())
        assert abs(total - 1.0) < 0.01

    def test_empty_event(self):
        probs = fair_probabilities({"bookmakers": []})
        assert probs == {}

    def test_no_bookmakers(self):
        probs = fair_probabilities({})
        assert probs == {}


# ── Find best odds tests ─────────────────────────────────

class TestFindBestOdds:
    def test_returns_correct_best(self):
        entries = find_best_odds(SAMPLE_EVENT)
        by_name = {e.outcome: e for e in entries}
        # Arsenal best is 2.30 from Hollywoodbets
        assert by_name["Arsenal"].price == 2.30
        assert by_name["Arsenal"].bookmaker == "Hollywoodbets"

    def test_sa_bookmaker_flag(self):
        entries = find_best_odds(SAMPLE_EVENT)
        by_name = {e.outcome: e for e in entries}
        # Hollywoodbets was removed from SA_BOOKMAKERS whitelist (now 5 books)
        # Arsenal best is from Hollywoodbets which is no longer SA
        assert by_name["Arsenal"].is_sa_book is False
        # Draw best is from Hollywoodbets (3.10) — also not SA
        assert by_name["Draw"].is_sa_book is False

    def test_non_sa_bookmaker(self):
        entries = find_best_odds(SAMPLE_EVENT)
        by_name = {e.outcome: e for e in entries}
        # Chelsea best is 3.40 from Bet365 (not SA)
        assert by_name["Chelsea"].is_sa_book is False

    def test_sa_bookmaker_betway(self):
        """Betway (in SA_BOOKMAKERS whitelist) is flagged correctly."""
        event = {
            "bookmakers": [
                {
                    "key": "betway", "title": "Betway",
                    "markets": [{"key": "h2h", "outcomes": [
                        {"name": "Team A", "price": 3.00},
                    ]}],
                },
            ],
        }
        entries = find_best_odds(event)
        assert entries[0].is_sa_book is True

    def test_empty_event(self):
        entries = find_best_odds({"bookmakers": []})
        assert entries == []


# ── Event with clear value (outlier bookmaker) ───────────

VALUE_EVENT = {
    "id": "val123",
    "sport_key": "soccer_epl",
    "commence_time": "2025-03-01T15:00:00Z",
    "home_team": "Liverpool",
    "away_team": "Everton",
    "bookmakers": [
        {
            "key": "bet365",
            "title": "Bet365",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Liverpool", "price": 1.80},
                {"name": "Everton", "price": 5.00},
                {"name": "Draw", "price": 3.50},
            ]}],
        },
        {
            "key": "betway",
            "title": "Betway",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Liverpool", "price": 1.75},
                {"name": "Everton", "price": 4.80},
                {"name": "Draw", "price": 3.40},
            ]}],
        },
        {
            # Outlier bookmaker with much higher Everton odds → value bet
            "key": "hollywoodbets",
            "title": "Hollywoodbets",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Liverpool", "price": 1.78},
                {"name": "Everton", "price": 7.50},
                {"name": "Draw", "price": 3.45},
            ]}],
        },
    ],
}


# ── Scan value bets tests ─────────────────────────────────

class TestScanValueBets:
    def test_finds_value_bets(self):
        picks = scan_value_bets([VALUE_EVENT], "soccer", min_ev=0.0)
        assert len(picks) > 0
        assert all(isinstance(p, ValueBet) for p in picks)

    def test_filters_by_min_ev(self):
        all_picks = scan_value_bets([VALUE_EVENT], "soccer", min_ev=0.0)
        high_picks = scan_value_bets([VALUE_EVENT], "soccer", min_ev=50.0)
        assert len(high_picks) <= len(all_picks)

    def test_sorted_by_ev_descending(self):
        picks = scan_value_bets([VALUE_EVENT], "soccer", min_ev=0.0)
        if len(picks) >= 2:
            for i in range(len(picks) - 1):
                assert picks[i].ev_pct >= picks[i + 1].ev_pct

    def test_empty_events(self):
        picks = scan_value_bets([], "soccer")
        assert picks == []

    def test_value_bet_fields(self):
        picks = scan_value_bets([VALUE_EVENT], "soccer", min_ev=0.0)
        assert len(picks) > 0
        p = picks[0]
        assert p.home == "Liverpool"
        assert p.away == "Everton"
        assert p.sport_key == "soccer"
        assert p.best_price > 0
        assert p.bookmaker != ""
        assert p.confidence != ""

    def test_efficient_market_no_value(self):
        """An efficient market (SAMPLE_EVENT) should produce few/no value bets at high min_ev."""
        picks = scan_value_bets([SAMPLE_EVENT], "soccer", min_ev=5.0)
        assert len(picks) == 0


# ── Format pick card tests ────────────────────────────────

class TestFormatPickCard:
    def test_contains_match_info(self):
        pick = ValueBet(
            home="Arsenal", away="Chelsea", sport_key="soccer",
            outcome="Arsenal", best_price=2.30, bookmaker="Hollywoodbets",
            is_sa_book=True, fair_prob=0.45, ev_pct=3.5,
            kelly_stake=0.05, confidence="🟡 Medium",
        )
        card = format_pick_card(pick)
        assert "Arsenal" in card
        assert "Chelsea" in card
        assert "2.30" in card
        assert "Hollywoodbets" in card
        assert "EV" in card

    def test_sa_bookmaker_shown(self):
        pick = ValueBet(
            home="A", away="B", sport_key="soccer",
            outcome="A", best_price=2.0, bookmaker="Betway.co.za",
            is_sa_book=True, fair_prob=0.5, ev_pct=5.0,
            kelly_stake=0.05, confidence="🟡 Medium",
        )
        card = format_pick_card(pick)
        assert "Betway.co.za" in card

    def test_non_sa_bookmaker_shown(self):
        pick = ValueBet(
            home="A", away="B", sport_key="soccer",
            outcome="A", best_price=2.0, bookmaker="Bet365",
            is_sa_book=False, fair_prob=0.5, ev_pct=5.0,
            kelly_stake=0.05, confidence="🟡 Medium",
        )
        card = format_pick_card(pick)
        assert "Bet365" in card

    def test_html_formatted(self):
        pick = ValueBet(
            home="A", away="B", sport_key="soccer",
            outcome="A", best_price=2.0, bookmaker="Bet365",
            is_sa_book=False, fair_prob=0.5, ev_pct=5.0,
            kelly_stake=0.05, confidence="🟡 Medium",
        )
        card = format_pick_card(pick)
        assert "<b>" in card
        assert "<code>" in card


# ── Quota tracking tests ─────────────────────────────────

class TestQuota:
    def test_get_quota_returns_dict(self):
        q = get_quota()
        assert "requests_used" in q
        assert "requests_remaining" in q


# ── Bot handler tests ────────────────────────────────────

pytestmark = pytest.mark.asyncio


async def test_cmd_picks_no_prefs(test_db, mock_update, mock_context):
    """Picks with no user prefs should still work (uses all sports)."""
    await db.upsert_user(77777, "picker", "Picker")
    await db.set_onboarding_done(77777)
    mock_update.effective_user.id = 77777
    mock_update.effective_chat.id = 77777

    no_picks_result = {
        "ok": False, "picks": [], "total_events": 0, "total_markets": 0,
        "total_scanned": 0, "quota_remaining": "499", "errors": None,
    }
    with patch("bot.get_picks_for_user", new_callable=AsyncMock, return_value=no_picks_result):
        await bot.cmd_picks(mock_update, mock_context)

    assert mock_context.bot.send_message.call_count >= 1


async def test_cmd_picks_with_prefs(test_db, mock_update, mock_context):
    """Picks should respect user sport preferences."""
    await db.upsert_user(77778, "picker2", "Picker2")
    await db.update_user_risk(77778, "aggressive")
    await db.save_sport_pref(77778, "soccer", league="epl")
    mock_update.effective_user.id = 77778
    mock_update.effective_chat.id = 77778

    pick_result = {
        "ok": True,
        "picks": [{
            "event_id": "abc123", "sport_key": "soccer",
            "home_team": "Arsenal", "away_team": "Chelsea",
            "commence_time": "2026-02-23T15:00:00Z",
            "market": "h2h", "outcome": "Arsenal",
            "odds": 2.30, "bookmaker": "Hollywoodbets",
            "bookmaker_key": "hollywoodbets", "is_sa_bookmaker": True,
            "ev": 5.3, "confidence": 45, "sharp_prob": 45.0,
            "stake": 150.0, "potential_return": 345.0, "profit": 195.0,
            "all_odds": [], "confidence_label": "🟡 Medium",
        }],
        "total_events": 5, "total_markets": 15, "total_scanned": 1,
        "quota_remaining": "498", "errors": None,
    }
    with patch("bot.get_picks_for_user", new_callable=AsyncMock, return_value=pick_result):
        await bot.cmd_picks(mock_update, mock_context)

    # Should have: loading deleted, header, pick card, footer
    assert mock_context.bot.send_message.call_count >= 2


async def test_cmd_admin_shows_quota(test_db, mock_update, mock_context):
    """Admin command should show API quota."""
    mock_update.effective_user.id = config.ADMIN_IDS[0]

    await bot.cmd_admin(mock_update, mock_context)

    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Admin Dashboard" in text
    assert "Quota" in text
    assert "requests" in text.lower()


async def test_cmd_admin_non_admin_ignored(test_db, mock_update, mock_context):
    """Non-admin should be ignored by /admin."""
    mock_update.effective_user.id = 999
    await bot.cmd_admin(mock_update, mock_context)
    mock_update.message.reply_text.assert_not_called()


async def test_handle_picks_go(test_db, mock_update, mock_context):
    """picks:go callback should trigger picks flow."""
    await db.upsert_user(77779, "picker3", "Picker3")
    query = mock_update.callback_query
    query.from_user.id = 77779
    query.message.chat_id = 77779

    no_picks_result = {
        "ok": False, "picks": [], "total_events": 0, "total_markets": 0,
        "total_scanned": 0, "quota_remaining": "499", "errors": None,
    }
    with patch("bot.get_picks_for_user", new_callable=AsyncMock, return_value=no_picks_result):
        await bot.handle_picks(query, mock_context, "go")

    assert mock_context.bot.send_message.call_count >= 1
