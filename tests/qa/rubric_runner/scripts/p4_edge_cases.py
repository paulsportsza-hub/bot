"""P4 — Edge case persona script (6 steps).

BUILD-QA-RUBRIC-RUNNER-01 — Phase B

Script:
  /qa reset → /start (use existing profile) → My Matches (empty state)
  → Top Edge Picks (empty state) → freetext → /qa reset + settings navigation

Focus: empty states, freetext handling, navigation resilience.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..gate_matrix import GateCell, build_gate_cells
from ..scripts.base import PersonaRunner, Reply
from ..surfaces import Artefact

log = logging.getLogger(__name__)

PERSONA_ID = "P4"
STEPS_TOTAL = 6


@dataclass
class P4Result:
    persona_id: str = PERSONA_ID
    steps_completed: int = 0
    steps_total: int = STEPS_TOTAL
    artefacts: list[Artefact] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    gate_matrix_cells: list[GateCell] = field(default_factory=list)
    defects: list[dict] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""


def _artefact(reply: Reply, surface_id: str) -> Artefact:
    return Artefact(
        surface_id=surface_id,
        timestamp=time.time(),
        message_text=reply.text,
        photo_path=reply.photo_path,
        response_time_s=reply.response_time_s,
    )


def _defect(result: P4Result, step: int, sev: str, desc: str) -> None:
    result.defects.append({"step": step, "sev": sev, "description": desc})
    log.warning("P4 defect SEV-%s step %d: %s", sev, step, desc)


async def run(runner: PersonaRunner) -> P4Result:
    result = P4Result()
    result.gate_matrix_cells = build_gate_cells(PERSONA_ID)
    step = 0

    try:
        # STEP 1: Reset
        step = 1
        r = await runner.send_cmd("/qa reset", surface_id="S0")
        result.artefacts.append(_artefact(r, "S0"))
        result.steps_completed += 1

        # STEP 2: /start — should use existing profile or re-onboard
        step = 2
        r = await runner.send_cmd("/start", surface_id="S0")
        result.artefacts.append(_artefact(r, "S0"))
        # Allow either onboarding or main menu — /qa reset cleared QA override but not DB profile
        if r.text == "[TIMEOUT]":
            _defect(result, step, "1", "/start timed out — SEV-1 onboarding blocked")
            result.aborted = True
            result.abort_reason = "start timeout"
            return result
        result.steps_completed += 1

        # STEP 3: My Matches — check empty state
        step = 3
        r = await runner.send_cmd("⚽ My Matches", timeout=runner.default_timeout, surface_id="S13")
        result.artefacts.append(_artefact(r, "S13"))
        result.timings["S13_mm_empty"] = r.response_time_s
        if r.text == "[TIMEOUT]":
            _defect(result, step, "2", "My Matches empty state timed out")
        elif not r.text.strip():
            _defect(result, step, "2", "My Matches returned empty text — C6 empty state quality fail")
        else:
            # Must have some content even if empty — not just a silent empty message
            if len(r.text.strip()) < 20:
                _defect(result, step, "3", "My Matches empty state too short — C6 deduction")
        result.steps_completed += 1

        # STEP 4: Top Edge Picks — check empty state or list
        step = 4
        r = await runner.send_cmd("💎 Top Edge Picks", timeout=runner.picks_timeout, surface_id="S13")
        result.artefacts.append(_artefact(r, "S13"))
        result.timings["S13_picks_empty"] = r.response_time_s
        if r.text == "[TIMEOUT]":
            _defect(result, step, "2", "Top Edge Picks empty state timed out")
        elif not r.text.strip():
            _defect(result, step, "2", "Top Edge Picks returned empty text — C6 quality fail")
        result.steps_completed += 1

        # STEP 5: Freetext input
        step = 5
        r = await runner.send_cmd(
            "What are the best picks for tonight?",
            timeout=8,
            surface_id="S7",
        )
        result.artefacts.append(_artefact(r, "S7"))
        if r.text == "[TIMEOUT]":
            _defect(result, step, "3", "Bot did not respond to freetext input")
        result.steps_completed += 1

        # STEP 6: Settings navigation + reset
        step = 6
        r = await runner.send_cmd("⚙️ Settings", surface_id="S6")
        result.artefacts.append(_artefact(r, "S6"))
        if r.text == "[TIMEOUT]":
            _defect(result, step, "2", "Settings timed out")
        # Verify back button works
        back_btn = None
        for row in r.buttons:
            for label in row:
                if "↩️" in label or "back" in label.lower() or "menu" in label.lower():
                    back_btn = label
                    break
            if back_btn:
                break
        if not back_btn:
            _defect(result, step, "2", "Settings has no back/menu button — dead end risk")
        result.steps_completed += 1

    except Exception as exc:
        log.error("P4 aborted at step %d: %s", step, exc, exc_info=True)
        result.aborted = True
        result.abort_reason = f"step {step}: {exc}"
        _defect(result, step, "1", f"Script exception: {exc}")

    return result
