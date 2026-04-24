"""GATE_MATRIX definitions and expected cells per persona.

BUILD-QA-RUBRIC-RUNNER-01 — Phase A

The GATE_MATRIX maps (user_tier, edge_tier) → expected access level.
Reference: tier_gate.get_edge_access_level().

Hard override (LOCKED): K3 < 80 % of testable cells = FAIL.
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Canonical matrix ──────────────────────────────────────────────────────────
#   key: (user_tier, edge_tier)  value: expected access level string

GATE_MATRIX: dict[tuple[str, str], str] = {
    ("bronze",  "bronze"):  "full",
    ("bronze",  "silver"):  "partial",
    ("bronze",  "gold"):    "blurred",
    ("bronze",  "diamond"): "locked",

    ("silver",  "bronze"):  "full",
    ("silver",  "silver"):  "full",
    ("silver",  "gold"):    "partial",
    ("silver",  "diamond"): "blurred",

    ("gold",    "bronze"):  "full",
    ("gold",    "silver"):  "full",
    ("gold",    "gold"):    "full",
    ("gold",    "diamond"): "partial",

    ("diamond", "bronze"):  "full",
    ("diamond", "silver"):  "full",
    ("diamond", "gold"):    "full",
    ("diamond", "diamond"): "full",
}

# Total testable cells — used for K3 threshold
TOTAL_GATE_CELLS = len(GATE_MATRIX)  # 16

# 80 % threshold for K3 hard override
K3_MIN_CELLS_FRACTION = 0.80


@dataclass
class GateCell:
    """A single tested GATE_MATRIX cell."""

    user_tier: str
    edge_tier: str
    expected: str
    actual: str = ""
    tested: bool = False

    @property
    def passed(self) -> bool:
        return self.tested and self.actual == self.expected

    @property
    def cell_key(self) -> tuple[str, str]:
        return (self.user_tier, self.edge_tier)


# ── Per-persona expected cells ────────────────────────────────────────────────

PERSONA_GATE_CELLS: dict[str, list[tuple[str, str]]] = {
    "P1": [
        ("bronze", "bronze"),
        ("bronze", "silver"),
        ("bronze", "gold"),
        ("bronze", "diamond"),
    ],
    "P2": [
        ("gold", "bronze"),
        ("gold", "silver"),
        ("gold", "gold"),
        ("gold", "diamond"),
    ],
    "P3": [
        ("diamond", "bronze"),
        ("diamond", "silver"),
        ("diamond", "gold"),
        ("diamond", "diamond"),
    ],
    "P4": [
        # Edge cases — tests whichever cells are reachable from the reset state
        ("bronze", "bronze"),
        ("bronze", "silver"),
    ],
}


def build_gate_cells(persona_id: str) -> list[GateCell]:
    """Build an untested GateCell list for the given persona."""
    expected_pairs = PERSONA_GATE_CELLS.get(persona_id, [])
    return [
        GateCell(
            user_tier=ut,
            edge_tier=et,
            expected=GATE_MATRIX[(ut, et)],
        )
        for ut, et in expected_pairs
    ]


def score_gate_cells(cells: list[GateCell]) -> float:
    """Return fraction of tested cells that passed (0.0–1.0)."""
    tested = [c for c in cells if c.tested]
    if not tested:
        return 0.0
    return sum(1 for c in tested if c.passed) / len(tested)


def k3_coverage(all_cells: list[GateCell]) -> float:
    """K3: fraction of ALL 16 GATE_MATRIX cells that were tested across all personas."""
    tested_keys = {c.cell_key for c in all_cells if c.tested}
    return len(tested_keys) / TOTAL_GATE_CELLS
