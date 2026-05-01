"""FIX-PREGEN-STATIC-PREFIX-PURE-01 — Polish-path cache_control prefix threshold.

The cache_control directive on the polish-path system prompt is no-op'd by
Anthropic when the static prefix is below the model minimum (1024 tokens for
Sonnet, 2048 for Haiku). Pre-fix: non-combat Sonnet polish prefix was 823
tokens — sub-threshold. The reorder in evidence_pack.format_evidence_prompt()
moves all literal-content blocks (OUTPUT FORMAT, BANNED PHRASES, VERDICT
BODY EXCLUSION) above the EVIDENCE PACK split sentinel so the prefix clears
1024 tokens with a target of 1500-1700 (per INV-PREGEN-STATIC-PREFIX-DRIFT-01
G5 projection).

Tests:
- test_static_prefix_meets_sonnet_minimum_non_combat: live count_tokens
  against a soccer edge fixture must return >= 1024 input_tokens for the
  static prefix. Skips when ANTHROPIC_API_KEY is unset (CI-friendly).
- test_static_prefix_meets_sonnet_minimum_combat: same for combat sport
  (MMA) — combat fixtures already cleared 1024 pre-fix (1168) but must still
  clear post-fix (target 1800-2000).
- test_split_sentinel_preserved: structural test (no API) — confirms the
  EVIDENCE PACK separator is still the split point and that the static prefix
  carries the new STYLE & OUTPUT GUIDE block while the dynamic suffix carries
  the new PER-MATCH CONSTRAINTS block.
- test_static_block_carries_moved_content: structural test — asserts that the
  4 named blocks per INV-G4 (OUTPUT FORMAT section descriptions, BANNED
  PHRASES, VERDICT BODY EXCLUSION) live in the static prefix (above split).
- test_dynamic_block_carries_per_match_interpolation: structural test —
  asserts that per-match interpolations (tone_band, verdict_action,
  bookmaker @ odds) stay in the dynamic suffix (below split).
"""

from __future__ import annotations

import os
import sys

import pytest

# Add bot root to sys.path so we can import evidence_pack directly. We
# intentionally do NOT call config.ensure_scrapers_importable() — this test
# only needs evidence_pack (a bot-tree module), and ensure_scrapers_importable
# prepends SCRAPERS_ROOT.parent which exposes a scrapers/contracts shadow that
# breaks tests/contracts/test_contracts_package.py + test_scraper_health_monitor.py
# (separate tracked failures unrelated to this fix).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


_SONNET_MINIMUM = 1024
_SONNET_MODEL = "claude-sonnet-4-6"
_SPLIT_SENTINEL = "───────────── EVIDENCE PACK ─────────────"
_STYLE_GUIDE_HEADER = "───────────── STYLE & OUTPUT GUIDE ─────────────"
_PER_MATCH_HEADER = "───────────── PER-MATCH CONSTRAINTS ─────────────"


def _minimal_pack(sport: str = "soccer", league: str = "EPL"):
    """Build a minimal EvidencePack — all block fields None (= unavailable)."""
    from evidence_pack import EvidencePack

    return EvidencePack(
        match_key="arsenal_vs_chelsea_2026-05-01",
        sport=sport,
        league=league,
        built_at="2026-04-28T12:00:00+00:00",
        pack_version=1,
        sa_odds=None,
        edge_state=None,
        espn_context=None,
        h2h=None,
        news=None,
        sharp_lines=None,
        settlement_stats=None,
        movements=None,
        injuries=None,
        richness_score="low",
        sources_available=0,
        sources_total=12,
        coverage_metrics=None,
    )


def _stub_spec(
    home: str = "Arsenal",
    away: str = "Chelsea",
    bookmaker: str = "Hollywoodbets",
    odds: float = 2.10,
    edge_tier: str = "gold",
    verdict_action: str = "back",
):
    """Build a minimal stub spec — only the attrs format_evidence_prompt reads."""
    from types import SimpleNamespace

    return SimpleNamespace(
        competition="Premier League",
        tone_band="moderate",
        evidence_class="supported",
        verdict_action=verdict_action,
        verdict_sizing="0.5u",
        bookmaker=bookmaker,
        odds=odds,
        edge_tier=edge_tier,
        home_name=home,
        away_name=away,
    )


def _has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _count_tokens(text: str, model: str) -> int:
    """Live messages.count_tokens via the Anthropic SDK.

    Force-reload anthropic to defeat fake modules left in sys.modules by
    earlier contract tests (e.g. test_anthropic_client.py installs a fake
    `anthropic` module via monkeypatch that leaks across the session).
    """
    import importlib
    import sys

    for _mod in list(sys.modules):
        if _mod == "anthropic" or _mod.startswith("anthropic."):
            sys.modules.pop(_mod, None)
    anthropic = importlib.import_module("anthropic")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return resp.input_tokens


@pytest.mark.skipif(
    not _has_anthropic_key(),
    reason="ANTHROPIC_API_KEY required for live messages.count_tokens",
)
def test_static_prefix_meets_sonnet_minimum_non_combat() -> None:
    """AC-3: non-combat Sonnet edge polish prefix must clear 1024-token min."""
    from evidence_pack import format_evidence_prompt

    pack = _minimal_pack(sport="soccer")
    spec = _stub_spec()
    static, _dynamic = format_evidence_prompt(pack, spec, return_split=True)

    tokens = _count_tokens(static, model=_SONNET_MODEL)

    assert tokens >= _SONNET_MINIMUM, (
        f"Non-combat Sonnet static prefix is {tokens} tokens — below "
        f"{_SONNET_MINIMUM}-token minimum. cache_control will be silently "
        "no-op'd. Reorder regression: confirm OUTPUT FORMAT / BANNED PHRASES "
        "/ VERDICT BODY EXCLUSION blocks moved above the EVIDENCE PACK split."
    )


@pytest.mark.skipif(
    not _has_anthropic_key(),
    reason="ANTHROPIC_API_KEY required for live messages.count_tokens",
)
def test_static_prefix_meets_sonnet_minimum_combat() -> None:
    """AC-3: combat Sonnet edge polish prefix must clear 1024-token min."""
    from evidence_pack import format_evidence_prompt

    pack = _minimal_pack(sport="mma")
    spec = _stub_spec()
    static, _dynamic = format_evidence_prompt(pack, spec, return_split=True)

    tokens = _count_tokens(static, model=_SONNET_MODEL)

    assert tokens >= _SONNET_MINIMUM, (
        f"Combat Sonnet static prefix is {tokens} tokens — below "
        f"{_SONNET_MINIMUM}-token minimum. Combat fixtures cleared 1024 "
        "pre-fix (1168) so a regression here means the COMBAT-SPORT EVIDENCE "
        "LAW block was dropped from above the split."
    )


def test_split_sentinel_preserved() -> None:
    """AC-2: the cache_control split point must remain at EVIDENCE PACK.

    Structural test — no Anthropic API required. Confirms:
    - The split helper still finds the EVIDENCE PACK sentinel.
    - The static prefix carries the new STYLE & OUTPUT GUIDE block.
    - The dynamic suffix carries the new PER-MATCH CONSTRAINTS block.
    """
    from evidence_pack import format_evidence_prompt

    for sport, match_preview in [
        ("soccer", False),
        ("mma", False),
        ("soccer", True),
    ]:
        pack = _minimal_pack(sport=sport)
        spec = _stub_spec()
        result = format_evidence_prompt(
            pack, spec, match_preview=match_preview, return_split=True
        )

        assert isinstance(result, tuple) and len(result) == 2, (
            f"return_split=True must return a 2-tuple (static, dynamic) for "
            f"sport={sport} match_preview={match_preview}"
        )
        static, dynamic = result

        # Sentinel is the join boundary — appears in dynamic, not static.
        assert _SPLIT_SENTINEL in dynamic, (
            f"Split sentinel missing from dynamic block for "
            f"sport={sport} match_preview={match_preview}"
        )
        assert _SPLIT_SENTINEL not in static, (
            f"Split sentinel leaked into static prefix for "
            f"sport={sport} match_preview={match_preview} — split logic broken"
        )

        # Reorder structural markers
        assert _STYLE_GUIDE_HEADER in static, (
            f"STYLE & OUTPUT GUIDE header missing from static prefix for "
            f"sport={sport} match_preview={match_preview} — reorder regression"
        )
        assert _PER_MATCH_HEADER in dynamic, (
            f"PER-MATCH CONSTRAINTS header missing from dynamic suffix for "
            f"sport={sport} match_preview={match_preview} — reorder regression"
        )


def test_static_block_carries_moved_content() -> None:
    """FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1:
    the polish path now produces verdict-only output. The static prefix carries
    the new STYLE & OUTPUT GUIDE wrapper + the 4-anchor verdict spec block
    (MANDATORY ANCHORS, CLOSE WITH ACTION, GOOD/BAD examples, no-hedging /
    no-telemetry rules) — Setup/Edge/Risk section instructions are stripped.
    """
    from evidence_pack import format_evidence_prompt

    for sport, match_preview, expected_in_static in [
        ("soccer", False, [
            "STYLE & OUTPUT GUIDE",
            "⛔ BRAAI VOICE — NOT QUANT VOICE.",
            "MANDATORY ANCHORS",
            "CLOSE WITH ACTION",
            "Slot's Reds at home in front of Anfield",
            "data has a cleaner read on X",
            "NO HEDGING OPENERS",
            "NO TELEMETRY VOCAB",
        ]),
        ("soccer", True, [
            "STYLE & OUTPUT GUIDE",
            "⛔ BRAAI VOICE — NOT QUANT VOICE.",
            "MANDATORY ANCHORS",
            "CLOSE WITH ACTION",
            "Slot's Reds at home in front of Anfield",
            "data has a cleaner read on X",
        ]),
    ]:
        pack = _minimal_pack(sport=sport)
        spec = _stub_spec()
        static, _dynamic = format_evidence_prompt(
            pack, spec, match_preview=match_preview, return_split=True
        )

        for marker in expected_in_static:
            assert marker in static, (
                f"Marker {marker!r} missing from static prefix for "
                f"sport={sport} match_preview={match_preview}"
            )


def test_dynamic_block_carries_per_match_interpolation() -> None:
    """AC-2: per-match interpolation (tone_band, verdict_action, bookmaker @
    odds, _tier_key) stays in the dynamic suffix — must NOT leak into the
    cached static prefix or the cache key fragments per match.
    """
    from evidence_pack import format_evidence_prompt

    pack = _minimal_pack(sport="soccer")
    spec = _stub_spec(
        bookmaker="Hollywoodbets",
        odds=2.10,
        edge_tier="diamond",
        verdict_action="back",
    )
    static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    # tone_band interpolation
    assert "TONE BAND: moderate" in dynamic
    assert "TONE BAND: moderate" not in static

    # verdict_action interpolation
    assert "Action: back" in dynamic
    assert "Action: back" not in static

    # bookmaker @ odds interpolation
    assert "Hollywoodbets at 2.1" in dynamic
    assert "Hollywoodbets at 2.1" not in static

    # _tier_key (diamond) conditional in _verdict_quality_lines
    assert "DIAMOND TIER ONLY" in dynamic
    assert "DIAMOND TIER ONLY" not in static
