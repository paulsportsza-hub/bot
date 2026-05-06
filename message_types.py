"""P3-02 / P3-04 — Message Type System for MzansiEdge bot.

Four canonical message builders:

  DigestMessage   — Compact digest of today's picks (≤4096 chars, max 7 items).
                    Each item has an inline button → editMessageText drill-down.
  DetailMessage   — Full analysis for one pick: narrative, odds, injuries,
                    expandable blockquote, ← Back button.
  AlertMessage    — Pre-match Gold/Diamond alert (audible, single CTA).
  ResultMessage   — Post-match outcome (silent, compact result + running totals).

Design rules
------------
- Pure renderers: no async, no DB calls, no bot state.
- Callers in bot.py pre-compute:
    • Callback keys via _shorten_cb_key() (bot.py's existing function)
    • Kickoff/broadcast strings from _get_broadcast_details()
    • disable_notification flag on send_message / send_notification calls
- All callback data ≤64 bytes (Telegram API limit).
- HTML parse_mode throughout. <blockquote expandable> requires Bot API 7.3+.

Edge cases handled
------------------
- 0 picks: "No Edges today" empty state
- Pick with no narrative: ⚠️ indicator in digest
- Stale digest button (bot restart cleared key map): is_stale_hash() + expired_response()
- Old digest button tapped: "This digest has expired. Send /today for fresh picks."
"""

from __future__ import annotations

from html import escape as h
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ── Tier display (mirrors renderers/edge_renderer.py) ───────────────────────

EDGE_EMOJIS: dict[str, str] = {
    "diamond": "💎",
    "gold": "🥇",
    "silver": "🥈",
    "bronze": "🥉",
}

EDGE_LABELS: dict[str, str] = {
    "diamond": "DIAMOND EDGE",
    "gold": "GOLDEN EDGE",
    "silver": "SILVER EDGE",
    "bronze": "BRONZE EDGE",
}

# ── Constants ────────────────────────────────────────────────────────────────

_MSG_MAX_CHARS: int = 4096  # Telegram message character limit
_HASH_LENGTH: int = 10      # MD5[:10] — length of bot.py _shorten_cb_key hashes


# ── Utility: stale hash detection ───────────────────────────────────────────

def is_stale_hash(key: str) -> bool:
    """Return True if *key* looks like a _shorten_cb_key hash that is no longer
    in the key map (e.g. after bot restart).

    Heuristic: exactly 10 lowercase hex chars.  Full match_keys always contain
    underscores or hyphens (e.g. 'sundowns_vs_pirates_2026-04-06') so this is
    a reliable discriminant.
    """
    return (
        len(key) == _HASH_LENGTH
        and key == key.lower()
        and all(c in "0123456789abcdef" for c in key)
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

_BK_DISPLAY_MAP: dict[str, str] = {
    "hollywoodbets": "Hollywoodbets",
    "betway": "Betway",
    "gbets": "GBets",
    "sportingbet": "Sportingbet",
    "supabets": "Supabets",
    "playabets": "Playabets",
    "wsb": "WSB",
    "supersportbet": "SuperSportBet",
}


def _bk_display(key: str) -> str:
    """Return human-readable bookmaker name from internal key."""
    return _BK_DISPLAY_MAP.get(key.lower(), key.title())


def _abbr(name: str, max_len: int = 4) -> str:
    """Build a short team abbreviation for button labels.

    Multi-word names → initials (e.g. "Kaizer Chiefs" → "KC").
    Single-word names → first *max_len* chars uppercased.
    """
    parts = name.split()
    if len(parts) >= 2:
        return "".join(p[0].upper() for p in parts[:3])
    return name[:max_len].upper()


def _confidence_label(tier: str, tone_band: str = "") -> str:
    """Return a user-friendly confidence string."""
    _tone_map: dict[str, str] = {
        "conviction": "Very high confidence",
        "confident": "High confidence",
        "strong": "Strong conviction",
        "moderate": "Moderate confidence",
        "lean": "Moderate confidence",
        "cautious": "Low confidence",
        "speculative": "Speculative",
    }
    _tier_map: dict[str, str] = {
        "diamond": "Very high confidence",
        "gold": "High confidence",
        "silver": "Moderate confidence",
        "bronze": "Low confidence",
    }
    if tone_band:
        label = _tone_map.get(tone_band.lower(), "")
        if label:
            return label
    return _tier_map.get(tier.lower(), "")


# ── DigestMessage ────────────────────────────────────────────────────────────

class DigestMessage:
    """Compact digest of today's top picks.

    Format per item::

        [N] {tier_emoji} {sport} {Home} vs {Away}
            {kickoff} · {confidence}

    Max 7 items (Miller's Law).  Each item has one inline button that triggers
    ``editMessageText`` via the existing ``edge:detail:{cb_key}`` callback.

    When the picks list is empty, an empty-state is returned with a Refresh
    button.

    Stale digest detection
    ~~~~~~~~~~~~~~~~~~~~~~
    After a bot restart the ``_cb_key_map`` in bot.py is cleared, so hashed
    callback keys from old digest messages can no longer be resolved.  When
    the ``edge:detail`` handler detects this (via :func:`is_stale_hash`), it
    should call :meth:`expired_response` and return early.
    """

    MAX_ITEMS: int = 7

    @staticmethod
    def build(
        picks: list[dict],
        *,
        title: str = "Today's Edge Picks",
        stats_summary: str = "",
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Build digest text + keyboard.

        Parameters
        ----------
        picks:
            List of tip dicts.  Each dict should include:

            * ``cb_key`` (str) — pre-shortened callback key (≤52 chars),
              computed by bot.py via ``_shorten_cb_key(match_key)``.
            * ``display_tier`` / ``edge_rating`` (str) — diamond/gold/silver/bronze.
            * ``home_team``, ``away_team`` (str).
            * ``kickoff`` / ``_bc_kickoff`` (str) — pre-formatted kickoff display.
            * ``confidence`` / ``tone_band`` (str, optional) — for label.
            * ``has_narrative`` (bool, optional) — False → ⚠️ shown.
            * ``sport_emoji`` (str, optional).

        title:
            Header title (default "Today's Edge Picks").

        stats_summary:
            Optional pre-rendered HTML for an expandable performance stats blockquote
            shown below the pick list.  E.g. "7-day hit rate: 68% · ROI +14.2%".

        Returns
        -------
        (text, InlineKeyboardMarkup)
        """
        picks = picks[: DigestMessage.MAX_ITEMS]

        if not picks:
            return DigestMessage._empty_state()

        lines: list[str] = [
            f"🔥 <b>{h(title)}</b>",
            "",
        ]
        buttons: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []

        for i, pick in enumerate(picks, start=1):
            tier = (
                pick.get("display_tier") or pick.get("edge_rating") or "bronze"
            ).lower()
            tier_emoji = EDGE_EMOJIS.get(tier, "🥉")
            home_raw = pick.get("home_team") or "Home"
            away_raw = pick.get("away_team") or "Away"
            home = h(home_raw)
            away = h(away_raw)
            kickoff = pick.get("kickoff") or pick.get("_bc_kickoff") or ""
            sport_emoji = pick.get("sport_emoji") or "🏅"
            confidence = _confidence_label(
                tier,
                pick.get("confidence") or pick.get("tone_band") or "",
            )
            warn = " ⚠️" if not pick.get("has_narrative", True) else ""

            # First line: number + tier badge + sport + teams
            line1 = (
                f"<b>[{i}]</b> {tier_emoji} {sport_emoji}"
                f" <b>{home} vs {away}</b>{warn}"
            )
            # Second line: kickoff + confidence + EV% (indented)
            detail_parts: list[str] = []
            if kickoff:
                detail_parts.append(kickoff)
            if confidence:
                detail_parts.append(confidence)
            ev_val = float(pick.get("ev") or 0.0)
            if ev_val > 0:
                detail_parts.append(f"<code>+{ev_val:.1f}%</code> EV")
            lines.append(line1)
            if detail_parts:
                lines.append("    " + " · ".join(detail_parts))
            lines.append("")

            # Button (tier emoji or 🔒 for locked picks)
            cb_key = pick.get("cb_key") or pick.get("match_key") or ""
            access = pick.get("access", "full")
            if access in ("full", "partial") and cb_key:
                cb = f"edge:detail:{cb_key}"
                btn_tier = tier_emoji
            elif cb_key:
                cb = f"hot:upgrade:{cb_key}"
                btn_tier = "🔒"
            else:
                cb = "hot:go"
                btn_tier = tier_emoji

            h_abbr = _abbr(home_raw)
            a_abbr = _abbr(away_raw)
            btn_label = f"[{i}] {sport_emoji} {h_abbr} v {a_abbr} {btn_tier}"
            row.append(InlineKeyboardButton(btn_label, callback_data=cb))
            if len(row) == 2:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

        # Optional expandable stats summary blockquote (P3-04)
        if stats_summary:
            lines.append("")
            lines.append(f"<blockquote expandable>{stats_summary}</blockquote>")

        buttons.append([InlineKeyboardButton("⚽ My Matches", callback_data="yg:all:0")])
        buttons.append([InlineKeyboardButton("↩️ Menu", callback_data="nav:main")])

        text = "\n".join(lines)
        if len(text) > _MSG_MAX_CHARS:
            text = text[: _MSG_MAX_CHARS - 3] + "..."

        return text, InlineKeyboardMarkup(buttons)

    @staticmethod
    def _empty_state() -> tuple[str, InlineKeyboardMarkup]:
        text = (
            "🔥 <b>Today's Edge Picks</b>\n\n"
            "No Edges today. Check back closer to kickoff.\n\n"
            "<i>We scan live markets every 15 minutes.</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="hot:go")],
            [InlineKeyboardButton("⚽ My Matches", callback_data="yg:all:0")],
        ])
        return text, markup

    @staticmethod
    def build_photo(
        picks: list[dict],
        *,
        title: str = "Today's Edge Picks",
    ) -> tuple[bytes, str, InlineKeyboardMarkup]:
        """Build image card + caption + keyboard for ``bot.send_photo()``.

        Calls :func:`image_card.generate_digest_card` internally.

        Parameters
        ----------
        picks:
            Same structure as :meth:`build`.  Max 5 shown in image
            (Miller's Law); remaining included in caption "+N more".

        title:
            Caption header title.

        Returns
        -------
        (png_bytes, caption_html, InlineKeyboardMarkup)

        Raises
        ------
        RuntimeError
            If Pillow image generation fails.  Catch and fall back to
            :meth:`build` for text-based digest.

        AC-9 / AC-10 / AC-12
        """
        from image_card import generate_digest_card  # lazy: avoids Pillow import cost

        png_bytes = generate_digest_card(picks)  # raises RuntimeError on failure

        # Short caption (Telegram photo captions: max 1024 chars)
        visible = picks[:DigestMessage.MAX_ITEMS]
        overflow = max(0, len(picks) - DigestMessage.MAX_ITEMS)
        caption_lines = [f"🔥 <b>{h(title)}</b>"]
        if visible:
            caption_lines.append(
                f"<i>{len(visible)} edge{'s' if len(visible) != 1 else ''} active today"
                + (f" · +{overflow} more</i>" if overflow > 0 else "</i>")
            )
        caption = "\n".join(caption_lines)

        # Inline keyboard: tier filter buttons + navigation (AC-10)
        buttons: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton("💎 Diamond", callback_data="digest:filter:diamond"),
                InlineKeyboardButton("🥇 Gold",    callback_data="digest:filter:gold"),
            ],
            [
                InlineKeyboardButton("🥈 Silver",  callback_data="digest:filter:silver"),
                InlineKeyboardButton("🥉 Bronze",  callback_data="digest:filter:bronze"),
            ],
            [InlineKeyboardButton("📊 Stats",  callback_data="digest:stats")],
            [InlineKeyboardButton("↩️ Menu",   callback_data="nav:main")],
        ]
        return png_bytes, caption, InlineKeyboardMarkup(buttons)

    @staticmethod
    def expired_response() -> tuple[str, InlineKeyboardMarkup]:
        """Return text + markup for a tapped button from a stale/expired digest.

        Call this when :func:`is_stale_hash` returns True for a callback key,
        meaning the bot restarted and the hash→match_key mapping was cleared.
        """
        return (
            "⏳ <b>This digest has expired.</b>\n\n"
            "Send /today for fresh picks.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Fresh Picks", callback_data="hot:go")],
            ]),
        )


# ── DetailMessage ────────────────────────────────────────────────────────────

class DetailMessage:
    """Full analysis for a single pick.

    Sections (HTML)::

        🎯 {sport} {Home} vs {Away}
        {tier_emoji} {TIER LABEL}
        🏆 {league}
        📅 {kickoff}
        📺 {broadcast}

        {narrative — pre-rendered HTML with 📋 🎯 ⚠️ 🏆 sections}

        💰 {outcome} @ {odds} ({bookmaker})
           📈 +{ev}% EV

        {injury_flags}

        <blockquote expandable>{deep analysis — all SA bookmaker odds}</blockquote>

    Buttons::

        [↩️ Back to Today's Picks]   ← uses back_cb
        [📲 Bet on {Bookmaker} →]    ← URL button (when bookmaker_url given)
        [📊 Compare Odds]            ← uses compare_odds_cb (when given)

    Expandable blockquote requires Bot API 7.3+ (supported since mid-2024).
    """

    @staticmethod
    def build(
        tip: dict,
        *,
        narrative: str = "",
        back_cb: str = "hot:back:0",
        show_odds: bool = True,
        injury_flags: str = "",
        bookmaker_name: str = "",
        bookmaker_url: str = "",
        compare_odds_cb: str = "",
        confidence_pct: float = 0.0,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Build detail view text + keyboard.

        Parameters
        ----------
        tip:
            Tip dict (same structure as hot tips tips list).  Key fields:

            * ``display_tier`` / ``edge_rating`` — diamond/gold/silver/bronze
            * ``home_team``, ``away_team``
            * ``sport_emoji``
            * ``league``
            * ``_bc_kickoff``, ``_bc_broadcast`` — pre-formatted strings
            * ``outcome``, ``odds``, ``ev``
            * ``bookmaker`` — bookmaker key (fallback if bookmaker_name not given)
            * ``odds_by_bookmaker`` — dict[bk_key, decimal_odds] for blockquote
            * ``edge_v2`` — dict with confirming_signals / total_signals

        narrative:
            Pre-rendered HTML narrative (4 sections: Setup/Edge/Risk/Verdict).
            When empty a minimal fallback is shown.

        back_cb:
            Callback data for the ← Back button.  Default: ``hot:back:0``.

        show_odds:
            Whether to render the odds block and Compare Odds button.

        injury_flags:
            Pre-formatted injury line (e.g. ``"💉 No injuries flagged"``).

        bookmaker_name:
            Display name shown on the CTA button (e.g. ``"Hollywoodbets"``).

        bookmaker_url:
            Affiliate URL for the CTA button.

        compare_odds_cb:
            Callback data for Compare Odds button.  Typically
            ``f"odds:compare:{cb_key}"`` (pre-computed by caller).

        confidence_pct:
            Confidence percentage to display (0–100).  0 means omit the line.

        Returns
        -------
        (text, InlineKeyboardMarkup)
        """
        tier = (tip.get("display_tier") or tip.get("edge_rating") or "bronze").lower()
        tier_emoji = EDGE_EMOJIS.get(tier, "🥉")
        tier_label = EDGE_LABELS.get(tier, "BRONZE EDGE")
        home_raw = tip.get("home_team") or "Home"
        away_raw = tip.get("away_team") or "Away"
        home = h(home_raw)
        away = h(away_raw)
        sport_emoji = tip.get("sport_emoji") or "🏅"
        league = h(tip.get("league") or "")
        kickoff = tip.get("_bc_kickoff") or tip.get("kickoff") or ""
        # FIX-DSTV-CHANNEL-PERM-01: broadcast (channel info) permanently removed
        outcome = h(tip.get("outcome") or "")
        odds_val = float(tip.get("odds") or 0.0)
        ev = float(tip.get("ev") or 0.0)
        bookmaker = h(bookmaker_name or _bk_display(tip.get("bookmaker") or ""))

        lines: list[str] = []

        # Header (🎯 marker used by _inject_narrative_header in bot.py)
        lines.append(f"🎯 {sport_emoji} <b>{home} vs {away}</b>")
        lines.append(f"<b>{tier_emoji} {tier_label}</b>")
        if league:
            lines.append(f"🏆 {league}")
        if kickoff:
            lines.append(f"📅 {kickoff}")
        lines.append("")

        # Narrative in expandable blockquote (P3-04)
        if narrative:
            lines.append(f"<blockquote expandable>{narrative.strip()}</blockquote>")
            lines.append("")
        else:
            lines.append("📋 <b>The Setup</b>")
            lines.append(f"<b>{home}</b> vs <b>{away}</b>")
            lines.append("")

        # Odds block — monospace for all numerical data (P3-04)
        if show_odds and odds_val:
            bk_str = f" ({bookmaker})" if bookmaker else ""
            lines.append(f"💰 <b>{outcome}</b> @ <code>{odds_val:.2f}</code>{bk_str}")
            if confidence_pct > 0:
                lines.append(f"   📊 Confidence: <code>{confidence_pct:.0f}%</code>")
            if ev > 0:
                lines.append(f"   📈 +<code>{ev:.1f}%</code> EV")
            lines.append("")

        # Injury flags
        if injury_flags:
            lines.append(injury_flags)
            lines.append("")

        # Expandable blockquote for deep analysis
        deep = DetailMessage._deep_analysis(tip, show_odds=show_odds)
        if deep:
            lines.append(f"<blockquote expandable>{deep}</blockquote>")
            lines.append("")

        text = "\n".join(lines).rstrip()

        # Keyboard
        buttons: list[list[InlineKeyboardButton]] = []

        buttons.append([
            InlineKeyboardButton("↩️ Back to Edge Picks", callback_data=back_cb)
        ])

        if bookmaker_url:
            bk_label = (
                f"📲 Bet on {bookmaker_name} →" if bookmaker_name else "📲 Bet Now →"
            )
            buttons.append([InlineKeyboardButton(bk_label, url=bookmaker_url)])

        if compare_odds_cb:
            buttons.append([
                InlineKeyboardButton("📊 Compare Odds", callback_data=compare_odds_cb)
            ])

        return text, InlineKeyboardMarkup(buttons)

    @staticmethod
    def build_card_photo(
        card_data: dict,
        *,
        buttons: list[list] | None = None,
        back_cb: str = "hot:back:0",
    ) -> tuple[bytes, str, "InlineKeyboardMarkup"]:
        """Build single-match photo detail from card_pipeline data.

        Parameters
        ----------
        card_data:
            Output of ``card_pipeline.build_card_data()``.
        buttons:
            Pre-built button rows (from ``_build_game_buttons``).
            If None, a minimal Back button is used.
        back_cb:
            Callback data for fallback Back button (only used when
            *buttons* is None).

        Returns
        -------
        (png_bytes, caption_html, InlineKeyboardMarkup)

        Raises
        ------
        RuntimeError
            If image generation or caption rendering fails.
        """
        from image_card import generate_match_card
        from card_pipeline import render_card_html

        img = generate_match_card(card_data)
        caption = render_card_html(card_data)

        if buttons is None:
            buttons = [[InlineKeyboardButton(
                "↩️ Back to Edge Picks", callback_data=back_cb,
            )]]
        return img, caption, InlineKeyboardMarkup(buttons)

    @staticmethod
    def _deep_analysis(tip: dict, *, show_odds: bool = True) -> str:
        """Build the expandable blockquote content."""
        parts: list[str] = []

        # All-bookmaker odds table
        odds_by_bk: dict = tip.get("odds_by_bookmaker") or {}
        if show_odds and odds_by_bk:
            outcome_label = h(tip.get("outcome") or "Pick")
            parts.append(f"📊 <b>SA Bookmaker Odds — {outcome_label}</b>")
            sorted_bk = sorted(odds_by_bk.items(), key=lambda x: x[1], reverse=True)
            best_bk = sorted_bk[0][0] if sorted_bk else ""
            for bk_key, bk_odds in sorted_bk:
                marker = "⭐ " if bk_key == best_bk else "   "
                bk_name = _bk_display(bk_key)
                parts.append(f"{marker}{bk_name}: <b>{float(bk_odds):.2f}</b>")

        # Signal summary
        ev2 = tip.get("edge_v2") or {}
        confirming = int(ev2.get("confirming_signals") or 0)
        total_sigs = int(ev2.get("total_signals") or 0)
        if total_sigs > 0:
            if parts:
                parts.append("")
            parts.append(
                f"📡 <b>Signal coverage:</b> {confirming}/{total_sigs} confirming"
            )

        return "\n".join(parts)


# ── AlertMessage ─────────────────────────────────────────────────────────────

class AlertMessage:
    """Pre-match Gold/Diamond alert for a single pick.

    Sent 2–4 hours before kickoff.  Callers must set
    ``disable_notification=False`` on ``send_message`` to make it audible.

    Format::

        ⚡ Match Alert — {tier_emoji} {TIER LABEL}

        {sport} {Home} vs {Away}
        🏆 {league}
        📅 {kickoff}
        ⏰ Kicking off in Xh Ym

        Pick: {outcome} @ {odds} ({bookmaker})
        Edge: +{ev}% expected value

    Single primary CTA button (bet URL).  Secondary: Full Analysis button
    when ``detail_cb`` is provided.
    """

    @staticmethod
    def build(
        tip: dict,
        *,
        bookmaker_name: str = "",
        bookmaker_url: str = "",
        minutes_to_kickoff: int = 0,
        detail_cb: str = "",
        analysis: str = "",
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Build alert text + keyboard.

        Parameters
        ----------
        tip:
            Tip dict.  Key fields same as DetailMessage.build().

        bookmaker_name:
            SA bookmaker display name for the CTA button.

        bookmaker_url:
            Affiliate URL for the primary CTA button.

        minutes_to_kickoff:
            Minutes until kickoff — used to build time string.  0 means
            the time string is omitted.

        detail_cb:
            Callback data for the "View Details" secondary button.
            Typically ``f"edge:detail:{cb_key}"`` (pre-computed by caller).

        analysis:
            Optional pre-rendered HTML for an expandable analysis blockquote
            (key insight, market context, or brief narrative).

        Returns
        -------
        (text, InlineKeyboardMarkup)
        """
        tier = (tip.get("display_tier") or tip.get("edge_rating") or "gold").lower()
        tier_emoji = EDGE_EMOJIS.get(tier, "🥇")
        tier_label = EDGE_LABELS.get(tier, "GOLDEN EDGE")
        home_raw = tip.get("home_team") or "Home"
        away_raw = tip.get("away_team") or "Away"
        home = h(home_raw)
        away = h(away_raw)
        sport_emoji = tip.get("sport_emoji") or "🏅"
        kickoff = tip.get("_bc_kickoff") or tip.get("kickoff") or ""
        league = h(tip.get("league") or "")
        outcome = h(tip.get("outcome") or "")
        odds_val = float(tip.get("odds") or 0.0)
        ev = float(tip.get("ev") or 0.0)
        bookmaker = h(bookmaker_name or _bk_display(tip.get("bookmaker") or ""))

        # Build time-to-kickoff string
        time_str = ""
        if minutes_to_kickoff > 0:
            hours, mins = divmod(minutes_to_kickoff, 60)
            if hours > 0 and mins > 0:
                time_str = f"Kicking off in {hours}h {mins}m"
            elif hours > 0:
                time_str = f"Kicking off in {hours}h"
            else:
                time_str = f"Kicking off in {mins} min"

        lines: list[str] = [
            f"⚡ <b>Match Alert</b> — {tier_emoji} {tier_label}",
            "",
            f"{sport_emoji} <b>{home} vs {away}</b>",
        ]
        if league:
            lines.append(f"🏆 {league}")
        if kickoff:
            lines.append(f"📅 {kickoff}")
        if time_str:
            lines.append(f"⏰ {h(time_str)}")
        lines.append("")

        if outcome:
            if odds_val and bookmaker:
                lines.append(f"<b>Pick:</b> {outcome} @ <code>{odds_val:.2f}</code> ({bookmaker})")
            elif odds_val:
                lines.append(f"<b>Pick:</b> {outcome} @ <code>{odds_val:.2f}</code>")
            else:
                lines.append(f"<b>Pick:</b> {outcome}")

        if ev > 0:
            lines.append(f"<b>Edge:</b> +<code>{ev:.1f}%</code> expected value")

        # Expandable analysis blockquote — key insight / market context (P3-04)
        if analysis:
            lines.append("")
            lines.append(f"<blockquote expandable>{analysis}</blockquote>")

        text = "\n".join(lines)

        # Buttons: single primary CTA (audible = disable_notification=False, set by caller)
        buttons: list[list[InlineKeyboardButton]] = []
        if bookmaker_url:
            btn_label = (
                f"📲 Bet on {bookmaker_name} →" if bookmaker_name else "📲 Bet Now →"
            )
            buttons.append([InlineKeyboardButton(btn_label, url=bookmaker_url)])

        if detail_cb:
            buttons.append([
                InlineKeyboardButton("🔍 View Details", callback_data=detail_cb)
            ])

        if not buttons:
            buttons.append([
                InlineKeyboardButton("💎 See All Picks", callback_data="hot:go")
            ])

        return text, InlineKeyboardMarkup(buttons)


# ── ResultMessage ────────────────────────────────────────────────────────────

class ResultMessage:
    """Post-match outcome notification.

    Sent silently (callers set ``disable_notification=True``).

    Format::

        ✅ HIT 🥇           (or ❌ MISS 🥈)

        ⚽ {match_display}
        📋 Score: {score}
        🎯 Pick: {outcome} @ {odds}

        Last {period}: {hits}/{total} ({hit_rate}%) · ROI +{roi}%

    No inline keyboard is returned (``None``).  Silent background update.
    """

    @staticmethod
    def build(
        result: dict,
        totals: dict | None = None,
        post_match_analysis: str = "",
    ) -> tuple[str, None]:
        """Build result notification text.

        Parameters
        ----------
        result:
            Dict with keys:

            * ``result`` (str) — ``'hit'`` or ``'miss'``
            * ``match_key`` / ``match_display`` (str) — display name
            * ``outcome`` (str) — predicted outcome label
            * ``odds`` / ``recommended_odds`` (float) — decimal odds
            * ``ev`` / ``predicted_ev`` (float) — predicted EV at recommendation
            * ``match_score`` (str) — final score (e.g. ``"2-1"``)
            * ``edge_tier`` (str) — diamond/gold/silver/bronze

        totals:
            Dict with running stats:

            * ``total`` (int)
            * ``hits`` (int)
            * ``hit_rate`` (float) — 0.0–1.0
            * ``roi_pct`` / ``roi_7d`` (float) — ROI percentage
            * ``period`` (str) — e.g. ``"7 days"``

        post_match_analysis:
            Optional pre-rendered HTML for an expandable post-match analysis
            blockquote (market review, model notes, etc.).

        Returns
        -------
        (text, None)  — no keyboard for silent result messages
        """
        result_str = result.get("result", "")
        is_hit = result_str == "hit"
        r_emoji = "✅" if is_hit else "❌"
        result_word = "HIT" if is_hit else "MISS"

        tier = (result.get("edge_tier") or "bronze").lower()
        tier_emoji = EDGE_EMOJIS.get(tier, "🥉")

        match_display = h(
            result.get("match_display") or result.get("match_key") or ""
        )
        outcome = h(result.get("outcome") or "")
        odds_val = float(
            result.get("odds") or result.get("recommended_odds") or 0.0
        )
        score = h(result.get("match_score") or "")
        pl_rands = float(result.get("pl_rands") or 0.0)

        lines: list[str] = [
            f"{r_emoji} <b>{result_word}</b> {tier_emoji}",
            "",
        ]

        if match_display:
            lines.append(f"⚽ {match_display}")
        if score:
            lines.append(f"📋 Score: {score}")
        if outcome and odds_val:
            lines.append(f"🎯 Pick: {outcome} @ <code>{odds_val:.2f}</code>")
        elif outcome:
            lines.append(f"🎯 Pick: {outcome}")

        # P/L in Rands (P3-04)
        if pl_rands != 0.0:
            pl_sign = "+" if pl_rands >= 0 else "-"
            lines.append(f"💵 P/L: <code>{pl_sign}R{abs(pl_rands):.0f}</code>")

        # Running totals — monospace for all numbers (P3-04)
        if totals and int(totals.get("total") or 0) > 0:
            lines.append("")
            total = int(totals["total"])
            hits = int(totals.get("hits") or 0)
            hr = float(totals.get("hit_rate") or 0.0)
            roi = float(totals.get("roi_pct") or totals.get("roi_7d") or 0.0)
            period = totals.get("period") or "7 days"
            # hit_rate may be 0.65 or 65.0 — normalise to percentage
            hr_pct = hr * 100.0 if hr <= 1.0 else hr
            roi_sign = "+" if roi >= 0 else ""
            lines.append(
                f"<b>Last {h(period)}:</b>"
                f"  <code>{hits}/{total}</code> (<code>{hr_pct:.0f}%</code>)"
                f" · ROI <code>{roi_sign}{roi:.1f}%</code>"
            )

        # Expandable post-match analysis blockquote (P3-04)
        if post_match_analysis:
            lines.append("")
            lines.append(f"<blockquote expandable>{post_match_analysis}</blockquote>")

        return "\n".join(lines), None
