"""MzansiEdge — Picks service (platform-agnostic).

Orchestrates the picks pipeline: loads user profile, fetches odds,
computes EV, and returns structured pick data for rendering.
"""

from __future__ import annotations

from typing import Any

import config
import db
from scripts.picks_engine import get_picks_for_user


async def get_picks(user_id: int, max_picks: int = 5) -> dict[str, Any]:
    """Full picks pipeline for a user.

    Returns dict with:
    - ok: bool
    - reason: str | None (e.g. "no_leagues", "quota_exhausted", "no_picks", "error")
    - picks: list[dict]
    - total_events, total_markets, total_scanned: int
    - quota_remaining: str
    - risk_label: str
    - experience: str
    - errors: list[str] | None
    """
    user = await db.get_user(user_id)
    risk_key = (user.risk_profile if user else None) or "moderate"
    profile = config.RISK_PROFILES.get(risk_key, config.RISK_PROFILES["moderate"])
    experience = (user.experience_level if user else None) or "casual"

    # Get user's preferred leagues
    prefs = await db.get_user_sport_prefs(user_id)
    if prefs:
        league_keys = list({p.league for p in prefs if p.league})
    else:
        league_keys = list(config.SPORTS_MAP.keys())

    if not league_keys:
        return {
            "ok": False,
            "reason": "no_leagues",
            "picks": [],
            "total_events": 0,
            "total_markets": 0,
            "total_scanned": 0,
            "quota_remaining": "?",
            "risk_label": profile["label"],
            "experience": experience,
            "errors": None,
        }

    # Fetch picks via engine
    user_bankroll = getattr(user, "bankroll", None) if user else None
    try:
        result = await get_picks_for_user(
            league_keys=league_keys,
            risk_profile=risk_key,
            max_picks=max_picks,
            bankroll=user_bankroll,
        )
    except Exception as exc:
        return {
            "ok": False,
            "reason": "error",
            "picks": [],
            "total_events": 0,
            "total_markets": 0,
            "total_scanned": 0,
            "quota_remaining": "?",
            "risk_label": profile["label"],
            "experience": experience,
            "errors": [str(exc)],
        }

    # Check for quota exhaustion
    if result.get("errors") and any("quota_exhausted" in str(e) for e in result["errors"]):
        return {
            **result,
            "reason": "quota_exhausted",
            "risk_label": profile["label"],
            "experience": experience,
        }

    if not result["ok"] or not result["picks"]:
        return {
            **result,
            "reason": "no_picks",
            "risk_label": profile["label"],
            "experience": experience,
        }

    return {
        **result,
        "reason": None,
        "risk_label": profile["label"],
        "experience": experience,
        "league_count": len(league_keys),
    }
