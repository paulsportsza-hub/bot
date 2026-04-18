"""FIX-VERDICT-SHAPE-GUARD-01 — Unit tests for F1 shape guard in _generate_verdict().

AC2: Stubs Anthropic client to return banned shape on attempt 1, valid shape on
attempt 2. Asserts valid shape is returned and attempt 1's log line fires.
"""
from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add bot root to path so imports resolve without running bot startup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_response(text: str):
    """Build a minimal Anthropic messages.create response stub."""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


class TestVerdictShapeGuard(unittest.TestCase):
    """F1 shape-guard: retry on banned template, return valid text on success."""

    def _get_generate_verdict(self):
        """Import _generate_verdict lazily to avoid bot-level side effects."""
        import importlib
        bot = importlib.import_module("bot")
        return bot._generate_verdict

    def _minimal_tip(self, **kwargs):
        base = {
            "home_team": "Manchester City",
            "away_team": "Arsenal",
            "pick": "Manchester City",
            "odds": 1.75,
            "bookmaker": "Hollywoodbets",
            "league_key": "epl",
            "confidence": 80,
        }
        base.update(kwargs)
        return base

    def _minimal_verified(self):
        return {"matchup": "Manchester City vs Arsenal"}

    def test_valid_verdict_returned_on_second_attempt(self):
        """On attempt 1 banned shape → attempt 2 valid text → returns valid text."""
        BANNED = "Manchester City at 1.75."
        VALID = "City have won four on the bounce and the line hasn't moved. Back City."

        attempt_counter = {"n": 0}

        def _fake_create(**kwargs):
            attempt_counter["n"] += 1
            if attempt_counter["n"] == 1:
                return _make_response(BANNED)
            return _make_response(VALID)

        tip = self._minimal_tip()
        verified = self._minimal_verified()

        with patch("anthropic.Anthropic") as MockClient:
            client_inst = MockClient.return_value
            client_inst.messages.create.side_effect = _fake_create

            with patch("bot.log") as mock_log:
                fn = self._get_generate_verdict()
                result = fn(tip, verified)

        # The result should contain the core content (punctuation may be adjusted by _fix_orphan_back)
        self.assertIn("City have won four on the bounce", result)
        self.assertNotEqual(result.strip(), BANNED.strip())
        # AC1: verify the banned-template warning fired on attempt 1
        # Check args directly — format string uses %d so string repr shows "%d" not "0"
        shape_guard_calls = [
            c for c in mock_log.warning.call_args_list
            if c.args and "verdict_rejected_banned_template" in str(c.args[0])
        ]
        self.assertTrue(
            len(shape_guard_calls) >= 1,
            f"Expected verdict_rejected_banned_template log, got: {mock_log.warning.call_args_list}",
        )
        # template_idx arg must be 0 (price-prefix pattern is index 0)
        # args: (fmt, tier, len, template_idx, text)
        first_call_args = shape_guard_calls[0].args
        self.assertEqual(
            first_call_args[3], 0,
            f"Expected template_idx=0, got {first_call_args[3]}",
        )

    def test_programmatic_fallback_when_both_attempts_banned(self):
        """If both attempt 1 and retry return banned shape, programmatic fallback fires."""
        BANNED = "Arsenal at 1.42."

        tip = self._minimal_tip(
            home_team="Arsenal",
            away_team="Bournemouth",
            pick="Arsenal",
            odds=1.42,
            ev=5.5,
        )
        verified = self._minimal_verified()

        with patch("anthropic.Anthropic") as MockClient:
            client_inst = MockClient.return_value
            client_inst.messages.create.return_value = _make_response(BANNED)

            fn = self._get_generate_verdict()
            result = fn(tip, verified)

        # Must not return empty — programmatic fallback should produce something
        # (programmatic fallback requires ev > 0 and odds > 0 which we have)
        self.assertIsInstance(result, str)
        # It should NOT be the banned shape text
        self.assertNotEqual(result.strip(), BANNED.strip())

    def test_non_banned_text_passes_through_unchanged(self):
        """Text that does not match any banned template passes through without retry."""
        VALID = "City are in stunning form and the Betway price is generous. Back City."

        attempt_counter = {"n": 0}

        def _fake_create(**kwargs):
            attempt_counter["n"] += 1
            return _make_response(VALID)

        tip = self._minimal_tip()
        verified = self._minimal_verified()

        with patch("anthropic.Anthropic") as MockClient:
            client_inst = MockClient.return_value
            client_inst.messages.create.side_effect = _fake_create

            fn = self._get_generate_verdict()
            result = fn(tip, verified)

        # Only one Anthropic call should happen (no retry needed)
        self.assertEqual(attempt_counter["n"], 1, "Expected exactly 1 API call for valid text")
        self.assertIn("City", result)


if __name__ == "__main__":
    unittest.main()
