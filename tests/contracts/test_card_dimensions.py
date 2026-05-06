"""Contract test: card template dimension variants.

BUILD-CARD-DIMENSIONS-LOCK-01
Validates that every template in card_templates/ belongs to a declared variant
and that its .card CSS matches the variant spec.

  Variant DETAIL — fixed 480×620: edge_detail.html and fixed-card peers
  Variant LIST   — dynamic 480×N: list/adaptive detail templates

Failing tests mean:
  test_template_in_declared_variant  → a new template was added without declaring its variant
  test_detail_variant_fixed_dims     → a DETAIL template lost its fixed 480×620 .card rule
  test_list_variant_no_fixed_height  → a LIST template gained a fixed .card height

Validated by: card_renderer.py module docstring ## Canonical Card Dimensions section.
"""

import os
import re

import pytest

_TEMPLATE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "card_templates")
)

DETAIL_TEMPLATES = {
    "edge_detail.html",
    # BUILD-WAVE1-SUB-01
    "sub_plans.html",
    "sub_founding_live.html",
    # BUILD-HOME-WINNERS-CARD-01
    "home_winners.html",
    # BUILD-ONBOARDING-HYPE-PACK-01
    "onboarding_done.html",
    # BUILD-SETTINGS-SPORTS-CARD-01
    "settings_sports.html",
    # FIX-ZERO-TEXT-SETTINGS-HOME-01
    "settings_home.html",
}
LIST_TEMPLATES = {
    "edge_picks.html",
    "edge_picks_index.html",
    "match_detail.html",  # FIX-CARD-MATCH-CANONICAL-FAMILY-01: canonical adaptive LIST variant
    "my_matches.html",
    "edge_summary.html",
    "tier_page.html",
    # ai_breakdown.html archived under BUILD-VERDICT-ONLY-STRIP-AI-BREAKDOWN-01
    # BUILD-WAVE1-SUB-01
    "sub_upgrade_bronze.html",
    "sub_upgrade_gold.html",
    "sub_upgrade_diamond_max.html",
    "sub_payment_ready.html",
    "sub_payment_error.html",
    "sub_email_redirect.html",
    "sub_status_active.html",
    "sub_status_bronze.html",
    "sub_billing_active.html",
    "sub_billing_inactive.html",
    "sub_cancel_confirm.html",
    "sub_cancel_done.html",
    "sub_payment_confirmed.html",
    "sub_founding_confirmed.html",
    "sub_founding_soldout.html",
    "sub_founding_ended.html",
    "sub_expiry_notice.html",
    "sub_trial_expiry.html",
    # BUILD-WAVE2-ONBOARDING-01
    "onboarding_welcome.html",
    "onboarding_experience.html",
    "onboarding_sports.html",
    "onboarding_favourites.html",
    "onboarding_favourites_manual.html",
    "onboarding_fuzzy_suggest.html",
    "onboarding_team_celebration.html",
    "onboarding_edge_explainer.html",
    "onboarding_risk.html",
    "onboarding_bankroll.html",
    "onboarding_bankroll_custom.html",
    "onboarding_notify.html",
    "onboarding_summary.html",
    "story_quiz_step.html",
    "story_quiz_complete.html",
    "onboarding_restart.html",
    # BUILD-PROFILE-CARD-01
    "profile_home.html",
    # BUILD-MY-TEAMS-CARD-01
    "my_teams.html",
    # BUILD-HELP-CARD-01
    "help.html",
    # BUILD-BOOKMAKER-DIRECTORY-CARD-01
    "bookmaker_directory.html",
    # BUILD-HELP-CARD-01
    "help.html",
    # WAVE-G2-CANONICAL-LIFT-01
    "tier_lock_upsell.html",
    # FIX-ZERO-TEXT-EMPTY-STATES-01
    "edge_picks_empty.html",
    "live_games_empty.html",
    # FIX-ZERO-TEXT-GUIDE-MENU-01
    "guide_menu.html",
    # FIX-ZERO-TEXT-SUBSCRIBE-EDGE-CASES-01
    "sub_already_active.html",
    "sub_plan_invalid.html",
    "sub_founding_disclosure.html",
}
ALL_DECLARED = DETAIL_TEMPLATES | LIST_TEMPLATES

DETAIL_WIDTH_PX = 480
DETAIL_HEIGHT_PX = 620


def _discover_templates():
    return sorted(f for f in os.listdir(_TEMPLATE_DIR) if f.endswith(".html"))


def _card_css_block(html: str) -> str:
    """Return the body of the first .card { ... } rule in the HTML."""
    m = re.search(r"\.card\s*\{([^}]+)\}", html, re.DOTALL)
    return m.group(1) if m else ""


def _css_property(block: str, prop: str) -> str | None:
    """Return the value of a CSS property from a rule block, or None if absent."""
    m = re.search(rf"{prop}\s*:\s*([^;]+);", block)
    return m.group(1).strip() if m else None


# ── Parametrize over all discovered templates ─────────────────────────────────

@pytest.mark.parametrize("template", _discover_templates())
def test_template_in_declared_variant(template):
    """Every template must be listed in DETAIL_TEMPLATES or LIST_TEMPLATES."""
    assert template in ALL_DECLARED, (
        f"'{template}' is not declared in either DETAIL_TEMPLATES or LIST_TEMPLATES.\n"
        "Add it to the correct variant in test_card_dimensions.py AND update the\n"
        "## Canonical Card Dimensions docstring in card_renderer.py."
    )


@pytest.mark.parametrize("template", sorted(DETAIL_TEMPLATES))
def test_detail_variant_fixed_dims(template):
    """DETAIL templates must have .card { width: 480px; height: 620px }."""
    path = os.path.join(_TEMPLATE_DIR, template)
    block = _card_css_block(open(path).read())
    assert block, f"{template}: no .card CSS rule found"

    width = _css_property(block, "width")
    height = _css_property(block, "height")

    assert width == f"{DETAIL_WIDTH_PX}px", (
        f"{template} [DETAIL]: expected .card width: {DETAIL_WIDTH_PX}px, got '{width}'"
    )
    assert height == f"{DETAIL_HEIGHT_PX}px", (
        f"{template} [DETAIL]: expected .card height: {DETAIL_HEIGHT_PX}px, got '{height}'.\n"
        "Changing this would break the DETAIL variant — see BUILD-CARD-DIMENSIONS-LOCK-01.\n"
        "Example failure trigger: changing height to 700px would fail this assertion."
    )


@pytest.mark.parametrize("template", sorted(LIST_TEMPLATES))
def test_list_variant_no_fixed_height(template):
    """LIST templates must NOT declare a fixed height on .card (dynamic height)."""
    path = os.path.join(_TEMPLATE_DIR, template)
    block = _card_css_block(open(path).read())
    assert block, f"{template}: no .card CSS rule found"

    height = _css_property(block, "height")
    assert height is None, (
        f"{template} [LIST]: .card has fixed height '{height}' but LIST variant requires\n"
        "dynamic height (no .card height declaration).\n"
        "Remove the height property to restore dynamic measurement.\n"
        "See BUILD-CARD-DIMENSIONS-LOCK-01."
    )


# ── Bookmaker row single-line guarantee (FIX-REGRESS-D1-BOOKMAKER-LINE-01) ────

def _bookie_chips_row_css(html: str) -> str:
    """Return the CSS block for .bookie-chips-row."""
    m = re.search(r"\.bookie-chips-row\s*\{([^}]+)\}", html, re.DOTALL)
    return m.group(1) if m else ""


def test_edge_detail_bookie_row_nowrap():
    """edge_detail.html .bookie-chips-row must have flex-wrap: nowrap."""
    path = os.path.join(_TEMPLATE_DIR, "edge_detail.html")
    block = _bookie_chips_row_css(open(path).read())
    assert block, "edge_detail.html: no .bookie-chips-row CSS rule found"
    wrap_val = _css_property(block, "flex-wrap")
    assert wrap_val == "nowrap", (
        f"edge_detail.html .bookie-chips-row: expected flex-wrap: nowrap, got '{wrap_val}'.\n"
        "Wrap must be impossible — FIX-REGRESS-D1-BOOKMAKER-LINE-01."
    )


def test_edge_detail_bookie_row_overflow_hidden():
    """edge_detail.html .bookie-chips-row must have overflow: hidden."""
    path = os.path.join(_TEMPLATE_DIR, "edge_detail.html")
    block = _bookie_chips_row_css(open(path).read())
    assert block, "edge_detail.html: no .bookie-chips-row CSS rule found"
    overflow_val = _css_property(block, "overflow")
    assert overflow_val == "hidden", (
        f"edge_detail.html .bookie-chips-row: expected overflow: hidden, got '{overflow_val}'.\n"
        "Overflow must be hidden to prevent wrapping — FIX-REGRESS-D1-BOOKMAKER-LINE-01."
    )


def test_build_edge_detail_data_max_bookmakers_at_480():
    """build_edge_detail_data at 480px returns at most 4 bookmakers."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "ev": 5.0,
        "home": "Chiefs",
        "away": "Pirates",
        "all_odds": [
            {"bookie": "Betway",        "odds": 1.80, "is_pick": True},
            {"bookie": "Hollywoodbets", "odds": 1.78},
            {"bookie": "SupaBets",      "odds": 1.75},
            {"bookie": "GBets",         "odds": 1.72},
            {"bookie": "Sportingbet",   "odds": 1.70},
            {"bookie": "WSB",           "odds": 1.68},
        ],
    }
    data = build_edge_detail_data(tip, card_width=480)
    assert len(data["all_odds"]) <= 4, (
        f"Expected ≤4 bookmakers at 480px, got {len(data['all_odds'])}"
    )


def test_build_edge_detail_data_max_bookmakers_at_360():
    """build_edge_detail_data at 360px returns at most 3 bookmakers."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "all_odds": [
            {"bookie": "A", "odds": 1.80},
            {"bookie": "B", "odds": 1.78},
            {"bookie": "C", "odds": 1.75},
            {"bookie": "D", "odds": 1.72},
        ],
    }
    data = build_edge_detail_data(tip, card_width=360)
    assert len(data["all_odds"]) <= 3, (
        f"Expected ≤3 bookmakers at 360px, got {len(data['all_odds'])}"
    )


def test_build_edge_detail_data_injuries_line_populated():
    """important_injuries is always empty on Edge Detail cards (FIX-INJURY-SUPPRESS-01)."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "home_injuries": [{"player": "Saka", "reason": "hamstring"}],
        "away_injuries": [{"player": "Salah", "reason": "doubt"}],
    }
    data = build_edge_detail_data(tip)
    assert data["important_injuries"] == "", (
        "important_injuries must always be empty on Edge Detail cards (FIX-INJURY-SUPPRESS-01)"
    )


def test_build_edge_detail_data_injuries_line_empty_when_no_injuries():
    """important_injuries is empty string when no injury data present."""
    from card_data import build_edge_detail_data

    tip = {"display_tier": "gold", "home_injuries": [], "away_injuries": []}
    data = build_edge_detail_data(tip)
    assert data["important_injuries"] == "", (
        "important_injuries must be empty string — no placeholder allowed"
    )


def test_build_match_detail_data_injuries_passthrough():
    """home_injuries and away_injuries pass through from match dict (BUILD-MM-INJURY-RESTORE-01)."""
    from card_data import build_match_detail_data

    home = [{"player": "Saka", "reason": "hamstring"}]
    away = [{"player": "Salah", "reason": "doubt"}, {"player": "Diaz", "reason": "knock"}]
    match = {"home_injuries": home, "away_injuries": away}
    data = build_match_detail_data(match)
    assert data["home_injuries"] == home, (
        "home_injuries must pass through from match dict (BUILD-MM-INJURY-RESTORE-01)"
    )
    assert data["away_injuries"] == away, (
        "away_injuries must pass through from match dict (BUILD-MM-INJURY-RESTORE-01)"
    )


def test_build_match_detail_data_injuries_default_empty_when_absent():
    """home_injuries and away_injuries default to [] when match dict omits them."""
    from card_data import build_match_detail_data

    data = build_match_detail_data({})
    assert data["home_injuries"] == []
    assert data["away_injuries"] == []
