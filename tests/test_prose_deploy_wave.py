from __future__ import annotations

import bot
import narrative_spec
from renderers import telegram_renderer, whatsapp_renderer


def test_live_w80_path_uses_programmatic_builder(monkeypatch):
    monkeypatch.setattr(bot, "_build_programmatic_narrative", lambda *args, **kwargs: "W80")
    monkeypatch.setattr(bot, "_build_signal_only_narrative", lambda *args, **kwargs: "SIGNAL")

    result = bot._build_live_w80_prose_narrative(
        ctx_data={"data_available": True},
        tips=[{"ev": 1.2}],
        sport="soccer",
        home_team="Arsenal",
        away_team="Everton",
    )

    assert result == "W80"


def test_signal_only_narrative_routes_through_narrative_spec_baseline(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_build(ctx_data, edge_data, tips, sport):
        captured["ctx_data"] = ctx_data
        captured["edge_data"] = edge_data
        captured["tips"] = tips
        captured["sport"] = sport
        return {"spec": "ok"}

    def _fake_render(spec):
        captured["spec"] = spec
        return "BASELINE"

    monkeypatch.setattr(narrative_spec, "build_narrative_spec", _fake_build)
    monkeypatch.setattr(narrative_spec, "_render_baseline", _fake_render)

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

    assert result == "BASELINE"
    assert captured["ctx_data"] is None
    assert captured["sport"] == "soccer"
    assert captured["spec"] == {"spec": "ok"}
    assert captured["edge_data"]["home_team"] == "Arsenal"
    assert captured["edge_data"]["away_team"] == "Everton"


def test_live_w80_weak_path_uses_narrative_spec_baseline(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_build(ctx_data, edge_data, tips, sport):
        captured["ctx_data"] = ctx_data
        captured["edge_data"] = edge_data
        captured["tips"] = tips
        captured["sport"] = sport
        return {"spec": "ok"}

    def _fake_render(spec):
        captured["spec"] = spec
        return "BASELINE"

    monkeypatch.setattr(bot, "_build_programmatic_narrative", lambda *args, **kwargs: "W80")
    monkeypatch.setattr(narrative_spec, "build_narrative_spec", _fake_build)
    monkeypatch.setattr(narrative_spec, "_render_baseline", _fake_render)

    result = bot._build_live_w80_prose_narrative(
        ctx_data={},
        tips=[{"ev": 1.2}],
        sport="soccer",
        home_team="Arsenal",
        away_team="Everton",
    )

    assert result == "BASELINE"
    assert captured["ctx_data"] is None
    assert captured["sport"] == "soccer"
    assert captured["spec"] == {"spec": "ok"}
    assert captured["edge_data"]["home_team"] == "Arsenal"
    assert captured["edge_data"]["away_team"] == "Everton"


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

    assert lines[0] == "📊 0/1 signals [MODEL ONLY]"


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
