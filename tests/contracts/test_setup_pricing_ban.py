from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""FIX-PREGEN-SETUP-PRICING-LEAK-01 + -02 — Setup-section pricing-language ban.

Four layers of protection against Sonnet polish leaking pricing/probability
vocabulary into The Setup section.

1. Polish prompt text itself (BOTH edge and match_preview branches) contains the
   STRICT BAN instructions.
2. `_validate_polish()` gate 8a defensively rejects any polished output via TWO
   helpers running side-by-side:
     - `_find_stale_setup_patterns` mirrors the cache-read absolute-ban detector
       (decimal + price-context).
     - `_find_setup_strict_ban_violations` (FIX-02) catches integer-percentage
       probabilities, isolated banned tokens, and Elo-implied phrasing — the
       gap surfaced post-FIX-01 on everton_vs_manchester_city_2026-05-04.
3. The deterministic W82 baseline never produces banned vocabulary in Setup.
"""


import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()


_BANNED_TOKENS = [
    "bookmaker",
    "odds",
    "price",
    "priced",
    "implied",
    "implied probability",
    "implied chance",
    "fair probability",
    "fair value",
    "expected value",
    "model reads",
]


def _minimal_pack(sport: str = "soccer", league: str = "Premier League"):
    """Build a minimal EvidencePack for prompt-rendering."""
    from evidence_pack import EvidencePack

    return EvidencePack(
        match_key="home_vs_away_2026-05-02",
        sport=sport,
        league=league,
        built_at="2026-04-25T10:00:00Z",
    )


def _minimal_spec(home: str = "Arsenal", away: str = "Fulham"):
    """Build a minimal NarrativeSpec — just what format_evidence_prompt reads."""
    from narrative_spec import NarrativeSpec

    return NarrativeSpec(
        home_name=home,
        away_name=away,
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        outcome="home",
        outcome_label=f"{home} home win",
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


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — polish prompt text contains the STRICT BAN block.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.skip(
    reason=(
        "FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1: "
        "Setup/Edge/Risk section instructions stripped from polish prompt. "
        "The 'STRICT BAN' Setup-section block is no longer emitted. The "
        "polish path now produces verdict-only output and the new anchor "
        "block is covered by tests/contracts/test_verdict_prompt_anchors.py."
    )
)
def test_setup_instruction_contains_strict_ban_block():
    """Superseded — see test_verdict_prompt_anchors.py for the new spec."""


@pytest.mark.skip(
    reason=(
        "FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1: "
        "Setup/Edge/Risk section instructions stripped from polish prompt "
        "(both branches). Match-preview also produces verdict-only output."
    )
)
def test_match_preview_branch_strict_ban_block():
    """Superseded — see test_verdict_prompt_anchors.py for the new spec."""


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — _validate_polish defensively rejects Setup pricing leak.
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_polish_rejects_setup_pricing():
    """A polish output whose Setup contains 'implied probability of 85%' must
    be rejected by _validate_polish() (defensive gate 8a)."""
    import bot

    spec = _minimal_spec()

    # A polished output that satisfies every other validator gate (4 headers,
    # team names, bookmaker name + odds, no global banned phrases) but leaks
    # 'implied' + a decimal into The Setup. The detector's odds_in_setup branch
    # should fire; _validate_polish should return False.
    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal arrive in form. The Elo-implied home win probability is 85% "
        "and the model reads them at 1.85.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets are at 1.85, fair probability 58%, EV 4.5%.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Limited evidence depth on the away side.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Arsenal at 1.85 on Hollywoodbets — small stake play with the "
        "model and tipster backing aligned, sensible exposure for a gold-tier "
        "edge with tipster consensus pulling the same way."
    )
    baseline = polished  # baseline irrelevant for this gate

    assert bot._validate_polish(polished, baseline, spec) is False, (
        "defensive Setup-pricing gate failed to reject 'implied probability of 85%'"
    )


def test_validate_polish_accepts_clean_setup():
    """Sanity guard: a polished output with clean Setup prose passes the gate."""
    import bot

    spec = _minimal_spec()

    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal sit on 70 points with a strong recent run. Fulham are mid-table "
        "and have struggled away from home.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets are at 1.85, fair probability 58%, EV 4.5%.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Limited evidence depth on the away side — Fulham's away record is thin "
        "and there's no strong tipster consensus to anchor the reading.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Arsenal at 1.85 on Hollywoodbets — the limited evidence depth on "
        "the away side is already priced in; model and tipster backing aligned "
        "for sensible exposure at this gold-tier number."
    )
    baseline = polished

    assert bot._validate_polish(polished, baseline, spec) is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — W82 baseline never produces Setup pricing leaks.
# ─────────────────────────────────────────────────────────────────────────────


_BASELINE_FIXTURES = [
    # 5 soccer
    ("soccer", "Premier League", "Arsenal", "Fulham"),
    ("soccer", "Premier League", "Liverpool", "Crystal Palace"),
    ("soccer", "La Liga", "Real Madrid", "Sevilla"),
    ("soccer", "Champions League", "Paris Saint-Germain", "Bayern Munich"),
    ("soccer", "PSL", "Mamelodi Sundowns", "Kaizer Chiefs"),
    # 5 rugby
    ("rugby", "URC", "Bulls", "Stormers"),
    ("rugby", "URC", "Sharks", "Lions"),
    ("rugby", "URC", "Edinburgh", "Sharks"),
    ("rugby", "URC", "Benetton Treviso", "Leinster"),
    ("rugby", "Super Rugby", "Crusaders", "Brumbies"),
    # 5 cricket
    ("cricket", "IPL", "Royal Challengers Bengaluru", "Gujarat Titans"),
    ("cricket", "IPL", "Mumbai Indians", "Chennai Super Kings"),
    ("cricket", "SA20", "Sunrisers Eastern Cape", "Joburg Super Kings"),
    ("cricket", "T20I", "Bangladesh", "Sri Lanka"),
    ("cricket", "Test", "Australia", "India"),
    # 5 mma
    ("mma", "UFC", "Dricus Du Plessis", "Sean Strickland"),
    ("mma", "UFC", "Islam Makhachev", "Charles Oliveira"),
    ("mma", "UFC", "Alex Pereira", "Magomed Ankalaev"),
    ("mma", "UFC", "Tom Aspinall", "Curtis Blaydes"),
    ("mma", "UFC", "Ilia Topuria", "Max Holloway"),
    # 5 boxing (FIX-W82-BASELINE-PRICE-TALKING-01: extended sport coverage)
    ("boxing", "Major Bouts", "Tyson Fury", "Oleksandr Usyk"),
    ("boxing", "Major Bouts", "Canelo Alvarez", "Jermall Charlo"),
    ("boxing", "Major Bouts", "Terence Crawford", "Errol Spence"),
    ("boxing", "Major Bouts", "Naoya Inoue", "Stephen Fulton"),
    ("boxing", "Major Bouts", "Devin Haney", "Vasyl Lomachenko"),
]


@pytest.mark.parametrize("sport,league,home,away", _BASELINE_FIXTURES)
def test_baseline_setup_never_contains_pricing(sport, league, home, away):
    """W82 deterministic baseline must never emit Setup-section pricing language.

    Regression guard: if `_render_baseline()` is changed to inject odds/bookmaker
    vocabulary into Setup, this test catches it before users do.

    FIX-W82-BASELINE-PRICE-TALKING-01 (2026-04-27): now also asserts the
    polish-time strict-ban detector returns [] for W82 baseline. Pre-fix the
    `_render_setup_no_context` low-context variants leaked banned vocab into Setup
    (e.g. "let the price do the talking"); post-fix, all 4 sections are clean
    by construction. The brief moved this from "out of scope" (FIX-02) to active
    coverage (FIX-W82-BASELINE-PRICE-TALKING-01).
    """
    import bot
    from narrative_spec import build_narrative_spec, _render_baseline

    edge_data = {
        "home_team": home,
        "away_team": away,
        "league": league,
        "best_bookmaker": "Hollywoodbets",
        "best_odds": 1.85,
        "edge_pct": 4.5,
        "outcome": "home",
        "outcome_team": home,
        "confirming_signals": 2,
        "composite_score": 62.0,
        "bookmaker_count": 5,
        "stale_minutes": 0,
        "movement_direction": "neutral",
        "tipster_against": 0,
    }
    tips = [
        {
            "outcome": "home",
            "odds": 1.85,
            "bookie": "Hollywoodbets",
            "bookmaker": "Hollywoodbets",
            "ev": 4.5,
            "prob": 58.0,
            "home_team": home,
            "away_team": away,
        }
    ]

    spec = build_narrative_spec({}, edge_data, tips, sport)
    baseline = _render_baseline(spec)

    reasons = bot._find_stale_setup_patterns(baseline)
    assert reasons == [], (
        f"baseline Setup pricing leak in {sport} {home} vs {away}: {reasons}\n"
        f"--- baseline ---\n{baseline}"
    )

    # FIX-W82-BASELINE-PRICE-TALKING-01: the strict-ban detector now asserted too.
    # Pre-fix the `_render_setup_no_context` low-context variants emitted banned
    # vocab into Setup (e.g. "let the price do the talking", "lean on the price",
    # "what the odds say matters more"); post-fix, those variants are rewritten
    # in non-pricing language and this assertion guards against regression.
    strict_reasons = bot._find_setup_strict_ban_violations(baseline)
    assert strict_reasons == [], (
        f"FIX-W82-BASELINE-PRICE-TALKING-01 regression in {sport} {home} vs {away}: "
        f"{strict_reasons}\n--- baseline ---\n{baseline}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# FIX-W82-BASELINE-PRICE-TALKING-01 — Exhaustive fuzzing matrix (≥100 fixtures).
# ─────────────────────────────────────────────────────────────────────────────
#
# AC-3 expands the regression coverage from 25 base fixtures to ≥100 by sweeping
# each fixture across multiple `(composite_score, support_level, ev_pct, odds)`
# combinations. Each combination drives a different posture_band × signal_band ×
# ev_band × score_band path through `_render_setup_no_context`, exercising the
# full variant matrix. The previous 25-fixture coverage only hit a single posture
# point per fixture and missed the variant 4 ("market architecture / let the price
# do the talking") leak that lived in the `premium`/`thin` close_map branches.

# 5 coverage profiles drive different (posture × signal × ev × score) paths.
# Together these exercise every cell in the posture_map × close_map matrix.
_COVERAGE_PROFILES = [
    # (label, composite_score, confirming_signals, ev_pct, odds, stale_minutes)
    ("premium_confident_multi", 78.0, 3, 9.5, 1.55, 0),       # premium / confident / multi_signal
    ("solid_balanced_single",   55.0, 1, 4.0, 1.85, 0),       # solid / balanced / single_signal
    ("thin_cautious_no_signal", 42.0, 0, 1.2, 2.10, 0),       # thin / cautious / no_signal — variant 4 path
    ("premium_cautious_no",     65.0, 0, 1.5, 3.40, 0),       # premium / cautious / no_signal — live underdog
    ("solid_confident_no_sig",  56.0, 0, 8.5, 1.60, 5),       # solid / confident / no_signal — short fav
]


@pytest.mark.parametrize("sport,league,home,away", _BASELINE_FIXTURES)
@pytest.mark.parametrize("profile_label,composite,signals,ev,odds,stale",
                         _COVERAGE_PROFILES,
                         ids=[p[0] for p in _COVERAGE_PROFILES])
def test_baseline_setup_fuzzing_strict_ban_zero(
    sport, league, home, away,
    profile_label, composite, signals, ev, odds, stale,
):
    """FIX-W82-BASELINE-PRICE-TALKING-01 AC-3: exhaustive fuzzing — every
    sport × fixture × coverage-profile combination must produce zero strict-ban
    violations across the FULL baseline narrative (Setup, Edge, Risk, Verdict).

    Sweep size: 25 fixtures × 5 coverage profiles = 125 combinations (≥100).
    Each profile drives a different `(posture_band × signal_band × ev_band ×
    score_band)` cell in the variant matrix — together these exhaustively
    exercise every path through `_render_setup_no_context`.
    """
    import bot
    from narrative_spec import build_narrative_spec, _render_baseline

    edge_data = {
        "home_team": home,
        "away_team": away,
        "league": league,
        "best_bookmaker": "Hollywoodbets",
        "best_odds": odds,
        "edge_pct": ev,
        "outcome": "home",
        "outcome_team": home,
        "confirming_signals": signals,
        "composite_score": composite,
        "bookmaker_count": 5,
        "stale_minutes": stale,
        "movement_direction": "neutral",
        "tipster_against": 0,
    }
    tips = [
        {
            "outcome": "home",
            "odds": odds,
            "bookie": "Hollywoodbets",
            "bookmaker": "Hollywoodbets",
            "ev": ev,
            "prob": (1 + ev / 100.0) / odds * 100.0,
            "home_team": home,
            "away_team": away,
        }
    ]

    # Empty ctx_data → drives _render_setup_no_context (the path with the leak).
    spec = build_narrative_spec({}, edge_data, tips, sport)
    baseline = _render_baseline(spec)

    strict_reasons = bot._find_setup_strict_ban_violations(baseline)
    assert strict_reasons == [], (
        f"FIX-W82-BASELINE-PRICE-TALKING-01 regression: profile={profile_label} "
        f"{sport} {home} vs {away}: {strict_reasons}\n--- baseline ---\n{baseline}"
    )

    # Also confirm "market architecture" doesn't appear (not in the strict-ban
    # token list, so explicitly checked here per brief banned-tokens spec).
    assert "market architecture" not in baseline.lower(), (
        f"FIX-W82-BASELINE-PRICE-TALKING-01 'market architecture' leaked: "
        f"profile={profile_label} {sport} {home} vs {away}\n--- baseline ---\n{baseline}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# FIX-W82-BASELINE-PRICE-TALKING-01 — _validate_baseline_setup helper unit tests.
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_baseline_setup_is_callable():
    """AC-2: _validate_baseline_setup must exist on the bot module."""
    import bot

    assert callable(bot._validate_baseline_setup), (
        "_validate_baseline_setup must be exported as a module-level callable"
    )


def test_validate_baseline_setup_clean_returns_empty():
    """Clean Setup body returns []."""
    import bot

    text = _wrap_setup(
        "Arsenal sit second on 75 points after a four-match winning run. "
        "Fulham have lost three in a row and slip toward mid-table."
    )
    assert bot._validate_baseline_setup(text) == []


def test_validate_baseline_setup_flags_pricing_token():
    """Setup body containing a banned token returns non-empty reasons."""
    import bot

    text = _wrap_setup("The bookmaker has Arsenal at 1.45 here.")
    reasons = bot._validate_baseline_setup(text)
    assert reasons, "_validate_baseline_setup must flag bookmaker token"
    assert "banned_token:bookmaker" in reasons


def test_validate_baseline_setup_delegates_to_strict_ban():
    """_validate_baseline_setup runs BOTH the strict-ban enforcer AND the
    Phase 4 semantic detector. Result is the merged superset of both.

    FIX-NARRATIVE-ROT-ROOT-01 / Phase 4 / AC-4.1: the baseline-time validator
    no longer just delegates — it merges results from the keyword strict-ban
    detector and the new semantic-class detector. For inputs the semantic
    detector doesn't fire on, the result is identical to the strict-ban
    output (the original delegation contract is preserved for clean cases).
    For inputs both detectors fire on, the merged superset is returned.
    """
    import bot

    test_inputs = [
        _wrap_setup("Clean form-based context with no pricing vocabulary."),
        _wrap_setup("The implied chance favours the home side here."),
        _wrap_setup("The model reads 30% probability for an away win."),
        _wrap_setup("City have won four on the bounce coming in."),
    ]
    for text in test_inputs:
        baseline_result = bot._validate_baseline_setup(text)
        strict_result = bot._find_setup_strict_ban_violations(text)
        semantic_result = bot._find_setup_pricing_semantic_violations(text)
        # Order-preserving merge with duplicates collapsed.
        expected = list(dict.fromkeys(list(strict_result) + list(semantic_result)))
        assert baseline_result == expected, (
            f"_validate_baseline_setup must merge strict + semantic results "
            f"for: {text[:60]!r}\n"
            f"baseline_result={baseline_result}\nstrict_result={strict_result}\n"
            f"semantic_result={semantic_result}\nexpected={expected}"
        )
        # The strict result must remain a subset of the merged result (the
        # original delegation contract is preserved — semantic just adds).
        for r in strict_result:
            assert r in baseline_result


# ─────────────────────────────────────────────────────────────────────────────
# FIX-02 Test suite — _find_setup_strict_ban_violations helper unit tests.
# ─────────────────────────────────────────────────────────────────────────────


def _wrap_setup(setup_body: str) -> str:
    """Wrap a Setup body in the minimum HTML scaffold the extractor expects."""
    return (
        f"📋 <b>The Setup</b>\n{setup_body}\n\n"
        "🎯 <b>The Edge</b>\nE.\n\n"
        "⚠️ <b>The Risk</b>\nR.\n\n"
        "🏆 <b>Verdict</b>\nV."
    )


def test_strict_ban_helper_flags_elo_implied_integer_percentage():
    """FIX-02 AC-2(a): 'Elo-implied 30%'-style sentences must be flagged.

    This is the EXACT shape that bypassed the FIX-01 detector (no decimal,
    no qualifying price-cue word adjacent to a decimal — `_find_stale_setup_patterns`
    returned `[]` and the leak shipped to users)."""
    import bot

    text = _wrap_setup(
        "City are rated 150 points higher (1743 vs 1593), with the model "
        "putting Everton's home win probability at just 30%."
    )
    reasons = bot._find_setup_strict_ban_violations(text)
    assert reasons, f"helper missed Everton-style integer-prob leak: {reasons!r}"
    assert any("integer_probability" in r for r in reasons), (
        f"expected integer_probability reason; got {reasons!r}"
    )


def test_strict_ban_helper_flags_isolated_implied_token():
    """FIX-02 AC-2(c): 'the implied chance favours …' is flagged on the
    banned-token check even when no decimal-probability follows."""
    import bot

    text = _wrap_setup("The implied chance favours the home side here.")
    reasons = bot._find_setup_strict_ban_violations(text)
    assert any(r.startswith("banned_token:") for r in reasons), (
        f"expected banned_token reason; got {reasons!r}"
    )
    # Both 'implied' (substring) and 'implied chance' (full phrase) should fire.
    assert "banned_token:implied" in reasons
    assert "banned_token:implied chance" in reasons


def test_strict_ban_helper_flags_bookmaker_token():
    """FIX-02 AC-2(c): 'the bookmaker has the home side at' triggers
    banned_token:bookmaker."""
    import bot

    text = _wrap_setup("The bookmaker has the home side at 1.45 here.")
    reasons = bot._find_setup_strict_ban_violations(text)
    assert "banned_token:bookmaker" in reasons, (
        f"expected banned_token:bookmaker; got {reasons!r}"
    )


def test_strict_ban_helper_flags_fair_value_decimal():
    """FIX-02 AC-2(d): 'fair value of 1.85' triggers BOTH the banned_token
    check (fair value) AND the decimal_probability check (1.85)."""
    import bot

    text = _wrap_setup("The fair value of 1.85 sits well above market here.")
    reasons = bot._find_setup_strict_ban_violations(text)
    assert "banned_token:fair value" in reasons, f"expected fair value; got {reasons!r}"
    assert any("decimal_probability:1.85" in r for r in reasons), (
        f"expected decimal_probability:1.85; got {reasons!r}"
    )


def test_strict_ban_helper_returns_empty_for_clean_setup():
    """FIX-02 AC-2(e): clean Setup prose with metric-phrase decimals
    (`0.6 goals per game`) returns []."""
    import bot

    text = _wrap_setup(
        "Arsenal sit on 70 points with strong recent form and a 21-7-5 "
        "record. Fulham are mid-table averaging 0.6 goals per game."
    )
    reasons = bot._find_setup_strict_ban_violations(text)
    assert reasons == [], f"clean Setup wrongly flagged: {reasons!r}"


def test_strict_ban_helper_metric_phrase_carve_out_extends_to_runs_and_points():
    """Regression: the metric-phrase carve-out must cover all three sport vocabularies
    (`goals per game`, `points per game`, `runs per game`) — not just soccer."""
    import bot

    for metric in ("goals per game", "points per game", "runs per game"):
        text = _wrap_setup(f"Strong attack averaging 2.4 {metric} this run.")
        reasons = bot._find_setup_strict_ban_violations(text)
        assert reasons == [], (
            f"metric-phrase carveout failed for '{metric}': {reasons!r}"
        )


def test_validate_polish_rejects_everton_style_integer_probability():
    """FIX-02 AC-1: With Everton/City's CURRENT cache content fed to
    `_validate_polish` as a polish output, the gate MUST return False.

    This test reproduces the EXACT defect that motivated FIX-02: the
    Setup string `Elo-implied home win probability of just 30%` slipped
    past `_find_stale_setup_patterns` because it has no decimal and no
    qualifying price-cue adjacent to a decimal. The new strict-ban
    helper catches it via the integer-probability pattern."""
    import bot

    spec = _minimal_spec(home="Everton", away="Manchester City")
    polished = (
        "📋 <b>The Setup</b>\n"
        "Guardiola's City arrive at Goodison on 70 points with a 21-7-5 "
        "record and a current run of WWWDD — a side still grinding results "
        "when it matters. Moyes' Toffees sit on 47 points with a 13-8-12 "
        "record. The Elo gap is stark: City are rated 150 points higher "
        "(1743 vs 1593), with the model putting Everton's home win "
        "probability at just 30%.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets are at 1.85, fair probability 58%, EV 4.5%.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Limited evidence depth on the away side.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Everton at 1.85 on Hollywoodbets — small stake play with the "
        "model and tipster backing aligned, sensible exposure for a gold-tier "
        "edge with tipster consensus pulling the same way."
    )
    baseline = polished

    assert bot._validate_polish(polished, baseline, spec) is False, (
        "FIX-02 gate failed to reject Everton-style integer-probability leak"
    )
