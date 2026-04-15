# Banned Verdict Templates

## B20 — Named coach not in fixture metadata (LOCKED — INV-VERDICT-COACH-FABRICATION-01)

**Rule**: Any verdict that names a manager, coach, or head coach whose name
does NOT appear in `evidence_pack.home_manager` or `evidence_pack.away_manager`
MUST be rejected.

**Origin**: Brentford v Manchester United Gold candidate (15 April 2026).
Generated "Amorim's United are struggling at Old Trafford this season..."
Amorim was NOT the current United manager — hallucinated from training data
(model cutoff ~mid-2025).

**Detection patterns**:
- Possessive: `[A-Z][a-z]{2,}'s side/men/team/squad/approach/...`
- Under: `under [A-Z][a-z]{2,}`

**Examples of REJECTED verdicts**:
- "Amorim's United are struggling..." (Amorim not in evidence_pack)
- "Under ten Hag, this side has..." (ten Hag not in evidence_pack)
- "Klopp's Reds have the momentum..." (Klopp not in evidence_pack)
- "Conte's system is built to..." (Conte not in evidence_pack)
- "Mourinho's pragmatism will..." (Mourinho not in evidence_pack)
- "Pochettino's side have turned a corner..." (Pochettino not in evidence_pack)

**Examples of ACCEPTED verdicts**:
- "Arteta's Gunners are in strong form..." (Arteta IS in evidence_pack.home_manager)
- "United are struggling at home..." (no manager named — acceptable)
- "The Blues have won four from five..." (no manager named — acceptable)

**Enforcement**:
- `validate_manager_names()` in `narrative_spec.py` — hard gate
- Wired into `min_verdict_quality()` via `evidence_pack` parameter
- Also checked directly after `_generate_verdict_constrained()` output
