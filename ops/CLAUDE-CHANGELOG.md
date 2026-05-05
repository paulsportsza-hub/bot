# CLAUDE.md — Changelog & Lock History

*Historical record of Standing Order changes, version bumps, and major doc-system events. Moved here from CLAUDE.md header on 5 May 2026 (`AUDIT-DOC-SYSTEM-CLEANUP-2026-05-05`) to keep CLAUDE.md within the SO #33 15K hard limit. Latest first.*

---

## 5 May 2026 — `AUDIT-DOC-SYSTEM-CLEANUP-2026-05-05` (AUDITOR Cowork)

System-wide doc + memory cleanup:

- Memory: 154 → ~95 files. 50+ superseded entries archived to `memory/archive/`. MEMORY.md compressed 30K → 14K.
- Cowork canonical: archived stale `DATA/`, `DEVELOPMENT/`, `audits/`, `agents/`, 8 stale briefs, 17 pre-launch content drafts, 6 applied .cowork-handoff scripts. Top-level dirs cleaned.
- CLAUDE.md: changelog header extracted to this file. Standing Orders verbose how-to-apply trimmed (kept rule + brief why; full detail in originating memory files / DEV-STANDARDS).
- New SOs added today: none. Existing SOs anchor the new dispatch infrastructure work landed earlier today (FIX-BADGE-DONE-IS-DONE-01, FIX-AGENT-AUTO-PERMISSIONS-01, FIX-BYPASS-PERMISSIONS-ACCEPT-01-ROLLBACK, FIX-ENQUEUE-CLEAN-STALE-ON-REQUEUE-01, FIX-DBLOCK-RUNTIME-HOT-PATHS-01).

## 4 May 2026 — `BUILD-DEV-STANDARDS-V45-REVIEW-GATE-NARROW-01` (Sonnet - AUDITOR)

Codex Review Gate v4.4 → v4.5. After `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01` burned the full 5h window on stacked Opus Max + mandatory adversarial review:

- `/codex:adversarial-review` is now DISCRETIONARY (opt-in via brief AC, not auto-fired).
- Mandatory adversarial triggers narrowed 6 → 3: money/payments, auth/settlement, non-rollback-safe migrations.
- Cost rule added: when executor = Opus Max Effort, default review = standard `/codex:review` unless adversarial explicitly justified.

## 3 May 2026 — `BUILD-DEV-STANDARDS-V4.4-REVIEW-GATE-01` (Opus Max Effort - AUDITOR)

- Added SO #45 Codex Review Gate. DEV-STANDARDS → v4.4.
- Codex XHigh + Codex High RETIRED as executors. Codex pivots to universal reviewer via `/codex:*`.
- Active agent set narrowed from 16 to 8: `{Opus Max Effort | Sonnet} - {LEAD | AUDITOR | COO | NARRATIVE}`.

## 2 May 2026 PM — Model Routing v1 LOCKED

Canonical: [Notion](https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08) · mirror: [`ops/MODEL-ROUTING.md`](ops/MODEL-ROUTING.md).

- Sonnet default (70-80% of execution), Codex High mechanical, Opus Max Effort judgement, Codex XHigh hard code root-cause.
- SO #44 rewritten as Routing v1 binding rule. SO #43 updated for new agent taxonomy.
- 16 canonical Agent options on Briefs DB + Pipeline DS.
- Supersedes Pure Claude Ecosystem v4.2 + Codex 5.5 Cutover.

## 25 April 2026 — SO #41 added (Approval Binds Commit)

A Cowork lead reviewing a report with code/data changes MUST verify the commit landed + pushed before closing the wave. Triggered by FIX-CLV-DEDUP-WRITE-01 (24 Apr) — Sonnet-LEAD reported Complete with passing tests but the commit never landed; the work lived only in the working tree.

## 23 April 2026 — Narrative Wiring Bible v1 LOCKED

Canonical at Notion `34bd9048-d73c-81f8-af8a-e3bfb540cc0f` · server mirror `/home/paulsportsza/bot/ops/NARRATIVE-WIRING-BIBLE.md`. Mandatory pre-read for any narrative/verdict/pregen work.

## 24 April 2026 — `FIX-EDGE-FIXTURE-BLACKLIST-01` LOCKED

`scrapers/edge/fixture_blacklist.py` gates test_cricket + all women's sport from edge generation.

## 22 April 2026 — SO #40 added (KICKOFF-SOURCE-1)

Every `broadcast_schedule` SELECT that drives a user-facing kickoff time / alert window / sort key over match start time MUST include `source = 'supersport_scraper'` in WHERE.

## 20 April 2026 — Surface & Funnel Model v5 LOCKED

Canonical on [Notion](https://www.notion.so/349d9048d73c81d79572e3b306c8df11) (source of truth), mirrored at [`ops/SURFACE-FUNNEL-MODEL.md`](ops/SURFACE-FUNNEL-MODEL.md). Superbru DECOMMISSIONED. SO #39 (30-min freshness rule) candidate pending freshness audit.

## 19 April 2026 — SO #38 added (Visual QA sub-agent)

Mandatory separate sub-agent for any user-facing surface change. Telethon for Telegram, Playwright for web. Producing agent cannot self-certify.

## 17 April 2026 — `CLAUDE-MD-SO-SPLIT-01` Tier 1 + Holy Trinity formalised

- 36 SOs → 11 universal in CLAUDE.md + 25 moved to domain modules (original numbers preserved).
- Holy Trinity locked: AUDITOR / LEAD / COO. AUDITOR Lane B formalised (Information Architecture & Dispatch System).
- ME-Core P5 (Marketing & Acquisition) added.
- Sonnet-as-Cowork-default locked.

## Earlier (March – mid-April 2026)

Earlier locks include SO #1-#36 set across Mar-Apr 2026 (`/codex:review` plugin install, Notion canonical reference structure, agent-report filing protocol, role split into Holy Trinity, AUDITOR Lane B), the original Pure Claude Ecosystem locks, and the Hetzner migration. See `archive/` and Notion Project Memory for full history.

---

*Append new lock events here when a Standing Order changes or a major version bump lands. Latest first. Keep entries terse — link out to briefs/Notion pages for detail.*
