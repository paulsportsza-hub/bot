"""FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01 — regression guard.

Three SELECTs reading narrative_cache.narrative_html for the breakdown surface
MUST filter on `narrative_html IS NOT NULL AND LENGTH(TRIM(...)) > 0`.
verdict-cache rows write narrative_html='' (empty string) by construction at
bot.py::_store_verdict_cache_sync INSERT path — these are NOT breakdown-eligible.

When no eligible row exists, build_ai_breakdown_data must synthesize a baseline
row via narrative_spec.build_narrative_spec(...) + _render_baseline(spec) so
users always see content. The _store_verdict_cache_sync writer is unchanged —
verdict_html surface (card image) keeps serving verdict-cache rows.

Tests:
- AC-2 (filter present in 3 SELECTs)
- AC-3 (fallback wires _render_baseline when DB miss)
- AC-12 (writer byte-identical — _store_verdict_cache_sync untouched)
- AC-13 (verdict_html surface unaffected — _get_cached_verdict has no filter)
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import card_data  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed_temp_db() -> Path:
    """Create a temp odds.db with narrative_cache + edge_results tables."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE narrative_cache (
            match_id TEXT PRIMARY KEY,
            narrative_html TEXT NOT NULL,
            model TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            tips_json TEXT NOT NULL,
            odds_hash TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            evidence_json TEXT,
            narrative_source TEXT NOT NULL DEFAULT 'w82',
            coverage_json TEXT,
            structured_card_json TEXT,
            verdict_html TEXT,
            evidence_class TEXT,
            tone_band TEXT,
            spec_json TEXT,
            context_json TEXT,
            generation_ms INTEGER,
            quality_status TEXT,
            quarantined INTEGER DEFAULT 0,
            setup_validated INTEGER DEFAULT 1,
            verdict_validated INTEGER DEFAULT 1,
            setup_attempts INTEGER DEFAULT 1,
            verdict_attempts INTEGER DEFAULT 1,
            status TEXT DEFAULT NULL,
            quarantine_reason TEXT DEFAULT NULL
        );
        CREATE TABLE edge_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            match_key TEXT NOT NULL,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            composite_score REAL NOT NULL,
            bet_type TEXT NOT NULL,
            recommended_odds REAL NOT NULL,
            bookmaker TEXT NOT NULL,
            predicted_ev REAL NOT NULL,
            result TEXT,
            match_score TEXT,
            actual_return REAL,
            recommended_at DATETIME NOT NULL,
            settled_at DATETIME,
            match_date DATE NOT NULL,
            confirming_signals INTEGER DEFAULT NULL,
            movement TEXT,
            posted_to_alerts_direct INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()
    return Path(path)


_VALID_NARRATIVE_HTML = (
    "🎯 Home vs Away / 🏆 PSL\n"
    "📋 <b>The Setup</b>\n"
    "Setup text for the fixture.\n"
    "🎯 <b>The Edge</b>\n"
    "Edge text here at 1.85 with Hollywoodbets.\n"
    "⚠️ <b>The Risk</b>\n"
    "Risk text here.\n"
    "🏆 <b>Verdict</b>\n"
    "Back the home side at 1.85 — the price reflects measured value.\n"
)


def _insert_full_row(db_path: Path, match_id: str, narrative_html: str) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO narrative_cache
           (match_id, narrative_html, model, edge_tier, tips_json, odds_hash,
            created_at, expires_at, narrative_source, verdict_html)
           VALUES (?, ?, 'sonnet', 'gold', '[{"ev":5.0,"bookmaker":"Betway"}]',
                   'h', datetime('now'), datetime('now','+12 hours'),
                   'w84', 'Back home — strong call.')""",
        (match_id, narrative_html),
    )
    conn.commit()
    conn.close()


def _insert_verdict_cache_row(db_path: Path, match_id: str) -> None:
    """Mimic the exact shape _store_verdict_cache_sync INSERT path produces."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO narrative_cache
           (match_id, narrative_html, model, edge_tier, tips_json, odds_hash,
            created_at, expires_at, narrative_source, verdict_html)
           VALUES (?, '', 'view-time', '', '[{"odds":1.85,"bookmaker":"Betway"}]',
                   'h', datetime('now'), datetime('now','+12 hours'),
                   'verdict-cache', 'Back the side at 1.85 — measured.')""",
        (match_id,),
    )
    conn.commit()
    conn.close()


def _insert_edge_result(db_path: Path, match_id: str, tier: str = "gold") -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO edge_results
           (edge_id, match_key, sport, league, edge_tier, composite_score,
            bet_type, recommended_odds, bookmaker, predicted_ev,
            recommended_at, match_date, confirming_signals)
           VALUES (?, ?, 'soccer', 'epl', ?, 65.0, '1X2:home',
                   1.85, 'hollywoodbets', 5.5,
                   datetime('now'), date('now'), 2)""",
        (f"e_{match_id}", match_id, tier),
    )
    conn.commit()
    conn.close()


# ── AC-2: filter present in card_data.build_ai_breakdown_data SELECT ──────────


def test_card_data_select_carries_non_empty_narrative_filter():
    """The SELECT in build_ai_breakdown_data must filter empty narrative_html."""
    src = Path(card_data.__file__).read_text()
    # Find the function body
    fn_start = src.index("def build_ai_breakdown_data(match_id: str)")
    fn_body = src[fn_start: fn_start + 4000]
    # Both branches (with and without quarantine columns) must carry the filter
    assert "narrative_html IS NOT NULL" in fn_body
    assert "LENGTH(TRIM(COALESCE(narrative_html, '')))" in fn_body or \
           "LENGTH(TRIM(COALESCE(narrative_html,'')))" in fn_body
    # Both occurrences (preferred + legacy fallback)
    assert fn_body.count("narrative_html IS NOT NULL") >= 2


# ── AC-2: filter present in bot._get_cached_narrative SELECTs ────────────────


def test_bot_get_cached_narrative_carries_non_empty_filter():
    """Both SELECT branches in _get_cached_narrative must filter empty narrative_html."""
    bot_src = (Path(card_data.__file__).parent / "bot.py").read_text()
    fn_start = bot_src.index("async def _get_cached_narrative(match_id: str)")
    fn_body = bot_src[fn_start: fn_start + 4000]
    assert fn_body.count("narrative_html IS NOT NULL") >= 2, (
        "Both preferred and legacy SELECT branches must carry the filter."
    )
    assert fn_body.count("LENGTH(TRIM(COALESCE(narrative_html") >= 2


# ── AC-2 — DB-level: filter excludes empty narrative_html row ─────────────────


def test_db_select_excludes_empty_narrative_row(monkeypatch):
    """A verdict-cache style row (narrative_html='') must not be returned."""
    db = _seed_temp_db()
    try:
        _insert_verdict_cache_row(db, "westham_vs_arsenal_2026-05-10")
        # No edge_results row → fallback returns None too
        monkeypatch.setenv("SCRAPERS_ROOT", str(db.parent))
        # Ensure we point at our temp DB — the function reads SCRAPERS_ROOT/odds.db
        target = db.parent / "odds.db"
        if target != db:
            target.unlink(missing_ok=True)
            target.symlink_to(db)
        result = card_data.build_ai_breakdown_data("westham_vs_arsenal_2026-05-10")
        assert result is None, (
            "verdict-cache row with empty narrative_html and no edge_results "
            "must yield None (no synthesis possible)."
        )
    finally:
        db.unlink(missing_ok=True)


def test_db_select_returns_full_narrative_row(monkeypatch):
    """A row with non-empty narrative_html must still be returned + parsed."""
    db = _seed_temp_db()
    try:
        _insert_full_row(db, "test_vs_match_2026-05-10", _VALID_NARRATIVE_HTML)
        monkeypatch.setenv("SCRAPERS_ROOT", str(db.parent))
        target = db.parent / "odds.db"
        if target != db:
            target.unlink(missing_ok=True)
            target.symlink_to(db)
        result = card_data.build_ai_breakdown_data("test_vs_match_2026-05-10")
        assert result is not None, "Full pregen row must produce breakdown dict"
        assert "Setup text" in result["setup_html"]
        assert "Edge text here" in result["edge_html"]
        assert "Risk text here" in result["risk_html"]
    finally:
        db.unlink(missing_ok=True)


# ── AC-3 — fallback synthesis wired correctly ─────────────────────────────────


def test_synthesize_baseline_returns_none_when_no_edge_results(monkeypatch):
    """Without an edge_results row for the match, synthesis returns None."""
    db = _seed_temp_db()
    try:
        monkeypatch.setenv("SCRAPERS_ROOT", str(db.parent))
        target = db.parent / "odds.db"
        if target != db:
            target.unlink(missing_ok=True)
            target.symlink_to(db)
        result = card_data._synthesize_breakdown_row_from_baseline(
            "noedge_vs_match_2026-05-10"
        )
        assert result is None
    finally:
        db.unlink(missing_ok=True)


def test_synthesize_baseline_returns_six_tuple_when_edge_exists(monkeypatch):
    """With an edge_results row, synthesis returns a 6-tuple in DB row shape."""
    db = _seed_temp_db()
    try:
        _insert_edge_result(db, "synth_vs_match_2026-05-10", tier="gold")
        monkeypatch.setenv("SCRAPERS_ROOT", str(db.parent))
        target = db.parent / "odds.db"
        if target != db:
            target.unlink(missing_ok=True)
            target.symlink_to(db)
        result = card_data._synthesize_breakdown_row_from_baseline(
            "synth_vs_match_2026-05-10"
        )
        assert result is not None
        assert len(result) == 6, "Must return (narrative_html, edge_tier, tips_json, verdict_html, evidence_class, created_at)"
        narrative_html, edge_tier, tips_json, verdict_html, evidence_class, created_at = result
        assert isinstance(narrative_html, str) and len(narrative_html) > 100
        assert edge_tier == "gold"
        assert tips_json.startswith("[")
        assert verdict_html == ""
        assert evidence_class == ""
        assert created_at  # ISO timestamp
    finally:
        db.unlink(missing_ok=True)


def test_build_ai_breakdown_falls_back_to_baseline_when_only_verdict_cache(monkeypatch):
    """End-to-end: verdict-cache row is filtered out; fallback synthesis fires."""
    db = _seed_temp_db()
    try:
        match_id = "fallback_vs_test_2026-05-10"
        _insert_verdict_cache_row(db, match_id)
        _insert_edge_result(db, match_id, tier="silver")
        monkeypatch.setenv("SCRAPERS_ROOT", str(db.parent))
        target = db.parent / "odds.db"
        if target != db:
            target.unlink(missing_ok=True)
            target.symlink_to(db)
        result = card_data.build_ai_breakdown_data(match_id)
        assert result is not None, (
            "Fallback synthesis must produce a breakdown dict when only "
            "a verdict-cache row exists in narrative_cache."
        )
        # Tier comes from edge_results (silver), not the empty cache tier
        assert "SILVER" in result["tier_label"].upper()
        # All four sections must be populated by the baseline render
        for section in ("setup_html", "edge_html", "risk_html", "verdict_prose_html"):
            assert result[section], f"{section} must be non-empty after baseline render"
    finally:
        db.unlink(missing_ok=True)


# ── AC-12 — writer byte-identical: _store_verdict_cache_sync untouched ────────


def test_store_verdict_cache_sync_body_unchanged():
    """The writer is the empty-narrative source. AC-12: writer byte-identical pre/post.

    This test asserts the verdict-cache INSERT path still writes narrative_html=''
    (the empty string is the design contract — it's why the reader filter is the fix).
    Any change to this INSERT body should fail this test and force a brief amendment.
    """
    bot_src = (Path(card_data.__file__).parent / "bot.py").read_text()
    fn_start = bot_src.index("def _store_verdict_cache_sync(")
    fn_end = bot_src.index("\nasync def ", fn_start)
    fn_body = bot_src[fn_start:fn_end]
    # The literal empty narrative_html in the INSERT statement
    assert "VALUES (?, '', ?, 'view-time'" in fn_body, (
        "_store_verdict_cache_sync INSERT path must keep writing narrative_html='' — "
        "this is the design contract; the reader filter is what makes it safe."
    )
    # And the source label
    assert "'verdict-cache'" in fn_body


# ── AC-13 — verdict_html surface untouched: _get_cached_verdict has NO filter ──


def test_get_cached_verdict_has_no_narrative_html_filter():
    """The card-image surface (verdict_html) must keep serving verdict-cache rows.

    AC-13: filter applies only to the breakdown reader, not to _get_cached_verdict.
    Verifies the SELECT in _get_cached_verdict does NOT carry the narrative_html
    non-empty filter — verdict-cache rows must still produce a verdict on the card.
    """
    bot_src = (Path(card_data.__file__).parent / "bot.py").read_text()
    fn_start = bot_src.index("def _get_cached_verdict(match_key: str)")
    fn_end = bot_src.index("\ndef ", fn_start + 1)
    fn_body = bot_src[fn_start:fn_end]
    # Narrow check: the SELECT statement reading verdict_html should NOT filter
    # narrative_html non-empty. Look for "verdict_html" SELECT inside this fn.
    assert "SELECT verdict_html" in fn_body, "Must keep reading verdict_html"
    assert "LENGTH(TRIM(COALESCE(narrative_html" not in fn_body, (
        "_get_cached_verdict must NOT filter on narrative_html — that surface "
        "is the card image, which serves verdict_html from any source row "
        "including verdict-cache rows where narrative_html is empty by design."
    )


# ── CLAUDE.md Rule 19 anchor — locked-rule freshness guard ────────────────────


def test_claude_md_rule_19_present():
    """CLAUDE.md must carry Rule 19 for downstream agents to find it."""
    claude_md = (Path(card_data.__file__).parent / "CLAUDE.md").read_text()
    assert "### Rule 19 — AI Breakdown reader filters empty narrative_html" in claude_md
    assert "FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01" in claude_md
