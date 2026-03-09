"""W82-SPEC + W82-RENDER: NarrativeSpec — typed editorial specification + baseline renderer.

W82-SPEC: Code decides evidence class, tone band, and verdict constraints BEFORE any text
is written. The LLM may only polish words within these constraints.

W82-RENDER: Deterministic rendering functions that turn a NarrativeSpec into complete
4-section narrative prose. Zero AI, zero API calls, zero external imports.
build_narrative_spec() uses lazy imports from bot.py to avoid Sentry initialisation
in test/scraper environments.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


# ── Tone Band Language Rules ───────────────────────────────────────────────────

TONE_BANDS: dict[str, dict[str, list[str]]] = {
    "cautious": {
        "allowed": [
            "speculative price angle", "long-shot value only",
            "numbers-only play", "thin support", "price is interesting",
            "worth a small punt if you like the price",
            "market may be right here", "tread carefully",
        ],
        "banned": [
            "market has this wrong", "market completely wrong",
            "strong edge", "must back", "lock it in", "slam dunk",
            "huge value", "no-brainer", "confident", "clear edge",
            "obvious value", "one of the best plays",
        ],
    },
    "moderate": {
        "allowed": [
            "mild lean", "slight edge", "numbers suggest",
            "worth considering", "some value here",
        ],
        "banned": [
            "market has this completely wrong", "slam dunk", "lock",
            "huge edge", "no-brainer", "one of the best plays",
        ],
    },
    "confident": {
        "allowed": [
            "genuine value", "supported edge", "solid play",
            "numbers and indicators agree", "worth backing",
        ],
        "banned": [
            "slam dunk", "lock", "no-brainer", "guaranteed",
        ],
    },
    "strong": {
        "allowed": [
            "market mispriced", "strong conviction", "premium value",
            "one of the best plays on the card",
        ],
        "banned": [
            "guaranteed", "lock", "no-brainer", "can't lose",
        ],
    },
}


# ── NarrativeSpec Dataclass ───────────────────────────────────────────────────

@dataclass
class NarrativeSpec:
    """Typed editorial specification. Code decides everything here.
    The LLM may only polish words within these constraints."""

    # Identity
    home_name: str
    away_name: str
    competition: str              # "Premier League", "Champions League", etc.
    sport: str                    # "soccer", "rugby", "cricket"

    # Setup context
    home_story_type: str          # from _decide_team_story()
    away_story_type: str
    home_coach: str | None = None
    away_coach: str | None = None
    home_position: int | None = None
    away_position: int | None = None
    home_points: int | None = None
    away_points: int | None = None
    home_form: str = ""           # "WWDLD"
    away_form: str = ""
    home_record: str = ""         # "W9 D3 L2"
    away_record: str = ""
    home_gpg: float | None = None
    away_gpg: float | None = None
    home_last_result: str = ""    # "beating Everton 2-0 at home"
    away_last_result: str = ""
    h2h_summary: str = ""
    injuries_home: list[str] = field(default_factory=list)
    injuries_away: list[str] = field(default_factory=list)

    # Edge thesis (code-decided)
    outcome: str = ""             # "draw", "home", "away"
    outcome_label: str = ""       # "the draw", "Aston Villa away win"
    bookmaker: str = ""           # "SuperSportBet"
    odds: float = 0.0
    ev_pct: float = 0.0
    fair_prob_pct: float = 0.0
    composite_score: float = 0.0

    # Evidence classification (THE KEY INNOVATION)
    support_level: int = 0                # 0-7 confirming signals
    evidence_class: str = "speculative"   # speculative / lean / supported / conviction
    tone_band: str = "cautious"           # cautious / moderate / confident / strong

    # Risk (code-decided)
    risk_factors: list[str] = field(default_factory=list)
    risk_severity: str = "moderate"       # low / moderate / high

    # Verdict (code-decided — capped by tone band)
    verdict_action: str = ""      # "speculative punt" / "lean" / "back" / "strong back"
    verdict_sizing: str = ""      # "tiny exposure or pass" / "small stake" / "standard stake" / "confident stake"

    # Stale/movement context
    stale_minutes: int = 0
    movement_direction: str = "neutral"   # "for" / "against" / "neutral"
    tipster_against: int = 0

    # Raw scaffold (for LLM grounding in Stage 3)
    scaffold: str = ""


# ── Evidence Classification ────────────────────────────────────────────────────

def _classify_evidence(edge_data: dict) -> tuple[str, str, str, str]:
    """Returns (evidence_class, tone_band, verdict_action, verdict_sizing).

    This is the SINGLE MOST IMPORTANT function in the narrative engine.
    It prevents contradictions architecturally — a card with 0 indicators
    can NEVER sound confident because the tone band doesn't allow it.
    """
    support = edge_data.get("confirming_signals", 0)
    ev = edge_data.get("edge_pct", 0)
    composite = edge_data.get("composite_score", 0)
    stale = edge_data.get("stale_minutes", 0)
    movement = edge_data.get("movement_direction", "neutral")

    # Penalties degrade effective support
    stale_penalty = 1 if stale >= 360 else 0      # 6+ hours stale
    movement_penalty = 1 if movement == "against" else 0
    effective = max(0, support - stale_penalty - movement_penalty)

    if effective == 0:
        return ("speculative", "cautious",
                "speculative punt", "tiny exposure or pass")
    elif effective == 1:
        return ("lean", "moderate",
                "lean", "small stake")
    elif effective <= 3:
        return ("supported", "confident",
                "back", "standard stake")
    else:  # 4+
        if composite >= 60 and ev >= 5:
            return ("conviction", "strong",
                    "strong back", "confident stake")
        return ("supported", "confident",
                "back", "standard stake")


# ── Contradiction Guards ───────────────────────────────────────────────────────

def _check_coherence(spec: NarrativeSpec) -> list[str]:
    """Catch contradictions BEFORE any text is rendered.
    If violations found, downgrade tone_band before proceeding."""
    violations = []

    if spec.support_level == 0 and spec.tone_band in ("confident", "strong"):
        violations.append("0 indicators but confident/strong tone")

    if spec.support_level <= 1 and spec.verdict_action in ("back", "strong back"):
        violations.append("≤1 indicator but back/strong back verdict")

    if spec.risk_severity == "high" and spec.verdict_action == "strong back":
        violations.append("high risk but strong back verdict")

    if spec.evidence_class == "speculative" and spec.verdict_action != "speculative punt":
        violations.append("speculative evidence but non-speculative verdict")

    if spec.stale_minutes >= 720 and spec.tone_band != "cautious":
        violations.append("12+ hour stale pricing but not cautious tone")

    if spec.tipster_against >= 2 and spec.tone_band == "strong":
        violations.append("2+ tipsters against but strong tone")

    return violations


def _enforce_coherence(spec: NarrativeSpec) -> NarrativeSpec:
    """Downgrade spec until coherent. Mutates and returns spec."""
    violations = _check_coherence(spec)
    while violations:
        # Downgrade one level
        if spec.tone_band == "strong":
            spec.tone_band = "confident"
            spec.evidence_class = "supported"
            spec.verdict_action = "back"
            spec.verdict_sizing = "standard stake"
        elif spec.tone_band == "confident":
            spec.tone_band = "moderate"
            spec.evidence_class = "lean"
            spec.verdict_action = "lean"
            spec.verdict_sizing = "small stake"
        elif spec.tone_band == "moderate":
            spec.tone_band = "cautious"
            spec.evidence_class = "speculative"
            spec.verdict_action = "speculative punt"
            spec.verdict_sizing = "tiny exposure or pass"
        else:
            break  # Already at floor
        violations = _check_coherence(spec)
    return spec


# ── Risk Helpers ───────────────────────────────────────────────────────────────

def _build_risk_factors(
    edge_data: dict,
    ctx_data: dict | None,
    sport: str,
) -> list[str]:
    """Build code-decided risk factor list from edge signals."""
    factors = []
    stale = edge_data.get("stale_minutes", 0)
    confirming = edge_data.get("confirming_signals", 0)
    movement = edge_data.get("movement_direction", "neutral")
    tipster_against = edge_data.get("tipster_against", 0)
    outcome = edge_data.get("outcome", "")

    if stale >= 360:
        factors.append(f"Stale price — hasn't updated in {stale // 60}h, could shift before kickoff.")
    if confirming == 0:
        factors.append("Zero confirming indicators — pure price edge with no supporting data.")
    if movement == "against":
        factors.append("Market drifting away from this outcome — sharp money may disagree.")
    if tipster_against >= 2:
        factors.append(f"{tipster_against} tipster sources lean the other way.")
    if outcome == "away" and confirming < 3:
        factors.append("Away side faces home crowd disadvantage — factor that in.")
    if not factors:
        factors.append("Standard match variance applies.")
    return factors


def _assess_risk_severity(risk_factors: list[str], edge_data: dict) -> str:
    """Return 'low', 'moderate', or 'high' based on risk profile."""
    stale = edge_data.get("stale_minutes", 0)
    movement = edge_data.get("movement_direction", "neutral")
    tipster_against = edge_data.get("tipster_against", 0)
    confirming = edge_data.get("confirming_signals", 0)

    if (
        stale >= 720
        or (movement == "against" and tipster_against >= 2)
        or (confirming == 0 and movement == "against")
    ):
        return "high"
    if (
        confirming >= 4
        and movement != "against"
        and stale < 120
        and tipster_against == 0
    ):
        return "low"
    return "moderate"


# ── Label Helpers ──────────────────────────────────────────────────────────────

_LEAGUE_DISPLAY: dict[str, str] = {
    # Soccer
    "psl": "Premiership (PSL)",
    "epl": "Premier League",
    "champions_league": "Champions League",
    "ucl": "Champions League",
    "la_liga": "La Liga",
    "bundesliga": "Bundesliga",
    "serie_a": "Serie A",
    "ligue_1": "Ligue 1",
    "mls": "MLS",
    # Rugby
    "urc": "United Rugby Championship",
    "super_rugby": "Super Rugby Pacific",
    "six_nations": "Six Nations",
    "currie_cup": "Currie Cup",
    "international_rugby": "International Rugby",
    "rugby_champ": "Rugby Championship",
    # Cricket
    "t20_world_cup": "T20 World Cup",
    "sa20": "SA20",
    "ipl": "IPL",
    "big_bash": "Big Bash League",
    "test_cricket": "Test Series",
    "odis": "ODI Series",
    "t20i": "T20I Series",
    # Combat
    "ufc": "UFC",
    "boxing": "Boxing",
    "boxing_major": "Boxing",
}


def _humanise_league(league_key: str) -> str:
    """Convert league key to user-friendly display name."""
    return _LEAGUE_DISPLAY.get(league_key, league_key.replace("_", " ").title())


def _build_outcome_label(
    edge_data: dict, home_name: str, away_name: str
) -> str:
    """Convert outcome key to human-readable label."""
    outcome = edge_data.get("outcome", "")
    if outcome == "home":
        return f"{home_name} win"
    if outcome == "away":
        return f"{away_name} win"
    if outcome == "draw":
        return "the draw"
    return outcome


def _build_h2h_summary(ctx_data: dict | None) -> str:
    """Build concise H2H summary from ctx_data head_to_head list."""
    if not ctx_data:
        return ""
    h2h = ctx_data.get("head_to_head", [])
    if not h2h:
        return ""
    home_wins = sum(1 for m in h2h if m.get("home_score", 0) > m.get("away_score", 0))
    away_wins = sum(1 for m in h2h if m.get("away_score", 0) > m.get("home_score", 0))
    draws = len(h2h) - home_wins - away_wins
    return f"{len(h2h)} meetings: {home_wins}W {draws}D {away_wins}L"


# ── Main Builder ───────────────────────────────────────────────────────────────

def build_narrative_spec(
    ctx_data: dict,
    edge_data: dict,
    tips: list,
    sport: str,
) -> NarrativeSpec:
    """Assemble NarrativeSpec from all available data.
    Reuses _decide_team_story() from W81-SCAFFOLD.

    Lazy imports from bot.py avoid Sentry initialisation in test/scraper environments.
    """
    # Lazy imports — only triggered when this function is called, not at module import
    from bot import (  # type: ignore[import]
        _decide_team_story,
        _build_verified_scaffold,
        _scaffold_last_result,
        _parse_record,
        get_verified_injuries,
    )

    home = ctx_data.get("home_team", {}) if isinstance(ctx_data.get("home_team"), dict) else {}
    away = ctx_data.get("away_team", {}) if isinstance(ctx_data.get("away_team"), dict) else {}

    home_name = home.get("name", edge_data.get("home_team", "Home"))
    away_name = away.get("name", edge_data.get("away_team", "Away"))

    # Evidence classification
    ev_class, tone, verdict_action, verdict_sizing = _classify_evidence(edge_data)

    # Risk factors (code-decided)
    risk_factors = _build_risk_factors(edge_data, ctx_data, sport)
    risk_severity = _assess_risk_severity(risk_factors, edge_data)

    # Parse home/away records for _decide_team_story
    home_rec = _parse_record(home.get("home_record", ""))
    away_rec = _parse_record(away.get("away_record", ""))

    # Build scaffold (reuse W81-SCAFFOLD)
    scaffold = _build_verified_scaffold(ctx_data, edge_data, sport)

    # Verified injuries
    injuries = get_verified_injuries(home_name, away_name)

    # Fair probability — edge_v2 uses "fair_probability", pregen uses "fair_prob"
    fair_prob_raw = edge_data.get("fair_prob") or edge_data.get("fair_probability", 0)

    spec = NarrativeSpec(
        home_name=home_name,
        away_name=away_name,
        competition=_humanise_league(edge_data.get("league", "")),
        sport=sport,
        home_story_type=_decide_team_story(
            home.get("position"), home.get("points"), home.get("form", ""),
            home_rec, None, home.get("goals_per_game"), is_home=True,
        ),
        away_story_type=_decide_team_story(
            away.get("position"), away.get("points"), away.get("form", ""),
            None, away_rec, away.get("goals_per_game"), is_home=False,
        ),
        home_coach=home.get("coach"),
        away_coach=away.get("coach"),
        home_position=home.get("position"),
        away_position=away.get("position"),
        home_points=home.get("points"),
        away_points=away.get("points"),
        home_form=home.get("form", ""),
        away_form=away.get("form", ""),
        home_last_result=_scaffold_last_result(home),
        away_last_result=_scaffold_last_result(away),
        h2h_summary=_build_h2h_summary(ctx_data),
        injuries_home=injuries.get("home", []),
        injuries_away=injuries.get("away", []),
        outcome=edge_data.get("outcome", ""),
        outcome_label=_build_outcome_label(edge_data, home_name, away_name),
        bookmaker=edge_data.get("best_bookmaker", ""),
        odds=edge_data.get("best_odds", 0),
        ev_pct=edge_data.get("edge_pct", 0),
        fair_prob_pct=round(float(fair_prob_raw) * 100, 1) if fair_prob_raw else 0.0,
        composite_score=edge_data.get("composite_score", 0),
        support_level=edge_data.get("confirming_signals", 0),
        evidence_class=ev_class,
        tone_band=tone,
        risk_factors=risk_factors,
        risk_severity=risk_severity,
        verdict_action=verdict_action,
        verdict_sizing=verdict_sizing,
        stale_minutes=edge_data.get("stale_minutes", 0),
        movement_direction=edge_data.get("movement_direction", "neutral"),
        tipster_against=edge_data.get("tipster_against", 0),
        scaffold=scaffold,
    )

    # Enforce coherence — downgrade if contradictions found
    spec = _enforce_coherence(spec)

    return spec


# ── Rendering Engine (W82-RENDER) ─────────────────────────────────────────────
# Pure Python — no bot imports, no LLM calls, no external I/O.
# All functions are deterministic: same NarrativeSpec = same output.

def _ordinal_r(n: int) -> str:
    """Return ordinal string: 1 → '1st', 2 → '2nd', 11 → '11th'."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _pick(seed: str, n: int) -> int:
    """MD5-deterministic 0..n-1 index. Same team name = same template every time."""
    return int(hashlib.md5(seed.encode()).hexdigest(), 16) % n


def _coach_possessive(coach: str | None) -> str:
    """Return 'Smith's' or 'the manager's' when coach is unknown."""
    if not coach:
        return "the manager's"
    last = coach.split()[-1]
    return f"{last}'" if last.endswith("s") else f"{last}'s"


def _pos_phrase(pos: int | None) -> str:
    """Return ordinal position or 'mid-table' if unknown."""
    return _ordinal_r(pos) if pos is not None else "mid-table"


def _form_br(form: str, games: int = 5) -> str:
    """Return 'W-W-D-L-W' from form string. Empty string if no data."""
    if not form:
        return ""
    return "-".join(form[:games])


def _last_sent(name: str, last_result: str) -> str:
    """Return '<name> came in <last_result>.' or '' if no data."""
    if not last_result:
        return ""
    return f"{name} came in {last_result}."


def _injuries_sent(injuries: list[str]) -> str:
    """Return 'Key absence: X.' or 'Missing: X, Y, Z.' or '' if none."""
    if not injuries:
        return ""
    if len(injuries) == 1:
        return f"Key absence: {injuries[0]}."
    return f"Missing: {', '.join(injuries[:3])}."


def _parse_wdl(record: str) -> tuple[int, int, int]:
    """Parse 'W9 D3 L2' → (9, 3, 2). Returns (0, 0, 0) on failure."""
    m = re.search(r"W(\d+)\s+D(\d+)\s+L(\d+)", record)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (0, 0, 0)


def _h2h_bridge(h2h: str, home: str, away: str) -> str:
    """Return formatted H2H sentence or '' if no data."""
    if not h2h:
        return ""
    return f"Head to head: {h2h}."


def _sentence_case(text: str) -> str:
    """Capitalise first character only — preserves proper nouns in the rest."""
    if not text:
        return text
    return text[0].upper() + text[1:]


# ── Story-type template functions (10 types × 3 variants) ─────────────────────
# Each function takes (v, name, coach, pos, pts, form, record, gpg, last_result,
#                      injuries, comp, sport, is_home) → str
# v is the variant index (0/1/2), selected deterministically by _pick().

def _tmpl_title_push(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    pts_str = f" on {pts} points" if pts else ""
    if v == 0:
        parts = [f"{name} are {ord_pos} in {comp}{pts_str}, building a genuine title case."]
        if f:
            parts.append(f"Form reads {f} — they're not letting up.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"It's been a title-calibre campaign from {poss} side — {ord_pos}{pts_str}."]
        if f:
            parts.append(f"A {f} run backs up the league table position.")
        if gpg and gpg > 1.5:
            parts.append(f"Averaging {gpg:.1f} goals per game.")
        if last:
            parts.append(last)
    else:
        parts = [f"{name} lead the way in {comp}{pts_str} — {ord_pos} and looking the real deal."]
        if f:
            parts.append(f"Recent form: {f}.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_fortress(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    w, d, l = _parse_wdl(record)
    poss = _coach_possessive(coach)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    if v == 0:
        hw_str = f" ({w}W {d}D {l}L at home)" if w + d + l > 0 else ""
        parts = [f"{name}'s home record tells its own story{hw_str} — opponents don't enjoy coming here."]
        if f:
            parts.append(f"Current form: {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"{poss} side have turned their ground into a fortress this season."]
        if w > 0:
            parts.append(f"{w} home wins show a unit that's hard to break down on their own patch.")
        if f:
            parts.append(f"Form: {f}.")
    else:
        parts = [f"Home advantage is real for {name} — opponents come here knowing what's in store."]
        if f:
            parts.append(f"Recent form: {f}.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_crisis(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    pts_str = f" on {pts} points" if pts else ""
    if v == 0:
        parts = [f"{name} are in trouble — {ord_pos} in {comp}{pts_str} and the pressure is mounting."]
        if f:
            parts.append(f"Form reads {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"{poss} side sit {ord_pos}{pts_str} in the table and it's not pretty."]
        if f:
            parts.append(f"A {f} run sums up where they are right now.")
        if last:
            parts.append(last)
    else:
        parts = [f"It's been a difficult stretch for {name} — {ord_pos} in {comp}{pts_str}."]
        if f:
            parts.append(f"Form: {f}.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_recovery(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    if v == 0:
        parts = [f"{name} look to be finding their feet again — {ord_pos} after a testing run."]
        if last:
            parts.append(last)
        if f:
            parts.append(f"Form: {f}.")
    elif v == 1:
        parts = [f"There are signs of life from {poss} side after a difficult spell — {ord_pos} and trending up."]
        if f:
            parts.append(f"Recent form {f} shows the bounce-back is real.")
        if last:
            parts.append(last)
    else:
        parts = [f"{name} are on the move — bouncing back from their rough patch, now sitting {ord_pos}."]
        if f:
            parts.append(f"Form reads {f}.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_momentum(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    if v == 0:
        parts = [f"{name} are in form right now — {ord_pos} and carrying genuine momentum."]
        if f:
            parts.append(f"Form: {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"Hard to ignore the form of {poss} side — {ord_pos} and on a roll."]
        if f:
            parts.append(f"A {f} sequence has given them real confidence.")
        if gpg and gpg > 1.5:
            parts.append(f"Scoring at {gpg:.1f} per game right now.")
    else:
        parts = [f"{name} have hit their stride — {ord_pos} and not looking like stopping."]
        if f:
            parts.append(f"Form reads {f}.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_inconsistent(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    if v == 0:
        parts = [f"{name} are difficult to read — {ord_pos} but blowing hot and cold this season."]
        if f:
            parts.append(f"Form {f} captures the inconsistency.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"You never quite know which version of {name} will show up — {ord_pos} but capable of anything."]
        if f:
            parts.append(f"Form reads {f} — make of that what you will.")
    else:
        parts = [f"{poss} side have been unpredictable — {ord_pos} in {comp} and the form shows why."]
        if f:
            parts.append(f"A {f} sequence reflects a team you can't pin down.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_draw_merchants(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    w, d, l = _parse_wdl(record)
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    d_str = f" ({d} draws this season)" if d > 0 else ""
    if v == 0:
        parts = [f"{name} are built for attrition — {ord_pos} in {comp} with a draw-heavy profile{d_str}."]
        if f:
            parts.append(f"Form: {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        d_ref = f"{d} draws" if d > 0 else "frequent draws"
        parts = [f"Close contests are {poss} signature — {d_ref} this season tells you {name} rarely get blown away."]
        if f:
            parts.append(f"Form reads {f}.")
    else:
        parts = [f"{name} grind results — {ord_pos}, hard to beat, hard to back with confidence."]
        if gpg is not None and gpg < 1.5:
            parts.append(f"Averaging only {gpg:.1f} goals per game.")
        if f:
            parts.append(f"Form: {f}.")
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_setback(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    if v == 0:
        parts = [f"{name} suffered a recent blip — {ord_pos} in {comp} but still in the mix."]
        if f:
            parts.append(f"Form: {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"A bump in the road for {poss} side — {ord_pos} after dropping points recently."]
        if f:
            parts.append(f"Form reads {f} — one bad result doesn't define the season.")
        if last:
            parts.append(last)
    else:
        parts = [f"{name} are a side capable of better than their recent result suggests — {ord_pos} in {comp}."]
        if f:
            parts.append(f"Form: {f}.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_anonymous(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    poss = _coach_possessive(coach)
    ord_pos = _pos_phrase(pos)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    pts_str = f" on {pts} points" if pts else ""
    if v == 0:
        parts = [f"{name} sit {ord_pos} in {comp}{pts_str} — steady mid-table with no strong narrative either way."]
        if f:
            parts.append(f"Form reads {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"There's not much to shout about with {name} right now — {ord_pos}{pts_str} and quietly ticking along."]
        if f:
            parts.append(f"Form: {f}.")
    else:
        parts = [f"{poss} side sit {ord_pos} in {comp} — mid-table with no title ambitions or relegation worries."]
        if f:
            parts.append(f"Form reads {f}.")
        if last:
            parts.append(last)
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


def _tmpl_neutral(
    v: int, name: str, coach: str | None, pos: int | None, pts: int | None,
    form: str, record: str, gpg: float | None, last_result: str,
    injuries: list[str], comp: str, sport: str, is_home: bool,
) -> str:
    f = _form_br(form)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    if v == 0:
        parts = [f"{name} come into this {'at home' if is_home else 'on the road'}."]
        if f:
            parts.append(f"Form reads {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"{'Home side' if is_home else 'Visitors'} {name} line up with limited context available."]
        if f:
            parts.append(f"Form: {f}.")
    else:
        parts = [f"{name} enter this fixture — the numbers speak louder than any pre-match narrative."]
        if f:
            parts.append(f"Form reads {f}.")
    if inj:
        parts.append(inj)
    return " ".join(p for p in parts if p)


# ── Templates dispatch table ───────────────────────────────────────────────────

def _mk_variants(fn: object) -> list:
    """Create 3 variant lambdas for a template function, avoiding closure issues."""
    return [
        (lambda f, v: lambda *a: f(v, *a))(fn, 0),
        (lambda f, v: lambda *a: f(v, *a))(fn, 1),
        (lambda f, v: lambda *a: f(v, *a))(fn, 2),
    ]


_TEAM_TEMPLATES: dict[str, list] = {
    "title_push":     _mk_variants(_tmpl_title_push),
    "fortress":       _mk_variants(_tmpl_fortress),
    "crisis":         _mk_variants(_tmpl_crisis),
    "recovery":       _mk_variants(_tmpl_recovery),
    "momentum":       _mk_variants(_tmpl_momentum),
    "inconsistent":   _mk_variants(_tmpl_inconsistent),
    "draw_merchants": _mk_variants(_tmpl_draw_merchants),
    "setback":        _mk_variants(_tmpl_setback),
    "anonymous":      _mk_variants(_tmpl_anonymous),
    "neutral":        _mk_variants(_tmpl_neutral),
}


# ── Render Functions ───────────────────────────────────────────────────────────

def _render_team_para(
    name: str,
    coach: str | None,
    story_type: str,
    position: int | None,
    points: int | None,
    form: str,
    record: str,
    gpg: float | None,
    last_result: str,
    injuries: list[str],
    competition: str,
    sport: str,
    is_home: bool,
) -> str:
    """Select and render a team paragraph based on story type.
    Template selection is MD5-deterministic: same team always gets same variant.
    Falls back to 'neutral' for unknown story types.
    """
    variants = _TEAM_TEMPLATES.get(story_type, _TEAM_TEMPLATES["neutral"])
    idx = _pick(name, len(variants))
    fn = variants[idx]
    return fn(name, coach, position, points, form, record, gpg, last_result,
              injuries, competition, sport, is_home)


def _render_setup(spec: NarrativeSpec) -> str:
    """4-8 sentence Setup section from verified NarrativeSpec data.
    OEI pattern: home paragraph → away paragraph → H2H bridge.
    """
    home_para = _render_team_para(
        spec.home_name, spec.home_coach, spec.home_story_type,
        spec.home_position, spec.home_points, spec.home_form,
        spec.home_record, spec.home_gpg, spec.home_last_result,
        spec.injuries_home, spec.competition, spec.sport, is_home=True,
    )
    away_para = _render_team_para(
        spec.away_name, spec.away_coach, spec.away_story_type,
        spec.away_position, spec.away_points, spec.away_form,
        spec.away_record, spec.away_gpg, spec.away_last_result,
        spec.injuries_away, spec.competition, spec.sport, is_home=False,
    )
    h2h = _h2h_bridge(spec.h2h_summary, spec.home_name, spec.away_name)
    parts = [p for p in [home_para, away_para, h2h] if p]
    return "\n".join(parts)


def _render_edge(spec: NarrativeSpec) -> str:
    """Edge thesis calibrated to evidence_class. All phrases respect tone_band."""
    bk = spec.bookmaker or "the market"
    odds_str = f"{spec.odds:.2f}" if spec.odds else "?"
    ev_str = f"+{spec.ev_pct:.1f}%" if spec.ev_pct > 0 else f"{spec.ev_pct:.1f}%"
    fp_str = f"{spec.fair_prob_pct:.0f}%" if spec.fair_prob_pct else "?"
    outcome = spec.outcome_label or "this outcome"

    if spec.evidence_class == "speculative":
        return (
            f"This is a numbers-only play. The price is interesting; the conviction isn't there yet. "
            f"Fair probability at {fp_str}, available at {odds_str} with {bk} ({ev_str} edge). "
            f"Thin support — the market may be right here."
        )
    elif spec.evidence_class == "lean":
        return (
            f"Numbers suggest some value on {outcome}. "
            f"Fair probability at {fp_str} vs the {odds_str} on offer at {bk} ({ev_str}). "
            f"Worth considering at this price, though conviction is limited."
        )
    elif spec.evidence_class == "supported":
        return (
            f"Solid play — indicators agree on {outcome}. "
            f"Fair probability at {fp_str} vs {odds_str} at {bk} ({ev_str}). "
            f"Numbers and available indicators support this angle. Genuine value at current odds."
        )
    else:  # conviction
        return (
            f"One of the stronger plays on today's card. "
            f"Multiple signals align behind {outcome} at {odds_str} with {bk} ({ev_str}). "
            f"Fair probability at {fp_str} — strong conviction here, market looks mispriced."
        )


def _render_risk(spec: NarrativeSpec) -> str:
    """Risk section from code-decided risk factors plus a sizing caveat."""
    factors_text = " ".join(spec.risk_factors)
    sizing = spec.verdict_sizing or "size accordingly"
    severity_note = {
        "high": "High-risk profile — size down significantly or pass entirely.",
        "moderate": f"Stake accordingly: {sizing}.",
        "low": f"Risk profile is clean here. {_sentence_case(sizing)} is appropriate.",
    }.get(spec.risk_severity, f"Stake accordingly: {sizing}.")
    return f"{factors_text} {severity_note}".strip()


def _render_verdict(spec: NarrativeSpec) -> str:
    """Verdict capped by tone_band. Never uses phrases banned by tone_band."""
    outcome = spec.outcome_label or "this outcome"
    odds_str = f"{spec.odds:.2f}" if spec.odds else "?"
    bk = spec.bookmaker or "the market"
    action = spec.verdict_action
    sizing = spec.verdict_sizing

    if action == "speculative punt":
        return (
            f"Speculative punt only — worth a small punt if you like the price. "
            f"{_sentence_case(outcome)} at {odds_str} with {bk}. "
            f"Sizing: {sizing}."
        )
    elif action == "lean":
        return (
            f"Mild lean on {outcome} at {odds_str} ({bk}). "
            f"Numbers suggest some value; back cautiously. "
            f"Sizing: {sizing}."
        )
    elif action == "back":
        return (
            f"Back {outcome} at {odds_str} with {bk}. "
            f"Numbers and indicators agree — worth backing at this price. "
            f"Sizing: {sizing}."
        )
    else:  # strong back
        return (
            f"Strong back on {outcome} at {odds_str} ({bk}). "
            f"Premium value — one of the best plays on the card. "
            f"Sizing: {sizing}."
        )


def _render_baseline(spec: NarrativeSpec) -> str:
    """Assemble all 4 sections into the full baseline narrative with emoji headers."""
    setup = _render_setup(spec)
    edge = _render_edge(spec)
    risk = _render_risk(spec)
    verdict = _render_verdict(spec)
    return (
        f"📋 The Setup\n{setup}\n\n"
        f"🎯 The Edge\n{edge}\n\n"
        f"⚠️ The Risk\n{risk}\n\n"
        f"🏆 Verdict\n{verdict}"
    )
