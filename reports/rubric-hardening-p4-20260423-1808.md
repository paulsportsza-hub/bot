# QA Run Report — BUILD-QA-RUBRIC-RUNNER-01

## Run metadata

- **Run timestamp**: 2026-04-23 18:09 SAST
- **Personas**: P4
- **STITCH_MOCK_MODE**: True
- **Payment flow executed E2E**: False
- **Composite score**: 5.44/10
- **Verdict**: FAIL (J5 < 5.0)

## Per-persona results

### P4 — Bronze

**Persona composite: 7.8** = 0.5·L1(9.5) + 0.5·L2(6.2)

Steps: 6/6

#### L1 Card Quality

[███████████████████░] 9.5/10

- **C1** (3.0w): 10.0/10 — OK
- **C2** (1.5w): 10.0/10 — OK
- **C3** (2.0w): 10.0/10 — OK
- **C4** (1.5w): 10.0/10 — OK
- **C5** (0.5w): 10.0/10 — OK
- **C6** (0.5w): 0.0/10 — Empty state S13 returned empty text — SEV-2; Empty state S13 returned empty text — SEV-2
- **C7** (1.0w): 10.0/10 — OK

#### L2 Journey Integrity

[████████████░░░░░░░░] 6.2/10

- **J1** (30%): 10.0/10 — completed 6/6
- **J2** (20%): 8.0/10 — Only 2 S0 steps captured — onboarding may be incomplete
- **J3** (20%): 3.0/10 — S0: 4.4s > SLA 3.0s; S0: 4.9s > SLA 3.0s; S13: 22.9s > SLA 4.0s; S13: 5.0s > SLA 4.0s; S7: 8.1s > SLA 4.0s; S6: 9.8s > SLA 4.0s; 1 responses exceeded 3× SLA
- **J4** (15%): 6.5/10 — 2 SEV-2 defects (data mismatch / broken button); 1 SEV-3 defects (visual / non-critical)
- **J5** (15%): 0.0/10 — No GATE_MATRIX cells tested

#### Defects

- **SEV-2** (step 3): My Matches returned empty text — C6 empty state quality fail
- **SEV-2** (step 4): Top Edge Picks returned empty text — C6 quality fail
- **SEV-3** (step 5): Bot did not respond to freetext input

## L3 Coverage

[██░░░░░░░░░░░░░░░░░░] 1.0/10

- **K1** (40%): 0.0/10 — Missing surfaces: ['S0', 'S1', 'S10', 'S11', 'S2', 'S3', 'S4', 'S6', 'S7']; Covered 0/9 required surfaces
- **K2** (30%): 3.3/10 — Sports not covered: ['cricket', 'rugby']
- **K3** (30%): 0.0/10 — Tested 0/16 GATE_MATRIX cells (0%); HARD OVERRIDE: K3=0% < 80% threshold

- GATE_MATRIX cells tested: 0/16
- K3 threshold passed (≥80%): NO — HARD OVERRIDE

## Composite Score

```
0.65 × mean(persona_composite) + 0.35 × L3
0.65 × 7.84 + 0.35 × 1.00 = 5.44
```

**5.44/10 — FAIL (J5 < 5.0)**

## Defects

Total: 3 (0 SEV-1, 2 SEV-2, 1 SEV-3)

### SEV-2
- [P4 step 3] My Matches returned empty text — C6 empty state quality fail
- [P4 step 4] Top Edge Picks returned empty text — C6 quality fail

### SEV-3
- [P4 step 5] Bot did not respond to freetext input

## CLAUDE.md Updates

None required from this QA run.
