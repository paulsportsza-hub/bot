#!/usr/bin/env python3
"""
MzansiEdge — Founder-Facing Data Pipeline Health Dashboard
Served at /ops/health on port 8501.
Read-only access to SQLite. Never writes to any DB.
"""

import functools
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

from flask import Flask, Response, request

# ── Response cache (avoids 5s full-table-scan queries on every request) ──────
_page_cache: dict[str, tuple[str, float]] = {}
_page_cache_lock = threading.Lock()
_PAGE_CACHE_TTL = 60  # seconds — heavy queries run at most once per minute

# ── Config ────────────────────────────────────────────────────────────────────
SCRAPERS_DB = os.path.expanduser("~/scrapers/odds.db")
BOT_DB = os.path.expanduser("~/bot/data/mzansiedge.db")
TIPSTER_DB = os.path.expanduser("~/scrapers/tipsters/tipster_predictions.db")
QUOTAS_FILE = os.path.join(os.path.dirname(__file__), "api_quotas.json")

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "mzansiedge")
PORT = int(os.getenv("DASHBOARD_PORT", "8501"))

# ── League chart labels (full names, not truncated) ───────────────────────────

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

app = Flask(__name__)


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != DASHBOARD_USER or auth.password != DASHBOARD_PASS:
            return Response(
                "Unauthorized — MzansiEdge Ops Dashboard",
                401,
                {"WWW-Authenticate": 'Basic realm="MzansiEdge Ops"'},
            )
        return f(*args, **kwargs)
    return wrapper


# ── DB helpers ────────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

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
        return "s-green", "🟢 Healthy"
    elif pct >= 50:
        return "s-amber", "🟡 Degraded"
    elif pct > 0:
        return "s-red", "🔴 Critical"
    else:
        return "s-black", "⚫ No Data"


# ── Panel data builders ───────────────────────────────────────────────────────

def build_coverage_matrix(conn) -> list[dict]:
    if not table_exists(conn, "odds_snapshots"):
        return []
    rows = q_all(conn, """
        SELECT u.sport, u.league,
            COUNT(DISTINCT u.match_id)                                          AS total,
            COUNT(CASE WHEN nc.narrative_source = 'w84'           THEN 1 END)  AS w84,
            COUNT(CASE WHEN nc.narrative_source = 'w82'           THEN 1 END)  AS w82,
            COUNT(CASE WHEN nc.narrative_source = 'baseline_no_edge' THEN 1 END) AS baseline
        FROM (
            SELECT DISTINCT match_id, sport, league
            FROM   odds_snapshots
            WHERE  substr(match_id, -10) BETWEEN date('now') AND date('now', '+7 days')
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

    # ── Rugby watchlist: URC / Varsity Cup / Currie Cup visibility ────────────
    _RUGBY_WATCHLIST = [
        ("urc",     "URC"),
        ("varsity",  "Varsity Cup"),
        ("currie",   "Currie Cup"),
    ]

    # Query ALL odds_snapshots for any rugby/urc/varsity/currie keys (not just upcoming)
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

    # Leagues already in the matrix (upcoming matches)
    in_matrix = {c["league"].lower() for c in out}

    for kw, display in _RUGBY_WATCHLIST:
        # Already shown via main upcoming-match query?
        if any(kw in lg for lg in in_matrix):
            continue
        # In odds_snapshots (any date) but no upcoming matches?
        in_db = any(kw in lg for lg in found_rugby_leagues)
        badge = "⚫ No Data" if in_db else "○ Not Tracked"
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
        return "—"
    if prev_7d == 0:
        return f"{current_7d:,} ↑"
    delta_pct = (current_7d - prev_7d) / prev_7d
    if delta_pct > 0.1:
        arrow = "↑"
    elif delta_pct < -0.1:
        arrow = "↓"
    else:
        arrow = "→"
    return f"{current_7d:,} {arrow}"


def build_source_freshness(conn) -> list[dict]:
    out = []

    def row(name, last_ts, records_24h, trend_7d="—"):
        css, lbl = freshness(last_ts)
        out.append({
            "name": name, "last_pull": lbl,
            "records_24h": records_24h,
            "css": css, "trend_7d": trend_7d,
        })

    # SA bookmakers — derive from scrape_runs
    if table_exists(conn, "scrape_runs"):
        r = q_one(conn, "SELECT finished_at, bookmaker_summary FROM scrape_runs ORDER BY id DESC LIMIT 1")
        if r:
            try:
                total = sum(json.loads(r["bookmaker_summary"] or "{}").values())
            except Exception:
                total = 0
            # 7d trend from odds_snapshots
            c7 = q_one(conn, "SELECT COUNT(*) as c FROM odds_snapshots WHERE scraped_at >= datetime('now','-7 days')")
            c14 = q_one(conn, "SELECT COUNT(*) as c FROM odds_snapshots WHERE scraped_at >= datetime('now','-14 days') AND scraped_at < datetime('now','-7 days')")
            trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
            row("SA Bookmakers (8x)", r["finished_at"], total, trend)
        else:
            row("SA Bookmakers (8x)", None, 0)
    else:
        out.append({"name": "SA Bookmakers (8x)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "—"})

    # The Odds API (sharp)
    if table_exists(conn, "sharp_odds"):
        r = q_one(conn, "SELECT MAX(scraped_at) as last FROM sharp_odds")
        c = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-24 hours')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-14 days') AND scraped_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        row("The Odds API (Sharp)", r["last"] if r else None, (c["c"] if c else 0), trend)
    else:
        out.append({"name": "The Odds API (Sharp)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "—"})

    # ESPN
    if table_exists(conn, "espn_stats_cache"):
        r = q_one(conn, "SELECT MAX(fetched_at) as last, COUNT(*) as c FROM espn_stats_cache")
        row("ESPN Hidden API", r["last"] if r else None, r["c"] if r else 0, f"{r['c'] if r else 0} →")
    else:
        out.append({"name": "ESPN Hidden API", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "—"})

    # API-Football (from api_usage table)
    if table_exists(conn, "api_usage"):
        r = q_one(conn, "SELECT MAX(called_at) as last FROM api_usage WHERE api_name='api_football'")
        c = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_football' AND called_at >= date('now')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_football' AND called_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_football' AND called_at >= datetime('now','-14 days') AND called_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        if r and r["last"]:
            row("API-Football", r["last"], c["c"] if c else 0, trend)
        else:
            out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "—"})
    else:
        out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "—"})

    # Narrative cache
    if table_exists(conn, "narrative_cache"):
        r = q_one(conn, "SELECT MAX(created_at) as last FROM narrative_cache")
        c = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-24 hours')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-14 days') AND created_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        row("Narrative Cache", r["last"] if r else None, c["c"] if c else 0, trend)
    else:
        out.append({"name": "Narrative Cache", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "—"})

    # Sportmonks Cricket — not yet integrated
    out.append({"name": "Sportmonks Cricket", "last_pull": "Not Connected", "records_24h": 0, "css": "s-amber", "trend_7d": "—"})

    # Tipster Sources (from tipster_predictions.db)
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
        out.append({"name": "Tipster Sources", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "trend_7d": "—"})

    # WAHA / WhatsApp — not yet integrated
    out.append({"name": "WAHA / WhatsApp", "last_pull": "Not Connected", "records_24h": 0, "css": "s-amber", "trend_7d": "—"})

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


def build_api_quotas() -> list[dict]:
    """Build API quota rows from live DB data."""
    quotas = []
    conn = db_connect(SCRAPERS_DB)  # dashboard's read-only connection

    # ── The Odds API (tracked via sharp_odds scrape batches) ──
    odds_used_month = 0
    odds_used_today = 0
    monthly_limit = 20000
    credits_per_batch = 34  # ~34 credits per scrape run
    if conn:
        try:
            # Monthly: count distinct scrape batches this calendar month
            mr = conn.execute(
                "SELECT COUNT(DISTINCT substr(scraped_at,1,16)) as batches "
                "FROM sharp_odds WHERE scraped_at >= strftime('%Y-%m-01','now')"
            ).fetchone()
            if mr:
                odds_used_month = (mr["batches"] or 0) * credits_per_batch
            # Today
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

    # ── API-Football (tracked via api_usage table) ──
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

    # ── Sportmonks Cricket (not yet connected) ──
    quotas.append({
        "api": "Sportmonks Cricket",
        "plan": "Not Connected",
        "daily_limit": None,
        "used_today": None,
        "remaining": None,
        "reset": "—",
    })

    if conn:
        try:
            conn.close()
        except Exception:
            pass

    return quotas


def build_alerts(conn) -> list[dict]:
    alerts = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if conn is None:
        return [{"ts": now_str, "sev": "🔴", "msg": "Main DB unreachable — all panels degraded"}]

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
                    "ts": now_str, "sev": "🔴",
                    "msg": f"Scraper silent — {BK_DISPLAY.get(bk, bk)}: 0 records in last 6h",
                })

    # Sports with 0% w84 coverage
    for c in build_coverage_matrix(conn):
        if c["total"] > 0 and c["w84"] == 0:
            alerts.append({
                "ts": now_str, "sev": "🟡",
                "msg": f"Zero w84 — {c['sport'].upper()} / {c['league']}: {c['total']} matches, all {('w82' if c['w82'] else 'baseline')}",
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
                "sev": "🟡",
                "msg": f"Edge data present but narrative={r['narrative_source']}: {r['match_id']}",
            })

    return sorted(alerts, key=lambda x: x["ts"], reverse=True)[:50]


# ── HTML renderer ─────────────────────────────────────────────────────────────

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


def render_page(conn, db_status: str) -> str:
    coverage = build_coverage_matrix(conn)
    scrapers  = build_scraper_health(conn)
    sources   = build_source_freshness(conn)
    quotas    = build_api_quotas()
    alerts    = build_alerts(conn)
    updated   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    alert_count = len(alerts)

    # ── KPI metrics ──────────────────────────────────────────────────────────
    active_scrapers = sum(1 for s in scrapers if s["css"] == "s-green")
    matches_24h     = sum(s["matches_24h"] for s in scrapers)
    total_w84       = sum(c["w84"]   for c in coverage)
    total_matches_c = sum(c["total"] for c in coverage)
    coverage_pct    = round(total_w84 / total_matches_c * 100, 1) if total_matches_c > 0 else 0

    def chip(css_key: str, text: str) -> str:
        cls = {"s-green": "chip-green", "s-amber": "chip-amber",
               "s-red": "chip-red", "s-black": "chip-gray"}.get(css_key, "chip-gray")
        return f'<span class="chip {cls}"><span class="cdot"></span>{text}</span>'

    # ── Panel 1: Coverage Matrix rows ────────────────────────────────────────
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

    # ── Panel 2: Source Freshness rows ───────────────────────────────────────
    p2_rows = ""
    for s in sources:
        p2_rows += (
            "<tr>"
            + td(s["name"])
            + td(chip(s["css"], s["last_pull"]))
            + td(f'{s.get("records_24h", "—"):,}' if isinstance(s.get("records_24h"), int) else "—")
            + td(s.get("trend_7d", "—"))
            + "</tr>"
        )

    # ── Panel 3: Scraper Health rows ─────────────────────────────────────────
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

    # ── Panel 4: API Quota rows ───────────────────────────────────────────────
    p4_rows = ""
    for q in quotas:
        used    = q.get("used_today")
        limit   = q.get("daily_limit")
        remain  = q.get("remaining")
        link    = q.get("link", "#")

        used_cell   = str(used)   if used   is not None else f'<a href="{link}" target="_blank" style="color:#F8C830;font-size:11px">Check dashboard ↗</a>'
        remain_cell = str(remain) if remain is not None else "—"
        limit_cell  = str(limit)  if limit  is not None else "—"

        # Colour the "remaining" cell
        if remain is not None and limit:
            pct = remain / limit
            rcss = "s-green" if pct > 0.5 else ("s-amber" if pct > 0.2 else "s-red")
        else:
            rcss = "s-black"

        p4_rows += (
            "<tr>"
            + td(q["api"])
            + td(q.get("plan", "—"))
            + td(limit_cell)
            + td(used_cell)
            + td(remain_cell, rcss)
            + td(q.get("reset", "—"))
            + "</tr>"
        )

    # ── Panel 5: Alert rows ───────────────────────────────────────────────────
    p5_rows = ""
    if alerts:
        for a in alerts:
            sev_style = "color:#ef4444" if "🔴" in a["sev"] else "color:#f59e0b"
            p5_rows += (
                f'<div class="alert-row">'
                f'<span style="font-family:\'Geist Mono\',monospace;font-size:11px;color:#6b7280">{a["ts"]}</span>'
                f'<span style="{sev_style};margin:0 8px">{a["sev"]}</span>'
                f'<span>{a["msg"]}</span>'
                f'</div>'
            )
    else:
        p5_rows = '<div style="text-align:center;color:#22c55e;padding:20px">✓ No active alerts</div>'

    # ── Chart data ────────────────────────────────────────────────────────────
    chart_labels = json.dumps([_chart_label(c["league"]) for c in coverage])
    chart_w84    = json.dumps([c["w84"]      for c in coverage])
    chart_w82    = json.dumps([c["w82"]      for c in coverage])
    chart_base   = json.dumps([c["baseline"] for c in coverage])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="300">
<title>MzansiEdge — Data Health</title>
<link rel="icon" type="image/x-icon" href="https://mzansiedge.co.za/favicon.ico">
<link rel="icon" type="image/png" sizes="192x192" href="https://mzansiedge.co.za/favicon-192.png">
<link rel="apple-touch-icon" href="https://mzansiedge.co.za/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Work+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
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
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ background: var(--carbon); color: var(--text); font-family: var(--font-b); font-size: 14px; line-height: 1.6; min-height: 100vh; }}
  a {{ color: var(--gold); text-decoration: none; }} a:hover {{ text-decoration: underline; }}

  /* TOPBAR */
  .topbar {{ position: sticky; top: 0; z-index: 100; background: rgba(10,10,10,0.96); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-bottom: 1px solid var(--border); padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
  .topbar-left {{ display: flex; align-items: center; gap: 16px; }}
  .topbar-logo img {{ height: 28px; width: auto; display: block; }}
  .topbar-divider {{ width: 1px; height: 20px; background: var(--border); }}
  .topbar-pill {{ background: rgba(248,200,48,0.1); border: 1px solid rgba(248,200,48,0.2); border-radius: 999px; padding: 3px 12px; font-family: var(--font-d); font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--gold); }}
  .topbar-right {{ display: flex; align-items: center; gap: 20px; }}
  .topbar-meta {{ font-size: 11px; font-family: var(--font-m); color: var(--muted); }}
  .topbar-meta em {{ color: var(--text); font-style: normal; }}
  .db-status {{ display: flex; align-items: center; gap: 6px; font-size: 11px; font-family: var(--font-m); }}
  .pulse {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .pulse-green {{ background: var(--green); box-shadow: 0 0 0 2px rgba(34,197,94,.25); animation: pulse 2s infinite; }}
  .pulse-red   {{ background: var(--red);   box-shadow: 0 0 0 2px rgba(239,68,68,.25); }}
  @keyframes pulse {{ 0%,100% {{ box-shadow: 0 0 0 2px rgba(34,197,94,.25); }} 50% {{ box-shadow: 0 0 0 5px rgba(34,197,94,.1); }} }}

  /* BANNER */
  .banner {{ padding: 7px 24px; font-size: 11px; font-family: var(--font-m); text-align: center; letter-spacing: .02em; }}
  .banner-ok  {{ background: rgba(34,197,94,.06); color: var(--green); border-bottom: 1px solid rgba(34,197,94,.12); }}
  .banner-err {{ background: rgba(239,68,68,.06);  color: var(--red);   border-bottom: 1px solid rgba(239,68,68,.12); }}

  /* PAGE */
  .page {{ max-width: 1440px; margin: 0 auto; padding: 20px 20px 48px; }}

  /* KPI STRIP */
  .kpi-strip {{ display: grid; grid-template-columns: repeat(5,1fr); gap: 12px; margin-bottom: 20px; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 14px 16px; position: relative; overflow: hidden; }}
  .kpi::after {{ content:''; position:absolute; top:0; left:0; right:0; height:2px; background: var(--grad); }}
  .kpi-lbl {{ font-size: 10px; font-family: var(--font-d); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }}
  .kpi-val {{ font-size: 26px; font-family: var(--font-d); font-weight: 700; line-height: 1; }}
  .kpi-sub {{ font-size: 11px; font-family: var(--font-m); color: var(--muted); margin-top: 5px; }}
  .c-gold  {{ color: var(--gold); }}
  .c-green {{ color: var(--green); }}
  .c-amber {{ color: var(--amber); }}
  .c-red   {{ color: var(--red); }}
  .c-text  {{ color: var(--text); }}

  /* PANELS */
  .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); overflow: hidden; margin-bottom: 16px; }}
  .panel-head {{ padding: 11px 18px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 12px; background: rgba(255,255,255,.015); }}
  .panel-title {{ font-family: var(--font-d); font-weight: 700; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--text); }}
  .panel-sub {{ font-size: 11px; font-family: var(--font-m); color: var(--muted); text-align: right; }}

  /* TABLES */
  .tbl-wrap {{ overflow-x: auto; }}
  .tbl {{ width: 100%; border-collapse: collapse; min-width: 480px; }}
  .tbl thead th {{ font-family: var(--font-d); font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; background: rgba(0,0,0,.2); }}
  .tbl tbody td {{ padding: 9px 14px; border-bottom: 1px solid var(--border-sub); font-family: var(--font-m); font-size: 12px; vertical-align: middle; white-space: nowrap; }}
  .tbl tbody tr:last-child td {{ border-bottom: none; }}
  .tbl tbody tr:hover td {{ background: rgba(248,200,48,.025); }}

  /* CHIPS */
  .chip {{ display:inline-flex; align-items:center; gap:5px; padding:3px 9px; border-radius:999px; font-size:10px; font-weight:700; font-family:var(--font-d); letter-spacing:.04em; white-space:nowrap; }}
  .cdot {{ width:6px; height:6px; border-radius:50%; flex-shrink:0; }}
  .chip-green {{ background:rgba(34,197,94,.1);  color:var(--green); border:1px solid rgba(34,197,94,.2);  }} .chip-green .cdot {{ background:var(--green); box-shadow:0 0 4px var(--green); }}
  .chip-amber {{ background:rgba(245,158,11,.1); color:var(--amber); border:1px solid rgba(245,158,11,.2); }} .chip-amber .cdot {{ background:var(--amber); }}
  .chip-red   {{ background:rgba(239,68,68,.1);  color:var(--red);   border:1px solid rgba(239,68,68,.2);  }} .chip-red   .cdot {{ background:var(--red); }}
  .chip-gray  {{ background:rgba(107,114,128,.1);color:var(--muted); border:1px solid rgba(107,114,128,.2);}} .chip-gray  .cdot {{ background:var(--muted); }}

  /* STATUS TEXT (legacy compat) */
  .s-green {{ color:var(--green); font-weight:700; }} .s-amber {{ color:var(--amber); font-weight:700; }} .s-red {{ color:var(--red); font-weight:700; }} .s-black {{ color:var(--muted); font-weight:700; }}

  /* ALERT LOG */
  .alerts-scroll {{ max-height:320px; overflow-y:auto; }}
  .alert-row {{ padding:9px 16px; border-bottom:1px solid var(--border-sub); display:flex; align-items:flex-start; gap:10px; }}
  .alert-row:last-child {{ border-bottom:none; }} .alert-row:hover {{ background:rgba(255,255,255,.02); }}
  .alert-ts {{ font-family:var(--font-m); font-size:10px; color:var(--muted); white-space:nowrap; padding-top:2px; min-width:108px; }}
  .alert-msg {{ font-family:var(--font-m); font-size:12px; line-height:1.45; color:var(--text); }}
  .alert-badge {{ background:var(--red); color:#fff; border-radius:999px; padding:1px 8px; font-size:10px; font-weight:700; margin-left:6px; }}

  /* CHART */
  .chart-wrap {{ padding:16px; height:200px; position:relative; }}

  /* GRID */
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}

  /* FOOTER */
  .footer {{ text-align:center; padding:20px; font-size:11px; font-family:var(--font-m); color:var(--muted); border-top:1px solid var(--border); margin-top:8px; }}
  #countdown {{ color:var(--gold); font-weight:700; }}

  /* RESPONSIVE */
  @media(max-width:1000px) {{ .kpi-strip {{ grid-template-columns:repeat(3,1fr); }} .grid-2 {{ grid-template-columns:1fr; }} }}
  @media(max-width:600px)  {{ .kpi-strip {{ grid-template-columns:repeat(2,1fr); }} .topbar {{ padding:10px 14px; }} }}
</style>
</head>
<body>

<!-- TOPBAR -->
<nav class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">
      <img src="/static/logo.png" alt="MzansiEdge" onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
      <span style="display:none;font-family:var(--font-d);font-weight:700;font-size:16px;background:linear-gradient(135deg,#F8C830,#E8571F);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">MzansiEdge</span>
    </div>
    <div class="topbar-divider"></div>
    <div class="topbar-pill">Data Health</div>
  </div>
  <div class="topbar-right">
    <div class="db-status">
      <span class="pulse {'pulse-green' if conn else 'pulse-red'}"></span>
      <span style="color:{'var(--green)' if conn else 'var(--red)'}">{db_status}</span>
    </div>
    <div class="topbar-meta">Updated <em>{updated} SAST</em> · refreshes in <em id="countdown">5:00</em></div>
  </div>
</nav>

{'<div class="banner banner-err">⚠ Main database unreachable — panels showing cached/empty data</div>' if conn is None else '<div class="banner banner-ok">✓ scrapers/odds.db connected and readable</div>'}

<div class="page">

  <!-- KPI STRIP -->
  <div class="kpi-strip">
    <div class="kpi">
      <div class="kpi-lbl">Active Scrapers</div>
      <div class="kpi-val {'c-green' if active_scrapers == len(scrapers) else 'c-amber' if active_scrapers > 0 else 'c-red'}">{active_scrapers}<span style="font-size:14px;color:var(--muted);font-weight:400">/{len(scrapers)}</span></div>
      <div class="kpi-sub">bookmakers online</div>
    </div>
    <div class="kpi">
      <div class="kpi-lbl">Matches Scraped</div>
      <div class="kpi-val c-gold">{matches_24h:,}</div>
      <div class="kpi-sub">last 24 hours</div>
    </div>
    <div class="kpi">
      <div class="kpi-lbl">Narrative Coverage</div>
      <div class="kpi-val {'c-green' if coverage_pct >= 80 else 'c-amber' if coverage_pct >= 40 else 'c-red'}">{coverage_pct}<span style="font-size:14px;color:var(--muted);font-weight:400">%</span></div>
      <div class="kpi-sub">w84 AI-enriched</div>
    </div>
    <div class="kpi">
      <div class="kpi-lbl">Active Alerts</div>
      <div class="kpi-val {'c-red' if alert_count > 5 else 'c-amber' if alert_count > 0 else 'c-green'}">{alert_count}</div>
      <div class="kpi-sub">pipeline issues</div>
    </div>
    <div class="kpi">
      <div class="kpi-lbl">Leagues Tracked</div>
      <div class="kpi-val c-text">{total_matches_c}</div>
      <div class="kpi-sub">upcoming matches (7d)</div>
    </div>
  </div>

  <!-- Panel 1: Coverage Matrix -->
  <div class="panel">
    <div class="panel-head">
      <span class="panel-title">Sport Coverage Matrix</span>
      <span class="panel-sub">Next 7 days &nbsp;·&nbsp; 🟢 w84 = AI-enriched &nbsp;·&nbsp; 🔴 w82 = Template &nbsp;·&nbsp; 🟡 Baseline = No edge data</span>
    </div>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead>
          <tr>
            <th>Sport</th><th>League</th><th>Matches</th>
            <th>w84 (AI)</th><th>w82 (Template)</th><th>Baseline</th>
            <th>Coverage %</th><th>Status</th>
          </tr>
        </thead>
        <tbody>{p1_rows}</tbody>
      </table>
    </div>
    <div class="chart-wrap">
      <canvas id="coverageChart"></canvas>
    </div>
  </div>

  <div class="grid-2">

    <!-- Panel 2: Source Freshness -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">Data Source Freshness</span>
        <span class="panel-sub">🟢 &lt;1h &nbsp; 🟡 1–6h &nbsp; 🔴 &gt;6h</span>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Source</th><th>Last Pull</th><th>Records (24h)</th><th>7d</th></tr></thead>
          <tbody>{p2_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Panel 3: Scraper Health -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">Scraper Health</span>
        <span class="panel-sub">8 SA bookmakers &nbsp;·&nbsp; last 24h</span>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Bookmaker</th><th>Last Scrape</th><th>Matches (24h)</th><th>Avg Odds/Match</th></tr></thead>
          <tbody>{p3_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Panel 4: API Quotas -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">API Quota Tracker</span>
        <span class="panel-sub">Live from DB &nbsp;·&nbsp; refreshes every 60s</span>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>API</th><th>Plan</th><th>Daily Limit</th><th>Used Today</th><th>Remaining</th><th>Reset</th></tr></thead>
          <tbody>{p4_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Panel 5: Alert Log -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">Alert Log{'<span class="alert-badge">' + str(alert_count) + '</span>' if alert_count else ''}</span>
        <span class="panel-sub">Last 48h &nbsp;·&nbsp; scrapers · coverage · pipeline</span>
      </div>
      <div class="alerts-scroll">{p5_rows}</div>
    </div>

  </div><!-- /grid-2 -->

  <div class="footer">
    Auto-refreshes in <span id="countdown">5:00</span> &nbsp;·&nbsp; MzansiEdge Ops &nbsp;·&nbsp; Read-only
  </div>

</div><!-- /page -->

<script>
(function() {{
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

// Countdown timer
(function() {{
  var secs = 300;
  var el = document.getElementById('countdown');
  setInterval(function() {{
    secs--;
    if (secs <= 0) {{ location.reload(); return; }}
    var m = Math.floor(secs / 60), s = secs % 60;
    if (el) el.textContent = m + ':' + (s < 10 ? '0' : '') + s;
  }}, 1000);
}})();
</script>
</body>
</html>"""


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/ops/health")
@require_auth
def health():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("html")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    conn = db_connect(SCRAPERS_DB)
    db_status = "Connected" if conn else "Unreachable"
    try:
        html = render_page(conn, db_status)
    finally:
        if conn:
            conn.close()

    with _page_cache_lock:
        _page_cache["html"] = (html, now)

    return Response(html, mimetype="text/html")


@app.route("/")
@require_auth
def root():
    return Response(
        '<html><body style="background:#0A0A0A;color:#F5F5F5;font-family:sans-serif;'
        'display:flex;align-items:center;justify-content:center;height:100vh">'
        '<a href="/ops/health" style="color:#F8C830;font-size:18px">→ Go to /ops/health</a>'
        "</body></html>",
        mimetype="text/html",
    )


@app.route("/healthz")
def healthz():
    """Unauthenticated health check for monitoring."""
    return Response("ok", mimetype="text/plain")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"MzansiEdge Health Dashboard starting on port {PORT}")
    print(f"  URL:  http://localhost:{PORT}/ops/health")
    print(f"  Auth: {DASHBOARD_USER}:***")
    print(f"  DB:   {SCRAPERS_DB}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
