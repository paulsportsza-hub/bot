"""Deterministic fixtures for snapshot rendering tests."""

from __future__ import annotations

TIER_EDGE_SCORES = {
    "diamond": 62.0,
    "gold": 46.0,
    "silver": 39.0,
    "bronze": 22.0,
}

ACCESS_TIERS = ["full", "partial", "blurred", "locked"]


def make_tip(
    *,
    home: str = "Mamelodi Sundowns",
    away: str = "Kaizer Chiefs",
    league: str = "PSL",
    league_key: str = "psl",
    sport_key: str = "soccer_south_africa_psl",
    sport: str = "soccer",
    outcome: str = "Sundowns",
    odds: float = 1.85,
    ev: float = 5.2,
    display_tier: str = "gold",
    match_id: str = "mamelodi_sundowns_vs_kaizer_chiefs_2026-03-10",
    event_id: str | None = None,
    commence_time: str = "2026-03-10T15:00:00Z",
    bookmaker: str = "hollywoodbets",
    edge_v2: dict | None = None,
    edge_score: float | None = None,
) -> dict:
    """Return a stable edge payload that survives current renderer thresholds."""
    edge_score = TIER_EDGE_SCORES.get(display_tier, 40.0) if edge_score is None else edge_score
    event_id = event_id or match_id
    edge_v2 = edge_v2 or {
        "match_key": match_id,
        "tier": display_tier,
        "composite_score": edge_score,
        "confirming_signals": 4 if display_tier in ("gold", "diamond") else 2,
        "contradicting_signals": 1 if display_tier in ("gold", "diamond") else 0,
        "edge_pct": ev,
        "best_bookmaker": bookmaker,
        "best_odds": odds,
        "signals": {
            "price_edge": {
                "available": True,
                "signal_strength": 0.82,
                "edge_pct": ev,
                "best_odds": odds,
                "best_bookmaker": bookmaker,
                "sharp_source": "pinnacle",
            },
            "market_agreement": {
                "available": True,
                "signal_strength": 0.71,
                "agreeing_bookmakers": 4,
                "total_bookmakers": 6,
            },
            "movement": {
                "available": True,
                "signal_strength": 0.69,
                "movement_pct": 2.4,
                "steam_confirms": True,
                "n_bks_moving": 3,
            },
            "form_h2h": {
                "available": True,
                "signal_strength": 0.66,
                "home_form_string": "WWDLW",
                "away_form_string": "LDWWW",
            },
            "tipster": {"available": False, "signal_strength": 0.5},
            "lineup_injury": {"available": False, "signal_strength": 0.5},
        },
    }
    return {
        "home_team": home,
        "away_team": away,
        "league": league,
        "league_key": league_key,
        "sport_key": sport_key,
        "sport": sport,
        "outcome": outcome,
        "odds": odds,
        "ev": ev,
        "display_tier": display_tier,
        "edge_rating": display_tier,
        "edge_score": edge_score,
        "match_id": match_id,
        "event_id": event_id,
        "commence_time": commence_time,
        "bookmaker": bookmaker,
        "odds_by_bookmaker": {bookmaker: odds},
        "edge_v2": edge_v2,
    }


def sample_tips() -> list[dict]:
    """Stable mixed-tier list used across page snapshots."""
    return [
        make_tip(
            display_tier="diamond",
            outcome="Sundowns",
            odds=1.85,
            ev=16.0,
            match_id="sundowns_vs_chiefs_2026-03-10",
        ),
        make_tip(
            display_tier="gold",
            home="Arsenal",
            away="Chelsea",
            league="Premier League",
            league_key="epl",
            sport_key="soccer_epl",
            outcome="Arsenal",
            odds=2.10,
            ev=9.0,
            match_id="arsenal_vs_chelsea_2026-03-10",
        ),
        make_tip(
            display_tier="gold",
            home="Bulls",
            away="Stormers",
            league="URC",
            league_key="urc",
            sport_key="rugby_urc",
            sport="rugby",
            outcome="Bulls",
            odds=1.65,
            ev=8.5,
            match_id="bulls_vs_stormers_2026-03-10",
        ),
        make_tip(
            display_tier="silver",
            home="Liverpool",
            away="Man City",
            league="Premier League",
            league_key="epl",
            sport_key="soccer_epl",
            outcome="Draw",
            odds=3.40,
            ev=5.1,
            match_id="liverpool_vs_man_city_2026-03-10",
        ),
        make_tip(
            display_tier="silver",
            home="Sharks",
            away="Lions",
            league="URC",
            league_key="urc",
            sport_key="rugby_urc",
            sport="rugby",
            outcome="Sharks",
            odds=1.90,
            ev=4.8,
            match_id="sharks_vs_lions_2026-03-10",
        ),
        make_tip(
            display_tier="bronze",
            home="Orlando Pirates",
            away="Stellenbosch",
            league="PSL",
            league_key="psl",
            sport_key="soccer_south_africa_psl",
            outcome="Pirates",
            odds=2.30,
            ev=2.1,
            match_id="orlando_pirates_vs_stellenbosch_2026-03-10",
        ),
        make_tip(
            display_tier="bronze",
            home="Real Madrid",
            away="Barcelona",
            league="La Liga",
            league_key="la_liga",
            sport_key="soccer_spain_la_liga",
            outcome="Madrid",
            odds=2.50,
            ev=1.5,
            match_id="real_madrid_vs_barcelona_2026-03-10",
        ),
        make_tip(
            display_tier="bronze",
            home="India",
            away="Australia",
            league="T20 World Cup",
            league_key="t20_world_cup",
            sport_key="cricket_t20_world_cup",
            sport="cricket",
            outcome="India",
            odds=1.70,
            ev=1.2,
            match_id="india_vs_australia_2026-03-10",
        ),
    ]


def make_settled_edge(
    match_key: str,
    *,
    result: str = "hit",
    edge_tier: str = "gold",
    league: str = "psl",
    sport: str = "soccer",
    bet_type: str = "Home Win",
    recommended_odds: float = 2.10,
    actual_return: float = 210.0,
    match_date: str = "2026-03-13",
) -> dict:
    return {
        "match_key": match_key,
        "result": result,
        "edge_tier": edge_tier,
        "league": league,
        "sport": sport,
        "bet_type": bet_type,
        "recommended_odds": recommended_odds,
        "actual_return": actual_return,
        "match_date": match_date,
    }


def make_edge_tracker_summary(
    *,
    total: int = 10,
    hits: int = 6,
    hit_rate_pct: float = 60.0,
    roi: float | None = 12.4,
) -> dict:
    return {
        "loaded": True,
        "has_data": total > 0,
        "total": total,
        "hits": hits,
        "hit_rate_pct": hit_rate_pct,
        "roi": roi,
    }
