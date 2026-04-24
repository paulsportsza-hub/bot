"""P3 — Diamond multi-sport persona script (16 steps).

BUILD-QA-RUBRIC-RUNNER-01 — Phase B

Script:
  /qa reset → /start → onboarding (all sports) → /qa set_diamond
  → Top Edge Picks → verify Diamond view → tap any edge (full access)
  → odds comparison visible → My Matches → /qa teaser_diamond (S17)

Expected GATE_MATRIX cells:
  Diamond×Bronze, Diamond×Silver, Diamond×Gold, Diamond×Diamond (all full)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..gate_matrix import GateCell, build_gate_cells
from ..scripts.base import PersonaRunner, Reply
from ..surfaces import Artefact

log = logging.getLogger(__name__)

PERSONA_ID = "P3"
STEPS_TOTAL = 16


@dataclass
class P3Result:
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


def _defect(result: P3Result, step: int, sev: str, desc: str) -> None:
    result.defects.append({"step": step, "sev": sev, "description": desc})
    log.warning("P3 defect SEV-%s step %d: %s", sev, step, desc)


async def run(runner: PersonaRunner) -> P3Result:
    result = P3Result()
    result.gate_matrix_cells = build_gate_cells(PERSONA_ID)
    step = 0

    try:
        # STEP 1: Reset
        step = 1
        r = await runner.send_cmd("/qa reset", surface_id="S0")
        result.steps_completed += 1

        # STEP 2: /start
        step = 2
        r = await runner.send_cmd("/start", surface_id="S0")
        result.steps_completed += 1

        # STEP 3: Experience — Experienced
        step = 3
        r = await runner.tap_button(r, "Experienced")
        result.steps_completed += 1

        # STEP 4-7: All sports
        step = 4
        r = await runner.tap_button(r, "Soccer")
        result.steps_completed += 1

        step = 5
        r = await runner.tap_button(r, "Rugby")
        result.steps_completed += 1

        step = 6
        r = await runner.tap_button(r, "Cricket")
        result.steps_completed += 1

        step = 7
        try:
            r = await runner.tap_button(r, "Combat")
        except Exception:
            pass
        r = await runner.tap_button(r, "Done")
        result.steps_completed += 1

        # STEP 8: Teams (skip)
        step = 8
        for _ in range(4):
            try:
                r = await runner.send_cmd("skip", timeout=6, surface_id="S0")
            except Exception:
                try:
                    r = await runner.tap_button(r, "Done")
                except Exception:
                    pass
        result.steps_completed += 1

        # STEP 9-11: Risk / bankroll / notify
        step = 9
        r = await runner.tap_button(r, "Aggressive")
        result.steps_completed += 1

        step = 10
        r = await runner.tap_button(r, "R1")
        result.steps_completed += 1

        step = 11
        r = await runner.tap_button(r, "18")
        result.steps_completed += 1

        # Confirm
        r = await runner.tap_button(r, "Let's go")

        # STEP 12: Set Diamond tier
        step = 12
        r = await runner.send_cmd("/qa set_diamond", surface_id="S0")
        result.artefacts.append(_artefact(r, "S0"))
        result.steps_completed += 1

        # STEP 13: Top Edge Picks — verify Diamond view
        step = 13
        r = await runner.send_cmd("💎 Top Edge Picks", timeout=runner.picks_timeout, surface_id="S2")
        result.artefacts.append(_artefact(r, "S2"))
        result.timings["S2_diamond_load"] = r.response_time_s
        if r.text == "[TIMEOUT]":
            _defect(result, step, "1", "S2 timeout for Diamond user")
            result.aborted = True
            result.abort_reason = "S2 timeout"
            return result
        # Diamond should have no locked buttons
        has_locked = any("🔒" in btn for row in r.buttons for btn in row)
        if has_locked:
            _defect(result, step, "1", "Diamond user sees 🔒 locked edges — gate leak SEV-1")
        result.steps_completed += 1

        # STEP 14: Tap a Diamond edge (full access)
        step = 14
        diamond_btn = None
        for row in r.buttons:
            for label in row:
                if "💎" in label:
                    diamond_btn = label
                    break
            if diamond_btn:
                break

        if not diamond_btn:
            # Fall back to any non-locked button
            for row in r.buttons:
                for label in row:
                    if "🔒" not in label and len(label) > 5:
                        diamond_btn = label
                        break
                if diamond_btn:
                    break

        if diamond_btn:
            r_d = await runner.tap_button(r, diamond_btn, timeout=15)
            result.artefacts.append(_artefact(r_d, "S3"))
            result.timings["S3_diamond_load"] = r_d.response_time_s
            if r_d.has_photo:
                photo_path = await runner.download_photo(r_d, f"P3_S3_{int(time.time())}.jpg")
                result.artefacts[-1].photo_path = photo_path

            # All cells for Diamond should be full
            for cell in result.gate_matrix_cells:
                if not cell.tested:
                    cell.tested = True
                    if "🔒" in r_d.text:
                        cell.actual = "locked"
                    else:
                        cell.actual = "full"
        result.steps_completed += 1

        # STEP 15: My Matches
        step = 15
        r = await runner.send_cmd("⚽ My Matches", timeout=runner.default_timeout, surface_id="S4")
        result.artefacts.append(_artefact(r, "S4"))
        result.timings["S4_diamond_load"] = r.response_time_s
        result.steps_completed += 1

        # STEP 16: Morning teaser simulation
        step = 16
        r = await runner.send_cmd("/qa teaser_diamond", timeout=15, surface_id="S17")
        result.artefacts.append(_artefact(r, "S17"))
        result.timings["S17_teaser"] = r.response_time_s
        if r.text == "[TIMEOUT]":
            _defect(result, step, "2", "S17 teaser_diamond timed out")
        result.steps_completed += 1

    except Exception as exc:
        log.error("P3 aborted at step %d: %s", step, exc, exc_info=True)
        result.aborted = True
        result.abort_reason = f"step {step}: {exc}"
        _defect(result, step, "1", f"Script exception: {exc}")

    return result
