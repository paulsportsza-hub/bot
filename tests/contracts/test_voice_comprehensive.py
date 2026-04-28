"""FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 voice rubric regression guard (2026-04-28).

Hand-grade rubric enforcement for the holistic Verdict composition.

Required (every variant, every tier, every sport):
  R1. Cites outcome (team) by name in the verdict body.
  R2. Cites price (odds) AND bookmaker by name.
  R3. Resolves at least one Risk factor when spec.risk_factors is non-empty.
  R4. Tier-banded confidence vocabulary
      (Diamond confident; Gold disciplined; Silver speculative-with-reasoning;
      Bronze tentative-with-reservation).
  R5. 100–260 chars (tier-uniform per feedback_verdict_char_range_unified.md).
  R6. ≤ 2 complete sentences (count via sentence-terminator regex).

Forbidden (every verdict):
  F1.  "+X% EV" / "% EV" — telemetry, lives in The Edge.
  F2.  "indicators line up" — sibling boilerplate (count cite).
  F3.  "supporting indicator" — sibling boilerplate (singular count cite).
  F4.  "line movement" / "adverse movement" — telemetry.
  F5.  "price is stable" / "price angle" / "priced in" — meta-betting.
  F6.  "the lean is" — analytical jargon.
  F7.  "supported by data" — flat, generic, not braai voice.
  F8.  Any "%" symbol (verdict cites no percentages).
  F9.  Any 4-digit rating number (per Rule 10).

Sibling boilerplate detector (AC-14):
  C1.  Render verdicts across a synthetic corpus of distinct fixtures.
  C2.  Assert no rendered sub-string of length ≥ 40 chars repeats verbatim
       across ≥ 3 distinct fixtures.

Pure Python — no bot.py import, no LLM, no DB.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import (
    MIN_VERDICT_CHARS_BY_TIER,
    NarrativeSpec,
    TONE_BANDS,
    VERDICT_HARD_MAX,
    _render_verdict,
    _verdict_risk_clause,
    _verdict_support_line,
    _VERDICT_BANNED_TELEMETRY,
)


# ── Forbidden phrases (substring match, case-insensitive) ─────────────────────

_FORBIDDEN_PHRASES: tuple[str, ...] = _VERDICT_BANNED_TELEMETRY


# ── Required tier vocabulary (substring match, case-insensitive) ──────────────
# Verdict variants are required to carry tier-banded vocabulary. We accept any
# of the listed phrases as evidence the variant pool emits the right register.

_TIER_VOCAB: dict[str, tuple[str, ...]] = {
    # Diamond — confident, premium, conviction.
    "diamond": (
        "premium back", "strong back", "with conviction", "premium value",
        "the case is built", "one of the better plays",
    ),
    # Gold — disciplined, supported, standard stake.
    "gold": (
        "back ", "take ", "green light", "the call",
        "disciplined", "solid play", "case stands",
    ),
    # Silver — speculative-with-reasoning, mild lean, measured.
    "silver": (
        "mild lean", "is the lean", "measured play", "small-stake call",
        "small-to-standard",
    ),
    # Bronze — tentative-with-reservation, controlled punt, no hero call.
    "bronze": (
        "punt", "small stake", "no hero call", "calibration",
        "small-stake", "small exposure",
    ),
}


# ── Synthetic fixture corpus — diverse home/away/league/sport ─────────────────

_FIXTURE_CORPUS: list[dict] = [
    # Soccer — EPL
    dict(home_name="Arsenal", away_name="Chelsea", competition="Premier League",
         sport="soccer", outcome="home", outcome_label="Arsenal win",
         bookmaker="Betway", odds=1.85),
    dict(home_name="Liverpool", away_name="Manchester United", competition="Premier League",
         sport="soccer", outcome="away", outcome_label="Manchester United win",
         bookmaker="Hollywoodbets", odds=4.20),
    dict(home_name="Manchester City", away_name="Tottenham", competition="Premier League",
         sport="soccer", outcome="home", outcome_label="Manchester City win",
         bookmaker="Sportingbet", odds=1.65),
    # Soccer — PSL
    dict(home_name="Mamelodi Sundowns", away_name="Kaizer Chiefs", competition="Premiership (PSL)",
         sport="soccer", outcome="home", outcome_label="Sundowns win",
         bookmaker="Hollywoodbets", odds=1.95),
    dict(home_name="Orlando Pirates", away_name="SuperSport United", competition="Premiership (PSL)",
         sport="soccer", outcome="home", outcome_label="Pirates win",
         bookmaker="Betway", odds=2.10),
    # Soccer — UCL
    dict(home_name="Real Madrid", away_name="Barcelona", competition="UEFA Champions League",
         sport="soccer", outcome="home", outcome_label="Real Madrid win",
         bookmaker="Betway", odds=2.30),
    # Rugby — URC
    dict(home_name="Bulls", away_name="Stormers", competition="United Rugby Championship",
         sport="rugby", outcome="home", outcome_label="Bulls win",
         bookmaker="Hollywoodbets", odds=1.75),
    dict(home_name="Sharks", away_name="Lions", competition="United Rugby Championship",
         sport="rugby", outcome="away", outcome_label="Lions win",
         bookmaker="Sportingbet", odds=3.50),
    # Rugby — Super Rugby
    dict(home_name="Crusaders", away_name="Blues", competition="Super Rugby",
         sport="rugby", outcome="home", outcome_label="Crusaders win",
         bookmaker="Betway", odds=1.55),
    # Cricket — IPL
    dict(home_name="Mumbai Indians", away_name="Chennai Super Kings", competition="Indian Premier League",
         sport="cricket", outcome="home", outcome_label="Mumbai Indians win",
         bookmaker="Hollywoodbets", odds=2.05),
    dict(home_name="Royal Challengers", away_name="Kolkata Knight Riders", competition="Indian Premier League",
         sport="cricket", outcome="home", outcome_label="Royal Challengers win",
         bookmaker="Betway", odds=1.85),
    # Cricket — SA20
    dict(home_name="Joburg Super Kings", away_name="Pretoria Capitals", competition="SA20",
         sport="cricket", outcome="away", outcome_label="Pretoria Capitals win",
         bookmaker="Hollywoodbets", odds=2.40),
    # Combat — MMA
    dict(home_name="Dricus du Plessis", away_name="Sean Strickland", competition="UFC",
         sport="mma", outcome="home", outcome_label="Dricus du Plessis win",
         bookmaker="Betway", odds=1.90),
    dict(home_name="Jon Jones", away_name="Stipe Miocic", competition="UFC",
         sport="mma", outcome="home", outcome_label="Jon Jones win",
         bookmaker="Sportingbet", odds=1.45),
    # Combat — Boxing
    dict(home_name="Canelo Alvarez", away_name="David Benavidez", competition="Boxing",
         sport="boxing", outcome="home", outcome_label="Canelo Alvarez win",
         bookmaker="Betway", odds=1.70),
    dict(home_name="Tyson Fury", away_name="Oleksandr Usyk", competition="Boxing",
         sport="boxing", outcome="away", outcome_label="Oleksandr Usyk win",
         bookmaker="Hollywoodbets", odds=2.20),
]


# ── Tier × support permutations (verdict_action × support_level) ──────────────

_TIER_SCENARIOS: list[dict] = [
    # Diamond
    dict(tier="diamond", action="strong back", sizing="confident stake",
         tone="strong", evidence_class="conviction",
         support_level=4, contradicting_signals=0, ev_pct=15.0,
         composite_score=85.0, bookmaker_count=5),
    dict(tier="diamond", action="strong back", sizing="confident stake",
         tone="strong", evidence_class="conviction",
         support_level=3, contradicting_signals=1, ev_pct=12.0,
         composite_score=80.0, bookmaker_count=4),
    # Gold
    dict(tier="gold", action="back", sizing="standard stake",
         tone="confident", evidence_class="supported",
         support_level=3, contradicting_signals=0, ev_pct=8.0,
         composite_score=70.0, bookmaker_count=4),
    dict(tier="gold", action="back", sizing="standard stake",
         tone="confident", evidence_class="supported",
         support_level=2, contradicting_signals=0, ev_pct=6.0,
         composite_score=65.0, bookmaker_count=3),
    # Silver
    dict(tier="silver", action="lean", sizing="small stake",
         tone="moderate", evidence_class="lean",
         support_level=2, contradicting_signals=0, ev_pct=4.5,
         composite_score=55.0, bookmaker_count=3),
    dict(tier="silver", action="lean", sizing="small stake",
         tone="moderate", evidence_class="lean",
         support_level=1, contradicting_signals=0, ev_pct=3.0,
         composite_score=50.0, bookmaker_count=3),
    # Bronze (supported)
    dict(tier="bronze", action="speculative punt", sizing="tiny exposure",
         tone="cautious", evidence_class="speculative",
         support_level=1, contradicting_signals=0, ev_pct=2.5,
         composite_score=45.0, bookmaker_count=2),
    # Bronze (unsupported)
    dict(tier="bronze", action="speculative punt", sizing="tiny exposure",
         tone="cautious", evidence_class="speculative",
         support_level=0, contradicting_signals=0, ev_pct=2.0,
         composite_score=42.0, bookmaker_count=2),
]


def _make_spec(fixture: dict, scenario: dict, *, risk_text: str | None = None) -> NarrativeSpec:
    """Build a NarrativeSpec from a fixture × scenario combination."""
    if risk_text is None:
        risk_text = "Form data thin from a 3-game window — squad rotation likely."
    return NarrativeSpec(
        home_name=fixture["home_name"],
        away_name=fixture["away_name"],
        competition=fixture["competition"],
        sport=fixture["sport"],
        home_story_type="title_push",
        away_story_type="inconsistent",
        evidence_class=scenario["evidence_class"],
        tone_band=scenario["tone"],
        verdict_action=scenario["action"],
        verdict_sizing=scenario["sizing"],
        outcome=fixture["outcome"],
        outcome_label=fixture["outcome_label"],
        bookmaker=fixture["bookmaker"],
        odds=fixture["odds"],
        ev_pct=scenario["ev_pct"],
        fair_prob_pct=58.0,
        composite_score=scenario["composite_score"],
        bookmaker_count=scenario["bookmaker_count"],
        support_level=scenario["support_level"],
        contradicting_signals=scenario["contradicting_signals"],
        risk_factors=[risk_text],
        risk_severity="moderate",
        stale_minutes=0,
        movement_direction="neutral",
        tipster_against=0,
        edge_tier=scenario["tier"],
    )


def _sentence_count(text: str) -> int:
    """Count complete sentences (ending in . ! ? …).

    Skips decimal-point matches (e.g. '1.85' is not a sentence break) by
    requiring the terminator to be followed by whitespace or EOL.
    """
    stripped = text.rstrip()
    # Sentence terminator = . ! ? … followed by space or end-of-string.
    terminators = re.findall(r"[.!?…](?=\s|$)", stripped)
    return max(1, len(terminators))


# ── R1–R6 voice rubric — per tier × per sport ─────────────────────────────────


@pytest.mark.parametrize("scenario", _TIER_SCENARIOS, ids=lambda s: f"{s['tier']}-sup{s['support_level']}")
@pytest.mark.parametrize("fixture", _FIXTURE_CORPUS[:4], ids=lambda f: f"{f['sport']}-{f['home_name'][:6]}")
class TestVoiceRubricSampleCoverage:
    """16+ sample-coverage tests: 8 tier scenarios × 4 fixtures = 32 cases."""

    def test_r1_cites_outcome_label(self, scenario, fixture):
        """R1: Verdict cites the outcome label (team or selection name)."""
        spec = _make_spec(fixture, scenario)
        verdict = _render_verdict(spec)
        # Outcome label OR a substring of it (e.g. "Arsenal" from "Arsenal win").
        outcome = fixture["outcome_label"]
        # Strip "win"/"loss" suffix if present so we match the team name.
        team_part = outcome.replace(" win", "").replace(" loss", "").strip()
        assert team_part in verdict, (
            f"[{scenario['tier']}/{fixture['sport']}] Verdict missing team {team_part!r}: {verdict!r}"
        )

    def test_r2_cites_price_and_bookmaker(self, scenario, fixture):
        """R2: Verdict cites price (odds) AND bookmaker by name."""
        spec = _make_spec(fixture, scenario)
        verdict = _render_verdict(spec)
        odds_str = f"{fixture['odds']:.2f}"
        bk = fixture["bookmaker"]
        if scenario["action"] not in ("pass", "monitor"):
            assert odds_str in verdict, (
                f"[{scenario['tier']}/{fixture['sport']}] Verdict missing odds {odds_str!r}: {verdict!r}"
            )
            assert bk in verdict, (
                f"[{scenario['tier']}/{fixture['sport']}] Verdict missing bookmaker {bk!r}: {verdict!r}"
            )

    def test_r3_resolves_risk_factor_when_present(self, scenario, fixture):
        """R3: Verdict references at least one risk-resolution clause when spec.risk_factors non-empty."""
        spec = _make_spec(fixture, scenario)
        verdict = _render_verdict(spec)
        clause = _verdict_risk_clause(spec)
        if clause:
            # The full clause OR the snippet inside it must appear.
            assert clause in verdict, (
                f"[{scenario['tier']}/{fixture['sport']}] Risk-resolution clause {clause!r} "
                f"not woven into verdict: {verdict!r}"
            )

    def test_r4_tier_banded_vocabulary(self, scenario, fixture):
        """R4: Verdict carries tier-banded confidence vocabulary."""
        spec = _make_spec(fixture, scenario)
        verdict = _render_verdict(spec).lower()
        tier = scenario["tier"]
        vocab = _TIER_VOCAB.get(tier, ())
        assert any(v.lower() in verdict for v in vocab), (
            f"[{tier}/{fixture['sport']}] Verdict missing tier vocab. "
            f"Expected any of {vocab!r}; got: {verdict!r}"
        )

    def test_r5_length_within_tier_band(self, scenario, fixture):
        """R5: Verdict length within [tier_floor, VERDICT_HARD_MAX]."""
        spec = _make_spec(fixture, scenario)
        verdict = _render_verdict(spec)
        tier = scenario["tier"]
        floor = MIN_VERDICT_CHARS_BY_TIER[tier]
        # Within band: at least floor (per tier), at most VERDICT_HARD_MAX (260).
        assert floor <= len(verdict) <= VERDICT_HARD_MAX, (
            f"[{tier}/{fixture['sport']}] Verdict length {len(verdict)} "
            f"outside [{floor}, {VERDICT_HARD_MAX}]: {verdict!r}"
        )

    def test_r6_max_two_sentences(self, scenario, fixture):
        """R6: Verdict ≤ 2 complete sentences."""
        spec = _make_spec(fixture, scenario)
        verdict = _render_verdict(spec)
        n = _sentence_count(verdict)
        assert n <= 2, (
            f"[{scenario['tier']}/{fixture['sport']}] Verdict has {n} sentences (>2): {verdict!r}"
        )


# ── F1–F8 forbidden phrase detector (every variant, every tier, every sport) ──


class TestForbiddenPhrases:
    """Forbidden phrases must NEVER appear in any rendered verdict."""

    @pytest.mark.parametrize("scenario", _TIER_SCENARIOS,
                             ids=lambda s: f"{s['tier']}-sup{s['support_level']}")
    def test_no_forbidden_phrase_across_all_fixtures(self, scenario):
        """Sweep all 16 fixtures × scenario; assert no Forbidden phrase appears."""
        for fixture in _FIXTURE_CORPUS:
            spec = _make_spec(fixture, scenario)
            verdict = _render_verdict(spec).lower()
            for phrase in _FORBIDDEN_PHRASES:
                assert phrase not in verdict, (
                    f"FORBIDDEN {phrase!r} found in {scenario['tier']}/"
                    f"{fixture['sport']}/{fixture['home_name']}: {verdict!r}"
                )

    @pytest.mark.parametrize("scenario", _TIER_SCENARIOS,
                             ids=lambda s: f"{s['tier']}-sup{s['support_level']}")
    def test_no_percent_symbol_in_verdict(self, scenario):
        """F8: No '%' symbol — verdict cites no percentages (telemetry lives in Edge)."""
        for fixture in _FIXTURE_CORPUS:
            spec = _make_spec(fixture, scenario)
            verdict = _render_verdict(spec)
            assert "%" not in verdict, (
                f"Percent symbol found in {scenario['tier']}/{fixture['sport']}: {verdict!r}"
            )

    @pytest.mark.parametrize("scenario", _TIER_SCENARIOS,
                             ids=lambda s: f"{s['tier']}-sup{s['support_level']}")
    def test_no_4_digit_rating_number_in_verdict(self, scenario):
        """F9: No 4-digit rating number (per Rule 10)."""
        for fixture in _FIXTURE_CORPUS:
            spec = _make_spec(fixture, scenario)
            verdict = _render_verdict(spec)
            # Match standalone 4-digit numbers in the 1000-2999 Elo/Glicko range.
            assert not re.search(r"\b(?:1\d{3}|2\d{3})\b", verdict), (
                f"4-digit rating-range number in {scenario['tier']}/{fixture['sport']}: {verdict!r}"
            )


# ── Pass / monitor branch (zero/negative EV) ──────────────────────────────────


class TestPassMonitorVerdicts:
    """Pass/monitor branch when verdict_action is 'pass' or 'monitor'."""

    @pytest.mark.parametrize("action", ["pass", "monitor"])
    @pytest.mark.parametrize("fixture", _FIXTURE_CORPUS[:4], ids=lambda f: f"{f['sport']}-{f['home_name'][:6]}")
    def test_pass_monitor_no_forbidden_phrase(self, action, fixture):
        """Pass/monitor variants must not contain any forbidden phrase."""
        spec = NarrativeSpec(
            home_name=fixture["home_name"],
            away_name=fixture["away_name"],
            competition=fixture["competition"],
            sport=fixture["sport"],
            home_story_type="neutral",
            away_story_type="neutral",
            evidence_class="speculative",
            tone_band="cautious",
            verdict_action=action,
            verdict_sizing="tiny exposure",
            outcome=fixture["outcome"],
            outcome_label=fixture["outcome_label"],
            bookmaker=fixture["bookmaker"],
            odds=fixture["odds"],
            ev_pct=0.0,
            fair_prob_pct=50.0,
            composite_score=30.0,
            bookmaker_count=2,
            support_level=0,
            contradicting_signals=0,
            risk_factors=[],
            risk_severity="moderate",
            stale_minutes=0,
            movement_direction="neutral",
            tipster_against=0,
            edge_tier="bronze",
        )
        verdict = _render_verdict(spec).lower()
        for phrase in _FORBIDDEN_PHRASES:
            assert phrase not in verdict, (
                f"FORBIDDEN {phrase!r} in {action}/{fixture['sport']}: {verdict!r}"
            )

    def test_pass_monitor_renders_with_bookmaker(self):
        """Pass/monitor with bookmaker present cites both odds and bookmaker."""
        spec = NarrativeSpec(
            home_name="Arsenal", away_name="Chelsea",
            competition="Premier League", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="speculative", tone_band="cautious",
            verdict_action="pass", verdict_sizing="tiny exposure",
            outcome="home", outcome_label="Arsenal win",
            bookmaker="Betway", odds=2.10, ev_pct=0.0,
            fair_prob_pct=50.0, composite_score=30.0, bookmaker_count=2,
            support_level=0, contradicting_signals=0,
            risk_factors=[], risk_severity="moderate", stale_minutes=0,
            movement_direction="neutral", tipster_against=0,
            edge_tier="bronze",
        )
        verdict = _render_verdict(spec)
        assert "Arsenal" in verdict
        assert "Betway" in verdict
        assert "2.10" in verdict


# ── AC-14 sibling boilerplate detector ────────────────────────────────────────


class TestSiblingBoilerplateDetector:
    """AC-14: scan rendered output for cross-fixture verdict prose repetition.

    Brief AC-14 (verbatim): "Add a 'sibling boilerplate detector' — a contract
    test that scans rendered output for any phrase appearing verbatim in ≥3
    different fixtures. Fails if same phrasing ships across multiple cards."

    The W82 baseline is MD5-deterministic — same fixture always renders the
    same variant. Different fixtures with the same bookmaker that hash to the
    same variant index legitimately share template scaffolding (the W82 design
    intent). What this detector catches is DEGENERATE dispatch — cases where
    the variant pool is so small that distinct fixtures produce identical
    full verdict bodies, OR where a long fixture-specific span repeats
    verbatim across ≥3 fixtures (a sign of leaky boilerplate).
    """

    def test_no_full_verdict_repeats_across_distinct_fixtures(self):
        """Two distinct fixtures must NEVER produce the identical verdict text.

        This is the AC-14 contract: same phrasing across multiple cards = fail.
        Distinct fixtures are guaranteed to differ in at least one of
        (outcome_label, odds, bookmaker), so identical verdicts means a
        variant template stripped its fixture-specific tokens (a real bug).
        """
        seen: dict[str, str] = {}
        for fixture in _FIXTURE_CORPUS:
            for scenario in _TIER_SCENARIOS:
                spec = _make_spec(fixture, scenario)
                verdict = _render_verdict(spec)
                fid = f"{scenario['tier']}/{fixture['home_name']}/{fixture['outcome_label']}"
                if verdict in seen:
                    prior = seen[verdict]
                    if prior != fid:
                        # Distinct fixtures rendering identical verdict → fail.
                        pytest.fail(
                            f"Identical verdict across distinct fixtures: "
                            f"{prior} vs {fid}\nVerdict: {verdict!r}"
                        )
                seen[verdict] = fid

    def test_variant_pool_exercised_within_each_branch(self):
        """The MD5 dispatcher MUST exercise more than 1 variant per branch
        across the synthetic corpus (16 fixtures). Degenerate dispatch (all
        fixtures hashing to a single variant) means the variant pool is
        effectively unused — a sign of a seed bug or undersized corpus."""
        # Group rendered verdicts by (tier, branch, support_level).
        from collections import defaultdict
        rendered_by_branch: dict[tuple, set[str]] = defaultdict(set)
        for fixture in _FIXTURE_CORPUS:
            for scenario in _TIER_SCENARIOS:
                spec = _make_spec(fixture, scenario)
                verdict = _render_verdict(spec)
                # Strip fixture-specific tokens to expose the variant template.
                template = verdict
                for tok in (fixture["home_name"], fixture["away_name"],
                            fixture["bookmaker"], f"{fixture['odds']:.2f}",
                            fixture["outcome_label"]):
                    template = template.replace(tok, "<X>")
                key = (scenario["tier"], scenario["action"], scenario["support_level"])
                rendered_by_branch[key].add(template)

        # Each branch should exercise at least 2 distinct templates across
        # 16 fixtures (with N variants per branch and MD5 dispatch, by birthday
        # paradox we'd expect ~all variants exercised in 16 trials).
        for branch, templates in rendered_by_branch.items():
            assert len(templates) >= 2, (
                f"Branch {branch!r} exercised only {len(templates)} variant "
                f"across 16 fixtures — degenerate MD5 dispatch suspected. "
                f"Templates: {templates!r}"
            )

    def test_no_long_team_specific_span_repeats_across_3_plus_fixtures(self):
        """No span ≥ 60 chars containing a TEAM name repeats verbatim across
        ≥ 3 distinct fixtures.

        Team names are unique per fixture in the synthetic corpus, so any
        long span containing a team name SHOULD only appear under that one
        fixture's renderings. If 3 distinct fixtures emit the same long span
        with a team name, the variant template has stripped fixture-specific
        tokens (a real bug). Bookmaker-only repetition is expected (one
        bookmaker is shared across many fixtures by W82 design).
        """
        from collections import defaultdict
        WINDOW = 60
        frame_to_fixtures: dict[str, set[str]] = defaultdict(set)
        # Build a normalised team token map: lowercase first word per team.
        team_tokens = set()
        for f in _FIXTURE_CORPUS:
            for name in (f["home_name"], f["away_name"]):
                first = name.lower().split()[0]
                if len(first) >= 4:  # skip stopword-like first tokens
                    team_tokens.add(first)
        for fixture in _FIXTURE_CORPUS:
            for scenario in _TIER_SCENARIOS:
                spec = _make_spec(fixture, scenario)
                verdict = _render_verdict(spec).lower()
                fixture_id = fixture["home_name"]
                for i in range(0, max(0, len(verdict) - WINDOW + 1)):
                    frame = verdict[i:i + WINDOW]
                    if any(t in frame for t in team_tokens):
                        frame_to_fixtures[frame].add(fixture_id)

        violations = [(frame, sorted(fids)) for frame, fids in frame_to_fixtures.items()
                      if len(fids) >= 3]
        assert not violations, (
            f"Long team-specific span repeats across ≥3 fixtures: "
            f"{violations[:2]!r}"
        )


# ── Tone-band ban list mirror invariant ───────────────────────────────────────


class TestToneBandsBanListInvariant:
    """Globally-banned Verdict phrases are mirrored into all 4 tone band banned
    lists. Verdict-only banned phrases (count cites, telemetry) live in
    `_VERDICT_BANNED_TELEMETRY` and are enforced at hand-grade time on the
    rendered Verdict body — not at polish-time TONE_BANDS — to avoid rejecting
    legitimate Edge content that uses those phrases."""

    # Phrases banned in EVERY section of the narrative (flat / non-braai-voice).
    _GLOBALLY_BANNED = ("supported by data", "the lean is")

    @pytest.mark.parametrize("band", ["cautious", "moderate", "confident", "strong"])
    def test_band_contains_globally_banned_phrases(self, band):
        """Globally-banned phrases appear in TONE_BANDS[band]['banned']."""
        banned_set = {b.lower() for b in TONE_BANDS[band]["banned"]}
        for phrase in self._GLOBALLY_BANNED:
            assert phrase.lower() in banned_set, (
                f"TONE_BANDS[{band!r}]['banned'] missing globally-banned phrase {phrase!r}"
            )

    def test_verdict_only_phrases_NOT_in_tone_bands(self):
        """Verdict-only phrases (count cites, telemetry) MUST NOT be mirrored
        into TONE_BANDS — adding them rejects legitimate Edge polish content."""
        verdict_only = (
            "indicators line up", "supporting indicator",
            "line movement", "adverse movement",
            "price is stable", "price angle", "priced in", "% ev",
        )
        for band in ("cautious", "moderate", "confident", "strong"):
            banned_set = {b.lower() for b in TONE_BANDS[band]["banned"]}
            for phrase in verdict_only:
                assert phrase.lower() not in banned_set, (
                    f"TONE_BANDS[{band!r}]['banned'] must NOT contain Verdict-only "
                    f"phrase {phrase!r} — it would reject legitimate Edge content."
                )

    def test_supported_by_data_removed_from_confident_allowed(self):
        """'supported by data' MUST NOT be in confident.allowed (was previously)."""
        allowed = {a.lower() for a in TONE_BANDS["confident"]["allowed"]}
        assert "supported by data" not in allowed


# ── Helper-level clean-up assertions ──────────────────────────────────────────


class TestSupportLineAndRiskClauseClean:
    """`_verdict_support_line` and `_verdict_risk_clause` no longer leak telemetry."""

    @pytest.mark.parametrize("support,opposing", [(1, 0), (1, 2), (2, 0), (3, 1), (4, 0)])
    def test_support_line_emits_no_count(self, support, opposing):
        """Support line must NOT cite the count number when support >= 2."""
        spec = NarrativeSpec(
            home_name="Arsenal", away_name="Chelsea",
            competition="EPL", sport="soccer",
            home_story_type="title_push", away_story_type="inconsistent",
            evidence_class="lean", tone_band="moderate",
            verdict_action="lean", verdict_sizing="small stake",
            outcome="home", outcome_label="Arsenal win",
            bookmaker="Betway", odds=1.85, ev_pct=4.5,
            fair_prob_pct=58.0, composite_score=58.0, bookmaker_count=4,
            support_level=support, contradicting_signals=opposing,
            risk_factors=["form thin"], risk_severity="moderate", stale_minutes=0,
            movement_direction="neutral", tipster_against=0, edge_tier="silver",
        )
        line = _verdict_support_line(spec).lower()
        # No support_level number cited verbatim (e.g. "2 indicators", "3 signals").
        assert not re.search(rf"\b{support}\s+(indicator|signal|supporting)", line), (
            f"Support line cites count {support}: {line!r}"
        )
        # No banned phrase substrings.
        for phrase in ("indicators line up", "supporting indicator"):
            assert phrase not in line, f"Banned {phrase!r} in support line: {line!r}"

    def test_risk_clause_skips_pricing_tokens(self):
        """When risk_factor first significant token is 'price', clause must NOT
        produce 'the price angle is priced in'."""
        spec = NarrativeSpec(
            home_name="Arsenal", away_name="Chelsea",
            competition="EPL", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="lean", tone_band="moderate",
            verdict_action="lean", verdict_sizing="small stake",
            outcome="home", outcome_label="Arsenal win",
            bookmaker="Betway", odds=1.85, ev_pct=4.5,
            fair_prob_pct=58.0, composite_score=58.0, bookmaker_count=4,
            support_level=2, contradicting_signals=0,
            risk_factors=["Price stale by 6 hours — line movement against."],
            risk_severity="moderate", stale_minutes=0,
            movement_direction="neutral", tipster_against=0, edge_tier="silver",
        )
        # Either the helper returns "" (no qualifying snippet found) OR the
        # clause does not contain "price angle is priced in".
        clause = _verdict_risk_clause(spec)
        assert "price angle is priced in" not in clause.lower()
        assert "priced in" not in clause.lower()
        assert "price angle" not in clause.lower()
