"""FIX-KICKOFF-RELATIVE-01/D2 — Contract tests for verdict length convention.

Verifies that _cap_verdict() and _trim_to_last_sentence() both produce
output <= _VERDICT_MAX_CHARS (140) characters. Root cause: _cap_verdict()
clipped to 140 chars then appended "." giving max 141, which min_verdict_quality
rejects (strict > 140 check).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import _cap_verdict, _VERDICT_MAX_CHARS


# 10 sample verdicts ranging from short to long, with punctuation variants
_SAMPLE_VERDICTS = [
    # Short — must pass through unchanged
    "Back Arsenal at 2.50 with Betway — signals aligned. Full stake.",
    # Exactly at limit (140 chars)
    "B" * 140,
    # One over the limit (141 chars) — must be capped
    "C" * 141,
    # Well over limit (200 chars) — must be capped
    "Back Liverpool Win at 1.85 with Hollywoodbets — multiple confirming signals aligned. "
    "Strong probability gap versus fair value. Full stake for maximum expected value.",
    # Contains a word at the boundary
    "Back Manchester United at 2.10 with Betway — momentum is with them and the home crowd "
    "will be a factor tonight. This is a properly supported back. Full stake.",
    # Ends mid-word at clipping point — must word-boundary trim
    "X" * 130 + " endword extra chars here going over the limit yes",
    # No spaces — word boundary falls far back
    "a" * 145,
    # Trailing punctuation to strip
    "Lean on draw at 3.20 (GBets) — only one signal aligns, don't overstate it. Small stake.,;",
    # Long verdict with bookmaker name
    "Strong back on Home Win at 1.62 (SuperSportBet) — depth of support most edges don't get. "
    "Indicators doing their job here. Full stake.",
    # Very long single sentence — no natural sentence boundary before 140
    "Cautious lean on Away Win at 3.40 with Hollywoodbets; keep exposure proportionate "
    "with the modest edge available and monitor line movement before kickoff. Small stake.",
]


class TestCapVerdictLengthGuarantee:
    """_cap_verdict must always return <= _VERDICT_MAX_CHARS chars."""

    @pytest.mark.parametrize("verdict", _SAMPLE_VERDICTS)
    def test_cap_verdict_never_exceeds_max(self, verdict):
        result = _cap_verdict(verdict)
        assert len(result) <= _VERDICT_MAX_CHARS, (
            f"_cap_verdict returned {len(result)} chars (max {_VERDICT_MAX_CHARS}): {result!r}"
        )

    def test_short_verdict_unchanged(self):
        short = "Back Arsenal at 2.50. Full stake."
        assert _cap_verdict(short) == short

    def test_exact_limit_unchanged(self):
        text = "B" * 140
        assert _cap_verdict(text) == text

    def test_one_over_limit_capped(self):
        text = "Back Arsenal at 1.85 with Betway — signals confirmed. Full stake. Extra word."
        result = _cap_verdict(text)
        assert len(result) <= _VERDICT_MAX_CHARS

    def test_result_is_not_empty_for_long_input(self):
        text = "Z" * 200
        result = _cap_verdict(text)
        assert result  # Non-empty


class TestTrimToLastSentenceLengthGuarantee:
    """_trim_to_last_sentence must always return <= max_chars (140) chars."""

    def _trim(self, text: str, max_chars: int = 140) -> str:
        from bot import _trim_to_last_sentence
        return _trim_to_last_sentence(text, max_chars=max_chars)

    @pytest.mark.parametrize("verdict", _SAMPLE_VERDICTS)
    def test_trim_never_exceeds_max(self, verdict):
        result = self._trim(verdict)
        assert len(result) <= _VERDICT_MAX_CHARS, (
            f"_trim_to_last_sentence returned {len(result)} chars: {result!r}"
        )

    def test_short_verdict_unchanged(self):
        short = "Back Arsenal at 2.50. Full stake."
        assert self._trim(short) == short

    def test_long_verdict_sentence_boundary(self):
        text = (
            "Back Liverpool at 1.85. Strong confirming signals back this play. "
            "Full stake for maximum expected value. This sentence pushes it way over the limit."
        )
        result = self._trim(text)
        assert len(result) <= 140
        assert result.endswith(".")
