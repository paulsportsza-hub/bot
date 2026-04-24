"""Contract tests for FIX-CARD-ANALYSIS-CACHE-01.

Verifies that generate_card_analysis() wraps _call_haiku_with_breaker with a
sha256-keyed TTL cache so that identical verified_data avoids repeat Haiku calls.

openrouter_client is imported inside generate_card_analysis() with a local
`import openrouter_client as anthropic`, so tests patch via sys.modules.
"""
from __future__ import annotations

import hashlib
import sys
from unittest.mock import MagicMock, patch

import card_pipeline


def _or_patch():
    """Return a sys.modules patch that stubs out openrouter_client."""
    mock_or = MagicMock()
    mock_or.Anthropic.return_value = MagicMock()
    return patch.dict(sys.modules, {"openrouter_client": mock_or})


def _make_verified_data():
    return {
        "matchup": "Home vs Away",
        "best_odds": {
            "home": {"odds": 2.10, "bookmaker": "Betway"},
            "away": {"odds": 3.50, "bookmaker": "Betway"},
        },
        "home_key": "home",
        "away_key": "away",
        "ratings": {},
        "tipster": {},
        "fighters": {},
        "injuries": [],
    }


# ── AC-1: Module-level cache exists and is a TTLCache ─────────────────────────

def test_module_level_ttl_cache_exists():
    from cachetools import TTLCache
    assert hasattr(card_pipeline, "_card_analysis_cache"), (
        "_card_analysis_cache must exist at module level"
    )
    assert isinstance(card_pipeline._card_analysis_cache, TTLCache), (
        "_card_analysis_cache must be a cachetools.TTLCache"
    )


def test_cache_maxsize_and_ttl():
    cache = card_pipeline._card_analysis_cache
    assert cache.maxsize == 1000
    assert cache.ttl == 3600


# ── AC-2: Cache hit skips _call_haiku_with_breaker ────────────────────────────

def test_cache_hit_skips_haiku_call():
    """On second call with identical verified_data, Haiku must NOT be called."""
    card_pipeline._card_analysis_cache.clear()
    call_count = 0

    def fake_haiku(client, prompt):
        nonlocal call_count
        call_count += 1
        return "Great betting angle here."

    with patch("card_pipeline._call_haiku_with_breaker", side_effect=fake_haiku), \
         _or_patch():
        vd = _make_verified_data()
        r1 = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)
        r2 = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert r1 == r2 == "Great betting angle here."
    assert call_count == 1, (
        f"Haiku called {call_count} times; expected exactly 1 (second call must be cache hit)"
    )


def test_cache_hit_is_byte_identical():
    """Cached return must be byte-identical to the first call's return."""
    card_pipeline._card_analysis_cache.clear()

    with patch("card_pipeline._call_haiku_with_breaker", return_value="Exact analysis text."), \
         _or_patch():
        vd = _make_verified_data()
        r1 = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)
        r2 = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert r1 == r2, "Cache hit must return byte-identical string"


# ── AC-3: Failure path — empty/None NOT written to cache ──────────────────────

def test_failure_not_cached_when_haiku_returns_none():
    """Circuit-open / exception path: None return must NOT be written to cache."""
    card_pipeline._card_analysis_cache.clear()

    with patch("card_pipeline._call_haiku_with_breaker", return_value=None), \
         _or_patch():
        vd = _make_verified_data()
        result = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert result == ""
    assert len(card_pipeline._card_analysis_cache) == 0, (
        "None Haiku return must NOT be stored in cache"
    )


def test_failure_not_cached_when_haiku_returns_empty_string():
    """Empty string return must NOT be written to cache."""
    card_pipeline._card_analysis_cache.clear()

    with patch("card_pipeline._call_haiku_with_breaker", return_value=""), \
         _or_patch():
        vd = _make_verified_data()
        result = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert result == ""
    assert len(card_pipeline._card_analysis_cache) == 0, (
        "Empty string Haiku return must NOT be stored in cache"
    )


# ── AC-4: Cache key is sha256 of prompt (stable across renders) ───────────────

def test_cache_key_is_sha256_of_prompt():
    """The cache key stored must equal sha256(prompt).hexdigest()."""
    card_pipeline._card_analysis_cache.clear()
    captured_prompt = []

    def capture_haiku(client, prompt):
        captured_prompt.append(prompt)
        return "Stored analysis."

    with patch("card_pipeline._call_haiku_with_breaker", side_effect=capture_haiku), \
         _or_patch():
        vd = _make_verified_data()
        card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert captured_prompt, "Haiku must have been called once"
    expected_key = hashlib.sha256(captured_prompt[0].encode()).hexdigest()
    assert expected_key in card_pipeline._card_analysis_cache, (
        f"Cache must use sha256(prompt).hexdigest() as key; {expected_key!r} not found"
    )


# ── AC-5: Different inputs produce different cache entries ────────────────────

def test_different_inputs_different_cache_entries():
    """Different verified_data must produce separate cache entries."""
    card_pipeline._card_analysis_cache.clear()
    call_count = 0

    def counting_haiku(client, prompt):
        nonlocal call_count
        call_count += 1
        return f"Analysis #{call_count}"

    with patch("card_pipeline._call_haiku_with_breaker", side_effect=counting_haiku), \
         _or_patch():
        vd1 = _make_verified_data()
        vd2 = _make_verified_data()
        vd2["matchup"] = "Different vs Match"

        r1 = card_pipeline.generate_card_analysis("match_a_2026-04-25", vd1)
        r2 = card_pipeline.generate_card_analysis("match_b_2026-04-25", vd2)

    assert r1 != r2, "Different inputs must produce different Haiku calls and results"
    assert call_count == 2, "Two distinct prompts must each call Haiku once"
    assert len(card_pipeline._card_analysis_cache) == 2


# ── AC-6: circuit-breaker circuit-open path still returns empty (not cached) ──

def test_circuit_open_returns_empty_not_cached():
    """When circuit is open, _call_haiku_with_breaker returns None; must not cache."""
    card_pipeline._card_analysis_cache.clear()

    with patch("card_pipeline._call_haiku_with_breaker", return_value=None), \
         _or_patch():
        vd = _make_verified_data()
        result = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert result == "", "Circuit-open path must return empty string"
    assert len(card_pipeline._card_analysis_cache) == 0


# ── AC-7: Successful result IS written to cache ───────────────────────────────

def test_successful_result_written_to_cache():
    card_pipeline._card_analysis_cache.clear()

    with patch("card_pipeline._call_haiku_with_breaker", return_value="Analysis stored."), \
         _or_patch():
        vd = _make_verified_data()
        card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert len(card_pipeline._card_analysis_cache) == 1, (
        "Successful Haiku result must be stored in cache"
    )


# ── AC-8: Hard-capped result (>180 chars) is cached after truncation ──────────

def test_truncated_result_cached():
    card_pipeline._card_analysis_cache.clear()
    long_text = "X" * 200

    with patch("card_pipeline._call_haiku_with_breaker", return_value=long_text), \
         _or_patch():
        vd = _make_verified_data()
        result = card_pipeline.generate_card_analysis("home_vs_away_2026-04-25", vd)

    assert len(result) == 180, "Result must be hard-capped at 180 chars"
    assert result.endswith("...")
    assert len(card_pipeline._card_analysis_cache) == 1, (
        "Truncated but valid result must be stored in cache"
    )
    cached_val = next(iter(card_pipeline._card_analysis_cache.values()))
    assert cached_val == result, "Cached value must be the post-truncation string"
