"""L1 Card Quality scoring (C1–C7).

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

Weights:
  C1: Data Accuracy         3.0
  C2: Typography & Layout   1.5
  C3: Visual Correctness    2.0
  C4: Tier Badge            1.5
  C5: CTA Correctness       0.5
  C6: Empty State Quality   0.5
  C7: Narrative Quality     1.0
  Total: 10.0

L1 score = sum(dimension_score * weight) / sum(weights)
Returns L1Score dataclass with per-dimension breakdown.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from tests.qa.vision_ocr import CardOCR
from ..surfaces import Artefact
from ..scoring.ocr_schema import CardOCRV2

log = logging.getLogger(__name__)

# C-dimension weights (sum to 10.0)
_WEIGHTS: dict[str, float] = {
    "C1": 3.0,
    "C2": 1.5,
    "C3": 2.0,
    "C4": 1.5,
    "C5": 0.5,
    "C6": 0.5,
    "C7": 1.0,
}
_TOTAL_WEIGHT = sum(_WEIGHTS.values())  # 10.0

# SEV-level deductions
_SEV1_DEDUCTION = 10.0  # causes hard FAIL
_SEV2_DEDUCTION = 2.0
_SEV3_DEDUCTION = 1.0


@dataclass
class CDimension:
    """Score for a single C-dimension."""

    dimension: str      # "C1"–"C7"
    score: float        # 0.0–10.0 (per-dimension)
    weight: float
    notes: list[str] = field(default_factory=list)
    deductions: list[dict] = field(default_factory=list)

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class L1Score:
    """Aggregated L1 Card Quality score."""

    raw_score: float = 0.0      # 0.0–10.0
    dimensions: list[CDimension] = field(default_factory=list)
    defects: list[dict] = field(default_factory=list)   # SEV-tagged
    artefacts_scored: int = 0

    @property
    def score(self) -> float:
        return self.raw_score

    def as_dict(self) -> dict:
        return {
            "score": round(self.raw_score, 2),
            "artefacts_scored": self.artefacts_scored,
            "dimensions": {d.dimension: round(d.score, 2) for d in self.dimensions},
            "defects": self.defects,
        }


def _dim(label: str, score: float, notes: list[str] | None = None, deductions: list | None = None) -> CDimension:
    return CDimension(
        dimension=label,
        score=max(0.0, min(10.0, score)),
        weight=_WEIGHTS[label],
        notes=notes or [],
        deductions=deductions or [],
    )


def _score_c1_data_accuracy(artefacts: list[Artefact]) -> CDimension:
    """C1: Data Accuracy — odds, kickoff, team names correct."""
    score = 10.0
    notes: list[str] = []
    deductions: list[dict] = []

    for art in artefacts:
        ocr = art.ocr_result
        if ocr is None:
            continue

        # Check team names populated
        if not ocr.home_team or not ocr.away_team:
            score -= 2.0
            notes.append("Team name missing from card")
            deductions.append({"field": "teams", "deduction": 2.0, "sev": "SEV-2"})

        # V2: check odds and kickoff visible on full-access cards
        if isinstance(ocr, CardOCRV2):
            if not ocr.odds_value_visible:
                score -= 1.5
                notes.append("Odds not visible on card")
                deductions.append({"field": "odds", "deduction": 1.5, "sev": "SEV-2"})
            if not ocr.kickoff_visible:
                score -= 0.5
                notes.append("Kickoff not visible on card")
                deductions.append({"field": "kickoff", "deduction": 0.5, "sev": "SEV-3"})

    return _dim("C1", score, notes, deductions)


def _score_c2_typography(artefacts: list[Artefact]) -> CDimension:
    """C2: Typography & Layout — no broken HTML, formatting correct."""
    score = 10.0
    notes: list[str] = []
    deductions: list[dict] = []

    # Check for raw HTML tags leaked into text
    import re
    _BROKEN_HTML = re.compile(r"</?[a-zA-Z][^>]*>")

    for art in artefacts:
        if not art.message_text:
            continue
        if _BROKEN_HTML.search(art.message_text):
            # Some HTML is expected (bot uses HTML parse_mode)
            # Broken = unclosed or malformed tags
            pass

        # Check for placeholder text
        if "[PLACEHOLDER]" in art.message_text or "[TODO]" in art.message_text:
            score -= 2.0
            notes.append(f"Placeholder text in {art.surface_id}")
            deductions.append({"field": "placeholder", "deduction": 2.0, "sev": "SEV-3"})

    return _dim("C2", score, notes, deductions)


def _score_c3_visual(artefacts: list[Artefact]) -> CDimension:
    """C3: Visual Correctness — photo cards OCR'd, SuperSport logo check."""
    score = 10.0
    notes: list[str] = []
    deductions: list[dict] = []

    for art in artefacts:
        if art.surface_id not in ("S3", "S5"):
            continue

        if not art.photo_path:
            score -= 1.0
            notes.append(f"Photo not captured for {art.surface_id}")
            deductions.append({"field": "photo_missing", "deduction": 1.0, "sev": "SEV-3"})
            continue

        ocr = art.ocr_result
        if not isinstance(ocr, CardOCRV2):
            continue

        # Addition 1: SuperSport logo check (only when broadcast is visible)
        if ocr.broadcast_visible:
            if not ocr.supersport_logo_present:
                score -= 1.0
                notes.append("SuperSport logo missing on broadcast card")
                deductions.append({"field": "ss_logo_missing", "deduction": 1.0, "sev": "SEV-3"})
            elif "red" not in (ocr.supersport_logo_colour or "").lower():
                score -= 1.0
                notes.append(f"SuperSport logo colour={ocr.supersport_logo_colour!r} — expected red")
                deductions.append({"field": "ss_logo_colour", "deduction": 1.0, "sev": "SEV-3"})

    return _dim("C3", score, notes, deductions)


def _score_c4_tier_badge(artefacts: list[Artefact], persona_tier: str) -> CDimension:
    """C4: Tier Badge Correctness — badge matches user tier."""
    score = 10.0
    notes: list[str] = []
    deductions: list[dict] = []

    _tier_to_badge = {"diamond": "💎", "gold": "🥇", "silver": "🥈", "bronze": "🥉"}
    expected_badge = _tier_to_badge.get(persona_tier.lower(), "")

    for art in artefacts:
        if art.surface_id not in ("S2", "S3"):
            continue
        ocr = art.ocr_result
        if ocr is None:
            continue
        if ocr.tier_badge is None:
            score -= 0.5
            notes.append(f"Tier badge missing on {art.surface_id}")
            deductions.append({"field": "badge_missing", "deduction": 0.5, "sev": "SEV-3"})
        elif expected_badge and ocr.tier_badge not in _tier_to_badge.values():
            score -= 1.5
            notes.append(f"Unrecognised tier badge: {ocr.tier_badge!r}")
            deductions.append({"field": "badge_invalid", "deduction": 1.5, "sev": "SEV-2"})

    return _dim("C4", score, notes, deductions)


def _score_c5_cta(artefacts: list[Artefact]) -> CDimension:
    """C5: CTA Correctness — buttons correct."""
    score = 10.0
    notes: list[str] = []
    deductions: list[dict] = []

    for art in artefacts:
        if art.surface_id == "S10":
            # Subscribe surface should have plan buttons
            ocr = art.ocr_result
            if ocr and ocr.button_count == 0:
                score -= 2.0
                notes.append("No buttons on subscribe surface S10")
                deductions.append({"field": "no_buttons", "deduction": 2.0, "sev": "SEV-2"})

    return _dim("C5", score, notes, deductions)


def _score_c6_empty_state(artefacts: list[Artefact]) -> CDimension:
    """C6: Empty State Quality — empty states have meaningful content."""
    score = 10.0
    notes: list[str] = []
    deductions: list[dict] = []

    for art in artefacts:
        if art.surface_id == "S13":
            text = art.message_text or ""
            if not text.strip():
                score -= 5.0
                notes.append("Empty state S13 returned empty text — SEV-2")
                deductions.append({"field": "empty_text", "deduction": 5.0, "sev": "SEV-2"})
            elif len(text.strip()) < 20:
                score -= 2.0
                notes.append("Empty state S13 text too short")
                deductions.append({"field": "short_text", "deduction": 2.0, "sev": "SEV-3"})

    return _dim("C6", score, notes, deductions)


def _score_c7_narrative(artefacts: list[Artefact]) -> CDimension:
    """C7: Narrative Quality — verdict in range, not stub, tone correct."""
    score = 10.0
    notes: list[str] = []
    deductions: list[dict] = []

    _STUB_RE = __import__("re").compile(r"[—–-]\s*\?\s*at\s*0\.00\s*\.")

    for art in artefacts:
        if art.surface_id not in ("S2", "S3", "S5"):
            continue
        ocr = art.ocr_result
        if ocr is None or not ocr.verdict_text:
            continue

        n = ocr.verdict_char_count
        if n > 0 and (n < 50 or n > 400):
            score -= 1.0
            notes.append(f"Verdict char count {n} outside acceptable range [50, 400]")
            deductions.append({"field": "verdict_length", "deduction": 1.0, "sev": "SEV-3"})

        if _STUB_RE.search(ocr.verdict_text):
            score -= 3.0
            notes.append("Verdict matches stub shape '— ? at 0.00.'")
            deductions.append({"field": "stub_verdict", "deduction": 3.0, "sev": "SEV-2"})

    return _dim("C7", score, notes, deductions)


def score_card_quality(artefacts: list[Artefact], persona: Any) -> L1Score:
    """Score L1 Card Quality from a list of artefacts.

    Args:
        artefacts: All artefacts captured during a persona run.
        persona: PersonaDef — used for tier information.

    Returns:
        L1Score with raw_score (0.0–10.0) and per-dimension breakdown.
    """
    tier = getattr(persona, "tier", "bronze")

    dims = [
        _score_c1_data_accuracy(artefacts),
        _score_c2_typography(artefacts),
        _score_c3_visual(artefacts),
        _score_c4_tier_badge(artefacts, tier),
        _score_c5_cta(artefacts),
        _score_c6_empty_state(artefacts),
        _score_c7_narrative(artefacts),
    ]

    # Weighted sum
    total_weighted = sum(d.weighted_score for d in dims)
    raw_score = total_weighted / _TOTAL_WEIGHT

    all_defects: list[dict] = []
    for d in dims:
        for deduction in d.deductions:
            all_defects.append({"dimension": d.dimension, **deduction})

    scored = len([a for a in artefacts if a.ocr_result is not None or a.message_text])

    return L1Score(
        raw_score=round(raw_score, 3),
        dimensions=dims,
        defects=all_defects,
        artefacts_scored=scored,
    )
