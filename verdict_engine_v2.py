from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Mapping, Sequence


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


def _render_candidate(
    ctx: VerdictContext,
    *,
    primary_fact_type: str,
    shape: str,
    attempt: int,
) -> str | None:
    action = _action_sentence(ctx, salt=f"{shape}|{primary_fact_type}|{attempt}")
    action_with_price = _action_with_price(ctx)
    fact_clause = _render_fact_clause(ctx, primary_fact_type, attempt=attempt)
    if not fact_clause:
        return None

    price_anchor = _price_anchor(ctx)
    identity = identity_label(ctx, salt=f"{shape}|{attempt}")
    rendered: str | None

    if shape == "identity_price_fact_action":
        lead = identity
        if price_anchor:
            lead = f"{lead} {price_anchor}"
        rendered = f"{lead} — {fact_clause}. {action}"
    elif shape == "fact_price_action":
        rendered = f"{_capitalise(fact_clause)} — {action_with_price}"
    elif shape == "fact_action":
        rendered = f"{_capitalise(fact_clause)} — {action}"
    elif shape == "price_fact_action":
        if primary_fact_type == "price_edge":
            secondary = _secondary_fact_clause(ctx, attempt=attempt)
            if not secondary:
                return None
            rendered = f"{_capitalise(fact_clause)} and {secondary} — {action}"
        else:
            if not signal_available(ctx, "price_edge"):
                return None
            price_clause = _render_fact_clause(ctx, "price_edge", attempt=attempt)
            rendered = f"{_capitalise(price_clause)} and {fact_clause} — {action}"
    else:
        return None

    return _fit_candidate(rendered, ctx, primary_fact_type=primary_fact_type, attempt=attempt)


def _fit_candidate(
    text: str,
    ctx: VerdictContext,
    *,
    primary_fact_type: str,
    attempt: int,
) -> str | None:
    if len(text) <= 200:
        return text

    action = _action_sentence(ctx, salt=f"compact|{primary_fact_type}|{attempt}")
    fact_clause = _render_fact_clause(ctx, primary_fact_type, attempt=attempt)
    if not fact_clause:
        return None
    compact = f"{_capitalise(fact_clause)} — {action}"
    if len(compact) <= 200:
        return compact
    return None


def _render_fact_clause(ctx: VerdictContext, fact_type: str, *, attempt: int) -> str | None:
    key = f"{_base_key(ctx)}|{fact_type}|{attempt}"
    team = _clean(ctx.recommended_team)
    venue = _clean(ctx.venue)
    direction = _movement_direction(ctx)

    if fact_type == "price_edge":
        clauses = _eligible_price_clauses(ctx)
        if not clauses:
            return None
        base = stable_pick(clauses, key=f"{key}|price_clause")
        if "market" in base:
            return f"{base} for {team}"
        if base.startswith("the number"):
            return f"{base} on {team}"
        if base.startswith("the quote"):
            return f"{base} on {team}"
        return f"{base} for {team}"

    if fact_type == "form_h2h":
        base = stable_pick(FORM_CLAUSES, key=f"{key}|form_clause")
        if base == "recent results back the lean":
            return f"recent results back {team}"
        if base == "form gives this extra weight":
            return f"form gives {team} extra weight"
        if base == "the form read supports the price":
            return f"the form read supports {team}"
        if base == "recent form points the right way":
            return f"recent form points toward {team}"
        if base == "the results profile gives this support":
            return f"the results profile gives {team} support"
        if base == "form adds a useful push":
            return f"form adds a useful push for {team}"
        if base == "recent results strengthen the case":
            return f"recent results strengthen the case for {team}"
        return f"the form angle is doing real work for {team}"

    if fact_type == "lineup_injury":
        base = stable_pick(INJURY_CLAUSES, key=f"{key}|injury_clause")
        if base == "team news has not been fully priced in":
            return f"team news has not been fully priced in for {team}"
        if base == "the team-news angle adds weight":
            return f"the team-news angle adds weight for {team}"
        if base == "availability tilts this our way":
            return f"availability tilts this toward {team}"
        if base == "the injury read supports the price":
            return f"the injury read supports {team}"
        if base == "team news keeps the value alive":
            return f"team news keeps the value alive for {team}"
        return f"availability gives {team} extra appeal"

    if fact_type == "movement":
        if direction == "for":
            base = stable_pick(MOVEMENT_FOR_CLAUSES, key=f"{key}|movement_clause")
            if base.endswith("our way"):
                return f"the line is starting to move toward {team}"
            if base.endswith("the pick"):
                return f"market movement is following {team}"
            return f"{base} for {team}"
        if direction == "against":
            base = stable_pick(MOVEMENT_AGAINST_CLAUSES, key=f"{key}|movement_clause")
            return f"{base} on {team}"
        base = stable_pick(MOVEMENT_UNKNOWN_CLAUSES, key=f"{key}|movement_clause")
        return f"{base} for {team}"

    if fact_type == "market_agreement":
        base = stable_pick(MARKET_CLAUSES, key=f"{key}|market_clause")
        count = ctx.bookmaker_count or _mapping_int(_signal_value(ctx, "market_agreement"), "bookmaker_count")
        if count and count >= 3:
            return f"{count} books give {team} support"
        if base == "bookmaker breadth backs the lean":
            return f"bookmaker breadth backs {team}"
        if base == "the broader board supports the price":
            return f"the broader board supports {team}"
        return f"{base} for {team}"

    if fact_type == "tipster":
        base = stable_pick(TIPSTER_CLAUSES, key=f"{key}|tipster_clause")
        if base == "outside support lines up here":
            return f"outside support lines up behind {team}"
        if base == "external reads back this side":
            return f"external reads back {team}"
        return f"{base} for {team}"

    if fact_type == "venue_reference" and venue:
        base = stable_pick(VENUE_CLAUSES, key=f"{key}|venue_clause")
        rendered = base.format(venue=venue)
        if team in rendered:
            return rendered
        return f"{rendered} for {team}"

    return None


def _secondary_fact_clause(ctx: VerdictContext, *, attempt: int) -> str | None:
    candidates = [fact for fact in _available_fact_types(ctx) if fact != "price_edge"]
    if not candidates:
        return None
    for fact in _rotated(candidates, key=f"{_base_key(ctx)}|secondary_fact_type|{attempt}"):
        clause = _render_fact_clause(ctx, fact, attempt=attempt)
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
