# MzansiEdge Model Usage Bible - Codex Evidence Draft

Brief: `INV-MODEL-USAGE-BIBLE-CODEX-PERSPECTIVE-01`  
Authoring model: Codex XHigh  
Date: 2026-05-06  
Status: draft for AUDITOR reconciliation, not a routing lock

## Evidence Base

This draft is deliberately empirical. It uses:

- Pipeline DS `7da2d5d2-0e74-429e-9190-6a54d7bbcd23`: 1,247 reports dated 2026-04-06 through 2026-05-06, plus a 90-day property sweep of 2,755 reports dated 2026-02-05 through 2026-05-06. Citation form: `[Pipeline: BRIEF-ID, date, agent, outcome]`.
- Briefs DB `8aa573c8-f21d-4e97-909b-b11b34892a76`: 531 briefs created 2026-04-06 through 2026-05-06. Citation form: `[Briefs DB: count/status, date range]`.
- Git logs for `bot`, `scrapers`, `publisher`, and `dispatch`: 803 commits in the 30-day window. Citation form: `[git: repo@sha, date, subject]`.
- `dispatch_promoter.log` and dispatch code: capacity, defer, input-needed, and spawn routing evidence. Citation form: `[dispatch log: line/date]` or `[code: file:function]`.
- Sentry API, org `mzansi-edge`, project `mzansi-edge`, 30-day issues. No `brief_id` tag was present in latest event tags returned by the API; correlation is by release SHA, culprit, and issue title. Citation form: `[Sentry: shortId, date range, title, release]`.
- Local locked docs: `ops/MODEL-ROUTING.md`, `ops/DEV-STANDARDS.md`, `ops/CLAUDE-CHANGELOG.md`, and `CLAUDE.md`. Citation form: `[Local: path, lines/section]`.

Observed corpus counts:

| Corpus slice | Sonnet | Opus/Opus Max | Codex High/XHigh | Haiku |
| --- | ---: | ---: | ---: | ---: |
| Pipeline reports, 30 days | 445 reports, 439 complete-like | 241 reports, 237 complete-like | 42 reports, 39 complete-like | Runtime model only, not a Pipeline executor |
| Briefs DB, 30 days | 282 briefs | 181 briefs | 47 briefs | Runtime model only |
| Git commits, 30 days | Mixed executor attribution; 803 total across 4 repos | Mixed executor attribution; high churn reviewed by Opus in INV/QA | Codex-heavy waves visible in commit subjects and review passes | Not a commit actor |

Notes:

- The Pipeline has many historical rows with blank `Agent`; I did not infer model identity where the property was blank.
- The current Routing v1 mirror says Codex executor rows are retired and Codex is the universal reviewer, but `DISPATCH_MODE=pure-codex` was activated on 2026-05-06 and forces `codex --profile xhigh` regardless of the Notion Agent field. That conflict is the reason this bible exists. `[Local: CLAUDE.md SO #44, 2026-05-06]` `[code: dispatch/cmux_bridge/spawn_sequence.py:_model_flags]`

## Section 1 (§1) - Per-Model Strong-Suite Analysis

### Sonnet 4.6

Demonstrably strong:

- High-throughput implementation. Sonnet has the largest 30-day sample: 445 Pipeline reports and 439 complete-like reports; it handled routine bot/card/publisher work at volume. `[Pipeline: 2026-04-06..2026-05-06 aggregate]`
- Bounded production fixes with clear target surface. Sonnet fixed the My Matches empty schedule cache poisoning by preventing empty-list cache writes after dual API/DB timeouts; commit `d78df1f` landed on `origin/main`. `[Pipeline: FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01, 2026-05-01, Sonnet - LEAD, Reviewed]` `[git: bot@d78df1f, 2026-05-01]`
- Alerting and concurrency-adjacent patching when scoped tightly. Sonnet shipped `FIX-ALERTS-DOUBLE-POST-DEDUP-01`, moving tier-fire Alerts from post-then-mark to claim-before-send with durable reservations and 32 focused tests passing. `[Pipeline: FIX-ALERTS-DOUBLE-POST-DEDUP-01, 2026-05-06, Sonnet - LEAD, Complete]` `[git: bot@dfebf37, 2026-05-06]`
- Cost-burn fix execution after investigation. Sonnet shipped `BUILD-SONNET-BURN-FIX-03` with five fixes, 1,732 tests passing, and a deployed bot restart after Opus diagnosed the burn class. `[Pipeline: BUILD-SONNET-BURN-FIX-03, 2026-04-20, Sonnet - LEAD, Complete]`
- Routine docs/ops fixes. Sonnet landed `FIX-DOC-SERVER-CANONICAL-MIRROR-01`, `FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01`, and multiple bridge/publisher maintenance tasks. `[Pipeline: FIX-DOC-SERVER-CANONICAL-MIRROR-01, 2026-05-05, Sonnet - AUDITOR, Complete]` `[Pipeline: FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01, 2026-05-05, Sonnet - AUDITOR, Complete]`

Demonstrably weak:

- Commit discipline without an external gate. SO #41 was created after `FIX-CLV-DEDUP-WRITE-01` was reported complete but did not land as a commit; this is explicitly recorded as a Sonnet-LEAD pattern. `[Local: ops/CLAUDE-CHANGELOG.md, 2026-04-25 SO #41 entry]`
- Context loss before push. `FIX-QA-SAFE-PYTHON3-INTERPRETER-01` required AUDITOR manual recovery because the agent "context-thrashed before push." `[Pipeline: FIX-QA-SAFE-PYTHON3-INTERPRETER-01, 2026-05-01, Sonnet - AUDITOR, Complete]`
- Poor fit for hard root-cause ambiguity without review. `INV-BOT-PERF-RANDOM-LATENCY-01` found that a one-line dispatcher fix would have been unsafe; Codex adversarial review caught overclaims around PTB concurrency, render bounds, and SQLite timeout assumptions. `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05, Opus Max Effort - LEAD, Complete]`
- Sonnet as runtime content model can burn budget. `INV-SONNET-CREDIT-BURN-01` found five independent Sonnet call sites, a 2.5x-2.7x request spike, first 402s on 2026-04-19, and no circuit breaker. `[Pipeline: INV-SONNET-CREDIT-BURN-01, 2026-04-19, Opus Max Effort - LEAD, Complete]`
- Visual QA can miss actual pixels when reduced to OCR/spec checks. `WAVE-F-OPUS-01` was rejected because the visual QA compared button OCR rather than PNG pixels, missing the glow delta; the follow-up `INV-WAVE-F-GLOW-DELTA-01` traced the missing lift. `[Pipeline: WAVE-F-OPUS-01, 2026-05-01, Opus - LEAD, Blocked]` `[Pipeline: INV-WAVE-F-GLOW-DELTA-01, 2026-05-01, Opus - LEAD, Reviewed]`

Observed cost/latency:

- Sonnet runtime verdict generation was the dominant daily LLM cost before fixes: about 700 calls/day and $6.89/day for verdicts, plus about 200 calls/day and $3.74/day for narrative polish. `[Pipeline: INV-COST-TRIPLE-AUDIT-01, 2026-04-24, Opus Max Effort - AUDITOR, Complete]`
- Sonnet execution latency is not the bottleneck for ordinary code tasks; the documented latency incidents were runtime bot architecture, not the Sonnet session itself. `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05, Opus Max Effort - LEAD, Complete]`

Confidence: HIGH. Sonnet has the largest executor sample in the 30-day Pipeline corpus and multiple incident classes.

### Opus Max Effort

Demonstrably strong:

- High-stakes diagnosis and judgement. Opus diagnosed `INV-BOT-PERF-RANDOM-LATENCY-01` as three concurrent drivers, then incorporated Codex adversarial findings into a safer fix path. `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05, Opus Max Effort - LEAD, Complete]`
- QA judgement that creates real fix work. `QA-NAVIGATION-BUTTONS-01` found three P0 nav defects and two P1 defects through live Telethon scans. `[Pipeline: QA-NAVIGATION-BUTTONS-01, 2026-05-05, Opus Max Effort - LEAD, Complete]`
- Product-quality gatekeeping. `QA-LAUNCH-NARRATIVE-DEFINITIVE-01` and `QA-LAUNCH-NARRATIVE-DEFINITIVE-02` both returned NO-GO with explicit premium contract failures and live hallucination/accuracy blockers. `[Pipeline: QA-LAUNCH-NARRATIVE-DEFINITIVE-01, 2026-04-29, Opus Max Effort - AUDITOR, Complete]` `[Pipeline: QA-LAUNCH-NARRATIVE-DEFINITIVE-02, 2026-04-29, Opus Max Effort - AUDITOR, Complete]`
- Broad system audits. `INV-SOCIAL-OPS-PIPELINE-AUDIT-01` produced a 52-issue audit, 24 dispatchable P0/P1 briefs, and a 60-cell resilience scorecard. `[Pipeline: INV-SOCIAL-OPS-PIPELINE-AUDIT-01, 2026-04-27, Opus Max Effort - AUDITOR, Complete]`
- Hard narrative/runtime archaeology. `INV-NARRATIVE-BULLETPROOF-01` found 13 leak vectors, stale live process deployment, a P0 blank-shell deep-link regression, and several CRIT verdict-quality defects. `[Pipeline: INV-NARRATIVE-BULLETPROOF-01, 2026-04-23, Opus Max Effort - LEAD, Complete]`

Demonstrably weak:

- Premium-on-premium review can destroy throughput. `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01` stacked Opus Max executor plus mandatory Codex adversarial review, burned the full Cowork window, ran 9 review rounds, and hit a Codex usage limit before a clean final round. `[Pipeline: FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01, 2026-05-04, Opus Max Effort - AUDITOR, blockers-addressed]` `[Local: ops/DEV-STANDARDS.md v4.5 rationale]`
- Opus implementation on runtime code still needs Codex review. `FIX-BOT-PERF-LATENCY-BOUNDS-01` took five Codex adversarial iterations before the DB/render timeout fix was safe enough to ship. `[Pipeline: FIX-BOT-PERF-LATENCY-BOUNDS-01, 2026-05-05, Opus Max Effort - LEAD, Complete]`
- Opus can overfit broad investigations into too much scope. `FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01` needed 6 Codex adversarial rounds and 9 commits; round 7 hit an OpenAI usage cap. `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04, Opus Max Effort - LEAD, Complete with gate-error]`
- Opus is too expensive for routine implementation and content. The locked Routing v1 already says Opus should not do mechanical implementation, grep-heavy exploration, or simple copywriting; recent cost incidents support that discipline. `[Local: ops/MODEL-ROUTING.md, Model Roles]` `[Pipeline: BUILD-DEV-STANDARDS-V4.5-REVIEW-GATE-NARROW-01, 2026-05-04, Sonnet - LEAD, Complete]`
- Opus still needs hard visual proof. The WAVE-F rejected report shows that even premium judgement fails when visual QA is OCR-only instead of pixel comparison. `[Pipeline: WAVE-F-OPUS-01, 2026-05-01, Opus - LEAD, Blocked]`

Observed cost/latency:

- The clearest measured Opus cost incident is `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01`: 1h39m wall time, 171k tokens, 7% balance left. `[Pipeline: BUILD-DEV-STANDARDS-V4.5-REVIEW-GATE-NARROW-01, 2026-05-04, Sonnet - LEAD, Complete]`
- Opus is best treated as a scarce judgement model, not the default executor. `[Local: ops/MODEL-ROUTING.md, Cost Discipline]`

Confidence: HIGH. Opus has 241 30-day Pipeline reports and multiple high-signal QA/INV incidents.

### Codex XHigh / Codex High

Demonstrably strong:

- Codebase search, call-site tracing, and mechanical fixes. `FIX-SCRAPER-WRITE-RETRY-P0-01` wrapped scraper writes with retry, passed smoke tests, and landed `8c6aa5c` on `origin/main`. `[Pipeline: FIX-SCRAPER-WRITE-RETRY-P0-01, 2026-05-02, Codex High - LEAD, Complete]` `[git: scrapers@8c6aa5c, 2026-05-02]`
- Precise template/contract alignment. `FIX-CARD-MATCH-CANONICAL-FAMILY-01` aligned two templates, ran 129 canonical/dimension contracts plus neighbouring contracts, and addressed review-detected contract drift in a follow-up commit. `[Pipeline: FIX-CARD-MATCH-CANONICAL-FAMILY-01, 2026-05-06, Codex XHigh - AUDITOR, blockers-addressed]`
- Dispatch-system archaeology. `INV-DISPATCH-SYSTEM-DEBUG-SWEEP-01` found Mac/server SOT drift, a Claude-only activity detector, 16 findings, and 6 follow-up FIX briefs. `[Pipeline: INV-DISPATCH-SYSTEM-DEBUG-SWEEP-01, 2026-05-02, XHigh - AUDITOR, Complete]`
- Reviewer value. Codex adversarial review found substantive issues in `INV-BOT-PERF-RANDOM-LATENCY-01`, `FIX-BOT-PERF-LATENCY-BOUNDS-01`, `FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01`, and `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01`. `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05, Opus Max Effort - LEAD, Complete]` `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04, Opus Max Effort - LEAD, Complete]`
- Challenge Rule discipline. Codex stopped rather than patching when brief constraints conflicted with repo reality in verdict V2 cache/caller briefs. `[Pipeline: BUILD-VERDICT-V2-CACHE-CUTOVER-AND-AUDIT-01, 2026-05-06, Codex XHigh - NARRATIVE, Blocked]` `[Pipeline: BUILD-VERDICT-V2-CALLERS-VERIFY-02, 2026-05-06, Codex XHigh - NARRATIVE, Blocked]`

Demonstrably weak:

- Codex is not a complete substitute for cross-model review. SO #45 now says pure-Codex execution must spawn a fresh `codex exec` sub-agent because `/codex:review` from Codex is redundant and has hung in background-task UX. `[Local: ops/DEV-STANDARDS.md, Pure-Codex Sub-Agent Review, 2026-05-06]`
- Broad heterogeneous docs-contract work is a poor fit without pre-flight approval. `FIX-DOCS-CONTRACT-DRIFT-RULES-19-21-SO45-01` was preflight-deferred after review found the remaining work spanned more than three production files and needed distinct judgement per file. `[Pipeline: FIX-DOCS-CONTRACT-DRIFT-RULES-19-21-SO45-01, 2026-05-06, Codex XHigh - AUDITOR, preflight-deferred]`
- Codex execution can block on missing or contradictory brief constraints. `BUILD-VERDICT-V2-CACHE-CUTOVER-AND-AUDIT-01` stopped because the live cache surface was in `bot.py` while the brief hard-gated `bot.py` as no-touch. `[Pipeline: BUILD-VERDICT-V2-CACHE-CUTOVER-AND-AUDIT-01, 2026-05-06, Codex XHigh - NARRATIVE, Blocked]`
- Codex review can hit usage ceilings on high-churn premium briefs. `FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01` hit an OpenAI usage cap after multiple adversarial rounds. `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04, Opus Max Effort - LEAD, gate-error]`
- Codex should not be the product/narrative judge. The current Routing v1 explicitly reserves product/system truth judgement for Opus and routine execution for Sonnet; Codex rows are retired as primary executor in Routing v1. `[Local: ops/MODEL-ROUTING.md, Active vs Retired Agent set]`

Observed cost/latency:

- Codex direct execution smoke passed on 2026-05-01. `[Pipeline: INV-CODEX-CUTOVER-SMOKE-01, 2026-05-01, Medium - AUDITOR, Complete]`
- Direct `codex exec --quiet` is the canonical fresh-process review pattern under pure-codex to avoid plugin/background hangs. `[Local: ops/DEV-STANDARDS.md, Pure-Codex Sub-Agent Review]`
- Codex reviewer cost is acceptable on standard reviews but can become large under adversarial loops; documented caps occurred on pregen and bridge reviews. `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04]` `[Pipeline: FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01, 2026-05-04]`

Confidence: MEDIUM-HIGH. Codex has fewer Pipeline executor rows because it was retired, but review evidence is dense and high-signal.

### Haiku 4.5

Demonstrably strong:

- Cheap routine generation and checks. `INV-COST-TRIPLE-AUDIT-01` found Haiku call sites were small cost contributors: validators at about $0.27/day, non-edge narrative at about $0.23/day, free-text/chat at about $0.06/day, and publisher captions at about $0.06/day. `[Pipeline: INV-COST-TRIPLE-AUDIT-01, 2026-04-24, Opus Max Effort - AUDITOR, Complete]`
- Non-edge card analysis can degrade gracefully. `BUILD-HAIKU-SUMMARY-WIRE-01` wired Haiku analysis into non-edge My Matches detail cards with a circuit breaker: 2 consecutive failures trigger a 5-minute cooldown and cards render without analysis. `[Pipeline: BUILD-HAIKU-SUMMARY-WIRE-01, 2026-04-16, Blocked report body]`
- Guardrail/compliance use is observable in Sentry. Sentry recorded Haiku `x.sentiment.block` warnings and `publisher.compliance.block` warnings, showing Haiku can be useful as a lightweight safety classifier. `[Sentry: MZANSI-EDGE-3F, 2026-04-07..2026-04-11, x.sentiment.block]` `[Sentry: MZANSI-EDGE-3G, 2026-04-07, publisher.compliance.block]`
- Haiku is useful as a fallback/cost reduction target when quality expectations are narrow. `INV-SONNET-BURN-05` and cache TTL work moved low-stakes paths away from Sonnet to reduce cost. `[Pipeline: INV-SONNET-BURN-05, 2026-04-21, Opus Max Effort - LEAD, Complete]` `[Pipeline: FIX-CACHE-TTL-1H-01, 2026-04-28, Opus - LEAD, Complete]`

Demonstrably weak:

- Haiku hallucinated in verdict comparison. `VERDICT-MODEL-TEST-01` compared Haiku vs Sonnet and recorded a Haiku "73%" claim that was not in verified data. `[Pipeline: VERDICT-MODEL-TEST-01, 2026-04-08, Reviewed]`
- Haiku can become expensive when the cache loop is wrong. `INV-HAIKU-SPEND-01` found the spend window matched the day Haiku became the pregen primary model plus validator deletions; cache was operationally dead. `[Pipeline: INV-HAIKU-SPEND-01, 2026-04-23, Opus Max Effort - AUDITOR, Complete]`
- `FIX-NARRATIVE-CACHE-DEATH-01` found a Haiku regeneration loop costing about $5.55 over 20 hours, or about $8.33/day, against a $0.05/1,000 cards budget. `[Pipeline: FIX-NARRATIVE-CACHE-DEATH-01, 2026-04-23, Sonnet - LEAD, Complete]`
- Sentry recorded a Haiku-related MOQ insert failure due missing `NOTION_TOKEN`, proving Haiku-authored/social paths still need normal infra validation. `[Sentry: MZANSI-EDGE-3Z, 2026-04-11, x_card_queue NOTION_TOKEN not set, release 65abaa5]`
- Haiku should not be used for premium narrative judgement. The launch QA failures were about accuracy, hallucination, and premium contract quality; those require Opus judgement, not Haiku. `[Pipeline: QA-LAUNCH-NARRATIVE-DEFINITIVE-01, 2026-04-29, Opus Max Effort - AUDITOR, NO-GO]`

Observed cost/latency:

- Haiku is cheap per call but dangerous under unbounded loops. `[Pipeline: INV-COST-TRIPLE-AUDIT-01, 2026-04-24]` `[Pipeline: FIX-NARRATIVE-CACHE-DEATH-01, 2026-04-23]`
- Haiku safety/compliance events show low-latency operational use, but the Pipeline does not expose direct per-call latency. `[Sentry: MZANSI-EDGE-3F, MZANSI-EDGE-3G]`

Confidence: MEDIUM. Haiku is not a dispatch executor; evidence is runtime-generation, validator, and Sentry evidence.

## Section 2 (§2) - Task-Class to Model Routing Matrix

Legend: PRIMARY = default executor for that task class; FALLBACK = use when primary is blocked or evidence demands escalation; AVOID = do not use as executor except emergency/manual override.

| Task class | Sonnet 4.6 | Opus Max Effort | Codex XHigh | Haiku 4.5 |
| --- | --- | --- | --- | --- |
| FIX-S, single production file | PRIMARY - high-volume routine fixes landed cleanly, e.g. `FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01`. | FALLBACK - use only if the single file encodes high-stakes judgement, e.g. payment/auth. | FALLBACK - use for one-file deep root-cause or shared utility with hard call-site reasoning. | AVOID - runtime helper only, not code executor. |
| FIX-M, 2-3 production files | PRIMARY - bounded multi-file patches like zero-text/settings and alerts dedupe succeed with tests. | FALLBACK - use when risk is architectural or launch-facing. | FALLBACK - use when the hard part is tracing contracts/callers, as in scraper write retries. | AVOID. |
| FIX-L, 4+ production files | FALLBACK - only with explicit per-file snippets/pre-flight under SO #30. | PRIMARY for planning/review, not necessarily hands-on implementation; broad audits produced reliable issue stacks. | FALLBACK for mechanical uniform changes after pre-flight; AVOID for heterogeneous docs/refactor without snippets. | AVOID. |
| BUILD | PRIMARY for bounded implementation after AC is clear. | FALLBACK/PRIMARY for architecture design or premium narrative build standard. | FALLBACK for test harnesses, call-site maps, hard code root-cause. | AVOID except runtime subcomponent. |
| INV | FALLBACK for small fact-finding and routine logs. | PRIMARY for ambiguous system/product/narrative judgement, as shown by latency, launch QA, and social pipeline audits. | PRIMARY for code archaeology, grep-heavy incident mining, and dispatch/runtime trace. | AVOID as investigator. |
| OPS | PRIMARY for routine docs, deploy notes, Notion/reporting, and server hygiene. | FALLBACK for high-risk operational decisions, e.g. launch/no-go. | FALLBACK for log parsers, dispatch bridge debugging, and mechanical evidence extraction. | AVOID. |
| DOCS | PRIMARY for mirrors, reports, small SO updates. | FALLBACK for contradiction review and canonical doctrine. | FALLBACK for grep-backed docs-contract drift; AVOID if heterogenous >3 files without pre-flight. | AVOID. |
| CONTENT | PRIMARY for ordinary copy/content with constraints. | PRIMARY for premium brand/launch positioning and sensitive responsible-gambling language. | AVOID unless content tooling/code is the task. | FALLBACK for cheap low-stakes captions only after safety gates. |
| QA | FALLBACK for routine checklists. | PRIMARY for launch-grade QA and severity ranking; found P0 nav/text/narrative defects. | PRIMARY for mechanical QA harnesses, visual diff checks, and contract searches. | FALLBACK for lightweight classifier/safety checks only. |
| NARRATIVE | FALLBACK for implementation of already-decided validator/prompt edits. | PRIMARY for narrative quality judgement and premium contract decisions. | FALLBACK for validator/code trace and deterministic corpus wiring. | AVOID for premium judgement; FALLBACK for cheap non-edge summaries with circuit breaker. |

Evidence anchors for the matrix: `[Pipeline: FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01, 2026-05-01]`, `[Pipeline: INV-SOCIAL-OPS-PIPELINE-AUDIT-01, 2026-04-27]`, `[Pipeline: QA-NAVIGATION-BUTTONS-01, 2026-05-05]`, `[Pipeline: FIX-SCRAPER-WRITE-RETRY-P0-01, 2026-05-02]`, `[Pipeline: BUILD-HAIKU-SUMMARY-WIRE-01, 2026-04-16]`, `[Local: ops/MODEL-ROUTING.md]`.

## Section 3 (§3) - Cross-Model Review Protocol

### Rotation Rule

- Sonnet executes -> Codex reviews. Sonnet's weakness is commit/context discipline and architectural blind spots; Codex review found missing callers, contract drift, race windows, and review blockers across recent waves. `[Local: ops/CLAUDE-CHANGELOG.md SO #41]` `[Pipeline: FIX-CARD-MATCH-CANONICAL-FAMILY-01, 2026-05-06]`
- Codex executes -> Opus reviews. Codex can trace code, but a competing judgement model should challenge product fit, scope, and whether a STOP is appropriate. Codex self-review is explicitly redundant under pure-codex. `[Local: ops/DEV-STANDARDS.md Pure-Codex Sub-Agent Review]` `[Pipeline: FIX-DOCS-CONTRACT-DRIFT-RULES-19-21-SO45-01, 2026-05-06]`
- Opus executes -> Codex reviews. Opus is strong at judgement but expensive and can over-scope implementation; Codex review caught concrete runtime failure modes in bridge, pregen, and latency waves. `[Pipeline: FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01, 2026-05-04]` `[Pipeline: FIX-BOT-PERF-LATENCY-BOUNDS-01, 2026-05-05]`
- Haiku never self-completes production work. Haiku outputs are runtime artifacts and must be guarded by deterministic validators plus Sonnet/Codex/Opus depending on risk. `[Pipeline: VERDICT-MODEL-TEST-01, 2026-04-08]`

Do not use Sonnet as the reviewer of Codex by default. The main documented review value comes from Codex finding concrete implementation defects and Opus finding judgement/scoping defects; Sonnet's documented weakness is precisely missing commit/architecture discipline under pressure. `[Local: ops/CLAUDE-CHANGELOG.md SO #41]` `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05]`

### Mechanism for Claude Reviewing Codex Output

Prefer a Cowork-managed review queue over an ad hoc local `claude exec` pattern for the first rollout.

Reason: `spawn_sequence.py` currently knows how to build Claude/Codex executor commands from Agent metadata, but pure-codex review needs a reviewer model that is not the same process and can file a report. A review queue preserves Notion/Pipeline auditability, SO #43 role mapping, and mark_done gating. `[code: dispatch/cmux_bridge/spawn_sequence.py:_agent_cmd]` `[Local: CLAUDE.md SO #43/SO #45]`

Prototype queue contract:

```python
@dataclass(frozen=True)
class ReviewJob:
    brief_id: str
    executor_model: str
    reviewer_model: str
    repo: str
    head_sha: str
    diff_stat: str
    risk_tags: tuple[str, ...]
    review_mode: Literal["review", "adversarial-review"]

REVIEW_ROTATION = {
    "sonnet": "codex-xhigh",
    "codex-xhigh": "opus-max",
    "opus-max": "codex-xhigh",
    "haiku": "codex-xhigh",
}

def enqueue_review_job(meta: BriefMeta, head_sha: str) -> ReviewJob:
    reviewer = REVIEW_ROTATION[normalise_model(meta.executor_model)]
    return ReviewJob(
        brief_id=meta.brief_id,
        executor_model=meta.executor_model,
        reviewer_model=reviewer,
        repo=meta.target_repo,
        head_sha=head_sha,
        diff_stat=git_show_stat(head_sha),
        risk_tags=tuple(meta.risk_tags),
        review_mode=meta.review_mode,
    )
```

Fallback subprocess if the queue is not ready:

```bash
DIFF="$(git show --stat --patch HEAD)"
claude --model opus --effort max --prompt "$(cat <<EOF
You are an independent reviewer with no prior context.
Brief: <BRIEF-ID>
Executor: Codex XHigh
Review mode: review
Diff:
${DIFF}

Output exactly:
## Cross-Model Review
Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt
Findings:
- [P0|P1|P2|P3] <file:line> - <one-line finding>
- or "none"
EOF
)"
```

The queue is preferable because it can capture review state, timeout, and report URL in Pipeline DS instead of relying on shell stdout.

### Reviewer Output Contract

Every reviewer returns:

```text
## Cross-Model Review
Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt
Reviewer: <model-role>
Reviewed commit: <sha>
Review mode: review | adversarial-review
Findings:
- [P0|P1|P2|P3] <file:line> - <description>
- or "none"
Escalation: none | adversarial-required | human-required
```

This mirrors SO #45 and adds `Reviewer`, `Reviewed commit`, and `Escalation` for cross-model accounting. `[Local: ops/DEV-STANDARDS.md Codex Review Gate]`

### Failure Modes

- Reviewer crash or CLI failure: retry once. If still failed, mark report `Outcome: gate-error`, do not mark_done unless Paul explicitly authorises or the brief is n/a-no-commits. Evidence: pregen and bridge waves hit usage/cap failures and needed explicit handling. `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04]`
- Reviewer disagreement: executor may address blockers or file an `Outcome: needs-changes` report; do not self-override. For P0/P1 disagreement, escalate to Opus Max or Paul. `[Pipeline: FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01, 2026-05-04]`
- Reviewer too slow: standard review SLA is 20 minutes for FIX-S/M/DOCS/OPS, 45 minutes for FIX-L/BUILD/INV, and 60 minutes for adversarial. After SLA, downgrade to a different reviewer only once; otherwise gate-error with evidence.
- No commits: reviewer output can be `n/a-no-commits`, as seen in investigation reports. `[Pipeline: INV-SYSTEM-HEALTH-DAILY-20260506, 2026-05-06, Opus Max Effort - AUDITOR, n/a-no-commits]`

## Section 4 (§4) - Adversarial vs Standard Review Rules

### What Shipped with Standard Review and Later Regressed

- Commit landing and push verification regressed before SO #41. `FIX-CLV-DEDUP-WRITE-01` reported complete without a landed commit. This was not an adversarial-review problem; it required a deterministic SO #41 verification block. `[Local: ops/CLAUDE-CHANGELOG.md SO #41, 2026-04-25]`
- Visual regressions shipped through OCR-only QA. `WAVE-F-OPUS-01` missed PNG glow deltas because review did not require pixel evidence. This should trigger visual sub-agent QA, not necessarily adversarial code review. `[Pipeline: WAVE-F-OPUS-01, 2026-05-01, Blocked]`
- Runtime concurrency/cache defects were under-reviewed by standard checks: My Matches cache poisoning, double-post alert dedupe, and bot latency all required race/cache-aware review. `[Pipeline: FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01, 2026-05-01]` `[Pipeline: FIX-ALERTS-DOUBLE-POST-DEDUP-01, 2026-05-06]` `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05]`

Conclusion: standard review is enough for routine changes only when deterministic gates exist. Race/cache/runtime state changes need either adversarial review or a very focused standard prompt with concurrency/cache focus.

### What Ran Adversarial and Found Nothing or Cost Too Much

- The bridge spawn/done wave triggered the v4.5 narrowing because Opus Max plus mandatory adversarial review burned the Cowork window and 171k tokens. That cost was not proportionate as a default for all dispatch-system changes. `[Pipeline: FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01, 2026-05-04]` `[Local: ops/DEV-STANDARDS.md v4.5 rationale]`
- Pregen signals/cache flush had legitimate findings, but six rounds plus a usage cap shows adversarial must be scoped by specific failure class, not "review everything." `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04]`
- Latency investigation used adversarial well: Codex caught overclaims before implementation. This is a good advisory trigger for concurrency-sensitive runtime changes. `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05]`

### Refined Trigger Set

Mandatory adversarial:

- Money/payments/auth/settlement runtime paths. Keep current hard trigger; Stitch/payment failure work touches revenue trust. `[Pipeline: BUILD-STITCH-EDGEOPS-WIRE-01, 2026-05-01]`
- Non-rollback-safe migrations or schema changes on billing/compliance/retention-critical tables. Keep current hard trigger. `[Local: ops/DEV-STANDARDS.md v4.5 hard triggers]`
- Claim-before-send, idempotency, or external side-effect dedupe for user-visible sends. Add hard trigger because duplicate Alerts required a durable claim protocol and ambiguous-send fencing. `[Pipeline: FIX-ALERTS-DOUBLE-POST-DEDUP-01, 2026-05-06]`

Advisory adversarial:

- Runtime concurrency/cache/async state changes, including PTB dispatcher changes, render timeouts, background pregen, and in-memory caches. `[Pipeline: INV-BOT-PERF-RANDOM-LATENCY-01, 2026-05-05]` `[Pipeline: FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01, 2026-05-01]`
- Premium narrative/cache writes that can ship to paying users. `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04]` `[Pipeline: QA-LAUNCH-NARRATIVE-DEFINITIVE-02, 2026-04-29]`
- Dispatch/bridge changes only when they touch spawn state, DONE detection, queue state, or process lifecycle; otherwise standard review is enough. `[Pipeline: FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01, 2026-05-04]`

Standard review:

- Single-file non-shared docs, routine templates, simple report mirrors, and low-risk content/tooling. `[Pipeline: FIX-DOC-SERVER-CANONICAL-MIRROR-01, 2026-05-05]`
- QA-only reports with no commits use `n/a-no-commits`, not adversarial. `[Pipeline: QA-NAVIGATION-BUTTONS-01, 2026-05-05]`

## Section 5 (§5) - Sticking Point Archaeology

Ranked by observed cost of incident: user-facing blast, repeated waves, token/cost burn, and commit churn.

| Rank | Sticking point | Brief/date/model | Root cause class | Better model/rule |
| ---: | --- | --- | --- | --- |
| 1 | Sonnet/OpenRouter credit exhaustion | `INV-SONNET-CREDIT-BURN-01`, 2026-04-19, Opus Max | Capability/cost architecture: five Sonnet call families, 2.5x-2.7x request spike, no circuit breaker | Opus for cost diagnosis, Sonnet for bounded fixes; rule: runtime LLM spend changes require cost budget + circuit breaker |
| 2 | Bridge spawn/done cost stack | `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01`, 2026-05-04, Opus Max | Review policy/cost: mandatory adversarial on dispatch-system change caused 9 rounds and usage limit | Standard Codex review by default; adversarial only with focus text and cost justification |
| 3 | Premium pregen signal/cache drift | `FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01`, 2026-05-04, Opus Max | Shared runtime/cache race: stale gen-write, proxy verdict cache, premium signal defer gaps | Opus plans, Codex adversarial reviews; rule: premium cache writes trigger focused adversarial |
| 4 | Narrative/cache quality collapse | `INV-NARRATIVE-BULLETPROOF-01`, 2026-04-23, Opus Max | Deploy hygiene + runtime path divergence: stale binary, blank deep-link shell, short verdict path | Opus INV first, Codex trace for call paths; rule: launch QA must check active runtime and deep links |
| 5 | Haiku cache-death loop | `INV-HAIKU-SPEND-01` and `FIX-NARRATIVE-CACHE-DEATH-01`, 2026-04-23 | Cache contract bug: reject -> DELETE -> regenerate loop, silent write failures | Opus diagnosis, Sonnet fix; rule: any LLM cache invalidation change needs cost-loop guard |
| 6 | My Matches zero-card cache poisoning | `INV-MY-MATCHES-ZERO-P0-01` and `FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01`, 2026-05-01 | Concurrency/cache: empty result cached after dual timeout | Opus/Codex diagnosis, Sonnet fix; rule: empty-list cache writes require explicit TTL/negative-cache contract |
| 7 | Alerts double-post | `INV-DOUBLE-POST-GOLD-EDGE-01` and `FIX-ALERTS-DOUBLE-POST-DEDUP-01`, 2026-05-06 | External side-effect idempotency: post-then-mark allowed duplicate send window | Sonnet can fix with Codex review; rule: claim-before-send surfaces trigger adversarial |
| 8 | Visual QA missed glow | `WAVE-F-OPUS-01`, 2026-05-01 | QA method gap: OCR/button labels did not compare PNG pixels | Codex/Playwright/visual diff sub-agent; rule: visual QA must include pixel evidence |
| 9 | DB lock cascade | `FIX-DBLOCK-RUNTIME-HOT-PATHS-01`, 2026-05-05, Sonnet | Runtime DB contention: long write txn and insufficient lock instrumentation | Sonnet for scoped fix after AUDITOR finding; rule: DB hot paths need transaction-scope evidence |
| 10 | Random bot latency | `INV-BOT-PERF-RANDOM-LATENCY-01`, 2026-05-05, Opus Max | Architecture/concurrency: PTB serialization, unbounded render, DB read blocking | Opus diagnosis + Codex challenge, then scoped implementation |
| 11 | Dispatch SOT drift | `INV-DISPATCH-SYSTEM-DEBUG-SWEEP-01`, 2026-05-02, XHigh | Infrastructure drift: Mac/server code mismatch and Claude-only activity detection | Codex XHigh for code archaeology; rule: bridge changes need parity checks before deploy |
| 12 | Sentry singleton lock flood | Sentry `MZANSI-EDGE-1W`, 2026-04-10..2026-04-12, release `77d9d03` | Infrastructure/process duplication: singleton lock held by another bot instance | Codex/Sonnet ops fix depending on code scope; rule: process lifecycle incidents need Sentry + service-state evidence |

Supporting citations: `[Pipeline: INV-SONNET-CREDIT-BURN-01, 2026-04-19]`, `[Pipeline: FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01, 2026-05-04]`, `[Pipeline: FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01, 2026-05-04]`, `[Pipeline: INV-NARRATIVE-BULLETPROOF-01, 2026-04-23]`, `[Pipeline: INV-HAIKU-SPEND-01, 2026-04-23]`, `[Pipeline: FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01, 2026-05-01]`, `[Pipeline: FIX-ALERTS-DOUBLE-POST-DEDUP-01, 2026-05-06]`, `[Pipeline: WAVE-F-OPUS-01, 2026-05-01]`, `[Sentry: MZANSI-EDGE-1W, release 77d9d03]`.

## Section 6 (§6) - DISPATCH_MODE=full-stack Spec

### Intent

`DISPATCH_MODE=full-stack` should choose the cheapest safe executor from brief metadata and file/task signatures, then auto-wire the reviewer from the cross-model rotation. It should not erase the Notion Agent field the way pure-codex does. `[Local: CLAUDE.md SO #44]` `[code: spawn_sequence.py:_model_flags]`

### Metadata Needed

The current `_agent_cmd(agent: str)` only receives the Agent string. Full-stack needs `BriefMeta`:

```python
@dataclass(frozen=True)
class BriefMeta:
    brief_id: str
    agent: str
    klass: str
    target_repo: str
    touched_paths: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()
    review_mode: str = "review"
    declared_model_override: str | None = None
```

### TASK_SIGNATURES

```python
TASK_SIGNATURES = [
    {
        "name": "payments_auth",
        "matches": {"paths": ["*stitch*", "*payment*", "*subscription*", "*auth*"]},
        "executor": "sonnet",
        "reviewer": "codex-xhigh",
        "review_mode": "adversarial-review",
        "reason": "money/auth hard trigger",
    },
    {
        "name": "runtime_concurrency_cache",
        "matches": {"paths": ["bot.py", "card_sender.py", "scripts/pregenerate_narratives.py"], "terms": ["cache", "async", "lock", "timeout", "dedupe", "claim"]},
        "executor": "opus-max",
        "reviewer": "codex-xhigh",
        "review_mode": "adversarial-review",
        "reason": "recent cache/race incidents",
    },
    {
        "name": "bounded_fix",
        "matches": {"klass": ["FIX"], "prod_file_count_lte": 3, "risk_tags_absent": ["money", "auth", "migration", "runtime-concurrency"]},
        "executor": "sonnet",
        "reviewer": "codex-xhigh",
        "review_mode": "review",
        "reason": "Sonnet high-volume routine success",
    },
    {
        "name": "grep_trace_harness",
        "matches": {"terms": ["call site", "grep", "audit", "contract", "harness", "parser"], "klass": ["INV", "QA", "FIX"]},
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "review",
        "reason": "Codex evidence mining and call-site trace success",
    },
    {
        "name": "judgement_launch_narrative",
        "matches": {"klass": ["INV", "QA", "NARRATIVE"], "terms": ["launch", "premium", "narrative", "NO-GO", "calibration", "brand"]},
        "executor": "opus-max",
        "reviewer": "codex-xhigh",
        "review_mode": "review",
        "reason": "Opus QA/judgement incidents",
    },
    {
        "name": "docs_ops_low_risk",
        "matches": {"klass": ["DOCS", "OPS"], "prod_file_count_lte": 3, "risk_tags_absent": ["dispatch-state", "review-gate"]},
        "executor": "sonnet",
        "reviewer": "codex-xhigh",
        "review_mode": "review",
        "reason": "routine docs/ops volume",
    },
    {
        "name": "content_low_stakes",
        "matches": {"klass": ["CONTENT"], "risk_tags_absent": ["premium", "responsible-gambling", "launch"]},
        "executor": "sonnet",
        "reviewer": "codex-xhigh",
        "review_mode": "review",
        "reason": "routine content execution",
    },
]
```

### Code Sketch in `spawn_sequence.py`

```python
MODEL_COMMANDS = {
    "sonnet": ["claude", "--model", "sonnet"],
    "opus-max": ["claude", "--model", "opus", "--effort", "max"],
    "codex-xhigh": ["codex", "--profile", "xhigh"],
    "codex-high": ["codex", "--profile", "high"],
}

def _resolve_full_stack(meta: BriefMeta) -> tuple[list[str], ReviewPlan]:
    if meta.declared_model_override:
        executor = normalise_model(meta.declared_model_override)
        return MODEL_COMMANDS[executor], reviewer_for(executor, meta)

    prod_file_count = count_production_paths(meta.touched_paths)
    for sig in TASK_SIGNATURES:
        if signature_matches(sig["matches"], meta, prod_file_count):
            executor = sig["executor"]
            review_mode = max_review_mode(meta.review_mode, sig["review_mode"])
            return MODEL_COMMANDS[executor], ReviewPlan(
                reviewer=sig["reviewer"],
                review_mode=review_mode,
                reason=sig["reason"],
            )

    return MODEL_COMMANDS["sonnet"], ReviewPlan(
        reviewer="codex-xhigh",
        review_mode=meta.review_mode,
        reason="safe default",
    )

def _model_flags_for_meta(meta: BriefMeta) -> list[str]:
    mode = os.environ.get("DISPATCH_MODE", "")
    if mode == "pure-codex":
        return ["codex", "--profile", "xhigh"]
    if mode == "full-stack":
        cmd, review_plan = _resolve_full_stack(meta)
        write_review_plan(meta.brief_id, review_plan)
        return cmd
    return _model_flags(meta.agent)
```

Backward-compatible wrapper:

```python
def _agent_cmd(agent: str) -> str:
    return " ".join(_model_flags(agent))

def _agent_cmd_for_meta(meta: BriefMeta) -> str:
    return " ".join(_model_flags_for_meta(meta))
```

### Reviewer Wiring

At successful commit/push time:

```python
def after_push(meta: BriefMeta, head_sha: str) -> None:
    plan = read_review_plan(meta.brief_id)
    job = enqueue_review_job(meta, head_sha, plan)
    wait_for_review(job, timeout=review_timeout(plan))
    if job.outcome == "needs-changes":
        raise ReviewBlocked(job.report_url)
    if job.outcome == "gate-error" and meta.requires_review:
        raise ReviewGateError(job.report_url)
```

### Rollout Plan

1. Shadow-only for 20 briefs: compute full-stack executor/reviewer but keep actual `DISPATCH_MODE=pure-codex`; file resolver decisions in logs. Compare against human-picked Agent. `[dispatch log: active input-needed/cap evidence, 2026-05-06]`
2. Enable for DOCS/OPS/INV no-commit and QA-only first. These are low rollback risk and expose routing accuracy.
3. Enable for FIX-S and FIX-M with standard review, excluding money/auth/migration/cache/race tags.
4. Enable runtime/cache/adversarial signatures only after review queue exists.
5. Flip default when 30 consecutive full-stack decisions have no routing override and no report missing review outcome.

## Section 7 (§7) - Migration Path

### Backward Compatibility

- Existing briefs with explicit `Agent` still work in `hybrid`; `pure-codex` continues to force Codex while the transition is active. `[code: spawn_sequence.py:_model_flags]`
- `full-stack` should preserve the Agent field as an override only when a brief explicitly declares `model_override`; otherwise it uses metadata signatures. This prevents stale Agent fields from defeating routing.
- Legacy Codex Agent values remain readable but should emit warnings, as `enqueue.py` already does. `[code: dispatch/enqueue.py ACTIVE_AGENTS/LEGACY_AGENTS]`

### Default Flip Timing

- Do not flip directly from `pure-codex` to `full-stack`.
- First flip to shadow mode after this draft is reviewed against Routing v1 and approved.
- Flip execution default only after the review queue can make Claude review Codex outputs and Pipeline reports include `## Cross-Model Review` consistently.

### Deprecation of Legacy Values

- Keep `Codex XHigh - <ROLE>` and `Codex High - <ROLE>` selectable for historical reports and in-flight rescue work.
- New briefs should use active Routing v1 values plus `risk_tags`/`klass`/file signatures; executor selection happens in full-stack resolver.
- Rename documentation language from "Codex retired" to "Codex not default primary; selected by full-stack only for grep/trace/hard code truth." This reconciles Routing v1 with pure-codex operational reality.

### Standing Order Updates Required

- Amend SO #44: add `DISPATCH_MODE=full-stack`, define shadow mode, define resolver source-of-truth, and state fallback to `hybrid`/`pure-codex` when metadata is missing.
- Amend SO #45: rename `Codex Review Gate` to `Cross-Model Review Gate`; keep Codex as default reviewer for Sonnet/Opus, but add Opus review for Codex-executed briefs.
- Amend SO #30 brief authoring: require `touched_paths`, `risk_tags`, and `klass` fields when full-stack is active; keep the >3 production-file pre-flight rule.
- Amend report filing SO #35: require `Executor model`, `Reviewer model`, and `Review outcome` properties or first-line body fields so future mining does not need free-text extraction.

### Final Proposed Rule

Sonnet executes routine work. Opus judges ambiguous, launch-grade, and premium product truth. Codex traces hard code truth and reviews concrete implementation risk. Haiku stays a guarded runtime helper. No model self-completes production work; the reviewer must be a competing model unless the brief is no-commit or bootstrap-exempt.
