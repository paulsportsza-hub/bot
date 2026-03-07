"""E2E quality gate tests — Telethon-based regression suite for game breakdowns.

Tests the LIVE bot to ensure game breakdowns never produce:
- Terse single-line-per-team Setup sections
- Empty Edge/Risk/Verdict sections
- Missing section headers

Taps actual games from My Matches and validates the returned AI narrative
against the same quality gate used in production.

Usage:
    python tests/test_e2e_quality_gate.py              # Run all tests
    python tests/test_e2e_quality_gate.py --test setup  # Specific test
    python tests/test_e2e_quality_gate.py --verbose     # Show full narratives
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
)

# ── Configuration ────────────────────────────────────────

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.environ.get("TELETHON_SESSION", "data/telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

TIMEOUT_SHORT = 8   # For quick commands
TIMEOUT_LONG = 30   # For AI-generated breakdowns (Claude + retries)

# ── Quality patterns (mirrors bot.py _validate_breakdown) ──

_TERSE_STATS = re.compile(
    r"^[A-Z][\w\s']+:\s*\d+\w*\s+on\s+\d+\s+points", re.MULTILINE
)
_TERSE_TEAMLINE = re.compile(
    r"^[A-Z][\w\s'-]+:\s+(?:under\s|record\s|\d)", re.MULTILINE
)

SECTION_HEADERS = ["📋", "🎯", "⚠️", "🏆"]

REPORT_DIR = "/home/paulsportsza/reports/e2e-quality-gate"


@dataclass
class QualityCheck:
    """Results from checking a single game breakdown."""
    event_id: str = ""
    match_title: str = ""
    has_setup: bool = False
    has_edge: bool = False
    has_risk: bool = False
    has_verdict: bool = False
    setup_is_narrative: bool = False  # Not terse
    setup_sentences: int = 0
    edge_has_content: bool = False    # Not empty
    is_programmatic_fallback: bool = False
    raw_text: str = ""
    issues: list = field(default_factory=list)
    passed: bool = False


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration: float
    quality_checks: list = field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────

async def get_client() -> TelegramClient:
    # Try string session first (more reliable)
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                return client
            await client.disconnect()

    # Fallback to file session
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    return client


async def send_and_wait(client: TelegramClient, text: str, wait: float = TIMEOUT_SHORT) -> list:
    entity = await client.get_entity(BOT_USERNAME)
    await client.send_message(entity, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=15)
    return list(reversed(messages))


async def click_inline_button(client: TelegramClient, msg, callback_data_prefix: str,
                               wait: float = TIMEOUT_LONG) -> list:
    """Click an inline button by matching its callback data prefix."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                if data.startswith(callback_data_prefix):
                    await msg.click(data=btn.data)
                    await asyncio.sleep(wait)
                    entity = await client.get_entity(BOT_USERNAME)
                    messages = await client.get_messages(entity, limit=15)
                    return list(reversed(messages))
    return []


def extract_game_buttons(msg) -> list[dict]:
    """Extract all game buttons (yg:game:*) from a message."""
    buttons = []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return buttons
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                if data.startswith("yg:game:"):
                    event_id = data.replace("yg:game:", "")
                    buttons.append({"text": btn.text, "data": data, "event_id": event_id})
    return buttons


def check_breakdown_quality(text: str, event_id: str = "", match_title: str = "") -> QualityCheck:
    """Run quality gate checks on a game breakdown text."""
    qc = QualityCheck(event_id=event_id, match_title=match_title, raw_text=text)

    if not text:
        qc.issues.append("EMPTY_RESPONSE")
        return qc

    # Check section headers
    qc.has_setup = "📋" in text
    qc.has_edge = "🎯" in text
    qc.has_risk = "⚠️" in text
    qc.has_verdict = "🏆" in text

    if not qc.has_setup:
        qc.issues.append("MISSING_📋_SETUP")
    if not qc.has_edge:
        qc.issues.append("MISSING_🎯_EDGE")
    if not qc.has_risk:
        qc.issues.append("MISSING_⚠️_RISK")
    if not qc.has_verdict:
        qc.issues.append("MISSING_🏆_VERDICT")

    # Extract Setup section
    setup_text = ""
    if qc.has_setup:
        # Get text between Setup header and next section
        setup_match = re.search(
            r'📋.*?(?:The Setup|SETUP).*?\n(.*?)(?=🎯|⚠️|🏆|$)',
            text, re.DOTALL
        )
        if setup_match:
            setup_text = setup_match.group(1).strip()

    # Check for terse patterns
    terse_stats = _TERSE_STATS.findall(text)
    terse_lines = _TERSE_TEAMLINE.findall(text)

    if len(terse_stats) >= 1 or len(terse_lines) >= 2:
        qc.issues.append("TERSE_SETUP")
        qc.setup_is_narrative = False
    else:
        qc.setup_is_narrative = True

    # Count sentences in setup
    if setup_text:
        sentences = re.split(r'[.!?]+(?:\s|$)', setup_text)
        qc.setup_sentences = len([s for s in sentences if len(s.strip()) > 10])
        if qc.setup_sentences < 3:
            qc.issues.append(f"SHORT_SETUP ({qc.setup_sentences} sentences)")

    # Check Edge section has content
    if qc.has_edge:
        edge_match = re.search(
            r'🎯.*?(?:The Edge|EDGE).*?\n(.*?)(?=⚠️|🏆|$)',
            text, re.DOTALL
        )
        if edge_match:
            edge_text = edge_match.group(1).strip()
            qc.edge_has_content = len(edge_text) > 30
            if not qc.edge_has_content:
                qc.issues.append("EMPTY_EDGE")
        else:
            qc.issues.append("EMPTY_EDGE")

    # Check if programmatic fallback was used
    qc.is_programmatic_fallback = "Molineux Stadium" in text and "sit " in text and "from " in text

    # Overall pass/fail
    qc.passed = len(qc.issues) == 0

    return qc


def save_report(results: list[TestResult], checks: list[QualityCheck]):
    """Save E2E quality gate report to disk."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "timestamp": ts,
        "total_games_tested": len(checks),
        "games_passed": sum(1 for c in checks if c.passed),
        "games_failed": sum(1 for c in checks if not c.passed),
        "tests": [asdict(r) for r in results],
        "quality_checks": [
            {
                "event_id": c.event_id,
                "match_title": c.match_title,
                "passed": c.passed,
                "issues": c.issues,
                "setup_sentences": c.setup_sentences,
                "setup_is_narrative": c.setup_is_narrative,
                "edge_has_content": c.edge_has_content,
                "is_programmatic_fallback": c.is_programmatic_fallback,
            }
            for c in checks
        ],
    }

    report_path = os.path.join(REPORT_DIR, f"quality_gate_{ts}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  📄 Report saved: {report_path}")

    # Also save raw narratives for manual inspection
    for c in checks:
        if c.raw_text:
            safe_id = c.event_id.replace("/", "_")[:50]
            txt_path = os.path.join(REPORT_DIR, f"narrative_{safe_id}_{ts}.txt")
            with open(txt_path, "w") as f:
                f.write(f"Match: {c.match_title}\n")
                f.write(f"Event ID: {c.event_id}\n")
                f.write(f"Passed: {c.passed}\n")
                f.write(f"Issues: {c.issues}\n")
                f.write(f"Setup sentences: {c.setup_sentences}\n")
                f.write("=" * 60 + "\n")
                f.write(c.raw_text)
            print(f"  📝 Narrative saved: {txt_path}")


# ── Test Functions ───────────────────────────────────────

async def _get_my_matches_msg(client: TelegramClient):
    """Send My Matches and return the message with game buttons."""
    msgs = await send_and_wait(client, "⚽ My Matches", wait=TIMEOUT_SHORT)
    for msg in msgs:
        if msg.text and not msg.out and msg.reply_markup:
            game_btns = extract_game_buttons(msg)
            if game_btns:
                return msg
    return None


async def test_game_breakdowns_quality(client: TelegramClient, max_games: int = 3,
                                        verbose: bool = False) -> TestResult:
    """Tap up to max_games from My Matches and validate breakdown quality."""
    start = time.time()
    checks: list[QualityCheck] = []

    try:
        # Get My Matches
        print("    → Loading My Matches...")
        yg_msg = await _get_my_matches_msg(client)

        if not yg_msg:
            return TestResult("game_breakdowns", False,
                              "No 'My Matches' message found", time.time() - start, [])

        # Extract game buttons
        game_buttons = extract_game_buttons(yg_msg)
        if not game_buttons:
            return TestResult("game_breakdowns", True,
                              "No game buttons available to tap", time.time() - start, [])

        games_to_test = game_buttons[:max_games]
        print(f"    → Found {len(game_buttons)} games, testing {len(games_to_test)}")

        for i, btn in enumerate(games_to_test):
            print(f"    → [{i+1}/{len(games_to_test)}] Tapping: {btn['text']}...")

            # Re-fetch My Matches for each game (bot edits message after tap)
            if i > 0:
                yg_msg = await _get_my_matches_msg(client)
                if not yg_msg:
                    checks.append(QualityCheck(event_id=btn['event_id'], match_title=btn['text'],
                                               issues=["COULD_NOT_RELOAD_MY_MATCHES"]))
                    continue

            # Click the game button
            result_msgs = await click_inline_button(client, yg_msg, btn['data'], wait=TIMEOUT_LONG)

            # Find the breakdown message (the one with 📋 or narrative text)
            breakdown_text = ""
            match_title = btn['text']
            for msg in result_msgs:
                if msg.text and ("📋" in msg.text or "The Setup" in msg.text):
                    breakdown_text = msg.text
                    # Try to extract match title from header
                    title_match = re.search(r'(?:⚽|🏉|🏏|🥊)\s+(.+?)\n', msg.text)
                    if title_match:
                        match_title = title_match.group(1).strip()
                    break
                # Also check for "Analysing" loading message that gets edited
                if msg.text and ("analysis" in msg.text.lower() or "vs" in msg.text):
                    breakdown_text = msg.text

            # Quality check
            qc = check_breakdown_quality(breakdown_text, btn['event_id'], match_title)
            checks.append(qc)

            if verbose:
                print(f"      Text preview: {breakdown_text[:200]}...")

            status = "✅ PASS" if qc.passed else f"❌ FAIL: {qc.issues}"
            print(f"      {status} | Setup: {qc.setup_sentences} sentences | Edge: {'✓' if qc.edge_has_content else '✗'}")

            # Wait between games to avoid rate limits
            if i < len(games_to_test) - 1:
                await asyncio.sleep(3)

        # Overall assessment
        passed_count = sum(1 for c in checks if c.passed)
        failed_count = sum(1 for c in checks if not c.passed)
        all_passed = failed_count == 0

        if not all_passed:
            failed_matches = [c.match_title for c in checks if not c.passed]
            failed_issues = [c.issues for c in checks if not c.passed]
            msg = f"{passed_count}/{len(checks)} passed. Failed: {failed_matches}. Issues: {failed_issues}"
        else:
            msg = f"All {passed_count} game breakdowns passed quality gate"

        return TestResult("game_breakdowns", all_passed, msg, time.time() - start, checks)

    except Exception as e:
        return TestResult("game_breakdowns", False, str(e), time.time() - start, checks)


async def test_no_terse_in_any_game(client: TelegramClient, verbose: bool = False) -> TestResult:
    """Specifically test that NO game breakdown has a terse Setup section."""
    start = time.time()
    checks: list[QualityCheck] = []

    try:
        yg_msg = await _get_my_matches_msg(client)

        if not yg_msg:
            return TestResult("no_terse", True, "No games available", time.time() - start, [])

        game_buttons = extract_game_buttons(yg_msg)[:5]  # Test up to 5 games

        for i, btn in enumerate(game_buttons):
            print(f"    → Terse check [{i+1}/{len(game_buttons)}]: {btn['text']}...")

            # Re-fetch My Matches for each game (bot edits message after tap)
            if i > 0:
                yg_msg = await _get_my_matches_msg(client)
                if not yg_msg:
                    continue

            result_msgs = await click_inline_button(client, yg_msg, btn['data'], wait=TIMEOUT_LONG)

            breakdown_text = ""
            for msg in result_msgs:
                if msg.text and ("📋" in msg.text or "The Setup" in msg.text):
                    breakdown_text = msg.text
                    break

            qc = check_breakdown_quality(breakdown_text, btn['event_id'], btn['text'])
            checks.append(qc)

            if "TERSE_SETUP" in qc.issues:
                print(f"      ❌ TERSE DETECTED: {btn['text']}")
                if verbose:
                    print(f"      Raw text: {breakdown_text[:300]}")
            else:
                print(f"      ✅ Narrative format OK ({qc.setup_sentences} sentences)")

            if i < len(game_buttons) - 1:
                await asyncio.sleep(3)

        terse_count = sum(1 for c in checks if "TERSE_SETUP" in c.issues)
        all_ok = terse_count == 0

        return TestResult(
            "no_terse", all_ok,
            f"{terse_count}/{len(checks)} games had terse setup" if not all_ok
            else f"All {len(checks)} games have narrative setups",
            time.time() - start, checks
        )

    except Exception as e:
        return TestResult("no_terse", False, str(e), time.time() - start, checks)


async def test_all_sections_present(client: TelegramClient) -> TestResult:
    """Test that all 4 sections (Setup, Edge, Risk, Verdict) are present in breakdowns."""
    start = time.time()
    checks: list[QualityCheck] = []

    try:
        yg_msg = await _get_my_matches_msg(client)

        if not yg_msg:
            return TestResult("all_sections", True, "No games available", time.time() - start, [])

        game_buttons = extract_game_buttons(yg_msg)[:3]

        for i, btn in enumerate(game_buttons):
            print(f"    → Section check [{i+1}/{len(game_buttons)}]: {btn['text']}...")

            if i > 0:
                yg_msg = await _get_my_matches_msg(client)
                if not yg_msg:
                    continue

            result_msgs = await click_inline_button(client, yg_msg, btn['data'], wait=TIMEOUT_LONG)

            breakdown_text = ""
            for msg in result_msgs:
                if msg.text and ("📋" in msg.text or "🎯" in msg.text):
                    breakdown_text = msg.text
                    break

            qc = check_breakdown_quality(breakdown_text, btn['event_id'], btn['text'])
            checks.append(qc)

            missing = []
            if not qc.has_setup: missing.append("Setup")
            if not qc.has_edge: missing.append("Edge")
            if not qc.has_risk: missing.append("Risk")
            if not qc.has_verdict: missing.append("Verdict")

            if missing:
                print(f"      ❌ Missing sections: {missing}")
            else:
                print(f"      ✅ All 4 sections present")

            if i < len(game_buttons) - 1:
                await asyncio.sleep(3)

        missing_count = sum(1 for c in checks if not (c.has_setup and c.has_edge and c.has_risk and c.has_verdict))
        all_ok = missing_count == 0

        return TestResult(
            "all_sections", all_ok,
            f"{missing_count} games missing sections" if not all_ok
            else f"All {len(checks)} games have all 4 sections",
            time.time() - start, checks
        )

    except Exception as e:
        return TestResult("all_sections", False, str(e), time.time() - start, checks)


async def test_edge_not_empty(client: TelegramClient) -> TestResult:
    """Test that Edge sections have actual content (not empty)."""
    start = time.time()
    checks: list[QualityCheck] = []

    try:
        yg_msg = await _get_my_matches_msg(client)

        if not yg_msg:
            return TestResult("edge_content", True, "No games available", time.time() - start, [])

        game_buttons = extract_game_buttons(yg_msg)[:3]

        for i, btn in enumerate(game_buttons):
            print(f"    → Edge check [{i+1}/{len(game_buttons)}]: {btn['text']}...")

            if i > 0:
                yg_msg = await _get_my_matches_msg(client)
                if not yg_msg:
                    continue

            result_msgs = await click_inline_button(client, yg_msg, btn['data'], wait=TIMEOUT_LONG)

            breakdown_text = ""
            for msg in result_msgs:
                if msg.text and ("📋" in msg.text or "🎯" in msg.text):
                    breakdown_text = msg.text
                    break

            qc = check_breakdown_quality(breakdown_text, btn['event_id'], btn['text'])
            checks.append(qc)

            if "EMPTY_EDGE" in qc.issues:
                print(f"      ❌ Edge section EMPTY")
            else:
                print(f"      ✅ Edge has content")

            if i < len(game_buttons) - 1:
                await asyncio.sleep(3)

        empty_count = sum(1 for c in checks if "EMPTY_EDGE" in c.issues)
        all_ok = empty_count == 0

        return TestResult(
            "edge_content", all_ok,
            f"{empty_count} games had empty Edge" if not all_ok
            else f"All {len(checks)} games have Edge content",
            time.time() - start, checks
        )

    except Exception as e:
        return TestResult("edge_content", False, str(e), time.time() - start, checks)


async def test_setup_has_minimum_sentences(client: TelegramClient) -> TestResult:
    """Test that Setup sections have at least 3 sentences."""
    start = time.time()
    checks: list[QualityCheck] = []

    try:
        yg_msg = await _get_my_matches_msg(client)

        if not yg_msg:
            return TestResult("setup_sentences", True, "No games available", time.time() - start, [])

        game_buttons = extract_game_buttons(yg_msg)[:3]

        for i, btn in enumerate(game_buttons):
            print(f"    → Sentence count [{i+1}/{len(game_buttons)}]: {btn['text']}...")

            if i > 0:
                yg_msg = await _get_my_matches_msg(client)
                if not yg_msg:
                    continue

            result_msgs = await click_inline_button(client, yg_msg, btn['data'], wait=TIMEOUT_LONG)

            breakdown_text = ""
            for msg in result_msgs:
                if msg.text and ("📋" in msg.text or "The Setup" in msg.text):
                    breakdown_text = msg.text
                    break

            qc = check_breakdown_quality(breakdown_text, btn['event_id'], btn['text'])
            checks.append(qc)

            if qc.setup_sentences < 3:
                print(f"      ❌ Only {qc.setup_sentences} sentences (need ≥3)")
            else:
                print(f"      ✅ {qc.setup_sentences} sentences")

            if i < len(game_buttons) - 1:
                await asyncio.sleep(3)

        short_count = sum(1 for c in checks if c.setup_sentences < 3)
        all_ok = short_count == 0

        return TestResult(
            "setup_sentences", all_ok,
            f"{short_count} games had <3 sentences in Setup" if not all_ok
            else f"All {len(checks)} games have 3+ sentences",
            time.time() - start, checks
        )

    except Exception as e:
        return TestResult("setup_sentences", False, str(e), time.time() - start, checks)


# ── Test Runner ──────────────────────────────────────────

ALL_TESTS = {
    "breakdowns": test_game_breakdowns_quality,
    "no_terse": test_no_terse_in_any_game,
    "all_sections": test_all_sections_present,
    "edge_content": test_edge_not_empty,
    "setup_sentences": test_setup_has_minimum_sentences,
}


async def run_tests(test_names: list[str] | None = None,
                    verbose: bool = False) -> list[TestResult]:
    """Run specified tests (or all if None)."""
    client = await get_client()
    results: list[TestResult] = []
    all_checks: list[QualityCheck] = []

    tests_to_run = test_names or list(ALL_TESTS.keys())

    print(f"\n{'=' * 60}")
    print(f"  MzansiEdge Quality Gate E2E Tests — {len(tests_to_run)} suites")
    print(f"{'=' * 60}\n")

    for name in tests_to_run:
        test_fn = ALL_TESTS.get(name)
        if not test_fn:
            print(f"  ⚠️  Unknown test: {name}")
            continue

        print(f"\n  ▶ Suite: {name}")
        print(f"  {'─' * 50}")

        # Some tests accept verbose param
        import inspect
        sig = inspect.signature(test_fn)
        if "verbose" in sig.parameters:
            result = await test_fn(client, verbose=verbose)
        else:
            result = await test_fn(client)

        results.append(result)
        all_checks.extend(result.quality_checks)

        icon = "✅" if result.passed else "❌"
        print(f"\n  {icon} {result.name}: {result.message} ({result.duration:.1f}s)")

        await asyncio.sleep(3)

    await client.disconnect()

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total_time = sum(r.duration for r in results)

    print(f"\n{'=' * 60}")
    print(f"  Test Suites: {passed} passed, {failed} failed ({total_time:.1f}s)")
    games_tested = len(set(c.event_id for c in all_checks if c.event_id))
    games_passed = len(set(c.event_id for c in all_checks if c.passed and c.event_id))
    print(f"  Game Breakdowns: {games_passed}/{games_tested} passed quality gate")
    print(f"{'=' * 60}\n")

    # Save report
    save_report(results, all_checks)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MzansiEdge Quality Gate E2E Tests")
    parser.add_argument("--test", nargs="*", help="Specific test suite(s) to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full narratives")
    args = parser.parse_args()

    results = asyncio.run(run_tests(args.test, verbose=args.verbose))
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
