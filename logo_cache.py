"""IMG-W1.5 — Team Logo Fetcher & Cache for MzansiEdge.

Public API
----------
    get_logo(team_name, sport, league="") -> Path | None
        Cache-first lookup. No API calls. Safe on the render path.

    prefetch_logo(team_name, sport, league="") -> Path | None
        Fetch from API, process, and cache. Used by scripts/fetch_logos.py.

    _fuzzy_match_team(raw_name, known_names) -> str | None
        Fuzzy match at threshold 0.8 — exported for scripts/fetch_logos.py.

Cache structure
---------------
    DB:    bot/data/logo_cache.db  (SQLite via get_connection() — WAL mode)
    Files: bot-data-shared/card_assets/logos/team/{sport}/{team_key}.png
           (shared volume — safe to read from any bot tree, including bot-prod)

Override via env vars for testing:
    LOGO_CACHE_DB  — path to SQLite DB (default: data/logo_cache.db)
    LOGO_CACHE_DIR — path to logo storage dir (default: card_assets/logos/team)

API Sources (all require keys in .env)
--------------------------------------
    soccer  → API-Football v3   (API_FOOTBALL_KEY)
    rugby   → API-Sports Rugby  (API_SPORTS_KEY)
    cricket → Sportmonks v2     (SPORTMONKS_CRICKET_TOKEN)
    mma     → API-Sports MMA    (API_SPORTS_KEY)
    boxing  → API-Sports MMA    (API_SPORTS_KEY)

Constraints
-----------
    - NO API calls in get_logo() — always cache-first
    - 96×96 RGBA PNG output — transparent backgrounds preserved (LANCZOS resize)
    - Fuzzy match threshold 0.8 (difflib.get_close_matches)
    - Failed fetches recorded as status='failed' to avoid retry storms
    - Uses get_connection() — WAL + busy_timeout enforced (W81-DBLOCK)
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from db_connection import get_connection

log = logging.getLogger("mzansi.logo_cache")

# ── Paths (override via env for testing) ─────────────────────────────────────

_BOT_DIR = Path(__file__).parent

_LOGO_DB: str = os.environ.get(
    "LOGO_CACHE_DB",
    str(_BOT_DIR / "data" / "logo_cache.db"),
)

# Shared volume: neutral location readable from any bot tree (dev OR bot-prod).
# FIX-LOGO-CACHE-RELATIVE-PATHS-01 — do not revert to _BOT_DIR / "card_assets".
_SHARED_ASSETS: Path = Path("/home/paulsportsza/bot-data-shared/card_assets")

_LOGO_DIR: Path = Path(os.environ.get(
    "LOGO_CACHE_DIR",
    str(_SHARED_ASSETS / "logos" / "team"),
))

# ── Constants ─────────────────────────────────────────────────────────────────

LOGO_SIZE = (96, 96)
FUZZY_THRESHOLD = 0.8
REQUEST_TIMEOUT = 10

# Normalised sport → api_source label (used by _fetch_raw_logo and scripts/fetch_logos.py)
SPORT_TO_SOURCE: dict[str, str] = {
    "soccer":   "api_football",
    "football": "api_football",
    "rugby":    "api_sports_rugby",
    "cricket":  "sportmonks",
    "mma":      "api_sports_mma",
    "boxing":   "api_sports_mma",
    "combat":   "api_sports_mma",
}


# ── DB init ───────────────────────────────────────────────────────────────────

def _init_db() -> None:
    """Create logo_cache table and index if they do not exist."""
    conn = get_connection(db_path=_LOGO_DB)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS logo_cache (
                    team_key  TEXT PRIMARY KEY,
                    team_name TEXT NOT NULL,
                    sport     TEXT NOT NULL,
                    league    TEXT NOT NULL DEFAULT '',
                    file_path TEXT,
                    api_source TEXT,
                    fetched_at TEXT NOT NULL,
                    status    TEXT NOT NULL DEFAULT 'pending'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_logo_sport_status
                ON logo_cache(sport, status)
            """)
    finally:
        conn.close()


# Initialise on module import so the table always exists.
_init_db()


# ── Key / path helpers ────────────────────────────────────────────────────────

def _team_key(team_name: str, sport: str) -> str:
    """Normalise team name + sport to a filesystem-safe cache key.

    Example: ("Kaizer Chiefs", "soccer") → "soccer_kaizer_chiefs"
    """
    clean = re.sub(r"[^a-z0-9]+", "_", team_name.lower().strip())
    return f"{sport.lower()}_{clean.strip('_')}"


def _logo_path(team_key: str, sport: str) -> Path:
    """Derive full file path for a logo PNG, creating the sport subdir if needed."""
    sport_dir = _LOGO_DIR / sport.lower()
    sport_dir.mkdir(parents=True, exist_ok=True)
    return sport_dir / f"{team_key}.png"


# ── Fuzzy matching ────────────────────────────────────────────────────────────

def _fuzzy_match_team(raw_name: str, known_names: list[str]) -> str | None:
    """Return the best canonical match from known_names at FUZZY_THRESHOLD.

    Matching is case-insensitive. Returns the original canonical casing or
    None if no match meets the threshold.
    """
    if not known_names:
        return None
    lower_known = [n.lower() for n in known_names]
    matches = difflib.get_close_matches(
        raw_name.lower(),
        lower_known,
        n=1,
        cutoff=FUZZY_THRESHOLD,
    )
    if not matches:
        return None
    matched_lower = matches[0]
    for name in known_names:
        if name.lower() == matched_lower:
            return name
    return None


# ── Cache lookup (no API calls) ───────────────────────────────────────────────

def get_logo(team_name: str, sport: str, league: str = "") -> Path | None:
    """Cache-first logo lookup. No API calls. Safe on the render path.

    Returns a local Path to a 96×96 RGBA PNG on cache hit, None on miss.
    A cache entry exists but file is missing → returns None (treat as miss).
    """
    key = _team_key(team_name, sport)
    try:
        conn = get_connection(db_path=_LOGO_DB, timeout_ms=3000)
        try:
            row = conn.execute(
                "SELECT file_path, status FROM logo_cache WHERE team_key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        log.debug("get_logo DB error: %s", exc)
        return None

    if row is None or row["status"] != "ok" or not row["file_path"]:
        return None

    fp = Path(row["file_path"])
    # Guard: remap stale dev-tree paths to shared volume (handles old DB restores).
    _dev_prefix = "/home/paulsportsza/bot/card_assets/"
    if str(fp).startswith(_dev_prefix):
        fp = _SHARED_ASSETS / fp.relative_to(_dev_prefix)
        log.warning("get_logo: remapped dev-tree path to shared volume: %s", fp)
    return fp if fp.exists() else None


# ── Env / key resolution ──────────────────────────────────────────────────────

def _get_env(var: str) -> str:
    """Read env var, falling back to .env file in the bot directory."""
    val = os.environ.get(var, "")
    if val:
        return val
    env_file = _BOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(var + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http_get_json(url: str, headers: dict[str, str]) -> dict | None:
    """Synchronous JSON GET with custom headers. Returns parsed dict or None."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        log.warning("HTTP GET failed: %s — %s", url, exc)
        return None


def _http_get_bytes(url: str) -> bytes | None:
    """Download raw bytes from a URL. Returns None on any error."""
    req = urllib.request.Request(url, headers={"User-Agent": "MzansiEdge/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read()
    except Exception as exc:
        log.warning("Image download failed: %s — %s", url, exc)
        return None


# ── Per-sport API fetchers ────────────────────────────────────────────────────

def _fetch_soccer_logo(team_name: str) -> bytes | None:
    """API-Football v3 — team logo via /teams?name=."""
    key = _get_env("API_FOOTBALL_KEY")
    if not key:
        log.warning("API_FOOTBALL_KEY not set — cannot fetch soccer logo")
        return None
    url = f"https://v3.football.api-sports.io/teams?name={urllib.parse.quote(team_name)}"
    data = _http_get_json(url, {"x-apisports-key": key})
    if not data or not data.get("response"):
        return None
    logo_url = data["response"][0].get("team", {}).get("logo")
    return _http_get_bytes(logo_url) if logo_url else None


def _fetch_rugby_logo(team_name: str) -> bytes | None:
    """API-Sports Rugby v2 — team logo via /teams?name=."""
    key = _get_env("API_SPORTS_KEY")
    if not key:
        log.warning("API_SPORTS_KEY not set — cannot fetch rugby logo")
        return None
    url = f"https://v2.rugby.api-sports.io/teams?name={urllib.parse.quote(team_name)}"
    data = _http_get_json(url, {"x-apisports-key": key})
    if not data or not data.get("response"):
        return None
    logo_url = data["response"][0].get("logo")
    return _http_get_bytes(logo_url) if logo_url else None


def _fetch_cricket_logo(team_name: str) -> bytes | None:
    """Sportmonks Cricket v2 — team image via /teams?filter[name]=."""
    token = _get_env("SPORTMONKS_CRICKET_TOKEN")
    if not token:
        log.warning("SPORTMONKS_CRICKET_TOKEN not set — cannot fetch cricket logo")
        return None
    url = (
        "https://cricket.sportmonks.com/api/v2.0/teams"
        f"?api_token={token}&filter[name]={urllib.parse.quote(team_name)}"
    )
    data = _http_get_json(url, {})
    if not data or not data.get("data"):
        return None
    img_url = data["data"][0].get("image_path")
    return _http_get_bytes(img_url) if img_url else None


def _fetch_mma_logo(team_name: str) -> bytes | None:
    """API-Sports MMA v1 — fighter photo via /fighters?search=."""
    key = _get_env("API_SPORTS_KEY")
    if not key:
        log.warning("API_SPORTS_KEY not set — cannot fetch MMA logo")
        return None
    url = f"https://v1.mma.api-sports.io/fighters?search={urllib.parse.quote(team_name)}"
    data = _http_get_json(url, {"x-apisports-key": key})
    if not data or not data.get("response"):
        return None
    photo_url = data["response"][0].get("photo")
    return _http_get_bytes(photo_url) if photo_url else None


def _fetch_raw_logo(team_name: str, sport: str) -> tuple[bytes | None, str]:
    """Dispatch to the correct API source.

    Returns (raw_image_bytes_or_None, api_source_label).
    Source label is taken from SPORT_TO_SOURCE for consistency.
    """
    sport_lower = sport.lower()
    api_source = SPORT_TO_SOURCE.get(sport_lower, "unknown")
    if sport_lower in ("soccer", "football"):
        return _fetch_soccer_logo(team_name), api_source
    if sport_lower == "rugby":
        return _fetch_rugby_logo(team_name), api_source
    if sport_lower == "cricket":
        return _fetch_cricket_logo(team_name), api_source
    if sport_lower in ("mma", "boxing", "combat"):
        return _fetch_mma_logo(team_name), api_source
    log.warning("No logo API source for sport '%s'", sport)
    return None, api_source


# ── Image processing ──────────────────────────────────────────────────────────

def _process_image(raw_bytes: bytes) -> bytes | None:
    """Convert raw image bytes to 96×96 RGBA PNG.

    Transparent backgrounds are preserved via RGBA conversion.
    Returns PNG bytes or None on processing failure.
    """
    try:
        img = Image.open(BytesIO(raw_bytes)).convert("RGBA")
        img = img.resize(LOGO_SIZE, Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=False)
        return buf.getvalue()
    except Exception as exc:
        log.warning("Image processing failed: %s", exc)
        return None


# ── Public prefetch ───────────────────────────────────────────────────────────

def prefetch_logo(team_name: str, sport: str, league: str = "") -> Path | None:
    """Fetch logo from the appropriate API, process, save to disk, and cache.

    Skips teams that are already cached successfully.
    Records status='failed' on API or processing failure to avoid retry storms.
    NOT for use in the render path — use get_logo() there.

    Returns local Path on success, None on failure.
    """
    # Fast exit if already cached
    existing = get_logo(team_name, sport, league)
    if existing is not None:
        log.debug("Logo already cached, skipping: %s (%s)", team_name, sport)
        return existing

    key = _team_key(team_name, sport)
    dest = _logo_path(key, sport)
    now = datetime.now(timezone.utc).isoformat()

    raw_bytes, api_source = _fetch_raw_logo(team_name, sport)

    png_bytes: bytes | None = None
    if raw_bytes:
        png_bytes = _process_image(raw_bytes)

    conn = get_connection(db_path=_LOGO_DB)
    try:
        if png_bytes:
            dest.write_bytes(png_bytes)
            with conn:
                conn.execute(
                    """INSERT OR REPLACE INTO logo_cache
                       (team_key, team_name, sport, league, file_path,
                        api_source, fetched_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'ok')""",
                    (key, team_name, sport, league, str(dest), api_source, now),
                )
            log.info("Logo cached: %s → %s", team_name, dest)
            return dest
        else:
            with conn:
                conn.execute(
                    """INSERT OR REPLACE INTO logo_cache
                       (team_key, team_name, sport, league, file_path,
                        api_source, fetched_at, status)
                       VALUES (?, ?, ?, ?, NULL, ?, ?, 'failed')""",
                    (key, team_name, sport, league, api_source, now),
                )
            log.warning("Logo fetch failed: %s (%s)", team_name, sport)
            return None
    finally:
        conn.close()
