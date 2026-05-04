"""FIX-PROFILE-CARD-SPAM-03: shared context for the active card-send.

A tiny module exposing a ``ContextVar`` that records the template name being
sent through ``card_sender.send_card_or_fallback``. The Telegram-API-level
guard installed by ``bot._install_send_photo_dm_guard`` reads it to decide
whether an outgoing ``Bot.send_photo`` carries a profile card.

Defined in its own module to break the dependency cycle that would otherwise
arise between ``card_sender`` and ``bot``.
"""
from __future__ import annotations

import contextvars

_active_template_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "fix_profile_card_spam_03_active_template",
    default="",
)


def set_active_template(template: str):
    """Set the active template name and return the reset token."""
    return _active_template_ctx.set(template)


def reset_active_template(token) -> None:
    """Reset the active template using the token returned by set_active_template."""
    try:
        _active_template_ctx.reset(token)
    except (ValueError, LookupError):
        pass


def get_active_template() -> str:
    """Return the active template name, or '' when none is set."""
    return _active_template_ctx.get()
