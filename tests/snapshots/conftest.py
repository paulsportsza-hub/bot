"""Pytest configuration and text snapshot helpers for snapshot tests."""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_DIR.mkdir(exist_ok=True)


def snapshot_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.txt"


def serialize_snapshot(text: str, markup=None) -> str:
    """Render text plus inline keyboard rows into a plain-text golden format."""
    blocks = [text.rstrip()]
    if markup and hasattr(markup, "inline_keyboard"):
        rows: list[str] = []
        for row in markup.inline_keyboard:
            buttons = []
            for button in row:
                payload = button.callback_data or button.url or ""
                buttons.append(f"{button.text} -> {payload}".rstrip())
            rows.append(" | ".join(buttons))
        blocks.extend(["", "[buttons]", *rows])
    return "\n".join(blocks).rstrip() + "\n"


def assert_snapshot(name: str, actual: str, update: bool = False) -> None:
    path = snapshot_path(name)
    if update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return

    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"golden/{name}.txt",
                tofile="actual",
            )
        )
        pytest.fail(
            f"Snapshot mismatch for '{name}'.\n"
            "Run with --update-snapshots to approve changes.\n\n"
            f"{diff}"
        )


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update text golden snapshot files with current output.",
    )


@pytest.fixture
def update_snapshots(request) -> bool:
    return bool(request.config.getoption("--update-snapshots"))
