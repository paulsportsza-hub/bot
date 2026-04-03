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
from datetime import datetime, timezone

from flask import Flask, Response, request

# ── Config ────────────────────────────────────────────────────────────────────
SCRAPERS_DB = os.path.expanduser("~/scrapers/odds.db")
BOT_DB = os.path.expanduser("~/bot/data/mzansiedge.db")
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


def build_source_freshness(conn) -> list[dict]:
    out = []

    def row(name, last_ts, records_24h, extra=""):
        css, lbl = freshness(last_ts)
        out.append({
            "name": name, "last_pull": lbl,
            "records_24h": records_24h,
            "css": css, "extra": extra,
        })

    # SA bookmakers — derive from scrape_runs
    if table_exists(conn, "scrape_runs"):
        r = q_one(conn, "SELECT finished_at, bookmaker_summary FROM scrape_runs ORDER BY id DESC LIMIT 1")
        if r:
            try:
                total = sum(json.loads(r["bookmaker_summary"] or "{}").values())
            except Exception:
                total = 0
            row("SA Bookmakers (8x)", r["finished_at"], total)
        else:
            row("SA Bookmakers (8x)", None, 0)
    else:
        out.append({"name": "SA Bookmakers (8x)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "extra": ""})

    # The Odds API (sharp)
    if table_exists(conn, "sharp_odds"):
        r = q_one(conn, "SELECT MAX(scraped_at) as last FROM sharp_odds")
        c = q_one(conn, "SELECT COUNT(*) as c FROM sharp_odds WHERE scraped_at >= datetime('now','-24 hours')")
        row("The Odds API (Sharp)", r["last"] if r else None, (c["c"] if c else 0))
    else:
        out.append({"name": "The Odds API (Sharp)", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "extra": ""})

    # ESPN
    if table_exists(conn, "espn_stats_cache"):
        r = q_one(conn, "SELECT MAX(fetched_at) as last, COUNT(*) as c FROM espn_stats_cache")
        row("ESPN Hidden API", r["last"] if r else None, r["c"] if r else 0)
    else:
        out.append({"name": "ESPN Hidden API", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "extra": ""})

    # API-Football
    if table_exists(conn, "api_usage"):
        r = q_one(conn, "SELECT MAX(called_at) as last FROM api_usage WHERE api_name='api_football'")
        c = q_one(conn, "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_football' AND called_at >= date('now')")
        if r and r["last"]:
            row("API-Football", r["last"], c["c"] if c else 0)
        else:
            out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "extra": ""})
    else:
        out.append({"name": "API-Football", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "extra": ""})

    # Narrative cache
    if table_exists(conn, "narrative_cache"):
        r = q_one(conn, "SELECT MAX(created_at) as last FROM narrative_cache")
        c = q_one(conn, "SELECT COUNT(*) as c FROM narrative_cache WHERE created_at >= datetime('now','-24 hours')")
        row("Narrative Cache", r["last"] if r else None, c["c"] if c else 0)
    else:
        out.append({"name": "Narrative Cache", "last_pull": "Not Connected", "records_24h": 0, "css": "s-black", "extra": ""})

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
    try:
        with open(QUOTAS_FILE) as f:
            data = json.load(f)
        return data.get("quotas", [])
    except Exception:
        return [
            {
                "api": "The Odds API",
                "plan": "Upgraded (20K/month)",
                "daily_limit": 670,
                "used_today": None,
                "remaining": None,
                "reset": "Midnight UTC",
                "link": "https://the-odds-api.com",
            },
            {
                "api": "API-Football",
                "plan": "Unknown",
                "daily_limit": None,
                "used_today": None,
                "remaining": None,
                "reset": "Midnight UTC",
                "link": "https://dashboard.api-football.com",
            },
        ]


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
            + td(dot(s["css"]) + s["last_pull"], s["css"])
            + td(s.get("records_24h", "—"))
            + td("—")
            + "</tr>"
        )

    # ── Panel 3: Scraper Health rows ─────────────────────────────────────────
    p3_rows = ""
    for s in scrapers:
        p3_rows += (
            "<tr>"
            + td(s["name"])
            + td(dot(s["css"]) + s["last_scrape"], s["css"])
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Work+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --bg:#0A0A0A;--surface:#111111;--border:#1e1e1e;
    --text:#F5F5F5;--muted:#6b7280;
    --acc1:#F8C830;--acc2:#E8571F;
    --green:#22c55e;--amber:#f59e0b;--red:#ef4444;
    --font-head:'Outfit',sans-serif;
    --font-body:'Work Sans',sans-serif;
    --font-mono:'Geist Mono','Fira Code','Consolas',monospace;
  }}
  html,body{{background:var(--bg);color:var(--text);font-family:var(--font-body);font-size:14px;line-height:1.6;min-height:100vh}}
  a{{color:var(--acc1);text-decoration:none}}
  a:hover{{text-decoration:underline}}

  /* Header */
  .header{{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
  .header-logo{{font-family:var(--font-head);font-weight:700;font-size:18px;background:linear-gradient(135deg,var(--acc1),var(--acc2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
  .header-meta{{font-size:11px;color:var(--muted);font-family:var(--font-mono)}}
  .header-meta span{{color:var(--text)}}

  /* Layout */
  .container{{max-width:1400px;margin:0 auto;padding:20px 16px}}
  .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
  .panel{{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}}
  .panel-full{{grid-column:1/-1}}

  /* Panel header */
  .panel-head{{padding:12px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}}
  .panel-title{{font-family:var(--font-head);font-weight:700;font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--text)}}
  .panel-sub{{font-size:11px;color:var(--muted)}}

  /* Tables */
  .tbl{{width:100%;border-collapse:collapse}}
  .tbl th{{font-family:var(--font-head);font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}}
  .tbl td{{padding:8px 12px;border-bottom:1px solid #161616;font-family:var(--font-mono);font-size:12px;vertical-align:middle;white-space:nowrap}}
  .tbl tr:last-child td{{border-bottom:none}}
  .tbl tr:hover td{{background:rgba(255,255,255,.03)}}

  /* Alerts panel */
  .alerts-scroll{{max-height:280px;overflow-y:auto;padding:8px 0}}
  .alert-row{{padding:8px 16px;border-bottom:1px solid #161616;display:flex;align-items:flex-start;gap:8px;font-size:12px}}
  .alert-row:last-child{{border-bottom:none}}
  .alert-row:hover{{background:rgba(255,255,255,.02)}}

  /* Status chip */
  .chip{{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;font-family:var(--font-mono)}}
  .chip-green{{background:rgba(34,197,94,.15);color:var(--green)}}
  .chip-amber{{background:rgba(245,158,11,.15);color:var(--amber)}}
  .chip-red{{background:rgba(239,68,68,.15);color:var(--red)}}
  .chip-black{{background:rgba(107,114,128,.15);color:var(--muted)}}

  /* DB status banner */
  .banner{{padding:8px 16px;font-size:12px;font-family:var(--font-mono);text-align:center}}
  .banner-ok{{background:rgba(34,197,94,.1);color:var(--green)}}
  .banner-err{{background:rgba(239,68,68,.1);color:var(--red)}}

  /* Chart wrapper */
  .chart-wrap{{padding:16px;height:180px;position:relative}}

  /* Alert count badge */
  .alert-badge{{background:var(--red);color:#fff;border-radius:999px;padding:1px 7px;font-size:10px;margin-left:6px}}

  /* Mobile */
  @media(max-width:768px){{
    .grid-2{{grid-template-columns:1fr}}
    .panel-full{{grid-column:1}}
    .tbl td,.tbl th{{padding:6px 8px;font-size:11px}}
    .header{{padding:12px 16px}}
  }}
</style>
</head>
<body>

<header class="header">
  <div class="header-logo">MzansiEdge — Data Health</div>
  <div class="header-meta">
    Updated: <span>{updated} SAST</span>
    &nbsp;·&nbsp; Auto-refreshes every 5 min
    &nbsp;·&nbsp; DB: <span style="color:{'var(--green)' if conn else 'var(--red)'}">{db_status}</span>
  </div>
</header>

{'<div class="banner banner-err">⚠ Main database unreachable — showing cached/empty data</div>' if conn is None else '<div class="banner banner-ok">✓ Database connected — scrapers/odds.db</div>'}

<div class="container">

  <!-- Panel 1: Coverage Matrix -->
  <div class="panel panel-full">
    <div class="panel-head">
      <span class="panel-title">Sport Coverage Matrix</span>
      <span class="panel-sub">Next 7 days · 🟢 w84 = AI-enriched · 🔴 w82 = Template · 🟡 baseline = No edge data</span>
    </div>
    <div style="overflow-x:auto">
      <table class="tbl">
        <thead>
          <tr>
            <th>Sport</th><th>League</th><th>Total Matches</th>
            <th>w84 (AI)</th><th>w82 (Template)</th><th>Baseline</th>
            <th>Coverage %</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {p1_rows}
        </tbody>
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
        <span class="panel-sub">Green &lt;1h · Amber 1–6h · Red &gt;6h</span>
      </div>
      <div style="overflow-x:auto">
        <table class="tbl">
          <thead>
            <tr><th>Source</th><th>Last Pull</th><th>Records (24h)</th><th>Records (7d)</th></tr>
          </thead>
          <tbody>{p2_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Panel 3: Scraper Health -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">Scraper Health</span>
        <span class="panel-sub">8 SA bookmakers · last 24h</span>
      </div>
      <div style="overflow-x:auto">
        <table class="tbl">
          <thead>
            <tr><th>Bookmaker</th><th>Last Scrape</th><th>Matches (24h)</th><th>Avg Odds/Match</th></tr>
          </thead>
          <tbody>{p3_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Panel 4: API Quotas -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">API Quota Tracker</span>
        <span class="panel-sub">Updated by cron · manual check if stale</span>
      </div>
      <div style="overflow-x:auto">
        <table class="tbl">
          <thead>
            <tr><th>API</th><th>Plan</th><th>Daily Limit</th><th>Used Today</th><th>Remaining</th><th>Reset</th></tr>
          </thead>
          <tbody>{p4_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Panel 5: Alert Log -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">
          Alert Log
          {'<span class="alert-badge">' + str(alert_count) + '</span>' if alert_count else ''}
        </span>
        <span class="panel-sub">Last 48h · scrapers · coverage · pipeline</span>
      </div>
      <div class="alerts-scroll">
        {p5_rows}
      </div>
    </div>

  </div><!-- /grid-2 -->

</div><!-- /container -->

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
        {{ label: 'w84 (AI-enriched)', data: w84Data, backgroundColor: 'rgba(34,197,94,0.85)', borderRadius: 3 }},
        {{ label: 'w82 (Template)', data: w82Data, backgroundColor: 'rgba(239,68,68,0.70)', borderRadius: 3 }},
        {{ label: 'Baseline', data: baseData, backgroundColor: 'rgba(245,158,11,0.55)', borderRadius: 3 }},
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ labels: {{ color: '#F5F5F5', font: {{ size: 11 }} }} }},
        tooltip: {{ backgroundColor: '#111', titleColor: '#F5F5F5', bodyColor: '#9ca3af' }}
      }},
      scales: {{
        x: {{ stacked: true, ticks: {{ color: '#6b7280', font: {{ size: 10 }} }}, grid: {{ color: '#1e1e1e' }} }},
        y: {{ stacked: true, ticks: {{ color: '#6b7280', font: {{ size: 10 }}, stepSize: 1 }}, grid: {{ color: '#1e1e1e' }} }}
      }}
    }}
  }});
}})();

// Countdown to next refresh
(function() {{
  var secs = 300;
  setInterval(function() {{
    secs--;
    if (secs <= 0) location.reload();
  }}, 1000);
}})();
</script>
</body>
</html>"""


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/ops/health")
@require_auth
def health():
    conn = db_connect(SCRAPERS_DB)
    db_status = "Connected" if conn else "Unreachable"
    try:
        html = render_page(conn, db_status)
    finally:
        if conn:
            conn.close()
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
