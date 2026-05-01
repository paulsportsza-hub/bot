"""FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 — AC-1 contract tests.

Validates the new Strong-band tone-lock gate in `narrative_validator.py`:

1. Each banned pattern in `STRONG_BAND_INCOMPATIBLE_PATTERNS` fires correctly
   on a synthetic Gold/Diamond verdict that contains the phrase.
2. Clean Strong-band text passes (zero false positives).
3. Tier-aware enforcement matrix:
     - Diamond + Gold hit → CRITICAL refuse-write
     - Silver hit → MAJOR quarantine
     - Bronze → ALLOWED (cautious-band IS the correct register)
4. Hedging-conditional opener detection — Paul's exact verbatim case +
   5 close variants (but / however / though / although / yet).
5. End-to-end through `_validate_narrative_for_persistence` (Gate 9 wiring).

Brief: FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 (29 April 2026)
Live failure case: Manchester City vs Brentford GOLD verdict at Supabets 1.36
shipped "the form picture is unclear and there's limited edge to work with
here ... this is a cautious lean rather than a confident call". Paul rejected
inconsistent-with-tier voice; brief says Strong-band MUST speak Strong-band.
"""
from __future__ import annotations

import pytest

from narrative_validator import (
    STRONG_BAND_INCOMPATIBLE_PATTERNS,
    _check_hedging_conditional_opener,
    _check_tier_band_tone,
    _validate_narrative_for_persistence,
)


# ── 1. Banned-pattern catalogue completeness (AC-1.1) ────────────────────────


def test_strong_band_pattern_catalogue_minimum_size():
    """Brief AC-1 lists 16 distinct patterns across 3 failure shapes.

    Splits: 7 cautious framing + 5 evidence-poor hedging + 4 hedging closers
    (some overlap on borderline cases). The catalogue must carry ≥14 patterns
    to cover Paul's verbatim failure shape + close variants.
    """
    assert len(STRONG_BAND_INCOMPATIBLE_PATTERNS) >= 14


def test_strong_band_pattern_labels_unique():
    """No two patterns share a label — labels are the hit-deduplication key."""
    labels = [label for _, label in STRONG_BAND_INCOMPATIBLE_PATTERNS]
    assert len(labels) == len(set(labels))


# ── 2. Per-pattern firing on Gold/Diamond text (AC-1.2 — 13 patterns) ────────


@pytest.mark.parametrize(
    "phrase,expected_label",
    [
        # Cautious framing
        ("This is a cautious lean rather than a confident call.", "cautious lean"),
        ("Take it as a cautious play.", "cautious lean"),
        ("Approach this cautiously.", "cautious lean"),  # Should NOT fire
        ("There's limited edge to work with here.", "limited edge"),
        ("Thin edge on this fixture.", "limited edge"),
        ("No edge to work with right now.", "no edge to work with"),
        ("The form picture is unclear.", "form picture is unclear"),
        ("Picture is murky on this one.", "form picture is unclear"),
        ("This is a cautious lean rather than a confident call.",
         "rather than a confident call"),
        ("Speculative punt on this one.", "speculative punt"),
        ("Speculative bet at the current number.", "speculative punt"),
        ("Tiny exposure here, no hero call.", "tiny exposure"),
        ("Small exposure only on this fixture.", "small exposure only"),
        # Evidence-poor hedging
        ("Without recent form, hard to read this.", "without recent form"),
        ("Without head-to-head context, this is shaky.", "without recent form"),
        ("No recent form to anchor the read.", "no recent form"),
        ("Little recent context on this matchup.", "no recent form"),
        ("Data is thin on this fixture.", "data is thin"),
        ("Data is sparse on the form picture.", "data is thin"),
        ("Not enough to back at this number.", "not enough to back"),
        ("Not enough to recommend with confidence.", "not enough to back"),
        # Hedging closers
        ("This is a lean rather than a confident call.",
         "lean rather than a confident call"),
        ("One to watch rather than back at this price.",
         "one to watch rather than back"),
        ("Monitor only — not a back here.", "monitor only"),
    ],
)
def test_pattern_fires_on_gold_text(phrase, expected_label):
    """Each banned phrase fires when the tier is Gold."""
    hits, _hedging = _check_tier_band_tone(phrase, "gold", "verdict_html")
    if "cautiously" in phrase.lower() and "lean" not in phrase.lower():
        # Word-boundary scope: bare "cautiously" without lean/play/call/bet/
        # stake/approach/read suffix should NOT fire (legitimate prose).
        assert hits == [], f"False positive on {phrase!r}"
        return
    assert expected_label in hits, (
        f"Phrase {phrase!r} expected to hit label {expected_label!r}; got {hits!r}"
    )


# ── 3. Clean Strong-band text passes (AC-1.3) ────────────────────────────────


@pytest.mark.parametrize(
    "clean_verdict",
    [
        # Diamond Strong-band exemplar (verdict-generator skill)
        "Back Guardiola's City at 1.36 with Supabets — form solid, attack on song, "
        "Brentford bring nothing on the road. Get on it before the line moves.",
        # Gold Strong-band exemplar
        "Take Arsenal at 1.85 with Hollywoodbets — Arteta's lot are flying, "
        "Tottenham have lost five on the bounce. Standard stake on this one.",
        # Diamond conviction
        "Premium back on Liverpool at 1.97 with Supabets — Slot's Reds are scoring "
        "for fun, the case is built. Standard-to-heavy stake on this one.",
        # Gold disciplined
        "Back Brighton at 1.38 against a Wolves side that's only won twice in 12. "
        "Easy money — just be ready for the late equaliser.",
        # Diamond market-mispriced framing
        "Take Pereira's Forest at 2.52 with Betway with conviction — solid at home, "
        "Newcastle leaking late goals. Premium value on the form at this number.",
    ],
)
def test_clean_strong_band_passes(clean_verdict):
    """Zero false positives on clean Strong-band exemplars (Diamond + Gold)."""
    hits_d, hedging_d = _check_tier_band_tone(clean_verdict, "diamond", "verdict_html")
    hits_g, hedging_g = _check_tier_band_tone(clean_verdict, "gold", "verdict_html")
    assert hits_d == [], f"False positive on Diamond clean: {hits_d!r}"
    assert hits_g == [], f"False positive on Gold clean: {hits_g!r}"
    assert not hedging_d
    assert not hedging_g


# ── 4. Tier-aware enforcement matrix (AC-1.4) ────────────────────────────────


def test_bronze_tier_skips_scan_entirely():
    """Bronze tier MUST skip the entire Strong-band scan.

    Cautious-band IS Bronze's correct register per verdict-generator skill
    rubric. The function returns ([], False) regardless of content.
    """
    cautious_text = (
        "This is a cautious lean rather than a confident call — "
        "limited edge to work with, without recent form context."
    )
    hits, hedging = _check_tier_band_tone(cautious_text, "bronze", "verdict_html")
    assert hits == [], "Bronze must accept cautious-band vocabulary"
    assert not hedging, "Bronze must accept hedging openers"


def test_diamond_tier_fires_on_speculative_punt():
    """Diamond MUST fire on `speculative punt` (Bronze-only register)."""
    text = "Take a speculative punt on this — small exposure only."
    hits, _ = _check_tier_band_tone(text, "diamond", "verdict_html")
    assert "speculative punt" in hits


def test_gold_tier_fires_on_cautious_lean():
    """Gold MUST fire on `cautious lean` (Bronze-only register)."""
    text = "City are the pick at 1.36, but this is a cautious lean rather than a confident call."
    hits, _ = _check_tier_band_tone(text, "gold", "verdict_html")
    assert "cautious lean" in hits
    assert "rather than a confident call" in hits


def test_silver_tier_fires_on_strong_band_vocabulary():
    """Silver MUST fire (MAJOR severity in caller; the helper itself is
    severity-agnostic — it returns hits, the caller maps tier→severity)."""
    text = "Limited edge on this one — no edge to work with right now."
    hits, _ = _check_tier_band_tone(text, "silver", "verdict_html")
    assert "limited edge" in hits
    assert "no edge to work with" in hits


# ── 5. Hedging-conditional opener detection (AC-1.5 — verbatim + variants) ───


def test_hedging_opener_pauls_verbatim_case():
    """Paul's exact verbatim Manchester City vs Brentford failure case fires."""
    verbatim = (
        "City are the pick at Supabets at 1.36, but the form picture is "
        "unclear and there's limited edge to work with here."
    )
    assert _check_hedging_conditional_opener(verbatim) is True


@pytest.mark.parametrize(
    "verdict_text,expected",
    [
        # 5 close variants matching Paul's exact shape
        ("Liverpool look strong at 1.97, however the form is mixed.", True),
        ("Arsenal are the play at 1.85, though questions remain.", True),
        ("Brighton at 1.38 is appealing, although the data is thin.", True),
        ("Forest at 2.52, yet the recent form gives pause.", True),
        ("Sundowns at 1.55 with Hollywoodbets, but the rotation risk hovers.", True),
        # Negative cases — comma followed by NON-hedging conjunction
        ("Liverpool at 1.97 is too good — Slot's lot are flying, get on it.",
         False),  # Em-dash separator, comma followed by imperative
        ("Take Arsenal at 1.85, the lean is on form.", False),  # No hedging conj
        ("Back City at 1.36 with Supabets — form solid, attack on song.",
         False),  # Em-dash, comma followed by descriptor
        ("R200 returns R330 · Edge confirmed. City to cover.", False),  # Diamond shape, no comma+hedge
        ("Premium back on Liverpool at 1.97 with Supabets — case is built.",
         False),  # Em-dash, no comma at all in first clause
    ],
)
def test_hedging_opener_variants(verdict_text, expected):
    """Hedging-conditional opener detection covers all 5 conjunctions + clean shapes."""
    assert _check_hedging_conditional_opener(verdict_text) is expected


def test_hedging_opener_handles_html_tags():
    """HTML-stripped scanning — `<b>`-wrapped headers do not count as text."""
    html_verdict = (
        "<b>City</b> are the pick at 1.36, but the form picture is unclear."
    )
    assert _check_hedging_conditional_opener(html_verdict) is True


def test_hedging_opener_empty_text():
    """Empty string must return False (no scan possible)."""
    assert _check_hedging_conditional_opener("") is False
    assert _check_hedging_conditional_opener("   ") is False


def test_hedging_opener_no_comma():
    """Verdict with no comma — no first-clause delimiter — must return False."""
    text = "Back Liverpool at 1.97 with Supabets. Standard stake on this one."
    assert _check_hedging_conditional_opener(text) is False


# ── 6. End-to-end through _validate_narrative_for_persistence (AC-1.6) ───────


def test_e2e_gold_critical_refuse_on_pauls_verbatim_case():
    """Paul's verbatim failure case validated as Gold returns CRITICAL."""
    verdict_html = (
        "City are the pick at Supabets at 1.36, but the form picture is "
        "unclear and there's limited edge to work with here. The odds are "
        "short and without recent form or head-to-head context, this is a "
        "cautious lean rather than a confident call — Back City."
    )
    content = {
        "narrative_html": "",
        "verdict_html": verdict_html,
        "match_id": "manchester_city_vs_brentford_2026-04-29",
        "narrative_source": "w84-haiku-fallback",
    }
    result = _validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="gold",
        source_label="w84-haiku-fallback",
    )
    assert result.passed is False
    assert result.severity == "CRITICAL"
    # Should fire BOTH the strong_band_tone gate (5+ banned vocab hits) AND
    # the hedging_opener gate.
    failed_gates = {f.gate for f in result.failures}
    assert "strong_band_tone" in failed_gates
    assert "strong_band_hedging_opener" in failed_gates


def test_e2e_diamond_critical_refuse_on_cautious_punt():
    """Diamond verdict containing `speculative punt` returns CRITICAL refuse."""
    verdict_html = (
        "Take a speculative punt on Liverpool at 1.97 with Supabets — "
        "tiny exposure here, no hero call."
    )
    content = {
        "narrative_html": "",
        "verdict_html": verdict_html,
        "match_id": "liverpool_vs_chelsea_2026-04-29",
        "narrative_source": "w82",
    }
    result = _validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="diamond",
        source_label="w82",
    )
    assert result.passed is False
    assert result.severity == "CRITICAL"
    assert "strong_band_tone" in {f.gate for f in result.failures}


def test_e2e_silver_major_quarantine_on_limited_edge():
    """Silver verdict with `limited edge` returns MAJOR quarantine.

    FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01 (2026-04-30): closing sentence has
    been updated to retain an action verb so Gate 10 (closure rule) does not
    fire CRITICAL — the test still asserts the strong_band_tone MAJOR.
    """
    verdict_html = (
        "Take Brighton at 1.78 with Betway — limited edge on this one, "
        "but the price has room. Take Brighton at 1.78 with Betway."
    )
    content = {
        "narrative_html": "",
        "verdict_html": verdict_html,
        "match_id": "brighton_vs_wolves_2026-04-29",
        "narrative_source": "w82",
    }
    result = _validate_narrative_for_persistence(
        content,
        evidence_pack={"home_team": "Brighton", "away_team": "Wolves"},
        edge_tier="silver",
        source_label="w82",
    )
    # Silver hit = MAJOR (not CRITICAL). Result still fails (passed=False)
    # because passed requires zero CRITICAL AND zero MAJOR.
    assert result.passed is False
    assert result.severity == "MAJOR"
    assert "strong_band_tone" in {f.gate for f in result.failures}


def test_e2e_bronze_passes_with_cautious_vocabulary():
    """Bronze verdict with full cautious-band vocabulary PASSES (correct register)."""
    verdict_html = (
        "Take a speculative punt on Bournemouth at 3.20 with Hollywoodbets — "
        "limited edge here, this is a cautious lean rather than a confident call. "
        "Tiny exposure only."
    )
    content = {
        "narrative_html": "",
        "verdict_html": verdict_html,
        "match_id": "bournemouth_vs_sheffield_united_2026-04-30",
        "narrative_source": "w82",
    }
    result = _validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="bronze",
        source_label="w82",
    )
    # Bronze: Strong-band gate skipped entirely; cautious is correct register.
    sb_failures = [f for f in result.failures if f.gate == "strong_band_tone"]
    sb_hedging = [f for f in result.failures if f.gate == "strong_band_hedging_opener"]
    assert sb_failures == [], (
        "Bronze must NOT fire strong_band_tone gate; got "
        f"{[(f.severity, f.detail) for f in sb_failures]}"
    )
    assert sb_hedging == [], "Bronze must NOT fire hedging-opener gate"


def test_e2e_clean_diamond_passes():
    """Clean Diamond verdict passes Gate 9."""
    verdict_html = (
        "Premium back on Liverpool at 1.97 with Supabets — the depth of "
        "evidence most edges don't carry, the case is built. "
        "Standard-to-heavy stake on this one."
    )
    content = {
        "narrative_html": "",
        "verdict_html": verdict_html,
        "match_id": "liverpool_vs_chelsea_2026-04-30",
        "narrative_source": "w84-haiku-fallback",
    }
    result = _validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="diamond",
        source_label="w84-haiku-fallback",
    )
    # No strong-band-tone failures.
    sb_failures = [f for f in result.failures if f.gate == "strong_band_tone"]
    sb_hedging = [f for f in result.failures if f.gate == "strong_band_hedging_opener"]
    assert sb_failures == []
    assert sb_hedging == []


def test_e2e_gold_verdict_cautious_band_leak_fires():
    """Gate 9 fires on cautious-band leak in verdict_html on a Gold card.

    FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-2:
    the narrative_html scope of Gate 9 was dropped; only the verdict_html
    surface is scanned now (the polish path no longer writes the long-form
    Setup/Edge/Risk sections). Test reframed to feed the cautious-band
    leak through verdict_html instead.
    """
    verdict_html = (
        "Slot's Reds at home, the form picture is unclear on this one — "
        "Back Liverpool at 1.97 with Supabets."
    )
    content = {
        "narrative_html": "",
        "verdict_html": verdict_html,
        "match_id": "liverpool_vs_chelsea_2026-04-30",
        "narrative_source": "w84-haiku-fallback",
    }
    result = _validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="gold",
        source_label="w84-haiku-fallback",
    )
    assert result.passed is False
    assert result.severity == "CRITICAL"
    sb_failures = [f for f in result.failures if f.gate == "strong_band_tone"]
    assert len(sb_failures) >= 1
    assert any("verdict_html" in f.section for f in sb_failures)


# ── 7. Result idempotence (AC-1.7) ───────────────────────────────────────────


def test_validator_idempotent_on_strong_band_hits():
    """Calling the validator twice with the same input produces structurally
    identical results — same gate ordering, same hit labels.

    Validator-architecture invariant from the docstring: ``The validator is
    *idempotent*``. Without this, monitoring + AC-9 corpus-delta verification
    cannot rely on stable gate signatures."""
    verdict_html = (
        "City are the pick at 1.36, but the form picture is unclear and "
        "there's limited edge to work with here."
    )
    content = {
        "narrative_html": "",
        "verdict_html": verdict_html,
        "match_id": "test_2026-04-30",
        "narrative_source": "w82",
    }
    r1 = _validate_narrative_for_persistence(
        content, None, edge_tier="gold", source_label="w82"
    )
    r2 = _validate_narrative_for_persistence(
        content, None, edge_tier="gold", source_label="w82"
    )
    assert r1.passed == r2.passed
    assert r1.severity == r2.severity
    assert len(r1.failures) == len(r2.failures)
    for f1, f2 in zip(r1.failures, r2.failures):
        assert f1.gate == f2.gate
        assert f1.severity == f2.severity
        assert f1.section == f2.section
