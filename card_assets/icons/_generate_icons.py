"""IMG-W0 — Icon Generator.
Renders 16 icon PNGs (64×64 RGBA) from parametric SVG-style definitions.
Run once to regenerate: python _generate_icons.py
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ICON_SIZE = 64
OUT_DIR = Path(__file__).parent
ICON_COLOR = (255, 255, 255, 220)   # near-white, slightly transparent
ACCENT = (212, 168, 67, 255)         # gold #D4A843
DIM = (255, 255, 255, 120)           # dimmed


def _canvas():
    return Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))


def _save(img: Image.Image, name: str):
    img.save(OUT_DIR / f"{name}.png", format="PNG")


# ── 1. soccer ─────────────────────────────────────────────────────────────────
def make_soccer():
    img = _canvas(); d = ImageDraw.Draw(img)
    cx, cy, r = 32, 32, 26
    d.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=ICON_COLOR, width=3)
    # Pentagon-ish centre patch
    d.regular_polygon((cx, cy, 9), 5, rotation=18, fill=ICON_COLOR)
    # 5 surrounding patches (simplified as arcs)
    for i in range(5):
        angle = math.radians(i * 72 - 54)
        px = cx + 17 * math.cos(angle)
        py = cy + 17 * math.sin(angle)
        d.ellipse([(px-4, py-4), (px+4, py+4)], fill=DIM)
    _save(img, "soccer")


# ── 2. rugby ──────────────────────────────────────────────────────────────────
def make_rugby():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Oval ball
    d.ellipse([(10, 22), (54, 42)], outline=ICON_COLOR, width=3)
    # Seam line
    d.line([(32, 22), (32, 42)], fill=ICON_COLOR, width=2)
    d.line([(20, 26), (20, 38)], fill=DIM, width=1)
    d.line([(44, 26), (44, 38)], fill=DIM, width=1)
    _save(img, "rugby")


# ── 3. cricket ────────────────────────────────────────────────────────────────
def make_cricket():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Bat: handle
    d.line([(14, 10), (22, 28)], fill=ICON_COLOR, width=3)
    # Bat blade (wider rectangle angled)
    pts = [(18, 26), (46, 36), (52, 54), (24, 44)]
    d.polygon(pts, fill=ICON_COLOR)
    # Ball
    d.ellipse([(40, 8), (58, 26)], outline=ICON_COLOR, width=2, fill=(0,0,0,0))
    d.arc([(41, 9), (57, 25)], 30, 150, fill=ACCENT, width=2)
    _save(img, "cricket")


# ── 4. boxing ─────────────────────────────────────────────────────────────────
def make_boxing():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Glove body
    d.rounded_rectangle([(12, 20), (50, 52)], radius=10, outline=ICON_COLOR, width=3)
    # Thumb bump
    d.ellipse([(44, 14), (56, 30)], outline=ICON_COLOR, width=2)
    # Wrist band
    d.rectangle([(16, 46), (46, 52)], fill=ICON_COLOR)
    _save(img, "boxing")


# ── 5. basketball ─────────────────────────────────────────────────────────────
def make_basketball():
    img = _canvas(); d = ImageDraw.Draw(img)
    cx, cy, r = 32, 32, 26
    d.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=ICON_COLOR, width=3)
    d.arc([(cx-r, cy-r), (cx+r, cy+r)], 10, 170, fill=ICON_COLOR, width=2)
    d.arc([(cx-r, cy-r), (cx+r, cy+r)], 190, 350, fill=ICON_COLOR, width=2)
    d.line([(cx, cy-r), (cx, cy+r)], fill=ICON_COLOR, width=2)
    _save(img, "basketball")


# ── 6. tennis ─────────────────────────────────────────────────────────────────
def make_tennis():
    img = _canvas(); d = ImageDraw.Draw(img)
    cx, cy, r = 32, 32, 26
    d.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=ICON_COLOR, width=3)
    # Seam curves
    d.arc([(cx-r, cy-r+4), (cx+r, cy+r+4)], 220, 320, fill=ICON_COLOR, width=2)
    d.arc([(cx-r, cy-r-4), (cx+r, cy+r-4)], 40, 140, fill=ICON_COLOR, width=2)
    _save(img, "tennis")


# ── 7. trend_up ───────────────────────────────────────────────────────────────
def make_trend_up():
    img = _canvas(); d = ImageDraw.Draw(img)
    pts = [(10, 46), (24, 32), (34, 40), (54, 16)]
    d.line(pts, fill=ICON_COLOR, width=3, joint="curve")
    # Arrow head
    d.polygon([(46, 12), (58, 18), (54, 28)], fill=ICON_COLOR)
    _save(img, "trend_up")


# ── 8. trend_down ─────────────────────────────────────────────────────────────
def make_trend_down():
    img = _canvas(); d = ImageDraw.Draw(img)
    pts = [(10, 18), (24, 32), (34, 24), (54, 48)]
    d.line(pts, fill=ICON_COLOR, width=3, joint="curve")
    # Arrow head
    d.polygon([(46, 52), (58, 46), (54, 36)], fill=ICON_COLOR)
    _save(img, "trend_down")


# ── 9. fire ───────────────────────────────────────────────────────────────────
def make_fire():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Flame body
    pts = [
        (32, 6), (44, 22), (50, 14), (54, 32),
        (50, 50), (32, 58), (14, 50), (10, 32),
        (16, 14), (22, 22),
    ]
    d.polygon(pts, fill=ACCENT)
    # Inner highlight
    inner = [(32, 20), (40, 32), (44, 22), (46, 36), (32, 50), (18, 36), (20, 22), (26, 32)]
    d.polygon(inner, fill=(255, 220, 100, 180))
    _save(img, "fire")


# ── 10. diamond ───────────────────────────────────────────────────────────────
def make_diamond():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Classic diamond shape
    pts = [(32, 6), (58, 24), (32, 58), (6, 24)]
    d.polygon(pts, outline=ICON_COLOR, width=3)
    # Facet lines
    d.line([(6, 24), (58, 24)], fill=DIM, width=1)
    d.line([(32, 6), (6, 24)], fill=DIM, width=1)
    d.line([(32, 6), (58, 24)], fill=DIM, width=1)
    d.line([(18, 14), (32, 24), (46, 14)], fill=DIM, width=1)
    _save(img, "diamond")


# ── 11. star ──────────────────────────────────────────────────────────────────
def make_star():
    img = _canvas(); d = ImageDraw.Draw(img)
    cx, cy = 32, 32
    outer_r, inner_r = 28, 12
    pts = []
    for i in range(10):
        angle = math.radians(i * 36 - 90)
        r = outer_r if i % 2 == 0 else inner_r
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(pts, fill=ACCENT)
    _save(img, "star")


# ── 12. shield ────────────────────────────────────────────────────────────────
def make_shield():
    img = _canvas(); d = ImageDraw.Draw(img)
    pts = [(32, 8), (56, 16), (56, 38), (32, 58), (8, 38), (8, 16)]
    d.polygon(pts, outline=ICON_COLOR, width=3)
    # Check mark inside
    d.line([(20, 34), (28, 44), (46, 22)], fill=ICON_COLOR, width=3)
    _save(img, "shield")


# ── 13. clock ─────────────────────────────────────────────────────────────────
def make_clock():
    img = _canvas(); d = ImageDraw.Draw(img)
    cx, cy, r = 32, 32, 26
    d.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=ICON_COLOR, width=3)
    # Minute hand (to 12)
    d.line([(cx, cy), (cx, cy-18)], fill=ICON_COLOR, width=3)
    # Hour hand (to 3)
    d.line([(cx, cy), (cx+14, cy)], fill=ICON_COLOR, width=2)
    # Centre dot
    d.ellipse([(cx-3, cy-3), (cx+3, cy+3)], fill=ICON_COLOR)
    _save(img, "clock")


# ── 14. trophy ────────────────────────────────────────────────────────────────
def make_trophy():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Cup
    d.arc([(12, 8), (52, 40)], 0, 180, fill=ACCENT, width=4)
    d.line([(12, 24), (12, 8)], fill=ACCENT, width=4)
    d.line([(52, 24), (52, 8)], fill=ACCENT, width=4)
    # Handles
    d.arc([(4, 14), (16, 32)], 270, 90, fill=ICON_COLOR, width=2)
    d.arc([(48, 14), (60, 32)], 90, 270, fill=ICON_COLOR, width=2)
    # Stem + base
    d.line([(32, 40), (32, 52)], fill=ICON_COLOR, width=3)
    d.rectangle([(18, 50), (46, 56)], fill=ICON_COLOR)
    _save(img, "trophy")


# ── 15. chart ─────────────────────────────────────────────────────────────────
def make_chart():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Axes
    d.line([(12, 52), (12, 12)], fill=ICON_COLOR, width=2)
    d.line([(12, 52), (56, 52)], fill=ICON_COLOR, width=2)
    # Bars
    bars = [(16, 44, 24, 52), (26, 32, 34, 52), (36, 22, 44, 52), (46, 38, 54, 52)]
    for bar in bars:
        d.rectangle(bar, fill=ACCENT)
    _save(img, "chart")


# ── 16. lock ──────────────────────────────────────────────────────────────────
def make_lock():
    img = _canvas(); d = ImageDraw.Draw(img)
    # Shackle (arc)
    d.arc([(16, 8), (48, 36)], 180, 0, fill=ICON_COLOR, width=4)
    d.line([(16, 22), (16, 36)], fill=ICON_COLOR, width=4)
    d.line([(48, 22), (48, 36)], fill=ICON_COLOR, width=4)
    # Body
    d.rounded_rectangle([(10, 34), (54, 58)], radius=4, fill=ICON_COLOR)
    # Keyhole
    d.ellipse([(28, 40), (36, 48)], fill=(0, 0, 0, 200))
    d.rectangle([(30, 46), (34, 53)], fill=(0, 0, 0, 200))
    _save(img, "lock")


# ── Runner ────────────────────────────────────────────────────────────────────
GENERATORS = [
    make_soccer, make_rugby, make_cricket, make_boxing,
    make_basketball, make_tennis, make_trend_up, make_trend_down,
    make_fire, make_diamond, make_star, make_shield,
    make_clock, make_trophy, make_chart, make_lock,
]

if __name__ == "__main__":
    for fn in GENERATORS:
        fn()
    print(f"Generated {len(GENERATORS)} icons in {OUT_DIR}")
