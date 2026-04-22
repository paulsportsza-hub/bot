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
