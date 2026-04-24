"""Main CLI entry point for the QA Rubric Runner.

BUILD-QA-RUBRIC-RUNNER-01

Usage:
    python -m tests.qa.rubric_runner [--dry-run] [--personas P1,P2,P3,P4] [--output path/to/report.md]

Exit codes:
    0 = PASS or CONDITIONAL PASS
    1 = FAIL or QA-INVALID

--dry-run: run preflight only (no Telegram connection). Exits 0 on preflight pass.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure bot/ CWD is on sys.path so bot modules are importable
# ---------------------------------------------------------------------------
_BOT_DIR = Path(__file__).resolve().parent.parent.parent.parent  # /home/paulsportsza/bot
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

# Change to bot/ dir so relative paths (data/mzansiedge.db etc.) resolve
os.chdir(_BOT_DIR)

from .preflight import run_preflight, print_preflight
from .personas import parse_personas_arg, PERSONAS
from .config import (
    REPORT_DIR,
    SCREENSHOT_DIR,
    SESSION_PATH,
    BOT_USERNAME,
    BOT_REPLY_TIMEOUT,
    PICKS_TIMEOUT,
    STITCH_MOCK_MODE,
    ODDS_DB_PATH,
    MAIN_DB_PATH,
)

log = logging.getLogger("rubric_runner")


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_output_path(output_arg: str | None) -> str:
    if output_arg:
        return output_arg
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    return str(Path(REPORT_DIR) / f"rubric-{ts}.md")


async def _run_persona(
    persona_id: str,
    *,
    api_id: int,
    api_hash: str,
    chat_id: int,
    session_path: str,
) -> dict:
    """Run a single persona script and return raw result dict."""
    from .scripts.base import PersonaRunner

    runner = PersonaRunner(
        persona_id=persona_id,
        session_path=session_path,
        bot_username=BOT_USERNAME,
        api_id=api_id,
        api_hash=api_hash,
        chat_id=chat_id,
        screenshot_dir=SCREENSHOT_DIR,
        default_timeout=BOT_REPLY_TIMEOUT,
        picks_timeout=PICKS_TIMEOUT,
    )

    # Import persona script dynamically
    script_map = {
        "P1": "tests.qa.rubric_runner.scripts.p1_bronze_soccer",
        "P2": "tests.qa.rubric_runner.scripts.p2_gold_multi",
        "P3": "tests.qa.rubric_runner.scripts.p3_diamond_multi",
        "P4": "tests.qa.rubric_runner.scripts.p4_edge_cases",
    }
    module_name = script_map[persona_id]
    import importlib
    script_module = importlib.import_module(module_name)

    log.info("Running persona %s ...", persona_id)
    t0 = time.monotonic()
    async with runner:
        result = await script_module.run(runner)
    elapsed = time.monotonic() - t0
    log.info("Persona %s completed in %.1fs", persona_id, elapsed)

    return {"result": result, "elapsed": elapsed}


def _score_persona(raw_result: object, persona_def: object) -> "PersonaRunResult":
    """Convert raw script result to scored PersonaRunResult."""
    from .scoring.card import score_card_quality, L1Score
    from .scoring.journey import score_journey
    from .scoring.coverage import persona_composite as pc
    from .report import PersonaRunResult

    r = raw_result

    l1 = score_card_quality(r.artefacts, persona_def)
    l2 = score_journey(
        steps_completed=r.steps_completed,
        steps_total=r.steps_total,
        artefacts=r.artefacts,
        defects=r.defects,
        gate_cells=r.gate_matrix_cells,
        aborted=r.aborted,
    )
    composite = pc(l1.raw_score, l2.raw_score)

    return PersonaRunResult(
        persona_id=r.persona_id,
        tier=persona_def.tier,
        steps_completed=r.steps_completed,
        steps_total=r.steps_total,
        l1=l1,
        l2=l2,
        composite=composite,
        defects=r.defects,
        aborted=r.aborted,
        abort_reason=r.abort_reason,
    )


async def _run_all_personas(persona_ids: list[str], api_id: int, api_hash: str, chat_id: int) -> list:
    """Run all selected personas sequentially and return scored results."""
    from .personas import get_persona

    scored_results = []
    for pid in persona_ids:
        persona_def = get_persona(pid)
        try:
            raw_data = await _run_persona(
                pid,
                api_id=api_id,
                api_hash=api_hash,
                chat_id=chat_id,
                session_path=SESSION_PATH,
            )
            scored = _score_persona(raw_data["result"], persona_def)
        except Exception as exc:
            log.error("Persona %s failed: %s", pid, exc, exc_info=True)
            # Build a zero-scored result
            from .scoring.card import L1Score, CDimension
            from .scoring.journey import L2Score
            from .report import PersonaRunResult
            scored = PersonaRunResult(
                persona_id=pid,
                tier=persona_def.tier,
                steps_completed=0,
                steps_total=persona_def.steps_total,
                l1=L1Score(),
                l2=L2Score(),
                composite=0.0,
                defects=[{"sev": "1", "description": f"Persona script failed: {exc}"}],
                aborted=True,
                abort_reason=str(exc),
            )
        scored_results.append(scored)

    return scored_results


def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m tests.qa.rubric_runner",
        description="MzansiEdge QA Rubric Runner (BUILD-QA-RUBRIC-RUNNER-01)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run preflight checks only. Exit 0 on pass.",
    )
    parser.add_argument(
        "--personas",
        default="P1,P2,P3,P4",
        help="Comma-separated persona IDs to run (default: P1,P2,P3,P4)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown report path (default: auto-timestamped in REPORT_DIR)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    print("\n" + "=" * 60)
    print("MzansiEdge QA Rubric Runner — BUILD-QA-RUBRIC-RUNNER-01")
    print("=" * 60)

    # ── Preflight ─────────────────────────────────────────────────────────────
    preflight = run_preflight(skip_process_check=args.dry_run)
    print_preflight(preflight)

    if not preflight.passed:
        print("PREFLIGHT FAILED — aborting run")
        return 1

    if args.dry_run:
        print("--dry-run: preflight passed. Exiting 0.")
        return 0

    # ── Load env ──────────────────────────────────────────────────────────────
    # Load .env from bot/ dir if dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_BOT_DIR / ".env"))
    except ImportError:
        pass  # .env should already be loaded by the shell

    api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    chat_id = int(os.environ.get("TELEGRAM_E2E_TEST_CHAT_ID", "0"))

    if not api_id or not api_hash or not chat_id:
        print("ERROR: TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_E2E_TEST_CHAT_ID not set")
        return 1

    # ── Parse personas ────────────────────────────────────────────────────────
    try:
        personas = parse_personas_arg(args.personas)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    persona_ids = [p.persona_id for p in personas]
    print(f"Running personas: {', '.join(persona_ids)}")

    # ── Execute persona runs ──────────────────────────────────────────────────
    scored_results = asyncio.run(
        _run_all_personas(persona_ids, api_id, api_hash, chat_id)
    )

    # ── L3 Coverage ───────────────────────────────────────────────────────────
    from .scoring.coverage import score_coverage
    from .surfaces import Artefact

    all_artefacts: list[Artefact] = []
    all_gate_cells = []
    all_sports: list[str] = []
    payment_executed = False

    for pr in scored_results:
        all_artefacts.extend([])  # artefacts are on the raw result; scored has L1/L2
        all_gate_cells.extend([])

    # Re-collect from raw results (stored in L2 internally)
    for pid, pr in zip(persona_ids, scored_results):
        persona_def = PERSONAS[pid]
        all_sports.extend(persona_def.sports)
        for dim in pr.l2.dimensions:
            pass

    # Use per-persona gate cells from L2 J5 dimension notes
    # For coverage: approximate from personas run
    from .gate_matrix import build_gate_cells, GateCell
    combined_cells: list[GateCell] = []
    for pid in persona_ids:
        combined_cells.extend(build_gate_cells(pid))

    # Check if P1 completed payment
    p1_result = next((pr for pr in scored_results if pr.persona_id == "P1"), None)
    if p1_result:
        payment_executed = not any(
            "payment link not shown" in d.get("description", "").lower()
            for d in p1_result.defects
        )

    l3 = score_coverage(all_artefacts, combined_cells, list(set(all_sports)))

    # ── Generate report ───────────────────────────────────────────────────────
    from .report import generate_report

    output_path = _build_output_path(args.output)
    run_results = generate_report(
        scored_results,
        l3,
        output_path=output_path,
        stitch_mock_mode=STITCH_MOCK_MODE,
        payment_flow_executed=payment_executed,
    )

    print(f"\n{'='*60}")
    print(f"  Composite Score: {run_results.composite_score:.2f}/10")
    print(f"  Verdict: {run_results.verdict}")
    print(f"  Report: {output_path}")
    print(f"{'='*60}\n")

    # Exit code
    verdict = run_results.verdict
    if "PASS" in verdict and "FAIL" not in verdict:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
