#!/usr/bin/env python3
"""Create qa_profiles and qa_command_log tables in mzansiedge.db.

BUILD-QA-HARNESS-01: one-time migration. Safe to re-run (INSERT OR IGNORE).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_connection import get_connection

BOT_DB = str(Path(__file__).resolve().parent.parent / "data" / "mzansiedge.db")

_CREATE_QA_PROFILES = """
CREATE TABLE IF NOT EXISTS qa_profiles (
    profile_id        TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    subscribed_leagues TEXT NOT NULL DEFAULT '[]',
    edge_tiers_seen   TEXT NOT NULL DEFAULT '[]',
    my_matches        TEXT,
    persona_notes     TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    last_baselined_at TEXT,
    active            INT NOT NULL DEFAULT 1
)
"""

_CREATE_QA_COMMAND_LOG = """
CREATE TABLE IF NOT EXISTS qa_command_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  TEXT NOT NULL,
    command     TEXT NOT NULL,
    invoked_by  INTEGER NOT NULL,
    invoked_at  TEXT NOT NULL DEFAULT (datetime('now')),
    result_path TEXT,
    duration_ms INTEGER
)
"""

_SEED = [
    {
        "profile_id": "P01",
        "display_name": "EPL Diamond — Experienced Aggressive",
        "subscribed_leagues": ["epl"],
        "edge_tiers_seen": ["diamond", "gold", "silver", "bronze"],
        "my_matches": ["Arsenal", "Liverpool"],
        "persona_notes": "EPL-only, experienced aggressive, Diamond tier, R1000 bankroll, 07:00 notify",
    },
    {
        "profile_id": "P02",
        "display_name": "PSL Gold — Casual Moderate",
        "subscribed_leagues": ["psl"],
        "edge_tiers_seen": ["gold", "silver", "bronze"],
        "my_matches": ["Kaizer Chiefs", "Orlando Pirates"],
        "persona_notes": "PSL-only, casual moderate, Gold tier, R500 bankroll, 12:00 notify",
    },
    {
        "profile_id": "P03",
        "display_name": "URC Gold — Casual Moderate",
        "subscribed_leagues": ["urc"],
        "edge_tiers_seen": ["gold", "silver", "bronze"],
        "my_matches": ["Bulls", "Stormers"],
        "persona_notes": "URC rugby only, casual moderate, Gold tier, R500 bankroll, 18:00 notify",
    },
    {
        "profile_id": "P04",
        "display_name": "IPL Diamond — Experienced Aggressive",
        "subscribed_leagues": ["ipl"],
        "edge_tiers_seen": ["diamond", "gold", "silver", "bronze"],
        "my_matches": ["Mumbai Indians", "Chennai Super Kings"],
        "persona_notes": "IPL cricket only, experienced aggressive, Diamond tier, R2000 bankroll, 07:00 notify",
    },
    {
        "profile_id": "P05",
        "display_name": "T20 WC Bronze — Newbie Conservative",
        "subscribed_leagues": ["t20_world_cup"],
        "edge_tiers_seen": ["bronze"],
        "my_matches": ["South Africa", "India"],
        "persona_notes": "T20 World Cup only, newbie conservative, Bronze tier, R200 bankroll, 18:00 notify",
    },
    {
        "profile_id": "P06",
        "display_name": "Six Nations Gold — Experienced Moderate",
        "subscribed_leagues": ["six_nations"],
        "edge_tiers_seen": ["gold", "silver", "bronze"],
        "my_matches": ["England", "France"],
        "persona_notes": "Six Nations rugby only, experienced moderate, Gold tier, R1000 bankroll, 18:00 notify",
    },
    {
        "profile_id": "P07",
        "display_name": "Boxing Bronze — Casual Moderate",
        "subscribed_leagues": ["boxing"],
        "edge_tiers_seen": ["bronze"],
        "my_matches": None,
        "persona_notes": "Boxing only, casual moderate, Bronze tier, R500 bankroll, 21:00 notify. my_matches NULL — fighter names TBD per brief",
    },
    {
        "profile_id": "P08",
        "display_name": "UFC Diamond — Experienced Aggressive",
        "subscribed_leagues": ["mma"],
        "edge_tiers_seen": ["diamond", "gold", "silver", "bronze"],
        "my_matches": None,
        "persona_notes": "UFC/MMA only, experienced aggressive, Diamond tier, R2000 bankroll, 21:00 notify. my_matches NULL — fighter names TBD per brief",
    },
    {
        "profile_id": "P09",
        "display_name": "Soccer Mixed Gold — Experienced Moderate",
        "subscribed_leagues": ["epl", "psl", "champions_league"],
        "edge_tiers_seen": ["gold", "silver", "bronze"],
        "my_matches": ["Arsenal", "Kaizer Chiefs", "Barcelona"],
        "persona_notes": "Soccer mixed (EPL+PSL+CL), experienced moderate, Gold tier, R1000 bankroll, 07:00 notify",
    },
    {
        "profile_id": "P10",
        "display_name": "Multi-Sport Gold — Casual Moderate",
        "subscribed_leagues": ["psl", "urc", "t20_world_cup"],
        "edge_tiers_seen": ["gold", "silver", "bronze"],
        "my_matches": ["Kaizer Chiefs", "Bulls", "South Africa"],
        "persona_notes": "Multi-sport (Soccer+Rugby+Cricket), casual moderate, Gold tier, R500 bankroll, 12:00 notify",
    },
    {
        "profile_id": "P11",
        "display_name": "All Sports Diamond — Experienced Aggressive",
        "subscribed_leagues": ["epl", "psl", "urc", "ipl", "boxing", "mma"],
        "edge_tiers_seen": ["diamond", "gold", "silver", "bronze"],
        "my_matches": ["Arsenal", "Kaizer Chiefs", "Bulls", "South Africa", "Mumbai Indians"],
        "persona_notes": "All sports (Soccer+Rugby+Cricket+Combat), experienced aggressive, Diamond tier, R5000 bankroll, 07:00 notify",
    },
    {
        "profile_id": "P12",
        "display_name": "Zero Teams Bronze — Newbie Conservative",
        "subscribed_leagues": [],
        "edge_tiers_seen": ["bronze"],
        "my_matches": [],
        "persona_notes": "Zero favourites edge case (onboarding skipped favourites), newbie conservative, Bronze tier, R200 bankroll, 18:00 notify",
    },
]


def run() -> None:
    conn = get_connection(BOT_DB)
    with conn:
        conn.execute(_CREATE_QA_PROFILES)
        conn.execute(_CREATE_QA_COMMAND_LOG)
        created_at = "2026-04-17T00:00:00"
        for p in _SEED:
            conn.execute(
                """INSERT OR IGNORE INTO qa_profiles
                   (profile_id, display_name, subscribed_leagues, edge_tiers_seen,
                    my_matches, persona_notes, created_at, last_baselined_at, active)
                   VALUES (?,?,?,?,?,?,?,NULL,1)""",
                (
                    p["profile_id"],
                    p["display_name"],
                    json.dumps(p["subscribed_leagues"]),
                    json.dumps(p["edge_tiers_seen"]),
                    json.dumps(p["my_matches"]) if p["my_matches"] is not None else None,
                    p["persona_notes"],
                    created_at,
                ),
            )
    count = conn.execute("SELECT COUNT(*) FROM qa_profiles").fetchone()[0]
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='qa_profiles'"
    ).fetchone()[0]
    log_schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='qa_command_log'"
    ).fetchone()[0]
    conn.close()
    print(f"[OK] qa_profiles: {count} rows")
    print(f"Schema: {schema}")
    print(f"Log schema: {log_schema}")
    # Flag TBD fields
    print("\nNOTE: P07 and P08 my_matches = NULL (fighter names TBD per brief)")


if __name__ == "__main__":
    run()
