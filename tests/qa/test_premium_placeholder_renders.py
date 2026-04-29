"""FIX-AI-BREAKDOWN-DEFERRED-PLACEHOLDER-RENDER-01 — AC-3 synthetic harness.

Covers the three premium-card states that exercise the deferred placeholder
path end-to-end (build_ai_breakdown_data → handler short-circuit → template):

1. **Defer state**: edge_results unsettled premium row + gold_verdict_failed_edges
   defer entry, no narrative_cache row. `_check_premium_defer` fires.
2. **Quarantine state**: edge_results unsettled premium row + narrative_cache
   row with `status='quarantined'`, no defer entry. The cache SELECT filter
   excludes the row → cache miss → `_check_premium_quarantined` fires
   (FIX-PREMIUM-POSTWRITE-PROTECTION-01 AC-2).
3. **Orphan state**: edge_results unsettled premium row, no cache row, no
   defer entry, baseline-synthesis fallback also fails (no edge tip data).
   `build_ai_breakdown_data` returns None → handler shows generic "not
   available" message (this path is the real orphan path, not deferred).

All three states MUST NOT produce a Jinja template crash. States 1 and 2
MUST surface as `deferred=True` sentinels and render the placeholder block.
State 3 MUST surface as None and not invoke the template at all.

This harness lives in `tests/qa/` (not `tests/contracts/`) because it seeds
synthetic SQLite DBs end-to-end — closer to integration than unit. The
template-only contract tests live in
`tests/contracts/test_ai_breakdown_deferred_render.py`.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _seed_narrative_cache(db_path: str, match_id: str, *,
                          edge_tier: str = "gold",
                          status: str | None = None,
                          narrative_source: str = "w84",
                          html: str = "",
                          quarantine_reason: str = "") -> None:
    """Seed a narrative_cache row matching the production schema."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS narrative_cache (
                match_id TEXT PRIMARY KEY,
                narrative_html TEXT NOT NULL,
                model TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                tips_json TEXT NOT NULL,
                odds_hash TEXT NOT NULL,
                evidence_json TEXT,
                narrative_source TEXT NOT NULL DEFAULT 'w82',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                verdict_html TEXT,
                evidence_class TEXT,
                tone_band TEXT,
                spec_json TEXT,
                context_json TEXT,
                generation_ms INTEGER,
                coverage_json TEXT,
                structured_card_json TEXT,
                setup_validated INTEGER DEFAULT 1,
                verdict_validated INTEGER DEFAULT 1,
                setup_attempts INTEGER DEFAULT 1,
                verdict_attempts INTEGER DEFAULT 1,
                quality_status TEXT,
                quarantined INTEGER DEFAULT 0,
                status TEXT DEFAULT NULL,
                quarantine_reason TEXT DEFAULT NULL
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
            " narrative_source, created_at, expires_at, status, quarantine_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                match_id,
                html or (
                    "📋 <b>The Setup</b>\nClean prose.\n\n"
                    "🎯 <b>The Edge</b>\nE.\n\n"
                    "⚠️ <b>The Risk</b>\nR.\n\n"
                    "🏆 <b>Verdict</b>\nV."
                ),
                "claude-sonnet-4-6",
                edge_tier,
                "[]",
                "ohash",
                narrative_source,
                datetime.now(timezone.utc).isoformat(),
                (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
                status,
                quarantine_reason,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_edge_results(db_path: str, match_key: str, *,
                       edge_tier: str = "gold") -> None:
    """Seed an edge_results row so _check_premium_edge returns the tier."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edge_results (
                match_key TEXT,
                edge_tier TEXT,
                league TEXT,
                match_date TEXT,
                composite_score REAL,
                bet_type TEXT,
                recommended_odds REAL,
                bookmaker TEXT,
                predicted_ev REAL,
                confirming_signals INTEGER,
                movement TEXT,
                result TEXT,
                recommended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO edge_results "
            "(match_key, edge_tier, league, match_date, composite_score, bet_type, "
            " recommended_odds, bookmaker, predicted_ev, confirming_signals, "
            " movement, result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                match_key, edge_tier, "epl", "2026-05-09", 62.0,
                "1X2:home", 1.85, "Hollywoodbets", 4.5, 2, "neutral", None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_defer(db_path: str, match_key: str, *,
                edge_tier: str = "gold",
                consecutive_count: int = 1) -> None:
    """Seed a gold_verdict_failed_edges defer row in the bot DB."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gold_verdict_failed_edges (
                match_key TEXT PRIMARY KEY,
                edge_tier TEXT NOT NULL,
                fixture TEXT NOT NULL,
                pick TEXT NOT NULL,
                failure_reason TEXT NOT NULL,
                failed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                consecutive_count INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO gold_verdict_failed_edges "
            "(match_key, edge_tier, fixture, pick, failure_reason, consecutive_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (match_key, edge_tier, "Test Fixture", "test_pick",
             "test_reason", consecutive_count),
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# State 1: Defer state — narrative_cache empty, defer row exists
# ─────────────────────────────────────────────────────────────────────────────


def test_defer_state_returns_deferred_sentinel(tmp_path, monkeypatch):
    """Premium edge + defer entry + no cache → build_ai_breakdown_data returns
    {"deferred": True, "defer_count": N, ...}."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    bot_dir_data = Path(__file__).parents[2] / "data"
    bot_db = bot_dir_data / "mzansiedge.db"
    if not bot_db.exists():
        pytest.skip("bot/data/mzansiedge.db not present in this env")

    match_key = "synthetic_defer_test_2026-05-09"
    _seed_edge_results(str(odds_db), match_key, edge_tier="gold")
    _seed_defer(str(bot_db), match_key, edge_tier="gold", consecutive_count=2)

    try:
        from card_data import build_ai_breakdown_data
        result = build_ai_breakdown_data(match_key)
        assert result is not None
        assert result.get("deferred") is True, (
            f"Defer state must surface as deferred=True; got {result!r}"
        )
        assert result.get("defer_count") == 2
    finally:
        # Clean up the seeded defer row so we don't pollute prod state
        _conn = sqlite3.connect(str(bot_db))
        try:
            _conn.execute("DELETE FROM gold_verdict_failed_edges WHERE match_key = ?",
                          (match_key,))
            _conn.commit()
        finally:
            _conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# State 2: Quarantine state — narrative_cache row with status='quarantined'
# ─────────────────────────────────────────────────────────────────────────────


def test_quarantine_state_returns_deferred_sentinel(tmp_path, monkeypatch):
    """Premium edge + quarantined w84 row + no defer entry →
    build_ai_breakdown_data returns {"deferred": True, "quarantine_reason": ...}.
    """
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    match_key = "synthetic_quarantine_test_2026-05-09"
    _seed_edge_results(str(odds_db), match_key, edge_tier="gold")
    _seed_narrative_cache(
        str(odds_db),
        match_key,
        edge_tier="gold",
        status="quarantined",
        quarantine_reason="banned_patterns",
    )

    from card_data import build_ai_breakdown_data
    result = build_ai_breakdown_data(match_key)
    assert result is not None
    assert result.get("deferred") is True, (
        f"Quarantine state must surface as deferred=True; got {result!r}"
    )
    assert result.get("quarantine_reason") == "banned_patterns"


# ─────────────────────────────────────────────────────────────────────────────
# State 3: Orphan state — no cache, no defer, no edge → returns None
# ─────────────────────────────────────────────────────────────────────────────


def test_orphan_state_returns_none(tmp_path, monkeypatch):
    """Truly orphan (no edge data either) → returns None. Caller (handler)
    shows the 'not available' message rather than the placeholder. This is
    the legitimate orphan path — distinct from deferred."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    from card_data import build_ai_breakdown_data
    result = build_ai_breakdown_data("___no_such_match_anywhere___")
    assert result is None, (
        "Truly orphan match (no edge_results entry, no cache, no defer) MUST "
        "return None so the handler emits the 'not available' message"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cross-state: All three states render the template without crashing.
# ─────────────────────────────────────────────────────────────────────────────


def test_all_three_states_render_template_safely():
    """Render the template against each of the three input shapes to confirm
    none crashes the Jinja pipeline. The pre-fix bug was specifically that
    the deferred shape crashed with `'ev_pct' is undefined`."""
    from jinja2 import Environment, FileSystemLoader

    template_dir = Path(__file__).parents[2] / "card_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("ai_breakdown.html")

    cases = [
        ("defer", {"deferred": True, "match_id": "x", "edge_tier": "gold",
                   "defer_count": 1, "fixture": ""}),
        ("quarantine", {"deferred": True, "match_id": "y", "edge_tier": "diamond",
                        "defer_count": 0, "fixture": "",
                        "quarantine_reason": "ev_incoherent:cached=0.5,live=3.0"}),
        ("orphan_partial", {"home": "X", "away": "Y", "tier_label": "🥇",
                            "verdict_tag": "GOLD",
                            # ev_pct intentionally missing — defence-in-depth
                            "setup_html": "", "edge_html": "",
                            "risk_html": "", "verdict_prose_html": "",
                            "cap_reason": ""}),
    ]
    for name, data in cases:
        # If any state crashes, the test fails with an unhelpful Jinja
        # UndefinedError — wrap so the pytest output names the offender.
        try:
            html = template.render(**data)
        except Exception as exc:  # pragma: no cover — defensive
            raise AssertionError(
                f"Template render crashed on '{name}' state with {exc!r}; "
                f"the deferred branch / is-defined guards are incomplete"
            ) from exc
        assert html, f"Template returned empty output for '{name}' state"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
