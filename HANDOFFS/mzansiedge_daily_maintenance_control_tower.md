# MzansiEdge Daily Maintenance Control Tower

**Purpose:** Replace noisy arbiters, scattered Telegram alerts, and vague monitoring with a disciplined daily maintenance system that checks the product, surfaces true issues, creates fix briefs, and keeps Paul out of technical noise.

**Owner:** Paul
**Primary operating base:** Claude Cowork
**Execution mode:** Cowork scheduled tasks (one Claude session per task)
**Reporting destination:** Notion daily control note + fix briefs
**Paul-facing output:** One short daily digest unless a P0/P1 issue requires escalation

**Ratified:** 7 May 2026 — saved at `~/Documents/MzansiEdge/HANDOFFS/mzansiedge_daily_maintenance_control_tower.md`. Each scheduled task pre-reads its own §.

---

## 1. Executive Summary

MzansiEdge does not need more alerts. It needs a **Daily Maintenance Control Tower**.

The system should run every morning across the five Cowork dispatchers:

1. **Edge Lead** — runtime, bot performance, user-facing functionality, backend fixes.
2. **Edge Auditor** — algorithm quality, system health, documentation, queue hygiene, daily control digest.
3. **Edge COO** — organic marketing, marketing automation, Telegram channel, paid marketing safety.
4. **Edge SEO** — existing SEO system; only reports material exceptions into the digest.
5. **Narrative Engineer** — temporary specialist for verdict/card copy accuracy and richness.

The goal is simple:

> The system should check itself, fix what can be fixed, create focused briefs for what needs work, and only interrupt Paul when user trust, revenue, runtime, or public brand safety is at risk.

The dashboard remains the passive view. Telegram alerts become exception-only.

---

## 2. Operating Philosophy

### 2.1 No more noisy monitoring

A useful maintenance system answers:

- What is broken?
- How bad is it?
- Does it affect users, money, trust, or launch readiness?
- Who owns the fix?
- Has a fix brief been created?
- Does Paul need to do anything?

If the answer to the last question is "no," Paul should not be interrupted.

### 2.2 Fix root causes, not symptoms

Every investigation must identify the likely root cause or explicitly state that the cause is still unknown and needs a follow-up brief.

Bad: "Bot was slow today."
Good: "Warm Top Edge Picks path is slow because the route is recomputing narrative/card data instead of serving cached render output. Edge Lead fix brief created."

### 2.3 Notion is the single operating surface

All maintenance outputs go into Notion: daily health note, exception list, created fix briefs, resolved items, outstanding blockers, Paul-needed decisions. Telegram is reserved for genuine exceptions.

### 2.4 One problem = one brief

If the morning checks find three issues, create three focused briefs. Do not create one mega-brief.

---

## 3. Noise Policy

### 3.1 What Paul should normally see

One daily digest:

```
MzansiEdge Daily Control — YYYY-MM-DD

Overall: GREEN / AMBER / RED

Runtime: GREEN
Algorithm: AMBER — top board thin, no strong premium push today
Narrative: GREEN
Social: GREEN
SEO: GREEN

Fixes opened:
1. Edge Lead — investigate sharp freshness lag
2. COO — repair failed LinkedIn queue

Needs Paul:
None
```

### 3.2 Immediate Paul escalation triggers

Only escalate immediately for issues that threaten users, money, product trust, or public brand safety:

- bot down · duplicate bot instance · users receiving wrong gated content · payment/subscription failure · no viable edges while marketing is scheduled · severe algorithm regression · public post with brand/legal risk · narrative materially contradicting recommendation · Telegram automation about to push unsafe content.

### 3.3 What should NOT interrupt Paul

- minor data freshness warnings · weak edge board · low cache hit rate · non-critical post failure · stale docs · non-blocking SEO warning · small formatting issue · noisy log warning without user impact.

These become Notion notes or fix briefs.

---

## 4. Severity Levels

| Level | Meaning | Paul notified? | Action |
|---|---|---:|---|
| P0 | Product is broken or actively unsafe | Yes, immediately | Stop/repair/rollback/escalate |
| P1 | High-risk affecting trust, revenue, launch readiness, or today's public output | Yes, in digest or immediately if time-sensitive | Create urgent fix brief |
| P2 | Real issue, not immediately dangerous | No direct alert | Create fix brief |
| P3 | Cleanup, drift, hygiene | No | Add to backlog or auto-fix |

### P0 examples
Bot offline · duplicate bot instance · edge cards fail to render · freemium gate leaking paid data · payment flow broken · wrong recommendation displayed · public marketing post with legal/brand violation.

### P1 examples
Sharp data stale enough to weaken today's edge quality · edge generation returns unusually few/no edges · narrative verdicts overclaim weak evidence · top edge board commercially unsafe to promote · today's scheduled social content failed · Telegram queue broken for launch-critical post.

### P2 examples
Warm paths slower than target but still usable · cache hit rate lower than expected · some scrapers stale but enough coverage remains · non-critical automation failed and can be rescheduled · SEO crawl warning.

### P3 examples
Docs drift · old fix brief stale · minor formatting issue · historical warning without recurrence · cleanup tasks.

---

## 5. Daily Morning Schedule (SAST)

| Time | Dispatcher | Task | Cowork task ID |
|---:|---|---|---|
| 06:00 | Edge Auditor | Daily System Health Gate | `control-tower-1-system-health-gate` |
| 06:20 | Edge Lead | Bot Runtime Canary | `control-tower-2-bot-runtime-canary` |
| 06:45 | Edge Auditor | Algorithm & Edge Quality Audit | `control-tower-3-edge-quality-audit` |
| 07:10 | Narrative Engineer / Edge Lead | Narrative Verdict QA | `control-tower-4-narrative-verdict-qa` |
| 07:30 | Edge COO | Social Automation Safety Check | `control-tower-5-social-automation-safety` |
| 07:50 | Edge SEO | SEO Exception Check | `control-tower-6-seo-exception-check` |
| 08:10 | Edge Auditor | Daily Control Digest | `control-tower-7-daily-control-digest` |

---

## 6. Dispatcher Responsibilities

### 6.1 Edge Auditor
**Mandate:** Own system truth, algorithm integrity, health checks, documentation hygiene, queue sanity, and final daily digest.

Escalates when: edge quality is commercially unsafe · sharp data failure affects today's product · system health is red · multiple dispatchers report failures · no clear owner exists for a serious issue.

### 6.2 Edge Lead
**Mandate:** Own bot runtime, core backend, user-facing functionality, speed, cache behavior, button flows, and technical fixes.

Escalates when: bot is down · duplicate bot instance · users hit dead ends · paid/free gates leak · runtime slowness severe · cache/pregen architecture not used correctly.

### 6.3 Edge COO
**Mandate:** Own public-facing marketing operations, organic social, Telegram channel, marketing automation, approvals, paid marketing safety, public content compliance.

Escalates when: public post about to publish with unsafe content · automation failed for launch-critical content · product state and marketing message contradict · Paul approval needed for visual asset.

### 6.4 Edge SEO
**Mandate:** Own SEO and AI-search visibility. Avoid polluting daily product workflow.

Reports only if: site down · sitemap/indexing broke · high-priority page lost visibility · AI-search/entity visibility materially changed · technical SEO failure affects launch or conversion.

### 6.5 Narrative Engineer
**Mandate:** Own verdict/card copy accuracy, recommendation quality, narrative richness, tone discipline, prevention of misleading claims. Temporary specialist role until verdict system is stable for multiple consecutive weeks.

Escalates when: verdict contradicts recommendation · weak evidence gets strong betting language · team/market/factual detail is wrong · issue repeats after prior fix · card sounds generic or commercially weak across multiple samples.

---

## 7. Scheduled Task 1 — Daily System Health Gate

**Dispatcher:** Edge Auditor · **Time:** 06:00 SAST · **Model:** Claude Sonnet · **Frequency:** Daily

**Purpose:** Decide whether the system is healthy enough for normal operation today. Canonical system truth check — other morning tasks reference this rather than running overlapping health checks.

**Checks:** bot process · no duplicate instances · cron jobs ran · scrapers fresh · sharp benchmark fresh · SA bookmaker data fresh · edge count sane · tier distribution sane · settlement healthy · DB lock errors below threshold · narrative pregen ran · cache healthy · dashboard matches CLI · existing fix briefs not stuck · no unresolved P0/P1 from yesterday.

**Output:** Notion page `Daily System Health — YYYY-MM-DD` in Pipeline DS.

**Success criteria:** clear health status · no vague warnings · every issue has severity + owner · no P2/P3 alerts to Paul · P0/P1 escalated properly.

---

## 8. Scheduled Task 2 — Bot Runtime Canary

**Dispatcher:** Edge Lead · **Time:** 06:20 SAST · **Model:** Codex CLI execution + Sonnet diagnosis · **Frequency:** Daily

**Purpose:** Prove the bot actually works for users today. Lightweight canary, not full QA.

**Daily journeys:** /start · Top Edge Picks · one Diamond/Gold edge · one Silver/Bronze edge · back-button round trip · My Matches · locked/subscription view · warm reopen · narrative spot check · dead-end scan.

**Detect:** non-response · slow paths · spinner hang · dead ends · gate leaks · narrative contradiction · DB lock during reads · cache misses · fresh LLM on user tap · duplicate compute.

**Output:** Notion page `Bot Runtime Canary — YYYY-MM-DD` with 10-journey table.

---

## 9. Scheduled Task 3 — Algorithm & Edge Quality Audit

**Dispatcher:** Edge Auditor · **Time:** 06:45 SAST · **Model:** Sonnet daily; Opus for high-stakes judgement · **Frequency:** Daily

**Purpose:** Check today's edges are believable and commercially safe.

> Would a sharp, sceptical bettor look at today's top cards and think this product is real?

**Output is COMMERCIAL not technical.** Examples:
- "Today's edge board is healthy. Premium push is safe."
- "Today's board is thin. Avoid strong premium marketing today."
- "Diamond cards look overconfident relative to evidence. Algo calibration brief opened."

---

## 10. Scheduled Task 4 — Narrative Verdict QA

**Dispatcher:** Narrative Engineer / Edge Lead · **Time:** 07:10 SAST · **Model:** Sonnet daily; Opus if repeated contradiction · **Frequency:** Daily

**Purpose:** Prevent verdict/card copy from drifting into inaccurate, generic, or overconfident output.

**Daily sample:** 3 top-tier cards · 3 mid-tier · 2 low-information · 2 stale/edge-case if present.

**Checks:** verdict matches recommendation · doesn't contradict evidence · doesn't overstate weak signals · no guarantee language · no banned phrases ("lock", "sure thing", "free money", "can't lose") · facts correct · stake language matches confidence · tone matches tier · feels premium and specific · no generic filler · no repeated robotic phrasing.

---

## 11. Scheduled Task 5 — Social Automation Safety Check

**Dispatcher:** Edge COO · **Time:** 07:30 SAST · **Model:** Sonnet · **Frequency:** Daily

**Purpose:** Make sure public marketing doesn't silently break or contradict the product. Safety check, not content creation.

**Checks:** scheduled posts exist · queued on correct platforms · Telegram queue correct · Buffer/Make/n8n flows healthy · Bitly links correct per channel · no raw URLs where Bitly required · no win guarantees · no stale bookmaker counts ("8 bookmakers" is wrong, use "all major SA bookmakers") · correct tier names · responsible gambling tone · visual posts requiring Paul approval not auto-published · paid/organic messaging matches edge board · CTA links work.

---

## 12. Scheduled Task 6 — SEO Exception Check

**Dispatcher:** Edge SEO · **Time:** 07:50 SAST · **Frequency:** Daily or weekdays

**Purpose:** Keep SEO running without adding noise to the daily product/control workflow. Report only if material.

Report if: site down · sitemap/indexing broke · high-priority page major issue · AI-search visibility materially changed · launch-critical content blocked · SEO issue affects conversion or trust.

---

## 13. Scheduled Task 7 — Daily Control Digest

**Dispatcher:** Edge Auditor · **Time:** 08:10 SAST · **Model:** Sonnet · **Frequency:** Daily

**Purpose:** Collapse all morning checks into one clean decision surface. Only daily summary Paul should normally see.

**Inputs:** Tasks 1-6 outputs · open P0/P1/P2 fix briefs.

**Format:**

```
MzansiEdge Daily Control — YYYY-MM-DD

Overall: GREEN / AMBER / RED

Runtime: GREEN — one-line summary
Algorithm: GREEN — one-line summary
Narrative: GREEN — one-line summary
Social: GREEN — one-line summary
SEO: GREEN — one-line summary

Fixes opened:
1. ...

Autofixes completed:
1. ...

Needs Paul:
None / specific concise decision

Commercial guidance:
Safe to promote premium today? YES / CAUTION / NO
```

**Digest rules:** No technical logs · no stack traces · no long explanations · no raw CLI output · no vague "needs investigation" without owner · every issue has severity + owner · "None" if Paul not needed.

---

## 14. Auto-Fix Rules

### 14.1 Agents may auto-fix without Paul

Low-risk, clearly within lane:
- reschedule failed social post · correct Bitly link · fix obvious typo or forbidden phrase · update stale Notion task status · restart non-critical failed scheduled job if safe · regenerate missing report artifact · create missing fix brief · update docs after verified change · clean stale queue item · rerun a failed check once.

### 14.2 Agents must create a fix brief instead of direct fix

Brief instead of direct fix when:
- code changes required · algorithm calibration may be affected · runtime behavior changed · cache behavior regressed · DB/concurrency issue · narrative architecture issue · paid/free gate issue · public automation failure requires workflow change · fix could affect users.

### 14.3 Agents must escalate to Paul

- user-facing product broken · public content unsafe and time-sensitive · money/subscription flow affected · legal/responsible gambling risk · visual asset needs approval · no safe default decision · product state contradicts planned marketing.

---

## 15. Weekly Deep QA System (POST-LAUNCH)

Daily checks lightweight, deeper QA weekly. **Defer until Phase 1 daily tasks have run cleanly for 2 weeks.**

- **Monday — Runtime QA** (Edge Lead) — performance, cache, UX, dead-end, runtime trust
- **Wednesday — Edge Quality Deep Audit** (Edge Auditor, Opus) — top 25 audit, calibration, draw bias, settled review, sharp benchmark
- **Friday — Narrative & Commercial Quality** (Narrative + COO) — verdict quality, premium differentiation, marketing alignment
- **Sunday — Ops Cleanup** (Edge Auditor) — stale tasks, old alerts, docs drift, queue hygiene

---

## 16. Monthly Strategic Review (POST-LAUNCH)

Review whether the maintenance system itself is working. Are alerts noisy? Real issues caught before Paul notices? Fix briefs resolving? Algo improving? Narrative quality improving? Which checks remove? Which to add?

---

## 17. What To Remove or Demote

### Remove as primary operating tools
- Telegram alerts for every warning · arbiters that comment without creating fixes · multiple overlapping watchdogs · "something may be wrong" alerts without ownership · daily tasks producing technical logs for Paul · symptom reports without root-cause classification · any alert without severity/owner/action.

### Keep
- Dashboard · P0/P1 alerts · Daily Notion control note · focused fix briefs · weekly deeper QA · monster QA schema for planned diagnostic runs.

---

## 18. Final Daily Outcome Model

**GREEN:** product healthy · bot usable · edge board acceptable · narratives safe · marketing queue safe · no Paul action needed.
> Paul sees: `Overall GREEN. No action needed.`

**AMBER:** product usable · issues found · fix briefs opened · no urgent Paul action.
> Paul sees: `Overall AMBER. Product usable. Fixes opened. No action needed from you.`

**RED:** user trust, runtime, revenue, public brand safety, or launch readiness at risk.
> Paul sees: `Overall RED. Action needed: [specific concise decision]. Recommended move: [specific recommendation].`

---

## 19. Implementation Order

### Phase 1 — Install morning schedule (DONE 7 May 2026)
Cowork scheduled tasks `control-tower-1` through `control-tower-7` installed. See §5 for the schedule.

### Phase 2 — Suppress noise
- Demote all non-P0/P1 Telegram alerts
- Route P2/P3 to Notion
- Require every alert class to have an owner and fix path
- Remove duplicate watchers (decommission `regression_arbiter.py`, `arbiter_qa.py` cron entries; consolidate `health_checker.py` cadence; disable `health-monitor-fix` Cowork task)

### Phase 3 — Add weekly deep QA (POST-LAUNCH)

### Phase 4 — Review and prune (POST-LAUNCH, +2 weeks)

---

## 20. Final Operating Model

1. **Dashboard for passive visibility.**
2. **Morning Cowork checks (`control-tower-1` through `control-tower-7`) for active diagnosis.**
3. **Notion for system memory and fix briefs.**
4. **Telegram only for true exceptions (P0/P1 only).**
5. **Paul receives one short daily control digest at 08:10 SAST.**

The system tells Paul:
- whether the product is healthy
- whether today's edges are worth promoting
- whether the bot works
- whether public marketing is safe
- what got fixed, what got briefed, whether he is needed
