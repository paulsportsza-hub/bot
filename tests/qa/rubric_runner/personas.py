"""Persona definitions for the QA Rubric Runner.

BUILD-QA-RUBRIC-RUNNER-01 — Phase A

P1 — Bronze (Soccer only, 30 steps)
P2 — Gold (Multi-sport: Soccer+Rugby+Cricket, 15 steps)
P3 — Diamond (Multi-sport, 16 steps)
P4 — Edge Cases (6 steps)
"""
from __future__ import annotations

from dataclasses import dataclass

from .gate_matrix import PERSONA_GATE_CELLS


@dataclass(frozen=True)
class PersonaDef:
    """Static definition of a QA persona."""

    persona_id: str           # "P1", "P2", "P3", "P4"
    name: str                 # Human label
    tier: str                 # "bronze", "gold", "diamond"
    sports: list[str]         # sport keys selected during onboarding
    steps_total: int          # expected steps in the script
    gate_matrix_cells: list[tuple[str, str]]   # (user_tier, edge_tier) pairs to test
    description: str = ""


PERSONAS: dict[str, PersonaDef] = {
    "P1": PersonaDef(
        persona_id="P1",
        name="Bronze — Soccer Only",
        tier="bronze",
        sports=["soccer"],
        steps_total=30,
        gate_matrix_cells=PERSONA_GATE_CELLS["P1"],
        description=(
            "Fresh Bronze user. Goes through full onboarding (Soccer, Bafana, "
            "risk 3, R300, 7AM), visits Edge Picks, taps first edge, visits "
            "My Matches, Settings, Help, then initiates subscription flow E2E "
            "with STITCH_MOCK_MODE=True."
        ),
    ),
    "P2": PersonaDef(
        persona_id="P2",
        name="Gold — Multi-Sport",
        tier="gold",
        sports=["soccer", "rugby", "cricket"],
        steps_total=15,
        gate_matrix_cells=PERSONA_GATE_CELLS["P2"],
        description=(
            "Gold user. Onboards with Soccer+Rugby+Cricket, Aggressive risk, "
            "R3000, 18:00. Tier set via /qa set_gold. Verifies Gold access "
            "levels including Silver (full) and Diamond (partial) edges."
        ),
    ),
    "P3": PersonaDef(
        persona_id="P3",
        name="Diamond — Multi-Sport",
        tier="diamond",
        sports=["soccer", "rugby", "cricket"],
        steps_total=16,
        gate_matrix_cells=PERSONA_GATE_CELLS["P3"],
        description=(
            "Diamond user. All sports. Tier set via /qa set_diamond. "
            "Verifies full access to all edge tiers including Diamond edges. "
            "Also triggers teaser simulation via /qa teaser_diamond."
        ),
    ),
    "P4": PersonaDef(
        persona_id="P4",
        name="Edge Cases",
        tier="bronze",
        sports=["soccer"],
        steps_total=6,
        gate_matrix_cells=PERSONA_GATE_CELLS["P4"],
        description=(
            "Edge case coverage: empty states when no matches/edges, "
            "freetext input handling, and settings navigation resilience."
        ),
    ),
}


def get_persona(persona_id: str) -> PersonaDef:
    """Return PersonaDef for a given ID, raising KeyError if unknown."""
    if persona_id not in PERSONAS:
        raise KeyError(f"Unknown persona: {persona_id!r}. Valid: {list(PERSONAS)}")
    return PERSONAS[persona_id]


def parse_personas_arg(arg: str) -> list[PersonaDef]:
    """Parse comma-separated persona IDs from CLI arg, e.g. 'P1,P2,P3,P4'."""
    ids = [x.strip().upper() for x in arg.split(",") if x.strip()]
    unknown = [i for i in ids if i not in PERSONAS]
    if unknown:
        raise ValueError(f"Unknown persona IDs: {unknown}. Valid: {list(PERSONAS)}")
    return [PERSONAS[i] for i in ids]
