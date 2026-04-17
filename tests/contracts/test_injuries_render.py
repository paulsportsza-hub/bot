"""FIX-KICKOFF-RELATIVE-01/D3 — Contract tests for _build_important_injuries rendering.

Verifies that string-form injuries truncated at 25 chars have their closing
parenthesis completed, not left dangling. Root cause: inj.strip()[:25] cuts
"Jakub Kiwior (unavailable)" (27 chars) to "Jakub Kiwior (unavailable"
(missing closing ")").
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from card_data import _build_important_injuries


class TestBuildImportantInjuriesStringTruncation:
    """String injuries must not leave unclosed parentheses after truncation."""

    def test_long_string_closes_paren(self):
        # "Jakub Kiwior (unavailable)" = 27 chars, truncated to 25 → must close ")"
        result = _build_important_injuries(["Jakub Kiwior (unavailable)"], [])
        assert "(" not in result or result.count("(") == result.count(")"), (
            f"Unclosed paren in: {result!r}"
        )

    def test_exactly_25_chars_no_paren_issue(self):
        # 25 chars exactly — no truncation → no close needed
        result = _build_important_injuries(["ABCDEFGHIJKLMNOPQRSTUVWXY"], [])
        assert result == "ABCDEFGHIJKLMNOPQRSTUVWXY"

    def test_short_string_unaffected(self):
        result = _build_important_injuries(["Mo Salah (knock)"], [])
        assert result == "Mo Salah (knock)"

    def test_both_parens_balanced_after_truncation(self):
        injuries = ["Maldini Kacurri (unavailable, doubt)"]
        result = _build_important_injuries(injuries, [])
        assert result.count("(") == result.count(")"), (
            f"Unbalanced parens in: {result!r}"
        )

    def test_no_paren_in_string_unaffected(self):
        result = _build_important_injuries(["VeryLongPlayerNameGoesHereOver25"], [])
        assert ")" not in result  # No paren added when none was opened

    def test_mixed_home_and_away_string_injuries(self):
        home = ["Jakub Kiwior (unavailable)"]
        away = ["Gabriel Martinelli (doubt)"]
        result = _build_important_injuries(home, away)
        parts = result.split(", ")
        for part in parts:
            assert part.count("(") == part.count(")"), (
                f"Unbalanced parens in part {part!r} of {result!r}"
            )

    def test_dict_injuries_unaffected_by_fix(self):
        # Dict path (the normal path) must still work correctly
        home = [{"player": "Bukayo Saka", "status": "doubtful"}]
        away = [{"player": "Darwin Nunez", "reason": "knock"}]
        result = _build_important_injuries(home, away)
        assert "Bukayo Saka" in result
        assert "Darwin Nunez" in result
        assert "(" in result and ")" in result

    def test_up_to_three_items_returned(self):
        # Use injuries without internal commas to avoid split-count confusion
        injuries = [
            "Player One (injury)",
            "Player Two (knock)",
            "Player Three (unavailable)",
            "Player Four (suspended)",
        ]
        result = _build_important_injuries(injuries, [])
        parts = result.split(", ")
        assert len(parts) <= 3, f"Expected max 3 items, got {len(parts)}: {result!r}"

    def test_empty_lists_return_empty_string(self):
        assert _build_important_injuries([], []) == ""
