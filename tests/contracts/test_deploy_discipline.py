"""BUILD-NARRATIVE-WATERTIGHT-01 D.4 — deploy-discipline guard.

DEPLOY-DISCIPLINE-1 D1/D2 requires the live bot process to start AFTER the
working-tree ``bot.py`` was last modified. When the inverse holds, the
running process does not contain the most recent code — every quality gate,
every narrative fix, every monitor is silently absent from production.

This test enforces the invariant at contract-test time. It runs as part of
the wave completion gate (``scripts/qa_safe.sh gate``) so a deploy cannot
ship without verification.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


_BOT_PY = Path("/home/paulsportsza/bot/bot.py")


def _running_bot_pid_and_start_time():
    """Return (pid, epoch_start) for the live bot process, or (None, None)."""
    try:
        ps = subprocess.run(
            ["ps", "-eo", "pid,lstart=,cmd"],
            capture_output=True, text=True, check=True, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None, None
    for line in ps.stdout.splitlines():
        if "bot.py" not in line or "grep" in line:
            continue
        parts = line.strip().split(maxsplit=1)
        if not parts:
            continue
        pid = parts[0]
        # etimes gives seconds since start — simpler than parsing lstart.
        try:
            etimes = subprocess.run(
                ["ps", "-o", "etimes=", "-p", pid],
                capture_output=True, text=True, check=True, timeout=5,
            )
            secs = int(etimes.stdout.strip())
        except (subprocess.SubprocessError, ValueError):
            return pid, None
        import time as _t
        return pid, _t.time() - secs
    return None, None


def test_bot_py_mtime_before_process_start():
    """DEPLOY-DISCIPLINE-1: bot.py mtime MUST be ≤ running-process start time.

    When this fails, the running process predates the last code change. Every
    fix on disk is invisible to live traffic. Must be followed by a restart
    per D2 before the deploy can proceed.

    Skipped when no bot process is running (e.g., CI container).
    """
    if not _BOT_PY.exists():
        pytest.skip("bot.py not found at canonical path — skipping deploy-discipline check")
    pid, start_epoch = _running_bot_pid_and_start_time()
    if pid is None or start_epoch is None:
        pytest.skip("No live bot.py process detected — deploy-discipline check N/A in this env")
    mtime = os.path.getmtime(_BOT_PY)
    assert mtime <= start_epoch, (
        f"DEPLOY-DISCIPLINE-1 violation (BUILD-NARRATIVE-WATERTIGHT-01 D.4): "
        f"bot.py mtime {mtime:.0f} > process start {start_epoch:.0f} "
        f"(PID {pid}). Live runtime predates working-tree changes. Restart "
        f"the bot from /home/paulsportsza/bot/ per D2 before proceeding."
    )
