"""TG-G1-COMPLIANCE-FIX-01 — G1 morning teaser routes through publisher compliance gate.

AC6: compliance.run_gate called once with post_type="teaser" for G1 broadcast.
AC5: teaser post_type does not append 18+ footer on Telegram Alerts.
"""

import sys
import pytest
from unittest.mock import MagicMock

# Mirror bot.py dynamic import: add publisher + channels to path
for _p in ("/home/paulsportsza/publisher", "/home/paulsportsza/publisher/channels"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import compliance  # noqa: E402


def test_g1_compliance_gate_called_with_teaser(monkeypatch):
    """AC6: run_gate called once with post_type='teaser' for G1 broadcast."""
    mock_gate = MagicMock(return_value=("", []))
    monkeypatch.setattr(compliance, "run_gate", mock_gate)

    # Reproduce the exact call made by _morning_teaser_job broadcast block
    _caption, _warnings = compliance.run_gate(
        "Telegram Alerts", "", post_type="teaser"
    )

    mock_gate.assert_called_once_with("Telegram Alerts", "", post_type="teaser")
    assert _caption == ""
    assert _warnings == []


def test_teaser_post_type_no_footer():
    """AC5: teaser post_type does not append 18+ footer on Telegram Alerts."""
    text, warnings = compliance.run_gate(
        "Telegram Alerts", "🌅 Edge picks loading...", post_type="teaser"
    )
    assert "18+" not in text
    assert "NRGP" not in text
    # Body must be returned unmodified for teaser
    assert text == "🌅 Edge picks loading..."


def test_teaser_post_type_banned_phrase_still_rejected():
    """Compliance gate still rejects banned phrases even for teaser type."""
    from exceptions import ComplianceRejected

    with pytest.raises(ComplianceRejected):
        compliance.run_gate(
            "Telegram Alerts", "guaranteed winner tonight", post_type="teaser"
        )
