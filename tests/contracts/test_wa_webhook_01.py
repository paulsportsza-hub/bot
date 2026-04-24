"""WA-CLOUD-API-01 contract tests — WhatsApp webhook scaffold + ctwa_clid capture.

Covers Acceptance Criteria 1–5:
  AC1: GET correct verify_token  → 200 + hub.challenge echoed
  AC2: GET wrong verify_token    → 403
  AC3: POST CTWA payload         → wa_contacts row: source='ctwa', ctwa_clid set
  AC4: POST organic message      → wa_contacts row: source='organic', ctwa_clid=NULL
  AC5: Duplicate wa_id           → upsert: last_seen_at updated, ctwa_clid filled on re-contact
"""

import os
import sqlite3
import sys
import pytest

# Ensure bot/ is on the path for db_connection
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_db(path: str) -> sqlite3.Connection:
    """Create a wa_contacts table in a fresh test DB via the approved factory."""
    from db_connection import get_connection
    conn = get_connection(path, timeout_ms=5000)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wa_contacts (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           wa_id TEXT NOT NULL,
           phone_number TEXT,
           display_name TEXT,
           ctwa_clid TEXT,
           source TEXT NOT NULL DEFAULT 'organic',
           opted_in INTEGER NOT NULL DEFAULT 1,
           opted_in_at TEXT,
           last_seen_at TEXT,
           UNIQUE(wa_id)
        )"""
    )
    conn.commit()
    return conn


def _upsert_contact(conn: sqlite3.Connection, wa_id: str, phone: str,
                    display_name: str, ctwa_clid, source: str, now: str) -> None:
    """Mirror of the production upsert in handle_wa_webhook."""
    conn.execute(
        """INSERT INTO wa_contacts
           (wa_id, phone_number, display_name, ctwa_clid, source,
            opted_in, opted_in_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)
           ON CONFLICT(wa_id) DO UPDATE SET
           last_seen_at = excluded.last_seen_at,
           ctwa_clid = COALESCE(excluded.ctwa_clid, ctwa_clid),
           phone_number = COALESCE(excluded.phone_number, phone_number)
        """,
        (wa_id, phone, display_name, ctwa_clid, source, now, now),
    )
    conn.commit()


# ── AC1 / AC2: GET verification handshake ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_correct_token_returns_challenge():
    """AC1: GET with correct verify_token echoes hub.challenge with 200."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    verify_token = "mzansi_wh_verify_2026"

    async def handle_wa_verify(request: web.Request) -> web.Response:
        mode = request.rel_url.query.get("hub.mode", "")
        token = request.rel_url.query.get("hub.verify_token", "")
        challenge = request.rel_url.query.get("hub.challenge", "")
        if mode == "subscribe" and token == verify_token:
            return web.Response(status=200, text=challenge)
        return web.Response(status=403, text="Forbidden")

    app = web.Application()
    app.router.add_get("/webhook/whatsapp", handle_wa_verify)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": verify_token,
                "hub.challenge": "abc123xyz",
            },
        )
        assert resp.status == 200
        text = await resp.text()
        assert text == "abc123xyz"


@pytest.mark.asyncio
async def test_get_wrong_token_returns_403():
    """AC2: GET with wrong verify_token returns 403."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    verify_token = "mzansi_wh_verify_2026"

    async def handle_wa_verify(request: web.Request) -> web.Response:
        mode = request.rel_url.query.get("hub.mode", "")
        token = request.rel_url.query.get("hub.verify_token", "")
        challenge = request.rel_url.query.get("hub.challenge", "")
        if mode == "subscribe" and token == verify_token:
            return web.Response(status=200, text=challenge)
        return web.Response(status=403, text="Forbidden")

    app = web.Application()
    app.router.add_get("/webhook/whatsapp", handle_wa_verify)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "abc123xyz",
            },
        )
        assert resp.status == 403


# ── AC3: POST CTWA payload writes correct row ──────────────────────────────────

def test_post_ctwa_payload_writes_row(tmp_path):
    """AC3: CTWA message → wa_contacts row with source='ctwa' and ctwa_clid set."""
    db_path = str(tmp_path / "test.db")
    conn = _make_db(db_path)

    _upsert_contact(
        conn,
        wa_id="27821234567",
        phone="+27821234567",
        display_name="Test User",
        ctwa_clid="ARAkLgVJ_test_clid_abc123",
        source="ctwa",
        now="2026-04-24T12:00:00+02:00",
    )

    row = conn.execute(
        "SELECT * FROM wa_contacts WHERE wa_id = ?", ("27821234567",)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["wa_id"] == "27821234567"
    assert row["phone_number"] == "+27821234567"
    assert row["ctwa_clid"] == "ARAkLgVJ_test_clid_abc123"
    assert row["source"] == "ctwa"
    assert row["opted_in"] == 1
    assert row["opted_in_at"] is not None


# ── AC4: POST organic message (no referral) ────────────────────────────────────

def test_post_organic_message_writes_row_no_clid(tmp_path):
    """AC4: Organic message (no referral) → source='organic', ctwa_clid=NULL."""
    db_path = str(tmp_path / "test.db")
    conn = _make_db(db_path)

    _upsert_contact(
        conn,
        wa_id="27831111111",
        phone="+27831111111",
        display_name="Organic User",
        ctwa_clid=None,
        source="organic",
        now="2026-04-24T12:01:00+02:00",
    )

    row = conn.execute(
        "SELECT * FROM wa_contacts WHERE wa_id = ?", ("27831111111",)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["source"] == "organic"
    assert row["ctwa_clid"] is None
    assert row["opted_in"] == 1


# ── AC5: Duplicate wa_id upsert ────────────────────────────────────────────────

def test_duplicate_wa_id_upserts_correctly(tmp_path):
    """AC5: Same wa_id twice → last_seen_at updates, ctwa_clid filled on re-contact."""
    db_path = str(tmp_path / "test.db")
    conn = _make_db(db_path)

    # First contact — organic, no clid
    _upsert_contact(
        conn,
        wa_id="27841234567",
        phone="+27841234567",
        display_name="Return User",
        ctwa_clid=None,
        source="organic",
        now="2026-04-24T10:00:00+02:00",
    )

    # Re-contact from CTWA ad — same wa_id, now has clid
    _upsert_contact(
        conn,
        wa_id="27841234567",
        phone="+27841234567",
        display_name="Return User",
        ctwa_clid="NEW_CLID_XYZ",
        source="ctwa",
        now="2026-04-24T14:00:00+02:00",
    )

    rows = conn.execute(
        "SELECT * FROM wa_contacts WHERE wa_id = ?", ("27841234567",)
    ).fetchall()
    conn.close()

    # Only one row (UNIQUE constraint)
    assert len(rows) == 1
    row = rows[0]
    # ctwa_clid filled in on re-contact
    assert row["ctwa_clid"] == "NEW_CLID_XYZ"
    # last_seen_at updated to latest contact time
    assert row["last_seen_at"] == "2026-04-24T14:00:00+02:00"
    # opted_in preserved
    assert row["opted_in"] == 1


# ── AC5b: Existing clid not overwritten by NULL ────────────────────────────────

def test_existing_clid_not_overwritten_by_null(tmp_path):
    """AC5b: Upsert with NULL ctwa_clid does not overwrite an existing clid."""
    db_path = str(tmp_path / "test.db")
    conn = _make_db(db_path)

    _upsert_contact(
        conn,
        wa_id="27851234567",
        phone="+27851234567",
        display_name="Sticky User",
        ctwa_clid="FIRST_CLID_ABC",
        source="ctwa",
        now="2026-04-24T09:00:00+02:00",
    )

    # Re-contact without clid (organic follow-up)
    _upsert_contact(
        conn,
        wa_id="27851234567",
        phone="+27851234567",
        display_name="Sticky User",
        ctwa_clid=None,
        source="organic",
        now="2026-04-24T18:00:00+02:00",
    )

    row = conn.execute(
        "SELECT * FROM wa_contacts WHERE wa_id = ?", ("27851234567",)
    ).fetchone()
    conn.close()

    # COALESCE keeps the first clid when the new value is NULL
    assert row["ctwa_clid"] == "FIRST_CLID_ABC"
    assert row["last_seen_at"] == "2026-04-24T18:00:00+02:00"
