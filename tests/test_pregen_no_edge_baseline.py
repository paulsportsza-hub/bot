from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

import asyncio
import datetime
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot
from scripts import pregenerate_narratives as pregen

# Future dates so the DB date-filter (substr(match_id,-10) >= today) always passes.
_FUTURE_DATE_1 = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
_FUTURE_DATE_2 = (datetime.date.today() + datetime.timedelta(days=12)).isoformat()
_MATCH_KEY_1 = f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}"
_MATCH_KEY_2 = f"amazulu_vs_orlando_pirates_{_FUTURE_DATE_2}"


def _create_snapshot_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE odds_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmaker TEXT NOT NULL,
            match_id TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            league TEXT NOT NULL,
            sport TEXT NOT NULL,
            market_type TEXT NOT NULL,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            scraped_at TEXT NOT NULL
        );

        CREATE TABLE edge_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT NOT NULL,
            result TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO odds_snapshots (
            bookmaker, match_id, home_team, away_team, league, sport, market_type,
            home_odds, draw_odds, away_odds, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "hollywoodbets",
                _MATCH_KEY_1,
                "ts_galaxy",
                "polokwane_city",
                "psl",
                "soccer",
                "1x2",
                2.3,
                3.0,
                3.0,
                "2026-04-03T07:30:08+00:00",
            ),
            (
                "supabets",
                _MATCH_KEY_1,
                "ts_galaxy",
                "polokwane_city",
                "psl",
                "soccer",
                "1x2",
                2.5,
                3.0,
                2.8,
                "2026-04-03T07:31:08+00:00",
            ),
            (
                "hollywoodbets",
                _MATCH_KEY_2,
                "amazulu",
                "orlando_pirates",
                "psl",
                "soccer",
                "1x2",
                3.1,
                3.0,
                2.1,
                "2026-04-03T07:30:08+00:00",
            ),
        ],
    )
    conn.execute(
        "INSERT INTO edge_results (match_key, result) VALUES (?, NULL)",
        (_MATCH_KEY_2,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# BUILD-DUAL-MODEL-PREGEN: HAIKU_MODEL constant
# ---------------------------------------------------------------------------

def test_haiku_model_constant_present() -> None:
    """HAIKU_MODEL constant must be present in pregenerate_narratives."""
    assert hasattr(pregen, "HAIKU_MODEL")
    assert "haiku" in pregen.HAIKU_MODEL.lower()


# ---------------------------------------------------------------------------
# _load_snapshot_baseline_edges: is_non_edge flag (not skip_sonnet_polish)
# ---------------------------------------------------------------------------

def test_load_snapshot_baseline_edges_discovers_no_edge_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "odds.db"
    _create_snapshot_db(db_path)

    async def _fake_best_odds(match_id: str, market_type: str = "1x2") -> dict:
        assert market_type == "1x2"
        return {
            "match_id": match_id,
            "home_team": "ts_galaxy",
            "away_team": "polokwane_city",
            "league": "psl",
            "bookmaker_count": 2,
            "outcomes": {
                "home": {
                    "best_odds": 2.30,
                    "best_bookmaker": "hollywoodbets",
                    "all_bookmakers": {"hollywoodbets": 2.30, "supabets": 2.20},
                },
                "draw": {
                    "best_odds": 3.00,
                    "best_bookmaker": "supabets",
                    "all_bookmakers": {"hollywoodbets": 3.00, "supabets": 3.00},
                },
                "away": {
                    "best_odds": 3.00,
                    "best_bookmaker": "hollywoodbets",
                    "all_bookmakers": {"hollywoodbets": 3.00, "supabets": 2.80},
                },
            },
        }

    monkeypatch.setattr("scrapers.db_connect.connect_odds_db", lambda _path: sqlite3.connect(db_path))
    monkeypatch.setattr("services.odds_service.get_best_odds", _fake_best_odds)
    monkeypatch.setattr(bot, "_display_team_name", lambda name: name.replace("_", " ").title())
    monkeypatch.setattr(bot, "_display_bookmaker_name", lambda name: name.title())

    edges = pregen._load_snapshot_baseline_edges(limit=10)

    assert len(edges) == 1
    edge = edges[0]
    assert edge["match_key"] == _MATCH_KEY_1
    assert edge["narrative_source_hint"] == "baseline_no_edge"
    # BUILD-DUAL-MODEL-PREGEN: is_non_edge replaces skip_sonnet_polish
    assert edge["is_non_edge"] is True
    assert "skip_sonnet_polish" not in edge or edge.get("skip_sonnet_polish") is not True
    assert edge["commence_time"] == f"{_FUTURE_DATE_1}T00:00:00+00:00"
    assert edge["best_odds"] == 2.30
    assert edge["bookmaker_count"] == 2
    assert edge["edge_pct"] <= 0


def test_baseline_edge_has_is_non_edge_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-edge baseline edges must carry is_non_edge=True, not skip_sonnet_polish."""
    db_path = tmp_path / "odds.db"
    _create_snapshot_db(db_path)

    async def _fake_best_odds(match_id: str, market_type: str = "1x2") -> dict:
        return {
            "match_id": match_id,
            "home_team": "ts_galaxy",
            "away_team": "polokwane_city",
            "league": "psl",
            "bookmaker_count": 1,
            "outcomes": {
                "home": {"best_odds": 2.10, "best_bookmaker": "hollywoodbets", "all_bookmakers": {}},
                "draw": {"best_odds": 3.20, "best_bookmaker": "hollywoodbets", "all_bookmakers": {}},
                "away": {"best_odds": 3.50, "best_bookmaker": "hollywoodbets", "all_bookmakers": {}},
            },
        }

    monkeypatch.setattr("scrapers.db_connect.connect_odds_db", lambda _path: sqlite3.connect(db_path))
    monkeypatch.setattr("services.odds_service.get_best_odds", _fake_best_odds)
    monkeypatch.setattr(bot, "_display_team_name", lambda name: name.replace("_", " ").title())
    monkeypatch.setattr(bot, "_display_bookmaker_name", lambda name: name.title())

    edges = pregen._load_snapshot_baseline_edges(limit=10)
    for edge in edges:
        assert edge.get("is_non_edge") is True, f"{edge['match_key']} missing is_non_edge=True"
        # Must NOT have skip_sonnet_polish set to True (old flag is gone)
        assert not edge.get("skip_sonnet_polish"), f"{edge['match_key']} has stale skip_sonnet_polish"


# ---------------------------------------------------------------------------
# _generate_one: Haiku is called for is_non_edge=True edges
# ---------------------------------------------------------------------------

def _make_haiku_resp(text: str):
    """Build a mock Claude response object with the given text."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


_VALID_PREVIEW = (
    "📋 <b>The Setup</b>\n"
    "TS Galaxy host Polokwane City at home in PSL action.\n\n"
    "🎯 <b>The Edge</b>\n"
    "The home side holds a marginal pricing advantage at 2.30.\n\n"
    "⚠️ <b>The Risk</b>\n"
    "Away form data is limited — treat conservatively.\n\n"
    "🏆 <b>Verdict</b>\n"
    "Home side is the slight lean. Watch for early price movement."
)


@pytest.mark.asyncio
async def test_generate_one_non_edge_calls_haiku_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_non_edge=True edge must call HAIKU_MODEL, not SHADOW_MODEL."""
    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": True, "_context_mode": "FULL"}

    class _Pack:
        richness_score = 0.5
        coverage_metrics = None

    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(pregen, "build_evidence_pack", AsyncMock(return_value=_Pack()))
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _pack: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda *_args, **_kwargs: "preview prompt")
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: (
            "📋 <b>The Setup</b>\nBaseline.\n\n"
            "🎯 <b>The Edge</b>\nEdge.\n\n"
            "⚠️ <b>The Risk</b>\nRisk.\n\n"
            "🏆 <b>Verdict</b>\nMonitor home at 2.30 with Hollywoodbets."
        ),
    )

    haiku_resp = _make_haiku_resp(_VALID_PREVIEW)
    create_mock = AsyncMock(return_value=haiku_resp)
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    edge = {
        "match_key": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
        "home_team": "TS Galaxy",
        "away_team": "Polokwane City",
        "league": "psl",
        "sport": "soccer",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 2.3,
        "best_bookmaker": "Hollywoodbets",
        "best_bookmaker_key": "hollywoodbets",
        "edge_pct": -0.8,
        "fair_probability": 0.43,
        "composite_score": 52.0,
        "bookmaker_count": 2,
        "tier": "bronze",
        "narrative_source_hint": "baseline_no_edge",
        "is_non_edge": True,
        "commence_time": f"{_FUTURE_DATE_1}T00:00:00+00:00",
    }

    result = await pregen._generate_one(edge, "claude-sonnet-4-20250514", claude, sweep_type="refresh")

    # Claude MUST be called (Haiku path)
    assert create_mock.called, "Claude should be called for is_non_edge=True edges"
    # Must use HAIKU_MODEL, not SHADOW_MODEL
    call_kwargs = create_mock.call_args
    assert call_kwargs.kwargs.get("model") == pregen.HAIKU_MODEL, (
        f"Expected HAIKU_MODEL={pregen.HAIKU_MODEL!r}, "
        f"got {call_kwargs.kwargs.get('model')!r}"
    )


@pytest.mark.asyncio
async def test_generate_one_non_edge_uses_preview_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_non_edge=True must call format_evidence_prompt with match_preview=True."""
    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": True, "_context_mode": "FULL"}

    class _Pack:
        richness_score = 0.5
        coverage_metrics = None

    prompt_calls: list[dict] = []

    def _capturing_prompt(pack, spec, match_preview: bool = False) -> str:
        prompt_calls.append({"match_preview": match_preview})
        return "captured prompt"

    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(pregen, "build_evidence_pack", AsyncMock(return_value=_Pack()))
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _pack: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(pregen, "format_evidence_prompt", _capturing_prompt)
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: "📋 <b>The Setup</b>\nX.\n\n🎯 <b>The Edge</b>\nY.\n\n⚠️ <b>The Risk</b>\nZ.\n\n🏆 <b>Verdict</b>\nV.",
    )

    haiku_resp = _make_haiku_resp(_VALID_PREVIEW)
    create_mock = AsyncMock(return_value=haiku_resp)
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    edge = {
        "match_key": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
        "home_team": "TS Galaxy",
        "away_team": "Polokwane City",
        "league": "psl",
        "sport": "soccer",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 2.3,
        "best_bookmaker": "Hollywoodbets",
        "best_bookmaker_key": "hollywoodbets",
        "edge_pct": -0.8,
        "fair_probability": 0.43,
        "composite_score": 52.0,
        "bookmaker_count": 2,
        "tier": "bronze",
        "narrative_source_hint": "baseline_no_edge",
        "is_non_edge": True,
        "commence_time": f"{_FUTURE_DATE_1}T00:00:00+00:00",
    }

    await pregen._generate_one(edge, "claude-sonnet-4-20250514", claude, sweep_type="refresh")

    assert len(prompt_calls) == 1, "format_evidence_prompt should be called once"
    assert prompt_calls[0]["match_preview"] is True, "match_preview must be True for non-edge"


@pytest.mark.asyncio
async def test_generate_one_non_edge_haiku_success_sets_w84_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful Haiku polish must set narrative_source='w84'."""
    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": True, "_context_mode": "FULL"}

    class _Pack:
        richness_score = 0.5
        coverage_metrics = None

    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(pregen, "build_evidence_pack", AsyncMock(return_value=_Pack()))
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _pack: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: "📋 <b>The Setup</b>\nX.\n\n🎯 <b>The Edge</b>\nY.\n\n⚠️ <b>The Risk</b>\nZ.\n\n🏆 <b>Verdict</b>\nV.",
    )

    create_mock = AsyncMock(return_value=_make_haiku_resp(_VALID_PREVIEW))
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    edge = {
        "match_key": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
        "home_team": "TS Galaxy",
        "away_team": "Polokwane City",
        "league": "psl",
        "sport": "soccer",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 2.3,
        "best_bookmaker": "Hollywoodbets",
        "best_bookmaker_key": "hollywoodbets",
        "edge_pct": -0.8,
        "fair_probability": 0.43,
        "composite_score": 52.0,
        "bookmaker_count": 2,
        "tier": "bronze",
        "narrative_source_hint": "baseline_no_edge",
        "is_non_edge": True,
        "commence_time": f"{_FUTURE_DATE_1}T00:00:00+00:00",
    }

    result = await pregen._generate_one(edge, "claude-sonnet-4-20250514", claude, sweep_type="refresh")

    assert result["success"] is True
    assert result["_cache"]["narrative_source"] == "w84"


@pytest.mark.asyncio
async def test_generate_one_non_edge_haiku_success_sets_haiku_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful Haiku polish must set model='haiku' in _cache."""
    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": True, "_context_mode": "FULL"}

    class _Pack:
        richness_score = 0.5
        coverage_metrics = None

    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(pregen, "build_evidence_pack", AsyncMock(return_value=_Pack()))
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _pack: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: "📋 <b>The Setup</b>\nX.\n\n🎯 <b>The Edge</b>\nY.\n\n⚠️ <b>The Risk</b>\nZ.\n\n🏆 <b>Verdict</b>\nV.",
    )

    create_mock = AsyncMock(return_value=_make_haiku_resp(_VALID_PREVIEW))
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    edge = {
        "match_key": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
        "home_team": "TS Galaxy",
        "away_team": "Polokwane City",
        "league": "psl",
        "sport": "soccer",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 2.3,
        "best_bookmaker": "Hollywoodbets",
        "best_bookmaker_key": "hollywoodbets",
        "edge_pct": -0.8,
        "fair_probability": 0.43,
        "composite_score": 52.0,
        "bookmaker_count": 2,
        "tier": "bronze",
        "narrative_source_hint": "baseline_no_edge",
        "is_non_edge": True,
        "commence_time": f"{_FUTURE_DATE_1}T00:00:00+00:00",
    }

    result = await pregen._generate_one(edge, "claude-sonnet-4-20250514", claude, sweep_type="refresh")

    assert result["_cache"]["model"] == "haiku"


@pytest.mark.asyncio
async def test_generate_one_non_edge_haiku_fail_falls_back_to_w82(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Haiku validation fails, narrative_source must fall back to baseline_no_edge (W82)."""
    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": True, "_context_mode": "FULL"}

    class _Pack:
        richness_score = 0.5
        coverage_metrics = None

    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(pregen, "build_evidence_pack", AsyncMock(return_value=_Pack()))
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _pack: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: "📋 <b>The Setup</b>\nX.\n\n🎯 <b>The Edge</b>\nY.\n\n⚠️ <b>The Risk</b>\nZ.\n\n🏆 <b>Verdict</b>\nV.",
    )

    # Haiku returns a response that fails validation (missing 3 section headers)
    bad_response = "Only the Setup\n📋 <b>The Setup</b>\nSome content here."
    create_mock = AsyncMock(return_value=_make_haiku_resp(bad_response))
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    edge = {
        "match_key": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
        "home_team": "TS Galaxy",
        "away_team": "Polokwane City",
        "league": "psl",
        "sport": "soccer",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 2.3,
        "best_bookmaker": "Hollywoodbets",
        "best_bookmaker_key": "hollywoodbets",
        "edge_pct": -0.8,
        "fair_probability": 0.43,
        "composite_score": 52.0,
        "bookmaker_count": 2,
        "tier": "bronze",
        "narrative_source_hint": "baseline_no_edge",
        "is_non_edge": True,
        "commence_time": f"{_FUTURE_DATE_1}T00:00:00+00:00",
    }

    result = await pregen._generate_one(edge, "claude-sonnet-4-20250514", claude, sweep_type="refresh")

    assert result["success"] is True
    # Must fall back to baseline (not w84)
    assert result["_cache"]["narrative_source"] != "w84"
    assert result["_cache"]["model"] != "haiku"


@pytest.mark.asyncio
async def test_generate_one_edge_match_calls_sonnet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge matches (is_non_edge=False/absent) must call SHADOW_MODEL, not HAIKU_MODEL."""
    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": True, "_context_mode": "FULL"}

    class _Pack:
        richness_score = 0.5
        coverage_metrics = None

    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(pregen, "build_evidence_pack", AsyncMock(return_value=_Pack()))
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _pack: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)
    monkeypatch.setattr(pregen, "_strip_model_generated_h2h_references", lambda s: s)
    monkeypatch.setattr(pregen, "_strip_model_generated_sharp_references", lambda s: s)
    monkeypatch.setattr(pregen, "_build_sharp_injection", lambda *_args, **_kwargs: "")

    # verify_shadow_narrative: reject so we get w82 fallback (avoids bookmaker alignment logic)
    monkeypatch.setattr(
        pregen, "verify_shadow_narrative",
        lambda draft, pack, spec: (False, {"rejection_reasons": ["test_rejection"]}),
    )

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: "📋 <b>The Setup</b>\nX.\n\n🎯 <b>The Edge</b>\nY.\n\n⚠️ <b>The Risk</b>\nZ.\n\n🏆 <b>Verdict</b>\nMonitor home at 2.30 with Hollywoodbets.",
    )

    sonnet_resp = _make_haiku_resp("Sonnet narrative text with all sections.")
    create_mock = AsyncMock(return_value=sonnet_resp)
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    edge = {
        "match_key": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
        "home_team": "TS Galaxy",
        "away_team": "Polokwane City",
        "league": "psl",
        "sport": "soccer",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 2.3,
        "best_bookmaker": "Hollywoodbets",
        "best_bookmaker_key": "hollywoodbets",
        "edge_pct": 3.5,  # positive EV = edge match
        "fair_probability": 0.43,
        "composite_score": 60.0,
        "bookmaker_count": 2,
        "tier": "gold",  # gold passes W93-TIER-GATE so Sonnet polish is attempted
        "narrative_source_hint": "w82",
        # is_non_edge NOT set — this is an edge match
        "commence_time": f"{_FUTURE_DATE_1}T00:00:00+00:00",
    }

    await pregen._generate_one(edge, "claude-sonnet-4-20250514", claude, sweep_type="refresh")

    assert create_mock.called, "Claude should be called for edge matches"
    call_kwargs = create_mock.call_args
    # Must use SHADOW_MODEL, not HAIKU_MODEL
    assert call_kwargs.kwargs.get("model") != pregen.HAIKU_MODEL, (
        "Edge matches must not use HAIKU_MODEL"
    )
    assert call_kwargs.kwargs.get("model") == pregen.SHADOW_MODEL


# ---------------------------------------------------------------------------
# _validate_preview_polish
# ---------------------------------------------------------------------------

def test_validate_preview_polish_accepts_valid_preview() -> None:
    """A properly structured preview passes validation."""
    spec = SimpleNamespace(home_name="TS Galaxy", away_name="Polokwane City")
    assert pregen._validate_preview_polish(_VALID_PREVIEW, spec) is True


def test_validate_preview_polish_rejects_missing_headers() -> None:
    """Missing any of the 4 section headers must fail validation."""
    spec = SimpleNamespace(home_name=None, away_name=None)
    # Missing 🎯, ⚠️, 🏆 — only has 📋
    partial = "📋 <b>The Setup</b>\nSome content."
    assert pregen._validate_preview_polish(partial, spec) is False


def test_validate_preview_polish_rejects_missing_team() -> None:
    """If home team name is absent, validation fails."""
    spec = SimpleNamespace(home_name="AmazuluFC", away_name="Orlando Pirates")
    # "AmazuluFC" is NOT in the preview (first word check = "amazulufc")
    assert pregen._validate_preview_polish(_VALID_PREVIEW, spec) is False


def test_validate_preview_polish_rejects_bet_recommendation() -> None:
    """Bet recommendation phrases in preview output must fail validation."""
    spec = SimpleNamespace(home_name=None, away_name=None)
    bad_preview = (
        "📋 <b>The Setup</b>\nSetup text.\n\n"
        "🎯 <b>The Edge</b>\nEdge text.\n\n"
        "⚠️ <b>The Risk</b>\nRisk text.\n\n"
        "🏆 <b>Verdict</b>\nWorth backing the home side."
    )
    assert pregen._validate_preview_polish(bad_preview, spec) is False


def test_validate_preview_polish_rejects_value_play_phrase() -> None:
    """'value play' is a banned betting phrase in preview mode."""
    spec = SimpleNamespace(home_name=None, away_name=None)
    bad_preview = (
        "📋 <b>The Setup</b>\nSetup.\n\n"
        "🎯 <b>The Edge</b>\nThis is a real value play here.\n\n"
        "⚠️ <b>The Risk</b>\nRisk.\n\n"
        "🏆 <b>Verdict</b>\nLean home."
    )
    assert pregen._validate_preview_polish(bad_preview, spec) is False


def test_validate_preview_polish_no_spec_home_away() -> None:
    """If spec has no home_name/away_name, team check is skipped — headers still required."""
    spec = SimpleNamespace()  # no home_name or away_name
    # Missing section headers = fail
    assert pregen._validate_preview_polish("Some text without headers", spec) is False
    # All headers present = pass
    assert pregen._validate_preview_polish(_VALID_PREVIEW, spec) is True


# ---------------------------------------------------------------------------
# main() skip logic: zero edge_pct must NOT skip non-edge matches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_hot_tips_v1_fallback_carries_snapshot_material(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "DB_LEAGUES", ["psl"])
    monkeypatch.setattr(bot, "_display_team_name", lambda name: name.replace("_", " ").title())
    monkeypatch.setattr(bot, "_display_bookmaker_name", lambda name: name.title())
    monkeypatch.setattr(bot, "_get_league_display", lambda league, *_args: league.upper())
    monkeypatch.setattr(bot, "_build_edge_snapshots_from_match", lambda _match: {"snapshots": True})
    monkeypatch.setattr(bot, "_build_model_from_consensus", lambda _match: {"outcome": "home"})
    monkeypatch.setattr(bot.odds_svc, "detect_line_movement", AsyncMock(return_value={}))
    monkeypatch.setattr(bot, "calculate_edge_rating", lambda *_args, **_kwargs: bot.EdgeRating.BRONZE)
    monkeypatch.setattr(bot, "calculate_edge_score", lambda *_args, **_kwargs: 57.0)
    monkeypatch.setattr(bot, "apply_guardrails", lambda edge_enum, ev, bk_count: (edge_enum, ev, None))
    # V2 is required (TIER-FIX-01). Return a minimal valid result so the match is not skipped.
    monkeypatch.setattr(
        "scrapers.edge.edge_v2_helper.calculate_edge_v2",
        lambda *args, **kwargs: {
            "tier": "gold",
            "composite_score": 57.0,
            "edge_pct": 3.5,
            "outcome": "home",
            "confidence": "high",
            "sharp_source": "sa_consensus",
            "best_bookmaker": "hollywoodbets",
            "best_odds": 2.6,
            "fair_probability": 0.45,
            "confirming_signals": 2,
        },
    )
    # Bypass CARD-BUILD-01 population gate — card rendering not under test here.
    import card_pipeline
    monkeypatch.setattr(card_pipeline, "verify_card_populates", lambda tip, mid: (True, {}))
    # Bypass real odds.db fixture_mapping lookup — unit test should not depend on DB state.
    monkeypatch.setattr(bot, "_load_fixture_kickoffs", lambda ids: {})

    async def _fake_matches(*_args, **_kwargs) -> list[dict]:
        return [{
            "match_id": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
            "home_team": "ts_galaxy",
            "away_team": "polokwane_city",
            "bookmaker_count": 2,
            "outcomes": {
                    "home": {
                        "best_odds": 2.6,
                        "best_bookmaker": "hollywoodbets",
                        "all_bookmakers": {"hollywoodbets": 2.6, "supabets": 2.4},
                    },
                "draw": {
                    "best_odds": 3.0,
                    "best_bookmaker": "supabets",
                    "all_bookmakers": {"hollywoodbets": 3.0, "supabets": 3.0},
                },
                "away": {
                    "best_odds": 3.0,
                    "best_bookmaker": "hollywoodbets",
                    "all_bookmakers": {"hollywoodbets": 3.0, "supabets": 2.8},
                },
            },
        }]

    monkeypatch.setattr(bot.odds_svc, "get_all_matches", _fake_matches)

    tips = await bot._fetch_hot_tips_from_db_inner()

    assert len(tips) == 1
    tip = tips[0]
    assert tip["best_odds"] == 2.6
    assert tip["n_bookmakers"] == 2
    assert tip["composite_score"] == 57.0


# ---------------------------------------------------------------------------
# FIX-HAIKU-GATE: Empty evidence gate bypass for non-edge matches (AC-6)
# ---------------------------------------------------------------------------

def _make_edge(is_non_edge: bool, coverage_level: str = "empty") -> dict:
    """Build a minimal edge dict for gate tests."""

    class _CovMetrics:
        level = coverage_level

    class _Pack:
        richness_score = 0.0
        coverage_metrics = _CovMetrics() if coverage_level == "empty" else None

    return {
        "edge": {
            "match_key": f"ts_galaxy_vs_polokwane_city_{_FUTURE_DATE_1}",
            "home_team": "TS Galaxy",
            "away_team": "Polokwane City",
            "league": "psl",
            "sport": "soccer",
            "recommended_outcome": "home",
            "outcome": "home",
            "best_odds": 2.3,
            "best_bookmaker": "Hollywoodbets",
            "best_bookmaker_key": "hollywoodbets",
            "edge_pct": -0.8,
            "fair_probability": 0.43,
            "composite_score": 52.0,
            "bookmaker_count": 2,
            "tier": "bronze",
            "narrative_source_hint": "baseline_no_edge",
            "is_non_edge": is_non_edge,
            "commence_time": f"{_FUTURE_DATE_1}T00:00:00+00:00",
        },
        "pack": _Pack(),
    }


def _apply_standard_monkeypatches(monkeypatch, pack, capture_prompt=None):
    """Apply standard monkeypatches for _generate_one gate tests."""

    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": False, "_context_mode": "PARTIAL"}

    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(pregen, "build_evidence_pack", AsyncMock(return_value=pack))
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _p: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_a, **_k: "")
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)

    if capture_prompt is not None:
        monkeypatch.setattr(pregen, "format_evidence_prompt", capture_prompt)
    else:
        monkeypatch.setattr(pregen, "format_evidence_prompt", lambda *_a, **_k: "prompt")

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: (
            "📋 <b>The Setup</b>\nX.\n\n"
            "🎯 <b>The Edge</b>\nY.\n\n"
            "⚠️ <b>The Risk</b>\nZ.\n\n"
            "🏆 <b>Verdict</b>\nMonitor home at 2.30 with Hollywoodbets."
        ),
    )


# (a) Non-edge + empty evidence → Haiku is reached
@pytest.mark.asyncio
async def test_empty_evidence_non_edge_reaches_haiku(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX-HAIKU-GATE (a): Non-edge match with empty evidence must reach Haiku."""
    bundle = _make_edge(is_non_edge=True, coverage_level="empty")
    _apply_standard_monkeypatches(monkeypatch, bundle["pack"])

    create_mock = AsyncMock(return_value=_make_haiku_resp(_VALID_PREVIEW))
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    result = await pregen._generate_one(
        bundle["edge"], "claude-sonnet-4-20250514", claude, sweep_type="refresh"
    )

    assert create_mock.called, "Haiku must be called for non-edge + empty evidence"
    call_kwargs = create_mock.call_args
    assert call_kwargs.kwargs.get("model") == pregen.HAIKU_MODEL


# (b) Edge match + empty evidence → still blocked (no Haiku call)
@pytest.mark.asyncio
async def test_empty_evidence_edge_match_still_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX-HAIKU-GATE (b): Edge match with empty evidence must still be blocked."""
    bundle = _make_edge(is_non_edge=False, coverage_level="empty")
    _apply_standard_monkeypatches(monkeypatch, bundle["pack"])

    # Also patch Sonnet path so it doesn't crash if somehow reached
    monkeypatch.setattr(pregen, "_strip_model_generated_h2h_references", lambda s: s)
    monkeypatch.setattr(pregen, "_strip_model_generated_sharp_references", lambda s: s)
    monkeypatch.setattr(pregen, "_build_sharp_injection", lambda *_a, **_k: "")
    monkeypatch.setattr(
        pregen,
        "verify_shadow_narrative",
        lambda draft, pack, spec: (False, {"rejection_reasons": ["blocked"]}),
    )

    create_mock = AsyncMock(return_value=_make_haiku_resp("irrelevant"))
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    result = await pregen._generate_one(
        bundle["edge"], "claude-sonnet-4-20250514", claude, sweep_type="refresh"
    )

    assert not create_mock.called, "Claude must NOT be called for edge + empty evidence"
    assert result["success"] is True
    assert result["_cache"]["narrative_source"] != "w84"


# (c) Haiku receives minimal context prompt when evidence is empty
@pytest.mark.asyncio
async def test_empty_evidence_non_edge_receives_minimal_context_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX-HAIKU-GATE (c): Minimal context prompt must include team names, sport, competition."""
    bundle = _make_edge(is_non_edge=True, coverage_level="empty")
    captured_messages: list[list[dict]] = []

    async def _capturing_create(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        return _make_haiku_resp(_VALID_PREVIEW)

    _apply_standard_monkeypatches(monkeypatch, bundle["pack"])
    create_mock = AsyncMock(side_effect=_capturing_create)
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    await pregen._generate_one(
        bundle["edge"], "claude-sonnet-4-20250514", claude, sweep_type="refresh"
    )

    assert create_mock.called, "Haiku must be called"
    # ACCURACY-01 adds setup + verdict validation passes after the narrative call,
    # so total call count varies. Only the first call (narrative) must have the right content.
    assert len(captured_messages) >= 1
    prompt_content = captured_messages[0][0]["content"]
    prompt_lower = prompt_content.lower()

    # AC-3 fields must be present
    assert "ts galaxy" in prompt_lower or "home:" in prompt_lower
    assert "polokwane" in prompt_lower or "away:" in prompt_lower
    assert "sport:" in prompt_lower
    assert "competition:" in prompt_lower


# (d) Haiku validation still rejects bad output with empty evidence
@pytest.mark.asyncio
async def test_empty_evidence_non_edge_haiku_validation_still_rejects_bad_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX-HAIKU-GATE (d): _validate_preview_polish must still reject bad Haiku output."""
    bundle = _make_edge(is_non_edge=True, coverage_level="empty")
    _apply_standard_monkeypatches(monkeypatch, bundle["pack"])

    # Bad response: missing 3 section headers
    bad_response = "📋 <b>The Setup</b>\nOnly setup section — no edge, risk, verdict."
    create_mock = AsyncMock(return_value=_make_haiku_resp(bad_response))
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    result = await pregen._generate_one(
        bundle["edge"], "claude-sonnet-4-20250514", claude, sweep_type="refresh"
    )

    assert result["success"] is True
    # Validation must reject → falls back to baseline
    assert result["_cache"]["narrative_source"] != "w84"
    assert result["_cache"]["model"] != "haiku"


# (e) Mixed batch: edge+empty (blocked) and non-edge+empty (allowed)
@pytest.mark.asyncio
async def test_mixed_batch_empty_evidence_edge_blocked_non_edge_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX-HAIKU-GATE (e): In a mixed batch, edge+empty is blocked, non-edge+empty is allowed."""
    bundle_edge = _make_edge(is_non_edge=False, coverage_level="empty")
    bundle_non_edge = _make_edge(is_non_edge=True, coverage_level="empty")

    async def _passthrough_refresh(edge: dict) -> dict:
        return edge

    async def _fake_ctx(*args, **kwargs) -> dict:
        return {"data_available": False, "_context_mode": "PARTIAL"}

    import narrative_spec
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(
        narrative_spec,
        "_render_baseline",
        lambda _spec: (
            "📋 <b>The Setup</b>\nX.\n\n"
            "🎯 <b>The Edge</b>\nY.\n\n"
            "⚠️ <b>The Risk</b>\nZ.\n\n"
            "🏆 <b>Verdict</b>\nMonitor home at 2.30 with Hollywoodbets."
        ),
    )
    monkeypatch.setattr(pregen, "_refresh_edge_from_odds_db", _passthrough_refresh)
    monkeypatch.setattr(pregen, "_get_match_context", _fake_ctx)
    monkeypatch.setattr(
        pregen,
        "build_evidence_pack",
        AsyncMock(side_effect=[bundle_edge["pack"], bundle_non_edge["pack"]]),
    )
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda _p: "{}")
    monkeypatch.setattr(pregen, "_build_h2h_injection", lambda *_a, **_k: "")
    monkeypatch.setattr(pregen, "format_evidence_prompt", lambda *_a, **_k: "prompt")
    monkeypatch.setattr(pregen, "sanitize_ai_response", lambda s: s)
    monkeypatch.setattr(pregen, "_suppress_shadow_banned_phrases", lambda s: s)
    monkeypatch.setattr(pregen, "_strip_model_generated_h2h_references", lambda s: s)
    monkeypatch.setattr(pregen, "_strip_model_generated_sharp_references", lambda s: s)
    monkeypatch.setattr(pregen, "_build_sharp_injection", lambda *_a, **_k: "")
    monkeypatch.setattr(
        pregen,
        "verify_shadow_narrative",
        lambda draft, pack, spec: (False, {"rejection_reasons": ["blocked"]}),
    )
    # Bypass ACCURACY-01 validation — it adds 2 extra Haiku calls per w84 narrative
    # and is not under test here (only the narrative-generation gate is tested).
    async def _noop_validate(section_name, section_text, derived_claims, claude, model_id=""):
        return (section_text, True, 1)
    monkeypatch.setattr(pregen, "generate_and_validate", _noop_validate)

    haiku_call_count = 0

    async def _counting_create(**kwargs):
        nonlocal haiku_call_count
        if kwargs.get("model") == pregen.HAIKU_MODEL:
            haiku_call_count += 1
        return _make_haiku_resp(_VALID_PREVIEW)

    create_mock = AsyncMock(side_effect=_counting_create)
    claude = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    # Run both edges
    result_edge = await pregen._generate_one(
        bundle_edge["edge"], "claude-sonnet-4-20250514", claude, sweep_type="refresh"
    )
    result_non_edge = await pregen._generate_one(
        bundle_non_edge["edge"], "claude-sonnet-4-20250514", claude, sweep_type="refresh"
    )

    # Edge + empty: blocked — no Haiku call
    assert result_edge["_cache"]["narrative_source"] != "w84"
    # Non-edge + empty: allowed — Haiku called once, w84 served
    assert haiku_call_count == 1, f"Expected 1 Haiku call, got {haiku_call_count}"
    assert result_non_edge["_cache"]["narrative_source"] == "w84"
