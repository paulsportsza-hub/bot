# MzansiEdge — Anti-Patterns Checklist

> Version: 1.0
> Date: 2026-02-25 (Day 6)
> Source: 22-section Telegram UX Playbook + MzansiEdge-specific patterns
> Usage: Every PR touching bot UX must pass this checklist. If any item is violated, the PR needs a fix or a documented exception.

---

## Part A: Telegram UX Playbook Anti-Patterns (22 Sections)

These are the canonical "never do this" rules derived from each playbook section.

### 1. Parse Mode & Escaping

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-01 | Embedding `user.first_name` or any user input directly in HTML without `html.escape()` | User with `<b>` in name breaks message rendering; potential injection vector | Always `html.escape(value)` before embedding in `ParseMode.HTML` messages |
| AP-02 | Using `ParseMode.MARKDOWN` or `ParseMode.MARKDOWN_V2` | Markdown escaping is fragile — `_`, `*`, `[` in team names break parsing | Use `ParseMode.HTML` exclusively |

### 2. Message Structure

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-03 | No emoji + bold title as the first line | Users can't scan what the message is about at a glance | Start every message with `emoji <b>Title</b>` |
| AP-04 | Using `-` or `—` for bullet points | Inconsistent with Telegram visual conventions | Use `•` for all bullet lists |
| AP-05 | Wall of text without section breaks | Unreadable on mobile — users scroll past it | Separate sections with blank lines, use bold headers per section |

### 3. Loading Animations

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-06 | Sending a loading message and never deleting/editing it | "Thinking..." sits permanently in chat | Always edit-in-place or delete the loading message when the result arrives |
| AP-07 | Sending the result as a new message while the loading message stays | User sees both the "loading" and "result" — confusing | Edit the loading message into the result (`edit_message_text`) |
| AP-08 | No loading feedback for operations >1 second | User thinks the bot is broken | Send an italic loading message immediately, then edit it when done |

### 4. Numbered Lists + Buttons

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-09 | Sending each list item as a separate message | Floods chat, creates keyboard graveyard, impossible to scan | Single message with numbered list + compact `[1] [2] [3] [4] [5]` buttons |
| AP-10 | Full-width buttons for every list item when compact numbered buttons would work | Keyboard is taller than the message content; user can't see the list | Use compact numbered buttons in rows of 5, reserve full-width for CTAs |
| AP-11 | Button number doesn't match the item number in the message | "Tap 3" highlights the wrong match | Number in message text must exactly match the button number |

### 5. Pagination

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-12 | Showing all items on one page regardless of count | Long messages get truncated or become unreadable on mobile | 5 items per page with Prev/Next buttons |
| AP-13 | No page position indicator | User doesn't know how much content exists | Show `Page 1/3` in header |
| AP-14 | Reimplementing pagination logic in every handler | Bugs, inconsistency, maintenance burden | Single `paginate(items, page, per_page)` helper |

### 6. Chunked Text

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-15 | Sending messages that could exceed 4096 characters | Telegram silently drops the message — user sees nothing | Use `chunk_message(text, max_len=3500)` for all AI-generated content |
| AP-16 | Splitting a message mid-sentence | Confusing read | Split on `\n` boundaries only |
| AP-17 | Putting inline keyboard on every chunk | Multiple keyboards = confusion about which to tap | Keyboard on the last chunk only |

### 7. Keyboard Lifecycle

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-18 | Not tracking which message has the active inline keyboard | Old keyboards pile up in chat ("keyboard graveyard") | Track `_last_kb_msg_id` per chat; delete/edit old keyboard before sending new one |
| AP-19 | Sending 2+ messages with separate inline keyboards at the same time | User doesn't know which keyboard is "current" | One active inline keyboard message at a time |

### 8. Keyboard Layout

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-20 | Navigation button on the same row as action buttons | User accidentally taps Back instead of the action | Navigation (Back, Menu) alone on the last row |
| AP-21 | More than 5 buttons per row on numbered lists | Buttons become too narrow to tap on mobile | Max 5 compact buttons per row |
| AP-22 | Primary CTA (e.g., "Bet on Betway") in a 2-column layout | Reduces visual prominence of the main action | Primary CTA full-width, alone on its row |

### 9. Confirmation Dialogs

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-23 | Destructive action with no confirmation step | User accidentally resets profile or cancels subscription | Bold warning + numbered consequences + Confirm/Cancel buttons |
| AP-24 | "Are you sure?" without explaining what will happen | User can't make an informed decision | List specific consequences: "This will delete X, Y, Z" |

### 10. Progress Updates

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-25 | Deleting a loading message and sending the result as a new message | Chat jumps, notification noise, breaks message flow | Edit the loading message in-place with the result |
| AP-26 | No progress indication for multi-step operations | User waits in silence, thinks bot crashed | Show step counter: "Step 2/3: Analysing odds..." |

### 11. Callback Data Conventions

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-27 | Using multiple delimiter styles (`:` and `|` and `-`) in callbacks | Parsing bugs, inconsistency, harder to debug | Pick one convention and stick to it (MzansiEdge uses `:`) |
| AP-28 | Callback data exceeding 64 bytes | Telegram silently rejects the button — it won't work | Keep callbacks short: `hot:detail:3` not `hot_tips:show_detail:match_id_12345` |

### 12. Session Management

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-29 | In-memory state dicts without TTL | Memory leak — abandoned sessions never expire; OOM on high traffic | 30-minute TTL on all user session state |
| AP-30 | User switching flows without old state being cleared | State from flow A leaks into flow B — unpredictable behaviour | Clear state when user enters a new flow |

### 13. Error Recovery & Empty States

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-31 | Showing a raw error message ("Error: 500 Internal Server Error") | Scares users, exposes internals | Friendly message: "Something went wrong. Tap below to try again." |
| AP-32 | Error state with no recovery action | User is stuck, can only type /start | Every error message must have a button: Retry, Back, or Menu |

### 14. Dual Keyboard Coexistence

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-33 | Sending 2 messages on /start — one for reply keyboard, one for inline | "Double menu" confusion; user sees two keyboards and two messages | Single message with reply keyboard + inline keyboard |
| AP-34 | Hiding the reply keyboard during normal flows | User loses top-level navigation | Reply keyboard always visible (except during onboarding text input) |

### 15. Message Editing vs. New Messages

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-35 | Sending a new message for every state transition in a flow | Chat floods with bot messages; user can't find the current state | `edit_message_text` for state transitions within a flow |
| AP-36 | Sending a new message when the user taps a button on an existing message | Two messages for one interaction — confusing | Edit the message the button was on |

### 16. Affiliate Link Handling

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-37 | Affiliate link as inline text (`<a href="...">click here</a>`) | Easy to miss, doesn't look like a button, poor analytics | Always use URL buttons: `InlineKeyboardButton(text="...", url="...")` |
| AP-38 | Showing affiliate buttons on gated/locked content | User taps affiliate, lands on the site, but can't use the tip — frustrating | Affiliate buttons only on fully visible tip content |

### 17. Experience-Adaptive Content

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-39 | Using jargon like "Kelly criterion" or "EV" for newbie users | Confusing — user doesn't understand the recommendation | Adapt language to experience level: "suggested bet: R50" for newbies |
| AP-40 | Showing the same content depth for all experience levels | Experts want data; newbies want guidance — one-size disappoints both | Three tiers: newbie (explain everything), casual (brief), experienced (data-dense) |

### 18. Notification Throttling

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-41 | Sending more than 1 unsolicited message per day to a casual user | Feels spammy — user mutes or blocks the bot | Max 1 push notification per user per day (morning teaser OR line alert, not both) |
| AP-42 | No `last_notification_sent_at` tracking | Duplicates on bot restart; can't enforce pacing | Track per-user last notification timestamp in DB |

### 19. Edge Rating System

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-43 | Showing a raw confidence percentage without the tier name | "74%" means nothing without context | Always show `⛏️⭐ GOLD (74%)` — emoji + tier + percentage |
| AP-44 | Displaying tips with confidence below 40% | No edge — user is betting blind | Filter out all tips below 40% (BRONZE floor) |

### 20. Line Movement Display

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-45 | Showing a new odds value without the previous value | User can't see the direction of movement | Always show `old → new (+X%)` format |
| AP-46 | Alerting on every minor odds fluctuation (<5%) | Noise — meaningless market jitter | Only alert when movement >5% from opening line |

### 21. Stale Odds Warning

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-47 | Presenting 30-minute-old odds as "current" without any indicator | User makes betting decisions on stale data | Show "Updated X min ago" on all odds displays |
| AP-48 | Not warning when odds are likely stale (>30 min) | Misleading | Add `⚠️ Odds may have changed` when data age >30 minutes |

### 22. Multi-Bookmaker Odds Display

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| AP-49 | Showing international-only bookmakers (Pinnacle, Betfair) to users | SA users can't bet there — useless information | SA bookmakers only: Betway, Hollywoodbets, Sportingbet, etc. |
| AP-50 | Not highlighting the best odds when comparing | User has to mentally scan 4 numbers per outcome | Mark best odds with ⭐ on the same line |

---

## Part B: MzansiEdge-Specific Anti-Patterns

These are unique to MzansiEdge's brand, market, and product design.

### B1. South African Culture & Currency

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| ME-01 | Using `$` or `USD` for money amounts | MzansiEdge is SA-only — Rands only | Always `R49`, `R100`, `R210` — never `$` or `USD` |
| ME-02 | Using "howzit", "bru", "boet", "lekker bru" | Tone Guide says confident, not cringeworthy — forced slang alienates | SA English: "lekker" (sparingly), "sharp" are OK; "bru", "boet", "howzit" are banned |
| ME-03 | Showing leagues/sports not relevant to SA users | Users don't care about J-League or Slovenian 2nd division | Focus: PSL, EPL, La Liga, UCL, URC, Super Rugby, Proteas, Springboks |

### B2. Betting Responsibility

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| ME-04 | Saying "guaranteed win" or "can't lose" or "sure bet" | Illegal under SA gambling advertising law; irresponsible | "High conviction", "strong edge", "value bet" — never guarantee outcomes |
| ME-05 | Suggesting stakes without bankroll context | R500 bet is fine for some, reckless for others | Kelly sizing or percentage-of-bankroll framing; "Suggested: X% of your bankroll" |
| ME-06 | No responsible gambling notice anywhere | Regulatory risk | Footer or settings: "Gambling involves risk. Only bet what you can afford to lose." |

### B3. Brand & Product

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| ME-07 | Showing the tip without bookmaker attribution | User doesn't know where to bet; no affiliate revenue | Every tip must show at least one SA bookmaker name + odds |
| ME-08 | Showing a tip below the BRONZE floor (40% confidence) | No edge exists — violates the product promise | Never display tips with Edge Rating <40% |
| ME-09 | More than 10 tips in Hot Tips | Information overload — user can't choose | Max 10 tips, sorted by confidence, paginated 5/page |
| ME-10 | Showing tips from the same match in multiple outcomes without flagging | User might bet both "Arsenal Win" and "Draw" thinking they're independent | If showing multiple outcomes from one match, add "(same match)" label |

### B4. Subscriptions & Monetisation

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| ME-11 | Upselling on every interaction | Annoying — user will mute the bot | Soft nudge after 3rd tip view; hard gate only on premium features |
| ME-12 | Showing premium content partially then locking it | "Here's the edge... pay to see the verdict" — bait and switch | Show either full free content or clear paywall upfront; never half-reveal |
| ME-13 | Not showing subscription status in settings | User doesn't know if they're Free or Premium | Settings must show: Plan name, status, renewal date |

### B5. Affiliate Links

| # | Anti-Pattern | Why It's Bad | Correct Pattern |
|---|-------------|-------------|-----------------|
| ME-14 | Only showing one bookmaker when better odds exist elsewhere | User gets worse odds; trust erodes when they discover better prices | When multi-bookmaker is live, always show best odds first with ⭐ |
| ME-15 | Not rotating affiliate button placement | One bookmaker always gets prime position; others get no clicks | Rotate which bookmaker gets the primary CTA button position |
| ME-16 | Affiliate link without "Bet on [Name]" label | User doesn't know where the link goes | Always label: "📲 Bet on Betway →" not just "📲 Bet Now" |

---

## Quick Reference: Top 10 Most Common Anti-Patterns in MzansiEdge

For code reviewers — these are the ones most likely to appear in PRs:

1. **AP-09** — Sending list items as separate messages (Hot Tips)
2. **AP-01** — Missing `html.escape()` on user input
3. **AP-06** — Loading message never cleaned up
4. **AP-18** — No keyboard lifecycle tracking
5. **AP-35** — New message instead of edit-in-place
6. **AP-33** — Double message on /start and /menu
7. **AP-29** — In-memory state without TTL
8. **ME-01** — Using `$` instead of `R`
9. **AP-47** — No freshness indicator on odds
10. **ME-04** — Guarantee language in tips

---

## Checklist for PR Review

Before merging any bot UX change, verify:

- [ ] All user input is `html.escape()`'d before embedding in HTML messages
- [ ] No new messages sent where `edit_message_text` would suffice
- [ ] Loading messages are cleaned up (edited or deleted) when the result arrives
- [ ] Numbered lists use compact `[1]-[5]` buttons, not full-width per item
- [ ] Currency is Rand (`R`), never dollars
- [ ] No guarantee language ("sure bet", "can't lose")
- [ ] Odds show bookmaker name
- [ ] Tips below 40% Edge Rating are filtered out
- [ ] Inline keyboard lifecycle tracked — old keyboard removed before new one sent
- [ ] AI responses use `chunk_message()` if they could exceed 3500 chars
