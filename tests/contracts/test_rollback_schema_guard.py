"""Contract test: schema migration rollback guard.

BUILD-SCHEMA-MIGRATION-ROLLBACK-GUARD-01

AC-2: rollback compares target SHA's expected schema vs current schema_version.
AC-3: mismatch (target > current) → exit 5 + clear operator message.
AC-4: schema-compatible (target <= current) → rollback proceeds normally.
AC-5: simulates incompatible-schema rollback scenario.
"""
import os
import subprocess


def _script_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "scripts", "deploy_bot_prod_rollback.sh"))


def _make_migration_dir(parent, migration_nums: list) -> None:
    mdir = os.path.join(parent, "migrations")
    os.makedirs(mdir, exist_ok=True)
    for n in migration_nums:
        with open(os.path.join(mdir, f"{n:04d}_placeholder.py"), "w") as f:
            f.write(f"# placeholder migration {n}\n")


def _run_rollback(tmp_path, current_schema, prev_migrations: list, prod_migrations: list):
    """Set up fake prod/prev/shared trees and run rollback with DEPLOY_SKIP_RESTART=1."""
    shared = os.path.join(str(tmp_path), "shared")
    os.makedirs(shared, exist_ok=True)

    if current_schema is not None:
        with open(os.path.join(shared, "schema_version"), "w") as f:
            f.write(str(current_schema))

    prod = os.path.join(str(tmp_path), "bot-prod")
    os.makedirs(prod, exist_ok=True)
    _make_migration_dir(prod, prod_migrations)

    # The script derives PREV as "${PROD}-prev"
    prev = os.path.join(str(tmp_path), "bot-prod-prev")
    os.makedirs(prev, exist_ok=True)
    _make_migration_dir(prev, prev_migrations)

    env = {
        **os.environ,
        "DEPLOY_PROD_TREE": prod,
        "DEPLOY_SHARED": shared,
        "DEPLOY_SKIP_RESTART": "1",
    }
    result = subprocess.run(
        ["bash", _script_path()],
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


class TestSchemaGuardRefuses:
    def test_target_newer_schema_refused(self, tmp_path):
        """AC-3/AC-5: prev has migration v3, current schema_version=2 → exit 5."""
        rc, out = _run_rollback(tmp_path, current_schema=2, prev_migrations=[1, 2, 3], prod_migrations=[1, 2])
        assert rc == 5, f"Expected exit 5, got {rc}.\n{out}"
        assert "SCHEMA GUARD" in out, f"Expected SCHEMA GUARD in output:\n{out}"
        assert "manual schema audit" in out.lower(), f"Expected audit instruction:\n{out}"

    def test_error_message_includes_both_versions(self, tmp_path):
        """AC-3: error message names both target and current versions for operator clarity."""
        rc, out = _run_rollback(tmp_path, current_schema=1, prev_migrations=[1, 2], prod_migrations=[1])
        assert rc == 5
        assert "v2" in out, f"Expected target version 'v2' in output:\n{out}"
        assert "v1" in out, f"Expected current version 'v1' in output:\n{out}"

    def test_no_moves_made_when_guard_fires(self, tmp_path):
        """AC-3: guard fires before any filesystem mutations — prev dir still exists."""
        prev = os.path.join(str(tmp_path), "bot-prod-prev")
        rc, _ = _run_rollback(tmp_path, current_schema=2, prev_migrations=[1, 2, 3], prod_migrations=[1, 2])
        assert rc == 5
        assert os.path.isdir(prev), "bot-prod-prev must still exist — guard fired before any moves"


class TestSchemaGuardAllows:
    def test_equal_schemas_proceed(self, tmp_path):
        """AC-4: prev schema == current schema_version → rollback proceeds, exit 0."""
        rc, out = _run_rollback(tmp_path, current_schema=2, prev_migrations=[1, 2], prod_migrations=[1, 2])
        assert rc == 0, f"Expected exit 0, got {rc}.\n{out}"
        assert "schema guard OK" in out

    def test_older_target_schema_proceeds(self, tmp_path):
        """AC-4: prev schema v1 < current v3 → rollback proceeds (schema-compatible)."""
        rc, out = _run_rollback(tmp_path, current_schema=3, prev_migrations=[1], prod_migrations=[1, 2, 3])
        assert rc == 0, f"Expected exit 0, got {rc}.\n{out}"
        assert "schema guard OK" in out

    def test_no_schema_version_file_proceeds(self, tmp_path):
        """AC-4: missing schema_version file (pre-first-deploy) → guard skipped, proceeds."""
        rc, out = _run_rollback(tmp_path, current_schema=None, prev_migrations=[1], prod_migrations=[1])
        assert rc == 0, f"Expected exit 0, got {rc}.\n{out}"
        assert "guard skipped" in out

    def test_prev_has_no_migrations_dir_proceeds(self, tmp_path):
        """AC-4: prev tree has no migrations/ → treated as schema v0 → proceeds."""
        shared = os.path.join(str(tmp_path), "shared")
        os.makedirs(shared, exist_ok=True)
        with open(os.path.join(shared, "schema_version"), "w") as f:
            f.write("1")

        prod = os.path.join(str(tmp_path), "bot-prod")
        os.makedirs(prod, exist_ok=True)
        _make_migration_dir(prod, [1])

        prev = os.path.join(str(tmp_path), "bot-prod-prev")
        os.makedirs(prev, exist_ok=True)
        # No migrations dir in prev

        env = {
            **os.environ,
            "DEPLOY_PROD_TREE": prod,
            "DEPLOY_SHARED": shared,
            "DEPLOY_SKIP_RESTART": "1",
        }
        result = subprocess.run(["bash", _script_path()], env=env, capture_output=True, text=True)
        out = result.stdout + result.stderr
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}.\n{out}"
        assert "schema guard OK" in out
