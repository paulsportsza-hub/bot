# MzansiEdge Model Usage Bible — Canonical

**Status:** RATIFIED 6 May 2026 — supersedes Routing v1 (2 May 2026) and `DISPATCH_MODE=pure-codex` operational lock (6 May 2026 morning).
**Reconciles:** `INV-MODEL-USAGE-BIBLE-CODEX-PERSPECTIVE-01` (evidence-mining, 30-day Pipeline corpus 1,247 reports + 803 commits) + `INV-MODEL-USAGE-BIBLE-OPUS-PERSPECTIVE-01` (design synthesis). Both draft sources retained at `ops/MODEL-USAGE-BIBLE-CODEX-DRAFT.md` and `ops/MODEL-USAGE-BIBLE-OPUS-DRAFT.md` for evidence backstop.

**Canonical routing:** AUDITOR Cowork session reconciliation, 6 May 2026, against the two drafts above and current dispatch infrastructure (`spawn_sequence.py`, `enqueue.py`, `dispatch_promoter.py`).

---

## §1 — Per-Model Strong-Suite Analysis

### Sonnet 4.6

**Design role:** default bounded executor. Sonnet owns the routine flow of small/medium implementation, docs, brief drafting, standard QA triage, and content/UI changes where the desired outcome is well-specified. Highest sample size in the 30-day corpus (445 Pipeline reports, 282 briefs).

**Strong:** bounded production fixes (`FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01` shipped clean), alerting + concurrency-adjacent patching when scoped tightly (`FIX-ALERTS-DOUBLE-POST-DEDUP-01` 32 tests passing), routine docs/ops (`FIX-DOC-SERVER-CANONICAL-MIRROR-01`).

**Weak (strength-as-weakness):** optimizes for "finish the brief" — accepts local evidence too early. SO #41 was created after `FIX-CLV-DEDUP-WRITE-01` reported complete without a landed commit. Visual QA can miss pixels when reduced to OCR/spec checks (`WAVE-F-OPUS-01`). Hidden runtime layer blindness (`P0-WAVE-VERDICT-SONNET-RESTORE` — `.env` override silently moved verdict generation to Haiku despite code defaults).

**Not for:** deep runtime root cause, final launch judgement, adversarial review, ambiguous algorithm quality calls.

### Opus Max Effort

**Design role:** judgement authority. Architectural synthesis, product/system truth, adversarial questioning, QA rubric design, model-routing doctrine, launch-gate severity. 241 Pipeline reports / 30 days, almost all judgement-class.

**Strong:** high-stakes diagnosis (`INV-BOT-PERF-RANDOM-LATENCY-01` — three concurrent drivers identified), launch-grade QA (`QA-LAUNCH-NARRATIVE-DEFINITIVE-01/02` returned NO-GO with explicit blockers), broad system audits (`INV-SOCIAL-OPS-PIPELINE-AUDIT-01` produced 52 findings + 24 dispatchable briefs).

**Weak (strength-as-weakness):** over-scopes implementation. `FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01` needed 6 adversarial rounds + 9 commits before round 7 hit OpenAI usage cap. `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01` burned the full Cowork window on mandatory adversarial review of dispatch-system change (1h39m / 171k tokens / 7% balance left) — drove the v4.5 review-gate narrowing.

**Not for:** routine implementation, mechanical repository search, low-stakes content, simple test harnesses.

### Codex XHigh / High / Medium

**Design role:** code-truth and runtime archaeology. Best when the answer lives across files, call sites, tests, logs, async state, DB transactions, cache behaviour, and exact diffs. Also the right fresh reviewer for Claude-generated code because its biases differ from Claude's language-first completion pattern.

**Tier ladder (NEW per Paul, 6 May 2026):**

| Tier | Use when | Cost relative |
|---|---|---|
| **Codex Medium** | Trivial mechanical: single-line fix, doc typo, rename, contract anchor restoration | Cheapest |
| **Codex High** | Standard mechanical: multi-line refactor (≤3 files), contract-test fix, single-callable migration | Mid |
| **Codex XHigh** | Hard root cause, adversarial review, multi-file blast (>3 files with snippets), dispatch infra | Highest |

**Strong:** codebase search + call-site tracing (`FIX-SCRAPER-WRITE-RETRY-P0-01` shipped `8c6aa5c`), template/contract alignment (3 family briefs all shipped clean), dispatch archaeology (`INV-DISPATCH-SYSTEM-DEBUG-SWEEP-01` 16 findings + 6 follow-ups), reviewer value (caught substantive issues in latency/bridge/pregen waves).

**Weak (strength-as-weakness):** mechanical confidence outruns governance context — pure-Codex SO #45 had to switch from plugin review to fresh `codex exec` because self-shaped review through the same process was redundant. SO #41 commit-discipline failures recur (`FIX-COVERAGE-RUGBY-ODDS-VALIDATION-01` + `FIX-VERDICT-VALIDATOR-V2-SOCCER-VOCAB-01` reported complete with uncommitted diffs). Patches symptoms when env/config archaeology was needed.

**Not for:** product-quality signoff, brand judgement, narrative quality decisions, responsible-gambling tone calls.

### Haiku 4.5

**Design role:** runtime utility only — closed-world summaries, classification, fallback text where mistakes are cheap, reversible, and never sold as premium intelligence. NOT a dispatch executor.

**Strong:** safety/compliance classification (`x.sentiment.block`, `publisher.compliance.block` Sentry events), low-stakes captions with explicit guardrails.

**Weak:** hallucinates verdicts (`VERDICT-MODEL-TEST-01` — fabricated 73% claim). Cache-loop cost runaway (`FIX-NARRATIVE-CACHE-DEATH-01` — $5.55/20h regen loop against $0.05/1,000 budget). Hidden behind `.env` overrides can degrade premium paths invisibly.

**Not for:** premium narrative judgement, paid verdict generation, anything where calibrated confidence matters.

---

## §2 — Task-Class → Model Routing Matrix

Hybrid resolver: class default + signature override + risk escalation.

### Class defaults (when no signature matches)

| Klass | Default executor | Default reviewer | Review mode |
|---|---|---|---|
| FIX-S (1 prod file) | Sonnet | Codex Medium | standard |
| FIX-M (2-3 prod files) | Sonnet | Codex High | standard |
| FIX-L (>3 prod files, with snippets/Pre-flight) | Codex XHigh | Opus Max | standard |
| BUILD (bounded scope) | Sonnet | Codex High | standard |
| BUILD (architectural / launch surface) | Opus Max | Codex XHigh | standard |
| INV (small fact-finding) | Sonnet | Codex Medium | standard |
| INV (judgement / system audit / launch) | Opus Max | Codex XHigh | standard |
| INV (code archaeology / log mining) | Codex XHigh | Sonnet | standard |
| OPS (routine docs/deploy) | Sonnet | Codex Medium | standard |
| OPS (high-risk decisions) | Opus Max | Codex XHigh | standard |
| DOCS (mirrors/reports) | Sonnet | Codex Medium | standard |
| DOCS (canonical doctrine) | Opus Max | Codex XHigh | standard |
| CONTENT (routine copy) | Sonnet | Codex Medium | standard |
| CONTENT (premium/launch/responsible-gambling) | Opus Max | Codex High | standard |
| QA (mechanical harness/visual diff) | Codex XHigh | Sonnet | standard |
| QA (launch-grade severity) | Opus Max | Codex XHigh | standard |
| NARRATIVE (validator/prompt edits) | Codex XHigh | Opus Max | standard |
| NARRATIVE (quality judgement) | Opus Max | Codex XHigh | standard |

### Reviewer rotation rule

| Executor | Default reviewer | Fallback reviewer |
|---|---|---|
| Sonnet | Codex (XHigh for sensitive, Medium/High for routine) | — |
| Codex (any tier) | Opus Max | Sonnet (low-risk mechanical only) |
| Opus Max | Codex XHigh | Sonnet (rare; only when Codex unavailable) |
| Haiku | not a dispatch executor | n/a |

**Why not Sonnet→Codex→Sonnet rotation?** Sonnet's main weakness is governance receipt (commit/push verification) and architectural blind spots — Codex catches both. Codex's main weakness is product/system truth — Opus catches that. Opus's main weakness is over-synthesis and buildability assumptions — Codex catches that. Sonnet reviewing Codex doesn't challenge Codex's blind spots structurally (overlapping language-first bias on system intent), so it's only a fallback for clearly mechanical Codex work.

---

## §3 — Cross-Model Review Protocol

### When mandatory

EVERY code-touching or doctrine-changing brief. No agent self-completes production work. Review block must be in the report before `mark_done.sh` will run.

### Mechanism — layered (subprocess always, Cowork queue additive)

**Layer 1 (mandatory, ALL briefs):** Subprocess review fires before report files. Synchronous, diff-based, enforced by `mark_done.sh` blocking on the review block. This is the universal gate — even judgement-heavy briefs get a diff-level review pass first because the executor's diff might just be wrong before it even gets to the judgement question.

**Layer 2 (additive, judgement-heavy briefs only):** Cowork queue review. After subprocess review passes, brief lands in `awaiting_review/` instead of `done/`. AUDITOR Cowork session pulls, reads broader Notion/report context, applies in-session Claude reasoning, writes a second review block, flips status to `done`. `mark_done.sh` blocks until both review blocks present.

| Brief class | Layer 1 (subprocess) | Layer 2 (Cowork) | Why |
|---|---|---|---|
| Code-touching, bounded diff | ✓ required | — | Diff IS enough context. |
| Judgement-heavy (INV launch / NARRATIVE quality / premium content / model doctrine) | ✓ required | ✓ required | Subprocess catches diff-level errors; Cowork applies broader product/system reasoning. |
| Routing-system / dispatch-governance | ✓ required | ✓ required | Both layers — high cost of wrong + diff often touches process truth. |

Every brief gets at least subprocess review. Judgement-heavy gets BOTH. No brief skips review.

#### Mechanism 1 — Subprocess (`codex exec` or `claude --prompt`)

**Codex reviewing Claude:** existing pattern, kept intact.
```bash
DIFF=$(git show --stat --patch HEAD)
codex --profile xhigh exec --quiet "<canonical review prompt>"
```

**Claude reviewing Codex (NEW — needs implementation):**
```bash
DIFF=$(git show --stat --patch HEAD)
claude --model opus --effort max -p "<canonical review prompt>"
```

The bridge owns the wrapper:
- Diff selection: `git merge-base HEAD origin/main`...`HEAD`
- Stdout → `/tmp/_reviews/<BRIEF-ID>/<head-sha>-<reviewer>-review.md`
- Exit non-zero on `Outcome: needs-changes`, timeout, malformed output
- SLA enforced by wrapper, kill on timeout, write synthetic `needs-changes` block

If non-interactive `claude` CLI doesn't exist, wrapper calls Anthropic Messages API directly with same contract. Implementation is a follow-up FIX brief gated on this bible's ratification.

#### Mechanism 2 — Cowork-managed review queue

For judgement-heavy briefs, executor files report with `Status: awaiting_review` instead of `Complete`. AUDITOR Cowork session pulls review items, reasons in-session via Claude, writes review block, flips status to `Complete`. `mark_done.sh` blocked until status flips.

Cost: operator attention. Use only when the diff alone is insufficient — narrative doctrine, routing changes, launch gates.

### Review output contract (ALL reviewers, ALL mechanisms)

```markdown
## Cross-Model Review

Reviewer: <Codex Medium | Codex High | Codex XHigh | Opus Max Effort | Sonnet>
Reviewed commit: <sha>
Review mode: standard | adversarial
Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt | n/a-no-commits

Findings:
- [P0|P1|P2|P3] <file:line or section:line> — <one-line description>
- or "none"

Executor response:
- <how each finding was addressed, OR why it was not a blocker>
```

`mark_done.sh` validates this block exists + outcome is `clean | blockers-addressed | bootstrap-exempt | n/a-no-commits` before completion.

### Failure modes + SLAs

| Mode | Behavior |
|---|---|
| Reviewer crashes | Retry once. If still fails: `Outcome: gate-error`, brief stays open. |
| Reviewer unavailable (API/CLI failure) | Use fallback reviewer (Codex→Sonnet for mechanical, otherwise Cowork queue). Report logs the downgrade. |
| Reviewer over SLA | Standard 10min FIX-S/DOCS, 20min FIX-M/INV, 30min FIX-L/adversarial. Two timeouts → `awaiting-review-timeout` status. |
| Reviewer disagrees (P0/P1) | Executor must commit fix or escalate to AUDITOR. No self-override. |
| Reviewer disagrees (P2/P3) | Executor may accept with written rationale in "Executor response" block. |
| Insufficient context refusal | Executor provides smaller diff, file ranges, or report excerpts. Refusal is NOT clean. |

---

## §4 — Adversarial vs Standard Review

### First-principles framework

A brief inherently needs adversarial review when a plausible bug crosses one of these boundaries:

1. **Irreversible value boundary** — money, payments, billing, settlement, refunds. Single git revert can't unwind external state.
2. **Authentication/identity boundary** — auth, account ownership, subscription identity, privilege checks.
3. **Persistent production-data boundary** — migrations/backfills mutating durable state without reversible audit trail.
4. **Fanout boundary** — alerts, DMs, publishes, notifications, claim-before-send reservation flows. One bad decision multiplies before a human can stop it.
5. **Concurrent state boundary** — locks, queues, async handlers, cache writers. Race bugs plausible + tests undersample interleavings.
6. **Premium trust boundary** — paid narrative/verdict/edge ranking where hallucination/wrong-team/overconfidence damages user trust.
7. **Dispatch-governance boundary** — bridge, queue, review gate, `mark_done.sh`, report filing, badge state. Process bugs can make future governance lie.

### Mandatory adversarial triggers

| Trigger | Boundary | Evidence anchor |
|---|---|---|
| money/payments/billing/checkout/refunds/settlement | 1 | `BUILD-STITCH-EDGEOPS-WIRE-01` |
| auth/identity/tier-authorization/Telegram-user-binding | 2 | (no pre-launch incidents — preventive) |
| non-rollback-safe migrations | 3 | (preventive) |
| alerts/DM fanout, claim-before-send flows | 4 | `FIX-ALERTS-DOUBLE-POST-DEDUP-01` (10+ commits to fence properly) |
| dispatch-governance state changes (`mark_done`, queue state, badge, review-gate invocation) | 7 | `FIX-CLV-DEDUP-WRITE-01` (drove SO #41), `FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01` |

### Advisory adversarial triggers

| Trigger | Boundary | When |
|---|---|---|
| Concurrency/cache/async state changes (non-fanout) | 5 | When risk is real but reviewer can scope quickly |
| Premium narrative/cache writes | 6 | When change touches user-visible verdicts/narratives |
| Dispatch-bridge changes NOT touching state machine | 7 | Skip mandatory; standard review is sufficient |
| Model/env routing changes | 5 | When `.env` overrides could defeat code defaults |

### Standard review

Everything else: bounded code changes with rollback-safe behaviour, docs/report-only INV, content under existing locked rules, test-only additions to fixtures that don't shape production change.

### Cost discipline rule (LOCKED)

Mandatory cross-model review is non-negotiable. **Adversarial intensity** is selective. v4.4 stacked Opus Max executor + mandatory adversarial review for advisory categories and burned operating windows. v4.5 narrowing was the right correction. Bible reaffirms: **mandatory cross-model**, **discretionary adversarial**.

---

## §5 — Failure Class Taxonomy + Sticking Points

Eight structural failure classes (Opus framework), with incident anchors (Codex evidence) and structural fixes:

| # | Class | Top incidents | Structural fix |
|---|---|---|---|
| 1 | **Governance receipt failures** (Complete diverges from committed/pushed/reviewed) | `FIX-CLV-DEDUP-WRITE-01` → SO #41; `FIX-COVERAGE-RUGBY-ODDS-VALIDATION-01` + `FIX-VERDICT-VALIDATOR-V2-SOCCER-VOCAB-01` (uncommitted diffs after "complete") | Report validation MUST verify git receipt before close. `mark_done.sh` blocks until commit on origin/main grep matches AND `git rev-list --left-right --count HEAD...@{upstream}` returns `0\t0`. |
| 2 | **Bridge/queue state-machine failures** (filesystem state, workspace state, badge/process state disagree) | `FIX-ENQUEUE-CLEAN-STALE-ON-REQUEUE-01`, `FIX-DISPATCH-STATUS-RECONCILER-01`, `FIX-PROMOTE-REENTRANCY-RACE-01` (today) | Treat queue filesystem as canonical. Add state-machine invariant tests for every queue transition. |
| 3 | **Review mechanism failures** (review gate exists in docs, runtime can't enforce) | `FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01`, `FIX-CODEX-REVIEW-PLUGIN-RELIABILITY-01`, `FIX-SO45-CODEX-INLINE-SUBAGENT-01` | Cross-model reviewer = fresh process, synchronous stdout, no background UX. Bridge owns the wrapper. |
| 4 | **Blast-radius/context failures** (briefs ask too much discovery without snippets) | `FIX-DBLOCK-RUNTIME-HOT-PATHS-01`, `FIX-BRIEF-AUTHORING-MULTIFILE-DISCIPLINE-01`, `FIX-SO30-BLAST-RADIUS-01` (today) | SO #30 ≤3 production threshold + Pre-flight sub-agent escape valve. Atomic split when heterogeneous. |
| 5 | **Runtime hidden-layer failures** (env/cache/DB overrides defeat code defaults) | `P0-WAVE-VERDICT-SONNET-RESTORE`, `INV-SONNET-BURN-05` | Model routing checks MUST inspect runtime config, not only code defaults. Cost-loop guards on every LLM cache invalidation. |
| 6 | **Concurrency/fanout failures** (duplicate sends, stale reservations, race interleavings) | `FIX-ALERTS-DOUBLE-POST-DEDUP-01` (10+ commits), `FIX-MY-MATCHES-EMPTY-SCHEDULE-CACHE-POISONING-01` | Mandatory adversarial review for fanout/claim-before-send. Empty-list cache writes require explicit TTL/negative-cache contract. |
| 7 | **User-surface contract drift** (code paths keep old text/behaviour after product contract changes) | `QA-IMAGES-ZERO-TEXT-01` family (5 follow-ups: `EDGE-PICKS-EMPTY-TIER`, `GUIDE-TOPICS`, `MY-MATCHES-EMPTY`, `SETTINGS-RESET-CONFIRM`, `WELCOME-PICK-LOADING`) | User-facing surface changes need ROUTE-COMPLETE QA, not happy-path-only visual checks. Cold/empty branches MUST be QA'd. |
| 8 | **Coverage/window mismatch** (two correct surfaces have incompatible horizons) | `FIX-AI-BREAKDOWN-COVERAGE-01`, `INV-AI-BREAKDOWN-COVERAGE-01`, `FIX-COVERAGE-RUGBY-ODDS-VALIDATION-01` | Briefs touching narrative/cache horizons require an invariant map: producer horizon vs consumer horizon. |

### Cost-stacking sticking point (cross-cutting)

`FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01` consumed full Cowork window with mandatory adversarial on advisory class. Drove DEV-STANDARDS v4.5 narrowing. Bible structural fix: **separate mandatory cross-model review from adversarial intensity**. Mandatory ≠ adversarial.

---

## §6 — `DISPATCH_MODE=full-stack` Specification

### Three-mode toggle (LOCKED)

| Mode | Behavior | When to use |
|---|---|---|
| `pure-codex` | Every brief → `codex --profile xhigh` regardless of Agent | Emergency / Anthropic API outage / debug |
| `hybrid` | Notion `Agent` field drives executor (Routing v1 compat) | Migration window, manual override |
| `full-stack` | Resolver picks executor + reviewer per signature/klass/risk | **Canonical default after rollout** |

### BriefMeta contract (extends queue YAML)

```python
@dataclass(frozen=True)
class BriefExecutionMeta:
    brief_id: str
    klass: str                          # FIX-S | FIX-M | FIX-L | BUILD | INV | OPS | DOCS | CONTENT | QA | NARRATIVE
    target_repo: str                    # bot | scrapers | publisher | mzansiedge-wp | dispatch | home
    agent: str                          # Notion Agent (override only)
    files: tuple[str, ...] = ()         # parsed from "Files in scope" section
    risk_tags: tuple[str, ...] = ()     # money | auth | migration | fanout | concurrency | premium | dispatch-state | premium-narrative | low
    review_mode: str = "review"         # "review" (standard) | "adversarial-review"
    title: str = ""                     # for brief_terms matching
    declared_model_override: str | None = None  # explicit "use this model" only
```

`enqueue.py` parses `klass` from BRIEF-ID prefix, `risk_tags` from a Notion property, `files` from the "Files in scope" markdown section. Missing metadata → enqueue warning (signature matching collapses to klass defaults).

### TASK_SIGNATURES (priority-ordered, mandatory boundaries first)

```python
TASK_SIGNATURES = [
    # === MANDATORY ADVERSARIAL (boundary score +1000) ===
    {
        "name": "payments_auth_settlement",
        "matches": {
            "paths": ["*stitch*", "*payment*", "*subscription*", "*checkout*", "*auth*", "*settlement*"],
            "risk_tags": ["money", "auth", "settlement"],
            "brief_terms": ["payment", "checkout", "billing", "auth", "refund"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "irreversible value or identity boundary (mandatory adversarial)",
    },
    {
        "name": "alerts_dm_fanout",
        "matches": {
            "risk_tags": ["fanout", "claim-before-send"],
            "brief_terms": ["alert", "dm", "double-post", "notification", "fanout", "publish-batch"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "fanout boundary (mandatory adversarial per FIX-ALERTS-DOUBLE-POST-DEDUP-01)",
    },
    {
        "name": "dispatch_governance_state",
        "matches": {
            "repos": ["dispatch"],
            "paths": ["dispatch_promoter.py", "enqueue.py", "cmux_bridge/*.py", "mark_done.sh", "spawn_sequence.py"],
            "risk_tags": ["dispatch-state", "review-gate"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "dispatch-governance boundary — process bugs make future governance lie",
    },
    {
        "name": "non_rollback_migration",
        "matches": {
            "risk_tags": ["migration", "schema-change", "backfill"],
            "brief_terms": ["migration", "backfill", "schema"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "adversarial",
        "mechanism": "subprocess",
        "boundary_score": 1000,
        "reason": "persistent production-data boundary",
    },

    # === ADVISORY ADVERSARIAL (boundary score 0) ===
    {
        "name": "runtime_concurrency_cache",
        "matches": {
            "paths": ["bot.py", "card_sender.py", "scripts/pregenerate_narratives.py"],
            "brief_terms": ["cache", "async", "lock", "timeout", "dedupe", "claim", "race"],
            "risk_tags": ["concurrency", "cache"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "review",  # standard, but escalatable
        "mechanism": "subprocess",
        "reason": "runtime concurrency/cache class — recent incident density",
    },
    {
        "name": "premium_narrative_cache",
        "matches": {
            "paths": ["narrative_*.py", "evidence_pack.py", "pregenerate_narratives.py", "card_data.py"],
            "brief_terms": ["narrative", "verdict", "premium", "pregen", "quality gate"],
            "risk_tags": ["premium-narrative"],
        },
        "executor": "codex-xhigh",
        "reviewer": "opus-max",
        "review_mode": "review",
        "mechanism": "cowork-queue",  # judgement-heavy, diff alone insufficient
        "reason": "premium trust boundary — Cowork queue review for context",
    },

    # === CODE TRUTH / ARCHAEOLOGY ===
    {
        "name": "grep_trace_call_site",
        "matches": {
            "klass": ["INV", "QA"],
            "brief_terms": ["call site", "grep", "audit", "contract", "harness", "parser"],
        },
        "executor": "codex-xhigh",
        "reviewer": "sonnet",  # mechanical work — Sonnet review sufficient
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "code archaeology — Codex strong, Sonnet review sufficient",
    },

    # === JUDGEMENT-HEAVY ===
    {
        "name": "judgement_launch_narrative",
        "matches": {
            "klass": ["INV", "QA", "NARRATIVE"],
            "brief_terms": ["launch", "premium", "narrative quality", "no-go", "calibration", "brand", "doctrine"],
        },
        "executor": "opus-max",
        "reviewer": "codex-xhigh",
        "review_mode": "review",
        "mechanism": "cowork-queue",
        "reason": "Opus judgement domain — Cowork queue review",
    },

    # === ROUTINE BOUNDED ===
    {
        "name": "bounded_fix_routine",
        "matches": {
            "klass": ["FIX"],
            "prod_file_count_lte": 3,
            "risk_tags_absent": ["money", "auth", "migration", "fanout", "dispatch-state", "premium-narrative"],
        },
        "executor": "sonnet",
        "reviewer": "codex-medium",  # cheap reviewer for cheap work
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "Sonnet high-volume routine + cheapest competent reviewer",
    },
    {
        "name": "trivial_mechanical",
        "matches": {
            "klass": ["FIX-S", "DOCS", "OPS"],
            "prod_file_count_lte": 1,
            "brief_terms": ["typo", "rename", "anchor", "mirror sync"],
        },
        "executor": "codex-medium",  # cheapest tier when work is genuinely trivial
        "reviewer": "sonnet",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "trivial mechanical — cheapest Codex tier suffices",
    },
    {
        "name": "docs_routine",
        "matches": {
            "klass": ["DOCS", "OPS"],
            "prod_file_count_lte": 3,
            "risk_tags_absent": ["dispatch-state", "review-gate", "doctrine"],
        },
        "executor": "sonnet",
        "reviewer": "codex-medium",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "routine docs/ops — cheap rotation",
    },
    {
        "name": "content_low_stakes",
        "matches": {
            "klass": ["CONTENT"],
            "risk_tags_absent": ["premium", "responsible-gambling", "launch"],
        },
        "executor": "sonnet",
        "reviewer": "codex-medium",
        "review_mode": "review",
        "mechanism": "subprocess",
        "reason": "routine content",
    },
    {
        "name": "content_premium",
        "matches": {
            "klass": ["CONTENT"],
            "risk_tags": ["premium", "responsible-gambling", "launch"],
        },
        "executor": "opus-max",
        "reviewer": "codex-high",
        "review_mode": "review",
        "mechanism": "cowork-queue",
        "reason": "premium content — Opus voice + Cowork brand context review",
    },
]
```

### Resolver code sketch

```python
MODEL_COMMANDS = {
    "sonnet":      ["claude", "--model", "sonnet"],
    "opus-max":    ["claude", "--model", "opus", "--effort", "max"],
    "codex-medium":["codex", "--profile", "medium"],
    "codex-high":  ["codex", "--profile", "high"],
    "codex-xhigh": ["codex", "--profile", "xhigh"],
}

@dataclass(frozen=True)
class Route:
    executor_cmd: list[str]
    reviewer: str
    review_mode: Literal["review", "adversarial"]
    mechanism: Literal["subprocess", "cowork-queue"]
    rationale: str

def _agent_cmd(agent: str, meta: BriefExecutionMeta | None = None) -> str:
    mode = os.environ.get("DISPATCH_MODE", "hybrid")
    if mode == "pure-codex":
        return shlex.join(MODEL_COMMANDS["codex-xhigh"])
    if mode == "full-stack":
        if meta is None:
            log.warning("full-stack with missing meta — falling back to hybrid")
            return shlex.join(_model_flags(agent))
        route = resolve_full_stack_route(meta)
        write_review_plan(meta.brief_id, route)  # bridge reads at review time
        return shlex.join(route.executor_cmd)
    return shlex.join(_model_flags(agent))  # hybrid (Routing v1 compat)

def resolve_full_stack_route(meta: BriefExecutionMeta) -> Route:
    if meta.declared_model_override:
        return _route_from_override(meta)
    
    matches = []
    for sig in TASK_SIGNATURES:
        score = signature_score(sig, meta)
        if score > 0:
            matches.append((score + sig.get("boundary_score", 0), sig))
    
    if not matches:
        return _class_default_route(meta)
    
    matches.sort(key=lambda m: m[0], reverse=True)
    
    # Ambiguity guard: if top two are tied AND one has mandatory boundary,
    # mandatory wins. Otherwise pick safer (Codex for code-truth, Opus for judgement).
    if len(matches) >= 2 and matches[0][0] == matches[1][0]:
        return _ambiguous_route(meta, [m[1] for m in matches[:2]])
    
    return _route_from_signature(matches[0][1], meta)
```

### Mandatory metadata enforcement

`enqueue.py` MUST validate at enqueue time:
- `klass` derivable from BRIEF-ID
- `target_repo` valid + matches file-signature (existing FIX-ENQUEUE-REPO-FILE-SIGNATURE-01 check)
- `files` parseable from brief body (warn if absent)
- `risk_tags` parseable (default: empty → resolver uses signatures only)

Missing `files` makes signature matching weaker. Brief authoring discipline (Cowork lead drafting briefs) must include `## Files in scope` with explicit paths.

---

## §7 — Migration Path

### Phase 0 — Ratification (NOW)

- [ ] Paul reviews + ratifies this bible
- [ ] Promote to canonical `ops/MODEL-USAGE-BIBLE.md` on bot main
- [ ] Mark draft files (`-CODEX-DRAFT.md`, `-OPUS-DRAFT.md`) as `Status: superseded — see MODEL-USAGE-BIBLE.md` in their headers
- [ ] Bridge stays on `DISPATCH_MODE=hybrid` for migration window

### Phase 1 — Resolver shadow mode (1-2 days)

- [ ] Implement `resolve_full_stack_route()` + `BriefExecutionMeta` parsing
- [ ] Wire shadow logging into bridge: compute route for every brief, log predicted executor/reviewer/rationale, but execute with current Agent field
- [ ] Replay validation against ≥5 historical brief outcomes: `FIX-ALERTS-DOUBLE-POST-DEDUP-01` (should resolve to mandatory adversarial), `QA-IMAGES-ZERO-TEXT-01` (route-complete QA), `FIX-SO45-CODEX-INLINE-SUBAGENT-01` (dispatch-governance), `FIX-SO30-BLAST-RADIUS-01` (docs canonical), card canonical waves (signature → Sonnet+Codex)
- [ ] Acceptance: 100% of replayed briefs route to a model the AUDITOR judges as appropriate

### Phase 2 — Claude-reviews-Codex mechanism (parallel)

- [ ] Implement `claude --model opus --effort max -p` subprocess wrapper (or Anthropic API direct call if CLI doesn't support non-interactive)
- [ ] Wire diff selection, stdout capture, exit-code semantics, SLA timeout
- [ ] Cowork review queue: new YAML state `awaiting_review/`; `mark_done.sh` blocks until report has review block
- [ ] Acceptance: `FIX-DOCS-RULE-21-PREMIUM-W82-CLEANUP-01`-like brief executes with Sonnet, reviews with Codex Medium, `mark_done.sh` honors review gate

### Phase 3 — Low-risk live pilot

- [ ] Enable `full-stack` for DOCS, INV (no commits), QA-only briefs
- [ ] Run 10 briefs minimum, measure: routing accuracy (no override), review compliance (block present), no SO #41 violations

### Phase 4 — Stateful pilot

- [ ] Add FIX-S/FIX-M without payments/auth/fanout
- [ ] Add narrative/cache standard review
- [ ] 20+ briefs, same metrics

### Phase 5 — Default flip

- [ ] After 30 consecutive `full-stack` briefs with: zero override, zero missing review block, zero SO #41 violations
- [ ] Flip plist `DISPATCH_MODE=full-stack`
- [ ] Keep `pure-codex` and `hybrid` as fallback modes (per Paul, 6 May 2026)

---

## §8 — Standing Order Updates

### SO #44 (DISPATCH_MODE) — REPLACE

```markdown
**[SO #44]** Model Usage Bible routing — three dispatch modes via `DISPATCH_MODE` on bridge plist.

`full-stack` (canonical default after rollout) — bridge resolver picks executor and reviewer per BriefExecutionMeta (klass, repo, files, risk_tags, review_mode) using TASK_SIGNATURES from `ops/MODEL-USAGE-BIBLE.md` §6. Notion Agent field is override-only; without override, resolver decides.

`hybrid` (migration / manual override) — Notion Agent field drives executor via `_model_flags()` (Routing v1 compat).

`pure-codex` (emergency / Anthropic outage) — every brief routes to `codex --profile xhigh` regardless of Agent.

Toggle: edit `EnvironmentVariables` in `~/Library/LaunchAgents/com.mzansiedge.cmux-bridge.plist` + `launchctl kickstart -k gui/$(id -u)/com.mzansiedge.cmux-bridge`.

Cross-Model Review Gate (SO #45) is mandatory in all three modes. Cowork orchestration sessions always run on Claude regardless of mode.

Canonical: `ops/MODEL-USAGE-BIBLE.md`. (LOCKED 6 May 2026.)
```

### SO #45 (Review Gate) — RENAME + EXPAND

```markdown
**[SO #45]** Cross-Model Review Gate — no code-touching or doctrine-changing brief self-completes. After commit + push and before `mark_done.sh`, a competing model reviews with fresh context.

Reviewer rotation:
- Sonnet executor → Codex reviewer (XHigh for sensitive, Medium/High for routine)
- Codex executor (any tier) → Opus Max reviewer (Sonnet fallback for low-risk mechanical only)
- Opus Max executor → Codex XHigh reviewer
- Haiku is runtime-only, not a dispatch executor

Mechanism (chosen by resolver):
- Subprocess: `codex --profile <tier> exec --quiet "<prompt>"` (Codex reviewing) or `claude --model opus --effort max -p "<prompt>"` (Claude reviewing). Bridge owns the wrapper (diff selection, stdout capture, SLA timeout, exit codes).
- Cowork queue: brief lands in `awaiting_review/` state; AUDITOR Cowork session reviews via in-session Claude reasoning. For judgement-heavy briefs only.

Required report block (validated by `mark_done.sh`):

```
## Cross-Model Review
Reviewer: <model>
Reviewed commit: <sha>
Review mode: standard | adversarial
Outcome: clean | blockers-addressed | needs-changes | bootstrap-exempt | n/a-no-commits
Findings: [P0|P1|P2|P3] file:line — description (or "none")
Executor response: <how addressed or why not blocker>
```

Adversarial review is MANDATORY for: money/auth/settlement, non-rollback-safe migrations, fanout/claim-before-send flows, dispatch-governance state changes (mark_done, queue state, badge state, review-gate invocation). Otherwise standard review applies.

`mark_done.sh` blocks completion until block present + outcome ∈ {clean, blockers-addressed, bootstrap-exempt, n/a-no-commits}.

Canonical: `ops/MODEL-USAGE-BIBLE.md` §3. (LOCKED 6 May 2026, supersedes v4.5.)
```

### SO #30 — UNCHANGED, BIBLE-AWARE

Bible §6 reaffirms ≤3 production-file threshold + Pre-flight sub-agent escape valve. No SO #30 text change required.

### SO #41 — UNCHANGED, BIBLE-AWARE

Bible §5 class 1 reaffirms commit/push verification. `mark_done.sh` enhancement (Phase 2) makes SO #41 mechanically enforced.

### SO #43 — REAFFIRM

Role ownership (LEAD/AUDITOR/COO/NARRATIVE) is session-locked, NOT inferred from files. Full-stack chooses MODEL only; ROLE stays per session.

---

## §9 — Cost Discipline

### Codex tier ladder (Paul-locked, 6 May 2026)

Use the cheapest tier that's competent for the task. Wrong-tier waste shows up as either over-spend (XHigh on a typo) or under-quality (Medium on adversarial review).

| Tier | Default for | Avoid for |
|---|---|---|
| Codex Medium | Reviewing routine Sonnet work, single-line/typo fixes, contract-anchor restoration | Adversarial review, hard root cause, multi-file refactor |
| Codex High | Standard mechanical 2-3 files, contract-test fix, single-callable migration | Adversarial review of money/auth/dispatch |
| Codex XHigh | Hard root cause, adversarial review, dispatch infra, multi-file blast with snippets | Trivial mechanical (use Medium) |

### Opus discipline

Opus Max is scarce. Use ONLY for:
- Judgement (launch QA, doctrine, model routing, narrative quality)
- Reviewing Codex output on premium/dispatch/auth waves
- Cross-system audits

NOT for: routine implementation, grep-heavy exploration, simple copywriting, mechanical refactor.

Cost incident anchor: `FIX-BRIDGE-SPAWN-AND-DONE-OPUS-MAX-FINAL-01` consumed 171k tokens / 1h39m / 7% balance left from stacked Opus + adversarial review. Bible mandates standard review by default; adversarial requires explicit justification per §4.

### Sonnet circuit breakers

Sonnet runtime cost burns happen when call sites loop unbounded. Per `INV-SONNET-CREDIT-BURN-01` (5 call families, 2.5x-2.7x spike, no breaker). Routing/cache changes that affect runtime LLM spend MUST include cost-loop guard + circuit breaker.

### Haiku discipline

NOT a dispatch executor. Runtime use only, with:
- Closed-world contract (banned betting language, hallucination markers, wrong-sport gates)
- Cost-loop guard (per `INV-HAIKU-SPEND-01` — $5.55/20h regen loop without breaker)
- Never paid verdicts/edge picks

---

## §10 — Implementation Tracker (post-ratification)

After Paul ratifies:

| # | Task | Type | Owner |
|---|---|---|---|
| 1 | Mark draft bibles as superseded | DOCS | AUDITOR Cowork (this session) |
| 2 | Implement BriefExecutionMeta parser in enqueue.py | FIX | dispatched (Codex XHigh — dispatch-governance signature → adversarial) |
| 3 | Implement resolve_full_stack_route() in spawn_sequence.py | FIX | dispatched (Codex XHigh — dispatch-governance signature) |
| 4 | Implement Claude-reviews-Codex subprocess wrapper | BUILD | dispatched (Codex XHigh — dispatch-governance + auth-class for API key handling) |
| 5 | Implement Cowork review queue (awaiting_review state) | FIX | dispatched (Codex XHigh — dispatch-governance) |
| 6 | Update SO #44, SO #45 in CLAUDE.md | DOCS | AUDITOR Cowork |
| 7 | Add review-block validation to mark_done.sh | FIX | dispatched (Codex XHigh — dispatch-governance, mandatory adversarial) |
| 8 | Phase 1 shadow mode + replay validation | OPS | AUDITOR Cowork after #2-#5 land |
| 9 | Phase 3-5 progressive rollout | OPS | AUDITOR Cowork weekly |

---

## Appendices

### Appendix A — Source draft locations

- Codex evidence draft: `ops/MODEL-USAGE-BIBLE-CODEX-DRAFT.md` (origin/main commits `29b7b3a` / `f893d54` / `e3f4703`)
- Opus design draft: `ops/MODEL-USAGE-BIBLE-OPUS-DRAFT.md` (origin/main commits `1dee3f0` / `3ee4e7c`)

Both retained for evidence backstop. New work updates THIS canonical file; drafts are read-only history.

### Appendix B — Decision audit trail

| Decision | Source | Owner choice |
|---|---|---|
| Reconciliation method | Paul, 6 May 2026 | Inline Cowork (option c) |
| Routing decision shape | Paul, 6 May 2026 | Hybrid (klass default + signature override) |
| Cross-model review mechanism | Paul, 6 May 2026 | Hybrid (subprocess + Cowork queue) |
| Codex executor reviewer | Paul, 6 May 2026 | Codex → Sonnet acceptable as fallback for low-risk mechanical; Opus reserved for high-stakes |
| Fallback modes | Paul, 6 May 2026 | Keep `pure-codex` AND `hybrid` as fallback; do not delete |
| Codex tier usage | Paul, 6 May 2026 (NEW ASK) | Use Medium/High when competent — cost discipline |

### Appendix C — When the bible is wrong

If the resolver routes a brief to the wrong model and AUDITOR notices:
1. Override at dispatch via `--declared-model-override` flag (TBD in enqueue.py)
2. File a `FIX-BIBLE-SIGNATURE-DRIFT-NN` brief that updates TASK_SIGNATURES
3. NEVER edit the resolver behavior without updating this bible first

The bible IS the contract. Code follows. Runtime drift triggers immediate amendment.
