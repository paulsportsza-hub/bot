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
            "monitor the line", "monitor for line movement",
            "market may be right here",
        ],
        "banned": [
            "market has this wrong", "market completely wrong",
            "strong edge", "must back", "lock it in", "slam dunk",
            "huge value", "no-brainer", "confident", "clear edge",
            "obvious value", "one of the best plays",
            "numbers-only play", "thin support", "price is interesting",
            "the numbers alone", "limited pre-match context",
            "pure price edge with no supporting data",
            "supporting evidence is thin", "signals are absent",
            "no signal backing", "signals don't confirm",
            "pricing edge without supporting signals",
            "the numbers speak louder",
            "pure pricing call", "tread carefully",
            "conviction is limited",
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

    # W84-Q13: Zero or negative EV — no actionable edge, always pass
    # Gate only fires when edge_pct is explicitly provided and <= 0
    if "edge_pct" in edge_data and ev <= 0:
        return ("speculative", "cautious", "pass", "pass")

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
        _seed = edge_data.get("home_team", "") + edge_data.get("away_team", "")
        _v = _pick(_seed, 3)
        _zero_confirm = [
            # 0 — What model-only risk actually means
            "No form, movement, or tipster consensus backs this up. The model's probability estimate works from the typical baseline for this fixture type — not from any current team intelligence.",
            # 1 — What can and cannot be verified
            "No confirming signals from any source. What the model can verify is the price gap itself; what it cannot verify is whether that gap reflects a real probability error or deliberate bookmaker positioning.",
            # 2 — Specific about the uncertainty source
            "No current form, market movement, or tipster data validates the edge. The model identifies a pricing discrepancy based on the available pricing data — not on what either team is doing right now.",
        ]
        factors.append(_zero_confirm[_v])
    if movement == "against":
        factors.append("Market drifting away from this outcome — sharp money may disagree.")
    if tipster_against >= 2:
        factors.append(f"{tipster_against} tipster sources lean the other way.")
    if outcome == "away" and confirming < 3:
        factors.append("Away side faces home crowd disadvantage — factor that in.")
    if not factors:
        # W84-Q9: Replace clinical "Standard match variance applies." with 3 human variants
        _seed = edge_data.get("home_team", "") + edge_data.get("away_team", "")
        _v = _pick(_seed, 3)
        _default_factors = [
            "No specific flags on this one — clean risk profile, size normally.",
            "Nothing obvious stands against this. The usual match-day variables apply.",
            "Price and signals are aligned. Typical match uncertainty is the main remaining variable.",
        ]
        factors.append(_default_factors[_v])
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

    # W83-OVERNIGHT-FIX: guard against ctx_data=None (instant baseline path)
    ctx_data = ctx_data or {}

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
    # Back-calculate from EV + odds when direct probability is unavailable.
    # Derived from definition: EV = fair_prob * odds - 1
    # → fair_prob = (1 + ev_pct/100) / odds
    if not fair_prob_raw:
        _ev = edge_data.get("edge_pct", 0)
        _odds = edge_data.get("best_odds", 0)
        if _ev and _odds > 0:
            fair_prob_raw = (1 + _ev / 100.0) / _odds

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


def _plural(word: str) -> str:
    """Return the plural form of a fixture-type word."""
    _irregulars = {"clash": "clashes", "match": "matches"}
    return _irregulars.get(word, word + "s")


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
            parts.append(f"Current form ({f}) backs that up.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"{poss} side have turned their ground into a fortress this season."]
        if w > 0:
            parts.append(f"{w} home wins show a unit that's hard to break down on their own patch.")
        if f:
            parts.append(f"Form ({f}) confirms the trend.")
    else:
        parts = [f"Home advantage is real for {name} — opponents come here knowing what's in store."]
        if f:
            parts.append(f"Form ({f}) underlines the advantage.")
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
            parts.append(f"Form ({f}) reflects the pressure.")
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
            parts.append(f"Form ({f}) shows the bounce-back beginning.")
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
            parts.append(f"Form ({f}) says it all.")
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
            parts.append(f"Form ({f}) captures their approach.")
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
            parts.append(f"Form ({f}) tells the story.")
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
            parts.append(f"Form ({f}) shows the blip, but no panic yet.")
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
            parts.append(f"Form ({f}) isn't the full story.")
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
            parts.append(f"Form ({f}) — steady as she goes.")
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
            parts.append(f"Form ({f}) for what it's worth.")
    else:
        parts = [f"{name} enter this fixture without a strong recent record to lean on."]
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


def _competition_category(comp: str) -> str:
    """W84-Q5: Categorise competition for contextual framing in low-context narratives."""
    c = comp.lower()
    if any(w in c for w in ["champions", "europa", "conference", "continental"]):
        return "continental"
    if any(w in c for w in ["six nations", "rugby championship", "rugby world cup"]):
        return "international"
    if any(w in c for w in ["urc", "super rugby", "currie cup", "premiership rugby"]):
        return "club_rugby"
    if any(w in c for w in ["sa20", "ipl", "big bash", "t20", "odi", "test match"]):
        return "cricket"
    if any(w in c for w in ["ufc", "boxing", "mma"]):
        return "combat"
    return "league"  # domestic league default


def _match_shape_note(comp_cat: str, fixture_type: str) -> str:
    """W84-Q6/Q8: Genre description — what kind of contest this type of game tends to produce.

    Evidence-bounded: describes the competition genre only. No team-specific facts.
    """
    _ft_pl = _plural(fixture_type)
    _shapes = {
        "continental": (
            f"European competition {_ft_pl} carry a different weight to league games — "
            f"knockout stakes compress the scoring range and lift the value of cautious outcomes."
        ),
        "international": (
            f"International {_ft_pl} carry squad selection uncertainty "
            f"that can reshape the game plan right up to kickoff."
        ),
        "club_rugby": (
            f"Club rugby is decided by set-piece discipline and territorial control — "
            f"margins are tight, and a single dominant set-piece sequence can determine the outcome."
        ),
        "cricket": (
            f"Cricket outcomes hinge on conditions and team selection "
            f"that may not crystallise until just before the match."
        ),
        "combat": (
            f"Combat {_ft_pl} are shaped as much by stylistic matchup as raw record — "
            f"the right style clash can flip the market entirely, regardless of who's favourite."
        ),
        "league": (
            f"Without current form data, these {_ft_pl} are priced primarily on market consensus — "
            f"which is where implied probability and model probability tend to diverge most."
        ),
    }
    return _shapes.get(comp_cat, "")


def _render_setup_no_context(spec: NarrativeSpec) -> str:
    """W84-Q8: Premiumized no-context Setup. 8 MD5-deterministic variants.

    Each variant is a distinct angle on the fixture: competition character,
    contest tension, pre-match picture, live sweat, price story. Evidence-bounded
    — describes genre, competition type, and market mechanics only. No team facts.
    """
    comp = spec.competition or ""
    comp_note = f" in {comp}" if comp else ""
    h, a = spec.home_name, spec.away_name
    outcome = spec.outcome_label or "this outcome"
    odds_str = f"{spec.odds:.2f}" if spec.odds else ""
    bk = spec.bookmaker or "the market"
    sport = spec.sport or "soccer"

    fp_str = f"{spec.fair_prob_pct:.0f}%" if spec.fair_prob_pct else "?"
    market_implied = f"{round(100.0 / spec.odds):.0f}%" if spec.odds and spec.odds > 1 else "?"

    _ev = spec.ev_pct
    # _ev_noun: plain phrase without article ("moderate 3.8% expected value gap")
    # _ev_label: with article — use where "a/an" precedes ("a moderate 3.8%...")
    # Rule: use _ev_noun after "That/The/this"; use _ev_label elsewhere
    _ev_noun = (
        f"{_ev:.1f}% expected value gap" if _ev >= 5
        else f"moderate {_ev:.1f}% expected value gap" if _ev >= 2
        else f"{_ev:.1f}% expected value gap"
    )
    _ev_label = f"a {_ev_noun}"

    _fixture_type = {
        "soccer": "fixture", "rugby": "clash",
        "cricket": "encounter", "combat": "bout",
    }.get(sport, "match")

    _cat = _competition_category(comp)
    # W84-Q14: sport-aware override using contains check — sport_key is e.g.
    # "cricket_test_match", "cricket_icc_world_cup", not just "cricket"
    if _cat == "league" and "cricket" in sport:
        _cat = "cricket"
    elif _cat == "league" and ("rugby" in sport or sport in ("urc", "super_rugby")):
        _cat = "club_rugby"
    _match_shape = _match_shape_note(_cat, _fixture_type)

    # W84-Q8: What this competition type typically produces as a contest
    _ft_pl = _plural(_fixture_type)
    _cat_display = {
        "continental": "continental", "international": "international",
        "club_rugby": "club rugby", "cricket": "cricket",
        "combat": "combat sports", "league": "domestic league",
    }.get(_cat, _cat)
    _game_character = {
        "continental": (
            f"European competition {_ft_pl} have their own rhythm — "
            f"tighter margins, fewer open exchanges, and more intrigue in patient outcomes."
        ),
        "international": (
            f"International {_ft_pl} are shaped as much by what isn't confirmed "
            f"pre-match as what is — squad selection is the dominant variable."
        ),
        "club_rugby": (
            f"Club rugby at this level is a territory war — "
            f"set-piece execution and breakdown discipline decide margins more reliably than individual talent."
        ),
        "cricket": (
            f"Cricket at this level hinges on a narrow set of variables: "
            f"conditions, team selection, and the toss — all of which firm up in the final hours."
        ),
        "combat": (
            f"Combat sports markets are driven by narrative and matchup perception as much as record — "
            f"which produces pricing divergences between opening and closing lines."
        ),
        "league": (
            f"Domestic league {_ft_pl} without current form get priced on team identity — "
            f"which is where the market tends to over- or under-value sides relative to what the data actually supports."
        ),
    }.get(_cat, "")

    # W84-Q8: Pre-match picture for this competition type
    _fixture_context = {
        "continental": (
            f"Pre-kickoff information in European ties is always partial — "
            f"rotation decisions, tactical shape, and travel schedules create a soft pre-match price."
        ),
        "international": (
            f"The pre-match picture for international {_ft_pl} is deliberately incomplete — "
            f"coaches protect squad news, and the market works from the same uncertainty as everyone else."
        ),
        "club_rugby": (
            f"Club rugby markets run on less data than domestic football — "
            f"which means pricing gaps can hold longer before kickoff, "
            f"and the line move carries more information than the opening price."
        ),
        "cricket": (
            f"The pre-match picture crystallises late in cricket — "
            f"conditions and final XI confirmation can reshape the entire market in the hour before the toss."
        ),
        "combat": (
            f"Both corners have managed their pre-fight information carefully. "
            f"The opening line reflects what's been said publicly — not necessarily the full picture."
        ),
        "league": (
            f"Without form or movement data, this is priced on who these teams are — "
            f"not what they're doing right now. That's the most honest read available."
        ),
    }.get(_cat, "")

    # W84-Q8: What to watch live / what kind of sweat this is
    _sweat_note = {
        "continental": (
            f"The team shape in the opening 20 minutes tells you whether the market "
            f"priced the tactical intent correctly — watch how deep the away side defends."
        ),
        "international": (
            f"Squad confirmation and early match tempo will tell you whether "
            f"the pre-match price was anchored correctly."
        ),
        "club_rugby": (
            f"First-quarter territory and set-piece outcomes are the leading indicators — "
            f"they'll tell you whether the market's pre-match read is holding."
        ),
        "cricket": (
            f"The toss and first session are the real first data points — "
            f"they'll tell you whether the pre-match price deserved backing."
        ),
        "combat": (
            f"The opening exchange tells you whether the stylistic matchup "
            f"is playing out as the market modelled it."
        ),
        "league": (
            f"The opening exchanges will tell you whether the pre-match price "
            f"was well-anchored or wider than the match play deserves."
        ),
    }.get(_cat, "")

    # W84-Q8: Character of the pricing gap (EV-based, direct)
    _price_char = (
        f"The line looks softer than it should at this price." if _ev >= 8
        else f"There's a tick of value in the current price." if _ev >= 4
        else f"A real tick of value in the current price." if _ev >= 2
        else f"A slim model-identified edge in the opening line."
    )

    _v = _pick(h + a, 8)
    _nc_variants = [
        # 0 — Game character leads (what this competition type produces → then the price)
        (
            f"{h} vs {a}{comp_note}. "
            f"{_game_character} "
            f"{outcome} is priced at {odds_str} ({bk}) — our model reads {fp_str} fair probability. "
            f"When there's no form to lean on, the price gap carries more weight. That {_ev_noun} is the model's read on this one."
        ),
        # 1 — Match shape + what kind of competition this is + price
        (
            f"{h} take on {a}{comp_note}. "
            f"{_match_shape} "
            f"{bk} has {outcome} at {odds_str} ({market_implied} implied); our model reads {fp_str}. "
            f"That {_ev_noun} is the divergence — no form data to confirm it, but the price model flags it."
        ),
        # 2 — Pre-match picture + price divergence (why the gap might exist → the gap)
        (
            f"{h} vs {a}{comp_note}. "
            f"{_fixture_context} "
            f"The price on {outcome} — {odds_str} at {bk} ({market_implied} implied) — "
            f"diverges from our {fp_str} estimate by {_ev_noun}."
        ),
        # 3 — Match shape + how bookmakers price this competition type
        (
            f"{h} take on {a}{comp_note}. "
            f"{_match_shape} "
            f"When {_ft_pl} like this arrive without current form data, "
            f"the bookmaker's line is anchored to historical averages — not to what's happening right now. "
            f"{bk} at {odds_str} on {outcome} vs our {fp_str}: {_ev_label}."
        ),
        # 4 — Price character + direct editorial voice (sharp punter framing)
        (
            f"{h} host {a}{comp_note}. "
            f"{_price_char} "
            f"{bk} at {odds_str} implies {market_implied} probability on {outcome}; "
            f"our model reads {fp_str}. "
            f"In a market priced on identity rather than current form, that {_ev_noun} is the sharpest read you'll get pre-kick."
        ),
        # 5 — Match shape leads, price as supporting evidence
        (
            f"{_match_shape} "
            f"{h} vs {a}{comp_note}. "
            f"{bk} has {outcome} at {odds_str} ({market_implied} implied); our model has {fp_str}. "
            f"That {_ev_noun} is where the model and market disagree. This bet is the call on which one is right."
        ),
        # 6 — Live sweat description + price (what this bet feels like in-play)
        (
            f"{h} take on {a}{comp_note}. "
            f"{_sweat_note} "
            f"{bk} at {odds_str} on {outcome} — {market_implied} implied vs our {fp_str}. "
            f"That {_ev_noun} is the pre-match case. The live {_fixture_type} either confirms it or doesn't."
        ),
        # 7 — Full immersive frame (game character + sweat + price — richest no-context card)
        (
            f"This {_fixture_type} between {h} and {a}{comp_note} fits a recognisable type. "
            f"{_game_character} "
            f"{_sweat_note} "
            f"{bk} at {odds_str} on {outcome} vs our {fp_str}: {_ev_label}."
        ),
    ]
    return _nc_variants[_v]


def _render_setup(spec: NarrativeSpec) -> str:
    """4-8 sentence Setup section from verified NarrativeSpec data.
    OEI pattern: home paragraph → away paragraph → H2H bridge.

    W84-P1E: When no standings/form data available (both neutral, no form),
    produce a compact honest note rather than two thin boilerplate paragraphs.
    """
    # No context — produce compact edge-focused setup instead of boilerplate
    _no_context = (
        spec.home_story_type == "neutral"
        and spec.away_story_type == "neutral"
        and not spec.home_form
        and not spec.away_form
        and spec.home_position is None
        and spec.away_position is None
    )
    if _no_context:
        return _render_setup_no_context(spec)
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

    _seed = (spec.home_name or "") + (spec.away_name or "")

    if spec.evidence_class == "speculative":
        _v = _pick(_seed, 6)
        _spec_variants = [
            # 0 — Gap analysis: what type of mispricing this looks like
            (
                f"The model reads {ev_str} expected value on {outcome} at {odds_str} with {bk}. "
                f"Fair probability at {fp_str} vs the bookmaker's implied probability — "
                f"the model puts this down to a pricing difference, not a confirmed signal. "
                f"This is a price divergence without confirming signals — a model flag, not a confirmed edge."
            ),
            # 1 — Market exposure angle: what drives the gap
            (
                f"{outcome} at {odds_str} ({bk}) against a fair probability of {fp_str} gives {ev_str} edge. "
                f"When bookmakers manage exposure on a less-modelled outcome, the line can sit wider than "
                f"true probability warrants — which is what this gap looks like. "
                f"Note whether it holds or closes before kickoff — that tells you how the market reads it."
            ),
            # 2 — Analytical posture: what the model is saying
            (
                f"Our model puts fair value at {fp_str} for {outcome} — "
                f"{bk} is offering {odds_str}, which works out to {ev_str} expected value. "
                f"The gap is consistent across the model's calculations. "
                f"A measured-exposure play: you're backing the model's assessment against the bookmaker's."
            ),
            # 3 — What you're actually betting on (transparent, actionable)
            (
                f"A {ev_str} edge on {outcome} at {odds_str} with {bk}: "
                f"the model estimates {fp_str} fair probability, the bookmaker implies less. "
                f"The kind of bet where you back the model's pricing read against the bookmaker's "
                f"for this competition type — small stake, open mind."
            ),
            # 4 — Price divergence + resolution path
            (
                f"The bookmaker line on {outcome} ({odds_str} at {bk}) implies a lower probability "
                f"than our model's {fp_str} estimate — that's where the {ev_str} edge originates. "
                f"Speculative edges like this either close pre-kickoff as the market corrects, "
                f"or hold because the model has the better read. Treat exposure accordingly — if you take it at all."
            ),
            # 5 — Clean quantitative statement with bet posture
            (
                f"Expected value of {ev_str} on {outcome}: {bk} at {odds_str} vs our {fp_str} fair probability. "
                f"A measurable gap between the price and our model's read. No specific intel, but the number is there. "
                f"Small exposure — hold it lightly and watch the closing price."
            ),
        ]
        return _spec_variants[_v]

    elif spec.evidence_class == "lean":
        _v = _pick(_seed, 3)
        _lean_variants = [
            (
                f"Some value showing on {outcome} — fair probability at {fp_str} "
                f"vs {odds_str} on offer at {bk} ({ev_str}). "
                f"One signal leans this way, which moves this above pure speculation. "
                f"Enough signal to engage — size it carefully."
            ),
            (
                f"The model sees {ev_str} on {outcome} at {odds_str} ({bk}), "
                f"with one confirming indicator leaning in the same direction. "
                f"Fair value at {fp_str} — enough to act on, not enough to go heavy."
            ),
            (
                f"Fair probability at {fp_str} against {odds_str} at {bk} gives {ev_str} on {outcome}. "
                f"There's a single supporting signal here — it lifts this into measured play territory. "
                f"A step above a blind price bet."
            ),
        ]
        return _lean_variants[_v]

    elif spec.evidence_class == "supported":
        _v = _pick(_seed, 3)
        _supp_variants = [
            (
                f"Multiple indicators agree on {outcome} — fair probability at {fp_str} "
                f"vs {odds_str} at {bk} ({ev_str}). "
                f"This has the depth of support that separates a proper edge from a price guess."
            ),
            (
                f"This one has legs: {ev_str} expected value on {outcome} at {odds_str} ({bk}), "
                f"with confirming indicators from form, movement, or tipster consensus. "
                f"Fair value at {fp_str} — the case is solid at the current price."
            ),
            (
                f"The edge on {outcome} at {odds_str} with {bk} ({ev_str}) isn't just model-driven — "
                f"multiple data points confirm the gap. Fair probability at {fp_str}. "
                f"One of the better-supported plays on the card."
            ),
        ]
        return _supp_variants[_v]

    else:  # conviction
        _v = _pick(_seed, 3)
        _conv_variants = [
            (
                f"One of the stronger plays today. Multiple signals align behind {outcome} "
                f"at {odds_str} with {bk} ({ev_str}). "
                f"Fair probability at {fp_str} — the market looks mispriced here."
            ),
            (
                f"Strong conviction on {outcome}: {ev_str} expected value at {odds_str} ({bk}), "
                f"backed by a cluster of confirming signals. "
                f"Fair value at {fp_str} — this has the depth of support most edges don't get."
            ),
            (
                f"Everything lines up on {outcome} — {ev_str} edge, {odds_str} at {bk}, "
                f"fair probability at {fp_str}, and multiple confirming indicators. "
                f"Premium value. The market has this wrong."
            ),
        ]
        return _conv_variants[_v]


def _render_risk(spec: NarrativeSpec) -> str:
    """Risk section: what could go wrong + sizing guidance. Distinct from Edge (what's right)."""
    factors_text = " ".join(spec.risk_factors)
    # W84-Q8: More texture in severity notes — feels like a real risk assessment
    severity_note = {
        "high": "High-risk environment here — treat this as speculative or pass entirely.",
        "moderate": "Factor that in — size accordingly, but it doesn't change the core argument.",
        "low": "Risk profile is clean here. Execute with normal sizing.",
    }.get(spec.risk_severity, "Size conservatively and keep your exposure tight.")
    return f"{factors_text} {severity_note}".strip()


def _render_verdict(spec: NarrativeSpec) -> str:
    """Verdict capped by tone_band. Never uses phrases banned by tone_band."""
    outcome = spec.outcome_label or "this outcome"
    odds_str = f"{spec.odds:.2f}" if spec.odds else "?"
    bk = spec.bookmaker or "the market"
    action = spec.verdict_action
    sizing = spec.verdict_sizing

    _seed = (spec.home_name or "") + (spec.away_name or "")

    if action == "pass":
        # W84-Q13: Zero/negative EV — never frame as actionable
        return (
            f"No positive expected value at current pricing — "
            f"monitor for line movement or skip {outcome} until the price improves."
        )

    if action == "speculative punt":
        _v = _pick(_seed, 4)
        _sp_variants = [
            # W84-Q15: Disciplined posture — no "worth a unit", no "take the edge"
            (
                f"The price is the only reason {outcome} ({bk} @ {odds_str}) is on the board — "
                f"no confirming signal backs it. Only take it with minimal exposure and a clear head. "
                f"{_sentence_case(sizing)}."
            ),
            (
                f"If you back this at all, keep exposure very tight — {outcome} at {odds_str} ({bk}). "
                f"Monitor the line before kickoff. {_sentence_case(sizing)}."
            ),
            (
                f"A speculative angle on {outcome} at {odds_str} with {bk} — "
                f"the price is right, the signals aren't there yet. Monitor the line before committing. {_sentence_case(sizing)}."
            ),
            (
                f"Pass on this unless the price improves or a confirming signal emerges — "
                f"{outcome} at {odds_str} ({bk}) has no signal support. "
                f"Monitor the line, not the bet. {_sentence_case(sizing)}."
            ),
        ]
        return _sp_variants[_v]

    elif action == "lean":
        _v = _pick(_seed, 3)
        _lean_variants = [
            (
                f"Lean on {outcome} at {odds_str} ({bk}) — "
                f"enough signal to commit, not enough to go heavy. {_sentence_case(sizing)}."
            ),
            (
                f"A measured lean: {outcome} at {odds_str} with {bk}. "
                f"Back it at a reasonable stake, hold it with a clear head. {_sentence_case(sizing)}."
            ),
            (
                f"Cautious nod to {outcome} at {odds_str} ({bk}). "
                f"One signal in the right direction — enough to act on. {_sentence_case(sizing)}."
            ),
        ]
        return _lean_variants[_v]

    elif action == "back":
        _v = _pick(_seed, 3)
        _back_variants = [
            (
                f"Back {outcome} at {odds_str} with {bk} — "
                f"the indicators are doing their job here. {_sentence_case(sizing)}."
            ),
            (
                f"{outcome} at {odds_str} ({bk}) — back it. "
                f"Multiple data points confirm the direction. {_sentence_case(sizing)}."
            ),
            (
                f"This one gets the green light: {outcome} at {odds_str} with {bk}. "
                f"Supported, priced right, worth a considered stake. {_sentence_case(sizing)}."
            ),
        ]
        return _back_variants[_v]

    else:  # strong back
        _v = _pick(_seed, 3)
        _strong_variants = [
            (
                f"Strong back on {outcome} at {odds_str} ({bk}) — "
                f"this has the depth of support most edges don't get. {_sentence_case(sizing)}."
            ),
            (
                f"Back {outcome} at {odds_str} with {bk} with conviction. "
                f"Everything lines up — signals, price, model agreement. {_sentence_case(sizing)}."
            ),
            (
                f"Premium play: {outcome} at {odds_str} ({bk}). "
                f"The signals, the price, and the model all point the same way. {_sentence_case(sizing)}."
            ),
        ]
        return _strong_variants[_v]


def _render_baseline(spec: NarrativeSpec) -> str:
    """Assemble all 4 sections into the full baseline narrative with emoji headers."""
    setup = _render_setup(spec)
    edge = _render_edge(spec)
    risk = _render_risk(spec)
    verdict = _render_verdict(spec)
    return (
        f"📋 <b>The Setup</b>\n{setup}\n\n"
        f"🎯 <b>The Edge</b>\n{edge}\n\n"
        f"⚠️ <b>The Risk</b>\n{risk}\n\n"
        f"🏆 <b>Verdict</b>\n{verdict}"
    )
