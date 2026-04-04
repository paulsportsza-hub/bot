#!/usr/bin/env python3
"""
MzansiEdge --- Admin Panel
Served at /admin/health (default) on port 8501.
Read-only access to SQLite. Never writes to any DB.
Sidebar navigation with Data Health, Automation, and Customers views.
"""

import functools
import json
import os
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timezone, timedelta

from flask import Flask, Response, request, redirect

# -- Response cache (avoids heavy queries on every request) -------------------
_page_cache: dict[str, tuple[str, float]] = {}
_page_cache_lock = threading.Lock()
_PAGE_CACHE_TTL = 60  # seconds

# -- Notion cache for Automation view ----------------------------------------
_notion_cache: dict[str, tuple[list, float]] = {}
_notion_cache_lock = threading.Lock()
_NOTION_CACHE_TTL = 60  # seconds

# -- Config -------------------------------------------------------------------
SCRAPERS_DB = os.path.expanduser("~/scrapers/odds.db")
BOT_DB = os.path.expanduser("~/bot/data/mzansiedge.db")
TIPSTER_DB = os.path.expanduser("~/scrapers/tipsters/tipster_predictions.db")
QUOTAS_FILE = os.path.join(os.path.dirname(__file__), "api_quotas.json")

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "mzansiedge")
PORT = int(os.getenv("DASHBOARD_PORT", "8501"))

NOTION_TOKEN = os.getenv(
    "NOTION_TOKEN",
    "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",
)
NOTION_MARKETING_DB = "58123052-0e48-466a-be63-5308e793e672"

# -- SAST timezone offset -----------------------------------------------------
_SAST = timezone(timedelta(hours=2))

# -- League chart labels (full names) -----------------------------------------

_LEAGUE_CHART_NAMES: dict[str, str] = {
    "CHAMPIONS LEAGUE": "Champions League",
    "SUPER RUGBY": "Super Rugby",
    "TEST CRICKET": "Test Cricket",
    "TEST MATCHES": "Test Cricket",
    "SIX NATIONS": "Six Nations",
    "RUGBY CHAMPIONSHIP": "Rugby Champ",
    "T20 WORLD CUP": "T20 World Cup",
    "BIG BASH": "Big Bash",
    "URC": "URC",
    "CURRIE CUP": "Currie Cup",
    "VARSITY CUP": "Varsity Cup",
    "EPL": "EPL",
    "PSL": "PSL",
    "SA20": "SA20",
    "IPL": "IPL",
    "UFC": "MMA/UFC",
    "BOXING": "Boxing",
    "LA LIGA": "La Liga",
    "BUNDESLIGA": "Bundesliga",
    "SERIE A": "Serie A",
    "LIGUE 1": "Ligue 1",
    "MLS": "MLS",
    "INTERNATIONAL RUGBY": "Intl Rugby",
}


def _chart_label(league_upper: str) -> str:
    return _LEAGUE_CHART_NAMES.get(league_upper, league_upper.title())


BOOKMAKERS = [
    "hollywoodbets", "supabets", "betway", "sportingbet",
    "gbets", "wsb", "playabets", "supersportbet",
]
BK_DISPLAY = {
    "hollywoodbets": "HWB",
    "supabets": "Supabets",
    "betway": "Betway",
    "sportingbet": "Sportingbet",
    "gbets": "GBets",
    "wsb": "WSB",
    "playabets": "Playabets",
    "supersportbet": "SuperSportBet",
}

# -- Automation channel config ------------------------------------------------
_CHANNELS = [
    {"key": "facebook", "label": "Facebook", "color": "#1877F2"},
    {"key": "instagram", "label": "Instagram", "color": "#E4405F"},
    {"key": "linkedin", "label": "LinkedIn", "color": "#0A66C2"},
    {"key": "tiktok", "label": "TikTok", "color": "#ff0050"},
    {"key": "telegram_image", "label": "Telegram Image", "color": "#26A5E4"},
    {"key": "whatsapp", "label": "WhatsApp", "color": "#25D366"},
    {"key": "x_twitter", "label": "X / Twitter", "color": "#F5F5F5"},
]
_CHANNEL_MAP = {c["key"]: c for c in _CHANNELS}

app = Flask(__name__)


# -- Auth ---------------------------------------------------------------------

def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != DASHBOARD_USER or auth.password != DASHBOARD_PASS:
            return Response(
                "Unauthorized -- MzansiEdge Ops Dashboard",
                401,
                {"WWW-Authenticate": 'Basic realm="MzansiEdge Ops"'},
            )
        return f(*args, **kwargs)
    return wrapper


# -- DB helpers ---------------------------------------------------------------

def db_connect(path: str):
    """Open a read-only SQLite connection with timeout. Returns None if unavailable."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def q_all(conn, sql: str, params=()):
    if conn is None:
        return []
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:
        return []


def q_one(conn, sql: str, params=()):
    if conn is None:
        return None
    try:
        return conn.execute(sql, params).fetchone()
    except Exception:
        return None


def table_exists(conn, name: str) -> bool:
    r = q_one(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return r is not None


# -- Helpers ------------------------------------------------------------------

def parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        s = ts_str.strip().replace("Z", "+00:00")
        if "+" not in s[10:] and "-" not in s[10:]:
            s += "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def freshness(ts_str: str | None) -> tuple[str, str]:
    """Return (css_class, human_label) for a timestamp."""
    dt = parse_ts(ts_str)
    if dt is None:
        return "s-black", "Never"
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if age_h < 1:
        mins = int(age_h * 60)
        return "s-green", f"{mins}m ago"
    elif age_h < 6:
        return "s-amber", f"{age_h:.1f}h ago"
    else:
        return "s-red", f"{age_h:.1f}h ago"


def coverage_badge(pct: float) -> tuple[str, str]:
    if pct >= 90:
        return "s-green", "Healthy"
    elif pct >= 50:
        return "s-amber", "Degraded"
    elif pct > 0:
        return "s-red", "Critical"
    else:
        return "s-black", "No Data"


def _relative_time(ts_str: str | None) -> str:
    """Human-readable relative time from an ISO timestamp string."""
    dt = parse_ts(ts_str)
    if dt is None:
        return "Never"
    delta = datetime.now(timezone.utc) - dt
    secs = delta.total_seconds()
    if secs < 0:
        # Future
        secs = abs(secs)
        if secs < 3600:
            return f"in {int(secs // 60)}m"
        elif secs < 86400:
            return f"in {secs / 3600:.1f}h"
        else:
            return f"in {secs / 86400:.1f}d"
    if secs < 60:
        return "just now"
    elif secs < 3600:
        return f"{int(secs // 60)}m ago"
    elif secs < 86400:
        return f"{secs / 3600:.1f}h ago"
    else:
        return f"{secs / 86400:.1f}d ago"


def _sast_hhmm(ts_str: str | None) -> str:
    """Format ISO timestamp as HH:MM SAST."""
    dt = parse_ts(ts_str)
    if dt is None:
        return "--:--"
    sast = dt.astimezone(_SAST)
    return sast.strftime("%H:%M")


def _truncate(text: str | None, max_len: int) -> str:
    if not text:
        return ""
    text = str(text).replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


# -- Panel data builders (Data Health) ----------------------------------------

def build_coverage_matrix(conn) -> list[dict]:
    if not table_exists(conn, "odds_snapshots"):
        return []
    # P0 Fix: use scraped_at filter with idx_odds_time index instead of
    # substr(match_id, -10) which forces full table scan on 1.36M rows
    rows = q_all(conn, """
        SELECT u.sport, u.league,
            COUNT(DISTINCT u.match_id)                                          AS total,
            COUNT(CASE WHEN nc.narrative_source = 'w84'           THEN 1 END)  AS w84,
            COUNT(CASE WHEN nc.narrative_source = 'w82'           THEN 1 END)  AS w82,
            COUNT(CASE WHEN nc.narrative_source = 'baseline_no_edge' THEN 1 END) AS baseline
        FROM (
            SELECT DISTINCT match_id, sport, league
            FROM   odds_snapshots
            WHERE  scraped_at >= datetime('now', '-7 days')
        ) u
        LEFT JOIN narrative_cache nc ON nc.match_id = u.match_id
        GROUP BY u.sport, u.league
        ORDER BY u.sport, u.league
    """)
    out = []
    for r in rows:
        total = r["total"] or 0
        w84   = r["w84"]   or 0
        pct   = (w84 / total * 100) if total > 0 else 0
        css, badge = coverage_badge(pct)
        out.append({
            "sport":    r["sport"],
            "league":   r["league"].upper().replace("_", " "),
            "total":    total,
            "w84":      w84,
            "w82":      r["w82"]      or 0,
            "baseline": r["baseline"] or 0,
            "pct":      round(pct, 1),
            "css":      css,
            "badge":    badge,
        })

    # -- Rugby watchlist: URC / Varsity Cup / Currie Cup visibility -----------
    _RUGBY_WATCHLIST = [
        ("urc",     "URC"),
        ("varsity",  "Varsity Cup"),
        ("currie",   "Currie Cup"),
    ]

    all_rugby_rows = q_all(conn, """
        SELECT DISTINCT LOWER(league) AS league FROM odds_snapshots
        WHERE LOWER(league) LIKE '%rugby%'
           OR LOWER(league) LIKE '%urc%'
           OR LOWER(league) LIKE '%varsity%'
           OR LOWER(league) LIKE '%currie%'
        LIMIT 30
    """)
    found_rugby_leagues = {r["league"] for r in all_rugby_rows}
    app.logger.info("[DASHBOARD] Rugby-related leagues in odds_snapshots: %s",
                    found_rugby_leagues or "none found")

    in_matrix = {c["league"].lower() for c in out}

    for kw, display in _RUGBY_WATCHLIST:
        if any(kw in lg for lg in in_matrix):
            continue
        in_db = any(kw in lg for lg in found_rugby_leagues)
        badge = "No Data" if in_db else "Not Tracked"
        out.append({
            "sport":    "rugby",
            "league":   display,
            "total":    0,
            "w84":      0,
            "w82":      0,
            "baseline": 0,
            "pct":      0.0,
            "css":      "s-black",
            "badge":    badge,
        })

    return out


def _trend_indicator(current_7d: int, prev_7d: int) -> str:
    """Return 7d trend indicator: count + directional arrow."""
    if prev_7d == 0 and current_7d == 0:
        return "\u2014"
    if prev_7d == 0:
        return f"{current_7d:,} \u2191"
    delta_pct = (current_7d - prev_7d) / prev_7d
    if delta_pct > 0.1:
        arrow = "\u2191"
    elif delta_pct < -0.1:
        arrow = "\u2193"
    else:
        arrow = "\u2192"
    return f"{current_7d:,} {arrow}"


def build_source_freshness(conn) -> list[dict]:
    out = []

    def row(name, last_ts, records_24h, trend_7d="\u2014"):
        css, lbl = freshness(last_ts)
        out.append({
            "name": name, "last_pull": lbl,
            "records_24h": records_24h,
            "css": css, "trend_7d": trend_7d,
        })

    # SA bookmakers
    if table_exists(conn, "scrape_runs"):
        r = q_one(conn, "SELECT finished_at, bookmaker_summary FROM scrape_runs ORDER BY id DESC LIMIT 1")
        if r:
            try:
                total = sum(json.loads(r["bookmaker_summary"] or "{}").values())
            except Exception:
                total = 0
            c7 = q_one(conn, "SELECT COUNT(*) as c FROM odds_snapshots WHERE scraped_at >= datetime('now','-7 days')")
            c14 = q_one(conn, "SELECT COUNT(*) as c FROM odds_snapshots WHERE scraped_at >= datetime('now','-14 days') AND scraped_at < datetime('now','-7 days')")
            trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
            row("SA Bookmakers (8x)", r["finished_at"], total, trend)
        else:
            row("SA Bookmakers (8x)", None, 0)
    else:
        out.append({"name": "SA Bookmakers (8x)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # The Odds API (sharp)
    if table_exists(conn, "sharp_odds"):
        r = q_one(conn, "SELECT MAX(scraped_at) as last FROM sharp_odds")
        c = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-24 hours')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-14 days') AND scraped_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        row("The Odds API (Sharp)", r["last"] if r else None, (c["c"] if c else 0), trend)
    else:
        out.append({"name": "The Odds API (Sharp)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # ESPN
    if table_exists(conn, "espn_stats_cache"):
        r = q_one(conn, "SELECT MAX(fetched_at) as last, COUNT(*) as c FROM espn_stats_cache")
        row("ESPN Hidden API", r["last"] if r else None, r["c"] if r else 0, f"{r['c'] if r else 0} \u2192")
    else:
        out.append({"name": "ESPN Hidden API", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # API-Football
    if table_exists(conn, "api_usage"):
        r = q_one(conn, "SELECT MAX(called_at) as last FROM api_usage WHERE api_name='api_football'")
        c = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_football' AND called_at >= date('now')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_football' AND called_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_football' AND called_at >= datetime('now','-14 days') AND called_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        if r and r["last"]:
            row("API-Football", r["last"], c["c"] if c else 0, trend)
        else:
            out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})
    else:
        out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # Narrative cache
    if table_exists(conn, "narrative_cache"):
        r = q_one(conn, "SELECT MAX(created_at) as last FROM narrative_cache")
        c = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-24 hours')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-14 days') AND created_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        row("Narrative Cache", r["last"] if r else None, c["c"] if c else 0, trend)
    else:
        out.append({"name": "Narrative Cache", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # API-Sports MMA
    if table_exists(conn, "api_usage"):
        r = q_one(conn, "SELECT MAX(called_at) as last FROM api_usage WHERE api_name='api_sports_mma'")
        c = q_one(conn, "SELECT COUNT(*) as c FROM mma_fixtures WHERE scraped_at >= datetime('now','-24 hours')") if table_exists(conn, "mma_fixtures") else None
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_sports_mma' AND called_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_sports_mma' AND called_at >= datetime('now','-14 days') AND called_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        if r and r["last"]:
            row("API-Sports MMA", r["last"], c["c"] if c else 0, trend)
        else:
            out.append({"name": "API-Sports MMA", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})
    else:
        out.append({"name": "API-Sports MMA", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # API-Sports Rugby
    if table_exists(conn, "api_usage"):
        r = q_one(conn, "SELECT MAX(called_at) as last FROM api_usage WHERE api_name='api_sports_rugby'")
        c = q_one(conn, "SELECT COUNT(*) as c FROM rugby_fixtures WHERE scraped_at >= datetime('now','-24 hours')") if table_exists(conn, "rugby_fixtures") else None
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_sports_rugby' AND called_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_sports_rugby' AND called_at >= datetime('now','-14 days') AND called_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        if r and r["last"]:
            row("API-Sports Rugby", r["last"], c["c"] if c else 0, trend)
        else:
            out.append({"name": "API-Sports Rugby", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})
    else:
        out.append({"name": "API-Sports Rugby", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # Sportmonks Cricket
    if table_exists(conn, "api_usage"):
        r = q_one(conn, "SELECT MAX(called_at) as last FROM api_usage WHERE api_name='sportmonks_cricket'")
        c = q_one(conn, "SELECT COUNT(*) as c FROM sportmonks_fixtures WHERE scraped_at >= datetime('now','-24 hours')") if table_exists(conn, "sportmonks_fixtures") else None
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='sportmonks_cricket' AND called_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='sportmonks_cricket' AND called_at >= datetime('now','-14 days') AND called_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        if r and r["last"]:
            row("Sportmonks Cricket", r["last"], c["c"] if c else 0, trend)
        else:
            out.append({"name": "Sportmonks Cricket", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})
    else:
        out.append({"name": "Sportmonks Cricket", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # Tipster Sources
    tip_conn = db_connect(TIPSTER_DB)
    if tip_conn:
        try:
            tr = tip_conn.execute(
                "SELECT MAX(scraped_at) as last, "
                "SUM(CASE WHEN scraped_at >= datetime('now','-24 hours') THEN 1 ELSE 0 END) as d1, "
                "SUM(CASE WHEN scraped_at >= datetime('now','-7 days') THEN 1 ELSE 0 END) as d7, "
                "SUM(CASE WHEN scraped_at >= datetime('now','-14 days') AND scraped_at < datetime('now','-7 days') THEN 1 ELSE 0 END) as d14, "
                "COUNT(DISTINCT source) as sources "
                "FROM predictions"
            ).fetchone()
            if tr and tr["last"]:
                src_count = tr["sources"] or 0
                trend = _trend_indicator(tr["d7"] or 0, tr["d14"] or 0)
                row(f"Tipster Sources ({src_count}x)", tr["last"], tr["d1"] or 0, trend)
            else:
                row("Tipster Sources", None, 0)
        except Exception:
            row("Tipster Sources", None, 0)
        finally:
            tip_conn.close()
    else:
        out.append({"name": "Tipster Sources", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "\u2014"})

    # WAHA / WhatsApp
    out.append({"name": "WAHA / WhatsApp", "last_pull": "Not Connected", "records_24h": 0, "css": "s-amber", "trend_7d": "\u2014"})

    return out


def build_scraper_health(conn) -> list[dict]:
    if not table_exists(conn, "odds_snapshots"):
        return [{"name": BK_DISPLAY[b], "last_scrape": "Not Connected", "matches_24h": 0, "avg_odds": 0, "css": "s-black"} for b in BOOKMAKERS]
    rows = q_all(conn, """
        SELECT bookmaker,
               COUNT(DISTINCT match_id)                           AS matches,
               CAST(COUNT(*) AS REAL) / NULLIF(COUNT(DISTINCT match_id), 0) AS avg_odds,
               MAX(scraped_at)                                    AS last
        FROM   odds_snapshots
        WHERE  scraped_at >= datetime('now', '-24 hours')
        GROUP  BY bookmaker
    """)
    by_bk = {r["bookmaker"]: r for r in rows}
    out = []
    for bk in BOOKMAKERS:
        r = by_bk.get(bk)
        if r:
            css, lbl = freshness(r["last"])
            out.append({
                "name":       BK_DISPLAY[bk],
                "last_scrape": lbl,
                "matches_24h": r["matches"] or 0,
                "avg_odds":    round(r["avg_odds"] or 0, 1),
                "css":         css,
            })
        else:
            out.append({
                "name":       BK_DISPLAY[bk],
                "last_scrape": "No data (24h)",
                "matches_24h": 0,
                "avg_odds":    0,
                "css":         "s-red",
            })
    return out


def build_api_quotas(conn) -> list[dict]:
    """Build API quota rows from live DB data. Accepts caller's connection."""
    quotas = []

    # -- The Odds API --
    odds_used_month = 0
    odds_used_today = 0
    monthly_limit = 20000
    credits_per_batch = 34
    if conn:
        try:
            mr = conn.execute(
                "SELECT COUNT(DISTINCT substr(scraped_at,1,16)) as batches "
                "FROM sharp_odds WHERE scraped_at >= strftime('%Y-%m-01','now')"
            ).fetchone()
            if mr:
                odds_used_month = (mr["batches"] or 0) * credits_per_batch
            dr = conn.execute(
                "SELECT COUNT(DISTINCT substr(scraped_at,1,16)) as batches "
                "FROM sharp_odds WHERE scraped_at >= date('now')"
            ).fetchone()
            if dr:
                odds_used_today = (dr["batches"] or 0) * credits_per_batch
        except Exception:
            pass

    odds_remaining = max(monthly_limit - odds_used_month, 0)
    quotas.append({
        "api": "The Odds API",
        "plan": "Upgraded (20K/month)",
        "daily_limit": 670,
        "used_today": odds_used_today,
        "remaining": odds_remaining,
        "reset": "1st of month",
    })

    # -- API-Football --
    af_used_today = 0
    af_daily_limit = 100
    if conn:
        try:
            ar = conn.execute(
                "SELECT COUNT(*) as cnt FROM api_usage "
                "WHERE api_name='api_football' AND called_at >= date('now')"
            ).fetchone()
            if ar:
                af_used_today = ar["cnt"] or 0
        except Exception:
            pass

    quotas.append({
        "api": "API-Football",
        "plan": "Free (100/day)",
        "daily_limit": af_daily_limit,
        "used_today": af_used_today,
        "remaining": max(af_daily_limit - af_used_today, 0),
        "reset": "Midnight UTC",
    })

    # -- API-Sports MMA --
    mma_used_today = 0
    mma_daily_limit = 100
    if conn:
        try:
            mr = conn.execute(
                "SELECT COUNT(*) as cnt FROM api_usage "
                "WHERE api_name='api_sports_mma' AND called_at >= date('now')"
            ).fetchone()
            if mr:
                mma_used_today = mr["cnt"] or 0
        except Exception:
            pass

    quotas.append({
        "api": "API-Sports MMA",
        "plan": "Free (100/day)",
        "daily_limit": mma_daily_limit,
        "used_today": mma_used_today,
        "remaining": max(mma_daily_limit - mma_used_today, 0),
        "reset": "Midnight UTC",
    })

    # -- API-Sports Rugby --
    rugby_used_today = 0
    rugby_daily_limit = 100
    if conn:
        try:
            rr = conn.execute(
                "SELECT COUNT(*) as cnt FROM api_usage "
                "WHERE api_name='api_sports_rugby' AND called_at >= date('now')"
            ).fetchone()
            if rr:
                rugby_used_today = rr["cnt"] or 0
        except Exception:
            pass

    quotas.append({
        "api": "API-Sports Rugby",
        "plan": "Free (100/day)",
        "daily_limit": rugby_daily_limit,
        "used_today": rugby_used_today,
        "remaining": max(rugby_daily_limit - rugby_used_today, 0),
        "reset": "Midnight UTC",
    })

    # -- Sportmonks Cricket --
    sm_used_today = 0
    sm_daily_limit = 500
    if conn:
        try:
            sr = conn.execute(
                "SELECT COUNT(*) as cnt FROM api_usage "
                "WHERE api_name='sportmonks_cricket' AND called_at >= date('now')"
            ).fetchone()
            if sr:
                sm_used_today = sr["cnt"] or 0
        except Exception:
            pass

    quotas.append({
        "api": "Sportmonks Cricket",
        "plan": "Subscription",
        "daily_limit": sm_daily_limit,
        "used_today": sm_used_today,
        "remaining": max(sm_daily_limit - sm_used_today, 0),
        "reset": "Midnight UTC",
    })

    return quotas


def build_alerts(conn, coverage: list[dict]) -> list[dict]:
    """Build alert list. Accepts pre-computed coverage to avoid duplicate query."""
    alerts = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if conn is None:
        return [{"ts": now_str, "sev": "crit", "msg": "Main DB unreachable -- all panels degraded"}]

    # Scrapers silent in last 6h
    if table_exists(conn, "odds_snapshots"):
        rows = q_all(conn, """
            SELECT bookmaker FROM odds_snapshots
            WHERE scraped_at >= datetime('now','-6 hours')
            GROUP BY bookmaker
        """)
        active = {r["bookmaker"] for r in rows}
        for bk in BOOKMAKERS:
            if bk not in active:
                alerts.append({
                    "ts": now_str, "sev": "crit",
                    "msg": f"Scraper silent -- {BK_DISPLAY.get(bk, bk)}: 0 records in last 6h",
                })

    # Sports with 0% w84 coverage (use pre-computed coverage)
    for c in coverage:
        if c["total"] > 0 and c["w84"] == 0:
            alerts.append({
                "ts": now_str, "sev": "warn",
                "msg": f"Zero w84 -- {c['sport'].upper()} / {c['league']}: {c['total']} matches, all {('w82' if c['w82'] else 'baseline')}",
            })

    # Matches with edge data but no w84 narrative
    if table_exists(conn, "narrative_cache") and table_exists(conn, "edge_results"):
        rows = q_all(conn, """
            SELECT nc.match_id, nc.narrative_source, nc.created_at
            FROM   narrative_cache nc
            INNER  JOIN edge_results er ON er.match_key = nc.match_id
            WHERE  nc.narrative_source IN ('w82','baseline_no_edge')
            ORDER  BY nc.created_at DESC LIMIT 15
        """)
        for r in rows:
            alerts.append({
                "ts":  (r["created_at"] or "")[:19],
                "sev": "warn",
                "msg": f"Edge data present but narrative={r['narrative_source']}: {r['match_id']}",
            })

    return sorted(alerts, key=lambda x: x["ts"], reverse=True)[:50]


# -- Notion API helpers (Automation view) -------------------------------------

def _notion_request(endpoint: str, body: dict | None = None) -> dict | None:
    """Make a Notion API request using urllib. Returns parsed JSON or None."""
    url = f"https://api.notion.com/v1/{endpoint}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2025-09-03",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _query_notion_db(db_id: str, filter_obj: dict | None = None, sorts: list | None = None, page_size: int = 100) -> list[dict]:
    """Query a Notion database. Returns list of page objects."""
    body: dict = {"page_size": page_size}
    if filter_obj:
        body["filter"] = filter_obj
    if sorts:
        body["sorts"] = sorts
    result = _notion_request(f"data_sources/{db_id}/query", body)
    if result and "results" in result:
        return result["results"]
    return []


def _get_page_prop(page: dict, prop_name: str) -> str | None:
    """Extract a simple property value from a Notion page object."""
    props = page.get("properties", {})
    prop = props.get(prop_name)
    if not prop:
        return None
    ptype = prop.get("type", "")
    if ptype == "title":
        arr = prop.get("title", [])
        return arr[0]["plain_text"] if arr else None
    elif ptype == "rich_text":
        arr = prop.get("rich_text", [])
        return arr[0]["plain_text"] if arr else None
    elif ptype == "select":
        sel = prop.get("select")
        return sel["name"] if sel else None
    elif ptype == "multi_select":
        return ", ".join(s["name"] for s in prop.get("multi_select", []))
    elif ptype == "date":
        d = prop.get("date")
        if d:
            return d.get("start")
        return None
    elif ptype == "url":
        return prop.get("url")
    elif ptype == "status":
        st = prop.get("status")
        return st["name"] if st else None
    elif ptype == "checkbox":
        return str(prop.get("checkbox", False))
    elif ptype == "number":
        return str(prop.get("number", ""))
    elif ptype == "files":
        files = prop.get("files", [])
        return files[0].get("name", "") if files else None
    return None


def _fetch_marketing_queue() -> tuple[list[dict], float]:
    """Fetch all items from Marketing Ops Queue. Returns (items, fetch_time)."""
    cache_key = "marketing_queue"
    now = time.monotonic()
    with _notion_cache_lock:
        cached = _notion_cache.get(cache_key)
        if cached and (now - cached[1]) < _NOTION_CACHE_TTL:
            return cached[0], cached[1]

    raw_pages = _query_notion_db(NOTION_MARKETING_DB, page_size=100)
    items = []
    for page in raw_pages:
        item = {
            "id": page.get("id", ""),
            "title": _get_page_prop(page, "Title") or _get_page_prop(page, "Name") or "",
            "status": _get_page_prop(page, "Status") or "",
            "channel": _get_page_prop(page, "Channel") or "",
            "scheduled_time": _get_page_prop(page, "Scheduled Time") or _get_page_prop(page, "Scheduled") or "",
            "copy": _get_page_prop(page, "Copy") or _get_page_prop(page, "Copy Preview") or _get_page_prop(page, "Body") or "",
            "url": _get_page_prop(page, "URL") or _get_page_prop(page, "Published URL") or "",
            "asset": _get_page_prop(page, "Asset") or _get_page_prop(page, "Media") or "",
            "error": _get_page_prop(page, "Error") or _get_page_prop(page, "Reason") or "",
            "created": page.get("created_time", ""),
            "last_edited": page.get("last_edited_time", ""),
        }
        items.append(item)

    with _notion_cache_lock:
        _notion_cache[cache_key] = (items, now)

    return items, now


def _normalise_channel_key(raw: str) -> str:
    """Normalise channel name to a key in _CHANNEL_MAP."""
    if not raw:
        return ""
    low = raw.lower().strip()
    for key in _CHANNEL_MAP:
        if key.replace("_", " ") in low or key.replace("_", "") in low.replace(" ", ""):
            return key
    # Fallback heuristics
    if "fb" in low or "facebook" in low:
        return "facebook"
    if "ig" in low or "insta" in low:
        return "instagram"
    if "linked" in low:
        return "linkedin"
    if "tiktok" in low or "tik" in low:
        return "tiktok"
    if "telegram" in low:
        return "telegram_image"
    if "whatsapp" in low or "wa" in low:
        return "whatsapp"
    if "twitter" in low or low == "x":
        return "x_twitter"
    return ""


# -- HTML renderer helpers ----------------------------------------------------

STATUS_CSS = {
    "s-green": "color:#22c55e;font-weight:700",
    "s-amber": "color:#f59e0b;font-weight:700",
    "s-red":   "color:#ef4444;font-weight:700",
    "s-black": "color:#6b7280;font-weight:700",
}


def dot(css_class: str) -> str:
    styles = {
        "s-green": "#22c55e",
        "s-amber": "#f59e0b",
        "s-red":   "#ef4444",
        "s-black": "#6b7280",
    }
    colour = styles.get(css_class, "#6b7280")
    return f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{colour};margin-right:6px"></span>'


def td(content, css="", extra_style=""):
    style = STATUS_CSS.get(css, "")
    if extra_style:
        style = (style + ";" + extra_style).strip(";")
    s = f' style="{style}"' if style else ""
    return f"<td{s}>{content}</td>"


# -- SVG Icons ----------------------------------------------------------------

_ICON_HEARTBEAT = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>'
_ICON_PLAY = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>'
_ICON_USERS = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
_ICON_GEAR = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>'



# -- Shared CSS ---------------------------------------------------------------

def _shared_css() -> str:
    return """
  :root {
    --carbon: #0A0A0A;
    --surface: #111111;
    --surface-alt: #161616;
    --border: #1f1f1f;
    --border-sub: #161616;
    --text: #F5F5F5;
    --muted: #6b7280;
    --gold: #F8C830;
    --gold-mid: #F0A020;
    --gold-end: #E8571F;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
    --font-d: 'Outfit', sans-serif;
    --font-b: 'Work Sans', sans-serif;
    --font-m: 'ui-monospace','Cascadia Code','Fira Code','Consolas',monospace;
    --grad: linear-gradient(135deg, #F8C830, #F0A020, #E8571F);
    --r: 10px;
    --sidebar-w: 220px;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: var(--carbon); color: var(--text); font-family: var(--font-b); font-size: 14px; line-height: 1.6; min-height: 100vh; overflow-x: hidden; }
  a { color: var(--gold); text-decoration: none; } a:hover { text-decoration: underline; }

  /* SIDEBAR */
  .sidebar {
    position: fixed; top: 0; left: 0; bottom: 0; z-index: 200;
    width: var(--sidebar-w);
    background: #0A0A0A;
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column;
    overflow: hidden;
  }
  .sidebar-brand {
    display: flex; align-items: center; justify-content: center;
    padding: 20px 16px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .sidebar-brand img { width: 160px; height: auto; display: block; }
  .sidebar-nav { flex: 1; display: flex; flex-direction: column; padding: 8px 0; gap: 2px; }
  .sidebar-item {
    display: flex; align-items: center; gap: 12px;
    height: 42px; padding: 0 0 0 19px;
    color: var(--muted); cursor: pointer;
    border-left: 3px solid transparent;
    transition: background 150ms, color 150ms, border-color 150ms;
    text-decoration: none; white-space: nowrap; overflow: hidden;
  }
  .sidebar-item:hover { background: rgba(255,255,255,0.04); color: var(--text); text-decoration: none; }
  .sidebar-item.active {
    border-left: 3px solid; border-image: var(--grad) 1;
    background: rgba(248,200,48,0.06); color: var(--text);
  }
  .sidebar-item .item-icon { flex-shrink: 0; display: flex; align-items: center; }
  .sidebar-item .item-label {
    font-family: var(--font-d); font-weight: 600; font-size: 12px;
    letter-spacing: 0.04em;
  }
  .sidebar-bottom {
    border-top: 1px solid var(--border);
    padding: 8px 0; flex-shrink: 0;
  }

  /* CONTENT AREA */
  .content-area {
    margin-left: var(--sidebar-w);
    min-height: 100vh;
  }

  /* TOPBAR (inside content area) */
  .topbar { position: sticky; top: 0; z-index: 100; background: rgba(10,10,10,0.96); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-bottom: 1px solid var(--border); padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .topbar-left { display: flex; align-items: center; gap: 16px; }
  .topbar-pill { background: rgba(248,200,48,0.1); border: 1px solid rgba(248,200,48,0.2); border-radius: 999px; padding: 3px 12px; font-family: var(--font-d); font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--gold); }
  .topbar-right { display: flex; align-items: center; gap: 20px; }
  .topbar-meta { font-size: 11px; font-family: var(--font-m); color: var(--muted); }
  .topbar-meta em { color: var(--text); font-style: normal; }
  .db-status { display: flex; align-items: center; gap: 6px; font-size: 11px; font-family: var(--font-m); }
  .pulse { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .pulse-green { background: var(--green); box-shadow: 0 0 0 2px rgba(34,197,94,.25); animation: pulse 2s infinite; }
  .pulse-red   { background: var(--red);   box-shadow: 0 0 0 2px rgba(239,68,68,.25); }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 2px rgba(34,197,94,.25); } 50% { box-shadow: 0 0 0 5px rgba(34,197,94,.1); } }

  /* BANNER */
  .banner { padding: 7px 24px; font-size: 11px; font-family: var(--font-m); text-align: center; letter-spacing: .02em; }
  .banner-ok  { background: rgba(34,197,94,.06); color: var(--green); border-bottom: 1px solid rgba(34,197,94,.12); }
  .banner-err { background: rgba(239,68,68,.06);  color: var(--red);   border-bottom: 1px solid rgba(239,68,68,.12); }
  .banner-warn { background: rgba(245,158,11,.06); color: var(--amber); border-bottom: 1px solid rgba(245,158,11,.12); }

  /* PAGE */
  .page { max-width: 1440px; margin: 0 auto; padding: 20px 20px 48px; }

  /* KPI STRIP */
  .kpi-strip { display: grid; grid-template-columns: repeat(5,1fr); gap: 12px; margin-bottom: 20px; }
  .kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 14px 16px; position: relative; overflow: hidden; }
  .kpi::after { content:''; position:absolute; top:0; left:0; right:0; height:2px; background: var(--grad); }
  .kpi-lbl { font-size: 10px; font-family: var(--font-d); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
  .kpi-val { font-size: 26px; font-family: var(--font-d); font-weight: 700; line-height: 1; }
  .kpi-sub { font-size: 11px; font-family: var(--font-m); color: var(--muted); margin-top: 5px; }
  .c-gold  { color: var(--gold); }
  .c-green { color: var(--green); }
  .c-amber { color: var(--amber); }
  .c-red   { color: var(--red); }
  .c-text  { color: var(--text); }

  /* PANELS */
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); overflow: hidden; margin-bottom: 16px; }
  .panel-head { padding: 11px 18px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 12px; background: rgba(255,255,255,.015); }
  .panel-title { font-family: var(--font-d); font-weight: 700; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--text); }
  .panel-sub { font-size: 11px; font-family: var(--font-m); color: var(--muted); text-align: right; }
  .panel-red-accent { border-left: 3px solid var(--red); }
  .panel-orange-accent { border-top: 2px solid; border-image: var(--grad) 1; }

  /* TABLES */
  .tbl-wrap { overflow-x: auto; }
  .tbl { width: 100%; border-collapse: collapse; min-width: 480px; }
  .tbl thead th { font-family: var(--font-d); font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; background: rgba(0,0,0,.2); }
  .tbl tbody td { padding: 9px 14px; border-bottom: 1px solid var(--border-sub); font-family: var(--font-m); font-size: 12px; vertical-align: middle; white-space: nowrap; }
  .tbl tbody tr:last-child td { border-bottom: none; }
  .tbl tbody tr:hover td { background: rgba(248,200,48,.025); }

  /* CHIPS */
  .chip { display:inline-flex; align-items:center; gap:5px; padding:3px 9px; border-radius:999px; font-size:10px; font-weight:700; font-family:var(--font-d); letter-spacing:.04em; white-space:nowrap; }
  .cdot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
  .chip-green { background:rgba(34,197,94,.1);  color:var(--green); border:1px solid rgba(34,197,94,.2);  } .chip-green .cdot { background:var(--green); box-shadow:0 0 4px var(--green); }
  .chip-amber { background:rgba(245,158,11,.1); color:var(--amber); border:1px solid rgba(245,158,11,.2); } .chip-amber .cdot { background:var(--amber); }
  .chip-red   { background:rgba(239,68,68,.1);  color:var(--red);   border:1px solid rgba(239,68,68,.2);  } .chip-red   .cdot { background:var(--red); }
  .chip-gray  { background:rgba(107,114,128,.1);color:var(--muted); border:1px solid rgba(107,114,128,.2);} .chip-gray  .cdot { background:var(--muted); }

  /* Channel chips */
  .ch-chip { display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:4px; font-size:10px; font-weight:600; font-family:var(--font-d); letter-spacing:.03em; }
  .ch-dot { width:5px; height:5px; border-radius:50%; flex-shrink:0; }

  /* STATUS TEXT */
  .s-green { color:var(--green); font-weight:700; } .s-amber { color:var(--amber); font-weight:700; } .s-red { color:var(--red); font-weight:700; } .s-black { color:var(--muted); font-weight:700; }

  /* ALERT LOG */
  .alerts-scroll { max-height:320px; overflow-y:auto; }
  .alert-row { padding:9px 16px; border-bottom:1px solid var(--border-sub); display:flex; align-items:flex-start; gap:10px; }
  .alert-row:last-child { border-bottom:none; } .alert-row:hover { background:rgba(255,255,255,.02); }
  .alert-ts { font-family:var(--font-m); font-size:10px; color:var(--muted); white-space:nowrap; padding-top:2px; min-width:108px; }
  .alert-msg { font-family:var(--font-m); font-size:12px; line-height:1.45; color:var(--text); }
  .alert-badge { background:var(--red); color:#fff; border-radius:999px; padding:1px 8px; font-size:10px; font-weight:700; margin-left:6px; }

  /* CHART */
  .chart-wrap { padding:16px; height:200px; position:relative; }

  /* GRID */
  .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }

  /* STATUS CARDS GRID (Automation) */
  .channel-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:12px; padding:16px; }
  .channel-card { background:var(--surface-alt); border:1px solid var(--border); border-radius:var(--r); padding:14px; }
  .channel-card-head { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
  .channel-card-name { font-family:var(--font-d); font-weight:600; font-size:12px; }
  .channel-card-stat { font-family:var(--font-m); font-size:11px; color:var(--muted); margin-bottom:4px; }
  .channel-card-stat em { color:var(--text); font-style:normal; }

  /* COMING SOON */
  .coming-soon { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:60vh; color:var(--muted); gap:16px; }
  .coming-soon svg { opacity:0.3; }
  .coming-soon h2 { font-family:var(--font-d); font-weight:700; font-size:20px; color:var(--text); }
  .coming-soon p { font-family:var(--font-m); font-size:13px; }

  /* FOOTER */
  .footer { text-align:center; padding:20px; font-size:11px; font-family:var(--font-m); color:var(--muted); border-top:1px solid var(--border); margin-top:8px; }
  #countdown { color:var(--gold); font-weight:700; }

  /* RESPONSIVE */
  @media(max-width:768px) {
    .sidebar { display: none; }
    .content-area { margin-left: 0 !important; }
  }
  @media(max-width:1000px) { .kpi-strip { grid-template-columns:repeat(3,1fr); } .grid-2 { grid-template-columns:1fr; } }
  @media(max-width:600px)  { .kpi-strip { grid-template-columns:repeat(2,1fr); } .topbar { padding:10px 14px; } }
"""


# -- Sidebar HTML -------------------------------------------------------------

def _sidebar_html(active_view: str) -> str:
    items = [
        ("health", "Data Health", _ICON_HEARTBEAT, "/admin/health"),
        ("automation", "Automation", _ICON_PLAY, "/admin/automation"),
        ("customers", "Customers", _ICON_USERS, "/admin/customers"),
    ]
    nav_items = ""
    for key, label, icon, href in items:
        active_cls = " active" if key == active_view else ""
        nav_items += f'<a class="sidebar-item{active_cls}" href="{href}" data-view="{key}"><span class="item-icon">{icon}</span><span class="item-label">{label}</span></a>\n'

    return f"""<aside class="sidebar" id="sidebar">
  <div class="sidebar-brand"><img src="/static/wordmark.png" alt="MzansiEdge"></div>
  <nav class="sidebar-nav">{nav_items}</nav>
  <div class="sidebar-bottom">
    <a class="sidebar-item" href="#" title="Settings"><span class="item-icon">{_ICON_GEAR}</span><span class="item-label">Settings</span></a>
  </div>
</aside>"""


# -- Sidebar + Router JS -----------------------------------------------------

def _sidebar_js() -> str:
    return """
<script>
(function() {
  var contentInner = document.getElementById('contentInner');

  // AJAX view switching
  var navItems = document.querySelectorAll('.sidebar-item[data-view]');
  navItems.forEach(function(item) {
    item.addEventListener('click', function(e) {
      e.preventDefault();
      var view = this.getAttribute('data-view');
      var href = this.getAttribute('href');

      // Update active state
      navItems.forEach(function(n) { n.classList.remove('active'); });
      this.classList.add('active');

      // Fetch content via API endpoint
      fetch('/admin/api/' + view, {
        credentials: 'same-origin'
      })
      .then(function(resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.text();
      })
      .then(function(html) {
        contentInner.innerHTML = html;
        history.pushState({view: view}, '', href);
        // Re-init charts if Data Health view
        if (view === 'health') {
          var evt = new Event('healthViewLoaded');
          document.dispatchEvent(evt);
        }
      })
      .catch(function(err) {
        contentInner.innerHTML = '<div class="page"><div class="panel"><div style="padding:40px;text-align:center;color:var(--muted)">Failed to load view: ' + err.message + '</div></div></div>';
      });
    });
  });

  // Handle browser back/forward
  window.addEventListener('popstate', function(e) {
    if (e.state && e.state.view) {
      var view = e.state.view;
      navItems.forEach(function(n) {
        n.classList.toggle('active', n.getAttribute('data-view') === view);
      });
      fetch('/admin/api/' + view, { credentials: 'same-origin' })
      .then(function(r) { return r.text(); })
      .then(function(html) {
        contentInner.innerHTML = html;
        if (view === 'health') {
          document.dispatchEvent(new Event('healthViewLoaded'));
        }
      });
    }
  });

  // Set initial state
  history.replaceState({view: document.body.getAttribute('data-active-view')}, '');
})();
</script>"""


# -- Data Health content renderer ---------------------------------------------

def render_health_content(conn, db_status: str) -> str:
    """Render the Data Health inner content HTML (no shell)."""
    coverage = build_coverage_matrix(conn)
    scrapers  = build_scraper_health(conn)
    sources   = build_source_freshness(conn)
    quotas    = build_api_quotas(conn)
    alerts    = build_alerts(conn, coverage)
    updated   = datetime.now(_SAST).strftime("%Y-%m-%d %H:%M:%S")

    alert_count = len(alerts)

    # -- KPI metrics --
    active_scrapers = sum(1 for s in scrapers if s["css"] == "s-green")
    matches_24h     = sum(s["matches_24h"] for s in scrapers)
    total_w84       = sum(c["w84"]   for c in coverage)
    total_matches_c = sum(c["total"] for c in coverage)
    coverage_pct    = round(total_w84 / total_matches_c * 100, 1) if total_matches_c > 0 else 0

    def chip(css_key: str, text: str) -> str:
        cls = {"s-green": "chip-green", "s-amber": "chip-amber",
               "s-red": "chip-red", "s-black": "chip-gray"}.get(css_key, "chip-gray")
        return f'<span class="chip {cls}"><span class="cdot"></span>{text}</span>'

    # -- Topbar --
    db_pulse = "pulse-green" if conn else "pulse-red"
    db_color = "var(--green)" if conn else "var(--red)"
    banner = '<div class="banner banner-err">Main database unreachable -- panels showing cached/empty data</div>' if conn is None else '<div class="banner banner-ok">scrapers/odds.db connected and readable</div>'

    topbar = f"""<nav class="topbar">
  <div class="topbar-left">
    <div class="topbar-pill">Data Health</div>
  </div>
  <div class="topbar-right">
    <div class="db-status"><span class="pulse {db_pulse}"></span><span style="color:{db_color}">{db_status}</span></div>
    <div class="topbar-meta">Updated <em>{updated} SAST</em> &middot; refreshes in <em id="countdown">5:00</em></div>
  </div>
</nav>
{banner}"""

    # -- Panel 1: Coverage Matrix rows --
    p1_rows = ""
    if coverage:
        for c in coverage:
            p1_rows += (
                "<tr>"
                + td(c["sport"].capitalize())
                + td(c["league"])
                + td(c["total"])
                + td(c["w84"], "s-green" if c["w84"] > 0 else "s-black")
                + td(c["w82"], "s-red" if c["w82"] > 0 else "s-black")
                + td(c["baseline"], "s-amber" if c["baseline"] > 0 else "s-black")
                + td(f"{c['pct']}%", c["css"])
                + td(c["badge"])
                + "</tr>"
            )
    else:
        p1_rows = '<tr><td colspan="8" style="text-align:center;color:#6b7280;padding:20px">No upcoming matches in next 7 days</td></tr>'

    # -- Panel 2: Source Freshness rows --
    p2_rows = ""
    for s in sources:
        p2_rows += (
            "<tr>"
            + td(s["name"])
            + td(chip(s["css"], s["last_pull"]))
            + td(f'{s.get("records_24h", "\u2014"):,}' if isinstance(s.get("records_24h"), int) else "\u2014")
            + td(s.get("trend_7d", "\u2014"))
            + "</tr>"
        )

    # -- Panel 3: Scraper Health rows --
    p3_rows = ""
    for s in scrapers:
        p3_rows += (
            "<tr>"
            + td(s["name"])
            + td(chip(s["css"], s["last_scrape"]))
            + td(s["matches_24h"])
            + td(s["avg_odds"])
            + "</tr>"
        )

    # -- Panel 4: API Quota rows --
    p4_rows = ""
    for q in quotas:
        used    = q.get("used_today")
        limit   = q.get("daily_limit")
        remain  = q.get("remaining")
        link    = q.get("link", "#")

        used_cell   = str(used)   if used   is not None else f'<a href="{link}" target="_blank" style="color:#F8C830;font-size:11px">Check dashboard</a>'
        remain_cell = str(remain) if remain is not None else "\u2014"
        limit_cell  = str(limit)  if limit  is not None else "\u2014"

        if remain is not None and limit:
            pct = remain / limit
            rcss = "s-green" if pct > 0.5 else ("s-amber" if pct > 0.2 else "s-red")
        else:
            rcss = "s-black"

        p4_rows += (
            "<tr>"
            + td(q["api"])
            + td(q.get("plan", "\u2014"))
            + td(limit_cell)
            + td(used_cell)
            + td(remain_cell, rcss)
            + td(q.get("reset", "\u2014"))
            + "</tr>"
        )

    # -- Panel 5: Alert rows --
    p5_rows = ""
    if alerts:
        for a in alerts:
            sev_style = "color:#ef4444" if a["sev"] == "crit" else "color:#f59e0b"
            sev_icon = "&#x1F534;" if a["sev"] == "crit" else "&#x1F7E1;"
            p5_rows += (
                f'<div class="alert-row">'
                f'<span style="font-family:var(--font-m);font-size:11px;color:#6b7280">{a["ts"]}</span>'
                f'<span style="{sev_style};margin:0 8px">{sev_icon}</span>'
                f'<span>{a["msg"]}</span>'
                f'</div>'
            )
    else:
        p5_rows = '<div style="text-align:center;color:#22c55e;padding:20px">No active alerts</div>'

    # -- Chart data --
    chart_labels = json.dumps([_chart_label(c["league"]) for c in coverage])
    chart_w84    = json.dumps([c["w84"]      for c in coverage])
    chart_w82    = json.dumps([c["w82"]      for c in coverage])
    chart_base   = json.dumps([c["baseline"] for c in coverage])

    active_cls = "c-green" if active_scrapers == len(scrapers) else ("c-amber" if active_scrapers > 0 else "c-red")
    cov_cls = "c-green" if coverage_pct >= 80 else ("c-amber" if coverage_pct >= 40 else "c-red")
    alert_cls = "c-red" if alert_count > 5 else ("c-amber" if alert_count > 0 else "c-green")

    return f"""{topbar}
<div class="page">
  <div class="kpi-strip">
    <div class="kpi"><div class="kpi-lbl">Active Scrapers</div><div class="kpi-val {active_cls}">{active_scrapers}<span style="font-size:14px;color:var(--muted);font-weight:400">/{len(scrapers)}</span></div><div class="kpi-sub">bookmakers online</div></div>
    <div class="kpi"><div class="kpi-lbl">Matches Scraped</div><div class="kpi-val c-gold">{matches_24h:,}</div><div class="kpi-sub">last 24 hours</div></div>
    <div class="kpi"><div class="kpi-lbl">Narrative Coverage</div><div class="kpi-val {cov_cls}">{coverage_pct}<span style="font-size:14px;color:var(--muted);font-weight:400">%</span></div><div class="kpi-sub">w84 AI-enriched</div></div>
    <div class="kpi"><div class="kpi-lbl">Active Alerts</div><div class="kpi-val {alert_cls}">{alert_count}</div><div class="kpi-sub">pipeline issues</div></div>
    <div class="kpi"><div class="kpi-lbl">Leagues Tracked</div><div class="kpi-val c-text">{total_matches_c}</div><div class="kpi-sub">upcoming matches (7d)</div></div>
  </div>

  <div class="panel">
    <div class="panel-head"><span class="panel-title">Sport Coverage Matrix</span><span class="panel-sub">Next 7 days &middot; w84 = AI-enriched &middot; w82 = Template &middot; Baseline = No edge data</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Sport</th><th>League</th><th>Matches</th><th>w84 (AI)</th><th>w82 (Template)</th><th>Baseline</th><th>Coverage %</th><th>Status</th></tr></thead><tbody>{p1_rows}</tbody></table></div>
    <div class="chart-wrap"><canvas id="coverageChart"></canvas></div>
  </div>

  <div class="grid-2">
    <div class="panel"><div class="panel-head"><span class="panel-title">Data Source Freshness</span><span class="panel-sub">&lt;1h &middot; 1-6h &middot; &gt;6h</span></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Source</th><th>Last Pull</th><th>Records (24h)</th><th>7d</th></tr></thead><tbody>{p2_rows}</tbody></table></div>
    </div>
    <div class="panel"><div class="panel-head"><span class="panel-title">Scraper Health</span><span class="panel-sub">8 SA bookmakers &middot; last 24h</span></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Bookmaker</th><th>Last Scrape</th><th>Matches (24h)</th><th>Avg Odds/Match</th></tr></thead><tbody>{p3_rows}</tbody></table></div>
    </div>
    <div class="panel"><div class="panel-head"><span class="panel-title">API Quota Tracker</span><span class="panel-sub">Live from DB &middot; refreshes every 60s</span></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>API</th><th>Plan</th><th>Daily Limit</th><th>Used Today</th><th>Remaining</th><th>Reset</th></tr></thead><tbody>{p4_rows}</tbody></table></div>
    </div>
    <div class="panel"><div class="panel-head"><span class="panel-title">Alert Log{'<span class="alert-badge">' + str(alert_count) + '</span>' if alert_count else ''}</span><span class="panel-sub">Last 48h &middot; scrapers / coverage / pipeline</span></div>
      <div class="alerts-scroll">{p5_rows}</div>
    </div>
  </div>

  <div class="footer">Auto-refreshes in <span id="countdown2">5:00</span> &middot; MzansiEdge Ops &middot; Read-only</div>
</div>

<script>
(function initHealthCharts() {{
  var labels  = {chart_labels};
  var w84Data = {chart_w84};
  var w82Data = {chart_w82};
  var baseData= {chart_base};
  var ctx = document.getElementById('coverageChart');
  if (!ctx || !labels.length) return;
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [
        {{ label: 'w84 (AI-enriched)', data: w84Data, backgroundColor: 'rgba(34,197,94,0.8)', borderRadius: 4 }},
        {{ label: 'w82 (Template)',    data: w82Data, backgroundColor: 'rgba(239,68,68,0.65)',  borderRadius: 4 }},
        {{ label: 'Baseline',          data: baseData, backgroundColor: 'rgba(245,158,11,0.5)', borderRadius: 4 }},
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ labels: {{ color: '#9ca3af', font: {{ size: 11, family: "'Work Sans'" }} }} }},
        tooltip: {{ backgroundColor: '#161616', titleColor: '#F5F5F5', bodyColor: '#9ca3af', borderColor: '#1f1f1f', borderWidth: 1, padding: 10 }}
      }},
      scales: {{
        x: {{ stacked: true, ticks: {{ color: '#6b7280', font: {{ size: 10 }} }}, grid: {{ color: '#1a1a1a' }} }},
        y: {{ stacked: true, ticks: {{ color: '#6b7280', font: {{ size: 10 }}, stepSize: 1 }}, grid: {{ color: '#1a1a1a' }} }}
      }}
    }}
  }});
}})();
document.addEventListener('healthViewLoaded', function() {{
  setTimeout(function() {{
    var labels  = {chart_labels};
    var w84Data = {chart_w84};
    var w82Data = {chart_w82};
    var baseData= {chart_base};
    var ctx = document.getElementById('coverageChart');
    if (!ctx || !labels.length) return;
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: labels,
        datasets: [
          {{ label: 'w84 (AI-enriched)', data: w84Data, backgroundColor: 'rgba(34,197,94,0.8)', borderRadius: 4 }},
          {{ label: 'w82 (Template)',    data: w82Data, backgroundColor: 'rgba(239,68,68,0.65)',  borderRadius: 4 }},
          {{ label: 'Baseline',          data: baseData, backgroundColor: 'rgba(245,158,11,0.5)', borderRadius: 4 }},
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ labels: {{ color: '#9ca3af', font: {{ size: 11, family: "'Work Sans'" }} }} }},
          tooltip: {{ backgroundColor: '#161616', titleColor: '#F5F5F5', bodyColor: '#9ca3af', borderColor: '#1f1f1f', borderWidth: 1, padding: 10 }}
        }},
        scales: {{
          x: {{ stacked: true, ticks: {{ color: '#6b7280', font: {{ size: 10 }} }}, grid: {{ color: '#1a1a1a' }} }},
          y: {{ stacked: true, ticks: {{ color: '#6b7280', font: {{ size: 10 }}, stepSize: 1 }}, grid: {{ color: '#1a1a1a' }} }}
        }}
      }}
    }});
  }}, 100);
}});

(function() {{
  var secs = 300;
  function tick() {{
    secs--;
    if (secs <= 0) {{ location.reload(); return; }}
    var m = Math.floor(secs / 60), s = secs % 60;
    var txt = m + ':' + (s < 10 ? '0' : '') + s;
    var el1 = document.getElementById('countdown');
    var el2 = document.getElementById('countdown2');
    if (el1) el1.textContent = txt;
    if (el2) el2.textContent = txt;
  }}
  setInterval(tick, 1000);
}})();
</script>"""


# -- Automation content renderer ----------------------------------------------

def render_automation_content() -> str:
    """Render the Automation view inner content HTML."""
    notion_ok = True
    cache_age_str = ""

    try:
        items, fetch_time = _fetch_marketing_queue()
        cache_age_min = (time.monotonic() - fetch_time) / 60
        if cache_age_min > 2:
            cache_age_str = f"Showing cached data ({cache_age_min:.0f}m ago)"
    except Exception:
        items = []
        notion_ok = False
        # Try to get from cache
        with _notion_cache_lock:
            cached = _notion_cache.get("marketing_queue")
            if cached:
                items = cached[0]
                cache_age_min = (time.monotonic() - cached[1]) / 60
                cache_age_str = f"Notion unavailable -- showing cached data ({cache_age_min:.0f}m ago)"
            else:
                cache_age_str = "Notion unavailable -- no cached data"

    now_utc = datetime.now(timezone.utc)
    now_sast = now_utc.astimezone(_SAST)
    today_str = now_sast.strftime("%Y-%m-%d")
    updated = now_sast.strftime("%Y-%m-%d %H:%M:%S")

    # Categorise items
    published_today = []
    scheduled = []
    awaiting_approval = []
    failed_blocked = []
    recent_publishes = []
    all_active = []

    for item in items:
        status = (item.get("status") or "").lower().strip()
        sched_raw = item.get("scheduled_time") or ""

        if status in ("published", "done", "complete"):
            # Check if published today
            created = item.get("last_edited") or item.get("created") or ""
            if created and today_str in created[:10]:
                published_today.append(item)
            # All published in last 24h
            dt = parse_ts(created or item.get("scheduled_time"))
            if dt and (now_utc - dt).total_seconds() < 86400:
                recent_publishes.append(item)
        elif status in ("failed", "blocked", "error"):
            failed_blocked.append(item)
        elif status in ("approved", "ready", "scheduled"):
            # Future scheduled
            sched_dt = parse_ts(sched_raw)
            if sched_dt and sched_dt > now_utc:
                scheduled.append(item)
            elif sched_dt:
                # Past scheduled but not published -- treat as awaiting
                awaiting_approval.append(item)
            else:
                scheduled.append(item)
        elif status in ("awaiting approval", "draft", "review", "pending", "in review", "awaiting", "in progress"):
            awaiting_approval.append(item)

        if status not in ("published", "done", "complete", "archived"):
            all_active.append(item)

    # Sort
    scheduled.sort(key=lambda x: x.get("scheduled_time") or "9999")
    awaiting_approval.sort(key=lambda x: x.get("created") or "0000")
    recent_publishes.sort(key=lambda x: x.get("last_edited") or x.get("created") or "9999", reverse=True)

    # -- Channel stats --
    channel_stats: dict[str, dict] = {}
    for ch in _CHANNELS:
        channel_stats[ch["key"]] = {
            "last_published": None,
            "last_published_ts": None,
            "published_today": 0,
            "next_scheduled": None,
            "next_scheduled_ts": None,
            "queue_depth": 0,
            "last_failed": False,
        }

    for item in items:
        ch_key = _normalise_channel_key(item.get("channel") or "")
        if not ch_key or ch_key not in channel_stats:
            continue
        status = (item.get("status") or "").lower().strip()
        ts_raw = item.get("last_edited") or item.get("scheduled_time") or item.get("created") or ""

        if status in ("published", "done", "complete"):
            dt = parse_ts(ts_raw)
            if dt:
                if channel_stats[ch_key]["last_published_ts"] is None or dt > channel_stats[ch_key]["last_published_ts"]:
                    channel_stats[ch_key]["last_published_ts"] = dt
                    channel_stats[ch_key]["last_published"] = ts_raw
                if today_str in ts_raw[:10]:
                    channel_stats[ch_key]["published_today"] += 1
        elif status in ("failed", "blocked", "error"):
            channel_stats[ch_key]["last_failed"] = True
        elif status not in ("archived",):
            channel_stats[ch_key]["queue_depth"] += 1

        if status in ("approved", "ready", "scheduled"):
            sched = item.get("scheduled_time") or ""
            sched_dt = parse_ts(sched)
            if sched_dt and sched_dt > now_utc:
                if channel_stats[ch_key]["next_scheduled_ts"] is None or sched_dt < channel_stats[ch_key]["next_scheduled_ts"]:
                    channel_stats[ch_key]["next_scheduled_ts"] = sched_dt
                    channel_stats[ch_key]["next_scheduled"] = sched

    def _channel_chip(ch_key: str) -> str:
        ch = _CHANNEL_MAP.get(ch_key)
        if not ch:
            return f'<span class="ch-chip" style="background:rgba(107,114,128,0.15);color:var(--muted)">{ch_key}</span>'
        return f'<span class="ch-chip" style="background:{ch["color"]}22;color:{ch["color"]};border:1px solid {ch["color"]}33"><span class="ch-dot" style="background:{ch["color"]}"></span>{ch["label"]}</span>'

    def _status_chip(status: str) -> str:
        low = status.lower().strip()
        if low in ("published", "done", "complete"):
            return '<span class="chip chip-green"><span class="cdot"></span>Published</span>'
        elif low in ("approved", "ready", "scheduled"):
            return '<span class="chip chip-amber"><span class="cdot"></span>Scheduled</span>'
        elif low in ("failed", "blocked", "error"):
            return '<span class="chip chip-red"><span class="cdot"></span>Failed</span>'
        elif low in ("awaiting approval", "draft", "review", "pending", "in review", "awaiting", "in progress"):
            return '<span class="chip chip-gray"><span class="cdot"></span>Awaiting</span>'
        return f'<span class="chip chip-gray"><span class="cdot"></span>{status}</span>'

    # -- Topbar --
    banner = ""
    if cache_age_str:
        banner = f'<div class="banner banner-warn">{cache_age_str}</div>'
    elif not notion_ok:
        banner = '<div class="banner banner-err">Notion unavailable -- no cached data</div>'

    topbar = f"""<nav class="topbar">
  <div class="topbar-left"><div class="topbar-pill">Automation</div></div>
  <div class="topbar-right"><div class="topbar-meta">Updated <em>{updated} SAST</em></div></div>
</nav>
{banner}"""

    # -- Panel 1: Pipeline KPI Strip --
    pub_today_count = len(published_today)
    scheduled_count = len(scheduled)
    awaiting_count = len(awaiting_approval)
    failed_count = len(failed_blocked)
    total_queue = len(all_active)

    pub_cls = "c-green" if pub_today_count > 0 else "c-text"
    sched_cls = "c-gold"
    await_cls = "c-amber" if awaiting_count > 0 else "c-text"
    fail_cls = "c-red" if failed_count > 0 else "c-text"

    kpi_strip = f"""<div class="kpi-strip">
    <div class="kpi"><div class="kpi-lbl">Published Today</div><div class="kpi-val {pub_cls}">{pub_today_count}</div><div class="kpi-sub">posts sent</div></div>
    <div class="kpi"><div class="kpi-lbl">Scheduled</div><div class="kpi-val {sched_cls}">{scheduled_count}</div><div class="kpi-sub">approved &amp; queued</div></div>
    <div class="kpi"><div class="kpi-lbl">Awaiting Approval</div><div class="kpi-val {await_cls}">{awaiting_count}</div><div class="kpi-sub">needs review</div></div>
    <div class="kpi"><div class="kpi-lbl">Failed / Blocked</div><div class="kpi-val {fail_cls}">{failed_count}</div><div class="kpi-sub">{"action needed" if failed_count > 0 else "all clear"}</div></div>
    <div class="kpi"><div class="kpi-lbl">Total Queue</div><div class="kpi-val c-text">{total_queue}</div><div class="kpi-sub">active items</div></div>
  </div>"""

    # -- Panel 2: Channel Status Grid --
    channel_cards = ""
    for ch in _CHANNELS:
        cs = channel_stats[ch["key"]]
        # Status dot
        last_ts = cs.get("last_published_ts")
        if cs["last_failed"]:
            dot_color = "var(--red)"
            dot_title = "Last action failed"
        elif last_ts:
            age_h = (now_utc - last_ts).total_seconds() / 3600
            if age_h < 6:
                dot_color = "var(--green)"
                dot_title = "Active (< 6h)"
            elif age_h < 24:
                dot_color = "var(--amber)"
                dot_title = "Stale (6-24h)"
            else:
                dot_color = "var(--red)"
                dot_title = "Inactive (> 24h)"
        else:
            dot_color = "var(--muted)"
            dot_title = "No publishes yet"

        last_pub_str = _relative_time(cs["last_published"]) if cs["last_published"] else '<span style="color:var(--muted)">No publishes yet</span>'
        next_sched_str = _sast_hhmm(cs["next_scheduled"]) + " SAST" if cs["next_scheduled"] else "\u2014"
        accent_cls = ""
        if cs["next_scheduled_ts"]:
            mins_until = (cs["next_scheduled_ts"] - now_utc).total_seconds() / 60
            if 0 < mins_until < 60:
                accent_cls = " panel-orange-accent"

        channel_cards += f"""<div class="channel-card{accent_cls}">
  <div class="channel-card-head"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot_color}" title="{dot_title}"></span><span class="channel-card-name" style="color:{ch['color']}">{ch['label']}</span></div>
  <div class="channel-card-stat">Last published: <em>{last_pub_str}</em></div>
  <div class="channel-card-stat">Published today: <em>{cs['published_today']}</em></div>
  <div class="channel-card-stat">Next scheduled: <em>{next_sched_str}</em></div>
  <div class="channel-card-stat">Queue depth: <em>{cs['queue_depth']}</em></div>
</div>"""

    channel_panel = f"""<div class="panel">
    <div class="panel-head"><span class="panel-title">Channel Status</span><span class="panel-sub">7 channels &middot; last publish freshness</span></div>
    <div class="channel-grid">{channel_cards}</div>
  </div>"""

    # -- Panel 3: Upcoming Queue (max 20) --
    upcoming_html = ""
    if scheduled:
        rows = ""
        for item in scheduled[:20]:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            rows += (
                "<tr>"
                + td(_sast_hhmm(item.get("scheduled_time")))
                + td(_channel_chip(ch_key))
                + td(_truncate(item.get("title"), 50))
                + td(_truncate(item.get("copy"), 80), extra_style="color:var(--muted)")
                + td("+" if item.get("asset") else "\u2014")
                + td(_status_chip(item.get("status") or ""))
                + "</tr>"
            )
        upcoming_html = f"""<div class="panel">
    <div class="panel-head"><span class="panel-title">Upcoming Queue</span><span class="panel-sub">{len(scheduled)} scheduled</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Time</th><th>Channel</th><th>Title</th><th>Copy Preview</th><th>Asset</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>
  </div>"""

    # -- Panel 4: Awaiting Approval --
    awaiting_html = ""
    if awaiting_approval:
        rows = ""
        for item in awaiting_approval:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            created = item.get("created") or ""
            age_str = _relative_time(created)
            # Colour age
            dt = parse_ts(created)
            age_style = ""
            if dt:
                age_h = (now_utc - dt).total_seconds() / 3600
                if age_h > 24:
                    age_style = "color:var(--red);font-weight:700"
                elif age_h > 12:
                    age_style = "color:var(--amber);font-weight:700"

            rows += (
                "<tr>"
                + td(_channel_chip(ch_key))
                + td(_truncate(item.get("title"), 50))
                + td(_truncate(item.get("copy"), 120), extra_style="color:var(--muted)")
                + td("+" if item.get("asset") else "\u2014")
                + td(_relative_time(created))
                + td(age_str, extra_style=age_style)
                + "</tr>"
            )
        awaiting_html = f"""<div class="panel">
    <div class="panel-head"><span class="panel-title">Awaiting Approval</span><span class="panel-sub">{len(awaiting_approval)} items &middot; oldest first</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Channel</th><th>Title</th><th>Copy Preview</th><th>Asset</th><th>Created</th><th>Age</th></tr></thead><tbody>{rows}</tbody></table></div>
  </div>"""

    # -- Panel 5: Recent Publishes (last 24h, max 30) --
    recent_html = ""
    if recent_publishes:
        rows = ""
        for item in recent_publishes[:30]:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            ts = item.get("last_edited") or item.get("scheduled_time") or item.get("created") or ""
            url = item.get("url") or ""
            url_cell = f'<a href="{url}" target="_blank" style="color:var(--gold);font-size:11px">View</a>' if url else "\u2014"
            rows += (
                "<tr>"
                + td(_sast_hhmm(ts))
                + td(_channel_chip(ch_key))
                + td(_truncate(item.get("title"), 50))
                + td(url_cell)
                + td(_truncate(item.get("copy"), 60), extra_style="color:var(--muted)")
                + "</tr>"
            )
        recent_html = f"""<div class="panel">
    <div class="panel-head"><span class="panel-title">Recent Publishes</span><span class="panel-sub">Last 24h &middot; {len(recent_publishes)} items</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Time</th><th>Channel</th><th>Title</th><th>URL</th><th>Copy Preview</th></tr></thead><tbody>{rows}</tbody></table></div>
  </div>"""

    # -- Panel 6: Failed & Blocked --
    failed_html = ""
    if failed_blocked:
        rows = ""
        for item in failed_blocked:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            rows += (
                "<tr>"
                + td(_channel_chip(ch_key))
                + td(_truncate(item.get("title"), 50))
                + td(_status_chip(item.get("status") or ""))
                + td(_truncate(item.get("error"), 80) or "\u2014", extra_style="color:var(--red)")
                + td(_sast_hhmm(item.get("scheduled_time")))
                + td(_relative_time(item.get("created")))
                + "</tr>"
            )
        failed_html = f"""<div class="panel panel-red-accent">
    <div class="panel-head"><span class="panel-title" style="color:var(--red)">Failed &amp; Blocked</span><span class="panel-sub">{len(failed_blocked)} items need attention</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Channel</th><th>Title</th><th>Status</th><th>Error / Reason</th><th>Scheduled</th><th>Age</th></tr></thead><tbody>{rows}</tbody></table></div>
  </div>"""

    return f"""{topbar}
<div class="page">
  {kpi_strip}
  {channel_panel}
  {failed_html}
  {upcoming_html}
  {awaiting_html}
  {recent_html}
  <div class="footer">MzansiEdge Automation &middot; Notion-powered</div>
</div>"""


# -- Customers placeholder ----------------------------------------------------

def render_customers_content() -> str:
    """Render the Customers placeholder content."""
    topbar = """<nav class="topbar">
  <div class="topbar-left"><div class="topbar-pill">Customers</div></div>
  <div class="topbar-right"></div>
</nav>"""

    users_icon_large = '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'

    return f"""{topbar}
<div class="coming-soon">
  {users_icon_large}
  <h2>Coming Soon</h2>
  <p>Customer analytics and user management will appear here.</p>
</div>"""


# -- Shell renderer -----------------------------------------------------------

def render_shell(active_view: str, content_html: str) -> str:
    """Wrap content in the full page shell with sidebar, head, and scripts."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MzansiEdge — Admin Panel</title>
<link rel="icon" type="image/x-icon" href="https://mzansiedge.co.za/favicon.ico">
<link rel="icon" type="image/png" sizes="192x192" href="https://mzansiedge.co.za/favicon-192.png">
<link rel="apple-touch-icon" href="https://mzansiedge.co.za/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Work+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{_shared_css()}</style>
</head>
<body data-active-view="{active_view}">
{_sidebar_html(active_view)}
<div class="content-area" id="contentArea">
  <div id="contentInner">{content_html}</div>
</div>
{_sidebar_js()}
</body>
</html>"""


# -- Flask routes -------------------------------------------------------------

# Full-page routes (first load / direct navigation)

@app.route("/admin/health")
@require_auth
def admin_health():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("health_full")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    conn = db_connect(SCRAPERS_DB)
    db_status = "Connected" if conn else "Unreachable"
    try:
        content = render_health_content(conn, db_status)
    finally:
        if conn:
            conn.close()

    html = render_shell("health", content)

    with _page_cache_lock:
        _page_cache["health_full"] = (html, now)

    return Response(html, mimetype="text/html")


@app.route("/admin/automation")
@require_auth
def admin_automation():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("automation_full")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    content = render_automation_content()
    html = render_shell("automation", content)

    with _page_cache_lock:
        _page_cache["automation_full"] = (html, now)

    return Response(html, mimetype="text/html")


@app.route("/admin/customers")
@require_auth
def admin_customers():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("customers_full")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    content = render_customers_content()
    html = render_shell("customers", content)

    with _page_cache_lock:
        _page_cache["customers_full"] = (html, now)

    return Response(html, mimetype="text/html")


# AJAX content-only routes (for sidebar navigation without full page reload)

@app.route("/admin/api/health")
@require_auth
def api_health():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("health_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    conn = db_connect(SCRAPERS_DB)
    db_status = "Connected" if conn else "Unreachable"
    try:
        content = render_health_content(conn, db_status)
    finally:
        if conn:
            conn.close()

    with _page_cache_lock:
        _page_cache["health_content"] = (content, now)

    return Response(content, mimetype="text/html")


@app.route("/admin/api/automation")
@require_auth
def api_automation():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("automation_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    content = render_automation_content()

    with _page_cache_lock:
        _page_cache["automation_content"] = (content, now)

    return Response(content, mimetype="text/html")


@app.route("/admin/api/customers")
@require_auth
def api_customers():
    content = render_customers_content()
    return Response(content, mimetype="text/html")


# Redirects

@app.route("/ops/health")
@require_auth
def ops_health_redirect():
    return redirect("/admin/health", code=302)


@app.route("/")
@require_auth
def root():
    return redirect("/admin/health", code=302)


# Unauthenticated health check

@app.route("/healthz")
def healthz():
    """Unauthenticated health check for monitoring."""
    return Response("ok", mimetype="text/plain")


# -- Entry point --------------------------------------------------------------

if __name__ == "__main__":
    print(f"MzansiEdge Admin Panel starting on port {PORT}")
    print(f"  URL:  http://localhost:{PORT}/admin/health")
    print(f"  Auth: {DASHBOARD_USER}:***")
    print(f"  DB:   {SCRAPERS_DB}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
