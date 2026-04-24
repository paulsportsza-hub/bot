"""BUILD-CONTRACT-TESTS-01 — Test 9: View Accounting Idempotency

W84-ACC1 invariants:
  (a) record_tip_view(user_id, match_key, conn) is idempotent per (user, match_key, SAST day):
      calling twice with the same args inserts exactly one row in daily_tip_views.
  (b) check_tip_limit() uses COUNT(DISTINCT match_key) — not COUNT(*) — so old
      duplicate rows do not inflate the per-user daily count.

Uses an isolated in-memory SQLite DB — no live odds.db dependency.
"""
from __future__ import annotations

import os
import sqlite3
import sys

_BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BOT_DIR)
import config
config.ensure_scrapers_importable()

from scrapers.edge.edge_v2_helper import (
    _ensure_tip_views_table,
    check_tip_limit,
    record_tip_view,
)


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _ensure_tip_views_table(conn)
    return conn


# ── (a) record_tip_view idempotency ───────────────────────────────────────────

def test_record_tip_view_inserts_one_row():
    """First call inserts exactly one row."""
    conn = _fresh_db()
    record_tip_view(user_id=1, match_key="arsenal_vs_chelsea_2026-05-01", conn=conn)
    cnt = conn.execute("SELECT COUNT(*) FROM daily_tip_views").fetchone()[0]
    assert cnt == 1, f"Expected 1 row after first record_tip_view, got {cnt}"
    conn.close()


def test_record_tip_view_idempotent_same_fixture():
    """Calling twice with the same (user_id, match_key) inserts exactly one row."""
    conn = _fresh_db()
    mk = "sundowns_vs_pirates_2026-05-02"
    record_tip_view(user_id=2, match_key=mk, conn=conn)
    record_tip_view(user_id=2, match_key=mk, conn=conn)  # duplicate
    cnt = conn.execute("SELECT COUNT(*) FROM daily_tip_views").fetchone()[0]
    assert cnt == 1, (
        f"record_tip_view must be idempotent: expected 1 row after two identical calls, "
        f"got {cnt} (W84-ACC1)."
    )
    conn.close()


def test_record_tip_view_different_fixtures_count_separately():
    """Two different match_keys for the same user each produce their own row."""
    conn = _fresh_db()
    record_tip_view(user_id=3, match_key="chiefs_vs_downs_2026-05-03", conn=conn)
    record_tip_view(user_id=3, match_key="pirates_vs_amazulu_2026-05-03", conn=conn)
    cnt = conn.execute("SELECT COUNT(*) FROM daily_tip_views").fetchone()[0]
    assert cnt == 2, (
        f"Two distinct fixtures for same user should produce 2 rows, got {cnt}"
    )
    conn.close()


def test_record_tip_view_different_users_same_fixture():
    """Same match_key viewed by two different users → two separate rows."""
    conn = _fresh_db()
    mk = "arsenal_vs_liverpool_2026-05-04"
    record_tip_view(user_id=10, match_key=mk, conn=conn)
    record_tip_view(user_id=11, match_key=mk, conn=conn)
    cnt = conn.execute("SELECT COUNT(*) FROM daily_tip_views").fetchone()[0]
    assert cnt == 2, (
        f"Same fixture, different users should produce 2 rows, got {cnt}"
    )
    conn.close()


# ── (b) check_tip_limit uses COUNT(DISTINCT match_key) ────────────────────────

def test_check_tip_limit_source_uses_count_distinct():
    """check_tip_limit() source must use COUNT(DISTINCT match_key).

    This is a permanent architectural requirement from W84-ACC1: each fixture is
    counted once regardless of how many times it was opened (defensive against
    pre-existing duplicate rows).
    """
    import inspect
    src = inspect.getsource(check_tip_limit)
    assert "COUNT(DISTINCT" in src, (
        "W84-ACC1 VIOLATION: check_tip_limit() must use COUNT(DISTINCT match_key), "
        "not COUNT(*). Using COUNT(*) inflates the per-user daily count when "
        "old duplicate rows exist in daily_tip_views."
    )
    assert "match_key" in src, (
        "check_tip_limit() COUNT(DISTINCT must reference match_key column"
    )


def test_check_tip_limit_bronze_allows_below_cap():
    """Bronze user with 0 views today is allowed (can_view=True, remaining=3)."""
    conn = _fresh_db()
    can_view, remaining = check_tip_limit(user_id=99, user_tier="bronze", conn=conn)
    assert can_view is True, "Bronze user with 0 views should be allowed"
    assert remaining == 3, f"Expected 3 remaining for fresh bronze user, got {remaining}"
    conn.close()


def test_check_tip_limit_bronze_blocks_at_cap():
    """Bronze user at 3 distinct fixtures is blocked (can_view=False, remaining=0)."""
    conn = _fresh_db()
    for i in range(3):
        record_tip_view(user_id=5, match_key=f"match_{i}_2026-05-05", conn=conn)
    can_view, remaining = check_tip_limit(user_id=5, user_tier="bronze", conn=conn)
    assert can_view is False, (
        "Bronze user who has viewed 3 distinct fixtures should be blocked"
    )
    assert remaining == 0, f"Expected 0 remaining, got {remaining}"
    conn.close()


def test_check_tip_limit_bronze_duplicate_rows_not_inflated():
    """With pre-existing duplicate rows in daily_tip_views, COUNT(DISTINCT match_key)
    prevents the user from being blocked when they've only seen 1 unique fixture."""
    conn = _fresh_db()
    from datetime import datetime, timezone
    # Manually insert two rows for the same (user, match_key) — simulates old duplicates
    for _ in range(2):
        conn.execute(
            "INSERT INTO daily_tip_views (user_id, match_key, viewed_at) VALUES (?,?,?)",
            (7, "chiefs_vs_downs_2026-05-06", datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()
    # Despite 2 rows, COUNT(DISTINCT) should count it as 1 fixture
    can_view, remaining = check_tip_limit(user_id=7, user_tier="bronze", conn=conn)
    assert can_view is True, (
        "W84-ACC1: duplicate rows for the same fixture must not inflate the view count. "
        "check_tip_limit() must use COUNT(DISTINCT match_key)."
    )
    assert remaining == 2, f"Expected 2 remaining (3 cap - 1 distinct), got {remaining}"
    conn.close()


def test_check_tip_limit_gold_unlimited():
    """Gold (and diamond) users are always allowed regardless of view count."""
    conn = _fresh_db()
    for i in range(10):
        record_tip_view(user_id=8, match_key=f"match_{i}_2026-05-07", conn=conn)
    can_view, remaining = check_tip_limit(user_id=8, user_tier="gold", conn=conn)
    assert can_view is True, "Gold users must always be allowed (unlimited)"
    assert remaining == 999
    conn.close()
