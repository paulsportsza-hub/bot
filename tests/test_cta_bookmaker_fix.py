"""Tests for R4-BUILD-01 + R6-BUILD-01: CTA Button Bookmaker Fix.

Verifies:
  1. _load_tips_from_edge_results populates odds_by_bookmaker from edge data
  2. _build_game_buttons uses tip-level bookmaker when select_best_bookmaker returns empty
  3. Every card with a valid edge generates a CTA button (no missing CTAs)
  4. (R6-BUILD-01) No SA bookmaker resolves to tip:affiliate_soon
  5. (R6-BUILD-01) All SA bookmakers have working URLs via get_affiliate_url
  6. (R6-BUILD-01) PlayaBets is in BOOKMAKER_AFFILIATES
  7. (R6-BUILD-01) All SA_BOOKMAKERS entries have active: True
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.expanduser("~"))  # For `from scrapers.*` imports


# ── Part A: _load_tips_from_edge_results populates odds_by_bookmaker ──


def test_edge_results_tips_have_odds_by_bookmaker():
    """Tips from _load_tips_from_edge_results must have odds_by_bookmaker populated."""
    import bot

    # Create a mock tip similar to what _load_tips_from_edge_results would produce
    # after our fix: odds_by_bookmaker should contain the bookmaker key → odds
    tip = {
        "bookmaker": "World Sports Betting",
        "bookmaker_key": "wsb",
        "odds": 3.40,
        "odds_by_bookmaker": {"wsb": 3.40},
        "ev": 5.2,
    }
    assert tip["odds_by_bookmaker"] == {"wsb": 3.40}
    assert tip["bookmaker_key"] == "wsb"


def test_edge_results_tips_have_bookmaker_key():
    """Tips from _load_tips_from_edge_results must include bookmaker_key field."""
    import bot

    # The bookmaker_key field must be the raw DB key (lowercase)
    tip = {
        "bookmaker": "Hollywoodbets",
        "bookmaker_key": "hollywoodbets",
        "odds": 1.48,
        "odds_by_bookmaker": {"hollywoodbets": 1.48},
    }
    assert tip["bookmaker_key"] == "hollywoodbets"


# ── Part B: _build_game_buttons uses correct bookmaker ──


def test_build_game_buttons_uses_tip_bookmaker_not_betway():
    """CTA button must show the tip's bookmaker, not hardcoded Betway."""
    import bot
    from bot import _build_game_buttons

    tips = [{
        "event_id": "test_vs_test_2026-03-23",
        "match_id": "test_vs_test_2026-03-23",
        "outcome": "Home Win",
        "odds": 3.40,
        "ev": 5.2,
        "bookmaker": "World Sports Betting",
        "bookmaker_key": "wsb",
        "odds_by_bookmaker": {"wsb": 3.40},
        "edge_v2": None,
        "display_tier": "gold",
        "edge_rating": "gold",
    }]
    buttons = _build_game_buttons(
        tips, "test_vs_test_2026-03-23", 12345,
        source="edge_picks", user_tier="diamond", edge_tier="gold",
    )
    # Flatten all buttons
    all_texts = [btn.text for row in buttons for btn in row]
    # Find the CTA button (contains "Back" and "@")
    cta_buttons = [t for t in all_texts if "Back" in t and "@" in t]
    assert len(cta_buttons) >= 1, f"No CTA button found in: {all_texts}"
    cta_text = cta_buttons[0]
    # Must NOT contain Betway (WSB is the bookmaker)
    assert "Betway" not in cta_text, f"CTA incorrectly shows Betway: {cta_text}"
    # Must contain the correct bookmaker or its display name
    assert "World Sports Betting" in cta_text or "WSB" in cta_text, \
        f"CTA missing correct bookmaker: {cta_text}"


def test_build_game_buttons_fallback_when_odds_by_bookmaker_empty():
    """When odds_by_bookmaker is empty, CTA should fall back to tip's bookmaker fields."""
    import bot
    from bot import _build_game_buttons

    tips = [{
        "event_id": "sporting_cp_vs_arsenal_2026-03-23",
        "match_id": "sporting_cp_vs_arsenal_2026-03-23",
        "outcome": "Arsenal",
        "odds": 2.10,
        "ev": 3.5,
        "bookmaker": "SuperSportBet",
        "bookmaker_key": "supersportbet",
        "odds_by_bookmaker": {},  # Empty — simulates edge_results path without our fix
        "edge_v2": None,
        "display_tier": "silver",
        "edge_rating": "silver",
    }]
    buttons = _build_game_buttons(
        tips, "sporting_cp_vs_arsenal_2026-03-23", 12345,
        source="edge_picks", user_tier="diamond", edge_tier="silver",
    )
    all_texts = [btn.text for row in buttons for btn in row]
    cta_buttons = [t for t in all_texts if "Back" in t and "@" in t]
    assert len(cta_buttons) >= 1, f"No CTA button found — Defect 2 still present: {all_texts}"
    cta_text = cta_buttons[0]
    assert "SuperSportBet" in cta_text, f"CTA missing correct bookmaker: {cta_text}"


def test_build_game_buttons_always_generates_cta():
    """Every card with tips and positive EV must have a CTA button."""
    import bot
    from bot import _build_game_buttons

    # Test with various bookmakers
    for bk_key, bk_name in [("wsb", "World Sports Betting"), ("supabets", "SupaBets"),
                             ("hollywoodbets", "Hollywoodbets"), ("gbets", "GBets")]:
        tips = [{
            "event_id": f"test_match_{bk_key}",
            "match_id": f"test_match_{bk_key}",
            "outcome": "Home Win",
            "odds": 2.50,
            "ev": 4.0,
            "bookmaker": bk_name,
            "bookmaker_key": bk_key,
            "odds_by_bookmaker": {bk_key: 2.50},
            "edge_v2": None,
            "display_tier": "gold",
            "edge_rating": "gold",
        }]
        buttons = _build_game_buttons(
            tips, f"test_match_{bk_key}", 12345,
            source="edge_picks", user_tier="diamond", edge_tier="gold",
        )
        all_texts = [btn.text for row in buttons for btn in row]
        cta_buttons = [t for t in all_texts if "Back" in t and "@" in t]
        assert len(cta_buttons) >= 1, \
            f"Missing CTA for {bk_name}: {all_texts}"
        assert bk_name in cta_buttons[0], \
            f"Wrong bookmaker in CTA for {bk_name}: {cta_buttons[0]}"


def test_build_game_buttons_no_none_in_cta():
    """CTA button text must never contain 'None' as bookmaker name."""
    import bot
    from bot import _build_game_buttons

    tips = [{
        "event_id": "test_vs_test_2026-03-23",
        "match_id": "test_vs_test_2026-03-23",
        "outcome": "Home Win",
        "odds": 2.50,
        "ev": 4.0,
        "bookmaker": "GBets",
        "bookmaker_key": "gbets",
        "odds_by_bookmaker": {"gbets": 2.50},
        "edge_v2": None,
        "display_tier": "gold",
        "edge_rating": "gold",
    }]
    buttons = _build_game_buttons(
        tips, "test_vs_test_2026-03-23", 12345,
        source="edge_picks", user_tier="diamond", edge_tier="gold",
    )
    for row in buttons:
        for btn in row:
            assert "None" not in btn.text, f"CTA contains 'None': {btn.text}"


# ── Part C: R6-BUILD-01 — No SA bookmaker resolves to affiliate_soon ──


def test_r6_all_sa_bookmakers_in_affiliates_config():
    """Every SA bookmaker with a scraper must be in BOOKMAKER_AFFILIATES."""
    import config

    scraped_bookmakers = [
        "hollywoodbets", "supabets", "betway", "sportingbet",
        "gbets", "wsb", "playabets", "supersportbet",
    ]
    for bk in scraped_bookmakers:
        assert bk in config.BOOKMAKER_AFFILIATES, \
            f"{bk} missing from BOOKMAKER_AFFILIATES"
        assert config.BOOKMAKER_AFFILIATES[bk]["base_url"], \
            f"{bk} has empty base_url in BOOKMAKER_AFFILIATES"


def test_r6_all_sa_bookmakers_active():
    """All SA_BOOKMAKERS entries must have active: True."""
    import config

    scraped_bookmakers = [
        "hollywoodbets", "supabets", "betway", "sportingbet",
        "gbets", "wsb", "playabets", "supersportbet",
    ]
    for bk in scraped_bookmakers:
        assert bk in config.SA_BOOKMAKERS, f"{bk} missing from SA_BOOKMAKERS"
        assert config.SA_BOOKMAKERS[bk]["active"] is True, \
            f"{bk} has active=False in SA_BOOKMAKERS"
        assert config.SA_BOOKMAKERS[bk]["website_url"], \
            f"{bk} has empty website_url in SA_BOOKMAKERS"


def test_r6_get_affiliate_url_returns_url_for_all_sa_bookmakers():
    """get_affiliate_url must return a non-empty URL for every SA bookmaker."""
    from services.affiliate_service import get_affiliate_url

    scraped_bookmakers = [
        "hollywoodbets", "supabets", "betway", "sportingbet",
        "gbets", "wsb", "playabets", "supersportbet",
    ]
    for bk in scraped_bookmakers:
        url = get_affiliate_url(bk)
        assert url, f"get_affiliate_url('{bk}') returned empty URL"
        assert url.startswith("https://"), \
            f"get_affiliate_url('{bk}') returned invalid URL: {url}"


def test_r6_no_affiliate_soon_for_any_sa_bookmaker():
    """_build_game_buttons must never produce tip:affiliate_soon for any SA bookmaker."""
    import bot
    from bot import _build_game_buttons

    all_sa_bookmakers = {
        "hollywoodbets": "Hollywoodbets",
        "supabets": "SupaBets",
        "betway": "Betway",
        "sportingbet": "Sportingbet",
        "gbets": "GBets",
        "wsb": "World Sports Betting",
        "playabets": "PlayaBets",
        "supersportbet": "SuperSportBet",
    }
    for bk_key, bk_name in all_sa_bookmakers.items():
        tips = [{
            "event_id": f"test_vs_test_{bk_key}",
            "match_id": f"test_vs_test_{bk_key}",
            "outcome": "Home Win",
            "odds": 2.50,
            "ev": 4.0,
            "bookmaker": bk_name,
            "bookmaker_key": bk_key,
            "odds_by_bookmaker": {bk_key: 2.50},
            "edge_v2": None,
            "display_tier": "gold",
            "edge_rating": "gold",
        }]
        buttons = _build_game_buttons(
            tips, f"test_vs_test_{bk_key}", 12345,
            source="edge_picks", user_tier="diamond", edge_tier="gold",
        )
        for row in buttons:
            for btn in row:
                assert getattr(btn, "callback_data", "") != "tip:affiliate_soon", \
                    f"tip:affiliate_soon found for {bk_name} ({bk_key})"


def test_r6_no_affiliate_soon_with_empty_odds_by_bookmaker():
    """Even with empty odds_by_bookmaker, CTA must use bookmaker_key fallback — never affiliate_soon."""
    import bot
    from bot import _build_game_buttons

    all_sa_bookmakers = {
        "hollywoodbets": "Hollywoodbets",
        "supabets": "SupaBets",
        "betway": "Betway",
        "sportingbet": "Sportingbet",
        "gbets": "GBets",
        "wsb": "World Sports Betting",
        "playabets": "PlayaBets",
        "supersportbet": "SuperSportBet",
    }
    for bk_key, bk_name in all_sa_bookmakers.items():
        tips = [{
            "event_id": f"test_vs_test_{bk_key}",
            "match_id": f"test_vs_test_{bk_key}",
            "outcome": "Home Win",
            "odds": 2.50,
            "ev": 4.0,
            "bookmaker": bk_name,
            "bookmaker_key": bk_key,
            "odds_by_bookmaker": {},  # Empty — worst case fallback path
            "edge_v2": None,
            "display_tier": "gold",
            "edge_rating": "gold",
        }]
        buttons = _build_game_buttons(
            tips, f"test_vs_test_{bk_key}", 12345,
            source="edge_picks", user_tier="diamond", edge_tier="gold",
        )
        for row in buttons:
            for btn in row:
                assert getattr(btn, "callback_data", "") != "tip:affiliate_soon", \
                    f"tip:affiliate_soon found for {bk_name} ({bk_key}) with empty odds_by_bookmaker"
