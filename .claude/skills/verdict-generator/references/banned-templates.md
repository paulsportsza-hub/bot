# Banned Verdict Templates

## B20 — Named coach not in fixture metadata (LOCKED — INV-VERDICT-COACH-FABRICATION-01)

**Rule**: Any verdict that names a manager, coach, or head coach whose name
does NOT appear in `evidence_pack.home_manager` or `evidence_pack.away_manager`
MUST be rejected. This includes cases where the field is present but **empty** or
**null** — an empty field means no manager name may be used for that side.

**Origin**: Brentford v Manchester United Gold candidate (15 April 2026).
Generated "Amorim's United are struggling at Old Trafford this season..."
Amorim was NOT the current United manager — hallucinated from training data
(model cutoff ~mid-2025).

**NULL MANAGER CONDITIONAL** (INV-ADV-A-MANAGER-LEAKTHROUGH-01): If
`manager_home` is empty, null, or absent, the LLM MUST NOT name any manager or
coach for the home side — even if it recognises the team from training knowledge.
Training-data knowledge is irrelevant. The evidence pack is the only valid source.
Same rule for `manager_away`.

**Detection patterns**:
- Possessive: `[A-Z][a-z]{2,}'s side/men/team/squad/approach/...`
- Under: `under [A-Z][a-z]{2,}`

**Examples of REJECTED verdicts**:
- "Amorim's United are struggling..." (Amorim not in evidence_pack)
- "Under ten Hag, this side has..." (ten Hag not in evidence_pack)
- "Klopp's Reds have the momentum..." (Klopp not in evidence_pack)
- "Conte's system is built to..." (Conte not in evidence_pack)
- "Mourinho's pragmatism will..." (Mourinho not in evidence_pack)
- "Pochettino's side have turned a corner..." (Pochettino not in evidence_pack)
- "Guardiola's side are the play..." (manager_home is empty — null manager conditional violated)

**Examples of ACCEPTED verdicts**:
- "Arteta's Gunners are in strong form..." (Arteta IS in evidence_pack.home_manager)
- "United are struggling at home..." (no manager named — acceptable)
- "The Blues have won four from five..." (no manager named — acceptable)
- "City are the play." (manager_home is empty — correct, team name used only)

**Enforcement**:
- `validate_manager_names()` in `narrative_spec.py` — hard gate
- Wired into `min_verdict_quality()` via `evidence_pack` parameter
- Also checked directly after `_generate_verdict_constrained()` output
- Prompt rule: NULL MANAGER CONDITIONAL block in both verdict prompts (commit `ba833eb`)

**Cross-ref briefs**: INV-VERDICT-COACH-FABRICATION-01, INV-ADV-A-MANAGER-LEAKTHROUGH-01
(commit `ba833eb`), SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)

---

## B22 — Markdown formatting in verdict text (BUILD-SANITIZER-MARKDOWN-STRIP-01)

**Rule**: Verdict text MUST be plain text only. No markdown formatting of any kind:
no `**bold**`, `__bold__`, `*italic*`, `_italic_`, `` `backtick` ``, `# headers`,
`> blockquotes`, or `- / * bullets` may survive into the final verdict string.

Emphasis must be expressed through word choice and sentence rhythm — not formatting
characters.

**Origin**: FORGE-VERDICT-EXEMPLARS-02 candidate #11 (Ospreys v Leinster).
Sonnet emitted `**Signals active**` in the verdict — text landed in the card
unsanitised, corrupting the rendered output.

**Enforcement path** (BUILD-SANITIZER-MARKDOWN-STRIP-01 + SKILL-UPDATE-VERDICT-GENERATOR-01):
1. Prompt rule: PLAIN TEXT ONLY instruction in both verdict prompts
   (SKILL-UPDATE-VERDICT-GENERATOR-01 — prohibits markdown at generation time)
2. `_strip_markdown(text)` in `bot.py` — strips all markdown patterns. Applied in
   BOTH `_generate_verdict()` and `_generate_verdict_constrained()` BEFORE
   `_fix_orphan_back()`. Order: markdown strip → orphan-back fix.
3. `validate_no_markdown_leak(verdict)` in `narrative_spec.py` — hard FAIL regex
   `r'\*\*|__|`|^#+\s|^>\s'` checks for any leaked markdown POST-sanitizer.
4. Wired into `min_verdict_quality()` as **Gate 7** — a verdict with residual
   markdown will never reach the card renderer.
5. Contract tests: `tests/contracts/test_sanitizer_markdown_strip_01.py`

**Examples of REJECTED verdicts** (pre-sanitizer):
- `"**Signals active** are doing the heavy lifting here..."`  (`**` leaked)
- `"*Back* the away side at 1.80..."`  (`*` italic leaked)
- `"Back the home side at \`1.85\`"`  (backtick leaked)
- `"> This is a strong pick"` (blockquote leaked)

**Examples of ACCEPTED verdicts** (post-sanitizer):
- `"Signals active are doing the heavy lifting here."`
- `"Back the away side at 1.80."`

**Cross-ref briefs**: BUILD-SANITIZER-MARKDOWN-STRIP-01 (commit `6c0d532`),
SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)

---

## B28 — Diamond verdict 'At \<price\>' opening prefix (BUILD-VERDICT-RENDER-FIXES-01)

**Rule**: Any Diamond-tier verdict that begins with `At <price>` MUST be rejected.
Diamond verdicts must use the required price-prefix shape (see B29), not a raw price opener.

**Regex**: `^At\s+[0-9]+\.[0-9]+`

**Example FAIL**: `"At 1.85, the Reds are the play — they've dominated their last four and the line hasn't moved."`

**Rationale**: See exemplars.md rule #8. Diamond is our highest-conviction tier.
Opening with a raw price reads as mechanical and undermines the premium framing.
Diamond verdicts have their own required opener — see B29.

**Applies to**: Diamond tier only. Gold/Silver/Bronze with 'At 1.XX' openings are acceptable.

**Detection**: `validate_diamond_price_prefix()` in `narrative_spec.py` — tier-conditional hard gate in `min_verdict_quality()`.

**Cross-ref briefs**: BUILD-VERDICT-RENDER-FIXES-01 (commit `d52ff9a`),
SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)

---

## B29 — Diamond verdict missing required price-prefix opener (SKILL-UPDATE-VERDICT-GENERATOR-01)

**Rule**: Any Diamond-tier verdict (confidence_tier: MAX) that does NOT open with
the shape `<stake> returns <payout> · Edge confirmed` MUST be rejected.

Diamond verdicts must open with a price-prefix that makes the premium framing tangible:
the implied stake + payout + Edge confirmed marker. The LLM computes a round-number
example from the provided odds.

**Required opener shape**: `<stake> returns <payout> · Edge confirmed`
**Example**: `"R200 returns R330 · Edge confirmed. City to cover."`

**Rejection patterns** (Diamond tier only):
- `"City are the play."` — verdict doesn't open with price-prefix
- `"The Reds are the value here."` — no price-prefix
- `"Back Amakhosi at 1.65 on Betway."` — opens with "Back", not price-prefix
- `"R200 returns R330. City to cover."` — missing `· Edge confirmed` marker

**Accepted**:
- `"R200 returns R330 · Edge confirmed. City to cover."` ✓
- `"R100 returns R165 · Edge confirmed. Amakhosi at home is the call."` ✓

**Applies to**: Diamond tier ONLY (confidence_tier: MAX).
Gold, Silver, and Bronze MUST NOT use this format.

**Detection**: `validate_diamond_price_prefix()` in `narrative_spec.py` — extended to
check for required opener shape on Diamond in addition to the existing "At <price>" ban.

**Cross-ref brief**: SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)
