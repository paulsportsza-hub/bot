"""IMG-W0 — Card Template Constants for the Pillow card renderer.

All colour, font-path, layout, and tier constants for the new image-card system.
Colour palette sourced from the JSX `B` object (reference/mzansiedge-full-cards.jsx).
Fonts: Inter (body/heading) + JetBrains Mono (data/numbers).
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ── Asset root ────────────────────────────────────────────────────────────────
ASSETS_DIR = Path(__file__).parent / "card_assets"
FONTS_DIR = ASSETS_DIR / "fonts"
ICONS_DIR = ASSETS_DIR / "icons"
LOGOS_DIR = ASSETS_DIR / "logos"
BG_DIR = ASSETS_DIR / "bg"

# ── Colour palette (JSX B object) ─────────────────────────────────────────────
# Background colours
BG_PRIMARY: tuple[int, int, int] = (10, 14, 23)       # #0A0E17  canvas bg
BG_CARD: tuple[int, int, int] = (17, 24, 39)           # #111827  card surface
BG_ELEVATED: tuple[int, int, int] = (30, 41, 59)       # #1E293B  elevated surface
BG_BORDER: tuple[int, int, int] = (51, 65, 85)         # #334155  border / separator

# Text colours
TEXT_PRIMARY: tuple[int, int, int] = (248, 250, 252)   # #F8FAFC  primary text
TEXT_SECONDARY: tuple[int, int, int] = (148, 163, 184) # #94A3B8  secondary / muted
TEXT_MUTED: tuple[int, int, int] = (100, 116, 139)     # #64748B  disabled / meta

# Accent / brand
GOLD: tuple[int, int, int] = (212, 168, 67)            # #D4A843  primary gold accent
GOLD_LIGHT: tuple[int, int, int] = (251, 220, 110)     # #FBDC6E  light gold highlight
GOLD_DARK: tuple[int, int, int] = (161, 127, 50)       # #A17F32  dark gold shadow

# Tier colours (badge + confidence bar)
TIER_DIAMOND: tuple[int, int, int] = (147, 219, 248)   # #93DBF8  cyan
TIER_GOLD: tuple[int, int, int] = (212, 168, 67)       # #D4A843  gold
TIER_SILVER: tuple[int, int, int] = (148, 163, 184)    # #94A3B8  cool grey
TIER_BRONZE: tuple[int, int, int] = (180, 107, 48)     # #B46B30  warm amber-brown

# Semantic colours
COLOR_SUCCESS: tuple[int, int, int] = (34, 197, 94)    # #22C55E  green
COLOR_WARNING: tuple[int, int, int] = (234, 179, 8)    # #EAB308  amber
COLOR_ERROR: tuple[int, int, int] = (239, 68, 68)      # #EF4444  red
COLOR_INFO: tuple[int, int, int] = (59, 130, 246)      # #3B82F6  blue

# Separator / divider
SEPARATOR: tuple[int, int, int] = (30, 41, 59)         # #1E293B

# ── Tier colour map ───────────────────────────────────────────────────────────
TIER_COLORS: dict[str, tuple[int, int, int]] = {
    "diamond": TIER_DIAMOND,
    "gold":    TIER_GOLD,
    "silver":  TIER_SILVER,
    "bronze":  TIER_BRONZE,
}

TIER_LABELS: dict[str, str] = {
    "diamond": "DIAMOND",
    "gold":    "GOLD",
    "silver":  "SILVER",
    "bronze":  "BRONZE",
}

TIER_EMOJIS: dict[str, str] = {
    "diamond": "💎",
    "gold":    "🥇",
    "silver":  "🥈",
    "bronze":  "🥉",
}

# Representative composite score per tier (confidence bar default)
TIER_SCORE: dict[str, int] = {
    "diamond": 90,
    "gold":    74,
    "silver":  57,
    "bronze":  42,
}

# ── Font paths ────────────────────────────────────────────────────────────────
FONT_PATHS: dict[str, Path] = {
    "regular":   FONTS_DIR / "Inter-Regular.ttf",
    "bold":      FONTS_DIR / "Inter-Bold.ttf",
    "mono":      FONTS_DIR / "JetBrainsMono-Regular.ttf",
    "mono_bold": FONTS_DIR / "JetBrainsMono-Bold.ttf",
}

# System fallbacks (Liberation, ships on Ubuntu 20.04+)
_SYS_FONTS: dict[str, str] = {
    "regular":   "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "bold":      "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "mono":      "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "mono_bold": "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
}


def load_font(style: str, size: int) -> ImageFont.FreeTypeFont:
    """Load Inter/JBM font by style+size; falls back to Liberation then Pillow default."""
    primary = FONT_PATHS.get(style)
    if primary and primary.exists():
        return ImageFont.truetype(str(primary), size)
    fallback = _SYS_FONTS.get(style)
    if fallback and Path(fallback).exists():
        return ImageFont.truetype(fallback, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# ── Canvas dimensions ─────────────────────────────────────────────────────────
CARD_WIDTH = 1080
CARD_HEIGHT = 1080
CARD_PADDING_X = 56        # left/right inner padding
CARD_PADDING_Y = 48        # top/bottom inner padding

# Single-match card (portrait-like)
MATCH_CARD_WIDTH = 1080
MATCH_CARD_HEIGHT = 1080

# Header + footer heights
HEADER_HEIGHT = 200        # y 0..200
FOOTER_HEIGHT = 80         # h from bottom
FOOTER_Y = CARD_HEIGHT - FOOTER_HEIGHT

# Card rows (cards area between header and footer)
CARDS_AREA_Y_START = HEADER_HEIGHT + 10
CARDS_AREA_HEIGHT = FOOTER_Y - CARDS_AREA_Y_START - 10
MAX_CARDS_PER_DIGEST = 5   # Miller's Law

# ── Corner radius ─────────────────────────────────────────────────────────────
CARD_RADIUS = 12           # rounded corner radius for card surface
BADGE_RADIUS = 20          # pill badge corner radius
BAR_RADIUS = 4             # confidence bar corner radius

# ── Icon sizes ────────────────────────────────────────────────────────────────
ICON_SIZE = 64             # source PNG size
ICON_DISPLAY_SM = 24       # small icon display (inline)
ICON_DISPLAY_MD = 32       # medium icon display
ICON_DISPLAY_LG = 48       # large icon display

# ── Sport → icon filename map ─────────────────────────────────────────────────
SPORT_ICON: dict[str, str] = {
    "soccer":      "soccer",
    "football":    "soccer",
    "rugby":       "rugby",
    "rugby_union": "rugby",
    "rugby_league":"rugby",
    "cricket":     "cricket",
    "mma":         "boxing",
    "boxing":      "boxing",
    "combat":      "boxing",
    "basketball":  "basketball",
    "tennis":      "tennis",
}

# ── Badge padding ─────────────────────────────────────────────────────────────
BADGE_PAD_H = 14           # horizontal padding inside badge pill
BADGE_PAD_V = 7            # vertical padding inside badge pill

# ── Confidence bar ────────────────────────────────────────────────────────────
CONF_BAR_WIDTH = 260
CONF_BAR_HEIGHT = 8

# ── Gradient stops (header accent line) ──────────────────────────────────────
GRADIENT_START: tuple[int, int, int] = (212, 168, 67)   # gold
GRADIENT_END: tuple[int, int, int] = (147, 219, 248)    # cyan

# ── Logo paths ────────────────────────────────────────────────────────────────
WORDMARK_PATH = Path(__file__).parent / "assets" / "LOGO" / "mzansiedge-wordmark-dark-transparent.png"
AVATAR_PATH   = Path(__file__).parent / "assets" / "LOGO" / "bru-avatar-dark-background.png"


# ── Team badge fallback renderer ──────────────────────────────────────────────

def render_team_badge(
    team_name: str,
    size: int = 48,
    bg_color: Optional[tuple[int, int, int]] = None,
    text_color: tuple[int, int, int] = TEXT_PRIMARY,
) -> Image.Image:
    """Render a circle badge with team initials for teams with no logo asset.

    Parameters
    ----------
    team_name:
        Full team name (e.g. "Kaizer Chiefs"). Up to 2 initials extracted.
    size:
        Square canvas size in pixels.
    bg_color:
        Badge background colour. Defaults to a deterministic colour from TIER_COLORS
        based on the team name hash.
    text_color:
        Initials text colour.

    Returns
    -------
    PIL.Image.Image
        RGBA square image with circle badge.
    """
    # Deterministic bg from team name when not specified
    if bg_color is None:
        palette = list(TIER_COLORS.values())
        idx = int(hashlib.md5(team_name.encode(), usedforsecurity=False).hexdigest()[:4], 16)
        bg_color = palette[idx % len(palette)]

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    margin = 2
    draw.ellipse(
        [(margin, margin), (size - margin, size - margin)],
        fill=(*bg_color, 255),
    )

    # Initials: up to 2 chars from word starts
    words = team_name.strip().split()
    if len(words) >= 2:
        initials = (words[0][0] + words[-1][0]).upper()
    else:
        initials = (team_name[:2]).upper()

    font_size = max(10, int(size * 0.35))
    font = load_font("bold", font_size)

    # Centre the text
    bbox = font.getbbox(initials)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]

    draw.text((tx, ty), initials, font=font, fill=(*text_color, 255))

    return img


def load_icon(name: str, display_size: int = ICON_DISPLAY_MD) -> Optional[Image.Image]:
    """Load a named icon PNG, resize to display_size × display_size.

    Parameters
    ----------
    name:
        Icon stem (e.g. ``"soccer"``).
    display_size:
        Target square size for rendering.

    Returns
    -------
    PIL.Image.Image or None
        RGBA image, or None if not found.
    """
    path = ICONS_DIR / f"{name}.png"
    if not path.exists():
        return None
    try:
        img = Image.open(path).convert("RGBA")
        img = img.resize((display_size, display_size), Image.LANCZOS)
        return img
    except Exception:
        return None


def paste_alpha(base: Image.Image, layer: Image.Image, xy: tuple[int, int]) -> None:
    """Composite an RGBA layer onto base using its alpha channel."""
    base.paste(layer, xy, mask=layer)
