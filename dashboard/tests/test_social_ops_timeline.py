"""
18 tests for BUILD-SOCIAL-OPS-PILLS-HEALTH-01 — expected-slot cadence pills
in health_dashboard.py.

Tests cover:
  - TODAY_EXPECTED_SLOTS contract (14 rows, required keys, counts)
  - SHOW_REEL_KIT_ON_TIMELINE flag
  - _slots_for_dow() day-of-week filtering
  - _merge_expected_slots() overdue/upcoming logic + ±30 min matching
  - _build_so_timeline() sort order and kind field on posted items
"""
import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy deps so health_dashboard imports cleanly in CI
# ---------------------------------------------------------------------------

def _stub_imports():
    stubs = [
        "flask", "flask_login", "sentry_sdk", "sentry_sdk.integrations.flask",
        "posthog", "anthropic",
    ]
    for mod in stubs:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
    fm = sys.modules.setdefault("flask", MagicMock())
    fm.Flask = MagicMock(return_value=MagicMock())
    fm.request = MagicMock()
    fm.Response = MagicMock(side_effect=lambda body, **kw: body)
    fm.redirect = MagicMock()
    fm.jsonify = MagicMock(side_effect=lambda d: d)
    fm.render_template_string = MagicMock(return_value="")

_stub_imports()

sys.path.insert(0, "/home/paulsportsza/bot")
sys.path.insert(0, "/home/paulsportsza/bot/dashboard")

with patch("dashboard.health_dashboard._fetch_marketing_queue", return_value=([], None)):
    import dashboard.health_dashboard as hd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAST = timezone(timedelta(hours=2))
_SATURDAY_DOW = 5
_SUNDAY_DOW   = 6
_MONDAY_DOW   = 0


def _sast(h: int, m: int, date_str: str = "2026-04-18") -> datetime:
    """Return a UTC datetime for a given SAST HH:MM on date_str (Saturday 2026-04-18)."""
    naive = datetime.fromisoformat(f"{date_str}T{h:02d}:{m:02d}:00")
    sast_dt = naive.replace(tzinfo=_SAST)
    return sast_dt.astimezone(timezone.utc)


def _posted_item(channel: str, h: int, m: int, day: str = "2026-04-18") -> dict:
    """Build a minimal MOQ item that counts as posted."""
    sast_dt = datetime.fromisoformat(f"{day}T{h:02d}:{m:02d}:00+02:00")
    return {
        "id": f"moq_{channel}_{h:02d}{m:02d}",
        "channel": channel,
        "status": "published",
        "scheduled_time": sast_dt.isoformat(),
        "title": "test post",
    }


# Saturday 2026-04-18 is day_str used throughout
_DAY = "2026-04-18"


# ---------------------------------------------------------------------------
# AC1 — Cadence contract tests
# ---------------------------------------------------------------------------

class TestCadenceContract(unittest.TestCase):

    def test_slot_count_under_50(self):
        """Total contract rows must be < 50 (stop threshold)."""
        self.assertLess(len(hd.TODAY_EXPECTED_SLOTS), 50)

    def test_exactly_14_slots(self):
        """TODAY_EXPECTED_SLOTS must have exactly 14 rows."""
        self.assertEqual(len(hd.TODAY_EXPECTED_SLOTS), 14)

    def test_all_slots_have_required_keys(self):
        """Every slot must have channel, slot_time_sast, slot_label, dow."""
        required = {"channel", "slot_time_sast", "slot_label", "dow"}
        for slot in hd.TODAY_EXPECTED_SLOTS:
            self.assertTrue(required.issubset(slot.keys()),
                            f"Slot missing keys: {slot}")

    def test_saturday_includes_tiktok(self):
        """Saturday (dow=5) must include the TikTok B.R.U slot."""
        sat_slots = hd._slots_for_dow(_SATURDAY_DOW)
        channels = [s["channel"] for s in sat_slots]
        self.assertIn("TikTok", channels)

    def test_sunday_no_tiktok(self):
        """Sunday (dow=6) must NOT include TikTok."""
        sun_slots = hd._slots_for_dow(_SUNDAY_DOW)
        channels = [s["channel"] for s in sun_slots]
        self.assertNotIn("TikTok", channels)

    def test_saturday_tiktok_slot_label(self):
        """TikTok slot label on Saturday must be 'B.R.U clip'."""
        sat_slots = hd._slots_for_dow(_SATURDAY_DOW)
        tiktok = next((s for s in sat_slots if s["channel"] == "TikTok"), None)
        self.assertIsNotNone(tiktok)
        self.assertEqual(tiktok["slot_label"], "B.R.U clip")

    def test_monday_slots_count(self):
        """Monday (dow=0) should have 13 slots (all except TikTok)."""
        mon_slots = hd._slots_for_dow(_MONDAY_DOW)
        self.assertEqual(len(mon_slots), 13)

    def test_show_reel_kit_flag_true(self):
        """SHOW_REEL_KIT_ON_TIMELINE is True after FIX-REEL-KIT-TIMELINE-01."""
        self.assertTrue(hd.SHOW_REEL_KIT_ON_TIMELINE)


# ---------------------------------------------------------------------------
# AC2/AC3/AC4 — Timeline merge and pill classification
# ---------------------------------------------------------------------------

class TestMergeExpectedSlots(unittest.TestCase):

    def test_early_morning_all_future(self):
        """At 00:01 SAST, all Saturday slots should be 'upcoming'."""
        now_utc = _sast(0, 1)
        extra, overdue = hd._merge_expected_slots(_DAY, [], now_utc)
        all_kinds = [p["kind"] for posts in extra.values() for p in posts]
        self.assertEqual(overdue, 0)
        self.assertTrue(all(k == "upcoming" for k in all_kinds),
                        f"Expected all upcoming, got: {set(all_kinds)}")

    def test_midday_some_overdue(self):
        """At 13:30 SAST slots before 13:30 are overdue, after are upcoming."""
        now_utc = _sast(13, 30)
        extra, overdue = hd._merge_expected_slots(_DAY, [], now_utc)
        self.assertGreater(overdue, 0)
        all_kinds = [p["kind"] for posts in extra.values() for p in posts]
        self.assertIn("upcoming", all_kinds)

    def test_end_of_day_almost_all_overdue(self):
        """At 21:00 SAST all slots except 19:00 WA Brief #2 are overdue."""
        now_utc = _sast(21, 0)
        extra, overdue = hd._merge_expected_slots(_DAY, [], now_utc)
        # 19:00 < 21:00 so WA Brief #2 is also overdue → all slots overdue
        all_kinds = [p["kind"] for posts in extra.values() for p in posts]
        self.assertTrue(all(k == "overdue" for k in all_kinds),
                        f"Expected all overdue at 21:00, got: {set(all_kinds)}")

    def test_exact_slot_boundary_not_overdue(self):
        """At exactly 07:30 SAST, the 07:30 slot is NOT yet overdue (strict <)."""
        now_utc = _sast(7, 30)
        extra, overdue = hd._merge_expected_slots(_DAY, [], now_utc)
        # slot_mins=450, now_mins=450 → not overdue (kind="upcoming")
        tg_alerts = extra.get("telegram_alerts", [])
        slot_0730 = next((p for p in tg_alerts if p["sched"] == "07:30"), None)
        self.assertIsNotNone(slot_0730, "07:30 TG Alerts slot should be in extra")
        self.assertEqual(slot_0730["kind"], "upcoming")

    def test_one_minute_past_is_overdue(self):
        """At 07:31 SAST, the 07:30 slot IS overdue."""
        now_utc = _sast(7, 31)
        extra, overdue = hd._merge_expected_slots(_DAY, [], now_utc)
        tg_alerts = extra.get("telegram_alerts", [])
        slot_0730 = next((p for p in tg_alerts if p["sched"] == "07:30"), None)
        self.assertIsNotNone(slot_0730)
        self.assertEqual(slot_0730["kind"], "overdue")
        self.assertGreater(overdue, 0)

    def test_matched_slot_not_duplicated(self):
        """A posted MOQ item that exactly matches a slot removes that slot."""
        items = [_posted_item("Telegram Alerts", 7, 30)]
        now_utc = _sast(10, 0)
        extra, _ = hd._merge_expected_slots(_DAY, items, now_utc)
        tg_alerts = extra.get("telegram_alerts", [])
        slot_0730 = next((p for p in tg_alerts if p["sched"] == "07:30"), None)
        self.assertIsNone(slot_0730, "Matched slot must be removed from extra pills")

    def test_within_30min_window_matches(self):
        """A posted item within ±30 min of a slot should cancel that slot."""
        # Post at 07:55 — within 30 min of 07:30 slot (|55*1+7*60 - (7*60+30)| = 25 min)
        items = [_posted_item("Telegram Alerts", 7, 55)]
        now_utc = _sast(10, 0)
        extra, _ = hd._merge_expected_slots(_DAY, items, now_utc)
        tg_alerts = extra.get("telegram_alerts", [])
        slot_0730 = next((p for p in tg_alerts if p["sched"] == "07:30"), None)
        self.assertIsNone(slot_0730, "Post within ±30 min should cancel the slot")

    def test_outside_30min_window_no_match(self):
        """A posted item more than 30 min away does NOT cancel the slot."""
        # Post at 08:05 — 35 min from 07:30 slot
        items = [_posted_item("Telegram Alerts", 8, 5)]
        now_utc = _sast(10, 0)
        extra, _ = hd._merge_expected_slots(_DAY, items, now_utc)
        tg_alerts = extra.get("telegram_alerts", [])
        slot_0730 = next((p for p in tg_alerts if p["sched"] == "07:30"), None)
        self.assertIsNotNone(slot_0730, "Post outside ±30 min should NOT cancel the slot")

    def test_channel_mismatch_no_match(self):
        """A posted item on a different channel does not cancel a slot."""
        # Post Telegram Community at 07:30 — should not cancel Telegram Alerts 07:30
        items = [_posted_item("Telegram Community", 7, 30)]
        now_utc = _sast(10, 0)
        extra, _ = hd._merge_expected_slots(_DAY, items, now_utc)
        tg_alerts = extra.get("telegram_alerts", [])
        slot_0730 = next((p for p in tg_alerts if p["sched"] == "07:30"), None)
        self.assertIsNotNone(slot_0730, "Different channel post must not cancel this slot")


# ---------------------------------------------------------------------------
# AC5 — OVERDUE QUEUE KPI + posted item kind field
# ---------------------------------------------------------------------------

class TestBuildSoTimeline(unittest.TestCase):

    def _timeline(self, h: int, m: int, items: list = None):
        """Build timeline at given SAST time on Saturday _DAY."""
        now_utc = _sast(h, m)
        return hd._build_so_timeline(_DAY, items or [], now_utc)

    def test_posted_item_shows_posted_kind(self):
        """Regular posted MOQ items must have kind='posted' in the timeline."""
        items = [_posted_item("Telegram Alerts", 7, 30)]
        tl = self._timeline(10, 0, items)
        tg_ch = next((c for c in tl["channels"] if c["key"] == "telegram_alerts"), None)
        self.assertIsNotNone(tg_ch)
        moq_posts = [p for p in tg_ch["posts"] if not p.get("type") == "expected"]
        self.assertTrue(any(p.get("kind") == "posted" for p in moq_posts),
                        "Posted MOQ item must carry kind='posted'")

    def test_timeline_sorted_by_time(self):
        """Posts within each channel row must be sorted ascending by mins."""
        tl = self._timeline(10, 0)
        for ch in tl["channels"]:
            mins = [p["mins"] for p in ch["posts"]]
            self.assertEqual(mins, sorted(mins),
                             f"Channel {ch['key']} posts not sorted by time")

    def test_overdue_queue_kpi_nonzero_when_slots_overdue(self):
        """OVERDUE QUEUE KPI must be > 0 when overdue expected slots exist."""
        tl = self._timeline(21, 0)  # end of day, all slots overdue
        self.assertGreater(tl["kpis"]["overdue_queue_count"], 0)

    def test_overdue_queue_kpi_zero_early_morning(self):
        """OVERDUE QUEUE KPI must be 0 at 00:01 SAST (all slots future)."""
        tl = self._timeline(0, 1)
        self.assertEqual(tl["kpis"]["overdue_queue_count"], 0)


if __name__ == "__main__":
    unittest.main()
