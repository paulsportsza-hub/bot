# QA Rubric Runner — BUILD-QA-RUBRIC-RUNNER-01

4-persona end-to-end QA rubric for the MzansiEdge Telegram bot.

## Quick start

```bash
cd /home/paulsportsza/bot

# Preflight only (no Telegram connection)
python -m tests.qa.rubric_runner --dry-run

# Run all 4 personas
python -m tests.qa.rubric_runner --personas P1,P2,P3,P4

# Run specific personas
python -m tests.qa.rubric_runner --personas P1,P2

# Custom output path
python -m tests.qa.rubric_runner --output /home/paulsportsza/reports/qa-run-$(date +%Y%m%d-%H%M).md

# Verbose logging
python -m tests.qa.rubric_runner --dry-run --verbose
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | PASS or CONDITIONAL PASS |
| 1    | FAIL, QA-INVALID, or preflight failure |

## Scoring model

### L1 — Card Quality (50% of persona composite)

| Dim | Weight | Description |
|-----|--------|-------------|
| C1  | 3.0    | Data Accuracy — odds, kickoff, team names |
| C2  | 1.5    | Typography & Layout |
| C3  | 2.0    | Visual Correctness — photo cards, SuperSport logo |
| C4  | 1.5    | Tier Badge Correctness |
| C5  | 0.5    | CTA Correctness |
| C6  | 0.5    | Empty State Quality |
| C7  | 1.0    | Narrative Quality |

### L2 — Journey Integrity (50% of persona composite)

| Dim | Weight | Description |
|-----|--------|-------------|
| J1  | 30%    | Journey Completion Rate |
| J2  | 20%    | Onboarding Quality |
| J3  | 20%    | Response Latency (SLA) |
| J4  | 15%    | Error Recovery |
| J5  | 15%    | Tier-Gating Correctness |

### L3 — Coverage (35% of run composite)

| Dim | Weight | Description |
|-----|--------|-------------|
| K1  | 40%    | Surface Coverage |
| K2  | 30%    | Cross-Sport Parity |
| K3  | 30%    | Cross-Tier Parity |

### Run composite

```
Run composite = 0.65 × mean(persona_composite) + 0.35 × L3
Persona composite = 0.5 × L1 + 0.5 × L2
```

### Thresholds

| Score      | Verdict           |
|------------|-------------------|
| ≥ 9.0      | PASS              |
| 8.0 – 8.9  | CONDITIONAL PASS  |
| < 8.0      | FAIL              |
| Any SEV-1  | FAIL (override)   |

### Hard overrides (LOCKED)

- Any SEV-1 defect → FAIL
- J5 < 5.0 on any persona → FAIL
- K3 < 80% testable cells → FAIL
- Payment flow not executed E2E when STITCH_MOCK_MODE=True → FAIL
- Webhook sig verify fail → SEV-1 FAIL
- `db.set_user_tier()` used → QA-INVALID

## SEV levels

| Level | Examples |
|-------|---------|
| SEV-1 | Tier leak, payment link dead, onboarding blocked, silent 404 |
| SEV-2 | Wrong odds/kickoff, broken button, data mismatch |
| SEV-3 | Visual glitch, non-critical text error, logo missing |

## Personas

| ID | Tier    | Steps | Sports |
|----|---------|-------|--------|
| P1 | Bronze  | 30    | Soccer only |
| P2 | Gold    | 15    | Soccer + Rugby + Cricket |
| P3 | Diamond | 16    | All sports |
| P4 | (Edge)  | 6     | Empty states, freetext |

## File structure

```
tests/qa/rubric_runner/
  __init__.py          — package marker
  __main__.py          — module entry point
  config.py            — runner configuration
  surfaces.py          — surface taxonomy (S0–S17)
  gate_matrix.py       — GATE_MATRIX definitions
  preflight.py         — pre-run checks (PF-1 through PF-6)
  personas.py          — persona definitions (P1–P4)
  runner.py            — main CLI
  ocr_bridge.py        — V1/V2 OCR switch
  db_verify.py         — kickoff time cross-check (SO #40)
  report.py            — markdown + JSON report generator
  scripts/
    base.py            — PersonaRunner (Telethon wrapper)
    p1_bronze_soccer.py
    p2_gold_multi.py
    p3_diamond_multi.py
    p4_edge_cases.py
  assertions/
    card.py            — extended card assertions (V1 + V2 + Addition 1)
  scoring/
    card.py            — L1 scoring (C1–C7)
    journey.py         — L2 scoring (J1–J5)
    coverage.py        — L3 scoring (K1–K3)
    ocr_schema.py      — CardOCRV2 dataclass
```

## OCR versions

The runner uses `OCR_PROMPT_V2` (added to `tests/qa/ocr_prompt.py`).
V1 `OCR_PROMPT` is unchanged — ground-truth tests continue to use it.
Switch: `config.USE_OCR_V2 = True` (default).

## Kickoff verification (SO #40)

`db_verify.verify_kickoff_time()` cross-checks rendered kickoff times:

1. Query `broadcast_schedule WHERE source = 'supersport_scraper'` FIRST
2. If row found: compare times (±1 minute tolerance)
3. If no row: fall through to sportmonks_fixtures → match_key date suffix
4. NEVER use any-source broadcast_schedule query

Contract test: `tests/contracts/test_kickoff_supersport_only.py`

## Reports

- Markdown: `/home/paulsportsza/reports/rubric_runner/rubric-YYYYMMDD-HHMM.md`
- JSON sidecar: same path with `.json` extension
- Screenshots: `/home/paulsportsza/reports/rubric_runner/screenshots/`

## Required env vars

```
TELEGRAM_API_ID          # Telethon API ID
TELEGRAM_API_HASH        # Telethon API hash
TELEGRAM_E2E_TEST_CHAT_ID  # Telegram user ID (admin)
ANTHROPIC_API_KEY        # For OCR (warn if missing, skip OCR steps)
```
