from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

import sqlite3
from datetime import datetime, timedelta, timezone

import bot
from narrative_spec import NarrativeSpec, _render_baseline
from scrapers.news import news_helper


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
        support_level=3,
        contradicting_signals=0,
        evidence_class="supported",
        tone_band="confident",
        risk_factors=["Standard match variance applies."],
        risk_severity="moderate",
        verdict_action="back",
        verdict_sizing="standard stake",
        outcome="home",
        outcome_label="the Arsenal win",
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def _init_injury_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE team_injuries (
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
        CREATE TABLE extracted_injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            team_key TEXT,
            player_name TEXT,
            status TEXT,
            injury_type TEXT,
            confidence TEXT,
            keyword_match TEXT,
            extracted_at TEXT,
            expires_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source TEXT,
            url TEXT,
            body_text TEXT,
            published_at TEXT,
            scraped_at TEXT,
            has_injury_mentions INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


def test_validate_polish_rejects_global_banned_phrase() -> None:
    spec = _make_spec()
    baseline = _render_baseline(spec)
    polished = baseline.replace(
        "Standard match variance applies.",
        "Standard match variance applies. Let that shape the stake.",
    )

    assert bot._validate_polish(polished, baseline, spec) is False


def test_validate_polish_rejects_fabricated_h2h_rewrite() -> None:
    spec = _make_spec()
    baseline = _render_baseline(spec)
    polished = baseline.replace(
        "Head to head: 6 meetings: Arsenal 4W 1D 1L.",
        "Head to head: 6 meetings: Arsenal 1W 1D 4L.",
    )

    assert bot._validate_polish(polished, baseline, spec) is False


def test_validate_polish_rejects_h2h_prose_outside_labelled_line() -> None:
    spec = _make_spec()
    baseline = _render_baseline(spec)
    polished = baseline.replace(
        "Standard match variance applies.",
        "That head-to-head record of five straight draws is hard to ignore.",
    )

    assert bot._validate_polish(polished, baseline, spec) is False


def test_validate_polish_allows_h2h_omission_when_not_rewritten() -> None:
    spec = _make_spec()
    baseline = _render_baseline(spec)
    polished = baseline.replace("Head to head: 6 meetings: Arsenal 4W 1D 1L.", "").replace("\n\n\n", "\n\n")

    assert bot._validate_polish(polished, baseline, spec) is True


def test_validate_polish_rejects_stale_form_claim_when_context_is_not_fresh() -> None:
    spec = _make_spec(
        home_story_type="neutral",
        away_story_type="neutral",
        home_position=None,
        away_position=None,
        home_points=None,
        away_points=None,
        home_form="",
        away_form="",
        context_is_fresh=False,
        context_freshness_hours=72.0,
    )
    baseline = _render_baseline(spec)
    polished = baseline.replace(
        "📋 <b>The Setup</b>\n",
        "📋 <b>The Setup</b>\nArsenal have turned this ground into a fortress this season and Form reads WWWDL. ",
    )

    assert bot._validate_polish(polished, baseline, spec) is False


def test_get_verified_injuries_omits_stale_fixture_rows(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    _init_injury_db(db_path)

    now = datetime.now(timezone.utc)
    fresh_fixture = (now + timedelta(days=1)).strftime("%Y-%m-%dT15:00:00+00:00")
    stale_fixture = (now - timedelta(days=60)).strftime("%Y-%m-%dT15:00:00+00:00")
    recent_fetch = (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO team_injuries
        (league, team, player_name, injury_reason, injury_status, fixture_date, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "epl",
                "Arsenal",
                "Fresh Player",
                "Hamstring",
                "Questionable",
                fresh_fixture,
                recent_fetch,
            ),
            (
                "epl",
                "Arsenal",
                "Stale Player",
                "Knee",
                "Questionable",
                stale_fixture,
                recent_fetch,
            ),
        ],
    )
    conn.commit()
    conn.close()

    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    try:
        result = bot.get_verified_injuries("Arsenal", "Bournemouth")
    finally:
        bot._NARRATIVE_DB_PATH = original

    assert result["home"] == ["Fresh Player (Questionable)"]
    assert result["away"] == []


def test_format_injuries_for_narrative_omits_stale_fixture_rows(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    _init_injury_db(db_path)

    now = datetime.now(timezone.utc)
    fresh_fixture = (now + timedelta(days=1)).strftime("%Y-%m-%dT15:00:00+00:00")
    stale_fixture = (now - timedelta(days=60)).strftime("%Y-%m-%dT15:00:00+00:00")
    recent_fetch = (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
    match_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

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
                "Current Absence",
                "Hamstring",
                "Missing Fixture",
                fresh_fixture,
                recent_fetch,
            ),
            (
                "psl",
                "Kaizer Chiefs",
                "Old Absence",
                "Ankle",
                "Missing Fixture",
                stale_fixture,
                recent_fetch,
            ),
        ],
    )
    conn.commit()
    conn.close()

    text = news_helper.format_injuries_for_narrative(
        f"kaizer_chiefs_vs_orlando_pirates_{match_date}",
        db_path=db_path,
    )

    assert "Current Absence" in text
    assert "Old Absence" not in text


def test_get_verified_injuries_is_sport_aware_for_chiefs_name_collision(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    _init_injury_db(db_path)

    now = datetime.now(timezone.utc)
    fresh_fixture = (now + timedelta(days=1)).strftime("%Y-%m-%dT15:00:00+00:00")
    recent_fetch = (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")

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
                fresh_fixture,
                recent_fetch,
            ),
            (
                "super_rugby",
                "Chiefs",
                "Damian McKenzie",
                "Knee",
                "Questionable",
                fresh_fixture,
                recent_fetch,
            ),
        ],
    )
    conn.commit()
    conn.close()

    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    try:
        result = bot.get_verified_injuries(
            "Brumbies",
            "Chiefs",
            sport="rugby",
            league="super_rugby",
        )
    finally:
        bot._NARRATIVE_DB_PATH = original

    assert result["home"] == []
    assert result["away"] == ["Damian McKenzie (Questionable)"]


def test_format_routed_injuries_for_narrative_uses_verified_path_outside_psl(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    _init_injury_db(db_path)

    now = datetime.now(timezone.utc)
    fresh_fixture = (now + timedelta(days=1)).strftime("%Y-%m-%dT15:00:00+00:00")
    recent_fetch = (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")

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
                fresh_fixture,
                recent_fetch,
            ),
            (
                "super_rugby",
                "Chiefs",
                "Damian McKenzie",
                "Knee",
                "Questionable",
                fresh_fixture,
                recent_fetch,
            ),
        ],
    )
    conn.commit()
    conn.close()

    text = bot._format_routed_injuries_for_narrative(
        "",
        "Brumbies",
        "Chiefs",
        sport="rugby",
        league="super_rugby",
        db_path=db_path,
    )

    assert "Damian McKenzie (Questionable)" in text
    assert "Mduduzi Shabalala" not in text
    assert "Brumbies: No current injuries or absences." in text
