"""
Regression guard: SO #45 pure-codex review gate.

Pure-codex dispatch must direct agents to spawn a fresh inline
``codex --profile xhigh exec`` review sub-agent after commit + push.
The ``/codex:review --wait`` slash path remains canonical only for explicit
hybrid-mode Claude-executor briefs.
"""
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parents[2]  # bot/
_COWORK_ROOT = pathlib.Path("/home/paulsportsza")

_DEV_STANDARDS = _REPO_ROOT / "ops" / "DEV-STANDARDS.md"
_SERVER_SPAWN_SEQUENCE = _COWORK_ROOT / "dispatch" / "cmux_bridge" / "spawn_sequence.py"
_BOT_MIRROR_SPAWN_SEQUENCE = (
    _REPO_ROOT / "infra" / "dispatch" / "bridge" / "spawn_sequence.py"
)
_SPAWN_SEQUENCE_SURFACES = [
    _SERVER_SPAWN_SEQUENCE,
    _BOT_MIRROR_SPAWN_SEQUENCE,
]


def test_dev_standards_documents_pure_codex_inline_subagent():
    text = _DEV_STANDARDS.read_text(encoding="utf-8")
    required = [
        "### Pure-Codex Sub-Agent Review",
        "codex --profile xhigh exec",
        "## Codex Sub-Agent Review",
        "Outcome: clean | blockers-addressed | needs-changes",
        "Hybrid mode unchanged",
        "/codex:review --wait",
    ]
    missing = [needle for needle in required if needle not in text]
    assert missing == []


def test_dev_standards_limits_wait_slash_to_hybrid_mode():
    text = _DEV_STANDARDS.read_text(encoding="utf-8")
    hybrid_idx = text.index("Hybrid mode unchanged")
    wait_idx = text.index("/codex:review --wait", hybrid_idx)
    inline_idx = text.index("codex --profile xhigh exec")

    assert inline_idx < hybrid_idx
    assert wait_idx > hybrid_idx


def test_spawn_sequence_review_gate_present_on_available_surfaces():
    if _COWORK_ROOT.exists():
        assert _SERVER_SPAWN_SEQUENCE.exists()
    assert _BOT_MIRROR_SPAWN_SEQUENCE.exists()

    checked = []

    for path in _SPAWN_SEQUENCE_SURFACES:
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8")
        checked.append(path)

        required = [
            "SO #45 REVIEW GATE",
            "codex --profile xhigh exec",
            "## Codex Sub-Agent Review",
            "Outcome: clean | blockers-addressed | needs-changes",
            "HYBRID-MODE CAVEAT",
            "DISPATCH_MODE=hybrid",
            "/codex:review --wait",
        ]
        missing = [needle for needle in required if needle not in text]
        assert missing == [], f"{path} missing {missing}"

        caveat_idx = text.index("HYBRID-MODE CAVEAT")
        wait_idx = text.index("/codex:review --wait")
        assert wait_idx > caveat_idx
        assert "always pass --wait" not in text
        assert "codex --profile xhigh exec --quiet" not in text

    assert checked, "No spawn_sequence.py surfaces were available to check"
