"""MzansiEdge — Picks Engine.

Fetches live odds, calculates EV, filters by user risk profile,
ranks by edge size, and formats pick cards.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import config
from scripts.odds_client import (
    calculate_ev,
    ev_confidence,
    fair_probabilities,
    fetch_odds_cached,
    get_quota,
    kelly_stake,
)

logger = logging.getLogger(__name__)

# Sharp bookmakers — their lines are closest to true probabilities
SHARP_BOOKS = {"pinnacle", "betfair_ex_eu", "matchbook"}

# Default bankroll for stake calculations (ZAR)
BANKROLL_DEFAULT = 6000.0

# Minimum bet in ZAR
MIN_STAKE = 10.0


async def get_picks_for_user(
    league_keys: list[str],
    risk_profile: str = "moderate",
    max_picks: int = 5,
) -> dict[str, Any]:
    """Full picks pipeline for a user.

    1. Fetch cached odds for each of the user's selected leagues
    2. For each event, for each market (h2h, totals):
       - Estimate true probability using sharp bookmaker lines (Pinnacle)
       - Fallback: use vig-removed fair probability from all bookmakers
       - Calculate EV using true prob vs best available odds
       - Calculate Kelly stake
    3. Filter by user's risk profile (min EV threshold)
    4. Rank by EV (highest edge first)
    5. Return top N picks

    Args:
        league_keys: Internal league keys (e.g. ["epl", "nba"])
        risk_profile: "conservative", "moderate", or "aggressive"
        max_picks: Maximum picks to return

    Returns dict with: ok, picks, total_events, total_markets, quota_remaining, errors
    """
    risk = config.RISK_PROFILES.get(risk_profile, config.RISK_PROFILES["moderate"])
    min_ev = risk["min_ev"]
    kelly_frac = risk["kelly_fraction"]
    max_stake_pct = risk["max_stake_pct"] / 100.0  # Convert 2 → 0.02
    bankroll = BANKROLL_DEFAULT

    all_picks: list[dict] = []
    total_events = 0
    total_markets = 0
    errors: list[str] = []

    for lk in league_keys:
        league = config.ALL_LEAGUES.get(lk)
        api_key = league.api_key if league else config.SPORTS_MAP.get(lk)
        if not api_key:
            continue

        sport_key = config.LEAGUE_SPORT.get(lk, lk)

        result = await fetch_odds_cached(
            api_key, regions="eu,uk,au", markets="h2h,totals",
        )

        if not result["ok"]:
            errors.append(f"{lk}: {result['error']}")
            continue

        events = result["data"] or []
        total_events += len(events)

        for event in events:
            event_id = event.get("id", "")
            home = event.get("home_team", "Unknown")
            away = event.get("away_team", "Unknown")
            commence = event.get("commence_time", "")
            bookmakers = event.get("bookmakers", [])

            if not bookmakers:
                continue

            # Vig-removed fair probabilities (fallback for non-sharp markets)
            fair_probs = fair_probabilities(event, "h2h")

            # ── Analyse h2h market ──
            for outcome_name in [home, away, "Draw"]:
                total_markets += 1

                best = _best_for_outcome(bookmakers, "h2h", outcome_name)
                if not best:
                    continue

                # True probability: sharp book → fair prob fallback
                true_prob = _get_sharp_probability(bookmakers, "h2h", outcome_name)
                if true_prob is None:
                    true_prob = fair_probs.get(outcome_name)
                if not true_prob or true_prob <= 0:
                    continue

                ev_pct = calculate_ev(best["odds"], true_prob)
                if ev_pct < min_ev:
                    continue

                ks = kelly_stake(best["odds"], true_prob, fraction=kelly_frac)
                stake = ks * bankroll
                stake = min(stake, bankroll * max_stake_pct)
                if stake < MIN_STAKE:
                    continue

                all_picks.append(_build_pick(
                    event_id=event_id, sport_key=sport_key,
                    home=home, away=away, commence=commence,
                    market="h2h", outcome=outcome_name,
                    best=best, true_prob=true_prob, ev_pct=ev_pct,
                    stake=stake,
                ))

            # ── Analyse totals market (Over/Under) ──
            fair_probs_totals = fair_probabilities(event, "totals")
            for outcome_name in ["Over", "Under"]:
                total_markets += 1

                best = _best_for_outcome(bookmakers, "totals", outcome_name)
                if not best:
                    continue

                true_prob = _get_sharp_probability(bookmakers, "totals", outcome_name)
                if true_prob is None:
                    true_prob = fair_probs_totals.get(outcome_name)
                if not true_prob or true_prob <= 0:
                    continue

                ev_pct = calculate_ev(best["odds"], true_prob)
                if ev_pct < min_ev:
                    continue

                ks = kelly_stake(best["odds"], true_prob, fraction=kelly_frac)
                stake = ks * bankroll
                stake = min(stake, bankroll * max_stake_pct)
                if stake < MIN_STAKE:
                    continue

                point = _get_totals_point(bookmakers, outcome_name)
                display_outcome = f"{outcome_name} {point}" if point else outcome_name

                all_picks.append(_build_pick(
                    event_id=event_id, sport_key=sport_key,
                    home=home, away=away, commence=commence,
                    market="totals", outcome=display_outcome,
                    best=best, true_prob=true_prob, ev_pct=ev_pct,
                    stake=stake,
                ))

    # Sort by EV (highest edge first) and take top N
    all_picks.sort(key=lambda p: p["ev"], reverse=True)
    top_picks = all_picks[:max_picks]

    quota = get_quota()

    return {
        "ok": len(top_picks) > 0,
        "picks": top_picks,
        "total_scanned": len(all_picks),
        "total_events": total_events,
        "total_markets": total_markets,
        "quota_remaining": quota.get("requests_remaining", "unknown"),
        "errors": errors if errors else None,
    }


# ── Internal helpers ─────────────────────────────────────


def _build_pick(
    event_id: str, sport_key: str,
    home: str, away: str, commence: str,
    market: str, outcome: str,
    best: dict, true_prob: float, ev_pct: float,
    stake: float,
) -> dict:
    """Construct a pick dict from computed values."""
    odds = best["odds"]
    return {
        "event_id": event_id,
        "sport_key": sport_key,
        "home_team": home,
        "away_team": away,
        "commence_time": commence,
        "market": market,
        "outcome": outcome,
        "odds": odds,
        "bookmaker": best["bookmaker_title"],
        "bookmaker_key": best["bookmaker_key"],
        "is_sa_bookmaker": best["is_sa"],
        "ev": round(ev_pct, 1),
        "confidence": round(true_prob * 100),
        "sharp_prob": round(true_prob * 100, 1),
        "stake": round(stake, 2),
        "potential_return": round(stake * odds, 2),
        "profit": round(stake * (odds - 1), 2),
        "all_odds": best["all_odds"][:5],
        "confidence_label": ev_confidence(ev_pct),
    }


def _best_for_outcome(
    bookmakers: list[dict], market: str, outcome_name: str,
) -> dict | None:
    """Find best odds for a specific outcome across all bookmakers.

    Returns dict with: odds, bookmaker_key, bookmaker_title, is_sa, all_odds
    or None if outcome not found.
    """
    all_odds: list[dict] = []

    for bk in bookmakers:
        bk_key = bk.get("key", "").lower()
        bk_title = bk.get("title", bk_key)
        is_sa = bk_key in config.SA_BOOKMAKERS

        for mkt in bk.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt.get("outcomes", []):
                if outcome["name"] == outcome_name:
                    all_odds.append({
                        "odds": outcome["price"],
                        "bookmaker_key": bk_key,
                        "bookmaker_title": bk_title,
                        "is_sa": is_sa,
                    })

    if not all_odds:
        return None

    # Sort by odds descending (best first)
    all_odds.sort(key=lambda x: x["odds"], reverse=True)
    best = all_odds[0]

    return {
        "odds": best["odds"],
        "bookmaker_key": best["bookmaker_key"],
        "bookmaker_title": best["bookmaker_title"],
        "is_sa": best["is_sa"],
        "all_odds": all_odds,
    }


def _get_sharp_probability(
    bookmakers: list[dict],
    market: str,
    outcome_name: str,
) -> Optional[float]:
    """Extract probability estimate from sharp bookmakers.

    Sharp lines (Pinnacle, Betfair) are closest to true probabilities.
    Returns probability as float (0-1) or None if no sharp line found.
    """
    for bookie in bookmakers:
        if bookie.get("key", "").lower() not in SHARP_BOOKS:
            continue
        for mkt in bookie.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt.get("outcomes", []):
                if outcome["name"] == outcome_name:
                    odds = outcome["price"]
                    if odds > 1:
                        return 1.0 / odds
    return None


def _get_totals_point(bookmakers: list[dict], outcome_name: str) -> Optional[str]:
    """Extract the point line for Over/Under markets (e.g. 2.5)."""
    for bookie in bookmakers:
        for mkt in bookie.get("markets", []):
            if mkt["key"] != "totals":
                continue
            for outcome in mkt.get("outcomes", []):
                if outcome["name"] == outcome_name and "point" in outcome:
                    return str(outcome["point"])
    return None


# ── Pick card formatting (experience-aware) ──────────────


def format_pick_card(pick: dict, index: int, experience: str = "casual") -> str:
    """Format a pick card based on user's experience level.

    Experienced → compact, stats-heavy
    Casual → narrative + explained odds
    Newbie → full hand-holding with Rands
    """
    home = pick["home_team"]
    away = pick["away_team"]
    outcome = pick["outcome"]
    odds = pick["odds"]
    ev = pick["ev"]
    confidence = pick["confidence"]
    stake = pick["stake"]
    profit = pick["profit"]
    potential = pick["potential_return"]
    bookie = pick["bookmaker"]
    market = pick["market"]
    sa_flag = " 🇿🇦" if pick.get("is_sa_bookmaker") else ""

    # Parse commence time
    try:
        ct = datetime.fromisoformat(pick["commence_time"].replace("Z", "+00:00"))
        kickoff = ct.strftime("%a %d %b, %H:%M")
    except Exception:
        kickoff = "TBC"

    if experience == "experienced":
        return (
            f"<b>#{index} | {home} vs {away}</b>\n"
            f"⏰ {kickoff}\n\n"
            f"💰 <b>{outcome}</b> @ <b>{odds:.2f}</b> ({bookie}{sa_flag})\n"
            f"📈 EV: <b>+{ev}%</b> | Conf: {confidence}% | Kelly: R{stake:,.0f}\n"
            f"💵 Stake R{stake:,.0f} → Return R{potential:,.0f} (+R{profit:,.0f})\n\n"
            f"<i>{market.upper()} market</i>"
        )

    elif experience == "newbie":
        if market == "h2h":
            if outcome == "Draw":
                bet_explain = "You're betting that the match ends in a draw."
            else:
                bet_explain = f"You're betting that <b>{outcome}</b> wins the match."
        elif "Over" in outcome:
            bet_explain = f"You're betting there will be more than {outcome.split()[-1]} total goals in the match."
        elif "Under" in outcome:
            bet_explain = f"You're betting there will be fewer than {outcome.split()[-1]} total goals."
        else:
            bet_explain = f"Bet on: {outcome}"

        return (
            f"<b>#{index} 🏟️ {home} vs {away}</b>\n"
            f"⏰ {kickoff}\n\n"
            f"📋 <b>What's the bet?</b>\n"
            f"{bet_explain}\n\n"
            f"💵 <b>The odds: {odds:.2f}</b>\n"
            f"This means for every <b>R100</b> you bet, you'd get <b>R{odds * 100:,.0f}</b> back — "
            f"that's R100 plus <b>R{(odds - 1) * 100:,.0f} profit</b>.\n\n"
            f"🎯 <b>How confident is the AI?</b> {confidence}%\n"
            f"Our AI thinks this outcome is more likely than the odds suggest — "
            f"that's a <b>+{ev}%</b> edge in our favour.\n\n"
            f"💡 <b>Suggested bet:</b> R{stake:,.0f}\n"
            f"If it wins → you get <b>R{potential:,.0f}</b> back (R{profit:,.0f} profit)\n\n"
            f"📲 Best odds at: <b>{bookie}</b>{sa_flag}\n\n"
            f"<i>💡 Tip: Start small while you're learning. R20-50 bets are perfect.</i>"
        )

    else:
        # CASUAL: Narrative + explained odds
        return (
            f"<b>#{index} 🏟️ {home} vs {away}</b>\n"
            f"⏰ {kickoff}\n\n"
            f"💰 <b>{outcome}</b> @ {odds:.2f} ({bookie}{sa_flag})\n"
            f"The AI found a <b>+{ev}%</b> edge here — confidence {confidence}%.\n\n"
            f"📊 Suggested: R{stake:,.0f} → potential R{potential:,.0f} return\n"
            f"<i>(R{profit:,.0f} profit if it lands)</i>"
        )
