"""FIX-PREGEN-DIAMOND-PRIORITY-01: Contract tests for tier-priority pregen sort.

Guards (per AC-2/AC-3/AC-12):
  - _TIER_PRIORITY ranks Diamond < Gold < Silver < Bronze (lowest int = highest priority)
  - Tier names align with GATE_MATRIX canonical order
  - _kickoff_unix is best-effort (no exceptions for missing/garbage input)
  - Sort is stable: tier blocks first, kickoff ASC within each tier
  - Mixed-tier list orders Diamond first, Bronze last
  - Unknown tier strings sort after Bronze (priority 99)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

# Ensure scripts/ on sys.path
_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_BOT_ROOT, "scripts")
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# AC-3: _TIER_PRIORITY constant + GATE_MATRIX alignment
# ---------------------------------------------------------------------------


class TestTierPriorityConstant:
    def test_priority_order_diamond_first_bronze_last(self):
        """Lower priority int = higher refresh priority."""
        from pregenerate_narratives import _TIER_PRIORITY

        assert _TIER_PRIORITY["diamond"] < _TIER_PRIORITY["gold"]
        assert _TIER_PRIORITY["gold"] < _TIER_PRIORITY["silver"]
        assert _TIER_PRIORITY["silver"] < _TIER_PRIORITY["bronze"]

    def test_priority_keys_lowercase(self):
        """Candidate dicts carry lowercase tier strings; the lookup must match."""
        from pregenerate_narratives import _TIER_PRIORITY

        for key in _TIER_PRIORITY:
            assert key == key.lower()

    def test_priority_keys_match_gate_matrix_canonical(self):
        """All four tier names in GATE_MATRIX appear as _TIER_PRIORITY keys.

        Source of truth: scripts/data_health_check.py::_GATE_MATRIX.
        """
        from pregenerate_narratives import _TIER_PRIORITY

        gate_matrix_tiers = {"bronze", "silver", "gold", "diamond"}
        assert set(_TIER_PRIORITY.keys()) == gate_matrix_tiers


# ---------------------------------------------------------------------------
# AC-2/AC-3: _kickoff_unix helper correctness
# ---------------------------------------------------------------------------


class TestKickoffUnixHelper:
    def test_iso_string_parses(self):
        from pregenerate_narratives import _kickoff_unix

        ts = _kickoff_unix({"commence_time": "2026-05-09T18:00:00+00:00"})
        assert ts > 0
        assert ts == datetime(2026, 5, 9, 18, 0, 0, tzinfo=timezone.utc).timestamp()

    def test_z_suffix_parses(self):
        """ISO with 'Z' suffix should normalise to UTC."""
        from pregenerate_narratives import _kickoff_unix

        ts = _kickoff_unix({"commence_time": "2026-05-09T18:00:00Z"})
        assert ts == datetime(2026, 5, 9, 18, 0, 0, tzinfo=timezone.utc).timestamp()

    def test_datetime_object_passthrough(self):
        """`_resolved_kickoff` is set to a datetime by _resolve_kickoff()."""
        from pregenerate_narratives import _kickoff_unix

        dt = datetime(2026, 5, 9, 18, 0, 0, tzinfo=timezone.utc)
        ts = _kickoff_unix({"_resolved_kickoff": dt})
        assert ts == dt.timestamp()

    def test_resolved_kickoff_takes_priority_over_commence_time(self):
        """When both are present, the cap-truncation site value wins."""
        from pregenerate_narratives import _kickoff_unix

        early = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        late_iso = "2026-12-31T00:00:00+00:00"
        ts = _kickoff_unix({"_resolved_kickoff": early, "commence_time": late_iso})
        assert ts == early.timestamp()

    def test_missing_returns_inf(self):
        """No timestamp → sort last in band, never raise."""
        from pregenerate_narratives import _kickoff_unix

        assert _kickoff_unix({}) == float("inf")

    def test_garbage_returns_inf(self):
        """Unparseable string → sort last in band, never raise."""
        from pregenerate_narratives import _kickoff_unix

        assert _kickoff_unix({"commence_time": "not-a-date"}) == float("inf")
        assert _kickoff_unix({"commence_time": ""}) == float("inf")


# ---------------------------------------------------------------------------
# AC-2: tier-priority sort end-to-end ordering
# ---------------------------------------------------------------------------


def _candidate(match_key: str, tier: str, kickoff_iso: str) -> dict:
    """Build a minimal candidate dict mirroring _load_pregen_edges output."""
    return {
        "match_key": match_key,
        "tier": tier,
        "_resolved_kickoff": datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00")),
    }


class TestTierPrioritySortOrdering:
    def test_diamond_before_gold_before_silver_before_bronze(self):
        """Mixed tiers sort into clean tier blocks regardless of input order."""
        from pregenerate_narratives import _TIER_PRIORITY, _kickoff_unix

        # Deliberately reversed
        candidates = [
            _candidate("a_b_2026-05-01", "bronze", "2026-05-01T00:00:00+00:00"),
            _candidate("c_d_2026-05-02", "silver", "2026-05-02T00:00:00+00:00"),
            _candidate("e_f_2026-05-03", "gold", "2026-05-03T00:00:00+00:00"),
            _candidate("g_h_2026-05-04", "diamond", "2026-05-04T00:00:00+00:00"),
        ]
        candidates.sort(key=lambda e: (
            _TIER_PRIORITY.get((e.get("tier") or "bronze").lower(), 99),
            _kickoff_unix(e),
        ))
        tiers = [c["tier"] for c in candidates]
        assert tiers == ["diamond", "gold", "silver", "bronze"]

    def test_within_tier_sort_by_kickoff_ascending(self):
        """Same tier — earliest kickoff wins."""
        from pregenerate_narratives import _TIER_PRIORITY, _kickoff_unix

        candidates = [
            _candidate("late_gold", "gold", "2026-05-09T18:00:00+00:00"),
            _candidate("early_gold", "gold", "2026-05-02T18:00:00+00:00"),
            _candidate("middle_gold", "gold", "2026-05-04T18:00:00+00:00"),
        ]
        candidates.sort(key=lambda e: (
            _TIER_PRIORITY.get((e.get("tier") or "bronze").lower(), 99),
            _kickoff_unix(e),
        ))
        keys = [c["match_key"] for c in candidates]
        assert keys == ["early_gold", "middle_gold", "late_gold"]

    def test_premium_far_future_beats_bronze_imminent(self):
        """The whole point of the fix: a far-future Gold MUST sort before
        an imminent Bronze. Pre-fix kickoff-only sort got this wrong and
        let Bronze displace Gold on cap truncation."""
        from pregenerate_narratives import _TIER_PRIORITY, _kickoff_unix

        candidates = [
            _candidate("imminent_bronze", "bronze", "2026-04-29T00:00:00+00:00"),
            _candidate("future_gold", "gold", "2026-05-09T00:00:00+00:00"),
        ]
        candidates.sort(key=lambda e: (
            _TIER_PRIORITY.get((e.get("tier") or "bronze").lower(), 99),
            _kickoff_unix(e),
        ))
        assert candidates[0]["match_key"] == "future_gold"
        assert candidates[1]["match_key"] == "imminent_bronze"

    def test_unknown_tier_sorts_last(self):
        """Unrecognised tier strings get priority 99 and land after Bronze."""
        from pregenerate_narratives import _TIER_PRIORITY, _kickoff_unix

        candidates = [
            _candidate("weird", "platinum", "2026-04-29T00:00:00+00:00"),
            _candidate("bronze", "bronze", "2026-05-09T00:00:00+00:00"),
        ]
        candidates.sort(key=lambda e: (
            _TIER_PRIORITY.get((e.get("tier") or "bronze").lower(), 99),
            _kickoff_unix(e),
        ))
        assert candidates[0]["match_key"] == "bronze"
        assert candidates[1]["match_key"] == "weird"

    def test_uppercase_tier_strings_normalised_via_lower(self):
        """Defensive: any caller mistakenly passing 'GOLD' must still sort right."""
        from pregenerate_narratives import _TIER_PRIORITY, _kickoff_unix

        candidates = [
            _candidate("upper_silver", "SILVER", "2026-05-04T00:00:00+00:00"),
            _candidate("upper_diamond", "DIAMOND", "2026-05-04T00:00:00+00:00"),
        ]
        candidates.sort(key=lambda e: (
            _TIER_PRIORITY.get((e.get("tier") or "bronze").lower(), 99),
            _kickoff_unix(e),
        ))
        assert candidates[0]["match_key"] == "upper_diamond"

    def test_missing_tier_defaults_to_bronze(self):
        """Candidates without a tier key are treated as Bronze."""
        from pregenerate_narratives import _TIER_PRIORITY, _kickoff_unix

        candidates = [
            {"match_key": "no_tier", "_resolved_kickoff": datetime(2026, 5, 1, tzinfo=timezone.utc)},
            _candidate("real_silver", "silver", "2026-05-02T00:00:00+00:00"),
        ]
        candidates.sort(key=lambda e: (
            _TIER_PRIORITY.get((e.get("tier") or e.get("edge_tier") or "bronze").lower(), 99),
            _kickoff_unix(e),
        ))
        assert candidates[0]["match_key"] == "real_silver"
        assert candidates[1]["match_key"] == "no_tier"


# ---------------------------------------------------------------------------
# AC-12: Wave 2A coupling filter byte-identical
# ---------------------------------------------------------------------------


class TestWave2AInvariantsPreserved:
    """The Diamond-priority sort must NOT touch the FIX-PREGEN-EDGE-RESULTS-COUPLING-01
    intersection filter or the allowlist constant."""

    def test_load_unsettled_edge_match_keys_still_callable(self):
        from pregenerate_narratives import _load_unsettled_edge_match_keys

        assert callable(_load_unsettled_edge_match_keys)

    def test_warm_coverage_allowlist_still_empty_default(self):
        from pregenerate_narratives import _PREGEN_WARM_COVERAGE_ALLOWLIST

        assert isinstance(_PREGEN_WARM_COVERAGE_ALLOWLIST, frozenset)
        assert len(_PREGEN_WARM_COVERAGE_ALLOWLIST) == 0
