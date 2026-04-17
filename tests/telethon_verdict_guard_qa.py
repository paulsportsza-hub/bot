"""FIX-REGRESS-D1-VERDICT-GUARD-01 — Telethon QA for LLM meta-leak validator.

Captures 3 Edge Detail cards from @mzansiedge_bot, asserts none contain the 10
banned LLM meta-markers. Saves raw text + screenshots to reports dir.
"""
import asyncio
import json
import os
from datetime import datetime

from telethon import TelegramClient

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
SESSION = "/home/paulsportsza/bot/data/telethon_session"
BOT = "@mzansiedge_bot"
OUTPUT = "/home/paulsportsza/reports/telethon_FIX_REGRESS_D1.json"
SS_DIR = "/home/paulsportsza/reports/screenshots_FIX_REGRESS_D1"

os.makedirs(SS_DIR, exist_ok=True)

BANNED_META_MARKERS = [
    # Original 10 tier-validation error markers
    "i notice", "i understand", "confidence_tier", "selective",
    "not one of", "isn't one of", "valid tiers", "four valid",
    "valid options", "i apologize",
    # FIX-NARRATIVE-META-MARKERS-01: LLM refusals + data-absence meta-commentary
    "i cannot", "i can't produce",
    "no form, h2h", "no form data, h2h", "no manager names", "also noting",
]

results = {
    "timestamp": datetime.now().isoformat(),
    "wave": "FIX-REGRESS-D1-VERDICT-GUARD-01",
    "commit_sha": "b526164",
    "cards": [],
    "log": [],
    "summary": {},
}


def log(msg):
    print(msg)
    results["log"].append(msg)


async def latest_bot_msg(client, bot_entity, limit=5):
    me = await client.get_me()
    async for msg in client.iter_messages(bot_entity, limit=limit):
        if msg.sender_id != me.id:
            return msg
    return None


async def save_ss(client, msg, name):
    if not msg:
        return None
    if msg.photo:
        path = os.path.join(SS_DIR, f"{name}.jpg")
        await client.download_media(msg, file=path)
        log(f"  [SS] {path}")
        return path
    # Save text dump too
    path = os.path.join(SS_DIR, f"{name}.txt")
    text = msg.text or msg.message or ""
    with open(path, "w") as f:
        f.write(text)
    log(f"  [TXT] {path}")
    return path


async def goto_edge_picks(client, bot_entity):
    await client.send_message(BOT, "/start")
    await asyncio.sleep(3)
    start = await latest_bot_msg(client, bot_entity)
    if not start or not start.buttons:
        return None
    for row in start.buttons:
        for btn in row:
            if "edge picks" in btn.text.lower() or "hot tips" in btn.text.lower():
                await btn.click()
                await asyncio.sleep(5)
                return await latest_bot_msg(client, bot_entity)
    return None


def get_tip_buttons(msg):
    if not msg or not msg.buttons:
        return []
    labels = []
    skip = ["next", "prev", "back", "←", "→", "page", "menu", "home",
            "↩", "settings", "profile", "help", "subscribe", "plans", "unlock"]
    for row in msg.buttons:
        for btn in row:
            t = btn.text.strip()
            if t and not any(k in t.lower() for k in skip) and len(t) > 3:
                labels.append(t)
    return labels


async def click_btn_label(msg, label):
    if not msg or not msg.buttons:
        return False
    for row in msg.buttons:
        for btn in row:
            if btn.text.strip() == label:
                await btn.click()
                return True
    return False


def check_meta_markers(text):
    """Return list of found banned markers (lowercased input)."""
    low = (text or "").lower()
    return [m for m in BANNED_META_MARKERS if m in low]


async def capture_edge_details(client, bot_entity, n=3):
    cards = []
    list_msg = await goto_edge_picks(client, bot_entity)
    if not list_msg:
        log("FAIL: could not reach edge picks list")
        return cards

    labels = get_tip_buttons(list_msg)
    log(f"List has {len(labels)} tip buttons: {labels[:5]}")

    for i, label in enumerate(labels[:n]):
        log(f"\n--- Card {i + 1}: '{label}' ---")
        list_msg = await goto_edge_picks(client, bot_entity)
        if not list_msg:
            break
        clicked = await click_btn_label(list_msg, label)
        if not clicked:
            log(f"  could not click '{label}'")
            continue
        await asyncio.sleep(6)
        detail = await latest_bot_msg(client, bot_entity)
        if not detail:
            log("  no detail response")
            continue

        text = detail.text or detail.message or ""
        is_img = bool(detail.photo)
        caption = detail.message or "" if is_img else ""
        combined = text + "\n" + caption

        found_markers = check_meta_markers(combined)
        ss = await save_ss(client, detail, f"D1_card_{i + 1}")

        card = {
            "card_index": i + 1,
            "label": label,
            "is_image": is_img,
            "text_length": len(text),
            "text_content": text[:2000],  # cap to keep JSON readable
            "caption": caption[:500],
            "banned_markers_found": found_markers,
            "meta_leak_detected": bool(found_markers),
            "screenshot": ss,
        }
        cards.append(card)
        log(f"  is_image={is_img}, text_len={len(text)}, banned_markers={found_markers}")
        log(f"  Text preview: {text[:300]}")
    return cards


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    log(f"Connected as: {me.first_name} (ID: {me.id})")
    bot_entity = await client.get_entity(BOT)

    cards = await capture_edge_details(client, bot_entity, n=3)
    results["cards"] = cards

    # Summary
    total_cards = len(cards)
    cards_with_leak = sum(1 for c in cards if c["meta_leak_detected"])
    results["summary"] = {
        "total_cards_captured": total_cards,
        "cards_with_meta_leak": cards_with_leak,
        "all_clean": cards_with_leak == 0 and total_cards >= 3,
        "verdict": "PASS" if (cards_with_leak == 0 and total_cards >= 3) else "FAIL",
    }

    with open(OUTPUT, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    log(f"\n=== SUMMARY ===")
    log(f"Cards captured: {total_cards}")
    log(f"Cards with meta leak: {cards_with_leak}")
    log(f"Verdict: {results['summary']['verdict']}")
    log(f"Output: {OUTPUT}")
    log(f"Screenshots: {SS_DIR}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
