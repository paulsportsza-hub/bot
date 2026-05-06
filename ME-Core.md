# ME-Core.md — The Five Pillars
*Created: 4 April 2026. Updated: 5 April 2026. Launch: 27 April 2026 (22 days). Owner: COO. Authority: Founder-locked.*

**This document is the single source of truth for what MzansiEdge must achieve before launch.** Every agent working on any aspect of this project must read this document before starting work. Every brief must map to one of these five pillars. Every report must measure progress against them. Work that does not advance a pillar does not ship.

**⚠️ PILLAR EXPANSION (17 April 2026, T-10):** Marketing elevated from ops-module concern to full launch pillar (P5). Rationale: at T-10 the four product pillars are either green or in final polish. Launch success now hinges on acquisition/distribution, not code. See Pillar 5 below.

All other projects are paused. This is the only focus.

---

## The Five Pillars

| # | Pillar | What it means | Gate | Current |
|---|--------|---------------|------|---------|
| P1 | **Product Surface Quality** | Image cards are data-accurate, visually correct, complete, and signal-honest | 7.0/10 for 5 consecutive days on card QA rubric (no regression) | ⚠️ **Pillar reshaped 6 Apr.** Old narrative rubric (QA-32) retired. New card QA rubric (`ops/QA-RUBRIC-CARDS.md`) measures: data accuracy, completeness, visual correctness, signal honesty, render performance, caption discipline. IMG-W0 ✅ + IMG-W2 ✅ → IMG-W1 (renderer) running → W3 (Telegram integration) → W4 (QA). Haiku blockquote approved for ALL cards/tiers. |
| P2 | **Monitoring & Observability** | Every data source, runtime, and pipeline has automated health tracking | Dashboard live with alerts on all sources | P2-UX-POLISH ✅ Done: 4-tab professional layout, KPI hierarchy, exception-first display, 483ms cold load. P2-04 soak test running. **⚠️ Social Ops dashboard section needs pro-grade overhaul — UI-SOCIAL-OPS-REDESIGN-02 dispatched 17 Apr.** Narrative coverage metric denominator needs fix (17.1% total vs 63.3% edge-only). |
| P3 | **UI Overhaul** | Three-surface architecture (Bot + Channel + Group) with server-rendered image cards | Image card digest + tier drill-down + 2-3 audible notifications/day + three surfaces utilised | P3-06 ✅ Done: /settings live. Five-channel architecture LOCKED (16 Apr): TG Alerts (Diamond/Gold picks) + TG Community (seeded discussion) + WA Channel (curated digest) + IG (Reels discovery) + TikTok (B.R.U entertainment) + Bot (product). Full spec: `ops/MARKETING-CORE.md`. IMG card system in build (W1 running). |
| P4 | **Quant Models** | Edge quality powered by V3 probability models | Dixon-Coles + CLV + Glicko-2 live in edge_v2 pipeline | P4-07 ✅ Done: CLV pipeline fully wired. bet_log_writer called at all 4 edge-serving paths. Fire-and-forget + dedup. 899 tests pass. **P4 COMPLETE — all briefs landed.** |
| P5 | **Marketing & Acquisition** | Launch-ready go-to-market across five marketing surfaces: organic posting, paid Meta Ads, social calendar, SEO+GEO, and consolidated roadmap | Day-0: Meta Ads live, 2x SEO pillar posts shipped, organic posting SLAs green, llms.txt + Bing indexed. Day-30: 1,500 organic clicks/mo + Meta Ads ROAS ≥1.5 or kill. Day-90: 25+ referring domains, DR trending to 20, first data-moat release. | **New pillar 17 Apr 2026.** Canonical index: `ops/MARKETING-ROADMAP.md`. Five surfaces wired: `ops/MARKETING-CORE.md` (organic), `COO/PAID-ADS-ROADMAP.md` (Meta Ads), `ops/SOCIAL-CALENDAR.md` (B.R.U.), `ops/SEO.md` (SEO+GEO full playbook with 18 reserved brief IDs), and this pillar as the launch gate. |

**All five pillars are equally important. None are optional. They are the launch gate.**

---

## Pillar 1: Product Surface Quality

**Goal:** Every image card a user sees is data-accurate, visually correct, complete for its sport, and signal-honest. Server-rendered Playwright + Jinja2 HTML→PNG cards are the product surface — NOT text messages, NOT long narratives. Scores 9.0+ on the card QA rubric (`ops/QA-RUBRIC-CARDS.md`) across all card types. Quality must not regress.

**⚠️ PILLAR RESHAPED (6 April 2026 — Paul-locked, non-negotiable):**
The old "Narrative Quality" pillar measured rich text narratives, template rates, and narrative richness scores. That era is over. MzansiEdge now delivers server-rendered image cards via Playwright + Jinja2 (Pillow abandoned after 4 failed iterations). The product surface is pixels, not paragraphs. Quality means: the data on the card is correct, the visual rendering is clean, the signals are honest, and the Haiku-generated blockquote adds flavour without inventing facts.

**Image Card System (updated 6 April 2026):**
- **3 card types:** Edge Picks (merged — replaces old Edge Summary + Tier Page into one card), My Matches, Edge Detail. No separate Tier Page. No footer bar on any card.
- **Playwright + Jinja2 renderer** (`bot/card_renderer.py`) — HTML/CSS templates → PNG screenshot at 2x device scale (480px CSS → 960px output). Pure data→pixels, no LLM in the render path.
- **Edge Picks card:** Compact tier summary line in header + pick rows directly below, max 4 per image, page-based pagination. Each pick has a [N] number matching the Telegram button below. Numbered edge-to-button mapping is a core UX requirement.
- **Haiku verdict renders INSIDE the image (ALL cards, ALL tiers).** Claude Haiku generates a short, punchy verdict paragraph from verified DB data ONLY. Telegram caption is a minimal one-liner for notification preview only. Haiku processes ONLY our DB fields. NO LLM general knowledge. NO hallucination.
- **Minimal captions only** — no blockquotes, no analysis text below the image. Caption serves as notification preview. All rich content lives in the rendered PNG.
- **No team logos at launch** — cut for unpredictability. Revisit post-launch.
- **Accuracy is 10/10 non-negotiable** — every number on every card must match the source DB. Stale odds flagged visually.
- **QA rubric:** `ops/QA-RUBRIC-CARDS.md` — 7 dimensions replacing the old 4-dimension narrative rubric. See rubric for full scoring criteria.
- **QA measures all card types** across all sports. Edge-only metrics are not the product experience.

**Benchmark (6 April 2026 → updated 21 April 2026):** Launch gate is 9.0 on the card QA rubric (raised from 7.0 — Paul override, new rubric v3.0). D3 visual scoring uses `claude-opus-4-7` vision model. Priority is data accuracy and visual correctness, not narrative richness.

### Verdict Model Split (LOCKED 8 April 2026 — Paul decision)

**Edge Detail cards → Sonnet.** My Matches cards → Haiku. These are different products with different quality bars. Do not apply the Haiku spec to Edge Detail cards.

| Card type | Model | Max tokens | Voice |
|-----------|-------|-----------|-------|
| Edge Detail | `claude-sonnet-4-6` | 110 | SA sports pundit, nicknames, manager names, SA slang |
| My Matches | `claude-haiku-4-5-20251001` | 60 | Single sentence ≤80 chars, data-anchored |

**Note:** VERDICT-MODEL-TEST-01 (8 April) will produce a side-by-side Haiku/Sonnet comparison on live Edge Detail cards. Paul reviews output before any model change is considered for Edge cards. Until that report is reviewed and a new decision is locked, Sonnet is the Edge Detail standard.

---

### Edge Detail Verdict Spec (LOCKED 8 April 2026)

**Purpose:** Every Edge Detail card carries a short, punchy, data-driven verdict that demonstrates knowledge and summarises the edge. SA sports pundit voice — like a sharp bru explaining the bet to a mate at the pub.

**Wire point:** `_generate_verdict()` / `_generate_verdict_constrained()` in `bot/bot.py`. Pre-computation path: `pregenerate_narratives.py` → `narrative_cache.verdict_html`.

**Model parameters:**
- Model: `claude-sonnet-4-6`
- Temperature: `0.5`
- Max tokens: `110`

**Output contract:**
- 2 sentences maximum, then one final call line (e.g. "Back the draw." / "Take United.")
- SA pundit voice: nicknames (Amakhosi, The Bucs, Canes), manager names (Amorim, Slot), plain English form ("5 wins on the bounce")
- Must cite at least one number from the data (EV%, odds, form record, H2H)
- FORBIDDEN: stadium names, player names not in DB, invented stats
- ABSOLUTELY FORBIDDEN: fabricated venue references ("at Stamford Bridge" → hard reject)

**Output contract:**
- Single sentence, **≤80 characters** (hard limit, truncate at boundary if model exceeds)
- Must be **data-anchored** — must cite at least one of: EV%, odds, fair-value probability, win rate, form streak, H2H record, injury impact
- No general knowledge ("Liverpool are historically strong at Anfield" → ❌)
- No hallucination ("Salah scored 12 goals last month" without DB source → ❌)
- No hedging language ("could", "might", "possibly")
- Active voice, present tense
- Lowercase the team names exactly as the DB stores them

**Input (what Haiku sees):** A flat dict of verified fields from `build_verified_data_block` only — no free text, no narrative, no scraped context. Specifically: home/away, league, edge_score, ev_pct, fair_value_prob, market_odds, opening_odds, signals_lit (list), form_home (last 5), form_away (last 5), h2h (last 5 results), injury_count, top_tipster_pct.

**System prompt skeleton:**
> You are a sports betting analyst writing a single-sentence verdict for an edge card. You receive only verified database fields. You MUST cite at least one number from those fields. You MUST NOT use general knowledge about teams, players, leagues, or history. You MUST NOT hedge. Output one sentence ≤80 characters in present tense.

**Examples (good):**
- "Brentford home form 5W in 5 makes 3.52 on Everton a +3.6% EV mispricing."
- "TS Galaxy at 2.60 vs Polokwane prices a 38% win when fair value is 40%."
- "Chelsea draw at 3.75 vs Man Utd carries +28% market overlay on draw history."

**Examples (bad — auto-reject):**
- "Liverpool always struggle at Stamford Bridge." (general knowledge, no number)
- "This could be a value bet if form holds." (hedging, no data)
- "A great pick from our model." (no data, no specifics)

**Fallback behaviour:**
- If Haiku call raises any exception → return empty string
- If output >80 chars → truncate at last word boundary before 80
- If output fails the "must cite a number" guardrail (regex check for digit) → return empty string
- Empty string → template hides the Verdict section entirely (no placeholder, no skeleton)

**Failure handling:** Use `log.warning` with `match_key`, exception type, and prompt size. Never `log.debug`. Never silent. (Lesson: REBUILD-02 had to elevate `_enrich_tip_for_card`'s silent debug handler — Verdict wiring inherits the same standard.)

**Cost ceiling:** ≤$0.05 per 1000 cards at current Haiku pricing. If a daily monitoring sweep shows higher, COO investigates prompt bloat or runaway retries.

### Current State (6 April 2026)
- **Image Card System build in progress.** IMG-W0 (Assets & Foundation) ✅ + IMG-W2 (Data Adapter) ✅ → IMG-W1 (Card Renderer) 🔄 running → IMG-W3 (Telegram Integration) next → IMG-W4 (QA).
- **Old QA-32 (narrative rubric): 8.37 CONDITIONAL — now retired.** The narrative QA rubric measured text quality. The new card QA rubric (`ops/QA-RUBRIC-CARDS.md`) will be applied starting from IMG-W4. Old P0 defects (hallucinate, odds mismatch) are structurally eliminated by the image card system — cards render from verified DB data only.
- **Haiku blockquote approved (6 Apr):** Short, punchy analysis paragraph for ALL cards regardless of tier. Haiku processes DB fields only. Affordable, adds flavour. Will be wired into card_pipeline.py as a pre-render step.
- **P1-BUILD-30 ✅ Done (5 Apr):** All 4 QA-30 defects fixed. D-08 Setup fallback in `edge_detail_renderer.py`. D-09 composite seed in `narrative_spec.py`. D-10a Neutral Analysis stripped from `bot.py`. D-10b `_display_team_name()` canonical casing. 12 new tests, 899 contracts pass. Commits: `434a20f`, `f0c8040`. Bot restarted.
- **P1-INV-29 ✅ Done (5 Apr):** All 7 QA-29 defects traced to exact file:function:line targets by Opus investigation.
  - **D-01 (P1)** CTA odds mismatch — `bot.py:7222` uses broken `max()` on nested dicts instead of `_select_best_bookmaker_for_outcome()`. Single-line fix.
  - **D-02 (P1)** EV mismatch — narrative bakes EV into cached HTML at generation time; footer reads fresh EV. Stale cache = divergent numbers. Needs cache invalidation or serve-time injection.
  - **D-03 (P2)** Duplicate header — outer header at `bot.py:2612` + inner header from `_inject_narrative_header()` both concatenated. Strip one.
  - **D-04 (P2)** Empty AI-ENRICHED card — PSL teams not in ESPN. `get_match_context()` returns empty, LLM generates generic filler. Needs local DB fallback (team_ratings + match_results).
  - **D-05 (P2)** Broadcast lookup failed — `fuzzy_match_broadcast()` missing PSL team aliases. Add aliases + league-level default channels.
  - **D-06 (P3)** Missing Setup in instant-baseline — `_build_edge_only_section()` has no Setup. By design but fixable — add minimal context.
  - **D-07 (P2)** Sport coverage skew — `calculate_edge_v2()` only invoked for soccer/cricket by cron. Rugby/MMA/boxing edges not computed.
- **P1-PREGEN-30 + QA-30 ✅ Done (5 Apr):** Pregen: 49/55 generated, 0 failures. W84 coverage 86.4% (19/22 upcoming). QA-30: 6.02 FAIL. 3 new defects:
  - **D-08 (P1)** Template cards missing Setup section — `_section_team_context()` in `edge_detail_renderer.py:495-498` returns `""` when `mep_met=False` (no context). No fallback Setup exists in CLEAN-RENDER-v2 path. W84 path has `_render_setup_no_context()` (line 1456) but CLEAN-RENDER was never given an equivalent. Fix: add no-context Setup fallback using EdgeDetailData fields.
  - **D-09 (P2)** Team description verbatim reuse — `_pick()` in `narrative_spec.py:810-812` seeds with team name only. `_render_team_para()` (line 1360) passes only `name` as seed. Same team = same hash = same paragraph. Fix already exists in `_render_setup_no_context()` (line 1621-1623) which uses composite seed. Apply same pattern: add `opponent_name` to seed.
  - **D-10a (P2)** "— Neutral Analysis" suffix visible — appended at `bot.py:16908-16910` outside `<b>` tag, baked into cache at line 17086. Fix: strip before caching or remove entirely.
  - **D-10b (P2)** Team name case inconsistency — `_teams_from_vs_event_id()` at `bot.py:6797-6798` uses `.title()` ("Ts Galaxy"). Fix: replace with `_display_team_name()` which uses canonical `DISPLAY_NAMES` dict.
- **Arbiter gate: Day 0 — READY TO START.** QA-31 passed 7.0 → P1-06 ARBITER-SETUP now unblocked. Once Arbiter is live, 5-clean-days clock starts on first 7.0+ Arbiter run.
- Previous BUILD fixes (4 Apr): KEY-MISMATCH ✅, INJURIES ✅, NEWS ✅ — all still valid.
- w84 coverage: **68.8%** (AI-ENRICHED only: ~52.7% per dashboard). Soccer 75%, Rugby 33%, Cricket 11%, MMA 0%, Boxing 0%.
- Template-path distribution: TEMPLATE 5%, AI-ENRICHED 52.5%, INSTANT-BASELINE 42.5%.
- 794+ tests passing. All pre-merge gates green.

### Remaining Briefs (in order)

| Brief ID | Title | Type | Agent | Depends On | Status |
|-----------|-------|------|-------|------------|--------|
| P1-01 | PREGEN-CYCLE-POST-FIXES — Regenerate all narratives with new evidence | Execute | Sonnet | BUILD fixes landed | ✅ Done (5 Apr) — w84 68.8%, 61 generated/0 failed |
| P1-02 | QA-29 — Telethon E2E quality assessment (target 7.0) | QA | Opus | P1-01 | ✅ Done (5 Apr) — 6.61 FAIL, 7 defects |
| P1-INV-29 | INVESTIGATE-QA29-DEFECTS — Map all 7 defect root causes to exact code targets | Investigate | Opus | P1-02 | ✅ Done (5 Apr) — all 7 mapped to file:line |
| P1-BUILD-29 | FIX-QA29-DEFECTS — Fix D-01 through D-06 (6 code/structural defects) | Build | Sonnet | P1-INV-29 | ✅ Done (5 Apr) — 6 fixes, 18 tests, 888 total pass |
| P1-03 | FIX-COVERAGE-GATE — Sport-specific evidence thresholds for MMA/Boxing/Cricket | Build | Sonnet | P1-BUILD-29 | Ready to brief (D-07 is pipeline fix) |
| P1-04 | FIX-LINEUP-RENDERER — Deterministic renderer for lineup availability data | Build | Sonnet | P1-BUILD-29 | Ready to brief (AC-3 partial from INJURIES) |
| P1-05 | FIX-MMA-NAME-ORDER — Normalize firstname_lastname vs lastname_firstname keys | Build | Sonnet | P1-BUILD-29 | Ready to brief (flagged by KEY-MISMATCH) |
| P1-PREGEN-30 | PREGEN-CYCLE-30 — Regenerate narratives post-fix, then QA-30 | Execute + QA | Sonnet→Opus | P1-BUILD-29 | ✅ Done (5 Apr) — 6.02 FAIL, 3 new defects |
| P1-INV-30 | INVESTIGATE-QA30-DEFECTS — Map D-08/D-09/D-10 to exact code targets | Investigate | Opus | P1-PREGEN-30 | ✅ Done (5 Apr) — 4 defects mapped to file:line (D-08, D-09, D-10a, D-10b) |
| P1-BUILD-30 | FIX-QA30-DEFECTS — Fix D-08 Setup fallback + D-09 seed + D-10a/b artifacts | Build | Sonnet | P1-INV-30 | ✅ Done (5 Apr) — 4 fixes, 12 tests, 899 total |
| P1-PREGEN-31 | PREGEN-CYCLE-31 — Regenerate narratives post-BUILD-30, then QA-31 | Execute + QA | Sonnet→Opus | P1-BUILD-30 | ✅ Done (5 Apr) — 7.40 PASS. 49/55 generated, W84 63.3%. **7.0 GATE CLEARED.** |
| P1P3-INV | INVESTIGATE — Map rendering pipeline, audit data sources, design card schema + Haiku prompt | Investigate | Opus | P1-PREGEN-31 | ✅ Done (5 Apr) — 10 ACs passed. 4 additional DBs discovered (combat_data.db, enrichment.db, tipster_predictions.db, bot cache). Card schema + Haiku prompt designed. Coverage projection: 17.1%→~92%. |
| P1P3-BUILD | Implement structured card format + wire additional data sources | Build | Sonnet | P1P3-INV | ✅ Code complete (5 Apr) — 853-line `card_pipeline.py`, 4 DBs wired, 971 tests pass. Awaiting P1P3-VERIFY for coverage + grep confirmation. [Notion](https://www.notion.so/339d9048d73c817c892ecf3c23c8a2ef) |
| P1-QA-32 | QA-CARD-PIPELINE — First QA of card_pipeline.py product surface (Telethon E2E, 16 cards) | QA | Opus | P1P3-BUILD | ✅ Done (5 Apr) — 8.37 CONDITIONAL PASS. 2 P0 defects (hallucinate, odds mismatch). Without P0: 8.93. Template 14%, 8/16 >1024 chars. Next: P0-HALLUCINATE fix. [Notion](https://www.notion.so/) |
| P1P3-DATA-AUDIT | Full server data source inventory + dashboard integration map | Investigate | Opus | None | ✅ Done (5 Apr) — 28 SQLite files catalogued, 8 orphaned sources found, 18 empty DBs to clean, 3 stale pipelines flagged. [Notion](https://www.notion.so/339d9048d73c817a8821ecd83bf1a3d2) |
| P1P3-VERIFY | Pregen cycle + template marker scan + coverage report | Verify | Sonnet | P1P3-BUILD | 📥 Pending — [Notion](https://www.notion.so/339d9048d73c8175bcb4c66664a3c577). Run pregen, grep 7 banned phrases, report coverage ≥50%, export 10 sample cards. |
| P1-06 | ARBITER-SETUP — Daily automated QA with regression alerts (card format rubric) | Build | Opus | P1P3-VERIFY | **Blocked on P1P3-VERIFY** — QA rubric needs updating to score structured cards, not long-form narratives. |
| P1-07+ | Regression fixes as surfaced by Arbiter | Build | Sonnet | P1-06 | Rolling |

### Measurement (Card QA Rubric — 7 dimensions)
- **Data Accuracy (30%):** Every number on every card matches source DB. Auto-fail on any hallucinated data point.
- **Data Completeness (15%):** Sport-specific evidence thresholds met (form, H2H, injuries, odds per sport).
- **Visual Correctness (15%):** Tier colours, font rendering, layout spacing, badge rendering all match spec.
- **Graceful Degradation (10%):** Missing data produces "—" or empty space, never crashes, never shows placeholder text.
- **Render Performance (5%):** <500ms per card, single-threaded Pillow.
- **Signal Honesty (15%):** Confidence bar, EV %, signal dots all match underlying edge_v2 data. No inflation.
- **Caption Discipline (10%):** Captions are minimal one-liners for notification preview only. All analysis/verdict text renders INSIDE the image in the VERDICT section. No blockquotes.
- **Full rubric:** `ops/QA-RUBRIC-CARDS.md`
- **5-clean-days clock:** Starts when Arbiter produces 9.0+ on day 1 using card rubric. Resets on any regression below 9.0.

---

## Pillar 2: Monitoring & Observability

**Goal:** Every data source, scraper, pipeline, and runtime metric is tracked on the Admin Panel dashboard with automated staleness alerts to EdgeOps. No data gap goes undetected for more than 6 hours. Nothing relies on human memory.

### Current State (5 April 2026)
- Admin Panel live at `:8501` with Task Hub, Data Health, Social Media views
- **P2-01 INVESTIGATE-MONITORING ✅ Done (5 Apr):** Full audit mapped 42 data sources across 12 categories. Only 18/42 (43%) currently monitored. 5-table health schema designed.
- **P2-02 BUILD-MONITORING-DASHBOARD ✅ Done (5 Apr):** 5-table schema migrated. `health_checker.py` sweeps 42 sources in 0.4s every 30 min (cron). Admin Panel `/admin/health` rebuilt with real-time status indicators, freshness charts, API quota tracking. 14 new tests, 799 contracts pass. All 13 acceptance criteria met.
- **P2-03 BUILD-MONITORING-ALERTS ✅ Done (5 Apr):** `scripts/health_alerter.py` (393 lines). EdgeOps Telegram alerts for staleness/failures (SO #20 enforced — contract test blocks public channel). 2-hour dedup via SQLite. Recovery alerts when sources come back healthy. Daily 07:00 SAST summary digest. API quota alerts (>80% usage). Integrated into health_checker.py 30-min cron. 20 new tests, 926 total pass. All 13 ACs met. Also fixed 3 pre-existing bugs: health_alerter forbidden chat_id in docstring, dedup timestamp format mismatch, missing model_probability in sport-specific SPORT_WEIGHTS.
- **P2-UX-DASH ✅ Done (5 Apr):** Unified System Health dashboard live at `/admin/health`. Merged System Health + Data Health tabs. 8-card KPI strip (System Health Score, Active Scrapers, Narrative Coverage, Active Alerts, CPU, RAM, Sentry Issues, Upcoming Matches). 11 panels: Source Health Monitor, Sport Coverage Matrix (Chart.js), Server Resources, Sentry Issues, Process Monitor, API Health, Scraper Health, Data Freshness, API Quota Tracker, Alert History 24h, Rendering Path Stats. All data from live DB queries (60s cache). `/admin/system` redirects to `/admin/health`. Old renderers left as dead code. Mobile-responsive. Cold load <2s.
- **P2-QA-DASH ✅ Done (5 Apr):** 14 Playwright E2E tests, all pass. System Health 53.0%, Active Scrapers 0/8, Narrative Coverage 48.6%, Active Alerts 13. Query perf fix: narrative_coverage 16.6s→0.26s. 971 total tests. **Next: P2-04 (48-hour soak test).**

### What Must Be Monitored

| Data Source | Table/Location | Staleness Threshold | Current Gap |
|-------------|---------------|---------------------|-------------|
| SA Odds (8 bookmakers) | odds_latest | 4 hours | No staleness alert |
| Sharp Lines (Pinnacle, Betfair, etc.) | sharp_odds | 12 hours | No staleness alert |
| ESPN Context | espn_context / enrichment.db | 24 hours | No monitoring |
| Match Lineups | match_lineups | 24 hours per matchday | No monitoring |
| News Pipeline | news_articles (odds.db) | 24 hours | Fixed today, no alert |
| Line Movements | line_movements | 12 hours | Only 2 matches in 24h — no alert |
| MMA Fighter Records | mma_fighters | 7 days | No monitoring |
| Standings (Rugby/Cricket) | standings tables | 7 days | No monitoring |
| Pregen Pipeline | narrative_cache | ⛔ DEPRECATED — kill cron (P0-KILL-PREGEN). Was burning 4.5M tokens/day for narratives nobody sees | No monitoring |
| Edge Pipeline | edge_results | 6 hours | No monitoring |
| Scraper Runtimes | cron logs / Sentry | Per-run failure detection | Sentry exists but no dashboard view |
| w84 Coverage | narrative_cache vs upcoming fixtures | Daily | No tracking |
| Template-path % | narrative_cache rendering_path | Daily | No tracking |

### Remaining Briefs (in order)

| Brief ID | Title | Type | Agent | Depends On | Status |
|-----------|-------|------|-------|------------|--------|
| P2-01 | INVESTIGATE-MONITORING — Map all data sources, define health schema, design dashboard | Investigate | Opus | None | ✅ Done (5 Apr) — 42 sources, 5-table schema |
| P2-02 | BUILD-MONITORING-DASHBOARD — Implement health checks + Admin Panel integration | Build | Sonnet | P2-01 | ✅ Done (5 Apr) — 42 sources, 0.4s sweep, 14 tests |
| P2-03 | BUILD-MONITORING-ALERTS — EdgeOps Telegram alerts for staleness/failures | Build | Sonnet | P2-02 | ✅ Done (5 Apr) — 393 lines, 20 tests, 926 total |
| P2-UX-DASH | UNIFIED-SYSTEM-HEALTH — Combine System Health + Data Health into one dashboard, UX overhaul, wire all sources | Build | Sonnet | P2-03 | ✅ Done (5 Apr) — unified view, 8 KPIs, 11 panels |
| P2-QA-DASH | PLAYWRIGHT-DASHBOARD-QA — E2E tests verifying every dashboard number matches DB reality | QA | Sonnet | P2-UX-DASH | ✅ Done (5 Apr) — 14 tests pass, 971 total, 16.6s→0.26s perf fix |
| P2-04 | VERIFY-MONITORING — 48-hour soak test, confirm all sources reporting accurately | QA | Sonnet | P2-QA-DASH | 🔄 Dispatched (5 Apr) — Notion: 339d9048d73c81999001de26095309ab |
| P2-UX-POLISH | DASHBOARD-UX-OVERHAUL — Professional diagnostic dashboard patterns (research: reference/ops-dashboard-patterns.md) | Build | Sonnet | P2-QA-DASH | ✅ Done (5 Apr) — 4-tab layout, exception-first, KPI hierarchy, 14 E2E tests, 483ms cold load. **⚠️ Narrative coverage metric needs denominator fix (shows 17.1% total vs 63.3% edge-only).** |
| DASH-RAG-FIX | RAG threshold recalibration + new data source wiring — fix colour semantics (BLACK→GREY for on-demand), wire enrichment.db/combat_data.db/tipster_predictions.db into monitoring | Build | Sonnet | P2-UX-POLISH | 📥 Pending — Notion: [339d9048d73c81059f6ffa2e6fa11395](https://www.notion.so/339d9048d73c81059f6ffa2e6fa11395) |

### Measurement
- **Sources monitored:** 13/13 (see table above)
- **Alert latency:** <30 minutes from threshold breach to EdgeOps notification
- **False positive rate:** <1/day after soak test
- **Dashboard accuracy:** Admin Panel reflects true state within 5 minutes

---

## Pillar 3: UI Overhaul

**Goal:** The Telegram bot delivers a world-class mobile experience. Users see the full picture in 2 seconds and reach any detail in one tap. The bot matches the best information-dense bots on Telegram.

**⚠️ P1+P3 CONVERGENCE (6 April 2026 — Paul-locked):** P1 (product surface quality) and P3 (UI overhaul) are fully coupled. Server-rendered Pillow image cards ARE the product surface. The same work that matches the gold standard UX also solves the data accuracy problem — cards render directly from verified DB fields with zero LLM hallucination risk in the render path. Haiku adds a short blockquote flavour text from DB data only. The gold standard is `reference/BOT-UX-PHILOSOPHY.md` ("Redesigning MzansiEdge for mobile-first clarity").

**⚠️ FIVE-CHANNEL ARCHITECTURE (16 April 2026 — supersedes three-surface model):**
MzansiEdge operates across five content channels + Bot. Full spec: `ops/MARKETING-CORE.md`.
- **TG Alerts** (`@MzansiEdgeAlerts`) — primary broadcast. Diamond/Gold Edge Pick cards + P&L recaps. 3/day, max 4. NRGP footer mandatory.
- **TG Community** (`@MzansiEdge`) — seeded discussion. Polls, match threads, prompts. 4/day. NOT a second alerts channel.
- **WhatsApp Channel** — curated daily digest. Top 20-30% of picks. 1-2/day. 8-12% view rate ceiling accepted.
- **Instagram** — discovery engine. 1 Reel/day + 2-3 Stories + 1-2 carousels/week.
- **TikTok** (`@heybru_za`) — B.R.U entertainment. Compliance-safe. Ramping to daily over 8 weeks.
- **Bot** (`@mzansiedge_bot`) — the personalised product. Image cards, /today, /settings, tier drill-down.
- **Mini App** (future) — React dashboard for power users. Post-launch.

### Design Principles (from research document, LOCKED)
1. **One message per concept.** No bundling unrelated data.
2. **Summary first, detail on demand.** Image card with tier buttons → tap to drill down via message editing.
3. **Progressive disclosure.** Expandable blockquotes for analysis, not visible by default.
4. **2-3 audible notifications per day max.** Morning digest (audible) + Gold pre-match (audible) + everything else silent.
5. **Miller's Law (7 +/- 2 items).** Max 5 items visible before requiring navigation.
6. **Hick's Law.** Fewer choices = more action. One primary CTA per message.
7. **Consistent templates.** Every message type follows the same structure: emoji marker, bold header, monospace numbers, expandable analysis, one primary button.

### Target Message Architecture

```
DAILY FLOW:
08:30 [audible]  → Image card digest (photo + inline buttons: Gold / Silver / Bronze / Stats)
  ↳ tap Gold    → Message edits to show Gold picks with expandable analysis
  ↳ tap Silver  → Message edits to show Silver picks
  ↳ tap Back    → Returns to digest summary
14:00 [audible]  → Pre-match alert (Gold only, 2-4h before kickoff)
Post-match [silent] → Compact result with outcome + running totals
21:00 [silent]   → Evening recap + tomorrow teaser
```

### Current State (5 April 2026)
- **P3-01 INVESTIGATE-BOT-UX ✅ Done (5 Apr):** Full architecture map of bot.py (23,251 lines). Build spec produced.
- **P3-02 BUILD-BOT-MESSAGE-SYSTEM ✅ Done (5 Apr):** New `message_types.py` module with 4 pure renderer classes (DigestMessage, DetailMessage, AlertMessage, ResultMessage). `/today` command wired to DigestMessage. Stale hash detection for bot restart recovery. 83 new tests, 865 total pass. No circular imports. Edit-based drill-down foundation in place.
- **P3-03 BUILD-BOT-IMAGE-CARDS ✅ Done (5 Apr):** `bot/image_card.py` (260 lines). Pillow-based 1080×1080px PNG image cards with brand colors (Carbon Black bg, orange gradient accents). Tier badges (Diamond/Gold/Silver/Bronze with correct emojis + colors), confidence bars, B.R.U. avatar, wordmark. Max 5 matches per card (Miller's Law). `DigestMessage.build_photo()` added to message_types.py — returns InputMediaPhoto. Tier filter inline keyboard buttons. 18 new tests, 851 total pass. Also fixed 3 pre-existing bugs from other waves. **Bot.py wiring (actual send_photo call) NOT in this brief — next step (P3-WIRE).**
- **P3-WIRE ✅ Done (5 Apr):** `/today` sends 1080×1080 PNG image card via `send_photo()`. Tier filter buttons (💎🥇🥈🥉📊) → `edit_message_caption` with filtered picks. `digest:back` restores card. Morning teaser `_morning_teaser_job` uses `send_photo` with `RuntimeError` fallback to text. 11 new tests, 860 contracts pass. Bot restarted, live.
- **P3-04 ✅ Done (5 Apr):** Consistent branded templates across all 4 message types. Expandable `<blockquote expandable>` for narratives. Monospace `<code>` for all numbers (odds, EV, hit rate, ROI, P/L). P/L in Rands on ResultMessage. Confidence % on DetailMessage. "View Details" button on AlertMessage. 29 new tests, 860 contracts pass.
- **P3-05 ✅ Done (5 Apr):** `bot/notification_budget.py` created. SQLite-backed per-user daily audible counter. MAX_AUDIBLE_PER_DAY=3, fails open (if SQLite errors → sound plays). `_pre_match_gold_alert_job` (hourly, checks for Gold+ matches 2-4h before kickoff). `_budget_reset_job` (00:00 SAST daily). `asyncio.to_thread()` for sync SQLite in async handlers. 13 new tests, 945 total pass. Bot restarted with new jobs.
- No `/settings` command yet (P3-06)

### Remaining Briefs (in order)

| Brief ID | Title | Type | Agent | Depends On | Status |
|-----------|-------|------|-------|------------|--------|
| P3-01 | INVESTIGATE-BOT-UX — Map current bot.py message architecture (every sendMessage, callback, keyboard builder) | Investigate | Opus | None | ✅ Done (5 Apr) — 23,251-line map + build spec |
| P3-02 | BUILD-BOT-MESSAGE-SYSTEM — Split monolith into digest/detail/alert/result message types with message editing | Build | Sonnet | P3-01 | ✅ Done (5 Apr) — message_types.py, 83 tests, 865 total |
| P3-03 | BUILD-BOT-IMAGE-CARDS — Python Pillow daily summary card (team matchups, tiers, confidence, times) | Build | Sonnet | P3-02 | ✅ Done (5 Apr) — 260 lines, 18 tests, 851 total |
| P3-WIRE | WIRE-SEND-PHOTO — Wire image_card.py into bot.py send_photo call for /today and daily digest | Build | Sonnet | P3-03 | ✅ Done (5 Apr) — send_photo live, 11 tests, 860 pass |
| P3-04 | BUILD-BOT-TEMPLATES — Consistent message template system with expandable blockquotes | Build | Sonnet | P3-02 | ✅ Done (5 Apr) — 4 types templated, 29 tests, 860 pass |
| P3-05 | BUILD-BOT-NOTIFICATIONS — Staggered notification flow (audible budget, silent results, disable_notification) | Build | Sonnet | P3-02 | ✅ Done (5 Apr) — SQLite budget, MAX_AUDIBLE=3, 13 tests, 945 total |
| P3-06 | BUILD-BOT-SETTINGS — /settings inline keyboard (tier filters, sport filters, quiet hours) | Build | Sonnet | P3-05 | ✅ Done (5 Apr) — user_settings.py, SQLite, 26 tests, 899 contracts |
| P1P3-BUILD | *(Same brief as P1 table)* — Structured card format is the P1+P3 convergence build | Build | Sonnet | P1P3-INV ✅ | 📥 Pending — see P1 table for full details |
| P3-07 | QA-BOT-UX — Full Telethon E2E UX validation against design principles + card format | QA | Opus | P1P3-BUILD | Blocked on P1P3-BUILD |
| P3-08 | Paul phone review — Human UX testing on mobile | Human QA | Paul | P3-07 | Blocked |

### Post-Launch
- **Five-channel architecture is LOCKED** — roles defined in `ops/MARKETING-CORE.md`. Bot is primary product surface. TG Alerts broadcasts Diamond/Gold picks (3/day). TG Community runs seeded discussion (4/day). WA curates daily digest. IG + TikTok are discovery channels.
- **Mini App dashboard** — React-based, post-launch for power users. Tabbed pick browsing, performance charts, subscription management via Telegram Stars.
- **Channel content automation** — automated daily digest card + 1 free Bronze pick to Channel, results to Channel (silent). Requires IMG-W3 completion.

### Measurement
- **Messages per concept:** 1 (no multi-concept walls)
- **Taps to any detail:** ≤2 from digest
- **Audible notifications per day:** ≤3
- **Paul's phone test:** "Not scary to look at" (subjective but non-negotiable)
- **Button data:** All callbacks <64 bytes
- **Message length:** All messages <4096 chars, all captions <1024 chars

---

## Pillar 4: Quant Models

**Goal:** Replace the current Elo-based Layer 1 probability model with V3 quantitative models that produce sharper, more accurate edge detection. Better probability estimates → more real edges detected → higher tier quality → users trust the product.

### Current State (5 April 2026)
- **Edge V2 pipeline:** 7-signal composite. Layer 1 = Elo (basic), Layer 2 = Betfair Exchange sharp benchmark, Layer 3 = SA bookmaker consensus.
- **W1 CLV/EV Framework:** ✅ Complete (2 April). Foundation layer for measuring edge quality over time.
- **P4-01 BUILD-W1-PENDING ✅ Done (5 Apr):** All 4 CLV wiring items complete. DB migration script, CLV query API (`get_clv_for_edge()`), kill switch monitor + cron (65% negative CLV rate or avg<-8% threshold), closing odds backfill job (30 min post-kickoff). E2E test passed. 2 new crons deployed.
- **P4-02 INVESTIGATE-DIXON-COLES ✅ Done (5 Apr):** Full architecture plan produced. 6,029 historical matches available. Bivariate Poisson with tau correlation. <20s training time. Pooled model recommended. Build spec ready for P4-03.
- **P4-04 BUILD-GLICKO-CRICKET ✅ Done (5 Apr):** Cricket added to SPORT_CONFIGS (tau=0.5, HA=30, draw_prob=0.0 for T20). 39 teams rated from 260 matches. 6 upcoming IPL matches have Glicko-2 ratings.
- **P4-03 BUILD-DIXON-COLES ✅ Done (5 Apr):** `scrapers/elo/dixon_coles.py` (360 lines). Numpy-only Adam optimiser. 167 teams from 6,029 matches in 0.4s. τ correction, home advantage 1.237x, ρ=-0.0286. `get_dc_probability()` API in elo_helper.py. Runs as Step 4 of daily cron. 12 new tests, 776 contracts pass. **Gaps noted:** Feature flag USE_DIXON_COLES not confirmed. Brier score comparison vs Elo not reported (backtest function exists). Half-life 107 days vs brief's 180.
- **W3 Glicko-2:** All 3 sports live (soccer + rugby + cricket ✅).
- **P4-07 ✅ Done (5 Apr):** CLV pipeline fully wired. `_blw_fire_tips()` called at all 4 edge-serving paths via fire-and-forget `asyncio.create_task()`. `_bet_log_seen` in-memory set for dedup. `_load_tips_from_edge_results()` fixed to select `e.edge_id`. 14 new tests, 899 pass. **Pillar 4 is COMPLETE — all briefs landed.**
- **P4-05 INTEGRATE-V3-PIPELINE ✅ Done (5 Apr):** Dixon-Coles wired into edge_v2 via `collect_model_probability_signal()`. `USE_DIXON_COLES=True` feature flag. DC weight 0.27 for soccer (DC_SOCCER_WEIGHTS). CLV metadata (clv_avg, clv_sample_size) added to edge outputs — informational only, not in composite. Elo fallback for unknown teams. Backtest on 26 live matches: **+2.9 composite score** with DC ON vs OFF. Fixed missing `model_probability` in sport-specific SPORT_WEIGHTS for rugby/cricket/mma/boxing (set to 0.00). 9 new tests, 860 contracts pass. **V3 integration complete — all models live in edge_v2.**

### Remaining Briefs (in order)

| Brief ID | Title | Type | Agent | Depends On | Status |
|-----------|-------|------|-------|------------|--------|
| P4-01 | BUILD-W1-PENDING — Complete CLV wiring (DB migration, query API, kill switch, backfill) | Build | Sonnet | None | ✅ Done (5 Apr) — all 4 items, E2E passed |
| P4-02 | INVESTIGATE-DIXON-COLES — Architecture plan for Dixon-Coles implementation (data requirements, training pipeline, integration points) | Investigate | Opus | None | ✅ Done (5 Apr) — 6,029 matches, build spec ready |
| P4-03 | BUILD-DIXON-COLES — Implement Dixon-Coles model for soccer probability estimation | Build | Sonnet | P4-02 | ✅ Done (5 Apr) — 360 lines, 167 teams, 12 tests |
| P4-04 | BUILD-GLICKO-CRICKET — Complete Glicko-2 cricket leg (fixture matching fix) | Build | Sonnet | None | ✅ Done (5 Apr) — 39 teams, 3 sports live |
| P4-05 | INTEGRATE-V3-PIPELINE — Wire Dixon-Coles + CLV + Glicko-2 into edge_v2 scoring | Build | Sonnet | P4-03, P4-04 | ✅ Done (5 Apr) — DC wired, +2.9 composite, 9 tests |
| P4-06 | QA-EDGE-QUALITY — Backtest V3 edges against historical results, compare to V2 accuracy | QA | Opus | P4-05 | ✅ Done (5 Apr) — +1.4 composite, 40.8% hit, +20.7% ROI, KEEP DC=True |
| P4-07 | WIRE-CLV-PIPELINE — Wire bet_log_writer into edge serving so CLV fields populate | Build | Sonnet | P4-06 | ✅ Done (5 Apr) — all 4 serve paths wired, dedup, 14 tests, 899 pass |

### Measurement
- **Model accuracy (Brier score):** Dixon-Coles vs Elo on historical soccer data — must improve
- **Edge detection rate:** More edges detected per match day with V3 vs V2
- **Tier distribution:** More Diamond/Gold edges (V3 should produce sharper probabilities)
- **CLV tracking:** Closing line value measurement live and producing data
- **Backtest hit rate:** V3 edges on historical data vs V2 edges

---

## Post-Launch Backlog

Ideas parked for after launch. Not active. Each line is a one-paragraph spec captured at the moment of ideation; full briefs get written when the item is activated.

### AI Breakdown — On-Tap Real-Time Generation (Diamond-only) — captured 2 May 2026

**Premise (Paul, 2 May 2026):** AI Breakdown is a Diamond-tier feature with low click volume. Pregenning it daily wastes calls and pushes stale content. Generate on-tap when the user clicks the button. Latency tolerable. Strict prompt enforces multi-source confirmation.

**Architecture (decided in chat 2 May 2026):**
- On click: server pre-fetches a structured `evidence_pack` synchronously — `edge_results` row, last 6h `odds_snapshots`, `injuries_v2` both teams, `line_movement` last 24h, `recent_form` last 5, `h2h` last 5, venue, sportmonks manager quotes, ESPN preview, plus a server-side curated news cache (whitelist of BBC / ESPN / Sky Sports / official club RSS / sportmonks press feed; 30-min cron refresh into a new `match_news` table keyed by `(match_key, source, fetched_at)`).
- LLM never touches a database. LLM never calls web_search. All facts come from the pre-fetched evidence_pack. Strict prompt: *"Use ONLY facts present in EVIDENCE_PACK. Do not invent stats, quotes, or citations."*
- Cache key `(match_key, edge_revision_id)` with 5-min TTL — first Diamond user pays the 5–8s latency, the next 4 within the window are instant. Edge flip invalidates.
- Opus 4.7 for quality. Estimated cost at 100 Diamond subs × 5 unique taps/day × ~3000 tokens = ~$15/day, scales linearly.
- Validator gate: same telemetry-vocab / vague-content / team-token / closure-rule checks the verdict pipeline uses. Hard reject → fall back to a deterministic premium template (corpus-style but longer). No "best-effort serve" — the W84 lesson sticks.
- Loading UX: edit-message flow. Initial reply "🔮 Generating premium read..." → replace with final breakdown.
- Fallback rule: if the pre-fetch loses >2 data sources, render "Premium analysis warming up. Try again in 60s." Better than weak output.

**Why it's parked:** verdict pipeline is still failing as of 2 May. Don't add a second LLM surface until the deterministic verdict path is GO. AI Breakdown ships post-launch when the corpus stabilises.

**When to activate:** after launch day, after a clean QA-LIVE-CARDS-EVERY-ACTIVE pass, when Diamond subscriber count justifies the premium feature investment.

**Brief wave shape (when activated):**
1. `BUILD-NEWS-FEED-INGEST-01` (Sonnet - LEAD): cron + RSS adapters + `match_news` table for the source whitelist
2. `INV-AI-BREAKDOWN-ONTAP-01` (Opus Max - LEAD): map every existing AI Breakdown call site, the data pre-fetch surface, what's already in `card_data._synthesize_breakdown_row_from_baseline`, and the deferred-placeholder render path. Outputs file:line targets + evidence_pack schema + cache strategy + fallback ladder.
3. `BUILD-AI-BREAKDOWN-ONTAP-01` (Opus Max - LEAD): ship the on-tap path with cache, validator, fallback, loading UX

**Web-search note:** Paul asked whether we can let the LLM web-search at runtime (Anthropic native tool). Decision: no. Web-search-enabled LLMs hallucinate sources confidently; we don't control which sites they read; legal/brand exposure on betting content is real; reproducible QA becomes impossible. Server-controlled news fetch from a whitelist captures the same value safely.

---

## Master Timeline

```
══════════════════════════════════════════════════════════════
LOCKED ROADMAP (5 April 2026) — Paul-approved execution order
══════════════════════════════════════════════════════════════

COMPLETED (5 April — all prior briefs)
├── P1: 01, 02, INV-29, BUILD-29, PREGEN-30, QA-30, INV-30, BUILD-30  (all ✅)
├── P2: 01, 02, 03, UX-DASH, QA-DASH                                   (all ✅)
├── P3: 01, 02, 03, WIRE, 04, 05                                       (all ✅)
└── P4: 01, 02, 03, 04, 05, 06, 07  ★ PILLAR COMPLETE ★               (all ✅)

PHASE A — CRITICAL PATH + PARALLEL (5-8 April)  ★ COMPLETE ★
├── P1-PREGEN-31 + QA-31  [✅ DONE 5 Apr — 7.40 PASS — 7.0 GATE CLEARED]
├── P3-06  BUILD-BOT-SETTINGS  [✅ DONE 5 Apr]
├── P2-04  VERIFY-MONITORING 48h soak  [🔄 RUNNING]
├── P2-UX-POLISH  [✅ DONE 5 Apr]
└── P1P3-INV  INVESTIGATE card redesign  [✅ DONE 5 Apr — 10 ACs, 4 new DBs found]

PHASE A2 — IMAGE CARD SYSTEM BUILD (6-8 April)  ★ ACTIVE ★
├── P1P3-BUILD  [✅ CODE COMPLETE 5 Apr — 853-line card_pipeline.py, 4 DBs wired, 971 tests]
├── P1P3-DATA-AUDIT  [✅ DONE 5 Apr — 28 files, 8 orphans, 18 empty DBs, 3 stale pipelines]
├── IMG-W0  ASSETS & FOUNDATION  [✅ DONE 6 Apr — fonts, icons, card_templates.py, colour palette]
├── IMG-W2  DATA ADAPTER  [✅ DONE 6 Apr — card_pipeline.py structured fields: form, H2H, signals, injuries, key_stats, odds_structured]
├── IMG-PW2R  EDGE PICKS CARD  [✅ APPROVED — Playwright + Jinja2, merged Summary+Tier into one card, numbered [N] picks, max 4/page]
├── IMG-PW2R-FIX  EDGE-TO-EDGE CSS  [✅ APPROVED — black bleed wrapper, footer removed, sport emojis]
├── IMG-PW3  MY MATCHES CARD  [✅ APPROVED — two row variants (edge + upcoming), tight spacing]
├── IMG-PW4  EDGE DETAIL CARD  [✅ APPROVED — full analysis deep-dive, tier colours, signals, H2H]
├── IMG-PW5  MATCH DETAIL CARD  [✅ APPROVED — no-edge equivalent of Edge Detail]
├── INV-W3   WIRING INVESTIGATION  [📥 DISPATCHED — Opus, navigation state machine + data accuracy + button spec]
├── INV-P2   HEALTH DASHBOARD AUDIT  [📥 DISPATCHED — Opus, deprecated metrics + new card-era monitoring]
├── INV-P4   QUANT MODEL AUDIT  [📥 DISPATCHED — Opus, signal utilisation + calibration + edge hit rate]
├── P1P3-VERIFY  Pregen + grep + coverage report  [📥 PENDING]
│   Notion: https://www.notion.so/339d9048d73c8175bcb4c66664a3c577
├── DASH-RAG-FIX  Dashboard RAG threshold recalibration + data source wiring  [📥 PENDING]
│   Notion: https://www.notion.so/339d9048d73c81059f6ffa2e6fa11395
└── P2-04 soak continues in background

PHASE B — IMG INTEGRATION + SERVER MIGRATION (9-11 April)
├── IMG-W3  TELEGRAM INTEGRATION  [After all card templates approved — button wiring, callbacks, navigation flow]
├── IMG-W4  IMAGE CARD QA  [After IMG-W3 — new card QA rubric, all card types, all sports]
├── P1-06  ARBITER-SETUP  [After IMG-W4 — daily automated QA using card rubric]
│   Daily automated QA, 5-clean-days clock starts
├── P3-07  QA-BOT-UX  [After IMG-W3]
│   Full Telethon E2E UX validation against card format + design principles
└── OPS-MIGRATE  SERVER MIGRATION DO→Hetzner CPX52  [After all BUILD briefs]
    Provision → rsync → cron → DNS → verify → cut over
    12 vCPUs / 24 GB RAM / 480 GB SSD / €36.99/mo (was $96/mo)

PHASE C — HUMAN QA + ARBITER (12-18 April)
├── P3-08  Paul phone review on NEW server  [After P3-07 + migration]
├── P1-07+ Regression fixes  [Rolling — Arbiter surfaces, agent fixes]
└── Arbiter 5-clean-days clock running  [Must clear by ~20 Apr]

PHASE D — LAUNCH PREP (19-26 April)
├── 5-clean-days clock completes (if started ~12 Apr → clears ~17 Apr)
├── P3-08 fixes from phone review
├── DO server decommission (after 7+ days Hetzner stable)
└── Final launch readiness check — all 4 pillars green

DAY 22: 27 April — LAUNCH
```

### Parallelism Rules
- P1 (product surface) and P2 (monitoring) touch different files — can run in parallel
- IMG waves are STRICTLY sequential: W0 → W2 → W1 → W3 → W4. Each wave depends on the prior.
- P4 ★ COMPLETE — no further parallel constraints.
- **Server constraint:** 16GB RAM (upgraded 5 Apr). 2 agents can run concurrently.
- **Sequencing within pillars is strict.** Investigate → Build → QA. No shortcuts.

---

## Progress Tracking

**Updated after every brief completion and every QA run.**

### Pillar 1: Product Surface Quality
| Metric | Baseline (5 Apr) | Current (6 Apr) | Target |
|--------|------------------|---------|--------|
| Card QA Score | N/A (old rubric: 8.37) | **Awaiting QA-BASELINE-02B** — rubric v3.0 active (Opus 4.7 D3 vision, PASS ≥9.0) | 9.0+ sustained |
| IMG Card Types | 0/4 | **4/4 approved** — Edge Picks ✅, My Matches ✅, Edge Detail ✅, Match Detail ✅. All templates done. | 4/4 rendering |
| Haiku Blockquote | Not started | **Approved (6 Apr)** — all cards, all tiers. Wiring after W1 completes | Live on all cards |
| Data Accuracy | N/A | **Structural fix** — cards render from DB fields only, zero hallucination risk | 10/10 non-negotiable |
| Clean days at 9.0+ | 0 | **0** — clock starts on first Arbiter run using rubric v3.0 (QA-BASELINE-02B must PASS first) | 5 consecutive |
| Tests passing | 899 | **899+** (IMG-W1 adding 25+ new tests) | No regression |

### Pillar 2: Monitoring
| Metric | Baseline (4 Apr) | Current (5 Apr) | Target |
|--------|------------------|---------|--------|
| Sources monitored | 0/13 | **42/42 ✅** | 42/42 ✅ |
| Health sweep time | N/A | **0.4s per sweep** | <30s |
| Alert latency | None | **<30 min ✅** — EdgeOps alerts, 2h dedup, recovery | <30 min ✅ |
| Dashboard accuracy | Partial | **Real-time ✅ + E2E verified** — 14 Playwright tests pass, query perf 16.6s→0.26s | All sources live ✅ |
| Tests | 794+ | **971 total ✅** (+14 Playwright from P2-QA-DASH) | No regression |

### Pillar 3: UI Overhaul
| Metric | Baseline (4 Apr) | Current (5 Apr) | Target |
|--------|------------------|---------|--------|
| Message types | Monolith | **4 classes ✅** | 4 distinct types |
| /today command | Wall-of-text | **Image card + tier buttons ✅** | Image card digest ✅ |
| Tests | 794+ | **945 total ✅** (+13 from P3-05) | No regression |
| Image cards | None | **image_card.py ✅ + send_photo live** | Daily Pillow cards ✅ |
| Audible notifications/day | All | **≤3 ✅ (P3-05 done)** — SQLite budget, fails open | ≤3 ✅ |
| Paul phone test | "Scary" | Still legacy paths visible | "Not scary" |

### Pillar 4: Quant Models
| Metric | Baseline (4 Apr) | Current (5 Apr) | Target |
|--------|------------------|---------|--------|
| Layer 1 model | Elo | **Dixon-Coles LIVE ✅** | Dixon-Coles ✅ |
| CLV tracking | Framework only | **Fully wired ✅** — all 4 serve paths, fire-and-forget dedup (P4-07) | Live + producing data ✅ |
| Glicko-2 sports | Soccer + Rugby | **Soccer + Rugby + Cricket ✅** | All 3 done ✅ |
| V3 backtest improvement | N/A | **+2.9 composite score** | Measurable vs V2 ✅ |
| **P4 STATUS** | — | **COMPLETE — all 7 briefs landed** | ✅ |

---

## Social Content Positioning Policy (LOCKED 13 April 2026 — Paul decision)

MzansiEdge is a **sports intelligence platform**, not a licensed gambling operator. This distinction governs all social content.

**What this means for content:**
- Frame all content as sports analytics and edge intelligence — never as betting tips
- Captions reference edge scores, match intelligence, and analysis — never odds, bookmaker names, or stake amounts
- "Edge score: 57%" is correct. "Arsenal @ 4.25 (World Sports Betting)" is not
- The brand tagline "Bet. Better." is locked — but it does not override caption language rules

**Platform-specific rules:**
- **TikTok/Instagram/WhatsApp Channel/Facebook/LinkedIn:** Zero gambling language. No footer. No 18+. No NRGP. This is not legally required and actively hurts algorithmic reach.
- **Telegram/WhatsApp Group (closed community):** Light note only — `"18+ · Play Responsibly"`. Users are opted-in product members.

**Legal basis:** The National Gambling Act mandatory RG disclaimers apply to licensed operators (bookmakers). MzansiEdge does not accept wagers and is not a licensed operator. The ARB Code requires honesty but does not mandate specific footers for analytics services.

**Implementation:** `publisher/compliance_config.py` (SOCIAL-POSITIONING-01), `publisher/channels/tiktok.py` (TIKTOK-CAPTION-01). Any agent touching caption or compliance code must read this section first.

---

## Rules for All Agents

1. **Read this document before starting any brief.** If your brief doesn't map to a pillar, stop and check with COO.
2. **Report progress against pillar metrics.** Every report must include a "Pillar Progress" section stating which pillar the work advanced and by how much.
3. **Do not start work that regresses another pillar.** If a P3 change would break P1 narrative quality, flag it immediately.
4. **Challenge Rule applies to every brief.** If the approach is flawed, raise it before proceeding.
5. **Handoff Protocol applies to every brief.** If blocked, write a structured handoff document.
6. **The four pillars are the only priorities until launch.** No new features, no nice-to-haves, no side quests. Everything maps to P1, P2, P3, or P4.
7. **COO updates this document after every brief completion.** Progress tables, brief statuses, and timeline adjustments are maintained here, not in chat.

---

*This document is referenced at the top of CLAUDE.md. It supersedes all previous priority discussions, roadmaps, and informal plans. The four pillars are the launch gate. Ship all four or don't ship.*
