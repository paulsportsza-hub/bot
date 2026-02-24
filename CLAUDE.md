# MzansiEdge — CLAUDE.md

## Overview
AI-powered sports betting Telegram bot for South Africa. Uses python-telegram-bot v20+ (PTB), Claude API for AI tips, The Odds API for live odds, and async SQLAlchemy for persistence.

## Architecture

```
bot.py              ← Main bot: handlers, onboarding, picks, callback routing (Telegram-specific)
config.py           ← Environment config, sport/league definitions, TOP_TEAMS, aliases, risk profiles, SA_BOOKMAKERS (dict-of-dicts), LEAGUE_EXAMPLES, TEAM_ABBREVIATIONS
db.py               ← Async SQLAlchemy models & helpers (User, GameSubscription, WhatsApp columns)
services/
  __init__.py       ← Service layer init
  user_service.py   ← Platform-agnostic user logic: archetype classification, profile data, onboarding persistence
  schedule_service.py ← Platform-agnostic schedule: event fetching, date grouping, game tips data
  picks_service.py  ← Platform-agnostic picks: orchestrates picks pipeline, returns structured data
  templates.py      ← Message template registry: all user-facing strings with telegram/whatsapp variants
renderers/
  __init__.py       ← Renderers init
  telegram_renderer.py  ← Telegram HTML rendering: profile, schedule, picks, tips
  whatsapp_renderer.py  ← WhatsApp plain text rendering (placeholder for future integration)
  whatsapp_menus.py     ← WhatsApp 3-button menu definitions + Telegram keyboard audit
scripts/
  odds_client.py    ← The Odds API client, EV calculation, value bet scanning, odds caching, find_best_sa_odds()
  picks_engine.py   ← Picks pipeline: fetch → EV calc (SA-only odds) → filter → rank → format pick cards
  sports_data.py    ← Sports data service: Odds API fetch, file caching, curated lists, thefuzz fuzzy matching, events fetch
  telegraph_guides.py ← Telegra.ph betting guide publisher for SA bookmakers
  live_scores.py    ← Live scores polling service: fetch scores, detect changes, notify subscribers
tests/
  conftest.py       ← Pytest fixtures (mock bot, in-memory DB)
  test_config.py    ← Sport categories, leagues, fav types, aliases, risk profiles, SPORT_DISPLAY, SA_PRIORITY_GROUPS
  test_sports_data.py ← Curated lists, aliases, caching, fuzzy matching, get_top_teams
  test_archetype.py   ← classify_archetype logic, archetype DB columns
  e2e_telegram.py     ← Playwright E2E tests against live bot on Telegram Web
save_telegram_session.py ← One-time script to save Telegram Web login state
scripts/
  setup_e2e.sh        ← Install system deps for Playwright Chromium
  test_db.py        ← User CRUD, sport prefs, bet creation tests
  test_odds_client.py ← best_odds, format_odds (mocked HTTP)
  test_bot_handlers.py ← /start, /menu, /help handler tests
  test_onboarding.py   ← Full onboarding quiz state machine, fuzzy matching, edit flow
  test_picks.py        ← EV calc, Kelly stake, value bet scanning, pick cards, /admin
  test_day1.py         ← Experience onboarding, persistent menu, adapted pick cards, profile reset
```

## Sport Categories & Leagues

Sports are organised as **categories** with sub-leagues via `config.SPORTS` (list of `SportDef`).

### SportDef dataclass
```python
@dataclass
class SportDef:
    key: str          # "soccer", "rugby", etc.
    label: str        # display name
    emoji: str
    fav_type: str     # "team" / "player" / "fighter" / "driver" / "skip"
    leagues: list[LeagueDef]
```

### LeagueDef dataclass
```python
@dataclass
class LeagueDef:
    key: str          # "epl", "nba", etc.
    label: str        # display name
    api_key: str | None  # The Odds API sport key (None if not available)
```

### 11 Sport Categories
| Category | fav_type | Leagues |
|----------|----------|---------|
| soccer | team | PSL, EPL, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, MLS |
| rugby | team | URC, Super Rugby, Currie Cup, Six Nations, Rugby Championship, RWC |
| cricket | team | CSA/SA20, Test Matches, IPL, Big Bash, T20 World Cup |
| tennis | player | ATP Tour, WTA Tour, Grand Slams |
| boxing | fighter | Major Bouts |
| mma | fighter | UFC Events |
| basketball | team | NBA, EuroLeague |
| american_football | team | NFL |
| golf | player | PGA Tour, DP World Tour, Majors |
| motorsport | driver | Formula 1, MotoGP |
| horse_racing | skip | SA Horse Racing |

### Lookup maps (auto-generated from SPORTS)
- `ALL_SPORTS` — category key → SportDef
- `ALL_LEAGUES` — league key → LeagueDef
- `LEAGUE_SPORT` — league key → category key
- `SPORTS_MAP` — league key → api_key (only leagues with API keys)

### TOP_TEAMS dict
`config.TOP_TEAMS[league_key]` → list of top teams/players for that league. Used for multi-select buttons in onboarding favourites step. ~32 league keys.

### TEAM_ALIASES dict
`config.TEAM_ALIASES[lowercase_alias]` → canonical name. ~113+ aliases. Used for fuzzy matching during manual favourite input. Covers EPL nicknames (gunners, red devils, sky blues, reds, toffees), SA PSL slang (glamour boys, usuthu, masandawana), La Liga (los blancos, blaugrana), Rugby (bokke, les bleus), Tennis (rafa, djoker), Boxing (canelo, tank, fury), Cricket (proteas, blackcaps, windies), MMA (poatan, stillknocks).

### LEAGUE_EXAMPLES dict
`config.LEAGUE_EXAMPLES[league_key]` → example string for team input prompts. ~35 entries (e.g. `"epl": "e.g. Arsenal, Liverpool, Man City"`). Used in `_show_next_team_prompt()` during onboarding and settings team editing to show league-specific placeholder text.

### TEAM_ABBREVIATIONS dict
`config.TEAM_ABBREVIATIONS[team_name]` → short abbreviation. ~60 entries (e.g. `"Arsenal": "ARS"`, `"Kaizer Chiefs": "KC"`, `"Real Madrid": "RMA"`). Used for compact button display in schedule view.

### abbreviate_team()
`config.abbreviate_team(name, max_len=3)` → abbreviation from `TEAM_ABBREVIATIONS` dict with fallback to first 3 chars uppercased.

### fav_type helpers
- `config.fav_label(sport)` → "favourite team" / "favourite player" / "favourite fighter" / "favourite driver or team"
- `config.fav_label_plural(sport)` → plural form

### SPORT_DISPLAY dict (Odds API group mapping)
`config.SPORT_DISPLAY[group]` → `{"emoji": "⚽", "entity": "team", "entities": "teams"}`. Maps Odds API group names (Soccer, Tennis, Boxing, etc.) to display config. 12 groups.

### SA_PRIORITY_GROUPS list
Ordered SA-first display: Soccer → Rugby Union → Cricket → Boxing → MMA → Tennis → Golf → Basketball → ...

### Display helpers
- `config.get_sport_emoji(group)` → emoji for Odds API group (fallback: 🏅)
- `config.get_entity_label(group, plural=False)` → "team"/"player"/"fighter" (fallback: "team")
- `config.ODDS_API_BASE` → alias for `ODDS_BASE_URL`

## Callback Data Pattern
All inline keyboard callbacks use `prefix:action` format:
- `sport:{league_key}` — View odds for a league
- `ai:{category_key}` — AI tip for a sport category
- `menu:home` — Main menu
- `picks:today` / `picks:go` — Today's value bet picks
- `ob_exp:experienced` / `ob_exp:casual` / `ob_exp:newbie` — Experience level
- `ob_sport:{category_key}` — Toggle sport in onboarding
- `ob_nav:sports_done` / `ob_nav:back_sports` / `ob_nav:league_done:{key}` — Navigation
- `ob_league:{sport_key}:{league_key}` — Toggle league
- `ob_fav:{sport_key}:{index}` — Toggle favourite team/player
- `ob_fav_manual:{sport_key}` — Switch to manual input mode
- `ob_fav_done:{sport_key}` — Done with favourites for this sport
- `ob_fav_suggest:{sport_key}:{index}` — Accept fuzzy match suggestion
- `ob_fav_back:{sport_key}` — Back from manual to button grid
- `ob_edit:sports` / `ob_edit:risk` / `ob_edit:sport:{key}` — Edit from summary
- `ob_summary:show` — Return to summary
- `ob_risk:moderate` — Select risk profile
- `ob_bankroll:R1000` / `ob_bankroll:skip` / `ob_bankroll:custom` — Bankroll selection
- `ob_notify:18` — Select 6 PM notifications
- `ob_done:finish` — Complete onboarding
- `ob_restart:go` — Restart onboarding after profile reset
- `bets:active` / `bets:history` — My Bets sub-menu
- `teams:view` / `teams:edit` — My Teams sub-menu
- `teams:edit_league:{sport_key}:{league_key}` — Enter text input for team editing
- `stats:overview` / `stats:leaderboard` — Stats sub-menu
- `affiliate:compare` / `affiliate:sa` / `affiliate:intl` — Bookmakers sub-menu
- `settings:home` / `settings:risk` / `settings:notify` / `settings:sports` / `settings:reset` / `settings:reset:confirm` — Settings sub-menu
- `settings:story` / `settings:toggle_notify:{key}` — Notification preferences in settings
- `settings:bankroll` / `settings:set_bankroll:{amount}` — Bankroll management in settings
- `nav:main` — Navigate to main menu (alias for `menu:home`)
- `nav:schedule` — Navigate to schedule view
- `schedule:tips:{event_id}` — Get AI tips for a specific game
- `tip:detail:{event_id}:{index}` — View detailed tip analysis
- `subscribe:{event_id}` — Subscribe to live score updates for a game
- `unsubscribe:{event_id}` — Unsubscribe from live score updates
- `story:start` / `story:pref:{key}:{yes|no}` — Betting story notification quiz
- `ob_fav_retry:{sport_key}` — Re-prompt for team text input

## Picks / Value Bet Flow
1. User taps "Today's Picks" button or sends `/picks`
2. `_do_picks_flow(chat_id, bot, user_id)` sends loading message with randomised verb
3. Loads user's risk profile + preferred leagues + bankroll from DB
4. Calls `picks_engine.get_picks_for_user(league_keys, risk_profile, max_picks=10, bankroll=user_bankroll)`
5. Engine fetches cached odds per league via `odds_client.fetch_odds_cached()`
6. For each event, estimates sharp probabilities (Pinnacle/Betfair lines preferred, fallback to vig-removed consensus)
7. Uses SA-only bookmaker odds for EV calculation and display (via `_best_sa_for_outcome()`)
8. Computes EV% for each outcome: `(sa_best_odds × fair_prob - 1) × 100`
9. Skips picks where no SA bookmaker offers the market
10. Filters to positive EV above profile's `min_ev` threshold
11. Computes Kelly criterion stake, capped at `max_stake_pct` of user's bankroll (default R1000, min R10)
12. Ranks by EV descending, returns top `max_picks` as structured dicts
13. Bot formats each pick via `picks_engine.format_pick_card(pick, index, experience)` and sends as individual messages
14. Pick cards show: match, outcome, best SA odds@bookmaker (.co.za name), EV%, confidence, stake→return

### Risk Profile Thresholds
| Profile      | min_ev | Kelly fraction | Max stake % |
|-------------|--------|----------------|-------------|
| Conservative | 5%     | 0.25           | 2%          |
| Moderate     | 3%     | 0.50           | 5%          |
| Aggressive   | 1%     | 1.00           | 10%         |

### SA Bookmaker Whitelist (5 books, .co.za display names)
`config.SA_BOOKMAKERS` is a `dict[str, dict]` mapping API key → bookmaker config:
```python
SA_BOOKMAKERS = {
    "betway": {"display_name": "Betway.co.za", "short_name": "Betway", "guide_url": "", "affiliate_base_url": ""},
    "sportingbet": {"display_name": "SportingBet.co.za", ...},
    "10bet": {"display_name": "10Bet.co.za", ...},
    "playabets": {"display_name": "PlayaBets.co.za", ...},
    "supabets": {"display_name": "SupaBets.co.za", ...},
}
```
- `config.sa_display_name(bk_key)` → returns `.co.za` display name for a bookmaker key
- No 🇿🇦 flags on individual bookmaker names (flag only used in branding/welcome messages)

Sharp bookmakers (Pinnacle, Betfair, etc.) are kept for internal probability estimation only — never shown to users.

### SA Odds Functions
- `odds_client.find_best_sa_odds(event, market)` → list of `OddsEntry` filtered to SA bookmakers only
- `picks_engine._best_sa_for_outcome(bookmakers, outcome, market)` → best odds from SA-whitelisted bookmakers for user-facing display

## Admin Commands
- `/admin` — Dashboard showing Odds API quota (requests used/remaining), total users, onboarded users
- `/settings` — User preferences (risk profile, notifications, sports, bankroll, profile reset)
- `/stats` — Legacy stats command (user count, tip results)

## Onboarding Quiz Flow (8 steps)
1. **Experience level** — Experienced / Casual / Newbie
2. **Sports selection** — Category-based grid (Soccer, Rugby, Cricket, Tennis, Boxing, MMA, Basketball, American Football, Golf, Motorsport, Horse Racing)
3. **League selection** — Per selected sport, toggle leagues. **Single-league sports auto-select** (e.g. NFL, UFC).
4. **Favourites** — Text-based input per league. User types comma-separated team/player names with fuzzy matching. Max 5 per league. Horse racing skipped (fav_type="skip"). Sport-appropriate language (team/player/fighter/driver). Queue-based: iterates `_fav_league_queue` of `(sport_key, league_key)` pairs. League-specific examples from `config.LEAGUE_EXAMPLES`.
5. **Risk profile** — Conservative / Moderate / Aggressive
6. **Weekly bankroll** — Preset buttons (R500, R1000, R2000, R5000) + "Not sure yet" skip + "Custom amount" text input. Saved to `User.bankroll`. Used for personalised Kelly stake sizing.
7. **Notification time** — 7 AM / 12 PM / 6 PM / 9 PM
8. **Summary** — Clean profile display with abbreviated league names, league-prefixed teams, bankroll display, edit buttons: "Edit Sports & Favourites" and "Edit Risk & Notifications". Confirm with "Let's go!"

### Favourites data structure
`ob["favourites"]` is a dict-of-dicts: `{sport_key: {league_key: [team_names...]}}`. Saved to DB as one `UserSportPref` row per team per league.

### Post-onboarding: Welcome message + Betting Story quiz
All experience levels get the same welcome message with a CTA to "Set Up My Story" (notification preferences quiz) or "Skip for Now". The story quiz walks through 6 notification types (daily_picks, game_day_alerts, weekly_recap, edu_tips, market_movers, live_scores) with Yes/No for each, saved as JSON in `User.notification_prefs`.

### Archetype classification (on onboarding completion)
`services.user_service.classify_archetype(experience, risk, num_sports)` → `(archetype, engagement_score)`:
- **complete_newbie**: experience="newbie" → score 3.0
- **eager_bettor**: experienced + aggressive/moderate → score 8-10
- **casual_fan**: everyone else → score 5-7

Saved to `User.archetype` and `User.engagement_score` via `db.update_user_archetype()`.

### Fuzzy matching (text-based team input)
Two fuzzy matching systems:
1. **bot.py `_handle_team_text_input()`**: Processes comma-separated team names. Pipeline: alias lookup (sports_data.ALIASES + config.TEAM_ALIASES) → `difflib.get_close_matches` against `config.TOP_TEAMS[league]` then all alias targets. Shows matched/unmatched results with Continue/Try Again buttons.
2. **scripts/sports_data.py**: `thefuzz` (Levenshtein) against dynamic/curated lists. Pipeline: exact → alias → fuzzy → substring. Returns top 3 with confidence scores.

State tracked in `bot._onboarding_state[user_id]` dict with `_team_input_sport`, `_team_input_league`, `_fav_league_queue` keys.

## Profile Reset
Settings → "🔄 Reset Profile" → warning screen → "Yes, reset everything" → clears all prefs, risk, experience, bankroll, onboarding_done in DB → redirects to onboarding. Betting history/stats NOT deleted.

## DB Models
- `User` — id, username, first_name, risk_profile, notification_hour, onboarding_done, experience_level, education_stage, archetype, engagement_score, notification_prefs (JSON), bankroll (float), source, fb_click_id, fb_ad_id, whatsapp_phone (str), preferred_platform (str: "telegram"|"whatsapp")
- `UserSportPref` — user_id, sport_key, league, team_name
- `Tip` — sport, match, prediction, odds, result
- `Bet` — user_id, tip_id, stake
- `GameSubscription` — user_id, event_id, sport_key, home_team, away_team, commence_time, is_active, created_at

### Key DB helpers
- `reset_user_profile(user_id)` — Wipe all user preferences (incl. archetype/engagement/bankroll) but keep account + history
- `clear_user_sport_prefs(user_id)` — Delete all sport prefs for a user
- `clear_user_league_teams(user_id, sport_key, league_key)` — Delete team prefs for a specific league while keeping the league pref itself
- `update_user_archetype(user_id, archetype, engagement_score)` — Set archetype classification
- `update_user_bankroll(user_id, bankroll)` — Set weekly bankroll in ZAR
- `update_user_whatsapp(user_id, phone, platform)` — Set WhatsApp phone and preferred platform
- `get_onboarded_count()` — Count of users who completed onboarding
- `get_notification_prefs(user)` — Parse JSON notification prefs with defaults (daily_picks, game_day_alerts, weekly_recap, edu_tips, market_movers, bankroll_updates, live_scores)
- `update_notification_prefs(user_id, prefs)` — Save notification preferences as JSON
- `subscribe_to_game(user_id, event_id, ...)` — Subscribe to live score updates (deduplicates)
- `unsubscribe_from_game(user_id, event_id)` — Unsubscribe from a game
- `get_user_subscriptions(user_id)` — Get all active subscriptions
- `get_subscribers_for_event(event_id)` — Get all subscribers for an event
- `deactivate_subscriptions_for_event(event_id)` — Deactivate all subs for a completed event
- `_migrate_columns()` — Auto-add new columns to existing SQLite databases on startup

### Picks Engine (`scripts/picks_engine.py`)
| Function | Purpose |
|----------|---------|
| `get_picks_for_user(league_keys, risk_profile, max_picks, bankroll)` | Full pipeline: fetch cached odds → sharp prob estimation → SA-only EV calc → filter → rank |
| `format_pick_card(pick, index, experience)` | Experience-aware pick card formatting (experienced/casual/newbie) |
| `_best_sa_for_outcome(bookmakers, outcome, market)` | Find best odds from SA-whitelisted bookmakers only |

Returns dict: `{ok, picks, total_scanned, total_events, total_markets, quota_remaining, errors}`

Each pick dict contains: `event_id, sport_key, home_team, away_team, commence_time, market, outcome, odds, bookmaker, bookmaker_key, is_sa_bookmaker, ev, confidence, sharp_prob, stake, potential_return, profit, all_odds, confidence_label`

### Odds Caching (`scripts/odds_client.py`)
- File-based JSON cache in `data/odds_cache/` with 30-minute TTL
- `fetch_odds_cached(sport_key, regions, markets, odds_format)` → `{ok, data, error}`
- Cache key format: `odds_{sport_key}_{markets}.json`
- Handles quota exhaustion gracefully (returns error dict)
- Keeps API usage within 500 requests/month free tier
- `find_best_sa_odds(event, market)` → list of `OddsEntry` filtered to SA bookmakers only

### Sharp Bookmaker Probability
Engine prefers sharp book lines for "true" probability estimation:
- **Sharp books**: Pinnacle (`pinnacle`), Betfair Exchange (`betfair_ex_eu`), Matchbook (`matchbook`)
- **Fallback**: Vig-removed consensus from all bookmakers (same as `fair_probabilities()`)
- Sharp lines are devigged to sum to 1.0 before EV calculation
- Sharp books are used for probability only; user-facing odds come from SA bookmakers only

### Sports Data Service (`scripts/sports_data.py`)
- **File caching**: JSON files in `data/sports_cache/` with configurable TTL (24h sports, 12h teams)
- `fetch_available_sports()` → grouped dict from Odds API `/sports`
- `fetch_teams_for_sport(sport_key)` → team list from Odds API events
- `get_top_teams_for_sport(group, sport_key, limit)` → API first, curated fallback
- `CURATED_LISTS` — ~15 sport keys with fallback team/player lists
- `ALIASES` — ~120+ lowercase nickname → canonical name mappings (incl. EPL full squads, SA PSL slang, boxing, MMA, rugby, cricket)
- `fuzzy_match_team(input, known_names)` → top 3 matches with confidence scores
- `fetch_events_for_league(league_key)` → upcoming events from Odds API `/events` endpoint (free, 2hr cache)

## Persistent Reply Keyboard (Sticky Keyboard)
Always-visible bottom keyboard using `ReplyKeyboardMarkup` with `is_persistent=True`.

```
🎯 Picks | 📅 Schedule | 🔴 Live
📊 Stats | ⚙️ Settings  | ❓ Help
```

- `get_main_keyboard()` — returns the 2×3 `ReplyKeyboardMarkup`
- `handle_keyboard_tap()` — `MessageHandler` with `filters.Regex` that routes taps to existing handlers
- Sent after onboarding completes (in `handle_ob_done`)
- Sent with `/start` for returning users and `/menu`
- Hidden during onboarding with `ReplyKeyboardRemove()`
- Coexists with inline keyboards (`InlineKeyboardMarkup`) — both visible simultaneously
- Handler registered BEFORE `freetext_handler` in `main()` (order matters in PTB)

### Keyboard routes
| Button | Handler |
|--------|---------|
| 🎯 Picks | `_do_picks_flow()` |
| 📅 Schedule | `_build_schedule()` |
| 🔴 Live | `_show_live_games()` — shows active game subscriptions |
| 📊 Stats | `_show_stats_overview()` — user stats (archetype, engagement, bankroll) |
| ⚙️ Settings | `kb_settings()` inline menu |
| ❓ Help | `HELP_TEXT` with `kb_nav()` |

## Inline Menu System
Main menu: `kb_main()` → Daily Briefing | My Bets | My Teams | Stats | Schedule | Bookmakers | Settings

Sub-menus: `kb_bets()`, `kb_teams()`, `kb_stats()`, `kb_bookmakers()`, `kb_settings()`
Every sub-screen has "↩️ Back" + "🏠 Main Menu" via `kb_nav()`.

## Schedule Feature
`/schedule` command or "📅 Schedule" button shows upcoming games for user's followed teams.
- `cmd_schedule()` — Entry point for /schedule command
- `_build_schedule()` — Shared logic for command + callback. Fetches events per league via `fetch_events_for_league()`, converts to SAST (Africa/Johannesburg), groups by date ("Today" / "Tomorrow" / "Wednesday, 26 Feb"), numbers events with sport emojis and kick-off times. Bolds user's followed teams. Abbreviated team buttons using `config.abbreviate_team()`. Limits to top 5 buttons for Telegram constraints. Returns (text, markup).
- `_generate_game_tips()` — AI game breakdown per event using Claude Haiku. Builds structured odds context, calls Claude for ~200-word narrative (team form, betting angle, risk assessment). Uses `find_best_sa_odds()` for SA-only odds display. Shows tip buttons with EV%. Caches tips in `_game_tips_cache`. Triggered by "Get Tips" button (`schedule:tips:{event_id}`).
- Shows "No upcoming games found" if no matches for followed teams.

## AI Game Breakdown
When a user taps a game in the schedule, `_generate_game_tips()` calls Claude Haiku (`claude-haiku-4-5-20251001`) with a `GAME_ANALYSIS_PROMPT` system prompt and structured odds context. The response is a ~200-word narrative covering team form, betting angles, and risk assessment. Below the narrative, tip buttons are displayed: `💰 {outcome} @ {odds:.2f} (EV: +{ev}%)`.

Tips are cached in `_game_tips_cache[event_id]` for use by the tip detail page.

## Tip Detail Page
Tapping a tip button (`tip:detail:{event_id}:{index}`) shows an experience-adapted detail card via `_format_tip_detail()`:
- **Experienced**: odds, EV%, Kelly stake fraction, top 3 bookmaker comparison
- **Casual**: narrative, R100 payout example, stake hint, bookmaker name
- **Newbie**: bet type explanation, R20/R50 payout examples, "Start small" advice

If user has bankroll set, shows personalised stake recommendation.

Buttons:
- `📖 How to bet on {bookie}` → Telegra.ph guide URL
- `🔔 Follow this game` → `subscribe:{event_id}` for live score alerts
- `↩️ Back` → return to game tips view

## Telegra.ph Betting Guides (`scripts/telegraph_guides.py`)
Publishes step-by-step betting guides for 5 SA bookmakers on Telegra.ph (instant view).

- `BOOKMAKER_GUIDES` dict — Guide content in Telegraph Node format for each bookmaker (signup, deposit, placing bet, withdrawal steps)
- `_ensure_account()` — Creates Telegraph account, caches token in `data/telegraph_token.json`
- `_create_page(token, title, content)` — POST to Telegraph API `/createPage`
- `get_guide_url(bookmaker_key)` → Publishes guide if not cached, returns URL from `data/telegraph_urls.json`

Supports: betway, sportingbet, 10bet, playabets, supabets.

## Live Game Subscriptions
Users can subscribe to live score updates for specific games.

### Subscription flow
1. User taps "🔔 Follow this game" on a tip detail page → `subscribe:{event_id}`
2. Creates `GameSubscription` in DB with event metadata
3. User receives confirmation message

### Score polling (`scripts/live_scores.py`)
- `fetch_scores(sport_key)` — Fetches from Odds API `/scores` endpoint (1 request/call)
- `detect_changes(event_id, current)` — Compares with in-memory `_score_cache`, returns change descriptions:
  - Score updates: `⚽ Score update: Arsenal 2 - 1 Chelsea`
  - Game completed: `🏁 Full time: Arsenal 2 - 1 Chelsea`
- `check_score_updates(bot)` — Polls for updates, sends notifications to subscribers, deactivates subscriptions for completed games

### Quota strategy
Poll every 5 minutes only for sport_keys with active subscribers. `/scores` costs 1 request/call.

## Bankroll Management
Users set a weekly betting bankroll during onboarding (step 6) or via Settings → "💰 Bankroll".

### Preset amounts
R500, R1000, R2000, R5000, plus "Not sure yet" (skip) and "Custom amount" (text input).

### Integration
- Stored in `User.bankroll` (float, nullable)
- Used in `picks_engine.get_picks_for_user()` for Kelly stake sizing (defaults to R1000 if not set)
- Displayed in profile summary and tip detail pages
- Personalised stake recommendations in tip detail: `💰 Suggested: R{stake} ({pct}% of R{bankroll})`

## Settings Team Editing
Settings → "My Teams" → "✏️ Edit Teams" shows a league picker. Selecting a league enters text input mode for that league (same fuzzy matching as onboarding). State tracked in `_team_edit_state[user_id]`.

Flow: `teams:edit` → league picker → `teams:edit_league:{sk}:{lk}` → text input → fuzzy match → save. Uses `db.clear_user_league_teams()` to replace teams for the selected league.

## Betting Story / Notification Preferences
Multi-step notification quiz presented after onboarding or accessible via Settings → "📖 My Notifications".

### Story quiz state
`_story_state[chat_id]` dict with `step` (0-5) and `prefs` dict. Steps iterate through `STORY_STEPS` list.

### 6 notification types
| Key | Default | Description |
|-----|---------|-------------|
| daily_picks | on | Morning value bet picks |
| game_day_alerts | on | Pre-match alerts for followed teams |
| weekly_recap | on | Weekly performance summary |
| edu_tips | on | Betting education tips |
| market_movers | off | Line movement alerts |
| live_scores | on | Live score updates for subscribed games |

The `live_scores` step is skipped for newbie experience level.

### Settings integration
Settings → "📖 My Notifications" shows toggle buttons for each notification type with on/off emoji indicators.

## Profile Summary
`format_profile_summary(user_id)` — Reusable async helper that formats a clean profile display. Used in `settings:home` and onboarding summary. Shows experience, sports grouped by league with teams (abbreviated league names via `_abbreviate_league()`), bankroll, risk profile, and notification time.

### League abbreviations
`_abbreviate_league(label)` maps long league names to short forms: "Champions League"→"UCL", "Six Nations"→"6N", "CSA / SA20"→"SA20", "Rugby Championship"→"RC", etc.

## Experience-Adapted Pick Cards
`format_pick_card(pick, index, experience)` in `scripts/picks_engine.py`:
- **Experienced**: compact stats — odds, EV%, Kelly stake, stake→return with profit
- **Casual**: narrative — "We like X", explained odds, R100 payout illustration
- **Newbie**: full hand-holding — bet type explained, payout in R20/R50, "Start small" advice

Legacy `format_pick_card(pick)` in `scripts/odds_client.py` still used for ValueBet objects in test suite.

## Service Layer (`services/`)
Platform-agnostic business logic extracted from bot.py. Services return plain data (dicts) that renderers format for specific platforms.

### user_service.py
| Function | Purpose |
|----------|---------|
| `classify_archetype(experience, risk, num_sports)` | Classify user into archetype with engagement score |
| `get_profile_data(user_id)` | Fetch structured profile data (experience, sports, risk, bankroll, notify) |
| `persist_onboarding(user_id, ob)` | Save all onboarding data to DB and classify archetype |
| `get_user_league_keys(user_id)` | Get user's preferred league keys (fallback: all leagues) |
| `get_user_teams(user_id)` | Get user's followed team names (lowercased set) |

### schedule_service.py
| Function | Purpose |
|----------|---------|
| `get_schedule(user_id, max_events)` | Build schedule data: events grouped by date with SAST times |
| `get_game_tips_data(event_id, user_id)` | Fetch odds and calculate EV for a specific game |

### picks_service.py
| Function | Purpose |
|----------|---------|
| `get_picks(user_id, max_picks)` | Full picks pipeline: loads profile → fetches odds → returns structured picks |

### templates.py
Message template registry with `telegram` and `whatsapp` variants for all user-facing strings.

```python
from services.templates import render
msg = render("welcome_new_user", name="Paul")  # Telegram HTML
msg = render("picks_header", platform="whatsapp", count=3, s="s", ...)
```

~40 templates covering: welcome, menus, picks, schedule, onboarding, settings, errors, subscriptions.

## Renderers (`renderers/`)
Platform-specific rendering of service layer data.

### telegram_renderer.py
Formats data as Telegram HTML with `<b>`, `<i>`, `<code>` tags:
- `render_profile_summary(data)` → HTML profile card
- `render_schedule(data)` → HTML schedule with date groups
- `render_picks_header(data)` / `render_no_picks(data)` → HTML picks messages
- `render_game_tips(data, narrative)` → HTML game analysis with odds
- `render_tip_detail(tip, experience, bankroll)` → Experience-adapted tip detail

### whatsapp_renderer.py (placeholder)
Formats data as WhatsApp-safe plain text with `*bold*`, `_italic_`:
- Same function signatures as telegram_renderer
- Strips HTML tags, uses WhatsApp formatting
- `menu_buttons()` / `picks_buttons()` → WhatsApp interactive button format (max 3 per message)

### whatsapp_menus.py
Documents WhatsApp 3-button menu adaptations:
- `TELEGRAM_KEYBOARD_AUDIT` — maps each keyboard function to button count + adaptation needed
- Defines cascading menu structures for WhatsApp (e.g. main menu → more... sub-menus)
- Paginated sport selection (3 per screen)

## WhatsApp Readiness
DB supports multi-platform users:
- `User.whatsapp_phone` — Phone number (e.g. "+27821234567")
- `User.preferred_platform` — "telegram" or "whatsapp"
- `db.update_user_whatsapp(user_id, phone, platform)` — Set WhatsApp config
- Profile reset clears WhatsApp fields

The architecture separates concerns:
1. **Services** return plain data (no platform deps)
2. **Renderers** format data for specific platforms
3. **Templates** provide platform-specific message strings
4. **bot.py** handles only Telegram-specific dispatch (PTB handlers, InlineKeyboardMarkup)

## Conventions
- HTML parse_mode throughout all Telegram messages
- PTB v20+ async handlers
- Inline keyboards only (no reply keyboards)
- Max 2 buttons per row for mobile
- `prefix:action` callback_data routing in `on_button()`
- Loading messages use randomised verb templates
- Sport-appropriate language via `fav_type` field
- ↩️ back arrow (not 🔙) across all buttons
- .co.za domain names for SA bookmaker display (no 🇿🇦 flags on bookmaker names)
- Onboarding back buttons on every step except the first (experience)

## Verification
```bash
# Run unit tests (281 tests)
pytest tests/ -x -q --ignore=tests/e2e_telegram.py --ignore=tests/e2e_telethon.py

# Run specific test file
pytest tests/test_onboarding.py -v

# Start the bot
python bot.py
```

## E2E Testing (Playwright on Telegram Web)

### Setup (one-time)
```bash
# 1. Install system deps (needs sudo)
sudo bash scripts/setup_e2e.sh

# 2. Save Telegram Web login session (needs display)
python save_telegram_session.py
# → Saves data/telegram_session.json
```

### Running E2E tests
```bash
python tests/e2e_telegram.py                    # Run all suites
python tests/e2e_telegram.py --test onboarding  # Specific suite
python tests/e2e_telegram.py --test commands    # Post-onboarding commands
python tests/e2e_telegram.py --test fuzzy       # Fuzzy matching only
python tests/e2e_telegram.py --test edge        # Edge cases
python tests/e2e_telegram.py --report           # View saved report
```

### E2E test suites
1. **Onboarding Flow** — /start, experience, sports, leagues, teams, risk, bankroll, notify, summary, edit, confirm
2. **Post-Onboarding** — all commands respond, settings menu, back buttons, HTML formatting
3. **Profile Reset** — warning screen, confirm reset, re-onboarding
4. **Fuzzy Matching** — typos ("Arsnal"), aliases ("gooners"), SA slang ("amakhosi")
5. **Edge Cases** — zero sports, /start when onboarded, random text, rapid commands
6. **Sticky Keyboard & UX Polish** — keyboard appears after /start, all 6 buttons respond, back arrows use ↩️, schedule formatting, profile accessibility

### Reports
- `data/e2e_report.json` — structured JSON report
- `data/e2e_screenshots/` — screenshots at every step

## Environment Variables
See `.env.example` for required variables:
- `BOT_TOKEN` — Telegram bot token
- `ODDS_API_KEY` — The Odds API key
- `ANTHROPIC_API_KEY` — Claude API key
- `ADMIN_IDS` — Comma-separated Telegram user IDs
- `TZ` — Timezone (default: Africa/Johannesburg)
- `DATABASE_URL` — SQLAlchemy async URL
