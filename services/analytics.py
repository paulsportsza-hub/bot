"""PostHog analytics wrapper for MzansiEdge event tracking."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("mzansiedge.analytics")

try:
    import posthog
    _POSTHOG_KEY = os.environ.get("POSTHOG_API_KEY", "")
    _POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
    if _POSTHOG_KEY:
        posthog.api_key = _POSTHOG_KEY
        posthog.host = _POSTHOG_HOST
        _enabled = True
    else:
        _enabled = False
except ImportError:
    _enabled = False


def track(user_id: int, event: str, properties: dict | None = None) -> None:
    """Track an event in PostHog. No-op if PostHog is not configured."""
    if not _enabled:
        return
    try:
        posthog.capture(event, distinct_id=str(user_id), properties=properties or {})
    except Exception as exc:
        log.debug("PostHog track failed: %s", exc)
