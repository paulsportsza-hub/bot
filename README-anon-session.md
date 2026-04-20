# Telethon anon_session — Re-auth Runbook

## What is it?

`anon_session.session` is a Telethon file-based session authenticated to Paul's
personal Telegram account.  It lets automated scripts and QA tools connect to
Telegram as a real user — required for SO #38 visual QA (reading/screenshotting
messages the bot sends to channels and the test user).

**Owner account:** Paul's personal Telegram (the account that created this
session).  Not a bot account.

**Session file location:** `/home/paulsportsza/bot/anon_session.session`

---

## How to detect expiry

Any consumer script will raise one of these on connect:

```
telethon.errors.AuthKeyUnregisteredError
telethon.errors.AuthKeyError
```

Or `client.is_user_authorized()` returns `False`.

Quick check from the server:

```bash
cd /home/paulsportsza/bot
.venv/bin/python - <<'EOF'
import asyncio, os
os.environ.setdefault('TELEGRAM_API_ID', '32418601')
os.environ.setdefault('TELEGRAM_API_HASH', '95e313a8ef5b998be0515dd8328fac57')
from telethon import TelegramClient
async def check():
    c = TelegramClient("anon_session", int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'])
    await c.connect()
    ok = await c.is_user_authorized()
    print("VALID" if ok else "EXPIRED")
    await c.disconnect()
asyncio.run(check())
EOF
```

---

## How to re-authenticate

The bootstrap script is **idempotent** — it checks for a valid session first and
does nothing if the session is still good.

```bash
ssh -t paulsportsza@37.27.179.53 \
    'cd /home/paulsportsza/bot && .venv/bin/python bootstrap_anon_session.py'
```

1. The script asks for a phone number in international format (e.g. `+27821234567`).
2. Telegram sends a login code to Paul's phone (SMS or another Telegram session).
3. Type the code when prompted.
4. If 2FA is enabled, enter the password when prompted (press Enter if no 2FA).
5. The script confirms: `✅ Signed in as: Paul (@...)`

**The Telegram code is short-lived (≤ 5 minutes).**  Have the phone ready before
running the command.

To force a re-auth even when the session looks valid:

```bash
.venv/bin/python bootstrap_anon_session.py --force
```

---

## Who can run it?

Only Paul (or someone with access to Paul's phone for the Telegram code).  The
script requires interactive input — it cannot be run from a cron job or
unattended.

---

## API credentials

Stored in `/home/paulsportsza/bot/.env`:

```
TELEGRAM_API_ID=32418601
TELEGRAM_API_HASH=95e313a8ef5b998be0515dd8328fac57
```

These are the app credentials registered at my.telegram.org under Paul's account.
They do not expire.

---

## Backup policy

Before any re-auth, back up the old session:

```bash
cp /home/paulsportsza/bot/anon_session.session \
   /home/paulsportsza/bot/anon_session.session.bak-$(date +%Y-%m-%d)
```

The backup is useless for reconnecting (it's the expired session) but is useful
for forensics if something goes wrong.

---

## Consumers (files that break when session is invalid)

- `tests/telethon_ss_badge_verify.py` — visual QA for SO #38 badge checks
- `scripts/r5_ops_telethon.py`, `r7_qa_telethon.py`, `r10_qa_telethon.py`,
  `r15_qa_telethon.py` — wave QA scripts
- `scripts/qa_b14_run.py`, `qa_b28_pass2.py`, `qa_baseline_28_telethon.py` — build QA
- `scripts/qa30_telethon.py` — Telethon E2E run
