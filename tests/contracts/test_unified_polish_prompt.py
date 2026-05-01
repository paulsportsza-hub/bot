
import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""FIX-NARRATIVE-ROT-ROOT-01 (Phase 3) — Unified polish prompt contract.

Phase 3 deliverables:
- Deliverable 1: CANONICAL MANAGERS hard-constraint block in EVERY polish path
  (closes LB-2 Amorim + LB-3 Nuno hallucination paths).
- Deliverable 2: verdict-cache uses the unified prompt builder (was inline
  hardcoded prompt with zero coaches injection).
- Deliverable 3: pregen sweep verification logs.

Contract guards (≥12 tests):
1.  CANONICAL MANAGERS block present + both surnames extracted
2.  Home unknown / away known
3.  Both unknown
4.  Static-prefix token count meets Sonnet 1024 minimum (live count_tokens)
5.  DATA AVAILABILITY block reflects evidence pack flags
6.  Setup pricing ban present in every prompt branch
7.  Setup opening shape variation present in unified-builder prompt
8.  Diamond tier-aware tone band injected
9.  Bronze tier-aware tone band injected
10. Notts Forest verdict-cache regression — Pereira not Nuno (LB-3 closure)
11. Man Utd verdict-cache regression — Carrick not Amorim (LB-2 closure)
12. Per-model variation: builder accepts both 'sonnet' and 'haiku' classes
13. Coaches injection lands in DYNAMIC block (post-separator) not static
14. Static block still contains STYLE & OUTPUT GUIDE header (Rule 22 invariant)
15. CANONICAL MANAGERS includes the literal "you MUST use these surnames"
    instruction prefix in every branch
"""


import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make the bot worktree importable.
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)


_SPLIT_SENTINEL = "───────────── EVIDENCE PACK ─────────────"
_STYLE_GUIDE_HEADER = "───────────── STYLE & OUTPUT GUIDE ─────────────"
_PER_MATCH_HEADER = "───────────── PER-MATCH CONSTRAINTS ─────────────"
_CANONICAL_MGR_MARKER = "CANONICAL MANAGERS"
_DATA_AVAIL_MARKER = "DATA AVAILABILITY"
_SETUP_SHAPE_MARKER = "SETUP OPENING SHAPE"
_SONNET_MIN = 1024
_SONNET_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Coaches.json fixture — temp scrapers root for deterministic tests.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_coaches(monkeypatch):
    """Inject a deterministic coaches.json so lookup_coach() is stable."""
    tmp_root = tempfile.mkdtemp(prefix="fix_narrative_rot_root_01_")
    scrapers_dir = Path(tmp_root) / "scrapers"
    scrapers_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "soccer": {
            "arsenal": {"name": "Mikel Arteta"},
            "chelsea": {"name": "Enzo Maresca"},
            "manchester united": {"name": "Michael Carrick"},
            "manchester_united": {"name": "Michael Carrick"},
            "manchester utd": {"name": "Michael Carrick"},
            "nottingham forest": {"name": "Nuno Espírito Santo"},
            "nottingham_forest": {"name": "Nuno Espírito Santo"},
            "everton": {"name": "Sean Dyche"},
        }
    }
    # The brief uses 'Pereira' and 'Carrick' as the canonical surname targets
    # for the LB-3 / LB-2 regression — we override Forest to Pereira here so
    # the test reflects the brief's exact regression contract (Forest hired
    # Pereira post-Nuno per the brief's LB-3 description).
    payload["soccer"]["nottingham forest"] = {"name": "Vitor Pereira"}
    payload["soccer"]["nottingham_forest"] = {"name": "Vitor Pereira"}
    (scrapers_dir / "coaches.json").write_text(json.dumps(payload))
    monkeypatch.setenv("SCRAPERS_ROOT", str(scrapers_dir))
    # Bust the lookup cache so the new path is honoured.
    import narrative_spec
    narrative_spec._COACH_LOOKUP_CACHE = None
    yield
    narrative_spec._COACH_LOOKUP_CACHE = None


# ---------------------------------------------------------------------------
# Pack / spec helpers — minimal, deterministic, sport-aware.
# ---------------------------------------------------------------------------


def _build_pack(
    *,
    sport: str = "soccer",
    league: str = "EPL",
    home: str = "Arsenal",
    away: str = "Chelsea",
    home_coach: str = "",
    away_coach: str = "",
    h2h_available: bool = False,
    espn_available: bool = False,
    injuries_available: bool = False,
    movements_available: bool = False,
):
    from evidence_pack import (
        EvidencePack,
        ESPNContextBlock,
        EvidenceSource,
        H2HBlock,
        InjuriesBlock,
        MovementsBlock,
    )

    espn = None
    if espn_available or home_coach or away_coach:
        espn = ESPNContextBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at="2026-04-29T12:00:00+00:00",
                source_name="test",
                stale_minutes=0.0,
            ),
            data_available=espn_available,
            home_team={"name": home, "coach": home_coach},
            away_team={"name": away, "coach": away_coach},
            h2h=[],
            competition=league,
            season="2025-26",
        )
    h2h = None
    if h2h_available:
        h2h = H2HBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at="2026-04-29T12:00:00+00:00",
                source_name="test",
                stale_minutes=0.0,
            ),
            matches=[{
                "date": "2025-12-15",
                "home": home,
                "away": away,
                "home_score": 1,
                "away_score": 2,
                "competition": league,
            }],
        )
    injuries = None
    if injuries_available:
        injuries = InjuriesBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at="2026-04-29T12:00:00+00:00",
                source_name="test",
                stale_minutes=0.0,
            ),
            home_injuries=[{"name": "Player A", "status": "Out"}],
            away_injuries=[],
            total_injury_count=1,
        )
    movements = None
    if movements_available:
        movements = MovementsBlock(
            provenance=EvidenceSource(
                available=True,
                fetched_at="2026-04-29T12:00:00+00:00",
                source_name="test",
                stale_minutes=0.0,
            ),
            movements=[{"bookmaker": "hwb", "outcome": "home", "from": 2.10, "to": 2.05}],
            movement_count=1,
        )
    return EvidencePack(
        match_key=f"{home.lower().replace(' ', '_')}_vs_{away.lower().replace(' ', '_')}_2026-05-01",
        sport=sport,
        league=league,
        built_at="2026-04-29T12:00:00+00:00",
        pack_version=1,
        sa_odds=None,
        edge_state=None,
        espn_context=espn,
        h2h=h2h,
        news=None,
        sharp_lines=None,
        settlement_stats=None,
        movements=movements,
        injuries=injuries,
        richness_score="low",
        sources_available=0,
        sources_total=12,
        coverage_metrics=None,
    )


def _build_spec(
    *,
    home: str = "Arsenal",
    away: str = "Chelsea",
    edge_tier: str = "gold",
    tone_band: str = "moderate",
    bookmaker: str = "Hollywoodbets",
    odds: float = 2.10,
    verdict_action: str = "back",
):
    return SimpleNamespace(
        competition="Premier League",
        tone_band=tone_band,
        evidence_class="supported",
        verdict_action=verdict_action,
        verdict_sizing="0.5u",
        bookmaker=bookmaker,
        odds=odds,
        edge_tier=edge_tier,
        home_name=home,
        away_name=away,
    )


# ---------------------------------------------------------------------------
# Test 1 — both coaches present in coaches.json → CANONICAL MANAGERS block
# present, both surnames extracted.
# ---------------------------------------------------------------------------


def test_canonical_managers_with_both_in_coaches_json():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack(home="Arsenal", away="Chelsea")
    spec = _build_spec(home="Arsenal", away="Chelsea")
    static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    assert _CANONICAL_MGR_MARKER in dynamic, "CANONICAL MANAGERS missing"
    # Block must carry the imperative instruction (brief mandate).
    assert "you MUST use these surnames" in dynamic
    assert "NO substitutions" in dynamic
    # Both teams must be listed with surname-only directive.
    assert "Home: Arsenal — Mikel Arteta (refer as Arteta)" in dynamic
    assert "Away: Chelsea — Enzo Maresca (refer as Maresca)" in dynamic


# ---------------------------------------------------------------------------
# Test 2 — home coach missing, away coach present → "manager unknown" + Maresca.
# ---------------------------------------------------------------------------


def test_canonical_managers_home_missing_away_known():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack(home="Some FC", away="Chelsea")
    spec = _build_spec(home="Some FC", away="Chelsea")
    static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    assert "Home: Some FC — manager unknown — do not name the manager." in dynamic
    assert "Away: Chelsea — Enzo Maresca (refer as Maresca)" in dynamic


# ---------------------------------------------------------------------------
# Test 3 — both coaches absent in coaches.json → both "manager unknown".
# ---------------------------------------------------------------------------


def test_canonical_managers_both_missing():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack(home="Unknown FC", away="Other FC")
    spec = _build_spec(home="Unknown FC", away="Other FC")
    static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    assert "Home: Unknown FC — manager unknown — do not name the manager." in dynamic
    assert "Away: Other FC — manager unknown — do not name the manager." in dynamic


# ---------------------------------------------------------------------------
# Test 4 — static prefix still clears Sonnet 1024-token minimum (Rule 22).
# Live count_tokens — skipped when ANTHROPIC_API_KEY is unset.
# ---------------------------------------------------------------------------


def _has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


@pytest.mark.skipif(
    not _has_anthropic_key(),
    reason="ANTHROPIC_API_KEY required for live messages.count_tokens",
)
def test_static_prefix_meets_sonnet_minimum_with_canonical_managers():
    """Rule 22 invariant: static prefix MUST stay >= 1024 tokens after the
    canonical-managers + data-availability + opening-shape blocks land in
    the dynamic suffix. None of the new content can leak above the split.

    Synthetic estimate fallback: when the live count_tokens call fails (auth
    error in CI / sandbox env, network), fall back to a word-count-based
    proxy (words × 1.3 ≈ tokens — Anthropic-published heuristic). The proxy
    still catches the regression we care about (static prefix shrinking by
    hundreds of tokens) without flaking on infra issues.
    """
    import importlib
    for _mod in list(sys.modules):
        if _mod == "anthropic" or _mod.startswith("anthropic."):
            sys.modules.pop(_mod, None)
    anthropic = importlib.import_module("anthropic")

    from evidence_pack import format_evidence_prompt

    pack = _build_pack(home="Arsenal", away="Chelsea")
    spec = _build_spec(home="Arsenal", away="Chelsea")
    static, _dynamic = format_evidence_prompt(pack, spec, return_split=True)

    tokens: int
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.count_tokens(
            model=_SONNET_MODEL,
            messages=[{"role": "user", "content": static}],
        )
        tokens = resp.input_tokens
    except Exception as exc:
        # Auth / network failure → fall back to synthetic estimate.
        msg = str(exc).lower()
        if "auth" not in msg and "401" not in msg and "api" not in msg and "network" not in msg:
            raise
        tokens = int(len(static.split()) * 1.3)

    assert tokens >= _SONNET_MIN, (
        f"Static prefix is {tokens} tokens — below {_SONNET_MIN}."
    )


# ---------------------------------------------------------------------------
# Test 5 — DATA AVAILABILITY block reflects evidence pack flags (h2h=False).
# ---------------------------------------------------------------------------


def test_data_availability_h2h_false_emits_must_not_cite():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack(h2h_available=False)
    spec = _build_spec()
    _static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    assert _DATA_AVAIL_MARKER in dynamic
    assert "H2H: data_available=False" in dynamic
    # When data_available=False the instruction must mandate vague language.
    assert "MUST NOT cite specific match counts" in dynamic


def test_data_availability_h2h_true_allows_citing():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack(h2h_available=True)
    spec = _build_spec()
    _static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    assert "H2H: data_available=True" in dynamic
    assert "you MAY cite the H2H sentence injected after generation" in dynamic


# ---------------------------------------------------------------------------
# Test 6 — Setup pricing ban present in every prompt branch (edge + preview).
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1: "
        "Setup section instructions stripped from polish prompt. The price-"
        "free-zone block is no longer emitted; the polish path is verdict-only."
    )
)
def test_setup_price_free_zone_in_every_branch():
    """Superseded — see test_verdict_prompt_anchors.py for the new spec."""


# ---------------------------------------------------------------------------
# Test 7 — Setup opening shape variation present in unified-builder prompt.
# ---------------------------------------------------------------------------


def test_setup_opening_shape_in_unified_builder():
    import bot

    pack = _build_pack(home="Arsenal", away="Chelsea")
    spec = _build_spec(home="Arsenal", away="Chelsea")
    static, dynamic = bot._build_unified_polish_prompt(
        pack, spec, edge_tier="gold", model_class="sonnet"
    )

    assert _SETUP_SHAPE_MARKER in dynamic
    # FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-29) AC-5: the prompt now
    # injects ONE pattern (MD5-deterministic on match_key), not all 6. The
    # selected pattern label MUST be one of the 6 catalogue entries — the
    # underlying ``_OPENING_PATTERNS`` tuple is the source of truth.
    selected_label, selected_example = bot._select_opening_pattern(
        getattr(pack, "match_key", "") or ""
    )
    assert selected_label in dynamic, (
        f"Selected pattern label {selected_label!r} not injected into dynamic block"
    )
    assert selected_example in dynamic, (
        f"Selected pattern example {selected_example!r} not injected into dynamic block"
    )
    # Reverse contract: the OTHER 5 pattern labels MUST NOT all appear (single-
    # pattern injection means only the selected label appears in the SETUP
    # OPENING SHAPE block).
    other_labels = [
        label for label, _ in bot._OPENING_PATTERNS if label != selected_label
    ]
    other_count = sum(1 for label in other_labels if label in dynamic)
    assert other_count == 0, (
        f"Multi-pattern leak: {other_count}/5 non-selected labels appeared in dynamic block"
    )
    assert "DO NOT default to the manager-led mould" in dynamic


# ---------------------------------------------------------------------------
# Test 8 — Tier-aware tone for Diamond → confident/strong band injected.
# ---------------------------------------------------------------------------


def test_tone_band_diamond_confident_or_strong():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack()
    spec = _build_spec(edge_tier="diamond", tone_band="strong")
    full = format_evidence_prompt(pack, spec)
    assert "TONE BAND: strong" in full


# ---------------------------------------------------------------------------
# Test 9 — Tier-aware tone for Bronze → cautious band injected.
# ---------------------------------------------------------------------------


def test_tone_band_bronze_cautious():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack()
    spec = _build_spec(edge_tier="bronze", tone_band="cautious")
    full = format_evidence_prompt(pack, spec)
    assert "TONE BAND: cautious" in full


# ---------------------------------------------------------------------------
# Test 10 — verdict-cache LB-3 regression: Forest → Pereira (NOT Nuno).
# ---------------------------------------------------------------------------


def test_verdict_cache_forest_uses_pereira_not_nuno():
    """LB-3 regression: Nottingham Forest's canonical manager is Pereira.
    The unified prompt MUST emit the Pereira surname constraint and MUST NOT
    silently allow 'Nuno' through.
    """
    import bot

    pack = _build_pack(home="Nottingham Forest", away="Arsenal")
    spec = _build_spec(home="Nottingham Forest", away="Arsenal")
    _static, dynamic = bot._build_unified_polish_prompt(
        pack, spec, edge_tier="gold", model_class="sonnet"
    )
    # Pereira must be the directive surname.
    assert "Vitor Pereira" in dynamic
    assert "(refer as Pereira)" in dynamic
    # The OLD coach surname Nuno MUST NOT appear in the canonical managers
    # block — its presence anywhere in the dynamic prompt is the LB-3
    # hallucination signal we must close.
    _block_start = dynamic.find(_CANONICAL_MGR_MARKER)
    assert _block_start >= 0
    _block_text = dynamic[_block_start:_block_start + 600]
    assert "Nuno" not in _block_text, (
        "LB-3 regression: 'Nuno' leaked into the CANONICAL MANAGERS block — "
        "the canonical surname must be Pereira."
    )


# ---------------------------------------------------------------------------
# Test 11 — verdict-cache LB-2 regression: Man Utd → Carrick (NOT Amorim).
# ---------------------------------------------------------------------------


def test_verdict_cache_man_utd_uses_carrick_not_amorim():
    """LB-2 regression: per the test fixture, Man Utd's canonical manager is
    Carrick. The unified prompt MUST emit the Carrick surname constraint and
    MUST NOT allow 'Amorim' to surface.
    """
    import bot

    pack = _build_pack(home="Manchester United", away="Liverpool")
    spec = _build_spec(home="Manchester United", away="Liverpool")
    _static, dynamic = bot._build_unified_polish_prompt(
        pack, spec, edge_tier="gold", model_class="sonnet"
    )
    assert "Michael Carrick" in dynamic
    assert "(refer as Carrick)" in dynamic
    _block_start = dynamic.find(_CANONICAL_MGR_MARKER)
    assert _block_start >= 0
    _block_text = dynamic[_block_start:_block_start + 600]
    assert "Amorim" not in _block_text, (
        "LB-2 regression: 'Amorim' leaked into the CANONICAL MANAGERS block — "
        "the canonical surname must be Carrick."
    )


# ---------------------------------------------------------------------------
# Test 12 — Per-model variation: Haiku and Sonnet produce identical prompts;
# only the documented max_tokens differ at the caller (this is a model_class
# acceptance test that the builder does not bifurcate the prompt).
# ---------------------------------------------------------------------------


def test_unified_builder_accepts_haiku_and_sonnet():
    import bot

    pack = _build_pack(home="Arsenal", away="Chelsea")
    spec = _build_spec(home="Arsenal", away="Chelsea")
    s_sonnet, d_sonnet = bot._build_unified_polish_prompt(
        pack, spec, edge_tier="gold", model_class="sonnet"
    )
    s_haiku, d_haiku = bot._build_unified_polish_prompt(
        pack, spec, edge_tier="gold", model_class="haiku"
    )
    # Prompt body identical regardless of model_class — caller varies max_tokens.
    assert s_sonnet == s_haiku
    assert d_sonnet == d_haiku


# ---------------------------------------------------------------------------
# Test 13 — Coaches injection lands in DYNAMIC (post-separator) block, not
# static. Asserts CANONICAL MANAGERS does NOT bloat the cacheable static
# prefix and lives below the EVIDENCE PACK split.
# ---------------------------------------------------------------------------


def test_canonical_managers_lands_in_dynamic_not_static():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack()
    spec = _build_spec()
    static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    assert _CANONICAL_MGR_MARKER not in static, (
        "Rule 22 invariant violated: CANONICAL MANAGERS leaked into the "
        "cacheable static prefix — per-match interpolation must stay below "
        "the EVIDENCE PACK split."
    )
    assert _CANONICAL_MGR_MARKER in dynamic
    # Same invariant for DATA AVAILABILITY (Phase 3 deliverable 1).
    assert _DATA_AVAIL_MARKER not in static
    assert _DATA_AVAIL_MARKER in dynamic


# ---------------------------------------------------------------------------
# Test 14 — Static block still contains STYLE & OUTPUT GUIDE header (Rule 22
# invariant — sacred existing block must survive Phase 3 additions).
# ---------------------------------------------------------------------------


def test_style_guide_header_still_in_static_after_phase3():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack()
    spec = _build_spec()
    static, _dynamic = format_evidence_prompt(pack, spec, return_split=True)

    assert _STYLE_GUIDE_HEADER in static, (
        "Rule 22 invariant violated: STYLE & OUTPUT GUIDE header dropped "
        "from static prefix — Phase 3 additions must not displace existing "
        "static content."
    )


# ---------------------------------------------------------------------------
# Test 15 — sanity belt: the 'you MUST use these surnames; NO substitutions'
# instruction prefix appears verbatim per the brief mandate. Locked Phase 3
# AC-3.2.
# ---------------------------------------------------------------------------


def test_canonical_managers_directive_prefix_verbatim():
    from evidence_pack import format_evidence_prompt

    pack = _build_pack()
    spec = _build_spec()
    _static, dynamic = format_evidence_prompt(pack, spec, return_split=True)

    expected = "CANONICAL MANAGERS (you MUST use these surnames; NO substitutions):"
    assert expected in dynamic
