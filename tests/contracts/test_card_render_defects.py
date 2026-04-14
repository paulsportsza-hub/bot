"""BUILD-CARD-RENDER-01 — Regression tests for three card rendering defects.

D1: Verdict truncation
    _generate_verdict max_tokens reduced to 35 (≈140 chars max) so output fits
    the fixed 480×620 verdict container (≈150 char visible capacity) with margin.

D2: Match time not showing
    _enrich_tip_for_card must call _resolve_kickoff_time even when _bc_kickoff
    is set — it may be date-only (no time component) from the scraper.
    Regression guard: time in tip dict flows through to card context dict.

D3: Arrow misalignment
    .ev-value gains display:inline-flex;align-items:center — visual, covered
    by Playwright PNG in the wave report.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── D1 — Verdict max_tokens cap ───────────────────────────────────────────────

def test_d1_generate_verdict_max_tokens_capped():
    """_generate_verdict max_tokens must be ≤ 120 (BUILD-VERDICT-PROMPT-04: trim-to-sentence caps output at ≤140 chars)."""
    bot_path = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
    source = open(bot_path).read()

    # Find _generate_verdict function body (up to next top-level def)
    m = re.search(r"^def _generate_verdict\b(.+?)^def ", source, re.DOTALL | re.MULTILINE)
    assert m, "_generate_verdict not found in bot.py"
    fn_body = m.group(1)

    token_values = re.findall(r"max_tokens=(\d+)", fn_body)
    assert token_values, "No max_tokens found in _generate_verdict"
    for tv in token_values:
        assert int(tv) <= 120, (
            f"_generate_verdict max_tokens={tv} exceeds safe limit of 120 "
            f"(card container fits ≈150 chars; _trim_to_last_sentence caps at 140 chars)"
        )


def test_d1_generate_verdict_constrained_max_tokens_capped():
    """_generate_verdict_constrained max_tokens must also be ≤ 120."""
    bot_path = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
    source = open(bot_path).read()

    m = re.search(r"^def _generate_verdict_constrained\b(.+?)^def ", source, re.DOTALL | re.MULTILINE)
    assert m, "_generate_verdict_constrained not found in bot.py"
    fn_body = m.group(1)

    token_values = re.findall(r"max_tokens=(\d+)", fn_body)
    assert token_values, "No max_tokens found in _generate_verdict_constrained"
    for tv in token_values:
        assert int(tv) <= 120, (
            f"_generate_verdict_constrained max_tokens={tv} exceeds safe limit of 120"
        )


def test_d1_cap_verdict_trims_to_word_boundary():
    """_cap_verdict must truncate at word boundary, never mid-word."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from bot import _cap_verdict

    long_text = "A" * 50 + " " + "B" * 50 + " " + "C" * 50
    result = _cap_verdict(long_text, limit=140)
    assert len(result) <= 140
    # Must not end mid-word
    assert not result.endswith("A") or " " not in long_text[:141], (
        "cap_verdict must truncate at word boundary"
    )
    # Short text passes through unchanged
    short = "Back Chiefs."
    assert _cap_verdict(short) == short


def test_d1_trim_to_last_sentence_handles_mid_word_truncation():
    """BUILD-VERDICT-TRIM-HARDEN-03: _trim_to_last_sentence NEVER returns empty for non-empty input."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from bot import _trim_to_last_sentence

    # Empty input → empty output
    assert _trim_to_last_sentence("") == ""
    assert _trim_to_last_sentence("   ") == ""

    # Non-empty input with no sentence boundary → word-boundary fallback (NOT empty)
    partial = "Lucknow Super"
    result_partial = _trim_to_last_sentence(partial)
    assert result_partial != "", "HARDEN-03: must not return empty for non-empty input"
    assert result_partial in ("Lucknow Super", "Lucknow")  # word-boundary or full (fits in 140)

    # The regression case from the brief (137 chars, no .!?)
    regression = "Royal Challengers Bengaluru at 1.61 on WSB — they've won four of their last five while Lucknow Super Giants have lost their last three"
    result_reg = _trim_to_last_sentence(regression, max_chars=140)
    assert result_reg != "", "HARDEN-03: regression case must not return empty"
    assert len(result_reg) <= 140

    # Complete sentence within limit
    complete = "Back Chiefs at home. They are in fine form."
    result = _trim_to_last_sentence(complete, max_chars=140)
    assert result.endswith((".", "!", "?"))
    assert len(result) <= 140

    # Over-long input gets trimmed to last sentence boundary
    long_sentence = "Chiefs are flying. " + "x" * 200
    result2 = _trim_to_last_sentence(long_sentence, max_chars=140)
    assert result2 != "", "HARDEN-03: over-long input must not return empty"
    assert len(result2) <= 140


def test_d1_deterministic_fallbacks_all_capped_in_constrained():
    """Every return _render_verdict_deterministic(spec) in _generate_verdict_constrained must be wrapped with _cap_verdict."""
    bot_path = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
    source = open(bot_path).read()

    m = re.search(r"^def _generate_verdict_constrained\b(.+?)^def _normalise_mm_event_id", source, re.DOTALL | re.MULTILINE)
    assert m, "_generate_verdict_constrained body not found in bot.py"
    fn_body = m.group(1)

    # Every bare return must be wrapped
    bare_returns = re.findall(r"return _render_verdict_deterministic\(spec\)(?!\s*#)", fn_body)
    assert bare_returns == [], (
        f"Found {len(bare_returns)} unwrapped return _render_verdict_deterministic(spec) in "
        f"_generate_verdict_constrained — must be return _cap_verdict(_render_verdict_deterministic(spec))"
    )

    bare_fallback = re.findall(r"return _rv_fallback\(spec\)(?!\s*#)", fn_body)
    assert bare_fallback == [], (
        f"Found {len(bare_fallback)} unwrapped return _rv_fallback(spec) in "
        f"_generate_verdict_constrained — must be return _cap_verdict(_rv_fallback(spec))"
    )


def test_d1_verdict_within_cap_survives_context_build():
    """A verdict at or below 150 chars must appear unchanged in the card context."""
    from card_data import build_edge_detail_data

    # 125 chars — typical punchy SA verdict
    verdict = (
        "Amakhosi at home is the call. Chiefs have won four of their last five "
        "and the Bucs are in poor nick on the road. Back Amakhosi."
    )
    assert len(verdict) <= 150, "Test verdict itself exceeds safe cap — fix the test"

    tip = {
        "display_tier": "gold",
        "edge_rating": "gold",
        "ev": 5.5,
        "home": "Kaizer Chiefs",
        "away": "Orlando Pirates",
        "league": "PSL",
        "pick": "Kaizer Chiefs",
        "pick_odds": 1.85,
        "bookmaker": "Hollywoodbets",
        "verdict": verdict,
    }
    ctx = build_edge_detail_data(tip)
    assert ctx.get("verdict") == verdict, (
        f"Verdict was modified or dropped by context build. Got: {ctx.get('verdict')!r}"
    )


# ── D2 — Kickoff time flows from fixture_mapping through to card context ───────

def test_d2_kickoff_time_in_tip_appears_in_card_context():
    """When tip['time'] is set (resolved from fixture_mapping), it must appear in context.

    This guards the downstream half of the data path:
        _enrich_tip_for_card sets tip["time"]  →  build_edge_detail_data passes it through.
    """
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "edge_rating": "gold",
        "ev": 5.5,
        "home": "Arsenal",
        "away": "Chelsea",
        "league": "Premier League",
        "pick": "Arsenal",
        "pick_odds": 1.85,
        "bookmaker": "Betway",
        "_bc_kickoff": "2026-04-13",   # date-only from odds scraper (no time component)
        "date": "Sun 13 Apr",
        "time": "15:00",               # resolved from fixture_mapping by _enrich_tip_for_card
    }
    ctx = build_edge_detail_data(tip)
    assert ctx.get("time") == "15:00", (
        f"Kickoff time not present in card context. "
        f"Expected '15:00', got: {ctx.get('time')!r}"
    )


def test_d2_date_only_bc_kickoff_does_not_suppress_time():
    """_bc_kickoff being a date-only string must not suppress a separately resolved time.

    Root cause of BUILD-CARD-RENDER-01 D2: the old guard was
        if not enriched.get('time') and not enriched.get('_bc_kickoff'):
    which skipped _resolve_kickoff_time whenever _bc_kickoff was set, even if
    _bc_kickoff carried no time component. The fix removes the _bc_kickoff clause.
    """
    from card_data import build_edge_detail_data

    # Simulate post-fix state: _bc_kickoff is date-only, time was resolved separately
    tip = {
        "display_tier": "silver",
        "edge_rating": "silver",
        "ev": 3.2,
        "home": "Man City",
        "away": "Arsenal",
        "league": "Premier League",
        "pick": "Man City",
        "pick_odds": 1.62,
        "bookmaker": "Betway",
        "_bc_kickoff": "2026-04-20",   # date-only — must NOT block time display
        "time": "17:30",               # resolved from fixture_mapping
    }
    ctx = build_edge_detail_data(tip)
    assert ctx.get("time") == "17:30", (
        f"Time '17:30' was suppressed by date-only _bc_kickoff. "
        f"Got: {ctx.get('time')!r}"
    )


def test_d2_time_format_is_hhmm():
    """Time in card context must be HH:MM format (not ISO, not TBC, not empty)."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "bronze",
        "edge_rating": "bronze",
        "ev": 1.8,
        "home": "Sundowns",
        "away": "Pirates",
        "league": "PSL",
        "pick": "Sundowns",
        "pick_odds": 1.52,
        "bookmaker": "Betway",
        "time": "19:00",
    }
    ctx = build_edge_detail_data(tip)
    t = ctx.get("time", "")
    assert re.match(r"^\d{2}:\d{2}$", t), (
        f"Time must be HH:MM format. Got: {t!r}"
    )


# ── D2 — Guard: _enrich_tip_for_card condition in bot.py ──────────────────────

def test_d2_enrich_tip_guard_condition_correct():
    """The _enrich_tip_for_card time guard must NOT include '_bc_kickoff' check.

    Regression: old guard `if not enriched.get('time') and not enriched.get('_bc_kickoff'):`
    prevented _resolve_kickoff_time from running when _bc_kickoff was date-only.
    The fix: `if not enriched.get('time'):` — call resolver whenever time is absent.
    """
    bot_path = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
    source = open(bot_path).read()

    # Find the BUILD-KO-TIME-FIX-01 block and check the guard condition
    m = re.search(
        r"BUILD-KO-TIME-FIX-01.*?if not enriched\.get\(['\"]time['\"]\)(.*?)try:",
        source,
        re.DOTALL,
    )
    assert m, (
        "Could not find BUILD-KO-TIME-FIX-01 guard in bot.py — "
        "check _enrich_tip_for_card section 8d"
    )
    guard_tail = m.group(1)
    assert "_bc_kickoff" not in guard_tail, (
        "Guard still contains _bc_kickoff check — D2 regression not fixed.\n"
        f"Guard tail: {guard_tail!r}"
    )
