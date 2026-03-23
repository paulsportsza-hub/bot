from __future__ import annotations

import bot
import narrative_spec
from renderers import telegram_renderer, whatsapp_renderer


def test_signal_only_narrative_produces_output():
    """_build_signal_only_narrative produces a narrative with section headers."""
    result = bot._build_signal_only_narrative(
        tips=[{
            "ev": 1.2,
            "outcome": "home",
            "odds": 1.95,
            "bookie": "Betway",
            "league": "Premier League",
            "edge_v2": {
                "match_key": "arsenal_vs_everton_2026-03-13",
                "league": "Premier League",
                "confirming_signals": 0,
            },
        }],
        sport="soccer",
    )

    assert "The Setup" in result
    assert "The Edge" in result
    assert "Arsenal" in result
    assert "Everton" in result


def test_edge_signal_meta_marks_model_only():
    confirming, total, model_only = bot._edge_signal_meta({
        "confirming_signals": 0,
        "signals": {
            "movement": {"available": True, "signal_strength": 0.2},
            "tipster": {"available": True, "signal_strength": 0.1},
        },
    })

    assert confirming == 0
    assert total == 2
    assert model_only is True


def test_gate_signal_display_shows_model_only_label():
    lines = bot._gate_signal_display(
        {
            "confirming_signals": 0,
            "signals": {"movement": {"available": True, "signal_strength": 0.2}},
        },
        user_tier="bronze",
        edge_tier="gold",
    )

    assert "signal" in lines[0].lower()


def test_hot_tips_empty_state_uses_new_copy():
    text, _ = bot._build_hot_tips_page([], page=0, user_tier="diamond")

    assert "thin slate" in text.lower()
    assert "market is efficient" not in text


def test_render_no_picks_copy_is_trustworthy():
    data = {"total_events": 12, "total_markets": 40, "risk_label": "Moderate"}

    telegram_text = telegram_renderer.render_no_picks(data)
    whatsapp_text = whatsapp_renderer.render_no_picks(data)

    assert "Nothing clears your Moderate profile right now." in telegram_text
    assert "protecting your bankroll" not in telegram_text
    assert "market is efficient" not in telegram_text
    assert "API quota" not in telegram_text
    assert "No value bets found right now" in whatsapp_text
