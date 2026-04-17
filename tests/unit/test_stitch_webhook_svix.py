"""Unit tests for Svix-based Stitch webhook verification.

STITCH-WEBHOOK-SVIX-FIX-01
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from svix.webhooks import Webhook

# A well-formed whsec_ secret for testing (32 bytes of zeroes, base64-encoded)
_TEST_SECRET = "whsec_MfKQ9r8GKYqrTwjUPZB8TDgD"
_TEST_BODY = b'{"type": "payment.complete", "data": {"id": "pay_test"}}'
_TEST_MSG_ID = "msg_test_abc123"


def _make_service(secret: str = _TEST_SECRET):
    """Return a StitchService instance with the given webhook_secret — no config read."""
    from services.stitch_service import StitchService
    svc = StitchService.__new__(StitchService)
    svc.webhook_secret = secret
    return svc


def _valid_headers(secret: str = _TEST_SECRET, body: bytes = _TEST_BODY,
                   ts: datetime | None = None) -> dict[str, str]:
    """Build headers with a valid Svix signature."""
    if ts is None:
        ts = datetime.now(tz=timezone.utc)
    wh = Webhook(secret)
    sig = wh.sign(_TEST_MSG_ID, ts, body.decode())
    return {
        "svix-id": _TEST_MSG_ID,
        "svix-timestamp": str(int(ts.timestamp())),
        "svix-signature": sig,
    }


class TestStitchWebhookSvix:

    def test_a_valid_signature_returns_true(self):
        """Test A: valid Svix signature → verify_webhook returns True."""
        svc = _make_service()
        headers = _valid_headers()
        assert svc.verify_webhook(headers, _TEST_BODY) is True

    def test_b_tampered_body_returns_false(self):
        """Test B: tampered body → returns False."""
        svc = _make_service()
        headers = _valid_headers(body=_TEST_BODY)
        tampered = b'{"type": "payment.complete", "data": {"id": "pay_hacked"}}'
        assert svc.verify_webhook(headers, tampered) is False

    def test_c_expired_timestamp_returns_false(self):
        """Test C: timestamp >5 min old → returns False (Svix replay protection)."""
        svc = _make_service()
        old_ts = datetime.now(tz=timezone.utc) - timedelta(seconds=400)
        headers = _valid_headers(ts=old_ts)
        assert svc.verify_webhook(headers, _TEST_BODY) is False

    def test_d_missing_headers_returns_false(self):
        """Test D: missing svix headers → returns False."""
        svc = _make_service()
        assert svc.verify_webhook({}, _TEST_BODY) is False

    def test_e_empty_webhook_secret_returns_false(self):
        """Test E: empty webhook_secret → returns False."""
        svc = _make_service(secret="")
        headers = _valid_headers()
        assert svc.verify_webhook(headers, _TEST_BODY) is False

    def test_sentry_breadcrumb_on_failure(self):
        """verify_webhook calls sentry_sdk.add_breadcrumb on signature failure."""
        import services.stitch_service as _mod
        mock_sdk = type("SDK", (), {"add_breadcrumb": staticmethod(lambda **kw: None)})()
        breadcrumbs: list[dict] = []
        mock_sdk.add_breadcrumb = lambda **kw: breadcrumbs.append(kw)

        with patch.object(_mod, "_sentry_sdk", mock_sdk):
            svc = _make_service()
            headers = _valid_headers(body=_TEST_BODY)
            tampered = b'{"type": "tampered"}'
            result = svc.verify_webhook(headers, tampered)

        assert result is False
        assert len(breadcrumbs) == 1
        bc = breadcrumbs[0]
        assert bc["category"] == "stitch.webhook.verify"
        assert bc["level"] == "warning"
        assert bc["data"]["svix_id"] == _TEST_MSG_ID
        assert bc["data"]["has_timestamp"] is True
