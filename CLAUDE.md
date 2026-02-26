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
  test_e2e_flow.py     ← Telethon-based E2E flow tests: sticky keyboard, Your Games, Hot Tips, sport filter
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
- `picks:today` / `picks:go` — Legacy picks (still works via _do_picks_flow)
- `yg:all:{page}` — Your Games: default all-games view with pagination
- `yg:sport:{key}:{day}:{page}` — Your Games: sport-specific 7-day view
- `yg:game:{event_id}` — Your Games: tap game → AI breakdown
- `yg:noop` — No-op for pagination label
- `hot:go` / `hot:show` — Hot Tips: scan all sports, send separate messages per tip
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
- `nav:schedule` — Navigate to Your Games (legacy redirect)
- `schedule:tips:{event_id}` — Get AI tips for a specific game
- `tip:detail:{event_id}:{index}` — View detailed tip analysis
- `subscribe:{event_id}` — Subscribe to live score updates for a game
- `unsubscribe:{event_id}` — Unsubscribe from live score updates
- `story:start` / `story:pref:{key}:{yes|no}` — Betting story notification quiz
- `ob_fav_retry:{sport_key}` — Re-prompt for team text input

## Picks / Value Bet Flow
1. User taps "🔥 Hot Tips" button or sends `/picks` → `_build_hot_tips()` (new primary flow)
   - Legacy: `picks:today` callback → `_do_picks_flow()` (still works)
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

### SA Bookmaker Config (Betway-exclusive MVP)
**MVP Strategy:** Betway is the only active bookmaker. Other SA books are dormant (`active: False`) for future expansion.

```python
ACTIVE_BOOKMAKER = "betway"
BETWAY_AFFILIATE_CODE = "BPA117074"

SA_BOOKMAKERS = {
    "betway": {"display_name": "Betway.co.za", "short_name": "Betway", "website_url": "https://www.betway.co.za", "guide_url": "<telegraph_url>", "affiliate_base_url": "https://www.betway.co.za/?btag=BPA117074", "active": True},
    "sportingbet": {..., "active": False},
    "10bet": {..., "active": False},
    "playabets": {..., "active": False},
    "supabets": {..., "active": False},
}
```

**Helper functions:**
- `config.get_active_bookmaker()` → returns the active bookmaker's full config dict
- `config.get_active_display_name()` → `"Betway"` (short name)
- `config.get_active_website_url()` → `"https://www.betway.co.za"`
- `config.get_affiliate_url(event_id=None)` → Betway affiliate URL with `?btag=BPA117074` (deep links pending, uses base URL for now)
- `config.sa_display_name(bk_key)` → returns `.co.za` display name for any bookmaker key

**Betway branding:** All user-facing odds display, tip details, bookmaker menus, and pick cards use Betway branding with affiliate tracking via `?btag=BPA117074` (no 🇿🇦 flags on bookmaker names or tips). Sharp bookmakers (Pinnacle, Betfair, etc.) are kept for internal probability estimation only — never shown to users. Deep links to specific events are pending — `get_affiliate_url()` accepts an `event_id` parameter for future use.

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
- `get_users_for_notification(hour)` — Get onboarded users with matching notification_hour and daily_picks enabled
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
⚽ Your Games | 🔥 Hot Tips | 📖 Guide
👤 Profile    | ⚙️ Settings | ❓ Help
```

- `get_main_keyboard()` — returns the 2×3 `ReplyKeyboardMarkup`
- `handle_keyboard_tap()` — `MessageHandler` with `filters.Regex` that routes taps to existing handlers
- `_LEGACY_LABELS` dict maps old button labels ("🎯 Today's Picks", "📅 Schedule", "🔴 Live Games", "📊 My Stats", "📖 Betway Guide") to new handlers for cached keyboards
- Sent after onboarding completes (in `handle_ob_done`)
- Sent with `/start` for returning users and `/menu`
- Hidden during onboarding with `ReplyKeyboardRemove()`
- Coexists with inline keyboards (`InlineKeyboardMarkup`) — both visible simultaneously
- Handler registered BEFORE `freetext_handler` in `main()` (order matters in PTB)

### Keyboard routes
| Button | Handler |
|--------|---------|
| ⚽ Your Games | `_show_your_games()` — personalised 7-day schedule with edge indicators |
| 🔥 Hot Tips | `_show_hot_tips()` — top 5 cross-market value bets with confidence indicators |
| 📖 Guide | `_show_betway_guide()` — Telegra.ph guide link |
| 👤 Profile | `_show_profile()` — full profile summary via `format_profile_summary()` |
| ⚙️ Settings | `kb_settings()` inline menu |
| ❓ Help | HELP_TEXT — commands and feature descriptions |

## Inline Menu System
Main menu: `kb_main()` → Your Games | Hot Tips | My Bets | My Teams | Stats | Bookmakers | Settings

Sub-menus: `kb_bets()`, `kb_teams()`, `kb_stats()`, `kb_bookmakers()`, `kb_settings()`
Every sub-screen has "↩️ Back" + "🏠 Main Menu" via `kb_nav()`.

## Your Games Feature (replaces Schedule)
`/schedule` command or "⚽ Your Games" button shows personalised game schedule with two views.

### Two-view architecture
1. **Default (all games)**: `_render_your_games_all(user_id, page)` — Shows all games sorted by edge first then by time. Sport filter emoji buttons at bottom.
2. **Sport view**: `_render_your_games_sport(user_id, sport_key, day_offset, page)` — 7-day schedule for one sport with day navigation tabs.

### Core functions
- `_show_your_games(update, ctx, user_id)` — Entry point (reply keyboard + /schedule command)
- `_render_your_games_all(user_id, page)` — Default all-games view, sorted by edge, with sport filter buttons
- `_render_your_games_sport(user_id, sport_key, day_offset, page)` — Sport-specific 7-day view with day nav
- `_fetch_schedule_games(user_id)` — Fetches and caches events from user's leagues
- `_check_edges_for_games(games)` — Quick EV check per game (🔥 marker if any outcome has EV > 2%)
- `_parse_date(commence_time)` — Parse commence_time to SAST datetime
- `_format_date_label(date_obj, now_dt)` — Format date as "Today", "Tomorrow", "Wednesday, 26 Feb"
- `_get_sport_emoji_for_api_key(api_key)` — Map Odds API sport key to emoji

### Callback patterns
- `yg:all:{page}` — Default all-games view with pagination
- `yg:sport:{key}:{day}:{page}` — Sport-specific view with day offset + pagination
- `yg:game:{event_id}` — Tap a game → AI breakdown (replaces `schedule:tips:`)
- `yg:noop` — No-op for pagination label

### Sport filter buttons
Shown when user follows 2+ sport categories. Row of emoji buttons (e.g. `⚽ 🏉 🏏`). Tapping switches to sport-specific 7-day view.

### Edge indicators
`_check_edges_for_games()` does a quick EV scan using cached odds. Games with EV > 2% on any outcome get a 🔥 marker. In default view, edge games sort to the top.

### Pagination
10 games per page (`GAMES_PER_PAGE = 10`). Callbacks: `yg:all:{page}` or `yg:sport:{key}:{day}:{page}`.

### Game tap → AI breakdown
`yg:game:{event_id}` → `_generate_game_tips()`. Back button returns to `yg:all:0`.

## Hot Tips Feature (replaces Picks)
`/picks` command or "🔥 Hot Tips" button scans ALL sports for value bets and sends separate messages per tip.

### Core functions
- `_show_hot_tips(update, ctx, user_id)` — Entry point (reply keyboard + /picks command)
- `_do_hot_tips_flow(chat_id, bot)` — Core logic: scan all sports, send separate messages per tip with Betway button
- `_fetch_hot_tips_all_sports()` — Scans `HOT_TIPS_SCAN_SPORTS` (~25 Odds API sport keys) for value bets. Uses 15-min cache.
- `_format_kickoff_display(commence_time)` — Format as "Today 19:30" or "Wed 26 Feb, 15:00"

### All-sports scanning
`HOT_TIPS_SCAN_SPORTS` is a list of ~25 Odds API sport keys covering soccer, rugby, cricket, basketball, NFL, MMA, boxing, tennis, golf. Tips are scanned across ALL sports (not just user's preferences).

### 15-minute cache
`_hot_tips_cache["global"]` stores `{"tips": [...], "ts": float}` with `HOT_TIPS_CACHE_TTL = 900` seconds.

### Top 5 selection
Scanned tips are sorted by EV% descending and capped at top 5 for a focused discovery feed.

### Message format
- Header message: "🔥 Hot Tips — N Value Bets"
- Individual tip messages (one per tip): match, kickoff, outcome, odds, EV%, confidence with indicator (🟢 ≥60%, 🟡 ≥40%, 🔴 <40%)
- Each tip has a "📲 Bet on Betway →" button (URL link)
- Footer message with Refresh, Your Games, Menu buttons

### No flags or disclaimers
- No 🇿🇦 flags on bookmaker names in tip/pick outputs
- No "gamble responsibly" disclaimers in tip outputs
- Clean, focused tip presentation

### Legacy compatibility
- `/picks` command redirects to Hot Tips
- `picks:today` / `picks:go` callbacks still work via `_do_picks_flow()`
- `_do_picks_flow()` still exists for direct API use
- `hot:go` / `hot:show` both trigger `_do_hot_tips_flow()`

## AI Game Breakdown
When a user taps a game in Your Games, `_generate_game_tips()` calls Claude Haiku (`claude-haiku-4-5-20251001`) with `GAME_ANALYSIS_PROMPT`. The prompt uses structured emoji section headers:
- 📋 **The Setup** — recent form, injuries/absences, head-to-head, venue factor with specific stats
- 🎯 **The Edge** — specific value angle with probability gap reference; honest when no edge exists
- ⚠️ **The Risk** — specific scenario that could derail the pick (key player rested, weather, etc.)
- 🏆 **Verdict** — bold one-line pick with conviction level (High/Medium/Low)

No disclaimers in the AI output (handled separately). South African conversational tone ("braai", "lekker"). Sport-specific language ("clean sheet" for soccer, "try line" for rugby, "strike rate" for cricket). Keeps output short when data is thin. Odds shown separately below as "Betway Odds" section. Tips cached in `_game_tips_cache[event_id]`.

## Tip Detail Page
Tapping a tip button (`tip:detail:{event_id}:{index}`) shows an experience-adapted detail card via `_format_tip_detail()`:
- **Experienced**: odds with Betway branding, EV%, Kelly stake fraction
- **Casual**: narrative, R100 payout example, stake hint, Betway branding
- **Newbie**: bet type explanation, R20/R50 payout examples, "Start small" advice

If user has bankroll set, shows personalised stake recommendation.

Buttons always use the active bookmaker (Betway for MVP):
- `📲 Bet on Betway →` → affiliate URL with `?btag=BPA117074`
- `🔔 Follow this game` → `subscribe:{event_id}` for live score alerts
- `↩️ Back` → return to Your Games (`yg:all:0`)

## Morning Notification Teasers (Scheduled Job)
Automated daily teaser messages sent to users at their preferred notification hour.

### Architecture
- Uses PTB's `JobQueue.run_repeating()` with 1-hour interval
- `_seconds_until_next_hour()` calculates first run time (aligns to next whole hour SAST)
- `_morning_teaser_job(ctx)` — runs every hour, checks current SAST hour against users' `notification_hour`
- `db.get_users_for_notification(hour)` — queries onboarded users with matching hour + `daily_picks` enabled

### Teaser format
When tips exist:
```
☀️ Good morning!
🔥 N value bets found today.
Top pick: ⚽ Team A vs Team B
💰 Outcome @ odds · EV +X%
⏰ Kickoff time
```
With buttons: "🔥 See Hot Tips" + "⚽ Your Games"

When no tips: "No value bets found yet today" message with same buttons.

### Notification preferences
- Only sends to users with `daily_picks: true` in notification_prefs JSON
- Respects `notification_hour` set during onboarding (7, 12, 18, or 21)
- Silently skips users whose Telegram chat is unavailable (blocked bot, etc.)

## Telegra.ph Betting Guides (`scripts/telegraph_guides.py`)
Publishes step-by-step betting guides for SA bookmakers on Telegra.ph (instant view).

- `BOOKMAKER_GUIDES` dict — Guide content in Telegraph Node format (signup, FICA, deposit, bet placement, withdrawal, app)
- `_ensure_account()` — Creates Telegraph account, caches token in `data/telegraph_token.json`
- `_create_page(token, title, content)` — POST to Telegraph API `/createPage`
- `get_guide_url(bookmaker_key)` → Publishes guide if not cached, returns URL from `data/telegraph_urls.json`
- `ensure_active_guide()` → Pre-publishes guide for `ACTIVE_BOOKMAKER` and wires URL into `config.SA_BOOKMAKERS[key]["guide_url"]`. Called at bot startup in `_post_init()`.

MVP: Betway guide is comprehensive (6 steps: signup, FICA, deposit methods, bet placement, withdrawal, app). Other bookmaker guides are basic (4 steps).

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
- Both persistent reply keyboard (2×3 sticky keyboard) and inline keyboards (callback menus)
- Max 2 buttons per row for mobile
- `prefix:action` callback_data routing in `on_button()`
- Loading messages use randomised verb templates
- Sport-appropriate language via `fav_type` field
- ↩️ back arrow (not 🔙) across all buttons
- .co.za domain names for SA bookmaker display (no 🇿🇦 flags on bookmaker names)
- Onboarding back buttons on every step except the first (experience)

## Verification
```bash
# Run unit tests (E2E auto-excluded via pytest.ini)
pytest tests/ -x -q

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

### Telethon E2E flow tests
```bash
python tests/test_e2e_flow.py                    # Run all 8 flow tests
python tests/test_e2e_flow.py --test sticky_keyboard  # Specific test
python tests/test_e2e_flow.py --test hot_tips     # Hot Tips separate messages
python tests/test_e2e_flow.py --test no_za_flags  # Verify no ZA flags in tips
```

8 Telethon-based tests:
1. **sticky_keyboard** — Verify 2×3 reply keyboard layout
2. **your_games** — Default all-games view
3. **sport_filter** — Sport emoji button → sport-specific view
4. **pagination** — Pagination when >10 games
5. **hot_tips** — Separate messages per tip with Betway buttons
6. **all_sports** — Header mentions "all markets"
7. **no_za_flags** — No 🇿🇦 flags in tip messages
8. **game_breakdown** — Game tap → AI analysis with Betway button

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

## Agent Reporting Pipeline

### Overview
CLI agents push markdown reports to Notion via push-report script. Reports land in the Agent Reports Pipeline database, tagged and searchable.

### Flow
1. Team Lead writes brief → Director pastes into agent's tmux window
2. Agent works → writes .md report to /home/paulsportsza/reports/
3. Agent runs: push-report --agent X --wave Y report.md
4. Report appears in Notion with status "New"
5. Team Lead reads/reviews in Notion → marks "Reviewed"
6. Team Lead writes next briefs → cycle repeats

### push-report Script
- Location: /usr/local/bin/push-report
- Source: /home/paulsportsza/push-report.py
- Zero external deps — Python 3 stdlib only (urllib.request)
- Features: Multi-page splitting (>95 blocks → linked pages of 90), h4+ heading fix, 30s timeout
- Config: PROJECT = "MzansiEdge", VALID_AGENTS = ["QA", "LeadDev", "Dataminer", "UX"], NOTION_DB_ID = "a7cd424d700a4ab684ec10bd08c9948b"

### Environment Variables (set in /etc/environment AND ~/.bashrc)
    NOTION_TOKEN=(set in ~/.bashrc — do not commit)
    NOTION_DB_ID=a7cd424d700a4ab684ec10bd08c9948b

### Usage
    push-report --agent QA --wave 9A /home/paulsportsza/reports/qa-wave9a-20260225-1527.md
    push-report --agent LeadDev --wave 9B --status "Action Taken" --title "Merge Complete" report.md

### Agent Brief Template (REPORT section)
Every agent brief MUST end with a REPORT section containing:
- Write report to: /home/paulsportsza/reports/{agent}-{wave}-$(date +%Y%m%d-%H%M).md
- Push to Notion: push-report --agent {Agent} --wave {Wave} /path/to/report.md

### Notion Database References

| Database | DB Hex ID | Data Source (collection://) |
|---|---|---|
| Agent Reports Pipeline | a7cd424d700a4ab684ec10bd08c9948b | collection://7da2d5d2-0e74-429e-9190-6a54d7bbcd23 |
| Bug Tracker | — | collection://263e9fe5-ba1d-492a-b960-2f765379ed5a |
| Sprint Log | — | collection://120f7ad1-5b03-47a6-ac30-4c4dfc490cf0 |

| Notion Page | Page ID |
|---|---|
| Team Status | 312d9048-d73c-81a2-8ae6-c022d938c755 |
| Agent Reporting Guide | 312d9048-d73c-814a-afc3-e7cd835d02fb |
| Wiki | 311d9048-d73c-8178-a24e-e2c305937775 |

## Multi-Bookmaker Architecture (Day 6+)

### New Services (on feature/multi-bookmaker branch)
| File | Purpose |
|------|---------|
| services/edge_rating.py | 5-factor edge scoring: consensus 30%, model alignment 25%, line movement 15%, value detection 20%, market breadth 10%. Returns DIAMOND/GOLD/SILVER/BRONZE/HIDDEN. |
| services/affiliate_service.py | Best-odds bookmaker selection, rotating affiliate links, runner-up odds |
| services/odds_service.py | Cross-bookmaker odds from Dataminer odds.db. Wide-format schema. |
| services/analytics.py | PostHog v7 event tracking wrapper |
| renderers/edge_renderer.py | Telegram HTML: edge badges, tip cards with odds comparison |

### Edge Rating Tiers (Diamond System — Wave 14A)
| Tier | Emoji | EV Threshold | Score Threshold |
|------|-------|-------------|-----------------|
| Diamond | 💎 | ≥15% | 85%+ |
| Gold | 🥇 | ≥8% | 70%+ |
| Silver | 🥈 | ≥4% | 55%+ |
| Bronze | 🥉 | ≥1% | 40%+ |
| Hidden | — | <1% | Below 40% — NOT shown to users |

### Integration Status
- Services built and unit-tested (50+ edge case tests pass)
- NOT yet wired into bot.py handlers — tips still show single-source odds
- Merge needed: feature/stitch-integration into feature/multi-bookmaker (3 file conflicts)

## Scraper Pipeline (Dataminer)

### 5 Bookmakers LIVE
| Bookmaker | Scraper | Method | Proxy |
|-----------|---------|--------|-------|
| Hollywoodbets | bookmakers/hollywoodbets.py | REST API | ISP proxy (mzansi_isp) |
| Supabets | bookmakers/supabets.py | ASMX JSON | None |
| Betway | bookmakers/betway.py | REST BetBook | None |
| Sportingbet | bookmakers/sportingbet.py | REST CDS/Entain | None |
| GBets | bookmakers/gbets.py | WebSocket Swarm | None |

### Database
- Location: /home/paulsportsza/scrapers/odds.db (SQLite)
- Rows: 17,079+ (growing ~42K/day)
- Schema: Wide-format — one row per (bookmaker, match, market, timestamp)
- Columns: bookmaker, match_id, home_team, away_team, league, home_odds, draw_odds, away_odds, over_odds, under_odds, scraped_at, market_type
- Markets: 1x2, btts, over_under_2.5
- Leagues: PSL, EPL, Champions League
- Cron: 57 runs/day, ~740 odds per run, 46-second runtime

### Bright Data Credentials
- API Key: 4148a9c8-d613-494c-86db-adaa53991e51
- Customer ID: hl_b7cc8a14
- Zone: mzansi_isp (ZA-geolocated ISP IPs)

## Branch Status (as of Day 9 / 25 Feb 2026)

main (69c8273) has two feature branches:
- feature/stitch-integration (5b6abca) — 6 commits, 295 tests
- feature/multi-bookmaker = ux/playbook-conventions-day6 (cf9dbcd) — 8 commits, 281 tests

### Recommended Merge Order
1. ux/playbook-conventions-day6 → main (clean)
2. feature/stitch-integration → main (3 file conflicts, ~17 min)
3. Delete feature/multi-bookmaker (duplicate)

## Bug Tracker Summary

### Open Bugs (4 — all P3)
| ID | Description |
|----|-------------|
| BUG-009 | Keyless leagues — FIXED in cf9dbcd, needs re-verify |
| BUG-013 | Platinum edge threshold may be too narrow |
| BUG-015 | ExecStart uses system Python not venv |
| BUG-016 | PID lock no PermissionError handling |

## Payment Integration
- Paystack: REJECTED (betting)
- Stripe: Unavailable in SA
- Stitch: Signing up (Feb 2026). Code on feature/stitch-integration branch.

## Affiliate Status (25 Feb 2026)
| Bookmaker | Status |
|-----------|--------|
| Playa Bets | Approved |
| GBets | Verified |
| Betway | Applied (BPA117074) |
| Hollywoodbets | Applied |
| Supabets | Under review |
| Sportingbet | Applied |
| WSB | Applied |
| 10bet | Applied |
| Bet.co.za | Not yet (needs 10 depositing customers) |

## Integrations
| Service | Status |
|---------|--------|
| Sentry | Live |
| PostHog | Live (phx_UuZyiC5yp5IFVtotbdcAz1qo0gifBAVimabmwPGNHvhH3HS) |
| ClickUp | Connected |
| Notion | Connected |
| Ahrefs | Connected |
| Bitly | Connected |

## CLAUDE.md Maintenance Rule
CRITICAL: Every LeadDev brief MUST include a CLAUDE.md update section. The Team Lead is responsible for specifying what to add/change in CLAUDE.md as part of every brief. LeadDev appends or edits CLAUDE.md accordingly before filing the wave report. This keeps CLAUDE.md as the authoritative project memory that new sessions read on startup.

## Key Dates
| Date | Milestone |
|------|-----------|
| 14 March 2026 | Launch |
| 25 Feb 2026 | Reporting pipeline deployed, 5 scrapers live, 17K+ odds |

## Wave 10A — Merge + Edge Rating + Multi-Bookmaker (25 Feb 2026)

### Branch Merge
- Merged ux/playbook-conventions-day6 → main (fast-forward, 20 files)
- Merged feature/stitch-integration → main (7 conflict hunks in 3 files resolved)
- Deleted merged branches: ux/playbook-conventions-day6, feature/multi-bookmaker, feature/stitch-integration
- 295 tests pass post-merge

### P0 Bug Fixes
| Fix | Description |
|-----|-------------|
| P0-1 | html.escape on user.first_name in handle_menu |
| P0-2 | html.escape on user.first_name at onboarding completion |
| P0-3 | Notification toggle re-render was missing live_scores option |
| P0-4 | Tip detail now has "Back to Hot Tips" button (was only "Back to Your Games") |
| P0-5 | hot:back callback now handled in on_button router |

### Edge Rating Wired Into Hot Tips
- calculate_edge_rating() called for each tip in _fetch_hot_tips_all_sports
- HIDDEN tips (<40%) filtered out automatically
- Tips sorted by edge rating (platinum first), then EV descending
- Edge badges prepended to each tip line in consolidated message
- Thresholds aligned to UX spec: GOLD 70%+, SILVER 55%+
- Emojis updated: PLATINUM ⛏️🔥, GOLD ⛏️⭐, SILVER ⛏️, BRONZE 🟤

### Multi-Bookmaker Odds in Tip Detail
- OddsService queries Dataminer scrapers DB for all bookmaker odds
- AffiliateService selects best-odds bookmaker with active affiliate priority
- render_tip_with_odds() generates rich multi-bookmaker tip cards
- Dynamic CTA button shows best-odds bookmaker name + affiliate link
- "📊 All Bookmaker Odds" button with render_odds_comparison()
- Graceful fallback to single-bookmaker display when scrapers DB has no match

### New Function: build_match_id (odds_service.py)
Normalises team names + date into composite match_id for scrapers DB lookup.

### New Handler: odds:compare:{event_id}
Shows full bookmaker odds comparison table for a match.

### Hot Tips Cache Fix
Tips from _fetch_hot_tips_all_sports now stored in _game_tips_cache so tip detail can find them.

## Wave 11A Bug Mop-Up (25 Feb 2026)

### Bugs Fixed
- BUG-019: sentry-sdk + posthog added to requirements.txt; sentry import guarded with try/except
- BUG-017: odds_service league filter now case-insensitive (COLLATE NOCASE)
- BUG-018: Silver emoji → ⛏️🥈, Bronze emoji → ⛏️🥉 (pickaxe + medal)
- BUG-015: systemd ExecStart now uses .venv/bin/python instead of /usr/bin/python3
- BUG-016: PID lock handles PermissionError on both read and write

### UX Polish
- CTA button: unified "📲 Bet on {bookmaker} →" format (no double emoji)
- Tip detail: shows "Odds updated X min ago" freshness indicator from scrapers DB timestamp
- Edge badge moved inline: `[1] ⚽ Chiefs vs Pirates ⛏️🔥` instead of separate line

### Test Status
- Tests: 295 passing, 0 failures
- Open bugs: 0 (all 19 resolved)

## Wave 12A — Migrate Hot Tips to odds.db (26 Feb 2026)

### Architecture Change
- Hot Tips now uses Dataminer's odds.db (38K+ rows, 5 SA bookmakers) as PRIMARY data source
- External Odds API demoted to fallback only (was at 498/500 monthly requests)
- Cross-bookmaker consensus model replaces sharp-book probability estimation

### New Functions (bot.py)
- `_build_edge_snapshots_from_match(match)` — converts odds_service match format to edge_rating snapshot format
- `_build_model_from_consensus(match)` — averages implied probabilities across all bookmakers as model prediction
- `_fetch_hot_tips_from_db()` — primary Hot Tips pipeline: queries odds.db → edge rating → filter HIDDEN → sort by tier + EV → top 10

### Hot Tips Flow (updated)
1. `_do_hot_tips_flow()` calls `_fetch_hot_tips_from_db()` first (primary)
2. If DB returns no tips, falls back to `_fetch_hot_tips_all_sports()` (Odds API)
3. Header updated: "Scanned 3 leagues across 5 SA bookmakers"

### Admin Dashboard (updated)
- `cmd_admin()` now shows odds.db stats prominently (rows, matches, bookmakers, last scrape)
- Odds API section relabelled "(fallback)" with request quota
- New function `get_db_stats()` in services/odds_service.py

### DB_LEAGUES constant
`DB_LEAGUES = ["psl", "epl", "champions_league"]` — leagues queried from odds.db

### Test Status
- Tests: 295 passing, 0 failures
- test_cmd_admin_shows_quota updated to mock odds_svc.get_db_stats
- test_cmd_picks_with_prefs updated to patch _fetch_hot_tips_from_db

## Wave 12B — Hot Tips Display Fixes (26 Feb 2026)

### Bugs Fixed
- BUG-023 (P1): Tip detail now uses multi-bookmaker renderer with all 5 SA bookmakers
  - `handle_tip_detail()` uses pre-fetched `odds_by_bookmaker` from DB tips directly
  - No longer rebuilds match_id from display names (which caused lookup failures)
  - `_handle_odds_comparison()` also uses stored match_id
- BUG-024 (P2): Team names display properly via `_display_team_name()` (wraps odds_normaliser `display_name()`)
- BUG-022 (P2): Bookmaker name shown in Hot Tips listing after odds

### Display Fixes
- Kickoff times no longer show scrape timestamp (odds.db has no kickoff data)
- League shown instead: `🏆 PSL` / `🏆 EPL` / `🏆 Champions League`
- All tips showing Gold Edge is expected behavior (5 SA books with similar odds = 70-80% score)

### Display Format (Hot Tips Listing)
```
[1] ⚽ Mamelodi Sundowns vs Sekhukhune United ⛏️⭐
     🏆 PSL
     💰 Sundowns @ 1.48 (Hollywoodbets) · EV +2.8%
```

### Display Format (Tip Detail)
Uses `render_tip_with_odds()` — shows edge badge, all bookmaker odds, best highlighted,
comparison button, freshness indicator, dynamic CTA bookmaker

### New Helper Functions
- `_display_team_name(key)` — wraps `scrapers.odds_normaliser.display_name()`, fallback: title-case
- `_display_bookmaker_name(key)` — maps bookmaker keys to display names
- `_LEAGUE_DISPLAY` — maps league keys to display names
- `_BK_DISPLAY` — maps bookmaker keys to display names

### Test Status
- Tests: 295 passing, 0 failures

## Wave 12C — Hot Tips UX Polish (26 Feb 2026)

### Mobile-First Rule
- MAX 5 content items per page (tips, games, matches)
- `HOT_TIPS_PAGE_SIZE = 5` constant
- Pagination with ⬅️ Prev / Next ➡️ buttons via `hot:page:{N}` callback
- `_build_hot_tips_page(tips, page)` — reusable page builder returns (text, markup)
- Header shows "Page 1/2 (10 bets found)" when paginated

### Icon Change
- 💡 → 🔍 throughout bot (magnifying glass = "investigate detail")
- Changed in: bot.py, scripts/odds_client.py, scripts/picks_engine.py

### Edge Rating Display
- Percentile-based tiers for UX diversity via `_assign_display_tiers()`
- Top 10% = Platinum, Top 35% = Gold, Top 65% = Silver, Rest = Bronze
- `display_tier` used for rendering badges; raw `edge_score` + `edge_rating` preserved for analytics
- New function: `calculate_edge_score()` in services/edge_rating.py (returns raw 0-100 score)

### Test Status
- Tests: 295 passing, 0 failures

## ⚠️ MANDATORY: Telethon E2E Testing Gate

**NO wave can be marked as "PASS" or "COMPLETE" without Telethon E2E tests against the LIVE running bot.**

### Rules
1. **Unit tests are NOT sufficient.** They test code logic, not what the user actually sees.
2. **Code review is NOT sufficient.** Imports and wiring can be correct on paper but fail at runtime.
3. **Bot API getUpdates is NOT sufficient.** It doesn't capture the real user experience.
4. **Every QA wave MUST include Telethon tests** that:
   - Connect as a real Telegram user via the existing Telethon session
   - Send actual messages/commands/button taps to @mzansiedge_bot
   - Capture the VERBATIM response text the user would see
   - Assert against expected UX (edge badges, multi-bookmaker odds, spacing, emojis)
   - Save raw response captures to /home/paulsportsza/reports/e2e-screenshots/

### Existing Telethon Setup
- Session file: [find with: find /home/paulsportsza -name "*.session"]
- Credentials: [find with: grep -r "API_ID" /home/paulsportsza/bot/.env]
- Previous test file: /home/paulsportsza/bot/tests/test_e2e_flow.py
- History: 8/8 passes across Days 5-8 (commands + keyboard buttons)

### Critical Telethon Checks (minimum for any QA pass)
1. /start → welcome message renders correctly
2. Hot Tips → edge badges visible, tips sorted by tier, dynamic bookmaker (not hardcoded Betway)
3. Tip detail → multi-bookmaker odds shown, CTA format correct, freshness indicator present
4. Odds comparison → multiple SA bookmakers listed
5. Settings → toggles work, live_scores preserved
6. Navigation → back buttons work, no dead ends

### Before Telethon Tests: Verify Bot is Fresh
```bash
# Compare code modification time vs process start time
stat bot.py | grep Modify
ps -p $(pgrep -f "python.*bot.py") -o lstart=
# If process started BEFORE code was last modified → RESTART BOT FIRST
```

### Failure = Block
If any Telethon E2E test fails, the wave is NOT complete. Fix and re-test.

### Bot Restart After Every Commit
Every LeadDev wave that modifies bot.py or any imported module MUST restart the bot process before marking complete:
```bash
pkill -f "python.*bot.py" && sleep 2
cd /home/paulsportsza/bot && source .venv/bin/activate
nohup python bot.py > /tmp/bot_latest.log 2>&1 &
sleep 5 && tail -20 /tmp/bot_latest.log
```
A stale process running old code is invisible to unit tests and has caused multiple missed bugs.

## Wave 12D — AI Tip Narrative + Smart Freshness (26 Feb 2026)

### AI Tip Narrative
- `_build_tip_narrative(tip)` generates a compelling paragraph explaining WHY a tip has value
- Tier-specific opening: Platinum = "Strong value pick", Gold = "Good value found", Silver = "Decent opportunity", Bronze = "Worth a look"
- Explains bookmaker divergence (best price vs market average), model probability, EV percentage
- Social proof: mentions when multiple bookmakers have shorter odds
- Inserted in `handle_tip_detail()` after `render_tip_with_odds()` and before freshness indicator

### Smart Freshness Display
- `_format_freshness(minutes_ago)` replaces raw timestamp logic
- Under 5 min: "⚡ Live odds" (impressive)
- 6-20 min: "Odds updated X min ago" (honest)
- Over 20 min: "Live SA bookmaker odds" (no specific time — avoids looking slow)

### Test Status
- Tests: 295 passing, 0 failures

## Wave 12E — Spacing, Bold Numbers, Game Detail Fix, Narrative Bugs (26 Feb 2026)

### Bold Numbers + Spacing (Global)
- All `[N]` numbered items now bold: `<b>[N]</b>` in Your Games (all + sport views) and Hot Tips
- Blank line after each item for mobile readability
- Blank line before date headers (except first) in Your Games
- Sport view changed from `N.` dot notation to `<b>[N]</b>` brackets for consistency

### Game Detail — odds.db First
- `_generate_game_tips()` now tries odds.db before Odds API (same as Hot Tips)
- If odds.db has data, builds tips from cross-bookmaker consensus (no API quota cost)
- Falls back to Odds API only if odds.db has no match
- Friendlier error: "No SA bookmaker odds available" instead of "Couldn't fetch odds"

### Tip Detail — Tier Consistency
- `handle_tip_detail()` now uses `display_tier` (percentile-based) instead of raw `edge_rating`
- Fixes Platinum-in-listing / Gold-in-detail mismatch

### Narrative Branding + Data Fix
- All tiers use "**The Edge:**" as opener (product branding)
- Fixed key mismatch: narrative now reads `odds`/`bookmaker`/`prob` (actual tip dict keys)
- Guard against zero/missing data (returns empty string instead of "0.00 at .")
- High-premium tips: "No other SA bookmaker has X at these odds"
- Social proof: "shortened their prices" instead of "moving this way"

### Test Status (Wave 12E)
- Tests: 295 passing, 0 failures

## Wave 12F — UX Audit Fixes (26 Feb 2026)

### Pagination
- `GAMES_PER_PAGE = 5` (was 10) — affects Your Games All, Your Games Sport, Schedule

### Bold Numbers + Spacing (additional screens)
- Schedule page: `N.` → `<b>[N]</b>` + blank lines between items
- Tip History: blank lines between items
- Bet History: blank lines between items
- Live Games: blank lines between items

### html.escape Additions
- `render_tip_with_odds()` — home/away escaped
- `_format_tip_detail()` — outcome/home/away escaped
- `_generate_game_tips()` — home/away escaped
- `format_odds_message()` — home/away escaped + blank lines
- Morning teaser — home/away escaped
- Tip History / Bet History — match/prediction escaped
- Live Games — team names escaped
- Schedule page — home/away escaped

### Game Breakdown Format
- Odds lines split into 2 lines: outcome + bookmaker on first, prob + EV on second

### Test Status (Wave 12F)
- Tests: 295 passing, 0 failures

## Wave 12G — Restore AI Game Breakdown (26 Feb 2026)

### Bug Fix
- Removed early return in `_generate_game_tips()` that blocked Claude Haiku call when no odds data existed
- AI breakdown now works for ALL sports including cricket, rugby, and matches without odds coverage

### Enhancements
- Multi-bookmaker CTA: uses `select_best_bookmaker()` when odds.db data available
- "📊 All Bookmaker Odds" button added when odds.db data exists
- Odds context prompt instructs Claude to provide general analysis when no odds available
- Tip dicts from odds.db now include `match_id` and `odds_by_bookmaker` for downstream handlers
- Conditional odds header: "SA Bookmaker Odds:" (odds.db) vs "Betway Odds:" (API)

### Test Status (Wave 12G)
- Tests: 295 passing, 0 failures

## Wave 12H — Spacing Fix + Country Flags (26 Feb 2026)

### P0: Double Spacing Fix
- Deleted 3 `lines.append("")` lines causing double blank lines between game items
- Affected: `_render_your_games_all()`, `_render_your_games_sport()`, `_render_schedule_page()`
- Blank line before date headers already handles group spacing correctly

### P1: Country Flags
- `config.COUNTRY_FLAGS` — dict mapping ~35 country/team names to flag emojis (Africa, Europe, Oceania, Americas, Asia)
- `config.get_country_flag(team_name)` — returns flag emoji or '' if not found
- `_get_flag_prefixes(home, away)` — both-or-nothing rule: if BOTH teams have a flag, return both with trailing space; if either is missing, return ('','') for both
- Applied to 10 display locations across 4 files:
  1. `_render_your_games_all()` — Your Games default view
  2. `_render_your_games_sport()` — Your Games sport view
  3. `_render_schedule_page()` — Schedule view
  4. `_build_hot_tips_page()` — Hot Tips listing
  5. `_format_tip_detail()` — Tip detail (all 3 experience levels)
  6. `_generate_game_tips()` — Game breakdown loading + header
  7. `_handle_odds_comparison()` — Odds comparison header
  8. `_show_live_games()` — Live games display
  9. `_morning_teaser_job()` — Morning notification teaser
  10. `render_tip_with_odds()` — Edge renderer tip cards
  11. `format_odds_message()` — Odds client message

### Test Status (Wave 12H)
- Tests: 295 passing, 0 failures

## Wave 13B — Odds Comparison UX Fixes (26 Feb 2026)

### BUG-022: Odds Comparison Dead End (FIXED)
- Added "🔙 Back to Game" button (`yg:game:{event_id}`) to `_handle_odds_comparison()`
- Also kept "🔥 Hot Tips" and "↩️ Menu" buttons for alternate navigation

### BUG-023: Odds Comparison Shows Only One Market (FIXED)
- Rewrote `_handle_odds_comparison()` to fetch full match data via `odds_svc.get_best_odds()`
- Now shows all 3 markets (Home Win / Draw / Away Win) with all bookmakers per market
- Each market section: ⭐ marks best odds, bookmakers sorted descending
- Outcome labels: 🏠 Home Win, 🤝 Draw, 🏟️ Away Win
- Uses `_display_bookmaker_name()` for consistent bookmaker display names

### BUG-024: CTA Bookmaker Mismatch (FIXED)
- Game breakdown CTA now uses the highest positive-EV tip's bookmaker (not tips[0])
- `best_ev_tip = max((t for t in tips if t["ev"] > 0), key=lambda t: t["ev"], default=tips[0])`
- If AI recommends Draw and GBets has best draw odds, CTA links to GBets

### New/Changed Callback Patterns
- `odds:compare:{event_id}` — now shows all 3 markets (was single-outcome)
- Back button in odds comparison: `yg:game:{event_id}` (new)

### Test Status (Wave 13B)
- Tests: 299 passing (4 new), 0 failures

## Wave 13F — North Star: Simplify, Recommend, Convert (26 Feb 2026)

**North Star Applied:** Game Breakdown simplified from 7 to 4 buttons. Recommended bet CTA is now the hero — shows tier badge, outcome, odds, and best bookmaker in one button. Analysis cached for 1hr to make navigation instant. Verdict uses programmatic Edge Rating badge. All back buttons standardised to ↩️. Every screen now passes the Three Laws test: simplify ruthlessly, make betting effortless, our recommendation is the hero.

### Game Breakdown Button Simplification (P0)
- Reduced from 7 buttons to 4: recommended CTA, compare odds, back, menu
- Removed: 3 individual outcome buttons, old static Betway CTA, Hot Tips button
- New `_build_game_buttons(tips, event_id, user_id)` helper for reuse

### Recommended Bet CTA (P0)
- Hero button: `{tier_emoji} Back {outcome} @ {odds} on {bookmaker} →`
- Uses highest positive-EV outcome (same logic as BUG-024 fix)
- Shows edge tier emoji (PLATINUM ⛏️🔥, GOLD ⛏️⭐, SILVER ⛏️🥈, BRONZE ⛏️🥉)
- Links to best bookmaker affiliate URL for that specific outcome
- Falls back to "View odds on {bookmaker} →" when no positive EV exists

### Verdict Edge Rating Badge (P0)
- Programmatic, not AI-generated — injected AFTER Claude response
- Format: `🏆 Verdict — ⛏️⭐ Gold Edge`
- Strips "with High/Medium/Low conviction" text (replaced by tier badge)
- Badge omitted when no EV data available

### Analysis Caching (P1)
- `_analysis_cache: dict[str, tuple[str, list, float]]` — event_id → (html, tips, timestamp)
- TTL: 3600 seconds (1 hour)
- On cache hit: serves instantly, skips Claude API call
- "Back to Game" from Odds Comparison is now instant (no re-analysis)
- Cleared on bot restart (in-memory only)

### Odds Comparison Affiliate Buttons (P0)
- Added 3 affiliate buttons at bottom of odds comparison (one per market)
- Format: `📲 {Bookmaker} — Best for {Home Win/Draw/Away Win} →`
- Only shown when bookmaker has an affiliate URL configured

### Back Button Emoji Consistency (P1)
- Fixed 🔙 → ↩️ in odds comparison back button
- All `InlineKeyboardButton` with "Back" text now use ↩️

### Test Status (Wave 13F)
- Tests: 307 passing (8 new), 0 failures

## Wave 14A — Diamond Edge System Overhaul (26 Feb 2026)

**Diamond Edge System (Wave 14A):** Rebranded PLATINUM → DIAMOND with 💎 emoji. New tier emojis: 💎 Diamond, 🥇 Gold, 🥈 Silver, 🥉 Bronze. Recalibrated thresholds: Diamond ≥15% EV (rare), Gold ≥8%, Silver ≥4%, Bronze ≥1%. Conviction text fully stripped from all AI responses + Claude prompt updated to not generate it. Onboarding Edge explainer screen added. Guide section updated. First-time tooltip implemented.

### P0: Rebrand PLATINUM → DIAMOND + New Emojis
- `EdgeRating.PLATINUM` → `EdgeRating.DIAMOND` in services/edge_rating.py
- `EDGE_EMOJIS`: `{"diamond": "💎", "gold": "🥇", "silver": "🥈", "bronze": "🥉"}`
- `EDGE_LABELS`: All UPPERCASE — `"DIAMOND EDGE"`, `"GOLD EDGE"`, `"SILVER EDGE"`, `"BRONZE EDGE"`
- Updated all display locations: verdict badge, CTA buttons, Hot Tips, Tip Detail, narrative opener
- Updated all test assertions across 6 test files
- Zero instances of "PLATINUM", "⛏️", or "⛏️🔥/⛏️⭐/⛏️🥈/⛏️🥉" remain in codebase

### P0: Recalibrated Tier Thresholds
| Tier | Old EV Threshold | New EV Threshold |
|------|-----------------|------------------|
| Diamond (was Platinum) | ≥8% | ≥15% |
| Gold | ≥5% | ≥8% |
| Silver | ≥2% | ≥4% |
| Bronze | <2% | ≥1% |
- Applied in `_build_game_buttons()`, verdict badge injection, and `_build_tip_narrative()`
- Leeds vs Man City draw at +9.3% EV now shows as 🥇 GOLD EDGE (not Diamond)
- Edge scoring thresholds in `calculate_edge_rating()` unchanged (85/70/55/40)

### P0: Fix BUG-NS-03 — Conviction Text Leak
- Conviction stripping moved OUTSIDE `if narrative and tips:` block — now strips from ALL narratives
- Regex handles all variants: "with Medium conviction", "Conviction: Medium.", "— High conviction", bare "Low conviction"
- Claude prompt updated: "Do NOT include conviction levels (High/Medium/Low) in the Verdict. The Edge Rating badge handles this."
- Double-space collapse after stripping

### P1: Onboarding Edge Explainer Screen
- New step between favourites and risk profile: `_show_edge_explainer()`
- Onboarding flow now 9 steps (was 8): Experience → Sports → Leagues → Favourites → **Edge Explainer** → Risk → Bankroll → Notifications → Summary
- Callback: `ob_nav:edge_done` → proceeds to risk step
- All step numbers updated from X/8 to X/9 throughout
- `back_risk` now goes to edge explainer (not directly to favourites)

### P2: Guide — Edge Ratings Explained
- `_show_betway_guide()` now shows Edge Ratings section first
- Explains all 4 tiers with EV thresholds and rarity
- Pro tip: "Focus on Gold and Diamond tips"
- Betway guide link preserved below separator

### P2: First-Time Edge Rating Tooltip
- On first tip detail view with edge rating, appends: "ℹ️ New to Edge Ratings? Tap 📖 Guide to learn more."
- Tracked via `User.edge_tooltip_shown` (Boolean) in DB
- `db.set_edge_tooltip_shown(user_id)` helper + migration column added
- Shown once per user, never again

### Test Status (Wave 14A)
- Tests: 318 passing (11 new), 0 failures

## Wave 14D — Edge System Cleanup (26 Feb 2026)

**Edge Cleanup (Wave 14D):** Fixed BUG-025 narrative case mismatch (all tiers showed 🥉 because comparisons used UPPERCASE but tier values are lowercase). Added edge badge to morning teaser. Experienced users now skip edge explainer in onboarding. Added ↩️ Back button to edge explainer. Softened guide from exact EV% thresholds to descriptive language. Tooltip now triggers on Gold/Diamond only.

### P2-1: BUG-025 — Narrative Case Mismatch Fix
- `_build_tip_narrative()` replaced UPPERCASE if/elif chain with `EDGE_EMOJIS.get(tier)` dict lookup
- Dict keys are lowercase, matching `EdgeRating` values — all tiers now get correct emoji
- Fallback: `EDGE_EMOJIS.get(tier.lower(), "🥉")` for safety

### P2-2: Morning Teaser Edge Badge
- `_morning_teaser_job()` calls `render_edge_badge()` on top pick's tier
- Badge appended after team names: `"Top pick: ⚽ Home vs Away 🥇 GOLD EDGE"`

### P2-3: Skip Edge Explainer for Experienced Users
- `ob.get("experience") == "experienced"` → skip to risk step directly
- Applied in: `_show_next_team_prompt()`, `favourites_done` callback, `back_risk` callback
- Casual/beginner users still see the edge explainer

### P2-4: Back Button on Edge Explainer
- Added `↩️ Back` button with `ob_nav:back_edge` callback
- Returns to last favourites prompt step

### P3-1: Soften Guide EV Thresholds
- Replaced exact EV% thresholds with descriptive language:
  - Diamond: "Very high expected value" (was "EV ≥15%")
  - Gold: "High expected value" (was "EV ≥8%")
  - Silver: "Moderate expected value" (was "EV ≥4%")
  - Bronze: "Positive expected value" (was "EV ≥1%")

### P3-2: Tooltip Gold/Diamond Only
- Tooltip now only triggers for `edge in ("diamond", "gold")`
- Silver/Bronze tips no longer show the tooltip

### Test Status (Wave 14D)
- Tests: 324 passing (6 new), 0 failures
