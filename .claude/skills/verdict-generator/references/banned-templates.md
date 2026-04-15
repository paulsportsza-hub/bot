# Banned Verdict Templates

## B20 — Named coach not in fixture metadata (LOCKED — INV-VERDICT-COACH-FABRICATION-01)

**Rule**: Any verdict that names a manager, coach, or head coach whose name
does NOT appear in `evidence_pack.home_manager` or `evidence_pack.away_manager`
MUST be rejected.

**Origin**: Brentford v Manchester United Gold candidate (15 April 2026).
Generated "Amorim's United are struggling at Old Trafford this season..."
Amorim was NOT the current United manager — hallucinated from training data
(model cutoff ~mid-2025).

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

**Examples of ACCEPTED verdicts**:
- "Arteta's Gunners are in strong form..." (Arteta IS in evidence_pack.home_manager)
- "United are struggling at home..." (no manager named — acceptable)
- "The Blues have won four from five..." (no manager named — acceptable)

**Enforcement**:
- `validate_manager_names()` in `narrative_spec.py` — hard gate
- Wired into `min_verdict_quality()` via `evidence_pack` parameter
- Also checked directly after `_generate_verdict_constrained()` output

---

## B22 — Markdown formatting in verdict text (BUILD-SANITIZER-MARKDOWN-STRIP-01)

**Rule**: Verdict text MUST NOT contain raw markdown formatting. Any `**bold**`,
`__bold__`, `*italic*`, `_italic_`, `` `backtick` ``, `# headers`, `> blockquotes`,
or `- / * bullets` that survive into the final verdict string are a defect.

**Origin**: FORGE-VERDICT-EXEMPLARS-02 candidate #11 (Ospreys v Leinster).
Sonnet emitted `**Signals active**` in the verdict — text landed in the card
unsanitised, corrupting the rendered output.

**Enforcement path** (BUILD-SANITIZER-MARKDOWN-STRIP-01):
1. `_strip_markdown(text)` in `bot.py` — strips all markdown patterns. Applied in
   BOTH `_generate_verdict()` and `_generate_verdict_constrained()` BEFORE
   `_fix_orphan_back()`. Order: markdown strip → orphan-back fix.
2. `validate_no_markdown_leak(verdict)` in `narrative_spec.py` — hard FAIL regex
   `r'\*\*|__|`|^#+\s|^>\s'` checks for any leaked markdown POST-sanitizer.
3. Wired into `min_verdict_quality()` as **Gate 7** — a verdict with residual
   markdown will never reach the card renderer.
4. Contract tests: `tests/contracts/test_sanitizer_markdown_strip_01.py`

**Examples of REJECTED verdicts** (pre-sanitizer):
- `"**Signals active** are doing the heavy lifting here..."`  (`**` leaked)
- `"*Back* the away side at 1.80..."`  (`*` italic leaked)
- `"Back the home side at \`1.85\`"`  (backtick leaked)
- `"> This is a strong pick"` (blockquote leaked)

**Examples of ACCEPTED verdicts** (post-sanitizer):
- `"Signals active are doing the heavy lifting here..."`
- `"Back the away side at 1.80..."`

---

## B28 — Diamond verdict 'At \<price\>' opening prefix (BUILD-VERDICT-RENDER-FIXES-01)

**Rule**: Any Diamond-tier verdict that begins with `At <price>` MUST be rejected.
Diamond verdicts must lead with the pick, context, or read — never the price.

**Regex**: `^At\s+[0-9]+\.[0-9]+`

**Example FAIL**: `"At 1.85, the Reds are the play — they've dominated their last four and the line hasn't moved."`

**Required**: `"The Reds are the play at 1.85 — dominant recent form and an unchanged line. Back the Reds."`

**Rationale**: See exemplars.md rule #8. Diamond is our highest-conviction tier.
Opening with a raw price reads as mechanical and undermines the premium framing.
The pick and its analytical basis must lead. The price is supporting evidence, not the headline.

**Applies to**: Diamond tier only. Gold/Silver/Bronze with 'At 1.XX' openings are acceptable.

**Detection**: `validate_diamond_price_prefix()` in `narrative_spec.py` — tier-conditional hard gate in `min_verdict_quality()`.
