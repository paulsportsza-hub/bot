# Runtime Isolation — bot-prod read-only checkout

> **Brief:** FIX-BOT-RUNTIME-WORKTREE-ISOLATION-01 (LEAD, 7 May 2026).
> **Driver:** dev edits in `/home/paulsportsza/bot/` were leaking into the
> live bot mid-session because Python imports modules lazily from disk.
> The bot-tree drift watchman surfaces the risk; this document specifies
> the structural fix.

---

## Directory layout

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

## Deploy flow

`scripts/deploy_bot_prod.sh <SHA>`:

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

**Manual deploy (current):** run the script directly on the server:

```bash
bash /home/paulsportsza/bot/scripts/deploy_bot_prod.sh <SHA>
```

The script must always run from a writable location (the dev tree) to avoid a
bootstrap problem when the script itself changes.

**CI auto-deploy: DISABLED** (brief `OPS-CI-DEPLOY-ON-MAIN-DISABLE-01`, 2026-05-07).
`.github/workflows/deploy-on-main.yml` was originally authored to SSH the prod
host on every push to `main`, but the push trigger has been removed because three
required secrets (`PROD_HOST`, `PROD_USER`, `PROD_SSH_KEY`) are not yet configured
on `paulsportsza-hub/bot`. Re-enable AC: provision those secrets + ratify the
invocation path (runner checkout vs `/home/paulsportsza/bot-prod/scripts/…`) in
brief `OPS-CI-DEPLOY-ON-MAIN-RE-ENABLE-01`. `workflow_dispatch:` remains active for
manual triggers from the GitHub Actions UI.

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
