from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest


def _create_alerts_edge_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE edge_results (
                edge_id TEXT PRIMARY KEY,
                match_key TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                bet_type TEXT NOT NULL,
                recommended_odds REAL NOT NULL,
                bookmaker TEXT NOT NULL,
                predicted_ev REAL NOT NULL,
                league TEXT NOT NULL,
                match_date TEXT NOT NULL,
                recommended_at TEXT NOT NULL,
                composite_score REAL NOT NULL,
                confirming_signals INTEGER,
                result TEXT,
                posted_to_alerts_direct INTEGER DEFAULT 0,
                posted_to_alerts_direct_claimed_at TEXT,
                posted_to_alerts_direct_claim_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO edge_results (
                edge_id, match_key, edge_tier, bet_type, recommended_odds,
                bookmaker, predicted_ev, league, match_date, recommended_at,
                composite_score, confirming_signals, result, posted_to_alerts_direct
            )
            VALUES (
                'edge_contract_alerts_dedup_01',
                'contract_home_vs_contract_away_2026-05-17',
                'gold',
                'Home Win',
                1.95,
                'playabets',
                0.08,
                'epl',
                date('now', '+1 day'),
                datetime('now'),
                87.5,
                4,
                NULL,
                0
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_alerts_send_log_has_edge_channel_version_unique_index(tmp_path):
    import bot_lib.alerts_direct as alerts_direct

    conn = sqlite3.connect(str(tmp_path / "odds.db"))
    try:
        alerts_direct._ensure_alerts_send_log_schema(conn)
        schema = "\n".join(
            row[0]
            for row in conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name IN ("
                "'alerts_send_log', "
                "'uix_alerts_send_log_edge_channel_version'"
                ") "
                "ORDER BY type, name"
            ).fetchall()
            if row[0]
        )
    finally:
        conn.close()

    assert "channel" in schema
    assert "status" in schema
    assert "row_version" in schema
    assert "CREATE UNIQUE INDEX uix_alerts_send_log_edge_channel_version" in schema
    assert "ON alerts_send_log(edge_id, channel, row_version)" in schema


def _patch_tier_fire_job(monkeypatch, db_path: str, sends: list[str]) -> None:
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
                "display_tier": "gold",
                "edge_tier": "gold",
            }
        ],
    )

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        sends.append(edge_id)
        await asyncio.sleep(0.05)
        return f"https://t.me/c/3789410835/{len(sends)}"

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)


@pytest.mark.asyncio
async def test_tier_fire_alerts_job_claims_before_send(monkeypatch, tmp_path):
    """Two rapid scheduler calls for one edge_id must produce exactly one send."""
    import bot

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    sends: list[str] = []
    _patch_tier_fire_job(monkeypatch, db_path, sends)

    ctx = SimpleNamespace()
    await asyncio.gather(
        bot._tier_fire_alerts_job(ctx),
        bot._tier_fire_alerts_job(ctx),
    )

    assert sends == ["edge_contract_alerts_dedup_01"]
    conn = sqlite3.connect(db_path)
    try:
        posted_state = conn.execute(
            "SELECT posted_to_alerts_direct FROM edge_results WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert posted_state == 1


@pytest.mark.asyncio
async def test_tier_fire_alerts_job_reclaims_stale_claim(monkeypatch, tmp_path):
    import bot

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE edge_results "
            "SET posted_to_alerts_direct = 0, "
            "posted_to_alerts_direct_claimed_at = datetime('now', '-11 minutes'), "
            "posted_to_alerts_direct_claim_id = 'old-owner'"
        )
        conn.commit()
    finally:
        conn.close()

    sends: list[str] = []
    _patch_tier_fire_job(monkeypatch, db_path, sends)
    await bot._tier_fire_alerts_job(SimpleNamespace())

    assert sends == ["edge_contract_alerts_dedup_01"]


@pytest.mark.asyncio
async def test_stale_claim_owner_cannot_release_reclaimed_edge(monkeypatch, tmp_path):
    import bot

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE edge_results "
            "SET posted_to_alerts_direct = 0, "
            "posted_to_alerts_direct_claimed_at = datetime('now', '-11 minutes'), "
            "posted_to_alerts_direct_claim_id = 'old-owner'"
        )
        conn.commit()
    finally:
        conn.close()

    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
                "display_tier": "gold",
                "edge_tier": "gold",
            }
        ],
    )

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        bot._db_write_retry(
            "UPDATE edge_results SET posted_to_alerts_direct = 0, "
            "posted_to_alerts_direct_claimed_at = NULL, "
            "posted_to_alerts_direct_claim_id = NULL "
            "WHERE edge_id = ? AND posted_to_alerts_direct = 0 "
            "AND posted_to_alerts_direct_claim_id = ?",
            (edge_id, "old-owner"),
            db_path=db_path,
        )
        return "https://t.me/c/3789410835/1"

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    await bot._tier_fire_alerts_job(SimpleNamespace())

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT posted_to_alerts_direct, posted_to_alerts_direct_claim_id "
            "FROM edge_results WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == (1, None)


@pytest.mark.asyncio
async def test_tier_fire_claim_keeps_posted_flag_boolean_visible(monkeypatch, tmp_path):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
            }
        ],
    )

    observed: list[tuple[int, bool]] = []

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT posted_to_alerts_direct, posted_to_alerts_direct_claim_id "
                "FROM edge_results WHERE edge_id = ?",
                (edge_id,),
            ).fetchone()
        finally:
            conn.close()
        observed.append((row[0], bool(row[1])))
        return "https://t.me/c/3789410835/1"

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    await bot._tier_fire_alerts_job(SimpleNamespace())

    assert observed == [(0, True)]


@pytest.mark.asyncio
async def test_tier_fire_ambiguous_send_keeps_claim_fenced(monkeypatch, tmp_path):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
            }
        ],
    )

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        return alerts_direct.ALERTS_SEND_UNKNOWN

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    await bot._tier_fire_alerts_job(SimpleNamespace())

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT posted_to_alerts_direct, posted_to_alerts_direct_claim_id "
            "FROM edge_results WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 0
    assert row[1]


@pytest.mark.asyncio
async def test_tier_fire_alerts_job_processes_diamond_and_dms(monkeypatch, tmp_path):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE edge_results SET edge_tier = 'diamond'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
                "display_tier": "diamond",
                "edge_tier": "diamond",
            }
        ],
    )

    sends: list[str] = []
    dms: list[str] = []

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        sends.append(edge_id)
        return "https://t.me/c/3789410835/1"

    async def fake_fire_diamond_edge_dms(
        ctx, tip, match_key, edge_id="", row_version=""
    ):
        dms.append(match_key)
        return True

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    monkeypatch.setattr(bot, "_fire_diamond_edge_dms", fake_fire_diamond_edge_dms)

    await bot._tier_fire_alerts_job(SimpleNamespace())

    assert sends == ["edge_contract_alerts_dedup_01"]
    assert dms == ["contract_home_vs_contract_away_2026-05-17"]


@pytest.mark.asyncio
async def test_diamond_retry_existing_channel_send_fires_missing_dms(
    monkeypatch,
    tmp_path,
):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE edge_results SET edge_tier = 'diamond'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
                "display_tier": "diamond",
                "edge_tier": "diamond",
            }
        ],
    )

    dms: list[str] = []

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        return alerts_direct.AlertsSendResult(
            "https://t.me/c/3789410835/1",
            new_send=False,
        )

    async def fake_fire_diamond_edge_dms(
        ctx, tip, match_key, edge_id="", row_version=""
    ):
        dms.append(match_key)
        return True

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    monkeypatch.setattr(bot, "_fire_diamond_edge_dms", fake_fire_diamond_edge_dms)

    await bot._tier_fire_alerts_job(SimpleNamespace())

    assert dms == ["contract_home_vs_contract_away_2026-05-17"]


@pytest.mark.asyncio
async def test_fire_diamond_edge_dms_skips_users_already_logged(
    monkeypatch,
    tmp_path,
):
    import sys
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setitem(
        sys.modules,
        "card_pipeline",
        SimpleNamespace(
            render_card_bytes=lambda *args, **kwargs: (b"png", None, None)
        ),
    )

    async def fake_diamond_users():
        return [101, 202]

    async def fake_can_send(user_id):
        return True

    after_send: list[int] = []

    async def fake_after_send(user_id):
        after_send.append(user_id)

    monkeypatch.setattr(bot.db, "get_active_diamond_users", fake_diamond_users)
    monkeypatch.setattr(bot, "_can_send_notification", fake_can_send)
    monkeypatch.setattr(bot, "_after_send", fake_after_send)

    row_version = "2026-05-06T08:00:00|diamond|Home Win|1.95|playabets|0.08"
    assert bot._reserve_tier_fire_diamond_dm_sync(
        "edge_contract_alerts_dedup_01",
        row_version,
        101,
    )
    assert bot._touch_tier_fire_diamond_dm_sync(
        "edge_contract_alerts_dedup_01",
        row_version,
        101,
    )
    bot._mark_tier_fire_diamond_dm_sent_sync(
        "edge_contract_alerts_dedup_01",
        row_version,
        101,
    )

    sent_users: list[int] = []

    class FakeTelegramBot:
        async def send_photo(self, chat_id, photo, reply_markup=None):
            sent_users.append(chat_id)

    ctx = SimpleNamespace(bot=FakeTelegramBot())
    assert await bot._fire_diamond_edge_dms(
        ctx,
        {"match_key": "contract_home_vs_contract_away_2026-05-17"},
        "contract_home_vs_contract_away_2026-05-17",
        "edge_contract_alerts_dedup_01",
        row_version,
    )
    assert await bot._fire_diamond_edge_dms(
        ctx,
        {"match_key": "contract_home_vs_contract_away_2026-05-17"},
        "contract_home_vs_contract_away_2026-05-17",
        "edge_contract_alerts_dedup_01",
        row_version,
    )

    assert sent_users == [202]
    assert after_send == [202]
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT user_id, status FROM alerts_diamond_dm_log "
            "WHERE edge_id = ? AND row_version = ? ORDER BY user_id",
            ("edge_contract_alerts_dedup_01", row_version),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(101, "sent"), (202, "sent")]


@pytest.mark.asyncio
async def test_fire_diamond_edge_dms_does_not_retry_stale_posting_dm(
    monkeypatch,
    tmp_path,
):
    import sys
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setitem(
        sys.modules,
        "card_pipeline",
        SimpleNamespace(
            render_card_bytes=lambda *args, **kwargs: (b"png", None, None)
        ),
    )

    async def fake_diamond_users():
        return [101]

    async def fake_can_send(user_id):
        return True

    async def fake_after_send(user_id):
        return None

    monkeypatch.setattr(bot.db, "get_active_diamond_users", fake_diamond_users)
    monkeypatch.setattr(bot, "_can_send_notification", fake_can_send)
    monkeypatch.setattr(bot, "_after_send", fake_after_send)

    original_mark_sent = bot._mark_tier_fire_diamond_dm_sent_sync
    monkeypatch.setattr(
        bot,
        "_mark_tier_fire_diamond_dm_sent_sync",
        lambda *args, **kwargs: False,
    )

    sent_users: list[int] = []

    class FakeTelegramBot:
        async def send_photo(self, chat_id, photo, reply_markup=None):
            sent_users.append(chat_id)

    row_version = "2026-05-06T08:00:00|diamond|Home Win|1.95|playabets|0.08"
    ctx = SimpleNamespace(bot=FakeTelegramBot())
    assert await bot._fire_diamond_edge_dms(
        ctx,
        {"match_key": "contract_home_vs_contract_away_2026-05-17"},
        "contract_home_vs_contract_away_2026-05-17",
        "edge_contract_alerts_dedup_01",
        row_version,
    )
    assert sent_users == [101]

    monkeypatch.setattr(bot, "_mark_tier_fire_diamond_dm_sent_sync", original_mark_sent)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE alerts_diamond_dm_log SET sent_at = ? WHERE edge_id = ?",
            (
                time.time() - bot._TIER_FIRE_DIAMOND_DM_STALE_SECONDS - 1,
                "edge_contract_alerts_dedup_01",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert not await bot._fire_diamond_edge_dms(
        ctx,
        {"match_key": "contract_home_vs_contract_away_2026-05-17"},
        "contract_home_vs_contract_away_2026-05-17",
        "edge_contract_alerts_dedup_01",
        row_version,
    )
    assert sent_users == [101]
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM alerts_diamond_dm_log WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("unknown",)


@pytest.mark.asyncio
async def test_fire_diamond_edge_dms_releases_retryable_send_exception(
    monkeypatch,
    tmp_path,
):
    import sys
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setitem(
        sys.modules,
        "card_pipeline",
        SimpleNamespace(
            render_card_bytes=lambda *args, **kwargs: (b"png", None, None)
        ),
    )

    async def fake_diamond_users():
        return [101]

    async def fake_can_send(user_id):
        return True

    monkeypatch.setattr(bot.db, "get_active_diamond_users", fake_diamond_users)
    monkeypatch.setattr(bot, "_can_send_notification", fake_can_send)

    class FailingTelegramBot:
        async def send_photo(self, chat_id, photo, reply_markup=None):
            raise RuntimeError("network before accepted response")

    row_version = "2026-05-06T08:00:00|diamond|Home Win|1.95|playabets|0.08"
    ctx = SimpleNamespace(bot=FailingTelegramBot())
    assert not await bot._fire_diamond_edge_dms(
        ctx,
        {"match_key": "contract_home_vs_contract_away_2026-05-17"},
        "contract_home_vs_contract_away_2026-05-17",
        "edge_contract_alerts_dedup_01",
        row_version,
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM alerts_diamond_dm_log WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == (0,)


@pytest.mark.asyncio
async def test_diamond_dm_retryable_failure_leaves_edge_unposted(
    monkeypatch,
    tmp_path,
):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE edge_results SET edge_tier = 'diamond'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
                "display_tier": "diamond",
                "edge_tier": "diamond",
            }
        ],
    )

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        return alerts_direct.AlertsSendResult(
            "https://t.me/c/3789410835/1",
            new_send=True,
        )

    async def fake_fire_diamond_edge_dms(
        ctx, tip, match_key, edge_id="", row_version=""
    ):
        return False

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    monkeypatch.setattr(bot, "_fire_diamond_edge_dms", fake_fire_diamond_edge_dms)

    await bot._tier_fire_alerts_job(SimpleNamespace())

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT posted_to_alerts_direct, posted_to_alerts_direct_claim_id "
            "FROM edge_results WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == (0, None)


@pytest.mark.asyncio
async def test_final_mark_revalidates_sent_row_version(monkeypatch, tmp_path):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
            }
        ],
    )

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE edge_results SET recommended_odds = 2.15, "
                "bookmaker = 'betway', predicted_ev = 0.12"
            )
            conn.commit()
        finally:
            conn.close()
        return alerts_direct.AlertsSendResult(
            "https://t.me/c/3789410835/1",
            new_send=True,
        )

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    await bot._tier_fire_alerts_job(SimpleNamespace())

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT posted_to_alerts_direct, posted_to_alerts_direct_claim_id "
            "FROM edge_results WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == (0, None)


@pytest.mark.asyncio
async def test_diamond_new_channel_send_dms_even_when_mark_race_loses(
    monkeypatch,
    tmp_path,
):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE edge_results SET edge_tier = 'diamond'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)
    monkeypatch.setattr(
        bot,
        "_load_tips_from_edge_results",
        lambda limit=50, skip_punt_filter=True: [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
                "display_tier": "diamond",
                "edge_tier": "diamond",
            }
        ],
    )

    dms: list[str] = []

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("UPDATE edge_results SET bet_type = 'Away Win'")
            conn.commit()
        finally:
            conn.close()
        return alerts_direct.AlertsSendResult(
            "https://t.me/c/3789410835/1",
            new_send=True,
        )

    async def fake_fire_diamond_edge_dms(
        ctx, tip, match_key, edge_id="", row_version=""
    ):
        dms.append(match_key)
        return True

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)
    monkeypatch.setattr(bot, "_fire_diamond_edge_dms", fake_fire_diamond_edge_dms)

    await bot._tier_fire_alerts_job(SimpleNamespace())

    assert dms == ["contract_home_vs_contract_away_2026-05-17"]


@pytest.mark.asyncio
async def test_tier_fire_alerts_claim_revalidates_current_row(monkeypatch, tmp_path):
    import bot
    import bot_lib.alerts_direct as alerts_direct
    import scrapers.edge.edge_config as edge_config

    db_path = str(tmp_path / "odds.db")
    _create_alerts_edge_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", db_path)

    def settle_after_select(limit=50, skip_punt_filter=True):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE edge_results SET result = 'hit' WHERE edge_id = ?",
                ("edge_contract_alerts_dedup_01",),
            )
            conn.commit()
        finally:
            conn.close()
        return [
            {
                "match_id": "contract_home_vs_contract_away_2026-05-17",
                "match_key": "contract_home_vs_contract_away_2026-05-17",
            }
        ]

    sends: list[str] = []

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        sends.append(edge_id)
        return "https://t.me/c/3789410835/1"

    monkeypatch.setattr(bot, "_load_tips_from_edge_results", settle_after_select)
    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)

    await bot._tier_fire_alerts_job(SimpleNamespace())

    assert sends == []


@pytest.mark.asyncio
async def test_post_to_alerts_reserves_send_log_before_send(monkeypatch, tmp_path):
    import bot_lib.alerts_direct as alerts_direct

    db_path = str(tmp_path / "odds.db")
    monkeypatch.setenv("ALERTS_SEND_LOG_DB_PATH", db_path)
    monkeypatch.setenv("TELEGRAM_PUBLISHER_BOT_TOKEN", "test-token")
    monkeypatch.setattr(alerts_direct, "_sync_render_card", lambda tip: b"png")
    monkeypatch.setattr(alerts_direct, "_emit_latency_event", lambda *args, **kwargs: None)

    post_calls: list[str] = []

    def fake_post_sync(token, png_bytes, caption, reply_markup):
        post_calls.append(reply_markup["inline_keyboard"][0][0]["url"])
        time.sleep(0.05)
        return f"https://t.me/c/3789410835/{len(post_calls)}"

    monkeypatch.setattr(alerts_direct, "_post_sync", fake_post_sync)

    tip = {
        "match_key": "contract_home_vs_contract_away_2026-05-17",
        "display_tier": "gold",
    }
    results = await asyncio.gather(
        alerts_direct.post_to_alerts(tip, "edge_contract_alerts_dedup_01"),
        alerts_direct.post_to_alerts(tip, "edge_contract_alerts_dedup_01"),
    )

    assert len(post_calls) == 1
    assert results.count(None) == 1
    assert [r for r in results if r] == ["https://t.me/c/3789410835/1"]

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(status), MAX(msg_url) FROM alerts_send_log "
            "WHERE edge_id = ? AND channel = 'alerts'",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == (1, "sent", "https://t.me/c/3789410835/1")


def test_alerts_send_log_dedupes_per_edge_row_version(monkeypatch, tmp_path):
    import bot_lib.alerts_direct as alerts_direct

    db_path = str(tmp_path / "odds.db")
    monkeypatch.setenv("ALERTS_SEND_LOG_DB_PATH", db_path)

    acquired, existing_url, first_id = alerts_direct._reserve_send_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
        "version-1",
    )
    assert (acquired, existing_url) == (True, None)
    assert alerts_direct._touch_send_reservation_sync(
        "edge_contract_alerts_dedup_01",
        first_id,
    )
    alerts_direct._finalize_send_log_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
        123,
        "https://t.me/c/3789410835/1",
        first_id,
    )

    acquired, existing_url, duplicate_id = alerts_direct._reserve_send_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
        "version-1",
    )
    assert acquired is False
    assert existing_url == "https://t.me/c/3789410835/1"
    assert duplicate_id is None

    acquired, existing_url, second_id = alerts_direct._reserve_send_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
        "version-2",
    )
    assert (acquired, existing_url) == (True, None)
    assert second_id != first_id

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT row_version, status FROM alerts_send_log "
            "WHERE edge_id = ? ORDER BY row_version",
            ("edge_contract_alerts_dedup_01",),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("version-1", "sent"), ("version-2", "sending")]


def test_stale_send_log_owner_cannot_release_or_finalize_reclaimed_reservation(
    monkeypatch,
    tmp_path,
):
    import bot_lib.alerts_direct as alerts_direct

    db_path = str(tmp_path / "odds.db")
    monkeypatch.setenv("ALERTS_SEND_LOG_DB_PATH", db_path)

    acquired, existing_url, old_id = alerts_direct._reserve_send_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
    )
    assert (acquired, existing_url) == (True, None)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE alerts_send_log SET sent_at = ? WHERE id = ?",
            (time.time() - alerts_direct._SEND_RESERVATION_STALE_SECONDS - 1, old_id),
        )
        conn.commit()
    finally:
        conn.close()

    acquired, existing_url, new_id = alerts_direct._reserve_send_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
    )
    assert (acquired, existing_url) == (True, None)
    assert new_id != old_id

    assert alerts_direct._touch_send_reservation_sync(
        "edge_contract_alerts_dedup_01",
        old_id,
    ) is False
    assert alerts_direct._touch_send_reservation_sync(
        "edge_contract_alerts_dedup_01",
        new_id,
    ) is True
    alerts_direct._release_send_reservation_sync(
        "edge_contract_alerts_dedup_01",
        old_id,
    )
    alerts_direct._finalize_send_log_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
        123,
        "https://t.me/c/3789410835/old",
        old_id,
    )
    alerts_direct._finalize_send_log_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
        456,
        "https://t.me/c/3789410835/new",
        new_id,
    )

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, status, msg_url FROM alerts_send_log WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(new_id, "sent", "https://t.me/c/3789410835/new")]


def test_stale_posting_reservation_becomes_unknown_not_retried(monkeypatch, tmp_path):
    import bot_lib.alerts_direct as alerts_direct

    db_path = str(tmp_path / "odds.db")
    monkeypatch.setenv("ALERTS_SEND_LOG_DB_PATH", db_path)

    acquired, existing_url, reservation_id = alerts_direct._reserve_send_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
    )
    assert (acquired, existing_url) == (True, None)
    assert alerts_direct._touch_send_reservation_sync(
        "edge_contract_alerts_dedup_01",
        reservation_id,
    ) is True

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE alerts_send_log SET sent_at = ? WHERE id = ?",
            (time.time() - alerts_direct._SEND_RESERVATION_STALE_SECONDS - 1, reservation_id),
        )
        conn.commit()
    finally:
        conn.close()

    acquired, existing_url, new_id = alerts_direct._reserve_send_sync(
        "edge_contract_alerts_dedup_01",
        "contract_home_vs_contract_away_2026-05-17",
        "gold",
    )

    assert acquired is False
    assert existing_url == alerts_direct.ALERTS_SEND_UNKNOWN
    assert new_id is None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, status FROM alerts_send_log WHERE edge_id = ?",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == (reservation_id, "unknown")


@pytest.mark.asyncio
async def test_post_to_alerts_keeps_unknown_reservation_on_ambiguous_send(
    monkeypatch,
    tmp_path,
):
    import bot_lib.alerts_direct as alerts_direct

    db_path = str(tmp_path / "odds.db")
    monkeypatch.setenv("ALERTS_SEND_LOG_DB_PATH", db_path)
    monkeypatch.setenv("TELEGRAM_PUBLISHER_BOT_TOKEN", "test-token")
    monkeypatch.setattr(alerts_direct, "_sync_render_card", lambda tip: b"png")
    monkeypatch.setattr(alerts_direct, "_emit_latency_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        alerts_direct,
        "_post_sync",
        lambda token, png_bytes, caption, reply_markup: alerts_direct.ALERTS_SEND_UNKNOWN,
    )

    result = await alerts_direct.post_to_alerts(
        {"match_key": "contract_home_vs_contract_away_2026-05-17"},
        "edge_contract_alerts_dedup_01",
    )

    assert result == alerts_direct.ALERTS_SEND_UNKNOWN
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM alerts_send_log WHERE edge_id = ? AND channel = 'alerts'",
            ("edge_contract_alerts_dedup_01",),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("unknown",)


def test_post_sync_classifies_known_no_send_failures(monkeypatch):
    import requests
    import bot_lib.alerts_direct as alerts_direct

    def read_timeout(*args, **kwargs):
        raise requests.exceptions.ReadTimeout("response lost")

    monkeypatch.setattr(requests, "post", read_timeout)
    assert (
        alerts_direct._post_sync("token", b"png", "", {"inline_keyboard": []})
        == alerts_direct.ALERTS_SEND_UNKNOWN
    )

    def connect_timeout(*args, **kwargs):
        raise requests.exceptions.ConnectTimeout("not sent")

    monkeypatch.setattr(requests, "post", connect_timeout)
    assert alerts_direct._post_sync("token", b"png", "", {"inline_keyboard": []}) is None

    def connection_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("ambiguous disconnect")

    monkeypatch.setattr(requests, "post", connection_error)
    assert (
        alerts_direct._post_sync("token", b"png", "", {"inline_keyboard": []})
        == alerts_direct.ALERTS_SEND_UNKNOWN
    )

    class RejectedResponse:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("401")

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: RejectedResponse())
    assert alerts_direct._post_sync("token", b"png", "", {"inline_keyboard": []}) is None


@pytest.mark.asyncio
async def test_post_to_alerts_aborts_if_reservation_lost_before_send(
    monkeypatch,
    tmp_path,
):
    import bot_lib.alerts_direct as alerts_direct

    db_path = str(tmp_path / "odds.db")
    monkeypatch.setenv("ALERTS_SEND_LOG_DB_PATH", db_path)
    monkeypatch.setenv("TELEGRAM_PUBLISHER_BOT_TOKEN", "test-token")
    monkeypatch.setattr(alerts_direct, "_emit_latency_event", lambda *args, **kwargs: None)

    def render_and_steal_reservation(tip):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "DELETE FROM alerts_send_log "
                "WHERE edge_id = ? AND channel = 'alerts' AND status = 'sending'",
                ("edge_contract_alerts_dedup_01",),
            )
            conn.commit()
        finally:
            conn.close()
        return b"png"

    post_calls: list[str] = []

    def fake_post_sync(token, png_bytes, caption, reply_markup):
        post_calls.append("called")
        return "https://t.me/c/3789410835/1"

    monkeypatch.setattr(alerts_direct, "_sync_render_card", render_and_steal_reservation)
    monkeypatch.setattr(alerts_direct, "_post_sync", fake_post_sync)

    result = await alerts_direct.post_to_alerts(
        {"match_key": "contract_home_vs_contract_away_2026-05-17"},
        "edge_contract_alerts_dedup_01",
    )

    assert result is None
    assert post_calls == []
