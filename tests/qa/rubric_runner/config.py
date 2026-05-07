"""Runner-specific config (separate from bot config.py).

BUILD-QA-RUBRIC-RUNNER-01 — Phase A
"""
from __future__ import annotations

# OCR version switch — V2 adds extended fields (supersport_logo, kickoff, etc.)
USE_OCR_V2: bool = True

# Payment mock — ALWAYS True in rubric runner; never hit real Stitch
STITCH_MOCK_MODE: bool = True

# Evidence retention
EVIDENCE_RETENTION_DAYS: int = 30

# Paths
SCREENSHOT_DIR: str = "/home/paulsportsza/reports/rubric_runner/screenshots"
REPORT_DIR: str = "/home/paulsportsza/reports/rubric_runner"

# Bot under test
BOT_USERNAME: str = "mzansiedge_bot"

# Telethon timeouts (seconds)
BOT_REPLY_TIMEOUT: int = 45    # default wait for a bot response (cold-start can take ~15s)
PICKS_TIMEOUT: int = 60        # wait for edge picks list (slower surface)

# Telethon session (relative to bot/ CWD)
SESSION_PATH: str = "data/telethon_qa_session.string"

# Database paths (relative to bot/ CWD)
ODDS_DB_PATH: str = "data/odds.db"
MAIN_DB_PATH: str = "data/mzansiedge.db"
