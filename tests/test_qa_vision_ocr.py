"""Unit tests for tests/qa/vision_ocr.py + card_assertions.py.

All Anthropic calls are mocked — no network, no ANTHROPIC_API_KEY required.
Runs as part of pytest -q (no `integration` marker).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.qa.card_assertions import (
    assert_button_set,
    assert_not_stub_shape,
    assert_teams_populated,
    assert_tier_badge_present,
    assert_verdict_in_range,
)
from tests.qa.vision_ocr import CardOCR, ocr_card


@dataclass
class _FakeBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeResponse:
    content: list[_FakeBlock]


def _fake_response(payload: dict) -> _FakeResponse:
    return _FakeResponse(content=[_FakeBlock(text=json.dumps(payload))])


def _make_tiny_png(tmp: Path) -> Path:
    """Write a valid 1x1 PNG so ocr_card() passes the file-exists check."""
    png_path = tmp / "card.png"
    png_path.write_bytes(
        # Minimal 1x1 PNG — header + IHDR + IDAT + IEND
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01^\xf3*:"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return png_path


# ── Case 1 — happy path ──────────────────────────────────────────────────────


def test_happy_path_parses_all_fields(tmp_path, monkeypatch):
    """Vision returns a well-formed card reading → all fields populated."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    png = _make_tiny_png(tmp_path)

    payload = {
        "verdict_text": (
            "Brighton's form is sharp — four wins from five — and the Magpies are "
            "in freefall. Back Brighton at 2.75 with WSB."
        ),
        "home_team": "Newcastle United",
        "away_team": "Brighton",
        "tier_badge": "🥇",
        "button_count": 3,
        "button_labels": ["📲 Bet on WSB →", "📊 All Odds", "↩️ Back"],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch("tests.qa.vision_ocr.anthropic.Anthropic", return_value=fake_client):
        ocr = ocr_card(png)

    assert ocr.home_team == "Newcastle United"
    assert ocr.away_team == "Brighton"
    assert ocr.tier_badge == "🥇"
    assert ocr.button_count == 3
    assert ocr.button_labels == ["📲 Bet on WSB →", "📊 All Odds", "↩️ Back"]
    assert "Brighton" in ocr.verdict_text
    assert ocr.verdict_char_count == len(ocr.verdict_text)

    # Assertion helpers all pass on a clean card.
    assert_verdict_in_range(ocr)
    assert_not_stub_shape(ocr)
    assert_teams_populated(ocr)
    assert_tier_badge_present(ocr)
    assert_button_set(ocr, ["📲 Bet on WSB →", "📊 All Odds", "↩️ Back"])


# ── Case 2 — stub-shape verdict ──────────────────────────────────────────────


def test_stub_shape_verdict_fires_stub_assertion(tmp_path, monkeypatch):
    """A verdict matching the '— ? at 0.00.' shape must trip assert_not_stub_shape."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    png = _make_tiny_png(tmp_path)

    payload = {
        "verdict_text": "Monitor — ? at 0.00. Edge confirmed by model probability.",
        "home_team": "Mamelodi Sundowns",
        "away_team": "Stellenbosch",
        "tier_badge": "🥇",
        "button_count": 2,
        "button_labels": ["📲 Bet on Betway →", "↩️ Back"],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch("tests.qa.vision_ocr.anthropic.Anthropic", return_value=fake_client):
        ocr = ocr_card(png)

    with pytest.raises(AssertionError, match="stub shape"):
        assert_not_stub_shape(ocr)

    # Other assertions are independent and still pass on this card.
    assert_teams_populated(ocr)
    assert_tier_badge_present(ocr)


# ── Case 3 — empty team labels ──────────────────────────────────────────────


def test_empty_team_labels_fires_teams_assertion(tmp_path, monkeypatch):
    """Blank or HOME/AWAY placeholder labels must trip assert_teams_populated."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    png = _make_tiny_png(tmp_path)

    payload = {
        "verdict_text": (
            "The bookmaker has priced this at 1.95 against a model fair price of 1.80. "
            "Signals line up for a measured back at the number."
        ),
        "home_team": "HOME",
        "away_team": "",
        "tier_badge": "🥈",
        "button_count": 2,
        "button_labels": ["📲 Bet on Betway →", "↩️ Back"],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch("tests.qa.vision_ocr.anthropic.Anthropic", return_value=fake_client):
        ocr = ocr_card(png)

    with pytest.raises(AssertionError):
        assert_teams_populated(ocr)

    # Verdict length and tier are still fine — assertion helpers are granular.
    assert_verdict_in_range(ocr)
    assert_tier_badge_present(ocr)


# ── Case 4 — no tier badge ──────────────────────────────────────────────────


def test_no_tier_badge_fires_tier_assertion(tmp_path, monkeypatch):
    """Missing tier badge must trip assert_tier_badge_present."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    png = _make_tiny_png(tmp_path)

    payload = {
        "verdict_text": (
            "Brighton have won three of the last five meetings and the price has shortened "
            "overnight — confirming signals line up. Back Brighton."
        ),
        "home_team": "Newcastle United",
        "away_team": "Brighton",
        "tier_badge": "",
        "button_count": 2,
        "button_labels": ["📲 Bet on WSB →", "↩️ Back"],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch("tests.qa.vision_ocr.anthropic.Anthropic", return_value=fake_client):
        ocr = ocr_card(png)

    assert ocr.tier_badge is None
    with pytest.raises(AssertionError, match="tier_badge missing"):
        assert_tier_badge_present(ocr)

    # Verdict + teams are clean.
    assert_verdict_in_range(ocr)
    assert_not_stub_shape(ocr)
    assert_teams_populated(ocr)


# ── Extra parser guards ──────────────────────────────────────────────────────


def test_json_wrapped_in_code_fences_is_parsed(tmp_path, monkeypatch):
    """Claude occasionally wraps JSON in ``` fences — parser must tolerate it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    png = _make_tiny_png(tmp_path)

    payload = {
        "verdict_text": "Zebre at 1.47 (WSB) — supported by data, priced with value.",
        "home_team": "Zebre",
        "away_team": "Dragons",
        "tier_badge": "🥇",
        "button_count": 0,
        "button_labels": [],
    }
    wrapped = "```json\n" + json.dumps(payload) + "\n```"
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(
        content=[_FakeBlock(text=wrapped)]
    )

    with patch("tests.qa.vision_ocr.anthropic.Anthropic", return_value=fake_client):
        ocr = ocr_card(png)

    assert ocr.home_team == "Zebre"
    assert ocr.tier_badge == "🥇"


def test_missing_file_raises_file_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with pytest.raises(FileNotFoundError):
        ocr_card(tmp_path / "does-not-exist.png")


def test_missing_api_key_raises_runtime_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    png = _make_tiny_png(tmp_path)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ocr_card(png)


def test_cardocr_dataclass_shape():
    """Sanity: the dataclass has all fields the brief specifies."""
    ocr = CardOCR(
        verdict_text="sample",
        verdict_char_count=6,
        home_team="A",
        away_team="B",
        tier_badge="💎",
        button_count=0,
    )
    assert ocr.verdict_text == "sample"
    assert ocr.verdict_char_count == 6
    assert ocr.button_labels == []
    assert ocr.raw_response == ""
