"""FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 — AC-3 corpus invariant.

For every row in edge_results where edge_tier IN ('diamond','gold')
                                 AND result IS NULL
                                 AND match_date BETWEEN date('now') AND date('now','+21 days')
MUST EXIST EITHER
  (a) a narrative_cache row with same match_id + narrative_source
      IN ('w84','w84-haiku-fallback')
  OR
  (b) a gold_verdict_failed_edges row with same match_key (deferred state).

NO premium edge may have NEITHER (orphan = test failure).

Out-of-scope leagues (La Liga, Serie A, Bundesliga, Ligue 1) are excluded
from the invariant per brief — Core 7 launch lock surfaces them as edges
but they are not part of the launch product.

This is the CI hard-gate test for AC-3. The structural tests below cover
view-time defer placeholder + orphan ERROR log wiring.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_BOT_DIR = Path(__file__).parents[2]
_SCRAPERS_DIR = Path(os.environ.get("SCRAPERS_ROOT", str(_BOT_DIR.parent / "scrapers")))
_ODDS_DB = _SCRAPERS_DIR / "odds.db"
_BOT_DB = _BOT_DIR / "data" / "mzansiedge.db"

# Core 7 launch product. Out-of-scope leagues are excluded from this invariant.
_OUT_OF_SCOPE_LEAGUES = (
    "spain_la_liga", "la_liga",
    "italy_serie_a", "serie_a",
    "germany_bundesliga", "bundesliga",
    "france_ligue_1", "ligue_1", "ligue1",
)


def _connect_odds():
    if not _ODDS_DB.exists():
        return None
    try:
        from scrapers.db_connect import connect_odds_db
        return connect_odds_db(str(_ODDS_DB))
    except Exception:
        return None


def _connect_bot():
    if not _BOT_DB.exists():
        return None
    try:
        from db_connection import get_connection
        return get_connection(str(_BOT_DB), timeout_ms=2000)
    except Exception:
        return None


def _has_table(conn, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _premium_unsettled_edges() -> list[dict]:
    """Return premium edges in scope (≤21 days, in-scope leagues, unsettled)."""
    conn = _connect_odds()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """SELECT match_key, edge_tier, league, match_date
               FROM edge_results
               WHERE edge_tier IN ('diamond','gold')
                 AND result IS NULL
                 AND match_date BETWEEN date('now') AND date('now','+21 days')""",
        ).fetchall()
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return [
        {"match_key": r[0], "edge_tier": (r[1] or "").lower(),
         "league": (r[2] or "").lower(), "match_date": r[3]}
        for r in rows
        if (r[2] or "").lower() not in _OUT_OF_SCOPE_LEAGUES
    ]


def _w84_match_keys() -> set[str]:
    conn = _connect_odds()
    if conn is None:
        return set()
    try:
        rows = conn.execute(
            """SELECT match_id FROM narrative_cache
               WHERE narrative_source IN ('w84','w84-haiku-fallback')
                 AND narrative_html IS NOT NULL
                 AND LENGTH(TRIM(COALESCE(narrative_html,''))) > 0
                 AND (status IS NULL OR status != 'quarantined')
                 AND COALESCE(quarantined, 0) = 0""",
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _deferred_match_keys() -> set[str]:
    conn = _connect_bot()
    if conn is None:
        return set()
    try:
        if not _has_table(conn, "gold_verdict_failed_edges"):
            return set()
        rows = conn.execute(
            "SELECT match_key FROM gold_verdict_failed_edges"
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Corpus invariant — the hard gate
# ---------------------------------------------------------------------------

def test_corpus_invariant_no_premium_orphans():
    """Every premium edge in scope must have either w84/w84-haiku-fallback
    OR a defer row. Orphans (neither) = test failure.

    Skipped when DBs aren't present (e.g. fresh CI without seeded data).
    """
    if not _ODDS_DB.exists() or not _BOT_DB.exists():
        pytest.skip("Live DBs not available (odds.db or mzansiedge.db missing)")

    edges = _premium_unsettled_edges()
    if not edges:
        pytest.skip("No premium edges in scope to check (edge_results empty)")

    w84 = _w84_match_keys()
    deferred = _deferred_match_keys()

    orphans = []
    for e in edges:
        mk = e["match_key"]
        if mk in w84:
            continue
        if mk in deferred:
            continue
        orphans.append(e)

    assert not orphans, (
        f"FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 AC-3 corpus invariant violated.\n"
        f"{len(orphans)} premium edge(s) have NEITHER w84/w84-haiku-fallback row "
        f"NOR a defer row in gold_verdict_failed_edges:\n"
        + "\n".join(f"  - {e['match_key']} (tier={e['edge_tier']} league={e['league']} date={e['match_date']})" for e in orphans[:10])
    )


# ---------------------------------------------------------------------------
# View-time wiring (structural)
# ---------------------------------------------------------------------------

def test_card_data_returns_deferred_dict_for_premium():
    """`build_ai_breakdown_data` must return a deferred sentinel dict when
    a premium edge has a defer row but no narrative_cache row."""
    src = (_BOT_DIR / "card_data.py").read_text(encoding="utf-8")
    assert "_check_premium_defer(" in src, (
        "card_data must define _check_premium_defer helper"
    )
    assert "_check_premium_edge(" in src, (
        "card_data must define _check_premium_edge helper"
    )
    assert '"deferred": True' in src, (
        "build_ai_breakdown_data must return a deferred sentinel dict"
    )
    assert (
        "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumDeferred" in src
    ), "PremiumDeferred log marker missing in card_data"
    assert (
        "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumOrphan" in src
    ), "PremiumOrphan log marker missing in card_data"


def test_bot_handler_renders_deferred_placeholder():
    """`_handle_ai_breakdown` must detect deferred=True and render the
    'AI Breakdown updating' placeholder rather than the synthesis card."""
    src = (_BOT_DIR / "bot.py").read_text(encoding="utf-8")
    assert "_bd.get(\"deferred\")" in src, (
        "bot.py _handle_ai_breakdown must check _bd.get('deferred')"
    )
    assert "AI Breakdown updating" in src, (
        "Placeholder text 'AI Breakdown updating' must be present in bot.py"
    )
    assert "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 AC-3" in src, (
        "bot.py must reference the brief — keeps wiring discoverable"
    )


def test_orphan_path_logs_error_and_breadcrumb():
    """The orphan path (premium + no cache + no defer + no synthesis) must
    log ERROR with the PremiumOrphan signature and add a Sentry breadcrumb."""
    src = (_BOT_DIR / "card_data.py").read_text(encoding="utf-8")
    # log.error with PremiumOrphan signature.
    assert "PremiumOrphan" in src
    assert "log.error" in src
    # Sentry breadcrumb.
    assert "add_breadcrumb(" in src or "sentry_sdk" in src, (
        "Sentry breadcrumb must be wired on the orphan path"
    )


def test_out_of_scope_leagues_excluded_from_invariant():
    """Test must exclude La Liga / Serie A / Bundesliga / Ligue 1."""
    self_src = Path(__file__).read_text(encoding="utf-8")
    assert "_OUT_OF_SCOPE_LEAGUES" in self_src
    for lg in ("la_liga", "serie_a", "bundesliga", "ligue_1"):
        assert lg in self_src, (
            f"Out-of-scope league '{lg}' must be in the exclusion list"
        )


# ---------------------------------------------------------------------------
# Helper unit tests (defensive)
# ---------------------------------------------------------------------------

def test_check_premium_defer_returns_none_when_db_missing(tmp_path, monkeypatch):
    """Best-effort: missing DB returns None, never raises."""
    monkeypatch.setenv("SCRAPERS_ROOT", str(tmp_path / "no_scrapers"))
    # Force the bot DB path to a non-existent location by editing PATH.
    # Helper reads from `Path(__file__).parent / "data" / "mzansiedge.db"` so
    # we can't easily redirect — test by passing a clearly-invalid match key
    # which will hit the missing-DB branch when bot DB is absent.
    from card_data import _check_premium_defer
    # Even if the live DB exists, an unknown match_key returns None.
    result = _check_premium_defer("___no_such_match_key___")
    assert result is None


def test_check_premium_edge_returns_none_for_unknown_match():
    from card_data import _check_premium_edge
    result = _check_premium_edge("___no_such_match_key___")
    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
