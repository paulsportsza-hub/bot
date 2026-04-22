"""Contract test — FIX-DASH-IG-TIMELINE-PREVIEW-MISMATCH-01, AC3.

test_ig_timeline_and_bottom_bar_resolve_same_row:
  Render _build_so_timeline with two IG reel rows scheduled for the same day:
    - Row A: pending reel (status="pending", reel_state resolves to "needs_upload")
    - Row B: done reel   (status="done",    reel_state resolves to "published")

  After the dedup block the IG channel must contain exactly ONE reel post,
  that post must be Row A (the active/pending one), and its id must be what
  both click handlers would pass to loadPreview() — proving the timeline-card
  click and the bottom-bar IG icon click open the same preview.
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy external deps before importing health_dashboard
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
sys.path.insert(0, "/home/paulsportsza/bot")
sys.path.insert(0, "/home/paulsportsza/bot/dashboard")

import dashboard.health_dashboard as hd  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAST = timezone(timedelta(hours=2))
_DAY  = "2026-04-22"

# now_sast = 10:00 SAST on the test day
_NOW_SAST = datetime(2026, 4, 22, 10, 0, 0, tzinfo=_SAST)

# Both reels are scheduled for noon SAST on the same day
_SCHED = "2026-04-22T12:00:00+02:00"


def _reel_item(item_id: str, status: str) -> dict:
    return {
        "id":             item_id,
        "channel":        "instagram",
        "work_type":      "reel",
        "title":          f"Daily Reel — {_DAY}",
        "status":         status,
        "scheduled_time": _SCHED,
        "last_edited":    "2026-04-22T08:00:00+02:00",
        "ready_for_automation": "yes",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIgTimelineAndBottomBarResolveSameRow(unittest.TestCase):
    """AC3 — timeline click and bottom-bar IG icon must both open the same row."""

    def setUp(self):
        # Prevent filesystem access for the MP4 final-upload check
        self._reel_patcher = patch.object(hd, "_reel_has_final", return_value=False)
        self._reel_patcher.start()

    def tearDown(self):
        self._reel_patcher.stop()

    def _get_ig_channel(self, payload: dict) -> dict | None:
        for ch in payload.get("channels", []):
            if ch.get("key") == "instagram":
                return ch
        return None

    def _reel_posts(self, ig_ch: dict) -> list[dict]:
        """Posts whose reel_state is a real reel state (not empty/blank)."""
        _reel_states = {"needs_upload", "queued", "overdue", "published"}
        return [p for p in ig_ch.get("posts", [])
                if (p.get("reel_state") or "") in _reel_states]

    # --- core AC3 test ---

    def test_ig_timeline_and_bottom_bar_resolve_same_row(self):
        """Two reel rows → dedup keeps only the active one; both handlers use same ID."""
        items = [
            _reel_item("pending-reel-id", "pending"),  # → needs_upload (active)
            _reel_item("done-reel-id",    "done"),     # → published    (done)
        ]
        payload = hd._build_so_timeline(_DAY, items, _NOW_SAST)

        ig_ch = self._get_ig_channel(payload)
        self.assertIsNotNone(ig_ch, "instagram channel missing from timeline payload")

        reel_posts = self._reel_posts(ig_ch)
        self.assertEqual(
            len(reel_posts), 1,
            f"Expected exactly 1 IG reel post after dedup, got {len(reel_posts)}: "
            f"{[p['id'] for p in reel_posts]}",
        )

        surviving = reel_posts[0]

        # The surviving post must be the active/pending reel
        self.assertEqual(
            surviving["id"], "pending-reel-id",
            "Timeline must keep the active (pending) reel, not the done one",
        )
        self.assertEqual(
            surviving["reel_state"], "needs_upload",
            "Surviving reel must have reel_state='needs_upload'",
        )

        # The done reel must not appear
        all_ids = [p["id"] for p in ig_ch.get("posts", [])]
        self.assertNotIn(
            "done-reel-id", all_ids,
            "Done reel must be removed by the dedup block",
        )

        # Both click handlers resolve to the same ID:
        #   - timeline click:   data-post-id = surviving["id"]
        #   - bottom-bar click: _soActiveIgReelId = surviving["id"]
        #     (JS reads first active post from the same posts array)
        active_id_from_timeline = surviving["id"]
        active_id_from_bottombar = next(
            (p["id"] for p in ig_ch.get("posts", [])
             if (p.get("reel_state") or "") in {"needs_upload", "queued", "overdue"}
             and p.get("id") and p["id"] != "__ig_reel_empty__"),
            None,
        )
        self.assertEqual(
            active_id_from_timeline,
            active_id_from_bottombar,
            "Timeline-card click and bottom-bar IG icon must resolve the same row ID",
        )

    # --- supporting AC3 sub-cases ---

    def test_single_pending_reel_not_deduped(self):
        """A single pending reel must pass through unchanged (no dedup needed)."""
        items = [_reel_item("only-reel", "pending")]
        payload = hd._build_so_timeline(_DAY, items, _NOW_SAST)
        ig_ch = self._get_ig_channel(payload)
        reel_posts = self._reel_posts(ig_ch)
        self.assertEqual(len(reel_posts), 1)
        self.assertEqual(reel_posts[0]["id"], "only-reel")

    def test_two_done_reels_keeps_first(self):
        """Two published reels and no active one → keep only the first (index-0)."""
        items = [
            _reel_item("done-a", "done"),
            _reel_item("done-b", "done"),
        ]
        payload = hd._build_so_timeline(_DAY, items, _NOW_SAST)
        ig_ch = self._get_ig_channel(payload)
        reel_posts = self._reel_posts(ig_ch)
        self.assertEqual(
            len(reel_posts), 1,
            "Two published reels must dedup to one",
        )
        self.assertEqual(
            reel_posts[0]["id"], "done-a",
            "Without an active reel, first published reel must survive",
        )

    def test_no_reel_rows_no_dedup(self):
        """No reel items at all → IG channel has no reel posts."""
        # A non-reel IG item (e.g. a story post)
        items = [{
            "id":             "story-post",
            "channel":        "instagram",
            "work_type":      "story",
            "title":          "Daily Story",
            "status":         "pending",
            "scheduled_time": _SCHED,
            "last_edited":    "2026-04-22T08:00:00+02:00",
        }]
        payload = hd._build_so_timeline(_DAY, items, _NOW_SAST)
        ig_ch = self._get_ig_channel(payload)
        reel_posts = self._reel_posts(ig_ch)
        self.assertEqual(len(reel_posts), 0, "Non-reel posts must not appear in reel_posts")


if __name__ == "__main__":
    unittest.main()
