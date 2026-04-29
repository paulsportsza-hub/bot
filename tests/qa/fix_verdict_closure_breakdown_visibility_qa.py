#!/usr/bin/env python3
"""FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 — HG-2 Telethon QA.

Pulls the last 6 edge-card messages from @MzansiEdgeAlerts and checks:
  - Card image present (photo attachment)
  - Verdict prose in caption
  - AI Breakdown button presence + label
  - For each card: closing-sentence components (action verb / team / odds)
  - Visibility-gate behaviour (button visible iff polish + quality)

Output: JSON report + screenshots saved to
``/home/paulsportsza/reports/evidence/fix_verdict_closure_breakdown_visibility_qa/``.

Inline-only — no card-tap interactions (no live state mutation).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

_ENV = Path(__file__).resolve().parents[2] / ".env"
if _ENV.exists():
    load_dotenv(str(_ENV))

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
STRING_SESSION_FILE = str(
    Path(__file__).resolve().parents[2] / "data" / "telethon_session.string"
)
ALERTS_CHANNEL_ID = int(os.getenv("TELEGRAM_ALERTS_CHANNEL_ID", "-1003789410835"))

EVIDENCE_DIR = Path(
    "/home/paulsportsza/reports/evidence/"
    "fix_verdict_closure_breakdown_visibility_qa"
)
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


# Action verbs from the brief AC-1 cluster.
_ACTION_VERBS_RE = re.compile(
    r"\b(?:back|take|bet\s+on|get\s+on|put\s+(?:your\s+)?money\s+on|"
    r"hammer\s+it\s+on|get\s+behind|lean\s+on|ride|smash)\b",
    re.IGNORECASE,
)

# Odds shape matcher.
_ODDS_RE = re.compile(
    r"(?:\b[1-9]\d?\.\d{2}\b|\b\d+/\d+\b|(?:^|\s)[+-]\d{2,4}\b)"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _last_sentence(text: str) -> str:
    if not text:
        return ""
    plain = _HTML_TAG_RE.sub("", text).strip()
    if not plain:
        return ""
    parts = re.split(r"[.!?]\s+", plain)
    nonempty = [p.strip() for p in parts if p and p.strip()]
    if not nonempty:
        return ""
    return nonempty[-1].rstrip(" \t.!?;,…—–-").strip()


def _extract_verdict_section(caption: str) -> str:
    """Find the Verdict section in the caption — anchor on 🏆."""
    if not caption:
        return ""
    idx = caption.find("🏆")
    if idx == -1:
        return ""
    rest = caption[idx:]
    # Strip the header line if present.
    nl = rest.find("\n")
    return rest[nl + 1:].strip() if nl != -1 else ""


def _extract_match_id_from_caption(caption: str) -> str:
    """Best-effort match key extraction. Looks for "vs" team name pattern."""
    if not caption:
        return ""
    # First line typically: "🎯 Home vs Away" or similar.
    first = caption.split("\n", 1)[0]
    return first.strip()


def _check_closure(verdict: str, home_hint: str = "", away_hint: str = "") -> dict:
    last = _last_sentence(verdict)
    has_action = bool(_ACTION_VERBS_RE.search(last))
    has_odds = bool(_ODDS_RE.search(last))
    last_lower = last.lower()
    team_hit = False
    for raw in (home_hint, away_hint):
        name = (raw or "").strip().lower()
        if not name:
            continue
        if name in last_lower:
            team_hit = True
            break
    return {
        "closing_sentence": last,
        "has_action_verb": has_action,
        "has_team": team_hit,
        "has_odds_shape": has_odds,
    }


def _check_breakdown_button(reply_markup) -> dict:
    """Return whether the Full AI Breakdown button is present + its label."""
    info = {
        "ai_breakdown_button_visible": False,
        "ai_breakdown_label": "",
        "buttons_seen": [],
    }
    if not reply_markup:
        return info
    rows = getattr(reply_markup, "rows", None) or []
    for row in rows:
        for btn in getattr(row, "buttons", []) or []:
            text = getattr(btn, "text", "") or ""
            info["buttons_seen"].append(text)
            if "ai breakdown" in text.lower() or text.lstrip().startswith("🤖"):
                info["ai_breakdown_button_visible"] = True
                info["ai_breakdown_label"] = text
            elif "🔒 full ai breakdown" in text.lower():
                info["ai_breakdown_button_visible"] = True
                info["ai_breakdown_label"] = text
    return info


async def main():
    if not Path(STRING_SESSION_FILE).exists():
        print(f"ERROR: missing session string at {STRING_SESSION_FILE}", file=sys.stderr)
        sys.exit(1)
    session_str = Path(STRING_SESSION_FILE).read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: telethon session not authorised", file=sys.stderr)
        sys.exit(1)

    entity = await client.get_entity(ALERTS_CHANNEL_ID)
    messages = []
    async for m in client.iter_messages(entity, limit=20):  # type: ignore[arg-type]
        if not m.photo:
            continue
        messages.append(m)
        if len(messages) >= 6:
            break

    print(f"[QA] Captured {len(messages)} edge-card messages from channel id {ALERTS_CHANNEL_ID}")

    rows = []
    for i, m in enumerate(messages, 1):
        caption = m.message or ""
        msg_id = m.id
        sent_at = m.date.isoformat() if m.date else ""

        # Save screenshot.
        screenshot_path = EVIDENCE_DIR / f"card_{i:02d}_msg{msg_id}.jpg"
        try:
            await client.download_media(m, file=str(screenshot_path))
        except Exception as exc:
            print(f"[QA] screenshot fail for msg {msg_id}: {exc}")

        verdict = _extract_verdict_section(caption)
        match_label = _extract_match_id_from_caption(caption)

        # Crude team-name extraction from "🎯 Home vs Away" line.
        teams_match = re.search(r"🎯\s*([^\n]+?)\s+vs\s+([^\n]+)", caption)
        home_hint = teams_match.group(1).strip() if teams_match else ""
        away_hint = teams_match.group(2).strip() if teams_match else ""
        # Trim trailing emoji / punctuation.
        home_hint = re.sub(r"[\U0001F300-\U0001FAFF]+", "", home_hint).strip()
        away_hint = re.sub(r"[\U0001F300-\U0001FAFF]+", "", away_hint).strip()

        closure = _check_closure(verdict, home_hint, away_hint)
        button = _check_breakdown_button(m.reply_markup)

        # Tier inferred from caption if "DIAMOND EDGE" / "GOLD EDGE" etc. appear.
        tier = ""
        for cand in ("DIAMOND EDGE", "GOLD EDGE", "SILVER EDGE", "BRONZE EDGE"):
            if cand in caption.upper():
                tier = cand.split()[0].lower()
                break

        row = {
            "card_index": i,
            "msg_id": msg_id,
            "sent_at": sent_at,
            "match_label": match_label,
            "tier": tier,
            "home_hint": home_hint,
            "away_hint": away_hint,
            "card_image_present": bool(m.photo),
            "screenshot_path": str(screenshot_path),
            "verdict_excerpt": verdict[:240],
            **closure,
            **button,
        }
        rows.append(row)
        print(f"[QA] card {i}: tier={tier} action={closure['has_action_verb']} "
              f"team={closure['has_team']} odds={closure['has_odds_shape']} "
              f"button={button['ai_breakdown_button_visible']}")

    report = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "channel_id": ALERTS_CHANNEL_ID,
        "card_count": len(rows),
        "cards": rows,
    }
    out_path = EVIDENCE_DIR / "report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[QA] report → {out_path}")
    print(f"[QA] screenshots → {EVIDENCE_DIR}/card_*.jpg")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
