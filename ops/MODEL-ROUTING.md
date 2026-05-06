# MzansiEdge Model Routing v1 — LOCKED 2 May 2026

**Status:** LOCKED 2 May 2026 (Paul). Supersedes Pure Claude Ecosystem v4.2 (28 Apr 2026) AND Codex 5.5 Cutover (1 May 2026 PM). Both prior locks RETIRED — this is the canonical model routing for MzansiEdge.  
**Audience:** every Cowork lead (DEV TEAM LEAD / COO / AUDITOR), every dispatched executor, every brief author.  
**Notion canonical:** https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08 — if a conflict arises, Notion wins.

---

## COMPACT ROUTING REFERENCE (v1 4-model routing matrix)

| Role | Use for |
|---|---|
| Sonnet default | ordinary execution — bounded fixes, docs, reports, normal briefs |
| Codex High mechanical | acceleration, call-site search, test harnesses, log parsing, scripts |
| Opus Max judgement | synthesis, adversarial review, algorithm calibration, launch signoff |
| Codex XHigh hard code root-cause | deep runtime bugs, concurrency, high-blast-radius investigation |

---

## CORE RULE

**Do not choose the strongest model by default.** Choose the cheapest/fastest model that can safely complete the task to launch-grade quality. Escalate only when the task has high ambiguity, high blast radius, interacting root causes, weak evidence, or major product/brand/algorithm consequences.

---

## 1. MODEL ROLES

### A. Codex XHigh (Codex 5.5 highest reasoning effort)

The hardest code-and-runtime problems where deep reasoning plus codebase execution matter.

**Best for:** thorny Telegram bot bugs with multiple possible causes; state/routing bugs where user journey, DB writes, cache, Telegram handlers, and async timing interact; root-cause investigations after Sonnet/Codex High has failed or produced uncertainty; architecture-level refactors in the bot; concurrency bugs, duplicate bot/process bugs, cache stampedes, DB lock contamination; high-risk surgical fixes where one bad patch can destabilise production; interpreting messy Telethon OCR/transcripts + logs + code paths together; final review before merging a high-blast-radius runtime change.

**Do NOT use for:** simple greps; routine patches; content writing; standard website/social tasks; first-pass implementation when Sonnet can handle it; broad QA report formatting after evidence is already clear.

**Escalation trigger:** use Codex XHigh when we have already gathered evidence and the question is *"What is the true root cause and safest code-level fix?"*

**Default owner:** DEV TEAM LEAD; sometimes AUDITOR for algorithm/runtime adjudication.

### B. Opus 4.7 Max Effort

The hardest judgement, synthesis, adversarial review, and product-quality reasoning.

**Best for:** high-stakes algorithm judgement; edge-quality calibration; narrative accuracy/richness review where facts, tone, commercial impact, and responsible-gambling risk interact; adversarial review of a proposed fix (*"Will this really solve the class of bug?"*); deciding whether evidence is sufficient to ship; interpreting QA reports and converting them into a ranked fix backlog; complex brand/product strategy where bad messaging could damage trust; reviewing system memory/docs for contradictions; designing testing schemas, acceptance criteria, and launch gates.

**Do NOT use for:** mechanical implementation; grep-heavy repo exploration; simple copywriting; routine social posts; basic Telethon execution; scripts that Codex can write faster.

**Escalation trigger:** use Opus Max when the question is *"What is the correct judgement, priority, risk interpretation, or launch-grade standard?"*

**Default owner:** AUDITOR for algorithm/system health/documentation; DEV TEAM LEAD for adversarial review; COO only for high-stakes brand/launch positioning.

### C. Sonnet

The default execution model.

**Best for:** first-pass debugging; bounded implementation; routine bot fixes; normal Claude Cowork briefs; practical UX review; website/content updates; brand-compliant copy with clear constraints; Notion task updates; documentation updates; normal QA classification; summarising evidence into clear reports; producing structured handoff briefs.

**Do NOT use alone for:** unresolved root-cause bugs after one failed attempt; high-blast-radius production changes; final algorithm signoff; thorny concurrency/runtime defects; launch/no-launch judgement; major architecture decisions.

**Escalation trigger:** start with Sonnet. Escalate if it is uncertain; it proposes a band-aid; tests fail after its fix; evidence conflicts; the failure class could affect revenue, trust, data integrity, or launch readiness.

**Default owner:** all three Cowork roles.

### D. Codex High (and Codex X-High mechanical sibling)

Fast codebase acceleration and mechanical engineering work.

**Best for:** grep-heavy code tracing; finding all call sites; mapping function dependencies; locating raw sqlite connections, duplicate handlers, stale imports, dead code; writing scripts; generating test harnesses; Telethon runner improvements; log parsers; OCR/transcript extraction helpers; mechanical patches with low ambiguity; parallel "second route" inspection while Sonnet owns the primary fix.

**Do NOT use as sole authority for:** high-stakes product judgement; algorithm calibration; narrative quality judgement; launch signoff; complex root-cause synthesis where evidence is contradictory.

**Escalation trigger:** use Codex High when the task is *"Search, map, script, patch, verify, or produce evidence fast."*

**Default owner:** DEV TEAM LEAD for code; AUDITOR for QA tooling/system health; COO only for website/tooling automation.

---

## 2. ROLE-BASED ROUTING

### DEV TEAM LEAD

Owns: Telegram bot core coding, runtime behaviour, bug fixing, builds, implementation, deployment verification.

**Default path:**
1. Sonnet — primary implementer for bounded fixes.
2. Codex High — parallel trace/grep/script/test support.
3. Codex XHigh — deep root-cause + safest fix when the problem is thorny or high-blast-radius.
4. Opus Max — adversarial review when the question is whether the fix is truly sufficient.

**Use Codex XHigh for:** duplicate bot/process bugs; Telegram async/routing state bugs; DB lock and cache stampede bugs; warm path still slow after normal fix; navigation triggering recomputation; user-facing runtime instability; multi-file refactor with production risk.

**Use Opus Max for:** *"Is this fix actually safe?"* / *"Are we solving the real class of bug?"* / *"Should this block launch?"* / *"Are the acceptance criteria strong enough?"*

**Use Sonnet for:** ordinary patches; handler updates; small UI fixes; simple tests; docs linked to code changes.

**Use Codex High for:** call-site maps; test harnesses; Telethon tooling; log extraction; mechanical patches; repo-wide checks.

**Rule:** if Sonnet fails once on a serious runtime bug, escalate. Do not grind through repeated Sonnet attempts.

### COO

Owns: marketing, website, social, brand execution, content calendar, launch ops, Notion marketing workflows.

**Default path:**
1. Sonnet — default content/operator model.
2. Opus Max — high-stakes brand, launch positioning, offer architecture, or major campaign narrative.
3. Codex High — website/WordPress/automation scripting support.
4. Codex XHigh — rarely used, only for complex website/tooling code problems.

**Use Sonnet for:** daily posts; LinkedIn targets; Quora answers; website copy updates; blog drafts; Notion task formatting; standard brand checks; launch checklists.

**Use Opus Max for:** homepage hero repositioning; subscription pitch; brand bible conflicts; sensitive responsible-gambling language; major campaign architecture; *"does this sell without overpromising?"*; premium narrative work.

**Use Codex High for:** website technical checks; schema/SEO snippets; WordPress automation helpers; broken Make/n8n pipeline diagnostics; analytics/debug scripts.

**Use Codex XHigh only for:** complex website build/debug tasks where code/runtime reasoning matters more than marketing judgement.

**Rule:** COO should not spend Opus Max on routine posts. Save it for messaging that defines the brand or materially affects conversion/trust.

### AUDITOR

Owns: edge algorithm, system health, documentation, memory system, QA evidence, regression discipline, launch gates.

**Default path:**
1. Sonnet — normal audit/report/update work.
2. Codex High — data extraction, scripts, test evidence, log/DB probes.
3. Opus Max — algorithmic judgement, evidence synthesis, launch-grade signoff.
4. Codex XHigh — code-level algorithm/runtime investigation when implementation behaviour must be traced.

**Use Opus Max for:** edge algorithm calibration review; deciding whether Diamond/Gold/Silver/Bronze behaviour makes sense; narrative accuracy and confidence discipline; audit synthesis after Telethon runs; launch/no-launch recommendations; documentation contradiction review; deciding severity and commercial risk.

**Use Codex High for:** extracting edge samples; building QA scripts; parsing Telethon transcripts; log correlation; health check probes; regression test scaffolding; data integrity checks.

**Use Codex XHigh for:** algorithm implementation bugs; edge ranking instability under concurrency; signal scoring bugs; DB/cache/runtime interactions affecting algorithm truth; code-level root cause behind a failed health check.

**Use Sonnet for:** ordinary documentation updates; simple system health summaries; test report drafting; memory hygiene; routine audit checklists.

**Rule:** AUDITOR is the final judge for *"is the system telling the truth?"* but DEV TEAM LEAD owns code changes needed to fix it.

---

## 3. TASK-TYPE ROUTING MATRIX

| Task | Primary | Escalate to |
|---|---|---|
| Telethon OCR QA execution | Codex High | Codex XHigh if OCR/transcript/log/code evidence conflict; Opus Max if severity/launch-impact question. Oversight: AUDITOR Sonnet |
| Telethon QA report synthesis | AUDITOR Sonnet | Opus Max for final exec summary, severity ranking, launch gates |
| Runtime bug investigation | DEV TEAM LEAD Sonnet + Codex High parallel trace | Codex XHigh for thorny root cause; Opus Max for final safety challenge |
| Surgical bot patch | Sonnet (+ Codex High for call sites/tests) | Codex XHigh if high blast radius or failed once |
| Bigger bot build/refactor | Planning: Opus Max if architecture complex. Implementation: Sonnet. Support: Codex High | Final review: Codex XHigh or Opus Max depending on whether risk is code-level or judgement-level |
| Edge algorithm investigation | AUDITOR Opus Max for judgement, Codex High for data | Codex XHigh or DEV TEAM LEAD Sonnet for code trace/fix |
| System health / monitoring | AUDITOR Sonnet, Codex High for probes | Codex XHigh for root cause; Opus Max if launch-impacting |
| Documentation / memory | AUDITOR Sonnet, Codex High for mechanical updates | Opus Max for contradiction review |
| Website / marketing | COO Sonnet | Opus Max for high-stakes positioning; Codex High for technical issue; Codex XHigh for complex website runtime |
| Social media / content | COO Sonnet | Opus Max for premium brand/campaign concept. Do NOT use Codex XHigh unless code/tooling is involved |

---

## 4. ESCALATION LAWS

**Sonnet → Codex XHigh when:** the bug survived one serious fix attempt; the issue crosses async handlers, DB, cache, Telegram, or runtime process state; logs and user-visible behaviour disagree; the fix could destabilise production; the code path is hard to reason about; a warm path is still slow; concurrency creates duplicate work or unstable output.

**Sonnet → Opus Max when:** judgement matters more than code execution; the question is *"is this good enough?"*; the risk is commercial, brand, algorithmic, or launch-level; evidence is ambiguous; multiple agents disagree; a proposed fix may be technically correct but product-wrong.

**Use Codex High immediately when:** the task needs repository search; the task needs all call sites; the task needs a script or test harness; the task needs log parsing; the task is mechanical and parallelisable.

**Do NOT escalate when:** the task is routine; a clear known fix exists; Sonnet can complete it with tests; the work is pure formatting/content; the output is low-blast-radius.

---

## 5. COST DISCIPLINE

Treat premium model usage as a launch-quality accelerator, not a default comfort blanket.

**Default spend posture:**
- Sonnet handles 70–80% of normal Cowork execution.
- Codex High handles mechanical acceleration and codebase search.
- Opus Max handles high-stakes judgement and adversarial review.
- Codex XHigh handles the hardest code/runtime reasoning.

Use the expensive models when they prevent: repeated failed cycles; bad architecture; false launch confidence; algorithmic embarrassment; runtime instability; product trust damage.

---

## 6. REQUIRED OUTPUT FORMAT FOR AGENTS

Every agent must state:
1. Model used.
2. Why that model was appropriate.
3. Evidence inspected.
4. Decision made.
5. What remains uncertain.
6. Whether escalation is needed.
7. Exact next action.

**For code tasks, also include:** files changed; tests run; logs checked; deployment/restart status if applicable; rollback risk.

**For audit tasks, also include:** severity; reproducibility; commercial impact; fix class; retest condition.

---

## 7. FINAL PRINCIPLE

> **Sonnet executes. Codex High accelerates. Codex XHigh solves hard code truth. Opus Max judges hard product/system truth. Do not confuse these roles. Do not let expensive models do cheap work. Do not let cheap models make high-stakes calls alone.**

---

## 8. CANONICAL AGENT-SELECT TAXONOMY (Notion Briefs DB + Pipeline DS)

Two active model levels × four roles = 8 active options as of 3 May 2026 (BUILD-DEV-STANDARDS-V4.4-REVIEW-GATE-01 / SO #45 — Codex Review Gate). Codex XHigh and Codex High executor rows are RETIRED — see §10 below.

| Model | LEAD | AUDITOR | COO | NARRATIVE |
|---|---|---|---|---|
| Codex Max Effort | ✅ | ✅ | rare | rare |
| Codex High | ✅ | ✅ | ✅ | rare |
| Opus Max Effort | ✅ | ✅ | ✅ | ✅ |
| Sonnet (default) | ✅ | ✅ | ✅ | ✅ |

**Bridge dispatch mapping** (`spawn_sequence._agent_cmd`):
- `Codex XHigh - X` → `codex --profile xhigh`
- `Codex High - X` → `codex --profile high`
- `Opus Max Effort - X` → `claude --model opus --effort max`
- `Sonnet - X` → `claude --model sonnet`

---

## 9. DEPRECATIONS

| Deprecated | Reason | Replacement |
|---|---|---|
| Pure Claude Ecosystem v4.2 (28 Apr 2026) | Hybrid Codex + Claude is now canonical | This doc |
| Codex 5.5 Cutover (1 May 2026 PM) — "Codex is the ONLY executor" | Reversed — Sonnet & Opus are valid Claude executors for the right work | This doc |
| SO #44 "Codex 5.5 is the ONLY executor for dispatched briefs" | Superseded by routing v1 | New SO #44 (Routing v1 binding rule — see CLAUDE.md) |
| `Medium - X` agent options | Codex Medium not in routing brief; collapsed into Codex High | `Codex High - X` |
| `Opus - X` (plain Opus, non-max) | Routing brief uses only Opus Max Effort | `Opus Max Effort - X` |
| `XHigh - X` naming | Replaced with explicit "Codex Max Effort - X" for clarity | `Codex Max Effort - X` |

---

## 10. CODEX REVIEW GATE (LOCKED 4 May 2026, v4.5; amended 6 May 2026)

Routing v1 pivot (v4.5, 4 May 2026 — supersedes v4.4, 3 May 2026): Codex stops being a primary executor in hybrid dispatch. Claude (Sonnet | Opus Max Effort) executes; Codex reviews via `/codex:review --wait` (standard, default) or `/codex:adversarial-review --wait <focus>` (adversarial, DISCRETIONARY) at the end of every code-touching brief, before mark_done.sh. Pure-codex dispatch is the 6 May 2026 amendment: when Codex is the executor, the review gate is a fresh inline `codex exec` sub-agent (`codex --profile xhigh exec`) per `FIX-SO45-CODEX-INLINE-SUBAGENT-01`, not the slash-command/plugin path. Locked under SO #45.

### Lifecycle (one extra mandatory step per brief)

After commit + push, before mark_done.sh: (1) if `DISPATCH_MODE=hybrid`, run `/codex:review --wait` (or `/codex:adversarial-review --wait <focus>` when explicitly declared) on the wave branch; (2) if `DISPATCH_MODE=pure-codex`, run `codex --profile xhigh exec "<review prompt>"` as a fresh inline sub-agent; (3) if blockers / `needs-changes`, address with additional commits + push, then re-run; (4) only proceed to mark_done.sh when review returns no blockers; (5) include the review summary verbatim under `## Codex Review` for hybrid or `## Codex Sub-Agent Review` for pure-codex; (6) state `Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt`.

### Review modes

- Hybrid standard: `/codex:review --wait` — default for Claude-executed briefs. Catches functional correctness, regressions, contract drift, gate coverage.
- Hybrid adversarial: `/codex:adversarial-review --wait <focus text>` — DISCRETIONARY. Invoked only when: (a) brief AC explicitly sets `review_mode: adversarial-review` with focus text, (b) standard hybrid review output recommends escalation, or (c) Paul override. Never auto-fired from trigger match alone.
- Pure-codex standard: `codex --profile xhigh exec "<review prompt>"` — default for Codex-executed briefs. This is the `FIX-SO45-CODEX-INLINE-SUBAGENT-01` lock event: fresh process, fresh context, synchronous stdout, no slash-command/plugin dependency.
- Pure-codex adversarial: same `codex exec` mechanism with adversarial prompt framing when AC explicitly declares `review_mode: adversarial-review` or a hard trigger applies.

### Adversarial-review mandatory triggers (narrowed 6 → 3 in v4.5)

- New runtime path handling money or payments. (KEPT)
- New runtime path handling auth or settlement. (KEPT)
- Migrations that are not rollback-safe. (KEPT)
- MOVED TO ADVISORY: Concurrency-sensitive code (locks, queues, async handlers, scrapers).
- MOVED TO ADVISORY: Any change touching the dispatch system, bridge, or worktree-runner.
- MOVED TO ADVISORY: Any narrative/cache surface that ships to premium-tier users.

### Brief authoring rule

Every brief AC block MUST explicitly declare the review mode: `"review_mode: review | adversarial-review"`. For adversarial-review, focus text is also required. Implicit adversarial from trigger match alone is NOT permitted (v4.5 change).

### Report format

Every report MUST include the review section for its dispatch mode: `## Codex Review` for hybrid slash-command output, or `## Codex Sub-Agent Review` for pure-codex `codex exec` stdout. Include the review summary verbatim and an explicit `Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt`. Reports without this section are INCOMPLETE and reopen the brief.

### Bootstrap exemption

BUILD-CODEX-PLUGIN-INSTALL-AND-VERIFY-01, BUILD-DEV-STANDARDS-V4.4-REVIEW-GATE-01, and BUILD-DEV-STANDARDS-V4.5-REVIEW-GATE-NARROW-01 are the ONLY three exempt briefs.

### Active vs Retired Agent set (post v4.4)

Active 8: Sonnet - LEAD | Sonnet - AUDITOR | Sonnet - COO | Sonnet - NARRATIVE | Opus Max Effort - LEAD | Opus Max Effort - AUDITOR | Opus Max Effort - COO | Opus Max Effort - NARRATIVE.

Retired 8 (RETIRED 3 May 2026 in hybrid dispatch — Codex XHigh/Codex High are no longer primary Claude-bridge executor selections; hybrid uses `/codex:review --wait`, while pure-codex dispatch uses the fresh `codex exec` sub-agent path from `FIX-SO45-CODEX-INLINE-SUBAGENT-01`): Codex XHigh - LEAD/AUDITOR/COO/NARRATIVE | Codex High - LEAD/AUDITOR/COO/NARRATIVE.

### Why

Sonnet-LEAD's commit-discipline pattern (multiple SO #41 violations Apr-May 2026) showed that pre-commit testing alone catches mechanical errors but not architectural risks (race conditions, auth gaps, data-loss windows, migration-rollback safety). The Codex review gate adds adversarial second-pair-of-eyes before any merge becomes irreversible.

*Locked 3 May 2026. Owner: Paul. Re-read at session start by every Cowork lead before drafting any code-touching brief.*

---

*Locked 2 May 2026. Owner: Paul. Re-read at session start by every Cowork lead before drafting any brief.*
