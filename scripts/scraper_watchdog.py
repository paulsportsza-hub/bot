#!/usr/bin/env python3
"""
Scraper watchdog — runs every 5 minutes via cron.
Detects: hung scraper process, stale DB writes, active DB lock.
Alerts to EdgeOps (internal Telegram channel) only.

Lock file format: /tmp/mzansi_scraper.lock — contains only a PID.
DB: /home/paulsportsza/scrapers/odds.db — scraped_at is ISO 8601 with TZ.
"""
import os
import sys
import time
import sqlite3
import datetime
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv

_SAST = ZoneInfo("Africa/Johannesburg")

# Load .env from bot working directory
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BOT_TOKEN = os.environ["BOT_TOKEN"]
EDGEOPS_CHAT_ID = "-1003877525865"
LOCK_FILE = "/tmp/mzansi_scraper.lock"
DB_PATH = "/home/paulsportsza/scrapers/odds.db"
MAX_LOCK_AGE_SECONDS = 300      # 5 minutes — kill if older
MAX_FRESHNESS_SECONDS = 900     # 15 minutes — alert if no new data
PEAK_HOURS_SAST = list(range(12, 24)) + [0]  # 12:00-00:00 SAST (= UTC 10:00-22:00)


def send_alert(message: str):
    """Send alert to EdgeOps internal channel only."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": EDGEOPS_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"Alert send failed: {e}", file=sys.stderr)


def check_lock_file():
    """Kill hung scraper if lock file mtime is too old."""
    if not os.path.exists(LOCK_FILE):
        return  # No scraper running — fine

    lock_age = time.time() - os.path.getmtime(LOCK_FILE)
    if lock_age < MAX_LOCK_AGE_SECONDS:
        return  # Running within expected time — fine

    # Lock is stale — read PID and attempt kill
    try:
        with open(LOCK_FILE) as f:
            pid = int(f.read().strip())
    except (ValueError, OSError) as e:
        send_alert(
            f"⚠️ <b>SCRAPER WATCHDOG:</b> Stale lock file but could not read PID: {e}\n"
            f"Lock age: {int(lock_age / 60)} min. Manual cleanup may be needed.\n"
            f"<code>rm {LOCK_FILE}</code>"
        )
        return

    # Verify the PID is actually alive before killing
    try:
        os.kill(pid, 0)  # Signal 0 = existence check, no actual kill
    except ProcessLookupError:
        # PID is already dead — stale lock with no live process
        os.remove(LOCK_FILE)
        print(f"Removed stale lock (PID {pid} already dead, lock age {lock_age:.0f}s)")
        return
    except PermissionError:
        pass  # Process exists but we can't signal it — fall through to kill attempt

    # PID is live and lock is too old — kill it
    try:
        os.kill(pid, 9)
        os.remove(LOCK_FILE)
        send_alert(
            f"⚠️ <b>SCRAPER WATCHDOG:</b> Killed hung scraper PID {pid}\n"
            f"Lock file age: {int(lock_age / 60)} min (max: {MAX_LOCK_AGE_SECONDS // 60} min)\n"
            f"Lock file removed. Next cron fire will start a fresh scraper."
        )
        print(f"Killed PID {pid}, lock age {lock_age:.0f}s")
    except (ProcessLookupError, PermissionError) as e:
        send_alert(
            f"⚠️ <b>SCRAPER WATCHDOG:</b> Stale lock (age {int(lock_age / 60)} min) "
            f"but could not kill PID {pid}: {e}"
        )


def check_data_freshness():
    """Alert if no new odds data written recently (peak hours only)."""
    if datetime.datetime.now(_SAST).hour not in PEAK_HOURS_SAST:
        return  # Off-peak — scraper runs less frequently, skip check

    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute(
            "SELECT MAX(scraped_at) FROM odds_snapshots"
        ).fetchone()
        conn.close()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            pass  # Will be caught by check_db_lock()
        else:
            print(f"Freshness check DB error: {e}", file=sys.stderr)
        return

    if not row or not row[0]:
        return

    last_write = row[0]
    try:
        # scraped_at is ISO 8601 with TZ, e.g. "2026-04-01T13:41:19.089796+00:00"
        dt = datetime.datetime.fromisoformat(str(last_write))
        now_sast = datetime.datetime.now(_SAST)
        age = (now_sast - dt).total_seconds()
    except (ValueError, TypeError) as e:
        print(f"Freshness check timestamp parse error: {e}", file=sys.stderr)
        return

    if age > MAX_FRESHNESS_SECONDS:
        send_alert(
            f"⚠️ <b>DATA FRESHNESS ALERT:</b> odds_snapshots last write was {int(age / 60)} min ago\n"
            f"Expected: &lt; {MAX_FRESHNESS_SECONDS // 60} min during peak hours\n"
            f"Last write: <code>{last_write}</code>\n"
            f"Possible scraper failure or DB lock."
        )


def check_db_lock():
    """Detect active DB write lock via BEGIN IMMEDIATE (2-second timeout)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=2)
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
        conn.close()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            send_alert(
                f"🚨 <b>DB LOCK DETECTED:</b> odds.db has an active write lock\n"
                f"BEGIN IMMEDIATE failed within 2s. Possible hung scraper.\n"
                f"Check: <code>ps aux | grep runner</code>\n"
                f"Check lock file: <code>cat {LOCK_FILE}</code>"
            )
        else:
            print(f"DB lock check error: {e}", file=sys.stderr)


if __name__ == "__main__":
    check_lock_file()
    check_data_freshness()
    check_db_lock()
    print(f"Watchdog OK — {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
