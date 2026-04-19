"""OpenRouter client — drop-in for anthropic.AsyncAnthropic / anthropic.Anthropic.

Uses the OpenRouter OpenAI-compatible API:
  POST https://openrouter.ai/api/v1/chat/completions

Provides AsyncOpenRouter and SyncOpenRouter with the same .messages.create()
interface as the Anthropic SDK so callers need no further changes.
Unsupported Anthropic params (tools, betas, etc.) are silently absorbed.

BUILD-SONNET-BURN-FIX-01 (2026-04-19) — protection layer:
  - Circuit breaker persisted to /tmp/openrouter_circuit.json (6h trip on 402)
  - Daily Sonnet cap via OPENROUTER_SONNET_DAILY_CAP env (default 1500)
  - Auto-fallback Sonnet → Haiku when exhausted / capped / circuit-open
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

# ── BUILD-SONNET-BURN-FIX-01: circuit breaker + daily cap ──────────────────

_HAIKU_FALLBACK_MODEL = "claude-haiku-4-5-20251001"

_CIRCUIT_STATE_PATH = "/tmp/openrouter_circuit.json"
_CIRCUIT_COOLDOWN_SEC = 6 * 60 * 60  # 6 hours

_DAILY_STATE_PATH = "/tmp/openrouter_daily.json"
_DAILY_CAP = int(os.environ.get("OPENROUTER_SONNET_DAILY_CAP", "1500"))


class OpenRouterExhaustedError(Exception):
    """Raised when Sonnet is exhausted (402, circuit open, or daily cap hit)."""


def _is_sonnet(model: str) -> bool:
    return model.startswith("claude-sonnet") or "sonnet" in model.lower()


def _load_circuit_state() -> dict[str, Any]:
    try:
        with open(_CIRCUIT_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_circuit_state(state: dict[str, Any]) -> None:
    try:
        with open(_CIRCUIT_STATE_PATH, "w") as f:
            json.dump(state, f)
    except OSError as e:
        log.warning("openrouter: circuit state save failed: %s", e)


def _circuit_open() -> bool:
    state = _load_circuit_state()
    tripped_at = state.get("tripped_at", 0)
    if not tripped_at:
        return False
    return (time.time() - tripped_at) < _CIRCUIT_COOLDOWN_SEC


def _trip_circuit(reason: str) -> None:
    _save_circuit_state({"tripped_at": time.time(), "reason": reason})
    log.warning("openrouter: circuit tripped (reason=%s) — Sonnet blocked for 6h", reason)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_daily_count() -> int:
    try:
        with open(_DAILY_STATE_PATH) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 0
    if state.get("date") != _today_utc():
        return 0
    return int(state.get("count", 0))


def _increment_daily_count() -> int:
    today = _today_utc()
    try:
        with open(_DAILY_STATE_PATH) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = {}
    if state.get("date") != today:
        state = {"date": today, "count": 0}
    state["count"] = int(state.get("count", 0)) + 1
    try:
        with open(_DAILY_STATE_PATH, "w") as f:
            json.dump(state, f)
    except OSError as e:
        log.warning("openrouter: daily counter save failed: %s", e)
    return state["count"]


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
        allow_haiku_fallback: bool = True,
        **kwargs: Any,  # absorbs tools, betas, etc.
    ) -> Message:
        effective_model = model
        if _is_sonnet(effective_model) and allow_haiku_fallback:
            if _circuit_open():
                log.warning(
                    "openrouter: Sonnet circuit open — downgrading to Haiku for this call"
                )
                effective_model = _HAIKU_FALLBACK_MODEL
            elif _load_daily_count() >= _DAILY_CAP:
                log.warning(
                    "openrouter: Sonnet daily cap (%s) hit — downgrading to Haiku for this call",
                    _DAILY_CAP,
                )
                effective_model = _HAIKU_FALLBACK_MODEL

        try:
            return await self._post(
                effective_model,
                messages,
                max_tokens=max_tokens,
                system=system,
                temperature=temperature,
                timeout=timeout,
            )
        except OpenRouterExhaustedError:
            if allow_haiku_fallback and _is_sonnet(effective_model):
                log.warning(
                    "openrouter: Sonnet exhausted — downgrading to Haiku for this call"
                )
                return await self._post(
                    _HAIKU_FALLBACK_MODEL,
                    messages,
                    max_tokens=max_tokens,
                    system=system,
                    temperature=temperature,
                    timeout=timeout,
                )
            raise

    async def _post(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        system: str | None,
        temperature: float | None,
        timeout: float,
    ) -> Message:
        import aiohttp

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
                if resp.status == 402:
                    _trip_circuit(f"402 on {model}")
                    raise OpenRouterExhaustedError(f"OpenRouter 402 on {model}")
                resp.raise_for_status()
                data = await resp.json()

        if _is_sonnet(model):
            _increment_daily_count()

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
        allow_haiku_fallback: bool = True,
        **kwargs: Any,
    ) -> Message:
        effective_model = model
        if _is_sonnet(effective_model) and allow_haiku_fallback:
            if _circuit_open():
                log.warning(
                    "openrouter: Sonnet circuit open — downgrading to Haiku for this call"
                )
                effective_model = _HAIKU_FALLBACK_MODEL
            elif _load_daily_count() >= _DAILY_CAP:
                log.warning(
                    "openrouter: Sonnet daily cap (%s) hit — downgrading to Haiku for this call",
                    _DAILY_CAP,
                )
                effective_model = _HAIKU_FALLBACK_MODEL

        try:
            return self._post(
                effective_model,
                messages,
                max_tokens=max_tokens,
                system=system,
                temperature=temperature,
                timeout=timeout,
            )
        except OpenRouterExhaustedError:
            if allow_haiku_fallback and _is_sonnet(effective_model):
                log.warning(
                    "openrouter: Sonnet exhausted — downgrading to Haiku for this call"
                )
                return self._post(
                    _HAIKU_FALLBACK_MODEL,
                    messages,
                    max_tokens=max_tokens,
                    system=system,
                    temperature=temperature,
                    timeout=timeout,
                )
            raise

    def _post(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        system: str | None,
        temperature: float | None,
        timeout: float,
    ) -> Message:
        import urllib.error as _urllib_err
        import urllib.request as _urllib_req

        body: dict[str, Any] = {
            "model": _or_model(model),
            "messages": _build_messages(system, messages),
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature

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
        try:
            with _urllib_req.urlopen(req, timeout=int(timeout)) as r:
                data = json.loads(r.read())
        except _urllib_err.HTTPError as e:
            if e.code == 402:
                _trip_circuit(f"402 on {model}")
                raise OpenRouterExhaustedError(f"OpenRouter 402 on {model}") from e
            raise

        if _is_sonnet(model):
            _increment_daily_count()

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
