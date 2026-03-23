# LEADDEV-REPORT-DAY9.md

**Agent:** LeadDev
**Date:** 2026-02-25
**Branch:** `feature/multi-bookmaker`
**Commit:** `cf9dbcd`

---

## PRIORITY 1: Bug Fixes

### BUG-009: Keyless leagues produce 404-style errors — FIXED

**Root cause:** Many leagues in `config.SPORTS` have `api_key=None` (e.g. URC, Super Rugby, Currie Cup, ATP, WTA, PGA, F1, MotoGP — 20+ leagues). When users follow these leagues, multiple code paths attempted to fetch data using the raw league key (e.g. "urc") as the Odds API sport key, producing 404 responses.

**5 code paths fixed:**

| Location | Line | Problem | Fix |
|----------|------|---------|-----|
| `_fetch_schedule_games()` | ~2993 | Called `fetch_events_for_league(lk)` for keyless leagues → 404 API calls | Skip leagues without `config.SPORTS_MAP` entry |
| `_render_your_games_all()` | ~2196 | Showed generic "No upcoming games" with no explanation | Detects keyless leagues, tells user which leagues lack data + suggests adding EPL/PSL/NBA |
| `_render_your_games_sport()` | ~2394 | Same generic "No games on {date}" | Detects sports with no API leagues, shows "doesn't have live odds data yet" |
| `handle_ai()` | ~937 | Called Claude with empty odds context → hallucinated tips | Returns early with "No odds data available for this sport" message |
| `_generate_game_tips()` | ~3254 | Used `SPORTS_MAP.get(target_league, target_league)` fallback → 404 | Returns early with "Odds data isn't available for this league yet" + back button |

**Already safe (no fix needed):**
- `get_picks_for_user()` — already skips leagues without `api_key` (line 75)
- `handle_sport()` — already shows "⚠️ Odds not available" when `api_key` is None
- `_check_edges_for_games()` — already sets `edge=False` for keyless leagues
- `_fetch_hot_tips_all_sports()` — uses hardcoded `HOT_TIPS_SCAN_SPORTS` (all valid API keys)
- `_do_hot_tips_flow()` — shows "No edges found" when tips list is empty

---

### BUG-010: No systemd service file — FIXED (Day 8) + HARDENED (Day 9)

**Day 8 (commit a1f219d):** Created `mzansiedge.service` and `scripts/install-service.sh`.

**Day 9 hardening:**
- Added `EnvironmentFile=/home/paulsportsza/bot/.env` so systemd loads env vars
- Changed `RestartSec=10` → `RestartSec=5` per brief
- Install script now uses `ln -sf` (symlink) instead of `cp` (copy)
- Install script no longer auto-starts — prints instructions instead

**Final service file:**
```ini
[Unit]
Description=MzansiEdge Telegram Bot
After=network.target

[Service]
Type=simple
User=paulsportsza
WorkingDirectory=/home/paulsportsza/bot
EnvironmentFile=/home/paulsportsza/bot/.env
ExecStart=/usr/bin/python3 /home/paulsportsza/bot/bot.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

---

### BUG-011: No duplicate instance protection — FIXED (Day 8)

**Implemented in commit a1f219d.** PID file lock at `/tmp/mzansiedge.pid`:
- `_acquire_pid_lock()` called at top of `main()` before `Application.builder()`
- If another instance is alive (`os.kill(pid, 0)`) → logs error + exits code 1
- Stale PID files cleaned automatically (ProcessLookupError/ValueError)
- Cleanup registered via `atexit`, `SIGTERM`, and `SIGINT` handlers

No changes needed on Day 9.

---

## PRIORITY 2: Branch Merge Analysis

### Branch Status

| Branch | Commits ahead of main | Status |
|--------|----------------------|--------|
| `feature/multi-bookmaker` | 8 | Active — all Day 6-9 work |
| `ux/playbook-conventions-day6` | 8 | Fully merged into multi-bookmaker |
| `feature/stitch-integration` | 6 | Separate — Stitch payment integration |

### Key finding: ux branch is already merged

`ux/playbook-conventions-day6` is an ancestor of `feature/multi-bookmaker` (fast-forward merged). No action needed — can be deleted.

### Merge: stitch-integration into multi-bookmaker

**Overlapping files (5):** `bot.py`, `config.py`, `pytest.ini`, `services/analytics.py`, `tests/test_bot_handlers.py`

**Conflict analysis (3 files, 6 hunks):**

| File | Hunks | Severity | Resolution |
|------|-------|----------|------------|
| `bot.py` | 3 | HIGH | Stitch re-adds BUG-008 logging (duplicate — take ours). Hot Tips rendering conflicts (two approaches — take our consolidated single-message with `html.escape()`). |
| `config.py` | 1 | MEDIUM | Both add PostHog config. Stitch also adds Paystack + Stitch keys. Keep both — additive merge. |
| `services/analytics.py` | 2 | LOW | Different PostHog wrapper implementations. Take ours (more robust `try/except ImportError`). |

**Auto-resolved (no conflicts):** `pytest.ini`, `tests/test_bot_handlers.py`

**Safe stitch-only files (6):** `CLAUDE.md`, `db.py`, `services/paystack_service.py`, `services/stitch_mock.py`, `services/stitch_service.py`, `tests/test_e2e_flow.py`

### Recommended merge order

1. **Delete `ux/playbook-conventions-day6`** — already in multi-bookmaker
2. **Merge `feature/stitch-integration` into `feature/multi-bookmaker`** — manual resolution needed for `bot.py` (Hot Tips), `config.py` (additive), `services/analytics.py` (take ours)
3. **Merge `feature/multi-bookmaker` into `main`** — clean after step 2

### Concerns

- **`bot.py` Hot Tips conflict is the biggest risk.** Stitch sends individual messages per tip with Betway affiliate buttons. Multi-bookmaker sends a single consolidated message with `[1]-[5]` numbered format + `html.escape()`. These are fundamentally different UX patterns. Recommend keeping multi-bookmaker's approach (matches UX audit recommendations) and porting the Betway affiliate button to the consolidated footer.
- The stitch branch also ports in the Sentry init at top of `bot.py` which multi-bookmaker doesn't have. This should be preserved during merge.

---

## Verification

| Check | Result |
|-------|--------|
| `ast.parse(bot.py)` | PASS |
| `ast.parse(config.py)` | PASS |
| `pytest tests/ -x -q` | 281 passed, 3.56s |
| Service file valid | PASS |
| PID lock functional test | PASS (Day 8) |

---

## Files Changed (Day 9)

| File | Action | Bug |
|------|--------|-----|
| `bot.py` | MODIFIED | BUG-009 — 5 code path fixes |
| `mzansiedge.service` | MODIFIED | BUG-010 — EnvironmentFile, RestartSec=5 |
| `scripts/install-service.sh` | MODIFIED | BUG-010 — symlink, no auto-start |
