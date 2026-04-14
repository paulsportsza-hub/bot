"""BUILD-EDGE-COUNT-FIX-01 contract: _load_tips_from_edge_results is the primary
path in _edge_precompute_job, with _fetch_hot_tips_from_db as fallback only.

Root cause: precompute was calling _fetch_hot_tips_from_db_inner() (returns
3 tips / 0 football) instead of _load_tips_from_edge_results() (returns
18 tips / 15 football).
"""
from __future__ import annotations

import inspect
import os
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))
os.chdir(str(_REPO_ROOT))

import bot


class TestEdgeCountFix01:
    """Structural contract: stable path is primary in precompute job."""

    def _precompute_source(self) -> str:
        return inspect.getsource(bot._edge_precompute_job)

    def test_stable_path_called_before_fragile_path(self) -> None:
        """_load_tips_from_edge_results must appear before _fetch_hot_tips_from_db
        in _edge_precompute_job source — stable path is primary."""
        src = self._precompute_source()
        stable_idx = src.find("_load_tips_from_edge_results")
        fragile_idx = src.find("_fetch_hot_tips_from_db()")
        assert stable_idx != -1, "_load_tips_from_edge_results not found in _edge_precompute_job"
        assert fragile_idx != -1, "_fetch_hot_tips_from_db() not found in _edge_precompute_job"
        assert stable_idx < fragile_idx, (
            "_load_tips_from_edge_results must appear BEFORE _fetch_hot_tips_from_db in "
            "_edge_precompute_job — stable path must be primary"
        )

    def test_fallback_guarded_by_empty_check(self) -> None:
        """_fetch_hot_tips_from_db() must only be called in an else-branch when
        edge_results is empty — never unconditionally."""
        src = self._precompute_source()
        fragile_idx = src.find("_fetch_hot_tips_from_db()")
        assert fragile_idx != -1
        # The fallback must be preceded by 'else' within a reasonable window
        preceding = src[max(0, fragile_idx - 200):fragile_idx]
        assert "else" in preceding, (
            "_fetch_hot_tips_from_db() must be inside an else-branch in _edge_precompute_job "
            "(called only when edge_results is empty)"
        )

    def test_contract_violation_warning_tag_present(self) -> None:
        """Fallback must log contract_violation=edge_results_empty."""
        src = self._precompute_source()
        assert "contract_violation" in src, (
            "_edge_precompute_job must log contract_violation when edge_results is empty"
        )
        assert "edge_results_empty" in src, (
            "_edge_precompute_job must tag fallback with contract_violation='edge_results_empty'"
        )
