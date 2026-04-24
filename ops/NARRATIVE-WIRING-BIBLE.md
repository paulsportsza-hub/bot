# 📖 Narrative Wiring Bible — v1 (2026-04-23)

**Wave:** INV-NARRATIVE-WIRING-BIBLE-01
**Author:** Opus Max Effort - LEAD
**Date:** 2026-04-23
**Status:** Source of truth for every agent that touches narrative code.

This document maps the narrative system exactly as it exists in the running
codebase at `/home/paulsportsza/bot/` on host `mzansiedge-hel1` (37.27.179.53)
with `bot.py` at 30,555 lines and the narrative_cache DB at
`/home/paulsportsza/scrapers/odds.db`. Every fact is cited with file:line
evidence or a direct DB query.

When the code changes, this document must change with it. Where I could not
confirm a claim with certainty, section 13 lists the open gap explicitly.

---

## 1. Overview & purpose

The narrative system turns a raw "edge" (a price/probability gap on a single
match) into the prose a user reads on the main Edge card and in the Full AI
Breakdown screen. It is the most consequential part of the product — every
Telegram user who taps a tip renders from this pipeline — and it has been the
most bug-prone, because three independent code paths (card image, AI Breakdown,
pregen job) each read different columns of the same `narrative_cache` table
with no shared reader.

This Bible exists to lock the wiring. Future agents must read section 2 before
touching verdict, narrative_html, or any quality gate, and must not assume
fields are interchangeable. Section 5 is the only authoritative surface-to-field
mapping — do not build from memory.

---

## 2. The two canonical questions answered

### Q1 — What field drives the verdict on the main Edge card image?

**Answer: `narrative_cache.verdict_html`.**

Evidence chain, end-to-end:

1. **User tap → bot reads tip**: All three entry paths (Hot Tips detail,
   My Matches detail, alerts deep-link) build the card with
   `build_edge_detail_data(_dl_tip_enriched)` at `bot.py:1285`, `bot.py:2076`,
   `bot.py:2299`.

2. **Card data builder** (`card_data.py:603-801`): reads `tip["verdict"]` at
   `card_data.py:788` and passes it to the `verdict` Jinja variable. All other
   fields on the card (teams, odds, form, H2H, signals) are built from
   `tip` + `build_verified_data_block()` — they do **not** come from
   `narrative_cache` at all.

3. **Enrichment** (`bot.py:8931-9354`): `_enrich_tip_for_card(tip, match_key)`
   is the function that populates `tip["verdict"]`. At `bot.py:9217-9326`:
   - Calls `_get_cached_verdict(match_key)` (`bot.py:14959`) which reads
     `SELECT verdict_html, evidence_class, tone_band, odds_hash, created_at,
     expires_at, tips_json, quality_status FROM narrative_cache WHERE
     match_id = ?` at `bot.py:14972-14977`.
   - If `verdict_html` passes the staleness checks (bookmaker match, odds ±0.10,
     EV ±1.0%, odds age ≤ 90 min same-day, content blacklist, tier-aware length
     floor from `MIN_VERDICT_CHARS_BY_TIER`), the cached text becomes
     `tip["verdict"]` after `_cap_verdict(..., limit=_VERDICT_MAX_CHARS)`.
   - If any check fails, `_generate_verdict(enriched, verified)` is called
     live and the output is fire-and-forget written back to `verdict_html`
     via `_store_verdict_cache_sync()` at `bot.py:15056`.

4. **Template render** (`card_templates/edge_detail.html:592-597`):
   ```html
   {% if tier and verdict %}
   <div class="verdict-section">
       <div class="section-hdr" style="color: #FFB300;">🏆 VERDICT</div>
       <div class="verdict-text">{{ verdict }}</div>
   </div>
   {% endif %}
   ```

5. **Crucially**: the card image does **NOT** read the embedded verdict inside
   `narrative_html`, and does **NOT** read `structured_card_json`. Every other
   field on the card is built outside `narrative_cache`. The 260-char hard max
   is enforced by the DB CHECK constraint on `verdict_html` (see Area 3) and
   re-enforced on serve by `_cap_verdict(..., limit=_VERDICT_MAX_CHARS)`.

### Q2 — What fields drive each Full AI Breakdown section?

**Answer: All four prose sections are parsed out of `narrative_cache.narrative_html`.**
`verdict_html` is used only to derive the short `verdict_tag` label shown above
the sections.

Evidence chain, end-to-end:

1. **User tap → bot calls breakdown renderer**: `card_pipeline.render_ai_breakdown_card(match_id)`
   at `card_pipeline.py:1674-1681` calls `build_ai_breakdown_data(match_id)` and
   passes the dict to `render_card_sync("ai_breakdown.html", data, width=480,
   device_scale_factor=2)`.

2. **Data builder** (`card_data.py:1101-1261`):
   ```sql
   SELECT narrative_html, edge_tier, tips_json, verdict_html, evidence_class
   FROM narrative_cache WHERE match_id = ?
   ```
   at `card_data.py:1132-1136`. This is the only DB read for the breakdown.

3. **Section parsing** (`card_data.py:1200-1243`): regex markers find
   `📋 <b>The Setup</b>`, `🎯 <b>The Edge</b>`, `⚠️ <b>The Risk</b>`,
   `🏆 <b>Verdict</b>` and `<b>SA Bookmaker Odds:</b>` inside `narrative_html`.
   Each section's prose is sliced between its marker and the next. The
   resulting `setup_html`, `edge_html`, `risk_html`, `verdict_prose_html`
   fields are returned to the template.

4. **`verdict_html` usage** (`card_data.py:1184-1198`): used ONLY to classify
   a short `verdict_tag` — STRONG BACK / BACK / MILD LEAN / SPECULATIVE /
   MONITOR / VERDICT — based on keyword match against `verdict_html` and
   `evidence_class`. The prose body of the breakdown's "Verdict" section
   comes from `narrative_html`, not `verdict_html`.

5. **Template render** (`card_templates/ai_breakdown.html`): receives the four
   `*_html` fields as Jinja variables and renders each section.

### Consequence of the Q1/Q2 split

The same 🏆 Verdict text can exist in **two different columns** for one row:

- `narrative_cache.verdict_html` — drives the main Edge card image.
- The 🏆 block inside `narrative_cache.narrative_html` — drives the
  AI Breakdown screen's verdict section.

These two texts can legitimately diverge because:
- `narrative_html` is generated once per pregen sweep (Sonnet polish of the
  four sections together, 6h TTL).
- `verdict_html` is updated live at serve time by `_store_verdict_cache_sync()`
  whenever staleness forces a fresh `_generate_verdict()` call (different
  Sonnet seed → different text).

This split is why the `BUILD-NARRATIVE-WATERTIGHT-01 C.1` serve-time gate at
`bot.py:14500-14551` runs `min_verdict_quality()` against **both** the embedded
verdict in `narrative_html` and the standalone `verdict_html` column. A row
passes only if both pass. The current quarantine dominance of
`verdict_quality:embedded_ok=False,standalone_ok=True` (16 of 35 rows — see
section 9) shows the embedded copy is the weaker path in practice.

---

## 3. narrative_cache schema

DDL (from `SELECT sql FROM sqlite_master WHERE name='narrative_cache'`):

```sql
CREATE TABLE "narrative_cache" (
    match_id TEXT PRIMARY KEY,
    narrative_html TEXT NOT NULL,
    model TEXT NOT NULL,
    edge_tier TEXT NOT NULL,
    tips_json TEXT NOT NULL,
    odds_hash TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    evidence_json TEXT,
    narrative_source TEXT NOT NULL DEFAULT 'w82',
    coverage_json TEXT,
    structured_card_json TEXT,
    verdict_html TEXT CHECK (verdict_html IS NULL OR
        (LENGTH(verdict_html) BETWEEN 1 AND 260)),
    evidence_class TEXT,
    tone_band TEXT,
    spec_json TEXT,
    context_json TEXT,
    generation_ms INTEGER,
    quality_status TEXT,
    quarantined INTEGER DEFAULT 0,
    setup_validated INTEGER DEFAULT 1,
    verdict_validated INTEGER DEFAULT 1,
    setup_attempts INTEGER DEFAULT 1,
    verdict_attempts INTEGER DEFAULT 1,
    status TEXT DEFAULT NULL,
    quarantine_reason TEXT DEFAULT NULL
);
```

| # | Column | Type | Notes | Writer(s) | Reader(s) | Surface |
|---|---|---|---|---|---|---|
| 0 | `match_id` | TEXT PK | `home_vs_away_YYYY-MM-DD`. Mutates on INSERT OR REPLACE. | `_store_narrative_cache`, `_store_verdict_cache_sync`, Haiku preview | All readers | Key for every surface |
| 1 | `narrative_html` | TEXT NOT NULL | 4-section HTML body with `📋 <b>The Setup</b>`, `🎯 <b>The Edge</b>`, `⚠️ <b>The Risk</b>`, `🏆 <b>Verdict</b>` headers. ~1100–2300 chars in practice. Can be empty string (`''`) when only a verdict is being stored (verdict-cache source). | `_store_narrative_cache`, Haiku preview writer, `_store_verdict_cache_sync` (new row only) | `_get_cached_narrative`, `build_ai_breakdown_data`, health check | **AI Breakdown** (all 4 sections) + health check sampler |
| 2 | `model` | TEXT NOT NULL | e.g. `claude-sonnet-4-6`, `haiku-4.5`, `view-time` (for verdict-only rows). | All writers | `_get_cached_narrative` | Telemetry only |
| 3 | `edge_tier` | TEXT NOT NULL | `diamond` / `gold` / `silver` / `bronze`. Defaulted to `bronze` at `bot.py:14730` if caller passes empty. | All writers | `_get_cached_narrative`, `build_ai_breakdown_data`, serve-time gates | Tier badge on every surface |
| 4 | `tips_json` | TEXT NOT NULL | JSON-serialised `tips` list — used to re-extract cached odds/EV/bookmaker for freshness checks. | All writers | `_get_cached_narrative`, `build_ai_breakdown_data`, `_get_cached_verdict` | EV%, bookmaker on AI Breakdown + freshness check |
| 5 | `odds_hash` | TEXT NOT NULL | MD5 of current odds via `_compute_odds_hash(match_id)`. Used to detect odds changes between generations. | All writers | `_get_cached_narrative`, `_get_cached_verdict` (via tips_json) | Freshness only |
| 6 | `created_at` | TIMESTAMP NOT NULL | Defaults to `CURRENT_TIMESTAMP` but all writers pass `now.isoformat()` explicitly. | All writers | Health check, staleness logging | Telemetry |
| 7 | `expires_at` | TIMESTAMP NOT NULL | `created_at + _NARRATIVE_CACHE_TTL` (6h default) or 24h for Haiku previews. TTL check in `_get_cached_narrative` returns None when expired. | All writers | Every reader (TTL check) | TTL eviction |
| 8 | `evidence_json` | TEXT (nullable) | Serialised `evidence_pack` — ESPN context, H2H raw, injuries, tipster rows, sharp injection. Used by serve-time gates to verify ESPN coverage and protect cached H2H from revalidation. | `_store_narrative_cache`, `_store_narrative_evidence` (UPDATE at `bot.py:15166`) | `_get_cached_narrative` (gates 3 & 10), `_generate_game_tips` | ESPN availability gate + H2H freshness skip |
| 9 | `narrative_source` | TEXT NOT NULL DEFAULT 'w82' | Active values observed in DB: `w84` (Sonnet polish), `w82` (deterministic baseline), `baseline_no_edge` (no-edge card preview), `verdict-cache` (standalone verdict-only row), `haiku_preview` (24h match-preview cache). Drives Gold/Diamond tier gate at `bot.py:14421` and ESPN freshness gate at `bot.py:14440`. | All writers (each passes its own constant) | `_get_cached_narrative` (gates 4 & 5), pregen sweep targeting | Content-source classification + gate routing |
| 10 | `coverage_json` | TEXT (nullable) | `evidence_pack.coverage_metrics` — which signals fired for the narrative. | `_store_narrative_cache` | `_get_cached_narrative` | Telemetry / debugging |
| 11 | `structured_card_json` | TEXT (nullable) | **Currently unread anywhere.** Written by pregen for future structured card rendering. Not consumed by `build_edge_detail_data`, `build_ai_breakdown_data`, or any live surface. See gap G3 in section 13. | `_store_narrative_cache` (pregen only) | — | Unused (dead-letter) |
| 12 | `verdict_html` | TEXT (nullable, CHECK 1–260) | Standalone verdict text. 260-char hard max enforced by DB CHECK. Truncated at last sentence boundary by `_store_narrative_cache` at `bot.py:14740`. Preserved across INSERT OR REPLACE by the read-before-write guard at `bot.py:14769-14778`. | `_store_narrative_cache`, `_store_verdict_cache_sync` (UPDATE at `bot.py:15120`, INSERT minimal row at `bot.py:15131`) | `_get_cached_verdict`, `_get_cached_narrative` (C.1 gate at `bot.py:14513`), `build_ai_breakdown_data` (tag only) | **Main Edge card image** (direct verdict display) |
| 13 | `evidence_class` | TEXT (nullable) | `NarrativeSpec._classify_evidence()` output: speculative / lean / supported / conviction. | `_store_narrative_cache` | `_get_cached_verdict`, `build_ai_breakdown_data` (verdict_tag fallback keyword match) | AI Breakdown verdict tag only |
| 14 | `tone_band` | TEXT (nullable) | Tone band from `TONE_BANDS` dict: cautious / moderate / confident / strong. Drives banned-phrase checks in polish validator. | `_store_narrative_cache` | `_get_cached_verdict` | Polish gate context |
| 15 | `spec_json` | TEXT (nullable) | Serialised `NarrativeSpec` dataclass used by renderer. Currently not re-read by any live path — written for future rehydration. | `_store_narrative_cache` | — | Dead-letter (same as #11) |
| 16 | `context_json` | TEXT (nullable) | ESPN match context dict at generation time. Not currently re-read by any live path. | `_store_narrative_cache` | — | Dead-letter |
| 17 | `generation_ms` | INTEGER (nullable) | Wall-clock ms to generate the narrative. | `_store_narrative_cache` | Telemetry queries | Performance telemetry |
| 18 | `quality_status` | TEXT (nullable) | Historical per-row quality marker. Legacy values include `'skipped_banned_shape'` (verdict pre-gate rejection). In current DB: **every row is NULL**. Superseded by `status` column. | `_store_verdict_cache_sync` (clears `skipped_banned_shape` when setting a new verdict at `bot.py:15121`) | `_get_cached_verdict` (returned but not gated on) | Legacy / winding-down |
| 19 | `quarantined` | INTEGER DEFAULT 0 | Legacy boolean flag. Only 1 row in DB has quarantined=1; all others default 0. Superseded by `status='quarantined'`. | No active writer in current code path | `_get_cached_narrative`, `_has_any_cached_narrative`, `_has_active_w84_cached` (all filter on `COALESCE(quarantined, 0) = 0`) | Legacy gate (kept for back-compat) |
| 20 | `setup_validated` | INTEGER DEFAULT 1 | NARRATIVE-ACCURACY-01 Rule 3: pass flag from `generate_and_validate()` for the Setup section. | `_store_narrative_cache` (pregen) | Telemetry | Validator telemetry |
| 21 | `verdict_validated` | INTEGER DEFAULT 1 | Same as above for Verdict section. | `_store_narrative_cache` (pregen) | Telemetry | Validator telemetry |
| 22 | `setup_attempts` | INTEGER DEFAULT 1 | Number of generation attempts for the Setup section (1 = first draft accepted; 2 = retry happened). | `_store_narrative_cache` (pregen) | Telemetry | Validator retry rate |
| 23 | `verdict_attempts` | INTEGER DEFAULT 1 | Same for Verdict section. | `_store_narrative_cache` (pregen) | Telemetry | Validator retry rate |
| 24 | `status` | TEXT DEFAULT NULL | **Active quarantine flag.** Value `'quarantined'` means the row is excluded from all serve paths. 24 of 35 rows currently. | All 10 serve-time quality gates (UPDATE SET status='quarantined' + quarantine_reason) | `_get_cached_narrative`, `_has_any_cached_narrative`, `_has_active_w84_cached` (all filter on `status IS NULL OR status != 'quarantined'`) | Primary quarantine mechanism |
| 25 | `quarantine_reason` | TEXT DEFAULT NULL | Free-text reason for the last `status='quarantined'` transition. e.g. `verdict_quality:embedded_ok=False,standalone_ok=True`. Observable via DB query — used for ops triage. | Every quality gate that sets status | Ops tooling only | Ops triage |

**Actual row distribution in production (2026-04-23):**

```
narrative_source    count
w84                 21
w82                  6
baseline_no_edge     6
verdict-cache        2
(haiku_preview)      0  — expired or not yet generated in observed window
TOTAL                35
```

```
status         quarantined=col  count
quarantined    0                 24
NULL           1                  8   ← legacy column value (quarantined INTEGER)
NULL           0                  3   ← active/servable rows
TOTAL                            35
```

**Only 3 of 35 rows (9%) are currently servable.** The dominant quarantine
reason is `verdict_quality:embedded_ok=False,standalone_ok=True` (16 rows),
meaning the 🏆 block parsed from `narrative_html` fails `min_verdict_quality()`
while the standalone `verdict_html` column passes. See section 11 for the
invariant implications.

---

## 4. Surface-to-field mapping (the critical table)

| Surface | Section / element | DB column(s) read | Read function (file:line) | Transform | Length constraint & why |
|---|---|---|---|---|---|
| **A. Main Edge card image** | Verdict text (🏆 VERDICT section) | `verdict_html` | `_get_cached_verdict` at `bot.py:14959-15053` (SELECT at `bot.py:14972-14977`) | Staleness-checked → `_cap_verdict(text, limit=_VERDICT_MAX_CHARS)` → `tip["verdict"]` → Jinja `{{ verdict }}` at `edge_detail.html:595` | 260-char DB CHECK; `MIN_VERDICT_CHARS_BY_TIER[tier]` floor; must end in `. ! ? …`; no banned phrases; ≥3 analytical words. Rationale: card verdict-box is a fixed pixel rectangle in `edge_detail.html:418-434`; overflow would wrap and clip. |
| **A. Main Edge card image** | Matchup, teams, tier, odds, pick, form, signals, H2H, bookmaker odds | **none from narrative_cache** | `build_edge_detail_data` at `card_data.py:603-801` + `_enrich_tip_for_card` at `bot.py:8931` | Data sourced from `build_verified_data_block()` (odds.db `odds_snapshots` + `match_results` + `team_injuries` tables) and from the live tip dict | Various — team names capped at 18px single-line (CSS `overflow: hidden; text-overflow: ellipsis`); form strings truncated to games_played. |
| **A. Main Edge card image** | Kickoff time & venue | — | `_resolve_kickoff_time()` at `bot.py:9167-9192`; `broadcast_schedule` query at `card_pipeline.py:1456-1489` (must include `AND source = 'supersport_scraper'` per SO #40) | — | — |
| **B. Full AI Breakdown** | 📋 The Setup (prose) | `narrative_html` | `build_ai_breakdown_data` at `card_data.py:1101-1261` (SELECT at `card_data.py:1132-1136`); regex section extractor at `card_data.py:1200-1243` | Regex `📋\s*<b>The Setup</b>` → slice to next marker → strip header line → `setup_html` | No hard cap; CSS-styled as scrolling block in `ai_breakdown.html` |
| **B. Full AI Breakdown** | 🎯 The Edge (prose) | `narrative_html` | Same as above (marker `🎯\s*<b>The Edge</b>`) | Same | Same |
| **B. Full AI Breakdown** | ⚠️ The Risk (prose) | `narrative_html` | Same as above (marker `⚠️\s*<b>The Risk</b>`) | Same | Same |
| **B. Full AI Breakdown** | 🏆 Verdict (prose body, NOT the short tag) | `narrative_html` | Same as above (marker `🏆\s*<b>Verdict</b>`) | Returned as `verdict_prose_html` | Same |
| **B. Full AI Breakdown** | Verdict tag ("BACK" / "LEAN" / "STRONG BACK") | `verdict_html` + `evidence_class` | Same function, lines `card_data.py:1184-1198` | Keyword match on `evidence_class` first, then `verdict_html` | Tag is a short label (3–12 chars), not the prose |
| **B. Full AI Breakdown** | Tier label + EV% + best bookmaker | `edge_tier` + `tips_json` | Same function, `card_data.py:1149-1182` | `tips_json` JSON-decoded, max by EV | — |
| **B. Full AI Breakdown** | Home/Away team names | — | Parsed from `match_id` suffix at `card_data.py:1154-1160` | `re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_id)` then title-case on `_vs_` split | — |
| **C. Hot Tips list view (no image, plain text)** | Tip lines + tier badges | — | `_build_hot_tips_page` at `bot.py:11932`. Reads `odds_snapshots` + `edge_results` from odds.db, NOT `narrative_cache`. | — | Card line capped by mobile 3-line format. |
| **D. My Matches list view** | Event lines | — | `_render_your_games_all` at `bot.py:6319`. No `narrative_cache` read — pure odds/schedule data. | — | — |
| **E. AI Breakdown gate button** | "Show AI Breakdown" button visibility | `narrative_html` (existence check only, any source) | `_has_any_cached_narrative` at `bot.py:14261-14296` (SELECT at `bot.py:14277-14285`) | Returns True if any row with `COALESCE(quarantined,0)=0 AND (status IS NULL OR status != 'quarantined') AND narrative_html IS NOT NULL AND LENGTH(TRIM(narrative_html)) > 0` and not expired | Gate at 1 row |
| **F. Pre-serve "warm" AI Breakdown gate** | w84-only warm check | `expires_at`, `narrative_source='w84'` | `_has_active_w84_cached` at `bot.py:14238` | Boolean | — |
| **G. Health check sampler** | Random 2-row fact-check every 2h | `narrative_html` | `_narrative_health_check_job` at `bot.py:29287` (SELECT at `bot.py:29301-29304`) | `_extract_claims(html)` → Haiku + web search verify (currently disabled by `_HEALTH_CHECK_WEB_SEARCH_ENABLED = False`, `bot.py:29284`) | Cache invalidation via DELETE on contradiction |
| **H. Haiku match-summary preview** | 2-3 sentence thin-context preview | `narrative_html` + `narrative_source='haiku_preview'` | `_generate_haiku_match_summary` at `bot.py:~20680` (SELECT at `bot.py:20688-20691`) | 24h TTL; `_has_haiku_banned_pattern` post-gen | 280-char hard cap in the Haiku skill (see `.claude/skills/haiku-match-summary/SKILL.md`) |

### Why the card image never reads `narrative_html` for the verdict

The card-image path was deliberately split from the AI Breakdown path during
the Q2 refactor (`BUILD-VERDICT-ENRICHMENT-FIX-01`,
`BUILD-VERDICT-RENDER-FIXES-01`, `BUILD-NARRATIVE-VOICE-01`) because:
- The card verdict has a 260-char hard physical limit (DB CHECK + CSS).
- The breakdown verdict prose can expand to multiple paragraphs.
- Generating both at once produced either bloated cards or thin breakdowns.

`verdict_html` is written on two pathways that can diverge:
- **Pregen sweep** writes both `narrative_html` (containing a 🏆 block) AND a
  separately-computed `verdict_html` via `_store_narrative_cache` at
  `bot.py:14780-14808`.
- **Serve-time** fresh verdict generation writes `verdict_html` only via
  `_store_verdict_cache_sync` (UPDATE path at `bot.py:15120` or INSERT minimal
  row path at `bot.py:15131`). It does NOT touch `narrative_html`.

After a serve-time regeneration, the 🏆 block in `narrative_html` is stale
relative to the refreshed `verdict_html`. Whether this divergence breaks a
surface depends on which surface is rendering next.

---

## 5. Write paths

| # | Function | file:line | Trigger | Columns WRITTEN | Columns NULL / default | INSERT mode | Pre-write validation |
|---|---|---|---|---|---|---|---|
| 1 | `_store_narrative_cache` (primary) | `bot.py:14673-14874` | Called by `_generate_game_tips` (serve-time) and by `pregenerate_narratives._generate_one` (cron). Main writer. | `match_id, narrative_html, model, edge_tier, tips_json, odds_hash, evidence_json, narrative_source, coverage_json, created_at, expires_at, structured_card_json, verdict_html, evidence_class, tone_band, spec_json, context_json, generation_ms, setup_validated, verdict_validated, setup_attempts, verdict_attempts` (22 cols) | `quality_status` (NULL), `quarantined` (0 default), `status` (NULL default), `quarantine_reason` (NULL default) — writer does not set these; gates do | **INSERT OR REPLACE** (full row) | (a) Premium-tier refusal: if `narrative_source in ("w82","baseline_no_edge") AND edge_tier in ("gold","diamond")` → **return without writing** (`bot.py:14716-14724`). (b) Tier default: empty `edge_tier` → `"bronze"` (`bot.py:14730`). (c) Verdict truncation: if `len(verdict_html) > 260` → `_trim_to_last_sentence(..., max_chars=260)` (`bot.py:14740`). (d) Verdict preservation: if `verdict_html is None`, read existing row's `verdict_html` and reuse (`bot.py:14769-14778`) — prevents wipe. |
| 2 | `_store_narrative_cache` (retry after OperationalError 'locked') | `bot.py:14831-14867` | Same as #1, but on first attempt lock | Same as #1 | Same | INSERT OR REPLACE | Same pre-validation; single 0.1s sleep + one retry. If retry fails, Sentry warning message, silent drop. |
| 3 | `_store_verdict_cache_sync` (UPDATE path) | `bot.py:15118-15125` | Called by `_enrich_tip_for_card` after live `_generate_verdict()`. Existing row found. | `verdict_html` (UPDATE SET), `quality_status` (conditionally cleared from `'skipped_banned_shape'`) | All other columns untouched | UPDATE | Pre-gate: `min_verdict_quality(verdict, tier, evidence_pack)` at `bot.py:15085`. On fail, silent skip + Sentry breadcrumb. |
| 4 | `_store_verdict_cache_sync` (INSERT minimal path) | `bot.py:15126-15145` | Same entry, no existing row | `match_id, narrative_html='', verdict_html, model='view-time', edge_tier, tips_json=[tip_data], odds_hash, narrative_source='verdict-cache', created_at, expires_at` | `evidence_json, coverage_json, structured_card_json, evidence_class, tone_band, spec_json, context_json, generation_ms, setup_validated(default 1), verdict_validated(default 1), setup_attempts(default 1), verdict_attempts(default 1), quality_status, quarantined(0), status, quarantine_reason` | INSERT OR REPLACE | Same pre-gate. Note: `narrative_html` is empty string (non-NULL), not NULL — satisfies NOT NULL constraint while signalling "verdict-only row". |
| 5 | `_generate_haiku_match_summary` writer | `bot.py:20784` (approx) | Haiku 2-3 sentence preview cache. 24h TTL. | `match_id, narrative_html(=summary), model='haiku-4.5', edge_tier='bronze', tips_json='[]', odds_hash='', narrative_source='haiku_preview', created_at, expires_at` | `evidence_json, coverage_json, structured_card_json, verdict_html, evidence_class, tone_band, spec_json, context_json, generation_ms, setup_validated, verdict_validated, setup_attempts, verdict_attempts, quality_status, quarantined, status, quarantine_reason` | INSERT OR REPLACE | `_has_haiku_banned_pattern(summary, sport)` pre-gate (bet language, hallucination markers, wrong-sport terms). |
| 6 | `_store_narrative_evidence` | `bot.py:15166` | Background fill when evidence_pack arrives after narrative was cached. | `evidence_json` only (UPDATE SET) | — | UPDATE | None — best-effort. |
| 7 | 10 quality-gate UPDATE sites in `_get_cached_narrative` | `bot.py:14354, 14369, 14406, 14428, 14477, 14491, 14541, 14574, 14586, 14605, 14648` | Serve-time quality failure | `status='quarantined', quarantine_reason=<reason>` | — | UPDATE | The check itself is the validation. |

### CHECK constraint behaviour on `verdict_html`

`verdict_html TEXT CHECK (verdict_html IS NULL OR (LENGTH(verdict_html)
BETWEEN 1 AND 260))`:

- Empty string (`''`) fails the CHECK → `sqlite3.IntegrityError`.
- `None` / NULL passes.
- Anything 1–260 chars inclusive passes.
- Anything >260 chars fails.

`_store_narrative_cache` pre-truncates at 260. `_store_verdict_cache_sync`
is guarded by `min_verdict_quality()` which hard-rejects >260. Caught
IntegrityErrors are tagged `contract_violation:narrative_cache` in Sentry
at `bot.py:14820-14823` — every fire is a contract bug, not a data issue.

### INSERT OR REPLACE vs UPDATE — the silent-wipe risk

Because #1 is INSERT OR REPLACE (full row), any column the caller passes as
`None` or default gets overwritten. The guard at `bot.py:14769-14778` reads
the existing `verdict_html` and carries it forward specifically to prevent
the pregen sweep (which may not regenerate a verdict every time) from
wiping a live-generated verdict. This is the `INV-CARD-NARRATIVE-SERVE-01`
invariant.

There is NO equivalent preservation guard for the other columns
(`evidence_json`, `coverage_json`, `structured_card_json`, `spec_json`,
`context_json`, `evidence_class`, `tone_band`, etc.). If pregen passes
`None` for any of these, the previous value is wiped on INSERT OR REPLACE.
Whether this matters depends on whether downstream logic still needs that
column — in current code, only `evidence_json` is re-read widely enough
to notice.

---

## 6. Read paths

Every `SELECT ... FROM narrative_cache` site in `bot.py`:

| # | Function / context | file:line | Columns read | Quality / filter conditions | Cache-miss behaviour |
|---|---|---|---|---|---|
| 1 | evidence backfill scan | `bot.py:12088` | `match_id, evidence_json` | none | Skip & continue |
| 2 | verdict-length DELETE purge (legacy cleanup on startup) | `bot.py:13932` | — (DELETE) | `LENGTH(verdict_html) > 300` | Drop the row |
| 3 | migration scan (one-time schema recovery) | `bot.py:13990` | `*` (for column copy into `narrative_cache_new200260`) | none | — |
| 4 | TTL sweep on startup | `bot.py:14086` | `match_id, expires_at, narrative_source` | none | Used to pick rows to DELETE |
| 5 | TTL DELETE | `bot.py:14116` | — (DELETE) | `match_id IN (...)` | — |
| 6 | `_has_active_w84_cached` | `bot.py:14244` | `expires_at` | `WHERE match_id = ? AND narrative_source = 'w84' AND COALESCE(quarantined,0) = 0` | Return False |
| 7 | `_has_any_cached_narrative` | `bot.py:14278` | `expires_at` | `WHERE match_id = ? AND COALESCE(quarantined,0)=0 AND (status IS NULL OR status != 'quarantined') AND narrative_html IS NOT NULL AND LENGTH(TRIM(narrative_html)) > 0` | Return False (gates the AI Breakdown button) |
| 8 | `_get_cached_narrative` (preferred SELECT) | `bot.py:14311-14317` | `narrative_html, model, edge_tier, tips_json, odds_hash, expires_at, evidence_json, narrative_source, coverage_json, created_at` | `WHERE match_id=? AND COALESCE(quarantined,0)=0 AND (status IS NULL OR status != 'quarantined')` | Fall through to non-status query then return None |
| 9 | `_get_cached_narrative` (fallback — older schema w/o `status` column) | `bot.py:14321-14326` | Same columns minus quarantine filter | `WHERE match_id=?` | Return None |
| 10 | `_get_cached_narrative` C.1 verdict-gate inner SELECT | `bot.py:14513-14515` | `verdict_html` | `WHERE match_id = ?` | Pass `_standalone_ok=True` (fail-open) |
| 11 | `_delete_narrative_cache` | `bot.py:14946` | — (DELETE) | `match_id = ?` | Called on outcome mismatch |
| 12 | `_get_cached_verdict` | `bot.py:14972-14977` | `verdict_html, evidence_class, tone_band, odds_hash, created_at, expires_at, tips_json, quality_status` | `WHERE match_id = ?` (no quarantine filter — see gap G1) | Return None → live `_generate_verdict()` runs |
| 13 | `_store_verdict_cache_sync` existence check | `bot.py:15113-15115` | `match_id` | `WHERE match_id = ?` | Pick INSERT vs UPDATE branch |
| 14 | Legacy narrative_cache scan (debug) | `bot.py:16217` | `match_id, narrative_html` | none | — |
| 15 | Cache validation sweep (DELETE on fail) | `bot.py:16236` | — (DELETE) | `match_id = ?` | — |
| 16 | Haiku preview cache check | `bot.py:20688-20691` | `narrative_html, expires_at` | `WHERE match_id = ? AND narrative_source = 'haiku_preview'` | Run Haiku, then write |
| 17 | Admin / dashboard stats | `bot.py:28335-28346` | `COUNT(*)`, `model + COUNT(*)`, `MIN/MAX created_at` | Various | — |
| 18 | Admin / stale scan | `bot.py:28859, 28888` | `COUNT(*)`, `match_id` | `WHERE COALESCE(quarantined,0) = 0` | — |
| 19 | `_narrative_health_check_job` sampler | `bot.py:29301-29304` | `match_id, narrative_html` | `WHERE expires_at > datetime('now') LIMIT 50` | Random sample of 2 |
| 20 | `card_data.build_ai_breakdown_data` | `card_data.py:1132-1136` | `narrative_html, edge_tier, tips_json, verdict_html, evidence_class` | `WHERE match_id = ?` (no quarantine filter — see gap G2) | Return None |

### Behavioural notes on readers

- **Readers #12 and #20 do NOT filter on quarantine/status.** The card image
  path (#12) can therefore serve a verdict from a row the breakdown path (#8)
  has quarantined. Conversely, the AI Breakdown builder (#20) can serve
  prose from a quarantined row. This is tracked as gaps **G1** and **G2**
  in section 13.
- Reader #8 is the most fortified: every one of the 10 serve-time quality
  gates runs inside it. If it returns None, the caller treats it as a cache
  miss and regenerates or falls back.
- Reader #12 is the bottleneck for Q1 staleness behaviour. All the
  bookmaker/odds/EV/age checks that let a cached verdict serve live at
  `bot.py:9221-9266` run against the row returned by #12.

---

## 7. Quality gates

### 7a. Serve-time gates in `_get_cached_narrative` (`bot.py:14299-14666`)

| # | Gate | file:line | Field(s) checked | Quarantine mechanism | Reason tag |
|---|---|---|---|---|---|
| 1 | Stale Setup patterns (regex on cleaned body) | `bot.py:14344-14361` | cleaned `narrative_html` | UPDATE SET status='quarantined', quarantine_reason=<joined reasons> | e.g. generic "take on" / "limited context" |
| 2 | Stale Setup context claims (evidence mismatch) | `bot.py:14362-14376` | `narrative_html` + `evidence_json` | UPDATE SET status='quarantined' | `stale_setup_context_claims` |
| 3 | ESPN unavailable for ESPN-covered league ≤7d | `bot.py:14377-14415` | `evidence_json.espn_context.data_available`, `evidence_json.league`, `match_id` date suffix | UPDATE SET status='quarantined' | `espn_unavailable:<league>` |
| 4 | Gold/Diamond forbidden w82/baseline_no_edge | `bot.py:14417-14435` | `narrative_source`, `edge_tier` | UPDATE SET status='quarantined' | `w82_for_tier:<tier>` |
| 5 | w82 for ESPN-covered league ≤7d | `bot.py:14437-14484` | `narrative_source`, league from `evidence_json` or `edge_results` fallback, date | UPDATE SET status='quarantined' | `w82_espn_freshness:<league>` |
| 6 | Banned phrases in cached body | `bot.py:14486-14498` | cleaned `narrative_html` | UPDATE SET status='quarantined' | `banned_patterns` |
| 7 | **C.1 — `min_verdict_quality()` on both embedded AND standalone** | `bot.py:14500-14551` | Embedded verdict extracted from `narrative_html` + `verdict_html` column | UPDATE SET status='quarantined' | `verdict_quality:embedded_ok=<bool>,standalone_ok=<bool>` |
| 8 | Old-format HTML headers missing (non-w82/baseline/verdict-cache) | `bot.py:14555-14581` | `narrative_html`, `narrative_source` | UPDATE SET status='quarantined' | `old_format_headers:<source>` |
| 9 | Empty section(s) in body | `bot.py:14582-14593` | cleaned `narrative_html` | UPDATE SET status='quarantined' | `empty_sections` |
| 10 | Stale H2H summary mismatch (bypassed when `evidence_json` present — gate 7 handles it) | `bot.py:14594-14612` | `narrative_html` + `tips` + `evidence_json` | UPDATE SET status='quarantined' | `stale_h2h_summary` |
| 11 | Tier drift >1 level | `bot.py:14613-14620` | cached tier vs `_quick_edge_tier_lookup(match_id)` | Return None (no quarantine) | — |
| 12 | EV incoherence >1.0pp | `bot.py:14622-14655` | Cached EV from `tips_json` vs live `edge_results` | UPDATE SET status='quarantined' | `ev_incoherent:cached=<x>,live=<y>` |

### 7b. Pre-write gate in `_store_narrative_cache`

- **Stream 4 F1-F2 refusal** at `bot.py:14716-14724`:
  - If `narrative_source in {w82, baseline_no_edge}` AND `edge_tier in {gold, diamond}` → refuse write, log
    `FIX-NARRATIVE-CACHE-SILENT-DROP-01 Stream4Refused`, emit Sentry warning.
  - Rationale: premium tiers must carry Sonnet-polished (w84) narratives or no row at all.
- **Tier default** at `bot.py:14730`: empty edge_tier → `"bronze"` to satisfy NOT NULL.
- **Verdict truncation** at `bot.py:14740`: `> 260 chars` → `_trim_to_last_sentence(..., max_chars=260)`.
- **Verdict preservation** at `bot.py:14769-14778`: if incoming `verdict_html` is None, reuse the existing row's `verdict_html`.

### 7c. Pre-write gate in `_store_verdict_cache_sync`

- `min_verdict_quality(verdict_html, tier, evidence_pack)` at `bot.py:15085`. On fail:
  - No DB write.
  - Sentry breadcrumb `verdict_cache_rejected` at `bot.py:15094`.
  - Warning log with match_key, tier, len, sample.

### 7d. `min_verdict_quality()` itself — 8 gates (`narrative_spec.py:407-464`)

1. **Tier-specific length floor**: `len(text) >= MIN_VERDICT_CHARS_BY_TIER[tier]`
   - Diamond 140, Gold 110, Silver 80, Bronze 60.
2. **Hard max**: `len(text) <= VERDICT_HARD_MAX` (260).
3. **Sentence boundary**: `text[-1] in ".!?…"` (BUILD-NARRATIVE-VOICE-01 AC-4).
4. **Banned trivial templates**: `BANNED_TRIVIAL_VERDICT_TEMPLATES` — bare "Team at price.", "Back X.", "Arsenal 2-1 Chelsea.".
5. **Analytical vocabulary count**: ≥3 words from `ANALYTICAL_VOCABULARY` frozenset.
6. **Manager name validation** (when `evidence_pack` given): `validate_manager_names(text, evidence_pack)` — fails if verdict names a coach absent from evidence. HG-1 NULL MANAGER CONDITIONAL enforcement.
7. **Diamond price-prefix shape** (Diamond tier only): `validate_diamond_price_prefix(text, tier)` — Diamond must open with "R<stake> returns R<payout> · Edge confirmed".
8. **No markdown leak**: `validate_no_markdown_leak(text)` — no `**`, `__`, backticks, headers, blockquotes survived.

`MIN_VERDICT_CHARS` (flat) at `narrative_spec.py:148` is **legacy** — new code
must use the per-tier dict. TODO `INV-VERDICT-GOLD-TRACE-01` is open against the
Gold calibration.

### 7e. Current quarantine distribution (DB query 2026-04-23)

```
quarantine_reason                                     count
verdict_quality:embedded_ok=False,standalone_ok=True   16
banned_patterns                                         3
odds_in_setup                                           2
w82_espn_freshness:psl                                  1
w82_espn_freshness:epl                                  1
old_format_headers:verdict-cache                        1
(other / null)                                          3
```

**16 of 24 quarantined rows (67%)** fail the C.1 gate because the embedded
verdict inside `narrative_html` fails `min_verdict_quality()` while the
standalone `verdict_html` passes. This is diagnostic: the pregen pipeline
generates the long-form narrative and the short verdict text independently,
with the standalone verdict attracting more quality engineering (dedicated
8-gate validator, serve-time regeneration) than the embedded 🏆 block.

The `odds_in_setup` reason (2 rows) surfaces one of the stale-Setup patterns
caught by gate 1 — it is not a separate code path.

---

## 8. Generation chains

Tracing each `narrative_source` value to its producer, model, prompt/spec, and fallback trigger:

### `w84` — primary Sonnet-polished narrative (21 rows in DB)

- **Producer**: `pregenerate_narratives._generate_one()` at `scripts/pregenerate_narratives.py:1771`, the W82-WIRE + W82-POLISH pipeline.
- **Model**: `NARRATIVE_MODEL` env var, default `claude-sonnet-4-6` (MODELS dict at `scripts/pregenerate_narratives.py:68-71`). Pre-INV-SONNET-BURN-05 this was Opus — do not revert.
- **Prompt / spec**: `_build_polish_prompt(baseline, spec, exemplars)` at `bot.py:19533` — receives a pre-rendered baseline from `_render_baseline(spec)` (`narrative_spec.py`) plus `TONE_BANDS` allowed/banned lists, verdict_action, 8 strict rules. The LLM may only improve flow; it may not change analytical posture.
- **Validator**: `_validate_polish(polished, baseline, spec)` — six gates: banned phrases, four section headers present, team names present, bookmaker+odds present, no speculative contradictions, `_quality_check()`. Fail → baseline served.
- **Verdict fork**: `generate_and_validate()` at `scripts/pregenerate_narratives.py:1653` wraps `generate_section()` for the Verdict section specifically, calling a second LLM at temperature=0 to check every claim against DERIVED CLAIMS. On failure, one retry at temperature=0.5 with violation list as banned phrases. If retry also fails, publishes best-effort with ⚠ flag and logs to `narrative_skip_log`.
- **Columns populated**: all 22 cols (full row). `setup_validated` / `verdict_validated` / `setup_attempts` / `verdict_attempts` carry validator state.
- **Fallback trigger**: Validator reject on both passes → `narrative_source='w84'` still, but `verdict_validated=0` or `setup_validated=0`. Complete pipeline failure → falls through to `w82`.

### `w82` — deterministic baseline (6 rows in DB)

- **Producer**: Same function. When polish fails or live_tap=True (`_generate_narrative_v2` at `bot.py` serving path with `live_tap=True`), the baseline is written as-is.
- **Model**: `'baseline'` or `'view-time'` string in `model` column. Zero LLM calls for w82.
- **Prompt / spec**: None — `_render_baseline(spec)` at `narrative_spec.py` is pure Python. 30 templates (10 story types × 3 MD5-deterministic variants). All phrases comply with `TONE_BANDS` allowed/banned lists.
- **Columns populated**: all 22 cols but `spec_json` carries the NarrativeSpec used.
- **Fallback trigger**: Reached when the polish pass fails 3 times (per generate_and_validate retry logic) OR when live-tap path served instantly during cache miss.

### `baseline_no_edge` — no-edge card preview (6 rows in DB)

- **Producer**: `_generate_narrative_v2(live_tap=True, ctx_data=None, tips=[])` path. Triggered by `edge:detail` instant-baseline flow when an event has no positive-EV tip (e.g. a match on the My Matches feed that exists in odds.db but didn't qualify as an edge).
- **Model**: `'baseline'`.
- **Prompt / spec**: Same as w82 but with neutral outcome framing.
- **Columns populated**: Same layout as w82; `evidence_class`, `tone_band` often NULL because no edge_data drives classification.
- **Fallback trigger**: Always the "no edge found" branch — not a failure fallback.

### `verdict-cache` — standalone verdict row (2 rows in DB)

- **Producer**: `_store_verdict_cache_sync()` at `bot.py:15056-15154`, INSERT path at `bot.py:15131-15143`.
- **Model**: `'view-time'`.
- **Prompt / spec**: `_generate_verdict(enriched, verified)` inside `_enrich_tip_for_card` calls the Sonnet verdict-only prompt (`.claude/skills/verdict-generator`). Max 180 tokens. Min floor per tier.
- **Columns populated**: minimal — `match_id, narrative_html='', verdict_html, model='view-time', edge_tier, tips_json=[single tip_data], odds_hash, narrative_source='verdict-cache', created_at, expires_at`. All other columns NULL.
- **Fallback trigger**: User tapped an edge detail but no existing narrative_cache row existed. Verdict generated live and cached for future taps. `narrative_html=''` signals "verdict-only row".

### `haiku_preview` — 2-3 sentence match preview (expired / 0 rows observed)

- **Producer**: `_generate_haiku_match_summary()` at `bot.py:~20680`.
- **Model**: `claude-haiku-4-5-20251001`. Temperature 0.3. Max 100 tokens.
- **Prompt / spec**: See `.claude/skills/haiku-match-summary/SKILL.md`. Closed-world data contract — only CONTEXT block data may be referenced.
- **Columns populated**: `match_id, narrative_html (=summary text), model='haiku-4.5', edge_tier='bronze', tips_json='[]', odds_hash='', narrative_source='haiku_preview', created_at, expires_at`. 24h TTL.
- **Fallback trigger**: Called when thin-context match needs a preview in UI contexts where no edge exists.
- **Post-gen gate**: `_has_haiku_banned_pattern(summary, sport)` — betting language, hallucination markers, wrong-sport terms. On fail: return empty string, no cache write.

### Fallback cascade — end-to-end

```
serve-time tap (edge:detail)
    │
    ├── [cache hit, passes all 12 serve gates] → serve cached w84/w82/verdict-cache
    │
    ├── [cache miss OR gate fail]
    │       ├── _generate_verdict() live (Sonnet)
    │       │       ├── success → _store_verdict_cache_sync (verdict-cache row OR UPDATE existing)
    │       │       └── fail (blacklist, empty, length-floor)
    │       │               ├── cached verdict_html fallback (if not blacklisted)
    │       │               └── _render_verdict(NarrativeSpec(neutral)) — deterministic
    │       │                       └── last resort: empty string, contract_violation=verdict_empty logged
    │       │
    │       └── [narrative_html needed — AI Breakdown / gate fail]
    │               ├── _generate_narrative_v2(live_tap=True) — instant baseline, zero LLM
    │               │       └── returns w82 HTML (no DB write; in-memory only)
    │               └── pregen next sweep produces w84 (6h TTL)
    │
    └── Health check (every 2h) randomly validates 2 rows; contradiction → DELETE
```

---

## 9. Pregen architecture

### `_narrative_pregenerate_job` (`bot.py:29235-29280`)

- **Schedule**: runs hourly but guards to 06:00 / 12:00 / 18:00 / 21:00 SAST at `bot.py:29249`. Other hours no-op.
  - **06:00 SAST = full sweep** — 24h-age + hash check, regenerate all eligible.
  - **12/18/21 SAST = refresh sweep** — cache-presence + outcome-match check, regenerate stale only.
- **Entry**: `from scripts.pregenerate_narratives import main as pregen_main; await pregen_main(sweep)` at `bot.py:29271-29272`.
- **Single-flight guard**: `_pregen_active` global bool set **before** lock acquisition at `bot.py:29260`, cleared in `finally` at `bot.py:29279`. This is a BASELINE-FIX pattern — TOCTOU-free, no yield point between check and set. `_pregen_lock = asyncio.Lock()` at `bot.py:28835` serialises the work itself.
- **Tier-aware horizon** (LOCKED per W84-VOICE / BUILD-NARRATIVE-VOICE-01):
  - Diamond/Gold: 96h ahead (`discover_pregen_targets(hours_ahead_premium=96)`).
  - Silver/Bronze: 48h ahead.
  - Implementation in `scripts/pregenerate_narratives.py:1183-1409`.
  - DO NOT revert `hours_ahead_premium` default to 48.
- **Concurrency cap**: `_evidence_sem = asyncio.Semaphore(3)` inside the pregen worker loop (`bot.py:29151`).

### `_edge_precompute_job` (`bot.py:29021-29232`)

- **Schedule**: every 15 minutes (wider cron).
- **Role**: pre-compute edge metadata + seed `_game_tips_cache[match_key]` so that `edge:detail` taps can serve an instant baseline (zero ESPN, zero LLM).
- **Relationship to narrative pregen**: does not generate narratives itself. Its output (tips with edge_v2 metadata) is what the narrative pregen reads to decide targets.
- **Single-flight guard**: `_precompute_active` bool at `bot.py:28904`, same pattern.

### `_background_pregen_fill()` (`bot.py:28936-29019`)

- **Trigger**: invoked post-Hot-Tips flow when users tap in and the Hot Tips cache has entries that lack warm narrative_cache rows.
- **Same lock**: shares `_pregen_lock` with the scheduled job — cannot collide.
- **Single-flight**: uses the same `_pregen_active` bool.

### Interaction + collision semantics

- All three jobs (`_narrative_pregenerate_job`, `_background_pregen_fill`, `_edge_precompute_job`) share single-flight bool guards. `_pregen_*` and `_precompute_*` are distinct.
- When the scheduled pregen collides with a user-triggered background fill: second caller returns immediately with `log.info("Pregen [job]: DROPPED — sweep already active")`.
- Narrative pregen and edge precompute can run concurrently — different locks. They read from the same `odds_snapshots` table but write to different rows of the same `narrative_cache` table. INSERT OR REPLACE semantics protect the table, but the WAL journal mode + 30s busy_timeout handle concurrent writers.

### Starvation mitigations (post BUILD-NARRATIVE-PREGEN-WINDOW-01)

- Tier-aware 96h horizon ensures Gold/Diamond edges detected beyond 48h still get pregenerated before users see them.
- `_needs_pregen_context_lift(ctx)` at `scripts/pregenerate_narratives.py:429` identifies weak-context fixtures that benefit from a lift pass.
- `_validate_pregen_runtime_schema()` + `_REQUIRED_BOT_FUNCTIONS` import contract at `scripts/pregenerate_narratives.py:369-410` — prevents cron from silently failing when a rename breaks the import.
- PID lock (fcntl) at `scripts/pregenerate_narratives.py` __main__ block — second concurrent script invocation exits cleanly code 0.
- Import contract test: `tests/contracts/test_imports.py::TestCriticalFunctions` — daily contract test fails before cron does if any critical export is renamed. Protected names: `_build_setup_section_v2`, `get_verified_injuries`, `_clean_fact_checked_output`, `build_verified_narrative`, `fact_check_output`, `_build_polish_prompt`, `_validate_polish`, `_render_baseline`, `_render_setup`, `_render_edge`, `_render_verdict`.

---

## 10. Key files and their roles

| File | Role | Primary narrative-relevant functions |
|---|---|---|
| `/home/paulsportsza/bot/bot.py` | Main async Telegram bot (30,555 lines). Narrative sections are ~14,000–15,500 (writers/readers/gates), ~8,900–9,400 (card enrichment), ~28,800–29,400 (pregen jobs), ~20,680–20,800 (Haiku preview). | `_has_active_w84_cached`, `_has_any_cached_narrative`, `_get_cached_narrative`, `_get_cached_verdict`, `_store_narrative_cache`, `_store_verdict_cache_sync`, `_store_narrative_evidence`, `_delete_narrative_cache`, `_enrich_tip_for_card`, `_generate_verdict`, `_generate_narrative_v2`, `_narrative_pregenerate_job`, `_background_pregen_fill`, `_edge_precompute_job`, `_narrative_health_check_job`, `_generate_haiku_match_summary` |
| `/home/paulsportsza/bot/card_data.py` | Template data builders for all card surfaces. | `build_edge_detail_data` (Q1 data), `build_ai_breakdown_data` (Q2 data), `build_my_matches_data`, `build_match_detail_data` |
| `/home/paulsportsza/bot/card_pipeline.py` | Card rendering orchestrator (HTML + PNG). Bridges `card_data` to Playwright renderer. | `build_card_data`, `render_card_html` (Telegram caption), `render_ai_breakdown_card` (breakdown PNG), `render_card_bytes`, `build_verified_data_block`, `generate_card_analysis`, `verify_card_populates` |
| `/home/paulsportsza/bot/card_renderer.py` | HTML-to-PNG Playwright wrapper. `render_card_sync("template.html", data, width, device_scale_factor)` returns PNG bytes. | `render_card_sync`, `warm_chromium` |
| `/home/paulsportsza/bot/card_templates/edge_detail.html` | **Main Edge card image template**. Q1 answer lives here (`{{ verdict }}` at line 595). | — |
| `/home/paulsportsza/bot/card_templates/ai_breakdown.html` | **Full AI Breakdown template**. Consumes `setup_html / edge_html / risk_html / verdict_prose_html`. | — |
| `/home/paulsportsza/bot/card_templates/my_matches.html` | My Matches list image. Does not read narrative_cache. | — |
| `/home/paulsportsza/bot/card_templates/edge_picks.html` | Hot Tips list image. Does not read narrative_cache directly. | — |
| `/home/paulsportsza/bot/narrative_spec.py` | Editorial spec module — typed `NarrativeSpec` dataclass, tone bands, evidence classification, deterministic renderer, verdict quality gates. | `build_narrative_spec`, `_render_baseline`, `_render_setup`, `_render_edge`, `_render_verdict`, `_classify_evidence`, `_check_coherence`, `_enforce_coherence`, `min_verdict_quality`, `analytical_word_count`, `_reject_llm_meta_strings`, `validate_manager_names`, `validate_diamond_price_prefix`, `validate_no_markdown_leak`, `_extract_verdict_text`, `cap_verdict_in_narrative`, `build_derived_claims`, `_derived_soccer / _rugby / _cricket_ipl / _cricket_test`, `lookup_coach`. Constants: `MIN_VERDICT_CHARS_BY_TIER`, `VERDICT_HARD_MAX=260`, `VERDICT_TARGET_LOW=140`, `VERDICT_TARGET_HIGH=200`, `ANALYTICAL_VOCABULARY`, `BANNED_TRIVIAL_VERDICT_TEMPLATES`, `TONE_BANDS`. |
| `/home/paulsportsza/bot/evidence_pack.py` | Evidence pack builder — ESPN + injuries + H2H + sharp injection. Produces `evidence_json` column content. | `build_evidence_pack`, `serialise_evidence_pack`, `format_evidence_prompt`, `verify_shadow_narrative`, `_build_verified_coaches`, `_fetch_h2h_from_match_results`, `_build_h2h_injection`, `_inject_h2h_sentence`, `_strip_model_generated_h2h_references`, `_build_sharp_injection`, `_inject_sharp_sentence`, `_strip_model_generated_sharp_references`, `_suppress_shadow_banned_phrases`, `get_verified_injuries` |
| `/home/paulsportsza/bot/scripts/pregenerate_narratives.py` | Cron-driven pregen runner. | `main`, `_generate_one`, `discover_pregen_targets`, `generate_section`, `generate_and_validate`, `_load_pregen_edges`, `_refresh_edge_from_odds_db`, `_pregen_enrichment_live_safe`, `_validate_pregen_runtime_schema`, `_ensure_skip_reason_column` |
| `/home/paulsportsza/bot/.claude/skills/verdict-generator/SKILL.md` | Governs all verdict text (both `_generate_verdict` live + `_generate_verdict_constrained` pregen). Six HG gates (2026-04-15). Locked merged tag `pre-launch-verdict-stack-2026-04-15`. | **Does NOT govern**: embedded 🏆 block in `narrative_html` (that comes from `_render_verdict(spec)` + Sonnet polish through `_build_polish_prompt`). |
| `/home/paulsportsza/bot/.claude/skills/haiku-match-summary/SKILL.md` | Governs Haiku preview generation only. Closed-world contract. 280-char cap, 2-3 sentences. `narrative_source='haiku_preview'` only. | — |
| `/home/paulsportsza/scrapers/odds.db` | SQLite — `narrative_cache`, `odds_snapshots`, `match_results`, `team_injuries`, `broadcast_schedule`, `edge_results`, `daily_tip_views`, `team_ratings`, `dc_params`, `shadow_narratives`. WAL mode, `busy_timeout=30000ms`. 700 MB. | Accessed via `scrapers.db_connect.connect_odds_db` (scrapers) or `db_connection.get_connection(_NARRATIVE_DB_PATH, timeout_ms=...)` (bot). |

Files that search positive for `narrative_cache|verdict_html|structured_card_json` but are not primary (test/scratch/scripts):

- `bot/dashboard/health_dashboard.py` — admin health view.
- `bot/scratch/verify_ai_breakdown_v2.py` — one-off verification script.
- `bot/scripts/backfill_verdict_quality_scan.py`, `data_health_check.py`, `forge_verdict_exemplars.py`, `monitor_narrative_integrity.py`, `remediate_w91_p3_cap_violations.py` — scripts.
- 21 test files in `bot/tests/contracts/` and `bot/tests/` — contract + integration coverage.

---

## 11. Critical invariants

Each invariant states the rule, cites its evidence, and describes what breaks
if it is violated.

### INV-1 — `verdict_html` must never exceed 260 chars

- **Evidence**: DB `CHECK (verdict_html IS NULL OR (LENGTH(verdict_html)
  BETWEEN 1 AND 260))` + CSS constraints in `edge_detail.html:417-434`
  (verdict-section has `flex-grow: 1` inside a 620px fixed-height card).
- **Enforcement**: `_store_narrative_cache` truncates at `bot.py:14740`.
  `min_verdict_quality()` Gate 2 rejects at `narrative_spec.py:436`.
- **If violated**: `sqlite3.IntegrityError` captured as
  `contract_violation:narrative_cache` in Sentry (`bot.py:14820-14823`).
  Card PNG would overflow the verdict-section rectangle, clipping mid-word.

### INV-2 — `verdict_html` is preserved across INSERT OR REPLACE when the new write passes `verdict_html=None`

- **Evidence**: `bot.py:14769-14778` reads existing `verdict_html` before the
  main INSERT OR REPLACE and reuses it when the caller passed None.
- **Enforcement**: The read-before-write guard is the enforcement. No test
  currently regression-guards this specific preservation.
- **If violated**: A pregen sweep that regenerates narrative_html but not
  verdict_html would wipe a live-cached verdict, causing the main Edge card
  to flash different verdict text between re-navigations. This is the
  INV-CARD-NARRATIVE-SERVE-01 pattern.

### INV-3 — C.1 serve-time gate applies `min_verdict_quality()` to BOTH the embedded verdict in `narrative_html` AND the standalone `verdict_html` column

- **Evidence**: `bot.py:14500-14551`. Both must pass (`_embedded_ok AND
  _standalone_ok`) for the row to serve.
- **Enforcement**: Gate 7 in section 7a.
- **If violated**: Stale/thin verdicts in `narrative_html` would serve to
  the AI Breakdown screen even when the standalone verdict_html is healthy,
  causing the breakdown's 🏆 section to show "Back Arsenal." or similar
  trivial templates. This is the dominant failure mode in current DB
  (67% of quarantines).

### INV-4 — Any `SELECT` from narrative_cache that returns servable rows MUST filter on `status != 'quarantined'` AND `quarantined = 0`

- **Evidence**: `bot.py:14246, 14280-14281, 14315-14316, 28891` — all
  active reader paths include both filters (with `COALESCE` for legacy
  rows).
- **Enforcement**: Convention only. No contract test currently blocks a
  new reader from being written without these filters.
- **If violated**: Quarantined rows that failed one of the 12 serve-time
  gates would bleed through to user surfaces. `build_ai_breakdown_data`
  (`card_data.py:1132`) and `_get_cached_verdict` (`bot.py:14972`) already
  violate this invariant — see gaps G1, G2.

### INV-5 — C.1 applies `min_verdict_quality()` to the embedded verdict WITHOUT passing `evidence_pack`

- **Evidence**: `bot.py:14523` — `_embedded_ok = _mvq(_embedded_verdict,
  tier=_tier_for_gate, evidence_pack=None)`. Same at `bot.py:14528` for
  standalone.
- **Enforcement**: Gate 7's `evidence_pack=None` means Gate 6 (manager
  name validation) always passes.
- **If violated by being set**: Gate 6 would need an accurate evidence
  pack for every cached row to be re-validated — a round-trip that the
  current code avoids because the evidence was already applied at
  generation time. Leaving this at `None` is intentional; flipping it on
  without a loaded pack would cause false-positive quarantines.

### INV-6 — Premium tiers (Gold, Diamond) must never serve `w82` or `baseline_no_edge` source narratives

- **Evidence**: Pre-write refuse at `bot.py:14716-14724` (`Stream4Refused`)
  + serve-time Gate 4 at `bot.py:14421-14435`.
- **Enforcement**: Two layers — refuse the write + reject the read.
- **If violated**: A Gold/Diamond user would see a thin, deterministic
  baseline when the pregen sweep produced no polish. The double-layer
  means even if a w82 row slipped into the table, it would be quarantined
  on first read.

### INV-7 — Every write that populates the main 22-column INSERT OR REPLACE must emit a `FIX-NARRATIVE-CACHE-SILENT-DROP-01 CommitOK` log line

- **Evidence**: `bot.py:14813-14817`. The companion pre-write log is
  `Stream4Accepted` at `bot.py:14750-14754`.
- **Enforcement**: Convention + log grepping. Sentry tag
  `contract:contract_violation:narrative_cache` fires on IntegrityError.
- **If violated**: A silent drop (Stream4Accepted emitted but no CommitOK
  within ~seconds for the same match_id) indicates the OperationalError
  retry failed silently. Ops must grep `log.warning("FIX-NARRATIVE-CACHE-
  SILENT-DROP-01` to detect.

### INV-8 — The 🏆 marker `f3c6` (U+1F3C6 = TROPHY) is the parse anchor for BOTH embedded verdict extraction and AI Breakdown section slicing

- **Evidence**: `narrative_spec._extract_verdict_text` at
  `narrative_spec.py:473` uses `narrative_html.find("\U0001f3c6")`.
  `card_data.py:1207` uses the regex `r"🏆\s*<b>Verdict</b>"`.
  `card_data.py:1211-1243` also relies on `🏆`.
- **Enforcement**: Literal emoji constant in multiple files.
- **If violated**: Changing the 🏆 marker without updating the two extractors
  would break the AI Breakdown verdict section rendering AND the C.1 gate's
  embedded-verdict extraction (causing every C.1 check to pass with empty
  text). Any emoji change must update `_extract_verdict_text`,
  `_strip_preamble` (`bot.py`), and the `_SECTION_MARKERS` list in
  `build_ai_breakdown_data`.

### INV-9 — `narrative_source` enumerated set is {`w84`, `w82`, `baseline_no_edge`, `verdict-cache`, `haiku_preview`}

- **Evidence**: DB row sample + 5 producer sites identified in section 8.
- **Enforcement**: Convention. Gate 8 at `bot.py:14561` hardcodes the set
  `{"w82", "baseline_no_edge", "verdict-cache"}` as the exempt list for
  old-format HTML headers — adding a new source value without updating
  this gate would trigger spurious quarantines.
- **If violated**: A new source not in the exempt list would be checked
  for W84-Q1 HTML headers (`<b>The Setup</b>` etc.) and quarantined as
  `old_format_headers:<new_source>`.

### INV-10 — Readers that need the latest content MUST check `expires_at > now` AND MUST NOT trust `created_at` for freshness

- **Evidence**: `_get_cached_narrative` at `bot.py:14331-14338`,
  `_has_active_w84_cached` at `bot.py:14253-14256`.
- **If violated**: Health check sampler #19 does not check `expires_at`
  strictly (it filters WHERE `expires_at > datetime('now')` in the SELECT
  so expired rows never reach it — but any new reader copying the pattern
  must include this filter).

### INV-11 — `min_verdict_quality()` Gate 4 (trivial-template reject) regex list is closed

- **Evidence**: `BANNED_TRIVIAL_VERDICT_TEMPLATES` at `narrative_spec.py:165-172`
  — three patterns only. Adding one without a version bump would cause
  verdicts that previously passed to start failing on the next pregen
  sweep.
- **If violated**: Mass regeneration of cached verdicts could overwhelm
  Sonnet quota. Changes require `/sc:spec-panel` review per
  `NARRATIVE-ACCURACY-01` governance.

---

## 12. How to safely touch this system

Checklist for any agent making changes to the narrative system:

1. **Read this Bible first.** Sections 2, 4, 7, 11 are non-optional.
2. **Identify which surface is affected.** Use the surface-to-field mapping
   in section 5. If your change touches a field read by more than one
   surface, plan for both.
3. **Grep first, never unranged read of bot.py.** (SO #30.) Before any
   `Read` ≥100 lines of bot.py, run:
   ```bash
   grep -n "pattern" /home/paulsportsza/bot/bot.py | head -40
   ```
   Then target your read with `offset` + `limit`.
4. **When adding a writer**:
   - Include every column in the INSERT or use UPDATE for partial writes.
   - Preserve `verdict_html` across INSERT OR REPLACE if you are touching
     `_store_narrative_cache` (INV-2).
   - Emit `Stream4Accepted` + `CommitOK` log lines for observability
     (INV-7).
   - Add a pre-write gate if you add a new failure mode.
5. **When adding a reader**:
   - Filter on both `status != 'quarantined'` AND `COALESCE(quarantined,0)=0`
     (INV-4). If the reader is allowed to see quarantined rows (e.g. an
     admin tool), document the exception explicitly.
   - Include the TTL check: `expires_at > datetime('now')` (INV-10).
   - Never `SELECT *` — verify the column list against section 3.
6. **When adding a quality gate**:
   - Place it in `_get_cached_narrative` (serve-time) or in
     `min_verdict_quality` (content-level).
   - Use `UPDATE ... SET status = 'quarantined', quarantine_reason = ?`
     with a human-readable reason tag. Document the tag pattern in
     section 7.
   - Add a contract test in `tests/contracts/`.
7. **When changing a `narrative_source` value or adding a new one**:
   - Update INV-9 and the Gate 8 exempt list at `bot.py:14561`.
   - Update any tier gate that references the source string (Gate 4 at
     `bot.py:14421`, Gate 5 at `bot.py:14440`).
   - Bump section 14 version with a migration note.
8. **When touching `verdict_html`**:
   - Test both the main Edge card (Q1) AND the AI Breakdown screen (Q2).
     These paths can diverge.
   - Run the telethon flow that taps an edge, backs out, and re-taps — if
     verdict text changes, INV-2 is broken.
9. **When touching `narrative_html`**:
   - Test the AI Breakdown screen. The regex parser at
     `card_data.py:1200-1243` depends on exact `📋 <b>The Setup</b>`,
     `🎯 <b>The Edge</b>`, `⚠️ <b>The Risk</b>`, `🏆 <b>Verdict</b>`,
     `<b>SA Bookmaker Odds:</b>` markers.
   - Never emit markdown in narrative_html — the `validate_no_markdown_leak`
     gate will reject subsequent verdicts that inherit the markdown.
10. **Never call `sqlite3.connect()` directly.** Use `get_connection()` for
    bot code (`db_connection.py`) or `scrapers.db_connect.connect_odds_db()`
    for scraper code. W81-DBLOCK is permanent (`CLAUDE.md` rules).
11. **Run the full contract suite before committing**:
    ```bash
    bash scripts/qa_safe.sh contracts
    ```
    At minimum, these must pass:
    - `test_imports.py::TestCriticalFunctions`
    - `test_narrative_spec.py` (92 tests)
    - `test_verdict_cache.py`, `test_verdict_char_range.py`,
      `test_verdict_quality_gate.py`, `test_serve_time_verdict_quality.py`
    - `test_ai_breakdown_button_present.py`
    - `test_card_render_defects.py`
    - `test_no_gold_baseline_writes.py`, `test_pregen_stub_gate.py`
12. **Update this Bible** in the same PR. Add an entry to section 14.

---

## 13. Open questions / known gaps

Items I could not confirm with certainty or which are known bugs I surfaced
during this investigation but did not fix (per the "documentation only"
instruction).

### G1 — `_get_cached_verdict` does not filter on quarantine/status

**Evidence**: `bot.py:14972-14977` SELECT has no `WHERE` clause beyond
`match_id = ?`. No check on `quarantined` or `status`.

**Consequence**: A row that Gate 7 (C.1) quarantined because its embedded
verdict failed `min_verdict_quality()` can still have its standalone
`verdict_html` served to the main Edge card image — because Gate 7 only
gates `_get_cached_narrative`, not `_get_cached_verdict`. This explains
the asymmetric quarantine pattern
(`embedded_ok=False, standalone_ok=True`): the system has been
over-trusting standalone verdicts to compensate for thin embedded ones.

**Root cause**: `_get_cached_verdict` predates the `status` column. Never
updated when the C.1 gate was added.

**Recommendation**: Add the same quarantine filter to `_get_cached_verdict`
OR document explicitly that the card verdict path is intentionally
allowed to serve "quarantined at breakdown level but healthy at verdict
level" rows. Either way, the current silent asymmetry is a
confusion vector.

### G2 — `build_ai_breakdown_data` does not filter on quarantine/status

**Evidence**: `card_data.py:1132-1136` SELECT has no `WHERE` clause beyond
`match_id = ?`.

**Consequence**: Tapping "Show AI Breakdown" on a match whose narrative
was quarantined by any of the 12 serve-time gates will still render the
breakdown from the quarantined `narrative_html`. The `_has_any_cached_narrative`
gate (`bot.py:14261`) is supposed to suppress the button in this case —
but it runs as a separate DB check that could race with a quarantine
transition happening in between the button render and the tap.

**Root cause**: `build_ai_breakdown_data` was designed for the happy path
and delegates the gate check to `_has_any_cached_narrative`. This split
reader is fragile.

**Recommendation**: Unify: either `build_ai_breakdown_data` returns None
on quarantined rows, or `_has_any_cached_narrative` is merged into it
and the function returns `None` on both cache-miss and quarantine.

### G3 — `structured_card_json`, `spec_json`, `context_json` are written but never read by live serve paths

**Evidence**: grep for `structured_card_json` in serve-time code: only the
writer in `_store_narrative_cache`. Same for `spec_json` and `context_json`
in the narrative-serving code — neither `card_data.py`, `card_pipeline.py`,
nor `_get_cached_verdict`/`_get_cached_narrative` returns them to callers.

**Consequence**: Three TEXT columns are populated on every pregen write
(storage cost) without ever informing a render. If they were intended as
structured-card rehydration for a future renderer, that renderer does
not exist.

**Recommendation**: Either wire them into a read path (e.g. pass
`structured_card_json` to `build_edge_detail_data` for structured render)
or mark them as deprecated and stop writing them to save storage and
pregen time.

### G4 — `quality_status` column is vestigial

**Evidence**: All 35 rows have `quality_status = NULL`. Only write site
is the conditional clearing of `'skipped_banned_shape'` at `bot.py:15121-15122`
— but no writer actually sets that value currently (the
BUILD-VERDICT-QUALITY-GATE-01 writer was deprecated when the pre-write
gate in `_store_verdict_cache_sync` took over).

**Consequence**: The column could be dropped. Holding it adds
confusion about whether it's meaningful to check on read.

**Recommendation**: Run a single scripted migration to drop
`quality_status` and `quarantined` (the INTEGER column — see G5) after
confirming no legacy readers still reference them.

### G5 — `quarantined` INTEGER column is legacy; `status` TEXT is the active flag

**Evidence**: Schema shows both columns. `quarantined` has 1 row at 1
(legacy); 34 at 0. Live quarantine code writes only to `status`
(`bot.py:14354, 14369, 14406, 14428, 14477, 14491, 14541, 14574, 14586,
14605, 14648`). Readers still filter on both for safety.

**Consequence**: Two boolean-meaning columns tracking the same concept.
Any new gate author could easily write to the wrong one and think the
quarantine took effect.

**Recommendation**: After confirming all writers have migrated, drop
the `quarantined` INTEGER column. Keep `status` + `quarantine_reason`
as the canonical pair.

### G6 — The `verdict-cache` row path produces `narrative_html=''` which violates the NOT NULL spirit

**Evidence**: `bot.py:15134` — `VALUES (?, '', ?, ...)`. The empty-string
passes `NOT NULL` but is semantically a lie: there is no narrative for
this row.

**Consequence**: `_has_any_cached_narrative` at `bot.py:14282-14283` has
a specific guard `AND LENGTH(TRIM(COALESCE(narrative_html,''))) > 0`
to exclude these rows from the AI Breakdown button check. If that guard
is removed, the breakdown button would light up for verdict-cache rows
and render an empty breakdown.

**Recommendation**: Add a contract test that enforces
`narrative_source='verdict-cache' ⇔ narrative_html=''`.

### G7 — Current servable-row ratio is 3/35 (9%)

**Evidence**: Section 3 DB query.

**Consequence**: The narrative system is running on a very thin cache.
Whether this is transient (one slow pregen cycle) or structural (C.1
gate is too strict for current generator output) requires observation
over multiple days.

**Recommendation**: Track the `verdict_quality:embedded_ok=False`
quarantine rate as a SLO. Current rate is ~67% of quarantines = 46% of
all rows = unacceptable for production.

### G8 — `MIN_VERDICT_CHARS` flat constant at `narrative_spec.py:148` is unused but still exported

**Evidence**: `MIN_VERDICT_CHARS: int = 80` with TODO
`INV-VERDICT-GOLD-TRACE-01`. Current production uses
`MIN_VERDICT_CHARS_BY_TIER` only.

**Recommendation**: Delete after confirming no legacy import still pulls
it. INV-VERDICT-GOLD-TRACE-01 is the task.

### G9 — `model` column string is not constrained

**Evidence**: Observed values: `claude-sonnet-4-6`, `claude-opus-4-20250514`,
`claude-haiku-4-5-20251001`, `haiku-4.5`, `baseline`, `view-time`,
`NARRATIVE_MODEL=...` envvar value.

**Consequence**: Inconsistent formatting (e.g. `haiku-4.5` vs
`claude-haiku-4-5-20251001`) makes telemetry queries fragile.
`_model_family_label()` at `scripts/pregenerate_narratives.py:80` handles
this in pregen but not in serve-time writers.

**Recommendation**: Normalise to canonical model IDs in all writers.

### G10 — No contract test for the `verdict_html` preservation guard (INV-2)

**Evidence**: grep for `test_.*preservation\|test_.*verdict.*preserve` in
`tests/contracts/` — no match. The guard at `bot.py:14769-14778` has no
regression coverage.

**Recommendation**: Add a contract test that inserts a row with a
verdict, calls `_store_narrative_cache` with `verdict_html=None`, and
asserts the verdict survives.

### G11 — `SKILL.md` files for `verdict-generator` and `haiku-match-summary` live at
`/home/paulsportsza/bot/.claude/skills/...` but the brief references skills at the project root

**Evidence**: `find /home/paulsportsza -name "SKILL.md" -path "*verdict*"` returned
`/home/paulsportsza/bot/.claude/skills/verdict-generator/SKILL.md`. There
is no `/home/paulsportsza/.claude/skills/verdict-generator/` path.

**Consequence**: Agents looking at user-scope skills (`~/.claude/skills`)
will not find the narrative-relevant skills — they are at project scope.
This is correct but worth documenting.

### G12 — The local-file brief path is a macOS path

**Evidence**: Brief says write to `/Users/paul/Documents/MzansiEdge/ops/
NARRATIVE-WIRING-BIBLE.md` — that path does not exist on host
mzansiedge-hel1 (Linux). I mirrored at `/home/paulsportsza/bot/ops/
NARRATIVE-WIRING-BIBLE.md` which is in the bot repo and survives deploys.

**Recommendation**: Sync the bot repo's `ops/NARRATIVE-WIRING-BIBLE.md`
to the Cowork Mac path via whatever mechanism Cowork uses for repo
mirroring. If Cowork reads directly from the server path, no sync
needed.

---

## 14. Version history

| Version | Date | Author | Changes |
|---|---|---|---|
| v1 | 2026-04-23 | Opus Max Effort - LEAD | Initial canonical wiring. Answers Q1 (card image → `verdict_html`) and Q2 (AI Breakdown → 4-section regex on `narrative_html`, verdict_tag from `verdict_html`+`evidence_class`). Maps 26-column schema, 7 distinct writers, 20 reader sites, 12 serve-time quality gates, 5 `narrative_source` values, 3 pregen jobs with tier-aware 48/96h horizon. 11 invariants locked. 12 open gaps documented for follow-up. |

---

*This Bible lives at `/home/paulsportsza/bot/ops/NARRATIVE-WIRING-BIBLE.md`
(mirror) and as a child page of the Core Memory page in Notion (source of
truth). When in doubt, update both in the same PR — drift between them is
how this kind of document fails.*
