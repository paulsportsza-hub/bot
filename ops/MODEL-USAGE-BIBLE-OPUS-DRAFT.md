# MzansiEdge Model Usage Bible - Opus Draft

**Brief:** `INV-MODEL-USAGE-BIBLE-OPUS-PERSPECTIVE-01`  
**Draft role:** design-synthesis perspective, independent of the Codex evidence-mining draft  
**Status:** reconciliation input, not yet canonical

This draft supersedes the shape of Routing v1, not the operational lock itself. The
current production state is still SO #44 `pure-codex` unless AUDITOR ratifies a
merged bible and updates the standing orders.

## Evidence Inspected

- `ops/MODEL-ROUTING.md`: current Routing v1 roles, escalation laws, retired Codex executor options, and Codex Review Gate v4.5 mirror.
- `ops/DEV-STANDARDS.md`: SO #45 review gate, pure-Codex inline sub-agent pattern, report filing format, and SO #30 blast-radius authoring discipline.
- `CLAUDE.md`: SO #30, SO #43, SO #44, SO #45, and SO #41 approval-binds-commit.
- `dispatch/cmux_bridge/spawn_sequence.py`: current `_agent_cmd()` / `_model_flags()` dispatch behavior and the `DISPATCH_MODE=pure-codex` override.
- `dispatch/enqueue.py`: active/legacy agent taxonomy, `VALID_REPOS`, review-mode triggers, and agent validation.
- `dispatch/dispatch_promoter.py`: queue mode promotion, INV/QA forced parallelism, same-repo sequential collision handling, and capacity gates.
- Local incident anchors from `ops/CLAUDE-CHANGELOG.md`, `ops/BRIDGE-INVARIANTS.md`, `ops/COWORK-LOCKED-MEMORY-BUNDLE.md`, `ops/NARRATIVE-WIRING-BIBLE.md`, and `reports/qa-images-zero-text-01/SUMMARY.md`.
- Companion Codex brief acceptance criteria only; no coordination and no reuse of its answer.

---

## §1 - Per-Model Strong-Suite Analysis

### Sonnet 4.6

**Design role in MzansiEdge:** default bounded executor. Sonnet should own the
ordinary flow of small and medium implementation, docs, brief drafting, standard
QA triage, and practical UI/content changes where the desired result is already
well specified. It is the right model when the system needs throughput and the
main risk is ordinary implementation error rather than deep unknown causality.

**Strength-as-weakness failure modes:**

- Sonnet optimizes for "finish the brief" and can accept local evidence too early. That maps to the `FIX-CLV-DEDUP-WRITE-01` class: report complete, tests described, but git receipt missing until SO #41 made commit/push verification load-bearing.
- It can patch visible symptoms without discovering hidden runtime layers. The `P0-WAVE-VERDICT-SONNET-RESTORE` / `INV-SONNET-BURN-05` failure was not a code diff problem first; a `.env` override silently put verdict and narrative regeneration on Haiku.
- It is vulnerable to role/process drift unless the protocol is explicit. SO #43 exists because an AUDITOR session dispatched `FIX-DBLOCK-RUNTIME-HOT-PATHS-01` as `Sonnet - LEAD`, breaking ownership surfaces.
- On high-blast-radius runtime work, Sonnet can burn cycles in discovery and asks for context that should have been pre-authored. The SO #30 revision cites `FIX-DBLOCK-RUNTIME-HOT-PATHS-01` and `FIX-BRIEF-AUTHORING-MULTIFILE-DISCIPLINE-01`.

**Structurally needed:** high-volume dispatch execution, small production fixes,
routine docs, standard QA summaries, content and website edits with clear rules.

**Substitutable:** deep runtime root cause, final launch judgement, adversarial
review, ambiguous algorithm quality calls, and any task where the right answer is
not obvious after one serious pass.

### Opus Max Effort

**Design role in MzansiEdge:** judgement authority. Opus is the model for
architectural synthesis, product/system truth, adversarial questioning, QA rubric
design, model-routing doctrine, launch-gate severity, and cases where the answer
must reconcile evidence, user trust, commercial risk, and operational cost.

**Strength-as-weakness failure modes:**

- Opus can over-invest in judgement where a mechanical patch is enough. The v4.5 review gate narrowing was driven by `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01`, where Opus Max plus mandatory adversarial review consumed the operating window for a dispatch-system class change.
- It is less efficient for grep-heavy mapping and repetitive patch application. On tasks like card canonical shell lifts or large call-site scans, Codex gives better mechanical throughput.
- It can design richer protocols than the bridge can enforce today unless it states the mechanism and failure behavior. Any full-stack proposal must account for current `_agent_cmd(agent)` receiving only the Agent string.
- It can create cost-stacking risk when paired with adversarial review by default. DEV-STANDARDS v4.5 correctly makes Opus executor + standard review the default unless adversarial is justified.

**Structurally needed:** final judgement on algorithm quality, routing doctrine,
cross-model review design, launch/no-launch calls, adversarial review of proposed
fix classes, and post-QA prioritization.

**Substitutable:** routine implementation, mechanical repository search, simple
docs, low-stakes content, and test harness scaffolding.

### Codex XHigh

**Design role in MzansiEdge:** code-truth and runtime archaeology. Codex XHigh is
best where the answer lives across files, call sites, tests, logs, async state,
DB transactions, cache behavior, and exact diffs. It is also the right fresh
reviewer for Claude-generated code because its biases differ from Claude's
language-first completion pattern.

**Strength-as-weakness failure modes:**

- Mechanical confidence can outrun governance context. Pure-Codex mode forced SO #45 to switch from plugin review to fresh inline `codex exec` because self-shaped review through the same process was redundant and had hung in background-task UX.
- Codex is excellent at "can this code work?" and weaker at "is this product/system decision correct?" It should not be sole authority for narrative quality, responsible-gambling tone, tier value proposition, or launch confidence.
- It can overfit to patchability. A bug like `P0-WAVE-VERDICT-SONNET-RESTORE` needs env/config archaeology before code change; code search alone can miss the operator layer.
- It can create false safety if it reviews its own architecture. Cross-model review exists partly because a same-family sub-agent shares too many blind spots with the executor.

**Structurally needed:** hard runtime bugs, concurrency, DB/cache contamination,
large call-site maps, migration safety review, post-Sonnet failed fixes, and
fresh review of Claude-authored code.

**Substitutable:** standard docs, content, brand judgement, routine UI copy, and
final product-quality signoff.

### Haiku 4.5

**Design role in MzansiEdge:** low-cost bounded language utility only. Haiku fits
closed-world summaries, simple classification, quick previews, and fallback text
where a mistake is cheap, reversible, and not sold as premium intelligence.

**Strength-as-weakness failure modes:**

- Cheap generation can be mistaken for acceptable generation. The `P0-WAVE-VERDICT-SONNET-RESTORE` incident showed Haiku hidden behind `.env` overrides on verdict/narrative paths, degrading every regeneration surface despite code defaults pointing to Sonnet.
- It is not suited to edge judgement, betting narrative, or premium-tier claims because MzansiEdge's trust surface depends on factual discipline and calibrated confidence.
- It needs strong closed-world contracts. The existing `haiku_preview` path in `NARRATIVE-WIRING-BIBLE.md` correctly gates banned betting language, hallucination markers, and wrong-sport terms.
- It can hide cost-driven regressions: if a cost-burn exercise changes env-level model selection, the repo diff may look clean while runtime behavior changes materially.

**Structurally needed:** only for low-risk previews/classification where the
input contract is closed and failure produces no paid recommendation.

**Substitutable:** almost everywhere else. Sonnet should own production verdict
language; Opus should judge high-stakes quality; Codex should inspect code.

---

## §2 - Task-Class to Model Routing Matrix

Legend: `PRIMARY` = default executor; `FALLBACK` = use after trigger or for a
slice of the work; `AVOID` = do not use unless Paul explicitly overrides.

| Task class | Sonnet 4.6 | Opus Max Effort | Codex XHigh | Haiku 4.5 |
|---|---|---|---|---|
| FIX-S | PRIMARY - bounded one-file fixes with clear AC are Sonnet's throughput lane. | AVOID - judgement cost rarely justified. | FALLBACK - use for hard root cause or caller scan after uncertainty. | AVOID - production code execution is outside role. |
| FIX-M | PRIMARY - 2-3 production files remain normal execution under SO #30. | FALLBACK - use when the fix class needs safety judgement. | FALLBACK - use for shared behavior, concurrency, DB/cache, or failed Sonnet pass. | AVOID - no runtime-code authority. |
| FIX-L | FALLBACK - only with explicit snippets or pre-flight and low ambiguity. | FALLBACK - architecture/safety review before execution. | PRIMARY - large runtime/call-site/root-cause fixes need code-truth depth. | AVOID - blast radius too high. |
| BUILD | PRIMARY - implement specified features and normal UX surfaces. | FALLBACK - product architecture, launch gates, and AC design. | FALLBACK - complex backend, migrations, test harnesses, or dispatch machinery. | AVOID - unless the build is a low-risk classifier/preview. |
| INV | PRIMARY - ordinary investigations, reports, and doc reconciliation. | PRIMARY - ambiguous system truth, model doctrine, launch judgement, severity ranking. | PRIMARY - evidence mining, logs, git archaeology, runtime cause tracing. | FALLBACK - narrow summarization of already-clean evidence only. |
| OPS | PRIMARY - Notion updates, reports, routine dispatch hygiene. | FALLBACK - governance doctrine or cross-lane conflict resolution. | FALLBACK - bridge, queue, CI, deployment, and automation failures. | AVOID - ops failures need traceability. |
| DOCS | PRIMARY - normal docs, mirrors, brief templates, cleanup. | FALLBACK - contradiction review and canonical doctrine. | FALLBACK - mechanical sync, grep-backed drift detection, link/callout scans. | FALLBACK - short summaries only, never canonical rules. |
| CONTENT | PRIMARY - standard copy under tone guide and clear constraints. | FALLBACK - high-stakes brand/offer/responsible-gambling language. | AVOID - use only if content task includes automation/tooling. | FALLBACK - cheap variants for non-sensitive drafts, with review. |
| QA | PRIMARY - standard QA classification and report writing. | PRIMARY - launch-grade QA synthesis, severity, and product risk. | PRIMARY - Telethon/Playwright harnesses, OCR scripts, DB/log probes. | AVOID - visual/product QA needs stronger reasoning. |
| NARRATIVE | PRIMARY - production verdict/narrative generation and ordinary rewrite. | PRIMARY - quality bar, voice doctrine, edge judgement, responsible-gambling risk. | FALLBACK - validators, cache wiring, corpus audits, serve-time gates. | FALLBACK - closed-world match preview only; avoid paid verdicts. |

Design implication: MzansiEdge should stop thinking in a single "best model"
default. The right default is a resolver that distinguishes task class, file
signature, state mutation, and review need.

---

## §3 - Cross-Model Review Protocol - Design First

### Why mandate cross-model review?

Single-model execution plus same-model sub-agent review catches some omissions,
but it does not reliably catch model-shaped blind spots. The strongest failure
classes in MzansiEdge are not syntax errors; they are mismatches between local AC
completion and system truth:

- "Complete" diverging from "committed" (`FIX-CLV-DEDUP-WRITE-01`).
- Code defaults diverging from runtime env (`P0-WAVE-VERDICT-SONNET-RESTORE`).
- Review gate mechanism diverging from actual bridge UX (`FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01`, `FIX-CODEX-REVIEW-PLUGIN-RELIABILITY-01`).
- Surface intent diverging from real user output (`QA-IMAGES-ZERO-TEXT-01`).

Cross-model review is valuable because it changes the failure lens. A Sonnet
executor tends to optimize coherent completion; Codex asks whether the diff,
callers, tests, and runtime contract actually support that completion. A Codex
executor tends to optimize patchability and mechanical coverage; Opus asks
whether the proposed contract is the right one and whether the class of bug is
actually solved. Opus tends to optimize judgement and architecture; Codex asks
whether the design is implementable in the current files and process.

### Reviewer Rotation

**Sonnet executes -> Codex reviews.** Sonnet's weak point is local sufficiency:
passing tests, plausible prose, and neat reports can still miss callers,
uncommitted work, hidden config, or contract drift. Codex is the right reviewer
because it is better at diff interrogation, call-site coverage, and mechanical
gate checks.

**Codex executes -> Opus reviews.** Codex's weak point is confident mechanical
closure. Opus should review Codex when the executor touched broad runtime logic,
dispatch rules, validators, or narrative/cache behavior, because the question is
often "did we choose the right invariant?" not only "does the patch compile?"

**Opus executes -> Codex reviews.** Opus's weak point is over-synthesis and
buildability assumptions. Codex should review Opus outputs for concrete code
shape, ambiguity a future implementer will trip on, missing file-level hooks,
and whether the protocol can actually be enforced.

**Why not Codex -> Sonnet?** Sonnet can review Codex for readability and obvious
regressions, but it is not the strongest counterweight to Codex's main weakness.
Codex needs a reviewer that challenges system intent and risk framing. Opus does
that better. Sonnet remains useful as an optional standard reviewer for low-risk
Codex mechanical work if Opus is unavailable, but it should not be the canonical
rotation for high-stakes Codex execution.

### Mechanism Proposals for Claude Reviewing Codex

**Mechanism 1: Claude subprocess/API reviewer.**

Code-touching Codex briefs would run a fresh Claude reviewer after commit + push:

```bash
DIFF=$(git show --stat --patch HEAD)
claude --model opus --effort max -p "$(cat <<EOF
You are an INDEPENDENT Opus reviewer with no prior context.
Brief: <BRIEF-ID>
Diff:
${DIFF}

Review for system intent, missing invariants, product risk, and whether the
patch solves the class of bug rather than the visible symptom.

Output:
## Claude Review
Outcome: clean | blockers-addressed | needs-changes
Findings:
- [P0|P1|P2|P3] <file:line or section:line> - <description>
- or "none"
EOF
)"
```

If the Claude CLI cannot support non-interactive prompt execution reliably, a
small wrapper should call Anthropic Messages API directly with the same contract.
To be buildable as a gate, the wrapper must own the mechanics instead of leaving
them to each executor:

- Diff selection: default to `git merge-base HEAD origin/main` -> `HEAD`; if the
  branch is already on `main`, use `git show --stat --patch HEAD`. The report
  records the exact base and head SHAs.
- Exit behavior: reviewer process exits `0` only for `Outcome: clean` or
  `Outcome: blockers-addressed`; exits non-zero for `needs-changes`, timeout,
  malformed output, or API/CLI failure.
- Persistence: stdout is written to
  `/tmp/_reviews/<BRIEF-ID>/<head-sha>-claude-review.md` and embedded verbatim
  in the agent report. The path is included in the report for audit recovery.
- Timeout: wrapper enforces the SLA budget, kills the subprocess on timeout, and
  writes a synthetic `Outcome: needs-changes` block with the timeout reason.
- Blocking integration: `mark_done.sh` or a pre-done bridge hook checks the
  report for the review block and refuses completion when the wrapper returned
  non-zero or the latest head SHA lacks a matching review artifact.

Tradeoffs:

- Pros: synchronous, enforceable, fresh-context, fits the current SO #45 shape,
  and keeps code-touching review inside the executor workflow.
- Cons: requires a reliable non-interactive Claude path or API wrapper, careful
  secret handling, stdout capture, timeout handling, and model/cost selection.
- Best fit: code-touching Codex briefs where the diff is enough context for a
  judgement reviewer.

**Mechanism 2: Cowork-managed review queue.**

Codex executors file the work into a new queue state such as `awaiting_review`
instead of directly marking done. A Cowork Opus/Sonnet session pulls the review
item, reads the brief/report/diff, writes a review result, and only then allows
`mark_done.sh`.

Tradeoffs:

- Pros: strongest true cross-model review, good for judgement-heavy INV/BUILD,
  lets Opus inspect broader Notion/report context, and avoids brittle CLI gaps.
- Cons: higher latency, more human/lead orchestration, another queue state to
  reconcile, and more risk of stuck briefs if review ownership is unclear.
- Best fit: narrative doctrine, routing, launch gates, high-stakes algorithm
  changes, and briefs where the diff alone is not enough.

**Mechanism 3: Hybrid review routing.**

Use subprocess/API review for code-touching and mechanically bounded briefs; use
Cowork-managed review for judgement-heavy briefs and doctrine. The full-stack
resolver chooses both executor and reviewer mechanism from the same signature.

Tradeoffs:

- Pros: avoids overpaying with Cowork review on small code patches while still
  giving high-judgement work the richer review it needs.
- Cons: needs precise resolver rules and report validation so agents cannot pick
  the cheaper route by habit.
- Best fit: MzansiEdge default. It matches the actual split between hard runtime
  fixes and hard judgement work.

### Reviewer Output Contract

Every reviewer, regardless of model or mechanism, returns exactly:

```markdown
## Cross-Model Review

Reviewer: <Codex XHigh | Opus Max Effort | Sonnet>
Review mode: standard | adversarial
Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt

Findings:
- [P0|P1|P2|P3] <file:line or section:line> - <description>
- none

Executor response:
- <how each finding was addressed, or why it was not a blocker>
```

`mark_done.sh` should remain forbidden until the report includes this block and
the outcome is `clean`, `blockers-addressed`, or a valid bootstrap exemption.

### Failure Modes and SLAs

- Reviewer crashes: executor retries once with the same prompt and logs stderr.
  Second crash becomes `needs-review` report status, not Complete.
- Reviewer unavailable: route to the paired fallback reviewer (`Codex -> Sonnet`
  only for low-risk mechanical work; otherwise Cowork queue).
- Reviewer exceeds SLA: standard review budget 10 minutes; judgement review
  budget 20 minutes; adversarial review budget 30 minutes. If exceeded twice,
  file an `awaiting-review-timeout` report and keep the brief open.
- Reviewer disagrees with executor: P0/P1 findings must be addressed with a new
  commit or escalated to AUDITOR. P2/P3 can be accepted with written rationale.
- Reviewer refuses because context is insufficient: executor must provide a
  smaller diff, relevant file ranges, or the report/brief excerpts. Refusal is
  not clean.

### Cost Analysis

Cross-model review adds latency and spend, but it replaces more expensive failure
recovery. MzansiEdge's costly incidents have not been "one more test would have
caught it" bugs; they have been governance, queue, hidden config, cache, and
surface-contract failures. The added cost is worth it when scoped:

- Standard code review should be cheap and bounded: one diff, one prompt, one
  output contract.
- Adversarial review should be reserved for inherently high-risk classes, not
  auto-fired from every dispatch/bridge touch.
- Cowork review should be for judgement-heavy work, not routine fixes.

The cost failure to avoid is v4.4-style stacking: premium executor plus mandatory
adversarial plus broad context for every advisory category. The design target is
mandatory cross-model review, discretionary adversarial intensity.

---

## §4 - Adversarial vs Standard Review Rules

### First-Principles Framework

A brief inherently needs adversarial review when a plausible bug crosses at least
one of these boundaries:

1. **Irreversible value boundary:** money, payments, billing, settlement, or any
   user entitlement where a single git revert cannot unwind bad external state.
2. **Authentication or identity boundary:** auth, account ownership, subscription
   identity, Telegram user identity, or privilege checks.
3. **Persistent production-data boundary:** migrations/backfills that mutate
   durable state without a deterministic rollback or audit trail.
4. **Fanout boundary:** alerts, DMs, publishes, notifications, or batch jobs where
   one bad decision multiplies across users before a human can stop it.
5. **Concurrent state boundary:** locks, queues, async handlers, cache writers,
   and reservation systems where race bugs are plausible and tests often under-
   sample interleavings.
6. **Premium trust boundary:** paid narrative, verdict, edge ranking, or card
   copy where hallucination, wrong teams, or overconfident language damages trust.
7. **Dispatch-governance boundary:** bridge, queue, review gate, report filing,
   or mark_done behavior where a process bug can make future governance lie.

The current v4.5 hard triggers map cleanly to the first three: money/payments,
auth/settlement, and non-rollback-safe migrations. That was the right cost
correction after v4.4, but the framework predicts several gaps.

### Proposed Trigger Set

**Mandatory adversarial review:**

- Money, payments, billing, subscription entitlement, checkout, refunds, or
  settlement.
- Auth, identity, user-tier authorization, or Telegram user/account binding.
- Non-rollback-safe migrations or production data backfills without a reversible
  audit trail.
- Fanout writes to users: alerts, DMs, notifications, publisher sends, or any
  "claim then send" reservation flow. `FIX-ALERTS-DOUBLE-POST-DEDUP-01` shows
  why double-send prevention is not just ordinary code correctness.
- Dispatch/review gate changes that can create false completion: `mark_done.sh`,
  report filing, queue state reconciliation, review invocation, or badge state.
  Incidents include `FIX-CLV-DEDUP-WRITE-01`, `FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01`,
  and `FIX-DISPATCH-STATUS-RECONCILER-01`.

**Advisory adversarial review:**

- Concurrency-sensitive implementation that does not cross fanout or durable
  data boundaries.
- Premium narrative/cache surface changes where standard review can inspect
  validators and sample output.
- Large refactors with snippets/pre-flight approval but no irreversible state.
- Model/env routing changes where the runtime override layer can defeat code
  defaults, as in `P0-WAVE-VERDICT-SONNET-RESTORE`.

**Standard review:**

- FIX-S and FIX-M bounded code changes with rollback-safe behavior.
- Docs and report-only INV work.
- Content changes under existing locked tone/copy rules.
- Test-only additions that do not alter shared fixtures or production contracts.

The adversarial distinction is not "important vs unimportant." It is "look for
failure as the primary job" vs "verify correctness and contract coverage." Most
briefs still need review; only a minority need hostile review.

---

## §5 - Sticking Point Archaeology

### Failure Class Taxonomy

1. **Governance receipt failures:** the report says Complete but commit, push,
   review, or Notion receipt is missing.
2. **Bridge/queue state-machine failures:** filesystem state, workspace state,
   and badge/process state disagree.
3. **Review mechanism failures:** the review gate exists in docs but the actual
   spawned environment does not run or wait for it reliably.
4. **Blast-radius/context failures:** briefs ask agents to discover too much
   across too many production files without snippets or pre-flight approval.
5. **Runtime hidden-layer failures:** env, cache, DB, or scheduled job settings
   override what code readers think is true.
6. **Concurrency/fanout failures:** duplicate sends, stale reservations, locks,
   and async interleavings require adversarial state reasoning.
7. **User-surface contract drift:** code paths keep old text or fallback behavior
   after the product contract changes.
8. **Coverage/window mismatch failures:** two correct constants or surfaces have
   incompatible horizons, so the user path is incomplete.

### Incidents and Structural Fixes

| Class | Incidents | What failed | Structural fix |
|---|---|---|---|
| Governance receipt | `FIX-CLV-DEDUP-WRITE-01` -> SO #41 | Complete report accepted without commit/push landing. | Report validation must verify git receipt before close; full-stack review contract must include commit/push evidence. |
| Governance receipt | `FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01` | Review could background and vanish without `--wait`. | Review invocation must be generated by the bridge or a shared helper, not remembered by agents. |
| Bridge state-machine | `FIX-ENQUEUE-CLEAN-STALE-ON-REQUEUE-01`, `FIX-DISPATCH-STATUS-RECONCILER-01` | Re-enqueue and reconciler state could create dual-state or orphan behavior. | Treat queue filesystem as canonical; add state-machine invariant tests for every queue transition. |
| Bridge spawn UX | `FIX-BYPASS-PERMISSIONS-ACCEPT-01-ROLLBACK`, `FIX-AGENT-AUTO-PERMISSIONS-01` | Prompt assumptions caused spawned agents to exit. | Bridge prompt handling must be modeled as runtime state, with tests for prompt order and no universal key sequences. |
| Review mechanism | `FIX-CODEX-REVIEW-PLUGIN-RELIABILITY-01`, `FIX-SO45-CODEX-INLINE-SUBAGENT-01` | Plugin review path was redundant or unreliable under pure-Codex. | Cross-model reviewer must be a fresh process with synchronous stdout and no background UX. |
| Blast radius | `FIX-DBLOCK-RUNTIME-HOT-PATHS-01`, `FIX-BRIEF-AUTHORING-MULTIFILE-DISCIPLINE-01`, `FIX-SO30-BLAST-RADIUS-01` | Large discovery-mode edits thrashed and failed. | Keep SO #30 production-file threshold; use pre-flight reviewer for >3 prod files without snippets. |
| Runtime hidden layer | `P0-WAVE-VERDICT-SONNET-RESTORE`, `INV-SONNET-BURN-05` | `.env` model overrides put verdict/narrative paths on Haiku despite Sonnet defaults. | Model routing checks must inspect env/runtime config, not only code defaults. |
| Coverage/window mismatch | `FIX-AI-BREAKDOWN-COVERAGE-01`, `INV-AI-BREAKDOWN-COVERAGE-01` | Premium Edge Picks lookahead exceeded pregen horizon, hiding AI Breakdown. | Routing for narrative/cache changes should require an invariant map: producer horizon vs consumer horizon. |
| User-surface drift | `QA-IMAGES-ZERO-TEXT-01`, `FIX-ZERO-TEXT-GUIDE-TOPICS-01`, `FIX-ZERO-TEXT-EDGE-PICKS-EMPTY-TIER-01` | Product contract moved to image-only, but cold/empty branches still sent text. | User-facing surface changes need route-complete QA, not just happy-path visual checks. |
| Concurrency/fanout | `FIX-ALERTS-DOUBLE-POST-DEDUP-01` series | Multiple commits were needed to fence claims, stale leases, retries, unknown sends, and DM state. | Alerts/DM fanout should always route to Codex XHigh execution plus adversarial review. |
| Cost stacking | `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01`, `BUILD-DEV-STANDARDS-V45-REVIEW-GATE-NARROW-01` | Mandatory adversarial stacked with Opus Max on advisory classes. | Separate mandatory cross-model review from adversarial intensity; require written adversarial trigger. |
| Role ownership | `FIX-DBLOCK-RUNTIME-HOT-PATHS-01` role-tag violation -> SO #43 | AUDITOR-authored brief tagged LEAD, breaking ownership surfaces. | Full-stack resolver must select model, not role; role remains session-locked and cannot be inferred from files. |

The common structural issue is not weak agents. It is missing mechanical
enforcement at boundaries where humans and models are both likely to assume the
previous step happened. The bible should therefore route both executor and
reviewer, and also specify which receipts make completion true.

---

## §6 - `DISPATCH_MODE=full-stack` Spec

### Decision Shape

Use a hybrid resolver: first classify the brief by explicit metadata, then refine
with path/signature rules, then apply risk escalation. A pure class-only resolver
is too blunt (`FIX` can mean one HTML card or alert fanout). A pure path resolver
is also too blunt (`bot.py` can mean copy, cache, auth, payments, or navigation).
The right shape is:

1. Read `klass`, `brief_id`, `target_repo`, `Agent`, `review_mode`, declared
   touched files, and risk tags from the queue YAML / Notion metadata.
2. Apply non-negotiable risk signatures first.
3. Apply file/task signatures.
4. Fall back to class defaults.
5. Attach reviewer model and review mechanism from the executor and risk class.

### Proposed Signatures

Signature matching must be deterministic:

- Paths are repo-relative POSIX paths from queue metadata, never absolute local
  paths. `target_repo` supplies the repo root.
- `brief_terms` are lowercased tokens from brief ID, title, AC headings, and risk
  tags. They are not extracted from arbitrary chat history.
- Lists inside a match key are OR conditions. Different keys contribute score,
  not an implicit AND, unless the signature sets `required_keys`.
- Scores are explicit: `risk_tags=100`, `brief_terms=40`, `paths=35`,
  `repos=25`, `klass=15`. Mandatory-boundary signatures add `+1000`.
- `signature_matches()` returns a numeric score. `signature_priority()` sorts by
  mandatory boundary first, then score, then declared signature order. Equal top
  scores call `ambiguous_route()`.
- `risk_tags` is the canonical metadata key. Any legacy `risk` value is
  normalized into `risk_tags` at enqueue time.
- Review modes normalize through one helper:

```python
def normalize_review_mode(raw: str) -> Literal["standard", "adversarial"]:
    value = (raw or "review").strip().lower()
    if value in {"review", "standard"}:
        return "standard"
    if value in {"adversarial-review", "adversarial"}:
        return "adversarial"
    raise ValueError(f"unknown review mode: {raw!r}")
```

```python
TASK_SIGNATURES = [
    {
        "name": "payments_auth_settlement",
        "matches": {"paths": ["*subscribe*", "*payment*", "*checkout*", "*settlement*"],
                    "brief_terms": ["payment", "checkout", "auth", "settlement", "subscription"]},
        "executor": ["codex", "--profile", "xhigh"],
        "reviewer": "opus-max-effort",
        "review_mode": "adversarial",
        "mechanism": "claude-review",
    },
    {
        "name": "alerts_dm_fanout",
        "matches": {"brief_terms": ["alert", "dm", "double-post", "notification", "fanout"]},
        "executor": ["codex", "--profile", "xhigh"],
        "reviewer": "opus-max-effort",
        "review_mode": "adversarial",
        "mechanism": "claude-review",
    },
    {
        "name": "dispatch_bridge_governance",
        "matches": {"repos": ["dispatch"],
                    "paths": ["dispatch_promoter.py", "enqueue.py", "cmux_bridge/*.py", "mark_done.sh"]},
        "executor": ["codex", "--profile", "xhigh"],
        "reviewer": "opus-max-effort",
        "review_mode": "adversarial",
        "mechanism": "claude-review",
        "mandatory_boundary": "dispatch_false_completion",
    },
    {
        "name": "model_doctrine_or_launch_judgement",
        "matches": {"klass": ["INV", "DOCS"],
                    "brief_terms": ["bible", "routing", "launch gate", "doctrine", "synthesis"]},
        "executor": ["claude", "--model", "opus", "--effort", "max"],
        "reviewer": "codex-xhigh",
        "review_mode": "standard",
        "mechanism": "codex-review",
    },
    {
        "name": "card_or_telegram_surface",
        "matches": {"paths": ["card_templates/*", "card_pipeline.py", "bot.py"],
                    "brief_terms": ["card", "telegram", "image", "button", "surface"]},
        "executor": ["claude", "--model", "sonnet"],
        "reviewer": "codex-xhigh",
        "review_mode": "standard",
        "mechanism": "codex-review",
        "extra_gate": "visual-qa-subagent",
    },
    {
        "name": "narrative_cache_verdict",
        "matches": {"paths": ["bot.py", "scripts/pregenerate_narratives.py", "card_data.py"],
                    "brief_terms": ["narrative", "verdict", "cache", "pregen", "quality gate"]},
        "executor": ["codex", "--profile", "xhigh"],
        "reviewer": "opus-max-effort",
        "review_mode": "standard",
        "mechanism": "claude-review",
    },
    {
        "name": "routine_docs_content",
        "matches": {"klass": ["DOCS", "CONTENT"], "risk_tags": ["low"]},
        "executor": ["claude", "--model", "sonnet"],
        "reviewer": "codex-xhigh",
        "review_mode": "standard",
        "mechanism": "codex-review",
    },
]
```

### `_agent_cmd` Code Sketch

The current `_agent_cmd(agent: str)` cannot implement full-stack well because it
does not receive `klass`, file paths, repo, or risk tags. The bridge should pass
a metadata object parsed from the queue YAML.

```python
@dataclass(frozen=True)
class BriefExecutionMeta:
    brief_id: str
    klass: str
    target_repo: str
    agent: str
    files: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()
    review_mode: str = "review"
    title: str = ""


def _agent_cmd(agent: str, meta: BriefExecutionMeta | None = None) -> str:
    mode = os.environ.get("DISPATCH_MODE", "hybrid")

    if mode == "pure-codex":
        return "codex --profile xhigh"

    if mode == "full-stack":
        if meta is None:
            raise ValueError("full-stack dispatch requires BriefExecutionMeta")
        route = resolve_full_stack_route(meta)
        return shlex.join(route.executor_cmd)

    # Backward-compatible Routing v1 / hybrid path.
    return shlex.join(_model_flags(agent))


def resolve_full_stack_route(meta: BriefExecutionMeta) -> Route:
    manual = manual_model_override(meta.agent, meta.risk_tags)
    if manual:
        return manual

    requested_review = normalize_review_mode(meta.review_mode)
    matches = [
        (signature_matches(sig, meta), sig)
        for sig in TASK_SIGNATURES
        if signature_matches(sig, meta) > 0
    ]
    if not matches:
        return class_default_route(meta.klass, requested_review)

    matches.sort(key=lambda item: signature_priority(item[1], meta, item[0]), reverse=True)
    top_score, top = matches[0]
    if len(matches) > 1 and signature_priority(matches[0][1], meta, matches[0][0]) == signature_priority(matches[1][1], meta, matches[1][0]):
        return ambiguous_route(meta, [matches[0][1], matches[1][1]], requested_review)
    return route_from_signature(top, requested_review)
```

`ambiguous_route()` should choose the safer executor (usually Codex XHigh for
code/state risk, Opus for judgement) and set `review_mode=adversarial` only if
one of the mandatory adversarial boundaries is present. It must also log the
ambiguity into the kickoff prompt so the executor and reviewer know why the route
was chosen.

### Cross-Model Reviewer Wiring

The route object should include reviewer instructions:

```python
@dataclass(frozen=True)
class Route:
    executor_cmd: list[str]
    reviewer: Literal["codex-xhigh", "opus-max-effort", "sonnet"]
    review_mode: Literal["standard", "adversarial"]
    mechanism: Literal["codex-review", "claude-review", "cowork-review"]
    rationale: str
```

The spawn kickoff should include:

- resolved executor command and rationale;
- required reviewer model and mechanism;
- exact review command template;
- forbidden completion rule: no `mark_done.sh` until review block is in report;
- adversarial focus text when applicable.

For later hard enforcement, `mark_done.sh` or the bridge should query the report
by `Wave=<BRIEF-ID>` and reject done if the review block is absent or has
`Outcome: needs-changes`.

### Ambiguity and Unavailability

- If a brief matches two models equally, choose the model aligned to the highest
  risk boundary: irreversible state -> Codex XHigh; product/launch judgement ->
  Opus; routine execution -> Sonnet.
- If the picked model is unavailable, downgrade only within the same competency
  axis: Codex XHigh -> Codex High for mechanical low-risk work; Opus -> Sonnet
  only for non-launch, non-adversarial judgement; Sonnet -> Codex XHigh only if
  the task is code-heavy, otherwise queue.
- If the resolver lacks file metadata, use class defaults but add a report
  warning. Repeated missing metadata should fail enqueue validation.

### Rollout Plan

1. **Shadow mode:** compute `full_stack_route` for every queued brief but keep
   current `pure-codex` execution. Log predicted executor/reviewer/rationale.
2. **Replay validation:** run the resolver against recent completed briefs with
   known outcomes: `FIX-ALERTS-DOUBLE-POST-DEDUP-01`, `QA-IMAGES-ZERO-TEXT-01`,
   `FIX-SO45-CODEX-INLINE-SUBAGENT-01`, `FIX-SO30-BLAST-RADIUS-01`, and card
   canonical waves. AUDITOR checks whether the route would have reduced risk.
3. **Low-risk live pilot:** enable full-stack only for DOCS, INV, QA, and FIX-S
   without payments/auth/fanout.
4. **Stateful pilot:** add dispatch and narrative/cache tasks with standard
   cross-model review.
5. **Default flip:** switch SO #44 default only after route logs show stable
   model choice, reports include cross-model review blocks, and no pilot brief
   closes without commit/push/review receipts.

---

## §7 - Migration Path

### Backward Compatibility

- Existing `DISPATCH_MODE=pure-codex` remains valid as an emergency/simple mode:
  all dispatched briefs execute as `codex --profile xhigh`.
- Existing `DISPATCH_MODE=hybrid` remains valid for explicit Agent routing via
  `_MODEL_KEYWORDS`.
- `full-stack` must not remove the Notion `Agent` property immediately. Keep it
  as a display/override/audit field while adding route metadata to the queue YAML.
- Existing active Agent values (`Sonnet - <ROLE>`, `Opus Max Effort - <ROLE>`)
  continue to validate. Legacy Codex executor values should remain warnings
  until all in-flight briefs are done.

### Default Flip Timing

Do not flip directly from pure-Codex to full-stack. Flip only after:

- resolver shadow logs exist for a representative sample of recent brief classes;
- queue YAML includes `klass`, `target_repo`, touched files or declared file
  signatures, review mode, and risk tags;
- report filing validation can detect the cross-model review block;
- the bridge kickoff injects the resolved reviewer mechanism; and
- AUDITOR has reconciled the Codex evidence draft with this Opus design draft.

### SO #44 Text Delta

Replace the current two-mode text with:

```markdown
**[SO #44]** Model Usage Bible routing - dispatch supports three modes via
`DISPATCH_MODE` on the bridge plist.

`pure-codex` - emergency/simple mode. Every dispatched brief routes to
`codex --profile xhigh` regardless of declared Agent.

`hybrid` - Routing v1 compatibility mode. The Notion `Agent` select drives
executor command via `spawn_sequence._agent_cmd`.

`full-stack` - canonical mode once ratified. The bridge resolves executor and
reviewer from brief class, target repo, file signatures, risk tags, review mode,
and explicit override. Role remains session-locked under SO #43; full-stack may
choose model but may not change LEAD/AUDITOR/COO/NARRATIVE ownership.

Cowork orchestration sessions always run on Claude. Cross-model review under
SO #45 is mandatory in all modes.
```

### SO #45 Text Delta

Replace the Codex-only review framing with:

```markdown
**[SO #45]** Cross-Model Review Gate - no code-touching or doctrine-changing
brief self-completes. After commit + push and before `mark_done.sh`, a competing
model reviews the output with fresh context.

Reviewer rotation:
- Sonnet executor -> Codex XHigh reviewer.
- Codex executor -> Opus Max Effort reviewer.
- Opus Max Effort executor -> Codex XHigh reviewer.

Review mechanisms:
- `codex --profile xhigh exec` for Codex reviewing Claude output.
- Use the server-supported canonical form above; the current CLI does not
  support the retired quiet flag.
- Claude subprocess/API reviewer for Claude reviewing Codex output, or Cowork
  review queue when the judgement context exceeds a diff.
- Hybrid selection: code-touching bounded briefs use subprocess/API review;
  judgement-heavy briefs use Cowork-managed review.

Required report block:
`## Cross-Model Review`
`Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt`

P0/P1 findings block `mark_done.sh` until addressed or escalated to AUDITOR.
Adversarial review is mandatory only for the current hard-trigger classes plus
any ratified fanout/governance additions; otherwise standard review is mandatory.
```

### Migration Risks

- **Resolver opacity:** if agents cannot see why a model was chosen, they will
  distrust or bypass the route. Put rationale in kickoff and reports.
- **Metadata gaps:** current `_agent_cmd(agent)` lacks enough context. If queue
  YAML does not carry file signatures/risk tags, full-stack will collapse into
  brittle class defaults.
- **Review deadlocks:** adding Cowork review queue without ownership and timeout
  rules will create stuck briefs. The route must select mechanism and fallback.
- **Cost rebound:** full-stack could recreate v4.4 cost stacking if adversarial
  intensity is tied to broad advisory categories. Keep cross-model mandatory and
  adversarial selective.
- **Role drift:** model resolver must never infer role from file path. SO #43
  role ownership remains separate from model choice.
- **False completion:** until `mark_done.sh` or report validation checks review
  blocks, agents can still close early. The migration should treat review receipt
  enforcement as part of the rollout, not a later nice-to-have.

### Final Recommendation

Ratify full-stack as a resolver-plus-review system, not just a model picker. The
model choice matters, but MzansiEdge's repeated failures happened at boundaries:
commit receipt, review receipt, queue truth, runtime env, cache horizon, fanout
state, and user-surface contracts. The new bible should route work to the model
best suited to the task and route review to the model best suited to challenge
that executor's blind spot.
