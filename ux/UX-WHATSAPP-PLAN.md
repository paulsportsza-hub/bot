# MzansiEdge — WhatsApp UX Plan

> Version: 1.0
> Date: 2026-02-25
> Status: PLANNING — Week 2 feature, design starts now
> Dependency: WhatsApp Business API integration (not yet built)

---

## Table of Contents

- [1. Platform Constraints](#1-platform-constraints)
- [2. Formatting Translation](#2-formatting-translation)
- [3. Navigation Model](#3-navigation-model)
- [4. Tip Card Format](#4-tip-card-format)
- [5. Hot Tips Flow](#5-hot-tips-flow)
- [6. Your Games Flow](#6-your-games-flow)
- [7. Subscription Flow](#7-subscription-flow)
- [8. Onboarding Flow](#8-onboarding-flow)
- [9. Settings Flow](#9-settings-flow)
- [10. Notifications & Alerts](#10-notifications--alerts)
- [11. Error States](#11-error-states)
- [12. Shared Logic Architecture](#12-shared-logic-architecture)
- [13. Migration Checklist](#13-migration-checklist)

---

## 1. Platform Constraints

### WhatsApp Business API vs Telegram — Side by Side

| Capability | Telegram | WhatsApp | Impact |
|-----------|----------|----------|--------|
| **Inline buttons** | Unlimited rows, any count | Not available | Use Reply Buttons (max 3) or List Messages (max 10 rows) |
| **Reply Buttons** | N/A (has Reply Keyboard) | Max 3 per message | Primary action pattern; forces cascading menus |
| **List Messages** | N/A | Up to 10 rows, with sections; each row: title (24 chars) + description (72 chars) | Primary list/navigation pattern; replaces numbered buttons |
| **CTA URL button** | `InlineKeyboardButton(url=)` | 1 per message, separate from Reply Buttons | Affiliate link gets its own message OR is the sole CTA |
| **Message editing** | `edit_message_text()` | NOT supported | Every state change = new message. Design shallow flows. |
| **Persistent keyboard** | `ReplyKeyboardMarkup(is_persistent=True)` | Not available (limited menu button) | No always-visible nav bar. Must use "Menu" keyword trigger. |
| **Rich formatting** | HTML: `<b>`, `<i>`, `<code>`, `<a>` | Markdown: `*bold*`, `_italic_`, `~strike~`, ` ```mono``` ` | Must convert all templates. No hyperlinks in text. |
| **Max message length** | 4096 chars | 4096 chars | Same limit, but no chunking with keyboard-on-last |
| **Media** | Photos, documents inline | Photos, documents inline | Can send tip card as image for richer formatting |
| **Session window** | Unlimited (bot can message anytime) | 24-hour window after user's last message | Proactive notifications require approved Template Messages |
| **Template Messages** | N/A | Required for outbound notifications; must be pre-approved by Meta | Morning teasers, line alerts, payment confirmations need templates |
| **Read receipts** | Not available | Blue ticks visible | Users expect faster responses |
| **Typing indicator** | `send_chat_action(TYPING)` | Supported | Use during AI analysis |

### Hard Constraints That Shape WhatsApp UX

1. **No message editing** — the single biggest difference. Every Telegram flow that uses edit-in-place becomes a "new message" flow on WhatsApp. This means:
   - "Back" sends a new summary (not editing the old one)
   - Loading → Result = 2 messages (not 1 edited message)
   - Drill-down and return = 2 new messages minimum
   - Design for **shallow flows** (max 2 levels deep) to avoid chat flooding

2. **3-button limit** — forces cascading menus. Any screen with >3 actions needs either:
   - A "More..." button leading to a second screen (already designed in `whatsapp_menus.py`)
   - A List Message (up to 10 rows, better for tips/games)

3. **24-hour session window** — proactive messages (morning teaser, line alerts) need pre-approved Template Messages. Templates have strict formatting rules and require Meta review.

4. **No persistent navigation** — users must type "Menu" or tap a button to navigate. No always-visible keyboard. Risk of users getting "lost".

---

## 2. Formatting Translation

### Template Conversion Rules

| Telegram HTML | WhatsApp Markdown | Notes |
|--------------|-------------------|-------|
| `<b>text</b>` | `*text*` | Direct equivalent |
| `<i>text</i>` | `_text_` | Direct equivalent |
| `<code>text</code>` | ` ```text``` ` | Inline code; use sparingly |
| `<a href="url">text</a>` | `url` (plain) | No clickable text links; URL must be visible |
| `html.escape(val)` | Not needed | No HTML injection risk in plain text |
| `\n\n` section break | `\n\n` section break | Same |
| `•` bullet | `•` bullet | Same |
| Emoji prefix | Emoji prefix | Same |

### Example: Tip Card Conversion

**Telegram HTML:**
```html
🎯 <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️🔥 Edge Rating: PLATINUM (92%)</b>

📋 <b>The Setup</b>
Arsenal unbeaten in 8 home games.

💡 <i>R100 bet pays R210 · EV: +7.3%</i>
```

**WhatsApp Markdown:**
```
🎯 *Arsenal vs Chelsea*
📅 Sat 15 Mar, 17:30 SAST

*⛏️🔥 Edge Rating: PLATINUM (92%)*

📋 *The Setup*
Arsenal unbeaten in 8 home games.

💡 _R100 bet pays R210 · EV: +7.3%_
```

### Renderer Architecture

The service layer already returns platform-agnostic dicts. `whatsapp_renderer.py` converts to WhatsApp format. The conversion is mechanical — same content, different markup.

```python
# Telegram (existing)
from renderers.telegram_renderer import render_tip_detail
text = render_tip_detail(tip, experience, bankroll)  # Returns HTML

# WhatsApp (new)
from renderers.whatsapp_renderer import render_tip_detail
text = render_tip_detail(tip, experience, bankroll)  # Returns WA markdown
```

---

## 3. Navigation Model

### The "No Edit" Problem

On Telegram, tapping a button edits the current message. On WhatsApp, tapping a button sends a new message. This fundamentally changes navigation:

**Telegram:** `Menu → Tips → Tip #3 → Back → Tips` = 1 message (edited 4 times)
**WhatsApp:** `Menu → Tips → Tip #3 → Back → Tips` = 5 messages

### Design Principles

1. **Shallow flows**: Max 2 levels deep (Summary → Detail). No 3-level nesting.
2. **Always offer "Menu"**: Every message includes a way back to the main menu.
3. **Text triggers**: Support keyword navigation as an alternative to buttons:
   - `menu` or `home` → Main Menu
   - `tips` → Hot Tips
   - `games` → Your Games
   - `settings` → Settings
   - `help` → Help
4. **List Messages for browsing**: Tips, games, and settings use List Messages (not cascading buttons).
5. **Reply Buttons for actions**: Bet, Follow, Back — max 3 per message.

### Main Menu

```
*Welcome to MzansiEdge!* 🇿🇦

What would you like to do?

Type a keyword or pick from the menu below.
```

**List Message** (tap "Menu" button to open):

```
┌─ List Message: "Main Menu" ──────────┐
│                                       │
│ Section: "Betting"                    │
│ ┌───────────────────────────────────┐ │
│ │ 🔥 Hot Tips                       │ │
│ │ Today's top value bets            │ │
│ ├───────────────────────────────────┤ │
│ │ ⚽ Your Games                     │ │
│ │ Upcoming games with edge ratings  │ │
│ ├───────────────────────────────────┤ │
│ │ 📲 Bookmaker Comparison          │ │
│ │ Compare SA bookmaker odds         │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Section: "Account"                    │
│ ┌───────────────────────────────────┐ │
│ │ 📊 My Stats                      │ │
│ │ Your betting performance          │ │
│ ├───────────────────────────────────┤ │
│ │ ⚙️ Settings                      │ │
│ │ Risk, bankroll, notifications     │ │
│ ├───────────────────────────────────┤ │
│ │ ❓ Help                          │ │
│ │ How MzansiEdge works              │ │
│ └───────────────────────────────────┘ │
└───────────────────────────────────────┘
```

**Why List Message:** 6 items in 2 sections. Clean, scannable, fits WhatsApp's pattern. Each row has a title (24 chars max) and description (72 chars max).

---

## 4. Tip Card Format

### Summary Line (in List Message rows)

Each tip appears as a List Message row:

```
Title:       "⛏️🔥 Arsenal vs Chelsea"     (24 chars max)
Description: "Arsenal Win @ 2.10 · EV +7.3% · PLATINUM"  (72 chars max)
```

**Character budget for title:**
- Emoji prefix: 4-5 chars (⛏️🔥 / ⛏️⭐ / ⛏️🥈 / ⛏️🥉)
- Remaining: ~19 chars for match name
- If names are long, abbreviate: "ARS vs CHE" instead of "Arsenal vs Chelsea"

**Character budget for description:**
- Outcome + odds: ~18 chars ("Arsenal Win @ 2.10")
- Separator: 3 chars (" · ")
- EV: ~10 chars ("EV +7.3%")
- Separator: 3 chars (" · ")
- Tier: ~8 chars ("PLATINUM")
- Total: ~42 chars — comfortably within 72

### Full Tip Card (Detail View)

When user taps a tip from the List Message, send a new message:

**Casual experience:**
```
🎯 *Arsenal vs Chelsea*
📅 Sat 15 Mar, 17:30 SAST

*⛏️🔥 Edge Rating: PLATINUM (92%)*

📋 *The Setup*
Arsenal unbeaten in 8 home games, 5 clean sheets.
Chelsea missing key midfielder.

🎯 *The Edge*
Market prices Arsenal win at 52% implied.
Our model says 63% — that's an 11-point gap.

⚠️ *The Risk*
Chelsea could sit deep and counter.

🏆 *Verdict*
Arsenal Win — High conviction.

*Best Odds:*
• Hollywoodbets: *2.15* ⭐
• Betway: 2.10
• Sportingbet: 2.05

📊 _Opened 1.90 → Now 2.15 (+13.2%) ↑_

💡 _R100 bet pays R215 · EV: +7.3%_
```

**Reply Buttons (max 3):**
```
┌──────────────────────────────┐
│ [📲 Bet on Hollywoodbets]    │  CTA URL button
│ [🔔 Follow Game]             │  Reply button
│ [📋 Menu]                    │  Reply button
└──────────────────────────────┘
```

**Important:** The CTA URL button (affiliate link) goes to the *best odds* bookmaker, not always Betway. This maximises user value and affiliate click-through.

**Experienced:**
```
🎯 *Arsenal vs Chelsea*
📅 Sat 15 Mar, 17:30 SAST

*⛏️🔥 PLATINUM (92%)*

📋 *The Setup*
ARS W5 D2 L1 last 8H (62.5%). CHE W3 D1 L4 away.
xG: ARS 1.82/g, CHE 1.21/g.

🎯 *The Edge*
Fair prob 63.2% vs implied 47.6%. Gap: +15.6pp.

*Best Odds:*
• Hollywoodbets: *2.15* ⭐
• Betway: 2.10
• Sportingbet: 2.05

📊 _1.90 → 2.15 (+13.2%) ↑ Sharp movement_

📈 EV: *+7.3%* · Kelly: ```3.8%```
💵 Stake R228 → R490 (+R262)
```

**Newbie:**
```
🎯 *Arsenal vs Chelsea*
📅 Sat 15 Mar, 17:30 SAST

*⛏️🔥 Edge Rating: PLATINUM*
_This is our highest confidence rating — the AI
found a big gap between true odds and bookmaker odds._

📋 *What's Happening*
Arsenal have been great at home — 8 games without a loss.
Chelsea are missing a key player.

🏆 *Our Pick: Arsenal Win*
The bookmakers are giving Arsenal good odds because they
think Chelsea have a chance. Our AI disagrees.

*Where to Bet:*
• Hollywoodbets: *2.15* ⭐ (best price)
• Betway: 2.10

💡 _Bet R20 → get R43 back_
💡 _Bet R50 → get R108 back_

_Start small while you're learning!_
```

---

## 5. Hot Tips Flow

### Entry Point

User types "tips" or taps "Hot Tips" from the List Message menu.

### Loading Message

```
🔥 _Mining the markets across all sports..._
```

WhatsApp supports typing indicators — show `typing` status during the scan.

### Tips Summary

**Message body:**
```
🔥 *Hot Tips — 8 Value Bets*
Scanned 25 markets · Updated 3 min ago

⛏️🔥 1. Arsenal vs Chelsea — Arsenal Win @ 2.15 (92%)
⛏️🔥 2. Sharks vs Stormers — Sharks ML @ 2.15 (88%)
⛏️⭐ 3. Proteas vs India — Proteas ML @ 3.20 (79%)
⛏️⭐ 4. Barcelona vs Real Madrid — BTTS @ 1.75 (76%)
⛏️⭐ 5. Lakers vs Celtics — Lakers +4.5 @ 1.90 (74%)
⛏️🥈 6. Chiefs vs Pirates — Draw @ 3.40 (68%)
⛏️🥈 7. Liverpool vs Spurs — Over 2.5 @ 1.65 (65%)
⛏️🥉 8. Djokovic vs Alcaraz — Djokovic @ 2.15 (62%)

_Tap below for full breakdowns_
```

**List Message button** ("View Tips"):

```
┌─ List Message: "View Tips" ──────────┐
│                                       │
│ Section: "Platinum"                   │
│ ┌───────────────────────────────────┐ │
│ │ ⛏️🔥 Arsenal vs Chelsea          │ │
│ │ Arsenal Win @ 2.15 · PLATINUM     │ │
│ ├───────────────────────────────────┤ │
│ │ ⛏️🔥 Sharks vs Stormers          │ │
│ │ Sharks ML @ 2.15 · PLATINUM       │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Section: "Gold"                       │
│ ┌───────────────────────────────────┐ │
│ │ ⛏️⭐ Proteas vs India            │ │
│ │ Proteas ML @ 3.20 · GOLD         │ │
│ ├───────────────────────────────────┤ │
│ │ ...                               │ │
│ └───────────────────────────────────┘ │
│                                       │
│ (up to 10 rows)                       │
└───────────────────────────────────────┘
```

**Why this works:** The text summary shows the overview. The List Message provides drill-down. Tapping a row sends a new message with the full tip card + 3 buttons. Sections group by Edge Rating tier.

### Pagination

WhatsApp List Messages support up to 10 rows — so all 10 tips fit in one List Message. No pagination needed. If we ever exceed 10, add a "More Tips..." row at position 10 that sends the next batch.

### Flow Diagram

```
User types "tips"
  │
  ├── Bot shows typing indicator
  ├── Bot sends summary text + List Message button
  │
  └── User taps a tip from List Message
        │
        ├── Bot sends full tip card (new message)
        ├── Reply Buttons: [Bet on X →] [Follow] [Menu]
        │
        └── User taps [Menu]
              └── Bot sends Main Menu (new message)
```

---

## 6. Your Games Flow

### Entry Point

User types "games" or taps "Your Games" from menu.

### Games Summary

```
⚽ *Your Games — 12 upcoming*
🔥 3 with edge

_Tap below to browse_
```

**List Message** ("Browse Games"):

```
┌─ List Message: "Browse Games" ───────┐
│                                       │
│ Section: "Today"                      │
│ ┌───────────────────────────────────┐ │
│ │ 🔥 Arsenal vs Chelsea            │ │
│ │ 17:30 · ⛏️🔥 PLATINUM edge       │ │
│ ├───────────────────────────────────┤ │
│ │ ⚽ Man City vs Liverpool         │ │
│ │ 20:00 · No edge                   │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Section: "Tomorrow"                   │
│ ┌───────────────────────────────────┐ │
│ │ 🏉 Sharks vs Stormers            │ │
│ │ 15:00 · ⛏️⭐ GOLD edge           │ │
│ ├───────────────────────────────────┤ │
│ │ ...                               │ │
│ └───────────────────────────────────┘ │
└───────────────────────────────────────┘
```

### >10 Games: Pagination

If user follows more than 10 games, the List Message shows the top 10 (edge games first), plus a "Load More..." row at position 10 that triggers the next batch.

### Sport Filter

If user follows 2+ sports, add Reply Buttons for filtering:

```
┌──────────────────────────────┐
│ [⚽ Soccer]                   │
│ [🏉 Rugby]                   │
│ [📋 All Sports]              │
└──────────────────────────────┘
```

Max 3 buttons — show the user's top 2 sports + "All". If 3+ sports, the third button becomes "More..." leading to a second filter screen.

---

## 7. Subscription Flow

The subscription flow is the most complex WhatsApp adaptation because it requires payment processing outside the chat.

### Step 1: Upsell Trigger

Same triggers as Telegram: 3rd tip view (soft), premium-only feature (hard gate), weekly recap (win-back).

**Soft nudge message:**
```
💎 *Unlock Full Breakdowns*

You've checked 3 tips today — you're clearly
looking for edges. Premium gets you:

*Free (current):*
• 1 AI tip per day
• Basic odds display

*Premium (R49/month):*
• Unlimited AI tips
• Full match breakdowns
• Kelly stake sizing
• Line movement alerts

That's less than R2 a day.
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [💎 Go Premium]              │
│ [⏭️ Not Now]                │
└──────────────────────────────┘
```

### Step 2: Email Collection

```
💎 *MzansiEdge Premium — R49/month*

To subscribe, reply with your *email address*.
_(Used for Paystack payment — never shared.)_
```

No buttons — user types their email. Bot validates format.

### Step 3: Payment Link

```
💳 *Payment Ready!*

Tap below to complete your R49/month subscription.

Reference: ```TXN-abc123```

_After paying, tap "I've Paid" to verify._
```

**Buttons:**
```
┌──────────────────────────────┐
│ [💳 Pay with Paystack →]     │  CTA URL button
│ [✅ I've Paid]               │  Reply button
│ [❌ Cancel]                  │  Reply button
└──────────────────────────────┘
```

**Key difference from Telegram:** The CTA URL button is the only way to link out. It appears as a distinct button type in WhatsApp. The "I've Paid" and "Cancel" are Reply Buttons.

### Step 4: Verification

```
⏳ _Verifying your payment..._
```

Then (new message — can't edit):

**Success:**
```
✅ *Payment Confirmed!*

Welcome to MzansiEdge Premium!

*Your subscription:*
• Plan: Premium (R49/month)
• Status: ✅ Active

You now get unlimited AI-powered tips.
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [🔥 Hot Tips]                │
│ [⚽ Your Games]              │
│ [📋 Menu]                   │
└──────────────────────────────┘
```

**Failure:**
```
❌ *Payment Not Found*

We couldn't verify your payment yet.

This could happen if:
• The payment is still processing
• The payment didn't go through

_No charge was made. Try again or check your bank._
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [🔄 Try Again]               │
│ [💳 Pay Again →]             │  CTA URL
│ [📋 Menu]                   │
└──────────────────────────────┘
```

### Step 5: Renewal & Cancellation (Template Messages)

These are proactive messages sent outside the 24-hour window — must be Template Messages.

**Renewal reminder (3 days before):**
```
Template: mzansiedge_renewal_reminder
Body: "Your MzansiEdge Premium renews in 3 days (R49). Reply CANCEL to stop, or do nothing to continue."
```

**Payment success:**
```
Template: mzansiedge_payment_success
Body: "✅ Your MzansiEdge Premium has been renewed (R49). Your edge is live!"
```

**Payment failure:**
```
Template: mzansiedge_payment_failed
Body: "⚠️ Your MzansiEdge Premium payment failed. Update your details to keep access: {{url}}"
```

---

## 8. Onboarding Flow

### Challenge

Telegram onboarding uses 8 steps with edit-in-place. On WhatsApp, each step = a new message. That's 8+ messages before the user gets any value.

### Strategy: Compressed Onboarding

Reduce to **4 messages** by combining steps and using smart defaults:

**Message 1: Welcome + Experience**
```
👋 *Welcome to MzansiEdge!*

AI-powered sports betting tips for SA.
Let's set up your profile in 3 quick steps.

*How would you describe yourself?*
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [🎓 Experienced Bettor]     │
│ [🎯 Casual Fan]             │
│ [🌱 New to Betting]         │
└──────────────────────────────┘
```

**Message 2: Sports + Leagues**
```
*What sports do you follow?*

_Tap below to pick your sports and leagues._
```

**List Message** ("Pick Sports"):
```
┌─ List Message: "Pick Sports" ────────┐
│                                       │
│ Section: "Popular in SA"              │
│ ┌───────────────────────────────────┐ │
│ │ ⚽ Soccer                         │ │
│ │ PSL, EPL, La Liga, UCL            │ │
│ ├───────────────────────────────────┤ │
│ │ 🏉 Rugby                         │ │
│ │ URC, Super Rugby, Currie Cup      │ │
│ ├───────────────────────────────────┤ │
│ │ 🏏 Cricket                       │ │
│ │ CSA, IPL, T20 World Cup           │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Section: "More Sports"                │
│ ┌───────────────────────────────────┐ │
│ │ 🎾 Tennis                        │ │
│ │ ATP, WTA, Grand Slams             │ │
│ ├───────────────────────────────────┤ │
│ │ 🥊 Boxing & MMA                  │ │
│ │ Major Bouts, UFC                  │ │
│ ├───────────────────────────────────┤ │
│ │ 🏀 Basketball                    │ │
│ │ NBA, EuroLeague                   │ │
│ └───────────────────────────────────┘ │
└───────────────────────────────────────┘
```

**Limitation:** List Messages are single-select. For multi-sport selection, the user taps one sport at a time. After each selection, bot confirms and asks "Pick another sport or tap Done":

```
✅ Added *Soccer* (PSL, EPL)

Pick another sport or tap Done.
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [➕ Add Sport]               │  → Shows List Message again
│ [✅ Done]                    │
└──────────────────────────────┘
```

**Message 3: Risk + Bankroll**
```
*Almost done!*

*Risk appetite:*
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [🛡️ Conservative]           │
│ [⚖️ Moderate]               │
│ [🔥 Aggressive]              │
└──────────────────────────────┘
```

After selection:

```
*Weekly bankroll?*
Reply with an amount (e.g. R1000) or pick:
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [R1,000]                     │
│ [R2,000]                     │
│ [Not Sure]                   │
└──────────────────────────────┘
```

**Message 4: Confirmation**
```
✅ *You're all set!*

*Your Profile:*
• Experience: Casual
• Sports: Soccer (PSL, EPL), Rugby (URC)
• Risk: Moderate
• Bankroll: R1,000

Your edge is live — let's go!
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [🔥 Hot Tips]                │
│ [⚽ Your Games]              │
│ [⚙️ Edit Settings]          │
└──────────────────────────────┘
```

### What's Deferred

- **Favourite teams:** Skipped during WhatsApp onboarding (too many messages). Default to all teams in selected leagues. Users can add favourites later via Settings.
- **Notification time:** Default to 7 AM for morning teasers. Editable in Settings.
- **Betting Story quiz:** Deferred to post-onboarding. Offer via Settings.

---

## 9. Settings Flow

### Entry Point

User types "settings" or taps Settings from menu.

**Message:**
```
⚙️ *Settings*

_Tap below to manage your preferences._
```

**List Message** ("Settings"):
```
┌─ List Message: "Settings" ───────────┐
│                                       │
│ Section: "Betting"                    │
│ ┌───────────────────────────────────┐ │
│ │ 🎯 Risk Profile                  │ │
│ │ Currently: Moderate               │ │
│ ├───────────────────────────────────┤ │
│ │ 💰 Bankroll                      │ │
│ │ Currently: R1,000/week            │ │
│ ├───────────────────────────────────┤ │
│ │ ⚽ My Sports                     │ │
│ │ Soccer, Rugby                     │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Section: "Notifications"              │
│ ┌───────────────────────────────────┐ │
│ │ ⏰ Notification Time              │ │
│ │ Currently: 7 AM                   │ │
│ ├───────────────────────────────────┤ │
│ │ 🔔 Notification Types            │ │
│ │ 5 of 7 enabled                    │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Section: "Account"                    │
│ ┌───────────────────────────────────┐ │
│ │ 💎 Subscription                  │ │
│ │ Premium · Renews 15 Mar           │ │
│ ├───────────────────────────────────┤ │
│ │ 🔄 Reset Profile                 │ │
│ │ Start fresh                       │ │
│ └───────────────────────────────────┘ │
└───────────────────────────────────────┘
```

Each setting selection sends a new message with the current value and Reply Buttons to change it. Example for Risk:

```
🎯 *Risk Profile*

Current: *Moderate*
• Min EV: 3%
• Kelly fraction: 0.50

Pick a new profile:
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [🛡️ Conservative]           │
│ [⚖️ Moderate ✓]             │
│ [🔥 Aggressive]              │
└──────────────────────────────┘
```

---

## 10. Notifications & Alerts

### Template Messages Required

All proactive messages (outside 24-hour window) need pre-approved templates:

| Template Name | Trigger | Body |
|--------------|---------|------|
| `morning_teaser` | Daily at user's notification hour | "🔥 MzansiEdge found {count} value bets today. Your top edge: {match} — {outcome} @ {odds} ({tier}). Reply TIPS to see all." |
| `line_movement` | Odds move >5% on followed game | "📊 Line alert: {match} — {outcome} moved from {old} to {new} ({pct}%). Reply TIPS for details." |
| `game_reminder` | 1 hour before followed game | "⚽ {match} starts in 1 hour. Edge: {tier} ({confidence}%). Reply TIPS to review." |
| `payment_success` | Paystack webhook | "✅ MzansiEdge Premium activated! R49/month. Reply MENU to start." |
| `payment_failed` | Paystack webhook | "⚠️ Your payment failed. No charge was made. Tap to try again: {url}" |
| `renewal_reminder` | 3 days before renewal | "Your MzansiEdge Premium renews in 3 days (R49). Reply CANCEL to stop." |
| `weekly_recap` | Weekly (Sunday evening) | "📊 Your week: {wins}/{total} tips correct ({pct}%). Best: {best_match} at {odds}. Reply STATS for full breakdown." |

### 24-Hour Window Messages

These are sent as regular messages within the session window (user interacted recently):

- Live score updates for followed games
- AI analysis responses
- Payment verification results
- Setting change confirmations

### Notification Throttling

Same rules as Telegram, but enforced more strictly because WhatsApp has stronger spam penalties:

- Max 1 proactive template per user per day (morning teaser OR line alert, not both)
- Line movement alerts only for followed games
- Game reminders only for followed games with edge
- Users must be able to reply STOP to opt out (WhatsApp requirement)

---

## 11. Error States

### Conversion from Telegram

Error messages need the same content but different formatting and recovery paths:

**No Tips Found:**
```
🔥 *Hot Tips*

No edges found right now — the market is efficient.
The AI is protecting your bankroll.

Check back when more games open.
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [⚽ Your Games]              │
│ [🔄 Refresh]                │
│ [📋 Menu]                   │
└──────────────────────────────┘
```

**Odds Unavailable:**
```
⚠️ *Odds Loading Issue*

Couldn't fetch live odds right now.
Give it a few minutes and try again.

_Your bankroll is safe — no bets placed automatically._
```

**Reply Buttons:**
```
┌──────────────────────────────┐
│ [🔄 Try Again]               │
│ [📋 Menu]                   │
└──────────────────────────────┘
```

**Stale Odds (inline warning):**
```
⚠️ _Odds last updated 45 min ago — may have changed_
```

Appended to any tip card where odds data is >30 minutes old.

**Unknown Input:**
```
🤔 I didn't understand that.

Type *menu* to see your options, or try:
• *tips* — Today's value bets
• *games* — Your upcoming games
• *settings* — Update preferences
```

No buttons — keep it simple. User types a keyword.

---

## 12. Shared Logic Architecture

### Current Service Layer (Already Platform-Agnostic)

```
services/
  user_service.py       ← Profile data, archetype, onboarding
  schedule_service.py   ← Game schedule, tips data
  picks_service.py      ← Picks pipeline
  templates.py          ← Message strings (telegram + whatsapp variants)

renderers/
  telegram_renderer.py  ← HTML formatting
  whatsapp_renderer.py  ← WhatsApp markdown formatting (needs expansion)
  whatsapp_menus.py     ← Menu definitions (needs update for List Messages)
```

### What Needs Building

| Component | Description | Effort |
|-----------|-------------|--------|
| `whatsapp_bot.py` | WhatsApp Business API handler (webhook receiver, message dispatcher) | Large |
| `whatsapp_renderer.py` | Expand: tip cards, multi-bookmaker, Edge Rating, line movement | Medium |
| `whatsapp_menus.py` | Update: List Message definitions, section groupings | Small |
| `whatsapp_session.py` | Session state: track user's current flow, last message, 24h window | Medium |
| Template Messages | Draft and submit to Meta for approval (7 templates) | Medium |
| `services/templates.py` | Add WhatsApp variants for new templates (multi-bookie, edge rating) | Small |

### Renderer Parity Checklist

| Renderer Function | Telegram | WhatsApp | Status |
|-------------------|----------|----------|--------|
| `render_profile_summary` | Done | Done | Ready |
| `render_schedule` | Done | Done | Ready |
| `render_picks_header` | Done | Done | Ready |
| `render_no_picks` | Done | Done | Ready |
| `render_game_tips` | Done | Done | Ready |
| `render_tip_detail` | Done | Done (basic) | Needs Edge Rating, multi-bookie |
| `render_hot_tips_summary` | Not yet | Not yet | New function needed |
| `render_multi_bookmaker_odds` | Not yet | Not yet | New function needed |
| `render_line_movement` | Not yet | Not yet | New function needed |
| `render_edge_rating_legend` | Not yet | Not yet | New function needed |
| `menu_buttons` | N/A | Done (basic) | Needs List Message format |
| `list_message_tips` | N/A | Not yet | New function needed |
| `list_message_games` | N/A | Not yet | New function needed |
| `list_message_settings` | N/A | Not yet | New function needed |

---

## 13. Migration Checklist

### Phase 1: Foundation (Week 2)

- [ ] Set up WhatsApp Business API account
- [ ] Implement webhook receiver (`whatsapp_bot.py`)
- [ ] Implement keyword routing (menu, tips, games, settings, help)
- [ ] Build session state manager (track current flow, 24h window)
- [ ] Expand `whatsapp_renderer.py` with all tip card formats
- [ ] Build List Message helpers for tips, games, settings, onboarding

### Phase 2: Core Flows (Week 2-3)

- [ ] Implement compressed onboarding (4 messages)
- [ ] Implement Hot Tips flow with List Messages
- [ ] Implement Your Games flow with List Messages
- [ ] Implement tip detail with Reply Buttons + CTA URL
- [ ] Implement Settings flow with List Messages
- [ ] Implement subscription flow (email → Paystack link → verify)

### Phase 3: Notifications (Week 3)

- [ ] Draft 7 Template Messages
- [ ] Submit to Meta for approval (allow 1-3 business days)
- [ ] Implement morning teaser delivery
- [ ] Implement line movement alerts
- [ ] Implement game reminders
- [ ] Implement payment notifications

### Phase 4: Polish (Week 3-4)

- [ ] Error states for all flows
- [ ] Stale odds warnings
- [ ] Edge Rating legend (text trigger: "edge" or "ratings")
- [ ] Multi-bookmaker odds display
- [ ] User testing with 5 SA beta users
- [ ] STOP/opt-out compliance

### Testing Strategy

- [ ] Unit tests: all WhatsApp renderer functions
- [ ] Integration tests: webhook → handler → response cycle
- [ ] Manual testing: real WhatsApp with test phone number
- [ ] Template Message approval: verify all 7 pass Meta review

---

## Appendix A: WhatsApp vs Telegram UX Decision Matrix

For each Telegram pattern, the optimal WhatsApp equivalent:

| Telegram Pattern | WhatsApp Equivalent | Notes |
|-----------------|---------------------|-------|
| Edit-in-place state transitions | New message per state | Accept more messages; keep flows shallow |
| Inline keyboard (many buttons) | List Message (up to 10 rows) | Primary navigation and browsing |
| Inline keyboard (2-3 actions) | Reply Buttons (max 3) | Action confirmations, simple choices |
| URL button (affiliate) | CTA URL button (1 per msg) | Can't combine with >2 Reply Buttons |
| Numbered `[1]-[5]` buttons | List Message rows | Tapping a row triggers the action |
| Persistent reply keyboard | Keyword triggers ("menu") | No persistent UI; train users to type keywords |
| Pagination (Prev/Next) | "Load More..." row in List | Or Reply Button: "Next Page" |
| Confirmation dialog | Reply Buttons: Confirm/Cancel | Same pattern, 2 buttons |
| Loading → edit to result | Loading message → new result message | 2 messages instead of 1 |
| Progress animation (edit cycle) | Typing indicator | Can't animate messages |

## Appendix B: WhatsApp Business API Message Types

Reference for developers building `whatsapp_bot.py`:

```python
# 1. Text Message (simple)
{
    "type": "text",
    "text": {"body": "Hello!"}
}

# 2. Interactive: Reply Buttons (max 3)
{
    "type": "interactive",
    "interactive": {
        "type": "button",
        "body": {"text": "Choose an option:"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "hot:go", "title": "Hot Tips"}},
                {"type": "reply", "reply": {"id": "yg:all:0", "title": "Your Games"}},
                {"type": "reply", "reply": {"id": "nav:home", "title": "Menu"}},
            ]
        }
    }
}

# 3. Interactive: List Message (up to 10 rows, with sections)
{
    "type": "interactive",
    "interactive": {
        "type": "list",
        "body": {"text": "Hot Tips — 8 Value Bets"},
        "action": {
            "button": "View Tips",
            "sections": [
                {
                    "title": "Platinum",
                    "rows": [
                        {
                            "id": "hot:detail:0",
                            "title": "⛏️🔥 ARS vs CHE",
                            "description": "Arsenal Win @ 2.15 · EV +7.3%"
                        },
                    ]
                },
            ]
        }
    }
}

# 4. Interactive: CTA URL (1 button)
{
    "type": "interactive",
    "interactive": {
        "type": "cta_url",
        "body": {"text": "Bet on Hollywoodbets"},
        "action": {
            "name": "cta_url",
            "parameters": {
                "display_text": "📲 Bet on Hollywoodbets →",
                "url": "https://www.hollywoodbets.co.za"
            }
        }
    }
}

# 5. Template Message (proactive, requires approval)
{
    "type": "template",
    "template": {
        "name": "morning_teaser",
        "language": {"code": "en"},
        "components": [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "8"},
                    {"type": "text", "text": "Arsenal vs Chelsea"},
                ]
            }
        ]
    }
}
```
