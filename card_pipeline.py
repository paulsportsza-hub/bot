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

# ── Haiku circuit breaker (BUILD-SPEED) ───────────────────────────────────────
_haiku_failures: int = 0
_haiku_circuit_open_until: float = 0.0


def _call_haiku_with_breaker(client, prompt: str) -> str | None:
    """Call Haiku with a circuit breaker: 2 consecutive failures → 5-min cooldown."""
    global _haiku_failures, _haiku_circuit_open_until
    if time.time() < _haiku_circuit_open_until:
        log.debug("card_pipeline: Haiku circuit open — skipping call")
        return None
    try:
        response = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_HAIKU_MAX_TOKENS,
            temperature=_HAIKU_TEMP,
            messages=[{"role": "user", "content": prompt}],
        )
        _haiku_failures = 0
        text = ""
        for block in response.content:
            if hasattr(block, "text") and block.text:
                text += block.text
        return text.strip()
    except Exception as exc:
        _haiku_failures += 1
        if _haiku_failures >= 2:
            _haiku_circuit_open_until = time.time() + 300  # 5-min cooldown
            log.warning(
                "card_pipeline: Haiku circuit OPENED after %d failures — cooldown 5min",
                _haiku_failures,
            )
        else:
            log.warning("card_pipeline: Haiku call failed (%d): %s", _haiku_failures, exc)
        return None

# ── Caption hard limit (Telegram photo captions) ─────────────────────────────
_CAPTION_MAX = 1024

# ── Injury staleness threshold ────────────────────────────────────────────────
INJURY_STALE_HOURS = 72

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
    """Open a read-only SQLite connection via approved factory. Returns None on failure."""
    if not Path(path).exists():
        return None
    try:
        from db_connection import get_connection
        return get_connection(db_path=path, readonly=True, timeout_ms=5000)
    except Exception as exc:
        log.warning("card_pipeline: cannot open %s: %s", path, exc)
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


# ── IMG-W2: Data adapter helpers ──────────────────────────────────────────────

def _compute_team_form(results: list[dict], team_key: str, last_n: int = 5) -> list[str]:
    """Return per-team array of 'W'/'D'/'L' for last *last_n* matches.

    CANONICAL HELPER (INV-04 AC-3): This is the single authoritative function
    for computing recent results per team. Do not duplicate this logic elsewhere.

    Parses the ``results`` list produced by :func:`build_verified_data_block`.
    Only matches where *team_key* appears (case-insensitive substring) as home
    or away are counted.  Matches with missing scores are skipped.
    """
    form: list[str] = []
    for r in results:
        if len(form) >= last_n:
            break
        home = r.get("home") or ""
        away = r.get("away") or ""
        hs = r.get("home_score")
        as_ = r.get("away_score")
        if hs is None or as_ is None:
            continue
        team_lower = team_key.lower()
        team_is_home = team_lower in home.lower()
        team_is_away = team_lower in away.lower()
        if not team_is_home and not team_is_away:
            continue
        try:
            hs_i, as_i = int(hs), int(as_)
        except (TypeError, ValueError):
            continue
        if hs_i == as_i:
            form.append("D")
        elif team_is_home:
            form.append("W" if hs_i > as_i else "L")
        else:
            form.append("W" if as_i > hs_i else "L")
    return form


def _h2h_key_variants(key: str) -> list[str]:
    """Return name variants to try for H2H matching, handling afc_/fc_ prefixes.

    e.g. 'bournemouth' → ['bournemouth', 'afc_bournemouth', 'fc_bournemouth', 'bournemouth_fc']
         'afc_bournemouth' → ['afc_bournemouth', 'bournemouth']
    """
    k = key.lower()
    variants = [k]
    if k.startswith("afc_"):
        variants.append(k[4:])
    elif k.startswith("fc_"):
        variants.append(k[3:])
    elif k.endswith("_fc"):
        variants.append(k[:-3])
    else:
        variants.append(f"afc_{k}")
        variants.append(f"fc_{k}")
        variants.append(f"{k}_fc")
    return variants


def _compute_h2h(results: list[dict], home_key: str, away_key: str) -> dict:
    """Return head-to-head record as ``{played, hw, d, aw}``.

    Invariant: ``hw + d + aw == played``.
    ``hw`` = wins for the *home_key* side.

    Uses prefix-alias expansion (afc_/fc_) so that 'bournemouth' matches
    stored keys like 'afc_bournemouth' in match_results.
    """
    played = hw = d = aw = 0
    hk_variants = _h2h_key_variants(home_key)
    ak_variants = _h2h_key_variants(away_key)
    for r in results:
        home = (r.get("home") or "").lower()
        away = (r.get("away") or "").lower()
        hs = r.get("home_score")
        as_ = r.get("away_score")
        if hs is None or as_ is None:
            continue
        # Normal direction: home_key at home, away_key away
        normal = any(v in home for v in hk_variants) and any(v in away for v in ak_variants)
        # Reversed: away_key at home, home_key away
        reversed_ = any(v in home for v in ak_variants) and any(v in away for v in hk_variants)
        if not normal and not reversed_:
            continue
        try:
            hs_i, as_i = int(hs), int(as_)
        except (TypeError, ValueError):
            continue
        played += 1
        if hs_i == as_i:
            d += 1
        elif normal:
            if hs_i > as_i:
                hw += 1
            else:
                aw += 1
        else:  # reversed
            if hs_i > as_i:
                aw += 1
            else:
                hw += 1
    return {"played": played, "hw": hw, "d": d, "aw": aw}


def _split_injuries(
    injuries: list[str], home_key: str, away_key: str
) -> tuple[list[str], list[str]]:
    """Split flat injuries list into per-team arrays of ``'Player (status)'`` strings.

    The raw format from :func:`build_verified_data_block` is::

        "Player Name (team_key) — status_or_type"

    This function reformats each entry to ``'Player Name (status)'`` and
    assigns it to the correct team bucket.
    """
    home_injuries: list[str] = []
    away_injuries: list[str] = []
    hk = home_key.lower()
    ak = away_key.lower()
    for inj in injuries:
        inj_lower = inj.lower()
        is_home = hk in inj_lower
        is_away = ak in inj_lower
        if not is_home and not is_away:
            continue
        # Reformat: "Player (team) — status" → "Player (status)"
        parts = inj.split(" — ", 1)
        if len(parts) == 2:
            player_part = parts[0].split(" (")[0].strip()
            status = parts[1].strip()
            formatted = f"{player_part} ({status})"
        else:
            formatted = inj
        if is_home:
            home_injuries.append(formatted)
        else:
            away_injuries.append(formatted)
    return home_injuries, away_injuries


def _compute_signals(tip: dict | None, verified: dict) -> dict:
    """Return signals dict with 6 named booleans for the card renderer.

    Keys: ``price_edge``, ``form``, ``movement``, ``market``, ``tipster``,
    ``injury``.
    """
    ev = float((tip or {}).get("ev") or 0)
    tipster = verified.get("tipster") or {}
    return {
        "price_edge": ev > 0,
        "form": bool(verified.get("results")),
        "movement": bool(
            (tip or {}).get("movement")
            or (tip or {}).get("line_movement")
            or (tip or {}).get("movement_detected")
        ),
        "market": tipster.get("home_consensus_pct") is not None,
        "tipster": bool(tipster.get("sources")),
        "injury": bool(verified.get("injuries")),
    }


def _compute_pick_team(outcome: str, home_display: str, away_display: str) -> str:
    """Return clean team name string for the pick outcome.

    Maps ``'Home'`` → home_display, ``'Away'`` → away_display,
    ``'Draw'`` → ``'Draw'``.  Falls back to *outcome* unchanged.
    """
    oc = outcome.lower().strip()
    if oc in ("home", "1"):
        return home_display
    if oc in ("away", "2"):
        return away_display
    if oc in ("draw", "x", "tie"):
        return "Draw"
    return outcome


def _compute_no_edge_reason(ev: float, verified: dict, tip: dict | None) -> str:
    """Return deterministic template string for non-edge matches.

    Returns an empty string when a positive edge exists.
    """
    if tip and ev > 0:
        return ""
    if not verified.get("data_sources_used"):
        return "Insufficient data to calculate edge for this match."
    if not verified.get("odds"):
        return "No bookmaker odds available for this match."
    return "No positive expected value detected across available bookmakers."


def _compute_key_stats(
    verified: dict,
    home_key: str,
    away_key: str,
    home_form: list[str],
    away_form: list[str],
    h2h: dict,
) -> list[dict]:
    """Return exactly 4 stat box dicts for Match Detail cards.

    Each dict has at minimum ``'label'``, ``'home'``, ``'away'`` keys.
    H2H boxes also include a ``'draw'`` key.  Missing data boxes use ``'—'``.
    """
    stats: list[dict] = []

    # Box 1: Glicko-2 / Elo ratings
    ratings = verified.get("ratings") or {}
    home_rat = ratings.get(home_key) or {}
    away_rat = ratings.get(away_key) or {}
    if home_rat or away_rat:
        stats.append({
            "label": "Rating",
            "home": f"{home_rat.get('mu', 0):.0f}" if home_rat else "N/A",
            "away": f"{away_rat.get('mu', 0):.0f}" if away_rat else "N/A",
        })

    # Box 2: Recent form (last 5)
    if home_form or away_form:
        stats.append({
            "label": "Form (L5)",
            "home": "".join(home_form) if home_form else "N/A",
            "away": "".join(away_form) if away_form else "N/A",
        })

    # Box 3: Head-to-head record
    if h2h.get("played"):
        stats.append({
            "label": "H2H",
            "home": str(h2h["hw"]),
            "draw": str(h2h["d"]),
            "away": str(h2h["aw"]),
        })

    # Box 4: Tipster consensus
    tipster = verified.get("tipster") or {}
    if tipster.get("sources"):
        home_pct = tipster.get("home_consensus_pct")
        away_pct = tipster.get("away_consensus_pct")
        stats.append({
            "label": "Tipster",
            "home": f"{home_pct}%" if home_pct is not None else "N/A",
            "away": f"{away_pct}%" if away_pct is not None else "N/A",
        })

    # Pad to exactly 4 boxes
    while len(stats) < 4:
        stats.append({"label": "N/A", "home": "—", "away": "—"})

    return stats[:4]


def _compute_match_detail_stats(
    match_key: str,
    home_key: str,
    away_key: str,
    sport: str,
    league: str,
    verified_ctx: dict,
) -> list[dict]:
    """Compute 4 Key Stats tiles for My Matches match_detail card.

    BUILD-MY-MATCHES-02: Home Record / Away Record / Avg Score / Fair Value.
    Schema: [{label: str, value: str, context: str}] — match_detail.html expects this.
    Returns [] on failure or insufficient data so the section hides gracefully.
    """
    if not home_key or not away_key:
        return []

    conn = _ro_conn(_ODDS_DB_PATH)
    if conn is None:
        return []

    stats: list[dict] = []
    hk_variants = _h2h_key_variants(home_key)
    ak_variants = _h2h_key_variants(away_key)

    def _ph(n: int) -> str:
        return ",".join("?" * n)

    try:
        cur = conn.cursor()

        # Determine current season: most-matched season in last 400 days for this league.
        # A rolling window avoids picking sparse "2026-2026" labels over the true active
        # season (e.g. '2025-2026' with 281 EPL rows).
        season = ""
        if league:
            cur.execute(
                """SELECT season, COUNT(*) AS cnt FROM match_results
                   WHERE league = ? AND match_date >= DATE('now', '-400 days')
                   GROUP BY season ORDER BY cnt DESC LIMIT 1""",
                (league,),
            )
            row = cur.fetchone()
            if row:
                season = row[0]

        season_clause = "AND season = ?" if season else ""
        season_params: tuple = (season,) if season else ()

        # ── Home Record: W-D-L for home_key at home this season ─────────────
        cur.execute(
            f"""SELECT result, COUNT(*) FROM match_results
               WHERE home_team IN ({_ph(len(hk_variants))}) {season_clause}
               GROUP BY result""",
            (*hk_variants, *season_params),
        )
        hw = hd = hl = 0
        for result, cnt in cur.fetchall():
            if result == "home":
                hw = cnt
            elif result == "draw":
                hd = cnt
            elif result == "away":
                hl = cnt
        if hw or hd or hl:
            stats.append({
                "label": "Home Record",
                "value": f"{hw}-{hd}-{hl}",
                "context": "at home",
            })

        # ── Away Record: W-D-L for away_key on road this season ─────────────
        cur.execute(
            f"""SELECT result, COUNT(*) FROM match_results
               WHERE away_team IN ({_ph(len(ak_variants))}) {season_clause}
               GROUP BY result""",
            (*ak_variants, *season_params),
        )
        aw = ad = al = 0
        for result, cnt in cur.fetchall():
            if result == "away":
                aw = cnt
            elif result == "draw":
                ad = cnt
            elif result == "home":
                al = cnt
        if aw or ad or al:
            stats.append({
                "label": "Away Record",
                "value": f"{aw}-{ad}-{al}",
                "context": "on the road",
            })

        # ── Avg Score: average scoreline from last 5 H2H matches ─────────────
        cur.execute(
            f"""SELECT home_score, away_score FROM match_results
               WHERE (home_team IN ({_ph(len(hk_variants))}) AND away_team IN ({_ph(len(ak_variants))}))
                  OR (home_team IN ({_ph(len(ak_variants))}) AND away_team IN ({_ph(len(hk_variants))}))
               ORDER BY match_date DESC LIMIT 5""",
            (*hk_variants, *ak_variants, *ak_variants, *hk_variants),
        )
        h2h_scores: list[tuple[int, int]] = []
        for hs, as_ in cur.fetchall():
            try:
                h2h_scores.append((int(hs), int(as_)))
            except (TypeError, ValueError):
                pass
        if h2h_scores:
            avg_h = sum(s[0] for s in h2h_scores) / len(h2h_scores)
            avg_a = sum(s[1] for s in h2h_scores) / len(h2h_scores)
            stats.append({
                "label": "Avg Score",
                "value": f"{avg_h:.0f}-{avg_a:.0f}",
                "context": "last 5 H2H",
            })

        # ── Fair Value: home win probability ─────────────────────────────────
        # Use verified.prob when available; fallback to Glicko-2 from team_ratings
        fair_pct: int | None = None
        raw_prob = verified_ctx.get("prob")
        if raw_prob is not None:
            try:
                p = float(raw_prob)
                # Handle both fraction (0–1) and percentage (0–100) formats
                if 0 < p <= 1.0:
                    fair_pct = int(round(p * 100))
                elif 1 < p <= 100:
                    fair_pct = int(round(p))
            except (TypeError, ValueError):
                pass

        if fair_pct is None:
            # Derive from team_ratings.mu using Glicko-2 expected score formula
            mu_home = mu_away = None
            _sport = sport or "soccer"
            for tk in hk_variants:
                cur.execute(
                    "SELECT mu FROM team_ratings WHERE team_name = ? AND sport = ? LIMIT 1",
                    (tk, _sport),
                )
                row = cur.fetchone()
                if row:
                    mu_home = float(row[0])
                    break
            for tk in ak_variants:
                cur.execute(
                    "SELECT mu FROM team_ratings WHERE team_name = ? AND sport = ? LIMIT 1",
                    (tk, _sport),
                )
                row = cur.fetchone()
                if row:
                    mu_away = float(row[0])
                    break
            if mu_home is not None and mu_away is not None:
                p_home = 1.0 / (1.0 + 10.0 ** (-(mu_home - mu_away) / 400.0))
                fair_pct = int(round(p_home * 100))

        if fair_pct is not None:
            stats.append({
                "label": "Fair Value",
                "value": f"{fair_pct}%",
                "context": "home win prob",
            })

    except Exception as exc:
        log.warning("_compute_match_detail_stats: query failed: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return stats[:4]


def _compute_odds_structured(verified: dict) -> dict:
    """Return 3-way odds structured per outcome with best bookmaker.

    Keys: ``'home'``, ``'draw'``, ``'away'`` (only present when data exists).
    Each value: ``{bookmaker, odds, stale}``.
    """
    best_odds = verified.get("best_odds") or {}
    result: dict = {}
    for outcome in ("home", "draw", "away"):
        bo = best_odds.get(outcome) or {}
        if bo.get("odds"):
            result[outcome] = {
                "bookmaker": bo.get("bookmaker", ""),
                "odds": float(bo["odds"]),
                "stale": bo.get("stale", ""),
            }
    return result


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
    import time as _time
    _pipeline_start = _time.monotonic()
    _stages_completed: list[str] = []

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
        "h2h_results": [],
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
                  AND market_type = '1x2'
                ORDER BY scraped_at DESC
                """,
                (match_key,),
            ).fetchall()
            if rows:
                result["data_sources_used"].append("odds_snapshots")
                _stages_completed.append("odds")
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
            log.warning("card_pipeline: odds_snapshots query failed: %s", exc)

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
                _stages_completed.append("lineups")
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
            log.warning("card_pipeline: match_lineups query failed: %s", exc)

        # extracted_injuries — from news scraping
        try:
            inj_rows = conn.execute(
                """
                SELECT ei.player_name, ei.team_key, ei.status, ei.injury_type
                FROM extracted_injuries ei
                WHERE (ei.team_key LIKE ? OR ei.team_key LIKE ?)
                  AND ei.status NOT IN ('Missing Fixture', 'Unknown')
                  AND ei.extracted_at > datetime('now', '-72 hours')
                ORDER BY ei.id DESC
                LIMIT 10
                """,
                (f"%{home_key}%", f"%{away_key}%"),
            ).fetchall()
            if inj_rows:
                result["data_sources_used"].append("extracted_injuries")
                _stages_completed.append("injuries")
                for row in inj_rows:
                    result["injuries"].append(
                        f"{row['player_name']} ({row['team_key']}) — "
                        f"{row['status'] or row['injury_type'] or 'injured'}"
                    )
        except Exception as exc:
            log.warning("card_pipeline: extracted_injuries query failed: %s", exc)

        # match_results — recent form
        try:
            res_rows = conn.execute(
                """
                SELECT match_key, home_team, away_team, home_score, away_score, league
                FROM match_results
                WHERE (home_team LIKE ? OR away_team LIKE ?
                       OR home_team LIKE ? OR away_team LIKE ?)
                ORDER BY match_date DESC
                LIMIT 20
                """,
                (
                    f"%{home_key}%", f"%{home_key}%",
                    f"%{away_key}%", f"%{away_key}%",
                ),
            ).fetchall()
            if res_rows:
                result["data_sources_used"].append("match_results")
                _stages_completed.append("results")
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
            log.warning("card_pipeline: match_results query failed: %s", exc)

        # h2h_results — dedicated head-to-head query (AND, not OR — guarantees both teams appear)
        # Uses %key% patterns so 'bournemouth' matches stored 'afc_bournemouth'.
        try:
            _hk_pat = f"%{home_key}%"
            _ak_pat = f"%{away_key}%"
            h2h_rows = conn.execute(
                """
                SELECT match_key, home_team, away_team, home_score, away_score, league
                FROM match_results
                WHERE (home_team LIKE ? AND away_team LIKE ?)
                   OR (home_team LIKE ? AND away_team LIKE ?)
                ORDER BY match_date DESC
                LIMIT 10
                """,
                (_hk_pat, _ak_pat, _ak_pat, _hk_pat),
            ).fetchall()
            for row in h2h_rows:
                result["h2h_results"].append({
                    "match_key": row["match_key"],
                    "home": row["home_team"],
                    "away": row["away_team"],
                    "home_score": row["home_score"],
                    "away_score": row["away_score"],
                    "league": row["league"],
                })
        except Exception as exc:
            log.warning("card_pipeline: h2h_results query failed: %s", exc)

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
                        _stages_completed.append("ratings")
        except Exception as exc:
            log.warning("card_pipeline: team_ratings query failed: %s", exc)

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
            log.warning("card_pipeline: news_articles (odds.db) query failed: %s", exc)

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
                            _stages_completed.append("combat")
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
        log.warning("card_pipeline: combat_data.db query failed: %s", exc)

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
                            if "enrichment" not in _stages_completed:
                                _stages_completed.append("enrichment")
                except Exception as exc:
                    log.warning("card_pipeline: enrichment news query failed: %s", exc)

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
                    log.warning("card_pipeline: enrichment weather query failed: %s", exc)
            finally:
                enrich_conn.close()
    except Exception as exc:
        log.warning("card_pipeline: enrichment.db connection failed: %s", exc)

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
                    _stages_completed.append("tipster")
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
                        # FIX 4 (CARD-REBUILD-03A): raw rows for top_tipsters in _enrich_tip_for_card
                        "_rows": [
                            {
                                "source": str(r["source"] or ""),
                                "predicted_winner": str(r["predicted_winner"] or ""),
                                "home_win_pct": r["home_win_pct"],
                                "away_win_pct": r["away_win_pct"],
                                "draw_pct": r["draw_pct"],
                                "confidence": r["confidence"],
                                "pick_summary": str(r["pick_summary"] or ""),
                            }
                            for r in tip_rows
                        ],
                    }
            finally:
                tipster_conn.close()
    except Exception as exc:
        log.warning("card_pipeline: tipster_predictions.db query failed: %s", exc)

    # ── CARD-FIX-B Task 2: venue from sportmonks ──────────────────────────────
    if conn is not None:
        try:
            venue_row = conn.execute(
                """
                SELECT v.name, v.city
                FROM sportmonks_fixtures f
                JOIN sportmonks_venues v ON f.venue_id = v.venue_id
                WHERE f.home_team LIKE ? AND f.away_team LIKE ?
                ORDER BY f.match_date DESC
                LIMIT 1
                """,
                (f"%{home_display}%", f"%{away_display}%"),
            ).fetchone()
            if venue_row and venue_row["name"]:
                city = venue_row["city"] or ""
                result["venue"] = f"{venue_row['name']}, {city}" if city else venue_row["name"]
        except Exception as exc:
            log.debug("card_pipeline: venue query failed: %s", exc)

    _pipeline_ms = (_time.monotonic() - _pipeline_start) * 1000
    _total_stages = 9  # odds, lineups, injuries, results, ratings, combat, enrichment, tipster, Haiku
    log.info(
        "pipeline_complete match_key=%s stages=%d/%d completed=%s elapsed_ms=%.1f",
        match_key,
        len(_stages_completed),
        _total_stages,
        ",".join(_stages_completed) if _stages_completed else "none",
        _pipeline_ms,
    )
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

    text = _call_haiku_with_breaker(client, prompt)
    if not text:
        return ""  # Circuit open or API failure — callers serve card without analysis
    # Hard cap at 280 chars
    if len(text) > 280:
        text = text[:277] + "..."
    return text


# ── CARD-BUILD-01: Card Population Gate ──────────────────────────────────────

def verify_card_populates(tip: dict | None, match_key: str) -> tuple[bool, str]:
    """Pre-flight check: can this tip produce a valid card?

    Returns (True, "") if yes. Returns (False, reason) if no.
    Does NOT call build_verified_data_block() — cheap dict-only check.
    """
    if tip is None:
        return False, "tip_is_none"
    pick = tip.get("outcome") or tip.get("home_team", "")
    if not pick or not pick.strip():
        return False, "empty_pick"
    odds = float(tip.get("odds", 0) or tip.get("home_odds", 0) or 0)
    if odds < 1.01:
        return False, f"invalid_odds:{odds}"
    bookmaker = tip.get("bookmaker") or tip.get("bookie", "")
    if not bookmaker or not bookmaker.strip():
        return False, "empty_bookmaker"
    return True, ""


def _log_card_population_failure(match_key: str, reason: str, tip: dict | None) -> None:
    """Log a tip that failed the population gate. Never raises."""
    try:
        from db_connection import get_connection
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_population_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_key TEXT NOT NULL,
                reason TEXT NOT NULL,
                tip_snapshot_json TEXT,
                created_at DATETIME DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO card_population_failures (match_key, reason, tip_snapshot_json) VALUES (?,?,?)",
            (match_key, reason, json.dumps(tip) if tip else None),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # never block on logging


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
    home_key = verified.get("home_key", "")
    away_key = verified.get("away_key", "")
    home_display = _team_display(home_key)
    away_display = _team_display(away_key)

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

    # CARD-FIX-B Task 3: resolve real kickoff from broadcast_schedule
    if conn is not None and date_str and home_display and away_display:
        try:
            _bs_row = conn.execute(
                """
                SELECT start_time FROM broadcast_schedule
                WHERE broadcast_date = ?
                  AND (home_team LIKE ? OR away_team LIKE ?)
                  AND (home_team LIKE ? OR away_team LIKE ?)
                  AND is_live = 1
                LIMIT 1
                """,
                (date_str,
                 f"%{home_display}%", f"%{home_display}%",
                 f"%{away_display}%", f"%{away_display}%"),
            ).fetchone()
            if _bs_row and _bs_row["start_time"]:
                from zoneinfo import ZoneInfo
                _st = datetime.fromisoformat(str(_bs_row["start_time"]))
                _sa_tz = ZoneInfo("Africa/Johannesburg")
                if _st.tzinfo is None:
                    _st = _st.replace(tzinfo=_sa_tz)
                else:
                    _st = _st.astimezone(_sa_tz)
                _time_str = _st.strftime("%H:%M")
                # Enrich kickoff with real time
                today = datetime.now().date()
                diff = (_st.date() - today).days
                if diff == 0:
                    kickoff = f"Today {_time_str}"
                elif diff == 1:
                    kickoff = f"Tomorrow {_time_str}"
                else:
                    kickoff = _st.strftime(f"%a %-d %b {_time_str}")
        except Exception as _bs_exc:
            log.debug("card_pipeline: broadcast_schedule kickoff query failed: %s", _bs_exc)

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

    # ── IMG-W2: compute new structured fields ─────────────────────────────────
    _results = verified.get("results") or []
    home_form = _compute_team_form(_results, home_key)
    away_form = _compute_team_form(_results, away_key)
    # CARD-REBUILD-04-02: asymmetric guard + most-recent-RIGHT reversal.
    # Results are fetched ORDER BY match_date DESC, so _compute_team_form returns
    # [newest, ..., oldest]. Reverse to [oldest, ..., newest] so rightmost dot
    # = most recent (Pixel Ref Rule 6). If either side has 0 results, hide both.
    if not home_form or not away_form:
        home_form = []
        away_form = []
    else:
        _form_n = min(len(home_form), len(away_form))
        home_form = home_form[:_form_n][::-1]
        away_form = away_form[:_form_n][::-1]
    # D-17b: hard cap at 5 regardless of asymmetric guard result
    home_form = home_form[:5]
    away_form = away_form[:5]
    _h2h_results = verified.get("h2h_results") or []
    h2h = _compute_h2h(_h2h_results if _h2h_results else _results, home_key, away_key)

    _raw_injuries = verified.get("injuries") or []
    home_injuries, away_injuries = _split_injuries(_raw_injuries, home_key, away_key)

    signals = _compute_signals(tip, verified)
    pick_team = _compute_pick_team(outcome, home_display, away_display)
    no_edge_reason = _compute_no_edge_reason(ev, verified, tip)
    key_stats = _compute_key_stats(verified, home_key, away_key, home_form, away_form, h2h)
    odds_structured = _compute_odds_structured(verified)

    card: dict = {
        # ── original fields (backward compatible — DO NOT REMOVE) ─────────
        "matchup": verified["matchup"] or f"{home_display} vs {away_display}",
        "home_team": home_display,
        "away_team": away_display,
        "outcome": outcome,
        "odds": best_odds_val,
        "bookmaker": best_bookmaker,
        "confidence": confidence,
        "ev": ev,
        "kickoff": kickoff,
        "venue": verified.get("venue") or (tip.get("venue") if tip else "") or "",
        "broadcast": broadcast,
        "sport": sport,
        "tier": tier,
        "analysis_text": analysis_text,
        "data_sources_used": verified["data_sources_used"],
        # Pass-through for downstream renderers
        "_verified": verified,
        # ── IMG-W2 structured fields (new — required by Pillow renderer) ──
        "home_form": home_form,        # AC-1: list[str] of 'W'/'D'/'L'
        "away_form": away_form,        # AC-1
        "signals": signals,            # AC-2: dict[str, bool]
        "h2h": h2h,                    # AC-3: {played, hw, d, aw}
        "home_injuries": home_injuries,  # AC-4: list[str] 'Player (status)'
        "away_injuries": away_injuries,  # AC-4
        "pick_team": pick_team,        # AC-5: clean team name string
        "no_edge_reason": no_edge_reason,  # AC-6: deterministic template
        "key_stats": key_stats,        # AC-7: list of 4 stat box dicts
        "odds_structured": odds_structured,  # AC-8: {home,draw,away} with bookmaker
        # ── IMG-W1R: edge_digest portrait fields (additive) ───────────────
        "league": (tip.get("league") or tip.get("league_display") or tip.get("league_key") or "") if tip else "",
        "broadcast_channel": (tip.get("_bc_broadcast") or tip.get("broadcast_channel") or "") if tip else "",
        "display_tier": tier,
        # CARD-BUILD-01: stealth fallback marker
        "data_status": "no_data" if not tip else "ok",
        # CARD-BUILD-01: Fair Value from model probability
        "fair_value": round(float(tip.get("prob", 0) or 0) * 100, 1) if tip and tip.get("prob") else None,
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
