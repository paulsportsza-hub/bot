"""Contract tests for canonical-lane commit discipline (OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01).

Locked rules:
  - `scripts/canonical_lane_check.sh` MUST exist + be executable.
  - `.githooks/pre-commit` MUST exist + be executable + invoke the canonical check.
  - `scripts/install_git_hooks.sh` MUST exist + be executable.
  - The check MUST exit 1 on mixed canonical/+non-canonical/ staging.
  - The check MUST exit 0 on canonical-only OR non-canonical-only staging.
  - The check MUST exit 0 (with warning) when ALLOW_CANONICAL_MIX=1.
  - CLAUDE.md MUST reference the OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01 amendment.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "canonical_lane_check.sh"
HOOK_SCRIPT = REPO_ROOT / ".githooks" / "pre-commit"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install_git_hooks.sh"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def _is_executable(p: Path) -> bool:
    return p.exists() and bool(p.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def _run_check(args: list[str], allow_mix: bool = False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["ALLOW_CANONICAL_MIX"] = "1" if allow_mix else "0"
    return subprocess.run(
        ["bash", str(CHECK_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=10,
    )


class TestArtifactsExist:
    def test_canonical_lane_check_exists_and_executable(self):
        assert CHECK_SCRIPT.exists(), f"missing {CHECK_SCRIPT}"
        assert _is_executable(CHECK_SCRIPT), f"not executable: {CHECK_SCRIPT}"

    def test_pre_commit_hook_exists_and_executable(self):
        assert HOOK_SCRIPT.exists(), f"missing {HOOK_SCRIPT}"
        assert _is_executable(HOOK_SCRIPT), f"not executable: {HOOK_SCRIPT}"

    def test_install_script_exists_and_executable(self):
        assert INSTALL_SCRIPT.exists(), f"missing {INSTALL_SCRIPT}"
        assert _is_executable(INSTALL_SCRIPT), f"not executable: {INSTALL_SCRIPT}"

    def test_pre_commit_hook_invokes_canonical_check(self):
        body = HOOK_SCRIPT.read_text()
        assert "scripts/canonical_lane_check.sh" in body, (
            "pre-commit hook does not invoke canonical_lane_check.sh"
        )

    def test_claude_md_documents_amendment(self):
        body = CLAUDE_MD.read_text()
        assert "OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01" in body, (
            "CLAUDE.md missing OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01 amendment"
        )
        # Brief Path A wording: "atomic-commit-only" + pre-commit hook reference.
        assert "atomic-commit-only" in body, (
            "CLAUDE.md amendment missing 'atomic-commit-only' Path A wording"
        )


class TestCanonicalLaneCheck:
    def test_mixed_staging_rejected(self):
        result = _run_check(["README.md", "static/qa-gallery/canonical/foo.png"])
        assert result.returncode == 1, (
            f"mixed staging should exit 1, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert "Canonical lane discipline violation" in result.stderr

    def test_canonical_only_accepted(self):
        result = _run_check(
            [
                "static/qa-gallery/canonical/foo.png",
                "static/qa-gallery/canonical/index.html",
            ]
        )
        assert result.returncode == 0, (
            f"canonical-only should exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )

    def test_non_canonical_only_accepted(self):
        result = _run_check(["README.md", "scripts/foo.py", "tests/test_bar.py"])
        assert result.returncode == 0, (
            f"non-canonical-only should exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )

    def test_empty_input_accepted(self):
        # Empty staged set (e.g. `git commit --allow-empty`) — must not block.
        result = subprocess.run(
            ["bash", str(CHECK_SCRIPT), "-"],
            input="",
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=10,
        )
        assert result.returncode == 0, (
            f"empty staged set should exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )

    def test_allow_mix_override_accepted(self):
        result = _run_check(
            ["README.md", "static/qa-gallery/canonical/foo.png"], allow_mix=True
        )
        assert result.returncode == 0, (
            f"ALLOW_CANONICAL_MIX=1 should exit 0, got {result.returncode}\nstderr: {result.stderr}"
        )
        assert "ALLOW_CANONICAL_MIX=1" in result.stderr

    def test_stdin_mode(self):
        # Mixed staging via stdin.
        result = subprocess.run(
            ["bash", str(CHECK_SCRIPT), "-"],
            input="README.md\nstatic/qa-gallery/canonical/foo.png\n",
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=10,
        )
        assert result.returncode == 1
        assert "Canonical lane discipline violation" in result.stderr

    def test_subdirectory_canonical_paths(self):
        # Ensure canonical/<subdir>/file.png is correctly classified.
        result = _run_check(
            [
                "README.md",
                "static/qa-gallery/canonical/onboarding/welcome.png",
            ]
        )
        assert result.returncode == 1, (
            "subdirectory canonical paths must also trigger the discipline check"
        )

    def test_canonical_prefix_only_match(self):
        # Files whose path *contains* `canonical` but does NOT start with the
        # locked prefix must NOT be classified as canonical.
        # E.g. `tests/qa/canonical_test.py` is just a test, not a canonical asset.
        result = _run_check(
            ["tests/qa/canonical_test.py", "scripts/canonical_lane_check.sh"]
        )
        assert result.returncode == 0, (
            "non-prefix matches must not be treated as canonical"
        )


class TestPreCommitHookOrdering:
    """The hook must run the canonical check BEFORE the secret scan + pre-merge gate.
    A canonical-mix violation should fail fast without spending CI time on a doomed
    commit.
    """

    def test_canonical_check_runs_before_secret_scan(self):
        body = HOOK_SCRIPT.read_text()
        canonical_idx = body.find("scripts/canonical_lane_check.sh")
        secret_idx = body.find("SECRET SCAN")
        assert canonical_idx >= 0
        assert secret_idx >= 0
        assert canonical_idx < secret_idx, (
            "canonical check must run before the secret scan in the hook"
        )

    def test_canonical_check_runs_before_pre_merge_gate(self):
        body = HOOK_SCRIPT.read_text()
        canonical_idx = body.find("scripts/canonical_lane_check.sh")
        gate_idx = body.find("scripts/pre_merge_gate.sh")
        assert canonical_idx >= 0
        assert gate_idx >= 0
        assert canonical_idx < gate_idx, (
            "canonical check must run before the pre-merge gate in the hook"
        )
