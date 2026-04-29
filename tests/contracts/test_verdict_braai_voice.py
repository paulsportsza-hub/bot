"""FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 AC-2 — verdict prompt braai voice.

Validates two things:

1. **Prompt structure** — `evidence_pack.format_evidence_prompt` injects the
   ⛔ BRAAI VOICE — NOT QUANT VOICE block (with verbatim BAD/GOOD examples)
   into the static cache prefix on BOTH branches (match_preview and edge).
   The block sits ABOVE the EVIDENCE PACK split sentinel so it is reused
   across every polish call without re-billing the prompt prefix
   (Rule 22 invariant).

2. **W82 baseline verdict text** — generate 30 verdicts via
   `narrative_spec._render_verdict` against synthetic `NarrativeSpec`
   objects spanning all 4 tiers + multiple leagues, and assert:
     * 0/30 hit telemetry-vocabulary regex (Rule 17 + AC-1 catalogue)
     * ≥25/30 contain at least one of the action-verb cluster
       (get on, back, take, worth, ride, leave)
     * 100% within 100-260 char range

Why W82 baseline rather than live polish: the W82 path is deterministic and
hits zero LLM cost. The polish-path equivalent test would require an
Anthropic API key + ~$0.50/run. The braai-voice prompt instructions are
validated via the structural test — the W82 templates are validated by the
output assertions.
"""
from __future__ import annotations

import re

import pytest

from narrative_spec import NarrativeSpec, _render_verdict


# ── Action-verb cluster (per brief AC-2 test instruction) ────────────────────
_ACTION_VERBS = ("get on", "back", "take", "worth", "ride", "leave")
_ACTION_VERB_RE = re.compile(
    r"\b(?:get on|back|take|worth|ride|leave)\b", re.IGNORECASE
)

# ── Telemetry vocabulary regex (mirror of AC-1 catalogue) ────────────────────
# Compiled here to keep this test independent of the validator import surface.
_TELEMETRY_RE_LIST: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bthe\s+(?:supporting\s+)?signals?\b",
        r"\bthe\s+reads?\b",
        r"\breads?\s+flag\b",
        r"\bbookmaker\s+(?:has\s+)?slipp(?:ed|ing|s)\b",
        r"\b(?:stays?|kept|keeps?|remains?|stay)\s+in\s+view\b",
        r"\bthe\s+case\s+(?:as\s+it\s+stands|here)\b",
        r"\b(?:the\s+)?model\s+(?:estimates|implies|prices?)\b",
        r"\bindicators?\s+(?:line\s+up|align)\b",
        r"\bstructural\s+(?:signal|lean|read)\b",
        r"\bprice\s+edge\b",
        r"\bsignal[-\s]aware\b",
        r"\bedge\s+confirms?\b",
    )
)


def _has_telemetry_leak(text: str) -> bool:
    return any(p.search(text) for p in _TELEMETRY_RE_LIST)


def _has_action_verb(text: str) -> bool:
    return bool(_ACTION_VERB_RE.search(text))


# ── Prompt-structure tests (AC-2.1) ──────────────────────────────────────────


@pytest.fixture
def _patched_evidence_pack():
    """Build a minimal EvidencePack instance for prompt rendering."""
    from evidence_pack import EvidencePack

    pack = EvidencePack(
        match_key="liverpool_vs_chelsea_2026-04-30",
        sport="soccer",
        league="EPL",
        built_at="2026-04-29T16:00:00+00:00",
        sources_total=10,
        sources_available=8,
        richness_score="HIGH",
    )
    return pack


def _make_spec() -> NarrativeSpec:
    """Synthetic NarrativeSpec covering enough fields to render a verdict."""
    return NarrativeSpec(
        sport="soccer",
        competition="EPL",
        home_name="Liverpool",
        away_name="Chelsea",
        home_story_type="momentum",
        away_story_type="setback",
        home_form="WWWWL",
        away_form="LLLLW",
        outcome="home",
        outcome_label="Liverpool",
        odds=1.97,
        bookmaker="Supabets",
        ev_pct=5.2,
        fair_prob_pct=58.0,
        support_level=2,
        contradicting_signals=0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="back",
        verdict_sizing="standard stake",
    )


def test_prompt_contains_braai_voice_block_match_preview(_patched_evidence_pack):
    """Match-preview branch carries the ⛔ BRAAI VOICE marker + 4 BAD examples."""
    from evidence_pack import format_evidence_prompt

    pack = _patched_evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=True)
    assert isinstance(prompt, str)
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" in prompt
    # 4 BAD examples from brief AC-2.
    assert "the supporting signals back the read" in prompt
    assert "the bookmaker has slipped" in prompt
    assert "the reads flag stays in view" in prompt
    assert "Standard stake on the case as it stands" in prompt
    # 3 GOOD examples from brief AC-2.
    assert "Liverpool at 1.97 is too good" in prompt
    assert "Brighton at 1.38 against a Wolves side" in prompt
    assert "Pereira's Forest at 2.52" in prompt


def test_prompt_contains_braai_voice_block_edge_branch(_patched_evidence_pack):
    """Edge branch carries the same braai voice marker + examples."""
    from evidence_pack import format_evidence_prompt

    pack = _patched_evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert isinstance(prompt, str)
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" in prompt
    assert "the supporting signals back the read" in prompt
    assert "Liverpool at 1.97 is too good" in prompt


def test_braai_voice_block_sits_above_evidence_pack_split(_patched_evidence_pack):
    """Rule 22 invariant: BRAAI VOICE marker is in the STATIC (cached) prefix.

    `format_evidence_prompt(return_split=True)` returns ``(static, dynamic)``
    where the cache_control directive applies only to the static block. The
    BRAAI VOICE block must sit in static — otherwise the prompt-cache hit
    rate degrades and the marker no longer appears in cached prefixes.
    """
    from evidence_pack import format_evidence_prompt

    pack = _patched_evidence_pack
    spec = _make_spec()
    static, dynamic = format_evidence_prompt(
        pack, spec, match_preview=False, return_split=True
    )
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" in static
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" not in dynamic
    static_pre, dynamic_pre = format_evidence_prompt(
        pack, spec, match_preview=True, return_split=True
    )
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" in static_pre
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" not in dynamic_pre


def test_action_verb_cluster_listed_in_prompt(_patched_evidence_pack):
    from evidence_pack import format_evidence_prompt

    pack = _patched_evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    # Brief AC-2 instructs the prompt to list the cluster verbatim.
    assert "ACTION VERB CLUSTER" in prompt
    assert "get on, back, take, worth, ride, leave" in prompt


# ── W82 baseline rendering tests (AC-2.2) ────────────────────────────────────


def _generate_30_verdicts() -> list[str]:
    """Generate 30 deterministic verdicts spanning 4 tiers + multiple leagues."""
    fixtures = [
        # 4 Diamond examples
        ("liverpool", "chelsea", "EPL", "soccer", "diamond", "strong", "back",
         "strong stake", "Hollywoodbets", 1.97, 7.5, 4),
        ("manchester_city", "arsenal", "EPL", "soccer", "diamond", "strong",
         "strong back", "premium stake", "Supabets", 1.65, 12.0, 5),
        ("real_madrid", "barcelona", "La Liga", "soccer", "diamond", "strong",
         "back", "standard stake", "Betway", 2.10, 8.3, 4),
        ("kaizer_chiefs", "orlando_pirates", "PSL", "soccer", "diamond",
         "strong", "back with confidence", "premium stake", "Hollywoodbets",
         1.90, 9.1, 4),
        # 8 Gold examples
        ("liverpool", "manchester_united", "EPL", "soccer", "gold", "confident",
         "back", "standard stake", "Supabets", 1.85, 5.8, 3),
        ("arsenal", "tottenham", "EPL", "soccer", "gold", "confident", "back",
         "standard stake", "Hollywoodbets", 2.15, 4.2, 3),
        ("brighton", "wolves", "EPL", "soccer", "gold", "confident", "back",
         "standard stake", "Betway", 1.38, 6.1, 3),
        ("nottingham_forest", "newcastle", "EPL", "soccer", "gold", "confident",
         "back", "standard stake", "Supabets", 2.52, 4.8, 3),
        ("mamelodi_sundowns", "supersport_united", "PSL", "soccer", "gold",
         "confident", "back", "standard stake", "Hollywoodbets", 1.55, 5.5, 3),
        ("leinster", "munster", "URC", "rugby", "gold", "confident", "back",
         "standard stake", "Betway", 1.72, 4.5, 3),
        ("bulls", "stormers", "URC", "rugby", "gold", "confident", "back",
         "standard stake", "Hollywoodbets", 2.05, 5.1, 3),
        ("mumbai_indians", "chennai_super_kings", "IPL", "cricket", "gold",
         "confident", "back", "standard stake", "Supabets", 1.95, 5.0, 3),
        # 9 Silver examples
        ("aston_villa", "everton", "EPL", "soccer", "silver", "moderate",
         "lean", "small-to-standard stake", "Betway", 1.78, 3.2, 2),
        ("crystal_palace", "fulham", "EPL", "soccer", "silver", "moderate",
         "lean", "small-to-standard stake", "Hollywoodbets", 2.50, 3.0, 2),
        ("west_ham", "brentford", "EPL", "soccer", "silver", "moderate", "lean",
         "small-to-standard stake", "Supabets", 2.08, 2.9, 2),
        ("burnley", "luton", "EPL", "soccer", "silver", "moderate", "lean",
         "small-to-standard stake", "Betway", 1.92, 3.1, 2),
        ("polokwane_city", "amazulu", "PSL", "soccer", "silver", "moderate",
         "lean", "small-to-standard stake", "Hollywoodbets", 2.65, 2.8, 2),
        ("sharks", "lions", "URC", "rugby", "silver", "moderate", "lean",
         "small-to-standard stake", "Supabets", 1.85, 2.7, 2),
        ("ulster", "connacht", "URC", "rugby", "silver", "moderate", "lean",
         "small-to-standard stake", "Betway", 2.20, 3.0, 2),
        ("rajasthan_royals", "delhi_capitals", "IPL", "cricket", "silver",
         "moderate", "lean", "small-to-standard stake", "Hollywoodbets", 1.88,
         3.3, 2),
        ("gujarat_titans", "lucknow_supergiants", "IPL", "cricket", "silver",
         "moderate", "lean", "small-to-standard stake", "Supabets", 2.05, 2.6, 2),
        # 9 Bronze examples
        ("bournemouth", "sheffield_united", "EPL", "soccer", "bronze",
         "cautious", "monitor", "small-stake speculative", "Hollywoodbets",
         3.20, 1.5, 0),
        ("leicester", "leeds", "EPL", "soccer", "bronze", "cautious", "monitor",
         "small-stake speculative", "Betway", 2.95, 1.2, 0),
        ("rangers_fc", "celtic", "Scottish Premiership", "soccer", "bronze",
         "cautious", "pass", "no stake", "Supabets", 4.50, 1.0, 0),
        ("southampton", "norwich", "Championship", "soccer", "bronze",
         "cautious", "monitor", "small-stake speculative", "Hollywoodbets",
         2.70, 1.3, 1),
        ("cape_town_city", "stellenbosch", "PSL", "soccer", "bronze", "cautious",
         "monitor", "small-stake speculative", "Betway", 3.10, 1.1, 0),
        ("wales", "italy", "Six Nations", "rugby", "bronze", "cautious",
         "monitor", "small-stake speculative", "Supabets", 3.50, 1.4, 0),
        ("scotland", "france", "Six Nations", "rugby", "bronze", "cautious",
         "monitor", "small-stake speculative", "Hollywoodbets", 4.20, 1.6, 0),
        ("punjab_kings", "kolkata_knight_riders", "IPL", "cricket", "bronze",
         "cautious", "monitor", "small-stake speculative", "Betway", 2.85, 1.5, 0),
        ("sunrisers_hyderabad", "royal_challengers_bangalore", "IPL", "cricket",
         "bronze", "cautious", "monitor", "small-stake speculative", "Supabets",
         2.40, 1.0, 1),
    ]
    verdicts: list[str] = []
    for (
        home,
        away,
        comp,
        sport,
        tier,
        tone_band,
        verdict_action,
        verdict_sizing,
        bookmaker,
        odds,
        ev,
        confirming,
    ) in fixtures:
        spec = NarrativeSpec(
            sport=sport,
            competition=comp,
            home_name=home.replace("_", " ").title(),
            away_name=away.replace("_", " ").title(),
            home_story_type="momentum",
            away_story_type="setback",
            home_form="WWWLW",
            away_form="LLWLW",
            outcome="home",
            outcome_label=home.replace("_", " ").title(),
            odds=odds,
            bookmaker=bookmaker,
            ev_pct=ev,
            fair_prob_pct=55.0,
            support_level=confirming,
            contradicting_signals=0,
            evidence_class=(
                "conviction" if tier == "diamond"
                else "supported" if tier == "gold"
                else "lean" if tier == "silver"
                else "speculative"
            ),
            tone_band=tone_band,
            verdict_action=verdict_action,
            verdict_sizing=verdict_sizing,
            edge_tier=tier,
        )
        verdicts.append(_render_verdict(spec))
    assert len(verdicts) == 30
    return verdicts


def test_w82_verdicts_have_zero_telemetry_leaks():
    """0/30 W82 baseline verdicts hit the telemetry-vocabulary regex catalogue."""
    verdicts = _generate_30_verdicts()
    leaks = [(i, v) for i, v in enumerate(verdicts) if _has_telemetry_leak(v)]
    assert leaks == [], (
        f"Telemetry leak in {len(leaks)}/30 W82 verdicts: "
        f"{[(i, v[:120]) for i, v in leaks[:5]]}"
    )


def test_w82_verdicts_use_action_verbs_majority():
    """≥25/30 W82 baseline verdicts contain at least one action verb.

    Pass tier (Bronze cautious) verdicts may legitimately omit action verbs
    when the verdict is a pass/monitor recommendation (per Rule 14: pass-mode
    variants don't push action). Threshold of 25 allows up to 5 pass/monitor
    cases without failing the gate.
    """
    verdicts = _generate_30_verdicts()
    with_verb = [v for v in verdicts if _has_action_verb(v)]
    assert len(with_verb) >= 25, (
        f"Only {len(with_verb)}/30 verdicts contain an action verb "
        f"({_ACTION_VERBS}). Brief AC-2 requires ≥25/30."
    )


def test_w82_verdicts_within_char_range():
    """100% of W82 baseline verdicts fall within 100-260 chars."""
    verdicts = _generate_30_verdicts()
    out_of_range = [(i, len(v), v[:80]) for i, v in enumerate(verdicts)
                    if not (100 <= len(v) <= 260)]
    assert out_of_range == [], (
        f"{len(out_of_range)}/30 verdicts outside 100-260 char range: "
        f"{out_of_range[:5]}"
    )


def test_w82_verdicts_unique_per_fixture():
    """Same (home, away, action) seed produces same variant — but 30 distinct
    fixtures should produce a high diversity of variants (no exact duplicates
    across the entire 30-card sample)."""
    verdicts = _generate_30_verdicts()
    # The MD5-deterministic variant selection should produce broad diversity.
    # Allow up to 6 exact duplicates (the verdict template pool is finite —
    # 26 distinct variants per Rule 14, with some collisions on similar seeds).
    dup_count = len(verdicts) - len(set(verdicts))
    assert dup_count <= 6, (
        f"Too many duplicate verdicts ({dup_count}/30) — variant pool may have "
        f"collapsed."
    )
