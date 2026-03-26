"""Sport context validators to prevent wrong-sport language in narratives."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SPORT_BANNED_TERMS: dict[str, set[str]] = {
    "cricket": {
        "football",
        "soccer",
        "clean sheet",
        "penalty kick",
        "offside",
        "corner kick",
        "red card",
        "yellow card",
        "goalkeeper",
        "striker",
        "hat-trick goal",
        "free kick",
        "throw-in",
        "scrum",
        "lineout",
        "try",
        "conversion kick",
        "maul",
        "ruck",
    },
    "rugby": {
        "football",
        "soccer",
        "clean sheet",
        "penalty kick",
        "offside trap",
        "corner kick",
        "wicket",
        "innings",
        "run rate",
        "over",
        "bowler",
        "batsman",
        "crease",
        "lbw",
        "stumped",
    },
    "soccer": {
        "wicket",
        "innings",
        "run rate",
        "over rate",
        "bowler",
        "batsman",
        "crease",
        "lbw",
        "stumped",
        "century",
        "scrum",
        "lineout",
        "maul",
        "ruck",
        "try line",
        "conversion kick",
        "drop goal",
        "sin bin",
    },
    "boxing": {
        "football",
        "soccer",
        "clean sheet",
        "wicket",
        "innings",
        "scrum",
        "lineout",
        "offside",
        "corner kick",
    },
    "mma": {
        "football",
        "soccer",
        "clean sheet",
        "wicket",
        "innings",
        "scrum",
        "lineout",
        "offside",
        "corner kick",
    },
}

SPORT_REQUIRED_TERMS: dict[str, set[str]] = {
    "cricket": {"bat", "bowl", "wicket", "run", "over", "innings", "pitch", "crease"},
    "rugby": {
        "try",
        "scrum",
        "lineout",
        "ruck",
        "maul",
        "conversion",
        "penalty",
        "tackle",
    },
    "soccer": {
        "goal",
        "clean sheet",
        "shot",
        "pass",
        "tackle",
        "corner",
        "penalty",
        "offside",
    },
    "boxing": {"round", "knockout", "punch", "ring", "bout", "decision", "belt"},
    "mma": {
        "round",
        "knockout",
        "submission",
        "octagon",
        "bout",
        "decision",
        "takedown",
    },
}


def _compile_term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip())
    escaped = escaped.replace(r"\ ", r"\s+")
    suffix = r"(?:s|es)?" if " " not in term and "-" not in term else ""
    return re.compile(rf"(?<!\w){escaped}{suffix}(?!\w)", re.IGNORECASE)


def _find_term_hits(text: str, terms: set[str]) -> list[str]:
    hits = [term for term in sorted(terms) if _compile_term_pattern(term).search(text)]
    return hits


def validate_sport_text(text: str, sport: str) -> tuple[bool, list[str]]:
    """Check narrative text for banned terms from other sports."""
    sport_lower = sport.lower().strip()
    banned = SPORT_BANNED_TERMS.get(sport_lower, set())
    hits = _find_term_hits(text, banned)
    return (len(hits) == 0, hits)


def validate_sport_relevance(text: str, sport: str) -> tuple[bool, str]:
    """Check whether the text mentions at least one relevant term for the sport."""
    sport_lower = sport.lower().strip()
    required = SPORT_REQUIRED_TERMS.get(sport_lower, set())
    if not required:
        return (True, "")

    for term in sorted(required):
        if _compile_term_pattern(term).search(text):
            return (True, term)
    return (False, "")


def build_programmatic_minimal_breakdown(sport: str, match_summary: str = "") -> str:
    """Return a factual fallback when verified context is unavailable or unsafe."""
    sport_display = sport.capitalize() if sport else "Sport"
    base = f"Limited verified data available for this {sport_display} fixture."
    if match_summary:
        base += f" {match_summary}"
    base += " Odds-based analysis only - no enriched narrative available."
    return base


def safe_generate_breakdown(
    llm_output: str,
    sport: str,
    verified_context: dict[str, Any] | None = None,
    match_summary: str = "",
) -> tuple[str, str]:
    """Validate LLM output and fall back safely when context is absent or contaminated."""
    if verified_context and not verified_context.get("data_available", False):
        logger.warning("No verified data for %s; using programmatic fallback", sport)
        return (
            build_programmatic_minimal_breakdown(sport, match_summary),
            "fallback_no_data",
        )

    is_valid, hits = validate_sport_text(llm_output, sport)
    if not is_valid:
        logger.warning("Sport validation failed for %s; banned terms: %s", sport, hits)
        return (
            build_programmatic_minimal_breakdown(sport, match_summary),
            "fallback_banned",
        )

    return (llm_output, "enriched")
