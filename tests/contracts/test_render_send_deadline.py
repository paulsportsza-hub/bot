"""FIX-BOT-PERF-LATENCY-BOUNDS-01 — Driver B contract guard.

Asserts every `asyncio.to_thread(render_card_sync, ...)` callsite in
`card_sender.py` is wrapped by an `asyncio.wait_for(...)` deadline within
3 lines above. A bare `to_thread(render_card_sync, ...)` lets a stalled
Chromium render hold the PTB dispatcher slot for up to 90s (Chromium's
internal hard timeout), starving every other user behind it.

Source-level scan — no bot import required, no asyncio runtime needed.
"""
from __future__ import annotations

import os
import re


_CARD_SENDER_PY = os.path.join(
    os.path.dirname(__file__), "..", "..", "card_sender.py"
)

_RENDER_NAME_RE = re.compile(r"\brender_card_sync\b")
_WAIT_FOR_RE = re.compile(r"\basyncio\.wait_for\(")


def _load_lines() -> list[str]:
    with open(_CARD_SENDER_PY, encoding="utf-8") as f:
        return f.read().splitlines()


def test_render_card_sync_callsites_are_bounded():
    """Every render_card_sync to_thread call must sit under a wait_for guard.

    Lookback window is 3 lines — covers `await asyncio.wait_for(\\n  asyncio.to_thread(\\n    render_card_sync, ...`.
    Failure prints offending line numbers so the engineer can see exactly
    which branch lost its deadline.
    """
    lines = _load_lines()
    violations: list[tuple[int, str]] = []

    for idx, line in enumerate(lines):
        if "render_card_sync" not in line:
            continue
        # Skip imports, comments, docstrings, and references that aren't calls.
        # The to_thread call form: render_card_sync appears as a function REFERENCE
        # (no parens immediately after) inside to_thread(...). We only flag lines
        # where render_card_sync is the first positional arg of to_thread(...).
        # Two forms appear:
        #   to_thread(\n    render_card_sync, ...
        #   to_thread(render_card_sync, ...)
        is_to_thread_arg = False
        if "to_thread(" in line and _RENDER_NAME_RE.search(line):
            is_to_thread_arg = True
        else:
            # Look one line above for an open `to_thread(`
            above = lines[idx - 1] if idx > 0 else ""
            if "to_thread(" in above and "render_card_sync" not in above:
                # Check this line is the bare reference (function name without parens)
                stripped = line.strip().rstrip(",")
                if stripped.startswith("render_card_sync"):
                    is_to_thread_arg = True

        if not is_to_thread_arg:
            continue

        # Look back up to 3 lines for asyncio.wait_for(
        window_start = max(0, idx - 3)
        window = "\n".join(lines[window_start: idx + 1])
        if not _WAIT_FOR_RE.search(window):
            violations.append((idx + 1, line.strip()))

    assert not violations, (
        "FIX-BOT-PERF-LATENCY-BOUNDS-01 (Driver B) violation: "
        "render_card_sync to_thread call without asyncio.wait_for deadline.\n"
        "Each unbounded call can hold the PTB dispatcher for up to 90s "
        "(Chromium internal timeout), starving all users.\n"
        "Offending line(s):\n  "
        + "\n  ".join(f"line {n}: {src}" for n, src in violations)
    )


def test_render_callsites_use_8_second_deadline():
    """The render deadline must be 8.0s — narrow enough that one stalled
    render cannot pin the dispatcher long enough to be user-visible across
    other taps, generous enough to absorb normal Chromium cold starts.

    Anchored on the to_thread(render_card_sync) line; scans the next 6 lines
    for both `timeout=8.0` and a closing `)`. Uses line-proximity rather than
    regex over balanced parens because `asyncio.wait_for(asyncio.to_thread(...), timeout=...)`
    has nested parens that defeat naive regex backtracking.
    """
    lines = _load_lines()
    matches = 0
    for idx, line in enumerate(lines):
        # Anchor on the render_card_sync reference. In production, the call is
        # split across lines so to_thread(  is on the line before render_card_sync.
        # Skip the import line and any docstring/comment mentions.
        stripped = line.strip()
        if not stripped.startswith("render_card_sync"):
            continue
        # The to_thread( token sits within ~3 lines above; timeout=8.0 within
        # ~6 lines below (between the closing ) of to_thread and the close of wait_for).
        before = "\n".join(lines[max(0, idx - 3): idx])
        after = "\n".join(lines[idx: idx + 7])
        if "to_thread(" in before and "timeout=8.0" in after:
            matches += 1
    assert matches >= 2, (
        "FIX-BOT-PERF-LATENCY-BOUNDS-01: expected ≥2 render_card_sync to_thread "
        f"calls under timeout=8.0 (one per branch — width=None and width=int), "
        f"found {matches}. The 8.0s deadline is the brief contract — narrowing "
        "or widening it requires a follow-up brief and CLAUDE.md update."
    )
