"""Save Telethon session string for E2E tests.

Run this ONCE interactively to authenticate with Telegram.
After saving, all subsequent E2E tests run automatically using the saved session.

Usage:
    python save_telethon_session.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
SESSION_PATH.parent.mkdir(exist_ok=True)


async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()

    session_str = client.session.save()
    SESSION_PATH.write_text(session_str)
    print(f"\nSession saved to {SESSION_PATH}")
    print(f"Session string length: {len(session_str)}")

    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")

    await client.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
