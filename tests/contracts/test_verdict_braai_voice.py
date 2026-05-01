
import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

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
    """Match-preview branch carries the ⛔ BRAAI VOICE marker + AC-1 examples.

    FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1
    rewrote the static block to verdict-only with 3 new GOOD examples
    (Slot/Anfield, Guardiola/Etihad, Pereira/Forest) + 3 new BAD examples
    (data has a cleaner read, is the lean, Standard stake on X. Back X.).
    """
    from evidence_pack import format_evidence_prompt

    pack = _patched_evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=True)
    assert isinstance(prompt, str)
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" in prompt
    # 3 BAD examples from AC-1.
    assert "data has a cleaner read on X" in prompt
    assert "is the lean" in prompt
    assert "Standard stake on X. Back X." in prompt
    # 3 GOOD examples from AC-1.
    assert "Slot's Reds at home in front of Anfield" in prompt
    assert "Guardiola's Sky Blues at the Etihad" in prompt
    assert "Pereira's Forest at the City Ground" in prompt


def test_prompt_contains_braai_voice_block_edge_branch(_patched_evidence_pack):
    """Edge branch carries the same braai voice marker + AC-1 examples."""
    from evidence_pack import format_evidence_prompt

    pack = _patched_evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert isinstance(prompt, str)
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE" in prompt
    assert "data has a cleaner read on X" in prompt
    assert "Slot's Reds at home in front of Anfield" in prompt


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
    """FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1:
    the action-close instruction lists the 9 imperatives verbatim
    (Back / Bet on / Put your money on / Get on / Take / Lean on / Ride /
    Hammer it on / Smash)."""
    from evidence_pack import format_evidence_prompt

    pack = _patched_evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert "CLOSE WITH ACTION" in prompt
    for imperative in (
        "Back",
        "Bet on",
        "Put your money on",
        "Get on",
        "Take",
        "Lean on",
        "Ride",
        "Hammer it on",
        "Smash",
    ):
        assert imperative in prompt, (
            f"imperative '{imperative}' missing from action-close cluster"
        )


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


# ── FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 AC-3 — tier-band tone audit ─────────
#
# Brief AC-3: Gold/Diamond W82 verdicts → 0 cautious-band vocabulary hits;
# Bronze W82 verdicts → cautious-band ALLOWED. Confirms the W82 baseline
# templates emit voice consistent with the tier badge.

# Mirror of `narrative_validator.STRONG_BAND_INCOMPATIBLE_PATTERNS` — kept here
# as a regex-only catalogue so the test is independent of the validator's
# tier-aware short-circuit (the helper skips Bronze; we want to scan ALL tiers
# and assert tier-conditional absence).
_STRONG_BAND_BANNED_RE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # Cautious framing
        r"\bcautious(?:ly)?\s+(?:lean|call|play|bet|stake|approach|read)\b",
        r"\b(?:limited|thin|sparse|weak|minimal)\s+edge\b",
        r"\bno\s+edge\s+to\s+work\s+with\b",
        r"\b(?:form\s+)?picture\s+is\s+(?:unclear|murky|split|mixed)\b",
        r"\brather\s+than\s+a\s+(?:confident|strong)\s+(?:call|play|bet)\b",
        r"\bspeculative\s+(?:punt|stake|play|bet)\b",
        r"\btiny\s+exposure\b",
        r"\bsmall\s+(?:exposure|stake)\s+only\b",
        # Evidence-poor hedging
        r"\bwithout\s+(?:recent\s+form|context|h2h|head[- ]to[- ]head|data)\b",
        r"\b(?:no|little)\s+recent\s+(?:form|context|h2h)\b",
        r"\bdata\s+is\s+(?:thin|sparse|limited|weak)\b",
        r"\bnot\s+enough\s+to\s+(?:back|trust|recommend)\b",
        # Hedging closers
        r"\b(?:lean|read|call)\s+rather\s+than\s+a\s+(?:confident|strong)\s+(?:call|play|bet)\b",
        r"\bone\s+to\s+watch\s+rather\s+than\s+back\b",
        r"\bmonitor\s+only\b",
    )
)


def _has_strong_band_banned_vocab(text: str) -> list[str]:
    """Return labels of every Strong-band banned phrase that fires on `text`."""
    hits: list[str] = []
    for compiled in _STRONG_BAND_BANNED_RE:
        m = compiled.search(text)
        if m:
            hits.append(m.group(0).lower())
    return hits


def test_strong_band_w82_verdicts_zero_cautious_band_vocab():
    """30 Gold/Diamond W82 verdicts contain ZERO cautious-band vocabulary.

    Brief AC-3: Strong-band verdict templates use ONLY Strong-band vocabulary.
    Bronze register words (cautious lean, limited edge, form picture unclear,
    rather than a confident call, speculative punt, tiny exposure, small
    exposure only, without recent form, data is thin, monitor only, etc.)
    NEVER appear on a Gold or Diamond card by construction.

    Generates 30 fixtures: 4 Diamond + 8 Gold (= 12 Strong-band) replicated
    plus the existing fixture set, scanned with the AC-1 catalogue.
    """
    verdicts = _generate_30_verdicts()
    # Index 0-3 = Diamond, 4-11 = Gold (per _generate_30_verdicts ordering).
    strong_band_verdicts = verdicts[:12]
    leaks = []
    for i, v in enumerate(strong_band_verdicts):
        hits = _has_strong_band_banned_vocab(v)
        if hits:
            leaks.append((i, hits, v[:120]))
    assert leaks == [], (
        f"Strong-band W82 verdicts MUST NOT contain cautious-band vocabulary. "
        f"Leaks in {len(leaks)}/12 verdicts: {leaks!r}"
    )


def test_silver_w82_verdicts_zero_cautious_band_vocab():
    """Silver W82 verdicts ALSO contain zero Strong-band-incompatible vocab.

    Per validator caller policy, Silver hits raise MAJOR (quarantine). The W82
    templates should preempt this by producing clean Silver text — Silver is
    `lean` action which uses `_lean_variants`. None of those variants reference
    cautious-band language by construction.
    """
    verdicts = _generate_30_verdicts()
    # Index 12-20 = Silver (per _generate_30_verdicts ordering).
    silver_verdicts = verdicts[12:21]
    leaks = []
    for i, v in enumerate(silver_verdicts):
        hits = _has_strong_band_banned_vocab(v)
        if hits:
            leaks.append((i, hits, v[:120]))
    assert leaks == [], (
        f"Silver W82 verdicts MUST NOT contain Strong-band-incompatible vocab "
        f"(quarantine trigger at writer level). Leaks: {leaks!r}"
    )


def test_bronze_w82_speculative_punt_uses_cautious_register():
    """Bronze speculative_punt W82 verdicts use cautious-band vocabulary.

    Brief AC-3 says Bronze cautious-band IS ALLOWED. The W82 Bronze
    speculative_punt templates exist for genuinely cautious cards and use
    register-appropriate language ("speculative punt", "small exposure",
    "no hero call") — banned on Strong-band tiers but correct on Bronze.

    Generates 4 Bronze fixtures forced into the `speculative punt` branch
    (verdict_action="speculative punt") to exercise the cautious vocab
    templates. Confirms the templates do contain Bronze register words.
    """
    bronze_specpunt_fixtures = [
        ("burnley", "luton", "EPL", "soccer", 3.50, 1.5, 1),
        ("leicester", "leeds", "EPL", "soccer", 2.95, 1.2, 0),
        ("rangers_fc", "celtic", "Scottish Premiership", "soccer", 4.50, 1.0, 0),
        ("cape_town_city", "stellenbosch", "PSL", "soccer", 3.10, 1.1, 1),
    ]
    bronze_verdicts: list[str] = []
    for home, away, comp, sport, odds, ev, confirming in bronze_specpunt_fixtures:
        spec = NarrativeSpec(
            sport=sport,
            competition=comp,
            home_name=home.replace("_", " ").title(),
            away_name=away.replace("_", " ").title(),
            home_story_type="momentum",
            away_story_type="setback",
            home_form="WLLLW",
            away_form="LWLLW",
            outcome="home",
            outcome_label=home.replace("_", " ").title(),
            odds=odds,
            bookmaker="Hollywoodbets",
            ev_pct=ev,
            fair_prob_pct=35.0,
            support_level=confirming,
            contradicting_signals=0,
            evidence_class="speculative",
            tone_band="cautious",
            verdict_action="speculative punt",  # Force the cautious branch.
            verdict_sizing="tiny exposure",
            edge_tier="bronze",
        )
        bronze_verdicts.append(_render_verdict(spec))

    # Sanity: verdicts generated.
    assert len(bronze_verdicts) == 4
    # The Bronze speculative_punt branch uses words like "punt", "small
    # exposure" / "no hero call" — let's confirm at least 2/4 fire on
    # Strong-band catalogue (since Bronze allows them, this proves the
    # cautious register is in use).
    bronze_with_register = [
        v for v in bronze_verdicts if _has_strong_band_banned_vocab(v)
    ]
    assert len(bronze_with_register) >= 2, (
        f"Bronze speculative_punt expected ≥2/4 verdicts using cautious-band "
        f"register; got {len(bronze_with_register)}/4: "
        f"{[v[:120] for v in bronze_verdicts]!r}"
    )

    # And confirm the validator helper accepts these Bronze cards (key AC-1
    # tier-aware enforcement: Bronze tier short-circuits, returning empty hits).
    from narrative_validator import _check_tier_band_tone

    for v in bronze_verdicts:
        hits, _hedging = _check_tier_band_tone(v, "bronze", "verdict_html")
        assert hits == [], (
            f"Bronze tier MUST be ALLOWED to use cautious-band vocabulary. "
            f"Validator flagged hits {hits!r} on text {v[:100]!r}"
        )


def test_strong_band_w82_verdicts_no_hedging_conditional_openers():
    """Diamond/Gold W82 verdicts MUST NOT open with hedging conditional clauses.

    Brief AC-1: "Strong-band verdicts MUST NOT have their first clause end
    with a comma followed by a hedging conjunction (but, however, though,
    although, yet)."

    The W82 holistic verdict templates compose the verdict in a single coherent
    voice — no "X is the pick, but Y is uncertain" shape. This test asserts
    that the templates themselves never produce that shape.
    """
    from narrative_validator import _check_hedging_conditional_opener

    verdicts = _generate_30_verdicts()
    strong_band_verdicts = verdicts[:12]  # Diamond + Gold
    hedging_hits = [
        (i, v[:120]) for i, v in enumerate(strong_band_verdicts)
        if _check_hedging_conditional_opener(v)
    ]
    assert hedging_hits == [], (
        f"Strong-band W82 verdicts MUST NOT open with hedging conditional "
        f"clauses (comma + but/however/though/although/yet). Hits: {hedging_hits!r}"
    )
