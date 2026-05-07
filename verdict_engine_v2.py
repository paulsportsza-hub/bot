from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import re
from typing import Any, Mapping, Sequence


def _single_mention_enabled() -> bool:
    return os.environ.get("V2_SINGLE_MENTION", "true").strip().lower() in ("true", "1", "yes", "on")


def _body_reference_enabled() -> bool:
    """FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 flag.
    flag=1 (default): body uses Strategy α (nickname → coach surname's side → anaphor).
    flag=0: revert to FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01 anaphor-only body.
    """
    return os.environ.get("V2_BODY_REFERENCE", "true").strip().lower() in ("true", "1", "yes", "on")


@dataclass(frozen=True)
class VerdictContext:
    match_key: str
    edge_revision: str
    sport: str
    league: str
    home_name: str
    away_name: str
    recommended_team: str
    outcome_label: str | None = None
    odds: str | float | None = None
    bookmaker: str | None = None
    tier: str = "bronze"
    signals: Mapping[str, Any] = field(default_factory=dict)
    evidence_pack: Mapping[str, Any] | None = None
    home_form: str | None = None
    away_form: str | None = None
    h2h: str | None = None
    injuries_home: Sequence[str] = field(default_factory=tuple)
    injuries_away: Sequence[str] = field(default_factory=tuple)
    venue: str | None = None
    coach: str | None = None
    nickname: str | None = None
    bookmaker_count: int | None = None
    line_movement_direction: str | None = None
    tipster_sources_count: int | None = None
    bet_type_is_team_outcome: bool = True


@dataclass(frozen=True)
class VerdictResult:
    text: str
    valid: bool
    fallback: bool
    primary_fact_type: str
    validation_errors: tuple[str, ...] = ()


CANONICAL_SIGNALS = (
    "price_edge",
    "movement",
    "lineup_injury",
    "form_h2h",
    "market_agreement",
    "tipster",
    "model_probability",
)

ALIASES = {
    "line_mvt": "movement",
    "injury": "lineup_injury",
    "form": "form_h2h",
    "market": "market_agreement",
}

BANNED_TELEMETRY_TERMS = (
    "composite",
    "tier floor",
    "signal stack",
    "ev",
    "expected value",
    "model probability",
    "implied probability",
    "support level",
)

BANNED_TIER_COPY = (
    "diamond-grade",
    "gold-grade",
    "silver-grade",
    "bronze-grade",
    "diamond tier",
    "gold tier",
    "silver tier",
    "bronze tier",
    "bronze-tier",
    "silver-tier",
    "gold-tier",
    "diamond-tier",
)

BANNED_OVERCLAIMS = (
    "guaranteed",
    "lock",
    "max bet",
    "all-in",
    "free money",
    "can't lose",
    "cannot lose",
)

LIVE_COMMENTARY_TERMS = (
    "dictating tempo",
    "creating overloads",
    "dominating the ball",
    "winning collisions",
    "controlling possession",
    "pinning them back",
)

PRICE_CLAUSES = (
    "the price still looks playable",
    "the number still gives us room",
    "the price leaves a clear opening",
    "the market has not fully caught up",
    "the value is still there",
    "the quote still looks generous",
    "the price is doing enough work",
    "the number keeps this live",
)

FORM_CLAUSES = (
    "recent results back the lean",
    "form gives this extra weight",
    "the form read supports the price",
    "recent form points the right way",
    "the results profile gives this support",
    "form adds a useful push",
    "recent results strengthen the case",
    "the form angle is doing real work",
)

INJURY_CLAUSES = (
    "team news has not been fully priced in",
    "the team-news angle adds weight",
    "availability tilts this our way",
    "the injury read supports the price",
    "team news keeps the value alive",
    "availability gives this extra appeal",
)

MOVEMENT_FOR_CLAUSES = (
    "the line is starting to move our way",
    "market movement is following the pick",
    "the move adds support",
    "the line move helps the case",
)

MOVEMENT_AGAINST_CLAUSES = (
    "the move has not killed the value",
    "the market shifted, but the price still plays",
    "the drift is noted, but value remains",
    "the move is a concern, not a blocker",
)

MOVEMENT_UNKNOWN_CLAUSES = (
    "the move has not killed the value",
    "the line still leaves room",
    "the movement read keeps this playable",
    "the move still leaves a path in",
)

MARKET_CLAUSES = (
    "the wider market gives this support",
    "bookmaker breadth backs the lean",
    "the broader board supports the price",
    "the market read adds confirmation",
)

TIPSTER_CLAUSES = (
    "outside support lines up here",
    "external reads back this side",
    "the outside view agrees",
    "tipster support adds a push",
)

VENUE_CLAUSES = (
    "{venue} gives the price extra context",
    "the home setting adds weight",
    "{venue} helps the case",
    "the venue angle supports the lean",
)

ACTION_BY_TIER = {
    "diamond": (
        "Back {team}, full stake.",
        "{team} is the play, full stake.",
    ),
    "gold": (
        "Back {team}, standard stake.",
        "{team} is the play, standard stake.",
    ),
    "silver": (
        "Lean {team}, standard stake.",
        "{team} gets the nod, standard stake.",
    ),
    "bronze": (
        "Worth a small play on {team}, light stake.",
        "Small lean to {team}, light stake.",
    ),
}

MARKET_ACTION_BY_TIER = {
    "diamond": (
        "Back {market}, full stake.",
        "{market} is the play, full stake.",
    ),
    "gold": (
        "Back {market}, standard stake.",
        "{market} is the play, standard stake.",
    ),
    "silver": (
        "Lean {market}, standard stake.",
        "{market} gets the nod, standard stake.",
    ),
    "bronze": (
        "Worth a small play on {market}, light stake.",
        "Small lean to {market}, light stake.",
    ),
}

FACT_PRIORITY = (
    "form_h2h",
    "lineup_injury",
    "movement",
    "market_agreement",
    "tipster",
    "venue_reference",
    "price_edge",
)

SHAPES = (
    "identity_price_fact_action",
    "fact_price_action",
    "fact_action",
    "price_fact_action",
)

KNOWN_TEAM_TOKENS = (
    "Sunrisers Hyderabad",
    "Delhi Capitals",
    "Chennai Super Kings",
    "Mumbai Indians",
    "Liverpool",
    "Chelsea",
    "Manchester City",
    "Brentford",
    "Bulls",
    "Stormers",
)

POSITIVE_MOVEMENT = {"for", "toward", "towards", "favourable", "favorable", "shortening", "steam"}
NEGATIVE_MOVEMENT = {"against", "away", "drift", "drifting", "negative", "unfavourable", "unfavorable"}

# FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 (Strategy α floor):
# Anaphor pool used when neither nickname nor coach is available. Each phrase
# acts as a noun-phrase substitute for the recommended team in body fact_clauses
# (e.g., "form gives the lean extra weight"). Stable_pick rotated per fact_type
# salt so multi-fact renders don't all land on the same anaphor.
ANAPHOR_POOL = (
    "the lean",
    "the pick",
    "the play",
    "this side",
    "this lean",
    "the call",
)


def stable_pick(options: Sequence[str], *, key: str) -> str:
    if not options:
        raise ValueError("stable_pick requires at least one option")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    idx = int(digest[:12], 16) % len(options)
    return options[idx]


def signal_available(ctx: VerdictContext, name: str) -> bool:
    canonical = ALIASES.get(name, name)
    value = _signal_value(ctx, canonical)
    if isinstance(value, Mapping):
        return value.get("available") is True
    if isinstance(value, bool):
        return value
    return bool(value)


def identity_label(ctx: VerdictContext, *, salt: str) -> str:
    team = _clean(ctx.recommended_team)
    nickname = _clean(ctx.nickname)
    coach = _clean(ctx.coach)
    labels: list[str] = []

    if coach and nickname:
        nick_for_coach = re.sub(r"^the\s+", "", nickname, flags=re.IGNORECASE)
        possessive = f"{coach}'" if coach.endswith("s") else f"{coach}'s"
        coach_label = f"{possessive} {nick_for_coach}"
        if 5 <= len(coach_label) <= 34:
            labels.append(coach_label)
    if nickname and len(nickname) <= 30:
        labels.append(nickname)
    if team:
        labels.append(team)

    if not labels:
        return team
    return stable_pick(tuple(dict.fromkeys(labels)), key=f"{_base_key(ctx)}|identity_style|{salt}")


def _coach_surname_possessive(coach: str) -> str:
    """Strategy α coach phrase: 'Pep Guardiola' → "Guardiola's side";
    'Sergio Ramos' → "Ramos' side"; 'Sir Alex Ferguson' → "Ferguson's side".

    Surname = last whitespace-split token. Apostrophe-only when surname ends
    in 's' (regardless of case), apostrophe-s otherwise.
    """
    cleaned = (coach or "").strip()
    if not cleaned:
        return ""
    parts = cleaned.split()
    surname = parts[-1] if parts else ""
    if not surname:
        return ""
    if surname.lower().endswith("s"):
        return f"{surname}' side"
    return f"{surname}'s side"


def _body_reference(
    ctx: VerdictContext, *, salt: str, force_anaphor: bool = False
) -> str:
    """Strategy α priority chain for body slot-fill.

    Order: nickname (e.g. 'the Magpies') → coach surname's side ('Guardiola's
    side') → anaphor pool ('the lean', 'the pick', ...).

    force_anaphor=True is used by the identity_lead shape when identity_label
    already fired with a nickname or coach phrase — avoids double-mention.
    Salt rotates the anaphor pool across fact_types within a render.
    """
    if not force_anaphor:
        nickname = _clean(ctx.nickname)
        if nickname:
            return nickname
        coach_phrase = _coach_surname_possessive(_clean(ctx.coach))
        if coach_phrase:
            return coach_phrase
    return stable_pick(ANAPHOR_POOL, key=f"{_base_key(ctx)}|body_anaphor|{salt}")


def _identity_used_alias(identity: str, ctx: VerdictContext) -> bool:
    """Detect whether identity_label() picked nickname/coach (vs bare team).

    True when identity_label fired with a non-team alias — the body must then
    fall through to anaphor to avoid a double-mention of nickname/coach.
    """
    if not identity:
        return False
    return identity.strip() != _clean(ctx.recommended_team)


def validate_team_integrity(text: str, ctx: VerdictContext) -> list[str]:
    errors: list[str] = []
    recommended = _clean(ctx.recommended_team)
    home = _clean(ctx.home_name)
    away = _clean(ctx.away_name)
    outcome = _clean(ctx.outcome_label)
    nickname = _clean(ctx.nickname)

    if not recommended:
        errors.append("missing_recommended_team")
        return errors

    recommended_ok = (
        _team_match(recommended, home)
        or _team_match(recommended, away)
        or bool(outcome and _team_match(recommended, outcome))
    )
    if not recommended_ok:
        errors.append("recommended_team_not_in_fixture")

    text_norm = _normalise(text)
    rec_norm = _normalise(recommended)
    nick_norm = _normalise(nickname)
    if rec_norm not in text_norm and not (nick_norm and nick_norm in text_norm):
        errors.append("verdict_missing_recommended_team_or_nickname")

    allowed = tuple(
        item
        for item in (
            home,
            away,
            recommended,
            outcome,
            nickname,
        )
        if item
    )
    for token in KNOWN_TEAM_TOKENS:
        if not _contains_team_token(text, token):
            continue
        if any(_team_match(token, allowed_name) for allowed_name in allowed):
            continue
        errors.append(f"third_team_reference:{token}")

    return errors


def validate_verdict(text: str, ctx: VerdictContext, *, fallback: bool = False) -> tuple[str, ...]:
    errors: list[str] = []
    if len(text) > 200:
        errors.append("too_long")
    if fallback and len(text) > 120:
        errors.append("fallback_too_long")

    errors.extend(_banned_errors(text, "banned_telemetry", BANNED_TELEMETRY_TERMS))
    errors.extend(_banned_errors(text, "banned_tier_copy", BANNED_TIER_COPY))
    errors.extend(_banned_errors(text, "banned_overclaim", BANNED_OVERCLAIMS))
    errors.extend(_banned_errors(text, "live_commentary", LIVE_COMMENTARY_TERMS))
    errors.extend(validate_team_integrity(text, ctx))
    errors.extend(_signal_claim_errors(text, ctx))

    return tuple(dict.fromkeys(errors))


def safe_shell(ctx: VerdictContext, reason: str) -> VerdictResult:
    team = _clean(ctx.recommended_team) or "the pick"
    tier = _tier(ctx)
    if tier in {"diamond", "gold"}:
        stake = "full stake" if tier == "diamond" else "standard stake"
        action = f"back {team}, {stake}."
        compact = f"{stake} play."
    elif tier == "silver":
        action = f"lean {team}, standard stake."
        compact = "standard-stake lean."
    else:
        action = f"small lean to {team}, light stake."
        compact = "light-stake lean."

    text = f"Price still supports {team} — {action}"
    if len(text) > 120:
        text = f"Price still supports {team} — {compact}"
    if len(text) > 120:
        text = f"Price supports {team}."

    shell_errors = validate_verdict(text, ctx, fallback=True)
    return VerdictResult(
        text=text,
        valid=not shell_errors,
        fallback=True,
        primary_fact_type="safe_shell",
        validation_errors=tuple(dict.fromkeys((reason, *shell_errors))),
    )


def render_verdict_v2(ctx: VerdictContext) -> VerdictResult:
    facts = _available_fact_types(ctx)
    if not facts:
        return safe_shell(ctx, "no_usable_fact")

    attempted_errors: list[str] = []
    primary_options = _rotated(facts, key=f"{_base_key(ctx)}|primary_fact_type")
    shape_options = _rotated(SHAPES, key=f"{_base_key(ctx)}|sentence_shape")

    for fact_attempt in range(len(primary_options)):
        primary = primary_options[fact_attempt]
        for shape_attempt, shape in enumerate(shape_options):
            for clause_attempt in range(8):
                candidate = _render_candidate(
                    ctx,
                    primary_fact_type=primary,
                    shape=shape,
                    attempt=clause_attempt + shape_attempt,
                )
                if not candidate:
                    continue
                errors = validate_verdict(candidate, ctx)
                if not errors:
                    return VerdictResult(
                        text=candidate,
                        valid=True,
                        fallback=False,
                        primary_fact_type=primary,
                        validation_errors=(),
                    )
                attempted_errors.extend(errors)

    reason = "normal_candidate_invalid"
    if attempted_errors:
        reason = attempted_errors[0]
    return safe_shell(ctx, reason)


def _is_team_outcome(ctx: VerdictContext) -> bool:
    """Whether the recommended pick is a team-bet (home/away win) vs market-bet
    (BTTS Yes/No, Over/Under, draw, etc.)."""
    if not ctx.bet_type_is_team_outcome:
        return False
    rec = _clean(ctx.recommended_team)
    if not rec:
        return False
    return _team_match(rec, _clean(ctx.home_name)) or _team_match(rec, _clean(ctx.away_name))


def _market_label(ctx: VerdictContext) -> str:
    """Human-readable market label for non-team-bet closes."""
    rec = _clean(ctx.recommended_team)
    outcome = _clean(ctx.outcome_label)
    if outcome and not _team_match(outcome, _clean(ctx.home_name)) and not _team_match(outcome, _clean(ctx.away_name)):
        return outcome
    return rec or outcome or "the pick"


def _market_action_sentence(ctx: VerdictContext, *, salt: str) -> str:
    options = MARKET_ACTION_BY_TIER.get(_tier(ctx), MARKET_ACTION_BY_TIER["bronze"])
    return stable_pick(options, key=f"{_base_key(ctx)}|market_action_variant|{salt}").format(
        market=_market_label(ctx)
    )


def _market_action_with_price(ctx: VerdictContext) -> str:
    market = _market_label(ctx)
    tier = _tier(ctx)
    price = _price_anchor(ctx)
    price_part = f" {price}" if price else ""
    if tier == "diamond":
        return f"back {market}{price_part}, full stake."
    if tier == "gold":
        return f"back {market}{price_part}, standard stake."
    if tier == "silver":
        return f"lean {market}{price_part}, standard stake."
    return f"small lean to {market}{price_part}, light stake."


def _render_candidate(
    ctx: VerdictContext,
    *,
    primary_fact_type: str,
    shape: str,
    attempt: int,
) -> str | None:
    single_mention = _single_mention_enabled()
    body_name_team = not single_mention
    is_team_outcome = _is_team_outcome(ctx)
    if not is_team_outcome and single_mention:
        body_name_team = False
        action = _market_action_sentence(ctx, salt=f"{shape}|{primary_fact_type}|{attempt}")
        action_with_price = _market_action_with_price(ctx)
    else:
        action = _action_sentence(ctx, salt=f"{shape}|{primary_fact_type}|{attempt}")
        action_with_price = _action_with_price(ctx)

    # FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 Strategy α:
    # compute identity first so we can detect alias-firing and force body to
    # anaphor in the identity_lead shape (avoids double nickname/coach mention).
    identity = identity_label(ctx, salt=f"{shape}|{attempt}")
    body_ref = ""
    if not body_name_team and _body_reference_enabled():
        force_anaphor = (
            shape == "identity_price_fact_action"
            and _identity_used_alias(identity, ctx)
        )
        body_ref = _body_reference(
            ctx, salt=primary_fact_type, force_anaphor=force_anaphor
        )

    fact_clause = _render_fact_clause(
        ctx, primary_fact_type, attempt=attempt,
        name_team=body_name_team, body_ref=body_ref,
    )
    if not fact_clause:
        return None

    price_anchor = _price_anchor(ctx)
    rendered: str | None

    # Single-mention close path: when V2_SINGLE_MENTION is on, fact_action +
    # price_fact_action shapes switch from _action (no odds) to
    # _action_with_price (carries odds + bookmaker). Without this,
    # verdict_corpus._with_v2_recommendation_anchor would prepend
    # `{team} at {odds} with {bookmaker} — ` to the verdict — adding a
    # second team mention and undoing Approach C. Applies to both team-bets
    # and market-bets (BTTS/Over/Under) — the wrapper triggers regardless.
    em_dash_action = action
    if single_mention:
        if is_team_outcome:
            em_dash_action = _capitalise(action_with_price)
        else:
            em_dash_action = _capitalise(_market_action_with_price(ctx))

    if shape == "identity_price_fact_action":
        lead = identity
        if price_anchor:
            lead = f"{lead} {price_anchor}"
        # Lead carries price_anchor (no wrapper prepend); close uses
        # the period-leading capitalised _action.
        rendered = f"{lead} — {fact_clause}. {action}"
    elif shape == "fact_price_action":
        rendered = f"{_capitalise(fact_clause)} — {action_with_price}"
    elif shape == "fact_action":
        rendered = f"{_capitalise(fact_clause)} — {em_dash_action}"
    elif shape == "price_fact_action":
        if primary_fact_type == "price_edge":
            secondary = _secondary_fact_clause(
                ctx, attempt=attempt, name_team=body_name_team, body_ref=body_ref
            )
            if not secondary:
                return None
            rendered = f"{_capitalise(fact_clause)} and {secondary} — {em_dash_action}"
        else:
            if not signal_available(ctx, "price_edge"):
                return None
            price_clause = _render_fact_clause(
                ctx, "price_edge", attempt=attempt,
                name_team=body_name_team, body_ref=body_ref,
            )
            if not price_clause:
                return None
            rendered = f"{_capitalise(price_clause)} and {fact_clause} — {em_dash_action}"
    else:
        return None

    return _fit_candidate(
        rendered,
        ctx,
        primary_fact_type=primary_fact_type,
        attempt=attempt,
        body_name_team=body_name_team,
        body_ref=body_ref,
        is_team_outcome=is_team_outcome,
    )


def _fit_candidate(
    text: str,
    ctx: VerdictContext,
    *,
    primary_fact_type: str,
    attempt: int,
    body_name_team: bool = True,
    body_ref: str = "",
    is_team_outcome: bool = True,
) -> str | None:
    if len(text) <= 200:
        return text

    # Mirror _render_candidate's close-with-price decision so the compact
    # fallback ALSO carries odds + bookmaker when V2_SINGLE_MENTION is on.
    # Without this, an overlength price_fact_action would compact to a
    # priceless close, the wrapper would prepend, and a second team/market
    # mention would re-appear. Codex round-5 finding.
    single_mention = _single_mention_enabled()
    if single_mention:
        if is_team_outcome:
            action = _capitalise(_action_with_price(ctx))
        else:
            action = _capitalise(_market_action_with_price(ctx))
    elif is_team_outcome:
        action = _action_sentence(ctx, salt=f"compact|{primary_fact_type}|{attempt}")
    else:
        action = _market_action_sentence(ctx, salt=f"compact|{primary_fact_type}|{attempt}")
    # body_ref carries Strategy α reference (nickname / coach / anaphor) — same
    # as the long path so compact rendering stays consistent.
    fact_clause = _render_fact_clause(
        ctx, primary_fact_type, attempt=attempt,
        name_team=body_name_team, body_ref=body_ref,
    )
    if not fact_clause:
        return None
    compact = f"{_capitalise(fact_clause)} — {action}"
    if len(compact) <= 200:
        return compact
    return None


def _render_fact_clause(
    ctx: VerdictContext,
    fact_type: str,
    *,
    attempt: int,
    name_team: bool = True,
    body_ref: str = "",
) -> str | None:
    """Render a fact clause for the given fact_type.

    name_team=True (legacy default) slot-fills ctx.recommended_team into the clause.
    name_team=False + body_ref="" (FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01
    Approach C) returns a team-less variant — the close carries the only mention.
    name_team=False + body_ref="<phrase>" (FIX-V2-VERDICT-NICKNAME-COACH-BODY-
    AND-VENUE-DROP-01 Strategy α) slots <phrase> into the same position {team}
    would occupy. body_ref is typically a nickname ("the Magpies"), coach phrase
    ("Guardiola's side"), or anaphor ("the lean") — all noun phrases that read
    cleanly in 'for X' / 'gives X' patterns.
    """
    # FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 Phase 4: venue
    # references retired ("Stadiums must be taken out. They just don't feel
    # right at all." — Paul 2026-05-07). Reject the fact_type unconditionally
    # so the rotation in render_verdict_v2 falls through to the next primary.
    # FACT_PRIORITY + _available_fact_types intentionally keep venue_reference
    # in the candidate list so the rotation modulo is byte-stable with the
    # pre-fix engine — protecting test_card_verdict_alignment from drift.
    if fact_type == "venue_reference":
        return None

    key = f"{_base_key(ctx)}|{fact_type}|{attempt}"
    team = _clean(ctx.recommended_team)
    venue = _clean(ctx.venue)
    direction = _movement_direction(ctx)
    # Slot resolution: legacy slot=team, body slot=body_ref (may be empty for
    # C+D anaphor-less). Empty slot triggers the no-name return path.
    slot = team if name_team else body_ref

    if fact_type == "price_edge":
        clauses = _eligible_price_clauses(ctx)
        if not clauses:
            return None
        base = stable_pick(clauses, key=f"{key}|price_clause")
        if not slot:
            return base
        if "market" in base:
            return f"{base} for {slot}"
        if base.startswith("the number"):
            return f"{base} on {slot}"
        if base.startswith("the quote"):
            return f"{base} on {slot}"
        return f"{base} for {slot}"

    if fact_type == "form_h2h":
        base = stable_pick(FORM_CLAUSES, key=f"{key}|form_clause")
        if not slot:
            return base
        if base == "recent results back the lean":
            return f"recent results back {slot}"
        if base == "form gives this extra weight":
            return f"form gives {slot} extra weight"
        if base == "the form read supports the price":
            return f"the form read supports {slot}"
        if base == "recent form points the right way":
            return f"recent form points toward {slot}"
        if base == "the results profile gives this support":
            return f"the results profile gives {slot} support"
        if base == "form adds a useful push":
            return f"form adds a useful push for {slot}"
        if base == "recent results strengthen the case":
            return f"recent results strengthen the case for {slot}"
        return f"the form angle is doing real work for {slot}"

    if fact_type == "lineup_injury":
        base = stable_pick(INJURY_CLAUSES, key=f"{key}|injury_clause")
        if not slot:
            return base
        if base == "team news has not been fully priced in":
            return f"team news has not been fully priced in for {slot}"
        if base == "the team-news angle adds weight":
            return f"the team-news angle adds weight for {slot}"
        if base == "availability tilts this our way":
            return f"availability tilts this toward {slot}"
        if base == "the injury read supports the price":
            return f"the injury read supports {slot}"
        if base == "team news keeps the value alive":
            return f"team news keeps the value alive for {slot}"
        return f"availability gives {slot} extra appeal"

    if fact_type == "movement":
        if direction == "for":
            base = stable_pick(MOVEMENT_FOR_CLAUSES, key=f"{key}|movement_clause")
            if not slot:
                return base
            if base.endswith("our way"):
                return f"the line is starting to move toward {slot}"
            if base.endswith("the pick"):
                return f"market movement is following {slot}"
            return f"{base} for {slot}"
        if direction == "against":
            base = stable_pick(MOVEMENT_AGAINST_CLAUSES, key=f"{key}|movement_clause")
            if not slot:
                return base
            return f"{base} on {slot}"
        base = stable_pick(MOVEMENT_UNKNOWN_CLAUSES, key=f"{key}|movement_clause")
        if not slot:
            return base
        return f"{base} for {slot}"

    if fact_type == "market_agreement":
        base = stable_pick(MARKET_CLAUSES, key=f"{key}|market_clause")
        count = ctx.bookmaker_count or _mapping_int(_signal_value(ctx, "market_agreement"), "bookmaker_count")
        if not slot:
            if count and count >= 3:
                return f"{count} books line up the same way"
            return base
        if count and count >= 3:
            return f"{count} books give {slot} support"
        if base == "bookmaker breadth backs the lean":
            return f"bookmaker breadth backs {slot}"
        if base == "the broader board supports the price":
            return f"the broader board supports {slot}"
        return f"{base} for {slot}"

    if fact_type == "tipster":
        base = stable_pick(TIPSTER_CLAUSES, key=f"{key}|tipster_clause")
        if not slot:
            return base
        if base == "outside support lines up here":
            return f"outside support lines up behind {slot}"
        if base == "external reads back this side":
            return f"external reads back {slot}"
        return f"{base} for {slot}"

    # DEPRECATED: venue_reference render kept as one-line revert per Phase 4
    # decision — the early return at the top of the function blocks this branch
    # from firing in production, but reinstating venue copy is a single-line
    # delete of that early return. _ = venue silences unused-local lint.
    _ = venue
    if fact_type == "venue_reference" and venue:
        base = stable_pick(VENUE_CLAUSES, key=f"{key}|venue_clause")
        rendered = base.format(venue=venue)
        if not slot:
            return rendered
        if team in rendered:
            return rendered
        return f"{rendered} for {slot}"

    return None


def _secondary_fact_clause(
    ctx: VerdictContext, *, attempt: int, name_team: bool = True, body_ref: str = ""
) -> str | None:
    candidates = [fact for fact in _available_fact_types(ctx) if fact != "price_edge"]
    if not candidates:
        return None
    for fact in _rotated(candidates, key=f"{_base_key(ctx)}|secondary_fact_type|{attempt}"):
        clause = _render_fact_clause(
            ctx, fact, attempt=attempt, name_team=name_team, body_ref=body_ref
        )
        if clause:
            return clause
    return None


def _available_fact_types(ctx: VerdictContext) -> tuple[str, ...]:
    available: list[str] = []
    for fact in FACT_PRIORITY:
        if fact == "form_h2h" and signal_available(ctx, "form_h2h"):
            available.append(fact)
        elif fact == "lineup_injury" and signal_available(ctx, "lineup_injury"):
            available.append(fact)
        elif fact == "movement" and signal_available(ctx, "movement"):
            available.append(fact)
        elif fact == "market_agreement" and signal_available(ctx, "market_agreement"):
            available.append(fact)
        elif fact == "tipster" and signal_available(ctx, "tipster"):
            available.append(fact)
        elif fact == "venue_reference" and _clean(ctx.venue) and _has_signal_fact(ctx) and _recommended_is_home(ctx):
            available.append(fact)
        elif fact == "price_edge" and signal_available(ctx, "price_edge"):
            available.append(fact)
    return tuple(available)


def _has_signal_fact(ctx: VerdictContext) -> bool:
    return any(
        (
            signal_available(ctx, "price_edge"),
            signal_available(ctx, "form_h2h"),
            signal_available(ctx, "lineup_injury"),
            signal_available(ctx, "movement") and bool(_movement_direction(ctx)),
            signal_available(ctx, "market_agreement"),
            signal_available(ctx, "tipster"),
        )
    )


def _recommended_is_home(ctx: VerdictContext) -> bool:
    return _team_match(_clean(ctx.recommended_team), _clean(ctx.home_name))


def _eligible_price_clauses(ctx: VerdictContext) -> tuple[str, ...]:
    if signal_available(ctx, "market_agreement"):
        return PRICE_CLAUSES
    return tuple(clause for clause in PRICE_CLAUSES if "market" not in clause)


def _signal_value(ctx: VerdictContext, name: str) -> Any:
    canonical = ALIASES.get(name, name)
    if canonical in ctx.signals:
        return ctx.signals[canonical]
    for alias, target in ALIASES.items():
        if target == canonical and alias in ctx.signals:
            return ctx.signals[alias]
    return None


def _movement_direction(ctx: VerdictContext) -> str | None:
    raw = _clean(ctx.line_movement_direction)
    if not raw:
        value = _signal_value(ctx, "movement")
        if isinstance(value, Mapping):
            raw = _clean(
                value.get("direction")
                or value.get("line_movement_direction")
                or value.get("movement_direction")
            )
    lowered = raw.lower()
    if not lowered:
        return None
    tokens = set(re.findall(r"[a-z]+", lowered))
    if tokens & NEGATIVE_MOVEMENT:
        return "against"
    if tokens & POSITIVE_MOVEMENT:
        return "for"
    return None


def _price_anchor(ctx: VerdictContext) -> str:
    odds = _odds(ctx)
    bookmaker = _clean(ctx.bookmaker)
    if odds and bookmaker:
        return f"at {odds} with {bookmaker}"
    if odds:
        return f"at {odds}"
    if bookmaker:
        return f"with {bookmaker}"
    return ""


def _action_sentence(ctx: VerdictContext, *, salt: str) -> str:
    options = ACTION_BY_TIER.get(_tier(ctx), ACTION_BY_TIER["bronze"])
    return stable_pick(options, key=f"{_base_key(ctx)}|action_variant|{salt}").format(
        team=_clean(ctx.recommended_team)
    )


def _action_with_price(ctx: VerdictContext) -> str:
    team = _clean(ctx.recommended_team)
    tier = _tier(ctx)
    price = _price_anchor(ctx)
    price_part = f" {price}" if price else ""
    if tier == "diamond":
        return f"back {team}{price_part}, full stake."
    if tier == "gold":
        return f"back {team}{price_part}, standard stake."
    if tier == "silver":
        return f"lean {team}{price_part}, standard stake."
    return f"small lean to {team}{price_part}, light stake."


def _tier(ctx: VerdictContext) -> str:
    tier = _clean(ctx.tier).lower()
    return tier if tier in ACTION_BY_TIER else "bronze"


def _odds(ctx: VerdictContext) -> str:
    if ctx.odds is None:
        return ""
    if isinstance(ctx.odds, float):
        return f"{ctx.odds:.2f}"
    return str(ctx.odds).strip()


def _base_key(ctx: VerdictContext) -> str:
    return f"{ctx.match_key}|{ctx.edge_revision}|{ctx.tier}|{ctx.sport}"


def _stable_index(length: int, *, key: str) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % length


def _rotated(options: Sequence[str], *, key: str) -> tuple[str, ...]:
    if not options:
        return ()
    idx = _stable_index(len(options), key=key)
    return tuple(options[idx:]) + tuple(options[:idx])


def _capitalise(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _team_match(left: str, right: str) -> bool:
    left_norm = _normalise(left)
    right_norm = _normalise(right)
    if not left_norm or not right_norm:
        return False
    return left_norm == right_norm or left_norm in right_norm or right_norm in left_norm


def _contains_team_token(text: str, token: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _banned_errors(text: str, prefix: str, terms: Sequence[str]) -> list[str]:
    errors: list[str] = []
    for term in terms:
        if _contains_phrase(text, term):
            errors.append(f"{prefix}:{term}")
    return errors


def _contains_phrase(text: str, term: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _signal_claim_errors(text: str, ctx: VerdictContext) -> list[str]:
    errors: list[str] = []
    lower = text.lower()

    if _has_any(lower, ("form", "recent results", "results profile", "streak")) and not signal_available(ctx, "form_h2h"):
        errors.append("unsupported_form_claim")
    if _has_any(lower, ("team news", "team-news", "injury", "availability", "absence", "missing")) and not signal_available(ctx, "lineup_injury"):
        errors.append("unsupported_team_news_claim")
    if _has_any(lower, ("line move", "market movement", "the line", "the move", "market shifted", "drift")):
        if not signal_available(ctx, "movement"):
            errors.append("unsupported_movement_claim")
    if _has_any(lower, ("wider market", "broader board", "bookmaker breadth", "books", "market read", "market has not")):
        if not signal_available(ctx, "market_agreement"):
            errors.append("unsupported_market_claim")
    if _has_any(lower, ("outside support", "external reads", "outside view", "tipster")) and not signal_available(ctx, "tipster"):
        errors.append("unsupported_tipster_claim")

    return errors


def _has_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)


def _mapping_int(value: Any, key: str) -> int | None:
    if not isinstance(value, Mapping):
        return None
    raw = value.get(key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
