from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import bot
import evidence_pack
import scripts.pregenerate_narratives as pregen
from scrapers.match_context_fetcher import _parse_score as _parse_espn_score


def _init_odds_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS odds_latest (
            match_id TEXT,
            bookmaker TEXT,
            market_type TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            last_seen TEXT
        )"""
    )
    conn.commit()
    conn.close()


def _init_injury_tables(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT,
            team TEXT,
            player_name TEXT,
            player_id INTEGER,
            injury_type TEXT,
            injury_reason TEXT,
            injury_status TEXT,
            fixture_id INTEGER,
            fixture_date TEXT,
            fetched_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS extracted_injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            player_name TEXT,
            team_key TEXT,
            status TEXT,
            injury_type TEXT,
            keyword_match TEXT,
            confidence TEXT,
            extracted_at TEXT,
            expires_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source TEXT,
            url TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _init_match_results_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS match_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT UNIQUE,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_score INTEGER,
            away_score INTEGER,
            result TEXT NOT NULL,
            match_date DATE NOT NULL,
            season TEXT,
            source TEXT DEFAULT 'espn',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def test_ensure_narrative_cache_table_adds_evidence_json(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    try:
        bot._ensure_narrative_cache_table()
        conn = sqlite3.connect(db_path)
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(narrative_cache)").fetchall()
        }
        conn.close()
        assert "evidence_json" in cols
    finally:
        bot._NARRATIVE_DB_PATH = original


@pytest.mark.asyncio
async def test_store_narrative_cache_persists_evidence_json(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    _init_odds_db(db_path)
    try:
        bot._ensure_narrative_cache_table()
        await bot._store_narrative_cache(
            "chiefs_vs_sundowns_2026-03-08",
            "<b>Test narrative</b>",
            [{"outcome": "home", "odds": 2.5, "ev": 5.0}],
            "gold",
            "opus",
            evidence_json='{"richness_score":"medium"}',
        )
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT evidence_json FROM narrative_cache WHERE match_id = ?",
            ("chiefs_vs_sundowns_2026-03-08",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == '{"richness_score":"medium"}'
    finally:
        bot._NARRATIVE_DB_PATH = original


def test_score_richness_levels() -> None:
    high_pack = evidence_pack.EvidencePack(
        match_key="a_vs_b_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        sa_odds=evidence_pack.SAOddsBlock(provenance=evidence_pack.EvidenceSource(True, "", "", 0.0)),
        edge_state=evidence_pack.EdgeStateBlock(provenance=evidence_pack.EvidenceSource(True, "", "", 0.0)),
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            data_available=True,
        ),
        sharp_lines=evidence_pack.SharpLinesBlock(provenance=evidence_pack.EvidenceSource(True, "", "", 0.0)),
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            total_injury_count=2,
        ),
        news=evidence_pack.NewsBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            article_count=2,
        ),
    )
    medium_pack = evidence_pack.EvidencePack(
        match_key="a_vs_b_2026-03-20",
        sport="soccer",
        league="psl",
        built_at="2026-03-20T00:00:00+00:00",
        sa_odds=evidence_pack.SAOddsBlock(provenance=evidence_pack.EvidenceSource(True, "", "", 0.0)),
        edge_state=evidence_pack.EdgeStateBlock(provenance=evidence_pack.EvidenceSource(True, "", "", 0.0)),
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            data_available=False,
        ),
    )
    low_pack = evidence_pack.EvidencePack(
        match_key="a_vs_b_2026-03-20",
        sport="soccer",
        league="ufc",
        built_at="2026-03-20T00:00:00+00:00",
        sa_odds=evidence_pack.SAOddsBlock(provenance=evidence_pack.EvidenceSource(False, "", "", 0.0)),
        edge_state=evidence_pack.EdgeStateBlock(provenance=evidence_pack.EvidenceSource(True, "", "", 0.0)),
    )

    assert evidence_pack._score_richness(high_pack) == ("high", 6)
    assert evidence_pack._score_richness(medium_pack) == ("medium", 2)
    assert evidence_pack._score_richness(low_pack) == ("low", 1)


def test_match_context_parse_score_handles_score_strings() -> None:
    assert _parse_espn_score("2-1") == 2


def test_match_verified_name_accepts_possessive_token() -> None:
    assert evidence_pack._match_verified_name("Betway's", {"betway"}) is True
    assert evidence_pack._match_verified_name("Arsenal's", {"arsenal"}) is True


def test_match_verified_name_accepts_unique_injury_surname_only() -> None:
    verified = evidence_pack._build_verified_injured(
        evidence_pack.EvidencePack(
            match_key="brighton_vs_liverpool_2026-03-20",
            sport="soccer",
            league="epl",
            built_at="2026-03-20T00:00:00+00:00",
            injuries=evidence_pack.InjuriesBlock(
                provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
                api_football=[
                    {"player_name": "M. Salah", "injury_status": "Questionable"},
                    {"player_name": "A. Du Preez", "injury_status": "Questionable"},
                ],
                total_injury_count=2,
            ),
        ),
        SimpleNamespace(injuries_home=[], injuries_away=[]),
    )
    unique_surnames = evidence_pack._build_unique_injury_surnames(
        evidence_pack.EvidencePack(
            match_key="brighton_vs_liverpool_2026-03-20",
            sport="soccer",
            league="epl",
            built_at="2026-03-20T00:00:00+00:00",
            injuries=evidence_pack.InjuriesBlock(
                provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
                api_football=[
                    {"player_name": "M. Salah", "injury_status": "Questionable"},
                    {"player_name": "A. Du Preez", "injury_status": "Questionable"},
                ],
                total_injury_count=2,
            ),
        ),
        SimpleNamespace(injuries_home=[], injuries_away=[]),
    )

    assert evidence_pack._match_verified_name(
        "Salah",
        verified,
        allow_single_token=False,
        unique_surnames=unique_surnames,
    ) is True
    assert evidence_pack._match_verified_name(
        "Du Preez",
        verified,
        allow_single_token=False,
        unique_surnames=unique_surnames,
    ) is True


def test_match_verified_name_rejects_ambiguous_injury_surname_only() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="liverpool_vs_spurs_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            api_football=[
                {"player_name": "M. Salah", "injury_status": "Questionable"},
                {"player_name": "A. Salah", "injury_status": "Questionable"},
            ],
            total_injury_count=2,
        ),
    )
    spec = SimpleNamespace(injuries_home=[], injuries_away=[])
    verified = evidence_pack._build_verified_injured(pack, spec)
    unique_surnames = evidence_pack._build_unique_injury_surnames(pack, spec)

    assert "salah" not in unique_surnames
    assert evidence_pack._match_verified_name(
        "Salah",
        verified,
        allow_single_token=False,
        unique_surnames=unique_surnames,
    ) is False


def test_match_verified_name_accepts_unique_injury_first_name_only() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="brighton_vs_liverpool_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        injuries=evidence_pack.InjuriesBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            api_football=[{"player_name": "Alisson Becker", "injury_status": "Questionable"}],
            total_injury_count=1,
        ),
    )
    spec = SimpleNamespace(injuries_home=[], injuries_away=[])
    verified = evidence_pack._build_verified_injured(pack, spec)
    unique_single_tokens = evidence_pack._build_unique_injury_single_tokens(pack, spec)

    assert "alisson" in unique_single_tokens
    assert evidence_pack._match_verified_name(
        "Alisson",
        verified,
        allow_single_token=True,
        unique_single_tokens=unique_single_tokens,
    ) is True


def test_format_edge_section_omits_zero_fair_probability() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        edge_state=evidence_pack.EdgeStateBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            composite_score=34.9,
            edge_tier="bronze",
            edge_pct=2.2,
            outcome="home",
            fair_probability=0.0,
            confirming_signals=1,
            contradicting_signals=1,
            signals={"movement": {"direction": "neutral"}},
            price_edge_score=0.4,
            market_agreement_score=0.3,
            movement_score=0.1,
            tipster_score=0.0,
            lineup_injury_score=0.0,
            form_h2h_score=0.0,
            weather_score=0.0,
            sharp_available=False,
        ),
    )

    section, error = evidence_pack._format_edge_section(pack)

    assert error is None
    assert section is not None
    assert "EV: 2.2% | Composite: 34.9/100" in section
    assert "Fair probability" not in section


def test_contains_explicit_news_claim_ignores_contextual_and_absence_phrases() -> None:
    assert evidence_pack._contains_explicit_news_claim("Bayern are still adapting under Vincent Kompany's management.") is False
    assert evidence_pack._contains_explicit_news_claim("No verified team news has filtered through for this match.") is False
    assert evidence_pack._contains_explicit_news_claim("The broader team news framing stays quiet for this match.") is False
    assert evidence_pack._contains_explicit_news_claim("According to reports, Bayern are set to rotate.") is True


def test_extract_candidate_proper_nouns_ignores_across_sa_phrase() -> None:
    nouns = evidence_pack._extract_candidate_proper_nouns(
        "Across SA, Betway still has Arsenal at 2.10 while Arsenal host Bournemouth."
    )

    assert "Across SA" not in nouns


def test_build_verified_names_includes_espn_token_when_context_exists() -> None:
    spec = SimpleNamespace(
        home_name="Arsenal",
        away_name="Bournemouth",
        competition="Premier League",
        sport="soccer",
        bookmaker="Betway",
    )
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        espn_context=evidence_pack.ESPNContextBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "match_context_fetcher", 0.0),
            data_available=True,
            home_team={"name": "Arsenal", "coach": "Mikel Arteta"},
            away_team={"name": "Bournemouth", "coach": "Andoni Iraola"},
        ),
    )

    coaches = evidence_pack._build_verified_coaches(pack, spec)
    verified = evidence_pack._build_verified_names(
        pack,
        spec,
        coaches,
        set(),
        evidence_pack._build_team_reference_aliases(pack, spec),
    )

    assert "espn" in verified


def test_is_h2h_absence_statement_handles_missing_history_language() -> None:
    assert evidence_pack._is_h2h_absence_statement("There is no head-to-head history in the verified pack.") is True
    assert evidence_pack._is_h2h_absence_statement("Setup stays neutral without H2H data.") is True
    assert evidence_pack._is_h2h_absence_statement("We are flying blind on recent meetings here.") is True
    assert evidence_pack._is_h2h_absence_statement("This angle runs without verified H2H history.") is True
    assert evidence_pack._is_h2h_absence_statement("There is missing recent meeting data for this fixture.") is True
    assert evidence_pack._is_h2h_absence_statement("There is no verified H2H block available for this match.") is True
    assert evidence_pack._is_h2h_absence_statement("Arsenal won the last meeting 2-1.") is False


def test_contains_h2h_claim_ignores_absence_language() -> None:
    assert bot._contains_h2h_claim("No head-to-head history available here.") is False
    assert bot._contains_h2h_claim("Flying blind on recent meetings, so setup stays neutral.") is False
    assert bot._contains_h2h_claim("Without verified H2H history, this is a pure price read.") is False
    assert bot._contains_h2h_claim("No verified H2H block available, so setup stays neutral.") is False
    assert bot._contains_h2h_claim("Arsenal won the last meeting 2-1.") is True


def test_build_locked_sharp_snippets_prefers_canonical_direct_prices() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        edge_state=evidence_pack.EdgeStateBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "edge_v2", 0.0),
            outcome="home",
        ),
        sharp_lines=evidence_pack.SharpLinesBlock(
            provenance=evidence_pack.EvidenceSource(True, "2026-03-20T00:00:00+00:00", "sharp_odds", 10.0),
            pinnacle_price={"home": 2.02, "away": 3.50},
            betfair_price={"home": 2.04},
            benchmarks=[
                {"bookmaker": "Pinnacle", "selection": "home", "back_price": 2.01, "lay_price": 2.03},
                {"bookmaker": "Smarkets", "selection": "away", "back_price": 3.55},
            ],
            spread_pct=1.5,
            liquidity_score="medium",
        ),
    )

    snippets = evidence_pack._build_locked_sharp_snippets(pack)

    assert snippets == ["Pinnacle home 2.02", "Betfair home 2.04"]


def test_build_sharp_injection_uses_locked_snippet_for_recommended_outcome() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        edge_state=evidence_pack.EdgeStateBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            outcome="home",
        ),
        sharp_lines=evidence_pack.SharpLinesBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            pinnacle_price={"home": 2.02},
            betfair_price={"home": 2.04},
            benchmarks=[{"bookmaker": "Pinnacle", "selection": "home", "back_price": 2.02}],
        ),
    )
    spec = SimpleNamespace(outcome="home", evidence_class="lean", tone_band="moderate")

    assert evidence_pack._build_sharp_injection(pack, spec) == "Sharp market pricing has home at 2.02."


def test_build_sharp_injection_returns_empty_when_no_safe_snippet_exists() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        edge_state=evidence_pack.EdgeStateBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            outcome="home",
        ),
        sharp_lines=evidence_pack.SharpLinesBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            pinnacle_price={"away": 4.10},
            betfair_price={},
            benchmarks=[{"bookmaker": "Pinnacle", "selection": "away", "back_price": 4.10}],
        ),
    )
    spec = SimpleNamespace(outcome="home", evidence_class="lean", tone_band="moderate")

    assert evidence_pack._build_sharp_injection(pack, spec) == ""


def test_build_h2h_injection_uses_verified_summary_and_latest_score() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
            matches=[
                {"date": "2026-02-01", "home": "Arsenal", "away": "Bournemouth", "score": "2-1"},
                {"date": "2025-11-10", "home": "Bournemouth", "away": "Arsenal", "score": "1-1"},
            ],
            summary={"home_wins": 1, "draws": 1, "away_wins": 0, "total": 2},
            summary_text="2 meetings: Arsenal 1W 1D 0L",
        ),
    )

    assert evidence_pack._build_h2h_injection(pack, SimpleNamespace()) == (
        "Head to head: 2 meetings: Arsenal 1W 1D 0L, and the last meeting finished 2-1."
    )


def test_build_h2h_injection_returns_empty_when_no_verified_h2h_exists() -> None:
    pack = evidence_pack.EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-20",
        sport="soccer",
        league="epl",
        built_at="2026-03-20T00:00:00+00:00",
        h2h=evidence_pack.H2HBlock(
            provenance=evidence_pack.EvidenceSource(False, "", "", 0.0),
            matches=[],
        ),
    )

    assert evidence_pack._build_h2h_injection(pack, SimpleNamespace()) == ""


def test_inject_h2h_sentence_adds_sentence_inside_setup_section() -> None:
    draft = (
        "📋 <b>The Setup</b>\nArsenal host Bournemouth here.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Arsenal at 2.10 and the price still looks playable.\n\n"
        "⚠️ <b>The Risk</b>\nStandard variance applies.\n\n"
        "🏆 <b>Verdict</b>\nLean Arsenal at Betway 2.10."
    )

    injected = evidence_pack._inject_h2h_sentence(
        draft,
        "Head to head: 2 meetings: Arsenal 1W 1D 0L, and the last meeting finished 2-1.",
    )

    assert "📋 <b>The Setup</b>\nArsenal host Bournemouth here. Head to head: 2 meetings: Arsenal 1W 1D 0L, and the last meeting finished 2-1." in injected
    assert "🎯 <b>The Edge</b>" in injected


def test_inject_sharp_sentence_adds_sentence_inside_edge_section() -> None:
    draft = (
        "📋 <b>The Setup</b>\nArsenal host Bournemouth here.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Arsenal at 2.10 and the price still looks playable.\n\n"
        "⚠️ <b>The Risk</b>\nStandard variance applies.\n\n"
        "🏆 <b>Verdict</b>\nLean Arsenal at Betway 2.10."
    )

    injected = evidence_pack._inject_sharp_sentence(draft, "Sharp market pricing has home at 2.02.")

    assert "🎯 <b>The Edge</b>\nBetway have Arsenal at 2.10 and the price still looks playable. Sharp market pricing has home at 2.02." in injected
    assert "⚠️ <b>The Risk</b>" in injected


def test_suppress_shadow_banned_phrases_rewrites_recurring_cautious_failures() -> None:
    draft = (
        "Thin support remains the issue here. "
        "This is a pure pricing call, and supporting evidence is thin."
    )

    suppressed = evidence_pack._suppress_shadow_banned_phrases(draft)

    assert "Thin support" not in suppressed
    assert "pure pricing call" not in suppressed.lower()
    assert "supporting evidence is thin" not in suppressed.lower()
    assert "Limited support" in suppressed
    assert "price-led angle" in suppressed.lower()
    assert "supporting evidence is limited" in suppressed.lower()


def test_strip_model_generated_sharp_references_removes_sharp_sentences() -> None:
    draft = (
        "📋 <b>The Setup</b>\nArsenal host Bournemouth here.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Arsenal at 2.10 and the price still looks playable. Pinnacle have home at 9.99 here.\n\n"
        "⚠️ <b>The Risk</b>\nBetfair would disagree with that sharp line.\n\n"
        "🏆 <b>Verdict</b>\nLean Arsenal at Betway 2.10."
    )

    stripped = evidence_pack._strip_model_generated_sharp_references(draft)

    assert "Pinnacle" not in stripped
    assert "Betfair" not in stripped
    assert "Betway have Arsenal at 2.10 and the price still looks playable." in stripped


def test_strip_model_generated_h2h_references_removes_h2h_sentences() -> None:
    draft = (
        "📋 <b>The Setup</b>\nArsenal host Bournemouth here. Head to head: 9 meetings: Arsenal 8W 1D 0L. We are flying blind on recent meetings.\n\n"
        "🎯 <b>The Edge</b>\nBetway have Arsenal at 2.10 and the price still looks playable.\n\n"
        "⚠️ <b>The Risk</b>\nStandard variance applies.\n\n"
        "🏆 <b>Verdict</b>\nLean Arsenal at Betway 2.10."
    )

    stripped = evidence_pack._strip_model_generated_h2h_references(draft)

    assert "Head to head" not in stripped
    assert "recent meetings" not in stripped.lower()
    assert "Arsenal host Bournemouth here." in stripped


@pytest.mark.asyncio
async def test_generate_one_includes_evidence_json(monkeypatch) -> None:
    async def fake_match_context(*args, **kwargs):
        return {"data_available": False}

    async def fake_build_evidence_pack(*args, **kwargs):
        return evidence_pack.EvidencePack(
            match_key="kaizer_chiefs_vs_magesi_2026-03-21",
            sport="soccer",
            league="psl",
            built_at="2026-03-20T00:00:00+00:00",
            edge_state=evidence_pack.EdgeStateBlock(
                provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
                edge_pct=12.2,
            ),
        )

    class FakeMessages:
        async def create(self, *args, **kwargs):
            raise RuntimeError("skip polish")

    class FakeClaude:
        messages = FakeMessages()

    monkeypatch.setattr(pregen, "_get_match_context", fake_match_context)
    monkeypatch.setattr(pregen, "build_evidence_pack", fake_build_evidence_pack)
    monkeypatch.setattr(pregen, "serialise_evidence_pack", lambda pack: '{"pack_version":1}')

    edge = {
        "match_key": "kaizer_chiefs_vs_magesi_2026-03-21",
        "league": "psl",
        "sport": "soccer",
        "best_bookmaker": "gbets",
        "best_odds": 1.62,
        "edge_pct": 12.2,
        "fair_probability": 0.62,
        "outcome": "home",
        "confirming_signals": 2,
        "contradicting_signals": 0,
        "composite_score": 43.8,
        "signals": {},
        "tier": "silver",
    }

    result = await pregen._generate_one(edge, "claude-sonnet", FakeClaude(), sweep_type="refresh")

    assert result["success"] is True
    assert result["_cache"]["evidence_json"] == '{"pack_version":1}'


@pytest.mark.asyncio
async def test_edge_precompute_job_backfills_evidence(monkeypatch) -> None:
    tip = {
        "match_id": "west_ham_vs_wolves_2026-04-10",
        "home_team": "West Ham",
        "away_team": "Wolves",
        "sport_key": "soccer",
        "league_key": "epl",
        "display_tier": "gold",
        "edge_rating": "gold",
        "ev": 3.4,
        "odds": 1.82,
        "prob": 57,
        "bookmaker": "Supabets",
        "outcome": "West Ham",
        "edge_v2": {
            "match_key": "west_ham_vs_wolves_2026-04-10",
            "league": "epl",
            "sport": "soccer",
            "best_bookmaker": "supabets",
            "best_odds": 1.82,
            "edge_pct": 3.4,
            "fair_probability": 0.5682,
            "outcome": "home",
            "confirming_signals": 3,
            "contradicting_signals": 1,
            "signals": {},
            "tier": "gold",
        },
    }

    async def fake_fetch_hot_tips():
        return [tip]

    async def fake_get_cached_narrative(match_id: str):
        return {"html": "<b>cached</b>", "tips": [tip], "edge_tier": "gold", "model": "sonnet"}

    async def fake_build_evidence_pack(*args, **kwargs):
        return evidence_pack.EvidencePack(
            match_key="west_ham_vs_wolves_2026-04-10",
            sport="soccer",
            league="epl",
            built_at="2026-03-20T00:00:00+00:00",
            edge_state=evidence_pack.EdgeStateBlock(
                provenance=evidence_pack.EvidenceSource(True, "", "", 0.0),
                edge_pct=3.4,
            ),
        )

    store_calls: list[tuple[str, str]] = []

    async def fake_store_evidence(match_id: str, evidence_json: str):
        store_calls.append((match_id, evidence_json))
        return True

    monkeypatch.setattr(bot, "_fetch_hot_tips_from_db", fake_fetch_hot_tips)
    monkeypatch.setattr(bot, "_get_cached_narrative", fake_get_cached_narrative)
    monkeypatch.setattr(bot, "_store_narrative_evidence", fake_store_evidence)
    monkeypatch.setattr("evidence_pack.build_evidence_pack", fake_build_evidence_pack)
    monkeypatch.setattr("evidence_pack.serialise_evidence_pack", lambda pack: '{"match_key":"west_ham_vs_wolves_2026-04-10"}')

    old_analysis = dict(bot._analysis_cache)
    old_game = dict(bot._game_tips_cache)
    try:
        bot._analysis_cache.clear()
        bot._game_tips_cache.clear()
        await bot._edge_precompute_job(SimpleNamespace())
    finally:
        bot._analysis_cache.clear()
        bot._analysis_cache.update(old_analysis)
        bot._game_tips_cache.clear()
        bot._game_tips_cache.update(old_game)

    assert store_calls == [
        ("west_ham_vs_wolves_2026-04-10", '{"match_key":"west_ham_vs_wolves_2026-04-10"}')
    ]


def test_fetch_injuries_filters_cross_sport_team_collision(tmp_path) -> None:
    db_path = str(tmp_path / "injuries.db")
    _init_injury_tables(db_path)

    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO team_injuries
        (league, team, player_name, injury_reason, injury_status, fixture_date, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "psl",
                "Kaizer Chiefs",
                "Mduduzi Shabalala",
                "Hamstring",
                "Questionable",
                "2026-03-22T15:00:00+00:00",
                "2026-03-20 06:00:00",
            ),
            (
                "super_rugby",
                "Chiefs",
                "Damian McKenzie",
                "Knee",
                "Questionable",
                "2026-03-22T15:00:00+00:00",
                "2026-03-20 06:00:00",
            ),
        ],
    )
    conn.commit()
    conn.close()

    original = evidence_pack.ODDS_DB
    evidence_pack.ODDS_DB = db_path
    try:
        injuries = evidence_pack._fetch_injuries(
            home_key="brumbies",
            away_key="chiefs",
            home_name="Brumbies",
            away_name="Chiefs",
            league="super_rugby",
            sport="rugby",
        )
    finally:
        evidence_pack.ODDS_DB = original

    assert [item["player_name"] for item in injuries.home_injuries] == []
    assert [item["player_name"] for item in injuries.away_injuries] == ["Damian McKenzie"]


def test_fetch_h2h_prefers_match_results_over_espn(tmp_path) -> None:
    db_path = str(tmp_path / "h2h.db")
    _init_match_results_table(db_path)

    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO match_results
        (match_key, sport, league, home_team, away_team, home_score, away_score, result, match_date, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "arsenal_vs_bournemouth_2026-02-01",
                "soccer",
                "epl",
                "arsenal",
                "bournemouth",
                2,
                1,
                "home",
                "2026-02-01",
                "espn",
            ),
            (
                "bournemouth_vs_arsenal_2025-11-10",
                "soccer",
                "epl",
                "bournemouth",
                "arsenal",
                1,
                1,
                "draw",
                "2025-11-10",
                "espn",
            ),
        ],
    )
    conn.commit()
    conn.close()

    original = evidence_pack.ODDS_DB
    evidence_pack.ODDS_DB = db_path
    try:
        block = evidence_pack._fetch_h2h_from_match_results(
            home_key="arsenal",
            away_key="bournemouth",
            home_name="Arsenal",
            away_name="Bournemouth",
            league="epl",
            sport="soccer",
        )
    finally:
        evidence_pack.ODDS_DB = original

    assert block is not None
    assert block.provenance.source_name == "match_results"
    assert block.summary_text == "2 meetings: Arsenal 1W 1D 0L"
    assert [match["score"] for match in block.matches] == ["2-1", "1-1"]


def test_banned_phrase_false_positive_accepts_contextual_confident_usage() -> None:
    text = "Amazulu should arrive confident after recent wins, but the setup still needs respect."

    assert evidence_pack._is_banned_phrase_false_positive(text, "confident") is True


def test_banned_phrase_false_positive_still_rejects_confident_stake_usage() -> None:
    text = "Worth a confident stake on Amazulu if the 2.10 is still there."

    assert evidence_pack._is_banned_phrase_false_positive(text, "confident") is False


def test_contains_explicit_news_claim_ignores_contextual_management_framing() -> None:
    text = "Bayern are still adapting under Vincent Kompany's management, and the broader team news picture stays quiet."

    assert evidence_pack._contains_explicit_news_claim(text) is False


def test_contains_explicit_news_claim_still_flags_report_style_wording() -> None:
    text = "According to reports, Bayern are expected to welcome a starter back."

    assert evidence_pack._contains_explicit_news_claim(text) is True


def test_contains_settlement_percentage_context_accepts_sample_edge_wording() -> None:
    text = "the edge still lines up with a 42.3% recent settlement sample"

    assert evidence_pack._contains_settlement_percentage_context(text) is True
