"""BUILD-SANITIZER-MARKDOWN-STRIP-01 — Contract tests for markdown sanitizer.

Tests _strip_markdown() in bot.py and validate_no_markdown_leak() in
narrative_spec.py, plus their integration into min_verdict_quality().

Covers: bold mid-sentence, bold at start, italic, backticks, header line,
bullet line, blockquote, double-bold (__), and the FORGE-02 #11 regression.
"""
import sys
import os

# Allow importing from the bot directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from narrative_spec import validate_no_markdown_leak, min_verdict_quality


# ── Import _strip_markdown from bot without triggering Sentry ────────────────

def _get_strip_markdown():
    """Import _strip_markdown via grep+exec to avoid Sentry SDK init."""
    import re as _re
    bot_path = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
    source = open(bot_path).read()
    # Extract the function definition (bounded by def _fix_orphan_back below it)
    m = _re.search(
        r'(def _strip_markdown\(text.*?)(?=\ndef _fix_orphan_back)',
        source,
        _re.DOTALL,
    )
    assert m, "_strip_markdown not found in bot.py"
    namespace: dict = {"re": _re}
    exec(m.group(1), namespace)  # noqa: S102
    return namespace["_strip_markdown"]


_strip_markdown = _get_strip_markdown()


# ── _strip_markdown unit tests ───────────────────────────────────────────────

class TestStripMarkdown:
    """BUILD-SANITIZER-MARKDOWN-STRIP-01: _strip_markdown() output tests."""

    def test_bold_mid_sentence(self):
        """**word** in middle of sentence → plain word."""
        result = _strip_markdown("The **Signals active** are doing the heavy lifting.")
        assert "**" not in result
        assert "Signals active" in result

    def test_bold_at_start(self):
        """**Bold** at start of sentence → plain text."""
        result = _strip_markdown("**Back the home side** — form is strong.")
        assert "**" not in result
        assert "Back the home side" in result

    def test_bold_double_underscore(self):
        """__text__ → plain text."""
        result = _strip_markdown("__Value pick__ — back the draw.")
        assert "__" not in result
        assert "Value pick" in result

    def test_italic_asterisk(self):
        """*italic* → plain text."""
        result = _strip_markdown("Price is *interesting* at 2.10.")
        assert result.count("*") == 0
        assert "interesting" in result

    def test_italic_underscore(self):
        """_italic_ → plain text."""
        result = _strip_markdown("The _away_ side looks vulnerable.")
        assert "_away_" not in result
        assert "away" in result

    def test_backticks(self):
        """`code` → plain text."""
        result = _strip_markdown("Edge signal `composite_score` is above threshold.")
        assert "`" not in result
        assert "composite_score" in result

    def test_header_line(self):
        """# Header and ## Header at start of line → removed."""
        result = _strip_markdown("## The Verdict\nBack the home side.")
        assert "#" not in result
        assert "The Verdict" in result
        assert "Back the home side" in result

    def test_bullet_line(self):
        """- bullet and * bullet at start of line → plain text."""
        result = _strip_markdown("- Back the home side.\n* Consider the draw.")
        assert not result.startswith("-")
        lines = result.strip().splitlines()
        assert not any(line.startswith(("- ", "* ")) for line in lines)
        assert "Back the home side" in result

    def test_blockquote(self):
        """> blockquote → plain text."""
        result = _strip_markdown("> This is a quoted verdict.")
        assert not result.startswith(">")
        assert "This is a quoted verdict" in result

    def test_preserves_em_dash(self):
        """Em dashes — must survive sanitization."""
        original = "Back the Reds — form is excellent — this is the play."
        result = _strip_markdown(original)
        assert result.count("—") == 2

    def test_preserves_apostrophe(self):
        """Apostrophes in contractions and possessives must survive."""
        original = "Arteta's Arsenal haven't looked back."
        result = _strip_markdown(original)
        assert "Arteta's" in result
        assert "haven't" in result

    def test_preserves_exclamation(self):
        """Exclamation marks must survive."""
        result = _strip_markdown("What a result! Back the home side.")
        assert "!" in result

    def test_empty_string(self):
        """Empty input returns empty output."""
        assert _strip_markdown("") == ""

    def test_clean_input_unchanged(self):
        """Plain text with no markdown passes through unchanged."""
        original = "Back the home side at 1.85 — solid form and a fair price."
        assert _strip_markdown(original) == original

    def test_forge02_candidate_11_regression(self):
        """Regression: FORGE-02 #11 Ospreys v Leinster leaked bold verdict.

        Original verdict had **Signals active** — must be stripped and
        validate_no_markdown_leak must pass on result.
        """
        leaked = (
            "**Signals active** are doing the heavy lifting here — "
            "Leinster's composite edge holds up at 2.10. Back Leinster."
        )
        stripped = _strip_markdown(leaked)
        assert "**" not in stripped
        assert "Signals active" in stripped
        assert validate_no_markdown_leak(stripped)


# ── validate_no_markdown_leak unit tests ────────────────────────────────────

class TestValidateNoMarkdownLeak:
    """BUILD-SANITIZER-MARKDOWN-STRIP-01: validate_no_markdown_leak() tests."""

    def test_clean_verdict_passes(self):
        """Plain prose verdict passes the validator."""
        assert validate_no_markdown_leak(
            "Back the home side at 1.85 — solid form and a fair price."
        )

    def test_bold_fails(self):
        """** in verdict fails validator."""
        assert not validate_no_markdown_leak("**Back** the home side.")

    def test_double_underscore_fails(self):
        """__ in verdict fails validator."""
        assert not validate_no_markdown_leak("__Back__ the home side.")

    def test_backtick_fails(self):
        """`code` in verdict fails validator."""
        assert not validate_no_markdown_leak("Edge `composite` at 2.10.")

    def test_header_fails(self):
        """# at start of line fails validator."""
        assert not validate_no_markdown_leak("# Verdict\nBack the home side.")

    def test_blockquote_fails(self):
        """> at start of line fails validator."""
        assert not validate_no_markdown_leak("> Back the home side.")

    def test_empty_string_passes(self):
        """Empty string passes (nothing to leak)."""
        assert validate_no_markdown_leak("")


# ── min_verdict_quality integration tests ───────────────────────────────────

class TestMinVerdictQualityMarkdownGate:
    """Gate 7 of min_verdict_quality rejects markdown-leaked verdicts."""

    _GOOD_VERDICT = (
        "Back the home side at 1.85 — solid form and this price carries "
        "genuine expected value over the market implied probability."
    )

    def test_clean_verdict_passes_gate7(self):
        """Clean verdict still passes min_verdict_quality."""
        assert min_verdict_quality(self._GOOD_VERDICT)

    def test_bold_leaked_verdict_fails_gate7(self):
        """Verdict with ** fails min_verdict_quality (Gate 7)."""
        leaked = (
            "**Back** the home side at 1.85 — solid form and this price carries "
            "genuine expected value over the market implied probability."
        )
        assert not min_verdict_quality(leaked)

    def test_backtick_leaked_verdict_fails_gate7(self):
        """Verdict with backtick fails min_verdict_quality (Gate 7)."""
        leaked = (
            "Back the home side at `1.85` — solid form and this price carries "
            "genuine expected value over the market implied probability."
        )
        assert not min_verdict_quality(leaked)
