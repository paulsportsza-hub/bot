from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "card_templates" / "match_detail.html"


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_match_detail_uses_canonical_match_family_upper_glow_zone():
    text = _template_text()

    assert 'class="upper-glow-zone"' in text
    assert 'class="upper-glow"' in text
    assert 'class="upper-glow-screen"' in text
    assert "ellipse 35% 130% at 92% 50%" in text
    assert "ellipse 22% 100% at 92% 50%" in text
    assert "{{ _glow }}10" in text
    assert "{{ _glow }}07" in text
    assert "{{ _glow }}1A" in text
    assert "{{ _glow }}0D" in text


def test_match_detail_upper_glow_resolves_tier_without_adapter_color():
    text = _template_text()

    assert "{% set _tier_glow =" in text
    assert "edge_badge_tier | default" in text
    assert "edge_badge_color | default" in text
    assert '_tier_glow.get(_tier, "#F7931A")' in text


def test_match_detail_is_adaptive_height_variant():
    text = _template_text()

    assert "height: 620px" not in text
    assert "width: 480px" in text
