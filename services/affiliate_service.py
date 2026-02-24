"""Affiliate link service for multi-bookmaker odds display.

Given a match with odds from multiple bookmakers, returns the best affiliate
link — prioritising bookmakers with active affiliate status and best odds.
"""

from __future__ import annotations

import logging

import config
from services.analytics import track as analytics_track

log = logging.getLogger("mzansiedge.affiliate")


def get_affiliate_url(bookmaker_key: str) -> str:
    """Build the affiliate URL for a bookmaker.

    If the bookmaker has an active affiliate with a code, appends the tag.
    Otherwise returns the base homepage URL.
    """
    aff = config.BOOKMAKER_AFFILIATES.get(bookmaker_key)
    if not aff:
        # Unknown bookmaker — try SA_BOOKMAKERS for a homepage
        sa = config.SA_BOOKMAKERS.get(bookmaker_key)
        return sa["website_url"] if sa else ""

    base = aff["base_url"]
    code = aff.get("affiliate_code")
    template = aff.get("deep_link_template")

    if aff["status"] == "active" and code:
        if template:
            return template.format(affiliate_code=code)
        # Default: append btag param
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}btag={code}"

    # No active affiliate — just the homepage
    return base


def select_best_bookmaker(
    odds_by_bookmaker: dict[str, float],
    user_id: int | None = None,
    match_id: str | None = None,
) -> dict:
    """Select the best bookmaker for a tip based on odds and affiliate status.

    Args:
        odds_by_bookmaker: dict mapping bookmaker_key → decimal odds (e.g. {"betway": 2.10, "hollywoodbets": 2.15})
        user_id: optional Telegram user ID for analytics
        match_id: optional match/event ID for analytics

    Returns:
        dict with keys: bookmaker_key, bookmaker_name, odds, affiliate_url, has_active_affiliate
    """
    if not odds_by_bookmaker:
        return {
            "bookmaker_key": None,
            "bookmaker_name": None,
            "odds": None,
            "affiliate_url": "",
            "has_active_affiliate": False,
        }

    # Sort by odds descending (best odds first)
    sorted_books = sorted(odds_by_bookmaker.items(), key=lambda x: x[1], reverse=True)

    # First pass: find the best-odds bookmaker with an active affiliate
    for bk_key, odds in sorted_books:
        aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
        if aff and aff["status"] == "active":
            result = _build_result(bk_key, odds, has_active=True)
            _track_shown(user_id, match_id, bk_key, odds, active=True)
            return result

    # Second pass: no active affiliates — use the best-odds bookmaker with a generic link
    best_key, best_odds = sorted_books[0]
    result = _build_result(best_key, best_odds, has_active=False)
    _track_shown(user_id, match_id, best_key, best_odds, active=False)
    return result


def get_runner_up_odds(
    odds_by_bookmaker: dict[str, float],
    exclude_key: str,
    max_others: int = 3,
) -> list[dict]:
    """Get runner-up bookmaker odds for the 'Also:' line.

    Returns list of dicts with bookmaker_name and odds, sorted by odds descending.
    """
    others = []
    for bk_key, odds in sorted(odds_by_bookmaker.items(), key=lambda x: x[1], reverse=True):
        if bk_key == exclude_key:
            continue
        aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
        sa = config.SA_BOOKMAKERS.get(bk_key)
        name = (aff or {}).get("name") or (sa or {}).get("short_name") or bk_key.title()
        others.append({"bookmaker_key": bk_key, "bookmaker_name": name, "odds": odds})
        if len(others) >= max_others:
            break
    return others


def _build_result(bk_key: str, odds: float, has_active: bool) -> dict:
    aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
    sa = config.SA_BOOKMAKERS.get(bk_key)
    name = (aff or {}).get("name") or (sa or {}).get("short_name") or bk_key.title()
    return {
        "bookmaker_key": bk_key,
        "bookmaker_name": name,
        "odds": odds,
        "affiliate_url": get_affiliate_url(bk_key),
        "has_active_affiliate": has_active,
    }


def _track_shown(
    user_id: int | None,
    match_id: str | None,
    bk_key: str,
    odds: float,
    active: bool,
) -> None:
    if user_id:
        analytics_track(user_id, "affiliate_link_shown", {
            "bookmaker": bk_key,
            "odds": odds,
            "has_active_affiliate": active,
            "match_id": match_id or "",
        })
