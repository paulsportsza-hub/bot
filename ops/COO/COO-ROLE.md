# Edge COO — Operating Role

*Last updated: 2026-04-30 (DOCS-DISPATCH-V2-CANONICAL-01)*

## Purpose

The COO owns marketing operations, content publishing, channel health, and the
4-sweep daily cadence. See `reference/ROLE-EDGE-COO.md` for the full role spec.

## Dispatch

**COO dispatches via SSH-enqueue only.** No manual CMUX paste.

```bash
KEY=$(find /sessions -name "id_ed25519" -path "*.cowork-ssh*" -print -quit)
ssh -i "$KEY" -o StrictHostKeyChecking=no -o BatchMode=yes paulsportsza@37.27.179.53 \
  -- '--notion-url <NOTION-URL> --role edge_coo --mode <sequential|parallel>'
```

After `ssh` exits: `pending/` → promoter → `ready/` → bridge → CMUX.
COO's responsibility ends at enqueue. Bridge pastes the dispatch block and
spawns `claude`. Full architecture: `ops/DISPATCH-V2.md`.

## Mode guidance

- `sequential` — same git repo as another in-flight brief. Default.
- `parallel` — different git repos only.

## Key files owned by COO

- `ops/COO/COO-ROLE.md` (this file)
- `ops/COO/STATE.md`
- `ops/COO/ROUTING.md` (if exists)
- `ops/COO/TOOLS.md` (if exists)

AUDITOR Lane B proposes edits to these files. COO ratifies before merge.
