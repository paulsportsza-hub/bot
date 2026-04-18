"""MzansiEdge — User service (platform-agnostic).

Handles user profile logic: archetype classification, profile summaries,
onboarding persistence, preference management.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import config
import db


def _infer_leagues_for_team(team: str, sport_key: str) -> list[str]:
    """Auto-infer league keys for a team within a specific sport.

    1. Check NATIONAL_TEAM_LEAGUES[sport_key][team] first (sport-specific)
    2. Check TEAM_TO_LEAGUES[team] filtered by LEAGUE_SPORT[lg] == sport_key
    3. Append NATIONAL_TEAM_BONUS_LEAGUES (domestic franchise leagues)
    4. Returns empty list if no mapping found
    """
    # 1. Sport-specific national team mapping
    national = config.NATIONAL_TEAM_LEAGUES.get(sport_key, {})
    if team in national:
        leagues = list(national[team])
    else:
        # 2. Generic reverse lookup filtered by sport
        all_leagues = config.TEAM_TO_LEAGUES.get(team, [])
        leagues = [lg for lg in all_leagues if config.LEAGUE_SPORT.get(lg) == sport_key]

    # 3. Add bonus domestic leagues for national teams
    bonus = config.NATIONAL_TEAM_BONUS_LEAGUES.get(sport_key, {}).get(team, [])
    for lg in bonus:
        if lg not in leagues:
            leagues.append(lg)

    return leagues


def resolve_user_league_keys(prefs) -> tuple[set, set]:
    """Return (user_teams, league_keys) with auto-inference for prefs with league=None.

    Canonical source for both _render_your_games_all and _fetch_schedule_games.
    FIX-MY-MATCHES-INFERENCE-01.
    """
    user_teams: set = set()
    league_keys: set = set()
    for pref in prefs:
        if pref.team_name:
            user_teams.add(pref.team_name.lower())
        if pref.league:
            league_keys.add(pref.league)
        elif pref.team_name:
            team_name = pref.team_name
            inferred = config.TEAM_TO_LEAGUES.get(team_name, [])
            if not inferred:
                canonical = config.TEAM_ALIASES.get(team_name.lower(), "")
                if canonical:
                    inferred = config.TEAM_TO_LEAGUES.get(canonical, [])
            sport_key = pref.sport_key or ""
            for ilk in inferred:
                if not sport_key or config.LEAGUE_SPORT.get(ilk) == sport_key:
                    league_keys.add(ilk)
    return user_teams, league_keys


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
            lg_label = lg.label if lg else pref.league
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
    notify_map = {7: "Morning (07:00 SAST)", 12: "Midday (12:00 SAST)", 18: "Evening (18:00 SAST)", 21: "Night (21:00 SAST)"}
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

    Favourites are now flat lists per sport: ob["favourites"][sk] = [name, ...].
    Leagues are auto-inferred from team names using TEAM_TO_LEAGUES and
    NATIONAL_TEAM_LEAGUES for sport-specific national team disambiguation.

    Returns (archetype, engagement_score).
    """
    await db.clear_user_sport_prefs(user_id)

    for sk in ob["selected_sports"]:
        favs = ob["favourites"].get(sk, [])

        # Handle legacy dict-of-dicts format
        if isinstance(favs, dict):
            flat: list[str] = []
            for teams in favs.values():
                flat.extend(teams)
            favs = flat

        if favs:
            for team in favs:
                # Auto-infer leagues for this team
                inferred_leagues = _infer_leagues_for_team(team, sk)
                if inferred_leagues:
                    for lg_key in inferred_leagues:
                        await db.save_sport_pref(user_id, sk, league=lg_key, team_name=team)
                else:
                    # No league mapping found — save without league
                    await db.save_sport_pref(user_id, sk, team_name=team)
        else:
            # No teams for this sport — just save the sport preference
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


async def backfill_bonus_leagues() -> int:
    """Retroactively add bonus domestic leagues for existing users with national teams.

    Scans all sport prefs. For each national team that has bonus leagues defined
    in NATIONAL_TEAM_BONUS_LEAGUES, checks if the user already has a pref row
    for that bonus league + team. If not, creates one.

    Returns the number of bonus prefs added.
    """
    import logging
    log = logging.getLogger(__name__)

    all_prefs = await db.get_all_sport_prefs()

    # Build lookup: (user_id, sport_key, league, team_name) → exists
    existing = set()
    for p in all_prefs:
        if p.team_name and p.league:
            existing.add((p.user_id, p.sport_key, p.league, p.team_name))

    added = 0
    for p in all_prefs:
        if not p.team_name:
            continue
        bonus = config.NATIONAL_TEAM_BONUS_LEAGUES.get(p.sport_key, {}).get(p.team_name, [])
        for lg in bonus:
            key = (p.user_id, p.sport_key, lg, p.team_name)
            if key not in existing:
                await db.save_sport_pref(p.user_id, p.sport_key, league=lg, team_name=p.team_name)
                existing.add(key)
                added += 1

    if added:
        log.info("Backfilled %d bonus league prefs for national teams", added)
    return added


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
