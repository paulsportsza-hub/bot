"""X-CARD-PIPE-01: Queue Gold Edge cards for X Publisher via Marketing Ops Queue.

Tier contract (LOCKED):
    - Gold tier only → queues for X Publisher (Status: Awaiting Approval)
    - Bronze → skipped entirely
    - Diamond → skipped entirely (paid-exclusive, never posted to X)

Deduplication: caller maintains _x_queued_keys set; this module is pure IO.
"""

import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("x_card_queue")

# Marketing Ops Queue — Notion database page ID
# publisher .env: NOTION_MARKETING_DB_ID; falls back to known prod ID
_MOQ_DB_ID = os.getenv(
    "NOTION_MARKETING_DB_ID", "9061c15b-e8de-416d-8d61-e6b1d4d37f9f"
)

# Web hosting: card PNGs saved here, served via nginx
_CARDS_HOST_DIR = Path("/var/www/mzansiedge-wp/assets/cards")
_CARDS_BASE_URL = "https://mzansiedge.co.za/assets/cards"

_NOTION_VERSION = "2022-06-28"


# ── Notion helpers ─────────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    token = os.getenv("NOTION_TOKEN", "")
    if not token:
        raise RuntimeError("NOTION_TOKEN not set")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _moq_insert(
    match_key: str,
    matchup: str,
    caption: str,
    asset_url: str,
    compliance_pass: bool,
) -> str:
    """POST a new page to Marketing Ops Queue. Returns Notion page URL."""
    payload = {
        "parent": {"database_id": _MOQ_DB_ID},
        "properties": {
            "Title": {
                "title": [{"type": "text", "text": {"content": f"Gold Edge Card — {matchup}"}}]
            },
            "Status": {"select": {"name": "Awaiting Approval"}},
            "Channel": {"select": {"name": "X"}},
            "Final Copy": {
                "rich_text": [{"type": "text", "text": {"content": caption}}]
            },
            "Asset Link": {"url": asset_url},
            "Compliance Pass?": {"checkbox": compliance_pass},
            "Work Type": {"select": {"name": "Social"}},
            "Lane": {"select": {"name": "Content/Social"}},
            "Automation Route": {"select": {"name": "Other"}},
            "Priority": {"select": {"name": "Medium"}},
            # Platform Notes stores match_key for X-SETTLEMENT-CARD-01 pairing
            "Platform Notes": {
                "rich_text": [{"type": "text", "text": {"content": match_key}}]
            },
            "Campaign / Theme": {
                "rich_text": [{"type": "text", "text": {"content": f"Gold Edge — {matchup}"}}]
            },
        },
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=data,
        headers=_notion_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    page_id = result.get("id", "")
    return f"https://www.notion.so/{page_id.replace('-', '')}"


# ── Image hosting ──────────────────────────────────────────────────────────────

def _host_card_image(match_key: str, image_bytes: bytes) -> str:
    """Save card PNG to web-accessible directory. Returns public URL."""
    _CARDS_HOST_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9_-]", "_", match_key.lower())[:80]
    filename = f"gold_{safe}_{int(time.time())}.png"
    (_CARDS_HOST_DIR / filename).write_bytes(image_bytes)
    return f"{_CARDS_BASE_URL}/{filename}"


# ── Caption generation ─────────────────────────────────────────────────────────

def _generate_caption(matchup: str, ev_pct: float, pick: str, odds: float) -> str:
    """Generate tweet caption via Anthropic Haiku. Returns plain text."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    prompt = (
        f"Generate a single X tweet for a sports betting intelligence card. "
        f"Match: {matchup}. Edge: +{ev_pct:.1f}%. Pick: {pick} @ {odds:.2f}. "
        f"Format: data-led hook (1 sentence) + 1 line context + "
        f"'Save for kickoff 📌' bookmark prompt. "
        f"NO link. NO bookmaker promotion. Max 220 chars. Output ONLY tweet text."
    )
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    block = resp.content[0]
    return getattr(block, "text", "").strip()


def _caption_fallback(matchup: str, ev_pct: float, pick: str, odds: float) -> str:
    return (
        f"{matchup} · Edge +{ev_pct:.1f}% · {pick} @ {odds:.2f} · Save for kickoff 📌"
    )[:220]


# ── Public entry point ─────────────────────────────────────────────────────────

def queue_gold_card_for_x(
    match_key: str,
    image_bytes: bytes,
    card_data: dict,
) -> None:
    """
    Synchronous worker: host image → generate caption → insert MOQ page.

    Must be called via asyncio.to_thread() — contains blocking I/O.

    Tier guard is enforced here as a second line of defence; callers should
    also check tier before creating the task.
    """
    tier = (card_data.get("tier") or card_data.get("display_tier") or "").lower()
    if tier != "gold":
        log.debug("x_card_queue: skip tier=%s match=%s", tier, match_key)
        return

    matchup = (
        card_data.get("matchup")
        or f"{card_data.get('home_team', '')} vs {card_data.get('away_team', '')}"
    ).strip(" vs") or match_key

    ev = float(card_data.get("ev") or 0)
    pick = (card_data.get("outcome") or card_data.get("pick_team") or "").strip()
    odds = float(card_data.get("odds") or 0)
    compliance_pass = bool(
        card_data.get("data_sources_used")
        or card_data.get("data_status") == "ok"
    )

    try:
        asset_url = _host_card_image(match_key, image_bytes)
        log.info("x_card_queue: image hosted at %s", asset_url)
    except Exception as e:
        log.error("x_card_queue: image hosting failed for %s: %s", match_key, e)
        return

    try:
        caption = _generate_caption(matchup, ev, pick, odds)
    except Exception as e:
        log.warning("x_card_queue: caption generation failed for %s: %s — using fallback", match_key, e)
        caption = _caption_fallback(matchup, ev, pick, odds)

    try:
        page_url = _moq_insert(
            match_key=match_key,
            matchup=matchup,
            caption=caption,
            asset_url=asset_url,
            compliance_pass=compliance_pass,
        )
        log.info("x_card_queue: MOQ page created → %s", page_url)
    except Exception as e:
        log.error("x_card_queue: MOQ insert failed for %s: %s", match_key, e)
