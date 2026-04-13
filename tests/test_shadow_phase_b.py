from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock

import pytest

import bot
import evidence_pack
import scripts.pregenerate_narratives as pregen
from narrative_spec import NarrativeSpec


def _make_spec(**overrides) -> NarrativeSpec:
    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Bournemouth",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="crisis",
        home_coach="Mikel Arteta",
        away_coach="Andoni Iraola",
        home_position=2,
        away_position=12,
        home_points=61,
        away_points=39,
        home_form="WWWDL",
        away_form="LDWLW",
        home_record="W9 D3 L2",
        away_record="W4 D4 L6",
        home_gpg=2.1,
        away_gpg=1.1,
        home_last_result="beating Newcastle 2-1 at home",
        away_last_result="drawing 1-1 away to Brentford",
        h2h_summary="6 meetings: Arsenal 4W 1D 1L",
        bookmaker="Betway",
        odds=2.10,
        ev_pct=5.2,
        fair_prob_pct=52.0,
        composite_score=58.0,
        support_level=2,
        contradicting_signals=0,
        evidence_class="lean",
        tone_band="moderate",
        risk_factors=["Standard match variance applies."],
        risk_severity="moderate",
        verdict_action="lean",
        verdict_sizing="small stake",
        outcome="home",
        outcome_label="the Arsenal win",
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def _make_pack(*, with_news: bool = True, low_richness: bool = False) -> evidence_pack.EvidencePack:
    return evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-21",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        richness_score="low" if low_richness else "high",
        sources_available=2 if low_richness else 7,
        sa_odds=evidence_pack.SAOddsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "odds_latest", 480.0 if low_richness else 40.0),
            odds_by_bookmaker={"Betway": {"home": 2.10, "draw": 3.30, "away": 3.60}},
            best_odds={"home": 2.10},
            best_bookmaker={"home": "Betway"},
            bookmaker_count=1,
        ),
        edge_state=evidence_pack.EdgeStateBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "edge_v2", 0.0),
            composite_score=58.0,
            edge_tier="silver",
            edge_pct=5.2,
            outcome="home",
            fair_probability=0.52,
            confirming_signals=2,
            contradicting_signals=0,
            signals={"movement": {"direction": "neutral"}},
            price_edge_score=0.72,
            market_agreement_score=0.55,
            movement_score=0.2,
            tipster_score=0.1,
            lineup_injury_score=0.2,
            form_h2h_score=0.4,
            sharp_available=True,
        ),
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={
                "name": "Arsenal",
                "position": 2,
                "points": 61,
                "form": "WWWDL",
                "record": "W9 D3 L2",
                "goals_per_game": 2.1,
                "coach": "Mikel Arteta",
                "last_result": "beating Newcastle 2-1 at home",
            },
            away_team={
                "name": "Bournemouth",
                "position": 12,
                "points": 39,
                "form": "LDWLW",
                "record": "W4 D4 L6",
                "goals_per_game": 1.1,
                "coach": "Andoni Iraola",
                "last_result": "drawing 1-1 away to Brentford",
            },
            h2h=[{"winner": "Arsenal"}],
        ),
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_results", 0.0),
            matches=[
                {"date": "2026-02-01", "home": "Arsenal", "away": "Bournemouth", "score": "2-1", "winner": "Arsenal"},
                {"date": "2025-11-10", "home": "Bournemouth", "away": "Arsenal", "score": "1-1", "winner": "draw"},
            ],
            summary={"home_wins": 1, "draws": 1, "away_wins": 0, "total": 2},
            summary_text="2 meetings: Arsenal 1W 1D 0L",
        ),
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(with_news, "2026-03-20T00:00:00+00:00", "news_articles", 15.0),
            articles=[{"title": "Arsenal training update ahead of Bournemouth clash", "source": "BBC"}] if with_news else [],
            article_count=1 if with_news else 0,
        ),
        sharp_lines=evidence_pack.SharpLinesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "sharp_odds", 10.0),
            pinnacle_price={"home": 2.02},
            betfair_price={"home": 2.04},
            benchmarks=[{"bookmaker": "Pinnacle", "selection": "home", "back_price": 2.02}],
            spread_pct=1.5,
            liquidity_score="medium",
        ),
        settlement_stats=evidence_pack.SettlementBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "edge_results", 0.0),
            stats_7d={"hit_rate": 0.46, "total": 13},
            stats_30d={"hit_rate": 0.52, "total": 51},
            tier_hit_rates={"silver": 0.49},
            streak={"label": "2 losses"},
            total_settled=64,
        ),
        movements=evidence_pack.MovementsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "line_movements", 0.0),
            movements=[{"bookmaker": "Betway", "selection": "home", "old_price": 2.15, "new_price": 2.10}],
            net_direction="stable",
            movement_count=1,
            velocity=0.1,
            bookmakers_moving=1,
        ),
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "injuries", 0.0),
            home_injuries=[{"player_name": "Bukayo Saka", "injury_status": "Questionable"}],
            away_injuries=[{"player_name": "Justin Kluivert", "injury_status": "Questionable"}],
            total_injury_count=2,
        ),
    )


def test_ensure_shadow_narratives_table_creates_table(tmp_path) -> None:
    db_path = str(tmp_path / "shadow.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    try:
        bot._ensure_shadow_narratives_table()
        import sqlite3

        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(shadow_narratives)").fetchall()}
        conn.close()
        assert {"match_key", "prompt_text", "verification_passed", "scored_quality", "scorer_notes"}.issubset(cols)
    finally:
        bot._NARRATIVE_DB_PATH = original


def test_format_evidence_prompt_handles_missing_sources() -> None:
    prompt = evidence_pack.format_evidence_prompt(_make_pack(with_news=False, low_richness=True), _make_spec())

    assert "[EVIDENCE NOT AVAILABLE]" in prompt
    assert "NEWS HEADLINES: No relevant team headlines." in prompt
    assert "No verified H2H exists. Do NOT mention head-to-head" not in prompt
    assert "The phrase 'value play' is banned. Do NOT use it anywhere." in prompt
    assert "Do NOT call the bet a 'value play'." in prompt
    assert "TONE BAND: moderate" in prompt
    assert "VERDICT CONSTRAINT:" in prompt
    assert "You must NOT use general sports knowledge" in prompt


def test_format_evidence_prompt_instructs_h2h_omission_when_missing() -> None:
    pack = _make_pack()
    pack.h2h = evidence_pack.H2HBlock(
        provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "h2h", 0.0, error="No verified H2H rows."),
    )

    prompt = evidence_pack.format_evidence_prompt(pack, _make_spec())

    assert "[HEAD TO HEAD]" in prompt
    assert "No verified H2H is available for this match." in prompt
    assert "No verified H2H exists. Do NOT mention head-to-head" in prompt


def test_format_evidence_prompt_includes_verified_h2h_section() -> None:
    prompt = evidence_pack.format_evidence_prompt(_make_pack(), _make_spec())

    assert "[HEAD TO HEAD]" in prompt
    assert "Verified H2H context is injected after your output." in prompt
    assert "Do NOT invent, paraphrase, summarize, or rewrite head-to-head yourself." in prompt
    assert "Summary: 2 meetings: Arsenal 1W 1D 0L" not in prompt
    assert "Recent verified meetings:" not in prompt
    assert "H2H context is injected separately. Do NOT generate head-to-head prose yourself." in prompt


def test_format_evidence_prompt_uses_sharp_placeholder_block() -> None:
    prompt = evidence_pack.format_evidence_prompt(_make_pack(), _make_spec())

    assert "[SHARP BENCHMARK LINES]" in prompt
    assert "Sharp pricing context is injected after your output." in prompt
    assert "Do NOT mention Pinnacle, Betfair, Matchbook, Smarkets, or any sharp bookmaker by name." in prompt
    assert "Do NOT cite any sharp price directly." in prompt
    assert "Pinnacle home 2.02" not in prompt
    assert "Betfair home 2.04" not in prompt
    assert "Do NOT mention sharp bookmakers or sharp prices. Any sharp context is injected separately." in prompt
    assert "Never use banned filler such as 'thin support', 'pure pricing call', or 'supporting evidence is thin'." in prompt
    assert "Thin support. Acknowledge gaps and keep conviction low." not in prompt


def test_format_evidence_prompt_uses_same_sharp_placeholder_when_no_safe_snippet_exists() -> None:
    pack = _make_pack()
    pack.sharp_lines = evidence_pack.SharpLinesBlock(
        provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "sharp_odds", 10.0),
        pinnacle_price={},
        betfair_price={},
        benchmarks=[],
        spread_pct=1.5,
        liquidity_score="medium",
    )

    prompt = evidence_pack.format_evidence_prompt(pack, _make_spec())

    assert "Sharp pricing context is injected after your output." in prompt
    assert "Pinnacle home 2.02" not in prompt


def test_verify_shadow_narrative_rejects_banned_and_untraceable_h2h() -> None:
    pack = _make_pack()
    spec = _make_spec(h2h_summary="")
    draft = (
        "📋 <b>The Setup</b>\n"
        "Arsenal sit 2nd on 61 points with form WWWDL. Head to head: 9 meetings: Arsenal 8W 1D 0L.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway have Arsenal at 2.10 and it is a value play.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Bukayo Saka is a doubt.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Arsenal at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is False
    assert report["hard_checks"]["banned_phrases_absent"]["passed"] is False
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is False


def test_verify_shadow_narrative_flags_support_language_boundary() -> None:
    pack = _make_pack(low_richness=True)
    spec = _make_spec(evidence_class="lean", support_level=1)
    draft = (
        "📋 <b>The Setup</b>\n"
        "Arsenal sit 2nd on 61 points with form WWWDL, while Bournemouth are 12th on 39 points, but verified context is thin.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway are 2.10 here and all indicators fully support Arsenal.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Limited evidence depth is the main risk because the price is stale.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Arsenal at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["soft_checks"]["support_language_boundary"]["flagged"] is True



def test_load_shadow_pregen_edges_uses_live_edge_results_source(monkeypatch) -> None:
    tip = {
        "match_id": "arsenal_vs_bournemouth_2026-03-21",
        "event_id": "arsenal_vs_bournemouth_2026-03-21",
        "sport_key": "soccer",
        "home_team": "Arsenal",
        "away_team": "Bournemouth",
        "outcome": "Arsenal",
        "odds": 2.10,
        "bookmaker": "Betway",
        "ev": 5.2,
        "prob": 52.0,
        "edge_rating": "silver",
        "display_tier": "silver",
        "edge_score": 58.0,
        "league": "Premier League",
        "league_key": "epl",
        "sharp_source": "edge_results",
        "edge_v2": None,
    }
    seen = {}

    def fake_load(limit: int = 10):
        seen["limit"] = limit
        return [tip]

    monkeypatch.setattr(bot, "_load_tips_from_edge_results", fake_load)

    edges = pregen._load_shadow_pregen_edges(limit=100)

    assert seen["limit"] == 100
    assert len(edges) == 1
    edge = edges[0]
    assert edge["match_key"] == "arsenal_vs_bournemouth_2026-03-21"
    assert edge["recommended_outcome"] == "home"
    assert edge["outcome"] == "home"
    assert edge["best_bookmaker"] == "Betway"
    assert edge["best_odds"] == 2.10
    assert edge["edge_pct"] == 5.2
    assert edge["fair_probability"] == 0.52
    assert edge["composite_score"] == 58.0
    assert edge["confirming_signals"] == 2
    assert edge["sport"] == "soccer"
    assert edge["league"] == "epl"


@pytest.mark.asyncio
async def test_main_writes_shadow_rows_from_live_edge_source(monkeypatch, tmp_path) -> None:
    original_db_path = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = str(tmp_path / "narratives.db")
    bot._ensure_narrative_cache_table()
    bot._ensure_shadow_narratives_table()

    live_tips = [
        {
            "match_id": "arsenal_vs_bournemouth_2026-04-11",
            "event_id": "arsenal_vs_bournemouth_2026-04-11",
            "sport_key": "soccer",
            "home_team": "Arsenal",
            "away_team": "Bournemouth",
            "outcome": "Arsenal",
            "odds": 2.10,
            "bookmaker": "Betway",
            "ev": 5.2,
            "prob": 52.0,
            "edge_rating": "silver",
            "display_tier": "silver",
            "edge_score": 58.0,
            "league": "Premier League",
            "league_key": "epl",
            "sharp_source": "edge_results",
            "edge_v2": None,
        },
        {
            "match_id": "everton_vs_chelsea_2026-03-21",
            "event_id": "everton_vs_chelsea_2026-03-21",
            "sport_key": "soccer",
            "home_team": "Everton",
            "away_team": "Chelsea",
            "outcome": "Chelsea",
            "odds": 2.35,
            "bookmaker": "Hollywoodbets",
            "ev": 4.1,
            "prob": 48.0,
            "edge_rating": "gold",
            "display_tier": "gold",
            "edge_score": 61.0,
            "league": "Premier League",
            "league_key": "epl",
            "sharp_source": "edge_results",
            "edge_v2": None,
        },
        {
            "match_id": "bournemouth_vs_manchester_united_2026-03-20",
            "event_id": "bournemouth_vs_manchester_united_2026-03-20",
            "sport_key": "soccer",
            "home_team": "Bournemouth",
            "away_team": "Manchester United",
            "outcome": "Draw",
            "odds": 3.40,
            "bookmaker": "Supabets",
            "ev": 3.3,
            "prob": 31.0,
            "edge_rating": "silver",
            "display_tier": "silver",
            "edge_score": 55.0,
            "league": "Premier League",
            "league_key": "epl",
            "sharp_source": "edge_results",
            "edge_v2": None,
        },
    ]

    class FakeClaude:
        pass

    async def fake_cached(match_key: str):
        return None

    async def fake_store_cache(*args, **kwargs):
        return None

    async def fake_verify_fill(*args, **kwargs):
        return None

    def fake_balance(verdicts):
        return None

    async def fake_generate_one(edge, model_id, claude, sweep_type="full"):
        pack = _make_pack()
        pack.match_key = edge["match_key"]
        spec = _make_spec(
            home_name=edge["home_team"],
            away_name=edge["away_team"],
            bookmaker=edge["best_bookmaker"],
            odds=edge["best_odds"],
            ev_pct=edge["edge_pct"],
            outcome=edge["outcome"],
            outcome_label=edge["recommended_outcome"],
        )
        return {
            "match_key": edge["match_key"],
            "success": True,
            "model": "sonnet",
            "duration": 0.01,
            "narrative": "🏆 Verdict\nLean the price.",
            "_cache": {
                "match_id": edge["match_key"],
                "html": "<b>shadow test</b>",
                "tips": [],
                "edge_tier": edge["tier"],
                "model": "sonnet",
                "evidence_json": '{"pack_version":1}',
                "_shadow": {
                    "match_key": edge["match_key"],
                    "pack": pack,
                    "spec": spec,
                    "evidence_json": '{"pack_version":1}',
                    "w82_baseline": "baseline text",
                    "w82_polished": "polished text",
                    "richness_score": "high",
                },
            },
        }

    monkeypatch.setattr(bot, "_load_tips_from_edge_results", lambda limit=10: live_tips[:limit])
    monkeypatch.setattr(pregen.anthropic, "AsyncAnthropic", lambda api_key=None: FakeClaude())
    monkeypatch.setattr(pregen, "_wait_for_scraper_writer_window", AsyncMock(return_value=True))
    monkeypatch.setattr(pregen, "_validate_pregen_runtime_schema", lambda db_path=None: None)
    monkeypatch.setattr(pregen, "_get_cached_narrative", fake_cached)
    monkeypatch.setattr(pregen, "_store_narrative_cache", fake_store_cache)
    monkeypatch.setattr(pregen, "_verify_and_fill_cache", fake_verify_fill)
    monkeypatch.setattr(pregen, "_check_verdict_balance", fake_balance)
    monkeypatch.setattr(pregen, "_generate_one", fake_generate_one)

    try:
        await pregen.main("refresh")
    finally:
        bot._NARRATIVE_DB_PATH = original_db_path
    # W84-CONFIRM-1: main completes without shadow tasks (no longer scheduled)
