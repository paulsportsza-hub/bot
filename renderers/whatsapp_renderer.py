"""MzansiEdge — WhatsApp renderer (placeholder).

Formats service-layer data as WhatsApp-safe plain text messages.
WhatsApp supports limited formatting: *bold*, _italic_, ~strikethrough~, ```monospace```.
Max 3 interactive buttons per message. No HTML.

This is a placeholder for the WhatsApp Business API integration.
"""

from __future__ import annotations

from typing import Any


def render_profile_summary(data: dict[str, Any]) -> str:
    """Render user profile data as WhatsApp plain text."""
    lines = ["*Your MzansiEdge Profile*\n"]
    lines.append(f"Experience: {data['experience_label']}\n")

    for sport in data["sports"]:
        lines.append(f"{sport['emoji']} *{sport['label']}*")
        for lg in sport["leagues"]:
            if lg["label"] and lg["teams"]:
                lines.append(f"  {lg['label']}: {', '.join(lg['teams'])}")
            elif lg["label"]:
                lines.append(f"  {lg['label']}")
            elif lg["teams"]:
                lines.append(f"  {', '.join(lg['teams'])}")
        lines.append("")

    lines.append(f"Risk: {data['risk_label']}")
    lines.append(f"Bankroll: {data['bankroll_str']}")
    lines.append(f"Daily picks: {data['notify_str']}")

    return "\n".join(lines)


def render_schedule(data: dict[str, Any]) -> str:
    """Render schedule data as WhatsApp plain text."""
    if not data["ok"]:
        if data["reason"] == "no_leagues":
            return "No leagues selected! Reply SETTINGS to update your sports."
        return (
            "No upcoming games found.\n\n"
            "None of your followed teams have scheduled games right now. "
            "Check back later or reply SETTINGS to add more teams."
        )

    lines = [f"*Upcoming Games ({data['total']})*\n"]
    for group in data["date_groups"]:
        lines.append(f"\n*{group['date_header']}*")
        for ev in group["events"]:
            home = f"*{ev['home']}*" if ev["home_bold"] else ev["home"]
            away = f"*{ev['away']}*" if ev["away_bold"] else ev["away"]
            lines.append(f"{ev['idx']}. {ev['emoji']} {ev['time']}  {home} vs {away}")

    return "\n".join(lines)


def render_picks_header(data: dict[str, Any]) -> str:
    """Render picks header as WhatsApp plain text."""
    picks = data["picks"]
    return (
        f"*Found {len(picks)} value bet{'s' if len(picks) != 1 else ''}!*\n\n"
        f"Scanned {data['total_events']} events | "
        f"{data['total_markets']} markets\n"
        f"Risk: {data['risk_label']}"
    )


def render_no_picks(data: dict[str, Any]) -> str:
    """Render 'no picks found' message as WhatsApp plain text."""
    return (
        "*No value bets found right now*\n\n"
        f"Scanned {data['total_events']} events.\n\n"
        "Bookmaker odds are fair today — no easy edges. "
        "Check back later!"
    )


def render_game_tips(data: dict[str, Any], narrative: str = "") -> str:
    """Render game tips as WhatsApp plain text."""
    lines = [
        f"*{data['home']} vs {data['away']}*",
        f"Kickoff: {data['kickoff']}\n",
    ]

    if narrative:
        # Strip HTML tags for WhatsApp
        import re
        clean = re.sub(r"<[^>]+>", "", narrative)
        lines.append(clean)
        lines.append("")

    tips = data.get("tips", [])
    if not tips:
        lines.append("No SA bookmaker odds available yet.")
    else:
        lines.append("*SA Bookmaker Odds:*")
        for tip in tips:
            ev_ind = f"+{tip['ev']}%" if tip["ev"] > 0 else f"{tip['ev']}%"
            lines.append(
                f"  {tip['outcome']}: {tip['odds']:.2f} "
                f"({tip['bookie']} | EV: {ev_ind})"
            )

    return "\n".join(lines)


def render_tip_detail(tip: dict, experience: str, bankroll: float | None = None) -> str:
    """Render a single tip detail as WhatsApp plain text."""
    outcome = tip.get("outcome", "?")
    odds = tip.get("odds", 0.0)
    ev = tip.get("ev", 0.0)
    prob = tip.get("prob", 0)
    bookie = tip.get("bookie", "?")
    home = tip.get("home_team", "?")
    away = tip.get("away_team", "?")

    payout_100 = odds * 100

    return (
        f"*{home} vs {away}*\n\n"
        f"Pick: *{outcome}* @ {odds:.2f} ({bookie})\n"
        f"Edge: +{ev}% | Confidence: {prob}%\n"
        f"R100 bet pays R{payout_100:.0f}\n\n"
        "_Always gamble responsibly._"
    )


# ── WhatsApp button helpers ──────────────────────────────

def menu_buttons() -> list[dict]:
    """Return main menu as WhatsApp interactive buttons (max 3).

    WhatsApp Business API format:
    [{"id": "action_id", "title": "Button Text"}]
    """
    return [
        {"id": "picks", "title": "Today's Picks"},
        {"id": "schedule", "title": "Schedule"},
        {"id": "settings", "title": "Settings"},
    ]


def picks_buttons() -> list[dict]:
    """Buttons shown after picks display."""
    return [
        {"id": "schedule", "title": "Schedule"},
        {"id": "menu", "title": "Main Menu"},
    ]
