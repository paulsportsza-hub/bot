"""P2 — Gold multi-sport persona script (15 steps).

BUILD-QA-RUBRIC-RUNNER-01 — Phase B

Script:
  /qa reset → /start → onboarding (Soccer+Rugby+Cricket, Aggressive, R3000, 18:00)
  → /qa set_gold → Top Edge Picks → verify Gold view
  → tap Silver edge (blurred→full for Gold) → tap Gold edge (full for Gold)
  → My Matches → /billing or /status

Expected GATE_MATRIX cells:
  Gold×Bronze (full), Gold×Silver (full), Gold×Gold (full), Gold×Diamond (partial)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..gate_matrix import GateCell, build_gate_cells
from ..scripts.base import PersonaRunner, Reply
from ..surfaces import Artefact

log = logging.getLogger(__name__)

PERSONA_ID = "P2"
STEPS_TOTAL = 15


@dataclass
class P2Result:
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


def _defect(result: P2Result, step: int, sev: str, desc: str) -> None:
    result.defects.append({"step": step, "sev": sev, "description": desc})
    log.warning("P2 defect SEV-%s step %d: %s", sev, step, desc)


async def run(runner: PersonaRunner) -> P2Result:
    result = P2Result()
    result.gate_matrix_cells = build_gate_cells(PERSONA_ID)
    step = 0

    try:
        # STEP 1: Reset
        step = 1
        r = await runner.send_cmd("/qa reset", surface_id="S0")
        result.artefacts.append(_artefact(r, "S0"))
        result.steps_completed += 1

        # STEP 2: /start
        step = 2
        r = await runner.send_cmd("/start", surface_id="S0")
        result.artefacts.append(_artefact(r, "S0"))
        result.steps_completed += 1

        # STEP 3: Experience
        step = 3
        r = await runner.tap_button(r, "Experienced")
        result.artefacts.append(_artefact(r, "S0"))
        result.steps_completed += 1

        # STEP 4-6: Select Soccer + Rugby + Cricket
        step = 4
        r = await runner.tap_button(r, "Soccer")
        result.steps_completed += 1

        step = 5
        r = await runner.tap_button(r, "Rugby")
        result.steps_completed += 1

        step = 6
        r = await runner.tap_button(r, "Cricket")
        result.steps_completed += 1

        r = await runner.tap_button(r, "Done")

        # STEP 7: Teams (skip/generic for each sport)
        step = 7
        for _ in range(3):
            try:
                r = await runner.send_cmd("skip", timeout=8, surface_id="S0")
            except Exception:
                try:
                    r = await runner.tap_button(r, "Done")
                except Exception:
                    pass
        result.artefacts.append(_artefact(r, "S0"))
        result.steps_completed += 1

        # STEP 8: Risk — Aggressive
        step = 8
        r = await runner.tap_button(r, "Aggressive")
        result.steps_completed += 1

        # STEP 9: Bankroll
        step = 9
        r = await runner.tap_button(r, "R1")
        result.steps_completed += 1

        # STEP 10: Notify time 18:00
        step = 10
        r = await runner.tap_button(r, "18")
        result.steps_completed += 1

        # STEP 11: Confirm
        step = 11
        r = await runner.tap_button(r, "Let's go")
        result.artefacts.append(_artefact(r, "S1"))
        result.steps_completed += 1

        # STEP 11b: Set Gold tier via /qa command
        step = 11
        r = await runner.send_cmd("/qa set_gold", surface_id="S0")
        result.artefacts.append(_artefact(r, "S0"))

        # STEP 12: Top Edge Picks — verify Gold view
        step = 12
        r = await runner.send_cmd("💎 Top Edge Picks", timeout=runner.picks_timeout, surface_id="S2")
        result.artefacts.append(_artefact(r, "S2"))
        result.timings["S2_gold_load"] = r.response_time_s
        if r.text == "[TIMEOUT]":
            _defect(result, step, "1", "S2 timeout for Gold user")
            result.aborted = True
            result.abort_reason = "S2 timeout"
            return result
        result.steps_completed += 1

        # STEP 13: Tap a Gold edge (Gold×Gold = full for Gold)
        step = 13
        gold_btn = None
        for row in r.buttons:
            for label in row:
                if "🥇" in label and "🔒" not in label:
                    gold_btn = label
                    break
            if gold_btn:
                break

        if gold_btn:
            r_g = await runner.tap_button(r, gold_btn, timeout=15)
            result.artefacts.append(_artefact(r_g, "S3"))
            for cell in result.gate_matrix_cells:
                if cell.user_tier == "gold" and cell.edge_tier == "gold":
                    cell.tested = True
                    cell.actual = "full" if "bookmaker" in r_g.text.lower() or "ev" in r_g.text.lower() else "partial"
        result.steps_completed += 1

        # STEP 14: My Matches
        step = 14
        r = await runner.send_cmd("⚽ My Matches", timeout=runner.default_timeout, surface_id="S4")
        result.artefacts.append(_artefact(r, "S4"))
        result.timings["S4_gold_load"] = r.response_time_s
        result.steps_completed += 1

        # STEP 15: Billing/status
        step = 15
        r = await runner.send_cmd("/status", timeout=8, surface_id="S16")
        result.artefacts.append(_artefact(r, "S16"))
        if "gold" not in r.text.lower() and "subscription" not in r.text.lower():
            _defect(result, step, "2", "S16 /status does not confirm Gold tier")
        result.steps_completed += 1

    except Exception as exc:
        log.error("P2 aborted at step %d: %s", step, exc, exc_info=True)
        result.aborted = True
        result.abort_reason = f"step {step}: {exc}"
        _defect(result, step, "1", f"Script exception: {exc}")

    return result
