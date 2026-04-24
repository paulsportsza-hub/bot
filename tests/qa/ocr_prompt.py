"""OCR prompt for Claude vision reads of delivered MzansiEdge cards.

Single-turn, low-temp prompt that asks Claude to return STRICT JSON so the
harness can parse deterministically. The four tier-badge emoji are listed as
the only acceptable `tier_badge` values — anything else is a hallucination
and will be rejected at parse time.
"""
from __future__ import annotations

# Only these four tier-badge emoji are accepted. Anything else → None in OCR.
ALLOWED_TIER_BADGES: tuple[str, ...] = ("💎", "🥇", "🥈", "🥉")


OCR_PROMPT = """You are reading a delivered MzansiEdge betting card screenshot.

Return ONLY a JSON object (no prose, no markdown fences, no commentary) with these exact keys:

{
  "verdict_text": "<full verdict body, whitespace-normalised>",
  "home_team": "<home team label as rendered>",
  "away_team": "<away team label as rendered>",
  "tier_badge": "<one of: 💎 🥇 🥈 🥉  OR  empty string if no tier badge is visible>",
  "button_count": <integer>,
  "button_labels": ["<label>", "..."]
}

Rules:
1. `verdict_text`: extract the VERDICT section body only — everything after the "🏆 VERDICT" / "VERDICT" header and before any footer or card boundary. Collapse internal whitespace to single spaces. Do not include the header word "VERDICT" itself.
2. `home_team` and `away_team`: the two team labels rendered on the card (left = home, right = away). If either label is not visible or blank, return an empty string for that field — NEVER guess, NEVER substitute. Preserve diacritics and punctuation.
3. `tier_badge`: the single tier-badge emoji shown on the card. Only one of {💎, 🥇, 🥈, 🥉} is acceptable. If no tier badge is visible, return an empty string. Do NOT return any other emoji, text label, or description.
4. `button_count`: number of interactive BUTTON elements visible BELOW the card photo (Telegram inline keyboard buttons). If the screenshot shows only the card image with no buttons visible, return 0.
5. `button_labels`: text labels of visible buttons in the same order they appear. If none, return [].
6. Return empty string / 0 / [] for any field you cannot read with confidence. Do NOT invent values.
7. Output must be valid JSON parseable by Python json.loads. No trailing commas. No markdown code fences.
"""

# ── V2 prompt — backward-compatible extension ───────────────────────────────
# OCR_PROMPT is IMMUTABLE (SO #30). Add new prompts as new constants only.
# Switch via config.USE_OCR_V2. Ground-truth suite continues to use OCR_PROMPT (V1).

OCR_PROMPT_V2 = """You are reading a delivered MzansiEdge betting card screenshot.

Return ONLY a JSON object (no prose, no markdown fences, no commentary) with these exact keys:

{
  "verdict_text": "<full verdict body, whitespace-normalised>",
  "home_team": "<home team label as rendered>",
  "away_team": "<away team label as rendered>",
  "tier_badge": "<one of: 💎 🥇 🥈 🥉  OR  empty string if no tier badge is visible>",
  "button_count": <integer>,
  "button_labels": ["<label>", "..."],
  "home_team_visible": <true|false>,
  "away_team_visible": <true|false>,
  "kickoff_visible": <true|false>,
  "league_visible": <true|false>,
  "broadcast_visible": <true|false>,
  "odds_value_visible": <true|false>,
  "bookmaker_name_visible": <true|false>,
  "sections_present": ["<section header text>", "..."],
  "supersport_logo_present": <true|false>,
  "supersport_logo_colour": "<colour description, e.g. 'red', 'white', or empty string if absent>"
}

Rules:
1. `verdict_text`: extract the VERDICT section body only — everything after the "🏆 VERDICT" / "VERDICT" header and before any footer or card boundary. Collapse internal whitespace to single spaces. Do not include the header word "VERDICT" itself.
2. `home_team` and `away_team`: the two team labels rendered on the card. Preserve diacritics and punctuation. If not visible return empty string.
3. `tier_badge`: the single tier-badge emoji shown on the card. Only one of {💎, 🥇, 🥈, 🥉} is acceptable. Return empty string if none visible.
4. `button_count`: number of interactive BUTTON elements visible BELOW the card photo (Telegram inline keyboard buttons).
5. `button_labels`: text labels of visible buttons in order. Empty array if none.
6. `home_team_visible` / `away_team_visible`: true if the respective team name is legibly visible.
7. `kickoff_visible`: true if a kickoff time (e.g. "19:30", "Today 19:30") is visible anywhere on the card.
8. `league_visible`: true if a league or competition name is visible.
9. `broadcast_visible`: true if a broadcast channel (e.g. "SS PSL", "DStv 202", "SuperSport") is visible.
10. `odds_value_visible`: true if at least one decimal odds value (e.g. "1.85", "2.40") is visible.
11. `bookmaker_name_visible`: true if a bookmaker name (e.g. "Betway", "Hollywoodbets", "GBets") is visible.
12. `sections_present`: list of section header texts visible on the card (e.g. "📋 The Setup", "🎯 The Edge").
13. `supersport_logo_present`: true if the SuperSport logo or wordmark is visible anywhere on the card.
14. `supersport_logo_colour`: describe the logo's primary colour ("red", "white", "black") or empty string if logo absent.
15. Return empty string / 0 / [] / false for any field you cannot read with confidence. Do NOT invent values.
16. Output must be valid JSON parseable by Python json.loads. No trailing commas. No markdown code fences.
"""
