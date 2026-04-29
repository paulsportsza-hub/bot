"""FIX-NARRATIVE-ROT-ROOT-01 Phase 2 — unified pre-persist narrative validator.

Single canonical validator that every narrative_cache write MUST pass through
before persistence. Replaces the historical drift between polish-time
(`_validate_polish`), serve-time (`min_verdict_quality`), writer-level
(`_validate_baseline_setup`), and cache-read gates.

The premium-tier no-fallback chain (Rule 23) and writer-level W82 refusal
(Rule 24) remain in `_store_narrative_cache` and are NOT moved here — they
gate the source/tier combo BEFORE this validator runs. This validator scans
content quality given that the source is permitted.

Architecture
------------
The validator is a *reporter* — it never decides what to do with failures.
The CALLER (writer) applies tier-aware enforcement policy:

- Premium (Diamond/Gold) on CRITICAL or MAJOR → refuse write
  (log `FIX-NARRATIVE-ROT-ROOT-01 PremiumValidatorRefused`).
- Non-premium (Silver/Bronze) on CRITICAL → refuse write
  (log `BaselineValidatorRefused`).
- Non-premium on MAJOR → write with `quality_status='quarantined'`
  (log `BaselineQuarantined`).

This split keeps the validator pure (testable in isolation, idempotent) and
the caller simple (single decision tree based on the result).

Lazy imports
------------
`bot.py` imports this module at the top of `_store_narrative_cache` and the
verdict-cache writer. Importing `bot` here at module load would create a
circular import. Helpers are imported lazily inside `_validate_narrative_for_persistence`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

Severity = Literal["CRITICAL", "MAJOR", "MINOR"]


# FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-29) — AC-1.
# Rule 17 telemetry vocabulary recurrence catalogue, sourced verbatim from
# QA-01 §6.3 (banned-phrase recurrence — `the bookmaker has slipped` in 8/19
# cards) and QA-01 §6.4 (verdict telemetry leak in 58% of cards). These
# phrases read like a quant analyst's note, not a SA mate at a braai.
#
# Word-boundary, case-insensitive. Where a pattern has known false-positive
# risk in legitimate non-betting prose ("in view of the squad rotation"),
# the regex narrows to the surrounding quant-speak context.
TELEMETRY_VOCABULARY_PATTERNS: tuple[tuple[str, str], ...] = (
    # "the supporting signals back the read" / "the signals confirm" — Rule 17
    # leak across 58% of cards. Broad match: any "the [supporting] signal(s)"
    # phrase falls into the braai-voice forbidden zone (signals are quant-talk).
    (r"\bthe\s+(?:supporting\s+)?signals?\b", "the signals"),
    # "the reads" — quant analyst metonym for "the analysis". The braai-voice
    # equivalent is the team-level read ("Slot's lot are flying"), not "the reads".
    (r"\bthe\s+reads?\b", "the reads"),
    # "reads flag" / "reads flag stays in view" — the entire reads-flag idiom is
    # unintelligible to a normal user.
    (r"\breads?\s+flag\b", "reads flag"),
    # "the bookmaker has slipped" / "bookmaker slipped" — QA-01 §6.3 flagged
    # this exact phrase in 8/19 cards. The braai-voice version is concrete:
    # "Supabets hasn't moved yet — get on it before they catch up."
    (r"\bbookmaker\s+(?:has\s+)?slipp(?:ed|ing|s)\b", "bookmaker slipped"),
    # "stays in view" / "kept in view" / "remains in view" — narrow context
    # because the bare "\bin view\b" hits legitimate prose ("in view of the
    # squad rotation, ..."). The actual quant-speak usage anchors on a verb of
    # persistence (stays/keeps/remains/kept).
    (r"\b(?:stays?|kept|keeps?|remains?|stay)\s+in\s+view\b", "stays in view"),
    # "the case as it stands" / "the case here" — wooden mid-paragraph filler.
    (r"\bthe\s+case\s+(?:as\s+it\s+stands|here)\b", "the case as it stands"),
    # "the model estimates" / "model implies" / "model prices" — the model is
    # not a character in our story. SA Braai Voice talks about teams/managers,
    # not the model. Use "we make it" or omit entirely.
    (r"\b(?:the\s+)?model\s+(?:estimates|implies|prices?)\b", "the model estimates"),
    # "indicators line up" / "indicators align" — already in
    # _VERDICT_BANNED_TELEMETRY but mirrored here for cross-section enforcement
    # (ban applies to AI Breakdown sections too, not only the Verdict).
    (r"\bindicators?\s+(?:line\s+up|align)\b", "indicators line up"),
    # "structural signal" / "structural lean" / "structural read" — analyst-deck
    # vocabulary; never appears in pundit speech.
    (r"\bstructural\s+(?:signal|lean|read)\b", "structural signal"),
    # "price edge" — quant-speak. The braai-voice version names the price:
    # "Liverpool at 1.97 is too good" — not "the price edge here is +5.2%".
    (r"\bprice\s+edge\b", "price edge"),
    # "signal-aware" / "signal aware" — analyst slack-speak.
    (r"\bsignal[-\s]aware\b", "signal-aware"),
    # "edge confirms" / "edge confirm" — the edge isn't a witness.
    (r"\bedge\s+confirms?\b", "edge confirms"),
    # "speculative punt" — tone-band mismatch on Gold/Diamond Strong-band cards.
    # Allowed on Bronze (genuinely speculative tier) but never on premium.
    # The validator caller scopes this hit by tier.
    (r"\bspeculative\s+punt\b", "speculative punt"),
)

# Compiled regex cache — module-level so we compile once.
_TELEMETRY_VOCABULARY_RE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in TELEMETRY_VOCABULARY_PATTERNS
)

# Patterns that ONLY fire on premium-tier (Strong-band) cards. Allowed on
# Bronze (genuinely speculative tier) per brief AC-2 tier-band tone rule.
_PREMIUM_ONLY_TELEMETRY_LABELS: frozenset[str] = frozenset({"speculative punt"})


# FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 (2026-04-29) — AC-1.
#
# Strong-band tier (Diamond + Gold) MUST speak Strong-band confidence.
# Cautious-band vocabulary collapses the verdict tone on a Strong-band card
# (live failure case 29 Apr 19:24 SAST: Manchester City vs Brentford GOLD
# verdict at Supabets 1.36 read "the form picture is unclear and there's
# limited edge to work with here ... this is a cautious lean rather than a
# confident call"). The verdict-generator skill rubric says Strong-band
# Gold should sound like "Back Guardiola's City at 1.36 with Supabets —
# form solid, attack on song, Brentford bring nothing on the road."
#
# Three failure shapes the catalogue covers:
#   1. Cautious framing  — "cautious lean", "limited edge", "speculative punt"
#   2. Evidence-poor hedging — "form picture is unclear", "without recent form"
#   3. Hedging closers — "rather than a confident call", "monitor only"
#
# Tier-aware caller policy (in `_validate_narrative_for_persistence`):
#   - Diamond + Gold hit → CRITICAL (refuse write — synthesis-on-tap covers
#     the cache miss; pregen retries via Wave 2 chain).
#   - Silver hit → MAJOR (quarantine; some hedging is acceptable on Silver
#     but Strong-band cautious vocabulary is not).
#   - Bronze → ALLOWED (cautious-band IS Bronze's correct register —
#     the verdict-generator skill maps Bronze to MILD confidence).
STRONG_BAND_INCOMPATIBLE_PATTERNS: tuple[tuple[str, str], ...] = (
    # ── Cautious framing ────────────────────────────────────────────────────
    # "cautious lean", "cautious play", "cautious call", "cautious bet",
    # "cautious stake", "cautious approach", "cautious read", "cautiously lean".
    # Word-boundary so legitimate prose ("cautious about the line") doesn't fire.
    (r"\bcautious(?:ly)?\s+(?:lean|call|play|bet|stake|approach|read)\b",
     "cautious lean"),
    # "limited edge", "thin edge", "sparse edge", "weak edge", "minimal edge"
    # — all describe an absent edge, banned on Strong-band where the card
    # ALGORITHMICALLY HAS an edge (that's why it's Gold/Diamond).
    (r"\b(?:limited|thin|sparse|weak|minimal)\s+edge\b", "limited edge"),
    # "no edge to work with" — Bronze framing on a card the algorithm tagged
    # as Strong-band edge. If the model says Gold and the verdict says
    # "no edge", the card is internally contradictory.
    (r"\bno\s+edge\s+to\s+work\s+with\b", "no edge to work with"),
    # "form picture is unclear / murky / split / mixed" / "picture is unclear"
    # — Bronze-tier hedging on a Strong-band card. The form was the SIGNAL
    # used to rate this Gold; saying it's unclear is a tone collapse.
    (r"\b(?:form\s+)?picture\s+is\s+(?:unclear|murky|split|mixed)\b",
     "form picture is unclear"),
    # "rather than a confident call" / "rather than a strong call" — explicit
    # tier-band downgrade vocabulary. Verbatim from Paul's live failure case.
    (r"\brather\s+than\s+a\s+(?:confident|strong)\s+(?:call|play|bet)\b",
     "rather than a confident call"),
    # "speculative punt" — Bronze-only register; mirrors telemetry catalogue
    # but listed here so the AC-1 gate fires it on Strong-band tiers even when
    # Gate 8 misses (e.g. when the phrase is in narrative_html but Gate 8
    # already flagged a different telemetry hit and dedup short-circuits).
    (r"\bspeculative\s+(?:punt|stake|play|bet)\b", "speculative punt"),
    # "tiny exposure" / "small exposure only" — cautious-band sizing language
    # that signals tier mismatch. Strong-band uses "standard stake" or
    # "standard-to-heavy" sizing. The qualifier "only" or "just" is required
    # to avoid false positives in legitimate prose ("a small stake on this
    # one" can read fine on Silver — but "small exposure only" reads Bronze).
    (r"\btiny\s+exposure\b", "tiny exposure"),
    (r"\bsmall\s+(?:exposure|stake)\s+only\b", "small exposure only"),

    # ── Evidence-poor hedging ───────────────────────────────────────────────
    # "without recent form / context / h2h / head-to-head / data" — Bronze
    # framing that admits the analysis is data-poor. Strong-band cards have
    # data by construction (the algorithm needed it to rate the card Gold).
    (r"\bwithout\s+(?:recent\s+form|context|h2h|head[- ]to[- ]head|data)\b",
     "without recent form"),
    # "no recent form" / "little recent context" / "no recent h2h" — same
    # shape as above, different opener.
    (r"\b(?:no|little)\s+recent\s+(?:form|context|h2h)\b",
     "no recent form"),
    # "data is thin / sparse / limited / weak" — analysis-poor hedging.
    (r"\bdata\s+is\s+(?:thin|sparse|limited|weak)\b", "data is thin"),
    # "not enough to back" / "not enough to trust" / "not enough to recommend"
    # — explicit refusal-of-confidence language. Banned on Strong-band where
    # the verdict MUST recommend with action-verb conviction.
    (r"\bnot\s+enough\s+to\s+(?:back|trust|recommend)\b",
     "not enough to back"),

    # ── Hedging closers ─────────────────────────────────────────────────────
    # "lean rather than a confident call" / "read rather than a strong call"
    # — composite hedging closer. Already partially caught by "rather than a
    # confident call" above; this pattern catches the lean/read/call opener
    # variants for monitoring completeness.
    (r"\b(?:lean|read|call)\s+rather\s+than\s+a\s+(?:confident|strong)\s+(?:call|play|bet)\b",
     "lean rather than a confident call"),
    # "one to watch rather than back" — Bronze closer; banned on Strong-band
    # where the verdict MUST close with action ("get on", "back", "take").
    (r"\bone\s+to\s+watch\s+rather\s+than\s+back\b",
     "one to watch rather than back"),
    # "monitor only" — Bronze closer (correct register); on Strong-band reads
    # as a refusal to commit and is a tier-band collapse.
    (r"\bmonitor\s+only\b", "monitor only"),
)

_STRONG_BAND_INCOMPATIBLE_RE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in STRONG_BAND_INCOMPATIBLE_PATTERNS
)


# Hedging-conditional-opener detection (separate gate per brief AC-1).
#
# Rule: Strong-band verdicts MUST NOT have their first clause end with a
# comma followed by a hedging conjunction (but, however, though, although,
# yet). Catches the "City are the pick at 1.36, but the form picture is
# unclear..." shape verbatim from Paul's live failure case.
#
# Detection algorithm:
#   1. Strip HTML tags + leading whitespace.
#   2. Find the first comma in the text.
#   3. Check next 1-2 tokens (skip whitespace) against
#      {but, however, though, although, yet}.
#   4. If match → hedging-conditional opener detected.
#
# Strong-band cards open with confidence:
#   GOOD: "Back Guardiola's City at 1.36 with Supabets — form solid..."
#   BAD:  "City are the pick at 1.36, but the form picture is unclear..."
#
# The em-dash separator is allowed (it sets up evidence, not contradiction).
# A semicolon is also allowed (it joins independent clauses, not hedging).
_HEDGING_CONJUNCTIONS: frozenset[str] = frozenset({
    "but", "however", "though", "although", "yet",
})

# Strip HTML tags for plain-text comma scanning (the validator runs against
# narrative_html which carries <b>...</b> Setup/Edge/Risk/Verdict headers).
_HTML_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>")


def _check_hedging_conditional_opener(text: str) -> bool:
    """Return True iff the verdict opens with a hedging conditional clause.

    Detects the "X is the pick, but ..." shape that is verbatim from Paul's
    live Manchester City vs Brentford failure case (Apr 29 19:24 SAST).
    Strong-band tone collapses when the first clause concedes uncertainty
    via {but, however, though, although, yet} — the verdict-generator skill
    rubric requires confidence-led openings on Gold/Diamond.

    Parameters
    ----------
    text
        Raw verdict text (HTML-stripped internally). Empty string returns False.

    Returns
    -------
    bool
        True if the first comma is immediately followed by a hedging
        conjunction (skipping whitespace). False otherwise.
    """
    if not text:
        return False
    # Strip HTML tags so we don't count "<b>" as text.
    plain = _HTML_TAG_RE.sub("", text).strip()
    if not plain:
        return False
    # Scan for the first comma — anything before is the first clause.
    comma_idx = plain.find(",")
    if comma_idx == -1:
        return False
    # Take the chunk after the comma. Skip whitespace.
    tail = plain[comma_idx + 1:].lstrip()
    if not tail:
        return False
    # First token after the comma. Strip trailing punctuation.
    first_token = tail.split(maxsplit=1)[0].strip(",.;:!?\"'").lower()
    return first_token in _HEDGING_CONJUNCTIONS


def _check_tier_band_tone(
    text: str, edge_tier: str, section: str
) -> tuple[list[str], bool]:
    """Scan `text` for AC-1 Strong-band tone-lock violations.

    Two-component scan:
      - banned vocabulary (STRONG_BAND_INCOMPATIBLE_PATTERNS)
      - hedging-conditional opener (verdict-only)

    Parameters
    ----------
    text
        Raw HTML or plaintext to scan. Empty string returns ([], False).
    edge_tier
        Lowercase tier label ("diamond" | "gold" | "silver" | "bronze").
        Bronze hits are NOT returned (cautious-band IS Bronze's correct
        register per verdict-generator skill rubric).
    section
        Identifier for the surface being scanned. Hedging-conditional
        opener detection runs on the verdict surfaces only ("verdict" /
        "verdict_html"); banned-vocab scan runs on every section.

    Returns
    -------
    tuple[list[str], bool]
        (banned_vocab_hits, hedging_opener_detected). Empty list +
        False when text is clean OR tier is Bronze.
    """
    if not text:
        return [], False
    tier = (edge_tier or "").lower()
    # Bronze: cautious is the correct register — skip the entire scan.
    if tier == "bronze":
        return [], False
    hits: list[str] = []
    seen: set[str] = set()
    for compiled, label in _STRONG_BAND_INCOMPATIBLE_RE:
        if compiled.search(text) and label not in seen:
            hits.append(label)
            seen.add(label)
    # Hedging opener detection runs on verdict surfaces only — narrative_html
    # contains 4 sections and the comma-rule applies to the verdict's first
    # clause, not (e.g.) the second sentence of The Setup.
    hedging = False
    if section in ("verdict", "verdict_html"):
        hedging = _check_hedging_conditional_opener(text)
    return hits, hedging


def _check_telemetry_vocabulary(
    text: str, edge_tier: str, section: str
) -> list[str]:
    """Scan `text` for Rule 17 telemetry-vocabulary leaks.

    Parameters
    ----------
    text
        Raw HTML or plaintext to scan. Empty string returns no hits.
    edge_tier
        Lowercase tier label ("diamond" | "gold" | "silver" | "bronze"). Used
        to scope tier-conditional patterns (e.g. `speculative punt` is allowed
        on Bronze cards because they are genuinely speculative).
    section
        Identifier for the surface being scanned ("verdict_html" |
        "narrative_html" | "verdict" | "edge" | "risk" | "setup"). Currently
        informational — the regex catalogue is identical across sections; the
        caller decides which sections to scan.

    Returns
    -------
    list[str]
        Deduped list of hit labels (e.g. ["bookmaker slipped", "the reads"]).
        Empty list when text is clean.
    """
    if not text:
        return []
    tier = (edge_tier or "").lower()
    is_premium = tier in ("diamond", "gold")
    hits: list[str] = []
    seen: set[str] = set()
    for compiled, label in _TELEMETRY_VOCABULARY_RE:
        if label in _PREMIUM_ONLY_TELEMETRY_LABELS and not is_premium:
            continue
        if compiled.search(text) and label not in seen:
            hits.append(label)
            seen.add(label)
    return hits


@dataclass
class ValidationFailure:
    """Single gate hit produced by the unified validator.

    Attributes
    ----------
    gate
        Stable identifier for the failed check (e.g. ``"venue_leak"``,
        ``"setup_pricing_semantic"``). Used for log markers + monitoring.
    severity
        ``"CRITICAL"``, ``"MAJOR"`` or ``"MINOR"``. Caller policy is keyed on
        this. Premium-tier refuses both CRITICAL and MAJOR; non-premium
        refuses only CRITICAL.
    detail
        Human-readable description of the violation. Truncated to ~200 chars
        in log output.
    section
        Which narrative section the gate fired against:
        ``"setup" | "edge" | "risk" | "verdict" | "verdict_html" | "all"``.
        ``"all"`` means a full-document scan (BANNED_NARRATIVE_PHRASES).
    """

    gate: str
    severity: Severity
    detail: str
    section: str = ""


@dataclass
class ValidationResult:
    """Outcome of a single validator pass.

    Attributes
    ----------
    passed
        ``True`` iff there are zero CRITICAL and zero MAJOR failures.
        MINOR failures DO NOT mark the result as failed — they are
        informational only.
    failures
        Ordered list of every gate hit. Same gate may not fire twice with the
        same detail — callers should treat duplicates as a bug in the gate.
    severity
        Highest severity present (``"CRITICAL" > "MAJOR" > "MINOR"``) or
        ``None`` when ``failures`` is empty.
    """

    passed: bool
    failures: list[ValidationFailure] = field(default_factory=list)
    severity: Severity | None = None

    @property
    def critical_count(self) -> int:
        """Number of CRITICAL failures — used by the caller to short-circuit."""
        return sum(1 for f in self.failures if f.severity == "CRITICAL")

    @property
    def major_count(self) -> int:
        """Number of MAJOR failures — used by the caller for quarantine policy."""
        return sum(1 for f in self.failures if f.severity == "MAJOR")


# Sections recognised by the gate stack. ``verdict_html`` is the verdict-only
# surface (verdict-cache writes) — separate from ``verdict`` (the verdict
# section of a full narrative) so the validator can differentiate.
_SECTION_VERDICT_HTML = "verdict_html"
_SECTION_NARRATIVE = "all"


def _extract_setup_section(narrative_html: str) -> str:
    """Best-effort extraction of the Setup section from a narrative HTML block.

    Mirrors `bot._extract_setup_section`. Looks for the 📋 (Setup header)
    marker and returns text up to the next section marker (🎯 Edge, ⚠️ Risk,
    🏆 Verdict). Returns the full input on no marker (defensive: caller still
    runs strict-ban scan).
    """
    if not narrative_html:
        return ""
    setup_marker = "\U0001f4cb"  # 📋
    edge_marker = "\U0001f3af"  # 🎯
    risk_marker = "⚠️"  # ⚠️
    verdict_marker = "\U0001f3c6"  # 🏆
    setup_idx = narrative_html.find(setup_marker)
    if setup_idx == -1:
        return narrative_html
    rest = narrative_html[setup_idx:]
    # Find the next section header after Setup.
    next_idx = len(rest)
    for marker in (edge_marker, risk_marker, verdict_marker):
        idx = rest.find(marker, len(setup_marker))
        if idx != -1 and idx < next_idx:
            next_idx = idx
    return rest[:next_idx]


def _validate_narrative_for_persistence(
    content: dict[str, Any],
    evidence_pack: dict | None,
    edge_tier: str,
    source_label: str,
) -> ValidationResult:
    """Run the full pre-persist gate stack against narrative content.

    Parameters
    ----------
    content
        Required keys: ``narrative_html`` (str | None), ``verdict_html`` (str | None),
        ``match_id`` (str), ``narrative_source`` (str). Empty/None values for
        ``narrative_html`` and ``verdict_html`` are tolerated — the relevant
        gate stack is skipped for empty surfaces.
    evidence_pack
        Parsed evidence_json dict. May be ``None`` when the writer has no
        evidence pack (e.g. verdict-cache path). Manager + claim gates skip
        when this is None.
    edge_tier
        Edge tier ("diamond" | "gold" | "silver" | "bronze"). Currently
        informational — caller applies tier-aware policy. Validator behaviour
        is tier-agnostic.
    source_label
        Narrative source label ("w82" | "w84-haiku-fallback" | "verdict-cache"
        | etc.). Currently informational — used in log markers only.

    Returns
    -------
    ValidationResult
        Reports findings; never makes write decisions.

    Notes
    -----
    The validator is *idempotent* — calling twice with the same input
    produces structurally identical results (same gate ordering, same
    detail strings). This is asserted by the contract test suite.
    """
    failures: list[ValidationFailure] = []
    narrative_html = content.get("narrative_html") or ""
    verdict_html = content.get("verdict_html") or ""
    match_id = content.get("match_id", "")

    # Lazy imports — bot.py imports this module at the top of _store_narrative_cache.
    # Importing bot here at module load would create a cycle.
    try:
        from narrative_spec import (
            find_venue_leaks,
            min_verdict_quality,
        )
    except ImportError as exc:
        log.warning(
            "FIX-NARRATIVE-ROT-ROOT-01 ValidatorImportFailed match_id=%s err=%s — "
            "gate is no-op (returning passed=True to avoid blocking writes)",
            match_id, exc,
        )
        return ValidationResult(passed=True)

    # Phase 4 detectors — assume the agreed names; integration after Phase 4 lands.
    try:
        from narrative_spec import validate_manager_names_in_all_sections  # type: ignore[attr-defined]
    except ImportError:
        validate_manager_names_in_all_sections = None  # type: ignore[assignment]

    try:
        from narrative_spec import validate_claims_against_evidence  # type: ignore[attr-defined]
    except ImportError:
        validate_claims_against_evidence = None  # type: ignore[assignment]

    try:
        from bot import _find_setup_pricing_semantic_violations  # type: ignore[attr-defined]
    except ImportError:
        _find_setup_pricing_semantic_violations = None  # type: ignore[assignment]

    try:
        from bot import _find_setup_strict_ban_violations as _find_setup_strict_ban  # type: ignore[attr-defined]
    except ImportError:
        _find_setup_strict_ban = None  # type: ignore[assignment]

    try:
        from bot import BANNED_NARRATIVE_PHRASES  # type: ignore[attr-defined]
    except ImportError:
        BANNED_NARRATIVE_PHRASES = []  # type: ignore[assignment]

    # ── Gate 1: Venue leaks in narrative_html (LB-1 closure) ─────────────────
    # Scan the FULL narrative — find_venue_leaks does not differentiate sections,
    # which is desirable here (Anfield in Verdict is just as wrong as Anfield in Setup).
    if narrative_html:
        venues = find_venue_leaks(narrative_html)
        if venues:
            failures.append(
                ValidationFailure(
                    gate="venue_leak",
                    severity="CRITICAL",
                    detail=f"venues={venues!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVenueLeak match_id=%s "
                "source=%s venues=%r",
                match_id, source_label, venues,
            )

    # ── Gate 2: Setup-section pricing leaks (LB-4 closure) ──────────────────
    # Two detectors: existing strict-ban (token + decimal + integer-prob) and the
    # Phase 4 semantic detector for "Elo-implied 70%" / "84% to win" patterns.
    if narrative_html:
        if _find_setup_strict_ban is not None:
            try:
                strict_reasons = _find_setup_strict_ban(narrative_html)
            except Exception as exc:
                strict_reasons = []
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorStrictBanFailed "
                    "match_id=%s err=%s",
                    match_id, exc,
                )
            if strict_reasons:
                failures.append(
                    ValidationFailure(
                        gate="setup_pricing",
                        severity="CRITICAL",
                        detail=f"reasons={strict_reasons!r}",
                        section="setup",
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorSetupPricingStrict "
                    "match_id=%s source=%s reasons=%r",
                    match_id, source_label, strict_reasons,
                )

        if _find_setup_pricing_semantic_violations is not None:
            try:
                semantic_reasons = _find_setup_pricing_semantic_violations(narrative_html)
            except Exception as exc:
                semantic_reasons = []
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorSetupSemanticFailed "
                    "match_id=%s err=%s",
                    match_id, exc,
                )
            if semantic_reasons:
                failures.append(
                    ValidationFailure(
                        gate="setup_pricing_semantic",
                        severity="CRITICAL",
                        detail=f"reasons={semantic_reasons!r}",
                        section="setup",
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorSetupPricingSemantic "
                    "match_id=%s source=%s reasons=%r",
                    match_id, source_label, semantic_reasons,
                )

    # ── Gate 3: Manager hallucination across all sections (LB-2/LB-3) ───────
    if narrative_html and evidence_pack is not None and validate_manager_names_in_all_sections is not None:
        try:
            mgr_violations = validate_manager_names_in_all_sections(
                narrative_html, evidence_pack
            )
        except Exception as exc:
            mgr_violations = []
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorManagerCheckFailed "
                "match_id=%s err=%s",
                match_id, exc,
            )
        if mgr_violations:
            # Phase 4 returns a list of `ManagerViolation` namedtuples — the
            # detail string is `"<count> hallucinated managers: <names>"`.
            try:
                names = [getattr(v, "name", str(v)) for v in mgr_violations]
            except Exception:
                names = [str(mgr_violations)]
            failures.append(
                ValidationFailure(
                    gate="manager_hallucination",
                    severity="CRITICAL",
                    detail=f"names={names!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorManagerHallucination "
                "match_id=%s source=%s names=%r",
                match_id, source_label, names,
            )

    # ── Gate 4: Claim verification against evidence (LB-5 / LB-B5) ──────────
    if narrative_html and evidence_pack is not None and validate_claims_against_evidence is not None:
        try:
            claim_violations = validate_claims_against_evidence(
                narrative_html, evidence_pack
            )
        except Exception as exc:
            claim_violations = []
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorClaimCheckFailed "
                "match_id=%s err=%s",
                match_id, exc,
            )
        # Phase 4 returns ClaimViolation namedtuples with a `kind` attribute.
        # H2H fabrications are CRITICAL (LB-5); form/record mismatches are MAJOR (LB-B5).
        h2h_violations = []
        evidence_violations = []
        for v in claim_violations or []:
            kind = (getattr(v, "kind", "") or "").lower()
            if "h2h" in kind:
                h2h_violations.append(v)
            else:
                evidence_violations.append(v)
        if h2h_violations:
            details = [getattr(v, "claim", str(v)) for v in h2h_violations]
            failures.append(
                ValidationFailure(
                    gate="claim_h2h_fabricated",
                    severity="CRITICAL",
                    detail=f"claims={details!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorClaimH2HFabricated "
                "match_id=%s source=%s claims=%r",
                match_id, source_label, details,
            )
        if evidence_violations:
            details = [getattr(v, "claim", str(v)) for v in evidence_violations]
            failures.append(
                ValidationFailure(
                    gate="claim_evidence_mismatch",
                    severity="MAJOR",
                    detail=f"claims={details!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorClaimEvidenceMismatch "
                "match_id=%s source=%s claims=%r",
                match_id, source_label, details,
            )

    # ── Gate 5: Verdict quality floor ───────────────────────────────────────
    if verdict_html:
        try:
            verdict_ok = min_verdict_quality(
                verdict_html, tier=edge_tier, evidence_pack=evidence_pack
            )
        except Exception as exc:
            verdict_ok = True
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVerdictQualityFailed "
                "match_id=%s err=%s",
                match_id, exc,
            )
        if not verdict_ok:
            failures.append(
                ValidationFailure(
                    gate="verdict_quality",
                    severity="MAJOR",
                    detail=f"len={len(verdict_html)} sample={verdict_html[:80]!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVerdictQualityFail "
                "match_id=%s source=%s tier=%s len=%d sample=%r",
                match_id, source_label, edge_tier, len(verdict_html),
                verdict_html[:80],
            )

    # ── Gate 6: Venue leaks in verdict_html (explicit) ──────────────────────
    # min_verdict_quality already scans for venues but only reports a bool.
    # Surface the explicit leak so the caller log carries the venue names.
    if verdict_html:
        verdict_venues = find_venue_leaks(verdict_html)
        if verdict_venues:
            # Don't double-fail if Gate 1 already caught it via narrative_html.
            already_failed = any(
                f.gate == "venue_leak" and "verdict" not in f.detail.lower()
                for f in failures
            )
            if not already_failed:
                failures.append(
                    ValidationFailure(
                        gate="venue_leak",
                        severity="CRITICAL",
                        detail=f"verdict venues={verdict_venues!r}",
                        section=_SECTION_VERDICT_HTML,
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVerdictVenueLeak "
                    "match_id=%s source=%s venues=%r",
                    match_id, source_label, verdict_venues,
                )

    # ── Gate 7: BANNED_NARRATIVE_PHRASES across narrative + verdict ─────────
    if BANNED_NARRATIVE_PHRASES:
        combined = (narrative_html or "") + " " + (verdict_html or "")
        combined_lower = combined.lower()
        hits = [p for p in BANNED_NARRATIVE_PHRASES if p.lower() in combined_lower]
        if hits:
            failures.append(
                ValidationFailure(
                    gate="banned_phrase",
                    severity="MAJOR",
                    detail=f"hits={hits[:5]!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorBannedPhrase "
                "match_id=%s source=%s hits=%r",
                match_id, source_label, hits[:5],
            )

    # ── Gate 8: Rule 17 telemetry vocabulary scan ───────────────────────────
    # FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-29) AC-1.
    # Scan BOTH verdict_html and narrative_html for telemetry vocabulary leaks.
    # Premium tier (Diamond/Gold) hit → CRITICAL (refuse write).
    # Non-premium tier hit → MAJOR (quarantine).
    tier_lower = (edge_tier or "").lower()
    tele_severity: Severity = "CRITICAL" if tier_lower in ("diamond", "gold") else "MAJOR"
    if narrative_html:
        narr_tele_hits = _check_telemetry_vocabulary(
            narrative_html, edge_tier, "narrative_html"
        )
        if narr_tele_hits:
            failures.append(
                ValidationFailure(
                    gate="telemetry_vocabulary",
                    severity=tele_severity,
                    detail=f"hits={narr_tele_hits!r}",
                    section="narrative_html",
                )
            )
            log.warning(
                "FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 ValidatorTelemetryVocab "
                "match_id=%s source=%s tier=%s section=narrative hits=%r",
                match_id, source_label, edge_tier, narr_tele_hits,
            )
    if verdict_html:
        v_tele_hits = _check_telemetry_vocabulary(
            verdict_html, edge_tier, "verdict_html"
        )
        if v_tele_hits:
            failures.append(
                ValidationFailure(
                    gate="telemetry_vocabulary",
                    severity=tele_severity,
                    detail=f"verdict hits={v_tele_hits!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 ValidatorTelemetryVocab "
                "match_id=%s source=%s tier=%s section=verdict_html hits=%r",
                match_id, source_label, edge_tier, v_tele_hits,
            )

    # ── Gate 9: Strong-band tone lock (FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01) ─
    # Brief AC-1: Strong-band tier (Diamond + Gold) MUST speak Strong-band
    # confidence. Cautious-band vocabulary collapses the verdict tone on a
    # Strong-band card (live failure case 29 Apr 19:24 SAST).
    #
    # Tier-aware enforcement matrix (per brief AC-1):
    #   - Diamond + Gold → CRITICAL (refuse write — synthesis-on-tap covers
    #     the cache miss; Wave 2 Sonnet retry → Haiku → defer chain still
    #     applies via the existing pregen flow).
    #   - Silver → MAJOR (quarantine; some hedging is acceptable on Silver
    #     but Strong-band cautious vocabulary is not — quarantined rows can
    #     still be served via the read surface but are flagged for repolish).
    #   - Bronze → ALLOWED (cautious-band IS Bronze's correct register;
    #     `_check_tier_band_tone` skips the scan entirely when tier=bronze).
    if tier_lower in ("diamond", "gold", "silver"):
        # Strong-band severity: Diamond/Gold = CRITICAL; Silver = MAJOR.
        # Bronze short-circuits inside `_check_tier_band_tone` (returns
        # empty hits + False hedging).
        sb_severity: Severity = "CRITICAL" if tier_lower in ("diamond", "gold") else "MAJOR"
        # Verdict scan runs against verdict_html (when present) AND the
        # narrative-embedded verdict section. The narrative_html scan also
        # picks up violations in The Setup / The Edge / The Risk where
        # cautious-band vocabulary leaks (e.g. "the form picture is unclear"
        # in The Setup of a Gold card).
        if narrative_html:
            narr_sb_hits, _narr_hedging = _check_tier_band_tone(
                narrative_html, edge_tier, "narrative_html"
            )
            if narr_sb_hits:
                failures.append(
                    ValidationFailure(
                        gate="strong_band_tone",
                        severity=sb_severity,
                        detail=f"hits={narr_sb_hits!r}",
                        section="narrative_html",
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 ValidatorStrongBandTone "
                    "match_id=%s source=%s tier=%s section=narrative hits=%r",
                    match_id, source_label, edge_tier, narr_sb_hits,
                )
        if verdict_html:
            v_sb_hits, v_hedging = _check_tier_band_tone(
                verdict_html, edge_tier, "verdict_html"
            )
            if v_sb_hits:
                failures.append(
                    ValidationFailure(
                        gate="strong_band_tone",
                        severity=sb_severity,
                        detail=f"verdict hits={v_sb_hits!r}",
                        section=_SECTION_VERDICT_HTML,
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 ValidatorStrongBandTone "
                    "match_id=%s source=%s tier=%s section=verdict_html hits=%r",
                    match_id, source_label, edge_tier, v_sb_hits,
                )
            # Hedging-conditional opener fires on Strong-band verdict only.
            # Silver allows mild hedging (lean tone band) so we scope the
            # opener gate to Diamond + Gold per brief AC-1.
            if v_hedging and tier_lower in ("diamond", "gold"):
                failures.append(
                    ValidationFailure(
                        gate="strong_band_hedging_opener",
                        severity="CRITICAL",
                        detail=f"first_clause hedging conditional opener; sample={verdict_html[:100]!r}",
                        section=_SECTION_VERDICT_HTML,
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 ValidatorStrongBandHedgingOpener "
                    "match_id=%s source=%s tier=%s sample=%r",
                    match_id, source_label, edge_tier, verdict_html[:100],
                )

    # ── Outcome ──────────────────────────────────────────────────────────────
    crit = [f for f in failures if f.severity == "CRITICAL"]
    major = [f for f in failures if f.severity == "MAJOR"]
    if crit:
        sev: Severity | None = "CRITICAL"
    elif major:
        sev = "MAJOR"
    elif failures:
        sev = "MINOR"
    else:
        sev = None
    return ValidationResult(
        passed=(len(crit) == 0 and len(major) == 0),
        failures=failures,
        severity=sev,
    )
