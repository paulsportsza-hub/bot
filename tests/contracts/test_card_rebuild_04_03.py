"""CARD-REBUILD-04-03 — Verdict rewrite: prompt + max_tokens + blacklist.

Acceptance tests for three defect fixes:
  D-01: max_tokens raised 60→100, system prompt instructs ≤75 chars
  D-02: phrase blacklist rejects general-knowledge verdicts
  D-16: verdict section header uses 🏆 not ⚠
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── helpers ───────────────────────────────────────────────────────────────────

_BLACKLISTED_PHRASES = [
    "home advantage", "away advantage",
    "historically", "tradition", "traditionally",
    "derby", "rivalry",
    "big game", "big match",
    "relegation battle", "title race",
    "form suggests", "expected to",
    "known for", "famous for",
    # CARD-FIX-J: "favourite" and "underdog" removed — legitimate SA betting terms
]

_FOUNDER_BASELINE = [
    {
        "tip": {"pick": "Arsenal", "outcome": "Arsenal", "odds": 1.85, "ev": 9.2, "home": "Arsenal", "away": "Chelsea"},
        "verified": {"matchup": "Arsenal vs Chelsea", "tipster": {}},
        "mock_verdict": "Arsenal at 1.85 offers +9.2% edge; Chelsea priced 8% tight.",
    },
    {
        "tip": {"pick": "Mamelodi Sundowns", "outcome": "Mamelodi Sundowns", "odds": 1.65, "ev": 6.5, "home": "Sundowns", "away": "Chiefs"},
        "verified": {"matchup": "Sundowns vs Chiefs", "tipster": {"home_consensus_pct": 72}},
        "mock_verdict": "Sundowns at 1.65 with +6.5% and 72% tipster backing.",
    },
    {
        "tip": {"pick": "Draw", "outcome": "Draw", "odds": 3.40, "ev": 11.0, "home": "Man City", "away": "Liverpool"},
        "verified": {"matchup": "Man City vs Liverpool", "tipster": {}},
        "mock_verdict": "Draw at 3.40 yields +11.0% against 28% market implied.",
    },
    {
        "tip": {"pick": "Springboks", "outcome": "Springboks", "odds": 1.55, "ev": 4.8, "home": "Springboks", "away": "All Blacks"},
        "verified": {"matchup": "Springboks vs All Blacks", "tipster": {"most_tipped": "Springboks"}},
        "mock_verdict": "Springboks at 1.55 present a +4.8% edge with 3 signals aligned.",
    },
    {
        "tip": {"pick": "Over 2.5", "outcome": "Over 2.5", "odds": 1.90, "ev": 7.3, "home": "Barcelona", "away": "Real Madrid"},
        "verified": {"matchup": "Barcelona vs Real Madrid", "tipster": {}},
        "mock_verdict": "Over 2.5 at 1.90 delivers +7.3% over 58% fair probability.",
    },
]


def _make_mock_response(verdict_text: str):
    """Build a fake Anthropic Messages response."""
    block = MagicMock()
    block.text = verdict_text
    resp = MagicMock()
    resp.content = [block]
    return resp


# ── D-01: 5 founder-baseline verdicts ─────────────────────────────────────────

@pytest.mark.parametrize("case", _FOUNDER_BASELINE)
def test_verdict_complete_sentence(case):
    """D-01: each founder-baseline verdict is a complete sentence ending in . or !"""
    from bot import _generate_verdict

    mock_resp = _make_mock_response(case["mock_verdict"])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        result = _generate_verdict(case["tip"], case["verified"])

    assert result.endswith((".", "!")), f"Verdict must end with . or !: {result!r}"


@pytest.mark.parametrize("case", _FOUNDER_BASELINE)
def test_verdict_within_80_chars(case):
    """D-01: each founder-baseline verdict is ≤80 chars."""
    from bot import _generate_verdict

    mock_resp = _make_mock_response(case["mock_verdict"])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        result = _generate_verdict(case["tip"], case["verified"])

    assert len(result) <= 80, f"Verdict exceeds 80 chars ({len(result)}): {result!r}"


@pytest.mark.parametrize("case", _FOUNDER_BASELINE)
def test_verdict_contains_digit(case):
    """D-01: each founder-baseline verdict contains at least one digit."""
    import re
    from bot import _generate_verdict

    mock_resp = _make_mock_response(case["mock_verdict"])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        result = _generate_verdict(case["tip"], case["verified"])

    assert re.search(r"\d", result), f"Verdict contains no digit: {result!r}"


@pytest.mark.parametrize("case", _FOUNDER_BASELINE)
def test_verdict_no_blacklisted_phrase(case):
    """D-02: each founder-baseline verdict contains no blacklisted phrase."""
    from bot import _generate_verdict

    mock_resp = _make_mock_response(case["mock_verdict"])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        result = _generate_verdict(case["tip"], case["verified"])

    lowered = result.lower()
    for phrase in _BLACKLISTED_PHRASES:
        assert phrase not in lowered, f"Blacklisted phrase {phrase!r} found in verdict: {result!r}"


# ── D-02: blacklist rejection test ────────────────────────────────────────────

def test_blacklist_rejects_home_advantage():
    """D-02: Haiku response containing 'home advantage' → _generate_verdict returns ''."""
    from bot import _generate_verdict

    blacklisted_text = "Arsenal hold home advantage at 1.85 with +9.2% EV edge."
    mock_resp = _make_mock_response(blacklisted_text)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    tip = {"pick": "Arsenal", "odds": 1.85, "ev": 9.2}
    verified = {"matchup": "Arsenal vs Chelsea", "tipster": {}}

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        result = _generate_verdict(tip, verified)

    assert result == "", f"Expected '' for blacklisted verdict, got: {result!r}"


@pytest.mark.parametrize("phrase", _BLACKLISTED_PHRASES)
def test_each_blacklisted_phrase_triggers_rejection(phrase):
    """D-02: every phrase in the blacklist triggers rejection."""
    from bot import _generate_verdict

    text = f"This {phrase} tip offers 5.0% EV at odds 2.10."
    mock_resp = _make_mock_response(text)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    tip = {"pick": "Team A", "odds": 2.10, "ev": 5.0}
    verified = {"matchup": "Team A vs Team B", "tipster": {}}

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        result = _generate_verdict(tip, verified)

    assert result == "", f"Phrase {phrase!r} should trigger rejection, got: {result!r}"


# ── D-01: max_tokens and system prompt params ─────────────────────────────────

def test_max_tokens_is_100():
    """D-01: Sonnet is called with max_tokens=110 (CARD-FIX-N: 2 sentences + call line)."""
    from bot import _generate_verdict

    mock_resp = _make_mock_response("Odds at 1.85 offer +9.2% EV edge.")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    tip = {"pick": "Arsenal", "odds": 1.85, "ev": 9.2, "home": "Arsenal", "away": "Chelsea"}
    verified = {"matchup": "Arsenal vs Chelsea", "tipster": {}}

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        _generate_verdict(tip, verified)

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs.get("max_tokens") >= 120, (
        f"max_tokens should be ≥120 (FIX-NARRATIVE-VERDICT-MAXTOKENS-01: 128 tok, _trim_to_last_sentence caps at 140 chars), got {call_kwargs.kwargs.get('max_tokens')}"
    )


def test_system_prompt_param_used():
    """D-01: Haiku call uses a 'system' parameter (not inline user prompt)."""
    from bot import _generate_verdict

    mock_resp = _make_mock_response("Odds at 1.85 offer +9.2% EV edge.")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    tip = {"pick": "Arsenal", "odds": 1.85, "ev": 9.2, "home": "Arsenal", "away": "Chelsea"}
    verified = {"matchup": "Arsenal vs Chelsea", "tipster": {}}

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        _generate_verdict(tip, verified)

    call_kwargs = mock_client.messages.create.call_args
    assert "system" in call_kwargs.kwargs, "Sonnet call must use 'system' parameter"
    system_text = call_kwargs.kwargs["system"]
    assert "SA sports pundit" in system_text, f"System prompt must use SA sports pundit voice, got: {system_text!r}"


# ── D-01: truncation safety net ───────────────────────────────────────────────

def test_truncation_appends_period_when_missing():
    """BUILD-VERDICT-TRUNCATE-02: long Sonnet output is trimmed to last sentence boundary within 140 chars."""
    from bot import _generate_verdict

    # 410-char text — _trim_to_last_sentence caps it to ≤140 chars
    long_text = (
        "Arsenal priced 8% tight at 1.85 with a +9.2% pricing gap — "
        "line movement backs the pick and tipster consensus sits at 72% — "
        "back with a manageable unit here no doubt about it at all and the "
        "form data confirms that the squad has been in exceptional touch "
        "across their last five outings winning four and drawing once with "
        "some really impressive attacking numbers throughout the whole run "
        "which means confidence in this selection is absolutely warranted here."
    )
    mock_resp = _make_mock_response(long_text)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_resp

    tip = {"pick": "Arsenal", "odds": 1.85, "ev": 9.2, "home": "Arsenal", "away": "Chelsea"}
    verified = {"matchup": "Arsenal vs Chelsea", "tipster": {}}

    with patch("openrouter_client.Anthropic", return_value=mock_client):
        result = _generate_verdict(tip, verified)

    # _trim_to_last_sentence caps at 140 chars; result ends with sentence terminal or is empty
    assert len(result) <= 140, f"Result exceeds 140 chars: {len(result)}"
    if result:
        assert result.endswith(('.', '!', '?')), f"Result does not end at sentence boundary: {result!r}"


# ── D-16: template emoji ───────────────────────────────────────────────────────

def test_verdict_template_uses_trophy_emoji():
    """D-16: edge_detail.html verdict section header uses 🏆 not ⚠."""
    template_path = (
        Path(__file__).parent.parent.parent / "card_templates" / "edge_detail.html"
    )
    content = template_path.read_text(encoding="utf-8")

    verdict_lines = [
        ln for ln in content.splitlines()
        if "VERDICT" in ln and "section-hdr" in ln
    ]
    assert verdict_lines, "No verdict section-hdr line found in template"
    verdict_line = verdict_lines[0]

    assert "🏆" in verdict_line, (
        f"Verdict header must use 🏆, got: {verdict_line!r}"
    )
    assert "⚠" not in verdict_line, (
        f"Verdict header must not use ⚠, got: {verdict_line!r}"
    )
