"""Report generator for the QA Rubric Runner.

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

Generates:
  - Markdown report at output_path
  - JSON sidecar at output_path.replace('.md', '.json')

Report skeleton follows INV-QA-RUBRIC-01 section 11.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .scoring.card import L1Score
from .scoring.journey import L2Score
from .scoring.coverage import L3Score, compute_run_composite, persona_composite

log = logging.getLogger(__name__)

# Thresholds
_PASS_THRESHOLD = 9.0
_CONDITIONAL_THRESHOLD = 8.0


@dataclass
class PersonaRunResult:
    """Aggregated per-persona scoring result."""

    persona_id: str
    tier: str
    steps_completed: int
    steps_total: int
    l1: L1Score
    l2: L2Score
    composite: float
    defects: list[dict] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    @property
    def verdict(self) -> str:
        return "ABORTED" if self.aborted else "SCORED"


@dataclass
class RunResults:
    """Full results for a complete rubric run."""

    run_timestamp: str
    persona_results: list[PersonaRunResult]
    l3: L3Score
    composite_score: float
    verdict: str
    sev1_count: int = 0
    payment_flow_executed: bool = False
    stitch_mock_mode: bool = True


def _verdict(composite: float, sev1_count: int, j5_scores: list[float],
             k3_fraction: float, payment_executed: bool, mock_mode: bool) -> str:
    """Compute the run verdict per hard overrides."""
    if sev1_count > 0:
        return "FAIL (SEV-1)"
    if any(s < 5.0 for s in j5_scores):
        return "FAIL (J5 < 5.0)"
    if k3_fraction < 0.80:
        return f"FAIL (K3 {k3_fraction*100:.0f}% < 80%)"
    if mock_mode and not payment_executed:
        return "FAIL (payment flow not executed E2E)"
    if composite >= _PASS_THRESHOLD:
        return "PASS"
    if composite >= _CONDITIONAL_THRESHOLD:
        return "CONDITIONAL PASS"
    return "FAIL"


def _md_score_bar(score: float, width: int = 20) -> str:
    """Simple text progress bar for markdown."""
    filled = int(round(score / 10.0 * width))
    return f"[{'█' * filled}{'░' * (width - filled)}] {score:.1f}/10"


def generate_report(
    persona_results: list[PersonaRunResult],
    l3: L3Score,
    *,
    output_path: str,
    stitch_mock_mode: bool = True,
    payment_flow_executed: bool = False,
    run_timestamp: str | None = None,
) -> RunResults:
    """Generate markdown + JSON sidecar report.

    Args:
        persona_results: Scored persona results (P1–P4).
        l3: L3 Coverage score.
        output_path: Path to write the markdown report.
        stitch_mock_mode: Whether STITCH_MOCK_MODE was True.
        payment_flow_executed: Whether P1 payment E2E was completed.
        run_timestamp: ISO timestamp (defaults to now).

    Returns:
        RunResults dataclass with composite score and verdict.
    """
    ts = run_timestamp or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    ts_display = datetime.now().strftime("%Y-%m-%d %H:%M SAST")

    # Gather per-persona composites
    persona_composites = [pr.composite for pr in persona_results]
    composite_score = compute_run_composite(persona_composites, l3.raw_score)

    # Collect SEV-1 defects
    all_defects: list[dict] = []
    for pr in persona_results:
        for d in pr.defects:
            all_defects.append({"persona": pr.persona_id, **d})
    sev1_count = sum(1 for d in all_defects if d.get("sev") == "1")

    # J5 scores for hard override check
    j5_scores = []
    for pr in persona_results:
        for dim in pr.l2.dimensions:
            if dim.dimension == "J5":
                j5_scores.append(dim.score)

    verdict = _verdict(
        composite_score, sev1_count, j5_scores,
        l3.k3_fraction, payment_flow_executed, stitch_mock_mode,
    )

    run_results = RunResults(
        run_timestamp=ts,
        persona_results=persona_results,
        l3=l3,
        composite_score=composite_score,
        verdict=verdict,
        sev1_count=sev1_count,
        payment_flow_executed=payment_flow_executed,
        stitch_mock_mode=stitch_mock_mode,
    )

    # ── Build markdown ────────────────────────────────────────────────────────
    lines: list[str] = []

    lines.append("# QA Run Report — BUILD-QA-RUBRIC-RUNNER-01")
    lines.append("")

    # Run metadata
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- **Run timestamp**: {ts_display}")
    lines.append(f"- **Personas**: {', '.join(pr.persona_id for pr in persona_results)}")
    lines.append(f"- **STITCH_MOCK_MODE**: {stitch_mock_mode}")
    lines.append(f"- **Payment flow executed E2E**: {payment_flow_executed}")
    lines.append(f"- **Composite score**: {composite_score:.2f}/10")
    lines.append(f"- **Verdict**: {verdict}")
    lines.append("")

    # Per-persona results
    lines.append("## Per-persona results")
    lines.append("")
    for pr in persona_results:
        lines.append(f"### {pr.persona_id} — {pr.tier.title()}")
        lines.append("")
        lines.append(
            f"**Persona composite: {pr.composite:.1f}** = "
            f"0.5·L1({pr.l1.raw_score:.1f}) + 0.5·L2({pr.l2.raw_score:.1f})"
        )
        lines.append("")
        lines.append(f"Steps: {pr.steps_completed}/{pr.steps_total}")
        if pr.aborted:
            lines.append(f"**ABORTED**: {pr.abort_reason}")
        lines.append("")

        # L1 breakdown
        lines.append("#### L1 Card Quality")
        lines.append("")
        lines.append(f"{_md_score_bar(pr.l1.raw_score)}")
        lines.append("")
        for dim in pr.l1.dimensions:
            notes_str = "; ".join(dim.notes) if dim.notes else "OK"
            lines.append(f"- **{dim.dimension}** ({dim.weight:.1f}w): {dim.score:.1f}/10 — {notes_str}")
        lines.append("")

        # L2 breakdown
        lines.append("#### L2 Journey Integrity")
        lines.append("")
        lines.append(f"{_md_score_bar(pr.l2.raw_score)}")
        lines.append("")
        for dim in pr.l2.dimensions:
            pct = int(dim.weight * 100)
            notes_str = "; ".join(dim.notes) if dim.notes else "OK"
            lines.append(f"- **{dim.dimension}** ({pct}%): {dim.score:.1f}/10 — {notes_str}")
        lines.append("")

        # Defects for this persona
        if pr.defects:
            lines.append("#### Defects")
            lines.append("")
            for d in pr.defects:
                sev = d.get("sev", "?")
                desc = d.get("description", "")
                step = d.get("step", "?")
                lines.append(f"- **SEV-{sev}** (step {step}): {desc}")
            lines.append("")

    # L3 Coverage
    lines.append("## L3 Coverage")
    lines.append("")
    lines.append(f"{_md_score_bar(l3.raw_score)}")
    lines.append("")
    for dim in l3.dimensions:
        pct = int(dim.weight * 100)
        notes_str = "; ".join(dim.notes) if dim.notes else "OK"
        lines.append(f"- **{dim.dimension}** ({pct}%): {dim.score:.1f}/10 — {notes_str}")
    lines.append("")
    lines.append(f"- GATE_MATRIX cells tested: {l3.gate_cells_tested}/{l3.gate_cells_total}")
    lines.append(f"- K3 threshold passed (≥80%): {'YES' if l3.k3_passes_hard_override else 'NO — HARD OVERRIDE'}")
    lines.append("")

    # Composite score
    lines.append("## Composite Score")
    lines.append("")
    lines.append(f"```")
    lines.append(f"0.65 × mean(persona_composite) + 0.35 × L3")
    if persona_composites:
        mean_p = sum(persona_composites) / len(persona_composites)
        lines.append(f"0.65 × {mean_p:.2f} + 0.35 × {l3.raw_score:.2f} = {composite_score:.2f}")
    lines.append(f"```")
    lines.append("")
    lines.append(f"**{composite_score:.2f}/10 — {verdict}**")
    lines.append("")

    # All defects
    lines.append("## Defects")
    lines.append("")
    if all_defects:
        sev1_d = [d for d in all_defects if d.get("sev") == "1"]
        sev2_d = [d for d in all_defects if d.get("sev") == "2"]
        sev3_d = [d for d in all_defects if d.get("sev") == "3"]
        lines.append(f"Total: {len(all_defects)} ({len(sev1_d)} SEV-1, {len(sev2_d)} SEV-2, {len(sev3_d)} SEV-3)")
        lines.append("")
        for sev_label, defect_list in [("SEV-1", sev1_d), ("SEV-2", sev2_d), ("SEV-3", sev3_d)]:
            if defect_list:
                lines.append(f"### {sev_label}")
                for d in defect_list:
                    p = d.get("persona", "?")
                    step = d.get("step", "?")
                    desc = d.get("description", "")
                    lines.append(f"- [{p} step {step}] {desc}")
                lines.append("")
    else:
        lines.append("No defects recorded.")
        lines.append("")

    # CLAUDE.md Updates
    lines.append("## CLAUDE.md Updates")
    lines.append("")
    lines.append("None required from this QA run.")
    lines.append("")

    # Write markdown
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Report written to %s", out_path)

    # ── Write JSON sidecar ────────────────────────────────────────────────────
    json_path = out_path.with_suffix(".json")
    json_data = {
        "composite_score": composite_score,
        "verdict": verdict,
        "run_timestamp": ts,
        "stitch_mock_mode": stitch_mock_mode,
        "payment_flow_executed": payment_flow_executed,
        "sev1_count": sev1_count,
        "persona_composites": {pr.persona_id: pr.composite for pr in persona_results},
        "l3_score": l3.raw_score,
        "l3_k3_fraction": l3.k3_fraction,
        "l3_k3_passes": l3.k3_passes_hard_override,
        "per_persona": {
            pr.persona_id: {
                "composite": pr.composite,
                "l1": pr.l1.as_dict(),
                "l2": pr.l2.as_dict(),
                "steps_completed": pr.steps_completed,
                "steps_total": pr.steps_total,
                "aborted": pr.aborted,
            }
            for pr in persona_results
        },
        "defects": all_defects,
    }
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    log.info("JSON sidecar written to %s", json_path)

    return run_results
