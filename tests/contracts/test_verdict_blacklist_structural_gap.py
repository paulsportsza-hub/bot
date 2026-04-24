"""QF-3 contract test — W84-Q9 \"structural gap\" regression guard.

Catches:
1. The substring being removed from _VERDICT_BLACKLIST in bot.py.
2. Any live narrative_cache row leaking the phrase in verdict_html or narrative_html.

Failure on either means the phrase is reachable to users again.
"""
import os
import sqlite3
import sys
import pytest

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)


def test_structural_gap_in_verdict_blacklist():
    """_VERDICT_BLACKLIST must carry \"structural gap\" (QF-3 W84-Q9 restore)."""
    from bot import _VERDICT_BLACKLIST
    assert "structural gap" in _VERDICT_BLACKLIST, (
        "\"structural gap\" missing from _VERDICT_BLACKLIST — W84-Q9 regression. "
        "Restore at bot.py:~8110 per QF-3 (2026-04-24)."
    )


def test_no_live_cache_row_leaks_structural_gap():
    """No servable narrative_cache row may contain \"structural gap\" in verdict_html or narrative_html."""
    db_path = "/home/paulsportsza/scrapers/odds.db"
    if not os.path.exists(db_path):
        pytest.skip("live DB not present in this environment")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        rows = conn.execute(
            """SELECT match_id
                 FROM narrative_cache
                WHERE COALESCE(quarantined, 0) = 0
                  AND (status IS NULL OR status != 'quarantined')
                  AND expires_at > datetime('now')
                  AND (
                        lower(COALESCE(verdict_html, '')) LIKE '%structural gap%'
                     OR lower(COALESCE(narrative_html, '')) LIKE '%structural gap%'
                      )""",
        ).fetchall()
    finally:
        conn.close()
    assert not rows, (
        "Live narrative_cache contains servable rows leaking 'structural gap': "
        + ", ".join(r[0] for r in rows)
    )
