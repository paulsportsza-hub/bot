"""Ground-truth integration test for tests/qa/vision_ocr.py.

Pins 3 real card screenshots captured by the BUILD-DEEPLINK-HARDEN-01
sub-agent and asserts Claude vision reads each one correctly.

Runs only under `pytest -m integration` (or via scripts/qa_safe.sh) — skipped
from the default `pytest -q` suite because it costs real Anthropic API tokens.

Challenge threshold: verdict fuzzy similarity must be >= 0.85 per the brief.
Below that, the OCR prompt needs material rework, not just parameter tweaks.
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

import pytest

from tests.qa.card_assertions import (
    assert_not_stub_shape,
    assert_teams_populated,
    assert_tier_badge_present,
    assert_verdict_in_range,
)
from tests.qa.vision_ocr import ocr_card

pytestmark = pytest.mark.integration


GROUND_TRUTH_DIR = Path(__file__).parent / "ground_truth"
VERDICT_FUZZY_MIN = 0.85  # Challenge rule: below this → escalate to LEAD.


def _ground_truth_cases() -> list[tuple[Path, dict]]:
    """Enumerate (png, expected) pairs for each card under ground_truth/."""
    cases: list[tuple[Path, dict]] = []
    for png in sorted(GROUND_TRUTH_DIR.glob("card_*.png")):
        expected_path = png.with_suffix(".expected.json")
        if not expected_path.is_file():
            continue
        with expected_path.open(encoding="utf-8") as f:
            expected = json.load(f)
        cases.append((png, expected))
    return cases


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=a, b=b).ratio()


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — integration OCR test cannot run",
)
@pytest.mark.parametrize("png,expected", _ground_truth_cases(), ids=lambda x: getattr(x, "name", ""))
def test_card_reads_match_ground_truth(png: Path, expected: dict) -> None:
    """For each pinned card, vision OCR must match the stored expected reading."""
    ocr = ocr_card(png)

    # Assertion helpers are the load-bearing contract — if any card fails
    # these, the harness is broken, not just a fuzzy-match issue.
    assert_verdict_in_range(ocr)
    assert_not_stub_shape(ocr)
    assert_teams_populated(ocr)
    assert_tier_badge_present(ocr)

    # Team labels + tier badge must match exactly — any drift is a real bug.
    assert ocr.home_team == expected["home_team"], (
        f"home_team OCR={ocr.home_team!r} != expected {expected['home_team']!r} "
        f"(card: {png.name})"
    )
    assert ocr.away_team == expected["away_team"], (
        f"away_team OCR={ocr.away_team!r} != expected {expected['away_team']!r} "
        f"(card: {png.name})"
    )
    assert ocr.tier_badge == expected["tier_badge"], (
        f"tier_badge OCR={ocr.tier_badge!r} != expected {expected['tier_badge']!r} "
        f"(card: {png.name})"
    )

    # Verdict text uses fuzzy similarity — small renderer whitespace/punctuation
    # drift is acceptable, but anything below the challenge threshold is a bug.
    ratio = _fuzzy_ratio(ocr.verdict_text, expected["verdict_text"])
    assert ratio >= VERDICT_FUZZY_MIN, (
        f"verdict fuzzy ratio {ratio:.3f} < {VERDICT_FUZZY_MIN} "
        f"(card: {png.name})\n"
        f"  OCR:      {ocr.verdict_text!r}\n"
        f"  EXPECTED: {expected['verdict_text']!r}"
    )


def test_ground_truth_dir_pins_at_least_three_cards() -> None:
    """Brief requires 3–5 pinned cards. Below 3 is a brief violation."""
    cases = _ground_truth_cases()
    assert len(cases) >= 3, (
        f"Ground-truth set has {len(cases)} cards — brief requires 3-5. "
        f"Pin more screenshots under {GROUND_TRUTH_DIR}"
    )
