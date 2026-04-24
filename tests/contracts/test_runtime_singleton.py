"""BUILD-CONTRACT-TESTS-01 — Test 1: Runtime Singleton Lock

Invariants:
  (a) _acquire_pid_lock() uses fcntl.flock(LOCK_EX | LOCK_NB) on the PID file
  (b) _log_startup_truth() logs PID, git SHA, bot.py mtime, and lock status
"""
import os
import re

_BOT_PY = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")


def _read_bot_section(fn_name: str, end_marker: str | None = None) -> str:
    """Extract source lines starting at 'def fn_name' until the next top-level def."""
    with open(_BOT_PY, encoding="utf-8") as f:
        source = f.read()
    pattern = rf"(?m)^def {re.escape(fn_name)}\b.*?(?=\ndef |\Z)"
    m = re.search(pattern, source, re.DOTALL)
    assert m, f"{fn_name} not found in bot.py"
    return m.group(0)


def test_acquire_pid_lock_uses_flock_ex_nb():
    """_acquire_pid_lock() must use fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)."""
    src = _read_bot_section("_acquire_pid_lock")

    # Verify the flock call includes both LOCK_EX and LOCK_NB
    assert "LOCK_EX" in src, "_acquire_pid_lock must use fcntl.LOCK_EX"
    assert "LOCK_NB" in src, "_acquire_pid_lock must use fcntl.LOCK_NB"
    # Verify they appear together in a flock() call
    assert re.search(r"fcntl\.flock\s*\(.*LOCK_EX.*LOCK_NB|LOCK_NB.*LOCK_EX", src), (
        "_acquire_pid_lock must call fcntl.flock with LOCK_EX | LOCK_NB together"
    )


def test_pid_lock_fd_is_module_level():
    """_PID_LOCK_FD must be kept open at module level so the kernel lock persists."""
    with open(_BOT_PY, encoding="utf-8") as f:
        source = f.read()
    assert "_PID_LOCK_FD" in source, "_PID_LOCK_FD module-level variable not found"
    # Must be assigned (fd kept open) not just declared
    assert re.search(r"_PID_LOCK_FD\s*=\s*fd", source), (
        "_PID_LOCK_FD must be assigned the open fd inside _acquire_pid_lock"
    )


def test_log_startup_truth_emits_pid():
    """_log_startup_truth must emit PID to logs."""
    src = _read_bot_section("_log_startup_truth")
    assert re.search(r"\bpid\b|\bPID\b", src), (
        "_log_startup_truth must log 'pid' keyword"
    )


def test_log_startup_truth_emits_sha():
    """_log_startup_truth must emit git SHA to logs."""
    src = _read_bot_section("_log_startup_truth")
    assert re.search(r"sha|git_sha|SHA", src, re.IGNORECASE), (
        "_log_startup_truth must log git SHA"
    )


def test_log_startup_truth_emits_mtime():
    """_log_startup_truth must emit bot.py mtime to logs."""
    src = _read_bot_section("_log_startup_truth")
    assert re.search(r"mtime|mtime_str", src), (
        "_log_startup_truth must log bot.py mtime"
    )


def test_log_startup_truth_emits_lock_status():
    """_log_startup_truth must emit singleton lock status to logs."""
    src = _read_bot_section("_log_startup_truth")
    assert re.search(r"lock_status|singleton|HELD", src), (
        "_log_startup_truth must log singleton lock status"
    )
