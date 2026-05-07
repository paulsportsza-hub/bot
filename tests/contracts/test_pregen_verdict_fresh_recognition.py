"""FIX-PREGEN-VERDICT-FRESHNESS-PROBE-01 contract tests.

Verifies that pregen's verdict-aware freshness probe correctly distinguishes
between the two consumer semantics on the same row state:
  - "warm for pregen": verdict-only rows (narrative_html='', verdict_html populated,
    engine_version='v2_microfact') should NOT be regenerated.
  - "missing for AI Breakdown": same rows are still cache-miss for _get_cached_narrative
    (strict narrative_html semantics unchanged — FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01).

Six tests covering both flag states and both consumer paths.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal narrative_cache DB for testing."""
    db = tmp_path / "test_narrative.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE narrative_cache (
            match_id TEXT PRIMARY KEY,
            narrative_html TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            edge_tier TEXT NOT NULL DEFAULT 'bronze',
            tips_json TEXT NOT NULL DEFAULT '[]',
            odds_hash TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            evidence_json TEXT,
            narrative_source TEXT NOT NULL DEFAULT 'v2_microfact',
            coverage_json TEXT,
            verdict_html TEXT,
            engine_version TEXT,
            status TEXT,
            quarantined INTEGER NOT NULL DEFAULT 0,
            quality_status TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def _insert_row(
    db: Path,
    match_id: str,
    *,
    narrative_html: str = "",
    verdict_html: str | None = None,
    engine_version: str | None = None,
    expires_offset_hours: int = 24,
    quarantined: int = 0,
    status: str | None = None,
    quality_status: str | None = None,
    odds_hash: str = "",
) -> None:
    exp = (datetime.now(timezone.utc) + timedelta(hours=expires_offset_hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR REPLACE INTO narrative_cache "
        "(match_id, narrative_html, expires_at, verdict_html, engine_version, "
        "quarantined, status, quality_status, narrative_source, odds_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            match_id,
            narrative_html,
            exp,
            verdict_html,
            engine_version,
            quarantined,
            status,
            quality_status,
            engine_version or "w82",
            odds_hash,
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Test 1 — verdict-only row is FRESH for pregen under V2
# ---------------------------------------------------------------------------

def test_verdict_only_row_is_fresh_for_pregen_under_v2(tmp_path: Path) -> None:
    """_is_verdict_only_warm returns True for v2_microfact row with verdict_html."""
    db = _make_db(tmp_path)
    _insert_row(
        db,
        "team_a_vs_team_b_2026-05-09",
        narrative_html="",
        verdict_html="<strong>Team A</strong> — Back the home side at 2.10.",
        engine_version="v2_microfact",
    )

    from scripts.pregenerate_narratives import _is_verdict_only_warm

    with (
        patch.dict(os.environ, {"VERDICT_ENGINE_V2": "1"}),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
    ):
        result = asyncio.run(_is_verdict_only_warm("team_a_vs_team_b_2026-05-09"))

    assert result is True, "Verdict-only V2 row must be recognised as warm by pregen"


# ---------------------------------------------------------------------------
# Test 2 — same row is MISSING for AI Breakdown (_get_cached_narrative strict)
# ---------------------------------------------------------------------------

def test_verdict_only_row_remains_missing_for_ai_breakdown(tmp_path: Path) -> None:
    """_get_cached_narrative returns None for the same verdict-only row (strict gate)."""
    db = _make_db(tmp_path)
    _insert_row(
        db,
        "team_a_vs_team_b_2026-05-09",
        narrative_html="",
        verdict_html="<strong>Team A</strong> — Back the home side at 2.10.",
        engine_version="v2_microfact",
    )

    from bot import _get_cached_narrative

    with (
        patch.dict(os.environ, {"VERDICT_ENGINE_V2": "1"}),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
    ):
        result = asyncio.run(_get_cached_narrative("team_a_vs_team_b_2026-05-09"))

    assert result is None, (
        "_get_cached_narrative must return None for verdict-only rows "
        "(AI Breakdown needs full narrative_html — strict gate unchanged)"
    )


# ---------------------------------------------------------------------------
# Test 3 — verdict_html present: _is_verdict_only_warm returns True regardless of narrative_html
# ---------------------------------------------------------------------------

def test_verdict_html_present_is_always_warm_for_pregen(tmp_path: Path) -> None:
    """_is_verdict_only_warm returns True whenever verdict_html is populated.

    Covers a row with BOTH columns populated — the predicate must return True
    since verdict_html is present. In real execution, such a row would be skipped
    via _get_cached_narrative before _is_verdict_only_warm is reached; this test
    asserts the predicate's standalone correctness without implying it covers
    that execution path.
    """
    db = _make_db(tmp_path)
    _insert_row(
        db,
        "team_c_vs_team_d_2026-05-10",
        narrative_html="<p>Full narrative prose text providing match context and analysis.</p>",
        verdict_html=(
            "<strong>Team C</strong> — Back them at 1.85, small signals confirmed "
            "across three markets, stake accordingly and manage risk."
        ),
        engine_version="v2_microfact",
    )

    from scripts.pregenerate_narratives import _is_verdict_only_warm

    with (
        patch.dict(os.environ, {"VERDICT_ENGINE_V2": "1"}),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
    ):
        warm_result = asyncio.run(_is_verdict_only_warm("team_c_vs_team_d_2026-05-10"))

    assert warm_result is True, "Full row with verdict_html must also be warm for pregen"


# ---------------------------------------------------------------------------
# Test 4 — empty row is MISSING for both consumers
# ---------------------------------------------------------------------------

def test_empty_row_is_missing_for_both(tmp_path: Path) -> None:
    """Row with both columns empty: both predicates return missing."""
    db = _make_db(tmp_path)
    _insert_row(
        db,
        "team_e_vs_team_f_2026-05-11",
        narrative_html="",
        verdict_html=None,
        engine_version="v2_microfact",
    )

    from bot import _get_cached_narrative
    from scripts.pregenerate_narratives import _is_verdict_only_warm

    with (
        patch.dict(os.environ, {"VERDICT_ENGINE_V2": "1"}),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
    ):
        narrative_result = asyncio.run(_get_cached_narrative("team_e_vs_team_f_2026-05-11"))
        warm_result = asyncio.run(_is_verdict_only_warm("team_e_vs_team_f_2026-05-11"))

    assert narrative_result is None, "Empty row must be missing for AI Breakdown"
    assert warm_result is False, "Empty row must also be missing for pregen"


# ---------------------------------------------------------------------------
# Test 5 — flag=0 falls back to legacy: verdict-only row treated as MISSING
# ---------------------------------------------------------------------------

def test_flag_off_falls_back_to_legacy_semantics(tmp_path: Path) -> None:
    """Under VERDICT_ENGINE_V2=0, _is_verdict_only_warm always returns False."""
    db = _make_db(tmp_path)
    _insert_row(
        db,
        "team_g_vs_team_h_2026-05-12",
        narrative_html="",
        verdict_html="<strong>Team G</strong> — value at 2.50.",
        engine_version="v2_microfact",
    )

    from scripts.pregenerate_narratives import _is_verdict_only_warm

    with (
        patch.dict(os.environ, {"VERDICT_ENGINE_V2": "0"}),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
    ):
        result = asyncio.run(_is_verdict_only_warm("team_g_vs_team_h_2026-05-12"))

    assert result is False, (
        "Under VERDICT_ENGINE_V2=0, verdict-only rows must be treated as MISSING "
        "(legacy behaviour preserved for rollback path)"
    )


# ---------------------------------------------------------------------------
# Test 6 — bot.py warm gate recognises verdict-only fresh rows
# ---------------------------------------------------------------------------

def test_warm_gate_in_bot_py_recognises_verdict_only_fresh(tmp_path: Path) -> None:
    """_count_uncached_hot_tips returns 0 when all hot tips have V2 verdict-only rows."""
    db = _make_db(tmp_path)
    keys = ["match_1_2026-05-09", "match_2_2026-05-09"]
    for mk in keys:
        _insert_row(
            db,
            mk,
            narrative_html="",
            verdict_html=f"<strong>{mk}</strong> — Edge confirmed.",
            engine_version="v2_microfact",
        )

    from bot import _count_uncached_hot_tips

    with (
        patch.dict(os.environ, {"VERDICT_ENGINE_V2": "1"}),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
    ):
        uncached = _count_uncached_hot_tips(keys)

    assert uncached == 0, (
        "_count_uncached_hot_tips must return 0 when all match_keys have "
        "V2 verdict-only rows — no needless regeneration triggered"
    )


# ---------------------------------------------------------------------------
# Test 7 — _count_warm_narratives counts V2 verdict-only rows (P3 coverage)
# ---------------------------------------------------------------------------

def test_count_warm_narratives_counts_verdict_only_rows(tmp_path: Path) -> None:
    """_count_warm_narratives returns > 0 when V2 verdict-only rows exist in window.

    Guards the startup no-hot-tips fallback path (P3 Codex review finding).
    """
    db = _make_db(tmp_path)
    for i in range(3):
        _insert_row(
            db,
            f"match_warm_{i}_2026-05-09",
            narrative_html="",
            verdict_html=f"<strong>Team {i}</strong> — Value confirmed.",
            engine_version="v2_microfact",
        )

    from bot import _count_warm_narratives

    with (
        patch.dict(os.environ, {"VERDICT_ENGINE_V2": "1"}),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
        patch("bot._NARRATIVE_DB_PATH", str(db)),
    ):
        warm = _count_warm_narratives()

    assert warm >= 3, (
        "_count_warm_narratives must count V2 verdict-only rows so the "
        "startup warmth check does not incorrectly trigger a pregen sweep"
    )


# ---------------------------------------------------------------------------
# Test 8 — _verdict_only_odds_hash returns stored hash (P2 match path)
# ---------------------------------------------------------------------------

def test_verdict_only_odds_hash_returns_stored_hash(tmp_path: Path) -> None:
    """_verdict_only_odds_hash returns the stored odds_hash for a v2_microfact row.

    This is the prerequisite for the full-sweep hash-match skip: when the stored
    hash equals the current computed hash, the gate skips regeneration.
    """
    db = _make_db(tmp_path)
    _insert_row(
        db,
        "match_hash_1_2026-05-09",
        narrative_html="",
        verdict_html="<strong>Team X</strong> — Back at 2.10.",
        engine_version="v2_microfact",
        odds_hash="abc123deadbeef",
    )

    from scripts.pregenerate_narratives import _verdict_only_odds_hash

    with patch("bot._NARRATIVE_DB_PATH", str(db)):
        stored = _verdict_only_odds_hash("match_hash_1_2026-05-09")

    assert stored == "abc123deadbeef", (
        "_verdict_only_odds_hash must return the stored hash so the full-sweep "
        "gate can compare against the current computed hash and skip on match"
    )


# ---------------------------------------------------------------------------
# Test 9 — _verdict_only_odds_hash returns '' for empty hash (P2 drift path)
# ---------------------------------------------------------------------------

def test_verdict_only_odds_hash_returns_empty_for_missing_hash(tmp_path: Path) -> None:
    """_verdict_only_odds_hash returns '' when odds_hash is empty — gate falls through to regen.

    When the stored hash is empty (never written or odds drifted), the full-sweep
    skip condition (_v_hash and _current_hash and _v_hash == _current_hash) evaluates
    False and the row is queued for regeneration, not skipped.
    """
    db = _make_db(tmp_path)
    _insert_row(
        db,
        "match_hash_2_2026-05-09",
        narrative_html="",
        verdict_html="<strong>Team Y</strong> — Lay at 2.80.",
        engine_version="v2_microfact",
        odds_hash="",
    )

    from scripts.pregenerate_narratives import _verdict_only_odds_hash

    with patch("bot._NARRATIVE_DB_PATH", str(db)):
        stored = _verdict_only_odds_hash("match_hash_2_2026-05-09")

    assert stored == "", (
        "_verdict_only_odds_hash must return '' when no valid hash is stored — "
        "the full-sweep gate then falls through to regeneration (odds-drift path)"
    )
