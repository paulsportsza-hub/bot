#!/usr/bin/env python3
"""
backfill_reel_today.py — DASH-POLISH-STORIES-01 / AC2

One-shot backfill for today's 20:30 SAST IG Reel MOQ row when the 06:00 UTC
reel_generator.py cron skipped or partially failed and left no Instagram row.

Imports reel_generator.py read-only — never modifies it. Creates exactly ONE
MOQ page:
    Channel        = Instagram
    Post Type      = reel
    Status         = Pending
    Scheduled Time = {today}T20:30:00+02:00
    Asset Link     = reuse today's rendered master mp4
    Final Copy     = generate_build_up() from publisher/ai_copy_generator

Idempotent: aborts if any Instagram row already exists for today.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REEL_DIR   = SCRIPT_DIR / "reel_cards"
PUB_DIR    = Path("/home/paulsportsza/publisher")

if str(REEL_DIR) not in sys.path:
    sys.path.insert(0, str(REEL_DIR))
if str(PUB_DIR) not in sys.path:
    sys.path.insert(0, str(PUB_DIR))

_IG_REEL_SLOT_FALLBACK = "20:30"
try:
    _publisher_root = str(SCRIPT_DIR.parents[1])  # /home/paulsportsza
    if _publisher_root not in sys.path:
        sys.path.insert(0, _publisher_root)
    from publisher.cadence import IG_REEL_SLOT as _IG_REEL_SLOT
except ImportError:
    _IG_REEL_SLOT = _IG_REEL_SLOT_FALLBACK

# Read-only imports from reel_generator.
from reel_generator import (  # type: ignore[import]
    MOQ_DB_ID,
    TIERS,
    _notion_request,
    _pick_id,
    _resolve_pick_team,
    _parse_teams_from_match_key,
    _select_top_tier_pick,
    abbr,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("backfill_reel_today")


def _today_sast_iso() -> str:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Africa/Johannesburg")).strftime("%Y-%m-%d")
    except Exception:
        return date.today().isoformat()


def _existing_ig_row_for_today(today: str) -> dict | None:
    resp = _notion_request("POST", f"/databases/{MOQ_DB_ID}/query", {
        "filter": {
            "and": [
                {"property": "Channel", "select": {"equals": "Instagram"}},
                {"property": "Title",   "rich_text": {"contains": today}},
            ]
        },
        "page_size": 5,
    })
    if not resp:
        return None
    results = resp.get("results", [])
    for page in results:
        if not page.get("archived"):
            return page
    return None


def main() -> int:
    if "--dry-run" in sys.argv:
        log.info("[BACKFILL] --dry-run: import OK, exiting.")
        return 0

    today = _today_sast_iso()
    log.info("[BACKFILL] Target date = %s (SAST)", today)

    if not os.environ.get("NOTION_TOKEN"):
        log.error("[BACKFILL] NOTION_TOKEN missing — reel_generator env hydrate failed. Abort.")
        return 2

    schema = _notion_request("GET", f"/databases/{MOQ_DB_ID}")
    if schema is None or schema.get("object") == "error":
        log.error("[BACKFILL] MOQ DB %s not accessible. Abort.", MOQ_DB_ID)
        return 2

    existing = _existing_ig_row_for_today(today)
    if existing is not None:
        log.info("[BACKFILL] Instagram row already exists for %s (id=%s) — nothing to do.",
                 today, existing.get("id"))
        return 0

    selection = _select_top_tier_pick(today)
    if selection is None:
        log.error("[BACKFILL] No pick available across tiers %s. Abort.", TIERS)
        return 3
    tier, row = selection

    edge_id = row["edge_id"]
    pid     = _pick_id(edge_id)
    home    = row.get("home_team") or None
    away    = row.get("away_team") or None
    if not home or not away:
        home, away = _parse_teams_from_match_key(row["match_key"])

    pick_team    = _resolve_pick_team(row["bet_type"], home, away)
    odds         = float(row["recommended_odds"])
    bookmaker    = row["bookmaker"]
    league_upper = row["league"].replace("_", " ").upper()
    match_date   = row["match_date"]

    # Community caption (build_up) — same formatter the IG row normally uses.
    from ai_copy_generator import generate_build_up as _fmt_build_up  # type: ignore[import]
    community_caption = _fmt_build_up(
        match=f"{home} vs {away}",
        league=league_upper,
        kickoff=match_date,
        broadcast="",
        edge_data={
            "outcome":   abbr(pick_team.upper()),
            "odds":      odds,
            "bookmaker": bookmaker,
        },
    )

    video_url = f"https://mzansiedge.co.za/assets/reel-cards/{today}/{pid}/master_{pid}.mp4"
    sched_iso = f"{today}T{_IG_REEL_SLOT}:00+02:00"
    tier_upper = tier.upper()

    moq_props = {
        "Title":  {"title": [{"text": {"content":
            f"🎬 Reel Still — {tier_upper} — Instagram — {today} [backfill]"}}]},
        "Status":          {"select": {"name": "Pending"}},
        "Channel":         {"select": {"name": "Instagram"}},
        "Asset Link":      {"url": video_url},
        "Final Copy":      {"rich_text": [{"text": {"content": community_caption}}]},
        "Lane":            {"select": {"name": "Content/Social"}},
        "Post Type":       {"select": {"name": "reel"}},
        "Scheduled Time":  {"date": {"start": sched_iso}},
    }
    body = {"parent": {"database_id": MOQ_DB_ID}, "properties": moq_props}

    resp = _notion_request("POST", "/pages", body)
    if not resp or not resp.get("id"):
        log.error("[BACKFILL] MOQ page create failed: %s", resp)
        return 4

    log.info("[BACKFILL] Created Instagram Reel row id=%s url=%s",
             resp["id"], resp.get("url", ""))
    log.info("[BACKFILL] tier=%s pick=%s @ %.2f on %s", tier_upper,
             pick_team, odds, bookmaker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
