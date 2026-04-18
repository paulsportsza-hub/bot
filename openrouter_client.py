"""OpenRouter client — drop-in for anthropic.AsyncAnthropic / anthropic.Anthropic.

Uses the OpenRouter OpenAI-compatible API:
  POST https://openrouter.ai/api/v1/chat/completions

Provides AsyncOpenRouter and SyncOpenRouter with the same .messages.create()
interface as the Anthropic SDK so callers need no further changes.
Unsupported Anthropic params (tools, betas, etc.) are silently absorbed.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_OR_URL = "https://openrouter.ai/api/v1/chat/completions"
_OR_SITE = "https://mzansiedge.co.za"
_OR_TITLE = "MzansiEdge"

# Anthropic SDK model IDs → OpenRouter model IDs
_MODEL_MAP: dict[str, str] = {
    "claude-haiku-4-5-20251001": "anthropic/claude-haiku-4.5",
    "claude-sonnet-4-20250514": "anthropic/claude-sonnet-4.5",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
    "claude-opus-4-7": "anthropic/claude-opus-4.7",
    "claude-opus-4-6": "anthropic/claude-opus-4.6",
}


def _or_model(model: str) -> str:
    return _MODEL_MAP.get(model, model)


def _build_messages(
    system: str | None,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if system:
        result.append({"role": "system", "content": system})
    result.extend(messages)
    return result


# ── Response types mirroring the Anthropic SDK surface ───────────────────────

@dataclass
class ContentBlock:
    text: str
    type: str = "text"


@dataclass
class Message:
    content: list[ContentBlock] = field(default_factory=list)


# ── Async client ─────────────────────────────────────────────────────────────

class _AsyncMessages:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        system: str | None = None,
        temperature: float | None = None,
        timeout: float = 60.0,
        **kwargs: Any,  # absorbs tools, betas, etc.
    ) -> Message:
        import aiohttp  # already installed via scrapers

        body: dict[str, Any] = {
            "model": _or_model(model),
            "messages": _build_messages(system, messages),
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": _OR_SITE,
            "X-Title": _OR_TITLE,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                _OR_URL,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return Message(content=[ContentBlock(text=text)])


class AsyncOpenRouter:
    """Async OpenRouter client — mirrors anthropic.AsyncAnthropic."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        resolved = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.messages = _AsyncMessages(resolved)


# ── Sync client ──────────────────────────────────────────────────────────────

class _SyncMessages:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        system: str | None = None,
        temperature: float | None = None,
        timeout: float = 60.0,
        **kwargs: Any,
    ) -> Message:
        body: dict[str, Any] = {
            "model": _or_model(model),
            "messages": _build_messages(system, messages),
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature

        import urllib.request as _urllib_req

        payload = json.dumps(body).encode()
        req = _urllib_req.Request(
            _OR_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": _OR_SITE,
                "X-Title": _OR_TITLE,
            },
            method="POST",
        )
        with _urllib_req.urlopen(req, timeout=int(timeout)) as r:
            data = json.loads(r.read())

        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return Message(content=[ContentBlock(text=text)])


class SyncOpenRouter:
    """Sync OpenRouter client — mirrors anthropic.Anthropic."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        resolved = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.messages = _SyncMessages(resolved)


# Aliases for drop-in compatibility with anthropic SDK naming conventions
AsyncAnthropic = AsyncOpenRouter
Anthropic = SyncOpenRouter
