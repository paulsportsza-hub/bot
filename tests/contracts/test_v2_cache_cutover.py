from __future__ import annotations

import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import audit_v2_cache as audit_script
from scripts.audit_v2_cache import audit_database, format_metrics


ROOT = Path(__file__).resolve().parents[2]


def _slice_between(source: str, start: str, end: str) -> str:
    start_idx = source.index(start)
    end_idx = source.index(end, start_idx)
    return source[start_idx:end_idx]


def test_cache_schema_writes_and_reads_are_version_aware() -> None:
    src = (ROOT / "bot.py").read_text(encoding="utf-8")

    ensure_block = _slice_between(
        src,
        "def _ensure_narrative_cache_table()",
        "# PIPELINE-BUILD-01: indexes",
    )
    assert "ALTER TABLE narrative_cache ADD COLUMN engine_version TEXT" in ensure_block
    assert "duplicate column" in ensure_block

    verdict_reader = _slice_between(
        src,
        "def _get_cached_verdict(match_key: str)",
        "def _is_verdict_stale",
    )
    assert "AND engine_version = ?" in verdict_reader
    assert "_verdict_engine_v2_enabled()" in verdict_reader
    assert "COALESCE(quarantined, 0)" in verdict_reader

    narrative_reader = _slice_between(
        src,
        "async def _get_cached_narrative(match_id: str)",
        "async def _store_narrative_cache(",
    )
    assert "AND engine_version = ?" in narrative_reader
    assert "COALESCE(quarantined, 0) = 0" in narrative_reader
    assert "quality_status NOT IN ('quarantined', 'skipped_banned_shape')" in narrative_reader

    warm_cache_probe = _slice_between(
        src,
        "def _count_uncached_hot_tips(",
        "_precompute_lock = asyncio.Lock()",
    )
    assert "_verdict_engine_v2_enabled()" in warm_cache_probe
    assert "AND engine_version = ?" in warm_cache_probe
    assert "COALESCE(quarantined, 0) = 0" in warm_cache_probe
    assert "quality_status NOT IN ('quarantined', 'skipped_banned_shape')" in warm_cache_probe

    narrative_writer = _slice_between(
        src,
        "async def _store_narrative_cache(",
        "async def _delete_narrative_cache",
    )
    assert "engine_version: str | None = None" in narrative_writer
    assert "quality_status, engine_version" in narrative_writer
    assert "SELECT verdict_html FROM narrative_cache" in narrative_writer
    assert "engine_version = None" in narrative_writer

    verdict_writer = _slice_between(
        src,
        "def _store_verdict_cache_sync(",
        "async def _store_narrative_evidence",
    )
    assert "engine_version: str | None = None" in verdict_writer
    assert "engine_version = ?" in verdict_writer
    assert "write_engine_version" in verdict_writer
    assert "_existing_has_narrative" in verdict_writer
    assert "tips_json = ?" in verdict_writer
    assert "odds_hash = ?" in verdict_writer
    assert "created_at = ?" in verdict_writer
    assert "expires_at = ?" in verdict_writer
    assert "VALUES (?, '', ?, 'view-time'" in verdict_writer

    odds_hash = _slice_between(
        src,
        "def _compute_odds_hash(match_id: str)",
        "# ── TIER-FIX C",
    )
    assert "stable_rows = [tuple(row) for row in rows]" in odds_hash


def test_cached_verdict_read_filter_respects_v2_flag(tmp_path: Path, monkeypatch) -> None:
    import bot

    db_path = tmp_path / "odds.db"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                evidence_class TEXT,
                tone_band TEXT,
                odds_hash TEXT,
                created_at TEXT,
                expires_at TEXT,
                tips_json TEXT,
                quality_status TEXT,
                status TEXT,
                quarantined INTEGER,
                engine_version TEXT
            );
            """
        )
        rows = [
            ("legacy_match", "Legacy verdict", None, None, None, 0),
            ("v2_match", "V2 verdict", "v2_microfact", None, None, 0),
            ("v2_quality_quarantined", "Bad V2 verdict", "v2_microfact", "quarantined", None, 0),
            ("v2_status_quarantined", "Bad V2 verdict", "v2_microfact", None, "quarantined", 0),
            ("v2_flag_quarantined", "Bad V2 verdict", "v2_microfact", None, None, 1),
        ]
        for match_id, verdict, engine_version, quality_status, status, quarantined in rows:
            conn.execute(
                """
                INSERT INTO narrative_cache
                VALUES (?, ?, 'class', 'tone', 'hash', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    verdict,
                    now.isoformat(),
                    expires.isoformat(),
                    '[{"bookmaker":"Betway","odds":1.85,"ev":4.2}]',
                    quality_status,
                    status,
                    quarantined,
                    engine_version,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(bot, "_NARRATIVE_DB_PATH", str(db_path))

    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")
    assert bot._get_cached_verdict("legacy_match") is None
    assert bot._get_cached_verdict("v2_match")["verdict_html"] == "V2 verdict"
    assert bot._get_cached_verdict("v2_quality_quarantined") is None
    assert bot._get_cached_verdict("v2_status_quarantined") is None
    assert bot._get_cached_verdict("v2_flag_quarantined") is None

    monkeypatch.setenv("VERDICT_ENGINE_V2", "0")
    assert bot._get_cached_verdict("legacy_match")["verdict_html"] == "Legacy verdict"
    assert bot._get_cached_verdict("v2_match")["verdict_html"] == "V2 verdict"
    assert bot._get_cached_verdict("v2_quality_quarantined") is None
    assert bot._get_cached_verdict("v2_status_quarantined") is None
    assert bot._get_cached_verdict("v2_flag_quarantined") is None


def test_cached_narrative_v2_does_not_drop_quarantine_gates_on_old_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import bot

    db_path = tmp_path / "odds.db"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                narrative_html TEXT NOT NULL,
                model TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                tips_json TEXT NOT NULL,
                odds_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                evidence_json TEXT,
                narrative_source TEXT,
                coverage_json TEXT,
                created_at TEXT,
                quality_status TEXT,
                status TEXT,
                engine_version TEXT,
                verdict_html TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO narrative_cache VALUES (?, ?, 'w82', 'silver', ?, 'hash', ?, NULL, 'w82', NULL, ?, NULL, 'quarantined', 'v2_microfact', NULL)
            """,
            (
                "liverpool_vs_chelsea_2026-06-20",
                "<b>The Setup</b> Liverpool hold the cleaner profile. <b>The Edge</b> The price still works. <b>The Risk</b> Rotation can move this late.",
                '[{"bookmaker":"Betway","odds":1.85,"ev":4.2}]',
                expires.isoformat(),
                now.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(bot, "_NARRATIVE_DB_PATH", str(db_path))
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")

    assert asyncio.run(
        bot._get_cached_narrative("liverpool_vs_chelsea_2026-06-20")
    ) is None


def test_verdict_write_does_not_clear_quarantined_narrative_row(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import bot

    db_path = tmp_path / "odds.db"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                narrative_html TEXT NOT NULL,
                model TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                tips_json TEXT NOT NULL,
                odds_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                evidence_json TEXT,
                narrative_source TEXT,
                coverage_json TEXT,
                created_at TEXT,
                quality_status TEXT,
                status TEXT,
                quarantined INTEGER DEFAULT 0,
                engine_version TEXT,
                verdict_html TEXT,
                evidence_class TEXT,
                tone_band TEXT
            );
            CREATE TABLE odds_latest (
                match_id TEXT,
                bookmaker TEXT,
                home_odds REAL,
                draw_odds REAL,
                away_odds REAL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO narrative_cache VALUES (?, ?, 'w82', 'silver', ?, 'hash', ?, NULL, 'w82', NULL, ?, 'quarantined', NULL, 0, 'v2_microfact', 'Old bad verdict.', NULL, NULL)
            """,
            (
                "liverpool_vs_chelsea_2026-06-20",
                "<b>The Setup</b> Liverpool hold the cleaner profile. <b>The Edge</b> The price still works. <b>The Risk</b> Rotation can move this late.",
                '[{"bookmaker":"Betway","odds":1.85,"ev":4.2}]',
                expires.isoformat(),
                now.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(bot, "_NARRATIVE_DB_PATH", str(db_path))
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")

    bot._store_verdict_cache_sync(
        "liverpool_vs_chelsea_2026-06-20",
        "Liverpool at 1.96 with Betway — price support is clear. Back Liverpool, standard stake.",
        {"edge_tier": "silver", "bookmaker": "Betway", "odds": 1.96, "ev": 4.2},
        engine_version="v2_microfact",
    )

    conn = sqlite3.connect(db_path)
    try:
        quality_status, verdict_html = conn.execute(
            "SELECT quality_status, verdict_html FROM narrative_cache WHERE match_id = ?",
            ("liverpool_vs_chelsea_2026-06-20",),
        ).fetchone()
    finally:
        conn.close()
    assert quality_status == "quarantined"
    assert "Back Liverpool" in verdict_html
    assert bot._get_cached_verdict("liverpool_vs_chelsea_2026-06-20") is None
    assert asyncio.run(
        bot._get_cached_narrative("liverpool_vs_chelsea_2026-06-20")
    ) is None


def test_audit_v2_cache_metrics_pass_clean_15_row_slate(tmp_path: Path) -> None:
    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                engine_version TEXT,
                tips_json TEXT,
                odds_hash TEXT,
                quality_status TEXT,
                status TEXT,
                quarantined INTEGER,
                created_at TEXT,
                expires_at TEXT
            );
            CREATE TABLE edge_results (
                match_key TEXT,
                sport TEXT,
                league TEXT,
                bet_type TEXT,
                result TEXT,
                match_date TEXT
            );
            """
        )
        for idx in range(15):
            match_id = f"team_{idx}_vs_opponent_{idx}_2026-05-{idx + 10:02d}"
            # FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01: clean fixture is
            # single-mention (team appears once in close, distinct lead per row).
            verdict = f"opportunity {idx} still looks playable here — back Team {idx}, standard stake."
            conn.execute(
                "INSERT INTO narrative_cache VALUES (?, ?, 'v2_microfact', ?, ?, '', '', 0, ?, ?)",
                (
                    match_id,
                    verdict,
                    '[{"bookmaker":"Betway","odds":1.85}]',
                    f"hash-{idx}",
                    datetime.now(timezone.utc).isoformat(),
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                ),
            )
            conn.execute(
                "INSERT INTO edge_results VALUES (?, 'soccer', 'epl', 'Home Win', NULL, ?)",
                (match_id, f"2026-05-{idx + 10:02d}"),
            )
        conn.commit()
    finally:
        conn.close()

    metrics = audit_database(str(db_path))

    assert metrics["total rows regenerated"] == 15
    assert metrics["invalid verdict count"] == 0
    assert metrics["team-integrity failure count"] == 0
    assert metrics["banned term count"] == 0
    assert metrics["distinct primary clause count"] == 15
    assert "```markdown" in format_metrics(metrics)


def test_audit_v2_cache_catches_wrong_recommended_side(tmp_path: Path) -> None:
    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                engine_version TEXT,
                tips_json TEXT,
                odds_hash TEXT,
                quality_status TEXT,
                status TEXT,
                quarantined INTEGER,
                created_at TEXT,
                expires_at TEXT
            );
            CREATE TABLE edge_results (
                match_key TEXT,
                sport TEXT,
                league TEXT,
                bet_type TEXT,
                result TEXT,
                match_date TEXT
            );
            """
        )
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO narrative_cache VALUES (?, ?, 'v2_microfact', ?, 'hash', '', '', 0, ?, ?)",
            (
                "delhi_capitals_vs_chennai_super_kings_2026-05-09",
                "Delhi Capitals at 2.05 with Betway — back Delhi Capitals, standard stake.",
                '[{"bookmaker":"Betway","odds":2.05}]',
                now.isoformat(),
                (now + timedelta(hours=1)).isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO edge_results VALUES (?, 'cricket', 'ipl', 'Away Win', NULL, '2026-05-09')",
            ("delhi_capitals_vs_chennai_super_kings_2026-05-09",),
        )
        conn.commit()
    finally:
        conn.close()

    metrics = audit_database(str(db_path))

    assert metrics["team-integrity failure count"] == 1
    assert metrics["invalid verdict count"] == 1


def test_audit_v2_cache_catches_delhi_chennai_sunrisers_leak(tmp_path: Path) -> None:
    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                engine_version TEXT,
                tips_json TEXT,
                odds_hash TEXT,
                quality_status TEXT,
                status TEXT,
                quarantined INTEGER,
                created_at TEXT,
                expires_at TEXT
            );
            CREATE TABLE edge_results (
                match_key TEXT,
                sport TEXT,
                league TEXT,
                bet_type TEXT,
                result TEXT,
                match_date TEXT
            );
            """
        )
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO narrative_cache VALUES (?, ?, 'v2_microfact', ?, 'hash', '', '', 0, ?, ?)",
            (
                "delhi_capitals_vs_chennai_super_kings_2026-05-09",
                "Sunrisers Hyderabad still look playable — back Chennai, standard stake.",
                '[{"bookmaker":"Betway","odds":2.05}]',
                now.isoformat(),
                (now + timedelta(hours=1)).isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO edge_results VALUES (?, 'cricket', 'ipl', 'Away Win', NULL, '2026-05-09')",
            ("delhi_capitals_vs_chennai_super_kings_2026-05-09",),
        )
        conn.commit()
    finally:
        conn.close()

    metrics = audit_database(str(db_path))

    assert metrics["team-integrity failure count"] == 1


def test_audit_v2_cache_allows_sunrisers_hyderabad_home_team() -> None:
    hits = audit_script._third_team_mentions(
        "Sunrisers Hyderabad win at 2.05 with Betway — back Sunrisers Hyderabad, standard stake.",
        "sunrisers_hyderabad_vs_delhi_capitals_2026-05-09",
    )

    assert hits == []


def test_audit_v2_cache_catches_quarantine_and_odds_drift(tmp_path: Path) -> None:
    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                engine_version TEXT,
                tips_json TEXT,
                odds_hash TEXT,
                quality_status TEXT,
                status TEXT,
                quarantined INTEGER,
                created_at TEXT,
                expires_at TEXT
            );
            CREATE TABLE edge_results (
                match_key TEXT,
                sport TEXT,
                league TEXT,
                bet_type TEXT,
                result TEXT,
                match_date TEXT
            );
            CREATE TABLE odds_latest (
                match_id TEXT,
                bookmaker TEXT,
                home_odds REAL,
                draw_odds REAL,
                away_odds REAL
            );
            """
        )
        now = datetime.now(timezone.utc)
        for idx, (quality_status, status, quarantined) in enumerate((
            ("", "", 0),
            ("quarantined", "", 0),
            ("", "quarantined", 0),
            ("", "", 1),
        )):
            match_id = f"team_{idx}_vs_opponent_{idx}_2026-05-{idx + 10:02d}"
            conn.execute(
                "INSERT INTO narrative_cache VALUES (?, ?, 'v2_microfact', ?, ?, ?, ?, ?, ?, ?)",
                (
                    match_id,
                    f"Team {idx} price has support — back Team {idx}, standard stake.",
                    '[{"bookmaker":"Betway","odds":1.85}]',
                    "stale-hash",
                    quality_status,
                    status,
                    quarantined,
                    now.isoformat(),
                    (now + timedelta(hours=1)).isoformat(),
                ),
            )
            conn.execute(
                "INSERT INTO edge_results VALUES (?, 'soccer', 'epl', 'Home Win', NULL, ?)",
                (match_id, f"2026-05-{idx + 10:02d}"),
            )
            conn.execute(
                "INSERT INTO odds_latest VALUES (?, 'Betway', 1.85, 3.20, 4.10)",
                (match_id,),
            )
        conn.commit()
    finally:
        conn.close()

    metrics = audit_database(str(db_path))

    assert metrics["invalid verdict count"] == 4


def test_audit_v2_cache_uses_latest_unsettled_edge_row(tmp_path: Path) -> None:
    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                engine_version TEXT,
                tips_json TEXT,
                odds_hash TEXT,
                quality_status TEXT,
                status TEXT,
                created_at TEXT,
                expires_at TEXT
            );
            CREATE TABLE edge_results (
                id INTEGER,
                match_key TEXT,
                sport TEXT,
                league TEXT,
                bet_type TEXT,
                result TEXT,
                match_date TEXT,
                recommended_at TEXT
            );
            """
        )
        match_id = "team_0_vs_opponent_0_2026-05-10"
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO narrative_cache VALUES (?, ?, 'v2_microfact', ?, 'hash', '', '', ?, ?)",
            (
                match_id,
                "Team 0 price has support — back Team 0, standard stake.",
                '[{"bookmaker":"Betway","odds":1.85}]',
                now.isoformat(),
                (now + timedelta(hours=1)).isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO edge_results VALUES (1, ?, 'soccer', 'epl', 'Away Win', NULL, '2026-05-10', '2026-05-06T00:00:00Z')",
            (match_id,),
        )
        conn.execute(
            "INSERT INTO edge_results VALUES (2, ?, 'soccer', 'epl', 'Home Win', NULL, '2026-05-10', '2026-05-06T01:00:00Z')",
            (match_id,),
        )
        conn.commit()
    finally:
        conn.close()

    metrics = audit_database(str(db_path))

    assert metrics["total rows regenerated"] == 1
    assert metrics["team-integrity failure count"] == 0


def test_audit_v2_cache_main_fails_on_duplicates_even_with_15_distinct(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                engine_version TEXT
            );
            CREATE TABLE edge_results (
                match_key TEXT,
                sport TEXT,
                league TEXT,
                bet_type TEXT,
                result TEXT,
                match_date TEXT
            );
            """
        )
        for idx in range(16):
            team_idx = 0 if idx < 2 else idx
            match_id = f"team_{team_idx}_vs_opponent_{idx}_2026-05-{idx + 10:02d}"
            verdict = f"Team {team_idx} price has support — back Team {team_idx}, standard stake."
            conn.execute(
                "INSERT INTO narrative_cache VALUES (?, ?, 'v2_microfact')",
                (match_id, verdict),
            )
            conn.execute(
                "INSERT INTO edge_results VALUES (?, 'soccer', 'epl', 'Home Win', NULL, ?)",
                (match_id, f"2026-05-{idx + 10:02d}"),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(sys, "argv", ["audit_v2_cache.py", "--db", str(db_path)])

    metrics = audit_database(str(db_path))
    assert metrics["distinct primary clause count"] == 15
    assert metrics["duplicate verdict count"] == 1
    assert audit_script.main() == 1


def test_audit_v2_cache_main_fails_on_fallback_shell(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT,
                engine_version TEXT
            );
            CREATE TABLE edge_results (
                match_key TEXT,
                sport TEXT,
                league TEXT,
                bet_type TEXT,
                result TEXT,
                match_date TEXT
            );
            """
        )
        for idx in range(15):
            match_id = f"team_{idx}_vs_opponent_{idx}_2026-05-{idx + 10:02d}"
            if idx == 0:
                verdict = "Team 0 at 1.85 with Betway — back Team 0, standard stake."
            else:
                verdict = f"Team {idx} price has support — back Team {idx}, standard stake."
            conn.execute(
                "INSERT INTO narrative_cache VALUES (?, ?, 'v2_microfact')",
                (match_id, verdict),
            )
            conn.execute(
                "INSERT INTO edge_results VALUES (?, 'soccer', 'epl', 'Home Win', NULL, ?)",
                (match_id, f"2026-05-{idx + 10:02d}"),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(sys, "argv", ["audit_v2_cache.py", "--db", str(db_path)])

    metrics = audit_database(str(db_path))
    assert metrics["fallback shell count"] == 1
    assert metrics["distinct primary clause count"] == 15
    assert audit_script.main() == 1
