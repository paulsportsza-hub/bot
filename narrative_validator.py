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


# FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 (2026-04-29) — AC-1.
#
# Verdict closure rule: the LAST sentence of verdict_html MUST close with an
# ACTUAL verdict. Live failure case (Liverpool vs Chelsea, Gold, 1.97 Supabets,
# 29 Apr 2026 ~20:25 SAST):
#   "What stands out: Slot's Reds have picked up two wins in their last three,
#    while Chelsea are in terrible form with five losses from their last five."
# Reads like a Setup observation. Validator passed it because tier-band tone is
# fine, no telemetry vocab, no banned phrases — but it never tells the user to
# back anyone. Closure-rule gate catches this structurally.
#
# Three components in the closing sentence:
#   1. Action verb from the cluster (case-insensitive, word-boundary).
#   2. Team / selection name (matches evidence_pack home/away OR betting selection).
#   3. Odds shape (decimal OR fraction OR American).
#
# Tier-aware enforcement (caller policy):
#   - Diamond + Gold (Strong-band): all 3 → PASS. Missing ANY → CRITICAL.
#   - Silver: action verb required; team OR odds optional but at least one.
#     Missing both → CRITICAL.
#   - Bronze: action verb required; team / odds optional.
#     Missing action verb → CRITICAL.
_VERDICT_ACTION_VERBS: tuple[str, ...] = (
    # Locked from brief AC-1; SA Braai voice + verdict-generator skill rubric.
    r"back",
    r"take",
    r"bet\s+on",
    r"get\s+on",
    r"put\s+(?:your\s+)?money\s+on",
    r"hammer\s+it(?:\s+on)?",
    r"get\s+behind",
    r"lean\s+on",
    r"ride",
    r"smash",
)
# FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 (2026-04-29) — AC-3.
# Declarative recommendation phrases. The brief broadens the action-verb cluster
# so the closing sentence can carry either an imperative ("Back Liverpool at
# 1.97 with Supabets") or a declarative recommendation ("Liverpool at 1.97
# is the pick — Supabets, measured stake"). Both shapes carry the same SA
# Braai voice intent — recommending a bet — without forcing the imperative-
# only frame on the W82 baseline templates.
_VERDICT_DECLARATIVE_PHRASES: tuple[str, ...] = (
    r"is\s+the\s+pick",
    r"is\s+the\s+play",
    r"is\s+the\s+call",
    r"is\s+the\s+lean",
    r"is\s+the\s+bet",
    r"is\s+the\s+value",
)
_VERDICT_ACTION_RE: re.Pattern[str] = re.compile(
    r"\b(?:" + "|".join(_VERDICT_ACTION_VERBS) + r")\b"
    r"|\b(?:" + "|".join(_VERDICT_DECLARATIVE_PHRASES) + r")\b",
    re.IGNORECASE,
)

# Odds shape: decimal (1.36-99.99), fraction (1/2, 11/10, 100/1), American (+150/-200).
# Decimal range narrows to plausible betting odds; rejects "5.0" alone and "12.5 goals".
_VERDICT_ODDS_RE: re.Pattern[str] = re.compile(
    r"(?:"
    r"\b[1-9]\d?\.\d{2}\b"  # decimal: 1.36, 1.97, 12.50
    r"|"
    r"\b\d+/\d+\b"  # fraction: 11/10, 100/1
    r"|"
    r"(?:^|\s)[+-]\d{2,4}\b"  # American: +150, -200, +1000
    r")"
)

# Selection-name vocabulary: betting-market keywords that count as a "selection"
# even when the team name is absent. The brief's PASS example includes
# "BTTS", "over X.5", "draw" etc.
_VERDICT_SELECTION_KEYWORDS: tuple[str, ...] = (
    r"home\s+win",
    r"away\s+win",
    r"draw",
    r"over\s+\d+(?:\.\d+)?",
    r"under\s+\d+(?:\.\d+)?",
    r"btts",
    r"both\s+teams\s+to\s+score",
    r"clean\s+sheet",
    r"asian\s+handicap",
    r"handicap",
    r"to\s+win",
    r"to\s+score",
    r"first\s+goalscorer",
    r"correct\s+score",
    r"double\s+chance",
    r"draw\s+no\s+bet",
)
_VERDICT_SELECTION_RE: re.Pattern[str] = re.compile(
    r"\b(?:" + "|".join(_VERDICT_SELECTION_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _last_sentence(text: str) -> str:
    """Return the last non-empty sentence from `text` after HTML strip.

    Tokenisation: split on ``[.!?]\\s+`` (sentence terminators followed by
    whitespace), take the last non-empty segment. Trailing punctuation is
    stripped. Empty input returns empty string.
    """
    if not text:
        return ""
    plain = _HTML_TAG_RE.sub("", text).strip()
    if not plain:
        return ""
    # Split on sentence terminator + whitespace. Trailing terminator (no
    # whitespace after) leaves an empty trailing segment which we filter out.
    parts = re.split(r"[.!?]\s+", plain)
    # Filter empties and strip trailing terminators on the final part.
    nonempty = [p.strip() for p in parts if p and p.strip()]
    if not nonempty:
        return ""
    last = nonempty[-1]
    # Strip trailing punctuation . ! ? ; , and similar.
    return last.rstrip(" \t.!?;,…—–-").strip()


def _verdict_closure_components(
    verdict_text: str,
    home_team: str = "",
    away_team: str = "",
) -> tuple[bool, bool, bool]:
    """Return (has_action, has_team_or_selection, has_odds) for closing sentence.

    Parameters
    ----------
    verdict_text
        Raw verdict HTML or plaintext. The function strips HTML tags and
        tokenises on [.!?]\\s+ to find the closing sentence.
    home_team
        Home team display name from evidence_pack. Used for the team check.
        Empty string disables team-name match (selection keywords still count).
    away_team
        Away team display name from evidence_pack. Same semantics as home_team.

    Returns
    -------
    tuple[bool, bool, bool]
        - has_action: an action verb from `_VERDICT_ACTION_VERBS` is present
        - has_team_or_selection: home/away name OR a betting-selection keyword
          is present
        - has_odds: an odds shape (decimal/fraction/American) is present

    Notes
    -----
    The closing-sentence tokenisation matches the brief's specification:
    "split verdict_html on `[.!?]\\s+`, take last non-empty segment as the
    closing sentence. Strip trailing punctuation."
    """
    last = _last_sentence(verdict_text)
    if not last:
        return (False, False, False)
    has_action = bool(_VERDICT_ACTION_RE.search(last))
    has_odds = bool(_VERDICT_ODDS_RE.search(last))

    # Team match: case-insensitive substring of home/away name in the closing
    # sentence. Single-word names (e.g. "Liverpool") use word-boundary; multi-
    # word names (e.g. "Manchester City") use plain substring (word-boundary
    # between two capitalised words is order-of-magnitude equivalent).
    last_lower = last.lower()
    team_hit = False
    for raw in (home_team, away_team):
        name = (raw or "").strip().lower()
        if not name:
            continue
        # Word-boundary if single token, plain substring otherwise.
        if " " in name:
            if name in last_lower:
                team_hit = True
                break
        else:
            if re.search(r"\b" + re.escape(name) + r"\b", last_lower):
                team_hit = True
                break

    selection_hit = bool(_VERDICT_SELECTION_RE.search(last))
    has_team_or_selection = team_hit or selection_hit
    return (has_action, has_team_or_selection, has_odds)


def _check_verdict_closure_rule(
    verdict_html: str,
    edge_tier: str,
    evidence_pack: dict | None,
) -> tuple[Severity | None, str]:
    """Apply tier-aware closure-rule enforcement to verdict_html.

    Parameters
    ----------
    verdict_html
        The verdict surface to scan. Empty string returns ``(None, "")``.
    edge_tier
        Lowercase tier label. Diamond + Gold require all 3 components; Silver
        requires action verb plus at least one of (team, odds); Bronze
        requires action verb only.
    evidence_pack
        Optional evidence dict. Reads ``home_team`` and ``away_team`` for the
        team-name match. ``None`` skips the team check (selection keywords
        still count via _VERDICT_SELECTION_KEYWORDS).

    Returns
    -------
    tuple[Severity | None, str]
        ``(None, "")`` when the verdict closes correctly for its tier.
        ``("CRITICAL", reason)`` when the closing sentence fails the tier rule.
        Reason is a short human-readable string e.g.
        ``"Strong-band missing odds in closing sentence: '...'"``.
    """
    if not verdict_html:
        return (None, "")
    tier = (edge_tier or "").lower()
    home_team = ""
    away_team = ""
    if isinstance(evidence_pack, dict):
        home_team = str(evidence_pack.get("home_team") or "").strip()
        away_team = str(evidence_pack.get("away_team") or "").strip()
    has_action, has_team, has_odds = _verdict_closure_components(
        verdict_html, home_team, away_team,
    )
    last = _last_sentence(verdict_html)
    sample = last[:120] if last else ""

    # Strong-band: all 3 required.
    if tier in ("diamond", "gold"):
        missing: list[str] = []
        if not has_action:
            missing.append("action_verb")
        if not has_team:
            missing.append("team_or_selection")
        if not has_odds:
            missing.append("odds_shape")
        if missing:
            return (
                "CRITICAL",
                f"Strong-band ({tier}) closing sentence missing "
                f"{','.join(missing)}; sample={sample!r}",
            )
        return (None, "")

    # Silver: action verb required; team OR odds optional but at least one.
    if tier == "silver":
        if not has_action:
            return (
                "CRITICAL",
                f"Silver closing sentence missing action_verb; "
                f"sample={sample!r}",
            )
        if not (has_team or has_odds):
            return (
                "CRITICAL",
                f"Silver closing sentence missing both team_or_selection "
                f"and odds_shape; sample={sample!r}",
            )
        return (None, "")

    # Bronze: action verb required.
    if tier == "bronze":
        if not has_action:
            return (
                "CRITICAL",
                f"Bronze closing sentence missing action_verb; "
                f"sample={sample!r}",
            )
        return (None, "")

    # Unknown tier — be permissive (do not block writes from non-standard tiers).
    return (None, "")


# FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 (2026-04-29) — AC-2.
#
# Vague-content pattern ban. Live failure case 2 (Manchester United vs
# Liverpool, Gold, 2.38 Supabets, 29 Apr 2026 ~20:25 SAST): the AI Breakdown
# read like an empty-calorie market summary — "looks like the sort of league
# fixture that takes shape once one side settles into its preferred tempo",
# "the play is live without being loud", "Risk reads clean here. The model and
# standard match volatility are the only live variables."  Individual phrases
# pass the tier-band-tone gates and the telemetry-vocabulary gate, but the
# CONTENT is vague and generic. Subscription-grade premium feature shipping
# subscription-not-grade output.
#
# Tier policy (caller):
#   - Diamond + Gold hit → CRITICAL (refuse write — Wave 2 Sonnet retry → Haiku
#     → defer chain still applies via the existing pregen flow).
#   - Silver / Bronze hit → MAJOR (quarantine — non-premium tier still gets a
#     free baseline served via the read surface, but flagged for repolish).
#
# Patterns are taken verbatim from brief AC-2.
VAGUE_CONTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    # "looks like the sort of fixture / match / league fixture / game"
    (r"\blooks?\s+like\s+the\s+sort\s+of\b", "looks like the sort of"),
    # "takes shape once one side settles into its preferred tempo"
    (r"\btakes?\s+shape\b", "takes shape"),
    (r"\bsettles?\s+into\s+its?\s+(?:preferred\s+)?tempo\b",
     "settles into its preferred tempo"),
    # "Risk reads clean here." — generic bare-cleanliness assertion.
    (r"\breads?\s+clean\s+here\b", "reads clean here"),
    # "The model and standard match volatility are the only live variables."
    (r"\b(?:the\s+)?only\s+live\s+variables?\b", "only live variables"),
    # "the play is live without being loud" — verbatim live failure phrase.
    (r"\bplay\s+is\s+live\s+without\s+being\s+loud\b",
     "play is live without being loud"),
    # "measured rather than loud" — verbatim live failure phrase.
    (r"\bmeasured\s+rather\s+than\s+loud\b", "measured rather than loud"),
    # "standard match volatility" — generic risk filler.
    (r"\bstandard\s+match\s+volatility\b", "standard match volatility"),
    # "the model and ..." — telemetry-class voice ("the model and standard
    # match volatility are the only live variables"). Distinct from the
    # narrower "the model estimates" telemetry vocabulary in Gate 8.
    (r"\bthe\s+model\s+and\b", "the model and"),
    # "everything we have points the same way" — empty-calorie closure.
    (r"\beverything\s+we\s+have\s+points\s+the\s+same\s+way\b",
     "everything we have points the same way"),
    # "the sort of fixture / match / game / league" — broader than "looks like
    # the sort of" since it can fire in mid-sentence.
    (r"\bthe\s+sort\s+of\s+(?:fixture|match|game|league)\b",
     "the sort of fixture"),
    # "once one side settles" — paired with "takes shape" but fires solo too.
    (r"\bonce\s+one\s+side\s+settles\b", "once one side settles"),
    # "not a huge edge, but X is still better" — empty-calorie hedging on a
    # premium card. The verdict-generator rubric requires Strong-band Gold to
    # close with conviction, not "but it's still better than our number".
    (r"\bnot\s+a\s+huge\s+edge\b", "not a huge edge"),
    # "but Supabets / Betway / Hollywoodbets / GBets / WSB / Sportingbet's
    # 2.38 is still better" — the wrapped form of the above. Word-boundary on
    # bookmaker name keyed to the live failure case.
    (
        r"\bbut\s+(?:supabets|betway|hollywoodbets|gbets|wsb|sportingbet)"
        r"(?:\'?s)?\s+\d+\.\d{2}\s+is\s+still\b",
        "but bookmaker odds is still better",
    ),
)

_VAGUE_CONTENT_RE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in VAGUE_CONTENT_PATTERNS
)


def _check_vague_content_patterns(text: str) -> list[str]:
    """Return deduped list of vague-content pattern hits found in `text`.

    Empty text → empty list. Each pattern fires at most once per scan
    (deduped by label) so `["takes shape", "looks like the sort of"]` not
    `["takes shape", "takes shape", "looks like the sort of"]`.
    """
    if not text:
        return []
    hits: list[str] = []
    seen: set[str] = set()
    for compiled, label in _VAGUE_CONTENT_RE:
        if label in seen:
            continue
        if compiled.search(text):
            hits.append(label)
            seen.add(label)
    return hits


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

    # ── Gate 10: Verdict closure rule (FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01) ─
    # AC-1: the LAST sentence of verdict_html MUST close with an action verb
    # plus tier-aware (team, odds) requirements. Live failure case 1 (Liverpool
    # vs Chelsea Gold 1.97 Supabets, 29 Apr 2026): verdict closed on form data
    # without ever telling the user to back anyone — passed all existing gates.
    if verdict_html:
        sev_close, reason_close = _check_verdict_closure_rule(
            verdict_html, edge_tier, evidence_pack,
        )
        if sev_close:
            failures.append(
                ValidationFailure(
                    gate="verdict_closure_rule",
                    severity=sev_close,
                    detail=reason_close,
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 "
                "ValidatorVerdictClosureRule match_id=%s source=%s tier=%s reason=%s",
                match_id, source_label, edge_tier, reason_close,
            )

    # ── Gate 11: Vague-content pattern ban (FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01) ─
    # AC-2: scan narrative_html (Setup, Edge, Risk, Verdict surfaces) and
    # verdict_html for empty-calorie / generic-prose patterns. Live failure
    # case 2 (Manchester United vs Liverpool Gold 2.38 Supabets) was driven by
    # phrases like "looks like the sort of league fixture that takes shape
    # once one side settles into its preferred tempo" + "the play is live
    # without being loud" + "the only live variables" — none caught by Gates
    # 8 / 9 because they aren't telemetry vocabulary or cautious-band hedging.
    #
    # Tier policy:
    #   - Diamond + Gold hit → CRITICAL (refuse write).
    #   - Silver / Bronze hit → MAJOR (quarantine — baseline still served on
    #     the read surface but the row is flagged for repolish).
    vague_severity: Severity = (
        "CRITICAL" if tier_lower in ("diamond", "gold") else "MAJOR"
    )
    if narrative_html:
        narr_vague_hits = _check_vague_content_patterns(narrative_html)
        if narr_vague_hits:
            failures.append(
                ValidationFailure(
                    gate="vague_content",
                    severity=vague_severity,
                    detail=f"hits={narr_vague_hits!r}",
                    section="narrative_html",
                )
            )
            log.warning(
                "FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 "
                "ValidatorVagueContent match_id=%s source=%s tier=%s "
                "section=narrative hits=%r",
                match_id, source_label, edge_tier, narr_vague_hits,
            )
    if verdict_html:
        v_vague_hits = _check_vague_content_patterns(verdict_html)
        if v_vague_hits:
            failures.append(
                ValidationFailure(
                    gate="vague_content",
                    severity=vague_severity,
                    detail=f"verdict hits={v_vague_hits!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 "
                "ValidatorVagueContent match_id=%s source=%s tier=%s "
                "section=verdict_html hits=%r",
                match_id, source_label, edge_tier, v_vague_hits,
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


# ── FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 — AC-1 ──────────
#
# Verdict-only validator for the verdict-cache write path. Subset of the unified
# validator that runs gates relevant to a verdict surface that has no Setup /
# Edge / Risk sections — verdict-cache rows write `narrative_html=''` by design
# (per Rule 19), so the unified validator's narrative-section gates are no-ops
# on this path. This function inlines the verdict-relevant gates and additionally:
#   - scans setup-pricing patterns against verdict_html (premium leak vector)
#   - scans manager validation against verdict_html
#   - enforces verdict char range [100, 260]
#
# Tier-aware enforcement matrix (caller policy at _store_verdict_cache_sync):
#   - Diamond + Gold → CRITICAL on banned-phrase / venue / manager / strong-band-
#     tone / closure rule → refuse write, log PremiumVerdictRefused.
#   - Silver → MAJOR on closure rule → quarantine row.
#   - Bronze → MINOR on closure rule → write with warning log.
#
# Severity assignment for each gate is computed inside this function. Caller
# inspects ValidationResult.failures and applies the matrix above.

# Verdict char range — Rule unified-char-range / Rule 6 (140-200 soft, 100 floor,
# 260 hard max). The brief AC-1 enforces a minimum of 100 (verdicts under 100
# chars are content-empty by structure, e.g. truncated single-clause "Take it.")
# and the hard max of VERDICT_HARD_MAX=260 is already enforced by _cap_verdict
# in narrative_spec, so this gate primarily guards the lower bound.
_VERDICT_CHAR_MIN: int = 100
_VERDICT_CHAR_MAX: int = 260


def _validate_verdict_for_persistence(
    verdict_html: str,
    edge_tier: str,
    evidence_pack: dict | None,
    source_label: str,
    match_id: str = "",
) -> ValidationResult:
    """Run the verdict-cache pre-persist gate stack.

    Subset of `_validate_narrative_for_persistence` scoped to a verdict surface
    only (no Setup/Edge/Risk sections). Gates run:

      1. Banned phrases (Rule 14/17/W84-Q9) — `BANNED_NARRATIVE_PHRASES`.
      2. Venue leak (Rule 18) — `find_venue_leaks`.
      3. Setup-pricing leak — `_find_setup_strict_ban_violations` against
         verdict_html (catches odds/probability vocabulary that occasionally
         leaks from verdict prose). Premium-tier hits CRITICAL.
      4. Manager validation against coaches.json — `validate_manager_names`
         (verdict-only via `min_verdict_quality`).
      5. Verdict quality floor — `min_verdict_quality` (markdown leak, length
         tier-floor, Diamond price-prefix, manager fabrication, venue, banned
         shapes, analytical vocab count). Returns single bool — surfaced as
         MAJOR severity.
      6. Telemetry vocabulary (Gate 8) — `_check_telemetry_vocabulary`.
         Premium = CRITICAL; non-premium = MAJOR.
      7. Strong-band tone lock (Gate 9) — `_check_tier_band_tone`. Diamond/Gold
         = CRITICAL; Silver = MAJOR; Bronze skipped.
      8. Verdict closure rule (Gate 10) — `_check_verdict_closure_rule`. Tier
         enforcement: Diamond/Gold all-3 components, Silver action+team-or-odds,
         Bronze action only.
      9. Vague-content patterns (Gate 11) — `_check_vague_content_patterns`.
         Premium = CRITICAL; non-premium = MAJOR.
     10. Verdict char range — must be in [_VERDICT_CHAR_MIN, _VERDICT_CHAR_MAX].
         Premium = CRITICAL on under-min; non-premium = MAJOR.

    Skipped (no narrative sections to scan):
      - Setup-pricing semantic detector (operates on the Setup section only)
      - Manager hallucination across Setup/Edge/Risk sections
      - Claim verification against evidence (operates on full narrative_html)
      - Section-level quality checks (length, entity counts)

    Parameters
    ----------
    verdict_html
        Verdict prose to validate. Empty/whitespace returns
        `ValidationResult(passed=True)` without any failures.
    edge_tier
        Lowercase tier label ("diamond" | "gold" | "silver" | "bronze").
        Tier-conditional gates use this to select severity.
    evidence_pack
        Optional dict carrying ``home_team``, ``away_team`` (used by closure
        rule team-name match) and ``managers`` / ``home_manager`` /
        ``away_manager`` (used by `validate_manager_names`).
    source_label
        Source identifier ("verdict-cache" | "view-time" | etc.). Used in log
        markers only.
    match_id
        Match key for logging. Empty by default — pass when available.

    Returns
    -------
    ValidationResult
        ``passed`` is True iff there are zero CRITICAL and zero MAJOR failures.
        Caller applies tier-aware enforcement (refuse / quarantine / warn).
    """
    failures: list[ValidationFailure] = []
    if not verdict_html or not verdict_html.strip():
        return ValidationResult(passed=True)

    tier_lower = (edge_tier or "").lower()
    is_premium = tier_lower in ("diamond", "gold")

    # Lazy imports — see _validate_narrative_for_persistence for rationale.
    try:
        from narrative_spec import (
            find_venue_leaks,
            min_verdict_quality,
        )
    except ImportError as exc:
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorImportFailed match_id=%s err=%s — gate is no-op",
            match_id, exc,
        )
        return ValidationResult(passed=True)

    try:
        from bot import _find_setup_strict_ban_violations as _find_setup_strict_ban  # type: ignore[attr-defined]
    except ImportError:
        _find_setup_strict_ban = None  # type: ignore[assignment]

    try:
        from bot import BANNED_NARRATIVE_PHRASES  # type: ignore[attr-defined]
    except ImportError:
        BANNED_NARRATIVE_PHRASES = []  # type: ignore[assignment]

    # ── Gate A: Venue leaks (Rule 18) ─────────────────────────────────────────
    venues = find_venue_leaks(verdict_html)
    if venues:
        failures.append(
            ValidationFailure(
                gate="venue_leak",
                severity="CRITICAL",
                detail=f"verdict venues={venues!r}",
                section=_SECTION_VERDICT_HTML,
            )
        )
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorVenueLeak match_id=%s source=%s venues=%r",
            match_id, source_label, venues,
        )

    # ── Gate B: BANNED_NARRATIVE_PHRASES (Rule 14/17/W84-Q9 catalogue) ────────
    if BANNED_NARRATIVE_PHRASES:
        v_lower = verdict_html.lower()
        hits = [p for p in BANNED_NARRATIVE_PHRASES if p.lower() in v_lower]
        if hits:
            sev_banned: Severity = "CRITICAL" if is_premium else "MAJOR"
            failures.append(
                ValidationFailure(
                    gate="banned_phrase",
                    severity=sev_banned,
                    detail=f"hits={hits[:5]!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
                "VerdictValidatorBannedPhrase match_id=%s source=%s tier=%s "
                "hits=%r",
                match_id, source_label, edge_tier, hits[:5],
            )

    # ── Gate C: Setup-pricing leak (premium-tier protection) ──────────────────
    # Verdict prose occasionally leaks pricing vocabulary that should live in
    # The Edge. The strict-ban detector covers `price`, `priced`, `bookmaker`,
    # `odds`, `implied`, `fair value`, `expected value`, `model reads`,
    # `market architecture`. Note: legitimate verdict closure cites odds shape
    # (e.g. "Back Liverpool at 1.97 with Supabets") — that's a numeric token
    # match, not a pricing-vocabulary hit, and is allowed.
    if _find_setup_strict_ban is not None:
        try:
            strict_reasons = _find_setup_strict_ban(verdict_html)
        except Exception as exc:
            strict_reasons = []
            log.warning(
                "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
                "VerdictValidatorStrictBanFailed match_id=%s err=%s",
                match_id, exc,
            )
        if strict_reasons:
            sev_pricing: Severity = "CRITICAL" if is_premium else "MAJOR"
            failures.append(
                ValidationFailure(
                    gate="setup_pricing",
                    severity=sev_pricing,
                    detail=f"verdict reasons={strict_reasons!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
                "VerdictValidatorSetupPricing match_id=%s source=%s tier=%s "
                "reasons=%r",
                match_id, source_label, edge_tier, strict_reasons,
            )

    # ── Gate D: Verdict quality floor (markdown / manager / Diamond price-prefix) ─
    # `min_verdict_quality` is the existing serve-time floor; surfaced here as
    # a single MAJOR failure on rejection. It internally calls
    # `validate_manager_names` (manager hallucination), `validate_diamond_
    # price_prefix`, `validate_no_markdown_leak`, length floor, and venue check.
    try:
        verdict_ok = min_verdict_quality(
            verdict_html, tier=edge_tier, evidence_pack=evidence_pack
        )
    except Exception as exc:
        verdict_ok = True
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorQualityFailed match_id=%s err=%s",
            match_id, exc,
        )
    if not verdict_ok:
        # Verdict quality floor (length, manager fabrication, Diamond
        # price-prefix, markdown leak, venue, banned shapes, analytical
        # vocab count) is CRITICAL across ALL tiers — a verdict that fails
        # `min_verdict_quality` is structurally broken (e.g. 30-char "At
        # 1.85 on Betway for Arsenal." fails the Bronze 60-char floor) and
        # must not be persisted. Preserves the W92-VERDICT-QUALITY P2
        # regression-guard contract that any verdict failing the quality
        # floor is silently SKIPPED with a Sentry breadcrumb.
        failures.append(
            ValidationFailure(
                gate="verdict_quality",
                severity="CRITICAL",
                detail=f"len={len(verdict_html)} sample={verdict_html[:80]!r}",
                section=_SECTION_VERDICT_HTML,
            )
        )
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorQualityFail match_id=%s source=%s tier=%s len=%d "
            "sample=%r",
            match_id, source_label, edge_tier, len(verdict_html),
            verdict_html[:80],
        )

    # ── Gate E: Telemetry vocabulary (Rule 17 / Gate 8) ───────────────────────
    tele_hits = _check_telemetry_vocabulary(
        verdict_html, edge_tier, "verdict_html"
    )
    if tele_hits:
        sev_tele: Severity = "CRITICAL" if is_premium else "MAJOR"
        failures.append(
            ValidationFailure(
                gate="telemetry_vocabulary",
                severity=sev_tele,
                detail=f"verdict hits={tele_hits!r}",
                section=_SECTION_VERDICT_HTML,
            )
        )
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorTelemetryVocab match_id=%s source=%s tier=%s "
            "hits=%r",
            match_id, source_label, edge_tier, tele_hits,
        )

    # ── Gate F: Strong-band tone lock (Gate 9) ────────────────────────────────
    # Bronze short-circuits inside `_check_tier_band_tone` (cautious-band IS
    # Bronze's correct register).
    if tier_lower in ("diamond", "gold", "silver"):
        sev_sb: Severity = "CRITICAL" if is_premium else "MAJOR"
        sb_hits, sb_hedging = _check_tier_band_tone(
            verdict_html, edge_tier, "verdict_html"
        )
        if sb_hits:
            failures.append(
                ValidationFailure(
                    gate="strong_band_tone",
                    severity=sev_sb,
                    detail=f"verdict hits={sb_hits!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
                "VerdictValidatorStrongBandTone match_id=%s source=%s tier=%s "
                "hits=%r",
                match_id, source_label, edge_tier, sb_hits,
            )
        # Hedging-conditional opener fires on Diamond/Gold only.
        if sb_hedging and is_premium:
            failures.append(
                ValidationFailure(
                    gate="strong_band_hedging_opener",
                    severity="CRITICAL",
                    detail=f"hedging conditional opener; sample={verdict_html[:100]!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
                "VerdictValidatorStrongBandHedgingOpener match_id=%s source=%s "
                "tier=%s sample=%r",
                match_id, source_label, edge_tier, verdict_html[:100],
            )

    # ── Gate G: Verdict closure rule (Gate 10) ────────────────────────────────
    sev_close, reason_close = _check_verdict_closure_rule(
        verdict_html, edge_tier, evidence_pack,
    )
    if sev_close:
        # `_check_verdict_closure_rule` returns CRITICAL for all tier
        # mismatches; the brief's tier-aware enforcement matrix downgrades
        # closure to MAJOR on Silver and MINOR on Bronze. We override the
        # severity here to match the matrix while preserving the diagnostic.
        if tier_lower == "silver":
            close_severity: Severity = "MAJOR"
        elif tier_lower == "bronze":
            close_severity = "MINOR"
        else:
            close_severity = sev_close
        failures.append(
            ValidationFailure(
                gate="verdict_closure_rule",
                severity=close_severity,
                detail=reason_close,
                section=_SECTION_VERDICT_HTML,
            )
        )
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorClosureRule match_id=%s source=%s tier=%s "
            "severity=%s reason=%s",
            match_id, source_label, edge_tier, close_severity, reason_close,
        )

    # ── Gate H: Vague-content patterns (Gate 11) ──────────────────────────────
    vague_hits = _check_vague_content_patterns(verdict_html)
    if vague_hits:
        sev_vague: Severity = "CRITICAL" if is_premium else "MAJOR"
        failures.append(
            ValidationFailure(
                gate="vague_content",
                severity=sev_vague,
                detail=f"verdict hits={vague_hits!r}",
                section=_SECTION_VERDICT_HTML,
            )
        )
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorVagueContent match_id=%s source=%s tier=%s "
            "hits=%r",
            match_id, source_label, edge_tier, vague_hits,
        )

    # ── Gate I: Verdict char range [_VERDICT_CHAR_MIN, _VERDICT_CHAR_MAX] ────
    # Strip HTML tags before measuring — the cap function works on plain text.
    plain = _HTML_TAG_RE.sub("", verdict_html).strip()
    plain_len = len(plain)
    if plain_len < _VERDICT_CHAR_MIN:
        sev_short: Severity = "CRITICAL" if is_premium else "MAJOR"
        failures.append(
            ValidationFailure(
                gate="verdict_char_range",
                severity=sev_short,
                detail=f"len={plain_len} < min={_VERDICT_CHAR_MIN}; "
                       f"sample={plain[:80]!r}",
                section=_SECTION_VERDICT_HTML,
            )
        )
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorCharRangeUnder match_id=%s source=%s tier=%s "
            "len=%d sample=%r",
            match_id, source_label, edge_tier, plain_len, plain[:80],
        )
    elif plain_len > _VERDICT_CHAR_MAX:
        # Over the hard cap — _cap_verdict should have prevented this; if it
        # leaks through, MAJOR-flag for monitoring. Caller doesn't refuse on
        # this alone (the cap is a safety net, not a content-quality gate).
        failures.append(
            ValidationFailure(
                gate="verdict_char_range",
                severity="MAJOR",
                detail=f"len={plain_len} > max={_VERDICT_CHAR_MAX}",
                section=_SECTION_VERDICT_HTML,
            )
        )
        log.warning(
            "FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 "
            "VerdictValidatorCharRangeOver match_id=%s source=%s tier=%s "
            "len=%d",
            match_id, source_label, edge_tier, plain_len,
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
