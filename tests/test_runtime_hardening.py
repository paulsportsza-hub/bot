from __future__ import annotations

import os
import subprocess
import sys

import config


def test_resolve_sqlite_url_anchors_relative_paths() -> None:
    resolved = config._resolve_sqlite_url("sqlite+aiosqlite:///data/mzansiedge.db")
    expected = f"sqlite+aiosqlite:///{(config.BOT_ROOT / 'data' / 'mzansiedge.db').as_posix()}"
    assert resolved == expected


def test_resolve_sqlite_url_preserves_in_memory() -> None:
    assert config._resolve_sqlite_url("sqlite+aiosqlite:///:memory:") == "sqlite+aiosqlite:///:memory:"
    assert config._sqlite_path_from_url("sqlite+aiosqlite:///:memory:") is None


def test_config_database_url_is_cwd_safe() -> None:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.setdefault("BOT_TOKEN", "test-token")
    env.setdefault("ODDS_API_KEY", "test-odds-key")
    env.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
    env.setdefault("ADMIN_IDS", "123456")
    env.setdefault("SENTRY_DSN", "")

    code = """
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
print(config.DATABASE_URL)
print(config.DATABASE_PATH)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(config.BOT_ROOT.parent),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    expected_url = f"sqlite+aiosqlite:///{(config.BOT_ROOT / 'data' / 'mzansiedge.db').as_posix()}"
    expected_path = (config.BOT_ROOT / "data" / "mzansiedge.db").as_posix()

    assert result.returncode == 0, result.stderr
    stdout_lines = result.stdout.strip().splitlines()
    assert stdout_lines == [expected_url, expected_path]


def test_match_context_import_no_longer_needs_scrapers_path() -> None:
    code = """
import sys
sys.path.insert(0, str(config.BOT_ROOT.parent))
import scrapers.match_context_fetcher
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(config.BOT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
