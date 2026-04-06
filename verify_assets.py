"""IMG-W0 — Asset Verification Script.

Validates all card_assets required by the Pillow card renderer.
Exit 0 on full pass. Exit 1 if any check fails.

Usage:
    python verify_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image, ImageFont

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m⚠\033[0m"

_ASSETS = Path(__file__).parent / "card_assets"
_FONTS = _ASSETS / "fonts"
_ICONS = _ASSETS / "icons"
_LOGOS = _ASSETS / "logos"
_BG    = _ASSETS / "bg"

_REQUIRED_FONTS = [
    "Inter-Regular.ttf",
    "Inter-Bold.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Bold.ttf",
]

_REQUIRED_ICONS = [
    "soccer", "rugby", "cricket", "boxing",
    "basketball", "tennis", "trend_up", "trend_down",
    "fire", "diamond", "star", "shield",
    "clock", "trophy", "chart", "lock",
]

failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  {PASS}  {label}")
    else:
        tag = f" — {detail}" if detail else ""
        print(f"  {FAIL}  {label}{tag}")
        failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}")
    print("─" * 50)


# ── 1. Directory structure ────────────────────────────────────────────────────
section("1. Directory structure")
for d in [_ASSETS, _FONTS, _ICONS, _LOGOS, _BG]:
    check(d.is_dir(), f"Exists: {d.relative_to(Path(__file__).parent)}")


# ── 2. Font files ─────────────────────────────────────────────────────────────
section("2. Font files")
for fname in _REQUIRED_FONTS:
    p = _FONTS / fname
    exists = p.exists() and p.stat().st_size > 0
    if exists:
        try:
            font = ImageFont.truetype(str(p), 24)
            check(True, f"Loadable by Pillow: {fname}")
        except Exception as exc:
            check(False, f"Loadable by Pillow: {fname}", str(exc))
    else:
        check(False, f"Exists & non-empty: {fname}")


# ── 3. Icon PNGs ──────────────────────────────────────────────────────────────
section("3. Icon PNGs (64×64 RGBA)")
for name in _REQUIRED_ICONS:
    p = _ICONS / f"{name}.png"
    if not p.exists():
        check(False, f"Exists: icons/{name}.png")
        continue
    try:
        img = Image.open(p)
        is_rgba = img.mode == "RGBA"
        is_size = img.size == (64, 64)
        check(is_rgba and is_size, f"icons/{name}.png — {img.size} {img.mode}",
              "expected 64×64 RGBA" if not (is_rgba and is_size) else "")
    except Exception as exc:
        check(False, f"icons/{name}.png", str(exc))


# ── 4. card_templates.py imports & key symbols ────────────────────────────────
section("4. card_templates.py")
try:
    import card_templates as ct

    # Colour constants
    for sym in [
        "BG_PRIMARY", "BG_CARD", "TEXT_PRIMARY", "TEXT_SECONDARY",
        "GOLD", "TIER_COLORS", "TIER_LABELS", "TIER_EMOJIS", "TIER_SCORE",
    ]:
        check(hasattr(ct, sym), f"Constant: {sym}")

    # Font paths dict
    check(hasattr(ct, "FONT_PATHS"), "FONT_PATHS dict")
    check(hasattr(ct, "load_font"), "load_font() function")

    # Layout constants
    for sym in [
        "CARD_WIDTH", "CARD_HEIGHT", "CARD_PADDING_X", "CARD_PADDING_Y",
        "HEADER_HEIGHT", "FOOTER_HEIGHT", "MAX_CARDS_PER_DIGEST",
        "CONF_BAR_WIDTH", "CONF_BAR_HEIGHT",
    ]:
        check(hasattr(ct, sym), f"Layout constant: {sym}")

    # Asset dirs
    for sym in ["ASSETS_DIR", "FONTS_DIR", "ICONS_DIR", "LOGOS_DIR", "BG_DIR"]:
        check(hasattr(ct, sym), f"Path constant: {sym}")

    # Helper functions
    check(hasattr(ct, "render_team_badge"), "render_team_badge() function")
    check(hasattr(ct, "load_icon"), "load_icon() function")
    check(hasattr(ct, "paste_alpha"), "paste_alpha() function")

except ImportError as exc:
    check(False, "card_templates.py importable", str(exc))


# ── 5. Team badge fallback renderer ───────────────────────────────────────────
section("5. Team badge fallback renderer")
try:
    from card_templates import render_team_badge
    img = render_team_badge("Kaizer Chiefs", size=48)
    check(img is not None, "render_team_badge() returns Image")
    check(img.size == (48, 48), f"Badge size — got {img.size}")
    check(img.mode == "RGBA", f"Badge mode — got {img.mode}")

    # Deterministic: same input → same output
    img1 = render_team_badge("Manchester United", size=64)
    img2 = render_team_badge("Manchester United", size=64)
    import hashlib
    h1 = hashlib.md5(img1.tobytes(), usedforsecurity=False).hexdigest()
    h2 = hashlib.md5(img2.tobytes(), usedforsecurity=False).hexdigest()
    check(h1 == h2, "render_team_badge() is deterministic")

except Exception as exc:
    check(False, "render_team_badge() smoke test", str(exc))


# ── 6. load_font() smoke test ─────────────────────────────────────────────────
section("6. load_font() — all 4 styles")
try:
    from card_templates import load_font
    for style in ["regular", "bold", "mono", "mono_bold"]:
        try:
            font = load_font(style, 24)
            check(font is not None, f"load_font('{style}', 24)")
        except Exception as exc:
            check(False, f"load_font('{style}', 24)", str(exc))
except ImportError as exc:
    check(False, "load_font importable", str(exc))


# ── 7. load_icon() smoke test ─────────────────────────────────────────────────
section("7. load_icon() — sample icons")
try:
    from card_templates import load_icon
    for name in ["soccer", "diamond", "lock"]:
        img = load_icon(name, 32)
        check(img is not None and img.size == (32, 32), f"load_icon('{name}', 32)")
except Exception as exc:
    check(False, "load_icon smoke test", str(exc))


# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("═" * 50)
if not failures:
    print(f"{PASS}  All checks passed — IMG-W0 assets verified.")
    sys.exit(0)
else:
    print(f"{FAIL}  {len(failures)} check(s) failed:")
    for f in failures:
        print(f"     • {f}")
    sys.exit(1)
