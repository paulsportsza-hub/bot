# Edge COO — Active State

*Last updated: 2026-04-30 (DOCS-DISPATCH-V2-CANONICAL-01)*

## Current Status

| Item | Value |
|------|-------|
| Snapshot date | 2026-04-30 |
| Top priority | Dispatch V2 rollout — all Cowork sessions updated to SSH-enqueue |
| Blockers | None |

## Dispatch system — updated 2026-04-30

COO dispatches via SSH-enqueue exclusively. The old manual-paste workflow is
retired. See `ops/DISPATCH-V2.md` for full architecture.

```bash
KEY=$(find /sessions -name "id_ed25519" -path "*.cowork-ssh*" -print -quit)
ssh -i "$KEY" -o StrictHostKeyChecking=no -o BatchMode=yes paulsportsza@37.27.179.53 \
  -- '--notion-url <NOTION-URL> --role edge_coo --mode <sequential|parallel>'
```

## Active briefs

*(Update before closing every session.)*

| Brief ID | Status | Notes |
|----------|--------|-------|
| — | — | — |

## Recent decisions

| Date | Decision | Ratified by |
|------|----------|------------|
| 2026-04-30 | Dispatch V2 locked; SSH-enqueue is the only dispatch path | Paul |
