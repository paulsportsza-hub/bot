# QA-RUBRIC-E2E — Operations Runbook

**Version:** v4.0 (INV-QA-RUBRIC-01, 2026-04-23)
**Wave:** BUILD-QA-RUBRIC-RUNNER-01
**Inherits:** `ops/QA-RUBRIC-CARDS-v3.md` — Section 1 anti-fluff rules and Section 8 vision model
**Launch gate:** Three consecutive PASS verdicts on three separate days required before release.

## When to run

- Before every production release
- After any wave that touches: bot.py, tier_gate.py, narrative_spec.py, payment flows
- After any GATE_MATRIX change
- Weekly validation pass (scheduled)

## Pre-run checklist

1. Bot running on canonical path: `ps aux | grep bot.py` → must show `/home/paulsportsza/bot/bot.py`
2. Telethon session valid: `data/telethon_session.string` exists and non-empty
3. STITCH_MOCK_MODE will be forced True by runner config
4. ANTHROPIC_API_KEY set (for OCR)

## Run

```bash
cd /home/paulsportsza/bot
source .venv/bin/activate

# Preflight check (no bot interaction)
python -m tests.qa.rubric_runner --dry-run

# Full run
python -m tests.qa.rubric_runner --personas P1,P2,P3,P4 \
  --output /home/paulsportsza/reports/rubric_runner/rubric-$(date +%Y%m%d-%H%M).md
```

## Exit code interpretation

| Exit | Meaning | Action |
|------|---------|--------|
| 0    | PASS or CONDITIONAL PASS | Push to Notion, proceed |
| 1    | FAIL or QA-INVALID | Block release, investigate defects |

## Interpreting FAIL verdicts

| Verdict | Root cause | Action |
|---------|-----------|--------|
| FAIL (SEV-1) | Tier leak, payment dead, onboarding blocked | Immediate P0 fix |
| FAIL (J5 < 5.0) | GATE_MATRIX access level wrong | Check tier_gate.py |
| FAIL (K3 < 80%) | Not enough gate cells tested | Add personas or extend P4 |
| FAIL (payment flow) | P1 payment E2E not executed | Check /subscribe → Gold → email → Stitch mock |

## Escalation

- Any SEV-1 defect: escalate to Controller immediately
- J5 < 5.0 on Bronze or Gold: block release — tier leak risk
- K3 < 80%: investigate which cells are missing and extend scripts

## Notion push

After every run (pass or fail), push report to Notion:

```bash
python3 ~/scripts/push_report.py \
  --agent Sonnet \
  --wave QA-RUBRIC-$(date +%Y%m%d) \
  /home/paulsportsza/reports/rubric_runner/rubric-*.md
```

## Contract test

Run the kickoff source contract before any rubric run:

```bash
bash scripts/qa_safe.sh tests/contracts/test_kickoff_supersport_only.py
```

This ensures all broadcast_schedule queries across the repo use `source='supersport_scraper'`.

## OCR

The runner uses `OCR_PROMPT_V2` (in `tests/qa/ocr_prompt.py`).
V1 `OCR_PROMPT` is immutable — never edit it.

If `ANTHROPIC_API_KEY` is not set, OCR steps are skipped with a warning.
C3/C4 card scoring will be reduced but the run continues.

## SuperSport Additions (LOCKED — 23 Apr 2026)

### Addition 1 — SuperSport Logo Visual Check (C3 assertion)

On any card where a broadcast channel is present, OCR (via `OCR_PROMPT_V2`) checks:
- `supersport_logo_present` (bool) — is the SuperSport logo visible?
- `supersport_logo_colour` (str) — what colour is the logo?

Assertion in `tests/qa/rubric_runner/assertions/card.py::assert_supersport_logo_red()`:
- **PASS** only if `present=True AND colour contains "red"`
- Missing or non-red logo → C3 deduction **-1.0** + SEV-3
- Cards with no broadcast channel: field is `null`, assertion is skipped

Implementation: `assertions/card.py`, `scoring/ocr_schema.py::CardOCRV2`

### Addition 2 — Kickoff Time Cross-Check vs SuperSport Scraper (C1 assertion, SO #40)

`verify_kickoff_time(match_id, rendered_kickoff_str)` in `db_verify.py`:

1. Query `broadcast_schedule WHERE source = 'supersport_scraper' AND match_id = ?`
2. If row exists: rendered time must match `start_time` in SAST (ZoneInfo Africa/Johannesburg), tolerance ±1 minute
3. If no supersport_scraper row: fall through to canonical chain:
   `sportmonks_fixtures → rugby_fixtures/mma_fixtures → commence_time → match_key date suffix`
4. **NEVER** add an any-source `broadcast_schedule` fallback (SO #40)

Mismatch → C1 deduction **-2.0** + SEV-2

Before every rubric run, verify SO #40 compliance:
```bash
bash scripts/qa_safe.sh tests/contracts/test_kickoff_supersport_only.py
```

## Maintenance

- Update `TEAM_ABBREVIATIONS` in `config.py` when new PSL/EPL teams are added
- Update persona step counts (`STEPS_TOTAL`) when onboarding flow changes
- Update `PERSONA_GATE_CELLS` in `gate_matrix.py` when tier access levels change
- Update SLA targets in `surfaces.py` when new surfaces are added
- Update `ops/QA-RUBRIC-CARDS-v3.md` (not the original `QA-RUBRIC-CARDS.md`) for card-level rubric changes
