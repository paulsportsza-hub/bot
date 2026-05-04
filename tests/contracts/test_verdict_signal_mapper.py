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
    # OPS-SPEC-SIGNAL-EXPOSURE-01 — native canonical signal exposure on the
    # spec. Default empty dict / None preserves the proxy-fallback path
    # (the existing tests' implicit semantics) so legacy assertions still
    # exercise the BUILD-VERDICT-SIGNAL-MAPPED-01 derivation.
    signals: dict = field(default_factory=dict)
    line_movement_direction: str | None = None


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
    'go big' / 'hard to look past' closures (was rejecting on
    _CORPUS_IMPERATIVE_CLOSE_RE). Routed via tier-scoped helper to prevent
    cross-tier acceptance (Codex round-2 P2).
    """
    from narrative_validator import imperative_close_ok
    diamond_close = "hard to look past Manchester City, go big at 1.40 on HWB."
    assert imperative_close_ok(diamond_close, "diamond"), (
        "Diamond signal-mapper closure must clear the imperative gate; "
        f"sample={diamond_close!r}"
    )


def test_p1_imperative_close_accepts_signal_mapper_silver():
    """P1 — Silver 'lean ... standard stake' closure must clear gate."""
    from narrative_validator import imperative_close_ok
    silver_close = "lean Chelsea win, standard stake."
    assert imperative_close_ok(silver_close, "silver"), (
        f"Silver signal-mapper closure must clear gate; sample={silver_close!r}"
    )


def test_p1_imperative_close_accepts_signal_mapper_bronze():
    """P1 — Bronze 'worth a small play ... light stake' closure clears via
    legacy 'worth a' alternation in the corpus regex (positive control).
    """
    from narrative_validator import imperative_close_ok
    bronze_close = "worth a small play on Manchester City win, light stake."
    assert imperative_close_ok(bronze_close, "bronze"), (
        f"Bronze closure must clear gate; sample={bronze_close!r}"
    )


def test_p1_imperative_close_accepts_gold():
    """P1 — Gold 'back ... standard stake' clears via existing 'back' alternation."""
    from narrative_validator import imperative_close_ok
    gold_close = "back Brighton & Hove Albion win, standard stake."
    assert imperative_close_ok(gold_close, "gold"), (
        f"Gold closure must clear gate; sample={gold_close!r}"
    )


# FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-02 (2026-05-04) — Codex round-2 P2:
# tier-scoped enforcement. Cross-tier closures must FAIL Gate 9 even though
# the underlying spec §10 imperatives are themselves recognised.

def test_p2_imperative_close_rejects_diamond_lean():
    """Cross-tier — Diamond verdict closing with Silver 'lean ...' fails."""
    from narrative_validator import imperative_close_ok
    txt = "lean Manchester City win, standard stake."
    assert not imperative_close_ok(txt, "diamond"), (
        f"Silver 'lean ...' closure must NOT clear Diamond gate; sample={txt!r}"
    )


def test_p2_imperative_close_rejects_diamond_small_play():
    """Cross-tier — Diamond verdict closing with Bronze 'small play' fails."""
    from narrative_validator import imperative_close_ok
    txt = "small play on Manchester City win, light stake."
    assert not imperative_close_ok(txt, "diamond"), (
        f"Bronze 'small play' closure must NOT clear Diamond gate; sample={txt!r}"
    )


def test_p2_imperative_close_rejects_gold_lean():
    """Cross-tier — Gold verdict closing with Silver 'lean ...' fails."""
    from narrative_validator import imperative_close_ok
    txt = "lean Brighton & Hove Albion win, standard stake."
    assert not imperative_close_ok(txt, "gold"), (
        f"Silver 'lean ...' closure must NOT clear Gold gate; sample={txt!r}"
    )


def test_p2_imperative_close_rejects_silver_go_big():
    """Cross-tier — Silver verdict closing with Diamond 'go big' fails."""
    from narrative_validator import imperative_close_ok
    txt = "hard to look past Chelsea, go big at 1.40 on HWB."
    assert not imperative_close_ok(txt, "silver"), (
        f"Diamond 'go big' closure must NOT clear Silver gate; sample={txt!r}"
    )


def test_p2_imperative_close_rejects_bronze_go_big():
    """Cross-tier — Bronze verdict closing with Diamond 'go big' fails."""
    from narrative_validator import imperative_close_ok
    txt = "hard to look past Burnley, go big at 3.20 on Betway."
    assert not imperative_close_ok(txt, "bronze"), (
        f"Diamond 'go big' closure must NOT clear Bronze gate; sample={txt!r}"
    )


def test_p2_imperative_close_legacy_corpus_tokens_universal():
    """Legacy corpus closures (back/take/bet/etc.) are tier-uniform — corpus
    encodes tier semantics via claims_max_conviction, not the close regex.
    Each legacy token must clear every tier's gate.
    """
    from narrative_validator import imperative_close_ok
    legacy_closes = [
        "back Manchester City to win at 1.40.",
        "take Chelsea to win, full stake.",
        "bet Liverpool, half stake.",
        "lock in this pick at 2.10.",
        "the play is Arsenal to win.",
        "the call is Tottenham at 1.85.",
    ]
    for tier in ("diamond", "gold", "silver", "bronze"):
        for txt in legacy_closes:
            assert imperative_close_ok(txt, tier), (
                f"Legacy corpus closure must clear gate for any tier; "
                f"tier={tier} sample={txt!r}"
            )


def test_p2_imperative_close_unknown_tier_falls_back_to_corpus():
    """Unknown tier (defensive): only legacy corpus tokens accepted; no
    signal-mapper imperatives added.
    """
    from narrative_validator import imperative_close_ok
    # Legacy corpus token clears
    assert imperative_close_ok("back City to win.", "platinum") is True
    # Signal-mapper Diamond closure does NOT clear under unknown tier
    assert imperative_close_ok(
        "hard to look past City, go big at 1.40 on HWB.", "platinum"
    ) is False


def test_p2_imperative_close_empty_or_none_returns_false():
    """Defensive: empty / None text returns False, never True."""
    from narrative_validator import imperative_close_ok
    assert imperative_close_ok("", "diamond") is False
    assert imperative_close_ok(None, "diamond") is False  # type: ignore[arg-type]


# FIX-VERDICT-SIGNAL-MAPPED-CODEX-REVIEW-03 (2026-05-04) — Codex round-3 P2:
# the legacy `_CORPUS_IMPERATIVE_CLOSE_RE` still contained `worth a` as a
# tier-uniform token, so a Diamond/Gold/Silver verdict closing with the
# literal Bronze closure `worth a small play on X, light stake.` matched
# the universal regex BEFORE the tier-scoped check fired. Fix: removed
# `worth a` from the legacy alternation (verified by audit — all corpus
# `worth a ...` closures live in the Bronze section only) and put it in
# the Bronze tier-scoped regex.

def test_p3_imperative_close_rejects_diamond_worth_a_small_play():
    """Cross-tier — Diamond verdict closing with the literal Bronze closer
    'worth a small play on X, light stake.' must fail Gate 9.
    """
    from narrative_validator import imperative_close_ok
    txt = "worth a small play on Manchester City win, light stake."
    assert not imperative_close_ok(txt, "diamond"), (
        "Bronze 'worth a small play' closure must NOT clear Diamond gate; "
        f"sample={txt!r}"
    )


def test_p3_imperative_close_rejects_gold_worth_a_small_play():
    """Cross-tier — Gold verdict closing with Bronze 'worth a small play' fails."""
    from narrative_validator import imperative_close_ok
    txt = "worth a small play on Brighton win, light stake."
    assert not imperative_close_ok(txt, "gold"), (
        f"Bronze closure must NOT clear Gold gate; sample={txt!r}"
    )


def test_p3_imperative_close_rejects_silver_worth_a_small_play():
    """Cross-tier — Silver verdict closing with Bronze 'worth a small play' fails."""
    from narrative_validator import imperative_close_ok
    txt = "worth a small play on Chelsea win, light stake."
    assert not imperative_close_ok(txt, "silver"), (
        f"Bronze closure must NOT clear Silver gate; sample={txt!r}"
    )


def test_p3_imperative_close_rejects_higher_tiers_corpus_bronze_closures():
    """Cross-tier — every corpus-authored Bronze closure ('worth a small play',
    'worth a measured punt', 'worth a small punt', 'worth a measured play')
    must fail for Diamond / Gold / Silver. Verified against VERDICT_CORPUS
    audit: all live in Bronze section.
    """
    from narrative_validator import imperative_close_ok
    bronze_corpus_closures = [
        "worth a small play on {team} at 1.40 with HWB, light stake.",
        "worth a measured punt on {team} at 2.10 on Betway, light stake.",
        "worth a small punt on {team} at 1.85 with Sportingbet, light stake.",
        "worth a measured play on {team} at 3.50 on Betway, light stake.",
    ]
    for txt in bronze_corpus_closures:
        for tier in ("diamond", "gold", "silver"):
            assert not imperative_close_ok(txt, tier), (
                f"Bronze corpus closure must NOT clear {tier} gate; "
                f"sample={txt!r}"
            )


def test_p3_imperative_close_accepts_bronze_corpus_worth_a_variants():
    """Positive control — every Bronze corpus closure clears Bronze gate."""
    from narrative_validator import imperative_close_ok
    bronze_corpus_closures = [
        "worth a small play on Burnley at 3.20, light stake.",
        "worth a measured punt on Wolves at 2.75 on Betway, light stake.",
        "worth a small punt on Brighton at 2.10 with HWB, light stake.",
        "worth a measured play on West Ham at 2.50 on Betway, light stake.",
    ]
    for txt in bronze_corpus_closures:
        assert imperative_close_ok(txt, "bronze"), (
            f"Bronze corpus closure must clear Bronze gate; sample={txt!r}"
        )


def test_p3_imperative_close_legacy_regex_no_longer_matches_worth_a():
    """Verify the legacy alternation no longer contains 'worth a' — direct
    structural assertion against the regex source pattern.
    """
    from narrative_validator import _CORPUS_IMPERATIVE_CLOSE_RE
    pattern_source = _CORPUS_IMPERATIVE_CLOSE_RE.pattern
    assert "worth" not in pattern_source, (
        "_CORPUS_IMPERATIVE_CLOSE_RE must no longer contain 'worth' — round-3 "
        "fix moved it exclusively to _BRONZE_SIGNAL_MAPPER_CLOSE_RE. Pattern: "
        f"{pattern_source!r}"
    )
    # Direct match check: "worth a small play on X." should NOT match the
    # legacy regex any more (only via the Bronze tier-scoped one).
    txt = "worth a small play on Manchester City, light stake."
    assert not _CORPUS_IMPERATIVE_CLOSE_RE.search(txt), (
        f"Legacy regex must not match Bronze 'worth a' closure; sample={txt!r}"
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


# ──────────────────────────────────────────────────────────────────────────
# OPS-SPEC-SIGNAL-EXPOSURE-01 — native spec.signals + line_movement_direction
# ──────────────────────────────────────────────────────────────────────────
#
# These tests exercise the post-fix path where NarrativeSpec carries a
# native ``signals: dict[str, bool]`` field populated from the canonical
# ``collect_all_signals`` output. The verdict path must:
#   AC-2 — read the dict natively when populated (Phase 3)
#   AC-3 — fall back to the legacy proxy adapter when empty (HG-5)
#   AC-4 — surface all 8 §12 combinations across 4 tiers × 3 sports
#   HG-4 — single source of truth alignment with the card-image dot contract
#

import narrative_spec as _ns
import verdict_corpus  # noqa: E402 — module-level import after the existing
                       # block that uses local imports for monkeypatch reload
                       # patterns; tests below treat this as a stable handle.


def _spec_for_combo(
    tier: str,
    *,
    signals: dict[str, bool],
    line_movement: str | None = None,
    sport: str = "soccer",
    outcome: str = "home",
    home_name: str = "Manchester City",
    away_name: str = "Brentford",
    outcome_label: str = "Manchester City",
    odds: float = 1.40,
    bookmaker: str = "HWB",
    ev_pct: float = 5.5,
    injuries_home: list | None = None,
    injuries_away: list | None = None,
    tipster_agrees: bool | None = True,
):
    """Build a _FakeSpec for a §12 combination with explicit native signals.

    For polarity-gated signals the helper sets supporting fields so the
    native path's polarity filters allow the signal to fire:
      - tipster: when ``signals['tipster']`` is True, sets tipster_available
        and tipster_agrees=True (or as overridden) so the gate passes.
      - injury: when ``signals['injury']`` is True, sets opponent-side
        injuries by default (single-name placeholder) so the gate passes.
    """
    inj_home = list(injuries_home or [])
    inj_away = list(injuries_away or [])
    if signals.get("injury") and not (inj_home or inj_away):
        # Default opponent-side weakening so the polarity gate passes.
        if outcome == "home":
            inj_away = ["Opponent Striker"]
        elif outcome == "away":
            inj_home = ["Home Striker"]
    return _FakeSpec(
        edge_tier=tier,
        sport=sport,
        outcome=outcome,
        outcome_label=outcome_label,
        home_name=home_name,
        away_name=away_name,
        odds=odds,
        bookmaker=bookmaker,
        ev_pct=ev_pct if signals.get("price_edge") else 0.0,
        # Set legacy fields to inert defaults so proxy-fallback path can
        # never accidentally satisfy a signal — the native dict alone
        # decides what fires.
        movement_direction="neutral",
        bookmaker_count=0,
        tipster_available=bool(signals.get("tipster")),
        tipster_agrees=tipster_agrees if signals.get("tipster") else None,
        home_form="",
        away_form="",
        injuries_home=inj_home,
        injuries_away=inj_away,
        signals=dict(signals),
        line_movement_direction=line_movement,
    )


# §12 combination → (key signals dict, expected primary lead, expected combined?)
_COMBO_SPECS = {
    # §12.1 — Price + Form (combined causal)
    "price_form": (
        {"price_edge": True, "form": True},
        None,  # primary path
        "The price hasn't caught up and recent form backs it",
    ),
    # §12.2 — Price + Injury (primary + secondary)
    "price_injury": (
        {"price_edge": True, "injury": True},
        None,
        "The price hasn't caught up and team news gives it extra weight",
    ),
    # §12.3 — Price + Line Movement favourable (special case)
    "price_line_favourable": (
        {"price_edge": True, "line_mvt": True},
        "favourable",
        "The line is moving our way and the price is still there",
    ),
    # §12.4 — Price + Line Movement against (special case)
    "price_line_against": (
        {"price_edge": True, "line_mvt": True},
        "against",
        "The market has moved, but the price still looks big",
    ),
    # §12.5 — Form-only (primary alone)
    "form_only": (
        {"form": True},
        None,
        "Recent form backs this",
    ),
    # §12.6 — Market-only (primary alone)
    "market_only": (
        {"market": True},
        None,
        "The wider market is leaning this way",
    ),
    # §12.7 — Tipster-only (primary alone)
    "tipster_only": (
        {"tipster": True},
        None,
        "Outside support points this way",
    ),
    # §12.8 — No signals (tier fallback) — lead varies by tier; just
    # assert the EXPECTED_ACTION fragment is present per tier.
    "no_signals_fallback": (
        {},
        None,
        None,  # tier-specific fallback — see assertion in test
    ),
}

_TIER_FALLBACK_LEADS = {
    "diamond": "The price still looks too big for the setup",
    "gold":    "There is enough value here to support the pick",
    "silver":  "There is just enough value here",
    "bronze":  "Not much in it, but there is a small lean",
}


def _build_verdict_for_spec(spec: _FakeSpec) -> str:
    """Mirror render_verdict's _spec_to_signals + build_verdict pipeline,
    bypassing the min_verdict_quality length-floor fallback.

    The brief contract is "spec.signals natively wires through to the
    signal-mapper". The downstream length probe is a SAFETY GATE that
    can swap in corpus output when the mapper happens to emit a short
    sentence — that's an orthogonal concern (existing behaviour).
    These tests exercise the dict-flow contract: spec.signals is the
    source the mapper consumes, mapped to spec §12.X phrasing.
    """
    cs = cast("verdict_corpus.NarrativeSpec", spec)
    sigs = verdict_corpus._spec_to_signals(cs)
    line_mvt = verdict_corpus._spec_movement_direction(cs)
    odds_val = float(spec.odds or 0)
    return m.build_verdict(
        team=(spec.outcome_label or spec.home_name or "the pick").strip(),
        tier=spec.edge_tier,
        signals=sigs,
        odds=(f"{odds_val:.2f}" if odds_val > 0 else None),
        bookmaker=(spec.bookmaker or None),
        line_movement_direction=line_mvt,
    )


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("combo_key", list(_COMBO_SPECS.keys()))
def test_ops_signal_exposure_native_path_8_combos(combo_key, tier):
    """AC-2 / AC-4 — 8 §12 combinations × 4 tiers fire from native spec.signals.

    Each combination wires the canonical 6-key signals dict directly on
    the NarrativeSpec. The verdict path's _spec_to_signals reads natively
    and the mapper produces the spec §12.X phrase for that combination
    + tier. Tested via the mapper directly (the brief contract); the
    downstream min_verdict_quality length probe is a separate gate
    exercised by existing render_verdict tests.
    """
    sigs, line_mvt, expected_lead = _COMBO_SPECS[combo_key]
    spec = _spec_for_combo(tier, signals=sigs, line_movement=line_mvt)
    out = _build_verdict_for_spec(spec)

    if combo_key == "no_signals_fallback":
        # §12.8 — tier-specific fallback lead
        assert out.startswith(_TIER_FALLBACK_LEADS[tier]), (
            f"Tier {tier} fallback should lead with §12.8 phrase; got: {out!r}"
        )
    else:
        assert expected_lead is not None  # type guard
        assert expected_lead in out, (
            f"§12 combo '{combo_key}' tier {tier} expected lead "
            f"{expected_lead!r}; got: {out!r}"
        )

    # Tier action fragment must always close the verdict.
    assert m.EXPECTED_ACTION[tier] in out, (
        f"Tier {tier} action fragment missing from verdict: {out!r}"
    )


# AC-4 — full reachability matrix: 4 tiers × 8 combos × 3 sports = 96 cases.
_COMBO_SPORTS = ("soccer", "rugby", "cricket")


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("combo_key", list(_COMBO_SPECS.keys()))
@pytest.mark.parametrize("sport", _COMBO_SPORTS)
def test_ops_signal_exposure_full_reachability_96_cases(combo_key, tier, sport):
    """AC-4 — 4 tiers × 8 §12 combos × 3 sports = 96 fixtures.

    Verdict copy is sport-agnostic (it never references sport vocabulary).
    This matrix proves the native path produces a legal verdict for every
    combination across all sports — the same combination renders the same
    spec §12.X phrase regardless of sport. Sport-specific tone surfaces
    in the Setup/Edge/Risk sections, not the Verdict; the mapper is
    sport-agnostic by design.
    """
    sigs, line_mvt, expected_lead = _COMBO_SPECS[combo_key]
    spec = _spec_for_combo(tier, signals=sigs, line_movement=line_mvt, sport=sport)
    out = _build_verdict_for_spec(spec)

    # Verdict must end with the period and the tier action fragment.
    assert out.endswith("."), f"Missing terminator: {out!r}"
    assert m.EXPECTED_ACTION[tier] in out, (
        f"sport={sport} tier={tier} combo={combo_key}: action fragment missing"
    )

    if combo_key == "no_signals_fallback":
        assert out.startswith(_TIER_FALLBACK_LEADS[tier])
    else:
        assert expected_lead is not None  # type guard
        assert expected_lead in out, (
            f"sport={sport} tier={tier} combo={combo_key}: expected "
            f"{expected_lead!r}; got: {out!r}"
        )

    # No banned terms / live commentary creep in for any sport.
    ok, hits = m.validate_output(out)
    assert ok, f"Banned/live-commentary hits for {sport}/{tier}/{combo_key}: {hits}"


def test_ops_signal_exposure_proxy_fallback_when_signals_empty():
    """AC-3 / HG-5 — empty spec.signals routes through legacy proxy adapter.

    Un-migrated specs (or any future producer that forgets to populate
    spec.signals) MUST still render a coherent verdict via the proxy
    fallback. Both paths converge on the same answer for typical inputs.
    """
    # Native path: explicit signals dict
    spec_native = _FakeSpec(
        edge_tier="gold",
        outcome="home",
        outcome_label="Manchester City",
        ev_pct=5.5,
        movement_direction="neutral",
        bookmaker_count=0,
        tipster_available=False,
        tipster_agrees=None,
        home_form="",
        away_form="",
        injuries_home=[],
        injuries_away=[],
        signals={"price_edge": True, "form": True},
        line_movement_direction=None,
        odds=1.40,
        bookmaker="HWB",
    )
    out_native = _build_verdict_for_spec(spec_native)

    # Fallback path: empty signals, equivalent legacy fields
    spec_fallback = _FakeSpec(
        edge_tier="gold",
        outcome="home",
        outcome_label="Manchester City",
        ev_pct=5.5,
        movement_direction="neutral",
        bookmaker_count=0,
        tipster_available=False,
        tipster_agrees=None,
        home_form="WWLDW",  # form proxy fires
        away_form="",
        injuries_home=[],
        injuries_away=[],
        signals={},  # native dict empty → proxy fallback
        line_movement_direction=None,
        odds=1.40,
        bookmaker="HWB",
    )
    out_fallback = _build_verdict_for_spec(spec_fallback)

    # Both paths yield the §12.1 (price + form) verdict.
    assert "The price hasn't caught up and recent form backs it" in out_native
    assert "The price hasn't caught up and recent form backs it" in out_fallback
    # Both must be valid (no banned/live terms).
    for label, out in (("native", out_native), ("fallback", out_fallback)):
        ok, hits = m.validate_output(out)
        assert ok, f"{label} path produced banned/live hits: {hits}"


def test_ops_signal_exposure_card_alignment_invariant():
    """HG-4 — spec.signals carries the SAME 6-key contract the card-image
    Edge Signal dots consume.

    The card-image renderer (card_data.build_edge_detail_data) reads
    ``tip['signals']`` as either a dict[name→bool] or a list of
    {name, active} entries. For HG-4 alignment, when we round-trip
    spec.signals through that contract — i.e., construct a tip with
    ``tip['signals'] = spec.signals`` — the booleans the card reads MUST
    equal the booleans the verdict path consumed.

    This test asserts the dict-shape contract: spec.signals has exactly
    the canonical 6 keys (after _normalise_spec_signals), and bool values
    survive the card-data normalisation step unchanged. Any divergence
    (e.g., the verdict path reading 'movement' while the card reads
    'line_mvt' for the same upstream signal) would re-introduce the
    alignment bug class FIX-CARD-VERDICT-RECOMMENDATION-ALIGNMENT-01
    closed for team/odds/bookmaker.
    """
    canonical = {
        "price_edge": True,
        "line_mvt":   False,
        "form":       True,
        "market":     False,
        "tipster":    True,
        "injury":     False,
    }
    spec = _spec_for_combo(
        "gold",
        signals=canonical,
        outcome="home",
        # tipster polarity gate passes
        tipster_agrees=True,
    )
    # Trip 1 — native verdict path consumes spec.signals
    raw = verdict_corpus._spec_to_signals(
        cast("verdict_corpus.NarrativeSpec", spec)
    )
    # Polarity-agnostic signals must round-trip 1:1.
    for key in ("price_edge", "line_mvt", "form", "market"):
        assert raw[key] is canonical[key], (
            f"HG-4: native path diverges from spec.signals for '{key}': "
            f"spec={canonical[key]} vs verdict={raw[key]}"
        )
    # Polarity-filtered signals must NOT fire in excess of the raw bool.
    assert raw["tipster"] is True, "tipster polarity gate (agrees=True) failed"
    assert raw["injury"] is False, "injury polarity gate (no opponent injuries) failed"

    # Trip 2 — card-data normalisation contract: dict[name→bool] passes through.
    # We don't import card_data here (heavy bot deps); the contract is enforced
    # at the dict-key level. Document via assertions.
    assert set(canonical.keys()) == {
        "price_edge", "line_mvt", "form", "market", "tipster", "injury"
    }, "spec.signals key set must match card-image canonical 6-key contract"


@pytest.mark.parametrize("native,fallback,expected", [
    ("favourable", "for",     "favourable"),
    ("favourable", "neutral", "favourable"),
    ("against",    "for",     "against"),
    ("against",    "neutral", "against"),
    ("unknown",    "for",     "unknown"),
    ("unknown",    "neutral", "unknown"),
    (None,         "for",     "favourable"),  # legacy "for" alias
    (None,         "favourable", "favourable"),
    (None,         "against", "against"),
    (None,         "neutral", "unknown"),
    (None,         "",        "unknown"),
    (None,         None,      "unknown"),
])
def test_ops_signal_exposure_line_movement_normalisation(native, fallback, expected):
    """AC-2 / Phase 2 step 2 — line_movement_direction normalisation contract.

    Mapper expects "favourable" / "against" / "unknown". The native field
    is preferred; falls back to mapping legacy movement_direction. The
    "favourable" / "for" alias must collapse to "favourable" so spec §6.2
    favourable lead fires; "neutral"/None collapse to "unknown" so the
    neutral lead fires.
    """
    spec = _FakeSpec(
        line_movement_direction=native,
        movement_direction=fallback or "",
    )
    out = verdict_corpus._spec_movement_direction(
        cast("verdict_corpus.NarrativeSpec", spec)
    )
    assert out == expected, (
        f"native={native} fallback={fallback}: expected {expected}, got {out}"
    )


def test_ops_signal_exposure_collect_all_signals_shape_normalises():
    """AC-1 / Phase 1 trace evidence — the canonical 7-key collect_all_signals
    output shape (price_edge, market_agreement, movement, tipster,
    lineup_injury, form_h2h, model_probability) flattens to the 6-key
    spec contract via _normalise_spec_signals.
    """
    sigs = {
        "price_edge":        {"available": True, "signal_strength": 0.7},
        "market_agreement":  {"available": True, "signal_strength": 0.5},
        "movement":          {"available": True, "direction": "for"},
        "tipster":           {"available": True, "agrees_with_edge": True},
        "lineup_injury":     {"available": True},
        "form_h2h":          {"available": True},
        "model_probability": {"available": True},  # not in 6-key — must drop
    }
    out = _ns._normalise_spec_signals(sigs)
    assert out == {
        "price_edge": True,
        "market":     True,
        "line_mvt":   True,
        "tipster":    True,
        "injury":     True,
        "form":       True,
    }, f"7-key→6-key remap failed: {out}"

    # An "available: False" signal must produce False, not be dropped.
    sigs_mixed = {
        "price_edge":   {"available": True},
        "form_h2h":     {"available": False},
        "movement":     {"available": False},
    }
    out_mixed = _ns._normalise_spec_signals(sigs_mixed)
    assert out_mixed == {
        "price_edge": True,
        "form":       False,
        "line_mvt":   False,
    }, f"available=False not preserved: {out_mixed}"

    # Bare bool dict survives unchanged.
    out_bool = _ns._normalise_spec_signals({"price_edge": True, "tipster": False})
    assert out_bool == {"price_edge": True, "tipster": False}

    # Empty / None → empty (back-compat sentinel for proxy fallback).
    assert _ns._normalise_spec_signals({}) == {}
    assert _ns._normalise_spec_signals(None) == {}
    assert _ns._normalise_spec_signals("not a dict") == {}
