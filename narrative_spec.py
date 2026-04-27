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
import json
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path


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
            "huge value", "no-brainer", "high confidence", "confident back",
            "confident stake", "clear edge",
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
            "no supporting indicators from any source",
            "no confirming indicators back it up",
            "treat this as a price-only play",
        ],
    },
    "moderate": {
        "allowed": [
            "mild lean", "slight edge", "numbers suggest",
            "worth considering", "some value here",
            "small-to-standard stake",
        ],
        "banned": [
            "market has this completely wrong", "slam dunk", "lock",
            "huge edge", "no-brainer", "one of the best plays",
            "small stake only",
        ],
    },
    "confident": {
        "allowed": [
            "genuine value", "supported edge", "solid play",
            "numbers and indicators agree", "worth backing",
            "standard stake", "supported by data",
        ],
        "banned": [
            "slam dunk", "lock", "no-brainer", "guaranteed",
            "small stake only", "monitor",
        ],
    },
    "strong": {
        "allowed": [
            "market mispriced", "strong conviction", "premium value",
            "one of the best plays on the card",
            "back with confidence", "standard-to-heavy stake", "strong lean",
        ],
        "banned": [
            "guaranteed", "lock", "no-brainer", "can't lose",
            "small stake only", "monitor",
        ],
    },
}

_SETUP_CONTEXT_MAX_AGE_HOURS = 48.0
_COACH_LOOKUP_CACHE: dict[str, object] | None = None


def _normalise_coach_lookup_name(name: str) -> str:
    """Mirror the scraper-side team-name normaliser for static coach lookups."""
    normalised = str(name or "").lower().strip().replace("_", " ").replace("-", " ")
    for suffix in (" fc", " sc", " cf", " afc"):
        if normalised.endswith(suffix):
            normalised = normalised[: -len(suffix)].strip()
    if normalised.startswith("the "):
        normalised = normalised[4:]
    return normalised


def _load_coach_lookup() -> dict[str, object]:
    """Load the shared scrapers coach table without importing bot config."""
    global _COACH_LOOKUP_CACHE
    if _COACH_LOOKUP_CACHE is not None:
        return _COACH_LOOKUP_CACHE

    scrapers_root = Path(
        os.environ.get("SCRAPERS_ROOT", str(Path(__file__).resolve().parent.parent / "scrapers"))
    )
    coaches_path = scrapers_root / "coaches.json"
    try:
        payload = json.loads(coaches_path.read_text())
        soccer_coaches = payload.get("soccer", {})
        _COACH_LOOKUP_CACHE = soccer_coaches if isinstance(soccer_coaches, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _COACH_LOOKUP_CACHE = {}
    return _COACH_LOOKUP_CACHE


def lookup_coach(team_name: str) -> str:
    """Return static coach name for a team, or empty string when unavailable."""
    normalised = _normalise_coach_lookup_name(team_name)
    if not normalised:
        return ""

    soccer_coaches = _load_coach_lookup()
    entry = soccer_coaches.get(normalised)
    if isinstance(entry, dict):
        return str(entry.get("name") or "")
    if isinstance(entry, str):
        return entry

    for key, value in soccer_coaches.items():
        if normalised in key or key in normalised:
            if isinstance(value, dict):
                return str(value.get("name") or "")
            if isinstance(value, str):
                return value
    return ""


# ── Verdict Quality Gate (BUILD-VERDICT-QUALITY-GATE-01) ──────────────────────

# TODO(INV-VERDICT-GOLD-TRACE-01): calibrate MIN_VERDICT_CHARS from 20-sample
# Sonnet Gold distribution.  Replace 80 with the calibrated value when
# INV-VERDICT-GOLD-TRACE-01 completes.
MIN_VERDICT_CHARS: int = 80  # legacy flat constant — use MIN_VERDICT_CHARS_BY_TIER for new gates

# BUILD-VERDICT-ENRICHMENT-FIX-01: tier-specific length gates
MIN_VERDICT_CHARS_BY_TIER: dict[str, int] = {
    "diamond": 140,
    "gold": 110,
    "silver": 80,
    "bronze": 60,
}

# BUILD-NARRATIVE-VOICE-01: unified target band + hard max (supersedes _VERDICT_MAX_CHARS=200)
# See .claude/skills/verdict-generator/references/tier-bands.md for full table.
VERDICT_TARGET_LOW: int = 140   # soft target — below this logs verdict_suboptimal_length
VERDICT_TARGET_HIGH: int = 200  # soft target upper bound
VERDICT_HARD_MAX: int = 260     # hard reject — prevents box overflow on the card UI
# Regexes that match trivially thin / content-empty verdicts.
# Gate fires if ANY pattern matches the stripped verdict text.
BANNED_TRIVIAL_VERDICT_TEMPLATES: list[re.Pattern] = [
    # "Team at score/odds." — bare name + number, no reasoning
    re.compile(r"^[\w'\u2019\s]+ at \d[\d.]*\.?\s*$", re.IGNORECASE),
    # Single action word + bare subject: "Back Arsenal." / "Lean X."
    re.compile(r"^(?:back|lean|monitor|pass|skip)\s+[\w'\s]+\.?\s*$", re.IGNORECASE),
    # Score-only prediction: "Arsenal 2-1 Chelsea."
    re.compile(r"^[\w'\s]+ \d+-\d+ [\w'\s]+\.?\s*$", re.IGNORECASE),
]

# Analytical vocabulary for word-count gate.
# A verdict with fewer than 3 of these words is content-empty by definition.
# Keep tight — do not add generic English words.
ANALYTICAL_VOCABULARY: frozenset = frozenset({
    # From brief's example list
    "form", "edge", "odds", "value", "injury", "home", "away", "defend", "attack",
    "record", "last", "recent", "goals", "clean", "shots", "run", "unbeaten",
    "pressure", "back", "lean", "expect", "favour", "reckon",
    # Essential betting/analytical terms
    "price", "stake", "signal", "movement", "monitor", "probability",
    "support", "align", "positive", "expected", "speculative",
    "confirming", "exposure", "standard",
})


def analytical_word_count(verdict: str) -> int:
    """Count distinct analytical vocabulary words present in verdict text.

    Uses word-boundary prefix matching so "supported" counts as "support",
    "signals" counts as "signal", "backed" counts as "back", etc.
    """
    lower = verdict.lower()
    return sum(
        1 for word in ANALYTICAL_VOCABULARY
        if re.search(r"\b" + re.escape(word), lower)
    )


# ── FIX-REGRESS-D1-VERDICT-GUARD-01 + FIX-NARRATIVE-META-MARKERS-01 ──────────

# Substrings that only appear in Sonnet's error/apology replies, never in a
# legitimate verdict. Lowercase; checked against lowercased verdict text.
# FIX-NARRATIVE-META-MARKERS-01: extended with data-absence meta-commentary
# patterns observed in pregen.log cascade (i cannot / no form, h2h / etc.)
_LLM_META_MARKERS: tuple[str, ...] = (
    # Tier-validation error replies (original 10)
    "i notice",
    "i understand",
    "confidence_tier",
    "selective",
    "not one of",
    "isn't one of",
    "valid tiers",
    "four valid",
    "valid options",
    "i apologize",
    # LLM refusal phrases (cascade source — escape all existing guards)
    "i cannot",
    "i can't produce",
    # Data-absence meta-commentary (most common cascade pattern in pregen logs)
    "no form, h2h",
    "no form data, h2h",
    "no manager names",
    "also noting",
)


def _reject_llm_meta_strings(verdict: str) -> bool:
    """Return True when the verdict text leaks LLM meta-reply patterns.

    FIX-REGRESS-D1-VERDICT-GUARD-01 + FIX-NARRATIVE-META-MARKERS-01: catches
    Sonnet error-replies about invalid tier values, input-field references,
    apologies, refusals, and data-absence meta-commentary shipping as the
    production verdict. Caller must fall back to the deterministic baseline
    and emit a Sentry breadcrumb `verdict_rejected_llm_meta`.
    """
    if not verdict:
        return False
    low = verdict.lower()
    return any(m in low for m in _LLM_META_MARKERS)


def validate_manager_names(verdict: str, evidence_pack: dict) -> bool:
    """Return True if verdict passes manager name validation.

    INV-VERDICT-COACH-FABRICATION-01: HARD gate.
    Returns False if verdict names a manager/coach not present in evidence_pack.

    Logic:
    - Find possessive manager-name patterns (e.g. "Amorim's side") and
      "under Name" patterns in the verdict text.
    - Check each found last-name (case-insensitive) against evidence_pack
      home_manager and away_manager fields.
    - If at least one evidence manager is populated and a non-matching name is
      found, HARD FAIL.
    - If no evidence managers are populated (both None/empty), no-op (pass).
    """
    home_mgr = (evidence_pack.get("home_manager") or "").strip()
    away_mgr = (evidence_pack.get("away_manager") or "").strip()

    # If no manager data at all, can't validate — pass (no-op)
    if not home_mgr and not away_mgr:
        return True

    # Build set of valid name tokens (case-insensitive)
    valid_names: set[str] = set()
    for mgr in (home_mgr, away_mgr):
        if mgr:
            for token in mgr.split():
                if len(token) >= 3:
                    valid_names.add(token.lower())

    # Known team-adjacent words that are NOT manager names (false-positive guard)
    _TEAM_WORDS = frozenset({
        "united", "city", "spurs", "reds", "gunners", "blues", "hammers",
        "chiefs", "pirates", "sundowns", "galaxy", "celtic", "rovers",
        "wanderers", "hotspur", "forest", "villa", "palace", "everton",
        "burnley", "fulham", "brentford", "bournemouth", "wolves",
        "leicester", "brighton", "newcastle", "southampton", "west",
        "ham", "crystal", "nottingham", "aston",
    })

    # Possessive manager patterns: "Name's side/men/team/..."
    _POSSESSIVE_RE = re.compile(
        r"\b([A-Z][a-z]{2,})[\u2019']s\s+(?:side|men|team|lads|boys|squad|"
        r"approach|style|tactics|formation|setup|plan|system|"
        r"United|City|Spurs|Reds|Gunners|Blues|Hammers|Chiefs|Pirates|"
        r"Sundowns|charges|reign|era|tenure)\b"
    )
    # "under Name" patterns
    _UNDER_RE = re.compile(r"\bunder\s+([A-Z][a-z]{2,})\b")

    found_names: set[str] = set()
    for m in _POSSESSIVE_RE.finditer(verdict):
        candidate = m.group(1).lower()
        if candidate not in _TEAM_WORDS:
            found_names.add(candidate)
    for m in _UNDER_RE.finditer(verdict):
        candidate = m.group(1).lower()
        if candidate not in _TEAM_WORDS:
            found_names.add(candidate)

    if not found_names:
        return True  # No manager references detected

    # Check each found name against valid evidence names
    for name in found_names:
        if name not in valid_names:
            return False  # Unknown manager name — HARD FAIL

    return True


def find_fabricated_manager_names(verdict: str, evidence_pack: dict) -> list[str]:
    """Return list of manager name references in verdict not found in evidence_pack.

    MONITOR-P0-FIX-01: Provides fabricated names for integrity event logging
    at the call site (pregenerate_narratives.py).
    Returns empty list when validation passes or no manager data is available.
    """
    home_mgr = (evidence_pack.get("home_manager") or "").strip()
    away_mgr = (evidence_pack.get("away_manager") or "").strip()
    if not home_mgr and not away_mgr:
        return []

    valid_names: set[str] = set()
    for mgr in (home_mgr, away_mgr):
        if mgr:
            for token in mgr.split():
                if len(token) >= 3:
                    valid_names.add(token.lower())

    _TEAM_WORDS = frozenset({
        "united", "city", "spurs", "reds", "gunners", "blues", "hammers",
        "chiefs", "pirates", "sundowns", "galaxy", "celtic", "rovers",
        "wanderers", "hotspur", "forest", "villa", "palace", "everton",
        "burnley", "fulham", "brentford", "bournemouth", "wolves",
        "leicester", "brighton", "newcastle", "southampton", "west",
        "ham", "crystal", "nottingham", "aston",
    })
    _POSSESSIVE_RE = re.compile(
        r"\b([A-Z][a-z]{2,})[\u2019']s\s+(?:side|men|team|lads|boys|squad|"
        r"approach|style|tactics|formation|setup|plan|system|"
        r"United|City|Spurs|Reds|Gunners|Blues|Hammers|Chiefs|Pirates|"
        r"Sundowns|charges|reign|era|tenure)\b"
    )
    _UNDER_RE = re.compile(r"\bunder\s+([A-Z][a-z]{2,})\b")

    found_names: set[str] = set()
    for m in _POSSESSIVE_RE.finditer(verdict):
        candidate = m.group(1).lower()
        if candidate not in _TEAM_WORDS:
            found_names.add(candidate)
    for m in _UNDER_RE.finditer(verdict):
        candidate = m.group(1).lower()
        if candidate not in _TEAM_WORDS:
            found_names.add(candidate)

    return [name for name in found_names if name not in valid_names]


def check_banned_template(verdict: str) -> int:
    """Return index (0-based) of first matching BANNED_TRIVIAL_VERDICT_TEMPLATES, or -1.

    MONITOR-P0-FIX-01: Provides template ID for banned_template_hit event logging
    at the call site (pregenerate_narratives.py).
    """
    text = verdict.strip()
    for idx, pattern in enumerate(BANNED_TRIVIAL_VERDICT_TEMPLATES):
        if pattern.match(text):
            return idx
    return -1


# BUILD-VERDICT-RENDER-FIXES-01: Diamond price-prefix gate
_DIAMOND_PRICE_PREFIX_RE = re.compile(r'^At\s+[0-9]+\.[0-9]+', re.IGNORECASE)


def validate_diamond_price_prefix(verdict: str, tier: str) -> bool:
    """Return True if verdict passes the Diamond price-prefix gate.

    BUILD-VERDICT-RENDER-FIXES-01: Diamond verdicts MUST NOT open with 'At <price>'.
    Gold/Silver/Bronze: always True (no tier gate).
    Diamond: HARD FAIL if verdict starts with 'At X.XX'.
    """
    if (tier or "").lower() != "diamond":
        return True
    return not bool(_DIAMOND_PRICE_PREFIX_RE.match(verdict.strip()))


_MARKDOWN_LEAK_RE = re.compile(r'\*\*|__|`|^#+\s|^>\s', re.MULTILINE)


def validate_no_markdown_leak(verdict: str) -> bool:
    """BUILD-SANITIZER-MARKDOWN-STRIP-01: Return True if verdict contains no markdown.

    Hard fail if any markdown formatting survives post-sanitizer.
    Checks: bold/italic markers (**/__), backticks (`), headers (#),
    blockquotes (>). Returns False (fail) if any leak detected.
    """
    return not bool(_MARKDOWN_LEAK_RE.search(verdict))


def min_verdict_quality(verdict: str, tier: str = "bronze",
                        evidence_pack: dict | None = None) -> bool:
    """Return True if verdict passes the minimum quality floor.

    BUILD-VERDICT-QUALITY-GATE-01.
    BUILD-VERDICT-ENRICHMENT-FIX-01: accepts tier parameter for tier-specific floors.
    INV-VERDICT-COACH-FABRICATION-01: accepts evidence_pack for manager name validation.

    Rejects verdicts that:
    1. Are shorter than the tier-specific MIN_VERDICT_CHARS_BY_TIER floor.
    2. Are longer than VERDICT_HARD_MAX (260).
    3. Do not end in a sentence terminator (. ! ? …) — BUILD-NARRATIVE-VOICE-01 AC-4.
    4. Match a banned trivial template (content-empty patterns).
    5. Contain fewer than 3 analytical vocabulary words.
    6. Name a manager/coach not present in evidence_pack (hard fail).
    7. Begin with "At <price>" for Diamond tier.
    8. Contain residual markdown formatting (**/__/`/#/>) (hard fail).

    AC-1 contract: min_verdict_quality("Arteta's Gunners at 4.") is False.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    text = verdict.strip()
    _tier_key = (tier or "bronze").lower()
    _floor = MIN_VERDICT_CHARS_BY_TIER.get(_tier_key, MIN_VERDICT_CHARS_BY_TIER["bronze"])
    # Gate 1 — tier-specific minimum character floor
    if len(text) < _floor:
        return False
    # Gate 2 — BUILD-NARRATIVE-VOICE-01: hard max prevents card box overflow
    if len(text) > VERDICT_HARD_MAX:
        return False
    # Gate 3 — BUILD-NARRATIVE-VOICE-01 AC-4: sentence-boundary check
    if text and text[-1] not in ".!?…":
        return False
    # Gate 4 — banned trivial templates
    for pattern in BANNED_TRIVIAL_VERDICT_TEMPLATES:
        if pattern.match(text):
            return False
    # Gate 5 — analytical vocabulary count
    if analytical_word_count(text) < 3:
        return False
    # Gate 6 — INV-VERDICT-COACH-FABRICATION-01: manager name fabrication check
    if evidence_pack is not None:
        if not validate_manager_names(text, evidence_pack):
            return False
    # Gate 7 — BUILD-VERDICT-RENDER-FIXES-01: Diamond price-prefix hard gate
    if not validate_diamond_price_prefix(text, tier):
        return False
    # Gate 8 — BUILD-SANITIZER-MARKDOWN-STRIP-01: markdown leak hard gate
    if not validate_no_markdown_leak(text):
        return False
    # Soft monitoring: verdict passes all gates but is below TARGET band
    if len(text) < VERDICT_TARGET_LOW:
        _log.info(
            "verdict_suboptimal_length: tier=%s, len=%d < target_low=%d",
            _tier_key, len(text), VERDICT_TARGET_LOW,
        )
    return True


def _extract_verdict_text(narrative_html: str) -> str:
    """Extract the plain-text Verdict section from a narrative HTML block.

    Looks for the 🏆 Verdict header and returns the text that follows,
    stripped of HTML tags.  Returns empty string if section not found.
    """
    idx = narrative_html.find("\U0001f3c6")  # 🏆
    if idx == -1:
        return ""
    verdict_section = narrative_html[idx:]
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", "", verdict_section)
    # Remove the header line ("🏆 Verdict — …")
    lines = clean.splitlines()
    body_lines = []
    for i, line in enumerate(lines):
        if i == 0:
            continue  # skip header line
        stripped = line.strip()
        if stripped:
            body_lines.append(stripped)
    return " ".join(body_lines).strip()


def cap_verdict_in_narrative(narrative_html: str) -> str:
    """W91-VALIDATOR-REJECT: Hard safety net — cap the Verdict body in a full
    narrative HTML block at _VERDICT_MAX_CHARS.

    The baseline renderer (`_render_verdict`) always applies `_cap_verdict` on
    every return path, but the W84 Sonnet polish path can produce verdicts up
    to 291 chars that pass `verify_shadow_narrative()` and then fail the final
    length gate in `min_verdict_quality()` — inflating `validator_reject_rate`.

    This helper finds the Verdict section (🏆), extracts the plain-text body,
    caps it via `_cap_verdict` if too long, and rewrites the narrative with
    the capped body while preserving the `🏆 <b>Verdict</b>...` header line.
    The body's inner HTML formatting is intentionally dropped on cap — this
    is a last-resort safety net, not a formatter.

    Returns the narrative unchanged when the verdict body is already within
    the cap or when the 🏆 marker is missing.
    """
    idx = narrative_html.find("\U0001f3c6")  # 🏆
    if idx == -1:
        return narrative_html
    head = narrative_html[:idx]
    tail = narrative_html[idx:]
    newline_pos = tail.find("\n")
    if newline_pos == -1:
        return narrative_html
    header_line = tail[: newline_pos + 1]
    body = tail[newline_pos + 1 :]
    body_plain = re.sub(r"<[^>]+>", "", body).strip()
    if len(body_plain) <= _VERDICT_MAX_CHARS:
        return narrative_html
    capped = _cap_verdict(body_plain)
    return head + header_line + capped


# ── NARRATIVE-ACCURACY-01: Derived Claims Pre-processor ──────────────────────

# CURRENT_STADIUMS: club → current 2025/26 ground name (LIVE DATA INTEGRITY).
# Update immediately on any confirmed ground move — do not wait for next wave.
# Everton moved to Hill Dickinson Stadium in August 2025.
CURRENT_STADIUMS: dict[str, str] = {
    "everton": "Hill Dickinson Stadium",
    "arsenal": "Emirates Stadium",
    "chelsea": "Stamford Bridge",
    "manchester city": "Etihad Stadium",
    "manchester united": "Old Trafford",
    "liverpool": "Anfield",
    "tottenham hotspur": "Tottenham Hotspur Stadium",
    "tottenham": "Tottenham Hotspur Stadium",
    "spurs": "Tottenham Hotspur Stadium",
    "aston villa": "Villa Park",
    "newcastle united": "St James' Park",
    "newcastle": "St James' Park",
    "west ham united": "London Stadium",
    "west ham": "London Stadium",
    "brighton": "Amex Stadium",
    "brentford": "Gtech Community Stadium",
    "fulham": "Craven Cottage",
    "crystal palace": "Selhurst Park",
    "wolverhampton wanderers": "Molineux",
    "wolves": "Molineux",
    "nottingham forest": "City Ground",
    "leicester city": "King Power Stadium",
    "leicester": "King Power Stadium",
    "ipswich town": "Portman Road",
    "ipswich": "Portman Road",
    "southampton": "St Mary's Stadium",
    "bournemouth": "Vitality Stadium",
    "real madrid": "Santiago Bernabéu",
    "barcelona": "Estadi Olímpic Lluís Companys",
    "atletico madrid": "Cívitas Metropolitano",
    "kaizer chiefs": "FNB Stadium",
    "orlando pirates": "Orlando Stadium",
    "mamelodi sundowns": "Loftus Versfeld",
}


def _parse_form_counts(form: str) -> tuple[int, int, int]:
    """Parse form string e.g. 'WWDLD' → (wins, draws, losses)."""
    return form.count("W"), form.count("D"), form.count("L")


def _form_streak(form: str) -> str:
    """Compute current streak from form string (index 0 = most recent)."""
    if not form:
        return ""
    current = form[0]
    count = 1
    for c in form[1:]:
        if c == current:
            count += 1
        else:
            break
    labels = {"W": ("won", "win"), "L": ("lost", "loss"), "D": ("drawn", "draw")}
    verb, noun = labels.get(current, ("", ""))
    if not verb:
        return ""
    if count == 1:
        return f"{verb} last out"
    return f"{verb} {count} in a row"


def _get_stadium(team_name: str) -> str:
    """Return current stadium name for team, or empty string if not known."""
    return CURRENT_STADIUMS.get(team_name.lower().strip(), "")


def _derived_soccer(h: dict, a: dict) -> dict:
    """Pre-compute derived claims for football (soccer) narratives.

    Uses exact field names from match_context_fetcher output.
    """
    h_form = h.get("form", "")
    a_form = a.get("form", "")
    h_w, h_d, h_l = _parse_form_counts(h_form)
    a_w, a_d, a_l = _parse_form_counts(a_form)
    h_name = h.get("name", "")
    a_name = a.get("name", "")
    return {
        "sport": "soccer",
        "home_form_str": h_form,
        "home_wins": h_w,
        "home_draws": h_d,
        "home_losses": h_l,
        "home_streak": _form_streak(h_form),
        "home_games_played": h.get("games_played"),
        "home_points": h.get("points"),
        "home_position": h.get("position"),
        "home_gpg": h.get("goals_per_game"),
        "home_record": h.get("home_record", ""),   # e.g. "W7 D2 L0" (home games)
        "home_stadium": _get_stadium(h_name),
        "home_venue_label": "at home" if h_name else "",
        "away_form_str": a_form,
        "away_wins": a_w,
        "away_draws": a_d,
        "away_losses": a_l,
        "away_streak": _form_streak(a_form),
        "away_games_played": a.get("games_played"),
        "away_points": a.get("points"),
        "away_position": a.get("position"),
        "away_gpg": a.get("goals_per_game"),
        "away_record": a.get("away_record", ""),   # e.g. "W3 D1 L4" (away games)
        "away_stadium": _get_stadium(a_name),
        "away_venue_label": "away from home" if a_name else "",
    }


def _derived_rugby(h: dict, a: dict) -> dict:
    """Pre-compute derived claims for rugby union narratives.

    Uses tries/bonus-points schema. Prohibits football terminology.
    """
    h_form = h.get("form", "")
    a_form = a.get("form", "")
    h_w, h_d, h_l = _parse_form_counts(h_form)
    a_w, a_d, a_l = _parse_form_counts(a_form)
    return {
        "sport": "rugby",
        "home_form_str": h_form,
        "home_wins": h_w,
        "home_draws": h_d,
        "home_losses": h_l,
        "home_streak": _form_streak(h_form),
        "home_games_played": h.get("games_played"),
        "home_points": h.get("points"),
        "home_tries_for": h.get("tries_for"),
        "home_tries_against": h.get("tries_against"),
        "home_bonus_points": h.get("bonus_points"),
        "away_form_str": a_form,
        "away_wins": a_w,
        "away_draws": a_d,
        "away_losses": a_l,
        "away_streak": _form_streak(a_form),
        "away_games_played": a.get("games_played"),
        "away_points": a.get("points"),
        "away_tries_for": a.get("tries_for"),
        "away_tries_against": a.get("tries_against"),
        "away_bonus_points": a.get("bonus_points"),
    }


def _derived_cricket_ipl(h: dict, a: dict) -> dict:
    """Pre-compute derived claims for T20/IPL/SA20 cricket narratives.

    NRR is the primary differentiator. Uses runs/wickets vocabulary.
    """
    h_form = h.get("form", "")
    a_form = a.get("form", "")
    h_w, _h_d, h_l = _parse_form_counts(h_form)
    a_w, _a_d, a_l = _parse_form_counts(a_form)
    return {
        "sport": "cricket_ipl",
        "home_form_str": h_form,
        "home_wins": h_w,
        "home_losses": h_l,
        "home_streak": _form_streak(h_form),
        "home_games_played": h.get("games_played"),
        "home_points": h.get("points"),
        "home_nrr": h.get("nrr"),
        "away_form_str": a_form,
        "away_wins": a_w,
        "away_losses": a_l,
        "away_streak": _form_streak(a_form),
        "away_games_played": a.get("games_played"),
        "away_points": a.get("points"),
        "away_nrr": a.get("nrr"),
    }


def _derived_cricket_test(h: dict, a: dict) -> dict:
    """Pre-compute derived claims for Test cricket narratives.

    Conservative handler for sparse ESPN data. Returns only what is
    explicitly available — does NOT synthesise or invent stats.
    """
    h_form = h.get("form", "")
    a_form = a.get("form", "")
    return {
        "sport": "cricket_test",
        "home_form_str": h_form,
        "home_games_played": h.get("games_played"),
        "home_wins": h.get("wins"),
        "home_losses": h.get("losses"),
        "away_form_str": a_form,
        "away_games_played": a.get("games_played"),
        "away_wins": a.get("wins"),
        "away_losses": a.get("losses"),
    }


def build_derived_claims(h: dict, a: dict, sport: str) -> dict:
    """Pre-compute all derived facts from team context dicts.

    Called BEFORE any LLM generation. Dispatches by sport. The returned
    dict is injected above raw facts with the instruction:
    'Do NOT compute your own counts. Every specific number, streak, or
    venue label MUST appear exactly as written below.'

    Args:
        h: home team dict from ctx_data["home_team"]
        a: away team dict from ctx_data["away_team"]
        sport: "soccer" | "rugby" | "cricket_ipl" | "cricket_test" | other
    """
    if not h and not a:
        return {"sport": sport}
    s = (sport or "").lower()
    if s == "rugby":
        return _derived_rugby(h, a)
    if s in ("cricket_ipl", "sa20", "ipl", "t20", "t20i"):
        return _derived_cricket_ipl(h, a)
    if s == "cricket_test":
        return _derived_cricket_test(h, a)
    # Default: soccer (EPL, PSL, UCL, La Liga etc.)
    return _derived_soccer(h, a)


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
    contradicting_signals: int = 0        # opposing signals tracked for copy discipline
    evidence_class: str = "speculative"   # speculative / lean / supported / conviction
    tone_band: str = "cautious"           # cautious / moderate / confident / strong

    # Risk (code-decided)
    risk_factors: list[str] = field(default_factory=list)
    risk_severity: str = "moderate"       # low / moderate / high

    # Verdict (code-decided — capped by tone band)
    verdict_action: str = ""      # "speculative punt" / "lean" / "back" / "strong back"
    verdict_sizing: str = ""      # "tiny exposure" / "small stake" / "standard stake" / "confident stake" / "standard-to-heavy stake"

    # Edge tier (from edge_rating — used for tier-based language floor)
    edge_tier: str = ""           # "diamond" / "gold" / "silver" / "bronze" / ""

    # Bookmaker coverage
    bookmaker_count: int = 0              # number of SA bookmakers pricing this match

    # Stale/movement context
    stale_minutes: int = 0
    movement_direction: str = "neutral"   # "for" / "against" / "neutral"
    tipster_against: int = 0
    tipster_agrees: bool | None = None
    tipster_available: bool = False
    context_freshness_hours: float | None = None
    context_is_fresh: bool = True

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

    # W84-Q13: Zero or negative EV — no actionable edge, neutral monitor posture
    # Gate only fires when edge_pct is explicitly provided and <= 0
    # VERDICT-FIX: "monitor" avoids explicit PASS language that contradicts tier badges at serve time
    if "edge_pct" in edge_data and ev <= 0:
        return ("speculative", "cautious", "monitor", "monitor")

    def _bucket_from_ev(ev_pct: float) -> int:
        if ev_pct < 2.0:
            return 0
        if ev_pct < 4.0:
            return 1
        if ev_pct < 7.0:
            return 2
        return 3

    def _profile(bucket: int) -> tuple[str, str, str, str]:
        profiles = [
            ("speculative", "cautious", "speculative punt", "tiny exposure"),
            ("lean", "moderate", "lean", "small stake"),
            ("supported", "confident", "back", "standard stake"),
            ("conviction", "strong", "strong back", "confident stake"),
        ]
        return profiles[max(0, min(bucket, len(profiles) - 1))]

    # Penalties degrade effective support
    stale_penalty = 1 if stale >= 360 else 0      # 6+ hours stale
    movement_penalty = 1 if movement == "against" else 0
    effective = max(0, support - stale_penalty - movement_penalty)

    bucket = _bucket_from_ev(ev)
    if effective == 0:
        if ev > 7.0:
            return _profile(2)
        return _profile(0)

    # Fewer confirming signals should always make the posture more conservative.
    if effective <= 1:
        bucket -= 1
    elif effective <= 2 and bucket >= 3:
        bucket -= 1

    # A strong verdict still needs both the EV and the broader support to back it up.
    if bucket >= 3 and (composite < 60 or effective < 3):
        bucket = 2

    # R4-BUILD-03: >7% EV must never render below the standard-stake floor.
    if ev > 7.0 and bucket < 2:
        bucket = 2

    return _profile(bucket)


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
            spec.verdict_sizing = "tiny exposure"
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
    ev = edge_data.get("edge_pct", 0)
    movement = edge_data.get("movement_direction", "neutral")
    tipster_against = edge_data.get("tipster_against", 0)
    outcome = edge_data.get("outcome", "")

    if stale >= 360:
        factors.append(f"Stale price — hasn't updated in {stale // 60}h, could shift before kickoff.")
    # BASELINE-VERDICT-FIX: _zero_confirm text describes "no signals backing a pricing gap" —
    # only appropriate when there IS a positive-EV gap (ev > 0). For baseline_no_edge (ev <= 0)
    # there is no gap to confirm, so this text would duplicate the Verdict's "no edge" message.
    if confirming == 0 and ev > 0:
        _v = _pick(
            f"{edge_data.get('match_key', '')}{edge_data.get('outcome', '')}{sport}",
            3,
        )
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
        # W84-Q9 / RENDER-FIX5: high-entropy seed (match_key + outcome + sport) for diversity
        _v = _pick(
            f"{edge_data.get('match_key', '')}{edge_data.get('outcome', '')}{sport}",
            3,
        )
        _default_factors = [
            "No specific flags on this one — clean risk profile on paper.",
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
    if not league_key:
        return ""
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


def _build_h2h_summary(
    ctx_data: dict | None,
    edge_data: dict | None = None,
    home_name: str = "",
) -> str:
    """Build concise H2H summary, preferring edge_v2 counts when present."""
    edge_data = edge_data or {}
    h2h_total = edge_data.get("h2h_total")
    home_wins = edge_data.get("h2h_a_wins")
    away_wins = edge_data.get("h2h_b_wins")
    draws = edge_data.get("h2h_draws")

    if (isinstance(h2h_total, (int, str, float))
            and isinstance(home_wins, (int, str, float))
            and isinstance(away_wins, (int, str, float))
            and isinstance(draws, (int, str, float))):
        try:
            total_i = int(h2h_total)
            home_i = int(home_wins)
            away_i = int(away_wins)
            draws_i = int(draws)
        except (TypeError, ValueError):
            total_i = home_i = away_i = draws_i = 0
        if total_i > 0 and home_i >= 0 and away_i >= 0 and draws_i >= 0 and (home_i + away_i + draws_i) == total_i:
            prefix = f"{home_name} " if home_name else ""
            return f"{total_i} meetings: {prefix}{home_i}W {draws_i}D {away_i}L".strip()

    if not ctx_data:
        return ""
    h2h = ctx_data.get("head_to_head", [])
    if not h2h:
        return ""

    def _score_pair(match: dict) -> tuple[int | None, int | None]:
        home_score = match.get("home_score")
        away_score = match.get("away_score")
        try:
            if home_score is not None and away_score is not None:
                return int(home_score), int(away_score)
        except (TypeError, ValueError):
            pass
        score = str(match.get("score") or "")
        parsed = re.search(r"(\d+)\s*-\s*(\d+)", score)
        if parsed:
            return int(parsed.group(1)), int(parsed.group(2))
        return None, None

    def _matches_team(label: str, expected: str) -> bool:
        clean_label = re.sub(r"[^a-z0-9]+", " ", str(label or "").lower()).strip()
        clean_expected = re.sub(r"[^a-z0-9]+", " ", str(expected or "").lower()).strip()
        return bool(clean_label and clean_expected and clean_label == clean_expected)

    home_wins = away_wins = draws = 0
    for match in h2h:
        winner = str(match.get("winner") or "").strip()
        if winner.lower() == "draw":
            draws += 1
            continue
        if winner:
            if home_name and _matches_team(winner, home_name):
                home_wins += 1
            else:
                away_wins += 1
            continue

        home_score, away_score = _score_pair(match)
        if home_score is None or away_score is None:
            continue
        if home_score == away_score:
            draws += 1
            continue
        match_home = str(match.get("home") or match.get("home_team") or "")
        match_away = str(match.get("away") or match.get("away_team") or "")
        if home_name and _matches_team(match_home, home_name):
            if home_score > away_score:
                home_wins += 1
            else:
                away_wins += 1
        elif home_name and _matches_team(match_away, home_name):
            if away_score > home_score:
                home_wins += 1
            else:
                away_wins += 1
        elif home_score > away_score:
            home_wins += 1
        else:
            away_wins += 1
    prefix = f"{home_name} " if home_name else ""
    total = home_wins + draws + away_wins
    if total <= 0:
        return ""
    return f"{total} meetings: {prefix}{home_wins}W {draws}D {away_wins}L".strip()


def _parse_context_timestamp(value: str | None) -> datetime | None:
    """Parse context freshness timestamps to UTC datetimes."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_setup_context_freshness_hours(ctx_data: dict | None) -> float | None:
    """Return setup-context age in hours, or None when freshness is unavailable."""
    if not ctx_data or not ctx_data.get("data_available"):
        return None
    freshness_dt = _parse_context_timestamp(ctx_data.get("data_freshness"))
    if freshness_dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - freshness_dt).total_seconds() / 3600.0)


def _is_setup_context_fresh(
    ctx_data: dict | None,
    *,
    freshness_hours: float | None = None,
) -> bool:
    """Only allow form / season-state copy when freshness is explicit and recent."""
    if not ctx_data or not ctx_data.get("data_available"):
        return False
    if freshness_hours is None:
        freshness_hours = _get_setup_context_freshness_hours(ctx_data)
    return freshness_hours is not None and freshness_hours <= _SETUP_CONTEXT_MAX_AGE_HOURS


def _filter_team_setup_context(team: dict, *, fresh: bool) -> dict:
    """Strip stale season-state fields while preserving identity/context basics."""
    if fresh:
        return team
    filtered = dict(team)
    for key in (
        "position",
        "league_position",
        "points",
        "games_played",
        "matches_played",
        "form",
        "record",
        "home_record",
        "away_record",
        "goals_per_game",
        "goal_difference",
        "goals_for",
        "goals_against",
        "conceded_per_game",
        "last_5",
        "last_result",
        "top_scorer",
        "key_players",
    ):
        filtered.pop(key, None)
    return filtered


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
    context_freshness_hours = _get_setup_context_freshness_hours(ctx_data)
    context_is_fresh = _is_setup_context_fresh(
        ctx_data,
        freshness_hours=context_freshness_hours,
    )
    home_setup = _filter_team_setup_context(home, fresh=context_is_fresh)
    away_setup = _filter_team_setup_context(away, fresh=context_is_fresh)

    home_name = home.get("name", edge_data.get("home_team", "Home"))
    away_name = away.get("name", edge_data.get("away_team", "Away"))
    home_setup["coach"] = str(home_setup.get("coach") or lookup_coach(home_name) or "")
    away_setup["coach"] = str(away_setup.get("coach") or lookup_coach(away_name) or "")

    # Evidence classification
    ev_class, tone, verdict_action, verdict_sizing = _classify_evidence(edge_data)

    # Risk factors (code-decided)
    risk_factors = _build_risk_factors(edge_data, ctx_data, sport)
    risk_severity = _assess_risk_severity(risk_factors, edge_data)

    # Parse home/away records for _decide_team_story
    home_rec = _parse_record(home_setup.get("home_record", ""))
    away_rec = _parse_record(away_setup.get("away_record", ""))

    # Build scaffold (reuse W81-SCAFFOLD)
    scaffold = _build_verified_scaffold(ctx_data, edge_data, sport)

    # Verified injuries
    injuries = get_verified_injuries(
        home_name,
        away_name,
        sport=sport,
        league=str(edge_data.get("league") or edge_data.get("league_key") or ""),
    )

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
        competition=_humanise_league(edge_data.get("league") or ""),
        sport=sport,
        home_story_type=_decide_team_story(
            home_setup.get("position"), home_setup.get("points"), home_setup.get("form", ""),
            home_rec, None, home_setup.get("goals_per_game"), is_home=True, sport=sport,
        ),
        away_story_type=_decide_team_story(
            away_setup.get("position"), away_setup.get("points"), away_setup.get("form", ""),
            None, away_rec, away_setup.get("goals_per_game"), is_home=False, sport=sport,
        ),
        home_coach=home_setup.get("coach"),
        away_coach=away_setup.get("coach"),
        home_position=home_setup.get("position"),
        away_position=away_setup.get("position"),
        home_points=home_setup.get("points"),
        away_points=away_setup.get("points"),
        home_form=home_setup.get("form", ""),
        away_form=away_setup.get("form", ""),
        home_last_result="",
        away_last_result="",
        h2h_summary=_build_h2h_summary(ctx_data, edge_data, home_name),
        injuries_home=injuries.get("home", []),
        injuries_away=injuries.get("away", []),
        outcome=edge_data.get("outcome", ""),
        outcome_label=_build_outcome_label(edge_data, home_name, away_name),
        bookmaker=edge_data.get("best_bookmaker", ""),
        odds=edge_data.get("best_odds", 0),
        ev_pct=edge_data.get("edge_pct", 0),
        fair_prob_pct=round(float(fair_prob_raw) * 100, 1) if fair_prob_raw else 0.0,
        composite_score=edge_data.get("composite_score", 0),
        bookmaker_count=edge_data.get("bookmaker_count", 0),
        support_level=edge_data.get("confirming_signals", 0),
        contradicting_signals=edge_data.get("contradicting_signals", 0),
        evidence_class=ev_class,
        tone_band=tone,
        risk_factors=risk_factors,
        risk_severity=risk_severity,
        verdict_action=verdict_action,
        verdict_sizing=verdict_sizing,
        stale_minutes=edge_data.get("stale_minutes", 0),
        movement_direction=edge_data.get("movement_direction", "neutral"),
        tipster_against=edge_data.get("tipster_against", 0),
        tipster_agrees=edge_data.get("tipster_agrees"),
        tipster_available=edge_data.get("tipster_available", False),
        context_freshness_hours=context_freshness_hours,
        context_is_fresh=context_is_fresh,
        scaffold=scaffold,
    )

    # BUILD-GATE-RELAX: Force cautious tone on ALL zero-signal edges — Paul 1 April 2026.
    # No conviction language on zero-signal cards, regardless of EV.
    if spec.support_level == 0:
        spec.tone_band = "cautious"
        if spec.verdict_action in ("back", "strong back"):
            spec.verdict_action = "lean"
        if spec.verdict_sizing in ("standard stake", "confident stake"):
            spec.verdict_sizing = "small stake"

    # Enforce coherence — downgrade if contradictions found
    spec = _enforce_coherence(spec)

    # TONE-BANDS-FIX: Enforce minimum conviction posture per edge tier.
    # Diamond/Gold badges already communicate quality — language must match the badge.
    # Applied AFTER coherence enforcement to override the BUILD-GATE-RELAX floor.
    _tier = (edge_data.get("edge_tier") or "").lower()
    spec.edge_tier = _tier
    if _tier == "diamond":
        # Diamond always uses conviction language — never hedging or speculative posture.
        if spec.tone_band not in ("confident", "strong"):
            spec.tone_band = "confident"
            spec.evidence_class = "supported"
        if spec.verdict_action in ("speculative punt", "monitor"):
            spec.verdict_action = "strong back"
        if spec.verdict_sizing in ("tiny exposure", "small stake"):
            spec.verdict_sizing = "standard-to-heavy stake"
    elif _tier == "gold":
        # Gold never uses hedging language — minimum lean posture.
        if spec.tone_band == "cautious":
            spec.tone_band = "moderate"
            spec.evidence_class = "lean"
        if spec.verdict_action in ("speculative punt", "monitor"):
            spec.verdict_action = "lean"
        if spec.verdict_sizing == "tiny exposure":
            spec.verdict_sizing = "small stake"

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


def _parse_wdl(record) -> tuple[int, int, int]:
    """Parse 'W9 D3 L2' → (9, 3, 2). Returns (0, 0, 0) on failure."""
    # Defensive: accept dicts during transition / stale caches
    if isinstance(record, dict):
        return (int(record.get("wins", 0) or 0),
                int(record.get("draws", 0) or 0),
                int(record.get("losses", 0) or 0))
    if not record:
        return (0, 0, 0)
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


def _support_balance_line(spec: NarrativeSpec) -> str:
    """Return count-aware support wording for Edge/Verdict copy."""
    support = max(0, spec.support_level)
    opposing = max(0, spec.contradicting_signals)
    if support <= 0:
        return "No confirming indicators line up behind this yet."
    if support == 1 and opposing <= 0:
        return "1 supporting signal lines up behind the price."
    if support == 1:
        return f"1 supporting signal backs it, with {opposing} pushing the other way."
    if opposing <= 0:
        return (
            f"{support} supporting indicator{'s' if support != 1 else ''} line up behind the price."
        )
    return (
        f"{support} supporting indicator{'s' if support != 1 else ''} back it, "
        f"with {opposing} pushing the other way."
    )


def _verdict_support_line(spec: NarrativeSpec) -> str:
    """Return shorter count-aware support wording for Verdict copy."""
    support = max(0, spec.support_level)
    opposing = max(0, spec.contradicting_signals)
    if support <= 0:
        return ""
    if opposing <= 0:
        return f"{support} supporting indicator{'s' if support != 1 else ''} sit behind the call."
    return (
        f"{support} supporting indicator{'s' if support != 1 else ''} sit behind it, "
        f"with {opposing} pushing back."
    )


def _build_evidence_clauses(spec: NarrativeSpec) -> str:
    """VERDICT-COHERENCE-FIX: Build match-specific evidence clauses for verdict.

    Three clauses from already-computed data — all deterministic, zero LLM:
    1. EV clause — why this edge is worth looking at
    2. Signal clause — what confirms or doesn't
    3. Risk clause — the one thing most likely to invalidate the edge
    """
    parts: list[str] = []

    # 1. EV clause — the most important addition
    if spec.ev_pct > 0:
        if spec.bookmaker_count >= 2:
            parts.append(f"+{spec.ev_pct:.1f}% EV across {spec.bookmaker_count} bookmakers.")
        else:
            parts.append(f"+{spec.ev_pct:.1f}% EV at current pricing.")

    # 2. Signal clause — describe confirming/contradicting signals
    signal_descs: list[str] = []
    if spec.movement_direction == "for":
        signal_descs.append("market movement confirms")
    if spec.tipster_available and spec.tipster_agrees is True:
        signal_descs.append("tipster consensus agrees")
    if signal_descs:
        parts.append(f"Key signals: {', '.join(signal_descs[:2])}.")
    elif spec.support_level == 0:
        parts.append("No confirming signals — higher variance.")

    # 3. Risk clause — top risk factor (skip default clean-risk phrases)
    _SKIP_RISK = ("clean risk", "nothing obvious", "price and signals are aligned")
    if spec.risk_factors:
        top_risk = spec.risk_factors[0]
        if not any(skip in top_risk.lower() for skip in _SKIP_RISK):
            # Ensure risk clause doesn't end with double period
            risk_text = top_risk.rstrip(".")
            parts.append(f"Main risk: {risk_text}.")

    return " ".join(parts)


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
    pos_ref = f"{ord_pos} in {comp}" if pos is not None else f"moving well in {comp}"
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    if v == 0:
        parts = [f"{name} are in form right now — {pos_ref} and carrying genuine momentum."]
        if f:
            parts.append(f"Form ({f}) says it all.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"Hard to ignore the form of {poss} side — {pos_ref} rather than drifting."]
        if f:
            parts.append(f"A {f} sequence has given them real confidence.")
        if gpg and gpg > 1.5:
            parts.append(f"Scoring at {gpg:.1f} per game right now.")
    else:
        parts = [f"{name} have hit their stride — {pos_ref} and not looking like stopping."]
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
        if pos is not None:
            parts = [f"{name} sit {ord_pos} in {comp}{pts_str} — steady with no strong narrative either way."]
        else:
            parts = [f"{name} come into this without a loud storyline in {comp}, which keeps the read market-first."]
        if f:
            parts.append(f"Form reads {f}.")
        if last:
            parts.append(last)
    elif v == 1:
        parts = [f"There's not much to shout about with {name} right now — {ord_pos}{pts_str} and quietly ticking along."]
        if f:
            parts.append(f"Form ({f}) — steady as she goes.")
    else:
        if pos is not None:
            parts = [f"{poss} side sit {ord_pos} in {comp} — outside both extremes and without a dominant storyline."]
        else:
            parts = [f"{poss} side do not bring an obvious standings story into this {comp} spot, so the match has to be read through the number."]
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
    form_note = _form_outlook(form)
    last = _last_sent(name, last_result)
    inj = _injuries_sent(injuries)
    ord_pos = _pos_phrase(pos)
    venue_note = "at home" if is_home else "away from home"
    if v == 0:
        parts = [f"{name} come into this {venue_note} without a dominant narrative around them."]
        if form_note:
            parts.append(form_note)
        elif pos is not None:
            parts.append(f"They sit {ord_pos} in {comp}, which keeps them in the middle of the wider picture.")
        else:
            parts.append("The read on them is still forming ahead of kickoff.")
    elif v == 1:
        parts = [f"{name} look like one of those sides you assess by the latest run rather than the badge."]
        if form_note:
            parts.append(form_note)
        elif pos is not None:
            parts.append(f"{ord_pos} in {comp} tells you they are competitive without yet defining the season.")
        else:
            parts.append("There is no clear surge or collapse attached to them coming into this fixture.")
    else:
        parts = [f"{name} arrive with enough uncertainty around them to keep this fixture interesting."]
        if form_note:
            parts.append(form_note)
        elif pos is not None:
            parts.append(f"{ord_pos} in {comp} is steady ground, but not a position that settles every question.")
        else:
            parts.append("They enter this one without a clean trend in either direction.")
    if last:
        parts.append(last)
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
    opponent_name: str = "",
) -> str:
    """Select and render a team paragraph based on story type.
    Template selection is MD5-deterministic: same team + opponent always gets same variant.
    D-09: Seeds with both name AND opponent_name so the same team vs different opponents
    produces different descriptions.
    Falls back to 'neutral' for unknown story types.
    """
    variants = _TEAM_TEMPLATES.get(story_type, _TEAM_TEMPLATES["neutral"])
    idx = _pick(name + opponent_name, len(variants))
    fn = variants[idx]
    return fn(name, coach, position, points, form, record, gpg, last_result,
              injuries, competition, sport, is_home)


def _competition_category(comp: str) -> str:
    """W84-Q5: Categorise competition for contextual framing in low-context narratives."""
    c = re.sub(r"[_-]+", " ", comp.lower()).strip()
    if any(w in c for w in ["united rugby championship", "urc", "super rugby", "currie cup", "premiership rugby"]):
        return "club_rugby"
    if any(w in c for w in ["six nations", "rugby championship", "rugby world cup"]):
        return "international"
    if any(w in c for w in ["champions league", "uefa champions", "europa league", "conference league", "continental cup"]):
        return "continental"
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
            f"the stakes shift the tempo and lift the value of cautious outcomes."
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
            f"Without current form data, these {_ft_pl} tend to take their shape from rhythm, territory, "
            f"and which side settles first once the contest gets moving."
        ),
    }
    return _shapes.get(comp_cat, "")


def _form_outlook(form: str) -> str:
    """Turn a form string into a short analyst-style read."""
    f = _form_br(form)
    if not f:
        return ""

    # Single result is not a form run — suppress entirely
    if len(form) < 2:
        return ""

    wins = form.count("W")
    losses = form.count("L")
    draws = form.count("D")
    total = len(form)

    if wins >= 4:
        return f"Form reads {f} — that is a side carrying genuine rhythm."
    if losses >= 4:
        return f"Form reads {f} — too many setbacks to call this stable."
    if wins > losses + 1:
        return f"Form reads {f} — enough to suggest their level is rising."
    if losses > wins + 1:
        return f"Form reads {f} — the shape is still uneven."
    if draws >= 3 and wins <= 1 and losses <= 1:
        return f"Form reads {f} — a run built on tight margins rather than momentum."

    # Short form (2-3 results) — honest about brevity, differentiated by direction
    if total <= 3:
        if wins > losses:
            return f"Form reads {f} — a short run leaning positive."
        elif losses > wins:
            return f"Form reads {f} — a short run that hasn\u2019t settled in their favour yet."
        else:
            return f"Form reads {f} — too early to read a clear trend."

    # Genuine mixed form (4+ results, no dominant pattern)
    return f"Form reads {f} — no clean trend in either direction."


def _render_setup_no_context(spec: NarrativeSpec) -> str:
    """Scene-setting fallback when both teams arrive without usable match context."""
    comp = spec.competition or ""
    comp_note = f" in {comp}" if comp else ""
    h, a = spec.home_name, spec.away_name
    sport = spec.sport or "soccer"

    fixture_type = {
        "soccer": "fixture",
        "rugby": "clash",
        "cricket": "encounter",
        "combat": "bout",
    }.get(sport, "match")
    fixture_type_plural = _plural(fixture_type)

    cat = _competition_category(comp)
    if cat == "league" and "cricket" in sport:
        cat = "cricket"
    elif cat == "league" and ("rugby" in sport or sport in ("urc", "super_rugby")):
        cat = "club_rugby"

    ev = float(spec.ev_pct or 0.0)
    support = max(0, int(spec.support_level or 0))
    odds = float(spec.odds or 0.0)
    composite = float(spec.composite_score or 0.0)

    # FIX-W82-BASELINE-PRICE-TALKING-01: posture_band describes the side's market
    # position in non-pricing language. "competitive price point" was the prior
    # else-branch — replaced with "balanced contest" to keep Setup free of
    # pricing vocabulary. See CLAUDE.md Narrative Generation Pipeline Rule 12.
    posture_band = (
        "short favourite" if odds and odds < 1.8 else
        "clear favourite" if odds and odds < 2.15 else
        "live underdog" if odds and odds >= 3.2 else
        "balanced contest"
    )
    ev_band = (
        "confident" if ev >= 7.0 else
        "cautious" if ev < 2.0 else
        "balanced"
    )
    signal_band = (
        "no_signal" if support == 0 else
        "multi_signal" if support >= 2 else
        "single_signal"
    )
    score_band = (
        "premium" if composite >= 60.0 else
        "solid" if composite >= 52.0 else
        "thin"
    )

    scene_map = {
        "continental": [
            f"{h} vs {a}{comp_note} lands with the slower, more strategic feel these continental {fixture_type_plural} usually bring.",
            f"{h} host {a}{comp_note} in a continental spot that normally rewards control before ambition.",
            f"{h} against {a}{comp_note} looks like the sort of continental tie where structure matters before the game starts to stretch.",
            f"This continental {fixture_type} between {h} and {a}{comp_note} should be read through tempo and control rather than headline noise.",
        ],
        "international": [
            f"{h} vs {a}{comp_note} sits in the kind of international window where management often matters as much as momentum.",
            f"{h} face {a}{comp_note} in an international spot that can stay opaque until the contest itself settles.",
            f"{h} and {a} meet{comp_note} with the usual international variables around selection, travel, and in-game adjustment.",
            f"This international {fixture_type} between {h} and {a}{comp_note} carries more uncertainty around match shape than a routine league date.",
        ],
        "club_rugby": [
            f"{h} vs {a}{comp_note} sets up as a club-rugby contest where territory and set-piece ownership should do the heavy lifting.",
            f"{h} host {a}{comp_note} in a rugby spot that is more likely to turn on exits, pressure, and repeat control than open chaos.",
            f"{h} against {a}{comp_note} has the profile of a rugby {fixture_type} where field-position control can dictate the conversation for long stretches.",
            f"This rugby clash between {h} and {a}{comp_note} looks built around discipline, restarts, and set-piece control before anything flashy arrives.",
            f"{h} against {a}{comp_note} shapes up as a club rugby {fixture_type} where gainline battles and set-piece dominance should determine which side controls the tempo.",
            f"{h} host {a}{comp_note} in a rugby spot likely to hinge on the kicking game — who wins field-position and who pins the opposition in the corners.",
            f"This rugby clash between {h} and {a}{comp_note} may be decided in the final quarter, where bench impact and repeat control after turnovers become the decisive factor.",
            f"{h} vs {a}{comp_note} looks like a contest decided by exits, pressure management, and which side holds its discipline when the scoreboard gets tight.",
        ],
        "cricket": [
            f"{h} vs {a}{comp_note} has the profile of a cricket contest likely to be shaped by conditions and tempo rather than constant swings.",
            f"{h} host {a}{comp_note} in a cricket spot where one controlled phase can matter more than long spells of pressure.",
            f"{h} against {a}{comp_note} reads like the sort of cricket encounter where timing and game management should outrank noise.",
            f"This cricket encounter between {h} and {a}{comp_note} is more about control points and pace-setting than dramatic momentum.",
        ],
        "combat": [
            f"{h} vs {a}{comp_note} looks like a bout where range discipline and stylistic leverage should decide the terms.",
            f"{h} face {a}{comp_note} in a matchup that is likely to hinge on positioning before it hinges on aggression.",
            f"{h} against {a}{comp_note} has the feel of a fight where one side establishing the geometry early could shape everything after that.",
            f"This bout between {h} and {a}{comp_note} reads as a technical matchup first and an emotional one second.",
        ],
        "league": [
            f"{h} vs {a}{comp_note} sits in a familiar league frame, but one that should reveal itself through rhythm before it reveals itself on the scoreboard.",
            f"{h} host {a}{comp_note} in a domestic spot where territory, game pace, and first control tend to matter more than noise around kickoff.",
            f"{h} against {a}{comp_note} looks like the sort of league {fixture_type} that takes shape once one side settles into its preferred tempo.",
            f"This league {fixture_type} between {h} and {a}{comp_note} should be judged through pattern and control before any bigger story gets attached to it.",
        ],
    }
    # FIX-W82-BASELINE-PRICE-TALKING-01: posture_map replaces the prior price_map.
    # All variants describe the analytical posture (signal mix × confidence band)
    # in non-pricing language. Banned vocabulary (price, priced, bookmaker, odds,
    # implied, fair value, expected value, model reads, market architecture) is
    # excluded by construction. See CLAUDE.md Narrative Generation Pipeline Rule 12.
    posture_map = {
        "confident": {
            "no_signal": [
                f"The headline read still leans hard enough toward the {posture_band} to lead with, even without broader supporting context.",
                f"This is still a sharper analytical posture: the indicator profile looks firm enough to lead with confidence, even if external corroboration is thin.",
            ],
            "single_signal": [
                f"There is one confirming indicator on top of the headline read, which keeps the case tighter than most low-context setups allow.",
                f"One supporting signal helps, but the indicator profile still does the heavy lifting on this {posture_band}.",
            ],
            "multi_signal": [
                f"With multiple indicators stacked behind it and a stronger-than-usual analytical lead, this is the sort of {posture_band} that can be stated more cleanly than usual.",
                f"The signal count gives this {posture_band} more authority, so the framing does not need to lean on theatre.",
            ],
        },
        "balanced": {
            "no_signal": [
                f"It still reads as a measured {posture_band} call first, which keeps discipline on the analytical signal rather than on any invented story.",
                f"The angle is mainly in the indicator profile here, so the right tone is measured rather than promotional.",
            ],
            "single_signal": [
                f"The case is respectable rather than emphatic: one supporting signal, a workable read on the {posture_band}, and no need to oversell it.",
                f"There is enough there to keep it live, but not enough to pretend this is a runaway read.",
            ],
            "multi_signal": [
                f"The support stack is real, but the read still belongs in the disciplined bucket rather than the loud one.",
                f"More than one indicator sharpens the view, although this still looks like a controlled read rather than a statement play.",
            ],
        },
        "cautious": {
            "no_signal": [
                f"With no supporting stack and only a narrow analytical lead, this is the kind of {posture_band} that asks for restraint.",
                f"The headline read keeps it on the board, but only just; without supporting indicators, this stays in caution territory rather than conviction territory.",
            ],
            "single_signal": [
                f"There is a hint of support, but the analytical lead is slim enough that this should still be treated carefully.",
                f"One indicator stops it from being purely thin, though not by enough to remove the caution.",
            ],
            "multi_signal": [
                f"Multiple indicators are doing more work than the analytical gap itself, which makes this more about respecting the read than pressing it.",
                f"Multiple signals keep it credible, but the margin is still narrow and should be handled that way.",
            ],
        },
    }
    # FIX-W82-BASELINE-PRICE-TALKING-01: close_map replaces the prior close_map.
    # All variants reframe the closing posture in analytical-signal language.
    # The "premium / solid / thin" axis still describes composite-score band, but
    # without leaking pricing vocabulary into the Setup body.
    close_map = {
        "premium": [
            f"That leaves a premium-grade analytical read on a fixture where the structure matters as much as the names.",
            f"The cleaner angle here is to trust the signal shape and keep the language as composed as the setup.",
            f"The indicator profile here is clean enough to lead with conviction, without embellishment.",
            f"A premium read on a fixture where the analytical signal is the headline, not the supporting cast.",
        ],
        "solid": [
            f"That keeps the focus on execution and analytical discipline rather than on borrowed narrative.",
            f"It is a solid setup for a measured read, with the indicator profile doing enough of the explanatory work.",
            f"A workable, proportionate read — the indicators have done their job and the analytical profile reflects it.",
            f"Solid signal context, no need to overreach — trust the read and stay disciplined.",
        ],
        "thin": [
            f"That is why the setup needs restraint: the frame is usable, but not rich enough for swagger.",
            f"The right read is compact and signal-literate — trust the analytical structure and let it carry the weight.",
            f"Thin context calls for a proportionate play — a measured analytical position without an oversold case behind it.",
            f"The analytical posture here is disciplined: lean on the indicator profile, size conservatively, and stay proportionate.",
            f"A signal-led read is the sharpest call here — what the indicators say matters more than what the surrounding data confirms.",
        ],
    }

    scene_variants = scene_map[cat]
    posture_variants = posture_map[ev_band][signal_band]
    close_variants = close_map[score_band]

    # R7-BUILD-03: Use raw float precision and competition key in seeds to reduce
    # collision rate for same-team rugby fixtures across different leagues/odds.
    # Replacing int-truncated odds/ev with f"{:.4f}" adds per-fixture diversity.
    _odds_str = f"{odds:.4f}"
    _ev_str = f"{ev:.4f}"
    scene = scene_variants[_pick(f"{h}|{a}|{comp}|{_odds_str}|{_ev_str}|scene", len(scene_variants))]
    posture = posture_variants[_pick(f"{h}|{a}|{cat}|{ev_band}|{signal_band}|posture", len(posture_variants))]
    close = close_variants[_pick(f"{h}|{a}|{comp}|{_odds_str}|{_ev_str}|{score_band}|close", len(close_variants))]
    return f"{scene} {posture} {close}"


def _render_setup_bridge(spec: NarrativeSpec) -> str:
    """Light connector for thin context-rich setups."""
    comp_note = f" in {spec.competition}" if spec.competition else ""
    return (
        f"That gives {spec.home_name} vs {spec.away_name}{comp_note} a clear shape before kickoff, "
        f"even if neither side arrives with a completely settled profile."
    )


def _render_setup(spec: NarrativeSpec) -> str:
    """4-8 sentence Setup section from verified NarrativeSpec data.
    OEI pattern: home paragraph → away paragraph → H2H bridge.

    W84-P1E: When no standings/form data available (both neutral, no form),
    produce a compact scene-setting note rather than two thin boilerplate paragraphs.
    """
    # No context — produce compact fixture framing via _render_setup_no_context.
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
        opponent_name=spec.away_name,
    )
    away_para = _render_team_para(
        spec.away_name, spec.away_coach, spec.away_story_type,
        spec.away_position, spec.away_points, spec.away_form,
        spec.away_record, spec.away_gpg, spec.away_last_result,
        spec.injuries_away, spec.competition, spec.sport, is_home=False,
        opponent_name=spec.home_name,
    )
    h2h = _h2h_bridge(spec.h2h_summary, spec.home_name, spec.away_name)
    bridge = ""
    combined_len = len(home_para) + len(away_para)
    if home_para and away_para and not h2h and combined_len < 320:
        bridge = _render_setup_bridge(spec)
    parts = [p for p in [home_para, away_para, bridge, h2h] if p]
    return "\n".join(parts)


def _render_edge(spec: NarrativeSpec) -> str:
    """Edge thesis calibrated to evidence_class. All phrases respect tone_band."""
    bk = spec.bookmaker or "the market"
    odds_str = f"{spec.odds:.2f}" if spec.odds else "?"
    ev_str = f"+{spec.ev_pct:.1f}%" if spec.ev_pct > 0 else f"{spec.ev_pct:.1f}%"
    fp_str = f"{spec.fair_prob_pct:.0f}%" if spec.fair_prob_pct else "?"
    outcome = spec.outcome_label or "this outcome"

    _seed = (spec.home_name or "") + (spec.away_name or "")
    support_line = _support_balance_line(spec)
    tipster_line = ""
    if spec.tipster_available and spec.tipster_agrees is True:
        tipster_line = " Tipster consensus leans the same way."
    elif spec.tipster_available and spec.tipster_agrees is False:
        tipster_line = " Tipster consensus is not on the same side."

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
                f"for this competition type — open mind."
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
                f"{bk} is a shade longer than our line on {outcome}: "
                f"{odds_str} on offer against a {fp_str} fair read ({ev_str}). "
                f"{support_line} Enough there to engage, not enough to get carried away."
                f"{tipster_line}"
            ),
            (
                f"{outcome} is not a huge edge, but {bk}'s {odds_str} is still better than our number. "
                f"{support_line} Fair value sits around {fp_str}, so the play is live without being loud."
                f"{tipster_line}"
            ),
            (
                f"{ev_str} sits on {outcome} because the current {odds_str} at {bk} is still a touch loose "
                f"against our {fp_str} fair line. {support_line} That makes it measured rather than speculative."
                f"{tipster_line}"
            ),
        ]
        return _lean_variants[_v]

    elif spec.evidence_class == "supported":
        _v = _pick(_seed, 3)
        _supp_variants = [
            (
                f"{bk} is still offering more than our line on {outcome}: "
                f"{odds_str} against a {fp_str} fair read ({ev_str}). "
                f"{support_line} That gives the edge a real base without pretending it is spotless."
                f"{tipster_line}"
            ),
            (
                f"The price has room on {outcome}: {bk} sits at {odds_str} while our fair line is closer to {fp_str}. "
                f"{support_line} The case is solid at the current number."
                f"{tipster_line}"
            ),
            (
                f"{ev_str} on {outcome} is not living on the model alone. "
                f"{support_line} With {bk} still at {odds_str} versus a {fp_str} fair line, "
                f"the edge has enough underneath it to be taken seriously."
                f"{tipster_line}"
            ),
        ]
        return _supp_variants[_v]

    else:  # conviction
        _v = _pick(_seed, 3)
        _conv_variants = [
            (
                f"One of the stronger plays today. {support_line} "
                f"{outcome} is {odds_str} with {bk} ({ev_str}). "
                f"Fair probability at {fp_str} — the market looks mispriced here."
                f"{tipster_line}"
            ),
            (
                f"Strong conviction on {outcome}: {ev_str} expected value at {odds_str} ({bk}), "
                f"backed by {support_line.lower()} "
                f"Fair value at {fp_str} — this has the depth of support most edges don't get."
                f"{tipster_line}"
            ),
            (
                f"{support_line} {ev_str} edge on {outcome} at {odds_str} with {bk}, "
                f"fair probability at {fp_str}. Premium value without needing to overstate the picture. "
                f"The market still looks mispriced."
                f"{tipster_line}"
            ),
        ]
        return _conv_variants[_v]


def _render_risk(spec: NarrativeSpec) -> str:
    """Risk section: uncertainty only. Stake posture belongs in Verdict."""
    factors_text = " ".join(spec.risk_factors)
    if spec.risk_severity == "high":
        return f"{factors_text} High-risk profile here — several things can still break against the call.".strip()
    if spec.risk_severity == "low":
        return f"{factors_text} Clean risk profile, but ordinary match variance still applies.".strip()
    return (factors_text.strip() or "Ordinary match uncertainty is the main thing left to respect.").strip()


# ── BUILD-VERDICT-CAP-01: Deterministic verdict fallback cap ───────────────────

# BUILD-NARRATIVE-VOICE-01: raised from 200 to 260 (tier-aware hard max — see VERDICT_HARD_MAX).
# _VERDICT_MAX_CHARS is kept as an alias so existing callers don't break.
_VERDICT_MAX_CHARS = VERDICT_HARD_MAX  # 260
_VERDICT_MIN_CHARS: int = 140


def _cap_verdict(text: str) -> str:
    """BUILD-VERDICT-CAP-01: Hard-cap verdict output at VERDICT_HARD_MAX (260) characters.
    Clips at the last word boundary to avoid mid-word truncation.
    FIX-KICKOFF-RELATIVE-01/D2: clip to cap - 1 before appending "."
    so the final string is always <= cap.
    """
    if len(text) <= _VERDICT_MAX_CHARS:
        return text
    clipped = text[:_VERDICT_MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(".,;")
    return clipped + "."


def _floor_verdict(text: str, spec: NarrativeSpec) -> str:
    """BUILD-VERDICT-FLOOR-01: Ensure verdict reaches _VERDICT_MIN_CHARS characters.

    Appends support count, EV, and signal clauses in priority order. Never adds
    "Main risk:" — risk belongs in its own section. Called before _cap_verdict.
    """
    if len(text) >= _VERDICT_MIN_CHARS:
        return text

    base = text.rstrip().rstrip(".")
    parts = [base]

    # Monitor/pass path: timing clause only, no staking content
    if (getattr(spec, "verdict_action", None) or "") in ("pass", "monitor"):
        parts.append(
            "Check back closer to kickoff — a line shift may unlock value on this one."
        )
        joined = " ".join(parts)
        return joined if joined.endswith(".") else joined + "."

    # Step 1 — support count line (most analytical, lowest char cost)
    support_line = _verdict_support_line(spec)
    if support_line and "supporting indicator" not in text.lower():
        parts.append(support_line.rstrip("."))

    joined = " ".join(parts)
    if len(joined) + 1 >= _VERDICT_MIN_CHARS:
        return joined + "."

    # Step 2 — EV clause (no "Main risk:" — risk belongs in its own section)
    _ev = spec.ev_pct or 0.0
    if _ev > 0:
        _bk_count = getattr(spec, "bookmaker_count", 1) or 1
        if _bk_count >= 2:
            parts.append(f"+{_ev:.1f}% EV across {_bk_count} SA bookmakers")
        else:
            parts.append(f"+{_ev:.1f}% EV at current pricing")

    joined = " ".join(parts)
    if len(joined) + 1 >= _VERDICT_MIN_CHARS:
        return joined + "."

    # Step 3 — signal clause (movement + tipster consensus)
    _sig: list[str] = []
    if (getattr(spec, "movement_direction", "neutral") or "neutral") == "for":
        _sig.append("market movement confirms")
    if getattr(spec, "tipster_agrees", None) is True and getattr(spec, "tipster_available", False):
        _sig.append("tipster consensus agrees")
    if _sig:
        parts.append(f"Key signals: {', '.join(_sig[:2])}")

    joined = " ".join(parts)
    if len(joined) + 1 >= _VERDICT_MIN_CHARS:
        return joined + "."

    # Step 4 — movement fallback when no signals found
    _dir = getattr(spec, "movement_direction", "neutral") or "neutral"
    if _dir == "against":
        parts.append("Monitor the closing line before committing")
    else:
        parts.append("No adverse line movement — price is stable at this number")

    return " ".join(parts) + "."


def _render_verdict(spec: NarrativeSpec) -> str:
    """Verdict capped by tone_band. Never uses phrases banned by tone_band.

    BUILD-VERDICT-CAP-01: All posture variants render ≤ 140 chars with typical inputs.
    Evidence clauses are NOT appended — they bloated verdicts beyond mobile-readable length.
    _cap_verdict() is applied on every return path as a hard safety net.
    """
    outcome = spec.outcome_label or "this outcome"
    odds_str = f"{spec.odds:.2f}" if spec.odds else "?"
    bk = spec.bookmaker or "the market"
    action = spec.verdict_action
    sizing = spec.verdict_sizing

    _seed = (spec.home_name or "") + (spec.away_name or "")

    # R7-BUILD-02: P1-STAKING-FLOOR — EV >= 7% must never render "small"/"tiny" sizing
    if spec.ev_pct >= 7.0 and sizing in ("tiny exposure", "small stake"):
        sizing = "standard stake"

    # The verification layer bans "confident" in rendered copy, so keep the
    # internal sizing label but render a neutral synonym.
    if sizing == "confident stake":
        sizing = "full stake"

    if action in ("pass", "monitor"):
        # W84-Q13 / VERDICT-FIX: Zero/negative EV — neutral monitor posture, no PASS recommendation
        if odds_str != "?" and bk != "the market":
            return _cap_verdict(_floor_verdict(
                f"No confirmed edge on {outcome} at {odds_str} ({bk}). "
                f"Monitor for line movement before committing.",
                spec,
            ))
        return _cap_verdict(_floor_verdict(
            f"No positive expected value at current pricing — "
            f"monitor for line movement until the price improves.",
            spec,
        ))

    if action == "speculative punt":
        _v = _pick(_seed, 4)
        # SIGNAL-FIX-01: Branch on support_level to prevent false "no signal" claims.
        # BUILD-VERDICT-01: Rewritten to SA pundit voice — zero banned phrases.
        if spec.support_level >= 1:
            _sp_variants = [
                (
                    f"Punt on {outcome} at {odds_str} ({bk}) — "
                    f"price gap confirmed. One signal backs it."
                ),
                (
                    f"{outcome} at {odds_str} with {bk} — "
                    f"bookmaker has mispriced this. Worth a punt — one indicator aligns."
                ),
                (
                    f"Price edge confirmed on {outcome} at {odds_str} ({bk}). "
                    f"One signal present — a controlled punt makes sense."
                ),
                (
                    f"{outcome} at {odds_str} ({bk}) — "
                    f"one confirming indicator. Worth a punt at the current price."
                ),
            ]
        else:
            _sp_variants = [
                (
                    f"Price edge on {outcome} at {odds_str} ({bk}). "
                    f"No confirming signal yet — worth a punt at the current number."
                ),
                (
                    f"{outcome} at {odds_str} with {bk} — "
                    f"the number justifies a punt. No signal aligned yet."
                ),
                (
                    f"Value on {outcome} at {odds_str} ({bk}). "
                    f"Price is right for a punt — signals not yet confirmed."
                ),
                (
                    f"{outcome} at {odds_str} ({bk}) — "
                    f"price alone has edge here. Awaiting signal confirmation."
                ),
            ]
        return _cap_verdict(_floor_verdict(_sp_variants[_v], spec))

    elif action == "lean":
        # BUILD-VERDICT-01: SA pundit voice — zero banned phrases, no staking advice.
        _v = _pick(_seed, 4)
        _lean_variants = [
            (
                f"{outcome} at {odds_str} ({bk}) — supported by data, priced with value. "
                f"{_verdict_support_line(spec) or 'Edge confirmed.'}"
            ),
            (
                f"Back {outcome} at {odds_str} with {bk}. "
                f"Supported by data — {_verdict_support_line(spec) or 'edge is there at this number.'}"
            ),
            (
                f"{outcome} at {odds_str} ({bk}) — supported by data. "
                f"{_verdict_support_line(spec) or 'Take it at the current price.'}"
            ),
            (
                f"Take {outcome} at {odds_str} with {bk} — "
                f"supported by data, priced right. {_verdict_support_line(spec) or 'Edge confirmed.'}"
            ),
        ]
        return _cap_verdict(_floor_verdict(_lean_variants[_v], spec))

    elif action == "back":
        # BUILD-VERDICT-01: No staking advice suffix.
        _v = _pick(_seed, 3)
        support_line = _verdict_support_line(spec)
        _back_variants = [
            (
                f"Back {outcome} at {odds_str} with {bk} — "
                f"{support_line or 'the case is there at the current number.'}"
            ),
            (
                f"{outcome} at {odds_str} ({bk}) — backable here. "
                f"{support_line or 'The price justifies the play.'}"
            ),
            (
                f"Green light on {outcome} at {odds_str} ({bk}) — "
                f"supported and priced right."
            ),
        ]
        return _cap_verdict(_floor_verdict(_back_variants[_v], spec))

    else:  # strong back
        # BUILD-VERDICT-01: No staking advice suffix.
        _v = _pick(_seed, 4)
        _strong_variants = [
            (
                f"Strong back on {outcome} at {odds_str} ({bk}) — "
                f"depth of support most edges don't get."
            ),
            (
                f"Back {outcome} at {odds_str} with {bk} with conviction — "
                f"signals, price, model all aligned."
            ),
            (
                f"Premium play: {outcome} at {odds_str} ({bk}). "
                f"Price, signals, model all aligned."
            ),
            (
                f"Back {outcome} at {odds_str} ({bk}) with confidence — "
                f"edge is clear and price is right."
            ),
        ]
        return _cap_verdict(_floor_verdict(_strong_variants[_v], spec))


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
