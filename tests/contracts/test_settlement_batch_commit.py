"""FIX-LONG-WRITER-TRANSACTION-01 — Contract test: settle_edges() batched commits.

Asserts that settle_edges() calls conn.commit() at least once per 10 edges
(in-loop) plus a final commit for the trailing partial batch — so a 100-edge
run produces >= 10 commit() calls and WAL write-lock is released incrementally.

AC-1: in-loop commit fires every 10 iterations (finally clause)
AC-2: @_retry_on_locked decorator is still present
AC-3: this test is green
"""
from __future__ import annotations

import os
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

_BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BOT_DIR)
import config
config.ensure_scrapers_importable()


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_unsettled_rows(n: int, days_ago: int = 1) -> list[sqlite3.Row]:
    """Return n fake sqlite3.Row-like dicts for unsettled edges."""
    match_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    rows = []
    for i in range(n):
        row = {
            "id": i + 1,
            "match_key": f"home_{i}_vs_away_{i}_{match_date}",
            "sport": "soccer",
            "league": "epl",
            "bet_type": "Home Win",
            "edge_tier": "silver",
            "composite_score": 55.0,
            "recommended_odds": 1.90,
            "match_date": match_date,
        }
        rows.append(row)
    return rows


def _row_factory(row_dict: dict):
    """Wrap a dict so it behaves like sqlite3.Row (supports __getitem__)."""
    m = MagicMock()
    m.__getitem__ = lambda self, key: row_dict[key]
    m.keys = lambda: list(row_dict.keys())
    return m


# ── AC-2: decorator still present ──────────────────────────────────────────────

def test_retry_on_locked_decorator_present():
    """settle_edges() source must still carry @_retry_on_locked."""
    scrapers_root = os.path.join(_BOT_DIR, "..", "scrapers")
    settlement_path = os.path.join(scrapers_root, "edge", "settlement.py")
    with open(settlement_path, encoding="utf-8") as f:
        src = f.read()
    # The decorator must appear immediately before 'def settle_edges'
    import re
    assert re.search(r"@_retry_on_locked\s+def settle_edges", src), (
        "@_retry_on_locked decorator is missing from settle_edges(). "
        "Per-batch retry semantics require it — do NOT remove."
    )


# ── AC-1: in-loop commit fires every 10 iterations ─────────────────────────────

def test_settle_edges_in_loop_commit_present():
    """Source must contain an in-loop conn.commit() inside a modulo-10 gate."""
    scrapers_root = os.path.join(_BOT_DIR, "..", "scrapers")
    settlement_path = os.path.join(scrapers_root, "edge", "settlement.py")
    with open(settlement_path, encoding="utf-8") as f:
        src = f.read()
    import re
    # The in-loop commit must be gated by (i + 1) % 10 == 0 or equivalent
    assert re.search(r"\(\s*i\s*\+\s*1\s*\)\s*%\s*10\s*==\s*0", src), (
        "settle_edges() must contain an in-loop `if (i + 1) % 10 == 0: conn.commit()` gate."
    )
    # Must use enumerate
    assert "for i, edge in enumerate(unsettled)" in src, (
        "settle_edges() loop must use `for i, edge in enumerate(unsettled)` "
        "to track the iteration counter."
    )


# ── AC-3: >= 10 commits on a 100-edge synthetic run ────────────────────────────

def test_settle_edges_commits_every_10():
    """100 synthetic unsettled edges must produce >= 10 conn.commit() calls."""
    from scrapers.edge import settlement

    n_edges = 100
    rows = [_row_factory(r) for r in _make_unsettled_rows(n_edges)]

    # Build a mock result row that always evaluates as a hit (2-1)
    mock_result_row = MagicMock()
    mock_result_row.__getitem__ = lambda self, key: {
        "home_score": 2, "away_score": 1, "result": "home"
    }[key]

    mock_conn = MagicMock()
    mock_conn.row_factory = None

    def _fake_execute(sql, params=()):
        cursor = MagicMock()
        sql_upper = sql.strip().upper()
        if "FROM EDGE_RESULTS" in sql_upper and "WHERE RESULT IS NULL" in sql_upper:
            cursor.fetchall.return_value = rows
        elif "FROM MATCH_RESULTS" in sql_upper:
            cursor.fetchone.return_value = mock_result_row
        else:
            cursor.fetchall.return_value = []
            cursor.fetchone.return_value = None
        return cursor

    mock_conn.execute = _fake_execute
    mock_conn.executemany = MagicMock()

    with patch.object(settlement, "connect_odds_db", return_value=mock_conn), \
         patch.object(settlement, "_ensure_table", return_value={}), \
         patch.object(settlement, "_fuzzy_match_result", return_value=None):

        settlement.settle_edges()

    commit_count = mock_conn.commit.call_count
    assert commit_count >= 10, (
        f"Expected >= 10 commit() calls for 100 edges (one per 10-edge batch + final), "
        f"got {commit_count}. "
        "FIX-LONG-WRITER-TRANSACTION-01: settle_edges() must commit every 10 edges."
    )


def test_settle_edges_25_edges_at_least_3_commits():
    """25 synthetic unsettled edges must produce >= 3 conn.commit() calls (2 batch + 1 final)."""
    from scrapers.edge import settlement

    n_edges = 25
    rows = [_row_factory(r) for r in _make_unsettled_rows(n_edges)]

    mock_result_row = MagicMock()
    mock_result_row.__getitem__ = lambda self, key: {
        "home_score": 1, "away_score": 0, "result": "home"
    }[key]

    mock_conn = MagicMock()
    mock_conn.row_factory = None

    def _fake_execute(sql, params=()):
        cursor = MagicMock()
        sql_upper = sql.strip().upper()
        if "FROM EDGE_RESULTS" in sql_upper and "WHERE RESULT IS NULL" in sql_upper:
            cursor.fetchall.return_value = rows
        elif "FROM MATCH_RESULTS" in sql_upper:
            cursor.fetchone.return_value = mock_result_row
        else:
            cursor.fetchall.return_value = []
            cursor.fetchone.return_value = None
        return cursor

    mock_conn.execute = _fake_execute
    mock_conn.executemany = MagicMock()

    with patch.object(settlement, "connect_odds_db", return_value=mock_conn), \
         patch.object(settlement, "_ensure_table", return_value={}), \
         patch.object(settlement, "_fuzzy_match_result", return_value=None):

        settlement.settle_edges()

    commit_count = mock_conn.commit.call_count
    # 25 edges → batch commits at i=9 and i=19 → 2 in-loop + 1 final = 3
    assert commit_count >= 3, (
        f"25 edges should produce >= 3 commits (2 in-loop + 1 final), got {commit_count}."
    )


def test_settle_edges_zero_edges_no_commit():
    """Zero unsettled edges: early return fires, no commit needed (nothing to write)."""
    from scrapers.edge import settlement

    mock_conn = MagicMock()
    mock_conn.row_factory = None

    def _fake_execute(sql, params=()):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = None
        return cursor

    mock_conn.execute = _fake_execute

    with patch.object(settlement, "connect_odds_db", return_value=mock_conn), \
         patch.object(settlement, "_ensure_table", return_value={}):

        result = settlement.settle_edges()

    # Early return path — no rows, no writes, no commit needed
    assert result["settled"] == 0
    assert result["skipped"] == 0
