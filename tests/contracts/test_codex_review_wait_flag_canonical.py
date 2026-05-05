"""
Regression guard: FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01

Asserts that no canonical doc contains a bare /codex:review or
/codex:adversarial-review invocation without the --wait flag on the same line.

Excludes:
  - Lines that are themselves documentation of the bare command
    (i.e. lines containing "bypasses", "interactive", "without --wait",
     "background task", example/docstring markers)
  - Lines inside <example> markers (AC-5 carve-out)
"""
import re
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parents[2]  # bot/
_COWORK_ROOT = pathlib.Path("/home/paulsportsza")

CANONICAL_DOCS = [
    _REPO_ROOT / "ops" / "DEV-STANDARDS.md",
    _COWORK_ROOT / "ops" / "DEV-STANDARDS.md",  # symlink → same file, kept for explicitness
]

# Lines containing any of these strings are excluded from the check
_EXCLUSION_PATTERNS = [
    "--wait",          # the correct form — already has the flag
    "bypasses",        # explanation text
    "interactive",     # explanation text
    "without --wait",  # explanation text ("without --wait" describes the bad case)
    "background task", # explanation text
    "<example>",       # inside example block
    "</example>",      # inside example block
]

# Regex that matches a bare invocation (no --wait on the line)
_BARE_REVIEW_RE = re.compile(r"`?/codex:review(?!\s+--wait)(?:`|\s|$)")
_BARE_ADVERSARIAL_RE = re.compile(r"`?/codex:adversarial-review(?!\s+--wait)(?:`|\s|$)")


def _is_excluded(line: str) -> bool:
    return any(pat in line for pat in _EXCLUSION_PATTERNS)


def _check_doc(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return list of (line_number, line_text) that violate the rule."""
    violations = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []  # doc may only exist on Cowork — skip silently

    inside_example = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "<example>" in line:
            inside_example = True
        if "</example>" in line:
            inside_example = False
        if inside_example:
            continue
        if _is_excluded(line):
            continue
        if _BARE_REVIEW_RE.search(line) or _BARE_ADVERSARIAL_RE.search(line):
            violations.append((lineno, line.strip()))
    return violations


def test_dev_standards_no_bare_codex_review():
    """DEV-STANDARDS.md must not contain bare /codex:review without --wait."""
    path = _REPO_ROOT / "ops" / "DEV-STANDARDS.md"
    violations = _check_doc(path)
    assert violations == [], (
        f"Bare /codex:review (without --wait) found in {path}:\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
    )


def test_dev_standards_no_bare_codex_adversarial_review():
    """DEV-STANDARDS.md must not contain bare /codex:adversarial-review without --wait."""
    path = _REPO_ROOT / "ops" / "DEV-STANDARDS.md"
    violations = [
        (ln, txt) for ln, txt in _check_doc(path)
        if "/codex:adversarial-review" in txt
    ]
    assert violations == [], (
        f"Bare /codex:adversarial-review (without --wait) found in {path}:\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
    )


def test_spawn_sequence_reminder_present():
    """spawn_sequence.py kickoff message must mention --wait for codex review."""
    path = _COWORK_ROOT / "dispatch" / "cmux_bridge" / "spawn_sequence.py"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return  # server-only file; skip on Cowork
    assert "--wait" in text and "codex:review" in text, (
        "spawn_sequence.py kickoff must include --wait reminder for /codex:review"
    )
