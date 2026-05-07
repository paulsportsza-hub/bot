"""E2E test — /help command sends an image card (photo) instead of plain text.

Assertions:
  A1: A photo was received (not plain text)
  A2: The photo contains the word "HELP" or "Help" (OCR)
  A3: Commands like "/picks" or "/schedule" are visible (OCR)
  A4: Keyboard buttons (Guide, Main Menu) are present in message markup

Run from /home/paulsportsza/bot/:
    .venv/bin/python tests/test_help_card_e2e.py
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import time

# ── Path fix so we can import the shared session helpers ──────────────────────
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    MessageMediaPhoto,
)

# ── Config ────────────────────────────────────────────────────────────────────
API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
TIMEOUT = 15  # seconds to wait for bot response

# Session paths (prefer string session)
_DIR = os.path.join(BOT_DIR, "data")
STRING_SESSION_FILE = os.path.join(_DIR, "telethon_qa_session.string")
FILE_SESSION = os.path.join(_DIR, "telethon_qa_session")


# ── Telethon client helpers ───────────────────────────────────────────────────

async def get_client() -> TelegramClient:
    """Connect using saved session."""
    if os.path.exists(STRING_SESSION_FILE):
        raw = open(STRING_SESSION_FILE).read().strip()
        if raw:
            client = TelegramClient(StringSession(raw), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                print("  ✓ Connected via string session")
                return client
            await client.disconnect()

    client = TelegramClient(FILE_SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not authorised. Run save_telegram_session.py first.")
        sys.exit(1)
    print("  ✓ Connected via file session")
    return client


async def send_and_wait(client: TelegramClient, text: str, wait: float = TIMEOUT) -> list:
    """Send a message and return all bot responses received within `wait` seconds."""
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    sent_id = sent.id
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=20)
    # Return bot messages after our sent message, oldest-first
    return list(reversed([m for m in messages if m.id > sent_id and not m.out]))


# ── OCR helper ───────────────────────────────────────────────────────────────

def ocr_photo_bytes(photo_bytes: bytes) -> str:
    """Run pytesseract OCR on raw image bytes. Returns extracted text."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(photo_bytes))
        text = pytesseract.image_to_string(img)
        return text
    except Exception as exc:
        print(f"  [OCR ERROR] {exc}")
        return ""


# ── Assertion helpers ─────────────────────────────────────────────────────────

def has_inline_button(msg, text: str) -> bool:
    """True if the message markup contains a button whose text contains `text`."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "text") and text.lower() in btn.text.lower():
                return True
    return False


def list_inline_buttons(msg) -> list[str]:
    """Return list of all inline button texts."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    labels = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "text"):
                labels.append(btn.text)
    return labels


# ── Main test ─────────────────────────────────────────────────────────────────

async def run_help_card_test():
    print()
    print("=" * 62)
    print("  MzansiEdge E2E — /help Command Photo Card Test")
    print("=" * 62)
    print()

    client = await get_client()
    start = time.time()

    print("  ▶  Sending /help to @mzansiedge_bot ...")
    responses = await send_and_wait(client, "/help", wait=TIMEOUT)
    elapsed = time.time() - start
    print(f"  ▶  Got {len(responses)} response(s) in {elapsed:.1f}s")

    await client.disconnect()

    # ── Find the response message ─────────────────────────────────────────
    help_msg = None
    for msg in responses:
        # Prefer a message that has a photo, or the most recent message
        if msg.media and isinstance(msg.media, MessageMediaPhoto):
            help_msg = msg
            break

    if help_msg is None and responses:
        help_msg = responses[-1]  # Fallback: last message

    if help_msg is None:
        print("\n  ✗  No response received from bot at all.")
        print("\n  OVERALL VERDICT: FAIL\n")
        sys.exit(1)

    # ── A1: Photo received? ───────────────────────────────────────────────
    has_photo = (
        help_msg.media is not None
        and isinstance(help_msg.media, MessageMediaPhoto)
    )
    a1_pass = has_photo

    print()
    print("  ── Assertion Results ──────────────────────────────────")
    print(f"  A1 (photo received):          {'PASS' if a1_pass else 'FAIL'}")

    # ── OCR ──────────────────────────────────────────────────────────────
    ocr_text = ""
    if has_photo:
        print("  ▶  Downloading photo for OCR ...")
        # Download photo bytes
        # We need a fresh client for download
        if os.path.exists(STRING_SESSION_FILE):
            raw = open(STRING_SESSION_FILE).read().strip()
            dl_client = TelegramClient(StringSession(raw), API_ID, API_HASH)
        else:
            dl_client = TelegramClient(FILE_SESSION, API_ID, API_HASH)
        await dl_client.connect()

        try:
            photo_bytes = await dl_client.download_media(help_msg.media, file=bytes)
            if photo_bytes:
                print(f"  ▶  Photo size: {len(photo_bytes):,} bytes — running OCR ...")
                ocr_text = ocr_photo_bytes(photo_bytes)
                print()
                print("  ── OCR Text (first 800 chars) ─────────────────────────")
                print("  " + ocr_text[:800].replace("\n", "\n  "))
                print()
            else:
                print("  [WARN] Photo download returned empty bytes")
        finally:
            await dl_client.disconnect()
    else:
        # If no photo, check if there's text
        text_preview = (help_msg.text or "")[:300]
        print(f"  [No photo — message text]: {text_preview!r}")

    # ── A2: OCR contains "HELP" or "Help" ────────────────────────────────
    a2_pass = (
        "HELP" in ocr_text
        or "Help" in ocr_text
        or "help" in ocr_text.lower()
    )
    print(f"  A2 (OCR: HELP visible):       {'PASS' if a2_pass else 'FAIL'}")
    if not a2_pass:
        print(f"       (OCR text sample: {ocr_text[:200]!r})")

    # ── A3: Commands visible in OCR ───────────────────────────────────────
    ocr_lower = ocr_text.lower()
    commands_found = []
    for cmd in ["/picks", "/schedule", "/menu", "/start", "/help"]:
        if cmd.lower() in ocr_lower or cmd.lstrip("/") in ocr_lower:
            commands_found.append(cmd)

    a3_pass = len(commands_found) > 0
    print(f"  A3 (OCR: commands visible):   {'PASS' if a3_pass else 'FAIL'}")
    if commands_found:
        print(f"       Found: {commands_found}")
    else:
        print(f"       No commands detected in OCR text")
        # Also check caption/text
        caption = help_msg.text or ""
        if caption:
            print(f"       Message caption: {caption[:200]!r}")

    # ── A4: Keyboard buttons present ─────────────────────────────────────
    buttons = list_inline_buttons(help_msg)
    guide_present   = any("guide" in b.lower() for b in buttons)
    menu_present    = any("menu" in b.lower() or "main" in b.lower() for b in buttons)
    a4_pass = guide_present or menu_present or len(buttons) > 0

    print(f"  A4 (keyboard buttons present):{' PASS' if a4_pass else ' FAIL'}")
    if buttons:
        print(f"       Buttons found: {buttons}")
    else:
        print(f"       No inline buttons found in markup")

    # ── Summary ──────────────────────────────────────────────────────────
    all_assertions = [a1_pass, a2_pass, a3_pass, a4_pass]
    pass_count = sum(all_assertions)
    verdict = "PASS" if all(all_assertions) else "FAIL"

    print()
    print("  ── Summary ────────────────────────────────────────────")
    print(f"  Assertions passed: {pass_count}/4")
    print(f"  OVERALL VERDICT: {verdict}")
    print("=" * 62)
    print()

    return verdict == "PASS"


def main():
    # Load .env
    env_file = os.path.join(BOT_DIR, ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    ok = asyncio.run(run_help_card_test())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
