# TIER-COPY-CANON.md — Canonical Tier Copy

**Version:** 1.0
**Authority:** INV-TIER-VALUE-PROPS-01 (21 Apr 2026)
**Owners:** UX Designer (copy), LEAD (enforcement)
**Supersedes:** Ad-hoc tier copy across `card_data_adapters.py`, card templates, `bot.py`, website, and
`copy/SUBSCRIPTION.md`.

---

## Purpose

This file is the **single source of truth** for user-facing tier value-prop copy. Every surface that
describes what a user gets at a tier (Bronze / Gold / Diamond / Founding Member) MUST quote from this
file verbatim (SHORT form) or use the LONG bullets with no material change in meaning.

Silver is **not a purchasable tier**. It is an edge classification only. Do not write user plan copy
for Silver.

---

## Principles (cross-checked against `copy/TONE-GUIDE.md`)

1. **Sharp, Honest, Useful** — plain English, no marketing adjectives, no stacked emojis.
2. **Concrete over abstract** — real numbers (R99/mo, 3 views), not "unlock limitless potential".
3. **Quiet confidence** — let features speak. One emoji per section, max.
4. **Never imply guarantees** — "edge", "value", "expected value" — never "guaranteed winner".
5. **Diamond must explicitly name its three pillars** — AI Breakdown, Diamond-exclusive edges,
   Personalised alerts. Anywhere Diamond is described, all three must be discoverable.

---

## Cross-check against `tier_gate.GATE_MATRIX`

`scrapers/tier_gate.py` + `bot/tests/contracts/test_gate_contracts.py` define the 12 access
combinations. The canonical copy below reflects what each tier user actually sees:

| User tier | Bronze edge | Silver edge | Gold edge | Diamond edge |
|-----------|-------------|-------------|-----------|--------------|
| Bronze    | full        | partial     | blurred   | locked       |
| Gold      | full        | full        | full      | locked       |
| Diamond   | full        | full        | full      | full         |

`partial` = return amount only. `blurred` = match header + badge + return hint. `locked` = match
header + badge + 🔒. Daily view caps additionally constrain Bronze (3 unique match detail views).

---

## BRONZE — Free Plan

### SHORT (1 line, ≤10 words)
> Free edge picks — 3 detail views a day.

### LONG (5 bullets, ≤12 words each)
- See every edge we post — badges visible across all tiers
- 3 full detail views per day across any tier
- Gold edges blurred, Diamond locked until you upgrade
- Season hit rate and portfolio return visible to all
- Morning teaser with the day's top picks

### Rationale
- "See every edge" + "badges visible" is accurate per GATE_MATRIX — Bronze users see the Diamond
  badge on locked cards, just not the pick data.
- "3 detail views a day" matches `check_tip_limit()` in `edge_v2_helper.py`.
- Drops the inaccurate "24h delayed edges" language currently in `card_data_adapters.py:38` —
  odds are not delayed for Bronze, access is gated per tier.

---

## GOLD — R99/mo or R799/yr

### SHORT (1 line, ≤10 words)
> R99/mo — unlimited picks, real-time odds, no daily cap.

### LONG (5 bullets, ≤12 words each)
- Unlimited detail views — no daily cap
- Full card detail on every Bronze, Silver and Gold pick
- Line movement and full odds comparison unlocked
- Morning alerts cover Gold picks, not just Bronze teasers
- Diamond edges remain locked — upgrade to reach them

### Rationale
- "Full card detail on every [...] pick" reflects the full card detail view (odds, signals, line movement) that Gold unlocks — the four-section AI Breakdown (Setup/Edge/Risk/Verdict) is Diamond-only and is not available to Gold users.
- "Line movement and full odds comparison" reflects the current `sub_upgrade_gold_data()` features
  — preserved, but tightened.
- Annual pricing (`R799/yr`) is omitted from SHORT to stay ≤10 words; surfaces that have room
  (plan cards, billing) include it: "R99/mo or R799/yr".

---

## DIAMOND — R199/mo or R1,599/yr

### SHORT (1 line, ≤10 words)
> R199/mo — the whole edge system, nothing held back.

### LONG (5 bullets, ≤12 words each)
- **Every edge unlocked — Diamond picks are Diamond-only**
- **Full AI Breakdown: Setup, Edge, Risk, Verdict on every match**
- **Personalised alerts tuned to your teams and bankroll**
- Line movement + sharp money + CLV tracking
- Priority support when something doesn't look right

### Rationale (THE THREE PILLARS — non-negotiable)

**1. AI Breakdown (bullet 2)**
- The W82/W84 NarrativeSpec pipeline produces four-section analysis (📋 Setup / 🎯 Edge /
  ⚠️ Risk / 🏆 Verdict) on every Diamond edge. Bronze sees at most the Setup section blurred;
  Gold sees full card detail (odds, signals, line movement) but NO AI Breakdown on any edge.
  Full AI Breakdown is Diamond-only, on every edge including Bronze/Silver/Gold tiers.
- Current `build_sub_plans_data()` says "Everything in Gold" — this hides that the AI Breakdown
  experience on Diamond edges is **only available at Diamond tier**. Fixed in this canon.

**2. Diamond-exclusive edges (bullet 1)**
- Per GATE_MATRIX, Diamond-tier edges show `locked` access to both Bronze and Gold users.
  Only Diamond subscribers see the pick data. This exclusivity is a structural feature of the
  product, not a marketing line.
- Current copy in `card_data_adapters.py:50`, `sub_upgrade_diamond_max.html`, and `sub_plans.html`
  never states "Diamond-only". Fixed in this canon.

**3. Personalised alerts (bullet 3)**
- `morning_teaser_v2` (Wave 26A) and result alerts (Wave 25C) are already tier-gated and
  personalised (tuned to user's teams, tier, bankroll). Diamond tier gets the richest variant —
  morning teasers for Gold picks, result alerts with full context, no upgrade CTAs.
- This feature exists in code (`onboarding_notify.html:48` references "personalised daily picks")
  but is never marketed as a Diamond tier benefit. Fixed in this canon.

**Supporting bullets**
- "Line movement + sharp money + CLV tracking" preserves the current feature list.
- "Priority support" replaces vague existing "priority support" language with the implicit
  commitment — same as now, but discoverable on plan cards.

---

## FOUNDING MEMBER — R699/yr Diamond (limited slots)

### SHORT (1 line, ≤10 words)
> R699/yr Diamond — price locked for life.

### LONG (5 bullets, ≤12 words each)
- Full Diamond access for one full year
- R699/yr locked forever — every renewal stays at this price
- Founding member badge and community access
- Under R2 a day for the whole edge system
- Limited slots — closes before public launch

### Rationale
- Preserves existing `sub_founding_live.html` bullets but tightens wording.
- "Under R2 a day" is a phrase we own per `copy/TONE-GUIDE.md` — it survives unchanged.
- Cross-checks against `product_catalogue.founding_offer.annual_price = 699` and
  `sub_founding_live.html:114` price hero block.

---

## Usage Rules

### When to use SHORT form
- Plan comparison tiles (one line per tier)
- Upgrade CTAs in tight mobile cards
- Nudge teaser lines ("Diamond — R199/mo, the whole edge system")
- Status lines in `/status` / `/billing` commands

### When to use LONG form
- Plan detail cards (`sub_plans.html`, `sub_upgrade_*.html`)
- Onboarding / education surfaces (blog, pitch deck, llms.txt)
- Monthly report tier-benefits footer (Diamond subscribers only)

### Adaptations allowed
- **Punctuation/line-break to fit 480px card width** — permitted.
- **Emoji prefix per tier** (🥉 Bronze / 🥇 Gold / 💎 Diamond / 🎁 Founding) — permitted.
- **Pricing split (R99/mo · R799/yr)** — permitted, still counted as one bullet.
- **Reordering bullets** — permitted for visual hierarchy, but Diamond's three pillars
  (AI Breakdown, Diamond-exclusive edges, Personalised alerts) MUST appear in the first three
  bullets wherever Diamond's LONG form is used.

### Adaptations forbidden
- Inventing new bullets that claim features not in this file.
- Claiming Gold has "AI breakdowns" or "AI analysis" in any form — Full AI Breakdown is Diamond-only.
- Dropping any of Diamond's three pillars from any surface.
- Using "guaranteed", "premium", "elite", "unlock limitless potential" or other TONE-GUIDE banned
  terms.
- Using "Silver" as a tier a user can buy.
- Claiming "24h delayed edges" for Bronze (not how the product works).

---

## Change Log

| Date       | Version | Author | Change                                              |
|------------|---------|--------|-----------------------------------------------------|
| 2026-04-21 | 1.0     | LEAD   | Initial canon (brief INV-TIER-VALUE-PROPS-01)      |
| 2026-04-21 | 1.1     | LEAD   | Paul override: Full AI Breakdown is Diamond-only. Gold copy corrected to "full card detail" only. |
