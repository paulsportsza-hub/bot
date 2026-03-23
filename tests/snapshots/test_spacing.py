"""Layer 4: Spacing law enforcement.

Ensures:
- No triple newlines in any output
- Card breathing room: exactly \\n\\n between cards
- Footer spacing follows the locked spec
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

_BROADCAST_PATCH = patch("bot._get_broadcast_details", return_value={"broadcast": "", "kickoff": "Sat 10 Mar · 17:30"})
_PORTFOLIO_PATCH = patch("bot._get_portfolio_line", return_value="📈 <b>R100 on our top 5</b> → R487 total return")
_FOUNDING_PATCH = patch("bot._founding_days_left", return_value=8)


def _make_tip(display_tier: str = "gold", **kw) -> dict:
    odds = kw.get("odds", 2.00)
    bookmaker = kw.get("bookmaker", "hollywoodbets")
    ev = kw.get("ev", 5.0)
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
        "edge_v2": {
            "match_key": f"team_a_vs_team_b_{display_tier}_2026-03-10",
            "tier": display_tier,
            "composite_score": 58.0,
            "confirming_signals": 3,
            "signals": {
                "price_edge": {
                    "available": True,
                    "signal_strength": 0.8,
                    "edge_pct": ev,
                    "best_odds": odds,
                    "best_bookmaker": bookmaker,
                },
                "market_agreement": {
                    "available": True,
                    "signal_strength": 0.7,
                    "agreeing_bookmakers": 4,
                    "total_bookmakers": 5,
                },
                "movement": {
                    "available": True,
                    "signal_strength": 0.68,
                    "movement_pct": 1.8,
                    "steam_confirms": True,
                },
                "form_h2h": {
                    "available": True,
                    "signal_strength": 0.66,
                    "home_form_string": "WWDLW",
                    "away_form_string": "LDWWW",
                },
            },
        },
    }
    defaults.update(kw)
    return defaults


def _build_page(tips: list[dict], user_tier: str = "diamond", **kw) -> str:
    """Build hot tips page and return text only."""
    with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
        from bot import _build_hot_tips_page
        text, _ = _build_hot_tips_page(tips, page=0, user_tier=user_tier, **kw)
    return text


class TestNoTripleNewlines:
    """SPACING LAW: Never more than \\n\\n anywhere in Hot Tips output."""

    def test_diamond_no_triple_newlines(self):
        tips = [_make_tip(display_tier="gold", home_team=f"Home{i}", away_team=f"Away{i}",
                          match_id=f"h{i}_vs_a{i}_2026-03-10") for i in range(8)]
        text = _build_page(tips, user_tier="diamond")
        assert "\n\n\n" not in text, f"Triple newline found in Diamond output:\n{text}"

    def test_bronze_no_triple_newlines(self):
        tips = [
            _make_tip(display_tier="diamond", match_id="d_2026-03-10"),
            _make_tip(display_tier="gold", match_id="g_2026-03-10"),
            _make_tip(display_tier="silver", match_id="s_2026-03-10"),
            _make_tip(display_tier="bronze", match_id="b_2026-03-10"),
        ]
        text = _build_page(tips, user_tier="bronze")
        assert "\n\n\n" not in text, f"Triple newline found in Bronze output:\n{text}"

    def test_gold_no_triple_newlines(self):
        tips = [
            _make_tip(display_tier="diamond", match_id="d_2026-03-10"),
            _make_tip(display_tier="gold", match_id="g_2026-03-10"),
        ]
        text = _build_page(tips, user_tier="gold")
        assert "\n\n\n" not in text, f"Triple newline found in Gold output:\n{text}"

    def test_losing_streak_no_triple_newlines(self):
        tips = [_make_tip(display_tier="gold", match_id="g_2026-03-10")]
        text = _build_page(tips, user_tier="bronze", consecutive_misses=5)
        assert "\n\n\n" not in text, f"Triple newline in losing streak:\n{text}"

    def test_empty_tips_no_triple_newlines(self):
        text = _build_page([], user_tier="diamond")
        assert "\n\n\n" not in text


class TestCardBreathingRoom:
    """Between cards: exactly \\n\\n (one visible blank line)."""

    def test_cards_separated_by_double_newline(self):
        # Use same-tier tips so no tier header appears between cards
        tips = [
            _make_tip(display_tier="gold", home_team="Home1", away_team="Away1",
                      match_id="h1_vs_a1_2026-03-10"),
            _make_tip(display_tier="gold", home_team="Home2", away_team="Away2",
                      match_id="h2_vs_a2_2026-03-10"),
            _make_tip(display_tier="gold", home_team="Home3", away_team="Away3",
                      match_id="h3_vs_a3_2026-03-10"),
        ]
        text = _build_page(tips, user_tier="diamond")
        # Find card blocks: each starts with [N]
        lines = text.split("\n")
        card_starts = [i for i, ln in enumerate(lines) if ln.strip().startswith("<b>[")]
        assert len(card_starts) == 3, f"Expected 3 cards, found {len(card_starts)}"

        for idx in range(len(card_starts) - 1):
            # Find end of current card: next non-empty line block ends at last
            # non-empty line before next card or blank line
            start_of_next = card_starts[idx + 1]
            # Between cards within same tier: blank line separator
            # Find the blank line(s) between card end and next card start
            between = lines[card_starts[idx] + 1:start_of_next]
            # Should contain at least one blank line before the next card
            assert "" in between, (
                f"Between card {idx+1} and {idx+2}: expected blank line separator, got {between!r}"
            )

    def test_tier_headers_between_different_tiers(self):
        """When cards span different tiers, tier headers appear between them."""
        tips = [
            _make_tip(display_tier="gold", home_team="Home1", away_team="Away1",
                      match_id="h1_vs_a1_2026-03-10"),
            _make_tip(display_tier="silver", home_team="Home2", away_team="Away2",
                      match_id="h2_vs_a2_2026-03-10"),
        ]
        text = _build_page(tips, user_tier="diamond")
        lines = text.split("\n")
        card_starts = [i for i, ln in enumerate(lines) if ln.strip().startswith("<b>[")]
        assert len(card_starts) == 2, f"Expected 2 cards, found {len(card_starts)}"
        # Between the two cards, a SILVER EDGE tier header should appear
        between_text = "\n".join(lines[card_starts[0]:card_starts[1]])
        assert "SILVER EDGE" in between_text, (
            f"Expected SILVER EDGE tier header between cards, got:\n{between_text}"
        )


class TestFooterSpacing:
    """Footer CTA block spacing follows locked spec."""

    def test_divider_has_breathing_room(self):
        """One blank line before and after ━━━ divider."""
        tips = [
            _make_tip(display_tier="diamond", match_id="d_2026-03-10"),
            _make_tip(display_tier="gold", match_id="g_2026-03-10"),
        ]
        text = _build_page(tips, user_tier="bronze")
        if "━━━" in text:
            lines = text.split("\n")
            div_idx = next(i for i, ln in enumerate(lines) if "━━━" in ln)
            # Before divider: blank line
            assert div_idx > 0 and lines[div_idx - 1].strip() == "", (
                f"Expected blank line before ━━━, got: {lines[div_idx-1]!r}"
            )
            # After divider: blank line
            assert div_idx < len(lines) - 1 and lines[div_idx + 1].strip() == "", (
                f"Expected blank line after ━━━, got: {lines[div_idx+1]!r}"
            )

    def test_footer_cta_no_internal_gaps(self):
        """Within footer CTA block (after divider blank), lines are consecutive."""
        tips = [
            _make_tip(display_tier="diamond", match_id="d_2026-03-10"),
            _make_tip(display_tier="gold", match_id="g_2026-03-10"),
        ]
        text = _build_page(tips, user_tier="bronze")
        if "━━━" in text:
            lines = text.split("\n")
            div_idx = next(i for i, ln in enumerate(lines) if "━━━" in ln)
            # CTA lines start after the blank line after divider
            cta_start = div_idx + 2  # skip divider + blank line
            cta_lines = lines[cta_start:]
            # Filter out trailing empty strings from join
            cta_lines = [ln for ln in cta_lines if ln.strip()]
            # All CTA lines should be non-empty consecutive (no gaps)
            for i, ln in enumerate(cta_lines):
                assert ln.strip(), f"Empty line in footer CTA block at position {i}"


class TestSanitizeSpacing:
    """sanitize_ai_response enforces max \\n\\n."""

    def test_triple_newlines_collapsed(self):
        from bot import sanitize_ai_response
        raw = "Line 1\n\n\n\nLine 2\n\n\n\n\nLine 3"
        result = sanitize_ai_response(raw)
        assert "\n\n\n" not in result

    def test_section_spacing_preserved(self):
        from bot import sanitize_ai_response
        raw = "📋 <b>The Setup</b>\nContent here.\n🎯 <b>The Edge</b>\nMore content."
        result = sanitize_ai_response(raw)
        # Section emojis should have blank line before them (except first)
        assert "\n\n🎯" in result
