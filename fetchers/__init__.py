"""Sport-specific data fetchers — replaces single-source ESPN dependency.

Each fetcher implements BaseFetcher and returns an ESPN-compatible context dict
so existing narrative_spec / evidence_pack consumers work unchanged.

Usage:
    from fetchers import get_fetcher
    fetcher = get_fetcher("soccer")
    ctx = await fetcher.fetch_context(match_key, league, horizon_hours)
"""

from fetchers.base_fetcher import BaseFetcher, MEP_DEFINITIONS

__all__ = ["BaseFetcher", "MEP_DEFINITIONS", "get_fetcher"]


def get_fetcher(sport: str) -> BaseFetcher:
    """Return the appropriate fetcher for a sport."""
    sport_lower = sport.lower()
    if sport_lower in ("soccer", "football"):
        from fetchers.football_fetcher import FootballFetcher
        return FootballFetcher()
    raise ValueError(f"No fetcher available for sport: {sport}")
