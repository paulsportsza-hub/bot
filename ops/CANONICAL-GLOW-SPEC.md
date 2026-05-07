# Canonical Card Glow Spec

**Locked:** 7 May 2026 | **Brief:** FIX-EDGE-CARD-GLOW-RESTORE-TOP-CENTER-CANONICAL-01
**Authority:** Paul direct approval after archaeology + diagnosis

> ONE pattern only. No carve-outs. No "family" exceptions.
> Top-center anchor. Per-tier colours. Sub_plans-aligned.
> DO NOT introduce a second pattern without an explicit Paul-approved brief.

---

## The Canonical Pattern

**Anchor:** `at 50% 25%` (horizontal centre, 25% from top of element)
**Geometry:** `ellipse 50% 90%` base layer, `ellipse 32% 60%` screen layer
**Position:** absolute, `inset: -10px 0 auto 0` base, `inset: 0 0 auto 0` screen
**Heights:** 190px base, 160px screen
**Filter:** `blur(3px)` base, `mix-blend-mode: screen` screen

Alphas (hex suffix on the colour):

| Tier | Colour | Base 0% | Base 45% | Base 70% | Screen 0% | Screen 50% |
|---|---|---|---|---|---|---|
| Diamond | #B9F2FF | 38 | 18 | 06 | 66 | 22 |
| Gold | #FFD700 | 38 | 18 | 06 | 66 | 22 |
| Silver | #CBD5E0 | 38 | 18 | 06 | 66 | 22 |
| Bronze | #E8A87C | 38 | 18 | 06 | 66 | 22 |
| Orange (no-edge fallback) | #F7931A | 38 | 18 | 06 | 66 | 22 |

Uniform alphas across tiers — the colour does the visual differentiation, not the opacity.

## HTML Structure (all 4 edge templates)

Insert as **direct children of `.header`**:

```html
{% set _glow_tier = (TIER_VAR | default("orange", true)) | lower %}
<div class="logo-glow logo-glow-{{ _glow_tier }}"></div>
<div class="logo-glow-screen logo-glow-screen-{{ _glow_tier }}"></div>
```

`TIER_VAR` per template:
- `edge_detail.html` → `tier`
- `edge_picks.html` → `top_tier` (already canonical)
- `edge_summary.html` → `top_tier` (already canonical)
- `match_detail.html` → `edge_badge_tier`

`.header` requirements:
- `position: relative;`
- `isolation: isolate;`
- `overflow: hidden;`

All other `.header` children must have `position: relative; z-index: 1`.

## CSS Block (paste verbatim)

```css
.logo-glow {
    position: absolute;
    inset: -10px 0 auto 0;
    height: 190px;
    pointer-events: none;
    z-index: 0;
    filter: blur(3px);
}
.logo-glow-screen {
    position: absolute;
    inset: 0 0 auto 0;
    height: 160px;
    pointer-events: none;
    z-index: 0;
    mix-blend-mode: screen;
}
.logo-glow-diamond { background: radial-gradient(ellipse 50% 90% at 50% 25%, #B9F2FF38 0%, #B9F2FF18 45%, #B9F2FF06 70%, transparent 100%); }
.logo-glow-gold    { background: radial-gradient(ellipse 50% 90% at 50% 25%, #FFD70038 0%, #FFD70018 45%, #FFD70006 70%, transparent 100%); }
.logo-glow-silver  { background: radial-gradient(ellipse 50% 90% at 50% 25%, #CBD5E038 0%, #CBD5E018 45%, #CBD5E006 70%, transparent 100%); }
.logo-glow-bronze  { background: radial-gradient(ellipse 50% 90% at 50% 25%, #E8A87C38 0%, #E8A87C18 45%, #E8A87C06 70%, transparent 100%); }
.logo-glow-orange  { background: radial-gradient(ellipse 50% 90% at 50% 25%, #F7931A38 0%, #F7931A18 45%, #F7931A06 70%, transparent 100%); }
.logo-glow-screen-diamond { background: radial-gradient(ellipse 32% 60% at 50% 28%, #B9F2FF66 0%, #B9F2FF22 50%, transparent 80%); }
.logo-glow-screen-gold    { background: radial-gradient(ellipse 32% 60% at 50% 28%, #FFD70066 0%, #FFD70022 50%, transparent 80%); }
.logo-glow-screen-silver  { background: radial-gradient(ellipse 32% 60% at 50% 28%, #CBD5E066 0%, #CBD5E022 50%, transparent 80%); }
.logo-glow-screen-bronze  { background: radial-gradient(ellipse 32% 60% at 50% 28%, #E8A87C66 0%, #E8A87C22 50%, transparent 80%); }
.logo-glow-screen-orange  { background: radial-gradient(ellipse 32% 60% at 50% 28%, #F7931A66 0%, #F7931A22 50%, transparent 80%); }
```

## No variants allowed

No `.upper-glow-zone`. No `at 92% 50%`. No `at 50% 45%`. No "match-family adaptive" carve-out. Anyone introducing a new variant must update this spec AND get explicit Paul approval AND file a fresh brief.

## Regression history (so we don't loop again)

- Apr 26: `fc14af4` lifted sub_plans top-center glow into match_detail. Visually correct but had clipping.
- Apr 28-30: `aec7e2d`, `f9a6fd3` tried to fix clipping by repositioning. Made it worse.
- 2 May: `e7758fb` deleted the top-center glow and replaced with right-side `at 92% 50%`. Misnamed commit ("CORRECT").
- 3 May: `eb25301` merged with misleading title ("canonical centre glow") that contradicts the diff.
- 3 May: `4c610f3 FIX-EDGE-GLOW-CANONICAL-ALIGN-01` propagated right-side variant to edge_detail/picks/summary.
- 4 May: `e50f730 DOCS-CANONICAL-GLOW-LOCK-01` codified the regression as canonical in this spec doc.
- 6 May: `FIX-CARD-MATCH-CANONICAL-FAMILY-01` added a match-family carve-out, doubling down.
- 7 May: Paul caught the regression visually. This spec rewrite restores pattern #1 as canonical.

The pattern: each iterative "fix" assumed the previous step's CSS was the desired baseline. None went back to the original sub_plans canonical that fc14af4 was trying to match. **Future agents: when in doubt, look at sub_plans.html and copy that.**
