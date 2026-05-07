# Control Tower (LOCKED 7 May 2026)

**Authoritative spec:** [`HANDOFFS/mzansiedge_daily_maintenance_control_tower.md`](../HANDOFFS/mzansiedge_daily_maintenance_control_tower.md) (also at `~/Documents/MzansiEdge/HANDOFFS/` on the Mac side)

**Bound by:** SO #51

**Operating model (binding):**
1. **Dashboard** — passive visibility
2. **Cowork scheduled tasks** (`control-tower-1` through `control-tower-7`) — active diagnosis every morning
3. **Notion** — system memory + fix briefs (Pipeline DS `7da2d5d2-0e74-429e-9190-6a54d7bbcd23`, Briefs DB `8aa573c8-f21d-4e97-909b-b11b34892a76`)
4. **Telegram** — exception-only (P0/P1 only)
5. **Paul** — receives ONE digest at 08:10 SAST (or zero if all GREEN)

## Daily morning schedule (SAST)

| Time | Task | Cowork ID | Notion Wave |
|---:|---|---|---|
| 06:00 | System Health Gate | `control-tower-1-system-health-gate` | `CONTROL-TOWER-DAILY-HEALTH-GATE` |
| 06:20 | Bot Runtime Canary | `control-tower-2-bot-runtime-canary` | `CONTROL-TOWER-RUNTIME-CANARY` |
| 06:45 | Algorithm & Edge Quality Audit | `control-tower-3-edge-quality-audit` | `CONTROL-TOWER-EDGE-QUALITY-AUDIT` |
| 07:10 | Narrative Verdict QA | `control-tower-4-narrative-verdict-qa` | `CONTROL-TOWER-NARRATIVE-VERDICT-QA` |
| 07:30 | Social Automation Safety | `control-tower-5-social-automation-safety` | `CONTROL-TOWER-SOCIAL-SAFETY` |
| 07:50 | SEO Exception Check | `control-tower-6-seo-exception-check` | `CONTROL-TOWER-SEO-EXCEPTION` |
| 08:10 | Daily Control Digest | `control-tower-7-daily-control-digest` | `CONTROL-TOWER-DAILY-DIGEST` |

## Severity binding (SO #51)

- **P0** — Paul notified immediately. Product broken / actively unsafe.
- **P1** — Paul sees in digest, or immediately if time-sensitive.
- **P2** — Notion fix brief, NO Paul alert.
- **P3** — Backlog or auto-fix, NO Paul alert.

Any new monitoring / alerter must classify findings into P0-P3 BEFORE deciding whether to surface to Paul.

## Decommissioned by SO #51

- Cowork task `mzansiedge-daily-health-routine` — disabled 7 May 2026, superseded by Task 1
- Cowork task `narrative-quality-arbiter` — disabled 7 May 2026, superseded by Task 4
- Cowork task `health-monitor-fix` — retired (was already disabled, kept stub)
- Cron `regression_arbiter.py` (09:00 SAST) — disabled in crontab 7 May 2026, comment-marked
- Cron `arbiter_qa.py` (09:30 SAST) — disabled in crontab 7 May 2026, comment-marked

## Adding a new monitor / alerter

Before adding any new check that posts to Telegram or files reports:
1. Read [HANDOFFS/mzansiedge_daily_maintenance_control_tower.md](../HANDOFFS/mzansiedge_daily_maintenance_control_tower.md) §17 ("What To Remove or Demote")
2. Confirm the check classifies findings P0-P3
3. Confirm only P0/P1 surfaces to Paul (Telegram or Cowork digest)
4. Confirm P2/P3 file Notion fix briefs without alerting
5. Add a row to the schedule table above

If the check duplicates one of the existing 7 control-tower tasks, extend the existing task instead.
