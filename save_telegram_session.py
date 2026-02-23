"""Save Telegram Web login state for E2E tests.

Run this ONCE interactively to save cookies + localStorage.
After saving, all subsequent tests run headless using the saved session.

Usage:
    python save_telegram_session.py
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

SESSION_PATH = Path("data/telegram_session.json")
SESSION_PATH.parent.mkdir(exist_ok=True)


async def save_session():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://web.telegram.org/a/")
        print("\n" + "=" * 60)
        print(">>> LOG IN TO TELEGRAM MANUALLY <<<")
        print(">>> Once logged in and you see your chats, press Enter here <<<")
        print("=" * 60 + "\n")
        input("Press Enter when ready...")

        await context.storage_state(path=str(SESSION_PATH))
        print(f"\nSession saved to {SESSION_PATH}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(save_session())
