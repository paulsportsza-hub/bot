# MzansiEdge QA Protocol v1.0

## Purpose
Repeatable QA methodology that ties every score to a release ID, controls for
sample variance, and produces diffable results across runs.

---

## 1. Pre-flight (before scoring anything)

| Step | Command / Action | Record |
|------|-----------------|--------|
| Verify runtime | `ps aux \| grep bot.py` — must show `/home/paulsportsza/bot/bot.py` | Bot PID |
| Capture release | `cd /home/paulsportsza/bot && git rev-parse --short HEAD` | Commit SHA |
| Timestamp | `date '+%Y-%m-%d %H:%M SAST'` | Run timestamp |
| Contract tests | `bash scripts/qa_safe.sh contracts` | PASS / FAIL (abort on FAIL) |

If the runtime path does not match or contracts fail → **BLOCK. Do not proceed.**

---

## 2. Sampling Method — Stratified Random (recommended)

**Why stratified random:** Fixed samples expire as matches come and go. Full
census varies in size across runs. Stratified random controls tier mix while
adapting to the live population.

**Procedure (10 cards):**
1. Query all unsettled edges: `SELECT match_key, edge_tier, sport, league FROM edge_results WHERE result IS NULL ORDER BY match_date`.
2. Group by tier. Allocate slots proportionally (round down), minimum 1 per
   tier present. Fill remainder from the largest tier.
3. Within each tier, sort by `match_key` and select using deterministic seed =
   first 8 chars of the commit SHA (Python: `random.seed(sha[:8])`).
4. If total live edges ≤ 12, use **full census** instead (score every card).

Record: total edges available, tier counts, sample list with match_keys.

---

## 3. Scoring Rubric

Score each card on four dimensions (1–10 scale):

| Dim | Weight | What to assess | Anchor: 3 | Anchor: 7 |
|-----|--------|----------------|-----------|-----------|
| **ACC** (Accuracy) | 0.25 | Factual correctness: team names, form strings, odds values, Elo figures, calculations | Multiple factual errors or wrong team | All facts correct, minor rounding |
| **RCH** (Richness) | 0.20 | Data depth: form, H2H, Elo, injuries, context, coach | Template-only, no specifics | Most data points present, 1–2 gaps |
| **VAL** (Value) | 0.20 | Edge reasoning: EV logic, risk factors, verdict quality | Generic / circular reasoning | Clear EV case with specific risk factors |
| **OVR** (Overall) | 0.35 | Holistic: tone, readability, user value, compliance with Notification Content Laws | Confusing or policy-violating | Professional, actionable, compliant |

**Composite** = `(ACC × 0.25) + (RCH × 0.20) + (VAL × 0.20) + (OVR × 0.35)`

**Caps:**
- Template cards (no enrichment data): RCH capped at 3/10.
- Cards with no narrative cache (on-the-fly generation or fallback): note serving
  path but score what the user actually sees.

**Rationale for confirming current weights:** ACC is foundational but partially
binary. OVR at 0.35 captures holistic user experience that dimensions miss
individually. Richness and Value split data-completeness from analytical quality.
No changes recommended at v1.0 — revisit after 5+ runs.

---

## 4. Metadata Captured Per Card

For each card in the sample, record:

| Field | How to capture |
|-------|---------------|
| `match_key` | From edge_results query |
| `sport` / `league` | From edge_results |
| `edge_tier` | From edge_results |
| `composite_score` | From edge_results (the edge composite, not QA score) |
| `serving_path` | Check narrative_cache: exists → **cache-hit**; absent but bot generates → **cache-miss**; template fallback → **template** |
| `enrichment_class` | **enriched** (narrative has form/H2H/Elo/context) or **template** (generic structure only) |
| `narrative_source` | From narrative_cache.narrative_source (e.g. w82, w84) or "live" if generated on-demand |
| `ACC` / `RCH` / `VAL` / `OVR` | Scored per rubric above |
| `card_composite` | Calculated per rubric formula |
| `defects` | Free-text list of specific issues found |

---

## 5. Reporting Format

Every QA report follows this structure (diffable across runs):

```
## QA Run Summary
- Run ID: QA-BASELINE-{NN}
- Release: {commit_sha} ({commit_msg_short})
- Timestamp: {YYYY-MM-DD HH:MM SAST}
- Bot PID: {pid}
- Contracts: PASS
- Population: {N} edges ({D}D / {G}G / {S}S / {B}B)
- Sample: {n} cards (method: stratified-random | full-census)
- Enrichment rate: {enriched}/{total} ({pct}%)
- Cache-hit rate: {hits}/{total} ({pct}%)

## Scores
| # | Match | Tier | Serving | Enrich | ACC | RCH | VAL | OVR | Comp | Defects |
|---|-------|------|---------|--------|-----|-----|-----|-----|------|---------|

## Composite: {overall_mean}/10 (Δ {delta} from prior run)
## Dimension Means: ACC={x} RCH={x} VAL={x} OVR={x}
```

---

## 6. Attribution Rule

A score change is attributed to a fix **only if all three hold:**
1. The fix is present in the deployed release (commit SHA matches).
2. The QA sample includes at least one card affected by the fix.
3. The specific dimension that improved corresponds to the fix's target
   (e.g. a rendering fix should move RCH/OVR, not ACC).

If conditions aren't met, log the delta as **unattributed variance**.

---

## 7. After Scoring

1. File the report to Notion Agent Reports Pipeline.
2. Write the overall composite into the Release Ledger entry for this commit.
3. If composite drops ≥ 0.5 from prior run → flag as potential regression.
