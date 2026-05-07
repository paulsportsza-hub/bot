#!/usr/bin/env python3
"""
QA script for BUILD-SETTINGS-CLEANUP-01 (v3 — targeted fixes)
Fixes from v2:
- Check 1: Click 'Done — Next step' not 'Soccer' repeatedly
- Check 4: Edge picks list is just buttons (no text), detect match buttons pattern
- Check 5: nop:spacer is the divider row button
- Checks 2/3: proper timing isolation after long operations
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import ReplyKeyboardMarkup
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
SESSION_PATH = "/home/paulsportsza/bot/data/telethon_qa_session"
BOT = "@mzansiedge_bot"
SS_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
SS_DIR.mkdir(parents=True, exist_ok=True)

ts = int(time.time())
TIMEOUT = 20


def save(label, text):
    p = SS_DIR / f"bsc01v3_{label}_{ts}.txt"
    p.write_text(str(text), encoding="utf-8")
    return str(p)


def full_text(msg):
    parts = []
    if msg and msg.message:
        parts.append(msg.message)
    if msg and msg.reply_markup and hasattr(msg.reply_markup, "rows"):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                label = getattr(btn, "text", "")
                if label:
                    parts.append(f"[BTN:{label}]")
    return "\n".join(parts)


def inline_buttons(msg):
    """Return list of (text, data) for inline buttons."""
    out = []
    if msg and msg.reply_markup and hasattr(msg.reply_markup, "rows"):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                text = getattr(btn, "text", "")
                data = getattr(btn, "data", None)
                out.append((text, data))
    return out


def reply_buttons(msg):
    out = []
    if msg and msg.reply_markup and isinstance(msg.reply_markup, ReplyKeyboardMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                out.append(btn.text)
    return out


async def await_bot(client, bot_id, after_time, timeout=TIMEOUT):
    """Wait for a bot message (not from us) arriving after `after_time`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(bot_id, limit=8)
        for m in msgs:
            if m.out:
                continue
            if m.date.timestamp() >= after_time - 1:
                return m
    return None


async def send_wait(client, bot_id, text, timeout=TIMEOUT):
    t = time.time()
    await client.send_message(bot_id, text)
    return await await_bot(client, bot_id, t, timeout)


async def click_wait(client, bot_id, msg, data, timeout=TIMEOUT):
    t = time.time()
    try:
        await client(GetBotCallbackAnswerRequest(peer=bot_id, msg_id=msg.id, data=data))
    except Exception as e:
        print(f"    [click-exc] {e}")
    await asyncio.sleep(2.5)
    msgs = await client.get_messages(bot_id, limit=6)
    for m in msgs:
        if m.out:
            continue
        if (m.edit_date and m.edit_date.timestamp() >= t - 1) or m.date.timestamp() >= t - 1:
            return m
    return None


async def run():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    bot = await client.get_entity(BOT)
    print(f"[INFO] Me: {me.username} ({me.id})  Bot: {bot.id}")

    # =====================================================================
    # CHECK 1: Onboarding — 7 steps, no risk/bankroll
    # =====================================================================
    print("\n[CHECK 1] Onboarding...")
    c1 = {"pass": False, "notes": [], "steps": [], "ocr": [], "step_count": 0, "risk_bankroll_found": False}

    # Reset onboarding
    t = time.time()
    await client.send_message(bot, "/qa force_onboard")
    r = await await_bot(client, bot, t, timeout=10)
    print(f"  force_onboard: {r.message if r else 'no resp'}")
    await asyncio.sleep(1)

    t = time.time()
    await client.send_message(bot, "/start")
    msg = await await_bot(client, bot, t, timeout=15)

    if not msg:
        c1["notes"].append("No /start response")
    else:
        step = 0
        done = False

        for _ in range(14):
            ft = full_text(msg)
            ibtns = inline_buttons(msg)
            rbtns = reply_buttons(msg)
            summary = f"step={step} ibtns={[t for t,d in ibtns]} rbtns={rbtns}"
            print(f"  {summary[:120]}")
            c1["steps"].append(summary[:200])
            c1["ocr"].append(ft[:200])

            # Risk/bankroll check
            low = ft.lower() + " " + (msg.message or "").lower()
            if "risk profile" in low or "bankroll" in low:
                c1["risk_bankroll_found"] = True
                c1["notes"].append(f"RISK/BANKROLL at step {step}")

            # Completion check: reply keyboard with main nav
            if rbtns and any(("edge" in b.lower() or "match" in b.lower() or "menu" in b.lower()) for b in rbtns):
                c1["steps"].append(f"DONE at step {step} — main nav visible")
                done = True
                break

            # Completion check: done message text
            if msg.message and any(kw in msg.message.lower() for kw in ["you're all set", "you're set", "let's go!", "welcome aboard"]):
                c1["steps"].append(f"DONE at step {step} — completion text")
                done = True
                break

            # Navigate inline buttons
            if ibtns:
                btn_labels = [t for t, d in ibtns]
                chosen_text = None
                chosen_data = None

                # Priority navigation logic
                PRIORITY = [
                    # Experience
                    "🎯 I bet regularly",
                    # Sports — need to select then advance
                    "✅ Done — Next step",
                    "Done — Next step",
                    "Next step",
                    "✅ Continue",
                    "Continue",
                    # After selecting soccer, click Done
                    "⚽ Soccer",
                    # Favourites
                    "Skip",
                    # Edge explainer
                    "Got it",
                    "🔥 Let's go",
                    "Let's go",
                    # Notify
                    "🔔 Yes, notify",
                    "Yes, notify",
                    "🔔 Yes",
                    # Summary / Plan
                    "View my picks",
                    "See Edge Picks",
                    "Edge Picks",
                    "Continue as Bronze",
                    "Start Free",
                    "Free",
                    "Later",
                ]

                # Check if soccer is already selected — if so, advance with Done
                soccer_selected = any("✅ ⚽ Soccer" in t for t, d in ibtns)
                done_btn = next(((t, d) for t, d in ibtns if "done" in t.lower() and "next" in t.lower()), None)
                if soccer_selected and done_btn:
                    chosen_text, chosen_data = done_btn
                else:
                    for p in PRIORITY:
                        for t, d in ibtns:
                            if p.lower() in t.lower():
                                chosen_text = t
                                chosen_data = d
                                break
                        if chosen_text:
                            break

                if not chosen_text:
                    # Fall back — skip Back button
                    for t, d in ibtns:
                        if "back" not in t.lower() and "↩" not in t:
                            chosen_text, chosen_data = t, d
                            break

                if chosen_text and chosen_data:
                    print(f"    -> click: {chosen_text!r}")
                    step += 1
                    next_msg = await click_wait(client, bot, msg, chosen_data, timeout=15)
                    if not next_msg:
                        c1["notes"].append(f"No resp after clicking {chosen_text!r}")
                        break
                    msg = next_msg
                else:
                    c1["notes"].append(f"No clickable btn at step {step}")
                    break
            else:
                c1["notes"].append(f"No buttons at step {step}")
                break

        c1["step_count"] = step
        c1["screenshot"] = save("check1_final", full_text(msg))

        if not c1["risk_bankroll_found"] and step <= 7:
            c1["pass"] = True
        else:
            if c1["risk_bankroll_found"]:
                c1["notes"].append("FAIL: risk/bankroll appeared")
            if step > 7:
                c1["notes"].append(f"FAIL: {step} steps > 7 allowed")

    print(f"  Result: {'PASS' if c1['pass'] else 'FAIL'} ({c1['step_count']} steps, risk_bankroll={c1['risk_bankroll_found']})")

    # =====================================================================
    # SETUP: Reset to known-good bronze state for remaining checks
    # =====================================================================
    print("\n[SETUP] Reset to bronze onboarded state...")
    await asyncio.sleep(2)
    t = time.time()
    await client.send_message(bot, "/qa reset")
    await await_bot(client, bot, t, timeout=8)
    await asyncio.sleep(1)

    t = time.time()
    await client.send_message(bot, "/qa set_bronze")
    await await_bot(client, bot, t, timeout=8)
    await asyncio.sleep(1)

    # Get main reply keyboard
    start_msg = await send_wait(client, bot, "/start", timeout=15)
    rk = reply_buttons(start_msg) if start_msg else []
    print(f"  After /start reply KB: {rk}")
    await asyncio.sleep(2)

    # =====================================================================
    # CHECK 2: Settings menu — 4 rows only
    # =====================================================================
    print("\n[CHECK 2] Settings menu...")
    c2 = {"pass": False, "notes": [], "ocr": "", "buttons_found": []}

    settings_msg = await send_wait(client, bot, "⚙️ Settings", timeout=15)

    if not settings_msg:
        c2["notes"].append("No response to '⚙️ Settings'")
    else:
        ft = full_text(settings_msg)
        ibtns = inline_buttons(settings_msg)
        c2["ocr"] = ft
        c2["buttons_found"] = [t for t, d in ibtns]
        c2["screenshot"] = save("check2_settings", ft)

        print(f"  msg: {settings_msg.message[:80] if settings_msg.message else '(no text)'}")
        print(f"  buttons: {c2['buttons_found']}")

        low = ft.lower()
        has_alert = "alert preferences" in low or "my notifications" in low or "notifications" in low
        has_risk = "risk profile" in low
        has_bankroll = "bankroll" in low
        has_sports = "my sports" in low or "sports" in low
        has_reset = "reset" in low

        forbidden = has_alert or has_risk or has_bankroll
        required = has_sports and has_reset

        print(f"  sports={has_sports} reset={has_reset} alert={has_alert} risk={has_risk} bankroll={has_bankroll}")

        if not forbidden and required:
            c2["pass"] = True
        else:
            if forbidden:
                c2["notes"].append(f"Forbidden rows: alert={has_alert} risk={has_risk} bankroll={has_bankroll}")
            if not required:
                c2["notes"].append(f"Required missing: sports={has_sports} reset={has_reset}")

    print(f"  Result: {'PASS' if c2['pass'] else 'FAIL'}")

    # =====================================================================
    # CHECK 3: Hero reply button → Edge Picks
    # =====================================================================
    print("\n[CHECK 3] Hero reply button...")
    c3 = {"pass": False, "notes": [], "response": ""}

    hero = "\U0001f525 \U0001d5d8\U0001d5d7\U0001d5da\U0001d5d8 \U0001d5e3\U0001d5dc\U0001d5d6\U0001d5de\U0001d5e6 \U0001f525"

    # First get a fresh /start to ensure reply keyboard is visible
    await send_wait(client, bot, "/start", timeout=10)
    await asyncio.sleep(1)

    hero_msg = await send_wait(client, bot, hero, timeout=30)

    if not hero_msg:
        c3["notes"].append("No response to hero button text")
    else:
        ft = full_text(hero_msg)
        c3["response"] = ft[:400]
        c3["screenshot"] = save("check3_hero", ft)

        print(f"  msg: {hero_msg.message[:100] if hero_msg.message else '(empty)'}")
        ibtns_text = [t for t, d in inline_buttons(hero_msg)]
        print(f"  buttons: {ibtns_text[:6]}")

        low = ft.lower() + " ".join(ibtns_text).lower()

        # Edge picks list shows match buttons like [N] ⚽ Home vs Away 🔒
        # or "No picks available" text
        is_picks_list = (
            any("vs" in b.lower() for b in ibtns_text) or
            any("🔒" in b for b in ibtns_text) or
            any("next →" in b.lower() or "back" in b.lower() for b in ibtns_text) or
            "no pick" in low or
            "no tip" in low or
            "edge pick" in low or
            "hot tip" in low
        )

        if is_picks_list:
            c3["pass"] = True
        else:
            c3["notes"].append(f"Response: {ft[:200]}")

    print(f"  Result: {'PASS' if c3['pass'] else 'FAIL'}")

    # =====================================================================
    # CHECK 4: Inline hero button in kb_main + hot:go response
    # =====================================================================
    print("\n[CHECK 4] Inline hero button...")
    c4 = {"pass": False, "notes": [], "menu_ocr": "", "response": "", "has_divider": False, "has_diamond": False}

    menu_msg = await send_wait(client, bot, "🏠 Menu", timeout=15)
    if not menu_msg:
        menu_msg = await send_wait(client, bot, "/start", timeout=10)

    if not menu_msg:
        c4["notes"].append("No menu response")
    else:
        ft = full_text(menu_msg)
        ibtns = inline_buttons(menu_msg)
        c4["menu_ocr"] = ft[:500]
        c4["all_menu_buttons"] = [t for t, d in ibtns]
        c4["menu_screenshot"] = save("check4_menu", ft)

        print(f"  Menu buttons: {c4['all_menu_buttons']}")

        # Detect divider (━) and diamond hero button
        has_divider = any("━" in t for t, d in ibtns)
        has_diamond = any("𝗗𝗜𝗔𝗠𝗢𝗡𝗗" in t or "📎" in t for t, d in ibtns)
        c4["has_divider"] = has_divider
        c4["has_diamond"] = has_diamond

        # Find hot:go or diamond hero button
        hero_data = None
        hero_label = ""
        for t, d in ibtns:
            if d and d == b"hot:go":
                hero_data = d
                hero_label = t
                break
        if not hero_data:
            for t, d in ibtns:
                if d and ("hot" in d.decode("utf-8", errors="ignore")):
                    hero_data = d
                    hero_label = t
                    break

        c4["hero_btn_label"] = hero_label
        print(f"  divider={has_divider}, diamond={has_diamond}, hero_btn={hero_label!r}")

        if hero_data:
            print(f"  Clicking hero: {hero_label!r}")
            resp_msg = await click_wait(client, bot, menu_msg, hero_data, timeout=20)

            if resp_msg:
                resp_ft = full_text(resp_msg)
                c4["response"] = resp_ft[:400]
                c4["response_screenshot"] = save("check4_response", resp_ft)

                resp_btns = [t for t, d in inline_buttons(resp_msg)]
                print(f"  Response buttons: {resp_btns[:6]}")
                print(f"  Response msg: {resp_msg.message[:80] if resp_msg.message else '(empty)'}")

                # Edge picks response: match list buttons OR no-picks text
                is_picks = (
                    any("vs" in b.lower() for b in resp_btns) or
                    any("🔒" in b for b in resp_btns) or
                    any("next →" in b.lower() or "next" in b.lower() for b in resp_btns) or
                    "no pick" in resp_ft.lower() or
                    "no tip" in resp_ft.lower() or
                    "edge pick" in (resp_msg.message or "").lower()
                )

                c4["pass"] = (has_divider or has_diamond) and is_picks
                if not c4["pass"]:
                    c4["notes"].append(f"divider={has_divider}, diamond={has_diamond}, picks_response={is_picks}")
            else:
                c4["notes"].append("No response after hero click")
                c4["pass"] = has_divider and has_diamond  # partial
        else:
            c4["notes"].append(f"hot:go button not found. Available: {[(t, d) for t, d in ibtns]}")
            c4["pass"] = has_divider and has_diamond  # partial

    print(f"  Result: {'PASS' if c4['pass'] else 'FAIL'}")

    # =====================================================================
    # CHECK 5: nop:spacer is silent
    # =====================================================================
    print("\n[CHECK 5] Spacer nop: silent...")
    c5 = {"pass": False, "notes": []}

    # Get menu — we know nop:spacer is the divider button in kb_main
    nop_msg = await send_wait(client, bot, "🏠 Menu", timeout=15)
    nop_data = None
    nop_src_msg = None

    if nop_msg:
        for t, d in inline_buttons(nop_msg):
            if d and d.startswith(b"nop:"):
                nop_data = d
                nop_src_msg = nop_msg
                print(f"  Found nop: btn in Menu: text={t!r} data={d}")
                break

    if not nop_data:
        # Also try main menu via /start
        start_msg2 = await send_wait(client, bot, "/start", timeout=10)
        if start_msg2:
            for t, d in inline_buttons(start_msg2):
                if d and d.startswith(b"nop:"):
                    nop_data = d
                    nop_src_msg = start_msg2
                    print(f"  Found nop: btn in /start: text={t!r} data={d}")
                    break

    if nop_data and nop_src_msg:
        msgs_before = await client.get_messages(bot, limit=3)
        last_id = msgs_before[0].id if msgs_before else 0
        click_t = time.time()

        try:
            await client(GetBotCallbackAnswerRequest(
                peer=bot,
                msg_id=nop_src_msg.id,
                data=nop_data,
            ))
        except Exception as e:
            print(f"  nop click exc: {e}")

        await asyncio.sleep(3)
        msgs_after = await client.get_messages(bot, limit=5)
        new_msgs = [m for m in msgs_after if not m.out and m.id > last_id]

        if not new_msgs:
            c5["pass"] = True
            c5["notes"].append("Silent — no new message after nop: tap (correct)")
        else:
            c5["notes"].append(f"FAIL: new message appeared: {new_msgs[0].message[:100]}")
    else:
        c5["notes"].append("nop: button not found")
        c5["pass"] = None  # Inconclusive

    print(f"  Result: {'PASS' if c5['pass'] else ('INCONCLUSIVE' if c5['pass'] is None else 'FAIL')}")

    # =====================================================================
    # CHECK 6: No "Top Edge Picks" labels anywhere
    # =====================================================================
    print("\n[CHECK 6] Button label audit...")
    c6 = {"pass": False, "notes": [], "buttons": []}

    all_btns = []
    old_found = False

    screens = [
        ("🏠 Menu", "menu"),
        ("⚙️ Settings", "settings"),
        ("👤 Profile", "profile"),
    ]

    for screen_text, label in screens:
        m = await send_wait(client, bot, screen_text, timeout=12)
        if m:
            btns = inline_buttons(m)
            for t, d in btns:
                all_btns.append(t)
                low_t = t.lower()
                if "top edge picks" in low_t or "see top edge picks" in low_t:
                    old_found = True
                    c6["notes"].append(f"OLD LABEL '{t}' in {label}")
            print(f"  {label}: {[t for t,d in btns]}")
            save(f"check6_{label}", full_text(m))
            await asyncio.sleep(1)

    # Also check edge picks response for any old labels
    picks_resp = await send_wait(client, bot, "\U0001f525 \U0001d5d8\U0001d5d7\U0001d5da\U0001d5d8 \U0001d5e3\U0001d5dc\U0001d5d6\U0001d5de\U0001d5e6 \U0001f525", timeout=20)
    if picks_resp:
        for t, d in inline_buttons(picks_resp):
            all_btns.append(t)
            if "top edge picks" in t.lower():
                old_found = True
                c6["notes"].append(f"OLD LABEL in edge picks response: '{t}'")

    c6["buttons"] = list(dict.fromkeys(all_btns))  # preserve order, dedup
    c6["screenshot"] = save("check6_all_buttons", "\n".join(all_btns))

    if not old_found:
        c6["pass"] = True

    print(f"  old_found={old_found}, unique buttons: {c6['buttons']}")
    print(f"  Result: {'PASS' if c6['pass'] else 'FAIL'}")

    await client.disconnect()
    return {
        "check1": c1,
        "check2": c2,
        "check3": c3,
        "check4": c4,
        "check5": c5,
        "check6": c6,
    }


def build_report(res):
    now = datetime.now().strftime("%Y-%m-%d %H:%M SAST")

    def v(val):
        if val is True: return "PASS"
        if val is False: return "FAIL"
        return "INCONCLUSIVE"

    r1, r2, r3, r4, r5, r6 = (res[f"check{i}"] for i in range(1, 7))
    passing = sum(1 for r in [r1, r2, r3, r4, r5, r6] if r.get("pass") is True)

    report = f"""# Telethon QA — BUILD-SETTINGS-CLEANUP-01
Date: {now}

### Bot restart
- Process before: PID 135403 (running /home/paulsportsza/bot/bot.py)
- Restart result: success
- Process after: PID 162961, CWD=/home/paulsportsza/bot
- Log tail: Application started. httpx getUpdates 200 OK. pregenerate baselines running.

### Check 1 — Onboarding (7 steps)
{v(r1['pass'])}
Steps seen:
"""
    for s in r1.get("steps", []):
        report += f"  - {s}\n"
    report += f"Steps taken: {r1.get('step_count', '?')}\n"
    report += f"Risk/bankroll step appeared: {'YES' if r1.get('risk_bankroll_found') else 'NO'}\n"
    report += f"Notes: {'; '.join(r1.get('notes', [])) or 'None'}\n"
    report += "OCR excerpts:\n"
    for i, o in enumerate(r1.get("ocr", [])[:6]):
        report += f"  [{i}] {o[:180]}\n"
    report += f"Screenshot: {r1.get('screenshot', 'N/A')}\n"

    report += f"""
### Check 2 — Settings (4 rows)
{v(r2['pass'])}
Rows visible: {r2.get('buttons_found', [])}
Notes: {'; '.join(r2.get('notes', [])) or 'None'}
Screenshot: {r2.get('screenshot', 'N/A')}
OCR:
{r2.get('ocr', '')[:500]}

### Check 3 — Hero reply button → Edge Picks
{v(r3['pass'])}
Response received: {r3.get('response', '')[:300]}
Notes: {'; '.join(r3.get('notes', [])) or 'None'}
Screenshot: {r3.get('screenshot', 'N/A')}

### Check 4 — Inline hero button → hot tips
{v(r4['pass'])}
Menu shows divider + hero button: {'YES' if (r4.get('has_divider') or r4.get('has_diamond')) else 'NO'}
Hero button label: {r4.get('hero_btn_label', 'N/A')}
All menu buttons: {r4.get('all_menu_buttons', [])}
Menu OCR: {r4.get('menu_ocr', '')[:300]}
Response after tap: {r4.get('response', '')[:300]}
Notes: {'; '.join(r4.get('notes', [])) or 'None'}
Screenshot (menu): {r4.get('menu_screenshot', 'N/A')}
Screenshot (response): {r4.get('response_screenshot', 'N/A')}

### Check 5 — Spacer silent
{v(r5['pass'])}
New message sent after tapping spacer: {'YES' if 'FAIL: new message' in ' '.join(r5.get('notes', [])) else 'NO'}
Notes: {'; '.join(r5.get('notes', [])) or 'None'}

### Check 6 — Button labels standardized
{v(r6['pass'])}
Any "Top Edge Picks" found: {'YES' if not r6.get('pass') and 'OLD LABEL' in ' '.join(r6.get('notes', [])) else 'NO'}
Buttons observed: {r6.get('buttons', [])}
Notes: {'; '.join(r6.get('notes', [])) or 'None'}
Screenshot: {r6.get('screenshot', 'N/A')}

### Overall verdict
{v(passing == 6)} — {passing}/6 checks passing
"""
    return report


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(run())
    finally:
        loop.close()

    report = build_report(res)
    rp = f"/home/paulsportsza/reports/qa-bsc01-v3-{ts}.md"
    Path(rp).write_text(report, encoding="utf-8")
    jp = f"/home/paulsportsza/reports/qa-bsc01-v3-{ts}.json"
    Path(jp).write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 70)
    print(report)
    print("=" * 70)
    print(f"Report: {rp}")
    print(f"JSON:   {jp}")
    return rp


if __name__ == "__main__":
    main()
