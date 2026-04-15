# TMUX Startup Workspace

Server-safe tmux TERM for these commands is handled by the remote helper scripts. The direct server address resolved on March 18, 2026 is `37.27.179.53`.

Optional one-time or anytime bootstrap:

```bash
ssh paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_bootstrap.sh'
```

Ghostty startup commands, one per workspace tab or subtab:

```bash
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh core-control'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh core-leaddev-sonnet'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh core-leaddev-codex'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh core-leaddev-opus'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh core-qa-opus'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh core-qa-sonnet'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh core-server'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh web-build-opus'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh web-ux-opus'
ssh -t paulsportsza@37.27.179.53 '~/bin/mzansi_tmux_attach.sh web-qa-opus'
```

Session behavior:

- `core-control` and `core-server` open `bash` in `/home/paulsportsza/bot`.
- `core-leaddev-codex` starts `codex` in `/home/paulsportsza/bot`.
- `core-leaddev-sonnet` and `core-qa-sonnet` start `claude --model sonnet` in `/home/paulsportsza/bot`.
- `core-leaddev-opus`, `core-qa-opus`, `web-build-opus`, `web-ux-opus`, and `web-qa-opus` start `claude --model opus` in `/home/paulsportsza/bot`.
