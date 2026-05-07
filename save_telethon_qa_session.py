"""Save Telethon session string for the dedicated QA test account.

Run this ONCE interactively after Paul creates the QA Telegram account.
All QA harnesses will then use telethon_qa_session instead of Paul's personal session.

Usage:
    python save_telethon_qa_session.py

Prerequisites:
    1. Paul has created a separate Telegram account for QA testing.
    2. That account has sent /start to @mzansiedge_bot.
    3. You are running this interactively (phone OTP required).
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_qa_session.string")
SESSION_PATH.parent.mkdir(exist_ok=True)


async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()

    session_str = client.session.save()
    SESSION_PATH.write_text(session_str)
    print(f"\nQA session saved to {SESSION_PATH}")
    print(f"Session string length: {len(session_str)}")

    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")
    print("\nAll QA harnesses will now authenticate as this account.")
    print("Paul's telethon_session is unchanged.")

    await client.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
