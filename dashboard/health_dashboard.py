#!/usr/bin/env python3
"""
MzansiEdge --- Admin Panel
Served at /admin/health (default) on port 8501.
Read-only access to SQLite. Never writes to any DB.
Sidebar navigation with Data Health, Automation, and Customers views.
"""

import functools
import hashlib
import logging
import secrets
import html
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

# ── Cadence: scheduled slot constants (single source of truth: publisher/cadence.py) ──
_DASH_REEL_SLOT_FALLBACK = "20:30"
_DASH_TG_SLOT_FALLBACK   = "20:00"
_DASH_WA_SLOT_FALLBACK   = "20:00"
try:
    import sys as _sys
    _publisher_root = str(Path(__file__).resolve().parents[2])  # /home/paulsportsza
    if _publisher_root not in _sys.path:
        _sys.path.insert(0, _publisher_root)
    from publisher.cadence import (
        IG_REEL_SLOT       as _DASH_IG_REEL_SLOT,
        TG_COMMUNITY_SLOT  as _DASH_TG_COMMUNITY_SLOT,
        WA_CHANNEL_SLOT    as _DASH_WA_CHANNEL_SLOT,
    )
except Exception:
    _DASH_IG_REEL_SLOT        = _DASH_REEL_SLOT_FALLBACK
    _DASH_TG_COMMUNITY_SLOT   = _DASH_TG_SLOT_FALLBACK
    _DASH_WA_CHANNEL_SLOT     = _DASH_WA_SLOT_FALLBACK


def _cadence_slots_script() -> str:
    """Inject cadence slot constants as window.CADENCE_SLOTS for JS template use."""
    slots = {
        "ig_reel":      _DASH_IG_REEL_SLOT,
        "tg_community": _DASH_TG_COMMUNITY_SLOT,
        "wa_channel":   _DASH_WA_CHANNEL_SLOT,
    }
    return f'<script>window.CADENCE_SLOTS={json.dumps(slots)};</script>'


def _slot_mins(slot: str) -> int:
    """Convert 'HH:MM' slot string to minutes since midnight."""
    hh, mm = slot.split(":")
    return int(hh) * 60 + int(mm)

_IG_REEL_MINS = _slot_mins(_DASH_IG_REEL_SLOT)
_IG_REEL_SAST = f"{_DASH_IG_REEL_SLOT} SAST"

from flask import Flask, Response, request, redirect, send_from_directory, abort

try:
    import sentry_sdk as _sentry
except ImportError:
    _sentry = None  # type: ignore[assignment]

# -- Response cache (avoids heavy queries on every request) -------------------
_page_cache: dict[str, tuple[str, float]] = {}
_page_cache_lock = threading.Lock()
_PAGE_CACHE_TTL = 60  # seconds
# stale-while-revalidate window: serve cache up to this age while a background
# thread refreshes. Keeps the p99 user-facing response snappy after the first
# hit even when Notion is slow.
_PAGE_CACHE_SWR = 600  # seconds
_page_refresh_inflight: set[str] = set()

# -- Cache key constants (single source of truth) ----------------------------
_CK_SOCIAL_OPS    = "social_ops_full"
_CK_TASK_HUB      = "task_hub_full"
_CK_TASK_HUB_CONT = "task_hub_content"
_CK_HEALTH        = "health_full"
_CK_HEALTH_CONT   = "health_content"
_CK_AUTO_CONT     = "automation_content"
_CK_SO_CONT       = "social_ops_content"
_CK_REEL_KIT      = "reel_kit_full"
_CK_REEL_KIT_CONT = "reel_kit_content"
_CK_CALENDAR      = "calendar_full"
_CK_CAL_CONT      = "calendar_content"

# -- Request timing log -------------------------------------------------------
_TIMING_LOG = Path("/home/paulsportsza/logs/dashboard_timing.log")

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

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_MARKETING_DB = "58123052-0e48-466a-be63-5308e793e672"
NOTION_TASK_HUB_PAGE = "31ed9048-d73c-814e-a179-ccd2cf35df1d"
# BUILD-REEL-KIT-DATE-RULE-01 (Piece B): set True when BUILD-SOCIAL-OPS-URGENT-PILLS-01 lands
SHOW_REEL_KIT_ON_TIMELINE = True
# Task Hub data sources (17 Apr 2026 — rewired to real DSs, old IDs were empty scaffold pages)
# LinkedIn has no separate ledger DB — reads from MOQ Channel=LinkedIn
NOTION_LINKEDIN_DB = os.getenv(
    "NOTION_LINKEDIN_DB", "320d9048-d73c-818d-8c7e-c4d06d1e3461"
)  # DEPRECATED — kept for env compat; fetch function now uses MOQ
NOTION_QUORA_DB = os.getenv(
    "NOTION_QUORA_DB", "dcb0e810-c714-4b92-b3b5-fad18c4a2452"
)  # 🌐 GEO Quora Pipeline
NOTION_FB_GROUPS_LEDGER = os.getenv(
    "NOTION_FB_GROUPS_LEDGER", "693414a9-5154-45d6-a548-70e84409d439"
)  # 📋 FB Groups Posting Ledger (group registry)
_NOTION_LEDGER_CACHE_TTL = 300  # seconds (LinkedIn / Quora ledgers)

# -- Reel Kit constants -------------------------------------------------------
_REEL_CARDS_ROOT = "/var/www/mzansiedge/assets/reel-cards"
_REEL_MASTERS_ROOT = "/var/www/mzansiedge/assets/reels"
_REEL_FINALS_ROOT = "/home/paulsportsza/bot/assets/reels"
_REEL_PUBLIC_BASE = "https://mzansiedge.co.za/assets/reels"

# -- Social Ops asset roots ---------------------------------------------------
# MOQ "Image URL" / "Video URL" columns frequently store Claude-session-scoped
# URLs (computer:///sessions/<id>/mnt/MzansiEdge/assets/<subdir>/<file>) that
# are not browser-loadable. _resolve_media_url() maps the trailing
# "<subdir>/<file>" portion onto one of _SO_ASSET_ROOTS and returns a
# dashboard-served path. See /admin/social-ops/asset/<subpath> route.
_SO_ASSET_ROOTS = (
    "/home/paulsportsza/assets",
    "/home/paulsportsza/MzansiEdge/assets",
    "/home/paulsportsza/bot/assets",
)
_REEL_MARKETING_DATA_SOURCE = NOTION_MARKETING_DB
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB upload limit (LOCKED)
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_PICK_ID = re.compile(r"^[A-Za-z0-9_-]+$")

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

# -- Timezones ----------------------------------------------------------------
_SAST = ZoneInfo("Africa/Johannesburg")
_UTC = ZoneInfo("UTC")

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
    {"key": "telegram_alerts", "label": "Telegram Alerts", "color": "#26A5E4", "emoji": "\u2708\ufe0f"},
    {"key": "telegram_community", "label": "Telegram Community", "color": "#179CDE", "emoji": "\U0001f465"},
    {"key": "whatsapp_channel", "label": "WhatsApp Channel", "color": "#25D366", "emoji": "\U0001f4ac"},
    {"key": "instagram", "label": "Instagram", "color": "#E4405F", "emoji": "\U0001f4f8"},
    {"key": "tiktok", "label": "TikTok", "color": "#ff0050", "emoji": "\U0001f3b5"},
]
_MANUAL_CHANNELS = []
_CHANNEL_MAP = {c["key"]: c for c in _CHANNELS + _MANUAL_CHANNELS}
_CHANNEL_SVG = {
    "telegram_alerts":    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M21.2 3.1L1.9 10.5c-1.3.5-1.3 1.3-.2 1.6l4.9 1.5 1.9 5.9c.2.7.4.8.9.3l2.8-2.7 5.5 4c1 .6 1.7.3 2-.9l3.5-16.5c.4-1.4-.5-2-.9-.4z" fill="#26A5E4"/></svg>',
    "telegram_community": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M21.2 3.1L1.9 10.5c-1.3.5-1.3 1.3-.2 1.6l4.9 1.5 1.9 5.9c.2.7.4.8.9.3l2.8-2.7 5.5 4c1 .6 1.7.3 2-.9l3.5-16.5c.4-1.4-.5-2-.9-.4z" fill="#179CDE"/></svg>',
    "whatsapp_channel":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M17.5 14.4c-.3-.1-1.6-.8-1.9-.9-.3-.1-.5-.1-.7.1-.2.3-.8 1-1 1.2-.2.2-.3.2-.6.1-.3-.2-1.3-.5-2.4-1.5-.9-.8-1.5-1.8-1.7-2.1-.2-.3 0-.5.1-.6.1-.1.3-.4.4-.5.2-.2.2-.3.3-.5.1-.2 0-.4 0-.5 0-.2-.7-1.6-.9-2.2-.3-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 1-1 2.4s1 2.8 1.2 3c.1.2 2 3.1 4.9 4.3.7.3 1.2.5 1.6.6.7.2 1.3.2 1.8.1.5-.1 1.6-.7 1.9-1.3.2-.6.2-1.2.2-1.3 0-.1-.2-.2-.5-.3zM12 21.8c-1.8 0-3.5-.5-5-1.3l-.4-.2-3.5.9.9-3.4-.2-.4c-1-1.6-1.5-3.4-1.5-5.3 0-5.4 4.4-9.8 9.8-9.8 2.6 0 5.1 1 6.9 2.9 1.8 1.8 2.9 4.3 2.9 6.9-.1 5.4-4.5 9.7-9.9 9.7zm8.3-18.1C18.2 1.6 15.2 0 12 0 5.4 0 0 5.4 0 12c0 2.1.6 4.2 1.6 6L0 24l6.2-1.6c1.7.9 3.7 1.4 5.8 1.4 6.6 0 12-5.4 12-12 0-3.2-1.2-6.2-3.5-8.5l-.2.4z" fill="#25D366"/></svg>',
    "instagram":          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><rect x="2" y="2" width="20" height="20" rx="5" stroke="#E4405F" stroke-width="2" fill="none"/><circle cx="12" cy="12" r="5" stroke="#E4405F" stroke-width="2" fill="none"/><circle cx="17.5" cy="6.5" r="1.5" fill="#E4405F"/></svg>',
    "tiktok":             '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M16.6 5.8A4.3 4.3 0 0112.3 2H9.2v13.4a2.6 2.6 0 11-1.8-2.5V9.7a5.8 5.8 0 104.9 5.7V9.8c1.2.8 2.6 1.2 4.1 1.2V7.8c-.7 0-1.3-.1-1.8-.4V5.8z" fill="#ff0050"/><path d="M16.6 5.8A4.3 4.3 0 0112.3 2" stroke="#00f2ea" stroke-width="1" fill="none"/></svg>',
    "threads":            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M16.3 11.3c-.1 0-.2 0-.3-.1-.2-.8-.7-1.5-1.4-1.9-.7-.4-1.6-.5-2.5-.2-.7.2-1.2.7-1.5 1.3-.3.6-.3 1.3-.1 1.9.2.7.7 1.2 1.3 1.5.7.3 1.4.3 2 .1.5-.1.9-.4 1.2-.8l.1-.1c.2.8.1 1.7-.3 2.4-.5.9-1.4 1.5-2.4 1.5-1.2 0-2.2-.5-2.8-1.5-.5-.8-.8-1.9-.8-3.4 0-1.5.3-2.6.8-3.4.7-1 1.7-1.5 2.8-1.5 1.3 0 2.3.6 2.8 1.7.3.5.4 1.1.5 1.7l.1.1c.5.2.9.5 1.2.9.1-1-.1-2-.5-2.9-.8-1.7-2.3-2.7-4.2-2.7-1.7 0-3 .8-3.8 2.1-.6 1-.9 2.4-.9 4.1s.3 3.1.9 4.1c.8 1.3 2.1 2.1 3.8 2.1 1.5 0 2.7-.6 3.5-1.8.6-1 .9-2.2.8-3.5 0-.1-.1-.3-.3-.4z" fill="#f5f5f5"/><path d="M12 2.5c-5.2 0-9.5 4.3-9.5 9.5s4.3 9.5 9.5 9.5 9.5-4.3 9.5-9.5S17.2 2.5 12 2.5z" stroke="#f5f5f5" stroke-width="1.5" fill="none"/></svg>',
    "linkedin":           '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M20.4 2H3.6C2.7 2 2 2.7 2 3.6v16.8c0 .9.7 1.6 1.6 1.6h16.8c.9 0 1.6-.7 1.6-1.6V3.6c0-.9-.7-1.6-1.6-1.6zM8.3 18.3H5.7V9.7h2.6v8.6zM7 8.6a1.5 1.5 0 110-3 1.5 1.5 0 010 3zm11.4 9.7h-2.6v-4.2c0-1 0-2.3-1.4-2.3s-1.6 1.1-1.6 2.2v4.3h-2.6V9.7h2.5v1.2a2.7 2.7 0 012.5-1.4c2.7 0 3.2 1.8 3.2 4v4.8z" fill="#0A66C2"/></svg>',
    "fb_groups":          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M24 12c0-6.6-5.4-12-12-12S0 5.4 0 12c0 6 4.4 11 10.1 11.9v-8.4H7.1V12h3V9.4c0-3 1.8-4.6 4.5-4.6 1.3 0 2.7.2 2.7.2v2.9h-1.5c-1.5 0-2 .9-2 1.9V12h3.3l-.5 3.5h-2.8v8.4C19.6 23 24 18 24 12z" fill="#1877F2"/></svg>',
    "quora":              '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M11.3 21.8c-.5-1-1.1-2.1-2.3-3.2l.8-1.1c.8.5 1.4 1.2 1.9 2 1.6-1 2.6-2.8 2.6-4.9 0-3.3-2.3-5.9-5.5-5.9S3.3 11.3 3.3 14.6s2.3 5.9 5.5 5.9c.8 0 1.7-.2 2.5-.7zm-2.5-12c2.3 0 3.8 1.8 3.8 4.2s-1.5 4.2-3.8 4.2-3.8-1.8-3.8-4.2 1.5-4.2 3.8-4.2z" fill="#B92B27"/><text x="14" y="10" font-size="10" font-weight="700" fill="#B92B27" font-family="Georgia,serif">Q</text></svg>',
}

app = Flask(__name__)


# -- Auth ---------------------------------------------------------------------

# -- Auth session cookie (fixes Chrome credential-URL fetch() block) ----------
_AUTH_COOKIE_NAME = "me_auth"
_AUTH_COOKIE_SECRET = os.getenv("DASHBOARD_COOKIE_SECRET", secrets.token_hex(32))

def _make_auth_token():
    msg = f"{DASHBOARD_USER}:{DASHBOARD_PASS}".encode()
    return hashlib.sha256(msg + _AUTH_COOKIE_SECRET.encode()).hexdigest()[:40]

def _valid_auth_cookie():
    cookie_val = request.cookies.get(_AUTH_COOKIE_NAME, "")
    return cookie_val == _make_auth_token()


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # Accept valid session cookie (for AJAX calls blocked by Chrome)
        if _valid_auth_cookie():
            return f(*args, **kwargs)
        # Fall back to Basic Auth
        auth = request.authorization
        if not auth or auth.username != DASHBOARD_USER or auth.password != DASHBOARD_PASS:
            return Response(
                "Unauthorized -- MzansiEdge Ops Dashboard",
                401,
                {"WWW-Authenticate": 'Basic realm="MzansiEdge Ops"'},
            )
        # Basic Auth succeeded -- set session cookie for subsequent AJAX calls
        resp = f(*args, **kwargs)
        if isinstance(resp, str):
            resp = Response(resp, mimetype="text/html")
        elif not isinstance(resp, Response):
            resp = Response(resp)
        resp.set_cookie(_AUTH_COOKIE_NAME, _make_auth_token(),
                        httponly=True, samesite="Lax", max_age=86400,
                        path="/admin/")
        return resp
    return wrapper


# -- Request timing middleware ------------------------------------------------

_timing_log_lock = threading.Lock()

@app.before_request
def _req_start():
    request._t0 = time.monotonic()
    request._cache_state = "miss"

@app.after_request
def _req_end(response):
    try:
        elapsed_ms = int((time.monotonic() - request._t0) * 1000)
        state = getattr(request, "_cache_state", "miss")
        ts = datetime.now(_SAST).isoformat()
        line = f"{ts} route={request.path} ms={elapsed_ms} cache={state}\n"
        with _timing_log_lock:
            with open(_TIMING_LOG, "a") as _tf:
                _tf.write(line)
    except Exception:
        pass
    return response


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


def _fetch_alerts_send_log(conn, limit: int = 10) -> list[dict]:
    """Fetch recent Alerts bot sends from alerts_send_log (AC-A event-driven feed)."""
    if not table_exists(conn, "alerts_send_log"):
        return []
    rows = q_all(
        conn,
        "SELECT edge_id, match_key, tier, image_bytes_size, msg_url, sent_at"
        " FROM alerts_send_log ORDER BY sent_at DESC LIMIT ?",
        (limit,),
    )
    return [
        {
            "edge_id": r["edge_id"] or "",
            "match_key": r["match_key"] or "",
            "tier": r["tier"] or "gold",
            "image_bytes_size": int(r["image_bytes_size"] or 0),
            "msg_url": r["msg_url"] or "",
            "sent_at": float(r["sent_at"] or 0),
        }
        for r in rows
    ]


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
            dt = dt.replace(tzinfo=_UTC)
        return dt
    except Exception:
        return None


def freshness(ts_str: str | None) -> tuple[str, str]:
    """Return (css_class, human_label) for a timestamp."""
    dt = parse_ts(ts_str)
    if dt is None:
        return "s-grey", "Never"
    age_h = (datetime.now(_SAST) - dt).total_seconds() / 3600
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
    age_m = (datetime.now(_SAST) - dt).total_seconds() / 60
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
    delta = datetime.now(_SAST) - dt
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


def _render_sast(dt) -> str:
    """Format an aware datetime as 'D Mon HH:MM' in SAST."""
    s = dt.astimezone(_SAST)
    return s.strftime("%-d %b %H:%M")


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


    # SuperSport.com (KO times + DStv channels via broadcast_schedule)
    if table_exists(conn, "broadcast_schedule"):
        r = q_one(conn, "SELECT MAX(scraped_at) as last FROM broadcast_schedule WHERE source='supersport_scraper'")
        c = q_one(conn, "SELECT COUNT(*) as c FROM broadcast_schedule WHERE source='supersport_scraper' AND scraped_at >= datetime('now','-24 hours')")
        c7 = q_one(conn, "SELECT COUNT(*) as c FROM broadcast_schedule WHERE source='supersport_scraper' AND scraped_at >= datetime('now','-7 days')")
        c14 = q_one(conn, "SELECT COUNT(*) as c FROM broadcast_schedule WHERE source='supersport_scraper' AND scraped_at >= datetime('now','-14 days') AND scraped_at < datetime('now','-7 days')")
        trend = _trend_indicator(c7["c"] if c7 else 0, c14["c"] if c14 else 0)
        if r and r["last"]:
            row("SuperSport Fixtures", r["last"], c["c"] if c else 0, trend)
        else:
            out.append({"name": "SuperSport Fixtures", "last_pull": "No data", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})
    else:
        out.append({"name": "SuperSport Fixtures", "last_pull": "Not Connected", "records_24h": 0, "css": "s-grey", "trend_7d": "\u2014"})

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
                   sr.source_name, shc.status as current_status
            FROM health_alerts ha
            LEFT JOIN source_registry sr ON sr.source_id = ha.source_id
            LEFT JOIN source_health_current shc ON shc.source_id = ha.source_id
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
            "current_status": r["current_status"] or "",
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
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            body = ""
        log.warning(f"[notion] HTTP {e.code} on {endpoint}: {body}")
        return None
    except Exception as e:
        log.warning(f"[notion] request failed on {endpoint}: {e}")
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
        return "".join(e.get("plain_text", "") for e in arr) if arr else None
    elif ptype == "rich_text":
        arr = prop.get("rich_text", [])
        return "".join(e.get("plain_text", "") for e in arr) if arr else None
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

    # Option A (FIX-DASH-PERF-02): cap at 3 pages cold (<200 rows) → <2s target
    raw_pages = _query_notion_db(
        NOTION_MARKETING_DB,
        sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
        page_size=100,
        max_pages=3,
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
            "image_url": _get_page_prop(page, "Image URL") or _get_page_prop(page, "Image") or "",
            "video_url": _get_page_prop(page, "Video URL") or _get_page_prop(page, "Video") or "",
            "asset_url": _get_page_prop(page, "Asset URL") or "",
            "media_url": _get_page_prop(page, "Media URL") or "",
            "ready_for_automation": _get_page_prop(page, "Ready for Automation?") or _get_page_prop(page, "Ready for Automation") or "",
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


def _th_search_daily_sheet(query: str, today_patterns: list[str]):
    """Search Notion for a daily sheet page whose title matches `query` AND contains
    one of today's date patterns. Returns (page_id, title) or (None, None)."""
    body = json.dumps({"query": query, "filter": {"value": "page", "property": "object"}, "page_size": 30}).encode("utf-8")
    req = urllib.request.Request("https://api.notion.com/v1/search", data=body,
                                  headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                                           "Notion-Version": "2025-09-03",
                                           "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.warning(f"[task-hub] search({query!r}) failed: {e}")
        return (None, None)
    for p in d.get("results", []):
        title = ""
        for pv in p.get("properties", {}).values():
            if pv.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in pv.get("title", []))
                break
        if any(pat.lower() in title.lower() for pat in today_patterns):
            return (p.get("id"), title)
    return (None, None)


def _th_fetch_blocks(page_id: str, max_pages: int = 4):
    """Fetch all blocks (paginated) for a Notion page. Returns list of block dicts."""
    out = []
    cursor = None
    for _ in range(max_pages):
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        req = urllib.request.Request(url,
                                      headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                                               "Notion-Version": "2025-09-03"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.warning(f"[task-hub] blocks({page_id}) failed: {e}")
            break
        out.extend(d.get("results", []))
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    return out


def _th_block_text(b: dict) -> str:
    t = b.get("type")
    content = b.get(t, {}) or {}
    if "rich_text" in content:
        return "".join(p.get("plain_text", "") for p in content.get("rich_text", []))
    return ""


def _th_block_url(b: dict) -> str:
    """Extract first URL from block's rich_text href annotations."""
    t = b.get("type")
    content = b.get(t, {}) or {}
    for p in content.get("rich_text", []):
        href = p.get("href")
        if href:
            return href
    return ""


def _th_today_patterns() -> list[str]:
    """Date fragments we match against daily-sheet titles."""
    sast = _SAST
    t = datetime.now(sast)
    pats = [
        t.strftime("%d %B %Y"),           # 17 April 2026
        t.strftime("%-d %B %Y") if hasattr(t, 'strftime') else t.strftime("%d %B %Y").lstrip("0"),
        t.strftime("%d %b %Y"),           # 17 Apr 2026
        t.strftime("%Y-%m-%d"),           # 2026-04-17
    ]
    # Dedupe + drop leading-zero variants
    pats.append(str(t.day) + t.strftime(" %B %Y"))
    pats.append(str(t.day) + t.strftime(" %b %Y"))
    return list(dict.fromkeys([p for p in pats if p]))


def _fetch_linkedin_ledger() -> list[dict]:
    """LinkedIn outreach targets parsed from today's '🔗 LinkedIn Connects — <date>' daily sheet.
    Block pattern: to_do (name — role, company — LinkedIn) + code (outreach message) — repeated.
    (Rewired 17 Apr 2026 v2: reads daily sheet child pages, not DBs.)"""
    cache_key = "linkedin_daily"
    now = time.monotonic()
    with _notion_cache_lock:
        cached = _notion_cache.get(cache_key)
        if cached and (now - cached[1]) < _NOTION_LEDGER_CACHE_TTL:
            return cached[0]

    rows: list[dict] = []
    try:
        pats = _th_today_patterns()
        page_id, page_title = _th_search_daily_sheet("LinkedIn Connects", pats)
        if not page_id:
            log.info(f"[task-hub] no LinkedIn daily sheet found for {pats[0]}")
        else:
            blocks = _th_fetch_blocks(page_id)
            current = None
            for b in blocks:
                t = b.get("type")
                if t == "to_do":
                    txt = _th_block_text(b)
                    url = _th_block_url(b)
                    if not txt:
                        continue
                    # Parse "Name — Role, Company — LinkedIn" (em-dash separator)
                    parts = [x.strip() for x in txt.split("—")]
                    name = parts[0] if parts else txt
                    role_company = parts[1] if len(parts) > 1 else ""
                    if "," in role_company:
                        role, company = role_company.split(",", 1)
                        role = role.strip(); company = company.strip()
                    else:
                        role = role_company; company = ""
                    posted = bool((b.get("to_do") or {}).get("checked"))
                    current = {
                        "id":           b.get("id", ""),
                        "name":         name,
                        "role":         role,
                        "company":      company,
                        "note":         "",
                        "url":          url,
                        "status":       "Posted" if posted else "Ready",
                        "posted":       posted,
                        "last_edited":  b.get("last_edited_time", ""),
                    }
                    rows.append(current)
                elif t == "code" and current is not None:
                    current["note"] = _th_block_text(b)[:500]
                    current = None  # message consumed
    except Exception as e:
        log.warning(f"[task-hub] linkedin daily parse failed: {e}")
        rows = []

    with _notion_cache_lock:
        _notion_cache[cache_key] = (rows, now)
    return rows


def _fetch_quora_ledger() -> list[dict]:
    """Quora questions parsed from today's '📝 Quora Daily — <date>' daily sheet.
    Block pattern per Q: heading_2 (Qn: question) + paragraph (Priority: …) + paragraph (View on Quora)
    + paragraph (<details><summary>) + N answer paragraphs + paragraph (</details>) + to_do (Posted).
    (Rewired 17 Apr 2026 v2.)"""
    cache_key = "quora_daily"
    now = time.monotonic()
    with _notion_cache_lock:
        cached = _notion_cache.get(cache_key)
        if cached and (now - cached[1]) < _NOTION_LEDGER_CACHE_TTL:
            return cached[0]

    rows: list[dict] = []
    try:
        pats = _th_today_patterns()
        page_id, _ = _th_search_daily_sheet("Quora Daily", pats)
        if not page_id:
            log.info(f"[task-hub] no Quora daily sheet found for {pats[0]}")
        else:
            blocks = _th_fetch_blocks(page_id)
            current = None
            in_answer = False
            answer_buf: list[str] = []
            for b in blocks:
                t = b.get("type")
                txt = _th_block_text(b)
                if t == "heading_2":
                    # flush previous
                    if current:
                        current["answer"] = "\n".join(answer_buf)[:800]
                        rows.append(current)
                    # new question (strip leading "Q1:", "Q12:", etc)
                    q = txt
                    m = re.match(r"^Q\d+[:.]?\s*", q)
                    if m:
                        q = q[m.end():]
                    current = {"id": b.get("id", ""), "question": q, "priority": "",
                               "url": "", "answer": "", "status": "Ready", "posted": False,
                               "topic": "Quora", "notes": "", "last_edited": b.get("last_edited_time", "")}
                    answer_buf = []
                    in_answer = False
                elif current is None:
                    continue
                elif t == "paragraph":
                    if txt.lower().startswith("priority:"):
                        current["priority"] = txt.split(":", 1)[1].strip().split("—")[0].strip()
                    elif "view on quora" in txt.lower() or txt.lower().startswith("url:"):
                        url = _th_block_url(b)
                        if url:
                            current["url"] = url
                    elif "<details" in txt.lower():
                        in_answer = True
                    elif "</details>" in txt.lower():
                        in_answer = False
                    elif in_answer:
                        if txt:
                            answer_buf.append(txt)
                elif t == "to_do" and txt.lower().startswith("posted"):
                    current["posted"] = bool((b.get("to_do") or {}).get("checked"))
                    current["status"] = "Posted" if current["posted"] else "Ready"
            if current:
                current["answer"] = "\n".join(answer_buf)[:800]
                rows.append(current)
    except Exception as e:
        log.warning(f"[task-hub] quora daily parse failed: {e}")
        rows = []

    with _notion_cache_lock:
        _notion_cache[cache_key] = (rows, now)
    return rows


def _fetch_fb_groups_today() -> list[dict]:
    """FB Group posts parsed from today's '📱 FB Groups — <date>' daily sheet.
    Block pattern per post: heading_3 (Group Name (size) — Category) + paragraphs for
    Image / Phase / Group URL / Headline char count + code (post text) + divider.
    (New 17 Apr 2026 v2 — supersedes MOQ filter.)"""
    cache_key = "fb_daily"
    now = time.monotonic()
    with _notion_cache_lock:
        cached = _notion_cache.get(cache_key)
        if cached and (now - cached[1]) < _NOTION_LEDGER_CACHE_TTL:
            return cached[0]

    rows: list[dict] = []
    try:
        pats = _th_today_patterns()
        page_id, _ = _th_search_daily_sheet("FB Groups", pats)
        if not page_id:
            log.info(f"[task-hub] no FB Groups daily sheet found for {pats[0]}")
        else:
            blocks = _th_fetch_blocks(page_id)
            current = None
            for b in blocks:
                t = b.get("type")
                txt = _th_block_text(b)
                if t == "heading_3":
                    if current:
                        rows.append(current)
                    # "Group Name (1.2K) — Category"
                    name = txt
                    size = ""
                    m = re.search(r"\(([^)]+)\)", txt)
                    if m:
                        size = m.group(1)
                        name = txt[:m.start()].strip()
                    if "—" in txt:
                        name_clean = name.split("—")[0].strip()
                        category = txt.split("—", 1)[1].strip() if "—" in txt else ""
                        name = name_clean
                    else:
                        category = ""
                    current = {"id": b.get("id", ""), "group": name, "size": size,
                               "category": category, "group_url": "", "image_url": "",
                               "phase": "", "final_copy": "", "title": name,
                               "status": "Ready", "posted": False, "last_edited": b.get("last_edited_time", "")}
                elif current is None:
                    continue
                elif t == "paragraph":
                    tl = txt.lower()
                    if tl.startswith("group url:"):
                        current["group_url"] = txt.split(":", 1)[1].strip()
                    elif tl.startswith("image"):
                        url = _th_block_url(b)
                        if url:
                            current["image_url"] = url
                    elif tl.startswith("phase:"):
                        current["phase"] = txt.split(":", 1)[1].strip()
                elif t == "code":
                    current["final_copy"] = _th_block_text(b)
                elif t == "to_do" and txt.lower().startswith(("posted", "done")):
                    current["posted"] = bool((b.get("to_do") or {}).get("checked"))
                    current["status"] = "Posted" if current["posted"] else "Ready"
            if current:
                rows.append(current)
    except Exception as e:
        log.warning(f"[task-hub] fb daily parse failed: {e}")
        rows = []

    # Enrich group_url from ledger registry where the daily sheet has no URL
    if rows:
        registry = _fetch_fb_ledger_registry()
        if registry:
            for row in rows:
                if not row["group_url"]:
                    name_key = row["group"].lower()
                    url = registry.get(name_key)
                    if not url:
                        for reg_name, reg_url in registry.items():
                            if reg_name in name_key or name_key in reg_name:
                                url = reg_url
                                break
                    if url:
                        row["group_url"] = url
                    else:
                        log.warning(f"[task-hub] no registry URL for FB group: {row['group']!r}")

    with _notion_cache_lock:
        _notion_cache[cache_key] = (rows, now)
    return rows


def _fetch_fb_ledger_registry() -> dict[str, str]:
    """Fetch group name → URL from the FB Groups Posting Ledger registry.
    Returns empty dict on any failure (integration may not have access yet)."""
    cache_key = "fb_ledger_registry"
    now = time.monotonic()
    with _notion_cache_lock:
        cached = _notion_cache.get(cache_key)
        if cached and (now - cached[1]) < _NOTION_LEDGER_CACHE_TTL:
            return cached[0]

    registry: dict[str, str] = {}
    try:
        result = _notion_request(f"databases/{NOTION_FB_GROUPS_LEDGER}/query", body={"page_size": 100})
        if result and result.get("results"):
            for page in result["results"]:
                props = page.get("properties", {})
                name = None
                url = None
                for prop in props.values():
                    ptype = prop.get("type", "")
                    if ptype == "title" and name is None:
                        arr = prop.get("title", [])
                        name = "".join(e.get("plain_text", "") for e in arr).strip()
                    elif ptype == "url" and url is None:
                        url = prop.get("url") or ""
                    elif ptype == "rich_text" and url is None:
                        arr = prop.get("rich_text", [])
                        val = "".join(e.get("plain_text", "") for e in arr).strip()
                        if val.startswith("https://www.facebook.com"):
                            url = val
                if name and url:
                    registry[name.lower()] = url
    except Exception as e:
        log.warning(f"[task-hub] fb ledger registry fetch failed: {e}")

    with _notion_cache_lock:
        _notion_cache[cache_key] = (registry, now)
    return registry


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
        return "fb_groups"
    if "ig" in low or "insta" in low:
        return "instagram"
    if "linked" in low:
        return "linkedin"
    if "tiktok" in low or "tik" in low:
        return "tiktok"
    if "thread" in low:
        return "threads"
    if "telegram" in low:
        if "alert" in low:
            return "telegram_alerts"
        if "community" in low or "comm" in low:
            return "telegram_community"
        return "telegram_alerts"
    if "whatsapp" in low or "wa " in low or low == "wa":
        return "whatsapp_channel"
    if "quora" in low:
        return "quora"
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
    "Threads", "Threads Image",
    "WhatsApp Channel",
    "TikTok",
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
    now_sast = datetime.now(_SAST)
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
            if sched_dt and sched_dt <= now_sast:
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
  body::before {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: url('/admin/static/bg-hero.jpg') center/cover no-repeat;
    opacity: 0.23;
    z-index: 0;
    pointer-events: none;
  }
  body > * { position: relative; z-index: 1; }
  html, body {
    background: var(--carbon);
    color: var(--text);
    font-family: var(--font-b);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
    overflow-x: hidden;
    background-image: none;
    position: relative;
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
  .kpi::after { content:''; position:absolute; top:0; left:0; right:0; height:2px; background: var(--grad); opacity: 0.45; transition: opacity 300ms var(--trans); }
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
  .panel { background: var(--surface); border: 1px solid rgba(255,255,255,0.05); border-radius: var(--r); overflow: hidden; position: relative; margin-bottom: 16px; box-shadow: var(--glow); transition: box-shadow 300ms var(--trans), border-color 300ms var(--trans); }
  .panel:hover { box-shadow: var(--glow-hover); border-color: rgba(248,200,48,0.08); }
  .panel-head { padding: 11px 18px; border-bottom: 1px solid rgba(255,255,255,0.04); display: flex; align-items: center; justify-content: space-between; gap: 12px; background: rgba(0,0,0,0.2); backdrop-filter: blur(4px); }
  .panel-title { font-family: var(--font-d); font-weight: 700; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--text); }
  .panel-sub { font-size: 11px; font-family: var(--font-m); color: var(--muted); text-align: right; }
  .panel-red-accent { border-left: 3px solid var(--red); }
  .panel-orange-accent::after { content:''; position:absolute; top:0; left:0; right:0; height:2px; background:var(--grad); opacity:0.45; pointer-events:none; z-index:1; }

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
    #loading-bar { left: 0; }
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
        ("social_ops", "Social Ops", _ICON_PLAY, "/admin/social-ops"),
        ("task_hub", "Task Hub", _ICON_TASKHUB, "/admin/task-hub"),
    ]
    # Badge counts only genuinely failed/blocked items — awaiting approvals do not
    # surface here, since those live in-screen on the Social Ops view itself.
    # Read from the Notion cache without triggering a fetch. A cold cache must
    # never block server-side sidebar rendering; the client-side poll against
    # /admin/api/task_hub_badge will correct the value once data arrives.
    _badge_count = 0
    try:
        with _notion_cache_lock:
            _cached = _notion_cache.get("marketing_queue")
        if _cached:
            _mq = _cached[0]
            _badge_count = sum(
                1 for _it in _mq
                if (_it.get("status") or "").lower().strip() in ("failed", "blocked", "error")
            )
    except Exception:
        pass
    nav_items = ""
    for key, label, icon, href in items:
        active_cls = " active" if key == active_view else ""
        badge_html = ""
        if key == "social_ops" and _badge_count > 0:
            badge_html = f'<span class="nav-badge" id="th-badge">{_badge_count}</span>'
        nav_items += f'<a class="sidebar-item{active_cls}" href="{href}" data-view="{key}"><span class="item-icon">{icon}</span><span class="item-label">{label}{badge_html}</span></a>\n'

    return f"""<aside class="sidebar" id="sidebar">
  <div class="sidebar-brand"><img src="/admin/static/wordmark.png" alt="MzansiEdge"></div>
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
          var thLink = document.querySelector('.sidebar-item[data-view="social_ops"] .item-label');
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
    "Data Feeds", "Monitoring",
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
                r.expected_interval_minutes, r.cron_schedule,
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

    now_sast = datetime.now(_SAST) if hasattr(datetime, 'now') else None
    for row in rows:
        d = dict(row)
        interval = d.get("expected_interval_minutes") or 0
        raw_status = d.get("status") or "black"
        # AC-1: on-demand services (interval=0) with no success show as grey, never red/black
        status = "grey" if (interval == 0 and raw_status == "black") else raw_status
        # Freshness override: if interval > 0 and last_success exceeds interval, force RED
        # Uses cron-window-aware logic so time-window scrapers don't fire overnight false alarms
        if interval > 0 and now_sast and d.get("last_success_at"):
            try:
                _ls = d["last_success_at"].replace("Z", "+00:00")
                _last_dt = datetime.fromisoformat(_ls)
                if _last_dt.tzinfo is None:
                    _last_dt = _last_dt.replace(tzinfo=_UTC)
                _age_min = (now_sast - _last_dt).total_seconds() / 60

                _truly_stale = True
                _cron_sched = d.get("cron_schedule") or ""
                if _cron_sched and _cron_sched.strip() not in ("on-demand", "@reboot"):
                    try:
                        import importlib.util as _ilu
                        _cw_spec = _ilu.spec_from_file_location(
                            "_cron_window",
                            os.path.join(os.path.expanduser("~"), "scripts", "cron_window.py")
                        )
                        _cw = _ilu.module_from_spec(_cw_spec)
                        _cw_spec.loader.exec_module(_cw)
                        _windows = _cw.parse_multi(_cron_sched)
                        if _windows and not _cw.is_in_any_window(_windows, now_sast):
                            _last_close = _cw.last_window_close(_windows, now_sast)
                            if _last_close is None or _last_dt >= _last_close - timedelta(minutes=interval):
                                _truly_stale = False  # outside window and caught the last window
                    except Exception:
                        pass  # cron_window unavailable — fall back to raw interval check

                if _truly_stale and _age_min > interval:
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
    red_cnt = shm.get("red_count", 0)
    black_cnt = shm.get("black_count", 0)
    total_degraded = yellow + red_cnt + black_cnt
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

    # Warn block: all non-green/non-grey sources
    warn_html = ""
    if total_degraded > 0:
        warn_src = [
            d for cat in _CATEGORY_ORDER
            for d in shm["sources_by_category"].get(cat, [])
            if (d.get("status") or "black") not in ("green", "grey", None)
        ]
        if warn_src:
            rows = "".join(
                f'<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px;font-family:var(--font-m)">'
                f'{_STATUS_DOT.get(d.get("status","black"),"")} '
                f'<span style="color:var(--text);flex:1">{d.get("source_name","")}</span>'
                f'<span style="color:var(--muted)">{_relative_time(d.get("last_success_at",""))}</span>'
                f'</div>'
                for d in warn_src
            )
            warn_html = (
                f'<details style="margin-bottom:8px">'
                f'<summary style="cursor:pointer;font-size:12px;font-family:var(--font-m);color:#f59e0b;padding:4px 0">'
                f'&#9679; {total_degraded} source{"s" if total_degraded != 1 else ""} degraded — expand</summary>'
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
    """Render Social Ops split-pane: tasks left, channels right (UI-SOCIAL-OPS-REDESIGN-01)."""
    import html as _html_mod

    notion_ok = True
    items: list[dict] = []
    fetch_time = time.monotonic()
    try:
        items, fetch_time = _fetch_marketing_queue()
    except Exception:
        notion_ok = False
        with _notion_cache_lock:
            cached = _notion_cache.get("marketing_queue")
            if cached:
                items = cached[0]
                fetch_time = cached[1]

    age_s = max(0, int(time.monotonic() - fetch_time))
    if age_s < 60:
        sync_label = f"Synced {age_s}s ago"
    elif age_s < 3600:
        sync_label = f"Synced {age_s // 60}m ago"
    else:
        sync_label = f"Synced {age_s // 3600}h ago"

    now_sast = datetime.now(_SAST)

    _CHANNEL_SLA: dict[str, float] = {
        "telegram_alerts": 6.0, "telegram_community": 12.0, "whatsapp_channel": 6.0,
        "instagram": 24.0, "tiktok": 48.0,
        "fb_groups": 72.0, "quora": 168.0,
    }
    _LK_GREEN_DAYS, _LK_AMBER_DAYS = 7, 14

    all_channels = _CHANNELS + _MANUAL_CHANNELS
    channel_stats: dict[str, dict] = {
        ch["key"]: {"last_published_ts": None, "queue_depth": 0, "approvals": 0,
                    "last_failed": False, "items": []}
        for ch in all_channels
    }
    failed_blocked: list[dict] = []

    # AC-A: load Alerts send log (event-driven, replaces dead MOQ→Alerts path)
    _asl_conn = db_connect(SCRAPERS_DB)
    _alerts_sends: list[dict] = []
    if _asl_conn:
        try:
            _alerts_sends = _fetch_alerts_send_log(_asl_conn, limit=10)
        except Exception:
            pass
        finally:
            _asl_conn.close()
    if _alerts_sends:
        _most_recent_send = _alerts_sends[0]  # already sorted DESC
        channel_stats["telegram_alerts"]["last_published_ts"] = datetime.fromtimestamp(
            _most_recent_send["sent_at"], tz=_UTC
        )

    for item in items:
        ch_key = _normalise_channel_key(item.get("channel") or "")
        if ch_key not in channel_stats:
            continue
        status = (item.get("status") or "").lower().strip()
        ts_raw = item.get("last_edited") or item.get("scheduled_time") or item.get("created") or ""
        if status in ("published", "done", "complete"):
            dt = parse_ts(ts_raw)
            if dt and (channel_stats[ch_key]["last_published_ts"] is None
                       or dt > channel_stats[ch_key]["last_published_ts"]):
                channel_stats[ch_key]["last_published_ts"] = dt
        elif status in ("failed", "blocked", "error"):
            channel_stats[ch_key]["last_failed"] = True
            failed_blocked.append(item)
        elif status not in ("archived",):
            channel_stats[ch_key]["queue_depth"] += 1
        if status in ("awaiting approval", "draft", "review", "pending", "in review", "awaiting"):
            channel_stats[ch_key]["approvals"] += 1
        channel_stats[ch_key]["items"].append(item)

    def _sla_state(ch_key: str, last_ts) -> dict:
        sev_color = {"healthy": "var(--green)", "watch": "var(--amber)",
                     "breached": "var(--red)", "dormant": "#6E7681"}
        if ch_key == "linkedin":
            sla_disp = f"{_LK_GREEN_DAYS}d"
            if not last_ts:
                return {"sev": "dormant", "color": sev_color["dormant"], "age": "\u2014",
                        "sla": sla_disp, "ratio": "\u2014"}
            age_d = (now_sast - last_ts).total_seconds() / 86400
            if age_d < _LK_GREEN_DAYS:
                sev = "healthy"
            elif age_d < _LK_AMBER_DAYS:
                sev = "watch"
            else:
                sev = "breached"
            return {"sev": sev, "color": sev_color[sev], "age": f"{age_d:.0f}d",
                    "sla": sla_disp, "ratio": f"{age_d:.0f}d / {_LK_GREEN_DAYS}d"}
        sla_h = _CHANNEL_SLA.get(ch_key, 24.0)
        sla_disp = f"{sla_h:.0f}h"
        if not last_ts:
            return {"sev": "dormant", "color": sev_color["dormant"], "age": "\u2014",
                    "sla": sla_disp, "ratio": "\u2014"}
        age_h = (now_sast - last_ts).total_seconds() / 3600
        if age_h < 1:
            age_lbl = f"{int(age_h * 60)}m"
        elif age_h < 48:
            age_lbl = f"{age_h:.1f}h"
        else:
            age_lbl = f"{age_h / 24:.0f}d"
        if age_h < sla_h:
            sev = "healthy"
        elif age_h < sla_h * 2:
            sev = "watch"
        else:
            sev = "breached"
        return {"sev": sev, "color": sev_color[sev], "age": age_lbl,
                "sla": sla_disp, "ratio": f"{age_lbl} / {sla_disp}"}

    _SEV_ORDER = {"breached": 0, "watch": 1, "dormant": 2, "healthy": 3}
    rows_data = []
    for ch in all_channels:
        cs = channel_stats[ch["key"]]
        st = _sla_state(ch["key"], cs["last_published_ts"])
        if cs["last_failed"]:
            st = {"sev": "breached", "color": "var(--red)", "age": "Failed",
                  "sla": st["sla"], "ratio": "Failed"}
        rows_data.append({"ch": ch, "st": st, "approvals": cs["approvals"],
                          "queue": cs["queue_depth"], "last_ts": cs["last_published_ts"]})

    def _sort_key(r):
        sev = r["st"]["sev"]
        ts = r["last_ts"].timestamp() if r["last_ts"] else 0
        secondary = -ts if sev != "healthy" else ts
        return (_SEV_ORDER[sev], secondary)
    rows_data.sort(key=_sort_key)

    def _row_html(r: dict) -> str:
        ch, st = r["ch"], r["st"]
        is_dormant = st["sev"] == "dormant"
        dot_style = (f'background:transparent;border:1.5px solid {st["color"]}'
                     if is_dormant else f'background:{st["color"]};border:1.5px solid {st["color"]}')
        appr_badge = (f'<span class="so-ch-appr-badge">\u00d7{r["approvals"]}</span>'
                      if r["approvals"] > 0 else "")
        if r["last_ts"]:
            age_h = (now_sast - r["last_ts"]).total_seconds() / 3600
            if age_h < 1:
                last_pub = f"{int(age_h * 60)}m ago"
            elif age_h < 48:
                last_pub = f"{age_h:.1f}h ago"
            else:
                last_pub = f"{age_h / 24:.0f}d ago"
        else:
            last_pub = "no posts"
        icon_svg = _CHANNEL_SVG.get(ch["key"], "")
        return (
            f'<div class="so-ch-row" data-severity="{st["sev"]}" data-channel="{ch["key"]}">'
            f'<span class="so-ch-dot" style="{dot_style}"></span>'
            f'<span class="so-ch-icon">{icon_svg}</span>'
            f'<span class="so-ch-name">{_html_mod.escape(ch["label"])}</span>'
            f'<span class="so-ch-last">{last_pub}</span>'
            f'<span class="so-ch-sla">{st["ratio"]}</span>'
            f'{appr_badge}'
            f'</div>'
        )

    channel_rows_html = "".join(_row_html(r) for r in rows_data)

    fb_banner_html = ""
    if failed_blocked:
        fb_count = len(failed_blocked)
        fb_item_parts = []
        for it in failed_blocked:
            pid = _html_mod.escape(it.get("id") or "")
            if not pid:
                continue
            ch_key = _normalise_channel_key(it.get("channel") or "")
            ch_lbl = _CHANNEL_MAP.get(ch_key, {}).get("label", ch_key or "?")
            err = _truncate(it.get("error") or it.get("title") or "issue", 80)
            fb_item_parts.append(
                f'<span class="so-fb-item" data-page-id="{pid}">'
                f'<span class="so-fb-item-text">{_html_mod.escape(ch_lbl)}: {_html_mod.escape(err)}</span>'
                f'<button type="button" class="so-fb-item-dismiss" '
                f'title="Dismiss notification" onclick="__soDismissFB(this)" '
                f'aria-label="Dismiss">&times;</button>'
                f'</span>'
            )
        fb_banner_html = (
            '<div class="so-fb-banner" id="so-fb-banner">'
            f'<span class="so-fb-count" id="so-fb-count">{fb_count} failed/blocked</span>'
            f'<span class="so-fb-list">{"".join(fb_item_parts)}</span>'
            '</div>'
        )
    # ── KPI computation (BUILD-SOCIAL-OPS-DASH-BOTTOM-01) ───────────────
    import json as _json_mod
    _POSTED_ST = {"published", "done", "complete", "posted"}
    _PENDING_ST = {"pending", "queued", "scheduled", "ready", "approved"}
    _FAILED_ST  = {"failed", "error", "blocked"}
    _OVERDUE_QUEUE_ST = {"pending", "ready", "queued"}
    _cutoff24   = now_sast - timedelta(hours=24)
    kpi_posted = kpi_pending = kpi_failed = kpi_queue = kpi_overdue_queue = kpi_pastdue = kpi_unscheduled = 0
    _12h_horizon = now_sast + timedelta(hours=12)
    for _it in items:
        _st  = (_it.get("status") or "").lower().strip()
        _ts  = parse_ts(_it.get("last_edited") or _it.get("scheduled_time") or _it.get("created") or "")
        _sch = parse_ts(_it.get("scheduled_time") or "")
        _rfa = (_it.get("ready_for_automation") or "").lower().strip()
        if _st in _POSTED_ST:
            if _ts and _ts >= _cutoff24:
                kpi_posted += 1
        elif _st in _FAILED_ST:
            if _ts and _ts >= _cutoff24:
                kpi_failed += 1
        elif _st != "archived":
            if _st in _PENDING_ST:
                kpi_pending += 1
            if _sch and now_sast <= _sch <= _12h_horizon:
                kpi_queue += 1
            if _sch and _sch < now_sast and _st in _PENDING_ST and _rfa in ("yes", "true", "1", "y"):
                kpi_pastdue += 1
            if not _sch and _st in _PENDING_ST:
                kpi_unscheduled += 1
        if (_st in _OVERDUE_QUEUE_ST
                and _sch and _sch < now_sast
                and _rfa in ("yes", "true", "1", "y")):
            kpi_overdue_queue += 1

    # ── Timeline init data (02B) ─────────────────────────────────────────
    _today_sast = now_sast.astimezone(_SAST)
    _today_str  = _today_sast.strftime("%Y-%m-%d")
    _now_mins   = _today_sast.hour * 60 + _today_sast.minute

    _TL_CH = [
        ("telegram_alerts",    "TG Alerts"),
        ("telegram_community", "TG Community"),
        ("whatsapp_channel",   "WA Channel"),
        ("instagram",          "Instagram"),
        ("tiktok",             "TikTok"),
    ]

    def _icon_for(wt: str, ck: str) -> str:
        w = (wt or "").lower()
        if "seed chat" in w:                 return "message-circle"
        if "morning" in w:                   return "sun"
        if "news" in w:                      return "newspaper"
        if "edge card" in w or "diamond" in w or "edge" in w: return "diamond"
        if "recap" in w:                     return "trophy"
        if "teaser" in w:                    return "eye"
        if "poll" in w or "discuss" in w:    return "message-square-more"
        if "alert" in w:                     return "bell"
        if "reel" in w:                      return "play-circle"
        if "carousel" in w:                  return "layers"
        if "story" in w:                     return "circle"
        if "b.r.u" in w or "bru" in w:       return "bot"
        if "article" in w:                   return "book-open"
        if "answer" in w:                    return "message-square-quote"
        if "image" in w or "photo" in w:     return "image"
        if "chat" in w:                      return "message-circle"
        _fb = {"tiktok": "bot", "telegram_alerts": "message-circle",
               "telegram_community": "message-square-more",
               "whatsapp_channel": "bell", "whatsapp_group": "message-square-more",
               "instagram": "image", "linkedin": "briefcase",
               "fb_groups": "message-square", "quora": "message-square-quote",
               "threads": "at-sign"}
        return _fb.get(ck, "help-circle")

    def _norm_wg(ch_raw: str) -> str:
        c = (ch_raw or "").lower()
        if "group" in c and ("whatsapp" in c or " wa" in c or c.startswith("wa")):
            return "whatsapp_group"
        return _normalise_channel_key(ch_raw)

    # ── Reel-kit + IG Story warnings banner (BUILD-SOCIAL-OPS-PREVIEW-UX-01) ──
    _warn_items: list[dict] = []
    try:
        for _rk in _fetch_overdue_notion_reel_kits():
            _warn_items.append({
                "id": _rk.get("block_id", ""),
                "label": f"\U0001f3a5 Reel Kit {_rk['date']} overdue",
                "href": "/admin/reel-kit",
            })
    except Exception:
        pass
    for _it in items:
        _wt = (_it.get("work_type") or "").lower()
        if "story" not in _wt:
            continue
        if _norm_wg(_it.get("channel") or "") != "instagram":
            continue
        _sdt2 = parse_ts(_it.get("scheduled_time") or "")
        if not _sdt2:
            continue
        if _sdt2.astimezone(_SAST).strftime("%Y-%m-%d") != _today_str:
            continue
        _asset2 = (_it.get("asset_link") or _it.get("asset_url") or _it.get("media_url") or "").strip()
        _pid2 = _html_mod.escape(_it.get("id") or "")
        _ttl2 = _it.get("title") or "IG Story"
        if not _asset2:
            _warn_items.append({"id": _pid2, "label": f"IG Story missing asset: {_ttl2[:60]}", "href": ""})
        elif _asset2.lower().startswith("computer://"):
            _warn_items.append({"id": _pid2, "label": f"IG Story has computer:// URL: {_ttl2[:60]}", "href": ""})
    warn_banner_html = ""
    if _warn_items:
        _wb_count = len(_warn_items)
        _wb_parts = []
        for _wi in _warn_items:
            _wi_label = _html_mod.escape(_wi["label"])
            _wi_id = _html_mod.escape(_wi.get("id") or "")
            _wi_href = _html_mod.escape(_wi.get("href") or "")
            _wi_text = (f'<a href="{_wi_href}" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline;">{_wi_label}</a>'
                        if _wi_href else _wi_label)
            _wb_parts.append(
                f'<span class="so-fb-item" data-page-id="{_wi_id}">'
                f'<span class="so-fb-item-text">{_wi_text}</span>'
                f'<button type="button" class="so-fb-item-dismiss" '
                f'title="Dismiss" onclick="__soWarnDismiss(this)" '
                f'aria-label="Dismiss">&times;</button>'
                f'</span>'
            )
        warn_banner_html = (
            '<div class="so-warn-banner" id="so-warn-banner">'
            f'<span class="so-fb-count" id="so-warn-count">{_wb_count} warning{"s" if _wb_count != 1 else ""}</span>'
            f'<span class="so-fb-list">{"".join(_wb_parts)}</span>'
            '</div>'
        )

    _tl_chans: list[dict] = []
    for _ck, _clbl in _TL_CH:
        _posts: list[dict] = []
        for _it in items:
            if _norm_wg(_it.get("channel") or "") != _ck:
                continue
            _sdt = parse_ts(_it.get("scheduled_time") or "")
            if not _sdt:
                continue
            _ss = _sdt.astimezone(_SAST)
            if _ss.strftime("%Y-%m-%d") != _today_str:
                continue
            _smins = _ss.hour * 60 + _ss.minute
            _adt   = parse_ts(_it.get("last_edited") or "")
            _ahhmm = (_adt.astimezone(_SAST).strftime("%H:%M") if _adt else "")
            _raw_st = (_it.get("status") or "").lower().strip()
            _disp_st = "queued" if _raw_st == "approved" else _raw_st
            _posts.append({
                "id":     _it.get("id", ""),
                "title":  (_it.get("title") or _it.get("copy") or "")[:60],
                "type":   _it.get("work_type") or "",
                "icon":   _icon_for(_it.get("work_type") or "", _ck),
                "status": _disp_st,
                "mins":   _smins,
                "sched":      f"{_ss.hour:02d}:{_ss.minute:02d}",
                "sched_full": _render_sast(_sdt),
                "actual": _ahhmm,
                "error":    _it.get("error") or "",
                "ch_lbl":   _clbl,
                "asset_url": _resolve_media_url(_it.get("asset_link") or _it.get("asset_url") or _it.get("image_url") or ""),
            })
        _tl_chans.append({"key": _ck, "label": _clbl, "icon": _so_platform_icon_svg(_ck), "color": _CHANNEL_MAP.get(_ck, {}).get("color", "#888888"), "posts": _posts})

    # AC-A: inject today's Alerts bot sends into the telegram_alerts timeline lane
    for _tl_ch in _tl_chans:
        if _tl_ch["key"] != "telegram_alerts":
            continue
        for _asend in _alerts_sends:
            _sdt = datetime.fromtimestamp(_asend["sent_at"], tz=_UTC).astimezone(_SAST)
            if _sdt.strftime("%Y-%m-%d") != _today_str:
                continue
            _smins2 = _sdt.hour * 60 + _sdt.minute
            _tier2 = _asend["tier"]
            _tl_ch["posts"].append({
                "id":        _asend["edge_id"] or _asend["match_key"],
                "title":     (_asend["match_key"] or "Edge card")[:60],
                "type":      f"{_tier2.title()} · {_asend['image_bytes_size'] // 1024}KB",
                "icon":      "diamond",
                "status":    "published",
                "mins":      _smins2,
                "sched":     f"{_sdt.hour:02d}:{_sdt.minute:02d}",
                "sched_full": f"Sent {_sdt.strftime('%H:%M')} SAST",
                "actual":    f"{_sdt.hour:02d}:{_sdt.minute:02d}",
                "error":     "",
                "ch_lbl":    "TG Alerts",
                "asset_url": "",
            })
        break

    _tl_json = _json_mod.dumps({
        "day":      _today_str,
        "now_mins": _now_mins,
        "channels": _tl_chans,
        "kpis": {
            "posted_24h":  kpi_posted,
            "pending":     kpi_pending,
            "failed_24h":  kpi_failed,
            "queue_depth": kpi_queue,
            "overdue_queue_count": kpi_overdue_queue,
            "past_due":    kpi_pastdue,
            "unscheduled": kpi_unscheduled,
        },
    })


    notion_warn = '' if notion_ok else (
        '<div class="so-warn">Notion unavailable \u2014 showing cached data</div>'
    )

    css = """<style>
.so-page{font-family:var(--font-b);color:var(--text);height:100vh;padding:16px 20px;box-sizing:border-box;display:flex;flex-direction:column;overflow:hidden;}
.so-topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:12px;flex-wrap:wrap;}
.so-h1{font-size:18px;font-weight:600;letter-spacing:-0.01em;margin:0;color:var(--text);display:flex;align-items:center;gap:8px;}
.so-live-dot{color:var(--green);font-size:10px;animation:so-blink 2s ease-in-out infinite;}
@keyframes so-blink{0%,100%{opacity:1;}50%{opacity:0.3;}}
.so-controls{display:flex;align-items:center;gap:10px;}
.so-sync-pill{font-family:var(--font-m);font-size:12px;color:var(--muted);background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:4px 10px;}
.so-warn{font-size:12px;color:var(--amber);margin-bottom:10px;}
.so-stale-badge{font-family:var(--font-m);font-size:10px;color:var(--amber);background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);border-radius:10px;padding:1px 6px;}
.so-day-picker{display:flex;align-items:center;gap:6px;}
.so-day-btn{background:var(--surface);border:1px solid var(--border);color:var(--muted);border-radius:4px;width:26px;height:26px;cursor:pointer;font-size:11px;display:flex;align-items:center;justify-content:center;transition:color 150ms,border-color 150ms;line-height:1;padding:0;}
.so-day-btn:hover:not(:disabled){color:var(--text);border-color:var(--gold);}
.so-day-btn:disabled{opacity:0.3;cursor:default;}
.so-day-lbl{font-family:var(--font-m);font-size:12px;color:var(--text);min-width:58px;text-align:center;}
.so-kpi-strip{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin-bottom:14px;}
@media(max-width:1100px){.so-kpi-strip{grid-template-columns:repeat(4,1fr);}}
@media(max-width:750px){.so-kpi-strip{grid-template-columns:repeat(3,1fr);}}
.so-fb-banner{background:rgba(248,81,73,0.08);border:1px solid rgba(248,81,73,0.28);border-radius:6px;
  color:var(--red);font-family:var(--font-m);font-size:12px;padding:6px 10px;margin-bottom:10px;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;line-height:1.4;}
.so-fb-count{font-weight:600;text-transform:uppercase;letter-spacing:.3px;font-size:11px;flex-shrink:0;}
.so-fb-list{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:1;min-width:0;}
.so-fb-item{display:inline-flex;align-items:center;gap:4px;background:rgba(248,81,73,0.10);
  border:1px solid rgba(248,81,73,0.28);border-radius:4px;padding:2px 2px 2px 9px;max-width:100%;}
.so-fb-item-text{font-size:11px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:420px;}
.so-fb-item-dismiss{background:transparent;border:none;color:var(--red);cursor:pointer;
  font-size:14px;line-height:1;padding:1px 7px;border-radius:3px;font-family:inherit;}
.so-fb-item-dismiss:hover{background:rgba(248,81,73,0.22);}
.so-fb-item-dismiss:disabled{opacity:0.4;cursor:wait;}
.so-main{display:grid;grid-template-columns:minmax(0,65fr) minmax(0,35fr);gap:16px;align-items:stretch;flex:1;min-height:0;overflow:hidden;}
@media(max-width:1279px){.so-main{grid-template-columns:minmax(0,1fr);flex:0 0 auto;height:auto;overflow:visible;}}
.so-left{display:flex;flex-direction:column;gap:12px;min-width:0;min-height:0;overflow:hidden;}
.so-bottom-grid{display:flex;flex-direction:column;gap:12px;flex:1;min-height:0;}
.so-queue{position:relative;overflow:hidden;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:10px 12px;min-width:0;display:flex;flex-direction:column;gap:8px;flex:1;min-height:0;box-shadow:var(--glow);}
.so-queue::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--grad);opacity:0.45;pointer-events:none;z-index:1;}
.so-panel-h{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.so-panel-title{font-size:12px;font-weight:600;color:var(--text);margin:0;letter-spacing:.3px;text-transform:uppercase;}
.so-panel-sub{font-family:var(--font-m);font-size:10px;color:var(--muted);}
.so-queue-body{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px;}
.so-queue-body::-webkit-scrollbar{width:6px;}.so-queue-body::-webkit-scrollbar-track{background:transparent;}.so-queue-body::-webkit-scrollbar-thumb{background:var(--muted);border-radius:3px;opacity:.5;}
.so-queue-row{position:relative;display:flex;align-items:center;gap:12px;padding:12px 14px 12px 18px;border-radius:8px;cursor:pointer;border:1px solid var(--border);background:var(--surface-alt);transition:border-color 150ms,transform 150ms,background 150ms;min-height:60px;overflow:hidden;}
.so-queue-row::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--so-ch,#888);}
.so-queue-row:hover{border-color:var(--so-ch,var(--gold));transform:translateY(-1px);background:var(--surface);}
.so-queue-row-logo{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;background:rgba(255,255,255,0.03);border:1px solid var(--border-sub);}
.so-queue-row-logo svg{width:22px;height:22px;}
.so-queue-row-main{min-width:0;flex:1;display:flex;flex-direction:column;gap:4px;}
.so-queue-row-title{font-size:14px;font-weight:500;color:var(--text);line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.so-queue-row-meta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted);}
.so-queue-row-ch{font-family:var(--font-m);font-size:10px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;color:var(--so-ch,var(--muted));}
.so-queue-row-type{color:var(--text);opacity:.75;font-size:11px;}
.so-queue-row-dot{width:3px;height:3px;border-radius:50%;background:var(--muted);opacity:.6;flex-shrink:0;}
.so-queue-row-status{padding:1px 7px;border-radius:10px;font-size:9px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;font-family:var(--font-m);flex-shrink:0;}
.so-queue-row-status.st-queued,.so-queue-row-status.st-approved,.so-queue-row-status.st-pending{background:rgba(248,200,48,0.12);color:var(--gold);border:1px solid rgba(248,200,48,0.28);}
.so-queue-row-status.st-ready{background:rgba(56,139,253,0.15);color:#58a6ff;border:1px solid rgba(56,139,253,0.30);}
.so-queue-row-status.st-scheduled{background:rgba(163,113,247,0.15);color:#bc8cff;border:1px solid rgba(163,113,247,0.30);}
.so-queue-row-when{display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0;text-align:right;}
.so-queue-row-time{font-family:var(--font-m);font-size:13px;color:var(--gold);font-weight:600;white-space:nowrap;}
.so-queue-row-rel{font-family:var(--font-m);font-size:10px;color:var(--muted);white-space:nowrap;}
.so-queue-empty{font-family:var(--font-m);font-size:11px;color:var(--muted);text-align:center;padding:30px 6px;}
.so-tile{position:relative;overflow:hidden;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:12px;min-height:200px;display:flex;flex-direction:column;min-width:0;box-shadow:var(--glow);}
.so-tile::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--grad);opacity:0.45;pointer-events:none;z-index:1;}
.so-tile-h{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;}
.so-tile-title{font-size:12px;font-weight:600;color:var(--text);margin:0;letter-spacing:.3px;text-transform:uppercase;display:flex;align-items:center;gap:6px;}
.so-tile-count{font-family:var(--font-m);font-size:10px;color:var(--muted);background:var(--surface-alt);border:1px solid var(--border);border-radius:10px;padding:1px 8px;}
.so-tile-body{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:6px;max-height:260px;}
.so-tile-body::-webkit-scrollbar{width:4px;}.so-tile-body::-webkit-scrollbar-track{background:transparent;}.so-tile-body::-webkit-scrollbar-thumb{background:var(--muted);opacity:.5;border-radius:2px;}
.so-tile-row{display:flex;align-items:center;gap:8px;padding:6px 8px;background:var(--surface-alt);border:1px solid var(--border);border-radius:6px;cursor:pointer;text-decoration:none;color:inherit;transition:border-color 150ms;}
.so-tile-row:hover{border-color:var(--gold);}
.so-tile-row-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.so-tile-row-title{font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.so-tile-row-sub{font-family:var(--font-m);font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.so-tile-empty{font-family:var(--font-m);font-size:11px;color:var(--muted);text-align:center;padding:20px 6px;}
.so-tile-thumb{width:28px;height:28px;border-radius:4px;object-fit:cover;background:var(--surface-alt);flex-shrink:0;}
.so-tile-tag{font-family:var(--font-m);font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:1px 5px;border-radius:3px;flex-shrink:0;border:1px solid var(--border);color:var(--muted);}
.so-tile-skel{background:var(--surface-alt);border-radius:4px;height:14px;animation:skel-p 1.2s ease-in-out infinite alternate;}
.so-tl-wrap{position:relative;min-width:0;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;contain:paint;box-shadow:var(--glow);}
.so-tl-wrap::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--grad);opacity:0.7;pointer-events:none;z-index:1;}
.so-tl-content{position:relative;}
.so-tl-hours-row{position:relative;height:22px;margin-left:140px;border-bottom:1px solid var(--border-sub);background:var(--surface-alt);}
.so-tl-hour-lbl{position:absolute;font-family:var(--font-m);font-size:10px;color:var(--muted);transform:translateX(-50%);top:4px;pointer-events:none;}
.so-tl-row{display:flex;align-items:center;height:52px;border-bottom:1px solid rgba(48,54,61,0.4);}
.so-tl-row:last-child{border-bottom:none;}
.so-tl-row:focus{outline:none;}
.so-tl-row-lbl{width:140px;flex-shrink:0;padding:0 8px 0 10px;font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:center;gap:6px;}
.so-tl-ch-icon{flex-shrink:0;display:flex;align-items:center;}
.so-tl-bar{flex:1;position:relative;height:52px;overflow:visible;}
.so-tl-gl{position:absolute;top:0;bottom:0;width:1px;background:rgba(255,255,255,0.04);pointer-events:none;}
.so-tl-gl-mid{background:rgba(255,255,255,0.025);}
.so-tl-hour-lbl-mid{opacity:0.5;}
.so-tl-icon-btn{position:absolute;top:50%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:2px;background:none;border:none;cursor:pointer;padding:2px;z-index:25;transition:transform 150ms;}
.so-tl-icon-btn:hover{transform:translate(-50%,-60%);z-index:30;}
.so-tl-icon-btn:focus{outline:none;z-index:30;}
.so-tl-icon-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:1.5;fill:none;color:var(--status-color,var(--muted));transition:color 150ms;}
.so-tl-icon-btn:hover svg,.so-tl-icon-btn:focus svg{color:var(--gold);}
.so-tl-icon-btn.so-active svg{color:var(--gold);filter:drop-shadow(0 0 4px rgba(248,200,48,0.7));transform:scale(1.2);}
@keyframes so-tl-reel-pulse{0%,100%{color:#ef4444;filter:drop-shadow(0 0 2px rgba(239,68,68,0.3));}50%{color:#fca5a5;filter:drop-shadow(0 0 8px rgba(239,68,68,0.9));}}
.so-tl-icon-btn.so-tl-reel-flash svg{animation:so-tl-reel-pulse 900ms ease-in-out infinite;color:#ef4444;}
.so-tl-reel-check{position:absolute;top:-4px;right:-6px;font-size:10px;color:#22c55e;font-weight:700;line-height:1;text-shadow:0 0 3px rgba(34,197,94,0.6);}
@keyframes so-tl-reel-empty-pulse{0%,100%{border-color:#ef4444;color:#ef4444;box-shadow:0 0 2px rgba(239,68,68,0.3);}50%{border-color:#fca5a5;color:#fca5a5;box-shadow:0 0 10px rgba(239,68,68,0.8);}}
.so-tl-reel-empty{position:absolute;top:50%;transform:translate(-50%,-50%);display:flex;align-items:center;justify-content:center;width:22px;height:22px;border:2px dashed #ef4444;border-radius:4px;background:rgba(239,68,68,0.08);color:#ef4444;font-size:13px;font-weight:700;line-height:1;cursor:help;z-index:26;animation:so-tl-reel-empty-pulse 900ms ease-in-out infinite;user-select:none;}
.so-tl-reel-empty:hover{background:rgba(239,68,68,0.18);}
.so-tl-icon-btn.so-tl-icon-empty{--status-color:#ef4444;}
.so-tl-icon-btn.so-tl-icon-empty svg{animation:so-tl-reel-pulse 900ms ease-in-out infinite;color:#ef4444;stroke-dasharray:3 3;}
.so-tl-icon-btn.so-tl-reel-overdue svg{color:#c91e1e;}
.so-tl-reel-state-lbl{position:absolute;bottom:-13px;left:50%;transform:translateX(-50%);background:#ef4444;color:#fff;font-family:var(--font-m);font-size:7px;font-weight:700;letter-spacing:0.04em;padding:1px 4px;border-radius:2px;white-space:nowrap;pointer-events:none;line-height:1.3;}
.so-tl-icon-btn.so-tl-reel-overdue .so-tl-reel-state-lbl{background:#c91e1e;}
@keyframes so-tl-reel-lbl-pulse{0%,100%{opacity:1;}50%{opacity:0.65;}}
.so-tl-icon-btn.so-tl-reel-flash .so-tl-reel-state-lbl{animation:so-tl-reel-lbl-pulse 900ms ease-in-out infinite;}
.so-tl-chip{position:absolute;top:50%;transform:translate(-50%,-50%);background:var(--surface-alt);border:1px solid var(--border);border-radius:10px;padding:1px 8px;font-family:var(--font-m);font-size:10px;color:var(--muted);cursor:pointer;white-space:nowrap;z-index:5;}
.so-tl-chip:hover{border-color:var(--gold);color:var(--text);}
.so-tl-now-line{position:absolute;top:0;bottom:0;width:2px;background:var(--grad);z-index:20;pointer-events:none;box-shadow:0 0 6px 2px rgba(248,200,48,0.45);}
.so-tl-now-lbl{position:absolute;top:3px;left:50%;transform:translateX(-50%);font-family:var(--font-m);font-size:9px;color:var(--gold);white-space:nowrap;background:var(--surface-alt);padding:1px 4px;border-radius:2px;border:1px solid rgba(248,200,48,0.3);z-index:21;}
.so-tl-bru-empty{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-family:var(--font-m);font-size:10px;color:var(--muted);white-space:nowrap;pointer-events:none;opacity:0.7;}
.so-tl-bru-badge{position:absolute;top:-3px;right:-3px;width:7px;height:7px;border-radius:50%;background:var(--gold);pointer-events:none;}
.so-preview{position:relative;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);display:flex;flex-direction:column;height:100%;max-height:100%;overflow-y:auto;min-width:0;min-height:0;box-shadow:var(--glow);}
.so-preview::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--grad);opacity:0.7;pointer-events:none;z-index:10;}
.so-preview::-webkit-scrollbar{width:4px;}.so-preview::-webkit-scrollbar-track{background:transparent;}.so-preview::-webkit-scrollbar-thumb{background:var(--muted);border-radius:2px;opacity:0.5;}
@media(max-width:1279px){.so-preview{height:auto;max-height:420px;}}
.so-pv-media{position:relative;width:100%;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden;}
.so-pv-media img,.so-pv-media video{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block;}
.so-pv-media.aspect-9-16{aspect-ratio:9/16;max-height:60vh;}
.so-pv-media.aspect-16-9{aspect-ratio:16/9;}
.so-pv-media.pv-carousel-wrap{aspect-ratio:9/16;max-height:60vh;background:#000;display:block;overflow:hidden;position:relative;}
.pv-carousel{display:flex;flex-direction:row;height:100%;width:100%;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x mandatory;scrollbar-width:none;scroll-behavior:smooth;}
.pv-carousel::-webkit-scrollbar{display:none;}
.pv-carousel-slide{position:relative;flex:0 0 100%;width:100%;height:100%;scroll-snap-align:center;scroll-snap-stop:always;background:#000;display:flex;align-items:center;justify-content:center;}
.pv-carousel-slide img{display:block;max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;}
.pv-carousel-num{position:absolute;top:8px;right:8px;font-family:var(--font-m);font-size:11px;background:rgba(0,0,0,0.65);color:#fff;padding:3px 8px;border-radius:10px;letter-spacing:.3px;z-index:2;}
.pv-carousel-nav{position:absolute;top:50%;transform:translateY(-50%);width:32px;height:32px;border-radius:50%;background:rgba(0,0,0,0.55);color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:18px;line-height:1;z-index:3;transition:background .15s,opacity .15s;user-select:none;}
.pv-carousel-nav:hover{background:rgba(0,0,0,0.8);}
.pv-carousel-nav[disabled]{opacity:0.25;cursor:default;}
.pv-carousel-nav.prev{left:8px;}
.pv-carousel-nav.next{right:8px;}
.pv-carousel-dots{position:absolute;bottom:10px;left:0;right:0;display:flex;justify-content:center;gap:5px;z-index:2;pointer-events:none;}
.pv-carousel-dot{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,0.5);transition:background .15s,transform .15s;}
.pv-carousel-dot.active{background:#fff;transform:scale(1.25);}
.so-pv-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:14px;padding:32px;text-align:center;color:var(--muted);font-size:13px;line-height:1.5;}
.so-pv-empty svg{opacity:0.18;}
.so-pv-skel{flex:1;padding:16px;display:flex;flex-direction:column;gap:10px;}
.skel-b{background:var(--surface-alt);border-radius:4px;animation:skel-p 1.2s ease-in-out infinite alternate;}
@keyframes skel-p{from{opacity:0.4;}to{opacity:0.8;}}
.so-pv-meta{font-family:var(--font-m);font-size:11px;color:var(--muted);display:flex;flex-wrap:wrap;gap:6px;padding:8px 12px;border-bottom:1px solid var(--border);}
.so-pv-chip{background:var(--surface-alt);border:1px solid var(--border);border-radius:10px;padding:1px 8px;}
.so-pv-body{flex:1;overflow-y:auto;padding:14px;}
.so-pv-actions{padding:10px 12px;border-top:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap;}
.so-pv-actions button,.so-pv-actions a{font-family:var(--font-m);font-size:11px;background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:4px;padding:3px 10px;cursor:pointer;text-decoration:none;transition:color 150ms,border-color 150ms;}
.so-pv-actions button:hover,.so-pv-actions a:hover{color:var(--text);border-color:var(--gold);}
.so-reel-upload-panel{display:flex;flex-direction:column;gap:14px;padding:16px;}
.so-rup-header{display:flex;align-items:center;gap:10px;font-size:14px;font-weight:600;color:var(--text);}
.so-rup-chip{background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.35);border-radius:10px;padding:2px 10px;font-size:11px;font-weight:600;letter-spacing:.03em;}
.so-rup-meta{font-size:12px;color:var(--muted);}
.so-rup-kit-btn button{width:100%;background:var(--surface-alt);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:9px 14px;font-size:12px;font-family:var(--font-m);cursor:pointer;text-align:left;transition:border-color 150ms,background 150ms;}
.so-rup-kit-btn button:hover{border-color:var(--gold);background:rgba(248,200,48,0.06);}
.so-rup-drop{border:2px dashed rgba(248,200,48,0.4);border-radius:8px;padding:28px 16px;text-align:center;cursor:pointer;transition:all .18s ease;color:var(--gold);}
.so-rup-drop:hover,.so-rup-drop.dragover{background:rgba(248,200,48,0.06);border-color:var(--gold);}
.so-rup-drop svg{display:block;margin:0 auto 10px;opacity:.7;}
.so-rup-drop-text{font-size:12px;color:var(--muted);}
.so-rup-browse{color:var(--gold);cursor:pointer;text-decoration:underline;}
.so-rup-status{font-size:12px;padding:0 2px;}
.so-rup-status.success{color:#22c55e;}
.so-rup-status.error{color:#ef4444;}
.so-rup-uploading{opacity:.55;pointer-events:none;}
/* ── Platform-native preview frames ─────────────────────────── */
.pv-frame{max-width:420px;margin:0 auto;font-size:13px;line-height:1.5;color:var(--text);}
.pv-frame-hdr{display:flex;align-items:center;gap:10px;padding:10px 12px;}
.pv-avatar{width:32px;height:32px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-family:var(--font-d);font-weight:700;font-size:13px;color:#fff;}
.pv-handle{font-family:var(--font-d);font-weight:600;font-size:13px;color:var(--text);}
.pv-sub{font-family:var(--font-m);font-size:11px;color:var(--muted);}
.pv-verified{display:inline-block;color:#3897f0;font-size:11px;margin-left:3px;vertical-align:top;line-height:1.2;}

/* Instagram */
.pv-ig-frame{background:#000;border:1px solid #262626;border-radius:8px;overflow:hidden;color:#f5f5f5;}
.pv-ig-hdr{display:flex;align-items:center;gap:10px;padding:10px 12px;border-bottom:1px solid #1a1a1a;}
.pv-ig-avatar{width:32px;height:32px;border-radius:50%;background:linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888);padding:2px;flex-shrink:0;}
.pv-ig-avatar-inner{width:100%;height:100%;border-radius:50%;background:#0a0a0a;display:flex;align-items:center;justify-content:center;font-family:var(--font-d);font-weight:700;font-size:12px;color:#f5f5f5;}
.pv-ig-handle{font-family:var(--font-d);font-weight:600;font-size:13px;color:#f5f5f5;flex:1;}
.pv-ig-more{color:#f5f5f5;font-size:18px;letter-spacing:2px;}
.pv-ig-media{position:relative;background:#000;}
.pv-ig-media.aspect-1-1{aspect-ratio:1/1;}
.pv-ig-media.aspect-4-5{aspect-ratio:4/5;}
.pv-ig-media.aspect-9-16{aspect-ratio:9/16;max-height:70vh;}
.pv-ig-media img,.pv-ig-media video{display:block;width:100%;height:100%;object-fit:cover;}
.pv-ig-actions{display:flex;align-items:center;gap:14px;padding:10px 12px;font-size:22px;color:#f5f5f5;}
.pv-ig-actions .sp{flex:1;}
.pv-ig-actions svg{width:24px;height:24px;stroke:#f5f5f5;stroke-width:2;fill:none;cursor:pointer;}
.pv-ig-likes{padding:0 12px 4px;font-family:var(--font-d);font-weight:600;font-size:13px;color:#f5f5f5;}
.pv-ig-caption{padding:4px 12px;font-size:13px;color:#f5f5f5;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;}
.pv-ig-caption b{font-weight:600;margin-right:4px;}
.pv-ig-caption .more{color:#8e8e8e;cursor:pointer;}
.pv-ig-tags{padding:0 12px 2px;font-size:13px;color:#e0f1ff;}
.pv-ig-tags a,.pv-ig-tags span{color:#e0f1ff;}
.pv-ig-comments{padding:4px 12px;font-size:13px;color:#8e8e8e;cursor:pointer;}
.pv-ig-time{padding:2px 12px 12px;font-family:var(--font-m);font-size:10px;color:#8e8e8e;text-transform:uppercase;letter-spacing:.3px;}
.pv-ig-slide-cap{position:absolute;left:12px;right:60px;bottom:12px;padding:8px 10px;background:rgba(0,0,0,0.55);border-radius:6px;font-size:12px;line-height:1.4;color:#fff;backdrop-filter:blur(4px);max-height:40%;overflow-y:auto;z-index:2;pointer-events:none;white-space:pre-wrap;}
.pv-ig-dots-top{position:absolute;top:10px;right:10px;display:flex;gap:3px;z-index:3;}
.pv-ig-dots-top .d{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,0.55);transition:background .15s,transform .15s;}
.pv-ig-dots-top .d.active{background:#fff;transform:scale(1.3);}
.pv-ig-count{position:absolute;top:10px;right:10px;padding:3px 9px;background:rgba(38,38,38,0.85);color:#fff;border-radius:12px;font-family:var(--font-m);font-size:11px;font-weight:600;z-index:3;}

/* TikTok */
.pv-tt-frame{position:relative;background:#000;border-radius:12px;overflow:hidden;aspect-ratio:9/16;max-height:70vh;color:#fff;}
.pv-tt-frame video,.pv-tt-frame img{width:100%;height:100%;object-fit:cover;display:block;}
.pv-tt-top{position:absolute;top:0;left:0;right:0;padding:12px 14px;display:flex;justify-content:center;gap:18px;z-index:3;background:linear-gradient(to bottom,rgba(0,0,0,0.35),transparent);font-family:var(--font-d);font-weight:600;font-size:14px;color:#fff;}
.pv-tt-top .tab{opacity:0.6;}
.pv-tt-top .tab.active{opacity:1;border-bottom:2px solid #fff;padding-bottom:2px;}
.pv-tt-side{position:absolute;right:8px;bottom:90px;display:flex;flex-direction:column;gap:18px;align-items:center;z-index:3;}
.pv-tt-side-item{display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;}
.pv-tt-side-item svg{width:32px;height:32px;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.6));}
.pv-tt-side-item .n{font-family:var(--font-d);font-weight:600;font-size:11px;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.6);}
.pv-tt-profile{width:46px;height:46px;border-radius:50%;border:2px solid #fff;background:#111;position:relative;display:flex;align-items:center;justify-content:center;font-family:var(--font-d);font-weight:700;color:#fff;}
.pv-tt-follow{position:absolute;bottom:-10px;left:50%;transform:translateX(-50%);width:20px;height:20px;border-radius:50%;background:#ff0050;color:#fff;display:flex;align-items:center;justify-content:center;font-size:16px;line-height:1;font-weight:700;}
.pv-tt-disc{width:46px;height:46px;border-radius:50%;background:radial-gradient(circle,#333 20%,#000 22%,#000 60%,#333 62%);display:flex;align-items:center;justify-content:center;animation:tt-spin 5s linear infinite;}
@keyframes tt-spin{to{transform:rotate(360deg);}}
.pv-tt-bottom{position:absolute;left:0;right:70px;bottom:0;padding:14px 16px 18px;z-index:3;background:linear-gradient(to top,rgba(0,0,0,0.55),transparent);}
.pv-tt-handle{font-family:var(--font-d);font-weight:700;font-size:15px;color:#fff;margin-bottom:6px;text-shadow:0 1px 2px rgba(0,0,0,0.6);}
.pv-tt-cap{font-size:13px;line-height:1.45;color:#fff;margin-bottom:8px;text-shadow:0 1px 2px rgba(0,0,0,0.6);white-space:pre-wrap;word-wrap:break-word;max-height:8em;overflow-y:auto;}
.pv-tt-music{display:flex;align-items:center;gap:6px;font-family:var(--font-m);font-size:11px;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.6);}

/* Telegram */
.pv-tg-frame{background:#17212b;border-radius:10px;overflow:hidden;border:1px solid #1f2c38;}
.pv-tg-hdr{display:flex;align-items:center;gap:10px;padding:10px 12px;background:#17212b;border-bottom:1px solid #0e1621;}
.pv-tg-hdr .pv-avatar{background:#3390ec;}
.pv-tg-name{font-family:var(--font-d);font-weight:600;font-size:14px;color:#fff;}
.pv-tg-sub{font-family:var(--font-m);font-size:11px;color:#7d8b98;}
.pv-tg-bubble{background:#182533;margin:10px 10px 12px;border-radius:10px;padding:4px 4px 8px;box-shadow:0 1px 2px rgba(0,0,0,0.35);position:relative;}
.pv-tg-bubble-media{border-radius:8px;overflow:hidden;background:#000;}
.pv-tg-bubble-media img,.pv-tg-bubble-media video{display:block;width:100%;max-height:420px;object-fit:cover;}
.pv-tg-bubble-text{padding:8px 10px 2px;font-size:14px;line-height:1.45;color:#fff;white-space:pre-wrap;word-wrap:break-word;}
.pv-tg-bubble-text b{font-weight:600;}
.pv-tg-bubble-text a{color:#6ab3f3;}
.pv-tg-meta{display:flex;justify-content:flex-end;align-items:center;gap:6px;padding:4px 12px 2px;font-family:var(--font-m);font-size:11px;color:#7d8b98;}
.pv-tg-meta .views::before{content:"\1F441";margin-right:3px;}
.pv-tg-reactions{display:flex;gap:6px;padding:4px 12px 8px;flex-wrap:wrap;}
.pv-tg-react{background:rgba(51,144,236,0.15);border:1px solid rgba(51,144,236,0.35);border-radius:12px;padding:2px 8px;font-family:var(--font-m);font-size:11px;color:#6ab3f3;}

/* WhatsApp */
.pv-wa-frame{background:#0b141a;border-radius:10px;overflow:hidden;border:1px solid #1f2c33;}
.pv-wa-hdr{display:flex;align-items:center;gap:10px;padding:10px 12px;background:#202c33;}
.pv-wa-hdr .pv-avatar{background:#00a884;}
.pv-wa-name{font-family:var(--font-d);font-weight:600;font-size:14px;color:#e9edef;}
.pv-wa-sub{font-family:var(--font-m);font-size:11px;color:#8696a0;}
.pv-wa-body{padding:12px;background:#0b141a;background-image:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(255,255,255,0.01) 2px,rgba(255,255,255,0.01) 3px);min-height:120px;}
.pv-wa-bubble{background:#005c4b;max-width:85%;margin-left:auto;border-radius:8px;padding:3px 3px 6px;box-shadow:0 1px 1px rgba(0,0,0,0.35);position:relative;}
.pv-wa-bubble::after{content:"";position:absolute;right:-6px;top:0;width:0;height:0;border-style:solid;border-width:0 0 8px 8px;border-color:transparent transparent transparent #005c4b;}
.pv-wa-bubble-media{border-radius:6px;overflow:hidden;background:#000;}
.pv-wa-bubble-media img,.pv-wa-bubble-media video{display:block;width:100%;max-height:360px;object-fit:cover;}
.pv-wa-bubble-text{padding:6px 8px 0;font-size:14px;line-height:1.4;color:#e9edef;white-space:pre-wrap;word-wrap:break-word;}
.pv-wa-meta{display:flex;justify-content:flex-end;align-items:center;gap:4px;padding:2px 8px 2px;font-family:var(--font-m);font-size:10px;color:#8696a0;}
.pv-wa-ticks{color:#53bdeb;letter-spacing:-2px;}

/* LinkedIn */
.pv-li-frame{background:#1b1f23;border-radius:8px;overflow:hidden;border:1px solid #38434f;color:#e7e9ea;}
.pv-li-hdr{display:flex;align-items:flex-start;gap:10px;padding:12px 16px 10px;}
.pv-li-hdr .pv-avatar{background:#0a66c2;border-radius:4px;}
.pv-li-name{font-family:var(--font-d);font-weight:600;font-size:14px;color:#e7e9ea;}
.pv-li-sub{font-family:var(--font-m);font-size:11px;color:#b0b7bd;line-height:1.4;}
.pv-li-follow{margin-left:auto;color:#70b5f9;font-family:var(--font-m);font-size:12px;font-weight:600;padding:4px 10px;border:1px solid #70b5f9;border-radius:16px;}
.pv-li-text{padding:0 16px 10px;font-size:14px;line-height:1.5;color:#e7e9ea;white-space:pre-wrap;word-wrap:break-word;}
.pv-li-text .more{color:#b0b7bd;cursor:pointer;}
.pv-li-media{background:#000;}
.pv-li-media img,.pv-li-media video{display:block;width:100%;max-height:460px;object-fit:cover;}
.pv-li-stats{display:flex;gap:6px;padding:8px 16px 4px;font-family:var(--font-m);font-size:11px;color:#b0b7bd;border-bottom:1px solid #38434f;}
.pv-li-actions{display:flex;padding:4px 8px;border-top:0;}
.pv-li-action{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;padding:8px;font-family:var(--font-d);font-weight:600;font-size:12px;color:#b0b7bd;cursor:pointer;border-radius:4px;}
.pv-li-action:hover{background:#2a3137;}
.pv-li-action svg{width:20px;height:20px;stroke:#b0b7bd;stroke-width:1.8;fill:none;}

/* Generic fallback */
.pv-gen{background:var(--surface-alt);border:1px solid var(--border);border-radius:10px;padding:12px 14px;font-size:13px;line-height:1.6;color:var(--text);white-space:pre-wrap;}
.so-tip{position:fixed;background:var(--surface-alt);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-family:var(--font-m);font-size:11px;color:var(--text);z-index:9999;pointer-events:none;max-width:240px;line-height:1.4;box-shadow:var(--glow);display:none;}
.so-tip-thumb{display:block;width:96px;height:96px;object-fit:cover;border-radius:4px;margin-bottom:6px;background:var(--surface);}
.so-chip-stack{display:flex;flex-direction:column;gap:6px;padding:4px 0;}
.so-chip-stack-item{display:flex;align-items:center;gap:10px;padding:9px 12px;background:var(--surface-alt);border:1px solid var(--border);border-radius:6px;cursor:pointer;text-align:left;width:100%;transition:border-color 150ms,background 150ms;}
.so-chip-stack-item:hover{border-color:var(--gold);background:var(--surface);}
.so-chip-stack-ch{font-family:var(--font-m);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:var(--gold);flex-shrink:0;min-width:80px;}
.so-chip-stack-time{font-family:var(--font-m);font-size:11px;color:var(--muted);flex-shrink:0;min-width:38px;}
.so-chip-stack-title{font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;}
.so-warn-banner{background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.28);border-radius:6px;color:var(--amber);font-family:var(--font-m);font-size:12px;padding:6px 10px;margin-bottom:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;line-height:1.4;}
.so-warn-banner .so-fb-count{color:var(--amber);}
.so-warn-banner .so-fb-item{background:rgba(245,158,11,0.10);border-color:rgba(245,158,11,0.28);}
.so-warn-banner .so-fb-item-dismiss{color:var(--amber);}
.so-warn-banner .so-fb-item-dismiss:hover{background:rgba(245,158,11,0.22);}
.pv-hashtags{font-family:var(--font-m);font-size:11px;color:#58a6ff;margin-top:8px;line-height:1.6;}
.pv-caption-label{font-family:var(--font-m);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px;opacity:0.7;}
</style>"""

    js = (
        """<script>
(function(){
var ICONS={
'message-circle':'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
'newspaper':'<path d="M4 3h13a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M8 7h8M8 11h8M8 15h4"/>',
'sun':'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
'diamond':'<path d="M2.7 10.3a2.41 2.41 0 0 0 0 3.41l7.59 7.59a2.41 2.41 0 0 0 3.41 0l7.59-7.59a2.41 2.41 0 0 0 0-3.41l-7.59-7.59a2.41 2.41 0 0 0-3.41 0Z"/>',
'trophy':'<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2z"/>',
'eye':'<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
'message-square-more':'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',
'bell':'<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
'play-circle':'<circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/>',
'layers':'<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9A1 1 0 0 0 21.4 6.08z"/><path d="m22 12.65-8.58 3.91a2 2 0 0 1-1.66 0L3.42 12.65"/><path d="m22 17.65-8.58 3.91a2 2 0 0 1-1.66 0L3.42 17.65"/>',
'circle':'<circle cx="12" cy="12" r="10"/>',
'image':'<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
'bot':'<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2M22 14h-2M15 13v2M9 13v2"/>',
'at-sign':'<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"/>',
'briefcase':'<rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
'book-open':'<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
'message-square':'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
'message-square-quote':'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 10a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm0 0v2"/><path d="M12 10a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm0 0v2"/>',
'help-circle':'<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>'
};
function svgI(name){var p=ICONS[name]||ICONS['help-circle'];return'<svg viewBox="0 0 24 24" aria-hidden="true">'+p+'</svg>';}

var _data=null,_currentDay=null,_dayOffset=0,_todayStr=null,_activePostId=null,_tipEl=null;

var SO_INIT="""
        + _tl_json
        + """;
_data=SO_INIT;_currentDay=SO_INIT.day;_todayStr=SO_INIT.day;

// ── Status helpers ────────────────────────────────────────────────────
var ST_COLOR={'posted':'#22c55e','published':'#22c55e','done':'#22c55e','complete':'#22c55e',
  'failed':'#ef4444','error':'#ef4444','blocked':'#ef4444','skipped':'#6b7280','archived':'#6b7280'};
var ST_MARK={'posted':'✓','published':'✓','done':'✓','complete':'✓',
  'failed':'!','error':'!','blocked':'!','skipped':'×','archived':'×'};
function stColor(s){return ST_COLOR[s]||'#f59e0b';}
function stMark(s){return ST_MARK[s]||'○';}

// ── DOM ready ─────────────────────────────────────────────────────────
function soInit(){
  _tipEl=document.getElementById('so-tip');
  renderTimeline(SO_INIT);
  updateNowLine();
  updateDayPicker();
  setupDayPicker();
  setupKeyboard();
  // Force live API refresh on first paint so stale SWR-cached SO_INIT
  // (e.g. yesterday's non-drip-day payload served today) is replaced with
  // fresh data within ~300ms instead of waiting a full 60s interval.
  setTimeout(refreshTimeline,0);
  setInterval(updateNowLine,60000);
  setInterval(refreshTimeline,60000);
  // Queue: initial + interval load
  fetchQueue();
  setInterval(fetchQueue,60000);
}
if(document.readyState!=='loading'){soInit();}else{document.addEventListener('DOMContentLoaded',soInit);}

// ── Day picker ────────────────────────────────────────────────────────
function updateDayPicker(){
  var lbl=document.getElementById('so-day-lbl');
  var nb=document.getElementById('so-day-next');
  var pb=document.getElementById('so-day-prev');
  if(lbl)lbl.textContent=_dayOffset===0?'Today':(_dayOffset===-1?'Yesterday':_currentDay);
  if(nb)nb.disabled=_dayOffset>=0;
  if(pb)pb.disabled=_dayOffset<=-7;
}
function setupDayPicker(){
  var p=document.getElementById('so-day-prev'),n=document.getElementById('so-day-next');
  if(p)p.addEventListener('click',function(){if(_dayOffset>-7){_dayOffset--;_currentDay=_offsetDay(_todayStr,_dayOffset);updateDayPicker();refreshTimeline();}});
  if(n)n.addEventListener('click',function(){if(_dayOffset<0){_dayOffset++;_currentDay=_offsetDay(_todayStr,_dayOffset);updateDayPicker();refreshTimeline();}});
}
function _offsetDay(base,off){var d=new Date(base+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+off);return d.toISOString().slice(0,10);}

// ── Refresh ───────────────────────────────────────────────────────────
function refreshTimeline(){
  fetch('/admin/api/social-ops/timeline?day='+_currentDay,{credentials:'same-origin'})
    .then(function(r){if(!r.ok)throw 0;return r.json();})
    .then(function(d){_data=d;renderTimeline(d);updateNowLine();if(d.kpis)updateKPIs(d.kpis);clearStale();})
    .catch(showStale);
}
function updateKPIs(k){
  var m={'kpi-posted':k.posted_24h,'kpi-pending':k.pending,'kpi-failed':k.failed_24h,'kpi-queue':k.queue_depth,'kpi-overdue':k.overdue_queue_count,'kpi-pastdue':k.past_due,'kpi-unscheduled':k.unscheduled};
  for(var id in m){var el=document.getElementById(id);if(el&&m[id]!==undefined)el.textContent=m[id];}
}
function showStale(){var e=document.getElementById('so-stale-badge');if(e)e.style.display='';}
function clearStale(){var e=document.getElementById('so-stale-badge');if(e)e.style.display='none';}

// ── Now line ──────────────────────────────────────────────────────────
function updateNowLine(){
  var nl=document.getElementById('so-tl-now');
  if(_dayOffset!==0){if(nl)nl.style.display='none';return;}
  var now=new Date(),uh=now.getUTCHours(),um=now.getUTCMinutes();
  var sm=(uh*60+um+120)%1440;
  var cont=document.getElementById('so-tl-content');
  if(!cont||!nl)return;
  var lw=140,tw=cont.offsetWidth;
  if(tw<=lw)return;
  var x=lw+(sm/1440)*(tw-lw);
  nl.style.left=x+'px';
  nl.style.height=cont.offsetHeight+'px';
  nl.style.display='block';
  var hh=String(Math.floor(sm/60)).padStart(2,'0'),mm=String(sm%60).padStart(2,'0');
  var ll=document.getElementById('so-tl-now-lbl');
  if(ll)ll.textContent='now '+hh+':'+mm;
}

// ── Timeline rendering ────────────────────────────────────────────────
function renderTimeline(data){
  var cont=document.getElementById('so-tl-rows');
  if(!cont)return;
  cont.innerHTML=(data.channels||[]).map(renderRow).join('');
  cont.querySelectorAll('[data-post-id]').forEach(function(btn){
    btn.addEventListener('click',function(){loadPreview(btn.dataset.postId);setActive(btn);});
    btn.addEventListener('mouseenter',function(e){showTip(e,btn.dataset);});
    btn.addEventListener('mouseleave',hideTip);
    btn.addEventListener('focus',function(e){showTip(e,btn.dataset);});
    btn.addEventListener('blur',hideTip);
  });
  cont.querySelectorAll('[data-chip]').forEach(function(chip){
    chip.addEventListener('click',function(){
      try{var posts=JSON.parse(chip.dataset.chip);if(posts.length)loadChipStack(posts);}catch(e){}
    });
    chip.addEventListener('mouseenter',function(e){
      try{var posts=JSON.parse(chip.dataset.chip);showChipTip(e,posts);}catch(_){}
    });
    chip.addEventListener('mouseleave',hideTip);
    chip.addEventListener('focus',function(e){
      try{var posts=JSON.parse(chip.dataset.chip);showChipTip(e,posts);}catch(_){}
    });
    chip.addEventListener('blur',hideTip);
    chip.addEventListener('keydown',function(e){
      if(e.key==='Enter'){e.preventDefault();try{var posts=JSON.parse(chip.dataset.chip);if(posts.length)loadChipStack(posts);}catch(_){}}
    });
  });
  updateNowLine();
}
function setActive(btn){
  document.querySelectorAll('.so-tl-icon-btn').forEach(function(b){b.classList.remove('so-active');});
  if(btn)btn.classList.add('so-active');
}
function resolveCollisions(posts){
  if(!posts||!posts.length)return[];
  var s=posts.slice().sort(function(a,b){return a.mins-b.mins;}),res=[],i=0;
  while(i<s.length){
    var g=[s[i]],j=i+1;
    while(j<s.length&&s[j].mins-s[i].mins<30)g.push(s[j++]);
    if(g.length===1){res.push({p:g[0],off:0,chip:false});}
    else if(g.length===2){res.push({p:g[0],off:-9,chip:false});res.push({p:g[1],off:9,chip:false});}
    else{res.push({p:g[0],off:0,chip:true,n:g.length,grp:g});}
    i=j;
  }
  return res;
}
function renderRow(ch,ri){
  var its=resolveCollisions(ch.posts);
  var emptyLabel=ch.bru_empty?'<div class="so-tl-bru-empty">No B.R.U. videos queued</div>':'';
  var icons=its.map(function(it,ci){
    var p=it.p,pct=(p.mins/1440*100).toFixed(3)+'%';
    if(it.chip){
      var cp=JSON.stringify(it.grp.map(function(g){return{id:g.id,title:g.title,ch:g.ch_lbl,sched:g.sched};})).replace(/"/g,'&quot;');
      return '<button class="so-tl-chip" style="left:'+pct+'" data-chip="'+cp+'" tabindex="0" aria-label="'+it.n+' posts">+'+it.n+'</button>';
    }
    var off=it.off?'margin-top:'+it.off+'px;':'';
    var al=eA([p.type||'Post',ch.label,'scheduled '+p.sched,p.status||'unknown'].join(' · '));
    // DASH-POLISH-STORIES-01 / AC1: empty-slot flash (distinct from overdue).
    if(p.reel_state==='empty'){
      var emTitle=eA(p.title||"No IG Reel queued for today's 19:00 slot");
      var emSvg=p.glyph||svgI(p.icon||'help-circle');
      return '<button class="so-tl-icon-btn so-tl-icon-empty" style="left:'+pct+'" title="'+emTitle+'" aria-label="'+emTitle+'" role="gridcell" tabindex="-1">'+emSvg+'</button>';
    }
    var badge=p.bru_mismatch?'<span class="so-tl-bru-badge"></span>':'';
    if(p.reel_state==='published')badge+='<span class="so-tl-reel-check" aria-hidden="true">✓</span>';
    var cls='so-tl-icon-btn';
    if(p.reel_state==='needs_upload')cls+=' so-tl-reel-flash';
    else if(p.reel_state==='overdue')cls+=' so-tl-reel-overdue';
    var reelTooltip=p.reel_state==='needs_upload'?'Reel kit needed — not uploaded yet':p.reel_state==='overdue'?'Reel past scheduled time — missed':'';
    var reelLblText=p.reel_state==='needs_upload'?'NEEDS UPLOAD':p.reel_state==='overdue'?'MISSED':'';
    var reelLblBadge=reelLblText?'<span class="so-tl-reel-state-lbl">'+reelLblText+'</span>':'';
    return '<button class="'+cls+'" style="left:'+pct+';'+off+';--status-color:'+stColor(p.status)+'" '+
      'data-post-id="'+eA(p.id)+'" data-row-idx="'+ri+'" data-col-idx="'+ci+'" '+
      'data-title="'+eA(p.title)+'" data-sched="'+eA(p.sched)+'" data-sched-full="'+eA(p.sched_full||'')+'" data-status="'+eA(p.status)+'" '+
      'data-ch="'+eA(ch.label)+'" data-type="'+eA(p.type)+'" data-asset-url="'+eA(p.asset_url||'')+'" '+
      'data-reel-state="'+eA(p.reel_state||'')+'" '+
      (reelTooltip?'title="'+eA(reelTooltip)+'" ':'')+
      'aria-label="'+al+'" tabindex="-1" role="gridcell">'+
      (p.glyph||svgI(p.icon||'help-circle'))+badge+reelLblBadge+
      '</button>';
  }).join('');
  return '<div class="so-tl-row" role="row" aria-label="'+eA(ch.label)+'" data-row-idx="'+ri+'" tabindex="0">'+
    '<div class="so-tl-row-lbl" style="color:'+eA(ch.color||'')+'">'+(ch.icon?'<span class="so-tl-ch-icon">'+ch.icon+'</span>':'')+eH(ch.label)+'</div>'+
    '<div class="so-tl-bar" id="so-bar-'+ri+'">'+emptyLabel+
    '<div class="so-tl-gl" style="left:0%"></div>'+
    '<div class="so-tl-gl so-tl-gl-mid" style="left:12.5%"></div>'+
    '<div class="so-tl-gl" style="left:25%"></div>'+
    '<div class="so-tl-gl so-tl-gl-mid" style="left:37.5%"></div>'+
    '<div class="so-tl-gl" style="left:50%"></div>'+
    '<div class="so-tl-gl so-tl-gl-mid" style="left:62.5%"></div>'+
    '<div class="so-tl-gl" style="left:75%"></div>'+
    '<div class="so-tl-gl so-tl-gl-mid" style="left:87.5%"></div>'+
    icons+'</div></div>';
}

// ── Keyboard navigation ───────────────────────────────────────────────
function setupKeyboard(){
  document.addEventListener('keydown',function(e){
    var a=document.activeElement;if(!a)return;
    var isIcon=!!(a.dataset&&a.dataset.postId);
    var isRow=!isIcon&&a.classList.contains('so-tl-row');
    if(!isIcon&&!isRow)return;
    var ri=parseInt((isIcon?a:a).dataset.rowIdx||'0');
    var ci=parseInt((isIcon?a.dataset.colIdx:'-1')||'0');
    if(isRow){
      if(e.key==='ArrowDown'){e.preventDefault();focusRow(ri+1);}
      else if(e.key==='ArrowUp'){e.preventDefault();focusRow(ri-1);}
      else if(e.key==='ArrowRight'||e.key==='Enter'){e.preventDefault();focusIcon(ri,0);}
    } else {
      if(e.key==='ArrowLeft'){e.preventDefault();focusIcon(ri,ci-1);}
      else if(e.key==='ArrowRight'){e.preventDefault();focusIcon(ri,ci+1);}
      else if(e.key==='ArrowUp'){e.preventDefault();focusRow(ri-1);}
      else if(e.key==='ArrowDown'){e.preventDefault();focusRow(ri+1);}
      else if(e.key==='Enter'){e.preventDefault();loadPreview(a.dataset.postId);setActive(a);}
      else if(e.key==='Escape'){e.preventDefault();closePreview();focusRow(ri);}
    }
  });
}
function focusRow(idx){var rows=document.querySelectorAll('[role="row"]');if(idx>=0&&idx<rows.length)rows[idx].focus();}
function focusIcon(ri,ci){
  var bar=document.getElementById('so-bar-'+ri);if(!bar)return;
  var icons=bar.querySelectorAll('[data-post-id]');
  if(!icons.length){focusRow(ri);return;}
  icons[Math.max(0,Math.min(ci,icons.length-1))].focus();
}

// ── Tooltip ───────────────────────────────────────────────────────────
function showTip(e,ds){
  if(!_tipEl)return;
  var au=ds.assetUrl||'';
  var imgHtml=au&&au.indexOf('://')>0?'<img src="'+eA(au)+'" class="so-tip-thumb" loading="lazy" onerror="this.remove()" alt="">':'';
  _tipEl.innerHTML=imgHtml+[ds.title?eH(ds.title):'(no title)',[ds.ch,ds.type].filter(Boolean).join(' \u00b7 '),eH(ds.ch||'?')+' \u2014 '+(ds.schedFull?eH(ds.schedFull):ds.sched||'?')+' SAST'].join('<br>');
  _tipEl.style.display='block';
  _tipEl.style.left=(e.clientX+12)+'px';_tipEl.style.top=(e.clientY-8)+'px';
}
function hideTip(){if(_tipEl)_tipEl.style.display='none';}
function showChipTip(e,posts){
  if(!_tipEl)return;
  var lines=posts.map(function(p){return eH(p.ch||'')+' \u00b7 '+eH(p.sched||'')+' \u00b7 '+eH(p.title||'(no title)');});
  _tipEl.innerHTML=lines.join('<br>');
  _tipEl.style.display='block';
  _tipEl.style.left=(e.clientX+12)+'px';_tipEl.style.top=(e.clientY-8)+'px';
}
function loadChipStack(posts){
  if(!posts||!posts.length)return;
  _activePostId=null;
  document.getElementById('so-pv-empty').style.display='none';
  document.getElementById('so-pv-skel').style.display='none';
  var ld=document.getElementById('so-pv-loaded');
  ld.style.display='flex';ld.style.flexDirection='column';ld.style.flex='1';
  var meta='<div class="so-pv-meta"><span class="so-pv-chip">'+posts.length+' posts at this time</span></div>';
  var stack='<div class="so-chip-stack">';
  for(var i=0;i<posts.length;i++){
    var p=posts[i];
    stack+='<button class="so-chip-stack-item" data-post-id="'+eA(p.id||'')+'">'+
      '<span class="so-chip-stack-ch">'+eH(p.ch||'')+'</span>'+
      '<span class="so-chip-stack-time">'+eH(p.sched||'')+'</span>'+
      '<span class="so-chip-stack-title">'+eH(p.title||'(no title)')+'</span>'+
      '</button>';
  }
  stack+='</div>';
  ld.innerHTML=meta+'<div class="so-pv-body">'+stack+'</div><div class="so-pv-actions"></div>';
  ld.querySelectorAll('.so-chip-stack-item').forEach(function(btn){
    btn.addEventListener('click',function(){var pid=btn.getAttribute('data-post-id');if(pid)loadPreview(pid);});
  });
}

// ── Preview pane ──────────────────────────────────────────────────────
function loadPreview(id){
  if(!id)return;_activePostId=id;
  document.getElementById('so-pv-empty').style.display='none';
  document.getElementById('so-pv-loaded').style.display='none';
  document.getElementById('so-pv-skel').style.display='flex';
  fetch('/admin/api/social-ops/post/'+id,{credentials:'same-origin'})
    .then(function(r){if(!r.ok)throw 0;return r.json();})
    .then(showPreview).catch(showPvErr);
}
function showPreview(p){
  document.getElementById('so-pv-skel').style.display='none';
  var sc=stColor(p.status||''),sm2=stMark(p.status||'');
  var chips=[
    '<span class="so-pv-chip">'+eH(p.channel||'?')+'</span>',
    p.type?'<span class="so-pv-chip">'+eH(p.type)+'</span>':'',
    p.scheduled?'<span class="so-pv-chip">📅 '+eH(p.scheduled)+' SAST</span>':'',
    p.actual?'<span class="so-pv-chip">\u2713 '+eH(p.actual)+'</span>':'',
    '<span class="so-pv-chip" style="color:'+sc+';border-color:'+sc+'50;">'+sm2+' '+eH(p.status||'unknown')+'</span>',
    p.id?'<span class="so-pv-chip" title="Post ID">#'+eH(p.id.slice(0,8))+'</span>':'',
    p.error?'<span class="so-pv-chip" style="color:var(--red);" title="'+eA(p.error)+'">Error</span>':'',
  ].filter(Boolean).join('');
  document.getElementById('so-pv-meta').innerHTML=chips;
  document.getElementById('so-pv-body').innerHTML=renderPvBody(p);
  initPvCarousels();
  if(p.reel_state==='overdue'||p.reel_state==='needs_upload')soReelUploadInit();
  var acts=[];
  if((p.status||'').match(/fail|error|block/i))acts.push('<button onclick="alert(\\'Retry: use Notion to re-queue this post\\')">Retry</button>');
  if((p.status||'').match(/pending|queue|sched|ready|await/i))acts.push('<button onclick="alert(\\'Skip: use Notion to update status\\')">Skip</button>');
  if(p.permalink)acts.push('<a href="'+eA(p.permalink)+'" target="_blank" rel="noopener">Open original \u2197</a>');
  acts.push('<button onclick="navigator.clipboard.writeText('+JSON.stringify(JSON.stringify(p))+')">Copy payload</button>');
  document.getElementById('so-pv-actions').innerHTML=acts.join('');
  var ld=document.getElementById('so-pv-loaded');ld.style.display='flex';ld.style.flexDirection='column';ld.style.flex='1';
}
function _pvBrand(ch){
  if(ch.includes('instagram'))return{handle:'mzansiedge',display:'MzansiEdge',avatar:'M',sub:'Sponsored'};
  if(ch.includes('tiktok'))return{handle:'@mzansiedge',display:'MzansiEdge',avatar:'M',sub:'original sound'};
  if(ch.includes('telegram community')||ch.includes('telegram_community'))return{handle:'MzansiEdge Community',display:'MzansiEdge Community',avatar:'M',sub:'Group'};
  if(ch.includes('telegram'))return{handle:'MzansiEdge Alerts',display:'MzansiEdge Alerts',avatar:'M',sub:'Channel'};
  if(ch.includes('whatsapp'))return{handle:'MzansiEdge',display:'MzansiEdge',avatar:'M',sub:'Channel'};
  if(ch.includes('linkedin'))return{handle:'MzansiEdge',display:'MzansiEdge',avatar:'M',sub:'Sports intelligence · Johannesburg · Sponsored'};
  return{handle:'MzansiEdge',display:'MzansiEdge',avatar:'M',sub:''};
}
function _pvCaption(p,ch){
  if(ch.includes('telegram'))return p.telegram_caption||p.caption_final||p.caption||p.body_markdown||'';
  if(ch.includes('instagram'))return p.ig_caption||p.caption_final||p.caption||p.body_markdown||'';
  return p.caption_final||p.caption||p.body_markdown||'';
}
function _pvEscHtml(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function _pvLineBreaks(s){return _pvEscHtml(s).replace(/\\n/g,'<br>');}
function _pvHashLine(p){
  if(!p.hashtags_str)return'';
  var tags=eH(p.hashtags_str).split(/\\s+/).filter(Boolean);
  return'<span>'+tags.join(' ')+'</span>';
}
function _pvTimeLabel(p){
  if(p.scheduled)return eH(p.scheduled);
  if(p.created_at)return eH(p.created_at);
  return'Just now';
}
function renderIgFrame(p,media){
  var br=_pvBrand('instagram');
  var cap=_pvCaption(p,'instagram');
  var hasCarousel=p.carousel_images && p.carousel_images.length>1;
  var capHtml=cap?'<div class="pv-ig-caption"><b>'+eH(br.handle)+'</b>'+_pvLineBreaks(cap)+'</div>':'';
  var tagHtml=p.hashtags_str?'<div class="pv-ig-tags">'+_pvHashLine(p)+'</div>':'';
  var hdr='<div class="pv-ig-hdr"><div class="pv-ig-avatar"><div class="pv-ig-avatar-inner">'+eH(br.avatar)+'</div></div><div class="pv-ig-handle">'+eH(br.handle)+' <span style="color:#8e8e8e;font-weight:400;">· '+eH(br.sub)+'</span></div><div class="pv-ig-more">⋯</div></div>';
  var actions=''+
    '<div class="pv-ig-actions">'+
      '<svg viewBox="0 0 24 24"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>'+
      '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'+
      '<svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>'+
      '<span class="sp"></span>'+
      '<svg viewBox="0 0 24 24"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>'+
    '</div>';
  var likes='<div class="pv-ig-likes">1,247 likes</div>';
  var comments='<div class="pv-ig-comments">View all 38 comments</div>';
  var time='<div class="pv-ig-time">'+_pvTimeLabel(p)+'</div>';
  return'<div class="pv-ig-frame">'+hdr+media+actions+likes+capHtml+tagHtml+comments+time+'</div>';
}
function renderTikTokFrame(p,media){
  var br=_pvBrand('tiktok');
  var cap=_pvCaption(p,'tiktok');
  var tags=p.hashtags_str?'<div style="color:#fff;font-weight:600;margin-top:4px;">'+eH(p.hashtags_str)+'</div>':'';
  var top='<div class="pv-tt-top"><span class="tab">Following</span><span class="tab active">For You</span></div>';
  var side=''+
    '<div class="pv-tt-side">'+
      '<div class="pv-tt-side-item">'+
        '<div class="pv-tt-profile">'+eH(br.avatar)+'<span class="pv-tt-follow">+</span></div>'+
      '</div>'+
      '<div class="pv-tt-side-item">'+
        '<svg viewBox="0 0 48 48" fill="#fff"><path d="M24 42s-14-8.35-14-18a8 8 0 0 1 14-5.3A8 8 0 0 1 38 24c0 9.65-14 18-14 18z"/></svg>'+
        '<span class="n">45.2K</span>'+
      '</div>'+
      '<div class="pv-tt-side-item">'+
        '<svg viewBox="0 0 48 48" fill="#fff"><path d="M42 22c0 9.4-8 17-18 17-2.8 0-5.5-.6-7.8-1.7L8 40l2.7-8.2C8.4 29 7 25.6 7 22 7 12.6 15.5 5 24 5s18 7.6 18 17z"/></svg>'+
        '<span class="n">1,247</span>'+
      '</div>'+
      '<div class="pv-tt-side-item">'+
        '<svg viewBox="0 0 48 48" fill="#fff"><path d="M12 4v40l12-8 12 8V4z"/></svg>'+
        '<span class="n">892</span>'+
      '</div>'+
      '<div class="pv-tt-side-item">'+
        '<svg viewBox="0 0 48 48" fill="#fff"><path d="M4 24l20-12v8c12 0 20 8 20 20-4-6-10-10-20-10v8z"/></svg>'+
        '<span class="n">Share</span>'+
      '</div>'+
      '<div class="pv-tt-disc"></div>'+
    '</div>';
  var bottom=''+
    '<div class="pv-tt-bottom">'+
      '<div class="pv-tt-handle">'+eH(br.handle)+'</div>'+
      '<div class="pv-tt-cap">'+_pvLineBreaks(cap)+tags+'</div>'+
      '<div class="pv-tt-music">🎵 '+eH(br.sub)+' · '+eH(br.display)+'</div>'+
    '</div>';
  return'<div class="pv-tt-frame">'+media+top+side+bottom+'</div>';
}
function renderTelegramFrame(p,media){
  var br=_pvBrand((p.channel||'').toLowerCase());
  var cap=_pvCaption(p,'telegram');
  var bodyHtml=cap.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>');
  var hdr='<div class="pv-tg-hdr"><div class="pv-avatar">'+eH(br.avatar)+'</div><div><div class="pv-tg-name">'+eH(br.display)+'</div><div class="pv-tg-sub">'+eH(br.sub)+'</div></div></div>';
  var bubbleMedia=media?'<div class="pv-tg-bubble-media">'+media+'</div>':'';
  var bubbleText=bodyHtml?'<div class="pv-tg-bubble-text">'+bodyHtml+'</div>':'';
  var hashInline=p.hashtags_str?'<div class="pv-tg-bubble-text" style="padding-top:2px;"><span style="color:#6ab3f3;">'+eH(p.hashtags_str)+'</span></div>':'';
  var meta='<div class="pv-tg-meta"><span class="views">12.4K</span><span>'+_pvTimeLabel(p)+'</span></div>';
  var react='<div class="pv-tg-reactions"><span class="pv-tg-react">🔥 284</span><span class="pv-tg-react">👀 1.1K</span><span class="pv-tg-react">💎 92</span></div>';
  return'<div class="pv-tg-frame">'+hdr+'<div class="pv-tg-bubble">'+bubbleMedia+bubbleText+hashInline+meta+'</div>'+react+'</div>';
}
function renderWhatsAppFrame(p,media){
  var br=_pvBrand('whatsapp');
  var cap=_pvCaption(p,'whatsapp');
  var bodyHtml=_pvLineBreaks(cap);
  var hashInline=p.hashtags_str?'<br><br><span style="color:#53bdeb;">'+eH(p.hashtags_str)+'</span>':'';
  var hdr='<div class="pv-wa-hdr"><div class="pv-avatar">'+eH(br.avatar)+'</div><div><div class="pv-wa-name">'+eH(br.display)+'</div><div class="pv-wa-sub">'+eH(br.sub)+' · Broadcast</div></div></div>';
  var bubbleMedia=media?'<div class="pv-wa-bubble-media">'+media+'</div>':'';
  var bubbleText=bodyHtml?'<div class="pv-wa-bubble-text">'+bodyHtml+hashInline+'</div>':'';
  var meta='<div class="pv-wa-meta"><span>'+_pvTimeLabel(p)+'</span><span class="pv-wa-ticks">✓✓</span></div>';
  return'<div class="pv-wa-frame">'+hdr+'<div class="pv-wa-body"><div class="pv-wa-bubble">'+bubbleMedia+bubbleText+meta+'</div></div></div>';
}
function renderLinkedInFrame(p,media){
  var br=_pvBrand('linkedin');
  var cap=_pvCaption(p,'linkedin');
  var bodyHtml=_pvLineBreaks(cap);
  var hashInline=p.hashtags_str?'<br><br><span style="color:#70b5f9;">'+eH(p.hashtags_str)+'</span>':'';
  var hdr='<div class="pv-li-hdr"><div class="pv-avatar" style="background:#0a66c2;border-radius:4px;">'+eH(br.avatar)+'</div><div><div class="pv-li-name">'+eH(br.display)+'</div><div class="pv-li-sub">'+eH(br.sub)+'<br>'+_pvTimeLabel(p)+' · <span title="Public">🌐</span></div></div><div class="pv-li-follow">+ Follow</div></div>';
  var text=bodyHtml?'<div class="pv-li-text">'+bodyHtml+hashInline+'</div>':'';
  var mediaWrap=media?'<div class="pv-li-media">'+media+'</div>':'';
  var stats='<div class="pv-li-stats"><span>🔥 284 · 💡 92</span><span style="margin-left:auto;">38 comments · 12 reposts</span></div>';
  var actions=''+
    '<div class="pv-li-actions">'+
      '<div class="pv-li-action"><svg viewBox="0 0 24 24"><path d="M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7"/></svg>Like</div>'+
      '<div class="pv-li-action"><svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Comment</div>'+
      '<div class="pv-li-action"><svg viewBox="0 0 24 24"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>Repost</div>'+
      '<div class="pv-li-action"><svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>Send</div>'+
    '</div>';
  return'<div class="pv-li-frame">'+hdr+text+mediaWrap+stats+actions+'</div>';
}
function renderPvBody(p){
  var ch=(p.channel||'').toLowerCase();
  // Awaiting-upload reel: show specialized upload panel instead of IG preview
  if((p.reel_state==='overdue'||p.reel_state==='needs_upload')&&ch.includes('instagram')){return renderReelUploadPanel(p);}
  var media=renderPvMedia(p,ch);
  if(ch.includes('instagram'))return renderIgFrame(p,media);
  if(ch.includes('tiktok'))return renderTikTokFrame(p,media);
  if(ch.includes('telegram'))return renderTelegramFrame(p,media);
  if(ch.includes('whatsapp'))return renderWhatsAppFrame(p,media);
  if(ch.includes('linkedin'))return renderLinkedInFrame(p,media);
  var cap=_pvCaption(p,ch);
  var ttl=p.title?'<b>'+eH(p.title)+'</b><br><br>':'';
  var hashHtml=p.hashtags_str?'<div class="pv-hashtags">'+eH(p.hashtags_str)+'</div>':'';
  return media+'<div class="pv-gen">'+ttl+_pvLineBreaks(cap)+'</div>'+hashHtml;
}
function renderPvMedia(p,ch){
  ch=ch||(p.channel||'').toLowerCase();
  var hasCarousel=p.carousel_images && p.carousel_images.length>1;
  if(!p.image_url && !p.video_url && !hasCarousel)return'';
  var aspectCls='';
  if(ch.includes('instagram')){
    aspectCls='pv-ig-media '+(p.media_aspect==='9:16'?'aspect-9-16':(p.media_aspect==='4:5'?'aspect-4-5':'aspect-1-1'));
  }
  var inner='';
  if(p.video_url){
    inner='<video controls preload="metadata" playsinline src="'+eA(p.video_url)+'"></video>';
  }else if(hasCarousel){
    var total=p.carousel_images.length;
    var captions=p.slide_captions||[];
    var hasSlideCaps=captions.length===total;
    var slides=p.carousel_images.map(function(u,i){
      var capOverlay='';
      if(ch.includes('instagram') && hasSlideCaps){
        capOverlay='<div class="pv-ig-slide-cap">'+_pvLineBreaks(captions[i])+'</div>';
      }
      return '<div class="pv-carousel-slide">'+capOverlay+'<img loading="lazy" alt="Slide '+(i+1)+'" src="'+eA(u)+'"></div>';
    }).join('');
    var dots=p.carousel_images.map(function(_,i){
      return '<span class="pv-carousel-dot'+(i===0?' active':'')+'" data-idx="'+i+'"></span>';
    }).join('');
    var igDots='';
    if(ch.includes('instagram')){
      igDots='<div class="pv-ig-dots-top">'+p.carousel_images.map(function(_,i){return'<span class="d'+(i===0?' active':'')+'"></span>';}).join('')+'</div>'+
             '<span class="pv-ig-count" data-ig-count>1/'+total+'</span>';
    }
    inner=igDots+
          '<div class="pv-carousel" data-carousel>'+slides+'</div>'+
          (ch.includes('instagram')?'':'<span class="pv-carousel-num" data-carousel-num>1/'+total+'</span>')+
          '<button class="pv-carousel-nav prev" data-carousel-prev aria-label="Previous slide" disabled>‹</button>'+
          '<button class="pv-carousel-nav next" data-carousel-next aria-label="Next slide">›</button>'+
          '<div class="pv-carousel-dots" data-carousel-dots>'+dots+'</div>';
  }else if(p.image_url){
    inner='<img loading="lazy" alt="" src="'+eA(p.image_url)+'">';
  }
  var wrapCls=ch.includes('instagram')?aspectCls:'so-pv-media '+(hasCarousel?'pv-carousel-wrap aspect-1-1':'');
  if(hasCarousel && !ch.includes('instagram'))wrapCls+=' pv-carousel-wrap';
  else if(hasCarousel && ch.includes('instagram'))wrapCls+=' pv-carousel-wrap';
  return'<div class="'+wrapCls+'">'+inner+'</div>';
}
function initPvCarousels(){
  document.querySelectorAll('.pv-carousel-wrap').forEach(function(wrap){
    var track=wrap.querySelector('[data-carousel]');
    if(!track||track.dataset.pvInit)return;
    track.dataset.pvInit='1';
    var prev=wrap.querySelector('[data-carousel-prev]');
    var next=wrap.querySelector('[data-carousel-next]');
    var dotsEl=wrap.querySelector('[data-carousel-dots]');
    var numEl=wrap.querySelector('[data-carousel-num]');
    var igCountEl=wrap.querySelector('[data-ig-count]');
    var igDotsWrap=wrap.querySelector('.pv-ig-dots-top');
    var igDots=igDotsWrap?Array.prototype.slice.call(igDotsWrap.querySelectorAll('.d')):[];
    var dots=dotsEl?Array.prototype.slice.call(dotsEl.querySelectorAll('.pv-carousel-dot')):[];
    var slides=track.querySelectorAll('.pv-carousel-slide');
    var total=slides.length;
    var current=0;
    function update(){
      if(numEl)numEl.textContent=(current+1)+'/'+total;
      if(igCountEl)igCountEl.textContent=(current+1)+'/'+total;
      dots.forEach(function(d,i){d.classList.toggle('active',i===current);});
      igDots.forEach(function(d,i){d.classList.toggle('active',i===current);});
      if(prev)prev.disabled=current<=0;
      if(next)next.disabled=current>=total-1;
    }
    function goto(i){
      current=Math.max(0,Math.min(total-1,i));
      var target=slides[current];
      if(target)track.scrollTo({left:target.offsetLeft,behavior:'smooth'});
      update();
    }
    if(prev)prev.addEventListener('click',function(e){e.preventDefault();goto(current-1);});
    if(next)next.addEventListener('click',function(e){e.preventDefault();goto(current+1);});
    dots.forEach(function(d){d.style.pointerEvents='auto';d.style.cursor='pointer';d.addEventListener('click',function(){goto(parseInt(d.dataset.idx,10)||0);});});
    var scrollTimer=null;
    track.addEventListener('scroll',function(){
      if(scrollTimer)clearTimeout(scrollTimer);
      scrollTimer=setTimeout(function(){
        var w=track.clientWidth||1;
        var idx=Math.round(track.scrollLeft/w);
        if(idx!==current){current=idx;update();}
      },80);
    },{passive:true});
    update();
  });
}
// ── Reel upload panel ─────────────────────────────────────────────────────────
function renderReelUploadPanel(p){
  var rawSched=p.scheduled||'';
  var datePart=rawSched.split(' ')[0]||'';
  var slotPart=rawSched.split(' ')[1]||window.CADENCE_SLOTS.ig_reel;
  var rowId=p.id||'';
  return'<div class="so-reel-upload-panel">'+
    '<div class="so-rup-header">🎥 IG Reel<span class="so-rup-chip">AWAITING UPLOAD</span></div>'+
    '<div class="so-rup-meta">'+eH(datePart)+' &middot; '+eH(slotPart)+' SAST &middot; Upload your Premiere Pro export to queue this reel.</div>'+
    '<div class="so-rup-kit-btn">'+
      '<button onclick="soReelOpenKit('+JSON.stringify(datePart)+')">📦 Open Reel Kit in Task Hub →</button>'+
    '</div>'+
    '<div class="so-rup-upload" id="so-rup-zone" data-row="'+eA(rowId)+'" data-date="'+eA(datePart)+'">'+
      '<div class="so-rup-drop" id="so-rup-drop">'+
        '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>'+
        '<div class="so-rup-drop-text">Drop <b>master.mp4</b> here or <label class="so-rup-browse" for="so-rup-file">browse</label></div>'+
        '<input type="file" id="so-rup-file" accept="video/mp4" style="display:none">'+
      '</div>'+
    '</div>'+
    '<div id="so-rup-status" class="so-rup-status"></div>'+
  '</div>';
}
function soReelOpenKit(date){
  fetch('/admin/api/reel-kit-url?date='+encodeURIComponent(date),{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.found&&d.url){window.open(d.url,'_blank','noopener,noreferrer');}
      else{var b=document.getElementById('so-rup-status');if(b){b.textContent='No Reel Kit found for '+date+' — run reel_generator.py first.';b.className='so-rup-status error';}}
    })
    .catch(function(){var b=document.getElementById('so-rup-status');if(b){b.textContent='Could not resolve Reel Kit URL.';b.className='so-rup-status error';}});
}
function soReelUploadFile(file,rowId,date){
  var status=document.getElementById('so-rup-status');
  var zone=document.getElementById('so-rup-zone');
  var drop=document.getElementById('so-rup-drop');
  if(!file){return;}
  if(!file.type.includes('mp4')&&!file.name.endsWith('.mp4')){
    if(status){status.textContent='Please select an MP4 file.';status.className='so-rup-status error';}
    return;
  }
  if(zone)zone.classList.add('so-rup-uploading');
  if(status){status.textContent='Uploading…';status.className='so-rup-status';}
  var fd=new FormData();
  fd.append('row_id',rowId);
  fd.append('date',date);
  fd.append('file',file);
  fetch('/admin/reel/upload',{method:'POST',body:fd,credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(zone)zone.classList.remove('so-rup-uploading');
      if(d.ok){
        // Show success
        if(drop)drop.innerHTML='<div style="color:var(--green);text-align:center">✅ Uploaded — queued for 19:00 SAST</div>';
        if(status){status.textContent='Master MP4 uploaded. Refreshing timeline…';status.className='so-rup-status success';}
        // Instant local glyph repaint: strip flash class
        var glyphBtn=document.querySelector('[data-post-id="'+rowId+'"]');
        if(glyphBtn){glyphBtn.classList.remove('so-tl-reel-flash');}
        // Force timeline refresh (will confirm queued state from server)
        if(typeof refreshTimeline==='function')refreshTimeline();
      } else {
        if(status){status.textContent='Upload failed: '+(d.error||'unknown error');status.className='so-rup-status error';}
      }
    })
    .catch(function(err){
      if(zone)zone.classList.remove('so-rup-uploading');
      if(status){status.textContent='Network error — upload failed.';status.className='so-rup-status error';}
    });
}
function soReelUploadInit(){
  var zone=document.getElementById('so-rup-zone');
  if(!zone)return;
  var drop=document.getElementById('so-rup-drop');
  var fileInput=document.getElementById('so-rup-file');
  var rowId=zone.dataset.row;
  var date=zone.dataset.date;
  if(!drop||!fileInput||!rowId||!date)return;
  drop.addEventListener('click',function(e){if(e.target.tagName!=='LABEL')fileInput.click();});
  drop.addEventListener('dragover',function(e){e.preventDefault();drop.classList.add('dragover');});
  drop.addEventListener('dragleave',function(){drop.classList.remove('dragover');});
  drop.addEventListener('drop',function(e){e.preventDefault();drop.classList.remove('dragover');soReelUploadFile(e.dataTransfer.files[0],rowId,date);});
  fileInput.addEventListener('change',function(){soReelUploadFile(fileInput.files[0],rowId,date);});
}
function showPvErr(){
  document.getElementById('so-pv-skel').style.display='none';
  document.getElementById('so-pv-loaded').style.display='none';
  var e=document.getElementById('so-pv-empty');e.style.display='flex';
  e.innerHTML='<svg viewBox="0 0 24 24" width="48" height="48" stroke="currentColor" stroke-width="1" fill="none"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg><p>Could not load post.</p>';
}
function closePreview(){
  _activePostId=null;
  document.getElementById('so-pv-skel').style.display='none';
  document.getElementById('so-pv-loaded').style.display='none';
  document.getElementById('so-pv-empty').style.display='flex';
}

// ── Failed/Blocked banner dismiss ─────────────────────────────────────
window.__soDismissFB=function(btn){
  var item=btn.closest('.so-fb-item');
  if(!item)return;
  var pageId=item.getAttribute('data-page-id');
  if(!pageId)return;
  btn.disabled=true;
  fetch('/admin/api/dismiss-item',{
    method:'POST',
    credentials:'same-origin',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({page_id:pageId})
  }).then(function(r){
    if(!r.ok)throw new Error('HTTP '+r.status);
    return r.json().catch(function(){return{ok:true};});
  }).then(function(){
    item.remove();
    var banner=document.getElementById('so-fb-banner');
    if(!banner)return;
    var remaining=banner.querySelectorAll('.so-fb-item').length;
    if(remaining===0){
      banner.style.display='none';
      return;
    }
    var cnt=document.getElementById('so-fb-count');
    if(cnt)cnt.textContent=remaining+' failed/blocked';
  }).catch(function(e){
    btn.disabled=false;
    console.error('Dismiss failed:',e);
    alert('Could not dismiss: '+(e&&e.message?e.message:'unknown error'));
  });
};
window.__soWarnDismiss=function(btn){
  var item=btn.closest('.so-fb-item');if(!item)return;
  item.remove();
  var banner=document.getElementById('so-warn-banner');
  if(!banner)return;
  if(!banner.querySelectorAll('.so-fb-item').length)banner.style.display='none';
  var cnt=document.getElementById('so-warn-count');
  if(cnt){var n=banner.querySelectorAll('.so-fb-item').length;if(n>0)cnt.textContent=n+' warning'+(n!==1?'s':'');}
};

// ── Queue ─────────────────────────────────────────────────────────────
function _soRelWhen(mins){
  if(mins==null)return '';
  if(mins<1)return 'now';
  if(mins<60)return 'in '+mins+'m';
  var h=Math.floor(mins/60),m=mins%60;
  return 'in '+h+'h'+(m?' '+m+'m':'');
}
function _soStatusCls(st){return 'st-'+String(st||'').toLowerCase().replace(/[^a-z]/g,'');}
function fetchQueue(){
  fetch('/admin/api/social-ops/queue?hours=12',{credentials:'same-origin'})
    .then(function(r){if(!r.ok)throw 0;return r.json();})
    .then(renderQueue)
    .catch(function(){var b=document.getElementById('so-queue-body');if(b)b.innerHTML='<div class="so-queue-empty">Could not load.</div>';});
}
function renderQueue(d){
  var c=document.getElementById('so-queue-count');
  var b=document.getElementById('so-queue-body');
  if(!c||!b)return;
  var posts=(d&&d.posts)||[];
  c.textContent=posts.length+' in next '+((d&&d.horizon_hours)||12)+'h';
  if(!posts.length){b.innerHTML='<div class="so-queue-empty">Nothing scheduled in the next 12 hours.</div>';return;}
  var html='';
  for(var i=0;i<posts.length&&i<80;i++){
    var p=posts[i];
    var color=p.channel_color||'#888';
    var logo=p.channel_icon_svg||'';
    var lbl=p.channel_label||(p.channel_key||p.channel||'').replace(/_/g,' ');
    var st=(p.status||'').toLowerCase();
    var stCls=_soStatusCls(st);
    var rel=_soRelWhen(p.mins_until);
    html+='<div class="so-queue-row" data-post-id="'+eA(p.id)+'" title="'+eA(p.sched_full||'')+'" style="--so-ch:'+eA(color)+';">'+
      '<div class="so-queue-row-logo" style="color:'+eA(color)+';">'+logo+'</div>'+
      '<div class="so-queue-row-main">'+
        '<div class="so-queue-row-title">'+eH(p.title||'Untitled post')+'</div>'+
        '<div class="so-queue-row-meta">'+
          '<span class="so-queue-row-ch">'+eH(lbl)+'</span>'+
          (p.type?'<span class="so-queue-row-dot"></span><span class="so-queue-row-type">'+eH(p.type)+'</span>':'')+
          (st?'<span class="so-queue-row-status '+stCls+'">'+eH(st)+'</span>':'')+
        '</div>'+
      '</div>'+
      '<div class="so-queue-row-when">'+
        '<span class="so-queue-row-time">'+eH(p.sched||'')+'</span>'+
        (rel?'<span class="so-queue-row-rel">'+eH(rel)+'</span>':'')+
      '</div>'+
    '</div>';
  }
  b.innerHTML=html;
  var rows=b.querySelectorAll('.so-queue-row');
  for(var j=0;j<rows.length;j++){
    rows[j].addEventListener('click',function(){
      var id=this.getAttribute('data-post-id');
      if(id&&typeof loadPreview==='function')loadPreview(id);
    });
  }
}

// ── Helpers ───────────────────────────────────────────────────────────
function eH(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function eA(s){if(!s)return'';return String(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

})();
</script>"""
    )
    return f"""{css}
<div class="so-page">
  <div class="so-topbar">
    <h1 class="so-h1">
      <span class="so-live-dot" aria-hidden="true">&#9679;</span>
      Social Ops
      <span class="so-stale-badge" id="so-stale-badge" style="display:none">stale</span>
    </h1>
    <div class="so-controls">
      <span class="so-sync-pill">{sync_label}</span>
      <div class="so-day-picker" role="group" aria-label="Day navigation">
        <button class="so-day-btn" id="so-day-prev" aria-label="Previous day">&#9664;</button>
        <span class="so-day-lbl" id="so-day-lbl">Today</span>
        <button class="so-day-btn" id="so-day-next" aria-label="Next day" disabled>&#9654;</button>
      </div>
    </div>
  </div>
  {notion_warn}
  <div class="so-kpi-strip">
    <div class="kpi"><div class="kpi-lbl">Posted 24h</div><div class="kpi-val c-green" id="kpi-posted">{kpi_posted}</div></div>
    <div class="kpi"><div class="kpi-lbl">Pending now</div><div class="kpi-val" id="kpi-pending">{kpi_pending}</div></div>
    <div class="kpi"><div class="kpi-lbl">Failed 24h</div><div class="kpi-val c-red" id="kpi-failed">{kpi_failed}</div></div>
    <div class="kpi"><div class="kpi-lbl">Queue (12h)</div><div class="kpi-val" id="kpi-queue">{kpi_queue}</div></div>
    <div class="kpi"><div class="kpi-lbl">Overdue Queue</div><div class="kpi-val c-gold" id="kpi-overdue">{kpi_overdue_queue}</div></div>
    <div class="kpi"><div class="kpi-lbl">Past-due</div><div class="kpi-val c-red" id="kpi-pastdue">{kpi_pastdue}</div></div>
    <div class="kpi"><div class="kpi-lbl">Unscheduled</div><div class="kpi-val" id="kpi-unscheduled">{kpi_unscheduled}</div></div>
  </div>
  {fb_banner_html}
  {warn_banner_html}
  <div class="so-main">
    <div class="so-left">
      <div class="so-tl-wrap">
        <div id="so-tl-content" class="so-tl-content">
          <div class="so-tl-hours-row" aria-hidden="true">
            <span class="so-tl-hour-lbl" style="left:0%">00</span>
            <span class="so-tl-hour-lbl so-tl-hour-lbl-mid" style="left:12.5%">03</span>
            <span class="so-tl-hour-lbl" style="left:25%">06</span>
            <span class="so-tl-hour-lbl so-tl-hour-lbl-mid" style="left:37.5%">09</span>
            <span class="so-tl-hour-lbl" style="left:50%">12</span>
            <span class="so-tl-hour-lbl so-tl-hour-lbl-mid" style="left:62.5%">15</span>
            <span class="so-tl-hour-lbl" style="left:75%">18</span>
            <span class="so-tl-hour-lbl so-tl-hour-lbl-mid" style="left:87.5%">21</span>
          </div>
          <div class="so-tl-now-line" id="so-tl-now" style="display:none" aria-hidden="true">
            <span class="so-tl-now-lbl" id="so-tl-now-lbl">now 00:00</span>
          </div>
          <div id="so-tl-rows" role="grid" aria-label="24-hour post timeline"></div>
        </div>
      </div>
      <div class="so-bottom-grid">
        <div class="so-queue" aria-label="Next 12 hours queue">
          <div class="so-panel-h">
            <div class="so-panel-title">Next 12h Queue</div>
            <div class="so-panel-sub" id="so-queue-count">--</div>
          </div>
          <div class="so-queue-body" id="so-queue-body">
            <div class="so-tile-skel" style="width:80%"></div>
            <div class="so-tile-skel" style="width:60%"></div>
            <div class="so-tile-skel" style="width:70%"></div>
          </div>
        </div>
      </div>
    </div>
    <div class="so-preview" id="so-preview" aria-label="Post preview" aria-live="polite">
      <div class="so-pv-empty" id="so-pv-empty" style="display:flex;flex:1">
        <svg viewBox="0 0 24 24" width="52" height="52" stroke="currentColor" stroke-width="1" fill="none" aria-hidden="true">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <path d="M3 9h18M9 21V9"/>
        </svg>
        <p>Click a post on the timeline<br>to preview it here.</p>
      </div>
      <div class="so-pv-skel" id="so-pv-skel" style="display:none">
        <div class="skel-b" style="height:18px;width:55%"></div>
        <div class="skel-b" style="height:14px;width:38%"></div>
        <div class="skel-b" style="height:110px;width:100%"></div>
        <div class="skel-b" style="height:13px;width:75%"></div>
        <div class="skel-b" style="height:13px;width:50%"></div>
      </div>
      <div id="so-pv-loaded" style="display:none">
        <div class="so-pv-meta" id="so-pv-meta"></div>
        <div class="so-pv-body" id="so-pv-body"></div>
        <div class="so-pv-actions" id="so-pv-actions"></div>
      </div>
    </div>
  </div>
</div>
<div class="so-tip" id="so-tip" role="tooltip" aria-hidden="true"></div>
{_cadence_slots_script()}{js}"""


def render_reel_kit_page() -> str:
    """Render the dedicated Reel Kit gallery page (UI-SOCIAL-OPS-REDESIGN-01)."""
    import html as _html_mod
    now_sast = datetime.now(_SAST)
    today_str = now_sast.strftime("%Y-%m-%d")
    try:
        reel_kits = _scan_reel_kits(today_str)
    except Exception:
        reel_kits = []

    _TIER_COLORS = {"diamond": "#00D4FF", "gold": "#F59E0B", "silver": "#94A3B8", "bronze": "#CD7F32"}
    if reel_kits:
        cards = ""
        for kit in reel_kits:
            pick_id = kit["pick_id"]
            tier_key = kit.get("tier") or ""
            tier_color = _TIER_COLORS.get(tier_key, "#94A3B8")
            tier_label = tier_key.title() if tier_key else "Pick"
            vo_count = len(kit.get("vos", []))
            has_master = kit.get("has_master", False)
            if has_master:
                status_html = '<span style="color:var(--green);font-weight:700">Ready</span>'
            elif vo_count > 0:
                status_html = f'<span style="color:var(--amber)">{vo_count} VO{"s" if vo_count != 1 else ""}</span>'
            else:
                status_html = '<span style="color:var(--muted)">Card only</span>'
            thumb_file = kit.get("thumb") or kit.get("card") or f"card_{pick_id}.png"
            thumb_url = f"https://mzansiedge.co.za/assets/reel-cards/{today_str}/{pick_id}/{thumb_file}"
            card_url = f"https://mzansiedge.co.za/assets/reel-cards/{today_str}/{pick_id}/card_{pick_id}.png"
            display_name = pick_id[:12].upper()
            cards += f"""<div class="rk-card" style="border-top:3px solid {tier_color}">
  <img class="rk-thumb" src="{_html_mod.escape(thumb_url)}" alt="{_html_mod.escape(display_name)}" loading="lazy">
  <div class="rk-tier" style="color:{tier_color}">{_html_mod.escape(tier_label)}</div>
  <div class="rk-name">{_html_mod.escape(display_name)}</div>
  <div class="rk-status">{status_html}</div>
  <a class="rk-download" href="{_html_mod.escape(card_url)}" download target="_blank">\u2b07 Download</a>
</div>"""
        body = f'<div class="rk-grid">{cards}</div>'
    else:
        body = '<div class="rk-empty">No reel kits for today.</div>'

    return f"""<style>
.rk-page{{font-family:var(--font-b);color:var(--text);background:var(--carbon);min-height:100vh;padding:20px;}}
.rk-h1{{font-size:18px;font-weight:600;margin:0 0 16px 0;}}
.rk-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;}}
.rk-card{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px;text-align:center;}}
.rk-thumb{{width:100%;height:160px;object-fit:cover;border-radius:6px;background:rgba(255,255,255,.04);}}
.rk-tier{{font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-top:8px;}}
.rk-name{{font-family:var(--font-m);font-size:12px;color:var(--text);margin-top:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.rk-status{{font-family:var(--font-m);font-size:11px;margin-top:4px;}}
.rk-download{{display:block;margin-top:8px;padding:6px 0;background:rgba(88,166,255,.12);color:var(--gold);
  border:1px solid rgba(88,166,255,.30);border-radius:5px;font-weight:700;font-size:11px;
  text-decoration:none;}}
.rk-download:hover{{background:rgba(88,166,255,.22);}}
.rk-empty{{text-align:center;padding:60px 0;color:var(--muted);}}
</style>
<div class="rk-page">
  <h1 class="rk-h1">Reel Kit \u2014 {today_str}</h1>
  {body}
</div>"""


def render_calendar_page() -> str:
    """Render the dedicated Calendar (14-day schedule) page (UI-SOCIAL-OPS-REDESIGN-01)."""
    import html as _html_mod
    now_sast = datetime.now(_SAST)
    now_sast = now_sast.astimezone(_SAST)
    fourteen_days = now_sast + timedelta(days=14)

    items: list[dict] = []
    try:
        items, _ = _fetch_marketing_queue()
    except Exception:
        with _notion_cache_lock:
            cached = _notion_cache.get("marketing_queue")
            if cached:
                items = cached[0]

    schedule_items: list[dict] = []
    for item in items:
        status = (item.get("status") or "").lower().strip()
        if status not in ("approved", "awaiting approval", "drafting", "briefed", "draft", "ready", "scheduled"):
            continue
        sched_dt = parse_ts(item.get("scheduled_time") or "")
        if sched_dt and now_sast <= sched_dt <= fourteen_days:
            schedule_items.append(item)
    schedule_items.sort(key=lambda x: x.get("scheduled_time") or "9999")

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

    def _color(status: str) -> str:
        s = status.lower().strip()
        if s in ("approved", "ready", "scheduled"):
            return "var(--green)"
        if s in ("awaiting approval", "awaiting"):
            return "var(--amber)"
        return "var(--muted)"

    ch_headers = "".join(f'<th>{c["label"]}</th>' for c in _CHANNELS)
    rows = ""
    for i in range(14):
        day_dt = now_sast + timedelta(days=i)
        day_key = day_dt.strftime("%Y-%m-%d")
        day_label = "Today" if i == 0 else ("Tomorrow" if i == 1 else day_dt.strftime("%a %d %b"))
        cells = ""
        for ch in _CHANNELS:
            day_items = sched_grid[day_key].get(ch["key"], [])
            if not day_items:
                cells += "<td></td>"
                continue
            cell = ""
            for it in day_items:
                title = _truncate(it.get("title") or it.get("copy") or "", 40)
                color = _color(it.get("status") or "")
                cell += (f'<div class="cal-item" style="border-left:2px solid {color};">'
                         f'{_html_mod.escape(title)}</div>')
            cells += f"<td>{cell}</td>"
        rows += f'<tr><td class="cal-day">{day_label}</td>{cells}</tr>'

    return f"""<style>
.cal-page{{font-family:var(--font-b);color:var(--text);background:var(--carbon);min-height:100vh;padding:20px;}}
.cal-h1{{font-size:18px;font-weight:600;margin:0 0 16px 0;}}
.cal-tbl{{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;}}
.cal-tbl th,.cal-tbl td{{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top;font-size:12px;}}
.cal-tbl th{{background:var(--surface-alt);color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em;}}
.cal-day{{font-weight:600;white-space:nowrap;color:var(--text);}}
.cal-item{{padding:2px 6px;margin-bottom:3px;font-family:var(--font-m);font-size:11px;color:var(--text);}}
</style>
<div class="cal-page">
  <h1 class="cal-h1">14-Day Schedule</h1>
  <table class="cal-tbl">
    <thead><tr><th>Day</th>{ch_headers}</tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


# -- Approvals view -----------------------------------------------------------

_APPROVALS_NOTION_URL = "https://www.notion.so/Marketing-Ops-Queue"

def render_approvals_content() -> str:
    """Render the Approvals pipeline view inner content HTML."""
    now_sast = datetime.now(_SAST)
    now_sast = now_sast.astimezone(_SAST)
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

def _today_sast_str() -> str:
    """Return today's date in SAST as YYYY-MM-DD."""
    return datetime.now(_SAST).strftime("%Y-%m-%d")


def _is_today_sast(iso_str: str) -> bool:
    """True if the given ISO timestamp (or YYYY-MM-DD) falls on today in SAST."""
    if not iso_str:
        return False
    try:
        # Accept bare date strings (YYYY-MM-DD) or full ISO timestamps
        if len(iso_str) == 10 and iso_str[4] == "-":
            return iso_str == _today_sast_str()
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        return dt.astimezone(_SAST).strftime("%Y-%m-%d") == _today_sast_str()
    except Exception:
        return False


def _filter_fb_today(rows: list[dict]) -> list[dict]:
    """Exclude already-posted items. (v2: daily-sheet rows, not MOQ.)"""
    return [r for r in rows if not r.get("posted")]


# Kept for backwards-compat callers; now a pass-through no-op filter
def _filter_fb_today_from_moq(mq_items: list[dict]) -> list[dict]:
    return []


def _filter_quora_today(rows: list[dict]) -> list[dict]:
    """Exclude posted items, sort by priority. (v2: daily-sheet rows.)"""
    PRIO = {"high": 0, "medium": 1, "low": 2}
    out = [r for r in rows if not r.get("posted")]
    out.sort(key=lambda x: PRIO.get((x.get("priority") or "").lower(), 9))
    return out


def _filter_linkedin_today(rows: list[dict]) -> list[dict]:
    """Exclude already-sent/posted targets. (v2: daily-sheet rows.)"""
    return [r for r in rows if not r.get("posted")]


def _fetch_task_hub_data() -> dict:
    """Assemble the four Task Hub panes. Daily sheets + on-disk reel kits.
    (Rewired 17 Apr 2026 v2 — FB/Quora/LinkedIn come from daily sheet child pages.)
    (FIX-DASH-PERF-02: parallelised via ThreadPoolExecutor — target <1.5s cold.)"""
    today = _today_sast_str()

    def _do_reels():
        try:
            return _scan_reel_kits(today)
        except Exception as e:
            log.warning(f"[task-hub] reel scan failed: {e}")
            return []

    def _do_fb():
        try:
            return _filter_fb_today(_fetch_fb_groups_today())
        except Exception as e:
            log.warning(f"[task-hub] fb fetch failed: {e}")
            return []

    def _do_quora():
        try:
            return _filter_quora_today(_fetch_quora_ledger())
        except Exception as e:
            log.warning(f"[task-hub] quora fetch failed: {e}")
            return []

    def _do_linkedin():
        try:
            return _filter_linkedin_today(_fetch_linkedin_ledger())
        except Exception as e:
            log.warning(f"[task-hub] linkedin fetch failed: {e}")
            return []

    with ThreadPoolExecutor(max_workers=4) as _pool:
        f_reels   = _pool.submit(_do_reels)
        f_fb      = _pool.submit(_do_fb)
        f_quora   = _pool.submit(_do_quora)
        f_linkedin = _pool.submit(_do_linkedin)
        reels        = f_reels.result()
        fb_today     = f_fb.result()
        quora_today  = f_quora.result()
        linkedin_today = f_linkedin.result()

    return {
        "date": today,
        "reels": reels,
        "fb": fb_today,
        "quora": quora_today,
        "linkedin": linkedin_today,
    }


def _bg_refresh_task_hub() -> None:
    try:
        data = _fetch_task_hub_data()
        content = render_task_hub_tabbed(data)
        html_out = render_shell("task_hub", content)
        with _page_cache_lock:
            _page_cache["task_hub_full"] = (html_out, time.monotonic())
    except Exception:
        if _sentry is not None:
            _sentry.capture_exception()
    finally:
        with _page_cache_lock:
            _page_refresh_inflight.discard("task_hub_full")


# -- Task Hub inline SVG icons (NO EMOJI in rendered HTML) --------------------
_TH_SVG_PLAY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>'
_TH_SVG_HEADPHONES = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/></svg>'
_TH_SVG_DOWNLOAD = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
_TH_SVG_UPLOAD = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>'
_TH_SVG_CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
_TH_SVG_EXTLINK = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'
_TH_SVG_CLIPBOARD = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>'
_TH_SVG_IMAGE = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>'


def _th_badge_for_tier(tier: str | None) -> str:
    t = (tier or "").lower().strip()
    if t == "diamond":
        return '<span class="badge diamond">Diamond</span>'
    if t == "gold":
        return '<span class="badge gold">Gold</span>'
    if t == "silver":
        return '<span class="badge silver">Silver</span>'
    return '<span class="badge silver">Ready</span>'


def _th_escape(s: str) -> str:
    return html.escape(s or "", quote=True)


def _th_truncate(s: str, n: int = 240) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _th_render_reel_card(kit: dict, date: str) -> str:
    pick = kit.get("pick_id") or ""
    tier_raw = (kit.get("tier") or "").strip()
    # Only show a tier badge when we actually know the tier. Otherwise the
    # silver "Ready" fallback duplicates the state badge below it.
    tier_badge = _th_badge_for_tier(tier_raw) if tier_raw else ""
    has_master = bool(kit.get("has_master"))
    state_badge = (
        '<span class="badge done">Uploaded</span>' if has_master
        else '<span class="badge pending">Ready</span>'
    )
    card_file = kit.get("card") or ""
    card_url = (
        f"https://mzansiedge.co.za/assets/reel-cards/{date}/{pick}/{card_file}"
        if card_file else ""
    )
    if has_master:
        thumb_inner = f'<div class="thumb bru">master.mp4 {_TH_SVG_CHECK}</div>'
    elif card_url:
        # Real 1080x1920 card PNG as preview — much more useful than a
        # generic play-icon placeholder. Play button overlay still clickable.
        thumb_inner = (
            f'<div class="thumb thumb-real" '
            f'style="background-image:url(\'{_th_escape(card_url)}\');">'
            f'<div class="play">{_TH_SVG_PLAY}</div>'
            f'</div>'
        )
    else:
        thumb_inner = f'<div class="thumb"><div class="play">{_TH_SVG_PLAY}</div></div>'
    vos = kit.get("vos") or []
    vo_btn = (
        f'<button type="button" onclick="thReelVO(\'{_th_escape(date)}\',\'{_th_escape(pick)}\')">{_TH_SVG_HEADPHONES} VO preview</button>'
        if vos else ""
    )
    dl_btn = (
        f'<button type="button" onclick="thReelDownload(\'{_th_escape(date)}\',\'{_th_escape(pick)}\')">{_TH_SVG_DOWNLOAD} Download kit</button>'
    )
    if has_master:
        upload_zone = (
            f'<div class="upload-zone done">{_TH_SVG_CHECK} Uploaded · queued to MOQ</div>'
        )
    else:
        upload_zone = (
            f'<div class="upload-zone" data-pick="{_th_escape(pick)}" data-date="{_th_escape(date)}">'
            f'{_TH_SVG_UPLOAD} Drop finished master.mp4 here or click'
            f'<input type="file" accept="video/mp4" style="display:none" />'
            f'</div>'
        )
    # Header: "<Tier> — <TEAM> — <Bookmaker>" when metadata available.
    pick_team = (kit.get("pick_team") or "").strip()
    bookmaker_key = (kit.get("bookmaker") or "").strip().lower()
    if tier_raw and pick_team and bookmaker_key:
        bk_display = _REEL_BK_DISPLAY.get(bookmaker_key, bookmaker_key.title())
        header_title = f"{tier_raw.title()} \u2014 {pick_team} \u2014 {bk_display}"
    else:
        pick_short = pick[:8] if len(pick) > 8 else pick
        header_title = f"Reel \u00b7 {pick_short}"
    head_left = (
        f'{tier_badge}'
        f'<div class="meta" style="margin-top:6px;"><strong>{_th_escape(header_title)}</strong></div>'
        f'<div class="meta">{len(vos)} VO clip(s)</div>'
    )
    return f"""
    <div class="card" data-pick="{_th_escape(pick)}">
      <div class="head">
        <div>
          {head_left}
        </div>
        {state_badge}
      </div>
      {thumb_inner}
      <div class="row-actions">
        {dl_btn}
        {vo_btn}
      </div>
      {upload_zone}
    </div>
    """


def _th_render_fb_card(item: dict) -> str:
    pid = item.get("id") or ""
    group_name = item.get("group") or item.get("title") or "(untitled)"
    final_copy = item.get("final_copy") or ""
    # Preserve double-newline paragraph breaks in HTML display (per feedback_fb_paragraph_spacing)
    copy_html = _th_escape(final_copy).replace("\n\n", "<br><br>").replace("\n", "<br>")
    image_url = item.get("image_url") or ""
    status = (item.get("status") or "Ready").strip()
    group_url = item.get("group_url") or ""

    badge = (
        '<span class="badge done">' + _th_escape(status) + '</span>'
        if status.lower() in ("posted", "sent", "done")
        else '<span class="badge pending">' + _th_escape(status) + '</span>'
    )
    # Fall back to Facebook group search when no direct URL
    if group_url:
        open_label = "Open group ↗"
    else:
        group_url = "https://www.facebook.com/search/groups/?q=" + urllib.parse.quote(group_name)
        open_label = "Search Facebook ↗"
    thumb = (
        f'<div class="thumb thumb-fb" style="background-image:url(\'{_th_escape(image_url)}\');background-size:cover;background-position:center"></div>'
        if image_url else
        f'<div class="thumb thumb-fb">{_TH_SVG_IMAGE}</div>'
    )
    open_link = f'<a href="{_th_escape(group_url)}" target="_blank" rel="noopener" style="color:var(--cyan);font-size:11px">{_TH_SVG_EXTLINK} {open_label}</a>'
    return f"""
    <div class="card" data-id="{_th_escape(pid)}">
      <div class="head">
        <div style="flex:1">
          <div class="fb-group-name">{_th_escape(group_name)}</div>
          <div class="meta">{open_link}</div>
        </div>
        {badge}
      </div>
      {thumb}
      <div class="copy-preview">{copy_html}</div>
      <div class="row-actions">
        <button type="button" onclick="thCopyText(this,{json.dumps(final_copy)})">{_TH_SVG_CLIPBOARD} Copy text</button>
        <button type="button" class="primary" onclick="thFbPosted('{_th_escape(pid)}',this)">{_TH_SVG_CHECK} Mark posted</button>
      </div>
    </div>
    """


def _th_render_quora_card(item: dict) -> str:
    pid = item.get("id") or ""
    q = item.get("question") or "(untitled question)"
    topic = item.get("topic") or ""
    url = item.get("url") or ""
    status = (item.get("status") or "Draft").strip()
    badge = (
        '<span class="badge done">' + _th_escape(status) + '</span>'
        if status.lower() in ("posted", "answered", "published")
        else '<span class="badge pending">' + _th_escape(status) + '</span>'
    )
    link_html = (
        f'<a href="{_th_escape(url)}" target="_blank" rel="noopener" style="color:var(--cyan);font-size:11px">{_TH_SVG_EXTLINK} Open on Quora</a>'
        if url else ""
    )
    return f"""
    <div class="card" data-id="{_th_escape(pid)}">
      <div class="head">
        <div style="flex:1">
          <div class="question-title">{_th_escape(q)}</div>
          <div class="meta">{_th_escape(topic) or 'Quora'} {link_html}</div>
        </div>
        {badge}
      </div>
      <div class="row-actions">
        <button type="button" class="primary" onclick="thQuoraPosted('{_th_escape(pid)}',this)">{_TH_SVG_CHECK} Mark posted</button>
      </div>
    </div>
    """


def _th_render_linkedin_card(item: dict) -> str:
    pid = item.get("id") or ""
    name = item.get("name") or "(unknown)"
    company = item.get("company") or ""
    role = item.get("role") or ""
    full_msg = item.get("note") or ""
    note = _th_truncate(full_msg, 220)
    url = item.get("url") or ""
    status = (item.get("status") or "Draft").strip()
    initials = "".join([w[0] for w in name.split()[:2] if w])[:2].upper() or "?"
    badge = (
        '<span class="badge sent">' + _th_escape(status) + '</span>'
        if status.lower() in ("sent", "connected", "replied")
        else '<span class="badge pending">' + _th_escape(status) + '</span>'
    )
    link_html = (
        f'<a href="{_th_escape(url)}" target="_blank" rel="noopener" style="color:var(--cyan);font-size:11px">{_TH_SVG_EXTLINK} Profile</a>'
        if url else ""
    )
    msg_block = (
        f'<div class="li-msg-wrap">'
        f'<button type="button" class="li-copy-icon" onclick="thCopyIcon(this,{json.dumps(full_msg)})"'
        f' aria-label="Copy message" title="Copy message">{_TH_SVG_CLIPBOARD}</button>'
        f'<div class="copy-preview">{_th_escape(note)}</div>'
        f'</div>'
        if full_msg else ""
    )
    return f"""
    <div class="card" data-id="{_th_escape(pid)}">
      <div class="head">
        <div class="linkedin-head" style="flex:1">
          <div class="avatar">{_th_escape(initials)}</div>
          <div>
            <div class="linkedin-name">{_th_escape(name)}</div>
            <div class="linkedin-role">{_th_escape(role)}{(' · ' + _th_escape(company)) if company else ''}</div>
            <div class="meta">{link_html}</div>
          </div>
        </div>
        {badge}
      </div>
      {msg_block}
      <div class="row-actions">
        <button type="button" class="primary" onclick="thLinkedinSent('{_th_escape(pid)}',this)">{_TH_SVG_CHECK} Mark sent</button>
      </div>
    </div>
    """


def render_task_hub_tabbed(data: dict) -> str:
    """Render the 4-pane Task Hub dashboard from assembled data."""
    reels = data.get("reels") or []
    fb = data.get("fb") or []
    quora = data.get("quora") or []
    linkedin = data.get("linkedin") or []
    date_str = data.get("date") or _today_sast_str()
    total = len(reels) + len(fb) + len(quora) + len(linkedin)
    try:
        pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %d %B %Y")
    except Exception:
        pretty_date = date_str

    reel_cards = "\n".join(_th_render_reel_card(k, date_str) for k in reels) or '<div class="meta" style="padding:24px;text-align:center">No reel kits scanned for today.</div>'
    fb_cards = "\n".join(_th_render_fb_card(i) for i in fb) or '<div class="meta" style="padding:24px;text-align:center">No FB group posts scheduled for today.</div>'
    quora_cards = "\n".join(_th_render_quora_card(i) for i in quora) or '<div class="meta" style="padding:24px;text-align:center">No Quora drafts pending.</div>'
    linkedin_cards = "\n".join(_th_render_linkedin_card(i) for i in linkedin) or '<div class="meta" style="padding:24px;text-align:center">No LinkedIn targets open.</div>'

    css = """
    <style>
      .th-root{color:var(--text);font-family:var(--font-b);font-size:14px;line-height:1.6;min-height:100vh;padding:16px 20px;box-sizing:border-box}
      .th-root *{box-sizing:border-box}
      .th-root .th-topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:12px;flex-wrap:wrap}
      .th-root .th-h1{font-size:18px;font-weight:600;letter-spacing:-0.01em;margin:0;color:var(--text);display:flex;align-items:center;gap:8px;font-family:var(--font-b)}
      .th-root .th-sync-pill{font-family:var(--font-m,var(--font-b));font-size:12px;color:var(--muted);background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:4px 10px}
      /* v3: Task Hub KPIs now share the softer (0.45) global gradient top-line */
      .th-root .kpi-strip{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
      .th-root .kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;position:relative;overflow:hidden;transition:all .18s var(--trans)}
      .th-root .kpi:hover{border-color:rgba(248,200,48,.25);background:var(--surface)}
      .th-root .kpi-lbl{font-size:10px;font-family:var(--font-d);font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
      .th-root .kpi-val{font-size:26px;font-family:var(--font-d);font-weight:700;line-height:1;color:var(--text)}
      .th-root .kpi-val.c-gold{color:var(--gold);text-shadow:0 0 18px rgba(248,200,48,.22)}
      .th-root .kpi-val.c-green{color:var(--green);text-shadow:0 0 14px rgba(34,197,94,.2)}
      .th-root .kpi-val.c-text{color:var(--text)}
      .th-root .kpi-sub{font-size:11px;font-family:var(--font-m);color:var(--muted);margin-top:6px}
      @media(max-width:1000px){.th-root .kpi-strip{grid-template-columns:repeat(3,1fr)}}
      @media(max-width:600px){.th-root .kpi-strip{grid-template-columns:repeat(2,1fr)}}
      .th-root .tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);padding:0 4px;background:transparent;margin-bottom:16px}
      .th-root .tab{padding:12px 18px;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;font-size:13px;font-family:var(--font-b);display:flex;align-items:center;gap:8px;user-select:none;transition:all .18s var(--trans)}
      .th-root .tab:hover{color:var(--text)}
      .th-root .tab.active{color:var(--gold);border-bottom-color:var(--gold)}
      .th-root .tab .count{background:var(--surface-alt);padding:2px 8px;border-radius:10px;font-size:11px;color:var(--muted);border:1px solid var(--border)}
      .th-root .tab.active .count{background:rgba(248,200,48,.14);color:var(--gold);border-color:rgba(248,200,48,.3)}
      .th-root main{padding:0}
      .th-root .pane{display:none}
      .th-root .pane.active{display:block}
      .th-root .pane-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;gap:16px}
      .th-root .pane-title{font-family:var(--font-d);font-size:15px;font-weight:600;color:var(--text)}
      .th-root .pane-sub{color:var(--muted);font-size:12px;margin-top:3px}
      .th-root button{background:var(--surface-alt);border:1px solid var(--border);color:var(--text);padding:8px 14px;border-radius:var(--r);font-size:12px;cursor:pointer;font-family:var(--font-b);display:inline-flex;align-items:center;gap:6px;transition:all .18s var(--trans)}
      .th-root button:hover{border-color:var(--gold);background:var(--surface)}
      .th-root button.primary{background:var(--grad);color:#0A0A0A;border-color:transparent;font-weight:600}
      .th-root button.primary:hover{filter:brightness(1.08)}
      .th-root .grid{display:grid;gap:14px}
      .th-root .grid.reels{grid-template-columns:repeat(3,1fr)}
      .th-root .grid.fb{grid-template-columns:repeat(2,1fr)}
      .th-root .grid.quora{grid-template-columns:1fr}
      .th-root .grid.linkedin{grid-template-columns:repeat(2,1fr)}
      @media (max-width:1100px){.th-root .grid.reels,.th-root .grid.fb,.th-root .grid.linkedin{grid-template-columns:1fr}}
      .th-root .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px;display:flex;flex-direction:column;gap:12px;box-shadow:var(--glow);transition:all .18s var(--trans);position:relative;overflow:hidden}
      .th-root .card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--grad);opacity:0.45;pointer-events:none;z-index:1}
      .th-root .card:hover{border-color:rgba(248,200,48,.3);box-shadow:var(--glow-hover)}
      .th-root .card:hover::before{opacity:0.7}
      .th-root .card .head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
      .th-root .badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:6px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;font-family:var(--font-b)}
      .th-root .badge.gold{background:rgba(248,200,48,.14);color:var(--gold);border:1px solid rgba(248,200,48,.3)}
      .th-root .badge.silver{background:rgba(245,245,245,.08);color:var(--text);border:1px solid var(--border)}
      .th-root .badge.diamond{background:rgba(248,200,48,.14);color:var(--gold);border:1px solid rgba(248,200,48,.3)}
      .th-root .badge.done{background:rgba(34,197,94,.14);color:var(--green);border:1px solid rgba(34,197,94,.3)}
      .th-root .badge.pending{background:rgba(245,158,11,.14);color:var(--amber);border:1px solid rgba(245,158,11,.3)}
      .th-root .badge.sent{background:rgba(34,197,94,.14);color:var(--green);border:1px solid rgba(34,197,94,.3)}
      .th-root .meta{color:var(--muted);font-size:12px}
      .th-root .meta strong{color:var(--text)}
      .th-root .thumb{width:100%;aspect-ratio:925/1364;background:var(--surface-alt) center/cover no-repeat;border:1px solid var(--border);border-radius:var(--r);display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:11px;overflow:hidden;position:relative}
      .th-root .thumb.thumb-real{background-size:cover;background-position:center;border-color:rgba(248,200,48,.3)}
      .th-root .thumb.thumb-real .play{background:rgba(10,10,10,.55);color:#fff;backdrop-filter:blur(4px)}
      .th-root .thumb.bru{background:var(--grad);color:#0A0A0A;font-weight:600;font-size:13px;gap:6px;border-color:transparent}
      .th-root .thumb .play{width:36px;height:36px;border-radius:50%;background:rgba(245,245,245,.9);color:var(--carbon);display:flex;align-items:center;justify-content:center;position:absolute;inset:0;margin:auto}
      .th-root .thumb-fb{aspect-ratio:1/1}
      .th-root .copy-preview{background:var(--surface-alt);border:1px solid var(--border);border-radius:var(--r);padding:10px 12px;font-size:12px;color:var(--muted);line-height:1.55;max-height:80px;overflow:hidden;position:relative}
      .th-root .copy-preview::after{content:'';position:absolute;bottom:0;left:0;right:0;height:20px;background:linear-gradient(180deg,transparent,var(--surface-alt))}
      .th-root .row-actions{display:flex;gap:6px;flex-wrap:wrap}
      .th-root .row-actions button{font-size:11px;padding:5px 10px}
      .th-root .upload-zone{border:1px dashed rgba(248,200,48,.5);border-radius:var(--r);padding:10px;text-align:center;color:var(--gold);font-size:11px;cursor:pointer;position:relative;transition:all .18s var(--trans)}
      .th-root .upload-zone:hover{background:rgba(248,200,48,.05);border-color:var(--gold)}
      .th-root .upload-zone.done{border-color:var(--green);color:var(--green);border-style:solid;background:rgba(34,197,94,.06)}
      .th-root .upload-zone.dragover{background:rgba(248,200,48,.10)}
      .th-root .upload-zone.uploading{opacity:.65;cursor:wait}
      .th-root .question-title{font-family:var(--font-d);font-size:14px;font-weight:600;margin-bottom:4px;color:var(--text)}
      .th-root .linkedin-head{display:flex;gap:12px;align-items:center}
      .th-root .avatar{width:42px;height:42px;border-radius:50%;background:var(--grad);display:flex;align-items:center;justify-content:center;color:#0A0A0A;font-family:var(--font-d);font-weight:700;font-size:15px;flex-shrink:0}
      .th-root .linkedin-name{font-size:13px;font-weight:600;color:var(--text)}
      .th-root .linkedin-role{color:var(--muted);font-size:11px}
      .th-root .li-msg-wrap{position:relative}
      .th-root .li-copy-icon{position:absolute;top:6px;right:6px;z-index:1;background:none;border:none;cursor:pointer;padding:4px;color:var(--muted);opacity:.45;border-radius:4px;display:flex;align-items:center;justify-content:center;line-height:1;transition:opacity .15s}
      .th-root .li-copy-icon:hover{opacity:1;background:var(--surface)}
      .th-root .fb-group-name{font-size:12px;color:var(--gold);font-weight:600;margin-bottom:2px}
      .th-root a{color:var(--gold);text-decoration:none}
      .th-root a:hover{text-decoration:underline}
    </style>
    """

    js = """
    <script>
    (function(){
      var root = document.getElementById('th-root');
      if(!root) return;
      // Tab switching
      root.querySelectorAll('.tab').forEach(function(t){
        t.addEventListener('click', function(){
          var key = t.getAttribute('data-tab');
          root.querySelectorAll('.tab').forEach(function(x){x.classList.remove('active');});
          root.querySelectorAll('.pane').forEach(function(x){x.classList.remove('active');});
          t.classList.add('active');
          var pane = root.querySelector('.pane[data-pane="'+key+'"]');
          if(pane) pane.classList.add('active');
        });
      });
      // Upload zones (reel masters)
      root.querySelectorAll('.upload-zone[data-pick]').forEach(function(zone){
        var input = zone.querySelector('input[type=file]');
        zone.addEventListener('click', function(){ if(input) input.click(); });
        zone.addEventListener('dragover', function(e){ e.preventDefault(); zone.classList.add('dragover'); });
        zone.addEventListener('dragleave', function(){ zone.classList.remove('dragover'); });
        zone.addEventListener('drop', function(e){
          e.preventDefault();
          zone.classList.remove('dragover');
          var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          if(f) thReelUpload(zone, f);
        });
        if(input){
          input.addEventListener('change', function(){
            if(input.files && input.files[0]) thReelUpload(zone, input.files[0]);
          });
        }
      });
    })();

    function thReelDownload(date, pick){
      fetch('/admin/api/reel-download', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify({date:date, pick_id:pick})})
        .then(function(r){ if(!r.ok) throw new Error('download failed'); return r.blob(); })
        .then(function(b){
          var url = URL.createObjectURL(b);
          var a = document.createElement('a'); a.href = url; a.download = 'reel_'+pick+'.zip';
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function(){ URL.revokeObjectURL(url); }, 500);
        })
        .catch(function(err){ alert('Download failed: '+err.message); });
    }

    function thReelVO(date, pick){
      var url = '/admin/social-ops/asset/' + encodeURIComponent('reel-cards/'+date+'/'+pick+'/vo_'+pick+'_v1.mp3');
      var a = new Audio(url);
      a.play().catch(function(){ window.open(url, '_blank'); });
    }

    function thReelUpload(zone, file){
      if(!file) return;
      zone.classList.add('uploading');
      var pick = zone.getAttribute('data-pick');
      var date = zone.getAttribute('data-date');
      var fd = new FormData();
      fd.append('file', file);
      fd.append('pick_id', pick);
      fd.append('date', date);
      fetch('/admin/api/task-hub/reel/'+encodeURIComponent(pick)+'/upload', {method:'POST', body: fd, credentials:'same-origin'})
        .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, body:j}; }); })
        .then(function(res){
          zone.classList.remove('uploading');
          if(res.ok && res.body && res.body.ok){
            zone.classList.add('done');
            zone.textContent = 'Uploaded \u2713 queued to MOQ';
          } else {
            alert('Upload failed');
          }
        })
        .catch(function(err){
          zone.classList.remove('uploading');
          alert('Upload error: '+err.message);
        });
    }

    function thCopyText(btn, text){
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(text).then(function(){
          var old = btn.innerHTML; btn.innerHTML = 'Copied'; setTimeout(function(){ btn.innerHTML = old; }, 1200);
        });
      } else {
        var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta);
        ta.select(); try { document.execCommand('copy'); } catch(e){}
        document.body.removeChild(ta);
      }
    }

    function thCopyIcon(btn, text){
      var svgCheck = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
      var old = btn.innerHTML;
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(text).then(function(){
          btn.innerHTML = svgCheck; btn.style.opacity='1'; btn.style.color='#22c55e';
          setTimeout(function(){ btn.innerHTML = old; btn.style.opacity=''; btn.style.color=''; }, 1500);
        }).catch(function(){ thCopyText(btn, text); });
      } else { thCopyText(btn, text); }
    }

    function _thMarkPostedGeneric(url, btn, card){
      btn.disabled = true;
      fetch(url, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'})
        .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, body:j}; }); })
        .then(function(res){
          if(res.ok && res.body && res.body.ok){
            if(card){ card.style.opacity='0.4'; }
            btn.innerHTML = 'Posted';
          } else {
            btn.disabled = false;
            alert('Update failed');
          }
        })
        .catch(function(err){
          btn.disabled = false;
          alert('Error: '+err.message);
        });
    }

    function thFbPosted(pid, btn){
      var card = btn.closest('.card');
      _thMarkPostedGeneric('/admin/api/task-hub/fb/'+encodeURIComponent(pid)+'/posted', btn, card);
    }
    function thQuoraPosted(pid, btn){
      var card = btn.closest('.card');
      _thMarkPostedGeneric('/admin/api/task-hub/quora/'+encodeURIComponent(pid)+'/posted', btn, card);
    }
    function thLinkedinSent(pid, btn){
      var card = btn.closest('.card');
      _thMarkPostedGeneric('/admin/api/task-hub/linkedin/'+encodeURIComponent(pid)+'/sent', btn, card);
    }
    </script>
    """

    workstreams = sum(1 for c in (reels, fb, quora, linkedin) if c)
    return f"""
<div id="th-root" class="th-root">
{css}
<div class="th-topbar">
  <h1 class="th-h1">Task Hub</h1>
  <span class="th-sync-pill">{_th_escape(pretty_date)} · {workstreams} workstreams · {total} items open</span>
</div>
<div class="kpi-strip">
  <div class="kpi"><div class="kpi-lbl">Reel kits</div><div class="kpi-val c-gold">{len(reels)}</div><div class="kpi-sub">to produce</div></div>
  <div class="kpi"><div class="kpi-lbl">FB group posts</div><div class="kpi-val c-text">{len(fb)}</div><div class="kpi-sub">scheduled today</div></div>
  <div class="kpi"><div class="kpi-lbl">Quora drafts</div><div class="kpi-val c-text">{len(quora)}</div><div class="kpi-sub">ready to post</div></div>
  <div class="kpi"><div class="kpi-lbl">LinkedIn targets</div><div class="kpi-val c-text">{len(linkedin)}</div><div class="kpi-sub">open</div></div>
  <div class="kpi"><div class="kpi-lbl">Total open</div><div class="kpi-val c-green">{total}</div><div class="kpi-sub">items</div></div>
</div>
<nav class="tabs">
  <div class="tab active" data-tab="reels">Reel Kits <span class="count">{len(reels)}</span></div>
  <div class="tab" data-tab="fb">FB Group Posts <span class="count">{len(fb)}</span></div>
  <div class="tab" data-tab="quora">Quora Answers <span class="count">{len(quora)}</span></div>
  <div class="tab" data-tab="linkedin">LinkedIn Connections <span class="count">{len(linkedin)}</span></div>
</nav>
<main>
  <section class="pane active" data-pane="reels">
    <div class="pane-header">
      <div>
        <div class="pane-title">Reel Kits — ready for production</div>
        <div class="pane-sub">Download kit · produce .mp4 in Premiere · upload master → auto-publishes to IG + TikTok</div>
      </div>
    </div>
    <div class="grid reels">{reel_cards}</div>
  </section>
  <section class="pane" data-pane="fb">
    <div class="pane-header">
      <div>
        <div class="pane-title">FB Group Posts — scheduled for today</div>
        <div class="pane-sub">Copy text · post to the group · mark done when live</div>
      </div>
    </div>
    <div class="grid fb">{fb_cards}</div>
  </section>
  <section class="pane" data-pane="quora">
    <div class="pane-header">
      <div>
        <div class="pane-title">Quora Answers — drafts ready to post</div>
        <div class="pane-sub">Open on Quora · post the draft · mark done</div>
      </div>
    </div>
    <div class="grid quora">{quora_cards}</div>
  </section>
  <section class="pane" data-pane="linkedin">
    <div class="pane-header">
      <div>
        <div class="pane-title">LinkedIn Connections — outreach queue</div>
        <div class="pane-sub">Open profile · send connect/message · mark sent</div>
      </div>
    </div>
    <div class="grid linkedin">{linkedin_cards}</div>
  </section>
</main>
</div>
{js}
"""


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


# -- Publisher exception health -----------------------------------------------

_PUBLISHER_EXCEPTIONS_LOG = Path("/home/paulsportsza/publisher/logs/exceptions.jsonl")


def _read_publisher_exceptions() -> dict:
    """Read publisher exception signals from append-only JSONL log."""
    result = {
        "publisher_last_exception_at": None,
        "publisher_exceptions_24h": 0,
        "publisher_exceptions_72h": 0,
        "recent": [],
    }
    if not _PUBLISHER_EXCEPTIONS_LOG.exists():
        return result
    try:
        now = datetime.now(_SAST)
        cutoff_24h = now - timedelta(hours=24)
        cutoff_72h = now - timedelta(hours=72)
        events = []
        with open(_PUBLISHER_EXCEPTIONS_LOG) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    ts_str = ev.get("timestamp", "")
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    ev["_ts"] = ts
                    events.append(ev)
                except Exception:
                    continue
        events.sort(key=lambda e: e["_ts"], reverse=True)
        if events:
            result["publisher_last_exception_at"] = events[0]["timestamp"]
        result["publisher_exceptions_24h"] = sum(1 for e in events if e["_ts"] >= cutoff_24h)
        result["publisher_exceptions_72h"] = sum(1 for e in events if e["_ts"] >= cutoff_72h)
        result["recent"] = events[:5]
    except Exception:
        pass
    return result


# -- System Health renderer ---------------------------------------------------

def render_system_health_content(conn) -> str:
    """Render the System Health monitoring view."""
    sentry   = _fetch_sentry_data()
    res      = _read_server_resources()
    procs    = _read_process_monitor()
    api_rows = _build_api_health(conn)
    pub_exc  = _read_publisher_exceptions()
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

    # ── Panel 5: Publisher Exception Health ───────────────────────────────────
    exc_24h = pub_exc["publisher_exceptions_24h"]
    exc_72h = pub_exc["publisher_exceptions_72h"]
    last_exc = pub_exc["publisher_last_exception_at"] or "—"
    if exc_24h >= 1:
        pub_css = "var(--red)"
        pub_status_label = "RED — exception in last 24h"
    elif exc_72h > 0:
        pub_css = "var(--amber)"
        pub_status_label = "AMBER — exception in last 72h"
    else:
        pub_css = "var(--green)"
        pub_status_label = "GREEN — no recent exceptions"
    pub_dot = f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{pub_css};margin-right:8px;vertical-align:middle"></span>'
    recent_rows = ""
    for ev in pub_exc["recent"]:
        ts_disp = ev.get("timestamp", "")[:19].replace("T", " ")
        exc_type = ev.get("exception_type", "")
        msg = ev.get("message", "")[:80]
        recent_rows += (
            f'<tr>'
            f'<td style="padding:5px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{ts_disp}</td>'
            f'<td style="padding:5px 12px;font-family:var(--font-d);font-size:11px;font-weight:600">{exc_type}</td>'
            f'<td style="padding:5px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{msg}</td>'
            f'</tr>'
        )
    recent_table = (
        f'<div class="tbl-wrap"><table class="tbl">'
        f'<thead><tr><th>Timestamp (UTC)</th><th>Exception</th><th>Message</th></tr></thead>'
        f'<tbody>{recent_rows if recent_rows else "<tr><td colspan=3 style=padding:12px;color:var(--muted);text-align:center>No exceptions logged</td></tr>"}</tbody>'
        f'</table></div>'
    ) if pub_exc["recent"] or True else ""
    publisher_exc_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Publisher Exception Health</span>'
        f'<span class="panel-sub">publisher/logs/exceptions.jsonl</span>'
        f'</div>'
        f'<div style="padding:12px 16px;display:flex;gap:24px;flex-wrap:wrap;align-items:center">'
        f'<div style="font-family:var(--font-d);font-size:12px">{pub_dot}<span style="color:{pub_css};font-weight:700">{pub_status_label}</span></div>'
        f'<div style="font-family:var(--font-m);font-size:12px;color:var(--muted)">publisher_exceptions_24h: <b style="color:{"var(--red)" if exc_24h else "var(--green)"}">{exc_24h}</b></div>'
        f'<div style="font-family:var(--font-m);font-size:12px;color:var(--muted)">publisher_last_exception_at: <b>{last_exc}</b></div>'
        f'</div>'
        f'{recent_table}'
        f'</div>'
    )

    return f"""{topbar}
<div class="page">
  <div class="grid-2">
    {sentry_panel}
    {resources_panel}
    {processes_panel}
    {api_panel}
    {publisher_exc_panel}
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
  /* Performance scope — one-line KPI strip + gradient top line on every panel */
  .perf-scope .kpi-strip { grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 16px; }
  .perf-scope .kpi { padding: 10px 12px; }
  .perf-scope .kpi-lbl { font-size: 9px; margin-bottom: 6px; }
  .perf-scope .kpi-val { font-size: 20px; }
  .perf-scope .kpi-sub { font-size: 10px; margin-top: 3px; }
  .perf-scope .panel { box-shadow: var(--glow); }
  .perf-scope .panel::after { content:''; position:absolute; top:0; left:0; right:0; height:2px; background:var(--grad); opacity:0.45; pointer-events:none; z-index:1; }
  @media (max-width: 1200px) { .perf-scope .kpi-strip { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 700px)  { .perf-scope .kpi-strip { grid-template-columns: repeat(2, 1fr); } }
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
            pass  # timezone import removed — using module-level _SAST
            _th_last = datetime.fromisoformat(_thf.read().strip())
            _th_age_h = round((datetime.now(_SAST) - _th_last).total_seconds() / 3600, 1)
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

    # ---- CLV Pipeline Health panel (SO #36, EDGE-REMEDIATION-02) ----
    _CLV_SOURCE_IDS = (
        "sharp_closing_capture",
        "sharp_clv_backfill",
        "sharp_clv_tracker",
        "sharp_clv_kill_monitor",
    )
    _clv_reg: dict = {}
    _clv_health_map: dict = {}
    try:
        if table_exists(conn, "source_registry"):
            for _r in q_all(conn, "SELECT source_id, expected_interval_minutes FROM source_registry WHERE source_id IN (?,?,?,?)", _CLV_SOURCE_IDS):
                _clv_reg[_r["source_id"]] = _r
    except Exception:
        pass
    try:
        if table_exists(conn, "source_health_current"):
            for _r in q_all(conn, "SELECT source_id, status, last_success_at, consecutive_failures FROM source_health_current WHERE source_id IN (?,?,?,?)", _CLV_SOURCE_IDS):
                _clv_health_map[_r["source_id"]] = _r
    except Exception:
        pass
    _clv_pipe_rows = ""
    _clv_any_breach = False
    _clv_breach_count = 0
    for _src_id in _CLV_SOURCE_IDS:
        _cp_name = _src_id.replace("sharp_", "", 1)
        _cp_reg = _clv_reg.get(_src_id)
        _cp_h = _clv_health_map.get(_src_id)
        _cp_sla = _cp_reg["expected_interval_minutes"] if _cp_reg else 99999
        _cp_status = "unknown"
        _cp_items = "—"

        # Status + last_success from canonical source_health_current
        if _cp_h:
            _db_status = _cp_h["status"] or "unknown"
            _db_last = _cp_h["last_success_at"]
            try:
                _cp_last_run = datetime.fromisoformat(_db_last.replace("Z", "+00:00")) if _db_last else None
            except (ValueError, AttributeError):
                _cp_last_run = None
        else:
            _db_status = "unknown"
            _cp_last_run = None

        if _db_status in ("red", "black"):
            _clv_any_breach = True
        if _db_status not in ("green", "unknown"):
            _clv_breach_count += 1

        # Get item counts from DB
        try:
            if _cp_name == "closing_capture":
                _row = q_one(conn, "SELECT COUNT(*) as cnt FROM odds_closing_sa WHERE captured_at > datetime('now', '-1 day')")
                _cp_items = str(_row["cnt"]) if _row else "0"
            elif _cp_name == "clv_backfill":
                _row = q_one(conn, "SELECT COUNT(*) as cnt FROM bet_recommendations_log WHERE clv IS NOT NULL AND closed_at > datetime('now', '-1 day')")
                _cp_items = str(_row["cnt"]) if _row else "0"
            elif _cp_name == "clv_tracker":
                _row = q_one(conn, "SELECT COUNT(*) as cnt FROM clv_tracking WHERE calculated_at > datetime('now', '-1 day')")
                _cp_items = str(_row["cnt"]) if _row else "0"
            elif _cp_name == "clv_kill_monitor":
                _km_row = q_one(conn, "SELECT enabled, window_neg_pct FROM model_kill_flags WHERE flag_name='clv_tracking'")
                if _km_row:
                    _km_enabled = _km_row["enabled"]
                    _neg_pct = _km_row["window_neg_pct"]
                    _cp_items = f"{'active' if _km_enabled else 'KILLED'}"
                    if _neg_pct is not None:
                        _cp_items += f" ({_neg_pct:.0%} neg)"
        except Exception:
            pass

        _ts_str = _cp_last_run.strftime("%H:%M") if _cp_last_run else "never"
        if _db_status == "green":
            _s_cls, _s_dot = "s-green", "🟢"
        elif _db_status == "yellow":
            _s_cls, _s_dot = "s-amber", "🟡"
        elif _db_status == "red":
            _s_cls, _s_dot = "s-red", "🔴"
        elif _db_status == "black":
            _s_cls, _s_dot = "s-black", "⚫"
        else:
            _s_cls, _s_dot = "s-grey", "⚪"
        _sla_display = f"{_cp_sla}m" if _cp_reg else "—"
        _clv_pipe_rows += f"""
      <tr>
        <td>{_s_dot} {_cp_name}</td>
        <td class="{_s_cls}">{_ts_str}</td>
        <td>{_sla_display}</td>
        <td>{_cp_items}</td>
      </tr>"""

    _clv_pipe_panel = f"""
<div class="panel {'panel-red-accent' if _clv_any_breach else 'panel-orange-accent'}" style="margin-bottom:16px;">
  <div class="panel-head">
    <span class="panel-title">CLV Pipeline Health</span>
    <span class="panel-sub">{'✅ HEALTHY' if _clv_breach_count == 0 else f'⚠️ {_clv_breach_count} BREACHING'}</span>
  </div>
  <div class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th>Component</th><th>Last Run</th><th>SLA</th><th>Items (24h)</th>
      </tr></thead>
      <tbody>{_clv_pipe_rows}</tbody>
    </table>
  </div>
</div>"""

    # ---- Assemble page ----
    return f"""
<style>{_perf_css()}</style>
<div class="perf-scope">
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
  {_clv_pipe_panel}
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
</div>
</div>"""



# -- Unified System Health renderer -------------------------------------------

def render_unified_health_content(conn, db_status: str) -> str:
    """Unified System Health view — tabbed layout (Overview / Alerts / Sources / System)."""
    # ── Gather all data ───────────────────────────────────────────────────────
    sentry   = _fetch_sentry_data()
    res      = _read_server_resources()
    procs    = _read_process_monitor()
    api_rows = _build_api_health(conn)
    pub_exc  = _read_publisher_exceptions()
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
        _cur_st = a.get("current_status") or ""
        still_degraded_badge = (
            '<span style="background:rgba(245,158,11,0.1);color:var(--amber);border:1px solid rgba(245,158,11,0.2);'
            'border-radius:999px;padding:1px 7px;font-size:10px;font-weight:700;font-family:var(--font-d);margin-left:6px">source still degraded</span>'
            if a["resolved"] and _cur_st and _cur_st not in ("green", "") else ""
        )
        return (
            f'<div class="alert-row">'
            f'<span class="alert-ts">{a["ts"]} SAST</span>'
            f'<span style="color:{sev_col};font-size:13px;flex-shrink:0">{sev_icon}</span>'
            f'<div style="min-width:0">'
            f'<div style="font-family:var(--font-d);font-size:11px;font-weight:700;color:var(--text)">{a["source_name"]}</div>'
            f'<div class="alert-msg">{_truncate(a["message"], 120)}{resolved_badge}{still_degraded_badge}</div>'
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

    # ── Publisher Exception Health panel ─────────────────────────────────────
    _exc_24h = pub_exc["publisher_exceptions_24h"]
    _exc_72h = pub_exc["publisher_exceptions_72h"]
    _last_exc = pub_exc["publisher_last_exception_at"] or "—"
    if _exc_24h >= 1:
        _pub_css = "var(--red)"
        _pub_lbl = "RED — exception in last 24h"
    elif _exc_72h > 0:
        _pub_css = "var(--amber)"
        _pub_lbl = "AMBER — exception in last 72h, clean last 24h"
    else:
        _pub_css = "var(--green)"
        _pub_lbl = "GREEN — no recent exceptions"
    _pub_dot = f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{_pub_css};margin-right:8px;vertical-align:middle"></span>'
    _exc_rows = ""
    for _ev in pub_exc["recent"]:
        _ts_d = _ev.get("timestamp", "")[:19].replace("T", " ")
        _exc_t = _ev.get("exception_type", "")
        _msg   = _ev.get("message", "")[:80]
        _exc_rows += (
            f'<tr>'
            f'<td style="padding:5px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted)">{_ts_d}</td>'
            f'<td style="padding:5px 12px;font-family:var(--font-d);font-size:11px;font-weight:600">{_exc_t}</td>'
            f'<td style="padding:5px 12px;font-family:var(--font-m);font-size:11px;color:var(--muted);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{_msg}</td>'
            f'</tr>'
        )
    _no_exc_row = '<tr><td colspan="3" style="padding:12px;color:var(--muted);text-align:center">No exceptions logged</td></tr>'
    publisher_exc_panel = (
        f'<div class="panel"><div class="panel-head">'
        f'<span class="panel-title">Publisher Exception Health</span>'
        f'<span class="panel-sub">publisher/logs/exceptions.jsonl</span>'
        f'</div>'
        f'<div style="padding:12px 16px;display:flex;gap:24px;flex-wrap:wrap;align-items:center">'
        f'<div style="font-family:var(--font-d);font-size:12px">{_pub_dot}<span style="color:{_pub_css};font-weight:700">{_pub_lbl}</span></div>'
        f'<div style="font-family:var(--font-m);font-size:12px;color:var(--muted)">publisher_exceptions_24h:&nbsp;<b style="color:{"var(--red)" if _exc_24h else "var(--green)"}">{_exc_24h}</b></div>'
        f'<div style="font-family:var(--font-m);font-size:12px;color:var(--muted)">publisher_last_exception_at:&nbsp;<b>{_last_exc}</b></div>'
        f'</div>'
        f'<div class="tbl-wrap"><table class="tbl">'
        f'<thead><tr><th>Timestamp (UTC)</th><th>Exception</th><th>Message</th></tr></thead>'
        f'<tbody>{_exc_rows if _exc_rows else _no_exc_row}</tbody></table></div>'
        f'</div>'
    )

    tab_system = f"""<div id="tab-system" class="tab-pane">
  <div class="grid-2">
    {resources_panel}
    {processes_panel}
    {publisher_exc_panel}
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
function coverageInit() {{
  var details = document.querySelector('#tab-overview details');
  if (details) {{
    details.addEventListener('toggle', function() {{
      if (details.open) initCoverageChart();
    }});
  }}
  // Also try init immediately if accordion already open
  initCoverageChart();
}}
if (document.readyState !== 'loading') {{ coverageInit(); }} else {{ document.addEventListener('DOMContentLoaded', coverageInit); }}

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


def _bg_refresh_social_ops() -> None:
    try:
        content = render_automation_content()
        html_out = render_shell("social_ops", content)
        with _page_cache_lock:
            _page_cache["social_ops_full"] = (html_out, time.monotonic())
    except Exception:
        if _sentry is not None:
            _sentry.capture_exception()
    finally:
        with _page_cache_lock:
            _page_refresh_inflight.discard("social_ops_full")



# --- v3 cache-control helper -----------------------------------------
def _no_store(resp: 'Response') -> 'Response':
    """Add headers so Paul's browser never serves a stale Task Hub /
    Social Ops page. We use SWR in-process cache on the server side
    already; the browser must always revalidate."""
    try:
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    except Exception:
        pass
    return resp


@app.route("/admin/social-ops")
@require_auth
def admin_social_ops():
    now = time.monotonic()
    should_refresh = False
    with _page_cache_lock:
        cached = _page_cache.get("social_ops_full")
        age = (now - cached[1]) if cached else None
        if cached and age is not None and age < _PAGE_CACHE_SWR:
            # Fresh enough to serve. If stale (past TTL) but within SWR window,
            # kick off a single background refresh — never block the response.
            if age >= _PAGE_CACHE_TTL and "social_ops_full" not in _page_refresh_inflight:
                _page_refresh_inflight.add("social_ops_full")
                should_refresh = True
            payload = cached[0]
        else:
            payload = None

    if should_refresh:
        threading.Thread(
            target=_bg_refresh_social_ops,
            name="so-refresh",
            daemon=True,
        ).start()

    if payload is not None:
        request._cache_state = "swr-refresh" if should_refresh else "hit"
        return _no_store(Response(payload, mimetype="text/html"))

    content = render_automation_content()
    html_out = render_shell("social_ops", content)

    with _page_cache_lock:
        _page_cache["social_ops_full"] = (html_out, now)

    return _no_store(Response(html_out, mimetype="text/html"))


@app.route("/admin/automation")
@require_auth
def admin_automation():
    return redirect("/admin/social-ops", code=302)


@app.route("/admin/system")
@require_auth
def admin_system():
    return redirect("/admin/health", code=302)


@app.route("/admin/customers")
@require_auth
def admin_customers_redirect():
    return redirect("/admin/system", code=302)



@app.route("/admin/api/task_hub_badge")
@require_auth
def api_task_hub_badge():
    """Return live badge count for Social Ops — only failed/blocked items."""
    try:
        mq, _ = _fetch_marketing_queue()
        count = sum(
            1 for it in mq
            if (it.get("status") or "").lower().strip() in ("failed", "blocked", "error")
        )
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
            request._cache_state = "hit"
            return _no_store(Response(cached[0], mimetype="text/html"))

    conn = db_connect(SCRAPERS_DB)
    db_status = "Connected" if conn else "Unreachable"
    try:
        content = render_unified_health_content(conn, db_status)
    finally:
        if conn:
            conn.close()

    with _page_cache_lock:
        _page_cache["health_content"] = (content, now)

    return _no_store(Response(content, mimetype="text/html"))


@app.route("/admin/api/automation")
@require_auth
def api_automation():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("automation_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            request._cache_state = "hit"
            return _no_store(Response(cached[0], mimetype="text/html"))

    content = render_automation_content()

    with _page_cache_lock:
        _page_cache["automation_content"] = (content, now)

    return _no_store(Response(content, mimetype="text/html"))


@app.route("/admin/api/social_ops")
@require_auth
def api_social_ops():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("social_ops_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return _no_store(Response(cached[0], mimetype="text/html"))
    content = render_automation_content()
    with _page_cache_lock:
        _page_cache["social_ops_content"] = (content, now)
    return _no_store(Response(content, mimetype="text/html"))


_SO_TL_CH = [
    ("telegram_alerts",    "TG Alerts"),
    ("telegram_community", "TG Community"),
    ("whatsapp_channel",   "WA Channel"),
    ("instagram",          "Instagram"),
    ("tiktok",             "TikTok"),
]
_SO_POSTED_ST = {"published", "done", "complete", "posted"}
_SO_PENDING_ST = {"pending", "queued", "scheduled", "ready", "approved"}
_SO_FAILED_ST  = {"failed", "error", "blocked"}


_SO_GLYPHS: dict[str, str] = {
    "card_diamond":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="1.5"/><path d="M12 7.5 L15.5 12 L12 16.5 L8.5 12 Z" fill="currentColor" stroke="none"/></svg>',
    "bar_chart":       '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="14" width="3.5" height="7" rx="0.5"/><rect x="8.5" y="10" width="3.5" height="11" rx="0.5"/><rect x="14" y="6" width="3.5" height="15" rx="0.5"/><rect x="19.5" y="12" width="3.5" height="9" rx="0.5"/></svg>',
    "poll":            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 5 Q3 3 5 3 H19 Q21 3 21 5 V14 Q21 16 19 16 H10 L6 20 V16 Q3 16 3 14 Z"/><rect x="7" y="10" width="2" height="4" fill="currentColor" stroke="none"/><rect x="11" y="8" width="2" height="6" fill="currentColor" stroke="none"/><rect x="15" y="6" width="2" height="8" fill="currentColor" stroke="none"/></svg>',
    "football":        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 5 L15 8 L14 12 L10 12 L9 8 Z" fill="currentColor" opacity="0.3"/><path d="M12 5 V3"/><path d="M15 8 L18 7"/><path d="M14 12 L17 14"/><path d="M10 12 L7 14"/><path d="M9 8 L6 7"/></svg>',
    "rugby":           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><ellipse cx="12" cy="12" rx="9" ry="5.5" transform="rotate(-30 12 12)"/><line x1="7" y1="14" x2="17" y2="9.5"/><line x1="9" y1="15" x2="10.3" y2="14.5"/><line x1="11.3" y1="13.5" x2="12.6" y2="13"/><line x1="13.7" y1="12" x2="15" y2="11.5"/></svg>',
    "cricket":         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="14" y="2" width="3" height="16" rx="1" transform="rotate(25 15.5 10)" fill="currentColor" opacity="0.6"/><line x1="12" y1="18" x2="14" y2="20" stroke-width="2.2"/><circle cx="7" cy="17" r="3"/><line x1="5.5" y1="16" x2="6" y2="16.8"/><line x1="7" y1="15.5" x2="7.3" y2="16.4"/></svg>',
    "discussion_seed": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M2 6 Q2 4 4 4 H13 Q15 4 15 6 V11 Q15 13 13 13 H7 L4 15.5 V13 Q2 13 2 11 Z"/><path d="M9 10 Q9 8.5 10.5 8.5 H20 Q22 8.5 22 10.5 V15 Q22 17 20 17 H16 L19 20 V17" fill="#111111"/></svg>',
    "newspaper":       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="1"/><rect x="5" y="6.5" width="6.5" height="4" fill="currentColor" opacity="0.25"/><line x1="13" y1="7" x2="19" y2="7"/><line x1="13" y1="9" x2="19" y2="9"/><line x1="5" y1="13" x2="19" y2="13"/><line x1="5" y1="15" x2="19" y2="15"/><line x1="5" y1="17" x2="14" y2="17"/></svg>',
    "stacked_cards":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="7" y="3" width="13" height="13" rx="2" fill="#111111"/><rect x="4" y="7" width="13" height="13" rx="2" fill="#111111"/></svg>',
    "photo_frame":     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5" fill="currentColor"/><path d="M21 15 L16 10 L5 21"/></svg>',
    "bru":             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="4" y="7" width="16" height="12" rx="2.5"/><line x1="12" y1="4" x2="12" y2="7"/><circle cx="12" cy="3.5" r="1" fill="currentColor"/><circle cx="9" cy="12" r="1.2" fill="currentColor"/><circle cx="15" cy="12" r="1.2" fill="currentColor"/><line x1="9" y1="16" x2="15" y2="16"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/></svg>',
}

# Rate-limit unknown-sport Sentry warnings: one per (sport_value, YYYY-MM-DD)
_SO_UNKNOWN_SPORT_WARNED: set[tuple[str, str]] = set()


def _so_icon_for(wt: str, ck: str) -> str:
    w = (wt or "").lower()
    if "seed chat" in w:                 return "message-circle"
    if "morning" in w:                   return "sun"
    if "news" in w:                      return "newspaper"
    if "edge card" in w or "diamond" in w or "edge" in w: return "diamond"
    if "recap" in w:                     return "trophy"
    if "teaser" in w:                    return "eye"
    if "poll" in w or "discuss" in w:    return "message-square-more"
    if "alert" in w:                     return "bell"
    if "reel" in w:                      return "play-circle"
    if "carousel" in w:                  return "layers"
    if "story" in w:                     return "circle"
    if "b.r.u" in w or "bru" in w:       return "bot"
    if "article" in w:                   return "book-open"
    if "answer" in w:                    return "message-square-quote"
    if "image" in w or "photo" in w:     return "image"
    if "chat" in w:                      return "message-circle"
    _fb = {"tiktok": "bot", "telegram_alerts": "message-circle",
           "telegram_community": "message-square-more",
           "whatsapp_channel": "bell", "whatsapp_group": "message-square-more",
           "instagram": "image", "linkedin": "briefcase",
           "fb_groups": "message-square", "quora": "message-square-quote",
           "threads": "at-sign"}
    return _fb.get(ck, "help-circle")


def _so_norm_channel(ch_raw: str) -> str:
    c = (ch_raw or "").lower()
    if "group" in c and ("whatsapp" in c or " wa" in c or c.startswith("wa")):
        return "whatsapp_group"
    return _normalise_channel_key(ch_raw)


def _pick_glyph_for_row(row: dict) -> str:
    """Return the inline-SVG glyph string for a MOQ row.

    Work-type keywords are the primary driver; channel is only used as a
    tiebreaker where the same keyword can mean different things on different
    lanes (e.g. "recap" → bar_chart on TG Alerts, newspaper on WA Channel),
    and as a final fallback when no keyword matches.

    Keyword → glyph mapping (from mockup social-ops-icons-19apr.html):
      bru/b.r.u or tiktok channel  → bru
      match + sport field          → football / rugby / cricket / discussion_seed
      poll                         → poll
      seed / discuss               → discussion_seed
      p&l / pnl / chart / stat     → bar_chart
      recap / wrap / weekly / summary
        on TG Alerts               → bar_chart  (performance summary)
        elsewhere                  → newspaper  (content digest)
      morning / evening / digest / news → newspaper
      reel                         → card_diamond
      carousel                     → stacked_cards
      story / photo / image        → photo_frame
      alert / edge / diamond / card / teaser → card_diamond
      channel fallback:
        telegram_alerts            → card_diamond
        whatsapp_*                 → newspaper
        telegram_community         → discussion_seed
        instagram                  → photo_frame
    """
    from datetime import date as _date

    # Combine work_type + title so keyword checks work against real Notion data.
    # work_type is always "Social"/"BRU"/empty; the actual post type lives in title.
    w  = ((row.get("work_type") or "") + " " + (row.get("title") or "")).lower()
    ch = _so_norm_channel(row.get("channel") or "")

    # ── BRU / TikTok ──────────────────────────────────────────────────────
    if ch == "tiktok" or "b.r.u" in w or "bru" in w:
        return _SO_GLYPHS["bru"]

    # ── Match thread — sport inferred from title (Sport field always empty) ─
    if "match thread" in w:
        if "rugby" in w or "urc" in w or "stormers" in w or "bulls" in w or "sharks" in w or "lions" in w or "springbok" in w:
            return _SO_GLYPHS["rugby"]
        if "cricket" in w or "ipl" in w or "proteas" in w or "sa20" in w or "t20" in w:
            return _SO_GLYPHS["cricket"]
        # Default match thread = football/soccer
        return _SO_GLYPHS["football"]

    # ── Poll ──────────────────────────────────────────────────────────────
    if "poll" in w:
        return _SO_GLYPHS["poll"]

    # ── Discussion / seed chat ────────────────────────────────────────────
    if "seed" in w or "discuss" in w:
        return _SO_GLYPHS["discussion_seed"]

    # ── Hard stats / P&L → bar_chart ─────────────────────────────────────
    if "p&l" in w or "pnl" in w or "chart" in w or "stat" in w:
        return _SO_GLYPHS["bar_chart"]

    # ── Recap / wrap / weekly / summary ──────────────────────────────────
    # TG Alerts: performance summary → bar_chart
    # All other channels: content digest → newspaper
    if "recap" in w or "wrap" in w or "weekly" in w or "summary" in w:
        return _SO_GLYPHS["bar_chart"] if ch == "telegram_alerts" else _SO_GLYPHS["newspaper"]

    # ── Morning / evening / digest → newspaper ───────────────────────────
    # "news" excluded here: "TG News" on telegram_alerts is an alert post (card_diamond),
    # not a digest. Channel fallback handles that case below.
    if "morning" in w or "evening" in w or "digest" in w or "brief" in w or "midday" in w:
        return _SO_GLYPHS["newspaper"]

    # ── Instagram subtypes (channel-specific) ─────────────────────────────
    if ch == "instagram":
        if "reel" in w:
            return _SO_GLYPHS["card_diamond"]
        if "carousel" in w:
            return _SO_GLYPHS["stacked_cards"]
        return _SO_GLYPHS["photo_frame"]

    # ── Reel / carousel / photo (non-Instagram fallback) ──────────────────
    if "reel" in w:
        return _SO_GLYPHS["card_diamond"]
    if "carousel" in w:
        return _SO_GLYPHS["stacked_cards"]
    if "story" in w or "photo" in w or "image" in w:
        return _SO_GLYPHS["photo_frame"]

    # ── Edge picks / alerts / cards ───────────────────────────────────────
    if "alert" in w or "edge" in w or "diamond" in w or "card" in w or "teaser" in w:
        return _SO_GLYPHS["card_diamond"]

    # ── Channel-level fallbacks ───────────────────────────────────────────
    if ch == "telegram_alerts":
        return _SO_GLYPHS["card_diamond"]
    if ch in ("whatsapp_channel", "whatsapp_group"):
        return _SO_GLYPHS["newspaper"]
    if ch == "telegram_community":
        return _SO_GLYPHS["discussion_seed"]
    if ch == "instagram":
        return _SO_GLYPHS["photo_frame"]
    return _SO_GLYPHS["discussion_seed"]


_SO_COMPUTER_URL_RE = re.compile(
    r"^computer://[^/]*/sessions/[^/]+/mnt/(?:MzansiEdge/)?assets/(.+)$"
)


def _cache_bust_mzansi_asset(url: str) -> str:
    """Append ?v=<mtime> to mzansiedge.co.za/assets URLs so browsers refresh
    after the generator rewrites the same filename. nginx sends immutable
    cache headers on this path, so URL-level busting is the only reliable
    way to serve the fresh PNG on regen."""
    if not url or "mzansiedge.co.za/assets/" not in url:
        return url
    if "?" in url or "#" in url:
        return url  # already has a query — leave it
    try:
        from urllib.parse import urlparse as _urlparse
        rel = _urlparse(url).path.split("/assets/", 1)[-1]
        local = os.path.join("/var/www/mzansiedge-wp/assets", rel)
        if os.path.isfile(local):
            return f"{url}?v={int(os.path.getmtime(local))}"
    except Exception:
        pass
    return url


def _resolve_media_url(raw: str) -> str:
    """Translate an MOQ-stored URL into a browser-loadable URL.

    MOQ "Image URL"/"Video URL"/"Asset URL" columns often contain Claude-session
    paths (``computer:///sessions/<id>/mnt/MzansiEdge/assets/<sub>/<file>``) which
    no browser can resolve — they render as black <img> boxes. This helper maps
    the trailing ``<sub>/<file>`` segment onto the first existing file under
    _SO_ASSET_ROOTS and returns a dashboard-served path. Real HTTP(S) URLs and
    paths already rooted at '/' are passed through untouched. Unresolvable URLs
    return "" so the frontend renders the text-only branch (no black box).
    """
    if not raw:
        return ""
    s = raw.strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith(("http://", "https://", "//")):
        return _cache_bust_mzansi_asset(s)
    if s.startswith("/admin/social-ops/asset/") or s.startswith("/static/"):
        return s
    m = _SO_COMPUTER_URL_RE.match(s)
    if not m:
        return ""
    rel = m.group(1).lstrip("/")
    if ".." in rel.split("/"):
        return ""
    for root in _SO_ASSET_ROOTS:
        candidate = os.path.normpath(os.path.join(root, rel))
        if not candidate.startswith(os.path.normpath(root) + os.sep):
            continue
        if os.path.isfile(candidate):
            return f"/admin/social-ops/asset/{rel}"
    return ""


def _so_extract_pick_id(item: dict) -> str:
    """Best-effort pick_id extraction from a Notion MOQ item.

    Looks at title + copy for a pick_id-shaped token (alnum + _/-, 6-40 chars).
    Returns "" when nothing confidently matches.
    """
    for field in ("title", "copy", "campaign_theme", "platform_notes"):
        text = item.get(field) or ""
        if not text:
            continue
        for token in re.findall(r"\b([A-Za-z0-9][A-Za-z0-9_-]{5,39})\b", text):
            if "_" in token or "-" in token:
                if _RE_PICK_ID.match(token):
                    return token
    return ""


def _reel_has_final(page_id: str, date_str: str) -> bool:
    """True if a master MP4 has been uploaded for this MOQ row (Social Ops upload flow)."""
    if not page_id or not date_str:
        return False
    return os.path.isfile(os.path.join(_REEL_FINALS_ROOT, date_str, "final", f"{page_id}.mp4"))


def _so_platform_icon_svg(ck: str) -> str:
    """Inline SVG platform icon for the 7 publisher channels. 20×20, currentColor stroke."""
    _ICONS = {
        "telegram_alerts":
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
        "telegram_community":
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="13" y2="14"/></svg>',
        "whatsapp_channel":
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/><polyline points="9 11 12 14 15 11"/></svg>',
        "whatsapp_group":
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        "instagram":
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg>',
        "tiktok":
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 12a4 4 0 1 0 4 4V4a5 5 0 0 0 5 5"/></svg>',
        "threads":
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 8c-2.8 0-5 1.8-5 5s2.2 5 5 5c3 0 5-1.5 5-4"/><path d="M12 8c0-3 1.5-5 4-5"/></svg>',
    }
    return _ICONS.get(ck, "")


_SO_OVERDUE_QUEUE_ST = {"pending", "ready", "queued"}


def _bru_drip_items_for_day(day_str: str) -> list[dict]:
    """Return B.R.U. drip virtual post items for the given SAST day.

    Reads the bru_drip sidecar queue (state/bru_queue.json) and reconstructs
    the video list using the same deterministic shuffle as bru_drip.py.
    Dashboard read-only — never modifies bru_drip.py or the queue.

    Cron: 0 9 */2 * * → 09:00 SAST on odd days of month.
    Epoch: 2026-04-19 → fires video at queue position 1.
    Returns [] when queue exhausted or day is not a drip day.
    """
    import json as _json
    import random as _random
    from datetime import date as _date, timedelta as _timedelta, datetime as _dt
    from pathlib import Path as _Path
    from zoneinfo import ZoneInfo as _ZI

    _QUEUE_FILE = _Path("/home/paulsportsza/publisher/state/bru_queue.json")
    _PHASE2_DIR = _Path("/var/www/mzansiedge-wp/assets/bru/phase2")
    _PHASE3_DIR = _Path("/var/www/mzansiedge-wp/assets/bru/phase3")
    _SHUFFLE_SEED = 2026
    _DRIP_EPOCH    = _date(2026, 4, 19)  # First drip day; fires video at position 1
    _DRIP_EPOCH_POS = 1                  # Queue position on epoch date
    _DRIP_HOUR     = 11                  # 11:00 SAST (matches cron `0 9 */2 * *` UTC — see PUBLISHER-HYGIENE-SWEEP-01)

    try:
        day = _date.fromisoformat(day_str)
    except ValueError:
        return []

    # Cron fires on odd days of month only
    if day.day % 2 == 0:
        return []

    try:
        state = _json.loads(_QUEUE_FILE.read_text())
    except (OSError, ValueError):
        return []

    # Count drip days between epoch (exclusive) and requested day (inclusive)
    # to derive the video index for that day.
    offset = 0
    cur = _DRIP_EPOCH
    while cur < day:
        cur += _timedelta(days=1)
        if cur.day % 2 == 1:
            offset += 1
    video_idx = _DRIP_EPOCH_POS + offset

    # Reconstruct video list — mirrors bru_drip._scan_videos exactly
    videos: list[dict] = []
    if _PHASE2_DIR.is_dir():
        for mp4 in sorted(_PHASE2_DIR.glob("*.mp4")):
            slug = mp4.stem.rsplit("-", 1)[-1] if "-" in mp4.stem else mp4.stem
            videos.append({"slug": slug, "filename": mp4.name, "phase": 2})
    phase3: list[dict] = []
    if _PHASE3_DIR.is_dir():
        for mp4 in sorted(_PHASE3_DIR.glob("*.mp4")):
            slug = mp4.stem.rsplit("-", 1)[-1] if "-" in mp4.stem else mp4.stem
            phase3.append({"slug": slug, "filename": mp4.name, "phase": 3})
    _rng = _random.Random(_SHUFFLE_SEED)
    _rng.shuffle(phase3)
    videos.extend(phase3)

    if not videos or video_idx >= len(videos):
        return []  # Queue exhausted for this date

    current_pos = state.get("position", 0)
    history_positions = {h.get("position") for h in state.get("history", [])}
    video = videos[video_idx]

    # Determine publish status from queue history
    already_published = (video_idx in history_positions) or (
        video_idx < current_pos and bool(state.get("last_published"))
    )

    sched_sast = _dt(day.year, day.month, day.day, _DRIP_HOUR, 0, 0,
                     tzinfo=_ZI("Africa/Johannesburg"))
    title = f"B.R.U. Drip \u2014 {video['slug'].replace('-', ' ').title()} (Phase {video['phase']})"
    return [{
        "id":         f"bru_drip_{video_idx}",
        "title":      title,
        "type":       "B.R.U. Video",
        "icon":       "bot",
        "status":     "published" if already_published else "scheduled",
        "mins":       _DRIP_HOUR * 60,
        "sched":      f"{_DRIP_HOUR:02d}:00",
        "sched_full": _render_sast(sched_sast),
        "actual":     "",
        "error":      "",
        "ch_lbl":     "TikTok",
        "is_bru_drip": True,
        "glyph":       _SO_GLYPHS["bru"],
    }]


_BRU_PUBLIC_BASE = "https://mzansiedge.co.za/assets/bru"
_BRU_HOOKS = (
    "This is B.R.U. Welcome to the Edge.",
    "B.R.U. sees what you see. Only sharper.",
    "Built for the culture. Sharpened by data.",
    "Your AI edge in the wild.",
    "The future of SA sports intelligence.",
    "No cap. Just edge.",
    "B.R.U. doesn't miss.",
    "From the streets to the stats.",
)
_BRU_TOPIC_TAGS: dict[str, list[str]] = {
    "robotatrobot": ["Johannesburg", "StreetCulture"],
    "taxirank":     ["TaxiCulture", "Johannesburg"],
    "braai":        ["Braai", "SouthAfricanCulture"],
    "smartshopper": ["SmartShopper", "SALife"],
    "pothole":      ["SAProblems", "SouthAfrica"],
    "engen":        ["SALife", "RoadTrip"],
    "prison1":      ["SAStories", "SouthAfrica"],
    "prison2":      ["SAStories", "SouthAfrica"],
    "sangoma":      ["SACulture", "Heritage"],
    "sars":         ["SARS", "SAHumour"],
    "discovery":    ["DiscoverySA", "SALife"],
    "groupchat":    ["SAHumour", "WhatsAppSA"],
    "gameranger":   ["Gaming", "SAGaming"],
    "saa":          ["SAA", "SouthAfrica"],
    "ponty":        ["SAStories", "SouthAfrica"],
    "hero-intro":   ["MzansiEdge", "BRU"],
}
_BRU_BANNED_TAGS = frozenset({
    "betting", "gambling", "bets", "sportsbetting", "odds",
    "wager", "casino", "slots", "bet", "gamble", "punting",
})


def _bru_drip_preview_payload(video_idx: int) -> dict | None:
    """Reconstruct BRU drip preview payload for the given queue position.

    Mirrors bru_drip._scan_videos + _format_caption exactly. BRU drip posts
    are synthetic (not in the Notion marketing queue) so the standard
    api_so_post lookup returns 404 — this helper rebuilds the payload from
    the source-of-truth video assets + queue state.
    """
    import json as _json
    import random as _random
    from pathlib import Path as _Path

    _QUEUE_FILE = _Path("/home/paulsportsza/publisher/state/bru_queue.json")
    _PHASE2_DIR = _Path("/var/www/mzansiedge-wp/assets/bru/phase2")
    _PHASE3_DIR = _Path("/var/www/mzansiedge-wp/assets/bru/phase3")
    _SHUFFLE_SEED = 2026

    videos: list[dict] = []
    if _PHASE2_DIR.is_dir():
        for mp4 in sorted(_PHASE2_DIR.glob("*.mp4")):
            slug = mp4.stem.rsplit("-", 1)[-1] if "-" in mp4.stem else mp4.stem
            videos.append({"slug": slug, "filename": mp4.name, "phase": 2})
    phase3: list[dict] = []
    if _PHASE3_DIR.is_dir():
        for mp4 in sorted(_PHASE3_DIR.glob("*.mp4")):
            slug = mp4.stem.rsplit("-", 1)[-1] if "-" in mp4.stem else mp4.stem
            phase3.append({"slug": slug, "filename": mp4.name, "phase": 3})
    _rng = _random.Random(_SHUFFLE_SEED)
    _rng.shuffle(phase3)
    videos.extend(phase3)

    if video_idx < 0 or video_idx >= len(videos):
        return None

    v = videos[video_idx]
    video_url = f"{_BRU_PUBLIC_BASE}/phase{v['phase']}/{v['filename']}"

    hook = _BRU_HOOKS[video_idx % len(_BRU_HOOKS)]
    slug = v["slug"]
    topic_tags = _BRU_TOPIC_TAGS.get(slug, ["SouthAfrica"])
    tags = ["MzansiEdge", "BRU"]
    for t in topic_tags:
        if t.lower() not in _BRU_BANNED_TAGS:
            tags.append(t)
    tags.append("SouthAfrica")
    tag_line = " ".join(f"#{t}" for t in dict.fromkeys(tags))
    caption_body = f"{hook}\n\n{tag_line}"
    hashtags = tag_line.split()

    try:
        state = _json.loads(_QUEUE_FILE.read_text())
    except (OSError, ValueError):
        state = {"position": 0, "history": [], "last_published": None}
    history_positions = {h.get("position") for h in state.get("history", [])}
    current_pos = state.get("position", 0)
    already_published = (video_idx in history_positions) or (
        video_idx < current_pos and bool(state.get("last_published"))
    )

    title = f"B.R.U. Drip \u2014 {slug.replace('-', ' ').title()} (Phase {v['phase']})"

    return {
        "id":               f"bru_drip_{video_idx}",
        "channel":          "TikTok",
        "channel_key":      "tiktok",
        "type":             "B.R.U. Video",
        "title":            title,
        "body_markdown":    caption_body,
        "media_urls":       [video_url],
        "image_url":        "",
        "video_url":        video_url,
        "carousel_images":  [],
        "media_aspect":     "9:16",
        "caption":          caption_body,
        "caption_final":    caption_body,
        "telegram_caption": caption_body,
        "ig_caption":       caption_body,
        "hashtags":         hashtags,
        "hashtags_str":     tag_line,
        "scheduled":        "11:00 SAST",
        "actual":           "",
        "status":           "published" if already_published else "scheduled",
        "permalink":        "",
        "error_message":    "",
        "campaign":         "B.R.U. Drip",
        "platform_notes":   f"phase{v['phase']}/{v['filename']} \u2014 deterministic shuffle seed={_SHUFFLE_SEED}",
    }


def _build_so_timeline(day_str: str, items: list[dict], now_sast: datetime, alerts_sends: list | None = None) -> dict:
    """Build timeline + KPI payload for a given SAST day string (YYYY-MM-DD)."""
    cutoff24 = now_sast - timedelta(hours=24)
    horizon_12h = now_sast + timedelta(hours=12)
    kpi_posted = kpi_pending = kpi_failed = kpi_queue = kpi_overdue_queue = kpi_pastdue = kpi_unscheduled = 0
    for it in items:
        st  = (it.get("status") or "").lower().strip()
        ts  = parse_ts(it.get("last_edited") or it.get("scheduled_time") or it.get("created") or "")
        sch = parse_ts(it.get("scheduled_time") or "")
        rfa = (it.get("ready_for_automation") or "").lower().strip()
        if st in _SO_POSTED_ST:
            if ts and ts >= cutoff24:
                kpi_posted += 1
        elif st in _SO_FAILED_ST:
            if ts and ts >= cutoff24:
                kpi_failed += 1
        elif st != "archived":
            if st in _SO_PENDING_ST:
                kpi_pending += 1
            if sch and now_sast <= sch <= horizon_12h:
                kpi_queue += 1
            if sch and sch < now_sast and st in _SO_PENDING_ST and rfa in ("yes", "true", "1", "y"):
                kpi_pastdue += 1
            if not sch and st in _SO_PENDING_ST:
                kpi_unscheduled += 1
        if (st in _SO_OVERDUE_QUEUE_ST
                and sch and sch < now_sast
                and rfa in ("yes", "true", "1", "y")):
            kpi_overdue_queue += 1

    now_sast = now_sast.astimezone(_SAST)
    now_mins = now_sast.hour * 60 + now_sast.minute if day_str == now_sast.strftime("%Y-%m-%d") else -1

    channels = []
    for ck, clbl in _SO_TL_CH:
        posts = []
        for it in items:
            if _so_norm_channel(it.get("channel") or "") != ck:
                continue
            sdt = parse_ts(it.get("scheduled_time") or "")
            if not sdt:
                continue
            ss = sdt.astimezone(_SAST)
            if ss.strftime("%Y-%m-%d") != day_str:
                continue
            smins = ss.hour * 60 + ss.minute
            adt   = parse_ts(it.get("last_edited") or "")
            ahhmm = adt.astimezone(_SAST).strftime("%H:%M") if adt else ""
            raw_st = (it.get("status") or "").lower().strip()
            disp_st = "queued" if raw_st == "approved" else raw_st
            # SOCIAL-OPS-TIMELINE-INTEGRITY-01: state-aware reel indicator on IG lane.
            # reel_state ∈ {published, overdue, needs_upload, queued}. Front-end reads this to
            # apply the flashing-red keyframe (needs_upload), solid-red (overdue), or checkmark (published).
            reel_state = ""
            if ck == "instagram":
                _wt = (it.get("work_type") or "").lower()
                _ttl_lc = (it.get("title") or "").lower()
                _is_reel = ("reel" in _wt) or ("reel still" in _ttl_lc) or ("reel" in _ttl_lc)
                if _is_reel:
                    _reel_date_str = sdt.astimezone(_SAST).strftime("%Y-%m-%d") if sdt else ""
                    _moq_page_id = it.get("id") or ""
                    _final_uploaded = _reel_has_final(_moq_page_id, _reel_date_str)
                    _reel_excl = _SO_POSTED_ST | {"archived"}
                    if raw_st in _SO_POSTED_ST:
                        reel_state = "published"
                    elif _final_uploaded:
                        reel_state = "queued"  # master uploaded, awaiting publisher cron
                    elif raw_st not in _reel_excl:
                        if sdt and sdt < now_sast:
                            reel_state = "overdue"      # past scheduled time, no final
                        else:
                            reel_state = "needs_upload" # before scheduled time, no final
            posts.append({
                "id":     it.get("id", ""),
                "title":  (it.get("title") or it.get("copy") or "")[:60],
                "type":   it.get("work_type") or "",
                "icon":   _so_icon_for(it.get("work_type") or "", ck),
                "glyph":  _pick_glyph_for_row(it),
                "status": disp_st,
                "mins":   smins,
                "sched":      f"{ss.hour:02d}:{ss.minute:02d}",
                "sched_full": _render_sast(sdt),
                "actual": ahhmm,
                "error":  it.get("error") or "",
                "ch_lbl": clbl,
                "reel_state": reel_state,
            })
        # DASH-POLISH-STORIES-01 / AC1: empty-slot flash for today's 19:00 IG Reel.
        # If day is today (SAST) and no IG Reel row exists in MOQ for any state
        # (published/queued/overdue), emit a virtual "empty" marker at 19:00.
        if ck == "instagram" and day_str == now_sast.strftime("%Y-%m-%d"):
            _has_reel = any(
                (p.get("reel_state") or "") in ("published", "queued", "overdue", "needs_upload")
                for p in posts
            )
            if not _has_reel:
                posts.append({
                    "id":     "__ig_reel_empty__",
                    "title":  f"No IG Reel queued for today's {_DASH_IG_REEL_SLOT} slot — reel_generator.py 06:00 UTC may have skipped or failed.",
                    "type":   "reel",
                    "icon":   "film",
                    "status": "empty",
                    "mins":   _IG_REEL_MINS,
                    "sched":      _DASH_IG_REEL_SLOT,
                    "sched_full": _IG_REEL_SAST,
                    "actual": "",
                    "error":  "",
                    "ch_lbl": clbl,
                    "reel_state": "empty",
                    "glyph":  _SO_GLYPHS["card_diamond"],
                })
        ch_dict: dict = {"key": ck, "label": clbl, "icon": _so_platform_icon_svg(ck),
                         "color": _CHANNEL_MAP.get(ck, {}).get("color", "#888888"), "posts": posts}
        if ck == "tiktok":
            bru_items = _bru_drip_items_for_day(day_str)
            moq_mins = {p["mins"] for p in posts}
            for bru in bru_items:
                conflict = any(abs(bru["mins"] - m) < 30 for m in moq_mins)
                if conflict:
                    # MOQ wins — badge the conflicting MOQ post to flag the mismatch
                    for p in posts:
                        if abs(p["mins"] - bru["mins"]) < 30:
                            p["bru_mismatch"] = True
                else:
                    posts.append(bru)
            ch_dict["bru_empty"] = not posts and not bru_items
        channels.append(ch_dict)

    # AC-B: inject today's Alerts bot sends into the telegram_alerts timeline lane
    if alerts_sends:
        for _ch in channels:
            if _ch["key"] != "telegram_alerts":
                continue
            for _asend in alerts_sends:
                _sdt = datetime.fromtimestamp(_asend["sent_at"], tz=_UTC).astimezone(_SAST)
                if _sdt.strftime("%Y-%m-%d") != day_str:
                    continue
                _smins = _sdt.hour * 60 + _sdt.minute
                _tier = _asend["tier"]
                _ch["posts"].append({
                    "id":         _asend["edge_id"] or _asend["match_key"],
                    "title":      (_asend["match_key"] or "Edge card")[:60],
                    "type":       f"{_tier.title()} · {_asend['image_bytes_size'] // 1024}KB",
                    "icon":       "diamond",
                    "status":     "published",
                    "mins":       _smins,
                    "sched":      f"{_sdt.hour:02d}:{_sdt.minute:02d}",
                    "sched_full": f"Sent {_sdt.strftime('%H:%M')} SAST",
                    "actual":     f"{_sdt.hour:02d}:{_sdt.minute:02d}",
                    "error":      "",
                    "ch_lbl":     "TG Alerts",
                    "asset_url":  "",
                })
            break

    return {
        "day":      day_str,
        "now_mins": now_mins,
        "channels": channels,
        "kpis": {
            "posted_24h":  kpi_posted,
            "pending":     kpi_pending,
            "failed_24h":  kpi_failed,
            "queue_depth": kpi_queue,
            "overdue_queue_count": kpi_overdue_queue,
            "past_due":    kpi_pastdue,
            "unscheduled": kpi_unscheduled,
        },
    }


@app.route("/admin/api/social-ops/timeline")
@require_auth
def api_so_timeline():
    from datetime import date as _date
    now_sast = datetime.now(_SAST)
    today_sast = now_sast.astimezone(_SAST)

    day_param = request.args.get("day", "").strip()
    if day_param:
        try:
            _date.fromisoformat(day_param)
            day_str = day_param
        except ValueError:
            return Response(json.dumps({"error": "Invalid day format, expected YYYY-MM-DD"}),
                            status=400, mimetype="application/json")
    else:
        day_str = today_sast.strftime("%Y-%m-%d")

    items, _ = _fetch_marketing_queue()
    _asl_conn2 = db_connect(SCRAPERS_DB)
    _alerts_sends2: list = []
    if _asl_conn2:
        try:
            _alerts_sends2 = _fetch_alerts_send_log(_asl_conn2, limit=50)
        finally:
            _asl_conn2.close()
    payload = _build_so_timeline(day_str, items, now_sast, alerts_sends=_alerts_sends2)
    return Response(json.dumps(payload), mimetype="application/json")


def _build_so_queue(items: list[dict], now_sast: datetime, horizon_hours: int = 12) -> dict:
    """Next `horizon_hours` of scheduled posts across all channels, sorted by scheduled time."""
    horizon = now_sast + timedelta(hours=horizon_hours)
    posts: list[dict] = []
    for it in items:
        st = (it.get("status") or "").lower().strip()
        if st in _SO_POSTED_ST or st in _SO_FAILED_ST or st == "archived":
            continue
        sch = parse_ts(it.get("scheduled_time") or "")
        if not sch or sch < now_sast or sch > horizon:
            continue
        ch_key = _so_norm_channel(it.get("channel") or "")
        ss = sch.astimezone(_SAST)
        raw_st = (it.get("status") or "").lower().strip()
        disp_st = "queued" if raw_st == "approved" else raw_st
        ch_meta = _CHANNEL_MAP.get(ch_key, {})
        ch_label = next((lbl for (ck, lbl) in _SO_TL_CH if ck == ch_key), ch_meta.get("label", ""))
        posts.append({
            "id":               it.get("id", ""),
            "title":            (it.get("title") or it.get("copy") or "")[:80],
            "channel_key":      ch_key,
            "channel":          it.get("channel") or "",
            "channel_label":    ch_label,
            "channel_color":    ch_meta.get("color", "#888888"),
            "channel_icon_svg": _CHANNEL_SVG.get(ch_key, _so_platform_icon_svg(ch_key)),
            "type":             it.get("work_type") or "",
            "icon":             _so_icon_for(it.get("work_type") or "", ch_key),
            "status":           disp_st,
            "sched":            ss.strftime("%a %H:%M"),
            "sched_full":       _render_sast(sch),
            "sched_iso":        sch.astimezone(_SAST).isoformat(),
            "mins_until":       int((sch - now_sast).total_seconds() // 60),
        })
    posts.sort(key=lambda p: p["sched_iso"])
    return {
        "horizon_hours": horizon_hours,
        "count":         len(posts),
        "posts":         posts,
    }


@app.route("/admin/api/social-ops/queue")
@require_auth
def api_so_queue():
    now_sast = datetime.now(_SAST)
    try:
        horizon = int(request.args.get("hours", "12"))
    except ValueError:
        horizon = 12
    horizon = max(1, min(horizon, 72))
    items, _ = _fetch_marketing_queue()
    payload = _build_so_queue(items, now_sast, horizon)
    return _no_store(Response(json.dumps(payload), mimetype="application/json"))



@app.route("/admin/api/social-ops/post/<post_id>")
@require_auth
def api_so_post(post_id: str):
    # BRU drip posts are synthetic (not in Notion marketing queue) — rebuild
    # the preview payload directly from the video asset + queue state.
    if post_id.startswith("bru_drip_"):
        try:
            _video_idx = int(post_id.rsplit("_", 1)[-1])
        except ValueError:
            _video_idx = -1
        _bru_payload = _bru_drip_preview_payload(_video_idx) if _video_idx >= 0 else None
        if _bru_payload is not None:
            return Response(json.dumps(_bru_payload), mimetype="application/json")
        return Response(json.dumps({"error": "BRU drip video not found"}),
                        status=404, mimetype="application/json")

    items, _ = _fetch_marketing_queue()
    item = next((it for it in items if it.get("id") == post_id), None)
    if item is None:
        return Response(json.dumps({"error": "Post not found"}),
                        status=404, mimetype="application/json")

    sdt = parse_ts(item.get("scheduled_time") or "")
    adt = parse_ts(item.get("last_edited") or "")
    copy_raw = item.get("copy") or item.get("title") or ""

    hashtags: list[str] = []
    caption_lines: list[str] = []
    for line in copy_raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            hashtags.extend(t for t in stripped.split() if t.startswith("#"))
        else:
            caption_lines.append(stripped)
    caption = "\n".join(caption_lines).strip()

    explicit_image = item.get("image_url") or ""
    explicit_video = item.get("video_url") or ""
    asset = item.get("asset_link") or item.get("asset_url") or item.get("media_url") or ""

    # IG Carousel rows pack multiple slide URLs separated by '|' into either
    # image_url or asset_link. Split into a list and use the first URL as the
    # primary image preview; keep the rest for the carousel renderer.
    carousel_images: list[str] = []
    for _src_name, _src_val in (("image", explicit_image), ("asset", asset)):
        if "|" in _src_val:
            _parts = [u.strip() for u in _src_val.split("|") if u.strip()]
            if len(_parts) > 1:
                carousel_images = _parts
                if _src_name == "image":
                    explicit_image = _parts[0]
                else:
                    asset = _parts[0]
                break

    channel_key = _so_norm_channel(item.get("channel") or "")
    is_vertical = channel_key in ("instagram", "tiktok")

    image_url = ""
    video_url = ""

    if explicit_video:
        video_url = explicit_video
    if explicit_image:
        image_url = explicit_image

    if not video_url and not image_url and asset:
        asset_lower = asset.lower()
        if asset_lower.endswith((".mp4", ".mov", ".webm", ".m4v")):
            video_url = asset
        elif asset_lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            image_url = asset
        else:
            image_url = asset

    if is_vertical and not video_url and sdt:
        pick_id = _so_extract_pick_id(item)
        if pick_id:
            date_str = sdt.astimezone(_SAST).strftime("%Y-%m-%d")
            master_rel = f"{date_str}/{pick_id}_master.mp4"
            master_path = os.path.join(_REEL_MASTERS_ROOT, master_rel)
            if os.path.isfile(master_path):
                video_url = f"{_REEL_PUBLIC_BASE}/{master_rel}"

    # Resolve computer:// and other unservable schemes to dashboard-served
    # paths. Drops URLs we cannot serve so the frontend renders text-only
    # instead of a black box.
    image_url = _resolve_media_url(image_url)
    video_url = _resolve_media_url(video_url)

    if carousel_images:
        media_urls = [video_url] if video_url else []
        media_urls.extend(carousel_images)
    else:
        media_urls = [u for u in (video_url, image_url) if u]

    # Per-slide captions for IG Carousel. Splits caption on blank lines or
    # numbered/bulleted list markers. If segment count matches slide count,
    # each slide gets its own caption; otherwise the global caption is used.
    slide_captions: list[str] = []
    if carousel_images and len(carousel_images) > 1:
        _slide_n = len(carousel_images)
        _segments: list[str] = []
        import re as _re2
        _slide_split = _re2.split(r'(?im)^\s*SLIDE\s+\d+\s*[:\.\-]?\s*', caption or "")
        _slide_parts = [s.strip() for s in _slide_split if s and s.strip()]
        if len(_slide_parts) == _slide_n:
            _segments = _slide_parts
        if not _segments:
            _blocks = [b.strip() for b in (caption or "").split("\n\n") if b.strip()]
            if len(_blocks) == _slide_n:
                _segments = _blocks
        if not _segments:
            _numbered = _re2.findall(r'^\s*(?:\d+[\.\)]\s*|[•\-\u2013]\s*)(.+)$', caption or "", flags=_re2.M)
            if len(_numbered) == _slide_n:
                _segments = [s.strip() for s in _numbered]
        if _segments:
            # Strip trailing meta block from the last slide — publishers often
            # append `---\nCAPTION:\n...` (the post caption) after the final
            # SLIDE N: marker. That belongs in `caption`, not on slide N.
            _last = _segments[-1]
            _cut = _re2.search(r'(?im)^\s*(?:-{3,}|CAPTION\s*:)\s*$', _last)
            if _cut:
                _last = _last[:_cut.start()].rstrip()
            _segments[-1] = _last
            slide_captions = _segments

    if carousel_images:
        media_aspect = "1:1"
    elif video_url or image_url:
        media_aspect = "9:16" if is_vertical else "16:9"
    else:
        media_aspect = None

    import re as _re
    _plain_caption = _re.sub(r'<[^>]+>', '', caption)
    # Reel metadata for awaiting-upload panel
    _is_reel_post = (
        "reel" in (item.get("work_type") or "").lower()
        or "reel" in (item.get("title") or "").lower()
    )
    reel_date_out = sdt.astimezone(_SAST).strftime("%Y-%m-%d") if sdt else ""
    reel_final_out = _reel_has_final(post_id, reel_date_out) if _is_reel_post else False
    now_utc_so = datetime.now(_SAST)
    if _is_reel_post and channel_key == "instagram":
        raw_st_so = (item.get("status") or "").lower().strip()
        _reel_excl_so = _SO_POSTED_ST | {"archived"}
        if raw_st_so in _SO_POSTED_ST:
            reel_state_out = "published"
        elif reel_final_out:
            reel_state_out = "queued"
        elif raw_st_so not in _reel_excl_so:
            if sdt and sdt < now_utc_so:
                reel_state_out = "overdue"      # past scheduled time, no final
            else:
                reel_state_out = "needs_upload" # before scheduled time, no final
        else:
            reel_state_out = ""
    else:
        reel_state_out = ""
    payload = {
        "id":              post_id,
        "channel":         item.get("channel") or "",
        "channel_key":     channel_key,
        "type":            item.get("work_type") or "",
        "body_markdown":   copy_raw,
        "media_urls":      media_urls,
        "image_url":       image_url,
        "video_url":       video_url,
        "carousel_images": carousel_images,
        "slide_captions":  slide_captions,
        "media_aspect":    media_aspect,
        "caption":         caption,
        "caption_final":   caption,
        "telegram_caption": caption,
        "ig_caption":      _plain_caption,
        "hashtags":        hashtags,
        "hashtags_str":    " ".join(hashtags),
        "scheduled":       sdt.astimezone(_SAST).strftime("%Y-%m-%d %H:%M") if sdt else "",
        "actual":          adt.astimezone(_SAST).strftime("%Y-%m-%d %H:%M") if adt else "",
        "status":          ("queued" if (item.get("status") or "").lower().strip() == "approved" else (item.get("status") or "").lower().strip()),
        "permalink":       item.get("url") or "",
        "error_message":   item.get("error") or "",
        "campaign":        item.get("campaign_theme") or "",
        "platform_notes":  item.get("platform_notes") or "",
        "reel_state":      reel_state_out,
        "reel_date":       reel_date_out,
        "reel_has_final":  reel_final_out,
    }
    return Response(json.dumps(payload), mimetype="application/json")


@app.route("/admin/social-ops/asset/<path:subpath>")
@require_auth
def so_serve_asset(subpath: str):
    if ".." in subpath.split("/") or subpath.startswith("/"):
        abort(404)
    for root in _SO_ASSET_ROOTS:
        candidate = os.path.normpath(os.path.join(root, subpath))
        if not candidate.startswith(os.path.normpath(root) + os.sep):
            continue
        if os.path.isfile(candidate):
            return send_from_directory(root, subpath, conditional=True)
    abort(404)


@app.route("/admin/api/reel_kit")
@require_auth
def api_reel_kit():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("reel_kit_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return _no_store(Response(cached[0], mimetype="text/html"))
    content = render_reel_kit_page()
    with _page_cache_lock:
        _page_cache["reel_kit_content"] = (content, now)
    return _no_store(Response(content, mimetype="text/html"))


_RE_NOTION_REEL_KIT = re.compile(r"^🎥 Reel Kit (\d{4}-\d{2}-\d{2})")


@app.route("/admin/api/reel-kit-url")
@require_auth
def api_reel_kit_url():
    """Return the Notion deep-link for today's Reel Kit block in Task Hub.

    Accepts ?date=YYYY-MM-DD. Returns {found, url} or {found: false}.
    """
    date_str = request.args.get("date", "").strip()
    if not date_str or not _RE_DATE.match(date_str):
        return Response('{"found":false,"error":"invalid date"}', status=400, mimetype="application/json")
    data = _notion_request(f"blocks/{NOTION_TASK_HUB_PAGE}/children?page_size=100")
    if not data:
        return Response('{"found":false,"error":"task hub unavailable"}', status=502, mimetype="application/json")
    page_id_clean = NOTION_TASK_HUB_PAGE.replace("-", "")
    for block in data.get("results", []):
        if block.get("type") != "to_do":
            continue
        texts = block.get("to_do", {}).get("rich_text", [])
        text = "".join(t["plain_text"] for t in texts)
        m = _RE_NOTION_REEL_KIT.match(text)
        if m and m.group(1) == date_str:
            block_id_clean = block["id"].replace("-", "")
            notion_url = f"https://www.notion.so/{page_id_clean}#{block_id_clean}"
            return Response(json.dumps({"found": True, "url": notion_url}), mimetype="application/json")
    return Response(json.dumps({"found": False}), mimetype="application/json")


@app.route("/admin/reel/upload", methods=["POST"])
@require_auth
def api_reel_final_upload():
    """POST — upload master Reel MP4 for an existing MOQ row (Social Ops flow).

    Form fields: row_id (MOQ Notion page ID), date (YYYY-MM-DD), file (MP4).
    Saves to _REEL_FINALS_ROOT/<date>/final/<row_id>.mp4.
    Updates the MOQ row's Asset Link in Notion.
    """
    if request.content_length and request.content_length > MAX_CONTENT_LENGTH:
        return Response('{"ok":false,"error":"file too large (max 50 MB)"}', status=413, mimetype="application/json")
    f = request.files.get("file")
    row_id = (request.form.get("row_id") or "").strip()
    date_str = (request.form.get("date") or "").strip()
    if not f or not row_id or not date_str:
        return Response('{"ok":false,"error":"missing file, row_id, or date"}', status=400, mimetype="application/json")
    if not _RE_DATE.match(date_str):
        return Response('{"ok":false,"error":"invalid date format"}', status=400, mimetype="application/json")
    # Validate row_id looks like a UUID/Notion page ID
    if not re.match(r'^[0-9a-f-]{32,36}$', row_id, re.I):
        return Response('{"ok":false,"error":"invalid row_id"}', status=400, mimetype="application/json")
    # Save the file
    finals_dir = os.path.join(_REEL_FINALS_ROOT, date_str, "final")
    os.makedirs(finals_dir, exist_ok=True)
    dest_path = os.path.join(finals_dir, f"{row_id}.mp4")
    try:
        f.save(dest_path)
    except OSError as exc:
        return Response(json.dumps({"ok": False, "error": f"save failed: {exc}"}), status=500, mimetype="application/json")
    # Served URL via so_serve_asset (auth-gated admin route)
    video_url = f"/admin/social-ops/asset/reels/{date_str}/final/{row_id}.mp4"
    # Update the MOQ row's Asset Link in Notion
    patch_body = {"properties": {"Asset Link": {"url": video_url}}}
    _notion_request(f"pages/{row_id}", body=patch_body, method="PATCH")
    # Invalidate Social Ops cache so next timeline fetch shows queued state
    with _page_cache_lock:
        _page_cache.pop("social_ops_full", None)
    with _notion_cache_lock:
        _notion_cache.pop("marketing_queue", None)
    return Response(
        json.dumps({"ok": True, "video_url": video_url, "row_id": row_id}),
        mimetype="application/json",
    )


def _fetch_overdue_notion_reel_kits() -> list[dict]:
    """Fetch past-dated unchecked 🎥 Reel Kit to_do blocks from Task Hub.

    Returns list of {date, text, block_id} for blocks where date < today SAST.
    Returns [] when SHOW_REEL_KIT_ON_TIMELINE is False (PILLS-01 not landed).
    SO-31: single fetch from Task Hub — no per-block requests.
    """
    if not SHOW_REEL_KIT_ON_TIMELINE:
        return []
    today = datetime.now(_SAST).date().isoformat()
    data = _notion_request(f"blocks/{NOTION_TASK_HUB_PAGE}/children?page_size=100")
    if not data:
        return []
    overdue = []
    for block in data.get("results", []):
        if block.get("type") != "to_do":
            continue
        todo = block.get("to_do", {})
        if todo.get("checked"):
            continue
        text = "".join(t["plain_text"] for t in todo.get("rich_text", []))
        m = _RE_NOTION_REEL_KIT.match(text)
        if m and m.group(1) < today:
            overdue.append({"date": m.group(1), "text": text, "block_id": block["id"]})
    return overdue


@app.route("/admin/api/social-ops/reel-kits")
@require_auth
def api_so_reel_kits():
    """Scan last 3 SAST days for reel kits awaiting a master upload."""
    try:
        now_sast = datetime.now(_SAST)
        days: list[str] = []
        for d in range(3):
            days.append((now_sast - timedelta(days=d)).strftime("%Y-%m-%d"))

        outstanding: list[dict] = []
        ready_count = 0
        for date_str in days:
            try:
                kits = _scan_reel_kits(date_str)
            except Exception:
                kits = []
            for k in kits:
                pick_id = k.get("pick_id") or ""
                tier = k.get("tier") or ""
                card = k.get("card") or ""
                still = k.get("still") or ""
                thumb = k.get("thumb") or card or ""
                vos = k.get("vos") or []
                has_master = bool(k.get("has_master"))
                if has_master:
                    ready_count += 1
                    continue
                thumb_url = (
                    f"https://mzansiedge.co.za/assets/reel-cards/{date_str}/{pick_id}/{thumb}"
                    if thumb else ""
                )
                outstanding.append({
                    "date":       date_str,
                    "pick_id":    pick_id,
                    "tier":       tier,
                    "card":       card,
                    "still":      still,
                    "thumb":      thumb,
                    "thumb_url":  thumb_url,
                    "vo_count":   len(vos),
                    "has_master": False,
                })
        overdue_notion = _fetch_overdue_notion_reel_kits()
        return _no_store(Response(
            json.dumps({
                "days": days,
                "rows": outstanding,
                "ready_count": ready_count,
                "outstanding_count": len(outstanding),
                "overdue_notion": overdue_notion,
                "show_rk_timeline": SHOW_REEL_KIT_ON_TIMELINE,
            }),
            mimetype="application/json",
        ))
    except Exception:
        return _no_store(Response(
            json.dumps({
                "days": [], "rows": [], "ready_count": 0, "outstanding_count": 0,
                "overdue_notion": [], "show_rk_timeline": False,
            }),
            mimetype="application/json",
        ))


@app.route("/admin/api/social-ops/linkedin")
@require_auth
def api_so_linkedin():
    rows = _fetch_linkedin_ledger()
    return Response(
        json.dumps({"rows": rows, "count": len(rows)}),
        mimetype="application/json",
    )


@app.route("/admin/api/social-ops/quora")
@require_auth
def api_so_quora():
    rows = _fetch_quora_ledger()
    return Response(
        json.dumps({"rows": rows, "count": len(rows)}),
        mimetype="application/json",
    )


@app.route("/admin/api/calendar")
@require_auth
def api_calendar():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("calendar_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return _no_store(Response(cached[0], mimetype="text/html"))
    content = render_calendar_page()
    with _page_cache_lock:
        _page_cache["calendar_content"] = (content, now)
    return _no_store(Response(content, mimetype="text/html"))


@app.route("/admin/task-hub")
@require_auth
def admin_task_hub():
    """Task Hub — tabbed inbox: Reel Kits, FB Group Posts, Quora Answers, LinkedIn.

    Serves cached HTML immediately (stale-while-revalidate up to 10min) and kicks
    off a background refresh when the TTL has expired. Cold first hit blocks.
    """
    now = time.monotonic()
    should_refresh = False
    payload = None
    with _page_cache_lock:
        cached = _page_cache.get("task_hub_full")
        if cached:
            age = now - cached[1]
            if age < _PAGE_CACHE_TTL:
                payload = cached[0]
            elif age < _PAGE_CACHE_SWR and "task_hub_full" not in _page_refresh_inflight:
                _page_refresh_inflight.add("task_hub_full")
                should_refresh = True
                payload = cached[0]
            elif age < _PAGE_CACHE_SWR:
                payload = cached[0]

    if should_refresh:
        threading.Thread(target=_bg_refresh_task_hub, daemon=True).start()

    if payload is not None:
        request._cache_state = "swr-refresh" if should_refresh else "hit"
        return _no_store(Response(payload, mimetype="text/html"))

    # Cold path — render fully
    data = _fetch_task_hub_data()
    content = render_task_hub_tabbed(data)
    html = render_shell("task_hub", content)
    with _page_cache_lock:
        _page_cache["task_hub_full"] = (html, time.monotonic())
    return _no_store(Response(html, mimetype="text/html"))


@app.route("/admin/api/task-hub/data")
@require_auth
def api_task_hub_data():
    """JSON payload for client-side refresh of tab counts + lists."""
    data = _fetch_task_hub_data()
    return _no_store(Response(json.dumps(data), mimetype="application/json"))


@app.route("/admin/api/task_hub")
@require_auth
def api_task_hub_content():
    """HTML partial for SPA sidebar navigation. Returns inner content only (no shell)."""
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("task_hub_content")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            request._cache_state = "hit"
            return _no_store(Response(cached[0], mimetype="text/html"))
    data = _fetch_task_hub_data()
    content = render_task_hub_tabbed(data)
    with _page_cache_lock:
        _page_cache["task_hub_content"] = (content, now)
    return _no_store(Response(content, mimetype="text/html"))


def _mark_notion_status_posted(page_id: str, extra_props: dict | None = None) -> bool:
    """PATCH a Notion page Status → Posted. Returns True on success."""
    from datetime import datetime as _dt
    if not page_id:
        return False
    now_iso = _dt.now(_SAST).isoformat()
    props = {
        "Status": {"select": {"name": "Posted"}},
        "Posted At": {"date": {"start": now_iso}},
    }
    if extra_props:
        props.update(extra_props)
    body = {"properties": props}
    try:
        result = _notion_request(f"pages/{page_id}", body=body, method="PATCH")
        return bool(result and result.get("object") == "page")
    except Exception:
        return False


@app.route("/admin/api/task-hub/fb/<page_id>/posted", methods=["POST"])
@require_auth
def api_task_hub_fb_posted(page_id: str):
    ok = _mark_notion_status_posted(page_id)
    if ok:
        with _notion_cache_lock:
            _notion_cache.pop("marketing_queue", None)
        with _page_cache_lock:
            _page_cache.pop("task_hub_full", None)
            _page_cache.pop("task_hub_content", None)
            _page_cache.pop("social_ops_full", None)
    return Response(json.dumps({"ok": ok}), mimetype="application/json")


@app.route("/admin/api/task-hub/quora/<page_id>/posted", methods=["POST"])
@require_auth
def api_task_hub_quora_posted(page_id: str):
    from datetime import datetime as _dt
    now_iso = _dt.now(_SAST).isoformat()
    extra = {"Answered At": {"date": {"start": now_iso}}}
    # Quora ledger may use a different status column name — try generic Posted first.
    ok = _mark_notion_status_posted(page_id, extra_props=extra)
    if ok:
        with _notion_cache_lock:
            _notion_cache.pop("quora_ledger", None)
            _notion_cache.pop("marketing_queue", None)
        with _page_cache_lock:
            _page_cache.pop("task_hub_full", None)
            _page_cache.pop("task_hub_content", None)
            _page_cache.pop("social_ops_full", None)
    return Response(json.dumps({"ok": ok}), mimetype="application/json")


@app.route("/admin/api/task-hub/linkedin/<page_id>/sent", methods=["POST"])
@require_auth
def api_task_hub_linkedin_sent(page_id: str):
    from datetime import datetime as _dt
    now_iso = _dt.now(_SAST).isoformat()
    props = {
        "Status": {"select": {"name": "Sent"}},
        "Sent At": {"date": {"start": now_iso}},
    }
    body = {"properties": props}
    try:
        result = _notion_request(f"pages/{page_id}", body=body, method="PATCH")
        ok = bool(result and result.get("object") == "page")
    except Exception:
        ok = False
    if ok:
        with _notion_cache_lock:
            _notion_cache.pop("linkedin_ledger", None)
            _notion_cache.pop("marketing_queue", None)
        with _page_cache_lock:
            _page_cache.pop("task_hub_full", None)
            _page_cache.pop("task_hub_content", None)
            _page_cache.pop("social_ops_full", None)
    return Response(json.dumps({"ok": ok}), mimetype="application/json")


@app.route("/admin/reel-kit")
@require_auth
def admin_reel_kit():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("reel_kit_full")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    content = render_reel_kit_page()
    html = render_shell("reel_kit", content)

    with _page_cache_lock:
        _page_cache["reel_kit_full"] = (html, now)

    return Response(html, mimetype="text/html")


@app.route("/admin/calendar")
@require_auth
def admin_calendar():
    now = time.monotonic()
    with _page_cache_lock:
        cached = _page_cache.get("calendar_full")
        if cached and (now - cached[1]) < _PAGE_CACHE_TTL:
            return Response(cached[0], mimetype="text/html")

    content = render_calendar_page()
    html = render_shell("calendar", content)

    with _page_cache_lock:
        _page_cache["calendar_full"] = (html, now)

    return Response(html, mimetype="text/html")



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
            _page_cache.pop("social_ops_full", None)
            _page_cache.pop("automation_content", None)
            _page_cache.pop("task_hub_full", None)
            _page_cache.pop("task_hub_content", None)
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
            _page_cache.pop("social_ops_full", None)
            _page_cache.pop("automation_content", None)
            _page_cache.pop("task_hub_full", None)
            _page_cache.pop("task_hub_content", None)
        return Response('{"ok":true}', mimetype="application/json")
    else:
        return Response('{"error":"notion update failed"}', status=502, mimetype="application/json")


# -- Reel Kit helpers ---------------------------------------------------------

_REEL_BK_DISPLAY: dict[str, str] = {
    "hollywoodbets": "HWB", "betway": "Betway", "supabets": "Supabets",
    "sportingbet": "Sportingbet", "gbets": "GBets", "wsb": "WSB",
    "playabets": "PlayaBets", "supersportbet": "SuperSportBet",
}

_REEL_TEAM_ABBREV: dict[str, str] = {
    "KOLKATA KNIGHT RIDERS": "KKR", "ROYAL CHALLENGERS BANGALORE": "RCB",
    "ROYAL CHALLENGERS BENGALURU": "RCB", "CHENNAI SUPER KINGS": "CSK",
    "SUNRISERS HYDERABAD": "SRH", "LUCKNOW SUPER GIANTS": "LSG",
    "RAJASTHAN ROYALS": "RAJASTHAN", "PUNJAB KINGS": "PUNJAB",
    "DELHI CAPITALS": "DELHI", "MUMBAI INDIANS": "MUMBAI", "GUJARAT TITANS": "GUJARAT",
    "MANCHESTER UNITED": "MAN UTD", "MANCHESTER CITY": "MAN CITY",
    "TOTTENHAM HOTSPUR": "SPURS", "NEWCASTLE UNITED": "NEWCASTLE",
    "WEST HAM UNITED": "WEST HAM", "NOTTINGHAM FOREST": "FOREST",
    "BRIGHTON HOVE ALBION": "BRIGHTON", "BRIGHTON & HOVE ALBION": "BRIGHTON",
    "WOLVERHAMPTON WANDERERS": "WOLVES", "LEICESTER CITY": "LEICESTER",
    "SHEFFIELD UNITED": "SHEFFIELD", "LUTON TOWN": "LUTON",
    "VODACOM BULLS": "BULLS", "HOLLYWOODBETS SHARKS": "SHARKS",
    "DHL STORMERS": "STORMERS", "EMIRATES LIONS": "LIONS",
}


def _reel_abbr(name: str) -> str:
    u = (name or "").strip().upper()
    return _REEL_TEAM_ABBREV.get(u, u)


def _reel_pick_team_from_bet(bet_type: str, home: str, away: str) -> str:
    bt = (bet_type or "").lower()
    if "away" in bt:
        return away
    return home  # home win, draw, or unknown → home team


def _reel_teams_from_match_key(match_key: str) -> tuple[str, str]:
    key = re.sub(r'_\d{4}-\d{2}-\d{2}$', '', match_key)
    if '_vs_' in key:
        home_raw, away_raw = key.split('_vs_', 1)
        return home_raw.replace('_', ' ').title(), away_raw.replace('_', ' ').title()
    return match_key, match_key


def _resolve_reel_meta_from_db(pick_ids: list[str]) -> dict[str, dict]:
    """Backfill pick_team/bookmaker/tier for kits that have no meta.json."""
    if not pick_ids:
        return {}
    result: dict[str, dict] = {}
    try:
        conn = db_connect(SCRAPERS_DB)
        if conn is None:
            return result
        rows = conn.execute(
            "SELECT edge_id, bet_type, bookmaker, edge_tier, match_key"
            " FROM edge_results ORDER BY recommended_at DESC"
        ).fetchall()
        conn.close()
        pid_set = set(pick_ids)
        for row in rows:
            pid = hashlib.md5(row["edge_id"].encode()).hexdigest()[:12]
            if pid not in pid_set or pid in result:
                continue
            home, away = _reel_teams_from_match_key(row["match_key"])
            pick_team = _reel_abbr(_reel_pick_team_from_bet(row["bet_type"], home, away))
            result[pid] = {
                "pick_team": pick_team,
                "bookmaker": row["bookmaker"],
                "tier": row["edge_tier"],
            }
            if len(result) == len(pid_set):
                break
    except Exception:
        pass
    return result


def _scan_reel_kits(date_str: str) -> list[dict]:
    """Scan _REEL_CARDS_ROOT/{date}/{pick_id}/ subdirs for reel kits."""
    if not _RE_DATE.match(date_str):
        return []
    date_dir = os.path.join(_REEL_CARDS_ROOT, date_str)
    if not os.path.isdir(date_dir):
        return []
    kits: dict[str, dict] = {}
    for entry in sorted(os.listdir(date_dir)):
        sub = os.path.join(date_dir, entry)
        if not os.path.isdir(sub):
            continue
        pick_id = entry
        if not _RE_PICK_ID.match(pick_id):
            continue
        kit: dict = {"pick_id": pick_id, "card": None, "still": None, "thumb": None,
                     "vos": [], "tier": None, "pick_team": None, "bookmaker": None}
        for fname in sorted(os.listdir(sub)):
            if fname.startswith("card_") and fname.endswith(".png"):
                kit["card"] = fname
            elif fname.startswith("still_") and fname.endswith(".png"):
                kit["still"] = fname
            elif fname.startswith("thumb_") and (fname.endswith(".jpg") or fname.endswith(".png")):
                kit["thumb"] = fname
            elif fname.startswith("vo_") and fname.endswith(".mp3"):
                kit["vos"].append(fname)
            elif fname.startswith("tier_"):
                kit["tier"] = fname[5:]  # e.g. "tier_diamond" -> "diamond"
            elif fname == "meta.json":
                try:
                    with open(os.path.join(sub, fname)) as fh:
                        meta = json.load(fh)
                    kit["pick_team"] = meta.get("pick_team") or kit["pick_team"]
                    kit["bookmaker"] = meta.get("bookmaker") or kit["bookmaker"]
                    if meta.get("tier") and not kit["tier"]:
                        kit["tier"] = meta["tier"]
                except Exception:
                    pass
        if kit["card"] is None:
            continue
        kits[pick_id] = kit
    # For kits still missing pick_team/bookmaker, backfill from edge_results DB.
    missing = [pid for pid, k in kits.items() if not k["pick_team"] or not k["bookmaker"]]
    if missing:
        db_meta = _resolve_reel_meta_from_db(missing)
        for pid, meta in db_meta.items():
            if pid in kits:
                if not kits[pid]["pick_team"]:
                    kits[pid]["pick_team"] = meta.get("pick_team")
                if not kits[pid]["bookmaker"]:
                    kits[pid]["bookmaker"] = meta.get("bookmaker")
                if not kits[pid]["tier"]:
                    kits[pid]["tier"] = meta.get("tier")
    # Check if master already uploaded
    masters_dir = os.path.join(_REEL_MASTERS_ROOT, date_str)
    result = []
    for pick_id, kit in kits.items():
        master_path = os.path.join(masters_dir, f"{pick_id}_master.mp4") if os.path.isdir(masters_dir) else ""
        kit["has_master"] = os.path.isfile(master_path) if master_path else False
        kit["vos"].sort()
        result.append(kit)
    return result


def _find_reel_card(date_str: str, pick_id: str) -> str | None:
    """Return absolute path to card PNG if it exists (subdir layout)."""
    if not _RE_DATE.match(date_str) or not _RE_PICK_ID.match(pick_id):
        return None
    # New layout: {date}/{pick_id}/card_{pick_id}.png
    p = os.path.join(_REEL_CARDS_ROOT, date_str, pick_id, f"card_{pick_id}.png")
    if os.path.isfile(p):
        return p
    # Fallback: flat layout {date}/card_{pick_id}.png
    p_flat = os.path.join(_REEL_CARDS_ROOT, date_str, f"card_{pick_id}.png")
    return p_flat if os.path.isfile(p_flat) else None


def _find_reel_vos(date_str: str, pick_id: str) -> list[str]:
    """Return sorted list of absolute paths to VO MP3s (subdir layout)."""
    if not _RE_DATE.match(date_str) or not _RE_PICK_ID.match(pick_id):
        return []
    # New layout: {date}/{pick_id}/vo_*.mp3
    sub_dir = os.path.join(_REEL_CARDS_ROOT, date_str, pick_id)
    if os.path.isdir(sub_dir):
        vos = []
        for fname in sorted(os.listdir(sub_dir)):
            if fname.startswith(f"vo_{pick_id}_v") and fname.endswith(".mp3"):
                vos.append(os.path.join(sub_dir, fname))
        if vos:
            return vos
    # Fallback: flat layout {date}/vo_*.mp3
    date_dir = os.path.join(_REEL_CARDS_ROOT, date_str)
    if not os.path.isdir(date_dir):
        return []
    vos = []
    for fname in sorted(os.listdir(date_dir)):
        if fname.startswith(f"vo_{pick_id}_v") and fname.endswith(".mp3"):
            vos.append(os.path.join(date_dir, fname))
    return vos


# -- Reel Kit API routes -----------------------------------------------------

@app.route("/admin/api/reel-kits")
@require_auth
def api_reel_kits():
    """GET — scan reel-cards root for kits on a date."""
    date_str = request.args.get("date", "")
    if not _RE_DATE.match(date_str):
        return Response('{"error":"invalid date"}', status=400, mimetype="application/json")
    kits = _scan_reel_kits(date_str)
    return Response(
        json.dumps({"date": date_str, "kits": kits}),
        mimetype="application/json",
    )


@app.route("/admin/api/reel-download", methods=["POST"])
@require_auth
def api_reel_download():
    """POST — return ZIP with card PNG + VO MP3s for a pick."""
    try:
        body = request.get_json(force=True)
        date_str = (body or {}).get("date", "").strip()
        pick_id = (body or {}).get("pick_id", "").strip()
    except Exception:
        return Response('{"error":"bad request"}', status=400, mimetype="application/json")

    if not _RE_DATE.match(date_str) or not _RE_PICK_ID.match(pick_id):
        return Response('{"error":"invalid params"}', status=400, mimetype="application/json")

    card_path = _find_reel_card(date_str, pick_id)
    vos = _find_reel_vos(date_str, pick_id)
    if not card_path:
        return Response('{"error":"card not found"}', status=404, mimetype="application/json")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(card_path, os.path.basename(card_path))
        for vo in vos:
            zf.write(vo, os.path.basename(vo))
    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="reel_{pick_id}.zip"'},
    )


@app.route("/admin/api/reel-upload", methods=["POST"])
@app.route("/admin/api/task-hub/reel/<pick_id>/upload", methods=["POST"])
@require_auth
def api_reel_upload(pick_id=None):
    """POST — upload master Reel MP4, create MOQ item for Instagram ONLY."""
    if request.content_length and request.content_length > MAX_CONTENT_LENGTH:
        return Response('{"error":"file too large"}', status=413, mimetype="application/json")

    f = request.files.get("file")
    pick_id = request.form.get("pick_id", "").strip() or (pick_id or "")
    date_str = request.form.get("date", "").strip()
    block_id = request.form.get("block_id", "").strip()

    if not f or not pick_id or not date_str:
        return Response('{"error":"missing file, pick_id, or date"}', status=400, mimetype="application/json")
    if not _RE_DATE.match(date_str) or not _RE_PICK_ID.match(pick_id):
        return Response('{"error":"invalid params"}', status=400, mimetype="application/json")

    # Save master MP4
    masters_dir = os.path.join(_REEL_MASTERS_ROOT, date_str)
    os.makedirs(masters_dir, exist_ok=True)
    master_path = os.path.join(masters_dir, f"{pick_id}_master.mp4")
    f.save(master_path)

    video_url = f"{_REEL_PUBLIC_BASE}/{date_str}/{pick_id}_master.mp4"

    # Schedule for next 3h boundary in SAST
    _SAST_OFF = timezone(timedelta(hours=2))
    now_sast = datetime.now(_SAST_OFF)
    current_3h = now_sast.hour // 3 * 3
    next_3h = current_3h + 3
    if next_3h >= 24:
        sched = now_sast.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        sched = now_sast.replace(hour=next_3h, minute=0, second=0, microsecond=0)
    sched_iso = sched.isoformat()

    # Create ONE MOQ page for Instagram only (Override 2 — TikTok uses B.R.U. drip)
    moq_title = f"Reel — {pick_id[:8]} ({date_str})"
    moq_body = {
        "parent": {"database_id": _REEL_MARKETING_DATA_SOURCE},
        "properties": {
            "Name": {"title": [{"text": {"content": moq_title}}]},
            "Status": {"select": {"name": "Awaiting Approval"}},
            "Channel": {"select": {"name": "Instagram"}},
            "Asset Link": {"url": video_url},
            "Scheduled Time": {"date": {"start": sched_iso}},
        },
    }
    result = _notion_request("pages", body=moq_body)
    ok = bool(result and result.get("object") == "page")

    # Invalidate cache
    with _notion_cache_lock:
        _notion_cache.pop("marketing_queue", None)
    with _page_cache_lock:
        _page_cache.pop("social_ops_full", None)

    return Response(
        json.dumps({"ok": ok, "video_url": video_url, "scheduled": sched_iso, "channel": "Instagram"}),
        mimetype="application/json",
    )


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

def _prime_cache_on_boot() -> None:
    """Warm social-ops and task-hub caches 10s after boot (avoids cold hits on first open)."""
    import urllib.request as _ur
    time.sleep(10)
    base = f"http://localhost:{PORT}"
    creds = f"{DASHBOARD_USER}:{DASHBOARD_PASS}"
    import base64 as _b64
    auth_hdr = "Basic " + _b64.b64encode(creds.encode()).decode()
    for path in ("/admin/social-ops", "/admin/task-hub"):
        try:
            req = _ur.Request(base + path, headers={"Authorization": auth_hdr})
            with _ur.urlopen(req, timeout=30):
                pass
            log.info(f"[prime-cache] warmed {path}")
        except Exception as _e:
            log.debug(f"[prime-cache] {path} skipped: {_e}")


if __name__ == "__main__":
    print(f"MzansiEdge Admin Panel starting on port {PORT}")
    print(f"  URL:  http://localhost:{PORT}/admin/health")
    print(f"  Auth: {DASHBOARD_USER}:***")
    print(f"  DB:   {SCRAPERS_DB}")
    if os.getenv("PRIME_CACHE_ON_BOOT", "1") != "0":
        threading.Thread(target=_prime_cache_on_boot, daemon=True, name="cache-primer").start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
