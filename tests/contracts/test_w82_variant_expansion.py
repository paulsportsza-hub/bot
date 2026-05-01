"""FIX-NARRATIVE-W82-VARIANT-EXPANSION-01 — AC-5 contract tests.

Twelve tests covering:
  - Variant pool size + closure rule + telemetry vocabulary + char range
    (parametrised across the 7-pattern pool)
  - MD5-seeded selection determinism + uniform distribution
  - Nickname / manager surname / venue references when available
  - Banned-phrase scan against the canonical TELEMETRY_VOCABULARY_PATTERNS
  - Pool diversity post-render (≥5 distinct opening hashes across 30 fixtures)
  - _render_baseline idempotence on repeated calls for the same fixture
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import (
    NarrativeSpec,
    _W82_VARIANT_PATTERNS,
    _action_verb_w82,
    _render_baseline,
    _render_verdict_w82_pool,
    _select_w82_variant,
    _sizing_w82,
    lookup_nickname,
)
from narrative_validator import (
    TELEMETRY_VOCABULARY_PATTERNS,
    _VERDICT_ACTION_RE,
    _VERDICT_ODDS_RE,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_spec(
    home: str = "Liverpool",
    away: str = "Chelsea",
    *,
    tier: str = "gold",
    action: str = "back",
    coach: str = "Arne Slot",
    venue: str = "Anfield",
    home_form: str = "WWWDW",
    away_form: str = "LWLDL",
    home_pos: int | None = 2,
    away_pos: int | None = 10,
    odds: float = 1.65,
    bookmaker: str = "Supabets",
    risk_factors: list[str] | None = None,
) -> NarrativeSpec:
    return NarrativeSpec(
        home_name=home,
        away_name=away,
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="inconsistent",
        home_coach=coach,
        away_coach="",
        home_position=home_pos,
        away_position=away_pos,
        home_points=68 if home_pos else None,
        away_points=42 if away_pos else None,
        home_form=home_form,
        away_form=away_form,
        outcome="home",
        outcome_label=home,
        bookmaker=bookmaker,
        odds=odds,
        ev_pct=4.5,
        fair_prob_pct=63.0,
        composite_score=70.0,
        bookmaker_count=4,
        support_level=2,
        contradicting_signals=0,
        evidence_class="supported",
        tone_band="confident",
        risk_factors=risk_factors if risk_factors is not None else ["Squad rotation possible after midweek UCL"],
        risk_severity="moderate",
        verdict_action=action,
        verdict_sizing="standard stake",
        edge_tier=tier,
        venue=venue,
    )


def _last_sentence(text: str) -> str:
    parts = re.split(r"[.!?]\s+", text.strip())
    nonempty = [p.strip() for p in parts if p and p.strip()]
    return nonempty[-1].rstrip(" \t.!?;,…—–-").strip() if nonempty else ""


def _opening_hash(verdict_text: str) -> str:
    """Hash first 8 lowercased whitespace-normalised tokens of a verdict."""
    tokens = verdict_text.lower().split()
    head = " ".join(tokens[:8])
    return hashlib.md5(head.encode("utf-8")).hexdigest()[:8]


# ── Test 1: pool size ─────────────────────────────────────────────────────────

def test_variant_pool_has_at_least_5_imperative_closing_variants():
    """The W82 pool must carry at least 5 imperative-closing variants (AC-3)."""
    assert len(_W82_VARIANT_PATTERNS) >= 5, (
        f"_W82_VARIANT_PATTERNS has {len(_W82_VARIANT_PATTERNS)} entries; "
        f"AC-3 requires ≥5 NEW imperative-closing variants."
    )


# ── Test 2: telemetry vocabulary ──────────────────────────────────────────────

@pytest.mark.parametrize("pattern_index", range(len(_W82_VARIANT_PATTERNS)))
def test_each_variant_passes_telemetry_vocabulary_gate(pattern_index):
    """No variant may emit any phrase from TELEMETRY_VOCABULARY_PATTERNS."""
    spec = _make_spec()
    verb = _action_verb_w82(spec.verdict_action, spec.edge_tier)
    sizing = _sizing_w82(spec.verdict_action, spec.edge_tier)
    text = _W82_VARIANT_PATTERNS[pattern_index](spec, verb, sizing)
    for pat, label in TELEMETRY_VOCABULARY_PATTERNS:
        compiled = re.compile(pat, re.IGNORECASE)
        assert not compiled.search(text), (
            f"Variant {pattern_index} ({_W82_VARIANT_PATTERNS[pattern_index].__name__}) "
            f"emits banned telemetry phrase '{label}': {text!r}"
        )


# ── Test 3: closure rule ──────────────────────────────────────────────────────

@pytest.mark.parametrize("pattern_index", range(len(_W82_VARIANT_PATTERNS)))
def test_each_variant_passes_closure_rule_gate(pattern_index):
    """Every variant's closing sentence must carry action verb + team + odds.

    Mirrors narrative_validator._check_verdict_closure_rule for Diamond/Gold
    (strict — all 3 components in the LAST sentence).
    """
    spec = _make_spec()
    verb = _action_verb_w82(spec.verdict_action, spec.edge_tier)
    sizing = _sizing_w82(spec.verdict_action, spec.edge_tier)
    text = _W82_VARIANT_PATTERNS[pattern_index](spec, verb, sizing)
    last = _last_sentence(text)
    assert _VERDICT_ACTION_RE.search(last), (
        f"Variant {pattern_index} last sentence missing action verb: {last!r}"
    )
    assert _VERDICT_ODDS_RE.search(last), (
        f"Variant {pattern_index} last sentence missing odds: {last!r}"
    )
    assert spec.home_name.lower() in last.lower(), (
        f"Variant {pattern_index} last sentence missing team name: {last!r}"
    )


# ── Test 4: char range ────────────────────────────────────────────────────────

@pytest.mark.parametrize("pattern_index", range(len(_W82_VARIANT_PATTERNS)))
def test_each_variant_passes_char_range_100_260(pattern_index):
    """Each rendered variant fits the W82 verdict char window (100-260)."""
    spec = _make_spec()
    verb = _action_verb_w82(spec.verdict_action, spec.edge_tier)
    sizing = _sizing_w82(spec.verdict_action, spec.edge_tier)
    text = _W82_VARIANT_PATTERNS[pattern_index](spec, verb, sizing)
    assert 100 <= len(text) <= 260, (
        f"Variant {pattern_index} ({_W82_VARIANT_PATTERNS[pattern_index].__name__}) "
        f"char count {len(text)} outside [100,260]: {text!r}"
    )


# ── Test 5: MD5 determinism ───────────────────────────────────────────────────

def test_md5_seeded_selection_deterministic():
    """Same (home, away, tier) input → same variant index every call."""
    cases = [
        ("Liverpool", "Chelsea", "gold"),
        ("Manchester City", "Brentford", "diamond"),
        ("Brighton", "Wolves", "silver"),
        ("Stade Toulousain", "Munster", "silver"),
    ]
    n = len(_W82_VARIANT_PATTERNS)
    for home, away, tier in cases:
        first = _select_w82_variant(home, away, tier, n)
        # Should give same result across 100 calls
        for _ in range(100):
            assert _select_w82_variant(home, away, tier, n) == first


# ── Test 6: uniform distribution ──────────────────────────────────────────────

def test_md5_seeded_selection_distributes_uniform():
    """Synthetic match-keys distribute approximately uniformly across the pool.

    Brief AC-5 specifies "100 synthetic match-keys, distribution within ±25%
    of uniform". With 7 variants and 100 samples, expected per-bucket count is
    14.3 with a binomial standard deviation of ~3.5 — meaning a real MD5 will
    naturally produce a distribution exceeding ±25% on small samples just from
    sampling noise. We use a 500-sample harness to converge on the true MD5
    distribution and verify it falls within ±25% of expected.

    Catches the broken-selector failure modes the brief intends:
      - Constant return (all 0%, max 100%) → fails immediately
      - Skewed selector (all to first variant) → fails
      - Real MD5 → passes consistently
    """
    n_variants = len(_W82_VARIANT_PATTERNS)
    counts = [0] * n_variants
    home_teams = [f"Home{i}" for i in range(25)]
    away_teams = [f"Away{j}" for j in range(20)]
    n_samples = len(home_teams) * len(away_teams)  # 500
    for h in home_teams:
        for a in away_teams:
            idx = _select_w82_variant(h, a, "gold", n_variants)
            counts[idx] += 1
    expected = n_samples / n_variants
    lower = expected * 0.75
    upper = expected * 1.25
    for i, c in enumerate(counts):
        assert lower <= c <= upper, (
            f"Variant {i} count {c} outside ±25% of expected {expected:.1f} "
            f"(bounds [{lower:.1f}, {upper:.1f}]); full distribution: {counts}"
        )


# ── Test 7: nickname when available ───────────────────────────────────────────

def test_variant_uses_team_nickname_when_available():
    """At least one variant references the curated nickname for an EPL fixture.

    Liverpool's nickname is 'the Reds' (from team_nicknames.json). Across the
    7-pattern pool, the nickname must surface in at least one rendering of a
    Liverpool home match.
    """
    spec = _make_spec(home="Liverpool", away="Chelsea")
    verb = _action_verb_w82(spec.verdict_action, spec.edge_tier)
    sizing = _sizing_w82(spec.verdict_action, spec.edge_tier)
    nickname = lookup_nickname("Liverpool")
    assert nickname, "team_nicknames.json missing Liverpool entry"
    rendered = [fn(spec, verb, sizing) for fn in _W82_VARIANT_PATTERNS]
    nick_hits = sum(1 for t in rendered if nickname.lower() in t.lower() or nickname[4:].lower() in t.lower())
    assert nick_hits >= 1, (
        f"No variant referenced nickname '{nickname}' across the pool. "
        f"Renders: {rendered}"
    )


# ── Test 8: manager surname when available ────────────────────────────────────

def test_variant_uses_manager_surname_when_available():
    """At least one variant references the home coach's surname when present."""
    spec = _make_spec(home="Liverpool", coach="Arne Slot")
    verb = _action_verb_w82(spec.verdict_action, spec.edge_tier)
    sizing = _sizing_w82(spec.verdict_action, spec.edge_tier)
    rendered = [fn(spec, verb, sizing) for fn in _W82_VARIANT_PATTERNS]
    surname_hits = sum(1 for t in rendered if "Slot" in t)
    assert surname_hits >= 1, (
        f"No variant referenced coach surname 'Slot' across the pool. "
        f"Renders: {rendered}"
    )


# ── Test 9: venue when available ──────────────────────────────────────────────

def test_variant_uses_venue_when_available():
    """At least one variant references the venue when spec.venue is populated."""
    spec = _make_spec(home="Liverpool", venue="Anfield")
    verb = _action_verb_w82(spec.verdict_action, spec.edge_tier)
    sizing = _sizing_w82(spec.verdict_action, spec.edge_tier)
    rendered = [fn(spec, verb, sizing) for fn in _W82_VARIANT_PATTERNS]
    venue_hits = sum(1 for t in rendered if "Anfield" in t)
    assert venue_hits >= 1, (
        f"No variant referenced venue 'Anfield' across the pool. "
        f"Renders: {rendered}"
    )


# ── Test 10: banned-phrase grep across whole pool ─────────────────────────────

def test_no_banned_telemetry_phrase_in_any_variant():
    """Sweep all 7 variants × 5 fixtures; assert zero telemetry hits."""
    fixtures = [
        ("Liverpool", "Chelsea", "gold", "back"),
        ("Manchester City", "Brentford", "diamond", "strong back"),
        ("Brighton", "Wolves", "silver", "lean"),
        ("Stade Toulousain", "Munster", "silver", "lean"),
        ("Mumbai Indians", "Chennai Super Kings", "gold", "back"),
    ]
    compiled = [(re.compile(p, re.IGNORECASE), label) for p, label in TELEMETRY_VOCABULARY_PATTERNS]
    hits: list[tuple[str, str]] = []
    for home, away, tier, action in fixtures:
        spec = _make_spec(home=home, away=away, tier=tier, action=action,
                          coach="" if home == "Stade Toulousain" else "Coach Name",
                          venue="" if home == "Stade Toulousain" else "Stadium")
        verb = _action_verb_w82(action, tier)
        sizing = _sizing_w82(action, tier)
        for fn in _W82_VARIANT_PATTERNS:
            text = fn(spec, verb, sizing)
            for pat, label in compiled:
                if pat.search(text):
                    hits.append((label, text))
    assert not hits, (
        f"Banned telemetry phrases detected across the W82 pool: {hits}"
    )


# ── Test 11: pool diversity post-render ───────────────────────────────────────

def test_variant_pool_diversity_post_render():
    """Render 30 synthetic fixtures via _render_baseline; require ≥5 distinct
    opening-shape hashes from the verdict section.

    Mirrors HG-4 of the brief.
    """
    fixtures = [
        ("Liverpool", "Chelsea", "Anfield", "Arne Slot", "WWWDW", "LWLDL", 2, 10, "gold", "back", "epl"),
        ("Manchester City", "Brentford", "Etihad Stadium", "Pep Guardiola", "WWWWW", "LLLDW", 1, 14, "diamond", "strong back", "epl"),
        ("Brighton", "Wolves", "Amex Stadium", "Fabian Hurzeler", "WWDLW", "LDLLD", 7, 16, "silver", "lean", "epl"),
        ("Arsenal", "Tottenham Hotspur", "Emirates", "Mikel Arteta", "WWWLW", "DLWWD", 3, 6, "gold", "back", "epl"),
        ("Aston Villa", "Newcastle United", "Villa Park", "Unai Emery", "DWWLD", "WLLDW", 8, 5, "silver", "lean", "epl"),
        ("Mamelodi Sundowns", "Orlando Pirates", "Loftus Versfeld", "Miguel Cardoso", "WWWWD", "DWLLW", 1, 4, "diamond", "strong back", "psl"),
        ("Kaizer Chiefs", "Stellenbosch", "FNB Stadium", "Khalil Ben Youssef", "DWLDD", "WWDLL", 6, 3, "silver", "lean", "psl"),
        ("Bayern Munich", "Borussia Dortmund", "Allianz Arena", "Vincent Kompany", "WWDWW", "LDWLW", 1, 4, "gold", "back", "bundesliga"),
        ("Real Madrid", "FC Barcelona", "Bernabéu", "Alvaro Arbeloa", "WDWWW", "WWLDW", 1, 2, "diamond", "strong back", "la_liga"),
        ("Atletico Madrid", "Sevilla", "Metropolitano", "Diego Simeone", "WWLWD", "DWLLD", 4, 9, "silver", "lean", "la_liga"),
        ("Juventus", "Inter Milan", "Allianz Stadium Turin", "Luciano Spalletti", "DWWLW", "WWWDD", 4, 1, "gold", "back", "serie_a"),
        ("AC Milan", "Napoli", "San Siro", "Massimiliano Allegri", "WLWWD", "WDWWW", 5, 2, "silver", "lean", "serie_a"),
        ("Paris Saint Germain", "Marseille", "Parc des Princes", "Luis Enrique", "WWWWW", "WLDWL", 1, 4, "diamond", "strong back", "ligue_1"),
        ("Ajax", "PSV Eindhoven", "Johan Cruyff Arena", "", "WDWLD", "WWDLW", 3, 1, "silver", "lean", "eredivisie"),
        ("Stade Toulousain", "Munster", "", "", "", "", None, None, "silver", "lean", "champions_cup"),
        ("Stormers", "Bulls", "DHL Stadium", "", "WLDWW", "WWDLD", 2, 5, "gold", "back", "urc"),
        ("Sharks", "Lions", "Kings Park", "", "DLWLD", "LDLLW", 8, 11, "silver", "lean", "urc"),
        ("South Africa Rugby", "New Zealand Rugby", "Ellis Park", "", "WWWWW", "WDWLW", 1, 2, "diamond", "strong back", "international_rugby"),
        ("Mumbai Indians", "Chennai Super Kings", "Wankhede Stadium", "", "WLWWL", "WWLDD", 4, 5, "gold", "back", "ipl"),
        ("Royal Challengers Bangalore", "Gujarat Titans", "Chinnaswamy Stadium", "", "WWLDW", "LWWLD", 3, 6, "silver", "lean", "ipl"),
        ("Sunrisers Hyderabad", "Delhi Capitals", "Rajiv Gandhi Stadium", "", "LWDLW", "DWLLD", 7, 9, "silver", "lean", "ipl"),
        ("Chelsea", "Arsenal", "Stamford Bridge", "Liam Rosenior", "DLWLD", "WWWLW", 11, 3, "silver", "lean", "epl"),
        ("Manchester United", "Liverpool", "Old Trafford", "Michael Carrick", "LDWWL", "WWWDW", 12, 2, "gold", "back", "epl"),
        ("Everton", "West Ham", "Hill Dickinson Stadium", "David Moyes", "WLLDW", "DLLWD", 14, 13, "silver", "lean", "epl"),
        ("Nottingham Forest", "Newcastle United", "City Ground", "Vitor Pereira", "WDLDW", "WLLDW", 9, 5, "silver", "lean", "epl"),
        ("Inter Milan", "Roma", "San Siro", "Cristian Chivu", "WWWDD", "DLWWL", 1, 7, "gold", "back", "serie_a"),
        ("RB Leipzig", "Bayer Leverkusen", "Red Bull Arena", "Ole Werner", "WLDWW", "WDDWL", 5, 3, "silver", "lean", "bundesliga"),
        ("Olympique Lyonnais", "Olympique Marseille", "Groupama Stadium", "", "DWLDW", "WWDLW", 8, 4, "silver", "lean", "ligue_1"),
        ("Sporting CP", "FC Porto", "Estádio José Alvalade", "", "WWWWW", "WWDWW", 1, 2, "gold", "back", "primeira"),
        ("Boca Juniors", "River Plate", "La Bombonera", "", "WWLDW", "DWWLW", 3, 1, "silver", "lean", "argentine"),
    ]
    assert len(fixtures) == 30, "AC-5 / HG-4 requires 30 synthetic fixtures"

    verdict_openings: list[str] = []
    verdicts: list[str] = []
    for fx in fixtures:
        spec = _make_spec(
            home=fx[0], away=fx[1], venue=fx[2], coach=fx[3],
            home_form=fx[4], away_form=fx[5],
            home_pos=fx[6], away_pos=fx[7],
            tier=fx[8], action=fx[9],
        )
        baseline = _render_baseline(spec)
        # Extract verdict section (after 🏆 Verdict\n)
        verdict_marker = "🏆 <b>Verdict</b>\n"
        idx = baseline.find(verdict_marker)
        assert idx >= 0, f"No verdict marker in baseline render for {fx[0]} vs {fx[1]}"
        verdict_text = baseline[idx + len(verdict_marker):].strip()
        verdicts.append(verdict_text)
        verdict_openings.append(_opening_hash(verdict_text))

    distinct = set(verdict_openings)
    assert len(distinct) >= 5, (
        f"Only {len(distinct)} distinct opening hashes across 30 verdicts. "
        f"AC-5 / HG-4 require ≥5 distinct opening-shape hashes. "
        f"Verdict samples: {verdicts[:3]}"
    )


# ── Test 12: idempotence on repeated render ───────────────────────────────────

def test_render_baseline_idempotent_on_same_match():
    """Same NarrativeSpec rendered 10 times produces identical output."""
    spec = _make_spec(home="Liverpool", away="Chelsea")
    first = _render_baseline(spec)
    for _ in range(10):
        again = _render_baseline(spec)
        assert again == first, (
            "Same NarrativeSpec produced different baseline output across "
            "consecutive _render_baseline calls — cache coherence broken."
        )
