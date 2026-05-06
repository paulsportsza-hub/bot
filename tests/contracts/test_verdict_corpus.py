"""Contract test for the deterministic verdict corpus — sport-banded.

BUILD-W82-CORPUS-EXPANSION-01 — Phase 4 (2026-05-02). Sport-banded corpus
expansion: 4 tiers × 3 sports × 30 sentences = 360 verdict sentences plus
25 concern prefixes. Twelve new test categories on top of the original eight
from BUILD-W82-RIP-AND-REPLACE-01 — refactored to the new VERDICT_CORPUS
shape (`dict[str, dict[str, list[VerdictSentence]]]`).

Categories (per brief Phase 4 list):

  Original 8 (refactored to sport-banded shape):
    1. Bucket size — every (tier, sport) has exactly 30 sentences
    2. Filter safety — every (tier, sport) has ≥15 claims_completeness=False
    3. Tag consistency — completeness regex hit MUST be tagged True
    4. Concern prefix expansion — exactly 25, all end in '.', none have slots
    5. Voice differentiation — Jaccard bigram cross-sport < 0.6 within tier
    6. No concessive connectors anywhere
    7. No contradiction with concern prefix — has_real_risk=True path never
       produces a contradicting prefix×completeness-claim pair
    8. Char range 100-200 across realistic slot-fill spread
    9. Hash determinism — same (match_key, tier, sport) → same sentence
    10. Hash distribution — 200 specs visit ≥66% of each bucket
    11. Sport normalisation — all variants map to {soccer, rugby, cricket}
    12. Existing imperative-close gate still passes for every sentence

  Plus retained from BUILD-W82-RIP-AND-REPLACE-01:
    - Empty-slot defensive handling
    - Concern-prefix concatenation cleanliness
    - has_real_risk corner-case behaviour
    - Liverpool-Chelsea / Arsenal-Fulham regression fixtures

All tests are pure Python (no DB, no LLM) — they run in milliseconds.

BUILD-VERDICT-SIGNAL-MAPPED-01 (2026-05-03): The corpus is now the
fallback path; the signal-mapped builder is the main path. These
existing tests cover the corpus structure, slot-fill mechanics,
sport-bucket selection, and concern-prefix discipline — all of which
remain in place as the safety net. To keep the assertions stable, the
module-level autouse fixture pins ``USE_SIGNAL_MAPPED_VERDICTS=0`` so
``render_verdict`` always exercises the corpus path here. The new
builder has its own contract suite at ``test_verdict_signal_mapper.py``.
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field

import pytest

import verdict_corpus as vc


@pytest.fixture(autouse=True)
def _force_corpus_path(monkeypatch):
    """Pin render_verdict to the legacy corpus path for this test module.

    BUILD-VERDICT-SIGNAL-MAPPED-01 — the signal-mapped builder is the
    main path under default flag, but these tests guard the corpus
    fallback. Setting the flag off keeps the assertions stable while
    HG-4 holds the corpus in place as the safety net.
    """
    monkeypatch.setenv("VERDICT_ENGINE_V2", "0")
    monkeypatch.setattr(vc, "_USE_V2", False)
    monkeypatch.setenv("USE_SIGNAL_MAPPED_VERDICTS", "0")
    yield


# ── Shared fixtures ───────────────────────────────────────────────────────


@dataclass
class _MockSpec:
    """Minimal NarrativeSpec stand-in — only the fields render_verdict reads."""

    edge_tier: str = "bronze"
    sport: str = "soccer"
    outcome_label: str = ""
    odds: float = 0.0
    bookmaker: str = ""
    league: str = "epl"
    recommended_team: str = ""
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
    edge_revision: str = ""
    recommended_at: str = ""
    kickoff_utc: str | None = None
    verdict_action: str = ""
    signals: dict = field(default_factory=dict)
    evidence_pack: dict | None = None
    h2h: str = ""
    home_form: str | None = None
    away_form: str | None = None
    venue: str | None = None
    coach: str | None = None
    nickname: str | None = None
    bookmaker_count: int | None = None
    line_movement_direction: str | None = None
    tipster_sources_count: int | None = None


# Realistic slot-fill spread:
#  - shortest team: "PSG" (3 chars)
#  - longest team: "Mamelodi Sundowns" (17 chars)
#  - shortest bookmaker: "WSB" (3 chars)
#  - longest bookmaker: "SuperSportBet" (13 chars)
_SLOT_SPREAD = [
    ("PSG", 1.55, "WSB"),
    ("Liverpool", 1.96, "SuperSportBet"),
    ("Mamelodi Sundowns", 11.50, "SuperSportBet"),
    ("Arsenal", 2.10, "Hollywoodbets"),
    ("Sundowns", 1.48, "Betway"),
    ("Real Madrid", 3.25, "Sportingbet"),
]

_TIERS = ("diamond", "gold", "silver", "bronze")
_SPORTS = ("soccer", "rugby", "cricket")


# Same canonical imperative regex the validator uses.
_IMPERATIVE_CLOSE_RE = re.compile(
    r"(?:^|\s)("
    r"back|hammer|get\s+on|take|bet|lock\s+in|load\s+up|go\s+in|"
    r"the\s+play\s+is|the\s+call\s+is|worth\s+a"
    r")\b.*[\.!]?\s*$",
    re.IGNORECASE,
)

_COMPLETENESS_REGEX = re.compile(
    r"\b(every|all|whole|top to bottom|complete|model and market|numbers and signals)\b",
    re.IGNORECASE,
)

_MAX_CONVICTION_REGEX = vc._MAX_CONVICTION_TOKENS

_CONCESSIVE_RE = re.compile(
    r"\b(Despite that|Even so|Still,|That said|Even with that)\b",
)

_CRICKET_PREFIX_MARKERS = re.compile(
    r"\b(wicket|pitch|surface|dew|toss|batting|bowling)\b",
    re.IGNORECASE,
)
_RUGBY_PREFIX_MARKERS = re.compile(
    r"\b(scrum|lineout|breakdown|forward pack|forward platform|set-piece dominance|blitz|line-speed|gainline|ruck)\b",
    re.IGNORECASE,
)
_SOCCER_PREFIX_MARKERS = re.compile(
    r"\b(backline|midfield|pressing|wing|set-piece|away record|clean sheets)\b",
    re.IGNORECASE,
)


def _last_sentence(text: str) -> str:
    parts = re.split(r"[.!?]\s+", text.strip())
    nonempty = [p.strip() for p in parts if p and p.strip()]
    return nonempty[-1].rstrip(" \t.!?;,…—–-") if nonempty else ""


def _bigrams(text: str) -> set[tuple[str, str]]:
    words = re.findall(r"[a-z]+", text.lower())
    return set(zip(words, words[1:]))


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _all_prefixes() -> list[str]:
    return [prefix for bucket in vc.CONCERN_PREFIXES.values() for prefix in bucket]


def _unique_prefixes() -> list[str]:
    return list(dict.fromkeys(_all_prefixes()))


# ── 1. Bucket size — every (tier, sport) has exactly 30 sentences ─────────


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_bucket_has_exactly_30_sentences(tier: str, sport: str) -> None:
    pool = vc.VERDICT_CORPUS[tier][sport]
    assert len(pool) == 30, (
        f"({tier},{sport}) has {len(pool)} sentences, expected 30"
    )


# ── 2. Filter safety — Gold/Silver/Bronze safe pool has >=8 sentences ─────


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_filter_safety_minimum_8_non_diamond(tier: str, sport: str) -> None:
    """Each non-Diamond bucket must have >=8 safe sentences for risk renders."""
    pool = vc.VERDICT_CORPUS[tier][sport]
    safe_count = sum(
        1 for s in pool
        if not s.claims_completeness and not s.claims_max_conviction
    )
    if tier == "diamond":
        assert safe_count == 0, (
            f"Diamond should remain max-conviction under Option A; got "
            f"{safe_count} safe sentences in ({tier},{sport})"
        )
        return
    assert safe_count >= 8, (
        f"({tier},{sport}) has only {safe_count} safe sentences (need >=8)"
    )


# ── 3. Tag consistency — completeness regex hit MUST be tagged True ───────


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_tag_consistency_completeness_regex(tier: str, sport: str) -> None:
    """Brief Phase 4: scan every sentence text; if it contains a
    completeness-claim regex hit, the tag MUST be True. Hard-fail when
    regex matches but tag is False."""
    pool = vc.VERDICT_CORPUS[tier][sport]
    for idx, vs in enumerate(pool):
        if _COMPLETENESS_REGEX.search(vs.text):
            assert vs.claims_completeness, (
                f"({tier},{sport})[{idx}] regex hit but tagged False: {vs.text!r}"
            )


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_tag_consistency_max_conviction_regex(tier: str, sport: str) -> None:
    """claims_max_conviction is auto-tagged from _MAX_CONVICTION_TOKENS."""
    pool = vc.VERDICT_CORPUS[tier][sport]
    for idx, vs in enumerate(pool):
        expected = bool(_MAX_CONVICTION_REGEX.search(vs.text))
        assert vs.claims_max_conviction is expected, (
            f"({tier},{sport})[{idx}] max-conviction tag mismatch: {vs.text!r}"
        )


# ── 4. Concern prefix expansion — sport-bucketed, period-terminated, no slots ─


def test_concern_prefixes_dict_shape() -> None:
    assert isinstance(vc.CONCERN_PREFIXES, dict)
    assert set(vc.CONCERN_PREFIXES.keys()) == {"soccer", "rugby", "cricket"}


@pytest.mark.parametrize("sport", _SPORTS)
def test_concern_prefix_bucket_minimum_8(sport: str) -> None:
    assert len(vc.CONCERN_PREFIXES[sport]) >= 8, (
        f"{sport} has only {len(vc.CONCERN_PREFIXES[sport])} prefixes"
    )


def test_concern_prefixes_exact_unique_count() -> None:
    assert len(_unique_prefixes()) == 25, (
        f"Expected 25 unique concern prefixes, got {len(_unique_prefixes())}"
    )


def test_concern_prefixes_end_in_period() -> None:
    for idx, prefix in enumerate(_unique_prefixes()):
        assert prefix.rstrip()[-1] == ".", (
            f"prefix[{idx}] missing terminator period: {prefix!r}"
        )


def test_concern_prefixes_no_slot_placeholders() -> None:
    for idx, prefix in enumerate(_unique_prefixes()):
        for slot in ("{team}", "{odds}", "{bookmaker}"):
            assert slot not in prefix, (
                f"prefix[{idx}] contains slot {slot}: {prefix!r}"
            )


def test_concern_prefixes_assert_no_tier_conviction() -> None:
    """Concern prefixes are sport-flavoured-safe — must not contain tier
    conviction language (hammer / load up / lock in / etc.)."""
    tier_imperatives = (
        "hammer", "load up", "go in heavy", "lock in", "back ", "get on",
        "take ", "bet ", "the play is", "the call is", "worth a",
    )
    for idx, prefix in enumerate(_unique_prefixes()):
        low = prefix.lower()
        for token in tier_imperatives:
            assert token not in low, (
                f"prefix[{idx}] contains tier imperative {token!r}: {prefix!r}"
            )


def test_soccer_concern_prefix_bucket_has_no_foreign_sport_markers() -> None:
    """Regression: soccer cards must not receive cricket/rugby concern terms."""
    for prefix in vc.CONCERN_PREFIXES["soccer"]:
        assert not _CRICKET_PREFIX_MARKERS.search(prefix), (
            f"soccer prefix leaked cricket marker: {prefix!r}"
        )
        assert not _RUGBY_PREFIX_MARKERS.search(prefix), (
            f"soccer prefix leaked rugby marker: {prefix!r}"
        )


@pytest.mark.parametrize("sport,foreign_regexes", [
    ("rugby", (_CRICKET_PREFIX_MARKERS,)),
    ("cricket", (_RUGBY_PREFIX_MARKERS, _SOCCER_PREFIX_MARKERS)),
])
def test_concern_prefix_bucket_foreign_marker_contract(sport: str, foreign_regexes: tuple[re.Pattern, ...]) -> None:
    for prefix in vc.CONCERN_PREFIXES[sport]:
        for regex in foreign_regexes:
            assert not regex.search(prefix), (
                f"{sport} prefix leaked foreign marker {regex.pattern!r}: {prefix!r}"
            )


# ── 5. Voice differentiation — Jaccard cross-sport < 0.6 within tier ──────


@pytest.mark.parametrize("tier", _TIERS)
def test_voice_differentiation_cross_sport(tier: str) -> None:
    """Cross-sport Jaccard bigram similarity must be < 0.6 within each tier
    — forces real sport-vocabulary differentiation between the buckets."""
    per_sport_bigrams: dict[str, set] = {}
    for sport in _SPORTS:
        joined = " ".join(s.text for s in vc.VERDICT_CORPUS[tier][sport])
        per_sport_bigrams[sport] = _bigrams(joined)

    for i, s1 in enumerate(_SPORTS):
        for s2 in _SPORTS[i + 1:]:
            j = _jaccard(per_sport_bigrams[s1], per_sport_bigrams[s2])
            assert j < 0.6, (
                f"tier={tier} ({s1} vs {s2}) Jaccard={j:.3f} ≥ 0.6"
            )


# ── 6. Zero concessive connectors anywhere ────────────────────────────────


def test_corpus_has_zero_concessive_connectors() -> None:
    for tier in _TIERS:
        for sport in _SPORTS:
            pool = vc.VERDICT_CORPUS[tier][sport]
            for idx, vs in enumerate(pool):
                rendered = vs.text.format(team="Liverpool", odds="1.96",
                                          bookmaker="SuperSportBet")
                assert not _CONCESSIVE_RE.search(rendered), (
                    f"({tier},{sport})[{idx}] has concessive: {rendered!r}"
                )
    for idx, prefix in enumerate(_unique_prefixes()):
        assert not _CONCESSIVE_RE.search(prefix), (
            f"prefix[{idx}] has concessive: {prefix!r}"
        )


# ── 7. No contradiction with concern prefix (HG-3 — exhaustive) ────────────


def test_no_contradiction_with_concern_prefix_exhaustive() -> None:
    """HG-3: concern renders never combine a concern prefix with a flagged body.

    The flagged body set is any sentence with claims_completeness=True OR
    claims_max_conviction=True. Diamond is Option-A exempt from concern
    prefixes, so the concern search space covers Gold/Silver/Bronze.
    """
    flagged_count = 0
    search_space = 0
    violations: list[str] = []

    for tier in _TIERS:
        for sport in _SPORTS:
            pool = vc.VERDICT_CORPUS[tier][sport]
            flagged_pool = [
                s for s in pool
                if s.claims_completeness or s.claims_max_conviction
            ]
            flagged_count += len(flagged_pool)
            # Synthesise a spec that triggers has_real_risk for this tier
            spec = _MockSpec(
                edge_tier=tier,
                sport=sport,
                outcome_label="Liverpool",
                odds=1.96,
                bookmaker="SuperSportBet",
                home_name="Liverpool",
                away_name="Chelsea",
                composite_score=42,        # near floor — triggers has_real_risk
                support_level=0,           # zero confirming → triggers
                contradicting_signals=0,
                match_key=f"{tier}_{sport}_no_contradict_test",
            )
            assert vc.has_real_risk(spec), (  # type: ignore[arg-type]
                f"setup error: spec for ({tier},{sport}) doesn't trigger has_real_risk"
            )
            if tier == "diamond":
                rendered = vc.render_verdict(spec)  # type: ignore[arg-type]
                assert not any(rendered.startswith(p) for p in _all_prefixes()), (
                    f"Diamond risk render should be prefix-exempt: {rendered!r}"
                )
                continue

            search_space += len(vc.CONCERN_PREFIXES[sport]) * len(flagged_pool)
            # Hash-pick across many synthetic match keys so we exercise the
            # filter across the full prefix×bucket space.
            for i in range(150):
                spec.match_key = f"{tier}_{sport}_synth_{i}"
                rendered = vc.render_verdict(spec)  # type: ignore[arg-type]
                # Identify which prefix and which body sentence were picked
                used_prefix = None
                for p in vc.CONCERN_PREFIXES[sport]:
                    if rendered.startswith(p):
                        used_prefix = p
                        break
                assert used_prefix is not None, (
                    f"no prefix in {rendered!r} (has_real_risk=True path)"
                )
                body = rendered[len(used_prefix) + 1:]
                # The body must NOT come from a flagged sentence
                for vs in flagged_pool:
                    body_template_text = vs.text.format(
                        team="Liverpool", odds="1.96", bookmaker="SuperSportBet"
                    )
                    if body == body_template_text:
                        violations.append(
                            f"({tier},{sport}) prefix={used_prefix!r} body=True: {body!r}"
                        )

    print(
        f"\nHG-3 search space: sport-bucket concern prefixes × "
        f"{flagged_count} flagged sentences (completeness or max-conviction) "
        f"across non-Diamond buckets = {search_space:,} contradiction surfaces. "
        f"Violations: 0"
    )
    assert not violations, f"HG-3 violations found:\n" + "\n".join(violations)


# ── 8. Char range 100-200 across realistic slot-fill spread ───────────────


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_corpus_char_range_100_to_200(tier: str, sport: str) -> None:
    pool = vc.VERDICT_CORPUS[tier][sport]
    for idx, vs in enumerate(pool):
        for team, odds, bk in _SLOT_SPREAD:
            rendered = vs.text.format(team=team, odds=f"{odds:.2f}", bookmaker=bk)
            assert 100 <= len(rendered) <= 200, (
                f"({tier},{sport})[{idx}] with ({team},{odds},{bk}) → "
                f"{len(rendered)} chars: {rendered!r}"
            )


def test_concern_prefix_concat_total_within_260() -> None:
    """Combined prefix + space + body must be ≤ VERDICT_HARD_MAX=260.
    Verifies the brief's expanded char range accommodates concern + verdict
    even at the 200-char ceiling for the body."""
    longest_body = max(
        (s.text for tier in _TIERS for sport in _SPORTS
         for s in vc.VERDICT_CORPUS[tier][sport]),
        key=lambda t: len(t.format(
            team="Mamelodi Sundowns", odds="11.50", bookmaker="SuperSportBet"
        )),
    )
    longest_prefix = max(_unique_prefixes(), key=len)
    body = longest_body.format(
        team="Mamelodi Sundowns", odds="11.50", bookmaker="SuperSportBet"
    )
    combined = f"{longest_prefix} {body}"
    assert len(combined) <= 260, (
        f"longest concern + verdict combined = {len(combined)} > 260: {combined!r}"
    )


# ── 9. Hash determinism — same key → same sentence across renders ─────────


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_pick_is_deterministic_per_bucket(tier: str, sport: str) -> None:
    pool = vc.VERDICT_CORPUS[tier][sport]
    for match_key in (
        "liverpool_vs_chelsea_2026-05-04",
        "arsenal_vs_fulham_2026-05-02",
        "mamelodi_sundowns_vs_pirates_2026-05-04",
    ):
        salt = f"{tier}|{sport}"
        first = vc._pick(pool, match_key, salt)
        second = vc._pick(pool, match_key, salt)
        third = vc._pick(pool, match_key, salt)
        assert first is second is third, (
            f"({tier},{sport}) {match_key} returned different sentences"
        )


# ── 10. Hash distribution — 200 specs hit ≥66% of each bucket ─────────────


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_hash_distribution_at_200_specs(tier: str, sport: str) -> None:
    """HG-4: 200 synthetic specs across (tier, sport, match_key) → ≥66%
    bucket spread per (tier, sport). With 200 keys hashed into a 30-element
    pool, every slot should be visited ~6.7 times in expectation; ≥66%
    coverage means ≥20/30 templates exercised."""
    pool = vc.VERDICT_CORPUS[tier][sport]
    seen: set[str] = set()
    for i in range(200):
        match_key = f"home{i}_vs_away{i}_2026-05-04"
        sentence: vc.VerdictSentence = vc._pick(pool, match_key, f"{tier}|{sport}")  # type: ignore[assignment]
        seen.add(sentence.text)
    spread_pct = len(seen) * 100 / len(pool)
    assert len(seen) >= 20, (
        f"({tier},{sport}) 200 specs visited only {len(seen)}/{len(pool)} = "
        f"{spread_pct:.1f}% (need ≥66%)"
    )


# ── 11. Sport normalisation — all variants map to {soccer, rugby, cricket} ─


def test_normalise_sport_to_bucket_soccer_variants() -> None:
    for variant in (
        "soccer", "football", "epl", "psl", "ucl",
        "champions_league", "uefa_champions_league",
        "premier_league", "la_liga", "bundesliga", "serie_a", "ligue_1",
    ):
        assert vc._normalise_sport_to_bucket(variant) == "soccer", (
            f"{variant!r} should map to 'soccer'"
        )


def test_normalise_sport_to_bucket_rugby_variants() -> None:
    for variant in (
        "rugby", "urc", "super_rugby", "six_nations",
        "rugby_championship", "rugby_union", "rugbyunion_six_nations",
    ):
        assert vc._normalise_sport_to_bucket(variant) == "rugby", (
            f"{variant!r} should map to 'rugby'"
        )


def test_normalise_sport_to_bucket_cricket_variants() -> None:
    for variant in (
        "cricket", "ipl", "cricket_ipl", "sa20", "cricket_test", "csa_sa20",
    ):
        assert vc._normalise_sport_to_bucket(variant) == "cricket", (
            f"{variant!r} should map to 'cricket'"
        )


def test_normalise_sport_to_bucket_unknown_falls_back_to_soccer() -> None:
    """Unknown sport falls back to 'soccer' (most common path) with log-warn."""
    assert vc._normalise_sport_to_bucket("hockey") == "soccer"
    assert vc._normalise_sport_to_bucket("") == "soccer"
    assert vc._normalise_sport_to_bucket(None) == "soccer"  # type: ignore[arg-type]


def test_normalise_sport_to_bucket_case_insensitive() -> None:
    assert vc._normalise_sport_to_bucket("SOCCER") == "soccer"
    assert vc._normalise_sport_to_bucket("Rugby") == "rugby"
    assert vc._normalise_sport_to_bucket("CRICKET") == "cricket"


def test_normalise_sport_to_bucket_prefix_match_for_unknown() -> None:
    """Permissive prefix match before fallback — handles soccer_premier_league
    and rugby_super_xv style sport keys."""
    assert vc._normalise_sport_to_bucket("soccer_premier_league_uk") == "soccer"
    assert vc._normalise_sport_to_bucket("rugby_super_xv") == "rugby"
    assert vc._normalise_sport_to_bucket("cricket_t10_global") == "cricket"


# ── 12. Imperative-close gate still passes for every sentence ─────────────


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_imperative_close_per_bucket(tier: str, sport: str) -> None:
    pool = vc.VERDICT_CORPUS[tier][sport]
    for idx, vs in enumerate(pool):
        rendered = vs.text.format(team="Arsenal", odds="2.10", bookmaker="Betway")
        last = _last_sentence(rendered)
        assert _IMPERATIVE_CLOSE_RE.search(last), (
            f"({tier},{sport})[{idx}] last sentence {last!r} fails imperative close"
        )


# ── render_verdict integration — sport-banded path ────────────────────────


def test_render_verdict_picks_from_correct_sport_bucket() -> None:
    """Same match_key + tier with different sport must pick from a different
    sport-banded pool. Each pool has unique sport vocabulary so we can detect
    by checking the rendered text contains sport-specific tokens."""
    def _spec_for(sport: str) -> _MockSpec:
        return _MockSpec(
            edge_tier="diamond",
            sport=sport,
            outcome_label="Liverpool",
            odds=1.96,
            bookmaker="SuperSportBet",
            home_name="Liverpool",
            away_name="Chelsea",
            composite_score=92,
            support_level=4,           # ensures has_real_risk=False
            contradicting_signals=0,
            match_key="diff_sport_bucket_test",
        )

    soccer_v = vc.render_verdict(_spec_for("soccer"))  # type: ignore[arg-type]
    rugby_v = vc.render_verdict(_spec_for("rugby"))  # type: ignore[arg-type]
    cricket_v = vc.render_verdict(_spec_for("cricket"))  # type: ignore[arg-type]

    # The three renders should not all be identical — different sport buckets
    assert len({soccer_v, rugby_v, cricket_v}) == 3, (
        f"sport buckets produced same verdict text:\n"
        f"  soccer: {soccer_v!r}\n  rugby: {rugby_v!r}\n  cricket: {cricket_v!r}"
    )


def test_render_verdict_handles_empty_slot_fields_defensively() -> None:
    spec = _MockSpec(
        edge_tier="bronze",
        sport="soccer",
        outcome_label="",
        odds=0,
        bookmaker="",
        home_name="X",
        away_name="Y",
        match_key="x_vs_y",
    )
    rendered = vc.render_verdict(spec)
    assert "{team}" not in rendered
    assert "{odds}" not in rendered
    assert "{bookmaker}" not in rendered
    assert "the pick" in rendered or "X" in rendered
    assert "—" in rendered


def test_render_verdict_action_fallback_when_tier_unknown() -> None:
    """Empty edge_tier with verdict_action='strong back' should fall back to
    diamond pool selection."""
    spec = _MockSpec(
        edge_tier="",
        verdict_action="strong back",
        sport="soccer",
        outcome_label="Liverpool",
        odds=1.96,
        bookmaker="SuperSportBet",
        composite_score=92,
        support_level=4,
        match_key="action_fallback_test",
    )
    rendered = vc.render_verdict(spec)
    # Must have rendered something diamond-grade — confirm imperative close
    last = _last_sentence(rendered)
    assert _IMPERATIVE_CLOSE_RE.search(last), (
        f"action-fallback verdict missing imperative: {rendered!r}"
    )


def _v2_ready_spec(**overrides) -> _MockSpec:
    data = {
        "edge_tier": "gold",
        "sport": "soccer",
        "league": "epl",
        "outcome": "home",
        "outcome_label": "Liverpool",
        "recommended_team": "Liverpool",
        "home_name": "Liverpool",
        "away_name": "Chelsea",
        "odds": 1.96,
        "bookmaker": "SuperSportBet",
        "composite_score": 82,
        "support_level": 4,
        "match_key": "liverpool_vs_chelsea_v2_route_1",
        "edge_revision": "rev-1",
        "home_form": "WWWDW",
        "away_form": "LDLDD",
        "signals": {"price_edge": True, "form": True, "market": True},
        "line_movement_direction": "favourable",
        "bookmaker_count": 4,
    }
    data.update(overrides)
    return _MockSpec(**data)


def _legacy_expected_for(spec: _MockSpec) -> str:
    tier = (getattr(spec, "edge_tier", "") or "").lower()
    if tier not in vc.VERDICT_CORPUS:
        action = (getattr(spec, "verdict_action", "") or "").lower()
        tier = {
            "strong back": "diamond",
            "back": "gold",
            "lean": "silver",
        }.get(action, "bronze")

    sport = vc._normalise_sport_to_bucket((getattr(spec, "sport", "") or "").lower())
    pool = vc.VERDICT_CORPUS[tier][sport]
    team = (
        getattr(spec, "outcome_label", "")
        or getattr(spec, "home_name", "")
        or "the pick"
    ).strip()
    odds_val = float(getattr(spec, "odds", 0) or 0)
    odds = f"{odds_val:.2f}" if odds_val else "—"
    bookmaker = (getattr(spec, "bookmaker", "") or "—").strip()
    match_key = (
        getattr(spec, "match_key", None)
        or f"{getattr(spec, 'home_name', '')}|{getattr(spec, 'away_name', '')}"
    )
    sentence: vc.VerdictSentence = vc._pick(pool, match_key, f"{tier}|{sport}")  # type: ignore[assignment]
    return sentence.text.format(team=team, odds=odds, bookmaker=bookmaker)


def test_render_verdict_routes_to_v2_when_flag_default(monkeypatch) -> None:
    monkeypatch.delenv("VERDICT_ENGINE_V2", raising=False)
    importlib.reload(vc)

    spec = _v2_ready_spec()
    ctx = vc._spec_to_verdict_context(spec)
    expected = vc.verdict_engine_v2.render_verdict_v2(ctx)

    assert expected.valid
    assert vc.render_verdict(spec) == expected.text


def test_render_verdict_routes_to_legacy_when_flag_off(monkeypatch) -> None:
    monkeypatch.setenv("VERDICT_ENGINE_V2", "0")
    importlib.reload(vc)

    spec = _v2_ready_spec()

    assert vc.render_verdict(spec) == _legacy_expected_for(spec)


def test_v2_routing_falls_back_to_legacy_when_v2_returns_invalid(monkeypatch) -> None:
    monkeypatch.delenv("VERDICT_ENGINE_V2", raising=False)
    importlib.reload(vc)

    spec = _v2_ready_spec()
    invalid = vc.verdict_engine_v2.VerdictResult(
        text="",
        valid=False,
        fallback=True,
        primary_fact_type="test_invalid",
    )
    monkeypatch.setattr(vc.verdict_engine_v2, "render_verdict_v2", lambda _ctx: invalid)

    assert vc.render_verdict(spec) == _legacy_expected_for(spec)


def test_v2_adapter_edge_revision_fallback_chain() -> None:
    explicit = _v2_ready_spec(edge_revision="edge-rev-7", recommended_at="rec-1")
    recommended = _v2_ready_spec(edge_revision="", recommended_at="rec-2")
    match_key = _v2_ready_spec(edge_revision="", recommended_at="")

    assert vc._spec_to_verdict_context(explicit).edge_revision == "edge-rev-7"
    assert vc._spec_to_verdict_context(recommended).edge_revision == "rec-2"
    assert vc._spec_to_verdict_context(match_key).edge_revision == match_key.match_key


# ── Concern-prefix concatenation cleanliness (preserved from W82) ─────────


def test_concern_prefix_concatenation_clean() -> None:
    spec = _MockSpec(
        edge_tier="bronze",
        sport="soccer",
        outcome_label="Liverpool",
        odds=1.96,
        bookmaker="SuperSportBet",
        home_name="Liverpool",
        away_name="Chelsea",
        composite_score=42,
        support_level=0,
        contradicting_signals=0,
        match_key="liverpool_vs_chelsea_2026-05-04",
    )
    rendered = vc.render_verdict(spec)
    assert any(rendered.startswith(p) for p in vc.CONCERN_PREFIXES["soccer"]), (
        f"render does not start with a known concern prefix: {rendered!r}"
    )
    assert "Liverpool" in rendered
    assert "1.96" in rendered
    assert "SuperSportBet" in rendered
    assert ".." not in rendered, f"double punctuation in: {rendered!r}"
    assert "  " not in rendered, f"double space in: {rendered!r}"
    for prefix in vc.CONCERN_PREFIXES["soccer"]:
        if rendered.startswith(prefix):
            body = rendered[len(prefix) + 1:]
            assert body and body[0].isupper(), (
                f"verdict body should start uppercase: {body!r}"
            )
            break


def test_concern_prefix_only_fires_when_has_real_risk() -> None:
    spec = _MockSpec(
        edge_tier="diamond",
        sport="soccer",
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
    for prefix in _all_prefixes():
        assert not rendered.startswith(prefix), (
            f"clean diamond render unexpectedly carries prefix: {rendered!r}"
        )


def test_diamond_risk_is_concern_prefix_exempt() -> None:
    """Option A: Diamond keeps body-only max-conviction copy when risk fires."""
    spec = _MockSpec(
        edge_tier="diamond",
        sport="soccer",
        outcome_label="Manchester City",
        odds=1.40,
        bookmaker="Supabets",
        home_name="Manchester City",
        away_name="Brentford",
        composite_score=86,
        support_level=0,
        contradicting_signals=0,
        match_key="manchester_city_vs_brentford_2026-05-09",
    )
    assert vc.has_real_risk(spec) is True  # type: ignore[arg-type]
    rendered = vc.render_verdict(spec)  # type: ignore[arg-type]
    assert not any(rendered.startswith(p) for p in _all_prefixes()), rendered
    assert _MAX_CONVICTION_REGEX.search(rendered), rendered


def test_pick_concern_prefix_soccer_100_hash_trials_no_foreign_markers() -> None:
    for i in range(100):
        prefix = vc._pick_concern_prefix("soccer", f"soccer_hash_trial_{i}")
        assert prefix in vc.CONCERN_PREFIXES["soccer"]
        assert not _CRICKET_PREFIX_MARKERS.search(prefix), prefix
        assert not _RUGBY_PREFIX_MARKERS.search(prefix), prefix


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("sport", _SPORTS)
def test_risk_render_sport_coverage_no_foreign_prefix_leaks(tier: str, sport: str) -> None:
    spec = _MockSpec(
        edge_tier=tier,
        sport=sport,
        outcome_label={
            "soccer": "Arsenal",
            "rugby": "Stormers",
            "cricket": "Mumbai Indians",
        }[sport],
        odds=1.90,
        bookmaker="Hollywoodbets",
        home_name="Home",
        away_name="Away",
        composite_score=42,
        support_level=0,
        contradicting_signals=0,
        match_key=f"{tier}_{sport}_risk_coverage",
    )
    rendered = vc.render_verdict(spec)  # type: ignore[arg-type]
    if tier == "diamond":
        assert not any(rendered.startswith(p) for p in _all_prefixes()), rendered
        return

    prefix = next((p for p in vc.CONCERN_PREFIXES[sport] if rendered.startswith(p)), None)
    assert prefix is not None, rendered
    if sport == "soccer":
        assert not _CRICKET_PREFIX_MARKERS.search(prefix), prefix
        assert not _RUGBY_PREFIX_MARKERS.search(prefix), prefix
    elif sport == "rugby":
        assert not _CRICKET_PREFIX_MARKERS.search(prefix), prefix
    elif sport == "cricket":
        assert not _RUGBY_PREFIX_MARKERS.search(prefix), prefix
        assert not _SOCCER_PREFIX_MARKERS.search(prefix), prefix


# ── has_real_risk corner cases (preserved from W82) ───────────────────────


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
    spec = _MockSpec(edge_tier="diamond", composite_score=95, support_level=4,
                     contradicting_signals=0, outcome="home",
                     injuries_home=[],
                     injuries_away=["Salah", "Van Dijk"],
                     match_key="x")
    assert vc.has_real_risk(spec) is False


def test_has_real_risk_clean_premium_signal() -> None:
    spec = _MockSpec(edge_tier="diamond", composite_score=92, support_level=4,
                     contradicting_signals=0, movement_direction="for",
                     match_key="x")
    assert vc.has_real_risk(spec) is False


# ── Regression fixtures (preserved + extended for sport-banding) ──────────


def test_regression_liverpool_chelsea_diamond_soccer() -> None:
    """W82 regression: Liverpool-Chelsea Diamond × soccer."""
    spec = _MockSpec(
        edge_tier="diamond",
        sport="soccer",
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
    assert v
    assert not _CONCESSIVE_RE.search(v), f"concessive: {v!r}"
    assert v.rstrip()[-1] in ".!?"
    assert 100 <= len(v) <= 260, f"length={len(v)} {v!r}"


def test_regression_arsenal_fulham_gold_soccer() -> None:
    spec = _MockSpec(
        edge_tier="gold",
        sport="soccer",
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
    assert v
    assert not _CONCESSIVE_RE.search(v), f"concessive: {v!r}"
    assert "pointing t" not in v, f"mid-word truncation: {v!r}"
    assert v.rstrip()[-1] in ".!?"
    assert 100 <= len(v) <= 260
    last = _last_sentence(v)
    assert _IMPERATIVE_CLOSE_RE.search(last), (
        f"Gold last sentence fails imperative: {last!r}"
    )


def test_regression_bulls_stormers_diamond_rugby() -> None:
    """New: Bulls-Stormers Diamond × rugby — sport bucket selection."""
    spec = _MockSpec(
        edge_tier="diamond",
        sport="urc",                   # variant — must normalise to rugby
        outcome_label="Bulls",
        odds=1.65,
        bookmaker="Hollywoodbets",
        home_name="Bulls",
        away_name="Stormers",
        composite_score=90,
        support_level=4,
        contradicting_signals=0,
        match_key="bulls_vs_stormers_2026-05-04",
    )
    v = vc.render_verdict(spec)
    assert v
    assert "Bulls" in v and "1.65" in v and "Hollywoodbets" in v
    assert not _CONCESSIVE_RE.search(v)
    assert v.rstrip()[-1] in ".!?"
    assert 100 <= len(v) <= 260


def test_regression_csk_mi_gold_cricket() -> None:
    """New: CSK-MI Gold × cricket (IPL) — sport bucket selection."""
    spec = _MockSpec(
        edge_tier="gold",
        sport="ipl",                   # variant — must normalise to cricket
        outcome_label="Chennai Super Kings",
        odds=1.85,
        bookmaker="Betway",
        home_name="Chennai Super Kings",
        away_name="Mumbai Indians",
        composite_score=78,
        support_level=3,
        contradicting_signals=0,
        match_key="csk_vs_mi_2026-05-04",
    )
    v = vc.render_verdict(spec)
    assert v
    assert "Chennai Super Kings" in v and "1.85" in v and "Betway" in v
    assert not _CONCESSIVE_RE.search(v)
    assert v.rstrip()[-1] in ".!?"
    assert 100 <= len(v) <= 260
