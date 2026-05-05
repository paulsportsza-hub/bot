"""Signal-mapped deterministic verdict builder.

BUILD-VERDICT-SIGNAL-MAPPED-01 (2026-05-03). Replaces the 360-sentence
sport-banded verdict corpus as the main path for verdict generation. The
corpus stays as the fallback safety net when the new builder rejects its
own output (banned-term / live-commentary scanner) or when the feature
flag is disabled.

FIX-VERDICT-VARIETY-WITHIN-SECTION12-BUCKET-01 (2026-05-04). Phrase pools
for primary / secondary signals and the special-case Price+Line direction
leads are now ``tuple[str, ...]`` instead of single strings. ``build_verdict``
hash-picks one variant per match_key (mirrors :func:`verdict_corpus._pick`)
so simultaneous cards with identical signal posture render distinct
verdict bodies (Paul flagged 4 simultaneous Gold/Silver cards rendering
the same §12.X "unknown" lead). Determinism guarantee: same
``(match_key, signal_combo, tier)`` always picks the same phrasing across
processes; different ``match_key`` spreads across the pool. Anchor
phrasings from spec §12.1-§12.7 remain pool members so existing
reachability contracts hold.

FIX-VERDICT-VARIETY-PASS-5-LAND-01 (2026-05-05). Two follow-on fixes from
the pass-5 adversarial-review that were stashed in the prior brief:
(1) ``SECONDARY_PHRASES_LINE_MVT_UNKNOWN`` — a direction-neutral
secondary pool for ``line_mvt`` so that under unknown / missing
``line_movement_direction`` the secondary clause never emits a
directional-assertion phrase (e.g. "the line movement backs the pick");
(2) ``_PRICE_LINE_FAVOURABLE_BY_TIER`` / ``_PRICE_LINE_AGAINST_BY_TIER``
— per-tier directional-lead dicts so Diamond / Gold / Silver / Bronze
each render from their own pool with no cross-tier framing leak (pass-3
isolated only the Bronze-specific anchors; pass-5 found Diamond / Gold /
Silver still shared the same flat pool).

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

import hashlib
import logging
import re
from typing import Iterable, Mapping, Tuple

logger = logging.getLogger(__name__)

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
# FIX-VERDICT-VARIETY-WITHIN-SECTION12-BUCKET-01: pools instead of single
# strings. First entry per pool is the spec §12.X / §14 anchor for the
# common (signal, tier) cell so it stays reachable; subsequent entries
# are the alternates from spec §6 verbatim. Hash-pick spreads selection
# across the pool keyed by match_key (see :func:`_pick_variant`).
PRIMARY_PHRASES: dict[str, tuple[str, ...]] = {
    # §6.1 Price Edge — 5 phrasings (anchor first; remaining four are the
    # spec §6.1 alternates verbatim).
    "price_edge": (
        "The price hasn't caught up",
        "The price still looks generous",
        "There is still value in the price",
        "The price is still bigger than it should be",
        "This still looks underpriced",
    ),
    # Line Mvt as PRIMARY fires when line_mvt is the only / highest-priority
    # active signal (i.e. price_edge False). The §6.2 unknown phrasings are
    # the natural fit here because Price+Line Mvt with a known direction
    # routes through the special-case block below. Pool depth = 3 to keep
    # variety; the legacy single-string lead "The line movement still leaves
    # value" stays as the anchor for backward compatibility.
    "line_mvt": (
        "The line movement still leaves value",
        "The line movement still leaves enough value",
        "The move has not taken the value away",
    ),
    # §6.6 Injury — 5 phrasings.
    "injury": (
        "The line doesn't fully reflect the team news",
        "Team news gives this extra weight",
        "The team news angle supports this",
        "The price still looks light against the team news",
        "Team news has not been fully priced in",
    ),
    # §6.5 Form — 5 phrasings.
    "form": (
        "Recent form backs this",
        "Form is on their side",
        "The form read supports it",
        "Recent results give this some weight",
        "Form gives this pick support",
    ),
    # §6.3 Market — 4 phrasings.
    "market": (
        "The wider market is leaning this way",
        "The market is giving this side support",
        "The broader market backs the lean",
        "The market support is on this side",
    ),
    # §6.4 Tipster — 4 spec-approved phrasings + legacy anchor (5 total).
    # The legacy "Outside support points this way" anchor is preserved (it
    # is the current §12.7 anchor and predates the §6.4 list); §6.4 #1-#4
    # follow verbatim.
    "tipster": (
        "Outside support points this way",
        "There is extra support on this side",
        "The outside support lines up here",
        "Trusted support is pointing this way",
        "External support backs this lean",
    ),
}

# Secondary clause variants — short rephrasings of spec §6 phrasings that
# read naturally in the "and {secondary}" position (lowercase first letter,
# pronoun "it" instead of "this"). The first entry is the legacy anchor
# used in spec §12.1 / §12.2 / §12.5-§12.7 pairings.
SECONDARY_PHRASES: dict[str, tuple[str, ...]] = {
    "injury": (
        "team news gives it extra weight",
        "the team news angle backs it",
        "team news has not been fully priced in",
        "the price still looks light against the team news",
    ),
    "form": (
        "recent form backs it",
        "form backs it",
        "form is on their side",
        "the form read supports it",
        "recent results give this weight",
    ),
    # SECONDARY[line_mvt] is the directional pool — used when the line
    # movement direction is favourable / against. The third entry "the line
    # movement backs the pick" is a directional assertion that ONLY reads
    # truthful when direction is known. For unknown direction, secondary
    # picks route through SECONDARY_PHRASES_LINE_MVT_UNKNOWN below
    # (FIX-VERDICT-VARIETY-PASS-5-LAND-01 Finding 1).
    "line_mvt": (
        "the move has not taken the value away",
        "the line movement still leaves enough value",
        "the line movement backs the pick",
    ),
    "market": (
        "the market support is there",
        "the broader market backs the lean",
        "the market support is on this side",
        "the wider market is leaning this way",
    ),
    "tipster": (
        "outside support lines up",
        "external support backs the lean",
        "the outside support lines up here",
        "trusted support is pointing this way",
    ),
}

# Direction-neutral SECONDARY[line_mvt] pool — used when the verdict's
# line_movement_direction is missing / "unknown" / "neutral" so that the
# secondary clause never asserts directional support the data has not
# established (FIX-VERDICT-VARIETY-PASS-5-LAND-01 Finding 1, Codex pass-5
# 2026-05-05). Spec §6.2 unknown branch authors two phrasings ("the move
# has not taken the value away" / "the line movement still leaves enough
# value"); pool depth 2 leaves ≥3-distinct-secondary contracts under
# 4-card variety stress, so three derived neutral variants extend the
# pool. None of the entries contain the directional-assertion patterns
# "backs the pick" / "moving our way" / "starting to follow" /
# "beginning to move" — those phrases only render under known direction
# via the directional lead pools or via SECONDARY_PHRASES["line_mvt"].
SECONDARY_PHRASES_LINE_MVT_UNKNOWN: tuple[str, ...] = (
    # §6.2 unknown branch (verbatim, secondary form).
    "the move has not taken the value away",
    "the line movement still leaves enough value",
    # Derived neutral variants — restate the same "value remains intact"
    # observation without claiming directional support.
    "the line movement still leaves value",
    "the value is still there after the move",
    "the move has not eaten into the value",
)


# Special-case Price Edge + Line Movement leads (spec §12.3 / §12.4).
# Per-tier dict: each tier renders ONLY from its own pool to prevent
# cross-tier framing leaks (Diamond "...is still there" never lands in
# front of a Gold "back" close; Gold "...still looks fair" never lands
# in front of a Diamond "go big" close, etc.). FIX-VERDICT-VARIETY-PASS-
# 5-LAND-01 Finding 3 (Codex pass-5 2026-05-05) — pass-3 isolated only
# the Bronze-specific anchors; pass-5 found the residual Diamond/Gold/
# Silver leak. Spec-authored anchors per (direction, tier):
#   §12.3 Diamond  — "...and the price is still there"
#   §12.3 Gold     — "...and the price still looks fair"
#   §12.3 Bronze   — "Small move this way with a little value left"
#   §12.4 Diamond  — "The market has moved, but the price still looks big"
#   §12.4 Gold     — "The line has shifted, but there is still value here"
#   §12.4 Bronze   — "The price has moved, but there is still a small lean"
# §12.3 Silver and §12.4 Silver are single-clause phrasings without the
# composite price+line shape; the per-tier Silver pools below derive a
# Silver-coloured composite tail ("...the price still has a small edge"
# for favourable; "...there is still a small edge" / "...not enough to
# kill the play" for against) by mechanical recombination of the §6.2
# leads with the §12.8 Silver "small edge" framing (pre-approved spec
# voice; the alternative — routing Silver through the primary+secondary
# path while D/G/B use the directional pool — would split the §12.3/§12.4
# render path on tier and complicate the contract).
# Pool sizes per tier:
#   favourable: D = 4, G = 4, S = 4, B = 4
#   against:    D = 3, G = 3, S = 3, B = 3
_PRICE_LINE_FAVOURABLE_BY_TIER: dict[str, tuple[str, ...]] = {
    # Diamond — §6.2 favourable leads × §12.3-D tail "...the price is still there".
    "diamond": (
        "The line is moving our way and the price is still there",
        "The move is starting to follow this side and the price is still there",
        "The market is beginning to move this way and the price is still there",
        "The line movement backs the pick and the price is still there",
    ),
    # Gold — §6.2 favourable leads × §12.3-G tail "...the price still looks fair".
    "gold": (
        "The line is moving our way and the price still looks fair",
        "The move is starting to follow this side and the price still looks fair",
        "The market is beginning to move this way and the price still looks fair",
        "The line movement backs the pick and the price still looks fair",
    ),
    # Silver — §6.2 favourable leads × Silver-coloured derived tail
    # "...the price still has a small edge" (matches the §12.8 Silver
    # "small edge" framing already in _FALLBACK_BY_TIER below).
    "silver": (
        "The line is moving our way and the price still has a small edge",
        "The move is starting to follow this side and the price still has a small edge",
        "The market is beginning to move this way and the price still has a small edge",
        "The line movement backs the pick and the price still has a small edge",
    ),
    # Bronze — §12.3-B anchor + 3 derived (§6.2 leads × §12.3-B tail
    # "with a little value left"). Stays disjoint from D/G/S pools.
    "bronze": (
        "Small move this way with a little value left",
        "The line is moving our way with a little value left",
        "The move is starting to follow this side with a little value left",
        "The market is beginning to move this way with a little value left",
    ),
}
_PRICE_LINE_AGAINST_BY_TIER: dict[str, tuple[str, ...]] = {
    # Diamond — §6.2 against leads × §12.4-D tail "...the price still looks big".
    "diamond": (
        "The market has moved, but the price still looks big",
        "The line has shifted, but the price still looks big",
        "The price has moved, but it still looks big",
    ),
    # Gold — §6.2 against leads × §12.4-G tail "...there is still value here".
    "gold": (
        "The line has shifted, but there is still value here",
        "The market has moved, but there is still value here",
        "The price has moved, but there is still value here",
    ),
    # Silver — §6.2 against leads × Silver-coloured derived tail
    # ("...there is still a small edge" / "...not enough to kill the
    # play"). The "not enough to kill the play" phrasing was previously
    # the un-tiered third entry of the legacy flat against pool; its
    # "thin but live" tone naturally homes in Silver here.
    "silver": (
        "The market has moved, but there is still a small edge",
        "The line has shifted, but there is still a small edge",
        "The price has moved, but not enough to kill the play",
    ),
    # Bronze — §12.4-B anchor + 2 derived (§6.2 leads × §12.4-B tail
    # "but there is still a small lean").
    "bronze": (
        "The price has moved, but there is still a small lean",
        "The market has moved, but there is still a small lean",
        "The line has shifted, but there is still a small lean",
    ),
}
# Direction "unknown" is NOT anchored in spec §12 (only §12.3 favourable
# and §12.4 against have explicit anchors). When direction is unknown,
# routing through the standard primary+secondary path lifts pool depth
# to PRIMARY[price_edge] (5) × SECONDARY_PHRASES_LINE_MVT_UNKNOWN (5) =
# 25 candidate composites — the path that resolved the Paul-flagged
# 4-card monoculture (FIX-VERDICT-VARIETY-WITHIN-SECTION12-BUCKET-01)
# and now also bars directional-assertion phrasings under unknown
# direction (FIX-VERDICT-VARIETY-PASS-5-LAND-01 Finding 1).


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


# ── Hash-distributed variant picker (mirror of verdict_corpus._pick) ──────
def _pick_variant(pool: tuple[str, ...], match_key: str, salt: str) -> str:
    """Hash-pick a variant from ``pool`` keyed by ``(match_key, salt)``.

    Uses MD5 for stable cross-process determinism — same ``(match_key, salt)``
    always returns the same element; different match_keys spread across the
    pool. Mirrors :func:`verdict_corpus._pick` (the canonical hash-pick
    used for the legacy 360-sentence corpus) so the two pickers stay
    behaviourally aligned.

    The salt should encode the dimension being picked (``primary|<key>``,
    ``secondary|<key>``, ``price_line_<direction>``, ``fallback|<tier>``)
    so the primary and secondary picks for the same match_key are
    independent — no co-correlation between the two clauses.

    A pool of size 1 short-circuits to that single element (saves a hash
    round-trip and produces identical output regardless of match_key).
    Empty pools raise ``ValueError`` — pools should be authored with at
    least one entry per signal/tier cell.
    """
    if not pool:
        raise ValueError(f"empty phrase pool for salt={salt!r}")
    if len(pool) == 1:
        return pool[0]
    seed = f"{match_key}|{salt}".encode("utf-8")
    h = hashlib.md5(seed).hexdigest()
    return pool[int(h, 16) % len(pool)]


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
# Tier-specific fallback leads. Spec §12.8 authors a single phrase per
# tier; the brief's variety contract for ≥3 distinct primaries across 4
# simultaneous cards requires pool depth >= 3, which single-entry pools
# cannot provide (Codex adversarial-review pass-4, 2026-05-05). Each tier
# extends the spec anchor with two editorial alternates that:
#   - keep the no-strong-signals editorial framing of §12.8 (generic
#     "value/edge in the setup" language, no signal-specific claims)
#   - clear the §15.1 banned-term and §15.2 live-commentary scanners
#   - mirror the tier conviction the §12.8 anchor sets (Diamond strong /
#     Gold supporting / Silver thin / Bronze marginal)
# The §12.8 anchor stays at index 0 of each tuple (regression guard).
_FALLBACK_BY_TIER: dict[str, tuple[str, ...]] = {
    "diamond": (
        "The price still looks too big for the setup",
        "There is real edge in the price right now",
        "The setup still favours the play at this price",
        "The price still has plenty behind it for this play",
    ),
    "gold": (
        "There is enough value here to support the pick",
        "There is enough behind this lean to back it",
        "The setup gives this side enough support",
        "The price still favours backing this side",
    ),
    "silver": (
        "There is just enough value here",
        "There is a slim but live edge to lean on",
        "The setup leaves a small edge for this side",
        "The lean is thin but still live at this price",
    ),
    "bronze": (
        "Not much in it, but there is a small lean",
        "There is a small edge worth a measured play",
        "Light value, but the lean is still there",
        "A small angle is worth a measured play here",
    ),
}


# ── build_verdict (spec §14 Step 6) ────────────────────────────────────────
def build_verdict(
    team: str,
    tier: str,
    signals: Mapping[str, object] | None,
    odds: str | float | None = None,
    bookmaker: str | None = None,
    line_movement_direction: str | None = None,
    match_key: str | None = None,
) -> str:
    """Render a deterministic signal-mapped verdict.

    ``match_key`` keys the hash-pick over the per-signal phrase pools. Same
    ``(match_key, signal_combo, tier)`` always picks the same phrasing
    (deterministic + cacheable); different match_keys spread across the pool
    so simultaneous cards with identical signal posture render distinct
    bodies (FIX-VERDICT-VARIETY-WITHIN-SECTION12-BUCKET-01). When
    ``match_key`` is missing / empty the salt falls back to ``team`` and a
    debug log fires — backward-compatibility shim for any caller that has
    not yet been migrated.

    Control flow:
      1. Normalise raw signals to the 6 canonical booleans.
      2. Special-case Price Edge + Line Movement (spec §12.3 / §12.4) when
         direction is favourable / against — pick from the direction-specific
         lead pool. Direction "unknown" / missing routes through (3) so the
         primary+secondary cartesian product gives variety (spec §12 has no
         anchor for unknown direction, only §12.3 favourable and §12.4
         against; resolves the §6.2-unknown pool-depth=2 monoculture Paul
         flagged 2026-05-04).
      3. Otherwise, primary + secondary picks per priority order. Two-part
         causal shape if both fire; clean causal if only primary; tier
         fallback (spec §12.8) if no signals are active.

    Returns the assembled sentence ending in a period. Never raises;
    defensively returns a tier-appropriate fallback when inputs are
    malformed.
    """
    norm = normalize_signals(signals)
    action = build_action(tier, team, odds, bookmaker)
    tier_key = (tier or "").lower() or "silver"

    salt_key = (match_key or "").strip()
    if not salt_key:
        team_salt = (team or "").strip()
        if team_salt:
            logger.debug(
                "verdict_signal_mapper.build_verdict invoked without match_key; "
                "falling back to team salt %r (variety degraded — see "
                "FIX-VERDICT-VARIETY-WITHIN-SECTION12-BUCKET-01).",
                team_salt,
            )
        salt_key = team_salt or "_no_key"

    # Salt strategy: per-tier directional pools (Pass-5 Finding 3) make
    # tier-mixing on the directional salts redundant for cross-tier
    # collision avoidance — each tier picks from its own pool — but tier
    # mixing is preserved because the per-tier pools have different sizes
    # and entries, so a tier-pure salt could still collide unevenly. The
    # primary/secondary salts deliberately stay tier-free — mixing tier
    # there regressed the Paul-flagged 4-card variety on primary|
    # price_edge in pass-2. The unknown-direction secondary[line_mvt]
    # salt namespaces with "|unknown" so it draws independently from the
    # directional secondary pool's hash distribution.
    #
    # Direction normalisation contract: only the explicit canonical
    # values (`favourable` / `for` for favourable, `against` for against)
    # route through the directional pools. EVERY other value — empty,
    # `None`, `unknown`, `neutral`, AND any producer-specific sentinel
    # (`none`, `n/a`, ...) — collapses to the unknown route. This keeps
    # the secondary `line_mvt` clause neutral whenever direction has not
    # been positively established (Codex pass-5-land adversarial-review,
    # 2026-05-05 — closed-default avoids version-skew leak through
    # SECONDARY_PHRASES["line_mvt"]'s directional entry).
    direction = (line_movement_direction or "").strip().lower()
    direction_known_favourable = direction in ("favourable", "for")
    direction_known_against = direction == "against"
    direction_unknown = not (direction_known_favourable or direction_known_against)

    # Special: Price Edge + Line Movement — directional anchor pools.
    if norm["price_edge"] and norm["line_mvt"]:
        if direction_known_against:
            # `_BY_TIER.get(tier_key, ...)["silver"]` is the documented
            # fallback for any unrecognised tier string — mirrors the
            # `tier_key = ... or "silver"` coercion at the top of this
            # function. Production tiers are restricted to the canonical
            # 4 by edge_rating, so this fallback is defensive only.
            against_pool = _PRICE_LINE_AGAINST_BY_TIER.get(
                tier_key, _PRICE_LINE_AGAINST_BY_TIER["silver"]
            )
            lead = _pick_variant(
                against_pool, salt_key, f"price_line_against|{tier_key}"
            )
            return f"{lead} — {action}."
        if direction_known_favourable:
            favourable_pool = _PRICE_LINE_FAVOURABLE_BY_TIER.get(
                tier_key, _PRICE_LINE_FAVOURABLE_BY_TIER["silver"]
            )
            lead = _pick_variant(
                favourable_pool, salt_key, f"price_line_favourable|{tier_key}"
            )
            return f"{lead} — {action}."
        # Direction unknown / neutral / None / non-canonical sentinel —
        # fall through to the standard primary+secondary path with the
        # neutral SECONDARY_PHRASES_LINE_MVT_UNKNOWN pool below.
        # PRIMARY[price_edge] × SECONDARY_PHRASES_LINE_MVT_UNKNOWN gives
        # the variety that pool-depth=2 §6.2-unknown couldn't, with no
        # directional-assertion leak.

    primary = pick_primary(norm)
    secondary = pick_secondary(norm, primary)

    if primary and secondary:
        primary_phrase = _pick_variant(
            PRIMARY_PHRASES[primary], salt_key, f"primary|{primary}"
        )
        # Pass-5 Finding 1 — under unknown direction, route line_mvt-secondary
        # through the direction-neutral pool so the secondary clause never
        # asserts directional support the data has not established.
        if secondary == "line_mvt" and direction_unknown:
            secondary_pool = SECONDARY_PHRASES_LINE_MVT_UNKNOWN
            secondary_salt = "secondary|line_mvt|unknown"
        else:
            secondary_pool = SECONDARY_PHRASES[secondary]
            secondary_salt = f"secondary|{secondary}"
        secondary_phrase = _pick_variant(
            secondary_pool, salt_key, secondary_salt
        )
        return f"{primary_phrase} and {secondary_phrase} — {action}."
    if primary:
        primary_phrase = _pick_variant(
            PRIMARY_PHRASES[primary], salt_key, f"primary|{primary}"
        )
        return f"{primary_phrase} — {action}."

    fallback_pool = _FALLBACK_BY_TIER.get(tier_key, _FALLBACK_BY_TIER["silver"])
    lead = _pick_variant(fallback_pool, salt_key, f"fallback|{tier_key}")
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
    "SECONDARY_PHRASES_LINE_MVT_UNKNOWN",
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
