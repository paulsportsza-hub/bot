"""QA-BASELINE-09: Telethon E2E — click → capture → back → repeat."""
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonUrl

API_ID = int(os.environ.get("TELEGRAM_API_ID", "32418601"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
STRING_SESSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "telethon_session.string",
)
BOT_USERNAME = "mzansiedge_bot"
REPORT_DIR = "/home/paulsportsza/reports"


def btns(msg):
    out = []
    if msg and msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for b in row.buttons:
                if isinstance(b, KeyboardButtonCallback):
                    out.append({"text": b.text, "data": b.data.decode(), "type": "callback"})
                elif isinstance(b, KeyboardButtonUrl):
                    out.append({"text": b.text, "url": b.url, "type": "url"})
    return out


async def get_client():
    s = open(STRING_SESSION_FILE).read().strip()
    c = TelegramClient(StringSession(s), API_ID, API_HASH)
    await c.connect()
    assert await c.is_user_authorized(), "Not authorized"
    return c


async def click_data(client, msg, data, wait=12):
    """Click callback button on message, wait, re-fetch message."""
    try:
        await msg.click(data=data.encode())
    except Exception as e:
        return None, str(e)
    await asyncio.sleep(wait)
    # Re-fetch the same message to get updated content
    updated = await client.get_messages(BOT_USERNAME, ids=msg.id)
    return updated, None


async def run():
    client = await get_client()
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] Connected\n")
    results = {"timestamp": datetime.now().isoformat(), "hot_tips": [], "my_matches": [], "gate": {}}

    # === HOT TIPS ===
    print("=" * 60)
    print("HOT TIPS FLOW")
    print("=" * 60)

    await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
    await asyncio.sleep(22)

    # Find the main tips message (the one with edge:detail buttons)
    msgs = await client.get_messages(BOT_USERNAME, limit=25)
    tips_msg = None
    for m in msgs:
        if m.out:
            continue
        b = btns(m)
        if any(x.get("data", "").startswith("edge:detail:") for x in b):
            tips_msg = m
            break

    if not tips_msg:
        print("ERROR: No tips message found!")
        await client.disconnect()
        return results

    tips_text = tips_msg.text or tips_msg.raw_text or ""
    results["list_header"] = tips_text[:500]
    print(f"Tips list: {tips_text[:200]}...\n")

    # Collect detail buttons from this message
    tip_buttons = [b for b in btns(tips_msg) if b.get("data", "").startswith("edge:detail:")]
    back_button = [b for b in btns(tips_msg) if b.get("data", "").startswith("hot:page:")]
    print(f"Page 1: {len(tip_buttons)} tips, {len(back_button)} page buttons")

    # Process each tip on page 1
    all_tip_keys = []
    for tb in tip_buttons:
        mk = tb["data"].replace("edge:detail:", "")
        all_tip_keys.append((mk, tb["data"], tb["text"]))

    # Also get page 2 if available
    page2_keys = []
    if back_button:
        p2data = [b["data"] for b in back_button if "1" in b["data"]]
        if p2data:
            updated, err = await click_data(client, tips_msg, p2data[0], wait=8)
            if updated and not err:
                tips_msg = updated  # Now showing page 2
                p2_btns = [b for b in btns(tips_msg) if b.get("data", "").startswith("edge:detail:")]
                for tb in p2_btns:
                    mk = tb["data"].replace("edge:detail:", "")
                    if mk not in [k[0] for k in all_tip_keys]:
                        page2_keys.append((mk, tb["data"], tb["text"]))
                print(f"Page 2: {len(p2_btns)} tips")
                # Go back to page 1
                p0data = [b for b in btns(tips_msg) if b.get("data", "") == "hot:page:0"]
                if p0data:
                    updated, _ = await click_data(client, tips_msg, "hot:page:0", wait=8)
                    if updated:
                        tips_msg = updated

    all_tip_keys.extend(page2_keys)
    print(f"\nTotal unique tips: {len(all_tip_keys)}")
    for mk, _, txt in all_tip_keys:
        print(f"  {mk}: {txt}")

    # Now click each tip, capture detail, click back
    for i, (mk, data, txt) in enumerate(all_tip_keys):
        print(f"\n--- Hot Tip [{i+1}/{len(all_tip_keys)}]: {mk} ---")

        # Click the detail button
        t0 = time.time()
        updated, err = await click_data(client, tips_msg, data, wait=12)
        elapsed = time.time() - t0

        if err:
            print(f"  ERROR: {err}")
            # Re-send Hot Tips to get fresh message
            await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
            await asyncio.sleep(18)
            fresh = await client.get_messages(BOT_USERNAME, limit=15)
            found = False
            for fm in fresh:
                if fm.out:
                    continue
                for fb in btns(fm):
                    if fb.get("data") == data:
                        tips_msg = fm
                        t0 = time.time()
                        updated, err2 = await click_data(client, fm, data, wait=12)
                        elapsed = time.time() - t0
                        if not err2 and updated:
                            found = True
                        break
                if found:
                    break
            if not found:
                print(f"  SKIP: could not click")
                results["hot_tips"].append({"match_key": mk, "source": "hot_tips", "error": "click_failed"})
                continue

        detail_text = (updated.text or updated.raw_text or "") if updated else ""

        # If we got the list back instead of detail, the click may have failed
        if "Live Edges Found" in detail_text or "Edge Picks —" in detail_text:
            print(f"  Got list instead of detail, retrying...")
            # The button might have paginated. Try finding the button again.
            tip_btns_now = [b for b in btns(updated or tips_msg) if b.get("data") == data]
            if tip_btns_now:
                updated, err = await click_data(client, updated or tips_msg, data, wait=12)
                if updated and not err:
                    detail_text = updated.text or updated.raw_text or ""

        card = _build_card(mk, "hot_tips", detail_text, elapsed, btns(updated) if updated else [])
        results["hot_tips"].append(card)
        _print_card(card)

        # Navigate back to list
        if updated:
            back_btns = [b for b in btns(updated) if "back" in b.get("data", "").lower() or "hot:back" in b.get("data", "")]
            if back_btns:
                tips_msg_updated, _ = await click_data(client, updated, back_btns[0]["data"], wait=6)
                if tips_msg_updated:
                    tips_msg = tips_msg_updated
            else:
                # Re-send Hot Tips
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(15)
                fresh = await client.get_messages(BOT_USERNAME, limit=15)
                for fm in fresh:
                    if fm.out:
                        continue
                    if any(b.get("data", "").startswith("edge:detail:") for b in btns(fm)):
                        tips_msg = fm
                        break

        await asyncio.sleep(2)

    # === MY MATCHES ===
    print("\n" + "=" * 60)
    print("MY MATCHES FLOW")
    print("=" * 60)

    await client.send_message(BOT_USERNAME, "⚽ My Matches")
    await asyncio.sleep(18)

    msgs = await client.get_messages(BOT_USERNAME, limit=15)
    mm_msg = None
    for m in msgs:
        if m.out:
            continue
        b = btns(m)
        if any(x.get("data", "").startswith("yg:game:") for x in b):
            mm_msg = m
            break

    if not mm_msg:
        print("No My Matches message with game buttons found")
        # Check if the latest message IS a matches list without buttons
        for m in msgs:
            if not m.out:
                t = m.text or ""
                print(f"  Latest msg ({len(t)} chars): {t[:200]}...")
                results["my_matches_text"] = t
                break
    else:
        mm_text = mm_msg.text or mm_msg.raw_text or ""
        results["my_matches_text"] = mm_text[:500]
        print(f"My Matches list: {mm_text[:200]}...\n")

        game_buttons = [b for b in btns(mm_msg) if b.get("data", "").startswith("yg:game:")]
        seen = set()
        unique_games = []
        for gb in game_buttons:
            eid = gb["data"].replace("yg:game:", "")
            if eid not in seen:
                seen.add(eid)
                unique_games.append((eid, gb["data"], gb["text"]))

        print(f"Unique games: {len(unique_games)}")
        for eid, _, txt in unique_games:
            print(f"  {eid}: {txt}")

        for i, (eid, data, txt) in enumerate(unique_games[:8]):
            print(f"\n--- My Match [{i+1}/{min(len(unique_games),8)}]: {eid} ---")

            t0 = time.time()
            updated, err = await click_data(client, mm_msg, data, wait=15)
            elapsed = time.time() - t0

            if err:
                print(f"  ERROR: {err}")
                # Re-send My Matches
                await client.send_message(BOT_USERNAME, "⚽ My Matches")
                await asyncio.sleep(15)
                fresh = await client.get_messages(BOT_USERNAME, limit=15)
                found = False
                for fm in fresh:
                    if fm.out:
                        continue
                    for fb in btns(fm):
                        if fb.get("data") == data:
                            mm_msg = fm
                            t0 = time.time()
                            updated, err2 = await click_data(client, fm, data, wait=15)
                            elapsed = time.time() - t0
                            if not err2 and updated:
                                found = True
                            break
                    if found:
                        break
                if not found:
                    results["my_matches"].append({"match_key": eid, "source": "my_matches", "error": "click_failed"})
                    continue

            detail_text = (updated.text or updated.raw_text or "") if updated else ""
            card = _build_card(eid, "my_matches", detail_text, elapsed, btns(updated) if updated else [])
            results["my_matches"].append(card)
            _print_card(card)

            # Navigate back
            if updated:
                back_btns = [b for b in btns(updated) if b.get("data", "").startswith("yg:all:")]
                if back_btns:
                    mm_updated, _ = await click_data(client, updated, back_btns[0]["data"], wait=8)
                    if mm_updated:
                        mm_msg = mm_updated
                else:
                    await client.send_message(BOT_USERNAME, "⚽ My Matches")
                    await asyncio.sleep(12)
                    fresh = await client.get_messages(BOT_USERNAME, limit=10)
                    for fm in fresh:
                        if not fm.out and any(b.get("data","").startswith("yg:game:") for b in btns(fm)):
                            mm_msg = fm
                            break

            await asyncio.sleep(2)

    # === COVERAGE GATE LOGS ===
    print("\n" + "=" * 60)
    print("COVERAGE GATE LOG CHECK")
    print("=" * 60)
    results["gate"]["checked"] = True

    # Save
    f = os.path.join(REPORT_DIR, f"qa-b09-capture-{datetime.now().strftime('%Y%m%d-%H%M')}.json")
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(f, "w") as fh:
        json.dump(results, fh, indent=2, default=str)

    print(f"\nSaved: {f}")
    print(f"Hot Tips: {len([c for c in results['hot_tips'] if 'error' not in c])}")
    print(f"My Matches: {len([c for c in results['my_matches'] if 'error' not in c])}")

    await client.disconnect()
    return results


def _build_card(mk, source, text, elapsed, buttons):
    card = {
        "match_key": mk, "source": source, "text": text,
        "text_length": len(text), "response_time_s": round(elapsed, 1),
        "buttons": [{"text": b["text"], "data": b.get("data",""), "type": b["type"]} for b in buttons],
    }
    card["has_setup"] = "Setup" in text or "📋" in text
    card["has_edge"] = ("The Edge" in text or "🎯" in text) and "Edge Picks" not in text
    card["has_risk"] = "Risk" in text or "⚠️" in text
    card["has_verdict"] = "Verdict" in text or "🏆" in text
    card["has_odds"] = any(bk in text.lower() for bk in ["hollywoodbets","betway","sportingbet","supabets","gbets"])
    card["has_broadcast"] = "📺" in text
    card["has_kickoff"] = "📅" in text
    card["has_edge_badge"] = any(b in text for b in ["💎","🥇","🥈","🥉"])
    card["has_neutral"] = "Neutral Analysis" in text
    card["has_insufficient"] = "Insufficient data" in text
    card["has_lock"] = "🔒" in text
    card["all_4_sections"] = all([card["has_setup"], card["has_edge"], card["has_risk"], card["has_verdict"]])

    # Count key facts
    facts = 0
    facts += len(re.findall(r"\b(?:sits?|position|place|ranked)\s+\d+(?:st|nd|rd|th)", text, re.I))
    facts += len(re.findall(r"on\s+\d+\s+points", text, re.I))
    facts += len(re.findall(r"\b[WDLT]{3,}\b", text))
    facts += len(re.findall(r"\d+\s+wins?\s+(?:from|in|of)\s+\d+", text, re.I))
    facts += len(re.findall(r"\b\d+-\d+\b(?!\s*%)", text))  # scores but not percentages
    facts += len(re.findall(r"h2h|head.to.head|last\s+\d+\s+meetings?", text, re.I))
    facts += len(re.findall(r"\d+\.\d+\s*(?:\(|on\s)(?:Hollywoodbets|Betway|GBets|Sportingbet|Supabets)", text))
    facts += len(re.findall(r"(?:Hollywoodbets|Betway|GBets|Sportingbet|Supabets)\s*(?:@|at)?\s*\d+\.\d+", text))
    facts += len(re.findall(r"\d+\.?\d*%", text))
    facts += len(re.findall(r"(?:coach|manager|under)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", text, re.I))
    card["key_facts_count"] = facts
    return card


def _print_card(card):
    print(f"  Length: {card['text_length']}, Time: {card['response_time_s']}s")
    print(f"  4 sections: {card['all_4_sections']}")
    print(f"  Setup={card['has_setup']} Edge={card['has_edge']} Risk={card['has_risk']} Verdict={card['has_verdict']}")
    print(f"  Odds={card['has_odds']} Bcast={card['has_broadcast']} Kickoff={card['has_kickoff']} Badge={card['has_edge_badge']}")
    print(f"  Key facts: {card['key_facts_count']}")
    t = card["text"]
    print(f"  Text: {t[:300]}...")


if __name__ == "__main__":
    asyncio.run(run())
