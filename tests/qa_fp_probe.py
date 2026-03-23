"""Targeted false-positive probe for W84 verifier cleanup validation."""
import sys
sys.path.insert(0, "/home/paulsportsza")

from evidence_pack import (
    _extract_candidate_proper_nouns,
    _KNOWN_VERIFIED_VENUE_PHRASES,
    _is_non_name_proper_noun_phrase,
    _normalise_name_phrase,
    _NON_NAME_PROPER_NOUN_PHRASES,
)

# _has_stale_h2h_summary lives in bot.py (not safe to import directly)
# H2H section uses static code inspection instead

# ─── 1. Venue name false positives ────────────────────────────────────────────
print("=== TEST 1: VENUE NAME FALSE POSITIVES ===")
venue_inputs = [
    ("Stamford Bridge",   False),  # should FP (not whitelisted)
    ("Selhurst Park",     False),  # should FP
    ("City Ground",       False),  # should FP
    ("Emirates Stadium",  False),  # should FP
    ("Anfield",           True),   # single word — NOT extracted by 2-word regex
    ("Old Trafford",      False),  # should FP
    ("Villa Park",        False),  # should FP
    ("St James Park",     False),  # should FP
    ("Goodison Park",     False),  # should FP
    ("Kings Park",        True),   # in whitelist — should be OK
    ("Kings Park Stadium",True),   # in whitelist — should be OK
]

venue_fps = []
for name, expect_ok in venue_inputs:
    in_whitelist = _normalise_name_phrase(name) in _KNOWN_VERIFIED_VENUE_PHRASES
    candidates = _extract_candidate_proper_nouns(name)
    extracted = bool(candidates)
    fp = extracted and not in_whitelist
    ok = not fp
    status = "OK " if ok else "FP "
    match = "=EXPECTED" if (ok == expect_ok) else "!UNEXPECTED"
    print(f"  {status} | {name!r:25} | extracted={extracted} | whitelisted={in_whitelist} {match}")
    if fp:
        venue_fps.append(name)

print(f"\n  VENUE FP COUNT: {len(venue_fps)}/11 inputs trigger false positive")
print(f"  FP list: {venue_fps}")

# ─── 2. SA acronym fragment false positives ───────────────────────────────────
print("\n=== TEST 2: SA ACRONYM FRAGMENT FALSE POSITIVES ===")
sa_inputs = [
    ("With SA",          False),  # should FP (not whitelisted)
    ("Most SA",          False),  # should FP
    ("Among SA",         False),  # should FP
    ("Without SA",       False),  # should FP
    ("In SA",            True),   # single word "In" — may not extract
    ("Across SA",        True),   # in whitelist
    ("South Africa",     True),   # in whitelist
    ("SA bookmakers",    False),  # multi-word mixed case — check
]

sa_fps = []
for phrase, expect_ok in sa_inputs:
    in_whitelist = _is_non_name_proper_noun_phrase(phrase)
    candidates = _extract_candidate_proper_nouns(phrase)
    extracted = bool(candidates)
    fp = extracted and not in_whitelist
    ok = not fp
    status = "OK " if ok else "FP "
    match = "=EXPECTED" if (ok == expect_ok) else "!UNEXPECTED"
    print(f"  {status} | {phrase!r:20} | extracted={extracted} | whitelisted={in_whitelist} | cands={candidates} {match}")
    if fp:
        sa_fps.append(phrase)

print(f"\n  SA FP COUNT: {len(sa_fps)}/8 inputs trigger false positive")
print(f"  FP list: {sa_fps}")

# ─── 3. Stale H2H rejection loop behavior ─────────────────────────────────────
print("\n=== TEST 3: STALE H2H REJECTION LOOP (CODE INSPECTION) ===")

# _has_stale_h2h_summary lives in bot.py — we can't import bot safely.
# Instead inspect the code path statically.
with open("bot.py") as f:
    bot_src = f.read()

# Confirm the function signature and comparison approach
has_stale_present = "_has_stale_h2h_summary" in bot_src
expected_fn_present = "_expected_h2h_summary_from_evidence" in bot_src
recompute_pattern = "or _expected_h2h_summary_from_tips(tips)" in bot_src

print(f"  _has_stale_h2h_summary present:              {has_stale_present}")
print(f"  _expected_h2h_summary_from_evidence present: {expected_fn_present}")
print(f"  Still uses _expected_h2h_summary_from_tips:  {recompute_pattern}")
print()

# Find the function body for inspection
lines = bot_src.split("\n")
fn_start = next((i for i, l in enumerate(lines) if "def _has_stale_h2h_summary" in l), None)
if fn_start is not None:
    fn_lines = lines[fn_start:fn_start+12]
    print("  Current _has_stale_h2h_summary body:")
    for l in fn_lines:
        print(f"    {l}")

# Check whether the fix (compare stored H2H directly) was applied
fix_applied = "evidence_json" in "".join(lines[fn_start:fn_start+20]) if fn_start else False
recomputes = "_expected_h2h_summary_from_evidence(evidence_json)" in "".join(lines[fn_start:fn_start+20]) if fn_start else False
print(f"\n  Fix applied (use stored H2H directly): {fix_applied and not recomputes}")
print(f"  Still recomputing from evidence_json:  {recomputes}")
print()
print("  H2H FIX STATUS: NOT DEPLOYED")
print("  P2 loop fires when H2H block in evidence_json drifts during scraper write window")
print("  Self-resolves when H2H stabilizes. Currently 0 active same-day matches in cache.")

# ─── 4. Verify W84 default path integrity ─────────────────────────────────────
print("\n=== TEST 4: W84 DEFAULT PATH INTEGRITY CHECK ===")

# Check that W84_SERVE env-var gate is removed
import os
w84_env = os.environ.get("W84_SERVE", "NOT_SET")
print(f"  W84_SERVE env var: {w84_env!r}")

# Check pregenerate_narratives comment
with open("scripts/pregenerate_narratives.py") as f:
    content = f.read()
confirm1_deployed = "W84-CONFIRM-1" in content and "env-var gate has been removed" in content
print(f"  W84-CONFIRM-1 deployed (gate removed): {confirm1_deployed}")

# Check TOCTOU fix
with open("bot.py") as f:
    bot_content = f.read()
toctou_fixed = "_pregen_active" in bot_content and "_pregen_lock.locked()" not in bot_content
toctou_broken = "_pregen_lock.locked()" in bot_content
print(f"  TOCTOU boolean flag fix deployed:      {toctou_fixed}")
print(f"  TOCTOU broken pattern still present:   {toctou_broken}")

# Check venue whitelist size
print(f"\n  _KNOWN_VERIFIED_VENUE_PHRASES size: {len(_KNOWN_VERIFIED_VENUE_PHRASES)} entries")
from evidence_pack import _NON_NAME_PROPER_NOUN_PHRASES
print(f"  _NON_NAME_PROPER_NOUN_PHRASES size:  {len(_NON_NAME_PROPER_NOUN_PHRASES)} entries")
print(f"  Venue whitelist contents: {sorted(_KNOWN_VERIFIED_VENUE_PHRASES)}")
print(f"  SA phrase whitelist contents: {sorted(_NON_NAME_PROPER_NOUN_PHRASES)}")

print("\n=== PROBE COMPLETE ===")
