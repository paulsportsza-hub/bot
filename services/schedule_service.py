"""MzansiEdge — Schedule service (platform-agnostic).

Fetches upcoming events, filters to user's teams, groups by date,
and returns structured data for rendering.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import config
import db


SA_TZ = ZoneInfo(config.TZ)


async def get_schedule(user_id: int, max_events: int = 10) -> dict[str, Any]:
    """Build schedule data for a user.

    Returns dict with:
    - ok: bool
    - reason: str | None (e.g. "no_leagues", "no_events")
    - events: list of event dicts grouped by date
    - date_groups: list of {date_header, events: [{idx, emoji, time, home, away, home_bold, away_bold, event_id}]}
    - total: int
    """
    from scripts.sports_data import fetch_events_for_league

    prefs = await db.get_user_sport_prefs(user_id)
    user_teams: set[str] = set()
    league_keys: set[str] = set()
    for pref in prefs:
        if pref.team_name:
            user_teams.add(pref.team_name.lower())
        if pref.league:
            league_keys.add(pref.league)

    if not league_keys:
        return {"ok": False, "reason": "no_leagues", "events": [], "date_groups": [], "total": 0}

    all_events: list[dict] = []
    for lk in league_keys:
        if not config.SPORTS_MAP.get(lk):
            continue  # Skip leagues without an Odds API key
        sport_key = config.LEAGUE_SPORT.get(lk, "")
        sport = config.ALL_SPORTS.get(sport_key)
        sport_emoji = sport.emoji if sport else "\U0001f3c5"
        events = await fetch_events_for_league(lk)
        for event in events:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            is_relevant = (
                home.lower() in user_teams
                or away.lower() in user_teams
                or not user_teams
            )
            if is_relevant:
                all_events.append({**event, "league_key": lk, "sport_emoji": sport_emoji})

    if not all_events:
        return {"ok": False, "reason": "no_events", "events": [], "date_groups": [], "total": 0}

    all_events.sort(key=lambda e: e.get("commence_time", ""))
    upcoming = all_events[:max_events]

    today = datetime.now(SA_TZ).date()
    tomorrow = today + timedelta(days=1)

    date_groups: list[dict] = []
    current_group: dict | None = None

    for idx, event in enumerate(upcoming, 1):
        try:
            ct = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
            ct_sa = ct.astimezone(SA_TZ)
            event_date = ct_sa.date()
            event_time = ct_sa.strftime("%H:%M")

            if event_date == today:
                date_header = "Today"
            elif event_date == tomorrow:
                date_header = "Tomorrow"
            else:
                date_header = ct_sa.strftime("%A, %d %b")
        except Exception:
            date_header = "TBC"
            event_time = ""

        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        emoji = event.get("sport_emoji", "\U0001f3c5")
        event_id = event.get("id", str(idx))

        event_data = {
            "idx": idx,
            "emoji": emoji,
            "time": event_time,
            "home": home,
            "away": away,
            "home_bold": home.lower() in user_teams,
            "away_bold": away.lower() in user_teams,
            "event_id": event_id,
            "home_abbr": config.abbreviate_team(home),
            "away_abbr": config.abbreviate_team(away),
        }

        if current_group is None or current_group["date_header"] != date_header:
            current_group = {"date_header": date_header, "events": []}
            date_groups.append(current_group)
        current_group["events"].append(event_data)

    return {
        "ok": True,
        "reason": None,
        "events": upcoming,
        "date_groups": date_groups,
        "total": len(upcoming),
    }


async def get_game_tips_data(
    event_id: str,
    user_id: int,
) -> dict[str, Any]:
    """Fetch odds and calculate EV for a specific game.

    Returns dict with:
    - ok: bool
    - reason: str | None
    - home, away, kickoff
    - tips: list of {outcome, odds, bookie, bookie_key, ev, prob, event_id, home_team, away_team}
    - odds_context: str (for Claude prompt)
    """
    from scripts.sports_data import fetch_events_for_league
    from scripts.odds_client import fetch_odds_cached, fair_probabilities, find_best_sa_odds, calculate_ev

    prefs = await db.get_user_sport_prefs(user_id)
    league_keys = list({p.league for p in prefs if p.league})

    target_event = None
    target_league = None
    for lk in league_keys:
        if not config.SPORTS_MAP.get(lk):
            continue  # Skip leagues without an Odds API key
        events = await fetch_events_for_league(lk)
        for event in events:
            if event.get("id") == event_id:
                target_event = event
                target_league = lk
                break
        if target_event:
            break

    if not target_event:
        return {"ok": False, "reason": "not_found", "home": "?", "away": "?", "kickoff": "", "tips": [], "odds_context": ""}

    home = target_event.get("home_team", "?")
    away = target_event.get("away_team", "?")

    try:
        ct = datetime.fromisoformat(target_event["commence_time"].replace("Z", "+00:00"))
        kickoff = ct.strftime("%a %d %b, %H:%M")
    except Exception:
        kickoff = "TBC"

    # Fetch odds
    api_key = config.SPORTS_MAP.get(target_league, target_league)
    odds_result = await fetch_odds_cached(api_key, regions="eu,uk,au", markets="h2h")

    if not odds_result["ok"]:
        return {"ok": False, "reason": "no_odds", "home": home, "away": away, "kickoff": kickoff, "tips": [], "odds_context": ""}

    event_odds = None
    for ev in (odds_result["data"] or []):
        if ev.get("id") == event_id:
            event_odds = ev
            break

    if not event_odds or not event_odds.get("bookmakers"):
        return {"ok": False, "reason": "no_bookmakers", "home": home, "away": away, "kickoff": kickoff, "tips": [], "odds_context": ""}

    # Compute fair probabilities and find best SA odds
    fair_probs = fair_probabilities(event_odds)
    best_entries = find_best_sa_odds(event_odds)

    tips: list[dict] = []
    for entry in best_entries:
        prob = fair_probs.get(entry.outcome, 0)
        if prob <= 0:
            continue
        ev_pct = calculate_ev(entry.price, prob)
        implied = round(prob * 100)
        tips.append({
            "outcome": entry.outcome,
            "odds": entry.price,
            "bookie": entry.bookmaker,
            "bookie_key": getattr(entry, "bookmaker", "").lower().replace(" ", ""),
            "ev": round(ev_pct, 1),
            "prob": implied,
            "event_id": event_id,
            "home_team": home,
            "away_team": away,
        })

    tips.sort(key=lambda t: t["ev"], reverse=True)

    odds_context = "\n".join(
        f"- {t['outcome']}: {t['odds']:.2f} ({t['bookie']}), "
        f"fair prob {t['prob']}%, EV {t['ev']:+.1f}%"
        for t in tips
    ) if tips else "No SA bookmaker odds available."

    return {
        "ok": True,
        "reason": None,
        "home": home,
        "away": away,
        "kickoff": kickoff,
        "tips": tips,
        "odds_context": odds_context,
    }
