"""Bootstrap / re-auth the Telethon anon_session.session file.

Run interactively when the session is expired or revoked:
    cd /home/paulsportsza/bot
    .venv/bin/python bootstrap_anon_session.py

Telegram will send a login code to the account phone.  Type it when prompted.
If 2FA is enabled, enter the password when prompted.
"""

import asyncio
import getpass
import os
import sys
from pathlib import Path

# ── Credentials ───────────────────────────────────────────────────────────────
_BOT_DIR = Path(__file__).parent
_ENV_FILE = _BOT_DIR / ".env"
SESSION   = str(_BOT_DIR / "anon_session")   # Telethon appends .session


def _read_env(path: Path) -> dict:
    env: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


_env = _read_env(_ENV_FILE)
API_ID   = int(_env.get("TELEGRAM_API_ID")   or os.getenv("TELEGRAM_API_ID",   "0"))
API_HASH =     _env.get("TELEGRAM_API_HASH") or os.getenv("TELEGRAM_API_HASH", "")

try:
    from telethon import TelegramClient
    from telethon.errors import AuthKeyUnregisteredError, AuthKeyError
except ImportError:
    sys.exit("telethon not installed — run: .venv/bin/pip install telethon")

if not API_ID or not API_HASH:
    sys.exit(
        "TELEGRAM_API_ID / TELEGRAM_API_HASH missing.\n"
        f"Check {_ENV_FILE}"
    )


async def _session_valid() -> bool:
    """Return True if the existing session file is authorised."""
    client = TelegramClient(SESSION, API_ID, API_HASH)
    try:
        await client.connect()
        return await client.is_user_authorized()
    except (AuthKeyUnregisteredError, AuthKeyError):
        return False
    except Exception as e:
        print(f"  (connect check error: {e})")
        return False
    finally:
        await client.disconnect()


async def main() -> None:
    force = "--force" in sys.argv

    print("Checking existing session …")
    if not force and await _session_valid():
        client = TelegramClient(SESSION, API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        await client.disconnect()
        print(f"\n✅ Session is already valid — logged in as {me.first_name} (@{me.username})")
        print("No re-auth needed.  Run again with --force to re-auth anyway.")
        return

    # ── Interactive re-auth ───────────────────────────────────────────────────
    print("\nStarting interactive authentication …")
    print("Telegram will send a code to the account's phone or another Telegram session.\n")

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start(
        phone=lambda: input("Phone number (international format, e.g. +27821234567): "),
        code_callback=lambda: input("Telegram code: "),
        password=lambda: getpass.getpass("2FA password (press Enter to skip): "),
    )
    me = await client.get_me()
    await client.disconnect()

    print(f"\n✅ Signed in as: {me.first_name} (@{me.username})  id={me.id}")
    print(f"Session saved to: {SESSION}.session")


if __name__ == "__main__":
    asyncio.run(main())
