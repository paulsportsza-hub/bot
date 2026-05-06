from __future__ import annotations

import bot
import db_connection


GOOD_VERDICT = (
    "Recent results strengthen the case for Liverpool. "
    "Back Liverpool at 1.96 with Supabets, standard stake."
)
BAD_SIGNAL_CLAIM = (
    "Recent results strengthen the case for Liverpool. "
    "Back Liverpool at 1.96 with Supabets, standard stake."
)


class _DummyConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        return None

    def commit(self):
        self.statements.append(("COMMIT", ()))

    def close(self):
        self.statements.append(("CLOSE", ()))


def _pack(form_available: bool):
    return {
        "match_id": "liverpool_vs_chelsea_2026-05-07",
        "match_key": "liverpool_vs_chelsea_2026-05-07",
        "home_team": "Liverpool",
        "away_team": "Chelsea",
        "recommended_team": "Liverpool",
        "outcome_label": "Liverpool",
        "sport": "soccer",
        "league": "epl",
        "recommended_odds": 1.96,
        "bookmaker": "Supabets",
        "signals": {
            "price_edge": {"available": True},
            "form_h2h": {"available": form_available},
        },
    }


def _tip_data(form_available: bool):
    return {
        "edge_tier": "gold",
        "bookmaker": "Supabets",
        "odds": 1.96,
        "evidence_pack": _pack(form_available),
    }


def _install_dummy_db(monkeypatch):
    conn = _DummyConnection()
    monkeypatch.setattr(db_connection, "get_connection", lambda *_a, **_kw: conn)
    monkeypatch.setattr(bot, "_compute_odds_hash", lambda _match_key: "hash")
    return conn


def _wrote_verdict(conn: _DummyConnection) -> bool:
    return any("INSERT OR REPLACE INTO narrative_cache" in sql for sql, _ in conn.statements)


def test_bot_validator_call_consistent_under_v2_flag_on(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")
    good_conn = _install_dummy_db(monkeypatch)

    bot._store_verdict_cache_sync(
        "liverpool_vs_chelsea_2026-05-07",
        GOOD_VERDICT,
        _tip_data(form_available=True),
    )

    assert _wrote_verdict(good_conn)

    bad_conn = _install_dummy_db(monkeypatch)
    bot._store_verdict_cache_sync(
        "liverpool_vs_chelsea_2026-05-07",
        BAD_SIGNAL_CLAIM,
        _tip_data(form_available=False),
    )

    assert not _wrote_verdict(bad_conn)


def test_bot_validator_call_consistent_under_v2_flag_off(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "0")
    conn = _install_dummy_db(monkeypatch)

    bot._store_verdict_cache_sync(
        "liverpool_vs_chelsea_2026-05-07",
        BAD_SIGNAL_CLAIM,
        _tip_data(form_available=False),
    )

    assert _wrote_verdict(conn)
