"""FIX-NARRATIVE-ROT-ROOT-01 / Phase 4 / AC-4.2 — Cross-section manager validation.

The QA wave flagged manager hallucinations in narrative bodies that the
existing Verdict-only `find_fabricated_manager_names()` cannot catch:

  - LB-2: "Amorim's United" appears in Setup on Man Utd-Liverpool. Man Utd's
    actual coach in coaches.json is Michael Carrick.
  - LB-3: "Nuno's side" appears on Notts Forest. Forest's actual coach is
    Vitor Pereira.

`validate_manager_names_in_all_sections()` scans the FULL polished narrative
and cross-references every proper-noun token against:

  1. evidence_pack["espn_context"]["home_team"]["coach"]
  2. evidence_pack["espn_context"]["away_team"]["coach"]
  3. canonical scraper lookup `lookup_coach(team_name)`
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


def _build_text(setup="", edge="", risk="", verdict=""):
    """Build a narrative with all four section markers."""
    return (
        "🎯 Home vs Away\n"
        f"📋 The Setup\n{setup}\n"
        f"🎯 The Edge\n{edge}\n"
        f"⚠️ The Risk\n{risk}\n"
        f"🏆 Verdict\n{verdict}\n"
    )


def _pack_man_utd_liverpool(coaches_present=True):
    """Build evidence_pack for Man Utd vs Liverpool with current coaches."""
    pack = {
        "espn_context": {
            "home_team": {"name": "Manchester United"},
            "away_team": {"name": "Liverpool"},
        },
    }
    if coaches_present:
        pack["espn_context"]["home_team"]["coach"] = "Michael Carrick"
        pack["espn_context"]["away_team"]["coach"] = "Arne Slot"
    return pack


def _pack_forest_newcastle(coaches_present=True):
    """Build evidence_pack for Forest vs Newcastle with current coaches."""
    pack = {
        "espn_context": {
            "home_team": {"name": "Nottingham Forest"},
            "away_team": {"name": "Newcastle United"},
        },
    }
    if coaches_present:
        pack["espn_context"]["home_team"]["coach"] = "Vitor Pereira"
        pack["espn_context"]["away_team"]["coach"] = "Eddie Howe"
    return pack


# ── LB-2: "Amorim's United" hallucination ────────────────────────────────────


def test_lb2_amorims_united_in_setup_fires() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="Amorim's United arrive on a 4-game unbeaten run at Old Trafford.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    pack = _pack_man_utd_liverpool()
    viols = validate_manager_names_in_all_sections(text, pack)
    assert viols, "expected Amorim hallucination to fire on Man Utd evidence"
    assert any(v.name.lower() == "amorim" for v in viols)
    assert any(v.section == "setup" for v in viols)
    # Carrick + Slot are the expected coaches.
    v0 = viols[0]
    assert v0.expected_home == "Michael Carrick"
    assert v0.expected_away == "Arne Slot"


def test_lb2_amorims_united_in_verdict_fires() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="Setup body.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Worth a small unit on Amorim's side. Hold it lightly.",
    )
    pack = _pack_man_utd_liverpool()
    viols = validate_manager_names_in_all_sections(text, pack)
    assert any(v.name.lower() == "amorim" and v.section == "verdict" for v in viols)


# ── LB-3: "Nuno's side" hallucination on Forest ──────────────────────────────


def test_lb3_nunos_side_on_forest_fires() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="Nuno's side return to the City Ground hoping to climb the table.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    pack = _pack_forest_newcastle()
    viols = validate_manager_names_in_all_sections(text, pack)
    assert viols, "expected Nuno hallucination to fire on Forest evidence"
    assert any(v.name.lower() == "nuno" for v in viols)


# ── Clean cases — must NOT fire ──────────────────────────────────────────────


def test_clean_arteta_arsenal_passes() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="Arteta's Arsenal sit on 53 points after a strong run.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    pack = {
        "espn_context": {
            "home_team": {"name": "Arsenal", "coach": "Mikel Arteta"},
            "away_team": {"name": "Chelsea", "coach": "Liam Rosenior"},
        },
    }
    viols = validate_manager_names_in_all_sections(text, pack)
    assert viols == []


def test_clean_carrick_correct_for_man_utd() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="Carrick's United are looking to bounce back from a tough run.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    pack = _pack_man_utd_liverpool()
    viols = validate_manager_names_in_all_sections(text, pack)
    assert viols == []


def test_clean_team_words_do_not_fire() -> None:
    """Team words (United, City, etc.) must not be flagged as managers."""
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="United come in off the back of two clean sheets at home.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    pack = _pack_man_utd_liverpool()
    viols = validate_manager_names_in_all_sections(text, pack)
    assert viols == []


def test_clean_country_names_do_not_fire() -> None:
    """Country names (England, France) must not be flagged as managers."""
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="England's domestic league has produced many such fixtures over the years.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    pack = _pack_man_utd_liverpool()
    viols = validate_manager_names_in_all_sections(text, pack)
    assert viols == []


# ── No coach data — graceful no-op ───────────────────────────────────────────


def test_no_coach_data_returns_empty() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="Mystery's side arrive in fine form.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    # Pack with NO coach data (and no canonical lookup match).
    pack = {
        "espn_context": {
            "home_team": {"name": "Unknown FC"},
            "away_team": {"name": "Made Up United"},
        },
    }
    viols = validate_manager_names_in_all_sections(text, pack)
    # No oracle to validate against → graceful no-op.
    assert viols == []


def test_empty_text_returns_empty() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    pack = _pack_man_utd_liverpool()
    assert validate_manager_names_in_all_sections("", pack) == []


def test_empty_pack_returns_empty() -> None:
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(setup="Amorim's United arrive in form.")
    # No oracle to validate against — must not fire (false-positive guard).
    assert validate_manager_names_in_all_sections(text, None) == []
    assert validate_manager_names_in_all_sections(text, {}) == []


# ── Canonical lookup — works without explicit coach in evidence_pack ─────────


def test_canonical_lookup_catches_hallucination() -> None:
    """When evidence_pack has team names but no coach key, canonical
    `lookup_coach()` must still validate against the scraper coaches.json."""
    from narrative_spec import validate_manager_names_in_all_sections

    text = _build_text(
        setup="Amorim's United arrive on a 4-game unbeaten run.",
        edge="Edge body.",
        risk="Risk body.",
        verdict="Verdict closer body.",
    )
    # Coaches NOT explicitly set in evidence_pack — canonical lookup applies.
    pack = _pack_man_utd_liverpool(coaches_present=False)
    viols = validate_manager_names_in_all_sections(text, pack)
    assert viols, "canonical lookup_coach() must catch the hallucination"
    assert any(v.name.lower() == "amorim" for v in viols)


# ── Manager namedtuple stability ─────────────────────────────────────────────


def test_manager_violation_is_namedtuple() -> None:
    from narrative_spec import ManagerViolation

    v = ManagerViolation(
        name="Amorim",
        section="setup",
        expected_home="Michael Carrick",
        expected_away="Arne Slot",
    )
    assert v.name == "Amorim"
    assert v.section == "setup"
    assert v.expected_home == "Michael Carrick"
    assert v.expected_away == "Arne Slot"
    # Field order locked.
    assert ManagerViolation._fields == (
        "name", "section", "expected_home", "expected_away",
    )
