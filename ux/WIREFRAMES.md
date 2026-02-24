# MzansiEdge — UX Wireframes

> Date: 2026-02-25
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

⛏️🔥 1. ⚽ Arsenal vs Chelsea — Arsenal Win @ 2.10 (92%)
⛏️🔥 2. 🏉 Sharks vs Stormers — Sharks ML @ 2.15 (88%)
⛏️⭐ 3. 🏏 Proteas vs India — Proteas ML @ 3.20 (79%)
⛏️⭐ 4. ⚽ Barcelona vs Real Madrid — BTTS @ 1.75 (76%)
⛏️⭐ 5. 🏀 Lakers vs Celtics — Lakers +4.5 @ 1.90 (74%)

<i>Tap a number for full breakdown</i>
```

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

⛏️🥈 6. ⚽ Chiefs vs Pirates — Draw @ 3.40 (68%)
⛏️🥈 7. ⚽ Liverpool vs Spurs — Over 2.5 @ 1.65 (65%)
⛏️🥉 8. 🎾 Djokovic vs Alcaraz — Djokovic ML @ 2.15 (62%)
⛏️🥉 9. 🥊 UFC 312 — Fighter A @ 1.80 (60%)
⛏️🥉 10. ⛳ PGA Event — Player X Top 5 @ 4.50 (55%)

<i>Tap a number for full breakdown</i>
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

## 3. MATCH DETAIL (Tip Card)

Full AI analysis with odds comparison. Shown when user taps a numbered button from Hot Tips or Your Games.

### Loading State (edit-in-place)
```html
🤖 <i>Analysing form for Arsenal vs Chelsea…</i>
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

<b>Betway Odds:</b>
• Arsenal Win: <b>2.10</b> 💰
• Draw: 3.40
• Chelsea Win: 4.20

💡 <i>R100 bet pays R210 · EV: +7.3%</i>
```

### Message Text (Experienced)
```html
🎯 <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️🔥 Edge Rating: PLATINUM (92%)</b>

📋 <b>The Setup</b>
Arsenal W5 D2 L1 last 8 home (62.5%). Chelsea
W3 D1 L4 away (37.5%). xG: ARS 1.82/g, CHE 1.21/g.

🎯 <b>The Edge</b>
Fair prob 63.2% vs implied 47.6%. Gap: +15.6pp.
Market overweighting Chelsea's recent UCL form.

⚠️ <b>The Risk</b>
Palmer injury doubt. If fit, Chelsea's counter-attack
threat increases. Venue factor may be overstated.

🏆 <b>Verdict</b>
Arsenal Win — High conviction.

<b>Betway Odds:</b>
• Arsenal Win: <b>2.10</b> 💰
• Draw: 3.40
• Chelsea Win: 4.20

📈 EV: <b>+7.3%</b> · Kelly: <code>3.8%</code>
💵 Stake R228 → R479 (+R251)
```

### Keyboard Layout
```
┌───────────────────────────────────┐
│ [📲 Bet on Betway →]             │  URL: betway.co.za
│ [🔔 Follow this game]            │  subscribe:{event_id}
│ [↩️ Back to Hot Tips]             │  hot:back
└───────────────────────────────────┘
```

If accessed from Your Games:
```
┌───────────────────────────────────┐
│ [📲 Bet on Betway →]             │  URL: betway.co.za
│ [🔔 Follow this game]            │  subscribe:{event_id}
│ [🔥 Hot Tips]                     │  hot:go
│ [↩️ Back to Your Games]          │  yg:all:0
└───────────────────────────────────┘
```

---

## 4. MULTI-BOOKMAKER ODDS TABLE

How we display odds from multiple SA bookmakers cleanly within a match detail.

### Single Bookmaker (MVP — Current)
```html
<b>Betway Odds:</b>
• Arsenal Win: <b>2.10</b> 💰
• Draw: 3.40
• Chelsea Win: 4.20
```

### Multi-Bookmaker (Future)
```html
<b>Best SA Odds:</b>

<b>Arsenal Win:</b>
• Hollywoodbets: <b>2.15</b> ⭐
• Betway: 2.10
• Sportingbet: 2.05

<b>Draw:</b>
• Betway: <b>3.50</b> ⭐
• Hollywoodbets: 3.40
• Sportingbet: 3.35

<b>Chelsea Win:</b>
• Sportingbet: <b>4.30</b> ⭐
• Betway: 4.20
• Hollywoodbets: 4.10
```

### Compact Multi-Bookmaker (If Space Constrained)
```html
<b>Best Odds:</b>
• Arsenal Win: <b>2.15</b> (Hollywoodbets) ⭐
• Draw: <b>3.50</b> (Betway) ⭐
• Chelsea Win: <b>4.30</b> (Sportingbet) ⭐

<i>Best odds marked with ⭐</i>
```

### Rules
- Best odds marked with ⭐ on same line
- SA bookmakers only (never show Pinnacle, Betfair, etc.)
- Order: highest odds first within each outcome
- If only 1 bookmaker has odds for that market, no ⭐ (nothing to compare)
- Each bookmaker name is a display name (e.g., "Hollywoodbets" not "hollywoodbets_za")
- Max 4 bookmakers per outcome to keep message compact

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

Push notification format for sharp money moves. Sent proactively to users who follow the game.

### Message Text
```html
📊 <b>Line Movement Alert</b>

⚽ <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>Arsenal Win:</b>
1.90 → <b>2.10</b> (+10.5%)
🔥 Sharp money moving the line

This often signals insider information or
major team news. Worth checking your position.

<b>⛏️ Edge Rating: PLATINUM (92%)</b>
```

### Keyboard Layout
```
┌───────────────────────────────────┐
│ [🎯 View Full Breakdown]         │  yg:game:{event_id}
│ [📲 Bet on Betway →]             │  URL: betway.co.za
│ [🔕 Mute Alerts for This Game]   │  unsubscribe:{event_id}
└───────────────────────────────────┘
```

### Notes
- Only sent to users who follow this game (via subscribe)
- Triggered when any outcome's odds move >5% from opening
- Max 1 line movement alert per game per user per day
- "Mute" button respects user choice — no repeated alerts

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

## Appendix: Message Character Counts

| Wireframe | Estimated Characters | Within 3500 Limit? |
|-----------|---------------------|-------------------|
| Main Menu | ~120 | Yes |
| Hot Tips Summary (5 items) | ~450 | Yes |
| Match Detail (casual) | ~900 | Yes |
| Match Detail (experienced) | ~850 | Yes |
| Multi-Bookmaker (full) | ~600 | Yes |
| Subscription Prompt | ~450 | Yes |
| Payment Confirmation | ~300 | Yes |
| Line Movement Alert | ~400 | Yes |
| Edge Rating Legend | ~800 | Yes |

All wireframes fit well within the 3500-character safety limit. The longest (match detail with AI analysis) could approach ~1500 chars with a long Claude response — still safe.
