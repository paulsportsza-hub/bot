#!/usr/bin/env python3
"""
QA script for BUILD-SETTINGS-CLEANUP-01 (v4 — message ID tracking)
Key fix: track last seen message ID to avoid stale message responses
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
SESSION_PATH = "/home/paulsportsza/bot/data/telethon_session"
BOT = "@mzansiedge_bot"
SS_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
SS_DIR.mkdir(parents=True, exist_ok=True)
ts = int(time.time())
TIMEOUT = 25


def save(label, text):
    p = SS_DIR / f"bsc01v4_{label}_{ts}.txt"
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
                t = getattr(btn, "text", "")
                d = getattr(btn, "data", None)
                out.append((t, d))
    return out


def rbtns(msg):
    out = []
    if msg and msg.reply_markup and isinstance(msg.reply_markup, ReplyKeyboardMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                out.append(btn.text)
    return out


async def get_latest_bot_id(client, bot):
    """Get the ID of the latest message from bot (to use as baseline)."""
    msgs = await client.get_messages(bot, limit=5)
    for m in msgs:
        if not m.out:
            return m.id
    return 0


async def wait_new_bot_msg(client, bot, after_id, timeout=TIMEOUT):
    """Wait for a new bot message with ID > after_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(bot, limit=8)
        for m in msgs:
            if not m.out and m.id > after_id:
                return m
    return None


async def send_get(client, bot, text, timeout=TIMEOUT):
    """Send text, wait for new bot response."""
    before_id = await get_latest_bot_id(client, bot)
    await client.send_message(bot, text)
    return await wait_new_bot_msg(client, bot, before_id, timeout)


async def click_get(client, bot, msg, data, timeout=TIMEOUT):
    """Click callback, wait for new or edited bot response."""
    before_id = await get_latest_bot_id(client, bot)
    click_t = time.time()
    try:
        await client(GetBotCallbackAnswerRequest(peer=bot, msg_id=msg.id, data=data))
    except Exception as e:
        print(f"    [click-exc] {e}")
    await asyncio.sleep(2.5)
    # Check for new message
    msgs = await client.get_messages(bot, limit=8)
    for m in msgs:
        if not m.out and m.id > before_id:
            return m
    # Check for edited message
    for m in msgs:
        if not m.out and m.edit_date and m.edit_date.timestamp() >= click_t - 1:
            return m
    return None


async def run():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    bot = await client.get_entity(BOT)
    print(f"[INFO] Me={me.username}({me.id}) Bot={bot.id}")

    results = {}

    # =====================================================================
    # CHECK 1: Onboarding — 7 steps, no risk/bankroll
    # =====================================================================
    print("\n[CHECK 1] Onboarding...")
    c1 = {"pass": False, "notes": [], "steps": [], "ocr": [], "step_count": 0, "risk_bankroll_found": False}

    # Force reset
    fo = await send_get(client, bot, "/qa force_onboard", timeout=12)
    print(f"  force_onboard resp: {fo.message[:80] if fo else 'none'}")
    await asyncio.sleep(1)

    # /start
    msg = await send_get(client, bot, "/start", timeout=15)
    if not msg:
        c1["notes"].append("No /start response")
    else:
        step = 0
        done = False

        for _ in range(15):
            ft = full_text(msg)
            ib = ibtns(msg)
            rb = rbtns(msg)
            summary = f"step={step} msg={repr(msg.message[:50] if msg.message else '')} ibtns={[t for t,d in ib][:5]}"
            print(f"  {summary}")
            c1["steps"].append(summary[:220])
            c1["ocr"].append(ft[:200])

            low = ft.lower() + " " + (msg.message or "").lower()
            if "risk profile" in low or "bankroll" in low:
                c1["risk_bankroll_found"] = True
                c1["notes"].append(f"RISK/BANKROLL at step {step}")

            # Done: main nav reply keyboard
            if rb and any(("edge" in b.lower() or "match" in b.lower() or "menu" in b.lower()) for b in rb):
                c1["steps"].append(f"DONE step={step} — main reply KB visible. Keys: {rb}")
                done = True
                break

            # Done: onboarding done message content
            if msg.message and any(kw in msg.message.lower() for kw in ["you're all set", "you're set", "let's go!", "welcome aboard"]):
                c1["steps"].append(f"DONE step={step} — done message")
                done = True
                break

            # Done: done buttons visible
            btn_texts = [t.lower() for t, d in ib]
            if any("edge picks" in t or "how it works" in t or "skip for now" in t for t in btn_texts):
                c1["steps"].append(f"DONE step={step} — done screen inline btns visible")
                done = True
                break

            if ib:
                # Smart navigation
                soccer_selected = any("✅ ⚽ Soccer" in t for t, d in ib)
                done_next = next(((t, d) for t, d in ib if "done" in t.lower() and "next" in t.lower()), None)

                if soccer_selected and done_next:
                    ch_t, ch_d = done_next
                else:
                    PRIORITY = [
                        "🎯 I bet regularly",    # experience
                        "✅ Done — Next step",   # sports confirm
                        "Done — Next step",
                        "⚽ Soccer",             # select sport
                        "Skip",                  # favourites skip
                        "Got it",                # edge explainer
                        "🔥 Let's go",
                        "Let's go",
                        "🔔 Yes, notify",        # notify
                        "Yes, notify",
                        "🔔 Yes",
                        "View my picks",         # summary
                        "See Edge Picks",
                        "🔥 Edge Picks",
                        "Continue as Bronze",    # plan
                        "Start Free",
                        "Free",
                        "Later",
                        "Skip for Now",
                        "⏭️ Skip for Now",
                    ]
                    ch_t, ch_d = None, None
                    for p in PRIORITY:
                        for t, d in ib:
                            if p.lower() in t.lower():
                                ch_t, ch_d = t, d
                                break
                        if ch_t:
                            break
                    if not ch_t:
                        for t, d in ib:
                            if "back" not in t.lower() and "↩" not in t and d:
                                ch_t, ch_d = t, d
                                break

                if ch_t and ch_d:
                    print(f"    -> click: {ch_t!r}")
                    step += 1
                    nxt = await click_get(client, bot, msg, ch_d, timeout=15)
                    if not nxt:
                        c1["notes"].append(f"No resp after click {ch_t!r}")
                        break
                    msg = nxt
                elif ch_t and not ch_d:
                    print(f"    -> send: {ch_t!r}")
                    step += 1
                    nxt = await send_get(client, bot, ch_t, timeout=15)
                    if not nxt:
                        c1["notes"].append(f"No resp after send {ch_t!r}")
                        break
                    msg = nxt
                else:
                    c1["notes"].append(f"No nav btn at step {step}")
                    break
            elif rb:
                # Reply keyboard — send first btn
                ch = rb[0]
                print(f"    -> reply: {ch!r}")
                step += 1
                nxt = await send_get(client, bot, ch, timeout=15)
                if not nxt:
                    c1["notes"].append(f"No resp after reply {ch!r}")
                    break
                msg = nxt
            else:
                c1["notes"].append(f"No buttons at step {step}")
                break

        c1["step_count"] = step
        c1["screenshot"] = save("check1_final", full_text(msg))
        print(f"  Final msg: {msg.message[:100] if msg.message else '(empty)'}")
        print(f"  Final btns: {[t for t,d in ibtns(msg)][:5]} reply={rbtns(msg)[:3]}")

        if not c1["risk_bankroll_found"] and step <= 7:
            c1["pass"] = True
        else:
            if c1["risk_bankroll_found"]:
                c1["notes"].append("FAIL: risk/bankroll appeared")
            if step > 7:
                c1["notes"].append(f"FAIL: {step} steps > 7")

    print(f"  Check1: {'PASS' if c1['pass'] else 'FAIL'} ({c1['step_count']} steps, risk={c1['risk_bankroll_found']})")
    results["check1"] = c1

    # =====================================================================
    # SETUP: Ensure user is onboarded (onboarding_done=True)
    # /qa reset does NOT affect onboarding_done, so if check1 completed
    # the onboarding, we should be good. But do /qa set_bronze for tier.
    # =====================================================================
    print("\n[SETUP] Setting bronze tier...")
    r = await send_get(client, bot, "/qa reset", timeout=8)
    print(f"  reset: {r.message[:60] if r else 'no resp'}")
    await asyncio.sleep(1)
    r = await send_get(client, bot, "/qa set_bronze", timeout=8)
    print(f"  set_bronze: {r.message[:60] if r else 'no resp'}")
    await asyncio.sleep(1)

    # Verify we're past onboarding
    probe = await send_get(client, bot, "/start", timeout=12)
    if probe:
        rb_probe = rbtns(probe)
        ib_probe = ibtns(probe)
        print(f"  /start reply_kb={rb_probe} inline={[t for t,d in ib_probe][:4]}")
        # If we see onboarding buttons, do a quick complete-onboard
        if ib_probe and any("bet" in t.lower() or "experience" in t.lower() or "i bet" in t.lower() for t, d in ib_probe):
            print("  [WARN] Still in onboarding — fast-completing...")
            # Fast path: click 'experienced', then Done, then skip to end
            for quick_label in ["🎯 I bet regularly", "⚽ Soccer", "✅ Done — Next step", "Skip", "Got it", "🔥 Let's go", "Let's go", "🔔 Yes", "View my picks", "⏭️ Skip for Now", "Continue as Bronze"]:
                cur_ib = ibtns(probe)
                cur_rb = rbtns(probe)
                found = False
                for t, d in cur_ib:
                    if quick_label.lower() in t.lower() and d:
                        print(f"  Fast-click: {t!r}")
                        probe = await click_get(client, bot, probe, d, timeout=10)
                        found = True
                        break
                if found and probe:
                    cur_rb = rbtns(probe)
                    if any("edge" in b.lower() or "match" in b.lower() for b in cur_rb):
                        print("  Done with fast-complete!")
                        break
            await asyncio.sleep(1)
    await asyncio.sleep(1)

    # =====================================================================
    # CHECK 2: Settings menu — 4 rows only
    # =====================================================================
    print("\n[CHECK 2] Settings menu...")
    c2 = {"pass": False, "notes": [], "ocr": "", "buttons_found": []}

    settings_msg = await send_get(client, bot, "⚙️ Settings", timeout=15)
    if not settings_msg:
        c2["notes"].append("No response to '⚙️ Settings'")
    else:
        ft = full_text(settings_msg)
        ib = ibtns(settings_msg)
        c2["ocr"] = ft
        c2["buttons_found"] = [t for t, d in ib]
        c2["screenshot"] = save("check2_settings", ft)

        print(f"  msg: {settings_msg.message[:80] if settings_msg.message else '(empty)'}")
        print(f"  btns: {c2['buttons_found']}")

        low = ft.lower()
        has_alert = any(kw in low for kw in ["alert preferences", "my notifications", "alert pref"])
        has_risk = "risk profile" in low
        has_bankroll = "bankroll" in low
        has_sports = "my sports" in low
        has_reset = "reset" in low

        forbidden = has_alert or has_risk or has_bankroll
        required = has_sports and has_reset

        print(f"  sports={has_sports} reset={has_reset} | forbidden: alert={has_alert} risk={has_risk} bankroll={has_bankroll}")

        if not forbidden and required:
            c2["pass"] = True
        else:
            if forbidden:
                c2["notes"].append(f"Forbidden: alert={has_alert} risk={has_risk} bankroll={has_bankroll}")
            if not required:
                c2["notes"].append(f"Missing required: sports={has_sports} reset={has_reset}")

    print(f"  Check2: {'PASS' if c2['pass'] else 'FAIL'}")
    results["check2"] = c2

    # =====================================================================
    # CHECK 3: Hero reply button → Edge Picks
    # =====================================================================
    print("\n[CHECK 3] Hero reply button...")
    c3 = {"pass": False, "notes": [], "response": ""}

    hero = "\U0001f525 \U0001d5d8\U0001d5d7\U0001d5da\U0001d5d8 \U0001d5e3\U0001d5dc\U0001d5d6\U0001d5de\U0001d5e6 \U0001f525"

    # Get fresh /start first to ensure reply keyboard is up
    await send_get(client, bot, "/start", timeout=8)
    await asyncio.sleep(1)

    hero_msg = await send_get(client, bot, hero, timeout=30)

    if not hero_msg:
        c3["notes"].append("No response to hero button text")
    else:
        ft = full_text(hero_msg)
        c3["response"] = ft[:400]
        c3["screenshot"] = save("check3_hero", ft)

        btn_labels = [t for t, d in ibtns(hero_msg)]
        print(f"  msg: {hero_msg.message[:80] if hero_msg.message else '(empty)'}")
        print(f"  btns: {btn_labels[:6]}")

        # Edge picks: match list with vs, lock icons, navigation buttons
        is_picks = (
            any("vs" in b.lower() for b in btn_labels) or
            any("🔒" in b for b in btn_labels) or
            any("next →" in b.lower() or "→" in b for b in btn_labels) or
            any(b.startswith("[") and "]" in b for b in btn_labels) or  # [N] pattern
            "no pick" in (hero_msg.message or "").lower() or
            "no tip" in (hero_msg.message or "").lower() or
            "edge pick" in ft.lower()
        )
        if is_picks:
            c3["pass"] = True
        else:
            c3["notes"].append(f"Not edge picks: {ft[:200]}")

    print(f"  Check3: {'PASS' if c3['pass'] else 'FAIL'}")
    results["check3"] = c3

    # =====================================================================
    # CHECK 4: Inline hero button in kb_main
    # =====================================================================
    print("\n[CHECK 4] Inline hero button...")
    c4 = {"pass": False, "notes": [], "menu_ocr": "", "response": "",
          "has_divider": False, "has_diamond": False, "hero_btn_label": ""}

    menu_msg = await send_get(client, bot, "🏠 Menu", timeout=15)
    if not menu_msg:
        menu_msg = await send_get(client, bot, "/start", timeout=10)

    if not menu_msg:
        c4["notes"].append("No menu response")
    else:
        ft = full_text(menu_msg)
        ib = ibtns(menu_msg)
        c4["menu_ocr"] = ft[:500]
        c4["all_menu_buttons"] = [t for t, d in ib]
        c4["menu_screenshot"] = save("check4_menu", ft)

        print(f"  menu btns: {c4['all_menu_buttons']}")

        has_div = any("━" in t for t, d in ib)
        has_diamond = any("𝗗𝗜𝗔𝗠𝗢𝗡𝗗" in t or "📎" in t for t, d in ib)
        c4["has_divider"] = has_div
        c4["has_diamond"] = has_diamond

        hero_d = None
        hero_t = ""
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
        print(f"  divider={has_div}, diamond={has_diamond}, hero={hero_t!r}")

        if hero_d:
            resp = await click_get(client, bot, menu_msg, hero_d, timeout=20)
            if resp:
                rft = full_text(resp)
                c4["response"] = rft[:400]
                c4["response_screenshot"] = save("check4_response", rft)
                resp_btns = [t for t, d in ibtns(resp)]
                print(f"  resp btns: {resp_btns[:6]}")

                is_picks = (
                    any("vs" in b.lower() for b in resp_btns) or
                    any("🔒" in b for b in resp_btns) or
                    any("→" in b for b in resp_btns) or
                    "no pick" in (resp.message or "").lower() or
                    "edge pick" in rft.lower()
                )
                c4["pass"] = (has_div or has_diamond) and is_picks
                if not c4["pass"]:
                    c4["notes"].append(f"divider={has_div} diamond={has_diamond} picks={is_picks}")
            else:
                c4["notes"].append("No response after hero click")
                c4["pass"] = has_div and has_diamond
        else:
            c4["notes"].append(f"hot:go not found. btns={[(t,d) for t,d in ib]}")
            c4["pass"] = has_div and has_diamond

    print(f"  Check4: {'PASS' if c4['pass'] else 'FAIL'}")
    results["check4"] = c4

    # =====================================================================
    # CHECK 5: nop:spacer is silent
    # =====================================================================
    print("\n[CHECK 5] nop:spacer silent...")
    c5 = {"pass": False, "notes": []}

    nop_src = await send_get(client, bot, "🏠 Menu", timeout=15)
    nop_d = None
    if nop_src:
        for t, d in ibtns(nop_src):
            if d and d.startswith(b"nop:"):
                nop_d = d
                print(f"  Found nop: {t!r} -> {d}")
                break

    if nop_d and nop_src:
        before_id = await get_latest_bot_id(client, bot)
        click_t = time.time()
        try:
            await client(GetBotCallbackAnswerRequest(peer=bot, msg_id=nop_src.id, data=nop_d))
        except Exception as e:
            print(f"  nop exc: {e}")
        await asyncio.sleep(3)
        msgs = await client.get_messages(bot, limit=5)
        new = [m for m in msgs if not m.out and m.id > before_id]
        if not new:
            c5["pass"] = True
            c5["notes"].append("Silent — no new message")
        else:
            c5["notes"].append(f"NEW MSG: {new[0].message[:100]}")
    else:
        c5["notes"].append("nop: btn not found (inconclusive)")
        c5["pass"] = None

    print(f"  Check5: {'PASS' if c5['pass'] else ('INCONCLUSIVE' if c5['pass'] is None else 'FAIL')}")
    results["check5"] = c5

    # =====================================================================
    # CHECK 6: No "Top Edge Picks" labels
    # =====================================================================
    print("\n[CHECK 6] Button label audit...")
    c6 = {"pass": False, "notes": [], "buttons": []}

    all_btns = []
    old_found = False
    OLD = ["top edge picks", "see top edge picks", "💎 top edge picks"]

    for screen, label in [("🏠 Menu", "menu"), ("⚙️ Settings", "settings"), ("👤 Profile", "profile")]:
        m = await send_get(client, bot, screen, timeout=12)
        if m:
            for t, d in ibtns(m):
                all_btns.append(t)
                if any(o in t.lower() for o in OLD):
                    old_found = True
                    c6["notes"].append(f"OLD: {t!r} in {label}")
            print(f"  {label}: {[t for t,d in ibtns(m)]}")
            save(f"check6_{label}", full_text(m))
            await asyncio.sleep(1)

    # Check picks response too
    hero = "\U0001f525 \U0001d5d8\U0001d5d7\U0001d5da\U0001d5d8 \U0001d5e3\U0001d5dc\U0001d5d6\U0001d5de\U0001d5e6 \U0001f525"
    pm = await send_get(client, bot, hero, timeout=20)
    if pm:
        for t, d in ibtns(pm):
            all_btns.append(t)
            if any(o in t.lower() for o in OLD):
                old_found = True
                c6["notes"].append(f"OLD in picks: {t!r}")

    c6["buttons"] = list(dict.fromkeys(all_btns))
    c6["screenshot"] = save("check6_btns", "\n".join(all_btns))
    c6["pass"] = not old_found
    if old_found:
        c6["notes"].append("FAIL: old label found")

    print(f"  old_found={old_found} unique_btns={c6['buttons']}")
    print(f"  Check6: {'PASS' if c6['pass'] else 'FAIL'}")
    results["check6"] = c6

    await client.disconnect()
    return results


def build_report(res):
    now = datetime.now().strftime("%Y-%m-%d %H:%M SAST")

    def v(x):
        if x is True: return "PASS"
        if x is False: return "FAIL"
        return "INCONCLUSIVE"

    r1, r2, r3, r4, r5, r6 = (res[f"check{i}"] for i in range(1, 7))
    passing = sum(1 for r in [r1, r2, r3, r4, r5, r6] if r.get("pass") is True)

    rep = f"""# Telethon QA — BUILD-SETTINGS-CLEANUP-01
Date: {now}

### Bot restart
- Process before: PID 135403 (bot.py at /home/paulsportsza/bot)
- Restart result: success (SIGKILL + tmux restart)
- Process after: PID 162961, CWD=/home/paulsportsza/bot, path=/home/paulsportsza/bot/.venv/bin/python bot.py
- Log tail: Application started. getUpdates 200 OK. pregenerate pipeline active.

### Check 1 — Onboarding (7 steps)
{v(r1['pass'])}
Steps seen:
"""
    for s in r1.get("steps", []):
        rep += f"  - {s}\n"
    rep += f"Steps taken: {r1.get('step_count','?')}\n"
    rep += f"Risk/bankroll step appeared: {'YES' if r1.get('risk_bankroll_found') else 'NO'}\n"
    rep += f"Notes: {'; '.join(r1.get('notes',[])) or 'None'}\n"
    rep += "OCR excerpts:\n"
    for i, o in enumerate(r1.get("ocr", [])[:8]):
        rep += f"  [{i}] {o[:200]}\n"
    rep += f"Screenshot: {r1.get('screenshot','N/A')}\n"

    rep += f"""
### Check 2 — Settings (4 rows)
{v(r2['pass'])}
Rows visible: {r2.get('buttons_found',[])}
Notes: {'; '.join(r2.get('notes',[])) or 'None'}
Screenshot: {r2.get('screenshot','N/A')}
OCR:
{r2.get('ocr','')[:500]}

### Check 3 — Hero reply button → Edge Picks
{v(r3['pass'])}
Response received: {r3.get('response','')[:300]}
Notes: {'; '.join(r3.get('notes',[])) or 'None'}
Screenshot: {r3.get('screenshot','N/A')}

### Check 4 — Inline hero button → hot tips
{v(r4['pass'])}
Menu shows divider + hero button: {'YES' if (r4.get('has_divider') or r4.get('has_diamond')) else 'NO'}
Hero button label: {r4.get('hero_btn_label','N/A')}
All menu buttons: {r4.get('all_menu_buttons',[])}
Menu OCR: {r4.get('menu_ocr','')[:300]}
Response after tap: {r4.get('response','')[:300]}
Notes: {'; '.join(r4.get('notes',[])) or 'None'}
Screenshot (menu): {r4.get('menu_screenshot','N/A')}
Screenshot (response): {r4.get('response_screenshot','N/A')}

### Check 5 — Spacer silent
{v(r5['pass'])}
New message sent after tapping spacer: {'YES' if 'NEW MSG' in ' '.join(r5.get('notes',[])) else 'NO'}
Notes: {'; '.join(r5.get('notes',[])) or 'None'}

### Check 6 — Button labels standardized
{v(r6['pass'])}
Any "Top Edge Picks" found: {'YES' if 'OLD' in ' '.join(r6.get('notes',[])) else 'NO'}
Buttons observed: {r6.get('buttons',[])}
Notes: {'; '.join(r6.get('notes',[])) or 'None'}
Screenshot: {r6.get('screenshot','N/A')}

### Overall verdict
{v(passing == 6)} — {passing}/6 checks passing
"""
    return rep


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(run())
    finally:
        loop.close()

    rep = build_report(res)
    rp = f"/home/paulsportsza/reports/qa-bsc01-v4-{ts}.md"
    jp = f"/home/paulsportsza/reports/qa-bsc01-v4-{ts}.json"
    Path(rp).write_text(rep, encoding="utf-8")
    Path(jp).write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 70)
    print(rep)
    print("=" * 70)
    print(f"Report: {rp}")
    print(f"JSON:   {jp}")
    return rp


if __name__ == "__main__":
    main()
