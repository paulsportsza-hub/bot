# MzansiEdge UX Audit — Day 5

> Audited: bot.py (4,495 lines), telegram_renderer.py, whatsapp_renderer.py, whatsapp_menus.py, templates.py
> Date: 2026-02-24
> Auditor: UX Designer Agent

---

## 1. Architecture Overview

The bot has a well-structured dual-keyboard system:
- **Persistent Reply Keyboard** (sticky, always visible): 2x3 grid — Your Games, Hot Tips, Guide, Profile, Settings, Help
- **Inline Keyboards**: Contextual buttons attached to individual messages for navigation and actions

Message rendering is separated into a service layer (platform-agnostic data) and renderer layer (Telegram HTML / WhatsApp plain text). Templates are centralised in `services/templates.py`. This architecture is solid for dual-platform support.

---

## 2. Message Density Analysis

### CRITICAL: Hot Tips — Message Spam (bot.py:2652-2737)

**Current behaviour:** `_do_hot_tips_flow()` sends **up to 7 separate messages** for 5 tips:
1. Loading message (deleted)
2. Header message: "Hot Tips — N Value Bets"
3. Tip #1 (individual message with Betway button)
4. Tip #2 (individual message with Betway button)
5. Tip #3 (individual message with Betway button)
6. Tip #4 (individual message with Betway button)
7. Tip #5 (individual message with Betway button)
8. Footer message (Refresh, Your Games, Menu buttons)

**Impact:** User's chat floods with 7 messages. Each tip is a full-width message with its own inline button. Scrolling back is annoying. If the user taps "Refresh", they get 7 MORE messages. This compounds rapidly.

**Paul's spec:** "A single message with the 10 top bets ordered by confidence and exciting emojis for the best of the best with numbered buttons below that give more detail."

### ALSO AFFECTED: Legacy Picks Flow (bot.py:2866-2988)

`_do_picks_flow()` has the same anti-pattern: header + individual pick cards + footer = up to 7 messages.

### GOOD: Your Games (bot.py:2199-2347)

Your Games returns a **single message** with all games listed, inline buttons per game, pagination, sport filters, and navigation. This is the correct pattern.

### GOOD: Game Breakdown (bot.py:3210-3383)

Uses `edit_message_text` to replace the current message in-place. AI analysis, odds, and action buttons all in one message. Back button returns to Your Games. Correct pattern.

### Message Density Summary

| Flow | Messages Sent | Target | Status |
|------|--------------|--------|--------|
| Hot Tips | 7 (header + 5 tips + footer) | 1 | **FIX NEEDED** |
| Legacy Picks | 7 (header + 5 picks + footer) | 1 | **FIX NEEDED** |
| Your Games | 1 (paginated) | 1 | Good |
| Game Breakdown | 1 (edit in-place) | 1 | Good |
| Onboarding steps | 1 (edit in-place) | 1 | Good |
| Morning Teaser | 1 | 1 | Good |
| /start (returning) | 2 (welcome + quick menu) | 1-2 | Acceptable |
| Profile | 1 | 1 | Good |
| Settings | 1 (edit in-place) | 1 | Good |

---

## 3. Flow Sequences Examined

### 3.1 Onboarding (8 steps)

**Flow:** /start -> experience -> sports -> leagues -> favourites (per league) -> risk -> bankroll -> notify -> summary -> done -> story quiz

**Findings:**
- Uses `edit_message_text` throughout — single message updates in place. **Excellent.**
- Back buttons on every step except first. **Good.**
- Step counter (Step N/8) provides clear progress. **Good.**
- Sticky keyboard hidden during onboarding with `ReplyKeyboardRemove()`. **Good.**
- Auto-select for single-league sports. **Good efficiency.**
- Fuzzy matching for team input with alias support. **Good.**
- Post-onboarding: welcome + story quiz CTA + keyboard activation = 2-3 messages. **Acceptable.**

**Minor issues:**
- After onboarding completion, `handle_ob_done()` sends the welcome message via `edit_message_text` AND then sends a separate keyboard activation message (line 1731-1736). This could potentially be one message, but since the sticky keyboard requires `send_message`, this is a technical limitation. **Acceptable.**

### 3.2 Hot Tips (Primary Value Proposition)

**Flow:** Tap "Hot Tips" -> loading -> header -> tip1 -> tip2 -> ... -> tip5 -> footer

**Critical issue:** Already documented above — sends 7 separate messages.

**Other notes:**
- Scans 25 Odds API sport keys. **Good breadth.**
- 15-minute cache prevents excessive API calls. **Good.**
- Top 5 sorted by EV. Paul wants **top 10** sorted by confidence.
- Currently uses EV as ranking metric. Paul wants **confidence** as ranking.
- No confidence-based emoji differentiation. Paul wants 🔥/⭐/✅.
- Each tip has its own Betway affiliate button — this is actually good for conversion but bad for UX density.

### 3.3 Your Games

**Flow:** Tap "Your Games" -> single paginated message with game list -> tap game -> AI breakdown (edit in-place) -> back to list

**Excellent pattern:**
- Single message with all games
- Edge indicators (🔥) on high-EV games
- Sport filter emoji buttons when 2+ sports
- Pagination (10 per page)
- Game buttons with abbreviated team names
- 7-day navigation in sport-specific view
- Back/Menu navigation consistent

**Minor issues:**
- Game buttons use format `[1] ⚽ ARS vs CHE 🔥` — functional but could be more compact as numbered buttons to match Paul's vision.

### 3.4 Subscription Flow

**Flow:** /subscribe -> email prompt -> Paystack link + "I've Paid" button -> verification -> confirmation

**Findings:**
- Uses ConversationHandler for email collection. **Good.**
- Loading message during payment setup. **Good.**
- "I've Paid - Verify" button for manual verification. **Smart for SA connectivity.**
- Check Again button if payment pending. **Good.**
- Cancel option throughout. **Good.**
- Webhook auto-confirms for instant verification. **Excellent.**
- Premium status check prevents double-subscribe. **Good.**

### 3.5 Settings

**Flow:** Settings button -> profile summary + menu -> sub-screens (risk, bankroll, notify, sports, story, reset)

**Findings:**
- All sub-screens use `edit_message_text`. **Good.**
- Notification toggles: tap to toggle, re-renders in-place. **Good.**
- Reset flow: warning -> confirm -> restart onboarding. **Good safety.**

**Issue:**
- "Change Sports" (line 3912-3917) just says "Use /start to redo onboarding" — this is a dead end. Users should be able to edit sports without full re-onboarding.
- Notification toggle view has inconsistency: initial view shows 7 notification types (line 3951-3963) but the re-render after toggle only shows 6 (line 3978-3985 — missing `live_scores`). **Bug.**

### 3.6 Profile View

**Flow:** Tap "Profile" -> summary message with "Edit Profile" button

**Clean, correct. One message.**

### 3.7 Morning Teaser (Scheduled)

**Good format:** Single message with top pick preview + buttons. Respects notification hour preference and daily_picks opt-in.

---

## 4. Button Patterns & Callback Routing

### Callback Convention
All callbacks use `prefix:action` format. Clean and well-organised:
- `yg:all:0`, `yg:sport:soccer:0:0`, `yg:game:{id}` — Your Games
- `hot:go`, `hot:show` — Hot Tips
- `ob_exp:experienced`, `ob_sport:soccer` — Onboarding
- `settings:home`, `settings:risk` — Settings
- `tip:detail:{event_id}:{index}` — Tip detail
- `subscribe:{event_id}`, `unsubscribe:{event_id}` — Live scores
- `sub:verify:{reference}` — Payment verification

### Button Layout Patterns
- Max 2 buttons per row for main menus. **Good for mobile.**
- Navigation always at bottom: Back + Menu. **Consistent.**
- Uses ↩️ for back (not 🔙). **Consistent.**
- Betway affiliate buttons use URL type (opens browser). **Correct.**

---

## 5. Anti-Patterns Found

### Critical (P0)
1. **Hot Tips message spam** — 7 messages instead of 1 summary. This is the #1 UX problem.
2. **Legacy Picks message spam** — Same issue as Hot Tips.

### Medium (P1)
3. **"Change Sports" dead end** — Settings > Sports tells user to /start instead of allowing inline editing.
4. **Notification toggle bug** — `live_scores` notification type dropped from re-render after toggle (line 3985 vs 3963).
5. **No "thinking" indicator cleanup for AI chat** — `freetext_handler` sends "Thinking..." but never deletes it; the reply appears as a new message below, leaving stale "Thinking..." visible.
6. **cmd_menu sends 2 messages** (line 568-580) — welcome text + quick menu inline. Could be combined.
7. **cmd_start for returning users sends 2 messages** (line 537-542) — same issue as cmd_menu.

### Low (P2)
8. **Tip count mismatch** — Hot Tips scans for top 5, Paul wants top 10.
9. **Sorting metric** — Tips sorted by EV%, Paul wants confidence (probability) as primary sort.
10. **No subscription upsell in organic flows** — No premium prompts in Hot Tips or Your Games for free users.
11. **"My Bets" placeholder** — Shows "No active bets yet" with no actual bet tracking. Placeholder text references "Daily Briefing" which doesn't exist.
12. **Leaderboard placeholder** — "Coming soon" with no ETA or preview.

---

## 6. Quick Wins Identified

### Quick Win 1: Consolidate Hot Tips into single message
Convert `_do_hot_tips_flow()` from 7 separate messages to 1 summary message with numbered inline buttons. Highest impact change.

### Quick Win 2: Fix notification toggle bug
Add `live_scores` to the re-render notification type list (line 3985).

### Quick Win 3: Clean up "Thinking..." indicator
In `freetext_handler`, delete the "Thinking..." message before sending the AI reply, or use `edit_message_text` on it.

### Quick Win 4: Combine /start and /menu double messages
Merge welcome text and quick menu into a single message for returning users.

### Quick Win 5: Add upsell touch-point
Add a subtle "Upgrade to Premium" row at the bottom of Hot Tips for non-premium users (respecting max 1 unsolicited suggestion/day rule).

### Quick Win 6: Fix "My Bets" placeholder text
Change "Daily Briefing" reference to "Hot Tips" to match current naming.

---

## 7. Emoji Usage Patterns

Current emoji usage is generally good but inconsistent:
- 🔥 = Edge indicator (Your Games), Hot Tips branding
- ⚽🏉🏏🎾🥊🏀🏈⛳🏎️🐎 = Sport-specific
- ✅ = Confirmation, match success
- ❌ = Error, loss
- ⚠️ = Warning
- 💰 = Money, value, odds
- 📈 = EV, stats
- 🟢🟡🔴 = Confidence dots in Hot Tips
- 📲 = Betway CTA

**Missing from Paul's spec:**
- 🔥 for highest confidence (90%+)
- ⭐ for high confidence (75-89%)
- ✅ for good confidence (<75%)

---

## 8. WhatsApp Readiness Assessment

### Already Done
- Service layer returns platform-agnostic data (dicts)
- `whatsapp_renderer.py` exists with WhatsApp-safe plain text formatting
- `whatsapp_menus.py` documents 3-button menu cascading
- `TELEGRAM_KEYBOARD_AUDIT` maps every keyboard to button count + WA adaptation needed
- DB supports `whatsapp_phone` and `preferred_platform` fields
- Templates have both `telegram` and `whatsapp` variants

### Not Yet Done
- No WhatsApp bot implementation
- WhatsApp List Messages not designed (critical for multi-item views)
- WhatsApp section headers not considered
- No WhatsApp-specific flow documentation

### Key Translation Challenges
- Hot Tips numbered buttons (10 buttons) -> WhatsApp List Message (max 10 rows, natural fit)
- Inline keyboard grids -> Must cascade into 3-button screens
- `edit_message_text` -> WhatsApp doesn't support message editing (must send new messages)
- Persistent reply keyboard -> WhatsApp persistent menu (limited)

---

## 9. Loading / Feedback Patterns

| Action | Loading Indicator | Cleanup | Rating |
|--------|------------------|---------|--------|
| Hot Tips | "Scanning across all markets..." | Deleted | Good |
| Legacy Picks | "Scanning across N leagues..." | Deleted | Good |
| Game Breakdown | "Analysing X vs Y..." | Edited in-place | Good |
| AI Chat | "Thinking..." | **NOT deleted** | Fix needed |
| Payment Setup | "Setting up your payment..." | Deleted | Good |
| Payment Verify | "Verifying your payment..." | Edited in-place | Good |

---

## 10. Tone & Voice Assessment

Current tone matches the brief well:
- "Your edge is live" — confident
- "No edges found right now — the market is efficient" — honest
- "This is the AI protecting your bankroll" — builds trust
- Randomised loading verbs: "Hunting value", "Crunching numbers" — personality

Could be improved:
- Some messages are too formal: "Update your sports in /settings" — could be "Tweak your sports in Settings, bra"
- Error messages are plain: "Unknown action" — should be friendlier
- "Always gamble responsibly" appears inconsistently

---

## Summary Statistics

- **Lines of code audited:** 4,495 (bot.py) + 196 (telegram_renderer) + 152 (whatsapp_renderer) + 130 (whatsapp_menus) + 372 (templates) = **5,345 total**
- **Flows examined:** 7 (onboarding, hot tips, your games, game breakdown, settings, subscription, morning teaser)
- **Anti-patterns found:** 12 (2 critical, 5 medium, 5 low)
- **Quick wins identified:** 6
- **Messages per interaction (current):** Hot Tips 7, everything else 1-2
- **Callback patterns catalogued:** 45+ unique prefixes
