"""Affiliate link service for multi-bookmaker odds display.

Given a match with odds from multiple bookmakers, returns the best affiliate
link — prioritising deep links (direct match pages) over generic homepage URLs.
"""

from __future__ import annotations

import logging

import config
from services.analytics import track as analytics_track

log = logging.getLogger("mzansiedge.affiliate")

# Deep link helper — imported lazily to avoid circular deps at module load
_deep_links_available = True
try:
    from scrapers.deeplinks.deeplink_helper import (
        get_match_deep_links as _get_match_deep_links,
        get_single_deep_link as _get_single_deep_link,
    )
except ImportError:
    _deep_links_available = False
    _get_match_deep_links = None
    _get_single_deep_link = None

# Tier labels for button text
DEEP_LINK_TIERS = {1: "Bet Now", 2: "View {sport}", 3: "Visit"}


def get_affiliate_url(bookmaker_key: str, match_id: str | None = None) -> str:
    """Build the best URL for a bookmaker, preferring deep links.

    Priority: deep link (match page) → affiliate URL → homepage.
    """
    # Try deep link first
    if match_id and _deep_links_available and _get_single_deep_link:
        try:
            deep_url = _get_single_deep_link(match_id, bookmaker_key)
            if deep_url:
                return deep_url
        except Exception:
            pass  # Fall through to generic URL

    aff = config.BOOKMAKER_AFFILIATES.get(bookmaker_key)
    if not aff:
        sa = config.SA_BOOKMAKERS.get(bookmaker_key)
        return sa["website_url"] if sa else ""

    base = aff["base_url"]
    code = aff.get("affiliate_code")
    template = aff.get("deep_link_template")

    if aff["status"] == "active" and code:
        if template:
            return template.format(affiliate_code=code)
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}btag={code}"

    return base


def get_deep_link_tier(match_id: str, bookmaker_key: str) -> int:
    """Get the deep link tier (1=direct match, 2=league page, 3=homepage) or 0 if no deep link."""
    if not match_id or not _deep_links_available or not _get_match_deep_links:
        return 0
    try:
        links = _get_match_deep_links(match_id)
        info = links.get(bookmaker_key)
        return info["tier"] if info else 0
    except Exception:
        return 0


def get_cta_label(bookmaker_name: str, match_id: str | None = None, bookmaker_key: str = "", sport: str = "") -> str:
    """Build CTA button text based on deep link tier.

    Tier 1: 'Bet Now at Hollywoodbets →'
    Tier 2: 'View Soccer at Betway →'
    Tier 3: 'Visit GBets →'
    No deep link: 'Bet on {name} →'
    """
    tier = get_deep_link_tier(match_id, bookmaker_key) if match_id and bookmaker_key else 0
    if tier == 1:
        return f"Bet Now at {bookmaker_name} →"
    elif tier == 2:
        sport_label = sport.title() if sport else "Odds"
        return f"View {sport_label} at {bookmaker_name} →"
    elif tier == 3:
        return f"Visit {bookmaker_name} →"
    return f"Bet on {bookmaker_name} →"


def select_best_bookmaker(
    odds_by_bookmaker: dict[str, float],
    user_id: int | None = None,
    match_id: str | None = None,
) -> dict:
    """Select the best bookmaker for a tip based on odds and affiliate status.

    Deep links are preferred: if a bookmaker has a direct match page (Tier 1),
    it gets a bonus in selection. URL resolution uses deep links automatically.

    Args:
        odds_by_bookmaker: dict mapping bookmaker_key → decimal odds
        user_id: optional Telegram user ID for analytics
        match_id: optional match/event ID for deep link lookup + analytics

    Returns:
        dict with keys: bookmaker_key, bookmaker_name, odds, affiliate_url, has_active_affiliate, deep_link_tier
    """
    if not odds_by_bookmaker:
        return {
            "bookmaker_key": None,
            "bookmaker_name": None,
            "odds": None,
            "affiliate_url": "",
            "has_active_affiliate": False,
            "deep_link_tier": 0,
        }

    # Sort by odds descending (best odds first)
    sorted_books = sorted(odds_by_bookmaker.items(), key=lambda x: x[1], reverse=True)

    # First pass: find the best-odds bookmaker with an active affiliate
    for bk_key, odds in sorted_books:
        aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
        if aff and aff["status"] == "active":
            result = _build_result(bk_key, odds, has_active=True, match_id=match_id)
            _track_shown(user_id, match_id, bk_key, odds, active=True)
            return result

    # Second pass: no active affiliates — use the best-odds bookmaker with deep link preference
    best_key, best_odds = sorted_books[0]
    result = _build_result(best_key, best_odds, has_active=False, match_id=match_id)
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


def _build_result(bk_key: str, odds: float, has_active: bool, match_id: str | None = None) -> dict:
    aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
    sa = config.SA_BOOKMAKERS.get(bk_key)
    name = (aff or {}).get("name") or (sa or {}).get("short_name") or bk_key.title()
    tier = get_deep_link_tier(match_id, bk_key) if match_id else 0
    return {
        "bookmaker_key": bk_key,
        "bookmaker_name": name,
        "odds": odds,
        "affiliate_url": get_affiliate_url(bk_key, match_id=match_id),
        "has_active_affiliate": has_active,
        "deep_link_tier": tier,
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
