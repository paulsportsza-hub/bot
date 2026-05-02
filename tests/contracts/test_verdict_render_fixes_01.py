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


# ── Defect 2 — Diamond 'At <price>' prefix gate (RETIRED) ────────────────────
#
# BUILD-W82-RIP-AND-REPLACE-01 (2026-05-02): the Diamond price-prefix gate
# was specific to the W82 variable-assembly era's "At X.XX..." opener pattern.
# The deterministic verdict_corpus closes Diamond verdicts with imperatives
# (hammer / load up / go in heavy / lock in), so the gate's anti-pattern can
# no longer surface. validate_diamond_price_prefix is retained as a True-
# returning shim for callsite stability — see narrative_spec.py docstring.
# Prior tests in this section were tightly coupled to the retired pattern
# and are removed.
