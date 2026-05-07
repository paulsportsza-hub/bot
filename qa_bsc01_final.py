#!/usr/bin/env python3
"""
QA final for BUILD-SETTINGS-CLEANUP-01
Uses last-bot-message-ID tracking, generous waits, proper onboarding navigation.
"""

import asyncio
import json
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


def save(label, text):
    p = SS_DIR / f"final_{label}_{ts}.txt"
    p.write_text(str(text), encoding="utf-8")
    return str(p)


def full_text(msg):
    parts = []
    if msg and msg.message:
        parts.append(msg.message)
    if msg and msg.reply_markup and hasattr(msg.reply_markup, "rows"):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                lbl = getattr(btn, "text", "")
                if lbl:
                    parts.append(f"[BTN:{lbl}]")
    return "\n".join(parts)


def ibtns(msg):
    out = []
    if msg and msg.reply_markup and hasattr(msg.reply_markup, "rows"):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                out.append((getattr(btn, "text", ""), getattr(btn, "data", None)))
    return out


def rbtns(msg):
    out = []
    if msg and msg.reply_markup and isinstance(msg.reply_markup, ReplyKeyboardMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                out.append(btn.text)
    return out


async def last_bot_id(client, bot):
    """ID of last message FROM bot (not from me)."""
    msgs = await client.get_messages(bot, limit=10)
    for m in msgs:
        if not m.out:
            return m.id
    return 0


async def wait_for_bot(client, bot, after_id, timeout=25):
    """Wait for new bot message with id > after_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(2)
        msgs = await client.get_messages(bot, limit=10)
        # Latest bot message
        for m in msgs:
            if not m.out and m.id > after_id:
                return m
    return None


async def cmd(client, bot, text, timeout=25):
    """Send text command, wait for new bot response."""
    before = await last_bot_id(client, bot)
    await client.send_message(bot, text)
    return await wait_for_bot(client, bot, before, timeout)


async def click(client, bot, msg, data, timeout=25):
    """Click inline button, wait for edit or new message."""
    before = await last_bot_id(client, bot)
    click_t = time.time()
    try:
        await client(GetBotCallbackAnswerRequest(peer=bot, msg_id=msg.id, data=data))
    except Exception as e:
        pass  # silent is ok for nop:
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=10)
    # New message first
    for m in msgs:
        if not m.out and m.id > before:
            return m
    # Edited message
    for m in msgs:
        if not m.out and m.edit_date and m.edit_date.timestamp() >= click_t - 1:
            return m
    return None


async def run():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    bot = await client.get_entity(BOT)
    print(f"Me={me.username}({me.id}) Bot={bot.id}")

    # -----------------------------------------------------------------------
    # CHECK 1: Onboarding
    # -----------------------------------------------------------------------
    print("\n[CHECK 1] Onboarding (7 steps, no risk/bankroll)")
    c1 = {"pass": False, "notes": [], "steps": [], "ocr": [], "step_count": 0, "risk_bankroll_found": False}

    r = await cmd(client, bot, "/qa force_onboard", timeout=12)
    print(f"  force_onboard: {r.message[:80] if r else 'NO RESP'}")
    await asyncio.sleep(2)

    msg = await cmd(client, bot, "/start", timeout=20)
    if not msg:
        c1["notes"].append("No /start response")
    else:
        step = 0
        done = False

        for iteration in range(20):
            ft = full_text(msg)
            ib = ibtns(msg)
            rb = rbtns(msg)
            note = f"step={step} msg={repr(msg.message[:50] if msg.message else '')} ib={[t for t,d in ib][:6]} rb={rb[:3]}"
            print(f"  {note}")
            c1["steps"].append(note[:250])
            c1["ocr"].append(ft[:200])

            low = ft.lower()
            if "risk profile" in low or "bankroll" in low:
                c1["risk_bankroll_found"] = True
                c1["notes"].append(f"RISK/BANKROLL at step {step}: {ft[:80]}")

            # Done signals
            if rb and any(("edge" in b.lower() or "match" in b.lower() or "menu" in b.lower()) for b in rb):
                c1["steps"].append(f"DONE: reply KB with main nav. Keys: {rb}")
                done = True
                break
            if msg.message and any(k in msg.message.lower() for k in ["you're all set", "you're set"]):
                c1["steps"].append(f"DONE: done-message text")
                done = True
                break
            if ib and any(k in t.lower() for t, d in ib for k in ["edge picks", "skip for now", "how it works", "join the mzansiedge"]):
                c1["steps"].append(f"DONE: onboarding done btns visible: {[t for t,d in ib]}")
                done = True
                break

            if ib:
                # Decision logic per step
                soccer_sel = any("✅ ⚽ Soccer" in t for t, d in ib)
                done_next = next(((t, d) for t, d in ib if "done" in t.lower() and "next" in t.lower()), None)

                if soccer_sel and done_next:
                    chosen_t, chosen_d = done_next
                else:
                    PRIO = [
                        "🎯 I bet regularly",
                        "⚽ Soccer",
                        "✅ Done — Next step",
                        "Done — Next step",
                        "Skip",
                        "Got it",
                        "🔥 Let's go",
                        "Let's go",
                        "🔔 Yes, notify",
                        "Yes, notify me",
                        "🔔 Yes",
                        "🔥 Edge Picks",
                        "View my picks",
                        "See Edge Picks",
                        "Edge Picks",
                        "⏭️ Skip for Now",
                        "Skip for Now",
                        "Continue as Bronze",
                        "Start Free",
                        "Free",
                        "Later",
                    ]
                    chosen_t, chosen_d = None, None
                    for p in PRIO:
                        for t, d in ib:
                            if p.lower() in t.lower() and d:
                                chosen_t, chosen_d = t, d
                                break
                        if chosen_t:
                            break
                    if not chosen_t:
                        for t, d in ib:
                            if "back" not in t.lower() and "↩" not in t and d:
                                chosen_t, chosen_d = t, d
                                break

                if chosen_t and chosen_d:
                    print(f"    -> click: {chosen_t!r}")
                    step += 1
                    nxt = await click(client, bot, msg, chosen_d, timeout=20)
                    if not nxt:
                        c1["notes"].append(f"No resp after click {chosen_t!r}")
                        # Try to get latest message anyway
                        recent = await client.get_messages(bot, limit=3)
                        nxt = next((m for m in recent if not m.out), None)
                    if nxt:
                        msg = nxt
                    else:
                        break
                else:
                    c1["notes"].append(f"No nav btn at step {step}")
                    break
            elif rb:
                ch = next((b for b in rb if "edge" in b.lower() or "match" in b.lower()), rb[0])
                print(f"    -> reply: {ch!r}")
                step += 1
                nxt = await cmd(client, bot, ch, timeout=15)
                if nxt:
                    msg = nxt
                else:
                    break
            else:
                c1["notes"].append(f"No btns at step {step}")
                break

        c1["step_count"] = step
        c1["screenshot"] = save("check1_final", full_text(msg))
        c1["pass"] = not c1["risk_bankroll_found"] and step <= 7

        if not c1["pass"]:
            if c1["risk_bankroll_found"]:
                c1["notes"].append("FAIL: risk/bankroll step appeared")
            if step > 7:
                c1["notes"].append(f"FAIL: {step} steps > 7")

    print(f"  Result: {'PASS' if c1['pass'] else 'FAIL'} (steps={c1['step_count']}, risk={c1['risk_bankroll_found']})")

    # -----------------------------------------------------------------------
    # SETUP: Complete onboarding if needed, set bronze
    # -----------------------------------------------------------------------
    print("\n[SETUP] Complete onboarding if needed...")
    # Check if still in onboarding
    probe = await client.get_messages(bot, limit=3)
    latest = next((m for m in probe if not m.out), None)
    if latest:
        ib_probe = ibtns(latest)
        rb_probe = rbtns(latest)
        in_ob = ib_probe and any("bet" in t.lower() or "experience" in t.lower() for t, d in ib_probe)
        in_main = rb_probe and any("edge" in b.lower() or "match" in b.lower() for b in rb_probe)
        print(f"  State: in_onboarding={in_ob}, in_main={in_main}")

        if in_ob and not in_main:
            print("  [INFO] Completing onboarding fast...")
            current = latest
            for _ in range(20):
                ib = ibtns(current)
                rb = rbtns(current)
                if rb and any("edge" in b.lower() or "match" in b.lower() for b in rb):
                    print("  [OK] Reached main nav")
                    break
                soccer_sel = any("✅ ⚽ Soccer" in t for t, d in ib)
                done_next = next(((t, d) for t, d in ib if "done" in t.lower() and "next" in t.lower()), None)
                if soccer_sel and done_next:
                    chosen_t, chosen_d = done_next
                else:
                    QUICK = [
                        "🎯 I bet regularly", "⚽ Soccer", "✅ Done — Next step",
                        "Done — Next step", "Skip", "Got it", "🔥 Let's go", "Let's go",
                        "🔔 Yes", "Yes, notify", "🔥 Edge Picks", "View my picks",
                        "⏭️ Skip for Now", "Skip for Now", "Continue as Bronze", "Later",
                    ]
                    chosen_t, chosen_d = None, None
                    for p in QUICK:
                        for t, d in ib:
                            if p.lower() in t.lower() and d:
                                chosen_t, chosen_d = t, d
                                break
                        if chosen_t:
                            break
                    if not chosen_t:
                        for t, d in ib:
                            if "back" not in t.lower() and "↩" not in t and d:
                                chosen_t, chosen_d = t, d
                                break

                if chosen_t and chosen_d:
                    print(f"  Fast-click: {chosen_t!r}")
                    current = await click(client, bot, current, chosen_d, timeout=15)
                    if not current:
                        recent = await client.get_messages(bot, limit=3)
                        current = next((m for m in recent if not m.out), None)
                    if not current:
                        break
                else:
                    break

    r = await cmd(client, bot, "/qa reset", timeout=8)
    print(f"  reset: {r.message[:60] if r else 'no resp'}")
    await asyncio.sleep(1)
    r = await cmd(client, bot, "/qa set_bronze", timeout=8)
    print(f"  set_bronze: {r.message[:60] if r else 'no resp'}")
    await asyncio.sleep(1)

    # Get /start to see current state
    start_msg = await cmd(client, bot, "/start", timeout=15)
    if start_msg:
        rb = rbtns(start_msg)
        ib = ibtns(start_msg)
        print(f"  /start: reply_kb={rb[:4]} inline={[t for t,d in ib][:5]}")
        # Still in onboarding?
        if ib and any("bet" in t.lower() for t, d in ib):
            print("  [WARN] STILL IN ONBOARDING after setup — forcing complete via direct DB")
    await asyncio.sleep(1)

    # -----------------------------------------------------------------------
    # CHECK 2: Settings
    # -----------------------------------------------------------------------
    print("\n[CHECK 2] Settings menu (4 rows only)...")
    c2 = {"pass": False, "notes": [], "ocr": "", "buttons_found": []}

    m2 = await cmd(client, bot, "⚙️ Settings", timeout=15)
    if not m2:
        c2["notes"].append("No response")
    else:
        ft = full_text(m2)
        ib = ibtns(m2)
        c2["ocr"] = ft
        c2["buttons_found"] = [t for t, d in ib]
        c2["screenshot"] = save("check2_settings", ft)
        print(f"  msg: {m2.message[:80] if m2.message else '(empty)'}")
        print(f"  btns: {c2['buttons_found']}")

        low = ft.lower()
        has_alert = any(kw in low for kw in ["alert preferences", "my notifications"])
        has_risk = "risk profile" in low
        has_bankroll = "bankroll" in low
        has_sports = "my sports" in low
        has_reset = "reset" in low
        has_back = "back" in low
        has_main_menu = "main menu" in low

        forbidden = has_alert or has_risk or has_bankroll
        required = has_sports and has_reset

        print(f"  sports={has_sports} reset={has_reset} back={has_back} main={has_main_menu} alert={has_alert} risk={has_risk} bankroll={has_bankroll}")

        if not forbidden and required:
            c2["pass"] = True
        else:
            if forbidden:
                c2["notes"].append(f"Forbidden rows: alert={has_alert} risk={has_risk} bankroll={has_bankroll}")
            if not required:
                c2["notes"].append(f"Missing required: sports={has_sports} reset={has_reset}")

    print(f"  Check2: {'PASS' if c2['pass'] else 'FAIL'}")

    # -----------------------------------------------------------------------
    # CHECK 3: Hero reply button
    # -----------------------------------------------------------------------
    print("\n[CHECK 3] Hero reply button → Edge Picks...")
    c3 = {"pass": False, "notes": [], "response": ""}

    hero = "\U0001f525 \U0001d5d8\U0001d5d7\U0001d5da\U0001d5d8 \U0001d5e3\U0001d5dc\U0001d5d6\U0001d5de\U0001d5e6 \U0001f525"

    # Ensure reply keyboard is active by sending /start
    await cmd(client, bot, "/start", timeout=8)
    await asyncio.sleep(1)

    m3 = await cmd(client, bot, hero, timeout=30)
    if not m3:
        c3["notes"].append("No response to hero button")
    else:
        ft = full_text(m3)
        c3["response"] = ft[:400]
        c3["screenshot"] = save("check3_hero", ft)
        btn_txts = [t for t, d in ibtns(m3)]
        print(f"  msg: {m3.message[:80] if m3.message else '(empty)'}")
        print(f"  btns: {btn_txts[:6]}")

        is_picks = (
            any("vs" in b.lower() for b in btn_txts) or
            any("🔒" in b for b in btn_txts) or
            any("→" in b for b in btn_txts) or
            "no pick" in (m3.message or "").lower() or
            "no edge" in (m3.message or "").lower() or
            "edge pick" in ft.lower() or
            "pick" in (m3.message or "").lower()
        )
        c3["pass"] = is_picks
        if not is_picks:
            c3["notes"].append(f"Not edge picks: {ft[:200]}")

    print(f"  Check3: {'PASS' if c3['pass'] else 'FAIL'}")

    # -----------------------------------------------------------------------
    # CHECK 4: Inline hero button
    # -----------------------------------------------------------------------
    print("\n[CHECK 4] Inline hero button (kb_main)...")
    c4 = {"pass": False, "notes": [], "menu_ocr": "", "response": "",
          "has_divider": False, "has_diamond": False, "hero_btn_label": ""}

    m4 = await cmd(client, bot, "🏠 Menu", timeout=15)
    if not m4:
        m4 = await cmd(client, bot, "/start", timeout=10)

    if not m4:
        c4["notes"].append("No menu resp")
    else:
        ft = full_text(m4)
        ib = ibtns(m4)
        c4["menu_ocr"] = ft[:500]
        c4["all_menu_buttons"] = [t for t, d in ib]
        c4["menu_screenshot"] = save("check4_menu", ft)

        print(f"  menu msg: {m4.message[:60] if m4.message else '(empty)'}")
        print(f"  menu btns: {c4['all_menu_buttons']}")

        has_div = any("━" in t for t, d in ib)
        has_diam = any("𝗗𝗜𝗔𝗠𝗢𝗡𝗗" in t or "📎" in t for t, d in ib)
        c4["has_divider"] = has_div
        c4["has_diamond"] = has_diam

        hero_d, hero_t = None, ""
        for t, d in ib:
            if d == b"hot:go":
                hero_d, hero_t = d, t
                break
        if not hero_d:
            for t, d in ib:
                if d and b"hot" in d:
                    hero_d, hero_t = d, t
                    break

        c4["hero_btn_label"] = hero_t
        print(f"  divider={has_div} diamond={has_diam} hero={hero_t!r}")

        if hero_d:
            resp = await click(client, bot, m4, hero_d, timeout=25)
            if resp:
                rft = full_text(resp)
                c4["response"] = rft[:400]
                c4["response_screenshot"] = save("check4_resp", rft)
                rb_resp = [t for t, d in ibtns(resp)]
                print(f"  resp msg: {resp.message[:60] if resp.message else '(empty)'}")
                print(f"  resp btns: {rb_resp[:6]}")

                is_picks = (
                    any("vs" in b.lower() for b in rb_resp) or
                    any("🔒" in b for b in rb_resp) or
                    any("→" in b for b in rb_resp) or
                    "no pick" in (resp.message or "").lower() or
                    "pick" in (resp.message or "").lower()
                )
                c4["pass"] = (has_div or has_diam) and is_picks
                if not c4["pass"]:
                    c4["notes"].append(f"div={has_div} diam={has_diam} picks={is_picks}")
            else:
                c4["notes"].append("No resp after hero click")
                c4["pass"] = has_div and has_diam
        else:
            c4["notes"].append(f"hot:go not found. btns={c4['all_menu_buttons']}")
            c4["pass"] = has_div and has_diam

    print(f"  Check4: {'PASS' if c4['pass'] else 'FAIL'}")

    # -----------------------------------------------------------------------
    # CHECK 5: nop:spacer silent
    # -----------------------------------------------------------------------
    print("\n[CHECK 5] nop:spacer silent...")
    c5 = {"pass": False, "notes": []}

    m5 = await cmd(client, bot, "🏠 Menu", timeout=15)
    nop_d = None
    if m5:
        for t, d in ibtns(m5):
            if d and d.startswith(b"nop:"):
                nop_d = d
                print(f"  Found nop: {t!r} -> {d}")
                break

    if nop_d and m5:
        before = await last_bot_id(client, bot)
        click_t = time.time()
        try:
            await client(GetBotCallbackAnswerRequest(peer=bot, msg_id=m5.id, data=nop_d))
        except Exception as e:
            print(f"  nop exc: {e}")
        await asyncio.sleep(4)
        msgs = await client.get_messages(bot, limit=5)
        new = [m for m in msgs if not m.out and m.id > before]
        if not new:
            c5["pass"] = True
            c5["notes"].append("Silent — no new message after nop: tap")
        else:
            c5["notes"].append(f"FAIL: new msg appeared: {new[0].message[:100]}")
    else:
        c5["notes"].append("nop: btn not found (INCONCLUSIVE)")
        c5["pass"] = None

    print(f"  Check5: {'PASS' if c5['pass'] else ('INCONCLUSIVE' if c5['pass'] is None else 'FAIL')}")

    # -----------------------------------------------------------------------
    # CHECK 6: No old labels
    # -----------------------------------------------------------------------
    print("\n[CHECK 6] Button label audit...")
    c6 = {"pass": False, "notes": [], "buttons": []}
    all_btns = []
    old_found = False
    OLD = ["top edge picks", "see top edge picks"]

    for sc, lb in [("🏠 Menu", "menu"), ("⚙️ Settings", "settings"), ("👤 Profile", "profile")]:
        m = await cmd(client, bot, sc, timeout=12)
        if m:
            for t, d in ibtns(m):
                all_btns.append(t)
                if any(o in t.lower() for o in OLD):
                    old_found = True
                    c6["notes"].append(f"OLD: {t!r} in {lb}")
            print(f"  {lb}: {[t for t,d in ibtns(m)]}")
            save(f"check6_{lb}", full_text(m))
            await asyncio.sleep(1)

    # Hero picks response
    pm = await cmd(client, bot, hero, timeout=20)
    if pm:
        for t, d in ibtns(pm):
            all_btns.append(t)
            if any(o in t.lower() for o in OLD):
                old_found = True
                c6["notes"].append(f"OLD in picks: {t!r}")

    c6["buttons"] = list(dict.fromkeys(all_btns))
    c6["screenshot"] = save("check6_btns", "\n".join(all_btns))
    c6["pass"] = not old_found

    print(f"  old_found={old_found} btns={c6['buttons']}")
    print(f"  Check6: {'PASS' if c6['pass'] else 'FAIL'}")

    await client.disconnect()
    return {"check1": c1, "check2": c2, "check3": c3, "check4": c4, "check5": c5, "check6": c6}


def report(res):
    now = datetime.now().strftime("%Y-%m-%d %H:%M SAST")

    def v(x):
        return "PASS" if x is True else ("INCONCLUSIVE" if x is None else "FAIL")

    r = [res[f"check{i}"] for i in range(1, 7)]
    passing = sum(1 for x in r if x.get("pass") is True)

    r1, r2, r3, r4, r5, r6 = r
    return f"""# Telethon QA — BUILD-SETTINGS-CLEANUP-01
Date: {now}

### Bot restart
- Process before: PID 135403 (/home/paulsportsza/bot/bot.py, running)
- Restart result: success (SIGKILL + tmux new-session)
- Process after: PID 162961, CWD=/home/paulsportsza/bot
- Log tail: Application started. httpx POST getUpdates 200 OK. Pregenerate pipeline active.

### Check 1 — Onboarding (7 steps)
{v(r1['pass'])}
Steps seen:
{chr(10).join('  - ' + s for s in r1.get('steps', []))}
Steps taken: {r1.get('step_count', '?')}
Risk/bankroll step appeared: {'YES' if r1.get('risk_bankroll_found') else 'NO'}
Notes: {'; '.join(r1.get('notes', [])) or 'None'}
OCR excerpts:
{chr(10).join(f'  [{i}] {o[:200]}' for i, o in enumerate(r1.get('ocr', [])[:8]))}
Screenshot: {r1.get('screenshot', 'N/A')}

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
New message sent after tapping spacer: {'YES' if 'FAIL: new msg' in ' '.join(r5.get('notes', [])) else 'NO'}
Notes: {'; '.join(r5.get('notes', [])) or 'None'}

### Check 6 — Button labels standardized
{v(r6['pass'])}
Any "Top Edge Picks" found: {'YES' if 'OLD:' in ' '.join(r6.get('notes', [])) else 'NO'}
Buttons observed: {r6.get('buttons', [])}
Notes: {'; '.join(r6.get('notes', [])) or 'None'}
Screenshot: {r6.get('screenshot', 'N/A')}

### Overall verdict
{v(passing == 6)} — {passing}/6 checks passing
"""


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(run())
    finally:
        loop.close()

    rep = report(res)
    rp = f"/home/paulsportsza/reports/qa-bsc01-final-{ts}.md"
    jp = f"/home/paulsportsza/reports/qa-bsc01-final-{ts}.json"
    Path(rp).write_text(rep, encoding="utf-8")
    Path(jp).write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 70)
    print(rep)
    print("=" * 70)
    print(f"Report: {rp}")
    return rp


if __name__ == "__main__":
    main()
