"""FIX-REGRESS-D1-VERDICT-GUARD-01 + FIX-NARRATIVE-META-MARKERS-01: LLM meta-reply leak validator tests.

Validator `_reject_llm_meta_strings(verdict: str) -> bool` returns True when the
verdict text contains LLM error-reply meta-strings such as:
  - "I notice", "I understand", "I apologize"
  - "confidence_tier"
  - "SELECTIVE" (an invalid tier value the Sonnet prompt rejects by echoing it)
  - "not one of", "isn't one of"
  - "valid tiers", "four valid", "valid options"
  - "i cannot", "i can't produce" (LLM refusal phrases — FIX-NARRATIVE-META-MARKERS-01)
  - "no form, h2h", "no form data, h2h", "no manager names", "also noting"
    (data-absence meta-commentary — FIX-NARRATIVE-META-MARKERS-01)

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

    # FIX-NARRATIVE-META-MARKERS-01: 6 new markers

    def test_rejects_i_cannot(self):
        verdict = "I cannot produce a valid verdict for this match because the data is missing."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_i_cant_produce(self):
        verdict = "I can't produce a verdict for this match — the confidence tier is invalid."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_no_form_h2h(self):
        verdict = "Also, no form, H2H, manager, or signals data was provided, so proceed cautiously."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_no_form_data_h2h(self):
        verdict = "Also, no form data, H2H summary, manager names, or signals were provided."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_no_manager_names(self):
        verdict = "Note: No manager names, form data, or H2H summary were provided for this fixture."
        self.assertTrue(_reject_llm_meta_strings(verdict))

    def test_rejects_also_noting(self):
        verdict = "Also noting: no manager names, no form data, no H2H summary were included."
        self.assertTrue(_reject_llm_meta_strings(verdict))


if __name__ == "__main__":
    unittest.main()
