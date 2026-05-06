"""Contract tests for the canonical my_matches card shell."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "card_templates" / "my_matches.html"


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _css_rule(selector: str, text: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\s*\}}", text, re.S)
    assert match, f"missing CSS rule for {selector}"
    return match.group("body")


def test_my_matches_header_uses_canonical_logo_glow_without_header_background():
    text = _template_text()
    header_css = _css_rule(".header", text)

    assert ".logo-glow" in text
    assert ".logo-glow-screen" in text
    assert 'class="logo-glow"' in text
    assert 'class="logo-glow-screen"' in text
    assert "background: linear-gradient(180deg" not in header_css


def test_my_matches_keeps_compact_text_bookmaker_and_dynamic_bindings():
    text = _template_text()

    assert "bk-logo" not in text
    assert "{{ total_matches }}" in text
    assert "{{ total_edges }}" in text
    assert "{{ match.tier_color }}" in text
    assert "{{ match.tier_emoji }}" in text
    assert "{{ match.bookmaker }}" in text
