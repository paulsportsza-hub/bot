# Dispatch Infra — Guardrail Placement Registry

*Created: 2026-05-07 · Brief: OPS-LANE-B-PLACEMENT-RATIFY-3-GUARDRAILS-01 (Lane B AUDITOR)*
*Status: RATIFIED — all 3 guardrails confirmed in canonical placement.*

This document is the single source of truth for the location, wiring, and
placement rationale of server-side and repo-side guardrails that were shipped
as part of the Codex review-gate / dispatch isolation hardening work (T65, T67).

---

## Guardrail Inventory

### 1. `codex_broker_reaper.sh` — Orphaned Broker Killer

| Field | Value |
|---|---|
| **Script path** | `/home/paulsportsza/scripts/codex_broker_reaper.sh` |
| **Systemd service** | `/etc/systemd/system/codex-broker-reaper.service` |
| **Systemd timer** | `/etc/systemd/system/codex-broker-reaper.timer` |
| **Timer schedule** | Every 30 min (OnUnitActiveSec=30min, OnBootSec=10min) |
| **Timer status** | Active (enabled since 2026-05-07 07:02 UTC) |
| **Run as** | `paulsportsza` (Nice=10) |
| **Origin** | SO #45 Codex review gate + INV-CODEX-BROKER-LEAK-ROOT-CAUSE-01 |

**Purpose:** Kills `app-server-broker.mjs` processes that have been re-parented
to PID 1 (orphaned after their parent tmux/shell exits). Costs ~250 MB RAM +
2–9% CPU per orphan indefinitely without this reaper. Also purges stale
`/tmp/cxc-*` directories whose `broker.pid` is dead.

**Safety:** Only kills brokers with `ppid=1`. Active brokers (live parent shell)
are untouched.

**Placement decision: RATIFIED ✓**
`/home/paulsportsza/scripts/` is the canonical home for server-side
infrastructure scripts that are not bot application code. The systemd wiring
at `/etc/systemd/system/` (service + timer pair) is the correct pattern for
periodic server maintenance. Timer is confirmed active and enabled.

---

### 2. `bot_tree_drift_check.sh` — Live-Bot Drift Warning

| Field | Value |
|---|---|
| **Script path** | `/home/paulsportsza/scripts/bot_tree_drift_check.sh` |
| **Wiring** | `wave_worktree_create.sh` line 60 (non-blocking, `\|\| true`) |
| **Dispatch coverage** | `dispatch_runner.sh` line 260 → `wave_worktree_create.sh` → transitive |
| **Systemd timer** | None (dispatch-scoped, not time-scoped) |
| **Thresholds** | WARN: 3 modified production .py files; CRIT: 8 |
| **Origin** | SO #41 — wave dispatch runner / worktree isolation |

**Purpose:** Warns (WARN) or fails (CRIT) when the live bot tree
(`/home/paulsportsza/bot`) has too many uncommitted production Python edits.
`mzansi-bot.service` runs from that tree — Python imports lazily, so a
modified `.py` on disk is loaded live mid-session.

**Wiring path:**
```
dispatch_runner.sh (line 260)
  → wave_worktree_create.sh (line 60)
    → bot_tree_drift_check.sh || true  ← FULLY advisory, never blocks
```
Every brief dispatched through the canonical runner fires the drift check at
worktree creation time. The `|| true` suffix means BOTH WARN and CRIT exit 1
are masked — dispatch always continues. The check is purely advisory: authors
see the warning on stderr before their worktree is ready but cannot be blocked
by it at the current wiring level.

**Placement decision: RATIFIED ✓**
`/home/paulsportsza/scripts/` is correct. No standalone systemd timer is
needed: the check is scoped to dispatch events, not calendar time. Transitive
dispatch-runner coverage means it fires on every brief.

---

### 3. `db-bare-connect-check.sh` — Bare sqlite3.connect() Guard

| Field | Value |
|---|---|
| **Script path** | `/home/paulsportsza/bot/.githooks/db-bare-connect-check.sh` |
| **Hook wiring** | `.githooks/pre-commit` → `if ! ./.githooks/db-bare-connect-check.sh; then exit 1; fi` |
| **Git config** | `core.hooksPath=.githooks` (confirmed active in bot repo) |
| **Activated by** | `scripts/install_git_hooks.sh` (idempotent, run once per clone) |
| **Propagation** | Git copies `.githooks/` into worktrees — all wave worktrees inherit the hook |
| **Bypass** | `BARE_CONNECT_BYPASS=1 git commit ...` (audit-trailed) |
| **Origin** | OPS-DBLOCK-BARE-CONNECT-GREP-GUARD-01 — incident FIX-DBLOCK-CARD-GEN-DIGEST-STATS-01 (2026-05-07) |

**Purpose:** Rejects staged Python files that call `sqlite3.connect()` directly
(outside the two canonical helpers: `db_connection.py::get_connection` and
`scrapers/db_connect.py::connect_odds_db`). Bare connects skip WAL +
`busy_timeout=30000ms` pragmas → "database is locked" under write contention.

**Allowlist (pass-through):** `db_connection.py`, `db_connect.py`, test files
(`test_*.py`, `tests/`), URI `mode=ro` paths.

**Multi-copy note:** The script appears in `bot-prod/`, `bot-prod-prev/`,
and all `worktrees/*/.githooks/` directories. These are git-propagated copies
and are expected. The authoritative source is
`/home/paulsportsza/bot/.githooks/db-bare-connect-check.sh`; all others
track it via their working tree's git checkout.

**Placement decision: RATIFIED ✓**
`.githooks/` within the bot repo is the canonical location for tracked
pre-commit hooks (per OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01). Tracking
the hook in the repo (rather than `.git/hooks/`) ensures it propagates to
worktrees automatically and is version-controlled.

---

## Drift / Inconsistency Flags (AC-4)

### D-1 (LOW) — Stale `.git/hooks/pre-commit` artifact

`/home/paulsportsza/bot/.git/hooks/pre-commit` (dated 2026-03-27) is a relic
from before `core.hooksPath=.githooks` was configured. Because `core.hooksPath`
overrides `.git/hooks/`, this file is functionally dead but may confuse future
readers or tooling that inspects the standard hook location.

**Impact:** None (dead code). **Suggested follow-up:** `OPS-CLEANUP-GIT-HOOKS-DEAD-ARTIFACT-01` — remove or leave a forwarding comment in `.git/hooks/pre-commit`.

### D-2 (INFO) — `bot_tree_drift_check.sh` CRIT threshold vs current live drift

At ratification time the live bot tree has ~7 modified production `.py` files
(WARN level; CRIT threshold is 8). This is a live operational observation, not
a placement issue. Monitor drift level before next brief dispatch.

**Impact:** None on guardrail placement. **Action:** No follow-up brief needed;
operational awareness item for the brief author/runner.

---

## Summary

| Guardrail | Canonical path | Wiring | Status |
|---|---|---|---|
| `codex_broker_reaper.sh` | `/home/paulsportsza/scripts/` | systemd timer (30 min, active) | RATIFIED ✓ |
| `bot_tree_drift_check.sh` | `/home/paulsportsza/scripts/` | `wave_worktree_create.sh` → `dispatch_runner.sh` | RATIFIED ✓ |
| `db-bare-connect-check.sh` | `/home/paulsportsza/bot/.githooks/` | `pre-commit` via `core.hooksPath=.githooks` | RATIFIED ✓ |

All 3 guardrails are in correct canonical placement. No moves required.
One low-priority drift artifact flagged (D-1). One operational info item (D-2).

---

## Claude Sibling Review (AC-6)

*Self-review by AUDITOR Lane B (Sonnet) — 2026-05-07*

**Scope:** Placement ratification only. No code was changed.

**Findings:**
- Guardrail paths and systemd/hook wiring confirmed by live inspection (find, systemctl, git config).
- `dispatch_runner.sh → wave_worktree_create.sh` transitive chain confirmed at source level (line 260).
- All 3 placement decisions are consistent with project conventions (`scripts/` for server ops, `.githooks/` for tracked hooks, `/etc/systemd/system/` for daemons).
- D-1 stale artifact: functionally harmless, noted as low-priority.
- D-2 live drift level: advisory only — does not affect guardrail correctness.
- Codex sub-agent (SO #45) flagged P2: original wording implied CRIT could block dispatch — corrected to reflect `|| true` makes both WARN and CRIT fully advisory.

**Verdict:** blockers-addressed — documentation updated to accurately reflect advisory-only CRIT behavior.
