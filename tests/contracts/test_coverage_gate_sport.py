"""BUILD-COVERAGE-GATE — Sport-specific evidence threshold contract tests.

AC-7:  Contract tests for each sport path through compute_coverage_level()
AC-8:  MMA fight with 2 fighter records reaches W84 (coverage = "full")
AC-9:  Cricket match with standings reaches W84 (coverage = "full" or "partial")
AC-10: Boxing with no fighter data stays W82 (coverage = "empty")
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── AC-7: Sport-specific paths through compute_coverage_level ──


class TestSoccerCoverageUnchanged:
    """Soccer thresholds must be identical to pre-BUILD-COVERAGE-GATE."""

    def test_soccer_empty(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="soccer", league="epl",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=5,
        )
        assert level == "empty"

    def test_soccer_partial_low_key_facts(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="soccer", league="epl",
            key_facts=2, form_games=3, h2h_games=2,
            standings=True, market_count=5,
        )
        assert level == "partial"

    def test_soccer_partial_low_market_count(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="soccer", league="psl",
            key_facts=6, form_games=5, h2h_games=4,
            standings=True, market_count=1,
        )
        assert level == "partial"

    def test_soccer_full(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="soccer", league="epl",
            key_facts=6, form_games=5, h2h_games=4,
            standings=True, market_count=5,
        )
        assert level == "full"

    def test_soccer_ignores_fighter_records(self):
        """Soccer should not benefit from fighter_records kwarg."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="soccer", league="epl",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=5,
            fighter_records=2,
        )
        assert level == "empty"


# ── AC-8: MMA fight with 2 fighter records reaches W84 ──


class TestMMAcoverage:
    """MMA coverage uses fighter records as primary evidence."""

    def test_mma_full_both_fighters(self):
        """Both fighters have records → 'full'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="mma", league="ufc",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=1,
            fighter_records=2,
        )
        assert level == "full"

    def test_mma_partial_one_fighter_plus_odds(self):
        """One fighter record + odds → 'partial'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="mma", league="ufc",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=1,
            fighter_records=1,
        )
        assert level == "partial"

    def test_mma_partial_odds_only(self):
        """No fighter data but 2+ bookmakers → 'partial'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="mma", league="ufc",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=2,
            fighter_records=0,
        )
        assert level == "partial"

    def test_mma_empty_no_data(self):
        """No fighter records and <2 bookmakers → 'empty'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="mma", league="ufc",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=0,
            fighter_records=0,
        )
        assert level == "empty"

    def test_combat_alias(self):
        """'combat' sport string works same as 'mma'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="combat", league="ufc",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=1,
            fighter_records=2,
        )
        assert level == "full"


# ── AC-9: Cricket match with standings reaches W84 ──


class TestCricketCoverage:
    """Cricket coverage uses standings from cricket_standings table."""

    def test_cricket_full_with_standings(self):
        """Cricket standings + key facts → 'full'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="cricket", league="ipl",
            key_facts=1, form_games=0, h2h_games=0,
            standings=False, market_count=2,
            cricket_standings=True,
        )
        assert level == "full"

    def test_cricket_partial_standings_only(self):
        """Cricket standings alone → 'partial'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="cricket", league="sa20",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=0,
            cricket_standings=True,
        )
        assert level == "partial"

    def test_cricket_empty_no_data(self):
        """No ESPN, no standings → 'empty'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="cricket", league="sa20",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=0,
            cricket_standings=False,
        )
        assert level == "empty"

    def test_cricket_partial_with_glicko(self):
        """Cricket with Glicko + odds → 'partial'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="cricket", league="sa20",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=2,
            glicko_available=True,
        )
        assert level == "partial"


# ── AC-10: Boxing with no fighter data stays W82 (empty) ──


class TestBoxingCoverage:
    """Boxing without enrichment data stays at empty/partial."""

    def test_boxing_empty_no_data(self):
        """Boxing with no fighter records and <2 bookmakers → 'empty'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="boxing", league="major_bouts",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=1,
            fighter_records=0,
        )
        assert level == "empty"

    def test_boxing_empty_zero_everything(self):
        """Boxing with zero data across the board → 'empty'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="boxing", league="major_bouts",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=0,
            fighter_records=0,
        )
        assert level == "empty"

    def test_boxing_partial_with_odds(self):
        """Boxing with 2+ bookmakers but no fighter data → 'partial'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="boxing", league="major_bouts",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=2,
            fighter_records=0,
        )
        assert level == "partial"


# ── AC-7 continued: Rugby coverage ──


class TestRugbyCoverage:
    """Rugby coverage uses Glicko-2 as key evidence source."""

    def test_rugby_full_with_glicko_and_standings(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="rugby", league="urc",
            key_facts=1, form_games=0, h2h_games=0,
            standings=True, market_count=2,
            glicko_available=True,
        )
        assert level == "full"

    def test_rugby_partial_with_h2h(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="rugby", league="six_nations",
            key_facts=0, form_games=0, h2h_games=3,
            standings=False, market_count=2,
        )
        assert level == "partial"

    def test_rugby_empty_no_data(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="rugby", league="urc",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=0,
        )
        assert level == "empty"

    def test_rugby_full_with_key_facts_and_glicko(self):
        """Rugby: 1 key_fact + Glicko = 2 rugby_facts + Glicko → 'full'."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="rugby", league="super_rugby",
            key_facts=1, form_games=0, h2h_games=0,
            standings=False, market_count=1,
            glicko_available=True,
        )
        assert level == "full"


# ── Helper function tests ──


class TestHasNonzeroRecord:
    """_has_nonzero_record correctly parses fighter W-L-D strings."""

    def test_normal_record(self):
        from evidence_pack import _has_nonzero_record

        assert _has_nonzero_record("25-4-0") is True

    def test_zero_record(self):
        from evidence_pack import _has_nonzero_record

        assert _has_nonzero_record("0-0-0") is False

    def test_empty_string(self):
        from evidence_pack import _has_nonzero_record

        assert _has_nonzero_record("") is False

    def test_undefeated(self):
        from evidence_pack import _has_nonzero_record

        assert _has_nonzero_record("14-0-0") is True

    def test_draws_only(self):
        from evidence_pack import _has_nonzero_record

        assert _has_nonzero_record("0-0-2") is True

    def test_malformed(self):
        from evidence_pack import _has_nonzero_record

        assert _has_nonzero_record("abc") is False

    def test_none_safe(self):
        from evidence_pack import _has_nonzero_record

        assert _has_nonzero_record(None) is False


# ── Default fallback for unknown sports ──


class TestDefaultFallback:
    """Unknown sport uses original universal logic."""

    def test_unknown_sport_empty(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="darts", league="pdc",
            key_facts=0, form_games=0, h2h_games=0,
            standings=False, market_count=5,
        )
        assert level == "empty"

    def test_unknown_sport_full(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="darts", league="pdc",
            key_facts=6, form_games=3, h2h_games=2,
            standings=True, market_count=5,
        )
        assert level == "full"
