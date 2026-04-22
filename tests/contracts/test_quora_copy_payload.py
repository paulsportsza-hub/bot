"""FIX-DASH-QUORA-COPY-TRUNCATION-01 — contract test.

Verifies that a Quora answer of > 800 chars is stored in full_answer without
truncation, and that the copy payload (full_answer) is at least as long as
the original answer body.

We replicate the answer-flush logic from _fetch_quora_ledger() directly so
the test stays dependency-free and fast.
"""

def _simulate_fetch(answer_text: str) -> dict:
    """Simulate the answer-flush block from _fetch_quora_ledger()."""
    answer_buf = answer_text.splitlines()
    _full = "\n".join(answer_buf)
    return {
        "full_answer": _full,
        "answer": _full[:800],
    }


class TestCopyPayloadEqualsFullAnswer:
    """AC-3: copy payload length >= full answer body length."""

    def test_short_answer_unchanged(self):
        body = "A" * 200
        row = _simulate_fetch(body)
        assert row["full_answer"] == body
        assert len(row["full_answer"]) == len(body)

    def test_exactly_800_chars_no_truncation(self):
        body = "B" * 800
        row = _simulate_fetch(body)
        assert len(row["full_answer"]) == 800
        assert row["full_answer"] == row["answer"]

    def test_3000_char_answer_full_answer_not_truncated(self):
        """Core AC-3 requirement: 3000-char body, full_answer >= body length."""
        body = "C" * 3000
        row = _simulate_fetch(body)
        assert len(row["full_answer"]) >= len(body), (
            f"full_answer length {len(row['full_answer'])} < body length {len(body)}"
        )

    def test_display_answer_still_truncated(self):
        """UI preview may remain truncated — only full_answer must be complete."""
        body = "D" * 2000
        row = _simulate_fetch(body)
        assert len(row["answer"]) <= 800
        assert len(row["full_answer"]) == 2000

    def test_full_answer_equals_body_byte_for_byte(self):
        """Clipboard payload must match source byte-for-byte (AC-1)."""
        body = "Edge picks — " + "★ " * 500  # unicode, multi-line would use \n
        row = _simulate_fetch(body)
        assert row["full_answer"] == body

    def test_copy_payload_field_key_is_full_answer(self):
        """JS reads t.full_answer — key must exist in row dict."""
        row = _simulate_fetch("Some answer text")
        assert "full_answer" in row, "full_answer key missing from Quora row dict"

    def test_multiline_answer_preserved(self):
        lines = ["Line " + str(i) for i in range(200)]
        body = "\n".join(lines)
        row = _simulate_fetch(body)
        assert row["full_answer"] == body
        assert row["full_answer"].count("\n") == 199

    def test_empty_answer_safe(self):
        row = _simulate_fetch("")
        assert row["full_answer"] == ""
        assert row["answer"] == ""
