"""IMG-PW1: Data adapter — build edge_summary template data from pipeline tips.

Public API:
    build_edge_summary_data(tips: list[dict]) -> dict
    build_ai_breakdown_data(match_id: str) -> dict | None
"""
from __future__ import annotations
import base64
import io
import json
import logging
import re as _re
from datetime import datetime
from pathlib import Path


def _extract_dstv_num(channel: str) -> str:
    """Extract DStv channel number from channel string e.g. 'SuperSport (DStv 203)' → '203'."""
    if not channel:
        return ""
    m = _re.search(r"DStv\s+(\d+)", channel)
    return m.group(1) if m else ""

log = logging.getLogger(__name__)

# ── Logo helpers ───────────────────────────────────────────────────────────────
_BOT_DIR = Path(__file__).parent
_ASSETS_DIR = _BOT_DIR.parent / "assets"

_HEADER_LOGO = _BOT_DIR / "assets" / "LOGO" / "mzansiedge-wordmark-dark-transparent.png"
_FOOTER_LOGO = _ASSETS_DIR / "LOGO" / "mzansiedge-micro-mark-e-transparent.png"
_SS_LOGO = _BOT_DIR.parent / "assets" / "icons" / "ss.png"
_SS_ICON_40 = _BOT_DIR.parent / "assets" / "icons" / "ss_40.png"


def _load_ss_icon_b64() -> str:
    """Load SuperSport icon as base64 data URL (40×40 PNG)."""
    import PIL.Image
    try:
        path = _SS_ICON_40 if _SS_ICON_40.exists() else _SS_LOGO
        with PIL.Image.open(path) as img:
            buf = io.BytesIO()
            img.convert("RGBA").resize((40, 40), PIL.Image.LANCZOS).save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


_SS_ICON_B64: str = _load_ss_icon_b64()


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
_HOT_TIPS_ALLOC_TARGET = 10


def _allocate_tips_by_tier(tips: list[dict], min_per_tier: int = 3) -> list[dict]:
    """Return a tier-aware Hot Tips list while preserving order within each tier."""
    if not tips:
        return []

    min_count = max(int(min_per_tier or 0), 0)
    grouped: dict[str, list[tuple[int, dict]]] = {tier: [] for tier in _TIER_ORDER}

    for idx, tip in enumerate(tips):
        tier = (
            tip.get("edge_tier")
            or tip.get("display_tier")
            or tip.get("edge_rating")
            or tip.get("tier")
            or "bronze"
        )
        tier_key = str(tier).lower().strip()
        if tier_key not in grouped:
            tier_key = "bronze"
        grouped[tier_key].append((idx, tip))

    allocated: list[dict] = []
    selected_indexes: set[int] = set()

    for tier in _TIER_ORDER:
        for idx, tip in grouped[tier][:min_count]:
            allocated.append(tip)
            selected_indexes.add(idx)

    target_count = max(min(len(tips), _HOT_TIPS_ALLOC_TARGET), len(allocated))
    if len(allocated) >= target_count:
        return allocated

    for tier in _TIER_ORDER:
        for idx, tip in grouped[tier]:
            if len(allocated) >= target_count:
                return allocated
            if idx in selected_indexes:
                continue
            allocated.append(tip)
            selected_indexes.add(idx)

    return allocated

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


def _resolve_cap_reason(tip: dict, tier_key: str | None) -> str:
    """FIX-CARD-SURFACE-TIER-CAP-REASON-01: derive cap reason from (league, tier).

    Returns the plain-English cap reason when the tip's league has a structural
    LEAGUE_TIER_CAP and the resolved tier matches that cap. Empty string for
    uncapped edges (AC-6 regression guard — irrelevant cap text MUST NOT appear
    on cards where no cap fired).

    Reads from scrapers.edge.tier_engine to keep the helper as the single source
    of truth (AC-2: sibling helper to assign_tier()).
    """
    if not tier_key:
        return ""
    league = (
        tip.get("league_key")
        or tip.get("league")
        or tip.get("league_display")
        or ""
    )
    if not league:
        return ""
    league_lower = str(league).lower().strip().replace(" ", "_")
    try:
        from scrapers.edge.tier_engine import get_league_cap_reason
    except Exception:
        return ""
    reason = get_league_cap_reason(league_lower, tier_key)
    return reason or ""


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


def _normalise_tier_key(raw: object, default: str = "bronze") -> str:
    key = str(raw or default).lower().strip()
    return key if key in _TIER_META else default


def edge_picks_index_tier_locked(user_tier: str, edge_tier: str) -> bool:
    """Return whether the index row should route through upgrade.

    The list/detail surface can expose partial or blurred higher-tier previews.
    The index is a tier entry menu, so tiers above the user's plan route to the
    upsell even when the underlying list gate classifies them as previewable.
    """
    import tier_gate

    user_key = _normalise_tier_key(user_tier)
    edge_key = _normalise_tier_key(edge_tier)
    access_level = tier_gate.get_edge_access_level(user_key, edge_key)
    if access_level == "locked":
        return True
    return _TIER_META[edge_key]["rank"] < _TIER_META[user_key]["rank"]


def build_edge_picks_index_data(user_tier: str, tier_counts: dict[str, int]) -> dict:
    """Build edge_picks_index.html template data for the tier menu."""
    counts = {key: 0 for key in _TIER_ORDER}
    for raw_key, raw_count in (tier_counts or {}).items():
        key = _normalise_tier_key(raw_key)
        try:
            count = int(raw_count or 0)
        except (TypeError, ValueError):
            count = 0
        counts[key] += max(count, 0)

    total_edges = sum(counts.values())
    tier_summary = []
    for key in _TIER_ORDER:
        meta = _TIER_META[key]
        tier_summary.append({
            "emoji": meta["emoji"],
            "count": counts[key],
            "color": meta["color"],
        })

    default_key = next(
        (key for key in _TIER_ORDER if not edge_picks_index_tier_locked(user_tier, key)),
        "bronze",
    )

    tiers = []
    for key in _TIER_ORDER:
        meta = _TIER_META[key]
        locked = edge_picks_index_tier_locked(user_tier, key)
        tiers.append({
            "key": key,
            "emoji": meta["emoji"],
            "label": meta["label"],
            "color": meta["color"],
            "count": counts[key],
            "locked": locked,
            "is_default": key == default_key and not locked,
            "bg_alpha": meta["bg_alpha"],
            "border_alpha": meta["border_alpha"],
        })

    return {
        "header_logo_b64": logo_b64(_HEADER_LOGO, max_height=64),
        "tier_summary": tier_summary,
        "total_edges": total_edges,
        "live_total": total_edges,
        "tiers": tiers,
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
        "channel_logo_url": tip.get("channel_logo_url") or "",  # BUILD-CHANNEL-LOGOS-01
        "channel_dstv_num": _extract_dstv_num(tip.get("channel") or ""),  # BUILD-CHANNEL-LOGOS-01
        "ss_icon_b64": _SS_ICON_B64,  # BUILD-CHANNEL-LOGOS-01: SuperSport icon for badge
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

        # FIX-CARD-SURFACE-TIER-CAP-REASON-01: structural cap explanation surfaces
        # beneath the verdict when LEAGUE_TIER_CAP fires (Super Rugby / Currie Cup
        # capped at Silver). Empty string for uncapped edges.
        "cap_reason": _resolve_cap_reason(tip, tier_key),

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
        "channel_logo_url": match.get("channel_logo_url") or "",  # BUILD-CHANNEL-LOGOS-01
        "channel_dstv_num": _extract_dstv_num(match.get("channel") or ""),  # BUILD-CHANNEL-LOGOS-01
        "ss_icon_b64": _SS_ICON_B64,  # BUILD-CHANNEL-LOGOS-01: SuperSport icon for badge
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

        # Edge badge — BUILD-MM-EDGE-INDICATOR-01
        "edge_badge_tier":  match.get("edge_badge_tier") or "",
        "edge_badge_label": match.get("edge_badge_label") or "",
        "edge_badge_emoji": match.get("edge_badge_emoji") or "",

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


# ── AI Breakdown card data ─────────────────────────────────────────────────────


def _check_premium_defer(match_id: str) -> dict | None:
    """FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 AC-3.

    Read ``gold_verdict_failed_edges`` (in ``bot/data/mzansiedge.db``) for a
    deferred-state row keyed by ``match_id``. The pregen Wave 2 chain UPSERTs
    here whenever Sonnet polish + Haiku polish both fail for a premium card.

    Returns a dict ``{match_key, edge_tier, consecutive_count, fixture}`` when
    a defer row exists, else ``None``. Best-effort — any DB error returns None
    (caller treats missing defer as "not deferred"). Never raises.
    """
    import os as _os
    from pathlib import Path as _PathDefer

    _bot_dir = _PathDefer(__file__).parent
    _bot_db = str(_bot_dir / "data" / "mzansiedge.db")
    if not _os.path.exists(_bot_db):
        return None
    try:
        from db_connection import get_connection as _defer_conn
        _c = _defer_conn(_bot_db, timeout_ms=2000)
    except Exception:
        return None
    try:
        try:
            row = _c.execute(
                "SELECT match_key, edge_tier, fixture, consecutive_count "
                "FROM gold_verdict_failed_edges WHERE match_key = ?",
                (match_id,),
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        return {
            "match_key": row[0],
            "edge_tier": (row[1] or "").lower(),
            "fixture": row[2] or "",
            "consecutive_count": int(row[3] or 1),
        }
    finally:
        try:
            _c.close()
        except Exception:
            pass


def _check_premium_quarantined(match_id: str) -> dict | None:
    """FIX-PREMIUM-POSTWRITE-PROTECTION-01 AC-2.

    Detect a premium-tier ``narrative_cache`` row marked ``status='quarantined'``.
    The view-time SELECT in ``build_ai_breakdown_data`` already filters these out
    (so a tainted row never renders), but a quarantined w84 row paired with NO
    ``gold_verdict_failed_edges`` defer entry would otherwise fall through to the
    W82 synthesis-on-tap baseline — the exact W82-boilerplate regression the
    predecessor brief documented (Brentford–West Ham, Brighton–Wolves, 29 Apr).

    This helper closes that gap: if any ``status='quarantined'`` row exists for
    a Gold/Diamond edge tier, the caller should serve the deferred placeholder
    instead of synthesising a W82 baseline. The pregen sweep (or polish retry)
    will replace the row with a clean w84 narrative on the next cycle.

    Reads from ``scrapers/odds.db`` (the canonical narrative_cache DB,
    ``_NARRATIVE_DB_PATH`` in bot.py — same DB the AC-3 corpus invariant test
    queries for w84/w84-haiku-fallback rows).

    Returns ``{match_key, edge_tier, quarantine_reason}`` when at least one
    quarantined premium row exists, else ``None``. Best-effort — any DB error
    returns None. Never raises.
    """
    import os as _os
    from pathlib import Path as _PathQuar

    _bot_dir = _PathQuar(__file__).parent
    _SCRAPERS_DIR = _PathQuar(_os.environ.get("SCRAPERS_ROOT", str(_bot_dir.parent / "scrapers")))
    _ODDS_DB = str(_SCRAPERS_DIR / "odds.db")
    if not _os.path.exists(_ODDS_DB):
        return None
    try:
        from scrapers.db_connect import connect_odds_db as _quar_conn
        _c = _quar_conn(_ODDS_DB)
    except Exception:
        return None
    try:
        try:
            row = _c.execute(
                "SELECT match_id, edge_tier, COALESCE(quarantine_reason, '') "
                "FROM narrative_cache "
                "WHERE match_id = ? "
                "AND status = 'quarantined' "
                "AND LOWER(COALESCE(edge_tier, '')) IN ('gold', 'diamond') "
                "LIMIT 1",
                (match_id,),
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        return {
            "match_key": row[0],
            "edge_tier": (row[1] or "").lower(),
            "quarantine_reason": row[2] or "",
        }
    finally:
        try:
            _c.close()
        except Exception:
            pass


def _check_premium_edge(match_id: str) -> str | None:
    """Look up ``edge_results`` for ``match_id``; return tier ("gold"/"diamond")
    when an unsettled premium edge exists, else ``None``. Best-effort.

    Used by the AI Breakdown view-time path to decide whether the
    PremiumOrphan ERROR log + Sentry breadcrumb should fire when no
    narrative_cache row is found and synthesis also fails.
    """
    import os as _os
    from pathlib import Path as _PathOrph

    _bot_dir = _PathOrph(__file__).parent
    _SCRAPERS_DIR = _PathOrph(_os.environ.get("SCRAPERS_ROOT", str(_bot_dir.parent / "scrapers")))
    _ODDS_DB = str(_SCRAPERS_DIR / "odds.db")
    if not _os.path.exists(_ODDS_DB):
        return None
    try:
        from scrapers.db_connect import connect_odds_db as _orph_conn
        _c = _orph_conn(_ODDS_DB)
    except Exception:
        return None
    try:
        row = _c.execute(
            "SELECT edge_tier FROM edge_results "
            "WHERE match_key = ? AND result IS NULL "
            "ORDER BY recommended_at DESC LIMIT 1",
            (match_id,),
        ).fetchone()
        if not row:
            return None
        tier = (row[0] or "").lower()
        if tier in ("gold", "diamond"):
            return tier
        return None
    except Exception:
        return None
    finally:
        try:
            _c.close()
        except Exception:
            pass


def _synthesize_breakdown_row_from_baseline(match_id: str) -> tuple | None:
    """FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01: instant-baseline fallback.

    When no eligible narrative_cache row exists for ``match_id`` (because the
    match was never pregenerated, or the only row is a verdict-cache row with
    empty ``narrative_html``), synthesize a row tuple in the exact shape
    ``build_ai_breakdown_data`` expects from the DB SELECT, using:

      1. edge_results lookup for sport / league / tier / odds / bookmaker / EV
      2. ``narrative_spec.build_narrative_spec(...)`` to construct a NarrativeSpec
      3. ``narrative_spec._render_baseline(spec)`` to produce the 4-section HTML

    Zero LLM calls, zero ESPN context fetch — same instant-baseline path used by
    ``_generate_narrative_v2(live_tap=True)`` and the Hot Tips warm path.
    Latency target: < 100ms (deterministic templates only).

    Returns ``(narrative_html, edge_tier, tips_json, verdict_html='',
              evidence_class='', created_at_iso)`` matching the DB row order,
    or ``None`` when there is no edge data for this match either (truly
    unreachable). The caller then returns ``None`` to its own caller.
    """
    import json as _json
    import os
    import re as _re
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    _BOT_DIR = _Path(__file__).parent
    _SCRAPERS_DIR = _Path(os.environ.get("SCRAPERS_ROOT", str(_BOT_DIR.parent / "scrapers")))
    _ODDS_DB = str(_SCRAPERS_DIR / "odds.db")

    try:
        from scrapers.db_connect import connect_odds_db
        _conn = connect_odds_db(_ODDS_DB)
    except Exception as exc:
        log.debug("baseline-fallback: cannot connect to odds.db: %s", exc)
        return None

    edge_row = None
    try:
        try:
            edge_row = _conn.execute(
                """SELECT sport, league, edge_tier, composite_score, bet_type,
                          recommended_odds, bookmaker, predicted_ev,
                          confirming_signals, movement
                   FROM edge_results
                   WHERE match_key = ?
                   ORDER BY (result IS NULL) DESC, recommended_at DESC
                   LIMIT 1""",
                (match_id,),
            ).fetchone()
        except Exception as exc:
            log.debug("baseline-fallback: edge_results lookup failed for %s: %s", match_id, exc)
    finally:
        try:
            _conn.close()
        except Exception:
            pass

    if not edge_row:
        return None

    sport, league, edge_tier, composite_score, bet_type, odds, bookmaker, ev, confirming, movement = edge_row
    sport = (sport or "soccer").lower()
    edge_tier = (edge_tier or "bronze").lower()

    # bet_type is shaped like "1X2:home" / "1X2:away" / "1X2:draw"; outcome is the suffix.
    outcome = "home"
    if bet_type and ":" in bet_type:
        outcome = bet_type.split(":", 1)[1].lower()
    if outcome not in ("home", "away", "draw"):
        outcome = "home"

    # Extract teams from match_id ("home_vs_away_YYYY-MM-DD")
    home, away = "", ""
    _mid_nodate = _re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_id)
    if "_vs_" in _mid_nodate:
        _h_raw, _a_raw = _mid_nodate.split("_vs_", 1)
        home = " ".join(w.capitalize() for w in _h_raw.split("_"))
        away = " ".join(w.capitalize() for w in _a_raw.split("_"))

    outcome_label = home if outcome == "home" else (away if outcome == "away" else "Draw")

    tip_dict = {
        "match_id": match_id,
        "sport": sport,
        "league": league or "",
        "edge_tier": edge_tier,
        "outcome": outcome,
        "outcome_label": outcome_label,
        "odds": float(odds or 0),
        "bookmaker": bookmaker or "",
        "ev": float(ev or 0),
        "predicted_ev": float(ev or 0),
        "composite_score": float(composite_score or 0),
        "confirming_signals": int(confirming or 0),
        "movement": movement or "",
        "home_team": home,
        "away_team": away,
    }
    edge_data = {
        "outcome": outcome,
        "outcome_label": outcome_label,
        "home_team": home,
        "away_team": away,
        "best_odds": float(odds or 0),
        "best_bookmaker": bookmaker or "",
        "edge_pct": float(ev or 0),
        "composite_score": float(composite_score or 0),
        "confirming_signals": int(confirming or 0),
        "movement": movement or "",
        "league": league or "",
    }

    try:
        from narrative_spec import build_narrative_spec, _render_baseline
        spec = build_narrative_spec({}, edge_data, [tip_dict], sport)
        baseline_html = _render_baseline(spec)
    except Exception as exc:
        log.warning("baseline-fallback: spec/render failed for %s: %s", match_id, exc)
        return None

    if not baseline_html or not baseline_html.strip():
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    log.info(
        "AI_BREAKDOWN_BASELINE_FALLBACK match_id=%s tier=%s sport=%s len=%d",
        match_id, edge_tier, sport, len(baseline_html),
    )
    return (
        baseline_html,           # narrative_html
        edge_tier,               # edge_tier
        _json.dumps([tip_dict], default=str),  # tips_json
        "",                      # verdict_html (empty — verdict_tag derived below)
        "",                      # evidence_class
        now_iso,                 # created_at
    )


# FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01 (2026-04-30) — AC-4 (restored from
# reverted b585c69).
#
# Breakdown visibility gate. Paul's directive (verbatim): "rather don't show AI
# breakdown unless there's something worth a monthly subscription behind it
# because breaking our image-only rule and showing this vague, generic crap is
# honestly worse than the alternative."
#
# Show the "🤖 Full AI Breakdown" button ONLY WHEN ALL 5 conditions hold:
#   1. narrative_source IN ('w84','w84-haiku-fallback') — Sonnet / Haiku polish
#      landed, not a W82 baseline.
#   2. status IS NULL OR status NOT IN ('quarantined','deferred') — gate is a
#      strict superset of the existing reader filter (Rule 19 + 20).
#   3. Setup section ≥ 200 chars AND ≥ 3 named entities (team / manager /
#      specific number ending in goals/points/wins/losses/meetings).
#   4. Edge section ≥ 100 chars AND ≥ 1 bookmaker name AND ≥ 1 odds-shape match.
#   5. Risk section ≥ 100 chars AND ≥ 1 specific risk noun from the curated list.
#
# When the gate returns False the bot.py keyboard builder skips the breakdown
# button entirely; the card surface still includes the verdict (which has
# already passed AC-1 closure rule + AC-2 vague-content ban). Card image +
# CTA + "↩️ Back" remain.

# Section quality thresholds — locked from brief AC-4.
_BREAKDOWN_SETUP_MIN_CHARS = 200
_BREAKDOWN_SETUP_MIN_ENTITIES = 3
_BREAKDOWN_EDGE_MIN_CHARS = 100
_BREAKDOWN_RISK_MIN_CHARS = 100

# Polish-quality narrative sources. W82 baseline is intentionally excluded —
# even though synthesis-on-tap can still serve it on read, we don't surface
# the button for it (visibility gate is stricter than read availability).
_BREAKDOWN_POLISH_SOURCES: frozenset[str] = frozenset({
    "w84",
    "w84-haiku-fallback",
})

# Statuses that disqualify a row even when narrative_source is polish-quality.
# Quarantined = post-write integrity check fired; deferred = pregen retry chain
# still in flight (Rule 23 Wave 2 chain).
_BREAKDOWN_DISQUALIFYING_STATUSES: frozenset[str] = frozenset({
    "quarantined",
    "deferred",
})

# SA bookmaker names — case-insensitive substring match against the Edge
# section. Mirrors `config.SA_BOOKMAKERS` short_name keys plus historical
# spellings observed in pregen output.
_BREAKDOWN_BOOKMAKER_NAMES: frozenset[str] = frozenset({
    "betway",
    "hollywoodbets",
    "supabets",
    "sportingbet",
    "gbets",
    "playabets",
    "wsb",
    "10bet",
    "betxchange",
    "world sports betting",
})

# Odds shape — same regex semantics as the validator AC-1 closure rule.
_BREAKDOWN_ODDS_RE = _re.compile(
    r"(?:\b[1-9]\d?\.\d{2}\b|\b\d+/\d+\b|(?:^|\s)[+-]\d{2,4}\b)"
)

# Curated risk-noun list. 30 tokens covering soccer/rugby/cricket/combat/generic.
_BREAKDOWN_RISK_NOUNS: tuple[str, ...] = (
    # Player / squad availability
    "injury", "injuries",
    "rotation", "rotations",
    "fatigue",
    "suspension", "suspensions",
    "rest", "rested", "resting",
    "lineup", "lineups",
    "starting eleven", "starting xi",
    "absence", "absences",
    "travel",
    # Form / fixture
    "away record",
    "derby",
    "cup distraction",
    "fixture congestion",
    "schedule",
    "tournament",
    # Conditions
    "weather", "wind", "rain", "heat",
    "pitch", "surface",
    "altitude",
    "kickoff time", "kick-off time",
    # In-match
    "referee", "ref",
    "var",
    "late goals",
    "set piece", "set-piece",
    "discipline", "red card", "yellow card",
    # Combat / cricket-specific
    "weight cut",
    "toss",
    "conditions",
    # Market / structural
    "line movement", "movement",
    "stale price",
)
_BREAKDOWN_RISK_NOUNS_RE = _re.compile(
    r"\b(?:" + "|".join(
        _re.escape(n) for n in sorted(_BREAKDOWN_RISK_NOUNS, key=len, reverse=True)
    ) + r")\b",
    _re.IGNORECASE,
)

# Named-entity heuristic patterns. Specific numbers ending in points / goals /
# wins / losses / meetings / matches / runs / wickets / KOs / etc.
_BREAKDOWN_NUMERIC_ENTITY_RE = _re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(?:points?|pts|goals?|wins?|losses?|defeats?|draws?|meetings?|"
    r"matches?|games?|tries|tries?|runs?|wickets?|kos?|knockouts?|"
    r"submissions?|finishes?|fights?|bonus\s+points?)"
    r"\b",
    _re.IGNORECASE,
)


def _section_extract_for_quality(narrative_html: str, section_key: str) -> str:
    """Extract a section's prose body (header line stripped) for quality scan.

    Mirrors the section-extraction logic in ``build_ai_breakdown_data`` but
    is exposed for external use. Returns empty string when the section
    marker is absent.
    """
    if not narrative_html:
        return ""
    section_markers = [
        ("setup",   r"📋\s*<b>The Setup</b>"),
        ("edge",    r"🎯\s*<b>The Edge</b>"),
        ("risk",    r"⚠️\s*<b>The Risk</b>"),
        ("verdict", r"🏆\s*<b>Verdict</b>"),
        ("odds",    r"<b>SA Bookmaker Odds:</b>"),
    ]
    positions: list[tuple[str, int]] = []
    for name, pat in section_markers:
        m = _re.search(pat, narrative_html)
        if m:
            positions.append((name, m.start()))
    positions.sort(key=lambda x: x[1])
    start_idx = next((p for n, p in positions if n == section_key), None)
    if start_idx is None:
        return ""
    next_pos = None
    for _name, _pos in positions:
        if _pos > start_idx:
            next_pos = _pos
            break
    section_html = (
        narrative_html[start_idx:next_pos].strip()
        if next_pos else
        narrative_html[start_idx:].strip()
    )
    first_newline = section_html.find("\n")
    if first_newline != -1:
        section_html = section_html[first_newline:].strip()
    else:
        section_html = ""
    return section_html.strip()


def _section_plain_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace for length / scan checks."""
    if not html:
        return ""
    plain = _re.sub(r"<[^>]+>", "", html)
    return _re.sub(r"\s+", " ", plain).strip()


def _count_setup_named_entities(
    setup_text: str,
    home_team: str,
    away_team: str,
    manager_names: tuple[str, ...] = (),
) -> int:
    """Count distinct named entities in the Setup section.

    Counts unique entities (saying a name 3 times still = 1 entity).
    Brief AC-4 threshold is 3.
    """
    if not setup_text:
        return 0
    text_lower = setup_text.lower()
    seen: set[str] = set()

    for raw in (home_team, away_team):
        name = (raw or "").strip().lower()
        if not name:
            continue
        if " " in name:
            if name in text_lower:
                seen.add(f"team:{name}")
        else:
            if _re.search(r"\b" + _re.escape(name) + r"\b", text_lower):
                seen.add(f"team:{name}")

    for mgr in manager_names:
        mgr_clean = (mgr or "").strip().lower()
        if not mgr_clean:
            continue
        if _re.search(r"\b" + _re.escape(mgr_clean) + r"\b", text_lower):
            seen.add(f"mgr:{mgr_clean}")

    for m in _BREAKDOWN_NUMERIC_ENTITY_RE.finditer(setup_text):
        seen.add(f"num:{m.group(0).lower().strip()}")

    return len(seen)


def _check_setup_quality(
    setup_html: str,
    home_team: str,
    away_team: str,
    manager_names: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Return (passed, reason). Reason is empty when passed."""
    plain = _section_plain_text(setup_html)
    if len(plain) < _BREAKDOWN_SETUP_MIN_CHARS:
        return (False, f"setup_len={len(plain)}<{_BREAKDOWN_SETUP_MIN_CHARS}")
    entities = _count_setup_named_entities(
        plain, home_team, away_team, manager_names,
    )
    if entities < _BREAKDOWN_SETUP_MIN_ENTITIES:
        return (
            False,
            f"setup_entities={entities}<{_BREAKDOWN_SETUP_MIN_ENTITIES}",
        )
    return (True, "")


def _check_edge_quality(edge_html: str) -> tuple[bool, str]:
    """Return (passed, reason). Edge ≥ 100 chars + bookmaker + odds shape."""
    plain = _section_plain_text(edge_html)
    if len(plain) < _BREAKDOWN_EDGE_MIN_CHARS:
        return (False, f"edge_len={len(plain)}<{_BREAKDOWN_EDGE_MIN_CHARS}")
    plain_lower = plain.lower()
    has_bookmaker = any(bk in plain_lower for bk in _BREAKDOWN_BOOKMAKER_NAMES)
    if not has_bookmaker:
        return (False, "edge_missing_bookmaker_name")
    if not _BREAKDOWN_ODDS_RE.search(plain):
        return (False, "edge_missing_odds_shape")
    return (True, "")


def _check_risk_quality(risk_html: str) -> tuple[bool, str]:
    """Return (passed, reason). Risk ≥ 100 chars + ≥ 1 specific risk noun."""
    plain = _section_plain_text(risk_html)
    if len(plain) < _BREAKDOWN_RISK_MIN_CHARS:
        return (False, f"risk_len={len(plain)}<{_BREAKDOWN_RISK_MIN_CHARS}")
    if not _BREAKDOWN_RISK_NOUNS_RE.search(plain):
        return (False, "risk_missing_specific_risk_noun")
    return (True, "")


def compute_breakdown_visibility(
    narrative_cache_row: dict | None,
    evidence_pack: dict | None = None,
) -> bool:
    """Return True iff the AI Breakdown button should be visible for this row.

    Parameters
    ----------
    narrative_cache_row
        Dict (or dict-like) with at minimum: ``narrative_html``,
        ``narrative_source``, optional ``status``. Missing any required key
        returns False (defensive).
    evidence_pack
        Optional dict with ``home_team``, ``away_team``, and optional
        ``coaches`` (list/tuple of manager surnames).

    Returns
    -------
    bool
        True when ALL 5 visibility conditions hold; False otherwise.
    """
    if not isinstance(narrative_cache_row, dict):
        return False

    narrative_source = (narrative_cache_row.get("narrative_source") or "").lower()
    if narrative_source not in _BREAKDOWN_POLISH_SOURCES:
        return False

    status = (narrative_cache_row.get("status") or "").lower()
    if status in _BREAKDOWN_DISQUALIFYING_STATUSES:
        return False

    narrative_html = narrative_cache_row.get("narrative_html") or ""
    if not narrative_html.strip():
        return False

    setup_html = _section_extract_for_quality(narrative_html, "setup")
    edge_html = _section_extract_for_quality(narrative_html, "edge")
    risk_html = _section_extract_for_quality(narrative_html, "risk")

    home_team = ""
    away_team = ""
    manager_names: tuple[str, ...] = ()
    if isinstance(evidence_pack, dict):
        home_team = str(evidence_pack.get("home_team") or "").strip()
        away_team = str(evidence_pack.get("away_team") or "").strip()
        coaches = evidence_pack.get("coaches") or ()
        if isinstance(coaches, (list, tuple)):
            manager_names = tuple(str(c).strip() for c in coaches if c)

    setup_ok, _setup_reason = _check_setup_quality(
        setup_html, home_team, away_team, manager_names,
    )
    if not setup_ok:
        return False

    edge_ok, _edge_reason = _check_edge_quality(edge_html)
    if not edge_ok:
        return False

    risk_ok, _risk_reason = _check_risk_quality(risk_html)
    if not risk_ok:
        return False

    return True


def compute_breakdown_visibility_reasons(
    narrative_cache_row: dict | None,
    evidence_pack: dict | None = None,
) -> list[str]:
    """Diagnostic variant — returns an ordered list of failed conditions.

    Empty list ⇔ ``compute_breakdown_visibility`` returns True.
    """
    failures: list[str] = []
    if not isinstance(narrative_cache_row, dict):
        return ["row_not_dict"]

    narrative_source = (narrative_cache_row.get("narrative_source") or "").lower()
    if narrative_source not in _BREAKDOWN_POLISH_SOURCES:
        failures.append(f"narrative_source={narrative_source!r}_not_polish")
    status = (narrative_cache_row.get("status") or "").lower()
    if status in _BREAKDOWN_DISQUALIFYING_STATUSES:
        failures.append(f"status={status!r}_disqualifying")
    narrative_html = narrative_cache_row.get("narrative_html") or ""
    if not narrative_html.strip():
        failures.append("narrative_html_empty")

    if narrative_html.strip():
        setup_html = _section_extract_for_quality(narrative_html, "setup")
        edge_html = _section_extract_for_quality(narrative_html, "edge")
        risk_html = _section_extract_for_quality(narrative_html, "risk")

        home_team = ""
        away_team = ""
        manager_names: tuple[str, ...] = ()
        if isinstance(evidence_pack, dict):
            home_team = str(evidence_pack.get("home_team") or "").strip()
            away_team = str(evidence_pack.get("away_team") or "").strip()
            coaches = evidence_pack.get("coaches") or ()
            if isinstance(coaches, (list, tuple)):
                manager_names = tuple(str(c).strip() for c in coaches if c)

        s_ok, s_reason = _check_setup_quality(
            setup_html, home_team, away_team, manager_names,
        )
        if not s_ok:
            failures.append(s_reason)
        e_ok, e_reason = _check_edge_quality(edge_html)
        if not e_ok:
            failures.append(e_reason)
        r_ok, r_reason = _check_risk_quality(risk_html)
        if not r_ok:
            failures.append(r_reason)
    return failures


def build_ai_breakdown_data(match_id: str) -> dict | None:
    """Build template data for the Full AI Breakdown card.

    Fetches narrative_html from narrative_cache, parses it into 4 sections,
    and extracts edge metadata for the template.

    Parameters
    ----------
    match_id:
        Normalised match identifier: ``home_vs_away_YYYY-MM-DD``.

    Returns
    -------
    dict suitable for ai_breakdown.html template, or None if no data found.
    """
    import os
    from pathlib import Path as _Path
    _BOT_DIR = _Path(__file__).parent
    _SCRAPERS_DIR = _Path(os.environ.get("SCRAPERS_ROOT", str(_BOT_DIR.parent / "scrapers")))
    _ODDS_DB = str(_SCRAPERS_DIR / "odds.db")

    # ── Fetch narrative_cache row ─────────────────────────────────────────────
    try:
        from scrapers.db_connect import connect_odds_db
        conn = connect_odds_db(_ODDS_DB)
    except Exception as exc:
        log.warning("build_ai_breakdown_data: cannot connect to odds.db: %s", exc)
        return None

    row = None
    try:
        # AC-15: exclude quarantined rows; include created_at for AC-12 staleness check.
        # FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01: also exclude rows with empty
        # narrative_html — `verdict-cache` rows write narrative_html='' by construction
        # (bot.py::_store_verdict_cache_sync INSERT path) and would render four blank
        # prose sections through the existing _SECTION_MARKERS regex. The breakdown
        # surface treats these as "no narrative cached" and falls through to the
        # baseline-render path below.
        # Falls back to unfiltered query on older DBs that lack status/quarantined columns.
        try:
            row = conn.execute(
                """SELECT narrative_html, edge_tier, tips_json, verdict_html, evidence_class,
                          created_at
                   FROM narrative_cache
                   WHERE match_id = ?
                     AND (status IS NULL OR status != 'quarantined')
                     AND COALESCE(quarantined, 0) = 0
                     AND narrative_html IS NOT NULL
                     AND LENGTH(TRIM(COALESCE(narrative_html, ''))) > 0""",
                (match_id,),
            ).fetchone()
        except Exception:
            row = conn.execute(
                """SELECT narrative_html, edge_tier, tips_json, verdict_html, evidence_class,
                          created_at
                   FROM narrative_cache
                   WHERE match_id = ?
                     AND narrative_html IS NOT NULL
                     AND LENGTH(TRIM(COALESCE(narrative_html, ''))) > 0""",
                (match_id,),
            ).fetchone()
    except Exception as exc:
        log.warning("build_ai_breakdown_data: query failed: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not row:
        # FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 AC-3: premium defer check.
        # Before falling through to the W82 synthesis-on-tap fallback, check
        # whether a premium-tier defer row exists. If yes, return a deferred
        # sentinel — caller (bot.py::_handle_ai_breakdown) renders the
        # "AI Breakdown updating — refresh in a few minutes" placeholder
        # instead of W82 boilerplate. Premium subscribers must NEVER see
        # synthesis-on-tap content during a live polish-failure window.
        _premium_tier = _check_premium_edge(match_id)
        if _premium_tier:
            _defer = _check_premium_defer(match_id)
            if _defer:
                log.info(
                    "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumDeferred "
                    "match_id=%s tier=%s consecutive=%d — serving placeholder "
                    "(no narrative_cache row, defer in flight)",
                    match_id, _premium_tier, _defer.get("consecutive_count", 1),
                )
                return {
                    "deferred": True,
                    "match_id": match_id,
                    "edge_tier": _premium_tier,
                    "defer_count": _defer.get("consecutive_count", 1),
                    "fixture": _defer.get("fixture", ""),
                }
            # FIX-PREMIUM-POSTWRITE-PROTECTION-01 AC-2: post-write quarantine check.
            # The cache SELECT above already excludes status='quarantined' rows,
            # but the predecessor brief documented (Brentford–West Ham,
            # Brighton–Wolves on 29 Apr) that w84-served premium rows can be
            # quarantined post-commit by serve-time gates without a paired
            # `gold_verdict_failed_edges` defer entry — so the cache-miss path
            # would otherwise fall through to W82 synthesis. That is the W82-
            # boilerplate regression Paul observed on premium cards. Treat any
            # quarantined Gold/Diamond row as an in-flight defer so the user
            # sees the "updating" placeholder rather than tainted W82 content.
            _quarantined = _check_premium_quarantined(match_id)
            if _quarantined:
                log.warning(
                    "FIX-PREMIUM-POSTWRITE-PROTECTION-01 PremiumQuarantined "
                    "match_id=%s tier=%s reason=%s — serving placeholder "
                    "(no narrative_cache row eligible, w84 row quarantined post-write)",
                    match_id,
                    _premium_tier,
                    _quarantined.get("quarantine_reason", ""),
                )
                return {
                    "deferred": True,
                    "match_id": match_id,
                    "edge_tier": _premium_tier,
                    "defer_count": 0,
                    "fixture": "",
                    "quarantine_reason": _quarantined.get("quarantine_reason", ""),
                }
        # FIX-AI-BREAKDOWN-EMPTY-NARRATIVE-FILTER-01: instant-baseline fallback.
        # No eligible cache row + no premium defer → synthesize a row from
        # edge_results + _render_baseline(spec). Zero LLM, zero ESPN — same
        # path used by _generate_narrative_v2(live_tap=True). Returns None
        # only when there is no edge data either (truly unreachable match).
        row = _synthesize_breakdown_row_from_baseline(match_id)
        if not row:
            # FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 AC-3: orphan path.
            # Premium edge exists but neither narrative_cache nor defer row
            # nor synthesizable baseline — pregen gap. Should never fire in
            # steady state. Log ERROR + Sentry breadcrumb so EdgeOps notices.
            if _premium_tier:
                log.error(
                    "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumOrphan "
                    "match_id=%s tier=%s — premium edge has neither cache "
                    "nor defer nor synthesizable baseline (pregen gap)",
                    match_id, _premium_tier,
                )
                try:
                    import sentry_sdk as _orphan_sentry
                    _orphan_sentry.add_breadcrumb(
                        category="ai_breakdown.premium_orphan",
                        level="error",
                        message="FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumOrphan",
                        data={"match_id": match_id, "tier": _premium_tier},
                    )
                except Exception:
                    pass
            return None

    narrative_html = row[0] or ""
    edge_tier = (row[1] or "bronze").lower()
    tips_json_raw = row[2] or "[]"
    verdict_html = row[3] or ""
    evidence_class = row[4] or ""
    created_at_raw = row[5] if row[5] is not None else None

    # ── Parse teams from match_id ─────────────────────────────────────────────
    home, away = "", ""
    _mid_nodate = _re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_id)
    if "_vs_" in _mid_nodate:
        _h_raw, _a_raw = _mid_nodate.split("_vs_", 1)
        home = " ".join(w.capitalize() for w in _h_raw.split("_"))
        away = " ".join(w.capitalize() for w in _a_raw.split("_"))

    # ── Tier label ────────────────────────────────────────────────────────────
    _TIER_LABELS = {
        "diamond": "DIAMOND EDGE",
        "gold": "GOLD EDGE",
        "silver": "SILVER EDGE",
        "bronze": "BRONZE EDGE",
    }
    tier_label = _TIER_LABELS.get(edge_tier, "EDGE")

    # ── Parse tips_json for ev_pct + best bookmaker ──────────────────────────
    ev_pct = 0.0
    best_bookmaker_key = ""
    try:
        tips_list = json.loads(tips_json_raw) if isinstance(tips_json_raw, str) else tips_json_raw
        if tips_list and isinstance(tips_list, list):
            best = max(tips_list, key=lambda t: float(t.get("ev") or 0), default=None)
            if best:
                ev_pct = float(best.get("ev") or 0)
                best_bookmaker_key = str(best.get("bookmaker") or "")
    except Exception:
        pass

    # ── Derive verdict_tag from evidence_class / verdict_html ─────────────────
    ec_lower = (evidence_class or "").lower()
    vh_lower = (verdict_html or "").lower()
    if "strong_back" in ec_lower or "strong back" in vh_lower:
        verdict_tag = "STRONG BACK"
    elif "back" in ec_lower or " back" in vh_lower:
        verdict_tag = "BACK"
    elif "lean" in ec_lower or "lean" in vh_lower:
        verdict_tag = "MILD LEAN"
    elif "speculative" in ec_lower or "speculative" in vh_lower:
        verdict_tag = "SPECULATIVE"
    elif "monitor" in ec_lower or "monitor" in vh_lower:
        verdict_tag = "MONITOR"
    else:
        verdict_tag = "VERDICT"

    # ── Parse narrative_html into 4 sections ──────────────────────────────────
    # Section markers (ordered as they appear in the HTML)
    # Note: title line also starts with 🎯, so anchor Edge section precisely.
    _SECTION_MARKERS = [
        ("setup",   r"📋\s*<b>The Setup</b>"),
        ("edge",    r"🎯\s*<b>The Edge</b>"),
        ("risk",    r"⚠️\s*<b>The Risk</b>"),
        ("verdict", r"🏆\s*<b>Verdict</b>"),
        ("odds",    r"<b>SA Bookmaker Odds:</b>"),
    ]

    # Find positions of each marker in the HTML
    _positions: list[tuple[str, int]] = []
    for _name, _pat in _SECTION_MARKERS:
        _m = _re.search(_pat, narrative_html)
        if _m:
            _positions.append((_name, _m.start()))

    # Sort by position
    _positions.sort(key=lambda x: x[1])

    def _extract_section(section_name: str) -> str:
        """Extract prose content for a given section, stripping the header line."""
        start_idx = next((pos for name, pos in _positions if name == section_name), None)
        if start_idx is None:
            return ""
        # Find the end: beginning of the next section marker
        _next_pos = None
        for _name, _pos in _positions:
            if _pos > start_idx:
                _next_pos = _pos
                break
        section_html = (
            narrative_html[start_idx:_next_pos].strip()
            if _next_pos else
            narrative_html[start_idx:].strip()
        )
        # Strip the first line (section header line)
        _first_newline = section_html.find("\n")
        if _first_newline != -1:
            section_html = section_html[_first_newline:].strip()
        else:
            section_html = ""
        return section_html.strip()

    def _trim_to_last_sentence(text: str, max_chars: int = 200) -> str:
        """Truncate text at the nearest sentence boundary before max_chars."""
        if len(text) <= max_chars:
            return text
        chunk = text[:max_chars]
        last = max(chunk.rfind("."), chunk.rfind("!"), chunk.rfind("?"))
        if last > 0:
            return chunk[:last + 1]
        return chunk

    # AC-3: setup/edge/risk get 200-char sentence-boundary truncation only.
    setup_html = _trim_to_last_sentence(_extract_section("setup"), 200)
    edge_html = _trim_to_last_sentence(_extract_section("edge"), 200)
    risk_html = _trim_to_last_sentence(_extract_section("risk"), 200)

    # AC-13 ordering for verdict:
    # (1) extract, (2) truncate, (3) strip for quality check,
    # (4) quality gate, (5) fallback with AC-11/AC-12 guards.
    verdict_prose_html = _extract_section("verdict")
    verdict_prose_html = _trim_to_last_sentence(verdict_prose_html, 200)

    _stripped_verdict = _re.sub(r"<[^>]+>", "", verdict_prose_html).strip()
    if _stripped_verdict:
        try:
            from narrative_spec import min_verdict_quality as _mvq
            if not _mvq(_stripped_verdict, edge_tier, evidence_pack=None):
                # AC-11: NULL guard — never substitute an empty string.
                if not verdict_html:
                    log.info(
                        "AI_BREAKDOWN_VERDICT_FALLBACK_NULL match_id=%s tier=%s",
                        match_id, edge_tier,
                    )
                    # Retain thin verdict_prose_html as-is (thin > blank).
                else:
                    # AC-12: Staleness guard — suppress if row is stale AND
                    # verdict_html references a live bookmaker name.
                    _suppress_fallback = False
                    if created_at_raw:
                        try:
                            from datetime import timezone
                            _created_dt = datetime.fromisoformat(
                                str(created_at_raw).replace("Z", "+00:00")
                            )
                            if _created_dt.tzinfo is None:
                                _created_dt = _created_dt.replace(tzinfo=timezone.utc)
                            _age_h = (
                                datetime.now(timezone.utc) - _created_dt
                            ).total_seconds() / 3600.0
                            if _age_h > 12:
                                from config import SA_BOOKMAKERS as _SA_BKS
                                _bk_names = {v["short_name"].lower() for v in _SA_BKS.values()}
                                if any(n in verdict_html.lower() for n in _bk_names):
                                    log.info(
                                        "AI_BREAKDOWN_VERDICT_STALE match_id=%s age_hours=%.1f",
                                        match_id, _age_h,
                                    )
                                    _suppress_fallback = True
                        except Exception:
                            pass
                    # AC-13 step 5: substitute verdict_html without re-truncating.
                    if not _suppress_fallback:
                        log.info(
                            "AI_BREAKDOWN_VERDICT_FALLBACK match_id=%s tier=%s "
                            "reason=embedded_failed_quality",
                            match_id, edge_tier,
                        )
                        verdict_prose_html = verdict_html
        except Exception:
            pass

    # FIX-CARD-SURFACE-TIER-CAP-REASON-01: surface league cap reason on AI Breakdown.
    # League is read from edge_results so the helper can detect a structural cap
    # (Super Rugby / Currie Cup → Silver). Empty string for uncapped edges.
    cap_reason = ""
    try:
        from scrapers.db_connect import connect_odds_db as _ck_connect
        _ck_conn = _ck_connect(_ODDS_DB)
        try:
            _ck_row = _ck_conn.execute(
                "SELECT league FROM edge_results WHERE match_key = ? LIMIT 1",
                (match_id,),
            ).fetchone()
        finally:
            try:
                _ck_conn.close()
            except Exception:
                pass
        if _ck_row and _ck_row[0]:
            cap_reason = _resolve_cap_reason(
                {"league_key": str(_ck_row[0])}, edge_tier
            )
    except Exception as _ck_exc:
        log.debug("build_ai_breakdown_data: cap_reason resolve failed: %s", _ck_exc)

    return {
        "home": home,
        "away": away,
        "tier_label": tier_label,
        "ev_pct": ev_pct,
        "verdict_tag": verdict_tag,
        "setup_html": setup_html,
        "edge_html": edge_html,
        "risk_html": risk_html,
        "verdict_prose_html": verdict_prose_html,
        "best_bookmaker_key": best_bookmaker_key,
        "cap_reason": cap_reason,
    }
