"""Unit tests for services/meta_capi.py (BUILD-CAPI-01)."""
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _make_response(status_code: int = 200, text: str = '{"events_received": 1}') -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ── fire_purchase_event: happy path ────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_purchase_event_sends_correct_payload():
    """Payload shape: Purchase event with ctwa_clid, hashed phone, hashed email."""
    user_row = {
        "ctwa_clid": "ABCDEF123456",
        "whatsapp_phone": "+27821234567",
        "email": "user@example.com",
        "fb_click_id": None,
    }

    with (
        patch("services.meta_capi.config") as mock_cfg,
        patch("services.meta_capi._lookup_user_data", return_value=user_row),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_cfg.META_PIXEL_ID = "2387744055035848"
        mock_cfg.META_CAPI_ACCESS_TOKEN = "EAAtest123"
        mock_cfg.DATABASE_PATH = None

        mock_resp = _make_response(200)
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        from services import meta_capi
        await meta_capi.fire_purchase_event(42, 69900, "founding_diamond")

        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args

        url = call_kwargs[0][0]
        assert "2387744055035848" in url

        params = call_kwargs[1]["params"]
        assert params["access_token"] == "EAAtest123"

        payload = call_kwargs[1]["json"]
        event = payload["data"][0]

        assert event["event_name"] == "Purchase"
        assert event["action_source"] == "system_generated"
        assert isinstance(event["event_time"], int)

        ud = event["user_data"]
        assert ud["ctwa_clid"] == "ABCDEF123456"
        assert ud["ph"] == [_sha256("+27821234567")]
        assert ud["em"] == [_sha256("user@example.com")]

        cd = event["custom_data"]
        assert cd["value"] == 699.0
        assert cd["currency"] == "ZAR"
        assert cd["content_name"] == "founding_diamond"


# ── fire_purchase_event: fallback to fb_click_id ──────────────────────────


@pytest.mark.asyncio
async def test_fire_purchase_event_falls_back_to_fb_click_id():
    """When ctwa_clid is NULL, falls back to users.fb_click_id."""
    user_row = {
        "ctwa_clid": None,
        "whatsapp_phone": None,
        "email": None,
        "fb_click_id": "FB_CLICK_99",
    }

    with (
        patch("services.meta_capi.config") as mock_cfg,
        patch("services.meta_capi._lookup_user_data", return_value=user_row),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_cfg.META_PIXEL_ID = "PIXELID"
        mock_cfg.META_CAPI_ACCESS_TOKEN = "TOKEN"
        mock_cfg.DATABASE_PATH = None

        mock_resp = _make_response(200)
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        from services import meta_capi
        await meta_capi.fire_purchase_event(7, 9900, "gold_monthly")

        payload = mock_http.post.call_args[1]["json"]
        ud = payload["data"][0]["user_data"]
        assert ud["ctwa_clid"] == "FB_CLICK_99"
        assert "ph" not in ud
        assert "em" not in ud


# ── fire_purchase_event: no ctwa_clid, no fb_click_id ─────────────────────


@pytest.mark.asyncio
async def test_fire_purchase_event_no_attribution_signal():
    """Fires even when no ctwa_clid or fb_click_id — user_data is empty."""
    user_row = {"ctwa_clid": None, "whatsapp_phone": None, "email": None, "fb_click_id": None}

    with (
        patch("services.meta_capi.config") as mock_cfg,
        patch("services.meta_capi._lookup_user_data", return_value=user_row),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_cfg.META_PIXEL_ID = "PIXEL"
        mock_cfg.META_CAPI_ACCESS_TOKEN = "TOKEN"
        mock_cfg.DATABASE_PATH = None

        mock_resp = _make_response(200)
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        from services import meta_capi
        await meta_capi.fire_purchase_event(99, 19900, "diamond_monthly")

        mock_http.post.assert_called_once()
        payload = mock_http.post.call_args[1]["json"]
        ud = payload["data"][0]["user_data"]
        assert ud == {}


# ── fire_purchase_event: not configured ───────────────────────────────────


@pytest.mark.asyncio
async def test_fire_purchase_event_skips_when_not_configured():
    """Returns immediately without HTTP call when CAPI env vars are empty."""
    with (
        patch("services.meta_capi.config") as mock_cfg,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_cfg.META_PIXEL_ID = ""
        mock_cfg.META_CAPI_ACCESS_TOKEN = ""
        mock_cfg.DATABASE_PATH = None

        from services import meta_capi
        await meta_capi.fire_purchase_event(1, 69900, "founding_diamond")

        mock_client_cls.assert_not_called()


# ── fire_purchase_event: silent failure on exception ──────────────────────


@pytest.mark.asyncio
async def test_fire_purchase_event_silent_failure_on_exception():
    """Exceptions are swallowed — never raises, never blocks payment flow."""
    with (
        patch("services.meta_capi.config") as mock_cfg,
        patch("services.meta_capi._lookup_user_data", side_effect=RuntimeError("db boom")),
        patch("services.meta_capi._sentry") as mock_sentry,
    ):
        mock_cfg.META_PIXEL_ID = "PIXEL"
        mock_cfg.META_CAPI_ACCESS_TOKEN = "TOKEN"
        mock_cfg.DATABASE_PATH = None

        from services import meta_capi

        # Must NOT raise
        await meta_capi.fire_purchase_event(5, 9900, "gold_monthly")

        mock_sentry.capture_exception.assert_called_once()


@pytest.mark.asyncio
async def test_fire_purchase_event_silent_failure_on_http_exception():
    """HTTP failures are swallowed — Sentry logged, no raise."""
    user_row = {"ctwa_clid": "CLICK", "whatsapp_phone": None, "email": None, "fb_click_id": None}

    with (
        patch("services.meta_capi.config") as mock_cfg,
        patch("services.meta_capi._lookup_user_data", return_value=user_row),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("services.meta_capi._sentry") as mock_sentry,
    ):
        mock_cfg.META_PIXEL_ID = "PIXEL"
        mock_cfg.META_CAPI_ACCESS_TOKEN = "TOKEN"
        mock_cfg.DATABASE_PATH = None

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        from services import meta_capi

        await meta_capi.fire_purchase_event(3, 9900, "gold_monthly")

        mock_sentry.capture_exception.assert_called_once()


# ── amount_cents conversion ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_purchase_event_amount_cents_conversion():
    """amount_cents=9900 → value=99.0 in custom_data."""
    user_row = {"ctwa_clid": None, "whatsapp_phone": None, "email": None, "fb_click_id": None}

    with (
        patch("services.meta_capi.config") as mock_cfg,
        patch("services.meta_capi._lookup_user_data", return_value=user_row),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_cfg.META_PIXEL_ID = "P"
        mock_cfg.META_CAPI_ACCESS_TOKEN = "T"
        mock_cfg.DATABASE_PATH = None

        mock_resp = _make_response(200)
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        from services import meta_capi
        await meta_capi.fire_purchase_event(1, 9900, "gold_monthly")

        cd = mock_http.post.call_args[1]["json"]["data"][0]["custom_data"]
        assert cd["value"] == 99.0
        assert cd["currency"] == "ZAR"
