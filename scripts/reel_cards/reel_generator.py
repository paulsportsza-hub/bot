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
BOT_DIR      = SCRIPT_DIR.parents[1]          # /home/paulsportsza/bot
SCRAPERS_DB  = "/home/paulsportsza/scrapers/odds.db"
OUTPUT_ROOT  = Path("/var/www/mzansiedge/assets/reel-cards")
ENV_FILE     = "/home/paulsportsza/publisher/.env"
LOG_DIR      = Path("/home/paulsportsza/logs")
BG_ASSETS    = SCRIPT_DIR / "assets"  # bg-{tier}.png lives here

NOTION_TOKEN    = os.environ.get("NOTION_TOKEN", "")
TASK_HUB_PAGE   = "31ed9048-d73c-814e-a179-ccd2cf35df1d"
MOQ_DB_ID       = "9061c15b-e8de-416d-8d61-e6b1d4d37f9f"
NOTION_VERSION  = "2022-06-28"

TIERS = ["diamond", "gold", "silver", "bronze"]

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("reel_generator")


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


# ── Step 1: Query edge picks ───────────────────────────────────────────────────

def query_top_picks() -> dict:
    """Return dict of {tier: pick_dict} for tiers that have an unsettled edge."""
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
        LIMIT 1
    """
    results = {}
    try:
        conn = sqlite3.connect(SCRAPERS_DB, timeout=15)
        conn.row_factory = sqlite3.Row
        for tier in TIERS:
            row = conn.execute(sql, (tier,)).fetchone()
            if row:
                results[tier] = dict(row)
                log.info("[QUERY] %s tier → %s (score=%.1f)", tier.upper(),
                         row["match_key"], row["composite_score"])
            else:
                log.info("[QUERY] %s tier → no unsettled picks", tier.upper())
        conn.close()
    except Exception as exc:
        log.error("[QUERY] DB error: %s", exc)
    return results


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

    pick = {
        "tier":          tier,
        "home_team":     home,
        "away_team":     away,
        "pick_team":     pick_team,
        "league":        row["league"].replace("_", " ").title(),
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

    # Archive existing today's Awaiting Approval Reel Still items
    existing = _notion_request("POST", f"/databases/{MOQ_DB_ID}/query", {
        "filter": {
            "and": [
                {"property": "Status", "select": {"equals": "Awaiting Approval"}},
                {"property": "Title", "rich_text": {"contains": f"Reel Still"}},
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
        log.info("[MOQ] Archived %d stale Awaiting Approval item(s) for %s", archived, today)

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
        composite   = r["composite_score"]
        card_url    = r["card_url"]
        still_url   = r.get("still_url", card_url)
        pid         = r["pick_id"]

        # TG-AUTOGEN-REWRITE-01 Phase 2: captions via shared formatter (10-section)
        _PUB_DIR = "/home/paulsportsza/publisher"
        if _PUB_DIR not in sys.path:
            sys.path.insert(0, _PUB_DIR)
        from telegram_news_formatter import format_teaser as _fmt_teaser  # type: ignore[import]
        from telegram_news_formatter import format_build_up as _fmt_build_up  # type: ignore[import]

        _edge_data_alerts = {
            "outcome": pick_team,
            "odds": odds,
            "bookmaker": bookmaker,
            "composite_score": composite,
        }

        # G2: Alerts caption — push-notification surface (Gold/Diamond), post_type=teaser
        alerts_caption = _fmt_teaser(
            match=f"{home} vs {away}",
            tier=tier,
            league=league_upper,
            kickoff=match_date,
            broadcast="",
            edge_data=_edge_data_alerts,
            link="https://mzansiedge.co.za",
        )

        # G3: Community caption — conversational surface (Silver/Bronze), post_type=build_up
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

        # Derive video URL for community items (Silver/Bronze → reel video)
        video_url = (
            f"https://mzansiedge.co.za/assets/reel-cards/{today}/{pid}/master_{pid}.mp4"
        )

        # TG-SURFACE-SPLIT-01 — tier-based Telegram routing
        # Gold/Diamond → Telegram Alerts (push-notification, still PNG)
        # Silver/Bronze → Telegram Community (conversation, video)
        if tier in ("gold", "diamond"):
            tg_channel   = "Telegram Alerts"
            tg_asset     = still_url
            tg_caption   = alerts_caption
            tg_emoji     = "🖼️"
            tg_post_type = "teaser"
        else:
            tg_channel   = "Telegram Community"
            tg_asset     = video_url
            tg_caption   = community_caption
            tg_emoji     = "🎬"
            tg_post_type = "build_up"

        # One MOQ item per channel (Channel is a select, not multi-select)
        tg_channels = [
            (tg_channel, tg_asset, tg_caption, tg_emoji, tg_post_type),
            ("WhatsApp Channel", still_url, alerts_caption, "🖼️", "teaser"),
        ]
        for channel, asset, copy, emoji, post_type_val in tg_channels:
            moq_props: dict = {
                "Title": {"title": [{"text": {"content": f"{emoji} Reel Still — {tier_upper} — {channel} — {today}"}}]},
                "Status": {"select": {"name": "Awaiting Approval"}},
                "Channel": {"select": {"name": channel}},
                "Asset Link": {"url": asset},
                "Final Copy": {"rich_text": [{"text": {"content": copy}}]},
                "Lane": {"select": {"name": "Content/Social"}},
                "Post Type": {"select": {"name": post_type_val}},
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
    log.info("=" * 60)
    log.info("reel_generator.py starting — %s", datetime.now().isoformat())
    log.info("=" * 60)

    today = datetime.now().strftime("%Y-%m-%d")
    env   = _load_env(ENV_FILE)

    # ── Step 1: Query picks ────────────────────────────────────────────────────
    picks = query_top_picks()
    if not picks:
        log.warning("[MAIN] No unsettled edges found for any tier. Exiting.")
        sys.exit(0)

    # Diamond rarity gate: max 1 per 10 days
    if "diamond" in picks and _diamond_used_recently(today):
        log.info("[RARITY] Diamond gate — skipping Diamond, promoting to Gold pool")
        del picks["diamond"]

    # ── Steps 2+3: Render cards + VOs ─────────────────────────────────────────
    rendered = []
    for tier, row in picks.items():
        result = render_card(row, tier, today)
        if result is None:
            continue
        pid, card_path, pick_dict = result

        home      = pick_dict["home_team"]
        away      = pick_dict["away_team"]
        card_url  = (
            f"https://mzansiedge.co.za/assets/reel-cards/{today}/{pid}/card_{pid}.png"
        )
        still_url = generate_still(card_path, tier, pid, today) or card_url

        vos = generate_vos(pick_dict, pid, today, env)

        rendered.append({
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
            "still_url":        still_url,
            "vo_paths":         vos,
        })

    if not rendered:
        log.error("[MAIN] No cards rendered successfully. Exiting.")
        sys.exit(1)

    log.info("[MAIN] Rendered %d card(s): %s", len(rendered),
             [r["tier"] for r in rendered])

    # ── Step 4: Task Hub ───────────────────────────────────────────────────────
    add_task_hub_blocks(rendered, today)

    # ── Step 5: MOQ items ──────────────────────────────────────────────────────
    create_moq_items(rendered, today)

    # ── Step 6: Crontab ───────────────────────────────────────────────────────
    pre_count, post_count = add_crontab()

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("  Today: %s", today)
    log.info("  Cards rendered: %d", len(rendered))
    for r in rendered:
        log.info("  [%s] %s vs %s → %s", r["tier"].upper(),
                 r["home_team"], r["away_team"], r["card_path"])
        log.info("         VO count: %d", len(r["vo_paths"]))
        log.info("         URL: %s", r["card_url"])
    log.info("  Crontab lines: %d → %d", pre_count, post_count)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
