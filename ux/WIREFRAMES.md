# MzansiEdge — UX Wireframes

> Date: 2026-02-25 (updated: multi-bookmaker, line movement, Edge Rating placement)
> Format: ASCII wireframes with exact HTML message text, keyboard layouts, loading states, and callback data

---

## 1. MAIN MENU

What users see on `/start` (returning) or "🏠 Home" button.

### Loading State
None — immediate render.

### Message Text
```html
🇿🇦 <b>MzansiEdge — Main Menu</b>

Hey Paul, your edge is waiting.
What would you like to do?
```

### Keyboard Layout
```
┌─────────────────────────────────────┐
│ [⚽ Your Games]     [🔥 Hot Tips]   │  yg:all:0      hot:go
│ [💰 My Bets]        [🏟️ My Teams]   │  bets:active   teams:view
│ [📈 Stats]          [🎰 Bookmakers] │  stats:overview affiliate:compare
│ [⚙️ Settings]                       │  settings:home
└─────────────────────────────────────┘
```

### Notes
- User's `first_name` escaped with `html.escape()`
- Persistent reply keyboard also active (separate from inline)
- Single message — NOT two messages as currently implemented

---

## 2. TODAY'S TIPS (Hot Tips)

Paginated list (5/page) with Edge Rating badges. Single message.

### Loading State
```html
🔥 <i>Mining the markets across all sports…</i>
```
Loading message is then **edited** into the final tips summary (not deleted + new message).

### Message Text (Page 1 of 2)
```html
🔥 <b>Hot Tips — 10 Value Bets</b>
Page 1/2 · Scanned 25 markets · Updated 3 min ago

⛏️🔥 1. ⚽ Arsenal vs Chelsea
   Arsenal Win @ <b>2.15</b> (HWB) ⭐ · 92%
⛏️🔥 2. 🏉 Sharks vs Stormers
   Sharks ML @ <b>2.15</b> (Betway) ⭐ · 88%
⛏️⭐ 3. 🏏 Proteas vs India
   Proteas ML @ <b>3.20</b> (HWB) ⭐ · 79%
⛏️⭐ 4. ⚽ Barcelona vs Real Madrid
   BTTS @ <b>1.80</b> (Sportingbet) ⭐ · 76%
⛏️⭐ 5. 🏀 Lakers vs Celtics
   Lakers +4.5 @ <b>1.90</b> (Betway) ⭐ · 74%

<i>Best odds shown ⭐ · Tap a number for breakdown</i>
```

**Summary line format:** Each tip occupies 2 lines — match name on line 1, outcome + best odds + bookmaker abbreviation + confidence on line 2. This keeps lines short for mobile while showing the best-odds bookmaker at a glance.

**Bookmaker abbreviations for summary lines:** HWB = Hollywoodbets, Betway = Betway, SB = Sportingbet, Supa = Supabets. Full names shown in detail view.

### Keyboard Layout (Page 1)
```
┌─────────────────────────────────────┐
│ [1]  [2]  [3]  [4]  [5]           │  hot:detail:0..4
│ [Next ➡️]                           │  hot:page:1
│ [🔄 Refresh]                        │  hot:go
│ [↩️ Menu]                           │  nav:home
└─────────────────────────────────────┘
```

### Message Text (Page 2 of 2)
```html
🔥 <b>Hot Tips — 10 Value Bets</b>
Page 2/2 · Scanned 25 markets · Updated 3 min ago

⛏️🥈 6. ⚽ Chiefs vs Pirates
   Draw @ <b>3.50</b> (HWB) ⭐ · 68%
⛏️🥈 7. ⚽ Liverpool vs Spurs
   Over 2.5 @ <b>1.68</b> (Betway) ⭐ · 65%
⛏️🥉 8. 🎾 Djokovic vs Alcaraz
   Djokovic ML @ <b>2.20</b> (SB) ⭐ · 62%
⛏️🥉 9. 🥊 UFC 312 — Fighter A
   Fighter A @ <b>1.85</b> (HWB) ⭐ · 60%
⛏️🥉 10. ⛳ PGA Event — Player X
   Top 5 @ <b>4.50</b> (Betway) ⭐ · 55%

<i>Best odds shown ⭐ · Tap a number for breakdown</i>
```

### Keyboard Layout (Page 2)
```
┌─────────────────────────────────────┐
│ [6]  [7]  [8]  [9]  [10]          │  hot:detail:5..9
│ [⬅️ Prev]                           │  hot:page:0
│ [🔄 Refresh]                        │  hot:go
│ [↩️ Menu]                           │  nav:home
└─────────────────────────────────────┘
```

### Notes
- Tips sorted by confidence descending
- Max 10 tips total, 5 per page
- If fewer than 6 tips: single page, no pagination
- Edge Rating emoji prefix on each line
- Sport emoji before match name
- Loading message edited into this (never deleted + sent new)

---

## 3. MATCH DETAIL (Tip Card) — Multi-Bookmaker

Full AI analysis with multi-bookmaker odds comparison, Edge Rating badge, and line movement indicator. Shown when user taps a numbered button from Hot Tips or Your Games.

### Loading State (edit-in-place)
```html
🤖 <i>Analysing form for Arsenal vs Chelsea…</i>
```

### Visual Layout Guide

```
┌─────────────────────────────────────────┐
│  🎯 MATCH HEADER                        │
│  📅 Date/Time                           │
│                                         │
│  ⛏️🔥 EDGE RATING BADGE (top, prominent)│
│                                         │
│  📋 THE SETUP (AI analysis)             │
│  🎯 THE EDGE                            │
│  ⚠️ THE RISK                            │
│  🏆 VERDICT                             │
│                                         │
│  📊 MULTI-BOOKMAKER ODDS TABLE          │
│     Per-outcome, best marked ⭐          │
│     Line movement ↑↓ on verdict outcome │
│                                         │
│  💡 PAYOUT / STAKE LINE                 │
│                                         │
│  [📲 Bet on {best_odds_bookie} →]       │
│  [🔔 Follow] [↩️ Back]                  │
└─────────────────────────────────────────┘
```

### Message Text (Casual Experience)
```html
🎯 <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️🔥 Edge Rating: PLATINUM (92%)</b>

📋 <b>The Setup</b>
Arsenal unbeaten in 8 home games, 5 clean sheets.
Chelsea missing key midfielder. H2H: Arsenal won
last 3 at home.

🎯 <b>The Edge</b>
Market prices Arsenal win at 52% implied. Our model
says 63% — that's an 11-point gap. Lekker value.

⚠️ <b>The Risk</b>
Chelsea could sit deep and counter. Arsenal's set-piece
defence has been shaky — 3 goals from corners.

🏆 <b>Verdict</b>
Arsenal Win — High conviction. The edge is sharp.

<b>SA Bookmaker Odds:</b>

<b>Arsenal Win</b> 💰
• Hollywoodbets: <b>2.15</b> ⭐
  1.90 → 2.15 (+13.2%) ↑
• Betway: 2.10
• Sportingbet: 2.05

<b>Draw</b>
• Betway: <b>3.50</b> ⭐
• Hollywoodbets: 3.40
• Sportingbet: 3.35

<b>Chelsea Win</b>
• Sportingbet: <b>4.30</b> ⭐
• Betway: 4.20
• Hollywoodbets: 4.10

💡 <i>R100 on Arsenal Win @ Hollywoodbets pays R215
EV: +7.3%</i>
```

### Message Text (Experienced)
```html
🎯 <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️🔥 PLATINUM (92%)</b>

📋 <b>The Setup</b>
ARS W5 D2 L1 last 8H (62.5%). CHE W3 D1 L4
away (37.5%). xG: ARS 1.82/g, CHE 1.21/g.

🎯 <b>The Edge</b>
Fair prob 63.2% vs implied 47.6%. Gap: +15.6pp.
Market overweighting Chelsea's recent UCL form.

⚠️ <b>The Risk</b>
Palmer injury doubt. If fit, counter-attack threat
increases. Venue factor may be overstated.

🏆 <b>Verdict</b>
Arsenal Win — High conviction.

<b>SA Bookmaker Odds:</b>

<b>Arsenal Win</b> 💰
• Hollywoodbets: <b>2.15</b> ⭐
  1.90 → 2.15 (+13.2%) ↑
• Betway: 2.10
• Sportingbet: 2.05

<b>Draw</b>
• Betway: <b>3.50</b> ⭐
• Hollywoodbets: 3.40

<b>Chelsea Win</b>
• Sportingbet: <b>4.30</b> ⭐
• Betway: 4.20

📈 EV: <b>+7.3%</b> · Kelly: <code>3.8%</code>
💵 Stake R228 @ Hollywoodbets → R490 (+R262)
```

### Message Text (Newbie)
```html
🎯 <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️🔥 Edge Rating: PLATINUM</b>
<i>This is our highest confidence rating.</i>

📋 <b>What's Happening</b>
Arsenal have been great at home — 8 games without
a loss. Chelsea are missing a key player.

🏆 <b>Our Pick: Arsenal Win</b>
The bookmakers are giving Arsenal good odds because
they think Chelsea have a chance. Our AI disagrees.

<b>Where to Bet:</b>
• Hollywoodbets: <b>2.15</b> ⭐ (best price)
• Betway: 2.10

💡 <i>Bet R20 → get R43 back
Bet R50 → get R108 back
Start small while you're learning!</i>
```

### Keyboard Layout (Multi-Bookmaker)

The CTA button links to the bookmaker offering the **best odds** for the verdict outcome. This maximises user value and affiliate revenue for the winning bookmaker.

```
┌───────────────────────────────────────┐
│ [📲 Bet on Hollywoodbets →]           │  URL: hollywoodbets.co.za (best odds)
│ [🔔 Follow this game]                │  subscribe:{event_id}
│ [📊 All Bookmaker Odds]              │  odds:compare:{event_id}
│ [↩️ Back to Hot Tips]                 │  hot:back
└───────────────────────────────────────┘
```

If accessed from Your Games:
```
┌───────────────────────────────────────┐
│ [📲 Bet on Hollywoodbets →]           │  URL: hollywoodbets.co.za (best odds)
│ [🔔 Follow this game]                │  subscribe:{event_id}
│ [📊 All Bookmaker Odds]              │  odds:compare:{event_id}
│ [↩️ Back to Your Games]              │  yg:all:0
└───────────────────────────────────────┘
```

### Single Bookmaker Fallback (MVP)

When only Betway has odds for this market:

```html
<b>Betway Odds:</b>
• Arsenal Win: <b>2.10</b> 💰
• Draw: 3.40
• Chelsea Win: 4.20

💡 <i>R100 bet pays R210 · EV: +7.3%</i>
```

```
┌───────────────────────────────────┐
│ [📲 Bet on Betway →]             │  URL: betway.co.za
│ [🔔 Follow this game]            │  subscribe:{event_id}
│ [↩️ Back to Hot Tips]             │  hot:back
└───────────────────────────────────┘
```

No ⭐ marker when only 1 bookmaker — nothing to compare. No "All Bookmaker Odds" button.

---

## 4. MULTI-BOOKMAKER ODDS TABLE

How we display odds from multiple SA bookmakers cleanly within a match detail. Includes line movement indicators and best-odds highlighting with affiliate logic.

### Display Modes

Three display modes depending on context and number of bookmakers:

### 4A. Full Odds Table (Match Detail — Primary View)

Used in the Match Detail tip card (Section 3) when 2+ bookmakers have odds.

```html
<b>SA Bookmaker Odds:</b>

<b>Arsenal Win</b> 💰
• Hollywoodbets: <b>2.15</b> ⭐
  1.90 → 2.15 (+13.2%) ↑
• Betway: 2.10
• Sportingbet: 2.05
• Supabets: 2.00

<b>Draw</b>
• Betway: <b>3.50</b> ⭐
• Hollywoodbets: 3.40
  3.30 → 3.40 (+3.0%) ↑
• Sportingbet: 3.35

<b>Chelsea Win</b>
• Sportingbet: <b>4.30</b> ⭐
• Betway: 4.20
• Hollywoodbets: 4.10
  4.50 → 4.10 (−8.9%) ↓
```

**Layout rules for full table:**
- Outcome name bolded on its own line
- 💰 marker on the verdict outcome (the one with edge)
- Each bookmaker on a `•` bullet, best odds bolded with ⭐
- Line movement shown as indented sub-line under the bookmaker where it moved
- Movement format: `{open} → {current} ({+/-pct}%) ↑/↓`
- ↑ = odds drifting (value improving for punter)
- ↓ = odds shortening (value decreasing)
- Only show movement when >5% change from opening

### 4B. Compact Odds (Hot Tips Summary / Space-Constrained)

Used in the Hot Tips summary list (Section 2) and any context where space is tight.

```html
<b>Best Odds:</b>
• Arsenal Win: <b>2.15</b> (HWB) ⭐ ↑
• Draw: <b>3.50</b> (Betway) ⭐
• Chelsea Win: <b>4.30</b> (SB) ⭐

<i>⭐ = best SA odds · ↑ = odds drifting</i>
```

**Layout rules for compact:**
- One line per outcome — best odds only
- Bookmaker abbreviated: HWB, Betway, SB, Supa
- ↑/↓ arrow appended if >5% movement
- No sub-lines, no other bookmakers
- Footer explains symbols on first view

### 4C. Single Bookmaker (MVP Fallback)

When only one bookmaker (Betway) has odds for this market.

```html
<b>Betway Odds:</b>
• Arsenal Win: <b>2.10</b> 💰
• Draw: 3.40
• Chelsea Win: 4.20
```

No ⭐ marker (nothing to compare). No abbreviated name.

### 4D. Full Comparison View (Dedicated Screen)

Accessible via "📊 All Bookmaker Odds" button from Match Detail. Shows all outcomes with all bookmakers side-by-side.

```html
📊 <b>Odds Comparison — Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>Arsenal Win</b> 💰
• Hollywoodbets: <b>2.15</b> ⭐  1.90 → 2.15 ↑
• Betway: 2.10                  1.95 → 2.10 ↑
• Sportingbet: 2.05             2.05 (no move)
• Supabets: 2.00                —

<b>Draw</b>
• Betway: <b>3.50</b> ⭐        3.40 → 3.50 ↑
• Hollywoodbets: 3.40           3.30 → 3.40 ↑
• Sportingbet: 3.35             3.35 (no move)
• Supabets: 3.30                —

<b>Chelsea Win</b>
• Sportingbet: <b>4.30</b> ⭐   4.30 (no move)
• Betway: 4.20                  4.50 → 4.20 ↓
• Hollywoodbets: 4.10           4.50 → 4.10 ↓
• Supabets: 4.00                —

<i>⭐ Best SA odds · ↑ Drifting · ↓ Shortening
Updated 5 min ago</i>
```

```
┌───────────────────────────────────────┐
│ [📲 Bet on Hollywoodbets →]           │  URL (best odds for verdict)
│ [🎯 Back to Analysis]                │  tip:detail:{event_id}
│ [↩️ Menu]                            │  nav:home
└───────────────────────────────────────┘
```

### Line Movement Rules

| Movement | Symbol | Meaning | Colour Intent |
|----------|--------|---------|---------------|
| Odds increased >5% | ↑ | Drifting — more value for punter | Positive (green feel) |
| Odds decreased >5% | ↓ | Shortening — less value | Negative (red feel) |
| Odds changed <5% | (no move) | Minor fluctuation, not shown | Neutral |
| No opening data | — | Bookmaker added after open | No indicator |

**When to show movement:**
- Always show on the verdict outcome (the one the tip recommends)
- Show on other outcomes only in the Full Comparison View (4D)
- Only show when change is >5% from opening line
- "Sharp money" label when movement >10% on any outcome: `🔥 Sharp movement detected`

### Affiliate Link Logic

The CTA button always links to the bookmaker with the **best odds for the verdict outcome**:

```python
# Pseudocode for affiliate button selection
verdict_outcome = tip["outcome"]  # e.g. "Arsenal Win"
best_bookie = max(
    odds_by_bookmaker[verdict_outcome],
    key=lambda b: b["odds"]
)
affiliate_url = SA_BOOKMAKERS[best_bookie["key"]]["affiliate_base_url"]
button_text = f"📲 Bet on {best_bookie['display_name']} →"
```

If the best-odds bookmaker doesn't have an affiliate URL configured, fall back to the next-best bookmaker that does. Always show the bookmaker name — never a generic "Bet Now".

### Edge Rating Badge Placement

The Edge Rating badge sits directly below the match header, above the AI analysis:

```
Match Header
Date/Time
                          ← blank line
Edge Rating Badge         ← ALWAYS here, never buried in text
                          ← blank line
AI Analysis sections...
```

This ensures it's visible without scrolling on mobile. In the Hot Tips summary, the badge emoji prefix (⛏️🔥/⛏️⭐/⛏️🥈/⛏️🥉) appears at the start of each tip line instead.

### Rules Summary

- Best odds marked with ⭐ on same line
- SA bookmakers only (never show Pinnacle, Betfair, etc.)
- Order within each outcome: highest odds first
- If only 1 bookmaker has odds for that market, no ⭐ (nothing to compare)
- Display names: "Hollywoodbets" not "hollywoodbets_za", "Betway" not "betway"
- Abbreviations in compact view: HWB, Betway, SB, Supa
- Max 4 bookmakers per outcome (if 5+ exist, show top 4 + "and N more")
- Line movement only when >5% change from opening
- Affiliate CTA goes to best-odds bookmaker for verdict outcome
- Edge Rating badge always in the header area, never below the odds table

---

## 5. SUBSCRIPTION FLOW

Free tier prompt → plan selection → payment → confirmation.

### Step 1: Upsell Prompt (Soft Nudge)

Triggered after 3rd tip view for free users.

```html
💎 <b>Unlock Full Breakdowns</b>

You've checked 3 tips today — you're clearly
looking for edges. Here's what Premium gets you:

<b>Free (current):</b>
• 1 AI tip per day
• Basic odds display
• Edge Rating badge only

<b>Premium (R49/month):</b>
• Unlimited AI tips daily
• Full match breakdowns
• Kelly stake sizing
• Line movement alerts
• Priority access to new features

That's less than R2 a day.
```

```
┌───────────────────────────────────┐
│ [💎 Go Premium — R49/month]      │  nav:subscribe
│ [⏭️ Not Now]                      │  nav:home
└───────────────────────────────────┘
```

### Step 2: Email Collection

```html
💎 <b>MzansiEdge Premium — R49/month</b>

To subscribe, please enter your <b>email address</b> below.
<i>(Used for Paystack payment — never shared.)</i>
```

User types email. No buttons needed (text input state).

### Step 3: Payment Link

```html
💳 <b>Payment Ready!</b>

Tap below to complete your R49/month subscription.

<i>Reference: <code>TXN-abc123</code></i>
```

```
┌───────────────────────────────────┐
│ [💳 Pay with Paystack →]         │  URL: paystack.com/...
│ [✅ I've Paid — Verify]          │  sub:verify:{ref}
│ [❌ Cancel]                       │  sub:cancel
└───────────────────────────────────┘
```

### Step 4: Verification (Loading)
```html
⏳ <i>Verifying your payment…</i>
```

### Step 5: Confirmation

```html
✅ <b>Payment Confirmed!</b>

Welcome to MzansiEdge Premium, Paul!

<b>Your subscription:</b>
• Plan: Premium (R49/month)
• Status: ✅ Active

You now get unlimited AI-powered tips.
Your edge is live — let's go! 🚀
```

```
┌───────────────────────────────────┐
│ [🔥 Hot Tips]                     │  hot:go
│ [⚽ Your Games]                   │  yg:all:0
└───────────────────────────────────┘
```

---

## 6. LINE MOVEMENT ALERT

Push notification format for sharp money moves. Sent proactively to users who follow the game. Multi-bookmaker aware — shows which bookmaker(s) moved.

### Message Text (Single Bookmaker Move)
```html
📊 <b>Line Movement Alert</b>

⚽ <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️🔥 Edge Rating: PLATINUM (92%)</b>

<b>Arsenal Win — Hollywoodbets:</b>
1.90 → <b>2.15</b> (+13.2%) ↑
🔥 Sharp money moving the line

<i>This often signals major team news
or insider information.</i>
```

### Message Text (Multi-Bookmaker Move — Coordinated Drift)

When 2+ bookmakers move in the same direction:

```html
📊 <b>Line Movement Alert</b>

⚽ <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️🔥 Edge Rating: PLATINUM (92%)</b>

<b>Arsenal Win — Odds drifting across books:</b>
• Hollywoodbets: 1.90 → <b>2.15</b> (+13.2%) ↑
• Betway: 1.95 → <b>2.10</b> (+7.7%) ↑
• Sportingbet: 2.05 (no move)

🔥 Multiple bookmakers adjusting — strong signal.

<i>Best current price: Hollywoodbets @ 2.15 ⭐</i>
```

### Message Text (Opposite Direction — Steam Move)

When odds shorten at one book but drift at another (potential steam move):

```html
📊 <b>Line Movement Alert</b>

🏉 <b>Sharks vs Stormers</b>
📅 Sat 15 Mar, 15:00 SAST

<b>⛏️⭐ Edge Rating: GOLD (78%)</b>

<b>Sharks ML — Mixed movement:</b>
• Hollywoodbets: 1.80 → <b>2.00</b> (+11.1%) ↑
• Betway: 1.85 → <b>1.75</b> (−5.4%) ↓

⚡ Books disagree — HWB offering more value
while Betway shortens. Could be a steam move.

<i>Best current price: Hollywoodbets @ 2.00 ⭐</i>
```

### Keyboard Layout
```
┌───────────────────────────────────────┐
│ [🎯 View Full Breakdown]             │  yg:game:{event_id}
│ [📲 Bet on Hollywoodbets →]           │  URL: hollywoodbets.co.za (best odds)
│ [🔕 Mute Alerts]   [↩️ Menu]         │  unsubscribe:{event_id}  nav:home
└───────────────────────────────────────┘
```

### Edge Rating Badge Placement

Badge sits below the match header, above the line movement data — consistent with the Match Detail placement from Section 3.

### Alert Logic Rules

| Trigger | Action | Message Variant |
|---------|--------|-----------------|
| 1 bookmaker moves >5% | Send alert | Single bookmaker move |
| 2+ bookmakers move same direction >5% | Send alert | Coordinated drift |
| 2 bookmakers move opposite directions >5% | Send alert | Steam move (higher priority) |
| All bookmakers move <5% | No alert | — |
| Only bookmakers without affiliate URLs move | Still send alert | CTA goes to best-odds bookie with URL |

### Notes
- Only sent to users who follow this game (via `subscribe:{event_id}`)
- Triggered when any outcome's odds move >5% from opening at any tracked SA bookmaker
- Max 1 line movement alert per game per user per day
- Edge Rating badge always shown — helps user contextualise the alert
- Affiliate CTA goes to the bookmaker with the best current odds (not necessarily the one that moved)
- "Mute" button respects user choice — no repeated alerts for this game
- For Telegram: these are new messages (not edits) since they're proactive push notifications
- For WhatsApp: these require an approved Template Message (see UX-WHATSAPP-PLAN.md Section 10)

---

## 7. EDGE RATING LEGEND

Shown on first visit (one-time tooltip) or from Hot Tips via a "What's this?" button.

### Message Text
```html
⛏️ <b>Edge Ratings — How It Works</b>

MzansiEdge mines the odds markets to find
where bookmakers have mispriced an outcome.

Our AI compares true probability (calculated
from sharp bookmaker lines) against SA
bookmaker odds. The bigger the gap, the
higher the Edge Rating.

<b>The Tiers:</b>

⛏️🔥 <b>PLATINUM (85%+)</b>
Sharpest edge. Highest conviction pick.
These are rare — jump on them.

⛏️⭐ <b>GOLD (70-84%)</b>
Strong value. The probability gap is
significant. Solid bet.

⛏️🥈 <b>SILVER (55-69%)</b>
Decent edge. Consider for accumulators
or smaller stakes.

⛏️🥉 <b>BRONZE (40-54%)</b>
Modest edge. The market is close to
fair but we see some value.

<i>Tips below 40% are never shown —
that's the AI protecting your bankroll.</i>
```

### Keyboard Layout
```
┌───────────────────────────────────┐
│ [🔥 See Today's Tips]            │  hot:go
│ [↩️ Back]                         │  {previous_screen}
└───────────────────────────────────┘
```

### Notes
- Shown once on first Hot Tips visit (tracked via user flag)
- Also accessible from a small "ℹ️" button in Hot Tips header
- Uses edit-in-place, back returns to Hot Tips summary

---

## Appendix A: Message Character Counts

| Wireframe | Estimated Characters | Within 3500 Limit? |
|-----------|---------------------|-------------------|
| Main Menu | ~120 | Yes |
| Hot Tips Summary (5 items, 2-line format) | ~600 | Yes |
| Match Detail — casual + multi-bookie (4 books) | ~1,400 | Yes |
| Match Detail — experienced + multi-bookie | ~1,300 | Yes |
| Match Detail — newbie (simplified) | ~800 | Yes |
| Match Detail — single bookie fallback | ~900 | Yes |
| Full Comparison View (4D) | ~1,200 | Yes |
| Subscription Prompt | ~450 | Yes |
| Payment Confirmation | ~300 | Yes |
| Line Movement Alert — single bookie | ~400 | Yes |
| Line Movement Alert — coordinated drift | ~550 | Yes |
| Line Movement Alert — steam move | ~500 | Yes |
| Edge Rating Legend | ~800 | Yes |

The largest message is the casual Match Detail with 4 bookmakers across 3 outcomes + line movement (~1,400 chars). With a long AI narrative section, this could reach ~2,000 chars — still well within the 3,500-char safety limit.

**If a match has 5+ bookmakers:** The `chunk_message()` safety net catches any overflow, but the 4-bookmaker cap per outcome (Section 4 rules) prevents this in practice.

## Appendix B: Multi-Bookmaker Data Flow

```
odds_client.fetch_odds_cached(sport_key)
  │
  ├── For each SA bookmaker in SA_BOOKMAKERS where active=True:
  │     Extract odds per outcome
  │
  ├── find_best_sa_odds(event, market)
  │     Returns: list[OddsEntry] sorted by odds desc
  │
  ├── detect_line_movement(event_id, outcome, current_odds)
  │     Compares against odds_history table
  │     Returns: {open, current, pct_change, direction}
  │
  └── Renderer receives:
        {
          "outcomes": [
            {
              "name": "Arsenal Win",
              "is_verdict": true,
              "bookmakers": [
                {"name": "Hollywoodbets", "key": "hollywoodbets",
                 "odds": 2.15, "is_best": true,
                 "movement": {"open": 1.90, "pct": 13.2, "dir": "up"}},
                {"name": "Betway", "key": "betway",
                 "odds": 2.10, "is_best": false,
                 "movement": null},
                ...
              ]
            },
            ...
          ],
          "best_affiliate": {"name": "Hollywoodbets", "url": "..."}
        }
```

This data structure is platform-agnostic — both `telegram_renderer` and `whatsapp_renderer` consume it.
