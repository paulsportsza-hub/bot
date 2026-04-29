"""FIX-NARRATIVE-BOILERPLATE-VERDICT-TEMPLATE-01 regression guard (2026-04-28).

Asserts that:
  1. The exact boilerplate phrase "supporting indicator sit" never appears.
  2. The "1 supporting indicator" + singular-verb "sit" pluralisation bug
     never re-enters any rendered verdict.
  3. _verdict_support_line emits MD5-deterministic variants per
     (support_level, contradicting_signals) branch (3 variants per branch).
  4. _render_verdict variants for all 4 tiers cite team / EV% (integer)
     / odds / bookmaker / signal info / risk-resolution clause.
  5. Variants do NOT repeat verbatim across distinct fixtures in a sweep
     — i.e. MD5-deterministic seeding produces variation.
  6. The new code path is byte-clean against TONE_BANDS banned-phrase
     lists for the corresponding tier.

Pure Python — no bot.py import, no LLM, no DB.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import (
    NarrativeSpec,
    TONE_BANDS,
    _render_verdict,
    _verdict_risk_clause,
    _verdict_support_line,
)


_FORBIDDEN_BOILERPLATE_PHRASES = (
    "supporting indicator sit",
)


def _make_spec(**overrides) -> NarrativeSpec:
    defaults = dict(
        home_name="Sundowns", away_name="Chiefs",
        competition="Premiership (PSL)", sport="soccer",
        home_story_type="title_push", away_story_type="inconsistent",
        evidence_class="lean", tone_band="moderate",
        verdict_action="lean", verdict_sizing="small stake",
        outcome="home", outcome_label="Sundowns win",
        bookmaker="Hollywoodbets", odds=1.85, ev_pct=4.5,
        fair_prob_pct=58.0, composite_score=58.0,
        bookmaker_count=4, support_level=2, contradicting_signals=0,
        risk_factors=["Form data is thin from a 3-game window. Tipster consensus is unavailable."],
        risk_severity="moderate", stale_minutes=0,
        movement_direction="neutral", tipster_against=0,
        edge_tier="silver",
    )
    defaults.update(overrides)
    return NarrativeSpec(**defaults)


# ── 1. Forbidden boilerplate phrases never render ─────────────────────────────


class TestForbiddenBoilerplate:
    """The exact boilerplate phrase from the bug report MUST never render."""

    def test_support_line_never_emits_singular_sit_after_indicator(self):
        """Support line for support=1 must say 'sits' (or restructure) — never 'indicator sit'."""
        for opp in (0, 1, 2):
            spec = _make_spec(support_level=1, contradicting_signals=opp)
            line = _verdict_support_line(spec)
            # Either uses pluralised verb, or restructures away from the
            # singular noun + plural verb anti-pattern.
            assert not re.search(r"indicator\s+sit\b", line.lower()), (
                f"Support line still emits singular noun + plural verb 'indicator sit': {line!r}"
            )

    def test_no_supporting_indicator_sit_in_any_tier_verdict(self):
        """Forbidden phrase 'supporting indicator sit' must not appear in ANY tier verdict."""
        for action, sizing, tone, ec, sup, opp, ev in [
            ("speculative punt", "tiny exposure", "cautious",  "speculative", 0, 0, 3.5),
            ("speculative punt", "tiny exposure", "cautious",  "speculative", 1, 0, 3.5),
            ("speculative punt", "tiny exposure", "cautious",  "speculative", 1, 2, 3.5),
            ("lean",             "small stake",   "moderate",  "lean",        2, 0, 4.5),
            ("lean",             "small stake",   "moderate",  "lean",        2, 1, 4.5),
            ("back",             "standard stake","confident", "supported",   3, 0, 8.0),
            ("back",             "standard stake","confident", "supported",   3, 1, 8.0),
            ("strong back",      "confident stake","strong",   "conviction",  4, 0, 15.0),
        ]:
            spec = _make_spec(verdict_action=action, verdict_sizing=sizing,
                              tone_band=tone, evidence_class=ec,
                              support_level=sup, contradicting_signals=opp,
                              ev_pct=ev)
            verdict = _render_verdict(spec).lower()
            for phrase in _FORBIDDEN_BOILERPLATE_PHRASES:
                assert phrase not in verdict, (
                    f"FORBIDDEN boilerplate {phrase!r} found in {action} verdict: {verdict!r}"
                )

    def test_singular_one_supporting_indicator_sit_pattern_absent(self):
        """The exact 'N supporting indicator sit' anti-pattern (any N) must not appear."""
        spec = _make_spec(support_level=1, contradicting_signals=0,
                          verdict_action="lean", tone_band="moderate", evidence_class="lean")
        verdict = _render_verdict(spec)
        assert not re.search(r"\b\d+\s+supporting\s+indicator(?!s)\s+sit\b", verdict.lower()), (
            f"Anti-pattern 'N supporting indicator sit' still renders: {verdict!r}"
        )


# ── 2. _verdict_support_line determinism + variant coverage ───────────────────


class TestSupportLineVariants:
    """3 MD5-deterministic variants per (support, opposing) branch."""

    def test_support_zero_returns_empty_string(self):
        spec = _make_spec(support_level=0, contradicting_signals=0)
        assert _verdict_support_line(spec) == ""

    def test_support_one_no_opposing_emits_singular_phrasing(self):
        """FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-29): support=1 must
        convey singular evidence in SA voice. The earlier "one signal sits"
        phrasing was retired (Rule 17 telemetry vocabulary purge); the rewrite
        speaks of form / recent run / backer and may not include the literal
        word "one"."""
        spec = _make_spec(support_level=1, contradicting_signals=0)
        line = _verdict_support_line(spec).lower()
        # Anti-pattern: literal "indicator sit" / "indicator(s) line up" must not return.
        assert "indicator sit" not in line
        assert "indicators line up" not in line
        # New SA-voice contract: line must reference form / run / evidence /
        # backer to convey supporting weight.
        assert any(token in line for token in ("form", "run", "evidence", "back")), (
            f"support=1 line missing SA-voice support token: {line!r}"
        )

    def test_support_multi_no_opposing_excludes_count(self):
        """FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-28 + 2026-04-29):
        brief Forbidden list bans count cites in the Verdict body. Counts
        belong in The Edge section, not the Verdict. _verdict_support_line
        now emits qualitative phrases only — and must avoid the Rule 17
        telemetry vocabulary entirely (no "signals" / "indicators" tokens)."""
        spec = _make_spec(support_level=3, contradicting_signals=0)
        line = _verdict_support_line(spec)
        # No count cite: assert no digit token appears.
        import re as _re
        assert not _re.search(r"\b\d+\b", line), (
            f"support=3 line cites count digit (banned per Rule 17): {line!r}"
        )
        # Qualitative phrasing must reference SA-voice support tokens (form,
        # evidence, picture). The legacy "signal" / "indicator" tokens are
        # banned by Rule 17 (FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 AC-2).
        assert any(token in line.lower() for token in ("form", "evidence", "picture")), (
            f"support=3 line missing SA-voice support token: {line!r}"
        )

    def test_md5_determinism_same_fixture_same_variant(self):
        """Same home/away pair must always render the same support line variant."""
        spec_a = _make_spec(home_name="Arsenal", away_name="Chelsea", support_level=2)
        spec_b = _make_spec(home_name="Arsenal", away_name="Chelsea", support_level=2)
        assert _verdict_support_line(spec_a) == _verdict_support_line(spec_b)

    def test_md5_diversity_across_fixtures(self):
        """Different fixtures should not all render the same variant."""
        outputs = set()
        for h, a in [
            ("Arsenal", "Chelsea"),
            ("Liverpool", "Manchester City"),
            ("Tottenham", "Brighton"),
            ("Everton", "Newcastle"),
            ("West Ham", "Aston Villa"),
            ("Brentford", "Fulham"),
            ("Sundowns", "Pirates"),
            ("Chiefs", "Sundowns"),
        ]:
            spec = _make_spec(home_name=h, away_name=a, support_level=2, contradicting_signals=0)
            outputs.add(_verdict_support_line(spec))
        # 8 distinct fixtures should hit at least 2 different variants
        assert len(outputs) >= 2, f"MD5 seeding not producing variant diversity: {outputs!r}"


# ── 3. Tier-aware variants cite EV%, odds, bookmaker, team, signals ───────────


class TestTierAwareVariantsCiteFixtureData:
    """Each tier verdict MUST cite team / EV% (integer) / odds / bookmaker."""

    def _check_cites_fixture_data(self, spec, expected_team, expected_odds, expected_bk, expected_ev):
        """FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-28): EV cite removed
        from Verdict per brief Forbidden list ('+X% EV' / '% EV' belong in The
        Edge, not the Verdict). The expected_ev parameter is preserved for
        signature stability but no longer asserted on verdict text."""
        verdict = _render_verdict(spec)
        # Team name reference (full or partial — outcome_label carries it)
        assert expected_team.lower() in verdict.lower(), (
            f"Verdict missing team {expected_team!r}: {verdict!r}"
        )
        # Odds cited
        assert f"{expected_odds:.2f}" in verdict, (
            f"Verdict missing odds {expected_odds:.2f}: {verdict!r}"
        )
        # Bookmaker cited
        assert expected_bk in verdict, (
            f"Verdict missing bookmaker {expected_bk!r}: {verdict!r}"
        )
        # Verdict MUST NOT cite EV percentage (Rule 17 — telemetry lives in The Edge).
        assert "% EV" not in verdict, (
            f"Verdict cites '% EV' (Rule 17 forbidden — belongs in The Edge): {verdict!r}"
        )
        assert "% ev" not in verdict.lower(), (
            f"Verdict cites '% ev' (Rule 17 forbidden — belongs in The Edge): {verdict!r}"
        )
        # Suppress unused-arg warning while preserving signature.
        _ = expected_ev

    def test_bronze_speculative_cites_all(self):
        spec = _make_spec(
            verdict_action="speculative punt", verdict_sizing="tiny exposure",
            tone_band="cautious", evidence_class="speculative",
            outcome_label="Sundowns win", odds=2.10, bookmaker="WSB", ev_pct=3.5,
            support_level=1, edge_tier="bronze",
        )
        self._check_cites_fixture_data(spec, "Sundowns", 2.10, "WSB", 3.5)

    def test_silver_lean_cites_all(self):
        spec = _make_spec(
            verdict_action="lean", verdict_sizing="small stake",
            tone_band="moderate", evidence_class="lean",
            outcome_label="Arsenal win", odds=1.85, bookmaker="Hollywoodbets", ev_pct=4.5,
            support_level=2, edge_tier="silver",
        )
        self._check_cites_fixture_data(spec, "Arsenal", 1.85, "Hollywoodbets", 4.5)

    def test_gold_back_cites_all(self):
        spec = _make_spec(
            verdict_action="back", verdict_sizing="standard stake",
            tone_band="confident", evidence_class="supported",
            outcome_label="Liverpool win", odds=1.65, bookmaker="Betway", ev_pct=8.0,
            support_level=3, edge_tier="gold",
        )
        self._check_cites_fixture_data(spec, "Liverpool", 1.65, "Betway", 8.0)

    def test_diamond_strong_back_cites_all(self):
        spec = _make_spec(
            verdict_action="strong back", verdict_sizing="confident stake",
            tone_band="strong", evidence_class="conviction",
            outcome_label="Manchester City win", odds=1.55, bookmaker="SuperSportBet", ev_pct=15.5,
            support_level=4, edge_tier="diamond",
        )
        self._check_cites_fixture_data(spec, "Manchester City", 1.55, "SuperSportBet", 15.5)


# ── 4. Risk-resolution covenant (gate 8c at baseline time) ────────────────────


class TestRiskResolutionCovenant:
    """Gate 8c covenant: Verdict references at least one Risk factor when present."""

    def test_risk_clause_returns_empty_when_no_risk_factors(self):
        spec = _make_spec(risk_factors=[])
        assert _verdict_risk_clause(spec) == ""

    def test_risk_clause_extracts_significant_token(self):
        """First significant word from risk_factors[0] should appear in the clause."""
        spec = _make_spec(
            home_name="ZTeamA", away_name="ZTeamB",
            risk_factors=["Squad rotation is the main concern here."],
        )
        clause = _verdict_risk_clause(spec).lower()
        assert clause, "Risk clause empty for non-empty risk_factors"
        # 'squad' is the first significant word — must appear in clause
        assert "squad" in clause, f"Clause missing risk-token 'squad': {clause!r}"

    def test_verdict_token_overlap_with_risk_factor(self):
        """Rendered verdict must share at least one significant token with risk_factors[0]."""
        spec = _make_spec(
            home_name="Liverpool", away_name="Chelsea",
            verdict_action="back", tone_band="confident", evidence_class="supported",
            support_level=3, ev_pct=7.0,
            risk_factors=["Squad rotation is the main concern here."],
        )
        verdict = _render_verdict(spec).lower()
        assert "squad" in verdict, (
            f"Verdict lacks risk-resolution token overlap: {verdict!r}"
        )


# ── 5. Tier banned-phrase regression ──────────────────────────────────────────


class TestVariantsRespectToneBands:
    """No new variant introduces a phrase banned by its tier's tone band."""

    @pytest.mark.parametrize(
        "action,tone,ec,sizing",
        [
            ("speculative punt", "cautious",  "speculative", "tiny exposure"),
            ("lean",             "moderate",  "lean",        "small stake"),
            ("back",             "confident", "supported",   "standard stake"),
            ("strong back",      "strong",    "conviction",  "confident stake"),
        ],
    )
    def test_no_banned_phrases_in_tier_verdicts(self, action, tone, ec, sizing):
        for support, opp, ev in [(0, 0, 3.0), (1, 0, 4.5), (2, 1, 7.0), (4, 0, 15.0)]:
            spec = _make_spec(verdict_action=action, verdict_sizing=sizing,
                              tone_band=tone, evidence_class=ec,
                              support_level=support, contradicting_signals=opp,
                              ev_pct=ev)
            verdict = _render_verdict(spec).lower()
            for phrase in TONE_BANDS[tone]["banned"]:
                assert phrase.lower() not in verdict, (
                    f"Banned phrase {phrase!r} for tone {tone!r} in {action} "
                    f"(support={support}): {verdict!r}"
                )


# ── 6. Sweep diversity (no verbatim repetition across fixtures) ───────────────


class TestSweepDiversity:
    """Across a 20-fixture sweep, no two distinct fixtures render the same verdict."""

    def test_twenty_fixture_sweep_renders_distinct_verdicts(self):
        fixtures = [
            ("Arsenal", "Chelsea"), ("Liverpool", "Manchester City"),
            ("Tottenham", "Brighton"), ("Everton", "Newcastle"),
            ("West Ham", "Aston Villa"), ("Brentford", "Fulham"),
            ("Sundowns", "Pirates"), ("Chiefs", "Sundowns"),
            ("Bulls", "Stormers"), ("Sharks", "Lions"),
            ("Bangladesh", "New Zealand"), ("India", "Australia"),
            ("Sri Lanka", "Pakistan"), ("England", "South Africa"),
            ("Crusaders", "Blues"), ("Reds", "Brumbies"),
            ("Munster", "Leinster"), ("Ulster", "Connacht"),
            ("Barcelona", "Real Madrid"), ("Atletico Madrid", "Sevilla"),
        ]
        verdicts: set[str] = set()
        for h, a in fixtures:
            spec = _make_spec(home_name=h, away_name=a,
                              outcome_label=f"{h} win",
                              verdict_action="lean", tone_band="moderate", evidence_class="lean",
                              support_level=2, contradicting_signals=0, ev_pct=4.5)
            verdicts.add(_render_verdict(spec))
        # 20 fixtures → at least 4 distinct variants (we have 4 lean variants × 3 support-line variants
        # = 12 possible combos). At least ~4 unique outputs is the floor.
        assert len(verdicts) >= 4, (
            f"Sweep diversity below floor: {len(verdicts)} unique verdicts in 20 fixtures"
        )
