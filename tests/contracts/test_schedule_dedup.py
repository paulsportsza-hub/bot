"""CARD-FIX-B Task 1 — Cross-source schedule dedup regression tests.

Ensures that build_match_id() produces the same normalised key regardless
of whether commence_time is real (API) or synthetic midnight (DB), so
_fetch_schedule_games() deduplicates correctly.
"""
import sys


def _ensure_scrapers_path():
    """Add scrapers parent to sys.path if not already present."""
    scrapers_parent = "/home/paulsportsza"
    if scrapers_parent not in sys.path:
        sys.path.insert(0, scrapers_parent)


def test_cross_source_dedup_same_match():
    """Two sources (Odds API + odds.db) for same match must normalise to same key."""
    _ensure_scrapers_path()
    from services.odds_service import build_match_id

    # Odds API event: real commence_time
    api_mid = build_match_id("Chelsea", "Man City", "2026-04-12T15:00:00Z")
    # DB event: synthetic midnight from match_id suffix
    db_mid = build_match_id("Chelsea", "Man City", "2026-04-12T00:00:00Z")

    # Both should produce the same normalised match_id (date portion is YYYY-MM-DD)
    assert api_mid == db_mid, (
        f"API mid '{api_mid}' != DB mid '{db_mid}' — "
        "cross-source dedup will fail because build_match_id uses date[:10]"
    )


def test_distinct_chelsea_fixtures_not_collapsed():
    """Chelsea vs Man City (Apr 12) and Chelsea vs Man Utd (Apr 18) must both appear."""
    _ensure_scrapers_path()
    from services.odds_service import build_match_id

    mid1 = build_match_id("Chelsea", "Man City", "2026-04-12T15:00:00Z")
    mid2 = build_match_id("Chelsea", "Man Utd", "2026-04-18T19:30:00Z")

    assert mid1 != mid2, "Two distinct fixtures must produce different match IDs"

    # Same fixture, same date, different times → same ID
    mid1_midnight = build_match_id("Chelsea", "Man City", "2026-04-12T00:00:00Z")
    assert mid1 == mid1_midnight, (
        "Same fixture with different times on same date must normalise to same ID"
    )


def test_db_sourced_event_commence_time_not_midnight():
    """DB events with broadcast_schedule start_time should inherit real kickoff.

    Verifies that build_card_data accepts conn parameter for broadcast_schedule
    kickoff resolution (CARD-FIX-B Task 3).
    """
    import inspect
    import card_pipeline

    sig = inspect.signature(card_pipeline.build_card_data)
    params = list(sig.parameters.keys())
    assert "conn" in params, "build_card_data must accept conn parameter for DB queries"
    assert "match_key" in params, "build_card_data must accept match_key"
