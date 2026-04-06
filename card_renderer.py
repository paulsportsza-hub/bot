"""IMG-PW1: Generic Playwright HTML-to-PNG renderer.

Usage:
    from card_renderer import render_card, render_card_sync
    png_bytes = await render_card("edge_summary.html", data, width=480)
    png_bytes = render_card_sync("edge_summary.html", data, width=480)

LOCKED RENDER STANDARD (IMG-PW2R):
    width=480, device_scale_factor=2 → 960px physical output.
    body { padding: 2px; box-sizing: content-box; } adds 2px black bleed on all sides.
    page.screenshot(full_page=True) — no omit_background (transparent PNG causes grey edges on Telegram Desktop).
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

    _start = time.monotonic()
    page = await browser.new_page(
        viewport={"width": width, "height": 100},
        device_scale_factor=device_scale_factor,
    )
    try:
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(600)  # allow fonts to load

        height = await page.evaluate("document.body.scrollHeight")
        if height < 10:
            height = 200
        await page.set_viewport_size({"width": width, "height": height})
        await page.wait_for_timeout(200)

        png_bytes = await page.screenshot(
            type="png",
            full_page=True,
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
        height * device_scale_factor,
    )
    return png_bytes


def render_card_sync(
    template_name: str,
    data: dict,
    width: int = 480,
    device_scale_factor: int = 2,
) -> bytes:
    """Render a card synchronously using the persistent browser pool.

    Safe to call from any thread (including asyncio.to_thread).
    Blocks until the render completes or raises on error.
    """
    # Wait for pool to be ready (browser launch or error)
    if not _pool["ready"].wait(timeout=30):
        raise RuntimeError("card_renderer: browser pool did not initialise in 30s")
    if _pool["error"]:
        raise RuntimeError(f"card_renderer: pool init failed: {_pool['error']}") from _pool["error"]

    loop = _pool["loop"]
    if loop is None:
        raise RuntimeError("card_renderer: pool loop is None")

    future = asyncio.run_coroutine_threadsafe(
        _render_page(template_name, data, width, device_scale_factor),
        loop,
    )
    return future.result(timeout=90)


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
