# Standing Orders Catalog (SO-CATALOG) — Canonical Index

> **Source of truth for every Standing Order (SO) governing MzansiEdge agents, dispatch, and runtime.** Notion canonical mirror under MzansiEdge Project Wiki (link in §Notion Mirror). Server canonical: this file.
>
> **Purpose:** every `[SO #N]` or `SO #N` reference across briefs, reports, role specs, ops modules, and Notion resolves to one row in this catalog. Original SO numbers preserved (gaps intentional). Authored by AUDITOR Lane B per SO-addition gate protocol — this catalog is read-only inventory; new SOs flow through AUDITOR for placement, then a follow-up sweep refreshes the catalog.

*Last updated: 5 May 2026 — FIX-DOC-SO-CATALOG-CANONICAL-01 — initial canonical build. Resolved SO #30 dual-definition collision (R1 from `INV-DOC-ADVERSARIAL-AUDIT-2026-05-05`): line-range read discipline retains #30; OCR_PROMPT immutability renamed to SO #47.*

---

## Roll-up totals

| Metric | Count |
|---|---|
| Total SOs in catalog | 34 |
| ACTIVE | 33 |
| CANDIDATE (pending audit landing) | 1 |
| SUPERSEDED | 0 (history note: SO #44 v1 "Codex 5.5 only executor" superseded by SO #44 Routing v1 binding rule, same number reused) |
| RETIRED | 0 |
| RENUMBERED | 1 (SO #30 OCR-immutability → SO #47, this brief) |
| Numbered gaps (unused) | #1, #5, #8, #12, #13, #16, #17, #21, #23–26, #37, #42 |

---

## Canonical table

| SO # | Title | Status | Source (server path) | Lock date | Anchor / line |
|---|---|---|---|---|---|
| #2 | Notion = single source of truth for operational memory | ACTIVE | `Notion Core Memory`; mirrored `bot/ops/DISPATCH-V2.md` | — | Notion `340d9048-d73c-81d2-b0be-d5dfca2dd8a6` · `DISPATCH-V2.md` L193 |
| #3 | Paul approves all external content | ACTIVE | `Notion Core Memory` | — | Notion `340d9048-d73c-81d2-b0be-d5dfca2dd8a6` |
| #4 | No new Make automation. Ever | ACTIVE | `bot/ops/TECHNICAL.md` | — | `TECHNICAL.md` L65 |
| #6 | Brand Bible v3 is the canonical brand reference | ACTIVE | `bot/ops/BRAND.md` | — | `BRAND.md` L14 |
| #7 | COO generates ALL images via NB Pro | ACTIVE | `Notion Core Memory` | — | Notion `340d9048-d73c-81d2-b0be-d5dfca2dd8a6` |
| #9 | Paul NEVER posts manually — Python publisher handles all publishing | ACTIVE | `Notion Core Memory` | — | Notion `340d9048-d73c-81d2-b0be-d5dfca2dd8a6` |
| #10 | Challenge Rule — every brief must include the verbatim "raise concerns before proceeding" instruction | ACTIVE | `bot/ops/DEV-STANDARDS.md` | 1 Apr 2026 | `DEV-STANDARDS.md` item 10, L61 |
| #11 | Handoff Protocol — every brief includes the verbatim handoff doc instruction | ACTIVE | `bot/ops/DEV-STANDARDS.md` | 1 Apr 2026 | `DEV-STANDARDS.md` item 11, L63 |
| #14 | Classify before discussing | ACTIVE | `bot/ops/DISPATCH-V2.md` (referenced; pre-split origin in retired CLAUDE.md SO-block) | — | `DISPATCH-V2.md` L194 |
| #15 | Workers return compressed state only | ACTIVE | `bot/ops/DEV-STANDARDS.md` | 17 Apr 2026 (moved from CLAUDE.md) | `DEV-STANDARDS.md` L16 |
| #18 | Every state change = Notion update in the same response | ACTIVE | `bot/ops/DEV-STANDARDS.md` | 17 Apr 2026 (moved) | `DEV-STANDARDS.md` L17 |
| #19 | Coding agents use Sentry MCP during investigations, builds, QA | ACTIVE | `bot/ops/DEV-STANDARDS.md` | 17 Apr 2026 (moved) | `DEV-STANDARDS.md` L18 |
| #20 | EdgeOps alerts ONLY (chat_id `-1003877525865`) — never public channel | ACTIVE | `bot/dashboard/health_dashboard.py`; `bot/scripts/monitor_narrative_integrity.py`; contract tests | — | `health_dashboard.py` L1832 · `monitor_narrative_integrity.py` L66 · `tests/contracts/test_health_alerter.py` L642 |
| #22 | Never write a URL that hasn't been verified to return HTTP 200 | ACTIVE | `bot/reference/ROLE-EDGE-AUDITOR.md` | — | `ROLE-EDGE-AUDITOR.md` L119 |
| #27 | LEAD personally reviews every QA-BASELINE report; AUDITOR ratifies algo-truth verdicts (REWORDED 17 Apr 2026 PM — pre-split named COO) | ACTIVE | `bot/ops/DEV-STANDARDS.md`; mirrored `bot/reference/ROLE-EDGE-AUDITOR.md` | 17 Apr 2026 (reworded) | `DEV-STANDARDS.md` L19 · `ROLE-EDGE-AUDITOR.md` L120 |
| #28 | Production health monitoring handled by `health-monitor-fix` (every 12h) | ACTIVE | `bot/ops/TECHNICAL.md`; mirrored `bot/reference/ROLE-EDGE-AUDITOR.md` (acting-on side) | 17 Apr 2026 (moved) | `TECHNICAL.md` L66 · `ROLE-EDGE-AUDITOR.md` L121 |
| #29 | Project isolation absolute — MzansiEdge only | ACTIVE | `Notion Core Memory`; `bot/ops/DISPATCH-V2.md` | — | Notion `340d9048-d73c-81d2-b0be-d5dfca2dd8a6` · `DISPATCH-V2.md` L195 |
| #30 | Line-range file ops only — no full-file `Read` on files >500 lines; grep first, then targeted Read | ACTIVE | `bot/ops/DEV-STANDARDS.md` (item 13); enforced `bot/reference/ROLE-EDGE-AUDITOR.md`; `bot/ops/NARRATIVE-WIRING-BIBLE.md` | 7 Apr 2026 | `DEV-STANDARDS.md` item 13, L67 · `ROLE-EDGE-AUDITOR.md` L122 · `NARRATIVE-WIRING-BIBLE.md` L757 |
| #31 | One-fetch rule for briefs and Notion pages | ACTIVE | `bot/ops/DEV-STANDARDS.md` (item 14); enforced `bot/reference/ROLE-EDGE-AUDITOR.md` | 7 Apr 2026 | `DEV-STANDARDS.md` item 14, L69 · `ROLE-EDGE-AUDITOR.md` L122 |
| #32 | 10-turn cap per session; one brief = one session | ACTIVE | `bot/ops/DEV-STANDARDS.md` (item 15); enforced `bot/reference/ROLE-EDGE-AUDITOR.md` | 7 Apr 2026 | `DEV-STANDARDS.md` item 15, L71 · `ROLE-EDGE-AUDITOR.md` L122 |
| #33 | Notion page hygiene — hard char limits (Task Hub 2K, CLAUDE.md 15K) | ACTIVE | `bot/ops/DEV-STANDARDS.md`; enforced `bot/reference/ROLE-EDGE-AUDITOR.md` | 10 Apr 2026 (LOCKED) | `DEV-STANDARDS.md` L20 · `ROLE-EDGE-AUDITOR.md` L123 |
| #34 | No betting language — match-intelligence framing only | ACTIVE | `bot/bot.py` runtime; `bot/tests/deploy_verify_2026_04_17.py` gate | — | `bot.py` L21666 · `tests/deploy_verify_2026_04_17.py` L361 |
| #35 | Reports filed in Agent Reports Pipeline DS (`7da2d5d2-0e74-429e-9190-6a54d7bbcd23`) per protocol | ACTIVE | `bot/ops/DEV-STANDARDS.md` §Agent Report Filing Protocol; mirrored `bot/ops/DISPATCH-V2.md` | 6 Apr 2026 | `DEV-STANDARDS.md` L36–57, L333 · `DISPATCH-V2.md` L196 |
| #36 | Every new automated component MUST be wired into monitoring dashboard in same brief | ACTIVE | `bot/ops/DEV-STANDARDS.md` | 15 Apr 2026 (LOCKED) | `DEV-STANDARDS.md` L21 |
| #38 | Card QA OCR Block — mandatory in every card-touching brief | ACTIVE | `bot/ops/DEV-STANDARDS.md` §Card QA OCR Block; mirrored `bot/ops/DISPATCH-V2.md`, `bot/reference/ROLE-EDGE-LEAD.md` | 22 Apr 2026 (LOCKED) | `DEV-STANDARDS.md` L77–99 · `DISPATCH-V2.md` L197 · `ROLE-EDGE-LEAD.md` L82 |
| #39 | Caption-refresh / freshness audit (CANDIDATE — pending `AUDIT-SCHEDULED-TASKS-FRESHNESS-01` landing) | CANDIDATE | `bot/ops/SURFACE-FUNNEL-MODEL.md` | — | `SURFACE-FUNNEL-MODEL.md` L154 |
| #40 | Authoritative kickoff source = `broadcast_schedule WHERE source='supersport_scraper'`; no any-source fallback | ACTIVE | `bot/ops/NARRATIVE-WIRING-BIBLE.md`; contract tests | — | `NARRATIVE-WIRING-BIBLE.md` L244 · `tests/contracts/test_kickoff_supersport_only.py` · `tests/contracts/test_pregen_refresh_window.py` |
| #41 | Approval binds commit — accepting a code/data-change report requires verifying commit + push landed | ACTIVE | `bot/ops/COWORK-LOCKED-MEMORY-BUNDLE.md`; referenced `bot/CLAUDE.md`, `bot/ops/DISPATCH-V2.md` | 25 Apr 2026 (LOCKED) | `COWORK-LOCKED-MEMORY-BUNDLE.md` L189–232 · `CLAUDE.md` L14 · `DISPATCH-V2.md` L198 |
| #43 | Session role locks dispatch role — every brief dispatched uses the dispatching session's canonical role on all three surfaces | ACTIVE | `bot/ops/COWORK-LOCKED-MEMORY-BUNDLE.md`; referenced `bot/ops/BRIDGE-INVARIANTS.md` | 5 May 2026 (LOCKED) | `COWORK-LOCKED-MEMORY-BUNDLE.md` L10 · `BRIDGE-INVARIANTS.md` L292 |
| #44 | Routing v1 binding rule (Sonnet default · Codex High mechanical · Opus Max judgement · Codex XHigh hard code root-cause); supersedes prior SO #44 ("Codex 5.5 is the ONLY executor") | ACTIVE | `bot/ops/MODEL-ROUTING.md` (Notion canonical: `354d9048-d73c-8138-bf72-d8ce7b768a08`) | 2 May 2026 (LOCKED) | `MODEL-ROUTING.md` L1, L233 |
| #45 | Codex Review Gate (v4.5) — `/codex:review --wait` mandatory after commit, before `mark_done.sh` | ACTIVE | `bot/ops/DEV-STANDARDS.md`; mirrored `bot/ops/MODEL-ROUTING.md` §10, `bot/ops/BRIDGE-INVARIANTS.md` | 4 May 2026 (v4.5 LOCKED) | `DEV-STANDARDS.md` L409–486 · `MODEL-ROUTING.md` L240–284 · `BRIDGE-INVARIANTS.md` L146, L158 |
| #46 | No time references — ever (no time-of-day, day-of-week, sleep, breaks, "tomorrow") | ACTIVE | `bot/ops/COWORK-LOCKED-MEMORY-BUNDLE.md`; anchor in `bot/CLAUDE.md` | 4 May 2026 (LOCKED) | `COWORK-LOCKED-MEMORY-BUNDLE.md` L160 |
| #47 | OCR_PROMPT is IMMUTABLE — add new prompts as new constants only (renamed from #30 by FIX-DOC-SO-CATALOG-CANONICAL-01) | ACTIVE | `bot/tests/qa/ocr_prompt.py`; `bot/tests/qa/rubric_runner/ocr_bridge.py` | 5 May 2026 (renumber LOCKED) | `tests/qa/ocr_prompt.py` L38 · `tests/qa/rubric_runner/ocr_bridge.py` L12 |

---

## SO #30 collision resolution (this brief)

**Finding R1 from `INV-DOC-ADVERSARIAL-AUDIT-2026-05-05`:** SO #30 had two conflicting definitions on disk:

1. **Line-range read discipline** — `bot/reference/ROLE-EDGE-AUDITOR.md:122` (`[SO #30 / #31 / #32]`); `bot/ops/NARRATIVE-WIRING-BIBLE.md:757` (`(SO #30.) Before any Read ≥100 lines of bot.py`); brief authoring instructions ("SO #30 strict: read files with offset+limit, never full reads on files >500 lines") echo this rule.
2. **OCR_PROMPT immutability** — `bot/tests/qa/ocr_prompt.py:38`; `bot/tests/qa/rubric_runner/ocr_bridge.py:12`.

Resolution: **line-range reads RETAIN #30** (more widely referenced — three doc sites + every brief authoring header). The OCR rule is **renumbered SO #47** (next available, after the current max #46). The OCR rule is narrow (one Python module + one bridge) and self-contained, so renumbering touches only those two file headers.

**Files changed in this resolution:**

- `bot/tests/qa/ocr_prompt.py:38` — comment header `(SO #30)` → `(SO #47)`
- `bot/tests/qa/rubric_runner/ocr_bridge.py:12` — comment `per SO #30` → `per SO #47`

**Verified absence of a third SO #30 definition** (Challenge Rule SO #10 surfaced explicitly): grep across `--include='*.md' --include='*.py'` in `/home/paulsportsza/bot` returned exactly four hits, two for each rule. No third party.

---

## Coverage and orphan check (AC-6)

Cross-reference scan: every `[SO #N]` and `SO #N` reference across `bot/CLAUDE.md`, `bot/ops/*.md`, `bot/reference/*.md`, server `tests/`, `scripts/`, runtime, plus Notion Core Memory and Active State, resolves to a row above.

- Bracketed (`[SO #N]`) definition forms found: SO #4, #6, #15, #18, #19, #22, #27, #28, #30, #31, #32, #33, #36 (13 unique). Each maps to its anchor row.
- Plain (`SO #N`) reference forms found: SO #2, #3, #6, #7, #9, #10, #11, #14, #20, #28, #29, #30, #34, #35, #38, #40, #41, #43, #44, #45, #46 — all map to entries above.
- Candidate (`#39`) flagged in `SURFACE-FUNNEL-MODEL.md` as pending audit landing. Tracked with status `CANDIDATE` until COO promotes.
- No orphan references — every numbered SO encountered in a server-reachable surface has a row.

---

## Notes

- DEV-STANDARDS.md numbered list items 1-15 carry historical pre-split SO numbering (per `*Last updated:* 17 April 2026 PM` header in that doc). Item 10 → SO #10, item 11 → SO #11, item 13 → SO #30, item 14 → SO #31, item 15 → SO #32. This catalog is the authoritative cross-walk: A3 is closed.
- Source of truth precedence: the catalog row's anchor is canonical for that SO's text. ROLE-EDGE-AUDITOR.md mirrors role-specific framing (e.g. "AUDITOR is bound by these") but does not redefine the rule.
- New SO additions route through AUDITOR Lane B (SO-addition gate per `bot/reference/ROLE-EDGE-AUDITOR.md` L173). After placement, a follow-up sweep adds the row here.

---

## Notion Mirror

A canonical Notion mirror of this catalog lives under MzansiEdge Project Wiki — link recorded in the FIX-DOC-SO-CATALOG-CANONICAL-01 report. On any future SO change, server canonical (this file) is the source; Notion mirror updates from it.

*Authored 5 May 2026 by AUDITOR Lane B (Information Architecture). Brief: FIX-DOC-SO-CATALOG-CANONICAL-01. Closes adversarial-audit findings R1 (RED), A2 (AMBER), A3 (AMBER).*


---

## SO #50 — Canonical Card Glow (LOCKED 7 May 2026)

| Field | Value |
|---|---|
| Status | ACTIVE |
| Source | `ops/CANONICAL-GLOW-SPEC.md` (authoritative) · `ops/TECHNICAL.md` §"Canonical Card Glow (LOCKED 7 May 2026)" (mirror) |
| Lock date | 7 May 2026 |
| Authority | Paul direct approval after TWO regression cycles (2 May right-side variant + 7 May header-clipped variant) |
| Bound contract tests | `tests/contracts/test_match_detail_canonical.py` (6 assertions) + `tests/contracts/test_edge_detail_canonical.py` (6 assertions) |
| Bound briefs | DOCS-GLOW-CANONICAL-LOCK-01 (this lock) · FIX-EDGE-CARD-GLOW-OVERFLOW-RESTORE-01 (`f059fa7`) · c04650b FIX-GLOW-COVERAGE-01 (working baseline) |
| Working pattern | `.upper-section` / `.upper-glow-zone` wrapper with `overflow: hidden`; `.header { overflow: visible }`; glow divs as direct children of the wrapper; anchor `at 50% 45%`; per-tier classes `.logo-glow-{diamond\|gold\|silver\|bronze}`; heights 260px / 220px |
| Forbidden patterns | `at 50% 25%` (top-center) on edge cards · `at 92% 50%` (right-side) · `.header { overflow: hidden }` · `_glow` Jinja adapter variable |
| Affected templates | `card_templates/match_detail.html` · `card_templates/edge_detail.html` |
| Carve-out | Sub_plans-pattern templates (`sub_plans.html`, `profile_home.html`, `my_matches.html`, `onboarding_*.html`) use a SEPARATE canonical: `.header` itself contains the glow with `overflow: hidden` because their layout is single-zone. Do not cross-pollinate. |

**Standing rule:** any brief touching glow CSS on `match_detail.html` or `edge_detail.html` MUST (a) read `ops/CANONICAL-GLOW-SPEC.md` before editing, (b) run both contract tests after editing AND before committing, (c) include a Codex sub-agent review for any deviation from the locked pattern (visual regressions are user-facing and Paul-approval-required).
