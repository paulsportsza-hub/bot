"""FIX-NARRATIVE-MMA-LORE-01 — Strip generic-lore phrases from combat-sport prose.

Covers:
  AC-2: Unit tests for _find_combat_lore_violations (cases a-g).
  AC-3: _validate_polish gate 8e rejects combat polish containing banned phrases.
  AC-5: format_evidence_prompt carries combat-specific instruction (both branches).
  AC-13: Sport coverage across MMA, boxing, UFC, Bellator, ONE FC.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()


# ── AC-2(a): classic lore trope flagged on combat sport ──────────────────────


def test_combat_lore_detects_classic_trope():
    """Combat narrative with 'the fight game' returns combat_lore reason."""
    from bot import _find_combat_lore_violations

    narrative = (
        "📋 <b>The Setup</b>\n"
        "Welcome to the fight game where anything happens.\n"
        "🎯 <b>The Edge</b>\nFighter A at 1.85.\n"
    )
    reasons = _find_combat_lore_violations(narrative, "mma")
    assert "combat_lore:the fight game" in reasons


# ── AC-2(b): clean combat narrative passes ──────────────────────────────────


def test_combat_lore_clean_narrative_returns_empty():
    """Combat narrative with no banned phrases returns []."""
    from bot import _find_combat_lore_violations

    narrative = (
        "📋 <b>The Setup</b>\n"
        "Fighter A faces Fighter B on the May 2 card. Both enter at welterweight.\n"
        "🎯 <b>The Edge</b>\nFighter A priced at 1.65 by SuperSportBet.\n"
    )
    assert _find_combat_lore_violations(narrative, "mma") == []


# ── AC-2(c): non-combat sport is no-op even with banned phrase ──────────────


def test_non_combat_sport_is_noop():
    """Same trope inside soccer narrative returns [] — gate is sport-keyed."""
    from bot import _find_combat_lore_violations

    narrative = (
        "📋 <b>The Setup</b>\n"
        "Welcome to the fight game. Real Madrid vs Barcelona is always fierce.\n"
    )
    assert _find_combat_lore_violations(narrative, "soccer") == []


# ── AC-2(d): sport=None is no-op ────────────────────────────────────────────


def test_sport_none_is_noop():
    """sport=None returns []."""
    from bot import _find_combat_lore_violations

    narrative = "📋 <b>The Setup</b>\nThis is the fight game.\n"
    assert _find_combat_lore_violations(narrative, None) == []
    assert _find_combat_lore_violations(narrative, "") == []


# ── AC-2(e): multiple banned phrases — one reason per unique phrase, no dups ─


def test_multiple_banned_phrases_no_duplicates():
    """Each unique phrase fires once even if it appears multiple times."""
    from bot import _find_combat_lore_violations

    narrative = (
        "📋 <b>The Setup</b>\n"
        "Historically the fight game has rewarded warriors.\n"
        "🎯 <b>The Edge</b>\n"
        "In combat sports the heart of a champion matters more than form.\n"
        "⚠️ <b>The Risk</b>\n"
        "Submission vulnerability is real here.\n"
    )
    reasons = _find_combat_lore_violations(narrative, "mma")
    # Each unique phrase fires once.
    assert "combat_lore:historically" in reasons
    assert "combat_lore:the fight game" in reasons
    assert "combat_lore:in combat sports" in reasons
    assert "combat_lore:the heart of a champion" in reasons
    assert "combat_lore:submission vulnerability" in reasons

    # Dedup: same phrase appearing twice produces only one entry.
    duplicate = "📋 The Setup\nWarrior spirit and warrior spirit again.\n"
    duplicate_reasons = _find_combat_lore_violations(duplicate, "mma")
    assert duplicate_reasons.count("combat_lore:warrior spirit") == 1


# ── AC-2(f): HTML stripped before phrase match ───────────────────────────────


def test_html_stripped_before_match():
    """`<b>the fight game</b>` matches just like plain `the fight game`."""
    from bot import _find_combat_lore_violations

    html_narrative = "📋 <b>The Setup</b>\n<b>The fight game</b> never sleeps here.\n"
    reasons = _find_combat_lore_violations(html_narrative, "mma")
    assert "combat_lore:the fight game" in reasons

    # Italic + bold combinations also matched
    nested_narrative = "📋 The Setup\n<i><b>warrior spirit</b></i> drives this.\n"
    reasons = _find_combat_lore_violations(nested_narrative, "mma")
    assert "combat_lore:warrior spirit" in reasons


# ── AC-2(g): cricket / tennis / rugby narratives are unaffected ──────────────


def test_other_sports_unaffected():
    """Non-combat sports — cricket, rugby, tennis, soccer — return []."""
    from bot import _find_combat_lore_violations

    narrative = (
        "📋 <b>The Setup</b>\n"
        "Warrior spirit lives in this Springbok pack — bread and butter rugby.\n"
    )
    for sport in ("cricket", "rugby", "tennis", "soccer", "f1"):
        assert _find_combat_lore_violations(narrative, sport) == [], (
            f"Combat-lore gate must be no-op for sport={sport!r}"
        )


# ── Empirically observed phrases (calibration anchor — INV-flagged corpus) ──


@pytest.mark.parametrize("phrase", [
    "in combat sports",
    "psychological and logistical advantages",
    "championship-level mma",
    "inherent unpredictability of mma",
    "challenger's mentality",
    "the promotion's ruleset",
    "submission vulnerability",
    "fight-night adjustments",
    "double-edged sword",
    "historically",
])
def test_empirically_observed_phrases_caught(phrase):
    """Each phrase observed in W84 INV-flagged corpus must trigger the gate.

    These are the calibration anchor — if any drops out, the regression caught
    by INV-NARRATIVE-AUDIT-PRE-LAUNCH-01 reopens.
    """
    from bot import _find_combat_lore_violations

    narrative = (
        "📋 <b>The Setup</b>\n"
        f"The {phrase} matters here significantly.\n"
        "🎯 <b>The Edge</b>\nFighter A at 1.65.\n"
    )
    reasons = _find_combat_lore_violations(narrative, "mma")
    assert any(phrase in r for r in reasons), (
        f"Phrase {phrase!r} not caught — calibration regression"
    )


# ── AC-13: sport coverage ────────────────────────────────────────────────────


@pytest.mark.parametrize("sport", [
    "mma", "boxing", "ufc", "bellator", "one_fc", "one",
    "pfl", "glory", "k1", "kickboxing", "combat",
])
def test_sport_coverage_combat_keys(sport):
    """All combat sport keys trigger the gate when banned phrase present."""
    from bot import _find_combat_lore_violations

    narrative = "📋 <b>The Setup</b>\nThis is the fight game.\n"
    reasons = _find_combat_lore_violations(narrative, sport)
    assert "combat_lore:the fight game" in reasons, (
        f"Combat-sport key {sport!r} did not trigger gate"
    )


# ── AC-3: gate 8e wiring — _validate_polish rejects combat-lore on MMA ──────


def _make_combat_spec():
    """Minimal NarrativeSpec for an MMA fixture."""
    from narrative_spec import NarrativeSpec

    return NarrativeSpec(
        home_name="Marshall Francis",
        away_name="Brennan Lucas",
        competition="UFC",
        sport="mma",
        home_story_type="neutral",
        away_story_type="neutral",
        outcome="home",
        outcome_label="Marshall Francis to win",
        bookmaker="SuperSportBet",
        odds=1.19,
        ev_pct=0.0,
        fair_prob_pct=84.0,
        composite_score=42.0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="lean",
        verdict_sizing="small stake",
        edge_tier="bronze",
    )


def _build_polish_passing_other_gates(includes: str) -> str:
    """Build a polish output that passes gates 1-8d, with controllable text in Setup."""
    return (
        "📋 <b>The Setup</b>\n"
        f"Marshall Francis hosts Brennan Lucas in a UFC matchup. {includes}\n\n"
        "🎯 <b>The Edge</b>\n"
        "SuperSportBet price Marshall Francis to win at 1.19. The fair probability "
        "sits at 84% — a thin sliver of edge but not enough to chase hard.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "The form gap on Lucas is real — he could land one clean shot and flip the script.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Live with the form-gap risk and lean Marshall Francis at 1.19 with SuperSportBet — "
        "small stake on the analytical lean, not a conviction play, and certainly nothing "
        "to overcommit on given how tight the price already is here."
    )


def test_validate_polish_rejects_combat_lore_on_mma():
    """Gate 8e: _validate_polish returns False when MMA polish contains banned lore."""
    import bot

    spec = _make_combat_spec()
    polished = _build_polish_passing_other_gates(
        "Historically the fight game rewards the home fighter."
    )
    baseline = polished
    evidence_pack = {"team_ratings": {}}

    result = bot._validate_polish(polished, baseline, spec, evidence_pack=evidence_pack)
    assert result is False, (
        "_validate_polish must reject MMA polish containing 'historically' + 'the fight game'"
    )


def test_validate_polish_accepts_clean_combat_polish():
    """Gate 8e control: clean combat polish passes when no banned phrases present."""
    import bot

    spec = _make_combat_spec()
    polished = _build_polish_passing_other_gates(
        "Both fighters enter the cage with sharp records on the SA card."
    )
    baseline = polished
    evidence_pack = {"team_ratings": {}}

    result = bot._validate_polish(polished, baseline, spec, evidence_pack=evidence_pack)
    assert result is True, (
        "_validate_polish must pass clean MMA polish when no combat-lore phrases present"
    )


def test_validate_polish_no_op_for_soccer_with_combat_phrase():
    """Gate 8e is sport-keyed — same banned phrase on a soccer spec passes gate 8e.

    (Polish may still fail other gates; we test gate 8e isolation by ensuring
    the polish contains the banned phrase but in a SOCCER spec the gate is bypassed.)
    """
    import bot
    from narrative_spec import NarrativeSpec

    soccer_spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Fulham",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        outcome="home",
        outcome_label="Arsenal home win",
        bookmaker="Hollywoodbets",
        odds=1.85,
        ev_pct=4.5,
        fair_prob_pct=58.0,
        composite_score=62.0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="lean",
        verdict_sizing="small stake",
        edge_tier="gold",
    )
    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal head into this strongly. Historically the fight game rewards home sides too.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets price Arsenal at 1.85. At a fair probability of 58% the gap "
        "is a 4.5% lean-tier expected value edge.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Saka fitness is the real concern — his absence dulls the left flank creator.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Discount the Saka fitness concern — Arsenal have cover on the wing. "
        "Back Arteta's side at 1.85 with Hollywoodbets, small stake on the lean."
    )
    # Confirm the lone gate under test (8e) does not fire for soccer.
    combat_reasons = bot._find_combat_lore_violations(polished, soccer_spec.sport)
    assert combat_reasons == [], (
        "Combat-lore gate must be no-op for soccer — sport-keyed isolation broken"
    )


# ── AC-5: format_evidence_prompt carries combat law for combat fixtures ──────


def _build_minimal_pack(sport: str):
    """Construct a minimal EvidencePack for prompt-building."""
    from evidence_pack import EvidencePack, EvidenceSource, SAOddsBlock

    src = EvidenceSource(available=True, fetched_at="", source_name="test", stale_minutes=0.0)
    return EvidencePack(
        match_key="a_vs_b_2026-05-02",
        sport=sport,
        league="UFC" if sport in {"mma", "boxing", "ufc", "bellator"} else "Premier League",
        built_at="2026-04-25T00:00:00+00:00",
        sa_odds=SAOddsBlock(provenance=src),
        richness_score="low",
        sources_available=3,
        sources_total=12,
    )


def _build_minimal_spec(sport: str):
    from narrative_spec import NarrativeSpec

    return NarrativeSpec(
        home_name="Fighter A",
        away_name="Fighter B",
        competition="UFC" if sport in {"mma", "boxing", "ufc", "bellator"} else "Premier League",
        sport=sport,
        home_story_type="neutral",
        away_story_type="neutral",
        outcome="home",
        outcome_label="Fighter A to win",
        bookmaker="SuperSportBet",
        odds=1.65,
        ev_pct=2.5,
        fair_prob_pct=60.0,
        composite_score=45.0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="lean",
        verdict_sizing="small stake",
        edge_tier="bronze",
    )


_COMBAT_PROMPT_MARKERS = (
    "COMBAT-SPORT EVIDENCE LAW",
    "FIX-NARRATIVE-MMA-LORE-01",
    "fighter_records",
    "the fight game",
    "in combat sports",
    "prefer brevity over fabrication",
)


def test_evidence_prompt_carries_combat_law_for_mma_edge_branch():
    """Edge branch (match_preview=False) carries combat-law block for MMA pack."""
    from evidence_pack import format_evidence_prompt

    pack = _build_minimal_pack("mma")
    spec = _build_minimal_spec("mma")
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    for marker in _COMBAT_PROMPT_MARKERS:
        assert marker in prompt, (
            f"Combat-law marker {marker!r} missing from edge-branch prompt for MMA fixture"
        )


def test_evidence_prompt_carries_combat_law_for_mma_match_preview_branch():
    """Match-preview branch (match_preview=True) carries combat-law block for MMA pack."""
    from evidence_pack import format_evidence_prompt

    pack = _build_minimal_pack("mma")
    spec = _build_minimal_spec("mma")
    prompt = format_evidence_prompt(pack, spec, match_preview=True)
    for marker in _COMBAT_PROMPT_MARKERS:
        assert marker in prompt, (
            f"Combat-law marker {marker!r} missing from match-preview-branch prompt for MMA fixture"
        )


def test_evidence_prompt_omits_combat_law_for_soccer():
    """Soccer fixtures do NOT receive combat-law block — sport-keyed."""
    from evidence_pack import format_evidence_prompt

    pack = _build_minimal_pack("soccer")
    spec = _build_minimal_spec("soccer")
    for branch in (False, True):
        prompt = format_evidence_prompt(pack, spec, match_preview=branch)
        assert "COMBAT-SPORT EVIDENCE LAW" not in prompt, (
            f"Combat-law block leaked into soccer prompt (match_preview={branch})"
        )
        assert "FIX-NARRATIVE-MMA-LORE-01" not in prompt, (
            f"Combat-law marker leaked into soccer prompt (match_preview={branch})"
        )


@pytest.mark.parametrize("sport", ["boxing", "ufc", "bellator", "one_fc"])
def test_evidence_prompt_combat_law_covers_all_combat_keys(sport):
    """All combat sport keys trigger the combat-law injection."""
    from evidence_pack import format_evidence_prompt

    pack = _build_minimal_pack(sport)
    spec = _build_minimal_spec(sport)
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert "COMBAT-SPORT EVIDENCE LAW" in prompt, (
        f"Combat-law block missing for sport={sport!r}"
    )
