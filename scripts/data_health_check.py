#!/usr/bin/env python3
"""
MzansiEdge — Data Pipeline Health Check
Runs every 6 hours via cron. Logs every run.
Sends Telegram to EdgeOps ONLY when health is degraded (🟡/🔴).
Silence = healthy.

Standing Order #20: NEVER send to @MzansiEdgeAlerts. EdgeOps only.
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
SAST = ZoneInfo("Africa/Johannesburg")
UTC = ZoneInfo("UTC")
from typing import Optional

import requests
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BOT_TOKEN       = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
EDGEOPS_CHAT_ID = "-1003877525865"   # Standing Order #20: EdgeOps only. See CLAUDE.md.

SCRAPERS_DB = os.path.expanduser("~/scrapers/odds.db")
BOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUOTAS_FILE = os.path.join(BOT_DIR, "dashboard", "api_quotas.json")
LOG_DIR     = os.path.join(BOT_DIR, "logs")
LOG_FILE    = os.path.join(LOG_DIR, "data_health.log")

BOOKMAKERS = [
    "hollywoodbets", "supabets", "betway", "sportingbet",
    "gbets", "wsb", "playabets", "supersportbet",
]
BK_DISPLAY = {
    "hollywoodbets": "HWB", "supabets": "Supabets", "betway": "Betway",
    "sportingbet": "Sportingbet", "gbets": "GBets", "wsb": "WSB",
    "playabets": "Playabets", "supersportbet": "SuperSportBet",
}

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── DB helpers ────────────────────────────────────────────────────────────────

def db_open() -> Optional[sqlite3.Connection]:
    try:
        conn = sqlite3.connect(f"file:{SCRAPERS_DB}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        log.warning(f"DB open failed: {e}")
        return None


def q_all(conn, sql: str, params=()):
    if conn is None:
        return []
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as e:
        log.warning(f"Query failed ({e}): {sql[:80]}")
        return []


def q_one(conn, sql: str, params=()):
    if conn is None:
        return None
    try:
        return conn.execute(sql, params).fetchone()
    except Exception as e:
        log.warning(f"Query failed ({e}): {sql[:80]}")
        return None


def table_exists(conn, name: str) -> bool:
    r = q_one(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return r is not None


# ── Freshness helpers ─────────────────────────────────────────────────────────

def age_hours(ts_str: Optional[str]) -> Optional[float]:
    """Return hours since timestamp, or None if unparseable."""
    if not ts_str:
        return None
    try:
        s = ts_str.strip().replace("Z", "+00:00")
        if "T" in s and "+" not in s[10:] and "-" not in s[11:]:
            s += "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (datetime.now(SAST) - dt).total_seconds() / 3600
    except Exception:
        return None


def bk_freshness_status(h: Optional[float]) -> str:
    """Bookmaker / ESPN freshness: 🟢 <2h, 🟡 2-6h, 🔴 >6h, ⚫ never."""
    if h is None:
        return "⚫"
    if h < 2:
        return "🟢"
    elif h < 6:
        return "🟡"
    else:
        return "🔴"


def coverage_status(pct: float, has_matches: bool) -> str:
    if not has_matches:
        return "⚫"
    if pct >= 90:
        return "🟢"
    elif pct >= 50:
        return "🟡"
    else:
        return "🔴"


# ── Health checks ─────────────────────────────────────────────────────────────

def check_sport_coverage(conn) -> list[dict]:
    """Per sport/league w84 coverage for next 7 days."""
    if not table_exists(conn, "odds_snapshots"):
        return [{"sport": "all", "league": "ALL", "status": "⚫", "detail": "Table missing"}]

    rows = q_all(conn, """
        SELECT u.sport, u.league,
            COUNT(DISTINCT u.match_id)                                            AS total,
            COUNT(CASE WHEN nc.narrative_source = 'w84' THEN 1 END)              AS w84,
            COUNT(CASE WHEN nc.narrative_source = 'w82' THEN 1 END)              AS w82,
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

    results = []
    for r in rows:
        total = r["total"] or 0
        w84   = r["w84"]   or 0
        pct   = (w84 / total * 100) if total > 0 else 0
        sport_label = f"{r['sport'].capitalize()}/{r['league'].upper().replace('_', ' ')}"
        status = coverage_status(pct, total > 0)
        results.append({
            "sport":  r["sport"],
            "league": r["league"],
            "label":  sport_label,
            "total":  total,
            "w84":    w84,
            "pct":    round(pct, 1),
            "status": status,
            "detail": f"{pct:.0f}% w84 ({w84}/{total} matches)",
        })
    return results


def check_scraper_freshness(conn) -> list[dict]:
    """Per-bookmaker freshness from odds_snapshots."""
    if not table_exists(conn, "odds_snapshots"):
        return [{"name": bk, "status": "⚫", "detail": "Table missing"} for bk in BOOKMAKERS]

    rows = q_all(conn, """
        SELECT bookmaker, MAX(scraped_at) AS last
        FROM   odds_snapshots
        GROUP  BY bookmaker
    """)
    last_by_bk = {r["bookmaker"]: r["last"] for r in rows}

    results = []
    for bk in BOOKMAKERS:
        last = last_by_bk.get(bk)
        h    = age_hours(last)
        status = bk_freshness_status(h)
        detail = f"{h:.1f}h ago" if h is not None else "never"
        results.append({
            "bk":     bk,
            "name":   BK_DISPLAY[bk],
            "status": status,
            "detail": detail,
            "age_h":  h,
        })
    return results


def check_espn_freshness(conn) -> dict:
    """ESPN data freshness."""
    if not table_exists(conn, "espn_stats_cache"):
        return {"status": "⚫", "detail": "Table missing"}
    r = q_one(conn, "SELECT MAX(fetched_at) AS last FROM espn_stats_cache")
    last = r["last"] if r else None
    h    = age_hours(last)
    status = bk_freshness_status(h)
    detail = f"{h:.1f}h ago" if h is not None else "never"
    return {"status": status, "detail": detail, "age_h": h}


def check_api_football(conn) -> dict:
    """API-Football: connected if called in last 24h."""
    if not table_exists(conn, "api_usage"):
        return {"status": "⚫", "detail": "Not connected", "calls_today": 0}
    r = q_one(conn, """
        SELECT COUNT(*) AS calls, MAX(called_at) AS last
        FROM   api_usage
        WHERE  api_name = 'api_football'
        AND    called_at >= date('now')
    """)
    calls = (r["calls"] or 0) if r else 0
    last  = r["last"] if r else None
    if calls > 0:
        h = age_hours(last)
        status = "🟢"
        detail = f"{calls} calls today, last {h:.1f}h ago" if h is not None else f"{calls} calls today"
    else:
        # Check if ever called
        ever = q_one(conn, "SELECT MAX(called_at) AS last FROM api_usage WHERE api_name='api_football'")
        if ever and ever["last"]:
            status = "🟡"
            detail = "No calls today (last: " + (ever["last"] or "")[:10] + ")"
        else:
            status = "⚫"
            detail = "Never called"
    return {"status": status, "detail": detail, "calls_today": calls}


def check_narrative_staleness(conn) -> dict:
    """Matches in next 24h that have a narrative entry but it's not w84."""
    if not table_exists(conn, "narrative_cache") or not table_exists(conn, "odds_snapshots"):
        return {"status": "⚫", "detail": "Table missing", "stale_count": 0}

    r = q_one(conn, """
        SELECT COUNT(DISTINCT u.match_id) AS stale
        FROM (
            SELECT DISTINCT match_id FROM odds_snapshots
            WHERE substr(match_id, -10) BETWEEN date('now') AND date('now', '+1 day')
        ) u
        INNER JOIN narrative_cache nc ON nc.match_id = u.match_id
        WHERE nc.narrative_source != 'w84'
    """)
    stale = (r["stale"] or 0) if r else 0
    if stale == 0:
        return {"status": "🟢", "detail": "All 24h narratives are w84 (or none cached)", "stale_count": 0}
    elif stale <= 3:
        return {"status": "🟡", "detail": f"{stale} match(es) in 24h with non-w84 narrative", "stale_count": stale}
    else:
        return {"status": "🔴", "detail": f"{stale} matches in 24h with non-w84 narrative", "stale_count": stale}


# ── Quota updater ─────────────────────────────────────────────────────────────

def update_api_quotas(conn) -> None:
    """Write current API usage to dashboard/api_quotas.json."""
    calls_today = 0
    if conn and table_exists(conn, "api_usage"):
        r = q_one(conn, """
            SELECT COUNT(*) AS c FROM api_usage
            WHERE api_name='api_football' AND called_at >= date('now')
        """)
        calls_today = (r["c"] or 0) if r else 0

    quotas = {
        "_comment": "Updated by scripts/data_health_check.py every 6h",
        "_updated": datetime.now(SAST).isoformat(),
        "quotas": [
            {
                "api": "The Odds API",
                "plan": "Upgraded (20K/month)",
                "daily_limit": 670,
                "used_today": None,
                "remaining": None,
                "reset": "Midnight UTC",
                "link": "https://the-odds-api.com",
                "_note": "Usage tracked via response headers (not in DB). Check provider dashboard.",
            },
            {
                "api": "API-Football",
                "plan": "Check dashboard",
                "daily_limit": None,
                "used_today": calls_today if calls_today > 0 else None,
                "remaining": None,
                "reset": "Midnight UTC",
                "link": "https://dashboard.api-football.com",
            },
        ],
    }

    try:
        os.makedirs(os.path.dirname(QUOTAS_FILE), exist_ok=True)
        with open(QUOTAS_FILE, "w") as f:
            json.dump(quotas, f, indent=2)
        log.info(f"Updated api_quotas.json (api_football calls today: {calls_today})")
    except Exception as e:
        log.warning(f"Failed to write api_quotas.json: {e}")


# ── Gate matrix health check ──────────────────────────────────────────────────

# Canonical GATE_MATRIX (TIER-GATE-IMPL-01) — authoritative truth
_GATE_MATRIX = [
    ("bronze",  "bronze",  "full"),
    ("bronze",  "silver",  "partial"),
    ("bronze",  "gold",    "blurred"),
    ("bronze",  "diamond", "locked"),
    ("gold",    "bronze",  "full"),
    ("gold",    "silver",  "full"),
    ("gold",    "gold",    "full"),
    ("gold",    "diamond", "locked"),
    ("diamond", "bronze",  "full"),
    ("diamond", "silver",  "full"),
    ("diamond", "gold",    "full"),
    ("diamond", "diamond", "full"),
]


def check_gate_matrix() -> dict:
    """Verify all 12 gate matrix cells return expected access levels.

    Returns dict with 'status' (🟢/🔴), 'failures' list, 'checked' count.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tier_gate import get_edge_access_level
    except ImportError as e:
        return {"status": "🔴", "failures": [f"Import error: {e}"], "checked": 0}

    failures = []
    for user_tier, edge_tier, expected in _GATE_MATRIX:
        actual = get_edge_access_level(user_tier, edge_tier)
        if actual != expected:
            failures.append(f"{user_tier}→{edge_tier}: expected={expected}, got={actual}")

    return {
        "status": "🟢" if not failures else "🔴",
        "failures": failures,
        "checked": len(_GATE_MATRIX),
    }


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_alert(message: str) -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set — cannot send Telegram alert")
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": EDGEOPS_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.ok:
            log.info("Telegram alert sent to EdgeOps")
        else:
            log.warning(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Telegram send error: {e}")


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(coverage, scrapers, espn, api_foot, staleness, gate=None) -> tuple[str, str, list[str]]:
    """
    Returns (overall_status, telegram_message, log_lines).
    overall_status: '🟢', '🟡', or '🔴'
    """
    log_lines = []
    issues_red  = []
    issues_amber = []

    # ── Sport coverage ────────────────────────────────────────────────────────
    cov_lines = []
    for c in coverage:
        s = c["status"]
        cov_lines.append(f"{s} {c['label']}: {c['detail']}")
        log_lines.append(f"  coverage {s} {c['label']}: {c['detail']}")
        if s == "🔴":
            issues_red.append(f"{c['label']} {c['detail']}")
        elif s == "🟡":
            issues_amber.append(f"{c['label']} {c['detail']}")

    # ── Scraper freshness ─────────────────────────────────────────────────────
    healthy = sum(1 for s in scrapers if s["status"] == "🟢")
    total   = len(scrapers)
    degraded = [s for s in scrapers if s["status"] in ("🟡", "🔴", "⚫")]

    bk_summary = f"🟢 {healthy}/{total} healthy" if not degraded else ""
    bk_detail_lines = []
    for s in scrapers:
        log_lines.append(f"  scraper {s['status']} {s['name']}: {s['detail']}")
        if s["status"] != "🟢":
            bk_detail_lines.append(f"{s['status']} {s['name']}: last pull {s['detail']}")
            if s["status"] == "🔴" or s["status"] == "⚫":
                issues_red.append(f"Scraper {s['name']} {s['detail']}")
            else:
                issues_amber.append(f"Scraper {s['name']} {s['detail']}")

    scraper_section = bk_summary if not bk_detail_lines else "\n".join(
        ([f"🟢 {healthy}/{total} healthy"] if healthy < total else []) + bk_detail_lines
    )

    # ── ESPN ──────────────────────────────────────────────────────────────────
    log_lines.append(f"  espn {espn['status']}: {espn['detail']}")
    if espn["status"] == "🔴":
        issues_red.append(f"ESPN {espn['detail']}")
    elif espn["status"] == "🟡":
        issues_amber.append(f"ESPN {espn['detail']}")

    # ── API-Football ──────────────────────────────────────────────────────────
    log_lines.append(f"  api_football {api_foot['status']}: {api_foot['detail']}")
    if api_foot["status"] == "🔴":
        issues_red.append(f"API-Football {api_foot['detail']}")

    # ── Staleness ─────────────────────────────────────────────────────────────
    log_lines.append(f"  narrative_staleness {staleness['status']}: {staleness['detail']}")
    if staleness["status"] == "🔴":
        issues_red.append(f"Narrative staleness: {staleness['detail']}")
    elif staleness["status"] == "🟡":
        issues_amber.append(f"Narrative staleness: {staleness['detail']}")

    # ── Gate matrix ───────────────────────────────────────────────────────────
    gate_line = ""
    if gate is not None:
        log_lines.append(f"  gate_matrix {gate['status']}: {gate['checked']} cells checked, {len(gate['failures'])} failures")
        if gate["status"] == "🔴":
            fail_detail = "; ".join(gate["failures"][:3])
            issues_red.append(f"GATE MATRIX BROKEN: {fail_detail}")
            gate_line = f"\n🔒 Gate Matrix: {gate['status']} {len(gate['failures'])} FAILURES\n" + "\n".join(f"  {f}" for f in gate["failures"])
        else:
            gate_line = f"\n🔒 Gate Matrix: {gate['status']} {gate['checked']}/12 cells OK"

    # ── Overall ───────────────────────────────────────────────────────────────
    if issues_red:
        overall = "🔴"
    elif issues_amber:
        overall = "🟡"
    else:
        overall = "🟢"

    # ── Action line ───────────────────────────────────────────────────────────
    worst = (issues_red + issues_amber)
    action_line = worst[0] if worst else "All systems healthy"

    # ── Telegram message ──────────────────────────────────────────────────────
    now_sast = datetime.now().strftime("%Y-%m-%d %H:%M SAST")
    cov_block = "\n".join(cov_lines) if cov_lines else "⚫ No upcoming matches"

    msg = (
        f"⚠️ DATA HEALTH CHECK — {now_sast}\n"
        f"\n"
        f"Sport Coverage:\n{cov_block}\n"
        f"\n"
        f"Scrapers:\n{scraper_section}\n"
        f"\n"
        f"ESPN: {espn['status']} {espn['detail']}\n"
        f"API-Football: {api_foot['status']} {api_foot['detail']}\n"
        f"{gate_line}\n"
        f"\n"
        f"Action needed: {action_line}"
    )

    return overall, msg, log_lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    start = datetime.now()
    log.info("=== DATA HEALTH CHECK START ===")

    conn = db_open()
    if conn is None:
        log.warning("DB unavailable — skipping checks, not alerting (transient)")
        log.info("=== DATA HEALTH CHECK END (DB UNAVAILABLE) ===")
        return

    try:
        coverage  = check_sport_coverage(conn)
        scrapers  = check_scraper_freshness(conn)
        espn      = check_espn_freshness(conn)
        api_foot  = check_api_football(conn)
        staleness = check_narrative_staleness(conn)
        gate      = check_gate_matrix()

        overall, telegram_msg, log_lines = build_report(
            coverage, scrapers, espn, api_foot, staleness, gate=gate
        )

        for line in log_lines:
            log.info(line)

        # Always update quotas file
        update_api_quotas(conn)

        elapsed = (datetime.now() - start).total_seconds()
        log.info(f"Overall health: {overall} | Elapsed: {elapsed:.1f}s")

        if overall in ("🟡", "🔴"):
            log.info("Health degraded — sending Telegram alert to EdgeOps")
            send_alert(telegram_msg)
        else:
            log.info("Health is 🟢 — no alert sent (silence = healthy)")

    finally:
        conn.close()

    log.info("=== DATA HEALTH CHECK END ===")


if __name__ == "__main__":
    main()
