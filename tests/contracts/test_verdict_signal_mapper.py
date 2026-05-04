"""Contract tests for verdict_signal_mapper (BUILD-VERDICT-SIGNAL-MAPPED-01).

Brief: Notion 355d9048d73c81f4a9b2ce69a63c7f27 — replace the 360-sentence
corpus main path with a deterministic signal-mapped builder. Corpus stays
as fallback. These tests guard:

  - All 8 §12 combination mappings × 4 tiers (exact verbatim output)
  - Banned-term scanner sweep (§15.1) on 200 synthetic specs (HG-3)
  - Live-commentary scanner sweep (§15.2) on 200 synthetic specs (HG-3)
  - Tier action sanity (§15.3): every output contains the expected fragment
  - Visible signal alignment (§15.4 / HG-6): if verdict mentions
    "price" → price_edge active; "form" → form active; "team news"
    → injury active; "market" → market or line_mvt active;
    "outside support" → tipster active.
  - Spec §12.8 fallback verbatim per tier when no signals fire
  - Feature flag (HG-5): USE_SIGNAL_MAPPED_VERDICTS=False routes to corpus
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import cast

import pytest

import verdict_signal_mapper as m


# ──────────────────────────────────────────────────────────────────────────
# §12 — exact combination mappings × 4 tiers
# ──────────────────────────────────────────────────────────────────────────

_TIERS = ("diamond", "gold", "silver", "bronze")

_DIAMOND_ACTION = "hard to look past Manchester City, go big at 1.40 on HWB"
_GOLD_ACTION = "back Manchester City, standard stake"
_SILVER_ACTION = "lean Manchester City, standard stake"
_BRONZE_ACTION = "worth a small play on Manchester City, light stake"

# Spec §12.1 — Price Edge + Form
@pytest.mark.parametrize("tier,expected", [
    ("diamond", f"The price hasn't caught up and recent form backs it — {_DIAMOND_ACTION}."),
    ("gold",    f"The price hasn't caught up and recent form backs it — {_GOLD_ACTION}."),
    ("silver",  f"The price hasn't caught up and recent form backs it — {_SILVER_ACTION}."),
    ("bronze",  f"The price hasn't caught up and recent form backs it — {_BRONZE_ACTION}."),
])
def test_combo_price_form(tier, expected):
    """§12.1 — Price Edge + Form: primary phrase + secondary phrase form."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={"price_edge": True, "form": True},
        odds="1.40", bookmaker="HWB",
    )
    assert out == expected


# Spec §12.2 — Price Edge + Injury
@pytest.mark.parametrize("tier,expected", [
    ("diamond", f"The price hasn't caught up and team news gives it extra weight — {_DIAMOND_ACTION}."),
    ("gold",    f"The price hasn't caught up and team news gives it extra weight — {_GOLD_ACTION}."),
    ("silver",  f"The price hasn't caught up and team news gives it extra weight — {_SILVER_ACTION}."),
    ("bronze",  f"The price hasn't caught up and team news gives it extra weight — {_BRONZE_ACTION}."),
])
def test_combo_price_injury(tier, expected):
    """§12.2 — Price Edge + Injury: primary then injury secondary."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={"price_edge": True, "injury": True},
        odds="1.40", bookmaker="HWB",
    )
    assert out == expected


# Spec §12.3 — Price Edge + Line Movement (favourable)
@pytest.mark.parametrize("tier,expected", [
    ("diamond", f"The line is moving our way and the price is still there — {_DIAMOND_ACTION}."),
    ("gold",    f"The line is moving our way and the price is still there — {_GOLD_ACTION}."),
    ("silver",  f"The line is moving our way and the price is still there — {_SILVER_ACTION}."),
    ("bronze",  f"The line is moving our way and the price is still there — {_BRONZE_ACTION}."),
])
def test_combo_price_line_favourable(tier, expected):
    """§12.3 — Price Edge + Line Movement (favourable): special-case lead."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={"price_edge": True, "line_mvt": True},
        odds="1.40", bookmaker="HWB",
        line_movement_direction="favourable",
    )
    assert out == expected


# Spec §12.4 — Price Edge + Line Movement (against)
@pytest.mark.parametrize("tier,expected", [
    ("diamond", f"The market has moved, but the price still looks big — {_DIAMOND_ACTION}."),
    ("gold",    f"The market has moved, but the price still looks big — {_GOLD_ACTION}."),
    ("silver",  f"The market has moved, but the price still looks big — {_SILVER_ACTION}."),
    ("bronze",  f"The market has moved, but the price still looks big — {_BRONZE_ACTION}."),
])
def test_combo_price_line_against(tier, expected):
    """§12.4 — Price Edge + Line Movement (against): contrast lead."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={"price_edge": True, "line_mvt": True},
        odds="1.40", bookmaker="HWB",
        line_movement_direction="against",
    )
    assert out == expected


# Spec §12.5 — Form only
@pytest.mark.parametrize("tier,expected", [
    ("diamond", f"Recent form backs this — {_DIAMOND_ACTION}."),
    ("gold",    f"Recent form backs this — {_GOLD_ACTION}."),
    ("silver",  f"Recent form backs this — {_SILVER_ACTION}."),
    ("bronze",  f"Recent form backs this — {_BRONZE_ACTION}."),
])
def test_combo_form_only(tier, expected):
    """§12.5 — Form only: clean causal shape."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={"form": True},
        odds="1.40", bookmaker="HWB",
    )
    assert out == expected


# Spec §12.6 — Market only
@pytest.mark.parametrize("tier,expected", [
    ("diamond", f"The wider market is leaning this way — {_DIAMOND_ACTION}."),
    ("gold",    f"The wider market is leaning this way — {_GOLD_ACTION}."),
    ("silver",  f"The wider market is leaning this way — {_SILVER_ACTION}."),
    ("bronze",  f"The wider market is leaning this way — {_BRONZE_ACTION}."),
])
def test_combo_market_only(tier, expected):
    """§12.6 — Market only."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={"market": True},
        odds="1.40", bookmaker="HWB",
    )
    assert out == expected


# Spec §12.7 — Tipster only
@pytest.mark.parametrize("tier,expected", [
    ("diamond", f"Outside support points this way — {_DIAMOND_ACTION}."),
    ("gold",    f"Outside support points this way — {_GOLD_ACTION}."),
    ("silver",  f"Outside support points this way — {_SILVER_ACTION}."),
    ("bronze",  f"Outside support points this way — {_BRONZE_ACTION}."),
])
def test_combo_tipster_only(tier, expected):
    """§12.7 — Tipster only (use sparingly, here as primary fallback)."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={"tipster": True},
        odds="1.40", bookmaker="HWB",
    )
    assert out == expected


# Spec §12.8 — No-strong-signals fallback
@pytest.mark.parametrize("tier,expected_lead", [
    ("diamond", "The price still looks too big for the setup"),
    ("gold",    "There is enough value here to support the pick"),
    ("silver",  "There is just enough value here"),
    ("bronze",  "Not much in it, but there is a small lean"),
])
def test_combo_no_signals_fallback(tier, expected_lead):
    """§12.8 — empty signals dict per tier → tier-specific fallback lead."""
    out = m.build_verdict(
        team="Manchester City", tier=tier,
        signals={}, odds="1.40", bookmaker="HWB",
    )
    assert out.startswith(expected_lead)


# ──────────────────────────────────────────────────────────────────────────
# §15.3 — Tier action sanity
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier,fragment", list(m.EXPECTED_ACTION.items()))
def test_tier_action_fragment_present(tier, fragment):
    """Every render for a given tier contains the expected action fragment."""
    out = m.build_verdict(
        team="Stormers", tier=tier,
        signals={"price_edge": True, "form": True},
        odds="2.10", bookmaker="Betway",
    )
    assert fragment in out


# ──────────────────────────────────────────────────────────────────────────
# §15.1 / §15.2 — banned-term + live-commentary sweep (HG-3)
# ──────────────────────────────────────────────────────────────────────────

def _synthetic_signal_combos() -> list[dict[str, bool]]:
    """All 64 combinations of the 6 signal booleans."""
    keys = ("price_edge", "line_mvt", "market", "tipster", "form", "injury")
    out = []
    for mask in range(2 ** len(keys)):
        out.append({k: bool((mask >> i) & 1) for i, k in enumerate(keys)})
    return out


def test_banned_term_sweep_200_synthetic_specs():
    """HG-3: 200 synthetic specs × 0 banned-term hits."""
    teams = ["Manchester City", "Arsenal", "Stormers", "Proteas", "Sundowns"]
    odds_values = ["1.40", "2.10", "3.50", None]
    bookmakers = ["HWB", "Betway", "Sportingbet", None]
    directions = ["favourable", "against", "unknown"]

    specs = []
    for tier in _TIERS:
        for combo_idx, combo in enumerate(_synthetic_signal_combos()):
            specs.append({
                "team":     teams[combo_idx % len(teams)],
                "tier":     tier,
                "signals":  combo,
                "odds":     odds_values[combo_idx % len(odds_values)],
                "bookmaker": bookmakers[combo_idx % len(bookmakers)],
                "line_movement_direction": directions[combo_idx % len(directions)],
            })

    # 64 × 4 = 256 specs; cap at 200 per HG-3 wording.
    specs = specs[:200]
    assert len(specs) == 200

    failures = []
    for s in specs:
        out = m.build_verdict(**s)
        ok, hits = m.validate_output(out)
        if not ok:
            failures.append((s, out, hits))
    assert failures == [], (
        f"banned-term hits in {len(failures)}/200 renders. First: {failures[0]}"
    )


def test_live_commentary_sweep_zero_hits():
    """HG-3 (§15.2): no live-match commentary terms in any combo."""
    failures = []
    for tier in _TIERS:
        for combo in _synthetic_signal_combos():
            out = m.build_verdict(
                team="Bafana", tier=tier, signals=combo,
                odds="1.85", bookmaker="HWB",
                line_movement_direction="favourable",
            )
            for term in m.LIVE_COMMENTARY_TERMS:
                if term.lower() in out.lower():
                    failures.append((tier, combo, term, out))
    assert failures == [], f"live-commentary hits: {failures[:3]}"


# ──────────────────────────────────────────────────────────────────────────
# §15.4 / HG-6 — visible signal alignment
# ──────────────────────────────────────────────────────────────────────────

def test_alignment_price_implies_price_edge_active():
    """If verdict mentions 'price' AND any signal is active, price_edge or line_mvt is True.

    The all-empty signal case routes to the §12.8 fallback lead, which uses
    pricing language by spec design (every edge is a price-driven concept).
    Alignment therefore only applies when at least one signal fired.
    """
    for tier in _TIERS:
        for combo in _synthetic_signal_combos():
            if not any(combo.values()):
                continue  # §12.8 fallback — pricing lead is by spec design
            out = m.build_verdict(
                team="Liverpool", tier=tier, signals=combo,
                odds="1.85", bookmaker="HWB",
                line_movement_direction="favourable",
            )
            if " price " in f" {out.lower()} ":
                assert combo.get("price_edge") or combo.get("line_mvt"), (
                    f"verdict mentions 'price' but neither price_edge nor line_mvt active. "
                    f"tier={tier} combo={combo} out={out}"
                )


def test_alignment_form_implies_form_active():
    """If verdict mentions 'form' (in active-signal mode), signals.form is True."""
    for tier in _TIERS:
        for combo in _synthetic_signal_combos():
            if not any(combo.values()):
                continue  # §12.8 fallback path — exempt
            out = m.build_verdict(
                team="Arsenal", tier=tier, signals=combo,
                odds="1.85", bookmaker="HWB",
                line_movement_direction="favourable",
            )
            if "form" in out.lower():
                assert combo.get("form"), (
                    f"verdict mentions 'form' but signals.form not active. "
                    f"tier={tier} combo={combo} out={out}"
                )


def test_alignment_team_news_implies_injury_active():
    """If verdict mentions 'team news', signals.injury is True."""
    for tier in _TIERS:
        for combo in _synthetic_signal_combos():
            if not any(combo.values()):
                continue
            out = m.build_verdict(
                team="Sundowns", tier=tier, signals=combo,
                odds="1.85", bookmaker="HWB",
                line_movement_direction="favourable",
            )
            if "team news" in out.lower():
                assert combo.get("injury"), (
                    f"verdict mentions 'team news' but signals.injury not active. "
                    f"tier={tier} combo={combo} out={out}"
                )


def test_alignment_market_implies_market_or_line_mvt_active():
    """If verdict mentions 'market', signals.market OR line_mvt is True."""
    for tier in _TIERS:
        for combo in _synthetic_signal_combos():
            if not any(combo.values()):
                continue
            out = m.build_verdict(
                team="Stormers", tier=tier, signals=combo,
                odds="1.85", bookmaker="HWB",
                line_movement_direction="favourable",
            )
            if "market" in out.lower():
                assert combo.get("market") or combo.get("line_mvt"), (
                    f"verdict mentions 'market' but neither market nor line_mvt active. "
                    f"tier={tier} combo={combo} out={out}"
                )


def test_alignment_outside_support_implies_tipster_active():
    """If verdict mentions 'outside support', signals.tipster is True."""
    for tier in _TIERS:
        for combo in _synthetic_signal_combos():
            if not any(combo.values()):
                continue
            out = m.build_verdict(
                team="Proteas", tier=tier, signals=combo,
                odds="1.85", bookmaker="HWB",
                line_movement_direction="favourable",
            )
            if "outside support" in out.lower():
                assert combo.get("tipster"), (
                    f"verdict mentions 'outside support' but signals.tipster not active. "
                    f"tier={tier} combo={combo} out={out}"
                )


# ──────────────────────────────────────────────────────────────────────────
# Feature flag (HG-5) — corpus fallback under USE_SIGNAL_MAPPED_VERDICTS=0
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class _FakeSpec:
    edge_tier: str = "diamond"
    sport: str = "soccer"
    outcome: str = "home"
    outcome_label: str = "Manchester City"
    home_name: str = "Manchester City"
    away_name: str = "Brentford"
    odds: float = 1.40
    bookmaker: str = "HWB"
    ev_pct: float = 5.5
    movement_direction: str = "for"
    bookmaker_count: int = 4
    tipster_available: bool = True
    # FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-01 (2026-05-04): tipster_agrees
    # mirrors the production NarrativeSpec field. Default True keeps existing
    # tests' "tipster fires" semantics — the new gate (P2) requires explicit
    # agreement, so this default models the "tipsters concur with the pick"
    # case that the original tests assumed implicitly.
    tipster_agrees: bool | None = True
    home_form: str = "WWWDW"
    away_form: str = "LDLDD"
    injuries_home: list = field(default_factory=list)
    injuries_away: list = field(default_factory=list)
    home_position: int | None = 1
    away_position: int | None = 17
    composite_score: float = 92.0
    support_level: int = 4
    contradicting_signals: int = 0
    fair_prob_pct: float = 75.0
    verdict_action: str = "strong back"
    match_key: str = "manchester_city_vs_brentford_2026-05-03"


def test_feature_flag_default_uses_signal_mapper(monkeypatch):
    """HG-5 default — flag absent → signal-mapped output."""
    monkeypatch.delenv("USE_SIGNAL_MAPPED_VERDICTS", raising=False)
    import verdict_corpus
    importlib.reload(verdict_corpus)
    out = verdict_corpus.render_verdict(cast("verdict_corpus.NarrativeSpec", _FakeSpec()))
    # Signal-mapper hits the §12.3 favourable special-case lead
    assert out.startswith("The line is moving our way and the price is still there")
    # And the action clause is the Diamond form
    assert "hard to look past Manchester City, go big at 1.40 on HWB" in out


def test_feature_flag_off_routes_to_corpus(monkeypatch):
    """HG-5 — flag=0 routes to legacy corpus path (rollback safety)."""
    monkeypatch.setenv("USE_SIGNAL_MAPPED_VERDICTS", "0")
    import verdict_corpus
    importlib.reload(verdict_corpus)
    out = verdict_corpus.render_verdict(cast("verdict_corpus.NarrativeSpec", _FakeSpec()))
    # Corpus output must NOT match the signal-mapped lead
    assert not out.startswith("The line is moving our way and the price is still there")
    # Corpus still produces a Diamond action ending — slot-filled
    assert "Manchester City" in out


def test_feature_flag_false_string_routes_to_corpus(monkeypatch):
    """Flag accepts '0' / 'false' / 'no' / 'off' as falsy."""
    for falsy in ("0", "false", "no", "off", "FALSE"):
        monkeypatch.setenv("USE_SIGNAL_MAPPED_VERDICTS", falsy)
        import verdict_corpus
        importlib.reload(verdict_corpus)
        out = verdict_corpus.render_verdict(cast("verdict_corpus.NarrativeSpec", _FakeSpec()))
        assert not out.startswith("The line is moving our way"), (
            f"flag={falsy!r} should route to corpus but signal-mapped fired"
        )


# ──────────────────────────────────────────────────────────────────────────
# Banned-term scanner direct unit
# ──────────────────────────────────────────────────────────────────────────

def test_validate_output_catches_signal_stack():
    ok, hits = m.validate_output("The signal stack confirms — back Arsenal.")
    assert not ok and "signal stack" in hits


def test_validate_output_catches_tier_name():
    ok, hits = m.validate_output("Diamond-grade pick — go big.")
    assert not ok and "Diamond-grade" in hits


def test_validate_output_catches_ev_token():
    ok, hits = m.validate_output("EV is strong here — back it.")
    assert not ok and "EV" in hits


def test_validate_output_does_not_match_word_every():
    """The 'EV' regex must not fire on 'every' / 'Everton'."""
    ok, hits = m.validate_output("Every signal points one way for Everton — back them.")
    # 'EV' shouldn't fire — but 'signal' isn't banned in isolation; we
    # specifically guard the 'EV' pattern here.
    assert "EV" not in hits


def test_validate_output_catches_live_commentary():
    ok, hits = m.validate_output("Wing play creating overloads in attack — back City.")
    assert not ok and "creating overloads" in hits


def test_validate_output_clean_passes():
    ok, hits = m.validate_output(
        "The price hasn't caught up and recent form backs it — "
        "hard to look past Manchester City, go big at 1.40 on HWB."
    )
    assert ok
    assert hits == []


# ──────────────────────────────────────────────────────────────────────────
# Adapter normalisation — production key aliases
# ──────────────────────────────────────────────────────────────────────────

def test_normalize_signals_handles_production_aliases():
    """Production signal_collectors keys map onto the 6 brief keys."""
    raw = {
        "movement": True,           # → line_mvt
        "market_agreement": True,   # → market
        "lineup_injury": True,      # → injury
        "form_h2h": True,           # → form
        "tipster": True,
        "price_edge": True,
    }
    norm = m.normalize_signals(raw)
    assert norm == {
        "price_edge": True, "line_mvt": True, "market": True,
        "tipster": True, "form": True, "injury": True,
    }


def test_normalize_signals_handles_title_case():
    """Spec §14 Step 2 — Title Case aliases are accepted."""
    raw = {
        "Price Edge": True, "Line Mvt": True, "Market": True,
        "Tipster": True, "Form": True, "Injury": True,
    }
    norm = m.normalize_signals(raw)
    assert all(norm.values())


def test_normalize_signals_dict_values_are_truthy():
    """signal_collectors returns dicts with available/signal_strength —
    treat non-empty dicts as truthy (callers should pre-flatten when
    they want strength-aware semantics)."""
    raw = {
        "price_edge": {"signal_strength": 0.8, "available": True},
        "movement": {},  # empty dict → falsy
    }
    norm = m.normalize_signals(raw)
    assert norm["price_edge"] is True
    assert norm["line_mvt"] is False


# ──────────────────────────────────────────────────────────────────────────
# Priority order
# ──────────────────────────────────────────────────────────────────────────

def test_pick_primary_respects_priority_order():
    """price_edge > line_mvt > injury > form > market > tipster."""
    # All active → price_edge wins
    assert m.pick_primary({k: True for k in m.PRIMARY_PRIORITY}) == "price_edge"
    # No price_edge → line_mvt wins
    sigs = {k: True for k in m.PRIMARY_PRIORITY}
    sigs["price_edge"] = False
    assert m.pick_primary(sigs) == "line_mvt"
    # Down to tipster
    only_tip = {k: False for k in m.PRIMARY_PRIORITY}
    only_tip["tipster"] = True
    assert m.pick_primary(only_tip) == "tipster"


def test_pick_secondary_excludes_primary():
    """Secondary picker never returns the primary key."""
    sigs = {"price_edge": True, "form": True, "injury": True}
    assert m.pick_secondary(sigs, "price_edge") == "injury"  # injury > form
    assert m.pick_secondary(sigs, "injury") == "form"


def test_pick_secondary_returns_none_when_only_primary_active():
    sigs = {"price_edge": True, "form": False, "injury": False,
            "line_mvt": False, "market": False, "tipster": False}
    assert m.pick_secondary(sigs, "price_edge") is None


# ──────────────────────────────────────────────────────────────────────────
# FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-01 (2026-05-04) — regression guards
# for the 3 blockers Codex adversarial-review flagged on commit 4a115b9.
# ──────────────────────────────────────────────────────────────────────────


def test_p1_imperative_close_accepts_signal_mapper_diamond():
    """P1 — narrative_validator imperative-close gate must accept Diamond
    'go big' / 'hard to look past' closures (was rejecting on _CORPUS_IMPERATIVE_CLOSE_RE).
    """
    from narrative_validator import _CORPUS_IMPERATIVE_CLOSE_RE
    diamond_close = "hard to look past Manchester City, go big at 1.40 on HWB."
    assert _CORPUS_IMPERATIVE_CLOSE_RE.search(diamond_close), (
        "Diamond signal-mapper closure must clear the imperative regex; "
        f"sample={diamond_close!r}"
    )


def test_p1_imperative_close_accepts_signal_mapper_silver():
    """P1 — Silver 'lean ... standard stake' closure must clear regex."""
    from narrative_validator import _CORPUS_IMPERATIVE_CLOSE_RE
    silver_close = "lean Chelsea win, standard stake."
    assert _CORPUS_IMPERATIVE_CLOSE_RE.search(silver_close), (
        f"Silver signal-mapper closure must clear regex; sample={silver_close!r}"
    )


def test_p1_imperative_close_accepts_signal_mapper_bronze():
    """P1 — Bronze 'worth a small play ... light stake' closure clears regex
    via 'worth a' alternation (already passed pre-fix; positive control).
    """
    from narrative_validator import _CORPUS_IMPERATIVE_CLOSE_RE
    bronze_close = "worth a small play on Manchester City win, light stake."
    assert _CORPUS_IMPERATIVE_CLOSE_RE.search(bronze_close), (
        f"Bronze closure must clear regex; sample={bronze_close!r}"
    )


def test_p1_imperative_close_accepts_gold():
    """P1 — Gold 'back ... standard stake' clears via existing 'back' alternation."""
    from narrative_validator import _CORPUS_IMPERATIVE_CLOSE_RE
    gold_close = "back Brighton & Hove Albion win, standard stake."
    assert _CORPUS_IMPERATIVE_CLOSE_RE.search(gold_close), (
        f"Gold closure must clear regex; sample={gold_close!r}"
    )


def test_p1_render_verdict_falls_back_when_quality_probe_fails(monkeypatch):
    """P1 — when min_verdict_quality probe rejects the mapper output (e.g. <100
    chars), render_verdict must fall back to the corpus path so the downstream
    persistence gate doesn't silently quarantine or refuse the write.
    """
    monkeypatch.delenv("USE_SIGNAL_MAPPED_VERDICTS", raising=False)
    import verdict_corpus
    importlib.reload(verdict_corpus)

    # Force the quality probe to always fail.
    monkeypatch.setattr(
        "narrative_spec.min_verdict_quality",
        lambda *_a, **_kw: False,
        raising=True,
    )

    spec = _FakeSpec(
        edge_tier="silver",
        outcome="home",
        outcome_label="Aston Villa win",
        odds=2.10,
        bookmaker="Betway",
        ev_pct=4.2,
        movement_direction="neutral",
        bookmaker_count=4,
        tipster_available=False,
        tipster_agrees=None,
        home_form="WDLDW",
        away_form="LDLDW",
    )
    out = verdict_corpus.render_verdict(cast("verdict_corpus.NarrativeSpec", spec))
    # Mapper output starts with "The price hasn't caught up..." — corpus does NOT.
    assert not out.startswith("The price hasn't caught up"), (
        f"render_verdict should fall back to corpus when quality probe fails; "
        f"got mapper output: {out!r}"
    )


def test_p2_picked_side_home_injury_does_not_activate_injury_signal():
    """P2 — when outcome=home AND home has injuries, the injury signal must
    NOT activate. Picked-side injuries are contradicting evidence (handled by
    has_real_risk + concern-prefix path), not supporting evidence.
    """
    import verdict_corpus
    importlib.reload(verdict_corpus)
    spec = _FakeSpec(
        outcome="home",
        outcome_label="Manchester City",
        injuries_home=["De Bruyne", "Foden"],  # picked side has injuries
        injuries_away=[],
    )
    sig = verdict_corpus._spec_to_signals(cast("verdict_corpus.NarrativeSpec", spec))
    assert sig["injury"] is False, (
        "Picked-side (home) injuries must NOT activate the injury signal — "
        f"that's contradicting evidence, not support. Got: {sig}"
    )


def test_p2_picked_side_away_injury_does_not_activate_injury_signal():
    """P2 — same inversion check for the away pick path."""
    import verdict_corpus
    importlib.reload(verdict_corpus)
    spec = _FakeSpec(
        outcome="away",
        outcome_label="Brentford",
        injuries_home=[],
        injuries_away=["Mbeumo"],  # picked side has injuries
    )
    sig = verdict_corpus._spec_to_signals(cast("verdict_corpus.NarrativeSpec", spec))
    assert sig["injury"] is False


def test_p2_opposing_side_injury_activates_injury_signal_home_pick():
    """P2 — when outcome=home AND AWAY has injuries, injury IS active
    (opponent weakness supports our pick — spec §6.6 framing).
    """
    import verdict_corpus
    importlib.reload(verdict_corpus)
    spec = _FakeSpec(
        outcome="home",
        outcome_label="Manchester City",
        injuries_home=[],
        injuries_away=["Mbeumo"],  # OPPONENT injured
    )
    sig = verdict_corpus._spec_to_signals(cast("verdict_corpus.NarrativeSpec", spec))
    assert sig["injury"] is True, (
        "Opponent injuries must activate the injury signal — that's the "
        "support direction the mapper's positive phrasing assumes."
    )


def test_p2_opposing_side_injury_activates_injury_signal_away_pick():
    """P2 — symmetric: outcome=away AND HOME injured → injury active."""
    import verdict_corpus
    importlib.reload(verdict_corpus)
    spec = _FakeSpec(
        outcome="away",
        outcome_label="Brentford",
        injuries_home=["Foden"],  # OPPONENT injured
        injuries_away=[],
    )
    sig = verdict_corpus._spec_to_signals(cast("verdict_corpus.NarrativeSpec", spec))
    assert sig["injury"] is True


def test_p2_empty_outcome_suppresses_injury_signal():
    """P2 — when outcome is empty (no clear pick side), injury must NOT fire.
    The mapper phrasing is "the OTHER team weakened" framing only — without
    a pick side we can't decide which team's injuries are support vs risk.
    """
    import verdict_corpus
    importlib.reload(verdict_corpus)
    spec = _FakeSpec(
        outcome="",
        outcome_label="",
        injuries_home=["A"],
        injuries_away=["B"],
    )
    sig = verdict_corpus._spec_to_signals(cast("verdict_corpus.NarrativeSpec", spec))
    assert sig["injury"] is False, (
        "Empty outcome must suppress the injury signal."
    )


def test_p2_tipster_available_without_agreement_does_not_activate():
    """P2 — tipster_available alone is insufficient. Without an explicit
    tipster_agrees=True, the mapper would emit 'outside support points this
    way' even when tipsters are AGAINST the pick. The fix gates on agreement.
    """
    import verdict_corpus
    importlib.reload(verdict_corpus)
    # Case 1: tipster_agrees=False (against the pick)
    spec_against = _FakeSpec(tipster_available=True, tipster_agrees=False)
    sig_against = verdict_corpus._spec_to_signals(
        cast("verdict_corpus.NarrativeSpec", spec_against)
    )
    assert sig_against["tipster"] is False, (
        f"tipster_agrees=False must suppress the signal; got {sig_against}"
    )
    # Case 2: tipster_agrees=None (no data)
    spec_none = _FakeSpec(tipster_available=True, tipster_agrees=None)
    sig_none = verdict_corpus._spec_to_signals(
        cast("verdict_corpus.NarrativeSpec", spec_none)
    )
    assert sig_none["tipster"] is False, (
        f"tipster_agrees=None must suppress the signal; got {sig_none}"
    )


def test_p2_tipster_active_only_when_agreement_explicit_true():
    """P2 — only explicit tipster_agrees=True activates the signal."""
    import verdict_corpus
    importlib.reload(verdict_corpus)
    spec = _FakeSpec(tipster_available=True, tipster_agrees=True)
    sig = verdict_corpus._spec_to_signals(cast("verdict_corpus.NarrativeSpec", spec))
    assert sig["tipster"] is True


def test_p2_render_verdict_no_outside_support_when_tipsters_disagree(monkeypatch):
    """P2 integration — render_verdict must NOT emit 'outside support points
    this way' when tipsters disagree with the pick, even if the spec carries
    tipster_available=True.
    """
    monkeypatch.delenv("USE_SIGNAL_MAPPED_VERDICTS", raising=False)
    import verdict_corpus
    importlib.reload(verdict_corpus)

    spec = _FakeSpec(
        edge_tier="bronze",
        outcome_label="Brentford",
        tipster_available=True,
        tipster_agrees=False,  # against the pick
        movement_direction="neutral",  # avoid Price+LineMvt special case
        # zero out other signals so tipster would be the only candidate
        # primary if it were active
        bookmaker_count=2,
        home_form="",
        away_form="",
        injuries_home=[],
        injuries_away=[],
        ev_pct=2.0,
    )
    out = verdict_corpus.render_verdict(cast("verdict_corpus.NarrativeSpec", spec))
    assert "outside support" not in out.lower(), (
        f"Verdict must not claim 'outside support' when tipsters disagree; "
        f"got: {out!r}"
    )


def test_p2_render_verdict_no_team_news_when_picked_side_injured(monkeypatch):
    """P2 integration — render_verdict must NOT emit 'team news gives it extra
    weight' when the PICKED side is the injured one. Picked-side injuries are
    risk, not support.
    """
    monkeypatch.delenv("USE_SIGNAL_MAPPED_VERDICTS", raising=False)
    import verdict_corpus
    importlib.reload(verdict_corpus)

    spec = _FakeSpec(
        edge_tier="silver",
        outcome="home",
        outcome_label="Manchester City",
        injuries_home=["De Bruyne"],  # picked side injured
        injuries_away=[],
        movement_direction="neutral",
        tipster_available=False,
        tipster_agrees=None,
        bookmaker_count=2,
        home_form="WWWDW",
        away_form="LDLDD",
        ev_pct=3.5,
    )
    out = verdict_corpus.render_verdict(cast("verdict_corpus.NarrativeSpec", spec))
    assert "team news" not in out.lower(), (
        f"Verdict must not claim 'team news gives it extra weight' for the "
        f"picked side that's the one injured; got: {out!r}"
    )
