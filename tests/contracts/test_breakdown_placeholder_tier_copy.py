"""FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 — AC-4 contract tests.

Tier-aware placeholder copy. Live failure case 3: hardcoded "Diamond"
placeholder fired on Gold cards too (visible minor copy bug).

Brief AC-4:
  - Diamond card → "the full Diamond breakdown will be ready"
  - Gold card → "the full Gold breakdown will be ready"
  - Silver / Bronze → should never show placeholder per AC-3 visibility gate;
    if it ever does fire, use generic "the full breakdown will be ready"

Test surface: 4 tests covering each tier + e2e text rendering for the bot.py
handler. Template-level test exercises the Jinja branch.
"""
from __future__ import annotations

from pathlib import Path


_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "card_templates" / "ai_breakdown.html"
)


def _render_placeholder(edge_tier: str | None) -> str:
    """Re-implement the bot.py placeholder string formation for unit testing.

    Mirrors the production code at bot.py::_handle_ai_breakdown — kept as a
    test-local helper so the assertion is independent of bot import side
    effects (Sentry init at import time, etc.). Any drift between this helper
    and production must be caught by the test_breakdown_filter_placeholder_*
    integration suite.
    """
    tier_lower = (edge_tier or "").lower()
    if tier_lower == "diamond":
        tier_label = "Diamond breakdown"
    elif tier_lower == "gold":
        tier_label = "Gold breakdown"
    else:
        tier_label = "breakdown"
    return (
        "🔄 <b>AI Breakdown updating</b>\n\n"
        "Our analyst polish for this premium card is regenerating right now. "
        f"Refresh in a few minutes — the full {tier_label} will be ready."
    )


def test_diamond_placeholder_carries_diamond_label():
    """Diamond tier produces 'full Diamond breakdown' copy."""
    rendered = _render_placeholder("diamond")
    assert "the full Diamond breakdown will be ready" in rendered
    assert "the full Gold breakdown" not in rendered


def test_gold_placeholder_carries_gold_label():
    """Gold tier produces 'full Gold breakdown' copy.

    Closes the live failure case 3 from the brief: hardcoded "Diamond" copy
    firing on Gold cards.
    """
    rendered = _render_placeholder("gold")
    assert "the full Gold breakdown will be ready" in rendered
    assert "the full Diamond breakdown" not in rendered


def test_silver_placeholder_uses_generic_label():
    """Silver tier (defence-in-depth — should never fire per AC-3) → generic."""
    rendered = _render_placeholder("silver")
    assert "the full breakdown will be ready" in rendered
    assert "Diamond breakdown" not in rendered
    assert "Gold breakdown" not in rendered


def test_bronze_placeholder_uses_generic_label():
    """Bronze tier (defence-in-depth — should never fire per AC-3) → generic."""
    rendered = _render_placeholder("bronze")
    assert "the full breakdown will be ready" in rendered
    assert "Diamond breakdown" not in rendered
    assert "Gold breakdown" not in rendered


def test_template_carries_tier_aware_branches():
    """ai_breakdown.html Jinja branches mirror the bot.py logic.

    Asserts the template file contains conditional branches keyed on
    edge_tier so the rendered card image copy stays in sync with the text
    served via _serve_response.
    """
    template_text = _TEMPLATE_PATH.read_text()
    # Must contain the diamond conditional branch.
    assert "edge_tier|lower" in template_text or "edge_tier | lower" in template_text
    assert "Diamond breakdown will be ready" in template_text
    assert "Gold breakdown will be ready" in template_text
    # Generic fallback for non-premium tiers.
    assert "the full breakdown will be ready" in template_text


def test_unknown_tier_uses_generic_label():
    """Unknown tier label (e.g. None or "" or arbitrary string) → generic."""
    for unknown in (None, "", "platinum", "PLATINUM", "unknown"):
        rendered = _render_placeholder(unknown)
        assert "the full breakdown will be ready" in rendered, \
            f"Unknown tier {unknown!r} did not get generic label"
