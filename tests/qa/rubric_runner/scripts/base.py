"""Shared Telethon helpers for persona scripts.

BUILD-QA-RUBRIC-RUNNER-01 — Phase B

PersonaRunner provides a thin async wrapper around Telethon's UserClient:
  - send_cmd(): send text, await reply with timing
  - tap_button(): click inline button by partial label match
  - download_photo(): save photo message to disk
  - wait_reply(): await next bot reply with timeout

All methods record response times for J3 scoring.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Presence flag — actual classes imported locally in methods
try:
    import telethon as _telethon_check  # type: ignore[import]
    del _telethon_check
    _TELETHON_AVAILABLE = True
except ImportError:
    _TELETHON_AVAILABLE = False


@dataclass
class Reply:
    """A single captured bot reply."""

    text: str
    has_photo: bool = False
    photo_path: str = ""
    buttons: list[list[str]] = field(default_factory=list)   # [[label, ...], ...]
    response_time_s: float = 0.0
    raw: Any = None   # raw Telethon Message object


class PersonaRunner:
    """Async Telethon wrapper for one persona script run.

    Usage::

        async with PersonaRunner(persona_id="P1") as runner:
            reply = await runner.send_cmd("/qa reset")
            reply = await runner.send_cmd("/start")
            reply = await runner.tap_button(reply, "Soccer")

    All captured replies are stored in ``self.replies`` for scoring.
    """

    def __init__(
        self,
        persona_id: str,
        *,
        session_path: str = "data/telethon_qa_session.string",
        bot_username: str = "mzansiedge_bot",
        api_id: int | None = None,
        api_hash: str | None = None,
        chat_id: int | None = None,
        screenshot_dir: str = "/home/paulsportsza/reports/rubric_runner/screenshots",
        default_timeout: int = 15,
        picks_timeout: int = 30,
    ) -> None:
        if not _TELETHON_AVAILABLE:
            raise RuntimeError("telethon is not installed — cannot run PersonaRunner")

        self.persona_id = persona_id
        self.bot_username = bot_username
        self.screenshot_dir = Path(screenshot_dir)
        self.default_timeout = default_timeout
        self.picks_timeout = picks_timeout

        # Credentials — env vars take priority over constructor args
        self._api_id = api_id or int(os.environ.get("TELEGRAM_API_ID", "0"))
        self._api_hash = api_hash or os.environ.get("TELEGRAM_API_HASH", "")
        self._chat_id = chat_id or int(os.environ.get("TELEGRAM_E2E_TEST_CHAT_ID", "0"))

        # Read session string from file
        sp = Path(session_path)
        if not sp.is_absolute():
            sp = Path("/home/paulsportsza/bot") / sp
        self._session_string = sp.read_text().strip() if sp.exists() else ""

        self.client: Any = None  # TelegramClient | None at runtime
        self._bot_entity: Any = None  # resolved bot entity
        self.replies: list[Reply] = []
        self._reply_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._edit_queue: asyncio.Queue[Any] = asyncio.Queue()

    async def __aenter__(self) -> "PersonaRunner":
        from telethon import TelegramClient as _TC  # type: ignore[import]
        from telethon.sessions import StringSession  # type: ignore[import]

        self.client = _TC(
            StringSession(self._session_string),
            self._api_id,
            self._api_hash,
        )
        await self.client.start()

        # Resolve bot entity by username — more reliable than raw chat_id
        self._bot_entity = await self.client.get_entity(self.bot_username)

        # Register event handlers that feed bot messages/edits into their queues
        from telethon import events as _events  # type: ignore[import]
        @self.client.on(_events.NewMessage(from_users=self.bot_username))
        async def _msg_handler(event: Any) -> None:  # noqa: F841
            await self._reply_queue.put(event.message)

        @self.client.on(_events.MessageEdited(from_users=self.bot_username))
        async def _edit_handler(event: Any) -> None:  # noqa: F841
            await self._edit_queue.put(event.message)

        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        log.info("PersonaRunner[%s] connected", self.persona_id)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self.client:
            await self.client.disconnect()
        log.info("PersonaRunner[%s] disconnected", self.persona_id)

    # ── Core helpers ─────────────────────────────────────────────────────────

    async def send_cmd(
        self,
        text: str,
        timeout: int | None = None,
        surface_id: str = "S1",
    ) -> Reply:
        """Send a text command and wait for the next bot reply.

        Returns a Reply with timing recorded.
        """
        if self.client is None:
            raise RuntimeError("PersonaRunner not started — use as async context manager")

        _timeout = timeout or self.default_timeout
        t0 = time.monotonic()

        await self.client.send_message(self._bot_entity, text)
        reply = await self.wait_reply(timeout=_timeout)
        reply.response_time_s = time.monotonic() - t0

        self.replies.append(reply)
        log.debug(
            "PersonaRunner[%s] send_cmd %r → reply in %.2fs (surface=%s)",
            self.persona_id, text, reply.response_time_s, surface_id,
        )
        return reply

    async def tap_button(
        self,
        msg_or_reply: Any,
        label: str,
        timeout: int | None = None,
    ) -> Reply:
        """Click an inline button that contains `label` (case-insensitive partial match).

        Args:
            msg_or_reply: Reply object or raw Telethon Message.
            label: Substring to match against button labels (case-insensitive).
            timeout: Seconds to wait for reply.

        Returns:
            Reply from the bot after the button click.
        """
        if self.client is None:
            raise RuntimeError("PersonaRunner not started")

        raw_msg = msg_or_reply.raw if isinstance(msg_or_reply, Reply) else msg_or_reply
        if raw_msg is None:
            raise ValueError("Cannot tap button — message has no raw object")

        t0 = time.monotonic()
        await raw_msg.click(filter=lambda b: label.lower() in b.text.lower())
        _timeout = timeout or self.default_timeout
        reply = await self.wait_reply(timeout=_timeout)
        reply.response_time_s = time.monotonic() - t0
        self.replies.append(reply)
        return reply

    async def download_photo(
        self,
        msg_or_reply: Any,
        filename: str | None = None,
    ) -> str:
        """Download photo from a message to screenshot_dir.

        Returns the absolute path to the downloaded file.
        """
        if self.client is None:
            raise RuntimeError("PersonaRunner not started")

        raw_msg = msg_or_reply.raw if isinstance(msg_or_reply, Reply) else msg_or_reply
        if raw_msg is None or not raw_msg.photo:
            return ""

        ts = int(time.time())
        name = filename or f"{self.persona_id}_photo_{ts}.jpg"
        dest = self.screenshot_dir / name

        await self.client.download_media(raw_msg.photo, str(dest))
        log.debug("PersonaRunner[%s] photo downloaded to %s", self.persona_id, dest)
        return str(dest)

    async def wait_reply(self, timeout: int | None = None) -> Reply:
        """Wait for the next bot reply from the queue.

        Collects ALL messages the bot sends within `timeout` seconds after
        the first one arrives (for multi-message responses).  Returns a merged
        Reply where text is joined by newlines.
        """
        _timeout = timeout or self.default_timeout

        # Wait for first message
        try:
            first: Any = await asyncio.wait_for(self._reply_queue.get(), timeout=_timeout)
        except asyncio.TimeoutError:
            log.warning("PersonaRunner[%s] timeout waiting for bot reply (%.0fs)", self.persona_id, _timeout)
            return Reply(text="[TIMEOUT]")

        messages: list[Any] = [first]

        # Grace window: collect additional NewMessages AND coalesce MessageEdited for the same
        # message_id within 3 seconds. The bot sends a "Loading..." NewMessage then edits it
        # to the final content; we discard the loading text and use the edited text instead.
        _GRACE_NEW = 2.0    # multi-message collection window
        _GRACE_EDIT = 3.0   # MessageEdited coalescing window
        deadline = time.monotonic() + max(_GRACE_NEW, _GRACE_EDIT)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            new_task = asyncio.ensure_future(self._reply_queue.get())
            edit_task = asyncio.ensure_future(self._edit_queue.get())

            done, pending = await asyncio.wait(
                {new_task, edit_task},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            if not done:
                break

            for t in done:
                try:
                    msg = t.result()
                except Exception:
                    continue
                if t is edit_task:
                    if msg.id == messages[0].id:
                        # MessageEdited for the first (loading) message — replace with final text
                        messages[0] = msg
                    # else: stale edit for a different message — discard
                else:
                    messages.append(msg)

        # Build merged Reply
        texts = []
        has_photo = False
        buttons: list[list[str]] = []
        last_raw = messages[-1]

        for m in messages:
            if m.text:
                texts.append(m.text)
            if m.photo:
                has_photo = True
            # Extract inline button labels
            if m.buttons:
                for row in m.buttons:
                    row_labels = [b.text for b in row]
                    buttons.append(row_labels)

        return Reply(
            text="\n".join(texts),
            has_photo=has_photo,
            buttons=buttons,
            raw=last_raw,
        )

    # ── Screenshot helpers ───────────────────────────────────────────────────

    def screenshot_path(self, surface_id: str) -> str:
        """Return a timestamped screenshot path for a surface."""
        ts = int(time.time())
        name = f"{self.persona_id}_{surface_id}_{ts}.png"
        return str(self.screenshot_dir / name)
