"""BUILD-C1-OPTIONA-PHASE1-BREAKDOWN-01 — AC-9 / AC-14 contract tests.

AC-9: build_ai_breakdown_data() returns verdict_prose_html == verdict_html column
when the parsed embedded verdict is banned-trivial ("Back Arsenal.").

AC-14 Case A (NULL fallback): When verdict_html is NULL/empty AND the embedded
verdict fails quality, the function retains the thin embedded text (never
substitutes an empty string), and logs AI_BREAKDOWN_VERDICT_FALLBACK_NULL.

AC-14 Case B (truncation order): When _extract_section("verdict") returns a
250-char string whose first 200 chars pass quality, the returned
verdict_prose_html is ≤ 200 chars AND no fallback substitution occurred.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import card_data


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_narrative_html(verdict_text: str) -> str:
    """Construct a minimal narrative_html with all 4 section markers."""
    return (
        "🎯 Home vs Away / 🏆 PSL\n"
        "📋 <b>The Setup</b>\n"
        "Setup text for the fixture.\n"
        "🎯 <b>The Edge</b>\n"
        "Edge text here.\n"
        "⚠️ <b>The Risk</b>\n"
        "Risk text here.\n"
        f"🏆 <b>Verdict</b>\n"
        f"{verdict_text}\n"
    )


def _make_mock_conn(row: tuple) -> MagicMock:
    """Return a mock SQLite connection whose execute().fetchone() yields row."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = row
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    return mock_conn


def _fresh_created_at() -> str:
    """Return an ISO timestamp representing 2 hours ago (within the 12h staleness window)."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


QUALITY_VERDICT_HTML = (
    "Arteta's Arsenal carry the form edge into this one — five home wins from six "
    "and a bookmaker price gap of 8%. The signals align. Back them at standard stake."
)


# ── AC-9 ──────────────────────────────────────────────────────────────────────

def test_ac9_trivial_embedded_falls_back_to_verdict_html():
    """AC-9: Banned-trivial embedded verdict → verdict_prose_html == verdict_html."""
    trivial_embedded = "Back Arsenal."
    narrative = _build_narrative_html(trivial_embedded)
    created_at = _fresh_created_at()

    # 6-column row: narrative_html, edge_tier, tips_json, verdict_html, evidence_class, created_at
    row = (narrative, "gold", "[]", QUALITY_VERDICT_HTML, "", created_at)
    mock_conn = _make_mock_conn(row)

    with patch("scrapers.db_connect.connect_odds_db", return_value=mock_conn):
        result = card_data.build_ai_breakdown_data("arsenal_vs_brentford_2026-04-24")

    assert result is not None, "build_ai_breakdown_data must return a dict, not None"
    assert result["verdict_prose_html"] == QUALITY_VERDICT_HTML, (
        f"AC-9: expected verdict_prose_html == verdict_html. Got: {result['verdict_prose_html']!r}"
    )


# ── AC-14 Case A — NULL fallback ──────────────────────────────────────────────

def test_ac14_case_a_null_verdict_html_retains_thin_text(caplog):
    """AC-14 Case A: verdict_html NULL → thin embedded text retained, not empty string."""
    trivial_embedded = "Back Arsenal."
    narrative = _build_narrative_html(trivial_embedded)
    created_at = _fresh_created_at()

    # verdict_html is empty (AC-11 guard fires)
    row = (narrative, "bronze", "[]", "", "", created_at)
    mock_conn = _make_mock_conn(row)

    with caplog.at_level(logging.INFO, logger="card_data"):
        with patch("scrapers.db_connect.connect_odds_db", return_value=mock_conn):
            result = card_data.build_ai_breakdown_data("arsenal_vs_brentford_2026-04-24")

    assert result is not None, "build_ai_breakdown_data must return a dict"
    # AC-11: thin text retained, not replaced with empty string
    assert result["verdict_prose_html"] != "", (
        "AC-14 Case A: verdict_prose_html must not be empty when verdict_html is NULL. "
        "The thin embedded text must be retained (thin > blank)."
    )
    # AC-14 Case A: AI_BREAKDOWN_VERDICT_FALLBACK_NULL must appear in logs
    log_text = " ".join(r.message for r in caplog.records)
    assert "AI_BREAKDOWN_VERDICT_FALLBACK_NULL" in log_text, (
        "AC-14 Case A: AI_BREAKDOWN_VERDICT_FALLBACK_NULL must be logged when "
        "verdict_html is NULL/empty and quality gate fires."
    )


# ── AC-14 Case B — truncation order ──────────────────────────────────────────

def test_ac14_case_b_truncation_order_correct():
    """AC-14 Case B: 250-char verdict, first ~167 chars pass quality.
    Truncation fires at sentence boundary before 200; quality check runs on
    truncated text; no fallback occurs; verdict_prose_html ≤ 200 chars.
    """
    # Construct a 250-char verdict where the first ~167 chars pass quality.
    # Three sentences; the third pushes past 200 chars total.
    sentence_1 = (
        "Arsenal's form edge is confirmed, home record supports this, "
        "and the bookmaker odds gap is real. Back them at standard stake."
    )  # 123 chars, ends in "."
    sentence_2 = (
        " Away side faces extra pressure here with limited support indicators."
    )  # 69 chars, ends in "."
    sentence_3 = " Form signals align with the overall case and edge is clear."  # 61 chars

    long_verdict = sentence_1 + sentence_2 + sentence_3
    assert len(long_verdict) > 200, f"Test verdict must exceed 200 chars (got {len(long_verdict)})"

    # Verify first 200 chars contain a sentence boundary
    first_200 = long_verdict[:200]
    last_stop = max(first_200.rfind("."), first_200.rfind("!"), first_200.rfind("?"))
    assert last_stop > 60, "Test verdict must have a sentence boundary within first 200 chars"

    narrative = _build_narrative_html(long_verdict)
    created_at = _fresh_created_at()

    # verdict_html is a different string (sentinel) — allows detecting if fallback fired
    sentinel_verdict_html = "SENTINEL_VERDICT_HTML_SHOULD_NOT_APPEAR"
    row = (narrative, "bronze", "[]", sentinel_verdict_html, "", created_at)
    mock_conn = _make_mock_conn(row)

    with patch("scrapers.db_connect.connect_odds_db", return_value=mock_conn):
        result = card_data.build_ai_breakdown_data("arsenal_vs_brentford_2026-04-24")

    assert result is not None
    vph = result["verdict_prose_html"]

    # AC-14 Case B: ≤ 200 chars
    assert len(vph) <= 200, (
        f"AC-14 Case B: verdict_prose_html must be ≤ 200 chars after truncation. "
        f"Got {len(vph)} chars: {vph!r}"
    )
    # No fallback — sentinel must not appear
    assert sentinel_verdict_html not in vph, (
        "AC-14 Case B: fallback substitution must NOT occur when truncated text passes quality."
    )
    # Must end at a sentence boundary (. ! ?)
    assert vph[-1] in ".!?", (
        f"AC-14 Case B: truncated verdict must end at a sentence boundary. Got: {vph[-1]!r}"
    )


# ── AC-3 truncation applies to non-verdict sections ──────────────────────────

def test_ac3_setup_edge_risk_truncated_at_200():
    """AC-3: setup_html, edge_html, risk_html are each capped at 200 chars."""
    long_section = (
        "This is a very long narrative section that definitely exceeds 200 characters "
        "in total length. It should be truncated at the nearest sentence boundary "
        "before the 200-character limit. This trailing sentence should not appear."
    )
    assert len(long_section) > 200

    # All three prose sections use the same long text
    narrative = (
        "📋 <b>The Setup</b>\n" + long_section + "\n"
        "🎯 <b>The Edge</b>\n" + long_section + "\n"
        "⚠️ <b>The Risk</b>\n" + long_section + "\n"
        "🏆 <b>Verdict</b>\n" + QUALITY_VERDICT_HTML + "\n"
    )
    created_at = _fresh_created_at()
    row = (narrative, "bronze", "[]", QUALITY_VERDICT_HTML, "", created_at)
    mock_conn = _make_mock_conn(row)

    with patch("scrapers.db_connect.connect_odds_db", return_value=mock_conn):
        result = card_data.build_ai_breakdown_data("arsenal_vs_brentford_2026-04-24")

    assert result is not None
    for key in ("setup_html", "edge_html", "risk_html"):
        val = result[key]
        assert len(val) <= 200, (
            f"AC-3: {key} must be ≤ 200 chars after truncation. Got {len(val)}: {val!r}"
        )
