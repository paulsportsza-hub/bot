from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from scrapers.db_connect import connect_odds_db_readonly
from scrapers.odds_integrity import filter_outlier_prices
from scrapers.odds_normaliser import display_name as _display_team_name
from scrapers.utils.roster_validation import player_belongs_to_match_teams as _player_belongs_to_match_teams

ODDS_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scrapers", "odds.db")
ENRICHMENT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scrapers", "enrichment.db")


@dataclass
class EvidenceSource:
    available: bool
    fetched_at: str
    source_name: str
    stale_minutes: float
    error: str = ""


@dataclass
class SAOddsBlock:
    provenance: EvidenceSource
    odds_by_bookmaker: dict[str, dict[str, float | None]] = field(default_factory=dict)
    best_odds: dict[str, float] = field(default_factory=dict)
    best_bookmaker: dict[str, str] = field(default_factory=dict)
    bookmaker_count: int = 0
    market_type: str = "1x2"


@dataclass
class EdgeStateBlock:
    provenance: EvidenceSource
    composite_score: float = 0.0
    edge_tier: str = "bronze"
    edge_pct: float = 0.0
    outcome: str = ""
    fair_probability: float = 0.0
    confirming_signals: int = 0
    contradicting_signals: int = 0
    signals: dict[str, Any] = field(default_factory=dict)
    price_edge_score: float = 0.0
    market_agreement_score: float = 0.0
    movement_score: float = 0.0
    tipster_score: float = 0.0
    lineup_injury_score: float = 0.0
    form_h2h_score: float = 0.0
    weather_score: float = 0.0
    sharp_available: bool = False


@dataclass
class ESPNContextBlock:
    provenance: EvidenceSource
    data_available: bool = False
    home_team: dict[str, Any] = field(default_factory=dict)
    away_team: dict[str, Any] = field(default_factory=dict)
    h2h: list[dict[str, Any]] = field(default_factory=list)
    competition: str = ""
    season: str = ""


@dataclass
class H2HBlock:
    provenance: EvidenceSource
    matches: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    summary_text: str = ""


@dataclass
class NewsBlock:
    provenance: EvidenceSource
    articles: list[dict[str, Any]] = field(default_factory=list)
    home_team_articles: list[dict[str, Any]] = field(default_factory=list)
    away_team_articles: list[dict[str, Any]] = field(default_factory=list)
    injury_mentions: list[dict[str, Any]] = field(default_factory=list)
    article_count: int = 0


@dataclass
class SharpLinesBlock:
    provenance: EvidenceSource
    benchmarks: list[dict[str, Any]] = field(default_factory=list)
    pinnacle_price: dict[str, float] | None = None
    betfair_price: dict[str, float] | None = None
    spread_pct: float = 0.0
    liquidity_score: str = "unknown"


@dataclass
class SettlementBlock:
    provenance: EvidenceSource
    stats_7d: dict[str, Any] = field(default_factory=dict)
    stats_30d: dict[str, Any] = field(default_factory=dict)
    streak: dict[str, Any] = field(default_factory=dict)
    portfolio_7d: dict[str, Any] = field(default_factory=dict)
    tier_hit_rates: dict[str, float] = field(default_factory=dict)
    total_settled: int = 0


@dataclass
class MovementsBlock:
    provenance: EvidenceSource
    movements: list[dict[str, Any]] = field(default_factory=list)
    net_direction: str = "stable"
    movement_count: int = 0
    velocity: float = 0.0
    bookmakers_moving: int = 0


@dataclass
class InjuriesBlock:
    provenance: EvidenceSource
    api_football: list[dict[str, Any]] = field(default_factory=list)
    news_extracted: list[dict[str, Any]] = field(default_factory=list)
    home_injuries: list[dict[str, Any]] = field(default_factory=list)
    away_injuries: list[dict[str, Any]] = field(default_factory=list)
    total_injury_count: int = 0


@dataclass
class EvidencePack:
    match_key: str
    sport: str
    league: str
    built_at: str
    pack_version: int = 1
    sa_odds: SAOddsBlock | None = None
    edge_state: EdgeStateBlock | None = None
    espn_context: ESPNContextBlock | None = None
    h2h: H2HBlock | None = None
    news: NewsBlock | None = None
    sharp_lines: SharpLinesBlock | None = None
    settlement_stats: SettlementBlock | None = None
    movements: MovementsBlock | None = None
    injuries: InjuriesBlock | None = None
    richness_score: str = "low"
    sources_available: int = 0
    sources_total: int = 8


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _stale_minutes(value: str | None, *, now: datetime | None = None) -> float:
    dt = _parse_dt(value)
    if dt is None:
        return 0.0
    ref = now or datetime.now(timezone.utc)
    return round(max(0.0, (ref - dt).total_seconds() / 60.0), 1)


def _empty_source(name: str, *, error: str = "") -> EvidenceSource:
    return EvidenceSource(
        available=False,
        fetched_at=_utc_now_iso(),
        source_name=name,
        stale_minutes=0.0,
        error=error,
    )


def _connect_enrichment_db_readonly(timeout: float = 1.0) -> sqlite3.Connection:
    uri = f"file:{ENRICHMENT_DB}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _parse_match_key(match_key: str) -> tuple[str, str]:
    parts = match_key.rsplit("_", 1)
    teams_part = parts[0] if len(parts) > 1 else match_key
    if "_vs_" not in teams_part:
        return "", ""
    return teams_part.split("_vs_", 1)


def _display_name(team_key: str) -> str:
    return _display_team_name(team_key) if team_key else ""


def _keyword_patterns(team_key: str, display_name: str) -> list[str]:
    patterns = {team_key.replace("_", " ").lower(), display_name.lower()}
    parts = [p for p in display_name.lower().replace("-", " ").split() if len(p) >= 4]
    if parts:
        patterns.add(" ".join(parts))
    return [p for p in patterns if p]


def _safe_row_dict(row: sqlite3.Row | sqlite3.Row | dict | None) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def _compute_stats(rows: list[sqlite3.Row], days: int) -> dict[str, Any]:
    if not rows:
        return {
            "total": 0,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0.0,
            "avg_ev": 0.0,
            "avg_return": 0.0,
            "roi": 0.0,
            "by_tier": {},
            "period_days": days,
        }

    total = len(rows)
    hits = sum(1 for row in rows if row["result"] == "hit")
    misses = total - hits
    avg_ev = sum(float(row["predicted_ev"] or 0) for row in rows) / total
    total_return = sum(float(row["actual_return"] or 0) for row in rows)
    avg_return = total_return / total
    stake_total = total * 100.0
    roi = ((total_return - stake_total) / stake_total * 100.0) if stake_total else 0.0

    by_tier: dict[str, dict[str, float | int]] = {}
    for row in rows:
        tier = row["edge_tier"] or "unknown"
        bucket = by_tier.setdefault(tier, {"total": 0, "hits": 0})
        bucket["total"] += 1
        if row["result"] == "hit":
            bucket["hits"] += 1
    for tier, bucket in by_tier.items():
        total_tier = int(bucket["total"])
        bucket["hit_rate"] = round((bucket["hits"] / total_tier), 3) if total_tier else 0.0

    return {
        "total": total,
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 3) if total else 0.0,
        "avg_ev": round(avg_ev, 2),
        "avg_return": round(avg_return, 2),
        "roi": round(roi, 2),
        "by_tier": by_tier,
        "period_days": days,
    }


def _score_richness(pack: EvidencePack) -> tuple[str, int]:
    score = 0
    available = 0

    if pack.sa_odds and pack.sa_odds.provenance.available:
        score += 20
        available += 1
    if pack.edge_state and pack.edge_state.provenance.available:
        score += 20
        available += 1
    if pack.espn_context and pack.espn_context.provenance.available and pack.espn_context.data_available:
        score += 25
        available += 1
    if pack.sharp_lines and pack.sharp_lines.provenance.available:
        score += 10
        available += 1
    if pack.injuries and pack.injuries.provenance.available and pack.injuries.total_injury_count > 0:
        score += 8
        available += 1
    if pack.news and pack.news.provenance.available and pack.news.article_count > 0:
        score += 7
        available += 1
    if pack.movements and pack.movements.provenance.available and pack.movements.movement_count > 0:
        score += 5
        available += 1
    if pack.settlement_stats and pack.settlement_stats.provenance.available:
        score += 5
        available += 1

    if score >= 65:
        return "high", available
    if score >= 40:
        return "medium", available
    return "low", available


def _fetch_fixture_identity(match_key: str) -> dict[str, str]:
    conn = connect_odds_db_readonly(ODDS_DB, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT home_team, away_team, kickoff, league FROM fixture_mapping WHERE match_key = ?",
            (match_key,),
        ).fetchone()
        return _safe_row_dict(row)
    finally:
        conn.close()


def _fetch_sa_odds(match_key: str) -> SAOddsBlock:
    now = datetime.now(timezone.utc)
    conn = connect_odds_db_readonly(ODDS_DB, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT bookmaker, home_odds, draw_odds, away_odds, last_seen "
            "FROM odds_latest WHERE match_id = ? AND market_type = '1x2' ORDER BY bookmaker",
            (match_key,),
        ).fetchall()
        if not rows:
            return SAOddsBlock(provenance=_empty_source("odds_latest"))

        odds_by_bookmaker: dict[str, dict[str, float | None]] = {}
        best_odds = {"home": 0.0, "draw": 0.0, "away": 0.0}
        best_bookmaker = {"home": "", "draw": "", "away": ""}
        freshest = None
        for row in rows:
            bookmaker = row["bookmaker"]
            odds = {
                "home": row["home_odds"],
                "draw": row["draw_odds"],
                "away": row["away_odds"],
            }
            odds_by_bookmaker[bookmaker] = odds
            for outcome, value in odds.items():
                if value and float(value) > best_odds[outcome]:
                    best_odds[outcome] = float(value)
                    best_bookmaker[outcome] = bookmaker
            row_dt = _parse_dt(row["last_seen"])
            if row_dt and (freshest is None or row_dt > freshest):
                freshest = row_dt

        for outcome in ("home", "draw", "away"):
            prices = [
                (bookmaker, float(odds[outcome]))
                for bookmaker, odds in odds_by_bookmaker.items()
                if odds.get(outcome)
            ]
            clean_prices, _outliers = filter_outlier_prices(
                prices,
                match_id=match_key,
                selection=outcome,
            )
            if clean_prices:
                best_bookmaker[outcome], best_odds[outcome] = max(clean_prices, key=lambda item: item[1])
            else:
                best_bookmaker[outcome] = ""
                best_odds[outcome] = 0.0

        return SAOddsBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at=_utc_now_iso(),
                source_name="odds_latest",
                stale_minutes=_stale_minutes(freshest.isoformat() if freshest else None, now=now),
            ),
            odds_by_bookmaker=odds_by_bookmaker,
            best_odds={k: round(v, 2) for k, v in best_odds.items() if v},
            best_bookmaker={k: v for k, v in best_bookmaker.items() if v},
            bookmaker_count=len(odds_by_bookmaker),
        )
    finally:
        conn.close()


def _build_edge_state(edge_result: dict[str, Any] | None) -> EdgeStateBlock:
    edge_result = edge_result or {}
    signals = edge_result.get("signals") or {}
    price_edge = signals.get("price_edge") or {}
    market = signals.get("market_agreement") or {}
    movement = signals.get("movement") or {}
    tipster = signals.get("tipster") or {}
    lineup = signals.get("lineup_injury") or {}
    form_h2h = signals.get("form_h2h") or {}
    weather = signals.get("weather") or {}

    # R12-OVERNIGHT: Normalise edge_pct to percentage points.
    # edge_results may store decimal form (0.05) or percentage (5.0).
    # Detect: if edge_pct is between 0 and 1 exclusive AND a fallback "ev" or
    # "predicted_ev" field is >= 1, the decimal form is likely wrong.
    raw_edge_pct = float(edge_result.get("edge_pct") or 0.0)
    ev_fallback = float(edge_result.get("ev") or edge_result.get("predicted_ev") or 0.0)
    if 0 < abs(raw_edge_pct) < 1 and abs(ev_fallback) >= 1:
        ratio = abs(ev_fallback / raw_edge_pct) if raw_edge_pct else 0
        if 50 <= ratio <= 150:
            raw_edge_pct = ev_fallback

    return EdgeStateBlock(
        provenance=EvidenceSource(
            available=bool(edge_result),
            fetched_at=_utc_now_iso(),
            source_name="edge_v2",
            stale_minutes=_stale_minutes(edge_result.get("created_at")),
        ),
        composite_score=float(edge_result.get("composite_score") or 0.0),
        edge_tier=edge_result.get("tier") or edge_result.get("edge_tier") or "bronze",
        edge_pct=raw_edge_pct,
        outcome=edge_result.get("outcome") or "",
        fair_probability=float(edge_result.get("fair_probability") or edge_result.get("fair_prob") or 0.0),
        confirming_signals=int(edge_result.get("confirming_signals") or 0),
        contradicting_signals=int(edge_result.get("contradicting_signals") or 0),
        signals=signals,
        price_edge_score=float(price_edge.get("score") or 0.0),
        market_agreement_score=float(market.get("score") or 0.0),
        movement_score=float(movement.get("score") or 0.0),
        tipster_score=float(tipster.get("score") or 0.0),
        lineup_injury_score=float(lineup.get("score") or 0.0),
        form_h2h_score=float(form_h2h.get("score") or 0.0),
        weather_score=float(weather.get("score") or 0.0),
        sharp_available=bool(edge_result.get("sharp_available")),
    )


def _wrap_espn_context(ctx: dict[str, Any] | None) -> ESPNContextBlock:
    ctx = ctx or {}
    return ESPNContextBlock(
        provenance=EvidenceSource(
            available=bool(ctx),
            fetched_at=_utc_now_iso(),
            source_name="match_context_fetcher",
            stale_minutes=0.0,
        ),
        data_available=bool(ctx.get("data_available")),
        home_team=dict(ctx.get("home_team") or {}),
        away_team=dict(ctx.get("away_team") or {}),
        h2h=list(ctx.get("head_to_head") or []),
        competition=ctx.get("league") or "",
        season=str(ctx.get("season") or ""),
    )


def _parse_score_pair(score: Any, home_score: Any = None, away_score: Any = None) -> tuple[int | None, int | None]:
    try:
        if home_score is not None and away_score is not None:
            return int(home_score), int(away_score)
    except (TypeError, ValueError):
        pass

    match = re.search(r"(\d+)\s*-\s*(\d+)", str(score or ""))
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def _h2h_summary_text(home_name: str, home_wins: int, draws: int, away_wins: int) -> str:
    total = home_wins + draws + away_wins
    if total <= 0:
        return ""
    prefix = f"{home_name} " if home_name else ""
    return f"{total} meetings: {prefix}{home_wins}W {draws}D {away_wins}L".strip()


def _winner_from_scores(home_score: int | None, away_score: int | None, home_name: str, away_name: str) -> str:
    if home_score is None or away_score is None:
        return ""
    if home_score == away_score:
        return "draw"
    return home_name if home_score > away_score else away_name


def _summarise_h2h_matches(matches: list[dict[str, Any]], home_name: str, away_name: str) -> tuple[dict[str, Any], str]:
    home_wins = away_wins = draws = 0
    home_key = _normalise_name_key(home_name)
    away_key = _normalise_name_key(away_name)

    for match in matches:
        winner = str(match.get("winner") or "").strip()
        if winner.lower() == "draw":
            draws += 1
            continue
        winner_key = _normalise_name_key(winner)
        if winner_key and winner_key == home_key:
            home_wins += 1
        elif winner_key and winner_key == away_key:
            away_wins += 1
            continue
        else:
            home_team = str(match.get("home") or "")
            away_team = str(match.get("away") or "")
            home_score, away_score = _parse_score_pair(
                match.get("score"),
                match.get("home_score"),
                match.get("away_score"),
            )
            if home_score is None or away_score is None:
                continue
            if home_score == away_score:
                draws += 1
            elif _team_name_matches_requested(home_team, home_name):
                home_wins += 1 if home_score > away_score else 0
                away_wins += 1 if home_score < away_score else 0
            elif _team_name_matches_requested(away_team, home_name):
                home_wins += 1 if away_score > home_score else 0
                away_wins += 1 if away_score < home_score else 0

    summary = {
        "home_team": home_name,
        "away_team": away_name,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "total": home_wins + draws + away_wins,
    }
    return summary, _h2h_summary_text(home_name, home_wins, draws, away_wins)


def _fetch_h2h_from_match_results(
    home_key: str,
    away_key: str,
    home_name: str,
    away_name: str,
    league: str,
    sport: str,
    *,
    limit: int = 5,
) -> H2HBlock | None:
    now = datetime.now(timezone.utc)
    conn = connect_odds_db_readonly(ODDS_DB, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT home_team, away_team, home_score, away_score, result, match_date, source
            FROM match_results
            WHERE league = ? AND sport = ?
            ORDER BY match_date DESC
            LIMIT 250
            """,
            (league, sport),
        ).fetchall()
        requested_home = [home_key, home_name]
        requested_away = [away_key, away_name]
        matches: list[dict[str, Any]] = []
        for row in rows:
            row_home = str(row["home_team"] or "")
            row_away = str(row["away_team"] or "")
            same_order = any(_team_name_matches_requested(row_home, candidate) for candidate in requested_home if candidate) and any(
                _team_name_matches_requested(row_away, candidate) for candidate in requested_away if candidate
            )
            flipped_order = any(_team_name_matches_requested(row_home, candidate) for candidate in requested_away if candidate) and any(
                _team_name_matches_requested(row_away, candidate) for candidate in requested_home if candidate
            )
            if not (same_order or flipped_order):
                continue
            home_label = home_name if same_order else away_name
            away_label = away_name if same_order else home_name
            home_score = row["home_score"]
            away_score = row["away_score"]
            matches.append(
                {
                    "date": row["match_date"],
                    "home": home_label,
                    "away": away_label,
                    "home_score": int(home_score) if home_score is not None else None,
                    "away_score": int(away_score) if away_score is not None else None,
                    "score": f"{int(home_score)}-{int(away_score)}" if home_score is not None and away_score is not None else "",
                    "result": "draw" if row["result"] == "draw" else ("home" if home_score is not None and away_score is not None and home_score > away_score else "away"),
                    "winner": _winner_from_scores(home_score, away_score, home_label, away_label),
                    "source": row["source"] or "match_results",
                }
            )
            if len(matches) >= limit:
                break
        if not matches:
            return None
        summary, summary_text = _summarise_h2h_matches(matches, home_name, away_name)
        latest = _parse_dt(f"{matches[0]['date']}T00:00:00+00:00") if matches and matches[0].get("date") else None
        return H2HBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at=_utc_now_iso(),
                source_name="match_results",
                stale_minutes=_stale_minutes(latest.isoformat() if latest else None, now=now),
            ),
            matches=matches,
            summary=summary,
            summary_text=summary_text,
        )
    finally:
        conn.close()


def _build_h2h_from_espn(ctx: dict[str, Any] | None, home_name: str, away_name: str, *, limit: int = 5) -> H2HBlock | None:
    if not ctx:
        return None
    h2h_rows = list((ctx.get("head_to_head") or []))[:limit]
    if not h2h_rows:
        return None

    matches: list[dict[str, Any]] = []
    for row in h2h_rows:
        row_home = str(row.get("home") or row.get("home_team") or "")
        row_away = str(row.get("away") or row.get("away_team") or "")
        home_score, away_score = _parse_score_pair(row.get("score"), row.get("home_score"), row.get("away_score"))
        winner = str(row.get("winner") or "")
        if not winner and home_score is not None and away_score is not None:
            winner = _winner_from_scores(home_score, away_score, row_home, row_away)
        matches.append(
            {
                "date": str(row.get("date") or row.get("gameDate") or "")[:10],
                "home": row_home,
                "away": row_away,
                "home_score": home_score,
                "away_score": away_score,
                "score": f"{home_score}-{away_score}" if home_score is not None and away_score is not None else str(row.get("score") or ""),
                "result": "draw" if winner.lower() == "draw" else ("home" if _normalise_name_key(winner) == _normalise_name_key(row_home) else "away"),
                "winner": winner,
                "source": row.get("source") or "espn_h2h",
            }
        )

    matches = [match for match in matches if match.get("score") or match.get("winner")]
    if not matches:
        return None

    summary, summary_text = _summarise_h2h_matches(matches, home_name, away_name)
    freshness = _parse_dt(ctx.get("data_freshness"))
    return H2HBlock(
        provenance=EvidenceSource(
            available=True,
            fetched_at=_utc_now_iso(),
            source_name="espn_h2h",
            stale_minutes=_stale_minutes(freshness.isoformat() if freshness else None, now=datetime.now(timezone.utc)),
        ),
        matches=matches,
        summary=summary,
        summary_text=summary_text,
    )


def _fetch_news(
    home_key: str,
    away_key: str,
    home_name: str,
    away_name: str,
    league: str,
    sport: str,
    team_rosters: dict[str, list[str]] | None = None,
) -> NewsBlock:
    now = datetime.now(timezone.utc)
    patterns_home = _keyword_patterns(home_key, home_name)
    patterns_away = _keyword_patterns(away_key, away_name)
    articles: list[dict[str, Any]] = []
    verified_injured: set[str] = set()
    team_aliases = _build_simple_team_aliases(home_key, away_key, home_name, away_name)

    def _add_article(article: dict[str, Any]) -> None:
        key = article.get("url") or f"{article.get('source')}::{article.get('title')}"
        if any(existing.get("_dedupe_key") == key for existing in articles):
            return
        article["_dedupe_key"] = key
        articles.append(article)

    for db_kind in ("odds", "enrichment"):
        conn = (
            connect_odds_db_readonly(ODDS_DB, timeout=1.0)
            if db_kind == "odds"
            else _connect_enrichment_db_readonly(timeout=1.0)
        )
        try:
            conn.row_factory = sqlite3.Row
            if db_kind == "odds":
                verified_injured = _fetch_verified_injury_names(
                    conn, home_key, away_key, home_name, away_name, league, sport
                )
                rows = conn.execute(
                    "SELECT title, source, url, published_at, scraped_at, has_injury_mentions "
                    "FROM news_articles ORDER BY COALESCE(published_at, scraped_at) DESC LIMIT 250"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT title, source, url, published_at, scraped_at "
                    "FROM news_articles WHERE sport = ? "
                    "ORDER BY COALESCE(published_at, scraped_at) DESC LIMIT 250",
                    (sport,),
                ).fetchall()

            for row in rows:
                article = _safe_row_dict(row)
                title = str(article.get("title") or "").lower()
                text = f"{title} {str(article.get('query') or '').lower()}"
                if not any(pattern in text for pattern in patterns_home + patterns_away):
                    continue
                article["db_source"] = db_kind
                article["has_injury_mentions"] = bool(article.get("has_injury_mentions"))
                _add_article(article)
        finally:
            conn.close()

    for article in articles:
        article.pop("_dedupe_key", None)

    articles = _filter_injury_news_articles(articles, verified_injured, team_aliases)
    # Fix 1: filter headlines containing players from the opposing team
    if team_rosters:
        articles = _filter_cross_team_player_contamination(
            articles, home_name, away_name, patterns_home, patterns_away, team_rosters
        )
    articles.sort(
        key=lambda item: item.get("published_at") or item.get("scraped_at") or "",
        reverse=True,
    )
    limited = articles[:8]
    home_team_articles = [
        a for a in limited if any(pattern in str(a.get("title") or "").lower() for pattern in patterns_home)
    ][:4]
    away_team_articles = [
        a for a in limited if any(pattern in str(a.get("title") or "").lower() for pattern in patterns_away)
    ][:4]
    injury_mentions = [
        a for a in limited if a.get("has_injury_mentions") or "injur" in str(a.get("title") or "").lower()
    ][:4]
    freshest = None
    for article in limited:
        dt = _parse_dt(article.get("published_at") or article.get("scraped_at"))
        if dt and (freshest is None or dt > freshest):
            freshest = dt

    return NewsBlock(
        provenance=EvidenceSource(
            available=bool(limited),
            fetched_at=_utc_now_iso(),
            source_name="news_articles",
            stale_minutes=_stale_minutes(freshest.isoformat() if freshest else None, now=now),
        ),
        articles=limited,
        home_team_articles=home_team_articles,
        away_team_articles=away_team_articles,
        injury_mentions=injury_mentions,
        article_count=len(limited),
    )


def _prices_for_bookmaker(rows: list[sqlite3.Row], bookmaker_fragment: str) -> dict[str, float] | None:
    prices: dict[str, float] = {}
    for row in rows:
        bookmaker = str(row["bookmaker"] or "").lower()
        if bookmaker_fragment not in bookmaker:
            continue
        selection = str(row["selection"] or "").lower()
        if row["back_price"] is not None:
            prices[selection] = float(row["back_price"])
    return prices or None


def _fetch_sharp_lines(match_key: str) -> SharpLinesBlock:
    now = datetime.now(timezone.utc)
    conn = connect_odds_db_readonly(ODDS_DB, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT bookmaker, selection, back_price, lay_price, spread_pct, total_matched, "
            "liquidity_score, scraped_at FROM sharp_odds "
            "WHERE match_key = ? ORDER BY scraped_at DESC LIMIT 24",
            (match_key,),
        ).fetchall()
        if not rows:
            return SharpLinesBlock(provenance=_empty_source("sharp_odds"))

        freshest = max((_parse_dt(row["scraped_at"]) for row in rows), default=None)
        spread_values = [float(row["spread_pct"]) for row in rows if row["spread_pct"] is not None]
        liquidity = next(
            (str(row["liquidity_score"]) for row in rows if row["liquidity_score"] and row["liquidity_score"] != "unknown"),
            "unknown",
        )
        benchmarks = [
            {
                "bookmaker": row["bookmaker"],
                "selection": row["selection"],
                "back_price": row["back_price"],
                "lay_price": row["lay_price"],
                "spread_pct": row["spread_pct"],
                "total_matched": row["total_matched"],
                "liquidity_score": row["liquidity_score"],
                "scraped_at": row["scraped_at"],
            }
            for row in rows[:12]
        ]
        return SharpLinesBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at=_utc_now_iso(),
                source_name="sharp_odds",
                stale_minutes=_stale_minutes(freshest.isoformat() if freshest else None, now=now),
            ),
            benchmarks=benchmarks,
            pinnacle_price=_prices_for_bookmaker(rows, "pinnacle"),
            betfair_price=_prices_for_bookmaker(rows, "betfair"),
            spread_pct=round(sum(spread_values) / len(spread_values), 3) if spread_values else 0.0,
            liquidity_score=liquidity,
        )
    finally:
        conn.close()


def _fetch_settlement_stats() -> SettlementBlock:
    now = datetime.now(timezone.utc)
    cutoff_30 = (now.replace(microsecond=0) - timedelta(days=30)).isoformat()
    cutoff_7 = (now.replace(microsecond=0) - timedelta(days=7)).isoformat()
    conn = connect_odds_db_readonly(ODDS_DB, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        rows_30 = conn.execute(
            "SELECT edge_tier, result, predicted_ev, actual_return, settled_at "
            "FROM edge_results WHERE settled_at > ? AND result IN ('hit', 'miss') "
            "ORDER BY settled_at DESC",
            (cutoff_30,),
        ).fetchall()
        cutoff_7_dt = _parse_dt(cutoff_7)
        rows_7 = [
            row
            for row in rows_30
            if _parse_dt(row["settled_at"]) and _parse_dt(row["settled_at"]) > cutoff_7_dt
        ]
        latest = _parse_dt(rows_30[0]["settled_at"]) if rows_30 else None
        portfolio_hits = conn.execute(
            "SELECT recommended_odds FROM edge_results "
            "WHERE result = 'hit' AND settled_at > ? ORDER BY predicted_ev DESC LIMIT 10",
            (cutoff_7,),
        ).fetchall()
        all_settled = conn.execute(
            "SELECT COUNT(*) FROM edge_results WHERE result IN ('hit', 'miss')"
        ).fetchone()[0]
        recent_results = conn.execute(
            "SELECT result FROM edge_results WHERE result IN ('hit', 'miss') "
            "ORDER BY settled_at DESC LIMIT 20"
        ).fetchall()

        streak = {"type": "none", "count": 0}
        if recent_results:
            streak_result = recent_results[0]["result"]
            streak["type"] = "win" if streak_result == "hit" else "loss"
            streak["count"] = 0
            for row in recent_results:
                if row["result"] == streak_result:
                    streak["count"] += 1
                else:
                    break

        stats_7d = _compute_stats(rows_7, 7)
        stats_30d = _compute_stats(rows_30, 30)
        tier_hit_rates = {
            tier: float(bucket["hit_rate"])
            for tier, bucket in stats_30d.get("by_tier", {}).items()
        }
        total_return = sum(float(row["recommended_odds"] or 0) * 100 for row in portfolio_hits)
        return SettlementBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at=_utc_now_iso(),
                source_name="edge_results",
                stale_minutes=_stale_minutes(latest.isoformat() if latest else None, now=now),
            ),
            stats_7d=stats_7d,
            stats_30d=stats_30d,
            streak=streak,
            portfolio_7d={
                "total_return": round(total_return, 2),
                "count": len(portfolio_hits),
                "stake_per_edge": 100,
            },
            tier_hit_rates=tier_hit_rates,
            total_settled=int(all_settled or 0),
        )
    finally:
        conn.close()


def _fetch_movements(match_key: str) -> MovementsBlock:
    now = datetime.now(timezone.utc)
    conn = connect_odds_db_readonly(ODDS_DB, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT side, movement_type, severity, old_odds, new_odds, implied_prob_change, "
            "bookmakers_moving, total_bookmakers, direction, velocity, window_minutes, narrative, detected_at "
            "FROM line_movements WHERE match_id = ? ORDER BY detected_at DESC LIMIT 10",
            (match_key,),
        ).fetchall()
        if not rows:
            return MovementsBlock(provenance=_empty_source("line_movements"))

        latest = _parse_dt(rows[0]["detected_at"])
        velocities = [abs(float(row["velocity"] or 0.0)) for row in rows]
        return MovementsBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at=_utc_now_iso(),
                source_name="line_movements",
                stale_minutes=_stale_minutes(latest.isoformat() if latest else None, now=now),
            ),
            movements=[_safe_row_dict(row) for row in rows],
            net_direction=str(rows[0]["direction"] or "stable"),
            movement_count=len(rows),
            velocity=round(sum(velocities) / len(velocities), 4) if velocities else 0.0,
            bookmakers_moving=max(int(row["bookmakers_moving"] or 0) for row in rows),
        )
    finally:
        conn.close()


def _fetch_injuries(
    home_key: str,
    away_key: str,
    home_name: str,
    away_name: str,
    league: str,
    sport: str,
) -> InjuriesBlock:
    now = datetime.now(timezone.utc)
    conn = connect_odds_db_readonly(ODDS_DB, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        news_rows = conn.execute(
            "SELECT ei.player_name, ei.team_key, ei.status, ei.injury_type, ei.confidence, "
            "ei.extracted_at, ei.expires_at, na.title, na.url, na.source "
            "FROM extracted_injuries ei "
            "LEFT JOIN news_articles na ON na.id = ei.article_id "
            "WHERE ei.team_key IN (?, ?) AND (ei.expires_at IS NULL OR ei.expires_at > ?) "
            "ORDER BY ei.extracted_at DESC LIMIT 20",
            (home_key, away_key, now.isoformat()),
        ).fetchall()
        api_rows = conn.execute(
            "SELECT league, team, player_name, injury_type, injury_reason, injury_status, fixture_date, fetched_at "
            "FROM team_injuries "
            "WHERE (? = '' OR league = ?) "
            "ORDER BY fetched_at DESC LIMIT 80",
            (league, league),
        ).fetchall()

        news_items = [_safe_row_dict(row) for row in news_rows]
        api_items = [
            item
            for item in (_safe_row_dict(row) for row in api_rows)
            if _league_matches_sport(str(item.get("league") or ""), sport)
            if str(item.get("injury_status") or "").strip() not in {"Missing Fixture", "Unknown"}
        ]
        home_injuries = [item for item in news_items if item.get("team_key") == home_key]
        away_injuries = [item for item in news_items if item.get("team_key") == away_key]
        home_injuries.extend([item for item in api_items if _team_name_matches_requested(str(item.get("team") or ""), home_name)])
        away_injuries.extend([item for item in api_items if _team_name_matches_requested(str(item.get("team") or ""), away_name)])
        latest_candidates = [
            _parse_dt(item.get("fetched_at") or item.get("extracted_at"))
            for item in (news_items + api_items)
        ]
        latest = max((dt for dt in latest_candidates if dt is not None), default=None)
        total = len({(item.get("player_name") or item.get("player")) for item in home_injuries + away_injuries if item.get("player_name") or item.get("player")})
        return InjuriesBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at=_utc_now_iso(),
                source_name="team_injuries+extracted_injuries",
                stale_minutes=_stale_minutes(latest.isoformat() if latest else None, now=now),
            ),
            api_football=api_items,
            news_extracted=news_items,
            home_injuries=home_injuries,
            away_injuries=away_injuries,
            total_injury_count=total,
        )
    finally:
        conn.close()


async def _run_with_timeout(func, *args, timeout: float, fallback):
    try:
        return await asyncio.wait_for(asyncio.to_thread(func, *args), timeout=timeout)
    except Exception:
        return fallback


async def _fetch_espn_context(match_key: str, league: str, sport: str) -> dict[str, Any]:
    home_key, away_key = _parse_match_key(match_key)
    try:
        from scrapers.match_context_fetcher import get_match_context

        return await asyncio.wait_for(
            get_match_context(
                home_team=home_key,
                away_team=away_key,
                league=league,
                sport=sport,
                live_safe=True,
            ),
            timeout=5.0,
        )
    except Exception:
        return {}


async def build_evidence_pack(
    match_key: str,
    edge_result: dict[str, Any],
    sport: str,
    league: str,
    *,
    espn_ctx: dict[str, Any] | None = None,
    home_team: str = "",
    away_team: str = "",
) -> EvidencePack:
    built_at = _utc_now_iso()
    home_key, away_key = _parse_match_key(match_key)
    identity = await _run_with_timeout(_fetch_fixture_identity, match_key, timeout=1.0, fallback={})
    home_name = home_team or identity.get("home_team") or _display_name(home_key)
    away_name = away_team or identity.get("away_team") or _display_name(away_key)

    ctx = espn_ctx if espn_ctx is not None else await _fetch_espn_context(match_key, league, sport)
    pack = EvidencePack(
        match_key=match_key,
        sport=sport,
        league=league,
        built_at=built_at,
        edge_state=_build_edge_state(edge_result),
        espn_context=_wrap_espn_context(ctx),
    )

    sa_task = _run_with_timeout(
        _fetch_sa_odds,
        match_key,
        timeout=2.0,
        fallback=SAOddsBlock(provenance=_empty_source("odds_latest", error="timeout")),
    )
    _news_rosters = _extract_rosters_from_espn(ctx, home_name, away_name)
    news_task = _run_with_timeout(
        _fetch_news,
        home_key,
        away_key,
        home_name,
        away_name,
        league,
        sport,
        _news_rosters or None,
        timeout=2.0,
        fallback=NewsBlock(provenance=_empty_source("news_articles", error="timeout")),
    )
    sharp_task = _run_with_timeout(
        _fetch_sharp_lines,
        match_key,
        timeout=2.0,
        fallback=SharpLinesBlock(provenance=_empty_source("sharp_odds", error="timeout")),
    )
    settlement_task = _run_with_timeout(
        _fetch_settlement_stats,
        timeout=2.0,
        fallback=SettlementBlock(provenance=_empty_source("edge_results", error="timeout")),
    )
    movements_task = _run_with_timeout(
        _fetch_movements,
        match_key,
        timeout=2.0,
        fallback=MovementsBlock(provenance=_empty_source("line_movements", error="timeout")),
    )
    injuries_task = _run_with_timeout(
        _fetch_injuries,
        home_key,
        away_key,
        home_name,
        away_name,
        league,
        sport,
        timeout=2.0,
        fallback=InjuriesBlock(provenance=_empty_source("injuries", error="timeout")),
    )
    h2h_task = _run_with_timeout(
        _fetch_h2h_from_match_results,
        home_key,
        away_key,
        home_name,
        away_name,
        league,
        sport,
        timeout=2.0,
        fallback=None,
    )

    (
        pack.sa_odds,
        pack.news,
        pack.sharp_lines,
        pack.settlement_stats,
        pack.movements,
        pack.injuries,
        pack.h2h,
    ) = await asyncio.gather(
        sa_task,
        news_task,
        sharp_task,
        settlement_task,
        movements_task,
        injuries_task,
        h2h_task,
    )

    if pack.h2h is None:
        pack.h2h = _build_h2h_from_espn(ctx, home_name, away_name)
    if pack.h2h is None:
        pack.h2h = H2HBlock(provenance=_empty_source("h2h", error="No verified H2H rows."))

    pack.richness_score, pack.sources_available = _score_richness(pack)
    return pack


def evidence_pack_to_dict(pack: EvidencePack) -> dict[str, Any]:
    return asdict(pack)


def serialise_evidence_pack(pack: EvidencePack) -> str:
    import json

    return json.dumps(evidence_pack_to_dict(pack), sort_keys=True, default=str)


def _ordinal(value: int | None) -> str:
    if not value:
        return "?"
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _safe_display_name(name: str, fallback: str = "") -> str:
    text = (name or "").strip()
    if text:
        return text
    return fallback


def _team_names_from_pack(pack: EvidencePack, spec) -> tuple[str, str]:
    home = _safe_display_name((pack.espn_context.home_team if pack.espn_context else {}).get("name", ""), getattr(spec, "home_name", ""))
    away = _safe_display_name((pack.espn_context.away_team if pack.espn_context else {}).get("name", ""), getattr(spec, "away_name", ""))
    if home and away:
        return home, away
    home_key, away_key = _parse_match_key(pack.match_key)
    return (
        home or _display_name(home_key),
        away or _display_name(away_key),
    )


def _fmt_float(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}%"


def _describe_evidence_class(evidence_class: str) -> str:
    descriptions = {
        "speculative": "Limited support. Acknowledge gaps and keep conviction low.",
        "lean": "Some support exists, but this is still a modest edge.",
        "supported": "Multiple signals align, but risk and uncertainty must still be named.",
        "conviction": "The evidence base is strong. Be clear and direct without overstating certainty.",
    }
    return descriptions.get(evidence_class or "", "Stay proportionate to the evidence available.")


def _format_sa_odds_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    block = pack.sa_odds
    if not block or not block.provenance.available or not block.odds_by_bookmaker:
        reason = (block.provenance.error if block else "") or "No SA odds rows available."
        return None, f"SA BOOKMAKER ODDS: {reason}"

    lines = []
    for bookmaker, odds in sorted(block.odds_by_bookmaker.items()):
        parts = []
        for outcome in ("home", "draw", "away"):
            value = odds.get(outcome)
            if value:
                parts.append(f"{outcome} {float(value):.2f}")
        if parts:
            lines.append(f"- {bookmaker}: " + " | ".join(parts))
    lines.append(f"Data age: {_fmt_float(block.provenance.stale_minutes, 1)} minutes")
    lines.append(f"Bookmaker count: {block.bookmaker_count}")
    return "\n".join(lines), None


def _format_edge_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    block = pack.edge_state
    if not block or not block.provenance.available:
        reason = (block.provenance.error if block else "") or "No edge-state snapshot available."
        return None, f"EDGE ANALYSIS: {reason}"

    movement_direction = "neutral"
    movement = block.signals.get("movement") if isinstance(block.signals, dict) else {}
    if isinstance(movement, dict):
        movement_direction = movement.get("direction") or movement.get("net_direction") or "neutral"

    fair_probability = None
    try:
        fair_probability = float(block.fair_probability)
    except (TypeError, ValueError):
        fair_probability = None

    edge_parts = [f"EV: {_fmt_pct(block.edge_pct, 1)}"]
    if fair_probability not in (None, 0.0):
        edge_parts.append(
            "Fair probability: "
            + _fmt_pct(fair_probability * 100 if fair_probability <= 1 else fair_probability, 1)
        )
    edge_parts.append(f"Composite: {_fmt_float(block.composite_score, 1)}/100")

    lines = [
        f"Outcome: {block.outcome or 'n/a'} | Tier: {block.edge_tier}",
        " | ".join(edge_parts),
        (
            f"Confirming signals: {block.confirming_signals} | "
            f"Contradicting signals: {block.contradicting_signals}"
        ),
        "Signal breakdown:",
        f"- Price edge: {_fmt_float(block.price_edge_score, 2)}",
        f"- Market agreement: {_fmt_float(block.market_agreement_score, 2)}",
        f"- Line movement: {_fmt_float(block.movement_score, 2)} ({movement_direction})",
        f"- Tipster consensus: {_fmt_float(block.tipster_score, 2)}",
        f"- Form/H2H: {_fmt_float(block.form_h2h_score, 2)}",
        f"- Lineup/injury: {_fmt_float(block.lineup_injury_score, 2)}",
        f"- Weather: {_fmt_float(block.weather_score, 2)}",
        f"Sharp benchmark available: {'yes' if block.sharp_available else 'no'}",
    ]
    return "\n".join(lines), None


def _format_elo_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    """R12-OVERNIGHT: Surface Elo ratings for team strength context."""
    try:
        from scrapers.db_connect import connect_odds_db
        conn = connect_odds_db("/home/paulsportsza/scrapers/odds.db")
        home_key = pack.match_key.split("_vs_")[0] if "_vs_" in pack.match_key else ""
        away_key = pack.match_key.split("_vs_")[1].rsplit("_", 1)[0] if "_vs_" in pack.match_key else ""
        if not home_key or not away_key:
            conn.close()
            return None, "ELO RATINGS: Could not parse team keys from match_key."
        home_row = conn.execute(
            "SELECT rating, matches_played FROM elo_ratings WHERE team = ? AND sport = ?",
            (home_key, pack.sport),
        ).fetchone()
        away_row = conn.execute(
            "SELECT rating, matches_played FROM elo_ratings WHERE team = ? AND sport = ?",
            (away_key, pack.sport),
        ).fetchone()
        conn.close()
        if not home_row and not away_row:
            return None, "ELO RATINGS: No Elo data for either team."
        lines = []
        if home_row:
            lines.append(f"Home ({home_key.replace('_', ' ').title()}): rating {home_row[0]:.0f} ({home_row[1]} matches)")
        if away_row:
            lines.append(f"Away ({away_key.replace('_', ' ').title()}): rating {away_row[0]:.0f} ({away_row[1]} matches)")
        if home_row and away_row:
            diff = home_row[0] - away_row[0]
            lines.append(f"Rating gap: {abs(diff):.0f} points {'(home stronger)' if diff > 0 else '(away stronger)'}")
            # Rough win probability from Elo
            expected = 1 / (1 + 10 ** (-diff / 400))
            lines.append(f"Elo-implied home win probability: {expected * 100:.1f}%")
        return "\n".join(lines), None
    except Exception:
        return None, "ELO RATINGS: Elo lookup failed."


def _format_tipster_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    """R12-OVERNIGHT: Surface tipster consensus data."""
    try:
        from scrapers.db_connect import connect_odds_db
        conn = connect_odds_db("/home/paulsportsza/scrapers/tipsters/tipster_predictions.db")
        home_key = pack.match_key.split("_vs_")[0].replace("_", " ") if "_vs_" in pack.match_key else ""
        away_key = pack.match_key.split("_vs_")[1].rsplit("_", 1)[0].replace("_", " ") if "_vs_" in pack.match_key else ""
        if not home_key or not away_key:
            conn.close()
            return None, "TIPSTER CONSENSUS: Could not parse team names."
        # Match by fuzzy team names and recent date
        rows = conn.execute(
            """SELECT source, predicted_winner, home_win_pct, draw_pct, away_win_pct,
                      confidence, pick_summary
               FROM predictions
               WHERE LOWER(home_team) LIKE ? AND LOWER(away_team) LIKE ?
                 AND match_date >= date('now', '-7 days')
               ORDER BY scraped_at DESC""",
            (f"%{home_key.lower()}%", f"%{away_key.lower()}%"),
        ).fetchall()
        conn.close()
        if not rows:
            return None, "TIPSTER CONSENSUS: No tipster predictions found for this match."
        lines = [f"Sources checked: {len(rows)}"]
        winner_votes: dict[str, int] = {}
        for row in rows:
            source, winner, hw, dp, aw, conf, summary = row
            if winner:
                winner_votes[winner] = winner_votes.get(winner, 0) + 1
            conf_str = f" (confidence {conf:.0f}%)" if conf else ""
            lines.append(f"- {source}: predicts {winner or 'n/a'}{conf_str}")
        if winner_votes:
            top_pick = max(winner_votes, key=winner_votes.get)  # type: ignore[arg-type]
            agreement = winner_votes[top_pick]
            lines.append(f"Consensus: {agreement}/{len(rows)} sources back {top_pick}")
        return "\n".join(lines), None
    except Exception:
        return None, "TIPSTER CONSENSUS: Tipster data lookup failed."


def _format_espn_section(pack: EvidencePack, spec) -> tuple[str | None, str | None]:
    block = pack.espn_context
    if not block or not block.provenance.available or not block.data_available:
        reason = (block.provenance.error if block else "") or "No verified ESPN standings/form context."
        return None, f"ESPN STANDINGS & FORM: {reason}"

    home_name, away_name = _team_names_from_pack(pack, spec)
    home = block.home_team or {}
    away = block.away_team or {}
    def _line(team_name: str, team: dict) -> list[str]:
        return [
            f"{team_name}: {_ordinal(team.get('position'))}, {team.get('points', 'n/a')} pts, form {team.get('form') or team.get('last_5') or 'n/a'}",
            (
                f"  Record: {team.get('record') or 'n/a'} | Goals/game: "
                f"{team.get('goals_per_game') or team.get('gpg') or 'n/a'} | Coach: {team.get('coach') or 'n/a'}"
            ),
            f"  Last result: {team.get('last_result') or 'n/a'}",
        ]

    lines = _line(home_name, home) + _line(away_name, away)
    return "\n".join(lines), None


def _format_h2h_placeholder(pack: EvidencePack, spec) -> tuple[str | None, str | None]:
    if pack.h2h and pack.h2h.provenance.available and pack.h2h.matches:
        lines = [
            "Verified H2H context is injected after your output.",
            "Do NOT invent, paraphrase, summarize, or rewrite head-to-head yourself.",
            "Do NOT mention meetings, last meeting, fixture history, or H2H unless an injected H2H line is added separately.",
        ]
    else:
        lines = [
            "No verified H2H is available for this match.",
            "Do NOT mention head-to-head, meetings, last meeting, fixture history, or H2H anywhere.",
        ]
    return "\n".join(lines), None


def _build_locked_sharp_snippets(pack: EvidencePack) -> list[str]:
    block = pack.sharp_lines
    if not block or not block.provenance.available:
        return []

    bookmaker_rank = {
        "pinnacle": 0,
        "betfair": 1,
        "matchbook": 2,
        "smarkets": 3,
    }
    preferred_outcome = str(getattr(pack.edge_state, "outcome", "") or "").strip().lower()
    canonical: dict[tuple[str, str], tuple[int, str, str, float]] = {}

    def _store(bookmaker: Any, selection: Any, price: Any, priority: int) -> None:
        try:
            price_value = round(float(price), 2)
        except (TypeError, ValueError):
            return
        if price_value <= 1.0:
            return
        book = str(bookmaker or "").strip()
        outcome = str(selection or "").strip()
        if not book or not outcome:
            return
        key = (_normalise_sharp_bookmaker(book), outcome.lower())
        current = canonical.get(key)
        payload = (
            priority,
            book,
            outcome,
            price_value,
        )
        if current is None or priority < current[0]:
            canonical[key] = payload

    for selection, price in sorted((block.pinnacle_price or {}).items()):
        _store("Pinnacle", selection, price, 0)
    for selection, price in sorted((block.betfair_price or {}).items()):
        _store("Betfair", selection, price, 1)
    for benchmark in block.benchmarks[:6]:
        book = benchmark.get("bookmaker") or ""
        selection = benchmark.get("selection") or "selection"
        _store(book, selection, benchmark.get("back_price"), 2)
        _store(book, selection, benchmark.get("lay_price"), 3)
        _store(book, selection, benchmark.get("price"), 4)

    ordered = sorted(
        canonical.values(),
        key=lambda item: (
            0 if item[2].lower() == preferred_outcome else 1,
            bookmaker_rank.get(_normalise_sharp_bookmaker(item[1]), 99),
            item[0],
            item[2].lower(),
            item[3],
        ),
    )
    return [f"{book} {selection} {price:.2f}" for _, book, selection, price in ordered[:2]]


def _format_sharp_placeholder(pack: EvidencePack) -> tuple[str | None, str | None]:
    lines = [
        "Sharp pricing context is injected after your output.",
        "Do NOT mention Pinnacle, Betfair, Matchbook, Smarkets, or any sharp bookmaker by name.",
        "Do NOT cite any sharp price directly.",
        "If you discuss the pricing gap, use SA bookmaker prices only.",
    ]
    return "\n".join(lines), None


def _build_sharp_injection(pack: EvidencePack, spec) -> str:
    preferred_outcome = str(getattr(pack.edge_state, "outcome", "") or getattr(spec, "outcome", "") or "").strip().lower()
    if preferred_outcome not in {"home", "away", "draw"}:
        return ""
    if getattr(spec, "evidence_class", "") == "speculative" and getattr(spec, "tone_band", "") == "cautious":
        return ""

    snippets = _build_locked_sharp_snippets(pack)
    if not snippets:
        return ""

    parts = snippets[0].rsplit(" ", 2)
    if len(parts) != 3:
        return ""
    bookmaker, selection, price = parts
    selection_key = str(selection or "").strip().lower()
    if selection_key != preferred_outcome:
        return ""
    # R12-BUILD-03 Fix 3b: "Sharp market pricing" is a banned phrase — use "Market pricing"
    return f"Market pricing has {selection_key} at {price}."


def _build_h2h_injection(pack: EvidencePack, spec) -> str:
    block = pack.h2h
    if not (block and block.provenance.available and block.matches):
        return ""
    summary_text = str(block.summary_text or "").strip()
    if not summary_text:
        return ""
    sentence = f"Head to head: {summary_text}"
    latest_score = str((block.matches[0] or {}).get("score") or "").strip()
    if latest_score:
        sentence += f", and the last meeting finished {latest_score}"
    return sentence.rstrip(".") + "."


def _inject_h2h_sentence(draft: str, h2h_sentence: str) -> str:
    text = str(draft or "").strip()
    sentence = str(h2h_sentence or "").strip()
    if not text or not sentence or sentence in text:
        return text

    match = re.search(r"(📋[^\n]*\n)(.*?)(\n\n🎯[^\n]*\n)", text, flags=re.DOTALL)
    if not match:
        return text

    header, setup_body, edge_marker = match.groups()
    leading = text[:match.start()]
    trailing = text[match.end():]
    body = setup_body.strip()
    if not body:
        new_body = sentence
    else:
        paragraphs = body.split("\n\n", 1)
        first = paragraphs[0].strip()
        rest = paragraphs[1].strip() if len(paragraphs) > 1 else ""
        if first and first[-1] not in ".!?":
            first += "."
        new_body = f"{first} {sentence}".strip()
        if rest:
            new_body = f"{new_body}\n\n{rest}"

    return f"{leading}{header}{new_body}{edge_marker}{trailing}".strip()


def _inject_sharp_sentence(draft: str, sharp_sentence: str) -> str:
    text = str(draft or "").strip()
    sentence = str(sharp_sentence or "").strip()
    if not text or not sentence or sentence in text:
        return text

    match = re.search(r"(🎯[^\n]*\n)(.*?)(\n\n⚠️[^\n]*\n)", text, flags=re.DOTALL)
    if not match:
        return text

    header, edge_body, risk_marker = match.groups()
    leading = text[:match.start()]
    trailing = text[match.end():]
    body = edge_body.strip()
    if not body:
        new_body = sentence
    else:
        paragraphs = body.split("\n\n", 1)
        first = paragraphs[0].strip()
        rest = paragraphs[1].strip() if len(paragraphs) > 1 else ""
        if first and first[-1] not in ".!?":
            first += "."
        new_body = f"{first} {sentence}".strip()
        if rest:
            new_body = f"{new_body}\n\n{rest}"

    return f"{leading}{header}{new_body}{risk_marker}{trailing}".strip()


def _strip_model_generated_sharp_references(draft: str) -> str:
    text = str(draft or "").strip()
    if not text:
        return ""

    sharp_books = re.compile(r"\b(?:pinnacle|betfair(?:\s+ex(?:\s+(?:eu|uk))?)?|matchbook|smarkets)\b", re.IGNORECASE)
    parts = re.split(r"(\n\n+)", text)
    cleaned_parts: list[str] = []

    for part in parts:
        if not part:
            continue
        if re.fullmatch(r"\n\n+", part):
            cleaned_parts.append(part)
            continue

        lines = part.split("\n", 1)
        header = lines[0] if lines and lines[0].startswith(("📋", "🎯", "⚠️", "🏆")) else ""
        body = lines[1] if header and len(lines) > 1 else ("" if header else part)
        body = body.strip()
        if not body:
            cleaned_parts.append(header or part)
            continue

        sentences = re.split(r"(?<=[.!?])\s+", body)
        filtered = [sentence for sentence in sentences if sentence and not sharp_books.search(sentence)]
        rebuilt = " ".join(filtered).strip()
        if header:
            cleaned_parts.append(f"{header}\n{rebuilt}".rstrip() if rebuilt else header)
        elif rebuilt:
            cleaned_parts.append(rebuilt)

    cleaned = "".join(cleaned_parts)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _contains_h2h_reference_for_strip(text: str) -> bool:
    if not text:
        return False
    if _is_h2h_absence_statement(text):
        return True
    if _extract_h2h_chunks(text):
        return True
    lower_text = text.lower()
    if re.search(r"\b\d+W\b.*\b\d+D\b.*\b\d+L\b", text, flags=re.IGNORECASE):
        return bool(
            re.search(
                r"\b(?:head[\s-]+to[\s-]+head|h2h|\d+\s+meetings?|recent\s+meetings?|last\s+meeting)\b",
                lower_text,
                flags=re.IGNORECASE,
            )
        )
    return False


def _strip_model_generated_h2h_references(draft: str) -> str:
    text = str(draft or "").strip()
    if not text:
        return ""

    parts = re.split(r"(\n\n+)", text)
    cleaned_parts: list[str] = []

    for part in parts:
        if not part:
            continue
        if re.fullmatch(r"\n\n+", part):
            cleaned_parts.append(part)
            continue

        lines = part.split("\n", 1)
        header = lines[0] if lines and lines[0].startswith(("📋", "🎯", "⚠️", "🏆")) else ""
        body = lines[1] if header and len(lines) > 1 else ("" if header else part)
        body = body.strip()
        if not body:
            cleaned_parts.append(header or part)
            continue

        sentences = re.split(r"(?<=[.!?])\s+", body)
        filtered = [sentence for sentence in sentences if sentence and not _contains_h2h_reference_for_strip(sentence)]
        rebuilt = " ".join(filtered).strip()
        if header:
            cleaned_parts.append(f"{header}\n{rebuilt}".rstrip() if rebuilt else header)
        elif rebuilt:
            cleaned_parts.append(rebuilt)

    cleaned = "".join(cleaned_parts)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _format_sharp_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    block = pack.sharp_lines
    if not block or not block.provenance.available:
        reason = (block.provenance.error if block else "") or "No sharp benchmark lines."
        return None, f"SHARP BENCHMARK LINES: {reason}"

    snippets = _build_locked_sharp_snippets(pack)
    if not snippets:
        lines = [
            "No safe locked sharp snippet is available for this match.",
            "Omit sharp discussion completely.",
        ]
        return "\n".join(lines), None

    lines = [
        "Locked sharp snippets. If you mention sharp at all, copy exactly one snippet below and do not alter it.",
    ]
    for snippet in snippets:
        lines.append(f"- {snippet}")
    lines.append("Use at most one sharp snippet. Do NOT combine, compare, average, interpolate, or remap these prices.")
    lines.append("If none of these exact snippets fits cleanly, omit sharp discussion completely.")
    return "\n".join(lines), None


def _format_movements_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    block = pack.movements
    if not block or not block.provenance.available or not block.movements:
        reason = (block.provenance.error if block else "") or "No line movement history."
        return None, f"LINE MOVEMENTS: {reason}"

    lines = []
    for movement in block.movements[:6]:
        book = movement.get("bookmaker") or "unknown"
        selection = movement.get("selection") or movement.get("outcome") or "selection"
        old_price = movement.get("old_price")
        new_price = movement.get("new_price")
        moved_at = movement.get("moved_at") or movement.get("observed_at") or ""
        lines.append(
            f"- {book} {selection}: {old_price} -> {new_price} at {moved_at or 'unknown time'}"
        )
    lines.append(f"Net direction: {block.net_direction}")
    lines.append(f"Velocity: {_fmt_float(block.velocity, 2)}")
    lines.append(f"Bookmakers moving: {block.bookmakers_moving}")
    return "\n".join(lines), None


def _format_news_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    block = pack.news
    if not block or not block.provenance.available or not block.articles:
        reason = (block.provenance.error if block else "") or "No relevant team headlines."
        return None, f"NEWS HEADLINES: {reason}"

    lines = []
    for article in block.articles[:6]:
        title = str(article.get("title") or "").strip()
        if not title:
            continue
        source = str(article.get("source") or article.get("db_source") or "unknown").strip()
        published = article.get("published_at") or article.get("scraped_at") or "unknown time"
        lines.append(f"- {title} ({source}, {published})")
    lines.append(f"Article count: {block.article_count}")
    lines.append(f"Injury-related articles: {len(block.injury_mentions)}")
    return "\n".join(lines), None


def _format_injuries_section(pack: EvidencePack, spec) -> tuple[str | None, str | None]:
    block = pack.injuries
    if not block or not block.provenance.available or (
        not block.home_injuries and not block.away_injuries and not block.news_extracted and not block.api_football
    ):
        reason = (block.provenance.error if block else "") or "No verified injury rows."
        return None, f"INJURY REPORT: {reason}"

    home_name, away_name = _team_names_from_pack(pack, spec)

    def _fmt(items: list[dict[str, Any]]) -> str:
        if not items:
            return "none listed"
        formatted = []
        for item in items[:6]:
            player = item.get("player_name") or item.get("name") or "Unknown player"
            status = item.get("injury_status") or item.get("status") or item.get("reason") or "status unknown"
            formatted.append(f"{player} ({status})")
        return ", ".join(formatted)

    lines = [
        f"{home_name}: {_fmt(block.home_injuries)}",
        f"{away_name}: {_fmt(block.away_injuries)}",
        f"Total injury count: {block.total_injury_count}",
    ]
    return "\n".join(lines), None


def _format_settlement_section(pack: EvidencePack) -> tuple[str | None, str | None]:
    block = pack.settlement_stats
    if not block or not block.provenance.available or not block.total_settled:
        reason = (block.provenance.error if block else "") or "No recent settlement history."
        return None, f"SETTLEMENT TRACK RECORD: {reason}"

    stats_7d = block.stats_7d or {}
    stats_30d = block.stats_30d or {}
    tier_label, tier_rate = next(iter((block.tier_hit_rates or {}).items()), ("n/a", 0.0))
    streak = block.streak or {}

    lines = [
        f"7-day: {_fmt_pct((stats_7d.get('hit_rate') or 0.0) * 100, 1)} hit rate ({stats_7d.get('total', 0)} edges)",
        f"30-day: {_fmt_pct((stats_30d.get('hit_rate') or 0.0) * 100, 1)} hit rate ({stats_30d.get('total', 0)} edges)",
        f"{tier_label} tier: {_fmt_pct(float(tier_rate) * 100 if float(tier_rate) <= 1 else float(tier_rate), 1)} hit rate",
        f"Current streak: {streak.get('label') or streak.get('direction') or 'n/a'}",
    ]
    return "\n".join(lines), None


def format_evidence_prompt(pack: EvidencePack, spec) -> str:
    """Format the approved Phase B shadow reasoning prompt from evidence only."""
    from narrative_spec import TONE_BANDS

    tone_band = TONE_BANDS.get(spec.tone_band, {"allowed": [], "banned": []})
    home_name, away_name = _team_names_from_pack(pack, spec)

    sections: list[tuple[str, str]] = []
    unavailable: list[str] = []
    for title, formatter in (
        ("SA BOOKMAKER ODDS", _format_sa_odds_section),
        ("EDGE ANALYSIS", _format_edge_section),
        ("ESPN STANDINGS & FORM", lambda p: _format_espn_section(p, spec)),
        ("ELO RATINGS", _format_elo_section),
        ("TIPSTER CONSENSUS", _format_tipster_section),
        ("HEAD TO HEAD", lambda p: _format_h2h_placeholder(p, spec)),
        ("SHARP BENCHMARK LINES", _format_sharp_placeholder),
        ("LINE MOVEMENTS", _format_movements_section),
        ("NEWS HEADLINES", _format_news_section),
        ("INJURY REPORT", lambda p: _format_injuries_section(p, spec)),
        ("SETTLEMENT TRACK RECORD", _format_settlement_section),
    ):
        body, missing = formatter(pack)
        if body:
            sections.append((title, body))
        elif missing:
            unavailable.append(missing)

    if not unavailable:
        unavailable.append("None.")

    prompt_parts = [
        "You are a sharp South African sports betting analyst writing for MzansiEdge.",
        "Your readers are informed punters who want analytical depth, not template prose.",
        "",
        "You write like a mate at the braai who actually knows the numbers: punchy, direct,",
        "occasionally irreverent, but always evidence-grounded. You never bluff.",
        "",
        "RULES (violation = AUTOMATIC REJECTION — no exceptions):",
        "1. Every factual claim must trace to a specific field in the EVIDENCE PACK below.",
        "2. You may interpret and prioritise, but ONLY from the evidence provided.",
        "3. You must NOT invent, fabricate, or infer ANY facts, statistics, standings, form records, points tallies, goals-per-game figures, win/draw/loss records, coaches, player names, or events that are not EXPLICITLY present in the evidence pack. This is the #1 failure mode — fabricating plausible-sounding data when a source is missing.",
        "4. You must NOT use general sports knowledge, memory, or training-data knowledge to fill gaps.",
        "5. You must NOT imply stronger support than the evidence warrants.",
        "6. If a source is listed under [EVIDENCE NOT AVAILABLE], you MUST NOT reference ANY data from that source — not even plausible guesses. Pivot to what IS available instead.",
        "7. You must respect the TONE BAND and VERDICT CONSTRAINTS below.",
        "8. The phrase 'value play' is banned. Do NOT use it anywhere.",
        "9. Do NOT mention Pinnacle, Betfair, Matchbook, Smarkets, or any sharp bookmaker prices. Sharp context is injected separately.",
        "10. Never use banned filler such as 'thin support', 'pure pricing call', or 'supporting evidence is thin'. Prefer 'limited support', 'price-led angle', or evidence-specific wording. Do NOT use the phrases 'sharp market pricing' or 'worth backing'.",
        "11. Do NOT use the phrases 'knockout football', 'knockout stakes', 'knockout stage', 'knockout tie', 'knockout clash'. UCL league-phase matches are NOT knockouts. Describe match dynamics, not format labels.",
        "",
        "───────────── EVIDENCE PACK ─────────────",
        "",
        f"MATCH: {home_name} vs {away_name}",
        f"COMPETITION: {getattr(spec, 'competition', '') or pack.league}",
        f"SPORT: {pack.sport}",
        f"EVIDENCE RICHNESS: {pack.richness_score} ({pack.sources_available}/{pack.sources_total} sources)",
    ]

    for title, body in sections:
        prompt_parts.extend(["", f"[{title}]", body])

    # Build explicit anti-hallucination block for unavailable sources
    _espn_unavailable = any("ESPN" in item for item in unavailable)
    _injury_unavailable = any("INJURY" in item.upper() for item in unavailable)
    _news_unavailable = any("NEWS" in item.upper() for item in unavailable)

    hallucination_guard_lines: list[str] = []
    if _espn_unavailable:
        hallucination_guard_lines.extend([
            "• ESPN STANDINGS & FORM is NOT available. You MUST NOT mention:",
            "  league positions, points tallies, form strings (W/D/L sequences),",
            "  goals per game, season records, or coaches from this source.",
            "  Any fabricated standing/form data = AUTOMATIC REJECTION.",
        ])
    if _injury_unavailable:
        hallucination_guard_lines.extend([
            "• INJURY REPORT is NOT available. You MUST NOT name injured players",
            "  or reference squad availability.",
        ])
    if _news_unavailable:
        hallucination_guard_lines.extend([
            "• NEWS HEADLINES is NOT available. You MUST NOT reference recent",
            "  team news, transfers, or pre-match storylines.",
        ])

    prompt_parts.extend([
        "",
        "[EVIDENCE NOT AVAILABLE]",
        "\n".join(f"- {item}" for item in unavailable),
    ])

    if hallucination_guard_lines:
        prompt_parts.extend([
            "",
            "⛔ CRITICAL ANTI-HALLUCINATION GUARD:",
            "The above sources are genuinely missing — not redacted. DO NOT fill the gap",
            "with plausible-sounding data from your training knowledge.",
        ] + hallucination_guard_lines + [
            "",
            "Focus your narrative on what IS in the evidence pack: odds structure,",
            "edge analysis, line movements, and any other available sources.",
        ])

    prompt_parts.extend([
        "",
        "───────────── CONSTRAINTS ─────────────",
        "",
        f"TONE BAND: {spec.tone_band}",
        f"Allowed phrases: {', '.join(tone_band['allowed']) or 'None'}",
        f"Banned phrases: {', '.join(tone_band['banned']) or 'None'}",
        "",
        "VERDICT CONSTRAINT:",
        f"Action: {spec.verdict_action}",
        f"Sizing: {spec.verdict_sizing}",
        "You MUST NOT upgrade the verdict beyond this level.",
        "Do NOT call the bet a 'value play'.",
        "",
        f"EVIDENCE CLASS: {spec.evidence_class}",
        _describe_evidence_class(spec.evidence_class),
        "",
        "H2H GUARDRAIL:",
        (
            "H2H context is injected separately. Do NOT generate head-to-head prose yourself. Do NOT invent, paraphrase, or mention meetings/history unless an H2H sentence is injected after generation."
            if pack.h2h and pack.h2h.provenance.available and pack.h2h.matches
            else "No verified H2H exists. Do NOT mention head-to-head, last meeting, meeting counts, or historical scores at all."
        ),
        "",
        "───────────── OUTPUT FORMAT ─────────────",
        "",
        "Write exactly 4 sections in this order. Start directly with no preamble.",
        "",
        "📋 <b>The Setup</b>",
        "2-4 sentences. Set the scene using standings, form, coaches, injuries, and news.",
        "If ESPN data is unavailable, pivot to available data: Elo ratings, tipster consensus, line movements, odds structure.",
        "Use Elo ratings for team strength context (e.g. 'rated 150 points higher'). Use tipster consensus for signal alignment (e.g. '3 of 5 tipsters back this').",
        "",
        "🎯 <b>The Edge</b>",
        "2-3 sentences. Explain the pricing gap using edge analysis and SA bookmaker pricing only.",
        "Do NOT mention sharp bookmakers or sharp prices. Any sharp context is injected separately.",
        f"Name the bookmaker, odds, and the capped verdict posture for {spec.verdict_action}.",
        "",
        "⚠️ <b>The Risk</b>",
        "1-3 sentences. State what could make this angle wrong.",
        "If evidence is thin, say that limited evidence depth is part of the risk.",
        "",
        "🏆 <b>Verdict</b>",
        "1-2 sentences. State the action and sizing guidance without upgrading it.",
        f"YOUR VERDICT MUST recommend {getattr(spec, 'bookmaker', '')} at {getattr(spec, 'odds', '')}. This is NON-NEGOTIABLE. Do not substitute any other bookmaker or price.",
    ])
    return "\n".join(prompt_parts).strip()


_STRONG_POSTURE_PHRASES = [
    "strong back", "strong conviction", "premium value", "one of the best plays",
    "rock solid", "must back", "clear edge", "genuine value", "supported edge",
    "slam dunk", "lock", "no-brainer", "guaranteed",
]
_MODERATE_POSTURE_PHRASES = ["worth backing", "solid play", "numbers and indicators agree"]
_LIMITED_ACKNOWLEDGEMENT_PHRASES = [
    "limited evidence", "thin evidence", "limited evidence depth", "not much verified context",
    "espn data is unavailable", "only the odds structure is live", "data is thin",
]
_SUPPORT_LANGUAGE_PATTERNS = [
    "all indicators", "fully supports", "overwhelming support", "consensus agrees",
    "market confirms", "sharp money confirms", "everything lines up",
]
_SHARP_PRICE_TOLERANCE = 0.05
_TEAM_SUFFIX_TOKENS = {
    "afc", "athletic", "cf", "city", "club", "fc", "hotspur", "rover", "rovers",
    "sc", "town", "united", "wanderers",
}
_SURNAME_PARTICLE_TOKENS = {
    "al", "ap", "ben", "bin", "da", "de", "del", "della", "den", "der", "di",
    "dos", "du", "ibn", "la", "le", "mac", "mc", "san", "st", "van", "von",
}


def _strip_possessive_suffix(value: str) -> str:
    return re.sub(r"(?:'s|’s)\b", "", str(value or ""), flags=re.IGNORECASE)


def _name_word_tokens(value: Any) -> list[str]:
    # BASELINE-FIX-R3: NFKD normalise accented chars (é→e, ü→u) before tokenising.
    # Without this, "Konaté" produces ["konat"] instead of ["konate"].
    import unicodedata
    text = _strip_possessive_suffix(str(value or "").lower())
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return [token for token in re.findall(r"[a-z0-9]+", text) if token]


def _compact_name_phrase(value: Any) -> str:
    return " ".join(_name_word_tokens(value))


def _surname_key(value: Any) -> str:
    tokens = _name_word_tokens(value)
    if not tokens:
        return ""
    start = len(tokens) - 1
    while start > 0 and tokens[start - 1] in _SURNAME_PARTICLE_TOKENS:
        start -= 1
    return " ".join(tokens[start:])


def _injury_identity_key(value: Any) -> str:
    tokens = _name_word_tokens(value)
    if not tokens:
        return ""
    surname = _surname_key(value)
    if not surname:
        return " ".join(tokens)
    first_initial = ""
    if len(tokens[0]) == 1:
        first_initial = tokens[0]
    elif len(tokens[0]) > 1 and tokens[0] not in _SURNAME_PARTICLE_TOKENS:
        first_initial = tokens[0][0]
    return f"{first_initial}:{surname}"


def _flatten_name_tokens(name: str) -> set[str]:
    normalised = _strip_possessive_suffix(str(name or ""))
    parts = {part.strip() for part in re.split(r"[\s\-]+", normalised) if part.strip()}
    return {part for part in parts if len(part) >= 3}


def _extract_section(text: str, header: str, next_headers: list[str]) -> str:
    start = text.find(header)
    if start == -1:
        return ""
    end = len(text)
    for next_header in next_headers:
        idx = text.find(next_header, start + len(header))
        if idx != -1:
            end = min(end, idx)
    return text[start:end]


def _extract_form_strings(text: str) -> list[str]:
    return re.findall(r"\b[WDL]{3,6}\b", text)


def _extract_percentages(text: str) -> list[float]:
    values: list[float] = []
    for raw in re.findall(r"(\d+(?:\.\d+)?)\s*%", text):
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def _add_name_variants(target: set[str], value: Any, *, min_token_len: int = 4) -> None:
    text = str(value or "").strip()
    if not text:
        return
    lower = text.lower()
    target.add(lower)
    compact = _compact_name_phrase(text)
    if compact:
        target.add(compact)
    target.add(lower.replace("_", " "))
    target.add(lower.replace("-", " "))
    stripped = _strip_possessive_suffix(lower).strip()
    if stripped:
        target.add(stripped)
        target.add(stripped.replace("_", " "))
        target.add(stripped.replace("-", " "))
    for token in re.split(r"[\s_\-]+", lower):
        token = token.strip()
        if len(token) >= min_token_len:
            target.add(token)
            stripped_token = _strip_possessive_suffix(token).strip()
            if len(stripped_token) >= min_token_len:
                target.add(stripped_token)


def _add_percentage_variants(target: set[float], value: Any) -> None:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return
    if value_f == 0.0:
        return
    target.add(round(value_f, 2))
    target.add(round(value_f, 1))
    target.add(float(round(value_f)))


def _normalise_name_phrase(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalise_name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _team_base_tokens(name: str) -> list[str]:
    tokens = [token for token in _normalise_name_phrase(name).split() if token]
    if len(tokens) > 1 and tokens[-1] in _TEAM_SUFFIX_TOKENS:
        return tokens[:-1]
    return tokens


def _team_reference_variants(name: str) -> set[str]:
    variants: set[str] = set()
    normalized = _normalise_name_phrase(name)
    if not normalized:
        return variants
    variants.add(normalized)
    base_tokens = _team_base_tokens(name)
    if base_tokens:
        variants.add(" ".join(base_tokens))
        if len(base_tokens) == 1:
            variants.add(base_tokens[0])
    tokens = [token for token in normalized.split() if token]
    if len(tokens) >= 2 and len(tokens[-1]) >= 4:
        variants.add(tokens[-1])
    # BASELINE-FIX-R3: Add first significant token for multi-word names
    # (e.g. "Brighton" from "Brighton and Hove Albion")
    if len(tokens) >= 2 and len(tokens[0]) >= 4 and tokens[0] not in _TEAM_SUFFIX_TOKENS:
        variants.add(tokens[0])
    return {variant for variant in variants if variant}


def _build_team_reference_aliases(pack: EvidencePack, spec) -> dict[str, set[str]]:
    aliases = {"home": set(), "away": set()}
    side_names = {
        "home": [
            getattr(spec, "home_name", ""),
            ((pack.espn_context.home_team or {}).get("name", "") if pack.espn_context else ""),
        ],
        "away": [
            getattr(spec, "away_name", ""),
            ((pack.espn_context.away_team or {}).get("name", "") if pack.espn_context else ""),
        ],
    }

    canonical_keys: dict[str, set[str]] = {"home": set(), "away": set()}
    for side, names in side_names.items():
        for name in names:
            if not name:
                continue
            canonical_keys[side].add(_normalise_name_key(name))
            for variant in _team_reference_variants(name):
                aliases[side].add(variant)
                canonical_keys[side].add(_normalise_name_key(variant))

    try:
        import config

        for alias, canonical in getattr(config, "TEAM_ALIASES", {}).items():
            canonical_key = _normalise_name_key(canonical)
            for side in ("home", "away"):
                if canonical_key in canonical_keys[side]:
                    aliases[side].add(_normalise_name_phrase(alias))
    except Exception:
        pass

    explicit_aliases = {
        "psg": "Paris Saint-Germain",
        "spurs": "Tottenham",
        "man city": "Manchester City",
        "man united": "Manchester United",
        "brighton": "Brighton and Hove Albion",
        "glasgow": "Glasgow Warriors",
        "paris": "Paris Saint-Germain",
        "saint germain": "Paris Saint-Germain",
        "saint-germain": "Paris Saint-Germain",
        "barca": "Barcelona",
        "fcb": "Barcelona",
        "atletico": "Atletico Madrid",
        "atleti": "Atletico Madrid",
        "atm": "Atletico Madrid",
    }
    for alias, canonical in explicit_aliases.items():
        canonical_key = _normalise_name_key(canonical)
        for side in ("home", "away"):
            if canonical_key in canonical_keys[side]:
                aliases[side].add(_normalise_name_phrase(alias))

    shared = aliases["home"] & aliases["away"]
    if shared:
        aliases["home"] -= shared
        aliases["away"] -= shared

    return {
        side: {alias for alias in refs if alias}
        for side, refs in aliases.items()
    }


def _build_injury_team_exclusions(team_aliases: dict[str, set[str]]) -> set[str]:
    exclusions: set[str] = set()
    for refs in team_aliases.values():
        for alias in refs:
            normalized = _normalise_name_phrase(alias)
            if not normalized:
                continue
            exclusions.add(normalized)
            if not normalized.startswith("the "):
                exclusions.add(f"the {normalized}")
    return exclusions


def _contains_alias_reference(text: str, aliases: set[str]) -> bool:
    for alias in sorted(aliases, key=len, reverse=True):
        pattern = r"(?<![a-z0-9])" + re.escape(alias).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        if re.search(pattern, text or ""):
            return True
    return False


def _league_matches_sport(league: str, sport: str | None) -> bool:
    if not sport:
        return True
    try:
        import config

        league_key = str(league or "").strip().lower()
        return config.LEAGUE_SPORT.get(league_key) == sport
    except Exception:
        return False


def _team_name_matches_requested(row_team: str, requested_team: str) -> bool:
    row_norm = _normalise_name_phrase(row_team)
    req_norm = _normalise_name_phrase(requested_team)
    if not row_norm or not req_norm:
        return False
    if row_norm == req_norm:
        return True

    row_base = [token for token in _team_base_tokens(row_team) if token]
    req_base = [token for token in _team_base_tokens(requested_team) if token]
    if row_base and req_base and row_base == req_base:
        return True

    return False


def _build_simple_team_aliases(
    home_key: str,
    away_key: str,
    home_name: str,
    away_name: str,
) -> dict[str, set[str]]:
    aliases = {"home": set(), "away": set()}
    for side, values in {
        "home": [home_key, home_name],
        "away": [away_key, away_name],
    }.items():
        for value in values:
            aliases[side] |= _team_reference_variants(str(value or ""))
    return aliases


def _fetch_verified_injury_names(
    conn: sqlite3.Connection,
    home_key: str,
    away_key: str,
    home_name: str,
    away_name: str,
    league: str,
    sport: str,
) -> set[str]:
    verified: set[str] = set()
    now = datetime.now(timezone.utc).isoformat()

    extracted_rows = conn.execute(
        "SELECT player_name, team_key, extracted_at, expires_at "
        "FROM extracted_injuries "
        "WHERE team_key IN (?, ?) AND (expires_at IS NULL OR expires_at > ?)",
        (home_key, away_key, now),
    ).fetchall()
    for row in extracted_rows:
        if not _is_current_narrative_injury(extracted_at=row["extracted_at"]):
            continue
        _add_name_variants(verified, row["player_name"], min_token_len=3)

    api_rows = conn.execute(
        "SELECT league, team, player_name, injury_status, fixture_date, fetched_at "
        "FROM team_injuries "
        "WHERE (? = '' OR league = ?) "
        "AND injury_status NOT IN ('Missing Fixture', 'Unknown') "
        "ORDER BY fetched_at DESC LIMIT 80",
        (league, league),
    ).fetchall()
    for row in api_rows:
        if not _league_matches_sport(str(row["league"] or ""), sport):
            continue
        team = str(row["team"] or "")
        if not (
            _team_name_matches_requested(team, home_name)
            or _team_name_matches_requested(team, away_name)
        ):
            continue
        if not _is_current_narrative_injury(
            fixture_date=row["fixture_date"],
            fetched_at=row["fetched_at"],
        ):
            continue
        _add_name_variants(verified, row["player_name"], min_token_len=3)
    return verified


def _extract_title_injury_names(title: str) -> list[str]:
    head = re.split(r"\s[-:|]\s", str(title or "").strip(), maxsplit=1)[0]
    names = []
    for raw in re.split(r",|\band\b", head):
        cleaned = str(raw or "").strip()
        if not cleaned:
            continue
        if not re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){0,2}", cleaned):
            continue
        names.append(cleaned)
    return names


# Broader injury-context headline patterns (Fix 2)
_INJURY_CONTEXT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bchatter\s+(?:around|about|surrounding|regarding)\s+([A-Z][A-Za-z\'\-\.]+(?:\s+[A-Z][A-Za-z\'\-\.]+)?)\b"),
    re.compile(r"\bupdate\s+on\s+([A-Z][A-Za-z\'\-\.]+(?:\s+[A-Z][A-Za-z\'\-\.]+)?)\b"),
    re.compile(r"\bconcern\s+(?:over|about|surrounding|regarding)\s+([A-Z][A-Za-z\'\-\.]+(?:\s+[A-Z][A-Za-z\'\-\.]+)?)\b"),
    re.compile(r"\b([A-Z][A-Za-z\'\-\.]+(?:\s+[A-Z][A-Za-z\'\-\.]+)?)\s+injury\s+update\b"),
    re.compile(r"\b([A-Z][A-Za-z\'\-\.]+(?:\s+[A-Z][A-Za-z\'\-\.]+)?)\s+(?:scare|fitness\s+doubt|fitness\s+concern|injury\s+worry)\b"),
]


def _extract_contextual_player_names(title: str) -> list[str]:
    """Extract player names using broader injury-context patterns (e.g. 'chatter around X')."""
    names: list[str] = []
    for pattern in _INJURY_CONTEXT_PATTERNS:
        for match in pattern.finditer(str(title or "")):
            name = match.group(1).strip()
            if re.match(r"[A-Z][A-Za-z'.-]+", name):
                names.append(name)
    # Dedup preserving order
    seen: set[str] = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def _player_in_roster(player_name: str, roster: list[str]) -> bool:
    """Return True if player_name matches any entry in roster using the same matching logic
    as player_belongs_to_match_teams (accent-tolerant, last-name-first-initial matching)."""
    if not roster:
        return False
    # Route through the public helper by using a single dummy team so both
    # home_roster and away_roster resolve to the target roster.
    _DUMMY = "dummy_roster_check_only"
    return _player_belongs_to_match_teams(
        player_name, _DUMMY, _DUMMY,
        team_rosters={_DUMMY: roster},
    )


def _filter_cross_team_player_contamination(
    articles: list[dict[str, Any]],
    home_name: str,
    away_name: str,
    patterns_home: list[str],
    patterns_away: list[str],
    team_rosters: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Filter injury articles that mention players exclusively from the opposing team.

    An article is considered contaminated when:
    - It matched only ONE team's keyword patterns (i.e. was fetched for that team), AND
    - It contains a player name that is in the OPPOSING team's roster, AND
    - That player name is NOT in the article team's own roster.
    """
    home_roster = team_rosters.get(home_name) or []
    away_roster = team_rosters.get(away_name) or []
    if not home_roster or not away_roster:
        return articles  # No usable rosters — skip check (be permissive)

    filtered: list[dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title") or "").strip()
        lower = title.lower()

        # Only injury-related articles are candidates for contamination
        if not (article.get("has_injury_mentions") or "injur" in lower):
            filtered.append(article)
            continue

        matches_home = any(p in lower for p in patterns_home)
        matches_away = any(p in lower for p in patterns_away)

        # Mentions both teams → legitimate cross-coverage, keep
        if matches_home and matches_away:
            filtered.append(article)
            continue

        # Extract player names using both extraction methods
        names = _extract_title_injury_names(title) + _extract_contextual_player_names(title)
        if not names:
            filtered.append(article)
            continue

        contaminated = False
        for name in names:
            if matches_home and not matches_away:
                # Article tagged for HOME — flag if player is in AWAY roster but not HOME roster
                in_away = _player_in_roster(name, away_roster)
                in_home = _player_in_roster(name, home_roster)
                if in_away and not in_home:
                    contaminated = True
                    break
            elif matches_away and not matches_home:
                # Article tagged for AWAY — flag if player is in HOME roster but not AWAY roster
                in_home = _player_in_roster(name, home_roster)
                in_away = _player_in_roster(name, away_roster)
                if in_home and not in_away:
                    contaminated = True
                    break

        if not contaminated:
            filtered.append(article)

    return filtered


def _extract_rosters_from_espn(
    ctx: dict[str, Any],
    home_name: str,
    away_name: str,
) -> dict[str, list[str]]:
    """Build a {team_name: [player_names]} roster dict from ESPN context for contamination checks."""
    rosters: dict[str, list[str]] = {}
    if not ctx:
        return rosters

    for side_key, team_name in (("home_team", home_name), ("away_team", away_name)):
        side = ctx.get(side_key) or {}
        players: list[str] = []
        for scorer in side.get("top_scorers", []) or []:
            name = scorer.get("name", "") if isinstance(scorer, dict) else scorer
            if name:
                players.append(str(name))
        for player in side.get("key_players", []) or []:
            name = player.get("name", "") if isinstance(player, dict) else player
            if name:
                players.append(str(name))
        if players:
            rosters[team_name] = players

    return rosters


def _filter_injury_news_articles(
    articles: list[dict[str, Any]],
    verified_injured: set[str],
    team_aliases: dict[str, set[str]],
) -> list[dict[str, Any]]:
    team_exclusions = _build_injury_team_exclusions(team_aliases)
    filtered: list[dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title") or "").strip()
        lower = title.lower()
        if not (article.get("has_injury_mentions") or "injur" in lower):
            filtered.append(article)
            continue
        # Combine standard + broader contextual name extraction (Fix 2)
        title_names = _extract_title_injury_names(title)
        contextual_names = _extract_contextual_player_names(title)
        all_names = title_names + [n for n in contextual_names if n not in title_names]
        if not all_names:
            filtered.append(article)
            continue
        invalid = [
            name
            for name in all_names
            if _normalise_name_phrase(name) not in team_exclusions
            if not _match_verified_name(name, verified_injured, allow_single_token=True)
        ]
        if invalid:
            continue
        filtered.append(article)
    return filtered


def _text_chunks(text: str) -> list[str]:
    return [
        chunk.strip()
        for chunk in re.split(r"[\n\r]+|(?<=[.!?])\s+", text or "")
        if chunk.strip()
    ]


def _extract_decimal_odds(text: str) -> list[float]:
    values: list[float] = []
    for raw in re.findall(r"(?<![\d%])(\d+\.\d{1,2})(?!\s*%)", text or ""):
        try:
            price = float(raw)
        except ValueError:
            continue
        if price > 1.0:
            values.append(price)
    return values


def _build_verified_coaches(pack: EvidencePack, spec) -> set[str]:
    verified: set[str] = set()
    unique_coaches: dict[str, list[str]] = {}

    def _collect_coach(value: Any) -> None:
        text = _strip_possessive_suffix(str(value or "")).strip()
        if not text:
            return
        _add_name_variants(verified, text)
        key = _normalise_name_phrase(text)
        if key and key not in unique_coaches:
            unique_coaches[key] = [token for token in re.split(r"[\s\-]+", text) if token]

    if pack.espn_context and pack.espn_context.provenance.available:
        for side in (pack.espn_context.home_team or {}, pack.espn_context.away_team or {}):
            _collect_coach(side.get("coach") or side.get("manager") or "")
    for attr in ("home_coach", "away_coach"):
        _collect_coach(getattr(spec, attr, ""))

    coach_first_names: dict[str, int] = {}
    coach_last_names: dict[str, int] = {}
    for tokens in unique_coaches.values():
        if not tokens:
            continue
        if len(tokens[0]) >= 3:
            key = tokens[0].lower()
            coach_first_names[key] = coach_first_names.get(key, 0) + 1
        if len(tokens[-1]) >= 3:
            key = tokens[-1].lower()
            coach_last_names[key] = coach_last_names.get(key, 0) + 1

    for token, count in coach_first_names.items():
        if count == 1:
            verified.add(token)
    for token, count in coach_last_names.items():
        if count == 1:
            verified.add(token)
    return verified


def _iter_spec_injury_values(spec, attr: str) -> list[Any]:
    raw = getattr(spec, attr, None)
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        return list(raw)
    return [raw]


def _collect_verified_injury_names(pack: EvidencePack, spec) -> list[str]:
    names: list[str] = []
    if pack.injuries and pack.injuries.provenance.available:
        for injury in (
            list(pack.injuries.home_injuries)
            + list(pack.injuries.away_injuries)
            + list(pack.injuries.api_football)
            + list(pack.injuries.news_extracted)
        ):
            if isinstance(injury, dict):
                name = injury.get("player_name") or injury.get("player") or injury.get("name") or ""
            else:
                name = str(injury)
            if name:
                names.append(str(name))
    for attr in ("injuries_home", "injuries_away"):
        for item in _iter_spec_injury_values(spec, attr):
            if isinstance(item, dict):
                name = item.get("player_name") or item.get("player") or item.get("name") or ""
            else:
                name = str(item)
            if name:
                names.append(str(name))
    return names


def _build_unique_injury_surnames(pack: EvidencePack, spec) -> set[str]:
    surname_to_ids: dict[str, set[str]] = {}
    for name in _collect_verified_injury_names(pack, spec):
        surname = _surname_key(name)
        identity = _injury_identity_key(name)
        if not surname or not identity:
            continue
        surname_to_ids.setdefault(surname, set()).add(identity)
    return {
        surname
        for surname, identities in surname_to_ids.items()
        if len(identities) == 1
    }


def _build_unique_injury_single_tokens(pack: EvidencePack, spec) -> set[str]:
    token_to_ids: dict[str, set[str]] = {}
    for name in _collect_verified_injury_names(pack, spec):
        identity = _injury_identity_key(name)
        raw_tokens = _name_word_tokens(name)
        if not identity or not raw_tokens:
            continue

        candidate_tokens: set[str] = set()
        tokens = [token for token in raw_tokens if len(token) >= 3 and token not in _SURNAME_PARTICLE_TOKENS]
        if len(tokens) == 1 and len(raw_tokens) == 1:
            candidate_tokens.add(tokens[0])
        elif len(tokens) >= 2:
            for token in tokens[:-1]:
                candidate_tokens.add(token)

        for token in candidate_tokens:
            token_to_ids.setdefault(token, set()).add(identity)

    return {
        token
        for token, identities in token_to_ids.items()
        if len(identities) == 1
    }


def _build_verified_injured(pack: EvidencePack, spec) -> set[str]:
    verified: set[str] = set()
    unique_surnames = _build_unique_injury_surnames(pack, spec)

    for name in _collect_verified_injury_names(pack, spec):
        lower = _strip_possessive_suffix(str(name or "").strip().lower())
        compact = _compact_name_phrase(name)
        raw_tokens = _name_word_tokens(name)
        if lower:
            verified.add(lower)
            verified.add(lower.replace("_", " "))
            verified.add(lower.replace("-", " "))
        if compact:
            verified.add(compact)

        tokens = [token for token in raw_tokens if len(token) > 1]
        if len(tokens) >= 2:
            verified.add(" ".join(tokens))
            for token in tokens[:-1]:
                if len(token) >= 4 and token not in _SURNAME_PARTICLE_TOKENS:
                    verified.add(token)
        elif len(tokens) == 1 and len(raw_tokens) == 1 and len(tokens[0]) >= 3:
            verified.add(tokens[0])

        surname = _surname_key(name)
        if surname and surname in unique_surnames:
            verified.add(surname)
            surname_parts = surname.split()
            if len(surname_parts) > 1 and len(surname_parts[-1]) >= 4:
                verified.add(surname_parts[-1])

    return verified


def _build_verified_names(
    pack: EvidencePack,
    spec,
    verified_coaches: set[str],
    verified_injured: set[str],
    team_aliases: dict[str, set[str]],
) -> set[str]:
    verified: set[str] = set(verified_coaches) | set(verified_injured)

    # R12-OVERNIGHT: "Elo" is a system concept used in evidence packs, not a person name
    verified.add("elo")

    coach_first_names: dict[str, int] = {}
    for value in (
        getattr(spec, "home_name", ""),
        getattr(spec, "away_name", ""),
        getattr(spec, "competition", ""),
        getattr(spec, "bookmaker", ""),
        pack.league,
    ):
        _add_name_variants(verified, value, min_token_len=3)

    if pack.espn_context:
        _add_name_variants(verified, "ESPN", min_token_len=3)
        for side in (pack.espn_context.home_team or {}, pack.espn_context.away_team or {}):
            for key in ("name", "coach", "manager"):
                raw_value = side.get(key, "")
                _add_name_variants(verified, raw_value, min_token_len=3)
                if key in {"coach", "manager"}:
                    tokens = [token for token in re.split(r"[\s\-]+", str(raw_value or "").strip()) if len(token) >= 4]
                    if tokens:
                        coach_first_names[tokens[0].lower()] = coach_first_names.get(tokens[0].lower(), 0) + 1
            for scorer in side.get("top_scorers", []) or []:
                if isinstance(scorer, dict):
                    _add_name_variants(verified, scorer.get("name", ""))
                else:
                    _add_name_variants(verified, scorer)
            for player in side.get("key_players", []) or []:
                if isinstance(player, dict):
                    _add_name_variants(verified, player.get("name", ""))
                else:
                    _add_name_variants(verified, player)

    if pack.sa_odds and pack.sa_odds.provenance.available:
        for bookmaker in pack.sa_odds.odds_by_bookmaker:
            _add_name_variants(verified, bookmaker, min_token_len=3)
        for bookmaker in pack.sa_odds.best_bookmaker.values():
            _add_name_variants(verified, bookmaker, min_token_len=3)
        try:
            import config

            bookmaker_keys = {
                _normalise_name_key(bookmaker)
                for bookmaker in list(pack.sa_odds.odds_by_bookmaker) + list(pack.sa_odds.best_bookmaker.values())
                if bookmaker
            }
            for key, meta in getattr(config, "SA_BOOKMAKERS", {}).items():
                if _normalise_name_key(key) not in bookmaker_keys:
                    continue
                _add_name_variants(verified, meta.get("display_name", ""), min_token_len=3)
                _add_name_variants(verified, meta.get("short_name", ""), min_token_len=3)
        except Exception:
            pass
        try:
            import bot as bot_module

            for key, meta in getattr(bot_module, "SA_BOOKMAKERS_INFO", {}).items():
                if _normalise_name_key(key) not in bookmaker_keys:
                    continue
                _add_name_variants(verified, meta.get("name", ""), min_token_len=3)
        except Exception:
            pass

    if pack.sharp_lines and pack.sharp_lines.provenance.available:
        for benchmark in pack.sharp_lines.benchmarks:
            _add_name_variants(verified, benchmark.get("bookmaker", ""), min_token_len=3)
        for bookmaker in ("Pinnacle", "Betfair", "Matchbook", "Smarkets"):
            _add_name_variants(verified, bookmaker, min_token_len=3)

    if pack.news:
        for article in pack.news.articles:
            _add_name_variants(verified, article.get("source", ""), min_token_len=3)
            for phrase in re.findall(r"\b[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+)+\b", str(article.get("title") or "")):
                _add_name_variants(verified, phrase, min_token_len=3)

    for refs in team_aliases.values():
        for alias in refs:
            _add_name_variants(verified, alias, min_token_len=3)

    if pack.news:
        for article in (pack.news.home_team_articles or []) + (pack.news.away_team_articles or []):
            title = article.get("title", "") or article.get("headline", "")
            if title:
                for noun in re.findall(r"\b[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+)*\b", title):
                    _add_name_variants(verified, noun, min_token_len=3)

    for first_name, count in coach_first_names.items():
        if count == 1:
            verified.add(first_name)

    _KNOWN_COMPETITIONS = [
        "Premier League", "Champions League", "Europa League",
        "La Liga", "Bundesliga", "Serie A", "Ligue 1",
        "PSL", "Premiership", "URC", "United Rugby Championship",
        "Super Rugby", "Super Rugby Pacific", "Currie Cup",
        "Six Nations", "Rugby Championship",
        "SA20", "IPL", "Big Bash", "T20 World Cup",
    ]
    for comp in _KNOWN_COMPETITIONS:
        _add_name_variants(verified, comp, min_token_len=3)

    _KNOWN_NICKNAMES = [
        "The Seagulls", "The Toffees", "The Gunners", "The Reds",
        "The Blues", "The Foxes", "The Hammers", "The Magpies",
        "The Villans", "The Hornets", "The Canaries", "The Eagles",
        "The Cherries", "The Bees", "The Blades", "The Saints",
        "The Hatters", "The Cottagers", "The Robins", "The Baggies",
        "Amakhosi", "Masandawana", "Usuthu", "Buccaneers",
        "Ke Yona", "The Rockets", "Amatuks", "Wits",
        "Stormers", "Bulls", "Sharks", "Lions",
        "Springboks", "Proteas", "Bafana Bafana",
    ]
    for nickname in _KNOWN_NICKNAMES:
        _add_name_variants(verified, nickname, min_token_len=3)

    try:
        import bot as bot_module
        for nickname in getattr(bot_module, "_KNOWN_TEAM_NICKNAMES", set()):
            _add_name_variants(verified, nickname, min_token_len=3)
    except Exception:
        pass

    verified.update({
        "setup", "edge", "risk", "verdict", "the", "south", "african", "sa",
        "lean", "small", "standard", "stake", "value", "premium", "matchbook",
        "betfair", "pinnacle", "smarkets", "mzansiedge",
    })
    return {token for token in verified if token}


def _build_accepted_bookmaker_pairs(pack: EvidencePack, spec) -> set[tuple[str, float]]:
    accepted: set[tuple[str, float]] = set()
    if pack.sa_odds and pack.sa_odds.provenance.available:
        for bookmaker, outcomes in (pack.sa_odds.odds_by_bookmaker or {}).items():
            bookmaker_key = str(bookmaker or "").strip().lower().replace("_", " ")
            for price in (outcomes or {}).values():
                try:
                    price_value = float(price)
                except (TypeError, ValueError):
                    continue
                if price_value > 1.0:
                    accepted.add((bookmaker_key, round(price_value, 2)))
    bookmaker = str(getattr(spec, "bookmaker", "") or "").strip().lower()
    odds = getattr(spec, "odds", 0.0)
    try:
        odds_value = float(odds or 0.0)
    except (TypeError, ValueError):
        odds_value = 0.0
    if bookmaker and odds_value > 1.0:
        accepted.add((bookmaker.replace("_", " "), round(odds_value, 2)))
    return accepted


def _bookmaker_odds_match(text: str, accepted_pairs: set[tuple[str, float]]) -> tuple[bool, str]:
    lower = (text or "").lower()
    chunks = _text_chunks(text)
    for bookmaker, price in sorted(accepted_pairs):
        bookmaker_variants = {bookmaker, bookmaker.replace("_", " ")}
        for chunk in chunks:
            chunk_lower = chunk.lower()
            if not any(variant and variant in chunk_lower for variant in bookmaker_variants):
                continue
            prices = _extract_decimal_odds(chunk)
            if any(abs(found - price) <= 0.03 for found in prices):
                return True, f"Matched {bookmaker} {price:.2f}"
        if any(variant and variant in lower for variant in bookmaker_variants):
            prices = _extract_decimal_odds(text)
            if any(abs(found - price) <= 0.03 for found in prices):
                return True, f"Matched {bookmaker} {price:.2f}"
    return False, "No accepted bookmaker/odds pair found in output."


def _extract_named_references(text: str, patterns: list[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            value = match.group(1).strip()
            if value:
                matches.append(value)
    return matches


def _match_verified_name(
    name: str,
    verified: set[str],
    *,
    allow_single_token: bool = True,
    unique_surnames: set[str] | None = None,
    unique_single_tokens: set[str] | None = None,
) -> bool:
    lower = _strip_possessive_suffix(str(name or "").strip().lower())
    if not lower:
        return False
    compact = _compact_name_phrase(lower)
    if lower in verified or compact in verified:
        return True
    tokens = [token for token in _name_word_tokens(lower) if len(token) >= 3 and token not in _SURNAME_PARTICLE_TOKENS]
    if len(tokens) >= 2 and all(token in verified for token in tokens):
        return True
    surname = _surname_key(lower)
    if surname and unique_surnames and surname in unique_surnames:
        return True
    if not allow_single_token or len(tokens) != 1:
        return False
    token = tokens[0]
    if unique_single_tokens is not None:
        return token in unique_single_tokens
    return token in verified


def _normalise_sharp_bookmaker(bookmaker: str) -> str:
    key = str(bookmaker or "").strip().lower().replace("_", " ")
    if "betfair" in key:
        return "betfair"
    return key


def _build_accepted_sharp_prices(pack: EvidencePack) -> dict[str, set[float]]:
    accepted: dict[str, set[float]] = {}
    if not pack.sharp_lines or not pack.sharp_lines.provenance.available:
        return accepted

    def _add(bookmaker: str, price: Any) -> None:
        try:
            price_value = round(float(price), 2)
        except (TypeError, ValueError):
            return
        if price_value <= 1.0:
            return
        key = _normalise_sharp_bookmaker(bookmaker)
        if not key:
            return
        accepted.setdefault(key, set()).add(price_value)

    for benchmark in pack.sharp_lines.benchmarks:
        bookmaker = benchmark.get("bookmaker", "")
        for key in ("back_price", "lay_price", "price"):
            _add(bookmaker, benchmark.get(key))

    for bookmaker, price_map in (("Pinnacle", pack.sharp_lines.pinnacle_price), ("Betfair", pack.sharp_lines.betfair_price)):
        for price in (price_map or {}).values():
            _add(bookmaker, price)
    return accepted


def _extract_sharp_references(text: str) -> list[tuple[str, list[float]]]:
    references: list[tuple[str, list[float]]] = []
    book_pattern = re.compile(
        r"\b(pinnacle|betfair(?:\s+ex(?:\s+(?:eu|uk))?)?|matchbook|smarkets)\b",
        flags=re.IGNORECASE,
    )
    for chunk in _text_chunks(text):
        matches = list(book_pattern.finditer(chunk))
        for idx, match in enumerate(matches):
            bookmaker = _normalise_sharp_bookmaker(match.group(1))
            start = max(0, match.start() - 18)
            end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(chunk), match.end() + 80)
            window = chunk[start:end]
            references.append((bookmaker, _extract_decimal_odds(window)))
    return references


def _build_accepted_percentage_values(pack: EvidencePack, refs: dict[str, Any]) -> dict[str, set[float]]:
    accepted = {"direct": set(), "market_implied": set(), "sharp_implied": set(), "settlement": set()}

    for value in (refs.get("ev_pct"), refs.get("fair_prob_pct")):
        _add_percentage_variants(accepted["direct"], value)

    if pack.edge_state and pack.edge_state.provenance.available:
        _add_percentage_variants(accepted["direct"], pack.edge_state.edge_pct)
        # R12-BUILD-03 Fix 1b: Also accept absolute value of EV (Sonnet drops sign)
        try:
            _ev_pct_f = float(pack.edge_state.edge_pct)
            if _ev_pct_f < 0:
                _add_percentage_variants(accepted["direct"], abs(_ev_pct_f))
        except (TypeError, ValueError):
            pass
        fair_prob_pct = float(pack.edge_state.fair_probability or 0.0)
        if fair_prob_pct:
            if fair_prob_pct <= 1.0:
                fair_prob_pct *= 100.0
            _add_percentage_variants(accepted["direct"], fair_prob_pct)
        # R12-BUILD-03 Fix 1: Add composite_score to accepted values
        composite = getattr(pack.edge_state, "composite_score", None)
        if composite is not None:
            try:
                _add_percentage_variants(accepted["direct"], float(composite))
            except (TypeError, ValueError):
                pass
        # R12-BUILD-03 Fix 1: Add Elo probabilities
        elo_prob = getattr(pack.edge_state, "elo_prob", None)
        if elo_prob is not None:
            try:
                elo_val = float(elo_prob)
                _add_percentage_variants(accepted["direct"], elo_val * 100.0 if elo_val <= 1.0 else elo_val)
            except (TypeError, ValueError):
                pass

    # R12-OVERNIGHT: Add Elo-section computed probabilities from DB (these appear in evidence prompt)
    if pack.match_key and "_vs_" in pack.match_key:
        try:
            from scrapers.db_connect import connect_odds_db
            _elo_conn = connect_odds_db("/home/paulsportsza/scrapers/odds.db")
            _hk = pack.match_key.split("_vs_")[0]
            _ak = pack.match_key.split("_vs_")[1].rsplit("_", 1)[0]
            _hr = _elo_conn.execute("SELECT rating FROM elo_ratings WHERE team = ? AND sport = ?", (_hk, pack.sport)).fetchone()
            _ar = _elo_conn.execute("SELECT rating FROM elo_ratings WHERE team = ? AND sport = ?", (_ak, pack.sport)).fetchone()
            _elo_conn.close()
            if _hr and _ar:
                _diff = _hr[0] - _ar[0]
                _elo_exp = 1 / (1 + 10 ** (-_diff / 400))
                _add_percentage_variants(accepted["direct"], _elo_exp * 100.0)
                _add_percentage_variants(accepted["direct"], (1 - _elo_exp) * 100.0)
        except Exception:
            pass

    if pack.sa_odds and pack.sa_odds.provenance.available:
        for outcomes in (pack.sa_odds.odds_by_bookmaker or {}).values():
            for price in (outcomes or {}).values():
                try:
                    price_f = float(price)
                except (TypeError, ValueError):
                    continue
                if price_f > 1.0:
                    _add_percentage_variants(accepted["market_implied"], (1.0 / price_f) * 100.0)

    if pack.sharp_lines and pack.sharp_lines.provenance.available:
        for benchmark in pack.sharp_lines.benchmarks:
            for key in ("back_price", "lay_price", "price"):
                try:
                    price = float(benchmark.get(key))
                except (TypeError, ValueError):
                    continue
                if price > 1.0:
                    _add_percentage_variants(accepted["sharp_implied"], (1.0 / price) * 100.0)
        for price_map in (pack.sharp_lines.pinnacle_price, pack.sharp_lines.betfair_price):
            for price in (price_map or {}).values():
                try:
                    price_f = float(price)
                except (TypeError, ValueError):
                    continue
                if price_f > 1.0:
                    _add_percentage_variants(accepted["sharp_implied"], (1.0 / price_f) * 100.0)

    if pack.settlement_stats and pack.settlement_stats.provenance.available:
        for stats in (pack.settlement_stats.stats_7d, pack.settlement_stats.stats_30d):
            if stats and "hit_rate" in stats:
                _add_percentage_variants(accepted["settlement"], float(stats["hit_rate"]) * 100.0)
        for rate in (pack.settlement_stats.tier_hit_rates or {}).values():
            rate_f = float(rate)
            _add_percentage_variants(accepted["settlement"], rate_f * 100.0 if rate_f <= 1 else rate_f)
    return accepted


def _extract_percentage_contexts(text: str) -> list[tuple[float, str]]:
    contexts: list[tuple[float, str]] = []
    for chunk in _text_chunks(text):
        lower_chunk = chunk.lower()
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%", chunk):
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            contexts.append((value, lower_chunk))
    return contexts


_SHADOW_BANNED_PHRASE_REPLACEMENTS = (
    (r"\bthin support\b", "limited support"),
    (r"\bpure pricing call\b", "price-led angle"),
    (r"\bsupporting evidence is thin\b", "supporting evidence is limited"),
    (r"\bsharp market pricing\b", "market pricing"),
    (r"\bworth backing\b", "worth considering"),
)

_VERIFIER_BANNED_PHRASE_EXACT_ALLOWLIST = {
    "limited pre-match context",
    "limited pre match context",
}

_CONFIDENT_ASSERTIVE_PATTERNS = (
    r"\b(?:very|highly|extremely|really|fully)\s+confident\b",
    r"\bconfident\s+(?:stake|stakes|play|plays|bet|bets|back|backing|lean|leans|verdict|pick|picks|call)\b",
    r"\bconfident\s+(?:this|they|it|we)\b",
    r"\bconfident\s+enough\s+to\s+(?:back|bet|play|support)\b",
)

_CONFIDENT_CONTEXTUAL_PATTERNS = (
    r"\b(?:should|could|may|might|can)\s+(?:arrive|look|feel|be|seem|remain|grow)\s+confident\b",
    r"\b(?:arrive|arrives|arrived|look|looks|looked|feel|feels|felt|be|is|are|seem|seems|remain|remains|grew|grow|grows|growing)\s+confident\b",
    r"\bconfident\s+after\s+recent\s+(?:results|wins|performances|showings)\b",
    r"\bmore\s+confident\b",
)

_CONTEXTUAL_NEWS_FRAME_PATTERNS = (
    r"\b(?:current|broader)\s+(?:team|injury)\s+news\s+(?:picture|context|framing)\b",
    r"\b(?:team|injury)\s+news\s+(?:picture|context|framing)\b",
    r"\b(?:team|injury)\s+news\s+(?:is|looks|remains|stays)\s+(?:quiet|stable|light|limited|thin|muted|mixed|unclear)\b",
    r"\bwithout\s+(?:any\s+)?(?:fresh\s+)?(?:team|injury)\s+news\b",
    r"\b(?:broader|wider|current)\s+(?:team|injury|squad|selection|manager)\s+(?:picture|context|framing)\s+(?:stays|stayed|remains|remaining|looks)?\s*(?:quiet|stable|light|limited|thin|muted|mixed|unchanged)?\b",
    r"\b(?:team|injury|squad|selection)\s+(?:picture|context|framing)\s+(?:stays|stayed|remains|remaining|looks)\s+(?:quiet|stable|light|limited|thin|muted|mixed|unchanged)\b",
    r"\b(?:still\s+)?adapting\s+under\s+[a-z]+(?:\s+[a-z]+){0,2}(?:'s\s+management)?\b",
    r"\bunder\s+[a-z]+(?:\s+[a-z]+){0,2}'s\s+management\b",
)

_KNOWN_VERIFIED_VENUE_PHRASES = {
    "kings park",
    "kingspark",
    "kings park stadium",
    # EPL venues
    "selhurst park",
    "city ground",
    "stamford bridge",
    "emirates stadium",
    "emirates",
    "etihad stadium",
    "old trafford",
    "anfield",
    "goodison park",
    "elland road",
    "villa park",
    "st james park",
    "st james' park",
    "london stadium",
    "tottenham hotspur stadium",
    "craven cottage",
    "carrow road",
    "molineux",
    "turf moor",
    "vicarage road",
    "the amex",
    "amex stadium",
    "bramall lane",
    "portman road",
    "kenilworth road",
    "gtech community stadium",
    "sel park",
    # European venues
    "santiago bernabeu",
    "camp nou",
    "san siro",
    "allianz arena",
    "parc des princes",
    "signal iduna park",
    # SA venues
    "moses mabhida",
    "loftus versfeld",
    "fnb stadium",
    "ellis park",
    "dhl stadium",
    "wanderers stadium",
    "cape town stadium",
    "newlands",
    "newlands cricket",
    "boland park",
    "centurion park",
    "kingsmead",
    # Rugby/cricket venues
    "twickenham",
    "principality stadium",
    "murrayfield",
    "aviva stadium",
    "stade de france",
    "eden gardens",
    "lords",
    "the oval",
    "wanderers",
}

# R12-BUILD-03 Fix 5: Derby/geographical names that are NOT fabricated proper nouns
_DERBY_WHITELIST = {
    "merseyside", "the merseyside", "merseyside derby",
    "north london", "north london derby",
    "manchester", "manchester derby",
    "el clasico", "el cl\u00e1sico", "der klassiker",
    "old firm", "tyne-wear", "tyne-wear derby",
    "south coast derby", "revierderby", "soweto derby",
}

_SETTLEMENT_CONTEXT_PATTERNS = (
    r"\bsettlement\b",
    r"\bsettled\b",
    r"\bhit\s+rate\b",
    r"\bstrike\s+rate\b",
    r"\bconversion\s+rate\b",
    r"\btrack\s+record\b",
    r"\bresults?\s+sample\b",
    r"\bsample\b",
    r"\b(?:7|30)-day\b",
    r"\btier\s+hit\b",
)

_DIRECT_PERCENTAGE_CONTEXT_PATTERNS = (
    r"\bev\b",
    r"\bedge\b",
    r"\bfair\b",
    r"\bprob(?:ability)?\b",
    r"\bchance\b",
    r"\bimplied\b",
    r"\bvalue\b",
)


def _preserve_case_replacement(source: str, replacement: str) -> str:
    if not source:
        return replacement
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _suppress_shadow_banned_phrases(draft: str) -> str:
    text = str(draft or "")
    if not text:
        return ""
    for pattern, replacement in _SHADOW_BANNED_PHRASE_REPLACEMENTS:
        text = re.sub(
            pattern,
            lambda match, repl=replacement: _preserve_case_replacement(match.group(0), repl),
            text,
            flags=re.IGNORECASE,
        )
    return text


def _contains_banned_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", re.IGNORECASE)
    return bool(pattern.search(text))


def _is_banned_phrase_false_positive(text: str, phrase: str) -> bool:
    normalized_phrase = phrase.strip().lower()
    if normalized_phrase in _VERIFIER_BANNED_PHRASE_EXACT_ALLOWLIST:
        return True
    if normalized_phrase != "confident":
        return False
    if not _contains_banned_phrase(text, normalized_phrase):
        return False
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _CONFIDENT_ASSERTIVE_PATTERNS):
        return False
    return _contains_contextual_confident_usage(text)


def _contains_contextual_confident_usage(text: str) -> bool:
    lower = str(text or "").lower()
    return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in _CONFIDENT_CONTEXTUAL_PATTERNS)


def _contains_settlement_percentage_context(text: str) -> bool:
    lower = str(text or "").lower()
    return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in _SETTLEMENT_CONTEXT_PATTERNS)


def _contains_direct_percentage_context(text: str) -> bool:
    lower = str(text or "").lower()
    return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in _DIRECT_PERCENTAGE_CONTEXT_PATTERNS)


def _extract_h2h_score_patterns(text: str) -> list[str]:
    scores: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b(\d+)\s*-\s*(\d+)\b", text or ""):
        score = f"{int(match.group(1))}-{int(match.group(2))}"
        if score not in seen:
            seen.add(score)
            scores.append(score)
    return scores


def _extract_h2h_chunks(text: str) -> list[str]:
    cue = re.compile(
        r"\b(?:"
        r"head[\s-]+to[\s-]+head|"
        r"last\s+meeting|"
        r"last\s+met|"
        r"met\s+\d+\s+times|"
        r"\d+\s+meetings?\b|"
        r"(?:recent|previous|past|last)\s+meetings?\b|"
        r"history\s+between|"
        r"record\s+against|"
        r"h2h\b"
        r")\b",
        re.IGNORECASE,
    )
    return [chunk for chunk in _text_chunks(text) if cue.search(chunk)]


def _is_h2h_absence_statement(text: str) -> bool:
    patterns = [
        r"\bno\s+(?:verified\s+)?head[\s-]+to[\s-]+head\s+(?:history|data)(?:\s+available)?\b",
        r"\bwithout\s+(?:verified\s+)?head[\s-]+to[\s-]+head\s+(?:history|data)\b",
        r"\bmissing\s+(?:verified\s+)?head[\s-]+to[\s-]+head\s+(?:history|data)\b",
        r"\bno\s+(?:verified\s+)?head[\s-]+to[\s-]+head\s+block(?:\s+available)?\b",
        r"\bwithout\s+(?:verified\s+)?head[\s-]+to[\s-]+head\s+block\b",
        r"\bno\s+(?:verified\s+)?h2h\s+(?:history|data)(?:\s+available)?\b",
        r"\bwithout\s+(?:verified\s+)?h2h\s+(?:history|data)\b",
        r"\bmissing\s+(?:verified\s+)?h2h\s+(?:history|data)\b",
        r"\bno\s+(?:verified\s+)?h2h\s+block(?:\s+available)?\b",
        r"\bwithout\s+(?:verified\s+)?h2h\s+block\b",
        r"\bwithout\s+verified\s+h2h\s+history\b",
        r"\bmissing\s+(?:recent\s+)?meeting\s+data\b",
        r"\b(?:recent\s+)?meeting\s+data\s+(?:is\s+)?(?:missing|unavailable|not\s+verified)\b",
        r"\bno\s+(?:verified\s+)?meeting\s+history\b",
        r"\bflying\s+blind\s+on\s+(?:recent\s+)?meetings?\b",
        r"\b(?:history|meeting\s+data)\s+(?:is\s+)?(?:unavailable|not\s+verified)\b",
    ]
    lower = text or ""
    return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in patterns)


def _normalise_h2h_phrase(text: str) -> str:
    normalised = re.sub(r"<[^>]+>", " ", text or "")
    normalised = re.sub(r"head[\s-]+to[\s-]+head", "head to head", normalised, flags=re.IGNORECASE)
    normalised = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", normalised)
    normalised = re.sub(r"\s+", " ", normalised).strip().lower()
    return normalised.strip(" .,:;!?")


def _strip_h2h_lead_label(text: str) -> str:
    return re.sub(r"^(?:head to head|h2h)\s*:\s*", "", text or "", flags=re.IGNORECASE).strip()


def _h2h_chunk_matches_verified(chunk: str, summary_text: str, allowed_scores: set[str]) -> bool:
    normalised_chunk = _strip_h2h_lead_label(_normalise_h2h_phrase(chunk))
    if not normalised_chunk:
        return True

    summary_norm = _normalise_h2h_phrase(summary_text)
    if summary_norm and normalised_chunk == summary_norm:
        return True

    if not allowed_scores:
        return False

    score_alt = "|".join(re.escape(score) for score in sorted(allowed_scores))
    score_only = re.compile(
        rf"^(?:the\s+)?(?:last|most\s+recent|recent)\s+meeting\s+(?:finished|ended|was)\s+(?:a\s+)?(?:scoreline\s+of\s+)?(?:{score_alt})$",
        re.IGNORECASE,
    )
    if score_only.fullmatch(normalised_chunk):
        return True

    if summary_norm:
        summary_and_score = re.compile(
            rf"^{re.escape(summary_norm)}(?:,?\s+(?:and|with)\s+)?(?:the\s+)?(?:last|most\s+recent|recent)\s+meeting\s+(?:finished|ended|was)\s+(?:a\s+)?(?:scoreline\s+of\s+)?(?:{score_alt})$",
            re.IGNORECASE,
        )
        if summary_and_score.fullmatch(normalised_chunk):
            return True

    return False


def _h2h_summary_matches_claim(text: str, summary: dict[str, Any]) -> bool:
    if not text:
        return True
    total = int(summary.get("total") or 0)
    home_wins = int(summary.get("home_wins") or 0)
    draws = int(summary.get("draws") or 0)
    away_wins = int(summary.get("away_wins") or 0)

    for match in re.finditer(r"\b(\d+)\s+meetings?\b", text, flags=re.IGNORECASE):
        if int(match.group(1)) != total:
            return False
    for match in re.finditer(r"\b(\d+)W\b.*?\b(\d+)D\b.*?\b(\d+)L\b", text, flags=re.IGNORECASE):
        if (int(match.group(1)), int(match.group(2)), int(match.group(3))) != (home_wins, draws, away_wins):
            return False
    return True


def _trace_h2h_claims(text: str, pack: EvidencePack) -> tuple[bool, str]:
    block = pack.h2h
    if not (block and block.provenance.available and block.matches):
        return False, "No verified H2H block available."

    summary = block.summary or {}
    allowed_scores: set[str] = set()
    for match in block.matches:
        score = str(match.get("score") or "").strip()
        if score:
            allowed_scores.add(score)
            parts = score.split("-")
            if len(parts) == 2:
                allowed_scores.add(f"{parts[1].strip()}-{parts[0].strip()}")

    chunks = [chunk for chunk in _extract_h2h_chunks(text) if not _is_h2h_absence_statement(chunk)] or [text]
    for chunk in chunks:
        if not _h2h_chunk_matches_verified(chunk, block.summary_text or "", allowed_scores):
            return False, f"Unsupported H2H phrasing for chunk: {chunk}"
        if not _h2h_summary_matches_claim(chunk, summary):
            return False, f"H2H summary mismatch for chunk: {chunk}"
        score_patterns = _extract_h2h_score_patterns(chunk)
        if any(score not in allowed_scores for score in score_patterns):
            return False, f"H2H score mismatch for chunk: {chunk}"

    return True, f"Verified summary: {block.summary_text}; scores: {sorted(allowed_scores)}"


def _extract_candidate_proper_nouns(text: str) -> set[str]:
    candidates: set[str] = set()
    for chunk in _text_chunks(re.sub(r"<[^>]+>", " ", text or "")):
        for phrase in re.findall(r"\b[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+)+\b", chunk):
            tokens = [_strip_possessive_suffix(token).strip() for token in phrase.split() if token]
            if not tokens:
                continue
            if any(re.fullmatch(r"[WDL]{3,6}", token) for token in tokens):
                continue
            if all(re.fullmatch(r"[A-Z]{2,}", token) for token in tokens):
                continue
            if _is_non_name_proper_noun_phrase(phrase):
                continue
            # Skip phrases containing "SA" as a standalone abbreviation —
            # it's South Africa, not a person name.
            if any(token == "SA" for token in phrase.split()):
                continue
            candidates.add(phrase.strip())
    return candidates


_NON_NAME_PROPER_NOUN_PHRASES = {
    "across sa",
    "across south africa",
    "south africa",
    "with sa",
    "most sa",
    "from sa",
    "in sa",
    "for sa",
    "via sa",
    "than sa",
    "every sa",
    "all sa",
    "major sa",
    "other sa",
    "many sa",
    "five sa",
    "multiple sa",
    "our sa",
    "best sa",
    "top sa",
}


def _is_non_name_proper_noun_phrase(phrase: str) -> bool:
    return _normalise_name_phrase(phrase) in _NON_NAME_PROPER_NOUN_PHRASES


_NEWS_ABSENCE_PATTERNS = (
    r"\bno\s+(?:verified\s+|relevant\s+|reliable\s+)?(?:team\s+|injury\s+)?news\b",
    r"\bwithout\s+(?:verified\s+|relevant\s+|reliable\s+)?(?:team\s+|injury\s+)?news\b",
    r"\bno\s+(?:verified\s+|relevant\s+)?headlines?\b",
    r"\bwithout\s+(?:verified\s+|relevant\s+)?headlines?\b",
    r"\bno\s+reports?\b",
    r"\bwithout\s+reports?\b",
    r"\bno\s+latest\s+update\b",
    r"\bnews\s+is\s+unavailable\b",
)


_EXPLICIT_NEWS_CLAIM_PATTERNS = (
    r"\baccording to\b",
    r"\breports?\s+(?:say|suggest|indicate|claim|claimed|that)\b",
    r"\breported(?:ly)?\s+(?:to|as|by|in|that|set|expected|ruled|facing|miss|return)\b",
    r"\bsource(?:s)?\s+say\b",
    r"\bheadline(?:s)?\s+(?:say|says|suggest|show|shows|read|reads|indicate|indicates)\b",
    r"\b(?:team|injury)\s+news\s+(?:suggests|indicates|points\s+to|confirms|reports)\b",
    r"\bnews\s+has\s+filtered\s+through\s+that\b",
    r"\blatest\s+update\s+(?:suggests|indicates|confirms|is\s+that)\b",
)


def _is_news_absence_statement(text: str) -> bool:
    lower = str(text or "").lower()
    return any(re.search(pattern, lower) for pattern in _NEWS_ABSENCE_PATTERNS)


def _contains_explicit_news_claim(text: str) -> bool:
    lower = str(text or "").lower()
    if _is_news_absence_statement(lower):
        return False
    if any(re.search(pattern, lower) for pattern in _CONTEXTUAL_NEWS_FRAME_PATTERNS):
        return False
    return any(re.search(pattern, lower) for pattern in _EXPLICIT_NEWS_CLAIM_PATTERNS)


def _pack_allowed_names(pack: EvidencePack, spec) -> set[str]:
    names = {
        getattr(spec, "competition", ""),
        getattr(spec, "home_name", ""),
        getattr(spec, "away_name", ""),
        getattr(spec, "bookmaker", ""),
    }
    if pack.espn_context:
        home = pack.espn_context.home_team or {}
        away = pack.espn_context.away_team or {}
        names.update({
            home.get("name", ""),
            away.get("name", ""),
            home.get("coach", ""),
            away.get("coach", ""),
        })
    if pack.news:
        for article in pack.news.articles:
            names.add(str(article.get("source") or ""))
    if pack.injuries:
        for injury in list(pack.injuries.home_injuries) + list(pack.injuries.away_injuries):
            names.add(str(injury.get("player_name") or injury.get("name") or ""))
    filtered = set()
    for name in names:
        filtered.update(_flatten_name_tokens(name))
    filtered.update(
        {
            "Setup", "Edge", "Risk", "Verdict", "The", "South", "African", "SA",
            "MzansiEdge", "Lean", "Back", "Strong", "Small", "Standard", "Stake",
            "Premium", "Value",
        }
    )
    return {token for token in filtered if token}


def _resolve_reference_values(pack: EvidencePack, spec) -> dict[str, Any]:
    values: dict[str, Any] = {
        "home_name": getattr(spec, "home_name", ""),
        "away_name": getattr(spec, "away_name", ""),
        "bookmaker": getattr(spec, "bookmaker", ""),
        "odds": float(getattr(spec, "odds", 0.0) or 0.0),
        "ev_pct": float(getattr(spec, "ev_pct", 0.0) or 0.0),
        "fair_prob_pct": float(getattr(spec, "fair_prob_pct", 0.0) or 0.0),
        "evidence_class": getattr(spec, "evidence_class", ""),
        "verdict_action": getattr(spec, "verdict_action", ""),
        "richness_score": pack.richness_score,
        "home_form": "",
        "away_form": "",
        "home_position": None,
        "away_position": None,
        "home_points": None,
        "away_points": None,
        "coach_tokens": set(),
        "injury_tokens": set(),
        "news_titles": [str(article.get("title") or "") for article in (pack.news.articles if pack.news else [])],
        "news_available": bool(pack.news and pack.news.articles),
        "h2h_summary": (pack.h2h.summary_text if pack.h2h and pack.h2h.summary_text else getattr(spec, "h2h_summary", "")) or "",
        "sharp_prices": set(),
        "movement_score": 0.0,
        "tipster_score": 0.0,
        "form_h2h_score": 0.0,
        "lineup_injury_score": 0.0,
        "price_edge_score": 0.0,
        "market_agreement_score": 0.0,
        "stale_minutes": pack.sa_odds.provenance.stale_minutes if pack.sa_odds else 0.0,
    }

    if pack.espn_context:
        home = pack.espn_context.home_team or {}
        away = pack.espn_context.away_team or {}
        values["home_form"] = str(home.get("form") or home.get("last_5") or getattr(spec, "home_form", "") or "")
        values["away_form"] = str(away.get("form") or away.get("last_5") or getattr(spec, "away_form", "") or "")
        values["home_position"] = home.get("position") or getattr(spec, "home_position", None)
        values["away_position"] = away.get("position") or getattr(spec, "away_position", None)
        values["home_points"] = home.get("points") or getattr(spec, "home_points", None)
        values["away_points"] = away.get("points") or getattr(spec, "away_points", None)
        values["coach_tokens"] = {
            token
            for token in (
                _flatten_name_tokens(str(home.get("coach") or getattr(spec, "home_coach", "")))
                | _flatten_name_tokens(str(away.get("coach") or getattr(spec, "away_coach", "")))
            )
            if token
        }

    if pack.injuries:
        injury_tokens = set()
        for injury in list(pack.injuries.home_injuries) + list(pack.injuries.away_injuries):
            injury_tokens |= _flatten_name_tokens(str(injury.get("player_name") or injury.get("name") or ""))
        values["injury_tokens"] = injury_tokens

    if pack.edge_state:
        values["movement_score"] = float(pack.edge_state.movement_score or 0.0)
        values["tipster_score"] = float(pack.edge_state.tipster_score or 0.0)
        values["form_h2h_score"] = float(pack.edge_state.form_h2h_score or 0.0)
        values["lineup_injury_score"] = float(pack.edge_state.lineup_injury_score or 0.0)
        values["price_edge_score"] = float(pack.edge_state.price_edge_score or 0.0)
        values["market_agreement_score"] = float(pack.edge_state.market_agreement_score or 0.0)

    if pack.sharp_lines:
        sharp_prices = set()
        for price_map in (pack.sharp_lines.pinnacle_price, pack.sharp_lines.betfair_price):
            for price in (price_map or {}).values():
                try:
                    sharp_prices.add(round(float(price), 2))
                except (TypeError, ValueError):
                    continue
        for benchmark in pack.sharp_lines.benchmarks:
            for key in ("back_price", "lay_price"):
                try:
                    price = benchmark.get(key)
                    if price is not None:
                        sharp_prices.add(round(float(price), 2))
                except (TypeError, ValueError):
                    continue
        values["sharp_prices"] = sharp_prices

    if pack.h2h and pack.h2h.provenance.available:
        values["h2h_matches"] = list(pack.h2h.matches)
        values["h2h_summary_counts"] = dict(pack.h2h.summary or {})

    return values


def verify_shadow_narrative(draft: str, pack: EvidencePack, spec) -> tuple[bool, dict]:
    """Verify a shadow narrative against the evidence pack and spec boundaries."""
    from narrative_spec import TONE_BANDS

    try:
        import sys as _sys
        if "/home/paulsportsza" not in _sys.path:
            _sys.path.insert(0, "/home/paulsportsza")
        from scrapers.sport_terms import SPORT_BANNED_TERMS
    except Exception:
        SPORT_BANNED_TERMS = {}

    try:
        import bot as bot_module
        global_banned = list(getattr(bot_module, "BANNED_NARRATIVE_PHRASES", []))
        sanitizer = getattr(bot_module, "sanitize_ai_response", None)
    except Exception:
        global_banned = []
        sanitizer = None

    refs = _resolve_reference_values(pack, spec)
    sanitized = sanitizer(draft or "") if callable(sanitizer) else (draft or "").strip()
    lower = sanitized.lower()
    tone_band = TONE_BANDS.get(spec.tone_band, {"banned": []})
    verified_coaches = _build_verified_coaches(pack, spec)
    verified_injured = _build_verified_injured(pack, spec)
    verified_injury_surnames = _build_unique_injury_surnames(pack, spec)
    verified_injury_single_tokens = _build_unique_injury_single_tokens(pack, spec)
    team_aliases = _build_team_reference_aliases(pack, spec)
    injury_team_exclusions = _build_injury_team_exclusions(team_aliases)
    verified_names = _build_verified_names(pack, spec, verified_coaches, verified_injured, team_aliases)
    accepted_bookmaker_pairs = _build_accepted_bookmaker_pairs(pack, spec)
    accepted_sharp_prices = _build_accepted_sharp_prices(pack)
    accepted_percentages = _build_accepted_percentage_values(pack, refs)

    hard_checks: dict[str, dict[str, Any]] = {}
    soft_checks: dict[str, dict[str, Any]] = {}
    rejection_reasons: list[str] = []

    def _record_hard(name: str, passed: bool, detail: str) -> None:
        hard_checks[name] = {"passed": passed, "detail": detail}
        if not passed:
            rejection_reasons.append(f"{name}: {detail}")

    def _record_soft(name: str, flagged: bool, detail: str, category: str = "", amount: int = 0) -> None:
        soft_checks[name] = {
            "flagged": flagged,
            "detail": detail,
            "deduction_category": category if flagged else "",
            "deduction_amount": amount if flagged else 0,
        }

    section_order = [
        ("📋", ("the setup", "setup")),
        ("🎯", ("the edge", "edge")),
        ("⚠️", ("the risk", "risk")),
        ("🏆", ("verdict", "the verdict")),
    ]
    positions = []
    section_pass = True
    for emoji, variants in section_order:
        pos = sanitized.find(emoji)
        positions.append(pos)
        if pos == -1:
            section_pass = False
            continue
        header_window = sanitized[pos:pos + 48].lower()
        if not any(variant in header_window for variant in variants):
            section_pass = False
    _record_hard(
        "team_names_present",
        _contains_alias_reference(lower, team_aliases["home"]) and _contains_alias_reference(lower, team_aliases["away"]),
        f"Accepted home refs: {sorted(team_aliases['home'])}; away refs: {sorted(team_aliases['away'])}",
    )
    _record_hard(
        "section_structure",
        section_pass and positions == sorted(positions),
        "All 4 section emojis must exist in order after sanitization.",
    )
    bookmaker_pass, bookmaker_detail = _bookmaker_odds_match(sanitized, accepted_bookmaker_pairs)
    _record_hard(
        "bookmaker_odds_preserved",
        bookmaker_pass,
        bookmaker_detail + f" Accepted pairs: {sorted(accepted_bookmaker_pairs)}",
    )
    banned_hits = [
        phrase for phrase in list(tone_band["banned"]) + global_banned
        if phrase and _contains_banned_phrase(lower, phrase) and not _is_banned_phrase_false_positive(lower, phrase)
    ]
    _record_hard(
        "banned_phrases_absent",
        not banned_hits,
        "Banned hits: " + (", ".join(banned_hits[:8]) if banned_hits else "none"),
    )
    verdict_phrases = _STRONG_POSTURE_PHRASES if spec.verdict_action == "speculative punt" else []
    _record_hard(
        "verdict_cap_respected",
        not any(phrase in lower for phrase in verdict_phrases),
        "Speculative verdict cannot use strong-conviction language.",
    )

    try:
        h2h_claim = bool(getattr(bot_module, "_contains_h2h_claim")(sanitized)) if "bot_module" in locals() and hasattr(bot_module, "_contains_h2h_claim") else any(token in lower for token in ["head to head", "h2h", "meetings:"])
    except Exception:
        h2h_claim = any(token in lower for token in ["head to head", "h2h", "meetings:"])
    h2h_absence = _is_h2h_absence_statement(sanitized)
    h2h_pass = not h2h_claim
    h2h_detail = "No H2H claim detected."
    if h2h_absence and not (pack.h2h and pack.h2h.provenance.available and pack.h2h.matches):
        h2h_pass = True
        h2h_detail = "Explicit H2H absence statement with no verified H2H data."
    elif h2h_claim:
        h2h_pass, h2h_detail = _trace_h2h_claims(sanitized, pack)
    _record_hard(
        "h2h_claims_traceable",
        h2h_pass,
        h2h_detail,
    )

    form_strings = _extract_form_strings(sanitized)
    allowed_forms = {refs["home_form"], refs["away_form"]} - {""}
    _record_hard(
        "form_strings_traceable",
        all(form in allowed_forms for form in form_strings),
        f"Allowed form strings: {sorted(allowed_forms)}; found {form_strings}",
    )

    position_claims = {int(num) for num in re.findall(r"sit\s+(\d+)(?:st|nd|rd|th)", lower)}
    allowed_positions = {value for value in [refs["home_position"], refs["away_position"]] if isinstance(value, int)}
    _record_hard(
        "standings_positions_traceable",
        not position_claims or position_claims.issubset(allowed_positions),
        f"Allowed positions: {sorted(allowed_positions)}; found {sorted(position_claims)}",
    )

    point_claims = {int(num) for num in re.findall(r"on\s+(\d+)\s+points?", lower)}
    allowed_points = {value for value in [refs["home_points"], refs["away_points"]] if isinstance(value, int)}
    _record_hard(
        "points_traceable",
        not point_claims or point_claims.issubset(allowed_points),
        f"Allowed points: {sorted(allowed_points)}; found {sorted(point_claims)}",
    )

    coach_mentions = _extract_named_references(
        sanitized,
        [
            r"(?:coach|manager|boss)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
            r"under\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
        ],
    )
    unknown_coach_reference = [
        name for name in coach_mentions
        if not _match_verified_name(name, verified_coaches)
    ]
    _record_hard(
        "coach_names_match",
        not unknown_coach_reference,
        f"Verified coaches: {sorted(verified_coaches)}; cited {coach_mentions or ['none']}",
    )

    risk_section = _extract_section(sanitized, "⚠️", ["🏆"])
    injury_mentions = _extract_named_references(
        sanitized,
        [
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:is|are)\s+(?:a\s+)?(?:doubt|doubtful|out|missing|suspended|injured|questionable|knock)",
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:is|are)\s+carrying\s+a\s+knock",
            r"(?:without|missing|lose|lost)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
        ],
    )
    injury_words_present = any(word in lower for word in ["injur", "doubt", "doubtful", "suspended", "missing", "knock"])
    invalid_injuries = [
        name
        for name in injury_mentions
        if _normalise_name_phrase(name) not in injury_team_exclusions
        if not _match_verified_name(
            name,
            verified_injured,
            allow_single_token=True,
            unique_surnames=verified_injury_surnames,
            unique_single_tokens=verified_injury_single_tokens,
        )
    ]
    _record_hard(
        "injury_names_match",
        (not injury_words_present) or not invalid_injuries,
        (
            f"Verified injuries: {sorted(verified_injured)}; "
            f"unique surnames: {sorted(verified_injury_surnames)}; "
            f"unique single tokens: {sorted(verified_injury_single_tokens)}; "
            f"team exclusions: {sorted(injury_team_exclusions)}; "
            f"cited {injury_mentions or ['none']}"
        ),
    )

    sharp_refs = _extract_sharp_references(sanitized)
    if not (pack.sharp_lines and pack.sharp_lines.provenance.available):
        sharp_pass = not sharp_refs
    else:
        sharp_pass = True
        for bookmaker, cited_prices in sharp_refs:
            if not cited_prices:
                sharp_pass = False
                break
            known_prices = accepted_sharp_prices.get(bookmaker, set())
            if not known_prices:
                sharp_pass = False
                break
            if not all(any(abs(price - known) <= _SHARP_PRICE_TOLERANCE for known in known_prices) for price in cited_prices):
                sharp_pass = False
                break
    _record_hard(
        "sharp_prices_traceable",
        sharp_pass,
        f"Accepted sharp prices: {accepted_sharp_prices}; cited {sharp_refs or ['none']}",
    )

    proper_nouns = _extract_candidate_proper_nouns(sanitized)
    unexpected_nouns = []
    for phrase in sorted(proper_nouns):
        if _normalise_name_phrase(phrase) in _KNOWN_VERIFIED_VENUE_PHRASES:
            continue
        # R12-BUILD-03 Fix 5: Skip derby/geographical names
        if _normalise_name_phrase(phrase) in _DERBY_WHITELIST:
            continue
        tokens = [
            _strip_possessive_suffix(token).strip()
            for token in re.split(r"[\s\-]+", phrase.lower())
            if len(_strip_possessive_suffix(token).strip()) >= 4
        ]
        if tokens and not any(token in verified_names for token in tokens):
            unexpected_nouns.append(phrase)
    _record_hard(
        "no_fabricated_names",
        not unexpected_nouns,
        "Unexpected proper nouns: " + (", ".join(unexpected_nouns[:8]) if unexpected_nouns else "none"),
    )

    ev_pct_failures = []
    for value, context in _extract_percentage_contexts(sanitized):
        settlement_context = _contains_settlement_percentage_context(context)
        direct_context = _contains_direct_percentage_context(context)
        settlement_ok = settlement_context and any(abs(value - allowed) <= 1.5 for allowed in accepted_percentages["settlement"])
        if settlement_ok:
            continue
        if direct_context:
            settlement_bridge_ok = settlement_context and any(
                abs(value - allowed) <= 1.5 for allowed in accepted_percentages["settlement"]
            )
            if settlement_bridge_ok:
                continue
            direct_ok = any(abs(value - allowed) <= 1.5 for allowed in accepted_percentages["direct"])
            market_ok = any(abs(value - allowed) <= 1.5 for allowed in accepted_percentages["market_implied"])
            sharp_ok = any(abs(value - allowed) <= 1.5 for allowed in accepted_percentages["sharp_implied"])
            if not (direct_ok or market_ok or sharp_ok):
                ev_pct_failures.append(value)
            continue
        if settlement_context:
            if not any(abs(value - allowed) <= 1.5 for allowed in accepted_percentages["settlement"]):
                ev_pct_failures.append(value)
            continue
    _record_hard(
        "ev_probability_values",
        not ev_pct_failures,
        (
            f"Accepted direct: {sorted(accepted_percentages['direct'])}; "
            f"market-implied: {sorted(accepted_percentages['market_implied'])}; "
            f"sharp-implied: {sorted(accepted_percentages['sharp_implied'])}; "
            f"settlement: {sorted(accepted_percentages['settlement'])}; flagged {ev_pct_failures}"
        ),
    )

    news_claim_present = _contains_explicit_news_claim(sanitized)
    news_pass = True
    if news_claim_present and not refs["news_available"]:
        news_pass = False
    _record_hard(
        "news_claims_traceable",
        news_pass,
        "Explicit report-style news references require evidence-pack headlines.",
    )

    strong_for_class = []
    if refs["evidence_class"] in ("speculative", "lean"):
        strong_for_class = _STRONG_POSTURE_PHRASES + _MODERATE_POSTURE_PHRASES
    elif refs["evidence_class"] == "supported":
        strong_for_class = ["one of the best plays", "rock solid", "guaranteed", "lock"]
    conviction_drift = [phrase for phrase in strong_for_class if phrase in lower]
    _record_soft(
        "conviction_drift",
        bool(conviction_drift),
        "Over-strong posture: " + (", ".join(conviction_drift[:6]) if conviction_drift else "none"),
        "quality",
        1,
    )

    overinterp = []
    thresholds = {
        "movement": refs["movement_score"] < 0.4 and any(p in lower for p in ["strong movement", "moving sharply", "steam"]),
        "tipster": refs["tipster_score"] < 0.4 and any(p in lower for p in ["tipster consensus", "consensus agrees", "tipsters confirm"]),
        "form_h2h": refs["form_h2h_score"] < 0.5 and any(p in lower for p in ["form fully supports", "history strongly backs"]),
        "lineup_injury": refs["lineup_injury_score"] < 0.3 and any(p in lower for p in ["injury picture strongly favours", "lineups fully support"]),
    }
    overinterp = [name for name, flagged in thresholds.items() if flagged]
    _record_soft(
        "signal_overinterpretation",
        bool(overinterp),
        "Flagged signals: " + (", ".join(overinterp) if overinterp else "none"),
        "accuracy",
        1,
    )

    unsupported_news = False
    if refs["news_available"]:
        headline_text = " ".join(refs["news_titles"]).lower()
        if news_claim_present:
            unsupported_news = not any(
                token in headline_text
                for token in ["injur", "suspend", "doubt", "manager", "coach", "report", "headline", "update"]
            )
    _record_soft(
        "unsupported_news_claims",
        unsupported_news,
        "Narrative news claims exceed available headline evidence." if unsupported_news else "none",
        "accuracy",
        2,
    )

    track_rate = 0.0
    if pack.settlement_stats and pack.settlement_stats.stats_7d:
        track_rate = float(pack.settlement_stats.stats_7d.get("hit_rate") or 0.0) * 100
    track_sell = any(p in lower for p in ["red-hot", "incredibly accurate", "can trust this blindly"]) and track_rate < 50.0
    _record_soft(
        "track_record_oversell",
        track_sell,
        f"7-day hit rate {track_rate:.1f}% does not justify aggressive self-belief copy." if track_sell else "none",
        "accuracy",
        1,
    )

    missing_ack = refs["richness_score"] == "low" and not any(phrase in lower for phrase in _LIMITED_ACKNOWLEDGEMENT_PHRASES)
    _record_soft(
        "missing_low_richness_acknowledgement",
        missing_ack,
        "Low-richness packs should acknowledge evidence limits." if missing_ack else "none",
        "quality",
        1,
    )

    sport_banned = SPORT_BANNED_TERMS.get(pack.sport, {}).get("banned", [])
    contamination = [term for term in sport_banned if term.lower() in lower]
    _record_soft(
        "sport_term_contamination",
        bool(contamination),
        "Wrong-sport terms: " + (", ".join(contamination[:8]) if contamination else "none"),
        "quality",
        1,
    )

    stale_silence = refs["stale_minutes"] > 360 and not any(term in lower for term in ["stale", "old price", "aged odds", "verify the line", "price is old"])
    _record_soft(
        "stale_price_silence",
        stale_silence,
        f"SA odds are {_fmt_float(refs['stale_minutes'], 1)} minutes old." if stale_silence else "none",
        "accuracy",
        1,
    )

    support_boundary = any(pattern in lower for pattern in _SUPPORT_LANGUAGE_PATTERNS) and getattr(spec, "support_level", 0) < 3
    _record_soft(
        "support_language_boundary",
        support_boundary,
        f"Support language exceeds support_level={getattr(spec, 'support_level', 0)}." if support_boundary else "none",
        "accuracy",
        1,
    )

    verdict_boundary = refs["evidence_class"] in ("speculative", "lean") and any(
        phrase in lower for phrase in ["worth backing", "solid play", "strong back", "premium value"]
    )
    _record_soft(
        "verdict_posture_boundary",
        verdict_boundary,
        f"Verdict posture overstates evidence_class={refs['evidence_class']}." if verdict_boundary else "none",
        "quality",
        1,
    )

    soft_deductions = {"quality": 0, "accuracy": 0, "value": 0}
    for result in soft_checks.values():
        if result["flagged"]:
            soft_deductions[result["deduction_category"]] += int(result["deduction_amount"])

    report = {
        "passed": not rejection_reasons,
        "sanitized_draft": sanitized,
        "hard_checks": hard_checks,
        "soft_checks": soft_checks,
        "soft_deductions": soft_deductions,
        "rejection_reasons": rejection_reasons,
        "safe_rejection": None if not rejection_reasons else "verified_draft must be NULL; keep raw_draft for review only",
    }
    return report["passed"], report
