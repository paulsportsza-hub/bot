"""Extended CardOCR dataclass for V2 fields.

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

CardOCRV2 extends the original CardOCR with fields introduced by OCR_PROMPT_V2.
The V1 CardOCR is unchanged and used by the ground-truth suite.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from tests.qa.vision_ocr import CardOCR


@dataclass
class CardOCRV2(CardOCR):
    """Extended OCR reading with V2 prompt fields.

    All new fields default to None / False / empty so V2 cards can be
    used anywhere a V1 CardOCR is expected without attribute errors.
    """

    # Team visibility
    home_team_visible: bool = False
    away_team_visible: bool = False

    # Individual field visibility
    kickoff_visible: bool = False
    league_visible: bool = False
    broadcast_visible: bool = False
    odds_value_visible: bool = False
    bookmaker_name_visible: bool = False

    # Content
    sections_present: list[str] = field(default_factory=list)
    tier_badge_v2: str | None = None    # same as tier_badge; re-parsed from V2 prompt

    # Verdict
    verdict_text_v2: str = ""           # full verdict body from V2 prompt

    # SuperSport logo (Addition 1)
    supersport_logo_present: bool = False
    supersport_logo_colour: str = ""    # e.g. "red", "white", None if absent
