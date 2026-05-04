"""BUILD-DEEPLINK-HARDEN-01 — deep-link URL shape contract.

Locks three invariants:
1. bot_lib.alerts_direct._DEEPLINK_BASE uses the card_ prefix (no edge_ infix).
2. No tracked Python file emits a ?start=card_edge_ literal.
3. No tracked Python file emits an f"/start card_edge_" literal.

The edge_ infix is not produced by any live URL surface. It only appeared in
two untracked Telethon test files that have since been fixed and committed.
This contract ensures the regression cannot return via tracked code.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_THIS_FILE = os.path.abspath(__file__)
sys.path.insert(0, _REPO_ROOT)


def test_deeplink_base_constant_has_no_edge_infix():
    from bot_lib import alerts_direct

    assert alerts_direct._DEEPLINK_BASE == "https://t.me/mzansiedge_bot?start=card_"
    assert "card_edge_" not in alerts_direct._DEEPLINK_BASE


def _py_grep(pattern: str) -> list[str]:
    """Return 'file:lineno:line' strings for .py files containing pattern.

    Excludes this contract file itself. Uses plain filesystem search because
    the repo is configured with bare=true, making git grep unavailable.
    """
    hits: list[str] = []
    repo = Path(_REPO_ROOT)
    for py_file in repo.rglob("*.py"):
        if str(py_file) == _THIS_FILE:
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(errors="replace").splitlines(), 1):
                if pattern in line:
                    hits.append(f"{py_file.relative_to(repo)}:{lineno}:{line.rstrip()}")
        except OSError:
            pass
    return hits


def test_no_start_card_edge_in_tracked_code():
    hits = _py_grep("?start=card_edge_")
    assert hits == [], (
        "Tracked code must not emit ?start=card_edge_ deep-links. "
        "Only card_<match_key> is produced by live URL surfaces.\n"
        + "\n".join(hits)
    )


def test_no_slash_start_card_edge_in_tracked_code():
    hits = _py_grep("/start card_edge_")
    assert hits == [], (
        "Tracked code must not send /start card_edge_ in tests or scripts. "
        "The edge_ infix matches no production URL producer and creates "
        "pollution rows when fed into _store_verdict_cache_sync.\n"
        + "\n".join(hits)
    )
