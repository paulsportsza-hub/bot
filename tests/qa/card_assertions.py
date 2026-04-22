"""Content-level assertions on OCR'd card readings.

Each helper raises AssertionError with a descriptive message that includes
the OCR'd value so test output is debuggable without re-running OCR.
"""
from __future__ import annotations

import re

from tests.qa.ocr_prompt import ALLOWED_TIER_BADGES
from tests.qa.vision_ocr import CardOCR

# Matches the canonical stub shape we want to catch:
#   "— ? at 0.00."
# Tolerates unicode minus vs hyphen, run-on whitespace, and trailing punctuation
# leading into the rest of the verdict.
_STUB_VERDICT_RE = re.compile(r"[—–-]\s*\?\s*at\s*0\.00\s*\.")

# Literal placeholder team labels that indicate a broken render.
_PLACEHOLDER_TEAM_LABELS: frozenset[str] = frozenset({"HOME", "AWAY"})


def assert_verdict_in_range(
    ocr: CardOCR, min_chars: int = 100, max_chars: int = 260
) -> None:
    """Verdict body character count must fall inside [min_chars, max_chars]."""
    n = ocr.verdict_char_count
    if not (min_chars <= n <= max_chars):
        raise AssertionError(
            f"verdict_char_count={n} outside [{min_chars},{max_chars}] — "
            f"verdict={ocr.verdict_text!r}"
        )


def assert_not_stub_shape(ocr: CardOCR) -> None:
    """Verdict must not match the stub '— ? at 0.00.' shape."""
    if _STUB_VERDICT_RE.search(ocr.verdict_text):
        raise AssertionError(
            f"verdict matches stub shape '— ? at 0.00.' — "
            f"verdict={ocr.verdict_text!r}"
        )


def assert_teams_populated(ocr: CardOCR) -> None:
    """Both team strings must be non-empty and not the literal HOME/AWAY placeholders."""
    for side, value in (("home_team", ocr.home_team), ("away_team", ocr.away_team)):
        if not value.strip():
            raise AssertionError(f"{side} is empty — ocr={ocr!r}")
        if value.strip().upper() in _PLACEHOLDER_TEAM_LABELS:
            raise AssertionError(
                f"{side} equals placeholder {value!r} — render failed to substitute"
            )


def assert_tier_badge_present(
    ocr: CardOCR, expected: set[str] | None = None
) -> None:
    """A tier badge must be present. Optionally constrain to `expected`."""
    if ocr.tier_badge is None:
        raise AssertionError(
            f"tier_badge missing — must be one of {list(ALLOWED_TIER_BADGES)}"
        )
    allowed = expected if expected is not None else set(ALLOWED_TIER_BADGES)
    if ocr.tier_badge not in allowed:
        raise AssertionError(
            f"tier_badge={ocr.tier_badge!r} not in expected {sorted(allowed)}"
        )


def assert_button_set(ocr: CardOCR, expected_labels: list[str]) -> None:
    """OCR'd button labels must exactly match `expected_labels` (order + text)."""
    if ocr.button_count != len(expected_labels):
        raise AssertionError(
            f"button_count={ocr.button_count} != expected {len(expected_labels)} — "
            f"labels={ocr.button_labels!r}, expected={expected_labels!r}"
        )
    if ocr.button_labels != expected_labels:
        raise AssertionError(
            f"button_labels={ocr.button_labels!r} != expected {expected_labels!r}"
        )
