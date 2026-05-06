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
                posted_to_alerts_direct_claimed_at TEXT
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


def test_alerts_send_log_has_edge_channel_unique_index(tmp_path):
    import bot_lib.alerts_direct as alerts_direct

    conn = sqlite3.connect(str(tmp_path / "odds.db"))
    try:
        alerts_direct._ensure_alerts_send_log_schema(conn)
        schema = "\n".join(
            row[0]
            for row in conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name IN ('alerts_send_log', 'uix_alerts_send_log_edge_channel') "
                "ORDER BY type, name"
            ).fetchall()
            if row[0]
        )
    finally:
        conn.close()

    assert "channel" in schema
    assert "status" in schema
    assert "CREATE UNIQUE INDEX uix_alerts_send_log_edge_channel" in schema
    assert "ON alerts_send_log(edge_id, channel)" in schema


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
            "SET posted_to_alerts_direct = -1, "
            "posted_to_alerts_direct_claimed_at = datetime('now', '-11 minutes')"
        )
        conn.commit()
    finally:
        conn.close()

    sends: list[str] = []
    _patch_tier_fire_job(monkeypatch, db_path, sends)
    await bot._tier_fire_alerts_job(SimpleNamespace())

    assert sends == ["edge_contract_alerts_dedup_01"]


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
