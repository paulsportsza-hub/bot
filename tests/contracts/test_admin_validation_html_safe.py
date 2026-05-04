"""FIX-EDGEOPS-VALIDATION-PARSE-MODE-01 — regression guard.

format_telegram_message() in post_deploy_validation.py must HTML-escape all
failure strings before embedding them in a parse_mode=HTML message.

Root cause: labels like "Draw ratio <= 40%" and "Signal coverage <= 50%"
contain bare `<` characters which Telegram's HTML parser rejects with:
  "Can't parse entities: unsupported start tag '=' at byte offset N"

The fix: html.escape() is applied to every failure string in format_telegram_message.
This covers `<=`, `>=`, and any other HTML-incompatible characters that could appear
in check labels or detail strings (e.g. "Missing <b> tags" in a detail).

Tests:
- AC-2a: `<=` operator in failure label is escaped to `&lt;=`
- AC-2b: `>=` operator in failure label is escaped to `&gt;=`
- AC-2c: `<b>` tag in detail string is escaped to `&lt;b&gt;`
- AC-2d: Clean message (no failures) is unchanged
- AC-2e: Multiple failures are all escaped
- AC-2f: Telegram HTML parse_mode would accept the escaped message (mock)
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))


def _make_report(failures: list[str], pass_count: int = 5, total: int = 10) -> dict:
    return {
        "pass_count": pass_count,
        "total": total,
        "failures": failures,
        "details": [],
        "trigger": "auto_startup",
        "duration_ms": 123.4,
    }


def _import_format_telegram_message():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "post_deploy_validation",
        str(Path(__file__).resolve().parents[2] / "tests" / "post_deploy_validation.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    # Stub out heavy imports so the module loads in isolation
    fake_config = types.ModuleType("config")
    fake_config.BOT_ROOT = Path("/tmp")

    def ensure_scrapers_importable():
        pass

    fake_config.ensure_scrapers_importable = ensure_scrapers_importable
    sys.modules.setdefault("config", fake_config)
    spec.loader.exec_module(mod)
    return mod.format_telegram_message


# ── AC-2a: <= is escaped ──────────────────────────────────────────────────────

def test_lte_operator_is_escaped():
    fmt = _import_format_telegram_message()
    report = _make_report(["Draw ratio <= 40%: 80% draws (4/5)"])
    msg = fmt(report)
    assert "<=" not in msg, "Bare '<=' must not appear in Telegram HTML output"
    assert "&lt;=" in msg, "HTML-escaped '&lt;=' must be present"


# ── AC-2b: >= is escaped ──────────────────────────────────────────────────────

def test_gte_operator_is_escaped():
    fmt = _import_format_telegram_message()
    report = _make_report(["Edge count >= 1: 0 edges"])
    msg = fmt(report)
    assert ">=" not in msg, "Bare '>=' must not appear in Telegram HTML output"
    assert "&gt;=" in msg, "HTML-escaped '&gt;=' must be present"


# ── AC-2c: <b> in detail is escaped ──────────────────────────────────────────

def test_html_tag_in_detail_is_escaped():
    fmt = _import_format_telegram_message()
    # This is the actual failure string produced when sanitize_ai_response
    # fails to produce <b> bold tags (check 3b in check_ai_pipeline)
    report = _make_report(["HTML bold present: Missing <b> tags"])
    msg = fmt(report)
    # The <b> must be escaped, not interpreted as a bold tag
    assert "<b> tags" not in msg, "Bare '<b>' in detail must be escaped"
    assert "&lt;b&gt;" in msg, "HTML-escaped '<b>' must appear"


# ── AC-2d: Clean (no failures) message is unchanged ───────────────────────────

def test_pass_message_contains_no_escaped_entities():
    fmt = _import_format_telegram_message()
    report = _make_report(failures=[], pass_count=10, total=10)
    msg = fmt(report)
    assert "PASS" in msg
    # Should not have any escaped entities from failure labels
    assert "&lt;=" not in msg
    assert "&gt;=" not in msg


# ── AC-2e: Multiple failures are all escaped ──────────────────────────────────

def test_multiple_failures_all_escaped():
    fmt = _import_format_telegram_message()
    report = _make_report([
        "Draw ratio <= 40%: 80% draws (4/5)",
        "Signal coverage <= 50%: 2 violations",
        "Edge count >= 1: 0 edges",
    ])
    msg = fmt(report)
    assert "<=" not in msg, "No bare '<=' should remain"
    assert ">=" not in msg, "No bare '>=' should remain"
    assert msg.count("&lt;=") == 2, "Two lte operators should be escaped"
    assert msg.count("&gt;=") == 1, "One gte operator should be escaped"


# ── AC-2f: The escaped message is valid for Telegram parse_mode=HTML ──────────

def test_output_passes_basic_html_tag_validation():
    """Verify no unescaped < or > appear outside of intentional HTML tags."""
    fmt = _import_format_telegram_message()
    report = _make_report([
        "Draw ratio <= 40%: 80% draws",
        "Signal coverage <= 50%: 1 violation",
        "Edge count >= 3: 0 edges",
    ])
    msg = fmt(report)

    # Strip known-valid HTML tags: <b>, </b>, <i>, </i>
    without_tags = re.sub(r"</?(?:b|i)>", "", msg)

    # After removing valid tags, no bare < or > should remain
    assert "<" not in without_tags, f"Unescaped '<' found outside HTML tags:\n{msg}"
    assert ">" not in without_tags, f"Unescaped '>' found outside HTML tags:\n{msg}"


# ── AC-2g: Real-shape labels from ALL_CHECKS are safe ────────────────────────

def test_all_known_comparison_labels_are_safe():
    """Exhaustive check against every label that contains <= or >= in the suite."""
    fmt = _import_format_telegram_message()
    comparison_labels = [
        "Edge count >= 1",
        "Edge count >= 3",
        "Draw ratio <= 40%",
        "Signal coverage <= 50%",
    ]
    for label in comparison_labels:
        report = _make_report([f"{label}: some detail"])
        msg = fmt(report)
        assert "<=" not in msg, f"Bare '<=' from label '{label}' leaked into HTML"
        assert ">=" not in msg, f"Bare '>=' from label '{label}' leaked into HTML"
