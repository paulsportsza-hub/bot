# MzansiEdge — Telegram UX Playbook Audit

> Audited: bot.py (~4,500 lines), renderers/, services/templates.py, scripts/picks_engine.py
> Date: 2026-02-25
> Baseline: 22-section Telegram UX Playbook (production patterns)
> Note: TELEGRAM-UX-PLAYBOOK.md file was referenced but not present on disk. Audit uses the
> 22 canonical Telegram UX sections as described in the Day 6 brief.

---

## Audit Summary

| Rating | Count | Sections |
|--------|-------|----------|
| COMPLIANT | 4 | Parse Mode, Callback Data (partial), Confirmation Dialogs, Error Recovery |
| PARTIAL | 10 | Message Structure, Loading, Numbered Lists, Pagination, Keyboard Layout, Progress, Session Mgmt, Experience Adaptation, Notification Throttle, Affiliate |
| MISSING | 8 | Loading Animation Class, Chunked Text, Keyboard Lifecycle, Callback Conventions, Edge Rating System, Line Movement Display, Stale Odds Warning, HTML Escaping |

---

## Section-by-Section Audit

### 1. Parse Mode & Escaping

**Status: PARTIAL** | Priority: **P0**

**What the playbook requires:**
- Use `ParseMode.HTML` everywhere (never Markdown)
- Escape all user-supplied text with `html.escape()` before embedding in messages
- Never trust raw user input in HTML-formatted messages

**Current state:**
- `ParseMode.HTML` used consistently throughout bot.py (all `reply_text` and `send_message` calls). **COMPLIANT.**
- User input escaping: **MISSING.** No `html.escape()` calls found anywhere in bot.py.
  - `bot.py:530` — `user.first_name` embedded directly in HTML: `f"<b>Welcome back, {user.first_name}!</b>"`
  - `bot.py:553` — Same in onboarding welcome
  - `bot.py:862` — Same in menu handler
  - `bot.py:1854` — Team names from user input displayed without escaping: `f"✅ {m}"` and `f"❌ {u}"`
  - `bot.py:2667` — Hot Tips: `tip['home_team']` and `tip['away_team']` from API (less risky but still external data)
  - Risk: A user with `first_name` containing `<b>` or `<script>` tags could break message formatting or cause parse errors.

**Fix needed:**
```python
from html import escape
# Use escape(user.first_name) everywhere user data appears in HTML messages
```

**Files affected:** bot.py (all handlers using user.first_name, team names, user input text)

---

### 2. Message Structure

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Emoji + bold title as first line
- Blank line after title
- Bullet points use `•` (not `-`)
- Sections separated by blank lines
- Short lines for mobile readability (max ~50 chars per visual line)

**Current state:**
- Emoji + bold titles: **Mostly COMPLIANT.** e.g. `"🔥 <b>Hot Tips</b>"`, `"⚽ <b>Your Games</b>"`, `"📊 <b>Tip Detail</b>"`
- Blank line after title: **PARTIAL.** Some messages use `\n\n` correctly (Hot Tips header), others pack title and content together (help text, some settings).
- Bullet points: **NOT COMPLIANT.** Help text uses `—` dashes, settings uses button labels. No `•` bullets used anywhere.
  - `bot.py:589-609` — Help text uses `—` dashes for commands
  - `content/tip-card-template.md` — Uses `•` correctly in templates but bot.py doesn't implement them
- Section spacing: **PARTIAL.** Onboarding summary has good spacing. Tip cards could use clearer section breaks.
- Line length: **COMPLIANT** in most messages — kept concise for mobile.

**Specific issues:**
- `bot.py:585-609` (HELP_TEXT): Uses `—` instead of `•`, has no blank line after title
- `bot.py:2666-2670` (Hot Tips card): Good structure but missing section breaks between match info and odds
- `renderers/telegram_renderer.py:132-141` (game tips): Uses `  ` indentation for odds — should use `•`

---

### 3. Loading Animations

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Implement a `LoadingAnimation` class that cycles through verb phrases
- Edit the same message to show animation progression
- Use for all operations that take >1 second
- Clean up (delete) loading message when done

**Current state:**
- Loading messages exist: **PARTIAL.**
  - `bot.py:2621-2623` — Hot Tips: sends "🔥 Scanning across all markets..." then deletes. **Good.**
  - `bot.py:2860-2865` — Picks: sends "🔍 {verb} across {n} leagues..." then deletes. **Good.**
  - `bot.py:940` — AI tip: edits message to "🤖 Analysing odds..." **Good (edit-in-place).**
  - `bot.py:3207` — Game tips: edits to "🤖 Analysing {home} vs {away}..." **Good.**
- Loading verbs randomised: `LOADING_VERBS` list with 5 verbs. **Good personality.**
- `LoadingAnimation` class: **MISSING.** No class that cycles through states or edits progressively.
- AI chat "Thinking..." message: **NEVER CLEANED UP.** `bot.py:2789` sends "🤖 Thinking..." but the reply goes to a new message, leaving stale "Thinking..." visible.

**Needed:**
- Implement `LoadingAnimation` helper class that progressively edits a message
- Fix AI chat "Thinking..." cleanup — either edit-in-place or delete before reply
- Standardise loading pattern across all async operations

---

### 4. Numbered Lists + Buttons

**Status: PARTIAL** | Priority: **P0**

**What the playbook requires:**
- List items formatted as `[N] emoji item_text`
- Corresponding inline buttons: `[1] [2] [3] [4] [5]` per row, max 5 per row
- Number in message matches button number exactly
- Buttons trigger drill-down detail views

**Current state:**
- Your Games (all-games view): **PARTIAL.**
  - Message lists items as `1. ⚽ 19:30 Man City vs Arsenal` — uses `N.` not `[N]`
  - Buttons use `[1] ⚽ ARS vs CHE` — full-width per game (one button per row). NOT compact numbered buttons.
  - `bot.py:2269-2292` — list numbering
  - `bot.py:2297-2311` — buttons (full-width, one per row)
- Hot Tips: **NOT COMPLIANT.** Tips sent as separate messages, not as numbered list with buttons.
  - `bot.py:2662-2689` — Individual tip messages in a loop
  - This is the primary UX anti-pattern identified in Day 5 audit.
- Game breakdown buttons: Individual tip outcomes, not numbered. **Acceptable for detail views.**

**Fix needed:**
- Hot Tips: Consolidate into single message with `[1]-[10]` numbered buttons (2 rows of 5)
- Your Games: Change full-width game buttons to compact numbered buttons
- Standardise list format to `[N] emoji text` across all list views

---

### 5. Pagination

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- 5 items per page (optimal for Telegram's message height)
- Header shows position: "Page 1/3 (15 items)"
- `paginate()` reusable function
- Prev/Next buttons with page counters
- Keyboard on last page only (or consistently)

**Current state:**
- Your Games pagination: **Implemented but different from playbook.**
  - `GAMES_PER_PAGE = 10` — playbook recommends 5
  - Header shows count: `"12 games · 🔥 3 with edge"` — but no page position
  - Pagination buttons: `⬅️ Prev | 📄 1/2 | Next ➡️` — **Good.**
  - `bot.py:3134` — `GAMES_PER_PAGE = 10`
- Schedule pagination: 10 per page, same pattern. **Consistent but not 5/page.**
- Hot Tips: **No pagination** (max 5 tips, but should be 10 with pagination at 5/page)
- `paginate()` helper: **MISSING.** Each view reimplements pagination inline.

**Fix needed:**
- Consider reducing to 5 items/page for mobile readability (or keep 10 if Paul prefers density)
- Add page position to headers: `"Your Games (1/3)"`
- Extract reusable `paginate(items, page, per_page)` function
- Add pagination to Hot Tips when expanding to 10 items

---

### 6. Chunked Text

**Status: MISSING** | Priority: **P1**

**What the playbook requires:**
- Max 3500 chars per message (Telegram limit is 4096, leave buffer)
- Split on newline boundaries (never mid-sentence)
- Inline keyboard on last chunk only
- Helper function: `chunk_message(text, max_len=3500) -> list[str]`

**Current state:**
- `_chunk_message()` helper exists: `bot.py:3519-3538` — splits at 4000 chars on newlines. **Exists but:**
  - Limit is 4000, should be 3500 for safety buffer
  - **Never actually used anywhere in bot.py.** It's defined but uncalled.
- No AI response chunking: Claude API can return >4000 chars. If the game analysis or AI chat response exceeds Telegram's limit, it will silently fail or truncate.

**Fix needed:**
- Reduce `_chunk_message` limit to 3500
- Actually use it for AI responses (game tips narrative, AI chat freetext responses)
- Ensure keyboard only on last chunk

---

### 7. Keyboard Management (Lifecycle)

**Status: MISSING** | Priority: **P0**

**What the playbook requires:**
- Track `_last_kb_msg_id` per user/chat
- Delete old inline keyboard message before sending new one
- Prevents "keyboard graveyard" (old buttons scattered through chat)
- Single active keyboard at any time

**Current state:**
- **No keyboard lifecycle tracking.** No `_last_kb_msg_id` pattern.
- Hot Tips is the worst offender: sends 7+ messages each with their own inline keyboard. User's chat fills with stale buttons.
- `/start` and `/menu` for returning users send 2 messages: one with reply keyboard, one with inline keyboard. The inline keyboard message is never tracked or cleaned up.
  - `bot.py:537-542` — Two messages on /start
  - `bot.py:575-580` — Two messages on /menu
- Your Games: Single message, edit-in-place. **Good but no tracking.**
- Settings: Edit-in-place within a single message. **Good.**

**Fix needed:**
- Implement `_last_kb_msg_id` tracking per chat
- Before sending any new inline keyboard, delete (or edit) the previous one
- Critical for Hot Tips refactor: single message with keyboard replaces multi-message spam

---

### 8. Keyboard Layout

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Primary action: full-width button (single button on its own row)
- Secondary actions: 2-column layout
- Back/navigation: alone on last row
- Max 5 buttons per row for numbered buttons

**Current state:**
- Main menu (`kb_main()`): 2-column layout for menu items, settings alone on last row. **Good.**
- Navigation (`kb_nav()`): Back + Main Menu on one row. **Acceptable** but playbook says back alone.
- Settings (`kb_settings()`): Full-width per option + nav last row. **Good.**
- Onboarding sports: 2-column grid for sports. **Good.**
- Your Games game buttons: Full-width per game. **Should be compact numbered if using list+button pattern.**
- Hot Tips tip buttons (per-message): Single Betway button. **Will change with consolidation.**

**Specific issues:**
- `kb_nav()` has Back + Menu on same row — playbook wants Back alone on last row
- Missing: Primary CTA should be full-width above navigation

---

### 9. Confirmation Dialogs

**Status: COMPLIANT** | Priority: N/A

**What the playbook requires:**
- Bold header with warning emoji
- `<code>` entity for specific details
- Numbered consequences list
- Confirm + Cancel buttons (destructive action labelled clearly)

**Current state:**
- Profile reset: **COMPLIANT.**
  - `bot.py:3883-3897` — Warning with bold header, lists what will/won't be deleted, Confirm + Cancel buttons
- Payment verification: Appropriate confirmation flow. **COMPLIANT.**
- No other destructive actions exist that need confirmation.

---

### 10. Progress Updates

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Edit the same message to show progress (don't send new messages)
- Use state emojis: ⏳ (waiting) → 🚀 (in progress) → ✅ (done) / ❌ (failed)
- For multi-step operations, show step counter

**Current state:**
- Game analysis: Edits "🤖 Analysing..." to final result. **Good edit-in-place.**
- AI tip: Edits "🤖 Analysing odds..." to result. **Good.**
- Payment verification: Edits "⏳ Verifying..." to result. **Good.**
- Hot Tips: Deletes loading, sends new messages. **Not edit-in-place.**
- Picks: Deletes loading, sends new messages. **Not edit-in-place.**
- State emojis: Some use ⏳ and ✅ but not consistently. No 🚀 anywhere.

**Fix needed:**
- Standardise progress emoji sequence: ⏳ → 🔍/🤖 → ✅/❌
- Hot Tips refactor should edit loading message into final summary (not delete + send new)

---

### 11. Callback Data Conventions

**Status: PARTIAL** | Priority: **P2**

**What the playbook requires:**
- `nav:` prefix for navigation
- `pager|` prefix with pipe separators for pagination
- `confirm:` prefix for confirmation dialogs
- Consistent delimiter (`:` or `|`)

**Current state:**
- Uses `prefix:action` format consistently. **Good consistency.**
- Navigation: `nav:main`, `menu:home` — two prefixes for same concept. **INCONSISTENT.**
- Pagination: `yg:all:{page}`, `schedule:page:{page}` — embedded in callback, not separate `pager|` prefix. **Different from playbook but functional.**
- Confirmation: `settings:reset:confirm` — uses nested colons, not `confirm:` prefix. **Different from playbook.**
- No `|` delimiters used. All use `:`. **Consistent within codebase, different from playbook.**

**Assessment:** Current convention works but doesn't match playbook's `pager|` and `confirm:` standards. Given the codebase is already consistent internally, this is a P2 polish item — not worth a breaking refactor.

---

### 12. Session Management

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- 30-minute TTL on user session state
- Clear session when user starts unrelated flow
- Don't leak state across interactions

**Current state:**
- `_onboarding_state`: In-memory dict, no TTL. Lives until bot restart or explicit cleanup. **No TTL.**
  - `bot.py:66` — `_onboarding_state: dict[int, dict] = {}`
  - Cleaned on: onboarding completion (`handle_ob_done`) or new `/start`
  - Leak risk: If user abandons onboarding midway, state persists forever in memory
- `_story_state`: Same pattern, no TTL. `bot.py:69`
- `_team_edit_state`: Same. `bot.py:72`
- `_schedule_cache`: Per-user game cache, no TTL. `bot.py:3137`
- `_game_tips_cache`: Per-event tips cache, no TTL. `bot.py:3138`
- `_hot_tips_cache`: Has 15-minute TTL. `bot.py:2534`. **COMPLIANT for this one.**

**Fix needed:**
- Add TTL to `_onboarding_state`, `_story_state`, `_team_edit_state` (30 minutes)
- Add cleanup when user switches flows (e.g., if user is mid-onboarding and taps Hot Tips)
- Consider using `context.user_data` (PTB's built-in per-user storage) instead of module-level dicts

---

### 13. Error Recovery & Empty States

**Status: COMPLIANT** | Priority: N/A

**Current state:** Good error handling throughout:
- No leagues → "Set up your sports" with button
- No games → "No games this week" with alternatives
- No edges → "Market is efficient" (positive reframe)
- API failure → "Try again later" with retry button
- Quota exhausted → "Picks refresh tomorrow" with reassurance
- Every error has a recovery action (button or instruction)

**Only issue:** "Unknown action" fallback (`bot.py:818`) is terse — should be friendlier.

---

### 14. Dual Keyboard Coexistence

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Reply keyboard (persistent/sticky) and inline keyboards are separate systems
- Reply keyboard for top-level navigation (tab bar)
- Inline keyboards for contextual actions within messages
- Never conflict or confuse user about which to tap

**Current state:**
- Reply keyboard: 3x2 grid, persistent. **Good.**
- Inline keyboards: Contextual per message. **Good.**
- Coexistence: Both visible simultaneously. **Good.**
- Issue: `/start` and `/menu` send 2 messages — one for reply keyboard, one for inline. This creates a "double menu" effect.
  - `bot.py:537-542` — sends welcome text with reply keyboard, then "Quick menu:" with inline keyboard
- Onboarding properly hides reply keyboard. **Good.**

---

### 15. Message Editing vs. New Messages

**Status: PARTIAL** | Priority: **P0**

**What the playbook requires:**
- Use `edit_message_text` for state changes within a flow
- Only send new messages for genuinely new content
- Never send multiple messages when one would suffice

**Current state:**
- Onboarding: Edit-in-place throughout. **COMPLIANT.**
- Settings: Edit-in-place. **COMPLIANT.**
- Your Games: Edit-in-place for navigation. **COMPLIANT.**
- Game Breakdown: Edit-in-place. **COMPLIANT.**
- **Hot Tips: Sends 7+ new messages.** **NOT COMPLIANT.** This is the #1 anti-pattern.
- **Legacy Picks: Same issue.** Sends header + individual picks + footer.
- `/start` returning user: 2 new messages. **Should be 1.**
- `/menu`: 2 new messages. **Should be 1.**
- AI chat "Thinking...": New message, reply as another new message. "Thinking..." never cleaned up.

---

### 16. Affiliate Link Handling

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Affiliate links should use URL buttons (not inline text links)
- Never show affiliate links on gated/locked content
- Rotate affiliate partner exposure if multiple
- Track click-through analytics

**Current state:**
- Betway URL buttons: Used correctly as `InlineKeyboardButton(url=...)`. **Good.**
- Fallback when no URL: Uses callback "tip:affiliate_soon" with toast alert. **Good placeholder.**
- Affiliate rotation: **Not implemented.** Betway is exclusive MVP partner. Single bookmaker. **Acceptable for MVP.**
- Click tracking: **Not implemented.** No analytics on affiliate button taps.
- Affiliate on every tip message: Each Hot Tips tip card has a Betway button. **Aggressive but acceptable.**

---

### 17. Experience-Adaptive Content

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Detect user's experience level and adapt content depth
- Newbie: explain everything, small stakes, no jargon
- Casual: brief explanations, moderate stakes
- Experienced: data-dense, formulas, no hand-holding

**Current state:**
- Tip detail view: **COMPLIANT.** Three experience levels implemented:
  - `bot.py:3464-3516` — experienced (Kelly, EV formula, stake sizing)
  - `bot.py:3481-3500` — newbie (R20/R50 examples, full explanation)
  - `bot.py:3502-3516` — casual (R100, suggested stake)
- Hot Tips summary: **NOT adaptive.** Same format for all users.
- Game breakdown narrative: **NOT adaptive.** Same Claude prompt regardless of experience.
- Help text: **NOT adaptive.** Same for all levels.

---

### 18. Notification Throttling

**Status: PARTIAL** | Priority: **P1**

**What the playbook requires:**
- Max 1 unsolicited message per day for casual users
- Respect user's notification preferences
- Track last notification time per user
- Never spam

**Current state:**
- Morning teaser: Runs hourly, checks user's `notification_hour`. **Good scheduling.**
- `daily_picks` preference respected. **Good.**
- No per-user "last notified" tracking. **MISSING.** If the bot restarts at the user's notification hour, they could get a duplicate.
- Pacing rule: Max 1/day is the intent but not enforced in code — no `last_notification_sent_at` field.

---

### 19. Edge Rating System

**Status: MISSING** | Priority: **P1** (new feature)

**What the brief requires:**
- Mining theme: Platinum/Gold/Silver/Bronze with ⛏️ emoji
- Based on confidence/EV combination
- Always show emoji + tier name (never just a number)

**Current state:**
- Confidence shown as percentage + colored dots (🟢🟡🔴). **Different system.**
- No Edge Rating tiers implemented.
- No ⛏️ emoji or mining metaphor.

**This is a new design requirement**, not a compliance gap. See UX-CONVENTIONS.md for the full specification.

---

### 20. Line Movement Display

**Status: MISSING** | Priority: **P2** (new feature)

**What the brief requires:**
- Show odds movement: "Opened 1.90 → Now 2.10 (+10.5%)"
- Alert on sharp money detection
- Push notification format for significant moves

**Current state:**
- No line movement tracking or display anywhere in the codebase.
- Odds are fetched as point-in-time snapshots with 30-minute cache.
- No historical odds storage.

**This requires new infrastructure** (odds history table, movement detection logic) before UX can be implemented.

---

### 21. Stale Odds Warning

**Status: MISSING** | Priority: **P1**

**What the playbook requires:**
- If odds data is older than 30 minutes, show a warning label
- Never present stale odds as current

**Current state:**
- Odds cache TTL is 30 minutes (`scripts/odds_client.py`). **Good cache management.**
- Hot tips cache TTL is 15 minutes. **Good.**
- **No staleness indicator shown to users.** If the cache is 29 minutes old, odds display looks identical to fresh data.
- No "Last updated: X minutes ago" timestamp on any odds display.

**Fix needed:**
- Add "Last updated: X min ago" to odds displays
- If >30 min, add "⚠️ Odds may have changed" warning

---

### 22. Multi-Bookmaker Odds Display

**Status: PARTIAL** | Priority: **P1** (upcoming feature)

**What the brief requires:**
- Display odds from multiple SA bookmakers in a clean format
- SA bookmakers shown first
- Best odds marked with ⭐

**Current state:**
- MVP: Betway-only. Single bookmaker shown.
- `SA_BOOKMAKERS` config has 5 bookmakers (4 dormant). **Ready for expansion.**
- Game breakdown shows Betway odds per outcome. **Single bookmaker format.**
- `find_best_sa_odds()` already finds best across all SA bookmakers internally. **Backend ready.**

**When multi-bookmaker activates:** Need the UX pattern for showing 3-8 bookmakers per outcome cleanly. See WIREFRAMES.md for the designed pattern.

---

## Priority Summary

### P0 — Breaks UX (Fix Before Launch)

1. **HTML Escaping** (Section 1): User input embedded without `html.escape()`. Could break message rendering.
2. **Keyboard Lifecycle** (Section 7): No tracking of active keyboard messages. Hot Tips creates keyboard graveyard.
3. **Hot Tips Multi-Message Spam** (Sections 4, 15): 7 separate messages instead of 1. The core UX problem.
4. **AI Chat "Thinking..." Leak** (Sections 3, 15): Loading message never cleaned up.
5. **Numbered Button Pattern** (Section 4): Hot Tips needs `[1]-[10]` compact buttons. Your Games needs same pattern.

### P1 — Degrades UX (Fix Soon After Launch)

6. Message structure standardisation (Section 2): `•` bullets, consistent spacing
7. Chunked text (Section 6): Long AI responses could exceed Telegram limit
8. Session TTL (Section 12): Abandoned onboarding state leaks memory
9. Stale odds warning (Section 21): Users see cached odds without freshness indicator
10. Pagination helper (Section 5): Extract reusable paginate() function
11. `/start` and `/menu` double messages (Section 14): Consolidate to 1 message

### P2 — Polish (Post-Launch)

12. Callback data convention alignment (Section 11)
13. `LoadingAnimation` class (Section 3)
14. Experience-adaptive Hot Tips (Section 17)
15. Edge Rating system (Section 19) — new feature
16. Line Movement display (Section 20) — new feature
17. Affiliate click tracking (Section 16)
