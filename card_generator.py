"""IMG-W1 — Pillow Image Card Renderer for MzansiEdge.

Public API
----------
    generate_card(card_type: str, data) -> bytes

Card types
----------
    edge_digest   — Up to 5 tips: tier badge, confidence bar, EV, kickoff, sport icon
    my_matches    — Variable height: form dots, team names, kickoff times
    edge_detail   — Large tier badge, pick arrow, odds comparison, signal dots, analysis
    match_detail  — Key stats boxes, form ribbons, H2H, injuries, odds

Constraints
-----------
    - Width 1280px, dynamic height (max 2560px), PNG lossless
    - Uses ONLY card_templates.py colours/fonts/constants (no hardcoded values)
    - Uses ONLY card_pipeline.py data fields (no DB queries, no LLM)
    - Graceful degradation on missing fields — never crashes
    - <500ms generation time per card
"""
from __future__ import annotations

import functools
import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

import card_templates as T
from logo_cache import get_logo


@functools.lru_cache(maxsize=64)
def _font(style: str, size: int) -> ImageFont.FreeTypeFont:
    """Cached font loader — avoids re-parsing font files on every row."""
    return T.load_font(style, size)

# ── Canvas dimensions ─────────────────────────────────────────────────────────
_CARD_W: int = 1280          # output card width (px) — always constant
_MAX_H: int = 2560           # maximum card height (px)

# ── Layout constants (derived from card_templates) ────────────────────────────
_PAD_X: int = T.CARD_PADDING_X      # 56px left/right inner padding
_PAD_Y: int = T.CARD_PADDING_Y      # 48px top/bottom inner padding

# Header and footer
_HEADER_H: int = 190        # header block height
_FOOTER_H: int = 60         # footer block height

# Per-card-row heights for list cards
_DIGEST_ROW_H: int = 152    # edge_digest row height
_MATCHES_ROW_H: int = 128   # my_matches row height

# Radii reused from templates
_CARD_R: int = T.CARD_RADIUS        # 12 — card rounded corners
_BADGE_R: int = T.BADGE_RADIUS      # 20 — pill badge corners
_BAR_R: int = T.BAR_RADIUS          # 4  — confidence bar corners

# Icon sizes from templates
_ICON_SM: int = T.ICON_DISPLAY_SM   # 24
_ICON_MD: int = T.ICON_DISPLAY_MD   # 32

# Dot size for form indicators
_DOT_R: int = 8    # radius of W/D/L dot

# Content box styling for match_detail stats boxes
_BOX_W: int = 280
_BOX_H: int = 90

# Signal dot radius
_SIG_DOT_R: int = 7

# ── Digest portrait dimensions (edge_digest — 720×1280 Telegram-optimised) ───
# W1R2: 720px width avoids Telegram photo compression (max full-res).
# Compact 110px rows allow MAX_VISIBLE_PICKS=8 to fit in a 1280px canvas.
#
# W3 Button Layout (stacked vertical, document for Telegram integration):
#   Row 1: [💎 <tier>] [edge_detail callback per pick]
#   Row 2: [📲 Bet on <bookmaker> →] (URL, best-odds bookmaker)
#   Row 3: [🔄 Refresh] [↩️ Back]
#   Max 2 buttons per row (PTB mobile constraint).
_DIGEST_W: int = 720            # portrait width — Telegram max full-res
_DIGEST_MAX_H: int = 3600       # max height for digest canvas
_DIGEST_PAD_X: int = 40         # left/right inner padding
_DIGEST_STATS_H: int = 100      # stats bar height (LAST 10 / 7D ROI / YESTERDAY)
_DIGEST_TIER_HDR_H: int = 52    # tier section header height
_DIGEST_PICK_H: int = 120       # pick row height — card surface + gaps (100-120px range)
_DIGEST_FOOTER_H: int = 72      # digest footer height
_DIGEST_HEADER_H_EST: int = 155 # estimated header height for canvas pre-sizing
_TIER_ORDER: list[str] = ["diamond", "gold", "silver", "bronze"]

# Visible pick cap — overrides T.MAX_CARDS_PER_DIGEST for digest card
MAX_VISIBLE_PICKS: int = 8

# ── League display names (slug → emoji + label) ───────────────────────────────
_LEAGUE_DISPLAY: dict[str, str] = {
    "psl":                    "🇿🇦 PSL",
    "epl":                    "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL",
    "premier_league":         "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL",
    "soccer_epl":             "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL",
    "champions_league":       "⭐ UCL",
    "soccer_uefa_champs_league": "⭐ UCL",
    "la_liga":                "🇪🇸 La Liga",
    "soccer_spain_la_liga":   "🇪🇸 La Liga",
    "bundesliga":             "🇩🇪 Bundesliga",
    "soccer_germany_bundesliga": "🇩🇪 Bundesliga",
    "serie_a":                "🇮🇹 Serie A",
    "soccer_italy_serie_a":   "🇮🇹 Serie A",
    "ligue_1":                "🇫🇷 Ligue 1",
    "ligue1":                 "🇫🇷 Ligue 1",
    "soccer_france_ligue_one":"🇫🇷 Ligue 1",
    "rugby_championship":     "🏉 Rugby Champ",
    "six_nations":            "🏉 Six Nations",
    "rugbyunion_six_nations": "🏉 Six Nations",
    "urc":                    "🏉 URC",
    "super_rugby":            "🏉 Super Rugby",
    "currie_cup":             "🏉 Currie Cup",
    "sa20":                   "🏏 SA20",
    "ipl":                    "🏏 IPL",
    "t20_world_cup":          "🏏 T20 WC",
    "cricket_t20_world_cup":  "🏏 T20 WC",
    "test_cricket":           "🏏 Test",
    "mma_mixed_martial_arts": "🥊 UFC/MMA",
    "boxing_boxing":          "🥊 Boxing",
    "mma":                    "🥊 MMA",
    "boxing":                 "🥊 Boxing",
    "nba":                    "🏀 NBA",
}


# ── Drawing helpers ────────────────────────────────────────────────────────────

def _to_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes (lossless)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _canvas(height: int) -> tuple[Image.Image, ImageDraw.Draw]:
    """Create a new RGBA canvas with BG_PRIMARY fill."""
    height = min(height, _MAX_H)
    img = Image.new("RGB", (_CARD_W, height), T.BG_PRIMARY)
    draw = ImageDraw.Draw(img)
    return img, draw


def _trunc(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "\u2026"


def _text_w(text: str, font: ImageFont.FreeTypeFont) -> int:
    """Pixel width of text string."""
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _text_h(font: ImageFont.FreeTypeFont) -> int:
    """Approximate line height for a font."""
    bbox = font.getbbox("Ay")
    return bbox[3] - bbox[1]


def _gradient_line(
    draw: ImageDraw.Draw,
    x0: int, y: int, x1: int,
    height: int = 3,
) -> None:
    """Horizontal gradient line from GRADIENT_START to GRADIENT_END."""
    w = x1 - x0
    if w <= 0:
        return
    sr, sg, sb = T.GRADIENT_START
    er, eg, eb = T.GRADIENT_END
    for i in range(w):
        t = i / max(w - 1, 1)
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        draw.rectangle([(x0 + i, y), (x0 + i, y + height - 1)], fill=(r, g, b))


def _confidence_bar(
    draw: ImageDraw.Draw,
    x: int, y: int,
    width: int,
    pct: float,
    color: tuple[int, int, int],
) -> None:
    """Draw confidence bar track + fill."""
    h = T.CONF_BAR_HEIGHT
    r = _BAR_R
    draw.rounded_rectangle([(x, y), (x + width, y + h)], radius=r, fill=T.BG_ELEVATED)
    fill_w = max(h, int(width * max(0.0, min(1.0, pct))))
    draw.rounded_rectangle([(x, y), (x + fill_w, y + h)], radius=r, fill=color)


def _tier_badge(
    draw: ImageDraw.Draw,
    x: int, y: int,
    label: str,
    color: tuple[int, int, int],
    font: ImageFont.FreeTypeFont,
) -> int:
    """Draw colored pill badge. Returns x right-edge."""
    bbox = font.getbbox(label)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    bw = tw + T.BADGE_PAD_H * 2
    bh = th + T.BADGE_PAD_V * 2
    draw.rounded_rectangle([(x, y), (x + bw, y + bh)], radius=_BADGE_R, fill=color)
    lum = color[0] * 299 + color[1] * 587 + color[2] * 114
    text_fill = T.BG_PRIMARY if lum > 128000 else T.TEXT_PRIMARY
    tx = x + T.BADGE_PAD_H - bbox[0]
    ty = y + T.BADGE_PAD_V - bbox[1]
    draw.text((tx, ty), label, font=font, fill=text_fill)
    return x + bw + 12


def _form_dot(
    draw: ImageDraw.Draw,
    cx: int, cy: int,
    result: str,
) -> None:
    """Draw a W/D/L dot at (cx, cy)."""
    if result == "W":
        fill = T.COLOR_SUCCESS
    elif result == "D":
        fill = T.COLOR_WARNING
    else:
        fill = T.COLOR_ERROR
    r = _DOT_R
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=fill)


def _form_row(
    draw: ImageDraw.Draw,
    x: int, cy: int,
    form: list[str],
) -> int:
    """Draw up to 5 form dots starting at x. Returns x right-edge."""
    for i, result in enumerate(form[:5]):
        _form_dot(draw, x + _DOT_R, cy, result)
        x += _DOT_R * 2 + 4
    return x


def _get_team_logo(team_name: str, sport: str, size: int = 36) -> Image.Image:
    """Return a team logo at size×size RGBA.

    Tries logo_cache.get_logo() first (cache-only, no API).
    Falls back to T.render_team_badge() on miss or error.
    """
    try:
        path = get_logo(team_name, sport)
        if path and path.exists():
            return Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        pass
    return T.render_team_badge(team_name, size=size)


def _draw_wordmark(img: Image.Image, draw: ImageDraw.Draw, y: int, font: ImageFont.FreeTypeFont) -> int:
    """Draw logo wordmark. Returns y-bottom of the logo area."""
    wordmark = None
    if T.WORDMARK_PATH.exists():
        try:
            wm = Image.open(T.WORDMARK_PATH).convert("RGBA")
            target_h = 52
            ratio = target_h / wm.height
            target_w = int(wm.width * ratio)
            wm = wm.resize((target_w, target_h), Image.LANCZOS)
            wm_x = (_CARD_W - wm.width) // 2
            T.paste_alpha(img, wm, (wm_x, y))
            wordmark = wm
        except Exception:
            wordmark = None

    if wordmark is None:
        draw.text(
            (_CARD_W // 2, y + 10),
            "MZANSIEDGE",
            font=font,
            fill=T.GOLD,
            anchor="mt",
        )
        return y + 52
    return y + wordmark.height


def _draw_header(
    img: Image.Image,
    draw: ImageDraw.Draw,
    title: str,
    subtitle: str,
) -> int:
    """Draw branded header block. Returns y for first content row."""
    y = _PAD_Y // 2

    f_wordmark = T.load_font("bold", 38)
    f_title = T.load_font("bold", 30)
    f_sub = T.load_font("regular", 22)

    logo_bottom = _draw_wordmark(img, draw, y, f_wordmark)
    grad_y = logo_bottom + 10
    _gradient_line(draw, _PAD_X, grad_y, _CARD_W - _PAD_X)

    title_y = grad_y + 16
    draw.text((_CARD_W // 2, title_y), title, font=f_title, fill=T.TEXT_PRIMARY, anchor="mt")

    sub_y = title_y + 38
    draw.text((_CARD_W // 2, sub_y), subtitle, font=f_sub, fill=T.TEXT_SECONDARY, anchor="mt")

    sep_y = sub_y + 32
    draw.line([(0, sep_y), (_CARD_W, sep_y)], fill=T.SEPARATOR, width=1)

    return sep_y + 12


def _draw_footer(img: Image.Image, draw: ImageDraw.Draw, y: int) -> None:
    """Draw avatar + domain line in footer area."""
    f_footer = T.load_font("regular", 18)

    avatar = None
    if T.AVATAR_PATH.exists():
        try:
            av_img = Image.open(T.AVATAR_PATH).convert("RGBA")
            av_img.thumbnail((52, 52), Image.LANCZOS)
            av_x = _CARD_W - _PAD_X - av_img.width
            av_y = y + (_FOOTER_H - av_img.height) // 2
            T.paste_alpha(img, av_img, (av_x, av_y))
        except Exception:
            pass

    draw.text(
        (_PAD_X, y + _FOOTER_H // 2),
        "mzansiedge.co.za",
        font=f_footer,
        fill=T.TEXT_MUTED,
        anchor="lm",
    )


def _draw_separator_line(draw: ImageDraw.Draw, y: int) -> None:
    """Draw a full-width separator line."""
    draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)


def _sport_key_for(data: dict) -> str:
    """Extract sport key from a tip/game dict."""
    return (
        data.get("sport_key")
        or data.get("sport")
        or ""
    ).lower()


def _tier_for(data: dict) -> str:
    """Extract normalized tier string from a tip/card dict."""
    return (
        (data.get("display_tier") or data.get("edge_rating") or data.get("tier") or "bronze")
        .lower()
        .strip()
    )


def _kickoff_for(data: dict) -> str:
    """Extract kickoff display string from a tip/game dict."""
    return (
        data.get("kickoff")
        or data.get("kick_off")
        or data.get("_bc_kickoff")
        or data.get("_mm_kickoff")
        or ""
    )


def _league_display(raw: str) -> str:
    """Map raw league slug to display label with flag emoji.

    Tries exact match first, then substring, then formats the raw string.
    """
    if not raw:
        return ""
    key = raw.lower().strip().replace(" ", "_").replace("-", "_")
    if key in _LEAGUE_DISPLAY:
        return _LEAGUE_DISPLAY[key]
    for slug, label in _LEAGUE_DISPLAY.items():
        if slug in key or key in slug:
            return label
    # Fall back: uppercase short labels, title-case longer ones
    return raw.upper() if len(raw) <= 5 else raw.replace("_", " ").title()


# ── Digest portrait helpers ───────────────────────────────────────────────────

def _digest_canvas(height: int) -> tuple[Image.Image, ImageDraw.Draw]:
    """Create canvas at digest portrait width (1080px)."""
    height = min(height, _DIGEST_MAX_H)
    img = Image.new("RGB", (_DIGEST_W, height), T.BG_PRIMARY)
    draw = ImageDraw.Draw(img)
    return img, draw


def _draw_digest_header(
    img: Image.Image,
    draw: ImageDraw.Draw,
    title: str,
    subtitle: str,
) -> int:
    """Draw branded header at 1080px width. Returns y for first content row."""
    y = 20
    cx = _DIGEST_W // 2
    f_wordmark = _font("bold", 32)
    f_title = _font("bold", 26)
    f_sub = _font("regular", 20)

    logo_bottom = y + 52
    if T.WORDMARK_PATH.exists():
        try:
            wm = Image.open(T.WORDMARK_PATH).convert("RGBA")
            target_h = 48
            ratio = target_h / wm.height
            wm = wm.resize((int(wm.width * ratio), target_h), Image.LANCZOS)
            T.paste_alpha(img, wm, ((_DIGEST_W - wm.width) // 2, y))
            logo_bottom = y + wm.height
        except Exception:
            draw.text((cx, y + 10), "MZANSIEDGE", font=f_wordmark, fill=T.GOLD, anchor="mt")
    else:
        draw.text((cx, y + 10), "MZANSIEDGE", font=f_wordmark, fill=T.GOLD, anchor="mt")

    grad_y = logo_bottom + 8
    _gradient_line(draw, _DIGEST_PAD_X, grad_y, _DIGEST_W - _DIGEST_PAD_X)
    title_y = grad_y + 14
    draw.text((cx, title_y), title, font=f_title, fill=T.TEXT_PRIMARY, anchor="mt")
    sub_y = title_y + 34
    draw.text((cx, sub_y), subtitle, font=f_sub, fill=T.TEXT_SECONDARY, anchor="mt")
    sep_y = sub_y + 28
    draw.line([(0, sep_y), (_DIGEST_W, sep_y)], fill=T.SEPARATOR, width=1)
    return sep_y + 10


def _draw_digest_stats_bar(draw: ImageDraw.Draw, y: int, stats_summary: dict) -> int:
    """Draw LAST 10 / 7D ROI / YESTERDAY stats bar. Returns y below bar."""
    last_10 = str(stats_summary.get("last_10") or "—")
    roi_7d = str(stats_summary.get("roi_7d") or "—")
    yesterday = str(stats_summary.get("yesterday") or "—")
    f_label = _font("regular", 16)
    f_value = _font("bold", 28)
    col_w = _DIGEST_W // 3
    for i, (label, value) in enumerate((
        ("LAST 10", last_10),
        ("7D ROI", roi_7d),
        ("YESTERDAY", yesterday),
    )):
        cx = col_w * i + col_w // 2
        draw.text((cx, y + 14), label, font=f_label, fill=T.TEXT_MUTED, anchor="mt")
        val_color = T.COLOR_SUCCESS if value.startswith("+") else T.TEXT_PRIMARY
        draw.text((cx, y + 38), value, font=f_value, fill=val_color, anchor="mt")
        if i < 2:
            div_x = col_w * (i + 1)
            draw.line(
                [(div_x, y + 10), (div_x, y + _DIGEST_STATS_H - 10)],
                fill=T.BG_BORDER, width=1,
            )
    draw.line([(0, y + _DIGEST_STATS_H), (_DIGEST_W, y + _DIGEST_STATS_H)],
              fill=T.SEPARATOR, width=1)
    return y + _DIGEST_STATS_H + 8


def _draw_digest_tier_header(draw: ImageDraw.Draw, y: int, tier: str, count: int = 0) -> int:
    """Draw centered tier section header with emoji + flanking lines. Returns y below."""
    color = T.TIER_COLORS.get(tier, T.TIER_COLORS["bronze"])
    label = T.TIER_LABELS.get(tier, "BRONZE")
    emoji = T.TIER_EMOJIS.get(tier, "")
    f = _font("bold", 18)
    base = f"{label} EDGE ({count})" if count else f"{label} EDGE"
    text = f"{emoji} {base}" if emoji else base
    tw = _text_w(text, f)
    th = _text_h(f)
    cx = _DIGEST_W // 2
    ty = y + (_DIGEST_TIER_HDR_H - th) // 2
    line_y = ty + th // 2
    tx = cx - tw // 2
    rx = tx + tw
    if tx > _DIGEST_PAD_X + 8:
        draw.line([(_DIGEST_PAD_X, line_y), (tx - 10, line_y)], fill=color, width=2)
    if rx < _DIGEST_W - _DIGEST_PAD_X - 8:
        draw.line([(rx + 10, line_y), (_DIGEST_W - _DIGEST_PAD_X, line_y)], fill=color, width=2)
    draw.text((tx, ty), text, font=f, fill=color)
    return y + _DIGEST_TIER_HDR_H


def _draw_digest_pick_row(
    img: Image.Image,
    draw: ImageDraw.Draw,
    tip: dict,
    cy: int,
    is_last: bool,
) -> None:
    """Design-faithful 120px pick row — IMG-W1R3 3-line layout.

    Row 1 (cy+10): 32px logos + matchup text (17px bold) — NO odds
    Row 2 (cy+48): league pill + ⏰ kickoff + 📺 channel
    Row 3 (cy+76): Pick: TEAM (green) | odds pill | EV: +N% | form dots (right)
    """
    tier = _tier_for(tip)
    color = T.TIER_COLORS.get(tier, T.TIER_COLORS["bronze"])
    sport = (tip.get("sport_key") or tip.get("sport") or "").lower()

    home = tip.get("home_team") or "Home"
    away = tip.get("away_team") or "Away"
    ev = float(tip.get("ev_pct") or tip.get("ev") or 0)
    odds_val = float(tip.get("odds") or tip.get("recommended_odds") or 0)
    kickoff = _kickoff_for(tip)
    league_raw = tip.get("league") or tip.get("league_display") or tip.get("league_key") or ""
    league = _league_display(league_raw)

    # TV channel — try all possible keys
    broadcast_raw = (
        tip.get("_bc_broadcast") or
        tip.get("broadcast_channel") or
        tip.get("broadcast") or
        tip.get("tv_channel") or
        tip.get("dstv_channel") or ""
    )
    # Strip the "📺 " prefix if already present to avoid doubling
    broadcast = broadcast_raw[3:] if broadcast_raw.startswith("📺 ") else broadcast_raw

    # Resolve pick team
    pick_team = tip.get("pick_team") or tip.get("pick") or ""
    if not pick_team:
        outcome = (tip.get("outcome") or tip.get("bet_type") or "").lower().strip()
        if outcome in ("home", "1", "home win"):
            pick_team = home
        elif outcome in ("away", "2", "away win"):
            pick_team = away
        elif outcome in ("draw", "x", "tie"):
            pick_team = "Draw"
        else:
            pick_team = tip.get("outcome") or ""

    # Form data — use pick side's form if available
    pick_is_home = (pick_team or "").lower() == home.lower()
    form_list = (tip.get("home_form") if pick_is_home else tip.get("away_form")) or []
    if not form_list:
        form_list = tip.get("home_form") or []

    # ── Card surface + left accent ─────────────────────────────────────────────
    card_x0 = _DIGEST_PAD_X
    card_x1 = _DIGEST_W - _DIGEST_PAD_X
    card_y0 = cy + 4
    card_y1 = cy + _DIGEST_PICK_H - 4

    draw.rounded_rectangle([(card_x0, card_y0), (card_x1, card_y1)], radius=8, fill=T.BG_CARD)
    draw.rectangle([(card_x0, card_y0), (card_x0 + 4, card_y1)], fill=color)

    cx0 = card_x0 + 4 + 10
    cx1 = card_x1 - 10

    logo_size = 32
    f_team = _font("bold", 17)
    f_meta = _font("regular", 13)
    f_pick = _font("bold", 14)
    f_odds = _font("mono_bold", 16)
    f_ev   = _font("bold", 13)
    f_pill = _font("bold", 11)

    # ── Row 1 (cy+10): logos + matchup (NO odds) ──────────────────────────────
    y1 = card_y0 + 10

    home_path = get_logo(home, sport)
    away_path = get_logo(away, sport)

    if home_path and home_path.exists():
        print(f"[LOGO] REAL: {home} ({sport})")
        try:
            logo = Image.open(home_path).convert("RGBA").resize((logo_size, logo_size), Image.LANCZOS)
            T.paste_alpha(img, logo, (cx0, y1))
        except Exception:
            try:
                T.paste_alpha(img, T.render_team_badge(home, size=logo_size), (cx0, y1))
            except Exception:
                pass
    else:
        print(f"[LOGO] FALLBACK: {home} ({sport})")
        try:
            T.paste_alpha(img, T.render_team_badge(home, size=logo_size), (cx0, y1))
        except Exception:
            pass

    if away_path and away_path.exists():
        print(f"[LOGO] REAL: {away} ({sport})")
        try:
            logo = Image.open(away_path).convert("RGBA").resize((logo_size, logo_size), Image.LANCZOS)
            T.paste_alpha(img, logo, (cx0 + logo_size + 4, y1))
        except Exception:
            try:
                T.paste_alpha(img, T.render_team_badge(away, size=logo_size), (cx0 + logo_size + 4, y1))
            except Exception:
                pass
    else:
        print(f"[LOGO] FALLBACK: {away} ({sport})")
        try:
            T.paste_alpha(img, T.render_team_badge(away, size=logo_size), (cx0 + logo_size + 4, y1))
        except Exception:
            pass

    # Matchup text — full available width (no odds competing)
    team_x = cx0 + logo_size * 2 + 8
    avail_w = cx1 - team_x - 4
    max_len = 16
    while max_len > 5 and _text_w(
        f"{_trunc(home, max_len)} vs {_trunc(away, max_len)}", f_team
    ) > avail_w:
        max_len -= 1
    matchup_str = f"{_trunc(home, max_len)} vs {_trunc(away, max_len)}"
    team_y = y1 + max(0, (logo_size - _text_h(f_team)) // 2)
    draw.text((team_x, team_y), matchup_str, font=f_team, fill=T.TEXT_PRIMARY)

    # ── Row 2 (cy+48): league pill + ⏰ kickoff + 📺 channel ──────────────────
    y2 = card_y0 + 48
    meta_x = cx0

    if league:
        try:
            pb = f_pill.getbbox(league)
            pw = (pb[2] - pb[0]) + 12
            ph = (pb[3] - pb[1]) + 6
            draw.rounded_rectangle([(meta_x, y2), (meta_x + pw, y2 + ph)], radius=4, fill=T.BG_ELEVATED)
            draw.rounded_rectangle([(meta_x, y2), (meta_x + pw, y2 + ph)], radius=4, outline=color, width=1)
            draw.text((meta_x + 6 - pb[0], y2 + 3 - pb[1]), league, font=f_pill, fill=color)
            meta_x += pw + 8
        except Exception:
            pass

    if kickoff:
        ko_text = f"⏰ {kickoff}"
        draw.text((meta_x, y2 + 1), ko_text, font=f_meta, fill=T.TEXT_SECONDARY)
        meta_x += _text_w(ko_text, f_meta) + 10

    if broadcast:
        draw.text((meta_x, y2 + 1), f"📺 {broadcast}", font=f_meta, fill=T.TEXT_SECONDARY)

    # ── Row 3 (cy+76): Pick: TEAM (green) | odds pill | EV: +N% | form dots ──
    y3 = card_y0 + 76
    pos_x = cx0

    # "Pick:" label in muted text
    pick_label = "Pick: "
    draw.text((pos_x, y3), pick_label, font=f_pick, fill=T.TEXT_MUTED)
    pos_x += _text_w(pick_label, f_pick)

    # Pick team name in GREEN
    if pick_team:
        pt = _trunc(pick_team, 14)
        draw.text((pos_x, y3), pt, font=f_pick, fill=T.COLOR_SUCCESS)
        pos_x += _text_w(pt, f_pick) + 10

    # Odds pill (BG_ELEVATED background, primary white text)
    if odds_val > 0:
        odds_text = f"{odds_val:.2f}"
        ob = f_odds.getbbox(odds_text)
        ow = (ob[2] - ob[0]) + 10
        oh = (ob[3] - ob[1]) + 4
        draw.rounded_rectangle(
            [(pos_x, y3 - 2), (pos_x + ow, y3 - 2 + oh)],
            radius=4, fill=T.BG_ELEVATED,
        )
        draw.text(
            (pos_x + 5 - ob[0], y3 - 2 + 2 - ob[1]),
            odds_text, font=f_odds, fill=T.TEXT_PRIMARY,
        )
        pos_x += ow + 10

    # EV% label
    if ev != 0:
        ev_text = f"EV: +{ev:.1f}%" if ev > 0 else f"EV: {ev:.1f}%"
        ev_fill = T.COLOR_SUCCESS if ev > 0 else T.COLOR_ERROR
        draw.text((pos_x, y3), ev_text, font=f_ev, fill=ev_fill)

    # Form dots — right-aligned, 10px circles (5px radius), 3px gaps
    if form_list:
        dot_r = 5
        dot_gap = 3
        n_dots = min(len(form_list), 5)
        dots_w = n_dots * (dot_r * 2) + max(0, n_dots - 1) * dot_gap
        dx = cx1 - dots_w
        dot_cy = y3 + dot_r + 2
        for res in form_list[:5]:
            if res == "W":
                dot_fill = T.COLOR_SUCCESS
            elif res == "D":
                dot_fill = T.TEXT_SECONDARY  # gray for draws
            else:
                dot_fill = T.COLOR_ERROR
            draw.ellipse([(dx, dot_cy - dot_r), (dx + dot_r * 2, dot_cy + dot_r)], fill=dot_fill)
            dx += dot_r * 2 + dot_gap


def _draw_digest_footer(img: Image.Image, draw: ImageDraw.Draw, y: int) -> None:
    """Draw footer at 1080px width."""
    f_footer = _font("regular", 18)
    if T.AVATAR_PATH.exists():
        try:
            av_img = Image.open(T.AVATAR_PATH).convert("RGBA")
            av_img.thumbnail((48, 48), Image.LANCZOS)
            T.paste_alpha(img, av_img, (
                _DIGEST_W - _DIGEST_PAD_X - av_img.width,
                y + (_DIGEST_FOOTER_H - av_img.height) // 2,
            ))
        except Exception:
            pass
    draw.text(
        (_DIGEST_PAD_X, y + _DIGEST_FOOTER_H // 2),
        "mzansiedge.co.za",
        font=f_footer,
        fill=T.TEXT_MUTED,
        anchor="lm",
    )


def compute_digest_stats() -> dict:
    """Compute digest stats from edge_results DB. Returns dict for stats_summary.

    Queries scrapers/odds.db for:
    - LAST 10: last 10 settled results (W-L format)
    - 7D ROI: ROI on R100 stake per tip over last 7 days
    - YESTERDAY: settled results from yesterday (W-L format)

    Returns empty dict on any error so callers degrade gracefully.
    """
    from pathlib import Path as _Path
    from datetime import date as _date, timedelta as _td
    import sqlite3 as _sqlite3

    db_path = _Path(__file__).parent.parent / "scrapers" / "odds.db"
    if not db_path.exists():
        return {}

    try:
        conn = _sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = _sqlite3.Row

        # LAST 10 settled
        last_10 = conn.execute(
            "SELECT result FROM edge_results WHERE result IN ('hit','miss')"
            " ORDER BY settled_at DESC LIMIT 10"
        ).fetchall()
        w10 = sum(1 for r in last_10 if r["result"] == "hit")
        l10 = sum(1 for r in last_10 if r["result"] == "miss")
        last_10_str = f"{w10}-{l10}" if (w10 + l10) > 0 else "—"

        # YESTERDAY
        yesterday = (_date.today() - _td(days=1)).isoformat()
        yrows = conn.execute(
            "SELECT result FROM edge_results WHERE result IN ('hit','miss')"
            " AND DATE(settled_at) = ?",
            (yesterday,),
        ).fetchall()
        yw = sum(1 for r in yrows if r["result"] == "hit")
        yl = sum(1 for r in yrows if r["result"] == "miss")
        yesterday_str = f"{yw}-{yl}" if (yw + yl) > 0 else "—"

        # 7D ROI (R100 per tip)
        seven_ago = (_date.today() - _td(days=7)).isoformat()
        roi_rows = conn.execute(
            "SELECT recommended_odds, result FROM edge_results"
            " WHERE result IN ('hit','miss') AND DATE(settled_at) >= ?",
            (seven_ago,),
        ).fetchall()
        roi_str = "—"
        if roi_rows:
            stake = len(roi_rows) * 100
            returns_ = sum(
                row["recommended_odds"] * 100 if row["result"] == "hit" else 0
                for row in roi_rows
            )
            pct = (returns_ - stake) / stake * 100
            roi_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"

        conn.close()
        return {"last_10": last_10_str, "roi_7d": roi_str, "yesterday": yesterday_str}

    except Exception:
        return {}


# ── edge_digest renderer ──────────────────────────────────────────────────────

def _render_edge_digest(
    tips: list[dict],
    tier_filter: list[str] | None = None,
) -> bytes:
    """Render Edge Digest card: 720×1280+ portrait, tier-grouped, compact rows.

    Parameters
    ----------
    tips:
        List of tip dicts (hot-tips cache format).
    tier_filter:
        Optional list of tier names to display (e.g. ["diamond", "gold"]).
        When provided, only tips whose tier is in tier_filter are shown.
        Remaining tips are counted in overflow.
    """
    stats_summary: dict = {}
    for t in tips:
        if isinstance(t, dict) and t.get("stats_summary"):
            stats_summary = t["stats_summary"]
            break

    # Apply tier filter before capping
    if tier_filter:
        active_tiers = set(tier_filter)
        tips = [t for t in tips if _tier_for(t) in active_tiers]

    visible = tips[:MAX_VISIBLE_PICKS]
    overflow = max(0, len(tips) - MAX_VISIBLE_PICKS)
    n = len(visible)

    tier_groups: dict[str, list[dict]] = {}
    for tier in _TIER_ORDER:
        grp = [t for t in visible if _tier_for(t) == tier]
        if grp:
            tier_groups[tier] = grp
    n_groups = len(tier_groups)

    has_stats = bool(stats_summary and any(v for v in stats_summary.values() if v and v != "—"))
    total_h = (
        _DIGEST_HEADER_H_EST
        + ((_DIGEST_STATS_H + 8) if has_stats else 0)
        + n_groups * _DIGEST_TIER_HDR_H
        + max(n, 1) * _DIGEST_PICK_H
        + (40 if overflow else 0)
        + _DIGEST_FOOTER_H
        + 20
    )
    total_h = max(total_h, 1280)
    total_h = min(total_h, _DIGEST_MAX_H)

    img, draw = _digest_canvas(total_h)
    subtitle = f"{n} edge{'s' if n != 1 else ''} active today"
    y = _draw_digest_header(img, draw, "EDGE PICKS", subtitle)
    if has_stats:
        y = _draw_digest_stats_bar(draw, y, stats_summary)

    if not visible:
        f_empty = _font("regular", 26)
        draw.text(
            (_DIGEST_W // 2, y + 80),
            "No edges active right now",
            font=f_empty,
            fill=T.TEXT_MUTED,
            anchor="mt",
        )
        _draw_digest_footer(img, draw, total_h - _DIGEST_FOOTER_H)
        return _to_bytes(img)

    for tier in _TIER_ORDER:
        grp = tier_groups.get(tier)
        if not grp:
            continue
        y = _draw_digest_tier_header(draw, y, tier, count=len(grp))
        for i, tip in enumerate(grp):
            _draw_digest_pick_row(img, draw, tip, y, is_last=(i == len(grp) - 1))
            y += _DIGEST_PICK_H

    if overflow:
        f_ov = _font("bold", 22)
        draw.text(
            (_DIGEST_W // 2, y + 12),
            f"+{overflow} more",
            font=f_ov,
            fill=T.GOLD,
            anchor="mt",
        )

    _draw_digest_footer(img, draw, total_h - _DIGEST_FOOTER_H)
    return _to_bytes(img)


# ── my_matches renderer ────────────────────────────────────────────────────────

def _render_my_matches(games: list[dict]) -> bytes:
    """Render My Matches card: games with form dots and kickoff times."""
    n = len(games)
    content_h = n * _MATCHES_ROW_H if n else _MATCHES_ROW_H
    total_h = _HEADER_H + content_h + _FOOTER_H
    total_h = min(total_h, _MAX_H)

    img, draw = _canvas(total_h)
    subtitle = f"{n} match{'es' if n != 1 else ''} upcoming"
    cards_y = _draw_header(img, draw, "MY MATCHES", subtitle)

    if not games:
        f_empty = T.load_font("regular", 26)
        draw.text(
            (_CARD_W // 2, cards_y + 60),
            "No matches scheduled",
            font=f_empty,
            fill=T.TEXT_MUTED,
            anchor="mt",
        )
        _draw_footer(img, draw, total_h - _FOOTER_H)
        return _to_bytes(img)

    f_team = T.load_font("bold", 26)
    f_body = T.load_font("regular", 20)
    f_small = T.load_font("regular", 18)

    # Truncate if height would overflow
    max_rows = (_MAX_H - _HEADER_H - _FOOTER_H) // _MATCHES_ROW_H
    visible = games[:max_rows]

    for i, game in enumerate(visible):
        cy = cards_y + i * _MATCHES_ROW_H
        _draw_matches_row(img, draw, game, cy, f_team, f_body, f_small)

    _draw_footer(img, draw, total_h - _FOOTER_H)
    return _to_bytes(img)


def _draw_matches_row(
    img: Image.Image,
    draw: ImageDraw.Draw,
    game: dict,
    cy: int,
    f_team: ImageFont.FreeTypeFont,
    f_body: ImageFont.FreeTypeFont,
    f_small: ImageFont.FreeTypeFont,
) -> None:
    """Draw one my_matches row at vertical offset cy."""
    home = _trunc(game.get("home_team") or "Home", 20)
    away = _trunc(game.get("away_team") or "Away", 20)
    kickoff = _kickoff_for(game)
    home_form = game.get("home_form") or []
    away_form = game.get("away_form") or []

    # Sport icon
    sport_key = _sport_key_for(game)
    sport_icon_name = T.SPORT_ICON.get(sport_key, "")
    x = _PAD_X
    if sport_icon_name:
        icon = T.load_icon(sport_icon_name, _ICON_MD)
        if icon:
            T.paste_alpha(img, icon, (x, cy + 8))
            x += _ICON_MD + 10

    # Team names (home on top, away below)
    row1_y = cy + 8
    row2_y = cy + 44

    # Right side: kickoff + score
    right_x = _CARD_W - _PAD_X
    if kickoff:
        kw = _text_w(kickoff, f_body)
        draw.text((right_x - kw, row1_y + 4), kickoff, font=f_body, fill=T.TEXT_SECONDARY)

    # Home score / away score (if provided)
    home_score = game.get("home_score")
    away_score = game.get("away_score")
    if home_score is not None and away_score is not None:
        score_text = f"{home_score} - {away_score}"
        sw = _text_w(score_text, f_team)
        draw.text((right_x - sw, row2_y - 2), score_text, font=f_team, fill=T.GOLD)

    # Team names
    draw.text((x, row1_y), home, font=f_team, fill=T.TEXT_PRIMARY)
    draw.text((x, row2_y), away, font=f_team, fill=T.TEXT_SECONDARY)

    # Form dots — home above, away below
    form_x = x
    form_row1_y = cy + 88
    form_row2_y = cy + 104

    if home_form:
        label_w = _text_w("H:", f_small)
        draw.text((form_x, form_row1_y), "H:", font=f_small, fill=T.TEXT_MUTED)
        fx = form_x + label_w + 4
        for res in home_form[:5]:
            _form_dot(draw, fx + _DOT_R, form_row1_y + _DOT_R, res)
            fx += _DOT_R * 2 + 4

    if away_form:
        label_w = _text_w("A:", f_small)
        draw.text((form_x, form_row2_y), "A:", font=f_small, fill=T.TEXT_MUTED)
        fx = form_x + label_w + 4
        for res in away_form[:5]:
            _form_dot(draw, fx + _DOT_R, form_row2_y + _DOT_R, res)
            fx += _DOT_R * 2 + 4

    # Separator
    _draw_separator_line(draw, cy + _MATCHES_ROW_H - 2)


# ── edge_detail renderer ───────────────────────────────────────────────────────

def _render_edge_detail(data: dict) -> bytes:
    """Render Edge Detail card: tier badge, pick, odds, signals, analysis."""
    if not data:
        data = {}

    tier = _tier_for(data)
    color = T.TIER_COLORS.get(tier, T.TIER_COLORS["bronze"])
    tier_label = T.TIER_LABELS.get(tier, "BRONZE")
    tier_emoji = T.TIER_EMOJIS.get(tier, "🥉")

    home = data.get("home_team") or "Home"
    away = data.get("away_team") or "Away"
    matchup = data.get("matchup") or f"{home} vs {away}"
    pick_team = _trunc(data.get("pick_team") or "", 22)
    outcome = data.get("outcome") or ""
    odds_val = float(data.get("odds") or 0)
    bookmaker = data.get("bookmaker") or ""
    ev = float(data.get("ev") or 0)
    confidence = float(data.get("confidence") or T.TIER_SCORE.get(tier, 50))
    kickoff = _kickoff_for(data)
    broadcast = data.get("broadcast") or ""
    analysis_text = data.get("analysis_text") or ""
    signals = data.get("signals") or {}
    odds_structured = data.get("odds_structured") or {}
    home_injuries = data.get("home_injuries") or []
    away_injuries = data.get("away_injuries") or []

    # Compute required height
    analysis_lines = len(analysis_text.split("\n")) if analysis_text else 0
    analysis_h = max(0, analysis_lines) * 26 + (80 if analysis_text else 0)
    inj_h = (len(home_injuries) + len(away_injuries)) * 22 + (40 if (home_injuries or away_injuries) else 0)
    odds_section_h = len(odds_structured) * 44 + 40

    total_h = (
        80           # compact header (no subtitle)
        + 130        # large tier badge block
        + 100        # pick line + EV
        + odds_section_h
        + 90         # signal dots
        + analysis_h
        + inj_h
        + _FOOTER_H
        + 20         # bottom margin
    )
    total_h = min(total_h, _MAX_H)

    img, draw = _canvas(total_h)

    # Compact header (no subtitle — detail card starts immediately)
    y = _PAD_Y // 2
    f_wordmark = T.load_font("bold", 30)
    logo_bottom = _draw_wordmark(img, draw, y, f_wordmark)
    grad_y = logo_bottom + 8
    _gradient_line(draw, _PAD_X, grad_y, _CARD_W - _PAD_X)
    y = grad_y + 16

    # ── Large tier badge ───────────────────────────────────────────────────────
    f_large_badge = T.load_font("bold", 36)
    badge_label = tier_label
    badge_bbox = f_large_badge.getbbox(badge_label)
    bw = (badge_bbox[2] - badge_bbox[0]) + T.BADGE_PAD_H * 4
    bh = (badge_bbox[3] - badge_bbox[1]) + T.BADGE_PAD_V * 4
    bx = (_CARD_W - bw) // 2
    draw.rounded_rectangle([(bx, y), (bx + bw, y + bh)], radius=_BADGE_R, fill=color)
    lum = color[0] * 299 + color[1] * 587 + color[2] * 114
    badge_text_fill = T.BG_PRIMARY if lum > 128000 else T.TEXT_PRIMARY
    draw.text(
        (bx + T.BADGE_PAD_H * 2 - badge_bbox[0], y + T.BADGE_PAD_V * 2 - badge_bbox[1]),
        badge_label,
        font=f_large_badge,
        fill=badge_text_fill,
    )
    y += bh + 12

    # Matchup line
    f_matchup = T.load_font("bold", 30)
    draw.text((_CARD_W // 2, y), _trunc(matchup, 40), font=f_matchup, fill=T.TEXT_PRIMARY, anchor="mt")
    y += 46

    # ── Pick line ──────────────────────────────────────────────────────────────
    f_pick = T.load_font("bold", 26)
    f_odds_label = T.load_font("mono_bold", 32)
    f_small = T.load_font("regular", 20)

    if pick_team:
        pick_text = f"Pick: {pick_team}"
        if outcome and outcome.lower() not in ("home", "away", pick_team.lower()):
            pick_text = f"Pick: {outcome}"
        draw.text((_PAD_X, y), pick_text, font=f_pick, fill=color)

    if odds_val:
        odds_text = f"{odds_val:.2f}"
        ow = _text_w(odds_text, f_odds_label)
        draw.text((_CARD_W - _PAD_X - ow, y - 4), odds_text, font=f_odds_label, fill=color)
        if bookmaker:
            bk_text = f"@ {bookmaker}"
            bkw = _text_w(bk_text, f_small)
            draw.text((_CARD_W - _PAD_X - bkw, y + 30), bk_text, font=f_small, fill=T.TEXT_MUTED)

    y += 56

    # EV + confidence bar
    pct = min(1.0, confidence / 100.0)
    bar_w = T.CONF_BAR_WIDTH + 80
    _confidence_bar(draw, _PAD_X, y + 2, bar_w, pct, color)
    conf_label = f"{int(confidence)}%"
    draw.text((_PAD_X + bar_w + 10, y), conf_label, font=f_small, fill=T.TEXT_MUTED)

    if ev != 0:
        ev_text = f"EV {'+' if ev > 0 else ''}{ev:.1f}%"
        ev_color = T.COLOR_SUCCESS if ev > 0 else T.COLOR_ERROR
        ew = _text_w(ev_text, f_small)
        draw.text((_CARD_W - _PAD_X - ew, y), ev_text, font=f_small, fill=ev_color)
    y += 38

    if kickoff:
        draw.text((_PAD_X, y), f"⏰ {kickoff}", font=f_small, fill=T.TEXT_MUTED)
        if broadcast:
            bw_text = _trunc(broadcast, 30)
            draw.text((_PAD_X + 220, y), bw_text, font=f_small, fill=T.TEXT_MUTED)
        y += 28

    draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)
    y += 16

    # ── Odds comparison ────────────────────────────────────────────────────────
    if odds_structured:
        f_odds_sec = T.load_font("bold", 20)
        draw.text((_PAD_X, y), "ODDS COMPARISON", font=f_odds_sec, fill=T.TEXT_SECONDARY)
        y += 28
        f_odds_row = T.load_font("mono", 22)
        f_odds_label2 = T.load_font("regular", 20)
        outcome_labels = {"home": "Home Win", "draw": "Draw", "away": "Away Win"}
        for key in ("home", "draw", "away"):
            bo = odds_structured.get(key)
            if not bo:
                continue
            out_text = outcome_labels.get(key, key.title())
            bk_text = _trunc(bo.get("bookmaker") or "", 15)
            odds_str = f"{float(bo.get('odds') or 0):.2f}"
            stale = bo.get("stale") or ""

            # Mark the picked outcome
            is_pick = outcome.lower() in (key, out_text.lower())
            row_color = color if is_pick else T.TEXT_PRIMARY
            indicator = "→ " if is_pick else "  "

            draw.text((_PAD_X, y), indicator + out_text, font=f_odds_label2, fill=row_color)
            draw.text((_PAD_X + 240, y), odds_str + stale, font=f_odds_row, fill=row_color)
            draw.text((_PAD_X + 340, y), bk_text, font=f_odds_label2, fill=T.TEXT_MUTED)
            y += 40

        draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)
        y += 16

    # ── Signal dots ────────────────────────────────────────────────────────────
    signal_names = ["price_edge", "form", "movement", "market", "tipster", "injury"]
    signal_labels = ["Price Edge", "Form", "Movement", "Market", "Tipster", "Injury"]
    f_sig = T.load_font("regular", 17)

    draw.text((_PAD_X, y), "SIGNALS", font=T.load_font("bold", 20), fill=T.TEXT_SECONDARY)
    y += 26

    sig_x = _PAD_X
    sig_spacing = (_CARD_W - 2 * _PAD_X) // len(signal_names)
    for i, (key, label) in enumerate(zip(signal_names, signal_labels)):
        active = bool(signals.get(key))
        cx = sig_x + i * sig_spacing + sig_spacing // 2
        fill = T.COLOR_SUCCESS if active else T.BG_ELEVATED
        r = _SIG_DOT_R
        draw.ellipse([(cx - r, y + r), (cx + r, y + 3 * r)], fill=fill)
        lw = _text_w(label, f_sig)
        draw.text((cx - lw // 2, y + 3 * r + 6), label, font=f_sig, fill=T.TEXT_MUTED)
    y += 56

    draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)
    y += 12

    # ── Analysis text ──────────────────────────────────────────────────────────
    if analysis_text:
        f_analysis = T.load_font("regular", 21)
        draw.text((_PAD_X, y), "ANALYSIS", font=T.load_font("bold", 20), fill=T.TEXT_SECONDARY)
        y += 26
        _draw_wrapped_text(draw, analysis_text, _PAD_X, y, _CARD_W - 2 * _PAD_X, f_analysis, T.TEXT_PRIMARY, line_spacing=26)
        # Estimate lines for y advance
        est_lines = max(1, len(analysis_text) // 60 + analysis_text.count("\n"))
        y += est_lines * 26 + 10

    # ── Injuries ───────────────────────────────────────────────────────────────
    if home_injuries or away_injuries:
        draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)
        y += 12
        f_inj = T.load_font("regular", 19)
        draw.text((_PAD_X, y), "INJURY FLAGS", font=T.load_font("bold", 20), fill=T.TEXT_SECONDARY)
        y += 26
        for inj in (home_injuries + away_injuries)[:6]:
            draw.text((_PAD_X + 8, y), f"⚠ {_trunc(inj, 55)}", font=f_inj, fill=T.COLOR_WARNING)
            y += 22

    _draw_footer(img, draw, total_h - _FOOTER_H)
    return _to_bytes(img)


def _draw_wrapped_text(
    draw: ImageDraw.Draw,
    text: str,
    x: int, y: int,
    max_width: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    line_spacing: int = 24,
) -> int:
    """Wrap and draw text. Returns total height used."""
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        current: list[str] = []
        for word in words:
            test = " ".join(current + [word])
            if _text_w(test, font) <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
        else:
            lines.append("")

    total_h = 0
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_spacing), line, font=font, fill=fill)
        total_h += line_spacing
    return total_h


# ── match_detail renderer ─────────────────────────────────────────────────────

def _render_match_detail(data: dict) -> bytes:
    """Render Match Detail card: stats boxes, form ribbons, H2H, injuries, odds."""
    if not data:
        data = {}

    home = data.get("home_team") or "Home"
    away = data.get("away_team") or "Away"
    matchup = data.get("matchup") or f"{home} vs {away}"
    tier = _tier_for(data)
    color = T.TIER_COLORS.get(tier, T.TIER_COLORS["bronze"])
    kickoff = _kickoff_for(data)
    broadcast = data.get("broadcast") or ""
    key_stats = data.get("key_stats") or []
    home_form = data.get("home_form") or []
    away_form = data.get("away_form") or []
    h2h = data.get("h2h") or {}
    home_injuries = data.get("home_injuries") or []
    away_injuries = data.get("away_injuries") or []
    odds_structured = data.get("odds_structured") or {}

    # Estimate height
    inj_h = (len(home_injuries) + len(away_injuries)) * 22 + (40 if (home_injuries or away_injuries) else 0)
    odds_h = len(odds_structured) * 40 + (40 if odds_structured else 0)

    total_h = (
        _HEADER_H
        + 80        # matchup + kickoff
        + 220       # 2x2 stats boxes
        + 90        # form ribbons
        + (80 if h2h.get("played") else 0)
        + inj_h
        + odds_h
        + _FOOTER_H
        + 20
    )
    total_h = min(total_h, _MAX_H)

    img, draw = _canvas(total_h)
    y = _draw_header(img, draw, "MATCH DETAIL", _trunc(matchup, 36))

    f_title = T.load_font("bold", 28)
    f_body = T.load_font("regular", 20)
    f_small = T.load_font("regular", 18)
    f_mono = T.load_font("mono", 20)
    f_bold_sm = T.load_font("bold", 18)

    # Kickoff + broadcast
    if kickoff:
        draw.text((_CARD_W // 2, y), f"⏰ {kickoff}", font=f_body, fill=T.TEXT_SECONDARY, anchor="mt")
        y += 28
    if broadcast:
        draw.text((_CARD_W // 2, y), _trunc(broadcast, 35), font=f_small, fill=T.TEXT_MUTED, anchor="mt")
        y += 24
    y += 8

    # ── 2x2 Stats boxes ───────────────────────────────────────────────────────
    if key_stats:
        draw.text((_PAD_X, y), "KEY STATS", font=T.load_font("bold", 20), fill=T.TEXT_SECONDARY)
        y += 28
        box_gap = 16
        boxes_per_row = 2
        bw = (_CARD_W - 2 * _PAD_X - box_gap) // boxes_per_row

        for row_idx in range(0, min(4, len(key_stats)), 2):
            for col_idx in range(2):
                si = row_idx + col_idx
                if si >= len(key_stats):
                    break
                stat = key_stats[si]
                bx = _PAD_X + col_idx * (bw + box_gap)
                by = y

                # Box background
                draw.rounded_rectangle([(bx, by), (bx + bw, by + _BOX_H)], radius=_CARD_R, fill=T.BG_CARD)
                draw.rounded_rectangle([(bx, by), (bx + bw, by + _BOX_H)], radius=_CARD_R, outline=T.BG_BORDER, width=1)

                # Label (top center)
                f_stat_label = T.load_font("regular", 16)
                lbl = _trunc(stat.get("label") or "N/A", 12)
                lw = _text_w(lbl, f_stat_label)
                draw.text((bx + (bw - lw) // 2, by + 6), lbl, font=f_stat_label, fill=T.TEXT_MUTED)

                # Home / Draw / Away values
                f_stat_val = T.load_font("bold", 22)
                home_val = _trunc(str(stat.get("home") or "—"), 6)
                away_val = _trunc(str(stat.get("away") or "—"), 6)
                draw_val = stat.get("draw")

                if draw_val is not None:
                    # H2H style: home | draw | away
                    hw = _text_w(home_val, f_stat_val)
                    dw_text = _trunc(str(draw_val), 4)
                    dw = _text_w(dw_text, f_stat_val)
                    aw = _text_w(away_val, f_stat_val)
                    total_val_w = hw + dw + aw + 24
                    vx = bx + (bw - total_val_w) // 2
                    val_y = by + 32
                    draw.text((vx, val_y), home_val, font=f_stat_val, fill=color)
                    vx += hw + 12
                    draw.text((vx, val_y), dw_text, font=f_stat_val, fill=T.TEXT_SECONDARY)
                    vx += dw + 12
                    draw.text((vx, val_y), away_val, font=f_stat_val, fill=T.TEXT_MUTED)
                else:
                    # Home | Away
                    hw = _text_w(home_val, f_stat_val)
                    aw = _text_w(away_val, f_stat_val)
                    spacing = (bw - hw - aw) // 3
                    val_y = by + 32
                    draw.text((bx + spacing, val_y), home_val, font=f_stat_val, fill=color)
                    draw.text((bx + bw - spacing - aw, val_y), away_val, font=f_stat_val, fill=T.TEXT_MUTED)

                # Home / Away team label (bottom)
                f_sub = T.load_font("regular", 14)
                draw.text((bx + 8, by + _BOX_H - 22), _trunc(home, 12), font=f_sub, fill=T.TEXT_MUTED)
                draw.text((bx + bw - 8 - _text_w(_trunc(away, 12), f_sub), by + _BOX_H - 22), _trunc(away, 12), font=f_sub, fill=T.TEXT_MUTED)

            y += _BOX_H + box_gap

        y += 8

    # ── Form ribbons ──────────────────────────────────────────────────────────
    if home_form or away_form:
        draw.text((_PAD_X, y), "RECENT FORM", font=T.load_font("bold", 20), fill=T.TEXT_SECONDARY)
        y += 26

        label_w = 120
        f_form_label = T.load_font("regular", 20)

        if home_form:
            draw.text((_PAD_X, y + _DOT_R - 2), _trunc(home, 14), font=f_form_label, fill=T.TEXT_PRIMARY)
            fx = _PAD_X + label_w
            for res in home_form[:5]:
                _form_dot(draw, fx + _DOT_R, y + _DOT_R, res)
                fx += _DOT_R * 2 + 5
            y += _DOT_R * 2 + 10

        if away_form:
            draw.text((_PAD_X, y + _DOT_R - 2), _trunc(away, 14), font=f_form_label, fill=T.TEXT_SECONDARY)
            fx = _PAD_X + label_w
            for res in away_form[:5]:
                _form_dot(draw, fx + _DOT_R, y + _DOT_R, res)
                fx += _DOT_R * 2 + 5
            y += _DOT_R * 2 + 10

        y += 12

    # ── H2H ───────────────────────────────────────────────────────────────────
    if h2h.get("played"):
        draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)
        y += 14
        f_h2h = T.load_font("bold", 20)
        draw.text((_PAD_X, y), "HEAD TO HEAD", font=f_h2h, fill=T.TEXT_SECONDARY)
        y += 28
        played = h2h["played"]
        hw_val = h2h.get("hw", 0)
        d_val = h2h.get("d", 0)
        aw_val = h2h.get("aw", 0)
        h2h_text = f"{played} played — {_trunc(home, 12)} {hw_val}  Draw {d_val}  {_trunc(away, 12)} {aw_val}"
        draw.text((_PAD_X, y), h2h_text, font=f_body, fill=T.TEXT_PRIMARY)
        y += 30

    # ── Injuries ───────────────────────────────────────────────────────────────
    if home_injuries or away_injuries:
        draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)
        y += 12
        draw.text((_PAD_X, y), "INJURY FLAGS", font=T.load_font("bold", 20), fill=T.TEXT_SECONDARY)
        y += 26
        f_inj = T.load_font("regular", 19)
        for inj in (home_injuries + away_injuries)[:6]:
            draw.text((_PAD_X + 8, y), f"⚠ {_trunc(inj, 55)}", font=f_inj, fill=T.COLOR_WARNING)
            y += 22
        y += 6

    # ── Odds ─────────────────────────────────────────────────────────────────
    if odds_structured:
        draw.line([(0, y), (_CARD_W, y)], fill=T.BG_BORDER, width=1)
        y += 12
        draw.text((_PAD_X, y), "BOOKMAKER ODDS", font=T.load_font("bold", 20), fill=T.TEXT_SECONDARY)
        y += 28
        f_odds_row = T.load_font("mono", 22)
        f_bk = T.load_font("regular", 20)
        outcome_labels = {"home": "Home Win", "draw": "Draw", "away": "Away Win"}
        for key in ("home", "draw", "away"):
            bo = odds_structured.get(key)
            if not bo:
                continue
            out_text = outcome_labels.get(key, key.title())
            bk_text = _trunc(bo.get("bookmaker") or "", 16)
            odds_str = f"{float(bo.get('odds') or 0):.2f}"
            stale = bo.get("stale") or ""
            draw.text((_PAD_X, y), out_text, font=f_bk, fill=T.TEXT_PRIMARY)
            draw.text((_PAD_X + 240, y), odds_str + stale, font=f_odds_row, fill=color)
            draw.text((_PAD_X + 340, y), bk_text, font=f_bk, fill=T.TEXT_MUTED)
            y += 38

    _draw_footer(img, draw, total_h - _FOOTER_H)
    return _to_bytes(img)


# ── Error fallback ────────────────────────────────────────────────────────────

def _render_error_card(msg: str) -> bytes:
    """Render a minimal error card (used only when all rendering fails)."""
    total_h = 300
    img, draw = _canvas(total_h)
    f = T.load_font("regular", 22)
    draw.text(
        (_CARD_W // 2, total_h // 2),
        _trunc(f"Error: {msg}", 40),
        font=f,
        fill=T.COLOR_ERROR,
        anchor="mm",
    )
    return _to_bytes(img)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_card(card_type: str, data, tier_filter: list[str] | None = None) -> bytes:
    """Generate a PNG image card.

    Parameters
    ----------
    card_type:
        One of ``"edge_digest"``, ``"my_matches"``, ``"edge_detail"``,
        ``"match_detail"``.
    data:
        ``edge_digest`` / ``"my_matches"``: list of dicts.
        ``"edge_detail"`` / ``"match_detail"``: single dict from
        ``card_pipeline.build_card_data()``.
    tier_filter:
        Optional list of tier names to include in edge_digest output.
        E.g. ``["diamond", "gold"]`` hides silver/bronze picks.
        Ignored for other card types.

    Returns
    -------
    bytes
        PNG image bytes, lossless.

    Notes
    -----
    Never raises — returns an error card PNG on any rendering failure.
    """
    try:
        if card_type == "edge_digest":
            items = data if isinstance(data, list) else ([data] if data else [])
            return _render_edge_digest(items, tier_filter=tier_filter)
        elif card_type == "my_matches":
            items = data if isinstance(data, list) else ([data] if data else [])
            return _render_my_matches(items)
        elif card_type == "edge_detail":
            card_data = data if isinstance(data, dict) else (data[0] if data else {})
            return _render_edge_detail(card_data or {})
        elif card_type == "match_detail":
            card_data = data if isinstance(data, dict) else (data[0] if data else {})
            return _render_match_detail(card_data or {})
        else:
            return _render_edge_digest([])
    except Exception as exc:
        try:
            return _render_error_card(str(exc))
        except Exception:
            # Absolute last resort
            buf = io.BytesIO()
            Image.new("RGB", (_CARD_W, 200), T.BG_PRIMARY).save(buf, format="PNG")
            return buf.getvalue()
