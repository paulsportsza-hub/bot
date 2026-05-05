import importlib.util
import sys
import types
from pathlib import Path


_MISSING = object()


def _install_engine_package():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "bot" / "verdict_engine_v2.py"
    previous_bot = sys.modules.get("bot", _MISSING)
    previous_submodule = sys.modules.get("bot.verdict_engine_v2", _MISSING)
    package = types.ModuleType("bot")
    package.__path__ = [str(module_path.parent)]
    sys.modules["bot"] = package
    spec = importlib.util.spec_from_file_location("bot.verdict_engine_v2", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot.verdict_engine_v2"] = module
    spec.loader.exec_module(module)
    return previous_bot, previous_submodule


_previous_bot, _previous_submodule = _install_engine_package()

from bot.verdict_engine_v2 import (  # noqa: E402
    VerdictContext,
    render_verdict_v2,
    validate_team_integrity,
    validate_verdict,
)


def _restore_bot_imports():
    if _previous_bot is _MISSING:
        sys.modules.pop("bot", None)
    else:
        sys.modules["bot"] = _previous_bot
    if _previous_submodule is _MISSING:
        sys.modules.pop("bot.verdict_engine_v2", None)
    else:
        sys.modules["bot.verdict_engine_v2"] = _previous_submodule


_restore_bot_imports()


def ctx(**overrides):
    base = dict(
        match_key="liverpool_vs_chelsea_2026-05-09",
        edge_revision="rev-1",
        sport="soccer",
        league="epl",
        home_name="Liverpool",
        away_name="Chelsea",
        recommended_team="Liverpool",
        outcome_label="Liverpool",
        odds="1.96",
        bookmaker="Supabets",
        tier="gold",
        signals={
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "market_agreement": {"available": True, "bookmaker_count": 4},
        },
        venue="Anfield",
        coach="Slot",
        nickname="the Reds",
    )
    base.update(overrides)
    return VerdictContext(**base)


def test_v2_deterministic_for_same_context():
    context = ctx()

    verdicts = [render_verdict_v2(context).text for _ in range(100)]

    assert len(set(verdicts)) == 1
    assert render_verdict_v2(context).valid


def test_v2_changes_across_match_keys_without_breaking_contract():
    verdicts = [
        render_verdict_v2(ctx(match_key=f"liverpool_vs_chelsea_{idx}", edge_revision="rev-1"))
        for idx in range(8)
    ]

    assert all(verdict.valid for verdict in verdicts)
    assert all(not verdict.fallback for verdict in verdicts)
    assert len({verdict.text for verdict in verdicts}) > 1


def test_v2_respects_200_char_cap():
    context = ctx(
        recommended_team="Chennai Super Kings",
        outcome_label="Chennai Super Kings",
        home_name="Delhi Capitals",
        away_name="Chennai Super Kings",
        nickname="Chennai",
        coach="Stephen Fleming",
        bookmaker="Hollywoodbets",
        venue="MA Chidambaram Stadium",
    )

    verdict = render_verdict_v2(context)

    assert verdict.valid
    assert len(verdict.text) <= 200


def test_v2_has_no_banned_terms():
    verdict = render_verdict_v2(ctx())
    banned = (
        "composite",
        "tier floor",
        "signal stack",
        "expected value",
        "model probability",
        "diamond-grade",
        "gold tier",
        "guaranteed",
        "lock",
        "max bet",
        "free money",
        "dictating tempo",
        "creating overloads",
    )

    assert verdict.valid
    assert not any(term in verdict.text.lower() for term in banned)
    assert validate_verdict(verdict.text, ctx()) == ()


def test_v2_requires_form_signal_for_form_claims():
    context = ctx(signals={"price_edge": {"available": True}})

    errors = validate_verdict("Liverpool's recent results back the lean — back Liverpool, standard stake.", context)

    assert "unsupported_form_claim" in errors


def test_v2_requires_injury_signal_for_team_news_claims():
    context = ctx(signals={"price_edge": {"available": True}})

    errors = validate_verdict("Team news has not been fully priced in — back Liverpool, standard stake.", context)

    assert "unsupported_team_news_claim" in errors


def test_v2_requires_movement_signal_for_line_move_claims():
    context = ctx(signals={"price_edge": {"available": True}, "market_agreement": {"available": True}})

    errors = validate_verdict("The line is starting to move toward Liverpool — back Liverpool, standard stake.", context)

    assert "unsupported_movement_claim" in errors


def test_v2_requires_market_signal_for_bookmaker_breadth_claims():
    context = ctx(signals={"price_edge": {"available": True}, "movement": {"available": True, "direction": "toward"}})

    errors = validate_verdict("4 books give Liverpool support — back Liverpool, standard stake.", context)

    assert "unsupported_market_claim" in errors


def test_v2_treats_unfavourable_movement_as_adverse():
    context = ctx(
        signals={"price_edge": {"available": True}, "movement": {"available": True, "direction": "unfavourable"}},
        line_movement_direction="unfavourable",
    )

    verdict = render_verdict_v2(context)

    assert verdict.valid
    assert "move toward" not in verdict.text.lower()
    assert "following Liverpool" not in verdict.text


def test_v2_unknown_movement_renders_neutral_movement_not_price_shell():
    context = ctx(
        signals={"movement": {"available": True, "direction": "unknown"}},
        line_movement_direction="unknown",
    )

    verdict = render_verdict_v2(context)

    assert verdict.valid
    assert not verdict.fallback
    assert verdict.primary_fact_type == "movement"
    assert "Price still supports" not in verdict.text
    assert "move toward" not in verdict.text.lower()
    assert "following Liverpool" not in verdict.text


def test_v2_does_not_use_home_venue_for_away_pick():
    for index in range(40):
        verdict = render_verdict_v2(
            ctx(
                match_key=f"liverpool_vs_chelsea_away_{index}",
                recommended_team="Chelsea",
                outcome_label="Chelsea",
                signals={"price_edge": {"available": True}, "form_h2h": {"available": True}},
                venue="Anfield",
                coach=None,
                nickname=None,
            )
        )

        assert verdict.valid
        assert "Anfield" not in verdict.text
        assert "home setting" not in verdict.text.lower()
        assert "venue angle" not in verdict.text.lower()


def test_v2_form_and_injury_clauses_avoid_broken_possessives():
    teams = ("Liverpool", "Bulls", "Stormers", "Chennai Super Kings")
    signal_sets = (
        {"form_h2h": {"available": True}},
        {"lineup_injury": {"available": True}},
    )

    for team in teams:
        for signals in signal_sets:
            for index in range(12):
                verdict = render_verdict_v2(
                    ctx(
                        match_key=f"{team}_{index}_{tuple(signals)[0]}",
                        home_name=team,
                        away_name="Chelsea",
                        recommended_team=team,
                        outcome_label=team,
                        nickname=None,
                        coach=None,
                        signals=signals,
                    )
                )
                assert verdict.valid
                assert "'s the" not in verdict.text
                assert "s's" not in verdict.text


def test_v2_wrong_team_sunrisers_in_delhi_chennai_fails_integrity():
    context = ctx(
        match_key="delhi_capitals_vs_chennai_super_kings",
        sport="cricket",
        league="ipl",
        home_name="Delhi Capitals",
        away_name="Chennai Super Kings",
        recommended_team="Chennai Super Kings",
        outcome_label="Chennai Super Kings",
        nickname="Chennai",
    )

    errors = validate_team_integrity(
        "Sunrisers Hyderabad at 2.05 with Betway — back Chennai Super Kings, standard stake.",
        context,
    )

    assert "third_team_reference:Sunrisers Hyderabad" in errors


def test_v2_safe_shell_uses_recommended_team_only():
    context = ctx(
        match_key="delhi_capitals_vs_chennai_super_kings",
        sport="cricket",
        league="ipl",
        home_name="Delhi Capitals",
        away_name="Chennai Super Kings",
        recommended_team="Chennai Super Kings",
        outcome_label="Chennai Super Kings",
        nickname=None,
        signals={},
    )

    verdict = render_verdict_v2(context)

    assert verdict.fallback
    assert verdict.valid
    assert verdict.primary_fact_type == "safe_shell"
    assert "Chennai Super Kings" in verdict.text
    assert "Sunrisers Hyderabad" not in verdict.text
    assert "Delhi Capitals" not in verdict.text
    assert len(verdict.text) <= 120


def test_v2_uses_team_or_approved_nickname():
    verdict = render_verdict_v2(ctx())

    assert verdict.valid
    assert "Liverpool" in verdict.text or "the Reds" in verdict.text or "Slot's Reds" in verdict.text
    assert validate_team_integrity(verdict.text, ctx()) == []


def test_v2_handles_missing_optional_evidence():
    context = ctx(
        odds=None,
        bookmaker=None,
        venue=None,
        coach=None,
        nickname=None,
        bookmaker_count=None,
        evidence_pack=None,
    )

    verdict = render_verdict_v2(context)

    assert verdict.valid
    assert len(verdict.text) <= 200
    assert "Liverpool" in verdict.text
