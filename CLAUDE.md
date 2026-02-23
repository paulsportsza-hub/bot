# MzansiEdge — CLAUDE.md

## Overview
AI-powered sports betting Telegram bot for South Africa. Uses python-telegram-bot v20+ (PTB), Claude API for AI tips, The Odds API for live odds, and async SQLAlchemy for persistence.

## Architecture

```
bot.py              ← Main bot: handlers, onboarding, picks, callback routing
config.py           ← Environment config, sport/league definitions, TOP_TEAMS, aliases, risk profiles, SPORT_DISPLAY, SA_PRIORITY_GROUPS
db.py               ← Async SQLAlchemy models & helpers (incl. archetype, engagement_score, notification_prefs)
scripts/
  odds_client.py    ← The Odds API client, EV calculation, value bet scanning, odds caching
  picks_engine.py   ← Picks pipeline: fetch → EV calc → filter → rank → format pick cards
  sports_data.py    ← Sports data service: Odds API fetch, file caching, curated lists, thefuzz fuzzy matching, events fetch
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
`config.TEAM_ALIASES[lowercase_alias]` → canonical name. ~93 aliases. Used for fuzzy matching during manual favourite input.

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
- `ob_notify:18` — Select 6 PM notifications
- `ob_done:finish` — Complete onboarding
- `ob_restart:go` — Restart onboarding after profile reset
- `bets:active` / `bets:history` — My Bets sub-menu
- `teams:view` / `teams:edit` — My Teams sub-menu
- `stats:overview` / `stats:leaderboard` — Stats sub-menu
- `affiliate:compare` / `affiliate:sa` / `affiliate:intl` — Bookmakers sub-menu
- `settings:home` / `settings:risk` / `settings:notify` / `settings:sports` / `settings:reset` / `settings:reset:confirm` — Settings sub-menu
- `settings:story` / `settings:toggle_notify:{key}` — Notification preferences in settings
- `nav:main` — Navigate to main menu (alias for `menu:home`)
- `nav:schedule` — Navigate to schedule view
- `schedule:tips:{event_id}` — Get AI tips for a specific game
- `story:start` / `story:pref:{key}:{yes|no}` — Betting story notification quiz
- `ob_fav_retry:{sport_key}` — Re-prompt for team text input

## Picks / Value Bet Flow
1. User taps "Today's Picks" button or sends `/picks`
2. `_do_picks_flow(chat_id, bot, user_id)` sends loading message with randomised verb
3. Loads user's risk profile + preferred leagues from DB
4. Calls `picks_engine.get_picks_for_user(league_keys, risk_profile, max_picks=10)`
5. Engine fetches cached odds per league via `odds_client.fetch_odds_cached()`
6. For each event, estimates sharp probabilities (Pinnacle/Betfair lines preferred, fallback to vig-removed consensus)
7. Computes EV% for each outcome: `(best_odds × fair_prob - 1) × 100`
8. Filters to positive EV above profile's `min_ev` threshold
9. Computes Kelly criterion stake, capped at `max_stake_pct` of R1000 bankroll (min R10)
10. Ranks by EV descending, returns top `max_picks` as structured dicts
11. Bot formats each pick via `picks_engine.format_pick_card(pick, index, experience)` and sends as individual messages
12. Pick cards show: match, outcome, best odds@bookmaker (🇿🇦 for SA books), EV%, confidence, stake→return

### Risk Profile Thresholds
| Profile      | min_ev | Kelly fraction | Max stake % |
|-------------|--------|----------------|-------------|
| Conservative | 5%     | 0.25           | 2%          |
| Moderate     | 3%     | 0.50           | 5%          |
| Aggressive   | 1%     | 1.00           | 10%         |

### SA Bookmakers (highlighted with 🇿🇦)
betway, hollywoodbets, supabets, sportingbet, sunbet, betxchange, playabets, gbets

## Admin Commands
- `/admin` — Dashboard showing Odds API quota (requests used/remaining), total users, onboarded users
- `/settings` — User preferences (risk profile, notifications, sports, profile reset)
- `/stats` — Legacy stats command (user count, tip results)

## Onboarding Quiz Flow (7 steps)
1. **Experience level** — Experienced / Casual / Newbie
2. **Sports selection** — Category-based grid (Soccer, Rugby, Cricket, Tennis, Boxing, MMA, Basketball, American Football, Golf, Motorsport, Horse Racing)
3. **League selection** — Per selected sport, toggle leagues. **Single-league sports auto-select** (e.g. NFL, UFC).
4. **Favourites** — Text-based input per league. User types comma-separated team/player names with fuzzy matching. Max 5 per league. Horse racing skipped (fav_type="skip"). Sport-appropriate language (team/player/fighter/driver). Queue-based: iterates `_fav_league_queue` of `(sport_key, league_key)` pairs.
5. **Risk profile** — Conservative / Moderate / Aggressive
6. **Notification time** — 7 AM / 12 PM / 6 PM / 9 PM
7. **Summary** — Clean profile display (no heart emojis), league-prefixed teams, edit buttons: "Edit Sports & Favourites" and "Edit Risk & Notifications". Confirm with "Let's go!"

### Favourites data structure
`ob["favourites"]` is a dict-of-dicts: `{sport_key: {league_key: [team_names...]}}`. Saved to DB as one `UserSportPref` row per team per league.

### Post-onboarding: Welcome message + Betting Story quiz
All experience levels get the same welcome message with a CTA to "Set Up My Story" (notification preferences quiz) or "Skip for Now". The story quiz walks through 5 notification types (daily_picks, game_day_alerts, weekly_recap, edu_tips, market_movers) with Yes/No for each, saved as JSON in `User.notification_prefs`.

### Archetype classification (on onboarding completion)
`bot.classify_archetype(experience, risk, num_sports)` → `(archetype, engagement_score)`:
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
Settings → "🔄 Reset Profile" → warning screen → "Yes, reset everything" → clears all prefs, risk, experience, onboarding_done in DB → redirects to onboarding. Betting history/stats NOT deleted.

## DB Models
- `User` — id, username, first_name, risk_profile, notification_hour, onboarding_done, experience_level, education_stage, archetype, engagement_score, notification_prefs (JSON), source, fb_click_id, fb_ad_id
- `UserSportPref` — user_id, sport_key, league, team_name
- `Tip` — sport, match, prediction, odds, result
- `Bet` — user_id, tip_id, stake

### Key DB helpers
- `reset_user_profile(user_id)` — Wipe all user preferences (incl. archetype/engagement) but keep account + history
- `clear_user_sport_prefs(user_id)` — Delete all sport prefs for a user
- `update_user_archetype(user_id, archetype, engagement_score)` — Set archetype classification
- `get_onboarded_count()` — Count of users who completed onboarding
- `get_notification_prefs(user)` — Parse JSON notification prefs with defaults (daily_picks, game_day_alerts, weekly_recap, edu_tips, market_movers, bankroll_updates)
- `update_notification_prefs(user_id, prefs)` — Save notification preferences as JSON
- `_migrate_columns()` — Auto-add new columns to existing SQLite databases on startup

### Picks Engine (`scripts/picks_engine.py`)
| Function | Purpose |
|----------|---------|
| `get_picks_for_user(league_keys, risk_profile, max_picks)` | Full pipeline: fetch cached odds → sharp prob estimation → EV calc → filter → rank |
| `format_pick_card(pick, index, experience)` | Experience-aware pick card formatting (experienced/casual/newbie) |

Returns dict: `{ok, picks, total_scanned, total_events, total_markets, quota_remaining, errors}`

Each pick dict contains: `event_id, sport_key, home_team, away_team, commence_time, market, outcome, odds, bookmaker, bookmaker_key, is_sa_bookmaker, ev, confidence, sharp_prob, stake, potential_return, profit, all_odds, confidence_label`

### Odds Caching (`scripts/odds_client.py`)
- File-based JSON cache in `data/odds_cache/` with 30-minute TTL
- `fetch_odds_cached(sport_key, regions, markets, odds_format)` → `{ok, data, error}`
- Cache key format: `odds_{sport_key}_{markets}.json`
- Handles quota exhaustion gracefully (returns error dict)
- Keeps API usage within 500 requests/month free tier

### Sharp Bookmaker Probability
Engine prefers sharp book lines for "true" probability estimation:
- **Sharp books**: Pinnacle (`pinnacle`), Betfair Exchange (`betfair_ex_eu`), Matchbook (`matchbook`)
- **Fallback**: Vig-removed consensus from all bookmakers (same as `fair_probabilities()`)
- Sharp lines are devigged to sum to 1.0 before EV calculation

### Sports Data Service (`scripts/sports_data.py`)
- **File caching**: JSON files in `data/sports_cache/` with configurable TTL (24h sports, 12h teams)
- `fetch_available_sports()` → grouped dict from Odds API `/sports`
- `fetch_teams_for_sport(sport_key)` → team list from Odds API events
- `get_top_teams_for_sport(group, sport_key, limit)` → API first, curated fallback
- `CURATED_LISTS` — ~15 sport keys with fallback team/player lists
- `ALIASES` — ~100+ lowercase nickname → canonical name mappings (incl. EPL full squads, SA PSL slang)
- `fuzzy_match_team(input, known_names)` → top 3 matches with confidence scores
- `fetch_events_for_league(league_key)` → upcoming events from Odds API `/events` endpoint (free, 2hr cache)

## Persistent Menu System
Main menu: `kb_main()` → Daily Briefing | My Bets | My Teams | Stats | Schedule | Bookmakers | Settings

Sub-menus: `kb_bets()`, `kb_teams()`, `kb_stats()`, `kb_bookmakers()`, `kb_settings()`
Every sub-screen has "🔙 Back" + "🏠 Main Menu" via `kb_nav()`.

## Schedule Feature
`/schedule` command or "📅 Schedule" button shows upcoming games for user's followed teams.
- `cmd_schedule()` — Entry point for /schedule command
- `_build_schedule()` — Shared logic for command + callback. Fetches events per league via `fetch_events_for_league()`, filters to user's teams, formats with kick-off times (SAST). Returns (text, markup).
- `_generate_game_tips()` — AI tips per game using `fair_probabilities()` and `find_best_odds()` from odds_client. Triggered by "Get Tips" button (`schedule:tips:{event_id}`).
- Shows "No upcoming games found" if no matches for followed teams.

## Betting Story / Notification Preferences
Multi-step notification quiz presented after onboarding or accessible via Settings → "📖 My Notifications".

### Story quiz state
`_story_state[chat_id]` dict with `step` (0-4) and `prefs` dict. Steps iterate through `STORY_STEPS` list.

### 5 notification types
| Key | Default | Description |
|-----|---------|-------------|
| daily_picks | on | Morning value bet picks |
| game_day_alerts | on | Pre-match alerts for followed teams |
| weekly_recap | on | Weekly performance summary |
| edu_tips | on | Betting education tips |
| market_movers | off | Line movement alerts |

### Settings integration
Settings → "📖 My Notifications" shows toggle buttons for each notification type with on/off emoji indicators.

## Profile Summary
`format_profile_summary(user_id)` — Reusable async helper that formats a clean profile display. Used in `settings:home` and onboarding summary. Shows experience, sports grouped by league with teams, risk profile, and notification time.

## Experience-Adapted Pick Cards
`format_pick_card(pick, index, experience)` in `scripts/picks_engine.py`:
- **Experienced**: compact stats — odds, EV%, Kelly stake, stake→return with profit
- **Casual**: narrative — "We like X", explained odds, R100 payout illustration
- **Newbie**: full hand-holding — bet type explained, payout in R20/R50, "Start small" advice

Legacy `format_pick_card(pick)` in `scripts/odds_client.py` still used for ValueBet objects in test suite.

## Conventions
- HTML parse_mode throughout all messages
- PTB v20+ async handlers
- Inline keyboards only (no reply keyboards)
- Max 2 buttons per row for mobile
- `prefix:action` callback_data routing in `on_button()`
- Loading messages use randomised verb templates
- Sport-appropriate language via `fav_type` field

## Verification
```bash
# Run unit tests (277 tests)
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
1. **Onboarding Flow** — /start, experience, sports, leagues, teams, risk, notify, summary, edit, confirm
2. **Post-Onboarding** — all commands respond, settings menu, back buttons, HTML formatting
3. **Profile Reset** — warning screen, confirm reset, re-onboarding
4. **Fuzzy Matching** — typos ("Arsnal"), aliases ("gooners"), SA slang ("amakhosi")
5. **Edge Cases** — zero sports, /start when onboarded, random text, rapid commands

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
