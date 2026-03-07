"""Layer 1.3 — Source code scanning tests.

Scans actual source files for patterns that indicate regressions:
- All tier lookups use get_effective_tier() (not raw db.get_user_tier())
- Narrative prompt contains ABSOLUTE RULES
- No triple newlines in format/build functions
"""

from __future__ import annotations

import inspect
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.expanduser("~"))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))

BOT_PY = os.path.expanduser("~/bot/bot.py")


def _read_bot_source() -> str:
    """Read bot.py source once for all tests."""
    with open(BOT_PY, "r") as f:
        return f.read()


class TestTierLookupConsistency:
    """All user tier lookups in bot.py must use get_effective_tier()."""

    def test_no_raw_get_user_tier_in_handlers(self):
        """bot.py should NOT call db.get_user_tier() directly — use get_effective_tier()."""
        src = _read_bot_source()

        # Find all db.get_user_tier() calls
        raw_calls = re.findall(r'db\.get_user_tier\s*\(', src)

        # The only allowed occurrence is inside get_effective_tier() itself
        # Count how many times get_effective_tier references it
        fn_src = ""
        try:
            import bot
            fn_src = inspect.getsource(bot.get_effective_tier)
        except Exception:
            pass

        allowed_in_fn = fn_src.count("db.get_user_tier")
        total = len(raw_calls)

        assert total <= allowed_in_fn, (
            f"Found {total} calls to db.get_user_tier() in bot.py, "
            f"but only {allowed_in_fn} are inside get_effective_tier(). "
            f"Other calls should use get_effective_tier() instead."
        )

    def test_get_effective_tier_exists(self):
        """get_effective_tier must be defined in bot.py."""
        import bot
        assert hasattr(bot, "get_effective_tier"), (
            "bot.py must define get_effective_tier()"
        )
        assert callable(bot.get_effective_tier), (
            "get_effective_tier must be callable"
        )


class TestPromptRules:
    """AI prompt must contain anti-hallucination safeguards."""

    def test_analyst_prompt_has_absolute_rules(self):
        """The analyst prompt builder must contain 'ABSOLUTE' rules."""
        import bot
        fn = getattr(bot, "_build_analyst_prompt", None)
        if fn is None:
            pytest.skip("_build_analyst_prompt not found")
        src = inspect.getsource(fn)
        assert "ABSOLUTE" in src, (
            "_build_analyst_prompt() must contain ABSOLUTE RULES"
        )

    def test_analyst_prompt_has_golden_rule(self):
        """Prompt must contain the GOLDEN RULE anti-fabrication guard."""
        import bot
        fn = getattr(bot, "_build_analyst_prompt", None)
        if fn is None:
            pytest.skip("_build_analyst_prompt not found")
        src = inspect.getsource(fn)
        assert "GOLDEN RULE" in src, (
            "_build_analyst_prompt() must contain GOLDEN RULE"
        )

    def test_analyst_prompt_bans_unverified_facts(self):
        """Prompt must explicitly ban unverified factual claims."""
        import bot
        fn = getattr(bot, "_build_analyst_prompt", None)
        if fn is None:
            pytest.skip("_build_analyst_prompt not found")
        src = inspect.getsource(fn)
        assert "VERIFIED" in src.upper(), (
            "_build_analyst_prompt() must reference VERIFIED data"
        )


class TestFormattingIntegrity:
    """No triple newlines in format/build functions."""

    def test_no_triple_newlines_in_format_functions(self):
        """Format/build functions must never produce triple newlines."""
        src = _read_bot_source()

        # Extract all function bodies that start with _build_ or _format_ or _render_
        pattern = r'(def\s+(?:_build_|_format_|_render_)\w+\s*\([^)]*\).*?)(?=\ndef\s|\Z)'
        functions = re.findall(pattern, src, re.DOTALL)

        violations = []
        for fn_src in functions:
            # Check for hardcoded triple newlines in string literals
            if '\\n\\n\\n' in fn_src:
                # Extract function name
                name_match = re.match(r'def\s+(\w+)', fn_src)
                if name_match:
                    violations.append(name_match.group(1))

        assert not violations, (
            f"Functions with hardcoded triple newlines: {violations}. "
            f"Max allowed is \\n\\n (one blank line)."
        )

    def test_sanitize_ai_response_exists(self):
        """sanitize_ai_response must exist for post-processing AI output."""
        import bot
        assert hasattr(bot, "sanitize_ai_response"), (
            "bot.py must define sanitize_ai_response()"
        )


class TestGuardConstants:
    """W44-GUARDS constants must be present."""

    def test_fallback_phrases_defined(self):
        """_FALLBACK_PHRASES must exist and be non-empty."""
        import bot
        assert hasattr(bot, "_FALLBACK_PHRASES"), (
            "bot.py must define _FALLBACK_PHRASES"
        )
        assert len(bot._FALLBACK_PHRASES) >= 3, (
            f"_FALLBACK_PHRASES has only {len(bot._FALLBACK_PHRASES)} items, need >= 3"
        )

    def test_data_rich_leagues_defined(self):
        """_DATA_RICH_LEAGUES must include EPL and PSL."""
        import bot
        assert hasattr(bot, "_DATA_RICH_LEAGUES"), (
            "bot.py must define _DATA_RICH_LEAGUES"
        )
        assert "epl" in bot._DATA_RICH_LEAGUES, "EPL must be in _DATA_RICH_LEAGUES"
        assert "psl" in bot._DATA_RICH_LEAGUES, "PSL must be in _DATA_RICH_LEAGUES"
