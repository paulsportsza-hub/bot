"""OCR bridge — switches between V1 and V2 OCR based on config.USE_OCR_V2.

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

- V1 (USE_OCR_V2=False): delegates directly to vision_ocr.ocr_card()
  Returns CardOCR.

- V2 (USE_OCR_V2=True): calls Claude with OCR_PROMPT_V2 and parses into
  CardOCRV2 (a superset of CardOCR).  The ground-truth suite is unaffected
  because it imports vision_ocr.ocr_card() directly, never this bridge.

OCR_PROMPT is immutable per SO #30.  V2 is a new constant in ocr_prompt.py.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Union

from tests.qa.ocr_prompt import OCR_PROMPT, OCR_PROMPT_V2, ALLOWED_TIER_BADGES
from tests.qa.vision_ocr import CardOCR, _encode_image, _extract_json_blob
from .config import USE_OCR_V2
from .scoring.ocr_schema import CardOCRV2

log = logging.getLogger(__name__)

OCRResult = Union[CardOCR, CardOCRV2]

_MODEL = "claude-opus-4-7"
_MAX_TOKENS = 1500


def _coerce_bool(val: object) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _coerce_list_str(val: object) -> list[str]:
    if isinstance(val, list):
        return [str(x) for x in val if isinstance(x, str)]
    return []


def _parse_v2(raw: str) -> CardOCRV2:
    """Parse a V2 OCR response into a CardOCRV2 dataclass."""
    blob = _extract_json_blob(raw)
    data = json.loads(blob)

    # Base V1 fields
    verdict = " ".join(str(data.get("verdict_text", "") or "").split())
    home = str(data.get("home_team", "") or "").strip()
    away = str(data.get("away_team", "") or "").strip()

    button_count_raw = data.get("button_count", 0)
    try:
        button_count = int(button_count_raw)
    except (TypeError, ValueError):
        button_count = 0

    tier_raw = data.get("tier_badge", "")
    tier_badge = tier_raw.strip() if tier_raw.strip() in ALLOWED_TIER_BADGES else None

    base = CardOCR(
        verdict_text=verdict,
        verdict_char_count=len(verdict),
        home_team=home,
        away_team=away,
        tier_badge=tier_badge,
        button_count=button_count,
        button_labels=_coerce_list_str(data.get("button_labels")),
        raw_response=raw,
    )

    # V2-only fields
    ss_colour = str(data.get("supersport_logo_colour", "") or "").strip().lower()

    return CardOCRV2(
        # Inherit base fields
        verdict_text=base.verdict_text,
        verdict_char_count=base.verdict_char_count,
        home_team=base.home_team,
        away_team=base.away_team,
        tier_badge=base.tier_badge,
        button_count=base.button_count,
        button_labels=base.button_labels,
        raw_response=base.raw_response,
        # V2 extras
        home_team_visible=_coerce_bool(data.get("home_team_visible", False)),
        away_team_visible=_coerce_bool(data.get("away_team_visible", False)),
        kickoff_visible=_coerce_bool(data.get("kickoff_visible", False)),
        league_visible=_coerce_bool(data.get("league_visible", False)),
        broadcast_visible=_coerce_bool(data.get("broadcast_visible", False)),
        odds_value_visible=_coerce_bool(data.get("odds_value_visible", False)),
        bookmaker_name_visible=_coerce_bool(data.get("bookmaker_name_visible", False)),
        sections_present=_coerce_list_str(data.get("sections_present")),
        tier_badge_v2=tier_badge,
        verdict_text_v2=verdict,
        supersport_logo_present=_coerce_bool(data.get("supersport_logo_present", False)),
        supersport_logo_colour=ss_colour,
    )


def ocr_card_v2(image_path: "Path | str") -> CardOCRV2:
    """Run Claude vision with OCR_PROMPT_V2. Returns CardOCRV2."""
    import anthropic  # type: ignore[import-not-found]
    from typing import Any, cast

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"OCR image not found: {path}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — V2 OCR cannot run")

    media_type, b64 = _encode_image(path)
    client = anthropic.Anthropic(api_key=api_key)

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {"type": "text", "text": OCR_PROMPT_V2},
            ],
        }
    ]
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=cast(Any, messages),
    )

    text_parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)
    raw = "".join(text_parts).strip()
    if not raw:
        raise RuntimeError("V2 OCR response had no text content")

    return _parse_v2(raw)


def run_ocr(image_path: "Path | str") -> OCRResult:
    """Run OCR on an image, selecting V1 or V2 based on config.USE_OCR_V2.

    Returns CardOCRV2 when USE_OCR_V2=True, CardOCR otherwise.
    Falls back to V1 if V2 raises an exception.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set — returning stub OCR result")
        return CardOCR(
            verdict_text="[OCR SKIPPED — no API key]",
            verdict_char_count=0,
            home_team="",
            away_team="",
            tier_badge=None,
            button_count=0,
        )

    if USE_OCR_V2:
        try:
            return ocr_card_v2(path)
        except Exception as exc:
            log.warning("V2 OCR failed (%s), falling back to V1", exc)

    # V1 fallback
    from tests.qa.vision_ocr import ocr_card
    return ocr_card(path)
