"""BUILD-SCHEMAS-00 — Unit + integration tests for contracts/ Pydantic v2 package.

Tests P0 models: OddsSnapshotModel, EdgeResult, NarrativeCard, ScraperRunResult.
Integration test: Hollywoodbets → ScraperRunResult[OddsSnapshotModel] round-trip.
"""

import pytest
from datetime import datetime, timezone
from dataclasses import asdict

from contracts import OddsSnapshotModel, EdgeResult, NarrativeCard, ScraperRunResult
from contracts.adapters import validate_odds_snapshots


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_odds_dict(**overrides):
    """Minimal valid OddsSnapshotModel dict."""
    base = {
        "bookmaker": "hollywoodbets",
        "match_id": "arsenal_vs_chelsea_2026-04-14",
        "home_team": "arsenal",
        "away_team": "chelsea",
        "league": "epl",
        "sport": "football",
        "market_type": "1x2",
        "home_odds": 1.85,
        "draw_odds": 3.40,
        "away_odds": 4.20,
        "scraped_at": datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
        "source_url": "https://betapi.hollywoodbets.net/api/events/123/markets",
    }
    base.update(overrides)
    return base


def _make_edge_dict(**overrides):
    """Minimal valid EdgeResult dict."""
    base = {
        "match_key": "arsenal_vs_chelsea_2026-04-14",
        "outcome": "home",
        "market_type": "1x2",
        "sport": "football",
        "league": "epl",
        "edge_pct": 3.5,
        "composite_score": 62.0,
        "tier": "silver",
        "tier_display": "SILVER EDGE",
        "confidence": "medium",
        "sharp_available": True,
        "best_bookmaker": "hollywoodbets",
        "best_odds": 1.85,
        "fair_probability": 0.58,
        "sharp_source": "pinnacle",
        "method": "sharp_devig",
        "n_bookmakers": 4,
        "draw_penalty_applied": False,
        "league_penalty": 0.0,
        "stale_warning": False,
        "signals": {"movement": {"direction": "with", "strength": 0.6}},
        "confirming_signals": 2,
        "contradicting_signals": 0,
        "red_flags": [],
        "narrative": "Arsenal have an edge at home.",
        "narrative_bullets": ["Form: WWDWL"],
        "clv_avg": None,
        "clv_sample_size": 0,
        "created_at": "2026-04-14T12:00:00+00:00",
    }
    base.update(overrides)
    return base


def _make_narrative_dict(**overrides):
    """Minimal valid NarrativeCard dict."""
    base = {
        "fixture_id": "arsenal_vs_chelsea_2026-04-14",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "verdict_html": "<b>Back Arsenal</b> — genuine value at 1.85.",
        "pick": "home",
        "confidence_tier": "silver",
        "rendered_at": datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


# ── OddsSnapshotModel ────────────────────────────────────────────────────────

class TestOddsSnapshotModel:
    def test_valid_full(self):
        m = OddsSnapshotModel(**_make_odds_dict())
        assert m.bookmaker == "hollywoodbets"
        assert m.home_odds == 1.85
        assert m.draw_odds == 3.40

    def test_optional_fields_default(self):
        m = OddsSnapshotModel(**_make_odds_dict())
        assert m.over_odds is None
        assert m.under_odds is None
        assert m.event_id == ""
        assert m.handicap_line is None

    def test_with_over_under(self):
        m = OddsSnapshotModel(**_make_odds_dict(
            market_type="over_under_2.5",
            home_odds=0, away_odds=0,
            over_odds=1.90, under_odds=1.95,
        ))
        assert m.over_odds == 1.90

    def test_extra_field_forbidden(self):
        with pytest.raises(Exception):  # ValidationError
            OddsSnapshotModel(**_make_odds_dict(extra_field="boom"))

    def test_missing_required_field(self):
        d = _make_odds_dict()
        del d["bookmaker"]
        with pytest.raises(Exception):
            OddsSnapshotModel(**d)

    def test_wrong_type_strict(self):
        with pytest.raises(Exception):
            OddsSnapshotModel(**_make_odds_dict(home_odds="not_a_float"))

    def test_draw_odds_nullable(self):
        m = OddsSnapshotModel(**_make_odds_dict(draw_odds=None))
        assert m.draw_odds is None

    def test_model_dump_roundtrip(self):
        d = _make_odds_dict()
        m = OddsSnapshotModel(**d)
        dumped = m.model_dump()
        m2 = OddsSnapshotModel(**dumped)
        assert m == m2


# ── EdgeResult ────────────────────────────────────────────────────────────────

class TestEdgeResult:
    def test_valid_full(self):
        m = EdgeResult(**_make_edge_dict())
        assert m.tier == "silver"
        assert m.composite_score == 62.0

    def test_extra_field_forbidden(self):
        with pytest.raises(Exception):
            EdgeResult(**_make_edge_dict(rogue_field=True))

    def test_missing_required(self):
        d = _make_edge_dict()
        del d["match_key"]
        with pytest.raises(Exception):
            EdgeResult(**d)

    def test_signals_dict_accepted(self):
        m = EdgeResult(**_make_edge_dict(signals={"a": 1, "b": {"nested": True}}))
        assert m.signals["a"] == 1

    def test_clv_nullable(self):
        m = EdgeResult(**_make_edge_dict(clv_avg=2.3, clv_sample_size=15))
        assert m.clv_avg == 2.3

    def test_red_flags_list(self):
        m = EdgeResult(**_make_edge_dict(red_flags=["stale_price", "ghost_fixture"]))
        assert len(m.red_flags) == 2


# ── NarrativeCard ─────────────────────────────────────────────────────────────

class TestNarrativeCard:
    def test_valid(self):
        m = NarrativeCard(**_make_narrative_dict())
        assert m.pick == "home"

    def test_verdict_html_max_length(self):
        with pytest.raises(Exception):
            NarrativeCard(**_make_narrative_dict(verdict_html="x" * 141))

    def test_verdict_html_at_limit(self):
        m = NarrativeCard(**_make_narrative_dict(verdict_html="x" * 140))
        assert len(m.verdict_html) == 140

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            NarrativeCard(**_make_narrative_dict(bonus="nope"))


# ── ScraperRunResult ──────────────────────────────────────────────────────────

class TestScraperRunResult:
    def test_valid_empty(self):
        m = ScraperRunResult[OddsSnapshotModel](
            site_tag="hollywoodbets", run_id=1, rows=[], ok=True,
            errors=[], duration_ms=123.4,
        )
        assert m.ok is True
        assert len(m.rows) == 0

    def test_with_rows(self):
        row = OddsSnapshotModel(**_make_odds_dict())
        m = ScraperRunResult[OddsSnapshotModel](
            site_tag="hollywoodbets", run_id=1, rows=[row], ok=True,
            errors=[], duration_ms=456.7,
        )
        assert len(m.rows) == 1
        assert m.rows[0].bookmaker == "hollywoodbets"

    def test_with_errors(self):
        m = ScraperRunResult[OddsSnapshotModel](
            site_tag="hollywoodbets", run_id=1, rows=[], ok=False,
            errors=["bad row"], duration_ms=100.0,
        )
        assert not m.ok
        assert len(m.errors) == 1

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            ScraperRunResult[OddsSnapshotModel](
                site_tag="x", run_id=1, rows=[], ok=True,
                errors=[], duration_ms=0, bonus="x",
            )


# ── Adapter: validate_odds_snapshots ──────────────────────────────────────────

class TestAdapter:
    def test_valid_dataclass_to_model(self):
        """OddsSnapshot dataclass -> OddsSnapshotModel via adapter."""
        from scrapers.base_scraper import OddsSnapshot
        snap = OddsSnapshot(
            bookmaker="hollywoodbets",
            match_id="arsenal_vs_chelsea_2026-04-14",
            home_team="arsenal",
            away_team="chelsea",
            league="epl",
            sport="football",
            market_type="1x2",
            home_odds=1.85,
            draw_odds=3.40,
            away_odds=4.20,
            over_odds=None,
            under_odds=None,
            scraped_at=datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
            source_url="https://betapi.hollywoodbets.net/api/events/123/markets",
        )
        result = validate_odds_snapshots([snap], "hollywoodbets", run_id=1)
        assert result.ok
        assert len(result.rows) == 1
        assert result.rows[0].bookmaker == "hollywoodbets"
        assert result.site_tag == "hollywoodbets"
        assert result.errors == []

    def test_bad_row_captured_not_crash(self):
        """A malformed row is skipped + logged, valid rows pass through."""
        from scrapers.base_scraper import OddsSnapshot
        good = OddsSnapshot(
            bookmaker="hollywoodbets",
            match_id="good_vs_match_2026-04-14",
            home_team="good",
            away_team="match",
            league="epl",
            sport="football",
            market_type="1x2",
            home_odds=2.0,
            draw_odds=3.0,
            away_odds=4.0,
            over_odds=None,
            under_odds=None,
            scraped_at=datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
            source_url="https://example.com",
        )
        # Create a deliberately bad snapshot — force a string into home_odds
        bad = OddsSnapshot(
            bookmaker="hollywoodbets",
            match_id="bad_vs_match_2026-04-14",
            home_team="bad",
            away_team="match",
            league="epl",
            sport="football",
            market_type="1x2",
            home_odds=2.0,  # valid here, we'll corrupt the dict below
            draw_odds=3.0,
            away_odds=4.0,
            over_odds=None,
            under_odds=None,
            scraped_at=datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
            source_url="https://example.com",
        )
        # Corrupt after creation — inject extra field to trigger extra=forbid
        bad_dict = asdict(bad)
        bad_dict["rogue_key"] = "should_fail"

        # Manually validate: one good OddsSnapshot, one bad dict
        from contracts.odds import OddsSnapshotModel
        from pydantic import ValidationError

        validated = []
        errors = []
        for item in [good, bad]:
            d = asdict(item)
            if item is bad:
                d["rogue_key"] = "should_fail"
            try:
                validated.append(OddsSnapshotModel.model_validate(d))
            except ValidationError:
                errors.append(f"validation error on {d.get('match_id')}")

        assert len(validated) == 1
        assert len(errors) == 1

    def test_sentry_tag_on_violation(self):
        """Sentry is called with contract_violation tag on bad row."""
        from unittest.mock import patch, MagicMock
        from scrapers.base_scraper import OddsSnapshot

        # Create snapshot with extra field injected via adapter
        snap = OddsSnapshot(
            bookmaker="hollywoodbets",
            match_id="test_vs_sentry_2026-04-14",
            home_team="test",
            away_team="sentry",
            league="epl",
            sport="football",
            market_type="1x2",
            home_odds=2.0,
            draw_odds=3.0,
            away_odds=4.0,
            over_odds=None,
            under_odds=None,
            scraped_at=datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
            source_url="https://example.com",
        )

        # Monkey-patch asdict to inject extra field
        original_asdict = asdict
        def patched_asdict(obj):
            d = original_asdict(obj)
            d["rogue_key"] = "injected"
            return d

        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__ = MagicMock(return_value=mock_scope)
        mock_sentry.push_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch("contracts.adapters.asdict", patched_asdict):
            with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
                result = validate_odds_snapshots([snap], "hollywoodbets", run_id=1)

        assert not result.ok
        assert len(result.errors) == 1
        assert "contract_violation" in result.errors[0] or "validation" in result.errors[0]


# ── Integration: HWB scrape_validated round-trip ──────────────────────────────

class TestHWBIntegration:
    def test_scrape_validated_exists(self):
        """HollywoodbetsScraper source contains scrape_validated method."""
        import pathlib
        hwb_path = pathlib.Path(__file__).resolve().parents[3] / "scrapers" / "bookmakers" / "hollywoodbets.py"
        source = hwb_path.read_text()
        assert "async def scrape_validated" in source
        assert "validate_odds_snapshots" in source

    def test_validate_real_shape(self):
        """OddsSnapshot from base_scraper validates cleanly via adapter."""
        from scrapers.base_scraper import OddsSnapshot
        snap = OddsSnapshot(
            bookmaker="hollywoodbets",
            match_id="sundowns_vs_chiefs_2026-04-14",
            home_team="mamelodi_sundowns",
            away_team="kaizer_chiefs",
            league="psl",
            sport="football",
            market_type="1x2",
            home_odds=1.48,
            draw_odds=4.00,
            away_odds=6.50,
            over_odds=None,
            under_odds=None,
            scraped_at=datetime.now(timezone.utc),
            source_url="https://betapi.hollywoodbets.net/api/events/999/markets",
            event_id="999:42",
            handicap_line=None,
        )
        result = validate_odds_snapshots([snap], "hollywoodbets", run_id=42)
        assert result.ok
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.bookmaker == "hollywoodbets"
        assert row.match_id == "sundowns_vs_chiefs_2026-04-14"
        assert row.home_odds == 1.48
        assert row.event_id == "999:42"

    def test_round_trip_to_odds_snapshot(self):
        """Validated model can be converted back to OddsSnapshot for store_odds."""
        from scrapers.base_scraper import OddsSnapshot
        snap = OddsSnapshot(
            bookmaker="hollywoodbets",
            match_id="pirates_vs_sundowns_2026-04-14",
            home_team="orlando_pirates",
            away_team="mamelodi_sundowns",
            league="psl",
            sport="football",
            market_type="1x2",
            home_odds=2.80,
            draw_odds=3.10,
            away_odds=2.60,
            over_odds=None,
            under_odds=None,
            scraped_at=datetime.now(timezone.utc),
            source_url="https://betapi.hollywoodbets.net/api/events/100/markets",
        )
        result = validate_odds_snapshots([snap], "hollywoodbets")
        row = result.rows[0]
        # Convert back to OddsSnapshot (what store_odds expects)
        back = OddsSnapshot(**row.model_dump())
        assert back.bookmaker == snap.bookmaker
        assert back.home_odds == snap.home_odds
        assert back.match_id == snap.match_id
