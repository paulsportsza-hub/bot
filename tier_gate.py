"""Content gating by subscription tier.

Thin middleware wrapping Dataminer B's tier-aware functions from
edge_v2_helper and narrative_generator. The bot calls these
functions at content touchpoints (Hot Tips, Game Breakdown, Tip Detail).

Wave 21: Bronze UX overhaul — list display is ungated (all edges visible).
Gating happens at card rendering (blurred/locked) and View Detail (3/day limit).

Tier behaviour:
    Bronze (free): See all edges in list (blurred/locked per tier), 3 detail views/day
    Gold (R99/mo):  Full access to Bronze+Silver+Gold edges, unlimited views
    Diamond (R199/mo): Full access to everything
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger("mzansiedge.tier_gate")

# Lazy imports — scrapers module may not be on sys.path during unit tests.
# Functions are imported at call time and cached.
_edge_v2_helper = None
_narrative_gen = None


def _ensure_edge_v2():
    """Lazy import of edge_v2_helper."""
    global _edge_v2_helper
    if _edge_v2_helper is None:
        from scrapers.edge import edge_v2_helper
        _edge_v2_helper = edge_v2_helper
    return _edge_v2_helper


def _ensure_narrative():
    """Lazy import of narrative_generator. Returns None if not available."""
    global _narrative_gen
    if _narrative_gen is None:
        try:
            from scrapers.edge import narrative_generator
            _narrative_gen = narrative_generator
        except ImportError:
            _narrative_gen = False  # Mark as unavailable
    return _narrative_gen if _narrative_gen is not False else None


# ── Tier access helpers ──────────────────────────────────────


def user_can_access_edge(user_tier: str, edge_tier: str) -> bool:
    """Check if a user's subscription tier can fully access an edge's tier.

    Returns True if the user has full access (odds, breakdown, etc.).
    Bronze can access: bronze, silver (partial — odds visible, breakdown gated)
    Gold can access: bronze, silver, gold
    Diamond can access: everything
    """
    tier = user_tier.lower().strip()
    edge = edge_tier.lower().strip()

    if tier == "diamond":
        return True
    if tier == "gold":
        return edge in ("bronze", "silver", "gold")
    # Bronze
    return edge in ("bronze", "silver")


def get_edge_access_level(user_tier: str, edge_tier: str) -> str:
    """Return the access level for a user viewing an edge.

    Returns:
        "full" — user has full access
        "partial" — odds visible, breakdown gated (Bronze viewing Silver)
        "blurred" — odds/bookmaker masked (Bronze viewing Gold)
        "locked" — existence only (Bronze viewing Diamond)
    """
    tier = user_tier.lower().strip()
    edge = edge_tier.lower().strip()

    if tier == "diamond":
        return "full"
    if tier == "gold":
        if edge == "diamond":
            return "locked"
        return "full"
    # Bronze
    if edge == "bronze":
        return "full"
    if edge == "silver":
        return "partial"
    if edge == "gold":
        return "blurred"
    return "locked"  # diamond


def gate_edges(
    edges: list[dict[str, Any]],
    user_id: int,
    user_tier: str,
    conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], int, str | None]:
    """Return all edges with remaining view count (Wave 21: no list filtering).

    Args:
        edges: list of edge result dicts
        user_id: Telegram user ID
        user_tier: "bronze", "gold", or "diamond"
        conn: sqlite3 connection to odds.db (for tip limit tracking)

    Returns:
        (all_edges, remaining_views, upgrade_message_or_None)
        remaining_views is 999 for unlimited tiers.
    """
    helper = _ensure_edge_v2()

    # Check daily tip limit (bronze = 3/day) — for display counter only
    can_view, remaining = helper.check_tip_limit(user_id, user_tier, conn)

    # Return ALL edges (no filtering) — rendering handles tier display
    return list(edges), remaining, None


def check_tip_limit(user_id: int, user_tier: str, conn: sqlite3.Connection) -> tuple[bool, int]:
    """Check daily tip limit for View Detail gating."""
    helper = _ensure_edge_v2()
    return helper.check_tip_limit(user_id, user_tier, conn)


def record_view(user_id: int, match_key: str, conn: sqlite3.Connection) -> None:
    """Record a tip view for daily limit tracking."""
    helper = _ensure_edge_v2()
    helper.record_tip_view(user_id, match_key, conn)


def gate_narrative(edge_v2_result: dict[str, Any], user_tier: str) -> str:
    """Generate tier-appropriate narrative for an edge result.

    Bronze: short generic summary (no specific odds/bookmakers)
    Gold: full verdict with all signal bullets + red flags
    Diamond: Gold + line movement + sharp money + CLV context
    """
    gen = _ensure_narrative()
    if gen is None:
        return ""
    try:
        return gen.generate_narrative_for_tier(edge_v2_result, user_tier)
    except Exception as e:
        log.debug("Narrative generation failed: %s", e)
        return ""


def _founding_member_line() -> str:
    """Return Founding Member line if window is active, else empty."""
    try:
        import datetime as _dt
        # config imported at module level may not exist — guard
        import config as _cfg
        launch = _dt.date.fromisoformat(_cfg.LAUNCH_DATE)
        deadline = launch + _dt.timedelta(days=_cfg.FOUNDING_MEMBER_DEADLINE_DAYS)
        remaining = (deadline - _dt.date.today()).days
        if remaining > 0:
            return f"\n🎁 Founding Member: R699/yr Diamond — {remaining} days left"
    except Exception:
        pass
    return ""


def get_upgrade_message(user_tier: str, context: str = "tip", proof_line: str = "") -> str:
    """Build a tier-appropriate upgrade prompt message.

    Args:
        user_tier: current user tier
        context: "tip" for tip limit, "edge" for locked edge content,
                 "gold_edge" for Gold-locked edge, "diamond_edge" for Diamond-locked
        proof_line: optional recent settlement proof shown ahead of the subscribe CTA
    """
    tier = user_tier.lower().strip()
    fm = _founding_member_line()

    def _with_proof(message: str) -> str:
        if not proof_line:
            return message
        marker = "\n\n/subscribe — View plans"
        if marker in message:
            return message.replace(marker, f"\n{proof_line}{marker}")
        return f"{message}\n\n{proof_line}"

    if tier == "bronze":
        if context == "tip":
            return _with_proof(
                (
                "🔒 <b>You've used your 3 free detail views for today.</b>\n\n"
                "You can still browse all edges in the list.\n\n"
                "🥇 <b>Upgrade to Gold</b> for unlimited detail views, "
                "real-time edges, and the full verdict line on every match.\n"
                f"💰 R99/mo or R799/yr (save 33%){fm}\n\n"
                "/subscribe — View plans"
                )
            )
        if context == "gold_edge":
            return _with_proof(
                (
                "🔒 <b>This is a 🥇 Gold Edge</b>\n\n"
                "Unlock full odds, the full verdict line, and signal analysis.\n\n"
                f"🥇 <b>Gold: R99/mo or R799/yr (save 33%)</b>{fm}\n\n"
                "/subscribe — View plans"
                )
            )
        if context == "diamond_edge":
            return _with_proof(
                (
                "🔒 <b>This is a 💎 Diamond Edge</b>\n\n"
                "Every edge unlocked — Diamond picks are Diamond-only.\n"
                "Personalised alerts tuned to your teams and bankroll.\n\n"
                f"💎 <b>Diamond: R199/mo or R1,599/yr (save 33%)</b>{fm}\n\n"
                "/subscribe — View plans"
                )
            )
        return _with_proof(
            (
            "🔒 This edge is available on a higher tier.\n\n"
            f"🥇 <b>Upgrade to Gold</b> to unlock all edges.{fm}\n\n"
            "/subscribe — View plans"
            )
        )

    if tier == "gold":
        return _with_proof(
            (
            "🔒 This is a 💎 <b>Diamond</b> feature.\n\n"
            "Every edge unlocked — Diamond picks are Diamond-only.\n"
            "Personalised alerts tuned to your teams and bankroll.\n"
            "Line movement + sharp money + CLV tracking.\n\n"
            f"💎 <b>Diamond: R199/mo or R1,599/yr (save 33%)</b>{fm}\n\n"
            "/subscribe — View plans"
            )
        )

    return ""  # Diamond users see everything
