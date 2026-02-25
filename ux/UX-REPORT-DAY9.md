# MzansiEdge — Pre-Launch UX Audit (Day 9)

> Date: 2026-02-25
> Agent: UX Designer
> Launch: 14 March 2026 (17 days out)
> Codebase: `bot.py` on branch `ux/playbook-conventions-day6`
> Scope: First-time UX, core journeys, error states, playbook compliance, P0 verification

---

## Table of Contents

- [1. Pre-Launch UX Checklist](#1-pre-launch-ux-checklist)
- [2. Core User Journey Traces](#2-core-user-journey-traces)
- [3. Error State Audit](#3-error-state-audit)
- [4. Playbook Compliance Score](#4-playbook-compliance-score)
- [5. Day 6 P0 Fix Verification](#5-day-6-p0-fix-verification)
- [6. Remaining Issues Ranked by Severity](#6-remaining-issues-ranked-by-severity)
- [7. Launch Readiness Assessment](#7-launch-readiness-assessment)

---

## 1. Pre-Launch UX Checklist

### 1A. First-Time User Experience (/start → New User)

| Check | Pass/Fail | Line(s) | Notes |
|-------|-----------|---------|-------|
| Welcome message is clear and inviting | PASS | 554-559 | "Welcome to MzansiEdge, {name}!" — clear, warm, branded |
| Explains what the bot does in 1-2 sentences | FAIL | 554-559 | Jumps straight to "Let's set up your profile." No 1-liner explaining what MzansiEdge does. A new user who just tapped /start has no idea what this bot offers before being asked for their experience level. |
| Clear CTA | PASS | 561-563 | 3-button experience picker is clear |
| `first_name` escaped with `html.escape()` | PASS | 548 | `name = h(user.first_name or "")` |
| Reply keyboard hidden during onboarding | PASS | 550-553 | `ReplyKeyboardRemove()` sent before onboarding |
| Step indicator shown | PASS | 559 | "Step 1/8" — clear progress indicator |

**Critical gap:** The welcome message for brand-new users doesn't explain what MzansiEdge is. Before asking "What's your betting experience?", add a one-liner like:

```
AI-powered sports betting tips — we find the edges
the bookmakers miss, so you don't have to.
```

### 1B. Returning User Experience (/start → Existing User)

| Check | Pass/Fail | Line(s) | Notes |
|-------|-----------|---------|-------|
| Welcome back message | PASS | 531-537 | "Welcome back, {name}!" |
| Explains available actions | PASS | 536 | "Pick a sport or get an AI tip below." |
| Single message (not double) | PASS | 539-542 | Single `reply_text` with `get_main_keyboard()` — consolidated from Day 5's 2-message pattern |
| `first_name` escaped | PASS | 531 | `name = h(user.first_name or "")` |
| Inline menu included | FAIL | 539-542 | Only sends reply keyboard (`get_main_keyboard()`). No inline keyboard (`kb_main()`) on /start. User must use the sticky bottom keyboard. |
| Shows what changed since last visit | FAIL | — | No "since you left" summary (e.g., "3 new edges found"). Not critical for MVP. |

### 1C. /menu Command

| Check | Pass/Fail | Line(s) | Notes |
|-------|-----------|---------|-------|
| Sends main menu | PASS | 569-579 | Clean menu message |
| `first_name` escaped | FAIL | 858 | `handle_menu` at line 858: `{user.first_name}` NOT escaped. Uses raw `user.first_name` in HTML. |
| Single message | PASS | 577-579 | Single `reply_text` |

### 1D. /help Command

| Check | Pass/Fail | Line(s) | Notes |
|-------|-----------|---------|-------|
| Lists all commands | PASS | 584-608 | 7 commands + keyboard descriptions |
| Explains how tips work | PASS | 604-608 | Brief AI tips explainer |
| Uses `•` bullets | FAIL | 584-608 | Uses `—` dashes for command list, no bullets. Not critical but inconsistent with playbook. |
| Navigation back | PASS | 612 | `kb_nav()` included |

---

## 2. Core User Journey Traces

### Journey A: New User → /start → Browse Tips → View a Tip → See Odds

```
STEP 1: User sends /start
├── bot.py:526-564
├── Two messages sent: (1) "Setting up…" with ReplyKeyboardRemove, (2) Welcome + experience picker
├── ISSUE: 2 messages for new user onboarding start. First "Setting up…" is unnecessary noise.
│
STEP 2: User completes 8-step onboarding
├── experience → sports → leagues → favourites → risk → bankroll → notify → summary
├── All steps use edit-in-place — GOOD
├── Step indicators shown ("Step 3/8") — GOOD
│
STEP 3: Onboarding done → Welcome message
├── bot.py:1698-1720
├── "Welcome to MzansiEdge, {name}!"
├── ISSUE: Line 1698: `name = user.first_name or "champ"` — NOT ESCAPED with h()
├── CTA: "Set Up My Story" → notification quiz — GOOD
│
STEP 4: User taps "🔥 Hot Tips" from reply keyboard
├── bot.py:2618-2697 (_do_hot_tips_flow)
├── Loading: "🔥 {verb} across all markets…" — GOOD
├── Single consolidated message with numbered [1]-[5] buttons — FIXED (was 7 messages)
├── html.escape() on home/away/outcome — FIXED
│
STEP 5: User taps [1] button → tip detail
├── bot.py:3386-3445 (handle_tip_detail)
├── Shows detailed tip with odds, EV, stake info — GOOD
├── Affiliate button → Betway — GOOD
├── "Follow this game" button — GOOD
├── ISSUE: Back button goes to `schedule:tips:{event_id}` — this triggers a GAME TIPS
│   regeneration, NOT a return to the Hot Tips summary. From Hot Tips flow,
│   there is no way back to the consolidated tips list.
│
STEP 6: Odds display
├── Currently single bookmaker (Betway MVP)
├── edge_renderer.py exists with multi-bookmaker support — ready but not wired to Hot Tips
├── Edge Rating calculator exists (services/edge_rating.py) — but NOT used in Hot Tips flow
```

**Journey A verdict:** Mostly functional. Key issues: (1) no "back to Hot Tips" from tip detail, (2) Edge Rating not wired into Hot Tips yet, (3) unescaped `first_name` at onboarding completion.

### Journey B: User → Subscribe → Payment → Confirmation

```
STEP 1: User sees upsell prompt
├── NOT IMPLEMENTED — no paywall gate on free users
│
STEP 2: Email collection
├── NOT IMPLEMENTED
│
STEP 3: Payment link (Paystack)
├── NOT IMPLEMENTED
│
STEP 4: Verification
├── NOT IMPLEMENTED
```

**Journey B verdict:** Subscription/payment flow is NOT built. The `subscribe:` callback (line 802) only handles game-following subscriptions (live score alerts), not monetary subscriptions. The Paystack integration described in CLAUDE.md is not present in the current bot.py.

**Impact:** No revenue gate at launch. All users get the same content. This may be intentional for MVP (free launch, add paywall later) but should be confirmed with Team Lead.

### Journey C: User → Check Today's Tips → Tap a Match → See Breakdown

```
STEP 1: User taps "🔥 Hot Tips" from reply keyboard
├── Fires _do_hot_tips_flow() — GOOD
│
STEP 2: Loading → consolidated tips list
├── Single message with [1]-[10] numbered buttons — GOOD
│
STEP 3: User taps [3] button
├── tip:detail:{event_id}:2 callback — handled by handle_tip_detail
├── Shows tip detail with odds and EV — GOOD
│
STEP 4: Breakdown shown
├── Betway-only odds (MVP) — expected
├── Experience-adaptive formatting (newbie/casual/experienced) — GOOD
├── EV shown as "+X%" — GOOD
│
STEP 5: Back navigation
├── ISSUE: "↩️ Back" goes to schedule:tips:{event_id} which regenerates game tips
│   (a different view) instead of returning to the Hot Tips summary
```

**Journey C verdict:** Works end-to-end but the back navigation from tip detail is broken when accessed from Hot Tips. Should go to `hot:go` or a cached Hot Tips page.

### Journey D: Returning User → What Changed Since Last Visit

```
STEP 1: User sends /start (returning)
├── "Welcome back, {name}!" — generic greeting
├── No "since you left" data (new edges, results of previous tips, etc.)
│
STEP 2: User must manually explore
├── No proactive "X tips hit!" or "Y new edges" summary
```

**Journey D verdict:** Not implemented. Low priority for MVP but would significantly improve retention.

---

## 3. Error State Audit

| Error Scenario | Implemented? | Message Quality | Recovery Action | Line(s) |
|---------------|-------------|-----------------|-----------------|---------|
| No tips available | YES | "No edges found — market is efficient." | Your Games + Menu buttons | 2636-2647 |
| Payment failed | NOT IMPLEMENTED | — | — | — |
| Network/API timeout (odds fetch) | YES | "Could not fetch {league} odds. Try again later." | Nav buttons | 909-911 |
| Network/API timeout (AI chat) | PARTIAL | Generic exception — may show raw error | Nav buttons | 2800-2809 |
| Invalid input (onboarding) | YES | "R50 minimum bankroll" with retry | Retry prompt | 2716-2720 |
| Tip data expired | YES | "Tip data expired. Tap the game again." | Back to Your Games | 3400-3406 |
| Unknown callback action | YES | "Unknown action." | No buttons | 847 |
| No leagues selected | YES | "No leagues selected!" | Settings link | telegram_renderer.py:57-60 |
| No upcoming games | YES | "No upcoming games found" | Settings link | telegram_renderer.py:62-65 |
| AI Claude API error | PARTIAL | Falls back to delete thinking + send error, but error text may be technical | Nav buttons | 2800-2809 |

**Issues found:**

1. **"Unknown action." (line 847)** — Terse, unfriendly, no recovery buttons. Should be:
   ```
   🤔 Something went wrong. Try tapping a button from the menu.
   ```
   With a Menu button.

2. **AI error handling** — If Claude API fails at line 2800-2809, the fallback sends the reply text, but if the API threw an exception before generating `reply`, the error path may not be reached cleanly. Needs verification that the try/except around the Claude call properly catches API errors and shows a friendly message.

3. **Missing payment errors** — No subscription flow means no payment error states.

---

## 4. Playbook Compliance Score

Scoring each of the 22 playbook sections on a 3-point scale:
- **COMPLIANT** (2 pts) — Meets playbook requirements
- **PARTIAL** (1 pt) — Some aspects met, some missing
- **MISSING** (0 pts) — Not implemented

| # | Section | Score | Notes |
|---|---------|-------|-------|
| 1 | Parse Mode & Escaping | PARTIAL (1) | HTML parse mode consistent. `html.escape()` used in most places but missed at lines 858, 1698. |
| 2 | Message Structure | PARTIAL (1) | Emoji + bold titles. But uses `—` dashes instead of `•` bullets in help. |
| 3 | Loading Animations | PARTIAL (1) | Loading messages exist for Hot Tips, AI chat, game analysis. But Hot Tips deletes loading instead of editing. No `LoadingAnimation` class. |
| 4 | Numbered Lists + Buttons | COMPLIANT (2) | Hot Tips now uses `[1]-[10]` numbered buttons in rows of 5. Your Games uses `[1] ⚽ ARS vs CHE` full-width buttons. |
| 5 | Pagination | PARTIAL (1) | Your Games has `📄 1/3` pagination. But GAMES_PER_PAGE=10 (playbook says 5). No reusable `paginate()` helper. Hot Tips has no pagination (shows all tips on 1 page). |
| 6 | Chunked Text | MISSING (0) | `_chunk_message()` defined (line 3515) but never called anywhere. AI responses could exceed 4096 chars. |
| 7 | Keyboard Lifecycle | MISSING (0) | No `_last_kb_msg_id` tracking. Old keyboards accumulate. |
| 8 | Keyboard Layout | PARTIAL (1) | Good 2-column layouts. But Back + Menu on same row (playbook wants Back alone). |
| 9 | Confirmation Dialogs | COMPLIANT (2) | Profile reset has proper confirmation with consequences listed. |
| 10 | Progress Updates | PARTIAL (1) | AI chat edits "Thinking..." into result (fixed). But Hot Tips still deletes loading + sends new. |
| 11 | Callback Conventions | PARTIAL (1) | Consistent `prefix:action` format. But `nav:main` vs `menu:home` duplication for same concept. |
| 12 | Session Management | PARTIAL (1) | `_hot_tips_cache` has 15-min TTL. But `_onboarding_state`, `_story_state`, `_team_edit_state` have no TTL. |
| 13 | Error Recovery | PARTIAL (1) | Most errors have recovery buttons. But "Unknown action." has none. AI error path may not be robust. |
| 14 | Dual Keyboard Coexistence | PARTIAL (1) | /start (returning) sends only reply keyboard, no inline menu. /start (new) sends 2 messages. |
| 15 | Message Editing vs New | PARTIAL (1) | Onboarding, settings, Your Games use edit-in-place. But Hot Tips sends new messages (loading is deleted, result is new msg). |
| 16 | Affiliate Link Handling | COMPLIANT (2) | URL buttons used correctly. `edge_renderer.py` has bookmaker-attributed buttons. |
| 17 | Experience Adaptation | PARTIAL (1) | Tip detail adapts per experience level (newbie/casual/experienced). But Hot Tips summary is same for all. |
| 18 | Notification Throttling | PARTIAL (1) | Morning teaser checks `notification_hour`. But no `last_notification_sent_at` per-user tracking. |
| 19 | Edge Rating System | PARTIAL (1) | `edge_rating.py` implemented with 5-factor scoring. `edge_renderer.py` renders badges. But NOT wired into Hot Tips or tip detail in `bot.py`. |
| 20 | Line Movement Display | MISSING (0) | No line movement tracking or display in the codebase. |
| 21 | Stale Odds Warning | MISSING (0) | No freshness indicator on any odds display. |
| 22 | Multi-Bookmaker Display | PARTIAL (1) | `edge_renderer.py` has `render_odds_comparison()` and `render_tip_with_odds()`. But `bot.py` still uses single-bookmaker display. |

**Total: 20 / 44 (45%)**

**Breakdown:**
- COMPLIANT: 3 sections (9, 16, 4)
- PARTIAL: 15 sections
- MISSING: 4 sections (6, 7, 20, 21)

---

## 5. Day 6 P0 Fix Verification

### P0-1: HTML Escaping

| Status | PARTIALLY FIXED |
|--------|-----------------|

**What was fixed:**
- Line 10: `from html import escape as h` — imported correctly
- Line 531: `name = h(user.first_name or "")` — `/start` returning user: FIXED
- Line 548: `name = h(user.first_name or "")` — `/start` new user: FIXED
- Line 571: `name = h(user.first_name or "")` — `/menu` command: FIXED
- Line 2660-2662: `h(tip.get("home_team", ""))` etc. — Hot Tips: FIXED

**What was NOT fixed:**
- **Line 858:** `handle_menu` callback — `{user.first_name}` used raw in HTML f-string. This is the inline menu "home" handler — hit every time a user taps "🏠 Main Menu" from any screen.
- **Line 1698:** Onboarding completion — `name = user.first_name or "champ"` used raw in HTML. Hit once per user at onboarding finish.

**Severity:** Still P0. Line 858 is hit on EVERY menu navigation. A user with `<b>` in their Telegram name will see broken formatting site-wide.

### P0-2: Hot Tips Multi-Message Spam → Single Message

| Status | FIXED |
|--------|-------|

**Evidence:**
- Lines 2650-2671: Tips built into single `lines` list, joined at 2671
- Lines 2693-2697: Single `bot.send_message()` call
- Lines 2673-2684: Numbered `[1]-[10]` buttons in rows of 5

**Residual issue:** Loading message is deleted (line 2632) then result sent as new message (line 2693). Playbook says edit loading into result. This is a P1 (cosmetic flicker, not a functional bug).

### P0-3: Keyboard Lifecycle Tracking

| Status | NOT FIXED |
|--------|-----------|

No `_last_kb_msg_id` or equivalent found anywhere in bot.py. Grep for `_last_kb`, `last_msg`, `keyboard_msg`, `active_kb` — zero results.

Old inline keyboards still accumulate in chat. The Hot Tips fix (single message) reduces the problem but doesn't solve it systemically.

### P0-4: AI Chat "Thinking..." Message Leak

| Status | FIXED |
|--------|-------|

**Evidence:**
- Line 2800-2802: "Thinking..." message is edited in-place with the AI reply
- Lines 2803-2809: Fallback: if edit fails, delete "Thinking..." then send new message
- No stale "Thinking..." left in chat

### P0-5: Numbered Button Pattern Missing

| Status | FIXED (Hot Tips) / NOT FIXED (Your Games) |
|--------|---------------------------------------------|

**Hot Tips:** Fixed. Lines 2673-2684 implement `[1]-[10]` compact numbered buttons in rows of 5.

**Your Games:** Still uses full-width buttons (one per row). Lines 2274-2277 show `[i] ⚽ ARS vs CHE` style — numbered but full-width, not compact. This is acceptable for Your Games where the button label contains match info, but doesn't match the playbook's compact `[1] [2] [3] [4] [5]` pattern.

### P0 Fix Summary

| P0 Issue | Fixed? | Residual |
|----------|--------|----------|
| HTML Escaping | 80% | Lines 858, 1698 still unescaped |
| Hot Tips Single Message | YES | Loading delete instead of edit (P1) |
| Keyboard Lifecycle | NO | Not implemented |
| AI "Thinking..." Cleanup | YES | Clean fix with fallback |
| Numbered Buttons | 50% | Hot Tips yes, Your Games no |

---

## 6. Remaining Issues Ranked by Severity

### P0 — Fix Before Launch

| # | Issue | Location | Impact | Effort |
|---|-------|----------|--------|--------|
| 1 | `html.escape()` missing on `user.first_name` in `handle_menu` | bot.py:858 | Broken rendering on every menu navigation for users with HTML chars in name | 1 min |
| 2 | `html.escape()` missing on `user.first_name` at onboarding completion | bot.py:1698 | Broken welcome message | 1 min |
| 3 | Notification toggle re-render drops `live_scores` | bot.py:3992-3999 | ⚡ Live Scores option disappears after toggling any notification | 1 min — add missing line |
| 4 | No "Back to Hot Tips" from tip detail | bot.py:3440-3443 | Back button goes to `schedule:tips:` (regenerates game tips) instead of returning to Hot Tips list. User is stranded in a different flow. | 15 min |
| 5 | `hot:back` callback not handled | bot.py:778-780 | If wired, `hot:back` has no handler. The `hot:` prefix only handles `go`/`show`. | 5 min |

### P1 — Fix Soon After Launch

| # | Issue | Location | Impact | Effort |
|---|-------|----------|--------|--------|
| 6 | Edge Rating not wired into Hot Tips or tip detail | bot.py + edge_rating.py | Backend exists, renderer exists, but bot.py doesn't use them. Tips show raw EV% without Edge Rating badge. | 2 hours |
| 7 | Hot Tips loading deleted instead of edited | bot.py:2631-2634, 2693 | Cosmetic flicker — loading disappears then new message appears | 15 min |
| 8 | `_chunk_message()` never called | bot.py:3515 | AI responses could exceed Telegram's 4096 char limit, silently failing | 30 min |
| 9 | Keyboard lifecycle not tracked | entire bot.py | Old keyboards accumulate in chat over time | 1-2 hours |
| 10 | No `paginate()` helper — pagination reimplemented inline | multiple locations | Code duplication, inconsistency risk | 30 min |
| 11 | Welcome message for new users doesn't explain what the bot does | bot.py:554-559 | First-time users don't know what MzansiEdge offers before onboarding starts | 5 min |
| 12 | /start (new user) sends 2 messages | bot.py:550-563 | "Setting up…" + welcome = 2 messages. Should be 1. | 10 min |
| 13 | "Unknown action." fallback is terse and has no buttons | bot.py:847 | User hits a dead end with no recovery | 5 min |
| 14 | Multi-bookmaker odds not wired to bot.py | bot.py + edge_renderer.py | `render_tip_with_odds()` and `render_odds_comparison()` exist but aren't called from any handler | 2 hours |

### P2 — Post-Launch Polish

| # | Issue | Location | Impact | Effort |
|---|-------|----------|--------|--------|
| 15 | GAMES_PER_PAGE = 10 (playbook recommends 5) | bot.py:3139 | Dense pages on mobile | 5 min to change |
| 16 | Help text uses `—` dashes instead of `•` bullets | bot.py:584-608 | Minor inconsistency | 5 min |
| 17 | No stale odds warning on any display | — | Users see cached odds without freshness indicator | 30 min |
| 18 | No line movement display | — | Not built yet (needs odds history infra) | Large |
| 19 | No subscription/payment flow | — | No revenue gate. All content is free. | Large |
| 20 | In-memory state dicts have no TTL (except _hot_tips_cache) | bot.py:70-76 | Memory leak on high traffic — abandoned states persist forever | 1 hour |
| 21 | Session state not cleared on flow switch | bot.py | If user abandons onboarding mid-flow, state leaks | 30 min |
| 22 | `nav:main` vs `menu:home` — two callbacks for same action | bot.py:692, 700 | Confusion for developers, no user impact | 15 min |
| 23 | `LoadingAnimation` class not implemented | — | No progressive loading feedback | 1 hour |

---

## 7. Launch Readiness Assessment

### Overall Verdict: CONDITIONALLY READY

The bot is functional for a soft launch with the following conditions:

### Must Fix Before Launch (17 days)

1. **HTML escaping at lines 858 and 1698** — 2 minutes total. Security/rendering issue.
2. **Notification toggle `live_scores` bug** — 1 minute. Feature is broken.
3. **Hot Tips → Tip Detail → Back navigation** — 15 minutes. Users get stranded.
4. **Welcome message value proposition** — 5 minutes. New users need to know what the bot does.

**Total effort for must-fixes: ~25 minutes.**

### Should Fix Before Launch

5. **Wire Edge Rating into Hot Tips** — 2 hours. The backend is built (`edge_rating.py`, `edge_renderer.py`). Not showing it wastes a key differentiator.
6. **Wire multi-bookmaker odds** — 2 hours. Same — the renderer exists. Without it, every tip shows only Betway.
7. **Use `_chunk_message()` for AI responses** — 30 min. Silent message failures are a terrible user experience.

**Total effort for should-fixes: ~4.5 hours.**

### What Works Well

- Onboarding flow is clean (8 steps, edit-in-place, step indicators)
- Hot Tips consolidation is done and working
- AI chat "Thinking..." cleanup is properly implemented
- Experience-adaptive tip formatting (3 levels)
- Error recovery with action buttons on most error states
- Consistent HTML parse mode throughout
- Affiliate buttons using URL buttons (not inline text links)
- Reply keyboard is persistent and well-structured
- Fuzzy team name matching during onboarding
- `edge_rating.py` scoring system is well-designed (5 factors, 100-point scale)
- `edge_renderer.py` multi-bookmaker display is ready

### What's Missing for a Full Launch

- Subscription/payment flow (Paystack)
- Line movement tracking and display
- Stale odds warnings
- Keyboard lifecycle tracking
- `LoadingAnimation` class
- Reusable `paginate()` helper
- "Since you left" returning user summary

### Recommended Launch Strategy

**Week 1 (now → launch):** Fix the 4 must-fixes + wire Edge Rating and multi-bookmaker display. This gives users the core differentiated experience.

**Week 2 (post-launch):** Add `_chunk_message` usage, keyboard lifecycle, `LoadingAnimation`, and fix the minor UX polish items.

**Week 3-4:** Build subscription/payment flow, line movement, stale odds warnings.

---

## Appendix: Files Reviewed

| File | Lines | Key Findings |
|------|-------|-------------|
| `bot.py` | ~4,500 | Core bot. 5 P0 issues, 14 P1/P2 issues. |
| `services/edge_rating.py` | 251 | 5-factor Edge Rating calculator. Well-implemented. Not wired to bot.py. |
| `renderers/edge_renderer.py` | 154 | Multi-bookmaker tip renderer + odds comparison. Not wired to bot.py. |
| `renderers/telegram_renderer.py` | 196 | Profile, schedule, picks rendering. Working. |
| `renderers/whatsapp_renderer.py` | 152 | Placeholder. Basic rendering done. |
| `renderers/whatsapp_menus.py` | 130 | Menu definitions with compatibility matrix. |
| `CLAUDE.md` | ~400 | Architecture doc. Describes Paystack flow that doesn't exist in code. |

## Appendix: Edge Rating Emoji Discrepancy

The UX spec (WIREFRAMES.md, UX-CONVENTIONS.md) uses the **mining theme**:
- ⛏️🔥 PLATINUM, ⛏️⭐ GOLD, ⛏️🥈 SILVER, ⛏️🥉 BRONZE

The implementation (`edge_renderer.py`) uses **different emojis**:
- ⚡ PLATINUM EDGE, 🥇 Gold Edge, 🥈 Silver Edge, 🥉 Bronze Edge

**Action needed:** Align `edge_renderer.py` with the UX spec. Change `EDGE_EMOJIS` and `EDGE_LABELS` to match the mining theme. Also note the tier thresholds differ slightly:

| Tier | UX Spec | Implementation |
|------|---------|---------------|
| PLATINUM | 85%+ | 85%+ (match) |
| GOLD | 70-84% | 75-84% (mismatch) |
| SILVER | 55-69% | 60-74% (mismatch) |
| BRONZE | 40-54% | 40-59% (mismatch) |

The implementation uses `75` for GOLD and `60` for SILVER, while the UX spec uses `70` and `55`. LeadDev and UX should align on which thresholds to use. Recommend the UX spec values since they create more even distribution.
