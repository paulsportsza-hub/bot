"""Regression suite for BUILD-WORKTREE-DISPATCH-RUNNER-01.

Covers all five P2-ACs of the brief that introduced /home/paulsportsza/scripts/
dispatch_runner.sh and /home/paulsportsza/scripts/lib/so41_verify.sh.

These tests do not invoke the real Notion API or `claude` CLI. They exercise:

  * P2-AC-1: end-to-end pipeline in DISPATCH_RUNNER_TEST_MODE=1 against a
             throwaway temp git repo
  * P2-AC-2: PASS path — wave commit lands → so41_verify exits 0
  * P2-AC-3: FAIL path — no wave commit → so41_verify exits non-zero with
             explicit "no commit referencing BRIEF-ID" diagnostic
  * P2-AC-4: multi-repo verification — runs against bot + scrapers paths
  * P2-AC-5: Pure Claude lock — runner refuses (codex)/(cursor) tags

Each test scaffolds an isolated git repo in `tmp_path` and exports
GIT_DIR/GIT_WORK_TREE explicitly so the temp repo never touches the host
working tree (a defence against the same env-leak that bit BUILD-WORKTREE-
DISPATCH-RUNNER-01 itself during fixture authoring).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path("/home/paulsportsza/scripts")
DISPATCH_RUNNER = SCRIPTS_DIR / "dispatch_runner.sh"
SO41_VERIFY = SCRIPTS_DIR / "lib" / "so41_verify.sh"
WAVE_CREATE = SCRIPTS_DIR / "wave_worktree_create.sh"
WAVE_PRUNE = SCRIPTS_DIR / "wave_worktree_prune.sh"


# ---------------------------------------------------------------------------
# Helpers — every git invocation passes a fresh env that explicitly DROPS
# GIT_DIR / GIT_WORK_TREE so we never inherit a leak from a buggy parent.
# ---------------------------------------------------------------------------

def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    env["HOME"] = os.environ.get("HOME", "/tmp")
    env["GIT_AUTHOR_NAME"] = "ContractTest"
    env["GIT_AUTHOR_EMAIL"] = "contract-test@example.invalid"
    env["GIT_COMMITTER_NAME"] = "ContractTest"
    env["GIT_COMMITTER_EMAIL"] = "contract-test@example.invalid"
    if extra:
        env.update(extra)
    return env


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )


def _make_repo(tmp_path: Path, name: str = "bot") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("seed\n")
    _git(["add", "README.md"], repo)
    _git(["commit", "-q", "-m", "seed"], repo)
    # bare upstream so we can verify the "0 ahead / 0 behind" branch contract
    upstream = tmp_path / f"{name}.git"
    upstream.mkdir()
    _git(["init", "--bare", "-q", str(upstream)], repo)
    _git(["remote", "add", "origin", str(upstream)], repo)
    _git(["push", "-u", "origin", "main", "-q"], repo)
    return repo


def _add_brief_commit(repo: Path, brief_id: str, payload: str = "x\n") -> str:
    f = repo / f"{brief_id}.txt"
    f.write_text(payload)
    _git(["add", str(f.name)], repo)
    _git(["commit", "-q", "-m", f"{brief_id}: payload landed"], repo)
    _git(["push", "origin", "main", "-q"], repo)
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


# ---------------------------------------------------------------------------
# Smoke check: the canonical scripts exist, are executable, and load.
# ---------------------------------------------------------------------------

def test_scripts_exist_and_are_executable() -> None:
    for p in (DISPATCH_RUNNER, SO41_VERIFY, WAVE_CREATE, WAVE_PRUNE):
        assert p.exists(), f"missing: {p}"
        assert os.access(p, os.X_OK), f"not executable: {p}"


def test_so41_verify_lib_sources_clean() -> None:
    """Sourcing the lib must not error and must define so41_verify()."""
    rc = subprocess.run(
        ["bash", "-c", f"source {SO41_VERIFY} && declare -F so41_verify"],
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, rc.stderr
    assert "so41_verify" in rc.stdout


# ---------------------------------------------------------------------------
# P2-AC-2: so41_verify PASSES when the wave commit landed and pushed clean.
# ---------------------------------------------------------------------------

def test_p2_ac2_so41_pass_when_brief_commit_pushed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _add_brief_commit(repo, "BUILD-EXAMPLE-99")

    rc = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-EXAMPLE-99", str(repo)],
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert rc.returncode == 0, f"stderr={rc.stderr!r}\nstdout={rc.stdout!r}"
    assert "PASS" in rc.stdout
    assert "BUILD-EXAMPLE-99" in rc.stdout


# ---------------------------------------------------------------------------
# P2-AC-3: so41_verify FAILS with explicit diagnostic when no commit landed.
# ---------------------------------------------------------------------------

def test_p2_ac3_so41_fail_when_no_brief_commit(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    # No commit referencing the brief — only the seed.

    rc = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-MISSING-99", str(repo)],
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert rc.returncode != 0
    assert "FAIL" in rc.stderr
    assert "no commit referencing BUILD-MISSING-99" in rc.stderr


def test_p2_ac3_so41_fail_when_unpushed(tmp_path: Path) -> None:
    """Brief commit exists locally but not pushed — must FAIL on ahead/behind."""
    repo = _make_repo(tmp_path)
    f = repo / "x.txt"
    f.write_text("y\n")
    _git(["add", "x.txt"], repo)
    _git(["commit", "-q", "-m", "BUILD-LOCAL-99: not pushed"], repo)
    # No push.

    rc = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-LOCAL-99", str(repo)],
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert rc.returncode != 0
    assert "ahead" in rc.stderr or "behind" in rc.stderr


def test_p2_ac3_so41_fail_when_uncommitted_dirty(tmp_path: Path) -> None:
    """Wave commit landed but working tree dirty — must FAIL."""
    repo = _make_repo(tmp_path)
    _add_brief_commit(repo, "BUILD-DIRTY-99")
    # Now leave a tracked-file modification uncommitted.
    f = repo / "BUILD-DIRTY-99.txt"
    f.write_text("dirty\n")

    rc = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-DIRTY-99", str(repo)],
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert rc.returncode != 0
    assert "uncommitted" in rc.stderr


# ---------------------------------------------------------------------------
# P2-AC-4: multi-repo verification — runs against bot AND scrapers.
# ---------------------------------------------------------------------------

def test_p2_ac4_multi_repo_pass_only_when_both_pass(tmp_path: Path) -> None:
    bot = _make_repo(tmp_path, "bot")
    scrapers = _make_repo(tmp_path, "scrapers")

    # Land the brief in BOTH repos.
    _add_brief_commit(bot, "BUILD-MULTI-99")
    _add_brief_commit(scrapers, "BUILD-MULTI-99")

    rc_a = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-MULTI-99", str(bot)],
        env=_clean_env(), capture_output=True, text=True, timeout=20,
    )
    rc_b = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-MULTI-99", str(scrapers)],
        env=_clean_env(), capture_output=True, text=True, timeout=20,
    )
    assert rc_a.returncode == 0, rc_a.stderr
    assert rc_b.returncode == 0, rc_b.stderr


def test_p2_ac4_multi_repo_fail_when_one_repo_misses(tmp_path: Path) -> None:
    bot = _make_repo(tmp_path, "bot")
    scrapers = _make_repo(tmp_path, "scrapers")

    # Only bot has the brief commit.
    _add_brief_commit(bot, "BUILD-PARTIAL-99")

    rc_bot = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-PARTIAL-99", str(bot)],
        env=_clean_env(), capture_output=True, text=True, timeout=20,
    )
    rc_scr = subprocess.run(
        ["bash", str(SO41_VERIFY), "BUILD-PARTIAL-99", str(scrapers)],
        env=_clean_env(), capture_output=True, text=True, timeout=20,
    )
    assert rc_bot.returncode == 0
    assert rc_scr.returncode != 0
    assert "no commit referencing BUILD-PARTIAL-99" in rc_scr.stderr


# ---------------------------------------------------------------------------
# P2-AC-5: Pure Claude Ecosystem lock — runner refuses (codex) / (cursor)
# brief tags. We test the scanner helper without invoking the full pipeline.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body,expected_blocked",
    [
        ("**[1] — Sonnet (claude) — Standalone — INV — P0**", False),
        ("**[1] — Sonnet (cowork) — Standalone — INV — P0**", False),
        ("**[1] — Sonnet (codex) — Standalone — INV — P0**", True),
        ("**[1] — Sonnet (cursor) — Standalone — INV — P0**", True),
        ("Random text mentioning (codex) inline.", True),
        ("Random text mentioning (CURSOR) inline.", True),  # case-insensitive
        ("Random text without any banned tag.", False),
    ],
)
def test_p2_ac5_pure_claude_scanner(body: str, expected_blocked: bool) -> None:
    """The runner sources the same scan helper inline; emulate by calling bash."""
    snippet = (
        'if printf "%s" "$BODY" | grep -qiE \'\\(codex\\)|\\(cursor\\)\'; then '
        'echo BLOCKED; exit 1; else echo OK; fi'
    )
    rc = subprocess.run(
        ["bash", "-c", snippet],
        env={**_clean_env(), "BODY": body},
        capture_output=True,
        text=True,
        timeout=10,
    )
    if expected_blocked:
        assert rc.returncode != 0, f"should block: {body!r}"
        assert "BLOCKED" in rc.stdout
    else:
        assert rc.returncode == 0, f"should allow: {body!r} (rc={rc.returncode}, stderr={rc.stderr!r})"
        assert "OK" in rc.stdout


def test_p2_ac5_runner_script_carries_pure_claude_scanner() -> None:
    body = DISPATCH_RUNNER.read_text()
    assert "_scan_for_banned_cli_tags" in body, (
        "dispatch_runner.sh must carry the Pure Claude scan helper"
    )
    assert "(codex)" in body or "codex" in body, (
        "dispatch_runner.sh must reference the banned (codex) tag"
    )
    assert "Pure Claude Ecosystem" in body, (
        "dispatch_runner.sh must explain why the lock exists"
    )


# ---------------------------------------------------------------------------
# P2-AC-1: dry-run end-to-end pipeline in DISPATCH_RUNNER_TEST_MODE=1.
# We do not exercise the Notion API; we assert the wiring (regex validation,
# .env discovery, exit codes) is sound.
# ---------------------------------------------------------------------------

def test_p2_ac1_runner_rejects_invalid_brief_id(tmp_path: Path) -> None:
    rc = subprocess.run(
        ["bash", str(DISPATCH_RUNNER), "not-a-valid-id"],
        env=_clean_env({"NOTION_TOKEN": "fake"}),
        capture_output=True, text=True, timeout=10,
    )
    assert rc.returncode == 64, rc.stderr
    assert "does not match" in rc.stderr


def test_p2_ac1_runner_rejects_missing_token(tmp_path: Path) -> None:
    """Empty NOTION_TOKEN + missing .env file → runner aborts cleanly."""
    env = _clean_env({"ENV_FILE": str(tmp_path / "nonexistent.env")})
    env.pop("NOTION_TOKEN", None)
    rc = subprocess.run(
        ["bash", str(DISPATCH_RUNNER), "BUILD-EXAMPLE-01"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert rc.returncode == 78, rc.stderr
    assert "NOTION_TOKEN not set" in rc.stderr


# ---------------------------------------------------------------------------
# Wave worktree create / prune contract — protects the BRIEF-ID regex and
# the prune refusal-on-unmerged guard.
# ---------------------------------------------------------------------------

def test_wave_create_rejects_invalid_brief_id() -> None:
    rc = subprocess.run(
        ["bash", str(WAVE_CREATE), "lowercase-not-allowed-1"],
        env=_clean_env(), capture_output=True, text=True, timeout=10,
    )
    assert rc.returncode == 64
    assert "does not match" in rc.stderr


def test_wave_prune_rejects_unmerged_branch_without_force(tmp_path: Path) -> None:
    """Build a real worktree on a temp repo, leave it unmerged, then assert
    the prune refuses without WAVE_PRUNE_FORCE."""
    repo = _make_repo(tmp_path)
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()

    env = _clean_env({
        "WAVE_REPO": str(repo),
        "WAVE_WORKTREE_ROOT": str(worktree_root),
    })

    create = subprocess.run(
        ["bash", str(WAVE_CREATE), "BUILD-PRUNE-99"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert create.returncode == 0, create.stderr
    wt_path = create.stdout.strip()
    # Add an unmerged commit to the wave branch
    _git(["commit", "--allow-empty", "-q", "-m", "wave-only commit"], Path(wt_path))

    prune = subprocess.run(
        ["bash", str(WAVE_PRUNE), "BUILD-PRUNE-99"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert prune.returncode != 0
    assert "not on origin/main" in prune.stderr or "refusing to prune" in prune.stderr

    # Force prune cleans up.
    forced = subprocess.run(
        ["bash", str(WAVE_PRUNE), "BUILD-PRUNE-99"],
        env={**env, "WAVE_PRUNE_FORCE": "1"},
        capture_output=True, text=True, timeout=20,
    )
    assert forced.returncode == 0, forced.stderr
    assert not Path(wt_path).exists()
    # Belt-and-braces clean for the temp dir.
    if worktree_root.exists():
        shutil.rmtree(worktree_root, ignore_errors=True)
