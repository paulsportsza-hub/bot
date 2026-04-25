# Dev Team Briefing Standards (LOCKED — 6 March 2026)

> **Source of truth for agent briefing, delegation, and QA standards.**
> Referenced from CLAUDE.md.

*Last updated: 17 April 2026 PM by AUDITOR (CLAUDE-MD-SO-SPLIT-01 Tier 1 — absorbed 6 SOs from CLAUDE.md: #15, #18, #19, #27 [reworded], #33, #36.)*

---

## Standing Orders (moved from CLAUDE.md — 17 April 2026 PM)

*Original SO numbers preserved for historical reference. All agents dispatching, executing, or reporting on dev/QA work must read and re-read these before every response.*

- **[SO #15]** Workers return compressed state only. Every worker return must be compressed into: task, outcome, key findings, decision needed, next action, and Notion/status changes. COO rejects raw sprawl.
- **[SO #18]** Every state change = Notion update in the same response. When ANY item's status changes, the agent MUST update the corresponding Notion record in the same response. No state change lives only in chat.
- **[SO #19]** Coding agents should use Sentry MCP during investigations, builds, and QA. Sentry data is direct production evidence. Scheduled tasks and COO do NOT check Sentry — that is handled by the `health-monitor-fix` scheduled task (runs every 12h).
- **[SO #27 — reworded 17 Apr 2026 PM]** LEAD personally reviews every QA-BASELINE report before treating it as valid. AUDITOR ratifies algo-truth verdicts. QA agent verdicts are never accepted at face value. *(Pre-split wording named COO as reviewer; LEAD is now the correct owner under the Holy Trinity.)*
- **[SO #33]** Notion page hygiene — hard character limits. Task Hub: 2,000 chars max. CLAUDE.md: 15,000 chars max. Completed items are DELETED, not checked off. Ops sweep results go to dated child pages under Archive, never inline. Daily content pages are created under Archive, not as direct Task Hub children. Every agent-facing page starts with a Page Contract callout stating its rules. The Today section is replaced daily, never appended. Violation of these limits is a P0 workflow issue — fix before any other work. (LOCKED 10 Apr 2026 — after 90K-char Task Hub crash incident.)
- **[SO #36]** Every new automated component MUST be wired into the monitoring dashboard in the same brief that ships it. (LOCKED 15 Apr 2026.) Applies to: scrapers, cron jobs, scheduled tasks, data feeds, publishers, model generators, validators, ingest pipelines, ANY new automated process. Mandatory wiring per component: (a) health endpoint exposing last-run timestamp, success/failure, item count; (b) freshness SLA (max-age threshold beyond which dashboard flags red); (c) failure alert routed to EdgeOps `-1003877525865` (NEVER public alerts channel); (d) named owner module in dashboard registry; (e) dashboard entry verified visible BEFORE the brief reports Complete. Every BUILD brief introducing an automated component MUST include "Dashboard integration" as a numbered scope item with the five sub-points above. Reports without dashboard verification fail acceptance — the brief reopens. Precedent: BUILD-TRANSFERMARKT-COACHES-SCRAPER-01.

---

**One problem = one brief.** No mega-briefs. No combined tasks.

1. One essential focus per brief
2. Agent name in every brief title: `{Agent} Brief — {Wave}: {Description}`
3. Every brief includes verification checklist
4. Every brief requires a Notion report (Agent Reports Pipeline: `7da2d5d2-0e74-429e-9190-6a54d7bbcd23`)
5. Dependency order respected
6. COO handover after every major wave — agents do NOT update CLAUDE.md directly
7. No orphaned TODOs — every "follow-up" gets a brief in the same session
8. **Agent marks brief as Done on completion.** When an agent finishes work and files its report to Notion, it MUST update the brief's Status to "✅ Done" and write completion notes in the page body. No brief stays in "🔄 In Progress" after the work is complete. COO verifies this on every worker return.

### Agent Report Filing Protocol (LOCKED — 6 April 2026)

**This is non-negotiable. Every agent must follow this exactly on task completion.**

**Step 1 — File report to Agent Reports Pipeline.**
- Database: `7da2d5d2-0e74-429e-9190-6a54d7bbcd23`
- Required properties: `Report` (title), `Agent`, `Wave`, `Status` = "New", `Date`, `Project` = "MzansiEdge"
- `Server File`: path to the markdown report on server (e.g. `file:///home/paulsportsza/reports/{agent}-{wave}-{date}.md`)
- Report body must include: Objective, Deliverables (files created/modified), Acceptance Criteria table (all ACs with ✅/❌), Implementation Details, Test Results (count + pass rate), Blocks Unblocked.

**Hard cap: 300 words per report (LOCKED 7 Apr 2026 — token optimisation).** No prose narratives. Structured key-value only. The Acceptance Criteria table is exempt from the count (it's tabular data). Implementation Details: max 10 bullets, one line each. Any "explanation" or "rationale" lives in the brief, not the report. If a report exceeds 300 words, COO rejects it and the agent resubmits a compressed version.

**Step 2 — Update the original brief page.**
- Set Status to `✅ Done`
- Set `Latest Compressed Summary` to a one-paragraph summary: what was built, key numbers (lines, tests, ACs), what it unblocks.
- Set `Decision Needed From Paul?` to `__YES__` or `__NO__` as appropriate.

**Step 3 — Save report markdown to server.**
- Path: `/home/paulsportsza/reports/{agent}-{wave}-{YYYYMMDD}-{HHMM}.md`
- Naming: lowercase agent name, wave ID, date-time. Example: `leaddev-IMG-W1-20260406-0942.md`

**Violations:** If COO finds a report missing from the pipeline, or a brief still showing "🔄 In Progress" after the agent has stopped, the agent's output is treated as incomplete. COO will not process the work until the filing protocol is satisfied.

9. **Mandatory investigation before every BUILD wave (LOCKED — 23 March 2026).** Every wave of BUILD fixes MUST be preceded by an Opus `--effort max` investigative brief. The investigation maps the architecture, identifies exact `file:function:line` targets for every defect, and produces structured fix specifications. COO reviews the investigation report before creating any BUILD briefs. If any defect lacks an exact code target, the investigation is incomplete. No BUILD briefs are dispatched until the investigation passes review. This prevents the R6 failure mode where 5/6 fixes landed on the wrong code path.

10. **Every brief includes a Challenge Rule (LOCKED — 1 April 2026).** The following instruction must appear verbatim in every brief: *"If you identify any issues with the approach described — architectural, logical, or implementation concerns — raise them clearly before proceeding. Do not proceed silently with a flawed approach."* Agents will not push back by default. The instruction must be present to unlock that behaviour.

11. **Every brief includes a Handoff Protocol (LOCKED — 1 April 2026).** The following must appear verbatim in every brief: *"If blocked, write a handoff document before stopping. Required fields: (1) current progress, (2) key decisions made and why, (3) files modified, (4) remaining work, (5) blockers with specifics, (6) critical context for resumption. A context dump without this structure is a protocol violation — stop and write the structured doc instead."*

12. **Devil's Advocate agent — activate at 8.0+ narrative score (LOCKED — 1 April 2026).** At sustained 8.0+ QA score, designate a second QA-class agent as an adversarial reviewer. Its sole role is to find failure modes in other agents' outputs — not to validate, but to probe. It runs AFTER standard QA and BEFORE any 5-clean-days clock advancement. It may NOT confirm a pass; it may only challenge, surface edge cases, or return "No defects found." If it finds something, that defect must be resolved before the underlying QA run is treated as clean. This directly addresses the semantic failure pattern (QA-18, QA-19) where a validating agent returns "successful garbage." A probing agent with explicit adversarial framing catches what a validating agent is structurally inclined to miss.

13. **Line-range file ops only — no full-file reads on large files (LOCKED — 7 April 2026).** No agent may `Read` any file >500 lines without an `offset`/`limit`. Use Grep to locate the relevant function/section first, then targeted Read with line ranges. All edits use `Edit`/`str_replace`, never `Write` (Write is for new files only — never use it to "rewrite" an existing file). `bot.py` is 23K+ lines: a single unranged read burns ~100K tokens and the agent's context budget. If a brief genuinely requires a full-file read, the brief must explicitly state "full-file read approved" with a one-line justification. Auditable in wave logs.

14. **One-fetch rule for briefs and Notion pages (LOCKED — 7 April 2026).** Each agent fetches its own brief page ONCE at task start, never re-fetches mid-task. If the agent loses the brief contents from context, that's a context-management failure, not a reason to re-fetch. Notion queries against databases use property filters (Status, Date, Owner) — never `notion-fetch` a full page when a property query suffices. Average Notion read target: <1,000 tokens. Full-page reads only when explicitly required.

15. **10-turn cap per session, fresh session per brief (LOCKED — 7 April 2026).** No agent session exceeds 10 turns. One brief = one session. If a task needs more than 10 turns, the agent MUST stop and write a structured handoff doc (per item 11) — never continue past the cap. Use `/clear` between discrete sub-tasks within a session if continuation is necessary. Each new brief starts a fresh session. **Exception:** INV-type briefs running Opus `--effort max` may extend up to 20 turns when the brief explicitly states "INV-extended turn budget approved." All other agent types are bound to the 10-turn cap.

**Mandatory delegation header:** TASK TYPE, PROBLEM CLARITY, RUNTIME DEPENDENCY, STAKES, PRIMARY AGENT, SECONDARY REVIEWER, WHY THIS ROUTING, VERIFICATION PLAN. Default ladder: Codex → Sonnet → Opus → Codex verify.

---

### Card QA OCR Block — mandatory in every card-touching brief (SO #38, LOCKED 22 Apr 2026)

Any brief that touches card rendering MUST embed the following block verbatim in its QA sub-agent instructions. The Telethon sub-agent runs this immediately after capturing the screenshot. Results go into the agent report as a table.

```python
# SO #38 — Card OCR assertion block (mandatory, do not remove)
from tests.qa.vision_ocr import ocr_card
from tests.qa.card_assertions import verdict_in_range, not_stub_shape, teams_populated, tier_badge_present

ocr_result = ocr_card(photo_path)   # path to Telethon-downloaded card image

assertions = {
    "verdict_in_range":    verdict_in_range(ocr_result),
    "not_stub_shape":      not_stub_shape(ocr_result),
    "teams_populated":     teams_populated(ocr_result),
    "tier_badge_present":  tier_badge_present(ocr_result),
}

# All four must be True — any False = brief FAILS, do not file report as Complete
assert all(assertions.values()), f"OCR assertion failures: {assertions}"
```

Report evidence required: OCR raw text output + assertion results table (assertion name / pass-fail / value observed). A report without this table is rejected — brief reopens.

---

### Dispatch Format v4.1 (LOCKED — 18 April 2026, supersedes v4)

**This is the ONLY acceptable format for dispatching ANY brief (INV, BUILD, QA, FIX, investigation, marketing, SEO — all types, all agents: LEAD, COO, anyone else). Zero deviations. Any dispatch not matching this exact format will be rejected by Paul.**

**What changed in v4.1 (18 Apr 2026):** added mandatory `(cli)` parenthetical on the Model token so the dispatcher and the report agree on which CLI ran the brief. Also locks the Agent-field taxonomy for reports. Solves the "Dataminer/Codex/Claude" report-label confusion raised by Paul on 17 Apr PM.

**Every dispatch has exactly two parts. Em dashes (`—`), not hyphens (`-`).**

**Part 1 — Bold metadata header** (markdown bold, OUTSIDE and ABOVE the code block, on its own line):

```
**[N] — Model (cli) [flags] — Mode — TYPE — Priority**
```

Field spec:
- `[N]` — sequential number in square brackets across this dispatch (`[1]`, `[2]`, `[3]` …).
- `Model` — exactly one of: `Opus`, `Sonnet`, `Haiku`, `GPT-5`, `GPT-5-Codex`. Never "agent type," never "opus-4-7" or any model string. Capitalised.
- `(cli)` — **MANDATORY, lowercase, in parentheses, immediately after Model.** Exactly one of: `(claude)`, `(codex)`, `(cowork)`, `(cursor)`. Identifies which CLI will execute the brief. Reports must echo this exact string in the `Agent:` field.
- `[flags]` — optional. If using Opus with max reasoning, append ` --effort max` AFTER the `(cli)` token (e.g. `Opus (claude) --effort max`). No other flags.
- `Mode` — exactly one of: `Parallel` (runs concurrently with its sibling dispatches), `Sequential` (must wait on prior brief in this dispatch), `Standalone` (single brief, no siblings). Capitalised.
- `TYPE` — the brief family, UPPERCASE: `INV`, `BUILD`, `QA`, `FIX`, `INVESTIGATE-REGRESS`, `MARKETING`, `SEO`, etc. Matches the first token of the BRIEF-ID inside the block.
- `Priority` — exactly one of: `P0`, `P1`, `P2`. P0 = launch-blocking, P1 = this-week, P2 = post-launch.

**Part 2 — Code block** (fenced, copy-paste ready — Paul pastes the entire block unchanged into the coding agent's terminal). Exactly four lines, in this exact order:

```
BRIEF-ID — Descriptive Title YYYY-MM-DD [optional score/metric]
https://www.notion.so/<page_id>
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

Line-by-line spec:
1. **Line 1** — `BRIEF-ID — Title YYYY-MM-DD [metric]`. BRIEF-ID is the Notion page's brief identifier (e.g. `INVESTIGATE-REGRESS`, `BUILD-HEALTH-CLVBF-WINDOW-01`, `IMG-PW3`). Em dash separator. Date in ISO format. Optional trailing metric like `0.0/10` if the brief scores against a baseline.
2. **Line 2** — Full Notion URL to the brief page. Must be a live page, not a database row.
3. **Line 3** — `NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN` — the MzansiEdgeCLI token. Mandatory. Label is exactly `NOTION_TOKEN:` — not `Use notion API token:` (old v3 wording, DEAD).
4. **Line 4** — `Execute this brief.` — literal, exact. Period included. No variations.

**Additional context line (optional, only if required):** If the brief was updated mid-flight or needs a one-line pointer, add ONE extra line INSIDE the code block AFTER `Execute this brief.` (e.g. `Brief was updated 14:20 to include AC6.`). Never add commentary before or outside the 4 canonical lines.

**Rules:**
- Each brief gets its own separate bold header + code block pair. Never combine multiple briefs into one block.
- Number sequentially across the entire dispatch (`[1]`, `[2]`, `[3]` …), not per-type.
- Full brief content lives on the Notion page. Never reference server file paths in the dispatch. The Notion page IS the brief.
- The token is NOT a secret from the agent — it's how the agent fetches the Notion page via API. Always include it.
- Header must be bold markdown OUTSIDE the code block. If it's inside the block, Paul's paste breaks. Reject before sending.

**Canonical example (single brief):**

**[3] — Opus (claude) --effort max — Standalone — INV — P0**

```
INVESTIGATE-REGRESS — Narrative Regression 2026-04-17 0.0/10
https://www.notion.so/345d9048d73c817c9d2bc224fd94b424
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

**Canonical example (multi-brief wave):**

**[1] — Opus (claude) --effort max — Parallel — INV — P0**

```
W29-INV — Edge Algorithm Coverage Analysis 2026-04-17
https://www.notion.so/abc123
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

**[2] — Sonnet (codex) — Sequential — BUILD — P1**

```
IMG-PW3 — My Matches Card Template 2026-04-17
https://www.notion.so/def456
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

**Pre-send self-check (mandatory — run before every dispatch):**
1. Is the header line bold markdown and OUTSIDE the code block? ✅/❌
2. Does the header use em dashes (`—`), not hyphens? ✅/❌
3. Is the number in brackets (`[3]`, not `3`)? ✅/❌
4. **Does the Model token carry a lowercase `(cli)` parenthetical** — one of `(claude)` / `(codex)` / `(cowork)` / `(cursor)`? ✅/❌
5. Does the header end with a Priority (`P0`/`P1`/`P2`)? ✅/❌
6. Inside the block: BRIEF-ID line → URL → `NOTION_TOKEN:` → `Execute this brief.` — in that order? ✅/❌
7. Is the token label exactly `NOTION_TOKEN:` (not `Use notion API token:`)? ✅/❌
8. Are there any lines outside the 4 canonical ones? ❌ (should be no)

Any ❌ → dispatch is wrong. Fix before sending. No exceptions.

**Violation:** Any dispatch not matching this format will be rejected by Paul on sight. Every dispatching agent (LEAD, COO, any other lead) re-reads this section before every dispatch.

---

### Agent Report — Filename & Header Schema (LOCKED 18 April 2026)

**Why:** Reports were being filed as `Agent: Dataminer`, `Agent: Codex`, etc., with no canonical taxonomy. Paul flagged 17 Apr PM. This section is the taxonomy. Every dispatcher embeds it in the brief. Every executing agent echoes it in the report.

**Agent taxonomy (lowercase, exactly one of):**
- `claude` — Claude Code CLI (server or local)
- `codex` — OpenAI Codex CLI
- `cowork` — Cowork desktop session (AUDITOR / LEAD / COO)
- `cursor` — Cursor IDE agent

**Not allowed in the `Agent:` field:** any persona (`Dataminer`, `AUDITOR`, `LEAD`, `COO`), any model name (`opus`, `sonnet`), any nickname. Personas go in `Dispatcher:` if needed. Models go in `Model:`.

**Report filename schema:** `<agent>-<BRIEF-ID>-<YYYYMMDD-HHMM>.md`
- `<agent>` — lowercase from the taxonomy above.
- `<BRIEF-ID>` — exact ID from the dispatch block line 1.
- `<YYYYMMDD-HHMM>` — UTC timestamp. SAST offset noted in report body.

Example: `claude-INV-PRECOMPUTE-DEAD-WATCH-01-20260418-0830.md` ✅

**Report body — first 6 lines, exact order:**

```
# <BRIEF-ID> — <outcome>
**Wave:** <BRIEF-ID>
**Agent:** claude | codex | cowork | cursor
**Model:** Opus | Sonnet | Haiku | GPT-5 | GPT-5-Codex
**Date:** YYYY-MM-DD
**Status:** Complete | Blocked | Escalated
```

**Brief template (dispatchers must embed verbatim in the Notion page body):**

> **Report filing — mandatory**
> After completion, file your report at:
> - Filename: `<agent>-<BRIEF-ID>-<YYYYMMDD-HHMM>.md` (agent lowercase: `claude`/`codex`/`cowork`/`cursor`)
> - First 6 lines of body must be the canonical header (`# …`, `**Wave:**`, `**Agent:**`, `**Model:**`, `**Date:**`, `**Status:**`).
> - Push to Agent Reports Pipeline via `push-report` (see SO #35).
> - Use the CLI name from the dispatch header's `(cli)` parenthetical — do NOT invent a persona name.

---

### Deployment Discipline: Crontab Integrity (LOCKED — 6 April 2026)

**Context:** On 2026-04-05, the entire server crontab was silently wiped from 30+ entries to 1, causing 33 hours of total scraper/pipeline downtime. This rule prevents recurrence.

**Pre-deployment check (mandatory for ANY brief that touches the server):**
```bash
# Before any changes
crontab -l | wc -l   # Must be ≥ 20. If not, STOP and alert COO.
```

**Post-deployment check (mandatory):**
```bash
# After all changes
crontab -l | wc -l   # Must still be ≥ 20. If count dropped, ROLLBACK.
/home/paulsportsza/scripts/update_cron_baseline.sh   # Update checksum if crontab was intentionally modified
```

**Rules:**
1. Never use `crontab -r` or pipe a partial file into `crontab`. Always use `crontab -l > backup && ... && crontab restored_file`.
2. If a brief adds or removes cron entries, the report MUST include before/after `crontab -l | wc -l` counts.
3. Canonical crontab backup: `/home/paulsportsza/crontab_restored_20260406.txt`. If the crontab is damaged, restore from this file.
4. After any intentional crontab change, run `/home/paulsportsza/scripts/update_cron_baseline.sh` to update the checksum baseline so the hourly watchdog doesn't false-alarm.

---

### Post-Brief Progress Table (LOCKED — 17 April 2026)

Canonical spec lives at [`reference/PROGRESS-TABLE-FORMAT.md`](../reference/PROGRESS-TABLE-FORMAT.md). Format is fixed:

```
| Brief ID | Track | Status | Agent | ETA | Evidence | Blockers |
```

Mandatory for Edge LEAD: emit after every brief report lands, at every roadmap review, and when dispatching a new wave. Status values are strict (`Queued` · `In flight` · `Blocked` · `Complete` · `Failed` — no other labels). See canonical file for column specs, ordering rules, launch-gate row, and examples.
