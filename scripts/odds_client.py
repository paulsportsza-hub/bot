"""Async client for The Odds API — fetches live & upcoming odds for SA sports."""

from __future__ import annotations

import httpx

import config


async def fetch_odds(
    sport_key: str,
    regions: str = "eu",
    markets: str = "h2h",
    odds_format: str = "decimal",
) -> list[dict]:
    """Return a list of event dicts with bookmaker odds.

    Each event dict contains keys: id, sport_key, commence_time,
    home_team, away_team, bookmakers.
    """
    url = f"{config.ODDS_BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def fetch_sports() -> list[dict]:
    """Return all in-season sports available on The Odds API."""
    url = f"{config.ODDS_BASE_URL}/sports"
    params = {"apiKey": config.ODDS_API_KEY}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def best_odds(event: dict, market: str = "h2h") -> dict[str, float]:
    """Extract the best available odds per outcome across all bookmakers.

    Returns e.g. {"Home Team": 2.10, "Away Team": 3.40, "Draw": 3.05}.
    """
    best: dict[str, float] = {}
    for bk in event.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt["outcomes"]:
                name = outcome["name"]
                price = outcome["price"]
                if name not in best or price > best[name]:
                    best[name] = price
    return best


def format_odds_message(events: list[dict], sport_label: str) -> str:
    """Build an HTML-formatted odds summary for Telegram."""
    if not events:
        return f"<b>{sport_label}</b>\n\nNo upcoming events found."

    lines = [f"<b>{sport_label} — Upcoming Odds</b>\n"]
    for ev in events[:8]:
        home = ev["home_team"]
        away = ev["away_team"]
        odds = best_odds(ev)
        odds_str = " | ".join(f"{k}: <b>{v:.2f}</b>" for k, v in odds.items())
        lines.append(f"\u26bd <b>{home}</b> vs <b>{away}</b>\n   {odds_str}\n")
    return "\n".join(lines)
