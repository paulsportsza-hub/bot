from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# BUILD-PREGEN-KICKOFF-FILTER-01: use a future match date so the kickoff filter
# never skips these canary fixtures.
_FUTURE_DATE = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))
sys.path.insert(0, str(_REPO_ROOT.parent / "scrapers"))
os.chdir(str(_REPO_ROOT))

import bot
import narrative_spec
import scripts.pregenerate_narratives as pregen


def _edge() -> dict:
    return {
        "match_key": f"arsenal_vs_bournemouth_{_FUTURE_DATE}",
        "home_team": "Arsenal",
        "away_team": "Bournemouth",
        "league": "Premier League",
        "sport": "soccer",
        "commence_time": f"{_FUTURE_DATE} 15:00 UTC",
        "best_odds": 2.10,
        "best_bookmaker": "Betway",
        "edge_pct": 5.2,
        "fair_probability": 0.52,
        "recommended_outcome": "home",
        "outcome": "home",
        # W93-COST (2026-04-22): Sonnet polish is gated to gold/diamond. Use gold here so
        # the W84 generation path runs; silver/bronze now deterministically serve the
        # W82 baseline (see test_generate_one_silver_bronze_skips_w84_polish).
        "tier": "gold",
        "confirming_signals": 2,
        "composite_score": 58.0,
        "bookmaker_count": 2,
        "signals": {"movement": {"direction": "neutral"}},
        "stale_minutes": 5,
    }


def _baseline_text() -> str:
    # W92-VERDICT-QUALITY: the baseline verdict is served back to gold-tier
    # canary tests when the W84 path fails verification or errors. It therefore
    # has to pass the same gold quality gate (≥110 chars, ≥3 analytical words).
    return (
        "📋 <b>The Setup</b>\n"
        "Arsenal host Bournemouth here.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway have Arsenal at 2.10.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Standard variance applies.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Arsenal at Betway 2.10, with the price movement and confirming "
        "signals supporting a measured stake on the home side's recent form."
    )


def _w84_text() -> str:
    # W92-VERDICT-QUALITY: gold-tier verdicts must pass min_verdict_quality
    # (≥110 chars, ≥3 analytical vocab words, no banned template, no markdown).
    # Fixture verdict intentionally composed to satisfy these gates so that the
    # Sonnet polish path can be exercised without tripping the W92 gate.
    return (
        "📋 <b>The Setup</b>\n"
        "W84 setup.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway have Arsenal at 2.10.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "W84 risk.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Signals support backing Arsenal at 2.10 on Betway, with price "
        "movement and confirming indicators aligning favourably for this "
        "position."
    )


class _FakeMessages:
    async def create(self, **kwargs):
        return {"content": "unused"}


class _FakeClaude:
    def __init__(self):
        self.messages = _FakeMessages()


def _patch_generate_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", AsyncMock(side_effect=lambda e: e))
    monkeypatch.setattr(pregen, "_get_match_context", AsyncMock(return_value={"data_available": True}))
    monkeypatch.setattr(
        pregen,
        "build_evidence_pack",
        AsyncMock(return_value=SimpleNamespace(richness_score="high")),
    )
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda pack: '{"ok": true}')
    monkeypatch.setattr(
        narrative_spec,
        "build_narrative_spec",
        lambda ctx, edge_data, tips, sport: SimpleNamespace(
            home_story_type="momentum",
            away_story_type="crisis",
        ),
    )
    monkeypatch.setattr(narrative_spec, "_render_baseline", lambda spec: _baseline_text())
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda text: text)
    monkeypatch.setattr(pregen, "_strip_model_generated_h2h_references", lambda text: text)
    monkeypatch.setattr(pregen, "_strip_model_generated_sharp_references", lambda text: text)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda text: text)
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda pack, spec: "")
    monkeypatch.setattr(pregen, "_build_sharp_injection", lambda pack, spec: "")
    monkeypatch.setattr(pregen, "_inject_h2h_sentence", lambda text, sentence: text)
    monkeypatch.setattr(pregen, "_inject_sharp_sentence", lambda text, sentence: text)
    monkeypatch.setattr(pregen, "_extract_text_from_response", lambda resp: _w84_text())
    monkeypatch.setattr(pregen, "_get_exemplars_for_prompt", lambda *args, **kwargs: [])
    monkeypatch.setattr(pregen, "_build_polish_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(pregen, "_validate_polish", lambda polished, baseline, spec: True)


@pytest.mark.asyncio
async def test_cache_table_adds_narrative_source_column(tmp_path) -> None:
    db_path = str(tmp_path / "cache.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    try:
        bot._ensure_narrative_cache_table()
        import sqlite3

        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_cache)").fetchall()}
        conn.close()
        assert "narrative_source" in cols
    finally:
        bot._NARRATIVE_DB_PATH = original


@pytest.mark.asyncio
async def test_cache_round_trips_narrative_source(tmp_path) -> None:
    import sqlite3

    db_path = str(tmp_path / "cache.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS odds_latest ("
        "match_id TEXT, bookmaker TEXT, home_odds REAL, draw_odds REAL, away_odds REAL)"
    )
    conn.commit()
    conn.close()
    try:
        bot._ensure_narrative_cache_table()
        # P0-FIX-33: W84 cached entries must contain HTML section headers.
        # Sections need >30 chars of content to pass _has_empty_sections check.
        # BUILD-NARRATIVE-WATERTIGHT-01 C.1: verdict must satisfy min_verdict_quality
        # at the cached tier (silver floor = 120 chars) otherwise the serve-time gate
        # correctly rejects it. Extended the verdict stub to pass the floor.
        _w84_html = (
            "📋 <b>The Setup</b>\nArsenal sit 2nd on 54 points, in strong form.\n\n"
            "🎯 <b>The Edge</b>\nBookmaker pricing implies 28% but model reads 34%.\n\n"
            "⚠️ <b>The Risk</b>\nBournemouth away record is decent, keep stake measured.\n\n"
            "🏆 <b>Verdict</b>\nArteta's Gunners look sharp at the bookies' numbers, "
            "with three confirming signals lined up behind a 5.2% EV edge. Back them at "
            "home with a standard stake — enough backing to commit, not enough to overcommit."
        )
        await bot._store_narrative_cache(
            "arsenal_vs_bournemouth_2026-03-21",
            _w84_html,
            [{"outcome": "home", "odds": 2.1, "ev": 5.2}],
            "silver",
            "sonnet",
            narrative_source="w84",
        )
        cached = await bot._get_cached_narrative("arsenal_vs_bournemouth_2026-03-21")
        assert cached is not None
        assert cached["narrative_source"] == "w84"
    finally:
        bot._NARRATIVE_DB_PATH = original


@pytest.mark.asyncio
async def test_generate_one_serves_w84_when_verify_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_generate_dependencies(monkeypatch)

    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda pack, spec: "prompt")
    monkeypatch.setattr(
        pregen,
        "verify_shadow_narrative",
        lambda draft, pack, spec: (True, {"sanitized_draft": _w84_text()}),
    )

    result = await pregen._generate_one(_edge(), "claude-sonnet", _FakeClaude())

    assert result["success"] is True
    assert result["_cache"]["narrative_source"] == "w84"
    assert "Signals support backing Arsenal at 2.10 on Betway" in result["narrative"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["silver", "bronze"])
async def test_generate_one_silver_bronze_skips_w84_polish(
    monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    """W93-COST: silver/bronze tiers must serve the W82 baseline — no Sonnet polish.

    Guards the tier gate in pregenerate_narratives._generate_one that skips the W84
    polish path for non-premium tiers. Without this gate, cost-target regressions
    surface as $15+/day spikes (see W93-COST wave notes).
    """
    _patch_generate_dependencies(monkeypatch)

    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda pack, spec: "prompt")
    # If the gate leaks, verify_shadow_narrative would be invoked — set a sentinel
    # that would incorrectly flip the source to w84 if it were ever called.
    monkeypatch.setattr(
        pregen,
        "verify_shadow_narrative",
        lambda draft, pack, spec: (True, {"sanitized_draft": _w84_text()}),
    )

    edge = _edge()
    edge["tier"] = tier
    result = await pregen._generate_one(edge, "claude-sonnet", _FakeClaude())

    assert result["success"] is True
    assert result["_cache"]["narrative_source"] == "w82"
    assert "Lean Arsenal at Betway 2.10" in result["narrative"]


@pytest.mark.asyncio
async def test_generate_one_falls_back_to_w82_when_verify_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_generate_dependencies(monkeypatch)

    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda pack, spec: "prompt")
    monkeypatch.setattr(
        pregen,
        "verify_shadow_narrative",
        lambda draft, pack, spec: (False, {"rejection_reasons": ["bad h2h"]}),
    )

    result = await pregen._generate_one(_edge(), "claude-sonnet", _FakeClaude())

    assert result["success"] is True
    assert result["_cache"]["narrative_source"] == "w82"
    assert "Lean Arsenal at Betway 2.10" in result["narrative"]


@pytest.mark.asyncio
async def test_generate_one_falls_back_to_w82_on_w84_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_generate_dependencies(monkeypatch)

    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda pack, spec: "prompt")

    async def _boom(**kwargs):
        raise RuntimeError("anthropic down")

    claude = _FakeClaude()
    monkeypatch.setattr(claude.messages, "create", _boom)

    result = await pregen._generate_one(_edge(), "claude-sonnet", claude)

    assert result["success"] is True
    assert result["_cache"]["narrative_source"] == "w82"
    assert "Lean Arsenal at Betway 2.10" in result["narrative"]


@pytest.mark.asyncio
async def test_verify_and_fill_cache_fills_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    """W84-CONFIRM-1: verify_and_fill_cache fills gaps without shadow tasks."""
    monkeypatch.setattr(pregen, "_get_cached_narrative", AsyncMock(return_value=None))
    monkeypatch.setattr(
        pregen,
        "_generate_one",
        AsyncMock(
            return_value={
                "success": True,
                "_cache": {
                    "match_id": "arsenal_vs_bournemouth_2026-03-21",
                    "html": "<b>x</b>",
                    "tips": [],
                    "edge_tier": "silver",
                    "model": "sonnet",
                    "narrative_source": "w84",
                },
            }
        ),
    )
    monkeypatch.setattr(pregen, "_store_narrative_cache", AsyncMock())

    await pregen._verify_and_fill_cache([_edge()], "claude-sonnet", _FakeClaude(), "full")


@pytest.mark.asyncio
async def test_main_runs_w84_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """W84-CONFIRM-1: main() always runs W84 generation (no env-var gate)."""
    # BUILD-16a: _wait_for_scraper_writer_window removed — pregen no longer depends on scraper lock
    monkeypatch.setattr(pregen, "_validate_pregen_runtime_schema", lambda db_path=None: None)
    monkeypatch.setattr(pregen, "_load_pregen_edges", lambda limit=100, sport=None: [_edge()])
    monkeypatch.setattr(pregen, "_get_cached_narrative", AsyncMock(return_value=None))
    monkeypatch.setattr(pregen, "_store_narrative_cache", AsyncMock())
    monkeypatch.setattr(pregen, "_verify_and_fill_cache", AsyncMock())
    monkeypatch.setattr(pregen, "_check_verdict_balance", lambda verdicts: None)
    monkeypatch.setattr(pregen.anthropic, "AsyncAnthropic", lambda api_key=None: _FakeClaude())

    async def _generate_one(*args, **kwargs):
        return {
            "success": True,
            "duration": 0.01,
            "narrative": _w84_text(),
            "_cache": {
                "match_id": "arsenal_vs_bournemouth_2026-03-21",
                "html": "<b>x</b>",
                "tips": [],
                "edge_tier": "silver",
                "model": "sonnet",
                "evidence_json": "{}",
                "narrative_source": "w84",
            },
        }

    monkeypatch.setattr(pregen, "_generate_one", _generate_one)

    await pregen.main("full")


@pytest.mark.asyncio
async def test_get_cached_narrative_preserves_w84_h2h_from_evidence(tmp_path) -> None:
    import json
    import sqlite3

    db_path = str(tmp_path / "cache.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS odds_latest ("
        "match_id TEXT, bookmaker TEXT, home_odds REAL, draw_odds REAL, away_odds REAL)"
    )
    conn.execute(
        "INSERT INTO odds_latest (match_id, bookmaker, home_odds, draw_odds, away_odds) "
        "VALUES (?, ?, ?, ?, ?)",
        ("stellenbosch_vs_chippa_united_2026-03-21", "Betway", 2.10, 3.10, 3.40),
    )
    conn.commit()
    conn.close()

    try:
        bot._ensure_narrative_cache_table()
        evidence_json = json.dumps(
            {
                "h2h": {
                    "summary_text": "2 meetings: Stellenbosch 1W 1D 0L",
                    "matches": [{"score": "0-0"}],
                }
            }
        )
        await bot._store_narrative_cache(
            "stellenbosch_vs_chippa_united_2026-03-21",
            # BUILD-NARRATIVE-WATERTIGHT-01 C.1: verdict needs to satisfy the serve-time
            # min_verdict_quality gate at the silver tier (≥120 chars, terminal punct, SA
            # voice). Extended the stub to pass the floor while still exercising the H2H
            # evidence path that this canary is asserting on.
            (
                "📋 <b>The Setup</b>\n"
                "Head to head: 2 meetings: Stellenbosch 1W 1D 0L, and the last meeting finished 0-0.\n\n"
                "🎯 <b>The Edge</b>\n"
                "Betway have Stellenbosch at 2.10.\n\n"
                "⚠️ <b>The Risk</b>\n"
                "Variance still matters.\n\n"
                "🏆 <b>Verdict</b>\n"
                "Lean Stellenbosch at the Betway 2.10 numbers — H2H leans their way and the "
                "model still gives them value at this price, so stake it at a measured standard "
                "and let the edge do its work across the full card."
            ),
            [{"outcome": "home", "odds": 2.1, "ev": 3.8}],
            "silver",
            "sonnet",
            evidence_json=evidence_json,
            narrative_source="w84",
        )

        cached = await bot._get_cached_narrative("stellenbosch_vs_chippa_united_2026-03-21")
        assert cached is not None
        assert cached["narrative_source"] == "w84"
    finally:
        bot._NARRATIVE_DB_PATH = original
