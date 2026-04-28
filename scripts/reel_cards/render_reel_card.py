#!/usr/bin/env python3
"""
render_reel_card.py — MzansiEdge Reel Card Compositing Script v6.5
v6.5 (28 Apr 2026, FIX-REEL-KIT-RENDERING-01): tier rosette overlap fix.
  - LINE_Y_FIXED: 632 → 700 (cascade shifts down 68px so the medal emoji
    and the league/team-name block sit clear of the frame-baked rosette).
  - TIER_EMOJI_Y_NUDGE silver/gold/bronze: -0.20 → -0.50 (lift medal glyph
    higher within its block so the gap to the league text is ≥40px on every
    tier). Diamond keeps -0.70.
  - Behaviour is tier-agnostic — applies to all four tier badges.

v6 (legacy): LINE_Y_FIXED 590→632, two 46px steps within the available 232px.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── Frame constants ────────────────────────────────────────────────────────────
CANVAS_W    = 925
CANVAS_H    = 1364
OVAL_TOP    = 300
OVAL_BOTTOM = 1150
OVAL_LEFT   = 118
OVAL_RIGHT  = 812
OVAL_W      = OVAL_RIGHT - OVAL_LEFT
OVAL_H      = OVAL_BOTTOM - OVAL_TOP
CX          = (OVAL_LEFT + OVAL_RIGHT) // 2
SCALE       = OVAL_W / 1240

LINE_Y_FIXED = 700  # v6.5: 632 + 68 (clears medal emoji from team-name overlap)

# ── Font paths ─────────────────────────────────────────────────────────────────
POPPINS_BOLD   = '/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf'
POPPINS_MEDIUM = '/usr/share/fonts/truetype/poppins/Poppins-Medium.ttf'
JETBRAINS_BOLD = '/usr/share/fonts/truetype/jetbrains/JetBrainsMono-Bold.ttf'
NOTO_EMOJI     = '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'

FRAMES_DIR = Path(__file__).resolve().parent / 'assets'
TIER_EMOJI = {'diamond': '💎', 'gold': '🥇', 'silver': '🥈', 'bronze': '🥉'}

# Tier visual calibration. Diamond gem renders visually larger than medal glyphs
# at equal em_h, so it carries its own scale. v6.5 lifts silver/gold/bronze
# medals within their block to clear the team-name headline below.
TIER_EMOJI_SCALE    = {'diamond': 0.70, 'gold': 1.0, 'silver': 1.0, 'bronze': 1.0}
TIER_EMOJI_Y_NUDGE  = {'diamond': -0.70, 'gold': -0.50, 'silver': -0.50, 'bronze': -0.50}  # * em_h
TIER_LEAGUE_Y_NUDGE = {'diamond': -0.70, 'gold': -0.70, 'silver': -0.70, 'bronze': -0.70}  # * lh
TIER_TOP_BLOCK_Y_NUDGE = {'diamond': -15, 'gold': 0, 'silver': 0, 'bronze': 0}  # pixels, -ve = up
PICK_TEAM_Y_NUDGE = 5  # pixels, +ve = down. Baseline fix for orange pick_team glyph (v6.2)

# ── Colours ────────────────────────────────────────────────────────────────────
YELLOW        = (255, 210,   0)
YELLOW_BRIGHT = (255, 225,  50)
ORANGE        = (247, 147,  26)
WHITE         = (255, 250, 240)
MUTED         = (160, 150, 140)
GREEN         = ( 80, 220, 120)
BRAND_GRAD    = [(0.0, (255,210,0)), (0.5, (247,147,26)), (1.0, (255,107,0))]

# ── Helpers ────────────────────────────────────────────────────────────────────
def F(path, ref):
    return ImageFont.truetype(path, max(8, round(ref * SCALE)))

def Fpx(path, px):
    return ImageFont.truetype(path, max(8, px))

def measure(font, text):
    bb = font.getbbox(text)
    return bb[2] - bb[0], bb[3] - bb[1]

def lerp_color(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))

def grad_color(stops, t):
    t = max(0.0, min(1.0, t))
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]; t1, c1 = stops[i+1]
        if t0 <= t <= t1:
            return lerp_color(c0, c1, (t - t0) / (t1 - t0) if t1 != t0 else 0)
    return stops[-1][1]

def draw_grad_text(overlay, text, font, cx, y_top):
    """Full-canvas mask gradient text. Returns text bbox height."""
    cw, ch = overlay.size
    bb = font.getbbox(text)
    tw_ref = max(1, bb[2] - bb[0])
    th_ref = max(1, bb[3] - bb[1])
    x0 = cx - tw_ref // 2
    mask_img = Image.new('L', (cw, ch), 0)
    ImageDraw.Draw(mask_img).text((x0, y_top), text, font=font, fill=255)
    bbox = mask_img.getbbox()
    if not bbox:
        return th_ref
    bx0, by0, bx1, by1 = bbox
    tw_px = max(1, bx1 - bx0)
    grad = Image.new('RGB', (cw, ch), (0, 0, 0))
    gpx = grad.load()
    for gx in range(bx0, bx1):
        t = (gx - bx0) / (tw_px - 1) if tw_px > 1 else 0
        rc, gc, bc = grad_color(BRAND_GRAD, t)
        for gy in range(by0, by1):
            gpx[gx, gy] = (rc, gc, bc)
    result = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    result.paste(grad.convert('RGBA'), (0, 0), mask_img)
    overlay.alpha_composite(result)
    return th_ref

def render_emoji(char, target_h, alpha=255):
    font = ImageFont.truetype(NOTO_EMOJI, 109)
    tmp  = Image.new('RGBA', (200, 200), (0,0,0,0))
    ImageDraw.Draw(tmp).text((10, 10), char, font=font, embedded_color=True)
    bb = tmp.getbbox()
    if not bb:
        return Image.new('RGBA', (target_h, target_h), (0,0,0,0))
    crop = tmp.crop(bb)
    w, h = crop.size
    nw   = max(1, round(w * target_h / h))
    out  = crop.resize((nw, target_h), Image.LANCZOS)
    if alpha < 255:
        r, g, b, a = out.split()
        out = Image.merge('RGBA', (r, g, b, a.point(lambda p: int(p * alpha / 255))))
    return out

def glow_layer(size, draw_fn, blur_r):
    layer = Image.new('RGBA', size, (0,0,0,0))
    draw_fn(ImageDraw.Draw(layer))
    return layer.filter(ImageFilter.GaussianBlur(radius=blur_r))

# ── Main ───────────────────────────────────────────────────────────────────────
def render_reel_card(pick: dict, output_path: str) -> str:
    tier = pick['tier'].lower()
    frame_path = FRAMES_DIR / f'frame-{tier}.png'
    if not frame_path.exists():
        raise FileNotFoundError(f'Frame asset missing: {frame_path}')

    frame = Image.open(frame_path).convert('RGBA')
    if frame.size != (CANVAS_W, CANVAS_H):
        raise ValueError(f'Frame wrong size: {frame.size}')

    ov   = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0,0,0,0))
    draw = ImageDraw.Draw(ov)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    FL      = F(POPPINS_BOLD,   56)    # League: v5 unchanged
    FT      = F(POPPINS_BOLD,  107)    # Teams:  v5 unchanged
    FV      = F(POPPINS_BOLD,   47)    # VS:     v5 unchanged
    FLB_BET = F(POPPINS_MEDIUM, 55)    # YOU BET label: v5 unchanged
    FLB_WIN = F(POPPINS_MEDIUM, 38)    # YOU WIN label: v5 unchanged
    FB      = Fpx(JETBRAINS_BOLD, max(8, round(96 * 1.1 * 1.3 * SCALE)))  # stake: v5 unchanged
    FW      = Fpx(JETBRAINS_BOLD, max(8, round(148 * SCALE)))              # return: v5 unchanged

    # Pick line (auto-shrink)
    ps = 1.0
    while True:
        FP1 = Fpx(POPPINS_MEDIUM, max(8, round(48 * SCALE * ps)))
        FP2 = Fpx(POPPINS_BOLD,   max(8, round(58 * SCALE * ps)))
        FP3 = FP1
        pw1, _ = measure(FP1, 'Pick ')
        pw2, _ = measure(FP2, pick['pick_team'])
        pw3, _ = measure(FP3, f" @ {pick['bookmaker']}")
        if pw1 + pw2 + pw3 <= OVAL_W - 60 or ps <= 0.5:
            break
        ps -= 0.05

    FPRO = Fpx(POPPINS_BOLD, max(8, round(56 * SCALE * 1.44)))

    # ── Measurements ──────────────────────────────────────────────────────────
    _, lh  = measure(FL, pick['league'])
    _, hh  = measure(FT, pick['home_team'])
    _, vsh = measure(FV, ' VS ')
    _, awh = measure(FT, pick['away_team'])

    # Emoji: v5 factor 1.9008 unchanged
    em_h   = max(30, round(hh * 1.9008 * TIER_EMOJI_SCALE[tier]))
    em_img = render_emoji(TIER_EMOJI[tier], em_h, alpha=200)

    # Pick line baseline
    pa1, _ = FP1.getmetrics(); pa2, _ = FP2.getmetrics()
    base   = max(pa1, pa2)
    _, ph1 = measure(FP1, 'Pick '); _, ph2 = measure(FP2, pick['pick_team'])
    pick_h = base - min(pa1, pa2) + max(ph1, ph2)

    # Profit pill
    profit_text = f"{pick['profit']} PROFIT"
    ppw, pph = measure(FPRO, profit_text)
    ppx = max(8, round(30 * SCALE * 1.2))
    ppy = max(6, round(14 * SCALE * 1.2))
    pill_w = ppw + ppx * 2
    pill_h = pph + ppy * 2

    # Box dims
    bw = round(400 * SCALE); bh = round(280 * SCALE)
    bg = round(110 * SCALE); br = round(20  * SCALE)
    dh = round(14 * SCALE)

    # ── Cascade gaps (IDENTICAL to v5 — line_y position within cascade unchanged) ──
    GE  = max(0, round(14 * SCALE) - round(lh  * 0.10))
    GL  = max(0, round(18 * SCALE) - round(hh  * 0.10))
    GH  = round(2  * SCALE) + max(1, round(vsh * 0.05))
    GV  = max(0,  round(2  * SCALE) - round(awh * 0.10))
    GA  = round(34 * SCALE)
    GDM = round(44 * SCALE)
    GB  = round(50 * SCALE)
    GP  = round(28 * SCALE) + max(2, round(pill_h * 0.05))

    # cascade above determines start_y (line_y = start_y + cascade_above = LINE_Y_FIXED)
    cascade_above = em_h + GE + lh + GL + hh + GH + vsh + GV + awh + GA
    start_y = LINE_Y_FIXED - cascade_above
    y = start_y

    # ── Draw offsets (IDENTICAL to v5 — applied at draw time only) ────────────
    top_nudge = TIER_TOP_BLOCK_Y_NUDGE[tier]  # shifts whole top block without moving divider
    em_dy     = -round(em_h  * 0.35) + round(em_h  * TIER_EMOJI_Y_NUDGE[tier]) + top_nudge
    league_dy = -round(lh    * 0.82) + round(lh    * TIER_LEAGUE_Y_NUDGE[tier]) + top_nudge
    home_dy   = -round(hh    * 0.50) + top_nudge
    vs_dy     = +round(vsh   * 0.25) - round(vsh * 0.80) + top_nudge
    away_dy   = -round(awh   * 0.50) + top_nudge

    # ── 1. Tier emoji ──────────────────────────────────────────────────────────
    ov.alpha_composite(em_img, dest=(CX - em_img.width // 2, y + em_dy))
    y += em_img.height + GE

    # ── 2. League ──────────────────────────────────────────────────────────────
    draw.text((CX, y + league_dy), pick['league'], font=FL, fill=YELLOW, anchor='mt')
    y += lh + GL

    # ── 3. Home team ───────────────────────────────────────────────────────────
    draw.text((CX, y + home_dy), pick['home_team'], font=FT, fill=WHITE, anchor='mt')
    y += hh + GH

    # ── 4. VS ──────────────────────────────────────────────────────────────────
    draw.text((CX, y + vs_dy), ' VS ', font=FV, fill=YELLOW, anchor='mt')
    y += vsh + GV

    # ── 5. Away team (brand gradient) ─────────────────────────────────────────
    draw_grad_text(ov, pick['away_team'], FT, CX, y + away_dy)
    y += awh + GA

    # ── 6+7. Divider + diamond at LINE_Y_FIXED ────────────────────────────────
    line_y = y  # == LINE_Y_FIXED (658) by construction
    lx1 = CX - round(200 * SCALE)
    lx2 = CX + round(200 * SCALE)
    lt  = 4
    for i in range(lt):
        for lx in range(lx1, lx2 + 1):
            t = (lx - lx1) / max(1, lx2 - lx1)
            rc, gc, bc = grad_color(BRAND_GRAD, t)
            draw.point((lx, line_y - lt // 2 + i), fill=(rc, gc, bc, 255))
    draw.polygon(
        [(CX, line_y - dh), (CX + dh, line_y),
         (CX, line_y + dh), (CX - dh, line_y)],
        fill=YELLOW,
    )
    y += dh + GDM

    # ── 8. Boxes ──────────────────────────────────────────────────────────────
    byt = y; byb = byt + bh
    total_bw = bw * 2 + bg
    blx = CX - total_bw // 2
    brx = blx + bw + bg
    acx = blx + bw + bg // 2
    acy = byt + bh // 2

    # Arrow
    aw_half = round(44 * SCALE); ah_half = round(32 * SCALE)
    apt = [
        (acx - aw_half, acy - ah_half//2),
        (acx + 4,       acy - ah_half//2),
        (acx + 4,       acy - ah_half),
        (acx + aw_half, acy),
        (acx + 4,       acy + ah_half),
        (acx + 4,       acy + ah_half//2),
        (acx - aw_half, acy + ah_half//2),
    ]
    def _arrow_glow(d): d.polygon(apt, fill=(255,210,0,150))
    ov.alpha_composite(glow_layer((CANVAS_W, CANVAS_H), _arrow_glow, 7))
    draw.polygon(apt, fill=YELLOW)

    # Left box: YOU BET
    draw.rounded_rectangle([blx, byt, blx+bw, byb], radius=br,
                           fill=(255,255,255,10), outline=MUTED, width=3)
    _, lblh_bet = measure(FLB_BET, 'YOU BET')
    bcxl        = blx + bw // 2
    lbl_off_bet = round(36 * SCALE * 1.44)
    draw.text((bcxl, byt + lbl_off_bet), 'YOU BET', font=FLB_BET, fill=MUTED, anchor='mt')
    draw.text((bcxl, byt + lbl_off_bet + lblh_bet + round(20 * SCALE)),
              pick['stake'], font=FB, fill=WHITE, anchor='mt')

    # Right box: YOU WIN
    def _right_glow(d): d.rounded_rectangle([brx-5, byt-5, brx+bw+5, byb+5],
                                             radius=br+5, fill=(255,200,0,80))
    ov.alpha_composite(glow_layer((CANVAS_W, CANVAS_H), _right_glow, 12))
    draw.rounded_rectangle([brx, byt, brx+bw, byb], radius=br,
                           fill=(255,210,0,30), outline=YELLOW, width=3)
    _, lblh_win = measure(FLB_WIN, 'YOU WIN')
    bcxr        = brx + bw // 2
    lbl_off_win = round(36 * SCALE * 1.32)
    draw.text((bcxr, byt + lbl_off_win), 'YOU WIN', font=FLB_WIN, fill=YELLOW, anchor='mt')
    win_y = byt + lbl_off_win + lblh_win + round(20 * SCALE)
    def _win_glow(d): d.text((bcxr, win_y), pick['return_amount'],
                              font=FW, fill=(255,220,0,220), anchor='mt')
    ov.alpha_composite(glow_layer((CANVAS_W, CANVAS_H), _win_glow, 8))
    draw.text((bcxr, win_y), pick['return_amount'], font=FW, fill=YELLOW_BRIGHT, anchor='mt')
    y += bh + GB

    # ── 9. Pick line (baseline-aligned, unchanged) ────────────────────────────
    sx = CX - (pw1 + pw2 + pw3) // 2
    def _team_glow(d): d.text((sx + pw1, y + base - pa2 + PICK_TEAM_Y_NUDGE), pick['pick_team'],
                               font=FP2, fill=(255,120,0,180), anchor='lt')
    ov.alpha_composite(glow_layer((CANVAS_W, CANVAS_H), _team_glow, 8))
    draw.text((sx,         y + base - pa1), 'Pick ',           font=FP1, fill=WHITE,  anchor='lt')
    draw.text((sx + pw1,   y + base - pa2 + PICK_TEAM_Y_NUDGE), pick['pick_team'], font=FP2, fill=ORANGE, anchor='lt')
    draw.text((sx+pw1+pw2, y + base - pa1), f" @ {pick['bookmaker']}", font=FP3, fill=WHITE, anchor='lt')
    y += pick_h + GP

    # ── 10. Profit pill ────────────────────────────────────────────────────────
    # Pill SHAPE: carried by cascade (+232px vs v5) — includes "down 30%" draw offset
    py = y + round(pill_h * 0.45)
    px1 = CX - pill_w // 2; px2 = CX + pill_w // 2
    pill_shape_dy = 0
    draw.rounded_rectangle([(px1, py), (px2, py + pill_h)],
                           radius=round(48 * SCALE), fill=(40,180,80,60),
                           outline=GREEN, width=4)
    # Profit TEXT: exempt from step 1 → apply -116px offset so net shift = +116px
    draw.text((CX - ppw // 2, py + ppy - round(pill_h * 0.20)), profit_text, font=FPRO, fill=GREEN)

    # ── Composite ─────────────────────────────────────────────────────────────
    result = Image.alpha_composite(frame, ov)
    result.save(output_path, 'PNG')
    return output_path


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: python3 render_reel_card.py <pick.json> <output.png>')
        sys.exit(1)
    with open(sys.argv[1]) as fh:
        pick_data = json.load(fh)
    print(render_reel_card(pick_data, sys.argv[2]))
