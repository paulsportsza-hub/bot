"""MzansiEdge — Live scores polling service.

Fetches scores from The Odds API, detects changes, and sends notifications
to subscribed users.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

import config
import db

log = logging.getLogger("mzansiedge.live_scores")

# In-memory cache of last-seen scores per event
_score_cache: dict[str, dict] = {}


async def fetch_scores(sport_key: str) -> list[dict]:
    """Fetch live scores from The Odds API /scores endpoint.

    Costs 1 request per call. Returns list of score dicts.
    """
    url = f"{config.ODDS_BASE_URL}/sports/{sport_key}/scores"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "daysFrom": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log.error("Failed to fetch scores for %s: %s", sport_key, exc)
        return []


def detect_changes(event_id: str, current: dict) -> list[str]:
    """Compare current score data with cached version.

    Returns list of change descriptions, e.g.:
    ["Score update: Arsenal 2 - 1 Chelsea", "Game completed"]
    """
    prev = _score_cache.get(event_id)
    changes: list[str] = []

    completed = current.get("completed", False)
    scores = current.get("scores")
    home = current.get("home_team", "?")
    away = current.get("away_team", "?")

    if not prev:
        # First time seeing this event
        if scores and completed:
            home_score = _get_score(scores, home)
            away_score = _get_score(scores, away)
            changes.append(f"Full time: {home} {home_score} - {away_score} {away}")
        elif scores:
            home_score = _get_score(scores, home)
            away_score = _get_score(scores, away)
            if home_score != "0" or away_score != "0":
                changes.append(f"Score: {home} {home_score} - {away_score} {away}")
    else:
        prev_scores = prev.get("scores")
        prev_completed = prev.get("completed", False)

        if scores:
            home_score = _get_score(scores, home)
            away_score = _get_score(scores, away)
            prev_home = _get_score(prev_scores, home) if prev_scores else "0"
            prev_away = _get_score(prev_scores, away) if prev_scores else "0"

            if home_score != prev_home or away_score != prev_away:
                changes.append(f"⚽ Score update: {home} {home_score} - {away_score} {away}")

        if completed and not prev_completed:
            if scores:
                home_score = _get_score(scores, home)
                away_score = _get_score(scores, away)
                changes.append(f"🏁 Full time: {home} {home_score} - {away_score} {away}")
            else:
                changes.append(f"🏁 Game completed: {home} vs {away}")

    # Update cache
    _score_cache[event_id] = current
    return changes


def _get_score(scores: list[dict] | None, team_name: str) -> str:
    """Extract score for a team from scores array."""
    if not scores:
        return "0"
    for s in scores:
        if s.get("name") == team_name:
            return str(s.get("score", "0"))
    return "0"


async def check_score_updates(bot) -> None:
    """Poll for score updates and notify subscribers.

    Should be called periodically (e.g. every 5 minutes) when there
    are active subscriptions.
    """
    # Get all active subscriptions grouped by sport_key
    from collections import defaultdict

    all_subs = []
    # We need to get unique sport_keys from active subscriptions
    async with db.async_session() as s:
        from sqlalchemy import select as sa_select
        result = await s.execute(
            sa_select(db.GameSubscription).where(
                db.GameSubscription.is_active == True,  # noqa: E712
            )
        )
        all_subs = list(result.scalars().all())

    if not all_subs:
        return

    sport_events: dict[str, set[str]] = defaultdict(set)
    event_subs: dict[str, list[db.GameSubscription]] = defaultdict(list)
    for sub in all_subs:
        if sub.sport_key:
            sport_events[sub.sport_key].add(sub.event_id)
        event_subs[sub.event_id].append(sub)

    # Fetch scores per sport
    for sport_key, event_ids in sport_events.items():
        api_key = config.SPORTS_MAP.get(sport_key, sport_key)
        scores = await fetch_scores(api_key)

        for score_data in scores:
            eid = score_data.get("id", "")
            if eid not in event_ids:
                continue

            changes = detect_changes(eid, score_data)
            if not changes:
                continue

            # Send notifications to subscribers
            subs = event_subs.get(eid, [])
            for sub in subs:
                msg = "\n".join(changes)
                try:
                    await bot.send_message(
                        sub.user_id,
                        f"⚡ <b>Live Update</b>\n\n{msg}",
                        parse_mode="HTML",
                    )
                except Exception as exc:
                    log.warning("Failed to notify user %d: %s", sub.user_id, exc)

            # Deactivate subscriptions for completed games
            if score_data.get("completed"):
                await db.deactivate_subscriptions_for_event(eid)
