"""P3-03 — Daily Digest Image Card Generator using Python Pillow.

Public API:
    generate_digest_card(picks) -> bytes   PNG bytes, ready for bot.send_photo()

Constraints (from brief):
    - Pillow only.  No external image services, no browser rendering.
    - Brand Bible: Carbon Black #0A0A0A, Orange gradient #F8C830→#E8571F,
      Signal White #F5F5F5, dark-mode-first.
    - 1080×1080px (Telegram optimal).
    - Max 5 matches (Miller's Law).  "+N more" if >5 active edges.
    - Font fallback: Liberation family from system when brand TTFs absent.
    - Graceful skip of logo assets when files are missing.
    - Zero exceptions escape — callers catch RuntimeError for text fallback.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ── Canvas ────────────────────────────────────────────────────────────────────
_W, _H = 1080, 1080
_PAD_X = 60  # left/right padding

# ── Brand colours ─────────────────────────────────────────────────────────────
_BG           = (10, 10, 10)        # #0A0A0A Carbon Black
_FG           = (245, 245, 245)     # #F5F5F5 Signal White
_MUTED        = (140, 140, 140)     # secondary/muted text
_ACCENT_START = (248, 200, 48)      # #F8C830 gradient start
_ACCENT_END   = (232, 87, 31)       # #E8571F gradient end
_ACCENT       = (248, 200, 48)      # single-colour accent (start)
_SEPARATOR    = (35, 35, 35)        # card separator / bar track

# ── Tier styling ──────────────────────────────────────────────────────────────
_TIER_COLOR: dict[str, tuple[int, int, int]] = {
    "diamond": (124, 246, 255),  # #7CF6FF cyan
    "gold":    (248, 200, 48),   # #F8C830 gold
    "silver":  (192, 192, 192),  # silver
    "bronze":  (205, 127, 50),   # bronze
}
_TIER_LABEL: dict[str, str] = {
    "diamond": "DIAMOND",
    "gold":    "GOLD",
    "silver":  "SILVER",
    "bronze":  "BRONZE",
}
# Representative composite score per tier (used for confidence bar when edge_score absent)
_TIER_SCORE: dict[str, int] = {
    "diamond": 88,
    "gold":    72,
    "silver":  58,
    "bronze":  44,
}

# ── Layout (all y-values are absolute pixels) ─────────────────────────────────
_MAX_CARDS   = 5
_HEADER_H    = 200   # header area height (y=0..200)
_CARDS_AREA  = 710   # total height for match cards (200..910)
_FOOTER_Y    = 910   # footer starts here

# ── Asset paths ───────────────────────────────────────────────────────────────
_BOT_DIR      = Path(__file__).parent
_LOGO_DIR     = _BOT_DIR / "assets" / "LOGO"
_FONTS_DIR    = _BOT_DIR / "assets" / "fonts"
_WORDMARK_PATH = _LOGO_DIR / "mzansiedge-wordmark-dark-transparent.png"
_AVATAR_PATH   = _LOGO_DIR / "bru-avatar-dark-background.png"

# ── Font paths ────────────────────────────────────────────────────────────────
# Brand fonts (optional — loaded from assets/fonts/ when present)
_BRAND_FONTS: dict[str, list[str]] = {
    "bold":      ["Outfit-Bold.ttf", "Outfit-SemiBold.ttf"],
    "regular":   ["WorkSans-Regular.ttf", "WorkSans-Medium.ttf"],
    "mono":      ["GeistMono-Regular.ttf", "GeistMono-Medium.ttf"],
    "mono_bold": ["GeistMono-Bold.ttf"],
}
# System fallbacks (Liberation family — ships on Ubuntu 20.04+)
_SYS_FONTS: dict[str, str] = {
    "bold":      "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "regular":   "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "mono":      "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "mono_bold": "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
}


# ── Font loader ───────────────────────────────────────────────────────────────

def _font(style: str, size: int) -> ImageFont.FreeTypeFont:
    """Load font by style+size with graceful fallback chain."""
    for name in _BRAND_FONTS.get(style, []):
        p = _FONTS_DIR / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    sys_path = _SYS_FONTS.get(style)
    if sys_path and Path(sys_path).exists():
        return ImageFont.truetype(sys_path, size)
    # Last resort: Pillow default
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _gradient_line(
    draw: ImageDraw.Draw,
    x0: int, y: int, x1: int,
    height: int = 4,
) -> None:
    """Draw a horizontal gradient bar from ACCENT_START → ACCENT_END."""
    w = x1 - x0
    if w <= 0:
        return
    sr, sg, sb = _ACCENT_START
    er, eg, eb = _ACCENT_END
    for i in range(w):
        t = i / w
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        draw.rectangle([(x0 + i, y), (x0 + i, y + height - 1)], fill=(r, g, b))


def _confidence_bar(
    draw: ImageDraw.Draw,
    x: int, y: int,
    width: int, height: int,
    pct: float,
    color: tuple[int, int, int],
) -> None:
    """Draw track + filled bar. pct is 0.0..1.0."""
    r = height // 2
    draw.rounded_rectangle([(x, y), (x + width, y + height)], radius=r, fill=_SEPARATOR)
    fill_w = max(height, int(width * max(0.0, min(1.0, pct))))
    draw.rounded_rectangle([(x, y), (x + fill_w, y + height)], radius=r, fill=color)


def _tier_badge_width(label: str, font: ImageFont.FreeTypeFont) -> int:
    """Return pixel width a tier badge will occupy."""
    bbox = font.getbbox(label)
    tw = bbox[2] - bbox[0]
    return tw + 28  # 14px padding each side


def _draw_tier_badge(
    draw: ImageDraw.Draw,
    x: int, y: int,
    label: str,
    color: tuple[int, int, int],
    font: ImageFont.FreeTypeFont,
) -> int:
    """Draw colored pill badge. Returns x right-edge (next draw position)."""
    bbox = font.getbbox(label)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_h, pad_v = 14, 8
    bw = tw + pad_h * 2
    bh = th + pad_v * 2
    draw.rounded_rectangle([(x, y), (x + bw, y + bh)], radius=bh // 2, fill=color)
    # Dark text on bright backgrounds, light on dark
    text_fill = (10, 10, 10) if (color[0] + color[1] + color[2]) > 400 else _FG
    draw.text((x + pad_h, y + pad_v - bbox[1]), label, font=font, fill=text_fill)
    return x + bw + 12  # 12px gap after badge


def _truncate(name: str, max_len: int = 20) -> str:
    """Truncate name with ellipsis."""
    return name if len(name) <= max_len else name[: max_len - 1] + "\u2026"


def _text_w(text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _load_asset(path: Path, max_w: int, max_h: int) -> Optional[Image.Image]:
    """Load image asset, thumbnail to fit, convert to RGBA. None on failure."""
    if not path.exists():
        return None
    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        return img
    except Exception:
        return None


def _paste_alpha(base: Image.Image, layer: Image.Image, xy: tuple[int, int]) -> None:
    """Composite RGBA layer onto base at xy using alpha channel."""
    base.paste(layer, xy, mask=layer)


def _pick(seed: str, n: int) -> int:
    """MD5-deterministic 0..(n-1). Same seed → same index across runs."""
    digest = hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()
    return int(digest[:4], 16) % n


# ── Card row renderer ─────────────────────────────────────────────────────────

def _draw_match_card(
    draw: ImageDraw.Draw,
    pick: dict,
    cy: int,
    card_h: int,
    f_badge: ImageFont.FreeTypeFont,
    f_team: ImageFont.FreeTypeFont,
    f_body: ImageFont.FreeTypeFont,
    f_odds: ImageFont.FreeTypeFont,
    f_conf: ImageFont.FreeTypeFont,
) -> None:
    """Draw one match card at vertical position cy."""
    tier = (
        (pick.get("display_tier") or pick.get("edge_rating") or "bronze")
        .lower()
    )
    color = _TIER_COLOR.get(tier, _TIER_COLOR["bronze"])
    tier_label = _TIER_LABEL.get(tier, "BRONZE")

    home_raw = pick.get("home_team") or "Home"
    away_raw = pick.get("away_team") or "Away"
    home = _truncate(home_raw)
    away = _truncate(away_raw)
    teams_text = f"{home} vs {away}"

    kickoff = (
        pick.get("kickoff") or pick.get("_bc_kickoff")
        or pick.get("_mm_kickoff") or ""
    )
    sport_emoji = pick.get("sport_emoji") or ""

    odds_val = float(pick.get("odds") or 0.0)
    odds_text = f"{odds_val:.2f}" if odds_val else ""

    # Confidence bar from composite/edge score
    score_raw = (
        pick.get("composite_score")
        or pick.get("edge_score")
        or _TIER_SCORE.get(tier, 50)
    )
    score = float(score_raw)
    pct = min(1.0, score / 100.0)
    conf_label = f"{int(score)}%"

    # ── Row 1: badge  |  teams  |  odds ──────────────────────────────────
    row1_y = cy + 14

    # Tier badge
    badge_right = _draw_tier_badge(draw, _PAD_X, row1_y, tier_label, color, f_badge)

    # Odds (right-aligned)
    odds_x = _W - _PAD_X
    if odds_text:
        draw.text(
            (odds_x, row1_y + 4),
            odds_text,
            font=f_odds,
            fill=color,
            anchor="ra",
        )
        odds_left = odds_x - _text_w(odds_text, f_odds) - 10
    else:
        odds_left = odds_x

    # Team names (clipped to available width)
    team_x = badge_right
    max_team_w = odds_left - team_x - 8
    # Truncate team text to fit
    full_text = teams_text
    while _text_w(full_text, f_team) > max_team_w and len(full_text) > 6:
        full_text = full_text[:-2] + "\u2026"
    draw.text((team_x, row1_y + 2), full_text, font=f_team, fill=_FG)

    # ── Row 2: sport emoji + kickoff ──────────────────────────────────────
    row2_y = cy + 62
    kickoff_parts = []
    if kickoff:
        kickoff_parts.append(kickoff)
    # sport_emoji often won't render in Liberation fonts; use text fallback
    body_text = "  ".join(kickoff_parts) if kickoff_parts else "Kickoff TBC"
    draw.text((_PAD_X, row2_y), body_text, font=f_body, fill=_MUTED)

    # ── Row 3: confidence bar + percentage ───────────────────────────────
    row3_y = cy + 94
    bar_w = 280
    bar_h = 10
    _confidence_bar(draw, _PAD_X, row3_y + 2, bar_w, bar_h, pct, color)
    draw.text(
        (_PAD_X + bar_w + 12, row3_y),
        conf_label,
        font=f_conf,
        fill=_MUTED,
    )

    # ── Separator ─────────────────────────────────────────────────────────
    sep_y = cy + card_h - 4
    draw.line([(0, sep_y), (_W, sep_y)], fill=_SEPARATOR, width=1)


# ── Header helper ─────────────────────────────────────────────────────────────

def _draw_header(
    img: Image.Image,
    draw: ImageDraw.Draw,
    n_visible: int,
    f_wordmark: ImageFont.FreeTypeFont,
    f_title: ImageFont.FreeTypeFont,
    f_subtitle: ImageFont.FreeTypeFont,
) -> int:
    """Draw header block. Returns y for cards start."""
    # Wordmark (try image, fall back to text)
    wordmark = _load_asset(_WORDMARK_PATH, 380, 68)
    if wordmark:
        wm_x = (_W - wordmark.width) // 2
        _paste_alpha(img, wordmark, (wm_x, 22))
        gradient_y = 22 + wordmark.height + 14
    else:
        draw.text((_W // 2, 30), "MZANSIEDGE", font=f_wordmark, fill=_ACCENT, anchor="mt")
        gradient_y = 96

    # Gradient accent line
    _gradient_line(draw, _PAD_X, gradient_y, _W - _PAD_X, height=4)

    # Section title
    title_y = gradient_y + 18
    draw.text((_W // 2, title_y), "TODAY'S EDGE PICKS", font=f_title, fill=_FG, anchor="mt")

    # Count sub-line
    sub_y = title_y + 50
    if n_visible > 0:
        sub = f"{n_visible} edge{'s' if n_visible != 1 else ''} active today"
    else:
        sub = "No edges active right now"
    draw.text((_W // 2, sub_y), sub, font=f_subtitle, fill=_MUTED, anchor="mt")

    # Thin separator before cards
    sep_y = sub_y + 38
    draw.line([(0, sep_y), (_W, sep_y)], fill=_SEPARATOR, width=1)

    return sep_y + 10


# ── Footer helper ─────────────────────────────────────────────────────────────

def _draw_footer(
    img: Image.Image,
    draw: ImageDraw.Draw,
    f_footer: ImageFont.FreeTypeFont,
) -> None:
    """Draw avatar + domain line in footer."""
    # B.R.U. avatar (bottom-right corner)
    avatar = _load_asset(_AVATAR_PATH, 72, 72)
    if avatar:
        av_x = _W - _PAD_X - avatar.width
        av_y = _H - 20 - avatar.height
        _paste_alpha(img, avatar, (av_x, av_y))

    # Domain line (bottom-left)
    draw.text((_PAD_X, _H - 38), "mzansiedge.co.za", font=f_footer, fill=_MUTED)


# ── Single-match card (AC-12 / P1P3-BUILD) ────────────────────────────────────

def generate_match_card(card_data: dict) -> bytes:
    """Generate a 1080×1080px branded card for a single structured match card.

    Accepts the dict produced by ``card_pipeline.build_card_data()``.
    Falls back to ``generate_digest_card([card_data])`` internally so all
    Brand Bible v3 tokens (colors, fonts, confidence meter) are preserved.

    Parameters
    ----------
    card_data:
        Structured card dict.  Key fields used:

        * ``matchup`` / ``home_team``, ``away_team``
        * ``tier`` — diamond/gold/silver/bronze (maps to tier header color)
        * ``odds`` (float) — best decimal odds
        * ``confidence`` (float, 0-100) — confidence meter fill
        * ``kickoff`` — pre-formatted kickoff string
        * ``sport`` (optional) — sport key

    Returns
    -------
    bytes
        Raw PNG bytes suitable for ``bot.send_photo()``.

    Raises
    ------
    RuntimeError
        On any Pillow or asset error.  Callers catch and fall back to text.
    """
    # Normalise card_data into the pick dict format used by _draw_match_card
    pick = {
        "home_team": card_data.get("home_team") or (card_data.get("matchup", "") or "Home").split(" vs ")[0],
        "away_team": card_data.get("away_team") or (card_data.get("matchup", "") or "Away").split(" vs ")[-1],
        "display_tier": card_data.get("tier", "bronze"),
        "edge_rating": card_data.get("tier", "bronze"),
        "odds": card_data.get("odds", 0.0),
        "composite_score": card_data.get("confidence", 0.0),
        "edge_score": card_data.get("confidence", 0.0),
        "kickoff": card_data.get("kickoff", ""),
        "_bc_kickoff": card_data.get("kickoff", ""),
        "sport_emoji": _SPORT_EMOJI_MAP.get(card_data.get("sport", ""), "🏅"),
    }
    return generate_digest_card([pick])


# ── Sport emoji lookup (used by generate_match_card) ──────────────────────────
_SPORT_EMOJI_MAP: dict[str, str] = {
    "soccer": "⚽", "football": "⚽",
    "rugby": "🏉", "rugby_union": "🏉", "rugby_league": "🏉",
    "cricket": "🏏",
    "mma": "🥊", "boxing": "🥊", "combat": "🥊",
    "basketball": "🏀", "tennis": "🎾",
}


# ── Main entry point ─────────────────────────────────────────────────────────

def generate_digest_card(picks: list[dict]) -> bytes:
    """Generate 1080×1080px PNG daily digest card.

    Parameters
    ----------
    picks:
        List of tip dicts.  Used fields:

        * ``display_tier`` / ``edge_rating`` — diamond/gold/silver/bronze
        * ``home_team``, ``away_team``
        * ``kickoff`` / ``_bc_kickoff``
        * ``sport_emoji``
        * ``odds`` (float) — best decimal odds
        * ``composite_score`` / ``edge_score`` (0-100, optional)

    Returns
    -------
    bytes
        Raw PNG bytes, suitable for ``bot.send_photo()``.

    Raises
    ------
    RuntimeError
        On any Pillow or asset error.  Callers catch and fall back to text.
    """
    try:
        visible = picks[:_MAX_CARDS]
        overflow = max(0, len(picks) - _MAX_CARDS)

        # ── Font set ─────────────────────────────────────────────────────
        f_wordmark = _font("bold", 48)
        f_title    = _font("bold", 36)
        f_subtitle = _font("regular", 24)
        f_badge    = _font("bold", 20)
        f_team     = _font("bold", 34)
        f_body     = _font("regular", 24)
        f_odds     = _font("mono_bold", 32)
        f_conf     = _font("mono", 21)
        f_overflow = _font("bold", 26)
        f_footer   = _font("regular", 20)

        # ── Canvas ───────────────────────────────────────────────────────
        img  = Image.new("RGB", (_W, _H), _BG)
        draw = ImageDraw.Draw(img)

        # ── Header ───────────────────────────────────────────────────────
        cards_y = _draw_header(img, draw, len(visible), f_wordmark, f_title, f_subtitle)

        # ── No-edges state ────────────────────────────────────────────────
        if not visible:
            draw.text(
                (_W // 2, _H // 2 - 20),
                "No Edges today.",
                font=f_title,
                fill=_FG,
                anchor="mm",
            )
            draw.text(
                (_W // 2, _H // 2 + 30),
                "Check back closer to kickoff.",
                font=f_subtitle,
                fill=_MUTED,
                anchor="mm",
            )
            _draw_footer(img, draw, f_footer)
            return _to_bytes(img)

        # ── Distribute card height evenly ─────────────────────────────────
        available_h = _FOOTER_Y - cards_y - 20  # 20px gap before footer
        card_h = max(100, available_h // max(len(visible), 1))

        # ── Match cards ───────────────────────────────────────────────────
        for i, pick in enumerate(visible):
            cy = cards_y + i * card_h
            _draw_match_card(
                draw, pick, cy, card_h,
                f_badge, f_team, f_body, f_odds, f_conf,
            )

        # ── "+N more" indicator ───────────────────────────────────────────
        if overflow > 0:
            ov_y = cards_y + len(visible) * card_h + 8
            draw.text(
                (_W // 2, ov_y),
                f"+{overflow} more",
                font=f_overflow,
                fill=_ACCENT,
                anchor="mt",
            )

        # ── Footer ────────────────────────────────────────────────────────
        _draw_footer(img, draw, f_footer)

        return _to_bytes(img)

    except Exception as exc:
        raise RuntimeError(f"image_card generation failed: {exc}") from exc


def _to_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
