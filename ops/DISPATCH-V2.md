# Dispatch V2 — Canonical Reference

*Locked: 30 April 2026. This is the single source of truth for the MzansiEdge
dispatch system. All other docs (CLAUDE.md, DEV-STANDARDS.md, role specs,
onboarding messages) link here. Do not duplicate architecture prose elsewhere.*

---

## Pipeline

```
[Cowork agent]
   ↓  SSH (forced-command enqueue.py via .cowork-ssh key)
[server: /home/paulsportsza/dispatch/queue/pending/<BRIEF-ID>.yaml]
   ↓  systemd: dispatch-promoter.service polls every 5s
[server: /home/paulsportsza/dispatch/queue/ready/]
   ↓  Mac launchd: cmux-bridge polls ready/ every 5s via SSH ls
[Mac: CMUX workspace.create + spawn_sequence (mosh + claude + dispatch block)]
   ↓  bridge: SSH-mv ready/ → running/
[server: queue/running/]
   ↓  Claude Code session executes brief autonomously
[Notion Pipeline DS: agent files report; Paul copies URL]
   ↓  Paul relays URL to Cowork lead; lead reviews, marks Wave Done
[done/ marker; bridge renames CMUX workspace [✅ <tail>]]
```

---

## Cowork-Side: SSH-Enqueue (canonical)

### Command

```bash
KEY=$(find /sessions -name "id_ed25519" -path "*.cowork-ssh*" -print -quit)
ssh -i "$KEY" -o StrictHostKeyChecking=no -o BatchMode=yes paulsportsza@37.27.179.53 \
  -- '--notion-url <NOTION-URL> --role edge_<lead|auditor|coo> --mode <sequential|parallel>'
```

The argument MUST be passed after `--` to prevent SSH from parsing the flags
itself. The key is mounted into every Cowork sandbox under
`/sessions/<sandbox-id>/mnt/MzansiEdge/.cowork-ssh/`. Use `find` because the
sandbox ID changes per session.

The key is restricted on the server's `authorized_keys` to
`command="...enqueue_via_ssh.sh"` — it can **only** run `enqueue.py` with the
supplied flags. No shell, no scp, no other commands.

### enqueue.py flag reference

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--notion-url` | full Notion URL | *(required)* | Must be a live page |
| `--role` | `edge_lead`, `edge_auditor`, `edge_coo` | `edge_lead` | Sets role for bridge + workspace title |
| `--target-repo` | repo name (`bot`, `publisher`, etc.) | `bot` | Picked from brief metadata |
| `--mode` | `sequential`, `parallel` | `sequential` | See Mode Selection below |
| `--depends-on` | `<id1,id2>` comma-separated | *(none)* | IDs must exist in `done/` before promote |
| `--no-cmux-validation` | flag | off | Skip CMUX workspace pre-check (debug only) |

### Mode Selection

- **`sequential`** — must be used when this brief and any other in-flight brief
  target the **same git repo**. The pre-merge gate runs the full test suite on
  every commit; concurrent writes to the same repo cause collision failures.
- **`parallel`** — permitted only when every sibling brief targets a **different
  git repo**. Cross-repo parallelism is collision-free.
- **Default to `sequential` when in doubt.** False-positive serialisation costs
  ~10 min of wall time. False-positive parallelism costs a wave-blocking
  pre-merge collision.

---

## Server-Side: Queue State Machine

### Location

`/home/paulsportsza/dispatch/queue/`

### Subdirectories

| Subdir | Meaning | Who writes | Who reads |
|--------|---------|-----------|----------|
| `pending/` | Enqueued, not yet promoted | `enqueue.py` | `dispatch-promoter` |
| `ready/` | Deps + collisions clear | `dispatch-promoter` | `cmux-bridge` |
| `running/` | Bridge spawned workspace | `cmux-bridge` (via SSH-mv) | bridge tracker |
| `done/` | Brief finished | manual/auto report write | bridge → workspace [✅] |
| `failed/` | Spawn or run failed | bridge | manual cleanup |

### YAML file format

```yaml
brief_id: BUILD-X-01
notion_url: https://www.notion.so/...
agent: Sonnet - LEAD
role: edge_lead
target_repo: bot
mode: parallel
depends_on: []
enqueued_at: 2026-04-30T10:30:00Z
dispatcher_seq: 9
dispatcher_role: edge_lead
report_url: ''   # filled when done
```

---

## Server-Side: dispatch-promoter.service

| Item | Value |
|------|-------|
| File | `/home/paulsportsza/dispatch/dispatch_promoter.py` |
| Unit | `/etc/systemd/system/dispatch-promoter.service` |
| Log | `/home/paulsportsza/dispatch/dispatch_promoter.log` |
| Poll interval | every 5s |

### Promotion rules (per pending brief)

1. All `depends_on` briefs must exist in `done/`. Else hold.
2. `mode=sequential`: no other `ready/` or `running/` brief on the same
   `target_repo`. Else hold.
3. `mode=parallel`: free immediately (deps still required).

On promote: `mv pending/X.yaml ready/X.yaml`. Logs
`PROMOTED <id> pending → ready (mode=... repo=... deps=...)`.

---

## Mac-Side: cmux-bridge

| Item | Value |
|------|-------|
| Files | `~/Documents/dispatch/cmux_bridge/{cmux_bridge,cmux_socket,server_poller,spawn_sequence}.py` |
| launchd | `~/Library/LaunchAgents/com.mzansiedge.cmux-bridge.plist` |
| Log | `~/Library/Logs/cmux-bridge.log` |
| CMUX socket | `/Users/paul/Library/Application Support/cmux/cmux.sock` |
| Poll interval | every 5s via SSH `ls` to `paulsportsza@37.27.179.53` |

### On new brief seen

1. Capture currently-focused workspace ID (`workspace.current`) for focus
   restore.
2. `workspace.create` → new workspace.
3. `workspace.rename` to `🧑‍💻 [<seq>] [<MODEL>] <BRIEF-ID>` (MODEL derived
   from `brief.agent`).
4. `surface.list(workspace_id=X)` → use the auto-spawned default tab. Falls
   back to `surface.create` only if list comes up empty after 6s.
5. `spawn_sequence`: type `mosh paulsportsza@37.27.179.53` + Enter, wait 3s;
   type `claude --model <model>` + Enter, wait 5s; press Enter
   (trust-accept), wait 3s; paste 4-line dispatch block; double-Enter to
   submit.
6. SSH-mv server `ready/X.yaml` → `running/X.yaml`
   (`mark_running` in `server_poller`).
7. `workspace.select` back to captured prior workspace (focus restore).

---

## Workspace Title Format (locked)

```
🧑‍💻 [<seq>] [<MODEL>] <BRIEF-ID>
```

Examples:
- `🧑‍💻 [9] [SONNET] INV-EVIDENCE-PACK-ENRICHMENT-01`
- `🧑‍💻 [7] [OPUS] FIX-PREGEN-DIAMOND-PRIORITY-01`

Suffixes:
- Done: appends ` ✅ <last-8-chars-of-report-page-id>`
- Failed: appends ` ❌`
- Spawn-fail: appends ` ⚠️`

---

## The Dispatch Block (what bridge pastes)

```
<BRIEF-ID> — <YYYY-MM-DD>
<NOTION-URL>
NOTION_TOKEN: <env NOTION_TOKEN>
Execute this brief.
```

**Cowork agents NEVER paste this block themselves.** The bridge handles paste
automatically after spawning the CMUX workspace. If you are a Cowork agent
reading this: your job ends at `ssh ... -- '--notion-url ...'`. Bridge takes
it from there.

---

## Standing Orders — Unchanged

| SO | Rule | Status |
|----|------|--------|
| SO #2 | Notion = single source of truth. Briefs still drafted in Notion FIRST; SSH-enqueue passes the URL. | Unchanged |
| SO #14 | Classify before discussing. | Unchanged |
| SO #29 | Project isolation. SSH-enqueue is MzansiEdge-only. | Unchanged |
| SO #35 | Reports filed in Pipeline DS. Bridge does NOT file reports; the spawned Claude session does. | Unchanged |
| SO #38 | Mandatory visual QA sub-agent. Claude session in CMUX is responsible. | Unchanged |
| SO #41 | Approval binds commit. Bridge marks [✅ <tail>] only when report URL lands in `done/X.yaml`. | Unchanged |

---

## Troubleshooting Playbook

### Bridge silent-spawn

**Symptom:** `enqueue.py` exits 0, `pending/X.yaml` exists, but no CMUX
workspace appears.

1. Check `dispatch_promoter.log` — is the brief promoted to `ready/`? If not,
   promoter is holding it (deps missing, sequential collision).
2. Check `~/Library/Logs/cmux-bridge.log` — is the bridge polling? Look for
   `poll server ready/` entries. No entries → bridge daemon crashed or was
   never started.
3. Restart bridge: `launchctl unload ~/Library/LaunchAgents/com.mzansiedge.cmux-bridge.plist && launchctl load ...`
4. If brief is stuck in `ready/` and bridge is running but skipping it, check
   for `surface.list` parser errors in the bridge log.

### surface.list parser failure

**Symptom:** bridge log shows `surface.list error` or `no surfaces found`.

1. CMUX must be in **allowAll access mode** — check CMUX Settings → Access.
2. CMUX socket path: `/Users/paul/Library/Application Support/cmux/cmux.sock`.
   Verify it exists: `ls -la "/Users/paul/Library/Application Support/cmux/"`.
3. If socket is missing, CMUX app is not running. Start CMUX.
4. `spawn_sequence` falls back to `surface.create` after 6s timeout —
   workspace will be created with a new tab rather than the auto-spawned one.
   This is cosmetic; the brief runs normally.

### Focus-steal

**Symptom:** bridge opens a new workspace and brings it to the foreground mid-
session, interrupting the active Cowork window.

- Bridge calls `workspace.select` back to the prior workspace after spawn.
  If focus-steal persists, check bridge log for `focus restore` entries — a
  failed restore leaves the new workspace active.
- Workaround: do not use Cowork for interactive work while a dispatch is
  in-flight. The spawn sequence takes ~15s.

### Two-tab cosmetic

**Symptom:** new workspace has two tabs instead of one.

- `surface.list` returned the auto-spawned tab AND bridge called
  `surface.create` as a fallback. The duplicate tab is harmless — dispatch
  block was pasted into the correct (first) tab.
- If reproducible, check bridge log for `surface.list timeout` — increase the
  6s wait in `spawn_sequence.py` if the CMUX workspace consistently takes
  longer to initialise.

### Daemon-vs-bridge race

**Symptom:** brief appears in `ready/` but bridge immediately moves it to
`running/` without spawning a workspace (workspace title missing).

- `dispatch-promoter` runs on the server; `cmux-bridge` runs on Mac. They
  communicate via SSH polling. If the Mac's SSH connection to the server has
  high latency or the bridge poll cycle was mid-sleep when the brief appeared,
  the promoter may have written `ready/X.yaml` at the exact moment bridge was
  executing a different brief's `mark_running` call.
- Check `running/X.yaml` — if `report_url` is empty and no CMUX workspace
  exists, manually `mv running/X.yaml ready/X.yaml` on the server to
  re-surface the brief for the bridge.

### SSH key path on Cowork

**Symptom:** `ssh` exits with `Permission denied (publickey)`.

1. The key is at `~/Documents/MzansiEdge/.cowork-ssh/id_ed25519` on the Mac,
   mounted into Cowork sandbox under
   `/sessions/<sandbox-id>/mnt/MzansiEdge/.cowork-ssh/`.
2. Use `find /sessions -name "id_ed25519" -path "*.cowork-ssh*" -print -quit`
   — **do not hardcode the sandbox ID**, it changes per session.
3. Verify key permissions: `chmod 600 "$KEY"` (SSH rejects world-readable
   keys).
4. If the server rejects the key, the `authorized_keys` entry may have been
   overwritten. Ask Paul to re-add the `.cowork-ssh` public key.

---

*Last updated: 2026-04-30 by AUDITOR Lane B (DOCS-DISPATCH-V2-CANONICAL-01)*
