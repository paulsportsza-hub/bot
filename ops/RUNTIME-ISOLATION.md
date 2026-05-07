# Runtime Isolation — bot-prod tree

*Authored 2026-05-07 per FIX-BOT-RUNTIME-WORKTREE-ISOLATION-01 (T66) + OPS-DEPLOY-ON-MAIN-DISABLE-PENDING-T101-01 (T100). AUDITOR Lane B placement-gated.*

> **T66 driver:** dev edits in `/home/paulsportsza/bot/` were leaking into the
> live bot mid-session because Python imports modules lazily from disk.
> The bot-tree drift watchman surfaces the risk; T66 implemented the structural fix.
> **T100 driver:** CI auto-deploy workflow first run failed (empty `PROD_SSH_KEY`);
> auto-trigger disabled until T101 fixes the workflow design and secrets are configured.

---

## Live state

| Path | Role | Writable by `paulsportsza` | Owner of writes |
|---|---|---|---|
| `/home/paulsportsza/bot/` | dev tree (LEAD edits, wave-worktree base) | yes | dev / wave worktrees |
| `/home/paulsportsza/bot-prod/` | prod runtime (`mzansi-bot.service` reads from here) | NO (chmod u-w on every non-symlink) | none — frozen at deploy SHA |
| `/home/paulsportsza/bot-prod-prev/` | previous prod tree (rollback target) | n/a | rollback only |
| `/home/paulsportsza/bot-prod-failed/` | most recent failed deploy (post-rollback) | n/a | manual cleanup |
| `/home/paulsportsza/bot-data-shared/` | writable shared volume — DBs, reports, logs, bytecode cache | yes | bot-prod runtime via symlinks |
| `/home/paulsportsza/scrapers/` | sibling repo — `odds.db` lives here, accessed by both dev + prod | yes | scrapers + bot |

`bot-prod/` is structurally identical to a checked-out dev tree at the
deploy SHA, except:

- `bot-prod/data/`, `bot-prod/reports/`, `bot-prod/logs/`,
  `bot-prod/bet_log/` are symlinks into `bot-data-shared/`.
- `bot-prod/.venv/` is a symlink to `bot/.venv/` (avoids duplicating
  ~700 MB per deploy — see "Operational rules" below).
- Every regular file and non-symlinked directory has its user-write bit
  cleared.

`Path(__file__).parent.parent / "scrapers"` resolves to
`/home/paulsportsza/scrapers/` from BOTH bot/ and bot-prod/, so
`scrapers/odds.db` (the canonical 855 MB DB) needs no symlink — both
trees converge on the same physical file via the location-stable
relative path.

## systemd integration

`mzansi-bot.service` is unchanged. A drop-in override at
`/etc/systemd/system/mzansi-bot.service.d/exec-start.conf` re-points
`WorkingDirectory` and `ExecStart` to bot-prod/, and sets
`PYTHONPYCACHEPREFIX` to a writable bytecode cache inside the shared
volume so `chmod -R u-w` on bot-prod/ does not block bytecode caching.

Inspect the active unit with `systemctl cat mzansi-bot.service`.

## Manual deploy command

Until T101 ships, deploys are manual. From any machine with SSH access:

```bash
ssh paulsportsza@37.27.179.53 'bash /home/paulsportsza/bot-prod/scripts/deploy_bot_prod.sh <SHA>'
```

**Rollback** (if a deploy succeeds the script but a regression appears later):

```bash
ssh paulsportsza@37.27.179.53 'bash /home/paulsportsza/bot-prod/scripts/deploy_bot_prod_rollback.sh'
```

Atomic mv: prod → failed, prev → prod. Service restarts. Bot back on previous SHA.

### Deploy script detail

`scripts/deploy_bot_prod.sh <SHA>` (lives in `bot-prod/scripts/`, not `/home/paulsportsza/bot/scripts/`):

1. Verifies `<SHA>` is reachable from `origin/main` in the dev tree.
2. Builds a fresh `bot-prod-staging/` from a local clone of the dev
   tree's `.git`, checked out at `<SHA>`.
3. Replaces `staging/{data,reports,logs,bet_log}` with symlinks into
   `bot-data-shared/`. On a first deploy (shared subdirs empty) the
   script seeds the shared volume from the dev tree, preserving user
   state.
4. Replaces `staging/.venv` with a symlink to `bot/.venv`.
5. AST-parses `staging/bot.py` (cheap structural check).
6. Atomic-ish swap: `mv bot-prod -> bot-prod-prev`,
   `mv staging -> bot-prod`.
7. `chmod u-w` on every NON-symlink under `bot-prod/`. Symlinks are
   excluded so the shared volume stays writable.
8. `sudo systemctl restart mzansi-bot.service`, then waits up to 30s
   for `Startup Truth` to appear in `journalctl`. On regression the
   script invokes `deploy_bot_prod_rollback.sh` and exits non-zero.

## Rollback flow

`scripts/deploy_bot_prod_rollback.sh`:

1. Refuses if `bot-prod-prev/` does not exist.
2. Moves the current `bot-prod/` aside as `bot-prod-failed/` (any
   prior failed tree is overwritten).
3. Promotes `bot-prod-prev/` back to `bot-prod/`.
4. Restarts `mzansi-bot.service` and waits for `Startup Truth`.

After a rollback, the operator manually inspects `bot-prod-failed/`
and decides whether to remove or keep it for forensics. Forward-roll
of `bot-prod-prev/` (i.e. recovering the failed deploy) is not
automated; re-run `deploy_bot_prod.sh <SHA>` with the next good SHA.

## CI auto-deploy state — DISABLED

`.github/workflows/deploy-on-main.yml` is currently `workflow_dispatch`-only.
Auto-trigger on push to main was removed by T100 because:

1. `secrets.PROD_HOST`, `secrets.PROD_USER`, `secrets.PROD_SSH_KEY` are not
   configured on the repo — first run failed in 3s on empty `PROD_SSH_KEY`
   (commit 9a04332).
2. Workflow design currently invokes `bash /home/paulsportsza/bot/scripts/deploy_bot_prod.sh $SHA`
   — reads from the dev tree. Dev tree is not always on main, so the script may
   not exist on its current branch.

Manual workflow runs from the GitHub UI remain available for testing once secrets land.

## Re-enable AC (T101 — not yet authored)

T101 must satisfy ALL THREE before the auto-trigger is restored:

**(a) Secrets configured** on `paulsportsza-hub/bot` repo:
- `PROD_HOST` = `37.27.179.53`
- `PROD_USER` = `paulsportsza`
- `PROD_SSH_KEY` = private key of a **deploy-only** ed25519 keypair (NOT the
  existing `cowork-arbiter-mzansiedge` key — tighter scope, easier rotation)

Mint deploy key:
```bash
ssh-keygen -t ed25519 -f deploy_key -C "deploy-on-main-mzansiedge" -N ""
ssh paulsportsza@37.27.179.53 "cat >> ~/.ssh/authorized_keys" < deploy_key.pub
# paste deploy_key into GitHub Actions secret PROD_SSH_KEY
rm deploy_key deploy_key.pub  # never commit
```

**(b) Workflow design ratified** by AUDITOR Lane B — runner-side `actions/checkout@v4`
+ ssh-pipe pattern:

```yaml
steps:
  - uses: actions/checkout@v4
  - name: Deploy via ssh-pipe
    env:
      SHA: ${{ steps.sha.outputs.sha }}
    run: |
      ssh "${{ secrets.PROD_USER }}@${{ secrets.PROD_HOST }}" \
        'bash -s' < scripts/deploy_bot_prod.sh "$SHA"
```

This pattern is independent of local tree state on the prod box and ships the
script with the SHA being deployed (no chicken-and-egg if the script changes).

**(c) Trigger restored** in `.github/workflows/deploy-on-main.yml`:
restore the `push: branches: [main]` block AND remove the T100 disable comment.

## References

- **T66** — `FIX-BOT-RUNTIME-WORKTREE-ISOLATION-01` — runtime isolation foundation:
  bot-prod tree, systemd drop-in, deploy + rollback scripts.
- **T100** — `OPS-DEPLOY-ON-MAIN-DISABLE-PENDING-T101-01` — CI auto-trigger disabled;
  this runbook shipped here.
- **T101** — `OPS-DEPLOY-ON-MAIN-REENABLE-WITH-RUNNER-SIDE-CHECKOUT-01` — future brief,
  blocked on Paul minting the deploy-only SSH key.

## First-deploy runbook (one-time)

The brief lands as a series of file additions. Cutting over to bot-prod
for the first time:

1. Land all brief commits on `origin/main` (wave branch merged).
2. Confirm the dev tree's local origin/main matches the GitHub HEAD:

   ```bash
   git -C /home/paulsportsza/bot fetch origin
   git -C /home/paulsportsza/bot rev-parse origin/main
   ```

3. Drop the systemd override into place (requires sudo):

   ```bash
   sudo install -d -m 0755 /etc/systemd/system/mzansi-bot.service.d
   sudo tee /etc/systemd/system/mzansi-bot.service.d/exec-start.conf <<'CONF'
   [Service]
   WorkingDirectory=
   WorkingDirectory=/home/paulsportsza/bot-prod
   ExecStart=
   ExecStart=/home/paulsportsza/bot-prod/.venv/bin/python bot.py
   Environment=PYTHONPYCACHEPREFIX=/home/paulsportsza/bot-data-shared/pycache
   CONF
   sudo systemctl daemon-reload
   ```

4. Run the deploy script (the bot is still running from the dev tree at
   this point — the override only kicks in on the next restart):

   ```bash
   bash /home/paulsportsza/bot/scripts/deploy_bot_prod.sh "$(git -C /home/paulsportsza/bot rev-parse origin/main)"
   ```

5. Verify ACs (see below).

## AC verification (post-cutover)

```bash
# AC-4: ExecStart points at bot-prod
systemctl cat mzansi-bot.service | grep -F 'bot-prod/.venv/bin/python'

# AC-5: paulsportsza cannot edit bot-prod
touch /home/paulsportsza/bot-prod/bot.py 2>&1 \
    | grep -q 'Permission denied' && echo 'AC-5 ok'

# AC-2: wave_worktree_create.sh still derives from /home/paulsportsza/bot/
grep -F 'WAVE_REPO=/home/paulsportsza/bot' /home/paulsportsza/scripts/wave_worktree_create.sh

# AC-3: bot_tree_drift_check.sh still fires against /home/paulsportsza/bot/
grep -F 'BOT_TREE=/home/paulsportsza/bot' /home/paulsportsza/scripts/bot_tree_drift_check.sh

# Active service is using the new tree
systemctl show mzansi-bot --property=ExecStart --value | grep -F 'bot-prod'
```

## Operational rules

> **Hard rules — every agent, every session.**

1. Never `git`, `chmod`, `cp`, `mv`, `rm`, or `sudo` against
   `/home/paulsportsza/bot-prod/**` directly. All changes go through
   `scripts/deploy_bot_prod.sh`.
2. Wave worktrees are created from `/home/paulsportsza/bot/` (the dev
   tree). The runtime tree is invisible to dev work.
3. The bot-tree drift watchman (`scripts/bot_tree_drift_check.sh`)
   continues to fire against the dev tree. It is allowed to be noisy;
   the runtime is no longer affected.
4. `bot-prod/.venv` is a symlink to `bot/.venv`. Do not run
   `pip install` in `bot/.venv` while a deploy is in flight. After a
   pip-level upgrade, recycle the bot (`sudo systemctl restart
   mzansi-bot.service`) so it sees the upgraded packages.
5. `chmod -R u-w` on `bot-prod/` excludes symlinks. The shared volume
   (`bot-data-shared/`) stays writable. If you need to add a new
   writable subtree, update the `for sub in ...` loop in
   `deploy_bot_prod.sh` AND seed `bot-data-shared/<sub>/` before the
   next deploy.

## Failure modes & atomicity caveat

- **Power loss between `mv bot-prod bot-prod-prev` and
  `mv bot-prod-staging bot-prod`** (~100 ms window): on reboot,
  `bot-prod/` is missing and the service fails to start. Recovery:
  `mv bot-prod-prev bot-prod && sudo systemctl restart mzansi-bot`.
  A future iteration may switch to a symlink-flip pattern (`bot-prod`
  is a symlink to `bot-prod-r<n>`, deploys flip the symlink atomically
  via `ln -sfn`).
- **Forward-incompatible deploy rollback** (new deploy migrated the
  shared DB schema): a rollback script restores old binaries against
  new data. The unified persistence validator (Rule 21) is the existing
  guardrail, but operators should treat any migration as not-rollback-safe
  and verify schema compatibility before relying on auto-rollback.
- **`pip install` mid-deploy**: the `.venv` symlink means a pip
  operation in the dev tree is immediately visible to the running bot.
  Operator discipline: do not pip-install during a deploy window. If
  pip-level upgrade is needed, schedule it explicitly and recycle the
  service afterwards.
- **`__pycache__` writes**: prevented by `chmod -R u-w` on bot-prod.
  Mitigated by `PYTHONPYCACHEPREFIX=/home/paulsportsza/bot-data-shared/pycache`
  on the systemd unit so bytecode is cached in the shared volume.

## Out-of-scope follow-ups

- Migrating `scrapers/` to a similar prod-isolation model (separate
  brief).
- Migrating `publisher/` to a similar prod-isolation model (separate
  brief).
- Containerising the bot (Docker) — supersedes this scheme but is not
  required to deliver the isolation property.
- Replacing `wave_worktree_create.sh` — explicitly preserved (AC-2).
- `DOCS-SO-RUNTIME-PATH-ISOLATION-01` standing-order draft (AUDITOR-owned).
