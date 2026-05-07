#!/usr/bin/env python3
"""Audit active V2 verdict cache rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

import verdict_engine_v2
from scrapers.db_connect import connect_odds_db


ENGINE_VERSION = "v2_microfact"
DEFAULT_DB = "/home/paulsportsza/scrapers/odds.db"
MISSING_COLUMN = "__missing_column__"
METRIC_LABELS = (
    "total rows regenerated",
    "invalid verdict count",
    "fallback shell count",
    "team-integrity failure count",
    "duplicate verdict count",
    "distinct primary clause count",
    "banned term count",
    "gets_the_nod_count",
    "lean_count",
    "is_the_play_count",
    "small_lean_to_count",
    "signal_register_count",
    "team_mention_over_one_count",
    # FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 — venue token gate.
    # Counts rows whose verdict_html carries any stadium/venue token. Audit
    # fails when this is > 0 (verdict copy must read like punter language,
    # not a database dump).
    "venue_token_count",
)

# Tokens that must NEVER surface in a V2 verdict (Phase 4 — venue_reference
# retired). Captures generic markers ("Stadium", "Park", "Bowl"), the famous
# EPL grounds, foreign top-flight grounds, SA PSL grounds, the IPL set, and
# the city-suffix dump pattern that triggered Paul's complaint
# ("Bloemfontein", "Manchester" prefixed by ", ").
#
# FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 Codex P2 round-1 fix:
# coverage broadened (Park, Bowl, St James' Park, FNB, Loftus, Wankhede,
# Ellis, etc.) and matching is case-insensitive — so leaked venue copy can't
# slip past the hard-zero audit gate by case alone.
VENUE_TOKENS = (
    # Generic markers — Stadium is specific enough; bare "Park" / "Bowl"
    # would false-positive on soccer "park the bus" / cricket "bowl first"
    # (Codex P2 round-2). Compound venue names below cover the actual
    # ground-name leakage path.
    "Stadium",
    # EPL famous grounds
    "Old Trafford",
    "Etihad",
    "Anfield",
    "Stamford Bridge",
    "Emirates",
    "St James' Park",
    "Goodison",
    "Selhurst",
    "Tottenham Hotspur",
    # Foreign clubs
    "Camp Nou",
    "Bernabéu",
    "Bernabeu",
    "Wembley",
    "Allianz Arena",
    "Signal Iduna",
    "San Siro",
    # SA PSL grounds
    "FNB Stadium",
    "Loftus Versfeld",
    "Orlando Stadium",
    "Mbombela",
    "Moses Mabhida",
    "Athlone Stadium",
    "Dr. Petrus Molemela",
    # IPL grounds
    "Wankhede",
    "Eden Gardens",
    "Chinnaswamy",
    "Chepauk",
    "Arun Jaitley",
)
# City-suffix dump pattern: ", <Capitalised City>" coming straight after the
# venue. Detected in addition to VENUE_TOKENS so the audit catches whatever
# venue copy snuck in past the rotation gate. Case-insensitive.
VENUE_CITY_SUFFIX_RE = re.compile(
    r",\s+(Manchester|London|Liverpool|Bloemfontein|Soweto|Johannesburg|Pretoria|Durban|Cape\s+Town|Mumbai|Bengaluru|Bangalore|Chennai|Kolkata|Delhi|Hyderabad|Ahmedabad|Lucknow|Jaipur)\b",
    re.IGNORECASE,
)

SPORT_VOCAB_BANS = {
    "soccer": ("powerplay", "wicket", "set-piece", "breakdown", "scrum", "lineout"),
    "cricket": ("anfield", "set-piece", "scrum", "lineout", "midfield"),
    "rugby": ("powerplay", "wicket", "innings", "anfield"),
}

FALLBACK_PATTERNS = (
    "form gives this pick support",
    "market support adds weight",
    "price still supports",
    "edge confirmed",
    "this pick support",
)

SIGNAL_REGISTER_TERMS = (
    "form",
    "recent results",
    "books give",
    "set-piece",
    "powerplay",
    "breakdown",
    "lineout",
    "lineup",
    "injury",
    "absence",
    "missing",
    "movement",
    "line move",
    "market move",
    "venue",
    "old trafford",
    "etihad",
    # `home` is checked only against verdict_html, not generic bet-type labels.
    "home",
    "home advantage",
    "home setting",
    "stadium",
    "matchup",
    "head-to-head",
    "h2h",
    "streak",
    "pace",
    "press",
    "scrum",
    "maul",
    "attack",
    "defence",
    "defense",
    "batting",
    "bowling",
    "spin",
    "pitch",
    "wicket",
    "death overs",
    "new ball",
)

MIN_SIGNAL_REGISTER_RATIO = 0.30
FALLBACK_SHELL_RE = re.compile(
    r"^[^—]*(?:\bat\s+\d+(?:\.\d+)?\b|\bwith\s+[a-z])[^—]*"
    r"—\s*(?:back|lean|small lean to)\s+[^.]+,\s*"
    r"(?:full|standard|light)\s+stake\.\s*$",
    re.IGNORECASE,
)

TEAM_CATALOG = {
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea",
    "Crystal Palace", "Everton", "Fulham", "Liverpool", "Manchester City",
    "Manchester United", "Newcastle", "Nottingham Forest", "Tottenham", "West Ham",
    "Wolves", "Mamelodi Sundowns", "Kaizer Chiefs", "Orlando Pirates", "AmaZulu",
    "Golden Arrows", "Richards Bay", "Polokwane City", "Chippa United",
    "Sekhukhune United", "Marumo Gallants", "TS Galaxy", "Bulls", "Sharks",
    "Stormers", "Lions", "Leinster", "Ospreys", "Scarlets", "Crusaders", "Blues",
    "Delhi Capitals", "Chennai Super Kings", "Sunrisers Hyderabad", "Punjab Kings",
    "Kolkata Knight Riders", "Royal Challengers Bengaluru", "Lucknow Super Giants",
    "Mumbai Indians", "Rajasthan Royals", "Gujarat Titans", "Bangladesh",
    "New Zealand", "Germany", "Austria", "Denmark", "Jersey", "Sunrisers",
}


@dataclass(frozen=True)
class CacheRow:
    match_id: str
    verdict_html: str
    sport: str
    league: str
    bet_type: str
    recommended_team: str
    tips_json: str
    odds_hash: str
    quality_status: str
    status: str
    quarantined: str
    created_at: str
    expires_at: str


def _compile_terms(terms: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    patterns = []
    for term in terms:
        escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
        prefix = r"\b" if term[:1].isalnum() else ""
        suffix = r"\b" if term[-1:].isalnum() else ""
        patterns.append(re.compile(prefix + escaped + suffix, re.IGNORECASE))
    return tuple(patterns)


BANNED_PATTERNS = _compile_terms(
    tuple(verdict_engine_v2.BANNED_TELEMETRY_TERMS)
    + tuple(verdict_engine_v2.BANNED_TIER_COPY)
    + tuple(verdict_engine_v2.BANNED_OVERCLAIMS)
    + tuple(verdict_engine_v2.LIVE_COMMENTARY_TERMS)
)


def _pretty_team(raw: str) -> str:
    fixes = {
        "psg": "PSG",
        "ts": "TS",
        "rcb": "RCB",
    }
    words = []
    for part in raw.replace("_", " ").split():
        words.append(fixes.get(part.lower(), part.capitalize()))
    return " ".join(words).strip()


def teams_from_match_key(match_id: str) -> tuple[str, str]:
    stem = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_id or "")
    if "_vs_" not in stem:
        return "", ""
    home_raw, away_raw = stem.split("_vs_", 1)
    return _pretty_team(home_raw), _pretty_team(away_raw)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _mentions(text: str, team: str) -> bool:
    if not text or not team:
        return False
    haystack = _norm(text)
    needle = _norm(team)
    if needle and re.search(rf"\b{re.escape(needle)}\b", haystack):
        return True
    if len(needle.split()) > 1:
        return False
    return bool(needle and re.search(rf"\b{re.escape(needle)}\b", haystack))


def _known_teams_for_row(match_id: str) -> set[str]:
    """Return team names + nicknames considered "in fixture" for third-team
    detection.

    FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 Codex P2 fix:
    Strategy α puts curated nicknames into body / lead copy ("the Blues" for
    Chelsea, "the Reds" for Liverpool). The TEAM_CATALOG contains shared
    nicknames (e.g., Auckland "Blues") that previously false-positive-flagged
    Chelsea verdicts as third-team references. Including the recommended /
    home / away team's nickname in the allowed set neutralises that.
    """
    home, away = teams_from_match_key(match_id)
    allowed: set[str] = {team for team in (home, away) if team}
    try:
        from narrative_spec import lookup_nickname
        for team in (home, away):
            if not team:
                continue
            nick = lookup_nickname(team).strip()
            if nick:
                allowed.add(nick)
                # Also add the nickname with the leading "the " stripped
                # ("Blues" from "the Blues") so single-word substring matches
                # don't sneak through TEAM_CATALOG checks.
                bare_nick = re.sub(r"^the\s+", "", nick, flags=re.IGNORECASE)
                if bare_nick:
                    allowed.add(bare_nick)
    except ImportError:
        # narrative_spec may not be importable in some sandbox audit invocations
        # (no bot-side deps). Fall back to bare home/away — the worst-case is
        # a noisy third-team flag, never a false negative.
        pass
    return allowed


def _recommended_team_for_row(match_id: str, bet_type: str) -> str:
    home, away = teams_from_match_key(match_id)
    bet_norm = _norm(bet_type)
    if bet_norm in {"home", "home win"}:
        return home
    if bet_norm in {"away", "away win"}:
        return away
    if bet_norm in {"draw", "x"}:
        return ""
    for team in (home, away):
        team_norm = _norm(team)
        if team_norm and (team_norm in bet_norm or bet_norm in team_norm):
            return team
    return ""


def _supported_team_bet_type(bet_type: str) -> bool:
    bet_norm = _norm(bet_type)
    return bool(bet_norm and bet_norm not in {"draw", "x"})


def _team_mention_count(verdict: str, team: str) -> int:
    """Count whole-word occurrences of `team` in `verdict` (case-insensitive).

    FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01 audit gate (≤1× rule).
    Counts every bare-team occurrence regardless of suffix form. ' win'-
    suffixed mentions ('Liverpool win') still match because \\b{team}\\b
    finds the leading 'Liverpool' word boundary inside 'Liverpool win'.
    Mixed legacy shapes (e.g., 'Liverpool win — Back Liverpool') count
    correctly as 2× so the gate trips.
    """
    if not verdict or not team:
        return 0
    haystack = _norm(verdict)
    bare = _norm(team)
    if not bare:
        return 0
    return len(re.findall(rf"\b{re.escape(bare)}\b", haystack))


def _is_identity_lead_shape(verdict: str, team: str) -> bool:
    """Heuristic: identity_price_fact_action shape only.

    Engine output for identity_lead is `lead — body. action.` — i.e., the
    section AFTER the em-dash contains an internal sentence boundary
    (period followed by space + capital letter), distinguishing it from
    fact_action / fact_price_action / price_fact_action which all render
    `body — action.` (single sentence after the em-dash).

    The lead-contains-team check still applies. This dual gate prevents
    false positives like 'Recent results back Liverpool — Back Liverpool…'
    (a fact_action under flag=false / pre-fix mode) being exempted.
    """
    if not verdict or "—" not in verdict or not team:
        return False
    parts = verdict.split("—", 1)
    if len(parts) < 2:
        return False
    lead, after = parts[0].strip(), parts[1].strip()
    if len(lead) > 60:
        return False
    if not _mentions(lead, team):
        return False
    # Identity-lead has 2 sentences after em-dash (body. action.). Other
    # shapes have only 1. Look for an internal period followed by capital.
    if not re.search(r"\.\s+[A-Z]", after):
        return False
    return True


def _third_team_mentions(verdict: str, match_id: str) -> list[str]:
    allowed = {_norm(team) for team in _known_teams_for_row(match_id)}
    hits = []
    for team in TEAM_CATALOG:
        team_norm = _norm(team)
        if not team_norm:
            continue
        if team_norm in allowed:
            continue
        if any(re.search(rf"\b{re.escape(team_norm)}\b", allowed_team) for allowed_team in allowed):
            continue
        if _mentions(verdict, team):
            hits.append(team)
    return hits


def _primary_clause(verdict: str) -> str:
    text = re.sub(r"<[^>]+>", "", verdict or "").strip()
    if "—" in text:
        text = text.split("—", 1)[0]
    elif " - " in text:
        text = text.split(" - ", 1)[0]
    return re.sub(r"\s+", " ", text).strip().lower()


def _optional_column(cols: set[str], col: str) -> str:
    if col in cols:
        return f"COALESCE(nc.{col}, '') AS {col}"
    return f"'{MISSING_COLUMN}' AS {col}"


def _fetch_rows(db_path: str) -> list[CacheRow]:
    conn = connect_odds_db(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(narrative_cache)").fetchall()
        }
        edge_cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(edge_results)").fetchall()
        }
        if "engine_version" not in cols:
            return []
        optional_cols = ",\n                       ".join(
            _optional_column(
                cols,
                col,
            )
            for col in (
                "tips_json",
                "odds_hash",
                "quality_status",
                "status",
                "quarantined",
                "created_at",
                "expires_at",
            )
        )
        latest_filter = ""
        if {"id", "recommended_at"}.issubset(edge_cols):
            latest_filter = """
                   AND NOT EXISTS (
                       SELECT 1
                         FROM edge_results newer
                        WHERE newer.match_key = er.match_key
                          AND newer.result IS NULL
                          AND (
                              COALESCE(newer.recommended_at, '') > COALESCE(er.recommended_at, '')
                              OR (
                                  COALESCE(newer.recommended_at, '') = COALESCE(er.recommended_at, '')
                                  AND newer.id > er.id
                              )
                          )
                   )
            """
        try:
            rows = conn.execute(
                f"""
                SELECT nc.match_id, COALESCE(nc.verdict_html, '') AS verdict_html,
                       COALESCE(er.sport, '') AS sport, COALESCE(er.league, '') AS league,
                       COALESCE(er.bet_type, '') AS bet_type,
                       {optional_cols}
                  FROM narrative_cache nc
                  JOIN edge_results er ON er.match_key = nc.match_id
                 WHERE er.result IS NULL
                   AND nc.engine_version = ?
                   {latest_filter}
                 ORDER BY er.match_date, nc.match_id
                """,
                (ENGINE_VERSION,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "engine_version" not in str(exc).lower():
                raise
            rows = []
    finally:
        conn.close()
    return [
        CacheRow(
            match_id=str(row["match_id"] or ""),
            verdict_html=str(row["verdict_html"] or ""),
            sport=str(row["sport"] or "").lower(),
            league=str(row["league"] or "").lower(),
            bet_type=str(row["bet_type"] or ""),
            recommended_team=_recommended_team_for_row(
                str(row["match_id"] or ""),
                str(row["bet_type"] or ""),
            ),
            tips_json=str(row["tips_json"] or ""),
            odds_hash=str(row["odds_hash"] or ""),
            quality_status=str(row["quality_status"] or ""),
            status=str(row["status"] or ""),
            quarantined=str(row["quarantined"] or ""),
            created_at=str(row["created_at"] or ""),
            expires_at=str(row["expires_at"] or ""),
        )
        for row in rows
    ]


def _compute_current_odds_hash(conn: sqlite3.Connection, match_id: str) -> str:
    try:
        rows = conn.execute(
            "SELECT bookmaker, home_odds, draw_odds, away_odds "
            "FROM odds_latest WHERE match_id = ? ORDER BY bookmaker",
            (match_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return ""
    if not rows:
        return ""
    stable_rows = [tuple(row) for row in rows]
    return hashlib.md5(repr(stable_rows).encode()).hexdigest()


def _metadata_errors(
    row: CacheRow,
    *,
    now: datetime,
    current_odds_hash: str,
) -> list[str]:
    errors: list[str] = []
    for field in (
        "tips_json",
        "odds_hash",
        "quality_status",
        "status",
        "created_at",
        "expires_at",
    ):
        if getattr(row, field) == MISSING_COLUMN:
            errors.append(f"missing_column:{field}")
    if row.status.strip().lower() == "quarantined":
        errors.append("quarantined_status")
    if row.quarantined not in ("", "0", "0.0", MISSING_COLUMN):
        errors.append("quarantined_flag")
    if row.quality_status.strip().lower() in {"quarantined", "skipped_banned_shape"}:
        errors.append("bad_quality_status")
    if not row.tips_json or row.tips_json == MISSING_COLUMN:
        errors.append("missing_tips_json")
    else:
        try:
            parsed = json.loads(row.tips_json)
            if not isinstance(parsed, list):
                errors.append("tips_json_not_list")
        except Exception:
            errors.append("tips_json_invalid")
    if not row.created_at or row.created_at == MISSING_COLUMN:
        errors.append("missing_created_at")
    else:
        try:
            datetime.fromisoformat(row.created_at.replace("Z", "+00:00"))
        except Exception:
            errors.append("created_at_invalid")
    if not row.expires_at or row.expires_at == MISSING_COLUMN:
        errors.append("missing_expires_at")
    else:
        try:
            expires = datetime.fromisoformat(row.expires_at.replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < now:
                errors.append("expired_cache_row")
        except Exception:
            errors.append("expires_at_invalid")
    if not row.odds_hash or row.odds_hash == MISSING_COLUMN:
        errors.append("missing_odds_hash")
    elif current_odds_hash and current_odds_hash != row.odds_hash:
        errors.append("odds_hash_mismatch")
    return errors


def audit_database(db_path: str) -> dict[str, int]:
    rows = _fetch_rows(db_path)
    invalid_rows: set[str] = set()
    fallback_count = 0
    wrong_team_count = 0
    banned_count = 0
    gets_the_nod_count = 0
    lean_count = 0
    is_the_play_count = 0
    small_lean_to_count = 0
    signal_register_count = 0
    team_mention_over_one_count = 0
    venue_token_count = 0
    verdict_to_matches: dict[str, set[str]] = defaultdict(set)
    primary_clauses: list[str] = []
    conn = connect_odds_db(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)

    try:
        for row in rows:
            verdict = row.verdict_html.strip()
            lower = verdict.lower()
            if "gets the nod" in lower:
                gets_the_nod_count += 1
            if "small lean to" in lower:
                small_lean_to_count += 1
            elif "lean " in lower:
                lean_count += 1
            if "is the play" in lower:
                is_the_play_count += 1
            if any(term in lower for term in SIGNAL_REGISTER_TERMS):
                signal_register_count += 1
            current_odds_hash = _compute_current_odds_hash(conn, row.match_id)
            if _metadata_errors(row, now=now, current_odds_hash=current_odds_hash):
                invalid_rows.add(row.match_id)
            if not verdict:
                invalid_rows.add(row.match_id)
            if any(pattern in lower for pattern in FALLBACK_PATTERNS) or FALLBACK_SHELL_RE.search(verdict):
                fallback_count += 1
            banned_hits = sum(1 for pattern in BANNED_PATTERNS if pattern.search(verdict))
            if banned_hits:
                banned_count += banned_hits
                invalid_rows.add(row.match_id)
            sport_hits = [
                term for term in SPORT_VOCAB_BANS.get(row.sport, ())
                if re.search(rf"\b{re.escape(term)}\b", lower)
            ]
            if sport_hits:
                invalid_rows.add(row.match_id)
            team_integrity_failed = bool(
                row.recommended_team and not _mentions(verdict, row.recommended_team)
            )
            if not row.recommended_team and _supported_team_bet_type(row.bet_type):
                team_integrity_failed = True
            third_team_hits = _third_team_mentions(verdict, row.match_id)
            if third_team_hits:
                team_integrity_failed = True
            if team_integrity_failed:
                wrong_team_count += 1
                invalid_rows.add(row.match_id)

            # FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01 — team-mention-count gate.
            # Threshold: ≤1× recommended-team per render. Identity-lead shape may
            # carry 2× (lead + close) and is the documented exception — excluded
            # from the gate. Non-team bets (recommended_team=='') are skipped.
            row_team = row.recommended_team or _recommended_team_for_row(row.match_id, row.bet_type)
            if row_team and _supported_team_bet_type(row.bet_type):
                count = _team_mention_count(verdict, row_team)
                if count > 1 and not _is_identity_lead_shape(verdict, row_team):
                    team_mention_over_one_count += 1
                    invalid_rows.add(row.match_id)

            # FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 — venue gate.
            # Any stadium / venue / city-suffix token in the rendered verdict
            # marks the row invalid. Threshold is hard zero — verdict copy must
            # read like punter language, not a database dump. Case-insensitive
            # match (Codex P2 round-1 fix) so 'stadium', 'STADIUM', 'Stadium'
            # all trip the gate.
            if any(
                re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
                    verdict,
                    re.IGNORECASE,
                )
                for token in VENUE_TOKENS
            ) or VENUE_CITY_SUFFIX_RE.search(verdict):
                venue_token_count += 1
                invalid_rows.add(row.match_id)

            verdict_to_matches[verdict].add(row.match_id)
            clause = _primary_clause(verdict)
            if clause:
                primary_clauses.append(clause)
    finally:
        conn.close()

    duplicate_count = sum(
        len(matches) - 1 for verdict, matches in verdict_to_matches.items()
        if verdict and len(matches) >= 2
    )
    return {
        "total rows regenerated": len(rows),
        "invalid verdict count": len(invalid_rows),
        "fallback shell count": fallback_count,
        "team-integrity failure count": wrong_team_count,
        "duplicate verdict count": duplicate_count,
        "distinct primary clause count": len(set(primary_clauses)),
        "banned term count": banned_count,
        "gets_the_nod_count": gets_the_nod_count,
        "lean_count": lean_count,
        "is_the_play_count": is_the_play_count,
        "small_lean_to_count": small_lean_to_count,
        "signal_register_count": signal_register_count,
        "team_mention_over_one_count": team_mention_over_one_count,
        "venue_token_count": venue_token_count,
    }


def format_metrics(metrics: dict[str, int]) -> str:
    plain = "\n".join(f"{label}: {metrics[label]}" for label in METRIC_LABELS)
    return f"{plain}\n\n```markdown\n{plain}\n```"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit active V2 cache rows")
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()

    metrics = audit_database(args.db)
    print(format_metrics(metrics))
    total_rows = metrics["total rows regenerated"]
    action_shape_count = sum(
        1
        for label in (
            "gets_the_nod_count",
            "lean_count",
            "is_the_play_count",
            "small_lean_to_count",
        )
        if metrics[label] > 0
    )

    if (
        metrics["invalid verdict count"] > 0
        or metrics["fallback shell count"] > 0
        or metrics["banned term count"] > 0
        or metrics["team-integrity failure count"] > 0
        or metrics["duplicate verdict count"] > 0
        or metrics["distinct primary clause count"] < 15
        or (
            total_rows == 0
            or metrics["signal_register_count"] / total_rows < MIN_SIGNAL_REGISTER_RATIO
        )
        or action_shape_count < 2
        or metrics["team_mention_over_one_count"] > 0
        or metrics["venue_token_count"] > 0
    ):
        print("AUDIT FAILED", file=sys.stderr)
        return 1
    print("AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
