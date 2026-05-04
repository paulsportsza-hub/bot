"""Contract: qa_baseline scripts must not unconditionally forward raw messages to EdgeOps.

INV-EDGEOPS-NOISE-AUDIT-V3-01 (Patterns C + E).
FIX-QA-BASELINE-RAW-FORWARD-CUT-01.
"""
from pathlib import Path

SCRIPTS_DIR = Path("/home/paulsportsza/scripts")

TARGETS = [
    "qa_baseline_02_telethon.py",
    "qa_baseline_02_capture.py",
]

FORBIDDEN = "forward_messages(EDGEOPS_CHANNEL"


def _source(filename: str) -> str:
    path = SCRIPTS_DIR / filename
    assert path.exists(), f"Script not found: {path}"
    return path.read_text()


def test_telethon_no_edgeops_raw_forward():
    src = _source("qa_baseline_02_telethon.py")
    assert FORBIDDEN not in src, (
        f"qa_baseline_02_telethon.py must not call forward_messages(EDGEOPS_CHANNEL "
        f"at module-default code paths (FIX-QA-BASELINE-RAW-FORWARD-CUT-01)"
    )


def test_capture_no_edgeops_raw_forward():
    src = _source("qa_baseline_02_capture.py")
    assert FORBIDDEN not in src, (
        f"qa_baseline_02_capture.py must not call forward_messages(EDGEOPS_CHANNEL "
        f"at module-default code paths (FIX-QA-BASELINE-RAW-FORWARD-CUT-01)"
    )


def test_telethon_has_local_summary():
    src = _source("qa_baseline_02_telethon.py")
    assert "edgeops_summary" in src, (
        "qa_baseline_02_telethon.py must write structured local summary to captures['edgeops_summary']"
    )


def test_capture_has_local_summary():
    src = _source("qa_baseline_02_capture.py")
    assert "local_forward_summary" in src, (
        "qa_baseline_02_capture.py must record local_forward_summary in each capture entry"
    )
