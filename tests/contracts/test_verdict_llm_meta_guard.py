"""FIX-REGRESS-D1-VERDICT-GUARD-01: LLM meta-reply leak validator tests.

Validator `_reject_llm_meta_strings(verdict: str) -> bool` returns True when the
verdict text contains LLM error-reply meta-strings such as:
  - "I notice", "I understand", "I apologize"
  - "confidence_tier"
  - "SELECTIVE" (an invalid tier value the Sonnet prompt rejects by echoing it)
  - "not one of", "isn't one of"
  - "valid tiers", "four valid", "valid options"

On reject, the bot callers fall back to the deterministic baseline verdict and
emit a Sentry breadcrumb `verdict_rejected_llm_meta`. This test guards the
validator's rejection surface and its pass-through of clean analytical prose.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import _reject_llm_meta_strings


class TestRejectLLMMetaStrings(unittest.TestCase):
    """Validator must catch LLM error-reply leaks before they ship."""

    def test_rejects_i_notice(self):
        verdict = "I notice that 'SELECTIVE' is not one of the four valid tiers."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_confidence_tier_field_reference(self):
        verdict = "The confidence_tier value provided does not match the expected enum."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_selective_leak(self):
        verdict = "SELECTIVE is not a valid option — please use MILD, SOLID, STRONG, or MAX."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_not_one_of_phrase(self):
        verdict = "The input tier is not one of the allowed values."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_valid_tiers_phrase(self):
        verdict = "Please provide one of the four valid tiers."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_apology(self):
        verdict = "I apologize, but I cannot produce a verdict without a valid tier."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_isnt_one_of_phrase(self):
        verdict = "The provided label isn't one of the recognised tiers."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_i_understand(self):
        verdict = "I understand the request, but the tier input is not recognised."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_is_case_insensitive(self):
        verdict = "CONFIDENCE_TIER must be MILD, SOLID, STRONG, or MAX."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_accepts_clean_verdict(self):
        verdict = (
            "Back Arsenal at 1.85 on Betway. The 4.2% EV and consensus line movement "
            "confirm the edge — reasonable confidence for a standard stake."
        )
        self.assertFalse(_reject_llm_meta_strings(verdict))

    def test_accepts_cautious_verdict(self):
        verdict = "Monitor this market. The gap is real but signals are thin — a small stake is the ceiling."
        self.assertFalse(_reject_llm_meta_strings(verdict))

    def test_accepts_empty_string(self):
        self.assertFalse(_reject_llm_meta_strings(""))


if __name__ == "__main__":
    unittest.main()
