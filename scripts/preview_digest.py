#!/usr/bin/env python3
"""IMG-W1R3 — Generate edge_digest card preview from real DB data and send to Telegram."""
from __future__ import annotations
import json
import sqlite3
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

SCRAPERS_DB = Path("/home/paulsportsza/scrapers/odds.db")
ENV_FILE = BOT_DIR / ".env"


def _read_env(key: str) -> str:
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _parse_teams(match_key: str) -> tuple[str, str]:
    """Parse 'home_vs_away_YYYY-MM-DD' into display names."""
    body = match_key.rsplit("_", 1)[0]  # strip date suffix
    home_raw, _, away_raw = body.partition("_vs_")
    def _fmt(s: str) -> str:
        return " ".join(w.capitalize() for w in s.split("_"))
    return _fmt(home_raw), _fmt(away_raw)


def _get_broadcast(conn: sqlite3.Connection, home: str, away: str) -> tuple[str, str]:
    """Try to get kickoff + broadcast from broadcast_schedule.

    INV-FIX-KICKOFF-SOURCE-AUDIT-02: supersport_scraper-only; DStv EPG
    re-airs share team names but broadcast at a ±1h offset from the true
    kickoff.
    """
    try:
        row = conn.execute(
            """SELECT start_time, channel_short, dstv_number
               FROM broadcast_schedule
               WHERE source = 'supersport_scraper'
                 AND (home_team LIKE ? OR away_team LIKE ?)
               ORDER BY start_time LIMIT 1""",
            (f"%{home.split()[0]}%", f"%{away.split()[0]}%"),
        ).fetchone()
        if row:
            channel = row["channel_short"] or ""
            dstv = row["dstv_number"] or ""
            broadcast = f"{channel} (DStv {dstv})" if dstv else channel
            # Parse kickoff time
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(row["start_time"])
                today = date.today()
                tomorrow = today + timedelta(days=1)
                if dt.date() == today:
                    kickoff = f"Today {dt.strftime('%H:%M')}"
                elif dt.date() == tomorrow:
                    kickoff = f"Tomorrow {dt.strftime('%H:%M')}"
                else:
                    kickoff = dt.strftime("%a %-d %b · %H:%M")
            except Exception:
                kickoff = ""
            return kickoff, broadcast
    except Exception:
        pass
    return "", ""


def build_tips_from_db(limit: int = 8) -> list[dict]:
    if not SCRAPERS_DB.exists():
        print(f"ERROR: DB not found: {SCRAPERS_DB}")
        return []

    conn = sqlite3.connect(str(SCRAPERS_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT DISTINCT match_key, sport, league, edge_tier,
                  composite_score, bet_type, recommended_odds, bookmaker,
                  predicted_ev, match_date
           FROM edge_results
           WHERE result IS NULL
           ORDER BY composite_score DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    tips = []
    for r in rows:
        home, away = _parse_teams(r["match_key"])
        bet_type = r["bet_type"] or ""
        if "home" in bet_type.lower():
            pick_team = home
        elif "away" in bet_type.lower():
            pick_team = away
        else:
            pick_team = "Draw"

        # Match date as kickoff fallback
        match_date = r["match_date"] or ""
        kickoff_fallback = ""
        if match_date:
            try:
                md = date.fromisoformat(match_date)
                today = date.today()
                tomorrow = today + timedelta(days=1)
                if md == today:
                    kickoff_fallback = "Today"
                elif md == tomorrow:
                    kickoff_fallback = "Tomorrow"
                else:
                    kickoff_fallback = md.strftime("%a %-d %b")
            except Exception:
                kickoff_fallback = match_date

        # Try broadcast lookup
        kickoff, broadcast = _get_broadcast(conn, home, away)
        if not kickoff:
            kickoff = kickoff_fallback

        tips.append({
            "home_team": home,
            "away_team": away,
            "match_key": r["match_key"],
            "sport": r["sport"],
            "sport_key": r["sport"],
            "league": r["league"],
            "display_tier": r["edge_tier"],
            "edge_rating": r["edge_tier"],
            "tier": r["edge_tier"],
            "composite_score": float(r["composite_score"] or 0),
            "odds": float(r["recommended_odds"] or 0),
            "ev": float(r["predicted_ev"] or 0),
            "ev_pct": float(r["predicted_ev"] or 0),
            "bookmaker": r["bookmaker"] or "",
            "pick_team": pick_team,
            "outcome": bet_type,
            "kickoff": kickoff,
            "_bc_broadcast": f"📺 {broadcast}" if broadcast else "",
        })

    conn.close()
    return tips


def main() -> None:
    from card_generator import generate_card, compute_digest_stats

    print("=== IMG-W1R3 Preview Generator ===")

    # Build tips from DB
    tips = build_tips_from_db(limit=8)
    print(f"\nBuilt {len(tips)} tips from edge_results:")
    for i, t in enumerate(tips, 1):
        print(f"  [{i}] {t['home_team']} vs {t['away_team']} ({t['league']}) "
              f"{t['display_tier']} EV={t['ev']}% odds={t['odds']}")

    if not tips:
        print("ERROR: No active tips found in DB!")
        sys.exit(1)

    # Compute real stats and inject into first tip
    stats = compute_digest_stats()
    print(f"\nDigest stats: {stats}")
    if stats:
        tips[0]["stats_summary"] = stats

    # Generate card
    print("\nGenerating card...")
    img_bytes = generate_card("edge_digest", tips)
    out_path = Path("/tmp/edge_digest_w1r3_preview.png")
    out_path.write_bytes(img_bytes)
    print(f"Card saved: {out_path} ({len(img_bytes):,} bytes)")

    # Verify dimensions
    from PIL import Image
    from io import BytesIO
    img = Image.open(BytesIO(img_bytes))
    print(f"Dimensions: {img.size[0]}x{img.size[1]}px")
    assert img.size[0] == 720, f"Expected 720px wide, got {img.size[0]}"
    assert img.size[1] >= 1280, f"Expected >= 1280px tall, got {img.size[1]}"

    # Send to Telegram
    bot_token = _read_env("BOT_TOKEN")
    admin_ids = _read_env("ADMIN_IDS")
    chat_id = admin_ids.split(",")[0].strip() if admin_ids else ""

    if not bot_token or not chat_id:
        print("\nWARNING: BOT_TOKEN or ADMIN_IDS not found in .env — skipping Telegram send")
        print(f"Preview saved to: {out_path}")
        return

    print(f"\nSending to Telegram chat {chat_id}...")
    caption = "IMG-W1R3 Preview: Edge Digest V3 — Visual Overhaul"
    boundary = "imgw1r3boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="edge_digest.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                msg_id = result.get("result", {}).get("message_id", "?")
                print(f"Sent! message_id={msg_id}")
            else:
                print(f"Telegram error: {result}")
    except Exception as e:
        print(f"Telegram send error: {e}")
        print(f"Preview still saved to: {out_path}")


if __name__ == "__main__":
    main()
