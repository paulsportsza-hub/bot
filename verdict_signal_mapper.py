"""Signal-mapped deterministic verdict builder.

BUILD-VERDICT-SIGNAL-MAPPED-01 (2026-05-03). Replaces the 360-sentence
sport-banded verdict corpus as the main path for verdict generation. The
corpus stays as the fallback safety net when the new builder rejects its
own output (banned-term / live-commentary scanner) or when the feature
flag is disabled.

The new builder grounds every verdict in the active Edge Signal dots
visible on the card (Price Edge / Line Mvt / Market / Tipster / Form /
Injury). It picks a primary + secondary driver per the priority order
locked in the spec and assembles "[primary phrase] and [secondary
phrase] — [tier action]".

This module is pure Python with zero bot/Sentry/DB/HTTP imports — it
must remain importable from contract tests without side effects.

Voice rubric: ``.claude/skills/verdict-generator/SKILL.md`` (signal-mapped
mode). SA-native plain English. No telemetry language. No tier names in
prose. No live-match commentary. No overclaim verbs.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Tuple

# ── Priority orders (locked per spec §7 §8) ────────────────────────────────
PRIMARY_PRIORITY: list[str] = [
    "price_edge",
    "line_mvt",
    "injury",
    "form",
    "market",
    "tipster",
]

SECONDARY_PRIORITY: list[str] = [
    "injury",
    "form",
    "line_mvt",
    "market",
    "tipster",
]


# ── Phrase libraries (spec §6 / §14 Step 4) ────────────────────────────────
PRIMARY_PHRASES: dict[str, str] = {
    "price_edge": "The price hasn't caught up",
    "line_mvt":   "The line movement still leaves value",
    "injury":     "The line doesn't fully reflect the team news",
    "form":       "Recent form backs this",
    "market":     "The wider market is leaning this way",
    "tipster":    "Outside support points this way",
}

SECONDARY_PHRASES: dict[str, str] = {
    "injury":   "team news gives it extra weight",
    "form":     "recent form backs it",
    "line_mvt": "the move has not taken the value away",
    "market":   "the market support is there",
    "tipster":  "outside support lines up",
}


# ── Tier-action language (spec §10 — FIXED) ────────────────────────────────
def build_action(
    tier: str,
    team: str,
    odds: str | float | None = None,
    bookmaker: str | None = None,
) -> str:
    """Return the tier-appropriate action clause for the close.

    Diamond bakes ``odds`` and ``bookmaker`` into the line when both are
    present; falls back to the bare team form when either is missing
    (defensive for non-edge previews and partial slot fills). Other
    tiers ignore ``odds`` / ``bookmaker`` per spec — the action clause
    closes on team + sizing only.
    """
    t = (tier or "").lower()
    team_str = (team or "").strip() or "the pick"
    if t == "diamond":
        odds_str = _format_odds(odds)
        bk_str = (bookmaker or "").strip()
        if odds_str and bk_str:
            return f"hard to look past {team_str}, go big at {odds_str} on {bk_str}"
        return f"hard to look past {team_str}, go big"
    if t == "gold":
        return f"back {team_str}, standard stake"
    if t == "silver":
        return f"lean {team_str}, standard stake"
    if t == "bronze":
        return f"worth a small play on {team_str}, light stake"
    # Unknown tier — Silver-equivalent default keeps verdict shippable.
    return f"lean {team_str}, standard stake"


def _format_odds(odds: str | float | None) -> str:
    """Render odds as ``X.XX`` or empty string when unusable.

    Accepts already-formatted strings ("1.40") or numeric inputs.
    Zero / None / unparseable → empty string so :func:`build_action`
    can fall back to the bare-team Diamond form.
    """
    if odds is None:
        return ""
    if isinstance(odds, (int, float)):
        return f"{float(odds):.2f}" if float(odds) > 0 else ""
    s = str(odds).strip()
    if not s:
        return ""
    try:
        f = float(s)
        if f > 0:
            return f"{f:.2f}"
        return ""
    except ValueError:
        return s  # pre-formatted oddities like "10/3" passed through


# ── Signal selection (spec §14 Step 3) ─────────────────────────────────────
def normalize_signals(raw_signals: Mapping[str, object] | None) -> dict[str, bool]:
    """Coerce the brief's 6 canonical signal keys into booleans.

    Accepts both the production key set (price_edge / line_mvt / market /
    tipster / form / injury) AND title-case aliases ("Price Edge" etc.)
    referenced in the spec §14 Step 2. Other key shapes (movement,
    market_agreement, lineup_injury, form_h2h) are mapped here so the
    brief contract stays clean for downstream builders even when the
    production signals dict (signal_collectors.collect_all_signals) uses
    its own naming.
    """
    if raw_signals is None:
        raw_signals = {}

    def _truthy(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, Mapping):
            # Production signals are dicts with available/signal_strength —
            # treat any non-empty dict as truthy (callers should pre-flatten
            # to bool when they care about fine-grained activation).
            return bool(value)
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "no", "none")
        return bool(value)

    def _any(keys: Iterable[str]) -> bool:
        return any(_truthy(raw_signals.get(k)) for k in keys)

    return {
        "price_edge": _any(("price_edge", "Price Edge", "priceEdge")),
        "line_mvt":   _any(("line_mvt", "Line Mvt", "movement", "line_movement")),
        "market":     _any(("market", "Market", "market_agreement")),
        "tipster":    _any(("tipster", "Tipster")),
        "form":       _any(("form", "Form", "form_h2h")),
        "injury":     _any(("injury", "Injury", "lineup_injury", "team_news")),
    }


def pick_primary(signals: Mapping[str, bool]) -> str | None:
    """Return the highest-priority active signal key, or ``None``."""
    for key in PRIMARY_PRIORITY:
        if signals.get(key):
            return key
    return None


def pick_secondary(signals: Mapping[str, bool], primary: str | None) -> str | None:
    """Return the highest-priority active secondary signal != primary."""
    for key in SECONDARY_PRIORITY:
        if key == primary:
            continue
        if signals.get(key):
            return key
    return None


# ── Fallback leads (spec §12.8) ────────────────────────────────────────────
_FALLBACK_BY_TIER: dict[str, str] = {
    "diamond": "The price still looks too big for the setup",
    "gold":    "There is enough value here to support the pick",
    "silver":  "There is just enough value here",
    "bronze":  "Not much in it, but there is a small lean",
}


# ── build_verdict (spec §14 Step 6) ────────────────────────────────────────
def build_verdict(
    team: str,
    tier: str,
    signals: Mapping[str, object] | None,
    odds: str | float | None = None,
    bookmaker: str | None = None,
    line_movement_direction: str | None = None,
) -> str:
    """Render a deterministic signal-mapped verdict.

    Control flow:
      1. Normalise raw signals to the 6 canonical booleans.
      2. Special-case Price Edge + Line Movement (spec §12.3 / §12.4):
         pick a contrast / favourable / neutral lead based on
         ``line_movement_direction``.
      3. Otherwise, primary + secondary picks per priority order. Two-part
         causal shape if both fire; clean causal if only primary; tier
         fallback (spec §12.8) if no signals are active.

    Returns the assembled sentence ending in a period. Never raises;
    defensively returns a tier-appropriate fallback when inputs are
    malformed.
    """
    norm = normalize_signals(signals)
    action = build_action(tier, team, odds, bookmaker)

    # Special: Price Edge + Line Movement — contrast / favourable / unknown.
    if norm["price_edge"] and norm["line_mvt"]:
        direction = (line_movement_direction or "").strip().lower()
        if direction == "against":
            lead = "The market has moved, but the price still looks big"
        elif direction in ("favourable", "for"):
            lead = "The line is moving our way and the price is still there"
        else:
            lead = "The move has not taken the value away"
        return f"{lead} — {action}."

    primary = pick_primary(norm)
    secondary = pick_secondary(norm, primary)

    if primary and secondary:
        return f"{PRIMARY_PHRASES[primary]} and {SECONDARY_PHRASES[secondary]} — {action}."
    if primary:
        return f"{PRIMARY_PHRASES[primary]} — {action}."

    lead = _FALLBACK_BY_TIER.get((tier or "").lower(), _FALLBACK_BY_TIER["silver"])
    return f"{lead} — {action}."


# ── Banned-term enforcement (spec §15.1 / §15.2) ───────────────────────────
BANNED_TERMS: list[str] = [
    "signal stack",
    "supporting signal",
    "signal coverage",
    "composite",
    "tier floor",
    "at this tier",
    "model and market",
    "numbers and signals",
    "confirming signal",
    "contradicting indicator",
    "EV",
    "+% edge",
    "Diamond-grade",
    "Gold-grade",
    "Silver-grade",
    "Bronze-grade",
    "Diamond-tier",
    "Gold-tier",
    "Silver-tier",
    "Bronze-tier",
]

LIVE_COMMENTARY_TERMS: list[str] = [
    "creating overloads",
    "cutting through",
    "dominating collisions",
    "dictating tempo",
    "forcing mistakes",
    "building partnerships",
    "applying pressure",
    "holding possession",
]

EXPECTED_ACTION: dict[str, str] = {
    "diamond": "go big",
    "gold":    "standard stake",
    "silver":  "standard stake",
    "bronze":  "light stake",
}


# Banned terms with word-boundary semantics — the bare "EV" token must not
# match the bookmaker word "Everton" or the verb "every", and "+% edge" must
# match the structural artefact rather than incidental "%" + "edge" prose.
_BANNED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EV", re.compile(r"\bEV\b")),
    ("+% edge", re.compile(r"\+\s*\d+\s*%\s*edge", re.IGNORECASE)),
]

_BANNED_PLAIN: list[str] = [
    term for term in BANNED_TERMS
    if term not in ("EV", "+% edge")
]


def validate_output(text: str) -> Tuple[bool, list[str]]:
    """Scan ``text`` for §15.1 / §15.2 banned constructs.

    Returns ``(ok, hits)``. ``ok`` is False when ``hits`` is non-empty.
    Banned terms are case-insensitive substring matches except where
    the regex pattern enforces word-boundary semantics ("EV", "+% edge").
    Live-commentary detector is case-insensitive substring.
    """
    if not text:
        return True, []

    hits: list[str] = []
    lowered = text.lower()

    for term in _BANNED_PLAIN:
        if term.lower() in lowered:
            hits.append(term)

    for label, pattern in _BANNED_PATTERNS:
        if pattern.search(text):
            hits.append(label)

    for term in LIVE_COMMENTARY_TERMS:
        if term.lower() in lowered:
            hits.append(term)

    return (not hits), hits


__all__ = [
    "PRIMARY_PRIORITY",
    "SECONDARY_PRIORITY",
    "PRIMARY_PHRASES",
    "SECONDARY_PHRASES",
    "BANNED_TERMS",
    "LIVE_COMMENTARY_TERMS",
    "EXPECTED_ACTION",
    "normalize_signals",
    "pick_primary",
    "pick_secondary",
    "build_action",
    "build_verdict",
    "validate_output",
]
