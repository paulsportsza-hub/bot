"""IMG-PW1: Generic Playwright HTML-to-PNG renderer.

Usage:
    from card_renderer import render_card, render_card_sync
    png_bytes = await render_card("edge_summary.html", data, width=480)
    png_bytes = render_card_sync("edge_summary.html", data, width=480)

LOCKED RENDER STANDARD (IMG-PW2R — updated CARD-FIX-L):
    width=480, height=620, device_scale_factor=2 → 960×1240px physical output.
    Fixed clip: {"x":0,"y":0,"width":480,"height":620} — every card identical dimensions.
    No omit_background (transparent PNG causes grey edges on Telegram Desktop).
    Do NOT change these defaults without a brief.

BROWSER POOL (BUILD-W3):
    A persistent Chromium browser runs in a background daemon thread's event loop.
    render_card_sync() submits page-render coroutines via run_coroutine_threadsafe —
    browser cold-start only happens once per process lifetime (~1-2s), not per render.
    Individual renders create + close one page each (~200-400ms).
"""
from __future__ import annotations
import asyncio
import logging
import threading
import time
from pathlib import Path

import hashlib
import json

from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "card_templates"

_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)

# ── Browser pool ──────────────────────────────────────────────────────────────
# _pool["loop"]    — asyncio event loop running in the daemon thread
# _pool["browser"] — persistent Chromium browser (launched once)
# _pool["ready"]   — threading.Event set when browser is alive
# _pool["pw_ctx"]  — async_playwright() context manager kept alive
_pool: dict = {
    "loop": None,
    "browser": None,
    "pw_ctx": None,
    "ready": threading.Event(),
    "error": None,
    "lock": threading.Lock(),
}


async def _pool_init() -> None:
    """Called once in the pool's event loop — starts playwright + browser."""
    try:
        pw_ctx = async_playwright()
        pw = await pw_ctx.__aenter__()
        browser = await pw.chromium.launch()
        _pool["pw_ctx"] = pw_ctx
        _pool["browser"] = browser
        _pool["ready"].set()
        log.info("card_renderer: browser pool initialised")
    except Exception as exc:
        _pool["error"] = exc
        _pool["ready"].set()  # unblock render_card_sync so it can raise
        log.error("card_renderer: pool init failed: %s", exc)


async def _recreate_browser() -> None:
    """Close dead Playwright context and launch a fresh browser.

    Runs inside the pool's event loop. Called by _render_page_safe() on crash detection.
    """
    try:
        if _pool.get("browser"):
            await _pool["browser"].close()
    except Exception:
        pass  # browser is already dead — ignore
    try:
        if _pool.get("pw_ctx"):
            await _pool["pw_ctx"].__aexit__(None, None, None)
    except Exception:
        pass  # playwright context may already be dead
    # Re-launch fresh browser + playwright context
    pw_ctx = async_playwright()
    pw = await pw_ctx.__aenter__()
    browser = await pw.chromium.launch()
    with _pool["lock"]:
        _pool["pw_ctx"] = pw_ctx
        _pool["browser"] = browser
    log.info("card_renderer: browser pool recreated after crash")


def _run_pool() -> None:
    """Daemon thread target: own event loop, init browser, then run forever."""
    loop = asyncio.new_event_loop()
    _pool["loop"] = loop
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_pool_init())
    loop.run_forever()


_pool_thread = threading.Thread(target=_run_pool, daemon=True, name="card-renderer-pool")
_pool_thread.start()


async def _render_page(
    template_name: str,
    data: dict,
    width: int,
    device_scale_factor: int,
) -> bytes:
    """Render one page using the pooled browser (runs in pool event loop)."""
    browser = _pool["browser"]
    template = _env.get_template(template_name)
    html = template.render(**data)

    # CARD-FIX-L: all cards render at fixed 480×620 CSS px → 960×1240px physical
    _card_height = 620
    _start = time.monotonic()
    page = await browser.new_page(
        viewport={"width": width, "height": _card_height},
        device_scale_factor=device_scale_factor,
    )
    try:
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(50)  # minimal settle time

        png_bytes = await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": width, "height": _card_height},
        )
    finally:
        await page.close()

    _elapsed_ms = (time.monotonic() - _start) * 1000
    log.info(
        "card_render_complete template=%s elapsed_ms=%.1f bytes=%d size=%dx%dpx",
        template_name,
        _elapsed_ms,
        len(png_bytes),
        width * device_scale_factor,
        _card_height * device_scale_factor,
    )
    return png_bytes


async def _render_page_safe(
    template_name: str,
    data: dict,
    width: int,
    device_scale_factor: int,
) -> bytes:
    """Render with automatic browser recovery on crash.

    Wraps _render_page(). On a dead-browser error, recreates the browser and
    retries once. Non-browser errors are re-raised immediately.
    """
    try:
        return await _render_page(template_name, data, width, device_scale_factor)
    except Exception as e:
        err_str = str(e).lower()
        if "closed" in err_str or "target" in err_str or "browser" in err_str:
            log.warning(
                "card_renderer: browser crash detected (%s), recreating pool...", e
            )
            await _recreate_browser()
            return await _render_page(template_name, data, width, device_scale_factor)
        raise  # non-browser error: re-raise as-is


def render_card_sync(
    template_name: str,
    data: dict,
    width: int = 480,
    device_scale_factor: int = 2,
    *,
    cache_ttl: int | None = None,
) -> bytes:
    """Render a card synchronously using the persistent browser pool.

    Safe to call from any thread (including asyncio.to_thread).
    Blocks until the render completes or raises on error.

    Results are cached in card_cache (in-memory LRU). Pass cache_ttl to
    override the default TTL (300s on-demand / 900s precomputed).
    """
    from card_cache import card_cache as _cc

    # Cache key: template + data hash (invalidates when data changes)
    _data_hash = hashlib.md5(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    _cache_key = f"{template_name}:{_data_hash}"

    _cached = _cc.get(_cache_key)
    if _cached is not None:
        log.debug("card_renderer: cache HIT for %s", _cache_key)
        return _cached

    # Wait for pool to be ready (browser launch or error)
    if not _pool["ready"].wait(timeout=30):
        raise RuntimeError("card_renderer: browser pool did not initialise in 30s")
    if _pool["error"]:
        raise RuntimeError(f"card_renderer: pool init failed: {_pool['error']}") from _pool["error"]

    loop = _pool["loop"]
    if loop is None:
        raise RuntimeError("card_renderer: pool loop is None")

    future = asyncio.run_coroutine_threadsafe(
        _render_page_safe(template_name, data, width, device_scale_factor),
        loop,
    )
    png_bytes = future.result(timeout=90)
    _cc.put(_cache_key, png_bytes, ttl=cache_ttl)
    return png_bytes


async def render_card(
    template_name: str,
    data: dict,
    width: int = 480,
    device_scale_factor: int = 2,
) -> bytes:
    """Async wrapper — delegates to render_card_sync via asyncio.to_thread."""
    return await asyncio.to_thread(
        render_card_sync, template_name, data,
        width=width, device_scale_factor=device_scale_factor,
    )


def warm_chromium() -> None:
    """MM-05: Render a minimal 1×1px page to keep the Chromium process warm.

    Call from a PTB job (or external cron) every 60 minutes to prevent 10+ second
    cold-start renders after 1.5h+ idle. Blocks up to 15s; output is discarded.
    """
    _WARM_HTML = "<html><body style='background:#000;width:1px;height:1px;'></body></html>"

    async def _do_warm() -> None:
        browser = _pool.get("browser")
        if not browser:
            raise RuntimeError("no browser in pool")
        page = await browser.new_page(viewport={"width": 1, "height": 1})
        try:
            await page.set_content(_WARM_HTML)
            await page.screenshot(type="png", clip={"x": 0, "y": 0, "width": 1, "height": 1})
        finally:
            await page.close()

    if not _pool["ready"].wait(timeout=30):
        log.warning("warm_chromium: browser pool not ready — skipping")
        return
    if _pool.get("error"):
        log.warning("warm_chromium: pool init failed — skipping")
        return
    loop = _pool.get("loop")
    if not loop:
        log.warning("warm_chromium: pool loop not available — skipping")
        return
    future = asyncio.run_coroutine_threadsafe(_do_warm(), loop)
    try:
        future.result(timeout=15)
        log.info("warm_chromium: keep-warm render complete")
    except Exception as exc:
        log.warning("warm_chromium: keep-warm render failed: %s", exc)
