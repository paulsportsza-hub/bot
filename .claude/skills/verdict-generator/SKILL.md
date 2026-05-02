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

## Exemplar Bank (INJECT-EXEMPLARS-TO-BANK-01 — 2026-04-15)

Promoted verdict exemplars are stored in `bot/data/prose_exemplars.json` under the
`verdict_bank` key. These are injected at prompt-build time for style guidance.

| Field | Value |
|-------|-------|
| **Location** | `bot/data/prose_exemplars.json` → `verdict_bank` array |
| **Count** | 12 locked exemplars |
| **Last updated** | 2026-04-15 |
| **Loader** | `load_exemplars()` in `bot.py` (line ~17256) — cached on first call, cleared on restart |

### Promotion Criteria

1. Score **10/10** from forge validator (all HG gates pass), **OR** explicit Paul approval from
   the forge rating session.
2. Covers a **distinct shape** — no two exemplars with identical `(tier, sport, shape)` triple
   unless the second demonstrates a unique capability (e.g. dual-manager, SA locale, nickname-forward).
3. **HG-3 applied**: orphan `Back X.` back-lines joined to predecessor with em dash before storage.
4. **Plain text only**: no markdown formatting in `verdict_text`.

### Bank Contents (12 entries)

| ID | Tier | Sport | Shape | Source | Notes |
|----|------|-------|-------|--------|-------|
| forge_01_001 | Diamond | Soccer | home_fav | FORGE-01 | Paul 10/10 — Liverpool vs PSG |
| forge_01_002 | Diamond | Soccer | away_underdog | FORGE-01 | Paul 10/10 — Man City vs Arsenal |
| forge_01_003 | Diamond | Rugby | road_fav | FORGE-01 | Paul 10/10 — Ulster vs Leinster |
| forge_01_004 | Diamond | Soccer | road_fav | FORGE-01 | Diverse — Atletico vs Barcelona |
| forge_01_005 | Gold | Soccer | home_fav | FORGE-01 | Diverse — PSL/SA locale |
| forge_01_006 | Gold | Rugby | home_fav | FORGE-01 | Diverse — Super Rugby |
| forge_01_007 | Gold | Cricket | road_fav | FORGE-01 | Diverse — IPL |
| forge_01_008 | Silver | Soccer | road_fav | FORGE-01 | Diverse — PSL lower tier |
| forge_02_001 | Diamond | Soccer | road_fav | FORGE-02 | Dual-manager — MU vs Arsenal |
| forge_02_002 | Gold | Soccer | home_underdog | FORGE-02 | Dual-manager — Newcastle vs City |
| forge_02_003 | Gold | Soccer | home_fav | FORGE-02 | Dual-manager + PSL + SA nicknames |
| forge_02_004 | Bronze | Combat | away_underdog | FORGE-02 | Nickname-forward — DDP vs Chimaev |

---

## Related Files

| File | Role |
|------|------|
| `bot/bot.py` | `_generate_verdict()`, `_generate_verdict_constrained()`, `_strip_markdown()`, `_fix_orphan_back()` |
| `bot/narrative_spec.py` | `validate_manager_names()`, `validate_diamond_price_prefix()`, `validate_no_markdown_leak()`, `min_verdict_quality()` |
| `bot/verdict_corpus.py` | v2 deterministic corpus — `VERDICT_CORPUS`, `CONCERN_PREFIXES`, `has_real_risk()`, `render_verdict()` |
| `bot/data/coaches.json` | Curated manager list with `last_verified` dates |
| `bot/data/prose_exemplars.json` | Style-guide exemplars + `verdict_bank` (12 locked exemplars) |
| `bot/narrative_integrity_monitor.py` | `FRESHNESS_CHECK()` — stale coach alert |
| `.claude/skills/verdict-generator/assets/verdict-prompt-template.md` | Prompt template reference |
| `.claude/skills/verdict-generator/references/banned-templates.md` | Rejected pattern catalogue |

---

## v2 Deterministic Mode (BUILD-W82-RIP-AND-REPLACE-01 — 2026-05-02)

### Why v2

Six waves of W82 defects in five days surfaced a recurring pattern: each fix
removed one defect class (variant pool size, validator gate, closure rule,
clean-placeholder, connector valence) and the next wave surfaced a new one
(mid-word truncation, concessive contradiction, fragment-stitching). The
variable assembly engine was too clever for the value it produced. The fix
is to retire it entirely and replace it with a hand-authored corpus.

### Architecture

- **Corpus location:** `bot/verdict_corpus.py`. 40 verdict sentences (10 per
  tier — Diamond / Gold / Silver / Bronze) plus 10 sport-agnostic concern
  prefixes. Hand-authored, voice-reviewed, locked.
- **Hash-picker:** `_pick(corpus, match_key, tier)` uses MD5(`{match_key}|{tier}`)
  modulo `len(corpus)`. Same `(match_key, tier)` → same sentence every render.
  Different fixtures distribute approximately uniformly across the pool.
- **Slot-fill rule:** every sentence carries exactly three slots: `{team}`,
  `{odds}`, `{bookmaker}`. No other slots. The corpus author guarantees
  these are positioned for grammatical fluency in every variant.
- **Concern-prefix rule:** `has_real_risk(spec)` returns `True` when ANY of:
  - `lineup_injury` contradicting (pick side has a non-empty injuries list)
  - `line_movement` contradicting (`spec.movement_direction == "against"`)
  - `composite_score < tier_min + 5` (within 5 pts of tier floor — marginal)
  - `confirming_count == 0`
  - `contradicting_count >= 2`

  When True, a concern prefix is hash-picked from `CONCERN_PREFIXES` and
  concatenated to the verdict body via a single space — **no linguistic bridge
  between prefix and verdict body**. The reader's brain treats them as two
  beats: "here's the concern" then "here's the call".

- **Connector-ban rule:** zero concessive connectors anywhere in the corpus.
  No "Despite that", "Even so", "Still,", "That said", "Even with that".
  Regression-guarded by `tests/contracts/test_verdict_corpus.py`.

### Tier voice rubric

Every sentence honours the verdict-generator skill rubric. SA-native English.
Conviction tier-appropriate. Imperative close. 100-200 chars across realistic
slot-fill spread.

| Tier    | Conviction      | Imperatives                                              |
|---------|-----------------|----------------------------------------------------------|
| Diamond | maximum         | hammer, load up, go in heavy, lock in, bet, back, get on |
| Gold    | strong          | back, get on, take, the call is, bet                     |
| Silver  | measured        | back, the play is, take                                  |
| Bronze  | light           | worth a small play, worth a measured punt                |

### Validator gates retained (v2)

- **Char range** 100-200 (uniform `MIN_VERDICT_CHARS_BY_TIER` floor of 100;
  `VERDICT_HARD_MAX` 260 accommodates the corpus body plus optional concern
  prefix).
- **Imperative-close** (`_CORPUS_IMPERATIVE_CLOSE_RE`) — last sentence MUST
  contain one of the canonical imperatives. Diamond/Gold = CRITICAL on miss,
  Silver/Bronze = MAJOR.
- **Telemetry-vocab** (Rule 17 catalogue, e.g. "the signals", "the reads",
  "bookmaker slipped").
- **Vague-content** (e.g. "looks like the sort of", "takes shape").
- **Venue verified-list** (Rule 18 — verified `pack.venue` allows match;
  empty pack.venue allows curated stadiums.json fallback; cross-fixture
  inventions remain leaks).
- **Manager-name fabrication** (HG-1, against `coaches.json`).
- **Markdown-leak** (HG-4).

### Validator gates retired by v2

- Tier-branching closure rule (`_check_verdict_closure_rule`) — replaced
  with the uniform imperative-close gate.
- Strong-band tone lock (`_check_tier_band_tone`) — corpus is uniform; no
  cross-tier "cautious leaks" possible by construction.
- Hedging-conditional opener — corpus has zero concessive connectors.
- Diamond price-prefix shape (`<stake> returns <payout> · Edge confirmed`)
  — incompatible with imperative close. `validate_diamond_price_prefix` is
  retained as a True-returning shim for callsite stability.
- Risk-clause valence checks — concern prefix concatenation makes the
  Risk↔Verdict cohesion explicit; no Jaccard token-overlap needed.
- Concessive-connector regex bans — corpus contains zero connectors.
- Analytical-vocabulary count — anchored to old W82 verbose vocabulary.

### Don'ts

- Don't expand the corpus beyond 40 + 10 in this wave. Sport-banding and
  size growth are explicit policy decisions, not incremental edits.
- Don't add slots beyond `{team}`, `{odds}`, `{bookmaker}`. Other context
  belongs in The Setup / The Edge / The Risk sections, not in the verdict.
- Don't invent connectors between the concern prefix and the verdict body.
  The two-beat structure ("concern. call.") is intentional — narrative bridge
  re-introduces the failure modes the rip was meant to fix.
