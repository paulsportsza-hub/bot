"""Lightweight Sentry instrumentation helpers for handler latency diagnostics.

FIX-BOT-START-LATENCY-DIAGNOSTICS-01: phase-by-phase timing emit + Sentry
breadcrumbs for slow-handler diagnosis. All helpers are NO-OP when sentry_sdk is
not installed and never raise — instrumentation MUST NOT crash the handler.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

try:
    import sentry_sdk as _sentry
except ImportError:
    _sentry = None


SLOW_HANDLER_THRESHOLD_MS = 5000


def sentry_breadcrumb(category: str, message: str, **data) -> None:
    """Add a Sentry breadcrumb. Never raises."""
    try:
        if _sentry is None:
            return
        _sentry.add_breadcrumb(category=category, message=message, data=data, level="info")
    except Exception:
        pass


def sentry_capture(
    message: str,
    *,
    tags: dict | None = None,
    extra: dict | None = None,
) -> None:
    """Capture a Sentry message with optional tags + extra context.

    Always emitted at level=warning (instrumentation alerts, not errors).
    Never raises.
    """
    try:
        if _sentry is None:
            return
        with _sentry.push_scope() as scope:
            for k, v in (tags or {}).items():
                if v is not None:
                    scope.set_tag(k, str(v))
            for k, v in (extra or {}).items():
                scope.set_extra(k, v)
            _sentry.capture_message(message, level="warning")
    except Exception:
        pass


@contextmanager
def phase_timer(phases: dict, name: str) -> Iterator[None]:
    """Time a block and store elapsed_ms in `phases[name]`.

    Always populates phases[name], even on exception. Never raises (failures
    inside the timing bookkeeping itself are swallowed so instrumentation can
    not interrupt the handler body).
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        try:
            phases[name] = round((time.monotonic() - t0) * 1000, 1)
        except Exception:
            pass
