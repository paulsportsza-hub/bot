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


# FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01 (2026-04-30) — AC-1 (restored from
# reverted b585c69; AC-1 broadened per current brief).
#
# Verdict closure rule: the LAST sentence of verdict_html MUST close with an
# ACTUAL verdict. Live failure case 1 (Liverpool vs Chelsea, Gold, 1.97
# Supabets, 29 Apr 2026 ~20:25 SAST):
#   "What stands out: Slot's Reds have picked up two wins in their last three,
#    while Chelsea are in terrible form with five losses from their last five."
# Reads like a Setup observation. Validator passed it because tier-band tone is
# fine, no telemetry vocab, no banned phrases — but it never tells the user to
# back anyone. Closure-rule gate catches this structurally.
#
# Live failure case (this brief, 30 Apr 2026 ~15:55 SAST, Gujarat Titans vs
# RCB Gold 1.72 WSB):
#   "The data has a cleaner read on Royal Challengers Bengaluru's recent form
#    than on Gujarat Titans' — that's where the analysis starts."
# Same architectural failure mode — Setup-style opener as the entire verdict.
#
# Three components in the closing sentence:
#   1. Action verb cluster (case-insensitive, word-boundary).
#   2. Team / selection name (matches evidence_pack home/away OR betting selection).
#   3. Odds shape (decimal OR fraction OR American).
#
# Tier-aware enforcement (caller policy):
#   - Diamond + Gold (Strong-band): all 3 → PASS. Missing ANY → CRITICAL.
#   - Silver: action verb required; team OR odds optional but at least one.
#     Missing both → CRITICAL.
#   - Bronze: action verb required; team / odds optional.
#     Missing action verb → CRITICAL.
# FIX-VERDICT-CLOSURE-RULE-LOOSEN-AND-GERUND-ACCEPT-01 (2026-05-01) — AC-1.
# Reverses the strict imperative-only tightening from
# FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01. That tightening produced
# zero throughput — 100% of premium polish refused, then 100% of W82 baselines
# refused, plus blocking 6 Bronze speculative rows that close with sizing tails.
# The loosened rule catches genuine failures (no action verb at all, Setup-style
# observations as the close) while accepting legitimate prose shapes:
#   - Imperatives: back, bet on, get on, get behind, take, lean on, ride, …
#   - Gerunds: backing, taking, getting on, worth taking, …
#   - Declaratives: "X is the pick / play / call / lean / bet / value"
#   - Action prepositions: "worth a play on X", "worth a lean on X"
# The sizing-tail case STILL fails (no action verb at all):
#   FAIL: "Small-to-standard stake on this one at the current number."
# The Setup-style observation STILL fails:
#   FAIL: "That's where the analysis starts."
_VERDICT_ACTION_VERBS: tuple[str, ...] = (
    # Imperatives (9 clusters + get behind)
    r"back",
    r"bet\s+on",
    r"put\s+your\s+money\s+on",
    r"get\s+(?:on|behind)",
    r"take",
    r"lean\s+on",
    r"ride",
    r"hammer\s+it\s+on",
    r"smash",
    # Gerunds
    r"backing",
    r"betting\s+on",
    r"getting\s+on",
    r"taking",
    r"leaning\s+on",
    r"riding",
    r"hammering\s+it\s+on",
    r"smashing",
    r"worth\s+taking",
    # Declaratives
    r"is\s+the\s+(?:pick|play|call|lean|bet|value)",
    # Action prepositions
    r"worth\s+(?:a\s+)?(?:lean|back|punt|play|small)",
)

_VERDICT_ACTION_RE: re.Pattern[str] = re.compile(
    # Imperatives (9 clusters + get behind)
    r"\b(?:back|bet\s+on|put\s+your\s+money\s+on|get\s+(?:on|behind)|take|"
    r"lean\s+on|ride|hammer\s+it\s+on|smash)\b"
    # Gerunds
    r"|\b(?:backing|betting\s+on|getting\s+on|taking|"
    r"leaning\s+on|riding|hammering\s+it\s+on|smashing|worth\s+taking)\b"
    # Declaratives
    r"|\bis\s+the\s+(?:pick|play|call|lean|bet|value)\b"
    # Action prepositions
    r"|\bworth\s+(?:a\s+)?(?:lean|back|punt|play|small)\b",
    re.IGNORECASE,
)

# BUILD-W82-RIP-AND-REPLACE-01 (2026-05-02) — corpus-imperative regex.
# FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-03 (2026-05-04) — "worth a"
# removed from the universal alternation. Verified by codebase audit:
# every corpus sentence using "worth a ..." closures lives in the Bronze
# section of VERDICT_CORPUS only. Keeping "worth a" in this tier-uniform
# regex created the round-3 cross-tier leak Codex flagged
# (Diamond/Gold/Silver verdicts closing with the literal Bronze
# signal-mapper closure ``worth a small play on X, light stake.`` passed
# Gate 9 because ``worth a`` matched here before the tier-scoped check
# fired). "worth a" is now exclusively in `_BRONZE_SIGNAL_MAPPER_CLOSE_RE`.
# Other tier-uniform tokens (back / hammer / get on / take / bet / lock in /
# load up / go in / the play is / the call is) remain — corpus authors
# enforce conviction-language by claims_max_conviction filtering, not by
# this regex.
_CORPUS_IMPERATIVE_CLOSE_RE: re.Pattern[str] = re.compile(
    r"(?:^|\s)("
    r"back|hammer|get\s+on|take|bet|lock\s+in|load\s+up|go\s+in|"
    r"the\s+play\s+is|the\s+call\s+is"
    r")\b.*[\.!]?\s*$",
    re.IGNORECASE,
)

# FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-02 (2026-05-04) — tier-scoped
# signal-mapper imperatives. Per Codex adversarial-review round 2: adding
# the spec §10 imperatives to a single tier-agnostic alternation creates a
# loophole where a Silver/Bronze polished verdict closing with "go big" or
# a Diamond/Gold one closing with "lean ... standard stake" passes Gate 9.
# Round 3 (FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-03): the Bronze regex now
# also covers the corpus-authored "worth a small play / worth a measured
# punt / worth a small punt / worth a measured play" closures (all 18
# sentences live in the Bronze section of VERDICT_CORPUS by codebase audit).
# Each new imperative is keyed to the ONE tier the spec authorises:
#   - Diamond → "hard to look past {team}, go big at {odds} on {bookmaker}"
#   - Silver  → "lean {team}, standard stake"
#   - Bronze  → "worth a small play on {team}, light stake" (signal-mapper)
#               OR "worth a (small|measured) (play|punt) on ..." (legacy
#               corpus Bronze section) OR "small play ..." (mapper short form)
#   - Gold    → "back {team}, standard stake" — already covered by the
#     legacy "back" alternation in _CORPUS_IMPERATIVE_CLOSE_RE.
# `imperative_close_ok(text, tier)` is the single entry point: it accepts
# legacy corpus closures for any tier (the corpus uses tier-uniform tokens
# and enforces conviction via filtering, not the regex) PLUS the spec §10
# tier-scoped imperatives. A future cross-tier leak from either generator
# (corpus or mapper) hits a CRITICAL/MAJOR validation failure here.
_DIAMOND_SIGNAL_MAPPER_CLOSE_RE: re.Pattern[str] = re.compile(
    r"(?:^|\s)("
    r"go\s+big|hard\s+to\s+look\s+past"
    r")\b.*[\.!]?\s*$",
    re.IGNORECASE,
)
_SILVER_SIGNAL_MAPPER_CLOSE_RE: re.Pattern[str] = re.compile(
    r"(?:^|\s)lean\b.*[\.!]?\s*$",
    re.IGNORECASE,
)
_BRONZE_SIGNAL_MAPPER_CLOSE_RE: re.Pattern[str] = re.compile(
    r"(?:^|\s)("
    r"worth\s+a|small\s+play"
    r")\b.*[\.!]?\s*$",
    re.IGNORECASE,
)


def imperative_close_ok(text: str, tier: str) -> bool:
    """Return True iff ``text``'s closing sentence carries a tier-appropriate
    imperative.

    Accepts the legacy corpus alternation for any tier (the corpus is
    tier-uniform on tokens like ``back`` / ``hammer`` / ``take``; tier
    semantics are enforced by ``claims_max_conviction`` filtering at the
    corpus picker), AND the spec §10 signal-mapper imperatives keyed to
    their authorised tier — so a Silver/Bronze verdict closing with
    ``go big`` (Diamond-only), a Diamond/Gold one closing with ``lean``
    (Silver-only), or a Diamond/Gold/Silver one closing with ``worth a
    small play`` / ``worth a measured punt`` (Bronze-only, both signal-
    mapper and corpus) all fail Gate 9.

    Empty / non-string text returns False. Unknown tiers fall back to the
    legacy corpus check only — no signal-mapper imperatives are added,
    matching the original gate behaviour.

    NB: ``worth a`` was removed from the legacy alternation under
    FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-03. Audit of VERDICT_CORPUS
    confirmed every "worth a ..." closure lives in the Bronze section
    only, so the move is loss-free for the corpus path.
    """
    if not text:
        return False
    tier_lower = (tier or "").strip().lower()
    # Tier-scoped imperatives are checked FIRST so the Bronze "worth a"
    # / "small play" closures are matched against the Bronze branch only;
    # the legacy alternation does NOT include "worth a" any more, but
    # we keep the check ordering future-proof against further additions.
    if tier_lower == "diamond":
        if _DIAMOND_SIGNAL_MAPPER_CLOSE_RE.search(text):
            return True
    elif tier_lower == "silver":
        if _SILVER_SIGNAL_MAPPER_CLOSE_RE.search(text):
            return True
    elif tier_lower == "bronze":
        if _BRONZE_SIGNAL_MAPPER_CLOSE_RE.search(text):
            return True
    return bool(_CORPUS_IMPERATIVE_CLOSE_RE.search(text))

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
# even when the team name is absent.
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
    """Return the last non-empty sentence from ``text`` after HTML strip.

    Tokenisation: split on ``[.!?]\\s+`` (sentence terminators followed by
    whitespace), take the last non-empty segment. Trailing punctuation is
    stripped. Empty input returns empty string.
    """
    if not text:
        return ""
    plain = _HTML_TAG_RE.sub("", text).strip()
    if not plain:
        return ""
    parts = re.split(r"[.!?]\s+", plain)
    nonempty = [p.strip() for p in parts if p and p.strip()]
    if not nonempty:
        return ""
    last = nonempty[-1]
    return last.rstrip(" \t.!?;,…—–-").strip()


def _verdict_closure_components(
    verdict_text: str,
    home_team: str = "",
    away_team: str = "",
) -> tuple[bool, bool, bool]:
    """Return (has_action, has_team_or_selection, has_odds) for closing sentence."""
    last = _last_sentence(verdict_text)
    if not last:
        return (False, False, False)
    has_action = bool(_VERDICT_ACTION_RE.search(last))
    has_odds = bool(_VERDICT_ODDS_RE.search(last))

    last_lower = last.lower()
    team_hit = False
    for raw in (home_team, away_team):
        name = (raw or "").strip().lower()
        if not name:
            continue
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

    Returns ``(None, "")`` when the verdict closes correctly for its tier.
    Returns ``("CRITICAL", reason)`` when the closing sentence fails the rule.
    """
    if not verdict_html:
        return (None, "")
    tier = (edge_tier or "").lower()
    home_team = ""
    away_team = ""
    if isinstance(evidence_pack, dict):
        # evidence_pack["home_team"] may be a string (test/direct caller) or a
        # dict {"name": "...", "coach": ...} (serialised EvidencePack path).
        _ht = evidence_pack.get("home_team") or ""
        home_team = (_ht.get("name", "") if isinstance(_ht, dict) else str(_ht)).strip()
        _at = evidence_pack.get("away_team") or ""
        away_team = (_at.get("name", "") if isinstance(_at, dict) else str(_at)).strip()
    has_action, has_team, has_odds = _verdict_closure_components(
        verdict_html, home_team, away_team,
    )
    last = _last_sentence(verdict_html)
    sample = last[:120] if last else ""

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

    if tier == "bronze":
        if not has_action:
            return (
                "CRITICAL",
                f"Bronze closing sentence missing action_verb; "
                f"sample={sample!r}",
            )
        return (None, "")

    return (None, "")


# FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01 (2026-04-30) — AC-2 (restored from
# reverted b585c69 + 1 new whole-verdict-is-opener pattern).
#
# Vague-content pattern ban. Live failure case 2 (Manchester United vs
# Liverpool, Gold, 2.38 Supabets, 29 Apr 2026 ~20:25 SAST): the AI Breakdown
# read like an empty-calorie market summary — "looks like the sort of league
# fixture that takes shape once one side settles into its preferred tempo",
# "the play is live without being loud", "Risk reads clean here. The model and
# standard match volatility are the only live variables."
#
# Tier policy (caller):
#   - Diamond + Gold hit → CRITICAL (refuse write).
#   - Silver / Bronze hit → MAJOR (quarantine).
VAGUE_CONTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\blooks?\s+like\s+the\s+sort\s+of\b", "looks like the sort of"),
    (r"\btakes?\s+shape\b", "takes shape"),
    (r"\bsettles?\s+into\s+its?\s+(?:preferred\s+)?tempo\b",
     "settles into its preferred tempo"),
    (r"\breads?\s+clean\s+here\b", "reads clean here"),
    (r"\b(?:the\s+)?only\s+live\s+variables?\b", "only live variables"),
    (r"\bplay\s+is\s+live\s+without\s+being\s+loud\b",
     "play is live without being loud"),
    (r"\bmeasured\s+rather\s+than\s+loud\b", "measured rather than loud"),
    (r"\bstandard\s+match\s+volatility\b", "standard match volatility"),
    (r"\bthe\s+model\s+and\b", "the model and"),
    (r"\beverything\s+we\s+have\s+points\s+the\s+same\s+way\b",
     "everything we have points the same way"),
    (r"\bthe\s+sort\s+of\s+(?:fixture|match|game|league)\b",
     "the sort of fixture"),
    (r"\bonce\s+one\s+side\s+settles\b", "once one side settles"),
    (r"\bnot\s+a\s+huge\s+edge\b", "not a huge edge"),
    (
        r"\bbut\s+(?:supabets|betway|hollywoodbets|gbets|wsb|sportingbet)"
        r"(?:\'?s)?\s+\d+\.\d{2}\s+is\s+still\b",
        "but bookmaker odds is still better",
    ),
    # FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01 (this brief, AC-2 addition):
    # "The data has a cleaner read on X — that's where the analysis starts."
    # Anchored: matches a verdict whose ENTIRE content is a Setup-style opener
    # with no closing recommendation. Card 1 verbatim text from 30 Apr 15:55 SAST.
    (
        r"^\s*the\s+data\s+has\s+a\s+cleaner\s+read\s+on\s+.*?\s+—\s+that.s\s+where\s+the\s+analysis\s+starts\.?\s*$",
        "data has a cleaner read on (whole-verdict opener)",
    ),
)

_VAGUE_CONTENT_RE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in VAGUE_CONTENT_PATTERNS
)


def _check_vague_content_patterns(text: str) -> list[str]:
    """Return deduped list of vague-content pattern hits found in ``text``."""
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

    # FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-2:
    # Gates 1 (venue narrative_html scan), 2a/2b (setup_pricing), 3 (manager
    # hallucination on all-sections), 4 (claim verification), and 11
    # (vague_content) are dropped. They targeted long-form Setup/Edge/Risk
    # narrative_html sections that the polish path no longer writes
    # (BUILD-VERDICT-ONLY-STRIP-AI-BREAKDOWN-01 + this brief AC-1). The
    # verdict-only equivalents below remain in force.

    # ── Gate 3 (verdict-only): Manager validation against coaches.json ──────
    # Manager hallucination on the verdict surface still matters — the
    # 4-anchor verdict spec mandates HOME/AWAY COACH surnames taken from
    # CANONICAL MANAGERS. validate_manager_names returns False when the
    # verdict introduces a name not in evidence_pack — flag CRITICAL.
    if verdict_html and evidence_pack is not None:
        try:
            from narrative_spec import validate_manager_names as _validate_mgr_verdict
        except ImportError:
            _validate_mgr_verdict = None  # type: ignore[assignment]
        if _validate_mgr_verdict is not None:
            try:
                mgr_ok = _validate_mgr_verdict(verdict_html, evidence_pack)
            except Exception as exc:
                mgr_ok = True
                log.warning(
                    "FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 "
                    "ValidatorVerdictManagerCheckFailed match_id=%s err=%s",
                    match_id, exc,
                )
            if not mgr_ok:
                failures.append(
                    ValidationFailure(
                        gate="manager_hallucination",
                        severity="CRITICAL",
                        detail=f"verdict manager hallucination; sample={verdict_html[:120]!r}",
                        section=_SECTION_VERDICT_HTML,
                    )
                )
                log.warning(
                    "FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 "
                    "ValidatorVerdictManagerHallucination match_id=%s "
                    "source=%s tier=%s sample=%r",
                    match_id, source_label, edge_tier, verdict_html[:120],
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
    # BUILD-EVIDENCE-ENRICH-VENUE-SCOREBOARD-PROJECTION-01: verified-list mode.
    if verdict_html:
        verdict_venues = find_venue_leaks(verdict_html, evidence_pack)
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

    # ── Gate 7: BANNED_NARRATIVE_PHRASES on verdict_html ────────────────────
    # FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-2:
    # narrative_html no longer carries Setup/Edge/Risk sections; scope this
    # scan to verdict_html only.
    if BANNED_NARRATIVE_PHRASES and verdict_html:
        verdict_lower = verdict_html.lower()
        hits = [p for p in BANNED_NARRATIVE_PHRASES if p.lower() in verdict_lower]
        if hits:
            failures.append(
                ValidationFailure(
                    gate="banned_phrase",
                    severity="MAJOR",
                    detail=f"hits={hits[:5]!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorBannedPhrase "
                "match_id=%s source=%s hits=%r",
                match_id, source_label, hits[:5],
            )

    # ── Gate 8: Rule 17 telemetry vocabulary scan on verdict_html ───────────
    # FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-2:
    # narrative_html scope dropped (no long-form sections written).
    # Premium tier (Diamond/Gold) hit → CRITICAL (refuse write).
    # Non-premium tier hit → MAJOR (quarantine).
    tier_lower = (edge_tier or "").lower()
    tele_severity: Severity = "CRITICAL" if tier_lower in ("diamond", "gold") else "MAJOR"
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

    # ── Gate 9: Imperative-close rule (BUILD-W82-RIP-AND-REPLACE-01) ────────
    # The deterministic verdict_corpus emits sentences whose closing imperative
    # is one of: back / hammer / get on / take / bet / lock in / load up /
    # go in / the play is / the call is / worth a. The previous tier-branching
    # closure rule (Diamond/Gold = action+team+odds; Silver = action+one-of;
    # Bronze = action only) is retired — the corpus is uniform: every sentence
    # carries action+team+odds+bookmaker by construction.
    #
    # Tier-aware enforcement matrix:
    #   - Diamond + Gold → CRITICAL (premium tier MUST clear imperative-close;
    #     synthesis-on-tap covers the cache miss).
    #   - Silver + Bronze → MAJOR (quarantine).
    if verdict_html:
        last = _last_sentence(verdict_html)
        # FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-02 (2026-05-04): tier-scoped
        # check via imperative_close_ok — accepts legacy corpus closures for
        # any tier AND spec §10 signal-mapper imperatives only for the tier
        # the spec authorises (Diamond → "go big" / "hard to look past";
        # Silver → "lean"; Bronze → "small play"). Cross-tier mismatches now
        # fail Gate 9 with the same severity ladder.
        imp_close_ok = imperative_close_ok(last, tier_lower) if last else False
        if not imp_close_ok:
            close_severity: Severity = (
                "CRITICAL" if tier_lower in ("diamond", "gold") else "MAJOR"
            )
            failures.append(
                ValidationFailure(
                    gate="imperative_close",
                    severity=close_severity,
                    detail=f"last sentence missing imperative; sample={last[:120]!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "BUILD-W82-RIP-AND-REPLACE-01 ValidatorImperativeClose "
                "match_id=%s source=%s tier=%s sample=%r",
                match_id, source_label, edge_tier, last[:120],
            )

    # ── Gate 11: Vague-content pattern ban (retained from FIX-VERDICT-CLOSURE) ─
    # BUILD-W82-RIP-AND-REPLACE-01: re-enabled per brief Phase 2d (validator
    # simplification retains the vague-content gate). Premium tier hits are
    # CRITICAL; non-premium are MAJOR.
    if verdict_html:
        v_vague_hits = _check_vague_content_patterns(verdict_html)
        if v_vague_hits:
            vague_severity: Severity = (
                "CRITICAL" if tier_lower in ("diamond", "gold") else "MAJOR"
            )
            failures.append(
                ValidationFailure(
                    gate="vague_content",
                    severity=vague_severity,
                    detail=f"verdict hits={v_vague_hits!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "BUILD-W82-RIP-AND-REPLACE-01 ValidatorVagueContent "
                "match_id=%s source=%s tier=%s hits=%r",
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


# FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01 (2026-04-30) — AC-3.
#
# Verdict-only validator subset. Wired into every verdict-cache write site
# (currently `_store_verdict_cache_sync` in bot.py). Runs the verdict-relevant
# gates from `_validate_narrative_for_persistence`:
#   - Venue leaks in verdict_html (Gate 6 mirror)
#   - BANNED_NARRATIVE_PHRASES on verdict_html (Gate 7 mirror)
#   - Telemetry vocabulary on verdict_html (Gate 8 mirror)
#   - Strong-band tone on verdict_html (Gate 9 mirror)
#   - Closure rule on verdict_html (Gate 10)
#   - Vague-content patterns on verdict_html (Gate 11)
#   - min_verdict_quality (single MAJOR-or-CRITICAL gate)
#
# This is a thin wrapper around `_validate_narrative_for_persistence` that
# passes an empty narrative_html so only verdict-relevant gates fire. Tier
# enforcement is the caller's responsibility (writer applies the matrix).
def _validate_verdict_for_persistence(
    verdict_html: str,
    edge_tier: str,
    evidence_pack: dict | None,
    source_label: str,
) -> ValidationResult:
    """Verdict-only validator for verdict-cache write paths.

    Parameters
    ----------
    verdict_html
        The verdict surface to validate. Empty string → empty result (passed).
    edge_tier
        Tier label ("diamond" | "gold" | "silver" | "bronze"). Used for
        tier-aware Gate 9/11 severity (caller policy applies tier-aware
        write decisions on the result).
    evidence_pack
        Optional evidence dict — needed for the closure-rule team check.
        ``None`` skips team match (selection keywords still count).
    source_label
        Source label for log markers (e.g. ``"verdict-cache"``).

    Returns
    -------
    ValidationResult
        Reports findings; never makes write decisions.
    """
    if not verdict_html:
        return ValidationResult(passed=True)
    return _validate_narrative_for_persistence(
        content={
            "narrative_html": "",
            "verdict_html": verdict_html,
            "match_id": (
                evidence_pack.get("match_id", "")
                if isinstance(evidence_pack, dict) else ""
            ),
            "narrative_source": source_label,
        },
        evidence_pack=evidence_pack if isinstance(evidence_pack, dict) else None,
        edge_tier=edge_tier,
        source_label=source_label,
    )
