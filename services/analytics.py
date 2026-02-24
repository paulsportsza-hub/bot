"""PostHog analytics — event tracking for MzansiEdge."""

from __future__ import annotations

import logging

import posthog

import config

log = logging.getLogger("mzansiedge.analytics")

# Configure PostHog (v7+ uses api_key, not project_api_key)
posthog.api_key = config.POSTHOG_API_KEY
posthog.project_api_key = config.POSTHOG_API_KEY  # backward compat
posthog.host = config.POSTHOG_HOST

# Disable in test / missing key scenarios
if not config.POSTHOG_API_KEY:
    posthog.disabled = True
    log.warning("PostHog disabled — POSTHOG_API_KEY not set")


def track(user_id: int | str, event: str, properties: dict | None = None) -> None:
    """Track an event in PostHog. Silently ignores errors."""
    try:
        posthog.capture(event, distinct_id=str(user_id), properties=properties or {})
    except Exception as exc:
        log.warning("PostHog tracking error: %s", exc)
