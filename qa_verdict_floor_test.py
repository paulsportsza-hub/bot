"""
QA Verification: _render_verdict() floor/ceiling [140, 200] + " lean" blacklist.
Connects via Telethon (string session), triggers Top Edge Picks, opens at least 5
edge cards (ep:pick:N callbacks), extracts the Verdict section from each, reports PASS/FAIL.
"""
import asyncio
import re
import sys
import html as html_mod
import os
from dotenv import load_dotenv

load_dotenv("/home/paulsportsza/bot/.env")

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

STRING_SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
FILE_SESSION = "/home/paulsportsza/bot/data/telethon_qa_session"
BOT = "mzansiedge_bot"

VERDICT_MIN = 140
VERDICT_MAX = 200


def strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text)
    return html_mod.unescape(clean).strip()


def extract_verdict(text: str) -> str:
    """Extract text after the 🏆 Verdict header, HTML-stripped."""
    # Remove tg-spoiler wrappers but keep content
    text = re.sub(r"</?tg-spoiler>", "", text)

    patterns = [
        # Bold HTML then newline
        r"🏆\s*<b>Verdict</b>\s*\n([\s\S]+?)(?=\n\n(?:📋|🎯|⚠️|🏆)|$)",
        # Plain text header
        r"🏆\s*Verdict\s*\n([\s\S]+?)(?=\n\n(?:📋|🎯|⚠️|🏆)|$)",
        # Catch-all: anything after 🏆 header line
        r"🏆[^\n]*\n([\s\S]+?)(?:\n\n|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).strip()
            clean = strip_html(raw)
            if clean:
                return clean
    return ""


async def get_client():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                print("Using string session — authorised.")
                return client
            await client.disconnect()

    client = TelegramClient(FILE_SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    print("Using file session — authorised.")
    return client


async def run_qa():
    client = await get_client()
    results = []

    try:
        entity = await client.get_entity(BOT)

        # Step 1: Trigger Top Edge Picks list
        print("\n[1] Sending '💎 Top Edge Picks' …")
        sent = await client.send_message(entity, "💎 Top Edge Picks")
        sent_id = sent.id
        await asyncio.sleep(20)

        # Step 2: Collect all messages since our trigger
        msgs = await client.get_messages(entity, limit=20)
        recent = sorted([m for m in msgs if m.id >= sent_id], key=lambda m: m.id)
        print(f"[2] Received {len(recent)} message(s) after trigger")

        # Step 3: Collect all clickable tip buttons (ep:pick:N AND edge:detail:... patterns)
        tip_buttons = []  # list of (msg_obj, btn_obj, btn_label)
        for msg in recent:
            if not msg.buttons:
                continue
            for row in msg.buttons:
                for btn in row:
                    cbd = getattr(btn, "data", None)
                    if cbd is None:
                        continue
                    # Match ep:pick:N (main list buttons) or edge:detail:... (alternate path)
                    if b"ep:pick:" in cbd or b"edge:detail:" in cbd:
                        tip_buttons.append((msg, btn, btn.text))
                        print(f"   Found tip btn: {btn.text!r}  cb={cbd}")

        if not tip_buttons:
            print("\n[!] No ep:pick or edge:detail buttons found. All buttons:")
            for msg in recent:
                if msg.buttons:
                    for row in msg.buttons:
                        for btn in row:
                            cbd = getattr(btn, "data", None)
                            print(f"   msg {msg.id}: {btn.text!r}  cb={cbd}")
            return results

        # Step 4: Click each button, capture the card, extract verdict
        MAX_CARDS = 7
        clicked_cbs = set()

        for msg, btn, label in tip_buttons[:MAX_CARDS]:
            cb = getattr(btn, "data", b"")
            if cb in clicked_cbs:
                continue
            clicked_cbs.add(cb)

            print(f"\n[4.{len(results)+1}] Clicking '{label}' …")
            try:
                await btn.click()
            except Exception as e:
                print(f"   Click error: {e}")
                continue

            await asyncio.sleep(14)

            # Fetch the card that was just opened
            latest = sorted(await client.get_messages(entity, limit=8),
                            key=lambda m: m.id, reverse=True)

            detail_text = ""
            detail_msg = None
            for lm in latest:
                t = lm.text or lm.message or ""
                if "🏆" in t and len(t) > 100:
                    detail_text = t
                    detail_msg = lm
                    break

            if not detail_text:
                # Sometimes the detail is embedded in a message without 🏆 visible
                # Try the most recent message regardless
                for lm in latest:
                    t = lm.text or lm.message or ""
                    if len(t) > 100:
                        detail_text = t
                        detail_msg = lm
                        break

            if not detail_text:
                print("   [!] No detail card found after click — skipping")
                await _try_go_back(client, entity)
                continue

            # Extract match name from the 🎯 header line
            match_name = ""
            for line in detail_text.split("\n"):
                stripped_line = strip_html(line).strip()
                if "🎯" in line or ("vs" in stripped_line.lower() and len(stripped_line) > 5):
                    match_name = stripped_line
                    break
            if not match_name:
                match_name = strip_html(detail_text.split("\n")[0]).strip()

            verdict = extract_verdict(detail_text)
            vlen = len(verdict)

            floor_ok = vlen >= VERDICT_MIN
            ceiling_ok = vlen <= VERDICT_MAX
            lean_ok = " lean" not in verdict.lower()

            results.append({
                "card": len(results) + 1,
                "match": match_name,
                "verdict_raw": verdict,
                "verdict_len": vlen,
                "floor_ok": floor_ok,
                "ceiling_ok": ceiling_ok,
                "lean_ok": lean_ok,
                "full_text_preview": strip_html(detail_text)[:400],
            })

            print(f"   Match: {match_name}")
            print(f"   Verdict ({vlen} chars): {verdict!r}")
            print(f"   Floor ≥{VERDICT_MIN}: {'PASS' if floor_ok else 'FAIL'}")
            print(f"   Ceiling ≤{VERDICT_MAX}: {'PASS' if ceiling_ok else 'FAIL'}")
            print(f"   No ' lean': {'PASS' if lean_ok else 'FAIL'}")

            # Navigate back to picks list for the next click
            await _try_go_back(client, entity)

            # Refresh button list from the re-rendered list page
            refreshed = sorted(await client.get_messages(entity, limit=15), key=lambda m: m.id)
            for msg2 in refreshed:
                if not msg2.buttons:
                    continue
                for row in msg2.buttons:
                    for b in row:
                        cbd2 = getattr(b, "data", None)
                        if cbd2 and (b"ep:pick:" in cbd2 or b"edge:detail:" in cbd2):
                            if cbd2 not in clicked_cbs:
                                if not any(m is msg2 and bx.data == cbd2
                                           for m, bx, _ in tip_buttons):
                                    tip_buttons.append((msg2, b, b.text))
                                    print(f"   + New tip btn: {b.text!r}")

    finally:
        await client.disconnect()

    return results


async def _try_go_back(client, entity):
    """Try to press a back/hot:back/nav button to return to the list."""
    await asyncio.sleep(2)
    latest = sorted(await client.get_messages(entity, limit=5),
                    key=lambda m: m.id, reverse=True)
    for lm in latest:
        if not lm.buttons:
            continue
        for row in lm.buttons:
            for b in row:
                bdata = getattr(b, "data", None)
                if bdata and (b"hot:back" in bdata or b"nav:main" in bdata
                              or b"yg:all" in bdata or b"hot:go" in bdata):
                    try:
                        await b.click()
                        await asyncio.sleep(8)
                    except Exception:
                        pass
                    return
        break


async def main():
    results = await run_qa()

    print("\n" + "=" * 70)
    print("QA VERDICT FLOOR/CEILING + LEAN BLACKLIST — FINAL REPORT")
    print("=" * 70)

    cards_tested = len(results)
    print(f"Cards tested: {cards_tested}")

    if not results:
        print("\n[ERROR] No verdict sections could be extracted.")
        print("Possible causes:")
        print("  - Bot returned zero tips (no live edges)")
        print("  - Verdict section format changed or no 🏆 header present")
        print("  - Auth/session issue")
        return

    pass_floor = sum(1 for r in results if r["floor_ok"])
    pass_ceiling = sum(1 for r in results if r["ceiling_ok"])
    pass_lean = sum(1 for r in results if r["lean_ok"])
    pass_all = sum(1 for r in results if r["floor_ok"] and r["ceiling_ok"] and r["lean_ok"])

    print()
    for r in results:
        print(f"--- Card {r['card']}: {r['match']} ---")
        print(f"  Verdict ({r['verdict_len']} chars):")
        print(f"    {r['verdict_raw']}")
        floor_s = "PASS" if r["floor_ok"] else f"FAIL  <- VIOLATION ({r['verdict_len']} < {VERDICT_MIN})"
        ceiling_s = "PASS" if r["ceiling_ok"] else f"FAIL  <- VIOLATION ({r['verdict_len']} > {VERDICT_MAX})"
        lean_s = "PASS" if r["lean_ok"] else "FAIL  <- VIOLATION (contains ' lean')"
        print(f"  Floor ≥{VERDICT_MIN}:    {floor_s}")
        print(f"  Ceiling ≤{VERDICT_MAX}:  {ceiling_s}")
        print(f"  No ' lean':       {lean_s}")
        print()

    print("-" * 70)
    print(f"Floor ≥{VERDICT_MIN} PASS:    {pass_floor}/{cards_tested}")
    print(f"Ceiling ≤{VERDICT_MAX} PASS:  {pass_ceiling}/{cards_tested}")
    print(f"No ' lean' PASS:   {pass_lean}/{cards_tested}")
    print(f"All criteria PASS: {pass_all}/{cards_tested}")

    if cards_tested < 5:
        print(f"\nNOTE: Only {cards_tested} card(s) tested (target ≥5). Results are partial.")

    if pass_all == cards_tested and cards_tested > 0:
        print(f"\nOVERALL: PASS")
    elif cards_tested == 0:
        print("\nOVERALL: INCONCLUSIVE — No cards tested")
    else:
        print(f"\nOVERALL: FAIL — {cards_tested - pass_all} card(s) violated constraints")
        for r in results:
            if not (r["floor_ok"] and r["ceiling_ok"] and r["lean_ok"]):
                print(f"  FAILED: {r['match']}")
                print(f"    Verdict: {r['verdict_raw']!r}")


if __name__ == "__main__":
    asyncio.run(main())
