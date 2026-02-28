"""Edge Rating renderer — formats tips with multi-bookmaker odds display."""

from __future__ import annotations

from datetime import datetime
from html import escape as h
from zoneinfo import ZoneInfo

import config

EDGE_EMOJIS: dict[str, str] = {
    "diamond": "\U0001f48e",  # 💎
    "gold": "\U0001f947",     # 🥇
    "silver": "\U0001f948",   # 🥈
    "bronze": "\U0001f949",   # 🥉
}

EDGE_LABELS: dict[str, str] = {
    "diamond": "DIAMOND EDGE",
    "gold": "GOLDEN EDGE",
    "silver": "SILVER EDGE",
    "bronze": "BRONZE EDGE",
}


def render_edge_badge(rating: str) -> str:
    """Returns e.g. '💎 DIAMOND EDGE' or '🥇 GOLDEN EDGE'."""
    emoji = EDGE_EMOJIS.get(rating, "")
    label = EDGE_LABELS.get(rating, "")
    if emoji and label:
        return f"{emoji} {label}"
    return ""


def render_tip_with_odds(
    match: dict,
    odds_by_bookmaker: dict[str, float],
    edge_rating: str,
    best_bookmaker: dict,
    runner_ups: list[dict] | None = None,
    predicted_outcome: str = "",
) -> str:
    """Render a single tip card with multi-bookmaker odds.

    Args:
        match: dict with keys: home_team, away_team, league, commence_time, sport_emoji
        odds_by_bookmaker: dict mapping bookmaker_key → decimal odds for the predicted outcome
        edge_rating: EdgeRating string (diamond/gold/silver/bronze)
        best_bookmaker: dict from affiliate_service.select_best_bookmaker()
        runner_ups: list from affiliate_service.get_runner_up_odds()
        predicted_outcome: human-readable outcome string (e.g. "Chiefs to Win")

    Returns:
        HTML-formatted tip string for Telegram.
    """
    lines = []

    # Edge badge
    badge = render_edge_badge(edge_rating)
    if badge:
        lines.append(f"<b>{badge}</b>")

    # Match header
    home_raw = match.get("home_team", "Home")
    away_raw = match.get("away_team", "Away")
    home = h(home_raw)
    away = h(away_raw)
    hf = config.get_country_flag(home_raw)
    af = config.get_country_flag(away_raw)
    if hf and af:
        hf += " "
        af += " "
    else:
        hf = af = ""
    sport_emoji = match.get("sport_emoji", "\u26bd")
    lines.append(f"{sport_emoji} <b>{hf}{home} vs {af}{away}</b>")

    # League + kickoff
    league = match.get("league", "")
    kickoff = _format_kickoff(match.get("commence_time"))
    if league and kickoff:
        lines.append(f"\U0001f3c6 {league} \u2014 {kickoff}")
    elif league:
        lines.append(f"\U0001f3c6 {league}")
    elif kickoff:
        lines.append(f"\U0001f4c5 {kickoff}")

    lines.append("")  # blank line

    # Best odds line
    if best_bookmaker and best_bookmaker.get("odds"):
        bk_name = best_bookmaker["bookmaker_name"]
        odds = best_bookmaker["odds"]
        outcome_label = predicted_outcome or "Prediction"
        lines.append(f"<b>Best Odds:</b> {outcome_label} @ {odds:.2f} ({bk_name})")
    elif predicted_outcome:
        lines.append(f"<b>Pick:</b> {predicted_outcome}")

    # Runner-up odds
    if runner_ups:
        also_parts = [f"{r['bookmaker_name']} {r['odds']:.2f}" for r in runner_ups]
        lines.append(f"<i>Also: {' | '.join(also_parts)}</i>")

    return "\n".join(lines)


def render_tip_button_label(best_bookmaker: dict) -> str:
    """Render the CTA button label for a tip.

    Returns e.g. 'Bet on Hollywoodbets →' or 'Bet Now →'.
    """
    if best_bookmaker and best_bookmaker.get("bookmaker_name"):
        return f"Bet on {best_bookmaker['bookmaker_name']} \u2192"
    return "Bet Now \u2192"


def render_odds_comparison(odds_by_bookmaker: dict[str, float], predicted_outcome: str = "") -> str:
    """Render a compact odds comparison table for display.

    Returns HTML like:
    📊 <b>Odds Comparison</b>
    Hollywoodbets: 2.15
    Betway: 2.10
    Sportingbet: 2.05
    """
    if not odds_by_bookmaker:
        return ""

    sorted_odds = sorted(odds_by_bookmaker.items(), key=lambda x: x[1], reverse=True)
    lines = ["\U0001f4ca <b>Odds Comparison</b>"]
    if predicted_outcome:
        lines[0] += f" \u2014 {predicted_outcome}"

    for bk_key, odds in sorted_odds:
        aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
        sa = config.SA_BOOKMAKERS.get(bk_key)
        name = (aff or {}).get("name") or (sa or {}).get("short_name") or bk_key.title()
        # Mark the best with a star
        marker = "\u2b50 " if bk_key == sorted_odds[0][0] else "  "
        lines.append(f"{marker}{name}: <b>{odds:.2f}</b>")

    return "\n".join(lines)


def _format_kickoff(commence_time) -> str:
    """Format commence_time as 'Sat 1 Mar, 15:00' in SAST."""
    if not commence_time:
        return ""

    tz = ZoneInfo(config.TZ)

    if isinstance(commence_time, str):
        try:
            dt_obj = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return commence_time
    elif isinstance(commence_time, datetime):
        dt_obj = commence_time
    else:
        return str(commence_time)

    local = dt_obj.astimezone(tz)
    return local.strftime("%a %-d %b, %H:%M")
