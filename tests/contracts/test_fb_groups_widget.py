"""FIX-DASH-FB-GROUPS-LINK-AND-MARK-POSTED-01 — regression guard.

Defect 1: Active FB groups missing 'url' field → no clickable link in dashboard carousel.
Defect 2: _mark_notion_status_posted used {"select": ...} format on a "status"-type
          Notion property, returning HTTP 400. Mark Posted button silently did nothing.

Tests:
- test_every_active_group_has_url        — every active=True entry has non-empty url
- test_mark_posted_tries_status_type_first — function tries "status" key before "select"
- test_mark_posted_falls_back_to_select  — falls back to "select" when "status" fails
- test_mark_posted_returns_false_on_both_fail — returns False when both formats rejected
- test_mark_posted_empty_page_id         — returns False immediately on empty page_id
- test_moq_fallback_reads_group_context_url — _fetch_fb_groups_moq falls back to
                                              _GROUP_CONTEXT["url"] when registry miss
"""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub heavy external deps so health_dashboard can be imported in test env
# ---------------------------------------------------------------------------

def _stub_heavy_imports() -> None:
    for mod in [
        "flask", "flask_login", "sentry_sdk",
        "sentry_sdk.integrations.flask",
        "posthog", "anthropic",
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
    flask_mock = sys.modules.setdefault("flask", MagicMock())
    flask_mock.Flask = MagicMock(return_value=MagicMock())
    flask_mock.request = MagicMock()
    flask_mock.Response = MagicMock(side_effect=lambda body, **kw: body)
    flask_mock.jsonify = MagicMock(side_effect=lambda d: d)


_stub_heavy_imports()

# Ensure publisher is importable (health_dashboard also injects this, but be explicit)
_publisher_root = "/home/paulsportsza"
if _publisher_root not in sys.path:
    sys.path.insert(0, _publisher_root)

import dashboard.health_dashboard as hd  # noqa: E402


# ---------------------------------------------------------------------------
# Helper — load _GROUP_CONTEXT fresh (isolated, no health_dashboard side-effects)
# ---------------------------------------------------------------------------

def _get_group_context() -> dict:
    spec = importlib.util.spec_from_file_location(
        "fb_groups_daily",
        os.path.join(_publisher_root, "publisher/autogen/fb_groups_daily.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod._GROUP_CONTEXT


# ---------------------------------------------------------------------------
# Test 1 — every active group has a non-empty url
# ---------------------------------------------------------------------------

def test_every_active_group_has_url():
    """AC-1: every active=True entry in _GROUP_CONTEXT must have a non-empty url."""
    ctx = _get_group_context()
    missing = [
        name for name, cfg in ctx.items()
        if cfg.get("active") and not cfg.get("url")
    ]
    assert missing == [], (
        f"Active groups missing 'url': {missing}. "
        "Dashboard carousel cannot show a clickable link without it."
    )


# ---------------------------------------------------------------------------
# Test 2 — _mark_notion_status_posted tries "status" type first
# ---------------------------------------------------------------------------

def test_mark_posted_tries_status_type_first():
    """AC-2: function calls Notion PATCH with {"status": {"name": "Posted"}} first."""
    calls: list[dict] = []

    def fake_notion_request(path, body=None, method="GET"):
        calls.append(body)
        return {"object": "page"}

    with patch.object(hd, "_notion_request", side_effect=fake_notion_request):
        result = hd._mark_notion_status_posted("abc123")

    assert result is True
    assert calls, "No Notion PATCH call was made"
    first_props = calls[0]["properties"]
    assert "status" in first_props["Status"], (
        "First attempt must use 'status' type format (not 'select')"
    )


# ---------------------------------------------------------------------------
# Test 3 — falls back to "select" when "status" format returns None
# ---------------------------------------------------------------------------

def test_mark_posted_falls_back_to_select():
    """AC-3: if 'status' format returns None, retries with 'select' format."""
    attempt_formats: list[str] = []

    def fake_notion_request(path, body=None, method="GET"):
        props = body["properties"]["Status"]
        fmt = list(props.keys())[0]
        attempt_formats.append(fmt)
        if fmt == "status":
            return None  # simulate HTTP 400 returned as None
        return {"object": "page"}

    with patch.object(hd, "_notion_request", side_effect=fake_notion_request):
        result = hd._mark_notion_status_posted("page_xyz")

    assert result is True
    assert attempt_formats == ["status", "select"], (
        f"Expected ['status', 'select'] attempts, got {attempt_formats}"
    )


# ---------------------------------------------------------------------------
# Test 4 — returns False when both formats fail
# ---------------------------------------------------------------------------

def test_mark_posted_returns_false_on_both_fail():
    """AC-4: returns False when both 'status' and 'select' formats return None."""
    with patch.object(hd, "_notion_request", return_value=None):
        result = hd._mark_notion_status_posted("bad_page_id")
    assert result is False


# ---------------------------------------------------------------------------
# Test 5 — empty page_id returns False immediately
# ---------------------------------------------------------------------------

def test_mark_posted_empty_page_id_returns_false():
    """AC-5: returns False immediately on empty page_id without calling Notion."""
    with patch.object(hd, "_notion_request") as mock_req:
        result = hd._mark_notion_status_posted("")
    mock_req.assert_not_called()
    assert result is False


# ---------------------------------------------------------------------------
# Test 6 — _fetch_fb_groups_moq fallback reads _GROUP_CONTEXT url
# ---------------------------------------------------------------------------

def test_moq_fallback_reads_group_context_url():
    """AC-6: when MOQ row has no target_group_url and ledger registry misses,
    _fetch_fb_groups_moq falls back to _GROUP_CONTEXT['url']."""
    fake_item = {
        "id": "page-001",
        "title": "FB Group — Orlando Pirates News — Football",
        "channel": "Facebook Groups",
        "status": "Pending",
        "scheduled_time": "2099-01-01T10:00:00",
        "target_group_url": "",
        "copy": "Test copy",
        "asset_link": "",
        "image_url": "",
    }

    with patch.object(hd, "_fetch_marketing_queue", return_value=([fake_item], None)), \
         patch.object(hd, "_today_sast_str", return_value="2099-01-01"), \
         patch.object(hd, "_is_today_sast", return_value=True), \
         patch.object(hd, "_fetch_fb_ledger_registry", return_value={}), \
         patch.object(hd, "_notion_cache", {}), \
         patch.object(hd, "_notion_cache_lock", threading.Lock()):
        rows = hd._fetch_fb_groups_moq()

    assert rows, "Expected at least one row from _fetch_fb_groups_moq"
    row = rows[0]
    assert row["group"] == "Orlando Pirates News"
    assert row["group_url"], (
        "group_url should be populated from _GROUP_CONTEXT fallback, got empty string. "
        "Check that publisher.autogen.fb_groups_daily._GROUP_CONTEXT has 'url' for this group."
    )
    assert "facebook.com" in row["group_url"].lower(), (
        f"Expected a Facebook URL, got: {row['group_url']}"
    )
