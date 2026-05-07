"""QA-23 Page 2 capture — grab remaining Hot Tips cards from page 2."""

from __future__ import annotations
import asyncio, json, os, sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonUrl

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
TIMEOUT = 15
DETAIL_TIMEOUT = 25

async def get_client():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    if await client.is_user_authorized():
        return client
    sys.exit(1)

def extract_buttons(msg):
    buttons = []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return buttons
    for row_idx, row in enumerate(msg.reply_markup.rows):
        for btn_idx, btn in enumerate(row.buttons):
            info = {"row": row_idx, "col": btn_idx, "text": getattr(btn, "text", "")}
            if isinstance(btn, KeyboardButtonCallback):
                info["type"] = "callback"
                info["data"] = btn.data.decode("utf-8", errors="replace") if btn.data else ""
            elif isinstance(btn, KeyboardButtonUrl):
                info["type"] = "url"
                info["url"] = btn.url
            else:
                info["type"] = type(btn).__name__
            buttons.append(info)
    return buttons

async def run():
    client = await get_client()
    print("Connected.\n")

    # Send Hot Tips to get list
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, "\U0001f48e Top Edge Picks")
    await asyncio.sleep(18)
    messages = await client.get_messages(entity, limit=30)
    msgs = [m for m in messages if m.id > sent.id and not m.out]
    msgs = list(reversed(msgs))

    # Find page 1 message and click Next
    for msg in msgs:
        if msg.text and not msg.out:
            btns = extract_buttons(msg)
            for btn in btns:
                if btn.get("data", "").startswith("hot:page:1"):
                    print("Clicking Next to page 2...")
                    await msg.click(data=b"hot:page:1")
                    await asyncio.sleep(10)
                    # Get updated messages
                    p2_messages = await client.get_messages(entity, limit=15)
                    p2_msgs = list(reversed(p2_messages))

                    for p2msg in p2_msgs:
                        if p2msg.text and not p2msg.out:
                            print(f"\n--- Page 2 message (id={p2msg.id}) ---")
                            print(p2msg.text[:1500])
                            p2btns = extract_buttons(p2msg)
                            print(f"Buttons: {json.dumps(p2btns, indent=2)}")

                            # Click each edge:detail button
                            for p2btn in p2btns:
                                if p2btn.get("data", "").startswith("edge:detail:"):
                                    print(f"\n{'─'*60}")
                                    print(f"Opening: {p2btn['text']} → {p2btn['data']}")
                                    await p2msg.click(data=p2btn["data"].encode())
                                    await asyncio.sleep(DETAIL_TIMEOUT)
                                    det_msgs = await client.get_messages(entity, limit=15)
                                    for dm in reversed(det_msgs):
                                        if dm.text and not dm.out:
                                            print(f"\n=== VERBATIM DETAIL TEXT ===")
                                            print(dm.text)
                                            print(f"=== END VERBATIM ===")
                                            print(f"BUTTONS: {json.dumps(extract_buttons(dm), indent=2)}")
                                            # Go back
                                            await asyncio.sleep(2)
                                            for row in (dm.reply_markup.rows if dm.reply_markup else []):
                                                for b in row.buttons:
                                                    if hasattr(b, "text") and "Edge Picks" in b.text:
                                                        await dm.click(data=b.data)
                                                        await asyncio.sleep(5)
                                                    elif hasattr(b, "text") and "Back" in b.text and isinstance(b, KeyboardButtonCallback):
                                                        await dm.click(data=b.data)
                                                        await asyncio.sleep(5)
                                            break
                    break
            break

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run())
