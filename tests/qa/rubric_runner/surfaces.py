"""Surface taxonomy for the QA Rubric Runner.

BUILD-QA-RUBRIC-RUNNER-01 — Phase A

Surfaces (S0–S17) and card taxonomy (C0–C14) define which part of the bot
each captured artefact belongs to.  Used by scoring modules and the report
generator to map evidence to rubric dimensions.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SurfaceDef:
    """Descriptor for a single bot surface."""

    surface_id: str          # e.g. "S2"
    name: str                # human label
    sla_seconds: float       # J3 SLA
    photo_expected: bool = False   # True when a photo card is the deliverable


@dataclass(frozen=True)
class CardDef:
    """Descriptor for a card type captured during a run."""

    card_id: str          # e.g. "C3-EDGEDETAIL"
    name: str
    surface_id: str       # which surface this card appears on


# ── Surface registry ─────────────────────────────────────────────────────────

SURFACES: dict[str, SurfaceDef] = {
    "S0": SurfaceDef("S0", "Onboarding flow",                   sla_seconds=3.0),
    "S1": SurfaceDef("S1", "Main menu / sticky keyboard",       sla_seconds=2.0),
    "S2": SurfaceDef("S2", "Top Edge Picks list",               sla_seconds=5.0),
    "S3": SurfaceDef("S3", "Edge Detail card",                  sla_seconds=8.0,  photo_expected=True),
    "S4": SurfaceDef("S4", "My Matches list",                   sla_seconds=5.0),
    "S5": SurfaceDef("S5", "Match Detail card",                 sla_seconds=8.0,  photo_expected=True),
    "S6": SurfaceDef("S6", "Settings menu",                     sla_seconds=4.0),
    "S7": SurfaceDef("S7", "Help screen",                       sla_seconds=4.0),
    "S8": SurfaceDef("S8", "Guide topics",                      sla_seconds=4.0),
    "S9": SurfaceDef("S9", "Results / tracker",                 sla_seconds=4.0),
    "S10": SurfaceDef("S10", "Subscribe plan picker",           sla_seconds=3.0),
    "S11": SurfaceDef("S11", "Email prompt + Payment link",     sla_seconds=5.0),
    "S12": SurfaceDef("S12", "Payment confirm / fail push",     sla_seconds=4.0),
    "S13": SurfaceDef("S13", "Empty state (no edges)",          sla_seconds=4.0),
    "S14": SurfaceDef("S14", "Filter views",                    sla_seconds=4.0),
    "S15": SurfaceDef("S15", "Upgrade prompt",                  sla_seconds=4.0),
    "S16": SurfaceDef("S16", "Billing / status",                sla_seconds=4.0),
    "S17": SurfaceDef("S17", "Morning teaser (simulated)",      sla_seconds=4.0),
}


def get_sla(surface_id: str) -> float:
    """Return the J3 SLA in seconds for a surface; default 4s if unknown."""
    return SURFACES.get(surface_id, SurfaceDef(surface_id, "unknown", 4.0)).sla_seconds


# ── Card taxonomy ─────────────────────────────────────────────────────────────

CARDS: dict[str, CardDef] = {
    "C1-DIGEST":      CardDef("C1-DIGEST",      "Digest / summary card",       "S2"),
    "C2-FILTER":      CardDef("C2-FILTER",       "Filter view card",            "S14"),
    "C3-EDGEDETAIL":  CardDef("C3-EDGEDETAIL",   "Edge detail photo card",      "S3"),
    "C4-MM":          CardDef("C4-MM",           "My Matches list",             "S4"),
    "C5-MATCHDETAIL": CardDef("C5-MATCHDETAIL",  "Match detail photo card",     "S5"),
    "C6-SUBSCRIBE":   CardDef("C6-SUBSCRIBE",    "Subscribe plan picker card",  "S10"),
    "C7-EMAIL":       CardDef("C7-EMAIL",        "Email prompt card",           "S11"),
    "C8-PAYLINK":     CardDef("C8-PAYLINK",      "Payment link card",           "S11"),
}


# ── Artefact structure ────────────────────────────────────────────────────────

@dataclass
class Artefact:
    """A single captured message or photo from a persona run."""

    surface_id: str
    timestamp: float           # epoch seconds (time.time())
    message_text: str = ""
    photo_path: str = ""       # path to downloaded photo, if any
    ocr_result: object = None  # CardOCR or CardOCRV2 instance, if OCR was run
    response_time_s: float = 0.0   # time from send to first reply
    card_id: str = ""              # C3-EDGEDETAIL etc., optional
