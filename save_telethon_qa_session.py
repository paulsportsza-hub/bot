"""Save Telethon session for the dedicated QA test account.

Run this ONCE interactively after Paul creates the QA Telegram account.
All QA harnesses will then use telethon_qa_session instead of Paul's personal session.

Writes TWO session artifacts from a single authentication so both harness types work:
  - data/telethon_qa_session         (SQLite file, used by harnesses that pass a path)
  - data/telethon_qa_session.string  (used by harnesses that load StringSession)

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

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

STRING_SESSION_PATH = DATA_DIR / "telethon_qa_session.string"
FILE_SESSION_PATH = str(DATA_DIR / "telethon_qa_session")


async def main():
    # Authenticate once using the file session path — Telethon creates the SQLite .session file.
    # Then export a string copy so harnesses using StringSession also work.
    client = TelegramClient(FILE_SESSION_PATH, API_ID, API_HASH)
    await client.start()

    # Export to string session so string-session harnesses are covered.
    session_str = StringSession.save(client.session)
    STRING_SESSION_PATH.write_text(session_str)

    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")
    print(f"File session:   {FILE_SESSION_PATH}.session")
    print(f"String session: {STRING_SESSION_PATH} (len={len(session_str)})")
    print("\nBoth session artifacts written. All QA harnesses are now authorised.")
    print("Paul's telethon_session is unchanged.")

    await client.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
