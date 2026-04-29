"""FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 — AC-2 contract tests.

Vague-content pattern ban. Live failure case 2 (Manchester United vs Liverpool
Gold 2.38 Supabets, 29 Apr 2026 ~20:25 SAST): the AI Breakdown shipped
"looks like the sort of league fixture that takes shape once one side settles
into its preferred tempo", "the play is live without being loud", "Risk reads
clean here. The model and standard match volatility are the only live
variables." Individual phrases pass tier-band-tone gates and the
telemetry-vocabulary gate, but the CONTENT is empty calories — vague,
evidence-free, generic.

Tier policy:
  - Diamond + Gold hit → CRITICAL (refuse write).
  - Silver / Bronze hit → MAJOR (quarantine — non-premium row served, flagged
    for repolish).

Test surface: ≥15 tests covering each pattern, FP carve-outs, and end-to-end
integration through _validate_narrative_for_persistence.
"""
from __future__ import annotations

from narrative_validator import (
    VAGUE_CONTENT_PATTERNS,
    _check_vague_content_patterns,
    _validate_narrative_for_persistence,
)


# ── 1. Catalogue completeness ────────────────────────────────────────────────


def test_vague_pattern_catalogue_size():
    """Brief AC-2 lists 14 patterns. The catalogue must cover all of them."""
    assert len(VAGUE_CONTENT_PATTERNS) >= 14


def test_vague_pattern_labels_unique():
    """No two patterns share a label — labels are the dedup key."""
    labels = [label for _, label in VAGUE_CONTENT_PATTERNS]
    assert len(labels) == len(set(labels))


# ── 2. Each pattern fires individually ───────────────────────────────────────


def test_pattern_looks_like_the_sort_of_fires():
    text = "Manchester United against Liverpool looks like the sort of fixture."
    hits = _check_vague_content_patterns(text)
    assert "looks like the sort of" in hits


def test_pattern_takes_shape_fires():
    text = "Once it takes shape, the market will tighten."
    assert "takes shape" in _check_vague_content_patterns(text)


def test_pattern_settles_into_tempo_fires():
    text = "The team settles into its preferred tempo by half-time."
    assert "settles into its preferred tempo" in _check_vague_content_patterns(text)


def test_pattern_reads_clean_here_fires():
    text = "Risk reads clean here. The model is comfortable."
    assert "reads clean here" in _check_vague_content_patterns(text)


def test_pattern_only_live_variables_fires():
    text = "The model and match volatility are the only live variables."
    hits = _check_vague_content_patterns(text)
    assert "only live variables" in hits


def test_pattern_play_is_live_without_being_loud_fires():
    text = "Fair value sits around 43%, so the play is live without being loud."
    assert (
        "play is live without being loud"
        in _check_vague_content_patterns(text)
    )


def test_pattern_measured_rather_than_loud_fires():
    text = "Everything we have points the same way, measured rather than loud."
    assert (
        "measured rather than loud" in _check_vague_content_patterns(text)
    )


def test_pattern_standard_match_volatility_fires():
    text = "Standard match volatility is the only meaningful risk."
    assert (
        "standard match volatility" in _check_vague_content_patterns(text)
    )


def test_pattern_the_model_and_fires():
    text = "The model and standard match volatility are the only live variables."
    hits = _check_vague_content_patterns(text)
    assert "the model and" in hits


def test_pattern_everything_we_have_points_the_same_way_fires():
    text = "Everything we have points the same way."
    hits = _check_vague_content_patterns(text)
    assert "everything we have points the same way" in hits


def test_pattern_the_sort_of_fixture_fires():
    text = "It's the sort of fixture that defies the model."
    hits = _check_vague_content_patterns(text)
    assert "the sort of fixture" in hits


def test_pattern_once_one_side_settles_fires():
    text = "Once one side settles, the match-shape clarifies."
    hits = _check_vague_content_patterns(text)
    assert "once one side settles" in hits


def test_pattern_not_a_huge_edge_fires():
    text = "Not a huge edge, but it's there."
    assert "not a huge edge" in _check_vague_content_patterns(text)


def test_pattern_but_bookmaker_is_still_fires():
    """The Manchester United vs Liverpool live failure phrasing."""
    text = "Manchester United win is not a huge edge, but Supabets's 2.38 is still better than our number."
    hits = _check_vague_content_patterns(text)
    assert "but bookmaker odds is still better" in hits


# ── 3. Multi-hit detection (verbatim live failure) ───────────────────────────


def test_live_failure_case_multiple_hits():
    """Manchester United vs Liverpool verbatim Edge + Risk text fires multiple
    patterns simultaneously."""
    text = (
        "Manchester United against Liverpool in Premier League looks like the "
        "sort of league fixture that takes shape once one side settles into "
        "its preferred tempo. "
        "Manchester United win is not a huge edge, but Supabets's 2.38 is "
        "still better than our number. The play is live without being loud. "
        "Risk reads clean here. The model and standard match volatility are "
        "the only live variables. "
        "Back Manchester United win at 2.38 (Supabets) as a mild lean — "
        "everything we have points the same way, measured rather than loud."
    )
    hits = _check_vague_content_patterns(text)
    # Live failure should fire ≥ 6 distinct patterns.
    assert len(hits) >= 6


# ── 4. Clean-text false-positive guards ──────────────────────────────────────


def test_clean_premium_voice_passes():
    """SA Braai voice with concrete evidence triggers no patterns."""
    text = (
        "Slot's Reds have won 8 of 12 at home and Chelsea are leaking goals. "
        "Get on Liverpool at 1.97 with Supabets — squad rotation is the only "
        "concern but Slot has been confident in his XI."
    )
    assert _check_vague_content_patterns(text) == []


def test_clean_brand_voice_no_hits():
    """Concrete prose with team / manager / number entities → no hits."""
    text = (
        "Bournemouth pressed Newcastle hard last weekend (3-1 at the Vitality) "
        "and Iraola's lot have lost only 2 of their last 10 at home. "
        "Lean on Bournemouth at 2.40 — risk on Solanke fitness."
    )
    assert _check_vague_content_patterns(text) == []


def test_empty_input_returns_empty_list():
    assert _check_vague_content_patterns("") == []
    assert _check_vague_content_patterns("   ") == []


# ── 5. End-to-end through _validate_narrative_for_persistence ───────────────


def test_validator_e2e_gold_vague_content_critical():
    """Gold tier vague-content hit → CRITICAL (refuse write)."""
    narrative_html = (
        "📋 <b>The Setup</b>\n\n"
        "Manchester United against Liverpool in Premier League looks like "
        "the sort of league fixture that takes shape once one side settles "
        "into its preferred tempo.\n\n"
        "🎯 <b>The Edge</b>\n\n"
        "Not a huge edge, but Supabets's 2.38 is still better than our number.\n\n"
        "⚠️ <b>The Risk</b>\n\n"
        "Risk reads clean here. The model and standard match volatility are "
        "the only live variables.\n\n"
        "🏆 <b>Verdict</b>\n\n"
        "Back Manchester United at 2.38 with Supabets."
    )
    content = {
        "narrative_html": narrative_html,
        "verdict_html": "Back Manchester United at 2.38 with Supabets.",
        "match_id": "manchester_united_vs_liverpool_2026-04-29",
        "narrative_source": "w84",
    }
    result = _validate_narrative_for_persistence(
        content,
        evidence_pack={
            "home_team": "Manchester United",
            "away_team": "Liverpool",
        },
        edge_tier="gold",
        source_label="w84",
    )
    vague_failures = [f for f in result.failures if f.gate == "vague_content"]
    assert len(vague_failures) >= 1
    # At least one should be CRITICAL.
    assert any(f.severity == "CRITICAL" for f in vague_failures)
    assert not result.passed


def test_validator_e2e_silver_vague_content_major():
    """Silver tier vague-content hit → MAJOR (quarantine, not refuse)."""
    narrative_html = (
        "📋 <b>The Setup</b>\n\n"
        "This match looks like the sort of fixture that takes shape early.\n\n"
        "🎯 <b>The Edge</b>\n\n"
        "Edge is in the price.\n\n"
        "⚠️ <b>The Risk</b>\n\n"
        "Standard variance applies.\n\n"
        "🏆 <b>Verdict</b>\n\n"
        "Lean on Liverpool at 1.97."
    )
    content = {
        "narrative_html": narrative_html,
        "verdict_html": "Lean on Liverpool at 1.97.",
        "match_id": "x_vs_y_2026-04-29",
        "narrative_source": "w84",
    }
    result = _validate_narrative_for_persistence(
        content,
        evidence_pack={"home_team": "Liverpool", "away_team": "Chelsea"},
        edge_tier="silver",
        source_label="w84",
    )
    vague_failures = [f for f in result.failures if f.gate == "vague_content"]
    assert len(vague_failures) >= 1
    # Silver should be MAJOR, not CRITICAL.
    assert all(f.severity == "MAJOR" for f in vague_failures)


def test_validator_e2e_clean_premium_passes():
    """Clean concrete Strong-band voice with no vague phrases → no vague failures."""
    narrative_html = (
        "📋 <b>The Setup</b>\n\n"
        "Liverpool sit 2nd with 8 wins from 12 league matches and 22 goals "
        "scored at Anfield this season. Chelsea have shipped 14 in their last "
        "five and managed only 1 win in eight away.\n\n"
        "🎯 <b>The Edge</b>\n\n"
        "Supabets are 1.97 vs our fair price 2.10. The 7% gap is sharp.\n\n"
        "⚠️ <b>The Risk</b>\n\n"
        "Slot may rotate with the cup tie three days later.\n\n"
        "🏆 <b>Verdict</b>\n\n"
        "Get on Liverpool at 1.97 with Supabets."
    )
    content = {
        "narrative_html": narrative_html,
        "verdict_html": "Get on Liverpool at 1.97 with Supabets.",
        "match_id": "liverpool_vs_chelsea_2026-04-29",
        "narrative_source": "w84",
    }
    result = _validate_narrative_for_persistence(
        content,
        evidence_pack={"home_team": "Liverpool", "away_team": "Chelsea"},
        edge_tier="gold",
        source_label="w84",
    )
    vague_failures = [f for f in result.failures if f.gate == "vague_content"]
    assert vague_failures == []
