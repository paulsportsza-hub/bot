"""FIX-DEPLOY-DISCIPLINE-SILENT-SKIP-01 — regression test.

Covers AC-1 (canonical happy path), AC-2 (canonical failure → FAIL not SKIP),
and AC-3 (non-canonical SKIP) for the silent-skip-to-fail conversion in
``test_deploy_discipline.test_bot_py_mtime_before_process_start``.

Source brief: INV-PRE-MERGE-GATE-INTEGRITY-01 §G3 problem statement #2.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from tests.contracts import test_deploy_discipline as ddmod


def test_canonical_host_failure_path_calls_pytest_fail(tmp_path):
    """AC-2: on canonical host with no live bot.py, the test FAILs (not SKIPs)."""
    bot_py = tmp_path / "bot.py"
    bot_py.write_text("# stub")
    with patch.object(ddmod, "_BOT_PY", bot_py), \
         patch.object(ddmod, "_running_bot_pid_and_start_time", return_value=(None, None)), \
         patch.object(ddmod.socket, "gethostname", return_value="mzansiedge-hel1"):
        with pytest.raises(pytest.fail.Exception) as exc_info:
            ddmod.test_bot_py_mtime_before_process_start()
    msg = str(exc_info.value)
    assert "DEPLOY-DISCIPLINE-1 PROBE FAIL on canonical host" in msg
    assert "mzansiedge-hel1" in msg


def test_non_canonical_host_failure_path_skips(tmp_path):
    """AC-3: on a non-canonical host (e.g. dev laptop, CI), missing process SKIPs."""
    bot_py = tmp_path / "bot.py"
    bot_py.write_text("# stub")
    with patch.object(ddmod, "_BOT_PY", bot_py), \
         patch.object(ddmod, "_running_bot_pid_and_start_time", return_value=(None, None)), \
         patch.object(ddmod.socket, "gethostname", return_value="dev-laptop-foo"):
        with pytest.raises(pytest.skip.Exception) as exc_info:
            ddmod.test_bot_py_mtime_before_process_start()
    assert "non-canonical host" in str(exc_info.value)


def test_canonical_host_happy_path_runs_assertion(tmp_path):
    """AC-1: on canonical host with a live bot.py process, assertion executes (PASS)."""
    bot_py = tmp_path / "bot.py"
    bot_py.write_text("# stub")
    mtime = os.path.getmtime(bot_py)
    with patch.object(ddmod, "_BOT_PY", bot_py), \
         patch.object(ddmod, "_running_bot_pid_and_start_time", return_value=("12345", mtime + 60.0)), \
         patch.object(ddmod.socket, "gethostname", return_value="mzansiedge-hel1"):
        ddmod.test_bot_py_mtime_before_process_start()


def test_canonical_host_assertion_fires_when_mtime_after_start(tmp_path):
    """AC-1 inverse: stale-runtime detection still works on canonical host."""
    bot_py = tmp_path / "bot.py"
    bot_py.write_text("# stub")
    mtime = os.path.getmtime(bot_py)
    with patch.object(ddmod, "_BOT_PY", bot_py), \
         patch.object(ddmod, "_running_bot_pid_and_start_time", return_value=("12345", mtime - 60.0)), \
         patch.object(ddmod.socket, "gethostname", return_value="mzansiedge-hel1"):
        with pytest.raises(AssertionError) as exc_info:
            ddmod.test_bot_py_mtime_before_process_start()
    assert "DEPLOY-DISCIPLINE-1 violation" in str(exc_info.value)
