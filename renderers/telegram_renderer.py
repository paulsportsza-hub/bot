"""MzansiEdge — Telegram renderer.

Formats service-layer data as Telegram HTML messages with InlineKeyboardMarkup.
This module concentrates all Telegram-specific rendering that was previously
spread across bot.py.
"""

from __future__ import annotations

from typing import Any

import config


def render_profile_summary(data: dict[str, Any]) -> str:
    """Render user profile data as Telegram HTML.

    Args:
        data: Profile dict from services.user_service.get_profile_data()
    """
    lines = ["\U0001f4cb <b>Your MzansiEdge Profile</b>\n"]
    lines.append(f"\U0001f3af Experience: {data['experience_label']}\n")

    for sport in data["sports"]:
        lines.append(f"{sport['emoji']} <b>{sport['label']}</b>")
        if len(sport["leagues"]) <= 1:
            all_t: list[str] = []
            for lg in sport["leagues"]:
                all_t.extend(lg["teams"])
            if all_t:
                lines.append(f"  {', '.join(all_t)}")
        else:
            for lg in sport["leagues"]:
                if lg["label"] and lg["teams"]:
                    lines.append(f"  {lg['label']}: {', '.join(lg['teams'])}")
                elif lg["label"]:
                    lines.append(f"  {lg['label']}")
                elif lg["teams"]:
                    lines.append(f"  {', '.join(lg['teams'])}")
        lines.append("")

    lines.append(f"\u2696\ufe0f <b>Risk:</b> {data['risk_label']}")
    lines.append(f"\U0001f4b0 <b>Bankroll:</b> {data['bankroll_str']}")
    lines.append(f"\U0001f514 <b>Daily picks:</b> {data['notify_str']}")

    return "\n".join(lines)


def render_schedule(data: dict[str, Any]) -> str:
    """Render schedule data as Telegram HTML.

    Args:
        data: Schedule dict from services.schedule_service.get_schedule()
    """
    if not data["ok"]:
        if data["reason"] == "no_leagues":
            return (
                "\U0001f3df\ufe0f <b>No leagues selected!</b>\n\n"
                "Update your sports in /settings."
            )
        return (
            "\U0001f4c5 <b>No upcoming games found</b>\n\n"
            "None of your followed teams have scheduled games right now. "
            "Check back later or add more teams in /settings."
        )

    lines = [f"\U0001f4c5 <b>Upcoming Games ({data['total']})</b>\n"]
    for group in data["date_groups"]:
        lines.append(f"\n<b>{group['date_header']}</b>")
        for ev in group["events"]:
            home = f"<b>{ev['home']}</b>" if ev["home_bold"] else ev["home"]
            away = f"<b>{ev['away']}</b>" if ev["away_bold"] else ev["away"]
            lines.append(f"{ev['idx']}. {ev['emoji']} {ev['time']}  {home} vs {away}")

    return "\n".join(lines)


def render_picks_header(data: dict[str, Any]) -> str:
    """Render picks header as Telegram HTML."""
    picks = data["picks"]
    return (
        f"\U0001f4b0 <b>Found {len(picks)} value bet{'s' if len(picks) != 1 else ''}!</b>\n\n"
        f"\U0001f4ca Scanned {data['total_events']} events | "
        f"{data['total_markets']} markets\n"
        f"\u2696\ufe0f Risk: {data['risk_label']}\n"
        f"<i>API quota: {data.get('quota_remaining', '?')} remaining</i>"
    )


def render_no_picks(data: dict[str, Any]) -> str:
    """Render 'no picks found' message as Telegram HTML."""
    experience = data.get("experience", "casual")
    if experience == "newbie":
        return (
            "\U0001f4ed <b>No value bets found right now</b>\n\n"
            f"Scanned {data['total_events']} events across your leagues.\n\n"
            "This means bookmaker odds are fair \u2014 no easy edges today.\n"
            "Check back later! We scan markets throughout the day.\n\n"
            f"<i>API quota: {data.get('quota_remaining', '?')} remaining</i>"
        )
    return (
        "\U0001f4ed <b>No value bets found right now</b>\n\n"
        f"Scanned {data['total_events']} events | "
        f"{data['total_markets']} markets\n\n"
        f"No edges meeting your {data['risk_label']} profile.\n"
        "This is the AI protecting your bankroll \u2014 "
        "check back when more markets open or adjust your risk in /settings.\n\n"
        f"<i>API quota: {data.get('quota_remaining', '?')} remaining</i>"
    )


def render_game_tips(data: dict[str, Any], narrative: str = "") -> str:
    """Render game tips as Telegram HTML.

    Args:
        data: Tips dict from services.schedule_service.get_game_tips_data()
        narrative: Optional AI-generated analysis text
    """
    lines = [
        f"\U0001f3af <b>{data['home']} vs {data['away']}</b>",
        f"\u23f0 {data['kickoff']}\n",
    ]

    if narrative:
        lines.append(narrative)
        lines.append("")

    tips = data.get("tips", [])
    if not tips:
        lines.append("No SA bookmaker odds available for this game yet.")
    else:
        lines.append("<b>SA Bookmaker Odds:</b>")
        for tip in tips:
            ev_ind = f"+{tip['ev']}%" if tip["ev"] > 0 else f"{tip['ev']}%"
            value_marker = " \U0001f4b0" if tip["ev"] > 2 else ""
            lines.append(
                f"  {tip['outcome']}: <b>{tip['odds']:.2f}</b> "
                f"({tip['bookie']} | {tip['prob']}% | EV: {ev_ind}){value_marker}"
            )

    return "\n".join(lines)


def render_tip_detail(tip: dict, experience: str, bankroll: float | None = None) -> str:
    """Render a single tip detail page as Telegram HTML.

    Adapts output based on experience level.
    """
    outcome = tip.get("outcome", "?")
    odds = tip.get("odds", 0.0)
    ev = tip.get("ev", 0.0)
    prob = tip.get("prob", 0)
    bookie = tip.get("bookie", "?")
    home = tip.get("home_team", "?")
    away = tip.get("away_team", "?")

    if experience == "experienced":
        stake_info = ""
        if bankroll:
            from scripts.odds_client import kelly_stake
            ks = kelly_stake(odds, prob / 100.0, fraction=0.5)
            stake = ks * bankroll
            potential = stake * odds
            profit = stake * (odds - 1)
            stake_info = (
                f"\n\U0001f4b5 Kelly: R{stake:,.0f} \u2192 R{potential:,.0f} "
                f"(+R{profit:,.0f})"
            )
        return (
            f"\U0001f3af <b>{home} vs {away}</b>\n\n"
            f"\U0001f4cc <b>{outcome}</b> @ <b>{odds:.2f}</b> ({bookie})\n"
            f"\U0001f4c8 EV: <b>+{ev}%</b> | Sharp prob: {prob}%"
            f"{stake_info}"
        )

    elif experience == "newbie":
        payout_20 = odds * 20
        payout_50 = odds * 50
        return (
            f"\U0001f3af <b>{home} vs {away}</b>\n\n"
            f"\U0001f4cc Bet on: <b>{outcome}</b>\n"
            f"\U0001f4b0 Odds: <b>{odds:.2f}</b> at {bookie}\n\n"
            f"\U0001f4b5 Bet R20 \u2192 get <b>R{payout_20:.0f}</b> back\n"
            f"\U0001f4b5 Bet R50 \u2192 get <b>R{payout_50:.0f}</b> back\n\n"
            f"\U0001f4a1 <i>Start small: R20-50 per bet while learning.</i>"
        )

    else:  # casual
        payout_100 = odds * 100
        return (
            f"\U0001f3af <b>{home} vs {away}</b>\n\n"
            f"\U0001f4cc <b>{outcome}</b> @ {odds:.2f} ({bookie})\n"
            f"The AI found a <b>+{ev}%</b> edge \u2014 confidence {prob}%.\n\n"
            f"\U0001f4b5 R100 bet pays <b>R{payout_100:.0f}</b>"
        )
