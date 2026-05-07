"""Canonical glow contract for edge_detail.html.

Sister to test_match_detail_canonical.py. Locked 7 May 2026 by
DOCS-GLOW-CANONICAL-LOCK-01.

Enforces the c04650b FIX-GLOW-COVERAGE-01 WORKING pattern on edge_detail:
- .upper-glow-zone wrapper with overflow:hidden
- .header has overflow:visible (NOT hidden)
- glow divs are direct children of .upper-glow-zone, not .header
- anchor at 50% 45% (vertical-midpoint of upper section), NOT at 50% 25% or 92% 50%
- per-tier classes (.logo-glow-{tier}), NOT a single _glow Jinja variable
- height 260px base / 220px screen

Two prior regressions (right-side 2 May, header-clipped 7 May) explicitly rejected.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "card_templates" / "edge_detail.html"


def _template_text() -> str:
    return _strip_top_comment(TEMPLATE.read_text(encoding="utf-8"))

def _strip_top_comment(text: str) -> str:
    """Strip the leading <!-- CANONICAL CARD GLOW — LOCKED ... --> comment.
    The lock comment intentionally contains rejected patterns ("at 50% 25%",
    "overflow: hidden") as documented examples. Tests must scope assertions
    to live CSS, not the lock-stamp comment.
    """
    if text.startswith("<!--"):
        end = text.find("-->")
        if end != -1:
            text = text[end + 3:].lstrip()
    return text



def test_edge_detail_uses_upper_glow_zone_wrapper():
    text = _template_text()
    assert 'class="upper-glow-zone"' in text, ".upper-glow-zone wrapper missing"


def test_edge_detail_glow_anchored_at_50_45_per_tier():
    text = _template_text()
    assert "at 50% 45%" in text, "glow anchor must be at 50% 45%"
    assert "at 50% 25%" not in text, "REGRESSION: at 50% 25% (top-center) clips inside .header"
    assert "at 92% 50%" not in text, "REGRESSION: at 92% 50% (right-side) was rejected by Paul"


def test_edge_detail_uses_per_tier_glow_classes():
    text = _template_text()
    assert ".logo-glow-diamond" in text
    assert ".logo-glow-gold" in text
    assert ".logo-glow-silver" in text
    assert ".logo-glow-bronze" in text
    assert "{{ _glow }}10" not in text, "REGRESSION: _glow Jinja adapter rejected"
    assert "{{ _glow }}1A" not in text, "REGRESSION: _glow Jinja adapter rejected"


def test_edge_detail_glow_geometry():
    text = _template_text()
    assert "height: 260px" in text, "base glow height must be 260px"
    assert "height: 220px" in text, "screen glow height must be 220px"


def test_edge_detail_header_does_not_clip_glow():
    text = _template_text()
    # Find the .header { } block specifically
    match = re.search(r"\.header\s*\{[^}]*\}", text)
    assert match, "could not locate .header CSS block"
    header_block = match.group(0)
    assert "overflow: hidden" not in header_block, (
        "REGRESSION: .header { overflow: hidden } clips the glow. "
        ".upper-glow-zone wrapper provides overflow:hidden instead."
    )


def test_edge_detail_glow_is_first_child_of_wrapper():
    """Glow divs must be direct children of .upper-glow-zone, not .header."""
    text = _template_text()
    # Find <div class="upper-glow-zone"> ... <div class="header">
    m = re.search(
        r'<div class="upper-glow-zone">(.+?)<div class="header">',
        text,
        flags=re.DOTALL,
    )
    assert m, "could not locate .upper-glow-zone → .header sequence"
    between = m.group(1)
    assert "logo-glow" in between, (
        "Glow divs must sit BETWEEN .upper-glow-zone open tag and .header open tag, "
        "as direct children of .upper-glow-zone."
    )
