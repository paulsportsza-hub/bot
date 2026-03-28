"""Single-renderer for edge:detail — eliminates 3 overlapping paths.

CLEAN-RENDER-v2: One public function, one data path, one tier computation.
No caches, no branching, no reconciliation. Six recurring bugs become
structurally impossible.

Usage (from async handler):
    html = await asyncio.to_thread(render_edge_detail, match_key, user_tier, sport)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from html import escape as h

log = logging.getLogger(__name__)

# ── Imports from existing modules ────────────────────────────
# DB access (LOCKED rule: never bare sqlite3.connect)
from fetchers.base_fetcher import get_cached_context
from tier_gate import get_edge_access_level, get_upgrade_message
from renderers.edge_renderer import render_edge_badge, EDGE_LABELS
from config import get_country_flag


# ── Constants ────────────────────────────────────────────────

_DB_LEAGUE_SPORT: dict[str, str] = {
    "psl": "soccer", "epl": "soccer", "champions_league": "soccer",
    "la_liga": "soccer", "bundesliga": "soccer", "serie_a": "soccer",
    "ligue_1": "soccer",
    "urc": "rugby", "six_nations": "rugby", "super_rugby": "rugby",
    "sa20": "cricket", "ipl": "cricket", "t20_world_cup": "cricket",
    "test_cricket": "cricket",
    "ufc": "mma", "boxing": "boxing", "boxing_major": "boxing",
}

_LEAGUE_DISPLAY: dict[str, str] = {
    "psl": "PSL", "epl": "Premier League",
    "champions_league": "Champions League",
    "la_liga": "La Liga", "bundesliga": "Bundesliga",
    "serie_a": "Serie A", "ligue_1": "Ligue 1",
    "urc": "URC", "six_nations": "Six Nations",
    "super_rugby": "Super Rugby",
    "sa20": "SA20", "ipl": "IPL",
    "t20_world_cup": "T20 World Cup",
    "test_cricket": "Test Cricket",
    "ufc": "UFC", "boxing": "Boxing",
}

_BK_DISPLAY: dict[str, str] = {
    "hollywoodbets": "Hollywoodbets",
    "betway": "Betway",
    "supabets": "SupaBets",
    "sportingbet": "Sportingbet",
    "gbets": "GBets",
    "wsb": "World Sports Betting",
    "playabets": "PlayaBets",
    "supersportbet": "SuperSportBet",
}


# ── EdgeDetailData ───────────────────────────────────────────

@dataclass(frozen=True)
class EdgeDetailData:
    """Immutable intermediate struct — all fields set once during build."""

    match_key: str
    home: str
    away: str
    sport: str
    league: str
    league_display: str

    # Edge metrics — ONE source each
    edge_tier: str           # from edge_results.edge_tier (ONE computation)
    composite_score: float   # from edge_results.composite_score
    outcome: str             # normalised: "home" / "away" / "draw"
    outcome_display: str     # team display name or "Draw"
    recommended_odds: float  # from edge_results.recommended_odds
    bookmaker: str           # display name
    bookmaker_key: str       # raw key
    predicted_ev: float      # from edge_results.predicted_ev (ONE source)
    confirming_signals: int  # from edge_results.confirming_signals (ONE read)
    fair_prob_pct: float     # derived: (1 + ev/100) / odds * 100
    model_only: bool         # confirming_signals == 0 (same variable)

    # Context
    context: dict | None     # from match_context
    mep_met: bool            # minimum enrichment present

    # Metadata
    match_date: str
    user_tier: str
    access_level: str        # from get_edge_access_level (ONE gating pass)


# ── Data Loading ─────────────────────────────────────────────

def _load_edge_result(match_key: str) -> dict | None:
    """Read latest unsettled edge_results row for match_key.

    Uses the scraper connection factory per W81-DBLOCK locked rule.
    """
    try:
        from scrapers.db_connect import connect_odds_db
        from scrapers.edge.edge_config import DB_PATH
    except ImportError:
        log.warning("edge_detail_renderer: scraper imports unavailable")
        return None

    conn = connect_odds_db(DB_PATH)
    conn.row_factory = lambda cursor, row: dict(
        zip([col[0] for col in cursor.description], row)
    )
    try:
        row = conn.execute(
            """
            SELECT match_key, edge_tier, composite_score, bet_type,
                   recommended_odds, bookmaker, predicted_ev, league,
                   match_date, confirming_signals, sport
            FROM edge_results
            WHERE match_key = ? AND result IS NULL
            ORDER BY recommended_at DESC, id DESC
            LIMIT 1
            """,
            (match_key,),
        ).fetchone()
        return row
    except Exception as exc:
        log.warning("_load_edge_result failed for %s: %s", match_key, exc)
        return None
    finally:
        conn.close()


def _load_match_context(match_key: str) -> dict | None:
    """Read match_context via approved cache factory."""
    try:
        return get_cached_context(match_key)
    except Exception:
        return None


# ── Helpers ──────────────────────────────────────────────────

def _display_team_name(raw_key: str) -> str:
    """Convert normalised key to display name via odds_normaliser."""
    try:
        from scrapers.odds_normaliser import display_name as _odds_display_name
        return _odds_display_name(raw_key)
    except Exception:
        return raw_key.replace("_", " ").title()


def _display_bookmaker(raw_key: str) -> str:
    """Convert bookmaker key to display name."""
    return _BK_DISPLAY.get(raw_key, raw_key.title())


def _parse_teams(match_key: str) -> tuple[str, str]:
    """Extract display names from match_key 'home_vs_away_YYYY-MM-DD'."""
    mk_no_date = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_key)
    if "_vs_" in mk_no_date:
        home_raw, away_raw = mk_no_date.split("_vs_", 1)
    else:
        home_raw = away_raw = mk_no_date
    return _display_team_name(home_raw), _display_team_name(away_raw)


def _resolve_outcome(
    bet_type: str, home: str, away: str,
) -> tuple[str, str]:
    """Map DB bet_type to (raw_outcome, display_outcome).

    Returns:
        ("home"/"away"/"draw", team_display_name_or_Draw)
    """
    bt = (bet_type or "home").strip()
    if bt in ("Home Win", "home"):
        raw = "home"
    elif bt in ("Away Win", "away"):
        raw = "away"
    else:
        raw = "draw"
    labels = {"home": home, "away": away, "draw": "Draw"}
    return raw, labels.get(raw, bt)


def _detect_sport(league: str, sport_col: str | None = None) -> str:
    """Determine sport from DB column or league key."""
    if sport_col:
        return sport_col.lower()
    lk = (league or "").lower()
    try:
        from scrapers.edge.edge_config import LEAGUE_TO_SPORT
    except ImportError:
        LEAGUE_TO_SPORT = {}
    return LEAGUE_TO_SPORT.get(lk) or _DB_LEAGUE_SPORT.get(lk, "soccer")


def _format_date(date_str: str) -> str:
    """Format date for display: 'Today', 'Tomorrow', or 'Wed 26 Mar'."""
    try:
        d = date.fromisoformat(date_str[:10])
        today = date.today()
        delta = (d - today).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Tomorrow"
        return d.strftime("%a %d %b")
    except (ValueError, TypeError):
        return date_str or ""


def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 11 → '11th', etc."""
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ── Build Detail Data ────────────────────────────────────────

def _build_detail_data(
    edge_row: dict,
    ctx: dict | None,
    user_tier: str,
    sport_override: str | None = None,
) -> EdgeDetailData:
    """Merge edge_result + context into frozen data struct.

    Every field is set exactly ONCE from exactly ONE source.
    """
    from scrapers.edge.tier_engine import assign_tier

    mk = edge_row["match_key"]
    home, away = _parse_teams(mk)

    league_key = (edge_row.get("league") or "").lower()
    sport = sport_override or _detect_sport(league_key, edge_row.get("sport"))

    composite = float(edge_row.get("composite_score") or 0)
    ev = round(float(edge_row.get("predicted_ev") or 0), 1)
    odds = float(edge_row.get("recommended_odds") or 0)

    # Confirming signals: DB column first, estimate fallback for legacy rows
    cs_raw = edge_row.get("confirming_signals")
    if cs_raw is not None:
        confirming = int(cs_raw)
    else:
        confirming = (
            3 if composite >= 70
            else 2 if composite >= 55
            else 1 if composite >= 35
            else 0
        )

    # Tier: DB value is authoritative — ONE computation
    db_tier = (edge_row.get("edge_tier") or "").strip().lower()
    if db_tier in ("diamond", "gold", "silver", "bronze"):
        tier = db_tier
    else:
        tier = assign_tier(composite, ev, confirming, red_flags=[]) or "bronze"

    # Fair probability: (1 + EV/100) / odds × 100
    if ev > 0 and odds > 1.0:
        fair_prob = round(((1 + ev / 100.0) / odds) * 100)
    else:
        fair_prob = 0

    # Outcome
    outcome_raw, outcome_display = _resolve_outcome(
        edge_row.get("bet_type", "home"), home, away,
    )

    # Bookmaker
    bk_key = (edge_row.get("bookmaker") or "").strip().lower()

    # Match context
    mep_met = bool(ctx and isinstance(ctx, dict) and ctx.get("data_available"))

    # Access level — ONE gating pass
    access = get_edge_access_level(user_tier, tier)

    return EdgeDetailData(
        match_key=mk,
        home=home,
        away=away,
        sport=sport,
        league=league_key,
        league_display=_LEAGUE_DISPLAY.get(league_key, league_key.upper() if league_key else ""),
        edge_tier=tier,
        composite_score=composite,
        outcome=outcome_raw,
        outcome_display=outcome_display,
        recommended_odds=odds,
        bookmaker=_display_bookmaker(bk_key),
        bookmaker_key=bk_key,
        predicted_ev=ev,
        confirming_signals=confirming,
        fair_prob_pct=fair_prob,
        model_only=(confirming == 0),
        context=ctx,
        mep_met=mep_met,
        match_date=edge_row.get("match_date", ""),
        user_tier=user_tier,
        access_level=access,
    )


def _build_detail_data_from_tip(
    tip_data: dict,
    ctx: dict | None,
    user_tier: str,
) -> EdgeDetailData:
    """Build detail data from V1 tip dict when V2 edge_results unavailable.

    CLEAN-RUGBY: Produces a minimum viable card with real match info.
    Sets ``model_only=True`` and ``confirming_signals=0`` because V1
    does not track individual signal confirmations.
    """
    from scrapers.edge.tier_engine import assign_tier

    mk = tip_data.get("match_key") or tip_data.get("match_id", "")
    home, away = _parse_teams(mk)

    league_key = (
        tip_data.get("league") or tip_data.get("league_key") or ""
    ).lower()
    sport = (
        tip_data.get("sport") or _detect_sport(league_key)
    ).lower()

    composite = float(
        tip_data.get("composite_score")
        or tip_data.get("edge_score")
        or 0,
    )
    ev = round(
        float(tip_data.get("ev") or tip_data.get("predicted_ev") or 0), 1,
    )
    odds = float(
        tip_data.get("recommended_odds") or tip_data.get("odds") or 0,
    )

    # V1 doesn't track confirming signals
    confirming = 0

    # Tier from display_tier or edge_rating
    tier_raw = (
        tip_data.get("display_tier")
        or tip_data.get("edge_rating")
        or ""
    ).strip().lower()
    if tier_raw in ("diamond", "gold", "silver", "bronze"):
        tier = tier_raw
    else:
        tier = assign_tier(composite, ev, confirming, red_flags=[]) or "bronze"

    # Fair probability
    if ev > 0 and odds > 1.0:
        fair_prob = round(((1 + ev / 100.0) / odds) * 100)
    else:
        fair_prob = 0

    # Outcome — SERVE-PATH-FIX Fix 2: check edge_v2.outcome before defaulting
    bet_type = (
        tip_data.get("recommended_outcome")
        or tip_data.get("bet_type")
        or (tip_data.get("edge_v2") or {}).get("outcome")
        or "home"
    )
    outcome_raw, outcome_display = _resolve_outcome(bet_type, home, away)

    # Bookmaker
    bk_key = (tip_data.get("bookmaker") or "").strip().lower()

    # Context
    mep_met = bool(ctx and isinstance(ctx, dict) and ctx.get("data_available"))

    # Access level
    access = get_edge_access_level(user_tier, tier)

    # Match date from match_key suffix
    match_date = ""
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})$", mk)
    if date_match:
        match_date = date_match.group(1)

    return EdgeDetailData(
        match_key=mk,
        home=home,
        away=away,
        sport=sport,
        league=league_key,
        league_display=_LEAGUE_DISPLAY.get(
            league_key, league_key.upper() if league_key else "",
        ),
        edge_tier=tier,
        composite_score=composite,
        outcome=outcome_raw,
        outcome_display=outcome_display,
        recommended_odds=odds,
        bookmaker=_display_bookmaker(bk_key),
        bookmaker_key=bk_key,
        predicted_ev=ev,
        confirming_signals=confirming,
        fair_prob_pct=fair_prob,
        model_only=True,
        context=ctx,
        mep_met=mep_met,
        match_date=match_date,
        user_tier=user_tier,
        access_level=access,
    )


# ── Section Builders ─────────────────────────────────────────
# All builders: (EdgeDetailData) → str. Empty string if no data.

def _section_header(data: EdgeDetailData) -> str:
    """Fixture identity: badge, teams with flags, league, date."""
    # Flags: both-or-nothing rule
    hf = get_country_flag(data.home)
    af = get_country_flag(data.away)
    if hf and af:
        home_str = f"{hf} {h(data.home)}"
        away_str = f"{af} {h(data.away)}"
    else:
        home_str = h(data.home)
        away_str = h(data.away)

    lines = [f"🎯 <b>{home_str} vs {away_str}</b>"]
    if data.match_date:
        lines.append(f"📅 {_format_date(data.match_date)}")
    if data.league_display:
        lines.append(f"🏆 {h(data.league_display)}")
    lines.append(render_edge_badge(data.edge_tier))
    lines.append("")
    return "\n".join(lines)


def _section_team_context(data: EdgeDetailData) -> str:
    """Sport-dispatched team context from match_context."""
    if not data.context or not data.mep_met:
        return ""

    ctx = data.context
    lines = ["📋 <b>The Setup</b>"]

    home_para = _team_paragraph(ctx, "home", data.home, data.sport)
    if home_para:
        lines.append(home_para)

    away_para = _team_paragraph(ctx, "away", data.away, data.sport)
    if away_para:
        lines.append(away_para)

    if len(lines) <= 1:
        return ""
    lines.append("")
    return "\n".join(lines)


def _team_paragraph(ctx: dict, side: str, name: str, sport: str) -> str:
    """Build one team's context paragraph. Sport-aware."""
    parts: list[str] = []
    pos = ctx.get(f"{side}_position")
    pts = ctx.get(f"{side}_points")
    form = ctx.get(f"{side}_form", "")
    coach = ctx.get(f"{side}_coach", "")

    if pos and pts is not None:
        pos_str = _ordinal(int(pos))
        if sport == "cricket":
            w = ctx.get(f"{side}_wins", 0)
            lo = ctx.get(f"{side}_losses", 0)
            nrr = ctx.get(f"{side}_nrr", "")
            stat = f"{w}W-{lo}L"
            if nrr:
                stat += f", NRR {nrr}"
            parts.append(f"{h(name)} sit {pos_str} ({stat})")
        else:
            parts.append(f"{h(name)} sit {pos_str} on {pts} points")

    if form:
        parts.append(f"Form: {h(str(form))}")

    if coach:
        last = coach.split()[-1] if coach else ""
        if last:
            parts.append(f"under {h(last)}")

    # Sport-specific stats
    if sport == "soccer":
        gpg = ctx.get(f"{side}_goals_per_game")
        if gpg:
            parts.append(f"{gpg} goals/game")
    elif sport == "rugby":
        tf = ctx.get(f"{side}_tries_for")
        ta = ctx.get(f"{side}_tries_against")
        if tf is not None and ta is not None:
            parts.append(f"{tf} tries for, {ta} against")
    elif sport in ("mma", "boxing"):
        record = ctx.get(f"{side}_record", "")
        if record:
            parts.append(h(str(record)))

    return " · ".join(parts)


def _section_h2h(data: EdgeDetailData) -> str:
    """Head-to-head from context_json — ONE builder, no duplication possible."""
    if not data.context:
        return ""

    h2h = data.context.get("h2h") or data.context.get("head_to_head") or []
    if not h2h:
        return ""

    lines = ["⚔️ <b>Head to Head</b>"]
    for match in h2h[:5]:
        if isinstance(match, dict):
            result = match.get("result", "")
            comp = match.get("competition", "")
            line = h(str(result))
            if comp:
                line += f" <i>({h(str(comp))})</i>"
            lines.append(f"• {line}")
        elif isinstance(match, str):
            lines.append(f"• {h(match)}")

    lines.append("")
    return "\n".join(lines)


def _section_injuries(data: EdgeDetailData) -> str:
    """Soccer/rugby only, from context when available."""
    if data.sport not in ("soccer", "rugby"):
        return ""
    if not data.context:
        return ""

    injuries = data.context.get("injuries") or []
    if not injuries:
        return ""

    lines = ["🏥 <b>Key Absences</b>"]
    for inj in injuries[:6]:
        if isinstance(inj, dict):
            player = inj.get("player", "")
            reason = inj.get("reason", "")
            team = inj.get("team", "")
            line = h(str(player))
            if team:
                line += f" ({h(str(team))})"
            if reason:
                line += f" — {h(str(reason))}"
            lines.append(f"• {line}")
        elif isinstance(inj, str):
            lines.append(f"• {h(inj)}")

    lines.append("")
    return "\n".join(lines)


def _section_weather(data: EdgeDetailData) -> str:
    """Cricket only, from context weather_forecast."""
    if data.sport != "cricket":
        return ""
    if not data.context:
        return ""

    weather = data.context.get("weather_forecast", "")
    if not weather:
        return ""

    return f"🌤️ <b>Conditions</b>\n{h(str(weather))}\n"


def _section_edge(data: EdgeDetailData) -> str:
    """Bookmaker, odds, fair prob, EV gap explanation."""
    lines = ["🎯 <b>The Edge</b>"]

    ev_str = f"+{data.predicted_ev:.1f}%" if data.predicted_ev > 0 else f"{data.predicted_ev:.1f}%"
    value_flag = " 💰" if data.predicted_ev > 2 else ""

    lines.append(
        f"<b>{h(data.outcome_display)}</b> @ <b>{data.recommended_odds:.2f}</b> "
        f"on {h(data.bookmaker)}"
    )
    lines.append(
        f"Fair probability: {data.fair_prob_pct}% · EV: {ev_str}{value_flag}"
    )

    # Explain the gap when meaningful data exists
    if data.fair_prob_pct > 0 and data.recommended_odds > 1.0:
        market_implied = round(100 / data.recommended_odds)
        gap = data.fair_prob_pct - market_implied
        if gap > 0:
            lines.append(
                f"Our model sees {data.fair_prob_pct}% vs "
                f"{h(data.bookmaker)}'s implied {market_implied}% — "
                f"a {gap:.0f}pp gap."
            )

    lines.append("")
    return "\n".join(lines)


def _section_signals(data: EdgeDetailData) -> str:
    """Confirming count, model-only badge, signal summary.

    Uses data.confirming_signals (ONE read from DB) — no divergence possible.
    """
    lines = ["📡 <b>Signal Check</b>"]

    if data.model_only:
        lines.append(
            "No confirming indicators behind this price — "
            "the edge is carried by the pricing gap alone."
        )
    elif data.confirming_signals == 1:
        lines.append("1 signal aligned with this edge.")
    else:
        lines.append(f"{data.confirming_signals} signals aligned with this edge.")

    if data.composite_score > 0:
        lines.append(f"Composite score: {data.composite_score:.0f}/100")

    lines.append("")
    return "\n".join(lines)


def _section_risk(data: EdgeDetailData) -> str:
    """Risk factors from signals + context."""
    lines = ["⚠️ <b>The Risk</b>"]
    factors: list[str] = []

    if data.model_only:
        factors.append(
            "No supporting signals — size conservatively."
        )

    if data.outcome == "away" and data.confirming_signals < 3:
        factors.append(
            "Away side faces home crowd disadvantage — factor that in."
        )

    if data.context:
        injuries = data.context.get("injuries") or []
        if injuries:
            count = len(injuries)
            factors.append(
                f"{count} player absence{'s' if count != 1 else ''} "
                f"could shift the picture."
            )

    if not factors:
        factors.append(
            "No specific flags on this one — standard match-day variables apply."
        )

    for f in factors:
        lines.append(f"• {f}")

    lines.append("")
    return "\n".join(lines)


def _vpick(seed: str, n: int) -> int:
    """MD5-deterministic variant index — same seed always picks same variant."""
    return int(hashlib.md5(seed.encode()).hexdigest(), 16) % n


def _section_verdict(data: EdgeDetailData) -> str:
    """Tier-driven verdict — conviction mapped to signal count.

    SERVE-PATH-FIX Fix 3: MD5-deterministic variant selection per match_key
    so different cards show different verdict text.
    """
    lines = ["🏆 <b>Verdict</b>"]
    badge = render_edge_badge(data.edge_tier)
    seed = data.match_key

    if data.confirming_signals == 0:
        variants = [
            f"{badge} — Monitor the line. Small speculative exposure at best.",
            f"{badge} — Price-only edge with no confirming signals. Watch, don't chase.",
            f"{badge} — Speculative angle — if you take it, keep sizing minimal.",
        ]
        lines.append(variants[_vpick(seed, len(variants))])
    elif data.confirming_signals == 1:
        variants = [
            f"{badge} — A lean, not a conviction play. Size carefully.",
            f"{badge} — One signal confirms the price. Moderate exposure warranted.",
            f"{badge} — Early confirmation but not yet a full picture. Stay measured.",
        ]
        lines.append(variants[_vpick(seed, len(variants))])
    elif data.confirming_signals >= 3 and data.predicted_ev >= 8:
        variants = [
            f"{badge} — Strong support across indicators. Back with confidence.",
            f"{badge} — Multiple signals align with the price. This is a conviction play.",
            f"{badge} — The depth of support here is rare. Execute with full sizing.",
        ]
        lines.append(variants[_vpick(seed, len(variants))])
    else:
        variants = [
            f"{badge} — Enough signal to warrant a standard stake.",
            f"{badge} — Solid supporting evidence. Normal sizing applies.",
            f"{badge} — The numbers and signals agree. Back it at standard exposure.",
        ]
        lines.append(variants[_vpick(seed, len(variants))])

    return "\n".join(lines)


# ── Sport Section Dispatch ───────────────────────────────────

_SPORT_SECTIONS: dict[str, list] = {
    "soccer": [
        _section_header, _section_team_context, _section_h2h,
        _section_injuries, _section_edge, _section_signals,
        _section_risk, _section_verdict,
    ],
    "rugby": [
        _section_header, _section_team_context, _section_h2h,
        _section_edge, _section_signals, _section_risk, _section_verdict,
    ],
    "cricket": [
        _section_header, _section_team_context, _section_weather,
        _section_h2h, _section_edge, _section_signals,
        _section_risk, _section_verdict,
    ],
    "mma": [
        _section_header, _section_team_context, _section_edge,
        _section_signals, _section_risk, _section_verdict,
    ],
    "boxing": [
        _section_header, _section_team_context, _section_edge,
        _section_signals, _section_risk, _section_verdict,
    ],
}

_DEFAULT_SECTIONS = [
    _section_header, _section_team_context, _section_h2h,
    _section_edge, _section_signals, _section_risk, _section_verdict,
]


# ── Gating Renderers ─────────────────────────────────────────

def _render_full(data: EdgeDetailData) -> str:
    """Full access — all sections populated."""
    sections = _SPORT_SECTIONS.get(data.sport, _DEFAULT_SECTIONS)
    parts = [fn(data) for fn in sections]
    return "\n".join(p for p in parts if p)


def _render_partial(data: EdgeDetailData) -> str:
    """Partial access — odds visible, breakdown shorter."""
    parts = [_section_header(data), _section_edge(data)]

    # Truncated signal summary
    if data.confirming_signals > 0:
        s = "s" if data.confirming_signals != 1 else ""
        parts.append(
            f"📡 {data.confirming_signals} signal{s} aligned · "
            f"Composite {data.composite_score:.0f}/100"
        )
    parts.append("")
    parts.append(_section_verdict(data))
    parts.append("")
    parts.append("🔑 Unlock full analysis → /subscribe")
    return "\n".join(p for p in parts if p)


def _render_blurred(data: EdgeDetailData) -> str:
    """Blurred — header visible, odds masked, upgrade CTA."""
    lines = [_section_header(data)]
    lines.append("🎯 <b>The Edge</b>")
    lines.append(
        f"<b>{h(data.outcome_display)}</b> — "
        f"odds and breakdown available on upgrade."
    )
    lines.append("")

    tier_needed = "Diamond" if data.edge_tier == "diamond" else "Gold"
    label = EDGE_LABELS.get(data.edge_tier, "EDGE")
    lines.append(f"🔒 This {label} requires {tier_needed} access.")
    lines.append("🔑 Unlock → /subscribe")
    return "\n".join(lines)


def _render_locked(data: EdgeDetailData) -> str:
    """Locked — teaser only, upgrade CTA."""
    lines = [_section_header(data)]
    badge = render_edge_badge(data.edge_tier)
    lines.append(f"🔒 {badge}")
    lines.append("")
    lines.append(
        "This premium edge includes deeper signal context, "
        "odds analysis, and a full verdict."
    )
    lines.append("")
    lines.append(
        get_upgrade_message(data.user_tier, context="diamond_edge")
    )
    return "\n".join(lines)


# ── Public API ───────────────────────────────────────────────

def get_edge_tier_from_db(match_key: str) -> str:
    """Return authoritative edge_tier from edge_results DB (no gating, no render).

    Used by bot.py CLEAN-RENDER path so button tier always matches render tier.
    Returns 'bronze' when no row exists or tier is unrecognised.
    """
    row = _load_edge_result(match_key)
    if not row:
        return "bronze"
    tier = (row.get("edge_tier") or "bronze").strip().lower()
    return tier if tier in ("diamond", "gold", "silver", "bronze") else "bronze"


def render_edge_detail(
    match_key: str,
    user_tier: str,
    sport: str | None = None,
    tip_data: dict | None = None,
    include_tier: bool = False,
) -> "str | tuple[str, str]":
    """Render edge detail HTML — ONE function, ONE path, no branching caches.

    Synchronous. Call from ``asyncio.to_thread()``.

    Args:
        match_key: Edge results match key (e.g. ``arsenal_vs_tottenham_2026-03-26``).
        user_tier: Caller's effective tier (``bronze``/``gold``/``diamond``).
        sport: Optional sport override. Auto-detected from league if omitted.
        tip_data: V1 tip dict fallback when edge_results has no V2 row
            (CLEAN-RUGBY). Used to render a minimum viable card instead of
            the "No current edge data" error.
        include_tier: When True, return ``(html, edge_tier)`` tuple so the
            caller (bot.py CLEAN-RENDER) can use the authoritative tier for
            button building without a second DB query. Default False preserves
            the original string-return API so existing callers and tests are
            unaffected.

    Returns:
        HTML string when ``include_tier=False`` (default).
        ``(html, edge_tier)`` tuple when ``include_tier=True``.
    """
    edge_row = _load_edge_result(match_key)
    if not edge_row:
        if tip_data:
            ctx = _load_match_context(match_key)
            data = _build_detail_data_from_tip(tip_data, ctx, user_tier)
        else:
            mk_display = match_key.replace("_vs_", " vs ").replace("_", " ").title()
            error_html = (
                f"🎯 <b>{h(mk_display)}</b>\n\n"
                "No current edge data for this match."
            )
            if include_tier:
                return error_html, "bronze"
            return error_html
    else:
        ctx = _load_match_context(match_key)
        data = _build_detail_data(edge_row, ctx, user_tier, sport)

    if data.access_level == "locked":
        html = _render_locked(data)
    elif data.access_level == "blurred":
        html = _render_blurred(data)
    elif data.access_level == "partial":
        html = _render_partial(data)
    else:
        html = _render_full(data)

    # Clean up excessive whitespace
    html = re.sub(r"\n{3,}", "\n\n", html)

    if include_tier:
        return html, data.edge_tier
    return html
