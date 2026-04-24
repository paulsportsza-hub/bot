"""L3 Coverage scoring (K1–K3).

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

Weights (as % of L3 composite):
  K1: Surface Coverage    40%
  K2: Cross-Sport Parity  30%
  K3: Cross-Tier Parity   30%

L3 score = weighted mean of K1–K3, each normalised to 0.0–10.0.
Hard override: K3 < 80% testable cells = FAIL.

Run composite = 0.65 × mean(persona_composite) + 0.35 × L3
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..gate_matrix import (
    GateCell, k3_coverage, K3_MIN_CELLS_FRACTION, TOTAL_GATE_CELLS,
)
from ..surfaces import Artefact

log = logging.getLogger(__name__)

# Surfaces required for full K1 coverage
_REQUIRED_SURFACES = {"S0", "S1", "S2", "S3", "S4", "S6", "S7", "S10", "S11"}

# Sports required for full K2 coverage
_REQUIRED_SPORTS = {"soccer", "rugby", "cricket"}


@dataclass
class KDimension:
    dimension: str
    score: float
    weight: float
    notes: list[str] = field(default_factory=list)


@dataclass
class L3Score:
    raw_score: float = 0.0
    dimensions: list[KDimension] = field(default_factory=list)
    k3_fraction: float = 0.0    # captured for hard override
    gate_cells_tested: int = 0
    gate_cells_total: int = TOTAL_GATE_CELLS

    @property
    def score(self) -> float:
        return self.raw_score

    @property
    def k3_passes_hard_override(self) -> bool:
        return self.k3_fraction >= K3_MIN_CELLS_FRACTION

    def as_dict(self) -> dict:
        return {
            "score": round(self.raw_score, 2),
            "k3_fraction": round(self.k3_fraction, 3),
            "gate_cells_tested": self.gate_cells_tested,
            "gate_cells_total": self.gate_cells_total,
            "k3_passes": self.k3_passes_hard_override,
            "dimensions": {d.dimension: round(d.score, 2) for d in self.dimensions},
        }


def _k1_surface_coverage(all_artefacts: list[Artefact]) -> KDimension:
    """K1: Surface Coverage — required surfaces visited."""
    visited = {a.surface_id for a in all_artefacts if a.surface_id}
    covered = _REQUIRED_SURFACES & visited
    fraction = len(covered) / len(_REQUIRED_SURFACES)
    score = fraction * 10.0
    missing = _REQUIRED_SURFACES - visited
    notes: list[str] = []
    if missing:
        notes.append(f"Missing surfaces: {sorted(missing)}")
    notes.append(f"Covered {len(covered)}/{len(_REQUIRED_SURFACES)} required surfaces")
    return KDimension("K1", round(score, 2), 0.40, notes=notes)


def _k2_sport_parity(persona_sports: list[str]) -> KDimension:
    """K2: Cross-Sport Parity — sports covered across personas."""
    covered = set(s.lower() for s in persona_sports)
    required = _REQUIRED_SPORTS
    fraction = len(covered & required) / len(required)
    score = fraction * 10.0
    missing = required - covered
    notes: list[str] = []
    if missing:
        notes.append(f"Sports not covered: {sorted(missing)}")
    return KDimension("K2", round(score, 2), 0.30, notes=notes)


def _k3_tier_parity(all_cells: list[GateCell]) -> KDimension:
    """K3: Cross-Tier Parity — GATE_MATRIX cells tested across all personas."""
    fraction = k3_coverage(all_cells)
    score = fraction * 10.0
    tested_count = len({(c.user_tier, c.edge_tier) for c in all_cells if c.tested})
    notes = [f"Tested {tested_count}/{TOTAL_GATE_CELLS} GATE_MATRIX cells ({fraction*100:.0f}%)"]
    if fraction < K3_MIN_CELLS_FRACTION:
        notes.append(f"HARD OVERRIDE: K3={fraction*100:.0f}% < {K3_MIN_CELLS_FRACTION*100:.0f}% threshold")
    return KDimension("K3", round(score, 2), 0.30, notes=notes)


def score_coverage(
    all_artefacts: list[Artefact],
    all_gate_cells: list[GateCell],
    persona_sports: list[str],
) -> L3Score:
    """Score L3 Coverage.

    Args:
        all_artefacts: Merged artefacts from all persona runs.
        all_gate_cells: Merged gate cells from all persona runs.
        persona_sports: All sports covered across all personas.

    Returns:
        L3Score with 0.0–10.0 composite.
    """
    k1 = _k1_surface_coverage(all_artefacts)
    k2 = _k2_sport_parity(persona_sports)
    k3 = _k3_tier_parity(all_gate_cells)

    dims = [k1, k2, k3]
    raw_score = sum(d.score * d.weight for d in dims)
    k3_frac = k3_coverage(all_gate_cells)
    tested_count = len({(c.user_tier, c.edge_tier) for c in all_gate_cells if c.tested})

    return L3Score(
        raw_score=round(raw_score, 3),
        dimensions=dims,
        k3_fraction=k3_frac,
        gate_cells_tested=tested_count,
    )


def compute_run_composite(
    persona_composites: list[float],
    l3_score: float,
) -> float:
    """Run composite = 0.65 × mean(persona_composite) + 0.35 × L3."""
    if not persona_composites:
        return 0.0
    mean_persona = sum(persona_composites) / len(persona_composites)
    return round(0.65 * mean_persona + 0.35 * l3_score, 3)


def persona_composite(l1_score: float, l2_score: float) -> float:
    """Persona composite = 0.5 × L1 + 0.5 × L2."""
    return round(0.5 * l1_score + 0.5 * l2_score, 3)
