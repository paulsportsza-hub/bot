"""Pre-run preflight checks for the QA Rubric Runner.

BUILD-QA-RUBRIC-RUNNER-01 — Phase A

Checks performed:
  PF-1  Required DB files exist
  PF-2  Telethon session string file exists
  PF-3  STITCH_MOCK_MODE is True (runner overrides this but env must permit it)
  PF-4  ANTHROPIC_API_KEY is set (required for OCR)
  PF-5  Bot process is running on the canonical path
  PF-6  Screenshot and report dirs are writable

--dry-run mode: runs preflight only, does NOT connect to Telegram.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import (
    MAIN_DB_PATH,
    ODDS_DB_PATH,
    REPORT_DIR,
    SCREENSHOT_DIR,
    SESSION_PATH,
    STITCH_MOCK_MODE,
)

log = logging.getLogger(__name__)

# Canonical bot path (DEPLOY-DISCIPLINE-1)
_CANONICAL_BOT_PATH = "/home/paulsportsza/bot/bot.py"


@dataclass
class PreflightResult:
    """Aggregated result of all preflight checks."""

    passed: bool = True
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    def fail(self, check: str, reason: str) -> None:
        self.passed = False
        self.failures.append(f"[FAIL] {check}: {reason}")
        self.checks_run.append(check)

    def warn(self, check: str, reason: str) -> None:
        self.warnings.append(f"[WARN] {check}: {reason}")
        self.checks_run.append(check)

    def ok(self, check: str) -> None:
        self.checks_run.append(check)


def _bot_cwd() -> Path:
    """Return the canonical bot working directory."""
    return Path("/home/paulsportsza/bot")


def _resolve(rel_path: str) -> Path:
    """Resolve a path relative to the bot CWD."""
    p = Path(rel_path)
    if not p.is_absolute():
        p = _bot_cwd() / p
    return p


def check_db_files(result: PreflightResult) -> None:
    """PF-1: Required DB files must exist."""
    for label, rel in [("odds.db", ODDS_DB_PATH), ("mzansiedge.db", MAIN_DB_PATH)]:
        path = _resolve(rel)
        if path.exists():
            result.ok(f"PF-1/{label}")
        else:
            result.fail(f"PF-1/{label}", f"{path} not found")


def check_telethon_qa_session(result: PreflightResult) -> None:
    """PF-2: Telethon session string file must exist."""
    path = _resolve(SESSION_PATH)
    if path.exists() and path.stat().st_size > 0:
        result.ok("PF-2/telethon_qa_session")
    else:
        result.fail("PF-2/telethon_qa_session", f"{path} missing or empty")


def check_stitch_mock(result: PreflightResult) -> None:
    """PF-3: STITCH_MOCK_MODE must be True in runner config."""
    if STITCH_MOCK_MODE:
        result.ok("PF-3/stitch_mock")
    else:
        result.fail(
            "PF-3/stitch_mock",
            "STITCH_MOCK_MODE is False in runner config — payment flow will hit live Stitch",
        )


def check_ocr_key(result: PreflightResult) -> None:
    """PF-4: ANTHROPIC_API_KEY must be set for OCR."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        result.ok("PF-4/ocr_key")
    else:
        result.warn("PF-4/ocr_key", "ANTHROPIC_API_KEY not set — OCR steps will be skipped")


def check_bot_process(result: PreflightResult) -> None:
    """PF-5: Bot process must be running on canonical path (DEPLOY-DISCIPLINE-1).

    This is a soft check — we read /proc to avoid importing psutil.
    Skipped gracefully if /proc is unavailable.
    """
    proc_dir = Path("/proc")
    if not proc_dir.exists():
        result.warn("PF-5/bot_process", "/proc not available — skipping process check")
        return

    canonical = _CANONICAL_BOT_PATH
    found = False
    try:
        for pid_dir in proc_dir.iterdir():
            if not pid_dir.name.isdigit():
                continue
            cmdline_file = pid_dir / "cmdline"
            try:
                cmdline = cmdline_file.read_bytes().replace(b"\x00", b" ").decode(errors="replace")
                if "python" in cmdline and "bot.py" in cmdline:
                    if canonical in cmdline:
                        found = True
                        break
                    # Also accept relative "bot.py" when CWD resolves to the canonical dir
                    try:
                        cwd = os.readlink(str(pid_dir / "cwd"))
                        if cwd == str(Path(canonical).parent):
                            found = True
                            break
                    except (OSError, PermissionError):
                        pass
            except (PermissionError, FileNotFoundError):
                continue
    except Exception as exc:
        result.warn("PF-5/bot_process", f"Process scan failed: {exc}")
        return

    if found:
        result.ok("PF-5/bot_process")
    else:
        result.fail(
            "PF-5/bot_process",
            f"No process found running {canonical} — bot may be down or on wrong path",
        )


def check_output_dirs(result: PreflightResult) -> None:
    """PF-6: Screenshot and report directories must be writable."""
    for label, dirpath in [("screenshots", SCREENSHOT_DIR), ("reports", REPORT_DIR)]:
        p = Path(dirpath)
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".preflight_write_test"
            test_file.write_text("ok")
            test_file.unlink()
            result.ok(f"PF-6/{label}")
        except Exception as exc:
            result.fail(f"PF-6/{label}", f"{p} not writable: {exc}")


def check_prose_exemplars(result: PreflightResult) -> None:
    """D5: prose_exemplars.json must exist (DEPLOY-DISCIPLINE-1)."""
    path = _bot_cwd() / "data" / "prose_exemplars.json"
    if path.exists():
        result.ok("D5/prose_exemplars")
    else:
        result.fail("D5/prose_exemplars", f"{path} missing — D5 asset check fails")


def run_preflight(*, skip_process_check: bool = False) -> PreflightResult:
    """Run all preflight checks and return aggregated result.

    Args:
        skip_process_check: When True, PF-5 (bot process) is skipped.
            Used in --dry-run mode where we only validate config/files.
    """
    result = PreflightResult()

    check_db_files(result)
    check_telethon_qa_session(result)
    check_stitch_mock(result)
    check_ocr_key(result)
    check_output_dirs(result)
    check_prose_exemplars(result)

    if not skip_process_check:
        check_bot_process(result)
    else:
        result.ok("PF-5/bot_process[skipped-dry-run]")

    return result


def print_preflight(result: PreflightResult) -> None:
    """Print a human-readable preflight summary."""
    print(f"\n{'='*60}")
    print("QA RUBRIC RUNNER — PREFLIGHT")
    print(f"{'='*60}")
    for check in result.checks_run:
        status = "SKIP" if "skipped" in check else "OK  "
        print(f"  {status}  {check}")
    if result.warnings:
        print()
        for w in result.warnings:
            print(f"  {w}")
    if result.failures:
        print()
        for f in result.failures:
            print(f"  {f}")
    print()
    verdict = "PASS" if result.passed else "FAIL"
    print(f"  Preflight: {verdict}")
    print(f"{'='*60}\n")
