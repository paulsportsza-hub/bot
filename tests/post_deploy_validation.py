#!/usr/bin/env python3
"""Post-deploy validation suite for MzansiEdge bot.

Runs 5 automated checks after every bot restart. Can be triggered:
  - Automatically: job_queue.run_once() 30s after startup
  - Manually: /qa validate command

Each check returns (passed, label, detail). The suite aggregates results
and formats them for Telegram + log file output.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone

# Ensure project roots are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import BOT_ROOT, ensure_scrapers_importable
ensure_scrapers_importable()

log = logging.getLogger("mzansiedge.validation")

REPORT_DIR = str(BOT_ROOT.parent / "reports")


# ── W81-HEALTH: Fixture-aware thresholds ─────────────────────────────────


def _is_slump_day() -> bool:
    """True on Mon/Tue/Thu — post-weekend or mid-week rest day, fewer fixtures expected."""
    return datetime.now(timezone.utc).weekday() in (0, 1, 3)  # 0=Mon,1=Tue,3=Thu


def _fixture_minimum() -> int:
    return 1 if _is_slump_day() else 3


# ── Check 1: Edge Generation ─────────────────────────────────────────────


def check_edges() -> list[tuple[bool, str, str]]:
    """Validate edge pipeline produces enough diverse, consistent edges."""
    results = []
    try:
        from scrapers.edge.edge_v2_helper import get_top_edges
        edges = get_top_edges(n=20)
    except Exception as e:
        return [(False, "Edge pipeline", f"Import/call error: {e}")]

    # 1a: Minimum count (fixture-aware — W81-HEALTH)
    count = len(edges)
    min_count = _fixture_minimum()
    results.append((
        count >= min_count,
        f"Edge count >= {min_count}",
        f"{count} edges" + (" (slump day)" if _is_slump_day() else ""),
    ))

    # 1b: At least 1 Gold or Diamond (pass on slump days — W81-HEALTH)
    gold_plus = [e for e in edges if e.get("tier") in ("gold", "diamond")]
    slump = _is_slump_day()
    results.append((
        len(gold_plus) >= 1 or slump,
        "At least 1 Gold+ edge",
        f"{len(gold_plus)} Gold+ edges" + (" (slump day — OK)" if slump and not gold_plus else ""),
    ))

    # 1c: Draw ratio <= 40%
    if edges:
        draws = sum(1 for e in edges if e.get("outcome") == "draw")
        ratio = draws / len(edges)
        results.append((
            ratio <= 0.40,
            "Draw ratio <= 40%",
            f"{ratio * 100:.0f}% draws ({draws}/{len(edges)})",
        ))
    else:
        results.append((True, "Draw ratio", "No edges to check"))

    # 1d: All edges have composite_score > 0 and signals dict
    if edges:
        score_ok = all(
            e.get("composite_score", 0) > 0 and isinstance(e.get("signals"), dict)
            for e in edges
        )
        results.append((
            score_ok,
            "Signal consistency",
            "All edges have composite_score > 0" if score_ok
            else "Some edges missing score or signals",
        ))
    else:
        results.append((False, "Signal consistency", "No edges"))

    return results


# ── Check 2: Gate Leak Spot-Check ─────────────────────────────────────────


def check_gates() -> list[tuple[bool, str, str]]:
    """Verify tier gating logic returns correct access levels."""
    results = []
    try:
        from tier_gate import get_edge_access_level
    except ImportError:
        return [(False, "Gate import", "Cannot import tier_gate")]

    # Test matrix: (user_tier, edge_tier, expected_access)
    test_cases = [
        ("bronze", "bronze", "full"),
        ("bronze", "silver", "partial"),
        ("bronze", "gold", "blurred"),
        ("bronze", "diamond", "locked"),
        ("gold", "bronze", "full"),
        ("gold", "gold", "full"),
        ("gold", "diamond", "blurred"),
        ("diamond", "bronze", "full"),
        ("diamond", "gold", "full"),
        ("diamond", "diamond", "full"),
    ]

    failures = []
    for user_tier, edge_tier, expected in test_cases:
        actual = get_edge_access_level(user_tier, edge_tier)
        if actual != expected:
            failures.append(f"{user_tier}->{edge_tier}: expected {expected}, got {actual}")

    if failures:
        results.append((False, "Gate matrix", "; ".join(failures[:3])))
    else:
        results.append((True, "Gate matrix", f"{len(test_cases)} tier combos correct"))

    # Business rule: Bronze viewing Gold = no odds
    bronze_gold = get_edge_access_level("bronze", "gold")
    results.append((
        bronze_gold in ("blurred", "locked"),
        "Bronze no Gold odds",
        f"Bronze->Gold = {bronze_gold}",
    ))

    # Business rule: Diamond sees everything
    diamond_all = all(
        get_edge_access_level("diamond", t) == "full"
        for t in ("bronze", "silver", "gold", "diamond")
    )
    results.append((
        diamond_all,
        "Diamond full access",
        "Diamond sees all tiers" if diamond_all else "Diamond access restricted",
    ))

    return results


# ── Check 3: AI Breakdown Integrity ──────────────────────────────────────


def check_ai_pipeline() -> list[tuple[bool, str, str]]:
    """Test AI post-processing pipeline without triggering Claude."""
    results = []

    try:
        from bot import sanitize_ai_response, fact_check_output, build_verified_narrative
    except ImportError as e:
        return [(False, "AI pipeline import", f"Import failed: {e}")]

    # 3a: sanitize_ai_response strips markdown headers
    raw = (
        "## The Setup\n"
        "**Arsenal** sit 2nd on 50 points.\n\n"
        "## The Edge\n"
        "Good value on Arsenal win.\n\n"
        "## The Risk\n"
        "Chelsea away form strong.\n\n"
        "## Verdict\n"
        "Back Arsenal with Medium conviction.\n"
    )
    sanitized = sanitize_ai_response(raw)
    no_md_headers = "##" not in sanitized
    has_html_bold = "<b>" in sanitized
    conviction_gone = "Medium conviction" not in sanitized

    results.append((
        no_md_headers,
        "Markdown headers stripped",
        "No ## headers" if no_md_headers else "## headers leaked",
    ))
    results.append((
        has_html_bold,
        "HTML bold present",
        "<b> tags added" if has_html_bold else "Missing <b> tags",
    ))
    results.append((
        conviction_gone,
        "Conviction text stripped",
        "Removed" if conviction_gone else "Conviction text leaked",
    ))

    # 3b: fact_check_output strips fabricated positions
    fake_ctx = {
        "data_available": True,
        "home_team": {"name": "Arsenal", "league_position": 2},
        "away_team": {"name": "Chelsea", "league_position": 4},
    }
    bad_narrative = "Arsenal sit 5th in the league.\nChelsea are looking strong."
    checked = fact_check_output(bad_narrative, fake_ctx, sport="soccer")
    position_stripped = "5th" not in checked

    results.append((
        position_stripped,
        "Fact-check strips bad position",
        "Fabricated '5th' stripped" if position_stripped else "'5th' leaked through",
    ))

    # 3c: build_verified_narrative returns structured dict
    ctx_data = {
        "data_available": True,
        "home_team": {"name": "Sundowns", "league_position": 1, "points": 45,
                      "form": "WWWDW", "last_5": []},
        "away_team": {"name": "Chiefs", "league_position": 5, "points": 28,
                      "form": "WLDLW", "last_5": []},
    }
    narrative = build_verified_narrative(ctx_data, sport="soccer")
    is_dict = isinstance(narrative, dict)
    has_setup = bool(narrative.get("setup")) if is_dict else False

    results.append((
        is_dict and has_setup,
        "Verified narrative structure",
        f"Dict with {len(narrative.get('setup', []))} setup sentences"
        if is_dict else "Not a dict",
    ))

    return results


# ── Check 4: System Health ────────────────────────────────────────────────


def check_health() -> list[tuple[bool, str, str]]:
    """Run full health pipeline via existing health_monitor."""
    try:
        from scrapers.health_monitor import run_all_checks_for_display
        result = run_all_checks_for_display()
    except Exception as e:
        return [(False, "Health monitor", f"Import/call error: {e}")]

    results = []
    for name, emoji, detail in result.get("checks", []):
        passed = emoji == "\u2705"
        results.append((passed, f"Health: {name}", detail[:120]))

    if not results:
        results.append((False, "Health monitor", "No checks returned"))

    return results


# ── Check 5: Core Bot Functions ───────────────────────────────────────────


def check_handlers() -> list[tuple[bool, str, str]]:
    """Verify core bot handlers exist and are async coroutines."""
    results = []

    try:
        import bot as bot_module
    except Exception as e:
        return [(False, "Bot import", f"Cannot import bot: {e}")]

    # Key handlers that must exist and be async
    handler_names = [
        "cmd_start", "cmd_picks", "cmd_qa", "cmd_menu", "cmd_help",
        "on_button", "handle_keyboard_tap", "_do_hot_tips_flow",
    ]

    missing = []
    for name in handler_names:
        fn = getattr(bot_module, name, None)
        if fn is None or not asyncio.iscoroutinefunction(fn):
            missing.append(name)

    if missing:
        results.append((False, "Handler functions", f"Missing/non-async: {', '.join(missing)}"))
    else:
        results.append((True, "Handler functions", f"{len(handler_names)} handlers OK"))

    # ADMIN_IDS populated
    try:
        import config
        has_admins = len(config.ADMIN_IDS) > 0
        results.append((has_admins, "ADMIN_IDS", f"{len(config.ADMIN_IDS)} admin(s)"))
    except Exception:
        results.append((False, "ADMIN_IDS", "Cannot import config"))

    # QA commands dict has expected keys
    qa_cmds = getattr(bot_module, "_QA_COMMANDS", {})
    has_health = "health" in qa_cmds
    has_validate = "validate" in qa_cmds
    results.append((
        has_health and has_validate,
        "QA commands",
        f"{len(qa_cmds)} commands, health={'Y' if has_health else 'N'}, validate={'Y' if has_validate else 'N'}",
    ))

    return results


# ── Check 6: Breakdown Quality (W44-GUARDS) ─────────────────────────────


async def check_breakdown_quality() -> list[tuple[bool, str, str]]:
    """Verify match context pipeline returns real data for EPL (not fallback)."""
    results = []
    _fallback_phrases = [
        "limited verified data",
        "no verified context",
        "form data unavailable",
        "data currently unavailable",
    ]

    try:
        from scrapers.match_context_fetcher import get_match_context
        # W51-FIX: await directly (this check is detected as async by the runner)
        ctx = await get_match_context("arsenal", "chelsea", "epl")
    except Exception as e:
        return [(False, "Match context fetch", f"Error: {e}")]

    # 6a: data_available is True
    avail = ctx and ctx.get("data_available", False)
    results.append((
        avail,
        "EPL context data_available",
        "True" if avail else "False — pipeline broken",
    ))

    if not avail:
        return results

    # 6b: Home team has position + form
    home = ctx.get("home_team", {})
    has_pos = isinstance(home.get("league_position"), int)
    has_form = bool(home.get("form"))
    results.append((
        has_pos and has_form,
        "EPL home team data",
        f"pos={home.get('league_position')}, form={home.get('form', 'N/A')}",
    ))

    # 6c: No fallback phrases in team names or data
    ctx_str = str(ctx).lower()
    found = [p for p in _fallback_phrases if p in ctx_str]
    results.append((
        len(found) == 0,
        "No fallback phrases",
        "Clean" if not found else f"Found: {', '.join(found)}",
    ))

    return results


# ── Check 7: Edge Accuracy Spot-Check (Layer 2) ────────────────────────


def check_edge_accuracy() -> list[tuple[bool, str, str]]:
    """Spot-check Layer 2 edge accuracy: signal coverage + tier thresholds."""
    results = []

    try:
        from scrapers.edge.edge_v2_helper import get_top_edges
        from scrapers.edge.edge_config import SIGNAL_WEIGHTS
        edges = get_top_edges(n=20)
    except Exception as e:
        return [(False, "Edge accuracy import", f"Error: {e}")]

    if not edges:
        results.append((True, "Edge accuracy", "No live edges — skipped"))
        return results

    # 7a: Signal coverage — no edge should have >50% signals defaulting
    violations = []
    for e in edges:
        signals = e.get("signals", {})
        if not signals:
            continue
        total = len(signals)
        if total == 0:
            continue
        defaulting = sum(1 for s in signals.values() if not s.get("available", False))
        pct = (defaulting / total) * 100
        if pct > 50:
            violations.append(f"{e['match_key']}: {defaulting}/{total} ({pct:.0f}%)")

    results.append((
        len(violations) == 0,
        "Signal coverage <= 50%",
        "All edges OK" if not violations else f"{len(violations)} violations: {violations[0]}",
    ))

    # 7b: Tier ordering — higher tiers should have higher avg composite
    by_tier: dict[str, list[float]] = {}
    for e in edges:
        tier = e.get("tier", "bronze")
        by_tier.setdefault(tier, []).append(e.get("composite_score", 0))
    avgs = {t: sum(s) / len(s) for t, s in by_tier.items() if s}

    ordering_ok = True
    if "diamond" in avgs and "bronze" in avgs:
        if avgs["diamond"] < avgs["bronze"]:
            ordering_ok = False
    results.append((
        ordering_ok,
        "Tier ordering consistent",
        f"Tier avgs: {', '.join(f'{t}={v:.0f}' for t, v in sorted(avgs.items()))}",
    ))

    # 7c: No negative EV
    neg_ev = [e for e in edges if e.get("edge_pct", 0) <= 0]
    results.append((
        len(neg_ev) == 0,
        "No negative EV edges",
        f"{len(neg_ev)} negative EV" if neg_ev else "All positive EV",
    ))

    return results


# ── Check 8: Bronze User Journey (Layer 5 Spot-Check) ─────────────────


def check_bronze_journey() -> list[tuple[bool, str, str]]:
    """Verify Bronze user journey: gate returns correct access, locked edges visible."""
    results = []

    try:
        from tier_gate import get_edge_access_level
    except ImportError as e:
        return [(False, "Bronze journey import", f"Error: {e}")]

    # 8a: Bronze sees bronze edges as full
    access = get_edge_access_level("bronze", "bronze")
    results.append((
        access == "full",
        "Bronze sees bronze = full",
        f"Got: {access}",
    ))

    # 8b: Bronze sees diamond as locked
    access_d = get_edge_access_level("bronze", "diamond")
    results.append((
        access_d == "locked",
        "Bronze sees diamond = locked",
        f"Got: {access_d}",
    ))

    # 8c: Hot tips function importable and callable
    try:
        from scrapers.edge.edge_v2_helper import get_top_edges
        edges = get_top_edges(n=5)
        has_edges = isinstance(edges, list)
        results.append((
            has_edges,
            "Edge pipeline returns list",
            f"{len(edges)} edges" if has_edges else "Not a list",
        ))
    except Exception as e:
        results.append((False, "Edge pipeline call", f"Error: {e}"))

    # 8d: Edge dicts have required keys for display
    if edges:
        required = {"match_key", "outcome", "tier", "composite_score", "edge_pct"}
        sample = edges[0]
        missing = required - set(sample.keys())
        results.append((
            len(missing) == 0,
            "Edge dict has display keys",
            f"Missing: {missing}" if missing else "All keys present",
        ))

    return results


# ── Suite Runner ──────────────────────────────────────────────────────────


ALL_CHECKS = [
    ("Edge Generation", check_edges),
    ("Gate Leaks", check_gates),
    ("AI Pipeline", check_ai_pipeline),
    ("System Health", check_health),
    ("Core Handlers", check_handlers),
    ("Breakdown Quality", check_breakdown_quality),
    ("Edge Accuracy", check_edge_accuracy),
    ("Bronze Journey", check_bronze_journey),
]


async def run_validation_suite(trigger: str = "auto_startup") -> dict:
    """Execute all validation checks.

    Args:
        trigger: "auto_startup" | "qa_command" | "cli"

    Returns:
        {"pass_count": int, "total": int, "failures": list[str],
         "details": list[str], "trigger": str, "duration_ms": float}
    """
    start = time.monotonic()
    loop = asyncio.get_event_loop()

    all_results: list[tuple[bool, str, str]] = []
    failures: list[str] = []
    details: list[str] = []

    for group_name, check_fn in ALL_CHECKS:
        try:
            if asyncio.iscoroutinefunction(check_fn):
                # W51-FIX: async checks run directly on the event loop
                sub_results = await check_fn()
            else:
                sub_results = await loop.run_in_executor(None, check_fn)
        except Exception as e:
            sub_results = [(False, group_name, f"Crashed: {e}")]

        for passed, label, detail in sub_results:
            all_results.append((passed, label, detail))
            emoji = "\u2705" if passed else "\u274c"
            details.append(f"{emoji} {label}: {detail}")
            if not passed:
                failures.append(f"{label}: {detail}")

    duration_ms = (time.monotonic() - start) * 1000
    pass_count = sum(1 for p, _, _ in all_results if p)

    return {
        "pass_count": pass_count,
        "total": len(all_results),
        "failures": failures,
        "details": details,
        "trigger": trigger,
        "duration_ms": duration_ms,
    }


# ── Output Formatters ─────────────────────────────────────────────────────


def format_telegram_message(results: dict) -> str:
    """Format validation results as Telegram HTML message."""
    pc = results["pass_count"]
    total = results["total"]
    failures = results["failures"]
    ms = results["duration_ms"]

    if not failures:
        pid = os.getpid()
        return (
            f"\u2705 <b>Post-deploy validation: {pc}/{total} PASS</b>\n"
            f"Bot PID {pid} \u2014 all systems go.\n"
            f"<i>{results['trigger']} | {ms:.0f}ms</i>"
        )

    lines = [
        f"\U0001f534 <b>Post-deploy validation: {len(failures)} FAIL</b>\n",
    ]
    for f in failures:
        lines.append(f"\u274c {f}")

    lines.append(f"\n\u2705 {pc}/{total} other checks passed.")
    lines.append(f"<i>{results['trigger']} | {ms:.0f}ms</i>")
    return "\n".join(lines)


def write_report(results: dict) -> str:
    """Write plain-text report to reports/ directory. Returns file path."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    path = os.path.join(REPORT_DIR, f"post_deploy_validation_{ts}.txt")

    lines = [
        "MzansiEdge Post-Deploy Validation Report",
        f"Trigger: {results['trigger']}",
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
        f"Duration: {results['duration_ms']:.0f}ms",
        f"Result: {results['pass_count']}/{results['total']} PASS",
        "",
    ]
    lines.extend(results["details"])

    if results["failures"]:
        lines.append("")
        lines.append("FAILURES:")
        for f in results["failures"]:
            lines.append(f"  - {f}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")

    log.info("Validation report written: %s", path)
    return path


# ── CLI Entry Point ───────────────────────────────────────────────────────


async def _cli_main():
    results = await run_validation_suite(trigger="cli")
    path = write_report(results)

    for line in results["details"]:
        print(line)

    print(f"\nResult: {results['pass_count']}/{results['total']} PASS")
    print(f"Report: {path}")

    sys.exit(0 if not results["failures"] else 1)


if __name__ == "__main__":
    asyncio.run(_cli_main())
