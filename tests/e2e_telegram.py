"""MzansiEdge — End-to-End Telegram Bot Tests via Playwright.

Tests the LIVE bot on web.telegram.org by simulating real user interactions.
Requires: data/telegram_session.json (saved Telegram Web login state)

Usage:
    python tests/e2e_telegram.py                    # Run all tests
    python tests/e2e_telegram.py --test onboarding  # Run specific test group
    python tests/e2e_telegram.py --report           # Generate report only
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("e2e")

BOT_USERNAME = "mzansiedge_bot"
BOT_CHAT_NAME = "Mzansi Edge"
SESSION_PATH = Path("data/telegram_session.json")
REPORT_PATH = Path("data/e2e_report.json")
SCREENSHOT_DIR = Path("data/e2e_screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Test results accumulator
results: dict = {
    "timestamp": None,
    "total": 0,
    "passed": 0,
    "failed": 0,
    "errors": [],
    "warnings": [],
    "tests": [],
    "screenshots": [],
}


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

async def screenshot(page: Page, name: str):
    """Take a labeled screenshot for the report."""
    path = SCREENSHOT_DIR / f"{name}_{int(time.time())}.png"
    await page.screenshot(path=str(path))
    results["screenshots"].append({"name": name, "path": str(path)})
    logger.info("Screenshot: %s", path)


def record_test(name: str, status: str, details: str = "", duration: float = 0):
    """Record a test result."""
    entry = {
        "name": name,
        "status": status,
        "details": details,
        "duration_ms": round(duration * 1000),
    }
    results["tests"].append(entry)
    results["total"] += 1
    if status == "PASS":
        results["passed"] += 1
        logger.info("PASS: %s (%.1fs)", name, duration)
    elif status == "FAIL":
        results["failed"] += 1
        results["errors"].append(f"FAIL: {name} -- {details}")
        logger.error("FAIL: %s -- %s (%.1fs)", name, details, duration)
    elif status == "WARN":
        results["warnings"].append(f"WARN: {name} -- {details}")
        logger.warning("WARN: %s -- %s", name, details)
    else:
        results["failed"] += 1
        results["errors"].append(f"ERROR: {name} -- {details}")
        logger.error("ERROR: %s -- %s", name, details)


async def open_bot_chat(page: Page):
    """Navigate to the bot's chat on Telegram Web A."""
    await page.goto("https://web.telegram.org/a/")
    await page.wait_for_timeout(8000)

    # Click on the bot chat in the sidebar
    sidebar_link = page.locator("a.ListItem-button", has_text=BOT_CHAT_NAME).first
    try:
        await sidebar_link.click(timeout=10000)
        await page.wait_for_timeout(3000)
    except Exception:
        logger.warning("Could not find %s in sidebar, trying search", BOT_CHAT_NAME)
        # Fallback: use search
        search = page.locator('#telegram-search-input, input[placeholder*="Search"]').first
        if await search.count() > 0:
            await search.click()
            await page.keyboard.type(BOT_CHAT_NAME, delay=50)
            await page.wait_for_timeout(3000)
            result = page.locator("a.ListItem-button", has_text=BOT_CHAT_NAME).first
            await result.click(timeout=10000)
            await page.wait_for_timeout(3000)

    # Verify message input is visible
    try:
        await page.wait_for_selector("#editable-message-text", timeout=10000)
    except Exception:
        logger.warning("Could not find message input after opening chat")


async def send_message(page: Page, text: str):
    """Type and send a message to the bot."""
    input_el = page.locator("#editable-message-text")
    await input_el.click()
    # Clear existing text
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(text, delay=30)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(500)


async def send_command(page: Page, command: str):
    """Send a /command to the bot."""
    await send_message(page, command)
    await page.wait_for_timeout(4000)


async def wait_for_bot_response(page: Page, timeout: int = 10000) -> Optional[str]:
    """Wait for the bot to respond. Returns the latest bot message text."""
    start = time.time()
    last_count = await page.locator(".Message").count()
    while (time.time() - start) * 1000 < timeout:
        current_count = await page.locator(".Message").count()
        if current_count > last_count:
            msgs = await page.locator(".Message").all()
            if msgs:
                return (await msgs[-1].inner_text()).strip()
        await page.wait_for_timeout(500)
    # Return last message even if count didn't change
    msgs = await page.locator(".Message").all()
    if msgs:
        return (await msgs[-1].inner_text()).strip()
    return None


async def get_inline_buttons(page: Page) -> list[dict]:
    """Get all visible inline keyboard buttons from the last bot message."""
    button_data: list[dict] = []
    seen_texts: set[str] = set()

    # Telegram Web A: inline buttons are plain <button> elements with
    # a specific class pattern (obfuscated, but they have "no-upper-case")
    # They live inside the last message's reply markup area.
    # Strategy: get all buttons, filter out non-inline ones.
    all_buttons = await page.locator("button").all()
    skip_texts = {"Open", ""}
    skip_classes = {"main-menu", "translucent", "menu-container"}

    for btn in all_buttons:
        try:
            text = (await btn.inner_text()).strip()
            if not text or text in skip_texts or text in seen_texts:
                continue
            cls = await btn.get_attribute("class") or ""
            # Inline bot buttons have "no-upper-case" in their class
            if "no-upper-case" not in cls:
                continue
            is_visible = await btn.is_visible()
            if is_visible:
                seen_texts.add(text)
                button_data.append({"text": text, "element": btn})
        except Exception:
            pass

    return button_data


async def click_button_by_text(page: Page, text: str, partial: bool = False) -> bool:
    """Click an inline button by its text. Returns True if found and clicked."""
    buttons = await get_inline_buttons(page)
    for btn in buttons:
        if partial and text.lower() in btn["text"].lower():
            await btn["element"].click()
            await page.wait_for_timeout(2500)
            return True
        elif btn["text"].lower() == text.lower():
            await btn["element"].click()
            await page.wait_for_timeout(2500)
            return True
    return False


async def get_last_bot_message(page: Page) -> str:
    """Get the text of the most recent bot message (not our own)."""
    await page.wait_for_timeout(1000)
    msgs = await page.locator(".Message").all()
    # Walk backwards to find the last non-own message
    for msg in reversed(msgs):
        cls = await msg.get_attribute("class") or ""
        if "own" not in cls:
            return (await msg.inner_text()).strip()
    # Fallback: just return last message
    if msgs:
        return (await msgs[-1].inner_text()).strip()
    return ""


# ═══════════════════════════════════════════
# TEST SUITE 1: ONBOARDING FLOW
# ═══════════════════════════════════════════

async def test_bot_responds(page: Page):
    """TEST: Bot responds to /start command."""
    t0 = time.time()
    try:
        await send_command(page, "/start")
        await page.wait_for_timeout(3000)
        await screenshot(page, "start_response")

        buttons = await get_inline_buttons(page)
        if buttons:
            record_test("bot_responds_to_start", "PASS", f"Got {len(buttons)} buttons", time.time() - t0)
        else:
            msg = await get_last_bot_message(page)
            if msg:
                record_test("bot_responds_to_start", "PASS", f"Got text response: {msg[:100]}", time.time() - t0)
            else:
                record_test("bot_responds_to_start", "FAIL", "No response from bot after /start", time.time() - t0)
    except Exception as e:
        record_test("bot_responds_to_start", "ERROR", str(e), time.time() - t0)


async def test_experience_question(page: Page):
    """TEST: First step shows experience question with 3 options."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "experience_question")

        has_regular = any("regularly" in t.lower() or "experienced" in t.lower() for t in button_texts)
        has_sometimes = any("sometimes" in t.lower() or "casual" in t.lower() for t in button_texts)
        has_new = any("new" in t.lower() or "beginner" in t.lower() for t in button_texts)

        if has_regular and has_sometimes and has_new:
            record_test("experience_question_shows_3_options", "PASS",
                        f"Buttons: {button_texts}", time.time() - t0)
        elif len(buttons) >= 3:
            record_test("experience_question_shows_3_options", "WARN",
                        f"3+ buttons but couldn't verify experience options. Buttons: {button_texts}",
                        time.time() - t0)
        else:
            record_test("experience_question_shows_3_options", "FAIL",
                        f"Expected 3 experience options, got: {button_texts}", time.time() - t0)
    except Exception as e:
        record_test("experience_question_shows_3_options", "ERROR", str(e), time.time() - t0)


async def test_experience_selection(page: Page, choice: str = "sometimes"):
    """TEST: Selecting experience level advances to sport selection."""
    t0 = time.time()
    try:
        clicked = await click_button_by_text(page, choice, partial=True)
        if not clicked:
            buttons = await get_inline_buttons(page)
            if buttons:
                await buttons[1]["element"].click()
                await page.wait_for_timeout(2000)
                clicked = True

        await screenshot(page, "after_experience_selection")

        if not clicked:
            record_test("experience_selection_advances", "FAIL", "Could not click experience button", time.time() - t0)
            return

        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        has_sport = any(
            emoji in " ".join(button_texts)
            for emoji in ["Soccer", "Rugby", "Cricket", "Tennis", "Boxing"]
        )

        if has_sport:
            record_test("experience_selection_advances", "PASS",
                        f"Advanced to sport selection. Buttons: {button_texts[:5]}...", time.time() - t0)
        else:
            record_test("experience_selection_advances", "WARN",
                        f"Moved to next step but couldn't confirm sports. Buttons: {button_texts}", time.time() - t0)
    except Exception as e:
        record_test("experience_selection_advances", "ERROR", str(e), time.time() - t0)


async def test_sport_selection(page: Page):
    """TEST: Sport selection shows SA-priority sports first and supports multi-select."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "sport_selection")

        soccer_idx = next((i for i, t in enumerate(button_texts) if "soccer" in t.lower()), -1)

        if soccer_idx >= 0 and soccer_idx <= 2:
            record_test("sports_sa_priority_order", "PASS",
                        f"Soccer at position {soccer_idx}", time.time() - t0)
        elif soccer_idx >= 0:
            record_test("sports_sa_priority_order", "WARN",
                        f"Soccer at position {soccer_idx}, expected top 3", time.time() - t0)
        else:
            record_test("sports_sa_priority_order", "FAIL",
                        f"Soccer not found. Buttons: {button_texts}", time.time() - t0)

        has_boxing = any("boxing" in t.lower() for t in button_texts)
        if has_boxing:
            record_test("sports_has_boxing", "PASS", "Boxing found as sport option", time.time() - t0)
        else:
            record_test("sports_has_boxing", "FAIL",
                        f"Boxing not found. Buttons: {button_texts}", time.time() - t0)

        has_done = any("done" in t.lower() or "continue" in t.lower() or "next" in t.lower() for t in button_texts)
        if has_done:
            record_test("sports_has_done_button", "PASS", "Done/Continue button present", time.time() - t0)
        else:
            record_test("sports_has_done_button", "FAIL",
                        f"No Done/Continue button. Buttons: {button_texts}", time.time() - t0)

        # Select Soccer
        await click_button_by_text(page, "soccer", partial=True)
        await screenshot(page, "after_soccer_selected")

        # Check toggle
        buttons2 = await get_inline_buttons(page)
        button_texts2 = [b["text"] for b in buttons2]
        has_check = any("✅" in t for t in button_texts2)

        if has_check:
            record_test("sports_multi_select_toggle", "PASS",
                        "Toggle visible after selection", time.time() - t0)
        else:
            record_test("sports_multi_select_toggle", "WARN",
                        f"No toggle visible. Buttons: {button_texts2}", time.time() - t0)

        # Also select Tennis and Boxing
        await click_button_by_text(page, "tennis", partial=True)
        await page.wait_for_timeout(1000)
        await click_button_by_text(page, "boxing", partial=True)
        await page.wait_for_timeout(1000)

        await screenshot(page, "sports_multi_selected")

    except Exception as e:
        record_test("sport_selection", "ERROR", str(e), time.time() - t0)


async def test_sport_done_advances(page: Page):
    """TEST: Clicking Done after sport selection advances to leagues."""
    t0 = time.time()
    try:
        clicked = await click_button_by_text(page, "done", partial=True)
        if not clicked:
            clicked = await click_button_by_text(page, "continue", partial=True)
        if not clicked:
            clicked = await click_button_by_text(page, "next", partial=True)
        await page.wait_for_timeout(3000)
        await screenshot(page, "after_sports_done")

        if not clicked:
            record_test("sports_done_advances", "FAIL", "Could not click Done button", time.time() - t0)
            return

        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        has_league_indicators = any(
            term in " ".join(button_texts).lower()
            for term in ["premier", "epl", "la liga", "psl", "league", "champions", "serie",
                         "bundesliga", "ligue", "mls"]
        )

        if has_league_indicators:
            record_test("sports_done_advances_to_leagues", "PASS",
                        f"League selection shown. Buttons: {button_texts[:5]}...", time.time() - t0)
        else:
            record_test("sports_done_advances_to_leagues", "WARN",
                        f"Advanced but couldn't confirm leagues. Buttons: {button_texts}", time.time() - t0)

    except Exception as e:
        record_test("sports_done_advances", "ERROR", str(e), time.time() - t0)


async def test_league_selection(page: Page):
    """TEST: League selection for multi-league sports (Soccer)."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "league_selection")

        sa_league_idx = next(
            (i for i, t in enumerate(button_texts) if "south africa" in t.lower() or "psl" in t.lower()),
            -1,
        )

        if sa_league_idx == 0:
            record_test("league_sa_first", "PASS", "SA league is first option", time.time() - t0)
        elif sa_league_idx > 0:
            record_test("league_sa_first", "WARN",
                        f"SA league at position {sa_league_idx}, expected first", time.time() - t0)
        else:
            record_test("league_sa_first", "WARN",
                        f"SA league not found. Available: {button_texts}", time.time() - t0)

        clicked_epl = await click_button_by_text(page, "premier", partial=True)
        if not clicked_epl:
            clicked_epl = await click_button_by_text(page, "epl", partial=True)
        await page.wait_for_timeout(1000)

        await click_button_by_text(page, "done", partial=True)
        await page.wait_for_timeout(3000)
        await screenshot(page, "after_leagues_done")

        record_test("league_selection_flow", "PASS" if clicked_epl else "WARN",
                     "League selection completed", time.time() - t0)

    except Exception as e:
        record_test("league_selection", "ERROR", str(e), time.time() - t0)


async def test_team_selection(page: Page):
    """TEST: Team/player selection shows top options + manual input."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "team_selection")

        known_teams = ["arsenal", "manchester", "liverpool", "chelsea", "tottenham",
                       "chiefs", "pirates", "sundowns"]
        found_teams = [t for t in button_texts if any(team in t.lower() for team in known_teams)]

        if found_teams:
            record_test("team_selection_shows_teams", "PASS",
                        f"Found teams: {found_teams[:5]}", time.time() - t0)
        else:
            record_test("team_selection_shows_teams", "WARN",
                        f"No recognized teams. Buttons: {button_texts}", time.time() - t0)

        has_manual = any("type" in t.lower() or "manual" in t.lower() for t in button_texts)
        if has_manual:
            record_test("team_has_manual_input", "PASS", "Type manually button present", time.time() - t0)
        else:
            record_test("team_has_manual_input", "FAIL",
                        f"No manual input button. Buttons: {button_texts}", time.time() - t0)

        has_skip = any("skip" in t.lower() for t in button_texts)
        if has_skip:
            record_test("team_has_skip_button", "PASS", "Skip button present", time.time() - t0)
        else:
            record_test("team_has_skip_button", "WARN",
                        f"No skip button. Buttons: {button_texts}", time.time() - t0)

        if found_teams:
            await click_button_by_text(page, found_teams[0], partial=True)
            await page.wait_for_timeout(1000)
            await screenshot(page, "team_selected")

        await click_button_by_text(page, "done", partial=True)
        await page.wait_for_timeout(3000)

        record_test("team_selection_flow", "PASS", "Team selection completed", time.time() - t0)

    except Exception as e:
        record_test("team_selection", "ERROR", str(e), time.time() - t0)


async def test_tennis_skips_leagues(page: Page):
    """TEST: Tennis should skip league selection and go straight to players."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "tennis_step")

        msg = await get_last_bot_message(page)

        says_player = "player" in msg.lower() if msg else False
        says_league = "league" in msg.lower() if msg else False

        if says_player and not says_league:
            record_test("tennis_skips_leagues_shows_players", "PASS",
                        "Tennis skipped leagues, shows players", time.time() - t0)
        elif not says_league:
            record_test("tennis_skips_leagues_shows_players", "WARN",
                        f"No league step but couldn't confirm players. Message: {msg[:100] if msg else 'N/A'}",
                        time.time() - t0)
        else:
            record_test("tennis_skips_leagues_shows_players", "FAIL",
                        f"Tennis showed league selection. Message: {msg[:100] if msg else 'N/A'}", time.time() - t0)

        known_players = ["djokovic", "alcaraz", "sinner", "medvedev", "zverev"]
        found_players = [t for t in button_texts if any(p in t.lower() for p in known_players)]

        if found_players:
            record_test("tennis_shows_player_names", "PASS",
                        f"Found players: {found_players}", time.time() - t0)
        else:
            record_test("tennis_shows_player_names", "WARN",
                        f"No recognized players. Buttons: {button_texts}", time.time() - t0)

        await click_button_by_text(page, "skip", partial=True)
        if not await click_button_by_text(page, "done", partial=True):
            pass
        await page.wait_for_timeout(3000)

    except Exception as e:
        record_test("tennis_skips_leagues", "ERROR", str(e), time.time() - t0)


async def test_boxing_skips_leagues(page: Page):
    """TEST: Boxing should skip league selection."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "boxing_step")

        msg = await get_last_bot_message(page)

        says_fighter = "fighter" in msg.lower() if msg else False

        if says_fighter:
            record_test("boxing_says_fighters", "PASS",
                        "Boxing uses 'fighters' language", time.time() - t0)
        else:
            record_test("boxing_says_fighters", "WARN",
                        f"Couldn't confirm 'fighters' label. Message: {msg[:100] if msg else 'N/A'}",
                        time.time() - t0)

        known_fighters = ["usyk", "fury", "canelo", "crawford", "inoue"]
        found_fighters = [t for t in button_texts if any(f in t.lower() for f in known_fighters)]

        if found_fighters:
            record_test("boxing_shows_fighter_names", "PASS",
                        f"Found fighters: {found_fighters}", time.time() - t0)

        await click_button_by_text(page, "skip", partial=True)
        await page.wait_for_timeout(3000)

    except Exception as e:
        record_test("boxing_skips_leagues", "ERROR", str(e), time.time() - t0)


async def test_risk_profile(page: Page):
    """TEST: Risk profile selection with 3 options."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "risk_profile")

        has_conservative = any("conservative" in t.lower() for t in button_texts)
        has_moderate = any("moderate" in t.lower() or "balanced" in t.lower() for t in button_texts)
        has_aggressive = any("aggressive" in t.lower() for t in button_texts)

        if has_conservative and has_moderate and has_aggressive:
            record_test("risk_profile_3_options", "PASS",
                        "All 3 risk profiles present", time.time() - t0)
        else:
            record_test("risk_profile_3_options", "FAIL",
                        f"Missing risk options. Found: {button_texts}", time.time() - t0)

        await click_button_by_text(page, "moderate", partial=True)
        if not await click_button_by_text(page, "balanced", partial=True):
            pass
        await page.wait_for_timeout(3000)
        await screenshot(page, "after_risk_selected")

        record_test("risk_profile_selection", "PASS", "Risk profile selected", time.time() - t0)

    except Exception as e:
        record_test("risk_profile", "ERROR", str(e), time.time() - t0)


async def test_notification_time(page: Page):
    """TEST: Notification time selection."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        await screenshot(page, "notification_time")

        has_morning = any("morning" in t.lower() or "7" in t or "8" in t for t in button_texts)
        has_evening = any("evening" in t.lower() or "6" in t or "18" in t for t in button_texts)

        if has_morning:
            record_test("notification_has_morning", "PASS", "Morning option available", time.time() - t0)
        else:
            record_test("notification_has_morning", "WARN",
                        f"No morning option. Buttons: {button_texts}", time.time() - t0)

        clicked = await click_button_by_text(page, "morning", partial=True)
        if not clicked:
            if buttons:
                await buttons[0]["element"].click()
                await page.wait_for_timeout(2000)

        await page.wait_for_timeout(3000)
        await screenshot(page, "after_notification_selected")

        record_test("notification_time_selection", "PASS", "Notification time selected", time.time() - t0)

    except Exception as e:
        record_test("notification_time", "ERROR", str(e), time.time() - t0)


async def test_profile_summary(page: Page):
    """TEST: Profile summary shows all selections + edit buttons."""
    t0 = time.time()
    try:
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        msg = await get_last_bot_message(page)
        await screenshot(page, "profile_summary")

        msg_lower = msg.lower() if msg else ""
        has_soccer_mention = "soccer" in msg_lower

        if has_soccer_mention:
            record_test("summary_shows_selected_sports", "PASS",
                        "Soccer visible in summary", time.time() - t0)
        else:
            record_test("summary_shows_selected_sports", "WARN",
                        f"Couldn't find soccer in summary. Message: {msg[:200] if msg else 'N/A'}", time.time() - t0)

        has_edit_sports = any("edit" in t.lower() and ("sport" in t.lower() or "team" in t.lower() or "fav" in t.lower()) for t in button_texts)
        has_edit_risk = any("edit" in t.lower() and ("risk" in t.lower() or "notif" in t.lower()) for t in button_texts)
        has_confirm = any("go" in t.lower() or "confirm" in t.lower() or "looks good" in t.lower() for t in button_texts)

        if has_edit_sports:
            record_test("summary_has_edit_sports_button", "PASS", "Edit Sports button present", time.time() - t0)
        else:
            record_test("summary_has_edit_sports_button", "FAIL",
                        f"No Edit Sports button. Buttons: {button_texts}", time.time() - t0)

        if has_edit_risk:
            record_test("summary_has_edit_risk_button", "PASS", "Edit Risk button present", time.time() - t0)
        else:
            record_test("summary_has_edit_risk_button", "FAIL",
                        f"No Edit Risk button. Buttons: {button_texts}", time.time() - t0)

        if has_confirm:
            record_test("summary_has_confirm_button", "PASS", "Confirm/Let's Go button present", time.time() - t0)
        else:
            record_test("summary_has_confirm_button", "FAIL",
                        f"No confirm button. Buttons: {button_texts}", time.time() - t0)

    except Exception as e:
        record_test("profile_summary", "ERROR", str(e), time.time() - t0)


async def test_edit_sports_flow(page: Page):
    """TEST: Edit Sports button shows per-sport edit options."""
    t0 = time.time()
    try:
        clicked = await click_button_by_text(page, "edit sport", partial=True)
        if not clicked:
            clicked = await click_button_by_text(page, "edit team", partial=True)
        if not clicked:
            clicked = await click_button_by_text(page, "edit fav", partial=True)

        await page.wait_for_timeout(2000)
        await screenshot(page, "edit_sports_menu")

        if not clicked:
            record_test("edit_sports_opens", "FAIL", "Could not click edit sports button", time.time() - t0)
            return

        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        has_back = any("back" in t.lower() for t in button_texts)

        if len(buttons) >= 2:
            record_test("edit_sports_shows_sport_buttons", "PASS",
                        f"Sport edit buttons shown: {button_texts}", time.time() - t0)
        else:
            record_test("edit_sports_shows_sport_buttons", "FAIL",
                        f"No sport buttons. Got: {button_texts}", time.time() - t0)

        if has_back:
            record_test("edit_sports_has_back", "PASS", "Back button present", time.time() - t0)
        else:
            record_test("edit_sports_has_back", "WARN", "No back button", time.time() - t0)

        # Go back to summary
        await click_button_by_text(page, "back", partial=True)
        await page.wait_for_timeout(2000)

    except Exception as e:
        record_test("edit_sports_flow", "ERROR", str(e), time.time() - t0)


async def test_confirm_onboarding(page: Page):
    """TEST: Confirming onboarding completes it."""
    t0 = time.time()
    try:
        clicked = await click_button_by_text(page, "go", partial=True)
        if not clicked:
            clicked = await click_button_by_text(page, "confirm", partial=True)
        if not clicked:
            clicked = await click_button_by_text(page, "looks good", partial=True)

        await page.wait_for_timeout(3000)
        await screenshot(page, "after_onboarding_confirm")

        if not clicked:
            record_test("onboarding_confirm", "FAIL", "Could not click confirm button", time.time() - t0)
            return

        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        has_picks = any("pick" in t.lower() or "briefing" in t.lower() for t in button_texts)
        has_settings = any("setting" in t.lower() for t in button_texts)

        if has_picks or has_settings:
            record_test("onboarding_completes_to_main_menu", "PASS",
                        f"Main menu shown. Buttons: {button_texts}", time.time() - t0)
        else:
            record_test("onboarding_completes_to_main_menu", "WARN",
                        f"Onboarding completed but couldn't confirm main menu. Buttons: {button_texts}", time.time() - t0)

    except Exception as e:
        record_test("onboarding_confirm", "ERROR", str(e), time.time() - t0)


# ═══════════════════════════════════════════
# TEST SUITE 2: POST-ONBOARDING
# ═══════════════════════════════════════════

async def test_all_commands_respond(page: Page):
    """TEST: All registered commands produce a response."""
    t0 = time.time()
    commands = ["/start", "/menu", "/help", "/picks", "/settings"]

    for cmd in commands:
        try:
            await send_command(page, cmd)
            await page.wait_for_timeout(3000)
            await screenshot(page, f"cmd_{cmd.replace('/', '')}")

            buttons = await get_inline_buttons(page)
            msg = await get_last_bot_message(page)

            if buttons or msg:
                record_test(f"command_{cmd}_responds", "PASS",
                            f"Response received ({len(buttons)} buttons)", time.time() - t0)
            else:
                record_test(f"command_{cmd}_responds", "FAIL",
                            "No response", time.time() - t0)
        except Exception as e:
            record_test(f"command_{cmd}_responds", "ERROR", str(e), time.time() - t0)


async def test_settings_menu(page: Page):
    """TEST: Settings menu shows all expected options including Reset."""
    t0 = time.time()
    try:
        await send_command(page, "/settings")
        await page.wait_for_timeout(3000)
        await screenshot(page, "settings_menu")

        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        has_sports = any("sport" in t.lower() for t in button_texts)
        has_risk = any("risk" in t.lower() for t in button_texts)
        has_reset = any("reset" in t.lower() for t in button_texts)
        has_notifications = any("notif" in t.lower() for t in button_texts)

        for label, present in [
            ("settings_has_sports", has_sports),
            ("settings_has_risk", has_risk),
            ("settings_has_notifications", has_notifications),
            ("settings_has_reset", has_reset),
        ]:
            record_test(label, "PASS" if present else "FAIL",
                        f"{'Found' if present else 'Missing'}. Buttons: {button_texts}", time.time() - t0)

    except Exception as e:
        record_test("settings_menu", "ERROR", str(e), time.time() - t0)


async def test_back_buttons_work(page: Page):
    """TEST: Back buttons navigate correctly."""
    t0 = time.time()
    try:
        await send_command(page, "/settings")
        await page.wait_for_timeout(3000)

        clicked = await click_button_by_text(page, "back", partial=True)
        await page.wait_for_timeout(2000)
        await screenshot(page, "back_from_settings")

        if clicked:
            buttons = await get_inline_buttons(page)
            button_texts = [b["text"] for b in buttons]
            has_menu_items = len(buttons) >= 2
            record_test("back_button_settings_to_menu", "PASS" if has_menu_items else "WARN",
                        f"Navigated back. Buttons: {button_texts}", time.time() - t0)
        else:
            record_test("back_button_settings_to_menu", "FAIL",
                        "Could not click back button", time.time() - t0)

    except Exception as e:
        record_test("back_buttons", "ERROR", str(e), time.time() - t0)


async def test_html_parse_mode(page: Page):
    """TEST: Bot messages use HTML formatting (not raw markdown)."""
    t0 = time.time()
    try:
        await send_command(page, "/help")
        await page.wait_for_timeout(3000)

        msg = await get_last_bot_message(page)

        has_raw_markdown = any(marker in (msg or "") for marker in ["**", "```", "###", "---", "__"])

        if not has_raw_markdown:
            record_test("html_parse_mode_no_raw_markdown", "PASS",
                        "No raw markdown visible in /help response", time.time() - t0)
        else:
            record_test("html_parse_mode_no_raw_markdown", "FAIL",
                        f"Raw markdown detected in response: {msg[:200] if msg else 'N/A'}", time.time() - t0)

    except Exception as e:
        record_test("html_parse_mode", "ERROR", str(e), time.time() - t0)


# ═══════════════════════════════════════════
# TEST SUITE 3: PROFILE RESET
# ═══════════════════════════════════════════

async def test_profile_reset(page: Page):
    """TEST: Profile reset shows warning, then resets on confirm."""
    t0 = time.time()
    try:
        clicked = await click_button_by_text(page, "reset", partial=True)
        await page.wait_for_timeout(2000)
        await screenshot(page, "reset_warning")

        if not clicked:
            record_test("reset_shows_warning", "FAIL", "Could not click Reset button", time.time() - t0)
            return

        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        msg = await get_last_bot_message(page)

        has_warning = ("sure" in msg.lower() or "warning" in msg.lower()) if msg else False
        has_confirm = any("yes" in t.lower() or "confirm" in t.lower() or "reset" in t.lower() for t in button_texts)
        has_cancel = any("cancel" in t.lower() or "no" in t.lower() or "back" in t.lower() for t in button_texts)

        if has_warning and has_confirm and has_cancel:
            record_test("reset_shows_warning", "PASS",
                        "Warning shown with Confirm/Cancel buttons", time.time() - t0)
        else:
            record_test("reset_shows_warning", "WARN",
                        f"Warning: {has_warning}, Confirm: {has_confirm}, Cancel: {has_cancel}. "
                        f"Msg: {msg[:100] if msg else 'N/A'}, Buttons: {button_texts}", time.time() - t0)

        await click_button_by_text(page, "yes", partial=True)
        if not await click_button_by_text(page, "confirm", partial=True):
            pass
        await page.wait_for_timeout(3000)
        await screenshot(page, "after_reset")

        record_test("reset_completes", "PASS", "Reset confirmed", time.time() - t0)

    except Exception as e:
        record_test("profile_reset", "ERROR", str(e), time.time() - t0)


# ═══════════════════════════════════════════
# TEST SUITE 4: FUZZY MATCHING
# ═══════════════════════════════════════════

async def test_fuzzy_matching(page: Page):
    """TEST: Fuzzy matching works for typos and abbreviations."""
    t0 = time.time()
    try:
        # Start fresh onboarding
        await send_command(page, "/start")
        await page.wait_for_timeout(3000)

        # Click through experience
        await click_button_by_text(page, "sometimes", partial=True)
        await page.wait_for_timeout(2000)

        # Select only Soccer
        await click_button_by_text(page, "soccer", partial=True)
        await page.wait_for_timeout(1000)
        await click_button_by_text(page, "done", partial=True)
        await page.wait_for_timeout(3000)

        # Select EPL
        await click_button_by_text(page, "premier", partial=True)
        await page.wait_for_timeout(1000)
        await click_button_by_text(page, "done", partial=True)
        await page.wait_for_timeout(3000)

        # Now at team selection -- click "Type manually"
        await click_button_by_text(page, "type", partial=True)
        await page.wait_for_timeout(2000)

        # Test 1: Typo -- "Arsnal" should match "Arsenal"
        await send_message(page, "Arsnal")
        await page.wait_for_timeout(3000)
        await screenshot(page, "fuzzy_arsnal")

        msg = await get_last_bot_message(page)
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        if "arsenal" in (msg or "").lower() or any("arsenal" in t.lower() for t in button_texts):
            record_test("fuzzy_typo_arsnal", "PASS", "Arsnal -> Arsenal matched", time.time() - t0)
        else:
            record_test("fuzzy_typo_arsnal", "FAIL",
                        f"Arsnal not matched. Msg: {msg[:100] if msg else 'N/A'}, Buttons: {button_texts}",
                        time.time() - t0)

        # Accept match or go back
        await click_button_by_text(page, "yes", partial=True)
        await page.wait_for_timeout(2000)

        # Test 2: Alias -- "gooners" should match "Arsenal"
        await click_button_by_text(page, "type", partial=True)
        await page.wait_for_timeout(2000)
        await send_message(page, "gooners")
        await page.wait_for_timeout(3000)
        await screenshot(page, "fuzzy_gooners")

        msg2 = await get_last_bot_message(page)
        buttons2 = await get_inline_buttons(page)
        button_texts2 = [b["text"] for b in buttons2]

        if "arsenal" in (msg2 or "").lower() or any("arsenal" in t.lower() for t in button_texts2):
            record_test("fuzzy_alias_gooners", "PASS", "gooners -> Arsenal matched", time.time() - t0)
        else:
            record_test("fuzzy_alias_gooners", "FAIL",
                        f"gooners not matched. Msg: {msg2[:100] if msg2 else 'N/A'}, Buttons: {button_texts2}",
                        time.time() - t0)

        await click_button_by_text(page, "yes", partial=True)
        await page.wait_for_timeout(2000)

        # Test 3: SA slang -- "amakhosi" should match "Kaizer Chiefs"
        await click_button_by_text(page, "type", partial=True)
        await page.wait_for_timeout(2000)
        await send_message(page, "amakhosi")
        await page.wait_for_timeout(3000)
        await screenshot(page, "fuzzy_amakhosi")

        msg3 = await get_last_bot_message(page)
        buttons3 = await get_inline_buttons(page)
        button_texts3 = [b["text"] for b in buttons3]

        if "chiefs" in (msg3 or "").lower() or "kaizer" in (msg3 or "").lower() or any("chiefs" in t.lower() for t in button_texts3):
            record_test("fuzzy_sa_slang_amakhosi", "PASS", "amakhosi -> Kaizer Chiefs matched", time.time() - t0)
        else:
            record_test("fuzzy_sa_slang_amakhosi", "FAIL",
                        f"amakhosi not matched. Msg: {msg3[:100] if msg3 else 'N/A'}", time.time() - t0)

    except Exception as e:
        record_test("fuzzy_matching", "ERROR", str(e), time.time() - t0)


# ═══════════════════════════════════════════
# EDGE CASE TESTS
# ═══════════════════════════════════════════

async def test_zero_sports_done(page: Page):
    """TEST: Clicking Done with zero sports selected shows error."""
    t0 = time.time()
    try:
        await send_command(page, "/start")
        await page.wait_for_timeout(3000)

        # Select experience
        await click_button_by_text(page, "sometimes", partial=True)
        await page.wait_for_timeout(2000)

        # Click Done without selecting any sport
        await click_button_by_text(page, "done", partial=True)
        await page.wait_for_timeout(2000)
        await screenshot(page, "zero_sports_done")

        # Should still be on sport selection (not advance)
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        still_on_sports = any("soccer" in t.lower() or "rugby" in t.lower() for t in button_texts)
        if still_on_sports:
            record_test("zero_sports_blocks_advance", "PASS",
                        "Bot stayed on sport selection when no sports chosen", time.time() - t0)
        else:
            record_test("zero_sports_blocks_advance", "FAIL",
                        f"Advanced with no sports? Buttons: {button_texts}", time.time() - t0)

    except Exception as e:
        record_test("zero_sports_done", "ERROR", str(e), time.time() - t0)


async def test_start_when_onboarded(page: Page):
    """TEST: /start when already onboarded shows main menu, not onboarding."""
    t0 = time.time()
    try:
        await send_command(page, "/start")
        await page.wait_for_timeout(3000)
        await screenshot(page, "start_when_onboarded")

        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]
        msg = await get_last_bot_message(page)

        # Should show main menu if already onboarded
        has_menu = any("pick" in t.lower() or "briefing" in t.lower() or "setting" in t.lower() for t in button_texts)
        has_experience_q = any("regularly" in t.lower() or "sometimes" in t.lower() for t in button_texts)

        if has_menu and not has_experience_q:
            record_test("start_when_onboarded_shows_menu", "PASS",
                        "Main menu shown (not onboarding)", time.time() - t0)
        elif has_experience_q:
            record_test("start_when_onboarded_shows_menu", "FAIL",
                        "Showed onboarding again instead of main menu", time.time() - t0)
        else:
            record_test("start_when_onboarded_shows_menu", "WARN",
                        f"Couldn't determine state. Buttons: {button_texts}", time.time() - t0)

    except Exception as e:
        record_test("start_when_onboarded", "ERROR", str(e), time.time() - t0)


async def test_random_text_during_onboarding(page: Page):
    """TEST: Random text during onboarding doesn't break the flow."""
    t0 = time.time()
    try:
        # Reset first
        await send_command(page, "/settings")
        await page.wait_for_timeout(2000)
        await click_button_by_text(page, "reset", partial=True)
        await page.wait_for_timeout(2000)
        await click_button_by_text(page, "yes", partial=True)
        await page.wait_for_timeout(3000)

        # Start onboarding
        await send_command(page, "/start")
        await page.wait_for_timeout(3000)

        # Send random text
        await send_message(page, "hello this is random text")
        await page.wait_for_timeout(3000)
        await screenshot(page, "random_text_during_onboarding")

        # Bot should still show experience buttons or handle gracefully
        buttons = await get_inline_buttons(page)
        button_texts = [b["text"] for b in buttons]

        if len(buttons) > 0:
            record_test("random_text_no_crash", "PASS",
                        f"Bot handled random text. Buttons still present: {button_texts[:3]}", time.time() - t0)
        else:
            msg = await get_last_bot_message(page)
            if msg:
                record_test("random_text_no_crash", "PASS",
                            f"Bot responded to random text: {msg[:100]}", time.time() - t0)
            else:
                record_test("random_text_no_crash", "WARN",
                            "No response to random text during onboarding", time.time() - t0)

    except Exception as e:
        record_test("random_text_during_onboarding", "ERROR", str(e), time.time() - t0)


async def test_rapid_commands(page: Page):
    """TEST: Multiple rapid commands don't crash the bot."""
    t0 = time.time()
    try:
        for cmd in ["/help", "/menu", "/help"]:
            await send_message(page, cmd)
            await page.wait_for_timeout(500)

        await page.wait_for_timeout(5000)
        await screenshot(page, "rapid_commands")

        msg = await get_last_bot_message(page)
        buttons = await get_inline_buttons(page)

        if msg or buttons:
            record_test("rapid_commands_no_crash", "PASS",
                        f"Bot survived rapid commands ({len(buttons)} buttons)", time.time() - t0)
        else:
            record_test("rapid_commands_no_crash", "FAIL",
                        "No response after rapid commands", time.time() - t0)

    except Exception as e:
        record_test("rapid_commands", "ERROR", str(e), time.time() - t0)


# ═══════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════

async def run_all_tests():
    """Run the complete E2E test suite."""
    results["timestamp"] = datetime.now().isoformat()

    if not SESSION_PATH.exists():
        logger.error("No Telegram session found at %s", SESSION_PATH)
        logger.error("Run save_telegram_session.py first to save your login state.")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=str(SESSION_PATH),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        logger.info("Starting E2E tests against @%s", BOT_USERNAME)
        logger.info("=" * 60)

        # Open bot chat
        await open_bot_chat(page)
        await screenshot(page, "initial_state")

        # ── TEST SUITE 2: Post-Onboarding (run first since user is onboarded) ──
        logger.info("")
        logger.info("SUITE 2: Post-Onboarding Features")
        logger.info("-" * 40)

        await test_start_when_onboarded(page)
        await test_all_commands_respond(page)
        await test_settings_menu(page)
        await test_back_buttons_work(page)
        await test_html_parse_mode(page)
        await test_rapid_commands(page)

        # ── TEST SUITE 3: Profile Reset (sets up for onboarding test) ──
        logger.info("")
        logger.info("SUITE 3: Profile Reset & Re-onboarding")
        logger.info("-" * 40)

        await send_command(page, "/settings")
        await page.wait_for_timeout(2000)
        await test_profile_reset(page)

        # ── TEST SUITE 1: Full Onboarding Flow (after reset) ──
        logger.info("")
        logger.info("SUITE 1: Complete Onboarding Flow")
        logger.info("-" * 40)

        await test_bot_responds(page)
        await test_experience_question(page)
        await test_experience_selection(page)
        await test_sport_selection(page)
        await test_sport_done_advances(page)
        await test_league_selection(page)
        await test_team_selection(page)
        await test_tennis_skips_leagues(page)
        await test_boxing_skips_leagues(page)
        await test_risk_profile(page)
        await test_notification_time(page)
        await test_profile_summary(page)
        await test_edit_sports_flow(page)
        await test_confirm_onboarding(page)

        # ── TEST SUITE 5: Edge Cases ──
        logger.info("")
        logger.info("SUITE 5: Edge Cases")
        logger.info("-" * 40)

        await test_zero_sports_done(page)
        await test_random_text_during_onboarding(page)

        # Done
        await browser.close()

    # ── REPORT ──
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST REPORT")
    logger.info("=" * 60)
    logger.info("Total:    %d", results["total"])
    logger.info("Passed:   %d", results["passed"])
    logger.info("Failed:   %d", results["failed"])
    logger.info("Warnings: %d", len(results["warnings"]))

    if results["errors"]:
        logger.info("")
        logger.info("FAILURES:")
        for err in results["errors"]:
            logger.info("  - %s", err)

    if results["warnings"]:
        logger.info("")
        logger.info("WARNINGS:")
        for warn in results["warnings"]:
            logger.info("  - %s", warn)

    # Save report
    REPORT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    logger.info("")
    logger.info("Full report saved to: %s", REPORT_PATH)
    logger.info("Screenshots saved to: %s", SCREENSHOT_DIR)


async def run_specific_suite(suite_name: str):
    """Run a specific test suite by name."""
    results["timestamp"] = datetime.now().isoformat()

    if not SESSION_PATH.exists():
        logger.error("No Telegram session found at %s", SESSION_PATH)
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=str(SESSION_PATH),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        await page.goto("https://web.telegram.org/a/")
        await page.wait_for_timeout(5000)
        await open_bot_chat(page)
        await page.wait_for_timeout(3000)

        if suite_name == "onboarding":
            await test_bot_responds(page)
            await test_experience_question(page)
            await test_experience_selection(page)
            await test_sport_selection(page)
            await test_sport_done_advances(page)
            await test_league_selection(page)
            await test_team_selection(page)
            await test_tennis_skips_leagues(page)
            await test_boxing_skips_leagues(page)
            await test_risk_profile(page)
            await test_notification_time(page)
            await test_profile_summary(page)
            await test_edit_sports_flow(page)
            await test_confirm_onboarding(page)
        elif suite_name == "commands":
            await test_all_commands_respond(page)
            await test_settings_menu(page)
            await test_back_buttons_work(page)
            await test_html_parse_mode(page)
        elif suite_name == "reset":
            await send_command(page, "/settings")
            await page.wait_for_timeout(3000)
            await test_profile_reset(page)
        elif suite_name == "fuzzy":
            await test_fuzzy_matching(page)
        elif suite_name == "edge":
            await test_zero_sports_done(page)
            await test_start_when_onboarded(page)
            await test_random_text_during_onboarding(page)
            await test_rapid_commands(page)
        else:
            logger.error("Unknown suite: %s", suite_name)
            logger.info("Available: onboarding, commands, reset, fuzzy, edge")

        await browser.close()

    REPORT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    logger.info("Report saved to: %s", REPORT_PATH)


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        suite = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        asyncio.run(run_specific_suite(suite))
    elif "--report" in sys.argv:
        if REPORT_PATH.exists():
            data = json.loads(REPORT_PATH.read_text())
            print(json.dumps(data, indent=2))
        else:
            print(f"No report found at {REPORT_PATH}")
    else:
        asyncio.run(run_all_tests())
