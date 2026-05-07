"""FIX-BOT-SINGLETON-LOCK-STALE-RECOVERY-01 — singleton lock regression tests.

Three contract cases (AC-5):
  1. Stale PID in lockfile, no flock held → lock acquired, file has our PID.
  2. Live process holds flock → _acquire_pid_lock exits with code 1.
  3. Empty lockfile → lock acquired.
"""
from __future__ import annotations

import fcntl
import multiprocessing
import os
import sys
import tempfile
import time

import pytest

# Make project root importable without the conftest env bootstrap for pure-OS tests.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env guard: bot.py reads these at import time via config.
for _key, _val in [
    ("BOT_TOKEN", "test-token"),
    ("ODDS_API_KEY", "test-key"),
    ("ANTHROPIC_API_KEY", "test-key"),
    ("OPENROUTER_API_KEY", "test-key"),
    ("ADMIN_IDS", "0"),
    ("SENTRY_DSN", ""),
]:
    os.environ.setdefault(_key, _val)


def _load():
    """Lazy-import the two functions to avoid PTB module-level side-effects on
    first collection; also lets conftest finish env-patching first."""
    from bot import _acquire_pid_lock, _probe_pid_liveness
    return _acquire_pid_lock, _probe_pid_liveness


@pytest.fixture(autouse=True)
def _reset_singleton_lock():
    """Release the module-level lock fd between tests so each test starts clean."""
    import bot
    yield
    if bot._PID_LOCK_FD is not None:
        try:
            fcntl.flock(bot._PID_LOCK_FD, fcntl.LOCK_UN)
            os.close(bot._PID_LOCK_FD)
        except OSError:
            pass
        bot._PID_LOCK_FD = None


def _child_hold_lock(path: str, ready_write_fd: int) -> None:
    """Subprocess: acquire flock on *path*, write PID, signal parent, hold."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, str(os.getpid()).encode())
    os.write(ready_write_fd, b"1")
    os.close(ready_write_fd)
    time.sleep(30)


def test_stale_pid_lock_acquired():
    """Case 1: stale PID (99999) in lockfile, no competing flock → lock acquired."""
    _acquire_pid_lock, _ = _load()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pid") as f:
        path = f.name

    try:
        with open(path, "w") as fh:
            fh.write("99999\n")

        _acquire_pid_lock(path=path)  # must not raise

        with open(path) as fh:
            written = fh.read().strip()
        assert written == str(os.getpid()), (
            f"Expected {os.getpid()}, got {written!r}"
        )
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def test_live_pid_exits_code_1():
    """Case 2: child process holds flock → _acquire_pid_lock must exit with code 1."""
    _acquire_pid_lock, _ = _load()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pid") as f:
        path = f.name

    r_fd, w_fd = os.pipe()
    child = multiprocessing.Process(
        target=_child_hold_lock,
        args=(path, w_fd),
        daemon=True,
    )
    child.start()
    os.close(w_fd)

    try:
        ready = os.read(r_fd, 1)
        os.close(r_fd)
        assert ready == b"1", "Child did not signal readiness"

        with pytest.raises(SystemExit) as exc_info:
            _acquire_pid_lock(path=path)
        assert exc_info.value.code == 1
    finally:
        child.terminate()
        child.join(timeout=5)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def test_empty_lockfile_acquired():
    """Case 3: empty lockfile (fresh install) → lock acquired, PID written."""
    _acquire_pid_lock, _ = _load()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pid") as f:
        path = f.name
    # File exists but empty (NamedTemporaryFile writes nothing).

    try:
        _acquire_pid_lock(path=path)  # must not raise

        with open(path) as fh:
            written = fh.read().strip()
        assert written == str(os.getpid())
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
