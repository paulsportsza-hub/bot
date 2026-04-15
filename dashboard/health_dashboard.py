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
import re
import sqlite3
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

from flask import Flask, Response, request, redirect

try:
    import sentry_sdk as _sentry
except ImportError:
    _sentry = None  # type: ignore[assignment]

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
ENRICHMENT_DB = os.path.expanduser("~/scrapers/enrichment.db")
COMBAT_DB = os.path.expanduser("~/bot/data/combat_data.db")
QUOTAS_FILE = os.path.join(os.path.dirname(__file__), "api_quotas.json")

# Billing alert config
_BILLING_PATTERNS = [
    "credit balance", "payment required", "quota exceeded",
    "billing", "402", "insufficient credits", "plan limit", "api key",
]
_BILLING_URLS = {
    "anthropic":    "https://console.anthropic.com/settings/billing",
    "openrouter":   "https://openrouter.ai/settings/credits",
    "the_odds_api": "https://the-odds-api.com/account",
    "api-football": "https://dashboard.api-football.com",
}

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "mzansiedge")
PORT = int(os.getenv("DASHBOARD_PORT", "8501"))

NOTION_TOKEN = os.getenv(
    "NOTION_TOKEN",
    "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",
)
NOTION_MARKETING_DB = "58123052-0e48-466a-be63-5308e793e672"
NOTION_TASK_HUB_PAGE = "31ed9048-d73c-814e-a179-ccd2cf35df1d"

# -- Sentry config ------------------------------------------------------------
SENTRY_AUTH_TOKEN = os.getenv("SENTRY_AUTH_TOKEN", "")
SENTRY_ORG = "mzansi-edge"
SENTRY_PROJECT = "mzansi-edge"
# AC-8: Use DE region endpoint — project DSN is ingest.de.sentry.io, not sentry.io (US).
# Global sentry.io endpoint returns X-Hits counts that ignore the is:unresolved filter,
# causing the widget to show total-issue count (e.g. 16) even when 0 are unresolved.
_SENTRY_API = "https://de.sentry.io/api/0"

# -- System Health cache (Sentry + server metrics) ----------------------------
_system_health_cache: dict = {}
_system_health_cache_lock = threading.Lock()
_SYSTEM_HEALTH_TTL = 60  # seconds

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
    {"key": "telegram_alerts", "label": "Telegram Alerts", "color": "#26A5E4"},
    {"key": "telegram_community", "label": "Telegram Community", "color": "#179CDE"},
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
        return "s-grey", "Never"
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if age_h < 1:
        mins = int(age_h * 60)
        return "s-green", f"{mins}m ago"
    elif age_h < 6:
        return "s-amber", f"{age_h:.1f}h ago"
    else:
        return "s-red", f"{age_h:.1f}h ago"


def _is_offpeak() -> bool:
    """True during weekend (Sat/Sun) or off-peak hours (22:00-06:00 SAST)."""
    now_sast = datetime.now(_SAST)
    if now_sast.weekday() >= 5:  # Sat=5, Sun=6
        return True
    return now_sast.hour >= 22 or now_sast.hour < 6


def freshness_rag(ts_str, cycle_minutes: int = 60, offpeak_relaxed: bool = False) -> tuple:
    """RAG freshness with service-type-aware thresholds (AC-4, AC-6).

    cycle_minutes=0 -> GREY (on-demand)
    offpeak_relaxed=True -> 2x thresholds (AC-6)
    """
    if cycle_minutes == 0:
        return "s-grey", "On-demand — idle"
    dt = parse_ts(ts_str)
    if dt is None:
        return "s-grey", "No data"  # never ran — show grey not red
    age_m = (datetime.now(timezone.utc) - dt).total_seconds() / 60
    mult = 2 if offpeak_relaxed else 1
    green_max = cycle_minutes * mult
    amber_max = cycle_minutes * 2 * mult
    if age_m < green_max:
        return "s-green", (f"{int(age_m)}m ago" if age_m < 60 else f"{age_m/60:.1f}h ago")
    elif age_m < amber_max:
        return "s-amber", f"{age_m/60:.1f}h ago"
    else:
        return "s-red", f"{age_m/60:.1f}h ago"


def coverage_badge(pct: float) -> tuple[str, str]:
    if pct >= 90:
        return "s-green", "Healthy"
    elif pct >= 50:
        return "s-amber", "Degraded"
    elif pct > 0:
        return "s-red", "Critical"
    else:
        return "s-grey", "No Data"


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
    # Card-ready = match has odds from >= 2 distinct SA bookmakers in last 7 days.
    # This replaces the old narrative_source (w84/w82) approach — card data
    # availability is the correct metric for the image-card system.
    rows = q_all(conn, """
        SELECT u.sport, u.league,
            COUNT(DISTINCT u.match_id)                                        AS total,
            SUM(CASE WHEN u.bk_count >= 2 THEN 1 ELSE 0 END)                 AS card_ready
        FROM (
            SELECT match_id, sport, league,
                   COUNT(DISTINCT bookmaker)                                   AS bk_count
            FROM   odds_snapshots
            WHERE  scraped_at >= datetime('now', '-7 days')
            GROUP BY match_id, sport, league
        ) u
        GROUP BY u.sport, u.league
        ORDER BY u.sport, u.league
    """)
    out = []
    for r in rows:
        total      = r["total"]      or 0
        card_ready = r["card_ready"] or 0
        pct        = (card_ready / total * 100) if total > 0 else 0
        css, badge = coverage_badge(pct)
        out.append({
            "sport":      r["sport"],
            "league":     r["league"].upper().replace("_", " "),
            "total":      total,
            "card_ready": card_ready,
            "needs_data": total - card_ready,
            "pct":        round(pct, 1),
            "css":        css,
            "badge":      badge,
        })

    # -- Rugby watchlist: URC / Varsity Cup / Currie Cup visibility -----------
    _RUGBY_WATCHLIST = [
        ("urc",     "URC"),
        ("varsity",  "Varsity Cup"),
        ("currie",   "Currie Cup"),
    ]

    all_rugby_rows = q_all(conn, """
        SELECT DISTINCT league FROM odds_snapshots
        WHERE league IN ('super_rugby','urc','currie_cup','varsity_cup',
                         'international_rugby','rugby_championship','six_nations')
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
            "sport":      "rugby",
            "league":     display,
            "total":      0,
            "card_ready": 0,
            "needs_data": 0,
            "pct":        0.0,
            "css":        "s-grey",
            "badge":      badge,
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
        out.append({"name": "SA Bookmakers (8x)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

    # The Odds API (sharp)
    if table_exists(conn, "sharp_odds"):
        r = q_one(conn, "SELECT MAX(scraped_at) as last FROM sharp_odds")
        c = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-24 hours')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-14 days') AND scraped_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        row("The Odds API (Sharp)", r["last"] if r else None, (c["c"] if c else 0), trend)
    else:
        out.append({"name": "The Odds API (Sharp)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

    # ESPN — data lands in match_results via elo/glicko update_daily (not espn_stats_cache)
    if table_exists(conn, "match_results"):
        r   = q_one(conn, "SELECT MAX(created_at) as last FROM match_results WHERE source='espn'")
        c24 = q_one(conn, "SELECT COUNT(*) as c FROM match_results WHERE source='espn' AND created_at >= datetime('now','-24 hours')")
        c7  = q_one(conn, "SELECT COUNT(*) as c FROM match_results WHERE source='espn' AND created_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM match_results WHERE source='espn' AND created_at >= datetime('now','-14 days') AND created_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        row("ESPN Hidden API", r["last"] if r else None, c24["c"] if c24 else 0, trend)
    else:
        out.append({"name": "ESPN Hidden API", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

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
            out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
    else:
        out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

    # Narrative cache
    if table_exists(conn, "narrative_cache"):
        r = q_one(conn, "SELECT MAX(created_at) as last FROM narrative_cache")
        c = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-24 hours')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-14 days') AND created_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        row("Narrative Cache", r["last"] if r else None, c["c"] if c else 0, trend)
    else:
        out.append({"name": "Narrative Cache", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

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
            out.append({"name": "API-Sports MMA", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
    else:
        out.append({"name": "API-Sports MMA", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

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
            out.append({"name": "API-Sports Rugby", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
    else:
        out.append({"name": "API-Sports Rugby", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

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
            out.append({"name": "Sportmonks Cricket", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
    else:
        out.append({"name": "Sportmonks Cricket", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})


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
        out.append({"name": "Tipster Sources", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

    # Enrichment DB (weather + news) — AC-7
    enr_conn = db_connect(ENRICHMENT_DB)
    if enr_conn:
        try:
            offpeak = _is_offpeak()
            wr = enr_conn.execute(
                "SELECT MAX(scraped_at) as last, COUNT(*) as c FROM weather_forecasts "
                "WHERE scraped_at >= datetime('now','-24 hours')"
            ).fetchone()
            nr = enr_conn.execute(
                "SELECT MAX(scraped_at) as last, COUNT(*) as c FROM news_articles "
                "WHERE scraped_at >= datetime('now','-24 hours')"
            ).fetchone()
            w_css, w_lbl = freshness_rag(wr["last"] if wr else None, 1440, offpeak)
            n_css, n_lbl = freshness_rag(nr["last"] if nr else None, 1440, offpeak)
            out.append({"name": "Weather Forecasts", "last_pull": w_lbl, "records_24h": wr["c"] if wr else 0, "css": w_css, "trend_7d": "enrichment"})
            out.append({"name": "News Articles", "last_pull": n_lbl, "records_24h": nr["c"] if nr else 0, "css": n_css, "trend_7d": "enrichment"})
        except Exception:
            out.append({"name": "Weather Forecasts", "last_pull": "Error", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
            out.append({"name": "News Articles", "last_pull": "Error", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
        finally:
            enr_conn.close()
    else:
        out.append({"name": "Weather Forecasts", "last_pull": "Not found", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
        out.append({"name": "News Articles", "last_pull": "Not found", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

    # Combat data DB (may not exist) — AC-7
    if os.path.exists(COMBAT_DB):
        cbt_conn = db_connect(COMBAT_DB)
        if cbt_conn:
            try:
                cr = cbt_conn.execute(
                    "SELECT MAX(scraped_at) as last, COUNT(*) as c FROM fighter_records "
                    "WHERE scraped_at >= datetime('now','-24 hours')"
                ).fetchone()
                c_css, c_lbl = freshness_rag(cr["last"] if cr else None, 1440, _is_offpeak())
                out.append({"name": "MMA Fighter Records", "last_pull": c_lbl, "records_24h": cr["c"] if cr else 0, "css": c_css, "trend_7d": "combat"})
            except Exception:
                out.append({"name": "MMA Fighter Records", "last_pull": "No table", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
            finally:
                cbt_conn.close()
        else:
            out.append({"name": "MMA Fighter Records", "last_pull": "Not connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
    else:
        out.append({"name": "MMA Fighter Records", "last_pull": "Not found", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

    # Bot state DB (mzansiedge.db) — AC-7
    bot_conn = db_connect(BOT_DB)
    if bot_conn:
        try:
            ur = bot_conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN is_active=1 OR is_active IS NULL THEN 1 ELSE 0 END) as active "
                "FROM users"
            ).fetchone()
            sr = bot_conn.execute(
                "SELECT COUNT(*) as subs FROM users WHERE subscription_status='active'"
            ).fetchone()
            total_users = ur["total"] if ur else 0
            active_users = ur["active"] if ur else 0
            subs = sr["subs"] if sr else 0
            out.append({
                "name": f"Bot Users ({total_users} total, {subs} subscribers)",
                "last_pull": "Live",
                "records_24h": active_users,
                "css": "s-green",
                "trend_7d": "bot",
            })
        except Exception:
            out.append({"name": "Bot Users", "last_pull": "Error", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
        finally:
            bot_conn.close()
    else:
        out.append({"name": "Bot Users", "last_pull": "Not connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

    return out


def build_scraper_health(conn) -> list[dict]:
    if not table_exists(conn, "odds_snapshots"):
        return [{"name": BK_DISPLAY[b], "last_scrape": "Not Connected", "matches_24h": 0, "avg_odds": 0, "css": "s-grey"} for b in BOOKMAKERS]
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
            css, lbl = freshness_rag(r["last"], cycle_minutes=180, offpeak_relaxed=True)
            out.append({
                "name":       BK_DISPLAY[bk],
                "last_scrape": lbl,
                "matches_24h": r["matches"] or 0,
                "avg_odds":    round(r["avg_odds"] or 0, 1),
                "css":         css,
                "has_data_24h": True,
            })
        else:
            out.append({
                "name":       BK_DISPLAY[bk],
                "last_scrape": "No data (24h)",
                "matches_24h": 0,
                "avg_odds":    0,
                "css":         "s-red",
                "has_data_24h": False,
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

    # -- OpenRouter (image generation balance) --
    or_balance_usd = None
    or_total_credits = None
    or_pct_used = None
    or_checked_at = None
    if conn:
        try:
            row = conn.execute("""
                SELECT credits_remaining, credits_limit, pct_used, checked_at, meta
                FROM api_quota_tracking
                WHERE api_name = 'openrouter'
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            if row:
                or_balance_usd = (row["credits_remaining"] or 0) / 100
                or_total_credits = (row["credits_limit"] or 0) / 100
                or_pct_used = row["pct_used"]
                or_checked_at = row["checked_at"]
        except Exception:
            pass

    if or_balance_usd is not None:
        low = or_balance_usd < 3.0
        quotas.append({
            "api": "OpenRouter",
            "plan": "TopUp",
            "daily_limit": None,
            "used_today": None,
            "remaining": f"${or_balance_usd:.2f}",
            "reset": "Top-up required" if low else "—",
            "_balance_usd": or_balance_usd,
            "_low": low,
            "_checked_at": or_checked_at,
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

    # Sports with 0% card data coverage (use pre-computed coverage)
    for c in coverage:
        if c["total"] > 0 and c["card_ready"] == 0:
            alerts.append({
                "ts": now_str, "sev": "warn",
                "msg": f"Zero card data -- {c['sport'].upper()} / {c['league']}: {c['total']} matches, no multi-bookmaker coverage",
            })

    # LinkedIn / Facebook token expiry warnings (60-day cycle)
    _publisher_env = os.path.join(os.path.dirname(__file__), "..", "..", "publisher", ".env")
    _token_pairs = [
        ("LINKEDIN_TOKEN_ISSUED_AT", "LinkedIn OAuth2 token"),
        ("FACEBOOK_TOKEN_ISSUED_AT", "Facebook page access token"),
    ]
    _pub_env_vals: dict[str, str] = {}
    try:
        with open(_publisher_env) as _pf:
            for _line in _pf:
                _line = _line.strip()
                if "=" in _line and not _line.startswith("#"):
                    _k, _, _v = _line.partition("=")
                    _pub_env_vals[_k.strip()] = _v.strip()
    except Exception:
        pass
    for _env_key, _label in _token_pairs:
        _issued_str = _pub_env_vals.get(_env_key) or os.environ.get(_env_key, "")
        if _issued_str:
            try:
                from datetime import date as _date
                _issued = _date.fromisoformat(_issued_str[:10])
                _expiry = _issued + timedelta(days=60)
                _days_left = (_expiry - _date.today()).days
                if _days_left < 0:
                    alerts.append({"ts": now_str, "sev": "crit",
                                   "msg": f"{_label} EXPIRED {abs(_days_left)} days ago — refresh immediately"})
                elif _days_left < 7:
                    alerts.append({"ts": now_str, "sev": "warn",
                                   "msg": f"{_label} expires in {_days_left} day{'s' if _days_left != 1 else ''} — refresh soon"})
            except Exception:
                pass
        else:
            alerts.append({"ts": now_str, "sev": "warn",
                            "msg": f"{_label} expiry unknown — add {_env_key}=YYYY-MM-DD to publisher/.env"})

    return sorted(alerts, key=lambda x: x["ts"], reverse=True)[:50]


def build_health_alerts_history(conn) -> list[dict]:
    """Query health_alerts table for last 24h EdgeOps alerts with resolution status."""
    if conn is None:
        return []
    if not table_exists(conn, "health_alerts"):
        return []
    try:
        rows = q_all(conn, """
            SELECT ha.source_id, ha.alert_type, ha.severity, ha.message,
                   ha.fired_at, ha.resolved_at, ha.acknowledged,
                   sr.source_name
            FROM health_alerts ha
            LEFT JOIN source_registry sr ON sr.source_id = ha.source_id
            WHERE ha.fired_at >= datetime('now', '-24 hours')
            ORDER BY ha.fired_at DESC
            LIMIT 60
        """)
    except Exception:
        return []
    out = []
    for r in rows:
        resolved = r["resolved_at"] is not None
        out.append({
            "source_id": r["source_id"],
            "source_name": r["source_name"] or r["source_id"],
            "alert_type": (r["alert_type"] or "").replace("_", " "),
            "severity": r["severity"] or "warning",
            "message": r["message"] or "",
            "fired_at": r["fired_at"],
            "resolved": resolved,
            "ts": _sast_hhmm(r["fired_at"]),
            "ts_rel": _relative_time(r["fired_at"]),
        })
    return out


def build_api_quota_from_db(conn) -> list[dict]:
    """Query api_quota_tracking for latest per-API quota data (live from health_checker)."""
    if conn is None:
        return []
    if not table_exists(conn, "api_quota_tracking"):
        return []
    try:
        rows = q_all(conn, """
            SELECT api_name, credits_used, credits_limit, credits_remaining,
                   pct_used, period, checked_at
            FROM api_quota_tracking
            WHERE rowid IN (
                SELECT MAX(rowid) FROM api_quota_tracking GROUP BY api_name
            )
            ORDER BY api_name
        """)
    except Exception:
        return []
    out = []
    for r in rows:
        used = r["credits_used"]
        limit = r["credits_limit"]
        remaining = r["credits_remaining"]
        pct = float(r["pct_used"] or 0)
        pct_rem = (100.0 - pct) if limit else 0
        if pct_rem > 50:
            quota_css = "s-green"
        elif pct_rem > 20:
            quota_css = "s-amber"
        else:
            quota_css = "s-red"
        out.append({
            "api": r["api_name"].replace("_", " ").replace("the ", "The ").title(),
            "used": used if used is not None else "—",
            "limit": f"{limit:,}" if limit else "—",
            "remaining": f"{remaining:,}" if remaining is not None else "—",
            "pct_used": round(pct, 1),
            "period": r["period"] or "—",
            "last_updated": _relative_time(r["checked_at"]),
            "css": quota_css,
        })
    return out


# -- Notion API helpers (Automation view) -------------------------------------

def _notion_request(endpoint: str, body: dict | None = None, method: str | None = None) -> dict | None:
    """Make a Notion API request using urllib. Returns parsed JSON or None."""
    url = f"https://api.notion.com/v1/{endpoint}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2025-09-03",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _query_notion_db(db_id: str, filter_obj: dict | None = None, sorts: list | None = None, page_size: int = 100, max_pages: int = 10) -> list[dict]:
    """Query a Notion database with pagination. Returns list of page objects."""
    all_results: list[dict] = []
    start_cursor: str | None = None
    for _ in range(max_pages):
        body: dict = {"page_size": page_size}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts
        if start_cursor:
            body["start_cursor"] = start_cursor
        result = _notion_request(f"data_sources/{db_id}/query", body)
        if not result or "results" not in result:
            break
        all_results.extend(result["results"])
        if result.get("has_more") and result.get("next_cursor"):
            start_cursor = result["next_cursor"]
        else:
            break
    return all_results


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

    raw_pages = _query_notion_db(
        NOTION_MARKETING_DB,
        sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
        page_size=100,
        max_pages=10,
    )
    items = []
    for page in raw_pages:
        item = {
            "id": page.get("id", ""),
            "title": _get_page_prop(page, "Title") or _get_page_prop(page, "Name") or "",
            "status": _get_page_prop(page, "Status") or "",
            "channel": _get_page_prop(page, "Channel") or "",
            "scheduled_time": _get_page_prop(page, "Scheduled Time") or _get_page_prop(page, "Scheduled") or "",
            "copy": _get_page_prop(page, "Final Copy") or _get_page_prop(page, "Copy") or _get_page_prop(page, "Copy Preview") or _get_page_prop(page, "Body") or "",
            "asset_link": _get_page_prop(page, "Asset Link") or _get_page_prop(page, "Asset") or _get_page_prop(page, "Media") or "",
            "url": _get_page_prop(page, "URL") or _get_page_prop(page, "Published URL") or "",
            "campaign_theme": _get_page_prop(page, "Campaign / Theme") or _get_page_prop(page, "Campaign") or _get_page_prop(page, "Theme") or "",
            "error": _get_page_prop(page, "Error") or _get_page_prop(page, "Reason") or "",
            "work_type": _get_page_prop(page, "Work Type") or _get_page_prop(page, "Type") or "",
            "platform_notes": _get_page_prop(page, "Platform Notes") or _get_page_prop(page, "Notes") or "",
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
        if "alert" in low:
            return "telegram_alerts"
        if "community" in low or "comm" in low:
            return "telegram_community"
        return "telegram_alerts"  # default bare "telegram" to alerts channel
    if "whatsapp" in low or "wa" in low:
        return "whatsapp"
    if "twitter" in low or low == "x":
        return "x_twitter"
    return ""


# Channels that historically required Paul's approval before publishing.
# NOTE (META-TASKHUB-PERMAFIX-01): The Task Hub no longer uses this filter.
# Any MOQ item with a review status (Awaiting Approval, etc.) now appears in
# the Task Hub regardless of channel. _APPROVAL_CHANNELS is retained for
# the Social Media / Automation view's channel-specific grouping only.
_APPROVAL_CHANNELS: frozenset[str] = frozenset({
    "Facebook", "Facebook Image",
    "Instagram", "Instagram Image",
    "LinkedIn", "LinkedIn Image",
})


def _get_awaiting_items(
    items: list[dict],
    include_overdue: bool = False,
    channels: frozenset[str] | None = None,
) -> list[dict]:
    """Return items needing review.

    Args:
        items: all queue items
        include_overdue: if True, also include Approved/Ready/Scheduled items with
            past scheduled times (overdue posts that still need action).
        channels: if provided, restrict results to items whose Channel matches
            one of these values (exact, case-sensitive). Pass _APPROVAL_CHANNELS
            to enforce the FB/IG/LI-only approval model in the Task Hub.
    """
    now_utc = datetime.now(timezone.utc)
    awaiting: list[dict] = []
    for item in items:
        # Channel gate — apply before anything else
        if channels is not None:
            item_channel = (item.get("channel") or "").strip()
            if item_channel not in channels:
                continue
        status = (item.get("status") or "").lower().strip()
        sched_raw = item.get("scheduled_time") or ""
        if status in ("awaiting approval", "draft", "review", "pending",
                       "in review", "awaiting", "in progress"):
            awaiting.append(item)
        elif include_overdue and status in ("approved", "ready", "scheduled"):
            sched_dt = parse_ts(sched_raw)
            if sched_dt and sched_dt <= now_utc:
                awaiting.append(item)
    awaiting.sort(key=lambda x: x.get("scheduled_time") or x.get("created") or "9999")
    return awaiting


# -- HTML renderer helpers ----------------------------------------------------

STATUS_CSS = {
    "s-green": "color:#22c55e;font-weight:700",
    "s-amber": "color:#f59e0b;font-weight:700",
    "s-red":   "color:#ef4444;font-weight:700",
    "s-black": "color:#6b7280;font-weight:700",
    "s-grey":  "color:#6b7280;font-weight:700",
}


def dot(css_class: str) -> str:
    styles = {
        "s-green": "#22c55e",
        "s-amber": "#f59e0b",
        "s-red":   "#ef4444",
        "s-black": "#6b7280",
        "s-grey":  "#6b7280",
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
_ICON_SERVER = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>'
_ICON_TASKHUB = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="6" height="6" rx="1"/><rect x="3" y="13" width="6" height="6" rx="1"/><line x1="13" y1="8" x2="21" y2="8"/><line x1="13" y1="16" x2="21" y2="16"/><line x1="17" y1="5" x2="17" y2="11"/></svg>'
_ICON_CHART = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/></svg>'
_ICON_APPROVAL = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'



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
    --glow: 0 0 0 1px rgba(248,200,48,0.05), 0 4px 24px rgba(0,0,0,0.55);
    --glow-hover: 0 0 0 1px rgba(248,200,48,0.13), 0 8px 32px rgba(0,0,0,0.65), 0 0 40px rgba(248,200,48,0.04);
    --trans: cubic-bezier(0.4, 0, 0.2, 1);
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    background: var(--carbon);
    color: var(--text);
    font-family: var(--font-b);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
    overflow-x: hidden;
    background-image:
      radial-gradient(ellipse 80% 50% at 50% -10%, rgba(248,200,48,0.03) 0%, transparent 60%),
      radial-gradient(ellipse 50% 40% at 90% 110%, rgba(232,87,31,0.02) 0%, transparent 55%);
  }
  ::selection { background: rgba(248,200,48,0.2); color: var(--text); }
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: var(--carbon); }
  ::-webkit-scrollbar-thumb { background: rgba(248,200,48,0.18); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(248,200,48,0.32); }
  a { color: var(--gold); text-decoration: none; } a:hover { text-decoration: underline; }

  /* SIDEBAR */
  .sidebar {
    position: fixed; top: 0; left: 0; bottom: 0; z-index: 200;
    width: var(--sidebar-w);
    background: rgba(8,8,8,0.97);
    border-right: 1px solid rgba(255,255,255,0.04);
    display: flex; flex-direction: column;
    overflow: hidden;
    box-shadow: 2px 0 20px rgba(0,0,0,0.5);
  }
  .sidebar-brand {
    display: flex; align-items: center; justify-content: center;
    padding: 20px 16px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    flex-shrink: 0;
  }
  .sidebar-brand img { width: 160px; height: auto; display: block; }
  .sidebar-nav { flex: 1; display: flex; flex-direction: column; padding: 8px 0; gap: 2px; }
  .sidebar-item {
    display: flex; align-items: center; gap: 12px;
    height: 42px; padding: 0 0 0 19px;
    color: var(--muted); cursor: pointer;
    border-left: 3px solid transparent;
    transition: background 200ms var(--trans), color 200ms var(--trans), box-shadow 200ms var(--trans);
    text-decoration: none; white-space: nowrap; overflow: hidden;
  }
  .sidebar-item:hover { background: rgba(255,255,255,0.05); color: var(--text); text-decoration: none; }
  .sidebar-item.active {
    border-left: 3px solid; border-image: var(--grad) 1;
    background: rgba(248,200,48,0.07); color: var(--text);
    box-shadow: inset 0 0 20px rgba(248,200,48,0.03);
  }
  .sidebar-item .item-icon { flex-shrink: 0; display: flex; align-items: center; }
  .sidebar-item .item-label {
    font-family: var(--font-d); font-weight: 600; font-size: 12px;
    letter-spacing: 0.04em; display: flex; align-items: center; gap: 8px;
  }
  .nav-badge {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 18px; height: 18px; padding: 0 5px;
    background: #E8571F; color: #fff; font-size: 10px; font-weight: 700;
    border-radius: 9px; line-height: 1; font-family: var(--font-d);
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
  .topbar { position: sticky; top: 0; z-index: 100; background: rgba(10,10,10,0.92); backdrop-filter: blur(24px) saturate(160%); -webkit-backdrop-filter: blur(24px) saturate(160%); border-bottom: 1px solid rgba(255,255,255,0.04); padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; box-shadow: 0 1px 0 rgba(255,255,255,0.03), 0 4px 20px rgba(0,0,0,0.35); }
  .topbar-left { display: flex; align-items: center; gap: 16px; }
  .topbar-pill { background: rgba(248,200,48,0.1); border: 1px solid rgba(248,200,48,0.2); border-radius: 999px; padding: 3px 12px; font-family: var(--font-d); font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--gold); }
  .topbar-right { display: flex; align-items: center; gap: 20px; }
  .topbar-meta { font-size: 11px; font-family: var(--font-m); color: var(--muted); }
  .topbar-meta em { color: var(--text); font-style: normal; }
  .db-status { display: flex; align-items: center; gap: 6px; font-size: 11px; font-family: var(--font-m); }
  .pulse { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .pulse-green { background: var(--green); box-shadow: 0 0 0 2px rgba(34,197,94,.3), 0 0 8px rgba(34,197,94,0.4); animation: pulse 2s infinite; }
  .pulse-red   { background: var(--red);   box-shadow: 0 0 0 2px rgba(239,68,68,.3), 0 0 8px rgba(239,68,68,0.3); }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 2px rgba(34,197,94,.3), 0 0 8px rgba(34,197,94,0.4); } 50% { box-shadow: 0 0 0 6px rgba(34,197,94,.08), 0 0 14px rgba(34,197,94,0.2); } }

  /* BANNER */
  .banner { padding: 7px 24px; font-size: 11px; font-family: var(--font-m); text-align: center; letter-spacing: .02em; }
  .banner-ok  { background: rgba(34,197,94,.06); color: var(--green); border-bottom: 1px solid rgba(34,197,94,.12); }
  .banner-err { background: rgba(239,68,68,.06);  color: var(--red);   border-bottom: 1px solid rgba(239,68,68,.12); }
  .banner-warn { background: rgba(245,158,11,.06); color: var(--amber); border-bottom: 1px solid rgba(245,158,11,.12); }

  /* PAGE */
  .page { max-width: 1440px; margin: 0 auto; padding: 20px 20px 48px; }

  /* KPI STRIP */
  .kpi-strip { display: grid; grid-template-columns: repeat(5,1fr); gap: 12px; margin-bottom: 20px; }
  .kpi {
    background: var(--surface);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: var(--r);
    padding: 14px 16px;
    position: relative;
    overflow: hidden;
    box-shadow: var(--glow);
    transition: box-shadow 300ms var(--trans), border-color 300ms var(--trans), transform 200ms var(--trans);
  }
  .kpi:hover {
    box-shadow: var(--glow-hover);
    border-color: rgba(248,200,48,0.1);
    transform: translateY(-1px);
  }
  .kpi::after { content:''; position:absolute; top:0; left:0; right:0; height:2px; background: var(--grad); opacity: 0.7; transition: opacity 300ms var(--trans); }
  .kpi:hover::after { opacity: 1; }
  .kpi::before { content:''; position:absolute; top:0; left:0; width:100%; height:100%; background: radial-gradient(ellipse 60% 50% at 0% 0%, rgba(248,200,48,0.025) 0%, transparent 70%); pointer-events:none; }
  .kpi-lbl { font-size: 10px; font-family: var(--font-d); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
  .kpi-val { font-size: 26px; font-family: var(--font-d); font-weight: 700; line-height: 1; }
  .kpi-val.c-gold { text-shadow: 0 0 18px rgba(248,200,48,0.22); }
  .kpi-val.c-green { text-shadow: 0 0 14px rgba(34,197,94,0.2); }
  .kpi-val.c-red { text-shadow: 0 0 14px rgba(239,68,68,0.2); }
  .kpi-sub { font-size: 11px; font-family: var(--font-m); color: var(--muted); margin-top: 5px; }
  .c-gold  { color: var(--gold); }
  .c-green { color: var(--green); }
  .c-amber { color: var(--amber); }
  .c-red   { color: var(--red); }
  .c-text  { color: var(--text); }

  /* PANELS */
  .panel { background: var(--surface); border: 1px solid rgba(255,255,255,0.05); border-radius: var(--r); overflow: hidden; margin-bottom: 16px; box-shadow: var(--glow); transition: box-shadow 300ms var(--trans), border-color 300ms var(--trans); }
  .panel:hover { box-shadow: var(--glow-hover); border-color: rgba(248,200,48,0.08); }
  .panel-head { padding: 11px 18px; border-bottom: 1px solid rgba(255,255,255,0.04); display: flex; align-items: center; justify-content: space-between; gap: 12px; background: rgba(0,0,0,0.2); backdrop-filter: blur(4px); }
  .panel-title { font-family: var(--font-d); font-weight: 700; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--text); }
  .panel-sub { font-size: 11px; font-family: var(--font-m); color: var(--muted); text-align: right; }
  .panel-red-accent { border-left: 3px solid var(--red); }
  .panel-orange-accent { border-top: 2px solid; border-image: var(--grad) 1; }

  /* TABLES */
  .tbl-wrap { overflow-x: auto; }
  .tbl { width: 100%; border-collapse: collapse; min-width: 480px; }
  .tbl thead th { font-family: var(--font-d); font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 6px 12px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.04); white-space: nowrap; background: rgba(0,0,0,.3); backdrop-filter: blur(4px); }
  .tbl tbody td { padding: 6px 12px; border-bottom: 1px solid rgba(255,255,255,0.03); font-family: var(--font-m); font-size: 12px; vertical-align: middle; white-space: nowrap; transition: background 150ms var(--trans); }
  .tbl tbody tr:last-child td { border-bottom: none; }
  .tbl tbody tr:hover td { background: rgba(248,200,48,.04); }
  .tbl tbody tr:hover { box-shadow: inset 3px 0 0 rgba(248,200,48,0.35); }

  /* CHIPS */
  .chip { display:inline-flex; align-items:center; gap:5px; padding:3px 9px; border-radius:999px; font-size:10px; font-weight:700; font-family:var(--font-d); letter-spacing:.04em; white-space:nowrap; }
  .cdot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
  .chip-green { background:rgba(34,197,94,.08);  color:var(--green); border:1px solid rgba(34,197,94,.2);  box-shadow: 0 0 8px rgba(34,197,94,0.1); } .chip-green .cdot { background:var(--green); box-shadow:0 0 5px var(--green); }
  .chip-amber { background:rgba(245,158,11,.08); color:var(--amber); border:1px solid rgba(245,158,11,.2); box-shadow: 0 0 8px rgba(245,158,11,0.1); } .chip-amber .cdot { background:var(--amber); box-shadow:0 0 5px var(--amber); }
  .chip-red   { background:rgba(239,68,68,.08);  color:var(--red);   border:1px solid rgba(239,68,68,.2);  box-shadow: 0 0 8px rgba(239,68,68,0.1); } .chip-red   .cdot { background:var(--red); box-shadow:0 0 5px var(--red); }
  .chip-gray  { background:rgba(107,114,128,.08);color:var(--muted); border:1px solid rgba(107,114,128,.18);} .chip-gray  .cdot { background:var(--muted); }

  /* Channel chips */
  .ch-chip { display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:4px; font-size:10px; font-weight:600; font-family:var(--font-d); letter-spacing:.03em; }
  .ch-dot { width:5px; height:5px; border-radius:50%; flex-shrink:0; }

  /* STATUS TEXT */
  .s-green { color:var(--green); font-weight:700; } .s-amber { color:var(--amber); font-weight:700; } .s-red { color:var(--red); font-weight:700; } .s-black { color:var(--muted); font-weight:700; } .s-grey { color:var(--muted); font-weight:700; }

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

  /* LOADING BAR */
  #loading-bar {
    position: fixed; top: 0; left: var(--sidebar-w); right: 0;
    height: 3px;
    background: linear-gradient(90deg, #F8C830, #F0A020, #E8571F);
    z-index: 9999;
    opacity: 0;
    pointer-events: none;
    transform: scaleX(0);
    transform-origin: left;
    transition: opacity 80ms;
  }
  #loading-bar.lb-active {
    opacity: 1;
    animation: lb-progress 1.4s ease-in-out infinite alternate;
  }
  @keyframes lb-progress {
    0%   { transform: scaleX(0.05); }
    50%  { transform: scaleX(0.65); }
    100% { transform: scaleX(0.92); }
  }

  /* PAGE ENTRY ANIMATION */
  @keyframes fade-up { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
  .page { animation: fade-up 0.35s var(--trans) both; }
  .kpi { animation: fade-up 0.35s var(--trans) both; }
  .kpi:nth-child(1){animation-delay:0.04s} .kpi:nth-child(2){animation-delay:0.08s} .kpi:nth-child(3){animation-delay:0.12s} .kpi:nth-child(4){animation-delay:0.16s} .kpi:nth-child(5){animation-delay:0.20s}

  /* CLICKABLE KPI */
  .kpi-clickable { cursor: pointer; }
  .kpi-clickable:hover { background: rgba(248,200,48,0.05); }

  /* APPROVALS VIEW */
  .appr-pipeline-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:20px; flex-wrap:wrap; gap:12px; }
  .appr-count-badge { font-family:var(--font-d); font-size:13px; font-weight:700; color:var(--amber); background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.2); border-radius:999px; padding:4px 14px; }
  .appr-notion-link { font-family:var(--font-m); font-size:12px; color:var(--gold); }
  .empty-state { text-align:center; padding:60px 20px; font-family:var(--font-m); font-size:14px; color:var(--muted); }
  .empty-state-done { text-align:center; padding:60px 20px; }
  .empty-state-done-icon { font-size:40px; margin-bottom:12px; }
  .empty-state-done-text { font-family:var(--font-d); font-size:18px; font-weight:700; color:var(--text); }
  .empty-state-done-sub { font-family:var(--font-m); font-size:13px; color:var(--muted); margin-top:6px; }

  /* TABS */
  .tab-bar { display:flex; gap:0; border-bottom:1px solid var(--border); margin-bottom:20px; overflow-x:auto; flex-shrink:0; }
  .tab-btn { padding:10px 20px; font-family:var(--font-d); font-weight:600; font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:var(--muted); cursor:pointer; border:none; background:none; border-bottom:3px solid transparent; margin-bottom:-1px; transition:color 150ms,border-color 150ms; white-space:nowrap; }
  .tab-btn:hover { color:var(--text); }
  .tab-btn.tab-active { color:var(--gold); border-bottom-color:var(--gold); }
  .tab-pane { display:none; }
  .tab-pane.tab-active { display:block; }

  /* KPI TIER HIERARCHY */
  .kpi-strip-h { grid-template-columns:repeat(6,1fr); }
  .kpi-strip-h .kpi-t1 { grid-column:span 3; }
  .kpi-t1 .kpi-val { font-size:36px; }
  @media(max-width:1100px) { .kpi-strip-h { grid-template-columns:repeat(4,1fr); } .kpi-strip-h .kpi-t1 { grid-column:span 2; } }
  @media(max-width:768px) { .kpi-strip-h { grid-template-columns:repeat(2,1fr); } .kpi-strip-h .kpi-t1 { grid-column:span 2; } }

  /* COVERAGE BARS */
  .cov-bar-row { display:flex; align-items:center; gap:10px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.03); }
  .cov-bar-label { width:90px; font-family:var(--font-d); font-size:11px; font-weight:600; color:var(--text); flex-shrink:0; text-transform:capitalize; }
  .cov-bar-track { flex:1; background:rgba(255,255,255,0.05); border-radius:999px; height:7px; overflow:hidden; box-shadow:inset 0 1px 3px rgba(0,0,0,0.4); }
  .cov-bar-fill { height:100%; border-radius:999px; box-shadow: 0 0 10px rgba(248,200,48,0.18); }
  .cov-bar-meta { font-family:var(--font-m); font-size:11px; color:var(--muted); flex-shrink:0; text-align:right; min-width:90px; }

  /* EXCEPTION-FIRST */
  .exc-critical { background:rgba(239,68,68,0.06); border:1px solid rgba(239,68,68,0.22); border-radius:8px; padding:10px 14px; margin-bottom:10px; }
  .exc-warn-wrap { border:1px solid rgba(245,158,11,0.2); border-radius:8px; margin-bottom:8px; overflow:hidden; }
  .exc-warn-sum { padding:8px 14px; cursor:pointer; display:flex; align-items:center; gap:8px; font-family:var(--font-m); font-size:12px; color:var(--amber); }
  .exc-ok { background:rgba(34,197,94,0.04); border:1px solid rgba(34,197,94,0.14); border-radius:8px; padding:9px 14px; color:var(--green); font-family:var(--font-m); font-size:12px; margin-top:4px; }
  .exc-src-row { display:flex; align-items:center; gap:8px; padding:4px 2px; font-size:12px; border-bottom:1px solid rgba(239,68,68,0.1); }

  /* TABLE FIXED HEIGHT */
  .tbl-fixed { max-height:280px; overflow-y:auto; }

  /* ALERT LIMIT NOTE */
  .alert-limit-note { font-family:var(--font-m); font-size:11px; color:var(--muted); padding:6px 16px; border-top:1px solid var(--border); }

  /* BILLING ALERT (AC-15) */
  @keyframes billing-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
  }
  .billing-alert {
    background: rgba(255,0,255,0.08);
    border: 2px solid #ff00ff;
    color: #ff88ff;
    padding: 10px 16px;
    margin: 8px 0;
    border-radius: 6px;
    font-family: var(--font-m);
    font-size: 12px;
    animation: billing-pulse 1s ease-in-out infinite;
  }

  /* CLICKABLE KPI (s-grey status class) */
  .s-grey { color: #6b7280; font-weight: 700; }
"""


# -- Sidebar HTML -------------------------------------------------------------

def _sidebar_html(active_view: str) -> str:
    items = [
        ("health", "System Health", _ICON_SERVER, "/admin/health"),
        ("performance", "Edge Performance", _ICON_CHART, "/admin/performance"),
        ("automation", "Social Media", _ICON_PLAY, "/admin/automation"),
        ("task_hub", "Task Hub", _ICON_TASKHUB, "/admin/task-hub"),
    ]
    # Compute pending approval count for Task Hub badge
    _badge_count = 0
    try:
        _mq, _ = _fetch_marketing_queue()
        _badge_count = len(_get_awaiting_items(_mq, include_overdue=False))
    except Exception:
        pass
    nav_items = ""
    for key, label, icon, href in items:
        active_cls = " active" if key == active_view else ""
        badge_html = ""
        if key == "task_hub" and _badge_count > 0:
            badge_html = f'<span class="nav-badge" id="th-badge">{_badge_count}</span>'
        nav_items += f'<a class="sidebar-item{active_cls}" href="{href}" data-view="{key}"><span class="item-icon">{icon}</span><span class="item-label">{label}{badge_html}</span></a>\n'

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
  var _loadingBar = document.getElementById('loading-bar');
  var _currentXhr = null;
  var _loadStart = 0;
  var _MIN_LOAD_MS = 150;

  function _showBar() {
    _loadStart = Date.now();
    if (_loadingBar) { _loadingBar.classList.add('lb-active'); }
  }
  function _hideBar() {
    var elapsed = Date.now() - _loadStart;
    var delay = Math.max(0, _MIN_LOAD_MS - elapsed);
    setTimeout(function() {
      if (_loadingBar) { _loadingBar.classList.remove('lb-active'); }
    }, delay);
  }

  // Re-execute <script> tags that were injected via innerHTML
  // (innerHTML does NOT execute scripts; we must clone each one)
  function _execScripts(container) {
    var scripts = container.querySelectorAll('script');
    scripts.forEach(function(old) {
      var s = document.createElement('script');
      for (var i = 0; i < old.attributes.length; i++) {
        s.setAttribute(old.attributes[i].name, old.attributes[i].value);
      }
      s.textContent = old.textContent;
      old.parentNode.replaceChild(s, old);
    });
  }

  function _injectView(view, html, href) {
    contentInner.innerHTML = html;
    if (href) history.pushState({view: view}, '', href);
    _execScripts(contentInner);
    if (view === 'health') {
      document.dispatchEvent(new Event('healthViewLoaded'));
    }
    // Refresh Task Hub badge from server on every view switch
    fetch('/admin/api/task_hub_badge', {credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){
        var badge = document.getElementById('th-badge');
        var c = d.count || 0;
        if (badge) {
          if (c > 0) { badge.textContent = c; }
          else { badge.remove(); }
        } else if (c > 0) {
          var thLink = document.querySelector('.sidebar-item[data-view="task_hub"] .item-label');
          if (thLink) {
            var b = document.createElement('span');
            b.className = 'nav-badge'; b.id = 'th-badge'; b.textContent = c;
            thLink.appendChild(b);
          }
        }
      }).catch(function(){});
  }

  // AJAX view switching
  var navItems = document.querySelectorAll('.sidebar-item[data-view]');
  navItems.forEach(function(item) {
    item.addEventListener('click', function(e) {
      e.preventDefault();
      var view = this.getAttribute('data-view');
      var href = this.getAttribute('href');

      // Cancel any in-flight request
      if (_currentXhr) { try { _currentXhr.abort(); } catch(_) {} _currentXhr = null; }

      navItems.forEach(function(n) { n.classList.remove('active'); });
      this.classList.add('active');
      _showBar();

      var xhr = new XMLHttpRequest();
      _currentXhr = xhr;
      xhr.open('GET', '/admin/api/' + view, true);
      xhr.withCredentials = true;
      xhr.onload = function() {
        if (xhr !== _currentXhr) return;  // superseded by a newer click
        _currentXhr = null;
        _hideBar();
        if (xhr.status >= 200 && xhr.status < 300) {
          _injectView(view, xhr.responseText, href);
        } else {
          contentInner.innerHTML = '<div class="page"><div class="panel"><div style="padding:40px;text-align:center;color:var(--muted)">Failed to load view: HTTP ' + xhr.status + '</div></div></div>';
        }
      };
      xhr.onerror = function() {
        if (xhr !== _currentXhr) return;
        _currentXhr = null;
        _hideBar();
        contentInner.innerHTML = '<div class="page"><div class="panel"><div style="padding:40px;text-align:center;color:var(--muted)">Network error loading view.</div></div></div>';
      };
      xhr.onabort = function() { /* superseded — do nothing */ };
      xhr.send();
    });
  });

  // Expose helper for KPI card clicks that navigate programmatically
  window._navToView = function(view) {
    var item = document.querySelector('.sidebar-item[data-view="' + view + '"]');
    if (item) { item.click(); }
  };

  // Handle browser back/forward
  window.addEventListener('popstate', function(e) {
    if (e.state && e.state.view) {
      var view = e.state.view;
      navItems.forEach(function(n) {
        n.classList.toggle('active', n.getAttribute('data-view') === view);
      });
      _showBar();
      var xhr2 = new XMLHttpRequest();
      xhr2.open('GET', '/admin/api/' + view, true);
      xhr2.withCredentials = true;
      xhr2.onload = function() { _hideBar(); _injectView(view, xhr2.responseText, null); };
      xhr2.onerror = function() { _hideBar(); };
      xhr2.send();
    }
  });

  // Set initial state
  history.replaceState({view: document.body.getAttribute('data-active-view')}, '');
})();
</script>"""


# -- Source Health Monitor helpers -------------------------------------------

_CATEGORY_DISPLAY = {
    "bookmaker":   "Bookmaker Odds (8)",
    "sharp":       "Sharp Benchmark (4)",
    "rating":      "Ratings & Results (3)",
    "fixture":     "Fixtures & Lineups (5)",
    "tipster":     "Tipster Predictions (9)",
    "enrichment":  "News & Enrichment (4)",
    "settlement":  "Edge & Settlement (4)",
    "bot_job":     "Bot Jobs (5)",
    "Data Feeds":  "Data Feeds (1)",
}

_CATEGORY_ORDER = [
    "bookmaker", "sharp", "rating", "fixture",
    "tipster", "enrichment", "settlement", "bot_job",
    "Data Feeds",
]

_STATUS_DOT = {
    "green":  '<span style="color:#22c55e">&#9679;</span>',
    "yellow": '<span style="color:#f59e0b">&#9679;</span>',
    "red":    '<span style="color:#ef4444">&#9679;</span>',
    "black":  '<span style="color:#6b7280">&#9679;</span>',
    "grey":   '<span style="color:#6b7280">&#9679;</span>',
}

_STATUS_DISPLAY = {
    "green":  "GREEN",
    "yellow": "AMBER",
    "red":    "RED",
    "black":  "OFFLINE",
    "grey":   "IDLE",
}


def build_source_health_monitor(conn):
    """Return source health monitor dict for rendering.

    Returns dict with:
      system_score, green_count, yellow_count, red_count, black_count,
      sources_by_category, critical_issues
    Returns fallback dict with system_score=-1 if schema not migrated.
    """
    _fallback = {
        "system_score": -1,
        "green_count": 0, "yellow_count": 0, "red_count": 0, "black_count": 0,
        "grey_count": 0, "total_count": 0,
        "sources_by_category": {},
        "critical_issues": [],
    }
    if conn is None:
        return _fallback
    if not table_exists(conn, "source_health_current"):
        return _fallback
    if not table_exists(conn, "source_registry"):
        return _fallback

    try:
        rows = q_all(conn, """
            SELECT
                r.source_id, r.source_name, r.category, r.critical,
                r.expected_interval_minutes,
                h.status, h.last_success_at, h.consecutive_failures, h.last_rows_produced
            FROM source_registry r
            LEFT JOIN source_health_current h ON h.source_id = r.source_id
            WHERE r.enabled = 1
            ORDER BY r.category, r.source_name
        """)
    except Exception:
        return _fallback

    counts = {"green": 0, "yellow": 0, "red": 0, "black": 0, "grey": 0}
    sources_by_category = {cat: [] for cat in _CATEGORY_ORDER}
    critical_issues = []

    now_utc = datetime.now(timezone.utc) if hasattr(datetime, 'now') else None
    for row in rows:
        d = dict(row)
        interval = d.get("expected_interval_minutes") or 0
        raw_status = d.get("status") or "black"
        # AC-1: on-demand services (interval=0) with no success show as grey, never red/black
        status = "grey" if (interval == 0 and raw_status == "black") else raw_status
        # Freshness override: if interval > 0 and last_success exceeds interval, force RED
        if interval > 0 and now_utc and d.get("last_success_at"):
            try:
                _ls = d["last_success_at"].replace("Z", "+00:00")
                _last_dt = datetime.fromisoformat(_ls)
                if _last_dt.tzinfo is None:
                    _last_dt = _last_dt.replace(tzinfo=timezone.utc)
                _age_min = (now_utc - _last_dt).total_seconds() / 60
                if _age_min > interval:
                    status = "red"
            except (ValueError, TypeError):
                pass
        d["status"] = status  # update for rendering
        counts[status] = counts.get(status, 0) + 1
        cat = d.get("category", "")
        if cat not in sources_by_category:
            sources_by_category[cat] = []
        sources_by_category[cat].append(d)
        # GREY on-demand items are never critical
        if d.get("critical") and status in ("red", "black"):
            critical_issues.append(d)

    total = len(rows)
    # Weighted score: exclude GREY (on-demand/idle) from denominator (AC-5)
    # Only score sources with expected_interval > 0
    # Use freshness-overridden status from sources_by_category, not raw DB rows
    scored = [
        s for sources in sources_by_category.values()
        for s in sources
        if (s.get("expected_interval_minutes") or 0) > 0
    ]
    if scored:
        s_weights = {"green": 100, "yellow": 60, "red": 20, "black": 0, "grey": 0}
        raw = sum(s_weights.get(d.get("status") or "black", 0) for d in scored)
        system_score = round(raw / len(scored), 1)
    else:
        system_score = 0.0

    return {
        "system_score": system_score,
        "green_count": counts["green"],
        "yellow_count": counts["yellow"],
        "red_count": counts["red"],
        "black_count": counts["black"],
        "grey_count": counts.get("grey", 0),
        "total_count": total,
        "sources_by_category": sources_by_category,
        "critical_issues": critical_issues,
    }


def build_card_population_gate(conn) -> dict:
    """Card Population Gate status from card_population_failures table."""
    _fallback = {"count_24h": 0, "last_reason": "", "last_match": "", "status": "green"}
    if conn is None:
        return _fallback
    if not table_exists(conn, "card_population_failures"):
        return _fallback
    try:
        row = q_one(conn, """
            SELECT COUNT(*) as count_24h,
                   MAX(reason) as last_reason,
                   MAX(match_key) as last_match
            FROM card_population_failures
            WHERE created_at >= datetime('now', '-1 day')
        """)
        if not row:
            return _fallback
        count = row[0] or 0
        if count == 0:
            status = "green"
        elif count <= 3:
            status = "yellow"
        else:
            status = "red"
        return {
            "count_24h": count,
            "last_reason": row[1] or "",
            "last_match": row[2] or "",
            "status": status,
        }
    except Exception:
        return _fallback


def _render_card_population_gate_panel(cpg: dict) -> str:
    """Render the Card Population Gate as a small dashboard panel."""
    count = cpg["count_24h"]
    status = cpg["status"]
    reason = cpg["last_reason"]
    match = cpg["last_match"]

    status_dot = {
        "green": '<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 4px var(--green);margin-right:8px"></span>',
        "yellow": '<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--amber);box-shadow:0 0 4px var(--amber);margin-right:8px"></span>',
        "red": '<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--red);box-shadow:0 0 4px var(--red);margin-right:8px"></span>',
    }.get(status, "")

    status_label = {
        "green": '<span style="color:var(--green);font-weight:700">Healthy</span>',
        "yellow": '<span style="color:var(--amber);font-weight:700">Warning</span>',
        "red": '<span style="color:var(--red);font-weight:700">Critical</span>',
    }.get(status, "")

    detail_rows = (
        f'<tr><td style="padding:6px 12px;font-family:var(--font-d);font-size:12px;font-weight:600">Suppressed (24h)</td>'
        f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px">{count}</td></tr>'
    )
    if reason:
        esc_reason = reason.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        detail_rows += (
            f'<tr><td style="padding:6px 12px;font-family:var(--font-d);font-size:12px;font-weight:600">Last Reason</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{esc_reason}</td></tr>'
        )
    if match:
        esc_match = match.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        detail_rows += (
            f'<tr><td style="padding:6px 12px;font-family:var(--font-d);font-size:12px;font-weight:600">Last Match</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{esc_match}</td></tr>'
        )

    accent = ""
    if status == "red":
        accent = " panel-red-accent"
    elif status == "yellow":
        accent = " panel-orange-accent"

    return (
        f'<div class="panel{accent}">'
        f'<div class="panel-head">'
        f'<span class="panel-title">Card Population Gate</span>'
        f'<span class="panel-sub">{status_dot}{status_label}</span>'
        f'</div>'
        f'<div class="tbl-wrap tbl-fixed"><table class="tbl">'
        f'<tbody>{detail_rows}</tbody>'
        f'</table></div></div>'
    )


def build_rendering_path_stats(conn):
    """Query narrative_cache rendering path breakdown."""
    _fallback = {
        "w84": 0, "w82": 0, "baseline_no_edge": 0, "total": 0,
        "pct_w84": 0.0, "pct_w82": 0.0, "pct_baseline": 0.0,
    }
    if conn is None:
        return _fallback
    if not table_exists(conn, "narrative_cache"):
        return _fallback
    try:
        rows = q_all(conn, "SELECT narrative_source, COUNT(*) FROM narrative_cache GROUP BY narrative_source")
        counts = {r[0]: r[1] for r in rows}
    except Exception:
        return _fallback

    w84 = counts.get("w84", 0)
    w82 = counts.get("w82", 0)
    baseline = counts.get("baseline_no_edge", 0)
    total = sum(counts.values())
    return {
        "w84": w84,
        "w82": w82,
        "baseline_no_edge": baseline,
        "total": total,
        "pct_w84": round(w84 / total * 100, 1) if total else 0.0,
        "pct_w82": round(w82 / total * 100, 1) if total else 0.0,
        "pct_baseline": round(baseline / total * 100, 1) if total else 0.0,
    }


def _shm_js_str(names: list) -> str:
    """Encode a name list as a single-quoted JS string literal (\\n-separated).
    Single quotes inside names are escaped; result is safe inside onclick="...".
    """
    joined = "\\n".join(n.replace("\\", "\\\\").replace("'", "\\'") for n in names)
    return f"'{joined}'"


def _render_source_health_panel(shm: dict) -> str:
    """Render the full Source Health Monitor panel HTML — CSS-columns masonry layout."""
    if shm["system_score"] < 0:
        return '<div class="panel"><div class="panel-head"><span class="panel-title">Source Health Monitor</span></div><div style="padding:20px;color:#6b7280">Schema not migrated. Run scripts/health_schema_migration.py to enable.</div></div>'

    green = shm["green_count"]
    yellow = shm["yellow_count"]
    red = shm["red_count"]
    black = shm["black_count"]
    grey = shm.get("grey_count", black)
    total = shm.get("total_count", 42)
    score = shm["system_score"]
    score_cls = "c-green" if score >= 80 else ("c-amber" if score >= 50 else "c-red")

    # Source name lists for click-to-copy — encoded as safe JS string literals
    yellow_names = [
        d.get("source_name", "")
        for cat in _CATEGORY_ORDER
        for d in shm["sources_by_category"].get(cat, [])
        if (d.get("status") or "grey") == "yellow"
    ]
    red_names = [
        d.get("source_name", "")
        for cat in _CATEGORY_ORDER
        for d in shm["sources_by_category"].get(cat, [])
        if (d.get("status") or "grey") in ("red", "black")
    ]

    _COPY_STYLE = (
        "cursor:pointer;text-decoration:underline dotted;"
        "text-underline-offset:3px;user-select:none"
    )
    _COPY_FN = "shmCp"  # short name to keep onclick concise

    def _clickable_span(color: str, label: str, names: list) -> str:
        if not names:
            return f'<span style="color:{color}">&#9679; {label}</span>'
        js_str = _shm_js_str(names)
        return (
            f'<span style="color:{color};{_COPY_STYLE}" title="Click to copy names" '
            f'onclick="{_COPY_FN}({js_str},this)">&#9679; {label}</span>'
        )

    summary_bar = (
        f'<div style="display:flex;gap:16px;padding:8px 0 12px;font-size:13px;font-family:var(--font-m)">'
        + _clickable_span("#22c55e", f"{green} green", [])
        + _clickable_span("#f59e0b", f"{yellow} yellow", yellow_names)
        + _clickable_span("#ef4444", f"{red} red", red_names)
        + f'<span style="color:#6b7280">&#9679; {grey} idle</span>'
        + f'</div>'
    )

    critical_html = ""
    if shm["critical_issues"]:
        items_html = "".join(
            f'<div style="padding:3px 0;font-size:12px;font-family:var(--font-m)">'
            f'{_STATUS_DOT.get(d.get("status","black"),"")} '
            f'<b>{d.get("source_name","")}</b>'
            f'</div>'
            for d in shm["critical_issues"]
        )
        critical_html = (
            f'<div style="background:#1a0000;border:1px solid #ef4444;border-radius:6px;'
            f'padding:10px 14px;margin-bottom:14px">'
            f'<div style="font-size:11px;font-weight:700;color:#ef4444;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:6px">&#9888; Critical ({len(shm["critical_issues"])} sources)</div>'
            f'{items_html}'
            f'</div>'
        )

    # CSS columns: cards flow naturally — short cards pack below tall ones in each column
    cards_html = ""
    for cat in _CATEGORY_ORDER:
        sources = shm["sources_by_category"].get(cat, [])
        if not sources:
            continue
        cat_label = _CATEGORY_DISPLAY.get(cat, cat).split(" (")[0]

        src_rows = ""
        for d in sources:
            status = d.get("status") or "grey"
            dot = _STATUS_DOT.get(status, _STATUS_DOT["grey"])
            last_ok = d.get("last_success_at") or ""
            time_str = _relative_time(last_ok) if last_ok else "—"
            src_rows += (
                f'<div style="display:flex;align-items:center;gap:6px;padding:3px 0;'
                f'border-bottom:1px solid #1c1c1c;font-size:12px;font-family:var(--font-m)">'
                f'<span style="width:12px;flex-shrink:0">{dot}</span>'
                f'<span style="flex:1;color:#e5e7eb;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
                f'{d.get("source_name","")}</span>'
                f'<span style="color:#6b7280;white-space:nowrap;padding-left:6px">{time_str}</span>'
                f'</div>'
            )

        # break-inside:avoid-column + display:inline-block = card stays together in one column
        cards_html += (
            f'<div style="break-inside:avoid-column;display:inline-block;width:100%;'
            f'background:#111;border-radius:8px;padding:12px;margin-bottom:12px;box-sizing:border-box">'
            f'<div style="font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:8px">{cat_label}</div>'
            f'{src_rows}'
            f'</div>'
        )

    columns_html = (
        f'<div style="column-count:2;column-gap:12px">'
        f'{cards_html}'
        f'</div>'
    )

    # shmCp: textarea fallback works on HTTP; clipboard API used when available (HTTPS)
    copy_script = (
        '<script>'
        'if(!window.shmCp){'
        'window.shmCp=function(t,el){'
        'var old=el.textContent;'
        'var go=function(){'
        'var a=document.createElement("textarea");'
        'a.value=t.replace(/\\\\n/g,"\\n");'
        'a.style.cssText="position:fixed;opacity:0;top:0;left:0;width:1px;height:1px";'
        'document.body.appendChild(a);a.focus();a.select();'
        'try{document.execCommand("copy")}catch(e){}'
        'document.body.removeChild(a);'
        'el.textContent="Copied \u2713";'
        'setTimeout(function(){el.textContent=old},1500);'
        '};'
        'if(navigator.clipboard&&window.isSecureContext){'
        'navigator.clipboard.writeText(t.replace(/\\\\n/g,"\\n")).then(function(){'
        'el.textContent="Copied \u2713";setTimeout(function(){el.textContent=old},1500)'
        '}).catch(go)'
        '}else{go()}'
        '}}'
        '</script>'
    )

    return (
        f'<div class="panel">'
        f'<div class="panel-head"><span class="panel-title">Source Health Monitor</span>'
        f'<span class="panel-sub">{total} sources &middot; score <span class="{score_cls}">{score}%</span></span></div>'
        f'<div style="padding:0 18px 16px">'
        f'{summary_bar}'
        f'{critical_html}'
        f'{columns_html}'
        f'</div>'
        f'{copy_script}'
        f'</div>'
    )


def _render_exception_source_health(shm: dict) -> str:
    """Overview-tab compact source health. Shows critical/warning issues; category dots grid otherwise."""
    if shm["system_score"] < 0:
        return '<div class="panel"><div class="panel-head"><span class="panel-title">Source Health Monitor</span></div><div style="padding:16px;color:#6b7280;font-family:var(--font-m);font-size:12px">Schema not migrated.</div></div>'

    yellow = shm["yellow_count"]
    total = shm.get("total_count", 42)
    score = shm["system_score"]
    score_cls = "c-green" if score >= 80 else ("c-amber" if score >= 50 else "c-red")

    # Critical block
    crit_html = ""
    if shm["critical_issues"]:
        rows = "".join(
            f'<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px;font-family:var(--font-m)">'
            f'{_STATUS_DOT.get(d.get("status","black"),"")} '
            f'<span style="color:var(--text);font-weight:600;flex:1">{d.get("source_name","")}</span>'
            f'<span style="color:#ef4444">{_STATUS_DISPLAY.get(d.get("status",""), "UNKNOWN")}</span>'
            f'</div>'
            for d in shm["critical_issues"]
        )
        crit_html = (
            f'<div style="background:#1a0000;border:1px solid #ef4444;border-radius:6px;padding:10px 14px;margin-bottom:10px">'
            f'<div style="font-size:11px;font-weight:700;color:#ef4444;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">&#9888; Critical ({len(shm["critical_issues"])} sources)</div>'
            f'{rows}'
            f'</div>'
        )

    # Warn block: yellow sources
    warn_html = ""
    if yellow > 0:
        warn_src = [
            d for cat in _CATEGORY_ORDER
            for d in shm["sources_by_category"].get(cat, [])
            if (d.get("status") or "black") == "yellow"
        ]
        if warn_src:
            rows = "".join(
                f'<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px;font-family:var(--font-m)">'
                f'{_STATUS_DOT.get("yellow","")} '
                f'<span style="color:var(--text);flex:1">{d.get("source_name","")}</span>'
                f'<span style="color:var(--muted)">{_relative_time(d.get("last_success_at",""))}</span>'
                f'</div>'
                for d in warn_src
            )
            warn_html = (
                f'<details style="margin-bottom:8px">'
                f'<summary style="cursor:pointer;font-size:12px;font-family:var(--font-m);color:#f59e0b;padding:4px 0">'
                f'&#9679; {yellow} source{"s" if yellow != 1 else ""} degraded — expand</summary>'
                f'<div style="padding:6px 0 4px">{rows}</div>'
                f'</details>'
            )

    # Compact category grid — one dot per category, colour = worst status in that category
    cat_dots = ""
    _status_rank = {"red": 0, "black": 1, "yellow": 2, "green": 3, "grey": 4}
    for cat in _CATEGORY_ORDER:
        sources = shm["sources_by_category"].get(cat, [])
        if not sources:
            continue
        worst = min(sources, key=lambda d: _status_rank.get(d.get("status") or "grey", 4))
        w_status = worst.get("status") or "grey"
        dot = _STATUS_DOT.get(w_status, _STATUS_DOT["grey"])
        raw_label = _CATEGORY_DISPLAY.get(cat, cat)
        short_label = raw_label.split(" (")[0].replace(" & ", "/")
        cat_dots += (
            f'<div style="display:flex;align-items:center;gap:5px;font-size:12px;font-family:var(--font-m);color:#9ca3af">'
            f'{dot} <span>{short_label}</span>'
            f'</div>'
        )
    cat_grid = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;margin-top:4px">'
        f'{cat_dots}'
        f'</div>'
    )

    return (
        f'<div class="panel">'
        f'<div class="panel-head">'
        f'<span class="panel-title">Source Health Monitor</span>'
        f'<span class="panel-sub">{total} sources &middot; score <span class="{score_cls}">{score}%</span></span>'
        f'</div>'
        f'<div style="padding:12px 16px">'
        f'{crit_html}{warn_html}{cat_grid}'
        f'</div>'
        f'</div>'
    )


def _build_coverage_summary(coverage: list, p1_rows: str) -> str:
    """Compact per-sport coverage bars for Overview tab, with full matrix in accordion."""
    # Group by sport
    by_sport: dict = {}
    for c in coverage:
        sport = c["sport"]
        if sport not in by_sport:
            by_sport[sport] = {"total": 0, "card_ready": 0}
        by_sport[sport]["total"] += c["total"]
        by_sport[sport]["card_ready"] += c["card_ready"]

    bars_html = ""
    for sport, vals in sorted(by_sport.items()):
        total      = vals["total"]
        card_ready = vals["card_ready"]
        pct = round(card_ready / total * 100, 1) if total > 0 else 0
        fill_col = "#22c55e" if pct >= 80 else ("#f59e0b" if pct >= 40 else "#ef4444")
        bars_html += (
            f'<div class="cov-bar-row">'
            f'<span class="cov-bar-label">{sport}</span>'
            f'<div class="cov-bar-track"><div class="cov-bar-fill" style="width:{pct}%;background:{fill_col}"></div></div>'
            f'<span class="cov-bar-meta">{card_ready}/{total} · {pct}%</span>'
            f'</div>'
        )

    if not bars_html:
        bars_html = '<div style="color:var(--muted);font-size:12px;font-family:var(--font-m);padding:8px 0">No coverage data</div>'

    full_matrix = (
        f'<details style="margin-top:12px">'
        f'<summary style="cursor:pointer;font-family:var(--font-d);font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding:6px 0">Full League Breakdown &amp; Chart</summary>'
        f'<div style="margin-top:8px">'
        f'<div class="tbl-wrap tbl-fixed"><table class="tbl"><thead><tr><th>Sport</th><th>League</th><th>Matches</th><th>Card Data</th><th>Coverage %</th><th>Status</th></tr></thead><tbody>{p1_rows}</tbody></table></div>'
        f'<div class="chart-wrap"><canvas id="coverageChart"></canvas></div>'
        f'</div>'
        f'</details>'
    )

    return (
        f'<div class="panel">'
        f'<div class="panel-head"><span class="panel-title">Sport Coverage</span><span class="panel-sub">Next 7 days &middot; card-data availability</span></div>'
        f'<div style="padding:12px 16px">'
        f'{bars_html}'
        f'{full_matrix}'
        f'</div>'
        f'</div>'
    )


# -- Edge Tier Distribution panel (QW2) ---------------------------------------

def build_edge_tier_panel(conn) -> str:
    """Build HTML panel showing daily edge counts by tier for last 7 days."""
    if conn is None or not table_exists(conn, "edge_results"):
        return ""
    try:
        rows = q_all(conn, """
            SELECT date(recommended_at) AS day, edge_tier, COUNT(*) AS cnt
            FROM edge_results
            WHERE date(recommended_at) >= date('now', '-7 days')
            GROUP BY day, edge_tier
            ORDER BY day DESC, edge_tier
        """)
    except Exception:
        return ""
    if not rows:
        return ""

    # Build day → tier → count map
    days: list[str] = []
    data: dict[str, dict[str, int]] = {}
    for r in rows:
        day = r["day"]
        if day not in data:
            data[day] = {}
            days.append(day)
        data[day][r["edge_tier"]] = r["cnt"]

    tiers = [("diamond", "💎 Diamond", "#a78bfa"), ("gold", "🥇 Gold", "#F8C830"),
              ("silver", "🥈 Silver", "#9ca3af"), ("bronze", "🥉 Bronze", "#b45309")]

    # Table rows (most recent first)
    table_rows = ""
    for day in sorted(data.keys(), reverse=True):
        d = data[day]
        total = sum(d.values())
        table_rows += (
            f'<tr>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;color:var(--muted)">{day}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:13px;font-weight:700;color:#a78bfa">{d.get("diamond", 0)}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:13px;font-weight:700;color:#F8C830">{d.get("gold", 0)}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:13px;color:#9ca3af">{d.get("silver", 0)}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:13px;color:#b45309">{d.get("bronze", 0)}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;color:var(--text)">{total}</td>'
            f'</tr>'
        )

    # Chart data (chronological order)
    chart_days = json.dumps(sorted(data.keys()))
    chart_data = {t_key: json.dumps([data.get(d, {}).get(t_key, 0) for d in sorted(data.keys())])
                  for t_key, _, _ in tiers}

    return f"""<div class="panel">
  <div class="panel-head"><span class="panel-title">Edge Tier Distribution</span><span class="panel-sub">Last 7 days &middot; Diamond / Gold / Silver / Bronze</span></div>
  <div class="tbl-wrap"><table class="tbl">
    <thead><tr><th>Date</th><th>&#x1F48E; Diamond</th><th>&#x1F947; Gold</th><th>&#x1F948; Silver</th><th>&#x1F949; Bronze</th><th>Total</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table></div>
  <div class="chart-wrap"><canvas id="tierChart" style="height:160px"></canvas></div>
</div>
<script>
(function(){{
  var days = {chart_days};
  var ctx = document.getElementById('tierChart');
  if (!ctx || !days.length) return;
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: days,
      datasets: [
        {{ label: '💎 Diamond', data: {chart_data["diamond"]}, backgroundColor: 'rgba(167,139,250,0.85)', borderRadius: 4 }},
        {{ label: '🥇 Gold',    data: {chart_data["gold"]},    backgroundColor: 'rgba(248,200,48,0.85)',  borderRadius: 4 }},
        {{ label: '🥈 Silver',  data: {chart_data["silver"]},  backgroundColor: 'rgba(156,163,175,0.7)', borderRadius: 4 }},
        {{ label: '🥉 Bronze',  data: {chart_data["bronze"]},  backgroundColor: 'rgba(180,83,9,0.7)',    borderRadius: 4 }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
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
</script>"""


# -- Data Health content renderer ---------------------------------------------

def render_health_content(conn, db_status: str) -> str:
    """Render the Data Health inner content HTML (no shell)."""
    coverage = build_coverage_matrix(conn)
    scrapers  = build_scraper_health(conn)
    sources   = build_source_freshness(conn)
    quotas    = build_api_quotas(conn)
    alerts    = build_alerts(conn, coverage)
    shm       = build_source_health_monitor(conn)
    cpg       = build_card_population_gate(conn)
    updated   = datetime.now(_SAST).strftime("%Y-%m-%d %H:%M:%S")

    alert_count = len(alerts)

    # -- KPI metrics --
    active_scrapers  = sum(1 for s in scrapers if s.get("has_data_24h", False))
    matches_24h      = sum(s["matches_24h"] for s in scrapers)
    total_card_ready = sum(c["card_ready"] for c in coverage)
    total_matches_c  = sum(c["total"] for c in coverage)
    coverage_pct     = round(total_card_ready / total_matches_c * 100, 1) if total_matches_c > 0 else 0

    # edges_produced_today (QW1)
    edges_today = 0
    edges_yesterday = 0
    if conn and table_exists(conn, "edge_results"):
        try:
            r = q_one(conn, "SELECT COUNT(*) AS cnt FROM edge_results WHERE date(recommended_at) = date('now')")
            edges_today = r["cnt"] if r else 0
            r2 = q_one(conn, "SELECT COUNT(*) AS cnt FROM edge_results WHERE date(recommended_at) = date('now','-1 day')")
            edges_yesterday = r2["cnt"] if r2 else 0
        except Exception:
            pass
    edges_delta = edges_today - edges_yesterday
    edges_delta_str = (f"+{edges_delta}" if edges_delta > 0 else str(edges_delta)) if edges_yesterday > 0 else ""
    edges_cls = "c-green" if edges_today > 0 else "c-amber"

    def chip(css_key: str, text: str) -> str:
        cls = {"s-green": "chip-green", "s-amber": "chip-amber",
               "s-red": "chip-red", "s-black": "chip-gray",
               "s-grey": "chip-gray"}.get(css_key, "chip-gray")
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

    # -- Billing alert banner (AC-15) --
    billing_alerts = _check_billing_alerts()
    billing_html = ""
    if billing_alerts:
        items_html = "".join(
            f'<span style="margin-right:16px"><b>{a["service"]}</b>: {a["title"][:60]}&hellip; '
            f'({a["count"]} events) <a href="{a["billing_url"]}" target="_blank" '
            f'style="color:#fff;text-decoration:underline">Fix billing &rarr;</a></span>'
            for a in billing_alerts
        )
        billing_html = (
            f'<div class="billing-alert">'
            f'&#9888; BILLING ALERT &mdash; Pipeline is degraded: {items_html}'
            f'</div>'
        )

    # -- Panel 1: Coverage Matrix rows --
    p1_rows = ""
    if coverage:
        for c in coverage:
            p1_rows += (
                "<tr>"
                + td(c["sport"].capitalize())
                + td(c["league"])
                + td(c["total"])
                + td(c["card_ready"], "s-green" if c["card_ready"] > 0 else "s-grey")
                + td(f"{c['pct']}%", c["css"])
                + td(c["badge"])
                + "</tr>"
            )
    else:
        p1_rows = '<tr><td colspan="6" style="text-align:center;color:#6b7280;padding:20px">No upcoming matches in next 7 days</td></tr>'

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

        if "_low" in q:
            rcss = "s-red" if q["_low"] else "s-green"
        elif remain is not None and limit:
            pct = remain / limit
            rcss = "s-green" if pct > 0.5 else ("s-amber" if pct > 0.2 else "s-red")
        else:
            rcss = "s-grey"

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
    chart_labels     = json.dumps([_chart_label(c["league"]) for c in coverage])
    chart_card_ready = json.dumps([c["card_ready"]  for c in coverage])
    chart_needs_data = json.dumps([c["needs_data"]  for c in coverage])

    active_cls = "c-green" if active_scrapers == len(scrapers) else ("c-amber" if active_scrapers > 0 else "c-red")
    cov_cls = "c-green" if coverage_pct >= 80 else ("c-amber" if coverage_pct >= 40 else "c-red")
    alert_cls = "c-red" if alert_count > 5 else ("c-amber" if alert_count > 0 else "c-green")

    # -- Source Health Monitor KPI values --
    shm_score = shm["system_score"]
    shm_score_cls = "c-green" if shm_score >= 80 else ("c-amber" if shm_score >= 50 else ("c-red" if shm_score >= 0 else "c-text"))
    shm_score_display = f"{shm_score}" if shm_score >= 0 else "N/A"
    shm_green = shm["green_count"]
    shm_total = shm.get("total_count", 42)

    # -- Source Health Monitor panel --
    shm_panel = _render_source_health_panel(shm)

    # -- Card Population Gate panel --
    cpg_panel = _render_card_population_gate_panel(cpg)

    # -- Edge Tier Distribution panel (QW2) --
    tier_panel = build_edge_tier_panel(conn)

    # -- Clickable RED KPI helpers (AC-14) --
    def _kpi_onclick(metric_name: str, current_val: str, expected_val: str, db_path: str = "~/scrapers/odds.db") -> str:
        """Return onclick attribute for a RED-state KPI (copies COO investigation prompt)."""
        ts = updated
        return (
            f'onclick="copyPrompt(\'{metric_name}\',\'{current_val}\',\'{expected_val}\',\'{ts}\',\'{db_path}\')" '
            f'class="kpi kpi-clickable" title="Click to copy investigation prompt"'
        )

    scraper_kpi_attr = _kpi_onclick("Active Scrapers", str(active_scrapers), str(len(scrapers))) if active_cls == "c-red" else 'class="kpi"'
    cov_kpi_attr = _kpi_onclick("Card Coverage", f"{coverage_pct}%", ">80%", "~/bot/data/mzansiedge.db") if cov_cls == "c-red" else 'class="kpi"'
    alert_kpi_attr = _kpi_onclick("Active Alerts", str(alert_count), "<5", "~/scrapers/odds.db") if alert_cls == "c-red" else 'class="kpi"'
    shm_kpi_attr = _kpi_onclick("System Health", f"{shm_score_display}%", ">80%", "~/scrapers/odds.db") if shm_score_cls == "c-red" else 'class="kpi"'

    return f"""{topbar}
{billing_html}
<div class="page">
  <div class="kpi-strip">
    <div {shm_kpi_attr}><div class="kpi-lbl">System Health</div><div class="kpi-val {shm_score_cls}">{shm_score_display}<span style="font-size:14px;color:var(--muted);font-weight:400">%</span></div><div class="kpi-sub">{shm_green}/{shm_total} sources green</div></div>
    <div class="kpi"><div class="kpi-lbl">Edges Today</div><div class="kpi-val {edges_cls}">{edges_today}<span style="font-size:14px;color:var(--muted);font-weight:400">{' ' + edges_delta_str if edges_delta_str else ''}</span></div><div class="kpi-sub">vs {edges_yesterday} yesterday</div></div>
    <div {scraper_kpi_attr}><div class="kpi-lbl">Active Scrapers</div><div class="kpi-val {active_cls}">{active_scrapers}<span style="font-size:14px;color:var(--muted);font-weight:400">/{len(scrapers)}</span></div><div class="kpi-sub">bookmakers online</div></div>
    <div class="kpi"><div class="kpi-lbl">Matches Scraped</div><div class="kpi-val c-gold">{matches_24h:,}</div><div class="kpi-sub">last 24 hours</div></div>
    <div {cov_kpi_attr}><div class="kpi-lbl">Card Coverage</div><div class="kpi-val {cov_cls}">{coverage_pct}<span style="font-size:14px;color:var(--muted);font-weight:400">%</span></div><div class="kpi-sub">2+ SA bookmakers &middot; next 7d</div></div>
    <div {alert_kpi_attr}><div class="kpi-lbl">Active Alerts</div><div class="kpi-val {alert_cls}">{alert_count}</div><div class="kpi-sub">pipeline issues</div></div>
    <div class="kpi"><div class="kpi-lbl">Leagues Tracked</div><div class="kpi-val c-text">{total_matches_c}</div><div class="kpi-sub">upcoming matches (7d)</div></div>
  </div>

  {shm_panel}

  {tier_panel}

  {cpg_panel}

  <div class="panel">
    <div class="panel-head"><span class="panel-title">Sport Coverage Matrix</span><span class="panel-sub">Next 7 days &middot; card-data availability</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Sport</th><th>League</th><th>Matches</th><th>Card Data</th><th>Coverage %</th><th>Status</th></tr></thead><tbody>{p1_rows}</tbody></table></div>
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
  var labels        = {chart_labels};
  var cardReadyData = {chart_card_ready};
  var needsDataData = {chart_needs_data};
  var ctx = document.getElementById('coverageChart');
  if (!ctx || !labels.length) return;
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [
        {{ label: 'Card Data (2+ bk)', data: cardReadyData, backgroundColor: 'rgba(34,197,94,0.8)', borderRadius: 4 }},
        {{ label: 'Needs Data',        data: needsDataData, backgroundColor: 'rgba(239,68,68,0.65)',  borderRadius: 4 }},
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
    var labels        = {chart_labels};
    var cardReadyData = {chart_card_ready};
    var needsDataData = {chart_needs_data};
    var ctx = document.getElementById('coverageChart');
    if (!ctx || !labels.length) return;
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: labels,
        datasets: [
          {{ label: 'Card Data (2+ bk)', data: cardReadyData, backgroundColor: 'rgba(34,197,94,0.8)', borderRadius: 4 }},
          {{ label: 'Needs Data',        data: needsDataData, backgroundColor: 'rgba(239,68,68,0.65)',  borderRadius: 4 }},
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

function copyPrompt(metricName, currentValue, expectedValue, lastTs, dbPath) {{
  var prompt = 'Investigate: ' + metricName + ' showing ' + currentValue + ' (expected: ' + expectedValue + ').\\n' +
    'Last data: ' + lastTs + '. Server: 178.128.171.28\\n' +
    'Relevant path: ' + dbPath + '\\n' +
    'Steps: Check cron schedule, review logs, verify DB connectivity, check Sentry for related errors.';
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(prompt).then(function() {{
      var toast = document.getElementById('copy-toast');
      if (!toast) {{
        toast = document.createElement('div');
        toast.id = 'copy-toast';
        toast.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#22c55e;color:#000;padding:8px 16px;border-radius:6px;font-size:13px;z-index:9999;font-family:sans-serif';
        document.body.appendChild(toast);
      }}
      toast.textContent = 'Prompt copied \u2713';
      toast.style.display = 'block';
      setTimeout(function() {{ toast.style.display = 'none'; }}, 2000);
    }});
  }}
}}
</script>"""


# -- Automation content renderer ----------------------------------------------

def render_automation_content() -> str:
    """Render the Social Media view inner content HTML."""
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
    fourteen_days = now_utc + timedelta(days=14)

    # Categorise items
    published_today = []
    scheduled = []
    awaiting_approval = []
    failed_blocked = []
    recent_publishes = []
    all_active = []
    schedule_items = []   # for Schedule tab: Approved/Awaiting/Drafting/Briefed + has scheduled_time within 14d

    for item in items:
        status = (item.get("status") or "").lower().strip()
        sched_raw = item.get("scheduled_time") or ""

        if status in ("published", "done", "complete"):
            created = item.get("last_edited") or item.get("created") or ""
            if created and today_str in created[:10]:
                published_today.append(item)
            dt = parse_ts(created or item.get("scheduled_time"))
            if dt and (now_utc - dt).total_seconds() < 86400:
                recent_publishes.append(item)
        elif status in ("failed", "blocked", "error"):
            failed_blocked.append(item)
        elif status in ("approved", "ready", "scheduled"):
            scheduled.append(item)
        elif status in ("awaiting approval", "draft", "review", "pending", "in review", "awaiting", "in progress"):
            awaiting_approval.append(item)
        elif status in ("drafting", "briefed"):
            pass  # fall through to schedule_items below

        if status not in ("published", "done", "complete", "archived"):
            all_active.append(item)

        # Schedule tab: approved/awaiting/drafting/briefed + scheduled_time within 14 days
        if status in ("approved", "awaiting approval", "drafting", "briefed", "draft", "ready", "scheduled"):
            sched_dt = parse_ts(sched_raw)
            if sched_dt and now_utc <= sched_dt <= fourteen_days:
                schedule_items.append(item)

    # Sort
    scheduled.sort(key=lambda x: x.get("scheduled_time") or "9999")
    awaiting_approval.sort(key=lambda x: x.get("scheduled_time") or x.get("created") or "9999")
    recent_publishes.sort(key=lambda x: x.get("last_edited") or x.get("created") or "9999", reverse=True)
    schedule_items.sort(key=lambda x: x.get("scheduled_time") or "9999")

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

        if status in ("approved", "ready", "scheduled", "awaiting approval"):
            sched = item.get("scheduled_time") or ""
            sched_dt = parse_ts(sched)
            if sched_dt and sched_dt > now_utc:
                if channel_stats[ch_key]["next_scheduled_ts"] is None or sched_dt < channel_stats[ch_key]["next_scheduled_ts"]:
                    channel_stats[ch_key]["next_scheduled_ts"] = sched_dt
                    channel_stats[ch_key]["next_scheduled"] = sched

    # -- Local helpers --
    def _channel_chip(ch_key: str) -> str:
        ch = _CHANNEL_MAP.get(ch_key)
        if not ch:
            return f'<span class="ch-chip" style="background:rgba(107,114,128,0.15);color:var(--muted)">{ch_key or "?"}</span>'
        return (f'<span class="ch-chip" style="background:{ch["color"]}22;color:{ch["color"]};'
                f'border:1px solid {ch["color"]}33"><span class="ch-dot" style="background:{ch["color"]}"></span>'
                f'{ch["label"]}</span>')

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

    def _media_type_label(asset_link: str = "", channel: str = "", work_type: str = "") -> str:
        """Smart media type detection: returns 'Video', 'Image', or 'Post'."""
        ch_low = channel.lower().strip()
        wt_low = work_type.lower().strip()
        # TikTok is always video
        if "tiktok" in ch_low:
            return "Video"
        # BRU work type = video (Brand Response Unit)
        if wt_low == "bru":
            return "Video"
        # Detect from asset extension
        if asset_link and "." in asset_link:
            ext = asset_link.rsplit(".", 1)[-1].lower().split("?")[0]
            if ext in ("mp4", "mov", "webm", "avi"):
                return "Video"
            if ext in ("jpg", "jpeg", "png", "gif", "webp"):
                return "Image"
        return "Post"

    def _media_preview(asset_link: str, max_height: str = "300px", channel: str = "", work_type: str = "") -> str:
        if not asset_link:
            label = _media_type_label("", channel, work_type)
            return f'<span style="color:var(--muted);font-size:11px;font-family:var(--font-m)">{label}</span>'
        ext = asset_link.rsplit(".", 1)[-1].lower().split("?")[0] if "." in asset_link else ""
        if ext in ("mp4", "mov", "webm"):
            return (f'<video src="{asset_link}" controls '
                    f'style="max-height:{max_height};border-radius:4px;display:block;margin-top:10px;width:auto;"></video>')
        elif ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return (f'<img src="{asset_link}" alt="post asset" '
                    f'style="max-height:{max_height};border-radius:4px;object-fit:cover;display:block;margin-top:10px;">')
        else:
            label = _media_type_label(asset_link, channel, work_type)
            return f'<span style="color:var(--muted);font-size:11px;font-family:var(--font-m)">{label}</span>'

    def _media_thumb(asset_link: str) -> str:
        """Thumbnail for Recent Publishes table (max 120px)."""
        return _media_preview(asset_link, max_height="120px")

    # -- Topbar --
    banner = ""
    if cache_age_str:
        banner = f'<div class="banner banner-warn">{cache_age_str}</div>'
    elif not notion_ok:
        banner = '<div class="banner banner-err">Notion unavailable -- no cached data</div>'

    topbar = f"""<nav class="topbar">
  <div class="topbar-left"><div class="topbar-pill">Social Media</div></div>
  <div class="topbar-right"><div class="topbar-meta">Updated <em>{updated} SAST</em></div></div>
</nav>
{banner}"""

    # ── KPI numbers (shared across Feed tab) ───────────────────────────────
    pub_today_count = len(published_today)
    scheduled_count = len(scheduled)
    awaiting_count  = len(awaiting_approval)
    failed_count    = len(failed_blocked)
    total_queue     = len(all_active)

    pub_cls   = "c-green" if pub_today_count > 0 else "c-text"
    sched_cls = "c-gold"
    await_cls = "c-amber" if awaiting_count > 0 else "c-text"
    fail_cls  = "c-red"   if failed_count > 0  else "c-text"

    kpi_strip = f"""<div class="kpi-strip">
    <div class="kpi"><div class="kpi-lbl">Published Today</div><div class="kpi-val {pub_cls}">{pub_today_count}</div><div class="kpi-sub">posts sent</div></div>
    <div class="kpi"><div class="kpi-lbl">Scheduled</div><div class="kpi-val {sched_cls}">{scheduled_count}</div><div class="kpi-sub">approved &amp; queued</div></div>
    <div class="kpi kpi-clickable" onclick="window._navToView('task_hub')" title="View approval pipeline"><div class="kpi-lbl">Awaiting Approval</div><div class="kpi-val {await_cls}">{awaiting_count}</div><div class="kpi-sub">{"tap to review" if awaiting_count > 0 else "all clear"}</div></div>
    <div class="kpi"><div class="kpi-lbl">Failed / Blocked</div><div class="kpi-val {fail_cls}">{failed_count}</div><div class="kpi-sub">{"action needed" if failed_count > 0 else "all clear"}</div></div>
    <div class="kpi"><div class="kpi-lbl">Total Queue</div><div class="kpi-val c-text">{total_queue}</div><div class="kpi-sub">active items</div></div>
  </div>"""

    # ── Channel Status Grid ────────────────────────────────────────────────
    channel_cards = ""
    for ch in _CHANNELS:
        cs = channel_stats[ch["key"]]
        last_ts = cs.get("last_published_ts")
        if cs["last_failed"]:
            dot_color, dot_title = "var(--red)", "Last action failed"
        elif last_ts:
            age_h = (now_utc - last_ts).total_seconds() / 3600
            if age_h < 6:
                dot_color, dot_title = "var(--green)", "Active (< 6h)"
            elif age_h < 24:
                dot_color, dot_title = "var(--amber)", "Stale (6-24h)"
            else:
                dot_color, dot_title = "var(--red)", "Inactive (> 24h)"
        else:
            dot_color, dot_title = "var(--muted)", "No publishes yet"

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
    <div class="panel-head"><span class="panel-title">Channel Status</span><span class="panel-sub">8 channels &middot; last publish freshness</span></div>
    <div class="channel-grid">{channel_cards}</div>
  </div>"""

    # ── Failed & Blocked ───────────────────────────────────────────────────
    failed_html = ""
    if failed_blocked:
        rows = ""
        for item in failed_blocked:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            page_id = item.get("id", "")
            rows += (
                f'<tr id="fb-{page_id}">'
                + td(_channel_chip(ch_key))
                + td(_truncate(item.get("title"), 50))
                + td(_status_chip(item.get("status") or ""))
                + td(_truncate(item.get("error"), 80) or "\u2014", extra_style="color:var(--red)")
                + td(_sast_hhmm(item.get("scheduled_time")))
                + td(_relative_time(item.get("created")))
                + td(f'<button class="btn-dismiss" data-id="{page_id}">Dismiss</button>')
                + "</tr>"
            )
        failed_html = f"""<div class="panel panel-red-accent">
    <div class="panel-head"><span class="panel-title" style="color:var(--red)">Failed &amp; Blocked</span><span class="panel-sub">{len(failed_blocked)} items need attention</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Channel</th><th>Title</th><th>Status</th><th>Error / Reason</th><th>Scheduled</th><th>Age</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
  </div>"""

    # ── Recent Publishes (with inline media) ───────────────────────────────
    recent_html = ""
    if recent_publishes:
        rows = ""
        for item in recent_publishes[:30]:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            ts = item.get("last_edited") or item.get("scheduled_time") or item.get("created") or ""
            url = item.get("url") or ""
            url_cell = f'<a href="{url}" target="_blank" style="color:var(--gold);font-size:11px">View post</a>' if url else "\u2014"
            media_cell = _media_thumb(item.get("asset_link") or "")
            rows += (
                "<tr>"
                + td(media_cell, css="", extra_style="padding:6px 14px;min-width:100px")
                + td(_sast_hhmm(ts))
                + td(_channel_chip(ch_key))
                + td(_truncate(item.get("title"), 50))
                + td(url_cell)
                + td(_truncate(item.get("copy"), 60), extra_style="color:var(--muted);white-space:normal;max-width:300px")
                + "</tr>"
            )
        recent_html = f"""<div class="panel">
    <div class="panel-head"><span class="panel-title">Recent Publishes</span><span class="panel-sub">Last 24h &middot; {len(recent_publishes)} items</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Media</th><th>Time</th><th>Channel</th><th>Title</th><th>URL</th><th>Copy Preview</th></tr></thead><tbody>{rows}</tbody></table></div>
  </div>"""

    # ── Approval Queue cards ───────────────────────────────────────────────
    # Strictly match Notion status "Awaiting Approval"
    approval_queue_items = [i for i in items if (i.get("status") or "").strip().lower() == "awaiting approval"]
    approval_queue_items.sort(key=lambda x: x.get("scheduled_time") or x.get("created") or "9999")

    if approval_queue_items:
        appr_cards = ""
        for item in approval_queue_items:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            sched_str = _sast_hhmm(item.get("scheduled_time")) + " SAST" if item.get("scheduled_time") else "\u2014"
            campaign = _truncate(item.get("campaign_theme") or "", 40)
            copy_text = item.get("copy") or ""
            item_channel = item.get("channel") or ""
            item_work_type = item.get("work_type") or ""
            item_platform_notes = item.get("platform_notes") or ""
            media_html = _media_preview(item.get("asset_link") or "", channel=item_channel, work_type=item_work_type)
            # TikTok filename from Platform Notes
            tiktok_file_html = ""
            if "tiktok" in item_channel.lower() and item_platform_notes:
                _fn_match = re.search(r'[Ff]ile:\s*(.+)', item_platform_notes)
                if _fn_match:
                    tiktok_file_html = (f'<div style="margin-top:6px;font-size:11px;color:var(--amber);'
                                        f'font-family:var(--font-m)">&#128193; File to upload: '
                                        f'<code>{_fn_match.group(1).strip()}</code></div>')
            page_id = item.get("id", "")
            appr_cards += f"""<div class="appr-card" id="appr-{page_id}">
  <div class="appr-header">
    {_channel_chip(ch_key)}
    <span class="appr-meta">&#128337; {sched_str}</span>
    {f'<span class="appr-campaign">{campaign}</span>' if campaign else ""}
  </div>
  <div class="appr-copy">{copy_text}</div>
  {media_html}
  {tiktok_file_html}
  <div class="appr-error" style="display:none;color:var(--red);font-size:11px;margin-top:8px"></div>
  <div class="appr-actions">
    <button class="btn-approve" data-id="{page_id}">Approve</button>
    <button class="btn-archive" data-id="{page_id}">Archive</button>
  </div>
</div>"""
        approval_tab_content = f'<div id="appr-list">{appr_cards}</div>'
    else:
        approval_tab_content = '<div class="empty-state">No posts awaiting approval.</div>'

    # ── Schedule tab: 14-day lookahead table ───────────────────────────────
    # Map items into cells: {date_str: {ch_key: [items]}}
    channel_keys = [c["key"] for c in _CHANNELS]
    sched_grid: dict[str, dict[str, list]] = {}
    for i in range(14):
        day = (now_sast + timedelta(days=i)).strftime("%Y-%m-%d")
        sched_grid[day] = {k: [] for k in channel_keys}

    for item in schedule_items:
        sdt = parse_ts(item.get("scheduled_time") or "")
        if not sdt:
            continue
        sdt_sast = sdt.astimezone(_SAST)
        day_key = sdt_sast.strftime("%Y-%m-%d")
        if day_key not in sched_grid:
            continue
        ch_key = _normalise_channel_key(item.get("channel") or "")
        if ch_key in sched_grid[day_key]:
            sched_grid[day_key][ch_key].append(item)

    def _sched_status_color(status: str) -> str:
        low = status.lower().strip()
        if low in ("approved", "ready", "scheduled"):
            return "var(--green)"
        elif low in ("awaiting approval", "awaiting"):
            return "var(--amber)"
        else:
            return "var(--muted)"

    # Schedule table header
    ch_headers = "".join(f'<th style="min-width:90px">{c["label"]}</th>' for c in _CHANNELS)
    sched_rows = ""
    for i in range(14):
        day_dt = now_sast + timedelta(days=i)
        day_key = day_dt.strftime("%Y-%m-%d")
        day_label = "Today" if i == 0 else ("Tomorrow" if i == 1 else day_dt.strftime("%a %d %b"))
        cells = ""
        for ch in _CHANNELS:
            day_items = sched_grid[day_key].get(ch["key"], [])
            if not day_items:
                cells += "<td></td>"
            else:
                cell_html = ""
                for it in day_items:
                    title = _truncate(it.get("title") or it.get("copy") or "", 40)
                    status = it.get("status") or ""
                    color = _sched_status_color(status)
                    page_id = it.get("id", "")
                    cell_html += (f'<div class="sched-cell-item" data-id="{page_id}" '
                                  f'style="border-left:2px solid {color};padding:2px 6px;margin-bottom:3px;'
                                  f'cursor:pointer;font-size:11px;font-family:var(--font-m);">'
                                  f'{title}</div>')
                cells += f"<td>{cell_html}</td>"
        sched_rows += f"<tr><td style='white-space:nowrap;font-weight:600'>{day_label}</td>{cells}</tr>"

    schedule_table = f"""<div class="panel">
    <div class="panel-head"><span class="panel-title">14-Day Schedule</span><span class="panel-sub">Approved · Awaiting · Drafting · Briefed</span></div>
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th>Day</th>{ch_headers}</tr></thead>
      <tbody id="sched-body">{sched_rows}</tbody>
    </table></div>
  </div>
  <div id="sched-modal" style="display:none;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:20px;margin-top:12px"></div>"""

    automation_js = """<style>
.btn-dismiss{background:rgba(239,68,68,.08);color:var(--red);border:1px solid rgba(239,68,68,.2);border-radius:6px;padding:5px 14px;font-family:var(--font-d);font-weight:700;font-size:11px;cursor:pointer;transition:background 150ms;white-space:nowrap;}
.btn-dismiss:hover{background:rgba(239,68,68,.18);}
.btn-dismiss:disabled{opacity:.5;cursor:not-allowed;}
</style>
<script>
(function(){
  document.querySelectorAll('.btn-dismiss').forEach(function(btn){
    btn.addEventListener('click', function(){
      var id = this.dataset.id;
      var row = document.getElementById('fb-' + id);
      btn.disabled = true;
      fetch('/admin/api/dismiss-item', {
        method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({page_id: id})
      }).then(function(r){
        if(r.ok){
          row.style.transition='opacity 0.4s';
          row.style.opacity='0';
          setTimeout(function(){ row.remove(); }, 400);
        } else { btn.disabled = false; }
      }).catch(function(){ btn.disabled = false; });
    });
  });
})();
</script>"""

    return f"""{topbar}
<div class="page">
  {kpi_strip}
  {channel_panel}
  {failed_html}
  {recent_html}
  <div class="footer">MzansiEdge Social Media &middot; Notion-powered</div>
</div>
{automation_js}"""


# -- Approvals view -----------------------------------------------------------

_APPROVALS_NOTION_URL = "https://www.notion.so/Marketing-Ops-Queue"

def render_approvals_content() -> str:
    """Render the Approvals pipeline view inner content HTML."""
    now_utc = datetime.now(timezone.utc)
    now_sast = now_utc.astimezone(_SAST)
    updated = now_sast.strftime("%Y-%m-%d %H:%M:%S")

    cache_error = False
    banner = ""
    items: list[dict] = []

    try:
        items, fetch_time = _fetch_marketing_queue()
        cache_age_min = (time.monotonic() - fetch_time) / 60
        if cache_age_min > 1:
            banner = f'<div class="banner banner-warn">Showing cached data ({cache_age_min:.0f}m ago)</div>'
    except Exception:
        cache_error = True
        with _notion_cache_lock:
            cached_entry = _notion_cache.get("marketing_queue")
            if cached_entry:
                items = cached_entry[0]
                age_min = (time.monotonic() - cached_entry[1]) / 60
                banner = f'<div class="banner banner-warn">Notion unavailable — cached data ({age_min:.0f}m ago)</div>'
            else:
                banner = '<div class="banner banner-err">Unable to load approvals — Notion unavailable. <a href="/admin/approvals" style="color:var(--gold)">Retry</a></div>'

    approval_items = [i for i in items if (i.get("status") or "").strip().lower() == "awaiting approval"]
    approval_items.sort(key=lambda x: x.get("scheduled_time") or x.get("created") or "9999")

    has_more = len(approval_items) > 10
    shown_items = approval_items[:10]
    total_count = len(approval_items)

    topbar = f"""<nav class="topbar">
  <div class="topbar-left"><div class="topbar-pill">Approvals</div></div>
  <div class="topbar-right"><div class="topbar-meta">Updated <em>{updated} SAST</em></div></div>
</nav>
{banner}"""

    def _ch_chip(ch_key: str) -> str:
        ch = _CHANNEL_MAP.get(ch_key)
        if not ch:
            return f'<span class="ch-chip" style="background:rgba(107,114,128,0.15);color:var(--muted)">{ch_key or "?"}</span>'
        return (f'<span class="ch-chip" style="background:{ch["color"]}22;color:{ch["color"]};'
                f'border:1px solid {ch["color"]}33"><span class="ch-dot" style="background:{ch["color"]}"></span>'
                f'{ch["label"]}</span>')

    def _media_prev(asset_link: str) -> str:
        if not asset_link:
            return ""
        ext = asset_link.rsplit(".", 1)[-1].lower().split("?")[0] if "." in asset_link else ""
        if ext in ("mp4", "mov", "webm"):
            return (f'<video src="{asset_link}" controls '
                    f'style="max-height:280px;border-radius:4px;display:block;margin-top:10px;width:auto;"></video>')
        elif ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return (f'<img src="{asset_link}" alt="post asset" '
                    f'style="max-height:280px;border-radius:4px;object-fit:cover;display:block;margin-top:10px;">')
        return ""

    if cache_error and not items:
        body_html = banner  # error already shown in topbar banner
    elif not approval_items:
        body_html = """<div class="empty-state-done">
  <div class="empty-state-done-icon">&#10003;</div>
  <div class="empty-state-done-text">All caught up</div>
  <div class="empty-state-done-sub">No posts awaiting approval right now.</div>
</div>"""
    else:
        count_label = f"{total_count} item{'s' if total_count != 1 else ''} awaiting approval"
        more_link = (f'<a class="appr-notion-link" href="{_APPROVALS_NOTION_URL}" target="_blank">'
                     f'View all {total_count} in Notion →</a>') if has_more else ""
        cards_html = ""
        for item in shown_items:
            ch_key = _normalise_channel_key(item.get("channel") or "")
            sched_str = _sast_hhmm(item.get("scheduled_time")) + " SAST" if item.get("scheduled_time") else "\u2014"
            campaign = _truncate(item.get("campaign_theme") or "", 40)
            copy_text = item.get("copy") or ""
            media_html = _media_prev(item.get("asset_link") or "")
            page_id = item.get("id", "")
            cards_html += f"""<div class="appr-card" id="appr-pl-{page_id}">
  <div class="appr-header">
    {_ch_chip(ch_key)}
    <span class="appr-meta">&#128337; {sched_str}</span>
    {f'<span class="appr-campaign">{campaign}</span>' if campaign else ""}
  </div>
  <div class="appr-copy">{copy_text}</div>
  {media_html}
  <div class="appr-error" style="display:none;color:var(--red);font-size:11px;margin-top:8px"></div>
  <div class="appr-actions">
    <button class="btn-approve" data-id="{page_id}">Approve</button>
    <button class="btn-archive" data-id="{page_id}">Archive</button>
  </div>
</div>"""

        body_html = f"""<div class="panel">
  <div class="appr-pipeline-header">
    <span class="appr-count-badge">{count_label}</span>
    {more_link}
  </div>
  <div id="appr-pipeline-list">{cards_html}</div>
</div>"""

    approvals_js = """<script>
(function(){
  function _patch(page_id, status, card_id) {
    fetch('/admin/api/notion/patch', {
      method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({page_id: page_id, status: status})
    }).then(function(r){
      if(r.ok){
        var card = document.getElementById(card_id);
        if(card){ card.style.transition='opacity 0.35s'; card.style.opacity='0'; setTimeout(function(){card.remove();}, 370); }
      }
    });
  }
  document.querySelectorAll('.btn-approve').forEach(function(btn){
    btn.addEventListener('click', function(){
      var id = this.dataset.id;
      btn.disabled = true;
      _patch(id, 'Approved', 'appr-pl-' + id);
    });
  });
  document.querySelectorAll('.btn-archive').forEach(function(btn){
    btn.addEventListener('click', function(){
      var id = this.dataset.id;
      btn.disabled = true;
      _patch(id, 'Archived', 'appr-pl-' + id);
    });
  });
})();
</script>"""

    return f"""{topbar}
<div class="page">
  {body_html}
  <div class="footer">MzansiEdge Approvals &middot; Notion-powered</div>
</div>
{approvals_js}"""


# -- Task Hub helpers ---------------------------------------------------------

def _fetch_task_hub_blocks() -> list[dict]:
    """Fetch all blocks from Task Hub Notion page with pagination."""
    cache_key = "task_hub_blocks"
    now = time.monotonic()
    with _notion_cache_lock:
        cached = _notion_cache.get(cache_key)
        if cached and (now - cached[1]) < _NOTION_CACHE_TTL:
            return cached[0]

    all_blocks: list[dict] = []
    start_cursor: str | None = None
    for _ in range(20):
        params = "?page_size=100"
        if start_cursor:
            params += f"&start_cursor={start_cursor}"
        result = _notion_request(f"blocks/{NOTION_TASK_HUB_PAGE}/children{params}")
        if not result or "results" not in result:
            break
        all_blocks.extend(result["results"])
        if result.get("has_more") and result.get("next_cursor"):
            start_cursor = result["next_cursor"]
        else:
            break

    with _notion_cache_lock:
        _notion_cache[cache_key] = (all_blocks, now)
    return all_blocks


def _block_plain_text(block: dict) -> str:
    """Extract plain text from a Notion block's rich_text array."""
    btype = block.get("type", "")
    type_data = block.get(btype, {})
    rich_text = type_data.get("rich_text", [])
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def render_rich_text_html(rich_text_array: list) -> str:
    """Render a Notion rich_text array to HTML, preserving links, bold, italic, code."""
    import html as _html_lib
    parts = []
    for span in rich_text_array:
        text = span.get("plain_text", "")
        if not text:
            continue
        href = span.get("href")
        if not href:
            link_obj = (span.get("text") or {}).get("link")
            if isinstance(link_obj, dict):
                href = link_obj.get("url")
        ann = span.get("annotations", {})
        esc = _html_lib.escape(text)
        if href:
            parts.append(f'<a href="{_html_lib.escape(href)}" target="_blank" class="task-link">{esc}</a>')
        elif ann.get("bold"):
            parts.append(f'<strong>{esc}</strong>')
        elif ann.get("italic"):
            parts.append(f'<em>{esc}</em>')
        elif ann.get("code"):
            parts.append(f'<code>{esc}</code>')
        else:
            parts.append(esc)
    return "".join(parts)


def _parse_card_zones(rich_text_array: list) -> tuple[str, str, str]:
    """Split a rich_text array into (title_html, desc_html, links_html) at ' — ' separator."""
    full_html = render_rich_text_html(rich_text_array)
    sep = " \u2014 "  # " — "
    html_parts = full_html.split(sep)
    if len(html_parts) >= 2:
        title_html = html_parts[0]
        desc_html = sep.join(html_parts[1:])
    else:
        title_html = full_html
        desc_html = ""
    links_html = "".join(re.findall(r'<a[^>]*class="task-link"[^>]*>.*?</a>', full_html, re.DOTALL))
    return title_html, desc_html, links_html


def _classify_task(text: str) -> str:
    """Classify a to_do block text into one of the 5 task section keys."""
    lower = text.lower()
    if "fb group" in lower:
        return "post_now"
    elif "linkedin" in lower or "li-" in lower:
        return "connect"
    elif "quora" in lower:
        return "answer"
    elif "reddit" in lower or "mybroadband" in lower:
        return "read_reply"
    else:
        return "reminders"


def render_task_hub_content() -> str:
    """Render the Task Hub inner content HTML."""
    now_utc = datetime.now(timezone.utc)
    now_sast = now_utc.astimezone(_SAST)
    updated = now_sast.strftime("%Y-%m-%d %H:%M:%S")

    _ACCENT: dict[str, str] = {
        "approve_posts": "#22c55e",
        "post_now":      "#E8571F",
        "connect":       "#3b82f6",
        "answer":        "#8b5cf6",
        "read_reply":    "#06b6d4",
        "reminders":     "#888888",
    }

    _SECTION_META = [
        ("approve_posts", "Approve Posts",   "📋"),
        ("post_now",      "Post Now",        "📢"),
        ("connect",       "Connect",         "🔗"),
        ("answer",        "Answer",          "✍️"),
        ("read_reply",    "Read &amp; Reply","💬"),
        ("reminders",     "Reminders",       "🔔"),
    ]

    # ── Approve Posts: awaiting approval from Marketing Ops Queue ──────────
    # I1+I3: Show ALL channels with review status — the Status field is the
    # source of truth for whether Paul needs to act, not the channel name.
    _fetch_error: str = ""
    try:
        mq_items, _ = _fetch_marketing_queue()
    except Exception as _mq_exc:
        mq_items = []
        _fetch_error = f"Failed to fetch Marketing Ops Queue: {_mq_exc}"
    approve_items = _get_awaiting_items(mq_items, include_overdue=False)

    # ── Task sections: scoped to # 📝 Manual Tasks heading ─────────────────
    sections: dict[str, list[dict]] = {
        "post_now": [], "connect": [], "answer": [], "read_reply": [], "reminders": [],
    }
    try:
        blocks = _fetch_task_hub_blocks()
        in_manual = False
        for block in blocks:
            btype = block.get("type", "")
            # Start scope at heading_1 containing "Manual Tasks"
            if not in_manual:
                if btype == "heading_1" and "Manual Tasks" in _block_plain_text(block):
                    in_manual = True
                continue
            # End scope at next divider or heading_1
            if btype in ("divider", "heading_1"):
                break
            if btype != "to_do":
                continue
            if block.get("to_do", {}).get("checked", False):
                continue
            rt_arr = block.get("to_do", {}).get("rich_text", [])
            plain = "".join(sp.get("plain_text", "") for sp in rt_arr).strip()
            if not plain:
                continue
            key = _classify_task(plain)
            sections[key].append({"block_id": block["id"], "rich_text": rt_arr, "plain": plain})
    except Exception as _blk_exc:
        if not _fetch_error:
            _fetch_error = f"Failed to fetch Task Hub blocks: {_blk_exc}"

    # ── Build section HTML ─────────────────────────────────────────────────
    def _channel_chip_th(ch_key: str) -> str:
        ch = _CHANNEL_MAP.get(ch_key)
        if not ch:
            return (f'<span class="ch-chip" style="background:rgba(107,114,128,0.15);'
                    f'color:var(--muted)">{ch_key or "?"}</span>')
        return (f'<span class="ch-chip" style="background:{ch["color"]}22;color:{ch["color"]};'
                f'border:1px solid {ch["color"]}33"><span class="ch-dot" style="background:{ch["color"]}"></span>'
                f'{ch["label"]}</span>')

    sections_html = ""

    for sec_key, sec_label, sec_emoji in _SECTION_META:
        accent = _ACCENT.get(sec_key, "#E8571F")

        if sec_key == "approve_posts":
            items_for_section = approve_items
            if not items_for_section:
                continue
            n = len(items_for_section)
            cards = ""
            for item in items_for_section:
                import html as _html_mod
                title = item.get("title") or ""
                ch_key = _normalise_channel_key(item.get("channel") or "")
                sched_str = _sast_hhmm(item.get("scheduled_time")) + " SAST" if item.get("scheduled_time") else "\u2014"
                asset_link = item.get("asset_link") or ""
                asset_html = (f'<a href="{asset_link}" target="_blank" rel="noopener" '
                              f'class="appr-asset-link">&#128444;&#65039; View asset</a>') if asset_link else ""
                page_id = item.get("id", "")
                notion_url = f"https://www.notion.so/{page_id.replace('-', '')}" if page_id else ""
                notion_html = (f'<a href="{notion_url}" target="_blank" rel="noopener" '
                               f'class="appr-notion-link">&#128279; Open in Notion</a>') if notion_url else ""
                # Copy preview — show the post content Paul needs to review
                raw_copy = item.get("copy") or ""
                # Convert <br> to newlines for display, escape HTML, then re-add line breaks
                copy_text = raw_copy.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
                copy_text = _html_mod.escape(copy_text).replace("\n", "<br>")
                copy_html = f'<div class="appr-copy">{copy_text}</div>' if copy_text else ""
                cards += f"""<div class="appr-card" id="th-appr-{page_id}">
  <div class="appr-title">{_html_mod.escape(title)}</div>
  <div class="appr-header">
    {_channel_chip_th(ch_key)}
    <span class="appr-meta">&#128337; {sched_str}</span>
    {asset_html}
    {notion_html}
  </div>
  {copy_html}
  <div class="appr-error" style="display:none;color:var(--red);font-size:11px;margin-top:8px"></div>
  <div class="appr-actions">
    <button class="btn-approve" data-id="{page_id}">Approve</button>
    <button class="btn-archive" data-id="{page_id}">Archive</button>
  </div>
</div>"""
            sections_html += f"""<div class="task-section" data-section="{sec_key}" id="th-sec-{sec_key}">
  <div class="section-header">
    <div class="section-left">
      <span class="section-icon">{sec_emoji}</span>
      <span class="section-title">{sec_label}</span>
      <span class="section-count">{n} pending</span>
    </div>
    <div class="section-progress">
      <span class="progress-text" data-done="0" data-total="{n}">0 / {n} done</span>
      <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
    </div>
  </div>
  <div class="task-cards-wrap">{cards}</div>
</div>"""
        else:
            task_list = sections.get(sec_key, [])
            if not task_list:
                continue
            n = len(task_list)
            cards = ""
            for task in task_list:
                bid = task["block_id"]
                rt_arr = task["rich_text"]
                plain = task["plain"]
                content_html = render_rich_text_html(rt_arr)
                safe_plain = plain.replace('"', "&quot;").replace("'", "&#39;")
                cards += f"""<div class="task-card" data-block-id="{bid}" style="border-left-color:{accent}">
  <div class="task-content">{content_html}</div>
  <div class="task-actions">
    <button class="btn-copy" data-text="{safe_plain}">Copy</button>
    <button class="btn-done" data-block-id="{bid}">Done &#10004;</button>
  </div>
</div>"""
            sections_html += f"""<div class="task-section" data-section="{sec_key}" id="th-sec-{sec_key}">
  <div class="section-header">
    <div class="section-left">
      <span class="section-icon">{sec_emoji}</span>
      <span class="section-title">{sec_label}</span>
      <span class="section-count">{n} pending</span>
    </div>
    <div class="section-progress">
      <span class="progress-text" data-done="0" data-total="{n}">0 / {n} done</span>
      <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
    </div>
  </div>
  <div class="task-cards-wrap">{cards}</div>
</div>"""

    # ── I5: Error banner (observable failures) ────────────────────────────
    error_banner = ""
    if _fetch_error:
        if _sentry:
            _sentry.capture_message(
                _fetch_error,
                level="error",
                fingerprint=["admin.task_hub.fetch_failed"],
            )
        error_banner = (
            '<div class="th-error-banner">'
            '<strong>&#9888; Data fetch error:</strong> '
            f'{_fetch_error}. Try refreshing or check Notion API credentials.'
            '</div>'
        )

    # ── I4: Graceful empty state with timestamp ────────────────────────────
    if not sections_html:
        page_body = f"""<div class="task-hub-done">
  <div class="task-hub-done-icon">&#9989;</div>
  <div class="task-hub-done-text">Task Hub clear.</div>
  <div class="task-hub-done-sub">Nothing needs your attention right now. Last checked {updated} SAST.</div>
</div>"""
    else:
        page_body = f'<div class="task-hub-content">{sections_html}</div>'

    task_hub_css = """<style>
.task-hub-content{}
.task-section{margin-bottom:28px;}
.section-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px;}
.section-left{display:flex;align-items:center;gap:8px;}
.section-icon{font-size:18px;line-height:1;}
.section-title{font-family:var(--font-d);font-size:15px;font-weight:700;color:var(--text);}
.section-count{font-family:var(--font-m);font-size:12px;color:var(--muted);background:rgba(107,114,128,.12);border-radius:12px;padding:2px 9px;}
.section-progress{display:flex;align-items:center;gap:8px;}
.progress-text{font-family:var(--font-m);font-size:12px;color:var(--muted);white-space:nowrap;}
.progress-bar{width:100px;height:4px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;}
.progress-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,#F8C830,#E8571F);transition:width 0.3s ease;}
.task-cards-wrap{}
.task-card{display:flex;gap:16px;justify-content:space-between;background:var(--surface-alt);border:1px solid var(--border);border-left:3px solid #E8571F;border-radius:8px;padding:16px 20px;margin-bottom:10px;transition:opacity 0.25s ease,transform 0.25s ease;}
.task-card.exiting{opacity:0;transform:translateX(40px);}
.task-content{flex:1;min-width:0;font-family:var(--font-m);font-size:13px;line-height:1.6;color:var(--text);word-break:break-word;}
.task-actions{display:flex;gap:8px;flex-shrink:0;align-items:flex-start;}
a.task-link{background:rgba(232,87,31,.12);color:#F8C830;border:1px solid rgba(248,200,48,.25);border-radius:5px;padding:4px 10px;font-size:12px;font-family:var(--font-m);text-decoration:none;display:inline-block;}
a.task-link:hover{background:rgba(232,87,31,.22);}
.btn-copy{background:rgba(107,114,128,.12);color:var(--muted);border:1px solid rgba(107,114,128,.2);border-radius:6px;padding:5px 14px;font-family:var(--font-d);font-weight:700;font-size:11px;cursor:pointer;transition:background 150ms,color 150ms;white-space:nowrap;}
.btn-copy:hover{background:rgba(107,114,128,.22);}
.btn-copy.copied{background:rgba(34,197,94,.12);color:var(--green);border-color:rgba(34,197,94,.3);}
.btn-done{background:rgba(34,197,94,.12);color:var(--green);border:1px solid rgba(34,197,94,.25);border-radius:6px;padding:5px 14px;font-family:var(--font-d);font-weight:700;font-size:11px;cursor:pointer;transition:background 150ms;white-space:nowrap;}
.btn-done:hover{background:rgba(34,197,94,.22);}
.btn-done:disabled{opacity:.5;cursor:not-allowed;}
.appr-card{background:var(--surface);border:1px solid var(--border);border-left:3px solid #22c55e;border-radius:8px;padding:18px;margin-bottom:14px;position:relative;}
.appr-title{font-family:var(--font-d);font-weight:700;font-size:14px;color:var(--text);margin-bottom:8px;}
.appr-header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;}
.appr-meta{font-family:var(--font-m);font-size:11px;color:var(--muted);}
.appr-asset-link,.appr-notion-link{font-family:var(--font-d);font-size:11px;font-weight:600;color:var(--gold);text-decoration:none;}
.appr-asset-link:hover,.appr-notion-link:hover{text-decoration:underline;}
.appr-notion-link{color:var(--muted);}
.appr-campaign{font-family:var(--font-d);font-size:11px;font-weight:600;color:var(--gold);background:rgba(248,200,48,.1);border-radius:4px;padding:2px 8px;}
.appr-copy{font-family:var(--font-m);font-size:13px;line-height:1.6;color:var(--text);white-space:pre-wrap;word-break:break-word;}
.appr-actions{display:flex;gap:10px;margin-top:14px;}
.btn-approve{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3);border-radius:6px;padding:7px 20px;font-family:var(--font-d);font-weight:700;font-size:12px;cursor:pointer;transition:background 150ms;}
.btn-approve:hover{background:rgba(34,197,94,.25);}
.btn-archive{background:rgba(107,114,128,.1);color:var(--muted);border:1px solid rgba(107,114,128,.2);border-radius:6px;padding:7px 20px;font-family:var(--font-d);font-weight:700;font-size:12px;cursor:pointer;transition:background 150ms;}
.btn-archive:hover{background:rgba(107,114,128,.2);}
.btn-approve:disabled,.btn-archive:disabled{opacity:.5;cursor:not-allowed;}
.appr-error{display:none;color:var(--red);font-size:11px;margin-top:8px;}
.toast-success{position:absolute;top:12px;right:14px;background:var(--green);color:#000;border-radius:6px;padding:5px 12px;font-size:11px;font-weight:700;font-family:var(--font-d);}
.task-hub-done{text-align:center;padding:80px 40px;}
.task-hub-done-icon{font-size:48px;margin-bottom:16px;}
.task-hub-done-text{font-family:var(--font-d);font-size:22px;font-weight:700;color:var(--text);}
.task-hub-done-sub{font-family:var(--font-m);font-size:14px;color:var(--muted);margin-top:8px;}
.th-error-banner{background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);border-radius:8px;padding:14px 18px;margin-bottom:20px;font-family:var(--font-m);font-size:13px;color:#ef4444;line-height:1.5;}
.th-refresh-footer{display:flex;align-items:center;justify-content:space-between;padding:14px 0;margin-top:20px;border-top:1px solid var(--border);}
.th-refresh-ts{font-family:var(--font-m);font-size:12px;color:var(--muted);}
.btn-refresh{background:rgba(248,200,48,.12);color:var(--gold);border:1px solid rgba(248,200,48,.25);border-radius:6px;padding:6px 16px;font-family:var(--font-d);font-weight:700;font-size:11px;cursor:pointer;transition:background 150ms;}
.btn-refresh:hover{background:rgba(248,200,48,.22);}
</style>"""

    task_hub_js = """<script>
(function(){
  // Live badge update — keeps sidebar badge in sync after approve/archive/done
  function _updateBadge(delta) {
    var badge = document.getElementById('th-badge');
    if (!badge) return;
    var cur = parseInt(badge.textContent, 10) || 0;
    var nv = Math.max(0, cur + delta);
    if (nv > 0) {
      badge.textContent = nv;
    } else {
      badge.remove();
    }
  }

  function updateSectionProgress(sectionEl) {
    var pt = sectionEl.querySelector('.progress-text');
    var pf = sectionEl.querySelector('.progress-fill');
    if (!pt || !pf) return;
    var total = parseInt(pt.dataset.total, 10);
    var done = parseInt(pt.dataset.done, 10) + 1;
    pt.dataset.done = done;
    pt.textContent = done + ' / ' + total + ' done';
    var pct = total > 0 ? Math.round(done * 100 / total) : 0;
    pf.style.width = pct + '%';
    if (done >= total) {
      setTimeout(function() {
        sectionEl.style.transition = 'opacity 0.3s';
        sectionEl.style.opacity = '0';
        setTimeout(function() {
          sectionEl.remove();
          checkAllComplete();
        }, 300);
      }, 500);
    }
  }

  function checkAllComplete() {
    var sections = document.querySelectorAll('.task-section');
    var apprCards = document.querySelectorAll('.appr-card');
    if (sections.length === 0 && apprCards.length === 0) {
      var content = document.querySelector('.task-hub-content');
      if (content) {
        var now = new Date();
        var ts = now.toLocaleString('en-ZA', {timeZone:'Africa/Johannesburg', hour12:false});
        content.innerHTML = '<div class="task-hub-done"><div class="task-hub-done-icon">&#9989;</div>'
          + '<div class="task-hub-done-text">Task Hub clear.</div>'
          + '<div class="task-hub-done-sub">Nothing needs your attention right now. Last checked ' + ts + ' SAST.</div></div>';
      }
    }
  }

  // Done buttons (task cards)
  document.querySelectorAll('.btn-done').forEach(function(btn){
    btn.addEventListener('click', function(){
      var blockId = this.dataset.blockId;
      var card = this.closest('.task-card');
      var sectionEl = card ? card.closest('.task-section') : null;
      btn.disabled = true;
      fetch('/admin/api/done-block', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({block_id: blockId})
      }).then(function(r){
        if (r.ok) {
          _updateBadge(-1);
          card.classList.add('exiting');
          setTimeout(function(){
            card.remove();
            if (sectionEl) updateSectionProgress(sectionEl);
          }, 260);
        } else { btn.disabled = false; }
      }).catch(function(){ btn.disabled = false; });
    });
  });

  // Copy buttons
  document.querySelectorAll('.btn-copy').forEach(function(btn){
    btn.addEventListener('click', function(){
      var text = this.dataset.text;
      var self = this;
      navigator.clipboard.writeText(text).then(function(){
        self.textContent = 'Copied \u2714';
        self.classList.add('copied');
        setTimeout(function(){
          self.textContent = 'Copy';
          self.classList.remove('copied');
        }, 1500);
      }).catch(function(){});
    });
  });

  // Approve / Archive (Approve Posts section)
  document.querySelectorAll('.btn-approve,.btn-archive').forEach(function(btn){
    btn.addEventListener('click', function(){
      var id = this.dataset.id;
      var isApprove = this.classList.contains('btn-approve');
      var newStatus = isApprove ? 'Approved' : 'Archived';
      var card = document.getElementById('th-appr-' + id);
      var errEl = card.querySelector('.appr-error');
      var allBtns = card.querySelectorAll('.btn-approve,.btn-archive');
      allBtns.forEach(function(b){ b.disabled = true; });
      fetch('/admin/api/notion/patch', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({page_id: id, status: newStatus})
      }).then(function(r){
        if (r.ok) {
          _updateBadge(-1);
          card.style.transition = 'opacity 0.4s';
          card.style.opacity = '0.4';
          var toast = document.createElement('div');
          toast.className = 'toast-success';
          toast.textContent = newStatus + ' \u2714';
          card.appendChild(toast);
          setTimeout(function(){
            card.remove();
            checkAllComplete();
          }, 700);
        } else {
          errEl.textContent = 'Error updating Notion \u2014 try again';
          errEl.style.display = 'block';
          allBtns.forEach(function(b){ b.disabled = false; });
        }
      }).catch(function(){
        errEl.textContent = 'Network error \u2014 try again';
        errEl.style.display = 'block';
        allBtns.forEach(function(b){ b.disabled = false; });
      });
    });
  });

  // Refresh Now button — bypasses cache by hitting API endpoint with bust param
  var refreshBtn = document.getElementById('th-refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', function(){
      refreshBtn.disabled = true;
      refreshBtn.textContent = 'Refreshing...';
      fetch('/admin/api/task_hub_refresh', {method:'POST', credentials:'same-origin'})
        .then(function(){ window.location.reload(); })
        .catch(function(){ window.location.reload(); });
    });
  }
})();
</script>"""

    topbar = f"""<nav class="topbar">
  <div class="topbar-left"><div class="topbar-pill">Task Hub</div></div>
  <div class="topbar-right"><div class="topbar-meta">Updated <em>{updated} SAST</em></div></div>
</nav>"""

    # I7: Last-refreshed footer with Refresh Now button
    refresh_footer = f"""<div class="th-refresh-footer">
  <span class="th-refresh-ts">Last refreshed: {updated} SAST</span>
  <button class="btn-refresh" id="th-refresh-btn">Refresh now</button>
</div>"""

    return f"""{task_hub_css}
{topbar}
<div class="page">
  {error_banner}
  {page_body}
  {refresh_footer}
</div>
{task_hub_js}"""


# -- System Health data builders ----------------------------------------------

def _check_billing_alerts() -> list:
    """Scan Sentry issues for billing/payment failures. Cached 60s. (AC-15)"""
    cache_key = "billing_alerts"
    now = time.monotonic()
    with _system_health_cache_lock:
        cached = _system_health_cache.get(cache_key)
        if cached and (now - cached[1]) < _SYSTEM_HEALTH_TTL:
            return cached[0]
    alerts: list = []
    try:
        sentry = _fetch_sentry_data()
        if sentry.get("available"):
            all_issues_url = (
                f"{_SENTRY_API}/projects/{SENTRY_ORG}/{SENTRY_PROJECT}/issues/"
                f"?query=is%3Aunresolved&sort=freq&limit=50"
            )
            req = urllib.request.Request(
                all_issues_url, headers={"Authorization": f"Bearer {SENTRY_AUTH_TOKEN}"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                all_issues = json.loads(resp.read().decode("utf-8"))
            for issue in all_issues:
                title_lower = (issue.get("title") or "").lower()
                if any(p in title_lower for p in _BILLING_PATTERNS):
                    svc = "Unknown Service"
                    burl = "#"
                    for svc_key, url in _BILLING_URLS.items():
                        if svc_key.lower() in title_lower:
                            svc = svc_key.replace("-", " ").title()
                            burl = url
                            break
                    alerts.append({
                        "service": svc,
                        "title": (issue.get("title") or "")[:120],
                        "count": issue.get("count", "?"),
                        "billing_url": burl,
                        "short_id": issue.get("shortId", ""),
                    })
    except Exception:
        pass
    with _system_health_cache_lock:
        _system_health_cache[cache_key] = (alerts, now)
    return alerts


def _fetch_sentry_data() -> dict:
    """Fetch Sentry issues. Cached 60s."""
    cache_key = "sentry"
    now = time.monotonic()
    with _system_health_cache_lock:
        cached = _system_health_cache.get(cache_key)
        if cached and (now - cached[1]) < _SYSTEM_HEALTH_TTL:
            return cached[0]

    result: dict = {
        "available": False, "error": None,
        "total_issues": 0, "by_level": {},
        "top_issues": [],
    }

    if not SENTRY_AUTH_TOKEN:
        result["error"] = "SENTRY_AUTH_TOKEN not configured — set in .env to enable"
        with _system_health_cache_lock:
            _system_health_cache[cache_key] = (result, now)
        return result

    try:
        url = (
            f"{_SENTRY_API}/projects/{SENTRY_ORG}/{SENTRY_PROJECT}/issues/"
            f"?query=is%3Aunresolved&sort=freq&limit=25"
        )
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {SENTRY_AUTH_TOKEN}"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            issues = json.loads(resp.read().decode("utf-8"))
        result["available"] = True
        # AC-8: Use len(issues) — not X-Hits. X-Hits can reflect total project count
        # regardless of the is:unresolved filter, showing stale/resolved issues as open.
        result["total_issues"] = len(issues)
        by_level: dict = {}
        for issue in issues:
            lvl = issue.get("level", "error")
            by_level[lvl] = by_level.get(lvl, 0) + 1
        result["by_level"] = by_level
        result["top_issues"] = [
            {
                "short_id": i.get("shortId", ""),
                "title": (i.get("title") or "")[:80],
                "level": i.get("level", "error"),
                "count": i.get("count", "0"),
                "last_seen": i.get("lastSeen", ""),
            }
            for i in issues[:5]
        ]
    except Exception as exc:
        result["error"] = str(exc)[:120]

    with _system_health_cache_lock:
        _system_health_cache[cache_key] = (result, now)
    return result


def _read_server_resources() -> dict:
    """Read CPU/RAM/disk from /proc. Cached 60s."""
    cache_key = "server_resources"
    now = time.monotonic()
    with _system_health_cache_lock:
        cached = _system_health_cache.get(cache_key)
        if cached and (now - cached[1]) < _SYSTEM_HEALTH_TTL:
            return cached[0]

    result: dict = {
        "cpu_1": None, "cpu_5": None, "cpu_15": None,
        "mem_total_mb": None, "mem_used_mb": None, "mem_avail_mb": None, "mem_pct": None,
        "swap_total_mb": None, "swap_used_mb": None, "swap_pct": None,
        "disk_total": None, "disk_used": None, "disk_pct": None,
    }

    # CPU load from /proc/loadavg
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        result["cpu_1"]  = float(parts[0])
        result["cpu_5"]  = float(parts[1])
        result["cpu_15"] = float(parts[2])
    except Exception:
        pass

    # Memory from /proc/meminfo
    try:
        mem: dict = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        used  = total - avail
        result["mem_total_mb"] = total // 1024
        result["mem_avail_mb"] = avail // 1024
        result["mem_used_mb"]  = used  // 1024
        result["mem_pct"]      = round(used / total * 100) if total > 0 else 0
        swap_t = mem.get("SwapTotal", 0)
        swap_f = mem.get("SwapFree", 0)
        swap_u = swap_t - swap_f
        result["swap_total_mb"] = swap_t // 1024
        result["swap_used_mb"]  = swap_u // 1024
        result["swap_pct"]      = round(swap_u / swap_t * 100) if swap_t > 0 else 0
    except Exception:
        pass

    # Disk from df
    try:
        out = subprocess.check_output(["df", "-B1", "/"], timeout=3).decode()
        lines = out.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            dt = int(parts[1]); du = int(parts[2])
            result["disk_total"] = f"{dt // (1024**3):.0f}G"
            result["disk_used"]  = f"{du // (1024**3):.1f}G"
            result["disk_pct"]   = round(du / dt * 100) if dt > 0 else 0
    except Exception:
        pass

    with _system_health_cache_lock:
        _system_health_cache[cache_key] = (result, now)
    return result


def _read_process_monitor() -> dict:
    """Read running process status and cron schedule. Cached 60s."""
    cache_key = "processes"
    now = time.monotonic()
    with _system_health_cache_lock:
        cached = _system_health_cache.get(cache_key)
        if cached and (now - cached[1]) < _SYSTEM_HEALTH_TTL:
            return cached[0]

    def _proc_info(pattern: str) -> dict:
        try:
            out = subprocess.check_output(
                ["pgrep", "-a", "-f", pattern], timeout=3
            ).decode().strip()
            if out:
                pid = out.split()[0]
                lstart = subprocess.check_output(
                    ["ps", "-p", pid, "-o", "lstart="], timeout=3
                ).decode().strip()
                return {"running": True, "pid": pid, "started": lstart}
        except Exception:
            pass
        return {"running": False, "pid": None, "started": ""}

    bot_info       = _proc_info(r"\.venv/bin/python bot\.py")
    dash_info      = _proc_info("health_dashboard.py")
    publisher_info = _proc_info("publisher/publisher.py")

    cron_jobs = []
    try:
        ctab = subprocess.check_output(["crontab", "-l"], timeout=3).decode()
        for line in ctab.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            cmd = parts[5]
            for kw in ["runner.py", "settlement", "glicko", "the_odds_api", "validate_odds"]:
                if kw in cmd:
                    cron_jobs.append({
                        "schedule": " ".join(parts[:5]),
                        "cmd": re.sub(r"\s+", " ", cmd)[:65],
                    })
                    break
        cron_jobs = cron_jobs[:8]
    except Exception:
        pass

    result = {
        "bot": bot_info, "dashboard": dash_info,
        "publisher": publisher_info,
        "cron_jobs": cron_jobs,
    }
    with _system_health_cache_lock:
        _system_health_cache[cache_key] = (result, now)
    return result


def _build_api_health(conn) -> list:
    """Read API health metrics from api_usage table in odds.db."""
    apis = [
        ("the_odds_api", "The Odds API",      "sharp_odds"),
        ("espn",         "ESPN",              None),
        ("api_football", "API-Football",      None),
        ("api_sports_mma",   "API-Sports MMA",   None),
        ("api_sports_rugby", "API-Sports Rugby", None),
        ("sportmonks_cricket", "Sportmonks Cricket", None),
    ]
    rows = []

    # The Odds API — infer from sharp_odds table
    if conn and table_exists(conn, "sharp_odds"):
        r = q_one(conn, "SELECT MAX(scraped_at) as last FROM sharp_odds WHERE scraped_at >= datetime('now','-24 hours')")
        last = r["last"] if r else None
        _, lbl = freshness(last) if last else ("s-grey", "No data (24h)")
        css = "s-green" if last else "s-grey"
        calls_row = q_one(conn, "SELECT COUNT(DISTINCT substr(scraped_at,1,16)) as calls FROM sharp_odds WHERE scraped_at >= datetime('now','-24 hours')")
        calls_24h = calls_row["calls"] if calls_row else 0
        rows.append({"api": "The Odds API", "last_call": lbl, "calls_24h": calls_24h, "errors_24h": 0, "css": css})
    else:
        rows.append({"api": "The Odds API", "last_call": "No data", "calls_24h": 0, "errors_24h": 0, "css": "s-grey"})

    if conn is None or not table_exists(conn, "api_usage"):
        for _, label, _ in apis[1:]:
            rows.append({"api": label, "last_call": "No data", "calls_24h": "—", "errors_24h": 0, "css": "s-grey"})
        return rows

    for api_key, label, _ in apis[1:]:
        r = q_one(conn,
            "SELECT MAX(called_at) as last, COUNT(*) as total, "
            "SUM(CASE WHEN status_code >= 400 OR status_code IS NULL THEN 1 ELSE 0 END) as errs "
            "FROM api_usage WHERE api_name=? AND called_at >= datetime('now','-24 hours')",
            (api_key,)
        )
        if r and r["last"]:
            errs = r["errs"] or 0
            total = r["total"] or 0
            css = "s-green" if errs == 0 else ("s-amber" if errs <= 3 else "s-red")
            _, lbl = freshness(r["last"])
            rows.append({"api": label, "last_call": lbl, "calls_24h": total, "errors_24h": errs, "css": css})
        else:
            # ESPN: fall back to match_results (where ESPN data actually lands via update_daily)
            if api_key == "espn" and table_exists(conn, "match_results"):
                ec = q_one(conn, "SELECT MAX(created_at) as last FROM match_results WHERE source='espn'")
                if ec and ec["last"]:
                    _, lbl = freshness(ec["last"])
                    rows.append({"api": label, "last_call": lbl, "calls_24h": "results", "errors_24h": 0, "css": "s-green"})
                else:
                    rows.append({"api": label, "last_call": "No data (24h)", "calls_24h": 0, "errors_24h": 0, "css": "s-grey"})
            else:
                rows.append({"api": label, "last_call": "No data (24h)", "calls_24h": 0, "errors_24h": 0, "css": "s-grey"})

    return rows


def _pbar(pct, label: str) -> str:
    """Render a compact progress bar."""
    pct = pct or 0
    if pct < 70:
        colour = "var(--green)"
    elif pct < 90:
        colour = "var(--amber)"
    else:
        colour = "var(--red)"
    return (
        f'<div style="display:flex;align-items:center;gap:10px">'
        f'<div style="flex:1;background:#1f1f1f;border-radius:4px;height:8px;overflow:hidden">'
        f'<div style="width:{min(pct,100)}%;height:100%;background:{colour};border-radius:4px"></div></div>'
        f'<span style="font-family:var(--font-m);font-size:12px;color:var(--text);min-width:60px">{label}</span>'
        f'</div>'
    )


# -- System Health renderer ---------------------------------------------------

def render_system_health_content(conn) -> str:
    """Render the System Health monitoring view."""
    sentry   = _fetch_sentry_data()
    res      = _read_server_resources()
    procs    = _read_process_monitor()
    api_rows = _build_api_health(conn)
    updated  = datetime.now(_SAST).strftime("%Y-%m-%d %H:%M:%S")

    topbar = f"""<nav class="topbar">
  <div class="topbar-left"><div class="topbar-pill">System Health</div></div>
  <div class="topbar-right">
    <div class="topbar-meta">Updated <em>{updated} SAST</em> &middot; refreshes in <em id="sh-countdown">1:00</em></div>
  </div>
</nav>"""

    # ── Panel 1: Sentry Issues ───────────────────────────────────────────────
    if not sentry["available"]:
        err_msg = sentry.get("error") or "Sentry unavailable"
        if "not configured" in err_msg:
            sentry_body = (
                f'<div style="padding:24px;font-family:var(--font-m);font-size:13px;color:var(--muted)">'
                f'<div style="color:var(--amber);font-weight:700;margin-bottom:10px">&#9888; Sentry not configured</div>'
                f'<div>Add <code style="background:#1f1f1f;padding:2px 6px;border-radius:4px">SENTRY_AUTH_TOKEN=&lt;token&gt;</code> to <code style="background:#1f1f1f;padding:2px 6px;border-radius:4px">~/bot/.env</code> and restart the dashboard.</div>'
                f'</div>'
            )
        else:
            sentry_body = f'<div style="padding:24px;font-family:var(--font-m);font-size:12px;color:var(--red)">Sentry unavailable: {err_msg}</div>'
    else:
        level_html = ""
        level_colours = {"error": "var(--red)", "warning": "var(--amber)", "info": "var(--green)", "fatal": "#ef4444"}
        for lvl, cnt in sorted(sentry["by_level"].items(), key=lambda x: -x[1]):
            col = level_colours.get(lvl, "var(--muted)")
            level_html += (
                f'<span style="background:{col}22;color:{col};border:1px solid {col}44;'
                f'border-radius:999px;padding:2px 10px;font-size:11px;font-weight:700;font-family:var(--font-d);margin-right:6px">'
                f'{lvl.upper()} {cnt}</span>'
            )

        issue_rows = ""
        for i in sentry["top_issues"]:
            last = _relative_time(i.get("last_seen"))
            lvl = i.get("level", "error")
            col = level_colours.get(lvl, "var(--muted)")
            dot_html = f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{col};margin-right:6px;flex-shrink:0"></span>'
            issue_rows += (
                f'<tr>'
                f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{i.get("short_id","")}</td>'
                f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;max-width:320px;overflow:hidden;text-overflow:ellipsis">'
                f'{dot_html}{i.get("title","")}</td>'
                f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;text-align:right">{i.get("count","—")}</td>'
                f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{last}</td>'
                f'</tr>'
            )

        sentry_body = (
            f'<div style="padding:12px 16px 8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
            f'<span style="font-family:var(--font-d);font-size:22px;font-weight:700;color:var(--text)">{sentry["total_issues"]}</span>'
            f'<span style="font-family:var(--font-m);font-size:12px;color:var(--muted)">open issues</span>'
            f'<span style="flex:1"></span>{level_html}</div>'
            f'<div class="tbl-wrap"><table class="tbl">'
            f'<thead><tr><th>ID</th><th>Error</th><th>Events</th><th>Last Seen</th></tr></thead>'
            f'<tbody>{issue_rows}</tbody></table></div>'
        )

    sentry_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Sentry Issues</span>'
        f'<span class="panel-sub">mzansi-edge project &middot; unresolved &middot; top 5 by frequency</span>'
        f'</div>{sentry_body}</div>'
    )

    # ── Panel 2: Server Resources ────────────────────────────────────────────
    def _na(v, fmt="{}", suffix=""):
        return "N/A" if v is None else (fmt.format(v) + suffix)

    cpu_1  = res["cpu_1"];  cpu_5 = res["cpu_5"];  cpu_15 = res["cpu_15"]
    mem_pct  = res["mem_pct"] or 0
    swap_pct = res["swap_pct"] or 0
    disk_pct = res["disk_pct"] or 0

    # CPU colour based on 1-min load (assuming ~2 cores on DO)
    cpu_pct_approx = round((cpu_1 or 0) / 2 * 100) if cpu_1 is not None else None
    cpu_bar = _pbar(cpu_pct_approx, _na(cpu_1, "{:.2f}")) if cpu_1 is not None else '<span style="color:var(--muted);font-size:12px">N/A</span>'
    mem_bar  = _pbar(mem_pct,  f'{res["mem_used_mb"] or 0:,} MB / {res["mem_total_mb"] or 0:,} MB ({mem_pct}%)')
    swap_bar = _pbar(swap_pct, f'{res["swap_used_mb"] or 0:,} MB ({swap_pct}%)')
    disk_bar = _pbar(disk_pct, f'{res["disk_used"] or "—"} / {res["disk_total"] or "—"} ({disk_pct}%)')

    res_rows = (
        f'<div style="padding:16px;display:grid;gap:14px">'
        f'<div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">CPU Load (1m / 5m / 15m)</div>'
        f'{cpu_bar}'
        f'<div style="font-family:var(--font-m);font-size:11px;color:var(--muted);margin-top:4px">'
        f'{_na(cpu_1,"{:.2f}")} / {_na(cpu_5,"{:.2f}")} / {_na(cpu_15,"{:.2f}")}</div></div>'
        f'<div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">RAM Usage</div>'
        f'{mem_bar}</div>'
        f'<div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Swap Usage</div>'
        f'{swap_bar}</div>'
        f'<div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Disk Usage (/)</div>'
        f'{disk_bar}</div>'
        f'</div>'
    )

    resources_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Server Resources</span>'
        f'<span class="panel-sub">/proc/loadavg &middot; /proc/meminfo &middot; df /</span>'
        f'</div>{res_rows}</div>'
    )

    # ── Panel 3: Process Monitor ─────────────────────────────────────────────
    def _proc_row(label: str, info: dict) -> str:
        if info["running"]:
            dot = f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 4px var(--green);margin-right:8px"></span>'
            status = f'{dot}<span style="color:var(--green);font-weight:700">Running</span>'
            detail = f'PID {info["pid"]} &middot; started {info["started"]}'
        else:
            dot = f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--red);margin-right:8px"></span>'
            status = f'{dot}<span style="color:var(--red);font-weight:700">Not running</span>'
            detail = "—"
        return (
            f'<tr>'
            f'<td style="padding:8px 12px;font-family:var(--font-d);font-size:12px;font-weight:600">{label}</td>'
            f'<td style="padding:8px 12px;font-family:var(--font-m);font-size:12px">{status}</td>'
            f'<td style="padding:8px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{detail}</td>'
            f'</tr>'
        )

    proc_rows = (
        _proc_row("bot.py", procs["bot"])
        + _proc_row("health_dashboard.py", procs["dashboard"])
        + _proc_row("publisher.py (cron)", procs.get("publisher", {"running": False, "pid": None, "started": ""}))
    )

    cron_html = ""
    if procs["cron_jobs"]:
        cron_rows = ""
        for job in procs["cron_jobs"]:
            cron_rows += (
                f'<tr>'
                f'<td style="padding:5px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{job["schedule"]}</td>'
                f'<td style="padding:5px 12px;font-family:var(--font-m);font-size:11px">{job["cmd"]}</td>'
                f'</tr>'
            )
        cron_html = (
            f'<div style="padding:0 12px 4px;font-family:var(--font-d);font-size:10px;font-weight:700;'
            f'letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-top:12px">Cron Jobs</div>'
            f'<div class="tbl-wrap"><table class="tbl">'
            f'<thead><tr><th>Schedule</th><th>Command</th></tr></thead>'
            f'<tbody>{cron_rows}</tbody></table></div>'
        )

    processes_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Process Monitor</span>'
        f'<span class="panel-sub">pgrep &middot; crontab -l</span>'
        f'</div>'
        f'<div class="tbl-wrap"><table class="tbl">'
        f'<thead><tr><th>Process</th><th>Status</th><th>Detail</th></tr></thead>'
        f'<tbody>{proc_rows}</tbody></table></div>'
        f'{cron_html}</div>'
    )

    # ── Panel 4: API Health ───────────────────────────────────────────────────
    api_table_rows = ""
    for row in api_rows:
        errs = row["errors_24h"]
        err_css = "s-red" if errs > 3 else ("s-amber" if errs > 0 else "s-grey")
        status_dot = dot(row["css"])
        api_table_rows += (
            f'<tr>'
            f'<td style="padding:6px 12px;font-family:var(--font-d);font-size:12px;font-weight:600">{row["api"]}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px">{status_dot}{row["last_call"]}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px">{row["calls_24h"]}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px" class="{err_css if errs else ""}">{errs if errs else "—"}</td>'
            f'</tr>'
        )

    api_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">API Health</span>'
        f'<span class="panel-sub">api_usage table &middot; last 24h</span>'
        f'</div>'
        f'<div class="tbl-wrap"><table class="tbl">'
        f'<thead><tr><th>API</th><th>Last Call</th><th>Calls (24h)</th><th>Errors (24h)</th></tr></thead>'
        f'<tbody>{api_table_rows}</tbody></table></div></div>'
    )

    return f"""{topbar}
<div class="page">
  <div class="grid-2">
    {sentry_panel}
    {resources_panel}
    {processes_panel}
    {api_panel}
  </div>
  <div class="footer">Auto-refreshes in <span id="sh-countdown2">1:00</span> &middot; MzansiEdge Ops &middot; Read-only</div>
</div>
<script>
(function(){{
  var secs = 60;
  function tick() {{
    secs--;
    if (secs <= 0) {{ location.reload(); return; }}
    var txt = secs + 's';
    var el1 = document.getElementById('sh-countdown');
    var el2 = document.getElementById('sh-countdown2');
    if (el1) el1.textContent = txt;
    if (el2) el2.textContent = txt;
  }}
  setInterval(tick, 1000);
}})();
</script>"""


# -- Edge Performance content renderer ----------------------------------------

_TIER_CONFIG = {
    "diamond": {"label": "💎 Diamond", "cls": "tier-diamond"},
    "gold":    {"label": "🥇 Gold",    "cls": "tier-gold"},
    "silver":  {"label": "🥈 Silver",  "cls": "tier-silver"},
    "bronze":  {"label": "🥉 Bronze",  "cls": "tier-bronze"},
}
_SPORT_EMOJI = {
    "soccer": "⚽", "rugby": "🏉", "cricket": "🏏",
    "mma": "🥊", "boxing": "🥊", "combat": "🥊",
}
_TIER_ORDER = ["diamond", "gold", "silver", "bronze"]


def _fmt_match(match_key: str) -> str:
    key = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_key)
    key = key.replace("_vs_", " vs ")
    return key.replace("_", " ").title()


def _perf_css() -> str:
    return """
  /* Tier badges */
  .tier-badge { display:inline-flex; align-items:center; padding:3px 9px; border-radius:999px;
    font-size:10px; font-weight:700; font-family:var(--font-d); letter-spacing:.04em; white-space:nowrap; }
  .tier-diamond { background: rgba(248,200,48,.15); color:#F8C830;
    border:1px solid rgba(248,200,48,.35); }
  .tier-gold    { background: rgba(240,160,32,.12); color:#F0A020;
    border:1px solid rgba(240,160,32,.3); }
  .tier-silver  { background: rgba(156,163,175,.12); color:#9CA3AF;
    border:1px solid rgba(156,163,175,.25); }
  .tier-bronze  { background: rgba(180,120,60,.12); color:#B47840;
    border:1px solid rgba(180,120,60,.25); }
  /* Win/loss chips in recent table */
  .outcome-win  { color:var(--green); font-weight:700; }
  .outcome-loss { color:var(--red);   font-weight:700; }
  /* Chart window tabs */
  .chart-tabs { display:flex; gap:4px; }
  .chart-tab  { background:var(--surface-alt); border:1px solid var(--border); border-radius:6px;
    padding:4px 12px; font-size:10px; font-family:var(--font-d); font-weight:700;
    letter-spacing:.05em; color:var(--muted); cursor:pointer; }
  .chart-tab.active { background:rgba(248,200,48,.12); border-color:rgba(248,200,48,.35);
    color:var(--gold); }
  /* Empty state */
  .perf-empty { padding:48px 24px; text-align:center; color:var(--muted);
    font-family:var(--font-m); font-size:13px; }
"""


def render_performance_content(conn) -> str:
    """Render the Edge Performance inner content HTML (no shell)."""
    now_sast = datetime.now(_SAST)
    updated = now_sast.strftime("%Y-%m-%d %H:%M SAST")

    # ---- Query summary ----
    summary = q_one(conn, """
        SELECT COUNT(*) as total,
               SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
               ROUND(AVG(predicted_ev), 2) as avg_edge,
               SUM(CASE WHEN result='hit' THEN actual_return - 100.0 ELSE -100.0 END) as net_pl
        FROM edge_results WHERE result IN ('hit','miss')
    """)
    total   = int(summary["total"])   if summary else 0
    hits    = int(summary["hits"])    if summary else 0
    misses  = total - hits
    hit_rate = round(hits * 100.0 / total, 1) if total > 0 else 0.0
    avg_edge = round(float(summary["avg_edge"] or 0), 1) if summary else 0.0
    net_pl   = round(float(summary["net_pl"]   or 0), 0) if summary else 0.0

    # ---- CLV summary ----
    clv_summary = q_one(conn, """
        SELECT ROUND(AVG(clv), 3) as mean_clv,
               ROUND(AVG(CASE WHEN clv > 0 THEN 1.0 ELSE 0 END) * 100, 1) as pct_positive,
               COUNT(*) as n_clv
        FROM clv_tracking
    """)
    clv_val = float(clv_summary['mean_clv'] or 0) if clv_summary else 0
    clv_pct_positive = float(clv_summary['pct_positive'] or 0) if clv_summary else 0
    clv_n = int(clv_summary['n_clv'] or 0) if clv_summary else 0
    clv_cls = 'c-green' if clv_val > 0 else ('c-red' if clv_val < 0 else 'c-text')
    clv_sign = '+' if clv_val > 0 else ''

    # ---- Current streak ----
    recent_rows = q_all(conn, """
        SELECT result FROM edge_results
        WHERE result IN ('hit','miss')
        ORDER BY settled_at DESC LIMIT 30
    """)
    streak, streak_type = 0, None
    for row in recent_rows:
        r = row["result"]
        if streak_type is None:
            streak_type, streak = r, 1
        elif r == streak_type:
            streak += 1
        else:
            break

    # ---- By Tier ----
    tier_rows = q_all(conn, """
        SELECT edge_tier,
               COUNT(*) as cnt,
               SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result='miss' THEN 1 ELSE 0 END) as losses,
               ROUND(SUM(CASE WHEN result='hit' THEN 1.0 ELSE 0 END)*100.0/COUNT(*),1) as hit_rate,
               ROUND(AVG(predicted_ev),1) as avg_edge,
               ROUND(AVG(CASE WHEN result='hit' THEN recommended_odds END),2) as win_odds,
               ROUND(AVG(CASE WHEN result='miss' THEN recommended_odds END),2) as loss_odds,
               ROUND(SUM(CASE WHEN result='hit' THEN actual_return - 100.0 ELSE -100.0 END),0) as net_pl,
               ROUND(SUM(CASE WHEN result='hit' THEN actual_return - 100.0 ELSE -100.0 END)
                     / (COUNT(*) * 100.0) * 100, 1) as roi_pct
        FROM edge_results WHERE result IN ('hit','miss')
        GROUP BY edge_tier
    """)
    tier_map = {row["edge_tier"]: row for row in tier_rows}

    # ---- By Sport ----
    sport_rows = q_all(conn, """
        SELECT sport,
               COUNT(*) as cnt,
               SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result='miss' THEN 1 ELSE 0 END) as losses,
               ROUND(SUM(CASE WHEN result='hit' THEN 1.0 ELSE 0 END)*100.0/COUNT(*),1) as hit_rate,
               ROUND(AVG(predicted_ev),1) as avg_edge
        FROM edge_results WHERE result IN ('hit','miss')
        GROUP BY sport ORDER BY cnt DESC
    """)

    # ---- Recent 20 settlements ----
    recent_settled = q_all(conn, """
        SELECT match_date, match_key, sport, edge_tier, result,
               ROUND(predicted_ev,1) as ev,
               ROUND(recommended_odds,2) as odds, bookmaker
        FROM edge_results WHERE result IN ('hit','miss')
        ORDER BY settled_at DESC LIMIT 20
    """)

    # ---- Chart data: daily stats ----
    daily_raw = q_all(conn, """
        SELECT match_date,
               SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as dh,
               COUNT(*) as dt
        FROM edge_results WHERE result IN ('hit','miss')
        GROUP BY match_date ORDER BY match_date ASC
    """)
    daily = {row["match_date"]: (int(row["dh"]), int(row["dt"])) for row in daily_raw}
    all_dates = sorted(daily.keys())

    def build_window(days: int) -> dict:
        from datetime import date as _dt_date, timedelta as _dt_td
        cutoff = str(now_sast.date() - _dt_td(days=days - 1))
        dates = [d for d in all_dates if d >= cutoff]
        if not dates:
            dates = all_dates
        labels, wins_d, losses_d, rolling_7 = [], [], [], []
        for d in dates:
            labels.append(d[5:])
            dh, dt = daily[d]
            wins_d.append(dh)
            losses_d.append(dt - dh)
            d_date = _dt_date.fromisoformat(d)
            s7 = str(d_date - _dt_td(days=6))
            r7h = sum(v[0] for k, v in daily.items() if s7 <= k <= d)
            r7t = sum(v[1] for k, v in daily.items() if s7 <= k <= d)
            rolling_7.append(round(r7h * 100.0 / r7t, 1) if r7t > 0 else None)
        return {"labels": labels, "wins": wins_d, "losses": losses_d, "rolling": rolling_7}

    import json as _json
    chart_30  = _json.dumps(build_window(30))
    chart_60  = _json.dumps(build_window(60))
    chart_90  = _json.dumps(build_window(90))

    # ---- KPI HTML ----
    pl_cls = "c-green" if net_pl >= 0 else "c-red"
    pl_sign = "+" if net_pl >= 0 else ""
    hr_cls = "c-green" if hit_rate >= 50 else ("c-amber" if hit_rate >= 35 else "c-red")
    streak_label = (f"+{streak} ✅" if streak_type == "hit" else f"-{streak} ❌") if streak > 0 else "—"
    streak_cls = "c-green" if streak_type == "hit" else ("c-red" if streak_type == "miss" else "c-text")

    kpi_html = f"""
<div class="kpi-strip">
  <div class="kpi">
    <div class="kpi-lbl">Total Settled</div>
    <div class="kpi-val c-text">{total}</div>
    <div class="kpi-sub">{hits}W / {misses}L</div>
  </div>
  <div class="kpi">
    <div class="kpi-lbl">Hit Rate</div>
    <div class="kpi-val {hr_cls}">{hit_rate}%</div>
    <div class="kpi-sub">from {total} edges</div>
  </div>
  <div class="kpi">
    <div class="kpi-lbl">Net P/L (R100 stake)</div>
    <div class="kpi-val {pl_cls}">{pl_sign}R{int(net_pl):,}</div>
    <div class="kpi-sub">total return</div>
  </div>
  <div class="kpi">
    <div class="kpi-lbl">Avg Edge %</div>
    <div class="kpi-val c-gold">{avg_edge}%</div>
    <div class="kpi-sub">predicted EV</div>
  </div>
  <div class="kpi">
    <div class="kpi-lbl">Current Streak</div>
    <div class="kpi-val {streak_cls}">{streak_label}</div>
    <div class="kpi-sub">consecutive</div>
  </div>
  <div class="kpi">
    <div class="kpi-lbl">Mean CLV</div>
    <div class="kpi-val {clv_cls}">{clv_sign}{clv_val:.3f}</div>
    <div class="kpi-sub">{clv_pct_positive}% positive ({clv_n} samples)</div>
  </div>
</div>"""

    # ---- By Tier table ----
    if tier_map:
        tier_rows_html = ""
        for t in _TIER_ORDER:
            row = tier_map.get(t)
            if not row:
                continue
            cfg = _TIER_CONFIG.get(t, {"label": t.title(), "cls": "tier-bronze"})
            hr_c = "s-green" if row["hit_rate"] >= 50 else ("s-amber" if row["hit_rate"] >= 35 else "s-red")
            _net_pl = float(row["net_pl"] or 0)
            _roi_pct = float(row["roi_pct"] or 0)
            _pl_sign = "+" if _net_pl >= 0 else ""
            _roi_cls = "s-green" if _roi_pct >= 0 else "s-red"
            _pl_cls = "s-green" if _net_pl >= 0 else "s-red"
            tier_rows_html += f"""
      <tr>
        <td><span class="tier-badge {cfg['cls']}">{cfg['label']}</span></td>
        <td>{int(row['cnt'])}</td>
        <td>{int(row['wins'])}/{int(row['losses'])}</td>
        <td class="{hr_c}">{row['hit_rate']}%</td>
        <td class="{_roi_cls}">{_pl_sign}{_roi_pct}%</td>
        <td class="{_pl_cls}">{_pl_sign}R{int(_net_pl):,}</td>
        <td>{row['win_odds']}</td>
        <td>{row['loss_odds']}</td>
      </tr>"""
        tier_table = f"""
<div class="tbl-wrap">
  <table class="tbl">
    <thead><tr>
      <th>Tier</th><th>Total</th><th>W/L</th>
      <th>Hit Rate</th><th>ROI%</th><th>Net P/L</th>
      <th>Win Odds</th><th>Loss Odds</th>
    </tr></thead>
    <tbody>{tier_rows_html}</tbody>
  </table>
</div>"""
    else:
        tier_table = '<div class="perf-empty">No tier data yet.</div>'

    # ---- CLV by Tier table ----
    clv_rows = q_all(conn, """
        SELECT er.edge_tier,
               COUNT(ct.clv) as n_clv,
               ROUND(AVG(ct.clv), 3) as mean_clv,
               ROUND(AVG(CASE WHEN ct.clv > 0 THEN 1.0 ELSE 0 END) * 100, 1) as pct_positive
        FROM clv_tracking ct
        JOIN edge_results er ON er.match_key = ct.match_key
        WHERE er.result IN ('hit','miss')
        GROUP BY er.edge_tier
    """)
    if clv_rows:
        clv_rows_html = ""
        clv_tier_map = {row["edge_tier"]: row for row in clv_rows}
        for t in _TIER_ORDER:
            row = clv_tier_map.get(t)
            if not row:
                continue
            cfg = _TIER_CONFIG.get(t, {"label": t.title(), "cls": "tier-bronze"})
            _mc = float(row["mean_clv"] or 0)
            _mc_cls = "s-green" if _mc > 0 else ("s-red" if _mc < 0 else "")
            _mc_sign = "+" if _mc > 0 else ""
            clv_rows_html += f"""
      <tr>
        <td><span class="tier-badge {cfg['cls']}">{cfg['label']}</span></td>
        <td>{int(row['n_clv'])}</td>
        <td class="{_mc_cls}">{_mc_sign}{_mc:.3f}</td>
        <td>{row['pct_positive']}%</td>
      </tr>"""
        clv_table = f"""
<div class="tbl-wrap">
  <table class="tbl">
    <thead><tr>
      <th>Tier</th><th>Sample</th><th>Mean CLV</th><th>% Positive</th>
    </tr></thead>
    <tbody>{clv_rows_html}</tbody>
  </table>
</div>"""
    else:
        clv_table = '<div class="perf-empty">No CLV data yet.</div>'

    # ---- By Sport table ----
    if sport_rows:
        sport_rows_html = ""
        for row in sport_rows:
            sp = row["sport"] or "unknown"
            emoji = _SPORT_EMOJI.get(sp, "🏅")
            hr_c = "s-green" if row["hit_rate"] >= 50 else ("s-amber" if row["hit_rate"] >= 35 else "s-red")
            sport_rows_html += f"""
      <tr>
        <td>{emoji} {sp.title()}</td>
        <td>{int(row['cnt'])}</td>
        <td class="s-green">{int(row['wins'])}</td>
        <td class="s-red">{int(row['losses'])}</td>
        <td class="{hr_c}">{row['hit_rate']}%</td>
        <td>{row['avg_edge']}%</td>
      </tr>"""
        sport_table = f"""
<div class="tbl-wrap">
  <table class="tbl">
    <thead><tr>
      <th>Sport</th><th>Total</th><th>Wins</th><th>Losses</th>
      <th>Hit Rate</th><th>Avg Edge</th>
    </tr></thead>
    <tbody>{sport_rows_html}</tbody>
  </table>
</div>"""
    else:
        sport_table = '<div class="perf-empty">No sport data yet.</div>'

    # ---- Chart HTML ----
    if daily:
        chart_html = f"""
<div class="panel" style="margin-bottom:16px;">
  <div class="panel-head">
    <span class="panel-title">Rolling Hit Rate</span>
    <div class="chart-tabs">
      <button class="chart-tab active" data-window="30">30D</button>
      <button class="chart-tab" data-window="60">60D</button>
      <button class="chart-tab" data-window="90">90D</button>
    </div>
  </div>
  <div class="chart-wrap" style="height:220px; padding:16px 16px 8px;">
    <canvas id="perfHRChart"></canvas>
  </div>
</div>
<script>
(function() {{
  var datasets = {{
    30: {chart_30},
    60: {chart_60},
    90: {chart_90}
  }};
  var chartInst = null;
  function renderChart(days) {{
    var ctx = document.getElementById('perfHRChart');
    if (!ctx || typeof Chart === 'undefined') return;
    if (chartInst) {{ chartInst.destroy(); chartInst = null; }}
    var d = datasets[days];
    chartInst = new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: d.labels,
        datasets: [
          {{ label: 'Wins', data: d.wins,
             backgroundColor: 'rgba(34,197,94,0.45)', borderColor: 'rgba(34,197,94,0.7)',
             borderWidth: 1, order: 2 }},
          {{ label: 'Losses', data: d.losses,
             backgroundColor: 'rgba(239,68,68,0.45)', borderColor: 'rgba(239,68,68,0.7)',
             borderWidth: 1, order: 2 }},
          {{ label: '7-Day Hit Rate %', data: d.rolling, type: 'line',
             borderColor: '#F8C830', backgroundColor: 'transparent', borderWidth: 2,
             pointRadius: 3, pointBackgroundColor: '#F8C830',
             yAxisID: 'y2', order: 1, spanGaps: true }}
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        scales: {{
          x: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }},
               ticks: {{ color: '#6b7280', font: {{ size: 10 }} }} }},
          y: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }},
               ticks: {{ color: '#6b7280', font: {{ size: 10 }} }},
               title: {{ display: true, text: 'Results', color: '#6b7280', font: {{ size: 10 }} }} }},
          y2: {{ position: 'right', min: 0, max: 100, grid: {{ display: false }},
                ticks: {{ color: '#F8C830', font: {{ size: 10 }},
                          callback: function(v) {{ return v + '%'; }} }},
                title: {{ display: true, text: 'Hit Rate', color: '#F8C830', font: {{ size: 10 }} }} }}
        }},
        plugins: {{
          legend: {{ labels: {{ color: '#F5F5F5', font: {{ size: 11 }}, boxWidth: 12 }} }},
          tooltip: {{ backgroundColor: 'rgba(17,17,17,0.95)', titleColor: '#F5F5F5',
                     bodyColor: '#9ca3af', borderColor: '#1f1f1f', borderWidth: 1 }}
        }}
      }}
    }});
  }}
  renderChart(30);
  document.querySelectorAll('.chart-tab').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      document.querySelectorAll('.chart-tab').forEach(function(b) {{ b.classList.remove('active'); }});
      this.classList.add('active');
      renderChart(parseInt(this.getAttribute('data-window')));
    }});
  }});
}})();
</script>"""
    else:
        chart_html = """
<div class="panel" style="margin-bottom:16px;">
  <div class="panel-head"><span class="panel-title">Rolling Hit Rate</span></div>
  <div class="perf-empty">No settlement data yet — chart will appear once edges are settled.</div>
</div>"""

    # ---- Recent settlements table ----
    if recent_settled:
        recent_rows_html = ""
        for row in recent_settled:
            match_name = _fmt_match(row["match_key"])
            sp = row["sport"] or ""
            emoji = _SPORT_EMOJI.get(sp, "🏅")
            t_cfg = _TIER_CONFIG.get(row["edge_tier"] or "", {"label": (row["edge_tier"] or "").title(), "cls": "tier-bronze"})
            outcome_cls = "outcome-win" if row["result"] == "hit" else "outcome-loss"
            outcome_lbl = "W" if row["result"] == "hit" else "L"
            bk = BK_DISPLAY.get(row["bookmaker"] or "", (row["bookmaker"] or "").title())
            recent_rows_html += f"""
      <tr>
        <td style="color:var(--muted)">{row['match_date']}</td>
        <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;">{emoji} {match_name}</td>
        <td><span class="tier-badge {t_cfg['cls']}">{t_cfg['label']}</span></td>
        <td class="{outcome_cls}" style="font-weight:700;">{outcome_lbl}</td>
        <td>{row['ev']}%</td>
        <td>{row['odds']}</td>
        <td style="color:var(--muted)">{bk}</td>
      </tr>"""
        recent_table = f"""
<div class="tbl-wrap">
  <table class="tbl">
    <thead><tr>
      <th>Date</th><th>Match</th><th>Tier</th><th>W/L</th>
      <th>Edge %</th><th>Odds</th><th>Bookmaker</th>
    </tr></thead>
    <tbody>{recent_rows_html}</tbody>
  </table>
</div>"""
    else:
        recent_table = '<div class="perf-empty">No settled edges yet. Results will appear here once the settlement pipeline runs.</div>'

    # ---- Tier Health vs Baseline (EDGE-TIER-HEALTH-WATCH-01) ----
    _TIER_BASELINE = {
        "diamond": -20.0, "gold": 33.2, "silver": 12.9, "bronze": 1.6,
    }
    _th_rows = q_all(conn, """
        SELECT edge_tier,
               COUNT(*) as cnt,
               SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as wins,
               ROUND(SUM(CASE WHEN result='hit' THEN 1.0 ELSE 0 END)*100.0/COUNT(*),1) as hit_rate,
               ROUND(SUM(CASE WHEN result='hit' THEN recommended_odds - 1.0 ELSE -1.0 END)
                     / COUNT(*) * 100, 1) as roi_pct
        FROM edge_results
        WHERE result IN ('hit','miss')
          AND settled_at >= datetime('now', '-7 days')
        GROUP BY edge_tier
    """)
    _th_map = {row["edge_tier"]: row for row in _th_rows}

    # Freshness sentinel
    _th_fresh_cls = ""
    _th_fresh_txt = "Never run"
    _th_sentinel = os.path.expanduser("~/scrapers/edge/.tier_health_last_run")
    try:
        with open(_th_sentinel) as _thf:
            from datetime import timezone as _tz
            _th_last = datetime.fromisoformat(_thf.read().strip())
            _th_age_h = round((datetime.now(_tz.utc) - _th_last).total_seconds() / 3600, 1)
            _th_fresh_cls = "s-red" if _th_age_h > 13.0 else "s-green"
            _th_fresh_txt = f"{_th_age_h}h ago"
            if _th_age_h > 13.0:
                _th_fresh_txt += " (STALE)"
    except (OSError, ValueError):
        _th_fresh_cls = "s-red"

    _th_rows_html = ""
    for _thn in _TIER_ORDER:
        _thr = _th_map.get(_thn)
        _bl_roi = _TIER_BASELINE.get(_thn, 0.0)
        _tcfg = _TIER_CONFIG.get(_thn, {"label": _thn.title(), "cls": "tier-bronze"})
        if _thr:
            _live_roi = float(_thr["roi_pct"] or 0)
            _div_pp = round(abs(_live_roi - _bl_roi), 1)
            _n = int(_thr["cnt"])
            _wr = float(_thr["hit_rate"] or 0)
            if _n < 30:
                _status, _st_cls = "GREEN", "s-green"
            elif _div_pp > 30:
                _status, _st_cls = "RED", "s-red"
            elif _div_pp > 20:
                _status, _st_cls = "AMBER", "s-amber"
            else:
                _status, _st_cls = "GREEN", "s-green"
            _note = " (n&lt;30)" if _n < 30 else ""
        else:
            _live_roi, _div_pp, _n, _wr = 0.0, 0.0, 0, 0.0
            _status, _st_cls, _note = "GREEN", "s-green", " (n=0)"
        _roi_cls = "s-green" if _live_roi >= 0 else "s-red"
        _th_rows_html += f"""
      <tr>
        <td><span class="tier-badge {_tcfg['cls']}">{_tcfg['label']}</span></td>
        <td class="{_roi_cls}">{_live_roi}%</td>
        <td>{_bl_roi}%</td>
        <td>{_div_pp}pp</td>
        <td>{_n}</td>
        <td>{_wr}%</td>
        <td class="{_st_cls}" style="font-weight:700">{_status}{_note}</td>
      </tr>"""

    tier_health_panel = f"""
<div class="panel panel-orange-accent" style="margin-bottom:16px;">
  <div class="panel-head">
    <span class="panel-title">Tier Health vs Baseline</span>
    <span class="panel-sub">7-day rolling · INV-03 counterfactual · Last check: <span class="{_th_fresh_cls}">{_th_fresh_txt}</span></span>
  </div>
  <div class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th>Tier</th><th>Live ROI%</th><th>Baseline ROI%</th>
        <th>Divergence</th><th>n</th><th>Win Rate</th><th>Status</th>
      </tr></thead>
      <tbody>{_th_rows_html}</tbody>
    </table>
  </div>
</div>"""

    # ---- Assemble page ----
    return f"""
<style>{_perf_css()}</style>
<div class="topbar">
  <div class="topbar-left">
    <span class="topbar-pill">Edge Performance</span>
  </div>
  <div class="topbar-right">
    <span class="topbar-meta">Updated: <em>{updated}</em></span>
  </div>
</div>
<div class="page">
  {kpi_html}
  {tier_health_panel}
  <div class="grid-2">
    <div class="panel panel-orange-accent">
      <div class="panel-head">
        <span class="panel-title">Performance by Tier</span>
        <span class="panel-sub">{total} edges</span>
      </div>
      {tier_table}
    </div>
    <div class="panel panel-orange-accent">
      <div class="panel-head">
        <span class="panel-title">CLV by Tier</span>
        <span class="panel-sub">{clv_n} samples</span>
      </div>
      {clv_table}
    </div>
    <div class="panel panel-orange-accent">
      <div class="panel-head">
        <span class="panel-title">Performance by Sport</span>
        <span class="panel-sub">{total} edges</span>
      </div>
      {sport_table}
    </div>
  </div>
  {chart_html}
  <div class="panel">
    <div class="panel-head">
      <span class="panel-title">Recent Settlements</span>
      <span class="panel-sub">Last 20</span>
    </div>
    {recent_table}
  </div>
  <div class="footer">MzansiEdge Admin · Edge Performance · {updated}</div>
</div>"""



# -- Unified System Health renderer -------------------------------------------

def render_unified_health_content(conn, db_status: str) -> str:
    """Unified System Health view — tabbed layout (Overview / Alerts / Sources / System)."""
    # ── Gather all data ───────────────────────────────────────────────────────
    sentry   = _fetch_sentry_data()
    res      = _read_server_resources()
    procs    = _read_process_monitor()
    api_rows = _build_api_health(conn)
    coverage = build_coverage_matrix(conn)
    scrapers  = build_scraper_health(conn)
    sources   = build_source_freshness(conn)
    quotas    = build_api_quotas(conn)
    ha_rows  = build_health_alerts_history(conn)
    db_qrows = build_api_quota_from_db(conn)
    shm      = build_source_health_monitor(conn)
    cpg      = build_card_population_gate(conn)
    updated  = datetime.now(_SAST).strftime("%Y-%m-%d %H:%M:%S")

    # ── Derived KPI values ────────────────────────────────────────────────────
    active_scrapers  = sum(1 for s in scrapers if s.get("has_data_24h", False))
    matches_24h      = sum(s["matches_24h"] for s in scrapers)
    total_card_ready = sum(c["card_ready"] for c in coverage)
    total_matches_c  = sum(c["total"] for c in coverage)
    coverage_pct     = round(total_card_ready / total_matches_c * 100, 1) if total_matches_c > 0 else 0
    alert_count      = len(ha_rows)
    active_alert_count = sum(1 for a in ha_rows if not a.get("resolved", False))
    shm_score        = shm["system_score"]
    shm_green        = shm["green_count"]
    shm_total        = shm.get("total_count", 42)
    cpu_1            = res["cpu_1"]
    mem_pct          = res["mem_pct"] or 0

    shm_score_cls    = "c-green" if shm_score >= 80 else ("c-amber" if shm_score >= 50 else ("c-red" if shm_score >= 0 else "c-text"))
    shm_score_disp   = f"{shm_score}" if shm_score >= 0 else "N/A"
    active_cls       = "c-green" if active_scrapers == len(scrapers) else ("c-amber" if active_scrapers > 0 else "c-red")
    cov_cls          = "c-green" if coverage_pct >= 80 else ("c-amber" if coverage_pct >= 40 else "c-red")
    alert_cls        = "c-red" if active_alert_count > 3 else ("c-amber" if active_alert_count > 0 else "c-green")
    cpu_pct_approx   = round((cpu_1 or 0) / 2 * 100) if cpu_1 is not None else 0
    cpu_cls          = "c-green" if cpu_pct_approx < 60 else ("c-amber" if cpu_pct_approx < 85 else "c-red")
    mem_cls          = "c-green" if mem_pct < 70 else ("c-amber" if mem_pct < 90 else "c-red")
    sentry_count     = sentry.get("total_issues", 0) if sentry.get("available") else "—"
    sentry_cls       = "c-green" if sentry_count == 0 else ("c-amber" if isinstance(sentry_count, int) and sentry_count < 5 else "c-red")

    def chip(css_key: str, text: str) -> str:
        cls = {"s-green": "chip-green", "s-amber": "chip-amber",
               "s-red": "chip-red", "s-black": "chip-gray",
               "s-grey": "chip-gray"}.get(css_key, "chip-gray")
        return f'<span class="chip {cls}"><span class="cdot"></span>{text}</span>'

    def _na(v, fmt="{}", suffix=""):
        return "N/A" if v is None else (fmt.format(v) + suffix)

    def _kpi_onclick(metric_name: str, current_val: str, expected_val: str, db_path: str = "~/scrapers/odds.db", extra_cls: str = "") -> str:
        cls = f"kpi{' ' + extra_cls if extra_cls else ''} kpi-clickable"
        return (
            f'onclick="copyPrompt(\'{metric_name}\',\'{current_val}\',\'{expected_val}\',\'{updated}\',\'{db_path}\')" '
            f'class="{cls}" title="Click to copy investigation prompt"'
        )

    shm_kpi_attr     = _kpi_onclick("System Health",      f"{shm_score_disp}%",        ">80%",  extra_cls="kpi-t1") if shm_score_cls == "c-red" else 'class="kpi kpi-t1"'
    alert_kpi_attr   = _kpi_onclick("Active Alerts",      str(active_alert_count),     "<5",    extra_cls="kpi-t1") if alert_cls     == "c-red" else 'class="kpi kpi-t1"'
    scraper_kpi_attr = _kpi_onclick("Active Scrapers",    str(active_scrapers),        str(len(scrapers)))          if active_cls   == "c-red" else 'class="kpi"'
    cov_kpi_attr     = _kpi_onclick("Card Data Coverage", f"{coverage_pct}%",          ">80%",  "~/scrapers/odds.db") if cov_cls == "c-red" else 'class="kpi"'

    # ── Topbar ────────────────────────────────────────────────────────────────
    db_pulse = "pulse-green" if conn else "pulse-red"
    db_color = "var(--green)" if conn else "var(--red)"
    banner = (
        '<div class="banner banner-err">Main database unreachable — panels showing cached/empty data</div>'
        if conn is None else
        '<div class="banner banner-ok">scrapers/odds.db connected and readable</div>'
    )

    topbar = f"""<nav class="topbar">
  <div class="topbar-left">
    <div class="topbar-pill">System Health</div>
  </div>
  <div class="topbar-right">
    <div class="db-status"><span class="pulse {db_pulse}"></span><span style="color:{db_color}">{db_status}</span></div>
    <div class="topbar-meta">Updated <em>{updated} SAST</em> &middot; refreshes in <em id="countdown">5:00</em></div>
  </div>
</nav>
{banner}"""

    # ── KPI Strip (8 cards, 2-tier hierarchy) ─────────────────────────────────
    cpu_disp = f"{cpu_1:.2f}" if cpu_1 is not None else "N/A"
    kpi_strip = f"""<div class="kpi-strip kpi-strip-h">
  <div {shm_kpi_attr}><div class="kpi-lbl">System Health Score</div><div class="kpi-val {shm_score_cls}">{shm_score_disp}<span style="font-size:16px;color:var(--muted);font-weight:400">%</span></div><div class="kpi-sub">{shm_green}/{shm_total} sources green</div></div>
  <div {alert_kpi_attr}><div class="kpi-lbl">Active Alerts (24h)</div><div class="kpi-val {alert_cls}">{active_alert_count}</div><div class="kpi-sub">{alert_count} total &middot; {alert_count - active_alert_count} resolved</div></div>
  <div {scraper_kpi_attr}><div class="kpi-lbl">Active Scrapers</div><div class="kpi-val {active_cls}">{active_scrapers}<span style="font-size:14px;color:var(--muted);font-weight:400">/{len(scrapers)}</span></div><div class="kpi-sub">{matches_24h:,} matches (24h)</div></div>
  <div {cov_kpi_attr}><div class="kpi-lbl">Card Data Coverage</div><div class="kpi-val {cov_cls}">{coverage_pct}<span style="font-size:14px;color:var(--muted);font-weight:400">%</span></div><div class="kpi-sub">2+ SA bookmakers &middot; {total_matches_c} upcoming matches</div></div>
  <div class="kpi"><div class="kpi-lbl">Upcoming Matches</div><div class="kpi-val c-text">{total_matches_c}</div><div class="kpi-sub">next 7 days · {len(coverage)} leagues</div></div>
  <div class="kpi"><div class="kpi-lbl">Sentry Issues</div><div class="kpi-val {sentry_cls}">{sentry_count}</div><div class="kpi-sub">unresolved · mzansi-edge</div></div>
  <div class="kpi"><div class="kpi-lbl">CPU Load (1m)</div><div class="kpi-val {cpu_cls}">{cpu_disp}</div><div class="kpi-sub">{_na(res.get("cpu_5"), "{:.2f}")} / {_na(res.get("cpu_15"), "{:.2f}")} (5m/15m)</div></div>
  <div class="kpi"><div class="kpi-lbl">RAM Usage</div><div class="kpi-val {mem_cls}">{mem_pct}<span style="font-size:14px;color:var(--muted);font-weight:400">%</span></div><div class="kpi-sub">{res.get("mem_used_mb") or 0:,} / {res.get("mem_total_mb") or 0:,} MB</div></div>
</div>"""

    # ── Coverage data for summary ─────────────────────────────────────────────
    p1_rows = ""
    if coverage:
        for c in coverage:
            p1_rows += (
                "<tr>"
                + td(c["sport"].capitalize())
                + td(c["league"])
                + td(c["total"])
                + td(c["card_ready"], "s-green" if c["card_ready"] > 0 else "s-grey")
                + td(f"{c['pct']}%", c["css"])
                + td(c["badge"])
                + "</tr>"
            )
    else:
        p1_rows = '<tr><td colspan="6" style="text-align:center;color:#6b7280;padding:20px">No upcoming matches in next 7 days</td></tr>'

    chart_labels     = json.dumps([_chart_label(c["league"]) for c in coverage])
    chart_card_ready = json.dumps([c["card_ready"]  for c in coverage])
    chart_needs_data = json.dumps([c["needs_data"]  for c in coverage])

    coverage_summary = _build_coverage_summary(coverage, p1_rows)
    exc_shm = _render_exception_source_health(shm)

    # ── Overview tab ──────────────────────────────────────────────────────────
    tab_overview = f"""<div id="tab-overview" class="tab-pane tab-active">
  {kpi_strip}
  {exc_shm}
  {coverage_summary}
</div>"""

    # ── Alerts & Issues tab ───────────────────────────────────────────────────
    # Show 5 most recent, with expand to see all
    ALERT_PREVIEW = 5
    ha_preview = ha_rows[:ALERT_PREVIEW]
    ha_rest    = ha_rows[ALERT_PREVIEW:]

    def _ha_row_html(a: dict) -> str:
        sev = a["severity"]
        is_crit = sev == "critical"
        sev_col = "var(--red)" if is_crit else "var(--amber)"
        sev_icon = "&#x1F534;" if is_crit else "&#x1F7E1;"
        resolved_badge = (
            '<span style="background:rgba(34,197,94,0.1);color:var(--green);border:1px solid rgba(34,197,94,0.2);'
            'border-radius:999px;padding:1px 7px;font-size:10px;font-weight:700;font-family:var(--font-d);margin-left:6px">Resolved</span>'
            if a["resolved"] else ""
        )
        return (
            f'<div class="alert-row">'
            f'<span class="alert-ts">{a["ts"]} SAST</span>'
            f'<span style="color:{sev_col};font-size:13px;flex-shrink:0">{sev_icon}</span>'
            f'<div style="min-width:0">'
            f'<div style="font-family:var(--font-d);font-size:11px;font-weight:700;color:var(--text)">{a["source_name"]}</div>'
            f'<div class="alert-msg">{_truncate(a["message"], 120)}{resolved_badge}</div>'
            f'</div>'
            f'</div>'
        )

    if ha_rows:
        ha_preview_html = "".join(_ha_row_html(a) for a in ha_preview)
        ha_rest_html = (
            f'<details><summary class="alert-limit-note">+ {len(ha_rest)} more alerts — click to expand</summary>'
            f'{"".join(_ha_row_html(a) for a in ha_rest)}</details>'
            if ha_rest else ""
        )
        ha_html = ha_preview_html + ha_rest_html
    else:
        ha_html = '<div style="text-align:center;color:var(--green);padding:28px;font-family:var(--font-m);font-size:12px">&#10003; No EdgeOps alerts in the last 24h</div>'

    alerts_count_badge = f'<span class="alert-badge">{active_alert_count}</span>' if active_alert_count else ""
    resolved_count = alert_count - active_alert_count
    alerts_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Alert History (24h){alerts_count_badge}</span>'
        f'<span class="panel-sub">health_alerts table &middot; {active_alert_count} active &middot; {resolved_count} resolved</span>'
        f'</div><div class="alerts-scroll">{ha_html}</div></div>'
    )

    # Sentry panel
    if not sentry["available"]:
        err_msg = sentry.get("error") or "Sentry unavailable"
        if "not configured" in err_msg:
            sentry_body = (
                f'<div style="padding:24px;font-family:var(--font-m);font-size:13px;color:var(--muted)">'
                f'<div style="color:var(--amber);font-weight:700;margin-bottom:10px">&#9888; Sentry not configured</div>'
                f'<div>Add <code>SENTRY_AUTH_TOKEN</code> to <code>~/bot/.env</code> and restart.</div></div>'
            )
        else:
            sentry_body = f'<div style="padding:24px;font-family:var(--font-m);font-size:12px;color:var(--red)">Sentry unavailable: {err_msg}</div>'
    else:
        level_colours = {"error": "var(--red)", "warning": "var(--amber)", "info": "var(--green)", "fatal": "#ef4444"}
        level_html = "".join(
            f'<span style="background:{level_colours.get(lvl,"")}22;color:{level_colours.get(lvl,"")};border:1px solid {level_colours.get(lvl,"")}44;'
            f'border-radius:999px;padding:2px 10px;font-size:11px;font-weight:700;font-family:var(--font-d);margin-right:6px">'
            f'{lvl.upper()} {cnt}</span>'
            for lvl, cnt in sorted(sentry["by_level"].items(), key=lambda x: -x[1])
        )
        issue_rows = "".join(
            f'<tr>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{i.get("short_id","")}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;max-width:320px;overflow:hidden;text-overflow:ellipsis">'
            f'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{level_colours.get(i.get("level","error"),"")}; margin-right:6px"></span>'
            f'{i.get("title","")}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px;text-align:right">{i.get("count","—")}</td>'
            f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{_relative_time(i.get("last_seen"))}</td>'
            f'</tr>'
            for i in sentry["top_issues"]
        )
        sentry_body = (
            f'<div style="padding:12px 16px 8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
            f'<span style="font-family:var(--font-d);font-size:22px;font-weight:700;color:var(--text)">{sentry["total_issues"]}</span>'
            f'<span style="font-family:var(--font-m);font-size:12px;color:var(--muted)">open issues</span>'
            f'<span style="flex:1"></span>{level_html}</div>'
            f'<div class="tbl-wrap tbl-fixed"><table class="tbl"><thead><tr><th>ID</th><th>Error</th><th>Events</th><th>Last Seen</th></tr></thead>'
            f'<tbody>{issue_rows}</tbody></table></div>'
        )

    sentry_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Sentry Issues</span>'
        f'<span class="panel-sub">mzansi-edge &middot; unresolved &middot; top 5 by frequency</span>'
        f'</div>{sentry_body}</div>'
    )

    tab_alerts = f"""<div id="tab-alerts" class="tab-pane">
  {alerts_panel}
  {sentry_panel}
</div>"""

    # ── Data Sources tab ──────────────────────────────────────────────────────
    shm_full_panel = _render_source_health_panel(shm)
    cpg_panel = _render_card_population_gate_panel(cpg)

    p2_rows = "".join(
        "<tr>"
        + td(s["name"])
        + td(chip(s["css"], s["last_pull"]))
        + td(f'{s.get("records_24h", "—"):,}' if isinstance(s.get("records_24h"), int) else "—")
        + td(s.get("trend_7d", "—"))
        + "</tr>"
        for s in sources
    )
    freshness_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Data Source Freshness</span>'
        f'<span class="panel-sub">&lt;1h &middot; 1-6h &middot; &gt;6h</span>'
        f'</div><div class="tbl-wrap tbl-fixed"><table class="tbl">'
        f'<thead><tr><th>Source</th><th>Last Pull</th><th>Records (24h)</th><th>7d Trend</th></tr></thead>'
        f'<tbody>{p2_rows}</tbody></table></div></div>'
    )

    p3_rows = "".join(
        "<tr>"
        + td(s["name"])
        + td(chip(s["css"], s["last_scrape"]))
        + td(s["matches_24h"])
        + td(s["avg_odds"])
        + "</tr>"
        for s in scrapers
    )
    scraper_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Scraper Health</span>'
        f'<span class="panel-sub">8 SA bookmakers &middot; last 24h</span>'
        f'</div><div class="tbl-wrap tbl-fixed"><table class="tbl">'
        f'<thead><tr><th>Bookmaker</th><th>Last Scrape</th><th>Matches (24h)</th><th>Avg Odds/Match</th></tr></thead>'
        f'<tbody>{p3_rows}</tbody></table></div></div>'
    )

    api_table_rows = "".join(
        f'<tr>'
        f'<td style="padding:6px 12px;font-family:var(--font-d);font-size:12px;font-weight:600">{r["api"]}</td>'
        f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px">{dot(r["css"])}{r["last_call"]}</td>'
        f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px">{r["calls_24h"]}</td>'
        f'<td style="padding:6px 12px;font-family:var(--font-m);font-size:12px" class="{"s-red" if r["errors_24h"]>3 else ("s-amber" if r["errors_24h"]>0 else "")}">{r["errors_24h"] if r["errors_24h"] else "—"}</td>'
        f'</tr>'
        for r in api_rows
    )
    api_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">API Health</span>'
        f'<span class="panel-sub">api_usage table &middot; last 24h</span>'
        f'</div><div class="tbl-wrap tbl-fixed"><table class="tbl">'
        f'<thead><tr><th>API</th><th>Last Call</th><th>Calls (24h)</th><th>Errors (24h)</th></tr></thead>'
        f'<tbody>{api_table_rows}</tbody></table></div></div>'
    )

    # Enrich The Odds API entry with live health_checker data when available
    if db_qrows:
        db_odds = next((r for r in db_qrows if "odds" in r["api"].lower()), None)
        if db_odds:
            for q in quotas:
                if q["api"] == "The Odds API":
                    if db_odds["used"] != "—":
                        q["used_today"] = db_odds["used"]
                    # Parse formatted remaining string ("18,368") back to int for arithmetic
                    if db_odds["remaining"] not in ("—", None):
                        try:
                            q["remaining"] = int(str(db_odds["remaining"]).replace(",", ""))
                        except (ValueError, TypeError):
                            pass
                    q["plan"] = f"Upgraded · {db_odds['period'].capitalize()} ({db_odds['pct_used']}% used)"
                    break

    dq_rows = ""
    for q in quotas:
        used    = q.get("used_today")
        limit   = q.get("daily_limit")
        remain  = q.get("remaining")
        link    = q.get("link", "#")
        used_cell   = str(used)   if used   is not None else f'<a href="{link}" target="_blank" style="color:#F8C830;font-size:11px">Check dashboard</a>'
        remain_cell = str(remain) if remain is not None else "—"
        limit_cell  = str(limit)  if limit  is not None else "—"
        if "_low" in q:
            rcss = "s-red" if q["_low"] else "s-green"
        elif remain is not None and limit:
            pct = remain / limit
            rcss = "s-green" if pct > 0.5 else ("s-amber" if pct > 0.2 else "s-red")
        else:
            rcss = "s-grey"
        dq_rows += (
            "<tr>"
            + td(q["api"])
            + td(q.get("plan", "—"))
            + td(limit_cell)
            + td(used_cell)
            + td(remain_cell, rcss)
            + td(q.get("reset", "—"))
            + "</tr>"
        )
    quota_hdr = '<tr><th>API</th><th>Plan</th><th>Daily Limit</th><th>Used Today</th><th>Remaining</th><th>Reset</th></tr>'

    quota_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">API Quota Tracker</span>'
        f'<span class="panel-sub">Live from api_quota_tracking &middot; health_checker verified</span>'
        f'</div><div class="tbl-wrap tbl-fixed"><table class="tbl"><thead>{quota_hdr}</thead>'
        f'<tbody>{dq_rows}</tbody></table></div></div>'
    )

    tab_sources = f"""<div id="tab-sources" class="tab-pane">
  {shm_full_panel}
  {cpg_panel}
  <div class="grid-2">
    {scraper_panel}
    {freshness_panel}
  </div>
  <div class="grid-2">
    {api_panel}
    {quota_panel}
  </div>
</div>"""

    # ── System tab ────────────────────────────────────────────────────────────
    mem_pct_v  = res["mem_pct"] or 0
    swap_pct_v = res["swap_pct"] or 0
    disk_pct_v = res["disk_pct"] or 0
    cpu_pct_approx2 = round((cpu_1 or 0) / 2 * 100) if cpu_1 is not None else None
    cpu_bar  = _pbar(cpu_pct_approx2, _na(cpu_1, "{:.2f}")) if cpu_1 is not None else '<span style="color:var(--muted);font-size:12px">N/A</span>'
    mem_bar  = _pbar(mem_pct_v,  f'{res["mem_used_mb"] or 0:,} MB / {res["mem_total_mb"] or 0:,} MB ({mem_pct_v}%)')
    swap_bar = _pbar(swap_pct_v, f'{res["swap_used_mb"] or 0:,} MB ({swap_pct_v}%)')
    disk_bar = _pbar(disk_pct_v, f'{res["disk_used"] or "—"} / {res["disk_total"] or "—"} ({disk_pct_v}%)')

    resources_panel = f"""<div class="panel"><div class="panel-head">
  <span class="panel-title">Server Resources</span>
  <span class="panel-sub">/proc/loadavg &middot; /proc/meminfo &middot; df /</span>
</div>
<div style="padding:16px;display:grid;gap:14px">
  <div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">CPU Load (1m / 5m / 15m)</div>
  {cpu_bar}
  <div style="font-family:var(--font-m);font-size:11px;color:var(--muted);margin-top:4px">{_na(cpu_1, "{:.2f}")} / {_na(res.get("cpu_5"), "{:.2f}")} / {_na(res.get("cpu_15"), "{:.2f}")}</div></div>
  <div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">RAM Usage</div>{mem_bar}</div>
  <div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Swap Usage</div>{swap_bar}</div>
  <div><div style="font-family:var(--font-d);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Disk Usage (/)</div>{disk_bar}</div>
</div></div>"""

    def _proc_row(label: str, info: dict) -> str:
        if info["running"]:
            d = f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 4px var(--green);margin-right:8px"></span>'
            status = f'{d}<span style="color:var(--green);font-weight:700">Running</span>'
            detail = f'PID {info["pid"]} &middot; started {info["started"]}'
        else:
            d = f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--red);margin-right:8px"></span>'
            status = f'{d}<span style="color:var(--red);font-weight:700">Not running</span>'
            detail = "—"
        return (f'<tr><td style="padding:8px 12px;font-family:var(--font-d);font-size:12px;font-weight:600">{label}</td>'
                f'<td style="padding:8px 12px;font-family:var(--font-m);font-size:12px">{status}</td>'
                f'<td style="padding:8px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{detail}</td></tr>')

    proc_rows = (
        _proc_row("bot.py", procs["bot"])
        + _proc_row("health_dashboard.py", procs["dashboard"])
        + _proc_row("publisher.py (cron)", procs.get("publisher", {"running": False, "pid": None, "started": ""}))
    )
    cron_html = ""
    if procs["cron_jobs"]:
        cron_rows = "".join(
            f'<tr><td style="padding:5px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{j["schedule"]}</td>'
            f'<td style="padding:5px 12px;font-family:var(--font-m);font-size:11px">{j["cmd"]}</td></tr>'
            for j in procs["cron_jobs"]
        )
        cron_html = (
            f'<div style="padding:0 12px 4px;font-family:var(--font-d);font-size:10px;font-weight:700;'
            f'letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-top:12px">Cron Jobs</div>'
            f'<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Schedule</th><th>Command</th></tr></thead>'
            f'<tbody>{cron_rows}</tbody></table></div>'
        )

    processes_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Process Monitor</span>'
        f'<span class="panel-sub">pgrep &middot; crontab -l</span>'
        f'</div>'
        f'<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Process</th><th>Status</th><th>Detail</th></tr></thead>'
        f'<tbody>{proc_rows}</tbody></table></div>{cron_html}</div>'
    )

    tab_system = f"""<div id="tab-system" class="tab-pane">
  <div class="grid-2">
    {resources_panel}
    {processes_panel}
  </div>
</div>"""

    # ── Assemble page ─────────────────────────────────────────────────────────
    return f"""{topbar}
<div class="page">
  <div class="tab-bar">
    <button class="tab-btn tab-active" onclick="switchTab('overview',this)">Overview</button>
    <button class="tab-btn" onclick="switchTab('alerts',this)">Alerts &amp; Issues{(' <span class="alert-badge">' + str(active_alert_count) + '</span>') if active_alert_count else ''}</button>
    <button class="tab-btn" onclick="switchTab('sources',this)">Data Sources</button>
    <button class="tab-btn" onclick="switchTab('system',this)">System</button>
  </div>

  {tab_overview}
  {tab_alerts}
  {tab_sources}
  {tab_system}

  <div class="footer">Auto-refreshes in <span id="countdown2">5:00</span> &middot; MzansiEdge Ops &middot; Read-only</div>
</div>

<script>
function switchTab(id, btn) {{
  document.querySelectorAll('.tab-pane').forEach(function(p) {{ p.classList.remove('tab-active'); }});
  document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('tab-active'); }});
  document.getElementById('tab-' + id).classList.add('tab-active');
  btn.classList.add('tab-active');
  if (id === 'overview') {{ initCoverageChart(); }}
}}

function initCoverageChart() {{
  var labels        = {chart_labels};
  var cardReadyData = {chart_card_ready};
  var needsDataData = {chart_needs_data};
  var ctx = document.getElementById('coverageChart');
  if (!ctx || !labels.length) return;
  if (ctx._chartInstance) {{ ctx._chartInstance.destroy(); }}
  ctx._chartInstance = new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [
        {{ label: 'Card Data (2+ bk)', data: cardReadyData, backgroundColor: 'rgba(34,197,94,0.8)', borderRadius: 4 }},
        {{ label: 'Needs Data',        data: needsDataData, backgroundColor: 'rgba(239,68,68,0.65)',  borderRadius: 4 }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
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
}}

// Init chart when coverage accordion is opened
document.addEventListener('DOMContentLoaded', function() {{
  var details = document.querySelector('#tab-overview details');
  if (details) {{
    details.addEventListener('toggle', function() {{
      if (details.open) initCoverageChart();
    }});
  }}
  // Also try init immediately if accordion already open
  initCoverageChart();
}});

document.addEventListener('healthViewLoaded', function() {{
  setTimeout(initCoverageChart, 100);
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

function copyPrompt(metricName, currentValue, expectedValue, lastTs, dbPath) {{
  var prompt = 'Investigate: ' + metricName + ' showing ' + currentValue + ' (expected: ' + expectedValue + ').\\n' +
    'Last data: ' + lastTs + '. Server: 178.128.171.28\\n' +
    'Relevant path: ' + dbPath + '\\n' +
    'Steps: Check cron schedule, review logs, verify DB connectivity, check Sentry for related errors.';
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(prompt).then(function() {{
      var toast = document.getElementById('copy-toast');
      if (!toast) {{
        toast = document.createElement('div');
        toast.id = 'copy-toast';
        toast.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#22c55e;color:#000;padding:8px 16px;border-radius:6px;font-size:13px;z-index:9999;font-family:sans-serif';
        document.body.appendChild(toast);
      }}
      toast.textContent = 'Prompt copied \u2713';
      toast.style.display = 'block';
      setTimeout(function() {{ toast.style.display = 'none'; }}, 2000);
    }});
  }}
}}
</script>"""


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
<div id="loading-bar"></div>
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
        content = render_unified_health_content(conn, db_status)
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


@app.route("/admin/system")
@require_auth
def admin_system():
    return redirect("/admin/health", code=302)


@app.route("/admin/customers")
@require_auth
def admin_customers_redirect():
    return redirect("/admin/system", code=302)


# -- Task Hub cache flush (Refresh Now button) --------------------------------

@app.route("/admin/api/task_hub_refresh", methods=["POST"])
@require_auth
def api_task_hub_refresh():
    """Flush Task Hub caches so the next load fetches fresh data from Notion."""
    with _notion_cache_lock:
        _notion_cache.pop("marketing_queue", None)
        _notion_cache.pop("task_hub_blocks", None)
    return Response('{"ok":true}', mimetype="application/json")


@app.route("/admin/api/task_hub_badge")
@require_auth
def api_task_hub_badge():
    """Return live Task Hub badge count (pending approvals + manual tasks)."""
    try:
        mq, _ = _fetch_marketing_queue()
        count = len(_get_awaiting_items(mq, include_overdue=False))
    except Exception:
        count = 0
    return Response(json.dumps({"count": count}), mimetype="application/json")


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
        content = render_unified_health_content(conn, db_status)
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


@app.route("/admin/task-hub")
@require_auth
def admin_task_hub():
    content = render_task_hub_content()
    html = render_shell("task_hub", content)
    return Response(html, mimetype="text/html")


@app.route("/admin/api/task_hub")
@require_auth
def api_task_hub():
    content = render_task_hub_content()
    return Response(content, mimetype="text/html")


@app.route("/admin/api/system_health")
@require_auth
def api_system_health():
    # Merged into /admin/api/health — serve unified content
    return api_health()


@app.route("/admin/api/notion/patch", methods=["POST"])
@require_auth
def api_notion_patch():
    """PATCH a Notion page status (Approved or Archived)."""
    try:
        body = request.get_json(force=True)
        page_id = (body or {}).get("page_id", "").strip()
        new_status = (body or {}).get("status", "").strip()
    except Exception:
        return Response('{"error":"bad request"}', status=400, mimetype="application/json")

    if not page_id or new_status not in ("Approved", "Archived"):
        return Response('{"error":"invalid params"}', status=400, mimetype="application/json")

    patch_body = {"properties": {"Status": {"select": {"name": new_status}}}}
    result = _notion_request(f"pages/{page_id}", body=patch_body, method="PATCH")
    if result and result.get("object") == "page":
        # Invalidate notion cache so next load reflects the change
        with _notion_cache_lock:
            _notion_cache.pop("marketing_queue", None)
        with _page_cache_lock:
            _page_cache.pop("automation_full", None)
            _page_cache.pop("automation_content", None)
        return Response('{"ok":true}', mimetype="application/json")
    else:
        return Response('{"error":"notion update failed"}', status=502, mimetype="application/json")


@app.route("/admin/api/dismiss-item", methods=["POST"])
@require_auth
def api_dismiss_item():
    """Dismiss a Failed/Blocked item — PATCH Notion status to Archived."""
    try:
        body = request.get_json(force=True)
        page_id = (body or {}).get("page_id", "").strip()
    except Exception:
        return Response('{"error":"bad request"}', status=400, mimetype="application/json")

    if not page_id:
        return Response('{"error":"missing page_id"}', status=400, mimetype="application/json")

    patch_body = {"properties": {"Status": {"select": {"name": "Archived"}}}}
    result = _notion_request(f"pages/{page_id}", body=patch_body, method="PATCH")
    if result and result.get("object") == "page":
        with _notion_cache_lock:
            _notion_cache.pop("marketing_queue", None)
        with _page_cache_lock:
            _page_cache.pop("automation_full", None)
            _page_cache.pop("automation_content", None)
        return Response('{"ok":true}', mimetype="application/json")
    else:
        return Response('{"error":"notion update failed"}', status=502, mimetype="application/json")


@app.route("/admin/api/done-block", methods=["POST"])
@require_auth
def api_done_block():
    """Mark a Notion to_do block as checked (done)."""
    try:
        body = request.get_json(force=True)
        block_id = (body or {}).get("block_id", "").strip()
    except Exception:
        return Response('{"error":"bad request"}', status=400, mimetype="application/json")

    if not block_id:
        return Response('{"error":"missing block_id"}', status=400, mimetype="application/json")

    patch_body = {"to_do": {"checked": True}}
    result = _notion_request(f"blocks/{block_id}", body=patch_body, method="PATCH")
    if result and result.get("object") == "block":
        with _notion_cache_lock:
            _notion_cache.pop("task_hub_blocks", None)
        return Response('{"ok":true}', mimetype="application/json")
    else:
        return Response('{"error":"notion update failed"}', status=502, mimetype="application/json")


@app.route("/admin/api/notion/page/<page_id>")
@require_auth
def api_notion_page(page_id: str):
    """Return an HTML snippet for a single Notion page (schedule expand panel)."""
    # Find item in cache
    items = []
    with _notion_cache_lock:
        cached = _notion_cache.get("marketing_queue")
        if cached:
            items = cached[0]

    item = next((i for i in items if i.get("id", "").replace("-", "") == page_id.replace("-", "")), None)
    if not item:
        return Response('<div style="color:var(--muted);font-family:var(--font-m);font-size:12px">Post not found in cache.</div>', mimetype="text/html")

    ch_key = _normalise_channel_key(item.get("channel") or "")
    ch = _CHANNEL_MAP.get(ch_key)
    ch_html = (f'<span class="ch-chip" style="background:{ch["color"]}22;color:{ch["color"]};border:1px solid {ch["color"]}33">'
               f'{ch["label"]}</span>') if ch else ""

    sched_str = _sast_hhmm(item.get("scheduled_time")) + " SAST" if item.get("scheduled_time") else "\u2014"
    copy_text = item.get("copy") or ""
    asset_link = item.get("asset_link") or ""
    campaign = item.get("campaign_theme") or ""

    if asset_link:
        ext = asset_link.rsplit(".", 1)[-1].lower().split("?")[0] if "." in asset_link else ""
        if ext in ("mp4", "mov", "webm"):
            media_html = f'<video src="{asset_link}" controls style="max-height:300px;border-radius:4px;display:block;margin-top:10px;width:auto;"></video>'
        elif ext in ("jpg", "jpeg", "png", "gif", "webp"):
            media_html = f'<img src="{asset_link}" style="max-height:300px;border-radius:4px;object-fit:cover;display:block;margin-top:10px;">'
        else:
            media_html = ""
    else:
        media_html = ""

    html = f"""<div style="font-family:var(--font-m)">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
    {ch_html}
    <span style="font-size:11px;color:var(--muted)">&#128337; {sched_str}</span>
    {f'<span style="color:var(--gold);font-size:11px">{campaign}</span>' if campaign else ""}
  </div>
  <div style="font-size:13px;line-height:1.6;white-space:pre-wrap;word-break:break-word">{copy_text}</div>
  {media_html}
</div>"""
    return Response(html, mimetype="text/html")


@app.route("/admin/performance")
@require_auth
def admin_performance():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("performance_full")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    conn = db_connect(SCRAPERS_DB)
    try:
        content = render_performance_content(conn)
    finally:
        if conn:
            conn.close()

    html = render_shell("performance", content)

    with _page_cache_lock:
        _page_cache["performance_full"] = (html, now)

    return Response(html, mimetype="text/html")


@app.route("/admin/api/performance")
@require_auth
def api_performance():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("performance_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    conn = db_connect(SCRAPERS_DB)
    try:
        content = render_performance_content(conn)
    finally:
        if conn:
            conn.close()

    with _page_cache_lock:
        _page_cache["performance_content"] = (content, now)

    return Response(content, mimetype="text/html")


@app.route("/admin/approvals")
@require_auth
def admin_approvals():
    content = render_approvals_content()
    html = render_shell("approvals", content)
    return Response(html, mimetype="text/html")


@app.route("/admin/api/approvals")
@require_auth
def api_approvals():
    content = render_approvals_content()
    return Response(content, mimetype="text/html")


@app.route("/admin/api/health-log/<source_id>")
@require_auth
def api_health_log(source_id: str):
    """Return last 24h health log for a source as JSON."""
    conn = db_connect(SCRAPERS_DB)
    if conn is None:
        return Response('{"error":"db unavailable"}', status=503, mimetype="application/json")
    try:
        rows = q_all(conn, """
            SELECT checked_at, status, minutes_since_success, rows_produced, error_message
            FROM source_health_log
            WHERE source_id = ?
              AND checked_at >= datetime('now', '-24 hours')
            ORDER BY checked_at ASC
        """, (source_id,))
        data = [dict(r) for r in rows]
        return Response(json.dumps(data), mimetype="application/json")
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")
    finally:
        conn.close()


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
