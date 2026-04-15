"""BUILD-VERDICT-RENDER-FIXES-01 — contract tests.

Defect 1: Orphan 'Back X.' render fix — _fix_orphan_back().
Defect 2: Diamond 'At <price>' prefix gate — validate_diamond_price_prefix().
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Defect 1 — Orphan "Back X." orphan line fix ───────────────────────────────

class TestFixOrphanBack:
    """_fix_orphan_back() must join or strip the orphan Back clause."""

    def _fn(self):
        from bot import _fix_orphan_back
        return _fix_orphan_back

    def test_natural_inline_close_unchanged(self):
        """Verdict where 'Back X.' is already inline (no preceding period) is untouched."""
        fix = self._fn()
        # Em dash inline — no '. Back' pattern
        v = "The Reds are flying and the line agrees \u2014 Back Liverpool."
        assert fix(v) == v

    def test_orphaned_close_joins_with_em_dash(self):
        """Orphaned 'Back X.' sentence (preceded by '. ') is joined to previous sentence."""
        fix = self._fn()
        v = "Chiefs have won four of their last five. Back Amakhosi."
        result = fix(v)
        # Must contain "Back Amakhosi." without a sentence-starting capital after a period
        assert "Back Amakhosi." in result
        # The preceding period must be gone — now joined with em dash
        assert ". Back" not in result
        assert "\u2014 Back" in result

    def test_orphaned_close_strips_when_budget_exceeded(self):
        """When joining would exceed char_budget, the Back clause is stripped."""
        fix = self._fn()
        v = "Chiefs have won four of their last five. Back Amakhosi."
        # Force strip by passing a tiny budget
        result = fix(v, char_budget=5)
        assert "Back" not in result
        assert result.endswith(".")

    def test_no_match_returns_unchanged(self):
        """Verdict with no Back clause is returned as-is."""
        fix = self._fn()
        v = "The Sundowns are simply better in every department right now."
        assert fix(v) == v

    def test_back_the_team_pattern(self):
        """'Back the Draw.' pattern is also joined."""
        fix = self._fn()
        v = "Form and line movement both point this way. Back the Draw."
        result = fix(v)
        assert "Back the Draw." in result
        assert ". Back" not in result

    def test_regex_exposed_at_module_level(self):
        """_ORPHAN_BACK_RE must exist as a compiled regex in bot module."""
        import re
        import bot
        assert hasattr(bot, "_ORPHAN_BACK_RE"), "_ORPHAN_BACK_RE must be a module-level constant"
        assert isinstance(bot._ORPHAN_BACK_RE, re.Pattern)

    def test_fix_orphan_back_exported(self):
        """_fix_orphan_back must be importable from bot."""
        from bot import _fix_orphan_back
        assert callable(_fix_orphan_back)


# ── Defect 2 — Diamond 'At <price>' prefix gate ──────────────────────────────

class TestValidateDiamondPricePrefix:
    """validate_diamond_price_prefix() must hard-fail Diamond verdicts starting with 'At X.XX'."""

    def _fn(self):
        from narrative_spec import validate_diamond_price_prefix
        return validate_diamond_price_prefix

    def test_diamond_at_price_prefix_fails(self):
        """Diamond verdict starting with 'At 1.85, ...' must return False."""
        fn = self._fn()
        verdict = "At 1.85, the Reds are the play — they've dominated their last four."
        assert fn(verdict, "diamond") is False

    def test_diamond_clean_lead_passes(self):
        """Diamond verdict starting with pick/context passes."""
        fn = self._fn()
        verdict = "The Reds are the play at 1.85 — dominant recent form. Back Liverpool."
        assert fn(verdict, "diamond") is True

    def test_gold_at_price_prefix_passes(self):
        """Gold tier is not gated — 'At 1.85, ...' is acceptable for Gold."""
        fn = self._fn()
        verdict = "At 1.85, the Reds are value here. Back Liverpool."
        assert fn(verdict, "gold") is True

    def test_silver_at_price_prefix_passes(self):
        """Silver tier is not gated."""
        fn = self._fn()
        verdict = "At 2.10, there is value on the draw. Take the draw."
        assert fn(verdict, "silver") is True

    def test_bronze_at_price_prefix_passes(self):
        """Bronze tier is not gated."""
        fn = self._fn()
        verdict = "At 1.55, Chiefs are slight value. Back Chiefs."
        assert fn(verdict, "bronze") is True

    def test_empty_tier_treated_as_non_diamond(self):
        """Empty/None tier defaults to pass (non-diamond path)."""
        fn = self._fn()
        verdict = "At 1.85, the Reds are the play."
        assert fn(verdict, "") is True
        assert fn(verdict, None) is True  # type: ignore[arg-type]

    def test_wired_into_min_verdict_quality(self):
        """min_verdict_quality must reject a Diamond verdict with 'At <price>' prefix."""
        from narrative_spec import min_verdict_quality
        # Short enough to pass all other gates (len >= 160 for diamond)
        diamond_fail = (
            "At 1.85, the Reds are the play — they've dominated their last four "
            "fixtures and the line has been drifting steadily their way all week. "
            "The Gunners are in fine nick too. Back Liverpool."
        )
        assert len(diamond_fail) >= 160, "Test verdict must meet Diamond length floor"
        result = min_verdict_quality(diamond_fail, tier="diamond")
        assert result is False, "Diamond 'At <price>' verdict must fail min_verdict_quality"

    def test_function_exported_from_narrative_spec(self):
        """validate_diamond_price_prefix must be importable from narrative_spec."""
        from narrative_spec import validate_diamond_price_prefix
        assert callable(validate_diamond_price_prefix)
