# Dev Team Briefing Standards (LOCKED — 6 March 2026)

> **Source of truth for agent briefing, delegation, and QA standards.**
> Referenced from CLAUDE.md.

*Last updated: 17 April 2026 PM by AUDITOR (CLAUDE-MD-SO-SPLIT-01 Tier 1 — absorbed 6 SOs from CLAUDE.md: #15, #18, #19, #27 [reworded], #33, #36.)*
*Updated: 4 May 2026 — BUILD-DEV-STANDARDS-V4.5-REVIEW-GATE-NARROW-01 — narrowed Codex Review Gate after FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01 burned full 5h window on stacked Opus Max + adversarial.*
*Updated: 5 May 2026 — FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01 — enforced `--wait` flag on all /codex:review and /codex:adversarial-review references. Bypasses interactive background/foreground prompt that defeats the gate in bridge-spawned dispatch context.*

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

### Multi-file refactor authoring discipline (LOCKED 2026-05-05)

Briefs that modify >3 files MUST include exact OLD/NEW snippets per file in the AC body. Format:

```
File: path/to/file.py
OLD:
    <exact existing code line(s) to be replaced>
NEW:
    <exact replacement code line(s)>
```

- **Agent's job becomes find-and-replace, NOT discovery.** No grep, no exploration, minimal context accumulation.
- File:line targets without OLD/NEW snippets are acceptable for single-file briefs OR for INV-class briefs where the agent must discover the bug. For mechanical FIX-class refactors touching >3 files, snippets are mandatory.
- The brief author has already read the file; they include what they read in the brief. The agent does not re-discover.

**Why:** autocompact thrash on multi-file refactors. Documented incident: `FIX-DBLOCK-RUNTIME-HOT-PATHS-01`, 12-minute thrash at 5% context. Each file in a multi-file refactor needs its own grep-then-read-then-edit cycle; brief-time discovery blows context faster than autocompact can recover.

---

### Dispatch Format v4.2 (LOCKED — 28 April 2026, supersedes v4.1 — Pure Claude reconciliation)

**This is the ONLY acceptable format for dispatching ANY brief (INV, BUILD, QA, FIX, investigation, marketing, SEO — all types, all agents: LEAD, COO, anyone else). Zero deviations. Any dispatch not matching this exact format will be rejected by Paul.**

**What changed in v4.2 (28 Apr 2026 — Pure Claude Ecosystem lock):** v4.1's multi-CLI taxonomy `(claude)` / `(codex)` / `(cowork)` / `(cursor)` directly contradicted `feedback_pure_claude_ecosystem.md` — both LOCKED on 18 April 2026. The contradiction was the root cause of the FIX-CLAUDEMD-D2-SUPERVISOR-01 "Codex attribution leak" surfaced by AUDITOR Lane B on 28 Apr 2026. v4.2 collapses the `(cli)` taxonomy to **two options only: `(claude)` and `(cowork)`.** `(codex)` and `(cursor)` are explicitly BANNED. Historical `codex-*.md` reports filed 17-28 Apr 2026 under `/home/paulsportsza/reports/` are tagged retroactive-noncompliant — not recovered, not deleted, just flagged. `.codex/` server-side auth is archived as part of `OPS-CHAOS-CLEANUP-01`.

**What changed in v4.1 (18 Apr 2026, NOW SUPERSEDED BY v4.2):** added mandatory `(cli)` parenthetical on the Model token so the dispatcher and the report agree on which CLI ran the brief. Also locked the Agent-field taxonomy for reports. Solved the "Dataminer/Codex/Claude" report-label confusion raised by Paul on 17 Apr PM. **Retired by v4.2's Pure Claude reconciliation.**

**Every dispatch has exactly two parts. Em dashes (`—`), not hyphens (`-`).**

**Part 1 — Bold metadata header** (markdown bold, OUTSIDE and ABOVE the code block, on its own line):

```
**[N] — Model (cli) [flags] — Mode — TYPE — Priority**
```

Field spec:
- `[N]` — sequential number in square brackets across this dispatch (`[1]`, `[2]`, `[3]` …).
- `Model` — exactly one of: `Opus`, `Sonnet`, `Haiku`, `GPT-5`, `GPT-5-Codex`. Never "agent type," never "opus-4-7" or any model string. Capitalised.
- `(cli)` — **MANDATORY, lowercase, in parentheses, immediately after Model.** Exactly one of: `(claude)`, `(cowork)`. `(codex)` and `(cursor)` are BANNED per Pure Claude Ecosystem lock (v4.2, 28 Apr 2026). Identifies which Claude executor runs the brief. Reports must echo this exact string in the `Agent:` field.
- `[flags]` — optional. If using Opus with max reasoning, append ` --effort max` AFTER the `(cli)` token (e.g. `Opus (claude) --effort max`). No other flags.
- `Mode` — exactly one of: `Parallel` (runs concurrently with its sibling dispatches), `Sequential` (must wait on prior brief in this dispatch), `Standalone` (single brief, no siblings). Capitalised. **See Mode Selection Rule below — same-repo briefs MUST be Sequential.**
- `TYPE` — the brief family, UPPERCASE: `INV`, `BUILD`, `QA`, `FIX`, `INVESTIGATE-REGRESS`, `MARKETING`, `SEO`, etc. Matches the first token of the BRIEF-ID inside the block.
- `Priority` — exactly one of: `P0`, `P1`, `P2`. P0 = launch-blocking, P1 = this-week, P2 = post-launch.

**Mode Selection Rule (LOCKED — 27 April 2026 — same-repo serialization):**

The `Mode` flag is **load-bearing** — it determines whether briefs run concurrently or block on each other. Wrong choice causes pre-merge gate collisions, where one agent's uncommitted dirty state fails the full test suite that the other agent's commit gate runs.

- **`Parallel` is permitted ONLY when every sibling brief in the wave touches a DIFFERENT git repo** (e.g. one in `publisher`, one in `bot`, one in `scrapers`, one in `mzansiedge-wp`). Pre-merge gates run isolated per repo — cross-repo parallelism is collision-free.
- **`Sequential` is MANDATORY when two or more sibling briefs touch the SAME repo**, regardless of which files they edit. The pre-merge gate runs the full test suite in that repo on every commit — a sibling agent's uncommitted dirty state can fail unrelated tests and block the gate.
- **Default to `Sequential` when in doubt.** False-positive serialization costs ~10 minutes of wall time. False-positive parallelism costs a wave-blocking pre-merge collision (incident: 27 April 2026 — FIX-CONTENT-LAWS-CANON-01 + FIX-DASH-CHANNEL-NORMALISE-FAIL-LOUD-01 both targeted the bot repo as `Parallel`; CONTENT-LAWS-CANON pre-merge gate failed on a test owned by the still-uncommitted DASH-NORMALISE work).
- **Repo identification is part of dispatch authoring.** Every brief lives in exactly one primary repo per its file:line targets. If a brief touches multiple repos, it's `Sequential` against any sibling that touches any of those repos.
- **Pre-send check (mandatory):** for every brief marked `Parallel` in your dispatch, identify its primary repo (read the file:line in the Notion brief — look for `/home/paulsportsza/<repo>/...`). If any two `Parallel` siblings share a repo, downgrade the later one(s) to `Sequential` before sending.

**Repo classification cheat-sheet:**

| Repo | Path | Common brief types |
|---|---|---|
| `publisher` | `/home/paulsportsza/publisher` | autogen, channel modules, prequeue, dispatch loop, compliance |
| `bot` | `/home/paulsportsza/bot` | dashboard, bot.py, cards, reels, narrative, arbiter, QA gallery |
| `scrapers` | `/home/paulsportsza/scrapers` | sharp data, edge ingestion, settlement |
| `mzansiedge-wp` | `/var/www/mzansiedge-wp` | LP, blog, WP theme, hero pages |
| `Cowork` (no git) | n/a | `daily-*` scheduled task prompts (use `update_scheduled_task` directly, not via brief) |

**Part 2 — Code block** (fenced — **this is what the bridge pastes into the spawned Claude Code session. Cowork agents NEVER paste this manually.** See `ops/DISPATCH-V2.md §The Dispatch Block`). Exactly four lines, in this exact order:

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

**[2] — Sonnet (claude) — Sequential — BUILD — P1**

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
4. **Does the Model token carry a lowercase `(cli)` parenthetical** — one of `(claude)` / `(cowork)` only? `(codex)` and `(cursor)` are BANNED per Pure Claude Ecosystem lock. ✅/❌
5. Does the header end with a Priority (`P0`/`P1`/`P2`)? ✅/❌
6. Inside the block: BRIEF-ID line → URL → `NOTION_TOKEN:` → `Execute this brief.` — in that order? ✅/❌
7. Is the token label exactly `NOTION_TOKEN:` (not `Use notion API token:`)? ✅/❌
8. Are there any lines outside the 4 canonical ones? ❌ (should be no)
9. **Mode selection check:** for every brief marked `Parallel`, did you confirm it targets a DIFFERENT repo from every other `Parallel` sibling in this wave? Same-repo `Parallel` is a violation — downgrade the later one(s) to `Sequential`. ✅/❌

Any ❌ → dispatch is wrong. Fix before sending. No exceptions.

**Violation:** Any dispatch not matching this format will be rejected by Paul on sight. Every dispatching agent (LEAD, COO, any other lead) re-reads this section before every dispatch.

---

### SSH-Enqueue (canonical) — LOCKED 30 April 2026

**Supersedes** the `dispatch_runner.sh` manual-paste model
(BUILD-WORKTREE-DISPATCH-RUNNER-01). Cowork agents NEVER paste the dispatch
block manually. Bridge handles everything after `ssh` exits.

Full architecture at `ops/DISPATCH-V2.md`.

**Command (Cowork-side):**

```bash
KEY=$(find /sessions -name "id_ed25519" -path "*.cowork-ssh*" -print -quit)
ssh -i "$KEY" -o StrictHostKeyChecking=no -o BatchMode=yes paulsportsza@37.27.179.53 \
  -- '--notion-url <NOTION-URL> --role edge_<lead|auditor|coo> --mode <sequential|parallel>'
```

**enqueue.py flags:**

| Flag | Values | Default |
|------|--------|---------|
| `--notion-url` | full Notion URL | *(required)* |
| `--role` | `edge_lead`, `edge_auditor`, `edge_coo` | `edge_lead` |
| `--target-repo` | repo name | `bot` |
| `--mode` | `sequential`, `parallel` | `sequential` |
| `--depends-on` | `<id1,id2>` | *(none)* |
| `--no-cmux-validation` | flag | off |

**What happens after `ssh` exits:**
1. `pending/<BRIEF-ID>.yaml` written on server.
2. `dispatch-promoter.service` polls every 5s → promotes to `ready/` when deps
   clear and mode allows.
3. Mac `cmux-bridge` polls `ready/` → creates CMUX workspace, spawns
   `mosh + claude`, pastes the 4-line dispatch block automatically.
4. Claude Code session executes brief autonomously. Cowork agent's
   responsibility ends at step 1.

**Wave worktree contract (unchanged from BUILD-WORKTREE-DISPATCH-RUNNER-01):**
- Wave-class file edits in `/home/paulsportsza/bot/` main tree are refused at
  commit time. Carve-outs: `ops/`, `reference/`, `COO/`, `HANDOFFS/`,
  `CLAUDE.md`, `static/qa-gallery/canonical/`.
- Audit-trailed bypass: `WAVE_GUARD_BYPASS=1 git commit ...`
  (controller-approved only).

**Pure Claude Ecosystem (v4.2) — still enforced:** only `claude` CLI. `codex`
and `cursor` are banned. `dispatch-promoter` rejects briefs carrying banned CLI
tags.

**Regression guards:**
- `tests/contracts/test_dispatch_runner_so41.py` — covers the SO #41 contract
  (subprocess + temp git repo, no live Notion or claude calls).

---

### Agent Report — Filename & Header Schema (LOCKED 18 April 2026)

**Why:** Reports were being filed as `Agent: Dataminer`, `Agent: Codex`, etc., with no canonical taxonomy. Paul flagged 17 Apr PM. This section is the taxonomy. Every dispatcher embeds it in the brief. Every executing agent echoes it in the report.

**Agent taxonomy (lowercase, exactly one of) — Pure Claude Ecosystem LOCKED 28 April 2026:**
- `claude` — Claude Code CLI (server or local)
- `cowork` — Cowork desktop session (AUDITOR / LEAD / COO)

**BANNED (per Pure Claude Ecosystem lock, 28 Apr 2026):**
- `codex` — OpenAI Codex CLI. Was permitted 17-28 Apr 2026; reports filed under this label are retroactive-noncompliant.
- `cursor` — Cursor IDE agent. Was permitted 17-28 Apr 2026; same retroactive-noncompliant status.

Any report filed with `Agent: codex` or `Agent: cursor` after 28 Apr 2026 is invalid and the brief reopens.

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
**Agent:** claude | cowork
**Model:** Opus | Sonnet | Haiku | GPT-5 | GPT-5-Codex
**Date:** YYYY-MM-DD
**Status:** Complete | Blocked | Escalated
```

**Brief template (dispatchers must embed verbatim in the Notion page body):**

> **Report filing — mandatory**
> After completion, file your report at:
> - Filename: `<agent>-<BRIEF-ID>-<YYYYMMDD-HHMM>.md` (agent lowercase: `claude` or `cowork` only)
> - First 6 lines of body must be the canonical header (`# …`, `**Wave:**`, `**Agent:**`, `**Model:**`, `**Date:**`, `**Status:**`).
> - Push to Agent Reports Pipeline via `push-report` (see SO #35).
> - Use the CLI name from the dispatch header's `(cli)` parenthetical — do NOT invent a persona name. Only `claude` or `cowork` are permitted (per v4.2 Pure Claude Ecosystem lock).

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

### Parallel Lane Safety: Pathspec-Restricted Commits (LOCKED — 27 April 2026)

**Context:** On 2026-04-27 during OPS-STASH-AUDIT-01, a multi-commit walk on the bot repo was contaminated by a parallel curatorial-lane subagent that staged unrelated files between Opus-LEAD's pre-flight `git status` and its `git commit`. A naked `git commit` swept the canonical-lane's PNGs and `index.html` mod into a wave-named test commit. Recovery cost a `git reset --mixed HEAD~1` mid-execution. Race-safe pattern below prevents recurrence.

**Rule:** When the repo has any other concurrent session that may stage / modify files (Cowork curatorial lanes, scheduled scrapers, parallel agents), every commit MUST use the pathspec-restricted form:

```bash
git add <file1> [file2] [...]
git commit -m "<message>" -- <file1> [file2] [...]
```

The `-- <pathspec>` after the commit message restricts the commit to ONLY those paths regardless of what else is staged in the index. Naked `git commit` (no pathspec) commits everything in the index — including anything a parallel lane added between your `git add` and your `git commit`.

**When this matters:**
- Any wave that loops over multiple files committing one at a time.
- Any wave running on a repo that has an active curatorial / canonical lane (currently: bot repo + `static/qa-gallery/canonical/*` Paul-owned curatorial lane).
- Any OPS-STASH-AUDIT-style sweep across multiple owning waves.

**When it doesn't matter:**
- Single-file single-commit waves (the one file IS the path).
- Repos with zero concurrent agents (rare).

**Forward fix when contamination is detected mid-execution:**
1. `git reset --mixed HEAD~1` — restores files to working tree, keeps history clean.
2. Re-stage only your target paths.
3. Re-commit with the pathspec form.
4. Continue the wave. Document the recovery in the report.

**No `--force` push** to recover from contamination. The pathspec form is the prevention; the reset is the recovery; force-push is never the answer.

**Contract:** Every report from a multi-commit OPS / FIX brief running on bot or any active-curatorial repo MUST cite which form was used. Naked `git commit` form on these repos = brief incomplete.

---

### Post-Brief Progress Table (LOCKED — 17 April 2026)

Canonical spec lives at [`reference/PROGRESS-TABLE-FORMAT.md`](../reference/PROGRESS-TABLE-FORMAT.md). Format is fixed:

```
| Brief ID | Track | Status | Agent | ETA | Evidence | Blockers |
```

Mandatory for Edge LEAD: emit after every brief report lands, at every roadmap review, and when dispatching a new wave. Status values are strict (`Queued` · `In flight` · `Blocked` · `Complete` · `Failed` — no other labels). See canonical file for column specs, ordering rules, launch-gate row, and examples.

---

### Codex Review Gate (SO #45, v4.5 — LOCKED 4 May 2026)

*Supersedes v4.4 (3 May 2026). Routing v1 pivot: Codex stops being a primary executor. Codex now runs as the universal reviewer invoked via `/codex:review --wait` or `/codex:adversarial-review --wait` at the end of every code-touching brief, before `mark_done.sh`. Claude (Sonnet | Opus Max Effort) executes; Codex reviews. The `--wait` flag bypasses the interactive background/foreground prompt — without it, the review runs as a background task and may not complete before the session exits, defeating the gate.*

**Why v4.5:** FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01 burned the entire Cowork 5h window (1h 39m executor wall-time, 171k tokens, 7% balance left) running Opus Max Effort + `/codex:adversarial-review` (without `--wait`) stacked on top. The trigger fired correctly per v4.4's mandatory list but the cost is incompatible with Routing v1 §4 cost discipline. Fix the rule, not the gate.

#### Lifecycle (one extra mandatory step per brief)

After commit + push, before `mark_done.sh`:
1. Run `/codex:review --wait` (standard) or `/codex:adversarial-review --wait <focus>` (adversarial — see below) on the wave branch. (`--wait` bypasses the interactive background/foreground prompt.)
2. If review returns blockers, address with additional commits + push, then re-run review.
3. Only proceed to `mark_done.sh` when review returns no blockers.
4. Include the review summary verbatim in the report under a `## Codex Review` section.
5. State the outcome explicitly: `clean | blockers-addressed | bootstrap-exempt`.

Reports without the `## Codex Review` section are INCOMPLETE and reopen the brief.

#### Review modes

- **`/codex:review --wait`** — standard. Default for all briefs. Catches functional correctness, regressions, contract drift, gate coverage.
- **`/codex:adversarial-review --wait <focus text>`** — adversarial. DISCRETIONARY — invoked only when one of the conditions below is met. Never auto-fired from trigger match alone.

**Adversarial is DISCRETIONARY. Invoked only when:**
- (a) The brief AC explicitly sets `review_mode: adversarial-review` with a focus text, OR
- (b) Standard `/codex:review --wait` output itself recommends escalation, OR
- (c) Paul override.

The trigger list below no longer auto-fires adversarial.

#### Adversarial-review mandatory triggers (narrowed 6 → 3)

Adversarial review MUST be used (i.e. brief AC must declare `review_mode: adversarial-review`) when:

1. New runtime path handling **money, payments, or auth**.
2. Schema changes on tables with **retention / billing / compliance** impact.
3. Migrations that are **not idempotent or not rollback-safe**.

#### "Consider adversarial" advisory list (author judgement, not auto-fire)

The following moved from mandatory to advisory. Author uses judgement — standard review is the default, adversarial is opt-in when the specific risk warrants it:

- Concurrency-sensitive code (locks, queues, async handlers, scrapers).
- Any change touching the dispatch system, bridge, or worktree-runner.
- Any narrative / cache surface that ships to premium-tier users.

#### Cost rule (NEW — v4.5)

When executor model = **Opus Max Effort**, the default review is **standard `/codex:review --wait`** unless the brief AC explicitly justifies adversarial (i.e. satisfies one of the 3 mandatory triggers above or has a Paul override). No stacking premium-on-premium without explicit justification in the brief body.

#### Brief authoring rule

Every brief's AC block MUST specify the review mode:

```
Review mode for this brief: review | adversarial-review
```

For `adversarial-review`, the focus text is also required. Implicit adversarial from trigger match alone is not permitted — the AC must declare it.

#### Report format

Every report MUST include:

```markdown
## Codex Review
<review summary verbatim>
Outcome: clean | blockers-addressed | bootstrap-exempt
```

#### Bootstrap exemption

`BUILD-CODEX-PLUGIN-INSTALL-AND-VERIFY-01` and `BUILD-DEV-STANDARDS-V4.4-REVIEW-GATE-01` are exempt (ratifies the gate as canonical). All subsequent code-touching briefs MUST gate.

#### Active vs Retired Agent set (post v4.4, unchanged in v4.5)

- **Active 8**: Sonnet | Opus Max Effort × LEAD | AUDITOR | COO | NARRATIVE.
- **Retired 8** (Codex executor agents — now reviewers only): Codex XHigh | Codex High × the four roles. Selectable transitionally; `enqueue.py` emits a stderr WARNING when dispatched.

Mirror: `ops/MODEL-ROUTING.md` §9 (Cowork). Notion Routing v1 §10 (`354d9048-d73c-8138-bf72-d8ce7b768a08`).
