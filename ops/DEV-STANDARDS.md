# Dev Team Briefing Standards (LOCKED — 6 March 2026)

> **Source of truth for agent briefing, delegation, and QA standards.**
> Referenced from CLAUDE.md.

*Last updated: 6 May 2026 by Codex XHigh - AUDITOR (FIX-DOCS-SO45-ROUTING-MIRROR-CLEANUP-01 — aligns Codex Review Gate template with the pure-codex inline sub-agent lock event `FIX-SO45-CODEX-INLINE-SUBAGENT-01`: hybrid uses `/codex:review --wait`; pure-codex uses `codex --profile xhigh exec`). Earlier history: 4 May 2026 by Sonnet - AUDITOR (BUILD-DEV-STANDARDS-V45-REVIEW-GATE-NARROW-01 — v4.4 → v4.5, narrows Codex Review Gate after FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01 burned full 5h Cowork window on stacked Opus Max + mandatory adversarial; adversarial review is now DISCRETIONARY via brief AC; mandatory adversarial triggers narrowed 6→3; cost rule added). 3 May 2026 by Opus Max Effort - AUDITOR (BUILD-DEV-STANDARDS-V4.4-REVIEW-GATE-01 — v4.3 → v4.4, ratifies Codex Review Gate as canonical brief lifecycle / SO #45). 17 April 2026 PM by AUDITOR (CLAUDE-MD-SO-SPLIT-01 Tier 1 — absorbed 6 SOs from CLAUDE.md: #15, #18, #19, #27 [reworded], #33, #36.)*

---

## Codex Review Gate (v4.5 — LOCKED 4 May 2026, amended 6 May 2026)

**v4.5 narrows the Codex Review Gate to fix the cost-stacking failure mode.** Standard review remains mandatory on every code-touching brief, but the canonical invocation is mode-aware: `DISPATCH_MODE=hybrid` uses `/codex:review --wait`; `DISPATCH_MODE=pure-codex` uses a fresh inline `codex exec` sub-agent (`codex --profile xhigh exec`) per `FIX-SO45-CODEX-INLINE-SUBAGENT-01`. Adversarial review is **DISCRETIONARY** — opt-in via brief AC, NOT auto-fired by trigger match. v4.4's mandatory trigger list (6 categories) is narrowed to **3 hard categories** (money/payments, auth/settlement, non-rollback-safe migrations); the other three move to ADVISORY ("Consider adversarial"). Cost rule added: when executor = Opus Max Effort, default review = standard review unless brief AC explicitly justifies adversarial. **Driver:** FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01 stacked Opus Max + mandatory adversarial on a dispatch-system trigger and burned the full 5h Cowork window (1h 39m, 171k tokens, 7% balance left) — incompatible with Routing v1 §4 cost discipline.

Routing v1 pivot otherwise unchanged: Codex stops being a primary executor in hybrid dispatch; Claude (Sonnet or Opus Max Effort) executes and Codex reviews. Under pure-codex dispatch, the executor is already Codex, so the unbiased second pass is a separate `codex exec` process with fresh context. Both paths run after commit + push and before `mark_done.sh`. Locked under SO #45; pure-codex amendment locked 6 May 2026 by `FIX-SO45-CODEX-INLINE-SUBAGENT-01`.

### Lifecycle (one extra mandatory step per brief)

Standard brief execution gains one mandatory step between commit + push and `mark_done.sh`:

1. After commit + push, before `mark_done.sh`, choose the review mechanism by dispatch mode:
   - `DISPATCH_MODE=hybrid`: run `/codex:review --wait` (or `/codex:adversarial-review --wait <focus text>` when AC explicitly declared) on the wave branch from inside the executing Claude Code session.
   - `DISPATCH_MODE=pure-codex`: run `codex --profile xhigh exec "<review prompt>"` as a fresh inline sub-agent from inside the executing Codex session.
2. If review returns blockers, address them with additional commits + push, then re-run review.
3. Only proceed to `mark_done.sh` when review returns no blockers.
4. Include the review summary verbatim in the report under `## Codex Review` for hybrid mode or `## Codex Sub-Agent Review` for pure-codex mode.
5. State the outcome explicitly: `Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt`.

### Review modes

- **Hybrid standard:** `/codex:review --wait` — DEFAULT, MANDATORY when Claude is the executor. Functional correctness, regressions, contract drift, gate coverage. Use on every code-touching hybrid brief unless adversarial is explicitly declared.
- **Hybrid adversarial:** `/codex:adversarial-review --wait <focus text>` — DISCRETIONARY (v4.5). Adversarial second-pair-of-eyes on a specified failure-class focus. Invoked only when (a) brief AC explicitly sets `review_mode: adversarial-review` with focus text, (b) standard hybrid review output recommends escalation, or (c) Paul override. Trigger list does NOT auto-fire adversarial in v4.5.
- **Pure-codex standard:** `codex --profile xhigh exec "<review prompt>"` — DEFAULT, MANDATORY when Codex is the executor. This is the `FIX-SO45-CODEX-INLINE-SUBAGENT-01` lock event: a fresh process, fresh context, synchronous stdout, no slash-command/plugin dependency.
- **Pure-codex adversarial:** same `codex exec` mechanism with the adversarial prompt framing from §Pure-Codex Sub-Agent Review when AC explicitly declares `review_mode: adversarial-review` or a hard trigger applies.

### When to use adversarial review (mandatory triggers — narrowed v4.5)

**Mandatory triggers (3 hard categories — adversarial REQUIRED in brief AC):**

- New runtime path that handles **money or payments**.
- New runtime path that handles **auth or settlement**.
- Migrations that are **not rollback-safe** (any migration where rollback would lose data or break invariants).

**Advisory list (3 categories — "Consider adversarial" — author judgement, NOT auto-fire):**

- Concurrency-sensitive code (locks, queues, async handlers, scrapers).
- Changes touching the dispatch system, bridge, or worktree-runner.
- Narrative / cache surfaces that ship to premium-tier users.

For advisory items, the author decides per-brief whether the architectural risk warrants the cost of an adversarial review. Standard review is sufficient for the majority; reserve adversarial for genuinely high-blast-radius changes within those categories.

### Cost rule (v4.5 NEW)

When the executor model is Opus Max Effort, default review = hybrid standard `/codex:review --wait` unless the brief AC explicitly justifies adversarial in writing. No stacking premium-on-premium without justification. This rule exists because Opus Max Effort + adversarial Codex on the same brief routinely consumes the entire 5h Cowork window — incompatible with parallel orchestration.

### Brief authoring rule (v4.5 amended)

Every brief's AC block MUST explicitly declare `review_mode: review | adversarial-review` — no implicit escalation from trigger match. For `adversarial-review`, the focus text must state what to challenge. The Canonical Brief Template Block (see § Canonical Brief Template Blocks below) is mandatory in every dispatched brief. Dispatcher tooling (LEAD / COO / NARRATIVE / AUDITOR / any drafter) must embed the block verbatim before sending.

### Report format

Every report MUST include the review section for its dispatch mode:

- Hybrid: `## Codex Review` with the full slash-command summary verbatim.
- Pure-codex: `## Codex Sub-Agent Review` with the full `codex exec` stdout verbatim.
- An explicit `Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt` line.

Reports without this section are INCOMPLETE and the brief reopens. AUDITOR verifies on every worker return; COO blocks merge of any wave whose reports fail this check.

### Bootstrap exemption

Only three briefs are bootstrap-exempt because they ratify or amend the gate itself:

- `BUILD-CODEX-PLUGIN-INSTALL-AND-VERIFY-01` (server-side `/codex:*` plugin install).
- `BUILD-DEV-STANDARDS-V4.4-REVIEW-GATE-01` (this brief — ratifies the gate as canonical lifecycle).
- `BUILD-DEV-STANDARDS-V4.5-REVIEW-GATE-NARROW-01` (narrows the gate and cost rule).

All subsequent code-touching briefs MUST gate. Reports for the three exempt briefs include `Outcome: bootstrap-exempt` instead of `clean`.

### Why

Sonnet-LEAD's commit-discipline pattern (multiple SO #41 violations Apr–May 2026) showed that pre-commit testing alone catches mechanical errors but not architectural risks (race conditions, auth gaps, data-loss windows, migration rollback safety). The Codex review gate adds a second pair of eyes before any merge becomes irreversible. Pre-merge tests verify "did we break the existing contract?"; the standard review verifies "did we ship the right contract for this change?". The discretionary adversarial mode handles the small subset of changes where the architectural risk genuinely warrants the additional cost.

**v4.5 narrowing rationale:** v4.4's mandatory trigger list was too broad — "any change touching the dispatch system" alone fires on basically every bridge brief. Stacked with Opus Max Effort executor (the right model for hard concurrency / cache / runtime work), the combined cost burned the full 5h Cowork window per brief, blocking parallel orchestration. v4.5 keeps the gate's value (mandatory standard review) while moving the cost-stacking trigger categories to advisory. Premium models are accelerators, not comfort blankets — Routing v1 §4.

### Pure-Codex Sub-Agent Review (LOCKED 6 May 2026 — `FIX-SO45-CODEX-INLINE-SUBAGENT-01`)

When `DISPATCH_MODE=pure-codex` (Codex is the executor), the `/codex:review --wait` plugin / companion path is REDUNDANT — the executor is already Codex; calling its own plugin adds no cross-process eyes value, and the `codex review --commit` non-interactive subcommand has hung agents on background-task UX (13+ minute waits with no progress). **The new pattern: agent spawns a fresh `codex exec` sub-agent inline, synchronous, no plugin dependency.**

**Mechanism.** After commit + push, before `mark_done.sh`, the executor agent runs:

```bash
DIFF=$(git show --stat --patch HEAD)
codex --profile xhigh exec "$(cat <<EOF
You are an INDEPENDENT reviewer with NO prior context on this brief. Examine the diff below.

Brief: <BRIEF-ID> — <one-line summary from brief title>

Diff (commit $(git rev-parse HEAD)):
${DIFF}

Review for: race conditions, auth gaps, data-loss windows, migration rollback safety, logic errors, contract violations, missed callers of shared behaviour, gate coverage.

Output exactly this structure:

## Codex Sub-Agent Review

Outcome: clean | blockers-addressed | needs-changes

Findings:
- [P0|P1|P2|P3] <file:line> — <one-line description>
- (or "none" if no findings)
EOF
)"
```

The new `codex exec` invocation is a fresh process, fresh context, no shared session with the executor. That's the unbiased sub-agent. It returns to stdout synchronously (no background-task UX), so the agent can capture verbatim and embed in the report.

**Adversarial framing.** When `review_mode: adversarial-review` is declared in the brief AC (or a hard trigger fires — money/auth/non-rollback-safe migration), the prompt above is amended:

```
You are an ADVERSARIAL reviewer. Your job is to FIND failure modes, not validate.
Specific focus: <focus text from brief AC, e.g. "concurrent-write race on bot.py:render_card_image">
Be hostile. Look for what could go wrong. Edge cases. Missing locks. Auth bypasses. 
If you find ANY plausible failure mode, return needs-changes regardless of how unlikely.
Output structure same as standard review.
```

**Report section.** Agent embeds the sub-agent's stdout VERBATIM under a `## Codex Sub-Agent Review` heading (note: heading distinguishes the new pattern from the old `## Codex Review` plugin section — useful for archive/audit). Outcome line MUST appear: `clean | blockers-addressed | needs-changes | bootstrap-exempt`. Reports without this section reopen the brief.

**Hybrid mode unchanged.** When `DISPATCH_MODE=hybrid` (Claude executor), `/codex:review --wait` slash command IS the canonical pattern — it provides genuine cross-process eyes (Claude executor, Codex reviewer). Don't invent new patterns when the existing one works.

**What's wrong with the old plugin path under pure-codex (driver for the rewrite):** the `/codex:review --wait` slash invokes `node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" review` which spawns a NEW codex companion process — fine in principle, but its `codex review --commit <sha>` invocation is the non-interactive companion CLI which (a) backgrounds without `--wait` (the slash translates `--wait` correctly when fired from the slash, but when `codex` itself spawns an `exec`-style sub-agent it doesn't have an analogous flag), (b) spawns a `Waiting for background terminal` UX that has hung agents 13+ min with no completion signal, (c) the slash command itself isn't always installed in spawn environments. Direct `codex exec "<prompt>"` skips all of that — synchronous, no plugin, fresh context.

### Mirror

This section is paired with Routing v1 §10 on Notion (page `354d9048-d73c-8138-bf72-d8ce7b768a08`) and `ops/MODEL-ROUTING.md` (Cowork). Notion is canonical for routing decisions; DEV-STANDARDS is canonical for brief lifecycle and reporting protocol.

---

## Canonical Brief Template Blocks

The following blocks are mandatory in every dispatched brief. Each block goes verbatim into the brief's Notion page body. Dispatchers (LEAD / COO / NARRATIVE / AUDITOR / any drafter) embed them before sending.

### Codex Review Gate (mandatory, SO #45)

```
**Codex Review Gate (mandatory, SO #45 — v4.5)**

Review mode for this brief: `<review | adversarial-review>`  ← MUST be explicitly declared (no implicit escalation)
<If adversarial-review: focus text: "<what to challenge>">
<If executor=Opus Max Effort and review_mode=adversarial-review: justification: "<why premium-on-premium cost is warranted>">

After commit + push, before mark_done.sh:
1. If `DISPATCH_MODE=hybrid`: run `/codex:review --wait` (or `/codex:adversarial-review --wait <focus text>` when explicitly declared) on the wave branch.
2. If `DISPATCH_MODE=pure-codex`: run `codex --profile xhigh exec "<review prompt>"` as a fresh inline sub-agent per `FIX-SO45-CODEX-INLINE-SUBAGENT-01`.
3. If review returns blockers / `needs-changes`, address them with additional commits + push, then re-run review.
4. Only proceed to mark_done.sh when review returns no blockers.
5. Include the review summary verbatim in the report under `## Codex Review` for hybrid or `## Codex Sub-Agent Review` for pure-codex.
6. State the outcome: `clean | blockers-addressed | needs-changes | bootstrap-exempt`.
```

Dispatcher tooling guidance: every dispatched brief MUST include the Codex Review Gate block above with `review_mode` explicitly declared. Briefs missing it are non-compliant under v4.5 and must be re-issued.

---

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

### Multi-file refactor authoring discipline — blast-radius scoped (LOCKED 6 May 2026, supersedes 5 May rev)

**The 5 May rule was too aggressive.** Triggering on raw file count (incl. tests) blocked normal responsible fixes that touched 4 files where 2 were tests. New rule scopes discipline to PRODUCTION-file blast radius and exempts incidental tests.

**Trigger ladder:**

1. **≤3 production files** → agent may proceed with normal grep+read discovery. No pre-baked snippets required. Tests don't count regardless of how many.
2. **>3 production files** → brief AC MUST contain explicit per-file intent + OLD/NEW snippets per file, OR carry a pre-flight approval token (`Pre-flight: approved by <role> for discovery-mode (>3 files)` — used when the change is genuinely exploratory and the dispatcher accepts the thrash risk).
3. **Tests count toward the threshold ONLY when** the test change requires broad fixture / harness / framework refactor that itself shapes the production change (e.g. introducing a new test base class that 8 tests inherit from, or a shared mock that touches 5 fixture files). A targeted test added alongside a single-file production fix doesn't count.
4. **Shared-behavior changes** (modifying a util, contract, public function, base class, or signal used by ≥3 callers) require an extra-review block in the brief AC declaring the shared surface + caller scan, EVEN IF only 1 file actually changes. Format: `Shared-behavior: <symbol/file:line> · callers: <grep result, count + locations>`. Reviewer (Codex sub-agent or LEAD) eyes the caller scan to confirm no missed downstream impact.

**Why:** agents executing multi-file refactors without explicit per-file snippets must Grep+Read each file to locate the change site — multiplied by file count, context bloats, autocompact fires, brief dies. Two documented incidents (4-5 May 2026): `FIX-DBLOCK-RUNTIME-HOT-PATHS-01` (12-min thrash, 7 production files); `FIX-BRIEF-AUTHORING-MULTIFILE-DISCIPLINE-01` (24-min thrash, 4 production files). But the same rule applied to a 2-prod-file + 2-test-file fix wrongly blocks normal work. Blast radius matters; raw count doesn't.

**Authoring rules when the >3-prod trigger fires (mandatory in the AC body):**

1. **Per-file OLD/NEW snippets.** For each PRODUCTION file the brief touches, the AC includes a fenced block: full server-absolute path, exact OLD code (sufficient surrounding context for unique match: typically 5-15 lines), exact NEW code, expected character delta. Copy-paste fidelity. Tests don't need this unless they hit rule 3 above.
2. **Line range hint per file.** Each file gets `Read` instruction with `offset`/`limit` covering only the change region (SO #30 compliance). The agent never reads full files.
3. **No "discover the call site" instructions.** Phrases like "find every place X is called", "update all callers" are AUTHOR responsibility — the author runs the grep, lists file:line:snippet results, bakes them into the AC. If the author can't enumerate sites, the brief is INV-class, not FIX-class.
4. **One commit one push.** Agent applies all snippets in a single working-tree session, runs the contract test, commits once.
5. **Contract test scope:** if the brief ships >3 production-file edits, the contract test MUST be a single regex/AST scan across all touched files (not per-file unit tests).

**Pre-send check (dispatcher):** before sending any FIX/BUILD brief touching >3 PRODUCTION files (test count excluded), count the OLD/NEW snippets in the AC. If snippet count < production file count, the brief is non-compliant — re-author or attach `Pre-flight: approved` token before dispatch.

**Cost rule:** if a brief genuinely needs >3 production-file edits AND >3 sites of judgement (i.e. the author can't pre-bake snippets without doing the agent's work), split it into N atomic single-file briefs and dispatch sequentially. Atomic single-file briefs cannot thrash.

**Driver for the 6 May revision (`FIX-SO30-BLAST-RADIUS-01`):** the original 5 May rule started rejecting normal 2-prod + 2-test fixes that posed no real thrash risk. Goal of the rule is preventing autocompact thrash on genuinely large refactors, not gating routine work behind ceremony. Blast-radius framing keeps the guardrail where the risk lives and removes it from where it doesn't.

---

### Dispatch Format v4.3 (LOCKED — 2 May 2026 PM, supersedes v4.2 — Routing v1 reconciliation)

**This is the ONLY acceptable format for dispatching ANY brief (INV, BUILD, QA, FIX, INVESTIGATE-REGRESS, MARKETING, SEO — all types, all agents: LEAD, AUDITOR, COO, NARRATIVE). Zero deviations. Any dispatch not matching this exact format will be rejected by Paul.**

**What changed in v4.3 (2 May 2026 PM — Routing v1 reconciliation):** v4.2's Pure Claude Ecosystem lock banned `(codex)` from the `(cli)` parenthetical — but [Model Routing v1](https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08) reverses that ban: codex is canonical again for hard code root-cause + mechanical acceleration. v4.3 **eliminates the separate `Model` + `(cli)` fields** and replaces them with a single `Agent` token drawn directly from the 16 canonical Routing v1 options. The executor (claude vs codex) is implicit in the Agent name (`Codex XHigh` → codex; `Sonnet` → claude). One source of truth, no contradictions, no hand-mapping. The Notion brief's `Agent` property, the dispatch header, and the agent's report all use the SAME exact string.

**What changed in v4.2 (28 Apr 2026, NOW SUPERSEDED BY v4.3):** collapsed `(cli)` to `(claude)` / `(cowork)` only — banned `(codex)` and `(cursor)`. Pure Claude Ecosystem lock. **Retired by v4.3's Routing v1 reconciliation — codex is permitted again.** Reports filed 28 Apr–2 May under `(claude)` / `(cowork)` remain compliant historical artifacts; new dispatches MUST use v4.3's `Agent` string.

**What changed in v4.1 (18 Apr 2026, SUPERSEDED):** added mandatory `(cli)` parenthetical. Solved persona-label confusion. **Retired by v4.2 then v4.3.**

**Every dispatch has exactly two parts. Em dashes (`—`), not hyphens (`-`).**

**Part 1 — Bold metadata header** (markdown bold, OUTSIDE and ABOVE the code block, on its own line):

```
**[N] — Agent — Mode — TYPE — Priority**
```

Field spec:
- `[N]` — sequential number in square brackets across this dispatch (`[1]`, `[2]`, `[3]` …).
- `Agent` — **exactly one of the 16 canonical Routing v1 strings:** `{Codex XHigh | Codex High | Opus Max Effort | Sonnet} - {LEAD | AUDITOR | COO | NARRATIVE}`. Cased exactly. Hyphen separator (not em dash) between model and role. Examples: `Sonnet - LEAD`, `Codex XHigh - AUDITOR`, `Opus Max Effort - COO`, `Codex High - NARRATIVE`. The Notion brief's `Agent` select MUST match this string verbatim. The bridge maps it to the executor command via `spawn_sequence._MODEL_KEYWORDS`. **Legacy strings retained transitionally** (`XHigh / High / Medium - X`, plain `Opus - X`, `Sonnet - LEAD (legacy)`) — do NOT use for new briefs.
- `Mode` — exactly one of: `Parallel` (runs concurrently with its sibling dispatches), `Sequential` (must wait on prior brief in this dispatch), `Standalone` (single brief, no siblings). Capitalised. **See Mode Selection Rule below — same-repo briefs MUST be Sequential.**
- `TYPE` — the brief family, UPPERCASE: `INV`, `BUILD`, `QA`, `FIX`, `INVESTIGATE-REGRESS`, `MARKETING`, `SEO`, `OPS`, `DOCS`. Matches the first token of the BRIEF-ID inside the block.
- `Priority` — exactly one of: `P0`, `P1`, `P2`. P0 = launch-blocking, P1 = this-week, P2 = post-launch.

**Routing v1 model-selection guidance (read [Notion canonical](https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08) before drafting):** Sonnet is the default executor (70-80% of work). Escalate to Codex High for mechanical (grep/scripts/test harness/log parse), Opus Max Effort for judgement (algo/brand/launch gates/adversarial review), Codex XHigh for hard code root-cause (concurrency/cache/DB/runtime, post-Sonnet-failure deep fix). Do NOT default to the strongest model.

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

**[3] — Opus Max Effort - AUDITOR — Standalone — INV — P0**

```
INV-DISPATCH-SYSTEM-DEBUG-SWEEP-01 — Bridge pattern detector audit 2026-05-02
https://www.notion.so/353d9048d73c8124b28ed86236bd910d
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

**Canonical example (multi-brief wave):**

**[1] — Codex XHigh - LEAD — Parallel — INV — P0**

```
INV-EDGE-RANKING-CONCURRENCY-01 — Diamond/Gold ranking instability under load 2026-05-02
https://www.notion.so/abc123
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

**[2] — Sonnet - LEAD — Sequential — BUILD — P1**

```
BUILD-CARD-TEMPLATE-MY-MATCHES-01 — My Matches Card Template 2026-05-02
https://www.notion.so/def456
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

**[3] — Codex High - AUDITOR — Sequential — QA — P2**

```
QA-CALL-SITE-MAP-CARD-RENDERER-01 — Map all card_renderer.render() callers 2026-05-02
https://www.notion.so/ghi789
NOTION_TOKEN: ntn_REPLACE_WITH_NOTION_TOKEN
Execute this brief.
```

**Pre-send self-check (mandatory — run before every dispatch):**
1. Is the header line bold markdown and OUTSIDE the code block? ✅/❌
2. Does the header use em dashes (`—`), not hyphens? ✅/❌
3. Is the number in brackets (`[3]`, not `3`)? ✅/❌
4. **Is the `Agent` token exactly one of the 16 canonical Routing v1 strings** (`{Codex XHigh | Codex High | Opus Max Effort | Sonnet} - {LEAD | AUDITOR | COO | NARRATIVE}`)? Hyphen separator between model and role. Cased exactly. ✅/❌
5. **Does the Agent in the header match the `Agent` select on the Notion brief verbatim?** ✅/❌
6. Does the header end with a Priority (`P0`/`P1`/`P2`)? ✅/❌
7. Inside the block: BRIEF-ID line → URL → `NOTION_TOKEN:` → `Execute this brief.` — in that order? ✅/❌
8. Is the token label exactly `NOTION_TOKEN:` (not `Use notion API token:`)? ✅/❌
9. Are there any lines outside the 4 canonical ones? ❌ (should be no)
10. **Mode selection check:** for every brief marked `Parallel`, did you confirm it targets a DIFFERENT repo from every other `Parallel` sibling in this wave? Same-repo `Parallel` is a violation — downgrade the later one(s) to `Sequential`. ✅/❌
11. **Routing v1 fit check:** is this the cheapest/fastest model that can safely complete the task? Have you applied the escalation triggers in [MODEL-ROUTING.md §4](https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08)? ✅/❌

Any ❌ → dispatch is wrong. Fix before sending. No exceptions.

**Violation:** Any dispatch not matching this format will be rejected by Paul on sight. Every dispatching agent (LEAD, COO, any other lead) re-reads this section before every dispatch.

---

### Agent Report — Filename & Header Schema (LOCKED 2 May 2026 PM — Routing v1 reconciliation)

**Why:** Reports must echo the dispatch's `Agent` string verbatim so dispatcher and executor agree on which model+role ran the brief. Routing v1 collapses the prior `Agent` (CLI taxonomy) + `Model` (AI model) split into a single canonical string from the 16-option set.

**Agent taxonomy — Routing v1 LOCKED 2 May 2026:**

The `Agent:` field in every report MUST exactly match the dispatch header's `Agent` token, drawn from the 16 canonical Routing v1 options:

| Model | LEAD | AUDITOR | COO | NARRATIVE |
|---|---|---|---|---|
| Codex XHigh | ✅ | ✅ | rare | rare |
| Codex High | ✅ | ✅ | ✅ | rare |
| Opus Max Effort | ✅ | ✅ | ✅ | ✅ |
| Sonnet (default) | ✅ | ✅ | ✅ | ✅ |

**Legacy strings retained transitionally** (in-flight briefs from before Routing v1; do NOT use for new dispatches):
- `XHigh / High / Medium - X` (Codex-cutover-era, 1 May 2026)
- `Opus / Opus Max Effort / Sonnet - X` (pre-cutover Claude legacy)
- Pure-Claude v4.2 `claude` / `cowork` CLI tags

**Not allowed in the `Agent:` field:** any persona standalone (`Dataminer`, `AUDITOR`, `LEAD`, `COO`), any nickname, any non-canonical combination, any CLI tag (`(claude)`, `(codex)`).

**Report filename schema:** `<agent-slug>-<BRIEF-ID>-<YYYYMMDD-HHMM>.md`
- `<agent-slug>` — Routing v1 string lowercased and hyphenated (`sonnet-lead`, `codex-xhigh-auditor`, `opus-max-effort-coo`, `codex-high-narrative`). The bridge accepts the canonical mixed-case form too if you prefer.
- `<BRIEF-ID>` — exact ID from the dispatch block line 1.
- `<YYYYMMDD-HHMM>` — UTC timestamp. SAST offset noted in report body.

Example: `opus-max-effort-auditor-INV-DISPATCH-SYSTEM-DEBUG-SWEEP-01-20260502-0940.md` ✅

**Report body — first 6 lines, exact order:**

```
# <BRIEF-ID> — <outcome>
**Wave:** <BRIEF-ID>
**Agent:** <one of the 16 canonical Routing v1 strings>
**Date:** YYYY-MM-DD
**Status:** Complete | Blocked | Escalated
**Routing fit:** <one sentence — why this model was the right cheapest/fastest fit per Routing v1>
```

The `Routing fit` line is new in v4.3 and required per [MODEL-ROUTING.md §6](https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08). One sentence. Triggers escalation review if absent.

**Brief template (dispatchers must embed verbatim in the Notion page body):**

> **Report filing — mandatory**
> After completion, file your report at:
> - Filename: `<agent-slug>-<BRIEF-ID>-<YYYYMMDD-HHMM>.md` (slug = lowercased Routing v1 string with hyphens, e.g. `sonnet-auditor`, `codex-xhigh-lead`).
> - First 6 lines of body must be the canonical header (`# …`, `**Wave:**`, `**Agent:**`, `**Date:**`, `**Status:**`, `**Routing fit:**`).
> - The `Agent:` field MUST match the dispatch header's `Agent` token exactly — same as the Notion brief's `Agent` select.
> - Push to Agent Reports Pipeline via `push-report` (see SO #35).
> - One-sentence `Routing fit` justification mandatory per Routing v1 §6.

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
