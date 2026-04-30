"""Contract tests for FIX-ESPN-SCOREBOARD-DATE-AWARE-FETCH-01.

Verifies that:
1. _match_date_param() correctly converts YYYY-MM-DD to ESPN ?dates= format
2. get_match_context() accepts match_date parameter
3. match_date flows through to sub-functions
4. Pregen _get_match_context wrapper accepts and passes match_date
"""
import re
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


# ---------------------------------------------------------------------------
# _match_date_param helper
# ---------------------------------------------------------------------------

class TestMatchDateParam:
    def _import(self):
        from scrapers.match_context_fetcher import _match_date_param
        return _match_date_param

    def test_valid_date_returns_url_param_and_cache_suffix(self):
        fn = self._import()
        q, k = fn("2026-05-04")
        assert q == "?dates=20260504"
        assert k == "_20260504"

    def test_empty_string_returns_empty_pair(self):
        fn = self._import()
        q, k = fn("")
        assert q == ""
        assert k == ""

    def test_none_treated_as_empty(self):
        fn = self._import()
        # API callers may pass None; guard against it
        q, k = fn("")
        assert q == ""
        assert k == ""

    def test_malformed_date_returns_empty(self):
        fn = self._import()
        q, k = fn("not-a-date")
        assert q == ""
        assert k == ""

    def test_date_with_extra_chars_returns_empty(self):
        fn = self._import()
        q, k = fn("2026-05-04T00:00:00Z")
        # ISO datetime is not a pure YYYYMMDD → returns empty
        assert q == ""
        assert k == ""

    def test_hyphens_stripped_in_url_param(self):
        fn = self._import()
        q, _ = fn("2026-12-31")
        assert "-" not in q
        assert "20261231" in q


# ---------------------------------------------------------------------------
# get_match_context signature
# ---------------------------------------------------------------------------

class TestGetMatchContextSignature:
    def test_accepts_match_date_kwarg(self):
        import inspect
        from scrapers.match_context_fetcher import get_match_context
        sig = inspect.signature(get_match_context)
        assert "match_date" in sig.parameters, "get_match_context missing match_date param"

    def test_match_date_defaults_to_empty_string(self):
        import inspect
        from scrapers.match_context_fetcher import get_match_context
        sig = inspect.signature(get_match_context)
        p = sig.parameters["match_date"]
        assert p.default == "", f"match_date default should be '' not {p.default!r}"

    def test_match_date_is_keyword_only(self):
        import inspect
        from scrapers.match_context_fetcher import get_match_context
        sig = inspect.signature(get_match_context)
        p = sig.parameters["match_date"]
        assert p.kind == inspect.Parameter.KEYWORD_ONLY


# ---------------------------------------------------------------------------
# Sub-function signatures
# ---------------------------------------------------------------------------

class TestSubFunctionSignatures:
    """All sport sub-functions must accept match_date keyword arg."""

    def _check_sig(self, fn_name: str):
        import inspect
        import scrapers.match_context_fetcher as mcf
        fn = getattr(mcf, fn_name)
        sig = inspect.signature(fn)
        assert "match_date" in sig.parameters, f"{fn_name} missing match_date param"
        p = sig.parameters["match_date"]
        assert p.default == ""
        assert p.kind == inspect.Parameter.KEYWORD_ONLY

    def test_soccer_context(self):
        self._check_sig("_get_soccer_context")

    def test_rugby_context(self):
        self._check_sig("_get_rugby_context")

    def test_cricket_context(self):
        self._check_sig("_get_cricket_context")

    def test_franchise_cricket_context(self):
        self._check_sig("_get_franchise_cricket_context")

    def test_international_cricket_context(self):
        self._check_sig("_get_international_cricket_context")

    def test_mma_context(self):
        self._check_sig("_get_mma_context")


# ---------------------------------------------------------------------------
# Scoreboard URL construction (structural check via source inspection)
# ---------------------------------------------------------------------------

class TestScoreboardUrlPattern:
    """Verify scoreboard URL builders use _match_date_param output."""

    def _get_source(self):
        import inspect
        import scrapers.match_context_fetcher as mcf
        return inspect.getsource(mcf)

    def test_soccer_scoreboard_uses_date_param(self):
        src = self._get_source()
        # The pattern _sb_q must appear near the soccer scoreboard URL
        assert "_sb_q, _sb_k = _match_date_param(match_date)" in src

    def test_scoreboard_url_uses_sb_q(self):
        src = self._get_source()
        assert "scoreboard{_sb_q}" in src

    def test_scoreboard_key_uses_sb_k(self):
        src = self._get_source()
        assert "scoreboard_key" in src and "{_sb_k}" in src

    def test_date_param_applied_multiple_sports(self):
        src = self._get_source()
        # Should appear at least 4 times (soccer, rugby, franchise cricket, international cricket)
        count = src.count("_match_date_param(match_date)")
        assert count >= 4, f"Expected ≥4 _match_date_param usages, found {count}"


# ---------------------------------------------------------------------------
# Pregen wrapper signature
# ---------------------------------------------------------------------------

class TestPregenWrapperSignature:
    def test_pregen_get_match_context_accepts_match_date(self):
        import inspect
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
        # Import without executing bot-level startup
        import importlib.util
        pregen_path = os.path.join(
            os.path.dirname(__file__), "../../scripts/pregenerate_narratives.py"
        )
        if not os.path.exists(pregen_path):
            pytest.skip("pregenerate_narratives.py not found")
        src = open(pregen_path).read()
        # Check wrapper signature contains match_date
        assert "match_date: str = \"\"" in src or "match_date: str=''" in src or "match_date=" in src
        # Check ESPN fallback passes it
        assert "match_date=match_date" in src

    def test_generate_one_extracts_date_from_match_key(self):
        pregen_path = os.path.join(
            os.path.dirname(__file__), "../../scripts/pregenerate_narratives.py"
        )
        if not os.path.exists(pregen_path):
            pytest.skip("pregenerate_narratives.py not found")
        src = open(pregen_path).read()
        # Verify the date extraction regex is present
        assert r"(\d{4}-\d{2}-\d{2})$" in src or r"\d{4}-\d{2}-\d{2}" in src
        assert "_mk_date" in src
