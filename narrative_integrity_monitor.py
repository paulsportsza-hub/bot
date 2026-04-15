"""Narrative Integrity Monitor — data freshness checks for coaches.json.

INV-COACHES-JSON-AUDIT-01: Automated freshness mechanism.
Checks last_verified timestamps in scrapers/coaches.json against a max-age
threshold and fires a P1 alert when any entry exceeds it.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from config import COACHES_PATH

log = logging.getLogger(__name__)

# --- Configuration -----------------------------------------------------------

MAX_AGE_DAYS = 7  # P1 alert if any entry older than this
BOT_COACHES_PATH = Path(__file__).resolve().parent / "data" / "coaches.json"


# --- Public API --------------------------------------------------------------

def freshness_check(
    max_age_days: int = MAX_AGE_DAYS,
    reference_date: date | None = None,
) -> dict:
    """Check coaches.json freshness against max-age threshold.

    Returns a dict:
        ok:       bool — True if ALL entries are within max_age_days
        stale:    list[dict] — entries exceeding threshold
        missing:  list[str] — entries with no last_verified field
        checked:  int — total entries checked
        threshold_days: int — the max-age used
    """
    today = reference_date or date.today()
    threshold = today - timedelta(days=max_age_days)

    stale: list[dict] = []
    missing: list[str] = []
    checked = 0

    # --- scrapers/coaches.json (structured, has last_verified) ---------------
    try:
        with open(COACHES_PATH, "r") as f:
            structured = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.error("Cannot read %s: %s", COACHES_PATH, exc)
        return {
            "ok": False,
            "stale": [],
            "missing": [],
            "checked": 0,
            "threshold_days": max_age_days,
            "error": str(exc),
        }

    for sport, teams in structured.items():
        if not isinstance(teams, dict):
            continue
        for team, info in teams.items():
            if not isinstance(info, dict):
                continue
            checked += 1
            lv = info.get("last_verified")
            if not lv:
                missing.append(f"{sport}/{team}")
                continue
            try:
                verified_date = date.fromisoformat(lv)
            except ValueError:
                missing.append(f"{sport}/{team}")
                continue
            if verified_date < threshold:
                stale.append({
                    "sport": sport,
                    "team": team,
                    "name": info.get("name", "?"),
                    "last_verified": lv,
                    "age_days": (today - verified_date).days,
                })

    ok = len(stale) == 0 and len(missing) == 0

    if not ok:
        log.warning(
            "FRESHNESS_CHECK FAILED: %d stale, %d missing out of %d entries "
            "(threshold=%d days)",
            len(stale), len(missing), checked, max_age_days,
        )
        for entry in stale:
            log.warning(
                "  STALE: %s/%s — %s — last verified %s (%d days ago)",
                entry["sport"], entry["team"], entry["name"],
                entry["last_verified"], entry["age_days"],
            )
    else:
        log.info(
            "FRESHNESS_CHECK OK: %d entries, all within %d-day threshold",
            checked, max_age_days,
        )

    return {
        "ok": ok,
        "stale": stale,
        "missing": missing,
        "checked": checked,
        "threshold_days": max_age_days,
    }


def bot_coaches_sync_check() -> dict:
    """Check that bot/data/coaches.json entries are consistent with scrapers version.

    Returns:
        ok:          bool
        mismatches:  list[dict] — entries where bot and scrapers disagree
    """
    mismatches: list[dict] = []

    try:
        with open(BOT_COACHES_PATH, "r") as f:
            bot_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {"ok": False, "mismatches": [], "error": f"bot coaches: {exc}"}

    try:
        with open(COACHES_PATH, "r") as f:
            scrapers_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {"ok": False, "mismatches": [], "error": f"scrapers coaches: {exc}"}

    # Build flat lookup from scrapers structured format
    scrapers_flat: dict[str, str] = {}
    for _sport, teams in scrapers_data.items():
        if not isinstance(teams, dict):
            continue
        for team, info in teams.items():
            if isinstance(info, dict):
                key = team.lower().replace(" ", "_")
                scrapers_flat[key] = info.get("name", "")

    for team_key, names in bot_data.items():
        if not isinstance(names, list) or not names:
            continue
        bot_name = names[0]
        scrapers_name = scrapers_flat.get(team_key, "")
        if scrapers_name and bot_name != scrapers_name:
            mismatches.append({
                "team_key": team_key,
                "bot_name": bot_name,
                "scrapers_name": scrapers_name,
            })

    return {
        "ok": len(mismatches) == 0,
        "mismatches": mismatches,
    }
