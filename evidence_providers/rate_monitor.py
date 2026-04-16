"""Rate limit tracker for sport evidence API providers.

Tracks daily API call counts per provider and sends EdgeOps Telegram alerts
when usage crosses 70%, 90%, and 100% thresholds.

Singleton instance ``rate_monitor`` is created in evidence_providers/__init__.py.
All provider files call ``rate_monitor.record_call(provider_name)`` after each
live API call (not cache hits).

Standing Order #20: EdgeOps alerts ONLY (chat_id -1003877525865).
NEVER send rate alerts to @MzansiEdgeAlerts (public channel).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("mzansi.rate_monitor")

_EDGEOPS_CHAT_ID = -1003877525865
_BOT_TOKEN = os.getenv("BOT_TOKEN", "")
_TELEGRAM_API = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"

# Checked in descending order — one alert fires per threshold crossing.
_THRESHOLDS = [100, 90, 70]

_PROVIDER_DISPLAY: dict[str, str] = {
    "cricketdata": "CricketData.org",
    "api_sports": "API-Sports",
    "boxing_data": "Boxing-Data",
}

_PROVIDER_ACTION: dict[str, str] = {
    "cricketdata": "Paul may need to upgrade CricketData.org plan (free tier: 100/day)",
    "api_sports": "Paul may need to upgrade API-Sports plan (free tier: 100/day, $15/mo)",
    "boxing_data": "Paul may need to upgrade Boxing-Data plan (free tier: 100/day)",
}

_LEVEL_FOR_THRESHOLD: dict[int, str] = {
    70: "ALERT",
    90: "WARNING",
    100: "CRITICAL",
}


def _utc_today() -> str:
    """Return today's date as ISO string in UTC."""
    return datetime.now(timezone.utc).date().isoformat()


class RateMonitor:
    """Tracks API call counts per provider, fires EdgeOps alerts at thresholds."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._limits: dict[str, int] = {}
        self._last_reset: dict[str, str] = {}    # provider -> YYYY-MM-DD (UTC)
        self._alerted: dict[str, set[int]] = {}  # provider -> set of threshold %s already fired
        self._shared_with: dict[str, list[str]] = {}  # display labels for shared pools

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_provider(
        self,
        name: str,
        daily_limit: int,
        shared_with: list[str] | None = None,
    ) -> None:
        """Register a provider with its daily limit.

        shared_with lists the service names that draw from the same pool
        (e.g. rugby + mma both use api_sports). Used for alert display only.
        """
        self._counters[name] = 0
        self._limits[name] = daily_limit
        self._last_reset[name] = _utc_today()
        self._alerted[name] = set()
        self._shared_with[name] = list(shared_with) if shared_with else []

    def record_call(self, provider_name: str) -> None:
        """Increment counter. Check thresholds. Fire alert if a threshold is crossed.

        Must be fast — no blocking I/O. Alert sending is fire-and-forget.
        When the daily limit is hit, providers should still attempt the call
        (the API may soft-limit rather than hard-block). This method only monitors.
        """
        if provider_name not in self._counters:
            log.debug(
                "rate_monitor: unregistered provider %r — call not counted", provider_name
            )
            return
        self._check_reset(provider_name)
        self._counters[provider_name] += 1
        self._maybe_alert(provider_name)

    def get_usage(self, provider_name: str) -> dict[str, Any]:
        """Return {calls_used, daily_limit, pct_used, shared_pool_names}."""
        if provider_name not in self._counters:
            return {}
        self._check_reset(provider_name)
        calls = self._counters[provider_name]
        limit = self._limits[provider_name]
        pct = round((calls / limit) * 100, 1) if limit else 0.0
        return {
            "calls_used": calls,
            "daily_limit": limit,
            "pct_used": pct,
            "shared_pool_names": list(self._shared_with.get(provider_name, [])),
        }

    def get_all_usage(self) -> dict[str, dict[str, Any]]:
        """Return usage for all providers. Used by daily health check."""
        return {name: self.get_usage(name) for name in self._counters}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_reset(self, provider_name: str) -> None:
        """Reset counter if a new UTC day has started."""
        today = _utc_today()
        if self._last_reset.get(provider_name) != today:
            self._counters[provider_name] = 0
            self._alerted[provider_name] = set()
            self._last_reset[provider_name] = today

    def _maybe_alert(self, provider_name: str) -> None:
        calls = self._counters[provider_name]
        limit = self._limits[provider_name]
        if not limit:
            return
        pct = (calls / limit) * 100

        for threshold in _THRESHOLDS:
            if pct >= threshold and threshold not in self._alerted[provider_name]:
                self._alerted[provider_name].add(threshold)
                level = _LEVEL_FOR_THRESHOLD[threshold]
                msg = self._format_alert(provider_name, calls, limit, pct, level)
                self._fire_and_forget(msg)
                break  # one alert per record_call — wait for next crossing

    def _display_name(self, provider_name: str) -> str:
        base = _PROVIDER_DISPLAY.get(provider_name, provider_name)
        shared = self._shared_with.get(provider_name, [])
        if shared:
            return f"{base} ({' + '.join(shared)} shared)"
        return base

    def _format_alert(
        self,
        provider_name: str,
        calls: int,
        limit: int,
        pct: float,
        level: str,
    ) -> str:
        display = self._display_name(provider_name)
        action = _PROVIDER_ACTION.get(provider_name, "Review API plan")
        emoji = "⛔" if level == "CRITICAL" else ("⚠️" if level == "WARNING" else "ℹ️")
        return (
            f"{emoji} API RATE ALERT\n"
            f"Provider: {display}\n"
            f"Usage: {calls}/{limit} ({pct:.0f}%)\n"
            f"Level: {level}\n"
            f"Action: {action}"
        )

    def _fire_and_forget(self, message: str) -> None:
        """Schedule alert as a background task when a loop is running."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send_edgeops_alert(message))
        except RuntimeError:
            # No running event loop (e.g. startup or test context) — log only.
            log.warning("rate_monitor alert (no loop): %s", message)

    async def _send_edgeops_alert(self, message: str) -> None:
        """Send alert to EdgeOps Telegram (chat_id -1003877525865).

        NEVER sends to @MzansiEdgeAlerts — Standing Order #20.
        """
        try:
            import aiohttp  # local import — rate_monitor has no hard dep on aiohttp

            payload = {
                "chat_id": _EDGEOPS_CHAT_ID,
                "text": message,
            }
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(_TELEGRAM_API, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning(
                            "rate_monitor alert failed HTTP %s: %s",
                            resp.status,
                            body[:200],
                        )
                    else:
                        log.info("rate_monitor alert sent: %s", message[:80])
        except Exception as exc:
            log.warning("rate_monitor alert send error: %s", exc)
