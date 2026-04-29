"""FIX-NARRATIVE-ROT-ROOT-01 / Phase 4 / AC-4.3 — Claim-source validation.

`validate_claims_against_evidence()` checks that numeric claims in the
narrative are backed by the evidence pack. Five claim classes are scanned
across all four sections:

  1. H2H meeting count   ("5 meetings")  vs `h2h.matches`
  2. H2H W-D-L record    ("4W 0D 1L")    vs sum(WDL) <= len(matches)
  3. Form sequence       ("WWWLD")        vs espn_context.{home,away}.form
  4. Season W-D-L record (outside H2H)    vs espn_context.{home,away}.record
  5. Points total        ("58 points")    vs espn_context.{home,away}.points

QA-flagged cases:
  - LB-5: Brighton-Wolves "2 meetings: Brighton 0W 2D 0L" with empty h2h.matches
  - LB-B5: Liverpool-Chelsea "WWWLD" with data_available=False
  - LB-B4: Bayern-PSG "5 meetings: Bayern Munich 4W 0D 1L" with len(matches)==3
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
from config import ensure_scrapers_importable  # noqa: E402

ensure_scrapers_importable()


def _wrap_setup(setup: str) -> str:
    return (
        "🎯 Home vs Away\n"
        f"📋 The Setup\n{setup}\n"
        "🎯 The Edge\nEdge body.\n"
        "⚠️ The Risk\nRisk body.\n"
        "🏆 Verdict\nVerdict body.\n"
    )


# ── LB-5: H2H meeting count when h2h.matches is empty ────────────────────────


def test_lb5_brighton_wolves_h2h_empty_fires() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "Across 2 meetings between these sides, Brighton 0W 2D 0L."
    )
    pack = {
        "h2h": {"matches": []},
        "espn_context": {"data_available": True},
    }
    viols = validate_claims_against_evidence(text, pack)
    assert viols, "expected violation when h2h.matches is empty"
    classes = [v.claim_class for v in viols]
    assert "h2h_count" in classes


# ── LB-B4: H2H WDL exceeds matches length ────────────────────────────────────


def test_lb_b4_bayern_psg_wdl_exceeds_matches() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "These sides have met 5 times in previous meetings — Bayern Munich 4W 0D 1L."
    )
    # Pack has only 3 matches (5 cited, but only 3 in evidence).
    pack = {
        "h2h": {"matches": [{"home": "Bayern", "away": "PSG"}] * 3},
        "espn_context": {"data_available": True},
    }
    viols = validate_claims_against_evidence(text, pack)
    classes = [v.claim_class for v in viols]
    # h2h_count: cited 5 > len(matches)=3
    assert "h2h_count" in classes
    # h2h_wdl: cited W+D+L=5 > len(matches)=3
    assert "h2h_wdl" in classes


# ── LB-B5: Form sequence with data_available=False ───────────────────────────


def test_lb_b5_form_sequence_with_no_espn_data() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "On a WWWLD run heading into this fixture, Liverpool look strong."
    )
    pack = {
        "espn_context": {
            "data_available": False,
            "home_team": {"data_available": False, "form": ""},
            "away_team": {"data_available": False, "form": ""},
        },
        "h2h": {"matches": []},
    }
    viols = validate_claims_against_evidence(text, pack)
    classes = [v.claim_class for v in viols]
    assert "form_seq" in classes


# ── Clean cases — must NOT fire ──────────────────────────────────────────────


def test_clean_h2h_count_matches_evidence() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "These sides have met 3 times in previous meetings."
    )
    pack = {
        "h2h": {"matches": [{}] * 3},
        "espn_context": {"data_available": True},
    }
    assert validate_claims_against_evidence(text, pack) == []


def test_clean_h2h_count_under_matches() -> None:
    """Cited count <= h2h_count is OK (narrative may scope to a subset)."""
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "Across the last 2 meetings between these sides..."
    )
    pack = {
        "h2h": {"matches": [{}] * 5},
        "espn_context": {"data_available": True},
    }
    assert validate_claims_against_evidence(text, pack) == []


def test_clean_form_matches_espn_data() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "On a WWWLD run, Manchester City head into this fixture."
    )
    pack = {
        "espn_context": {
            "data_available": True,
            "home_team": {"data_available": True, "form": "WWWLD"},
            "away_team": {"data_available": True, "form": "DLWWW"},
        },
        "h2h": {"matches": []},
    }
    assert validate_claims_against_evidence(text, pack) == []


def test_clean_points_total_with_evidence() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "Liverpool sit on 58 points after a strong run."
    )
    pack = {
        "espn_context": {
            "data_available": True,
            "home_team": {"data_available": True, "points": 58},
            "away_team": {"data_available": True, "points": 53},
        },
        "h2h": {"matches": []},
    }
    assert validate_claims_against_evidence(text, pack) == []


def test_clean_season_wdl_matches_evidence() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "Manchester City sit at 12W 3D 2L across the season — a strong record."
    )
    pack = {
        "h2h": {"matches": []},
        "espn_context": {
            "data_available": True,
            "home_team": {
                "data_available": True,
                "record": {"wins": 12, "draws": 3, "losses": 2},
            },
            "away_team": {"data_available": True, "record": "8-5-4"},
        },
    }
    assert validate_claims_against_evidence(text, pack) == []


def test_clean_season_wdl_string_format_evidence() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "Newcastle's 8W 5D 4L points to consistent mid-table form."
    )
    pack = {
        "h2h": {"matches": []},
        "espn_context": {
            "data_available": True,
            "home_team": {"data_available": True, "record": "8-5-4"},
            "away_team": {"data_available": True, "record": "10-2-5"},
        },
    }
    assert validate_claims_against_evidence(text, pack) == []


# ── Defensive: empty / missing inputs ────────────────────────────────────────


def test_empty_pack_returns_empty() -> None:
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup("3 meetings between these sides — strong record.")
    # No oracle to validate — graceful no-op.
    assert validate_claims_against_evidence(text, None) == []
    assert validate_claims_against_evidence(text, {}) == []


def test_empty_text_returns_empty() -> None:
    from narrative_spec import validate_claims_against_evidence

    pack = {"h2h": {"matches": []}, "espn_context": {"data_available": False}}
    assert validate_claims_against_evidence("", pack) == []


def test_unrelated_numbers_do_not_fire() -> None:
    """Numbers that aren't claim-class numerics must pass cleanly."""
    from narrative_spec import validate_claims_against_evidence

    text = _wrap_setup(
        "Manchester City average 1.7 goals per game across the season."
    )
    pack = {
        "espn_context": {
            "data_available": True,
            "home_team": {"data_available": True, "points": 58},
        },
        "h2h": {"matches": [{}] * 3},
    }
    # No "X meetings", no WDL, no form sequence — no violation.
    assert validate_claims_against_evidence(text, pack) == []


# ── Claim violation namedtuple stability ─────────────────────────────────────


def test_claim_violation_is_namedtuple() -> None:
    from narrative_spec import ClaimViolation

    v = ClaimViolation(
        claim_class="h2h_count",
        claim_text="5 meetings",
        section="setup",
        evidence_state="h2h_matches_empty",
    )
    assert v.claim_class == "h2h_count"
    assert v.claim_text == "5 meetings"
    assert ClaimViolation._fields == (
        "claim_class", "claim_text", "section", "evidence_state",
    )
