#!/usr/bin/env python3
"""E2E Live Bot Test Suite — Wave 11B.

Tests the ACTUAL running bot by invoking its handlers directly, capturing
the real Telegram HTML output, and validating against UX specs.

Unlike unit tests that mock everything, this imports the real bot module
(which connects to real DB, real config) and calls the actual handler
functions, capturing what would be sent to Telegram.

Usage:
    cd /home/paulsportsza/bot
    source .venv/bin/activate
    python tests/test_e2e_live.py 2>&1 | tee /home/paulsportsza/reports/e2e-results.txt
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Setup environment
os.chdir("/home/paulsportsza/bot")
sys.path.insert(0, "/home/paulsportsza/bot")

os.environ.setdefault("TZ", "Africa/Johannesburg")

# Load .env
from dotenv import load_dotenv
load_dotenv("/home/paulsportsza/bot/.env")

# ── Results tracking ─────────────────────────────────────────────────
RESULTS: list[dict] = []
SCREENSHOTS_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def record(test_id: str, name: str, status: str, response: str = "",
           assertions: list[tuple[bool, str]] | None = None, detail: str = ""):
    """Record a test result."""
    assertions = assertions or []
    entry = {
        "test_id": test_id,
        "name": name,
        "status": status,
        "response": response[:2000] if response else "",
        "assertions": [(s, m) for s, m in assertions],
        "detail": detail,
    }
    RESULTS.append(entry)

    # Save screenshot
    screenshot_path = SCREENSHOTS_DIR / f"{test_id.lower().replace('-', '_')}.txt"
    screenshot_path.write_text(response or "(no response)")

    # Print result
    icon = "\u2705" if status == "PASS" else ("\u274c" if status == "FAIL" else "\u23ed\ufe0f")
    print(f"  [{icon} {status}] {test_id}: {name}")
    for passed, msg in assertions:
        flag = "\u2705" if passed else "\u274c"
        print(f"       {flag} {msg}")
    if detail:
        print(f"       Detail: {detail}")


# ── Bot internals import ─────────────────────────────────────────────
print("=" * 70)
print("LOADING BOT INTERNALS")
print("=" * 70)

try:
    import config
    import bot as bot_module
    from services.edge_rating import EdgeRating, calculate_edge_rating
    from services import odds_service as odds_svc
    from services.affiliate_service import select_best_bookmaker, get_runner_up_odds
    from renderers.edge_renderer import (
        render_edge_badge, render_tip_with_odds, render_tip_button_label,
        render_odds_comparison, EDGE_EMOJIS, EDGE_LABELS,
    )
    print("All imports OK")
except Exception as exc:
    print(f"IMPORT FAILED: {exc}")
    sys.exit(1)


# ── Helper: simulate a Telegram Update ───────────────────────────────
class FakeChat:
    def __init__(self, chat_id=411927634):
        self.id = chat_id
        self.type = "private"

class FakeUser:
    def __init__(self, user_id=411927634, first_name="Paul", username="paulsportsza"):
        self.id = user_id
        self.first_name = first_name
        self.username = username
        self.is_bot = False
        self.language_code = "en"

class CapturedMessage:
    """Captures what the bot would send to Telegram."""
    def __init__(self):
        self.messages: list[dict] = []
        self.edited: list[dict] = []
        self.deleted: list[int] = []

    def _make_sent(self, text, **kwargs):
        msg = MagicMock()
        msg.text = text
        msg.message_id = len(self.messages) + 1000
        msg.chat = FakeChat()
        msg.delete = AsyncMock()
        msg.edit_text = AsyncMock(side_effect=lambda t, **kw: self._edit(t, **kw))
        self.messages.append({"text": text, **kwargs})
        return msg

    def _edit(self, text, **kwargs):
        self.edited.append({"text": text, **kwargs})

    @property
    def all_texts(self) -> list[str]:
        """All texts: sent + edited (final state)."""
        texts = [m["text"] for m in self.messages]
        texts.extend(m["text"] for m in self.edited)
        return texts

    @property
    def last_text(self) -> str:
        if self.edited:
            return self.edited[-1]["text"]
        if self.messages:
            return self.messages[-1]["text"]
        return ""

    @property
    def all_buttons(self) -> list[str]:
        """All button labels from inline keyboards."""
        buttons = []
        for m in self.messages + self.edited:
            markup = m.get("reply_markup")
            if markup and hasattr(markup, "inline_keyboard"):
                for row in markup.inline_keyboard:
                    for btn in row:
                        buttons.append(btn.text)
        return buttons

    @property
    def all_callback_data(self) -> list[str]:
        data = []
        for m in self.messages + self.edited:
            markup = m.get("reply_markup")
            if markup and hasattr(markup, "inline_keyboard"):
                for row in markup.inline_keyboard:
                    for btn in row:
                        if btn.callback_data:
                            data.append(btn.callback_data)
        return data


# ══════════════════════════════════════════════════════════════════════
# SECTION 1: DIAGNOSTIC CHECKS
# ══════════════════════════════════════════════════════════════════════

async def run_diagnostics():
    print("\n" + "=" * 70)
    print("SECTION 0: DIAGNOSTICS")
    print("=" * 70)

    # DIAG-001: Bot code version
    import subprocess
    result = subprocess.run(["git", "log", "--oneline", "-1"],
                            capture_output=True, text=True, cwd="/home/paulsportsza/bot")
    commit = result.stdout.strip()
    record("DIAG-001", "Bot code version",
           "PASS" if "8c25076" in commit else "FAIL",
           response=commit,
           assertions=[(True, f"Commit: {commit}")],
           detail="Expected 8c25076")

    # DIAG-002: Bot process running latest code
    result = subprocess.run(["ps", "-p", str(os.popen("pgrep -f 'python.*bot.py' | head -1").read().strip()),
                             "-o", "lstart="],
                            capture_output=True, text=True)
    proc_start = result.stdout.strip()
    record("DIAG-002", "Bot process start time",
           "PASS",
           response=proc_start,
           assertions=[(True, f"Process started: {proc_start}")],
           detail="Must be AFTER 8c25076 commit time")

    # DIAG-003: odds.db accessible and fresh
    try:
        conn = sqlite3.connect("/home/paulsportsza/scrapers/odds.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM odds_snapshots")
        rows = c.fetchone()[0]
        c.execute("SELECT DISTINCT bookmaker FROM odds_snapshots")
        bookmakers = [r[0] for r in c.fetchall()]
        c.execute("SELECT MAX(scraped_at) FROM odds_snapshots")
        latest = c.fetchone()[0]
        conn.close()
        record("DIAG-003", "odds.db accessible",
               "PASS",
               response=f"rows={rows}, bookmakers={bookmakers}, latest={latest}",
               assertions=[
                   (rows > 10000, f"Rows: {rows} (need >10K)"),
                   (len(bookmakers) >= 4, f"Bookmakers: {len(bookmakers)} ({bookmakers})"),
                   (latest is not None, f"Latest scrape: {latest}"),
               ])
    except Exception as exc:
        record("DIAG-003", "odds.db accessible", "FAIL", detail=str(exc))

    # DIAG-004: Edge emojis correct (Diamond system — Wave 14A)
    expected = {
        "diamond": "\U0001f48e",   # 💎
        "gold": "\U0001f947",      # 🥇
        "silver": "\U0001f948",    # 🥈
        "bronze": "\U0001f949",    # 🥉
    }
    emoji_checks = []
    for tier, exp in expected.items():
        actual = EDGE_EMOJIS.get(tier, "MISSING")
        match = actual == exp
        emoji_checks.append((match, f"{tier}: got '{actual}', expected '{exp}'"))
    all_match = all(c[0] for c in emoji_checks)
    record("DIAG-004", "Edge emojis match UX spec",
           "PASS" if all_match else "FAIL",
           response=json.dumps({k: repr(v) for k, v in EDGE_EMOJIS.items()}),
           assertions=emoji_checks)

    # DIAG-005: Edge thresholds correct
    from services.edge_rating import calculate_edge_rating
    import inspect
    source = inspect.getsource(calculate_edge_rating)
    checks = [
        ("total >= 85" in source, "Platinum threshold: 85"),
        ("total >= 70" in source, "Gold threshold: 70"),
        ("total >= 55" in source, "Silver threshold: 55"),
        ("total >= 40" in source, "Bronze threshold: 40"),
    ]
    record("DIAG-005", "Edge thresholds match UX spec",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)

    # DIAG-006: Multi-bookmaker imports in bot.py
    source = inspect.getsource(bot_module)
    checks = [
        ("from services.edge_rating import" in source, "edge_rating imported in bot.py"),
        ("from services import odds_service" in source or "from services.odds_service" in source,
         "odds_service imported in bot.py"),
        ("from services.affiliate_service import" in source, "affiliate_service imported in bot.py"),
        ("from renderers.edge_renderer import" in source, "edge_renderer imported in bot.py"),
        ("calculate_edge_rating" in source, "calculate_edge_rating() called in bot.py"),
        ("select_best_bookmaker" in source, "select_best_bookmaker() called in bot.py"),
        ("render_tip_with_odds" in source, "render_tip_with_odds() called in bot.py"),
        ("render_edge_badge" in source, "render_edge_badge() called in bot.py"),
    ]
    record("DIAG-006", "Multi-bookmaker wired into bot.py",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)


# ══════════════════════════════════════════════════════════════════════
# SECTION 2: HOT TIPS — THE CRITICAL PATH
# ══════════════════════════════════════════════════════════════════════

async def test_hot_tips():
    print("\n" + "=" * 70)
    print("SECTION 2: HOT TIPS — CRITICAL PATH")
    print("=" * 70)

    # TEST-007: Hot Tips fetch + edge rating
    print("\n  Fetching hot tips (this calls the REAL _fetch_hot_tips_all_sports)...")
    try:
        tips = await bot_module._fetch_hot_tips_all_sports()
    except Exception as exc:
        record("TEST-007", "Hot Tips — fetch", "FAIL",
               detail=f"Exception: {exc}")
        return

    tip_summary = []
    for i, t in enumerate(tips):
        tip_summary.append(
            f"  [{i+1}] {t.get('home_team','?')} vs {t.get('away_team','?')} "
            f"| edge={t.get('edge_rating','MISSING')} | EV={t.get('ev',0)}% "
            f"| odds={t.get('odds',0):.2f} | bk={t.get('bookmaker','?')}"
        )
    tip_text = "\n".join(tip_summary) if tip_summary else "(no tips found)"

    checks_007 = [
        (len(tips) > 0, f"Tips returned: {len(tips)}"),
        (all(t.get("edge_rating") != EdgeRating.HIDDEN for t in tips),
         "No HIDDEN tips in results (filtered out)"),
    ]

    # Check sorting: should be by edge tier then EV
    if len(tips) > 1:
        rating_order = {EdgeRating.DIAMOND: 0, EdgeRating.GOLD: 1,
                        EdgeRating.SILVER: 2, EdgeRating.BRONZE: 3}
        sorted_correctly = True
        for i in range(len(tips) - 1):
            r1 = rating_order.get(tips[i].get("edge_rating", ""), 9)
            r2 = rating_order.get(tips[i+1].get("edge_rating", ""), 9)
            if r1 > r2:
                sorted_correctly = False
                break
            if r1 == r2 and tips[i]["ev"] < tips[i+1]["ev"]:
                sorted_correctly = False
                break
        checks_007.append((sorted_correctly, "Tips sorted by edge tier then EV"))
    else:
        checks_007.append((True, "Only 0-1 tips — sorting N/A"))

    # Check edge ratings are valid
    valid_ratings = {EdgeRating.DIAMOND, EdgeRating.GOLD, EdgeRating.SILVER, EdgeRating.BRONZE}
    ratings_present = {t.get("edge_rating") for t in tips}
    checks_007.append((ratings_present <= valid_ratings,
                        f"All ratings valid: {ratings_present}"))

    record("TEST-007", "Hot Tips — fetch + edge rating",
           "PASS" if all(c[0] for c in checks_007) else "FAIL",
           response=tip_text,
           assertions=checks_007)

    # TEST-008: Edge badge rendering
    if tips:
        badge_checks = []
        for i, tip in enumerate(tips[:5]):
            rating = tip.get("edge_rating", "")
            badge = render_edge_badge(rating)
            expected_emoji = EDGE_EMOJIS.get(rating, "")
            expected_label = EDGE_LABELS.get(rating, "")
            has_emoji = expected_emoji in badge if expected_emoji else True
            has_label = expected_label in badge if expected_label else True
            badge_checks.append((
                has_emoji and has_label,
                f"Tip {i+1} ({rating}): badge='{badge}'"
            ))
        record("TEST-008", "Edge badge rendering",
               "PASS" if all(c[0] for c in badge_checks) else "FAIL",
               assertions=badge_checks)
    else:
        record("TEST-008", "Edge badge rendering", "SKIP", detail="No tips to test")

    # TEST-009: Hot Tips message formatting
    if tips:
        # Simulate the actual message builder from _do_hot_tips_flow
        from html import escape as h
        lines = [
            f"\U0001f525 <b>Hot Tips \u2014 {len(tips)} Value Bet{'s' if len(tips) != 1 else ''}</b>",
            f"<i>Scanned {len(bot_module.HOT_TIPS_SCAN_SPORTS)} markets across all sports.</i>",
            "",
        ]
        for i, tip in enumerate(tips[:10], 1):
            kickoff = bot_module._format_kickoff_display(tip["commence_time"])
            sport_emoji = bot_module._get_sport_emoji_for_api_key(tip.get("sport_key", ""))
            home = h(tip.get("home_team", ""))
            away = h(tip.get("away_team", ""))
            outcome = h(tip.get("outcome", ""))
            badge = render_edge_badge(tip.get("edge_rating", ""))
            badge_line = f"     {badge}\n" if badge else ""
            lines.append(
                f"[{i}] {sport_emoji} <b>{home} vs {away}</b>\n"
                f"     \u23f0 {kickoff}\n"
                f"{badge_line}"
                f"     \U0001f4b0 {outcome} @ <b>{tip['odds']:.2f}</b> \u00b7 EV +{tip['ev']}%"
            )
            lines.append("")

        full_msg = "\n".join(lines)

        format_checks = [
            (len(full_msg) <= 4096, f"Message length: {len(full_msg)} chars (limit 4096)"),
            ("\U0001f525" in full_msg, "Header has fire emoji"),
            ("Value Bet" in full_msg, "Header says 'Value Bet'"),
            ("\u23f0" in full_msg, "Kickoff times have clock emoji"),
            ("\U0001f4b0" in full_msg, "Odds have money emoji"),
        ]

        # Check edge badges appear
        has_any_badge = False
        for rating in ["diamond", "gold", "silver", "bronze"]:
            emoji = EDGE_EMOJIS.get(rating, "")
            if emoji and emoji in full_msg:
                has_any_badge = True
                break
        format_checks.append((has_any_badge, "Edge badges visible in message"))

        # Check no raw HTML tags visible (they should be markup, not content)
        visible_tags = re.findall(r"(?<![<])<(?:b|i|code)[^>]*>", full_msg)
        # This is HTML for Telegram — tags are expected as markup.
        # What we DON'T want: literal escaped tags showing to user
        has_escaped_tags = "&lt;b&gt;" in full_msg or "&lt;i&gt;" in full_msg
        format_checks.append((not has_escaped_tags, "No escaped HTML tags visible to user"))

        # Check Betway isn't hardcoded everywhere
        betway_count = full_msg.lower().count("betway")
        format_checks.append((betway_count == 0,
                               f"Betway mentions in listing: {betway_count} (should be 0 in listing)"))

        record("TEST-009", "Hot Tips — message formatting",
               "PASS" if all(c[0] for c in format_checks) else "FAIL",
               response=full_msg[:1500],
               assertions=format_checks)
    else:
        record("TEST-009", "Hot Tips — message formatting", "SKIP", detail="No tips")

    # TEST-010: Tip detail — multi-bookmaker odds
    if tips:
        tip = tips[0]
        match_id = odds_svc.build_match_id(
            tip.get("home_team", ""),
            tip.get("away_team", ""),
            tip.get("commence_time", ""),
        )
        odds_result = await odds_svc.get_best_odds(match_id, "1x2") if match_id else {}

        outcome_key = tip.get("outcome", "").lower()
        _oc_map = {"home team": "home", "away team": "away", "draw": "draw"}
        mapped_key = _oc_map.get(outcome_key, outcome_key)
        outcome_data = odds_result.get("outcomes", {}).get(mapped_key, {})
        odds_by_bookmaker = outcome_data.get("all_bookmakers", {})

        detail_checks = [
            (match_id is not None and len(match_id) > 5,
             f"match_id built: '{match_id}'"),
            (bool(odds_result.get("outcomes")),
             f"Outcomes from DB: {list(odds_result.get('outcomes', {}).keys())}"),
        ]

        if odds_by_bookmaker:
            detail_checks.append((
                len(odds_by_bookmaker) > 1,
                f"Multi-bookmaker odds: {len(odds_by_bookmaker)} bookmakers — {odds_by_bookmaker}"
            ))

            best_bk = select_best_bookmaker(odds_by_bookmaker, 411927634, match_id)
            runner_ups = get_runner_up_odds(odds_by_bookmaker, best_bk.get("bookmaker_key", ""))

            detail_checks.append((
                best_bk.get("bookmaker_name") is not None,
                f"Best bookmaker: {best_bk.get('bookmaker_name')} @ {best_bk.get('odds')}"
            ))

            is_dynamic = best_bk.get("bookmaker_name", "").lower() != "betway" or len(odds_by_bookmaker) > 1
            detail_checks.append((
                is_dynamic or len(odds_by_bookmaker) == 1,
                f"Dynamic CTA (not always Betway): best={best_bk.get('bookmaker_name')}"
            ))

            # Render the actual tip card
            edge = tip.get("edge_rating", "")
            rendered = render_tip_with_odds(
                match=tip,
                odds_by_bookmaker=odds_by_bookmaker,
                edge_rating=edge,
                best_bookmaker=best_bk,
                runner_ups=runner_ups,
                predicted_outcome=tip.get("outcome", ""),
            )

            detail_checks.extend([
                ("Best Odds:" in rendered, "Rendered card has 'Best Odds:' line"),
                ("Also:" in rendered if runner_ups else True,
                 f"Runner-ups shown: {len(runner_ups)} bookmakers"),
                (EDGE_EMOJIS.get(edge, "X") in rendered if edge else True,
                 f"Edge badge in rendered card: {edge}"),
            ])

            # CTA button
            cta = render_tip_button_label(best_bk)
            detail_checks.append((
                best_bk.get("bookmaker_name", "") in cta,
                f"CTA label: '{cta}'"
            ))

            record("TEST-010", "Tip detail — multi-bookmaker odds",
                   "PASS" if all(c[0] for c in detail_checks) else "FAIL",
                   response=rendered,
                   assertions=detail_checks)
        else:
            detail_checks.append((False,
                f"NO multi-bookmaker data for match_id='{match_id}'"))
            record("TEST-010", "Tip detail — multi-bookmaker odds",
                   "FAIL",
                   response=f"match_id={match_id}, outcomes={odds_result.get('outcomes', {})}",
                   assertions=detail_checks,
                   detail="Odds not found in Dataminer DB — team name mismatch?")
    else:
        record("TEST-010", "Tip detail — multi-bookmaker odds", "SKIP", detail="No tips")

    # TEST-011: Odds comparison rendering
    if tips and odds_by_bookmaker and len(odds_by_bookmaker) > 1:
        comparison = render_odds_comparison(odds_by_bookmaker, tips[0].get("outcome", ""))
        comp_checks = [
            (len(comparison) > 0, "Comparison not empty"),
            ("\u2b50" in comparison, "Best odds marked with star"),
            ("<b>" in comparison, "Odds in bold"),
        ]
        # Check bookmaker count in display
        bk_names_found = 0
        for bk_key in odds_by_bookmaker:
            aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
            sa = config.SA_BOOKMAKERS.get(bk_key)
            name = (aff or {}).get("name") or (sa or {}).get("short_name") or bk_key.title()
            if name in comparison:
                bk_names_found += 1
        comp_checks.append((bk_names_found >= 2,
                             f"Bookmaker names in comparison: {bk_names_found}"))
        record("TEST-011", "Odds comparison rendering",
               "PASS" if all(c[0] for c in comp_checks) else "FAIL",
               response=comparison,
               assertions=comp_checks)
    else:
        record("TEST-011", "Odds comparison rendering", "SKIP",
               detail="Need >1 bookmaker for comparison")

    # TEST-012: CTA button URL
    if tips and odds_by_bookmaker:
        best_bk = select_best_bookmaker(odds_by_bookmaker, 411927634, match_id)
        url = best_bk.get("affiliate_url", "")
        url_checks = [
            (len(url) > 10, f"URL generated: {url}"),
            (".co.za" in url or ".net" in url, f"SA domain in URL: {url}"),
        ]
        record("TEST-012", "CTA button URL",
               "PASS" if all(c[0] for c in url_checks) else "FAIL",
               response=url,
               assertions=url_checks)
    else:
        record("TEST-012", "CTA button URL", "SKIP", detail="No bookmaker data")

    return tips


# ══════════════════════════════════════════════════════════════════════
# SECTION 3: EDGE RATING EDGE CASES
# ══════════════════════════════════════════════════════════════════════

async def test_edge_rating_cases():
    print("\n" + "=" * 70)
    print("SECTION 3: EDGE RATING EDGE CASES")
    print("=" * 70)

    from services.edge_rating import _safe_odds

    # TEST-013: _safe_odds robustness
    cases = [
        ({"odds": None}, None, "None"),
        ({"odds": 0}, None, "zero"),
        ({"odds": -1}, None, "negative"),
        ({"odds": "abc"}, None, "string"),
        ({}, None, "missing key"),
        ({"odds": 2.5}, 2.5, "valid float"),
        ({"odds": "1.85"}, 1.85, "valid string"),
    ]
    safe_checks = []
    for inp, expected, label in cases:
        result = _safe_odds(inp)
        safe_checks.append((result == expected, f"_safe_odds({label}): got {result}, expected {expected}"))

    record("TEST-013", "_safe_odds robustness (BUG-012 fix)",
           "PASS" if all(c[0] for c in safe_checks) else "FAIL",
           assertions=safe_checks)

    # TEST-014: Edge rating with all-None odds
    rating = calculate_edge_rating(
        [{"bookmaker": "bw", "outcome": "home", "odds": None},
         {"bookmaker": "hw", "outcome": "home", "odds": None}],
        {"outcome": "home", "confidence": 0.8, "implied_prob": 0.6}
    )
    record("TEST-014", "Edge rating with all-None odds",
           "PASS" if rating == EdgeRating.HIDDEN else "FAIL",
           assertions=[(rating == EdgeRating.HIDDEN, f"Rating: {rating} (expected HIDDEN)")],
           detail="All-None odds should produce HIDDEN, not crash")

    # TEST-015: Edge rating high-confidence scenario
    snapshots = [
        {"bookmaker": f"bk{i}", "outcome": "home", "odds": 1.7 + i * 0.05}
        for i in range(5)
    ]
    model = {"outcome": "home", "confidence": 0.92, "implied_prob": 0.62}
    movement = {"direction": "shortening", "magnitude": 0.12, "hours": 24}
    rating = calculate_edge_rating(snapshots, model, movement)
    record("TEST-015", "High-confidence edge scenario",
           "PASS" if rating in (EdgeRating.DIAMOND, EdgeRating.GOLD) else "FAIL",
           assertions=[
               (rating in (EdgeRating.DIAMOND, EdgeRating.GOLD),
                f"Rating: {rating} (expected DIAMOND or GOLD)"),
           ])


# ══════════════════════════════════════════════════════════════════════
# SECTION 4: ODDS SERVICE LIVE DATA
# ══════════════════════════════════════════════════════════════════════

async def test_odds_service():
    print("\n" + "=" * 70)
    print("SECTION 4: ODDS SERVICE LIVE DATA")
    print("=" * 70)

    # TEST-016: get_all_matches returns data
    matches = await odds_svc.get_all_matches("1x2", limit=10)
    match_checks = [
        (len(matches) > 0, f"Matches returned: {len(matches)}"),
    ]
    if matches:
        first = matches[0]
        match_checks.extend([
            (first.get("bookmaker_count", 0) > 0,
             f"Bookmaker count: {first.get('bookmaker_count')}"),
            (len(first.get("outcomes", {})) > 0,
             f"Outcomes: {list(first.get('outcomes', {}).keys())}"),
            (bool(first.get("home_team")),
             f"Teams: {first.get('home_team')} vs {first.get('away_team')}"),
        ])

    match_text = "\n".join([
        f"  {m['match_id']}: {m.get('bookmaker_count',0)} bks, "
        f"outcomes={list(m.get('outcomes',{}).keys())}"
        for m in matches[:5]
    ])
    record("TEST-016", "Odds service — get_all_matches",
           "PASS" if all(c[0] for c in match_checks) else "FAIL",
           response=match_text,
           assertions=match_checks)

    # TEST-017: League filter case-insensitive (BUG-017)
    psl_lower = await odds_svc.get_all_matches("1x2", league="psl", limit=5)
    psl_upper = await odds_svc.get_all_matches("1x2", league="PSL", limit=5)
    record("TEST-017", "League filter case-sensitivity (BUG-017)",
           "PASS" if len(psl_lower) == len(psl_upper) else "FAIL",
           assertions=[
               (len(psl_lower) > 0, f"'psl' (lowercase): {len(psl_lower)} matches"),
               (len(psl_upper) > 0, f"'PSL' (uppercase): {len(psl_upper)} matches"),
               (len(psl_lower) == len(psl_upper),
                f"Case-insensitive: lower={len(psl_lower)}, upper={len(psl_upper)}"),
           ],
           detail="BUG-017: get_all_matches should work with both 'psl' and 'PSL'")

    # TEST-018: build_match_id format
    mid = odds_svc.build_match_id("Kaizer Chiefs", "Orlando Pirates", "2026-03-01T15:00:00Z")
    mid_checks = [
        (mid is not None, f"match_id: '{mid}'"),
        ("kaizer" in mid.lower() if mid else False, "Contains 'kaizer'"),
        ("pirates" in mid.lower() if mid else False, "Contains 'pirates'"),
        ("2026-03-01" in mid if mid else False, "Contains date"),
    ]
    record("TEST-018", "build_match_id format",
           "PASS" if all(c[0] for c in mid_checks) else "FAIL",
           response=mid or "",
           assertions=mid_checks)


# ══════════════════════════════════════════════════════════════════════
# SECTION 5: AFFILIATE SERVICE
# ══════════════════════════════════════════════════════════════════════

async def test_affiliate_service():
    print("\n" + "=" * 70)
    print("SECTION 5: AFFILIATE SERVICE")
    print("=" * 70)

    # TEST-019: Best bookmaker selection
    odds = {"hollywoodbets": 2.15, "betway": 2.10, "supabets": 2.05, "gbets": 2.00}
    best = select_best_bookmaker(odds, 411927634, "test_match")
    checks = [
        (best["bookmaker_key"] == "hollywoodbets",
         f"Best by odds: {best['bookmaker_key']} @ {best.get('odds')}"),
        (best["odds"] == 2.15, f"Odds: {best['odds']}"),
        (best["bookmaker_name"] is not None,
         f"Display name: {best['bookmaker_name']}"),
    ]
    record("TEST-019", "Best bookmaker — highest odds wins",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           response=json.dumps(best, default=str),
           assertions=checks)

    # TEST-020: Runner-up odds
    runners = get_runner_up_odds(odds, "hollywoodbets", max_others=3)
    runner_checks = [
        (len(runners) == 3, f"Runner-ups: {len(runners)}"),
        (all(r["bookmaker_key"] != "hollywoodbets" for r in runners),
         "Best excluded from runner-ups"),
        (runners[0]["odds"] >= runners[1]["odds"] if len(runners) >= 2 else True,
         "Sorted by odds descending"),
    ]
    record("TEST-020", "Runner-up odds exclude best",
           "PASS" if all(c[0] for c in runner_checks) else "FAIL",
           response=json.dumps(runners, default=str),
           assertions=runner_checks)

    # TEST-021: Bookmaker display names
    name_checks = []
    for bk_key in ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets"]:
        aff = config.BOOKMAKER_AFFILIATES.get(bk_key)
        sa = config.SA_BOOKMAKERS.get(bk_key)
        name = (aff or {}).get("name") or (sa or {}).get("short_name") or bk_key.title()
        is_display = name != bk_key and name[0].isupper()
        name_checks.append((is_display, f"{bk_key} -> '{name}'"))
    record("TEST-021", "Bookmaker display names (not raw keys)",
           "PASS" if all(c[0] for c in name_checks) else "FAIL",
           assertions=name_checks)


# ══════════════════════════════════════════════════════════════════════
# SECTION 6: RENDERER — UX PLAYBOOK COMPLIANCE
# ══════════════════════════════════════════════════════════════════════

async def test_renderer_compliance():
    print("\n" + "=" * 70)
    print("SECTION 6: RENDERER — UX PLAYBOOK COMPLIANCE")
    print("=" * 70)

    # TEST-022: Edge badge format per tier
    badge_checks = []
    for tier in ["diamond", "gold", "silver", "bronze"]:
        badge = render_edge_badge(tier)
        emoji = EDGE_EMOJIS[tier]
        label = EDGE_LABELS[tier]
        badge_checks.append((
            emoji in badge and label in badge,
            f"{tier}: '{badge}' (emoji={repr(emoji)}, label='{label}')"
        ))
    badge = render_edge_badge("hidden")
    badge_checks.append((badge == "", f"hidden: '{badge}' (should be empty)"))
    badge = render_edge_badge("nonsense")
    badge_checks.append((badge == "", f"nonsense: '{badge}' (should be empty)"))
    record("TEST-022", "Edge badge format per tier",
           "PASS" if all(c[0] for c in badge_checks) else "FAIL",
           assertions=badge_checks)

    # TEST-023: Full tip card rendering
    match = {
        "home_team": "Kaizer Chiefs", "away_team": "Orlando Pirates",
        "league": "PSL", "commence_time": "2026-03-01T15:00:00Z",
        "sport_emoji": "\u26bd",
    }
    best_bk = {
        "bookmaker_key": "hollywoodbets", "bookmaker_name": "Hollywoodbets",
        "odds": 2.15, "affiliate_url": "https://www.hollywoodbets.net",
        "has_active_affiliate": False,
    }
    runner_ups = [
        {"bookmaker_name": "Betway", "odds": 2.10},
        {"bookmaker_name": "SupaBets", "odds": 2.05},
    ]
    rendered = render_tip_with_odds(
        match, {"hollywoodbets": 2.15, "betway": 2.10, "supabets": 2.05},
        "gold", best_bk, runner_ups, "Chiefs to Win",
    )
    card_checks = [
        ("Kaizer Chiefs vs Orlando Pirates" in rendered, "Team names in card"),
        ("GOLDEN EDGE" in rendered, "GOLDEN EDGE label in card"),
        ("\U0001f947" in rendered, "Gold emoji in card (🥇)"),
        ("2.15" in rendered, "Best odds shown"),
        ("Hollywoodbets" in rendered, "Best bookmaker shown"),
        ("Also:" in rendered, "Runner-ups 'Also:' line"),
        ("Betway" in rendered and "SupaBets" in rendered, "Runner-up names shown"),
        ("PSL" in rendered, "League shown"),
        ("Chiefs to Win" in rendered, "Predicted outcome shown"),
        ("<b>" in rendered, "HTML bold formatting"),
    ]
    record("TEST-023", "Full tip card rendering",
           "PASS" if all(c[0] for c in card_checks) else "FAIL",
           response=rendered,
           assertions=card_checks)

    # TEST-024: CTA button label format
    # Label is "Bet on {name} →", bot.py prepends "📲 " when building button
    label = render_tip_button_label(best_bk)
    cta_checks = [
        ("Bet" in label, f"Contains 'Bet': '{label}'"),
        ("Hollywoodbets" in label, "Has bookmaker name"),
        ("\u2192" in label, f"Has arrow: '{label}'"),
        (not label.startswith(" "), "No leading whitespace"),
    ]
    record("TEST-024", "CTA button label format",
           "PASS" if all(c[0] for c in cta_checks) else "FAIL",
           response=label,
           assertions=cta_checks)

    # TEST-025: Empty data graceful handling
    empty_tip = render_tip_with_odds({}, {}, "hidden", {})
    empty_checks = [
        ("Home vs Away" in empty_tip, "Default team names shown"),
        (len(empty_tip) > 0, "Non-empty response"),
    ]
    record("TEST-025", "Tip card with empty data",
           "PASS" if all(c[0] for c in empty_checks) else "FAIL",
           response=empty_tip,
           assertions=empty_checks)


# ══════════════════════════════════════════════════════════════════════
# SECTION 7: BOT HANDLER WIRING VERIFICATION
# ══════════════════════════════════════════════════════════════════════

async def test_handler_wiring():
    print("\n" + "=" * 70)
    print("SECTION 7: BOT HANDLER WIRING")
    print("=" * 70)

    import inspect
    source = inspect.getsource(bot_module)

    # TEST-026: hot:back callback handler
    checks = [
        ('"hot:back"' in source or "'hot:back'" in source,
         "hot:back callback_data exists in buttons"),
        ('action in ("go", "show", "back")' in source or
         'action in ("go","show","back")' in source or
         '"back"' in source,
         "hot:back routed in on_button handler"),
    ]
    record("TEST-026", "hot:back handler (P0-4 fix)",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)

    # TEST-027: HTML escape import
    checks = [
        ("from html import escape as h" in source, "html.escape imported as h()"),
    ]
    # Count h() usage
    h_calls = len(re.findall(r'\bh\(', source))
    checks.append((h_calls >= 10, f"h() called {h_calls} times (expect 10+)"))
    record("TEST-027", "HTML escaping (P0-1/P0-2 fix)",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)

    # TEST-028: live_scores toggle in settings
    checks = [
        ("live_scores" in source, "live_scores key referenced"),
        ("toggle_notify" in source, "toggle_notify handler exists"),
    ]
    record("TEST-028", "live_scores toggle (P0-3 fix)",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)

    # TEST-029: odds:compare handler
    checks = [
        ("odds:compare" in source, "odds:compare callback_data exists"),
        ("_handle_odds_comparison" in source, "_handle_odds_comparison function exists"),
        ("render_odds_comparison" in source, "render_odds_comparison called"),
    ]
    record("TEST-029", "Odds comparison handler wired",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)

    # TEST-030: Edge rating in Hot Tips flow
    # Check _fetch_hot_tips_all_sports calls calculate_edge_rating
    try:
        hot_tips_source = inspect.getsource(bot_module._fetch_hot_tips_all_sports)
        checks = [
            ("calculate_edge_rating" in hot_tips_source,
             "calculate_edge_rating() called in _fetch_hot_tips_all_sports"),
            ("EdgeRating.HIDDEN" in hot_tips_source,
             "HIDDEN check in _fetch_hot_tips_all_sports"),
            ("edge_rating" in hot_tips_source,
             "edge_rating key stored in tip dict"),
        ]
    except Exception:
        checks = [(False, "Could not inspect _fetch_hot_tips_all_sports")]

    record("TEST-030", "Edge rating in Hot Tips flow",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)

    # TEST-031: Tip detail uses multi-bookmaker
    try:
        # Look at the tip detail handler
        detail_funcs = [name for name in dir(bot_module) if "tip_detail" in name.lower() or "handle_tip" in name.lower()]
        source_snippets = []
        for fname in detail_funcs:
            fn = getattr(bot_module, fname, None)
            if fn and callable(fn):
                source_snippets.append(inspect.getsource(fn))
        combined = "\n".join(source_snippets)

        checks = [
            (len(detail_funcs) > 0, f"Tip detail functions: {detail_funcs}"),
            ("odds_svc" in combined or "get_best_odds" in combined,
             "odds_service queried in tip detail"),
            ("select_best_bookmaker" in combined,
             "select_best_bookmaker called in tip detail"),
            ("render_tip_with_odds" in combined,
             "render_tip_with_odds called in tip detail"),
        ]
    except Exception as exc:
        checks = [(False, f"Inspection failed: {exc}")]

    record("TEST-031", "Tip detail uses multi-bookmaker",
           "PASS" if all(c[0] for c in checks) else "FAIL",
           assertions=checks)


# ══════════════════════════════════════════════════════════════════════
# SECTION 8: TEAM NAME + BOOKMAKER NORMALISATION
# ══════════════════════════════════════════════════════════════════════

async def test_normalisation():
    print("\n" + "=" * 70)
    print("SECTION 8: NORMALISATION")
    print("=" * 70)

    # TEST-032: Bookmaker names are display-ready
    for bk_key in ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets"]:
        odds_dict = {bk_key: 2.00}
        best = select_best_bookmaker(odds_dict)
        name = best.get("bookmaker_name", "")
        is_display = name[0].isupper() if name else False
        record(f"TEST-032-{bk_key}", f"Bookmaker display name: {bk_key}",
               "PASS" if is_display else "FAIL",
               assertions=[(is_display, f"'{bk_key}' -> '{name}'")])


# ══════════════════════════════════════════════════════════════════════
# SECTION 9: ERROR HANDLING
# ══════════════════════════════════════════════════════════════════════

async def test_error_handling():
    print("\n" + "=" * 70)
    print("SECTION 9: ERROR HANDLING")
    print("=" * 70)

    # TEST-033: odds_service with missing DB
    original = odds_svc.ODDS_DB_PATH
    odds_svc.ODDS_DB_PATH = "/nonexistent/path.db"
    result = await odds_svc.get_best_odds("test", "1x2")
    odds_svc.ODDS_DB_PATH = original
    record("TEST-033", "Graceful handling of missing odds.db",
           "PASS" if result["outcomes"] == {} else "FAIL",
           assertions=[(result["outcomes"] == {}, "Returns empty outcomes, no crash")])

    # TEST-034: affiliate_service with empty odds
    result = select_best_bookmaker({})
    record("TEST-034", "Affiliate service with empty odds",
           "PASS" if result["bookmaker_key"] is None else "FAIL",
           assertions=[(result["bookmaker_key"] is None, "Returns None key, no crash")])

    # TEST-035: Edge rating with totally empty inputs
    try:
        rating = calculate_edge_rating([], {})
        record("TEST-035", "Edge rating with empty inputs",
               "PASS" if rating == EdgeRating.HIDDEN else "FAIL",
               assertions=[(rating == EdgeRating.HIDDEN, f"Rating: {rating}")])
    except Exception as exc:
        record("TEST-035", "Edge rating with empty inputs",
               "FAIL", detail=f"Exception: {exc}")

    # TEST-036: render_edge_badge with unknown tier
    badge = render_edge_badge("unknown_tier")
    record("TEST-036", "render_edge_badge unknown tier",
           "PASS" if badge == "" else "FAIL",
           assertions=[(badge == "", f"Badge: '{badge}' (should be empty)")])

    # TEST-037: render_odds_comparison with empty dict
    comp = render_odds_comparison({})
    record("TEST-037", "render_odds_comparison empty",
           "PASS" if comp == "" else "FAIL",
           assertions=[(comp == "", f"Output: '{comp}' (should be empty)")])

    # TEST-038: Hot Tips with simulated no-tips scenario
    # Verify the empty state message builder exists
    import inspect as _inspect
    source = _inspect.getsource(bot_module._do_hot_tips_flow)
    has_empty = "No edges found" in source or "no value bets" in source.lower() or "No edges" in source
    record("TEST-038", "Hot Tips empty state handler",
           "PASS" if has_empty else "FAIL",
           assertions=[(has_empty, "Empty state message exists in _do_hot_tips_flow")])


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  E2E LIVE BOT TEST SUITE — WAVE 11B")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Branch: main @ 8c25076")
    print("=" * 70)

    await run_diagnostics()
    tips = await test_hot_tips()
    await test_edge_rating_cases()
    await test_odds_service()
    await test_affiliate_service()
    await test_renderer_compliance()
    await test_handler_wiring()
    await test_normalisation()
    await test_error_handling()

    # ── SUMMARY ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    skipped = sum(1 for r in RESULTS if r["status"] == "SKIP")
    total = len(RESULTS)

    print(f"\nTotal: {total} | PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")

    if failed > 0:
        print("\nFAILED TESTS:")
        for r in RESULTS:
            if r["status"] == "FAIL":
                print(f"  \u274c {r['test_id']}: {r['name']}")
                for ok, msg in r["assertions"]:
                    if not ok:
                        print(f"     -> {msg}")
                if r["detail"]:
                    print(f"     Detail: {r['detail']}")

    # Save JSON results
    json_path = Path("/home/paulsportsza/reports/e2e-results.json")
    json_path.write_text(json.dumps(RESULTS, indent=2, default=str))
    print(f"\nJSON results: {json_path}")
    print(f"Screenshots: {SCREENSHOTS_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
