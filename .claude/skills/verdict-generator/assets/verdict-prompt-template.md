# Verdict Prompt Template — Manager/Coach Zero-Tolerance Rule

## INV-VERDICT-COACH-FABRICATION-01 (15 April 2026)

### ZERO-TOLERANCE MANAGER RULE (LOCKED)

NEVER name a manager, coach, or head coach unless their name appears verbatim
in `evidence_pack.home_manager` or `evidence_pack.away_manager`.

If the field is null or missing, omit the name entirely and refer to the side
by team name only.

This is a zero-tolerance rule. Violations are hard-rejected by
`validate_manager_names()` in `narrative_spec.py`.

### Origin incident

A Gold candidate for Brentford v Manchester United generated:
> "Amorim's United are struggling at Old Trafford this season..."

Amorim was NOT the current United manager. The model hallucinated from
training data (cutoff ~mid-2025). Paul caught it in rating — it never
published.

### Enforcement layers

1. **Evidence feed**: `pregenerate_narratives.py` passes `home_manager` and
   `away_manager` from `evidence_pack.espn_context` into the `_allowed` dict.
2. **Prompt rule**: The Sonnet system prompt includes a ZERO-TOLERANCE RULE
   paragraph immediately after the `manager_home / manager_away` field
   description.
3. **Validator**: `validate_manager_names()` in `narrative_spec.py` detects
   possessive manager patterns (`Name's side`) and `under Name` patterns,
   cross-references against evidence_pack, and hard-fails on mismatch.
4. **Quality gate**: `min_verdict_quality()` calls `validate_manager_names()`
   when `evidence_pack` is provided.
