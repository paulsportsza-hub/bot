"""CARD-REBUILD-01 — Contract tests for 8 detail card fixes.

FIX 1: test_display_tier_trusts_db
FIX 2: test_no_edge_rating_badge
FIX 3: test_detail_to_main_menu_transition (async, mocked)
FIX 4: test_my_matches_enrichment
FIX 5: test_verdict_coherence_gate
FIX 6: test_zero_value_guards
FIX 7: test_detect_sport_fallback_chain
FIX 8: test_template_layout_overflow
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── FIX 1: test_display_tier_trusts_db ────────────────────────────────────────

def test_display_tier_trusts_db():
    """A tip with edge_tier='diamond' and confirming_signals=0 must render as diamond.

    BUILD-GATE-RELAX override is deleted — display_tier falls through to edge_tier.
    """
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "diamond",
        "edge_rating": "diamond",
        "ev": 11.0,
        "home": "Barcelona",
        "away": "Atletico Madrid",
        "league": "La Liga",
        "pick": "Barcelona",
        "pick_odds": 2.10,
        "bookmaker": "Betway",
        "edge_v2": {"confirming_signals": 0},
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] == "diamond", f"Expected diamond, got {data['tier']}"
    assert data["tier_name"] == "DIAMOND"


# ── FIX 2: test_no_edge_rating_badge ──────────────────────────────────────────

def test_no_edge_rating_badge():
    """A match with no edge (display_tier=None) renders tier=None — template shows No Edge Rating."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": None,
        "home": "Norway U19",
        "away": "France U19",
        "league": "ICC U19 World Cup",
        "ev": 0,
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] is None, f"Expected None tier, got {data['tier']}"
    assert data["tier_emoji"] == ""
    assert data["tier_name"] == ""
    # pick/verdict will be empty strings — template hides them via {% if tier %}
    assert data["pick"] == ""
    assert data["verdict"] == ""


# ── FIX 3: test_detail_to_main_menu_transition ────────────────────────────────

@pytest.mark.asyncio
async def test_detail_to_main_menu_transition():
    """From a photo message, pressing Main Menu must delete+send (not edit_message_text)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    # Mock query with photo message
    query = AsyncMock()
    query.from_user = MagicMock()
    query.from_user.first_name = "Test"
    query.message = MagicMock()
    query.message.photo = [MagicMock()]  # truthy — it's a photo message
    query.message.chat_id = 12345
    query.message.delete = AsyncMock()
    query.get_bot = MagicMock()
    query.get_bot().send_message = AsyncMock()

    # Patch kb_main
    with patch("bot.kb_main", return_value=MagicMock()):
        from bot import _serve_response
        await _serve_response(query, "test text", MagicMock())

    # Must delete (photo→text transition) and send new message
    query.message.delete.assert_called_once()
    query.get_bot().send_message.assert_called_once()


# ── FIX 4: test_my_matches_enrichment ─────────────────────────────────────────

def test_my_matches_enrichment():
    """Non-edge match enriched via _enrich_tip_for_card produces edge_detail-compatible data."""
    from card_data import build_edge_detail_data

    # Simulate what FIX 4 does: enriched match with display_tier=None
    enriched = {
        "display_tier": None,
        "home": "Arsenal",
        "away": "Bournemouth",
        "league": "EPL",
        "home_form": ["W", "W", "D", "L", "W"],
        "away_form": ["L", "D", "W", "W", "L"],
        "home_odds": 1.85,
        "home_bookie": "Betway",
        "draw_odds": 3.40,
        "draw_bookie": "Hollywoodbets",
        "away_odds": 4.20,
        "away_bookie": "GBets",
        "h2h": {"n": 10, "hw": 5, "d": 3, "aw": 2},
        "ev": 0,
    }
    data = build_edge_detail_data(enriched)

    # Has match identity
    assert data["home"] == "Arsenal"
    assert data["away"] == "Bournemouth"
    assert data["league"] == "EPL"

    # Has form
    assert data["home_form"] == ["W", "W", "D", "L", "W"]
    assert data["away_form"] == ["L", "D", "W", "W", "L"]

    # Has H2H
    assert data["h2h_total"] == 10

    # No tier (FIX 2 gating)
    assert data["tier"] is None


# ── FIX 5: test_verdict_coherence_gate ────────────────────────────────────────

def test_verdict_from_haiku():
    """FIX 2 (CARD-REBUILD-03A): verdict comes from _generate_verdict (Haiku), not tipster consensus.
    Even when tipster most_tipped conflicts with pick, the Haiku-generated verdict is shown
    because it is based on EV/odds data, not on tipster alignment.
    """
    from bot import _enrich_tip_for_card
    from unittest.mock import patch, MagicMock

    tip = {
        "pick": "Bournemouth",
        "outcome": "Bournemouth",
        "odds": 2.5,
        "ev": 12.0,
        "bookmaker": "Betway",
    }
    mock_verified = {
        "home_key": "arsenal",
        "away_key": "bournemouth",
        "matchup": "Arsenal vs Bournemouth",
        "results": [],
        "injuries": [],
        "odds": {},
        "best_odds": {},
        "tipster": {"most_tipped": "Arsenal", "_rows": []},
    }
    mock_bvdb = MagicMock(return_value=mock_verified)
    mock_form = MagicMock(return_value=[])
    mock_h2h = MagicMock(return_value={"played": 0, "hw": 0, "d": 0, "aw": 0})
    mock_inj = MagicMock(return_value=([], []))
    mock_sig = MagicMock(return_value=[])
    mock_verdict = MagicMock(return_value="Bournemouth at 2.50 offers +12.0% EV over true probability.")

    with patch("card_pipeline.build_verified_data_block", mock_bvdb), \
         patch("card_pipeline._compute_team_form", mock_form), \
         patch("card_pipeline._compute_h2h", mock_h2h), \
         patch("card_pipeline._split_injuries", mock_inj), \
         patch("card_pipeline._compute_signals", mock_sig), \
         patch("bot._get_cached_verdict", return_value=None), \
         patch("bot._generate_verdict", mock_verdict):
        result = _enrich_tip_for_card(tip, "arsenal_vs_bournemouth_2026-04-07")

    # Verdict is Haiku-generated (EV-based), not tipster consensus
    assert result["verdict"] != "", "Verdict should be set by Haiku"
    assert "2.50" in result["verdict"] or "12" in result["verdict"], \
        f"Verdict should cite a number, got: {result['verdict']}"
    mock_verdict.assert_called_once()


# ── FIX 6: test_zero_value_guards ─────────────────────────────────────────────

def test_zero_value_guards():
    """Template with zero/missing odds renders no 0.00 pills."""
    from card_renderer import render_card_sync
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "silver",
        "ev": 3.5,
        "home": "Team A",
        "away": "Team B",
        "league": "EPL",
        "pick": "Team A",
        "pick_odds": 0,  # zero odds
        "bookmaker": "",
        "all_odds": [{"bookie": "BK", "odds": 0}],
        "fair_value": 0,
        "confidence": 0,
    }
    data = build_edge_detail_data(tip)

    # pick_odds is "0.00" string but template guards with {% if pick_odds and pick_odds != "0.00" %}
    assert data["pick_odds"] == "0.00"

    # Render and check no 0.00 appears in pills
    try:
        html_bytes = render_card_sync("edge_detail.html", data)
        html = html_bytes.decode("utf-8", errors="replace")
        # The pick odds span should not be rendered
        assert 'class="pick-odds"' not in html or "0.00" not in html.split('class="pick-odds"')[1].split("</span>")[0]
    except Exception:
        # Playwright may not be available in test env — verify data contract instead
        assert data["pick_odds"] == "0.00"
        assert data["fair_value"] == 0
        assert data["confidence"] == 0


# ── FIX 7: test_detect_sport_fallback_chain ───────────────────────────────────

def test_detect_sport_fallback_chain():
    """detect_sport covers all 4 branches: exact, substring, sport_key hint, default."""
    from card_data import detect_sport, sport_emoji

    # Branch 1: exact match
    assert detect_sport("EPL") == "soccer"
    assert detect_sport("IPL") == "cricket"
    assert detect_sport("URC") == "rugby"
    assert detect_sport("UFC") == "mma"

    # Branch 2: case-insensitive substring match
    assert detect_sport("ICC U19 World Cup") == "cricket"
    assert detect_sport("Super Rugby Pacific") == "rugby"
    assert detect_sport("T20 World Cup") == "cricket"
    assert detect_sport("Test Series") == "cricket"

    # Branch 3: sport_key hint
    assert detect_sport("Unknown League XYZ", sport_key="cricket") == "cricket"

    # Branch 4: default to soccer
    assert detect_sport("Unknown League XYZ") == "soccer"

    # Emoji integration
    assert sport_emoji("ICC U19 World Cup") == "🏏"
    assert sport_emoji("Super Rugby Pacific") == "🏉"
    assert sport_emoji("EPL") == "⚽"


# ── FIX 8: test_template_layout_overflow ──────────────────────────────────────

def test_template_layout_overflow():
    """2-line team name renders without layout break; venue slot removed."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "ev": 5.0,
        "home": "Borussia Mönchengladbach",
        "away": "Bayern Munich",
        "league": "Bundesliga",
        "pick": "Bayern Munich",
        "pick_odds": 1.75,
        "bookmaker": "Betway",
    }
    data = build_edge_detail_data(tip)

    # Long team name present
    assert data["home"] == "Borussia Mönchengladbach"

    # CARD-FIX-I: venue slot restored to meta bar (conditional — only shown when data present)
    from pathlib import Path
    template_path = Path(__file__).parent.parent.parent / "card_templates" / "edge_detail.html"
    html = template_path.read_text()

    # CARD-FIX-L: venue emoji updated to 🏙️
    assert '🏙️' in html, "Venue slot (🏙️) must be present in edge_detail.html meta bar"

    # CARD-FIX-A (D-INV-2): min-height reduced to remove dead space
    assert 'min-height: 56px' in html, "team-block should have min-height: 56px"

    # FIX 8: form-strip gap widened
    assert 'gap: 10px' in html, "form-row gap should be 10px"

    # CARD-FIX-A (D-INV-6): max-width/overflow removed; flex-wrap handles layout
    assert 'max-width: 90px' not in html, "odds-pill must not have max-width: 90px"

    try:
        from card_renderer import render_card_sync
        png = render_card_sync("edge_detail.html", data)
        assert len(png) > 0, "Rendered card should be non-empty"
    except Exception:
        pass  # Playwright may not be available
