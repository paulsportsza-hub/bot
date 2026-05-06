"""BUILD-VERDICT-V2-CALLERS-VERIFY-02 carry-over smoke guards.

All production verdict callers must converge on verdict_corpus.render_verdict().
That wrapper owns the VERDICT_ENGINE_V2 flag, so callers must not import the
engine directly or keep a separate synthesis implementation.
"""
from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]


def _slice_between(source: str, start: str, end: str | None = None) -> str:
    start_idx = source.index(start)
    if end is None:
        return source[start_idx:]
    end_idx = source.index(end, start_idx)
    return source[start_idx:end_idx]


def test_bot_enrich_tip_for_card_routes_through_v2_wrapper() -> None:
    src = (_ROOT / "bot.py").read_text(encoding="utf-8")
    block = _slice_between(
        src,
        "def _enrich_tip_for_card(tip: dict, match_key: str = \"\")",
        "# 11) Top tipsters",
    )

    assert "from verdict_corpus import render_verdict as _ns_render_verdict" in block
    assert "_fresh = _ns_render_verdict(_live_spec)" in block
    assert "verdict_engine_v2" not in block


def test_pregen_generate_one_routes_through_v2_wrapper() -> None:
    src = (_ROOT / "scripts" / "pregenerate_narratives.py").read_text(encoding="utf-8")
    block = _slice_between(
        src,
        "async def _generate_one(",
        "async def _verify_and_fill_cache(",
    )

    assert "from verdict_corpus import render_verdict as _rv_det" in block
    assert "_verdict_html = _rv_det(spec)" in block
    assert "verdict_engine_v2" not in block


def test_card_synthesis_routes_through_v2_wrapper() -> None:
    src = (_ROOT / "card_data.py").read_text(encoding="utf-8")
    block = _slice_between(
        src,
        "def _synthesize_breakdown_row_from_baseline(match_id: str)",
        "# FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01",
    )

    assert "import verdict_corpus" in src
    assert "verdict_corpus.render_verdict(spec)" in block
    assert "CARD_DATA_SYNTHESIS_VERDICT_RENDER_FAIL" in block
    assert "CARD_DATA_SYNTHESIS_VERDICT_RENDER_EMPTY" in block
    assert "verdict_html (empty" not in block
    assert "verdict_engine_v2" not in block
