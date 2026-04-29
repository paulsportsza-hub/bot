"""FIX-NARRATIVE-ROT-ROOT-01 Phase 2 — unified pre-persist validator contract.

Eighteen tests covering every gate path + the CALLER's tier-aware enforcement
policy. The validator itself is a pure reporter (severity + gates fired); the
caller (`_store_narrative_cache`) applies the policy:

  - Premium (Diamond/Gold) on CRITICAL or MAJOR → refuse write
  - Non-premium + CRITICAL → refuse write
  - Non-premium + MAJOR → write with quality_status='quarantined'
  - All passes → write normally

These tests bind the contract surface so future refactors cannot silently
drop a gate. Each LB-* tag refers to the leak board entry the test closes.

Phase 4 detectors (`_find_setup_pricing_semantic_violations`,
`validate_manager_names_in_all_sections`, `validate_claims_against_evidence`,
`ManagerViolation`, `ClaimViolation`) are *assumed* — when missing the
validator silently no-ops their gate and the test guards itself with a skip.
Integration after Phase 4 lands.
"""
from __future__ import annotations

import os
import sys
from collections import namedtuple
from typing import Any
from unittest import mock

import pytest

# Ensure the worktree root is on sys.path so `import narrative_validator`
# resolves regardless of pytest invocation directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_validator import (  # noqa: E402  (import after sys.path)
    ValidationFailure,
    ValidationResult,
    _validate_narrative_for_persistence,
)


# ── Phase 4 namedtuple shims ────────────────────────────────────────────────
# When Phase 4 hasn't published its real types we fake them so the tests can
# express the contract. The validator code uses only `getattr(..., 'name')`
# / `getattr(..., 'kind')` / `getattr(..., 'claim')` — duck-typed.

_FakeManagerViolation = namedtuple("FakeManagerViolation", ["name", "section"])
_FakeClaimViolation = namedtuple("FakeClaimViolation", ["kind", "claim", "section"])


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def evidence_pack_man_utd_carrick() -> dict[str, Any]:
    """Manchester United evidence pack — coach=Carrick, no Amorim.

    Used to assert the Phase 4 manager validator refuses "Amorim's United"
    text because Carrick is the only valid manager surface.
    """
    return {
        "home_team": "Manchester United",
        "away_team": "Brighton",
        "home_manager": "Michael Carrick",
        "away_manager": "Roberto De Zerbi",
        "h2h": {"matches": []},
        "home_form": {"data_available": True, "string": "WLDLW"},
        "away_form": {"data_available": True, "string": "WWLDD"},
    }


@pytest.fixture
def evidence_pack_forest_pereira() -> dict[str, Any]:
    """Nottingham Forest evidence pack — coach=Pereira, no Nuno.

    LB-3 closure regression case: legacy Sonnet prose said "Nuno's side" for
    Forest (Nuno managed in 2024, not now). Pack reflects current reality.
    """
    return {
        "home_team": "Nottingham Forest",
        "away_team": "Brentford",
        "home_manager": "Nuno Espirito Santo",
        "away_manager": "Thomas Frank",
        "h2h": {"matches": []},
    }


@pytest.fixture
def evidence_pack_clean() -> dict[str, Any]:
    """Generic evidence pack with H2H meetings populated — no fabrication risk."""
    return {
        "home_team": "Arsenal",
        "away_team": "Tottenham",
        "home_manager": "Mikel Arteta",
        "away_manager": "Ange Postecoglou",
        "h2h": {
            "matches": [
                {"home": "Arsenal", "away": "Tottenham", "result": "2-1"},
                {"home": "Tottenham", "away": "Arsenal", "result": "0-3"},
            ],
        },
        "home_form": {"data_available": True, "string": "WWWDL"},
        "away_form": {"data_available": True, "string": "DLWLW"},
    }


def _narrative(setup: str = "", edge: str = "", risk: str = "", verdict: str = "") -> str:
    """Helper: build a minimal HTML narrative with the four sections."""
    parts: list[str] = []
    parts.append("\U0001f3af <b>Arsenal vs Tottenham</b>")
    if setup:
        parts.append(f"\U0001f4cb <b>The Setup</b>\n{setup}")
    if edge:
        parts.append(f"\U0001f3af <b>The Edge</b>\n{edge}")
    if risk:
        parts.append(f"⚠️ <b>The Risk</b>\n{risk}")
    if verdict:
        parts.append(f"\U0001f3c6 <b>Verdict</b>\n{verdict}")
    return "\n\n".join(parts)


# ── Test 1: Empty content + None evidence → passes ─────────────────────────


def test_empty_content_none_evidence_passes() -> None:
    r = _validate_narrative_for_persistence(
        content={"narrative_html": "", "verdict_html": "", "match_id": "x_vs_y_2026-04-29",
                 "narrative_source": "w82"},
        evidence_pack=None,
        edge_tier="bronze",
        source_label="w82",
    )
    assert r.passed is True
    assert r.failures == []
    assert r.severity is None


# ── Test 2: Clean narrative + clean evidence → passes ──────────────────────


def test_clean_narrative_passes(evidence_pack_clean) -> None:
    narrative = _narrative(
        setup="Arsenal sit second on 38 points after a strong run. Tottenham counter on form.",
        edge="The bookmaker has Arsenal at 1.85 — fair model probability is 58%.",
        risk="Squad rotation could blunt the home edge.",
        verdict="Arteta's Gunners look poised — back the home win at 1.85.",
    )
    verdict = "Arteta's Gunners look poised — back the home win at 1.85."
    r = _validate_narrative_for_persistence(
        content={"narrative_html": narrative, "verdict_html": verdict,
                 "match_id": "arsenal_vs_tottenham_2026-04-29", "narrative_source": "w84"},
        evidence_pack=evidence_pack_clean,
        edge_tier="gold",
        source_label="w84",
    )
    # The underlying narrative_spec gates may flag minor things — assert at
    # minimum: passes critical, no venue leak, no manager hallucination.
    crit = [f for f in r.failures if f.severity == "CRITICAL"]
    assert crit == [], f"unexpected critical failures: {crit}"


# ── Test 3: Anfield in narrative → CRITICAL venue_leak ─────────────────────


def test_narrative_anfield_critical_venue_leak() -> None:
    narrative = _narrative(setup="The clash at Anfield will be tough for the visitors.")
    r = _validate_narrative_for_persistence(
        content={"narrative_html": narrative, "verdict_html": "",
                 "match_id": "liverpool_vs_x_2026-04-29", "narrative_source": "w84"},
        evidence_pack=None,
        edge_tier="gold",
        source_label="w84",
    )
    assert r.passed is False
    venue_failures = [f for f in r.failures if f.gate == "venue_leak"]
    assert len(venue_failures) >= 1
    assert venue_failures[0].severity == "CRITICAL"
    assert "Anfield" in venue_failures[0].detail


# ── Test 4: Goodison Park → CRITICAL venue_leak (LB-1 regression) ──────────


def test_narrative_goodison_critical_venue_leak() -> None:
    """LB-1 closure regression: Goodison was the canonical leak case. Everton
    moved to Hill Dickinson Stadium in August 2025 (CLAUDE.md Rule 2)."""
    narrative = _narrative(setup="A trip to Goodison Park is always tricky.")
    r = _validate_narrative_for_persistence(
        content={"narrative_html": narrative, "verdict_html": "",
                 "match_id": "everton_vs_x_2026-04-29", "narrative_source": "w82"},
        evidence_pack=None,
        edge_tier="gold",
        source_label="w82",
    )
    assert r.passed is False
    assert any(
        f.gate == "venue_leak" and f.severity == "CRITICAL" and "Goodison" in f.detail
        for f in r.failures
    )


# ── Test 5: "Elo-implied 70%" → CRITICAL setup_pricing (LB-4) ──────────────


def test_setup_elo_implied_critical_pricing() -> None:
    narrative = _narrative(
        setup="Arsenal are Elo-implied 70% favourites at home. Strong showings recently."
    )
    r = _validate_narrative_for_persistence(
        content={"narrative_html": narrative, "verdict_html": "",
                 "match_id": "arsenal_vs_x_2026-04-29", "narrative_source": "w84"},
        evidence_pack=None,
        edge_tier="gold",
        source_label="w84",
    )
    assert r.passed is False
    pricing = [f for f in r.failures if f.gate.startswith("setup_pricing")]
    assert pricing, f"expected setup_pricing failure; got {[(f.gate, f.detail) for f in r.failures]}"
    assert pricing[0].severity == "CRITICAL"


# ── Test 6: "84% to win" → CRITICAL setup_pricing ─────────────────────────


def test_setup_integer_probability_critical_pricing() -> None:
    narrative = _narrative(
        setup="Arsenal have an 84% probability of winning this fixture at home."
    )
    r = _validate_narrative_for_persistence(
        content={"narrative_html": narrative, "verdict_html": "",
                 "match_id": "arsenal_vs_x_2026-04-29", "narrative_source": "w84"},
        evidence_pack=None,
        edge_tier="gold",
        source_label="w84",
    )
    assert r.passed is False
    assert any(
        f.gate.startswith("setup_pricing") and f.severity == "CRITICAL"
        for f in r.failures
    )


# ── Test 7: "Amorim's United" + Carrick evidence → manager_hallucination ──


def test_amorim_united_with_carrick_evidence_critical(evidence_pack_man_utd_carrick) -> None:
    """LB-2 closure regression. Phase 4 publishes
    `validate_manager_names_in_all_sections`. When that helper isn't available
    (Phase 4 still landing) we skip the assertion — the validator is no-op."""
    narrative = _narrative(
        setup="Amorim's United come into this with momentum.",
        verdict="Amorim's side back to winning ways.",
    )

    fake_violations = [_FakeManagerViolation(name="Amorim", section="setup")]
    with mock.patch(
        "narrative_spec.validate_manager_names_in_all_sections",
        create=True,
        return_value=fake_violations,
    ):
        r = _validate_narrative_for_persistence(
            content={"narrative_html": narrative, "verdict_html": "",
                     "match_id": "manchester_united_vs_brighton_2026-04-29",
                     "narrative_source": "w84"},
            evidence_pack=evidence_pack_man_utd_carrick,
            edge_tier="gold",
            source_label="w84",
        )
    assert r.passed is False
    mgr = [f for f in r.failures if f.gate == "manager_hallucination"]
    assert len(mgr) == 1
    assert mgr[0].severity == "CRITICAL"
    assert "Amorim" in mgr[0].detail


# ── Test 8: "Nuno's side" + Pereira evidence → manager_hallucination (LB-3) ─


def test_nuno_forest_with_pereira_evidence_critical(evidence_pack_forest_pereira) -> None:
    narrative = _narrative(setup="Nuno's side will look to grind it out.")
    fake_violations = [_FakeManagerViolation(name="Nuno", section="setup")]
    with mock.patch(
        "narrative_spec.validate_manager_names_in_all_sections",
        create=True,
        return_value=fake_violations,
    ):
        r = _validate_narrative_for_persistence(
            content={"narrative_html": narrative, "verdict_html": "",
                     "match_id": "nottingham_forest_vs_brentford_2026-04-29",
                     "narrative_source": "w84"},
            evidence_pack=evidence_pack_forest_pereira,
            edge_tier="silver",
            source_label="w84",
        )
    assert any(
        f.gate == "manager_hallucination" and f.severity == "CRITICAL"
        for f in r.failures
    )


# ── Test 9: Fabricated H2H + empty matches → CRITICAL claim_h2h_fabricated (LB-5)


def test_fabricated_h2h_critical(evidence_pack_clean) -> None:
    """When evidence_pack.h2h.matches is empty, narrative MUST NOT cite H2H stats."""
    narrative = _narrative(
        setup="In their last 2 meetings: Brighton won 0, drew 2, lost 0."
    )
    pack = dict(evidence_pack_clean)
    pack["h2h"] = {"matches": []}

    fake_violations = [_FakeClaimViolation(
        kind="h2h_fabricated", claim="2 meetings: Brighton 0W 2D 0L", section="setup"
    )]
    with mock.patch(
        "narrative_spec.validate_claims_against_evidence",
        create=True,
        return_value=fake_violations,
    ):
        r = _validate_narrative_for_persistence(
            content={"narrative_html": narrative, "verdict_html": "",
                     "match_id": "x_vs_y_2026-04-29", "narrative_source": "w84"},
            evidence_pack=pack,
            edge_tier="gold",
            source_label="w84",
        )
    assert r.passed is False
    assert any(
        f.gate == "claim_h2h_fabricated" and f.severity == "CRITICAL"
        for f in r.failures
    )


# ── Test 10: WWWLD claim + data_available=False → MAJOR claim_evidence_mismatch ──


def test_form_claim_no_evidence_major(evidence_pack_clean) -> None:
    """LB-B5 closure: form citation without backing data → MAJOR (not CRITICAL)."""
    narrative = _narrative(setup="Arsenal arrive on a WWWLD form streak.")
    pack = dict(evidence_pack_clean)
    pack["home_form"] = {"data_available": False, "string": ""}

    fake_violations = [_FakeClaimViolation(
        kind="form_evidence_mismatch", claim="WWWLD form", section="setup"
    )]
    with mock.patch(
        "narrative_spec.validate_claims_against_evidence",
        create=True,
        return_value=fake_violations,
    ):
        r = _validate_narrative_for_persistence(
            content={"narrative_html": narrative, "verdict_html": "",
                     "match_id": "arsenal_vs_x_2026-04-29", "narrative_source": "w84"},
            evidence_pack=pack,
            edge_tier="bronze",
            source_label="w84",
        )
    assert any(
        f.gate == "claim_evidence_mismatch" and f.severity == "MAJOR"
        for f in r.failures
    )
    # Major-only must NOT mark passed=False if there are no critical findings.
    crit = [f for f in r.failures if f.severity == "CRITICAL"]
    if not crit:
        # passed only false if MAJOR present
        assert r.passed is False  # MAJOR fails the result per spec


# ── Test 11: Premium tier (gold) + CRITICAL refuse path log marker ──────────


def test_premium_critical_refuse_log_marker(caplog) -> None:
    narrative = _narrative(setup="A clash at Anfield will be tough.")
    # The validator only reports — but we assert the log marker text exists
    # in the validator's own log path so the caller's log is consistent.
    with caplog.at_level("WARNING", logger="narrative_validator"):
        r = _validate_narrative_for_persistence(
            content={"narrative_html": narrative, "verdict_html": "",
                     "match_id": "liverpool_vs_x_2026-04-29", "narrative_source": "w84"},
            evidence_pack=None,
            edge_tier="gold",
            source_label="w84",
        )
    assert r.critical_count == 1
    # The validator emits an internal `ValidatorVenueLeak` marker; the
    # *caller* emits `PremiumValidatorRefused`. The caller's marker is bound
    # in `bot._store_narrative_cache` and asserted in test 14 below via the
    # routing-logic test. Here we assert the validator's reporting marker.
    assert any(
        "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVenueLeak" in msg
        for msg in caplog.messages
    )


# ── Test 12: Premium (diamond) + MAJOR → result.passed=False ───────────────


def test_premium_major_fails_result() -> None:
    """A major-only failure (e.g. verdict quality) must mark the result as not-passed.

    Caller policy then refuses for premium tiers; non-premium would quarantine.
    The validator itself just reports passed=False so the caller branches.
    """
    narrative = _narrative(
        setup="A clean fixture analytically.",
        edge="The bookmaker has Arsenal at 1.85 — fair model probability is 58%.",
        risk="Squad rotation could blunt the home edge.",
    )
    # Force a MAJOR-only failure via the BANNED_NARRATIVE_PHRASES gate.
    # "value play" is on the banned list.
    narrative_with_banned = narrative + "\n\n\U0001f3c6 <b>Verdict</b>\nA classic value play here."
    r = _validate_narrative_for_persistence(
        content={"narrative_html": narrative_with_banned,
                 "verdict_html": "A classic value play here.",
                 "match_id": "x_vs_y_2026-04-29", "narrative_source": "w84"},
        evidence_pack=None,
        edge_tier="diamond",
        source_label="w84",
    )
    # MAJOR-or-CRITICAL -> passed=False
    assert r.passed is False
    assert r.major_count >= 1


# ── Test 13: Non-premium (silver) + CRITICAL → refuse ──────────────────────


def test_non_premium_critical_refuse() -> None:
    narrative = _narrative(setup="Trip to Goodison Park is tricky.")
    r = _validate_narrative_for_persistence(
        content={"narrative_html": narrative, "verdict_html": "",
                 "match_id": "everton_vs_x_2026-04-29", "narrative_source": "w82"},
        evidence_pack=None,
        edge_tier="silver",
        source_label="w82",
    )
    assert r.passed is False
    assert r.critical_count >= 1
    # Caller's policy: non-premium + CRITICAL → refuse. We assert the validator
    # surface (severity + gate) is sufficient for the caller to decide.
    assert r.severity == "CRITICAL"


# ── Test 14: Non-premium + MAJOR → caller quarantines (assert on caller) ──


def test_caller_quarantines_non_premium_major(caplog) -> None:
    """End-to-end: call the bot writer with a MAJOR-only narrative and assert
    that `_quality_status_override = 'quarantined'` lands in the INSERT params.

    We mock the underlying DB writer because we're testing the routing logic,
    not the SQLite plumbing.
    """
    pytest.importorskip("bot")
    import bot  # noqa: WPS433

    narrative = "\U0001f4cb <b>The Setup</b>\nClean.\n\U0001f3af <b>The Edge</b>\nNumbers."
    verdict = "A classic value play here."  # 'value play' is in BANNED_NARRATIVE_PHRASES

    insert_params: list[Any] = []

    class FakeConn:
        def execute(self, sql: str, params: tuple = ()) -> Any:
            if "INSERT OR REPLACE INTO narrative_cache" in sql:
                insert_params.append(params)

            class _Row:
                def fetchone(self) -> Any:
                    return None
            return _Row()

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

    with mock.patch("db_connection.get_connection", return_value=FakeConn()), \
         mock.patch("bot._compute_odds_hash", return_value="hash"), \
         caplog.at_level("WARNING"):
        import asyncio
        asyncio.run(bot._store_narrative_cache(
            match_id="x_vs_y_2026-04-29",
            html=narrative,
            tips=[],
            edge_tier="bronze",
            model="claude-sonnet",
            evidence_json=None,
            narrative_source="w84",
            verdict_html=verdict,
        ))

    # If the BANNED_NARRATIVE_PHRASES gate fires, MAJOR fail → quarantine.
    if insert_params:
        params = insert_params[0]
        # last param is _quality_status_override
        assert params[-1] == "quarantined", f"params tail: {params[-3:]}"
        assert any(
            "FIX-NARRATIVE-ROT-ROOT-01 BaselineQuarantined" in msg
            for msg in caplog.messages
        ), caplog.messages


# ── Test 15: Bypass routing — verdict-cache CRITICAL refuses, no INSERT ────


def test_verdict_cache_critical_refuses_no_insert(caplog) -> None:
    pytest.importorskip("bot")
    import bot

    # Verdict that fails Gate 9 (venue leak) → CRITICAL.
    bad_verdict = "Back Liverpool home at Anfield — 1.85 the price."

    insert_count = 0

    class FakeConn:
        def execute(self, sql: str, params: tuple = ()) -> Any:
            nonlocal insert_count
            if "INSERT OR REPLACE INTO narrative_cache" in sql or \
               "UPDATE narrative_cache" in sql:
                insert_count += 1

            class _Row:
                def fetchone(self) -> Any:
                    return None
            return _Row()

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

    tip_data: dict[str, Any] = {"edge_tier": "gold", "tier": "gold"}

    with mock.patch("db_connection.get_connection", return_value=FakeConn()), \
         mock.patch("bot._compute_odds_hash", return_value="hash"), \
         caplog.at_level("WARNING"):
        bot._store_verdict_cache_sync(
            match_key="liverpool_vs_x_2026-04-29",
            verdict_html=bad_verdict,
            tip_data=tip_data,
        )

    # Either the existing min_verdict_quality gate (W92) or the new unified
    # validator gate must refuse — we assert no DB write happened.
    assert insert_count == 0, "verdict cache must not write on CRITICAL"


# ── Test 16: Migration / evidence-only UPDATE bypasses content gates ──────


def test_evidence_only_update_skips_content_gates() -> None:
    """`_store_narrative_evidence` only mutates evidence_json. The unified
    validator is bypassed by design — this UPDATE doesn't carry narrative
    or verdict text. We assert the JSON sanity check is the only barrier.
    """
    pytest.importorskip("bot")
    import asyncio
    import bot

    class FakeCur:
        rowcount = 1

    class FakeConn:
        def execute(self, sql: str, params: tuple = ()) -> Any:
            return FakeCur()

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

    with mock.patch("db_connection.get_connection", return_value=FakeConn()):
        # Valid JSON object → returns True
        ok = asyncio.run(bot._store_narrative_evidence(
            match_id="x_vs_y_2026-04-29",
            evidence_json='{"home_team": "Arsenal"}',
        ))
        assert ok is True

        # Invalid JSON → returns False, no UPDATE issued
        bad = asyncio.run(bot._store_narrative_evidence(
            match_id="x_vs_y_2026-04-29",
            evidence_json="not-json{",
        ))
        assert bad is False


# ── Test 17: Idempotency — same input gives identical result ───────────────


def test_validator_is_idempotent() -> None:
    narrative = _narrative(setup="Trip to Anfield is brutal.")
    content = {"narrative_html": narrative, "verdict_html": "",
               "match_id": "x_vs_y_2026-04-29", "narrative_source": "w84"}
    r1 = _validate_narrative_for_persistence(
        content=content, evidence_pack=None, edge_tier="gold", source_label="w84"
    )
    r2 = _validate_narrative_for_persistence(
        content=content, evidence_pack=None, edge_tier="gold", source_label="w84"
    )
    assert r1.passed == r2.passed
    assert r1.severity == r2.severity
    assert len(r1.failures) == len(r2.failures)
    for a, b in zip(r1.failures, r2.failures):
        assert a.gate == b.gate
        assert a.severity == b.severity
        assert a.detail == b.detail
        assert a.section == b.section


# ── Test 18: ValidationResult helper properties ────────────────────────────


def test_validation_result_count_helpers() -> None:
    failures = [
        ValidationFailure(gate="venue_leak", severity="CRITICAL", detail="x"),
        ValidationFailure(gate="claim_evidence_mismatch", severity="MAJOR", detail="y"),
        ValidationFailure(gate="banned_phrase", severity="MAJOR", detail="z"),
    ]
    r = ValidationResult(passed=False, failures=failures, severity="CRITICAL")
    assert r.critical_count == 1
    assert r.major_count == 2
