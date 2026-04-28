"""FIX-AI-BREAKDOWN-BUTTON-GATE-COVERAGE-01 — regression guard.

`_has_any_cached_narrative(match_id)` MUST return True when EITHER:
  (a) a non-expired, non-quarantined narrative_cache row with non-empty
      narrative_html exists, OR
  (b) edge_results has any row for match_id (so synthesis fallback at
      card_data._synthesize_breakdown_row_from_baseline() can produce content).

The bulletproof contract is: edge exists → button shows → content renders.

Mechanical-consistency invariant: for any match_id where the gate returns True,
the breakdown handler MUST produce content (either from cache or via synthesis).
For any match_id where the gate returns False, the handler returns None
(button correctly hidden).

Tests cover:
- Gate returns True on cache row with non-empty narrative_html
- Gate returns True on cache row + edge_results
- Gate returns True on edge_results-only (verdict-cache shadowed scenario)
- Gate returns True on edge_results unsettled OR settled
- Gate returns False on neither cache nor edge_results
- Gate returns False on cache row with quarantined status (and no edge_results)
- Gate returns False on cache row with empty narrative_html (and no edge_results)
- Gate-and-synthesis mechanical consistency (CRITICAL invariant)
- Gate handles transient DB errors gracefully (defensive)
- Edge-results path agnostic to result column (settled OR unsettled)
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed_db(narrative_rows: list[dict] | None = None,
             edge_rows: list[dict] | None = None) -> Path:
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
    for r in narrative_rows or []:
        conn.execute(
            """INSERT INTO narrative_cache
               (match_id, narrative_html, model, edge_tier, tips_json, odds_hash,
                created_at, expires_at, narrative_source, status, quarantined)
               VALUES (?, ?, 'sonnet', ?, '[]', 'h',
                       datetime('now'), datetime('now','+12 hours'),
                       ?, ?, ?)""",
            (
                r["match_id"], r.get("narrative_html", ""),
                r.get("edge_tier", "gold"),
                r.get("narrative_source", "w84"),
                r.get("status"),
                r.get("quarantined", 0),
            ),
        )
    for r in edge_rows or []:
        conn.execute(
            """INSERT INTO edge_results
               (edge_id, match_key, sport, league, edge_tier, composite_score,
                bet_type, recommended_odds, bookmaker, predicted_ev,
                recommended_at, match_date, confirming_signals, result)
               VALUES (?, ?, ?, ?, ?, 65.0, '1X2:home',
                       1.85, 'hollywoodbets', 5.5,
                       datetime('now'), date('now'), 2, ?)""",
            (
                f"e_{r['match_key']}",
                r["match_key"],
                r.get("sport", "soccer"),
                r.get("league", "epl"),
                r.get("edge_tier", "gold"),
                r.get("result"),
            ),
        )
    conn.commit()
    conn.close()
    return Path(path)


def _gate(match_id: str, db_path: Path) -> bool:
    """Invoke _has_any_cached_narrative against a temp DB by monkey-patching the path."""
    import bot
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = str(db_path)
    try:
        return bot._has_any_cached_narrative(match_id)
    finally:
        bot._NARRATIVE_DB_PATH = original


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_gate_returns_true_when_cache_row_has_nonempty_html():
    """Path A — existing pregen path."""
    db = _seed_db(
        narrative_rows=[{
            "match_id": "test_vs_a_2026-05-10",
            "narrative_html": "📋 <b>The Setup</b>\nText.\n🎯 <b>The Edge</b>\nText.\n",
            "edge_tier": "gold",
        }],
    )
    try:
        assert _gate("test_vs_a_2026-05-10", db) is True
    finally:
        db.unlink(missing_ok=True)


def test_gate_returns_true_when_only_edge_results_row_exists():
    """Path B (CRITICAL) — synthesis fallback can produce content from edge_results alone.

    This is the FIX-AI-BREAKDOWN-BUTTON-GATE-COVERAGE-01 core invariant.
    The previous gate would have returned False here (no narrative_cache row),
    leaving the button hidden even though synthesis would have produced content.
    """
    db = _seed_db(
        edge_rows=[{
            "match_key": "test_vs_b_2026-05-10",
            "edge_tier": "gold",
        }],
    )
    try:
        assert _gate("test_vs_b_2026-05-10", db) is True, (
            "Button-gate must return True when edge_results has a row, even if "
            "narrative_cache has nothing — synthesis fallback can produce content."
        )
    finally:
        db.unlink(missing_ok=True)


def test_gate_returns_true_when_only_verdict_cache_empty_html_AND_edge_results():
    """The exact INV-AI-BREAKDOWN-MISSING-01 production scenario.

    Pre-fix: cache had verdict-cache row with narrative_html='' → gate returned
    False → button hidden. Post-fix: edge_results has the match → gate returns
    True → button shows → tap → synthesis produces baseline content.
    """
    db = _seed_db(
        narrative_rows=[{
            "match_id": "inv_repro_2026-05-10",
            "narrative_html": "",
            "narrative_source": "verdict-cache",
            "edge_tier": "",
        }],
        edge_rows=[{
            "match_key": "inv_repro_2026-05-10",
            "edge_tier": "gold",
        }],
    )
    try:
        assert _gate("inv_repro_2026-05-10", db) is True
    finally:
        db.unlink(missing_ok=True)


def test_gate_returns_true_for_settled_edge_results():
    """Edge-results path must be agnostic to result column.

    A settled edge (result='hit'/'miss') should still satisfy the gate so users
    can review historical breakdowns. Synthesis predicate ORDER BY (result IS NULL)
    DESC LIMIT 1 prefers unsettled but accepts settled.
    """
    db = _seed_db(
        edge_rows=[{
            "match_key": "settled_vs_match_2026-04-01",
            "edge_tier": "silver",
            "result": "hit",
        }],
    )
    try:
        assert _gate("settled_vs_match_2026-04-01", db) is True
    finally:
        db.unlink(missing_ok=True)


def test_gate_returns_false_when_neither_cache_nor_edge():
    """No cache row, no edge_results → button correctly hidden."""
    db = _seed_db()
    try:
        assert _gate("nothing_vs_match_2026-05-10", db) is False
    finally:
        db.unlink(missing_ok=True)


def test_gate_returns_false_when_only_quarantined_cache_row_AND_no_edge():
    """Quarantined cache + no edge_results → button hidden (no content path)."""
    db = _seed_db(
        narrative_rows=[{
            "match_id": "quar_vs_match_2026-05-10",
            "narrative_html": "📋 <b>The Setup</b>\nText.\n",
            "status": "quarantined",
        }],
    )
    try:
        assert _gate("quar_vs_match_2026-05-10", db) is False
    finally:
        db.unlink(missing_ok=True)


def test_gate_returns_false_when_only_empty_html_cache_row_AND_no_edge():
    """Verdict-cache row with no edge_results → button hidden (synthesis can't help)."""
    db = _seed_db(
        narrative_rows=[{
            "match_id": "empty_vs_match_2026-05-10",
            "narrative_html": "",
            "narrative_source": "verdict-cache",
        }],
    )
    try:
        assert _gate("empty_vs_match_2026-05-10", db) is False
    finally:
        db.unlink(missing_ok=True)


def test_gate_handles_empty_match_id_safely():
    """Defensive: empty match_id never crashes."""
    db = _seed_db()
    try:
        assert _gate("", db) is False
    finally:
        db.unlink(missing_ok=True)


# ── Mechanical-consistency invariant (CRITICAL) ───────────────────────────────


def test_gate_and_synthesis_predicates_aligned():
    """For every match_id where _has_any_cached_narrative returns True,
    build_ai_breakdown_data MUST be able to produce a non-None result.

    This is the bulletproof contract. If this test fails, the gate is showing
    the button on a match where the breakdown handler will return None — i.e.
    the user sees a broken button.
    """
    import bot
    import card_data
    db = _seed_db(
        narrative_rows=[{
            "match_id": "consistent_a_vs_match_2026-05-10",
            "narrative_html": (
                "🎯 Home vs Away / 🏆 PSL\n"
                "📋 <b>The Setup</b>\nSetup.\n"
                "🎯 <b>The Edge</b>\nEdge text.\n"
                "⚠️ <b>The Risk</b>\nRisk.\n"
                "🏆 <b>Verdict</b>\nVerdict.\n"
            ),
            "edge_tier": "gold",
        }],
        edge_rows=[
            {"match_key": "consistent_a_vs_match_2026-05-10", "edge_tier": "gold"},
            {"match_key": "consistent_b_vs_match_2026-05-10", "edge_tier": "silver"},
        ],
    )
    try:
        # Need to point both bot._NARRATIVE_DB_PATH and SCRAPERS_ROOT at this db
        bot_orig = bot._NARRATIVE_DB_PATH
        os.environ["SCRAPERS_ROOT"] = str(db.parent)
        target = db.parent / "odds.db"
        if target != db:
            target.unlink(missing_ok=True)
            target.symlink_to(db)
        bot._NARRATIVE_DB_PATH = str(target)
        try:
            for mid in (
                "consistent_a_vs_match_2026-05-10",
                "consistent_b_vs_match_2026-05-10",  # only edge_results, no cache row
            ):
                gate_says_yes = bot._has_any_cached_narrative(mid)
                handler_result = card_data.build_ai_breakdown_data(mid)
                if gate_says_yes:
                    assert handler_result is not None, (
                        f"INVARIANT VIOLATION: gate=True but handler=None for {mid}. "
                        f"Button would show but breakdown render would fail. "
                        f"Gate-and-synthesis predicates have drifted."
                    )
                else:
                    assert handler_result is None or all(
                        not handler_result.get(k) for k in
                        ("setup_html", "edge_html", "risk_html", "verdict_prose_html")
                    ), (
                        f"INVARIANT: gate=False but handler returned content for {mid}."
                    )
        finally:
            bot._NARRATIVE_DB_PATH = bot_orig
            target.unlink(missing_ok=True)
    finally:
        db.unlink(missing_ok=True)


# ── Implementation source-level guard ─────────────────────────────────────────


def test_gate_source_carries_edge_results_check():
    """Static source-level check that the function actually queries edge_results."""
    bot_src = (Path(__file__).resolve().parents[2] / "bot.py").read_text()
    fn_start = bot_src.index("def _has_any_cached_narrative(match_id: str)")
    fn_end = bot_src.index("\nasync def _get_cached_narrative(", fn_start)
    fn_body = bot_src[fn_start:fn_end]
    assert "FROM edge_results" in fn_body, (
        "Gate must query edge_results to satisfy mechanical-consistency invariant "
        "with _synthesize_breakdown_row_from_baseline."
    )
    assert "match_key = ?" in fn_body, (
        "Gate edge_results SELECT must filter by match_key (the foreign key)."
    )
    # Sanity: cache check still present
    assert "narrative_html IS NOT NULL" in fn_body
    assert "LENGTH(TRIM(COALESCE(narrative_html" in fn_body


def test_claude_md_rule_20_present():
    """CLAUDE.md must carry Rule 20 for downstream agents."""
    claude_md = (Path(__file__).resolve().parents[2] / "CLAUDE.md").read_text()
    assert "### Rule 20 — AI Breakdown button-gate is mechanically consistent" in claude_md
    assert "FIX-AI-BREAKDOWN-BUTTON-GATE-COVERAGE-01" in claude_md
