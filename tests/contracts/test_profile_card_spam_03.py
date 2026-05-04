"""FIX-PROFILE-CARD-SPAM-03 — third-layer regression guard.

Adds two more layers of defence on top of FIX-PROFILE-CARD-SPAM-01 (handler
guards) and FIX-PROFILE-CARD-SPAM-02 (the send_card_or_fallback early
return) so a profile card can never reach a non-DM chat:

  Layer 1 — render-level absolute ban
    card_renderer.render_card_sync(template_name="profile_home.html",
                                   chat_id_hint=<= 0)
    raises RuntimeError before any browser work / bytes are produced.

  Layer 2 — Telegram-API-layer guard
    bot._install_send_photo_dm_guard wraps Bot.send_photo and
    Bot.send_document. If the active card_send_context template is
    "profile_home.html" and chat_id <= 0, the wrapper short-circuits
    to None and emits an EdgeOps warning.

Source-level + behaviour tests for both layers. Also tests that the
contextvar in card_sender.py is set + reset around the send.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT_DIR))


# ── AC-1: source-level markers ───────────────────────────────────────────────

class TestSourceMarkers:
    def test_render_layer_marker_in_card_renderer(self):
        src = (BOT_DIR / "card_renderer.py").read_text(encoding="utf-8")
        assert "FIX-PROFILE-CARD-SPAM-03" in src, (
            "card_renderer.py must contain FIX-PROFILE-CARD-SPAM-03 guard marker"
        )

    def test_render_layer_signature_takes_chat_id_hint(self):
        src = (BOT_DIR / "card_renderer.py").read_text(encoding="utf-8")
        assert "chat_id_hint" in src, (
            "render_card_sync must accept chat_id_hint parameter"
        )

    def test_api_layer_marker_in_bot(self):
        src = (BOT_DIR / "bot.py").read_text(encoding="utf-8")
        assert "_install_send_photo_dm_guard" in src, (
            "bot.py must define _install_send_photo_dm_guard"
        )
        assert "FIX-PROFILE-CARD-SPAM-03" in src, (
            "bot.py must reference FIX-PROFILE-CARD-SPAM-03"
        )

    def test_api_layer_installer_called_in_post_init(self):
        src = (BOT_DIR / "bot.py").read_text(encoding="utf-8")
        post_init_idx = src.find("async def _post_init(")
        assert post_init_idx != -1, "bot.py must define _post_init"
        post_init_block = src[post_init_idx: post_init_idx + 3000]
        assert "_install_send_photo_dm_guard" in post_init_block, (
            "_post_init must call _install_send_photo_dm_guard"
        )

    def test_card_sender_uses_active_template_ctx(self):
        src = (BOT_DIR / "card_sender.py").read_text(encoding="utf-8")
        assert "card_send_context" in src, (
            "card_sender.py must import from card_send_context"
        )
        assert "_set_active_template" in src or "set_active_template" in src, (
            "card_sender.py must call set_active_template"
        )
        assert "_reset_active_template" in src or "reset_active_template" in src, (
            "card_sender.py must call reset_active_template"
        )

    def test_card_send_context_module_exists(self):
        ctx_path = BOT_DIR / "card_send_context.py"
        assert ctx_path.exists(), "card_send_context.py must exist"
        ctx_src = ctx_path.read_text(encoding="utf-8")
        assert "ContextVar" in ctx_src, (
            "card_send_context.py must use contextvars.ContextVar"
        )

    def test_card_sender_passes_chat_id_hint_to_renderer(self):
        src = (BOT_DIR / "card_sender.py").read_text(encoding="utf-8")
        assert "chat_id_hint=chat_id" in src, (
            "card_sender.py must pass chat_id_hint=chat_id to render_card_sync"
        )


# ── AC-2: render-layer ban ───────────────────────────────────────────────────

class TestRenderLayerBan:
    def test_render_card_sync_refuses_profile_for_negative_chat_id(self):
        from card_renderer import render_card_sync

        with pytest.raises(RuntimeError, match="FIX-PROFILE-CARD-SPAM-03"):
            render_card_sync(
                "profile_home.html",
                {},
                chat_id_hint=-1002987429381,
            )

    def test_render_card_sync_refuses_profile_for_zero_chat_id(self):
        from card_renderer import render_card_sync

        with pytest.raises(RuntimeError, match="FIX-PROFILE-CARD-SPAM-03"):
            render_card_sync(
                "profile_home.html",
                {},
                chat_id_hint=0,
            )

    def test_render_card_sync_allows_profile_for_dm_chat_id(self):
        # Positive chat_id must NOT trigger the FIX-PROFILE-CARD-SPAM-03 guard.
        # We force a sentinel exception immediately after the guard check by
        # patching _ensure_pool_started so we can assert the FIX-03 guard
        # specifically did NOT fire without engaging the real Playwright pool.
        from card_renderer import render_card_sync

        sentinel = RuntimeError("test-sentinel-pool-unavailable")
        with patch("card_renderer._ensure_pool_started", side_effect=sentinel):
            with pytest.raises(RuntimeError) as exc_info:
                render_card_sync(
                    "profile_home.html",
                    {},
                    chat_id_hint=123456,
                )
        assert "FIX-PROFILE-CARD-SPAM-03" not in str(exc_info.value), (
            "Guard must NOT fire for positive chat_id"
        )
        assert "test-sentinel-pool-unavailable" in str(exc_info.value)

    def test_render_card_sync_no_check_when_hint_omitted(self):
        # Backward-compat: legacy callers (QA gallery, pregen) that don't
        # pass chat_id_hint must keep working — the guard must NOT fire.
        from card_renderer import render_card_sync

        sentinel = RuntimeError("test-sentinel-pool-unavailable")
        with patch("card_renderer._ensure_pool_started", side_effect=sentinel):
            with pytest.raises(RuntimeError) as exc_info:
                render_card_sync("profile_home.html", {})
        assert "FIX-PROFILE-CARD-SPAM-03" not in str(exc_info.value)

    def test_render_card_sync_non_profile_template_unaffected(self):
        # Other templates must never trigger the FIX-PROFILE-CARD-SPAM-03
        # render-layer guard, even with chat_id_hint <= 0.
        from card_renderer import render_card_sync

        sentinel = RuntimeError("test-sentinel-pool-unavailable")
        with patch("card_renderer._ensure_pool_started", side_effect=sentinel):
            with pytest.raises(RuntimeError) as exc_info:
                render_card_sync(
                    "edge_picks.html",
                    {},
                    chat_id_hint=-1002987429381,
                )
        assert "FIX-PROFILE-CARD-SPAM-03" not in str(exc_info.value), (
            "Guard must be template-specific (only profile_home.html)"
        )


# ── AC-3: contextvar set/reset around send ───────────────────────────────────

class TestActiveTemplateContextvar:
    @pytest.mark.asyncio
    async def test_active_template_set_during_send(self):
        import card_sender as cs
        from card_send_context import get_active_template

        captured: dict = {"value": None}

        async def _spy_send_photo(*args, **kwargs):
            captured["value"] = get_active_template()
            return MagicMock(photo=[MagicMock(file_id="fid")])

        fake_bot = AsyncMock()
        fake_bot.send_photo = _spy_send_photo

        fake_fid = MagicMock()
        fake_fid.get.return_value = None

        with (
            patch.object(cs, "_build_cache_key", return_value="key_ctx"),
            patch("card_sender.asyncio.to_thread", new_callable=AsyncMock, return_value=b"\x89PNG"),
            patch.dict("sys.modules", {"file_id_cache": MagicMock(file_id_cache=fake_fid)}),
        ):
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=987654,
                template="profile_home.html",
                data={},
                text_fallback="",
                markup=None,
            )

        assert captured["value"] == "profile_home.html", (
            "Active template ContextVar must be set during the send_photo call"
        )

    @pytest.mark.asyncio
    async def test_active_template_reset_after_send(self):
        import card_sender as cs
        from card_send_context import get_active_template

        fake_bot = AsyncMock()
        fake_bot.send_photo.return_value = MagicMock(photo=[MagicMock(file_id="fid")])

        fake_fid = MagicMock()
        fake_fid.get.return_value = None

        with (
            patch.object(cs, "_build_cache_key", return_value="key_reset"),
            patch("card_sender.asyncio.to_thread", new_callable=AsyncMock, return_value=b"\x89PNG"),
            patch.dict("sys.modules", {"file_id_cache": MagicMock(file_id_cache=fake_fid)}),
        ):
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=987654,
                template="profile_home.html",
                data={},
                text_fallback="",
                markup=None,
            )

        assert get_active_template() == "", (
            "Active template ContextVar must reset to '' after the call"
        )

    @pytest.mark.asyncio
    async def test_active_template_reset_after_exception(self):
        import card_sender as cs
        from card_send_context import get_active_template

        fake_bot = AsyncMock()
        fake_bot.send_photo.side_effect = Exception("Telegram API down")

        fake_fid = MagicMock()
        fake_fid.get.return_value = None

        with (
            patch.object(cs, "_build_cache_key", return_value="key_exc"),
            patch("card_sender.asyncio.to_thread", new_callable=AsyncMock, return_value=b"\x89PNG"),
            patch.dict("sys.modules", {"file_id_cache": MagicMock(file_id_cache=fake_fid)}),
        ):
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=987654,
                template="profile_home.html",
                data={},
                text_fallback="",
                markup=None,
            )

        assert get_active_template() == "", (
            "Active template ContextVar must reset even when send_photo raises"
        )


# ── AC-4: API-layer guard via wrapped bot.send_photo ─────────────────────────

class TestApiLayerGuard:
    @pytest.mark.asyncio
    async def test_wrapped_send_photo_blocks_profile_for_group(self):
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock(return_value="ok")
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        token = set_active_template("profile_home.html")
        try:
            result = await fake_bot.send_photo(
                chat_id=-1002987429381,
                photo=b"\x89PNG",
            )
        finally:
            reset_active_template(token)

        assert result is None, (
            "Wrapped send_photo must return None when blocking profile to non-DM"
        )
        fake_bot.send_message.assert_called_once()
        edgeops_call = fake_bot.send_message.call_args
        assert edgeops_call.kwargs["chat_id"] == -1003877525865

    @pytest.mark.asyncio
    async def test_wrapped_send_photo_allows_profile_for_dm(self):
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock(return_value="ok")
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        token = set_active_template("profile_home.html")
        try:
            result = await fake_bot.send_photo(chat_id=123456, photo=b"\x89PNG")
        finally:
            reset_active_template(token)

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_wrapped_send_photo_allows_non_profile_template(self):
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock(return_value="ok")
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        token = set_active_template("edge_picks.html")
        try:
            # Group chat — must still go through (non-profile template)
            result = await fake_bot.send_photo(
                chat_id=-1002987429381,
                photo=b"\x89PNG",
            )
        finally:
            reset_active_template(token)

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_wrapped_send_photo_allows_when_no_active_template(self):
        from bot import _install_send_photo_dm_guard

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock(return_value="ok")
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        # No contextvar set → no profile send in flight → pass-through.
        result = await fake_bot.send_photo(
            chat_id=-1002987429381,
            photo=b"\x89PNG",
        )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_install_is_idempotent(self):
        from bot import _install_send_photo_dm_guard

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock()
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)
        first_send_photo = fake_bot.send_photo
        _install_send_photo_dm_guard(fake_bot)  # second call — must no-op
        second_send_photo = fake_bot.send_photo
        assert first_send_photo is second_send_photo, (
            "Repeated install must NOT replace the already-installed guard"
        )

    @pytest.mark.asyncio
    async def test_wrapped_send_photo_blocks_profile_for_string_channel(self):
        """A profile send to ``chat_id="@channel"`` must be refused.

        Telegram's Bot API accepts string usernames for public channels.
        The DM-only invariant fails closed: anything that is not a positive
        int is blocked.
        """
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock(return_value="ok")
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        token = set_active_template("profile_home.html")
        try:
            result = await fake_bot.send_photo(
                chat_id="@public_channel",
                photo=b"\x89PNG",
            )
        finally:
            reset_active_template(token)

        assert result is None, (
            "Wrapped send_photo must refuse string @channel chat_ids when a"
            " profile_home send is active (Codex P2: fail-closed for non-int"
            " destinations)"
        )
        fake_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrapped_send_photo_blocks_profile_for_zero_chat_id(self):
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock(return_value="ok")
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        token = set_active_template("profile_home.html")
        try:
            result = await fake_bot.send_photo(chat_id=0, photo=b"\x89PNG")
        finally:
            reset_active_template(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_wrapped_send_photo_blocks_profile_for_bool_chat_id(self):
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock(return_value="ok")
        fake_bot.send_document = AsyncMock()
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        # `True` is technically `int(1) > 0` but is conceptually not a chat_id.
        token = set_active_template("profile_home.html")
        try:
            result = await fake_bot.send_photo(chat_id=True, photo=b"\x89PNG")
        finally:
            reset_active_template(token)

        assert result is None, (
            "bool chat_id must NOT be treated as a valid DM chat_id"
        )

    @pytest.mark.asyncio
    async def test_wrapped_send_document_blocks_profile_for_group(self):
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        fake_bot = MagicMock()
        fake_bot.send_photo = AsyncMock()
        fake_bot.send_document = AsyncMock(return_value="ok")
        fake_bot.send_message = AsyncMock()

        _install_send_photo_dm_guard(fake_bot)

        token = set_active_template("profile_home.html")
        try:
            result = await fake_bot.send_document(
                chat_id=-1002987429381,
                document=b"PDF",
            )
        finally:
            reset_active_template(token)

        assert result is None


# ── AC-5: class-level fallback path for __slots__-protected classes ──────────

class TestSlotsFallback:
    """Verifies the install function falls back to class-level patching when
    the bot type uses __slots__ and refuses instance-level attribute assignment
    — the production case for PTB ExtBot/Bot.
    """

    @pytest.mark.asyncio
    async def test_slots_class_falls_back_to_class_level_patch(self):
        from bot import _install_send_photo_dm_guard
        from card_send_context import set_active_template, reset_active_template

        # A minimal class with __slots__ that mirrors the PTB Bot pattern:
        # methods are defined on the class, instance attribute assignment is
        # blocked because no slot is declared for the method name.
        class _SlotsBot:
            __slots__ = ()

            async def send_photo(self, *args, **kwargs):
                return "ORIGINAL_PHOTO"

            async def send_document(self, *args, **kwargs):
                return "ORIGINAL_DOC"

            async def send_message(self, *args, **kwargs):
                return "ORIGINAL_MSG"

        bot_inst = _SlotsBot()
        _install_send_photo_dm_guard(bot_inst)

        # The class itself should now carry the sentinel and the wrapped
        # methods — instance-level assignment is impossible due to __slots__.
        assert getattr(_SlotsBot, "_fix_profile_card_spam_03_guard_installed", None) is True
        assert _SlotsBot.send_photo.__name__ == "_guarded"
        assert _SlotsBot.send_document.__name__ == "_guarded"

        # Profile + non-DM → blocked
        token = set_active_template("profile_home.html")
        try:
            result = await bot_inst.send_photo(chat_id=-1002987429381, photo=b"PNG")
        finally:
            reset_active_template(token)
        assert result is None, (
            "Class-level wrapped send_photo must return None when blocking"
            " profile to non-DM"
        )

        # Profile + DM → allowed
        token = set_active_template("profile_home.html")
        try:
            result = await bot_inst.send_photo(chat_id=123456, photo=b"PNG")
        finally:
            reset_active_template(token)
        assert result == "ORIGINAL_PHOTO"

        # send_document → also wrapped
        token = set_active_template("profile_home.html")
        try:
            result = await bot_inst.send_document(
                chat_id=-1002987429381, document=b"PDF",
            )
        finally:
            reset_active_template(token)
        assert result is None

        # Cleanup: remove class-level patch so it doesn't leak across tests
        del _SlotsBot.send_photo
        del _SlotsBot.send_document
        del _SlotsBot._fix_profile_card_spam_03_guard_installed

    @pytest.mark.asyncio
    async def test_slots_class_install_is_idempotent(self):
        from bot import _install_send_photo_dm_guard

        class _SlotsBot2:
            __slots__ = ()

            async def send_photo(self, *args, **kwargs):
                return "P"

            async def send_document(self, *args, **kwargs):
                return "D"

            async def send_message(self, *args, **kwargs):
                return "M"

        bot_inst = _SlotsBot2()
        _install_send_photo_dm_guard(bot_inst)
        first_send_photo = _SlotsBot2.send_photo
        _install_send_photo_dm_guard(bot_inst)
        second_send_photo = _SlotsBot2.send_photo
        assert first_send_photo is second_send_photo, (
            "Repeated class-level install must NOT replace the existing wrapper"
        )

        # Cleanup
        del _SlotsBot2.send_photo
        del _SlotsBot2.send_document
        del _SlotsBot2._fix_profile_card_spam_03_guard_installed

    def test_install_handler_logs_fallback_reason(self):
        """The install function must announce the slots-fallback path so
        operators see it in journalctl when the bot starts.
        """
        src = (BOT_DIR / "bot.py").read_text(encoding="utf-8")
        # The install function must mention either "instance assignment refused"
        # or "class-level guard installed" so operators can confirm the path.
        assert "instance assignment refused" in src, (
            "install function must log when instance-level fails (slots case)"
        )
        assert "class-level guard installed" in src, (
            "install function must log when falling back to class-level"
        )
