"""L2 Journey Integrity scoring (J1–J5).

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

Weights (as % of L2 composite):
  J1: Journey Completion Rate  30%
  J2: Onboarding Quality       20%
  J3: Response Latency         20%
  J4: Error Recovery           15%
  J5: Tier-Gating Correctness  15%

L2 score = weighted mean of J1–J5, each normalised to 0.0–10.0.
Hard override: J5 < 5.0 on ANY persona = FAIL.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..gate_matrix import GateCell, score_gate_cells
from ..surfaces import get_sla, Artefact

log = logging.getLogger(__name__)

_WEIGHTS: dict[str, float] = {
    "J1": 0.30,
    "J2": 0.20,
    "J3": 0.20,
    "J4": 0.15,
    "J5": 0.15,
}


@dataclass
class JDimension:
    dimension: str
    score: float        # 0.0–10.0
    weight: float
    notes: list[str] = field(default_factory=list)


@dataclass
class L2Score:
    raw_score: float = 0.0
    dimensions: list[JDimension] = field(default_factory=list)
    j5_score: float = 0.0    # captured separately for hard override check

    @property
    def score(self) -> float:
        return self.raw_score

    def as_dict(self) -> dict:
        return {
            "score": round(self.raw_score, 2),
            "j5_score": round(self.j5_score, 2),
            "dimensions": {d.dimension: round(d.score, 2) for d in self.dimensions},
        }


def _j1_completion(steps_completed: int, steps_total: int) -> JDimension:
    """J1: Journey Completion Rate — steps_completed / steps_total."""
    rate = (steps_completed / max(steps_total, 1)) * 10.0
    return JDimension("J1", min(10.0, rate), _WEIGHTS["J1"],
                       notes=[f"completed {steps_completed}/{steps_total}"])


def _j2_onboarding(artefacts: list[Artefact], defects: list[dict]) -> JDimension:
    """J2: Onboarding Quality — S0 surfaces reached, no blocking defects."""
    score = 10.0
    notes: list[str] = []

    s0_count = sum(1 for a in artefacts if a.surface_id == "S0")
    if s0_count == 0:
        score -= 5.0
        notes.append("No S0 onboarding artefacts captured")
    elif s0_count < 3:
        score -= 2.0
        notes.append(f"Only {s0_count} S0 steps captured — onboarding may be incomplete")

    # Penalise blocking defects on S0
    for d in defects:
        desc = d.get("description", "").lower()
        if "onboarding" in desc and d.get("sev") == "1":
            score -= 5.0
            notes.append(f"Onboarding blocked: {d.get('description', '')}")
            break

    return JDimension("J2", max(0.0, score), _WEIGHTS["J2"], notes=notes)


def _j3_latency(artefacts: list[Artefact]) -> JDimension:
    """J3: Response Latency — within SLA for each surface."""
    score = 10.0
    notes: list[str] = []
    violations = 0
    total = 0

    for art in artefacts:
        if art.response_time_s <= 0:
            continue
        sla = get_sla(art.surface_id)
        total += 1
        if art.response_time_s > sla:
            violations += 1
            notes.append(
                f"{art.surface_id}: {art.response_time_s:.1f}s > SLA {sla}s"
            )

    if total > 0:
        violation_rate = violations / total
        score -= violation_rate * 6.0   # up to -6.0 for all SLA violations
        # Cap extra deduction for severe outliers (>3× SLA)
        severe = sum(
            1 for a in artefacts
            if a.response_time_s > 0 and a.response_time_s > get_sla(a.surface_id) * 3
        )
        if severe > 0:
            score -= min(severe * 1.0, 3.0)
            notes.append(f"{severe} responses exceeded 3× SLA")

    return JDimension("J3", max(0.0, min(10.0, score)), _WEIGHTS["J3"], notes=notes)


def _j4_error_recovery(defects: list[dict]) -> JDimension:
    """J4: Error Recovery — error states handled without dead ends."""
    score = 10.0
    notes: list[str] = []

    sev1 = [d for d in defects if d.get("sev") == "1"]
    sev2 = [d for d in defects if d.get("sev") == "2"]
    sev3 = [d for d in defects if d.get("sev") == "3"]

    score -= len(sev1) * 4.0
    score -= len(sev2) * 1.5
    score -= len(sev3) * 0.5

    if sev1:
        notes.append(f"{len(sev1)} SEV-1 defects (tier leak / onboarding blocked / payment)")
    if sev2:
        notes.append(f"{len(sev2)} SEV-2 defects (data mismatch / broken button)")
    if sev3:
        notes.append(f"{len(sev3)} SEV-3 defects (visual / non-critical)")

    return JDimension("J4", max(0.0, min(10.0, score)), _WEIGHTS["J4"], notes=notes)


def _j5_tier_gating(gate_cells: list[GateCell]) -> JDimension:
    """J5: Tier-Gating Correctness — GATE_MATRIX cells match expected."""
    tested = [c for c in gate_cells if c.tested]
    if not tested:
        # No cells tested — score 0 (hard override will fire)
        return JDimension("J5", 0.0, _WEIGHTS["J5"],
                          notes=["No GATE_MATRIX cells tested"])

    pass_rate = score_gate_cells(gate_cells)
    score = pass_rate * 10.0
    notes: list[str] = []

    failed = [c for c in tested if not c.passed]
    if failed:
        for c in failed:
            notes.append(
                f"Gate fail: {c.user_tier}×{c.edge_tier} "
                f"expected={c.expected!r} actual={c.actual!r}"
            )

    notes.append(f"{len(tested)}/{len(gate_cells)} cells tested, {len(failed)} failed")
    return JDimension("J5", max(0.0, score), _WEIGHTS["J5"], notes=notes)


def score_journey(
    steps_completed: int,
    steps_total: int,
    artefacts: list[Artefact],
    defects: list[dict],
    gate_cells: list[GateCell],
    aborted: bool = False,
) -> L2Score:
    """Score L2 Journey Integrity.

    Args:
        steps_completed: How many script steps were completed.
        steps_total: Total expected script steps.
        artefacts: All captured artefacts (for latency).
        defects: Defect list from persona script.
        gate_cells: GATE_MATRIX cell results.
        aborted: Whether the persona script aborted early.

    Returns:
        L2Score with 0.0–10.0 composite and per-dimension breakdown.
    """
    if aborted:
        # Aborted runs cap J1 at what was completed; J4 penalised
        defects = defects + [{"sev": "1", "description": "Script aborted"}]

    j1 = _j1_completion(steps_completed, steps_total)
    j2 = _j2_onboarding(artefacts, defects)
    j3 = _j3_latency(artefacts)
    j4 = _j4_error_recovery(defects)
    j5 = _j5_tier_gating(gate_cells)

    dims = [j1, j2, j3, j4, j5]

    # Weighted mean (weights sum to 1.0)
    raw_score = sum(d.score * d.weight for d in dims)

    return L2Score(
        raw_score=round(raw_score, 3),
        dimensions=dims,
        j5_score=j5.score,
    )
