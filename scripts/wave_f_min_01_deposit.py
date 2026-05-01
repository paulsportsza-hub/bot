#!/usr/bin/env python3
"""WAVE-F-MIN-01 — Deposit canonical HTML for my_matches + match_detail.

Option A: render from current prod templates with canonical fixture data,
save as *_canonical.html in the gallery, then visual-diff vs canonical PNGs.
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
import io

BOT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_ROOT))

from jinja2 import Environment, FileSystemLoader
from card_renderer import render_card_sync
from card_data import build_my_matches_data, build_match_detail_data

TEMPLATES_DIR  = BOT_ROOT / "card_templates"
CANONICAL_DIR  = BOT_ROOT / "static" / "qa-gallery" / "canonical"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

# ── Canonical fixture data (mirrors generate_qa_gallery.py exactly) ──────────
EDGE_MATCH_1 = {
    "has_edge": True,
    "home": "Kaizer Chiefs", "away": "Mamelodi Sundowns",
    "league": "DStv Premiership", "sport_emoji": "⚽",
    "date": "Sat 26 Apr", "time": "15:30", "channel": "SuperSport 211",
    "edge_tier": "gold", "pick": "Kaizer Chiefs", "bookmaker": "Betway",
}
EDGE_MATCH_2 = {
    "has_edge": True,
    "home": "Manchester City", "away": "Arsenal",
    "league": "Premier League", "sport_emoji": "⚽",
    "date": "Sun 27 Apr", "time": "16:00", "channel": "SuperSport 3",
    "edge_tier": "diamond", "pick": "Manchester City", "bookmaker": "Hollywoodbets",
}
PLAIN_MATCH_1 = {
    "has_edge": False,
    "home": "Stormers", "away": "Bulls",
    "league": "URC", "sport_emoji": "🏉",
    "date": "Sat 26 Apr", "time": "17:00", "channel": "SuperSport 4",
    "odds_home": 1.80, "odds_draw": None, "odds_away": 2.10,
}
PLAIN_MATCH_2 = {
    "has_edge": False,
    "home": "South Africa", "away": "India",
    "league": "T20 International", "sport_emoji": "🏏",
    "date": "Sun 27 Apr", "time": "14:00", "channel": "SuperSport 2",
    "odds_home": 2.10, "odds_draw": None, "odds_away": 1.75,
}
DETAIL_MATCH_WITH_EDGE = {
    "home": "Manchester City", "away": "Arsenal",
    "league": "Premier League", "sport_emoji": "⚽",
    "date": "Sun 27 Apr", "time": "16:00", "channel": "SuperSport 3",
    "home_form": ["W", "W", "W", "D", "W"], "away_form": ["W", "W", "L", "W", "W"],
    "home_odds": 1.85, "home_bookie": "Betway",
    "draw_odds": 3.40, "draw_bookie": "Hollywoodbets",
    "away_odds": 4.20, "away_bookie": "Sportingbet",
    "h2h": {"n": 10, "hw": 4, "d": 2, "aw": 4},
    "stats": [
        {"label": "Goals/Game", "value": "2.6", "context": "Home"},
        {"label": "Clean Sheets", "value": "55%", "context": "City"},
    ],
    "home_injuries": ["Rodri (Out)", "De Bruyne (Doubtful)"],
    "away_injuries": ["Saliba (Doubtful)", "Saka (Out)", "Ødegaard (Knock)"],
    "analysis_text": "",  # canonical shows no analysis section
    "edge_badge_tier":  "diamond",
    "edge_badge_label": "DIAMOND EDGE",
    "edge_badge_emoji": "💎",
}


def render_html(template_name: str, data: dict) -> str:
    tmpl = _env.get_template(template_name)
    return tmpl.render(**data)


def visual_diff(png_bytes: bytes, canonical_png_path: Path) -> tuple[float, int, str]:
    """Return (mean_diff, max_diff, notes) in pixel values [0-255].

    Compares by cropping both to the minimum shared dimensions, then
    doing a pixel-exact diff. Avoids interpolation artifacts from resize.
    """
    rendered = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    canonical = Image.open(canonical_png_path).convert("RGB")
    notes = ""

    rw, rh = rendered.size
    cw, ch = canonical.size

    if (rw, rh) != (cw, ch):
        notes = f"size mismatch rendered=({rw},{rh}) canonical=({cw},{ch})"
        print(f"  ⚠ {notes}")
        # Height-only difference: crop both to min height for pixel diff
        if rw == cw:
            min_h = min(rh, ch)
            diff_h = abs(rh - ch)
            print(f"    Width matches — cropping to min_h={min_h} (diff={diff_h}px logical={diff_h//2}px)")
            rendered  = rendered.crop((0, 0, rw, min_h))
            canonical = canonical.crop((0, 0, cw, min_h))
        else:
            notes += " width mismatch — SKIP pixel diff"
            return 999.0, 999, notes

    r_arr = np.array(rendered, dtype=np.int32)
    c_arr = np.array(canonical, dtype=np.int32)
    diff  = np.abs(r_arr - c_arr)
    mean_d = float(diff.mean())
    max_d  = int(diff.max())
    if max_d > 0:
        # Report where the worst diff is
        idx = np.unravel_index(diff.max(axis=2).argmax(), diff.shape[:2])
        notes += f" | worst pixel at row={idx[0]} col={idx[1]}"
    return mean_d, max_d, notes


def process_card(template_name: str, data: dict, canonical_html_name: str,
                 canonical_png_path: Path, width: int = 480) -> bool:
    print(f"\n{'='*60}")
    print(f"  Card: {template_name}")
    print(f"  Canonical HTML → {canonical_html_name}")
    print(f"  Canonical PNG  → {canonical_png_path.name}")

    # Step 1: Render to HTML and deposit as canonical
    html_str = render_html(template_name, data)
    out_html = CANONICAL_DIR / canonical_html_name
    out_html.write_text(html_str, encoding="utf-8")
    print(f"  ✓ Canonical HTML deposited ({len(html_str):,} bytes)")

    # Step 2: Render to PNG
    print(f"  Rendering PNG via Playwright…")
    png_bytes = render_card_sync(template_name, data, width=width)
    print(f"  ✓ PNG rendered ({len(png_bytes):,} bytes)")

    # Step 3: Save render for inspection
    render_path = CANONICAL_DIR / canonical_html_name.replace(".html", "_render_check.png")
    render_path.write_bytes(png_bytes)
    print(f"  ✓ Render saved → {render_path.name}")

    # Step 4: Visual diff vs canonical PNG
    if canonical_png_path.exists():
        mean_diff, max_diff, notes = visual_diff(png_bytes, canonical_png_path)
        print(f"  Visual diff — mean={mean_diff:.2f}  max={max_diff}px  [{notes}]")
        if max_diff <= 2:
            print(f"  ✓ PASS — max diff {max_diff} ≤ 2px")
            return True
        elif max_diff == 999:
            print(f"  ✗ FAIL — {notes}")
            return False
        else:
            print(f"  ✗ FAIL — max diff {max_diff} > 2px (tolerance 2px)")
            return False
    else:
        print(f"  ⚠ Canonical PNG not found: {canonical_png_path}")
        return False


def main():
    print("WAVE-F-MIN-01 — Canonical HTML Deposit")
    print(f"  Bot root:      {BOT_ROOT}")
    print(f"  Canonical dir: {CANONICAL_DIR}")

    results = {}

    # ── Card 1: my_matches ───────────────────────────────────────────────────
    my_matches_data = build_my_matches_data([EDGE_MATCH_1, EDGE_MATCH_2, PLAIN_MATCH_1, PLAIN_MATCH_2], page=1)
    results["my_matches"] = process_card(
        template_name="my_matches.html",
        data=my_matches_data,
        canonical_html_name="my_matches_canonical.html",
        canonical_png_path=CANONICAL_DIR / "my_matches_canonical.png",
    )

    # ── Card 2: match_detail (with_edge variant) ─────────────────────────────
    match_detail_data = build_match_detail_data(DETAIL_MATCH_WITH_EDGE)
    results["match_detail"] = process_card(
        template_name="match_detail.html",
        data=match_detail_data,
        canonical_html_name="match_detail_canonical.html",
        canonical_png_path=CANONICAL_DIR / "match_detail_canonical_with_edge.png",
        width=480,
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Summary:")
    all_pass = True
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n✓ Both cards deposited and visual diff passed.")
        sys.exit(0)
    else:
        print("\n✗ One or more cards failed visual diff.")
        sys.exit(1)


if __name__ == "__main__":
    main()
