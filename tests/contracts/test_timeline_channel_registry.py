"""Contract tests — Social Ops timeline channel registry.

FIX-DASH-TIKTOK-LANE-REGISTRY-01 — locks four invariants so a future edit
can never re-introduce the bug pattern that hid the TikTok lane:

1. There is exactly one canonical channel-order tuple list
   (`_TIMELINE_CHANNELS`) — both render paths reference the same object.
2. The Task Hub timeline `_TL_CH` and the Social Ops timeline `_SO_TL_CH`
   ARE `_TIMELINE_CHANNELS` (identity, not just equality) — drift is
   physically impossible.
3. TikTok is in the canonical list — never silently removed.
4. The Social Ops render path always emits the TikTok channel, even on a
   non-BRU day. Empty days set `bru_empty=True`; the channel never `continue`s
   out of the render loop.

The fourth test imports `health_dashboard` directly and inspects the source
of the loop body — it can't run the live render without spinning up Flask,
but the source-level guard catches the exact regression pattern that
existed before this wave (a `continue` inside `if ck == "tiktok":`).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

# Make bot/ importable.
_HERE = Path(__file__).resolve()
_BOT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_BOT_ROOT))

from config import ensure_scrapers_importable  # noqa: E402

ensure_scrapers_importable()


# ── Test 1: canonical list exists with the right shape ──────────────────────


def test_timeline_channels_is_canonical() -> None:
    """`_TIMELINE_CHANNELS` MUST exist and be a non-empty list of tuples."""
    from dashboard import health_dashboard as hd

    assert hasattr(hd, "_TIMELINE_CHANNELS"), (
        "dashboard.health_dashboard MUST expose _TIMELINE_CHANNELS — single "
        "source of truth for the timeline lane order/labels."
    )
    chans = hd._TIMELINE_CHANNELS
    assert isinstance(chans, list)
    assert len(chans) >= 1
    for entry in chans:
        assert isinstance(entry, tuple) and len(entry) == 2, (
            f"every entry must be a (key, label) tuple; got {entry!r}"
        )
        key, label = entry
        assert isinstance(key, str) and key, "channel key must be a non-empty str"
        assert isinstance(label, str) and label, "channel label must be a non-empty str"


# ── Test 2: both registries are the same object ─────────────────────────────


def test_so_tl_ch_is_canonical_alias() -> None:
    """`_SO_TL_CH` MUST be the same object as `_TIMELINE_CHANNELS`.

    Identity (`is`), not just equality. This makes drift impossible — the
    constant cannot be edited away from the canonical list because it is
    the canonical list.
    """
    from dashboard import health_dashboard as hd

    assert hd._SO_TL_CH is hd._TIMELINE_CHANNELS, (
        "_SO_TL_CH must reference _TIMELINE_CHANNELS by identity. "
        "If you redeclare it as a separate list literal, the registries "
        "will drift and the Social Ops timeline will lose channels."
    )


def test_tl_ch_aliases_canonical_in_render_path() -> None:
    """`_TL_CH = _TIMELINE_CHANNELS` MUST appear inside the Task Hub render.

    `_TL_CH` is a function-local in the Task Hub renderer, so we can't
    `is`-compare it. Instead we grep the render function body for the
    explicit assignment that aliases the canonical list.
    """
    from dashboard import health_dashboard as hd

    src = Path(hd.__file__).read_text(encoding="utf-8")

    # Match either `_TL_CH = _TIMELINE_CHANNELS` or the duplicate-tuple
    # pattern `_TL_CH = [\n    ("telegram_alerts", ...)`. The duplicate
    # pattern is the regression we want to catch.
    aliased = re.search(r"_TL_CH\s*=\s*_TIMELINE_CHANNELS", src) is not None
    duplicated = re.search(r"_TL_CH\s*=\s*\[\s*\n\s*\(\"telegram_alerts\"", src)

    assert aliased and duplicated is None, (
        "Task Hub renderer MUST alias `_TL_CH = _TIMELINE_CHANNELS`. "
        "Re-declaring _TL_CH as a separate list literal re-opens the "
        "registry-drift bug fixed by FIX-DASH-TIKTOK-LANE-REGISTRY-01."
    )


# ── Test 3: TikTok is in the canonical list ─────────────────────────────────


def test_tiktok_in_canonical_list() -> None:
    """`_TIMELINE_CHANNELS` MUST contain a `tiktok` entry."""
    from dashboard import health_dashboard as hd

    keys = [k for (k, _) in hd._TIMELINE_CHANNELS]
    assert "tiktok" in keys, (
        "tiktok MUST be in _TIMELINE_CHANNELS — removing it silently "
        "drops the lane from both timelines."
    )


def test_canonical_list_keys_match_channels_dict() -> None:
    """Every key in `_TIMELINE_CHANNELS` MUST exist in `_CHANNELS`.

    Catches the inverse drift: adding a channel to `_TIMELINE_CHANNELS`
    without registering its colour/emoji/icon in `_CHANNELS` would render
    a half-styled lane.
    """
    from dashboard import health_dashboard as hd

    canonical_keys = {k for (k, _) in hd._TIMELINE_CHANNELS}
    channels_keys = {c["key"] for c in hd._CHANNELS}

    missing = canonical_keys - channels_keys
    assert not missing, (
        f"_TIMELINE_CHANNELS keys missing from _CHANNELS: {missing}. "
        "Every timeline channel must have a colour/emoji entry."
    )


# ── Test 4: Social Ops loop never `continue`s for tiktok ────────────────────


def test_social_ops_loop_does_not_continue_on_tiktok() -> None:
    """Source-level guard against the BRU-EMPTY-HIDE regression.

    The pre-fix code had:
        if ck == "tiktok":
            bru_items = _bru_drip_items_for_day(day_str)
            if not bru_items:
                continue   # ← THIS dropped the entire lane

    This test fails if `continue` re-appears inside the `if ck == "tiktok":`
    block. The replacement uses `bru_empty=True` to signal idle state; the
    lane still renders.
    """
    from dashboard import health_dashboard as hd

    src = Path(hd.__file__).read_text(encoding="utf-8")

    # Locate the TikTok branch by anchoring on the unique opener line and
    # the `channels.append(ch_dict)` that closes the per-channel loop body.
    opener = 'if ck == "tiktok":'
    closer = "channels.append(ch_dict)"

    o_idx = src.find(opener)
    assert o_idx != -1, (
        "Could not find `if ck == \"tiktok\":` in dashboard.health_dashboard. "
        "Has the loop body been refactored? Relocate this guard if so."
    )
    c_idx = src.find(closer, o_idx)
    assert c_idx != -1, (
        "Could not find `channels.append(ch_dict)` after the TikTok branch."
    )
    block_body = src[o_idx:c_idx]

    # Forbid bare `continue` inside the TikTok branch — it would drop the
    # lane on non-BRU days and re-introduce the original bug.
    bare_continue = re.search(r"^\s+continue\s*$", block_body, re.MULTILINE)
    assert bare_continue is None, (
        "Found a bare `continue` inside `if ck == \"tiktok\":` — this is the "
        "exact pattern that hid the TikTok lane on non-BRU days. Use "
        "`ch_dict[\"bru_empty\"] = True` to signal idle state instead."
    )


# ── Test 5: API-level smoke — TikTok lane in the timeline payload ──────────


def test_timeline_render_includes_tiktok_when_no_bru(monkeypatch) -> None:
    """The `_build_so_timeline` helper MUST emit a TikTok lane on a non-BRU day.

    We exercise the helper with an empty marketing queue so no posts land
    in any channel, and confirm `tiktok` is still in the resulting channels
    list with `bru_empty=True` and zero posts. This is the canary for the
    fix — it would have failed on the pre-fix code that hit `continue`.
    """
    from dashboard import health_dashboard as hd

    # Stub `_bru_drip_items_for_day` to return [] — non-BRU day, like 2026-04-28.
    monkeypatch.setattr(hd, "_bru_drip_items_for_day", lambda _day: [])

    # 2026-04-28 is even, so naturally a non-BRU day. Use SAST tz to match
    # what the real route handler does.
    now_sast = datetime(2026, 4, 28, 11, 0, tzinfo=hd._SAST)
    payload = hd._build_so_timeline(
        day_str="2026-04-28",
        items=[],
        now_sast=now_sast,
        alerts_sends=[],
    )

    keys = [c["key"] for c in payload.get("channels", [])]
    assert "tiktok" in keys, (
        f"timeline payload missing tiktok lane on a non-BRU day: keys={keys}"
    )
    tt = next(c for c in payload["channels"] if c["key"] == "tiktok")
    assert tt.get("bru_empty") is True, (
        f"tiktok lane MUST set bru_empty=True on a non-BRU day; got {tt}"
    )
    assert tt.get("posts") == [], (
        f"tiktok lane on a non-BRU day MUST have zero posts; got {tt!r}"
    )
