"""Deterministic verdict corpus — sport-banded, hand-authored.

BUILD-W82-CORPUS-EXPANSION-01 (2026-05-02). Replaces the 40-sentence flat
corpus from BUILD-W82-RIP-AND-REPLACE-01 with a sport-banded 360-sentence
corpus: 4 tiers × 3 sports × 30 sentences. Plus 25 concern prefixes.

The motivation: 10 sentences per tier in the flat corpus meant subscribers
saw the same Diamond verdict every ~10 Diamond cards, and "every signal
aligned" sentences could pair with concern prefixes that asserted the
opposite. This wave fixes both — bigger pool, sport-native voice, and a
``claims_completeness`` tag that filters out completeness assertions when
``has_real_risk(spec)`` fires.

Slots: ``{team}``, ``{odds}``, ``{bookmaker}`` only. Zero connectors,
zero risk-clause helpers, zero concessive logic. When ``has_real_risk``
is True, the concern prefix concatenates with a single space — no
linguistic bridge.

Voice rubric: ``.claude/skills/verdict-generator/SKILL.md`` (v2 Deterministic
Mode + Sport-Banded section). SA-native English. Conviction tier-appropriate.
Imperative close. 100-200 char range per sentence after slot-fill. Sport-native
vocabulary differentiates soccer / rugby / cricket.

Tag rules:
  - ``claims_completeness=True`` for sentences asserting full signal coverage
    ("every signal", "model and market both", "top to bottom", "the whole
    stack", "numbers and signals", "all aligned", "complete read").
  - ``claims_max_conviction=True`` is auto-derived from the sentence text with
    ``_MAX_CONVICTION_TOKENS``.

Filter rule: ``has_real_risk=True`` and tier is not Diamond -> pool is
restricted to sentences where both flags are False before a concern prefix is
prepended. Option A from FIX-VERDICT-CORPUS-ARCHITECTURE-HARDENING-01 keeps
Diamond exempt from concern prefixes, so Diamond keeps its max-conviction
closing language even when the risk heuristic fires.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

import verdict_engine_v2

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from narrative_spec import NarrativeSpec


_log = logging.getLogger(__name__)
log = logging.getLogger(__name__)
_USE_V2 = os.environ.get("VERDICT_ENGINE_V2", "1") not in ("0", "false", "False", "no", "")


# Legacy fallback only. V2 lives in verdict_engine_v2.
# render_verdict() routes to V2 when VERDICT_ENGINE_V2=1 (default).
# Corpus data structures below are reachable only when VERDICT_ENGINE_V2=0
# OR when V2 returns invalid/empty (defence-in-depth).
# Do not extend this corpus for new verdict work.


_V2_SIGNAL_ALIASES: dict[str, str] = {
    **verdict_engine_v2.ALIASES,
    "line_movement": "movement",
}
_V2_CANONICAL_SIGNALS = set(verdict_engine_v2.CANONICAL_SIGNALS)
_V2_ALLOWED_SIGNALS = _V2_CANONICAL_SIGNALS | set(_V2_SIGNAL_ALIASES)


def _text_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text_or_none(value)
        if text:
            return text
    return ""


_VERDICT_ACTION_TIER_FALLBACKS = {
    "strong back": "diamond",
    "back": "gold",
    "lean": "silver",
}
_VERDICT_TIERS = frozenset(("diamond", "gold", "silver", "bronze"))


def _tier_for_spec(spec: "NarrativeSpec") -> str:
    tier = _text_or_empty(getattr(spec, "edge_tier", "")).strip().lower()
    if tier in _VERDICT_TIERS:
        return tier

    action = _text_or_empty(getattr(spec, "verdict_action", "")).strip().lower()
    return _VERDICT_ACTION_TIER_FALLBACKS.get(action, "bronze")


def _odds_for_v2(value: Any) -> str | float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        return value
    raise TypeError(f"odds must be numeric, string, or None; got {type(value).__name__}")


def _odds_text_for_boundary(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value) <= 0:
            return None
        return f"{float(value):.2f}"
    text = str(value).strip()
    return text if text and text != "—" else None


def _int_or_none(value: Any, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int or None; got {type(value).__name__}")
    return value


def _list_attr_for_v2(spec: "NarrativeSpec", field_name: str) -> list[str]:
    value = getattr(spec, field_name, None)
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be list[str]; got {type(value).__name__}")
    return list(value)


def _mapping_or_none(value: Any, field_name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping or None; got {type(value).__name__}")
    return value


def _has_explicit_v2_context(spec: "NarrativeSpec") -> bool:
    raw_signals = getattr(spec, "signals", None)
    if isinstance(raw_signals, Mapping) and bool(raw_signals):
        return True

    for field_name in (
        "match_key",
        "edge_revision",
        "recommended_at",
        "evidence_pack",
        "home_form",
        "away_form",
        "h2h",
        "h2h_summary",
        "venue",
        "coach",
        "nickname",
        "bookmaker_count",
        "line_movement_direction",
        "tipster_sources_count",
    ):
        value = getattr(spec, field_name, None)
        if field_name in ("bookmaker_count", "tipster_sources_count") and value == 0:
            continue
        if value not in (None, "", [], {}):
            return True

    return False


def _signals_for_v2(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, Mapping):
        raise TypeError(f"signals must be a mapping; got {type(raw).__name__}")

    signals: dict[str, Any] = {key: False for key in verdict_engine_v2.CANONICAL_SIGNALS}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise TypeError(f"signals keys must be str; got {type(key).__name__}")
        if key not in _V2_ALLOWED_SIGNALS:
            raise ValueError(f"unexpected signal key: {key}")
        if not isinstance(value, (bool, Mapping)):
            raise TypeError(
                f"signals[{key!r}] must be bool or mapping; got {type(value).__name__}"
            )
        signals[_V2_SIGNAL_ALIASES.get(key, key)] = value
    return signals


def _recommended_team_for_v2(spec: "NarrativeSpec") -> str:
    return _first_text(
        getattr(spec, "recommended_team", None),
        getattr(spec, "outcome_label", None),
        getattr(spec, "home_name", None),
    )


def _coach_for_v2(spec: "NarrativeSpec", recommended_team: str) -> str | None:
    explicit = _text_or_none(getattr(spec, "coach", None))
    if explicit:
        return explicit

    recommended_norm = recommended_team.strip().lower()
    home = _text_or_empty(getattr(spec, "home_name", "")).strip().lower()
    away = _text_or_empty(getattr(spec, "away_name", "")).strip().lower()
    if recommended_norm and home and (recommended_norm == home or recommended_norm in home or home in recommended_norm):
        return _text_or_none(getattr(spec, "home_coach", None))
    if recommended_norm and away and (recommended_norm == away or recommended_norm in away or away in recommended_norm):
        return _text_or_none(getattr(spec, "away_coach", None))
    return None


def _spec_to_verdict_context(spec: "NarrativeSpec") -> verdict_engine_v2.VerdictContext:
    recommended_team = _recommended_team_for_v2(spec)
    explicit_match_key = _text_or_empty(getattr(spec, "match_key", "")).strip()
    reconstructed_match_key = "|".join(
        part
        for part in (
            _text_or_empty(getattr(spec, "home_name", "")).strip(),
            _text_or_empty(getattr(spec, "away_name", "")).strip(),
        )
        if part
    )
    match_key = explicit_match_key or reconstructed_match_key
    edge_revision = _first_text(
        getattr(spec, "edge_revision", None),
        getattr(spec, "recommended_at", None),
        match_key,
    )
    raw_native_signals = getattr(spec, "signals", {})
    if raw_native_signals:
        _signals_for_v2(raw_native_signals)
    raw_signals = _spec_to_signals(spec)
    values = {
        "match_key": match_key,
        "edge_revision": edge_revision,
        "sport": _text_or_empty(getattr(spec, "sport", "")),
        "league": _text_or_empty(getattr(spec, "league", getattr(spec, "competition", ""))),
        "home_name": _text_or_empty(getattr(spec, "home_name", "")),
        "away_name": _text_or_empty(getattr(spec, "away_name", "")),
        "recommended_team": recommended_team,
        "outcome_label": _text_or_empty(getattr(spec, "outcome_label", "")),
        "odds": _odds_for_v2(getattr(spec, "odds", None)),
        "bookmaker": _text_or_none(getattr(spec, "bookmaker", None)),
        "tier": _tier_for_spec(spec),
        "kickoff_utc": _text_or_none(getattr(spec, "kickoff_utc", None)),
        "signals": _signals_for_v2(raw_signals),
        "evidence_pack": _mapping_or_none(getattr(spec, "evidence_pack", None), "evidence_pack"),
        "home_form": _text_or_none(getattr(spec, "home_form", None)),
        "away_form": _text_or_none(getattr(spec, "away_form", None)),
        "h2h": _text_or_none(getattr(spec, "h2h", getattr(spec, "h2h_summary", None))),
        "injuries_home": _list_attr_for_v2(spec, "injuries_home"),
        "injuries_away": _list_attr_for_v2(spec, "injuries_away"),
        "venue": _text_or_none(getattr(spec, "venue", None)),
        "coach": _coach_for_v2(spec, recommended_team),
        "nickname": _text_or_none(getattr(spec, "nickname", None)),
        "bookmaker_count": _int_or_none(getattr(spec, "bookmaker_count", None), "bookmaker_count"),
        "line_movement_direction": _text_or_none(getattr(spec, "line_movement_direction", None)),
        "tipster_sources_count": _int_or_none(
            getattr(spec, "tipster_sources_count", None),
            "tipster_sources_count",
        ),
    }
    field_names = set(verdict_engine_v2.VerdictContext.__dataclass_fields__)
    return verdict_engine_v2.VerdictContext(
        **{key: value for key, value in values.items() if key in field_names}
    )


def _v2_render_boundary_miss(
    text: str,
    spec: "NarrativeSpec",
    ctx: verdict_engine_v2.VerdictContext,
) -> str | None:
    explicit_v2_context = _has_explicit_v2_context(spec)
    if not explicit_v2_context and len(text) < 100:
        return "below_min_verdict_quality"

    tier = _text_or_empty(getattr(ctx, "tier", None) or getattr(spec, "edge_tier", "")).lower()
    if tier == "diamond":
        diamond_tokens = [
            "hammer",
            "load up",
            "go in heavy",
            "lock in",
            "high-conviction",
            "heavy stake",
            "standard-to-heavy",
            "full confident stake",
        ]
        if explicit_v2_context:
            diamond_tokens.append("full stake")
        if not any(token in text.lower() for token in diamond_tokens):
            return "missing_diamond_conviction_language"

    odds = _odds_text_for_boundary(getattr(spec, "odds", None))
    if odds and odds not in text:
        return "missing_recommendation_odds"

    bookmaker = _text_or_none(getattr(spec, "bookmaker", None))
    if bookmaker and bookmaker.lower() not in text.lower():
        return "missing_recommendation_bookmaker"

    return None


def _log_v2_event(
    event: str,
    spec: "NarrativeSpec",
    *,
    reason: str,
    ctx: verdict_engine_v2.VerdictContext | None = None,
    result: verdict_engine_v2.VerdictResult | None = None,
    exc: Exception | None = None,
    level: int = logging.INFO,
) -> None:
    log.log(
        level,
        event,
        extra={
            "event": event,
            "match_key": getattr(ctx, "match_key", None) or getattr(spec, "match_key", "<missing>"),
            "edge_revision": getattr(ctx, "edge_revision", None) or getattr(spec, "edge_revision", None),
            "tier": getattr(ctx, "tier", None) or getattr(spec, "edge_tier", None),
            "reason": reason,
            "primary_fact_type": getattr(result, "primary_fact_type", None),
            "validation_errors": getattr(result, "validation_errors", ()),
            "error": repr(exc) if exc is not None else None,
        },
    )


# ── BUILD-VERDICT-SIGNAL-MAPPED-01 (2026-05-03) feature flag ────────────────
# When True (default), render_verdict routes through verdict_signal_mapper
# first and only falls back to the 360-sentence corpus when the mapper
# returns an empty body or fails the banned-term / live-commentary scanner.
# Set USE_SIGNAL_MAPPED_VERDICTS=0 (or "false") to force the legacy corpus
# path — used by HG-5 regression test for rollback safety.
def _signal_mapped_enabled() -> bool:
    raw = os.environ.get("USE_SIGNAL_MAPPED_VERDICTS")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _spec_to_signals(spec: "NarrativeSpec") -> dict[str, bool]:
    """Adapt NarrativeSpec → 6-signal boolean dict for the new builder.

    OPS-SPEC-SIGNAL-EXPOSURE-01 (2026-05-04): NarrativeSpec now carries a
    native ``signals: dict[str, bool]`` field populated from the canonical
    ``collect_all_signals`` output via ``_extract_edge_data``. When the
    native dict is non-empty we read availability natively (single source
    of truth shared with the card-image Edge Signal dots — HG-4) and
    apply polarity filters against spec fields. When the native dict is
    empty (un-migrated specs / live-tap path with no edge_v2 metadata),
    we fall through to the BUILD-VERDICT-SIGNAL-MAPPED-01 proxy adapter
    so the mapper never crashes on an empty spec.

    Polarity rules (applied in BOTH paths):
      - price_edge → ``ev_pct > 0`` AND ``signals.price_edge`` raw fires
        (the product's core value prop — always true on positive-EV main
        path; native source confirms availability).
      - line_mvt   → raw availability passes through; favourable/against
        routing is downstream via ``_spec_movement_direction``.
      - market     → raw availability is sufficient — multi-book consensus
        is the §12.6 contract.
      - tipster    → AND-gated on ``tipster_agrees is True`` so the mapper
        never emits "outside support points this way" against the pick.
      - form       → raw availability is sufficient — §12 form phrasing
        ("recent form backs this") works for either-team form data.
      - injury     → AND-gated on opponent-side injuries supplied by
        ``get_verified_injuries``; picked-side injuries surface via the
        concern-prefix path. Empty outcome (no clear pick side) suppresses
        — spec §6.6 phrasing is explicitly "the OTHER team weakened".

    HG-4 alignment: ``spec.signals`` (raw availability) and
    ``card_pipeline._compute_signals`` (also raw availability, dot-render
    contract) trace to the same upstream collect_all_signals output. The
    polarity filters here apply on top of that shared source.
    """
    outcome = (getattr(spec, "outcome", "") or "").lower()
    inj_home = list(getattr(spec, "injuries_home", []) or [])
    inj_away = list(getattr(spec, "injuries_away", []) or [])
    if outcome == "home":
        opponent_injuries = bool(inj_away)
    elif outcome == "away":
        opponent_injuries = bool(inj_home)
    else:
        opponent_injuries = False

    tipster_agrees = bool(getattr(spec, "tipster_available", False)) and (
        getattr(spec, "tipster_agrees", None) is True
    )

    raw = getattr(spec, "signals", None) or {}
    if isinstance(raw, dict) and raw:
        # ── Native path (OPS-SPEC-SIGNAL-EXPOSURE-01) ──────────────────
        # spec.signals carries the canonical collect_all_signals
        # availability shape (post _normalise_spec_signals). Apply the
        # polarity gates above on top so positive phrasing only fires
        # when the signal SUPPORTS the pick.
        ev_pct = float(getattr(spec, "ev_pct", 0) or 0)
        return {
            "price_edge": bool(raw.get("price_edge")) and ev_pct > 0,
            "line_mvt":   bool(raw.get("line_mvt")),
            "market":     bool(raw.get("market")),
            "tipster":    bool(raw.get("tipster")) and tipster_agrees,
            "form":       bool(raw.get("form")),
            "injury":     bool(raw.get("injury")) and opponent_injuries,
        }

    # ── Proxy fallback (BUILD-VERDICT-SIGNAL-MAPPED-01 path) ───────────
    # Activated when spec.signals is empty — un-migrated specs from live-
    # tap callers that bypass _extract_edge_data, contract tests that
    # construct NarrativeSpec directly, or any future producer that
    # forgets to populate the field. Fallback derives booleans from
    # discrete spec fields (movement_direction, bookmaker_count,
    # home_form/away_form, etc.) per the original adapter.
    movement = (getattr(spec, "movement_direction", "") or "").lower()
    line_mvt_active = movement in ("for", "against", "unknown", "favourable")
    bookmaker_count = int(getattr(spec, "bookmaker_count", 0) or 0)
    market_active = bookmaker_count >= 3
    home_form = (getattr(spec, "home_form", "") or "").strip()
    away_form = (getattr(spec, "away_form", "") or "").strip()
    form_active = bool(home_form or away_form)
    ev_pct = float(getattr(spec, "ev_pct", 0) or 0)
    price_edge_active = ev_pct > 0
    return {
        "price_edge": price_edge_active,
        "line_mvt":   line_mvt_active,
        "market":     market_active,
        "tipster":    tipster_agrees,
        "form":       form_active,
        "injury":     opponent_injuries,
    }


def _spec_movement_direction(spec: "NarrativeSpec") -> str:
    """Map spec movement → mapper's three-value contract.

    Mapper expects ``favourable`` / ``against`` / ``unknown``.

    OPS-SPEC-SIGNAL-EXPOSURE-01 (2026-05-04): prefer the native
    ``spec.line_movement_direction`` field (already in the 3-value
    contract per ``_normalise_line_movement_direction``). Fall back
    to mapping the legacy ``spec.movement_direction`` field
    (``for`` / ``against`` / ``neutral`` / ``unknown``) when the
    native field is unset — un-migrated specs and proxy-fallback path.

    FIX-VERDICT-VARIETY-PASS-5-LAND-01 (2026-05-05) Codex adversarial
    hardening: the native field is closed-default authoritative when
    set. Only the canonical 3 values (``favourable`` / ``for`` /
    ``against``) route through the directional path; every other native
    value (``unknown`` / ``neutral`` / ``none`` / ``n/a`` / any
    producer-specific sentinel) collapses to ``unknown`` WITHOUT
    consulting the legacy ``movement_direction`` fallback. This stops
    a producer who sets a non-canonical native sentinel but a stale
    legacy ``"for"`` from rendering a directional verdict on a fixture
    where the line-movement signal has not been positively established.
    Legacy ``movement_direction`` is consulted only when the native
    field is genuinely absent (None / empty / missing attribute).
    """
    native = getattr(spec, "line_movement_direction", None)
    if isinstance(native, str) and native.strip():
        text = native.strip().lower()
        if text == "favourable":
            return "favourable"
        if text == "for":
            # Native ``for`` aliases to ``favourable`` — matches
            # build_verdict's accepted directional set.
            return "favourable"
        if text == "against":
            return "against"
        # Native field is set but not canonical — closed default to
        # ``unknown``. Do NOT fall through to legacy when native is
        # explicitly populated; that would let stale legacy values
        # override an intentionally-non-directional native.
        return "unknown"
    # Native field absent (None / "" / whitespace / missing attribute):
    # consult the legacy mapping for un-migrated specs.
    movement = (getattr(spec, "movement_direction", "") or "").lower()
    if movement in ("for", "favourable"):
        return "favourable"
    if movement == "against":
        return "against"
    return "unknown"


# ── Tier composite-score floors ───────────────────────────────────────────
# Mirrors the canonical tier thresholds at services/edge_rating.py. Used by
# has_real_risk to flag a marginal-edge case (composite within 5 pts of floor).
TIER_FLOORS: dict[str, int] = {
    "diamond": 85,
    "gold": 70,
    "silver": 55,
    "bronze": 40,
}


# ── VerdictSentence dataclass ─────────────────────────────────────────────
@dataclass(frozen=True)
class VerdictSentence:
    """A single verdict template with structural contradiction tags.

    Attributes:
        text: the sentence with ``{team}``, ``{odds}``, ``{bookmaker}`` slots.
        claims_completeness: True when the sentence asserts full signal
            coverage (e.g. "every signal aligned", "model and market both").
        claims_max_conviction: True when the sentence text uses maximum-
            conviction betting language (e.g. "hammer", "load up", "max stake").

        Filter rule: when ``has_real_risk`` fires for Gold/Silver/Bronze, only
            sentences where both flags are False are eligible. This prevents
            the verdict body asserting completeness or maximum conviction while
            the concern prefix flags a real concern.
    """

    text: str
    claims_completeness: bool
    claims_max_conviction: bool


def _v(text: str, claims_completeness: bool) -> VerdictSentence:
    """Shorthand factory keeps the corpus literal compact."""
    return VerdictSentence(
        text=text,
        claims_completeness=claims_completeness,
        claims_max_conviction=bool(_MAX_CONVICTION_TOKENS.search(text)),
    )


_MAX_CONVICTION_TOKENS = re.compile(
    r"\b(hammer|load up|go in heavy|max stake|full confident stake|lock in|heavy stake|full stake)\b",
    re.IGNORECASE,
)


# ── Sport bucket normalisation ────────────────────────────────────────────
# Maps Core 7 sport keys (and their variants) to the three corpus buckets.
# Anything outside Core 7 falls back to "soccer" with a log warning — fixture
# blacklist keeps non-Core 7 leagues out of the verdict path in production,
# so this fallback never fires in steady state.
_SPORT_BUCKET_MAP: dict[str, str] = {
    # Soccer variants
    "soccer": "soccer",
    "football": "soccer",
    "epl": "soccer",
    "psl": "soccer",
    "ucl": "soccer",
    "champions_league": "soccer",
    "uefa_champions_league": "soccer",
    "premier_league": "soccer",
    "la_liga": "soccer",
    "bundesliga": "soccer",
    "serie_a": "soccer",
    "ligue_1": "soccer",
    # Rugby variants
    "rugby": "rugby",
    "urc": "rugby",
    "super_rugby": "rugby",
    "six_nations": "rugby",
    "rugby_championship": "rugby",
    "rugby_union": "rugby",
    "rugbyunion_six_nations": "rugby",
    # Cricket variants
    "cricket": "cricket",
    "ipl": "cricket",
    "cricket_ipl": "cricket",
    "sa20": "cricket",
    "cricket_test": "cricket",
    "csa_sa20": "cricket",
}


def _normalise_sport_to_bucket(sport_key: str) -> str:
    """Normalise a sport key to one of {"soccer", "rugby", "cricket"}.

    Default unknown sport → "soccer" (most common path in production), with
    a log-warn for visibility. Core 7 fixture_blacklist gates non-supported
    leagues out of the verdict path, so the fallback never fires in
    steady state.
    """
    key = (sport_key or "").lower().strip()
    if not key:
        return "soccer"
    bucket = _SPORT_BUCKET_MAP.get(key)
    if bucket is None:
        # Try permissive prefix match before falling back — handles things
        # like "soccer_premier_league" or sport keys with extra suffixes.
        for prefix, mapped in (
            ("soccer", "soccer"),
            ("football", "soccer"),
            ("rugby", "rugby"),
            ("cricket", "cricket"),
        ):
            if key.startswith(prefix):
                return mapped
        _log.warning(
            "verdict_corpus: unknown sport_key=%r, falling back to 'soccer'",
            sport_key,
        )
        return "soccer"
    return bucket


# ── Verdict corpus — 360 sentences (4 tiers × 3 sports × 30) ──────────────
#
# Tag rule reminder: claims_completeness=True when the sentence text contains
# ANY completeness-claim regex hit (every / all / whole / top to bottom /
# complete / model and market / numbers and signals) used as a coverage
# assertion. The contract test enforces tag consistency.
#
# Tier voice rubric (verdict-generator/SKILL.md):
#   Diamond — maximum conviction: hammer / load up / go in heavy / lock in
#   Gold    — strong:             back / get on / take / the call is / bet
#   Silver  — measured:           the play is / take / back
#   Bronze  — light:               worth a small play / worth a measured punt
#
# Sport-native vocabulary (illustrative, not exhaustive):
#   Soccer (EPL/PSL/UCL): backline, midfield press, set-piece, finishing edge,
#     away record, away day, home crowd, pressing intensity, transition speed,
#     defensive shape, finishing chances, full-back overlap, wing play,
#     deep-block, high line, front three, build-up, half-spaces, second balls,
#     low block, double pivot, target man, channels, throw-in routine.
#   Rugby (URC/Super Rugby/Six Nations): forward pack, set-piece dominance,
#     scrum platform, lineout, breakdown, kicking game, line-speed, tight five,
#     loose forwards, gainline, territory, possession, exit strategy, restart,
#     maul, ruck speed, half-back combination, back-three counter, blitz
#     defence, attacking shape, garryowen, contestable kick, jackler.
#   Cricket (IPL/SA20): powerplay, middle overs, death overs, spin attack,
#     pace battery, batting depth, top order, finishing kick, par score,
#     surface read, dew factor, swing, bounce, turn, six-hitting power,
#     run-rate, partnership, new-ball, slog overs, impact substitute, opener.

VERDICT_CORPUS: dict[str, dict[str, list[VerdictSentence]]] = {
    "diamond": {
        "soccer": [
            _v("Front three running riot, midfield press tightening the screw — hammer {team} at {odds} on {bookmaker}, full confident stake on the day.", False),
            _v("Backline air-tight, set-piece threat is real, finishing edge clinical — load up on {team} at {odds} with {bookmaker}, heavy stake from kickoff.", False),
            _v("Numbers, signals, and the price are all aligned cleanly — go in heavy on {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Pressing intensity tells the whole story on this fixture — hammer {team} at {odds} on {bookmaker}, full confident stake from kickoff.", True),
            _v("Top to bottom, the edge holds up across the read — lock in {team} at {odds} on {bookmaker}, max stake on the day.", True),
            _v("Away record holding strong, finishing edge sharp through the channels — bet {team} at {odds} with {bookmaker}, full confident stake on the day.", False),
            _v("Model and market both reading this fixture the same way — back {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Defensive shape is locked, transitions cutting straight through — hammer {team} at {odds} on {bookmaker}, heavy stake from kickoff.", False),
            _v("Set-piece threat is the killer dimension on this match — load up on {team} at {odds} with {bookmaker}, full stake on the day.", False),
            _v("Every signal we measure has this side ahead on the day — go in heavy on {team} at {odds} on {bookmaker}, full confident stake.", True),
            _v("Wide men in form, full-backs bombing forward, finishing clean — lock in {team} at {odds} on {bookmaker}, max stake on the day.", False),
            _v("Home crowd a real factor, midfield is the engine room here — hammer {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("The whole tactical stack is pulling the same direction here. Bet {team} at {odds} with {bookmaker}, full confident stake on the day.", True),
            _v("High line holding, pressing trap clinical, finishing third sharp — load up on {team} at {odds} with {bookmaker}, heavy stake from kickoff.", False),
            _v("Recent form, away record, and head-to-head all on side — back {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Build-up phase clinical, second balls dominated through midfield — hammer {team} at {odds} on {bookmaker}, max stake on the day.", False),
            _v("Top to bottom, this read holds firm across the lineup — go in heavy on {team} at {odds} on {bookmaker}, full confident stake from kickoff.", True),
            _v("Bookies have priced this one wrong on every market we track — load up on {team} at {odds} with {bookmaker}, heavy stake on the day.", True),
            _v("Pressing trap and finishing edge cutting through opposition shape — lock in {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("Numbers and signals both lining up the right way on this fixture — bet {team} at {odds} with {bookmaker}, full confident stake on the day.", True),
            _v("Counter-attacking shape, transition speed, finishing third clinical — hammer {team} at {odds} on {bookmaker}, heavy stake on the day.", False),
            _v("Set-piece dominance is the difference-maker on this fixture — back {team} at {odds} on {bookmaker}, full confident stake from kickoff.", False),
            _v("Diamond-grade signal stack with the price still on offer here — go in heavy on {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("Backline is unbreakable, finishing chances clinical through the day — load up on {team} at {odds} with {bookmaker}, max stake on the day.", False),
            _v("Every layer of the read points to this side winning today — hammer {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Wing play creating overloads, half-spaces wide open in attack — lock in {team} at {odds} on {bookmaker}, full confident stake from kickoff.", False),
            _v("Front three connecting cleanly, midfield pivot dictating tempo here — bet {team} at {odds} with {bookmaker}, heavy stake on the day.", False),
            _v("Top to bottom, the lineup is doing the heavy lifting on this one — load up on {team} at {odds} with {bookmaker}, full stake from kickoff.", True),
            _v("Pressing high, defensive line bold, finishing chances real on the day — hammer {team} at {odds} on {bookmaker}, full confident stake on the day.", False),
            _v("The whole tactical setup gives this side a clear edge today — go in heavy on {team} at {odds} on {bookmaker}, max stake on the day.", True),
        ],
        "rugby": [
            _v("Forward pack dominating the gainline, set-piece platform locked — hammer {team} at {odds} on {bookmaker}, full confident stake on the day.", False),
            _v("Tight five winning the collisions, breakdown speed is brutal — load up on {team} at {odds} with {bookmaker}, heavy stake from kickoff.", False),
            _v("Numbers, signals, and the price are all pointing the same way — go in heavy on {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Set-piece dominance tells the whole story on this fixture — hammer {team} at {odds} on {bookmaker}, full confident stake from kickoff.", True),
            _v("Top to bottom, the edge holds clean across the read here — lock in {team} at {odds} on {bookmaker}, max stake on the day.", True),
            _v("Lineout firing, scrum platform stable, kicking game tactical — bet {team} at {odds} with {bookmaker}, full confident stake on the day.", False),
            _v("Model and market both reading the forward battle the same — back {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Blitz defence is suffocating, line-speed is brutal at gainline — hammer {team} at {odds} on {bookmaker}, heavy stake from kickoff.", False),
            _v("Back-three counter is the killer dimension on this fixture — load up on {team} at {odds} with {bookmaker}, full stake on the day.", False),
            _v("Every signal across the forward and back unit is on side — go in heavy on {team} at {odds} on {bookmaker}, full confident stake.", True),
            _v("Half-back combination clicking, exit strategy is clinical here — lock in {team} at {odds} on {bookmaker}, max stake on the day.", False),
            _v("Home stadium gives them territorial control, kicking game tactical — hammer {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("The whole pack is doing the work for this attacking shape. Bet {team} at {odds} with {bookmaker}, full confident stake on the day.", True),
            _v("Loose forwards dominant at the breakdown, ruck speed is fast — load up on {team} at {odds} with {bookmaker}, heavy stake from kickoff.", False),
            _v("Recent form, set-piece numbers, and head-to-head all on side — back {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Maul control suffocating opposition exits, pressure relentless — hammer {team} at {odds} on {bookmaker}, max stake on the day.", False),
            _v("Top to bottom, this read holds firm across the matchday squad — go in heavy on {team} at {odds} on {bookmaker}, full confident stake from kickoff.", True),
            _v("Bookies have got this priced wrong on every line we track here — load up on {team} at {odds} with {bookmaker}, heavy stake on the day.", True),
            _v("Scrum platform feeding the half-backs clean ball at the base — lock in {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("Numbers and signals both lining up behind this side cleanly — bet {team} at {odds} with {bookmaker}, full confident stake on the day.", True),
            _v("Territory and possession game both controlled, kicking sharp — hammer {team} at {odds} on {bookmaker}, heavy stake on the day.", False),
            _v("Set-piece dominance is the difference-maker on this fixture — back {team} at {odds} on {bookmaker}, full confident stake from kickoff.", False),
            _v("Diamond-grade signal stack with the price still showing here — go in heavy on {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("Tight five locked, lineout firing, forward platform brutal here — load up on {team} at {odds} with {bookmaker}, max stake on the day.", False),
            _v("Every layer of the read backs this side getting the win today — hammer {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Back row dominance at breakdown, jackler ruling the contest — lock in {team} at {odds} on {bookmaker}, full confident stake from kickoff.", False),
            _v("Flyhalf controlling tempo, contestable kicks pinning opposition deep — bet {team} at {odds} with {bookmaker}, heavy stake on the day.", False),
            _v("Top to bottom, the matchday squad is doing the work here — load up on {team} at {odds} with {bookmaker}, full stake from kickoff.", True),
            _v("Aerial battle controlled, restarts won, set-piece platform real — hammer {team} at {odds} on {bookmaker}, full confident stake on the day.", False),
            _v("The whole forward unit gives this side a clear edge on the day — go in heavy on {team} at {odds} on {bookmaker}, max stake on the day.", True),
        ],
        "cricket": [
            _v("Powerplay openers in form, top order striking with intent — hammer {team} at {odds} on {bookmaker}, full confident stake on the day.", False),
            _v("Pace battery sharp, spin attack on a turning surface — load up on {team} at {odds} with {bookmaker}, heavy stake from kickoff.", False),
            _v("Numbers, signals, and the price are all aligned cleanly here — go in heavy on {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Batting depth tells the whole story on this fixture today — hammer {team} at {odds} on {bookmaker}, full confident stake from kickoff.", True),
            _v("Top to bottom, the edge holds clean across the squad selection — lock in {team} at {odds} on {bookmaker}, max stake on the day.", True),
            _v("Death overs specialists ready, finishing kick locked at the back end — bet {team} at {odds} with {bookmaker}, full confident stake on the day.", False),
            _v("Model and market both reading the surface the same way here — back {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Six-hitting power through the middle order, spin a real weapon — hammer {team} at {odds} on {bookmaker}, heavy stake from kickoff.", False),
            _v("Surface read favouring spin is the killer dimension here today — load up on {team} at {odds} with {bookmaker}, full stake on the day.", False),
            _v("Every signal across batting and bowling is on side today — go in heavy on {team} at {odds} on {bookmaker}, full confident stake.", True),
            _v("New-ball pair sharp, swing and seam through the powerplay overs — lock in {team} at {odds} on {bookmaker}, max stake on the day.", False),
            _v("Home conditions a real factor, dew factor adds another angle — hammer {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("The whole batting card stacks up cleanly behind this side. Bet {team} at {odds} with {bookmaker}, full confident stake on the day.", True),
            _v("Pacers extracting bounce, partnership-building through middle overs — load up on {team} at {odds} with {bookmaker}, heavy stake from kickoff.", False),
            _v("Recent form, par score read, and head-to-head all on side — back {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Run-rate control tight, slog-overs hitters loaded for the back end — hammer {team} at {odds} on {bookmaker}, max stake on the day.", False),
            _v("Top to bottom, this batting line-up is the deeper of the two — go in heavy on {team} at {odds} on {bookmaker}, full confident stake from kickoff.", True),
            _v("Bookies have priced this wrong on every market we cover today — load up on {team} at {odds} with {bookmaker}, heavy stake on the day.", True),
            _v("Spin attack on a low-bounce track, batters comfortable with turn — lock in {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("Numbers and signals both lining up clean behind this team today — bet {team} at {odds} with {bookmaker}, full confident stake on the day.", True),
            _v("Powerplay six-hitting and middle-overs anchor both stacked here — hammer {team} at {odds} on {bookmaker}, heavy stake on the day.", False),
            _v("Death-over yorkers and slower balls are the difference today — back {team} at {odds} on {bookmaker}, full confident stake from kickoff.", False),
            _v("Diamond-grade signal stack with the price still on offer here — go in heavy on {team} at {odds} on {bookmaker}, full stake from kickoff.", False),
            _v("Top order anchored, finishers loaded, par score read clean — load up on {team} at {odds} with {bookmaker}, max stake on the day.", False),
            _v("Every layer of the squad read backs this side winning today — hammer {team} at {odds} on {bookmaker}, full stake on the day.", True),
            _v("Impact substitute changing the dynamic, batting depth deeper — lock in {team} at {odds} on {bookmaker}, full confident stake from kickoff.", False),
            _v("Wicket conditions favour their pace battery, swing on offer — bet {team} at {odds} with {bookmaker}, heavy stake on the day.", False),
            _v("Top to bottom, the squad selection has the right mix today — load up on {team} at {odds} with {bookmaker}, full stake from kickoff.", True),
            _v("Spin and pace combination matched to surface, partnerships set — hammer {team} at {odds} on {bookmaker}, full confident stake on the day.", False),
            _v("The whole batting and bowling unit gives them a clear edge today — go in heavy on {team} at {odds} on {bookmaker}, max stake on the day.", True),
        ],
    },
    "gold": {
        "soccer": [
            _v("Backline holding shape, midfield press doing the dirty work — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Front three connecting cleanly, finishing edge sharp on the day — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The model has a clear preference, and the price reflects fair value — back {team} at {odds} with {bookmaker}, standard stake.", False),
            _v("Set-piece threat is real, away record holding up well — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The call is straightforward when the read holds together like this — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Numbers and signals both nodding the same direction here — get on {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Wing play creating overloads, full-back overlaps cutting through — take {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Pressing intensity high, transitions clinical at both ends today — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The market is offering value where the model has conviction here — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Gold-grade read with clean signal support behind it on the day — get on {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Build-up phase composed, second balls won through midfield clean — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Half-spaces wide open, finishing third clinical against deep-block — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Confirming signals stacked on the right side cleanly today — back {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Defensive shape solid, double pivot dictating tempo from deep — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, the read favours this side getting the result — bet {team} at {odds} with {bookmaker}, standard stake on the day.", True),
            _v("Counter-attacking threat real, transition speed cutting through — take {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Recent form, away record, and head-to-head all read the same — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Set-piece dominance and finishing chances both stacking up here — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The call is straightforward when the signals read this clean today — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Model and market both reading this fixture clearly the same way — take {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Pressing trap working, finishing third clinical through channels — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("High line holding firm, pressing intensity squeezing the opposition — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The whole midfield is dictating, double pivot doing the work today — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Wide men in form, finishing chances clean through the day — take {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Solid edge on this fixture, supporting signals doing their job today — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Numbers tell the story, the price is offering fair value — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Front three connecting through half-spaces, build-up clean — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Home crowd a real factor, transitions cutting clean on the break — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("The price is fair to slightly generous on a confirmed read here — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, the lineup looks the more balanced of the two sides — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", True),
        ],
        "rugby": [
            _v("Forward pack winning the collisions, set-piece platform stable — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Lineout firing, scrum platform giving clean ball at the base — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The model has a clear preference, and the price reflects fair value — back {team} at {odds} with {bookmaker}, standard stake.", False),
            _v("Breakdown speed is sharp, gainline contest going their way — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The call is straightforward when the forward battle reads like this — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Numbers and signals both nodding the same way on this fixture — get on {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Half-back combination clicking, exit strategy is clean today — take {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Blitz defence aggressive, line-speed shutting down attacking shape — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The market is offering value where the read has conviction here — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Gold-grade read with the forward platform doing the work today — get on {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Maul control giving territory, kicking game tactical and tight — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Loose forwards busy at breakdown, ruck speed quick on attack — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Confirming signals stacked on the right side cleanly today — back {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Tight five locked, lineout dominance giving clean platform — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, the matchday squad reads stronger on this fixture — bet {team} at {odds} with {bookmaker}, standard stake on the day.", True),
            _v("Back-three counter dangerous, kicking game tactical and tight — take {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Recent form, set-piece numbers, and head-to-head all on side — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Forward pack and back-three counter both stacking up here — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The call is straightforward when the breakdown reads this clean — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Model and market both reading the forward battle the same way — take {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Choke tackle clinical, jackler dominant at every breakdown — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Aerial contest controlled, restart receipt clean through the day — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The whole forward platform is dictating tempo through phases — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Flyhalf controlling tempo, contestable kicks pinning opposition deep — take {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Solid edge on this fixture, supporting signals doing their job — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Numbers tell the story, the price is offering fair value here — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Scrum platform stable, set-piece dominance forcing penalties — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Home stadium giving territorial control, kicking sharp on exits — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("The price is fair to slightly generous on a confirmed read here — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, the matchday 23 looks the deeper of the two squads — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", True),
        ],
        "cricket": [
            _v("Top order in form, powerplay six-hitting power on the day — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Pace battery sharp, swing on offer through the new-ball overs — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The model has a clear preference, and the price reflects fair value — back {team} at {odds} with {bookmaker}, standard stake.", False),
            _v("Spin attack reading the surface, batting depth deeper today — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The call is straightforward when the surface read holds like this today — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Numbers and signals both nodding the same way on this fixture — get on {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Death-overs specialists loaded, finishing kick clean at the back end — take {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Middle-overs anchor steady, partnership-building through the spin — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The market is offering value where the read has conviction here — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Gold-grade read with batting depth doing the work today — get on {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Pacers extracting bounce, swing through the powerplay phase — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Slog-overs hitters loaded, run-rate control through middle overs — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Confirming signals stacked on the right side cleanly today — back {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("New-ball pair clinical, top order anchored through powerplay — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, this batting card looks the deeper today — bet {team} at {odds} with {bookmaker}, standard stake on the day.", True),
            _v("Spin attack on a low-bounce track, batters reading turn well — take {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Recent form, par score read, and head-to-head all read the same — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Six-hitting power and pace battery both stacking up cleanly here — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The call is straightforward when the surface read is this clean today — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Model and market both reading the par score the same way today — take {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Death-over yorkers and slower balls are the difference here — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Spin a real weapon on this surface, batters playing the angle — get on {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("The whole batting unit looks deeper across the order — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Impact substitute changing the dynamic at the back end — take {team} at {odds} with {bookmaker}, standard stake from kickoff.", False),
            _v("Solid edge on this fixture, supporting signals doing their job here — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Numbers tell the story, the price is offering fair value today — bet {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Wicket conditions favouring pace, batters needing to rebuild — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Home conditions a real factor, dew factor changing things later — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("The price is fair to slightly generous on a confirmed read here — get on {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, the squad selection has the right balance today — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", True),
        ],
    },
    "silver": {
        "soccer": [
            _v("Backline solid enough, midfield press tilting things this way — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Front three connecting in patches, finishing edge present — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The edge is real and the conviction stays measured today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Set-piece threat present, away record reasonable on the day — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Numbers tilt this way on a clean enough read of the fixture — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("The model has a preference and the market is offering it here — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The signals support the call, but the gap is not enormous today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Moderate edge with reasonable signal coverage on the read — the play is {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Worth the standard exposure on a measured read of this fixture — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Silver-grade signal with the price holding up through kickoff — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Pressing intensity tilting things, transitions clean on counter — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Half-spaces opening, full-back overlaps creating openings — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Defensive shape decent, double pivot doing reasonable work today — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Recent form on side, away record solid enough today — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Numbers and signals both leaning this direction today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", True),
            _v("Front three in form, finishing edge sharp through patches — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Counter-attacking threat real, transition speed cutting through — the play is {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Build-up phase composed enough, second balls won in patches — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Set-piece threat and finishing chances both leaning this way — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, the lineup looks slightly more balanced today — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Pressing trap working in patches, finishing third reasonable — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Wing play creating openings, half-spaces opening today — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Home crowd a factor, transitions cutting clean on the break — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Solid measured read with supporting signals on the right side — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Decent value with supporting signals on the right side here — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Pressing intensity decent, defensive line holding shape today — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("High line bold, transitions cutting through opposition shape — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Wide men in form, build-up phase composed through midfield — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Set-piece dominance present, finishing edge on side here — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Every supporting signal is leaning this direction today — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", True),
        ],
        "rugby": [
            _v("Forward pack winning patches, set-piece reasonable on the day — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Lineout firing in patches, scrum platform decent at the base — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The edge is real and the conviction stays measured today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Breakdown speed sharp enough, gainline contest tilting their way — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Numbers tilt this way on a clean enough read of the forward battle — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("The model has a preference and the market is offering it here — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Signals support the call, but the gap is not enormous today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Moderate edge with reasonable signal coverage on the read — the play is {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Worth the standard exposure on a measured read of this fixture — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Silver-grade signal with the price holding up through kickoff — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Half-back combination working in patches, exits decent today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Blitz defence reasonable, line-speed shutting down patches — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Maul control patchy, kicking game tactical enough today — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Recent form on side, set-piece reasonable on this fixture — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Numbers and signals both leaning this direction on the day — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", True),
            _v("Loose forwards busy at breakdown, ruck speed reasonable today — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Back-three counter dangerous in patches, kicks tactical — the play is {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Tight five working through phases, lineout reasonable today — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Forward platform and back-three counter both leaning this way — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, the matchday 23 looks slightly the more balanced — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Maul control patchy, choke tackle reasonable through phases — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Aerial battle decent, restart receipt reasonable today — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Home stadium a factor, kicking game pinning opposition exits — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Solid measured read with supporting signals on the right side — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Decent value with supporting signals on the right side here — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Breakdown speed reasonable, jackler busy in patches today — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Flyhalf controlling tempo, contestable kicks decent enough — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Set-piece dominance present in patches, scrum reasonable — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Forward pack winning patches, gainline contest decent — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Every supporting signal is leaning this direction today — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", True),
        ],
        "cricket": [
            _v("Top order in form in patches, powerplay reasonable today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Pace battery sharp enough, swing through the new-ball overs — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("The edge is real and the conviction stays measured today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Spin attack reading the surface, batting depth reasonable today — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Numbers tilt this way on a clean enough read of the surface — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("The model has a preference and the market is offering it here — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Signals support the call, but the gap is not enormous today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Moderate edge with reasonable signal coverage on the read — the play is {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Worth the standard exposure on a measured read of this fixture — back {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Silver-grade signal with the price holding up through kickoff — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Death-overs specialists ready in patches, finishing reasonable — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Middle-overs anchor steady enough, partnership-building decent — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Pacers extracting bounce, swing through powerplay decent — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Recent form on side, par score read reasonable today — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Numbers and signals both leaning this direction on the day — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", True),
            _v("Slog-overs hitters loaded, run-rate control reasonable today — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("New-ball pair sharp enough, top order anchored through patches — the play is {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Spin attack on this surface, batters reading turn reasonably — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Six-hitting power and pace battery both leaning this way today — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Top to bottom, this batting card looks slightly deeper today — back {team} at {odds} on {bookmaker}, standard stake on the day.", True),
            _v("Death-over yorkers reasonable, slower balls effective in patches — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Spin a weapon on this surface, partnership-building decent — take {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Home conditions a factor, dew factor changing things later — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Solid measured read with supporting signals on the right side — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Decent value with supporting signals on the right side here — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Wicket conditions favouring pace, batters needing patience — back {team} at {odds} on {bookmaker}, standard stake on the day.", False),
            _v("Impact substitute changing the dynamic at the back end — take {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Powerplay six-hitting reasonable, middle overs steady today — the play is {team} at {odds} with {bookmaker}, standard stake on the day.", False),
            _v("Top order anchored, finishers loaded for the back end — back {team} at {odds} on {bookmaker}, standard stake from kickoff.", False),
            _v("Every supporting signal is leaning this direction today — the play is {team} at {odds} on {bookmaker}, standard stake on the day.", True),
        ],
    },
    "bronze": {
        "soccer": [
            _v("Light edge with supporting signals on the thinner side here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Numbers nudge this way without much weight behind them today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Modest read with limited supporting evidence on the day here — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Bronze-tier signal — real edge but the conviction is thin today — worth a small play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Marginal value where the model has only a slight preference here — worth a measured punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Light support and a price that justifies a small position only today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Edge exists, but conviction stays modest at this tier today here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Signal is there in muted form, not screaming the play out today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Modest read on a fixture with enough value to justify exposure here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Thin but real edge on the day with the price still on offer — worth a measured punt on {team} at {odds} on {bookmaker}, light stake from kickoff.", False),
            _v("Backline holds in patches, midfield not pressing hard enough today — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Front three connecting in flashes, finishing edge thin today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Set-piece threat present in flashes, away record passable here — worth a small punt on {team} at {odds} with {bookmaker}, light stake from kickoff.", False),
            _v("Pressing intensity flashes, transitions clean in patches today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Wing play creating chances in flashes, finishing third thin — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Recent form patchy on both sides, light edge here today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake on the day.", False),
            _v("Numbers and signals both leaning slightly this way only — worth a small play on {team} at {odds} with {bookmaker}, light stake.", True),
            _v("Counter-attacking threat in flashes, transition speed thin today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Build-up phase okay in patches, second balls won occasionally — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Half-spaces opening occasionally, finishing chances limited today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("High line risky in patches, pressing trap working occasionally — worth a small play on {team} at {odds} with {bookmaker}, light stake from kickoff.", False),
            _v("Defensive shape okay, double pivot doing patchy work today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Wide men in flashes, build-up phase patchy through midfield — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Pressing trap working occasionally, finishing third inconsistent — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Set-piece dominance patchy, finishing edge thin on this read — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Home crowd a small factor, transitions occasionally clean today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Top to bottom, this lineup looks marginally the more balanced — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", True),
            _v("Front three patchy, finishing chances thin through the day — worth a measured punt on {team} at {odds} on {bookmaker}, light stake from kickoff.", False),
            _v("Pressing intensity occasional, defensive line holding in patches — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Build-up phase composed in flashes, second balls won occasionally — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
        ],
        "rugby": [
            _v("Light edge with supporting signals on the thinner side here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Numbers nudge this way without much weight behind them today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Modest read with limited supporting evidence on the day here — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Bronze-tier signal — real edge but the conviction is thin today — worth a small play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Marginal value where the model has only a slight preference here — worth a measured punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Light support and a price that justifies a small position only today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Edge exists, but conviction stays modest at this tier today here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Signal is there in muted form, not screaming the play out today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Modest read on a fixture with enough value to justify exposure here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Thin but real edge on the day with the price still on offer — worth a measured punt on {team} at {odds} on {bookmaker}, light stake from kickoff.", False),
            _v("Forward pack winning patches, set-piece platform passable today — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Lineout firing in flashes, scrum platform patchy at the base — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Breakdown speed sharp in flashes, gainline contest patchy today — worth a small punt on {team} at {odds} with {bookmaker}, light stake from kickoff.", False),
            _v("Half-back combination patchy in flashes, exits inconsistent — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Blitz defence working occasionally, line-speed inconsistent — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Recent form on this fixture passable, light edge today here — worth a measured punt on {team} at {odds} on {bookmaker}, light stake on the day.", False),
            _v("Numbers and signals both leaning slightly this way only today — worth a small play on {team} at {odds} with {bookmaker}, light stake.", True),
            _v("Maul control patchy, kicking game tactical in flashes today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Loose forwards busy in patches, ruck speed inconsistent — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Back-three counter dangerous in flashes, kicks tactical — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Tight five working in patches, lineout reasonable today here — worth a small play on {team} at {odds} with {bookmaker}, light stake from kickoff.", False),
            _v("Forward platform patchy, back-three counter inconsistent today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Aerial battle patchy, restart receipt inconsistent through phases — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Choke tackle working occasionally, jackler patchy at breakdown — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Set-piece dominance patchy, scrum platform inconsistent today — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Home stadium a small factor, kicking patchy through exits today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Top to bottom, the matchday 23 looks marginally the more balanced — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", True),
            _v("Flyhalf patchy in tempo, contestable kicks landing occasionally — worth a measured punt on {team} at {odds} on {bookmaker}, light stake from kickoff.", False),
            _v("Breakdown speed inconsistent, gainline contest patchy through phases — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Forward pack winning patches, set-piece platform passable today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
        ],
        "cricket": [
            _v("Light edge with supporting signals on the thinner side here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Numbers nudge this way without much weight behind them today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Modest read with limited supporting evidence on the day here — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Bronze-tier signal — real edge but the conviction is thin today — worth a small play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Marginal value where the model has only a slight preference here — worth a measured punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Light support and a price that justifies a small position only today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Edge exists, but conviction stays modest at this tier today here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Signal is there in muted form, not screaming the play out today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Modest read on a fixture with enough value to justify exposure here — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Thin but real edge on the day with the price still on offer — worth a measured punt on {team} at {odds} on {bookmaker}, light stake from kickoff.", False),
            _v("Top order in flashes, powerplay six-hitting power patchy today — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Pace battery sharp in flashes, swing through new-ball patchy — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Spin attack reading the surface in patches, batting depth ok — worth a small punt on {team} at {odds} with {bookmaker}, light stake from kickoff.", False),
            _v("Death-overs specialists patchy, finishing kick inconsistent today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Middle-overs anchor patchy, partnership-building inconsistent — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Recent form passable on this fixture, light edge today here — worth a measured punt on {team} at {odds} on {bookmaker}, light stake on the day.", False),
            _v("Numbers and signals both leaning slightly this way only today — worth a small play on {team} at {odds} with {bookmaker}, light stake.", True),
            _v("Pacers extracting bounce in flashes, swing through powerplay patchy — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Slog-overs hitters patchy, run-rate control inconsistent today — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("New-ball pair patchy, top order anchored in flashes today — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Spin attack on this surface, batters reading turn in flashes — worth a small play on {team} at {odds} with {bookmaker}, light stake from kickoff.", False),
            _v("Six-hitting power patchy, pace battery inconsistent today — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Death-over yorkers patchy, slower balls effective in flashes — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Spin a weapon on this surface, partnership-building patchy here — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Wicket conditions slightly favouring pace, batters needing time — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Home conditions a small factor, dew factor changing things later — worth a measured play on {team} at {odds} on {bookmaker}, light stake.", False),
            _v("Top to bottom, this batting card looks marginally the deeper today — worth a small punt on {team} at {odds} with {bookmaker}, light stake.", True),
            _v("Impact substitute changing dynamic in flashes at the back end — worth a measured punt on {team} at {odds} on {bookmaker}, light stake from kickoff.", False),
            _v("Powerplay six-hitting patchy, middle overs steady in flashes — worth a small play on {team} at {odds} with {bookmaker}, light stake.", False),
            _v("Top order anchored in patches, finishers loaded for the back end — worth a measured punt on {team} at {odds} on {bookmaker}, light stake.", False),
        ],
    },
}


# ── Concern prefixes — 25 sentences (15 sport-agnostic + 10 sport-flavoured)
# Used only when has_real_risk(spec) is True for Gold/Silver/Bronze. Concatenated
# to verdict body with a single space, no linguistic bridge. The verdict body
# still starts with a capital letter — the reader's brain treats prefix + body
# as two separate beats: "here's the concern" then "here's the call".
#
# FIX-VERDICT-CORPUS-ARCHITECTURE-HARDENING-01: keep the exact prefix text, but
# bucket by sport so cricket/rugby/soccer vocabulary cannot leak across sports.
_CONCERN_PREFIX_TEXTS: list[str] = [
    # 15 sport-agnostic
    "Form is choppy on both sides.",
    "The injury report carries late risk.",
    "Late market money is leaning the other way.",
    "Recent head-to-head doesn't favour this read.",
    "Lineup news could shift the picture before kickoff.",
    "The price has tightened off our entry point.",
    "Conditions on the day add an extra variable.",
    "Squad rotation risk is in play here.",
    "The supporting signal stack is on the lighter side.",
    "There is a contradicting indicator to keep in mind.",
    "Recent form has been patchy on both sides of the fixture.",
    "Sharp money has been leaning the other direction late.",
    "The composite read is closer to the tier floor than usual.",
    "Travel and turnaround add a small variable to this fixture.",
    "Confirming signals are on the thin side of comfort here.",
    # 10 sport-flavoured (sport-agnostic-safe — no tier claims, no slot placeholders)
    "The away record gives pause on this fixture.",       # soccer-flavoured
    "Set-piece concession trends add a small risk.",      # soccer/rugby
    "The breakdown battle is unpredictable on the day.",  # rugby
    "The forward platform could swing either way today.", # rugby
    "The surface might play differently than expected.",  # cricket
    "Dew factor and toss could shift the picture late.",  # cricket
    "The opposition has a recent run of clean sheets.",   # soccer
    "Aerial duels and territorial control are tight.",    # rugby
    "Wicket conditions are an unknown until the start.",  # cricket
    "Squad fitness across the matchday list is borderline.",  # all
]

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


def _classify_concern_prefixes(prefixes: list[str]) -> dict[str, list[str]]:
    """Classify existing concern prefixes into sport buckets by vocabulary."""
    buckets: dict[str, list[str]] = {"soccer": [], "rugby": [], "cricket": []}
    for prefix in prefixes:
        matched: list[str] = []
        if _SOCCER_PREFIX_MARKERS.search(prefix):
            matched.append("soccer")
        if _RUGBY_PREFIX_MARKERS.search(prefix):
            matched.append("rugby")
        if _CRICKET_PREFIX_MARKERS.search(prefix):
            matched.append("cricket")

        if not matched:
            matched = ["soccer", "rugby", "cricket"]

        for sport in matched:
            buckets[sport].append(prefix)
    return buckets


CONCERN_PREFIXES: dict[str, list[str]] = _classify_concern_prefixes(_CONCERN_PREFIX_TEXTS)


# ── has_real_risk — deterministic risk flag ───────────────────────────────
def has_real_risk(spec: "NarrativeSpec") -> bool:
    """Return True when the spec carries concrete contradicting evidence.

    Deterministic, no LLM. True when ANY of:
      1. lineup_injury contradicting (pick side has a non-empty injuries list)
      2. line_movement contradicting (spec.movement_direction == "against")
      3. composite_score within 5 points of the tier floor
      4. confirming_count == 0 (no supporting signals)
      5. contradicting_count >= 2

    All field reads are best-effort — missing or malformed attributes never
    raise. Returns False when the spec is unrecognisable so the call site
    falls back to the unprefixed verdict body.
    """
    # 1. Lineup injuries on the picked side
    outcome = (getattr(spec, "outcome", "") or "").lower()
    injuries_home = list(getattr(spec, "injuries_home", []) or [])
    injuries_away = list(getattr(spec, "injuries_away", []) or [])
    if outcome == "home" and injuries_home:
        return True
    if outcome == "away" and injuries_away:
        return True

    # 2. Line movement against the pick
    if (getattr(spec, "movement_direction", "") or "").lower() == "against":
        return True

    # 3. Composite within 5 pts of tier floor (marginal edge)
    tier = (getattr(spec, "edge_tier", "") or "").lower()
    floor = TIER_FLOORS.get(tier, 0)
    composite = float(getattr(spec, "composite_score", 0) or 0)
    if floor > 0 and composite < floor + 5:
        return True

    # 4. Zero confirming signals
    if int(getattr(spec, "support_level", 0) or 0) == 0:
        return True

    # 5. Two or more contradicting signals
    if int(getattr(spec, "contradicting_signals", 0) or 0) >= 2:
        return True

    return False


# ── Hash-picker — deterministic across reads of the same edge ─────────────
def _pick(items: list, match_key: str, salt: str) -> object:
    """Hash-pick an element from ``items`` by ``(match_key, salt)``.

    Uses MD5 for stable cross-process determinism. Same ``(match_key, salt)``
    always returns the same element; different keys spread across the pool.

    The salt is typically ``f"{tier}|{sport}"`` for verdict-body picks and
    ``f"{tier}|{sport}|prefix"`` for concern-prefix picks — keeping the two
    pickers independent so a fixture's prefix and verdict don't co-correlate.
    """
    seed = f"{match_key}|{salt}".encode("utf-8")
    h = hashlib.md5(seed).hexdigest()
    return items[int(h, 16) % len(items)]


def _pick_concern_prefix(sport: str, match_key: str, salt: str = "prefix") -> str:
    """Pick a concern prefix from the normalised sport bucket only."""
    sport_bucket = _normalise_sport_to_bucket(sport)
    return _pick(CONCERN_PREFIXES[sport_bucket], match_key, f"{sport_bucket}|{salt}")  # type: ignore[return-value]


# ── render_verdict — sport-banded slot-fill + optional concern prefix ─────
def render_verdict(spec: "NarrativeSpec") -> str:
    """Render the deterministic verdict for ``spec``.

    BUILD-VERDICT-SIGNAL-MAPPED-01 (2026-05-03): Main path is now the
    signal-mapped builder in ``verdict_signal_mapper.build_verdict``,
    which grounds the verdict in the active card signals (Price Edge /
    Line Mvt / Market / Tipster / Form / Injury) per the spec locked
    in Notion ``355d9048d73c81f4a9b2ce69a63c7f27``. The 360-sentence
    sport-banded corpus below is preserved as the fallback safety net
    — it serves when the new builder returns an empty string OR when
    the banned-term / live-commentary scanner fires on the new
    builder's output. Feature flag ``USE_SIGNAL_MAPPED_VERDICTS`` (env
    or settings) toggles this; default True. Set to ``0`` / ``false``
    to force the legacy corpus path (HG-5 rollback regression).

    Legacy fallback path (still active):

    Reads ``spec.edge_tier`` to select the corpus tier and ``spec.sport``
    to select the sport bucket. Hash-picks a sentence by
    ``(spec.match_key, tier, sport)``. Slot-fills ``{team}``, ``{odds}``,
    ``{bookmaker}``. Prepends a concern prefix (separator: single space)
    when ``has_real_risk(spec)`` is True for Gold/Silver/Bronze — and when the
    concern fires, the sentence pool is filtered to
    ``claims_completeness=False`` and ``claims_max_conviction=False`` to
    prevent contradiction with the prefix. Diamond is intentionally exempt
    from concern prefixes per Option A in
    FIX-VERDICT-CORPUS-ARCHITECTURE-HARDENING-01.

    Returns the bare body when the spec is mid-renderer and a slot would
    otherwise resolve to empty (defensive — slot fills are always non-empty
    in production paths). Empty edge_tier falls back to a ``verdict_action``
    → tier mapping (strong back→diamond, back→gold, lean→silver, else bronze)
    so legacy callers that build a NarrativeSpec without populating
    ``edge_tier`` still get a tier-appropriate verdict.
    """
    if _USE_V2:
        ctx: verdict_engine_v2.VerdictContext | None = None
        try:
            ctx = _spec_to_verdict_context(spec)
            result = verdict_engine_v2.render_verdict_v2(ctx)
            if result and getattr(result, "valid", False) and getattr(result, "text", ""):
                boundary_miss = _v2_render_boundary_miss(result.text, spec, ctx)
                if boundary_miss is None:
                    return result.text
                _log_v2_event(
                    "VERDICT_V2_FALL_THROUGH",
                    spec,
                    reason=boundary_miss,
                    ctx=ctx,
                    result=result,
                )
            else:
                _log_v2_event(
                    "VERDICT_V2_FALL_THROUGH",
                    spec,
                    reason="invalid_or_empty_v2_result",
                    ctx=ctx,
                    result=result,
                )
        except Exception as exc:
            _log_v2_event(
                "VERDICT_V2_RENDER_FAIL",
                spec,
                reason="exception",
                ctx=ctx,
                exc=exc,
                level=logging.WARNING,
            )
            # Fall through to the legacy path below.

    tier = _tier_for_spec(spec)

    # ── BUILD-VERDICT-SIGNAL-MAPPED-01 main path ───────────────────────────
    if _signal_mapped_enabled():
        try:
            from verdict_signal_mapper import build_verdict as _build_signal_verdict
            from verdict_signal_mapper import validate_output as _validate_signal_verdict

            team_for_action = (
                getattr(spec, "outcome_label", "")
                or getattr(spec, "home_name", "")
                or "the pick"
            ).strip()
            odds_val = float(getattr(spec, "odds", 0) or 0)
            bookmaker_val = (getattr(spec, "bookmaker", "") or "").strip()
            # FIX-VERDICT-VARIETY-WITHIN-SECTION12-BUCKET-01: NarrativeSpec
            # has no match_key field, so we reconstruct one from home/away
            # the same way the legacy corpus path (line 1028-1031 below)
            # does. Without this, draw picks collapse to outcome_label="the
            # draw" salt and simultaneous draw cards re-monoculture; non-draw
            # picks fall back to team-salt which has identical-team
            # collisions across competition slates. Mirrors verdict_corpus
            # ._pick keying so corpus and signal-mapper share the same
            # match-level entropy source.
            mapper_match_key = (
                (getattr(spec, "match_key", "") or "").strip()
                or "|".join(filter(None, (
                    (getattr(spec, "home_name", "") or "").strip(),
                    (getattr(spec, "away_name", "") or "").strip(),
                )))
                or None
            )
            mapped = _build_signal_verdict(
                team=team_for_action,
                tier=tier,
                signals=_spec_to_signals(spec),
                odds=(f"{odds_val:.2f}" if odds_val > 0 else None),
                bookmaker=bookmaker_val or None,
                line_movement_direction=_spec_movement_direction(spec),
                match_key=mapper_match_key,
            )
            ok, hits = _validate_signal_verdict(mapped)
            if mapped and ok:
                # Persistence-gate compatibility check: mapper output
                # MUST clear the same min_verdict_quality floor that
                # narrative_validator + _store_verdict_cache_sync apply
                # downstream — otherwise the verdict would be silently
                # quarantined or refused on write. Following Codex
                # adversarial-review (P1, 2026-05-04). We import lazily
                # because narrative_spec depends on this module at
                # render time and we must avoid circular imports at
                # module load. On any unexpected exception in the
                # quality probe we accept the mapper output (the gate
                # downstream will catch genuine misses) — the probe is
                # an early-fail-fast hint, not the source of truth.
                try:
                    from narrative_spec import min_verdict_quality as _mvq

                    if not _mvq(mapped, tier=tier, evidence_pack=None):
                        _log.warning(
                            "verdict-signal-mapper output failed "
                            "min_verdict_quality probe; falling back "
                            "to corpus. tier=%s len=%d sample=%r",
                            tier,
                            len(mapped),
                            mapped[:120],
                        )
                    else:
                        return mapped
                except Exception as _quality_exc:  # pragma: no cover — defensive
                    _log.debug(
                        "verdict-signal-mapper quality probe raised; "
                        "accepting mapper output. tier=%s err=%s",
                        tier,
                        _quality_exc,
                    )
                    return mapped
            elif not ok:
                _log.warning(
                    "verdict-signal-mapper validation failed; falling back to corpus. "
                    "tier=%s hits=%s",
                    tier,
                    hits,
                )
        except Exception as exc:  # pragma: no cover — defensive
            _log.warning(
                "verdict-signal-mapper failed; falling back to corpus. "
                "tier=%s err=%s",
                tier,
                exc,
            )

    sport_raw = (getattr(spec, "sport", "") or "").lower()
    sport = _normalise_sport_to_bucket(sport_raw)

    pool: list[VerdictSentence] = VERDICT_CORPUS[tier][sport]

    risk_fires = has_real_risk(spec)
    concern_fires = risk_fires and tier != "diamond"
    if concern_fires:
        filtered = [
            vs for vs in pool
            if not vs.claims_completeness and not vs.claims_max_conviction
        ]
        # Defensive: every Gold/Silver/Bronze (tier, sport) bucket has >=8
        # safe sentences by contract. Keep the guard so partial corpus edits
        # in development don't crash the verdict path before tests catch it.
        if filtered:
            pool = filtered

    # Slot inputs — every production caller fills them via NarrativeSpec.
    team = (
        getattr(spec, "outcome_label", "")
        or getattr(spec, "home_name", "")
        or "the pick"
    ).strip()
    odds_val = float(getattr(spec, "odds", 0) or 0)
    odds = f"{odds_val:.2f}" if odds_val else "—"
    bookmaker = (getattr(spec, "bookmaker", "") or "—").strip()

    # Match key drives the hash-pick. NarrativeSpec doesn't carry it as a
    # field; reconstruct from home/away when absent so the picker stays
    # deterministic for the same fixture across reads.
    match_key = (
        getattr(spec, "match_key", None)
        or f"{getattr(spec, 'home_name', '')}|{getattr(spec, 'away_name', '')}"
    )

    sentence: VerdictSentence = _pick(pool, match_key, f"{tier}|{sport}")  # type: ignore[assignment]
    body = sentence.text.format(team=team, odds=odds, bookmaker=bookmaker)

    if concern_fires:
        prefix = _pick_concern_prefix(sport, match_key, f"{tier}|prefix")
        return f"{prefix} {body}"

    return body


__all__ = [
    "VERDICT_CORPUS",
    "CONCERN_PREFIXES",
    "TIER_FLOORS",
    "VerdictSentence",
    "_normalise_sport_to_bucket",
    "_pick_concern_prefix",
    "_MAX_CONVICTION_TOKENS",
    "has_real_risk",
    "render_verdict",
]
