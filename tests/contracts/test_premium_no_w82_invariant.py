"""FIX-W84-PREMIUM-NO-FALLBACK-CLOSE-SAFETY-NET-01 — regression guard.

The Wave 2 chain (Rule 23) is the canonical no-fallback architecture for
premium tiers (Diamond + Gold): Sonnet retry → Haiku-narrative fallback →
defer with EdgeOps alert. The writer-level refusal at
``bot.py::_store_narrative_cache`` is the second-layer enforcement covering
bypass paths the Wave 2 chain doesn't intercept:

* ``_skip_w84`` carve-out in ``pregenerate_narratives._generate_one`` (PARTIAL
  coverage with ``_coverage_level == "empty"`` for Gold/Diamond, or
  ``edge.skip_sonnet_polish`` flag) — the chain sees ``not _skip_w84`` and
  skips the intercept entirely; ``_cache`` is built and the writer is invoked.
* ``_is_non_edge`` carve-out — non-edge premium-tier previews bypass the
  intercept by design.
* The bot serve-time persist path at
  ``bot.py::_generate_game_tips::_persist_narrative_bg`` invokes
  ``_store_narrative_cache(..., model="sonnet")`` without overriding the
  ``narrative_source="w82"`` default — the live-tap baseline lands in the
  cache labelled with the W82 source string.

Synthesis-on-tap (Rule 20) covers the resulting cache miss.
``_has_any_cached_narrative`` returns True whenever ``edge_results`` has the
match, and ``card_data._synthesize_breakdown_row_from_baseline`` produces a
fresh baseline at view time. Silver and Bronze tier W82-write path is
byte-identical pre/post (W93-TIER-GATE cost policy unchanged).

Tests:

1. ``test_corpus_invariant_no_premium_w82_rows`` — corpus-level scan against
   live ``narrative_cache``: zero rows where ``narrative_source = 'w82'`` AND
   ``edge_tier IN ('diamond', 'gold')``.
2. ``test_writer_refuses_gold_w82`` — Gold tier + ``narrative_source='w82'``
   → no row persisted (AC-5(a)).
3. ``test_writer_refuses_diamond_baseline_no_edge`` — Diamond +
   ``baseline_no_edge`` → no row persisted (AC-5(b)).
4. ``test_writer_persists_silver_w82_unchanged`` — Silver + W82 → row
   persisted as before (AC-5(c) tier-scope guard).
5. ``test_writer_persists_diamond_w84_unchanged`` — Diamond + W84 → row
   persisted (positive control: refusal is source-scoped, not tier-only).
6. ``test_writer_persists_gold_haiku_fallback_unchanged`` — Gold +
   ``w84-haiku-fallback`` → row persisted (Wave 2 success path is not
   blocked by the writer refusal).
7. ``test_brief_log_marker_present_in_writer`` — source-level check: the
   ``FIX-W84-PREMIUM-NO-FALLBACK-CLOSE-SAFETY-NET-01 PremiumW82WriteRefused``
   log line is present in ``_store_narrative_cache``. Monitoring + AC-9
   journalctl grep both depend on this exact string.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the worktree root is importable for ``bot`` (no installed package).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_BOT_PY = _ROOT / "bot.py"

# The live odds.db carries the narrative_cache table; resolved at test time so
# the suite runs against the same DB the bot service writes to.
_LIVE_ODDS_DB = Path(os.environ.get("ODDS_DB_PATH", "/home/paulsportsza/scrapers/odds.db"))


# ── 1. Corpus-level invariant against the live narrative_cache ────────────────


def test_corpus_invariant_no_premium_w82_rows():
    """AC-5 corpus invariant: zero non-expired premium-tier W82 rows.

    Skipped when the live odds.db isn't on disk (CI without the production
    artefact). The brief AC-7 verifies the same query post-deploy + cache
    flush; this test is the durable regression guard.
    """
    if not _LIVE_ODDS_DB.exists():
        pytest.skip(f"live narrative_cache DB not present at {_LIVE_ODDS_DB}")

    conn = sqlite3.connect(f"file:{_LIVE_ODDS_DB}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT count(*) FROM narrative_cache "
            "WHERE narrative_source IN ('w82', 'baseline_no_edge') "
            "AND edge_tier IN ('diamond', 'gold') "
            "AND datetime(expires_at) > datetime('now')"
        ).fetchone()
    finally:
        conn.close()

    premium_w82_rows = row[0] if row else 0
    if premium_w82_rows:
        # Surface the offending rows so a failing CI run is debuggable
        # without re-querying the DB by hand.
        conn = sqlite3.connect(f"file:{_LIVE_ODDS_DB}?mode=ro", uri=True)
        try:
            offenders = conn.execute(
                "SELECT match_id, narrative_source, edge_tier, "
                "datetime(created_at), datetime(expires_at) "
                "FROM narrative_cache "
                "WHERE narrative_source IN ('w82', 'baseline_no_edge') "
                "AND edge_tier IN ('diamond', 'gold') "
                "AND datetime(expires_at) > datetime('now') "
                "ORDER BY created_at DESC LIMIT 25"
            ).fetchall()
        finally:
            conn.close()
        pytest.fail(
            f"Corpus invariant violated: {premium_w82_rows} premium-tier "
            f"W82 / baseline_no_edge rows present in narrative_cache. "
            f"FIX-W84-PREMIUM-NO-FALLBACK-CLOSE-SAFETY-NET-01 writer-level "
            f"refusal is the second-layer enforcement — re-introducing the "
            f"safety-net write reopens the regression. Sample offenders:\n  "
            + "\n  ".join(repr(o) for o in offenders[:10])
        )


# ── 2-6. Writer behaviour under the refusal ───────────────────────────────────


def _build_in_memory_narrative_db(tmp_path: Path) -> Path:
    """Create a minimal narrative_cache table for isolated writer tests.

    The live schema enforces a CHECK constraint on verdict_html length but
    permits NULL; using NULL keeps the test fixture lean.
    """
    db_path = tmp_path / "narrative_cache_test.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # Mirror the production schema fields the writer touches. Column list
        # matches the INSERT OR REPLACE in `_store_narrative_cache::_store`.
        conn.execute(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                narrative_html TEXT,
                model TEXT,
                edge_tier TEXT,
                tips_json TEXT,
                odds_hash TEXT,
                evidence_json TEXT,
                narrative_source TEXT,
                coverage_json TEXT,
                created_at TEXT,
                expires_at TEXT,
                structured_card_json TEXT,
                verdict_html TEXT CHECK (verdict_html IS NULL OR LENGTH(verdict_html) BETWEEN 1 AND 260),
                evidence_class TEXT,
                tone_band TEXT,
                spec_json TEXT,
                context_json TEXT,
                generation_ms INTEGER,
                setup_validated INTEGER,
                verdict_validated INTEGER,
                setup_attempts INTEGER,
                verdict_attempts INTEGER,
                status TEXT,
                quarantine_reason TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _import_bot_writer(test_db_path: Path):
    """Import the live ``_store_narrative_cache`` against an isolated DB.

    bot.py's startup pulls in Sentry, PTB and a few async modules. We patch
    the module-level DB path before any test invokes the writer — the writer
    re-reads ``_NARRATIVE_DB_PATH`` from module scope on every call.
    """
    import bot as _bot

    _bot._NARRATIVE_DB_PATH = str(test_db_path)
    return _bot._store_narrative_cache


def _row_count(db_path: Path, match_id: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT count(*) FROM narrative_cache WHERE match_id = ?",
            (match_id,),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _stub_compute_odds_hash(*_args, **_kwargs):
    """`_compute_odds_hash` queries odds.db; stub for isolated DB tests."""
    return "stub_odds_hash"


@pytest.mark.parametrize("source", ["w82", "baseline_no_edge"])
@pytest.mark.parametrize("tier", ["gold", "diamond"])
def test_writer_refuses_premium_w82_and_baseline_no_edge(tmp_path, source, tier):
    """AC-5 (a) + (b): premium tier + W82-class source → no row persisted.

    Parametrised over both ``narrative_source`` values the refusal must catch
    (``w82`` and ``baseline_no_edge``) and both premium tier strings (Gold,
    Diamond). The matrix is the brief's tier-scoped refusal contract.
    """
    db_path = _build_in_memory_narrative_db(tmp_path)
    store = _import_bot_writer(db_path)

    match_id = f"home_vs_away_2026-05-01_{source}_{tier}"

    with patch("bot._compute_odds_hash", _stub_compute_odds_hash):
        asyncio.run(
            store(
                match_id=match_id,
                html="<p>Premium polish failure baseline</p>",
                tips=[{"outcome": "home", "bookie": "betway", "odds": 2.10}],
                edge_tier=tier,
                model="sonnet",
                narrative_source=source,
            )
        )

    assert _row_count(db_path, match_id) == 0, (
        f"Writer persisted a premium-tier ({tier}) {source} row — refusal "
        f"failed. Expected zero rows for match_id={match_id!r}."
    )


def test_writer_persists_silver_w82_unchanged(tmp_path):
    """AC-5 (c) + AC-14: Silver + W82 → row persisted.

    Tier-scope guard: the refusal must NOT regress Silver/Bronze persistence.
    W93-TIER-GATE cost policy keeps Silver/Bronze on the W82 baseline path.
    """
    db_path = _build_in_memory_narrative_db(tmp_path)
    store = _import_bot_writer(db_path)

    match_id = "silver_home_vs_silver_away_2026-05-01"

    with patch("bot._compute_odds_hash", _stub_compute_odds_hash):
        asyncio.run(
            store(
                match_id=match_id,
                html="<p>Silver baseline narrative</p>",
                tips=[{"outcome": "home", "bookie": "betway", "odds": 1.85}],
                edge_tier="silver",
                model="baseline",
                narrative_source="w82",
            )
        )

    assert _row_count(db_path, match_id) == 1, (
        "Silver + W82 row was NOT persisted — refusal leaked into "
        "non-premium tier. AC-14 requires byte-identical Silver/Bronze "
        "writer behaviour pre/post."
    )


def test_writer_persists_bronze_baseline_no_edge_unchanged(tmp_path):
    """AC-14 belt-and-suspenders: Bronze + baseline_no_edge → row persisted."""
    db_path = _build_in_memory_narrative_db(tmp_path)
    store = _import_bot_writer(db_path)

    match_id = "bronze_home_vs_bronze_away_2026-05-02"

    with patch("bot._compute_odds_hash", _stub_compute_odds_hash):
        asyncio.run(
            store(
                match_id=match_id,
                html="<p>Bronze non-edge preview</p>",
                tips=[{"outcome": "home", "bookie": "betway", "odds": 2.30}],
                edge_tier="bronze",
                model="haiku",
                narrative_source="baseline_no_edge",
            )
        )

    assert _row_count(db_path, match_id) == 1, (
        "Bronze + baseline_no_edge row was NOT persisted — refusal leaked "
        "into non-premium tier."
    )


def test_writer_persists_diamond_w84_unchanged(tmp_path):
    """Positive control: refusal is source-scoped (W82/baseline_no_edge) only.

    Diamond + W84 happy path must continue to persist.
    """
    db_path = _build_in_memory_narrative_db(tmp_path)
    store = _import_bot_writer(db_path)

    match_id = "diamond_home_vs_diamond_away_w84_2026-05-03"

    with patch("bot._compute_odds_hash", _stub_compute_odds_hash):
        asyncio.run(
            store(
                match_id=match_id,
                html="<p>Diamond W84 polished narrative</p>",
                tips=[{"outcome": "home", "bookie": "betway", "odds": 1.65}],
                edge_tier="diamond",
                model="sonnet",
                narrative_source="w84",
            )
        )

    assert _row_count(db_path, match_id) == 1, (
        "Diamond + W84 row was NOT persisted — refusal scope leaked "
        "beyond W82/baseline_no_edge sources."
    )


def test_writer_persists_gold_haiku_fallback_unchanged(tmp_path):
    """Wave 2 chain success path: Gold + w84-haiku-fallback → row persisted.

    Confirms the writer-level refusal does NOT block Wave 2's Haiku fallback
    output. Rule 23: ``narrative_source = "w84-haiku-fallback"`` is the
    canonical sentinel for premium Haiku-fallback rows and surfaces in
    monitoring dashboards.
    """
    db_path = _build_in_memory_narrative_db(tmp_path)
    store = _import_bot_writer(db_path)

    match_id = "gold_home_vs_gold_away_haiku_2026-05-04"

    with patch("bot._compute_odds_hash", _stub_compute_odds_hash):
        asyncio.run(
            store(
                match_id=match_id,
                html="<p>Gold W84 Haiku fallback narrative</p>",
                tips=[{"outcome": "home", "bookie": "betway", "odds": 1.95}],
                edge_tier="gold",
                model="haiku",
                narrative_source="w84-haiku-fallback",
            )
        )

    assert _row_count(db_path, match_id) == 1, (
        "Gold + w84-haiku-fallback row was NOT persisted — refusal leaked "
        "into Wave 2 chain success path. Rule 23 chain output must always "
        "land in cache."
    )


# ── 7. Source-level: brief log marker present ─────────────────────────────────


def test_brief_log_marker_present_in_writer():
    """Source-level: the brief's exact log marker is present in the writer.

    AC-9 corpus-delta verification greps journalctl for
    ``PremiumW82WriteRefused`` post-deploy. Monitoring depends on this
    string being byte-identical to the brief.
    """
    src = _BOT_PY.read_text()
    fn_start = src.index("async def _store_narrative_cache(")
    fn_end = src.index("\nasync def _store_narrative_evidence", fn_start)
    fn_body = src[fn_start:fn_end]

    assert (
        "FIX-W84-PREMIUM-NO-FALLBACK-CLOSE-SAFETY-NET-01 PremiumW82WriteRefused"
        in fn_body
    ), (
        "Writer-level refusal log marker missing or renamed. Monitoring + "
        "AC-9 journalctl grep both depend on this exact string. Do NOT "
        "rename without coordinating with EdgeOps."
    )

    # The conditional must early-return — the refusal is what makes the
    # marker semantically meaningful.
    cond_idx = fn_body.index('if _wg_src in ("w82", "baseline_no_edge")')
    line_start = fn_body.rfind("\n", 0, cond_idx) + 1
    if_line = fn_body[line_start: fn_body.index("\n", cond_idx)]
    if_indent = len(if_line) - len(if_line.lstrip())

    block_lines: list[str] = []
    cursor = fn_body.index("\n", cond_idx) + 1
    while cursor < len(fn_body):
        next_nl = fn_body.find("\n", cursor)
        if next_nl == -1:
            block_lines.append(fn_body[cursor:])
            break
        line = fn_body[cursor:next_nl]
        cursor = next_nl + 1
        if not line.strip():
            block_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= if_indent:
            break
        block_lines.append(line)

    block_body = "\n".join(block_lines)
    has_return = any(
        l.split("#", 1)[0].strip().startswith("return") for l in block_lines
    )
    assert has_return, (
        "Writer-level refusal block does NOT contain an early `return`. "
        "Without the return the refusal is logging-only and the W82 row "
        "still gets persisted by the `_store()` body below. Block was:\n"
        f"---\n{block_body}\n---"
    )
