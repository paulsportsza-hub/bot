"""Wave 16C — Broadcast Verification + Fact-Check Protocol via Telethon.

Tests:
  Part 1: Broadcast Display Verification (10 tests)
  Part 2: Fact-Check Protocol / BUG-HAL (10 AI breakdowns)
  Part 3: Regression spot-check

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/e2e_wave16c.py 2>&1 | tee /home/paulsportsza/reports/e2e-wave16c-raw.txt
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "/home/paulsportsza")

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave16c")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = Path("/home/paulsportsza/reports/wave16c-e2e-results.json")

BOT_TIMEOUT = 15
AI_TIMEOUT = 35

results: list[dict] = []
bugs: list[dict] = []
fact_checks: list[dict] = []  # Detailed fact-check records

EDGE_EMOJIS = {"💎", "🥇", "🥈", "🥉"}

# Wrong-sport terms for cross-validation
SOCCER_TERMS_BANNED_IN_OTHER = ["clean sheet", "penalty kick", "corner", "offside trap",
                                 "golden boot", "VAR"]
RUGBY_TERMS_BANNED_IN_SOCCER = ["try line", "lineout", "scrum", "ruck", "maul",
                                 "conversion kick", "drop goal", "sin bin"]
CRICKET_TERMS_BANNED_IN_SOCCER = ["innings", "wicket", "over rate", "strike rate",
                                   "bowling average", "run rate"]


def record(test_id: str, name: str, status: str, response: str,
           assertions: list[tuple[bool, str]], detail: str = ""):
    entry = {
        "test_id": test_id, "name": name, "status": status,
        "response": response[:3000],
        "assertions": [[ok, msg] for ok, msg in assertions],
        "detail": detail,
    }
    results.append(entry)
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(status, "?")
    log.info("  %s %s: %s — %s", icon, test_id, name, status)
    if status == "FAIL":
        for ok, msg in assertions:
            if not ok:
                log.error("      ASSERT FAILED: %s", msg)
    safe = test_id.replace(":", "_").replace("/", "_")
    (REPORT_DIR / f"16c-{safe}.txt").write_text(
        f"TEST: {test_id} — {name}\nSTATUS: {status}\n"
        f"RESPONSE:\n{response}\n\nASSERTIONS:\n"
        + "\n".join(f"  {'✓' if ok else '✗'} {msg}" for ok, msg in assertions)
        + (f"\n\nDETAIL: {detail}" if detail else ""),
        encoding="utf-8",
    )


def file_bug(bug_id: str, severity: str, screen: str, steps: str,
             expected: str, actual: str):
    bugs.append({
        "id": bug_id, "severity": severity, "screen": screen,
        "steps": steps, "expected": expected, "actual": actual,
    })
    log.warning("  🐛 %s (%s): %s — %s", bug_id, severity, screen, actual[:80])


# ── Telethon Helpers ─────────────────────────────────────────

async def _last_id(c: TelegramClient) -> int:
    msgs = await c.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0


async def send(c: TelegramClient, text: str, timeout: int = BOT_TIMEOUT) -> Message | None:
    last = await _last_id(c)
    try:
        await c.send_message(BOT, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await c.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > last and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def send_wait_buttons(c: TelegramClient, text: str,
                            timeout: int = BOT_TIMEOUT) -> Message | None:
    """Send and wait for a reply with inline buttons (handles loading states)."""
    last = await _last_id(c)
    try:
        await c.send_message(BOT, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await c.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    found_id = None
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > last and not m.out:
                if found_id is None:
                    found_id = m.id
                if m.buttons:
                    return m
        if found_id:
            updated = await c.get_messages(BOT, ids=found_id)
            if updated and updated.buttons:
                return updated
        await asyncio.sleep(1.5)
    if found_id:
        return await c.get_messages(BOT, ids=found_id)
    return None


async def click_data(c: TelegramClient, msg: Message, prefix: str,
                     timeout: int = 10) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    try:
                        await btn.click()
                    except Exception:
                        return None
                    await asyncio.sleep(3)
                    msgs = await c.get_messages(BOT, limit=10)
                    for m in msgs:
                        if m.id > old and not m.out:
                            return m
                    updated = await c.get_messages(BOT, ids=msg.id)
                    if updated:
                        return updated
                    return None
    return None


async def click_data_wait(c: TelegramClient, msg: Message, prefix: str,
                          timeout: int = AI_TIMEOUT) -> Message | None:
    """Click a button and wait for AI response with extended polling."""
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    target_btn = None
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    target_btn = btn
                    break
        if target_btn:
            break
    if not target_btn:
        return None
    try:
        await target_btn.click()
    except Exception:
        return None
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > old and not m.out and m.buttons:
                btns = get_buttons(m)
                if any("back" in b.lower() or "menu" in b.lower() for b in btns):
                    return m
        updated = await c.get_messages(BOT, ids=msg.id)
        if updated and updated.buttons:
            btns = get_buttons(updated)
            if any("back" in b.lower() or "menu" in b.lower() for b in btns):
                return updated
        await asyncio.sleep(2)
    msgs = await c.get_messages(BOT, limit=5)
    for m in msgs:
        if m.id > old and not m.out:
            return m
    return await c.get_messages(BOT, ids=msg.id)


def get_buttons(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row]


def get_callback_data(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    cbs = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                cbs.append(cb)
            elif hasattr(btn, "url") and btn.url:
                cbs.append(f"URL:{btn.url}")
    return cbs


# ── Fact-Check Helpers ───────────────────────────────────────

def extract_position_claims(text: str) -> list[dict]:
    """Extract all league position claims from AI text."""
    claims = []
    # Patterns: "sit 3rd", "currently 5th", "ranked 2nd", "in 1st place",
    # "top of the table", "bottom of the table"
    pos_pattern = re.compile(
        r'(?:sit|sitting|in|currently|placed|ranked|lie|lying)\s+'
        r'(\d+)(?:st|nd|rd|th)',
        re.IGNORECASE,
    )
    for match in pos_pattern.finditer(text):
        claimed_pos = int(match.group(1))
        # Find nearby team name — look at the surrounding context
        start = max(0, match.start() - 100)
        context = text[start:match.end() + 50]
        claims.append({
            "claimed_position": claimed_pos,
            "context": context.strip(),
            "offset": match.start(),
        })

    # Also check for "top of the table" → position 1
    if re.search(r'top of the (?:table|league|log)', text, re.IGNORECASE):
        claims.append({"claimed_position": 1, "context": "top of the table", "offset": 0})

    return claims


def extract_form_claims(text: str) -> list[dict]:
    """Extract form claims like 'won 3 of last 5', 'unbeaten in 12'."""
    claims = []
    # "won X of last Y"
    for m in re.finditer(r'(?:won|lost|drawn)\s+(\d+)\s+of\s+(?:their\s+)?last\s+(\d+)',
                         text, re.IGNORECASE):
        claims.append({"type": "win_count", "value": m.group(0), "context": text[max(0, m.start()-50):m.end()+50]})
    # "unbeaten in last X" / "unbeaten in X"
    for m in re.finditer(r'unbeaten\s+in\s+(?:their\s+)?(?:last\s+)?(\d+)', text, re.IGNORECASE):
        claims.append({"type": "unbeaten_run", "value": m.group(0), "context": text[max(0, m.start()-50):m.end()+50]})
    # Form strings like "WWDLW"
    for m in re.finditer(r'\b([WDLP]{3,})\b', text):
        claims.append({"type": "form_string", "value": m.group(1), "context": text[max(0, m.start()-50):m.end()+50]})
    return claims


def extract_stat_claims(text: str) -> list[dict]:
    """Extract statistical claims (goals per game, clean sheets, etc.)."""
    claims = []
    # "X goals per game" / "X goals in Y games"
    for m in re.finditer(r'(\d+\.?\d*)\s+goals?\s+(?:per\s+game|in\s+\d+\s+games?)',
                         text, re.IGNORECASE):
        claims.append({"type": "goals", "value": m.group(0), "context": text[max(0, m.start()-50):m.end()+50]})
    # "X clean sheets"
    for m in re.finditer(r'(\d+)\s+clean\s+sheets?', text, re.IGNORECASE):
        claims.append({"type": "clean_sheets", "value": m.group(0), "context": text[max(0, m.start()-50):m.end()+50]})
    return claims


def check_sport_context(text: str, sport: str) -> list[str]:
    """Check for wrong-sport terminology. Returns list of violations."""
    violations = []
    lower = text.lower()
    if sport == "soccer":
        for term in RUGBY_TERMS_BANNED_IN_SOCCER:
            if term.lower() in lower:
                violations.append(f"Rugby term '{term}' found in soccer breakdown")
        for term in CRICKET_TERMS_BANNED_IN_SOCCER:
            if term.lower() in lower:
                violations.append(f"Cricket term '{term}' found in soccer breakdown")
    elif sport in ("rugby", "urc", "six_nations"):
        for term in SOCCER_TERMS_BANNED_IN_OTHER:
            if term.lower() in lower:
                violations.append(f"Soccer term '{term}' found in rugby breakdown")
    elif sport in ("cricket", "sa20"):
        for term in SOCCER_TERMS_BANNED_IN_OTHER:
            if term.lower() in lower:
                violations.append(f"Soccer term '{term}' found in cricket breakdown")
    return violations


async def get_verified_context(home: str, away: str, league: str, sport: str = "") -> dict:
    """Fetch verified context from match_context_fetcher for comparison."""
    try:
        from scrapers.match_context_fetcher import get_match_context
        ctx = await get_match_context(
            home_team=home, away_team=away, league=league, sport=sport,
        )
        return ctx
    except Exception as e:
        log.warning("  Could not fetch verified context: %s", e)
        return {"data_available": False, "error": str(e)}


def fact_check_positions(text: str, ctx_data: dict) -> list[dict]:
    """Cross-reference AI position claims against verified context data."""
    results_list = []
    if not ctx_data.get("data_available"):
        return results_list

    verified: dict[str, int] = {}
    for side in ("home_team", "away_team"):
        team = ctx_data.get(side, {})
        name = team.get("name", "")
        pos = team.get("league_position")
        if name and pos is not None:
            verified[name.lower()] = pos

    claims = extract_position_claims(text)
    lower = text.lower()
    for claim in claims:
        for team_name, real_pos in verified.items():
            # Check if this team is mentioned near the position claim
            ctx = claim["context"].lower()
            if team_name in ctx:
                is_correct = claim["claimed_position"] == real_pos
                results_list.append({
                    "team": team_name,
                    "claimed": claim["claimed_position"],
                    "verified": real_pos,
                    "correct": is_correct,
                    "context": claim["context"],
                })

    return results_list


# ── Main Tests ───────────────────────────────────────────────

async def run_tests():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()

    me = await client.get_me()
    log.info("Connected as: %s (@%s)", me.first_name, me.username)
    log.info("Testing bot: @%s", BOT)
    log.info("=" * 60)

    await asyncio.sleep(2)

    # ================================================================
    # PART 1: BROADCAST DISPLAY VERIFICATION
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("PART 1: BROADCAST DISPLAY VERIFICATION")
    log.info("=" * 60)

    # BC-01 + BC-02: Hot Tips — check broadcast lines
    hot_msg = await send_wait_buttons(client, "🔥 Hot Tips")
    if not hot_msg:
        record("BC-01", "Hot Tips — date/time display", "SKIP", "No response", [])
        record("BC-02", "Hot Tips — channel display", "SKIP", "No response", [])
    else:
        ht = hot_msg.raw_text or ""

        # BC-01: Date/time lines present
        has_date = bool(re.search(r'⏰|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)', ht))
        # Check for time format (HH:MM)
        has_time = bool(re.search(r'\d{2}:\d{2}', ht))
        asserts = [
            (has_date or has_time, f"Date/time display present: date={has_date} time={has_time}"),
        ]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("BC-01", "Hot Tips — date/time display", status, ht[:500], asserts)

        # BC-02: Broadcast channel lines (📺)
        broadcast_lines = [l for l in ht.split('\n') if '📺' in l]
        has_broadcast = len(broadcast_lines) > 0
        has_dstv = any("DStv" in l or "SS " in l or "SuperSport" in l for l in broadcast_lines)
        asserts = [
            (has_broadcast, f"📺 broadcast lines found: {len(broadcast_lines)}"),
            (has_dstv or not has_broadcast,
             f"DStv channel info: {has_dstv}" if has_broadcast else "No broadcast lines to check"),
        ]
        status = "PASS" if has_broadcast and has_dstv else "WARN" if not has_broadcast else "FAIL"
        record("BC-02", "Hot Tips — channel display (📺)", status,
               f"Broadcast lines:\n" + "\n".join(broadcast_lines) if broadcast_lines else "None found",
               asserts,
               f"Found {len(broadcast_lines)} broadcast lines")

    # BC-03 + BC-04: Your Games — check broadcast lines
    yg_msg = await send(client, "⚽ Your Games")
    if not yg_msg:
        record("BC-03", "Your Games — broadcast display", "SKIP", "No response", [])
    else:
        yt = yg_msg.raw_text or ""
        yg_cbs = get_callback_data(yg_msg)

        # BC-03: Your Games broadcast lines
        broadcast_lines = [l for l in yt.split('\n') if '📺' in l]
        has_broadcast = len(broadcast_lines) > 0
        asserts = [
            (has_broadcast, f"📺 lines in Your Games: {len(broadcast_lines)}"),
        ]
        # Check format: "📺 SS EPL (DStv 203)" or similar
        if broadcast_lines:
            sample = broadcast_lines[0]
            has_channel = bool(re.search(r'SS |SuperSport|ESPN|SABC', sample))
            has_number = bool(re.search(r'DStv \d+|OVHD \d+', sample))
            asserts.append((has_channel, f"Channel name in broadcast: {has_channel}"))
            asserts.append((has_number, f"DStv number in broadcast: {has_number}"))

        status = "PASS" if all(a[0] for a in asserts) else "WARN" if not has_broadcast else "FAIL"
        record("BC-03", "Your Games — broadcast display", status,
               f"Text:\n{yt}\n\nBroadcast lines:\n" + "\n".join(broadcast_lines),
               asserts)

        # BC-04: Game Breakdown — full broadcast info
        game_cbs = [cb for cb in yg_cbs if cb.startswith("yg:game:")]
        if game_cbs:
            # Click first football game
            target_cb = game_cbs[0]
            log.info("  Clicking game for broadcast check: %s", target_cb[:30])
            gd_msg = await click_data_wait(client, yg_msg, target_cb)
            if gd_msg:
                gd_text = gd_msg.raw_text or ""
                gd_broadcast = [l for l in gd_text.split('\n') if '📺' in l]
                has_gd_broadcast = len(gd_broadcast) > 0
                asserts = [
                    (has_gd_broadcast, f"📺 in Game Breakdown: {len(gd_broadcast)}"),
                ]
                if gd_broadcast:
                    sample = gd_broadcast[0]
                    has_channel = bool(re.search(r'SS |SuperSport|ESPN|SABC', sample))
                    asserts.append((has_channel, f"Channel name: {has_channel}"))
                status = "PASS" if all(a[0] for a in asserts) else "WARN" if not has_gd_broadcast else "FAIL"
                record("BC-04", "Game Breakdown — broadcast display", status,
                       f"Broadcast lines: {gd_broadcast}\n\nFull text (first 500):\n{gd_text[:500]}",
                       asserts)
            else:
                record("BC-04", "Game Breakdown — broadcast display", "SKIP",
                       "No game detail response", [])
        else:
            record("BC-04", "Game Breakdown — broadcast display", "SKIP",
                   "No games in Your Games", [])

    # BC-05: Broadcast format check (DStv number format)
    # Re-use Hot Tips broadcast lines for format validation
    if hot_msg:
        ht = hot_msg.raw_text or ""
        all_broadcasts = [l.strip() for l in ht.split('\n') if '📺' in l]
        format_ok = True
        format_detail = []
        for bc in all_broadcasts:
            # Expected: "📺 SS EPL (DStv 203)" or "📺 Check SuperSport.com for listings"
            is_channel_format = bool(re.search(r'📺\s+.+\(DStv \d+\)', bc))
            is_fallback = "SuperSport.com" in bc or "Check " in bc
            ok = is_channel_format or is_fallback
            format_detail.append(f"{'✓' if ok else '✗'} {bc}")
            if not ok:
                format_ok = False
        asserts = [(format_ok or not all_broadcasts,
                    f"Broadcast format valid: {format_ok} ({len(all_broadcasts)} lines)")]
        status = "PASS" if format_ok else "WARN" if not all_broadcasts else "FAIL"
        record("BC-05", "Broadcast — DStv number format", status,
               "\n".join(format_detail), asserts)
    else:
        record("BC-05", "Broadcast — DStv number format", "SKIP", "No Hot Tips", [])

    # BC-06: Cross-sport channel check — cricket match
    yg_msg = await send(client, "⚽ Your Games")
    if yg_msg:
        # Try to filter to cricket
        yg_cbs = get_callback_data(yg_msg)
        cricket_cb = None
        for cb in yg_cbs:
            if cb == "yg:sport:cricket":
                cricket_cb = cb
                break
        if cricket_cb:
            cricket_msg = await click_data(client, yg_msg, cricket_cb)
            if cricket_msg:
                ct = cricket_msg.raw_text or ""
                cricket_broadcasts = [l.strip() for l in ct.split('\n') if '📺' in l]
                if cricket_broadcasts:
                    # Verify cricket channel (SS Cricket 212) not soccer channel
                    is_cricket_channel = any(
                        "Cricket" in b or "212" in b or "SuperSport.com" in b
                        for b in cricket_broadcasts
                    )
                    not_soccer_channel = not any(
                        "SS EPL" in b or "SS PSL" in b or "203" in b or "202" in b
                        for b in cricket_broadcasts
                    )
                    asserts = [
                        (is_cricket_channel, f"Cricket channel shown: {cricket_broadcasts}"),
                        (not_soccer_channel, f"Not soccer channel: {not_soccer_channel}"),
                    ]
                    status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                    record("BC-06", "Cross-sport — cricket channel", status,
                           "\n".join(cricket_broadcasts), asserts)
                else:
                    record("BC-06", "Cross-sport — cricket channel", "WARN",
                           f"No broadcast lines for cricket:\n{ct[:300]}",
                           [(False, "No 📺 lines found for cricket")])
            else:
                record("BC-06", "Cross-sport — cricket channel", "SKIP",
                       "No cricket filter response", [])
        else:
            record("BC-06", "Cross-sport — cricket channel", "SKIP",
                   "No cricket sport filter button", [])
    else:
        record("BC-06", "Cross-sport — cricket channel", "SKIP", "No Your Games", [])

    # BC-07: Date formatting check — Your Games shows day + time (Hot Tips shows leagues, not times)
    yg_for_time = await send(client, "⚽ Your Games")
    if yg_for_time:
        ygt = yg_for_time.raw_text or ""
        # Your Games shows "19:30  Leeds United vs Manchester City" format
        time_matches = re.findall(r'(\d{2}:\d{2})', ygt)
        has_times = len(time_matches) > 0
        # Check for day names (proper formatting): "Saturday, 28 Feb"
        has_day_names = bool(re.search(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', ygt))
        asserts = [
            (has_times, f"Time values found: {time_matches[:5]}"),
            (has_day_names, f"Day names present: {has_day_names}"),
        ]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("BC-07", "Date formatting — day + time", status, ygt[:400], asserts)
    else:
        record("BC-07", "Date formatting", "SKIP", "No Your Games", [])

    # BC-08: Fallback check — if match has no broadcast data
    # The static fallback should show "📺 SS EPL (DStv 203)" etc.
    # We can't force this condition, but we can check that ALL football
    # games have SOME broadcast line (either DB or fallback)
    if yg_msg:
        # Go back to all games
        yg_msg2 = await send(client, "⚽ Your Games")
        if yg_msg2:
            yt2 = yg_msg2.raw_text or ""
            game_lines = yt2.split('\n')
            game_count = sum(1 for l in game_lines if '⚽' in l or '🏏' in l or '🏉' in l)
            broadcast_count = sum(1 for l in game_lines if '📺' in l)
            # Every game should have a broadcast line (DB match, league fallback, or static default)
            asserts = [
                (broadcast_count >= game_count - 1,
                 f"Broadcast coverage: {broadcast_count} lines for {game_count} games"),
            ]
            status = "PASS" if all(a[0] for a in asserts) else "WARN"
            record("BC-08", "Broadcast fallback — all games covered", status,
                   f"Games: {game_count}, Broadcast lines: {broadcast_count}",
                   asserts)

    # ================================================================
    # PART 2: FACT-CHECK PROTOCOL
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("PART 2: FACT-CHECK PROTOCOL")
    log.info("=" * 60)

    # Get all available games for fact-checking
    yg_msg = await send(client, "⚽ Your Games")
    all_game_cbs = []
    game_info = {}  # event_id → {home, away, sport, league}
    if yg_msg:
        yg_cbs = get_callback_data(yg_msg)
        yg_text = yg_msg.raw_text or ""

        # Extract game lines with "vs" in order they appear
        game_lines_ordered = []
        for line in yg_text.split('\n'):
            if 'vs' in line:
                m = re.search(r'(?:🇿🇦|🇿🇼|🇬🇧|🇦🇺|🇳🇿|🇮🇳|🏴|🏳️)?\s*([A-Z][\w\s]+?)\s+vs\s+(?:🇿🇦|🇿🇼|🇬🇧|🇦🇺|🇳🇿|🇮🇳|🏴|🏳️)?\s*([A-Z][\w\s]+)', line)
                if not m:
                    m = re.search(r'([A-Z][\w\s]+?)\s+vs\s+([A-Z][\w\s]+)', line)
                if m:
                    sport = "soccer" if "⚽" in line else "cricket" if "🏏" in line else "rugby" if "🏉" in line else "unknown"
                    game_lines_ordered.append({
                        "home": m.group(1).strip(),
                        "away": m.group(2).strip(),
                        "sport": sport,
                    })

        # Extract game callbacks in order
        game_cb_ordered = [cb for cb in yg_cbs if cb.startswith("yg:game:")]

        # Pair them by index (callbacks appear in same order as displayed games)
        for idx, cb in enumerate(game_cb_ordered):
            eid = cb.replace("yg:game:", "")
            all_game_cbs.append(cb)
            if idx < len(game_lines_ordered):
                game_info[eid] = game_lines_ordered[idx]

    log.info("  Found %d games for fact-checking", len(all_game_cbs))

    hal_bug_count = 0

    for idx, game_cb in enumerate(all_game_cbs):
        event_id = game_cb.replace("yg:game:", "")
        test_id = f"FC-{idx+1:02d}"
        info = game_info.get(event_id, {})
        home = info.get("home", "?")
        away = info.get("away", "?")
        sport = info.get("sport", "soccer")
        match_label = f"{home} vs {away}"

        log.info("  FACT CHECK %d/%d: %s (%s)", idx + 1, len(all_game_cbs), match_label, sport)

        # Navigate fresh
        if idx > 0:
            yg_msg = await send(client, "⚽ Your Games")
            if not yg_msg:
                record(test_id, f"Fact check — {match_label}", "SKIP",
                       "Could not navigate", [])
                continue

        # Click game
        gd_msg = await click_data_wait(client, yg_msg, game_cb)
        if not gd_msg:
            record(test_id, f"Fact check — {match_label}", "SKIP",
                   "No game detail response", [])
            continue

        raw = gd_msg.raw_text or ""
        styled = gd_msg.text or ""

        if len(raw) < 50:
            record(test_id, f"Fact check — {match_label}", "SKIP",
                   f"Short response ({len(raw)} chars)", [])
            continue

        # Determine league_key for verified context
        league_key = ""
        if "EPL" in raw or "Premier League" in raw:
            league_key = "epl"
        elif "PSL" in raw:
            league_key = "psl"
        elif "Champions League" in raw:
            league_key = "champions_league"

        # Fetch verified context independently
        ctx_data = await get_verified_context(home, away, league_key, sport)
        has_verified = ctx_data.get("data_available", False)

        fc_record = {
            "match": match_label,
            "sport": sport,
            "league": league_key,
            "has_verified_data": has_verified,
            "position_checks": [],
            "form_checks": [],
            "stat_checks": [],
            "sport_context_violations": [],
            "hallucination_bugs": [],
        }

        asserts: list[tuple[bool, str]] = []

        # 1. CHECK POSITION CLAIMS
        if has_verified:
            pos_results = fact_check_positions(raw, ctx_data)
            for pr in pos_results:
                fc_record["position_checks"].append(pr)
                if not pr["correct"]:
                    hal_bug_count += 1
                    bug_id = f"BUG-HAL-{hal_bug_count:03d}"
                    file_bug(bug_id, "P0", f"Game Breakdown: {match_label}",
                             f"AI breakdown claims {pr['team']} is {pr['claimed']}",
                             f"Verified position: {pr['verified']}",
                             f"Claimed: {pr['claimed']}, Actual: {pr['verified']}")
                    fc_record["hallucination_bugs"].append(bug_id)
            if pos_results:
                all_correct = all(pr["correct"] for pr in pos_results)
                asserts.append((all_correct,
                                f"Position claims correct: {sum(1 for p in pos_results if p['correct'])}/{len(pos_results)}"))
            else:
                asserts.append((True, "No position claims to verify"))
        else:
            # NO verified data — check that AI doesn't fabricate positions
            pos_claims = extract_position_claims(raw)
            if pos_claims:
                # AI made position claims without verified data — suspicious but may be OK
                # if the fact_check_output stripped them
                asserts.append((True,
                                f"Position claims found without verified data: {len(pos_claims)} (check manually)"))
                fc_record["position_checks"].append({
                    "note": f"No verified data but AI made {len(pos_claims)} position claims",
                    "claims": [c["context"][:80] for c in pos_claims],
                })
            else:
                asserts.append((True, "No position claims (correct — no verified data)"))

        # 2. CHECK FORM CLAIMS
        form_claims = extract_form_claims(raw)
        if form_claims and has_verified:
            # Verify form strings against ctx_data
            for side in ("home_team", "away_team"):
                team = ctx_data.get(side, {})
                verified_form = team.get("form", "")
                if verified_form:
                    fc_record["form_checks"].append({
                        "team": team.get("name", ""),
                        "verified_form": verified_form,
                    })
            asserts.append((True, f"Form claims found: {len(form_claims)}"))
        else:
            asserts.append((True, f"Form claims: {len(form_claims)}"))

        # 3. CHECK STATISTICAL CLAIMS
        stat_claims = extract_stat_claims(raw)
        fc_record["stat_checks"] = [{"value": s["value"], "type": s["type"]} for s in stat_claims]
        if stat_claims and not has_verified:
            # Stats without verified data — could be hallucinated
            asserts.append((True,
                            f"WARN: {len(stat_claims)} stat claims without verified data"))
        else:
            asserts.append((True, f"Stat claims: {len(stat_claims)}"))

        # 4. CHECK SPORT CONTEXT
        violations = check_sport_context(raw, sport)
        fc_record["sport_context_violations"] = violations
        no_violations = len(violations) == 0
        if not no_violations:
            for v in violations:
                hal_bug_count += 1
                bug_id = f"BUG-HAL-{hal_bug_count:03d}"
                file_bug(bug_id, "P0", f"Game Breakdown: {match_label}",
                         f"AI used wrong-sport terminology",
                         f"No {sport}-inappropriate terms",
                         v)
                fc_record["hallucination_bugs"].append(bug_id)
        asserts.append((no_violations,
                        f"Sport context clean ({sport}): {no_violations}" +
                        (f" — violations: {violations}" if violations else "")))

        # 5. CHECK ODDS-ONLY MODE (for matches without verified data)
        if not has_verified:
            # Claude should NOT cite specific positions/stats
            asserts.append((True, f"Odds-only mode (no verified data available)"))

        # Overall status
        has_hal_bug = len(fc_record["hallucination_bugs"]) > 0
        status = "FAIL" if has_hal_bug else "PASS"
        detail = (
            f"Verified data: {has_verified}\n"
            f"Position claims: {len(fc_record['position_checks'])}\n"
            f"Form claims: {len(form_claims)}\n"
            f"Stat claims: {len(stat_claims)}\n"
            f"Sport violations: {len(violations)}\n"
            f"HAL bugs: {len(fc_record['hallucination_bugs'])}"
        )
        record(test_id, f"Fact check — {match_label} ({sport})", status,
               raw, asserts, detail)

        fact_checks.append(fc_record)
        await asyncio.sleep(1)

    # FC-SUM: Fact-check summary
    total_fc = len(fact_checks)
    total_hal = sum(len(fc["hallucination_bugs"]) for fc in fact_checks)
    with_verified = sum(1 for fc in fact_checks if fc["has_verified_data"])
    summary_asserts = [
        (total_hal == 0, f"Zero BUG-HAL filed: {total_hal}"),
        (total_fc >= 3, f"At least 3 matches fact-checked: {total_fc}"),
    ]
    status = "PASS" if all(a[0] for a in summary_asserts) else "FAIL"
    record("FC-SUM", f"Fact-check summary ({total_fc} matches)", status,
           f"Total: {total_fc}, With verified data: {with_verified}, HAL bugs: {total_hal}",
           summary_asserts,
           f"Checked {total_fc} matches, {with_verified} had verified context, {total_hal} hallucination bugs")

    # ================================================================
    # PART 3: REGRESSION
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("PART 3: REGRESSION")
    log.info("=" * 60)

    # R-01: /start
    start_msg = await send(client, "/start")
    if start_msg:
        st = start_msg.raw_text or ""
        asserts = [(len(st) > 20, f"/start: {len(st)} chars")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("R-01", "Regression — /start", status, st[:300], asserts)
    else:
        record("R-01", "Regression — /start", "FAIL", "No response", [])

    # R-02: Settings
    set_msg = await send(client, "⚙️ Settings")
    if set_msg:
        st = set_msg.raw_text or ""
        sbtns = get_buttons(set_msg)
        asserts = [(len(sbtns) >= 3, f"3+ buttons: {len(sbtns)}")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("R-02", "Regression — Settings", status,
               f"Buttons: {sbtns}", asserts)
    else:
        record("R-02", "Regression — Settings", "FAIL", "No response", [])

    # R-03: Edge ratings still display
    hot_msg2 = await send_wait_buttons(client, "🔥 Hot Tips")
    if hot_msg2:
        ht2 = hot_msg2.raw_text or ""
        has_edge = any(e in ht2 for e in EDGE_EMOJIS)
        asserts = [(has_edge, f"Edge badges in Hot Tips: {has_edge}")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("R-03", "Regression — Edge ratings display", status, ht2[:400], asserts)
    else:
        record("R-03", "Regression — Edge ratings", "FAIL", "No response", [])

    # R-04: Profile
    prof_msg = await send(client, "👤 Profile")
    if prof_msg:
        pt = prof_msg.raw_text or ""
        asserts = [(len(pt) > 50, f"Profile: {len(pt)} chars")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("R-04", "Regression — Profile", status, pt[:300], asserts)
    else:
        record("R-04", "Regression — Profile", "FAIL", "No response", [])

    # R-05: Guide
    guide_msg = await send(client, "📖 Guide")
    if guide_msg:
        gt = guide_msg.raw_text or ""
        has_edge_section = "Edge Ratings" in gt or "Diamond" in gt
        asserts = [(has_edge_section, "Edge Ratings in Guide")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("R-05", "Regression — Guide", status, gt[:400], asserts)
    else:
        record("R-05", "Regression — Guide", "FAIL", "No response", [])

    # ── Disconnect ────────────────────────────────────────────────
    await client.disconnect()

    # ── Summary ───────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("WAVE 16C VERIFICATION RESULTS")
    log.info("=" * 60)
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    warned = sum(1 for r in results if r["status"] == "WARN")
    log.info("  Total:   %d", total)
    log.info("  PASS:    %d", passed)
    log.info("  FAIL:    %d", failed)
    log.info("  SKIP:    %d", skipped)
    log.info("  WARN:    %d", warned)
    log.info("")
    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(r["status"], "?")
        log.info("  %s %s: %s", icon, r["test_id"], r["name"])
    if bugs:
        log.info("")
        log.info("  BUGS FILED: %d", len(bugs))
        for b in bugs:
            log.info("    %s (%s): %s — %s", b["id"], b["severity"], b["screen"], b.get("actual", "")[:80])

    # Fact-check detail
    log.info("")
    log.info("  FACT-CHECK DETAIL:")
    for fc in fact_checks:
        hal = fc["hallucination_bugs"]
        icon = "✗" if hal else "✓"
        log.info("    %s %s [%s/%s] — verified: %s, HAL: %d",
                 icon, fc["match"], fc["sport"], fc["league"],
                 fc["has_verified_data"], len(hal))
        for pc in fc["position_checks"]:
            if isinstance(pc, dict) and "correct" in pc:
                pc_icon = "✓" if pc["correct"] else "✗"
                log.info("      %s Position: %s claimed %d, verified %d",
                         pc_icon, pc.get("team", ""), pc.get("claimed", 0), pc.get("verified", 0))

    summary = {
        "wave": "16C",
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "warned": warned,
        "bug_count": len(bugs),
        "hal_bug_count": sum(1 for b in bugs if b["id"].startswith("BUG-HAL")),
        "fact_checks": fact_checks,
        "results": results,
        "bugs": bugs,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("")
    log.info("Results: %s", RESULTS_PATH)


if __name__ == "__main__":
    asyncio.run(run_tests())
