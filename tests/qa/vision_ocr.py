"""Claude-vision OCR for delivered MzansiEdge card screenshots.

Thin wrapper around anthropic.Anthropic that reads a card PNG and returns a
structured `CardOCR` dataclass. Callable from both the Telethon QA harness
(inline) and future sub-agents.

Model is pinned in a single constant (`_MODEL`). Uses `ANTHROPIC_API_KEY` from
env — no custom auth, no refactor of the shared openrouter_client.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import anthropic  # type: ignore[import-not-found]

from tests.qa.ocr_prompt import ALLOWED_TIER_BADGES, OCR_PROMPT

log = logging.getLogger(__name__)

# Single source of truth for the model string. Paul's call: Opus 4.7 only.
# Opus 4.7 does not accept `temperature` — determinism comes from the prompt
# (explicit JSON shape, no branching). We omit the param rather than send 0.0.
_MODEL = "claude-opus-4-7"
_MAX_TOKENS = 1024


@dataclass
class CardOCR:
    """Structured read of a delivered card screenshot."""

    verdict_text: str
    verdict_char_count: int
    home_team: str
    away_team: str
    tier_badge: str | None
    button_count: int
    button_labels: list[str] = field(default_factory=list)
    raw_response: str = ""


def _sniff_media_type(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes. Returns None if unknown.

    Telegram screenshots sometimes land on disk with a `.png` extension but
    JPEG content. The Anthropic vision API rejects mismatched media types, so
    we identify by magic bytes rather than by file extension.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _encode_image(image_path: Path) -> tuple[str, str]:
    """Return (media_type, base64-encoded-bytes) for an image file.

    Sniffs magic bytes first (authoritative) and falls back to the extension
    only when the header is unrecognised.
    """
    data = image_path.read_bytes()
    sniffed = _sniff_media_type(data)
    if sniffed:
        mime = sniffed
    else:
        mime, _ = mimetypes.guess_type(str(image_path))
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            mime = "image/png"
    return mime, base64.standard_b64encode(data).decode("ascii")


def _extract_json_blob(raw: str) -> str:
    """Pull the first balanced {...} JSON object out of a response string.

    Claude occasionally wraps JSON in ``` fences even when told not to —
    strip fences first, then locate the outermost braces.
    """
    text = raw.strip()
    # Strip markdown code fence wrappers if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in OCR response: {raw[:200]!r}")
    return text[start : end + 1]


def _normalise_tier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped in ALLOWED_TIER_BADGES:
        return stripped
    return None


def _coerce_list_str(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
    return out


def _parse_card_ocr(raw: str) -> CardOCR:
    blob = _extract_json_blob(raw)
    data = json.loads(blob)

    verdict = str(data.get("verdict_text", "") or "")
    verdict = " ".join(verdict.split())  # collapse whitespace

    home = str(data.get("home_team", "") or "").strip()
    away = str(data.get("away_team", "") or "").strip()

    button_count_raw = data.get("button_count", 0)
    try:
        button_count = int(button_count_raw)
    except (TypeError, ValueError):
        button_count = 0

    return CardOCR(
        verdict_text=verdict,
        verdict_char_count=len(verdict),
        home_team=home,
        away_team=away,
        tier_badge=_normalise_tier(data.get("tier_badge")),
        button_count=button_count,
        button_labels=_coerce_list_str(data.get("button_labels")),
        raw_response=raw,
    )


def ocr_card(image_path: Path | str, *, model: str = _MODEL) -> CardOCR:
    """Run Claude vision on a card screenshot. Returns structured reading.

    Uses ANTHROPIC_API_KEY from env (already present on server for other uses).

    Raises:
        FileNotFoundError: if `image_path` does not exist.
        RuntimeError: if ANTHROPIC_API_KEY is missing or the API returns an
            empty text response.
        ValueError: if the response cannot be parsed as JSON.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"OCR image not found: {path}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — OCR cannot run")

    media_type, b64 = _encode_image(path)
    client = anthropic.Anthropic(api_key=api_key)

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                },
                {"type": "text", "text": OCR_PROMPT},
            ],
        }
    ]
    resp = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        messages=cast(Any, messages),
    )

    # Claude vision responses are a list of content blocks. Concatenate text.
    text_parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)
    raw = "".join(text_parts).strip()
    if not raw:
        raise RuntimeError("OCR response had no text content")

    try:
        return _parse_card_ocr(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        log.warning("ocr_card: JSON parse failed on response: %s", raw[:500])
        raise ValueError(f"Failed to parse OCR response: {exc}") from exc
