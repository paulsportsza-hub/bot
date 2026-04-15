# Verdict Generator Skill — Agent Reference

## Purpose

Governs the production verdict text on every MzansiEdge edge card.
Two runtime paths:

- `_generate_verdict(tip, verified)` — live flow (called in `_enrich_tip_for_card`)
- `_generate_verdict_constrained(spec, allowed_data)` — pre-generation flow (called in
  `pregenerate_narratives._generate_one()`)

Both paths use the same Sonnet prompt + identical post-process pipeline.
The prompt template is the canonical reference for all new rule additions:
`.claude/skills/verdict-generator/assets/verdict-prompt-template.md`

Rejected pattern catalogue: `.claude/skills/verdict-generator/references/banned-templates.md`

---

## Hard Gates (2026-04-15)

Six rules locked on 2026-04-15 and merged under tag
`pre-launch-verdict-stack-2026-04-15`. Any verdict failing one or more of these
gates is hard-rejected — `min_verdict_quality()` in `narrative_spec.py` returns
`False` and the deterministic baseline from `_render_verdict(spec)` is served instead.

### HG-1 — NULL MANAGER CONDITIONAL

**Rule:** If `home_manager` / `away_manager` is empty, null, or missing from the
evidence pack, the verdict MUST NOT name any manager, coach, or head coach for that
side. Refer to the side by team name or nickname only.

This applies even when the LLM recognises the team and believes it knows the manager
from training knowledge. Training-data knowledge is **irrelevant** — the evidence pack
is the only valid source.

**Origin brief:** INV-ADV-A-MANAGER-LEAKTHROUGH-01 / commit `ba833eb`
**Cross-ref brief:** SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)

**Enforcement:**
- Sonnet prompt: NULL MANAGER CONDITIONAL block in both verdict prompts (`ba833eb`)
- Post-process: `validate_manager_names()` in `narrative_spec.py` (Gate 5 of
  `min_verdict_quality()`)
- Banned template: B20

---

### HG-2 — DIAMOND PRICE-PREFIX SHAPE

**Rule:** Diamond-tier verdicts (confidence_tier: MAX) MUST open with the price-prefix
shape `<stake> returns <payout> · Edge confirmed`.

Example: `R200 returns R330 · Edge confirmed. City to cover.`

The LLM computes a round-number stake from the provided odds
(e.g. odds 1.65 → `R100 returns R165 · Edge confirmed`).

**WRONG (rejected):** `"City are the play at 1.65."`
**RIGHT (accepted):** `"R200 returns R330 · Edge confirmed. City to cover."`

Do NOT use this format for Gold, Silver, or Bronze (confidence_tier SOLID/STRONG/MILD).

**Origin:** Pre-launch verdict quality review + BUILD-VERDICT-RENDER-FIXES-01
**Cross-ref brief:** SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15) / commit `d52ff9a`

**Enforcement:**
- Sonnet prompt: DIAMOND TIER PRICE-PREFIX instruction in both verdict prompts
  (SKILL-UPDATE-VERDICT-GENERATOR-01)
- Post-process: `validate_diamond_price_prefix()` in `narrative_spec.py` (Gate 6 of
  `min_verdict_quality()`)
- Banned templates: B28 (banned "At \<price\>" opener), B29 (missing required opener)

---

### HG-3 — ORPHAN BACK-LINE

**Rule:** A standalone `"Back X."` sentence MUST be joined to the preceding sentence
with an em dash, not left as a dangling fragment. If joining would exceed the character
budget, the orphan is stripped entirely.

**Origin brief:** BUILD-VERDICT-RENDER-FIXES-01 / commit `d52ff9a`

**Enforcement:**
- `_fix_orphan_back()` in `bot.py` — applied as step 2 of the post-process pipeline
  (after markdown strip)

---

### HG-4 — MARKDOWN LEAK

**Rule:** Verdict text MUST be plain text only. No markdown formatting:

- No `**bold**` or `__bold__`
- No `*italic*` or `_italic_`
- No `` `backtick` ``
- No `# headers`
- No `> blockquotes`
- No leading `- ` or `* ` bullets

Emphasis is expressed through word choice and sentence rhythm, not formatting characters.

**Origin brief:** BUILD-SANITIZER-MARKDOWN-STRIP-01 / commit `6c0d532`
**Cross-ref brief:** SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)

**Enforcement:**
- Sonnet prompt: PLAIN TEXT ONLY rule in both verdict prompts
  (SKILL-UPDATE-VERDICT-GENERATOR-01)
- Post-process step 1: `_strip_markdown()` in `bot.py` — strips all markdown patterns
- Post-process step 5: `validate_no_markdown_leak()` in `narrative_spec.py` (Gate 7 of
  `min_verdict_quality()`)
- Contract tests: `tests/contracts/test_sanitizer_markdown_strip_01.py`
- Banned template: B22

---

### HG-5 — COACHES.JSON FRESHNESS

**Rule:** Any verdict that names a manager must have that name validated against
`data/coaches.json` (Tier 1 — manually curated). Entries older than 7 days
(`last_verified` field) trigger an **Arbiter caution flag** even if the name is
technically correct.

**File:** `bot/data/coaches.json` — 42 soccer teams (all 20 EPL, full PSL, CL, La Liga)
**Freshness threshold:** 7 days
**Update cadence:** Must be refreshed after every confirmed manager change

Model training-data knowledge of who manages a team is explicitly unreliable — the
coaches.json file was introduced after discovering 7 stale entries in the API cache
(Amorim→Carrick, Maresca→Rosenior, Postecoglou→De Zerbi, Nabi→Ben Youssef,
Ancelotti→Arbeloa, Inzaghi→Chivu).

**Origin brief:** INV-COACHES-JSON-AUDIT-01 / commit `7169dcd`
**Cross-ref brief:** SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)

**Enforcement:**
- `narrative_integrity_monitor.py` — `FRESHNESS_CHECK()` function
- Data priority: Tier 1 (coaches.json) > Tier 2 (API cache) > Tier 3 (API live fetch)

---

### HG-6 — GATE ORDERING

**Rule:** The post-process pipeline MUST execute in this exact order. Deviating from
the order can cause downstream gates to operate on unclean text.

**Origin brief:** SKILL-UPDATE-VERDICT-GENERATOR-01 (2026-04-15)

---

## Post-Process Pipeline

Every LLM-generated verdict passes through this pipeline before being returned or
cached:

```
[LLM output]
      ↓
1. _strip_markdown(text)
   — strips **, __, *, _, `, #, >, leading - bullets
   — source: bot.py (commit 6c0d532)
      ↓
2. _fix_orphan_back(text)
   — joins orphan "Back X." sentence to predecessor with em dash
   — source: bot.py (commit d52ff9a)
      ↓
3. validate_manager_names(verdict, evidence_pack)
   — hard-rejects if manager named but not in evidence pack
   — source: narrative_spec.py Gate 5
      ↓
4. validate_diamond_price_prefix(verdict, tier)
   — hard-rejects Diamond that lacks "<stake> returns <payout> · Edge confirmed" opener
   — source: narrative_spec.py Gate 6
      ↓
5. validate_no_markdown_leak(verdict)
   — hard-rejects any residual markdown that survived step 1
   — source: narrative_spec.py Gate 7
      ↓
[returned verdict — or deterministic _render_verdict(spec) fallback on any FAIL]
```

Steps 1 and 2 execute inline inside `_generate_verdict()` and
`_generate_verdict_constrained()` before the return statement.
Steps 3–5 execute inside `min_verdict_quality()` in `narrative_spec.py`, which is
called by the pre-generation and quality-check paths.

---

## Coaches.json Cross-Check

Arbiter agents validating verdicts that name a manager MUST cross-check against
`data/coaches.json`:

1. Look up the named manager's team in `data/coaches.json`
2. Check the `last_verified` date
3. If `last_verified` is more than 7 days ago → raise **Arbiter caution flag**
4. If the named manager does not appear in `data/coaches.json` at all → hard reject

Example structure of `data/coaches.json`:
```json
{
  "Arsenal": {"coach": "Arteta", "last_verified": "2026-04-10"},
  "Manchester City": {"coach": "Guardiola", "last_verified": "2026-04-10"}
}
```

Monitor function: `narrative_integrity_monitor.py::FRESHNESS_CHECK()`

---

## Parent Commits

| SHA | Description | Brief |
|-----|-------------|-------|
| `7169dcd` | data: refresh coaches.json + narrative_integrity_monitor.py | INV-COACHES-JSON-AUDIT-01 |
| `d52ff9a` | BUILD-VERDICT-RENDER-FIXES-01: orphan back + Diamond price-prefix gate | BUILD-VERDICT-RENDER-FIXES-01 |
| `6c0d532` | BUILD-SANITIZER-MARKDOWN-STRIP-01: _strip_markdown + validate_no_markdown_leak | BUILD-SANITIZER-MARKDOWN-STRIP-01 |
| `ba833eb` | INV-ADV-A-MANAGER-LEAKTHROUGH-01: reinforce null manager prompt gate | INV-ADV-A |

---

## Related Files

| File | Role |
|------|------|
| `bot/bot.py` | `_generate_verdict()`, `_generate_verdict_constrained()`, `_strip_markdown()`, `_fix_orphan_back()` |
| `bot/narrative_spec.py` | `validate_manager_names()`, `validate_diamond_price_prefix()`, `validate_no_markdown_leak()`, `min_verdict_quality()` |
| `bot/data/coaches.json` | Curated manager list with `last_verified` dates |
| `bot/narrative_integrity_monitor.py` | `FRESHNESS_CHECK()` — stale coach alert |
| `.claude/skills/verdict-generator/assets/verdict-prompt-template.md` | Prompt template reference |
| `.claude/skills/verdict-generator/references/banned-templates.md` | Rejected pattern catalogue |
