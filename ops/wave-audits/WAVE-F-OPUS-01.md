# WAVE-F-OPUS-01 — Canonical lift audit (my_matches + match_detail)

**Date:** 2026-05-01
**Agent:** Opus 4.7 LEAD
**Brief:** `353d9048d73c8197a430ebb18c3f3a36` (P0 — Canonical template lift, replaces WAVE-F-MIN-01)
**Outcome:** Templates already at canonical parity. No code change required.

## Files inspected

| Role | Path | Lines |
|------|------|------|
| Source (canonical) | `static/qa-gallery/canonical/my_matches_canonical.html` | 381 |
| Source (canonical) | `static/qa-gallery/canonical/match_detail_canonical.html` | 541 |
| Destination (prod) | `card_templates/my_matches.html` | 347 |
| Destination (prod) | `card_templates/match_detail.html` | 532 |

## Diff finding

CSS section (between `<style>...</style>`) is **byte-identical** between canonical
and prod for both files:

- `my_matches`: prod CSS = canon CSS = 5 988 chars (identical)
- `match_detail`: prod CSS = canon CSS = 10 732 chars (identical)

All HTML structure (class names, tag tree, layout) is identical. Body-level
diffs are confined to:

1. Header logo block — canonical has the rendered `<img>` only; prod has the
   defensive `{% if header_logo_b64 %}<img>{% else %}<gradient-text-fallback>{% endif %}`
   conditional. The fallback fires only when the logo asset is missing; in
   practice `_logo()` in `card_data_adapters.py` always resolves to a non-empty
   base64 string, so the rendered output matches canonical.
2. Match data section — canonical has 4 hardcoded sample matches (Manchester
   City vs Arsenal, Kaizer Chiefs vs Mamelodi Sundowns, etc.); prod uses
   Jinja2 loops over `edge_matches` and `upcoming_matches`.

## Why a literal `cp` would break production

The canonical files contain zero Jinja2 markers (0 `{{ }}` and 0 `{% %}` in
both files). Overwriting prod with canonical would replace the dynamic
templates with static HTML mockups. Every user would then see hardcoded sample
data ("Manchester City vs Arsenal", "Kaizer Chiefs vs Mamelodi Sundowns")
instead of their real matches.

## Decision

Per AC1's allowance ("byte-for-byte identical … or **functionally equivalent
if template variables differ**") and Step 2 of the brief ("If the diff is
empty, the template is already correct — confirm with visual QA before
concluding"), the prod templates are already canonical-equivalent. No file
overwrite was performed.

The brief's premise that "Both files are still the old pre-canonical version
in production" was tested and is incorrect for these two files: the post-canonical
design (no `.header` border-bottom, fixture-pick text fix) was committed by
WAVE-F-MIN-01 in commit `8e9bff6` and is on `origin/main`. The remaining diff
between canonical and prod is purely the data-substitution noise described
above.

## Visual QA gate

Per SO #38 the producing agent cannot self-certify. A dedicated QA sub-agent
runs Telethon against the live bot, captures rendered My Matches and Match
Detail cards, runs `ocr_card()` and the four content assertions from
`tests/qa/card_assertions.py`. Evidence is filed in the Notion wave report.

## CLAUDE.md updates

None. The audit conclusion is recorded in this file rather than the
constitutional document because it is a wave-specific finding, not a
durable rule.
