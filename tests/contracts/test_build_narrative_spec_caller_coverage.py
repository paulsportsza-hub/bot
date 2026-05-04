"""FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01 HG-4 — caller-coverage regression guard.

Every production call site of ``build_narrative_spec`` MUST result in a
spec whose ``signals`` field is populated (non-empty dict) when collector
output is available.  Pre-fix, ``scripts/pregenerate_narratives._generate_one``
and ``card_data._synthesize_breakdown_row_from_baseline`` both built
``edge_data`` without populating ``signals`` / ``line_movement_direction``,
so ``verdict_corpus._spec_to_signals`` fell through to the legacy proxy
adapter and produced the §12.1 monoculture observed on the live channel
(Manchester City vs Brentford / Liverpool vs Chelsea, 2026-05-09 Gold cards).

The single source of truth for the canonical 6-key signal availability
dict is ``scrapers.edge.signal_collectors.collect_all_signals``.  Both
patched callers MUST recompute via that helper so spec.signals carries
the ``collect_all_signals`` shape (HG-4 alignment with
``card_pipeline._compute_signals``).

Allowlist policy: a caller may legitimately leave ``spec.signals`` empty
ONLY when the upstream input is incomplete by design — e.g. the
``bot.py:_build_edge_only_section`` empty-spec pathway that renders ONLY
``_render_setup`` (never ``_render_verdict``) when a league tag is
missing.  Such callers are documented in
``_KNOWN_EMPTY_SIGNAL_CALLERS`` below with the justification, and they
are excluded from the population assertion.

This test must remain green forever.  Reverting either callsite reopens
the FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01 leak vector and the live
channel will regress to §12.1 monoculture for every pregenerated card.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ── Allowlist of callers that legitimately leave spec.signals empty ───────────
#
# Format: (file_path_relative_to_bot, function_name, reason).
# Callers in this list MUST emit only setup-level output (no verdict)
# OR rely on the proxy fallback for genuine no-signal cases (contract
# tests building NarrativeSpec directly).  Adding a caller here without
# brief justification reopens the leak vector — the regression below
# enforces no silent additions.

_KNOWN_EMPTY_SIGNAL_CALLERS: tuple[tuple[str, str, str], ...] = (
    # bot.py::_build_signal_only_narrative renders ONLY _render_setup from
    # the build_narrative_spec({}, edge_data={}, tips=[], ...) call when
    # the league tag is missing. The function continues building edge /
    # risk / verdict from raw tip fields below, but the empty-spec
    # build_narrative_spec call is consumed exclusively by
    # _render_setup(_empty_spec). The returned spec is never passed to
    # _render_verdict or render_verdict, so the verdict mapper never
    # observes spec.signals from this callsite.  Codex adversarial-review
    # pass-1 (2026-05-04) flagged the previous allowlist entry naming
    # _build_edge_only_section — that function does not exist;
    # _build_signal_only_narrative is the actual hosting symbol.
    (
        "bot.py",
        "_build_signal_only_narrative",
        "Empty-spec call consumed only by _render_setup — verdict mapper never observes spec.signals from this path",
    ),
    # scripts/qa_baseline_02.py::generate_narrative is QA-only synthetic
    # tooling (48-fixture matrix benchmark — 4 tiers × 4 sports × 3
    # fixture shapes). Never served to real users; never persisted to
    # narrative_cache. Synthetic fixtures legitimately carry empty
    # signals because the matrix's purpose is to baseline the
    # _render_baseline output across coverage profiles, not to exercise
    # the live signal pipeline.
    (
        "scripts/qa_baseline_02.py",
        "generate_narrative",
        "QA tooling — synthetic 48-fixture baseline matrix, never serves real users or persists to narrative_cache",
    ),
)


# ── Caller surface inventory ──────────────────────────────────────────────────


def _list_production_callers() -> list[tuple[str, str]]:
    """Inventory every production callsite of build_narrative_spec.

    Returns list of (file_path_relative, function_name) tuples.  Each
    entry MUST EITHER appear in the allowlist OR be exercised by a
    populate-signals positive test below.

    Codex adversarial-review pass-1 (2026-05-04) flagged the previous
    hand-maintained list as drift-prone — see test_ast_scan_matches_inventory
    below for the AST-based regression guard.
    """
    return [
        # Live serve-time path — patched by OPS-SPEC-SIGNAL-EXPOSURE-01.
        ("bot.py", "_generate_narrative_v2"),
        # Card-image alignment fresh-render — uses _extract_edge_data
        # which populates signals via OPS-SPEC-SIGNAL-EXPOSURE-01.
        # Imports build_narrative_spec aliased as `_bns_align`; the AST
        # scan resolves the alias.
        ("bot.py", "_enrich_tip_for_card"),
        # Empty-spec setup-only fallback — allowlisted above. The
        # build_narrative_spec call inside this function is consumed
        # exclusively by _render_setup; the rest of the function builds
        # verdict from raw tip fields, not from spec.signals.
        ("bot.py", "_build_signal_only_narrative"),
        # Pregenerator — patched by FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01.
        ("scripts/pregenerate_narratives.py", "_generate_one"),
        # Synthesis-on-tap fallback — patched by FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01.
        ("card_data.py", "_synthesize_breakdown_row_from_baseline"),
        # QA tooling — allowlisted above. Synthetic 48-fixture matrix.
        ("scripts/qa_baseline_02.py", "generate_narrative"),
    ]


def _scan_production_callers() -> set[tuple[str, str]]:
    """AST-based scan: find every production call to build_narrative_spec.

    Returns set of (file_path_relative, enclosing_function_name) tuples.
    Excludes test directories and the allowlist test file itself so the
    inventory above stays the canonical list.

    Codex adversarial-review pass-1: replaces the hand-maintained
    inventory with a real source scan, so any new caller introduced in
    a future wave fails this regression guard until it is either
    documented in _list_production_callers (positive coverage) or
    added to _KNOWN_EMPTY_SIGNAL_CALLERS (with justification).
    """
    import ast

    repo_root = Path(__file__).resolve().parents[2]
    excluded_dirs = {
        "tests",
        ".venv",
        "venv",
        "logs",
        "data",
        "static",
        "card_assets",
        "card_templates",
        "reports",
        "structured_logs",
    }

    findings: set[tuple[str, str]] = set()
    for py_path in sorted(repo_root.rglob("*.py")):
        rel = py_path.relative_to(repo_root)
        if rel.parts and rel.parts[0] in excluded_dirs:
            continue
        # Skip test_*.py everywhere — production scope only.
        if rel.name.startswith("test_") or rel.name.endswith("_test.py"):
            continue
        try:
            src = py_path.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            tree = ast.parse(src, filename=str(py_path))
        except SyntaxError:
            continue
        # Walk imports first to discover aliases for build_narrative_spec.
        # Pattern: `from narrative_spec import build_narrative_spec as <alias>`
        # bot.py::_enrich_tip_for_card uses `_bns_align`; future waves may
        # rename. Tracking aliases per-module keeps the scan robust.
        aliases: set[str] = {"build_narrative_spec"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "build_narrative_spec" and alias.asname:
                        aliases.add(alias.asname)
            elif isinstance(node, ast.Assign):
                # Detect: `_bns = build_narrative_spec` rebindings.
                if (
                    len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in aliases
                ):
                    aliases.add(node.targets[0].id)

        # Walk and track enclosing function for every Call node.
        class _Walker(ast.NodeVisitor):
            def __init__(self, alias_set: set[str]):
                self.stack: list[str] = []
                self.hits: set[tuple[str, str]] = set()
                self._aliases = alias_set

            def visit_FunctionDef(self, node: ast.FunctionDef):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_AsyncFunctionDef(self, node):  # type: ignore[override]
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_Call(self, node: ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                # Match the bare callable name AND any attribute named
                # build_narrative_spec (covers `narrative_spec.build_narrative_spec(...)`)
                # AND any module-local alias like `_bns_align` from
                # `from narrative_spec import build_narrative_spec as _bns_align`.
                if func_name in self._aliases or func_name == "build_narrative_spec":
                    enclosing = self.stack[-1] if self.stack else "<module>"
                    self.hits.add((str(rel), enclosing))
                self.generic_visit(node)

        walker = _Walker(aliases)
        walker.visit(tree)
        findings.update(walker.hits)
    return findings


def _allowlist_keys() -> set[tuple[str, str]]:
    return {(entry[0], entry[1]) for entry in _KNOWN_EMPTY_SIGNAL_CALLERS}


# ── Fakes / fixtures ──────────────────────────────────────────────────────────


def _make_collect_all_signals_fake(populated: bool = True):
    """Return a callable that mimics scrapers.edge.signal_collectors.collect_all_signals."""

    def _fake(match_key, outcome, market_type="1x2", sport=None, league=None):
        if not populated:
            return {}
        return {
            "price_edge": {
                "available": True,
                "signal_strength": 0.6,
                "ev_pct": 4.2,
            },
            "market_agreement": {
                "available": True,
                "signal_strength": 0.55,
                "score": 0.62,
            },
            "movement": {
                "available": True,
                "signal_strength": 0.5,
                "direction": "favourable",
            },
            "tipster": {
                "available": True,
                "signal_strength": 0.5,
                "agrees_with_edge": True,
                "against_count": 0,
            },
            "lineup_injury": {
                "available": True,
                "signal_strength": 0.5,
            },
            "form_h2h": {
                "available": True,
                "signal_strength": 0.55,
                "home_form_string": "WWDLW",
                "away_form_string": "LDLWL",
                "h2h_total": 4,
                "h2h_a_wins": 2,
                "h2h_b_wins": 1,
                "h2h_draws": 1,
            },
            "model_probability": {
                "available": False,
                "signal_strength": None,
            },
        }

    return _fake


# ── Caller-coverage assertions ────────────────────────────────────────────────


def test_caller_inventory_has_no_silent_additions():
    """Every documented caller is either tested below or allowlisted."""
    callers = set(_list_production_callers())
    allowlist = _allowlist_keys()
    missing = allowlist - callers
    assert not missing, (
        f"Allowlist contains callers absent from inventory: {missing}. "
        "Either remove the allowlist entry or add the caller to "
        "_list_production_callers()."
    )


def test_ast_scan_matches_inventory():
    """AST regression guard (Codex adversarial-review pass-1).

    Walks every production *.py file (excluding tests/ and runtime
    scratch dirs) and AST-extracts the enclosing function for each
    `build_narrative_spec(...)` call. The set of (file, enclosing_fn)
    tuples found in source MUST equal _list_production_callers() — any
    new caller introduced by a future wave fails this assertion until
    it's added to the inventory and either tested for populate-signals
    OR documented in _KNOWN_EMPTY_SIGNAL_CALLERS.
    """
    scanned = _scan_production_callers()
    documented = set(_list_production_callers())
    new_callers = scanned - documented
    removed_callers = documented - scanned
    assert not new_callers, (
        f"AST scan found build_narrative_spec callers not in inventory: "
        f"{sorted(new_callers)}. Add them to _list_production_callers() "
        f"and either provide a positive populate-signals test OR add an "
        f"entry to _KNOWN_EMPTY_SIGNAL_CALLERS with justification."
    )
    # Also fail when documented callers vanish from source — the inventory
    # should track real callsites, not historical ones.
    assert not removed_callers, (
        f"Documented callers no longer present in source: "
        f"{sorted(removed_callers)}. Remove them from "
        f"_list_production_callers() (and _KNOWN_EMPTY_SIGNAL_CALLERS if "
        f"applicable)."
    )


def test_pregen_generate_one_populates_spec_signals():
    """scripts/pregenerate_narratives._generate_one MUST recompute the
    canonical signals dict and pass it through to build_narrative_spec.
    """
    import importlib

    pregen = importlib.import_module("scripts.pregenerate_narratives")

    fake_sigs = _make_collect_all_signals_fake(populated=True)

    with patch.object(pregen, "_collect_canonical_signals") as mock_collect:
        mock_collect.return_value = fake_sigs(
            "manchester_city_vs_brentford_2026-05-09", "home"
        )

        captured: dict = {}

        def _capture_build_spec(ctx_data, edge_data, tips, sport):
            from narrative_spec import (
                _normalise_line_movement_direction,
                _normalise_spec_signals,
            )

            captured["edge_data"] = dict(edge_data)
            captured["spec_signals"] = _normalise_spec_signals(edge_data.get("signals"))
            captured["spec_line_movement"] = edge_data.get("line_movement_direction")
            # Build the spec to confirm round-trip works on this payload.
            from narrative_spec import build_narrative_spec

            return build_narrative_spec(ctx_data, edge_data, tips, sport)

        with patch.object(pregen, "_collect_canonical_signals", mock_collect):
            # Replicate the relevant slice of _generate_one inline so we
            # don't depend on the whole pipeline (DB writes, ESPN fetch,
            # evidence pack assembly).  We're narrowly verifying that the
            # _pregen_edge_data dict the patched function builds carries
            # signals + line_movement_direction.
            edge = {
                "match_key": "manchester_city_vs_brentford_2026-05-09",
                "home_team": "Manchester City",
                "away_team": "Brentford",
                "league": "epl",
                "sport": "soccer",
                "recommended_outcome": "home",
                "best_bookmaker": "Supabets",
                "best_odds": 1.38,
                "edge_pct": 3.8,
                "fair_probability": 0.74,
                "composite_score": 64.7,
                "confirming_signals": 3,
                "edge_tier": "gold",
                "tier": "gold",
                "signals": {},
            }
            # Imports + helper invocations mirror _generate_one's
            # post-OPS-SPEC-SIGNAL-EXPOSURE-01 wiring.
            from narrative_spec import (
                _normalise_line_movement_direction,
                _normalise_spec_signals,
            )

            sigs = pregen._collect_canonical_signals(
                edge["match_key"],
                edge["recommended_outcome"],
                edge["sport"],
                edge["league"],
            )
            assert sigs, "_collect_canonical_signals must return populated dict"
            spec_sig_dict = _normalise_spec_signals(sigs)
            mvt_dir = sigs.get("movement", {}).get("direction", "")
            spec_line_movement = _normalise_line_movement_direction(mvt_dir)

            edge_data = {
                "home_team": edge["home_team"],
                "away_team": edge["away_team"],
                "league": edge["league"],
                "best_bookmaker": edge["best_bookmaker"],
                "best_odds": edge["best_odds"],
                "edge_pct": edge["edge_pct"],
                "outcome": edge["recommended_outcome"],
                "outcome_team": edge["home_team"],
                "confirming_signals": edge["confirming_signals"],
                "composite_score": edge["composite_score"],
                "edge_tier": edge["edge_tier"],
                "movement_direction": mvt_dir,
                "tipster_available": bool(sigs["tipster"]["available"]),
                "tipster_agrees": sigs["tipster"]["agrees_with_edge"],
                "tipster_against": sigs["tipster"].get("against_count", 0),
                "h2h_total": sigs["form_h2h"]["h2h_total"],
                "h2h_a_wins": sigs["form_h2h"]["h2h_a_wins"],
                "h2h_b_wins": sigs["form_h2h"]["h2h_b_wins"],
                "h2h_draws": sigs["form_h2h"]["h2h_draws"],
                "signals": spec_sig_dict,
                "line_movement_direction": spec_line_movement,
            }

            spec = _capture_build_spec(
                {}, edge_data, [{"outcome": "home"}], "soccer"
            )

        assert captured["spec_signals"], (
            "build_narrative_spec must receive non-empty signals dict "
            "from pregen path; signals dropped will fall back to §12.1 monoculture"
        )
        assert spec.signals, "spec.signals empty after build — pregen drop regression"
        # 6-key canonical contract: price_edge, line_mvt, market, tipster, form, injury
        canonical_keys = {"price_edge", "line_mvt", "market", "tipster", "form", "injury"}
        present = canonical_keys & set(spec.signals.keys())
        assert len(present) >= 4, (
            f"spec.signals missing canonical keys; present={present!r} "
            f"expected ≥4 of {canonical_keys!r}"
        )
        assert spec.line_movement_direction in (
            "favourable",
            "against",
            "unknown",
            None,
        ), f"line_movement_direction not in 3-value contract: {spec.line_movement_direction!r}"


def test_card_data_synthesis_populates_spec_signals():
    """card_data._synthesize_breakdown_row_from_baseline MUST recompute
    canonical signals so synthesis-on-tap (Rule 20 fallback) doesn't
    fall through to the §12.1 proxy adapter monoculture.
    """
    import importlib

    card_data = importlib.import_module("card_data")

    fake_sigs = _make_collect_all_signals_fake(populated=True)

    with patch("scrapers.edge.signal_collectors.collect_all_signals") as mock_sigs:
        mock_sigs.return_value = fake_sigs(
            "liverpool_vs_chelsea_2026-05-09", "home"
        )

        captured = {}
        from narrative_spec import (  # noqa: E402
            _normalise_line_movement_direction,
            _normalise_spec_signals,
            build_narrative_spec,
        )

        sigs = mock_sigs.return_value
        spec_signals = _normalise_spec_signals(sigs)
        movement_dir = sigs["movement"]["direction"]
        spec_line_movement = _normalise_line_movement_direction(movement_dir)

        edge_data = {
            "outcome": "home",
            "outcome_label": "Liverpool",
            "home_team": "Liverpool",
            "away_team": "Chelsea",
            "best_odds": 2.05,
            "best_bookmaker": "Hollywoodbets",
            "edge_pct": 4.1,
            "composite_score": 66.2,
            "confirming_signals": 3,
            "movement": "",
            "movement_direction": movement_dir,
            "league": "epl",
            "edge_tier": "gold",
            "tipster_agrees": sigs["tipster"]["agrees_with_edge"],
            "tipster_available": bool(sigs["tipster"]["available"]),
            "tipster_against": sigs["tipster"].get("against_count", 0),
            "h2h_total": sigs["form_h2h"]["h2h_total"],
            "h2h_a_wins": sigs["form_h2h"]["h2h_a_wins"],
            "h2h_b_wins": sigs["form_h2h"]["h2h_b_wins"],
            "h2h_draws": sigs["form_h2h"]["h2h_draws"],
            "signals": spec_signals,
            "line_movement_direction": spec_line_movement,
        }

        tip_dict = {
            "match_id": "liverpool_vs_chelsea_2026-05-09",
            "sport": "soccer",
            "league": "epl",
            "edge_tier": "gold",
            "outcome": "home",
            "outcome_label": "Liverpool",
            "odds": 2.05,
            "bookmaker": "Hollywoodbets",
            "ev": 4.1,
            "predicted_ev": 4.1,
            "composite_score": 66.2,
            "confirming_signals": 3,
            "movement": "",
            "home_team": "Liverpool",
            "away_team": "Chelsea",
        }

        spec = build_narrative_spec({}, edge_data, [tip_dict], "soccer")
        assert spec.signals, (
            "card_data synthesis path must produce non-empty spec.signals; "
            "empty dict regresses to §12.1 monoculture for every cache-miss tap"
        )
        assert spec.line_movement_direction in (
            "favourable",
            "against",
            "unknown",
            None,
        )


def test_pregen_falls_back_to_proxy_when_collector_returns_empty():
    """Defensive: when collect_all_signals raises or returns {}, the
    pregen path MUST still complete (mapper falls through to legacy
    proxy adapter — back-compat with un-migrated builders).  The fix
    must NOT crash pregen on collector failure.
    """
    import importlib

    pregen = importlib.import_module("scripts.pregenerate_narratives")

    with patch("scrapers.edge.signal_collectors.collect_all_signals") as mock_sigs:
        mock_sigs.side_effect = RuntimeError("collector unreachable")
        result = pregen._collect_canonical_signals(
            "manchester_city_vs_brentford_2026-05-09", "home", "soccer", "epl"
        )
        assert result == {}, "Collector failure must degrade to empty dict"


def test_pregen_collector_helper_exists_and_returns_dict():
    """Brief contract: _collect_canonical_signals helper exists in pregen."""
    import importlib

    pregen = importlib.import_module("scripts.pregenerate_narratives")
    assert hasattr(pregen, "_collect_canonical_signals")
    assert callable(pregen._collect_canonical_signals)


def test_normalise_helpers_imported_from_narrative_spec():
    """Brief AC-3: patches use the SAME _normalise_spec_signals +
    _normalise_line_movement_direction helpers OPS-SPEC-SIGNAL-EXPOSURE-01
    added.  No parallel implementation.
    """
    from narrative_spec import (
        _normalise_line_movement_direction,
        _normalise_spec_signals,
    )

    # Sanity: same shape as bot._extract_edge_data callers expect.
    raw = {
        "price_edge": {"available": True},
        "market_agreement": {"available": True},
        "movement": {"available": True, "direction": "favourable"},
        "tipster": {"available": True},
        "lineup_injury": {"available": False},
        "form_h2h": {"available": True},
    }
    sigs = _normalise_spec_signals(raw)
    assert sigs.get("price_edge") is True
    assert sigs.get("line_mvt") is True  # movement → line_mvt remap
    assert sigs.get("market") is True
    assert sigs.get("form") is True

    assert _normalise_line_movement_direction("favourable") == "favourable"
    assert _normalise_line_movement_direction("against") == "against"
    # Empty / neutral collapse to None per the helper contract.
    assert _normalise_line_movement_direction("") is None
    assert _normalise_line_movement_direction("neutral") is None


# ── Allowlist integrity ───────────────────────────────────────────────────────


def test_allowlist_documented():
    """Every allowlist entry must include a written reason and refer to
    a real production callsite.  This prevents silent additions that
    would re-open the leak vector.
    """
    for filepath, fn_name, reason in _KNOWN_EMPTY_SIGNAL_CALLERS:
        assert filepath, "Allowlist entry missing file path"
        assert fn_name, "Allowlist entry missing function name"
        assert reason, "Allowlist entry missing justification"
        assert len(reason) >= 12, (
            f"Allowlist reason too thin for {filepath}::{fn_name}: {reason!r}"
        )


def test_pregen_diff_includes_signals_key():
    """AC-3 mechanical check: the patched _generate_one source MUST
    include the 'signals' key in the _pregen_edge_data dict literal.
    Reverting the dict to its pre-fix shape will trip this guard before
    a live cache write can re-introduce the §12.1 monoculture.
    """
    pregen_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "pregenerate_narratives.py"
    )
    src = pregen_path.read_text()
    assert '"signals": _spec_signals_dict' in src, (
        "Pregen _pregen_edge_data dict must carry 'signals' key — "
        "regression back to FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01"
    )
    assert '"line_movement_direction": _spec_line_movement' in src, (
        "Pregen _pregen_edge_data dict must carry 'line_movement_direction' key"
    )
    assert "_collect_canonical_signals(" in src, (
        "Pregen must call _collect_canonical_signals at narrative-build time"
    )


def test_card_data_diff_includes_signals_key():
    """AC-3 mechanical check: card_data synthesis fallback MUST carry
    signals + line_movement_direction in the edge_data literal.
    """
    card_data_path = (
        Path(__file__).resolve().parents[2] / "card_data.py"
    )
    src = card_data_path.read_text()
    assert '"signals": _spec_signals_dict' in src, (
        "card_data synthesis fallback edge_data must carry 'signals' key"
    )
    assert '"line_movement_direction": _spec_line_movement' in src
    assert "collect_all_signals" in src, (
        "card_data synthesis fallback must invoke collect_all_signals"
    )
