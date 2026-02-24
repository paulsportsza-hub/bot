# MzansiEdge — UX Conventions (v2)

> Version: 2.0 — Playbook-aligned rewrite
> Last Updated: 2026-02-25 (Day 6)
> Status: ACTIVE — canonical UX reference for all developers
> Replaces: v1.0 (Day 5)

---

## Table of Contents

- [A. Message Templates](#a-message-templates)
- [B. Keyboard Layouts](#b-keyboard-layouts)
- [C. Loading Animation Verbs](#c-loading-animation-verbs)
- [D. Callback Data Map](#d-callback-data-map)
- [E. SA Betting Culture Notes](#e-sa-betting-culture-notes)
- [F. Core UX Patterns](#f-core-ux-patterns)
- [G. Edge Rating System](#g-edge-rating-system)
- [H. Navigation Conventions](#h-navigation-conventions)
- [I. WhatsApp Translation Notes](#i-whatsapp-translation-notes)

---

## A. Message Templates

All templates use `ParseMode.HTML`. Copy-paste ready for LeadDev.
Every user-supplied value must be wrapped in `html.escape()` before embedding.

### A1. Match Tip Card (Detail View)

```html
⚽ <b>Match Tip — Premier League</b>

<b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>⛏️ Edge Rating: PLATINUM (92%)</b>

📋 <b>The Setup</b>
Arsenal unbeaten in 8 home games, 5 clean sheets.
Chelsea missing key midfielder. H2H: Arsenal won last 3 at home.

🎯 <b>The Edge</b>
Market prices Arsenal win at 52% implied. Our model says 63%.
That's an 11-point gap — lekker value.

⚠️ <b>The Risk</b>
Chelsea could sit deep and counter. Arsenal's set-piece
defence has been shaky — 3 goals conceded from corners.

🏆 <b>Verdict</b>
Arsenal Win — High conviction. The edge is sharp.

<b>Best Odds:</b>
• Betway: <b>2.10</b> ⭐
• Hollywoodbets: 2.05
• Sportingbet: 2.00

<b>📊 Line Movement:</b>
Opened 1.90 → Now 2.10 (+10.5%)
🔥 Sharp money detected

💡 <i>R100 bet pays R210 · EV: +7.3%</i>
```

### A2. Daily Tips Summary (Hot Tips — Single Message)

```html
🔥 <b>Hot Tips — 10 Value Bets</b>

Scanned 25 markets · Updated 3 min ago

⛏️🔥 1. Arsenal vs Chelsea — Arsenal Win @ 2.10 (92%)
⛏️🔥 2. Sharks vs Stormers — Sharks ML @ 2.15 (88%)
⛏️⭐ 3. Proteas vs India — Proteas ML @ 3.20 (79%)
⛏️⭐ 4. Barcelona vs Real Madrid — BTTS @ 1.75 (76%)
⛏️⭐ 5. Lakers vs Celtics — Lakers +4.5 @ 1.90 (74%)
⛏️🥉 6. Chiefs vs Pirates — Draw @ 3.40 (68%)
⛏️🥉 7. Liverpool vs Spurs — Over 2.5 @ 1.65 (65%)
⛏️🥉 8. Djokovic vs Alcaraz — Djokovic ML @ 2.15 (62%)
⛏️🥉 9. UFC 312 — Fighter A @ 1.80 (60%)
⛏️🥉 10. PGA Event — Player X Top 5 @ 4.50 (55%)

<i>Tap a number for full breakdown</i>
```

### A3. Subscription Prompt

```html
💎 <b>MzansiEdge Premium — R49/month</b>

You're using the free plan (1 tip/day).

<b>Premium unlocks:</b>
• Unlimited AI-powered tips daily
• Full match breakdowns with odds comparison
• Kelly stake sizing for your bankroll
• Line movement alerts
• Early access to new features

That's less than R2 a day — cheaper than a Coke.

<i>Cancel anytime. No lock-in.</i>
```

### A4. Payment Confirmation

```html
✅ <b>Payment Confirmed!</b>

Welcome to MzansiEdge Premium, {name}!

<b>Your subscription:</b>
• Plan: Premium (R49/month)
• Next billing: {next_date}
• Status: ✅ Active

You now get unlimited AI-powered tips.
Your edge is live — let's go.
```

### A5. Edge Rating Explanation (First-Visit Tooltip)

```html
⛏️ <b>Edge Ratings Explained</b>

MzansiEdge mines the odds markets for value.
Here's what each tier means:

⛏️🔥 <b>PLATINUM (85%+)</b>
The sharpest edge. Our AI is highly confident
the market has mispriced this outcome.

⛏️⭐ <b>GOLD (70-84%)</b>
Strong value. Good probability gap between
true odds and bookmaker odds.

⛏️🥈 <b>SILVER (55-69%)</b>
Decent edge. Worth considering, especially
in accumulators.

⛏️🥉 <b>BRONZE (40-54%)</b>
Modest edge. The AI sees some value but
the probability gap is narrow.

<i>Tips below 40% are never shown.</i>
```

### A6. Line Movement Alert (Push Notification)

```html
📊 <b>Line Movement Alert</b>

⚽ <b>Arsenal vs Chelsea</b>
📅 Sat 15 Mar, 17:30 SAST

<b>Arsenal Win:</b> 1.90 → <b>2.10</b> (+10.5%)
🔥 Sharp money detected — line moving fast

⛏️ Edge Rating: <b>PLATINUM (92%)</b>

<i>This game is on your watchlist.</i>
```

### A7. Error / Empty States

**No Tips Found:**
```html
🔥 <b>Hot Tips</b>

No edges found right now — the market is efficient.
The AI is protecting your bankroll.

Check back when more games open, or browse
your games for upcoming matchups.
```

**Odds Unavailable:**
```html
⚠️ <b>Odds Loading Issue</b>

Couldn't fetch live odds right now.
Give it a few minutes and try again.

<i>Your bankroll is safe — no bets placed automatically.</i>
```

**Stale Odds Warning (inline):**
```html
⚠️ <i>Odds last updated 45 min ago — may have changed</i>
```

**Not Onboarded:**
```html
⚙️ <b>Set Up First</b>

Complete your profile to unlock this feature.
It takes 2 minutes.
```

---

## B. Keyboard Layouts

### B1. Main Menu (inline, sent after /start or /menu)

```
┌─────────────────────────────────────┐
│ [⚽ Your Games]     [🔥 Hot Tips]   │  ← 2-col primary
│ [💰 My Bets]        [🏟️ My Teams]   │  ← 2-col secondary
│ [📈 Stats]          [🎰 Bookmakers] │  ← 2-col tertiary
│ [⚙️ Settings]                       │  ← full-width
└─────────────────────────────────────┘
Callbacks: yg:all:0, hot:go, bets:active, teams:view,
           stats:overview, affiliate:compare, settings:home
```

### B2. Persistent Reply Keyboard (sticky, always visible)

```
┌───────────────────────────────────┐
│ [⚽ Your Games] [🔥 Hot Tips]     │
│ [🔴 Live Games] [📊 My Stats]    │
│ [📖 Betway Guide] [⚙️ Settings]  │
└───────────────────────────────────┘
```

### B3. Hot Tips (Summary + Numbered Drill-Down)

```
┌─────────────────────────────────┐
│ [1] [2] [3] [4] [5]           │  ← numbered buttons row 1
│ [6] [7] [8] [9] [10]          │  ← numbered buttons row 2
│ [🔄 Refresh]                    │  ← full-width action
│ [↩️ Menu]                       │  ← full-width nav
└─────────────────────────────────┘
Callbacks: hot:detail:0..9, hot:go, nav:home
```

**If <10 tips, show only that many buttons:**
- 5 or fewer: single row `[1] [2] [3] [4] [5]`
- 6-10: two rows

### B4. Hot Tips — Detail View

```
┌───────────────────────────────────┐
│ [📲 Bet on Betway →]             │  ← full-width CTA (URL)
│ [🔔 Follow this game]            │  ← full-width secondary
│ [↩️ Back to Hot Tips]             │  ← full-width nav
└───────────────────────────────────┘
Callbacks: (url), subscribe:{event_id}, hot:back
```

### B5. Your Games (Paginated List)

```
┌─────────────────────────────────┐
│ [1] [2] [3] [4] [5]           │  ← game buttons
│ [6] [7] [8] [9] [10]          │  ← game buttons (if >5)
│ [⬅️ Prev] [📄 1/2] [Next ➡️]  │  ← pagination (if >1 page)
│ [⚽] [🏉] [🏏]                │  ← sport filters (if 2+)
│ [🔥 Hot Tips] [↩️ Menu]        │  ← nav row
└─────────────────────────────────┘
```

### B6. Match Detail View

```
┌───────────────────────────────────┐
│ [💰 Arsenal Win +7.3%]           │  ← EV+ outcome 1
│ [💰 Over 2.5 +3.1%]              │  ← EV+ outcome 2
│ [📲 Bet on Betway →]             │  ← affiliate CTA (URL)
│ [🔔 Follow this game]            │  ← subscribe to live scores
│ [🔥 Hot Tips]                     │  ← cross-sell
│ [↩️ Back to Your Games]          │  ← back nav
└───────────────────────────────────┘
```

### B7. Subscription Management

```
┌───────────────────────────────────┐
│ [💳 Pay with Paystack →]         │  ← URL button
│ [✅ I've Paid — Verify]          │  ← manual verify
│ [❌ Cancel]                       │  ← cancel flow
└───────────────────────────────────┘
Callbacks: (url), sub:verify:{ref}, sub:cancel
```

**Active subscription:**
```
┌───────────────────────────────────┐
│ [💳 Update Payment Method]       │  ← future
│ [❌ Cancel Subscription]          │  ← confirm required
│ [↩️ Back]                         │  ← nav
└───────────────────────────────────┘
```

### B8. Settings

```
┌───────────────────────────────────┐
│ [🎯 Risk Profile]                │  ← full-width
│ [💰 Bankroll]                     │  ← full-width
│ [⏰ Notifications]                │  ← full-width
│ [📖 My Notifications]            │  ← full-width
│ [⚽ My Sports]                    │  ← full-width
│ [🔄 Reset Profile]               │  ← full-width (destructive, last)
│ [↩️ Back]                         │  ← nav alone
└───────────────────────────────────┘
```

### B9. Navigation (Standard)

```
┌───────────────────────────────────┐
│ [↩️ Back]        [🏠 Main Menu]  │
└───────────────────────────────────┘
```

**OR (playbook-preferred, back alone):**
```
┌───────────────────────────────────┐
│ [↩️ Back]                         │
└───────────────────────────────────┘
```

---

## C. Loading Animation Verbs

### Tips / Odds Scanning
```python
LOADING_TIPS = [
    "Scanning odds",
    "Crunching numbers",
    "Finding value",
    "Comparing bookmakers",
    "Hunting edges",
    "Mining the markets",
]
# Display: "🔥 <i>{verb} across all markets…</i>"
```

### Payments
```python
LOADING_PAYMENTS = [
    "Processing payment",
    "Verifying transaction",
    "Activating subscription",
    "Connecting to Paystack",
]
# Display: "⏳ <i>{verb}…</i>"
```

### AI Analysis
```python
LOADING_ANALYSIS = [
    "Analysing form",
    "Reading the pitch",
    "Studying stats",
    "Mining data",
    "Crunching the numbers",
    "Running the models",
]
# Display: "🤖 <i>{verb} for {home} vs {away}…</i>"
```

### Loading Animation Class (to be implemented)

```python
class LoadingAnimation:
    """Cycles through loading verbs by editing a single message."""

    def __init__(self, bot, chat_id, verbs: list[str], prefix_emoji: str = "🔍"):
        self.bot = bot
        self.chat_id = chat_id
        self.verbs = verbs
        self.prefix = prefix_emoji
        self.msg = None
        self._idx = 0

    async def start(self) -> None:
        self.msg = await self.bot.send_message(
            self.chat_id,
            f"{self.prefix} <i>{self.verbs[0]}…</i>",
            parse_mode=ParseMode.HTML,
        )

    async def advance(self) -> None:
        self._idx = (self._idx + 1) % len(self.verbs)
        if self.msg:
            await self.msg.edit_text(
                f"{self.prefix} <i>{self.verbs[self._idx]}…</i>",
                parse_mode=ParseMode.HTML,
            )

    async def finish(self, text: str, reply_markup=None) -> None:
        """Edit loading message into the final content."""
        if self.msg:
            await self.msg.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=reply_markup,
            )

    async def delete(self) -> None:
        if self.msg:
            try:
                await self.msg.delete()
            except Exception:
                pass
```

---

## D. Callback Data Map

### Navigation
```
nav:home                             → Main menu
nav:tips                             → Hot Tips (alias for hot:go)
nav:settings                         → Settings home
nav:schedule                         → Your Games (legacy redirect)
menu:home                            → Main menu (alias)
```

### Hot Tips
```
hot:go                               → Trigger Hot Tips scan
hot:show                             → Alias for hot:go
hot:detail:{index}                   → Show detail for tip at index (0-based)
hot:back                             → Return to Hot Tips summary
```

### Your Games
```
yg:all:{page}                        → All games, paginated
yg:sport:{key}:{day}:{page}         → Sport-specific 7-day view
yg:game:{event_id}                   → Game detail / AI breakdown
yg:noop                              → No-op (pagination label)
```

### Tips / Match Detail
```
tip:detail:{event_id}:{index}        → Detailed tip analysis
tip:affiliate_soon                   → Placeholder affiliate toast
```

### Schedule (legacy)
```
schedule:tips:{event_id}             → Game tips (legacy, redirects to yg:game:)
schedule:page:{page}                 → Schedule pagination (legacy)
schedule:noop                        → No-op
```

### Settings
```
settings:home                        → Profile summary + settings menu
settings:risk                        → Change risk profile
settings:bankroll                    → Change bankroll
settings:set_bankroll:{amount}       → Set specific bankroll amount
settings:notify                      → Change notification time
settings:sports                      → Change sports
settings:story                       → Notification toggles
settings:toggle_notify:{key}         → Toggle specific notification
settings:reset                       → Reset profile warning
settings:reset:confirm               → Confirm profile reset
```

### Onboarding
```
ob_exp:{level}                       → Set experience (experienced/casual/newbie)
ob_sport:{key}                       → Toggle sport
ob_nav:{action}                      → Navigation (sports_done, back_sports, etc.)
ob_league:{sport}:{league}           → Toggle league
ob_fav:{sport}:{index}               → Toggle favourite
ob_fav_manual:{sport}                → Switch to manual text input
ob_fav_done:{sport}                  → Done with favourites for sport
ob_fav_suggest:{sport}:{index}       → Accept fuzzy suggestion
ob_fav_back:{sport}                  → Back from manual to buttons
ob_fav_retry:{sport}                 → Re-prompt for team input
ob_risk:{profile}                    → Select risk profile
ob_bankroll:{value}                  → Select bankroll (or skip/custom/back)
ob_notify:{hour}                     → Select notification hour
ob_edit:{target}                     → Edit from summary (sports/risk/sport:{key})
ob_summary:show                      → Return to summary
ob_done:finish                       → Complete onboarding
ob_restart:go                        → Restart after reset
```

### Subscriptions
```
subscribe:{event_id}                 → Subscribe to live scores
unsubscribe:{event_id}               → Unsubscribe from live scores
sub:verify:{reference}               → Verify Paystack payment
sub:cancel                           → Cancel subscription flow
```

### Sub-menus
```
bets:active                          → Active bets view
bets:history                         → Bet history
teams:view                           → View followed teams
teams:edit                           → Edit teams menu
teams:edit_league:{sport}:{league}   → Edit teams for specific league
stats:overview                       → Stats overview
stats:leaderboard                    → Leaderboard (coming soon)
affiliate:compare                    → Bookmaker comparison
story:start                          → Start notification quiz
story:pref:{key}:{yes|no}            → Set notification preference
```

---

## E. SA Betting Culture Notes

### Currency
- **Always use R (Rand)**, never $, EUR, or GBP
- Format: `R49`, `R1,000`, `R10,000` (comma at thousands)
- "Less than R2 a day" for subscription anchoring
- Minimum bet context: R10-R20 for newbies, R100 for casual

### Bookmaker Display Order (SA-first)
When multi-bookmaker is active, always show SA bookmakers first:
1. Hollywoodbets
2. Betway SA
3. Sportingbet
4. Supabets
5. 10bet
6. International books (if shown)

Best odds marked with ⭐ suffix. MVP: Betway-only.

### Time
- **Always SAST** (South Africa Standard Time, UTC+2)
- Format: `17:30 SAST` or `Today 17:30` or `Sat 15 Mar, 17:30`
- 24-hour clock (not AM/PM) for brevity

### SA English
**Use naturally:**
- "sharp" (smart, precise), "value", "edge"
- "mate" (not "bro" or "bud")
- "lekker" (sparingly — max once per session)
- "sorted" (confirmed/done)
- "pitch up" (arrive/show up)
- "braai" (only in AI analysis, natural context)

**Never use from the bot:**
- "howzit", "bru", "boet" (too forced for a bot)
- "eish" (could feel patronising)
- Forced Afrikaans translations
- British formality ("whilst", "shall", "rather")

### Odds Display
- Always 2 decimal places: `2.10`, `1.85`, `3.40`
- Always show bookmaker: `2.10 (Betway)`
- Never show sharp bookmaker names to users (Pinnacle, Betfair used internally only)
- EV always with + sign: `+7.3%`, `+2.1%`

### Responsible Gambling
- Footer disclaimer: `<i>Always gamble responsibly. 18+ only.</i>` — on settings/profile screens only
- Never in tip cards (handled by footer)
- Never say "bet now" or "don't miss out"
- Reframe no-tips positively: "The AI is protecting your bankroll"

---

## F. Core UX Patterns

### F1. Single Message, Single Keyboard

Every user interaction produces exactly ONE message with ONE inline keyboard.
- Edit-in-place for flow transitions
- Delete old keyboard message before sending new one (when not editing)
- Never send multiple messages for one logical view

### F2. Summary + Drill-Down

All list views follow this universal pattern:

```
┌─────────────────────────────────┐
│  HEADER (title + count + meta)  │
│                                 │
│  ITEM LIST (1 line per item)    │
│  {emoji} 1. primary — metric   │
│  {emoji} 2. primary — metric   │
│  ...                            │
│                                 │
│  NUMBERED BUTTONS               │
│  [1] [2] [3] [4] [5]          │
│                                 │
│  NAVIGATION                     │
│  [Action] [↩️ Back]             │
└─────────────────────────────────┘
```

Tapping a number edits the message to show the detail view. Detail view always has "Back to {list}" button.

### F3. Edit-in-Place for Flow Transitions

```python
# GOOD: Edit existing message
await query.edit_message_text(new_text, reply_markup=new_kb)

# BAD: Send new message alongside old one
await bot.send_message(chat_id, new_text, reply_markup=new_kb)
```

Exceptions:
- Reply keyboard (must use `send_message` with `reply_markup=ReplyKeyboardMarkup`)
- First message in a flow (nothing to edit yet)

### F4. HTML Escaping

```python
from html import escape

# ALWAYS escape user-supplied values
name = escape(user.first_name)
team = escape(team_name)

text = f"<b>Welcome, {name}!</b>\nFollowing: {team}"
```

### F5. Message Structure Template

```
{emoji} <b>{Title}</b>

{Body section 1}

<b>{Section header}:</b>
• Item one
• Item two

<i>{Footer / disclaimer}</i>
```

Rules:
- Emoji + bold title on first line
- Blank line after title
- Bullet points use `•` (not `-` or `*`)
- Sections separated by blank lines
- Italic for secondary info / disclaimers
- Max ~50 visible characters per line for mobile

---

## G. Edge Rating System

### Mining Theme

MzansiEdge "mines" the odds markets for value. Each tip gets an Edge Rating based on the AI's confidence that the market has mispriced the outcome.

### Tiers

| Tier | Emoji | Confidence | Description |
|------|-------|-----------|-------------|
| PLATINUM | ⛏️🔥 | 85%+ | Sharpest edge. Highest conviction. |
| GOLD | ⛏️⭐ | 70-84% | Strong value. Good probability gap. |
| SILVER | ⛏️🥈 | 55-69% | Decent edge. Worth considering. |
| BRONZE | ⛏️🥉 | 40-54% | Modest edge. Narrow probability gap. |
| — | — | <40% | Never shown. Below minimum threshold. |

### Display Rules
- Always show both emoji AND tier name: `⛏️🔥 PLATINUM (92%)`
- Never show just the percentage without the tier
- Never show tips below 40% confidence
- In summary lists: `⛏️🔥` prefix is sufficient (no tier name needed for space)
- In detail views: full `⛏️🔥 Edge Rating: PLATINUM (92%)` display

### Mapping from Current System
Replace current confidence dots:
- 🟢 (60%+) → Split into PLATINUM (85+), GOLD (70-84), SILVER (55-69)
- 🟡 (40-59%) → BRONZE (40-54%), SILVER (55-59%)
- 🔴 (<40%) → Not shown

---

## H. Navigation Conventions

### Back Button
- Always ↩️ emoji (never 🔙)
- Returns to previous view via `edit_message_text`
- Alone on last row (playbook standard) or paired with Menu

### Main Menu
- 🏠 emoji
- `nav:home` or `menu:home` callback

### Flow Hierarchy
```
Main Menu
├── Your Games
│   ├── All Games (paginated, numbered buttons)
│   │   └── Game Detail (AI breakdown, edit-in-place)
│   └── Sport View (7-day tabs)
│       └── Game Detail
├── Hot Tips
│   └── Tip Detail (AI analysis + odds, edit-in-place)
├── Guide (Telegra.ph link)
├── Profile
│   └── Edit → Settings
├── Settings
│   ├── Risk Profile
│   ├── Bankroll
│   ├── Notifications
│   ├── Sports
│   ├── Notification Toggles
│   └── Reset Profile
├── My Bets
│   ├── Active
│   └── History
├── My Teams
│   ├── View
│   └── Edit (per league)
├── Stats
│   ├── Overview
│   └── Leaderboard
└── Help
```

---

## I. WhatsApp Translation Notes

### Platform Differences

| Feature | Telegram | WhatsApp |
|---------|----------|----------|
| Inline buttons | Unlimited rows | Max 3 buttons per message |
| List view | Inline buttons below text | List Message (up to 10 rows) |
| Message editing | `edit_message_text` | NOT supported |
| Formatting | HTML tags | WhatsApp markdown (`*bold*`, `_italic_`) |
| URL buttons | `InlineKeyboardButton(url=)` | CTA URL button (1 per message) |
| Persistent keyboard | `ReplyKeyboardMarkup` | Limited persistent menu |

### Hot Tips on WhatsApp
- Summary text in message body
- "View Tips" button opens WhatsApp List Message with up to 10 rows
- Each row: title = `⛏️🔥 Arsenal vs Chelsea`, description = `Arsenal Win @ 2.10 (92%)`
- Detail: new message (can't edit) with 3 buttons: Bet, Follow, Back

### Your Games on WhatsApp
- List Message with game rows, sections per day
- Pagination: "Load More" row at bottom
- Sport filter: separate 3-button message

### Settings on WhatsApp
- Cascading 3-button menus (already designed in `whatsapp_menus.py`)
- Screen 1: Risk, Bankroll, More...
- Screen 2: Notifications, Sports, Reset

### Key Constraint
WhatsApp cannot edit messages. "Back" always sends a new summary message.
Design flows to minimise back-and-forth depth.

---

## Appendix: Implementation Priority

| Item | Status | Priority | Notes |
|------|--------|----------|-------|
| HTML escaping (`html.escape`) | TO DO | P0 | All user/API data in messages |
| Hot Tips single-message refactor | TO DO | P0 | Core UX fix |
| Numbered buttons `[1]-[10]` | TO DO | P0 | Hot Tips + Your Games |
| Keyboard lifecycle tracking | TO DO | P0 | `_last_kb_msg_id` pattern |
| AI chat "Thinking..." cleanup | TO DO | P0 | Delete or edit loading msg |
| Edge Rating tiers | TO DO | P1 | Replace confidence dots |
| `LoadingAnimation` class | TO DO | P1 | Reusable loading helper |
| `paginate()` helper | TO DO | P1 | Extract from inline code |
| Chunked text for AI responses | TO DO | P1 | Use `_chunk_message()` |
| Session TTL for state dicts | TO DO | P1 | 30-min expiry |
| Stale odds warning | TO DO | P1 | "Last updated X min ago" |
| `/start` double-message fix | TO DO | P1 | Consolidate to 1 message |
| Line Movement tracking | TO DO | P2 | Needs odds history DB |
| Multi-bookmaker odds display | TO DO | P2 | When more SA books activate |
| WhatsApp List Messages | TO DO | P2 | Blocked on WA integration |
