"""Edge Rating calculator — the core IP of MzansiEdge.

Combines bookmaker consensus, AI model predictions, line movement signals,
and value detection into a single confidence rating for each tip.
"""

from __future__ import annotations

import logging
import statistics
import sys
import os

log = logging.getLogger("mzansiedge.edge")

# Import integrity guardrails
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
try:
    from scrapers.odds_integrity import cap_ev, validate_tier
except ImportError:
    # Graceful fallback if scrapers not available (e.g. in test env)
    def cap_ev(ev, tier, bk_count):
        return ev, ""
    def validate_tier(tier, bk_count):
        return tier


class EdgeRating:
    DIAMOND = "diamond"    # 85%+ confidence
    GOLD = "gold"          # 70%+ confidence
    SILVER = "silver"      # 55%+ confidence
    BRONZE = "bronze"      # 40%+ confidence
    HIDDEN = "hidden"      # Below 40% — NOT shown to users


def _safe_odds(snapshot: dict) -> float | None:
    """Extract odds from a snapshot, returning None if missing or invalid."""
    val = snapshot.get("odds")
    if val is None:
        return None
    try:
        fval = float(val)
        return fval if fval > 0 else None
    except (TypeError, ValueError):
        return None


def calculate_edge_rating(
    odds_snapshots: list[dict],
    model_prediction: dict,
    line_movement: dict | None = None,
) -> str:
    """Calculate the Edge Rating for a tip.

    Args:
        odds_snapshots: list of dicts with keys: bookmaker, outcome, odds, timestamp
            Each dict represents one bookmaker's odds for the predicted outcome.
            If odds is None for a bookmaker, that bookmaker is skipped.
        model_prediction: dict with keys:
            - outcome: str (e.g. "home", "away", "draw")
            - confidence: float (0.0-1.0) — Claude Haiku's confidence in the prediction
            - implied_prob: float (0.0-1.0) — model's estimated true probability
        line_movement: optional dict with keys:
            - direction: str ("shortening", "drifting", "stable")
            - magnitude: float (absolute change in odds over period)
            - hours: int (time window of movement)

    Returns:
        EdgeRating string constant (diamond/gold/silver/bronze/hidden)
    """
    if not odds_snapshots:
        odds_snapshots = []
    if not model_prediction:
        model_prediction = {}

    scores: list[float] = []

    # Factor 1: Bookmaker consensus (0-25 points)
    consensus_score = _bookmaker_consensus(odds_snapshots, model_prediction.get("outcome", ""))
    scores.append(consensus_score)

    # Factor 2: Model alignment (0-25 points)
    alignment_score = _model_alignment(odds_snapshots, model_prediction)
    scores.append(alignment_score)

    # Factor 3: Line movement (0-20 points)
    movement_score = _line_movement_score(line_movement, model_prediction.get("outcome", ""))
    scores.append(movement_score)

    # Factor 4: Value detection (0-20 points)
    value_score = _value_detection(odds_snapshots, model_prediction)
    scores.append(value_score)

    # Factor 5: Market breadth (0-10 points)
    breadth_score = _market_breadth(odds_snapshots)
    scores.append(breadth_score)

    total = sum(scores)

    log.debug(
        "Edge scores: consensus=%.1f alignment=%.1f movement=%.1f value=%.1f breadth=%.1f total=%.1f",
        *scores, total,
    )

    if total >= 85:
        return EdgeRating.DIAMOND
    if total >= 70:
        return EdgeRating.GOLD
    if total >= 55:
        return EdgeRating.SILVER
    if total >= 40:
        return EdgeRating.BRONZE
    return EdgeRating.HIDDEN


def calculate_edge_score(
    odds_snapshots: list[dict],
    model_prediction: dict,
    line_movement: dict | None = None,
) -> float:
    """Return the raw edge score (0-100) without tier mapping."""
    if not odds_snapshots:
        odds_snapshots = []
    if not model_prediction:
        model_prediction = {}
    return (
        _bookmaker_consensus(odds_snapshots, model_prediction.get("outcome", ""))
        + _model_alignment(odds_snapshots, model_prediction)
        + _line_movement_score(line_movement, model_prediction.get("outcome", ""))
        + _value_detection(odds_snapshots, model_prediction)
        + _market_breadth(odds_snapshots)
    )


def apply_guardrails(
    tier: str,
    ev: float,
    bk_count: int,
) -> tuple[str, float | None, str]:
    """Apply EV cap and tier validation guardrails.

    Args:
        tier: raw edge rating tier from calculate_edge_rating()
        ev: expected value as fraction (e.g. 0.15 for 15%)
        bk_count: number of bookmakers offering this match

    Returns:
        (adjusted_tier, adjusted_ev_or_None, reason)
        If adjusted_ev is None, the tip should be excluded entirely.
    """
    # Step 1: Validate tier against BK count (may downgrade)
    adjusted_tier = validate_tier(tier, bk_count)

    # Step 2: Cap EV for the (potentially downgraded) tier
    adjusted_ev, reason = cap_ev(ev, adjusted_tier, bk_count)

    if adjusted_tier != tier and not reason:
        reason = f"Tier downgraded: {tier} → {adjusted_tier} ({bk_count} BKs)"

    return adjusted_tier, adjusted_ev, reason


def _bookmaker_consensus(snapshots: list[dict], predicted_outcome: str) -> float:
    """Do multiple bookmakers agree on the favourite? (0-25 points)

    If 3+ bookmakers have the predicted outcome as favourite (lowest odds = highest
    implied probability), that's a strong consensus signal.
    """
    if not snapshots or not predicted_outcome:
        return 0.0

    # Group by bookmaker — get each bookmaker's view (skip None odds)
    bookmaker_odds: dict[str, float] = {}
    for snap in snapshots:
        bk = snap.get("bookmaker", "")
        outcome = snap.get("outcome", "")
        odds = _safe_odds(snap)
        if outcome == predicted_outcome and bk and odds is not None:
            bookmaker_odds[bk] = odds

    num_bookmakers = len(bookmaker_odds)
    if num_bookmakers == 0:
        return 0.0

    # Check if the predicted outcome is the favourite at each bookmaker
    # For simplicity: if odds < 2.0, the bookmaker considers it likely
    favouring = sum(1 for odds in bookmaker_odds.values() if odds < 2.5)
    consensus_ratio = favouring / num_bookmakers if num_bookmakers > 0 else 0

    # More bookmakers offering odds = more consensus data = higher base
    breadth_bonus = min(num_bookmakers / 5, 1.0) * 5  # 0-5 bonus for more bookmakers

    return min(consensus_ratio * 20 + breadth_bonus, 25.0)


def _model_alignment(snapshots: list[dict], prediction: dict) -> float:
    """Does the AI model agree with the bookmaker odds? (0-25 points)

    High alignment = model and market agree = stronger signal.
    """
    model_confidence = prediction.get("confidence", 0.5)
    model_prob = prediction.get("implied_prob", 0.5)
    predicted_outcome = prediction.get("outcome", "")

    if not snapshots or not predicted_outcome:
        return model_confidence * 15  # Partial credit for model confidence alone

    # Calculate market-implied probability for the predicted outcome
    outcome_odds = [o for s in snapshots if s.get("outcome") == predicted_outcome and (o := _safe_odds(s)) is not None]
    if not outcome_odds:
        return model_confidence * 15

    avg_odds = statistics.mean(outcome_odds)
    market_prob = 1.0 / avg_odds if avg_odds > 0 else 0.5

    # Alignment: how close is the model to the market?
    diff = abs(model_prob - market_prob)

    if diff < 0.05:
        # Strong alignment — model and market agree closely
        alignment = 20.0
    elif diff < 0.10:
        alignment = 15.0
    elif diff < 0.20:
        alignment = 10.0
    else:
        alignment = 5.0

    # Bonus for high model confidence
    confidence_bonus = model_confidence * 5  # 0-5 points

    return min(alignment + confidence_bonus, 25.0)


def _line_movement_score(movement: dict | None, predicted_outcome: str) -> float:
    """Are odds moving in the predicted direction? (0-20 points)

    Shortening odds on the predicted outcome = sharp money agrees = strong signal.
    """
    if not movement:
        return 10.0  # Neutral — no movement data available

    direction = movement.get("direction", "stable")
    magnitude = movement.get("magnitude", 0.0)

    if direction == "shortening":
        # Odds getting shorter = more money on this outcome = bullish
        base = 15.0
        magnitude_bonus = min(magnitude * 10, 5.0)  # bigger moves = stronger signal
        return min(base + magnitude_bonus, 20.0)
    elif direction == "drifting":
        # Odds getting longer = money moving away = bearish
        base = 5.0
        magnitude_penalty = min(magnitude * 10, 5.0)
        return max(base - magnitude_penalty, 0.0)
    else:
        # Stable
        return 10.0


def _value_detection(snapshots: list[dict], prediction: dict) -> float:
    """Is there a significant discrepancy between model and odds? (0-20 points)

    If the model says 60% chance but odds imply 45%, that's value.
    """
    model_prob = prediction.get("implied_prob", 0.5)
    predicted_outcome = prediction.get("outcome", "")

    if not snapshots or not predicted_outcome:
        return 0.0

    outcome_odds = [o for s in snapshots if s.get("outcome") == predicted_outcome and (o := _safe_odds(s)) is not None]
    if not outcome_odds:
        return 0.0

    best_odds = max(outcome_odds)
    market_prob = 1.0 / best_odds if best_odds > 0 else 0.5

    # Value = model prob > market prob (we think it's more likely than the market)
    edge = model_prob - market_prob

    if edge <= 0:
        return 0.0  # No value — market already prices it correctly or higher
    elif edge < 0.05:
        return 5.0
    elif edge < 0.10:
        return 10.0
    elif edge < 0.15:
        return 15.0
    else:
        return 20.0


def _market_breadth(snapshots: list[dict]) -> float:
    """How many bookmakers have this match listed? (0-10 points)

    More bookmakers = more liquid market = more reliable odds.
    """
    unique_bookmakers = {s.get("bookmaker") for s in snapshots if s.get("bookmaker") and _safe_odds(s) is not None}
    count = len(unique_bookmakers)

    if count >= 5:
        return 10.0
    elif count >= 3:
        return 7.0
    elif count >= 2:
        return 5.0
    elif count >= 1:
        return 3.0
    return 0.0
