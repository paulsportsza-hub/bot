"""Async client for The Odds API — fetches live odds, calculates EV, finds value bets."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

import config


# ── Data classes ──────────────────────────────────────────

@dataclass
class OddsEntry:
    """Best odds for a single outcome, with bookmaker info."""
    outcome: str        # e.g. "Arsenal", "Draw"
    price: float        # best decimal odds
    bookmaker: str      # bookmaker offering the best price
    is_sa_book: bool    # True if bookmaker is in SA_BOOKMAKERS


@dataclass
class ValueBet:
    """A single value bet identified by EV analysis."""
    home: str
    away: str
    sport_key: str
    outcome: str
    best_price: float
    bookmaker: str
    is_sa_book: bool
    fair_prob: float
    ev_pct: float           # expected value as percentage
    kelly_stake: float      # Kelly criterion stake fraction
    confidence: str         # "🟢 High" / "🟡 Medium" / "🔴 Low"


# ── Quota tracking (updated after each API call) ─────────

_last_quota: dict[str, str] = {
    "requests_used": "?",
    "requests_remaining": "?",
}


def get_quota() -> dict[str, str]:
    """Return the last known API quota info."""
    return dict(_last_quota)


# ── Core fetch functions ──────────────────────────────────

async def fetch_odds(
    sport_key: str,
    regions: str = "eu",
    markets: str = "h2h",
    odds_format: str = "decimal",
) -> list[dict]:
    """Return a list of event dicts with bookmaker odds.

    Also updates the global quota tracker from response headers.
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
        _update_quota(resp)
        return resp.json()


async def fetch_sports() -> list[dict]:
    """Return all in-season sports available on The Odds API."""
    url = f"{config.ODDS_BASE_URL}/sports"
    params = {"apiKey": config.ODDS_API_KEY}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        _update_quota(resp)
        return resp.json()


def _update_quota(resp: httpx.Response) -> None:
    """Extract quota headers from an Odds API response."""
    _last_quota["requests_used"] = resp.headers.get(
        "x-requests-used", _last_quota["requests_used"]
    )
    _last_quota["requests_remaining"] = resp.headers.get(
        "x-requests-remaining", _last_quota["requests_remaining"]
    )


# ── Odds analysis ────────────────────────────────────────

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


def find_best_odds(event: dict, market: str = "h2h") -> list[OddsEntry]:
    """Like best_odds but returns OddsEntry with bookmaker name + SA flag."""
    best: dict[str, OddsEntry] = {}
    for bk in event.get("bookmakers", []):
        bk_key = bk.get("key", "").lower()
        bk_title = bk.get("title", bk_key)
        is_sa = bk_key in config.SA_BOOKMAKERS
        for mkt in bk.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt["outcomes"]:
                name = outcome["name"]
                price = outcome["price"]
                if name not in best or price > best[name].price:
                    best[name] = OddsEntry(
                        outcome=name, price=price,
                        bookmaker=bk_title, is_sa_book=is_sa,
                    )
    return list(best.values())


def fair_probabilities(event: dict, market: str = "h2h") -> dict[str, float]:
    """Calculate fair (vig-removed) probabilities for each outcome.

    Method: average implied probability across all bookmakers, then
    normalise so they sum to 1.0.
    """
    # Collect all prices per outcome
    prices: dict[str, list[float]] = {}
    for bk in event.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt["outcomes"]:
                name = outcome["name"]
                price = outcome["price"]
                if price > 0:
                    prices.setdefault(name, []).append(price)

    if not prices:
        return {}

    # Average implied prob per outcome
    avg_implied: dict[str, float] = {}
    for name, price_list in prices.items():
        avg_implied[name] = sum(1.0 / p for p in price_list) / len(price_list)

    # Normalise to remove overround
    total = sum(avg_implied.values())
    if total == 0:
        return {}
    return {name: prob / total for name, prob in avg_implied.items()}


def calculate_ev(best_price: float, fair_prob: float) -> float:
    """Calculate EV% for a bet: (odds × prob - 1) × 100."""
    return (best_price * fair_prob - 1.0) * 100.0


def kelly_stake(best_price: float, fair_prob: float, fraction: float = 1.0) -> float:
    """Calculate fractional Kelly criterion stake as fraction of bankroll.

    Returns 0.0 if the bet has negative or zero edge.
    """
    b = best_price - 1.0  # net odds
    q = 1.0 - fair_prob
    if b <= 0:
        return 0.0
    kelly = (b * fair_prob - q) / b
    return max(0.0, kelly * fraction)


def ev_confidence(ev_pct: float) -> str:
    """Map EV% to a confidence indicator."""
    if ev_pct >= 8.0:
        return "🟢 High"
    elif ev_pct >= 4.0:
        return "🟡 Medium"
    else:
        return "🔴 Low"


# ── Value bet scanning ────────────────────────────────────

def scan_value_bets(
    events: list[dict],
    sport_key: str,
    min_ev: float = 3.0,
    kelly_fraction: float = 0.5,
    market: str = "h2h",
) -> list[ValueBet]:
    """Scan events for value bets above min_ev threshold.

    Returns a list of ValueBet sorted by EV descending.
    """
    picks: list[ValueBet] = []

    for ev in events:
        home = ev.get("home_team", "?")
        away = ev.get("away_team", "?")
        fair_probs = fair_probabilities(ev, market)
        best_entries = find_best_odds(ev, market)

        for entry in best_entries:
            fp = fair_probs.get(entry.outcome, 0.0)
            if fp <= 0:
                continue
            ev_pct = calculate_ev(entry.price, fp)
            if ev_pct < min_ev:
                continue
            ks = kelly_stake(entry.price, fp, kelly_fraction)
            picks.append(ValueBet(
                home=home,
                away=away,
                sport_key=sport_key,
                outcome=entry.outcome,
                best_price=entry.price,
                bookmaker=entry.bookmaker,
                is_sa_book=entry.is_sa_book,
                fair_prob=fp,
                ev_pct=ev_pct,
                kelly_stake=ks,
                confidence=ev_confidence(ev_pct),
            ))

    picks.sort(key=lambda p: p.ev_pct, reverse=True)
    return picks


# ── Formatting ────────────────────────────────────────────

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


def format_pick_card(pick: ValueBet, experience: str = "experienced") -> str:
    """Format a single ValueBet as an HTML pick card for Telegram.

    Adapts output based on experience level:
    - experienced: compact stats (odds, EV%, Kelly stake)
    - casual: narrative + explained odds + suggested stake
    - newbie: full hand-holding with explanations in Rands
    """
    if experience == "newbie":
        return _format_pick_newbie(pick)
    elif experience == "casual":
        return _format_pick_casual(pick)
    return _format_pick_experienced(pick)


def _format_pick_experienced(pick: ValueBet) -> str:
    """Compact stats for experienced bettors."""
    sport = config.ALL_SPORTS.get(pick.sport_key)
    emoji = sport.emoji if sport else "🏅"

    bk_display = pick.bookmaker
    if pick.is_sa_book:
        bk_display = f"🇿🇦 {pick.bookmaker}"

    return (
        f"{emoji} <b>{pick.home}</b> vs <b>{pick.away}</b>\n"
        f"   📌 Pick: <b>{pick.outcome}</b>\n"
        f"   💰 Odds: <b>{pick.best_price:.2f}</b> @ {bk_display}\n"
        f"   📈 EV: <b>{pick.ev_pct:+.1f}%</b> | {pick.confidence}\n"
        f"   🎯 Kelly: <code>{pick.kelly_stake:.1%}</code> of bankroll"
    )


def _format_pick_casual(pick: ValueBet) -> str:
    """Narrative style with explained odds for casual bettors."""
    sport = config.ALL_SPORTS.get(pick.sport_key)
    emoji = sport.emoji if sport else "🏅"

    bk_display = pick.bookmaker
    if pick.is_sa_book:
        bk_display = f"🇿🇦 {pick.bookmaker}"

    # Calculate payout for R100 bet
    payout = pick.best_price * 100

    # Suggested stake based on Kelly
    if pick.kelly_stake >= 0.05:
        stake_hint = "Medium-High stake"
    elif pick.kelly_stake >= 0.02:
        stake_hint = "Medium stake"
    else:
        stake_hint = "Small stake"

    return (
        f"{emoji} <b>{pick.home}</b> vs <b>{pick.away}</b>\n"
        f"   📌 We like: <b>{pick.outcome}</b>\n"
        f"   💰 Best odds: <b>{pick.best_price:.2f}</b> @ {bk_display}\n"
        f"   💵 R100 bet pays <b>R{payout:.0f}</b>\n"
        f"   📈 Edge: <b>{pick.ev_pct:+.1f}%</b> above fair value | {pick.confidence}\n"
        f"   💡 Suggested: <b>{stake_hint}</b>"
    )


def _format_pick_newbie(pick: ValueBet) -> str:
    """Full hand-holding for new bettors — explains everything."""
    sport = config.ALL_SPORTS.get(pick.sport_key)
    emoji = sport.emoji if sport else "🏅"

    bk_display = pick.bookmaker
    if pick.is_sa_book:
        bk_display = f"🇿🇦 {pick.bookmaker}"

    # Payout examples
    payout_20 = pick.best_price * 20
    payout_50 = pick.best_price * 50

    # Simple confidence label
    if "High" in pick.confidence:
        conf_explain = "Our analysis shows strong value here"
    elif "Medium" in pick.confidence:
        conf_explain = "Decent value — worth a small bet"
    else:
        conf_explain = "Some value, but proceed with caution"

    # Bet type explanation
    if pick.outcome == "Draw":
        bet_explain = "a <b>Draw</b> (neither team wins)"
    elif pick.outcome == pick.home:
        bet_explain = f"<b>{pick.outcome}</b> to win (home team)"
    else:
        bet_explain = f"<b>{pick.outcome}</b> to win (away team)"

    return (
        f"{emoji} <b>{pick.home}</b> vs <b>{pick.away}</b>\n"
        f"   📌 Bet on: {bet_explain}\n"
        f"   💰 Odds: <b>{pick.best_price:.2f}</b> @ {bk_display}\n"
        f"   💵 Bet R20 → get <b>R{payout_20:.0f}</b> back\n"
        f"   💵 Bet R50 → get <b>R{payout_50:.0f}</b> back\n"
        f"   {pick.confidence} — {conf_explain}\n"
        f"   💡 <i>Start small: R20-50 per bet</i>"
    )
