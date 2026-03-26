#!/usr/bin/env python3
"""
REGFIX-07: notify_notion_deploy.py
Post a deploy ledger entry to the Notion Release Ledger database.
Non-blocking — any API error is logged but never raises.

Usage:
    python3 scripts/notify_notion_deploy.py PASS REGFIX-07 "optional notes"
    python3 scripts/notify_notion_deploy.py FAIL REGFIX-07
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
LEDGER_DB_ID = "32fd9048-d73c-812a-b6e7-c06ee34a32aa"
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=BOT_DIR
        ).decode().strip()
    except Exception:
        return "unknown"


def post_deploy_entry(
    validation_pass: bool,
    wave_id: str = "",
    notes: str = "",
    deployer: str = "agent",
) -> bool:
    """Create a ledger entry in Notion. Returns True on success, False on failure."""
    sha = _git_sha()
    short_sha = sha[:7] if sha != "unknown" else "unknown"
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    ts_iso = now.isoformat()

    release_name = f"v{date_str}-{short_sha}"
    validation_str = "PASS" if validation_pass else "FAIL"

    payload = {
        "parent": {"database_id": LEDGER_DB_ID},
        "properties": {
            "Release": {
                "title": [{"text": {"content": release_name}}]
            },
            "Git SHA": {
                "rich_text": [{"text": {"content": sha}}]
            },
            "Timestamp": {
                "date": {"start": ts_iso}
            },
            "Deployer": {
                "select": {"name": deployer}
            },
            "Validation": {
                "select": {"name": validation_str}
            },
            "Rollback": {
                "checkbox": False
            },
        },
    }

    if wave_id:
        payload["properties"]["Wave ID"] = {
            "rich_text": [{"text": {"content": wave_id}}]
        }
    if notes:
        payload["properties"]["Notes"] = {
            "rich_text": [{"text": {"content": notes}}]
        }

    try:
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            page_id = resp.json().get("id", "")
            print(
                f"[notion-ledger] {release_name} | {validation_str} | "
                f"wave={wave_id or 'n/a'} | page={page_id}"
            )
            return True
        else:
            print(
                f"[notion-ledger] WARN: API {resp.status_code} — {resp.text[:200]}",
                file=sys.stderr,
            )
            return False
    except Exception as exc:
        print(f"[notion-ledger] WARN: {exc}", file=sys.stderr)
        return False


def backfill_from_ledger(ledger_path: str) -> int:
    """Parse local deploy_ledger.log and backfill entries into Notion."""
    if not os.path.exists(ledger_path):
        print(f"[notion-ledger] No ledger file at {ledger_path}")
        return 0

    count = 0
    with open(ledger_path) as f:
        content = f.read()

    # Each entry starts with a timestamp; join any wrapped lines
    import re
    # Normalise multi-line entries (joined by whitespace wrapping)
    content = re.sub(r'\n(?!\d{4}-\d{2}-\d{2})', ' ', content)

    for line in content.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        ts_match = re.match(r'^(\S+)', line)
        ts_str = ts_match.group(1) if ts_match else ""
        validation_pass = "PASS" in line
        sha_match = re.search(r'sha=([0-9a-f]+)', line)
        sha = sha_match.group(1) if sha_match else "unknown"
        short_sha = sha[:7]

        try:
            ts = datetime.fromisoformat(ts_str)
            date_str = ts.strftime("%Y-%m-%d")
        except Exception:
            date_str = "unknown"

        release_name = f"v{date_str}-{short_sha}"
        validation_str = "PASS" if validation_pass else "FAIL"

        payload = {
            "parent": {"database_id": LEDGER_DB_ID},
            "properties": {
                "Release": {"title": [{"text": {"content": release_name}}]},
                "Git SHA": {"rich_text": [{"text": {"content": sha}}]},
                "Timestamp": {"date": {"start": ts_str or date_str}},
                "Deployer": {"select": {"name": "auto"}},
                "Validation": {"select": {"name": validation_str}},
                "Rollback": {"checkbox": False},
                "Notes": {"rich_text": [{"text": {"content": "backfilled"}}]},
            },
        }

        try:
            resp = requests.post(
                "https://api.notion.com/v1/pages",
                headers={
                    "Authorization": f"Bearer {NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            if resp.status_code == 200:
                count += 1
                print(f"[notion-ledger] backfilled: {release_name} | {validation_str}")
            else:
                print(
                    f"[notion-ledger] WARN backfill {release_name}: "
                    f"{resp.status_code} {resp.text[:100]}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"[notion-ledger] WARN backfill {release_name}: {exc}", file=sys.stderr)

    return count


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "--backfill":
        ledger = args[1] if len(args) > 1 else "/var/log/mzansiedge/deploy_ledger.log"
        n = backfill_from_ledger(ledger)
        print(f"[notion-ledger] backfill complete: {n} entries")
        sys.exit(0)

    validation_arg = args[0] if len(args) > 0 else "PASS"
    wave_arg = args[1] if len(args) > 1 else ""
    notes_arg = args[2] if len(args) > 2 else ""

    success = post_deploy_entry(
        validation_pass=(validation_arg.upper() == "PASS"),
        wave_id=wave_arg,
        notes=notes_arg,
    )
    sys.exit(0 if success else 1)
