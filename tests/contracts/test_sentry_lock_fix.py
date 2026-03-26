from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))
sys.path.insert(0, str(_REPO_ROOT.parent / "scrapers"))
os.chdir(str(_REPO_ROOT))

import scripts.pregenerate_narratives as pregen


def _create_runtime_tables(db_path: Path, *, include_narrative_source: bool = True) -> None:
    conn = sqlite3.connect(db_path)
    narrative_source_col = "narrative_source TEXT NOT NULL DEFAULT 'w82'," if include_narrative_source else ""
    conn.execute(
        f"""
        CREATE TABLE narrative_cache (
            match_id TEXT PRIMARY KEY,
            narrative_html TEXT NOT NULL,
            model TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            tips_json TEXT NOT NULL,
            odds_hash TEXT NOT NULL,
            evidence_json TEXT,
            {narrative_source_col}
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE shadow_narratives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            raw_draft TEXT NOT NULL,
            verified_draft TEXT,
            verification_report TEXT NOT NULL,
            verification_passed BOOLEAN NOT NULL,
            w82_baseline TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def test_validate_pregen_runtime_schema_passes(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _create_runtime_tables(db_path)

    pregen._validate_pregen_runtime_schema(str(db_path))


def test_validate_pregen_runtime_schema_rejects_missing_column(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _create_runtime_tables(db_path, include_narrative_source=False)

    with pytest.raises(RuntimeError, match="narrative_source"):
        pregen._validate_pregen_runtime_schema(str(db_path))


@pytest.mark.asyncio
async def test_wait_for_scraper_writer_window_returns_true_without_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREGEN_SCRAPER_LOCK_FILE", str(tmp_path / "missing.lock"))

    assert await pregen._wait_for_scraper_writer_window() is True


@pytest.mark.asyncio
async def test_wait_for_scraper_writer_window_defers_when_lock_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock_file = tmp_path / "scraper.lock"
    lock_file.write_text(str(os.getpid()))
    monkeypatch.setenv("PREGEN_SCRAPER_LOCK_FILE", str(lock_file))
    monkeypatch.setenv("PREGEN_SCRAPER_WAIT_SECONDS", "0.2")
    monkeypatch.setenv("PREGEN_SCRAPER_WAIT_POLL_SECONDS", "0.05")

    assert await pregen._wait_for_scraper_writer_window() is False


@pytest.mark.asyncio
async def test_wait_for_scraper_writer_window_proceeds_after_lock_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = iter([123, None])

    monkeypatch.setattr(pregen, "_active_scraper_lock_pid", lambda lock_file=None: next(seen, None))
    monkeypatch.setenv("PREGEN_SCRAPER_WAIT_SECONDS", "1")
    monkeypatch.setenv("PREGEN_SCRAPER_WAIT_POLL_SECONDS", "0.01")

    assert await pregen._wait_for_scraper_writer_window() is True


@pytest.mark.asyncio
async def test_main_no_longer_calls_schema_ensure_in_hot_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pregen,
        "_ensure_narrative_cache_table",
        lambda: (_ for _ in ()).throw(AssertionError("hot-path DDL should not run")),
    )
    monkeypatch.setattr(
        pregen,
        "_ensure_shadow_narratives_table",
        lambda: (_ for _ in ()).throw(AssertionError("hot-path DDL should not run")),
    )
    monkeypatch.setattr(pregen, "_wait_for_scraper_writer_window", AsyncMock(return_value=True))
    monkeypatch.setattr(pregen, "_validate_pregen_runtime_schema", lambda db_path=None: None)
    monkeypatch.setattr(pregen, "_load_shadow_pregen_edges", lambda limit=100: [])

    await pregen.main("uncached_only")


@pytest.mark.asyncio
async def test_main_defers_safely_when_scraper_lock_is_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pregen, "_wait_for_scraper_writer_window", AsyncMock(return_value=False))
    monkeypatch.setattr(
        pregen,
        "_validate_pregen_runtime_schema",
        lambda db_path=None: (_ for _ in ()).throw(AssertionError("schema validation should not run")),
    )
    monkeypatch.setattr(
        pregen,
        "_load_shadow_pregen_edges",
        lambda limit=100: (_ for _ in ()).throw(AssertionError("edge load should not run")),
    )

    await pregen.main("refresh")


def test_pregen_enrichment_live_safe_reports_active_scraper_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pregen, "_active_scraper_lock_pid", lambda lock_file=None: 4242)

    live_safe, pid = pregen._pregen_enrichment_live_safe()

    assert live_safe is True
    assert pid == 4242


def test_pregen_enrichment_live_safe_always_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """W84-LOCKFIX: pregen enrichment is ALWAYS read-only to eliminate DB write contention."""
    monkeypatch.setattr(pregen, "_active_scraper_lock_pid", lambda lock_file=None: None)

    live_safe, pid = pregen._pregen_enrichment_live_safe()

    assert live_safe is True, "pregen enrichment must always use live_safe=True (W84-LOCKFIX)"
    assert pid is None


@pytest.mark.asyncio
async def test_get_match_context_uses_readonly_mode_while_scraper_lock_active(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_get_match_context(**kwargs):
        calls.append(kwargs)
        return {
            "data_available": True,
            "home_team": {"name": "Arsenal", "position": 2, "form": "WWWDL"},
            "away_team": {"name": "Bournemouth", "position": 12, "form": "LDWLW"},
        }

    monkeypatch.setattr(pregen, "_pregen_enrichment_live_safe", lambda: (True, 4242))
    # Disable API-Football fetcher so ESPN fallback path is exercised
    monkeypatch.setitem(sys.modules, "fetchers", None)
    fake_module = ModuleType("scrapers.match_context_fetcher")
    fake_module.get_match_context = _fake_get_match_context
    monkeypatch.setitem(sys.modules, "scrapers.match_context_fetcher", fake_module)

    ctx = await pregen._get_match_context("Arsenal", "Bournemouth", "epl", "soccer")

    assert ctx["data_available"] is True
    assert calls
    assert calls[0]["live_safe"] is True


@pytest.mark.asyncio
async def test_get_match_context_preserves_write_capable_mode_when_unlocked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_get_match_context(**kwargs):
        calls.append(kwargs)
        return {
            "data_available": True,
            "home_team": {"name": "Arsenal", "position": 2, "form": "WWWDL"},
            "away_team": {"name": "Bournemouth", "position": 12, "form": "LDWLW"},
        }

    monkeypatch.setattr(pregen, "_pregen_enrichment_live_safe", lambda: (False, None))
    # Disable API-Football fetcher so ESPN fallback path is exercised
    monkeypatch.setitem(sys.modules, "fetchers", None)
    fake_module = ModuleType("scrapers.match_context_fetcher")
    fake_module.get_match_context = _fake_get_match_context
    monkeypatch.setitem(sys.modules, "scrapers.match_context_fetcher", fake_module)

    ctx = await pregen._get_match_context("Arsenal", "Bournemouth", "epl", "soccer")

    assert ctx["data_available"] is True
    assert calls
    assert calls[0]["live_safe"] is False
