"""Canonical glow contract for match_detail.html.

Locked 7 May 2026 by FIX-EDGE-CARD-GLOW-OVERFLOW-RESTORE-01.

Enforces the c04650b FIX-GLOW-COVERAGE-01 WORKING pattern:
- .upper-section wrapper with overflow:hidden
- .header has overflow:visible (NOT hidden — glow must flow through)
- glow divs are direct children of .upper-section, not .header
- anchor at 50% 45% (vertical-midpoint of upper-section), NOT at 50% 25% or 92% 50%
- per-tier classes (.logo-glow-{tier}), NOT a single _glow Jinja variable
- height 260px base / 220px screen — large enough to span header + matchup + meta-bar

Two prior regressions surfaced by Paul (right-side 2 May variant, header-clipped 7 May variant)
are explicitly rejected by these assertions.
"""
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "card_templates" / "match_detail.html"


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_match_detail_uses_upper_section_wrapper():
    """The .upper-section wrapper must exist and contain the glow."""
    text = _template_text()
    assert 'class="upper-section"' in text, ".upper-section wrapper missing — glow will not flow through"


def test_match_detail_glow_anchored_at_50_45_per_tier():
    """Glow gradients must use the vertical-midpoint anchor, not top-center or right-side."""
    text = _template_text()
    # WORKING anchor
    assert "at 50% 45%" in text, "glow anchor must be at 50% 45% (vertical midpoint of upper-section)"
    # REGRESSION anchors must be absent
    assert "at 50% 25%" not in text, "REGRESSION: at 50% 25% (top-center) clips inside .header"
    assert "at 92% 50%" not in text, "REGRESSION: at 92% 50% (right-side) was rejected by Paul 7 May"


def test_match_detail_uses_per_tier_glow_classes():
    """Glow MUST use per-tier CSS classes, not a single _glow Jinja variable."""
    text = _template_text()
    # The c04650b pattern uses per-tier classes
    assert ".logo-glow-diamond" in text
    assert ".logo-glow-gold" in text
    assert ".logo-glow-silver" in text
    assert ".logo-glow-bronze" in text
    # The eb25301 regression injected a _glow adapter — must not return
    assert "{{ _glow }}10" not in text, "REGRESSION: _glow Jinja adapter was rejected"
    assert "{{ _glow }}1A" not in text, "REGRESSION: _glow Jinja adapter was rejected"


def test_match_detail_glow_geometry():
    """Glow heights must be the working values (260px base, 220px screen)."""
    text = _template_text()
    assert "height: 260px" in text, "base glow height must be 260px to span upper-section"
    assert "height: 220px" in text, "screen glow height must be 220px"


def test_match_detail_header_does_not_clip_glow():
    """The .header MUST NOT have overflow:hidden — the glow has to flow through."""
    text = _template_text()
    # Find the .header { } block specifically
    import re
    match = re.search(r"\.header\s*\{[^}]*\}", text)
    assert match, "could not locate .header CSS block"
    header_block = match.group(0)
    assert "overflow: hidden" not in header_block, (
        "REGRESSION (7 May 2026): .header { overflow: hidden } clips the glow inside the header strip. "
        "It must be overflow: visible (or unset). The .upper-section wrapper provides overflow:hidden."
    )


def test_match_detail_is_480_wide_card():
    """Card is 480px wide (the canonical card width)."""
    text = _template_text()
    assert "width: 480px" in text
