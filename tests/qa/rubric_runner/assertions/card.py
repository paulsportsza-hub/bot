"""Extended card assertions for the QA Rubric Runner.

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

Extends tests/qa/card_assertions.py with V2-specific assertions.
Includes Addition 1: assert_supersport_logo_red().

NEVER import or modify the original card_assertions.py here — only extend.
"""
from __future__ import annotations

import re
from typing import Union

from tests.qa.card_assertions import (  # re-export all V1 assertions
    assert_verdict_in_range,
    assert_not_stub_shape,
    assert_teams_populated,
    assert_tier_badge_present,
    assert_button_set,
)
from tests.qa.ocr_prompt import ALLOWED_TIER_BADGES
from tests.qa.vision_ocr import CardOCR
from ..scoring.ocr_schema import CardOCRV2

AnyCardOCR = Union[CardOCR, CardOCRV2]


# ── Addition 1 — SuperSport Logo Visual Check ─────────────────────────────────

def assert_supersport_logo_red(ocr: AnyCardOCR) -> None:
    """Assert SuperSport logo is present AND red.

    Per Paul-Approved Addition 1:
      - supersport_logo_present must be True
      - supersport_logo_colour must contain "red"

    Missing or non-red logo = C3 deduction (-1.0) + SEV-3.

    Cards with no broadcast channel: this assertion MUST be skipped
    by the caller (check broadcast_visible first).
    """
    if not isinstance(ocr, CardOCRV2):
        raise TypeError(
            "assert_supersport_logo_red requires CardOCRV2 — run with USE_OCR_V2=True"
        )

    if not ocr.supersport_logo_present:
        raise AssertionError(
            "supersport_logo_present=False — SuperSport logo missing from card "
            "(C3 deduction -1.0, SEV-3)"
        )

    colour = (ocr.supersport_logo_colour or "").lower()
    if "red" not in colour:
        raise AssertionError(
            f"supersport_logo_colour={ocr.supersport_logo_colour!r} — expected 'red' "
            f"(C3 deduction -1.0, SEV-3)"
        )


# ── V2-specific assertions ────────────────────────────────────────────────────

def assert_kickoff_visible(ocr: AnyCardOCR) -> None:
    """Kickoff time must be visible on the card."""
    if not isinstance(ocr, CardOCRV2):
        return  # V1 cannot check this field
    if not ocr.kickoff_visible:
        raise AssertionError("kickoff_visible=False — kickoff time not shown on card (C1 deduction)")


def assert_odds_visible(ocr: AnyCardOCR) -> None:
    """Odds value must be visible on a full-access card."""
    if not isinstance(ocr, CardOCRV2):
        return
    if not ocr.odds_value_visible:
        raise AssertionError("odds_value_visible=False — odds not shown (C1 deduction)")


def assert_bookmaker_visible(ocr: AnyCardOCR) -> None:
    """Bookmaker name must be visible on a full-access card."""
    if not isinstance(ocr, CardOCRV2):
        return
    if not ocr.bookmaker_name_visible:
        raise AssertionError("bookmaker_name_visible=False — bookmaker not shown (C1 deduction)")


def assert_tier_badge_matches_tier(ocr: AnyCardOCR, expected_tier: str) -> None:
    """Tier badge emoji on the card must match the expected tier.

    Mapping:
        diamond → 💎
        gold    → 🥇
        silver  → 🥈
        bronze  → 🥉
    """
    _tier_to_badge = {
        "diamond": "💎",
        "gold": "🥇",
        "silver": "🥈",
        "bronze": "🥉",
    }
    expected_badge = _tier_to_badge.get(expected_tier.lower())
    if expected_badge is None:
        raise ValueError(f"Unknown tier: {expected_tier!r}")

    badge = ocr.tier_badge
    if badge is None:
        raise AssertionError(
            f"tier_badge missing — expected {expected_badge!r} for tier {expected_tier!r} "
            f"(C4 deduction)"
        )
    if badge != expected_badge:
        raise AssertionError(
            f"tier_badge={badge!r} != expected {expected_badge!r} for tier {expected_tier!r} "
            f"(C4 deduction)"
        )


def assert_no_placeholder_sections(ocr: AnyCardOCR) -> None:
    """No section header should contain placeholder text like '...' or 'TODO'."""
    if not isinstance(ocr, CardOCRV2):
        return
    for section in ocr.sections_present:
        s_lower = section.lower()
        if "..." in s_lower or "todo" in s_lower or "[placeholder]" in s_lower:
            raise AssertionError(
                f"Section contains placeholder text: {section!r} (C2 deduction, SEV-3)"
            )


# ── Composite quick-check ─────────────────────────────────────────────────────

def quick_check_full_access_card(ocr: AnyCardOCR, edge_tier: str) -> list[str]:
    """Run all relevant assertions for a full-access card. Returns list of failure messages.

    Does NOT raise — caller collects failures for scoring.
    """
    failures: list[str] = []

    def _try(fn, *args, **kwargs) -> None:
        try:
            fn(*args, **kwargs)
        except (AssertionError, TypeError) as exc:
            failures.append(str(exc))

    _try(assert_verdict_in_range, ocr)
    _try(assert_not_stub_shape, ocr)
    _try(assert_teams_populated, ocr)
    _try(assert_tier_badge_present, ocr)
    _try(assert_tier_badge_matches_tier, ocr, edge_tier)
    _try(assert_kickoff_visible, ocr)
    _try(assert_odds_visible, ocr)
    _try(assert_bookmaker_visible, ocr)
    _try(assert_no_placeholder_sections, ocr)

    return failures
