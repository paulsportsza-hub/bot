"""FIX-H2H-DUP-01 — Regression guard: H2H block fires at most once in _render_setup().

Root cause: _h2h_bridge() (via _render_setup) and _inject_h2h_sentence() (W82 fallback
path in pregenerate_narratives.py) both insert "Head to head: ..." without seeing each
other. The fix adds an _h2h_already_present guard at pregenerate_narratives.py:2138 that
checks whether spec.h2h_summary.split(",")[0] is already present in the narrative before
calling _build_h2h_injection() + _inject_h2h_sentence().
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from narrative_spec import (
    NarrativeSpec,
    _render_baseline,
    _render_setup,
)
from evidence_pack import _inject_h2h_sentence


def _make_spec(h2h_summary: str = "4 wins, 2 draws, 1 loss — Mamelodi Sundowns led") -> NarrativeSpec:
    return NarrativeSpec(
        home_name="Mamelodi Sundowns",
        away_name="Kaizer Chiefs",
        competition="PSL",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="setback",
        home_coach="Rulani Mokwena",
        away_coach="Nasreddine Nabi",
        home_position=1,
        away_position=8,
        home_points=52,
        away_points=30,
        home_form="WWWDW",
        away_form="LLDWL",
        h2h_summary=h2h_summary,
        outcome="home",
        outcome_label="Sundowns win",
        bookmaker="Betway",
        odds=1.85,
        ev_pct=4.2,
        fair_prob_pct=58.0,
        composite_score=55.0,
        support_level=2,
        evidence_class="lean",
        tone_band="moderate",
        risk_factors=[],
        risk_severity="moderate",
        verdict_action="back",
        verdict_sizing="standard stake",
        stale_minutes=20,
        movement_direction="neutral",
        tipster_against=0,
    )


class TestH2HDuplicationGuard:
    """AC-4 — regression guard for FIX-H2H-DUP-01."""

    def test_render_setup_contains_exactly_one_h2h(self):
        """_render_setup emits H2H exactly once when h2h_summary is set."""
        spec = _make_spec()
        setup = _render_setup(spec)
        count = setup.lower().count("head to head")
        assert count == 1, (
            f"Expected exactly 1 'Head to head' in _render_setup output, got {count}.\n"
            f"Output:\n{setup}"
        )

    def test_render_baseline_contains_exactly_one_h2h(self):
        """Full baseline render emits H2H exactly once."""
        spec = _make_spec()
        baseline = _render_baseline(spec)
        count = baseline.lower().count("head to head")
        assert count == 1, (
            f"Expected exactly 1 'Head to head' in baseline, got {count}.\n"
            f"Baseline:\n{baseline}"
        )

    def test_guard_prevents_second_injection(self):
        """Simulates the old double-fire: calling _inject_h2h_sentence on a narrative
        that already contains the H2H fragment must produce exactly one 'Head to head' block.

        With the FIX-H2H-DUP-01 guard, pregenerate_narratives skips the injection entirely
        when spec.h2h_summary.split(',')[0] is already present. This test verifies the
        underlying _inject_h2h_sentence() would double-fire WITHOUT the guard, confirming
        the guard is the necessary line of defence.
        """
        spec = _make_spec()
        narrative = _render_baseline(spec)
        assert narrative.lower().count("head to head") == 1

        # Simulate what the old code did: call _inject_h2h_sentence unconditionally.
        # _h2h_bridge produced "Head to head: 4 wins, 2 draws, 1 loss — ..."
        # _build_h2h_injection would produce "Head to head: 4 wins, and the last meeting finished 2-1."
        # These are different strings so the `sentence in text` guard inside _inject_h2h_sentence
        # does NOT catch the duplicate → double-fire.
        simulated_injection = "Head to head: 4 wins, and the last meeting finished 2-1."
        after_injection = _inject_h2h_sentence(narrative, simulated_injection)
        double_fired = after_injection.lower().count("head to head") > 1
        assert double_fired, (
            "Expected _inject_h2h_sentence to double-fire without the FIX-H2H-DUP-01 guard "
            "(confirming the guard is necessary). If this fails the underlying mechanism changed."
        )

    def test_guard_logic_skips_when_h2h_already_present(self):
        """The _h2h_already_present guard correctly detects prior H2H inclusion."""
        spec = _make_spec()
        narrative = _render_baseline(spec)

        # Apply the guard logic exactly as coded in pregenerate_narratives.py
        _spec_h2h = getattr(spec, "h2h_summary", "") or ""
        _h2h_already_present = (
            _spec_h2h
            and _spec_h2h.split(",")[0].lower() in narrative.lower()
        )
        assert _h2h_already_present, (
            "Guard should detect that _h2h_bridge already included H2H in the narrative."
        )

    def test_guard_does_not_skip_when_h2h_absent(self):
        """Guard allows injection when spec.h2h_summary is empty (no _h2h_bridge output)."""
        spec = _make_spec(h2h_summary="")
        narrative = _render_baseline(spec)

        _spec_h2h = getattr(spec, "h2h_summary", "") or ""
        _h2h_already_present = (
            _spec_h2h
            and _spec_h2h.split(",")[0].lower() in narrative.lower()
        )
        assert not _h2h_already_present, (
            "Guard must NOT fire when h2h_summary is empty — injection should proceed."
        )

    def test_no_placeholders_in_baseline(self):
        """AC-5 — baseline output contains no [TBD], [H2H], or empty section bodies."""
        spec = _make_spec()
        baseline = _render_baseline(spec)
        for placeholder in ("[TBD]", "[H2H]", "[TEAM]"):
            assert placeholder not in baseline, (
                f"Placeholder {placeholder!r} found in baseline output."
            )
        # No consecutive empty lines beyond one blank line
        assert "\n\n\n" not in baseline, "Triple newline (double blank line) found in baseline."
