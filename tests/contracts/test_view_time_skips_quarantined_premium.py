"""FIX-PREMIUM-POSTWRITE-PROTECTION-01 — AC-2.

When a Gold/Diamond ``narrative_cache`` row gets ``status='quarantined'`` by
the post-write quality gates, the view-time path MUST treat it as orphan and
return the deferred sentinel — never fall through to W82 synthesis-on-tap.

Predecessor brief documented (Brentford–West Ham + Brighton–Wolves on 29 Apr):
- 12:14 W84 SERVED for liverpool_vs_chelsea_2026-05-09 → committed as w84
- 12:27 cache miss → background fill triggered
- post-deploy investigation: status='quarantined' flipped on the existing row

The cache SELECT in ``card_data.build_ai_breakdown_data`` already excludes
``status='quarantined'`` rows (FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01).
But for premium cards: when the quarantined row is the ONLY cache entry AND
no ``gold_verdict_failed_edges`` defer entry exists, the cache-miss path was
falling through to ``_synthesize_breakdown_row_from_baseline`` — the W82
boilerplate Paul observed.

The fix adds ``_check_premium_quarantined`` after ``_check_premium_defer`` in
the cache-miss branch. If a quarantined Gold/Diamond row exists, return the
deferred sentinel so the user sees the placeholder. The pregen sweep (or
polish retry) replaces the row on the next cycle.

This is defence-in-depth — AC-1 (Setup-section prompt tightening) closes the
trigger; AC-2 ensures the gate's downstream consequence (quarantine status
on a w84 row) doesn't expose users to W82 boilerplate during the polish-retry
window.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — synthetic narrative_cache + edge_results fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _seed_narrative_cache(db_path: str, match_id: str, *,
                          edge_tier: str = "gold",
                          status: str | None = None,
                          narrative_source: str = "w84",
                          html: str = "",
                          quarantine_reason: str = "") -> None:
    """Seed a narrative_cache row matching the production schema (canonical
    columns plus the FIX-NARRATIVE-CACHE-DEATH-01 quarantine columns)."""
    conn = sqlite3.connect(db_path)
    try:
        # Schema mirrors the production narrative_cache shape after every
        # ALTER TABLE in _ensure_narrative_cache_table() — the SELECT in
        # build_ai_breakdown_data requires evidence_class to be present.
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
                match_key,
                edge_tier,
                "epl",
                "2026-05-09",
                62.0,
                "1X2:home",
                1.85,
                "Hollywoodbets",
                4.5,
                2,
                "neutral",
                None,  # unsettled
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# AC-2 — _check_premium_quarantined returns dict for tainted premium row
# ─────────────────────────────────────────────────────────────────────────────


def test_check_premium_quarantined_returns_dict_for_gold(tmp_path, monkeypatch):
    """Quarantined Gold w84 row → returns sentinel with reason captured."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    _seed_narrative_cache(
        str(odds_db),
        "liverpool_vs_chelsea_2026-05-09",
        edge_tier="gold",
        status="quarantined",
        quarantine_reason="banned_patterns",
    )

    from card_data import _check_premium_quarantined

    result = _check_premium_quarantined("liverpool_vs_chelsea_2026-05-09")
    assert result is not None, (
        "Quarantined Gold row must surface as a sentinel — falls through to "
        "W82 synthesis otherwise (Paul's 29 Apr W82 boilerplate regression)"
    )
    assert result["edge_tier"] == "gold"
    assert result["match_key"] == "liverpool_vs_chelsea_2026-05-09"
    assert result["quarantine_reason"] == "banned_patterns"


def test_check_premium_quarantined_returns_dict_for_diamond(tmp_path, monkeypatch):
    """Diamond tier follows same rule as Gold."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    _seed_narrative_cache(
        str(odds_db),
        "atletico_madrid_vs_arsenal_2026-04-29",
        edge_tier="diamond",
        status="quarantined",
        quarantine_reason="verdict_quality:standalone_ok=False",
    )

    from card_data import _check_premium_quarantined

    result = _check_premium_quarantined("atletico_madrid_vs_arsenal_2026-04-29")
    assert result is not None
    assert result["edge_tier"] == "diamond"


def test_check_premium_quarantined_skips_silver(tmp_path, monkeypatch):
    """Silver/Bronze tier quarantines do NOT trip the helper — non-premium
    cards have no premium contract to honour, W82 synthesis is the right
    fallback for them."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    _seed_narrative_cache(
        str(odds_db),
        "test_silver_2026-05-09",
        edge_tier="silver",
        status="quarantined",
        quarantine_reason="banned_patterns",
    )

    from card_data import _check_premium_quarantined

    assert _check_premium_quarantined("test_silver_2026-05-09") is None, (
        "Silver-tier quarantine MUST NOT trigger premium-defer placeholder — "
        "Silver still serves W82 baseline per W93-TIER-GATE policy"
    )


def test_check_premium_quarantined_skips_clean_w84(tmp_path, monkeypatch):
    """A clean (non-quarantined) w84 row MUST NOT trigger the helper —
    only quarantined rows are orphan-equivalent."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    _seed_narrative_cache(
        str(odds_db),
        "clean_w84_2026-05-09",
        edge_tier="gold",
        status=None,  # NOT quarantined
    )

    from card_data import _check_premium_quarantined

    assert _check_premium_quarantined("clean_w84_2026-05-09") is None, (
        "Clean w84 rows must NOT trigger — the cache SELECT will serve them "
        "directly. False positives here would hide good content."
    )


def test_check_premium_quarantined_returns_none_when_db_missing(tmp_path, monkeypatch):
    """Missing odds.db → returns None, never raises (best-effort contract)."""
    monkeypatch.setenv("SCRAPERS_ROOT", str(tmp_path / "no_scrapers"))

    from card_data import _check_premium_quarantined

    assert _check_premium_quarantined("___no_db___") is None


# ─────────────────────────────────────────────────────────────────────────────
# AC-2 — build_ai_breakdown_data returns deferred sentinel when premium edge
#        has only a quarantined cache row (no defer entry)
# ─────────────────────────────────────────────────────────────────────────────


def test_build_breakdown_returns_deferred_for_quarantined_premium_orphan(
    tmp_path, monkeypatch,
):
    """End-to-end view-time path: quarantined w84 + premium edge + no defer
    row → build_ai_breakdown_data returns the deferred sentinel rather than
    falling through to W82 synthesis. This is the AC-2 user-visible behaviour."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    # Seed: quarantined w84 row + matching edge_results (premium edge exists)
    _seed_narrative_cache(
        str(odds_db),
        "brighton_vs_wolves_2026-05-09",
        edge_tier="gold",
        status="quarantined",
        quarantine_reason="banned_patterns",
    )
    _seed_edge_results(
        str(odds_db),
        "brighton_vs_wolves_2026-05-09",
        edge_tier="gold",
    )
    # NOTE: NO bot/data/mzansiedge.db gold_verdict_failed_edges row →
    # _check_premium_defer returns None → AC-2's _check_premium_quarantined
    # MUST fire on the quarantined row.

    from card_data import build_ai_breakdown_data

    result = build_ai_breakdown_data("brighton_vs_wolves_2026-05-09")
    assert result is not None, (
        "build_ai_breakdown_data must NOT return None when a premium edge "
        "exists — orphan path is reserved for unreachable matches"
    )
    assert result.get("deferred") is True, (
        f"Quarantined Gold w84 with no defer entry MUST surface as deferred=True "
        f"sentinel — got {result!r}. Without this, view-time falls through to "
        f"W82 synthesis (the regression Paul observed)"
    )
    assert result.get("edge_tier") == "gold"
    assert result.get("match_id") == "brighton_vs_wolves_2026-05-09"
    assert "quarantine_reason" in result, (
        "Deferred sentinel from quarantine path must carry quarantine_reason "
        "for ops triage"
    )


def test_build_breakdown_serves_clean_w84_normally(tmp_path, monkeypatch):
    """Sanity guard: a clean (non-quarantined) w84 row renders normally —
    AC-2's quarantine helper must NOT interfere with the happy path."""
    scrapers_dir = tmp_path / "scrapers"
    scrapers_dir.mkdir()
    odds_db = scrapers_dir / "odds.db"
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))

    _seed_narrative_cache(
        str(odds_db),
        "arsenal_vs_fulham_2026-05-09",
        edge_tier="gold",
        status=None,  # CLEAN
    )
    _seed_edge_results(
        str(odds_db),
        "arsenal_vs_fulham_2026-05-09",
        edge_tier="gold",
    )

    from card_data import build_ai_breakdown_data

    result = build_ai_breakdown_data("arsenal_vs_fulham_2026-05-09")
    assert result is not None
    assert result.get("deferred") is not True, (
        "Clean w84 row MUST NOT be served as deferred — that hides good content"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC-2 — Wiring guards: log marker, helper definition, observability
# ─────────────────────────────────────────────────────────────────────────────


def test_card_data_carries_quarantine_helper_and_log_marker():
    """Structural guard: card_data.py must define _check_premium_quarantined
    and the wiring must log the brief marker for observability."""
    bot_dir = Path(__file__).parents[2]
    src = (bot_dir / "card_data.py").read_text(encoding="utf-8")

    assert "def _check_premium_quarantined(" in src, (
        "card_data must define _check_premium_quarantined helper"
    )
    assert "FIX-PREMIUM-POSTWRITE-PROTECTION-01" in src, (
        "Brief marker must be present so the wiring is discoverable in grep"
    )
    assert "PremiumQuarantined" in src, (
        "Log marker 'PremiumQuarantined' must be present for ops triage"
    )


def test_view_time_skip_quarantined_select_filter_intact():
    """Regression guard: the cache SELECT in build_ai_breakdown_data MUST
    still filter status='quarantined' rows. AC-2's helper is defence-in-depth
    on TOP of this filter, not a replacement."""
    bot_dir = Path(__file__).parents[2]
    src = (bot_dir / "card_data.py").read_text(encoding="utf-8")

    # The primary filter must still be present on the narrative_cache SELECT.
    assert "status != 'quarantined'" in src, (
        "card_data.build_ai_breakdown_data must STILL filter quarantined rows "
        "from the cache SELECT — AC-2's helper is defence-in-depth, not a "
        "replacement for the primary filter"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
