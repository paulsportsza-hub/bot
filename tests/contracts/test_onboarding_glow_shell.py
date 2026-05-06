from pathlib import Path

import pytest


BOT_ROOT = Path(__file__).resolve().parents[2]

ONBOARDING_TEMPLATES = [
    "onboarding_risk.html",
    "onboarding_bankroll.html",
    "onboarding_bankroll_custom.html",
    "onboarding_notify.html",
]


@pytest.mark.parametrize("template_name", ONBOARDING_TEMPLATES)
def test_onboarding_subflow_cards_use_canonical_glow_shell(template_name: str) -> None:
    html = (BOT_ROOT / "card_templates" / template_name).read_text()

    assert 'class="logo-glow"' in html
    assert 'class="logo-glow-screen"' in html
    assert ".logo-glow" in html
    assert ".logo-glow-screen" in html
    assert "step-progress" in html
    assert "step-dot" in html
    assert "step-badge" not in html


@pytest.mark.parametrize("template_name", ONBOARDING_TEMPLATES)
def test_onboarding_subflow_cards_preserve_logo_binding(template_name: str) -> None:
    html = (BOT_ROOT / "card_templates" / template_name).read_text()

    assert "{% if header_logo_b64 %}" in html
    assert 'src="{{ header_logo_b64 }}"' in html
    assert "{% else %}" in html
    assert "logo-fallback" in html


def test_notify_progress_dots_remain_data_driven() -> None:
    html = (BOT_ROOT / "card_templates" / "onboarding_notify.html").read_text()

    assert "{% for i in range(total_steps) %}" in html
    assert "Step {{ step }} of {{ total_steps }}" in html
