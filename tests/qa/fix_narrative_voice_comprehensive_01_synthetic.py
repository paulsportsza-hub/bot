"""FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 HG-2 synthetic-render evidence harness.

Renders the W82 baseline narrative + verdict for the 6 named brief matches
(Liverpool-Chelsea, Brighton-Wolves, Arsenal-Fulham, Man Utd-Liverpool,
Man City-Brentford, Notts Forest-Newcastle) under realistic tier/odds
fixtures, asserts zero telemetry-vocabulary leaks across all sections, and
emits the rendered text + assertion summary as evidence under
``reports/e2e-screenshots/FIX-NARRATIVE-VOICE-COMPREHENSIVE-01-*``.

Synthetic harness rationale: the Telethon live-screenshot path requires an
interactive Telegram session which is not available from the wave-worktree
runner context. Synthetic rendering exercises the exact ``_render_baseline``
+ ``_render_verdict`` code paths that the bot serves at view time
(W82 baseline path; W84 polish failures fall back to the same renderer per
Rule 23). Output is byte-identical to the production W82 path.

Run: ``bash scripts/qa_safe.sh tests/qa/fix_narrative_voice_comprehensive_01_synthetic.py``
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add bot/ to path when run as a standalone script
_BOT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

from narrative_spec import (  # noqa: E402  pyright: ignore[reportMissingImports]
    NarrativeSpec,
    _render_baseline,
    _render_verdict,
    lookup_coach,
)


_TELEMETRY_PATTERNS: tuple[str, ...] = (
    r"\bthe\s+(?:supporting\s+)?signals?\b",
    r"\bthe\s+reads?\b",
    r"\breads?\s+flag\b",
    r"\bbookmaker\s+(?:has\s+)?slipp(?:ed|ing|s)\b",
    r"\b(?:stays?|kept|keeps?|remains?|stay)\s+in\s+view\b",
    r"\bthe\s+case\s+(?:as\s+it\s+stands|here)\b",
    r"\b(?:the\s+)?model\s+(?:estimates|implies|prices?)\b",
    r"\bindicators?\s+(?:line\s+up|align)\b",
    r"\bstructural\s+(?:signal|lean|read)\b",
    r"\bprice\s+edge\b",
    r"\bsignal[-\s]aware\b",
    r"\bedge\s+confirms?\b",
)
_TELE_RE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _TELEMETRY_PATTERNS
)
# Action-verb cluster (per brief AC-2 rubric)
_ACTION_VERB_RE = re.compile(
    r"\b(?:get on|back|take|worth|ride|leave)\b", re.IGNORECASE
)
# LB-7 manager mould (per brief AC-5)
_LB7_MOULD_RE = re.compile(
    r"\b\w+'s\s+\w+(?:\s+\w+)?\s+sit\s+on\s+\d+\s+points?\b",
    re.IGNORECASE,
)


_FIXTURES = [
    {
        "match_id": "liverpool_vs_chelsea_2026-04-30",
        "home_name": "Liverpool",
        "away_name": "Chelsea",
        "home_team_key": "liverpool",
        "away_team_key": "chelsea",
        "competition": "Premier League",
        "sport": "soccer",
        "outcome": "home",
        "outcome_label": "Liverpool",
        "odds": 1.97,
        "bookmaker": "Supabets",
        "ev_pct": 7.8,
        "fair_prob_pct": 58.0,
        "support_level": 4,
        "tier": "diamond",
        "tone_band": "strong",
        "verdict_action": "strong back",
        "verdict_sizing": "premium stake",
    },
    {
        "match_id": "brighton_vs_wolves_2026-05-01",
        "home_name": "Brighton",
        "away_name": "Wolves",
        "home_team_key": "brighton",
        "away_team_key": "wolves",
        "competition": "Premier League",
        "sport": "soccer",
        "outcome": "home",
        "outcome_label": "Brighton",
        "odds": 1.38,
        "bookmaker": "Betway",
        "ev_pct": 6.1,
        "fair_prob_pct": 80.0,
        "support_level": 3,
        "tier": "gold",
        "tone_band": "confident",
        "verdict_action": "back",
        "verdict_sizing": "standard stake",
    },
    {
        "match_id": "arsenal_vs_fulham_2026-05-02",
        "home_name": "Arsenal",
        "away_name": "Fulham",
        "home_team_key": "arsenal",
        "away_team_key": "fulham",
        "competition": "Premier League",
        "sport": "soccer",
        "outcome": "home",
        "outcome_label": "Arsenal",
        "odds": 1.55,
        "bookmaker": "Hollywoodbets",
        "ev_pct": 5.5,
        "fair_prob_pct": 70.0,
        "support_level": 3,
        "tier": "gold",
        "tone_band": "confident",
        "verdict_action": "back",
        "verdict_sizing": "standard stake",
    },
    {
        "match_id": "manchester_united_vs_liverpool_2026-05-03",
        "home_name": "Manchester United",
        "away_name": "Liverpool",
        "home_team_key": "manchester united",
        "away_team_key": "liverpool",
        "competition": "Premier League",
        "sport": "soccer",
        "outcome": "away",
        "outcome_label": "Liverpool",
        "odds": 1.85,
        "bookmaker": "Supabets",
        "ev_pct": 5.8,
        "fair_prob_pct": 60.0,
        "support_level": 3,
        "tier": "gold",
        "tone_band": "confident",
        "verdict_action": "back",
        "verdict_sizing": "standard stake",
    },
    {
        "match_id": "manchester_city_vs_brentford_2026-05-09",
        "home_name": "Manchester City",
        "away_name": "Brentford",
        "home_team_key": "manchester city",
        "away_team_key": "brentford",
        "competition": "Premier League",
        "sport": "soccer",
        "outcome": "home",
        "outcome_label": "Manchester City",
        "odds": 1.42,
        "bookmaker": "Hollywoodbets",
        "ev_pct": 6.5,
        "fair_prob_pct": 75.0,
        "support_level": 4,
        "tier": "gold",
        "tone_band": "confident",
        "verdict_action": "back",
        "verdict_sizing": "standard stake",
    },
    {
        "match_id": "nottingham_forest_vs_newcastle_2026-05-10",
        "home_name": "Nottingham Forest",
        "away_name": "Newcastle",
        "home_team_key": "nottingham forest",
        "away_team_key": "newcastle",
        "competition": "Premier League",
        "sport": "soccer",
        "outcome": "home",
        "outcome_label": "Forest",
        "odds": 2.52,
        "bookmaker": "Supabets",
        "ev_pct": 1.2,
        "fair_prob_pct": 42.0,
        "support_level": 2,
        "tier": "bronze",
        "tone_band": "moderate",
        "verdict_action": "lean",
        "verdict_sizing": "small-to-standard stake",
    },
]


def _build_spec(fix: dict) -> NarrativeSpec:
    return NarrativeSpec(
        sport=fix["sport"],
        competition=fix["competition"],
        home_name=fix["home_name"],
        away_name=fix["away_name"],
        home_story_type="momentum",
        away_story_type="setback",
        home_coach=lookup_coach(fix["home_team_key"]) or "",
        away_coach=lookup_coach(fix["away_team_key"]) or "",
        home_form="WWWLW",
        away_form="LLWLW",
        outcome=fix["outcome"],
        outcome_label=fix["outcome_label"],
        odds=fix["odds"],
        bookmaker=fix["bookmaker"],
        ev_pct=fix["ev_pct"],
        fair_prob_pct=fix["fair_prob_pct"],
        composite_score=60.0 + fix["ev_pct"],
        support_level=fix["support_level"],
        contradicting_signals=0,
        evidence_class=(
            "conviction" if fix["tier"] == "diamond"
            else "supported" if fix["tier"] == "gold"
            else "lean" if fix["tier"] == "silver"
            else "lean"
        ),
        tone_band=fix["tone_band"],
        verdict_action=fix["verdict_action"],
        verdict_sizing=fix["verdict_sizing"],
        edge_tier=fix["tier"],
    )


def _telemetry_hits(text: str) -> list[str]:
    return [p.pattern for p in _TELE_RE if p.search(text)]


def _setup_block(narrative: str) -> str:
    setup = "📋 <b>The Setup</b>"
    edge = "🎯"
    si = narrative.find(setup)
    if si == -1:
        return ""
    ei = narrative.find(edge, si + len(setup))
    return narrative[si:ei].strip() if ei != -1 else narrative[si:]


def _verdict_block(narrative: str) -> str:
    marker = "🏆 <b>Verdict</b>"
    vi = narrative.find(marker)
    return narrative[vi:].strip() if vi != -1 else ""


def _render_one(fix: dict) -> dict:
    spec = _build_spec(fix)
    baseline = _render_baseline(spec)
    verdict_only = _render_verdict(spec)
    setup = _setup_block(baseline)
    return {
        "match_id": fix["match_id"],
        "tier": fix["tier"],
        "outcome_label": fix["outcome_label"],
        "odds": fix["odds"],
        "bookmaker": fix["bookmaker"],
        "home_coach": spec.home_coach or "",
        "away_coach": spec.away_coach or "",
        "baseline_html": baseline,
        "setup_text": setup,
        "verdict_only": verdict_only,
        "verdict_block": _verdict_block(baseline),
        # Voice gate findings
        "telemetry_hits_full": _telemetry_hits(baseline),
        "telemetry_hits_verdict": _telemetry_hits(verdict_only),
        "telemetry_hits_setup": _telemetry_hits(setup),
        "has_action_verb_in_verdict": bool(_ACTION_VERB_RE.search(verdict_only)),
        "has_lb7_mould_in_setup": bool(_LB7_MOULD_RE.search(setup[:120])),
        "verdict_len": len(verdict_only),
    }


@pytest.fixture(scope="module")
def _evidence_dir() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = _BOT_ROOT / "reports" / "e2e-screenshots" / f"FIX-NARRATIVE-VOICE-COMPREHENSIVE-01-{ts}"
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture(scope="module")
def _all_renders(_evidence_dir: Path) -> list[dict]:
    renders = [_render_one(f) for f in _FIXTURES]
    # Persist evidence
    (_evidence_dir / "summary.json").write_text(json.dumps(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fixture_count": len(_FIXTURES),
            "tier_distribution": {tier: sum(1 for r in renders if r["tier"] == tier)
                                  for tier in ("diamond", "gold", "silver", "bronze")},
            "telemetry_hit_count_total": sum(
                len(r["telemetry_hits_full"]) for r in renders
            ),
            "verdicts_with_action_verb": sum(
                1 for r in renders if r["has_action_verb_in_verdict"]
            ),
            "setups_with_lb7_mould": sum(
                1 for r in renders if r["has_lb7_mould_in_setup"]
            ),
            "verdict_char_distribution": {
                r["match_id"]: r["verdict_len"] for r in renders
            },
            "renders": [
                {k: v for k, v in r.items()
                 if k not in ("baseline_html", "setup_text", "verdict_block")}
                for r in renders
            ],
        },
        indent=2,
    ))
    # Also write the full rendered text per match for visual review
    for r in renders:
        path = _evidence_dir / f"{r['match_id']}.txt"
        path.write_text(
            f"# {r['match_id']} — tier={r['tier']}\n"
            f"# odds={r['odds']} {r['bookmaker']} — outcome={r['outcome_label']}\n"
            f"# home_coach={r['home_coach']!r}  away_coach={r['away_coach']!r}\n\n"
            f"{r['baseline_html']}\n\n"
            f"---\n"
            f"# Standalone verdict ({r['verdict_len']} chars):\n\n"
            f"{r['verdict_only']}\n"
        )
    return renders


# ── Voice gate assertions ────────────────────────────────────────────────────


def test_zero_telemetry_leaks_across_all_6_renders(_all_renders):
    """Brief HG-2: 0/6 cards may hit Rule 17 telemetry vocabulary."""
    leaks = [
        (r["match_id"], r["telemetry_hits_full"])
        for r in _all_renders if r["telemetry_hits_full"]
    ]
    assert leaks == [], (
        f"Telemetry leaks in {len(leaks)}/6 cards: {leaks}"
    )


def test_setups_do_not_use_lb7_manager_mould(_all_renders):
    """Brief HG-2 + brief AC-5: 0/6 Setup openings carry the
    ``<Manager>'s <Team> sit on N points`` mould."""
    leaks = [
        r["match_id"] for r in _all_renders if r["has_lb7_mould_in_setup"]
    ]
    assert leaks == [], f"LB-7 mould detected in: {leaks}"


def test_majority_of_verdicts_have_action_verb(_all_renders):
    """Brief HG-4 acceptance: ≥1 verdict in the 5/6-card sample uses an
    action verb (get on, back, take, worth, ride, leave). The 6-card sample
    here is stricter — we expect ≥4/6."""
    with_verb = [r for r in _all_renders if r["has_action_verb_in_verdict"]]
    assert len(with_verb) >= 4, (
        f"Only {len(with_verb)}/6 verdicts contain an action verb"
    )


def test_verdicts_within_char_range(_all_renders):
    """Brief AC-2 + Rule 14: 100% of verdicts in [100, 260]."""
    out_of_range = [
        (r["match_id"], r["verdict_len"]) for r in _all_renders
        if not (100 <= r["verdict_len"] <= 260)
    ]
    assert out_of_range == [], (
        f"Verdicts outside [100, 260]: {out_of_range}"
    )


def test_lb3_pereira_in_forest_setup(_all_renders):
    """LB-3 closure: the Notts Forest verdict must cite Pereira (per
    coaches.json), zero ``Nuno``."""
    forest = next(r for r in _all_renders
                  if r["match_id"] == "nottingham_forest_vs_newcastle_2026-05-10")
    # Setup should reference Pereira (resolved from coaches.json)
    assert "Pereira" in forest["setup_text"], (
        f"Pereira not cited in Forest setup: {forest['setup_text'][:300]!r}"
    )
    # Zero Nuno anywhere in the rendered narrative
    full = forest["baseline_html"] + " " + forest["verdict_only"]
    assert not re.search(r"\bnuno\b", full, re.IGNORECASE), (
        f"Nuno still present in Forest narrative: {full[:300]!r}"
    )
