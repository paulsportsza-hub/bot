#!/usr/bin/env python3
"""Reel Kit Sweep — deletes past-dated unchecked 🎥 Reel Kit to_do blocks from Task Hub.

BUILD-REEL-KIT-DATE-RULE-01 (Piece A)
Cron: 0 * * * * cd /home/paulsportsza/bot && .venv/bin/python scripts/reel_kit_sweep.py >> /home/paulsportsza/logs/reel_kit_sweep.log 2>&1

Pattern: 🎥 Reel Kit YYYY-MM-DD (exact — emoji + prefix + ISO date)
Deletes: unchecked to_do blocks where embedded date < today SAST
Skips: checked blocks (completed) and future/today-dated blocks
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reel_kit_sweep")

NOTION_VERSION = "2022-06-28"
TASK_HUB_PAGE_ID = "31ed9048-d73c-814e-a179-ccd2cf35df1d"
_RE_REEL_KIT = re.compile(r"^🎥 Reel Kit (\d{4}-\d{2}-\d{2})")
_SAST = timezone(timedelta(hours=2))


def _load_token() -> str:
    for path in (os.path.expanduser("~/.env"), "/home/paulsportsza/.env"):
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("NOTION_TOKEN="):
                        return line.split("=", 1)[1].strip()
        except FileNotFoundError:
            continue
    return os.getenv("NOTION_TOKEN", "")


def _notion_get(token: str, path: str) -> dict:
    req = Request(
        f"https://api.notion.com/v1{path}",
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
    )
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _notion_delete(token: str, block_id: str) -> None:
    req = Request(
        f"https://api.notion.com/v1/blocks/{block_id}",
        method="DELETE",
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
    )
    with urlopen(req, timeout=15):
        pass


def _today_sast() -> str:
    return datetime.now(_SAST).date().isoformat()


def fetch_reel_kit_blocks(token: str) -> list[dict]:
    """Fetch unchecked 🎥 Reel Kit to_do blocks from Task Hub. One fetch — SO-31."""
    data = _notion_get(token, f"/blocks/{TASK_HUB_PAGE_ID}/children?page_size=100")
    blocks = []
    for block in data.get("results", []):
        if block.get("type") != "to_do":
            continue
        todo = block.get("to_do", {})
        if todo.get("checked"):
            continue
        text = "".join(t["plain_text"] for t in todo.get("rich_text", []))
        m = _RE_REEL_KIT.match(text)
        if m:
            blocks.append({"block_id": block["id"], "date": m.group(1), "text": text})
    return blocks


def sweep(token: str) -> int:
    """Delete past-dated unchecked Reel Kit blocks. Returns count deleted."""
    today = _today_sast()
    blocks = fetch_reel_kit_blocks(token)
    deleted = 0
    for b in blocks:
        if b["date"] < today:
            _notion_delete(token, b["block_id"])
            log.info("Deleted block %s — '%s'", b["block_id"], b["text"])
            deleted += 1
        else:
            log.debug("Keeping %s (date %s >= today %s)", b["block_id"], b["date"], today)
    return deleted


def main() -> None:
    token = _load_token()
    if not token:
        log.error("NOTION_TOKEN not found — aborting")
        sys.exit(1)
    try:
        n = sweep(token)
        log.info("Sweep complete — %d block(s) deleted", n)
    except URLError as exc:
        log.error("Notion API error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
