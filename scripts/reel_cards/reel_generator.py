#!/usr/bin/env python3
"""
reel_generator.py — REEL-GEN-01
Daily Reel Card + VO Generator for MzansiEdge.
Runs at 06:00 UTC (08:00 SAST) via crontab.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import sys
import urllib.request
import urllib.error
import json
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))  # ensure sibling modules (render_reel_card) import from any cwd
BOT_DIR      = SCRIPT_DIR.parents[1]          # /home/paulsportsza/bot
SCRAPERS_DB  = "/home/paulsportsza/scrapers/odds.db"
OUTPUT_ROOT  = Path("/var/www/mzansiedge/assets/reel-cards")
ENV_FILE     = "/home/paulsportsza/publisher/.env"
LOG_DIR      = Path("/home/paulsportsza/logs")
BG_ASSETS    = SCRIPT_DIR / "assets"  # bg-{tier}.png lives here

# ── Early env loader ──────────────────────────────────────────────────────────
# _load_env() below runs at main() time; module-level constants (NOTION_TOKEN)
# evaluate at import. This block hydrates os.environ from publisher/.env BEFORE
# the constants below are evaluated so secrets never live in the source file.
try:
    with open(ENV_FILE) as _envf:
        for _line in _envf:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
except Exception:
    pass

NOTION_TOKEN    = os.environ.get("NOTION_TOKEN", "")
TASK_HUB_PAGE   = "31ed9048-d73c-814e-a179-ccd2cf35df1d"
MOQ_DB_ID       = "9061c15b-e8de-416d-8d61-e6b1d4d37f9f"
NOTION_VERSION  = "2022-06-28"
EDGEOPS_CHAT_ID = os.environ.get("EDGEOPS_CHAT_ID", "")

TIERS = ["diamond", "gold", "silver", "bronze"]
MAX_REELS_PER_DAY = 1
SPORT_DIVERSITY_DAYS = 1    # no same sport within this many days
MATCH_UNIQUENESS_DAYS = 14  # no same match_key within this many days

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("reel_generator")

# ── Cadence: IG reel scheduled-time slot ──────────────────────────────────────
# Single source of truth lives in publisher/cadence.py.  If that file is missing
# or unparseable, fall back to the hard-wired default and log a WARNING so ops
# knows the cadence module needs attention.
_REEL_SLOT_FALLBACK = "20:30"
try:
    sys.path.insert(0, str(BOT_DIR.parent))  # expose /home/paulsportsza/ for publisher.*
    from publisher.cadence import IG_REEL_SLOT as _IG_REEL_SLOT
    _REEL_SLOT_SOURCE = "cadence.IG_REEL_SLOT"
except Exception:
    log.warning(
        "publisher/cadence.py unavailable — falling back to %s SAST for reel scheduled_time",
        _REEL_SLOT_FALLBACK,
    )
    _IG_REEL_SLOT = _REEL_SLOT_FALLBACK
    _REEL_SLOT_SOURCE = "fallback (hardcoded %s SAST default)" % _REEL_SLOT_FALLBACK


def _reel_sched_iso(date_str: str) -> tuple[str, str]:
    """Return (ISO-8601 datetime str, human source label) for the IG reel slot.

    Examples:
        "2026-04-22", cadence.IG_REEL_SLOT="20:30"
        → ("2026-04-22T20:30:00+02:00", "20:30 SAST (from cadence.IG_REEL_SLOT)")
    """
    hh_mm = _IG_REEL_SLOT  # e.g. "19:00" or "20:30"
    iso = f"{date_str}T{hh_mm}:00+02:00"
    label = f"{hh_mm} SAST (from {_REEL_SLOT_SOURCE})"
    return iso, label


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_env(path: str) -> dict:
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        log.warning("Env file not found: %s", path)
    return env


def _pick_id(edge_id: str) -> str:
    return hashlib.md5(edge_id.encode()).hexdigest()[:12]


def _parse_teams_from_match_key(match_key: str) -> tuple[str, str]:
    """Parse home/away from match_key like 'team_a_vs_team_b_2026-04-10'."""
    key = re.sub(r'_\d{4}-\d{2}-\d{2}$', '', match_key)
    if '_vs_' in key:
        home_raw, away_raw = key.split('_vs_', 1)
        home = home_raw.replace('_', ' ').title()
        away = away_raw.replace('_', ' ').title()
    else:
        home, away = match_key, match_key
    return home, away


# ──────────────────────────────────────────────────────────────────────────────
# TEAM NAME ABBREVIATIONS — used to avoid card geometry overflow on long names.
# Applied after .upper() at pick dict construction. Teams not in the dict render
# as-is. Adding a team here applies to home_team, away_team, AND pick_team.
# Canonical v6.4 lock 17 Apr 2026. See .auto-memory/project_card_regression_17apr.md
# ──────────────────────────────────────────────────────────────────────────────
TEAM_ABBREVIATIONS = {
    # IPL (cricket)
    "KOLKATA KNIGHT RIDERS":      "KKR",
    "ROYAL CHALLENGERS BANGALORE":"RCB",
    "ROYAL CHALLENGERS BENGALURU":"RCB",
    "CHENNAI SUPER KINGS":        "CSK",
    "SUNRISERS HYDERABAD":        "SRH",
    "LUCKNOW SUPER GIANTS":       "LSG",
    "RAJASTHAN ROYALS":           "RAJASTHAN",
    "PUNJAB KINGS":               "PUNJAB",
    "DELHI CAPITALS":             "DELHI",
    "MUMBAI INDIANS":             "MUMBAI",
    "GUJARAT TITANS":             "GUJARAT",
    # EPL (football) — long names only
    "MANCHESTER UNITED":          "MAN UTD",
    "MANCHESTER CITY":            "MAN CITY",
    "TOTTENHAM HOTSPUR":          "SPURS",
    "NEWCASTLE UNITED":           "NEWCASTLE",
    "WEST HAM UNITED":            "WEST HAM",
    "NOTTINGHAM FOREST":          "FOREST",
    "BRIGHTON HOVE ALBION":       "BRIGHTON",
    "BRIGHTON & HOVE ALBION":     "BRIGHTON",
    "WOLVERHAMPTON WANDERERS":    "WOLVES",
    "LEICESTER CITY":             "LEICESTER",
    "SHEFFIELD UNITED":           "SHEFFIELD",
    "LUTON TOWN":                 "LUTON",
    # Rugby URC (SA franchises)
    "VODACOM BULLS":              "BULLS",
    "HOLLYWOODBETS SHARKS":       "SHARKS",
    "DHL STORMERS":               "STORMERS",
    "EMIRATES LIONS":             "LIONS",
}

def abbr(name: str) -> str:
    """Return abbreviated team name if listed, else the original. Input expected uppercase."""
    if not name:
        return name
    return TEAM_ABBREVIATIONS.get(name.strip(), name)


def _resolve_pick_team(bet_type: str, home: str, away: str) -> str:
    bt = bet_type.lower()
    if 'home' in bt:
        return home
    if 'away' in bt:
        return away
    if 'draw' in bt:
        return 'Draw'
    return bet_type


def _notion_request(method: str, path: str, body: dict | None = None) -> dict | None:
    url = f"https://api.notion.com/v1{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        log.error("Notion %s %s → HTTP %d: %s", method, path, e.code, body_text[:200])
        return None
    except Exception as exc:
        log.error("Notion request error: %s", exc)
        return None


def _alert_edge_ops(message: str) -> None:
    """Send a plain-text alert to the EdgeOps Telegram chat."""
    token   = os.environ.get("BOT_TOKEN", "")
    chat_id = EDGEOPS_CHAT_ID
    if not token or not chat_id:
        log.warning("[EDGEOPS] BOT_TOKEN or EDGEOPS_CHAT_ID not set — alert skipped")
        return
    payload = json.dumps({"chat_id": chat_id, "text": f"[reel_generator] {message}"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload, method="POST",
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10):
            log.info("[EDGEOPS] Alert sent: %s", message)
    except Exception as exc:
        log.warning("[EDGEOPS] Alert failed: %s", exc)


# ── Step 1: Select single top-tier pick ───────────────────────────────────────

def _select_top_tier_pick(today: str) -> tuple[str, dict] | None:
    """Return (tier, row) for the highest-tier qualifying unsettled edge.
    Tries tiers Diamond → Gold → Silver → Bronze and returns the first match that
    passes the sport-diversity (SPORT_DIVERSITY_DAYS) and match-uniqueness
    (MATCH_UNIQUENESS_DAYS) guards. Diamond rarity gate runs first, independently.
    Returns None when no qualifying edge survives all filters."""
    import sqlite3

    sql = """
        SELECT
            e.edge_id, e.match_key, e.sport, e.league, e.edge_tier,
            e.composite_score, e.bet_type, e.recommended_odds, e.bookmaker,
            e.match_date,
            f.home_team, f.away_team
        FROM edge_results e
        LEFT JOIN fixture_mapping f ON e.match_key = f.match_key
        WHERE e.result IS NULL
          AND e.edge_tier = ?
        ORDER BY e.composite_score DESC
        LIMIT 10
    """
    diamond_blocked = _diamond_used_recently(today)
    if diamond_blocked:
        log.info("[SELECT] Diamond rarity gate active — skipping Diamond for today")

    tiers_to_check = [t for t in TIERS if not (t == "diamond" and diamond_blocked)]

    blocked_sports = _recent_sports_used(today, SPORT_DIVERSITY_DAYS)
    blocked_match_keys = _recent_match_keys_used(today, MATCH_UNIQUENESS_DAYS)
    if blocked_sports:
        log.info("[DIVERSITY] Sports blocked (last %d days): %s", SPORT_DIVERSITY_DAYS, blocked_sports)
    if blocked_match_keys:
        log.info("[DIVERSITY] Match keys blocked (last %d days): %d match(es)", MATCH_UNIQUENESS_DAYS, len(blocked_match_keys))

    any_diversity_excluded = False
    try:
        conn = sqlite3.connect(SCRAPERS_DB, timeout=15)
        conn.row_factory = sqlite3.Row
        for tier in tiers_to_check:
            rows = conn.execute(sql, (tier,)).fetchall()
            if not rows:
                log.info("[SELECT] %s tier — no qualifying edge", tier.upper())
                continue
            for row in rows:
                sport = (row["sport"] or "").lower()
                mk = row["match_key"]
                if sport and sport in blocked_sports:
                    log.info("[DIVERSITY] excluded %s sport=%s reason=sport_repeat", mk, sport)
                    any_diversity_excluded = True
                    continue
                if mk in blocked_match_keys:
                    log.info("[DIVERSITY] excluded %s sport=%s reason=match_repeat", mk, sport)
                    any_diversity_excluded = True
                    continue
                log.info("[SELECT] Top-tier pick: %s — %s (composite=%.1f)",
                         tier.upper(), mk, row["composite_score"])
                conn.close()
                return tier, dict(row)
            log.info("[SELECT] %s tier — all %d candidate(s) excluded by diversity filters",
                     tier.upper(), len(rows))
            any_diversity_excluded = True
        conn.close()
    except Exception as exc:
        log.error("[SELECT] DB error: %s", exc)
        return None

    if any_diversity_excluded:
        log.warning("[SELECT] no_reel_today — diversity filters exhaust pool")
    return None


# ── Step 2: Render card PNG ────────────────────────────────────────────────────

def render_card(row: dict, tier: str, today: str) -> tuple[str, str, dict] | None:
    """Render the reel card PNG. Returns (pick_id, output_path) or None on error."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from render_reel_card import render_reel_card

    edge_id  = row["edge_id"]
    pid      = _pick_id(edge_id)

    home = row.get("home_team") or None
    away = row.get("away_team") or None
    if not home or not away:
        home, away = _parse_teams_from_match_key(row["match_key"])

    pick_team = _resolve_pick_team(row["bet_type"], home, away)

    odds   = float(row["recommended_odds"])
    stake  = 100
    profit = round(stake * (odds - 1))

    # CARD-CASE-LOCK-01 — template geometry (render_reel_card.py) is tuned for UPPERCASE
    # caps-height glyphs only. Lowercase descenders (g/j/p/q/y) break gradient mask alignment
    # in _draw_gradient_text and clip team names. Force .upper() at render boundary.
    # Do NOT remove even if upstream DB is clean — historical regressions have let mixed-case
    # reach this function (see .auto-memory/project_card_regression_17apr.md).
    pick = {
        "tier":          tier,
        "home_team":     abbr(home.upper()),
        "away_team":     abbr(away.upper()),
        "pick_team":     abbr(pick_team.upper()),
        "league":        row["league"].replace("_", " ").upper(),
        "bet_type":      row["bet_type"],
        "recommended_odds": odds,
        "composite_score":  row["composite_score"],
        "bookmaker":     row["bookmaker"],
        "stake":         f"R{stake}",
        "return_amount": f"R{round(stake * odds)}",
        "profit":        f"R{profit}",
    }

    out_dir = OUTPUT_ROOT / today / pid
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / f"card_{pid}.png")

    try:
        render_reel_card(pick, output_path)
        log.info("[RENDER] %s card → %s", tier.upper(), output_path)
        # Save pick metadata for Task Hub display and diversity guards.
        # sport + match_key are read by _recent_sports_used / _recent_match_keys_used.
        meta_path = str(out_dir / "meta.json")
        with open(meta_path, "w") as fh:
            json.dump({
                "pick_team": pick["pick_team"],
                "bookmaker": row["bookmaker"],
                "tier": tier,
                "sport": row.get("sport", ""),
                "match_key": row.get("match_key", ""),
            }, fh)
        return pid, output_path, pick
    except Exception as exc:
        log.error("[RENDER] %s tier failed: %s", tier, exc)
        return None


# ── Step 3: Generate VOs ───────────────────────────────────────────────────────
# Script pools — LOCKED Apr 2026 (Paul approved)

_VO_OPENERS = [
    "Back {TEAM} on {BOOKIE}.",
    "Put your money on {TEAM} with {BOOKIE}.",
    "The pick is {TEAM} on {BOOKIE}.",
    "Get on {TEAM} with {BOOKIE}.",
    "Bet on {TEAM} at {BOOKIE}.",
    "Load up on {TEAM} on {BOOKIE}.",
    "Take {TEAM} at {BOOKIE}.",
    "Your play today — {TEAM} on {BOOKIE}.",
]
_VO_RETURNS = [
    "You could win {RETURNS} from a {STAKE} bet.",
    "Turn {STAKE} into {RETURNS}.",
    "A {STAKE} bet pays {RETURNS}.",
    "Walk away with {RETURNS} from {STAKE}.",
    "Net {RETURNS} from a {STAKE} bet.",
]
_VO_CTAS = [
    "Follow Mzansi Edge for more.",
    "Mzansi Edge — free picks, daily.",
    "Hit follow — Mzansi Edge drops a free tip every day.",
    "That's Mzansi Edge. Follow for more.",
    "Follow Mzansi Edge for your daily edge.",
    "Mzansi Edge. Hit follow for more.",
    "Follow for more — Mzansi Edge.",
    "Free tip every day — follow Mzansi Edge.",
]
_VO_PHONETICS = [
    (r'\bHollywoodbets\b', 'Hollywood Bets'),
    (r'\bSupabets\b',      'Super Bets'),
    (r'\bSuperbets\b',     'Super Bets'),
    (r'\bSuperSportBet\b', 'Super Sport Bet'),
    (r'\bPlayabets\b',     'Player Bets'),
    (r'\bMzansiEdge\b',    'Mzansi Edge'),
    (r'\bbetway\b',        'Betway'),
    (r'\bwsb\b',           'World Sports Betting'),
    (r'\bbetMGM\b',        'Bet MGM'),
]
_VO_STAKE = 100
_VO_ONES = ['','one','two','three','four','five','six','seven','eight','nine',
            'ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen',
            'seventeen','eighteen','nineteen']
_VO_TENS = ['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety']


def _vo_int_words(n: int) -> str:
    if n == 0: return 'zero'
    parts = []
    if n >= 1000:
        parts.append(f"{_vo_int_words(n // 1000)} thousand"); n %= 1000
    if n >= 100:
        parts.append(f"{_VO_ONES[n // 100]} hundred"); n %= 100
    if n >= 20:
        t = _VO_TENS[n // 10]; o = _VO_ONES[n % 10]
        parts.append(f"{t} {o}".strip() if o else t)
    elif n > 0:
        parts.append(_VO_ONES[n])
    return ' '.join(parts)


def _vo_rand(amount: float) -> str:
    words = _vo_int_words(int(amount))
    words = re.sub(
        r'(hundred)\s+((?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|'
        r'one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|'
        r'fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)\b)',
        r'\1 and \2', words)
    return f"{words} rand"


def _diamond_used_recently(today: str, days: int = 10) -> bool:
    """Return True if a Diamond reel was issued in the last `days` days (excluding today)."""
    from datetime import datetime as _dt, timedelta as _td
    try:
        today_dt = _dt.strptime(today, "%Y-%m-%d")
    except ValueError:
        return False
    for i in range(1, days + 1):
        check_date = (today_dt - _td(days=i)).strftime("%Y-%m-%d")
        date_dir = OUTPUT_ROOT / check_date
        if not date_dir.exists():
            continue
        for pick_dir in date_dir.iterdir():
            if pick_dir.is_dir() and (pick_dir / "tier_diamond").exists():
                log.info("[RARITY] Diamond issued on %s — gate active for %s", check_date, today)
                return True
    return False


def _recent_sports_used(today: str, days: int) -> set[str]:
    """Return sports (lowercase) that had a reel pick in the last `days` days (excl. today)."""
    from datetime import datetime as _dt, timedelta as _td
    try:
        today_dt = _dt.strptime(today, "%Y-%m-%d")
    except ValueError:
        return set()
    used: set[str] = set()
    for i in range(1, days + 1):
        check_date = (today_dt - _td(days=i)).strftime("%Y-%m-%d")
        date_dir = OUTPUT_ROOT / check_date
        if not date_dir.exists():
            continue
        for pick_dir in date_dir.iterdir():
            if not pick_dir.is_dir():
                continue
            meta = pick_dir / "meta.json"
            if meta.exists():
                try:
                    data = json.loads(meta.read_text())
                    sport = data.get("sport", "")
                    if sport:
                        used.add(sport.lower())
                except Exception:
                    pass
    return used


def _recent_match_keys_used(today: str, days: int) -> set[str]:
    """Return match_keys that had a reel pick in the last `days` days (excl. today)."""
    from datetime import datetime as _dt, timedelta as _td
    try:
        today_dt = _dt.strptime(today, "%Y-%m-%d")
    except ValueError:
        return set()
    used: set[str] = set()
    for i in range(1, days + 1):
        check_date = (today_dt - _td(days=i)).strftime("%Y-%m-%d")
        date_dir = OUTPUT_ROOT / check_date
        if not date_dir.exists():
            continue
        for pick_dir in date_dir.iterdir():
            if not pick_dir.is_dir():
                continue
            meta = pick_dir / "meta.json"
            if meta.exists():
                try:
                    data = json.loads(meta.read_text())
                    mk = data.get("match_key", "")
                    if mk:
                        used.add(mk)
                except Exception:
                    pass
    return used


def _vo_phonetics(text: str) -> str:
    for pat, rep in _VO_PHONETICS:
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)
    return text


def generate_vos(pick: dict, pid: str, today: str, env: dict) -> list[str]:
    """Generate 3 VO MP3s via ElevenLabs. 2-beat: pick statement + CTA."""
    import urllib.request as _ur

    api_key  = env.get("ELEVENLABS_API_KEY", "")
    voice_id = env.get("ELEVENLABS_VOICE_ID", "")
    if not api_key:
        log.warning("[VO] ELEVENLABS_API_KEY not set — skipping VO generation")
        return []

    out_dir = OUTPUT_ROOT / today / pid
    team    = _vo_phonetics(pick.get("pick_team", ""))
    bookie  = _vo_phonetics(pick.get("bookmaker", ""))
    stake   = _VO_STAKE
    returns = round(stake * pick["recommended_odds"])
    sw      = _vo_rand(stake)
    rw      = _vo_rand(returns)

    openers = random.sample(_VO_OPENERS, 3)
    rets    = random.sample(_VO_RETURNS, 3)
    ctas    = random.sample(_VO_CTAS,    3)

    el_url  = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    created = []
    for i, (opener, ret, cta) in enumerate(zip(openers, rets, ctas), 1):
        script = f"{opener.format(TEAM=team, BOOKIE=bookie)} {ret.format(STAKE=sw, RETURNS=rw)} {cta}"
        log.info("[VO] v%d: %s", i, script)
        payload = json.dumps({
            "text": script,
            "model_id": "eleven_v3",
            "voice_settings": {"stability": 1.0, "similarity_boost": 0.85}
        }).encode()
        req = _ur.Request(el_url, data=payload, method="POST")
        req.add_header("xi-api-key", api_key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "audio/mpeg")
        out_path = str(out_dir / f"vo_{pid}_v{i}.mp3")
        try:
            with _ur.urlopen(req, timeout=60) as resp:
                with open(out_path, "wb") as fh:
                    fh.write(resp.read())
            log.info("[VO] Wrote %s", out_path)
            created.append(out_path)
        except Exception as exc:
            log.error("[VO] v%d failed: %s", i, exc)
    return created


# ── Step 4: Task Hub Reel Kit block ───────────────────────────────────────────

def add_task_hub_blocks(rendered: list[dict], today: str) -> bool:
    """Replace today's Reel Kit to_do blocks on the Task Hub page."""
    # Fetch all blocks from Task Hub
    page_blocks = _notion_request("GET", f"/blocks/{TASK_HUB_PAGE}/children?page_size=100")
    if not page_blocks:
        log.error("[TASKHUB] Could not fetch Task Hub page blocks")
        return False

    # Delete any existing Reel Kit blocks for today
    deleted = 0
    for block in page_blocks.get("results", []):
        btype = block.get("type", "")
        if btype == "to_do":
            parts = block.get("to_do", {}).get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in parts)
            if f"Reel Kit {today}" in text:
                _notion_request("DELETE", f"/blocks/{block['id']}")
                deleted += 1
    if deleted:
        log.info("[TASKHUB] Deleted %d stale Reel Kit block(s) for %s", deleted, today)

    target_id = TASK_HUB_PAGE
    endpoint  = f"/blocks/{target_id}/children"

    children = []
    for r in rendered:
        tier      = r["tier"]
        tier_upper = tier.upper()
        home      = r["home_team"]
        away      = r["away_team"]
        pid       = r["pick_id"]
        card_url  = r["card_url"]

        text = f"🎥 Reel Kit {today} — {tier_upper}: {home} vs {away} — pick_id: {pid}"
        children.append({
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
                "checked": False,
            },
        })

    resp = _notion_request("PATCH", endpoint, {"children": children})
    if resp:
        log.info("[TASKHUB] Added %d Reel Kit block(s)", len(children))
        return True
    return False



# ── Step 2b: Composite still (BG + card) ─────────────────────────────────────

def generate_still(card_path: str, tier: str, pick_id: str, today: str) -> str | None:
    """Composite bg-{tier}.png behind the card PNG, save as still_{pick_id}.png.
    Returns public URL of the still, or None on failure."""
    try:
        from PIL import Image as _Image
    except ImportError:
        log.warning("[STILL] Pillow not available — skipping still generation")
        return None

    bg_file = BG_ASSETS / f"bg-{tier}.png"
    if not bg_file.exists():
        log.warning("[STILL] BG not found: %s — skipping still", bg_file)
        return None

    try:
        card  = _Image.open(card_path).convert("RGBA")
        bg    = _Image.open(bg_file).convert("RGBA")
        # Scale BG to card dimensions
        bg    = bg.resize(card.size, _Image.LANCZOS)
        # Composite: BG first, card on top
        still = _Image.alpha_composite(bg, card)
        out_dir  = Path(card_path).parent
        out_path = str(out_dir / f"still_{pick_id}.png")
        still.save(out_path, "PNG", optimize=True)
        # Write tier marker for Diamond rarity gate
        (out_dir / f"tier_{tier.lower()}").touch()
        # Write JPEG thumbnail (300px wide) for fast dashboard loading
        thumb_w = 300
        thumb_h = int(thumb_w * still.size[1] / still.size[0])
        thumb = still.resize((thumb_w, thumb_h), _Image.LANCZOS).convert("RGB")
        thumb_path = str(out_dir / f"thumb_{pick_id}.jpg")
        thumb.save(thumb_path, "JPEG", quality=75, optimize=True)
        log.info("[STILL] %s → %s", tier.upper(), out_path)
        return f"https://mzansiedge.co.za/assets/reel-cards/{today}/{pick_id}/still_{pick_id}.png"
    except Exception as exc:
        log.error("[STILL] Failed for %s: %s", tier, exc)
        return None


# ── Step 5: Marketing Ops Queue items ─────────────────────────────────────────

def create_moq_items(rendered: list[dict], today: str) -> bool:
    """Create one MOQ item per tier. Archives stale today items first."""
    # First verify the DB is accessible
    schema = _notion_request("GET", f"/databases/{MOQ_DB_ID}")
    if schema is None or schema.get("object") == "error":
        log.warning("[MOQ] Database %s not accessible — skipping MOQ creation. "
                    "Gap noted: MOQ DB not shared with integration.", MOQ_DB_ID)
        return False

    # Archive existing today's Approved Reel Video items (idempotent re-run guard)
    existing = _notion_request("POST", f"/databases/{MOQ_DB_ID}/query", {
        "filter": {
            "and": [
                {"property": "Status", "select": {"equals": "Approved"}},
                {"property": "Title", "rich_text": {"contains": "Reel Video"}},
                {"property": "Title", "rich_text": {"contains": today}},
            ]
        },
        "page_size": 50
    })
    archived = 0
    for page in (existing or {}).get("results", []):
        _notion_request("PATCH", f"/pages/{page['id']}", {"archived": True})
        archived += 1
    if archived:
        log.info("[MOQ] Archived %d stale Approved item(s) for %s", archived, today)

    props_schema = schema.get("properties", {})
    status_field = None
    for k, v in props_schema.items():
        if v.get("type") == "select" and "status" in k.lower():
            status_field = k
            break

    created = 0
    for r in rendered:
        tier        = r["tier"]
        tier_upper  = tier.upper()
        home        = r["home_team"]
        away        = r["away_team"]
        league_upper = r["league_display"].upper()
        match_date  = r["match_date"]
        odds        = r["recommended_odds"]
        pick_team   = r["pick_team"]
        bookmaker   = r["bookmaker"]
        pid         = r["pick_id"]

        # TG-AUTOGEN-REWRITE-01 Phase 2: captions via shared formatter (10-section)
        _PUB_DIR = "/home/paulsportsza/publisher"
        if _PUB_DIR not in sys.path:
            sys.path.insert(0, _PUB_DIR)
        from ai_copy_generator import generate_build_up as _fmt_build_up  # type: ignore[import]

        # Instagram caption — conversational surface, post_type=reel
        community_caption = _fmt_build_up(
            match=f"{home} vs {away}",
            league=league_upper,
            kickoff=match_date,
            broadcast="",
            edge_data={
                "outcome": pick_team,
                "odds": odds,
                "bookmaker": bookmaker,
            },
        )
        # Patch caption into meta.json so the Task Hub dashboard can surface it
        meta_patch_path = OUTPUT_ROOT / today / pid / "meta.json"
        try:
            existing_meta: dict = {}
            if meta_patch_path.exists():
                import json as _json
                with open(meta_patch_path) as _fh:
                    existing_meta = _json.load(_fh)
            existing_meta["caption"] = community_caption
            with open(meta_patch_path, "w") as _fh:
                import json as _json2
                _json2.dump(existing_meta, _fh)
        except Exception as _cap_exc:
            log.warning("[CAPTION] Could not patch meta.json with caption: %s", _cap_exc)

        # BUILD-REEL-VIDEO-IG-ONLY-01 — Instagram reel video only (WA + Community sidecars retired).
        video_url = (
            f"https://mzansiedge.co.za/assets/reel-cards/{today}/{pid}/master_{pid}.mp4"
        )

        # SOCIAL-OPS-TIMELINE-INTEGRITY-01 — Scheduled Time on approval.
        # Slot is read from publisher/cadence.py (IG_REEL_SLOT) so that one edit
        # there updates both this insert and the Social Ops dashboard timeline.
        sched_iso, _ = _reel_sched_iso(today)

        # One MOQ item: Instagram only. WA Channel and Telegram Community sidecars
        # are retired (BUILD-REEL-VIDEO-IG-ONLY-01, 2026-04-21).
        for channel, asset, copy, emoji, post_type_val in [
            ("Instagram", video_url, community_caption, "🎬", "reel"),
        ]:
            moq_props: dict = {
                "Title": {"title": [{"text": {"content": f"{emoji} Reel Video — {tier_upper} — {channel} — {today}"}}]},
                "Status": {"select": {"name": "Approved"}},
                "Channel": {"select": {"name": channel}},
                "Asset Link": {"url": asset},
                "Final Copy": {"rich_text": [{"text": {"content": copy}}]},
                "Lane": {"select": {"name": "Content/Social"}},
                "Post Type": {"select": {"name": post_type_val}},
                "Scheduled Time": {"date": {"start": sched_iso}},
            }
            body = {
                "parent": {"database_id": MOQ_DB_ID},
                "properties": moq_props,
            }
            resp = _notion_request("POST", "/pages", body)
            if resp and resp.get("id"):
                log.info("[MOQ] Created item %s / %s: %s", tier_upper, channel, resp["id"])
                created += 1
            else:
                log.error("[MOQ] Failed to create item for %s / %s", tier_upper, channel)

    return created > 0


# ── Step 5b: Archive stale same-day reel rows ─────────────────────────────────

def _archive_stale_same_day_reels(today: str) -> int:
    """Archive same-day Instagram reel MOQ rows that have no asset and a pending status.
    Sets Status = Archived on each matching row. Returns count archived."""
    schema = _notion_request("GET", f"/databases/{MOQ_DB_ID}")
    if schema is None or schema.get("object") == "error":
        log.warning("[ARCHIVE] MOQ DB not accessible — skipping stale reel archive")
        return 0

    existing = _notion_request("POST", f"/databases/{MOQ_DB_ID}/query", {
        "filter": {
            "and": [
                {"property": "Channel", "select": {"equals": "Instagram"}},
                {"property": "Post Type", "select": {"equals": "reel"}},
                {
                    "or": [
                        {"property": "Status", "select": {"equals": "Draft"}},
                        {"property": "Status", "select": {"equals": "Scheduled"}},
                        {"property": "Status", "select": {"equals": "Approved"}},
                        {"property": "Status", "select": {"equals": "Scheduled-Placeholder"}},
                    ]
                },
                {"property": "Asset Link", "url": {"is_empty": True}},
                {"property": "Scheduled Time", "date": {"equals": today}},
            ]
        },
        "page_size": 50,
    })

    archived = 0
    for page in (existing or {}).get("results", []):
        resp = _notion_request(
            "PATCH", f"/pages/{page['id']}",
            {"properties": {"Status": {"select": {"name": "Archived"}}}},
        )
        if resp and resp.get("id"):
            archived += 1
            log.info("[ARCHIVE] Archived stale reel MOQ row: %s", page["id"])
    if archived:
        log.info("[ARCHIVE] %d stale same-day reel MOQ row(s) → Archived for %s", archived, today)
    else:
        log.info("[ARCHIVE] No stale same-day reel rows found for %s", today)
    return archived


# ── Step 6: Crontab ────────────────────────────────────────────────────────────

CRON_ENTRY = (
    "0 6 * * * "
    "/home/paulsportsza/bot/.venv/bin/python3 "
    "/home/paulsportsza/bot/scripts/reel_cards/reel_generator.py "
    ">> /home/paulsportsza/logs/reel_generator.log 2>&1"
)


def add_crontab() -> tuple[int, int]:
    """Add crontab entry. Returns (pre_count, post_count)."""
    import subprocess

    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout
    pre_count = len(existing.splitlines()) if existing.strip() else 0

    if CRON_ENTRY in existing:
        log.info("[CRON] Entry already present (%d lines)", pre_count)
        return pre_count, pre_count

    new_crontab = existing.rstrip("\n") + "\n" + CRON_ENTRY + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
    if proc.returncode != 0:
        log.error("[CRON] crontab write failed: %s", proc.stderr)
        return pre_count, pre_count

    result2 = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    post_count = len(result2.stdout.splitlines()) if result2.stdout.strip() else 0
    log.info("[CRON] Added entry. Lines: %d → %d", pre_count, post_count)

    # Update checksum if script exists
    baseline_script = Path("/home/paulsportsza/scripts/update_cron_baseline.sh")
    if baseline_script.exists():
        subprocess.run(["bash", str(baseline_script)], capture_output=True)

    return pre_count, post_count


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MzansiEdge daily reel generator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print tier selection + MOQ preview without writing")
    args = parser.parse_args()
    dry_run = args.dry_run

    log.info("=" * 60)
    log.info("reel_generator.py starting — %s%s",
             datetime.now().isoformat(), " [DRY RUN]" if dry_run else "")
    log.info("=" * 60)

    today = datetime.now().strftime("%Y-%m-%d")
    env   = _load_env(ENV_FILE)

    # ── Archive stale same-day reel rows (before selecting / inserting) ────────
    # FIX-REEL-GEN-TOP-TIER-ONLY-01: run before any new row is written so the
    # archive step always sees the pre-run state.
    if not dry_run:
        _archive_stale_same_day_reels(today)

    # ── Step 1: Select single top-tier pick ───────────────────────────────────
    # MAX_REELS_PER_DAY = 1: pick the highest qualifying tier, ignore the rest.
    selection = _select_top_tier_pick(today)
    if selection is None:
        log.warning("[MAIN] no_reel_today — no qualifying edges for any tier. No reel queued.")
        if not dry_run:
            _alert_edge_ops(
                f"no_reel_today — {today}: no qualifying edge found across all tiers. "
                "No reel row created."
            )
        sys.exit(0)

    tier, row = selection

    # ── Dry-run preview ────────────────────────────────────────────────────────
    if dry_run:
        home = row.get("home_team") or None
        away = row.get("away_team") or None
        if not home or not away:
            home, away = _parse_teams_from_match_key(row["match_key"])
        _, sched_source = _reel_sched_iso(today)
        blocked_sports = _recent_sports_used(today, SPORT_DIVERSITY_DAYS)
        blocked_match_keys = _recent_match_keys_used(today, MATCH_UNIQUENESS_DAYS)
        sport = (row.get("sport") or "").lower()
        print(f"\n{'=' * 60}")
        print("DRY RUN — FIX-REEL-GEN-SPORT-DIVERSITY-01")
        print(f"  Diversity filter (sport, last {SPORT_DIVERSITY_DAYS}d): {blocked_sports or '(none)'}")
        print(f"  Diversity filter (match, last {MATCH_UNIQUENESS_DAYS}d): {len(blocked_match_keys)} blocked match(es)")
        sport_flag = " ⚠ WOULD BE BLOCKED (sport_repeat)" if sport in blocked_sports else " ✓ passes sport filter"
        match_flag = " ⚠ WOULD BE BLOCKED (match_repeat)" if row["match_key"] in blocked_match_keys else " ✓ passes match filter"
        print(f"  Chosen sport  : {sport}{sport_flag}")
        print(f"  Chosen match  : {row['match_key']}{match_flag}")
        print()
        print(f"  Tier selected : {tier.upper()}")
        print(f"  Match         : {home} vs {away}")
        print(f"  Bet type      : {row['bet_type']}")
        print(f"  Odds          : {row['recommended_odds']}")
        print(f"  Bookmaker     : {row['bookmaker']}")
        print(f"  Composite     : {row['composite_score']:.1f}")
        print()
        print("MOQ Row Preview:")
        print(f"  Title         : 🎬 Reel Video — {tier.upper()} — Instagram — {today}")
        print( "  Status        : Approved")
        print( "  Channel       : Instagram")
        print( "  Post Type     : reel")
        print(f"  Scheduled Time: {sched_source}")
        print( "  Asset Link    : (video URL set post-render)")
        print(f"{'=' * 60}\n")
        sys.exit(0)

    # ── Steps 2+3: Render card + VOs ──────────────────────────────────────────
    render_result = render_card(row, tier, today)
    if render_result is None:
        log.error("[MAIN] Card render failed for %s tier. Exiting.", tier.upper())
        sys.exit(1)

    pid, card_path, pick_dict = render_result
    home      = pick_dict["home_team"]
    away      = pick_dict["away_team"]
    card_url  = (
        f"https://mzansiedge.co.za/assets/reel-cards/{today}/{pid}/card_{pid}.png"
    )
    # Write tier marker for Diamond rarity gate.
    # BUILD-REEL-VIDEO-IG-ONLY-01: Reel Still retired; still composite no longer generated.
    (Path(card_path).parent / f"tier_{tier.lower()}").touch()
    vos = generate_vos(pick_dict, pid, today, env)

    rendered = [{
        "tier":             tier,
        "pick_id":          pid,
        "home_team":        home,
        "away_team":        away,
        "pick_team":        pick_dict["pick_team"],
        "league_display":   pick_dict["league"],
        "match_date":       str(row["match_date"]),
        "recommended_odds": pick_dict["recommended_odds"],
        "bookmaker":        pick_dict["bookmaker"],
        "composite_score":  pick_dict["composite_score"],
        "card_path":        card_path,
        "card_url":         card_url,
        "vo_paths":         vos,
    }]

    log.info("[MAIN] Single top-tier reel — %s: %s vs %s", tier.upper(), home, away)

    # ── Step 4: Task Hub ───────────────────────────────────────────────────────
    add_task_hub_blocks(rendered, today)

    # ── Step 5: MOQ item ───────────────────────────────────────────────────────
    create_moq_items(rendered, today)

    # ── Step 6: Crontab ───────────────────────────────────────────────────────
    pre_count, post_count = add_crontab()

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("SUMMARY — single top-tier reel (MAX_REELS_PER_DAY=%d)", MAX_REELS_PER_DAY)
    log.info("  Today   : %s", today)
    log.info("  Tier    : %s", tier.upper())
    log.info("  Match   : %s vs %s", home, away)
    log.info("  Card    : %s", card_path)
    log.info("  VOs     : %d", len(vos))
    log.info("  URL     : %s", card_url)
    log.info("  Crontab : %d → %d lines", pre_count, post_count)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
