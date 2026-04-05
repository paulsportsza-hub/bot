"""P1P3-BUILD — Structured Card Pipeline for MzansiEdge bot.

Public API
----------
    build_verified_data_block(match_key, conn=None) -> dict
    generate_card_analysis(match_key, verified_data) -> str
    build_card_data(match_key, conn=None) -> dict
    render_card_html(card_data) -> str

Constraints
-----------
- Haiku only: claude-haiku-4-5-20251001, temperature=0.3, max_tokens=200
- NO LLM general knowledge — prompt includes:
  "Use ONLY the data provided below. Do not add any information from your
   training data. If data is missing for a field, omit it."
- 1024 char hard cap on rendered card HTML (Telegram photo caption limit)
- Backwards compatible — narrative_cache.narrative_html untouched
- Missing fields are omitted, NEVER fabricated
- Sequential DB connections — combat_data.db, enrichment.db, tipster_predictions.db
  opened as separate read-only connections; never merged into odds.db
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from html import escape as h
from pathlib import Path

log = logging.getLogger(__name__)

# ── Model config ──────────────────────────────────────────────────────────────
_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_HAIKU_TEMP = 0.3
_HAIKU_MAX_TOKENS = 200

# ── Caption hard limit (Telegram photo captions) ─────────────────────────────
_CAPTION_MAX = 1024

# ── DB paths (resolved from config or ENV fallback) ──────────────────────────
_BOT_DIR = Path(__file__).parent
_SCRAPERS_DIR = Path(os.environ.get("SCRAPERS_ROOT", str(_BOT_DIR.parent / "scrapers")))
_ODDS_DB_PATH = str(_SCRAPERS_DIR / "odds.db")
_COMBAT_DB_PATH = str(_SCRAPERS_DIR / "combat_data.db")
_ENRICHMENT_DB_PATH = str(_SCRAPERS_DIR / "enrichment.db")
_TIPSTER_DB_PATH = str(_SCRAPERS_DIR / "tipsters" / "tipster_predictions.db")

# ── Prompt template (LOCKED — do not add general knowledge) ──────────────────
CARD_ANALYSIS_PROMPT = """\
You are a concise sports betting analyst. Write exactly 2-3 lines of analysis (≤280 characters total).

STRICT RULE: Use ONLY the data provided below. Do not add any information from your training data. \
If data is missing for a field, omit it. Never guess, infer, or hallucinate facts.

DATA:
{data_block}

Write 2-3 lines that explain the key betting angle based ONLY on the data above. \
No markdown, no bullet points, plain sentences only."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_match_key(match_key: str) -> tuple[str, str, str]:
    """Parse 'home_vs_away_YYYY-MM-DD' → (home_key, away_key, date_str).

    Returns ('', '', '') on failure — callers must handle gracefully.
    """
    m = re.match(r"^(.+)_vs_(.+)_(\d{4}-\d{2}-\d{2})$", match_key)
    if m:
        return m.group(1), m.group(2), m.group(3)
    # Fallback: try without date
    m2 = re.match(r"^(.+)_vs_(.+)$", match_key)
    if m2:
        return m2.group(1), m2.group(2), ""
    return "", "", ""


def _ro_conn(path: str) -> sqlite3.Connection | None:
    """Open a read-only SQLite connection. Returns None on failure."""
    if not Path(path).exists():
        return None
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True,
            timeout=3.0, check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as exc:
        log.debug("card_pipeline: cannot open %s: %s", path, exc)
        return None


def _team_display(key: str) -> str:
    """Convert snake_case team key to Title Case display name."""
    return " ".join(w.capitalize() for w in key.split("_"))


def _stale_marker(scraped_at: str | None) -> str:
    """Return ⏳ if odds are older than 24 hours, else ''."""
    if not scraped_at:
        return ""
    try:
        ts = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return "⏳" if age_h > 24 else ""
    except Exception:
        return ""


# ── AC-2: build_verified_data_block ──────────────────────────────────────────

def build_verified_data_block(match_key: str, conn: sqlite3.Connection | None = None) -> dict:
    """Assemble verified data from ALL DB sources for *match_key*.

    Parameters
    ----------
    match_key:
        Normalised match identifier: ``home_vs_away_YYYY-MM-DD``.
    conn:
        Optional open connection to odds.db.  If None, a fresh read-only
        connection is opened internally.

    Returns
    -------
    dict with keys:
        matchup, home_key, away_key, date_str,
        odds (dict[bookmaker → {home, draw, away, market_type}]),
        best_odds (dict: outcome, bookmaker, decimal, stale),
        lineups (list[dict]), injuries (list[str]),
        results (list[dict]), ratings (dict[team → rating]),
        fighters (dict[team_key → fighter_dict]),
        news (list[str — headline]),
        weather (dict), tipster (dict),
        data_sources_used (list[str])
    """
    home_key, away_key, date_str = _parse_match_key(match_key)
    result: dict = {
        "match_key": match_key,
        "matchup": "",
        "home_key": home_key,
        "away_key": away_key,
        "date_str": date_str,
        "odds": {},
        "best_odds": {},
        "lineups": [],
        "injuries": [],
        "results": [],
        "ratings": {},
        "fighters": {},
        "news": [],
        "weather": {},
        "tipster": {},
        "data_sources_used": [],
    }
    if not home_key or not away_key:
        return result

    home_display = _team_display(home_key)
    away_display = _team_display(away_key)
    result["matchup"] = f"{home_display} vs {away_display}"

    # ── odds.db data ─────────────────────────────────────────────────────────
    _close_conn = False
    if conn is None:
        conn = _ro_conn(_ODDS_DB_PATH)
        _close_conn = True
    if conn is None:
        return result

    try:
        # odds_snapshots — best odds per bookmaker (most recent per bk)
        try:
            rows = conn.execute(
                """
                SELECT bookmaker, market_type, home_odds, draw_odds, away_odds,
                       scraped_at
                FROM odds_snapshots
                WHERE match_id = ?
                  AND scraped_at >= datetime('now', '-48 hours')
                ORDER BY scraped_at DESC
                """,
                (match_key,),
            ).fetchall()
            if rows:
                result["data_sources_used"].append("odds_snapshots")
                seen_bk = set()
                for row in rows:
                    bk = row["bookmaker"]
                    if bk in seen_bk:
                        continue
                    seen_bk.add(bk)
                    result["odds"][bk] = {
                        "home": float(row["home_odds"] or 0),
                        "draw": float(row["draw_odds"] or 0),
                        "away": float(row["away_odds"] or 0),
                        "market_type": row["market_type"] or "1x2",
                        "scraped_at": row["scraped_at"],
                    }
                # best odds: highest for back (home or away), best bookmaker
                if result["odds"]:
                    best_home = max(result["odds"].items(),
                                   key=lambda x: x[1]["home"])
                    best_away = max(result["odds"].items(),
                                   key=lambda x: x[1]["away"])
                    result["best_odds"] = {
                        "home": {
                            "bookmaker": best_home[0],
                            "odds": best_home[1]["home"],
                            "stale": _stale_marker(best_home[1]["scraped_at"]),
                        },
                        "away": {
                            "bookmaker": best_away[0],
                            "odds": best_away[1]["away"],
                            "stale": _stale_marker(best_away[1]["scraped_at"]),
                        },
                    }
                    best_draw = max(result["odds"].items(),
                                   key=lambda x: x[1]["draw"])
                    if best_draw[1]["draw"]:
                        result["best_odds"]["draw"] = {
                            "bookmaker": best_draw[0],
                            "odds": best_draw[1]["draw"],
                            "stale": _stale_marker(best_draw[1]["scraped_at"]),
                        }
        except Exception as exc:
            log.debug("card_pipeline: odds_snapshots query failed: %s", exc)

        # match_lineups — starting XI
        try:
            lineup_rows = conn.execute(
                """
                SELECT team, team_side, player_name, formation
                FROM match_lineups
                WHERE match_key = ?
                ORDER BY team_side, player_name
                """,
                (match_key,),
            ).fetchall()
            if lineup_rows:
                result["data_sources_used"].append("match_lineups")
                result["lineups"] = [
                    {
                        "team": row["team"],
                        "side": row["team_side"],
                        "player": row["player_name"],
                        "formation": row["formation"],
                    }
                    for row in lineup_rows[:22]  # cap at 22 players
                ]
        except Exception as exc:
            log.debug("card_pipeline: match_lineups query failed: %s", exc)

        # extracted_injuries — from news scraping
        try:
            inj_rows = conn.execute(
                """
                SELECT ei.player_name, ei.team_key, ei.status, ei.injury_type
                FROM extracted_injuries ei
                WHERE (ei.team_key LIKE ? OR ei.team_key LIKE ?)
                  AND ei.status NOT IN ('Missing Fixture', 'Unknown')
                ORDER BY ei.id DESC
                LIMIT 10
                """,
                (f"%{home_key}%", f"%{away_key}%"),
            ).fetchall()
            if inj_rows:
                result["data_sources_used"].append("extracted_injuries")
                for row in inj_rows:
                    result["injuries"].append(
                        f"{row['player_name']} ({row['team_key']}) — "
                        f"{row['status'] or row['injury_type'] or 'injured'}"
                    )
        except Exception as exc:
            log.debug("card_pipeline: extracted_injuries query failed: %s", exc)

        # match_results — recent form
        try:
            res_rows = conn.execute(
                """
                SELECT match_key, home_team, away_team, home_score, away_score, league
                FROM match_results
                WHERE (home_team LIKE ? OR away_team LIKE ?
                       OR home_team LIKE ? OR away_team LIKE ?)
                ORDER BY match_key DESC
                LIMIT 10
                """,
                (
                    f"%{home_key}%", f"%{home_key}%",
                    f"%{away_key}%", f"%{away_key}%",
                ),
            ).fetchall()
            if res_rows:
                result["data_sources_used"].append("match_results")
                for row in res_rows:
                    result["results"].append({
                        "match_key": row["match_key"],
                        "home": row["home_team"],
                        "away": row["away_team"],
                        "home_score": row["home_score"],
                        "away_score": row["away_score"],
                        "league": row["league"],
                    })
        except Exception as exc:
            log.debug("card_pipeline: match_results query failed: %s", exc)

        # team_ratings — Glicko-2 / Elo
        try:
            for team_key in (home_key, away_key):
                rating_row = conn.execute(
                    """
                    SELECT team_name, sport, mu, phi, matches_played
                    FROM team_ratings
                    WHERE team_name LIKE ?
                    ORDER BY matches_played DESC
                    LIMIT 1
                    """,
                    (f"%{team_key.replace('_', '%')}%",),
                ).fetchone()
                if rating_row:
                    result["ratings"][team_key] = {
                        "mu": float(rating_row["mu"] or 0),
                        "phi": float(rating_row["phi"] or 0),
                        "played": int(rating_row["matches_played"] or 0),
                        "sport": rating_row["sport"],
                    }
                    if "team_ratings" not in result["data_sources_used"]:
                        result["data_sources_used"].append("team_ratings")
        except Exception as exc:
            log.debug("card_pipeline: team_ratings query failed: %s", exc)

        # news_articles in odds.db (sport-tagged)
        try:
            news_rows = conn.execute(
                """
                SELECT title FROM news_articles
                WHERE (title LIKE ? OR title LIKE ?)
                ORDER BY published_at DESC
                LIMIT 3
                """,
                (f"%{home_display}%", f"%{away_display}%"),
            ).fetchall()
            if news_rows:
                result["data_sources_used"].append("news_articles_odds")
                for row in news_rows:
                    if row["title"]:
                        result["news"].append(row["title"])
        except Exception as exc:
            log.debug("card_pipeline: news_articles (odds.db) query failed: %s", exc)

    finally:
        if _close_conn and conn:
            try:
                conn.close()
            except Exception:
                pass

    # ── combat_data.db — AC-9 ─────────────────────────────────────────────────
    try:
        combat_conn = _ro_conn(_COMBAT_DB_PATH)
        if combat_conn:
            try:
                for team_key, display in [(home_key, home_display), (away_key, away_display)]:
                    fighter_row = combat_conn.execute(
                        """
                        SELECT name, sport, record, wins, losses, draws,
                               finish_rate, weight_class, reach_cm
                        FROM fighters
                        WHERE name LIKE ?
                        ORDER BY wins DESC
                        LIMIT 1
                        """,
                        (f"%{display}%",),
                    ).fetchone()
                    if fighter_row:
                        result["fighters"][team_key] = {
                            "name": fighter_row["name"],
                            "sport": fighter_row["sport"],
                            "record": fighter_row["record"],
                            "wins": fighter_row["wins"],
                            "losses": fighter_row["losses"],
                            "finish_rate": fighter_row["finish_rate"],
                            "weight_class": fighter_row["weight_class"],
                        }
                        if "combat_data.db" not in result["data_sources_used"]:
                            result["data_sources_used"].append("combat_data.db")
                        # Fight history for this fighter
                        hist_rows = combat_conn.execute(
                            """
                            SELECT opponent, result, method, round, event
                            FROM fight_history
                            WHERE fighter_id = (
                                SELECT id FROM fighters WHERE name LIKE ? LIMIT 1
                            )
                            ORDER BY date DESC
                            LIMIT 5
                            """,
                            (f"%{display}%",),
                        ).fetchall()
                        if hist_rows:
                            result["fighters"][team_key]["history"] = [
                                {
                                    "opponent": r["opponent"],
                                    "result": r["result"],
                                    "method": r["method"],
                                    "round": r["round"],
                                }
                                for r in hist_rows
                            ]
            finally:
                combat_conn.close()
    except Exception as exc:
        log.debug("card_pipeline: combat_data.db query failed: %s", exc)

    # ── enrichment.db — AC-10 ─────────────────────────────────────────────────
    try:
        enrich_conn = _ro_conn(_ENRICHMENT_DB_PATH)
        if enrich_conn:
            try:
                # News articles
                try:
                    enrich_news = enrich_conn.execute(
                        """
                        SELECT title FROM news_articles
                        WHERE (title LIKE ? OR title LIKE ?)
                        ORDER BY published_at DESC
                        LIMIT 3
                        """,
                        (f"%{home_display}%", f"%{away_display}%"),
                    ).fetchall()
                    for row in enrich_news:
                        if row["title"] and row["title"] not in result["news"]:
                            result["news"].append(row["title"])
                    if enrich_news:
                        if "enrichment.db:news" not in result["data_sources_used"]:
                            result["data_sources_used"].append("enrichment.db:news")
                except Exception as exc:
                    log.debug("card_pipeline: enrichment news query failed: %s", exc)

                # Weather — use date from match_key if available
                try:
                    weather_date = date_str if date_str else datetime.now().strftime("%Y-%m-%d")
                    weather_row = enrich_conn.execute(
                        """
                        SELECT venue_city, forecast_date, temp_c, wind_kmh,
                               precip_pct, condition
                        FROM weather_forecasts
                        WHERE forecast_date = ?
                        ORDER BY forecast_hour
                        LIMIT 1
                        """,
                        (weather_date,),
                    ).fetchone()
                    if weather_row and weather_row["temp_c"] is not None:
                        result["weather"] = {
                            "city": weather_row["venue_city"],
                            "temp_c": weather_row["temp_c"],
                            "wind_kmh": weather_row["wind_kmh"],
                            "precip_pct": weather_row["precip_pct"],
                            "condition": weather_row["condition"],
                        }
                        result["data_sources_used"].append("enrichment.db:weather")
                except Exception as exc:
                    log.debug("card_pipeline: enrichment weather query failed: %s", exc)
            finally:
                enrich_conn.close()
    except Exception as exc:
        log.debug("card_pipeline: enrichment.db connection failed: %s", exc)

    # ── tipster_predictions.db — AC-11 ────────────────────────────────────────
    try:
        tipster_conn = _ro_conn(_TIPSTER_DB_PATH)
        if tipster_conn:
            try:
                tip_rows = tipster_conn.execute(
                    """
                    SELECT source, predicted_winner, home_win_pct, draw_pct,
                           away_win_pct, confidence, pick_summary
                    FROM predictions
                    WHERE (home_team LIKE ? AND away_team LIKE ?)
                       OR (home_team LIKE ? AND away_team LIKE ?)
                    ORDER BY scraped_at DESC
                    LIMIT 6
                    """,
                    (
                        f"%{home_display}%", f"%{away_display}%",
                        f"%{home_key.replace('_', '%')}%",
                        f"%{away_key.replace('_', '%')}%",
                    ),
                ).fetchall()
                if tip_rows:
                    result["data_sources_used"].append("tipster_predictions.db")
                    home_pcts, away_pcts, draw_pcts = [], [], []
                    winners: list[str] = []
                    for row in tip_rows:
                        if row["home_win_pct"]:
                            home_pcts.append(float(row["home_win_pct"]))
                        if row["away_win_pct"]:
                            away_pcts.append(float(row["away_win_pct"]))
                        if row["draw_pct"]:
                            draw_pcts.append(float(row["draw_pct"]))
                        if row["predicted_winner"]:
                            winners.append(row["predicted_winner"])
                    result["tipster"] = {
                        "sources": len(tip_rows),
                        "home_consensus_pct": round(sum(home_pcts) / len(home_pcts), 1) if home_pcts else None,
                        "away_consensus_pct": round(sum(away_pcts) / len(away_pcts), 1) if away_pcts else None,
                        "draw_consensus_pct": round(sum(draw_pcts) / len(draw_pcts), 1) if draw_pcts else None,
                        "most_tipped": max(set(winners), key=winners.count) if winners else None,
                    }
            finally:
                tipster_conn.close()
    except Exception as exc:
        log.debug("card_pipeline: tipster_predictions.db query failed: %s", exc)

    return result


# ── AC-3: generate_card_analysis ─────────────────────────────────────────────

def generate_card_analysis(match_key: str, verified_data: dict) -> str:
    """Call Haiku to produce 2-3 line analysis from verified data only.

    Parameters
    ----------
    match_key:
        Identifier for logging.
    verified_data:
        Output of :func:`build_verified_data_block`.

    Returns
    -------
    str
        2-3 lines of analysis, ≤280 characters.  Empty string on any failure.
        NEVER blocks rendering — callers must handle empty string gracefully.
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception as exc:
        log.debug("card_pipeline: anthropic import failed: %s", exc)
        return ""

    # Build compact data block for the prompt
    lines: list[str] = []
    matchup = verified_data.get("matchup", "")
    if matchup:
        lines.append(f"MATCHUP: {matchup}")

    # Best odds
    best = verified_data.get("best_odds", {})
    if best.get("home", {}).get("odds"):
        h_o = best["home"]
        lines.append(f"HOME WIN best odds: {h_o['odds']:.2f} ({h_o['bookmaker']})")
    if best.get("away", {}).get("odds"):
        a_o = best["away"]
        lines.append(f"AWAY WIN best odds: {a_o['odds']:.2f} ({a_o['bookmaker']})")
    if best.get("draw", {}).get("odds"):
        d_o = best["draw"]
        lines.append(f"DRAW best odds: {d_o['odds']:.2f} ({d_o['bookmaker']})")

    # Ratings
    for side, key in [("HOME", verified_data.get("home_key", "")),
                      ("AWAY", verified_data.get("away_key", ""))]:
        rat = verified_data.get("ratings", {}).get(key)
        if rat and rat.get("mu"):
            lines.append(
                f"{side} rating: {rat['mu']:.0f} "
                f"(played {rat.get('played', '?')} matches)"
            )

    # Tipster consensus
    tip = verified_data.get("tipster", {})
    if tip.get("sources"):
        home_pct = tip.get("home_consensus_pct")
        away_pct = tip.get("away_consensus_pct")
        if home_pct is not None and away_pct is not None:
            lines.append(
                f"TIPSTER CONSENSUS ({tip['sources']} sources): "
                f"home {home_pct}%, away {away_pct}%"
            )

    # Fighter records (MMA/Boxing)
    fighters = verified_data.get("fighters", {})
    for side_key, side_label in [
        (verified_data.get("home_key", ""), "FIGHTER A"),
        (verified_data.get("away_key", ""), "FIGHTER B"),
    ]:
        f = fighters.get(side_key)
        if f:
            lines.append(
                f"{side_label} {f.get('name', '')}: "
                f"{f.get('record', '?')} record, "
                f"{f.get('finish_rate', '?')}% finish rate"
            )

    # Injuries
    injuries = verified_data.get("injuries", [])
    if injuries:
        lines.append(f"INJURY FLAGS: {'; '.join(injuries[:3])}")

    # If no data at all, return "Limited data available"
    if not lines:
        return "Limited data available for this fixture."

    data_block = "\n".join(lines)
    prompt = CARD_ANALYSIS_PROMPT.format(data_block=data_block)

    try:
        response = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_HAIKU_MAX_TOKENS,
            temperature=_HAIKU_TEMP,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in response.content:
            if hasattr(block, "text") and block.text:
                text += block.text
        text = text.strip()
        # Hard cap at 280 chars
        if len(text) > 280:
            # Truncate at last sentence boundary within 280
            text = text[:277] + "..."
        return text
    except Exception as exc:
        log.warning("card_pipeline: Haiku call failed for %s: %s", match_key, exc)
        return ""  # Graceful fallback — callers serve card without analysis


# ── AC-4: build_card_data ─────────────────────────────────────────────────────

def build_card_data(
    match_key: str,
    conn: sqlite3.Connection | None = None,
    *,
    tip: dict | None = None,
    include_analysis: bool = True,
) -> dict:
    """Assemble full structured card dict.

    Parameters
    ----------
    match_key:
        Normalised match identifier.
    conn:
        Optional open connection to odds.db.
    tip:
        Optional pre-loaded tip dict (from edge_results or Hot Tips).
        When provided, overlay odds, tier, EV, bookmaker from this dict.
    include_analysis:
        If True (default), calls generate_card_analysis(). Set False for
        pregen pipelines that generate analysis separately.

    Returns
    -------
    dict with keys:
        matchup, odds, bookmaker, confidence, ev, kickoff, venue,
        broadcast, sport, tier, analysis_text, data_sources_used
    """
    verified = build_verified_data_block(match_key, conn=conn)
    home_display = _team_display(verified.get("home_key", ""))
    away_display = _team_display(verified.get("away_key", ""))

    # Determine best outcome/odds from verified data or tip overlay
    outcome = ""
    best_odds_val = 0.0
    best_bookmaker = ""
    ev = 0.0
    tier = "bronze"
    sport = ""
    confidence = 0.0

    if tip:
        outcome = tip.get("outcome", "")
        best_odds_val = float(tip.get("odds") or 0)
        best_bookmaker = tip.get("bookmaker", "")
        ev = float(tip.get("ev") or 0)
        tier = (tip.get("display_tier") or tip.get("edge_rating") or "bronze").lower()
        sport = tip.get("sport_key", "") or tip.get("sport", "")
        # Confidence from edge_score if available
        confidence = float(tip.get("edge_score") or tip.get("composite_score") or 0)
    else:
        # Derive from verified odds: pick best outcome by highest odds
        best_o = verified.get("best_odds", {})
        if best_o:
            _candidates = []
            for side_key in ("home", "draw", "away"):
                bo = best_o.get(side_key, {})
                if bo.get("odds"):
                    _candidates.append((side_key, bo["odds"], bo["bookmaker"]))
            if _candidates:
                _best = max(_candidates, key=lambda x: x[1])
                outcome = _best[0].title()  # e.g. "Home", "Draw", "Away"
                best_odds_val = _best[1]
                best_bookmaker = _best[2]

    # Kickoff from match_key date
    kickoff = ""
    date_str = verified.get("date_str", "")
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            today = datetime.now().date()
            diff = (dt.date() - today).days
            if diff == 0:
                kickoff = "Today"
            elif diff == 1:
                kickoff = "Tomorrow"
            elif diff < 0:
                kickoff = dt.strftime("%-d %b")  # past
            else:
                kickoff = dt.strftime("%a %-d %b")
        except ValueError:
            kickoff = date_str

    # Override kickoff from tip if it has _bc_kickoff
    if tip and tip.get("_bc_kickoff"):
        kickoff = tip["_bc_kickoff"]

    # Broadcast from tip
    broadcast = ""
    if tip and tip.get("_bc_broadcast"):
        broadcast = tip["_bc_broadcast"]

    # Analysis
    analysis_text = ""
    if include_analysis and (verified["data_sources_used"] or tip):
        analysis_text = generate_card_analysis(match_key, verified)

    card: dict = {
        "matchup": verified["matchup"] or f"{home_display} vs {away_display}",
        "home_team": home_display,
        "away_team": away_display,
        "outcome": outcome,
        "odds": best_odds_val,
        "bookmaker": best_bookmaker,
        "confidence": confidence,
        "ev": ev,
        "kickoff": kickoff,
        "venue": "",  # venue not yet in DB schema
        "broadcast": broadcast,
        "sport": sport,
        "tier": tier,
        "analysis_text": analysis_text,
        "data_sources_used": verified["data_sources_used"],
        # Pass-through for downstream renderers
        "_verified": verified,
    }
    return card


# ── AC-5: render_card_html ────────────────────────────────────────────────────

def render_card_html(card_data: dict) -> str:
    """Render structured card dict to Telegram-compatible HTML.

    Format:
        <b>Home vs Away</b>                ← bold matchup
        <code>odds @ Bookmaker</code>      ← monospace odds+bookmaker
        📊 Confidence · +EV% EV
        📅 Kickoff · 📺 Broadcast
        <blockquote expandable>analysis</blockquote>

    Hard limit: 1024 chars (Telegram photo caption limit).
    Priority truncation: analysis first, then venue/broadcast.
    Matchup + odds + confidence are NEVER truncated.
    """
    matchup = h(card_data.get("matchup", "Match"))
    outcome = h(card_data.get("outcome", ""))
    odds_val = float(card_data.get("odds") or 0)
    bookmaker = h(card_data.get("bookmaker", ""))
    confidence = float(card_data.get("confidence") or 0)
    ev = float(card_data.get("ev") or 0)
    kickoff = h(card_data.get("kickoff", ""))
    broadcast = card_data.get("broadcast", "")
    analysis = card_data.get("analysis_text", "")
    tier = (card_data.get("tier") or "bronze").lower()

    from message_types import EDGE_EMOJIS, EDGE_LABELS
    tier_emoji = EDGE_EMOJIS.get(tier, "🥉")
    tier_label = EDGE_LABELS.get(tier, "BRONZE EDGE")

    lines: list[str] = []

    # Line 1: tier badge + matchup
    lines.append(f"{tier_emoji} <b>{matchup}</b>")
    lines.append(f"<i>{tier_label}</i>")

    # Line 2: odds + bookmaker (monospace)
    if odds_val > 0:
        if outcome and bookmaker:
            lines.append(
                f"💰 {h(outcome)} @ <code>{odds_val:.2f}</code> ({bookmaker})"
            )
        elif odds_val and bookmaker:
            lines.append(f"💰 <code>{odds_val:.2f}</code> ({bookmaker})")
        elif odds_val:
            lines.append(f"💰 <code>{odds_val:.2f}</code>")

    # Line 3: confidence + EV
    detail_parts: list[str] = []
    if confidence > 0:
        detail_parts.append(f"📊 <code>{confidence:.0f}%</code> confidence")
    if ev > 0:
        detail_parts.append(f"+<code>{ev:.1f}%</code> EV")
    if detail_parts:
        lines.append(" · ".join(detail_parts))

    # Line 4: kickoff + broadcast (non-critical, truncated first)
    meta_parts: list[str] = []
    if kickoff:
        meta_parts.append(f"📅 {kickoff}")
    if broadcast:
        meta_parts.append(broadcast)
    meta_line = "  ".join(meta_parts) if meta_parts else ""

    # Assemble without analysis to measure base length
    base = "\n".join(lines)
    if meta_line:
        base_with_meta = f"{base}\n{meta_line}"
    else:
        base_with_meta = base

    # Add analysis in expandable blockquote if it fits
    if analysis:
        analysis_safe = h(analysis)
        candidate = f"{base_with_meta}\n<blockquote expandable>{analysis_safe}</blockquote>"
        if len(candidate) <= _CAPTION_MAX:
            return candidate
        # Try without meta
        candidate_no_meta = f"{base}\n<blockquote expandable>{analysis_safe}</blockquote>"
        if len(candidate_no_meta) <= _CAPTION_MAX:
            return candidate_no_meta
        # Truncate analysis to fit
        _overhead = len(f"{base}\n<blockquote expandable></blockquote>")
        _budget = _CAPTION_MAX - _overhead - 3
        if _budget > 20:
            truncated = h(analysis[:_budget]) + "..."
            return f"{base}\n<blockquote expandable>{truncated}</blockquote>"
        # Analysis doesn't fit at all — omit it
        if len(base_with_meta) <= _CAPTION_MAX:
            return base_with_meta
        return base[:_CAPTION_MAX]

    if len(base_with_meta) <= _CAPTION_MAX:
        return base_with_meta
    return base[:_CAPTION_MAX]
