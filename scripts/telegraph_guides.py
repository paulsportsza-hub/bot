"""MzansiEdge — Telegra.ph betting guides for SA bookmakers.

Creates and caches Telegraph pages with step-by-step betting guides.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

import config

log = logging.getLogger("mzansiedge.telegraph")

TELEGRAPH_API = "https://api.telegra.ph"
TOKEN_FILE = config.DATA_DIR / "telegraph_token.json"
URLS_FILE = config.DATA_DIR / "telegraph_urls.json"


# ── Guide content per bookmaker ──────────────────────────

BOOKMAKER_GUIDES: dict[str, dict] = {
    "betway": {
        "title": "How to Bet on Betway SA — Complete Guide (2026)",
        "content": [
            {"tag": "p", "children": [
                {"tag": "i", "children": [
                    "A step-by-step guide from MzansiEdge — your AI sports betting assistant."
                ]},
            ]},
            {"tag": "h3", "children": ["🔑 1. Create Your Betway Account"]},
            {"tag": "p", "children": [
                "Go to ", {"tag": "b", "children": ["betway.co.za"]},
                " and tap ", {"tag": "b", "children": ["Register"]}, ".",
            ]},
            {"tag": "p", "children": [
                "You'll need:",
            ]},
            {"tag": "ul", "children": [
                {"tag": "li", "children": ["Full name and email address"]},
                {"tag": "li", "children": ["SA ID number (must be 18+)"]},
                {"tag": "li", "children": ["A password you'll remember"]},
                {"tag": "li", "children": ["Your mobile number for OTP verification"]},
            ]},
            {"tag": "p", "children": [
                "Registration takes about 2 minutes.",
            ]},
            {"tag": "h3", "children": ["✅ 2. Verify Your Account (FICA)"]},
            {"tag": "p", "children": [
                "Betway requires FICA verification before you can withdraw.",
                " Upload a clear photo of your SA ID or passport.",
                " Verification is usually approved within a few hours — you can deposit and bet while waiting.",
            ]},
            {"tag": "h3", "children": ["💰 3. Make Your First Deposit"]},
            {"tag": "p", "children": [
                "Tap ", {"tag": "b", "children": ["Deposit"]},
                " and choose from these options:",
            ]},
            {"tag": "ul", "children": [
                {"tag": "li", "children": [{"tag": "b", "children": ["Ozow (Instant EFT)"]}, " — Fastest option. Links to FNB, Standard Bank, Capitec, Nedbank, Absa."]},
                {"tag": "li", "children": [{"tag": "b", "children": ["Credit/Debit Card"]}, " — Visa or Mastercard."]},
                {"tag": "li", "children": [{"tag": "b", "children": ["Bank Transfer (EFT)"]}, " — Manual transfer, takes 1-2 hours."]},
                {"tag": "li", "children": [{"tag": "b", "children": ["Voucher"]}, " — Buy a Betway voucher at selected retailers."]},
            ]},
            {"tag": "p", "children": [
                "Minimum deposit: ", {"tag": "b", "children": ["R10"]}, ".",
                " We recommend starting with R100-R500 for your first week.",
            ]},
            {"tag": "h3", "children": ["🎯 4. Place Your First Bet"]},
            {"tag": "p", "children": [
                "Here's how to place a bet on Betway:",
            ]},
            {"tag": "ol", "children": [
                {"tag": "li", "children": ["Browse ", {"tag": "b", "children": ["Sports"]}, " or use the search bar to find your match"]},
                {"tag": "li", "children": ["Tap the ", {"tag": "b", "children": ["odds"]}, " you want — it adds to your bet slip"]},
                {"tag": "li", "children": ["Enter your ", {"tag": "b", "children": ["stake amount"]}, " (how much you want to bet)"]},
                {"tag": "li", "children": ["Check the potential payout at the bottom"]},
                {"tag": "li", "children": ["Tap ", {"tag": "b", "children": ["Place Bet"]}, " to confirm"]},
            ]},
            {"tag": "p", "children": [
                {"tag": "b", "children": ["Pro tip:"]},
                " Start with single bets (one outcome) while you're learning.",
                " Accumulators are tempting but much harder to win.",
            ]},
            {"tag": "h3", "children": ["💵 5. Withdraw Your Winnings"]},
            {"tag": "p", "children": [
                "When you're ready to cash out:",
            ]},
            {"tag": "ol", "children": [
                {"tag": "li", "children": ["Go to ", {"tag": "b", "children": ["My Account → Withdraw"]}]},
                {"tag": "li", "children": ["Enter your SA bank details (FNB, Standard Bank, Capitec, Nedbank, or Absa)"]},
                {"tag": "li", "children": ["Enter the amount you want to withdraw"]},
                {"tag": "li", "children": ["Confirm — withdrawals usually arrive within ", {"tag": "b", "children": ["24 hours"]}]},
            ]},
            {"tag": "p", "children": [
                {"tag": "i", "children": ["Note: You must be FICA-verified before your first withdrawal."]}
            ]},
            {"tag": "h3", "children": ["📱 6. Get the Betway App"]},
            {"tag": "p", "children": [
                "Betway has a mobile app for Android and iOS.",
                " Download it from betway.co.za for the best experience — quicker bets, push notifications for your games, and easy deposits.",
            ]},
            {"tag": "hr"},
            {"tag": "p", "children": [
                {"tag": "i", "children": [
                    "Guide by MzansiEdge. Always gamble responsibly. 18+ only. National Responsible Gambling Programme: 0800 006 008."
                ]},
            ]},
        ],
    },
    "sportingbet": {
        "title": "How to Bet on SportingBet SA — Step by Step",
        "content": [
            {"tag": "h3", "children": ["1. Sign Up"]},
            {"tag": "p", "children": [
                "Visit ", {"tag": "b", "children": ["sportingbet.co.za"]},
                " and tap ", {"tag": "b", "children": ["Join Now"]}, ".",
                " Enter your details and SA ID number."
            ]},
            {"tag": "h3", "children": ["2. Deposit"]},
            {"tag": "p", "children": [
                "Use Ozow instant EFT, card, or bank transfer.",
                " Most deposits are instant."
            ]},
            {"tag": "h3", "children": ["3. Place a Bet"]},
            {"tag": "p", "children": [
                "Navigate to your sport, tap the odds to add to your slip,",
                " enter your stake, and confirm."
            ]},
            {"tag": "h3", "children": ["4. Withdraw"]},
            {"tag": "p", "children": [
                "Withdrawals go to your verified SA bank account.",
                " Processing time is typically 24-48 hours."
            ]},
            {"tag": "p", "children": [{"tag": "i", "children": ["Always gamble responsibly. 18+ only."]}]},
        ],
    },
    "10bet": {
        "title": "How to Bet on 10Bet SA — Step by Step",
        "content": [
            {"tag": "h3", "children": ["1. Sign Up"]},
            {"tag": "p", "children": [
                "Go to ", {"tag": "b", "children": ["10bet.co.za"]},
                " and register with your SA details."
            ]},
            {"tag": "h3", "children": ["2. Deposit"]},
            {"tag": "p", "children": [
                "Use instant EFT, card, or SID Instant EFT.",
                " Minimum deposit is R20."
            ]},
            {"tag": "h3", "children": ["3. Place a Bet"]},
            {"tag": "p", "children": [
                "Browse sports, tap odds to build your bet slip,",
                " enter stake and confirm."
            ]},
            {"tag": "h3", "children": ["4. Withdraw"]},
            {"tag": "p", "children": [
                "Request withdrawals to your bank account.",
                " Usually processed within 24 hours."
            ]},
            {"tag": "p", "children": [{"tag": "i", "children": ["Always gamble responsibly. 18+ only."]}]},
        ],
    },
    "playabets": {
        "title": "How to Bet on PlayaBets SA — Step by Step",
        "content": [
            {"tag": "h3", "children": ["1. Sign Up"]},
            {"tag": "p", "children": [
                "Visit ", {"tag": "b", "children": ["playabets.co.za"]},
                " and create your account with SA ID verification."
            ]},
            {"tag": "h3", "children": ["2. Deposit"]},
            {"tag": "p", "children": [
                "Choose from EFT, Ozow, vouchers, or card.",
                " Deposits are quick and easy."
            ]},
            {"tag": "h3", "children": ["3. Place a Bet"]},
            {"tag": "p", "children": [
                "Find your sport, select odds, set your stake, and place the bet."
            ]},
            {"tag": "h3", "children": ["4. Withdraw"]},
            {"tag": "p", "children": [
                "Cash out to your SA bank account.",
                " Processed within 1-2 business days."
            ]},
            {"tag": "p", "children": [{"tag": "i", "children": ["Always gamble responsibly. 18+ only."]}]},
        ],
    },
    "supabets": {
        "title": "How to Bet on SupaBets SA — Step by Step",
        "content": [
            {"tag": "h3", "children": ["1. Sign Up"]},
            {"tag": "p", "children": [
                "Go to ", {"tag": "b", "children": ["supabets.co.za"]},
                " and register. You'll need your SA ID."
            ]},
            {"tag": "h3", "children": ["2. Deposit"]},
            {"tag": "p", "children": [
                "Use Ozow, card, bank transfer, or retail vouchers.",
                " Min deposit is R10."
            ]},
            {"tag": "h3", "children": ["3. Place a Bet"]},
            {"tag": "p", "children": [
                "Browse markets, tap to select, enter stake, and confirm."
            ]},
            {"tag": "h3", "children": ["4. Withdraw"]},
            {"tag": "p", "children": [
                "Withdraw to your SA bank account.",
                " Usually arrives within 24 hours."
            ]},
            {"tag": "p", "children": [{"tag": "i", "children": ["Always gamble responsibly. 18+ only."]}]},
        ],
    },
}


# ── Telegraph API helpers ────────────────────────────────

def _load_token() -> str | None:
    """Load saved Telegraph token."""
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text()).get("access_token")
        except Exception:
            pass
    return None


def _save_token(token: str) -> None:
    """Save Telegraph token to disk."""
    TOKEN_FILE.write_text(json.dumps({"access_token": token}))


def _load_urls() -> dict[str, str]:
    """Load cached Telegraph page URLs."""
    if URLS_FILE.exists():
        try:
            return json.loads(URLS_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_urls(urls: dict[str, str]) -> None:
    """Save Telegraph page URLs to disk."""
    URLS_FILE.write_text(json.dumps(urls))


async def _ensure_account() -> str:
    """Get or create a Telegraph account. Returns access token."""
    token = _load_token()
    if token:
        return token

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{TELEGRAPH_API}/createAccount", json={
            "short_name": "MzansiEdge",
            "author_name": "MzansiEdge Bot",
            "author_url": "https://t.me/MzansiEdgeBot",
        })
        resp.raise_for_status()
        data = resp.json()
        token = data["result"]["access_token"]
        _save_token(token)
        return token


async def _create_page(token: str, title: str, content: list[dict]) -> str:
    """Create a Telegraph page. Returns the page URL."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{TELEGRAPH_API}/createPage", json={
            "access_token": token,
            "title": title,
            "author_name": "MzansiEdge",
            "content": content,
            "return_content": False,
        })
        resp.raise_for_status()
        return resp.json()["result"]["url"]


async def get_guide_url(bookmaker_key: str) -> str | None:
    """Get the Telegraph guide URL for a bookmaker.

    Creates the page on first call, returns cached URL thereafter.
    """
    urls = _load_urls()
    if bookmaker_key in urls:
        return urls[bookmaker_key]

    guide = BOOKMAKER_GUIDES.get(bookmaker_key)
    if not guide:
        return None

    try:
        token = await _ensure_account()
        url = await _create_page(token, guide["title"], guide["content"])
        urls[bookmaker_key] = url
        _save_urls(urls)
        log.info("Created Telegraph guide for %s: %s", bookmaker_key, url)
        return url
    except Exception as exc:
        log.error("Failed to create Telegraph guide for %s: %s", bookmaker_key, exc)
        return None


async def ensure_active_guide() -> str | None:
    """Pre-publish the guide for the active bookmaker and wire URL into config.

    Call this at bot startup to ensure the guide URL is ready.
    Returns the URL or None on failure.
    """
    bk_key = config.ACTIVE_BOOKMAKER
    url = await get_guide_url(bk_key)
    if url:
        config.SA_BOOKMAKERS[bk_key]["guide_url"] = url
        log.info("Active bookmaker guide URL wired: %s", url)
    return url
