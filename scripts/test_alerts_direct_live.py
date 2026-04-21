"""Live smoke test for alerts_direct.post_to_alerts.

Calls the real pipeline with the Arsenal vs Fulham gold edge and prints the
Telegram URL. Does NOT mark posted_to_alerts_direct=1 — safe to re-run.
"""
import asyncio
import os
import sys

# Make bot dir importable
sys.path.insert(0, "/home/paulsportsza/bot")

from dotenv import load_dotenv
load_dotenv("/home/paulsportsza/bot/.env")

# Pre-import PTB telegram before _ensure_paths() runs, so publisher's
# channels/telegram.py (which has no InlineKeyboardButton) doesn't shadow it.
import telegram  # noqa: F401 — must be imported before _ensure_paths adds publisher paths

from bot_lib.alerts_direct import post_to_alerts


TIP = {
    "match_id":          "arsenal_vs_fulham_2026-05-02",
    "match_key":         "arsenal_vs_fulham_2026-05-02",
    "edge_id":           "edge_arsenal_vs_fulham_2026-05-02_Home Win_TEST",
    "home_team":         "arsenal",
    "away_team":         "fulham",
    "outcome":           "Home Win",
    "outcome_key":       "home",
    "odds":              1.44,
    "recommended_odds":  1.44,
    "bookmaker":         "supabets",
    "ev":                2.9,
    "predicted_ev":      2.9,
    "league":            "English Premier League",
    "league_key":        "epl",
    "edge_tier":         "gold",
    "display_tier":      "gold",
    "edge_rating":       "gold",
    "edge_score":        68.3,
    "confirming_signals": 3,
}


async def main() -> None:
    print("Calling post_to_alerts …")
    url = await post_to_alerts(TIP, TIP["edge_id"], tier_assigned_at=None)
    if url:
        print(f"\n✅ SUCCESS — posted to Alerts channel: {url}")
    else:
        print("\n❌ FAILED — post_to_alerts returned None")


if __name__ == "__main__":
    asyncio.run(main())
