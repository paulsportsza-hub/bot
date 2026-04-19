"""IMG-PW1: Data adapter — build edge_summary template data from pipeline tips.

Public API:
    build_edge_summary_data(tips: list[dict]) -> dict
"""
from __future__ import annotations
import base64
import io
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# ── Logo helpers ───────────────────────────────────────────────────────────────
_BOT_DIR = Path(__file__).parent
_ASSETS_DIR = _BOT_DIR.parent / "assets"

_HEADER_LOGO = _BOT_DIR / "assets" / "LOGO" / "mzansiedge-wordmark-dark-transparent.png"
_FOOTER_LOGO = _ASSETS_DIR / "LOGO" / "mzansiedge-micro-mark-e-transparent.png"
_SS_LOGO = _BOT_DIR.parent / "assets" / "icons" / "ss.png"


def _parse_channel(raw: str) -> tuple[str, bool]:
    """Parse DStv channel number and SS flag from a broadcast/channel string.

    Returns (channel_number, is_ss).
    Examples:
      "📺 SS EPL (DStv 203)"  → ("203", True)
      "SS Rugby (DStv 211)"   → ("211", True)
      "DStv 203"              → ("203", True)   ← SS range 199-216
      "SABC 1 (FTA)"          → ("", False)
    """
    import re as _re_ch
    is_ss = bool(_re_ch.search(r'\bSS\b', raw))
    m = _re_ch.search(r'DStv\s*(\d+)', raw, _re_ch.IGNORECASE)
    if m:
        num = m.group(1)
        # DStv channels 199-216 are all SuperSport channels
        if not is_ss and 199 <= int(num) <= 216:
            is_ss = True
        return num, is_ss
    m2 = _re_ch.search(r'\b(\d{3})\b', raw)
    if m2:
        num = m2.group(1)
        if not is_ss and 199 <= int(num) <= 216:
            is_ss = True
        return num, is_ss
    return "", is_ss


def logo_b64(path: Path, max_height: int = 64) -> str:
    """Resize a logo PNG and return as base64 data URI."""
    try:
        from PIL import Image  # type: ignore[import-untyped]
        img = Image.open(path)
        ratio = max_height / img.height
        new_size = (max(1, int(img.width * ratio)), max_height)
        img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception as exc:
        log.warning("logo_b64: failed to load %s: %s", path, exc)
        return ""


# ── Tier metadata
# bg_alpha / border_alpha are 2-char hex suffixes appended to the color hex.
# Values chosen to be visible against #0A0A0A card background.
_TIER_META = {
    "diamond": {"emoji": "💎", "label": "DIAMOND", "color": "#B9F2FF", "rank": 0, "bg_alpha": "15", "border_alpha": "30"},
    "gold":    {"emoji": "🥇", "label": "GOLD",    "color": "#FFD700", "rank": 1, "bg_alpha": "15", "border_alpha": "30"},
    "silver":  {"emoji": "🥈", "label": "SILVER",  "color": "#A0AEC0", "rank": 2, "bg_alpha": "12", "border_alpha": "25"},
    "bronze":  {"emoji": "🥉", "label": "BRONZE",  "color": "#CD7F32", "rank": 3, "bg_alpha": "15", "border_alpha": "30"},
}

_TIER_ORDER = ["diamond", "gold", "silver", "bronze"]

# ── Sport icon helpers ──────────────────────────────────────────────────────────
LEAGUE_SPORT_MAP: dict[str, str] = {
    # Soccer
    "EPL": "soccer", "UCL": "soccer", "PSL": "soccer",
    "La Liga": "soccer", "Serie A": "soccer", "Bundesliga": "soccer",
    "Ligue 1": "soccer", "MLS": "soccer", "EFL": "soccer",
    "Europa": "soccer", "AFCON": "soccer",
    # Cricket
    "IPL": "cricket", "SA20": "cricket", "ODI": "cricket",
    "T20": "cricket", "Test": "cricket", "BBL": "cricket",
    "CPL": "cricket", "PSL-C": "cricket",
    "Test Series": "cricket", "T20 World Cup": "cricket",
    "ICC U19 World Cup": "cricket",
    # Rugby
    "Super Rugby": "rugby", "Super Rugby Pacific": "rugby",
    "URC": "rugby",
    "Rugby Championship": "rugby", "Six Nations": "rugby",
    "Currie Cup": "rugby",
    # Combat
    "UFC": "mma", "MMA": "mma",
    "Boxing": "boxing",
}

_SPORT_EMOJI_MAP: dict[str, str] = {
    "soccer": "⚽",
    "cricket": "🏏",
    "rugby": "🏉",
    "boxing": "🥊",
    "mma": "🤼",
}


def detect_sport(league: str, sport_key: str | None = None) -> str:
    """Detect sport from league string with fuzzy fallback chain.

    1. Exact match in LEAGUE_SPORT_MAP
    2. Case-insensitive substring match
    3. sport_key hint from caller
    4. Default to 'soccer'
    """
    if league in LEAGUE_SPORT_MAP:
        return LEAGUE_SPORT_MAP[league]
    league_lower = league.lower()
    for key, sport in LEAGUE_SPORT_MAP.items():
        if key.lower() in league_lower or league_lower in key.lower():
            return sport
    if sport_key:
        return sport_key
    return "soccer"


def sport_emoji(league: str, sport_key: str | None = None) -> str:
    """Return the sport emoji for the given league string."""
    sport = detect_sport(league, sport_key)
    return _SPORT_EMOJI_MAP.get(sport, "⚽")


def build_edge_summary_data(tips: list[dict]) -> dict:
    """Transform card_pipeline / Hot Tips tip dicts into edge_summary template data.

    Parameters
    ----------
    tips:
        List of tip dicts from bot._hot_tips_cache or card_pipeline.build_card_data().
        Expected fields (all optional with graceful fallbacks):
            tier / display_tier / edge_rating  -> tier key (lowercase)
            ev                                 -> EV percentage (float)
            odds                               -> decimal odds (float)
            home_team / home                   -> home team display name
            away_team / away                   -> away team display name
            league / league_display            -> league display name
            _bc_kickoff / kickoff              -> formatted kickoff string
            _bc_broadcast                      -> broadcast info (unused here)

    Returns
    -------
    dict matching edge_summary.html template contract:
        total_edges, tiers, top_pick, date_label
    """
    if not tips:
        return _empty_data()

    # Count per tier
    counts: dict[str, int] = {k: 0 for k in _TIER_ORDER}
    for tip in tips:
        tier = _resolve_tier(tip)
        if tier in counts:
            counts[tier] += 1

    # Build tier pills (only include tiers with count > 0)
    tiers = []
    for tier_key in _TIER_ORDER:
        if counts[tier_key] > 0:
            meta = _TIER_META[tier_key]
            tiers.append({
                "emoji": meta["emoji"],
                "count": counts[tier_key],
                "label": meta["label"],
                "color": meta["color"],
                "bg_hex": meta["color"] + meta["bg_alpha"],
                "border_hex": meta["color"] + meta["border_alpha"],
            })

    # Top pick: highest EV tip in highest-ranked tier
    top_pick = _pick_top(tips)

    return {
        "total_edges": len(tips),
        "tiers": tiers,
        "top_pick": top_pick,
        "date_label": datetime.now().strftime("%-d %b %Y"),
        "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),
        "footer_logo_b64": logo_b64(_FOOTER_LOGO, max_height=32),
    }


def _empty_data() -> dict:
    return {
        "total_edges": 0,
        "tiers": [],
        "top_pick": None,
        "date_label": datetime.now().strftime("%-d %b %Y"),
    }


def _resolve_tier(tip: dict) -> str | None:
    # Resolution chain for tier badges.
    # `edge_tier` (from edge_results) is the CANONICAL source of truth.
    # `display_tier` / `edge_rating` / `tier` are backwards-compat fields from
    # older tip dict shapes.  Future code MUST write to `edge_tier`.
    # This chain is a backwards-compat shim — do not extend it.
    raw = (
        tip.get("display_tier")
        or tip.get("edge_rating")
        or tip.get("tier")
        or tip.get("edge_tier")
    )
    if raw is None:
        return None
    return str(raw).lower().strip()


def _pick_top(tips: list[dict]) -> dict | None:
    if not tips:
        return None

    # Sort: best tier first (diamond=0), then highest EV
    def sort_key(t):
        tier = _resolve_tier(t)
        rank = _TIER_META.get(tier, {"rank": 99})["rank"]
        ev = float(t.get("ev") or 0)
        return (rank, -ev)

    best = sorted(tips, key=sort_key)[0]
    tier = _resolve_tier(best)
    tier_color = _TIER_META.get(tier, {"color": "#A0AEC0"})["color"]

    # Parse kickoff into date + time parts.
    # FIX-REGRESS-D2-DATE-PILL-01: fall back to commence_time (fixture_mapping.kickoff)
    # when _bc_kickoff is absent (tips not yet passed through _build_hot_tips_page).
    kickoff_raw = best.get("_bc_kickoff") or best.get("kickoff") or ""
    if not kickoff_raw:
        kickoff_raw = _format_commence_time_sast(best.get("commence_time") or "")
    date_part, time_part = _split_kickoff(kickoff_raw)

    # Home/away
    home = best.get("home_team") or best.get("home") or ""
    away = best.get("away_team") or best.get("away") or ""

    # League
    league = (
        best.get("league")
        or best.get("league_display")
        or best.get("league_key", "").upper()
        or ""
    )

    # Odds
    odds_val = float(best.get("odds") or 0)
    odds_str = f"{odds_val:.2f}" if odds_val else ""

    # EV
    ev_val = float(best.get("ev") or 0)
    ev_str = f"{ev_val:.1f}"

    # Bookmaker
    bookmaker = (
        best.get("bookmaker")
        or best.get("bookie")
        or best.get("best_bookmaker")
        or ""
    )

    return {
        "home": home,
        "away": away,
        "league": league,
        "date": date_part,
        "time": time_part,
        "odds": odds_str,
        "ev": ev_str,
        "tier_color": tier_color,
        "bookmaker": bookmaker,
    }


def build_edge_picks_data(tips: list[dict], page: int = 1, per_page: int = 4, user_tier: str = "diamond") -> dict:
    """Build edge_picks.html template data (merged summary + picks card).

    Parameters
    ----------
    tips:
        Full list of tip dicts (same format as build_edge_summary_data).
    page:
        1-based page number. Page 1 shows picks [1]-[4], page 2 shows [5]-[8].
    per_page:
        Max picks per image (default 4).
    user_tier:
        Viewer's subscription tier. Non-Diamond users see masked Diamond edges
        (TIER-GATE-INV-01).

    Returns
    -------
    dict matching edge_picks.html template contract:
        tier_summary, total_edges, groups, page, total_pages,
        header_logo_b64, footer_logo_b64
    """
    if not tips:
        return {
            "tier_summary": [],
            "total_edges": 0,
            "groups": [],
            "page": 1,
            "total_pages": 1,
            "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),
            "footer_logo_b64": logo_b64(_FOOTER_LOGO, max_height=32),
        }

    # Sort all tips by tier rank, then EV descending within tier
    def _sort_key(t):
        tier_key = _resolve_tier(t)
        rank = _TIER_META.get(tier_key, {"rank": 99})["rank"]
        ev = float(t.get("ev") or 0)
        return (rank, -ev)

    sorted_tips = sorted(tips, key=_sort_key)
    total = len(sorted_tips)
    import math
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))

    # Tier summary: total counts across ALL pages
    counts: dict[str, int] = {k: 0 for k in _TIER_ORDER}
    for tip in sorted_tips:
        tk = _resolve_tier(tip)
        if tk in counts:
            counts[tk] += 1
    tier_summary = []
    for tk in _TIER_ORDER:
        if counts[tk] > 0:
            meta = _TIER_META[tk]
            tier_summary.append({"emoji": meta["emoji"], "count": counts[tk], "color": meta["color"]})

    # Slice for current page
    start = (page - 1) * per_page
    end = start + per_page
    page_tips = sorted_tips[start:end]

    # Assign sequential pick numbers: page 1 = 1..4, page 2 = 5..8
    # Group by tier for sub-headers (only tiers present on this page)
    groups_dict: dict[str, list[dict]] = {}
    for i, tip in enumerate(page_tips):
        number = start + i + 1
        tier_key = _resolve_tier(tip)
        meta = _TIER_META.get(tier_key, _TIER_META["bronze"])

        home = tip.get("home_team") or tip.get("home") or ""
        away = tip.get("away_team") or tip.get("away") or ""
        league = (
            tip.get("league")
            or tip.get("league_display")
            or tip.get("league_key", "").upper()
            or ""
        )
        kickoff_raw = tip.get("_bc_kickoff") or tip.get("kickoff") or ""
        if not kickoff_raw:
            kickoff_raw = _format_commence_time_sast(tip.get("commence_time") or "")
        # Support pre-split date/time fields (from SAMPLE_PICKS)
        date_part = tip.get("date") or ""
        time_part = tip.get("time") or ""
        if not date_part and not time_part:
            date_part, time_part = _split_kickoff(kickoff_raw)

        odds_val = float(tip.get("odds") or 0)
        odds_str = f"{odds_val:.2f}" if odds_val else ""
        ev_val = float(tip.get("ev") or 0)
        ev_str = f"{ev_val:.1f}"
        pick_name = (
            tip.get("pick")
            or tip.get("outcome")
            or tip.get("pick_team")
            or tip.get("home_team")
            or tip.get("home")
            or ""
        )
        bookmaker = (
            tip.get("bookmaker")
            or tip.get("bookie")
            or tip.get("best_bookmaker")
            or ""
        )
        prize_return = round(200 * odds_val) if odds_val else 0

        # TIER-GATE-INV-01: Diamond picks are masked for non-Diamond users
        _locked = tier_key == "diamond" and user_tier.lower().strip() != "diamond"

        pick_dict = {
            "number": number,
            "home": "" if _locked else home,
            "away": "" if _locked else away,
            "league": league,
            "date": date_part,
            "time": time_part,
            "channel": tip.get("channel") or "",  # BUILD-KO-SUPERSPORT-PRIMARY-01
            "odds": "" if _locked else odds_str,
            "ev": "" if _locked else ev_str,
            "pick": "" if _locked else pick_name,
            "bookmaker": "" if _locked else bookmaker,
            "sport_emoji": sport_emoji(league),
            "prize_return": 0 if _locked else prize_return,
            "locked": _locked,
        }

        if tier_key not in groups_dict:
            groups_dict[tier_key] = []
        groups_dict[tier_key].append(pick_dict)

    # Build ordered groups list (diamond → gold → silver → bronze, present tiers only)
    groups = []
    for tk in _TIER_ORDER:
        if tk in groups_dict:
            meta = _TIER_META[tk]
            groups.append({
                "tier_emoji": meta["emoji"],
                "tier_name": meta["label"],
                "tier_color": meta["color"],
                "picks": groups_dict[tk],
            })

    return {
        "tier_summary": tier_summary,
        "total_edges": total,
        "groups": groups,
        "page": page,
        "total_pages": total_pages,
        "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),
        "footer_logo_b64": logo_b64(_FOOTER_LOGO, max_height=32),
    }


def build_tier_page_data(tips: list[dict], tier: str) -> dict:
    """Build tier_page.html template data for a single tier.

    Parameters
    ----------
    tips:
        Full list of tip dicts (same format as build_edge_summary_data).
    tier:
        Tier key: 'diamond', 'gold', 'silver', or 'bronze'.

    Returns
    -------
    dict matching tier_page.html template contract:
        tier (dict with name/emoji/color/pick_label),
        picks (list of pick dicts),
        header_logo_b64, footer_logo_b64
    """
    meta = _TIER_META.get(tier.lower(), _TIER_META["bronze"])

    # Filter picks for this tier
    tier_tips = [t for t in tips if _resolve_tier(t) == tier.lower()]

    picks = []
    for tip in tier_tips:
        home = tip.get("home_team") or tip.get("home") or ""
        away = tip.get("away_team") or tip.get("away") or ""
        league = (
            tip.get("league")
            or tip.get("league_display")
            or tip.get("league_key", "").upper()
            or ""
        )
        kickoff_raw = tip.get("_bc_kickoff") or tip.get("kickoff") or ""
        date_part, time_part = _split_kickoff(kickoff_raw)
        odds_val = float(tip.get("odds") or 0)
        odds_str = f"{odds_val:.2f}" if odds_val else ""
        ev_val = float(tip.get("ev") or 0)
        ev_str = f"{ev_val:.1f}"
        pick_name = (
            tip.get("pick")
            or tip.get("outcome")
            or tip.get("pick_team")
            or tip.get("home_team")
            or tip.get("home")
            or ""
        )
        bookmaker = (
            tip.get("bookmaker")
            or tip.get("bookie")
            or tip.get("best_bookmaker")
            or ""
        )
        picks.append({
            "home": home,
            "away": away,
            "league": league,
            "date": date_part,
            "time": time_part,
            "odds": odds_str,
            "ev": ev_str,
            "pick": pick_name,
            "bookmaker": bookmaker,
            "channel": tip.get("channel") or "",  # BUILD-KO-SUPERSPORT-PRIMARY-01
        })

    pick_count = len(picks)
    pick_label = f"{pick_count} pick{'s' if pick_count != 1 else ''}"

    return {
        "tier": {
            "name": meta["label"],
            "emoji": meta["emoji"],
            "color": meta["color"],
            "pick_label": pick_label,
        },
        "picks": picks,
        "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=44),
        "footer_logo_b64": logo_b64(_FOOTER_LOGO, max_height=32),
    }


def _confidence_tier(pct: float) -> str:
    if pct >= 95:
        return "MAX"
    elif pct >= 85:
        return "STRONG"
    elif pct >= 70:
        return "SOLID"
    else:
        return "MILD"


def _channel_fields(tip: dict) -> dict:
    """Channel display permanently removed (FIX-DSTV-CHANNEL-PERM-01).

    Returns empty channel fields so templates render nothing.
    """
    return {
        "channel_number": "",
        "channel_is_ss": False,
        "ss_logo_b64": "",
    }



def _build_important_injuries(home_injuries: list, away_injuries: list) -> str:
    """Build compact single-line injuries string from home/away injury lists.

    Returns up to 3 player names with status, empty string when no data.
    FIX-REGRESS-D1-BOOKMAKER-LINE-01: feeds the injuries-line that replaces
    the freed row from single-line bookmaker fix.
    """
    items: list[str] = []
    for inj_list in (home_injuries, away_injuries):
        for inj in inj_list:
            if isinstance(inj, dict):
                name = (inj.get("player") or inj.get("name") or "").strip()
                status = (inj.get("reason") or inj.get("status") or "").strip()
                if name:
                    s = name
                    if status:
                        s += f" ({status[:10]})"
                    items.append(s)
            elif isinstance(inj, str) and inj.strip():
                _s = inj.strip()[:25]
                # Close any unclosed parenthesis caused by truncation
                if "(" in _s and not _s.rstrip().endswith(")"):
                    _s = _s.rstrip() + ")"
                items.append(_s)
            if len(items) >= 3:
                return ", ".join(items)
    return ", ".join(items) if items else ""


def build_edge_detail_data(tip: dict, card_width: int = 480) -> dict:
    """Build edge_detail.html template data from a single tip/edge.

    Parameters
    ----------
    tip:
        Single tip dict. Expected fields (all optional with graceful fallbacks):
            tier / display_tier / edge_rating  -> tier key
            ev                                 -> EV percentage (float)
            home / home_team                   -> home team name
            away / away_team                   -> away team name
            league / league_display            -> league name
            date, time                         -> formatted date/time strings
            channel / ch                       -> DStv channel number
            venue                              -> stadium/venue name
            home_form, away_form               -> list of "W"/"D"/"L" strings
            pick                               -> pick description
            pick_odds / odds                   -> best odds (float)
            bookmaker                          -> bookmaker display name
            all_odds                           -> list of {bookie/b, odds/o} dicts
            signals                            -> dict {name: bool} or list [{name, active}]
            fair_value                         -> int 0-100
            confidence                         -> int 0-100
            h2h / h2h_total,h2h_home_wins...   -> H2H data
            home_injuries, away_injuries       -> lists of injury strings
            verdict                            -> verdict text string
    card_width:
        Rendered card width in pixels (default 480). Controls max bookmaker
        pill count: ≥480 → 4, ≥360 → 3, <360 → 2 (FIX-REGRESS-D1-BOOKMAKER-LINE-01).
    """
    # FIX 2: display_tier=None means no edge — suppress tier/pick/verdict in template.
    # Also gates on edge_tier so a tip with ONLY edge_tier set still resolves correctly.
    raw_tier = tip.get("display_tier")
    if (
        raw_tier is None
        and not tip.get("edge_rating")
        and not tip.get("tier")
        and not tip.get("edge_tier")
    ):
        tier_key = None
    else:
        tier_key = _resolve_tier(tip)
    meta = _TIER_META.get(tier_key, _TIER_META["bronze"]) if tier_key else {
        "emoji": "", "label": "", "color": "#777777", "rank": 99,
        "bg_alpha": "10", "border_alpha": "15",
    }

    home = tip.get("home") or tip.get("home_team") or ""
    away = tip.get("away") or tip.get("away_team") or ""
    league = tip.get("league") or tip.get("league_display") or ""

    # EV
    ev_val = float(tip.get("ev") or 0)
    ev_str = f"{ev_val:.2f}"

    # Pick odds — float for comparison in template, string for display
    pick_odds_val = float(tip.get("pick_odds") or tip.get("odds") or 0)
    pick_odds_str = f"{pick_odds_val:.2f}"

    # Prize return: R200 × odds, rounded to nearest R1
    prize_return = round(200 * pick_odds_val) if pick_odds_val > 0 else 200

    # All odds — normalise {b, o} or {bookie, odds} formats
    raw_all_odds = tip.get("all_odds") or []
    all_odds = []
    for o in raw_all_odds:
        bookie = o.get("bookie") or o.get("b") or ""
        odds_f = float(o.get("odds") or o.get("o") or 0)
        all_odds.append({
            "bookie": bookie,
            "odds": f"{odds_f:.2f}",
            "odds_float": odds_f,
            "is_pick": bool(o.get("is_pick")),
        })
    # FIX-REGRESS-D1-BOOKMAKER-LINE-01: deterministic count-drop based on card width.
    # 480px → max 4 pills · 360px → max 3 · <360px → max 2.
    # Row has nowrap+overflow:hidden so wrapping is impossible — extra pills are hidden.
    _max_bk = 3  # max 3 bookmaker chips always (UX contract)
    all_odds.sort(key=lambda x: x["odds_float"], reverse=True)
    # D-12: min 2 chips (hide pills row if <2)
    if len(all_odds) < 2:
        all_odds = []
    elif len(all_odds) > _max_bk:
        all_odds = all_odds[:_max_bk]

    # Signals — normalise from dict or list
    _SIGNAL_DISPLAY = {
        "line_mvt":    "Line Mvt",
        "movement":    "Line Mvt",
        "price_edge":  "Price Edge",
        "tipster":     "Tipster",
        "form":        "Form",
        "market":      "Market",
        "injury":      "Injury",
    }
    raw_signals = tip.get("signals") or {}
    if isinstance(raw_signals, dict):
        signals = [{"name": _SIGNAL_DISPLAY.get(k, k), "active": bool(v)} for k, v in raw_signals.items()]
    else:
        signals = [{"name": _SIGNAL_DISPLAY.get(s.get("name", ""), s.get("name", "")), "active": bool(s.get("active"))} for s in raw_signals]

    # CARD-FIX-B Task 5: pad to 6 canonical signals in fixed order
    _CANONICAL_SIGNALS = ["Price Edge", "Line Mvt", "Form", "Market", "Tipster", "Injury"]
    existing_names = {s["name"] for s in signals}
    for canon in _CANONICAL_SIGNALS:
        if canon not in existing_names:
            signals.append({"name": canon, "active": False})
    signals.sort(key=lambda s: _CANONICAL_SIGNALS.index(s["name"]) if s["name"] in _CANONICAL_SIGNALS else 99)

    # H2H — support nested dict {n, hw, d, aw} or flat fields
    h2h = tip.get("h2h") or {}
    h2h_total    = int(h2h.get("n")  or tip.get("h2h_total")     or 0)
    h2h_home_wins = int(h2h.get("hw") or tip.get("h2h_home_wins") or 0)
    h2h_draws    = int(h2h.get("d")  or tip.get("h2h_draws")     or 0)
    h2h_away_wins = int(h2h.get("aw") or tip.get("h2h_away_wins") or 0)

    # BUILD-KO-TIME-FIX-01: never fall back to "TBC". _enrich_tip_for_card() now
    # populates tip["time"] via _resolve_kickoff_time() (sport-aware fixture table
    # lookups). For sports with no time data (rugby, mma), time_str is empty and
    # the template renders date-only gracefully.
    # FIX-REGRESS-D2-DATE-PILL-01: fall back to commence_time when _bc_kickoff absent.
    kickoff_raw = tip.get("_bc_kickoff") or tip.get("kickoff") or ""
    if not kickoff_raw:
        kickoff_raw = _format_commence_time_sast(tip.get("commence_time") or "")
    date_part, time_part = _split_kickoff(kickoff_raw)
    date_str = tip.get("date") or date_part
    _raw_time = tip.get("time") or time_part
    # Coerce midnight sentinel (00:00 / 0:00) — stored when DB has date-only fixtures
    if _raw_time in ("00:00", "0:00", "0:00:00", "02:00", "TBC"):
        _raw_time = ""
    time_str = _raw_time or ""

    return {
        # Tier
        "tier":       tier_key,
        "tier_emoji": meta["emoji"],
        "tier_name":  meta["label"],
        "tier_color": meta["color"],

        # Match identity
        "sport_emoji": tip.get("sport_emoji") or sport_emoji(league),
        "league":  league,
        "home":    home,
        "away":    away,
        "date":    date_str,
        "time":    time_str,
        "channel": tip.get("channel") or "",  # BUILD-KO-SUPERSPORT-PRIMARY-01
        "venue":   tip.get("venue") or "",

        # Form
        "home_form": tip.get("home_form") or [],
        "away_form": tip.get("away_form") or [],

        # The Pick
        "pick":           tip.get("pick") or "",
        "pick_odds":      pick_odds_str,
        "pick_odds_float": pick_odds_val,
        "bookmaker":      tip.get("bookmaker") or "",
        "ev":             ev_str,
        "prize_return":   prize_return,
        "all_odds":       all_odds,

        # Signals + bars
        "signals":     signals,
        "fair_value":  int(tip.get("fair_value") or 0),
        "confidence":  int(tip.get("confidence") or 0),
        "confidence_tier": _confidence_tier(int(tip.get("confidence") or 0)),

        # H2H
        "h2h_total":     h2h_total,
        "h2h_home_wins": h2h_home_wins,
        "h2h_draws":     h2h_draws,
        "h2h_away_wins": h2h_away_wins,

        # Injuries — rendered in their own section (BUILD-VERDICT-INJURY-SPLIT-01)
        # DEF-2: capped at 3 per team to prevent card overflow
        "home_injuries": (tip.get("home_injuries") or [])[:3],
        "away_injuries": (tip.get("away_injuries") or [])[:3],
        # FIX-INJURY-SUPPRESS-01: always empty — injury line suppressed on Edge Detail cards.
        "important_injuries": "",

        # Verdict — raw, no injury appending (BUILD-VERDICT-INJURY-SPLIT-01)
        "verdict": tip.get("verdict") or "",

        # Tipsters — FIX 4 (CARD-REBUILD-03A); resolve "Home"/"Away" to team names (D-18)
        "top_tipsters": [
            {**t, "pick": home if t.get("pick") == "Home" else (away if t.get("pick") == "Away" else t.get("pick", ""))}
            for t in (tip.get("top_tipsters") or [])
        ],

        # Logo
        "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),

        # Model calibration badge — shown on rugby cards while Glicko-2 accumulates data (RUGBY-FIX-01)
        "model_badge": "Model Calibrating" if tip.get("sport") in ("rugby", "super_rugby") else None,
    }


def _fmt_odds(v) -> str | None:
    """Format an odds value as '1.85' string, or None if no draw."""
    if v is None:
        return None
    try:
        f = float(v)
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return str(v) if v else None


def build_my_matches_data(matches: list[dict], page: int = 1, per_page: int = 4) -> dict:
    """Build my_matches.html template data.

    Splits matches into edge_matches (has_edge=True) and upcoming_matches.
    Edge matches sorted first (by tier: diamond > gold > silver > bronze).
    Upcoming matches preserve caller order.
    Paginates: max 4 per image, edge matches first then upcoming.
    Assigns sequential [N] numbers across both groups.
    total_matches and total_edges reflect ALL matches, not just current page.

    Parameters
    ----------
    matches:
        List of match dicts. Expected fields:
            has_edge    bool  — True if an edge was found for this match
            home        str   — home team display name (also: home_team)
            away        str   — away team display name (also: away_team)
            league      str   — league display name
            date        str   — formatted date string, e.g. "Sat 12 Apr"
            time        str   — formatted time string, e.g. "13:30"
            channel     str   — DStv channel number (optional)
            sport_emoji str   — override sport emoji (optional; auto-derived from league)
            -- edge-only fields --
            edge_tier   str   — 'diamond'|'gold'|'silver'|'bronze'
            pick        str   — recommended pick team name
            bookmaker   str   — bookmaker display name
            -- non-edge fields --
            odds_home   float — home win odds
            odds_draw   float|None — draw odds (None for cricket/MMA/boxing)
            odds_away   float — away win odds
    """
    import math

    if not matches:
        return {
            "total_matches": 0,
            "total_edges": 0,
            "edge_matches": [],
            "upcoming_matches": [],
            "page": 1,
            "total_pages": 1,
            "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),
        }

    # Split into edge and non-edge
    all_edge = [m for m in matches if m.get("has_edge")]
    all_non_edge = [m for m in matches if not m.get("has_edge")]

    # Sort edge matches by tier rank (diamond first)
    def _edge_rank(m: dict) -> int:
        tier = (m.get("edge_tier") or "bronze").lower()
        return _TIER_META.get(tier, {"rank": 99})["rank"]

    all_edge_sorted = sorted(all_edge, key=_edge_rank)

    # Flat ordered list: edge first, then upcoming (preserve caller order for non-edge)
    all_flat = all_edge_sorted + all_non_edge
    total = len(all_flat)
    total_edges = len(all_edge)

    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    page_slice = all_flat[start:end]

    edge_matches: list[dict] = []
    upcoming_matches: list[dict] = []

    for i, m in enumerate(page_slice):
        number = start + i + 1
        home = m.get("home") or m.get("home_team") or ""
        away = m.get("away") or m.get("away_team") or ""
        league = m.get("league") or m.get("league_display") or ""
        s_emoji = m.get("sport_emoji") or sport_emoji(league)
        date_part = m.get("date") or ""
        time_part = m.get("time") or ""
        if m.get("has_edge"):
            _et_raw = m.get("edge_tier")
            tier_key = _et_raw.lower() if _et_raw else None
            meta = _TIER_META.get(tier_key, _TIER_META["bronze"]) if tier_key else {
                "emoji": "", "label": "", "color": "#777777", "rank": 99,
                "bg_alpha": "10", "border_alpha": "15",
            }
            edge_matches.append({
                "number": number,
                "home": home,
                "away": away,
                "league": league,
                "sport_emoji": s_emoji,
                "date": date_part,
                "time": time_part,
                "channel": m.get("channel") or "",  # BUILD-KO-SUPERSPORT-PRIMARY-01
                "has_edge": True,
                "edge_tier": tier_key,
                "tier_emoji": meta["emoji"],
                "tier_color": meta["color"],
                "pick": m.get("pick") or "",
                "bookmaker": m.get("bookmaker") or "",
            })
        else:
            upcoming_matches.append({
                "number": number,
                "home": home,
                "away": away,
                "league": league,
                "sport_emoji": s_emoji,
                "date": date_part,
                "time": time_part,
                "channel": m.get("channel") or "",  # BUILD-KO-SUPERSPORT-PRIMARY-01
                "has_edge": False,
                "odds_home": _fmt_odds(m.get("odds_home")),
                "odds_draw": _fmt_odds(m.get("odds_draw")),
                "odds_away": _fmt_odds(m.get("odds_away")),
            })

    return {
        "total_matches": total,
        "total_edges": total_edges,
        "edge_matches": edge_matches,
        "upcoming_matches": upcoming_matches,
        "page": page,
        "total_pages": total_pages,
        "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),
    }


def build_match_detail_data(match: dict) -> dict:
    """Build match_detail template data from a single match (no edge).

    Parameters
    ----------
    match:
        Single match dict. Expected fields (all optional with graceful fallbacks):
            league / league_display            -> league name
            home / home_team                   -> home team display name
            away / away_team                   -> away team display name
            date, time                         -> formatted date/time strings
            channel / ch                       -> DStv channel (already formatted, e.g. "DStv 211")
            venue                              -> stadium/venue name
            home_form, away_form               -> list of "W"/"D"/"L" strings
            home_odds                          -> best home win odds (float)
            home_bookie                        -> bookmaker for home odds
            draw_odds                          -> best draw odds (float or None)
            draw_bookie                        -> bookmaker for draw odds
            away_odds                          -> best away win odds (float)
            away_bookie                        -> bookmaker for away odds
            reason                             -> "why no edge" explanation string
            stats                              -> list of {label, value, context} dicts
            h2h / h2h_total,h2h_home_wins...   -> H2H data
            home_injuries, away_injuries       -> lists of injury strings
    """
    home = match.get("home") or match.get("home_team") or ""
    away = match.get("away") or match.get("away_team") or ""
    league = match.get("league") or match.get("league_display") or ""

    # H2H — support nested dict {n, hw, d, aw} or flat fields
    h2h = match.get("h2h") or {}
    h2h_total     = int(h2h.get("n")  or match.get("h2h_total")     or 0)
    h2h_home_wins = int(h2h.get("hw") or match.get("h2h_home_wins") or 0)
    h2h_draws     = int(h2h.get("d")  or match.get("h2h_draws")     or 0)
    h2h_away_wins = int(h2h.get("aw") or match.get("h2h_away_wins") or 0)

    # Odds — format as string with 2dp
    def _fmt(v) -> str:
        try:
            return f"{float(v):.2f}" if v is not None else ""
        except (TypeError, ValueError):
            return str(v) if v else ""

    return {
        # Identity
        "sport_emoji": match.get("sport_emoji") or sport_emoji(league),
        "league":  league,
        "home":    home,
        "away":    away,
        "date":    match.get("date") or "",
        "time":    match.get("time") or "",
        "channel": match.get("channel") or "",  # BUILD-KO-SUPERSPORT-PRIMARY-01
        # Form
        "home_form": match.get("home_form") or [],
        "away_form": match.get("away_form") or [],

        # Market Overview
        "home_odds":   _fmt(match.get("home_odds")),
        "home_bookie": match.get("home_bookie") or "",
        "draw_odds":   _fmt(match.get("draw_odds")) if match.get("draw_odds") is not None else None,
        "draw_bookie": match.get("draw_bookie") or "",
        "away_odds":   _fmt(match.get("away_odds")),
        "away_bookie": match.get("away_bookie") or "",

        # Why no edge
        "reason": match.get("reason") or "",

        # Key Stats
        "stats": match.get("stats") or [],

        # H2H
        "h2h_total":     h2h_total,
        "h2h_home_wins": h2h_home_wins,
        "h2h_draws":     h2h_draws,
        "h2h_away_wins": h2h_away_wins,

        "home_injuries": match.get("home_injuries") or [],
        "away_injuries": match.get("away_injuries") or [],

        # Haiku analysis — BUILD-HAIKU-SUMMARY-WIRE-01
        "analysis_text": match.get("analysis_text") or "",

        # Logo
        "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),
    }


def _split_kickoff(kickoff: str) -> tuple[str, str]:
    """Split 'Today 19:30' or 'Fri 6 Mar · 15:00' into (date, time)."""
    if not kickoff:
        return "", ""
    # Try '·' separator
    if "\u00b7" in kickoff or "·" in kickoff:
        sep = "\u00b7" if "\u00b7" in kickoff else "·"
        parts = kickoff.split(sep, 1)
        return parts[0].strip(), parts[1].strip()
    # Try space before HH:MM pattern — strip trailing timezone suffix first
    # e.g. "Tomorrow 14:55 SAST" → "Tomorrow 14:55" so regex can match
    import re
    kickoff_clean = re.sub(r'\s+[A-Z]{2,4}$', '', kickoff.strip())
    m = re.match(r"^(.*?)\s+(\d{1,2}:\d{2})$", kickoff_clean)
    if m:
        return m.group(1).strip(), m.group(2)
    # Just date
    return kickoff.strip(), ""


def _format_commence_time_sast(iso_str: str) -> str:
    """Convert UTC ISO kickoff to SAST display string for date-pill rendering.

    FIX-REGRESS-D2-DATE-PILL-01: fallback for tips that carry commence_time
    (fixture_mapping.kickoff) but have no _bc_kickoff or kickoff field set.
    Returns "Today 19:30", "Tomorrow 19:30", "Thu 17 Apr 19:30", or "" on failure.
    """
    try:
        from zoneinfo import ZoneInfo
        from datetime import timedelta, timezone
        _SAST = ZoneInfo("Africa/Johannesburg")
        s = (iso_str or "").strip()
        if not s:
            return ""
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "T" not in s and " " in s:
            s = s.replace(" ", "T")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_sast = dt.astimezone(_SAST)
        today = datetime.now(_SAST).date()
        delta = (dt_sast.date() - today).days
        if delta == 0:
            date_part = "Today"
        elif delta == 1:
            date_part = "Tomorrow"
        elif delta < 0:
            date_part = dt_sast.strftime("%-d %b")
        else:
            date_part = dt_sast.strftime("%a %-d %b")
        time_part = dt_sast.strftime("%H:%M")
        # 00:00 UTC = 02:00 SAST is a placeholder, not a real kickoff time
        if time_part == "02:00":
            return date_part
        return f"{date_part} {time_part}"
    except Exception:
        return ""
