# Verdict Prompt Template — Manager/Coach Zero-Tolerance Rule

## INV-VERDICT-COACH-FABRICATION-01 (15 April 2026)

### ZERO-TOLERANCE MANAGER RULE (LOCKED)

NEVER name a manager, coach, or head coach unless their name appears verbatim
in `evidence_pack.home_manager` or `evidence_pack.away_manager`.

If the field is null or missing, omit the name entirely and refer to the side
by team name only.

This is a zero-tolerance rule. Violations are hard-rejected by
`validate_manager_names()` in `narrative_spec.py`.

### Origin incident

A Gold candidate for Brentford v Manchester United generated:
> "Amorim's United are struggling at Old Trafford this season..."

Amorim was NOT the current United manager. The model hallucinated from
training data (cutoff ~mid-2025). Paul caught it in rating — it never
published.

### Enforcement layers

1. **Evidence feed**: `pregenerate_narratives.py` passes `home_manager` and
   `away_manager` from `evidence_pack.espn_context` into the `_allowed` dict.
2. **Prompt rule**: The Sonnet system prompt includes a ZERO-TOLERANCE RULE
   paragraph immediately after the `manager_home / manager_away` field
   description.
3. **Validator**: `validate_manager_names()` in `narrative_spec.py` detects
   possessive manager patterns (`Name's side`) and `under Name` patterns,
   cross-references against evidence_pack, and hard-fails on mismatch.
4. **Quality gate**: `min_verdict_quality()` calls `validate_manager_names()`
   when `evidence_pack` is provided.

---

## DIAMOND PRICE-PREFIX RULE (SKILL-UPDATE-VERDICT-GENERATOR-01 — 15 April 2026)

### DIAMOND TIER PRICE-PREFIX (confidence_tier: MAX only)

For **Diamond tier only** (`confidence_tier: MAX`): the verdict MUST open with a
price-prefix in the shape `<stake> returns <payout> · Edge confirmed`.

Use the provided odds to compute a round-number example:
- Odds 1.65 → `R100 returns R165 · Edge confirmed`
- Odds 1.80 → `R100 returns R180 · Edge confirmed`
- Odds 2.30 → `R100 returns R230 · Edge confirmed`

**WRONG Diamond opening (REJECTED)**: `"City are the play at 1.65."`
**RIGHT Diamond opening (ACCEPTED)**: `"R200 returns R330 · Edge confirmed. City to cover."`

Do NOT use this format for Gold, Silver, or Bronze (confidence_tier SOLID/STRONG/MILD).

### Prompt text to inject (both verdict prompts)

> "- DIAMOND TIER PRICE-PREFIX (confidence_tier: MAX only): Your verdict MUST open
>   with a price-prefix in the shape '<stake> returns <payout> · Edge confirmed'.
>   Use the odds to compute a round example (e.g. odds 1.65 → 'R100 returns R165
>   · Edge confirmed'). WRONG Diamond: 'City are the play.' RIGHT Diamond: 'R200
>   returns R330 · Edge confirmed. City to cover.' Do NOT use this format for
>   confidence_tier SOLID, STRONG, or MILD."

### Enforcement

- Sonnet prompt: instruction above in both `_generate_verdict()` and
  `_generate_verdict_constrained()` prompts (this brief)
- Post-process: `validate_diamond_price_prefix()` in `narrative_spec.py` (Gate 6)
- Banned templates: B28 (banned "At <price>" opener), B29 (missing required opener)

---

## MARKDOWN PROHIBITION (SKILL-UPDATE-VERDICT-GENERATOR-01 — 15 April 2026)

### PLAIN TEXT ONLY RULE (LOCKED)

Verdict text must be plain text. No markdown formatting characters of any kind.
Emphasis is expressed through word choice and sentence rhythm — not formatting.

**Prohibited**:
- `**bold**` or `__bold__`
- `*italic*` or `_italic_`
- `` `backtick` ``
- `# headers`
- `> blockquotes`
- Leading `- ` or `* ` as bullets

### Prompt text to inject (both verdict prompts, adjacent to NULL MANAGER CONDITIONAL)

> "PLAIN TEXT ONLY: Write plain text only. No markdown formatting. No asterisks
>   around words (**bold** or *italic*), no backticks, no # headers, no > blockquotes,
>   no leading hyphens or asterisks as bullets. If you want to emphasise, use word
>   choice and sentence rhythm — not formatting."

### Enforcement

- Sonnet prompt: PLAIN TEXT ONLY instruction in both verdict prompts (this brief)
- `_strip_markdown()` in `bot.py` — post-process step 1 (commit `6c0d532`)
- `validate_no_markdown_leak()` in `narrative_spec.py` — Gate 7 (commit `6c0d532`)
- Contract tests: `tests/contracts/test_sanitizer_markdown_strip_01.py`
- Banned template: B22
