
import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

import os
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))
sys.path.insert(0, str(_REPO_ROOT.parent / "scrapers"))
os.chdir(str(_REPO_ROOT))

import evidence_pack
from narrative_spec import NarrativeSpec


def _make_spec(**overrides) -> NarrativeSpec:
    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Bournemouth",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="crisis",
        home_coach="",
        away_coach="",
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
        bookmaker="Hollywoodbets",
        odds=2.15,
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


def _make_pack(**overrides) -> evidence_pack.EvidencePack:
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-21",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        richness_score="high",
        sources_available=7,
        sa_odds=evidence_pack.SAOddsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "odds_latest", 20.0),
            odds_by_bookmaker={
                "Betway": {"home": 2.10, "draw": 3.30, "away": 3.60},
                "GBets": {"home": 2.15, "draw": 3.35, "away": 3.55},
            },
            best_odds={"home": 2.15},
            best_bookmaker={"home": "GBets"},
            bookmaker_count=2,
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
                "coach": "Mikel Arteta",
                "top_scorers": [{"name": "Erling Haaland"}],
                "key_players": [{"name": "Bukayo Saka"}],
            },
            away_team={
                "name": "Bournemouth",
                "position": 12,
                "points": 39,
                "form": "LDWLW",
                "coach": "Andoni Iraola",
                "top_scorers": [],
                "key_players": [{"name": "Justin Kluivert"}],
            },
            h2h=[{"winner": "Arsenal"}],
        ),
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_results", 0.0),
            matches=[
                {"date": "2026-02-01", "home": "Arsenal", "away": "Bournemouth", "score": "2-1", "winner": "Arsenal"},
                {"date": "2025-11-10", "home": "Bournemouth", "away": "Arsenal", "score": "1-1", "winner": "draw"},
                {"date": "2025-08-18", "home": "Arsenal", "away": "Bournemouth", "score": "3-0", "winner": "Arsenal"},
                {"date": "2025-04-02", "home": "Bournemouth", "away": "Arsenal", "score": "1-2", "winner": "Arsenal"},
                {"date": "2024-12-14", "home": "Arsenal", "away": "Bournemouth", "score": "0-1", "winner": "Bournemouth"},
                {"date": "2024-08-11", "home": "Arsenal", "away": "Bournemouth", "score": "2-0", "winner": "Arsenal"},
            ],
            summary={"home_wins": 4, "draws": 1, "away_wins": 1, "total": 6},
            summary_text="6 meetings: Arsenal 4W 1D 1L",
        ),
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "news_articles", 15.0),
            articles=[{"title": "Arsenal training update", "source": "BBC"}],
            article_count=1,
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
            api_football=[{"player_name": "Bukayo Saka", "injury_status": "Questionable"}],
            news_extracted=[{"player_name": "Justin Kluivert", "injury_status": "Questionable"}],
            home_injuries=[],
            away_injuries=[],
            total_injury_count=2,
        ),
    )
    for key, value in overrides.items():
        setattr(pack, key, value)
    return pack


def _draft(setup: str, edge: str, risk: str = "Standard variance applies.", verdict: str = "Lean Arsenal at Betway 2.10.") -> str:
    if "Bournemouth" not in setup:
        setup = f"Arsenal host Bournemouth here. {setup}"
    return (
        f"📋 <b>The Setup</b>\n{setup}\n\n"
        f"🎯 <b>The Edge</b>\n{edge}\n\n"
        f"⚠️ <b>The Risk</b>\n{risk}\n\n"
        f"🏆 <b>Verdict</b>\n{verdict}"
    )


def test_h3_accepts_evidence_pack_bookmaker_pair_not_spec_pair() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the price still looks playable.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["bookmaker_odds_preserved"]["passed"] is True


def test_h9_accepts_evidence_pack_coach_with_spec_fallback_empty() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and coach Arteta still has them well organised.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec(home_coach="", away_coach=""))

    assert passed is True
    assert report["hard_checks"]["coach_names_match"]["passed"] is True


def test_h9_accepts_unique_coach_first_name_short_form() -> None:
    pack = _make_pack(
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={
                "name": "Arsenal",
                "position": 2,
                "points": 61,
                "form": "WWWDL",
                "coach": "Pep Guardiola",
                "top_scorers": [{"name": "Erling Haaland"}],
                "key_players": [{"name": "Bukayo Saka"}],
            },
            away_team={
                "name": "Bournemouth",
                "position": 12,
                "points": 39,
                "form": "LDWLW",
                "coach": "Andoni Iraola",
                "top_scorers": [],
                "key_players": [{"name": "Justin Kluivert"}],
            },
            h2h=[{"winner": "Arsenal"}],
        ),
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and coach Pep still has them well organised.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(
        draft,
        pack,
        _make_spec(home_coach="Pep Guardiola", away_coach="Andoni Iraola"),
    )

    assert passed is True
    assert report["hard_checks"]["coach_names_match"]["passed"] is True


def test_h9_rejects_ambiguous_coach_first_name_short_form() -> None:
    pack = _make_pack(
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={
                "name": "Arsenal",
                "position": 2,
                "points": 61,
                "form": "WWWDL",
                "coach": "Pep Guardiola",
                "top_scorers": [{"name": "Erling Haaland"}],
                "key_players": [{"name": "Bukayo Saka"}],
            },
            away_team={
                "name": "Bournemouth",
                "position": 12,
                "points": 39,
                "form": "LDWLW",
                "coach": "Pep Clotet",
                "top_scorers": [],
                "key_players": [{"name": "Justin Kluivert"}],
            },
            h2h=[{"winner": "Arsenal"}],
        ),
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and coach Pep still has them well organised.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec(home_coach="", away_coach=""))

    assert passed is False
    assert report["hard_checks"]["coach_names_match"]["passed"] is False


def test_h10_accepts_evidence_pack_injury_name_from_injury_block() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
        risk="Bukayo Saka is a doubt, so there is still some lineup risk here.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["injury_names_match"]["passed"] is True


def test_h10_accepts_unique_surname_only_injury_reference_from_abbreviated_evidence() -> None:
    pack = _make_pack(
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "injuries", 0.0),
            api_football=[{"player_name": "M. Salah", "injury_status": "Questionable"}],
            news_extracted=[{"player_name": "A. Du Preez", "injury_status": "Questionable"}],
            home_injuries=[],
            away_injuries=[],
            total_injury_count=2,
        ),
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
        risk="Salah is a doubt, and Du Preez is also a doubt, so lineup certainty is shaky.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is True
    assert report["hard_checks"]["injury_names_match"]["passed"] is True


def test_h10_rejects_ambiguous_surname_only_injury_reference() -> None:
    pack = _make_pack(
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "injuries", 0.0),
            api_football=[
                {"player_name": "M. Salah", "injury_status": "Questionable"},
                {"player_name": "A. Salah", "injury_status": "Questionable"},
            ],
            home_injuries=[],
            away_injuries=[],
            total_injury_count=2,
        ),
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
        risk="Salah is a doubt, so lineup certainty is shaky.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is False
    assert report["hard_checks"]["injury_names_match"]["passed"] is False


def test_h10_ignores_team_nickname_and_team_name_in_injury_context() -> None:
    pack = _make_pack(
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={
                "name": "Arsenal",
                "position": 2,
                "points": 61,
                "form": "WWWDL",
                "coach": "Mikel Arteta",
            },
            away_team={
                "name": "Fulham",
                "position": 12,
                "points": 39,
                "form": "LDWLW",
                "coach": "Marco Silva",
            },
        ),
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "injuries", 0.0),
            api_football=[{"player_name": "Mikel Merino", "injury_status": "Questionable"}],
            news_extracted=[{"player_name": "Tom Cairney", "injury_status": "Questionable"}],
            home_injuries=[],
            away_injuries=[],
            total_injury_count=2,
        ),
    )
    spec = _make_spec(away_name="Fulham")
    draft = (
        "📋 <b>The Setup</b>\nArsenal host Fulham here.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Arsenal at 2.10 and the edge is still there.\n\n"
        "⚠️ <b>The Risk</b>\nThe Gunners are missing Merino, while Fulham are without Cairney.\n\n"
        "🏆 <b>Verdict</b>\nLean Arsenal at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["injury_names_match"]["passed"] is True


def test_h10_accepts_unique_single_name_injury_reference() -> None:
    pack = _make_pack(
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "injuries", 0.0),
            api_football=[{"player_name": "Alisson Becker", "injury_status": "Questionable"}],
            home_injuries=[],
            away_injuries=[],
            total_injury_count=1,
        ),
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
        risk="Alisson is carrying a knock, so lineup certainty is shaky.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is True
    assert report["hard_checks"]["injury_names_match"]["passed"] is True


def test_h10_ignores_hammers_nickname_in_injury_context() -> None:
    spec = _make_spec(
        home_name="West Ham United",
        away_name="Wolverhampton",
        home_position=9,
        away_position=11,
        home_points=44,
        away_points=41,
        home_form="WWDLL",
        away_form="LDWLW",
        outcome_label="the West Ham win",
    )
    pack = _make_pack(
        match_key="west_ham_vs_wolves_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "West Ham United", "position": 9, "points": 44, "form": "WWDLL", "coach": "Julen Lopetegui"},
            away_team={"name": "Wolverhampton", "position": 11, "points": 41, "form": "LDWLW", "coach": "Gary O'Neil"},
            h2h=[],
        ),
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "injuries", 0.0),
            api_football=[{"player_name": "Mohammed Kudus", "injury_status": "Questionable"}],
            home_injuries=[],
            away_injuries=[],
            total_injury_count=1,
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\nWest Ham host Wolves here.\n\n"
        "🎯 <b>The Edge</b>\nBetway have West Ham at 2.10 and the edge is still there.\n\n"
        "⚠️ <b>The Risk</b>\nThe Hammers are missing Kudus, so the lineup risk is real.\n\n"
        "🏆 <b>Verdict</b>\nLean West Ham at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["injury_names_match"]["passed"] is True


def test_h10_ignores_team_name_in_injury_context_for_magesi() -> None:
    spec = _make_spec(
        home_name="Kaizer Chiefs",
        away_name="Magesi",
        home_position=6,
        away_position=14,
        home_points=35,
        away_points=22,
        home_form="WDLWW",
        away_form="LDDLL",
        outcome_label="the Kaizer Chiefs win",
    )
    pack = _make_pack(
        match_key="kaizer_chiefs_vs_magesi_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Kaizer Chiefs", "position": 6, "points": 35, "form": "WDLWW", "coach": "Nasreddine Nabi"},
            away_team={"name": "Magesi", "position": 14, "points": 22, "form": "LDDLL", "coach": "Owen da Gama"},
            h2h=[],
        ),
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "injuries", 0.0),
            api_football=[{"player_name": "Elvis Chipezeze", "injury_status": "Questionable"}],
            home_injuries=[],
            away_injuries=[],
            total_injury_count=1,
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\nChiefs host Magesi here.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Chiefs at 2.10 and the edge is still there.\n\n"
        "⚠️ <b>The Risk</b>\nMagesi are missing Chipezeze, so the away depth is thin.\n\n"
        "🏆 <b>Verdict</b>\nLean Chiefs at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["injury_names_match"]["passed"] is True


def test_h12_accepts_top_scorer_name_from_evidence_pack() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and Erling Haaland is one of the names in the verified context.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_h2_accepts_section_variants_after_sanitizer() -> None:
    draft = (
        "📋 **Setup**\nArsenal host Bournemouth here and sit 2nd on 61 points with form WWWDL.\n\n"
        "🎯 **Edge**\nBetway have Arsenal at 2.10 and the edge is still there.\n\n"
        "⚠️ **Risk**\nStandard variance applies.\n\n"
        "🏆 **The Verdict**\nLean Arsenal at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["section_structure"]["passed"] is True


def test_h11_rejects_sharp_price_when_sharp_data_unavailable() -> None:
    pack = _make_pack(
        sharp_lines=evidence_pack.SharpLinesBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "sharp_odds", 999.0)
        )
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Pinnacle are 2.02 on Arsenal and that sharp price backs the angle.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is False
    assert report["hard_checks"]["sharp_prices_traceable"]["passed"] is False


def test_h11_accepts_approximate_sharp_price_without_treating_percentages_as_odds() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Pinnacle are around 2.00 here, which is close to a 49.5% sharp view on Arsenal.",
        verdict="Lean Arsenal at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["sharp_prices_traceable"]["passed"] is True
    assert report["hard_checks"]["ev_probability_values"]["passed"] is True


def test_h11_rejects_deterministic_injected_sharp_sentence() -> None:
    # R7-BUILD-02: "Sharp market pricing" is now in BANNED_NARRATIVE_PHRASES —
    # verify_shadow_narrative must reject narratives containing this phrase.
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the edge is still there. Sharp market pricing has home at 2.02.",
        verdict="Lean Arsenal at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is False


def test_h11_accepts_rounded_sharp_price_inside_narrow_tolerance() -> None:
    pack = _make_pack(
        sharp_lines=evidence_pack.SharpLinesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "sharp_odds", 10.0),
            pinnacle_price={"home": 3.18},
            betfair_price={"home": 3.17},
            benchmarks=[{"bookmaker": "Pinnacle", "selection": "home", "back_price": 3.18}],
            spread_pct=1.5,
            liquidity_score="medium",
        )
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Pinnacle are around 3.23 here and that sharp reference still supports the angle.",
        verdict="Lean Arsenal at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is True
    assert report["hard_checks"]["sharp_prices_traceable"]["passed"] is True


def test_h11_rejects_sharp_price_outside_narrow_tolerance() -> None:
    pack = _make_pack(
        sharp_lines=evidence_pack.SharpLinesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "sharp_odds", 10.0),
            pinnacle_price={"home": 3.18},
            betfair_price={"home": 3.17},
            benchmarks=[{"bookmaker": "Pinnacle", "selection": "home", "back_price": 3.18}],
            spread_pct=1.5,
            liquidity_score="medium",
        )
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Pinnacle are around 3.24 here and that sharp reference still supports the angle.",
        verdict="Lean Arsenal at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is False
    assert report["hard_checks"]["sharp_prices_traceable"]["passed"] is False


def test_h13_accepts_market_implied_probability_from_sa_odds() -> None:
    pack = _make_pack(
        sa_odds=evidence_pack.SAOddsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "odds_latest", 20.0),
            odds_by_bookmaker={"Betway": {"home": 1.48, "draw": 4.20, "away": 6.20}},
            best_odds={"home": 1.48},
            best_bookmaker={"home": "Betway"},
            bookmaker_count=1,
        ),
        edge_state=evidence_pack.EdgeStateBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "edge_v2", 0.0),
            composite_score=58.0,
            edge_tier="silver",
            edge_pct=3.8,
            outcome="home",
            fair_probability=0.62,
            confirming_signals=2,
            contradicting_signals=0,
            signals={},
        ),
    )
    spec = _make_spec(bookmaker="Betway", odds=1.48, ev_pct=3.8, fair_prob_pct=62.0)
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 1.48, which implies roughly a 67.6% chance before the margin is stripped out.",
        verdict="Lean Arsenal at Betway 1.48.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["ev_probability_values"]["passed"] is True


def test_h13_rejects_untraced_probability() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10, and this reads like a 70% chance which is too big for the market.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is False
    assert report["hard_checks"]["ev_probability_values"]["passed"] is False


def test_h14_accepts_pack_edge_state_percentages_when_spec_values_are_blank() -> None:
    spec = _make_spec(ev_pct=0.0, fair_prob_pct=0.0)
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10, with about a 5% EV edge and roughly a 52% fair chance in the pack.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), spec)

    assert passed is True
    assert report["hard_checks"]["ev_probability_values"]["passed"] is True


def test_h14_accepts_valid_ev_value_when_nearby_record_language_exists() -> None:
    spec = _make_spec(ev_pct=5.2, fair_prob_pct=52.0)
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10, and the edge analysis still shows a 5.2% edge despite Arsenal's patchy recent record.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), spec)

    assert passed is True
    assert report["hard_checks"]["ev_probability_values"]["passed"] is True


def test_h15_accepts_verified_h2h_summary_and_score_reference() -> None:
    draft = _draft(
        "Arsenal host Bournemouth here. Head to head: 6 meetings: Arsenal 4W 1D 1L, and the last meeting finished 2-1.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is True


def test_h15_accepts_deterministic_injected_h2h_sentence() -> None:
    draft = _draft(
        "Arsenal host Bournemouth here. Head to head: 6 meetings: Arsenal 4W 1D 1L, and the last meeting finished 2-1.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is True


def test_h15_accepts_explicit_h2h_absence_when_no_verified_h2h_exists() -> None:
    pack = _make_pack(
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "h2h", 0.0, error="No verified H2H rows."),
        ),
    )
    draft = _draft(
        "Arsenal host Bournemouth here, but there is no head-to-head history in the verified pack for this angle.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is True
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is True


def test_h15_accepts_borderline_h2h_absence_wording_when_no_verified_h2h_exists() -> None:
    pack = _make_pack(
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "h2h", 0.0, error="No verified H2H rows."),
        ),
    )
    draft = _draft(
        "Arsenal host Bournemouth here, but we are flying blind on recent meetings without verified H2H history.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is True
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is True


def test_h15_accepts_no_verified_h2h_block_available_non_claim() -> None:
    pack = _make_pack(
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "h2h", 0.0, error="No verified H2H rows."),
        ),
    )
    draft = _draft(
        "Arsenal host Bournemouth here, but there is no verified H2H block available for this fixture.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is True
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is True


def test_h15_graceful_pass_h2h_claim_when_no_verified_h2h_exists() -> None:
    """R13-BUILD-01 Fix 4: Missing H2H evidence → graceful pass, not rejection."""
    pack = _make_pack(
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "h2h", 0.0, error="No verified H2H rows."),
        ),
    )
    draft = _draft(
        "Arsenal host Bournemouth here, and the last meeting finished 2-1.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    # R13-BUILD-01 Fix 4: h2h_claims_traceable now passes when no H2H evidence exists
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is True
    assert "graceful" in report["hard_checks"]["h2h_claims_traceable"]["detail"].lower()


def test_h15_rejects_freeform_h2h_expansion_even_when_verified_h2h_exists() -> None:
    draft = _draft(
        "Arsenal host Bournemouth here. Head to head: Arsenal have dominated recent meetings.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is False
    assert report["hard_checks"]["h2h_claims_traceable"]["passed"] is False


def test_team_names_present_accepts_clean_team_shorthand() -> None:
    spec = _make_spec(
        home_name="Crystal Palace",
        away_name="West Ham United",
        home_position=12,
        away_position=9,
        home_points=39,
        away_points=44,
        home_form="LDWLW",
        away_form="WWDLL",
    )
    pack = _make_pack(
        match_key="crystal_palace_vs_west_ham_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Crystal Palace", "position": 12, "points": 39, "form": "LDWLW", "coach": "Oliver Glasner"},
            away_team={"name": "West Ham United", "position": 9, "points": 44, "form": "WWDLL", "coach": "Julen Lopetegui"},
            h2h=[{"winner": "West Ham United"}],
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\n"
        "Palace host West Ham here, with Palace sat 12th on 39 points and form LDWLW.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway have Palace at 2.10 and the price still looks playable.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Standard variance applies.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Palace at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["team_names_present"]["passed"] is True


def test_team_names_present_accepts_psg_and_spurs_aliases() -> None:
    spec = _make_spec(
        home_name="Paris Saint-Germain",
        away_name="Tottenham",
        competition="Champions League",
        home_position=1,
        away_position=5,
        home_points=68,
        away_points=49,
        home_form="WWWWW",
        away_form="WWLDW",
        bookmaker="Betway",
        odds=2.10,
    )
    pack = _make_pack(
        match_key="psg_vs_tottenham_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Paris Saint-Germain", "position": 1, "points": 68, "form": "WWWWW", "coach": "Luis Enrique"},
            away_team={"name": "Tottenham", "position": 5, "points": 49, "form": "WWLDW", "coach": "Ange Postecoglou"},
            h2h=[],
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\n"
        "PSG host Spurs here, with PSG sat 1st on 68 points and form WWWWW.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway have PSG at 2.10 and the price still looks playable.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Standard variance applies.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean PSG at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["team_names_present"]["passed"] is True


def test_team_names_present_accepts_brighton_short_alias() -> None:
    spec = _make_spec(
        home_name="Brighton and Hove Albion",
        away_name="Liverpool",
        home_position=10,
        away_position=3,
        home_points=42,
        away_points=58,
        home_form="WDLWW",
        away_form="WWDLW",
    )
    pack = _make_pack(
        match_key="brighton_vs_liverpool_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Brighton and Hove Albion", "position": 10, "points": 42, "form": "WDLWW", "coach": "Fabian Hurzeler"},
            away_team={"name": "Liverpool", "position": 3, "points": 58, "form": "WWDLW", "coach": "Arne Slot"},
            h2h=[],
        ),
    )
    draft = _draft(
        "Brighton host Liverpool here, with Brighton sat 10th on 42 points and form WDLWW.",
        "Betway have Brighton at 2.10 and the price still looks playable.",
        verdict="Lean Brighton at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["team_names_present"]["passed"] is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_team_names_present_accepts_glasgow_short_alias() -> None:
    spec = _make_spec(
        home_name="Glasgow Warriors",
        away_name="Leinster",
        competition="URC",
        sport="rugby",
        home_position=1,
        away_position=2,
        home_points=44,
        away_points=41,
        home_form="WWWWW",
        away_form="WWLWW",
    )
    pack = _make_pack(
        match_key="glasgow_vs_leinster_2026-03-21",
        sport="rugby",
        league="urc",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Glasgow Warriors", "position": 1, "points": 44, "form": "WWWWW", "coach": "Franco Smith"},
            away_team={"name": "Leinster", "position": 2, "points": 41, "form": "WWLWW", "coach": "Leo Cullen"},
            h2h=[],
        ),
    )
    draft = _draft(
        "Glasgow host Leinster here, with Glasgow sat 1st on 44 points and form WWWWW.",
        "Betway have Glasgow at 2.10 and the price still looks playable.",
        verdict="Lean Glasgow at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["team_names_present"]["passed"] is True


def test_team_names_present_accepts_paris_and_saint_germain_aliases() -> None:
    spec = _make_spec(
        home_name="Paris Saint-Germain",
        away_name="Liverpool",
        competition="Champions League",
        home_position=1,
        away_position=3,
        home_points=68,
        away_points=61,
        home_form="WWWWW",
        away_form="WWDLW",
    )
    pack = _make_pack(
        match_key="psg_vs_liverpool_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Paris Saint-Germain", "position": 1, "points": 68, "form": "WWWWW", "coach": "Luis Enrique"},
            away_team={"name": "Liverpool", "position": 3, "points": 61, "form": "WWDLW", "coach": "Arne Slot"},
            h2h=[],
        ),
    )
    draft = _draft(
        "Paris host Liverpool here, with Saint-Germain sat 1st on 68 points and form WWWWW.",
        "Betway have Paris at 2.10 and the price still looks playable.",
        verdict="Lean Paris at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["team_names_present"]["passed"] is True


def test_team_names_present_accepts_man_city_and_man_united_aliases() -> None:
    spec = _make_spec(
        home_name="Manchester City",
        away_name="Manchester United",
        home_position=2,
        away_position=6,
        home_points=63,
        away_points=48,
        home_form="WWWDW",
        away_form="WDLWW",
        bookmaker="Betway",
        odds=2.10,
    )
    pack = _make_pack(
        match_key="man_city_vs_man_united_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Manchester City", "position": 2, "points": 63, "form": "WWWDW", "coach": "Pep Guardiola"},
            away_team={"name": "Manchester United", "position": 6, "points": 48, "form": "WDLWW", "coach": "Ruben Amorim"},
            h2h=[],
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\n"
        "Man City host Man United here, with Man City sat 2nd on 63 points and form WWWDW.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway have Man City at 2.10 and the price still looks playable.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Standard variance applies.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Man City at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["team_names_present"]["passed"] is True


def test_no_fabricated_names_accepts_journalist_from_news_title() -> None:
    pack = _make_pack(
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "news_articles", 15.0),
            articles=[{"title": "Luke Edwards says Arsenal trained at full strength", "source": "Telegraph"}],
            article_count=1,
        )
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and Luke Edwards says the training picture is stable.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_no_fabricated_names_accepts_espn_source_reference() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, but ESPN context is thin enough that the setup stays neutral.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_no_fabricated_names_accepts_sa_bookmaker_display_name_from_pack() -> None:
    pack = _make_pack(
        sa_odds=evidence_pack.SAOddsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "odds_latest", 20.0),
            odds_by_bookmaker={"wsb": {"home": 2.10, "draw": 3.30, "away": 3.60}},
            best_odds={"home": 2.10},
            best_bookmaker={"home": "wsb"},
            bookmaker_count=1,
        )
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and World Sports Betting is one of the verified SA bookmaker references here.",
        "WSB have Arsenal at 2.10 and the edge is still there.",
        verdict="Lean Arsenal at WSB 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec(bookmaker="WSB"))

    assert passed is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_no_fabricated_names_still_rejects_unverified_proper_noun() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and John Smith says this is the best spot on the board.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is False
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is False


def test_no_fabricated_names_accepts_across_sa_phrase() -> None:
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and Across SA the price still points the same way.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_banned_phrases_absent_accepts_limited_pre_match_context_false_positive() -> None:
    spec = _make_spec(tone_band="cautious", evidence_class="speculative", support_level=0)
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, but limited pre-match context keeps the setup measured.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), spec)

    assert passed is True
    assert report["hard_checks"]["banned_phrases_absent"]["passed"] is True


def test_banned_phrases_absent_accepts_non_assertive_confident_usage() -> None:
    spec = _make_spec(tone_band="cautious", evidence_class="speculative", support_level=0)
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, and should arrive confident after recent results without turning this into a certainty call.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), spec)

    assert passed is True
    assert report["hard_checks"]["banned_phrases_absent"]["passed"] is True


def test_banned_phrases_absent_accepts_contextual_confident_team_state() -> None:
    spec = _make_spec(tone_band="cautious", evidence_class="speculative", support_level=0)
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, while Bournemouth should still arrive confident after recent away results.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), spec)

    assert passed is True
    assert report["hard_checks"]["banned_phrases_absent"]["passed"] is True


def test_banned_phrases_absent_still_rejects_confident_stake_language() -> None:
    spec = _make_spec(tone_band="cautious", evidence_class="speculative", support_level=0)
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
        verdict="Worth a confident stake on Arsenal at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), spec)

    assert passed is False
    assert report["hard_checks"]["banned_phrases_absent"]["passed"] is False


def test_ev_probability_values_accepts_settlement_hit_rate_inside_edge_context() -> None:
    spec = _make_spec(
        home_name="Brighton and Hove Albion",
        away_name="Liverpool",
        home_position=10,
        away_position=3,
        home_points=42,
        away_points=58,
        home_form="WDLWW",
        away_form="WWDLW",
        ev_pct=0.0,
        fair_prob_pct=0.0,
    )
    pack = _make_pack(
        match_key="brighton_vs_liverpool_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Brighton and Hove Albion", "position": 10, "points": 42, "form": "WDLWW", "coach": "Fabian Hurzeler"},
            away_team={"name": "Liverpool", "position": 3, "points": 58, "form": "WWDLW", "coach": "Arne Slot"},
            h2h=[],
        ),
        settlement_stats=evidence_pack.SettlementBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "edge_results", 0.0),
            stats_7d={"hit_rate": 0.423, "total": 26},
            stats_30d={"hit_rate": 0.481, "total": 57},
            tier_hit_rates={"silver": 0.423},
            streak={"label": "1 win"},
            total_settled=83,
        ),
    )
    draft = _draft(
        "Brighton host Liverpool here, with Brighton sat 10th on 42 points and form WDLWW.",
        "Betway have Brighton at 2.10 and the edge still lines up with a 42.3% 7-day hit rate from the settlement sample.",
        verdict="Lean Brighton at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["ev_probability_values"]["passed"] is True


def test_ev_probability_values_accepts_settlement_sample_phrase_even_with_edge_wording() -> None:
    spec = _make_spec(
        home_name="Brighton and Hove Albion",
        away_name="Liverpool",
        home_position=10,
        away_position=3,
        home_points=42,
        away_points=58,
        home_form="WDLWW",
        away_form="WWDLW",
        ev_pct=2.3,
        fair_prob_pct=45.5,
    )
    pack = _make_pack(
        match_key="brighton_vs_liverpool_2026-03-21",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Brighton and Hove Albion", "position": 10, "points": 42, "form": "WDLWW", "coach": "Fabian Hurzeler"},
            away_team={"name": "Liverpool", "position": 3, "points": 58, "form": "WWDLW", "coach": "Arne Slot"},
            h2h=[],
        ),
        settlement_stats=evidence_pack.SettlementBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "edge_results", 0.0),
            stats_7d={"hit_rate": 0.423, "total": 26},
            stats_30d={"hit_rate": 0.481, "total": 57},
            tier_hit_rates={"silver": 0.423},
            streak={"label": "1 win"},
            total_settled=83,
        ),
    )
    draft = _draft(
        "Brighton host Liverpool here, with Brighton sat 10th on 42 points and form WDLWW.",
        "Betway have Brighton at 2.10 and the edge still lines up with a 42.3% edge from the recent settlement sample.",
        verdict="Lean Brighton at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["ev_probability_values"]["passed"] is True


def test_no_fabricated_names_accepts_kings_park_venue_reference() -> None:
    spec = _make_spec(
        home_name="Sharks",
        away_name="Munster",
        competition="URC",
        sport="rugby",
        home_position=3,
        away_position=5,
        home_points=39,
        away_points=34,
        home_form="WWLWW",
        away_form="WLWDW",
        outcome_label="the Sharks win",
    )
    pack = _make_pack(
        match_key="sharks_vs_munster_2026-03-21",
        sport="rugby",
        league="urc",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Sharks", "position": 3, "points": 39, "form": "WWLWW", "coach": "John Plumtree"},
            away_team={"name": "Munster", "position": 5, "points": 34, "form": "WLWDW", "coach": "Graham Rowntree"},
            h2h=[],
        ),
    )
    draft = _draft(
        "Sharks host Munster at Kings Park, with Sharks sat 3rd on 39 points and form WWLWW.",
        "Betway have Sharks at 2.10 and the edge is still there.",
        verdict="Lean Sharks at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_no_fabricated_names_accepts_kings_park_stadium_reference() -> None:
    spec = _make_spec(
        home_name="Sharks",
        away_name="Munster",
        competition="URC",
        sport="rugby",
        home_position=3,
        away_position=5,
        home_points=39,
        away_points=34,
        home_form="WWLWW",
        away_form="WLWDW",
        outcome_label="the Sharks win",
    )
    pack = _make_pack(
        match_key="sharks_vs_munster_2026-03-21",
        sport="rugby",
        league="urc",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Sharks", "position": 3, "points": 39, "form": "WWLWW", "coach": "John Plumtree"},
            away_team={"name": "Munster", "position": 5, "points": 34, "form": "WLWDW", "coach": "Graham Rowntree"},
            h2h=[],
        ),
    )
    draft = _draft(
        "Sharks host Munster at Kings Park Stadium, with Sharks sat 3rd on 39 points and form WWLWW.",
        "Betway have Sharks at 2.10 and the edge is still there.",
        verdict="Lean Sharks at Betway 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True


def test_news_claims_traceable_ignores_contextual_manager_statement_without_news() -> None:
    spec = _make_spec(
        home_name="Real Madrid",
        away_name="Bayern Munich",
        competition="Champions League",
        home_position=1,
        away_position=2,
        home_points=72,
        away_points=68,
        home_form="WWWWW",
        away_form="WWDWW",
        outcome_label="the Real Madrid win",
    )
    pack = _make_pack(
        match_key="real_madrid_vs_bayern_2026-03-21",
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "news_articles", 999.0, error="No relevant team headlines."),
            articles=[],
            article_count=0,
        ),
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Real Madrid", "position": 1, "points": 72, "form": "WWWWW", "coach": "Carlo Ancelotti"},
            away_team={"name": "Bayern Munich", "position": 2, "points": 68, "form": "WWDWW", "coach": "Vincent Kompany"},
            h2h=[],
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\nReal Madrid host Bayern here, with Bayern still adapting under Vincent Kompany's management.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Real Madrid at 2.10 and the edge is still there.\n\n"
        "⚠️ <b>The Risk</b>\nStandard variance applies.\n\n"
        "🏆 <b>Verdict</b>\nLean Real Madrid at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["news_claims_traceable"]["passed"] is True


def test_news_claims_traceable_ignores_contextual_management_and_news_frame_combo() -> None:
    spec = _make_spec(
        home_name="Real Madrid",
        away_name="Bayern Munich",
        competition="Champions League",
        home_position=1,
        away_position=2,
        home_points=72,
        away_points=68,
        home_form="WWWWW",
        away_form="WWDWW",
        outcome_label="the Real Madrid win",
    )
    pack = _make_pack(
        match_key="real_madrid_vs_bayern_2026-03-21",
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "news_articles", 999.0, error="No relevant team headlines."),
            articles=[],
            article_count=0,
        ),
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Real Madrid", "position": 1, "points": 72, "form": "WWWWW", "coach": "Carlo Ancelotti"},
            away_team={"name": "Bayern Munich", "position": 2, "points": 68, "form": "WWDWW", "coach": "Vincent Kompany"},
            h2h=[],
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\nReal Madrid host Bayern here, with Bayern still adapting under Vincent Kompany and the broader team news picture staying quiet.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Real Madrid at 2.10 and the edge is still there.\n\n"
        "⚠️ <b>The Risk</b>\nStandard variance applies.\n\n"
        "🏆 <b>Verdict</b>\nLean Real Madrid at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["news_claims_traceable"]["passed"] is True


def test_news_claims_traceable_ignores_contextual_team_news_framing_without_news() -> None:
    spec = _make_spec(
        home_name="Real Madrid",
        away_name="Bayern Munich",
        competition="Champions League",
        home_position=1,
        away_position=2,
        home_points=72,
        away_points=68,
        home_form="WWWWW",
        away_form="WWDWW",
        outcome_label="the Real Madrid win",
    )
    pack = _make_pack(
        match_key="real_madrid_vs_bayern_2026-03-21",
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "news_articles", 999.0, error="No relevant team headlines."),
            articles=[],
            article_count=0,
        ),
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Real Madrid", "position": 1, "points": 72, "form": "WWWWW", "coach": "Carlo Ancelotti"},
            away_team={"name": "Bayern Munich", "position": 2, "points": 68, "form": "WWDWW", "coach": "Vincent Kompany"},
            h2h=[],
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\nReal Madrid host Bayern here, and the broader team news framing stays quiet rather than shifting the base angle.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Real Madrid at 2.10 and the edge is still there.\n\n"
        "⚠️ <b>The Risk</b>\nStandard variance applies.\n\n"
        "🏆 <b>Verdict</b>\nLean Real Madrid at Betway 2.10."
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, spec)

    assert passed is True
    assert report["hard_checks"]["news_claims_traceable"]["passed"] is True


def test_news_claims_traceable_still_rejects_explicit_report_style_claim_without_news() -> None:
    pack = _make_pack(
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(False, "2026-03-20T00:00:00+00:00", "news_articles", 999.0, error="No relevant team headlines."),
            articles=[],
            article_count=0,
        ),
    )
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
        risk="According to reports, Bukayo Saka is trending towards a return.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, pack, _make_spec())

    assert passed is False
    assert report["hard_checks"]["news_claims_traceable"]["passed"] is False


# ── FIX-VERIFIER-FALSE-POSITIVES tests ──────────────────────────────────────


def _newcastle_draft(setup: str, edge: str, risk: str = "Standard variance applies.", verdict: str = "Lean Newcastle at Hollywoodbets 1.85.") -> str:
    if "Bournemouth" not in setup:
        setup = f"Newcastle host Bournemouth here. {setup}"
    return (
        f"📋 <b>The Setup</b>\n{setup}\n\n"
        f"🎯 <b>The Edge</b>\n{edge}\n\n"
        f"⚠️ <b>The Risk</b>\n{risk}\n\n"
        f"🏆 <b>Verdict</b>\n{verdict}"
    )


def _make_newcastle_spec(**overrides) -> "NarrativeSpec":
    spec = _make_spec(
        home_name="Newcastle United",
        away_name="Bournemouth",
        home_coach="Eddie Howe",
        away_coach="Andoni Iraola",
        home_position=5,
        away_position=10,
        home_points=52,
        away_points=42,
        home_form="WWWLL",
        away_form="DDDDD",
        bookmaker="Hollywoodbets",
        odds=1.85,
        ev_pct=3.4,
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def _make_newcastle_pack(**overrides) -> evidence_pack.EvidencePack:
    pack = _make_pack(
        match_key="newcastle_vs_bournemouth_2026-04-18",
        sa_odds=evidence_pack.SAOddsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "odds_latest", 20.0),
            odds_by_bookmaker={"Hollywoodbets": {"home": 1.85, "draw": 3.50, "away": 4.20}},
            best_odds={"home": 1.85},
            best_bookmaker={"home": "Hollywoodbets"},
            bookmaker_count=1,
        ),
    )
    for key, value in overrides.items():
        setattr(pack, key, value)
    return pack


def test_fp1_st_james_park_plain_passes_no_fabricated_names() -> None:
    """AC-1: 'St James Park' (no apostrophe) must not be flagged as fabricated."""
    draft = _newcastle_draft(
        "Newcastle sit 5th on 52 points with form WWWLL, playing at St James Park.",
        "Hollywoodbets have Newcastle at 1.85 — a 4.2% edge over fair value.",
        verdict="Lean Newcastle at Hollywoodbets 1.85.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(
        draft, _make_newcastle_pack(), _make_newcastle_spec()
    )

    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True, (
        f"St James Park should not be flagged: {report['hard_checks']['no_fabricated_names']['detail']}"
    )


def test_fp2_st_james_park_apostrophe_passes_no_fabricated_names() -> None:
    """AC-1: 'St James\u2019 Park' (curly apostrophe) must not be flagged as fabricated."""
    draft = _newcastle_draft(
        "Newcastle sit 5th on 52 points with form WWWLL, playing at St James\u2019 Park.",
        "Hollywoodbets have Newcastle at 1.85 — a 4.2% edge over fair value.",
        verdict="Lean Newcastle at Hollywoodbets 1.85.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(
        draft, _make_newcastle_pack(), _make_newcastle_spec()
    )

    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True, (
        f"St James\u2019 Park should not be flagged: {report['hard_checks']['no_fabricated_names']['detail']}"
    )


def test_fp3_the_gunners_nickname_passes_no_fabricated_names() -> None:
    """AC-2: 'The Gunners' (Arsenal nickname) must not be flagged as fabricated."""
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL. The Gunners have been dominant at home.",
        "Hollywoodbets have Arsenal at 2.10 — a 5.2% edge over fair value.",
        verdict="Lean Arsenal at Hollywoodbets 2.10.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(
        draft, _make_pack(), _make_spec(bookmaker="Hollywoodbets", odds=2.10)
    )

    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True, (
        f"The Gunners should not be flagged: {report['hard_checks']['no_fabricated_names']['detail']}"
    )


def test_fp4_sa_team_nicknames_pass_no_fabricated_names() -> None:
    """AC-4: SA team nicknames (Bafana Bafana, Amakhosi, Springboks, Proteas) must pass."""
    # Use a spec where home/away names include these teams to keep other checks happy
    bafana_spec = _make_spec(
        home_name="South Africa",
        away_name="Nigeria",
        competition="AFCON Qualifier",
        home_coach="Hugo Broos",
        away_coach="",
        home_position=1,
        away_position=3,
        home_points=12,
        away_points=9,
        home_form="WWWDW",
        away_form="WWDLW",
        bookmaker="Hollywoodbets",
        odds=1.90,
        ev_pct=4.0,
    )
    bafana_pack = _make_pack(
        match_key="south_africa_vs_nigeria_2026-06-15",
        sa_odds=evidence_pack.SAOddsBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "odds_latest", 20.0),
            odds_by_bookmaker={"Hollywoodbets": {"home": 1.90, "draw": 3.20, "away": 4.00}},
            best_odds={"home": 1.90},
            best_bookmaker={"home": "Hollywoodbets"},
            bookmaker_count=1,
        ),
    )
    draft = (
        "📋 <b>The Setup</b>\n"
        "South Africa host Nigeria here. Bafana Bafana sit top of the group on 12 points with form WWWDW.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets have South Africa at 1.90 — a 4.0% edge over fair value at 52.6%.\n\n"
        "⚠️ <b>The Risk</b>\nStandard variance applies.\n\n"
        "🏆 <b>Verdict</b>\nLean South Africa at Hollywoodbets 1.90."
    )

    _passed, report = evidence_pack.verify_shadow_narrative(draft, bafana_pack, bafana_spec)

    assert report["hard_checks"]["no_fabricated_names"]["passed"] is True, (
        f"Bafana Bafana should not be flagged: {report['hard_checks']['no_fabricated_names']['detail']}"
    )


def test_fp5_genuinely_fabricated_stadium_still_fails() -> None:
    """AC-3: A made-up stadium name must still be rejected — whitelist must not be a rubber stamp."""
    draft = _draft(
        "Arsenal sit 2nd on 61 points with form WWWDL, playing at The Thunderdome Arena.",
        "Hollywoodbets have Arsenal at 2.10 — a 5.2% edge over fair value.",
        verdict="Lean Arsenal at Hollywoodbets 2.10.",
    )

    _passed, report = evidence_pack.verify_shadow_narrative(
        draft, _make_pack(), _make_spec(bookmaker="Hollywoodbets", odds=2.10)
    )

    assert report["hard_checks"]["no_fabricated_names"]["passed"] is False, (
        "A fabricated stadium 'The Thunderdome Arena' must still be caught by the verifier"
    )


def test_fp6_known_proper_nouns_is_importable_and_extensible() -> None:
    """AC-5: KNOWN_PROPER_NOUNS is a module-level set that can be extended."""
    assert hasattr(evidence_pack, "KNOWN_PROPER_NOUNS"), "KNOWN_PROPER_NOUNS must be a module-level attribute"
    assert isinstance(evidence_pack.KNOWN_PROPER_NOUNS, set), "KNOWN_PROPER_NOUNS must be a set"
    # All required entries per the brief
    required = {
        "the gunners",   # Arsenal
        "the reds",      # Liverpool/Man United
        "the blues",     # Chelsea/Man City
        "the foxes",     # Leicester
        "the hammers",   # West Ham
        "the toffees",   # Everton
        "the magpies",   # Newcastle
        "the saints",    # Southampton
        "the blades",    # Sheffield United
        "bafana bafana", # SA national
        "amakhosi",      # Kaizer Chiefs
        "buccaneers",    # Orlando Pirates
        "stormers",      # Stormers
        "bulls",         # Bulls
        "sharks",        # Sharks
        "lions",         # Lions
        "springboks",    # Springboks
        "boks",          # Boks (short form)
        "proteas",       # SA cricket
    }
    missing = required - evidence_pack.KNOWN_PROPER_NOUNS
    assert not missing, f"Required entries missing from KNOWN_PROPER_NOUNS: {missing}"
    # Extensibility: adding an entry should work
    evidence_pack.KNOWN_PROPER_NOUNS.add("_test_entry_")
    assert "_test_entry_" in evidence_pack.KNOWN_PROPER_NOUNS
    evidence_pack.KNOWN_PROPER_NOUNS.discard("_test_entry_")


def test_strict_form_points_claims_still_reject_unsupported_values() -> None:
    draft = _draft(
        "Arsenal sit 3rd on 63 points with form WWWWW.",
        "Betway have Arsenal at 2.10 and the edge is still there.",
    )

    passed, report = evidence_pack.verify_shadow_narrative(draft, _make_pack(), _make_spec())

    assert passed is False
    assert report["hard_checks"]["form_strings_traceable"]["passed"] is False
    assert report["hard_checks"]["standings_positions_traceable"]["passed"] is False
    assert report["hard_checks"]["points_traceable"]["passed"] is False
