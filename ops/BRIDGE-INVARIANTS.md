# Bridge / Dispatch Class Invariants

*Authored: 5 May 2026 — BUILD-BRIDGE-INVARIANTS-DOCTRINE-01*
*Closes audit gap: INV-DOC-ADVERSARIAL-AUDIT-2026-05-05 AC-3*

This document states the invariants that the bridge / dispatch system MUST hold.
Each invariant is grounded in at least one precedent fix from the May 1–5 2026
production-bug cycle. Without these anchors the next person editing the bridge
will re-introduce the same bugs.

Repos:
- **dispatch** = `/home/paulsportsza/dispatch/` (bridge + queue + promoter)
- **bot** = `/home/paulsportsza/bot/` (DEV-STANDARDS, ops/)

---

## State-machine diagram

Every brief moves through exactly one path; re-enqueue is the only backward arc.

```
        ┌─────────┐
        │ pending │  ← re-enqueue (FIX-ENQUEUE-CLEAN-STALE-ON-REQUEUE-01)
        └────┬────┘       ▲
             │            │
  promoter picks up       │ (enqueue.py archives prior done/failed, then writes
  capacity slot           │  new pending YAML — prevents dual-state on re-queue)
             │            │
        ┌────▼────┐       │
        │  ready  │       │
        └────┬────┘       │
             │            │
  bridge spawns agent     │
  (spawn_sequence.py)     │
             │            │
        ┌────▼────┐       │
        │ running │───────┘
        │   🟢    │
        └────┬────┘
             │
    agent runs mark_done.sh
    (canonical DONE signal)
             │
        ┌────▼────┐       ┌─────────┐
        │  done   │◄──────│ running │ (post-done reawakening: agent
        │   ✅    │       │   🟢    │  types after mark_done; badge
        └─────────┘       └─────────┘  reverts 🟢 until idle again)
                               ▲
                (FIX-BRIDGE-STATUS-RESPONSIVE-POST-DONE-01)
                  done→running on fresh surface activity within
                  DONE_REAWAKEN_WINDOW_S; re-settles to ✅ after
                  DONE_SETTLE_S idle.

             ┌─────────┐
        ┌────►  failed  │  ← reconciler: agent process dead + YAML still
        │    │   ❌     │     in running/ (orphan / crash)
        │    └────┬────┘
        │         │
        │    re-enqueue (enqueue.py) → pending
        │
        └─── running  (FIX-DISPATCH-STATUS-RECONCILER-01:
                        reconciler detects PID dead while YAML in running/;
                        moves YAML to failed/ + fires EdgeOps alert)

Idle-kill (separate from badge):
  running (YAML in done/) → SIGTERM after IDLE_KILL_GRACE_S=300 s
  RAM cleanup only; badge already ✅ before this fires.
  (FIX-DISPATCH-RECONCILER-IDLE-KILL-POST-DONE-01)
```

Transitions summary:

| From    | To      | Trigger                                               |
|---------|---------|-------------------------------------------------------|
| pending | ready   | `dispatch_promoter.py` picks slot (capacity-aware)    |
| ready   | running | `spawn_sequence.py` spawns agent; PID captured        |
| running | done    | `mark_done.sh` canonical output line seen in buffer   |
| done    | running | Post-done surface activity within reawaken window     |
| running | failed  | Reconciler: PID dead, YAML still in running/          |
| failed  | pending | `enqueue.py --re-enqueue` (archives stale failed)     |
| done    | pending | `enqueue.py --re-enqueue` (archives stale done)       |

---

## Invariant 1 — Single-state truth

**Statement:** A brief YAML exists in exactly one queue directory at any time:
`pending/`, `ready/`, `running/`, `done/`, or `failed/`. The reconciler MUST
detect dual-state (YAML in two dirs) and resolve it. On any conflict, filesystem
state takes precedence over bridge in-memory state.

**Why:** When a brief was re-enqueued without archiving the prior `failed/` entry,
the reconciler saw both a `running/` YAML and a `failed/` YAML for the same
brief_id, kept `failed`, and dismissed the legitimate `running` entry — silently
killing an active agent.

**Evidence:**

| Fix | Commit (dispatch) | File:line |
|-----|-------------------|-----------|
| FIX-ENQUEUE-CLEAN-STALE-ON-REQUEUE-01 | `278518c` | `enqueue.py:616` |
| FIX-DISPATCH-STATUS-RECONCILER-01 | `d771898` | `cmux_bridge/cmux_bridge.py:1911` |
| FIX-BRIDGE-RECONCILER-GHOST-RUNNING-CLEANUP-01 | `ede0f6f` | `cmux_bridge/cmux_bridge.py` |
| FIX-BRIDGE-POLLER-CACHE-LAST-KNOWN-STATE-01 | `3a07dcc` | `cmux_bridge/server_poller.py:36` |

**Doctrinal anchor:** Bridge-doctrine — not in any SO. (The queue-dir layout is
bridge-internal; no SO governs which directory is canonical truth.)

---

## Invariant 2 — Badge = filesystem truth

**Statement:** The workspace badge state is derived solely from queue YAML
location, not from agent process liveness. ✅ = brief YAML in `done/`, full stop.
Post-done agent activity (recap text, summary) is cosmetic; it does not block or
revert the ✅ badge.

**Why:** The previous implementation gated ✅ on YAML-in-done/ AND agent-process-
exit. Agents perform extended post-done recap text and rarely go idle within the
bridge poll interval — so the ✅ badge almost never appeared in practice, leaving
the workspace stuck at 🟢 indefinitely after a successful brief.

**Evidence:**

| Fix | Commit (dispatch) | File:line |
|-----|-------------------|-----------|
| FIX-BADGE-DONE-IS-DONE-01 | `589876c` | `cmux_bridge/cmux_bridge.py:1785` |
| FIX-DISPATCH-STATUS-RECONCILER-01 | `d771898` | `cmux_bridge/cmux_bridge.py:1777` |
| FIX-BRIDGE-FALSE-DONE-DETECTION-01 | `c6c8dd6` | `cmux_bridge/cmux_bridge.py:43` |

Note: FIX-BRIDGE-FALSE-DONE-DETECTION-01 tightened the DONE signal detector to
require the canonical `mark_done.sh` output line (`^Marked <ID> done.  Report:
<url>$`) and pre-reject spawn-step echoes — so the filesystem move only happens
on a genuine close, not on a buffer false-positive.

**Doctrinal anchor:** Bridge-doctrine — not in any SO.

---

## Invariant 3 — Kickoff includes `--wait` directive

**Statement:** Every kickoff message (spawn step 6) instructs the agent to pass
`--wait` to `/codex:review` and `/codex:adversarial-review` invocations.

**Why:** Without `--wait`, `/codex:review` runs as a background task and may not
complete before the session exits, defeating the SO #45 review gate entirely. In
bridge-spawned sessions the interactive foreground/background prompt is never seen
by the user — the review silently disappears.

**Evidence:**

| Fix | Commit | Repo | File:line |
|-----|--------|------|-----------|
| FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01 | `3c7f158` | bot | `ops/DEV-STANDARDS.md:409` |
| Kickoff injection | `9a43dcf` + `3692bbb` | dispatch | `cmux_bridge/spawn_sequence.py:509` |
| FIX-CODEX-REVIEW-PLUGIN-RELIABILITY-01 | (no standalone commit; see Notion report) | bot | Codex plugin config — disabled model-invocation caching that caused cc-fail inside bridge-spawned agents |

**Doctrinal anchor:** DEV-STANDARDS.md SO #45 (v4.5 — locked 4 May 2026,
`ops/DEV-STANDARDS.md:409`).

---

## Invariant 4 — Bypass-permissions accept is global, not per-CWD

**Statement:** Claude Code's bypass-permissions warning is a one-time-per-user
prompt. The bridge MUST NOT send `Down+Enter` on every spawn. Only the trust-
folder `Enter` (step 5) is sent; the bypass accept is pre-written into
`~/.claude/` once and never re-sent.

**Why:** The trust-folder prompt appears BEFORE the bypass-permissions prompt on
every new CWD launch. `Down+Enter` on the trust prompt selects "No, exit" →
the agent exits immediately. Sending `Down+Enter` universally caused 100% of
bridge-spawned agents to exit on their first launch in a new working directory.

**Evidence:**

| Fix | Commit (dispatch) | File:line |
|-----|-------------------|-----------|
| FIX-BYPASS-PERMISSIONS-ACCEPT-01-ROLLBACK | `eace087` | `cmux_bridge/spawn_sequence.py:480` |
| FIX-AGENT-AUTO-PERMISSIONS-01 | `5589772` | `cmux_bridge/spawn_sequence.py:170` |

**Doctrinal anchor:** Bridge-doctrine — not in any SO. The one-time-per-user
nature of the bypass accept is a Claude Code runtime property; the bridge docs
`cmux_bridge/spawn_sequence.py:481–490` carry the authoritative comment.

---

## Invariant 5 — Autodeploy syncs to the live working tree

**Statement:** The autodeploy script's `REPO_DIR_LOCAL` MUST point at the path
used by the bridge LaunchAgent at runtime. Currently:
`~/Library/Application Support/cmux-bridge/dispatch/`

The historical path `~/Documents/dispatch/` MUST NOT be used.

**Why:** macOS TCC (Transparency, Consent, and Control) blocks LaunchAgent
processes from accessing `~/Documents/` without an explicit Full Disk Access
grant. A LaunchAgent deploying to a path it cannot read/write silently skips the
deploy — the bridge runs stale code indefinitely with no error.

**Evidence:**

| Fix | Commit (dispatch) | File:line |
|-----|-------------------|-----------|
| BUILD-DISPATCH-AUTO-DEPLOY-V2-SSH-POLL-01 | `588ecbd` | `infra/dispatch/scripts/cmux_bridge_autodeploy.sh:1` |
| BUILD-DISPATCH-RELOCATE-OUT-OF-DOCUMENTS-01 | `93ea9e5` | `infra/dispatch/scripts/cmux_bridge_autodeploy.sh:24` |
| FIX-AUTODEPLOY-SCRIPT-DEST-PATH-01 | inline 5 May 2026 (see Notion brief) | `infra/dispatch/scripts/cmux_bridge_autodeploy.sh:24` |

Canonical `REPO_DIR_LOCAL` line:

```bash
REPO_DIR_LOCAL="${DISPATCH_REPO:-$HOME/Library/Application Support/cmux-bridge/dispatch}"
```

**Doctrinal anchor:** Bridge-doctrine — not in any SO.

---

## Invariant 6 — Re-enqueue cleans terminal state

**Statement:** `enqueue.py` archives any prior `failed/` or `done/` YAML for the
same `brief_id` into `failed/archive/` or `done/archive/` before writing the new
`pending/` YAML. This MUST happen atomically in the enqueue operation, not lazily
in the reconciler.

**Why:** A stale `failed/<brief>.yaml` from a prior cancel/crash collided with the
new `running/<brief>.yaml` after promotion. The reconciler saw dual-state, kept
`failed`, and dismissed `running` — silently terminating the legitimate active
agent. The fix moved cleanup to enqueue time, so the new pending YAML is the only
copy from the moment of re-enqueue.

**Evidence:**

| Fix | Commit (dispatch) | File:line |
|-----|-------------------|-----------|
| FIX-ENQUEUE-CLEAN-STALE-ON-REQUEUE-01 | `278518c` | `enqueue.py:616` |

**Doctrinal anchor:** Bridge-doctrine — not in any SO.

---

## Invariant 7 — Idle-kill is independent of badge

**Statement:** The 5-minute SIGTERM grace (`IDLE_KILL_GRACE_S=300`) is a RAM-
cleanup mechanism only. It fires after `mark_done.sh` has already moved the YAML
to `done/` and the badge is already ✅. Idle-kill MUST NOT be treated as a badge-
state trigger.

**Why:** Conflating idle-kill with badge transition would make badge correctness
dependent on agent process timing — a process that keeps writing recap text for
>5 min would prevent the ✅ badge entirely (the prior bug), or an agent that
crashes immediately after `mark_done.sh` would never get SIGTERM'd (a RAM leak).
Separating the two concerns lets each one succeed independently.

**Evidence:**

| Fix | Commit (dispatch) | File:line |
|-----|-------------------|-----------|
| FIX-DISPATCH-RECONCILER-IDLE-KILL-POST-DONE-01 | `874f60f` | `cmux_bridge/cmux_bridge.py:185` |
| FIX-BADGE-DONE-IS-DONE-01 | `589876c` | `cmux_bridge/cmux_bridge.py:1789` |

The comment at `cmux_bridge/cmux_bridge.py:1789` explicitly states: *"Idle-kill
still SIGTERMs after IDLE_KILL_GRACE_S to free RAM, but that is independent of
badge state."*

**Doctrinal anchor:** Bridge-doctrine — not in any SO.

---

## Invariant 8 — Session role locks dispatch role

**Statement:** Every brief enqueued by a Cowork session MUST use that session's
declared role consistently across: (a) the Notion Agent-select property, (b) the
`--role` flag on the spawned agent, (c) the report's Agent property. Cross-lane
work uses Handoff Protocol (SO #11), not a role swap mid-session.

**Why:** Wrong-role reports pollute cross-lane tracking, create audit false-
positives (INV-SYSTEM-HEALTH scans flag them), and break the session-isolation
invariant that allows concurrent lanes to operate without interference.

**Evidence:**

| Fix | Commit (dispatch) | File:line |
|-----|-------------------|-----------|
| FIX-DISPATCH-STATUS-RECONCILER-01 | `d771898` | `cmux_bridge/cmux_bridge.py:390` (Routing v1 VALID_ROLES) |
| FIX-BRIDGE-CODEX-ACTIVITY-PATTERN-01 | `32ae01e` | `cmux_bridge/cmux_bridge.py:498` |

`VALID_ROLES` enforcement at `cmux_bridge/cmux_bridge.py:390` (Routing v1, locked
2 May 2026) rejects spawn attempts with unrecognised roles at the bridge layer,
preventing silent role drift.

**Doctrinal anchor:** SO #43 (canonical location: `ME-Core.md` — not mirrored
on server as of 5 May 2026; bridge-doctrine mirror here until server mirror
exists). See INV-DOC-COMPREHENSION-SMOKE-01 finding.

---

## Cross-reference: May 1–5 fix coverage

Every brief from the May 1–5 production-bug cycle is cited at least once above.

| Brief ID | Invariant(s) | Dispatch commit | Bot commit |
|----------|-------------|-----------------|------------|
| FIX-BRIDGE-FALSE-DONE-DETECTION-01 | 2 | `c6c8dd6` | — |
| FIX-BRIDGE-POLLER-CACHE-LAST-KNOWN-STATE-01 | 1 | `3a07dcc` | — |
| FIX-DISPATCH-STATUS-RECONCILER-01 | 1, 2, 8 | `d771898` | — |
| FIX-CODEX-REVIEW-PLUGIN-RELIABILITY-01 | 3 | — (config fix; see Notion report) | — |
| FIX-BRIDGE-CODEX-ACTIVITY-PATTERN-01 | 8 | `32ae01e` | — |
| FIX-CODEX-REVIEW-WAIT-FLAG-CANONICAL-01 | 3 | — | `3c7f158` |
| FIX-BRIDGE-STATUS-RESPONSIVE-POST-DONE-01 | 2 | `75c023f` | — |
| FIX-DISPATCH-RECONCILER-IDLE-KILL-POST-DONE-01 | 7 | `874f60f` | — |
| FIX-BADGE-DONE-IS-DONE-01 | 2, 7 | `589876c` | — |
| FIX-AUTODEPLOY-SCRIPT-DEST-PATH-01 | 5 | `93ea9e5` (path change) | — |
| BUILD-DISPATCH-AUTO-DEPLOY-V2-SSH-POLL-01 | 5 | `588ecbd` | — |
| FIX-ENQUEUE-CLEAN-STALE-ON-REQUEUE-01 | 1, 6 | `278518c` | — |
| FIX-BYPASS-PERMISSIONS-ACCEPT-01-ROLLBACK | 4 | `eace087` | — |
