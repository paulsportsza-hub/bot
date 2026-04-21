"""
Unit test: _render_verdict() floor/ceiling/lean directly on narrative_spec.py.
Does NOT require Telethon — runs against the live code.
"""
import sys
sys.path.insert(0, '/home/paulsportsza/bot')

from narrative_spec import (
    NarrativeSpec, _render_verdict, _VERDICT_MIN_CHARS, _VERDICT_MAX_CHARS,
)

print(f"VERDICT_MIN = {_VERDICT_MIN_CHARS}")
print(f"VERDICT_MAX = {_VERDICT_MAX_CHARS}")
print()

# 6 verdict action types × 3 ev/support configurations = 18 total tests
test_matrix = [
    # label,             action,          ev,    odds, bk,           outcome,       support
    ("speculative/0sig", "speculative punt", 1.5, 2.86, "PlayaBets",  "Atletico win", 0),
    ("speculative/1sig", "speculative punt", 2.5, 2.40, "Supabets",   "Fulham win",   1),
    ("lean/2sig",        "lean",           3.5,  1.65, "Supabets",   "Arsenal win",  2),
    ("lean/3sig",        "lean",           5.0,  1.80, "Sportingbet","Brighton win", 3),
    ("back/3sig",        "back",           6.0,  2.20, "Sportingbet","Man City win", 3),
    ("back/4sig",        "back",           8.0,  1.90, "GBets",      "Liverpool win",4),
    ("strong/4sig",      "strong back",    9.0,  1.80, "GBets",      "Burnley win",  4),
    ("strong/5sig",      "strong back",   12.0,  2.10, "PlayaBets",  "Everton win",  5),
    ("pass/neg_ev",      "pass",          -1.0,  1.40, "WSB",        "Man City win", 0),
    ("monitor/zero_ev",  "monitor",        0.0,  2.10, "Hollywoodbets","Chelsea win",0),
    # Edge EV cases
    ("lean/low_ev",      "lean",           1.1,  3.50, "WSB",        "Newcastle win",1),
    ("back/high_ev",     "back",          14.0,  4.20, "PlayaBets",  "Watford win",  4),
    # Different sports
    ("rugby/lean",       "lean",           3.0,  2.00, "Supabets",   "Crusaders win",2),
    ("cricket/back",     "back",           5.5,  2.30, "GBets",      "SA win",       3),
    ("mma/speculative",  "speculative punt", 2.0, 1.85, "SSB",       "Dricus win",   0),
]

print("=== UNIT TEST: _render_verdict() floor/ceiling/lean ===")
print()

all_pass = True
results = []

for label, action, ev, odds, bk, outcome, support in test_matrix:
    spec = NarrativeSpec(
        home_name="Arsenal", away_name="Liverpool",
        competition="Premier League", sport="soccer",
        home_story_type="neutral", away_story_type="neutral",
        outcome_label=outcome, odds=odds, bookmaker=bk,
        ev_pct=ev, composite_score=55.0,
        evidence_class="lean", tone_band="moderate",
        verdict_action=action, verdict_sizing="standard stake",
        support_level=support,
        bookmaker_count=3,
    )
    verdict = _render_verdict(spec)
    vlen = len(verdict)
    floor_ok = vlen >= _VERDICT_MIN_CHARS
    ceil_ok = vlen <= _VERDICT_MAX_CHARS
    lean_ok = " lean" not in verdict.lower()
    ok = floor_ok and ceil_ok and lean_ok
    if not ok:
        all_pass = False
    results.append((label, verdict, vlen, floor_ok, ceil_ok, lean_ok, ok))

    status = "PASS" if ok else "FAIL"
    floor_s = "PASS" if floor_ok else f"FAIL({vlen}<{_VERDICT_MIN_CHARS})"
    ceil_s = "PASS" if ceil_ok else f"FAIL({vlen}>{_VERDICT_MAX_CHARS})"
    lean_s = "PASS" if lean_ok else "FAIL(' lean')"
    print(f"[{label:20s}] {vlen:3d}ch  Floor:{floor_s:<18s}  Ceil:{ceil_s:<18s}  Lean:{lean_s}  -> {status}")
    print(f"  action={action!r}")
    print(f"  Verdict: {verdict!r}")
    if not ok:
        print("  *** VIOLATION ***")
    print()

print("-" * 80)
n = len(results)
pf = sum(1 for _, _, _, f, _, _, _ in results if f)
pc = sum(1 for _, _, _, _, c, _, _ in results if c)
pl = sum(1 for _, _, _, _, _, l, _ in results if l)
pa = sum(1 for _, _, _, _, _, _, a in results if a)

print(f"Floor >=  {_VERDICT_MIN_CHARS}: {pf}/{n}")
print(f"Ceiling <= {_VERDICT_MAX_CHARS}: {pc}/{n}")
print(f"No ' lean':   {pl}/{n}")
print(f"All PASS:     {pa}/{n}")

final = "PASS" if all_pass else "FAIL"
print(f"\nUNIT TEST OVERALL: {final}")
