"""Deterministic verdict corpus — replaces W82 variable assembly.

BUILD-W82-RIP-AND-REPLACE-01 (2026-05-02). Hand-authored 40 verdict sentences
(10 per tier) plus 10 sport-agnostic concern prefixes. Hash-pick by
(match_key, tier) for stability across reads of the same edge.

Slots: {team}, {odds}, {bookmaker} only. Zero connectors, zero risk-clause
helpers, zero concessive logic, zero variant pool. When the concern prefix
fires (has_real_risk(spec) is True), it concatenates with a single space —
no linguistic bridge between prefix and verdict body.

Voice rubric: .claude/skills/verdict-generator/SKILL.md (v2 Deterministic
Mode section). SA-native English. Conviction tier-appropriate. Imperative
close ("back / hammer / get on / take / bet / lock in / load up / go in /
the play is / the call is / worth a"). 100-200 char range per sentence
across realistic slot-fill spread.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from narrative_spec import NarrativeSpec


# ── Tier composite-score floors ───────────────────────────────────────────
# Mirrors the canonical tier thresholds at services/edge_rating.py. Used by
# has_real_risk to flag a marginal-edge case (composite within 5 pts of floor).
TIER_FLOORS: dict[str, int] = {
    "diamond": 85,
    "gold": 70,
    "silver": 55,
    "bronze": 40,
}


# ── Verdict corpus — 40 sentences ─────────────────────────────────────────
VERDICT_CORPUS: dict[str, list[str]] = {
    "diamond": [
        "This one is locked in across every signal we track — hammer {team} at {odds} on {bookmaker}, full confident stake on the day.",
        "Model and market are pointing the same direction here. Load up on {team} at {odds} with {bookmaker}, heavy stake from kickoff.",
        "Edge confirmed top to bottom and the price still hasn't moved — go in heavy on {team} at {odds} on {bookmaker}, standard-to-heavy stake.",
        "Every signal we measure points the same way on this fixture. Bet {team} at {odds} with {bookmaker}, full confident stake on the day.",
        "This is exactly what conviction looks like in our model. Lock in {team} at {odds} on {bookmaker}, standard-to-heavy stake from kickoff.",
        "Numbers, signals, and the price are all aligned cleanly here. Get on {team} at {odds} with {bookmaker}, full confident stake.",
        "Top-tier edge with the price still on offer through kickoff — hammer {team} at {odds} on {bookmaker}, standard-to-heavy stake.",
        "Everything we measure has this one as a high-conviction play. Back {team} at {odds} with {bookmaker}, full confident stake on the day.",
        "The bookies have got their numbers wrong on this one. Load up on {team} at {odds} on {bookmaker}, standard-to-heavy stake on the day.",
        "Diamond-grade signal stack, clean read top to bottom — go in heavy on {team} at {odds} with {bookmaker}, full confident stake.",
    ],
    "gold": [
        "The signals tell a clean story on this fixture — back {team} at {odds} with {bookmaker}, standard stake on the day.",
        "Strong read across the indicators we trust most. Get on {team} at {odds} on {bookmaker}, standard stake from kickoff.",
        "The model has a clear preference and the price reflects fair value — back {team} at {odds} with {bookmaker}, standard stake.",
        "Solid edge with the supporting signals doing their job. Take {team} at {odds} on {bookmaker}, standard stake on the day.",
        "The call is straightforward when the numbers read like this — back {team} at {odds} with {bookmaker}, standard stake on the day.",
        "Everything the data says points the right direction here. Get on {team} at {odds} on {bookmaker}, standard stake on the day.",
        "The price is fair to slightly generous on a confirmed edge — take {team} at {odds} with {bookmaker}, standard stake from kickoff.",
        "Numbers and signals both nodding the same direction on this one. Back {team} at {odds} on {bookmaker}, standard stake on the day.",
        "The market is offering value where the model has conviction — bet {team} at {odds} with {bookmaker}, standard stake on the day.",
        "Gold-grade read with clean signal support behind it. Get on {team} at {odds} on {bookmaker}, standard stake from kickoff.",
    ],
    "silver": [
        "The numbers lean this way without screaming it loud. The play is {team} at {odds} with {bookmaker}, standard stake on the day.",
        "A measured read with the signals tilted the right way here. Back {team} at {odds} on {bookmaker}, standard stake on the day.",
        "The edge is real and the conviction stays moderate today. The play is {team} at {odds} with {bookmaker}, standard stake on the day.",
        "Decent value with supporting signals on the right side here. The play is {team} at {odds} on {bookmaker}, standard stake on the day.",
        "Numbers tilt this way on a clean enough read of the fixture — back {team} at {odds} with {bookmaker}, standard stake on the day.",
        "The model has a preference and the market is offering it. Take {team} at {odds} on {bookmaker}, standard stake on the day.",
        "The signals support the call but the gap is not enormous. The play is {team} at {odds} with {bookmaker}, standard stake on the day.",
        "Moderate edge with reasonable signal coverage on the day. The play is {team} at {odds} on {bookmaker}, standard stake from kickoff.",
        "Worth the standard exposure on a measured read of the fixture — back {team} at {odds} with {bookmaker}, standard stake on the day.",
        "Silver-grade signal with the price holding up through kickoff — take {team} at {odds} on {bookmaker}, standard stake on the day.",
    ],
    "bronze": [
        "Light edge with supporting signals on the thinner side here. Worth a small play on {team} at {odds} with {bookmaker}, light stake.",
        "The numbers nudge this way without much weight behind them. Worth a measured punt on {team} at {odds} on {bookmaker}, light stake.",
        "A modest read with limited supporting evidence on the day. Worth a small punt on {team} at {odds} with {bookmaker}, light stake.",
        "Bronze-tier signal — real edge but the conviction is thin today. Worth a small play on {team} at {odds} on {bookmaker}.",
        "Marginal value where the model has only a slight preference. Worth a measured punt on {team} at {odds} with {bookmaker}, light stake.",
        "Light support and a price that justifies a small position only. Worth a measured play on {team} at {odds} on {bookmaker}, light stake.",
        "Edge exists, but conviction stays modest at this tier today. Worth a small play on {team} at {odds} with {bookmaker}.",
        "The signal is there in muted form, not screaming the play out. Worth a measured punt on {team} at {odds} on {bookmaker}.",
        "Modest read on a fixture with enough value to justify exposure. Worth a small play on {team} at {odds} with {bookmaker}, light stake.",
        "Thin but real edge on the day — worth a measured punt on {team} at {odds} on {bookmaker}, light stake from kickoff.",
    ],
}


# ── Concern prefixes — 10 sport-agnostic sentences ────────────────────────
# Used only when has_real_risk(spec) is True. Concatenated to verdict body
# with a single space, no linguistic bridge. The verdict body still starts
# with a capital letter — the reader's brain treats prefix + body as two
# separate beats: "here's the concern" then "here's the call".
CONCERN_PREFIXES: list[str] = [
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
]


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
def _pick(corpus: list[str], match_key: str, tier: str) -> str:
    """Hash-pick a sentence from corpus by (match_key, tier).

    Uses MD5 for stable cross-process determinism. Same (match_key, tier)
    always returns the same sentence; different keys spread across the pool.
    """
    seed = f"{match_key}|{tier}".encode("utf-8")
    h = hashlib.md5(seed).hexdigest()
    return corpus[int(h, 16) % len(corpus)]


# ── render_verdict — slot-fill + optional concern prefix ──────────────────
def render_verdict(spec: "NarrativeSpec") -> str:
    """Render the deterministic verdict for ``spec``.

    Reads ``spec.edge_tier`` to select the corpus pool. Hash-picks a sentence
    by ``(spec.match_key, tier)``. Slot-fills {team}, {odds}, {bookmaker}.
    Prepends a concern prefix (separator: single space) when
    ``has_real_risk(spec)`` is True.

    Returns the bare body when the spec is mid-renderer and a slot would
    otherwise resolve to empty (defensive — slot fills are always non-empty
    in production paths). Empty edge_tier falls back to a ``verdict_action``
    → tier mapping (strong back→diamond, back→gold, lean→silver, else bronze)
    so legacy callers that build a NarrativeSpec without populating
    ``edge_tier`` still get a tier-appropriate verdict.
    """
    tier = (getattr(spec, "edge_tier", "") or "").lower()
    pool = VERDICT_CORPUS.get(tier)
    if not pool:
        # Action-derived fallback when edge_tier is empty/unrecognised.
        action = (getattr(spec, "verdict_action", "") or "").lower()
        derived = {
            "strong back": "diamond",
            "back": "gold",
            "lean": "silver",
        }.get(action, "bronze")
        tier = derived
        pool = VERDICT_CORPUS[tier]

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

    template = _pick(pool, match_key, tier)
    body = template.format(team=team, odds=odds, bookmaker=bookmaker)

    if has_real_risk(spec):
        prefix = _pick(CONCERN_PREFIXES, match_key, tier + ":prefix")
        return f"{prefix} {body}"

    return body


__all__ = [
    "VERDICT_CORPUS",
    "CONCERN_PREFIXES",
    "TIER_FLOORS",
    "has_real_risk",
    "render_verdict",
]
