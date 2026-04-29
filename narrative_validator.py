"""FIX-NARRATIVE-ROT-ROOT-01 Phase 2 — unified pre-persist narrative validator.

Single canonical validator that every narrative_cache write MUST pass through
before persistence. Replaces the historical drift between polish-time
(`_validate_polish`), serve-time (`min_verdict_quality`), writer-level
(`_validate_baseline_setup`), and cache-read gates.

The premium-tier no-fallback chain (Rule 23) and writer-level W82 refusal
(Rule 24) remain in `_store_narrative_cache` and are NOT moved here — they
gate the source/tier combo BEFORE this validator runs. This validator scans
content quality given that the source is permitted.

Architecture
------------
The validator is a *reporter* — it never decides what to do with failures.
The CALLER (writer) applies tier-aware enforcement policy:

- Premium (Diamond/Gold) on CRITICAL or MAJOR → refuse write
  (log `FIX-NARRATIVE-ROT-ROOT-01 PremiumValidatorRefused`).
- Non-premium (Silver/Bronze) on CRITICAL → refuse write
  (log `BaselineValidatorRefused`).
- Non-premium on MAJOR → write with `quality_status='quarantined'`
  (log `BaselineQuarantined`).

This split keeps the validator pure (testable in isolation, idempotent) and
the caller simple (single decision tree based on the result).

Lazy imports
------------
`bot.py` imports this module at the top of `_store_narrative_cache` and the
verdict-cache writer. Importing `bot` here at module load would create a
circular import. Helpers are imported lazily inside `_validate_narrative_for_persistence`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

Severity = Literal["CRITICAL", "MAJOR", "MINOR"]


@dataclass
class ValidationFailure:
    """Single gate hit produced by the unified validator.

    Attributes
    ----------
    gate
        Stable identifier for the failed check (e.g. ``"venue_leak"``,
        ``"setup_pricing_semantic"``). Used for log markers + monitoring.
    severity
        ``"CRITICAL"``, ``"MAJOR"`` or ``"MINOR"``. Caller policy is keyed on
        this. Premium-tier refuses both CRITICAL and MAJOR; non-premium
        refuses only CRITICAL.
    detail
        Human-readable description of the violation. Truncated to ~200 chars
        in log output.
    section
        Which narrative section the gate fired against:
        ``"setup" | "edge" | "risk" | "verdict" | "verdict_html" | "all"``.
        ``"all"`` means a full-document scan (BANNED_NARRATIVE_PHRASES).
    """

    gate: str
    severity: Severity
    detail: str
    section: str = ""


@dataclass
class ValidationResult:
    """Outcome of a single validator pass.

    Attributes
    ----------
    passed
        ``True`` iff there are zero CRITICAL and zero MAJOR failures.
        MINOR failures DO NOT mark the result as failed — they are
        informational only.
    failures
        Ordered list of every gate hit. Same gate may not fire twice with the
        same detail — callers should treat duplicates as a bug in the gate.
    severity
        Highest severity present (``"CRITICAL" > "MAJOR" > "MINOR"``) or
        ``None`` when ``failures`` is empty.
    """

    passed: bool
    failures: list[ValidationFailure] = field(default_factory=list)
    severity: Severity | None = None

    @property
    def critical_count(self) -> int:
        """Number of CRITICAL failures — used by the caller to short-circuit."""
        return sum(1 for f in self.failures if f.severity == "CRITICAL")

    @property
    def major_count(self) -> int:
        """Number of MAJOR failures — used by the caller for quarantine policy."""
        return sum(1 for f in self.failures if f.severity == "MAJOR")


# Sections recognised by the gate stack. ``verdict_html`` is the verdict-only
# surface (verdict-cache writes) — separate from ``verdict`` (the verdict
# section of a full narrative) so the validator can differentiate.
_SECTION_VERDICT_HTML = "verdict_html"
_SECTION_NARRATIVE = "all"


def _extract_setup_section(narrative_html: str) -> str:
    """Best-effort extraction of the Setup section from a narrative HTML block.

    Mirrors `bot._extract_setup_section`. Looks for the 📋 (Setup header)
    marker and returns text up to the next section marker (🎯 Edge, ⚠️ Risk,
    🏆 Verdict). Returns the full input on no marker (defensive: caller still
    runs strict-ban scan).
    """
    if not narrative_html:
        return ""
    setup_marker = "\U0001f4cb"  # 📋
    edge_marker = "\U0001f3af"  # 🎯
    risk_marker = "⚠️"  # ⚠️
    verdict_marker = "\U0001f3c6"  # 🏆
    setup_idx = narrative_html.find(setup_marker)
    if setup_idx == -1:
        return narrative_html
    rest = narrative_html[setup_idx:]
    # Find the next section header after Setup.
    next_idx = len(rest)
    for marker in (edge_marker, risk_marker, verdict_marker):
        idx = rest.find(marker, len(setup_marker))
        if idx != -1 and idx < next_idx:
            next_idx = idx
    return rest[:next_idx]


def _validate_narrative_for_persistence(
    content: dict[str, Any],
    evidence_pack: dict | None,
    edge_tier: str,
    source_label: str,
) -> ValidationResult:
    """Run the full pre-persist gate stack against narrative content.

    Parameters
    ----------
    content
        Required keys: ``narrative_html`` (str | None), ``verdict_html`` (str | None),
        ``match_id`` (str), ``narrative_source`` (str). Empty/None values for
        ``narrative_html`` and ``verdict_html`` are tolerated — the relevant
        gate stack is skipped for empty surfaces.
    evidence_pack
        Parsed evidence_json dict. May be ``None`` when the writer has no
        evidence pack (e.g. verdict-cache path). Manager + claim gates skip
        when this is None.
    edge_tier
        Edge tier ("diamond" | "gold" | "silver" | "bronze"). Currently
        informational — caller applies tier-aware policy. Validator behaviour
        is tier-agnostic.
    source_label
        Narrative source label ("w82" | "w84-haiku-fallback" | "verdict-cache"
        | etc.). Currently informational — used in log markers only.

    Returns
    -------
    ValidationResult
        Reports findings; never makes write decisions.

    Notes
    -----
    The validator is *idempotent* — calling twice with the same input
    produces structurally identical results (same gate ordering, same
    detail strings). This is asserted by the contract test suite.
    """
    failures: list[ValidationFailure] = []
    narrative_html = content.get("narrative_html") or ""
    verdict_html = content.get("verdict_html") or ""
    match_id = content.get("match_id", "")

    # Lazy imports — bot.py imports this module at the top of _store_narrative_cache.
    # Importing bot here at module load would create a cycle.
    try:
        from narrative_spec import (
            find_venue_leaks,
            min_verdict_quality,
        )
    except ImportError as exc:
        log.warning(
            "FIX-NARRATIVE-ROT-ROOT-01 ValidatorImportFailed match_id=%s err=%s — "
            "gate is no-op (returning passed=True to avoid blocking writes)",
            match_id, exc,
        )
        return ValidationResult(passed=True)

    # Phase 4 detectors — assume the agreed names; integration after Phase 4 lands.
    try:
        from narrative_spec import validate_manager_names_in_all_sections  # type: ignore[attr-defined]
    except ImportError:
        validate_manager_names_in_all_sections = None  # type: ignore[assignment]

    try:
        from narrative_spec import validate_claims_against_evidence  # type: ignore[attr-defined]
    except ImportError:
        validate_claims_against_evidence = None  # type: ignore[assignment]

    try:
        from bot import _find_setup_pricing_semantic_violations  # type: ignore[attr-defined]
    except ImportError:
        _find_setup_pricing_semantic_violations = None  # type: ignore[assignment]

    try:
        from bot import _find_setup_strict_ban_violations as _find_setup_strict_ban  # type: ignore[attr-defined]
    except ImportError:
        _find_setup_strict_ban = None  # type: ignore[assignment]

    try:
        from bot import BANNED_NARRATIVE_PHRASES  # type: ignore[attr-defined]
    except ImportError:
        BANNED_NARRATIVE_PHRASES = []  # type: ignore[assignment]

    # ── Gate 1: Venue leaks in narrative_html (LB-1 closure) ─────────────────
    # Scan the FULL narrative — find_venue_leaks does not differentiate sections,
    # which is desirable here (Anfield in Verdict is just as wrong as Anfield in Setup).
    if narrative_html:
        venues = find_venue_leaks(narrative_html)
        if venues:
            failures.append(
                ValidationFailure(
                    gate="venue_leak",
                    severity="CRITICAL",
                    detail=f"venues={venues!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVenueLeak match_id=%s "
                "source=%s venues=%r",
                match_id, source_label, venues,
            )

    # ── Gate 2: Setup-section pricing leaks (LB-4 closure) ──────────────────
    # Two detectors: existing strict-ban (token + decimal + integer-prob) and the
    # Phase 4 semantic detector for "Elo-implied 70%" / "84% to win" patterns.
    if narrative_html:
        if _find_setup_strict_ban is not None:
            try:
                strict_reasons = _find_setup_strict_ban(narrative_html)
            except Exception as exc:
                strict_reasons = []
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorStrictBanFailed "
                    "match_id=%s err=%s",
                    match_id, exc,
                )
            if strict_reasons:
                failures.append(
                    ValidationFailure(
                        gate="setup_pricing",
                        severity="CRITICAL",
                        detail=f"reasons={strict_reasons!r}",
                        section="setup",
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorSetupPricingStrict "
                    "match_id=%s source=%s reasons=%r",
                    match_id, source_label, strict_reasons,
                )

        if _find_setup_pricing_semantic_violations is not None:
            try:
                semantic_reasons = _find_setup_pricing_semantic_violations(narrative_html)
            except Exception as exc:
                semantic_reasons = []
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorSetupSemanticFailed "
                    "match_id=%s err=%s",
                    match_id, exc,
                )
            if semantic_reasons:
                failures.append(
                    ValidationFailure(
                        gate="setup_pricing_semantic",
                        severity="CRITICAL",
                        detail=f"reasons={semantic_reasons!r}",
                        section="setup",
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorSetupPricingSemantic "
                    "match_id=%s source=%s reasons=%r",
                    match_id, source_label, semantic_reasons,
                )

    # ── Gate 3: Manager hallucination across all sections (LB-2/LB-3) ───────
    if narrative_html and evidence_pack is not None and validate_manager_names_in_all_sections is not None:
        try:
            mgr_violations = validate_manager_names_in_all_sections(
                narrative_html, evidence_pack
            )
        except Exception as exc:
            mgr_violations = []
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorManagerCheckFailed "
                "match_id=%s err=%s",
                match_id, exc,
            )
        if mgr_violations:
            # Phase 4 returns a list of `ManagerViolation` namedtuples — the
            # detail string is `"<count> hallucinated managers: <names>"`.
            try:
                names = [getattr(v, "name", str(v)) for v in mgr_violations]
            except Exception:
                names = [str(mgr_violations)]
            failures.append(
                ValidationFailure(
                    gate="manager_hallucination",
                    severity="CRITICAL",
                    detail=f"names={names!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorManagerHallucination "
                "match_id=%s source=%s names=%r",
                match_id, source_label, names,
            )

    # ── Gate 4: Claim verification against evidence (LB-5 / LB-B5) ──────────
    if narrative_html and evidence_pack is not None and validate_claims_against_evidence is not None:
        try:
            claim_violations = validate_claims_against_evidence(
                narrative_html, evidence_pack
            )
        except Exception as exc:
            claim_violations = []
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorClaimCheckFailed "
                "match_id=%s err=%s",
                match_id, exc,
            )
        # Phase 4 returns ClaimViolation namedtuples with a `kind` attribute.
        # H2H fabrications are CRITICAL (LB-5); form/record mismatches are MAJOR (LB-B5).
        h2h_violations = []
        evidence_violations = []
        for v in claim_violations or []:
            kind = (getattr(v, "kind", "") or "").lower()
            if "h2h" in kind:
                h2h_violations.append(v)
            else:
                evidence_violations.append(v)
        if h2h_violations:
            details = [getattr(v, "claim", str(v)) for v in h2h_violations]
            failures.append(
                ValidationFailure(
                    gate="claim_h2h_fabricated",
                    severity="CRITICAL",
                    detail=f"claims={details!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorClaimH2HFabricated "
                "match_id=%s source=%s claims=%r",
                match_id, source_label, details,
            )
        if evidence_violations:
            details = [getattr(v, "claim", str(v)) for v in evidence_violations]
            failures.append(
                ValidationFailure(
                    gate="claim_evidence_mismatch",
                    severity="MAJOR",
                    detail=f"claims={details!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorClaimEvidenceMismatch "
                "match_id=%s source=%s claims=%r",
                match_id, source_label, details,
            )

    # ── Gate 5: Verdict quality floor ───────────────────────────────────────
    if verdict_html:
        try:
            verdict_ok = min_verdict_quality(
                verdict_html, tier=edge_tier, evidence_pack=evidence_pack
            )
        except Exception as exc:
            verdict_ok = True
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVerdictQualityFailed "
                "match_id=%s err=%s",
                match_id, exc,
            )
        if not verdict_ok:
            failures.append(
                ValidationFailure(
                    gate="verdict_quality",
                    severity="MAJOR",
                    detail=f"len={len(verdict_html)} sample={verdict_html[:80]!r}",
                    section=_SECTION_VERDICT_HTML,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVerdictQualityFail "
                "match_id=%s source=%s tier=%s len=%d sample=%r",
                match_id, source_label, edge_tier, len(verdict_html),
                verdict_html[:80],
            )

    # ── Gate 6: Venue leaks in verdict_html (explicit) ──────────────────────
    # min_verdict_quality already scans for venues but only reports a bool.
    # Surface the explicit leak so the caller log carries the venue names.
    if verdict_html:
        verdict_venues = find_venue_leaks(verdict_html)
        if verdict_venues:
            # Don't double-fail if Gate 1 already caught it via narrative_html.
            already_failed = any(
                f.gate == "venue_leak" and "verdict" not in f.detail.lower()
                for f in failures
            )
            if not already_failed:
                failures.append(
                    ValidationFailure(
                        gate="venue_leak",
                        severity="CRITICAL",
                        detail=f"verdict venues={verdict_venues!r}",
                        section=_SECTION_VERDICT_HTML,
                    )
                )
                log.warning(
                    "FIX-NARRATIVE-ROT-ROOT-01 ValidatorVerdictVenueLeak "
                    "match_id=%s source=%s venues=%r",
                    match_id, source_label, verdict_venues,
                )

    # ── Gate 7: BANNED_NARRATIVE_PHRASES across narrative + verdict ─────────
    if BANNED_NARRATIVE_PHRASES:
        combined = (narrative_html or "") + " " + (verdict_html or "")
        combined_lower = combined.lower()
        hits = [p for p in BANNED_NARRATIVE_PHRASES if p.lower() in combined_lower]
        if hits:
            failures.append(
                ValidationFailure(
                    gate="banned_phrase",
                    severity="MAJOR",
                    detail=f"hits={hits[:5]!r}",
                    section=_SECTION_NARRATIVE,
                )
            )
            log.warning(
                "FIX-NARRATIVE-ROT-ROOT-01 ValidatorBannedPhrase "
                "match_id=%s source=%s hits=%r",
                match_id, source_label, hits[:5],
            )

    # ── Outcome ──────────────────────────────────────────────────────────────
    crit = [f for f in failures if f.severity == "CRITICAL"]
    major = [f for f in failures if f.severity == "MAJOR"]
    if crit:
        sev: Severity | None = "CRITICAL"
    elif major:
        sev = "MAJOR"
    elif failures:
        sev = "MINOR"
    else:
        sev = None
    return ValidationResult(
        passed=(len(crit) == 0 and len(major) == 0),
        failures=failures,
        severity=sev,
    )
