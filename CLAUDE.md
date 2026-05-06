# MzansiEdge — CLAUDE.md
*Last updated 5 May 2026 (`AUDIT-DOC-SYSTEM-CLEANUP-2026-05-05`). Lock history + version bumps: [`ops/CLAUDE-CHANGELOG.md`](ops/CLAUDE-CHANGELOG.md). Latest standing orders: SO #43 (session role locks dispatch role, May 1+2), SO #45 (Codex Review Gate v4.5, 4 May), SO #46 (no time references, 4 May).*

---

> ## ⚠️ MANDATORY PRE-READS at session start
>
> 1. [`ME-Core.md`](ME-Core.md) — Five launch pillars + brief-by-brief roadmap. All work maps to a pillar. Non-negotiable.
> 2. [`ME-Core-LAUNCH-RUNBOOK.md`](ME-Core-LAUNCH-RUNBOOK.md) — Six gated steps + locked thresholds (Arbiter ≥85%, QA-BASELINE-02 ≥8/10, launch gate ≥8.5/10 rolling 3d). Threshold changes require explicit Paul override.
> 3. [Notion — Model Routing v1](https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08) (CANONICAL) · mirror: [`ops/MODEL-ROUTING.md`](ops/MODEL-ROUTING.md) — 4-model routing, role matrices, escalation laws, 16 Agent options. SO #44 binds.
> 4. [Notion — Surface & Funnel Model v5](https://www.notion.so/349d9048d73c81d79572e3b306c8df11) (CANONICAL) · mirror: [`ops/SURFACE-FUNNEL-MODEL.md`](ops/SURFACE-FUNNEL-MODEL.md) — required for any agent touching public surfaces, publishers, CTAs, Bitly, autogen, ad creative, or routing. **Wins over conflicting docs.** When a brief contradicts the model: (a) revise the brief to comply BEFORE enqueue, (b) file a follow-up DOCS brief to clean the conflicting source, (c) never dispatch the contradicting brief as-is.
> 5. (narrative/verdict/pregen work only) [Notion — Narrative Wiring Bible v1](https://www.notion.so/Narrative-Wiring-Bible-v1-2026-04-23-34bd9048d73c81f8af8ae3bfb540cc0f) · server mirror: `/home/paulsportsza/bot/ops/NARRATIVE-WIRING-BIBLE.md` — §2/§7/§8/§11 minimum before editing `narrative_spec.py` / `evidence_pack.py` / `pregenerate_narratives.py` / `_generate_verdict*` / `_generate_haiku_match_summary`. Key invariant: card image reads `verdict_html`, AI Breakdown reads `narrative_html` — two distinct columns, two paths.

> ## 🎯 SCOPE: Core 7 (LOCKED 27 April 2026 — POST-LAUNCH)
> Product covers exactly 7 league families across 3 sports. Bridge expansion (Currie Cup + Rugby Championship) activates Jun–Aug for the seasonal gap.
>
> | Sport | In-scope leagues | Bridge (Jun–Aug only) |
> |---|---|---|
> | Soccer | EPL · PSL · UCL | — |
> | Rugby | URC · Super Rugby · Six Nations | Currie Cup · Rugby Championship |
> | Cricket | IPL | — |
>
> **Out of scope:** Combat (MMA + boxing — pipeline broken, separate track), all test cricket + women's sport (FIX-EDGE-FIXTURE-BLACKLIST-01 gate), La Liga / Serie A / Bundesliga / Ligue 1 / MLS / A-League / Top 14 / ODI–T20I beyond IPL (post-Core-7 expansion).
>
> Quality compounds; coverage doesn't. UI / copy / bio / `/start` welcome must match this scope. Any league addition passes through AUDITOR Lane B placement gate first.

---

## Ops Modules (load on demand — not by default)

> **CLAUDE.md is the routing core.** Domain-specific rules live in `ops/` modules. Read the module relevant to your task — do not load all of them.

| Module | Contents | Load when |
|--------|----------|-----------|
| [`COO/STATE.md`](COO/STATE.md) | Current State, Known Issues, Process Notes, 4-phase plan | COO at session start; agents skip |
| [`COO/COO-ROLE.md`](COO/COO-ROLE.md) | Operating model, status model, 4-sweep cadence, decision principles, failure modes | COO only |
| [`COO/ROUTING.md`](COO/ROUTING.md) | Lane model, founder intake contract, mixed-topic handling, control state, worker returns | COO only |
| [`ops/DEV-STANDARDS.md`](ops/DEV-STANDARDS.md) | Briefing standards, dispatch format, agent report protocol, challenge rule, handoff protocol, crontab integrity | COO (brief creation) + all dev agents |
| [`ops/BRAND.md`](ops/BRAND.md) | Brand Bible, design tokens, logo, UVP, pricing, Copywriting DNA | Content/visual agents |
| [`ops/CONTENT-LAWS.md`](ops/CONTENT-LAWS.md) | Bitly, LinkedIn/FB/Quora laws, image production, publishing flow, fact-check, queue-first, card format | Content-producing agents |
| [`ops/SOCIAL-CALENDAR.md`](ops/SOCIAL-CALENDAR.md) | B.R.U. deployment, content pillars, image production, approval overrides (posting cadence → MARKETING-CORE.md) | Social/marketing agents |
| [`ops/TECHNICAL.md`](ops/TECHNICAL.md) | Database inventory, Edge V2, pipeline, narrative engine, monitoring, tests | Dev agents |
| [Notion](https://www.notion.so/349d9048d73c81d79572e3b306c8df11) (canonical) · [`ops/SURFACE-FUNNEL-MODEL.md`](ops/SURFACE-FUNNEL-MODEL.md) (mirror) | **🔒 CANONICAL v5 — Notion is single source of truth for surface→funnel routing.** 5-layer model (Acquisition / Discovery / Warming / Conversion / Delivery), content-type destinations, Bitly enforcement law, 30-min freshness law, Alerts vs Community split (Alerts = edge cards only; news/wraps/banter → Community), IG Story link sticker, bio router page. Supersedes any conflicting routing in any other doc. | **Mandatory re-read at session start** for any agent touching public surfaces, publishers, CTAs, Bitly links, generators, autogen templates, ad creative, or routing logic |
| [`ops/MARKETING-CORE.md`](ops/MARKETING-CORE.md) | Canonical posting playbook — 5-channel cadence, timing, weekly calendar, content rotation, compliance, paid acquisition strategy (Meta Ads dual-funnel). **Routing/destinations defer to SURFACE-FUNNEL-MODEL.md** (v5) | All agents touching content surfaces |
| [`ops/QA-RUBRIC-CARDS.md`](ops/QA-RUBRIC-CARDS.md) | Card QA scoring rubric (7 dimensions, auto-cap, Arbiter) | QA agents, Arbiter |
| [`COO/TOOLS.md`](COO/TOOLS.md) | COO tool inventory, image gen, MCPs, publisher, admin panel, asset placement | COO |
| [`COO/PAID-ADS-ROADMAP.md`](COO/PAID-ADS-ROADMAP.md) | Paid ads execution tracker — pre-reqs, 14-day build plan, brief dispatch tracker, kill criteria | COO |
| [`ops/MARKETING-ROADMAP.md`](ops/MARKETING-ROADMAP.md) | Consolidated marketing roadmap — 1-page index of all 5 marketing surfaces (ME-Core pillars, MARKETING-CORE, PAID-ADS-ROADMAP, SOCIAL-CALENDAR, SEO) | Any marketing work — classify here first |
| [`ops/SEO.md`](ops/SEO.md) | Full SEO + GEO Launch Playbook: 38-target keyword map, 5-pillar content architecture, GEO strategy (llms.txt, AI-bot robots, AI-query baseline), technical SEO audit, competitor gap analysis, link-building playbook, 90-day calendar, KPI framework, data-moat thesis. Appendix A = 23 Mar 2026 GSC baseline | SEO / content / web agents; any organic-growth or GEO work |

### Claude Skills (in-repo)

| Skill | Path | Load when |
|-------|------|-----------|
| `verdict-generator` | [`.claude/skills/verdict-generator/SKILL.md`](.claude/skills/verdict-generator/SKILL.md) | Writing, validating, or reviewing any card verdict (Diamond/Gold/Silver/Bronze). Mandatory before editing `narrative_spec.py`, the Sonnet verdict prompt, or any verdict-quality monitor. |
| `haiku-match-summary` | [`.claude/skills/haiku-match-summary/SKILL.md`](.claude/skills/haiku-match-summary/SKILL.md) | Writing, modifying, or validating Haiku match summaries on non-Edge detail cards. Mandatory before editing `_generate_haiku_match_summary()`, the Haiku 4.5 prompt, or non-Edge card QA. ZERO hallucination tolerance. |

---

## ⛔ STANDING ORDERS (universal — every session, every agent)

*Post-split 17 April 2026 PM (CLAUDE-MD-SO-SPLIT-01 Tier 1). SO #38 added 19 Apr 2026. SO #40 added 22 Apr 2026. SO #41 added 25 Apr 2026. The 15 orders below apply to EVERY Cowork session (AUDITOR / LEAD / COO) and every dispatched agent, unconditionally. Original SO numbers preserved — gaps are intentional; the 25 moved orders live in target modules (see table at the end of this section). Re-read before every response.*

1. **[SO #1]** Fix root causes, not symptoms. Trace every bug back to WHY it happened. No band-aids.
2. **[SO #2]** Notion is the only operational memory. No critical context lives in chat history, worker memory, Make/n8n logic, or ad hoc notes.
3. **[SO #5]** Workers are stateless executors. They read a brief, do one bounded task, write output back to Notion, update status, stop.
4. **[SO #11]** Re-read Standing Orders before every response. Every session re-reads its role spec and Standing Orders before responding to Paul on ANY topic. No drift.
5. **[SO #13]** One live priority at a time. Each session maintains exactly one current top priority. All other items must be explicitly queued, delegated, parked, or dropped.
6. **[SO #14]** Classify before discussing. Every new founder request is classified into a structured intake (lane, type, urgency, owner, next action) before deeper discussion.
7. **[SO #29]** Project isolation is absolute. Every lead (AUDITOR, LEAD, COO) in this workspace manages MzansiEdge ONLY. Never touch AdFurnace content. If Paul raises AdFurnace: "That's AdFurnace — switch to your AdFurnace session."
8. **[SO #30]** Line-range file ops only — no full-file reads on files >500 lines. Grep first, then targeted Read with offset/limit. Edits use Edit, never Write. **Multi-file refactor corollary (5 May 2026):** briefs touching >3 files MUST contain pre-baked OLD/NEW snippets per file in the AC body (per `ops/DEV-STANDARDS.md` § Multi-file refactor authoring discipline). Without this, agents thrash through grep+read discovery → autocompact → brief dies. (LOCKED 7 Apr 2026.)
9. **[SO #31]** One-fetch rule for briefs and Notion pages. Each agent fetches its brief page ONCE at task start; never re-fetches mid-task. Notion DB queries use property filters, not full-page fetches. Target: <1,000 tokens per Notion read. (LOCKED 7 Apr 2026.)
10. **[SO #32]** 10-turn cap per session, fresh session per brief. If a task needs >10 turns, agent stops and writes a structured handoff doc — never continues past the cap. Exception: INV briefs with Opus `--effort max` may extend to 20. (LOCKED 7 Apr 2026.)
11. **[SO #35]** Agent reports filed as children of Pipeline DS `data_source_id: "7da2d5d2-0e74-429e-9190-6a54d7bbcd23"` (name `📋 Agent Reports Pipeline`). Legacy DB `f01214d9-...` — DO NOT file there. Required props: Report=`<BRIEF-ID> — <outcome>`, Status=Complete, Wave=`<BRIEF-ID>`, Agent, Project=MzansiEdge, Date. Reports filed elsewhere are INVISIBLE — brief reopens. (LOCKED 15 Apr 2026.)
12. **[SO #37]** Plain English to Paul, every response, every turn. Lead with takeaway in one sentence. Short bullets ≤2 lines each. No verbatim logs / SQL rows / raw paths unless explicitly asked. Detail goes in Notion briefs/reports — chat is for decisions and status. Anchor: `feedback_communication_style_plain.md`. (LOCKED 18 Apr 2026.)
13. **[SO #38]** Visual QA by separate sub-agent — mandatory for every brief modifying a user-facing surface (cards, publisher output, admin/web UI, Telegram). Producing agent cannot self-certify. Telethon for Telegram, Playwright for web. Card briefs additionally require `ocr_card()` + 4 content assertions (`verdict_in_range`, `not_stub_shape`, `teams_populated`, `tier_badge_present`). Screenshots + assertion table mandatory in report. (LOCKED 19 Apr 2026.)
14. **[SO #40]** Kickoff Source Authority — every `broadcast_schedule` SELECT driving a kickoff display, alert window, or kickoff sort MUST include `source = 'supersport_scraper'` in WHERE. `source IS NULL` rows are DStv EPG broadcast slots (re-airs, highlights) — wrong by ±1h or years. Channel / logo / programme-metadata queries may span all sources. Regression guard: `tests/contracts/test_kickoff_supersport_only.py`. (LOCKED 22 Apr 2026.)
15. **[SO #41]** Approval binds commit. Cowork lead reviewing a code/data-change report MUST verify commit landed + pushed before closing. Verification block: `git log --oneline | grep <BRIEF-ID>` (≥1 hit) + `git rev-list --left-right --count HEAD...@{upstream}` (`0\t0`). If either fails: open `OPS-COMMIT-RECOVER-<BRIEF-ID>` follow-up. Anchor: `feedback_so41_approval_binds_commit.md`. (LOCKED 25 Apr 2026.)
16. **[SO #42]** Workspace lifecycle accountability — close every brief workspace upon report review via `touch ~/Documents/MzansiEdge/.cowork-state/edge_<role>/close_requests/<BRIEF-ID>` in the same response. Close is a silent verb performed; no announcement. KEEP is the exception (single `Keeping <emoji> [N/M] [<MODEL>] <BRIEF-ID> open — <reason>` line). Stuck marker (>60s old) → next-turn first line is `🛑 Stuck close marker`. (LOCKED 1 May 2026.)
17. **[SO #43]** Canonical session role for ALL dispatch. Every Cowork session has exactly ONE role (LEAD / AUDITOR / COO / NARRATIVE) set at session start. EVERY brief enqueued MUST use that role across three surfaces: (a) Notion `Agent` select = `<MODEL> - <ROLE>`, (b) `enqueue.py --role edge_<role>`, (c) Pipeline DS report `Agent` property. Cross-lane work uses Handoff Protocol (problem-statement passing only) — never enqueue under foreign role. Anchor: `feedback_so43_session_role_locks_dispatch_role.md`. (LOCKED 1 May 2026; updated 2 May 2026 for Routing v1.)
18. **[SO #44]** Model Routing v1 — pick the cheapest/fastest model that can safely complete the task to launch-grade quality. **Core rule:** Sonnet executes (default 70-80%). Codex High accelerates (mechanical: grep / scripts / test harnesses / log parsing). Opus Max Effort judges (algo / brand / launch gates / severity). Codex XHigh solves hard code root-cause (concurrency / cache / DB / runtime). Do NOT default to strongest model; do NOT let expensive models do cheap work. Canonical: [Notion](https://www.notion.so/354d9048d73c8138bf72d8ce7b768a08) · mirror: [`ops/MODEL-ROUTING.md`](ops/MODEL-ROUTING.md). 16 Agent options on Briefs DB + Pipeline DS. (LOCKED 2 May 2026.)
19. **[SO #45]** Codex Review Gate — every code-touching brief runs `/codex:review --wait` after commit + push and before `mark_done.sh`. Reports without a `## Codex Review` section showing `Outcome: clean | blockers-addressed | bootstrap-exempt` are INCOMPLETE — brief reopens. `/codex:adversarial-review` is DISCRETIONARY (v4.5) — opt-in via brief AC `review_mode: adversarial-review`. Mandatory adversarial triggers narrowed to 3: money/payments, auth/settlement, non-rollback-safe migrations. Cost rule: Opus Max Effort executor → default standard review unless adversarial explicitly justified. Detail: `ops/DEV-STANDARDS.md` v4.5 section. (LOCKED 3 May 2026 v4.4; amended 4 May 2026 v4.5.)
20. **[SO #46]** Never reference time of day, sleep, breaks, deadlines, or anything assuming Paul's clock. If Paul is typing, work is active. Banned: "tomorrow", "tonight", "morning", "before bed", "get some rest", "long day", "end of day", "fresh tomorrow", "sleep on it", "take a break", "start your day", "end your day", "while you sleep". Cron / wall-clock SAST is permitted as system data; lifestyle framing is not. Anchor: `feedback_no_time_references.md`. (LOCKED 4 May 2026.)

### Where the other 25 SOs live (moved 17 April 2026 PM)

| Target module | Moved SOs | # |
|---|---|---|
| [`ops/DEV-STANDARDS.md`](ops/DEV-STANDARDS.md) | #15 (compressed worker returns) · #18 (state change = Notion) · #19 (Sentry for coding agents) · #27 (QA-BASELINE review gate — reworded) · #33 (Notion page hygiene) · #36 (dashboard wiring same-brief) | 6 |
| [`ops/CONTENT-LAWS.md`](ops/CONTENT-LAWS.md) | #3 (skills gate) · #8 (Copywriting DNA) · #17 (Approval = Queue) · #21 (fact-check L1) · #22 (verified URLs) · #23 (zero placeholders) · #24 (verify named people) · #26 (media preview links) · #34 (sports intelligence framing) | 9 |
| [`ops/TECHNICAL.md`](ops/TECHNICAL.md) | #4 (no new Make) · #28 (health-monitor-fix) | 2 |
| [`COO/COO-ROLE.md`](COO/COO-ROLE.md) | #7 (COO generates all images) · #9 (Paul never posts) · #10 (COO knows own tools) · #12 (scheduled task MDs) · #16 (split mixed messages) · #20 (EdgeOps only) · #25 (update_content only) | 7 |
| [`ops/BRAND.md`](ops/BRAND.md) | #6 (Brand Bible canonical) | 1 |

**How to consume:** load the module relevant to your task per the Ops Modules routing table above. Module SOs are binding when the module is loaded. Universal SOs (this section) bind every session unconditionally.

---

## Quick Reference

- **Bot:** @mzansiedge_bot (token: `8635022348:AAEMK4mAXp6OY4V1arZgekCnGQn42Qs2meg`)
- **Telegram Alerts Channel:** @MzansiEdgeAlerts (chat_id: `-1003789410835`) — user-facing ONLY. **NEVER ops alerts.**
- **Telegram Community Group:** @MzansiEdge (chat_id: `-1002987429381`)
- **EdgeOps (internal):** chat_id: `-1003877525865` — ALL internal ops alerts.
- **WhatsApp Channel:** https://whatsapp.com/channel/0029VbCS3iR1dAvybnSrVD1D
- **WAHA API:** `http://37.27.179.53:3000` — API key: `30c1030c52e1475f86a0a908644d67b9`, session: `default`, Channel ID: `120363426000312677@newsletter`
- **Server:** 37.27.179.53 (SSH user: paulsportsza)
- **Domain:** mzansiedge.co.za
- **Launch:** 27 April 2026
- **Facebook:** https://www.facebook.com/people/MzansiEdge/61587769109541/
- **TikTok:** @heybru_za
- **Notion Project Memory:** https://www.notion.so/313d9048d73c818f94aadea85b5158d0
- **Marketing Ops Queue:** data_source `58123052-0e48-466a-be63-5308e793e672`
- **Agent Briefs DB:** data_source `8aa573c8-f21d-4e97-909b-b11b34892a76`
- **Agent Reports Pipeline:** data_source `7da2d5d2-0e74-429e-9190-6a54d7bbcd23`
- **Task Hub:** `31ed9048-d73c-814e-a179-ccd2cf35df1d`
- **LinkedIn Connection Ledger:** `354d9048-d73c-81ce-a37e-c0624dcfaacb` *(migrated 2026-05-02 — old 320d9048 was in trash)*
- **Quora Answered Ledger:** `320d9048-d73c-8109-bc66-ddf2c9ab5fe8`
- **Affiliate DB:** data_source `c4453c92-210d-477e-94f9-5557e4bf930b`
- **Connected Integrations:** Gmail, Notion, Sentry, ClickUp, PostHog, Ahrefs, Windsor.ai, Bitly
- **Admin Panel:** `https://mzansiedge.co.za/admin/` — Basic Auth: `admin:mzansiedge`
- **Python Publisher:** `/home/paulsportsza/publisher/` — cron `0 */3 * * *` — all 6 channels live. Full detail in [`COO/TOOLS.md`](COO/TOOLS.md).

### Lead Agent Architecture — Four Roles

Four leads own all work: **AUDITOR / LEAD / COO / NARRATIVE**. One Cowork session = exactly one role. Cowork orchestration runs on Claude (Sonnet 4.6 default; Opus Max Effort for deep reasoning). Dispatched briefs route per Routing v1.

Every lead CAN dispatch briefs (INV/BUILD/FIX/QA/OPS/DOCS) within their lane's system boundary. Cross-lane work = Handoff Protocol (problem-statement passing only — never enqueue under foreign role per SO #43). Every dispatch follows [`ops/DEV-STANDARDS.md`](ops/DEV-STANDARDS.md) §Dispatch Format v4.3.

**AUDITOR** — Keep the system honest. Two lanes:
- **Lane A — Product Truth:** data, algorithm, system health, edge performance. Dispatches INV/FIX/QA/OPS touching audit/monitoring/dashboard/edge-results/settlement/arbiter systems. Product-runtime defects elsewhere → packaged problem statements to LEAD/NARRATIVE/COO.
- **Lane B — Information Architecture & Dispatch System:** memory, role assignment, file structure, CLAUDE.md budget, SO lifecycle, dispatch infrastructure (`infra/dispatch/bridge/*`, `enqueue.py`, `mark_done.sh`, `cmux_*.py`, LaunchAgent plists, `~/.cowork-state/` machinery, promoter, Routing v1 mapping). Dispatches IA + dispatch-system FIX/BUILD/INV. Proposes edits to other-owned modules; owner ratifies.

Spec: `reference/ROLE-EDGE-AUDITOR.md`. Loads: `CLAUDE.md` + `ME-Core.md` + `ops/STATE.md` + `ops/TECHNICAL.md` + `ops/QA-RUBRIC-CARDS.md` + spec.

**LEAD** — Core product runtime: bot.py, scrapers, publisher, mzansiedge-wp. Dispatches INV/BUILD/FIX/QA touching `/home/paulsportsza/{bot,publisher,scrapers}/` or `/var/www/mzansiedge-wp/`. Owns CMUX workspace model. Converts problem statements from AUDITOR/NARRATIVE/Paul into briefs. Does not make algo-truth calls — defers to AUDITOR. Spec: `reference/ROLE-EDGE-LEAD.md` + `reference/DEV-LEAD-OPERATING-MANUAL.md`.

**COO** — Marketing: organic, paid, SEO, social publishing, founder comms, scheduled content. Dispatches MARKETING/SEO/CONTENT/OPS touching Marketing Ops Queue, social publisher cadence, brand surfaces, paid ads, Notion marketing workflows. Owns 4-sweep cadence. Does not touch algo truth. Spec: `reference/ROLE-EDGE-COO.md`. Loads: `CLAUDE.md` + `ME-Core.md` + `COO/STATE.md` + `COO/COO-ROLE.md` + `COO/ROUTING.md`.

**NARRATIVE** *(elevated to full dispatcher 2 May 2026)* — Narrative engine: `narrative_cache`, verdict pipeline (Sonnet serve-time + Haiku pregen), `narrative_spec.py`, `evidence_pack.py`, `pregenerate_narratives.py`, Haiku match summaries, voice corpus calibration. Dispatches narrative-pipeline INV/BUILD/FIX/QA. Mandatory pre-read: [Narrative Wiring Bible v1](https://www.notion.so/Narrative-Wiring-Bible-v1-2026-04-23-34bd9048d73c81f8af8ae3bfb540cc0f). Defers to AUDITOR for launch gates. Loads: `CLAUDE.md` + `ME-Core.md` + `ops/STATE.md` + Bible mirror + `.claude/skills/verdict-generator/SKILL.md` + `.claude/skills/haiku-match-summary/SKILL.md`.

**Handoff protocol (cross-lane):**
- AUDITOR → LEAD: product-runtime defect → packaged problem statement → LEAD writes brief
- AUDITOR → NARRATIVE: narrative-engine defect → problem statement → NARRATIVE writes FIX
- LEAD → AUDITOR: "re-audit this fix" after BUILD lands touching algo/data/dashboard/health
- LEAD → NARRATIVE: product-runtime change crosses into narrative_cache → handoff
- NARRATIVE → AUDITOR: launch-gate question → AUDITOR adjudicates
- AUDITOR → COO: content-surface accuracy issue → COO owns editorial fix
- COO ↔ LEAD: COO surfaces publishing defects → LEAD dispatches fix → COO verifies
- Any lead → AUDITOR (Lane B): new SO/module/dispatch change → placement gate first

Coding agents dispatched by any lead do NOT load this CLAUDE.md. They receive a self-contained brief with all context embedded.

**Pre-draft duplicate-check (28 Apr 2026):** before drafting ANY new brief, the dispatcher does a quick Pipeline DS + Briefs DB search for adjacent in-flight or recently-closed work. Surface duplicates to the requester before writing.

---

## Locked Operational Rules

**OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01** (LOCKED 28 Apr 2026): Canonical image writes (`static/qa-gallery/canonical/`) must be atomic-commit-only — never mixed with code or ops files in the same commit. Pre-commit hook enforces this via `scripts/canonical_lane_check.sh`. Emergency override: `ALLOW_CANONICAL_MIX=1` (audit-trailed, with warning).

### Rule 19 — AI Breakdown reader filters empty narrative_html
**FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01** (LOCKED): The AI Breakdown card reader (`card_data.py`, `bot.py`) must filter out matches where `narrative_html` is empty, None, or whitespace-only before display. Rows with empty `narrative_html` fall back to the instant-baseline path rather than showing a blank breakdown. This guard prevents blank AI Breakdown cards reaching users.

### Rule 21 — w82 / baseline_no_edge are valid for ALL tiers
**FIX-PREGEN-COVERAGE-DIAMOND-01** (LOCKED): The pregen coverage SELECT (`narrative_source in ("w82", "baseline_no_edge")`) is tier-agnostic — rows with `edge_tier` of gold, silver, bronze, and diamond are ALL eligible. The coverage query must NOT issue an UPDATE that restricts rows to a specific tier subset. Diamond and gold rows produced by w82/baseline_no_edge are valid pregen cache entries and must be served to users on those tiers.
