"""MzansiEdge — User service (platform-agnostic).

Handles user profile logic: archetype classification, profile summaries,
onboarding persistence, preference management.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import config
import db


def classify_archetype(
    experience: str, risk: str, num_sports: int,
) -> tuple[str, float]:
    """Classify user into an archetype with engagement score.

    Returns (archetype, engagement_score) where:
    - eager_bettor: experienced + aggressive/moderate, many sports
    - casual_fan: casual experience or conservative risk
    - complete_newbie: newbie experience level
    """
    if experience == "newbie":
        return "complete_newbie", 3.0
    score = 5.0
    if experience == "experienced":
        score += 2.0
    if risk == "aggressive":
        score += 2.0
    elif risk == "moderate":
        score += 1.0
    if num_sports >= 3:
        score += 1.0
    if experience == "experienced" and risk in ("aggressive", "moderate"):
        return "eager_bettor", min(score, 10.0)
    return "casual_fan", min(score, 10.0)


async def get_profile_data(user_id: int) -> dict[str, Any]:
    """Fetch and structure user profile data.

    Returns a dict with all profile fields needed for rendering:
    - experience, experience_label
    - sports (list of {key, label, emoji, leagues: [{label, teams}]})
    - risk, risk_label
    - bankroll, bankroll_str
    - notify_hour, notify_str
    - archetype, engagement_score
    """
    user = await db.get_user(user_id)
    prefs = await db.get_user_sport_prefs(user_id)

    # Experience
    exp_labels = {
        "experienced": "I bet regularly",
        "casual": "I bet sometimes",
        "newbie": "I'm new to betting",
    }
    exp = (user.experience_level if user else None) or "casual"

    # Group prefs by sport → league → teams
    sport_leagues: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    sport_order: list[str] = []
    for pref in prefs:
        sk = pref.sport_key
        if sk not in sport_order:
            sport_order.append(sk)
        lg_label = ""
        if pref.league:
            lg = config.ALL_LEAGUES.get(pref.league)
            lg_label = _abbreviate_league(lg.label) if lg else pref.league
        if pref.team_name:
            sport_leagues[sk][lg_label].append(pref.team_name)
        elif lg_label:
            sport_leagues[sk].setdefault(lg_label, [])

    sports_data: list[dict] = []
    for sk in sport_order:
        sport = config.ALL_SPORTS.get(sk)
        league_dict = sport_leagues.get(sk, {})
        leagues_list: list[dict] = []
        for lg_name, teams in league_dict.items():
            leagues_list.append({"label": lg_name, "teams": teams})
        sports_data.append({
            "key": sk,
            "label": sport.label if sport else sk,
            "emoji": sport.emoji if sport else "\U0001f3c5",
            "leagues": leagues_list,
        })

    # Risk
    risk = (user.risk_profile if user else None) or "moderate"
    risk_raw = config.RISK_PROFILES.get(risk, {}).get("label", risk)
    risk_label = risk_raw.split(" ", 1)[-1] if " " in risk_raw else risk_raw

    # Bankroll
    bankroll = getattr(user, "bankroll", None) if user else None
    bankroll_str = f"R{bankroll:,.0f}" if bankroll else "Not set"

    # Notification hour
    hour = user.notification_hour if user else None
    notify_map = {7: "Morning (7 AM)", 12: "Midday (12 PM)", 18: "Evening (6 PM)", 21: "Night (9 PM)"}
    notify_str = notify_map.get(hour, f"{hour}:00") if hour is not None else "Not set"

    return {
        "experience": exp,
        "experience_label": exp_labels.get(exp, exp),
        "sports": sports_data,
        "risk": risk,
        "risk_label": risk_label,
        "bankroll": bankroll,
        "bankroll_str": bankroll_str,
        "notify_hour": hour,
        "notify_str": notify_str,
        "archetype": getattr(user, "archetype", None) if user else None,
        "engagement_score": getattr(user, "engagement_score", None) if user else None,
    }


async def persist_onboarding(user_id: int, ob: dict) -> tuple[str, float]:
    """Save all onboarding data to DB and classify archetype.

    Returns (archetype, engagement_score).
    """
    await db.clear_user_sport_prefs(user_id)

    for sk in ob["selected_sports"]:
        leagues = ob["selected_leagues"].get(sk, [])
        favs_dict = ob["favourites"].get(sk, {})

        if isinstance(favs_dict, list):
            favs_dict = {"": favs_dict}

        if leagues:
            for lg_key in leagues:
                teams = favs_dict.get(lg_key, [])
                if teams:
                    for team in teams:
                        await db.save_sport_pref(user_id, sk, league=lg_key, team_name=team)
                else:
                    await db.save_sport_pref(user_id, sk, league=lg_key)
        else:
            all_teams: list[str] = []
            for teams in favs_dict.values():
                all_teams.extend(teams)
            if all_teams:
                for team in all_teams:
                    await db.save_sport_pref(user_id, sk, team_name=team)
            else:
                await db.save_sport_pref(user_id, sk)

    if ob["risk"]:
        await db.update_user_risk(user_id, ob["risk"])
    if ob.get("bankroll") is not None:
        await db.update_user_bankroll(user_id, ob["bankroll"])
    if ob.get("notify_hour") is not None:
        await db.update_user_notification_hour(user_id, ob["notify_hour"])
    if ob.get("experience"):
        await db.update_user_experience(user_id, ob["experience"])

    archetype, eng_score = classify_archetype(
        ob.get("experience", "casual"),
        ob.get("risk", "moderate"),
        len(ob.get("selected_sports", [])),
    )
    await db.update_user_archetype(user_id, archetype, eng_score)
    await db.set_onboarding_done(user_id)

    return archetype, eng_score


async def get_user_league_keys(user_id: int) -> list[str]:
    """Get the user's preferred league keys, falling back to all leagues."""
    prefs = await db.get_user_sport_prefs(user_id)
    if prefs:
        return list({p.league for p in prefs if p.league})
    return list(config.SPORTS_MAP.keys())


async def get_user_teams(user_id: int) -> set[str]:
    """Get the user's followed team names (lowercased)."""
    prefs = await db.get_user_sport_prefs(user_id)
    return {p.team_name.lower() for p in prefs if p.team_name}


def _abbreviate_league(label: str) -> str:
    """Shorten long league names for compact display."""
    abbrevs = {
        "Champions League": "UCL",
        "Six Nations": "6N",
        "Rugby Championship": "RC",
        "CSA / SA20": "SA20",
        "T20 World Cup": "T20WC",
        "Grand Slams": "GS",
        "DP World Tour": "DPWT",
        "Super Rugby": "Super",
    }
    return abbrevs.get(label, label)
