# Canonical Card Glow Spec

**Locked:** 4 May 2026 | **Commits:** eb25301 (match_detail) · 4c610f3 (edge templates)
**Authority:** Paul direct approval after 12-step iterative tuning

> DO NOT modify alpha values, ellipse dimensions, or gradient centre without a new brief explicitly approved by Paul.
> DO NOT use a single `{{ tier_color }}` variable in CSS. Use per-tier CSS classes (see below).
> Agents reading card templates MUST read this file before making any changes to glow-related CSS.

---

## HTML Structure

Insert as **direct children of `.header`** (NOT inside any sub-container):

```html
{% if TIER_VAR %}
<div class="logo-glow logo-glow-{{ TIER_VAR }}"></div>
<div class="logo-glow-screen logo-glow-screen-{{ TIER_VAR }}"></div>
{% endif %}
```

Where `TIER_VAR` is the lowercase tier string for that template:
- `match_detail.html` → `edge_badge_tier`
- `edge_detail.html` → `tier`
- `edge_picks.html` → `top_tier`
- `edge_summary.html` → `top_tier`

All other `.header` children MUST have `position: relative; z-index: 1` so they render above the glow.
`.header` itself MUST have `overflow: hidden`.

> IMPORTANT: The tier variable MUST be lowercased when used in the class name.
> Use `{{ TIER_VAR | lower }}` — never `{{ TIER_VAR }}` bare.
> CSS classes are lowercase (logo-glow-gold) — title-case renders will silently produce no glow.

---

## Base Layer CSS

```css
.logo-glow {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 260px;
    pointer-events: none;
    z-index: 0;
    filter: blur(4px);
}
```

## Screen Blend Layer CSS

```css
.logo-glow-screen {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 220px;
    pointer-events: none;
    z-index: 0;
    mix-blend-mode: screen;
}
```

---

## Per-Tier Gradients (LOCKED — do not change alphas)

```css
.logo-glow-diamond {
    background: radial-gradient(ellipse 80% 70% at 50% 45%,
        #B9F2FF39 0%, #B9F2FF16 42%, #B9F2FF05 65%, transparent 90%);
}
.logo-glow-screen-diamond {
    background: radial-gradient(ellipse 70% 60% at 50% 45%,
        #B9F2FF51 0%, #B9F2FF1F 45%, transparent 80%);
}
.logo-glow-gold {
    background: radial-gradient(ellipse 80% 70% at 50% 45%,
        #FFD70039 0%, #FFD70016 42%, #FFD70005 65%, transparent 90%);
}
.logo-glow-screen-gold {
    background: radial-gradient(ellipse 70% 60% at 50% 45%,
        #FFD70051 0%, #FFD7001F 45%, transparent 80%);
}
.logo-glow-silver {
    background: radial-gradient(ellipse 80% 70% at 50% 45%,
        #CBD5E02B 0%, #CBD5E00F 42%, #CBD5E003 65%, transparent 90%);
}
.logo-glow-screen-silver {
    background: radial-gradient(ellipse 70% 60% at 50% 45%,
        #CBD5E042 0%, #CBD5E018 45%, transparent 80%);
}
.logo-glow-bronze {
    background: radial-gradient(ellipse 80% 70% at 50% 45%,
        #E8A87C30 0%, #E8A87C13 42%, #E8A87C04 65%, transparent 90%);
}
.logo-glow-screen-bronze {
    background: radial-gradient(ellipse 70% 60% at 50% 45%,
        #E8A87C47 0%, #E8A87C1B 45%, transparent 80%);
}
```

---

## Alpha Reference Table

| Tier    | Colour    | Base peak | Base mid | Base fade | Screen peak | Screen mid |
|---------|-----------|-----------|----------|-----------|-------------|------------|
| Diamond | #B9F2FF   | `39`      | `16`     | `05`      | `51`        | `1F`       |
| Gold    | #FFD700   | `39`      | `16`     | `05`      | `51`        | `1F`       |
| Silver  | #CBD5E0   | `2B`      | `0F`     | `03`      | `42`        | `18`       |
| Bronze  | #E8A87C   | `30`      | `13`     | `04`      | `47`        | `1B`       |

---

## Tuning History (summary)

12 iterative steps, 4 May 2026, Paul direct feedback. Key decisions:
- Centre point `at 50% 45%` — VS midpoint horizontally centred
- Two opacity reductions: −30% then −15% from initial values
- Single-source gradient (no dual or corner variants)
- Per-tier classes (not a single `{{ tier_color }}` CSS variable) to allow tier-specific alpha calibration

Full tuning log: Notion report `354d9048-d73c-819e-8700-c6fc2bda2566`
