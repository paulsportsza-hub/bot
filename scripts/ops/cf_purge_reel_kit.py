#!/usr/bin/env python3
"""Purge Cloudflare cache for /assets/reel-cards/<date>/ assets.

FIX-DASH-REEL-WIDGET-01 — Operations utility. When a reel kit is regenerated
on disk, the dashboard widget URL gets a new ?v=<mtime> query string and the
nginx Cache-Control is now max-age=300 must-revalidate, so refreshes are
fast. Cloudflare's edge cache, however, can still hold the old object for
the entire ?v= cycle (or longer if Browser Cache TTL was honored). This
script wipes Cloudflare's edge cache for every file under a date dir so
the very next request from any user goes to origin.

Usage:
    python3 -m scripts.ops.cf_purge_reel_kit --date 2026-04-28
    python3 -m scripts.ops.cf_purge_reel_kit --date 2026-04-28 --dry-run
    python3 -m scripts.ops.cf_purge_reel_kit --date today

Env (set in ~/.env or environment):
    CLOUDFLARE_API_TOKEN  — token with Zone.Cache Purge permission
    CLOUDFLARE_ZONE_ID    — zone id for mzansiedge.co.za

Exit codes:
    0  — purge successful (or dry-run completed)
    1  — invalid args or missing env
    2  — Cloudflare API rejected the request
    3  — date dir not found on disk

The Cloudflare API caps a single purge_cache call at 30 URLs. We chunk the
file list and walk each chunk sequentially so a kit with three VOs plus a
card across multiple picks never overflows.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import date, timedelta

_REEL_CARDS_ROOT = "/var/www/mzansiedge/assets/reel-cards"
_PUBLIC_BASE = "https://mzansiedge.co.za/assets/reel-cards"
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CF_API = "https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache"
_PURGE_CHUNK = 30  # Cloudflare hard limit per call


def _resolve_date(arg: str) -> str:
    today = date.today()
    if arg in ("today", ""):
        return today.isoformat()
    if arg in ("yesterday",):
        return (today - timedelta(days=1)).isoformat()
    if not _RE_DATE.match(arg):
        raise SystemExit(f"invalid date: {arg!r} (expected YYYY-MM-DD or 'today')")
    return arg


def _collect_urls(date_str: str) -> list[str]:
    """Walk the date dir and return absolute public URLs for every file."""
    date_dir = os.path.join(_REEL_CARDS_ROOT, date_str)
    if not os.path.isdir(date_dir):
        raise SystemExit((3, f"date dir not found: {date_dir}"))
    urls: list[str] = []
    for pick_id in sorted(os.listdir(date_dir)):
        pick_dir = os.path.join(date_dir, pick_id)
        if not os.path.isdir(pick_dir):
            continue
        for fname in sorted(os.listdir(pick_dir)):
            if fname.startswith("."):
                continue
            urls.append(f"{_PUBLIC_BASE}/{date_str}/{pick_id}/{fname}")
    return urls


def _purge_chunk(zone_id: str, token: str, urls: list[str]) -> dict:
    body = json.dumps({"files": urls}).encode("utf-8")
    req = urllib.request.Request(
        _CF_API.format(zone=zone_id),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return {"success": False, "errors": [{"code": exc.code, "message": err_body or str(exc)}]}
    except urllib.error.URLError as exc:
        return {"success": False, "errors": [{"message": str(exc)}]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Purge Cloudflare cache for reel-cards.")
    p.add_argument("--date", default="today",
                   help="YYYY-MM-DD or 'today'/'yesterday' (default: today)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print URLs that would be purged, don't call Cloudflare")
    args = p.parse_args(argv)

    date_str = _resolve_date(args.date)

    try:
        urls = _collect_urls(date_str)
    except SystemExit as exc:
        if isinstance(exc.code, tuple):
            code, msg = exc.code
            print(f"ERROR: {msg}", file=sys.stderr)
            return code
        raise

    if not urls:
        print(f"No reel kit assets found for {date_str} — nothing to purge.")
        return 0

    print(f"Resolved {len(urls)} reel-cards URLs for {date_str}.")

    if args.dry_run:
        for u in urls:
            print(f"  would purge: {u}")
        return 0

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "").strip()
    if not token or not zone_id:
        print("ERROR: CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID must be set "
              "(see ~/.env).", file=sys.stderr)
        return 1

    overall_ok = True
    for i in range(0, len(urls), _PURGE_CHUNK):
        chunk = urls[i:i + _PURGE_CHUNK]
        result = _purge_chunk(zone_id, token, chunk)
        ok = bool(result.get("success"))
        overall_ok = overall_ok and ok
        if ok:
            print(f"  purged chunk {i // _PURGE_CHUNK + 1}: {len(chunk)} URLs")
        else:
            errors = result.get("errors") or []
            print(f"  CHUNK FAILED ({i // _PURGE_CHUNK + 1}): {errors}", file=sys.stderr)

    return 0 if overall_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
