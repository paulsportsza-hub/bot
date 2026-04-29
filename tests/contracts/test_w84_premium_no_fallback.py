"""FIX-W84-PREMIUM-NO-FALLBACK-01 — Diamond+Gold MUST NOT silently drop to W82.

When Sonnet polish fails on a Diamond/Gold tier card, the new fallback chain is:
  1. Sonnet retry (2 extra attempts with exponential backoff) — handled in-line
     inside `_generate_one()` by the polish-block retry loop.
  2. Haiku-narrative polish — `_attempt_haiku_polish_fallback()` helper.
  3. Defer the row write (no narrative_cache write this sweep) and increment
     consecutive-defer counter via `_record_premium_defer()`.
  4. Alert EdgeOps when consecutive defers reach `_PREMIUM_DEFER_ALERT_THRESHOLD`.

Silver+Bronze tier behaviour is unchanged — they keep the existing W82 fallback
per W93-TIER-GATE cost policy.

Tests:
- test_premium_defer_alert_chat_id_locked: chat_id sentinel is exactly the
  EdgeOps Telegram group from the brief.
- test_premium_defer_alert_threshold_is_3: threshold matches the brief.
- test_haiku_fallback_helper_is_async_callable: helper exists and is async.
- test_record_defer_creates_row_and_returns_count: DB persistence of the
  consecutive-defer counter.
- test_record_defer_increments_on_repeated_call: same match_key called twice
  → consecutive_count = 2.
- test_clear_defer_removes_row: clearing the counter for a match_key works.
- test_premium_tier_intercept_decision_silver_bronze_skip: simulation —
  Silver+Bronze polish failures DO fall back to W82 (existing behaviour).
- test_premium_tier_intercept_decision_diamond_gold_intercept: simulation —
  Diamond+Gold polish failures trigger the intercept branch.
"""
from __future__ import annotations

import asyncio
import os
import sys
import sqlite3
import tempfile
import types

import pytest


@pytest.fixture(autouse=True)
def _patch_heavy_imports(monkeypatch):
    """Stub heavy imports that pregenerate_narratives pulls in at module level."""
    for mod_name in ("anthropic", "sentry_sdk"):
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, types.ModuleType(mod_name))


# ── Constants ───────────────────────────────────────────────────────────────


def test_premium_defer_alert_chat_id_locked() -> None:
    """The EdgeOps alert chat is the exact value from the brief —
    -1003877525865 (changing it requires a brief amendment + ops sign-off)."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import pregenerate_narratives as pgn

    assert pgn._PREMIUM_DEFER_ALERT_CHAT_ID == -1003877525865


def test_premium_defer_alert_threshold_is_3() -> None:
    """3 consecutive defers triggers the EdgeOps alert per the brief."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import pregenerate_narratives as pgn

    assert pgn._PREMIUM_DEFER_ALERT_THRESHOLD == 3


# ── Helper signatures ───────────────────────────────────────────────────────


def test_haiku_fallback_helper_is_async_callable() -> None:
    """`_attempt_haiku_polish_fallback` is the canonical Haiku polish entry —
    must be importable and async (the polish-block awaits it)."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import pregenerate_narratives as pgn

    assert hasattr(pgn, "_attempt_haiku_polish_fallback")
    assert asyncio.iscoroutinefunction(pgn._attempt_haiku_polish_fallback)


def test_record_and_clear_defer_helpers_exist() -> None:
    """`_record_premium_defer` and `_clear_premium_defer` are the canonical
    persistence helpers for the consecutive-defer counter."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import pregenerate_narratives as pgn

    assert callable(pgn._record_premium_defer)
    assert callable(pgn._clear_premium_defer)


# ── Defer counter persistence (DB-level) ────────────────────────────────────


def _temp_mzansi_db_dir() -> tempfile.TemporaryDirectory:
    """Spawn a temp directory housing a stub `data/mzansiedge.db`. The defer
    helpers compute the DB path via `os.path.dirname(__file__)/../data/mzansiedge.db`,
    so we need to monkey-patch the script's __file__ for isolation. Easier to
    simply place a pre-created DB at the canonical bot path under a tmp HOME.
    """
    return tempfile.TemporaryDirectory()


def test_record_defer_creates_row_and_returns_count_one(monkeypatch, tmp_path) -> None:
    """First call for a match_key returns count 1 and creates the row."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import pregenerate_narratives as pgn

    # Redirect the script's __file__ to a tmp dir so the "../data/mzansiedge.db"
    # resolution lands in tmp_path/data/.
    fake_scripts_dir = tmp_path / "scripts"
    fake_data_dir = tmp_path / "data"
    fake_scripts_dir.mkdir()
    fake_data_dir.mkdir()
    fake_script = fake_scripts_dir / "pregenerate_narratives.py"
    fake_script.write_text("# stub")
    monkeypatch.setattr(pgn, "__file__", str(fake_script))

    count = pgn._record_premium_defer(
        match_key="arsenal_vs_chelsea_2026-05-01",
        edge_tier="diamond",
        fixture="Arsenal vs Chelsea",
        pick="home",
        reason="haiku_fallback_failed",
        log=pgn.log,
    )

    assert count == 1
    db_path = fake_data_dir / "mzansiedge.db"
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT match_key, edge_tier, consecutive_count FROM gold_verdict_failed_edges"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "arsenal_vs_chelsea_2026-05-01"
    assert rows[0][1] == "diamond"
    assert rows[0][2] == 1


def test_record_defer_increments_on_repeated_call(monkeypatch, tmp_path) -> None:
    """Second call for the same match_key increments consecutive_count to 2."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import pregenerate_narratives as pgn

    fake_scripts_dir = tmp_path / "scripts"
    fake_data_dir = tmp_path / "data"
    fake_scripts_dir.mkdir()
    fake_data_dir.mkdir()
    fake_script = fake_scripts_dir / "pregenerate_narratives.py"
    fake_script.write_text("# stub")
    monkeypatch.setattr(pgn, "__file__", str(fake_script))

    pgn._record_premium_defer("liv_vs_city_2026-05-02", "gold", "Liv vs City", "home", "x", pgn.log)
    second = pgn._record_premium_defer("liv_vs_city_2026-05-02", "gold", "Liv vs City", "home", "y", pgn.log)
    third = pgn._record_premium_defer("liv_vs_city_2026-05-02", "gold", "Liv vs City", "home", "z", pgn.log)

    assert second == 2
    assert third == 3  # crosses _PREMIUM_DEFER_ALERT_THRESHOLD


def test_clear_defer_removes_row(monkeypatch, tmp_path) -> None:
    """`_clear_premium_defer` removes the row so subsequent defer counts start at 1."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import pregenerate_narratives as pgn

    fake_scripts_dir = tmp_path / "scripts"
    fake_data_dir = tmp_path / "data"
    fake_scripts_dir.mkdir()
    fake_data_dir.mkdir()
    fake_script = fake_scripts_dir / "pregenerate_narratives.py"
    fake_script.write_text("# stub")
    monkeypatch.setattr(pgn, "__file__", str(fake_script))

    pgn._record_premium_defer("psg_vs_marseille_2026-05-03", "diamond", "PSG vs Marseille", "home", "x", pgn.log)
    pgn._record_premium_defer("psg_vs_marseille_2026-05-03", "diamond", "PSG vs Marseille", "home", "y", pgn.log)
    pgn._clear_premium_defer("psg_vs_marseille_2026-05-03", pgn.log)
    after_clear = pgn._record_premium_defer("psg_vs_marseille_2026-05-03", "diamond", "PSG vs Marseille", "home", "z", pgn.log)

    assert after_clear == 1


# ── Tier-aware decision tree (simulation) ──────────────────────────────────


def _premium_intercept_decision(narrative_source: str, tier: str,
                                is_non_edge: bool, skip_w84: bool) -> bool:
    """Mirror the conditional that wraps the premium intercept block in
    `_generate_one()`. Tests document the policy without invoking the full
    async function.
    """
    return (
        narrative_source in ("w82", "baseline_no_edge")
        and tier.lower() in ("gold", "diamond")
        and not is_non_edge
        and not skip_w84
    )


def test_premium_tier_intercept_silver_bronze_skip() -> None:
    """Silver and Bronze polish failures DO NOT trigger the premium intercept —
    they keep the existing W82 fallback path per W93-TIER-GATE cost policy."""
    assert _premium_intercept_decision("w82", "silver", False, False) is False
    assert _premium_intercept_decision("w82", "bronze", False, False) is False
    assert _premium_intercept_decision("baseline_no_edge", "silver", False, False) is False
    assert _premium_intercept_decision("baseline_no_edge", "bronze", False, False) is False


def test_premium_tier_intercept_diamond_gold_fires() -> None:
    """Diamond and Gold polish failures DO trigger the premium intercept —
    Haiku fallback + defer instead of silent W82 write."""
    assert _premium_intercept_decision("w82", "diamond", False, False) is True
    assert _premium_intercept_decision("w82", "gold", False, False) is True
    assert _premium_intercept_decision("baseline_no_edge", "diamond", False, False) is True
    # Case-insensitive tier lookup defends against caller variation.
    assert _premium_intercept_decision("w82", "Diamond", False, False) is True
    assert _premium_intercept_decision("w82", "GOLD", False, False) is True


def test_premium_tier_intercept_skipped_when_polish_was_skipped() -> None:
    """Premium intercept ONLY fires when polish was attempted. If `_skip_w84`
    is True (e.g. coverage-gate denied polish, W93-TIER-GATE denied tier), the
    W82 baseline IS the legitimate output — defer would be wrong here."""
    assert _premium_intercept_decision("w82", "diamond", False, True) is False
    assert _premium_intercept_decision("w82", "gold", False, True) is False


def test_premium_tier_intercept_skipped_for_non_edge_preview() -> None:
    """Non-edge match previews use Haiku as PRIMARY (not fallback). Premium
    intercept is for edge-polish failures only."""
    assert _premium_intercept_decision("w82", "diamond", True, False) is False
    assert _premium_intercept_decision("w82", "gold", True, False) is False


def test_premium_tier_intercept_w84_success_does_not_trigger() -> None:
    """When polish succeeded (narrative_source = "w84" or w84-haiku-fallback),
    the intercept does NOT fire — there's nothing to recover from."""
    assert _premium_intercept_decision("w84", "diamond", False, False) is False
    assert _premium_intercept_decision("w84_quality_retry", "diamond", False, False) is False
    assert _premium_intercept_decision("w84-haiku-fallback", "diamond", False, False) is False
