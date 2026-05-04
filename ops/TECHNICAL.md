# Technical System Summary

> **Source of truth for database inventory, algorithm specs, pipeline architecture, and test coverage.** Referenced from CLAUDE.md.

*Last updated: 24 April 2026 PM by AUDITOR — added launch-week engine invariants: edge config tune, CLV dedup, fixture blacklist, settlement taxonomy, narrative wiring bible pointer. Tier thresholds line updated to reflect ALGO-FIX-01 canonical.*

---

## ⛔ CURRENT ENGINE INVARIANTS (LOCKED — LAUNCH WEEK)

These are the locked constraints any LEAD brief touching algo, pregen, settlement, or card surfaces must respect. Deviations require explicit Paul override.

### Tier thresholds (ALGO-FIX-01 — LOCKED)
- Diamond ≥ 60 composite · Gold ≥ 50 · Silver ≥ 35 · Bronze ≥ 20
- Diamond `min_confirming = 1` (lowered from 2 on 24 Apr — `FIX-EDGE-CONFIG-LAUNCH-TUNE-01` commit `2fd2d1b`)
- Revisit composite thresholds only after ≥30 settled Diamond edges (see `.auto-memory/project_algo_composite_works_gates_break.md`)

### Edge config weight profile (post FIX-EDGE-CONFIG-LAUNCH-TUNE-01, 24 Apr)
- `movement` weight `0.04` across all 10 profiles in `scrapers/edge/edge_config.py` (re-enabled from stub-zero; redistributed from `tipster`).
- `lineup_injury = 0.00` in `CRICKET_WEIGHTS`, `NON_SHARP_CRICKET_WEIGHTS`, `RUGBY_WEIGHTS`, `NON_SHARP_RUGBY_WEIGHTS`, `MMA_WEIGHTS`, `BOXING_WEIGHTS` (these sports don't have lineup_injury data — weight redistributed 50/50 to `form_h2h` + `price_edge`). Soccer profiles retain `lineup_injury`.
- Regression guard: `scrapers/tests/contracts/test_edge_config_weights.py` (29 tests).

### Fixture blacklist (FIX-EDGE-FIXTURE-BLACKLIST-01 — LOCKED 24 Apr 2026, commit `f31f992`)
- `scrapers/edge/fixture_blacklist.py::is_excluded()` gates test cricket + all women's sport at the top of `get_top_edges()` per-fixture loop in `scrapers/edge/edge_v2_helper.py`.
- Exclusions: `league = 'test_cricket'` (all test cricket), any league/sport substring `women`, 16 known women's-only league keys, team-name markers (` women`, ` women's`, ` ladies`, ` wfc`).
- Do not add test_cricket or women's sport fixtures back without removing the filter first.
- Regression guard: `scrapers/tests/contracts/test_fixture_blacklist.py` (37 tests).
- First live run: 8 fixtures gated cleanly, 2 valid men's edges passed, zero user-facing impact (no `alerts_send_log` entries for any excluded fixture).

### edge_results settlement taxonomy (LOCKED)
- `edge_results.result` uses `hit` / `miss` / `void` / `expired` — **NOT `won` / `lost`**.
- Any SQL assuming `won/lost` returns zero. Dashboard (`health_dashboard.py`) already uses `hit/miss` correctly.
- ROI mapping: `hit → +((odds-1)*stake)`, `miss → -stake`, `void / expired → 0 (excluded)`.
- Settlement cron: `30 1,3,5,7,9,11,13,15,17,19,21,23 * * * scripts/settle_edges.py`. Primary UPDATE sites: `scrapers/edge/settlement.py:275, 572, 815, 855, 878, 982, 1013`.

### CLV tracking (FIX-CLV-DEDUP-WRITE-01 — LOCKED 24 Apr 2026)
- `clv_tracking` has a unique expression index `idx_clv_dedup ON (match_key, selection, COALESCE(sharp_source, ''))`.
- Both writer sites use `INSERT OR IGNORE`: `scrapers/edge/settlement.py:340`, `scrapers/betfair/edge_helper.py:742`.
- Legacy taxonomy (`STRONG/MODERATE/SLIGHT/NEUTRAL/NEGATIVE`) in 209 historical rows is preserved as pre-W14A evidence — do NOT remap.
- Regression guard: `scrapers/tests/contracts/test_clv_tracking_dedup.py` (6 tests).

### Narrative Wiring Bible reference
- Before any change to narrative, verdict, or pregen code, **read the Bible**: Notion `34bd9048-d73c-81f8-af8a-e3bfb540cc0f` · server mirror `/home/paulsportsza/bot/ops/NARRATIVE-WIRING-BIBLE.md`.
- Minimum sections: §2 Q1/Q2 field mapping, §7 quality gates, §11 critical invariants.
- Skipping this read leads to incorrect model attribution (Sonnet serve-time vs Haiku pregen), wrong cost analysis, and defective fixes.

---

---

## ⛔ DASHBOARD — ONE FILE ONLY (LOCKED 18 April 2026)

**`health_dashboard.py`** (`/home/paulsportsza/bot/dashboard/health_dashboard.py`, served by `mzansi-admin.service` on port 8501) is the **ONE AND ONLY** admin dashboard. All Social Ops, System Health, Edge Performance, and Task Hub views live here.

**`/home/paulsportsza/dashboard/`** — **DEAD. DEPRECATED. DO NOT TOUCH.** This is an ancient FastAPI app that is not running and not used. Any agent that ships dashboard work to this path has shipped to the wrong service. If you find yourself grepping or editing files under `/home/paulsportsza/dashboard/`, stop immediately and re-target to `health_dashboard.py`.

**Why this matters:** PILLS-01 and FIX-REEL-KIT-TIMELINE-01 both shipped to the dead path by mistake, requiring costly re-work. This error must not recur.

---

## Standing Orders (moved from CLAUDE.md — 17 April 2026 PM)

*Original SO numbers preserved for historical reference. All agents building, dispatching, or operating any automated pipeline or monitoring surface must read these.*

- **[SO #4]** No new Make automation. Ever. All 7 Make scenarios are inactive/deprecated. n8n WF1/WF2b are deprecated — the Python multi-channel publisher at `/home/paulsportsza/publisher/` is the canonical publishing system.
- **[SO #28]** Production health monitoring is handled by `health-monitor-fix` (every 12h). This task checks `https://mzansiedge.co.za/admin/health`, Sentry issues, server logs, service status, and fixes what it can. No other scheduled task or COO checks Sentry or runs health checks. COO/AUDITOR acts on findings when surfaced.

---

This section is a condensed reference. Full implementation details live in the server codebase and Notion.

### Canonical Database Inventory (DATA-AUDIT — 5 April 2026)

| DB | Path on Server | Size | Tables | Rows | Purpose |
|----|----------------|------|--------|------|---------|
| **odds.db** | `/home/paulsportsza/scrapers/odds.db` | 840.7 MB | 47 | 1.95M | Primary odds, enrichment, standings, lineups, news |
| **enrichment.db** | `/home/paulsportsza/scrapers/enrichment.db` | 9.1 MB | 3 | 25.7K | Weather data, news articles, venue info |
| **tipster_predictions.db** | `/home/paulsportsza/scrapers/tipsters/tipster_predictions.db` | 3.1 MB | 4 | 9.2K | 6 tipster prediction sources |
| **mzansiedge.db** | `/home/paulsportsza/bot/data/mzansiedge.db` | 0.09 MB | 10 | 88 | Bot state, subscriptions, user preferences |
| **combat_data.db** | `/home/paulsportsza/bot/data/combat_data.db` | — | — | — | MMA fighter records (disconnected from bot pipeline — orphan) |
| **narrative_cache.db** | `/home/paulsportsza/bot/data/narrative_cache.db` | — | — | — | Pregen narrative cache |

**Orphaned data sources (identified 5 Apr, cleanup pending):** combat_data.db (disconnected), venues.json, shadow_narratives, psl_squads (34d stale), bet_recommendations_log, empty mma_fighters + team_injuries tables, mcp_data/ (538 MB stale snapshots), team_names.json. **18 empty .db artifact files** across server to be cleaned.

### Edge V2 — 7-Signal Composite Algorithm

Three-layer edge system: (1) Own probability model (Elo, target: Dixon-Coles), (2) Betfair Exchange sharp benchmark via The Odds API ($30/mo), (3) SA bookmaker soft consensus. Edge = Layer 3 disagrees with Layers 1 AND 2.

**Current data richness:** ~65-68% sharp-grade. Target: 85%.

**Tier thresholds (SUPERSEDED — see §Current Engine Invariants above for canonical ALGO-FIX-01 values: Diamond ≥60, Gold ≥50, Silver ≥35, Bronze ≥20 with Diamond min_confirming=1 post 24 Apr).** Pre-locked values below retained for historical reference only. Legacy: 💎 Diamond ≥52 composite/≥5% edge/≥2 confirming signals, 🥇 Gold ≥40/≥3%/≥0, 🥈 Silver ≥38/≥1.5%/≥0, 🥉 Bronze ≥15/≥0.5%/≥0.

**8 bookmaker scrapers live:** HWB, Supabets, Betway, Sportingbet, GBets, WSB, Playabets, SuperSportBet. Multi-BK coverage: 90.9%. Avg 5.4 bookmakers per match.

**Sharp data (Layer 2):** Pinnacle, Betfair Exchange, Matchbook, Smarkets. 8x daily cron.

**Defences:** MAD-based outlier detection, stale price graduated tiers, draw bias correction, ISBets ghost fixture pattern.

### _fetch_sa_odds() Key Lookup (LOCKED — BUILD-FIX-KEY-MISMATCH, 4 Apr)

- Queries `market_type IN ('1x2', 'match_winner', 'fight_winner')` in one pass.
- If forward key returns 0 rows, tries reversed key (away_vs_home) via indexed lookup.
- `effective_key` tracks which key hit for correct `filter_outlier_prices` invocation.
- Do NOT restrict to `'1x2'` only — cricket/MMA use `'match_winner'`.

### _fetch_injuries() Lineup Fallback (LOCKED — BUILD-FIX-INJURIES, 4 Apr)

- After querying `team_injuries` + `extracted_injuries`, if both return empty AND `match_key` is provided, calls `_fetch_lineup_availability()` as fallback.
- `match_lineups` table has 7,339 rows of starting XI/bench data — no explicit injury flags, but availability context.
- Bidirectional key lookup + ±1 day date tolerance (6 candidate keys).
- 175 matches now have availability data (was 0).

### News Pipeline (FIXED — BUILD-FIX-NEWS, 4 Apr)

- `psl_news_scraper.py` runs 3x daily (06:07, 12:07, 18:07 UTC). Google News RSS with `+when:7d` filter.
- `_is_current_narrative_injury()` function added (was undefined → NameError silently caught).
- 330+ fresh articles. `news.available=True` for PSL matches.
- EPL/rugby/cricket news covered by `enrichment.db` via separate `news_monitor.py` pipeline.

### Narrative Engine — ⛔ DEPRECATED (6 April 2026)

**The narrative engine and pregen pipeline are DEPRECATED.** The product surface is now Playwright + Jinja2 image cards (no LLM in the render path). The old Sonnet polish pipeline was burning 4.5M tokens/day generating narratives nobody sees. `pregenerate_narratives.py` cron must be killed. `narrative_cache.db` is orphaned. The only planned Anthropic API usage going forward is Haiku for verdict blockquotes in Edge Detail cards (not yet wired).

Previous architecture (historical reference only): NarrativeSpec (code) → Baseline render (code) → Sonnet polish → 50 golden-card regression tests. Full enrichment pipeline (BUILD-ENRICH-01–09) still valid for structured data fields used by image cards.

### ⛔ Narrative Rendering Path Classification (LOCKED — 24 March 2026)

**Three rendering paths exist. Only ONE is the product. The other two are failure modes.**

| Path | Classification | What it means |
|------|---------------|---------------|
| **AI-ENRICHED** (ESPN data + Sonnet polish via `narrative_cache`) | ✅ **THE PRODUCT** | Real match data (coaches, form, injuries, H2H), AI-polished narrative. This is what users pay for. Every card MUST reach this path. |
| **TEMPLATE** (NarrativeSpec deterministic templates, no real match data) | 🚨 **FAILURE MODE** | Something went wrong upstream — pregen pipeline didn't run, ESPN fetch failed silently, Sonnet polish errored out, or cache key mismatch. Treat as a P0 pipeline bug, NOT as acceptable output. |
| **INSTANT BASELINE** (live_tap emergency fallback, no LLM) | 🚨 **FAILURE MODE** | Cache miss + generation failure. Emergency fallback only. If a user sees this, something is critically broken. |

**Rules:**
- **TEMPLATE cards are NOT acceptable product output.** Any QA round where >10% of cards are template-rendered is a FAIL regardless of score.
- **Agents must NOT rate template cards highly.** A template card with generic boilerplate is 3/10 narrative richness maximum, no matter how "clean" the structure is.
- **The response to template cards is to fix the pregen pipeline**, not to improve template text. Polishing templates is "polishing a turd" — Paul's words, locked directive.
- **Score interpretation:** If 7/10 cards are templates, the product is broken. The score reflects a broken product, not a "template diversity issue."
- **Root cause priority:** When template cards appear, investigate: (1) Is the pregen pipeline running? (2) Is ESPN data being fetched for this match? (3) Is Sonnet polish succeeding? (4) Is the cache key matching between write and read? Fix the pipeline, not the template.

### Monitoring System (3 layers)

Layer 1: Automated health checks every 2 hours (10 checks, Telegram alert). Layer 2: Daily morning report at 07:00 SAST. Layer 3: Post-deployment validation 30s after every restart.

### Freemium Gate — "Show the Prize, Hide the Path"

Bronze users see WHAT they could win but not HOW. 4 access levels: full, partial, blurred, locked. W28-IMPL (implementation of 18 templates + 4 violation fixes) is still pending.

### Settlement Pipeline

17 edges settled (4 March batch), 35% hit rate. Small sample, will stabilise. ISBets ghost fixture defence live (auto-void after 3+ days no result).

### Test Coverage

794+ tests (719 contract + 59 snapshot + 16 edge accuracy, as of 4 Apr). 5-layer testing schema in `testing/TESTING-SCHEMA.md`. Launch gate: zero L2/L3 failures for 7 consecutive days.

## Canonical Card Glow (LOCKED)

All glow effects on card templates (`match_detail.html`, `edge_detail.html`, `edge_picks.html`, `edge_summary.html`) use the **eb25301 canonical spec** — a two-layer radial gradient (base + screen-blend) with per-tier CSS classes and Paul-approved alpha values from 12-step iterative tuning.

**Full spec:** `/home/paulsportsza/bot/ops/CANONICAL-GLOW-SPEC.md`

**Critical rules:**
- Gradient centre is `at 50% 45%` — do not move it
- Per-tier classes (`logo-glow-{diamond|gold|silver|bronze}`) — never collapse to a single `{{ tier_color }}` CSS variable
- Alpha values are locked — do not change without explicit Paul approval via new brief
- Glow divs are direct children of `.header`, not inside sub-containers
- `.header` must have `overflow: hidden`; all other children `z-index: 1`

Any brief touching card template CSS MUST read `CANONICAL-GLOW-SPEC.md` before making changes.
