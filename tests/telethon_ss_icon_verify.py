"""
Verify the SuperSport icon renders in edge detail cards.
Opens Hot Tips, finds first accessible tip, taps edge:detail,
captures the rendered PNG card.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

BOT = "@mzansiedge_bot"
SESSION = str(Path(__file__).parent.parent / "data" / "telethon_qa_session.session")
API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
OUT_DIR = Path("/tmp/ss_icon_verify")
OUT_DIR.mkdir(exist_ok=True)


async def main():
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    print("Connected")

    bot = await client.get_entity(BOT)

    # Step 1: send Hot Tips
    await client.send_message(bot, "💎 Top Edge Picks")
    await asyncio.sleep(6)

    # Get last few messages — look for a tip card message with inline buttons
    messages = await client.get_messages(bot, limit=20)
    # Look for ep:pick:N or edge:detail buttons
    PICK_PREFIXES = (b"ep:pick:", b"edge:detail:")
    card_msg = None
    detail_btn = None
    for msg in messages:
        if msg.buttons:
            for row in msg.buttons:
                for btn in row:
                    raw = (btn.data or b"")
                    if any(raw.startswith(p) for p in PICK_PREFIXES):
                        card_msg = msg
                        detail_btn = btn
                        break
                if detail_btn:
                    break
        if detail_btn:
            break

    if not detail_btn:
        print("No pick/detail button found — dumping button data:")
        for msg in messages[:5]:
            if msg.buttons:
                for row in msg.buttons:
                    for btn in row:
                        print(f"  btn text={btn.text!r} data={btn.data!r}")
        await client.disconnect()
        return

    print(f"Tapping: {detail_btn.text!r} data={detail_btn.data!r}")
    await detail_btn.click()
    await asyncio.sleep(8)

    # Get the latest message — should be the detail card PNG
    messages = await client.get_messages(bot, limit=5)
    for msg in messages:
        if msg.media:
            fname = OUT_DIR / f"detail_card_{int(time.time())}.png"
            await client.download_media(msg.media, str(fname))
            print(f"Card saved: {fname}")
            break
        if msg.text:
            print(f"Text response: {msg.text[:200]}")

    await client.disconnect()
    print("Done")


if __name__ == "__main__":
    asyncio.run(main())
