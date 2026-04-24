"""Unit tests for Stitch Express recurring subscriptions.

BUILD-STITCH-SUBSCRIPTION-01 (AC-11)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_service(mock_mode: bool = True):
    from services.stitch_service import StitchService
    svc = StitchService.__new__(StitchService)
    svc.client_id = "test_client_id"
    svc.client_secret = "test_secret"
    svc.webhook_secret = "whsec_test"
    svc._is_mock = lambda: mock_mode
    return svc


def _mock_token(svc):
    svc.get_client_token = AsyncMock(return_value="test_bearer_token")
    return svc


def _make_200_resp(data: dict) -> AsyncMock:
    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={"success": True, "data": {"subscription": data}})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_400_resp(field_errors: list) -> AsyncMock:
    resp = AsyncMock()
    resp.status = 400
    resp.json = AsyncMock(return_value={"fieldErrors": field_errors})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(resp: AsyncMock) -> MagicMock:
    session = MagicMock()
    session.post = MagicMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


class TestMonthlyBody:
    """AC-3: monthly request body — frequency/interval/byMonthDay."""

    def test_monthly_body_shape(self):
        svc = _make_service(mock_mode=False)
        _mock_token(svc)

        captured = {}

        def _fake_post(url, json=None, headers=None):
            captured["body"] = json
            return _make_200_resp({
                "id": "sub_monthly_test",
                "url": "https://express.stitch.money/checkout/sub_monthly_test",
                "status": "PENDING",
                "merchantReference": json.get("merchantReference", ""),
            })

        session = MagicMock()
        session.post = _fake_post
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.stitch_service._stitch_session", return_value=session):
            asyncio.get_event_loop().run_until_complete(
                svc.create_subscription(
                    user_id=42,
                    plan_code="gold_monthly",
                    amount_cents=9900,
                    period="monthly",
                    payer_name="Test User",
                    payer_email="test@example.com",
                )
            )

        body = captured["body"]
        rec = body["recurrence"]
        assert rec["frequency"] == "MONTHLY"
        assert rec["interval"] == 1
        assert "byMonthDay" in rec
        assert "byMonth" not in rec

    def test_monthly_by_month_day_is_utc_day(self):
        svc = _make_service(mock_mode=False)
        _mock_token(svc)

        captured = {}
        utc_day = datetime.now(timezone.utc).day

        def _fake_post(url, json=None, headers=None):
            captured["body"] = json
            return _make_200_resp({
                "id": "sub_day_test",
                "url": "https://express.stitch.money/checkout/sub_day_test",
                "status": "PENDING",
                "merchantReference": json.get("merchantReference", ""),
            })

        session = MagicMock()
        session.post = _fake_post
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.stitch_service._stitch_session", return_value=session):
            asyncio.get_event_loop().run_until_complete(
                svc.create_subscription(
                    user_id=7,
                    plan_code="gold_monthly",
                    amount_cents=9900,
                    period="monthly",
                    payer_name="Test",
                    payer_email="t@example.com",
                )
            )

        assert captured["body"]["recurrence"]["byMonthDay"] == utc_day


class TestAnnualBody:
    """AC-4: annual request body — frequency/interval/byMonth/byMonthDay."""

    def test_annual_body_shape(self):
        svc = _make_service(mock_mode=False)
        _mock_token(svc)

        captured = {}
        now = datetime.now(timezone.utc)

        def _fake_post(url, json=None, headers=None):
            captured["body"] = json
            return _make_200_resp({
                "id": "sub_annual_test",
                "url": "https://express.stitch.money/checkout/sub_annual_test",
                "status": "PENDING",
                "merchantReference": json.get("merchantReference", ""),
            })

        session = MagicMock()
        session.post = _fake_post
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.stitch_service._stitch_session", return_value=session):
            asyncio.get_event_loop().run_until_complete(
                svc.create_subscription(
                    user_id=99,
                    plan_code="diamond_annual",
                    amount_cents=159900,
                    period="annual",
                    payer_name="Annual User",
                    payer_email="annual@example.com",
                )
            )

        rec = captured["body"]["recurrence"]
        assert rec["frequency"] == "YEARLY"
        assert rec["interval"] == 1
        assert rec["byMonth"] == now.month
        assert rec["byMonthDay"] == now.day


class TestResponseParsing:
    """AC-1/AC-7: response parsing and return shape."""

    def test_200_response_parsed_correctly(self):
        svc = _make_service(mock_mode=False)
        _mock_token(svc)

        resp = _make_200_resp({
            "id": "sub_abc123",
            "url": "https://express.stitch.money/checkout/sub_abc123",
            "status": "PENDING",
            "merchantReference": "mze-42-gold-monthly-deadbeef",
        })
        session = _make_session(resp)

        with patch("services.stitch_service._stitch_session", return_value=session):
            result = asyncio.get_event_loop().run_until_complete(
                svc.create_subscription(
                    user_id=42,
                    plan_code="gold_monthly",
                    amount_cents=9900,
                    period="monthly",
                    payer_name="Test",
                    payer_email="test@example.com",
                    reference="mze-42-gold-monthly-deadbeef",
                )
            )

        assert result["subscription_id"] == "sub_abc123"
        assert result["checkout_url"] == "https://express.stitch.money/checkout/sub_abc123"
        assert result["status"] == "PENDING"
        assert result["reference"] == "mze-42-gold-monthly-deadbeef"

    def test_400_raises_runtime_error_with_field_errors(self):
        svc = _make_service(mock_mode=False)
        _mock_token(svc)

        resp = _make_400_resp([{"field": "recurrence.byMonthDay", "message": "is required"}])
        session = _make_session(resp)

        with patch("services.stitch_service._stitch_session", return_value=session):
            with pytest.raises(RuntimeError, match="400"):
                asyncio.get_event_loop().run_until_complete(
                    svc.create_subscription(
                        user_id=1,
                        plan_code="gold_monthly",
                        amount_cents=9900,
                        period="monthly",
                        payer_name="Test",
                        payer_email="t@e.com",
                    )
                )

    def test_payer_id_is_string_user_id(self):
        svc = _make_service(mock_mode=False)
        _mock_token(svc)

        captured = {}

        def _fake_post(url, json=None, headers=None):
            captured["body"] = json
            return _make_200_resp({
                "id": "sub_pid",
                "url": "https://x.com/sub_pid",
                "status": "PENDING",
                "merchantReference": "ref",
            })

        session = MagicMock()
        session.post = _fake_post
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.stitch_service._stitch_session", return_value=session):
            asyncio.get_event_loop().run_until_complete(
                svc.create_subscription(
                    user_id=12345,
                    plan_code="gold_monthly",
                    amount_cents=9900,
                    period="monthly",
                    payer_name="Test",
                    payer_email="t@e.com",
                )
            )

        assert captured["body"]["payerId"] == "12345"

    def test_start_date_has_z_suffix(self):
        svc = _make_service(mock_mode=False)
        _mock_token(svc)

        captured = {}

        def _fake_post(url, json=None, headers=None):
            captured["body"] = json
            return _make_200_resp({
                "id": "sub_dt",
                "url": "https://x.com/sub_dt",
                "status": "PENDING",
                "merchantReference": "ref2",
            })

        session = MagicMock()
        session.post = _fake_post
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.stitch_service._stitch_session", return_value=session):
            asyncio.get_event_loop().run_until_complete(
                svc.create_subscription(
                    user_id=1,
                    plan_code="gold_monthly",
                    amount_cents=9900,
                    period="monthly",
                    payer_name="Test",
                    payer_email="t@e.com",
                )
            )

        start = captured["body"]["startDate"]
        assert start.endswith("Z"), f"startDate must end with Z, got: {start}"
        assert "T" in start, f"startDate must be full ISO 8601, got: {start}"


class TestTokenScope:
    """AC-2: get_client_token caches per-scope independently."""

    def test_two_scopes_hit_token_endpoint_twice(self):
        from services.stitch_service import StitchService, _token_cache
        _token_cache.clear()

        svc = StitchService.__new__(StitchService)
        svc.client_id = "cid"
        svc.client_secret = "cs"
        svc.webhook_secret = "ws"
        svc._is_mock = lambda: False

        call_count = 0

        def _fake_post(url, json=None, headers=None):
            nonlocal call_count
            call_count += 1
            resp = AsyncMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={
                "success": True,
                "data": {"accessToken": f"tok_{call_count}"},
            })
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        from services import stitch_service as _ss
        session = MagicMock()
        session.post = _fake_post
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.stitch_service._stitch_session", return_value=session):
            loop = asyncio.get_event_loop()
            t1 = loop.run_until_complete(svc.get_client_token("client_paymentrequest"))
            t2 = loop.run_until_complete(svc.get_client_token("client_recurringpaymentconsentrequest"))

        assert call_count == 2
        assert t1 != t2

    def test_same_scope_uses_cache(self):
        from services.stitch_service import StitchService, _token_cache
        _token_cache.clear()

        svc = StitchService.__new__(StitchService)
        svc.client_id = "cid"
        svc.client_secret = "cs"
        svc.webhook_secret = "ws"
        svc._is_mock = lambda: False

        call_count = 0

        def _fake_post(url, json=None, headers=None):
            nonlocal call_count
            call_count += 1
            resp = AsyncMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={
                "success": True,
                "data": {"accessToken": "tok_cached"},
            })
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            return resp

        session = MagicMock()
        session.post = _fake_post
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.stitch_service._stitch_session", return_value=session):
            loop = asyncio.get_event_loop()
            loop.run_until_complete(svc.get_client_token("client_paymentrequest"))
            loop.run_until_complete(svc.get_client_token("client_paymentrequest"))

        assert call_count == 1


class TestMockMode:
    """create_subscription in mock mode returns a mock-shaped dict."""

    def test_mock_returns_subscription_id(self):
        svc = _make_service(mock_mode=True)
        result = asyncio.get_event_loop().run_until_complete(
            svc.create_subscription(
                user_id=42,
                plan_code="gold_monthly",
                amount_cents=9900,
                period="monthly",
                payer_name="Mock User",
                payer_email="mock@example.com",
            )
        )
        assert "subscription_id" in result
        assert "checkout_url" in result
        assert "status" in result
        assert "reference" in result

    def test_mock_checkout_url_is_string(self):
        svc = _make_service(mock_mode=True)
        result = asyncio.get_event_loop().run_until_complete(
            svc.create_subscription(
                user_id=1,
                plan_code="diamond_monthly",
                amount_cents=19900,
                period="monthly",
                payer_name="Mock",
                payer_email="m@example.com",
            )
        )
        assert isinstance(result["checkout_url"], str)
        assert len(result["checkout_url"]) > 0
