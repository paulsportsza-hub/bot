from __future__ import annotations

import asyncio
import sqlite3
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
                posted_to_alerts_direct INTEGER DEFAULT 0
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
    assert "CREATE UNIQUE INDEX uix_alerts_send_log_edge_channel" in schema
    assert "ON alerts_send_log(edge_id, channel)" in schema


@pytest.mark.asyncio
async def test_tier_fire_alerts_job_claims_before_send(monkeypatch, tmp_path):
    """Two rapid scheduler calls for one edge_id must produce exactly one send."""
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
                "display_tier": "gold",
                "edge_tier": "gold",
            }
        ],
    )

    sends: list[str] = []

    async def fake_post_to_alerts(tip, edge_id, tier_assigned_at=None):
        sends.append(edge_id)
        await asyncio.sleep(0.05)
        return f"https://t.me/c/3789410835/{len(sends)}"

    monkeypatch.setattr(alerts_direct, "post_to_alerts", fake_post_to_alerts)

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
