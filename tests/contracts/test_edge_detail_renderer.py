"""Contract tests for edge_detail_renderer — CLEAN-RENDER-v2.

Verifies structural guarantees:
- ONE source per field (no dual paths)
- Gating correctness by access level
- Sport section dispatch
- No duplicate sections
- EV/tier/signal consistency
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()


# ── Fixtures ─────────────────────────────────────────────────

def _make_edge_row(**overrides) -> dict:
    """Build a synthetic edge_results row."""
    base = {
        "match_key": "arsenal_vs_tottenham_2026-03-26",
        "edge_tier": "gold",
        "composite_score": 72.5,
        "bet_type": "home",
        "recommended_odds": 2.10,
        "bookmaker": "betway",
        "predicted_ev": 5.2,
        "league": "epl",
        "match_date": "2026-03-26",
        "confirming_signals": 2,
        "sport": "soccer",
    }
    base.update(overrides)
    return base


def _make_context(**overrides) -> dict:
    """Build a synthetic match_context dict."""
    base = {
        "data_available": True,
        "home_position": 3,
        "home_points": 55,
        "home_form": "WWDLW",
        "home_coach": "Mikel Arteta",
        "home_goals_per_game": 2.1,
        "away_position": 8,
        "away_points": 40,
        "away_form": "LDWWL",
        "away_coach": "Ange Postecoglou",
        "away_goals_per_game": 1.5,
        "h2h": [
            {"result": "Arsenal 3-1 Tottenham", "competition": "Premier League"},
            {"result": "Tottenham 0-1 Arsenal", "competition": "Premier League"},
        ],
        "injuries": [
            {"player": "Bukayo Saka", "team": "Arsenal", "reason": "Hamstring"},
        ],
    }
    base.update(overrides)
    return base


# Shared patches to avoid real DB/import hits
# ── Module Import ────────────────────────────────────────────

class TestModuleImport:
    """edge_detail_renderer must import cleanly."""

    def test_importable(self):
        import edge_detail_renderer  # noqa: F401

    def test_public_function_exists(self):
        from edge_detail_renderer import render_edge_detail
        assert callable(render_edge_detail)

    def test_dataclass_exists(self):
        from edge_detail_renderer import EdgeDetailData
        assert hasattr(EdgeDetailData, "__dataclass_fields__")

    def test_get_edge_tier_from_db_exists(self):
        """FIX-6: get_edge_tier_from_db exported for bot.py button coherence."""
        from edge_detail_renderer import get_edge_tier_from_db
        assert callable(get_edge_tier_from_db)

    def test_include_tier_false_returns_string(self):
        """FIX-6: default call returns plain string (backward compatible)."""
        from edge_detail_renderer import render_edge_detail
        with patch("edge_detail_renderer._load_edge_result", return_value=None), \
             patch("edge_detail_renderer._load_match_context", return_value=None):
            result = render_edge_detail("home_vs_away_2026-03-01", "bronze")
        assert isinstance(result, str)

    def test_include_tier_true_returns_tuple(self):
        """FIX-6: include_tier=True returns (html, edge_tier) tuple."""
        from edge_detail_renderer import render_edge_detail
        with patch("edge_detail_renderer._load_edge_result", return_value=None), \
             patch("edge_detail_renderer._load_match_context", return_value=None):
            result = render_edge_detail("home_vs_away_2026-03-01", "bronze", include_tier=True)
        assert isinstance(result, tuple)
        assert len(result) == 2
        html, tier = result
        assert isinstance(html, str)
        assert tier in ("diamond", "gold", "silver", "bronze")

    def test_include_tier_true_with_edge_row(self):
        """FIX-6: include_tier=True returns DB tier from edge_results row."""
        from edge_detail_renderer import render_edge_detail
        row = _make_edge_row(edge_tier="gold", confirming_signals=2)
        with patch("edge_detail_renderer._load_edge_result", return_value=row), \
             patch("edge_detail_renderer._load_match_context", return_value=None):
            result = render_edge_detail(row["match_key"], "diamond", include_tier=True)
        html, tier = result
        assert tier == "gold"

    def test_get_edge_tier_from_db_no_row_returns_bronze(self):
        """FIX-6: get_edge_tier_from_db returns 'bronze' when no row found."""
        from edge_detail_renderer import get_edge_tier_from_db
        with patch("edge_detail_renderer._load_edge_result", return_value=None):
            assert get_edge_tier_from_db("no_match_2026-03-01") == "bronze"

    def test_get_edge_tier_from_db_returns_db_tier(self):
        """FIX-6: get_edge_tier_from_db returns authoritative tier from DB."""
        from edge_detail_renderer import get_edge_tier_from_db
        row = _make_edge_row(edge_tier="diamond")
        with patch("edge_detail_renderer._load_edge_result", return_value=row):
            assert get_edge_tier_from_db(row["match_key"]) == "diamond"


# ── EdgeDetailData Construction ──────────────────────────────

class TestBuildDetailData:
    """_build_detail_data must populate all fields from exactly one source."""

    def test_ev_from_edge_results(self):
        """EV-MISMATCH fix: predicted_ev comes from edge_results.predicted_ev."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(predicted_ev=7.3)
        data = _build_detail_data(row, None, "diamond")
        assert data.predicted_ev == 7.3

    def test_tier_from_edge_results(self):
        """TIER-MISMATCH fix: edge_tier comes from edge_results.edge_tier."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(edge_tier="diamond")
        data = _build_detail_data(row, None, "diamond")
        assert data.edge_tier == "diamond"

    def test_tier_fallback_to_assign_tier(self):
        """Legacy rows without valid edge_tier fall back to assign_tier()."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(edge_tier="", composite_score=75, predicted_ev=10,
                             confirming_signals=3)
        data = _build_detail_data(row, None, "diamond")
        assert data.edge_tier in ("diamond", "gold", "silver", "bronze")

    def test_signals_from_db(self):
        """SIGNAL-CONTRADICTION fix: confirming_signals from DB column."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(confirming_signals=3)
        data = _build_detail_data(row, None, "diamond")
        assert data.confirming_signals == 3

    def test_model_only_when_zero_signals(self):
        """MODEL-ONLY BADGE fix: model_only = (confirming_signals == 0)."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(confirming_signals=0)
        data = _build_detail_data(row, None, "diamond")
        assert data.model_only is True

        row2 = _make_edge_row(confirming_signals=2)
        data2 = _build_detail_data(row2, None, "diamond")
        assert data2.model_only is False

    def test_fair_prob_computed(self):
        """Fair probability derived from EV + odds."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(predicted_ev=5.0, recommended_odds=2.0)
        data = _build_detail_data(row, None, "diamond")
        # (1 + 0.05) / 2.0 * 100 = 52.5 → round = 52
        assert data.fair_prob_pct == 52

    def test_outcome_resolved(self):
        """Outcome normalised from bet_type."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(bet_type="Home Win")
        data = _build_detail_data(row, None, "diamond")
        assert data.outcome == "home"
        assert "Arsenal" in data.outcome_display

    def test_mep_met_from_context(self):
        """mep_met reflects context.data_available."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row()
        ctx = _make_context(data_available=True)
        data = _build_detail_data(row, ctx, "diamond")
        assert data.mep_met is True

        data2 = _build_detail_data(row, None, "diamond")
        assert data2.mep_met is False

    def test_access_level_computed_once(self):
        """Access level computed via get_edge_access_level — ONE pass."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(edge_tier="diamond")
        data = _build_detail_data(row, None, "bronze")
        assert data.access_level == "locked"

        data2 = _build_detail_data(row, None, "diamond")
        assert data2.access_level == "full"

    def test_frozen_dataclass(self):
        """EdgeDetailData is immutable — no field can be mutated after build."""
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row()
        data = _build_detail_data(row, None, "diamond")
        with pytest.raises(AttributeError):
            data.predicted_ev = 99.9  # type: ignore[misc]


# ── Gating ───────────────────────────────────────────────────

class TestGating:
    """Access levels render different content."""

    def _render(self, user_tier: str, edge_tier: str, **kw) -> str:
        from edge_detail_renderer import render_edge_detail

        row = _make_edge_row(edge_tier=edge_tier, **kw)
        ctx = _make_context()
        with patch("edge_detail_renderer._load_edge_result", return_value=row), \
             patch("edge_detail_renderer._load_match_context", return_value=ctx):
            return render_edge_detail("test_vs_test_2026-03-26", user_tier)

    def test_full_access_has_all_sections(self):
        html = self._render("diamond", "gold")
        assert "📋 <b>The Setup</b>" in html
        assert "🎯 <b>The Edge</b>" in html
        assert "📡 <b>Signal Check</b>" in html
        assert "⚠️ <b>The Risk</b>" in html
        assert "🏆 <b>Verdict</b>" in html

    def test_locked_shows_upgrade(self):
        html = self._render("bronze", "diamond")
        assert "🔒" in html
        assert "/subscribe" in html
        # Must NOT show odds or signal details
        assert "Signal Check" not in html
        assert "The Risk" not in html

    def test_blurred_hides_odds(self):
        html = self._render("bronze", "gold")
        assert "available on upgrade" in html
        assert "/subscribe" in html

    def test_partial_shows_odds_but_limited(self):
        html = self._render("bronze", "silver", predicted_ev=5.0,
                            recommended_odds=2.0, confirming_signals=2)
        assert "🎯 <b>The Edge</b>" in html
        assert "🏆 <b>Verdict</b>" in html
        assert "/subscribe" in html
        # Should NOT have full setup section
        assert "📋 <b>The Setup</b>" not in html


# ── H2H Duplication ──────────────────────────────────────────

class TestH2HDuplication:
    """H2H-DUPLICATION fix: exactly one H2H section in output."""

    def test_single_h2h_section(self):
        from edge_detail_renderer import render_edge_detail

        row = _make_edge_row()
        ctx = _make_context()
        with patch("edge_detail_renderer._load_edge_result", return_value=row), \
             patch("edge_detail_renderer._load_match_context", return_value=ctx):
            html = render_edge_detail("test_vs_test_2026-03-26", "diamond")

        # Count H2H headers — must be exactly 1
        h2h_count = html.count("Head to Head")
        assert h2h_count == 1, f"Expected 1 H2H section, got {h2h_count}"


# ── Sport Dispatch ───────────────────────────────────────────

class TestSportDispatch:
    """Different sports get different section sets."""

    def _render_sport(self, sport: str) -> str:
        from edge_detail_renderer import render_edge_detail

        row = _make_edge_row(sport=sport, league="epl")
        ctx = _make_context(
            weather_forecast="Clear skies, 25°C",
            data_available=True,
        )
        with patch("edge_detail_renderer._load_edge_result", return_value=row), \
             patch("edge_detail_renderer._load_match_context", return_value=ctx):
            return render_edge_detail("test_vs_test_2026-03-26", "diamond", sport)

    def test_soccer_has_injuries(self):
        html = self._render_sport("soccer")
        assert "Key Absences" in html

    def test_cricket_has_weather(self):
        html = self._render_sport("cricket")
        assert "Conditions" in html

    def test_rugby_no_weather(self):
        html = self._render_sport("rugby")
        assert "Conditions" not in html

    def test_mma_no_injuries(self):
        html = self._render_sport("mma")
        assert "Key Absences" not in html

    def test_boxing_no_h2h(self):
        """Boxing section set does not include H2H."""
        from edge_detail_renderer import _SPORT_SECTIONS, _section_h2h
        assert _section_h2h not in _SPORT_SECTIONS["boxing"]


# ── No Edge Data Fallback ────────────────────────────────────

class TestNoEdgeData:
    """Graceful fallback when edge_results has no matching row."""

    def test_no_data_returns_friendly_message(self):
        from edge_detail_renderer import render_edge_detail

        with patch("edge_detail_renderer._load_edge_result", return_value=None):
            html = render_edge_detail("arsenal_vs_spurs_2026-03-26", "diamond")

        assert "No current edge data" in html
        assert "Arsenal" in html


# ── Template Repetition ──────────────────────────────────────

class TestTemplateRepetition:
    """TEMPLATE-REPETITION fix: prose from structured data, no NarrativeSpec."""

    def test_no_narrative_spec_import(self):
        """Renderer must NOT import from narrative_spec."""
        import edge_detail_renderer
        source_file = edge_detail_renderer.__file__
        with open(source_file) as f:
            source = f.read()
        assert "from narrative_spec" not in source
        assert "import narrative_spec" not in source

    def test_no_narrative_engine_import(self):
        """Renderer must NOT import from narrative_engine."""
        import edge_detail_renderer
        source_file = edge_detail_renderer.__file__
        with open(source_file)as f:
            source = f.read()
        assert "narrative_engine" not in source


# ── CLEAN-RUGBY: V1 Tip Fallback ────────────────────────────

def _make_tip(**overrides) -> dict:
    """Build a synthetic V1 tip dict for fallback testing."""
    base = {
        "match_key": "western_force_vs_chiefs_2026-03-28",
        "sport": "rugby",
        "league": "super_rugby",
        "edge_rating": "gold",
        "display_tier": "gold",
        "composite_score": 62.0,
        "ev": 4.5,
        "recommended_odds": 2.20,
        "bookmaker": "hollywoodbets",
        "recommended_outcome": "home",
    }
    base.update(overrides)
    return base


class TestV1TipFallback:
    """CLEAN-RUGBY: V1 tip data fallback when V2 edge_results missing."""

    def test_v1_fallback_renders_html_not_error(self):
        """When edge_results is empty but tip_data exists, render a card."""
        from edge_detail_renderer import render_edge_detail

        tip = _make_tip()
        with patch("edge_detail_renderer._load_edge_result", return_value=None), \
             patch("edge_detail_renderer._load_match_context", return_value=None):
            html = render_edge_detail(
                "western_force_vs_chiefs_2026-03-28", "gold", tip_data=tip,
            )

        assert "No current edge data" not in html
        # Must contain match identity
        assert "western force" in html.lower() or "Western Force" in html

    def test_v1_fallback_shows_odds_and_bookmaker(self):
        """V1 fallback card includes odds, bookmaker, and tier badge."""
        from edge_detail_renderer import render_edge_detail

        tip = _make_tip(
            recommended_odds=1.85, bookmaker="betway", display_tier="silver",
        )
        with patch("edge_detail_renderer._load_edge_result", return_value=None), \
             patch("edge_detail_renderer._load_match_context", return_value=None):
            html = render_edge_detail(
                "western_force_vs_chiefs_2026-03-28", "diamond", tip_data=tip,
            )

        assert "1.85" in html
        assert "Betway" in html

    def test_v1_fallback_confirming_estimated_from_composite(self):
        """V1 fallback estimates confirming_signals from composite_score (same logic as V2 path).
        composite=62 → confirming=2 → model_only=False."""
        from edge_detail_renderer import _build_detail_data_from_tip

        # composite_score=62 (default in _make_tip) → confirming=2 (>= 55), model_only=False
        tip = _make_tip()
        data = _build_detail_data_from_tip(tip, None, "diamond")
        assert data.confirming_signals == 2
        assert data.model_only is False

        # composite_score=0 → confirming=0, model_only=True
        tip_zero = _make_tip(composite_score=0)
        data_zero = _build_detail_data_from_tip(tip_zero, None, "diamond")
        assert data_zero.confirming_signals == 0
        assert data_zero.model_only is True

    def test_v2_path_ignores_tip_data(self):
        """When V2 edge_results exist, tip_data is not used."""
        from edge_detail_renderer import render_edge_detail

        row = _make_edge_row(predicted_ev=8.0, edge_tier="gold")
        ctx = _make_context()
        tip = _make_tip(ev=999.0)
        with patch("edge_detail_renderer._load_edge_result", return_value=row), \
             patch("edge_detail_renderer._load_match_context", return_value=ctx):
            html = render_edge_detail(
                "arsenal_vs_tottenham_2026-03-26", "diamond", tip_data=tip,
            )

        assert "No current edge data" not in html
        assert "999" not in html
