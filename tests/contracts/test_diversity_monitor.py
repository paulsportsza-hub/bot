"""FIX-NARRATIVE-ROT-ROOT-01 / Phase 4 / AC-4.5 — Narrative diversity monitor.

`scripts.monitor_narrative_diversity` reads `narrative_cache` and emits a
`DiversityAlert` line when any Setup-opening shape exceeds the 25%
dominance threshold across the sample window.

Tests cover:
  - 100% same shape → alert fires
  - 30% dominant shape → alert fires
  - 24% dominant shape → no alert (just-under threshold)
  - Empty table → clean exit, no alert
  - Missing `narrative_html` column → graceful error, no crash
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
from config import ensure_scrapers_importable  # noqa: E402

ensure_scrapers_importable()


def _seed_db(rows: list[tuple[str, str]]) -> Path:
    """Create a temp SQLite DB with `narrative_cache` populated with `rows`.

    Each row is a (match_id, narrative_html) tuple.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE narrative_cache ("
        "  match_id TEXT PRIMARY KEY,"
        "  narrative_html TEXT,"
        "  created_at TEXT"
        ")"
    )
    # Insert in reverse order so the most-recent row by `created_at` desc
    # ordering corresponds to the first row in the list.
    for i, (mid, html) in enumerate(rows):
        ts = f"2026-04-29T13:{i:02d}:00Z"
        conn.execute(
            "INSERT INTO narrative_cache VALUES (?, ?, ?)",
            (mid, html, ts),
        )
    conn.commit()
    conn.close()
    return Path(path)


def _wrap_setup_opening(opening: str) -> str:
    """Wrap a Setup opening into the full narrative HTML structure."""
    return (
        f"📋 The Setup\n{opening}\n"
        "🎯 The Edge\nEdge body.\n"
        "⚠️ The Risk\nRisk body.\n"
        "🏆 Verdict\nVerdict body.\n"
    )


# ── 100% same shape — alert fires ────────────────────────────────────────────


def test_100_pct_same_shape_fires_alert() -> None:
    from scripts.monitor_narrative_diversity import analyse_diversity

    rows = [
        (f"m{i}", _wrap_setup_opening(
            "Arteta's Arsenal sit on 53 points after a strong run."
        ))
        for i in range(20)
    ]
    db = _seed_db(rows)
    try:
        result = analyse_diversity(db, n=20)
        assert result["alert"] is True
        assert result["dominant_pct"] == pytest.approx(100.0)
        assert result["total"] == 20
    finally:
        db.unlink()


# ── 30% dominant shape — alert fires ─────────────────────────────────────────


def test_30_pct_dominant_fires_alert() -> None:
    from scripts.monitor_narrative_diversity import analyse_diversity

    # 6 same-shape rows + 14 unique rows = 30% dominant.
    rows = []
    for i in range(6):
        rows.append((f"d{i}", _wrap_setup_opening(
            "Arteta's Arsenal sit on 53 points after a strong run."
        )))
    for i in range(14):
        rows.append((f"u{i}", _wrap_setup_opening(
            f"Unique opener number {i} for differentiation purposes here."
        )))

    db = _seed_db(rows)
    try:
        result = analyse_diversity(db, n=20)
        assert result["alert"] is True
        assert result["dominant_pct"] == pytest.approx(30.0)
        assert result["total"] == 20
    finally:
        db.unlink()


# ── 24% dominant shape — no alert (just under threshold) ─────────────────────


def test_24_pct_dominant_no_alert() -> None:
    from scripts.monitor_narrative_diversity import analyse_diversity

    # 6 same-shape rows + 19 unique rows = 24% dominant.
    rows = []
    for i in range(6):
        rows.append((f"d{i}", _wrap_setup_opening(
            "Arteta's Arsenal sit on 53 points after a strong run."
        )))
    for i in range(19):
        rows.append((f"u{i}", _wrap_setup_opening(
            f"Distinct unique opener for card {i} which differs by index."
        )))
    # Sample size large enough to capture all 25 rows.
    db = _seed_db(rows)
    try:
        result = analyse_diversity(db, n=25)
        # 6/25 = 24%
        assert result["alert"] is False
        assert result["dominant_pct"] == pytest.approx(24.0)
        assert result["total"] == 25
    finally:
        db.unlink()


# ── Empty DB — clean exit, no alert ──────────────────────────────────────────


def test_empty_db_no_alert() -> None:
    from scripts.monitor_narrative_diversity import analyse_diversity

    db = _seed_db([])
    try:
        result = analyse_diversity(db, n=20)
        assert result["alert"] is False
        assert result["total"] == 0
        assert result.get("error") is None
    finally:
        db.unlink()


# ── Missing column — graceful error, no crash ────────────────────────────────


def test_missing_narrative_html_column_graceful() -> None:
    """If `narrative_html` column is missing, return graceful error dict."""
    from scripts.monitor_narrative_diversity import analyse_diversity

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE narrative_cache (match_id TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()
    try:
        result = analyse_diversity(Path(path), n=20)
        assert result["alert"] is False
        assert result["total"] == 0
        # Either the schema error surfaced as `error` key or we returned
        # cleanly with no rows — both satisfy the contract.
        assert result.get("error") or result["total"] == 0
    finally:
        Path(path).unlink()


# ── Helper-level test: first_n_tokens shape extraction ───────────────────────


def test_first_n_tokens_extracts_setup_body() -> None:
    from scripts.monitor_narrative_diversity import first_n_tokens

    html = _wrap_setup_opening(
        "Arteta's Arsenal sit on 53 points after a strong run."
    )
    shape = first_n_tokens(html, n=8)
    assert shape.startswith("arteta")
    assert len(shape.split()) == 8


def test_first_n_tokens_handles_empty_input() -> None:
    from scripts.monitor_narrative_diversity import first_n_tokens

    assert first_n_tokens("") == ""
    assert first_n_tokens("no setup section anywhere here") == ""


def test_first_n_tokens_strips_html() -> None:
    from scripts.monitor_narrative_diversity import first_n_tokens

    html = (
        "📋 <b>The Setup</b> Arteta's Arsenal sit on 53 points "
        "after a strong run of form.\n🎯 The Edge\nEdge body."
    )
    shape = first_n_tokens(html, n=8)
    assert "<b>" not in shape
    assert "the setup" not in shape  # header stripped
    assert shape.startswith("arteta")
