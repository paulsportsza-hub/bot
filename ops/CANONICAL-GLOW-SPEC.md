# Canonical Card Glow Spec

**Locked:** 7 May 2026 (re-locked) | **Brief:** FIX-EDGE-CARD-GLOW-OVERFLOW-RESTORE-01 + DOCS-GLOW-CANONICAL-LOCK-01
**Authority:** Paul direct approval after the second glow regression. Restores the c04650b WORKING pattern.

**Contract tests (run before committing any glow CSS change):**
- `tests/contracts/test_match_detail_canonical.py` — 6 assertions on match_detail
- `tests/contracts/test_edge_detail_canonical.py` — 6 assertions on edge_detail

> ONE pattern. The wrapper is `.upper-section`. The glow flows from header through matchup through meta-bar.
> DO NOT introduce a `header { overflow: hidden }` containment around the glow — it clips.
> DO NOT introduce `at 50% 25%` (top-center anchor) on edge cards — that pattern only works in `sub_plans.html` because that file's `.header` is the entire upper region.
> DO NOT introduce `at 92% 50%` right-side variant — Paul has explicitly rejected it twice.

---

## The Canonical Pattern

**Wrapper structure:** the glow lives inside a `.upper-section` element that wraps `.header + .matchup + .meta-bar`. The wrapper has `overflow: hidden`. The glow divs are direct children of `.upper-section`, NOT of `.header`.

**Anchor:** `at 50% 45%` (horizontal centre, near the vertical middle of `.upper-section` which is ~260px tall).
**Geometry:** `ellipse 80% 70%` base layer, `ellipse 70% 60%` screen layer.
**Heights:** 260px base, 220px screen — flows over header into matchup + meta-bar zone.
**Filter:** `blur(4px)` base, `mix-blend-mode: screen` screen.

Per-tier alphas (locked, do not modify without new brief):

| Tier | Colour | Base 0% | Base 42% | Base 65% | Screen 0% | Screen 45% |
|---|---|---|---|---|---|---|
| Diamond | #B9F2FF | 39 | 16 | 05 | 51 | 1F |
| Gold | #FFD700 | 39 | 16 | 05 | 51 | 1F |
| Silver | #CBD5E0 | 2B | 0F | 03 | 42 | 18 |
| Bronze | #E8A87C | 30 | 13 | 04 | 47 | 1B |

Silver and bronze run lower alpha on purpose (contrast tuning).

## Required CSS structure

```css
/* Glow zone wrapper (the magic — overflow:hidden lives HERE, not on .header) */
.upper-section {
    position: relative;
    overflow: hidden;
    isolation: isolate;
}

.header {
    position: relative;
    z-index: 1;
    overflow: visible;        /* explicitly visible — glow flows through */
    /* NO opaque background — the glow must show through */
}

.matchup {
    position: relative;
    z-index: 1;
}

.meta-bar {
    position: relative;
    z-index: 1;
}

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

.logo-glow-diamond { background: radial-gradient(ellipse 80% 70% at 50% 45%, #B9F2FF39 0%, #B9F2FF16 42%, #B9F2FF05 65%, transparent 90%); }
.logo-glow-screen-diamond { background: radial-gradient(ellipse 70% 60% at 50% 45%, #B9F2FF51 0%, #B9F2FF1F 45%, transparent 80%); }
.logo-glow-gold { background: radial-gradient(ellipse 80% 70% at 50% 45%, #FFD70039 0%, #FFD70016 42%, #FFD70005 65%, transparent 90%); }
.logo-glow-screen-gold { background: radial-gradient(ellipse 70% 60% at 50% 45%, #FFD70051 0%, #FFD7001F 45%, transparent 80%); }
.logo-glow-silver { background: radial-gradient(ellipse 80% 70% at 50% 45%, #CBD5E02B 0%, #CBD5E00F 42%, #CBD5E003 65%, transparent 90%); }
.logo-glow-screen-silver { background: radial-gradient(ellipse 70% 60% at 50% 45%, #CBD5E042 0%, #CBD5E018 45%, transparent 80%); }
.logo-glow-bronze { background: radial-gradient(ellipse 80% 70% at 50% 45%, #E8A87C30 0%, #E8A87C13 42%, #E8A87C04 65%, transparent 90%); }
.logo-glow-screen-bronze { background: radial-gradient(ellipse 70% 60% at 50% 45%, #E8A87C47 0%, #E8A87C1B 45%, transparent 80%); }
```

## Required HTML structure

```html
<div class="upper-section">
    {% if tier %}
    <div class="logo-glow logo-glow-{{ tier | lower }}"></div>
    <div class="logo-glow-screen logo-glow-screen-{{ tier | lower }}"></div>
    {% endif %}

    <div class="header">
        <!-- header content -->
    </div>

    <div class="matchup">
        <!-- matchup content -->
    </div>

    <div class="meta-bar">
        <!-- meta-bar content -->
    </div>
</div>
```

The tier variable per template:
- `edge_detail.html` → `tier`
- `match_detail.html` → `edge_badge_tier`
- `edge_picks.html` → `top_tier` (uses a separate `.header-glow` shell — kept as-is, that file is fine)
- `edge_summary.html` → `top_tier` (same as edge_picks — kept as-is)

## Two regression cycles caught

**Cycle 1 (e7758fb 2 May → eb25301 → e50f730 4 May):** right-side `at 92% 50%` variant landed. Codified in spec doc. Paul caught it 7 May.

**Cycle 2 (3e675bf / 80ffd8e 7 May):** my fix moved the glow inside `.header` with `overflow: hidden`. Glow couldn't escape the header, clipped at the bottom of the header strip. Paul caught it the same day.

The pattern that ACTUALLY works (and works for Paul visually) is `c04650b FIX-GLOW-COVERAGE-01` from 4 May:
- glow lives in a `.upper-section` wrapper
- wrapper has `overflow: hidden`
- header has `overflow: visible`
- glow geometry sized for the wrapper (260px tall, anchored at 45% vertical midpoint)

**For future agents: read this spec, look at c04650b commit, AND check `tests/contracts/test_match_detail_canonical.py`. Do not add `overflow: hidden` to `.header`. Do not move glow divs inside `.header`. Do not change the anchor.**
