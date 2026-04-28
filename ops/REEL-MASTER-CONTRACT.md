# Reel Master URL Contract

**Brief:** FIX-REEL-MASTER-URL-CONTRACT-01 (2026-04-28)
**Status:** Locked — single source of truth for reel master MP4 layout.

## Canonical Layout (LOCKED)

| Surface | Pattern |
|---------|---------|
| Filesystem path | `/home/paulsportsza/bot/assets/reels/<YYYY-MM-DD>/final/<row_id>.mp4` |
| Public URL | `https://mzansiedge.co.za/assets/reels/<YYYY-MM-DD>/final/<row_id>.mp4` |
| Cache-bust query | `?v=<file_mtime_int>` (epoch seconds, appended client-side) |
| nginx alias | `location ^~ /assets/reels/` → `/home/paulsportsza/bot/assets/reels/` |

`<row_id>` is the **MOQ Notion page ID** of the row that owns the reel — same value
the upload route writes (`api_reel_final_upload`, `dashboard/health_dashboard.py`).
NEVER `<pick_id>_master.mp4` — `pick_id` is the upstream Reel Kit identifier and is
not a filename in the master tree.

## Constants

Defined in `dashboard/health_dashboard.py:159-160`:

```python
_REEL_FINALS_ROOT = "/home/paulsportsza/bot/assets/reels"
_REEL_PUBLIC_BASE = "https://mzansiedge.co.za/assets/reels"
```

## Producer

`api_reel_final_upload()` (`/admin/reel/upload` POST) writes to
`<_REEL_FINALS_ROOT>/<date>/final/<row_id>.mp4`. This is the only producer.

## Consumer

`api_so_post()` (`/admin/api/social-ops/post/<post_id>`) builds the public master URL
that the social-ops dashboard widget consumes. The URL builder MUST mirror the
producer layout: `<_REEL_PUBLIC_BASE>/<date>/final/<post_id>.mp4` (`post_id` here is
the same Notion page ID — it equals `row_id` from the upload route).

The widget appends `?v=<reel_master_mtime>` (the producer-supplied file mtime epoch
seconds) at render time so freshly uploaded masters bust the browser cache without
poisoning the long-cache hit ratio across re-renders of the same upload.

## nginx Route

```
location ^~ /assets/reels/ {
    alias /home/paulsportsza/bot/assets/reels/;
    add_header Cache-Control "public, max-age=300, must-revalidate" always;
    types { video/mp4 mp4; }
    access_log off;
}
```

`max-age=300` (5 min) + `must-revalidate` matches the FIX-DASH-REEL-WIDGET-01
pattern for `/assets/reel-cards/`. NOT `immutable` — masters CAN be re-uploaded
under the same row_id, and the cache-bust query handles the freshness window
during the 5-minute revalidate gap.

## Regression Guards

`bot/tests/contracts/test_reel_master_url_contract.py` — 5 tests:

1. Widget URL uses `<row_id>.mp4` filename (regression guard: fails if
   `<pick_id>_master.mp4` reappears anywhere in the URL builder path).
2. Public URL maps to filesystem path (URL → FS path round-trip is symmetric).
3. nginx config exposes `/assets/reels/` location block.
4. Cache-bust query equals `reel_master_mtime` field shape.
5. Strict regression guard: `_master.mp4` substring is absent from the URL
   builder source line.

## Why This Layout Won

`<row_id>` is **already** the Notion page ID the operator uses to find the upload —
it ties the asset back to the MOQ row by Notion's primary key, no auxiliary
index, no rename step. The alternative (renaming uploads to `<pick_id>_master.mp4`
in the producer) would have required re-deriving the pick_id from the Notion row
on every fetch, an extra dashboard hop on every Notion → FS lookup. Keep the
write path simple, fix the read URL.
