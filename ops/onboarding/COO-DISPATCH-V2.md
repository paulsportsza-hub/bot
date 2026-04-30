# COO Onboarding — Dispatch V2

*Paste-ready message for the COO Cowork session. Last updated: 2026-04-30.*

---

## Dispatch system update (mandatory read)

The dispatch system was rebuilt end-to-end on 30 April 2026. **You no longer
paste dispatch blocks into CMUX. You no longer mv files between queue dirs.
Bridge handles all of that.**

**How it works (2 sentences):** You SSH-enqueue a brief by running one command
with the Notion URL and your role flag; the server queues it, a promoter service
moves it to `ready/` when deps clear, and the Mac-side bridge automatically
creates a CMUX workspace, spawns `mosh + claude`, and pastes the dispatch block.
Your job ends when `ssh` exits — the rest is automated.

---

## Your enqueue command (COO role)

```bash
KEY=$(find /sessions -name "id_ed25519" -path "*.cowork-ssh*" -print -quit)
ssh -i "$KEY" -o StrictHostKeyChecking=no -o BatchMode=yes paulsportsza@37.27.179.53 \
  -- '--notion-url <NOTION-URL> --role edge_coo --mode <sequential|parallel>'
```

Replace `<NOTION-URL>` with the full Notion page URL of the brief.
Replace `<sequential|parallel>` with the mode (see below).

---

## Mode selection

- **`sequential`** — use when this brief and any other currently in-flight brief
  touch the **same git repo**. This is the safe default.
- **`parallel`** — use only when this brief targets a **completely different
  git repo** from every other brief in `pending/`, `ready/`, or `running/`.
- **When in doubt: `sequential`.**

---

## What you no longer do

- You no longer paste dispatch blocks into CMUX.
- You no longer `mv` YAML files between queue dirs on the server.
- You no longer start `mosh` or `claude` manually in a CMUX tab.

Bridge handles all of that automatically.

---

## Full reference

`ops/DISPATCH-V2.md` — pipeline diagram, promoter rules, bridge behaviour,
workspace title format, troubleshooting playbook.

Bridge log (ask Paul to grep if something looks stuck):
`~/Library/Logs/cmux-bridge.log`
