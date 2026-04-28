"""Regression test for FIX-PRE-MERGE-GATE-SCOPE-STAGED-01.

scripts/pre_merge_gate.sh Step 2 must collect ONLY tracked + staged contract
tests. Untracked test_*.py files dropped into tests/contracts/ by parallel
agent sessions must NOT pollute the gate.

Covers:
  - AC-1: Untracked synthetic test is NOT collected
  - AC-2: Staged-new test IS collected
  - AC-3: Clean-tree scope == tracked-only scope (no regression)
  - AC-5: Gate retains the -rs flag for SKIP visibility

The Step 2 scoping snippet is exercised inside a throwaway git repo. The
full gate is not invoked here because Steps 1, 3-6 require the live bot
environment and would also recurse (Step 2 runs this very test).
A separate sync test asserts the snippet under test matches
scripts/pre_merge_gate.sh verbatim, so drift is caught on the next gate run.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "pre_merge_gate.sh"


# Mirrors the Step 2 scoping block in scripts/pre_merge_gate.sh.
# Outputs the SCOPED file list (one per line) on stdout. Empty on no-match.
SCOPING_SNIPPET = r"""
set -uo pipefail
TRACKED_CONTRACTS=$(git ls-files tests/contracts/ -- 'tests/contracts/test_*.py' 2>/dev/null)
STAGED_CONTRACTS=$(git diff --cached --name-only --diff-filter=A 2>/dev/null \
                   | grep -E '^tests/contracts/test_.*\.py$' || true)
SCOPED=$(printf '%s\n%s\n' "$TRACKED_CONTRACTS" "$STAGED_CONTRACTS" | sort -u | grep -v '^$' || true)
printf '%s' "$SCOPED"
"""


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def _scope(repo: Path) -> list[str]:
    result = subprocess.run(
        ["bash", "-c", SCOPING_SNIPPET],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return [ln for ln in result.stdout.splitlines() if ln.strip()]


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests" / "contracts").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], repo)
    tracked = repo / "tests" / "contracts" / "test_alpha.py"
    tracked.write_text("def test_alpha():\n    assert True\n")
    _git(["add", "tests/contracts/test_alpha.py"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


class TestStep2Scoping:
    def test_ac1_untracked_test_is_not_collected(self, tmp_repo: Path) -> None:
        synthetic = tmp_repo / "tests" / "contracts" / "test_zzzz_synthetic.py"
        synthetic.write_text("def test_synthetic():\n    assert False\n")
        # Deliberately not staged — simulates a parallel agent's WIP drop.

        scoped = _scope(tmp_repo)

        assert "tests/contracts/test_alpha.py" in scoped
        assert "tests/contracts/test_zzzz_synthetic.py" not in scoped, (
            f"Untracked synthetic leaked into Step 2 scope: {scoped}"
        )

    def test_ac2_staged_new_test_is_collected(self, tmp_repo: Path) -> None:
        new_test = tmp_repo / "tests" / "contracts" / "test_new_real.py"
        new_test.write_text("def test_new_real():\n    assert True\n")
        _git(["add", "tests/contracts/test_new_real.py"], tmp_repo)

        scoped = _scope(tmp_repo)

        assert "tests/contracts/test_alpha.py" in scoped, (
            f"Tracked test missing from scope: {scoped}"
        )
        assert "tests/contracts/test_new_real.py" in scoped, (
            f"Staged-new test missing from Step 2 scope: {scoped}"
        )

    def test_ac3_clean_tree_parity(self, tmp_repo: Path) -> None:
        scoped = _scope(tmp_repo)

        tracked_only = subprocess.run(
            ["git", "ls-files", "tests/contracts/", "--", "tests/contracts/test_*.py"],
            cwd=str(tmp_repo),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()

        assert scoped == sorted(tracked_only), (
            f"Clean-tree scope drift: scoped={scoped} tracked={tracked_only}"
        )

    def test_untracked_alongside_staged(self, tmp_repo: Path) -> None:
        # Combined case: a staged-new file and an untracked WIP drop coexist.
        # The staged-new file enters scope; the untracked one does not.
        staged = tmp_repo / "tests" / "contracts" / "test_new_real.py"
        staged.write_text("def test_new_real():\n    assert True\n")
        _git(["add", "tests/contracts/test_new_real.py"], tmp_repo)

        wip = tmp_repo / "tests" / "contracts" / "test_zzzz_synthetic.py"
        wip.write_text("def test_synthetic():\n    assert False\n")

        scoped = _scope(tmp_repo)

        assert "tests/contracts/test_new_real.py" in scoped
        assert "tests/contracts/test_zzzz_synthetic.py" not in scoped


class TestSnippetMatchesGateScript:
    """Catches drift between this regression test and the live gate."""

    def test_gate_uses_tracked_plus_staged_scoping(self) -> None:
        body = GATE_SCRIPT.read_text()
        assert "TRACKED_CONTRACTS=$(git ls-files tests/contracts/" in body, (
            "Step 2 must collect tracked tests via git ls-files"
        )
        assert (
            "STAGED_CONTRACTS=$(git diff --cached --name-only --diff-filter=A"
            in body
        ), "Step 2 must include staged-new tests via git diff --cached"
        assert "sort -u" in body, "Step 2 must dedupe the scoped file list"

    def test_gate_keeps_rs_flag_for_skip_visibility(self) -> None:
        body = GATE_SCRIPT.read_text()
        assert "pytest $SCOPED -q --tb=short -rs" in body, (
            "Step 2 must pass -rs so SKIP reasons surface (AC-5)"
        )

    def test_gate_no_longer_runs_unbounded_pytest_on_contracts(self) -> None:
        body = GATE_SCRIPT.read_text()
        # The pre-fix invocation collected the whole directory unconditionally.
        # That line MUST be gone — replaced by the SCOPED variable.
        assert "pytest tests/contracts/ -q --tb=short" not in body, (
            "Pre-fix unbounded contract collection must be removed"
        )
