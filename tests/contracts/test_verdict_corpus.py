"""Contract test for the deterministic verdict corpus.

BUILD-W82-RIP-AND-REPLACE-01 — Phase 3a (2026-05-02). 8 categories asserting
the corpus + render contract:

    1. Every tier renders all 10 sentences cleanly with synthetic slots
       (40 verdict cases).
    2. Every sentence ends on the canonical imperative regex.
    3. Zero concessive connector tokens across all 50 sentences.
    4. Hash-picker is deterministic — same (match_key, tier) → same sentence
       across renders.
    5. Concern-prefix concatenation: prefix + space + verdict body, no
       double punctuation, body still contains team + odds + bookmaker.
    6. Char range 100-200 holds for every (sentence, slot-fill) combination.
    7. Slot-fill never produces empty {team} / {odds} / {bookmaker}
       (defensive).
    8. Regression fixture: Liverpool-Chelsea Diamond + Arsenal-Fulham Gold
       inputs produce verdicts with no concessive connector and no
       truncation.

All tests are pure Python (no DB, no LLM) — they run in milliseconds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest

import verdict_corpus as vc


# ── Shared fixtures ───────────────────────────────────────────────────────


@dataclass
class _MockSpec:
    """Minimal NarrativeSpec stand-in — only the fields render_verdict reads."""

    edge_tier: str = "bronze"
    outcome_label: str = ""
    odds: float = 0.0
    bookmaker: str = ""
    home_name: str = ""
    away_name: str = ""
    composite_score: float = 0.0
    support_level: int = 0
    contradicting_signals: int = 0
    movement_direction: str = "neutral"
    outcome: str = "home"
    injuries_home: list = field(default_factory=list)
    injuries_away: list = field(default_factory=list)
    match_key: str = ""


# Realistic slot-fill spread:
#  - shortest team name in production: 3-letter abbreviation ("PSG")
#  - longest team name: "Mamelodi Sundowns" (17 chars)
#  - shortest bookmaker: "WSB" (3 chars)
#  - longest bookmaker: "SuperSportBet" (13 chars)
#  - odds: 1.55 (4 chars) → 11.50 (5 chars)
_SLOT_SPREAD = [
    ("PSG", 1.55, "WSB"),
    ("Liverpool", 1.96, "SuperSportBet"),
    ("Mamelodi Sundowns", 11.50, "SuperSportBet"),
    ("Arsenal", 2.10, "Hollywoodbets"),
    ("Sundowns", 1.48, "Betway"),
    ("Real Madrid", 3.25, "Sportingbet"),
]

_TIERS = ("diamond", "gold", "silver", "bronze")


# Same canonical imperative regex the validator uses (mirrors
# narrative_validator._CORPUS_IMPERATIVE_CLOSE_RE).
_IMPERATIVE_CLOSE_RE = re.compile(
    r"(?:^|\s)("
    r"back|hammer|get\s+on|take|bet|lock\s+in|load\s+up|go\s+in|"
    r"the\s+play\s+is|the\s+call\s+is|worth\s+a"
    r")\b.*[\.!]?\s*$",
    re.IGNORECASE,
)


def _last_sentence(text: str) -> str:
    parts = re.split(r"[.!?]\s+", text.strip())
    nonempty = [p.strip() for p in parts if p and p.strip()]
    return nonempty[-1].rstrip(" \t.!?;,…—–-") if nonempty else ""


# ── 1. Every tier renders all 10 sentences cleanly ────────────────────────


@pytest.mark.parametrize("tier", _TIERS)
def test_corpus_has_ten_sentences_per_tier(tier: str) -> None:
    assert len(vc.VERDICT_CORPUS[tier]) == 10, (
        f"{tier} pool has {len(vc.VERDICT_CORPUS[tier])} sentences, expected 10"
    )


@pytest.mark.parametrize("tier", _TIERS)
def test_corpus_renders_all_ten_sentences_per_tier(tier: str) -> None:
    """Render every corpus sentence with a synthetic spec; assert no exceptions
    and every render contains team + odds + bookmaker."""
    pool = vc.VERDICT_CORPUS[tier]
    for idx, template in enumerate(pool):
        # Slot-fill manually (bypass hash-picker) so this tests every sentence
        rendered = template.format(team="Liverpool", odds="1.96", bookmaker="SuperSportBet")
        assert "Liverpool" in rendered, f"{tier}[{idx}] missing team token"
        assert "1.96" in rendered, f"{tier}[{idx}] missing odds token"
        assert "SuperSportBet" in rendered, f"{tier}[{idx}] missing bookmaker token"
        # Sanity: rendered ends with terminator
        assert rendered.rstrip()[-1] in ".!?", f"{tier}[{idx}] missing sentence terminator"


# ── 2. Imperative-close pattern across all 40 sentences ───────────────────


@pytest.mark.parametrize("tier", _TIERS)
def test_corpus_imperative_close(tier: str) -> None:
    """Every corpus sentence's last sentence must match the imperative regex."""
    pool = vc.VERDICT_CORPUS[tier]
    for idx, template in enumerate(pool):
        rendered = template.format(team="Arsenal", odds="2.10", bookmaker="Betway")
        last = _last_sentence(rendered)
        assert _IMPERATIVE_CLOSE_RE.search(last), (
            f"{tier}[{idx}] last sentence {last!r} fails imperative close"
        )


# ── 3. Zero concessive connector tokens across all 50 sentences ───────────


_CONCESSIVE_RE = re.compile(
    r"\b(Despite that|Even so|Still,|That said|Even with that)\b",
)


def test_corpus_has_zero_concessive_connectors() -> None:
    """The brief locks zero concessive connectors anywhere in the corpus."""
    for tier, pool in vc.VERDICT_CORPUS.items():
        for idx, template in enumerate(pool):
            rendered = template.format(team="Liverpool", odds="1.96", bookmaker="SuperSportBet")
            assert not _CONCESSIVE_RE.search(rendered), (
                f"{tier}[{idx}] contains a concessive connector: {rendered!r}"
            )
    for idx, prefix in enumerate(vc.CONCERN_PREFIXES):
        assert not _CONCESSIVE_RE.search(prefix), (
            f"concern_prefix[{idx}] contains a concessive connector: {prefix!r}"
        )


# ── 4. Hash-picker is deterministic ───────────────────────────────────────


@pytest.mark.parametrize("tier", _TIERS)
def test_pick_is_deterministic_per_tier(tier: str) -> None:
    pool = vc.VERDICT_CORPUS[tier]
    for match_key in (
        "liverpool_vs_chelsea_2026-05-04",
        "arsenal_vs_fulham_2026-05-02",
        "mamelodi_sundowns_vs_pirates_2026-05-04",
    ):
        first = vc._pick(pool, match_key, tier)
        second = vc._pick(pool, match_key, tier)
        third = vc._pick(pool, match_key, tier)
        assert first == second == third, (
            f"{tier} {match_key} returned different sentences across calls"
        )


def test_pick_distributes_across_pool() -> None:
    """Across 100 synthetic match_keys, every Diamond sentence is picked at
    least once. This is a uniform-distribution sanity check on the MD5 mod."""
    pool = vc.VERDICT_CORPUS["diamond"]
    seen: set[str] = set()
    for i in range(100):
        match_key = f"home{i}_vs_away{i}_2026-05-04"
        seen.add(vc._pick(pool, match_key, "diamond"))
    # 100 keys hashed into a 10-element pool — collision is OK but every slot
    # should be visited at least 5 times in expectation.
    assert len(seen) == 10, f"only {len(seen)}/10 sentences visited across 100 keys"


# ── 5. Concern-prefix concatenation ───────────────────────────────────────


def test_concern_prefix_concatenation_clean() -> None:
    """has_real_risk=True path: prefix + ' ' + body, no double-punctuation,
    body still contains team + odds + bookmaker."""
    spec = _MockSpec(
        edge_tier="bronze",
        outcome_label="Liverpool",
        odds=1.96,
        bookmaker="SuperSportBet",
        home_name="Liverpool",
        away_name="Chelsea",
        composite_score=42,
        support_level=0,        # triggers has_real_risk=True
        contradicting_signals=0,
        match_key="liverpool_vs_chelsea_2026-05-04",
    )
    rendered = vc.render_verdict(spec)
    # Concern-prefix sits at front
    assert any(rendered.startswith(p) for p in vc.CONCERN_PREFIXES), (
        f"render does not start with a known concern prefix: {rendered!r}"
    )
    # Body still has all three slot tokens
    assert "Liverpool" in rendered
    assert "1.96" in rendered
    assert "SuperSportBet" in rendered
    # Single space separator after the prefix terminator (no double punctuation)
    assert ".." not in rendered, f"double punctuation in: {rendered!r}"
    assert "  " not in rendered, f"double space in: {rendered!r}"
    # Body's first character (after prefix + space) is uppercase
    for prefix in vc.CONCERN_PREFIXES:
        if rendered.startswith(prefix):
            body = rendered[len(prefix) + 1:]
            assert body and body[0].isupper(), (
                f"verdict body should start uppercase: {body!r}"
            )
            break


def test_concern_prefix_only_fires_when_has_real_risk() -> None:
    """Clean spec (high composite, multiple signals, no contradiction) MUST NOT
    receive a concern-prefix concat."""
    spec = _MockSpec(
        edge_tier="diamond",
        outcome_label="Liverpool",
        odds=1.96,
        bookmaker="SuperSportBet",
        home_name="Liverpool",
        away_name="Chelsea",
        composite_score=92,
        support_level=4,
        contradicting_signals=0,
        match_key="liverpool_vs_chelsea_2026-05-04",
    )
    rendered = vc.render_verdict(spec)
    # No concern prefix should be at the start
    for prefix in vc.CONCERN_PREFIXES:
        assert not rendered.startswith(prefix), (
            f"clean diamond render unexpectedly carries prefix: {rendered!r}"
        )


# ── 6. Char range 100-200 across realistic slot-fill spread ───────────────


@pytest.mark.parametrize("tier", _TIERS)
def test_corpus_char_range_100_to_200(tier: str) -> None:
    """Every (sentence, slot-fill) combination must be 100 ≤ len ≤ 200."""
    pool = vc.VERDICT_CORPUS[tier]
    for idx, template in enumerate(pool):
        for team, odds, bk in _SLOT_SPREAD:
            rendered = template.format(team=team, odds=f"{odds:.2f}", bookmaker=bk)
            assert 100 <= len(rendered) <= 200, (
                f"{tier}[{idx}] with ({team},{odds},{bk}) → {len(rendered)} chars: {rendered!r}"
            )


# ── 7. Slot-fill never produces empty {team} / {odds} / {bookmaker} ───────


def test_render_verdict_handles_empty_slot_fields_defensively() -> None:
    """When the spec is missing slot fields, render_verdict falls back to a
    safe placeholder rather than emitting a blank slot."""
    spec = _MockSpec(
        edge_tier="bronze",
        outcome_label="",   # empty
        odds=0,             # zero → renders as "—"
        bookmaker="",       # empty → renders as "—"
        home_name="X",
        away_name="Y",
        match_key="x_vs_y",
    )
    rendered = vc.render_verdict(spec)
    # No literal {curly} braces should remain after fill
    assert "{team}" not in rendered
    assert "{odds}" not in rendered
    assert "{bookmaker}" not in rendered
    # Placeholders kick in
    assert "the pick" in rendered or "X" in rendered
    assert "—" in rendered  # defensive odds + bookmaker placeholders


# ── 8. Regression fixture — Liverpool-Chelsea Diamond + Arsenal-Fulham Gold ─


def test_regression_liverpool_chelsea_diamond() -> None:
    """The brief's first failure case: Liverpool-Chelsea Diamond. Verify the
    deterministic render carries no concessive connector and no truncation."""
    spec = _MockSpec(
        edge_tier="diamond",
        outcome_label="Liverpool",
        odds=1.96,
        bookmaker="Supabets",
        home_name="Liverpool",
        away_name="Chelsea",
        composite_score=92,
        support_level=4,
        contradicting_signals=0,
        match_key="liverpool_vs_chelsea_2026-05-04",
    )
    v = vc.render_verdict(spec)
    assert v, "expected non-empty verdict"
    assert not _CONCESSIVE_RE.search(v), f"concessive connector present: {v!r}"
    # Mid-word truncation guard — verdict ends on a terminator
    assert v.rstrip()[-1] in ".!?", f"verdict not terminated: {v!r}"
    # Char range
    assert 100 <= len(v) <= 260, f"verdict length out of range: {len(v)} {v!r}"


def test_regression_arsenal_fulham_gold() -> None:
    """The brief's second failure case: Arsenal-Fulham Gold (mid-word truncation
    'pointing t....' + 'Despite that' contradiction). Verify the deterministic
    render fixes both issues."""
    spec = _MockSpec(
        edge_tier="gold",
        outcome_label="Arsenal",
        odds=1.51,
        bookmaker="SuperSportBet",
        home_name="Arsenal",
        away_name="Fulham",
        composite_score=78,
        support_level=3,
        contradicting_signals=0,
        match_key="arsenal_vs_fulham_2026-05-02",
    )
    v = vc.render_verdict(spec)
    assert v, "expected non-empty verdict"
    assert not _CONCESSIVE_RE.search(v), f"concessive connector present: {v!r}"
    assert "pointing t" not in v, f"mid-word truncation pattern present: {v!r}"
    assert v.rstrip()[-1] in ".!?", f"verdict not terminated: {v!r}"
    assert 100 <= len(v) <= 260, f"verdict length out of range: {len(v)} {v!r}"
    # Tier-appropriate imperative
    last = _last_sentence(v)
    assert _IMPERATIVE_CLOSE_RE.search(last), (
        f"Gold verdict last sentence {last!r} fails imperative close"
    )


# ── Concern-prefix structural assertions ──────────────────────────────────


def test_concern_prefixes_exact_count() -> None:
    assert len(vc.CONCERN_PREFIXES) == 10


def test_concern_prefixes_end_in_period() -> None:
    """Concern prefixes terminate with a period (not a connector)."""
    for idx, prefix in enumerate(vc.CONCERN_PREFIXES):
        assert prefix.rstrip()[-1] == ".", f"prefix[{idx}] missing period: {prefix!r}"


def test_concern_prefixes_have_no_slot_placeholders() -> None:
    """Concern prefixes are sport-agnostic — no slot placeholders allowed."""
    for idx, prefix in enumerate(vc.CONCERN_PREFIXES):
        for slot in ("{team}", "{odds}", "{bookmaker}"):
            assert slot not in prefix, (
                f"prefix[{idx}] contains slot placeholder {slot}: {prefix!r}"
            )


# ── has_real_risk heuristic — corner cases ────────────────────────────────


def test_has_real_risk_zero_confirming_signals() -> None:
    spec = _MockSpec(edge_tier="diamond", composite_score=92, support_level=0,
                     contradicting_signals=0, match_key="x")
    assert vc.has_real_risk(spec) is True


def test_has_real_risk_two_or_more_contradicting() -> None:
    spec = _MockSpec(edge_tier="gold", composite_score=82, support_level=3,
                     contradicting_signals=2, match_key="x")
    assert vc.has_real_risk(spec) is True


def test_has_real_risk_movement_against_pick() -> None:
    spec = _MockSpec(edge_tier="silver", composite_score=66, support_level=2,
                     contradicting_signals=0, movement_direction="against",
                     match_key="x")
    assert vc.has_real_risk(spec) is True


def test_has_real_risk_marginal_composite() -> None:
    """composite_score within 5 of tier floor → marginal edge → True."""
    # gold floor = 70; composite 73 (< 75) → marginal
    spec = _MockSpec(edge_tier="gold", composite_score=73, support_level=2,
                     contradicting_signals=0, match_key="x")
    assert vc.has_real_risk(spec) is True


def test_has_real_risk_lineup_injury_on_pick_side() -> None:
    spec = _MockSpec(edge_tier="bronze", composite_score=50, support_level=1,
                     contradicting_signals=0, outcome="home",
                     injuries_home=["Salah", "Van Dijk"],
                     match_key="x")
    assert vc.has_real_risk(spec) is True


def test_has_real_risk_lineup_injury_on_other_side_does_not_fire() -> None:
    """Injury on the OPPOSING side actually helps the pick — no risk."""
    spec = _MockSpec(edge_tier="diamond", composite_score=95, support_level=4,
                     contradicting_signals=0, outcome="home",
                     injuries_home=[],
                     injuries_away=["Salah", "Van Dijk"],
                     match_key="x")
    assert vc.has_real_risk(spec) is False


def test_has_real_risk_clean_premium_signal() -> None:
    """High composite + 4 confirming signals + no contradiction → clean."""
    spec = _MockSpec(edge_tier="diamond", composite_score=92, support_level=4,
                     contradicting_signals=0, movement_direction="for",
                     match_key="x")
    assert vc.has_real_risk(spec) is False
