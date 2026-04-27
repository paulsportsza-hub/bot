# MzansiEdge — CLAUDE.md

## ⛔ CRITICAL — FIX ROOT CAUSES, NOT SYMPTOMS
When you encounter a bug, error, or unexpected behaviour — trace it back to
the root cause and fix it there. Do NOT patch over symptoms with workarounds,
band-aids, or surface-level fixes. If you're not sure what the root cause is,
investigate until you find it. Every fix must address WHY the problem happened,
not just WHAT went wrong.

## Overview
AI-powered sports betting Telegram bot for South Africa. Uses python-telegram-bot v20+ (PTB), Claude API for AI tips, The Odds API for live odds, and async SQLAlchemy for persistence.

## Architecture

```
bot.py              ← Main bot: handlers, onboarding, picks, callback routing (Telegram-specific)
config.py           ← Environment config, sport/league definitions, TOP_TEAMS, TEAM_TO_LEAGUES, NATIONAL_TEAM_LEAGUES, SPORT_EXAMPLES, aliases, risk profiles, SA_BOOKMAKERS (dict-of-dicts), TEAM_ABBREVIATIONS
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
    fav_type: str     # "team" / "player" / "fighter" / "skip"
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

### 4 Sport Categories (Phase 0C — updated leagues)
| Category | fav_type | Leagues |
|----------|----------|---------|
| soccer | team | Premier League, PSL, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, MLS |
| rugby | team | International Rugby, URC, Super Rugby, Currie Cup, Six Nations, Rugby Championship |
| cricket | team | CSA/SA20, Test Matches, ODIs, T20 Internationals, IPL, Big Bash, T20 World Cup |
| combat | fighter | Major Bouts (boxing), UFC Events (mma) |

### Lookup maps (auto-generated from SPORTS)
- `ALL_SPORTS` — category key → SportDef
- `ALL_LEAGUES` — league key → LeagueDef
- `LEAGUE_SPORT` — league key → category key
- `SPORTS_MAP` — league key → api_key (only leagues with API keys)

### TOP_TEAMS dict
`config.TOP_TEAMS[league_key]` → list of top teams/players for that league. Used for multi-select buttons in onboarding favourites step. ~20 league keys.

### TEAM_TO_LEAGUES dict (Phase 0D)
`config.TEAM_TO_LEAGUES[team_name]` → list of league keys. Auto-generated by inverting `TOP_TEAMS`. Used by `user_service._infer_leagues_for_team()` to auto-infer leagues from team names during onboarding persistence. e.g. `"Arsenal": ["epl"]`, `"Bulls": ["urc", "currie_cup"]`.

### NATIONAL_TEAM_LEAGUES dict (Phase 0D)
`config.NATIONAL_TEAM_LEAGUES[sport_key][team_name]` → list of league keys. Sport-aware national team mapping for teams that appear across both rugby AND cricket (e.g. "South Africa", "England"). Used by `_infer_leagues_for_team()` with priority over `TEAM_TO_LEAGUES`. e.g. `NATIONAL_TEAM_LEAGUES["rugby"]["South Africa"] = ["international_rugby", "rugby_champ"]`.

### SPORT_EXAMPLES dict (Phase 0D)
`config.SPORT_EXAMPLES[sport_key]` → example string for per-sport team prompts in onboarding. 4 entries, one per sport category. Replaces per-league `LEAGUE_EXAMPLES` in onboarding. e.g. `"soccer": "e.g. Chiefs, Arsenal, Barcelona, Sundowns"`. `LEAGUE_EXAMPLES` still exists for settings team editing.

### TEAM_ALIASES dict
`config.TEAM_ALIASES[lowercase_alias]` → canonical name. ~100 aliases. Used for fuzzy matching during manual favourite input. Covers EPL nicknames (gunners, red devils, sky blues, reds, toffees), SA PSL slang (glamour boys, usuthu, masandawana), La Liga (los blancos, blaugrana), Rugby (bokke, les bleus), Boxing (canelo, tank, fury), Cricket (proteas, blackcaps, windies), MMA (poatan, stillknocks).

### LEAGUE_EXAMPLES dict
`config.LEAGUE_EXAMPLES[league_key]` → example string for team input prompts. ~25 entries (e.g. `"epl": "e.g. Arsenal, Liverpool, Man City"`). Used in settings team editing to show league-specific placeholder text.

### TEAM_ABBREVIATIONS dict
`config.TEAM_ABBREVIATIONS[team_name]` → short abbreviation. ~40 entries (e.g. `"Arsenal": "ARS"`, `"Kaizer Chiefs": "KC"`, `"Real Madrid": "RMA"`). Used for compact button display in schedule view.

### abbreviate_team()
`config.abbreviate_team(name, max_len=3)` → abbreviation from `TEAM_ABBREVIATIONS` dict with fallback to first 3 chars uppercased.

### fav_type helpers
- `config.fav_label(sport)` → "favourite team" / "favourite player" / "favourite fighter"
- `config.fav_label_plural(sport)` → plural form

### SPORT_DISPLAY dict (Odds API group mapping)
`config.SPORT_DISPLAY[group]` → `{"emoji": "⚽", "entity": "team", "entities": "teams"}`. Maps Odds API group names (Soccer, Boxing, etc.) to display config. 6 groups.

### SA_PRIORITY_GROUPS list
Ordered SA-first display: Soccer → Rugby Union → Cricket → Boxing → Mixed Martial Arts

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
- `ob_nav:sports_done` / `ob_nav:back_sports` — Navigation
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

## QA Harness (BUILD-QA-HARNESS-01 — 2026-04-17)
- `qa_profiles` (9 cols) + `qa_command_log` (7 cols) tables in `mzansiedge.db`
- 12 synthetic personas P01–P12 seeded via `scripts/create_qa_tables.py` (safe to re-run, INSERT OR IGNORE)
- `/qa profile list|<id>` — read-only profile inspection
- `/qa teaser <id>` — renders teaser HTML + digest PNG → `/tmp/qa/<id>/teaser_<ts>.*`
- `/qa digest_image <id>` — renders digest card PNG → `/tmp/qa/<id>/digest_<ts>.png`
- `/qa card_image <id> <match_id>` — renders match card PNG → `/tmp/qa/<id>/card_<ts>.png`
- All harness commands logged to `qa_command_log` with `duration_ms`
- Admin-only gate: non-admin gets "unauthorized"
- BUILD-QA-HARNESS-02 will add the capture-engine (screenshot + structured diff) on top of this foundation

## Onboarding Quiz Flow (5 steps — Phase 0D)
1. **Step 1: Experience level** — Experienced / Casual / Newbie
2. **Step 2: Sports selection** — Category-based grid (Soccer, Rugby, Cricket, Combat Sports)
3. **Step 3: Teams per sport** — One text prompt per selected sport. User types comma-separated team/player names with fuzzy matching. Max 5 per sport. Sport-appropriate language (team/player/fighter). Iterates `ob["selected_sports"][ob["_fav_idx"]]`. Uses `config.SPORT_EXAMPLES[sport_key]` for placeholder text. Shows ALL teams for that sport across all leagues via `_get_all_teams_for_sport()`. Per-team celebration lines with sport-context-aware emojis.
4. **Edge Explainer** (unnumbered) — "How Your Edge Works" screen explaining Edge-AI system. Experienced users skip this step.
5. **Step 4: Preferences** — Combined risk + bankroll + notify. Risk: Conservative / Moderate / Aggressive. Bankroll: R500/R1000/R2000/R5000 + skip + custom. Notify: 7 AM / 12 PM / 6 PM / 9 PM.
6. **Step 5: Summary** — Clean profile display with flat team lists per sport, bankroll display, edit buttons: "Edit Sports & Teams" and "Edit Preferences". Confirm with "Let's go!"

**No league selection step.** Users think in teams, not leagues. Leagues are auto-inferred during persistence via `user_service._infer_leagues_for_team()`.

### Favourites data structure (Phase 0D — flat lists)
`ob["favourites"]` is a flat dict: `{sport_key: [team_names...]}`. e.g. `{"soccer": ["Arsenal", "Kaizer Chiefs"], "rugby": ["South Africa", "Bulls"]}`. During `persist_onboarding()`, leagues are auto-inferred using `TEAM_TO_LEAGUES` (filtered by sport) and `NATIONAL_TEAM_LEAGUES` (sport-specific national team disambiguation). Saved to DB as one `UserSportPref` row per team per inferred league.

### Auto-league inference (user_service.py)
`_infer_leagues_for_team(team, sport_key)`:
1. Check `NATIONAL_TEAM_LEAGUES[sport_key][team]` first (sport-specific)
2. Check `TEAM_TO_LEAGUES[team]` filtered by `LEAGUE_SPORT[lg] == sport_key`
3. Returns empty list if no mapping found → saved without league key

### Post-onboarding: Welcome message + Edge Alerts quiz
All experience levels get the same welcome message with a CTA to "Set Up Edge Alerts" or "Skip for Now". The quiz walks through 6 notification types (daily_picks, game_day_alerts, weekly_recap, edu_tips, market_movers, live_scores) with Yes/No for each, saved as JSON in `User.notification_prefs`.

### Archetype classification (on onboarding completion)
`services.user_service.classify_archetype(experience, risk, num_sports)` → `(archetype, engagement_score)`:
- **complete_newbie**: experience="newbie" → score 3.0
- **eager_bettor**: experienced + aggressive/moderate → score 8-10
- **casual_fan**: everyone else → score 5-7

Saved to `User.archetype` and `User.engagement_score` via `db.update_user_archetype()`.

### Fuzzy matching (text-based team input)
Two fuzzy matching systems:
1. **bot.py `_handle_team_text_input()`**: Processes comma-separated team names. Pipeline: sport-label detection → alias lookup (sports_data.ALIASES + config.TEAM_ALIASES) → `difflib.get_close_matches` against all teams for sport (`_get_all_teams_for_sport()`) then all alias targets. Shows per-team celebration lines with Continue/Try Again buttons. Sport-specific error tips using `config.SPORT_EXAMPLES` when no match.
2. **scripts/sports_data.py**: `thefuzz` (Levenshtein) against dynamic/curated lists. Pipeline: exact → alias → fuzzy → substring. Returns top 3 with confidence scores.

State tracked in `bot._onboarding_state[user_id]` dict with `_team_input_sport`, `_fav_idx` keys. No `_team_input_league` or `_fav_league_queue` (removed in Phase 0D).

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
`HOT_TIPS_SCAN_SPORTS` is a list of ~16 Odds API sport keys covering soccer, rugby, cricket, MMA, boxing. Tips are scanned across all 4 core sports (not just user's preferences).

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

## NOTIFICATION CONTENT LAWS (LOCKED — 4 March 2026)

1. **NO WIN GUARANTEES.** Never "guaranteed winner" or "sure bet." Use "edge," "value," "expected value."
2. **SHOW LOSSES WITH SAME PROMINENCE AS WINS.** Every result notification includes season accuracy. Loss messages go out same as wins.
3. **NO AGGRESSIVE CTAs AFTER LOSING STREAKS.** 3+ consecutive misses → suppress upgrade CTAs for 48 hours. Replace with educational/transparency messaging.
4. **QUIET CONFIDENCE TONE.** Let numbers speak. No exclamation-heavy hype. One emoji per message section maximum.
5. **RESPONSIBLE GAMBLING FOOTER.** "Bet responsibly. 18+ only." in monthly reports, trial messages, and re-engagement nudges. Not on every alert.
6. **TRANSPARENCY IN LOSSES.** "The market was right on this one" — never hide or minimise a miss. This IS our competitive advantage.

## Verification

### Safe QA Runner (MANDATORY — QA-SAFE-1)
All test runs MUST use `scripts/qa_safe.sh`. Direct `pytest` invocations are
blocked by a Claude PreToolUse hook. The safe wrapper enforces:
- Exclusive flock — only ONE test run at a time (prevents swarm starvation)
- 5-minute wall-clock timeout (override: `QA_TIMEOUT=600`)
- nice +15 / ionice idle — lowest CPU/IO priority (protects live bot + scrapers)
- 30-second per-test timeout via pytest-timeout

```bash
# Full unit suite (bounded, fail-fast)
bash scripts/qa_safe.sh

# Layer-specific runs
bash scripts/qa_safe.sh contracts        # Layer 1: contract tests
bash scripts/qa_safe.sh edge_accuracy    # Layer 2: edge accuracy
bash scripts/qa_safe.sh accuracy         # Layer 3: historical accuracy
bash scripts/qa_safe.sh snapshots        # Layer 4: snapshot tests
bash scripts/qa_safe.sh e2e             # Layer 5: E2E user journeys

# Wave Completion Gate (Layers 1-4)
bash scripts/qa_safe.sh gate

# Specific test file
bash scripts/qa_safe.sh tests/test_config.py

# Pass extra pytest args after --
bash scripts/qa_safe.sh contracts -- -k "test_foo" -v

# Verbose mode
QA_VERBOSE=1 bash scripts/qa_safe.sh contracts

# Start the bot
python bot.py

# Pre-merge gate (also flock-protected)
bash scripts/pre_merge_check.sh
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
- Config: PROJECT = "MzansiEdge", CANONICAL_AGENTS = ["Opus Max Effort - COO", "Opus Max Effort - AUDITOR", "Opus Max Effort - LEAD", "Opus - COO", "Opus - AUDITOR", "Opus - LEAD", "Sonnet - COO", "Sonnet - AUDITOR", "Sonnet - LEAD"], NOTION_DB_ID = "a7cd424d700a4ab684ec10bd08c9948b"

### Environment Variables (set in /etc/environment AND ~/.bashrc)
    NOTION_TOKEN=(set in ~/.bashrc — do not commit)
    NOTION_DB_ID=a7cd424d700a4ab684ec10bd08c9948b

### ⛔ NOTION TOKEN VALIDATION — ALWAYS CHECK BEFORE PUSHING
Before running push-report, verify the token is live:
    curl -s https://api.notion.com/v1/users/me -H "Authorization: Bearer $NOTION_TOKEN" -H "Notion-Version: 2022-06-28" | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('object')=='user' else 'INVALID: '+d.get('message',''))"
If INVALID: token has been rotated. Ask Ops Hub for the current NOTION_TOKEN and update:
    sed -i 's|NOTION_TOKEN=".*"|NOTION_TOKEN="<new>"|' ~/.bashrc
    sudo sed -i 's|NOTION_TOKEN=.*|NOTION_TOKEN=<new>|' /etc/environment
    export NOTION_TOKEN="<new>"
The push-report script silently returns ✅ even on auth failure — always verify with curl first.

### Usage
    push-report --agent "Sonnet - AUDITOR" --wave 9A /home/paulsportsza/reports/qa-wave9a-20260225-1527.md
    push-report --agent "Sonnet - LEAD" --wave 9B --status "Action Taken" --title "Merge Complete" report.md

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

### Edge Rating Tiers (Diamond System — Phase 0D-FIX)
| Tier | Display Name | Emoji | EV Threshold | Score Threshold |
|------|-------------|-------|-------------|-----------------|
| Diamond | DIAMOND EDGE | 💎 | ≥15% | 85%+ |
| Gold | GOLDEN EDGE | 🥇 | ≥8% | 70%+ |
| Silver | SILVER EDGE | 🥈 | ≥4% | 55%+ |
| Bronze | BRONZE EDGE | 🥉 | ≥1% | 40%+ |
| Hidden | — | — | <1% | Below 40% — NOT shown to users |

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

## Wave 15A — AI Post-Processor + Odds CTA Fix (26 Feb 2026)

**AI Post-Processor (Wave 15A):** New `sanitize_ai_response()` function runs on ALL AI-generated content. Strips markdown headers, enforces section spacing, converts markdown bold to HTML, normalises whitespace, strips conviction text. Applied to Game Breakdown and Tip Narrative. Eliminates formatting inconsistency permanently.

**Odds Comparison 3-CTA (Wave 15A):** Fixed BUG-026 — now renders one affiliate CTA per market (Home/Draw/Away), each pointing to the best-odds bookmaker for that outcome. Root cause: GBets and Hollywoodbets were missing from `BOOKMAKER_AFFILIATES` and `SA_BOOKMAKERS` config dicts, so `get_affiliate_url()` returned empty → CTA buttons skipped.

### BUG-026: Odds Comparison 3-CTA
- Added `gbets` to `BOOKMAKER_AFFILIATES` and `SA_BOOKMAKERS` in config.py
- Added `hollywoodbets` to `SA_BOOKMAKERS` in config.py
- All 5 scraped bookmakers now have affiliate URL fallbacks → all CTA buttons render

### BUG-027 + BUG-028: AI Post-Processor
- `sanitize_ai_response(raw_text)` in bot.py — deterministic post-processor
- Strips: markdown headers (#/##/###), duplicate match titles, markdown bold (**), stray emphasis (*/_), conviction text
- Converts: markdown bullets to •, markdown bold to HTML `<b>`
- Enforces: section spacing (blank line before 📋🎯⚠️🏆💰), section header bold, max 1 blank line
- Applied after Claude response in `_generate_game_tips()`, replaces old conviction-only stripping
- Claude prompt updated with strict FORMATTING RULES section
- `import re` moved to top-level (was local imports)

### Test Status (Wave 15A)
- Tests: 335 passing (11 new), 0 failures

## Wave 15B — Sport Filter + Bookmaker Directory (26 Feb 2026)

**Sport Filter Inline (Wave 15B):** BUG-029 fixed — sport emoji buttons on Your Games now re-render the same message filtered to that sport. No separate screen. Day picker persists. "All" button removes filter. `_render_your_games_all()` now accepts `sport_filter` param. `_build_sport_filter_row()` helper for filter buttons.

**Multi-Bookmaker Directory (Wave 15B):** FIX-001 — bookmaker page now shows all 5 SA bookmakers with taglines and affiliate sign-up buttons. Single-bookmaker "Recommended" page replaced. `SA_BOOKMAKERS_INFO` dict added to bot.py with name/emoji/tagline per bookmaker.

### BUG-029: Sport Filter Inline Re-render
- `_render_your_games_all(user_id, page, sport_filter)` — sport_filter param filters games by sport_key
- Callback routing: `yg:sport:{key}` now calls `_render_your_games_all` with sport_filter (not separate handler)
- Pagination preserves filter: `yg:all:{page}:{sport_filter}`
- `_build_sport_filter_row()` — active sport bracketed, "All" button when filtered
- Empty state inline: "No {sport} games scheduled."
- Old `_render_your_games_sport()` is now dead code (retained for reference)

### FIX-001: Multi-Bookmaker Directory
- `SA_BOOKMAKERS_INFO` dict: 5 bookmakers with name, emoji, tagline
- `handle_affiliate()` renders all 5 bookmakers with taglines
- `kb_bookmakers()` generates one sign-up CTA button per bookmaker via `get_affiliate_url()`
- Menu button "🎰 Bookmakers" routes to `affiliate:compare`

### Test Status (Wave 15B)
- Tests: 342 passing (7 new), 0 failures

## Wave 16A — Broadcast Display on Event Cards (26 Feb 2026)

**Broadcast Display (Wave 16A):** All three main event screens now show DStv broadcast info. `_get_broadcast_line()` helper wraps the Dataminer's `get_broadcast_info()` (sync function from scrapers/broadcast_scraper.py). Pre-formatted display like "📺 SS EPL (DStv 203)" with free-to-air option appended when available.

### `_get_broadcast_line()` Helper
- Wraps `scrapers.broadcast_scraper.get_broadcast_info()` (sync, no async needed)
- Parameters: home_team, away_team, league_key, match_date
- Returns pre-formatted `display` string or empty string on failure
- 3-tier lookup: team match → league fallback → `LEAGUE_DEFAULT_CHANNELS` static default
- DB: `/home/paulsportsza/scrapers/odds.db` table `broadcast_schedule`

### Screens Updated
1. **Hot Tips** — broadcast line appended below league/kickoff line: `     📺 SS EPL (DStv 203)`
2. **Your Games** — broadcast line below each match: `     📺 SS PSL (DStv 202)`
3. **Game Breakdown** — broadcast line in header between kickoff and AI narrative

### Hot Tips `league_key` Field
- Hot tips from DB now include `league_key` (raw key like "psl") alongside display `league` ("PSL")
- Required for broadcast lookup which takes league_key not display name

## Wave 16B — Zero Hallucination Prompt System (26 Feb 2026)

**Verified Context (Wave 16B):** AI game breakdown now receives verified ESPN/Jolpica data as a VERIFIED_DATA section in the Claude prompt. Claude is instructed to use ONLY these facts for standings, form, H2H — never invent stats. Post-generation `validate_sport_context()` strips wrong-sport terminology. `fact_check_output()` removes fabricated league positions that contradict verified data.

### `_format_verified_context(ctx_data)`
- Converts `get_match_context()` dict into structured text block for Claude prompt
- Includes: league positions, points, W/D/L record, form (last 5), goals/game, head-to-head
- Returns empty string if `data_available: False`
- Data sources: ESPN (soccer/rugby), Jolpica (F1)

### `validate_sport_context(narrative, sport)`
- Post-processor that strips sport-inappropriate terms
- Soccer terms banned in rugby: "clean sheet", "penalty kick", "corner", "offside trap"
- Rugby terms banned in soccer: "try line", "lineout", "scrum", "ruck", "maul"
- Removes entire sentences containing wrong-sport terminology

### `fact_check_output(narrative, ctx_data)`
- Checks AI claims about league positions against verified data
- Pattern matching: "sit 3rd", "currently 5th", "ranked 2nd" etc.
- If claimed position contradicts verified position for named team, line is stripped
- No-op when no verified context available

### GAME_ANALYSIS_PROMPT Update
- Added VERIFIED DATA RULES section between Verdict and FORMATTING RULES
- Claude instructed to use ONLY verified data for standings/form/H2H
- If no VERIFIED DATA provided, keep analysis general — say "form data unavailable"
- May mention team reputation but must NOT cite specific stats without verified source

### `_generate_game_tips()` Changes
- Fetches verified context via `get_match_context()` (async) before Claude call
- Normalises team names to underscore format for ESPN lookup
- Injects VERIFIED_DATA block into user message when available
- Post-processing pipeline: `sanitize_ai_response()` → `validate_sport_context()` → `fact_check_output()`
- Graceful degradation: if context fetch fails, proceeds with odds-only analysis

### Test Status (Wave 16A+16B)
- Tests: 354 passing (12 new), 0 failures

## Wave 17B — Watertight Factual Accuracy (26 Feb 2026)

**Watertight Prompt (Wave 17B):** Claude prompt CRITICAL RULES completely rewritten. ALL factual claims must come from VERIFIED_DATA or ODDS DATA — not just statistics but also names, venues, history, tactics. Post-generation fact checker expanded to catch: unverified person names, historical claims, tactical descriptions, venue references, condition claims, and wrong-sport terms. `sport_terms.py` integrated. Sport type now explicit in every prompt. Offending sentences stripped automatically with logging.

### `_build_game_analysis_prompt(sport)` (replaces static `GAME_ANALYSIS_PROMPT`)
- Dynamic function parameterised by sport type ("soccer", "cricket", "rugby", "f1")
- Header: `SPORT: {sport}` + "You are analysing a {sport} match"
- CRITICAL RULES section bans: person names, historical claims, tactical descriptions, venue names, injuries/transfers, weather/conditions, "historically"/"traditionally"/"known for"
- WHAT YOU CAN USE: VERIFIED_DATA, ODDS DATA, own analytical reasoning only
- THE GOLDEN RULE: "If you cannot point to the exact field in VERIFIED_DATA or ODDS DATA that supports a claim, DO NOT MAKE THAT CLAIM"

### Expanded `fact_check_output(narrative, ctx_data)`
- Strips fabricated league positions (existing, unchanged)
- Strips historical claims: "historically", "traditionally", "known for", "dating back to", etc.
- Strips tactical/style descriptions: "counter-attack", "possession-based", "high press", "gegenpressing", etc.
- Strips condition references: "weather", "fixture congestion", "rotation", "altitude", etc.
- Strips unverified person names: detects capitalised proper nouns not in verified_names set
- All stripping logged via `log.warning()` for monitoring
- Verified team names preserved (both full name and individual words >3 chars)

### `validate_sport_context()` — Now Powered by `sport_terms.py`
- Replaced hardcoded wrong_terms dict with `SPORT_BANNED_TERMS` from `scrapers/sport_terms.py`
- Cricket: 33 banned terms (includes "african football", "continental heavyweight", "league table")
- Rugby: 31, Soccer: 30, F1: 24 banned terms
- Logging on every stripped term for monitoring

### Test Status (Wave 17B)
- Tests: 364 passing (10 new), 0 failures

## Wave 17E — Prompt Rebalance + Enriched Narrative (27 Feb 2026)

**Prompt Rebalance (Wave 17E):** CRITICAL RULES rewritten to split FACTUAL CLAIMS (absolute, locked to VERIFIED_DATA) from NARRATIVE & OPINION (encouraged, use freely). Claude now explicitly told to reference coaches/players by name from VERIFIED_DATA, describe form momentum using actual results, build narrative tension from H2H. Banned sport terms injected directly into prompt. Setup section must never be empty.

### `_build_game_analysis_prompt(sport, banned_terms)` (updated)
- Now accepts `banned_terms` parameter — sport-specific banned terms injected into prompt text
- FACTUAL CLAIMS section: zero exceptions, facts only from VERIFIED_DATA or ODDS DATA
- NARRATIVE & OPINION section: ENCOURAGED — opinions, predictions, personality, conviction
- SPORT VALIDATION section: shows banned terms for current sport
- TONE section: sharp SA sports analyst at a braai, punchy, "lekker" sparingly
- Setup section instruction: "MUST reference verified standings" (never say "form data unavailable")

### Enriched `_format_verified_context(ctx_data)` (updated)
- Now includes ALL enrichment fields from `get_match_context()`:
  - Venue, coaches, top scorers (name + goals), key players (rugby)
  - Home/away records, goals for/against, formations, starting XI lineups
  - Last 5 results with scores + opponents + H/A (from `last_5` list)
  - H2H with league tags
  - Rugby: tries for/against, bonus points, points differential
  - Cricket: wins/losses/NR/tied, NRR, runs for/against
  - F1: constructor standings, last race with top 5 results + circuit

### `fact_check_output(narrative, ctx_data)` (simplified)
- Removed _HISTORY_PATTERNS, _STYLE_PATTERNS, _CONDITION_PATTERNS (narrative now encouraged)
- Keeps: fabricated position detection, unverified person name detection
- Verified names now include: coaches, top scorers, key players, F1 drivers (from ctx_data)
- Person name check uses `any()` instead of `all()` for word matching (fixes "Under Nabi" false positive)

### `_ensure_setup_not_empty(output, ctx_data)` (NEW)
- Post-processor that detects thin Setup section (< 60 chars)
- Injects fallback from verified standings: position, points, form, coach
- Ensures Setup section always has meaningful content when verified data exists

### Prompt builder wiring
- `_generate_game_tips()` fetches `SPORT_BANNED_TERMS` and passes to `_build_game_analysis_prompt()`
- Post-processing pipeline: sanitize → validate_sport → fact_check → ensure_setup_not_empty

### Test Status (Wave 17E)
- Tests: 378 passing (14 new), 0 failures

## Phase 0B — Straggler Fixes + Onboarding UX Polish (27 Feb 2026)

**Part A — QA Stragglers (6 fixes):**
- STRAGGLER-001: Removed "Formula 1": "F1" and "Grand Slams": "Slams" from `_LEAGUE_ABBREV`
- STRAGGLER-002: Changed "NBA" → "URC" in keyless league suggestion text
- STRAGGLER-003: Removed F1/Jolpica references from docstrings (ESPN/Jolpica → ESPN)
- STRAGGLER-004: Removed "Tennis" from `sports_data.py` docstring example
- STRAGGLER-005: Replaced Tennis/Boxing E2E tests with Cricket/Combat equivalents
- STRAGGLER-006: Removed "Grand Slams" abbreviation (tennis league)

**Part B — Onboarding UX Polish (10 items):**

### "Top Edge Picks" Rebrand (was "Hot Tips")
- Sticky keyboard: "🔥 Hot Tips" → "💎 Top Edge Picks"
- All inline buttons, headers, help text updated
- `_LEGACY_LABELS` maps old "🔥 Hot Tips" → `hot_tips` for cached keyboards
- Regex pattern in `main()` includes both old and new labels
- Internal function names unchanged (hot_tips, _do_hot_tips_flow etc.)

### "Edge Alerts" Rebrand (was "Your Betting Story")
- Welcome message: "Your Betting Story" → "Edge Alerts"
- "Set Up My Story" → "Set Up Edge Alerts"
- "Your Story is Set!" → "Edge Alerts — All Set!"
- Settings button: "📖 My Notifications" → "🔔 Edge Alerts"
- "Show Me Hot Tips" → "💎 Top Edge Picks" post-story completion

### "Edge-AI" Branding
- Help text: "AI edge markers" → "Edge-AI markers"
- Help text: "How tips work" → "How the Edge works"
- Welcome message: "AI edge indicators" → "Edge-AI indicators"
- Edge explainer: "our AI compares" → "Our Edge-AI scans"

### Start Again Button
- Added "🔄 Start Again" (`ob_nav:restart`) to risk, bankroll, and notify keyboards
- `handle_ob_nav` handles `restart` action: clears state, restarts from experience step
- Keyboard functions now return Back + Start Again side by side

### Edge Rating Explainer Rewrite
- New copy emphasises Edge-AI and SA flavour ("lekker", "The bookies got this wrong")
- Pro tip footer: "Focus on 💎 Diamond and 🥇 Gold"
- Title: "How Your Edge Works" (was "Understanding Your Edge")

### Claude Haiku Personalised Welcome
- `handle_ob_done()` calls Claude Haiku (`claude-haiku-4-5-20251001`) for 2-sentence welcome
- Prompt includes: user name, sports, experience level, SA flair instructions
- Graceful fallback on API failure (empty string, no crash)
- Welcome text italicised below main message

### Animated Sport Emoji Spinner (Phase 0B-FIX)
- `SPORT_EMOJIS = ["⚽", "🏉", "🏏", "🥊"]`, `DOTS = [".", "..", "..."]`
- `_run_spinner(message, text, stop_event)` — async loop edits message every 0.5s with rotating emoji + dots
- Pattern: send/edit loading msg → `asyncio.create_task(_run_spinner(...))` → do work in try/finally → `stop_event.set()` → replace with result
- Applied to: Hot Tips, picks, game analysis, AI odds analysis

### Team-Aware Celebrations (Phase 0C, Fix 5)
- `TEAM_CELEBRATIONS` dict: 60+ team-specific celebrations with team-identity emojis (not sport emojis)
- `_SPORT_CELEBRATIONS` dict: sport-specific overrides for national teams appearing in multiple sports (e.g. "South Africa" in cricket → "Protea Fire!", in soccer → "Bafana Bafana!", in rugby → "Go Bokke!")
- `_SPORT_CHEERS_FALLBACK` dict: sport-level fallback when team not in either dict
- `_get_team_cheer(team, sport_key)` — checks sport-specific overrides first, then generic celebrations, then fallback
- Confirmation format: sport emoji header ("⚽ Nice picks!"), per-team celebration lines, neutral summary ("3 teams added.")
- No repeated celebration in summary line, no repeated emoji
- SA PSL teams use SA cultural names (Amakhosi, Masandawana, Usuthu)
- EPL teams use real chants (YNWA, COYS, Glory Glory)
- Entity label uses sport-appropriate term (team/fighter)

### Enhanced Aliases
- Added ~20 new aliases in `config.TEAM_ALIASES`:
  - MMA typos: "drikus", "du plessis", "pereira", "holloway", "omalley", "islam", "makhachev"
  - SA slang: "amakhosi", "khosi", "buccaneers", "bucs", "masandawana", "downs"
  - EPL common: "gooners", "gunners", "the reds", "pool", "man u", "man c", "chelsea fc"
  - Rugby: "stormers", "bulls", "sharks", "lions"

### Test Status (Phase 0B)
- Tests: 384 passing (11 new), 0 failures

## Phase 0D-FIX — Onboarding + Edge Picks Polish (28 Feb 2026)

### FIX 1+4: Celebration Confirmation Format
- Every team gets its own celebration line: `✅ Team — Celebration! emoji`
- Sport emoji header: `⚽ Nice picks!` (combat: `🥊 War room loaded!`)
- Summary line neutral: `3 teams added.` — no repeated celebration, no emoji
- Team emojis are team-identity (🟡⚫ for Chiefs, 🔴😈 for Man United) not sport emojis

### FIX 2: Sport-Context Celebrations
- `_SPORT_CELEBRATIONS` dict added for national team overrides by sport
- "South Africa" in cricket → "Protea Fire! 🔥🏏" (not "Go Bokke!")
- "South Africa" in soccer → "Bafana Bafana! 🇿🇦"
- "South Africa" in rugby → "Go Bokke! 🇿🇦"
- `_get_team_cheer(team, sport_key)` checks sport overrides first

### FIX 3: Additional Combat Aliases
- Added to TEAM_ALIASES: "dreikus", "drikus du plessis", "du plesis", "duplessis", "stilknocks", "stillnocks" → Dricus Du Plessis

### FIX 5: Edge Explainer Rewrite
- First paragraph now sells the algorithm: "cross-references odds from 5+ SA bookmakers, live form data, historical performance, tipster consensus from 4 prediction sources, and real-time match conditions"
- Second paragraph: "When we spot a gap between what the bookies think and what our AI calculates, that's your Edge."

### FIX 6: Bankroll Amounts
- Changed from R500/R1,000/R2,000/R5,000 to R50/R200/R500/R1,000
- Both onboarding and settings bankroll keyboards updated

### FIX 7: Bold Experience Label
- Profile summary: `🎯 <b>Experience:</b>` (was missing bold tags)

### FIX 8: Remove Claude Haiku Welcome
- Removed Haiku API call from `handle_ob_done()` — welcome message ends after feature descriptions + CTA buttons

### FIX 9: Top Edge Picks Tier Formatting
- Tips grouped by Edge tier with bold headers: `💎 <b>DIAMOND EDGE</b>`, `🥇 <b>GOLDEN EDGE</b>`, etc.
- "GOLD EDGE" renamed to "GOLDEN EDGE" everywhere (EDGE_LABELS, explainer, guide, tests)
- Edge tier label removed from match line (was next to team names)
- Edge tier emoji added to end of odds line (💰 line) as visual tag
- Tips sorted by tier (diamond first), then EV descending within each tier
- Continuous numbering across tiers

### Test Status (Phase 0D-FIX)
- Tests: 408 passing, 0 failures

## Phase 0E — Game Time + Channel on Edge Pick Detail (28 Feb 2026)

### `_get_broadcast_details()` Helper (bot.py)
- Queries `broadcast_schedule` table in odds.db directly for upcoming matches (today + 7 days)
- Uses `fuzzy_match_broadcast()` from `broadcast_matcher.py` for team name matching
- Extracts `start_time` (full ISO timestamp) → formatted via `_format_kickoff_display()`
- Builds channel display from `channel_short` + `dstv_number`
- Includes free-to-air fallback
- Falls back to `_get_broadcast_line()` for league-level matches
- Returns `{"broadcast": "📺 SS PSL (DStv 202)", "kickoff": "Sat 1 Mar · 17:30"}`

### `render_tip_with_odds()` — New Optional Params (edge_renderer.py)
- `kickoff_override: str = ""` — pre-formatted kickoff string, takes priority over `match.commence_time`
- `broadcast_line: str = ""` — pre-formatted broadcast string
- League, kickoff, broadcast now on separate lines (was `🏆 League — kickoff` on one line)

### Tip Detail View (bot.py — `handle_tip_detail()`)
- Calls `_get_broadcast_details()` before `render_tip_with_odds()`
- Passes `kickoff_override` and `broadcast_line` to renderer
- Detail card now shows: edge badge, match header, league, 📅 kickoff, 📺 channel, best odds, narrative

### List View (bot.py — `_build_hot_tips_page()`)
- Replaced `_get_broadcast_line()` with `_get_broadcast_details()`
- Kickoff time for DB-sourced tips (odds.db has no commence_time) now populated from broadcast_schedule
- Format: `🏆 League · ⏰ kickoff` + `📺 channel` on next line

### Test Status (Phase 0E)
- Tests: 496 passing, 0 failures

## Phase 0F — Rename + Empty State + Bonus Leagues (28 Feb 2026)

### FIX 1: "Your Games" → "My Matches" Rename
- All user-facing strings changed: sticky keyboard, headers, buttons, help text
- Internal handler names unchanged (`your_games`, `_render_your_games_all`, etc.)
- `_LEGACY_LABELS` maps old `"⚽ Your Games"` → `"your_games"` for cached keyboards
- Regex pattern in `main()` includes both old and new labels
- Tests updated: test_bot_handlers.py, test_day1.py, test_e2e_flow.py

### FIX 2: Empty State Improvements
- **No live matches state** (`_render_your_games_all`): Shows "No live matches for your teams right now." + next 3 upcoming fixtures from broadcast_schedule + "Top Edge Picks" button
- **Schedule empty state**: Same pattern — next fixtures + Top Edge Picks button
- **`_get_next_fixtures_for_teams()`**: New helper querying broadcast_schedule for upcoming live broadcasts matching user's teams. Returns up to 3 fixtures with full league names, kickoff dates.
- Removed ALL "add a league" / "try adding a league" messages (league step removed in Phase 0D)

### FIX 3: National Team Bonus Leagues
- `config.NATIONAL_TEAM_BONUS_LEAGUES` — maps sport → national team → domestic franchise leagues
  - Rugby: SA→URC+Currie Cup, NZ/AU/ARG→Super Rugby, IRE/SCO/WAL/ITA→URC
  - Cricket: SA→CSA/SA20, India→IPL, Australia→Big Bash
- `_infer_leagues_for_team()` in user_service.py now appends bonus leagues after standard inference
- `backfill_bonus_leagues()` in user_service.py — retroactive migration for existing users
- Called at bot startup in `_post_init()` — scans all sport prefs, adds missing bonus league rows
- `db.get_all_sport_prefs()` helper added for migration queries

### Test Status (Phase 0F)
- Tests: 496 passing, 0 failures

## Wave 25 — Notification Conversion Engine + UX Polish (4 March 2026)

### Anti-Fatigue Engine (25A)
- `_can_send_notification(user_id)` — central gate for ALL proactive notifications. Checks mute status + daily push caps (bronze:3, gold:4, diamond:5).
- `_after_send(user_id)` — increments push count after successful send. Called in all 5 existing cron jobs + 2 new jobs.
- 6 new User columns: `last_active_at`, `nudge_sent_at`, `muted_until`, `daily_push_count`, `last_push_date`, `consecutive_misses`

### /mute Command (25A)
- `/mute` (default 24h), `/mute 48h`, `/mute week`, `/mute off` (unmute)
- Aliases: `/unmute`, `/quiet`
- `db.set_muted_until(user_id, until)` / `db.is_muted(user_id)`

### last_active_at Tracking (25A)
- `db.update_last_active(user_id)` called in `handle_keyboard_tap()` + `on_button()`
- Covers all user interactions (sticky keyboard + inline buttons)

### Re-engagement Nudge Job (25A)
- `_reengagement_nudge_job()` — runs hourly, acts at 18:00 SAST
- `db.get_inactive_users(hours=72, nudge_cooldown_days=7)` — inactive + cooldown query
- Lighter tone after 2 consecutive unanswered nudges (14+ days)
- Shows real settlement stats, never generic "come back!" messaging

### Spoiler Tag Fix (25B)
- `_build_hot_tips_page()` blurred section: actual bet data behind `<tg-spoiler>`, return amount visible, lock CTA visible
- Fixed in `_format_monday_recap()` similarly

### Portfolio Stat (25B)
- `get_top_10_portfolio_return(days)` in `settlement.py` — R100 stake on each top hit
- `_get_portfolio_line()` in bot.py — formatted portfolio line in 4 formatters

### Post-Match Result Alerts (25C)
- `user_edge_views` table: tracks which users viewed which edges (dedup on user+edge)
- `db.log_edge_view()`, `db.get_edge_viewers()`, `db.get_edges_viewed_by_user()`
- Edge view logging in `_do_hot_tips_flow()` + `handle_tip_detail()`
- `get_recently_settled_since(hours)` in settlement.py
- `_result_alerts_job()` — runs every 2h, tier-gated templates, bundling (>3), consecutive miss tracking, CTA suppression after 3+ misses

### Cron Jobs (9 total)
| Job | Interval | Description |
|-----|----------|-------------|
| morning_teaser | 1h | Morning tips at user's preferred hour |
| weekend_preview | 1h | Weekend preview Fri 18:00 SAST |
| monday_recap | 1h | Monday recap Mon 08:00 SAST |
| monthly_report | 1h | Monthly report 1st of month |
| trial_expiry | 1h | Trial expiry reminders |
| live_scores | 5min | Live score polling |
| broadcast_refresh | 12h | DStv broadcast data |
| reengagement_nudge | 1h | Re-engagement at 18:00 SAST **(NEW)** |
| result_alerts | 2h | Post-match result alerts **(NEW)** |

### Test Status (Wave 25)
- Tests: 649+ passing, 0 failures
- New test files: test_wave25a.py (9), test_wave25b.py (4), test_wave25c.py (7)

## Wave 26A — Mobile-First Hot Tips Redesign (5 March 2026)

### Law 9 (MOBILE FIRST)
Every screen scannable in 2-3 scrolls on 6-inch phone.

### Hot Tips Cards — 3-Line Compact Format
- 3 lines per card (was 7). No section headers, no per-card CTAs, no signal counts on list.
- 4 access levels: full (odds+return), partial (same as full), blurred (return only), locked (lock message only)
- `<tg-spoiler>` tags removed from blurred cards — replaced with return-only line.

### Footer CTA
- Single block for Bronze (locked count + portfolio + /subscribe), lighter for Gold (Diamond count), none for Diamond.
- Losing streak override: `consecutive_misses >= 3` → educational footer instead of upgrade CTA.
- `_build_hot_tips_page()` accepts `consecutive_misses: int = 0` parameter.

### Buttons
- 3-letter abbreviations via `config.abbreviate_team()` (not `_abbreviate_btn()`).
- 🔒 icon for locked edges → `sub:plans`. Tier emoji for accessible → `edge:detail:{match_key}`.
- 18 new `TEAM_ABBREVIATIONS` entries (SA PSL stragglers + cricket + rugby franchises).

### Locked Detail View
- `handle_tip_detail()`: blurred/locked edges show plan comparison (Diamond R199/mo, Gold R99/mo).
- No bookmaker link, no Compare Odds for locked edges.
- "Follow this game" button removed from accessible detail view.

### Bookmaker Deep Link Gating
- `_build_game_buttons()` accepts `user_tier` parameter.
- ALL screens gated by `get_edge_access_level()` — blurred/locked = no URL button, shows "View Plans" instead.
- Compare All Odds button only shown when at least one tip is accessible.

### Morning Teasers — 3 Distinct Templates
- **Bronze:** free picks list + locked count + upgrade CTA (gated by consecutive_misses)
- **Gold:** top pick + Diamond FOMO (yesterday's Diamond hit rate) + NO View Plans button
- **Diamond:** top pick + NO upgrade CTA + 2 buttons only

### /qa Commands Added
- `tips_bronze`, `tips_gold`, `tips_diamond` — triggers Hot Tips flow as specified tier

### Test Status (Wave 26A)
- Tests: 663 passing, 0 failures
- New test file: test_wave26a.py (14 tests)

## Wave 26A-FIX — Detail View Cleanup + List View Refinements (5 March 2026)

### Game Breakdown Tier Gating
- Game breakdown (AI narrative path) now fully tier-gated via `get_edge_access_level()`
- `_gate_breakdown_sections()`: Setup free for all, Edge/Risk/Verdict show `🔒 Available on Gold.` for blurred/locked
- `_gate_signal_display()`: 2-line summary for non-accessible tiers (no ❌ marks)
- SA Bookmaker Odds: full for accessible, spoilered for blurred, hidden for locked
- Single CTA footer: `━━━ 🔒 Unlock full analysis → /subscribe (R99/mo)` — no per-section /subscribe
- `sanitize_ai_response()` step 1b: strips duplicate plain-text section headers

### List View Refinements
- Streak label: "N correct predictions in a row!" (win) / "Last N predictions missed — accuracy: X%" (loss)
- Card line 1: sport emoji before teams, tier badge after: `[N] ⚽ Home vs Away 🥇`
- Portfolio line shortened: "R100 on our top N → R{total} total return."
- `HOT_TIPS_PAGE_SIZE = 4`, `GAMES_PER_PAGE = 4` (was 5)

## Wave 27-UX — Hot Tips Layout Amendments (5 March 2026)

### Header Block (UT-1, UT-2)
- Title: `🔥 Top Edge Picks — {hit_rate}% Predicted Correctly (7D)` — 7-day hit rate from `get_edge_stats()`
- Subline: `Scanned {N} leagues, {M} external resources and all major SA bookmakers.` — resource count from `get_db_stats()` total_rows
- **LOCKED LAW:** Subline must say "all major SA bookmakers" — never a specific number
- Third line: `✅ {N} Live Edges Found` — replaces streak badge (streak removed from this screen)
- `_build_hot_tips_page()` accepts `hit_rate_7d: float = 0.0` and `resource_count: int = 0` parameters

### Card Spacing (UT-3)
- Double blank lines between cards (was single). All card-based list views must follow this standard.

### Footer CTA Bold Hierarchy (UT-4, UT-5)
- Bold key metric/label on each line, supporting detail in regular weight
- `🔒 <b>N edges locked</b> — tier breakdown`
- `📈 <b>R100 on our top N</b> → total return`
- `🔑 Unlock all → /subscribe` (emoji-led CTA)
- `🎁 <b>Founding Member:</b> pricing + countdown`
- Extra blank line before and after `━━━` divider for breathing room

### SA20 Date/Time (upstream issue)
- SA20 professional T20 matches have no commence_time in odds_snapshots (scraper doesn't capture it)
- DStv broadcast_schedule has "SCH SA20" (schools cricket) not professional SA20 — broadcast matcher mis-matches
- Fallback: date extracted from match_id suffix (e.g. `team_vs_team_2026-03-05` → "Today" / "Wed 05 Mar")
- Full fix requires Dataminer to add commence_time to odds pipeline or DStv to label SA20 matches distinctly

### Universal Truths (locked standards)
- UT-1: Every edge list header must show 7-day hit rate (when >= HIT_RATE_DISPLAY_THRESHOLD)
- UT-2: Italicised scan breadth subline on every primary list view
- UT-3: Double blank lines between cards on all card-based list views
- UT-4: Footer CTA bold hierarchy — bold key metric, regular weight for supporting detail
- UT-5: Every CTA line starts with relevant emoji

## Wave 27-UX-FIX — Spacing Regression + Hit Rate Threshold (5 March 2026)

### Spacing Fix
- SPACING LAW (locked): Never more than `\n\n` anywhere in Hot Tips output
- Between cards: one `lines.append("")` = `\n\n` via join (one visible blank line)
- Before/after `━━━` divider: same — one blank line each side
- Within footer CTA block: consecutive lines, no gaps

### Hit Rate Threshold
- `HIT_RATE_DISPLAY_THRESHOLD = 50` — only show hit rate in header when >= 50%
- Below threshold: falls back to "{N} Live Edges Found" format
- UT-1 amended: show hit rate only when >= threshold

## Wave 29-P0 — AI Hallucination Zero Tolerance (5 March 2026)

### ABSOLUTE RULES Prompt (LOCKED)
- 7 numbered ABSOLUTE RULES + GOLDEN RULE in _build_analyst_prompt()
- Form must match VERIFIED_DATA character-for-character
- No style/tactic descriptions, no unverified names, no training-data facts

### Fact-Checker Expansion (6 checks)
- Form patterns (exact WDL match), positions, differentials, scores, style words, unverified names
- >50% stripped → _build_programmatic_narrative() (rich prose fallback)
- All modifications logged via log.warning()

### Form Validation Pipeline
- _format_verified_context() truncates form to games_played (ESPN returns stale 5-char forms for 3-game seasons)
- Rugby always includes explicit W/D/L season record for cross-reference
- _verify_form_claim() uses exact match for WDL patterns (not substring)

### H2H Score Verification
- _verify_scores() handles both "score" string and home_score/away_score dict formats

## Wave 29-FIX — Two-Pass Narrative Architecture (5 March 2026)

### Two-Pass System (LOCKED)
- Pass 1: `build_verified_narrative()` builds pre-validated sentences from verified data (code only, no AI)
- Pass 2: `_build_analyst_prompt()` — Claude receives sentences as IMMUTABLE CONTEXT, interprets meaning
- Principle: "Code owns facts. AI owns analysis."

### build_verified_narrative()
- Input: ctx_data dict + tips list + enrichment block + sport
- Output: dict of sentence arrays per section (setup/edge/risk/verdict)
- Adapts to data availability: 1-4 sentences per section depending on what's available

### _build_analyst_prompt() (replaces _build_game_analysis_prompt)
- Identity: "You are an ANALYST, not a reporter"
- IMMUTABLE CONTEXT block in user message — Claude must not alter facts
- ABSOLUTE RULES + GOLDEN RULE retained from W29-P0
- _build_game_analysis_prompt kept as backward-compat alias

### Fallback Chain (updated)
- Quality gate fails 3x → _build_programmatic_narrative() (rich prose)
- fact_check >50% stripped → _build_programmatic_narrative() (rich prose)
- _build_programmatic_narrative returns empty → _generate_minimal_setup() (last resort)

## Wave 29-QA — Persistent /qa Tier Simulation (5 March 2026)

### QA Tier Override System
- `_QA_TIER_OVERRIDES: dict[int, str]` — in-memory override, cleared on restart
- `get_effective_tier(user_id)` — wrapper that checks override first, then DB
- All 27 `db.get_user_tier()` calls replaced with `get_effective_tier()`
- `/qa set_bronze`, `/qa set_gold`, `/qa set_diamond` — persist until `/qa reset`
- `/qa tips_*` now also persist tier override
- `_qa_banner(user_id)` — "⚠️ QA Mode: Viewing as TIER" prepended to key outputs
- Notification trigger functions use override instead of db.set_user_tier()
- Admin-only (ADMIN_IDS gate)
- TODO: Remove before launch

## Wave 30-GATE — Game Breakdown Gate Leaks + Emoji Fix (6 March 2026)

### Gate Leak Fixes
- `_gate_breakdown_sections()` — preamble text before first section emoji now skipped for non-full access
- `_build_game_buttons(edge_tier=)` — new parameter, single `get_edge_access_level()` check at top
- CTA emoji uses authoritative `edge_tier` (not EV-computed) — matches Hot Tips display tier
- No-positive-EV fallback now gated: blurred/locked → "View Plans" instead of deep link
- Compare All Odds button hidden for blurred/locked access
- `_analysis_cache` stores edge_tier in 4-tuple for cached path gating

## Wave 30-FORM — Form String Truncation in Narrative Bullets (6 March 2026)

### Form Truncation
- `narrative_generator.py` — `generate_narrative()` accepts `home_gp`/`away_gp`, truncates `home_form_string`/`away_form_string` before bullet creation
- `edge_v2.py` — `calculate_composite_edge()` passes through `home_gp`/`away_gp`
- `form_analyser.py` — `format_form_for_narrative()` accepts `home_gp`/`away_gp`, truncates form_string + "(last N)" count
- `bot.py` — `_truncate_form_bullets(bullets, match_ctx)` post-processes narrative bullets using `games_played` from ESPN standings
- Applied at: AI prompt enrichment, user-facing display, `format_form_for_narrative()` call
- Already truncated (W29-P0): `_format_verified_context()`, `build_verified_narrative()`

## Wave 69-VERIFY — Web Search Fact Verification (7 March 2026)

### Web Search Integration (LOCKED)
- `web_search_20250305` tool enabled on ALL Opus pre-gen calls (max_uses=2)
- NOT enabled on live Haiku game breakdown (too slow for interactive use)
- `_extract_text_from_response()` — handles multi-block responses (text + search results)
- STEP 1 instruction in `_build_analyst_prompt()`: verify form, standings, news before writing

### Three Verification Layers
- Layer 1: Opus web search in pre-gen (real-time verification during generation)
- Layer 2: `_verify_narrative_claims()` — Haiku cross-check after generation (full sweeps only)
- Layer 3: `_narrative_health_check_job()` — spot-checks 2 cached narratives every 2 hours

### England Form Fix (W69)
- Cross-season form contamination: `build_verified_narrative()` now truncates form to games_played
- Affects international tournaments (Six Nations, Rugby Championship) where form crosses seasons
- `_format_verified_context()` already truncated; `build_verified_narrative()` was missing truncation

## Wave 72-AUDIT — Definitive 20-Match Opus Audit (7 March 2026)

### Bug Fixes
- `_extract_text_from_response()` — added `block.text is not None` guard (web search blocks can have text=None)
- `odds.db` switched from DELETE to WAL journal mode for concurrent access
- Test added: None text block scenario in `test_extract_text_from_response`

### Audit Results (W72)
- 19/20 OK, 1 NO_DATA, 0 errors
- Web search active (W69), fact-checker active, 0 empty sections
- Banned phrase hits down from 11 (W65) to 8
- Stale price flagging working correctly in 4 narratives

## Wave 73-LAUNCH — Final Launch-Readiness Fixes + Sonnet Switch (7 March 2026)

### Model Switch (LOCKED)
- NARRATIVE_MODEL env var controls model for all narrative generation
- Default: claude-sonnet-4-20250514 (was claude-opus-4-20250514)
- Haiku retained for live game breakdown (speed) and health checks (cost)
- opus_audit.py and pregenerate_narratives.py both read NARRATIVE_MODEL

### Empty Verdict Fix
- _ensure_verdict_not_empty() — catches <40 char Verdict sections
- Signal-derived fallback: stale price → "verify", strong EV → "back", thin EV → "size conservatively"
- _has_empty_sections() now checks Verdict (🏆→end) in addition to Setup and Risk

### Programmatic Fallback Rewrite
- _build_programmatic_narrative() Risk section: signal-derived (movement, tipster consensus)
- Verdict section: stale-aware, confirming-signal-aware, no banned phrases
- Zero banned phrases remain in programmatic fallback

### Fact-Checker Nickname Whitelist
- _KNOWN_TEAM_NICKNAMES set: ~45 team nicknames (EPL, European, SA PSL, rugby franchises, cricket)
- Checked before unverified person name stripping in fact_check_output()

### Web Search Coverage Fix
- _build_analyst_prompt(mandatory_search=True) for pre-gen paths
- Mandatory wording: "You MUST use web search... NON-NEGOTIABLE"
- Conditional wording retained for live Haiku path (no web search tool)
- max_uses increased from 2 to 3

### Sonnet Benchmark (W73)
- 8/10 OK, 2 NO_DATA (Six Nations — DB lock), 0 errors
- 0 banned phrase hits (was 8 in W72)
- Avg 660 tokens, avg 28.7s per match
- Web search now fires on all matches (was 4/19 in W72)

## Wave 79-PHASE2 — Code Owns Facts, AI Owns Analysis (8 March 2026)

### Definitive Architecture (LOCKED)
- Code builds Setup (W80-PROSE data-driven language maps) — zero hallucination
- AI writes Edge + Risk ONLY (~200 tokens, focused prompt)
- Code builds Verdict (signal-driven: stale-aware, confirming-signal-aware)
- Assembly: _generate_narrative_v2() wires all three layers

### AI Prompt (LOCKED)
- _build_edge_risk_prompt() — focused ~60-line prompt for Edge + Risk only
- max_tokens=512 (was 1024)
- _build_analyst_prompt() kept for backward compat

## Wave W80-PROSE — Natural Analyst Prose Templates (9 March 2026)

### Setup Architecture (LOCKED — replaces W79 templates)
- _build_setup_section_v2(ctx_data, tips, sport) — master builder
- 17 functions where data dictates vocabulary (not fill-in-the-blank)
- _match_pick() — MD5 hash ensures same match = same variation, different matches = different phrasing
- _form_narrative() — 12 distinct patterns (streaks, recovery, draw-heavy, mixed/volatile)
- _position_narrative() — 8 ranges: "top of the table" through "deep in trouble"
- _h2h_hook() — <3 meetings: brief note; 3+ meetings: full narrative hook
- _coach_ref_v2() — last-name-only in possessive/has_them styles (analyst convention)
- _apply_sport_subs(text, sport) — post-assembly rugby/cricket terminology substitution
- Backward-compat aliases kept for _build_edge/risk/verdict_from_signals (v2 underneath)

### Deleted (W79 — fully replaced)
_coach_ref, _form_adjective, _gpg_woven, _record_woven, _last_result_fragment,
_last_result_impact, _h2h_verdict, _h2h_summary, _build_home/away_position_parts,
_append_h2h, _build_setup_position/form/matchup/h2h, _build_setup_section

## Wave W81-FACTCHECK — Stop Fact-Checker Destroying AI Edge/Risk (9 March 2026)

### Fact-Checker Architecture (LOCKED)
- _merge_continuation_lines(lines) — merges multi-line sentences before fact-checking.
  A sentence = text until . ! ? — continuation lines are bundled with their parent.
  Section headers (🎯⚠️📋🏆) always start new units.
- fact_check_output() now strips whole SENTENCES not individual \n-separated lines.
- _clean_fact_checked_output(text) — post-strip cleanup: orphaned commas, connectors, periods.
- get_verified_injuries(home, away) — queries team_injuries table (rows within 2 days).
  Player names injected into user_message as VERIFIED INJURY DATA block (Layer 1).
  Also added to verified_names in fact_check_output() so checker doesn't strip them (Layer 2).

### Bug Fixed (W81)
- _build_setup_section stale reference in fact_check_output() last-resort fallback
  → fixed to _build_setup_section_v2

## Wave W81-HEALTH — Fix 5 Recurring Post-Deploy Validation Failures (9 March 2026)

### Fixture-Aware Thresholds (LOCKED)
- _is_slump_day() / _fixture_minimum() — Mon/Tue/Thu = 1 edge minimum; Fri-Sun/Wed = 3.
  Applied in both post_deploy_validation.py and health_monitor.py.
- GOLD_DIAMOND_MAX_GAP_HOURS raised to 48h (post-weekend cycles exceed 24h naturally).
- check_settlement_pipeline() now distinguishes "match_results empty" from "pipeline stopped".
  Alert text: "Results scraper missing data" vs "pipeline hasn't run".
- settle_edges() logs WARNING when skipping (match_key not in match_results).

### Pre-Gen Safeguards (LOCKED)
- _REQUIRED_BOT_FUNCTIONS list + import validation in pregenerate_narratives.py startup.
  Raises ImportError with function names if any wave renames a required export.
- PID lock (fcntl) in pregenerate_narratives.py __main__ block.
  Lock file: ~/logs/pregen.pid. Second concurrent invocation exits cleanly with code 0.

### Pre-Gen Import Contract (LOCKED — W80+W81+MZANSI-EDGE-1D)
- tests/contracts/test_imports.py::TestCriticalFunctions guards all critical bot exports.
  Any rename of: _build_setup_section_v2, get_verified_injuries, _clean_fact_checked_output,
  build_verified_narrative, fact_check_output → daily contract test fails before cron does.
- NEVER test bot function availability with: python -c "import bot; asyncio.run(bot.fn())"
  Sentry SDK initialises at import time — AttributeError/ImportError captured as a real event.
  Use: grep -n "def fn_name" bot.py  OR  hasattr checks inside the test suite.

## Wave W81-SCAFFOLD — Story Detection + Factual Scaffold (9 March 2026)

### Three-Stage Prose Engine: Stage 1 Complete
- _decide_team_story(pos, pts, form, home_rec, away_rec, gpg, is_home, sport="soccer") → story type
  Soccer/rugby/cricket — 10 story types:
  (title_push, fortress, crisis, recovery, momentum, inconsistent, draw_merchants, setback, anonymous, neutral)
  Priority chain: title_push → fortress → crisis → recovery → momentum → inconsistent →
  draw_merchants → setback → anonymous → neutral
  MMA (sport="mma") — ranking + record story types (BUILD-ENRICH-08, 2026-04-04):
  Ranking: pos 1-3 → title_contender, 4-10 → gatekeeper, 11+ → prospect
  Modifier: wins≥20 & losses≤5 → dominant, losses>wins → comeback
  Combined: e.g. title_contender_dominant, gatekeeper_comeback
  Record-only (no ranking): dominant/comeback/neutral from form string
  No data (pos=None, form empty) → neutral (default preserved)
- _scaffold_last_result(team) — module-level helper extracted from _build_setup_section_v2
- _build_verified_scaffold(ctx, edge_data, sport) — full factual scaffold:
  SPORT/COMPETITION, HOME/AWAY story type + verified facts + H2H + EDGE + RISK FACTORS
  Calls get_verified_injuries() for live injury data from team_injuries DB table
- Wired into _generate_narrative_v2() as Stage 1: scaffold prepended to user_message
  as "VERIFIED SCAFFOLD:" block when ctx_data and tips are both available
- /qa scaffold <match_key> — admin debug command, prints raw scaffold for inspection
- Stage 2 (W81-REWRITE) and Stage 3 (W81-VERIFY) are next briefs

## Wave W81-CLEANUP — Story Type + Injuries + Exemplars Pre-Flight (9 March 2026)

### _decide_team_story() Crisis Threshold (LOCKED)
- Crisis threshold: pos >= 14 (was pos >= 16). Bottom-half relegation zone starts at 14th.
- Belt-and-suspenders: pos >= 14 AND l >= 3 → crisis even if last result was a win.
- Recovery guard: only fires when pos <= 13. pos >= 14 teams stay in crisis even after a bounce.
- Anonymous range: 8 <= pos <= 13 (was 8 <= pos <= 14).

### get_verified_injuries() Filter (LOCKED)
- Excludes injury_status IN ('Missing Fixture', 'Unknown') from scaffold.
  "Missing Fixture" is an API-Football artefact for squad-mapped players with no real record.

### load_exemplars() (LOCKED)
- _EXEMPLAR_FILE = data/prose_exemplars.json (relative to bot.py dir)
- _EXEMPLAR_CACHE: global dict — populated on first call, reused thereafter
- Graceful fallback: returns {"setup":{}, "edge":{}, "risk":{}, "verdict":{}} on any file error
- prose_exemplars.json: 10 story types × 3 exemplars each, 4 top-level section keys

## Wave W81-DBLOCK — SQLite "database is locked" Permanent Fix (9 March 2026)

### Root Cause (LOCKED — DO NOT REPEAT)
- log_edge_recommendation() had `except Exception` that swallowed sqlite3.OperationalError.
  @_retry_on_locked decorator saw a normal False return and never retried. 792 Sentry events.
- Fix: `except sqlite3.OperationalError: raise` added before broad except.
  OperationalError now propagates to decorator which retries up to 5× with 0.25s initial backoff.
- _RETRY_ATTEMPTS = 5 (was 3), _RETRY_BACKOFF = 0.25 (was 1.0)

### Retry Architecture (LOCKED)
- @_retry_on_locked catches OperationalError with "locked" — retries up to _RETRY_ATTEMPTS times
- connect_odds_db() sets busy_timeout=30000 — SQLite waits 30s per attempt before raising
- Combined: up to 5 attempts × 30s wait = 150s total tolerance for long scraper runs
- DO NOT add broad except Exception inside @_retry_on_locked-decorated functions — it breaks retries

### Health Monitor Tests (LOCKED — W81-HEALTH thresholds)
- test_too_few_edges: must mock Saturday (weekday=5) to ensure peak-day threshold applies
- test_stale_gold_alert: must use > 48h gap (GOLD_DIAMOND_MAX_GAP_HOURS=48 since W81-HEALTH)
- check_settlement_pipeline: conn must remain open until match_results diagnostic query is done

## Wave W81-COACHES — Coach Names Missing From Scaffolds (9 March 2026)

### Root Cause (LOCKED — DO NOT REPEAT)
- api_cache was checked BEFORE coaches.json. API-Football returns assistants/wrong coaches.
  coaches.json (manually curated, last_updated 2026-02-26) must ALWAYS take priority.
- Priority fix: `home_coach = _get_coach(...) or home_coach` — static wins when available.
- Degraded response (DB lock): coaches now injected from static JSON in except block.

### Coach Data Architecture (LOCKED)
- Tier 1: coaches.json (manually curated, 42 soccer teams — ALL 20 EPL, full PSL, CL, La Liga)
- Tier 2: api_cache (auto-populated, often wrong — treated as fallback for teams not in Tier 1)
- Tier 3: API-Football live fetch (also often wrong — last resort)
- Priority: Tier 1 wins when available. Tier 2/3 only for teams not in coaches.json.
- "wolves" alias added to coaches.json (Wolverhampton Wanderers short name, no partial match).
- coaches.json must be updated manually after every confirmed manager change.

## Wave W81-SETTLE — Settlement Pipeline Fix (9 March 2026)

### ISBets Ghost Fixture Pattern (LOCKED — DO NOT IGNORE)
- Playabets + Supabets are ISBets clones — same backend, same ghost fixtures
- ISBets pre-loads EPL fixtures with wrong dates AND wrong opponents weeks early
- A match appearing ONLY in Playabets/Supabets = high ghost fixture risk
- Three defences in settlement.py:
  1. log_edge_recommendation(): skips ISBets-only fixtures at log time
  2. settle_edges(): auto-voids ISBets-only edges after 3+ days no result
  3. void_edge(): manual void for confirmed ghost fixtures
- _ISBETS_BOOKMAKERS = {"playabets", "supabets"}, _GHOST_FIXTURE_DAYS = 3

### _fuzzy_match_result() (LOCKED — ±5 days + aliases)
- Extended to ±5 days (was ±1) to catch ISBets wrong-date fixtures
- Uses _expand_team_key() for alias expansion (e.g. wolves→wolverhampton_wanderers)
- _TEAM_ALIASES: 14 entries covering EPL short names + PSL canonical names
- Root cause of wolves-liverpool non-settlement: %wolves% LIKE does NOT match wolverhampton_wanderers

### void_edge() (NEW)
- result='void', excluded from hit_rate/ROI/streak stats (queries use WHERE result IN ('hit','miss'))
- match_score field stores reason (e.g. 'ghost_fixture_isbets')
- Exported from settlement.py — import as: from scrapers.edge.settlement import void_edge

## Wave W82-SPEC — NarrativeSpec + Evidence Classification (9 March 2026)

### Architecture (LOCKED)
- `narrative_spec.py` (bot/) — typed editorial spec module. Pure Python, no bot/Sentry deps at import time.
- `NarrativeSpec` dataclass: 30 fields covering identity, context, edge thesis, evidence class, risk, verdict
- `_classify_evidence(edge_data)` → (evidence_class, tone_band, verdict_action, verdict_sizing)
  - Stale penalty: -1 effective support if stale >= 360 min (6h)
  - Movement penalty: -1 effective support if movement == 'against'
  - 0 effective → speculative/cautious; 1 → lean/moderate; 2-3 → supported/confident; 4+ (composite>=60 + EV>=5%) → conviction/strong
- `TONE_BANDS`: 4 levels with allowed/banned phrase lists (cautious/moderate/confident/strong)
- `_check_coherence(spec)`: 6 contradiction checks — returns violation list
- `_enforce_coherence(spec)`: downgrade loop — strong→confident→moderate→cautious until coherent
- `build_narrative_spec(ctx_data, edge_data, tips, sport)` — assembles full spec; lazy imports from bot.py
- Contract tests: `tests/contracts/test_narrative_spec.py` (92 tests) + 9 guards in test_imports.py
- `_LEAGUE_DISPLAY` duplicated from bot.py's `LEAGUE_DISPLAY_NAMES` — keep both in sync on league additions

### Downgrade Termination Rule (LOCKED)
- Downgrade stops when no violations fire (not necessarily at floor)
- With 0 signals + strong tone: stops at moderate (lean verdict is not 'back'/'strong back')
- To force floor (cautious): requires stale_minutes >= 720 as additional violation

## Wave W82-RENDER — Deterministic Baseline Renderer (9 March 2026)

### Architecture (LOCKED)
- `_render_baseline(spec)` — assembles 4-section prose from NarrativeSpec. Zero AI. Zero API.
- `_render_setup(spec)` — home para + away para + H2H bridge. OEI pattern.
- `_render_edge(spec)` — 4 paths by evidence_class. All phrases comply with tone_band allowed/banned lists.
- `_render_risk(spec)` — code-decided risk factors + sizing caveat. Always includes stake guidance.
- `_render_verdict(spec)` — 4 paths by verdict_action. Tone-capped: never uses banned phrases.
- `_render_team_para(name, coach, story_type, ...)` — MD5-deterministic template selection.
  Same team name always gets same variant (3 per story type, 10 story types = 30 templates).
- `_TEAM_TEMPLATES` — dispatch dict. Falls back to 'neutral' for unknown story types.
- `_mk_variants(fn)` factory avoids Python closure-in-loop bug for template lambdas.

### Away Pick Risk Factor (LOCKED)
- Home advantage factor fires when `outcome == "away"` AND `confirming < 3`.
- For conviction-level away picks (3+ signals), disadvantage is already in model probabilities.
- Text: "Away side faces home crowd disadvantage — factor that in."

### W82-RENDER Contract Guards (LOCKED)
- `tests/contracts/test_imports.py::TestCriticalFunctions`: guards for _render_baseline, _render_setup, _render_edge, _render_verdict.
- Any rename of these 4 functions → daily contract test fails before cron does.

## Wave W82-WIRE — NarrativeSpec Pipeline Integration (9 March 2026)

### Architecture (LOCKED)
- `_generate_narrative_v2()` — 14-line body. Calls `build_narrative_spec()` → `_render_baseline()`. Zero LLM.
- `pregenerate_narratives._generate_one()` — same pipeline. Layer 2 verification + HTML assembly preserved.
- `_extract_edge_data(tips, home, away)` — normalises tip list into edge_data dict for build_narrative_spec().
- `_extract_teams_from_tips(tips, home, away)` — extracts real names from match_key. Kills "Home take on Away".
- "based on what you know" removed from `_generate_game_tips()`. No-odds path returns clean static string.
- Old 3-stage AI rewrite (scaffold + exemplars + Sonnet + fact-checker) is dead code. Removed by W82-POLISH.

### Dead Code (DO NOT RE-ENABLE)
The following are bypassed but left in bot.py until future cleanup:
`_build_verified_scaffold`, `_parse_story_types_from_scaffold`, `_build_rewrite_prompt`,
`_verify_rewrite`, `_build_edge_risk_prompt`, `_build_signal_only_narrative`

## Wave W82-POLISH — Constrained LLM Polish Pass (9 March 2026)

### Architecture (LOCKED)
- `_build_polish_prompt(baseline, spec, exemplars)` — constrained polish prompt. LLM may only improve flow, not analytical posture. Passes tone band allowed/banned lists, verdict action, 8 strict rules.
- `_validate_polish(polished, baseline, spec)` → bool — 6 gates: banned phrases, 4 section headers, team names, bookmaker+odds, speculative contradictions, _quality_check().
- `_generate_narrative_v2()`: live_tap=True → instant baseline, zero LLM. live_tap=False → baseline + Sonnet polish attempt. Polish FAIL → baseline served.
- `pregenerate_narratives._generate_one()`: always attempts polish. Cache stores polished version when valid.
- Both `_build_polish_prompt` and `_validate_polish` in `_REQUIRED_BOT_FUNCTIONS` — rename protection.
- Sweep result: validator correctly caught "lock" (banned in moderate band) during live run.

## Wave W83-OVERNIGHT — Instant Baseline + Signal Coverage Fix (9 March 2026)

### Architecture (LOCKED)
- `_edge_precompute_job()`: cache-miss tips now stored in `_game_tips_cache[match_id] = [_tip]`
  so instant baseline path is armed for all hot tips after each 15-min precompute cycle.
- `edge:detail` slow path: before `_generate_game_tips_safe()`, checks `_game_tips_cache` and
  serves instant baseline via `_generate_narrative_v2(live_tap=True, ctx_data=None)` — zero
  ESPN, zero LLM, zero DB writes. Falls through to full generation if baseline fails.
- `test_signal_strength_bounded`: updated to skip `available=False` signals (`lineup_injury`
  intentionally returns `None` strength for rugby/cricket — no injury data source exists).
- Problem 2 (4 cached edges): confirmed weekend lull + stale filter — NOT a code bug.
  `get_top_edges()` filters stale edges; `pregenerate_narratives` uses `get_top_edges()` → few edges on
  Sunday night. Instant baseline bridges the gap. Full polish at next 06:00 SAST sweep.

### Root Cause (LOCKED — DO NOT REPEAT)
- `_generate_game_tips()` for `_vs_` events hits three sequential 30-second waits:
  ESPN API timeout, `calculate_edge_v2()` DB ops, `_store_narrative_cache()` write retries.
  Total = 123.6s. `live_tap=True` skips LLM but does NOT skip these waits.
- Fix: pre-populate `_game_tips_cache` in `_edge_precompute_job()` for ALL hot tips (including
  cache misses), then serve instant baseline on tap before ever calling `_generate_game_tips_safe()`.

## Wave W84-P1D — Hot Tips Detail Serving Fix (10 March 2026)

### Root Causes Fixed (LOCKED — DO NOT REPEAT)

#### "Message is not modified" causes 31–123s slow opens
- When user double-taps a tip or re-enters a detail they've already seen, `query.edit_message_text()` throws `BadRequest("Message is not modified")`.
- Was caught by broad `except Exception` in instant baseline block → fell through to `_generate_game_tips_safe()` (ESPN+LLM slow path, 30–123s).
- **Fix:** In `edge:detail` handler, catch "not modified" string in exception message and return early — never fall through:
  ```python
  if "not modified" in str(_ie_err).lower():
      return  # Content already showing — success, not failure
  ```

#### `edge_v2=None` tips get wrong tone band despite Gold/Silver tier
- `_load_tips_from_edge_results` (fast DB path) returns tips with `edge_v2=None`.
- `_extract_edge_data` fell back to `confirming_signals=0` → `_classify_evidence` always returned "speculative/cautious" regardless of composite_score.
- Gold tips rendered as "cautious speculation" while showing 🥇 badge — contradictory.
- **Fix:** In `_extract_edge_data`, estimate `confirming_signals` from `edge_score` when `edge_v2=None`:
  - `edge_score >= 70` → 3 signals (Diamond/confident)
  - `edge_score >= 55` → 2 signals (Gold/moderate)
  - `edge_score >= 40` → 1 signal (Silver/lean)
  - `edge_score < 40`  → 0 signals (Bronze/cautious)

#### Wrong-match content was test artifact (not bot bug)
- Test used `"back" in text.lower()` which matched CTA "🥈 Back home @ 1.58 on Betway →" before nav "↩️ Back to Edge Picks".
- URL button didn't change message → test timed out → left display in wrong state.
- **Fix in test only:** `"edge picks" in text.lower() or text.strip().startswith("↩️ Back")`.

### Test Results (W84-P1D)
- Full unit suite: 1159 passed, 3 skipped, 0 failures
- Contract tests: 261 passed
- Live validation: 33/34 passed (1 timing flakiness, non-blocking)
- Narrative validation: 54/56 passed (2 design mismatches, non-blocking)

## Wave W84-MM1 — My Matches Cold-Path: DB-Independent (10 March 2026)

### Architecture (LOCKED)
- `_render_your_games_all()` accepts `skip_broadcast: bool = False`.
  When True, skips all `odds.db` broadcast queries — safe during `_edge_precompute_job`.
  Cold-path background task and `yg:all:` inline callback always pass `skip_broadcast=True`.
  Warm-path direct taps (cache hit) still show broadcast info.
- `_fetch_schedule_games()` DB gather (odds_svc.get_all_matches) has 2.5s timeout.
  On timeout, falls back to Odds API file-cache data only. Logged as WARNING.
- Cold-path deadline: 5.0s (was 3.5s). Well within 8s validation gate.
- Pattern: first 5 opens during edge_precompute (95s startup window) serve degraded in
  5.6–5.8s. Background task warms cache — subsequent opens are 0.8–0.9s full.

### DO NOT
- Add synchronous odds.db queries to `_render_your_games_all()` — they block threads.
- Remove the `skip_broadcast` guard — broadcast queries cause lock contention.
- Set the DB gather timeout > 3.0s — background task must complete within 5.0s deadline.

## Wave W84-HT2 — Hot Tips Page/Detail Identity: Snapshot-Frozen (10 March 2026)

### Architecture (LOCKED)
- `_ht_page_state: dict[int, int]` — per-user last rendered page number (0-indexed)
- `_ht_tips_snapshot: dict[int, list]` — per-user shallow copy of tips frozen at last render
- Both dicts stored after EVERY list render: `_do_hot_tips_flow` (warm/fast/cold), `hot:page:N`, `hot:back`
- `hot:page:N` reads snapshot first: `_ht_tips_snapshot.get(user_id) or _hot_tips_cache.get(...)`
  This prevents identity drift when `_edge_precompute_job` refreshes global cache between renders.
- Back callbacks are PAGE-ENCODED: `hot:back:{N}` (not bare `hot:back`)
  `hot:back` handler parses N; renders snapshot at that page; updates `_ht_page_state`.
- `_build_game_buttons(back_page=N)` — passes page number through for back callback encoding.
  All `edge:detail` paths pass `back_page=_ht_page_state.get(user_id, 0)`.

### DO NOT
- Read `_hot_tips_cache["global"]["tips"]` directly in `hot:page:N` — always use snapshot first.
- Use bare `hot:back` callback data — always encode page: `hot:back:{page}`.
- Reset `_ht_tips_snapshot[user_id]` without also resetting `_ht_page_state[user_id]`.

## Wave W84-ACC1 — Account Truth, QA Reset, View Accounting (10 March 2026)

### Architecture (LOCKED)

#### Entitlement Truth
- `get_user_tier(user_id)` reconciles bronze tier with active subscription:
  If `user_tier='bronze'` AND `subscription_status='active'`, derives tier from `plan_code`.
  `_resolve_tier_from_subscription(user)` builds tier map from STITCH_PRODUCTS + "stitch_premium"→gold.
  Returns derived tier; never mutates DB (read-only reconciliation).
- `get_effective_tier(user_id)` checks `_QA_TIER_OVERRIDES` first, then calls `get_user_tier()`.
  ALL product gates, /status, /billing, and notification paths use get_effective_tier().

#### /qa reset
- `/qa reset` clears ONLY `_QA_TIER_OVERRIDES` in-memory dict.
- NEVER calls `db.set_user_tier()` — subscription state in DB is never touched by QA commands.
- DB columns that /qa reset may update: daily_push_count, last_push_date, nudge_sent_at,
  last_active_at, consecutive_misses, muted_until. All are QA/notification-state fields only.

#### Daily View Accounting (edge_v2_helper.py)
- `record_tip_view(user_id, match_key, conn)` is idempotent per (user, match_key, SAST day).
  Same user + same match_key + same day → silently returns, no new row inserted.
  Different fixture → new row inserted, counts toward daily limit.
- `check_tip_limit()` uses `COUNT(DISTINCT match_key)` for Bronze users.
  Defensive against old duplicate rows.

### DO NOT
- Add db.set_user_tier() calls to /qa reset — it destroys real subscription state.
- Read user.user_tier directly for entitlement decisions — always use get_effective_tier().
- Remove the _resolve_tier_from_subscription() reconciliation — without it, stale bronze
  columns from pre-W84-ACC1 /qa reset will not heal automatically.
- Use COUNT(*) in check_tip_limit — must be COUNT(DISTINCT match_key).

## Wave W84-MM2 — My Matches Cold-Path DB Query Fix (11 March 2026)

### Architecture (LOCKED)

#### odds_snapshots Query Index Rule (LOCKED — DO NOT REVERT)
- `get_all_matches(league=X)` queries `odds_snapshots` (543K+ rows) with an INNER JOIN.
- `AND os.league = ?` — EXACT MATCH ONLY. Never add COLLATE NOCASE.
  COLLATE NOCASE disables the `idx_odds_league_time` index → full table scan → 6+ seconds.
  All league values in odds_snapshots are stored lowercase by scrapers — exact match is correct.
- `idx_odds_league_time` index covers `(league, scraped_at)`. Exact match uses this index.
  Query time: 0.001-0.9s (was 6+ seconds with COLLATE NOCASE on 543K rows).

#### Cold-Path Delivery Hardening (_show_your_games)
- None-guard: if `_render_your_games_all` raises exception, `_mm_result = [None, None]`.
  Must check for None before calling `loading.edit_text()`.
- Capped spinner wait: `asyncio.wait_for(asyncio.shield(spinner_task), timeout=2.0)`.
  Prevents unbounded block when spinner is mid-Telegram-API call at timeout fire.
- Explicit edit_text timeout: 3.0s cap on `loading.edit_text()`.
  Prevents indefinite hang on Telegram API slowness.

### DO NOT
- Add `COLLATE NOCASE` to `get_all_matches()` JOIN query — it destroys index usage.
- Remove the None-guard in `_show_your_games()` — silent failures were invisible before.
- Change `asyncio.wait_for(asyncio.shield(spinner_task), timeout=2.0)` back to bare `await spinner_task`.

## Wave W84-RT3 — Cold-Open Outlier + Persist Lock Warnings (11 March 2026)

### Architecture (LOCKED)

#### _show_your_games() Cold Path Budget (LOCKED — DO NOT REGRESS)
- `_mm_timed_out = False` flag tracks whether the 5.0s render deadline fired.
- On timeout path: `spinner_task.cancel()` immediately (0ms) → `reply_text` (no edit).
  Total: 5.0s + ~0.1s = 5.1s max.
- On success path: existing 2.0s spinner wait + 3.0s edit_text unchanged.
- DO NOT merge the two paths — the timeout path must cancel spinner, not wait for it.

#### _fetch_schedule_games() API Gather Timeout (LOCKED — DO NOT REMOVE)
- `asyncio.wait_for(asyncio.gather(*[fetch_events_for_league(lk)...]), timeout=3.5)`
- File-cached calls return in < 100ms. Cold fetches capped at 3.5s.
- On timeout: empty results for all API leagues, DB-only fallback used.
- Without this timeout, a single slow API call can consume the full 5.0s deadline.

#### Narrative Cache Persist — Best-Effort, Short Timeout (LOCKED)
- `_store_narrative_cache()`: single attempt with `get_connection(timeout_ms=3000)`.
  No retry loop. `log.debug()` on lock (not `log.warning()`).
- `_compute_odds_hash()`: also uses `get_connection(timeout_ms=3000)`.
- The in-memory `_analysis_cache[event_id]` always has the narrative. DB persist
  is for cross-restart resilience only — skipping one write is acceptable.
- `db_connection.get_connection()` now accepts `timeout_ms` parameter (default: _BUSY_MS).
  All non-critical background DB access should pass `timeout_ms=3000` or lower.

### DO NOT
- Merge the `_mm_timed_out` branches — the timeout path must not wait for spinner.
- Remove the `asyncio.wait_for(..., timeout=3.5)` from the API gather.
- Add retry logic back to `_store_narrative_cache()`.
- Change lock failures in `_store_narrative_cache()` from `log.debug` to `log.warning`.

## Wave W84-RT4 — Background View-Log Lock Cleanup (11 March 2026)

### Architecture (LOCKED)

#### Background record_view — 3s Timeout, debug on Lock (LOCKED)
- `_record_view_bg()` and `_ib_record_view_bg()` in `edge:detail` handler:
  `get_connection(timeout_ms=3000)` — not the default 30s.
  `sqlite3.OperationalError` with "locked" → `log.debug()`, NOT `log.warning()`.
  Any other error → `log.warning()`.
  Background view-log is best-effort; idempotent guard prevents double-counting on retry.

#### handle_tip_detail() Tier Gate — In Thread (LOCKED)
- `check_tip_limit()` + `record_view()` + `get_connection()` are synchronous sqlite3 calls.
  Moved to `asyncio.to_thread(_tip_gate_and_record)` with `timeout_ms=3000`.
  Returns True (allow) on any `OperationalError` with "locked" or other exception —
  never gate the user out due to DB pressure.

#### View Persistence Architecture (LOCKED)
- `daily_tip_views` (odds.db) — tracks per-user per-match daily view count.
  Written by `record_tip_view()` in `scrapers/edge/edge_v2_helper.py`.
  Idempotent: SELECT guard prevents INSERT if already recorded today for this fixture.
- `user_edge_views` (bot's SQLAlchemy DB) — tracks user↔edge views for result alerts.
  Written by `db.log_edge_view()` via aiosqlite — non-blocking, no lock risk.

### DO NOT
- Change `log.debug()` for locked errors in `_record_view_bg()` back to `log.warning()`.
  Lock errors here are expected during scraper write windows — they are not failures.
- Remove the `asyncio.to_thread()` from `handle_tip_detail()` tier gate.
  `_get_conn()` + `record_view()` are synchronous — calling on event loop blocks it.
- Use `get_connection()` without `timeout_ms=3000` for any best-effort background write.
  Default is 30s — appropriate for critical path writes, not background analytics.

## Wave W84-Q1 — Narrative Quality Floor (11 March 2026)

### Architecture (LOCKED)

#### Bold Section Headers (LOCKED)
- `_render_baseline()` in `narrative_spec.py` produces `📋 <b>The Setup</b>` etc.
  All 4 section headers use `<b>` tags in the baseline renderer.
- `_build_edge_only_section()` in `bot.py` also uses bold section headers.
- `_build_polish_prompt()` rules 7/8 reference `<b>`-tagged headers.
- `sanitize_ai_response()` in the slow path also enforces bold headers.
  All narrative paths now produce consistent bold section headers.

#### MD5-Deterministic Variant Selection (LOCKED)
- `_render_setup()` no-context path: 4 variants. `_pick(home+away, 4)` selects variant.
  Same match → same variant. Different matches → diverse output. No LLM needed.
- `_render_edge()` speculative path: 4 variants. All contain "expected value" + "tread carefully".
- `_render_verdict()` speculative punt: 3 variants. All contain "small punt" + "speculative".
- DO NOT replace with single-template strings — diversity is intentional and testable.

#### Eliminated Phrases (BANNED — DO NOT RE-INTRODUCE)
- "Limited pre-match context for this fixture — ... pure edge play driven by bookmaker pricing"
- "This is a numbers-only play — ... thin on supporting signals"
- "The price is interesting at ..."
- "Zero confirming indicators — pure price edge with no supporting data."
- In `_build_edge_only_section()`: "Limited pre-match context available for this fixture"
  and "Numbers-only play — ... thin on supporting signals"

### DO NOT
- Remove `<b>` tags from section headers in `_render_baseline()` or `_build_edge_only_section()`.
- Revert no-context / speculative variants to single-template strings.
- Change "No confirming indicators" back to "Zero confirming indicators".

## Wave W84-Q2 — Low-Context De-Templating + Header Guarantee (11 March 2026)

### Architecture (LOCKED)

#### `_strip_preamble()` — Fixture Header Preservation (LOCKED)
- W84-Q2 fix: `🎯` is checked BEFORE `📋`.
  Reason: cached HTML starts with `🎯 Home vs Away / 🏆 League / 📅 kickoff`.
  Previously, checking `📋` first stripped the entire fixture header from all cached narratives.
  DO NOT revert the marker order — `🎯` must come before `📋` in `_strip_preamble()`.
  Logic: if `dart_idx < setup_idx`, return from `dart_idx`. Plain narratives (no fixture header)
  still work correctly because `📋` appears before `🎯` in them.

#### TONE_BANDS["cautious"] Banned Phrases (LOCKED)
- Now includes: "numbers-only play", "thin support", "price is interesting",
  "the numbers alone", "limited pre-match context", "pure price edge with no supporting data"
- DO NOT move these back to "allowed". They are production-banned.
- `_validate_polish()` enforces these against every LLM polish pass.

#### Eliminated Phrases (BANNED — W84-Q1 + W84-Q2 combined)
- "This is a numbers-only play — ..." (removed in W84-Q1)
- "thin on supporting signals" (removed in W84-Q1)
- "The price is interesting at ..." (removed in W84-Q1)
- "Zero confirming indicators — ..." (W84-Q1 changed to "No confirming indicators")
- "Pre-match context is limited here" (removed in W84-Q2)
- "the numbers alone make this interesting" (removed in W84-Q2)
- "pure price edge with no supporting data" (removed in W84-Q2)
- "Not a single indicator backs this" (removed in W84-Q2)

### DO NOT
- Move any phrase from `TONE_BANDS["cautious"]["banned"]` to "allowed" without brief.
- Revert `_strip_preamble()` marker order — `🎯` must be checked before `📋`.
- Re-introduce "Pre-match context is limited here" in any setup path.

## Wave W84-Q3 — Low-Context Narrative Differentiation + Legacy Phrase Purge (11 March 2026)

### Architecture (LOCKED)

#### Cached Narrative Banned-Phrase Gate (LOCKED)
- `_get_cached_narrative()` calls `_has_banned_patterns()` on retrieved HTML.
  Returns None (cache miss) when banned phrases found → forces re-generation.
  DO NOT remove this check — it prevents stale cached narratives from serving legacy phrases.
- `BANNED_NARRATIVE_PHRASES` includes all legacy speculative phrases.

#### Low-Context Setup — 8 MD5-Deterministic Variants (LOCKED)
- `_render_setup_no_context(spec)` replaces inline variants in `_render_setup()`.
- 8 distinct analytical frames: sport-first, market-question, analyst-observation,
  fixture-type, contrarian, direct-model, bookmaker-focused, clean-short.
- Sport-specific texture varies by soccer/rugby/cricket/combat.
- EV magnitude language adapts (slim < 2%, moderate 2-5%, high ≥ 5%).
- DO NOT collapse back to fewer variants — diversity is the entire point.

#### Multi-Variant Edge/Risk/Verdict (LOCKED)
- Speculative Edge: 6 variants (was 4). Zero use of "tread carefully".
- Lean Edge: 3 variants (was 1). Supported Edge: 3 variants (was 1). Conviction: 3 variants (was 1).
- Speculative Verdict: 4 variants (was 3). Lean/Back/Strong: 3 variants each (was 1).
- Risk confirming==0: 3 MD5-deterministic variants.
- DO NOT reduce variant count or re-introduce single-template paths.

#### Section Role Separation (LOCKED)
- Setup = what kind of fixture context exists
- Edge = what the price discrepancy is (numbers, bookmaker, fair probability)
- Risk = what is missing / what could break it (no sizing guidance)
- Verdict = sizing / confidence posture only
- Risk section MUST NOT duplicate Verdict sizing string.

#### TONE_BANDS["cautious"] — Expanded Banned List (LOCKED)
- Now also bans: "supporting evidence is thin", "signals are absent", "no signal backing",
  "signals don't confirm", "pricing edge without supporting signals", "the numbers speak louder",
  "pure pricing call", "tread carefully", "conviction is limited"
- "pricing play", "price-only play", "tread carefully" removed from allowed list.

### DO NOT
- Remove the `_has_banned_patterns()` check from `_get_cached_narrative()`.
- Collapse low-context variants back to < 8.
- Re-introduce "tread carefully" in any speculative Edge variant.
- Add sizing guidance to Risk section (belongs in Verdict only).
- Move any phrase from cautious banned back to allowed without brief.

## Wave W84-MM3B/RT5 — My Matches Delivery Reliability (11 March 2026)

### Root Causes Fixed (LOCKED — DO NOT REPEAT)

#### `telegram.error.TimedOut` at loading message → silent no-response
- Line `loading = await update.message.reply_text("⚽ Loading...")` was unprotected.
  Any Telegram API timeout here raised an uncaught exception that propagated out of
  `_show_your_games` entirely. User received zero response.
- Fix: wrapped in `try/except` + `asyncio.wait_for(timeout=8.0)`. `loading` defaults
  to `None`; failure is logged as WARNING and execution continues.

#### spinner_task and loading.delete() assumed loading was not None
- All downstream code (`spinner_task = asyncio.create_task(...)`, `loading.delete()`,
  `loading.edit_text()`) assumed loading was a valid message object.
- Fix: `spinner_task: asyncio.Task | None = None`; only created `if loading is not None`.
  All references to spinner_task and loading guarded with `if X is not None`.

#### Warm path reply_text and render unprotected
- Line `text, markup = await _render_your_games_all(...)` (warm path): no timeout.
  Line `await update.message.reply_text(...)` (warm path): no exception handling.
- Fix: wrapped render in `asyncio.wait_for(timeout=10.0)` with fallback to `_FALLBACK_TEXT`.
  Wrapped reply_text in `asyncio.wait_for(timeout=8.0)` with `except Exception` logged.

#### Final reply_text fallback in success path unprotected
- The `reply_text` on line 3121 (old numbering) — inside edit-failure branch — had no
  try/except. Telegram failure here left user with only a deleted loading message.
- Fix: wrapped in `asyncio.wait_for(timeout=8.0)` + `except Exception` logged as ERROR.

### _show_your_games() Delivery Contract (LOCKED)
Every My Matches tap must end in one of:
- full list rendered and delivered
- explicit degraded fallback (Retry card) delivered
- error logged — never a silent no-response

### DO NOT
- Remove the try/except around `loading = await update.message.reply_text(...)`.
  Telegram TimedOut here IS a known failure mode — must be caught.
- Assume `loading` is not None after the cold-path initial send.
  Always guard: `if loading is not None` before any `loading.*` call.
- Assume `spinner_task` is not None. Check before `.cancel()` and before `wait_for`.
- Remove `asyncio.wait_for(timeout=8.0)` from warm-path delivery.
  Unprotected Telegram sends can stall indefinitely under network pressure.

## Wave W84-Q4 — Premiumization + Header Completion (11 March 2026)

### Header Completeness (LOCKED)
- `handle_tip_detail()` — after `_get_broadcast_details()`, if kickoff is empty,
  extracts date from `tip["match_id"]` (suffix `YYYY-MM-DD`).
  DB-sourced tips (odds.db) have no `commence_time` but match_id always carries the date.
  Returns: "Today", "Tomorrow", "Wed 26 Mar", or "26 Mar" depending on delta.
- Logic: `tip["match_id"].rsplit("_", 1)` → if last part is 10 chars → `date.fromisoformat()`.
- Falls through silently on ValueError — no kickoff shown rather than crashing.

### Low-Context Narrative Quality (LOCKED)

#### `_render_setup_no_context()` — 8 richer variants (W84-Q4)
- Added `fp_str` and `market_implied` computed from `spec.fair_prob_pct` and `spec.odds`.
- Each variant now leads with the analytical observation, not the data absence.
- Price structure treated as evidence: {bk} implies X% vs our Y% = Z% gap.
- Variants foreground: price structure, analytical thesis, pivot from limitation,
  market mechanics, editorial observation, model-vs-market disagreement, bookmaker behaviour, clean decisive.
- DO NOT revert to variants that lead with "No data available" or "Form data isn't available".
  These feel apologetic and are banned from this function.

#### Speculative `_render_edge()` — 6 richer variants (W84-Q4)
- Each variant now explains the TYPE of gap (not just its size):
  bookmaker pricing vs model probability, market mechanics in data-light markets,
  what the divergence means for the bet thesis.
- All variants still reference EV, fair probability, and bookmaker (test requirements).
- All still avoid banned phrases from TONE_BANDS["cautious"].

#### `_build_risk_factors()` confirming==0 — 3 richer variants (W84-Q4)
- Variant 0: explains that model estimate is based on base rates, not current intelligence.
- Variant 1: clarifies what CAN vs CANNOT be verified (the price gap vs what drives it).
- Variant 2: distinguishes historical distributions from current team form.
- All still contain "model", "confirm", or "signal" (test requirement at line 369).

### DO NOT
- Revert `_render_setup_no_context` variants to lead with "No data available" or "Form data isn't available".
- Remove `fp_str` or `market_implied` from `_render_setup_no_context` — they add necessary texture.
- Change the speculative edge variants to drop EV/fair-prob references (breaks test_speculative_mentions_ev_or_probability).
- Add "tread carefully", "pure pricing call", "price is interesting" to any speculative variant (banned).

## Wave W84-Q5 — Detail Header Completion + Low-Context De-Templating (11 March 2026)

### Header Completeness — Root Cause Fixed (LOCKED)

#### Bug: `edge:detail` instant baseline path missing kickoff + broadcast
- Lines 1253-1258 (old) assembled header as: `🎯 match` + `🏆 league` only.
- `_build_hot_tips_page()` computed kickoff + broadcast per tip but did NOT store them in the tip dict.
- Instant baseline path had no access to the list-rendered metadata.
- Fix: `_build_hot_tips_page()` now stores `tip["_bc_kickoff"]` and `tip["_bc_broadcast"]` after computing broadcast data.
- Fix: instant baseline path reads `_it0.get("_bc_kickoff")` and `_it0.get("_bc_broadcast")` and adds `📅` + `📺` lines.

#### Pattern: List render → Detail view header inheritance (LOCKED)
- `_build_hot_tips_page()` MUST store `_bc_kickoff` and `_bc_broadcast` in each tip dict.
- `edge:detail` instant baseline header MUST use these stored values.
- `handle_tip_detail()` accessible path: checks `_bc_kickoff`/`_bc_broadcast` BEFORE `_get_broadcast_details()` fresh call.
- `handle_tip_detail()` locked path: same check applied.
- This ensures list and detail always show the same kickoff/broadcast data.

### DO NOT
- Remove `tip["_bc_kickoff"] = kickoff` from `_build_hot_tips_page()` — detail depends on it.
- Add kickoff/broadcast to `edge:detail` instant baseline without reading from tip dict first.
  Fresh `_get_broadcast_details()` call here would be synchronous DB access on the event loop.
- Remove `_bc_kickoff`/`_bc_broadcast` inheritance guards from `handle_tip_detail()`.

### Low-Context Narrative — Competition-Aware Framing (LOCKED)

#### `_competition_category()` helper (narrative_spec.py — NEW)
- Returns one of: "continental", "international", "club_rugby", "cricket", "combat", "league".
- Categorises competition name string (case-insensitive) for contextual framing.
- Used by `_render_setup_no_context()` to inject `_comp_context` — one sentence per category.

#### `_render_setup_no_context()` — Competition-Aware Variants (W84-Q5)
- Added `_cat = _competition_category(comp)` and `_comp_context` dict (6 category contexts).
- Variants 0, 2: Lead with competition landscape first, then price as evidence.
- Variant 1: Analytical question frame — "is the EV gap real or does the market know something?"
- Variant 3: Bookmaker behaviour in THIS competition type (not generic).
- Variant 5: Base-rate reasoning anchored to competition context.
- Variant 6: Direct, honest, zero apology ("the analysis doesn't pretend otherwise").
- Variant 7: "Market prices become the primary analytical input" — premium framing.
- DO NOT revert variants to lead with data absence or remove `_comp_context`.

#### Speculative `_render_edge()` — Analytically Distinct Variants (W84-Q5)
- Variant 0: Calls the gap type explicitly ("what a base-rate mispricing looks like").
- Variant 1: Bookmaker exposure management angle (why the line can sit wider than true prob).
- Variant 3: "Calibration bet" framing — transparent about what the bet is actually on.
- Variant 4: Resolution path — speculative edges either close pre-kickoff or hold.
- Variant 5: Explicit bet posture — "small exposure, don't overcommit to an unconfirmed signal."
- All variants still reference EV, fair probability, bookmaker (contract tests require it).

## Wave W84-Q6 — My Matches Header Inheritance + Story Layer (11 March 2026)

### My Matches Header Inheritance (LOCKED — DO NOT REVERT)
- `_render_your_games_all()` stores `event["_mm_kickoff"]` and `event["_mm_broadcast"]` after computing them during list render.
- `_generate_game_tips()` falls back to these after fresh `_get_broadcast_details()` call when DB lookup returns empty.
- DO NOT remove the storage step — without it, detail headers drop kickoff/TV for all My Matches events.
- DO NOT remove the fallback — without it, only broadcast_schedule DB hits show full headers in detail view.
- Pattern: list render → store in event dict → detail inherits via `target_event.get("_mm_kickoff")`.

### `_match_shape_note(comp_cat, fixture_type)` (LOCKED)
- Genre description of what kind of game this typically is, based on competition category.
- 6 categories: continental, international, club_rugby, cricket, combat, league.
- Evidence-bounded: describes competition genre only — no team-specific facts, zero hallucination risk.
- Added to `narrative_spec.py` after `_competition_category()`.
- Woven into variants 1, 3, 5, 7 of `_render_setup_no_context()`.
- DO NOT collapse variants back to analytical-only framing — match shape diversity is intentional.

### `_render_setup_no_context()` — Story Layer (W84-Q6, variants 1/3/5/7)
- Variant 1: Question frame + match shape ("what kind of fixture is this?")
- Variant 3: Match shape + bookmaker behaviour (fixture character → why the gap exists)
- Variant 5: Match shape leads (genre first → base-rate context follows)
- Variant 7: Match shape + market price as primary input (alive, complete)
- Variants 0, 2, 4, 6 unchanged — pure analytical framing for diversity.

## Wave W84-Q7 — My Matches Header Injection (11 March 2026)

### Root Cause (LOCKED — DO NOT REPEAT)
- Narrative DB cache stores complete HTML including header block.
- Pre-generated narratives (pregenerate_narratives.py) and cached entries generated before W84-Q6 had incomplete/stale headers.
- Three early-return cache-hit paths served this HTML without rebuilding the header:
  - **Path A** (pre-spinner DB hit): checked `_get_cached_narrative(_pre_mid)` before spinner
  - **Path B** (W60-CACHE hit): checked `_get_cached_narrative(db_match_id)` after spinner
  - **Path C** (`_vs_` early hit): for PSL/DB events on cold tap; `target_event` is None
- W84-Q6's `_mm_broadcast` fallback worked only on the live generation path (no early return).
  Cold-path users (`skip_broadcast=True`) always had `_mm_broadcast = ""` — fallback never fired.

### Three New Helpers (bot.py — LOCKED)
- `_teams_from_vs_event_id(event_id)` — parses `home_vs_away_YYYY-MM-DD` match_id format into display names. Used when `target_event` is None (Path C cold tap).
- `_build_event_header(home_raw, away_raw, target_league, target_event)` — builds fresh header dict:
  1. kickoff: from `commence_time` (rejects 02:00 SAST midnight-UTC PSL placeholders → "TBC")
  2. kickoff fallback: `target_event["_mm_kickoff"]` if 02:00 SAST
  3. broadcast: `target_event["_mm_broadcast"]` first (zero DB cost)
  4. broadcast fallback: `_get_broadcast_details()` → `_get_broadcast_line()`
- `_inject_narrative_header(html, home_raw, away_raw, kickoff, league_display, broadcast_line)` — replaces stale header in cached HTML.
  Finds `📋` (Setup section marker) and replaces everything before it with fresh header lines.
  Fallback: prepends header if no `📋` marker found.
  Header line order: `🎯 Home vs Away`, `📅 kickoff`, `🏆 league`, `📺 broadcast`.

### Application (LOCKED — all three cache-hit paths)
- Each path calls `_build_event_header()` → `_inject_narrative_header()` before serving cached HTML.
- Injected HTML stored in `_analysis_cache[event_id]` — in-memory cache also serves fresh headers.
- Path C passes `target_league=""` and `target_event=None`; `_teams_from_vs_event_id()` provides team names.

### DO NOT
- Remove header injection from any of the three cache-hit paths — stale cache entries persist indefinitely.
- Add `COLLATE NOCASE` to any `odds_snapshots` query (destroys index, see W84-MM2).
- Let Path C skip `_inject_narrative_header()` because `target_event=None` — use `_teams_from_vs_event_id()` instead.
- Revert `_build_event_header()` kickoff midnight-UTC rejection — PSL events store 00:00 UTC = 02:00 SAST as placeholder.

## Wave W84-Q8 — Story Layer Premiumization (11 March 2026)

### Goal
Make thin cards (neutral/no-context) feel like a premium betting story, not a clinical model summary.
Evidence-bounded: zero hallucinated team facts. All new language describes competition genre, not specific teams.

### Changes (narrative_spec.py — LOCKED)

#### `_plural(word)` helper
- Irregular plural dict: `{"clash": "clashes", "match": "matches"}`
- All fixture-type pluralisation uses `_plural()` — no `{word}s` direct concatenation.

#### `_match_shape_note()` rewrite (W84-Q8)
- Richer genre descriptions with tactical/competitive texture
- Uses `_plural()` for fixture_type: "clashes", "fixtures", "matches" etc.
- Continental: knockout stakes, cautious outcomes; International: squad selection uncertainty;
  Club rugby: set-piece + territory, tight margins; Cricket: conditions + toss;
  Combat: stylistic matchup flips market; League: squad quality + model-vs-market gaps

#### `_render_setup_no_context()` — 4 new vocabulary dicts (LOCKED)
All dicts use `_ft_pl = _plural(_fixture_type)` (never `{_fixture_type}s` directly):
- `_game_character` — what this competition type produces as a contest (6 keys)
- `_fixture_context` — pre-match picture for this competition type (6 keys)
- `_sweat_note` — what to watch live, live sweat experience (6 keys)
- `_price_char` — EV-magnitude-based price characterisation (4 levels: ≥8/≥4/≥2/else)
- `_cat_display` — human-readable category name (converts "club_rugby" → "club rugby" etc.)
- `_ev_noun` vs `_ev_label` split: `_ev_noun` = "moderate 3.8% expected value gap" (no article);
  `_ev_label` = f"a {_ev_noun}". Use `_ev_noun` after "That/The"; `_ev_label` after ": " or verb.

Variant frame distribution (8 MD5-deterministic variants):
- V0: Game character leads → price
- V1: Match shape + competition type → price
- V2: Pre-match picture + price divergence
- V3: Match shape + how bookmakers price this type
- V4: Price character + direct editorial voice
- V5: Match shape leads, price as supporting evidence
- V6: Live sweat description + price
- V7: Full immersive frame (game character + sweat + price)

#### `_render_edge()` — enriched speculative variants
- Betting texture added: "worth the exposure, not worth overloading", "measured-exposure play",
  "small stake, open mind", "Size it like a speculative", "hold it lightly and watch the closing price"

#### `_render_risk()` severity notes
- high: "treat this as speculative or pass entirely"
- moderate: "the edge doesn't disappear because of it"
- low: "Risk profile is clean here. Execute with normal sizing."

#### `_render_verdict()` — SA voice
- Speculative: "Worth a unit", "Don't overcommit", "speculative angle — the price is right"
- Lean: "enough signal to commit, not enough to go heavy", "hold it with a clear head"
- Back/Strong: "indicators are doing their job", "depth of support most edges don't get"

### DO NOT
- Use `{_fixture_type}s` directly in any dict or f-string — always use `_ft_pl`.
- Use `{_cat}` directly in user-facing text — use `{_cat_display}`.
- Use `{_ev_label}` after "That/The/this" — it starts with "a" (article doubling).
- Remove the `_cat_display` dict — "club_rugby" must never appear in rendered output.

## Wave W84-Q9 — Hot Tips Header Lock + Story Premiumization (12 March 2026)

### Root Cause: Hot Tips Header Regression (LOCKED — DO NOT REPEAT)

Two distinct `edge:detail` paths, both missing header data:

#### Cache-miss path (instant baseline)
- `_edge_precompute_job()` populates `_game_tips_cache[match_key]` with fresh tip dicts
  that have NO `_bc_kickoff`/`_bc_broadcast` (set only during `_build_hot_tips_page()`).
- `edge:detail` read `_game_tips_cache` first → got precompute tips → empty header.
- **Fix:** After reading `_instant_tips[0]`, enrich from `_ht_tips_snapshot[user_id]` first
  (authoritative: mutated at list-render time), then fall back to `_format_kickoff_display(commence_time)`.

#### Cache-hit path (pregenerated HTML)
- `_inject_narrative_header()` (W84-Q7) was only wired to My Matches paths, not `edge:detail` cache-hit.
- **Fix:** Before serving cached HTML in `edge:detail`, call `_inject_narrative_header()` using
  tip metadata from cached content + snapshot enrichment + `commence_time` fallback.

#### Header inheritance pattern (LOCKED — both Hot Tips paths)
1. `_build_hot_tips_page()` stores `tip["_bc_kickoff"]` and `tip["_bc_broadcast"]` in each tip dict
2. `edge:detail` cache-miss: reads snapshot → falls back to `commence_time` → builds header
3. `edge:detail` cache-hit: reads cached content + snapshot → injects fresh header into HTML
4. DO NOT use `_get_broadcast_details()` as primary in `edge:detail` instant-baseline path — sync DB on event loop.

### Premiumization (narrative_spec.py — LOCKED)

#### `_build_risk_factors()` default (LOCKED — W84-Q9)
- Replaced "Standard match variance applies." with 3 MD5-deterministic human variants:
  - V0: "No specific flags on this one — clean risk profile, size normally."
  - V1: "Nothing obvious stands against this. The usual match-day variables apply."
  - V2: "Price and signals are aligned. Typical match uncertainty is the main remaining variable."
- Seed: `edge_data.get("home_team", "") + edge_data.get("away_team", "")`.
- DO NOT revert — "Standard match variance applies." is a banned clinical phrase.

#### Banned Phrases (LOCKED — do not re-introduce in any path)
- "Standard match variance applies."
- "competition-level averages" (in `_match_shape_note`, `_game_character`, `_fixture_context`)
- "structural signal" / "structural gap" / "structural argument" / "structural difference"
- "model-vs-market gaps" (in `_match_shape_note`, `_game_character`)
- "cleanest signal available"
- "most stable, if least specific, analytical input"
- "base-rate positioning"
- `"When {_cat_display} {_ft_pl} arrive..."` — causes "domestic league domestic league" repetition; use `"When {_ft_pl} like this arrive..."` instead.

### Snapshot Test Fix (LOCKED)
- `TestDetailView` tests use `_TIER_GATE_FOUNDING_PATCH = patch("tier_gate._founding_member_line", ...)`.
- DO NOT use `_FOUNDING_PATCH` (patches `bot._founding_days_left`) — different code path from `tier_gate`.
- Golden files updated to "8 days left" (stable mocked value).

## Wave W84-Q16 — Low-Signal Posture Hardening (12 March 2026)

### Banned Phrases (LOCKED — do not re-introduce in any path)
- "this gap warrants the exposure"
- "worth the exposure, not worth overloading"
- "small unit only"
- "worth a measured look"
- "worth backing" (in any setup/edge context)

### Rules (LOCKED)
- Setup sections = analytical context only. Zero betting recommendations, implicit or explicit.
- Speculative edge sections = describe the gap type and source. Never invite action.
- Speculative verdicts default to monitor/pass posture. No "small unit", no "take the edge".
- Lean edge sections end on engagement framing only ("size it carefully"), not bet endorsement.


## Wave W84-RT6 — Bournemouth Stall + Man City Header Re-Lock (12 March 2026)

### Root Causes Fixed (LOCKED — DO NOT REPEAT)

#### Bournemouth My Matches stall — sync SQLite blocking asyncio
- `_get_broadcast_details()` and `_get_broadcast_line()` are synchronous SQLite calls.
  Calling them directly on the event loop inside `_generate_game_tips()` blocked asyncio
  during DB lock windows. `asyncio.wait_for` cannot fire while the event loop is blocked.
  Telegram connection went stale → final `query.edit_message_text()` failed with TimedOut.
  Final delivery was unprotected (no try/except) → exception propagated to `_generate_game_tips_safe()`
  → recovery handler silently caught → user stuck on "Analysing..." forever.
- Fix 1: Both broadcast calls wrapped in `asyncio.to_thread()` with 3s/2s timeouts.
- Fix 2: Final `query.edit_message_text()` wrapped in try/except → falls back to `reply_text`.
- Fix 3: `_generate_game_tips_safe()` error recovery uses source-aware callbacks:
  `source="matches"` → `yg:game:` + "Back to My Matches" (was always using Hot Tips callbacks).

#### Man City header drops in Hot Tips detail — missing date fallback
- After bot restart, `_ht_tips_snapshot[user_id]` is cleared.
  CL tips in `_game_tips_cache` (from `_edge_precompute_job`) have no `_bc_kickoff`.
  `commence_time=""` for all DB-sourced tips.
  CL/UCL matches not in DStv `broadcast_schedule` → last-resort broadcast lookup returns empty.
  No date-from-match_id fallback existed in the instant-baseline path.
- Fix 4: Added date-from-match_id fallback after last-resort broadcast lookup.
  Reads YYYY-MM-DD suffix from match_key → formats as "Today" / "Tomorrow" / "Wed 12 Mar".
  Mirrors the same fallback in `_build_hot_tips_page()` (lines 5016-5034).

### Architecture (LOCKED)
- `asyncio.to_thread()` is REQUIRED for all synchronous SQLite calls inside async handlers.
  Default `_BUSY_MS = 30,000ms` — any sync call during a scraper write window can block for
  30 seconds, making `asyncio.wait_for` ineffective and stalling Telegram delivery.
- DO NOT add bare sync `_get_broadcast_details()` / `_get_broadcast_line()` calls in any
  async function — always use `asyncio.to_thread()` with a 3s or shorter timeout.
- DO NOT leave final `query.edit_message_text()` unprotected in any breakdown flow.
  Telegram API can time out even after content is ready — always have a `reply_text` fallback.
- `_generate_game_tips_safe()` source parameter MUST be respected in error recovery callbacks.
  My Matches taps use `source="matches"` → `yg:game:` + `yg:all:0`.
  Hot Tips taps use `source="edge_picks"` → `edge:detail:` + `hot:back:N`.

### Test Results (W84-RT6)
- Full unit suite: 1161 passed, 3 skipped, 0 failures
- Contract + snapshot tests: 263 passed
- Live validation (w84_rt1): 9/10 (1 pre-existing)
- Live validation (w84_p1): 33/34 (1 pre-existing timing flakiness)
- Narrative validation: 54/56 (2 pre-existing)

## Data Feeds

### Data Feeds → Coach Data (manual curation)

**Files**
- `scrapers/coaches.json` — structured `{sport: {team_key: {"name": "...", "last_verified": "YYYY-MM-DD", "note": "..."}}}`. System of record. Loaded by `bot/narrative_spec.lookup_coach()` and `scrapers/match_context_fetcher._get_coach()`.
- `bot/data/coaches.json` — flat `{team_key: ["First Last", "Surname"]}`. Mirror for the fact-checker whitelist (`evidence_pack._build_verified_coaches`). Must stay in sync with the soccer section of the structured file.

**Cadence** — audit every 14 d, or immediately on any public head-coach change for EPL / La Liga / Bundesliga / Serie A / Ligue 1 / UCL / PSL / URC / Super Rugby / Six Nations / IPL / SA20 / T20 World Cup.

**Audit procedure**
1. Pull top of `scrapers/coaches.json`. Identify entries with `last_verified > 7 d` (get counts from `bot/narrative_integrity_monitor.py::freshness_check`).
2. Cross-check against club official sites, Wikipedia (history table, not the infobox), BBC/SuperSport editorial.
3. Edit `scrapers/coaches.json`: update `name` if it changed, set `last_verified` to today's ISO date. If unable to confirm, keep the value and set `note: "Unverified in audit YYYY-MM-DD — carried forward"`.
4. If a soccer entry changed, mirror into `bot/data/coaches.json` using flat format `["First Last", "Surname"]`.
5. Commit with message `audit(coaches): verify N teams, update K coaches (INV/audit wave)` on `main`. No runtime restart required — both files are read fresh on lookup (no in-process cache).

**Automated drift detection** (after BUILD-COACHES-MONITOR-WIRE-01 ships)
- `scripts/monitor_narrative_integrity.py` runs every 30 min; a new `coach_freshness` signal flags when ≥ 10 % of entries are older than 7 d.
- EdgeOps receives Telegram alert + GlitchTip event. 2 h debounce.

**Do not**
- Do not re-enable `scrapers/transfermarkt_coaches.py` — WAF block persists (INV-COACHES-TRANSFERMARKT-RESCUE-01).
- Do not add `coaches.json` as an edge signal. It is narrative-only by design.
- Do not delete stale entries — `note` them; deletion breaks the fact-checker whitelist.

## Narrative Generation Pipeline (NARRATIVE-ACCURACY-01 — LOCKED 22 Apr 2026)

Five permanent rules for all narrative generation work. Read before touching
`scripts/pregenerate_narratives.py`, `narrative_spec.py`, `evidence_pack.py`,
or any narrative quality gate.

### Rule 1 — Pre-computed derived claims (no LLM-derived counts)
`build_derived_claims(h, a, sport)` is the required facts pre-processor for all
narrative generation. Do NOT call the LLM to derive form counts, streak lengths,
or home/away venue labels — compute them in Python first. The derived block is
injected above the raw facts with the instruction: *"Do NOT compute your own
counts. Every specific number, streak, or venue label MUST appear exactly as
written below."* Root cause of the 12 v1 FAILs: LLM was doing extraction +
prose in a single pass, introducing hallucinations at the extraction step.

### Rule 2 — CURRENT_STADIUMS dict is a live data integrity component
`CURRENT_STADIUMS` maps club → current 2025/26 ground name. Any club ground
change MUST be reflected here before the next cron run, not after. Failing to
update caused Everton "Goodison" errors (Everton moved to Hill Dickinson Stadium
in August 2025). Clubs to watch for upcoming moves: none confirmed for 2025/26
beyond Everton (already added). Add maintenance task to any wave brief that
touches `CURRENT_STADIUMS`.

### Rule 3 — Post-generation validator + one retry before publishing
`generate_and_validate()` (wrapping `generate_section()`) is required before
any narrative reaches `narrative_cache`. Validator runs a second LLM call at
`temperature=0` checking every claim against DERIVED CLAIMS. On failure, one
retry at `temperature=0.5` with violation list as banned phrases. If retry also
fails, publishes best-effort with ⚠ flag and logs to `narrative_skip_log`.
Do NOT publish first-draft narratives directly to cards. Store
`setup_validated`, `verdict_validated`, `setup_attempts`, `verdict_attempts`
on the narrative record for monitoring.

**Validator calibration note:** false-positive rate on verdicts is ~25%.
Arithmetic derivations ("twelve wins from sixteen games" for W12+D2+L2=16)
and standard paraphrases ("winless in five") are sometimes rejected by the
validator but are factually correct. These cause retries but do NOT represent
published accuracy failures. Do not over-tighten the validator to chase this
number — the calibration already whitelists arithmetic derivations and known
stadium names.

### Rule 4 — Sport-aware handlers (no football-only pipeline for rugby/cricket)
Narrative generation is sport-aware. `build_derived_claims(h, a, sport)` dispatches:
- Football (EPL/UCL/PSL/La Liga etc.) → `_derived_soccer()`
- Rugby (URC/Super Rugby) → `_derived_rugby()` — uses tries/bonus points schema, prohibits football terminology
- Cricket IPL/SA20 → `_derived_cricket_ipl()` — NRR as primary differentiator; runs/wickets vocabulary
- Cricket Test → `_derived_cricket_test()` — conservative handler for sparse ESPN data; blocks invented stats explicitly

Running the football-only pipeline on rugby or cricket produces "?" placeholders
and incorrect venue labels. Never use `_derived_soccer()` for non-football sports.

### Rule 5 — Verdict is story-close flavour, NOT a bet instruction
Verdict copy = SA braai analyst voice: manager names, team nicknames, narrative
punch line. Explicitly not a bet instruction. Price / EV / bookmaker are displayed
elsewhere on the card. Selected voice direction: **V1 — Story close** (confirmed
in NARRATIVE-ACCURACY-01 Part 2 voice testing). The wrong direction (V2) is
bet-instruction style ("back at 1.45, measured single") — rejected. If a verdict
reads like a sizing call, that is a voice regression. Refer to the `verdict-generator`
skill and `narrative_spec.TONE_BANDS` for the allowed/banned phrase sets.

### Rule 6 — SA Braai Voice (BUILD-NARRATIVE-VOICE-01 — LOCKED 22 Apr 2026)
All LLM-generated narrative sections MUST use SA voice (enforced in prompt by
`format_evidence_prompt()` in `evidence_pack.py`):
- Team nicknames: Amakhosi (Chiefs), The Bucs (Pirates), Brazilians/Downs (Sundowns),
  Bafana (SA soccer), Proteas (SA cricket), Boks/Springboks (SA rugby),
  Bulls/Stormers/Sharks/Lions (URC franchises)
- Manager convention: surname-only possessive — Arteta's Arsenal, Slot's Reds, Amorim's United
- Cite at least ONE specific number in the verdict (odds, EV%, streak, H2H record)
- FORBIDDEN: "proceed with caution", "worth backing", "value play", "guaranteed",
  "one to watch", "smart money", and all British hedging phrases
- Verdict MUST end in a sentence terminator (. ! ? …) — Gate 3 in `min_verdict_quality()`
- `VERDICT_HARD_MAX = 260` chars (soft target band: 140–200 chars)
- `max_tokens` for verdict-only Sonnet calls: ≥ 180 (`_generate_verdict()` in bot.py)

### Rule 7 — Tier-Aware Pregen Horizon (BUILD-NARRATIVE-VOICE-01 amended 2026-04-25)

Premium-tier (Diamond + Gold) edges: pregen horizon = 240h ahead (full Edge Picks lookahead). Standard-tier (Silver + Bronze) edges: pregen horizon = 48h ahead. Implementation: `discover_pregen_targets(hours_ahead_premium=240, hours_ahead=48)`. Rationale: AI Breakdown coverage gap closure (INV-AI-BREAKDOWN-COVERAGE-01 → FIX-AI-BREAKDOWN-COVERAGE-01). Cost validation: post-WAVE-02 baseline $3.93/mo + this fix +$7.30/mo = $11.23/mo total, within $60/mo budget. The lock prevents downward revert (240h → 96h or below); upward extensions are explicit policy decisions.

### Rule 8 — Setup section is bookmaker-/odds-/probability-language-free across BOTH polish (w84) AND deterministic baseline (w82) paths (FIX-PREGEN-SETUP-PRICING-LEAK-01 — LOCKED 2026-04-25; hardened FIX-PREGEN-SETUP-PRICING-LEAK-02 — LOCKED 2026-04-25; extended to baseline FIX-W82-BASELINE-PRICE-TALKING-01 — LOCKED 2026-04-27)

The Setup section in narrative polish output MUST NOT contain odds, bookmaker names, decimal probabilities, integer probabilities, EV percentages, "implied probability", "fair value", "Elo-implied", or any pricing/probability vocabulary. Polish prompts (`format_evidence_prompt` in `evidence_pack.py` — BOTH the edge branch and the match_preview branch) MUST NOT instruct Sonnet to pivot to "line movements" or "odds structure" inside Setup. Decimal numbers are allowed in Setup ONLY inside qualified metric phrases ("X.X goals per game", "X.X points per game", "X.X runs per game"). Probabilities are expressed as qualitative descriptors only (e.g. "strong favourites", "comfortable home edge") — no integer percentages either. Polish-time enforcement: `_validate_polish` gate 8a calls BOTH `_find_stale_setup_patterns` (cache-read absolute-ban detector — `bot.py:16307-16347`) AND `_find_setup_strict_ban_violations` (polish-time strict-ban enforcer — `bot.py` immediately after the cache-read detector). The cache-read detector remains a stale-pricing absolute-ban (NOT a staleness check) — relaxing it reopens the BUILD-NARRATIVE-WATERTIGHT-01 leak vector. Use `_has_stale_setup_context_claims` for time-based gating. The polish-time enforcer covers integer-percentage probabilities, isolated banned tokens (e.g. "implied" without proximate decimal), and Elo-implied phrasing — leak shapes the cache-read detector deliberately does not address. **The W82 baseline path** enforces via `_validate_baseline_setup` at the `_store_narrative_cache` callsite — narratives that fail the scan log `BASELINE REJECT: setup-pricing-leak` and skip persistence (the in-memory `_analysis_cache` already serves; the next pregen cycle rebuilds from cleaned templates). Both helpers are locked — do not relax without monitoring evidence. Regression guard: `tests/contracts/test_setup_pricing_ban.py` covers prompt instruction (both branches), the polish gate (positive + negative + integer-prob + banned-token + decimal-prob + Elo-implied + clean), the baseline-time helper (delegation + return parity), AND a 125-fixture fuzzing matrix (5 sports × 25 fixtures × 5 coverage profiles) asserting zero strict-ban hits across the full W82 baseline.

### Rule 9 — Verdict prose must cite a Risk factor (locked 2026-04-25, FIX-NARRATIVE-RISK-RESOLUTION-01)

The Verdict section in narrative polish output MUST reference at least one specific risk factor from The Risk section — either resolving it ("discount the injury concern"), hedging on it ("live with the squad-rotation risk"), or pricing it ("the form gap is already in the number"). Generic closers like "all things considered" do not satisfy. Polish prompts (`format_evidence_prompt` Verdict instruction in `evidence_pack.py`, BOTH the edge branch and the match_preview branch) MUST carry the VERDICT-CITES-RISK instruction. Polish-time enforcement: `_validate_polish` gate 8c calls `_find_risk_resolution_violations` (Jaccard token-overlap between Risk and Verdict sections, threshold `_RISK_RESOLUTION_MIN_JACCARD = 0.10`). Constant is tunable; lower bound 0.07 (over-rejection), upper bound 0.15 (false negatives). Gate fires on two patterns: `verdict_ignores_risk:overlap=N.NN` (Jaccard below threshold) and `risk_boilerplate` (boilerplate phrase + < 6 meaningful tokens in Risk). The Risk→Verdict cohesion is what makes the card read like one analytical voice rather than two stapled outputs. Regression guard: `tests/contracts/test_risk_resolution.py` (10 tests).

### Rule 10 — Rating numbers in polish must match the evidence pack (locked 2026-04-25, FIX-NARRATIVE-RATING-ANCHOR-01; tolerance widened 2026-04-27, FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01)

Any 4-digit Elo or Glicko-2 rating number (range 1000–2999) cited in a narrative polish pass MUST appear verbatim (within ±5 pts absolute) in the `[TEAM RATINGS ANCHOR]` evidence section. Sonnet must never invent, estimate, or copy rating numbers from example prompts. Root cause of fabrication: the prompt example `'1853 vs 1551'` was Arsenal's literal Elo values; Sonnet copied these to other matches. Implementation: `_build_team_ratings_anchor()` and `_format_team_ratings_section()` in `evidence_pack.py` query `team_ratings` (Glicko-2 `mu`) and `elo_ratings` tables and inject them as `[TEAM RATINGS ANCHOR]`. Both `format_evidence_prompt()` Setup instructions carry the RATING ANCHOR LAW and the omission rule ("if anchor absent, omit rating numbers entirely"). Polish-time enforcement: `_validate_polish` gate 8d calls `_find_rating_anchor_violations(polished, evidence_pack.get("team_ratings"))`. Gate fires on: `no_team_ratings_anchor` (4-digit cited but no anchor provided), `fabricated_rating:N` (cited number outside tolerance from all anchors), `fabricated_gap:N` (cited rating differential outside tolerance from actual). Tolerance: `_RATING_TOLERANCE = 5.0`. The validator accepts either the Glicko-2 OR Elo value as a valid anchor — whichever is available. AC-6 cache invalidation: 4 affected match IDs expired on 2026-04-25. Regression guard: `tests/contracts/test_rating_anchor.py` (17 tests).

Tolerance widened 2.0 → 5.0 (FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01, 2026-04-27) to absorb daily Glicko-2 cron drift on stable team ratings (parent INV-NARRATIVE-AUDIT-LAUNCH-DAY-01 observed 5–15pt average shifts per cron cycle). Tightening below 5.0 is forbidden without monitoring evidence of false-fabrication rate < 1% across a 7-day window. Widening above 10.0 risks losing precision on genuine fabrications — do not exceed without an alternative anchor mechanism (e.g. cache-invalidation hook on the cron itself, dispatched as P3 brief FIX-NARRATIVE-CACHE-INVALIDATE-ON-RATING-UPDATE-01 if AC-9 24h soak shows the widening was insufficient).

### Rule 11 — Combat-sport prose must anchor to evidence_pack only (locked 2026-04-25, FIX-NARRATIVE-MMA-LORE-01)

For boxing, MMA, UFC, Bellator, ONE FC and other combat fixtures (sport keys in `_COMBAT_SPORT_KEYS`), narrative polish output across ALL 4 sections (Setup, Edge, Risk, Verdict) MUST draw exclusively from `evidence_json.fighter_records`, `evidence_json.sharp_lines` / SA bookmaker odds, and `evidence_json.espn_context`. Generic LLM-training-knowledge lore phrases — both classic fight-game tropes ("historically", "the fight game", "in the fight business", "in his prime", "warrior spirit", "warrior's heart", "the heart of a champion", "bread and butter", "check the ledger", "old guard", "changing of the guard", "the division reads") and generic divisional/filler vocabulary observed in the W84 INV-flagged corpus ("in combat sports", "psychological and logistical advantages", "championship-level MMA", "inherent unpredictability of MMA", "challenger's mentality", "the promotion's ruleset", "submission vulnerability", "fight-night adjustments", "double-edged sword") — are banned. Invented stylistic profiles ("aggressive striking combinations", "wrestling credentials", "methodical approach") without verbatim source in fighter_records are also banned. When the evidence pack is thin, prefer brevity over fabrication. Implementation: `_COMBAT_SPORT_KEYS` (frozenset) and `_COMBAT_LORE_BANNED_PHRASES` (tuple) in `bot.py` are the canonical lists; mirror constant `_COMBAT_SPORT_KEYS_SET` in `evidence_pack.py` MUST stay in sync. Both `format_evidence_prompt()` branches carry the COMBAT-SPORT EVIDENCE LAW block when `pack.sport in _COMBAT_SPORT_KEYS_SET`. Polish-time enforcement: `_validate_polish` gate 8e calls `_find_combat_lore_violations(polished, spec.sport)`. Gate fires on `combat_lore:<phrase>` for each unique banned phrase hit (deduped). Banned-phrase list is calibrated empirically against W84 corpus; do NOT relax without monitoring evidence of FP rate > 5% per AC-9. Brief-listed "has been a", "this division has", "new wave" were dropped pre-launch — false-positive risk too high in non-lore contexts. Regression guard: `tests/contracts/test_combat_lore.py` (38 tests).

### Rule 12 — W82 baseline templates carry NO pricing vocabulary in Setup (locked 2026-04-27, FIX-W82-BASELINE-PRICE-TALKING-01)

All `_render_setup_*` and `_render_baseline_*` helpers in `narrative_spec.py` MUST emit Setup bodies free of: `price`, `priced`, `bookmaker`, `odds`, `implied`, `implied probability`, `implied chance`, `fair probability`, `fair value`, `expected value`, `model reads`, `market architecture`. Pricing vocabulary belongs in The Edge section, not Setup. The W82 deterministic baseline path bypasses `_validate_polish` gate 8a, so the templates themselves must be clean by construction PLUS a defence-in-depth scan must run at the persistence callsite. Implementation: (a) `_render_setup_no_context` in `narrative_spec.py` was rewritten under FIX-W82-BASELINE-PRICE-TALKING-01 — `price_band` → `posture_band` (renamed; `"competitive price point"` → `"balanced contest"`), `price_map` → `posture_map` (10 variants rewritten in non-pricing language), `close_map` (4 variants rewritten); (b) `_validate_baseline_setup(narrative)` in `bot.py` is a thin wrapper around `_find_setup_strict_ban_violations` that names the baseline-time call site distinctly; (c) `_store_narrative_cache` invokes the scan when `narrative_source == "w82"` and skips persistence on hit (logs `BASELINE REJECT: setup-pricing-leak`). Production-cache surface area was 0 at deploy time (preventive fix — the variant 4 "let the price do the talking" trigger conditions weren't matching live fixtures, but the bug was in code). Fuzzing regression guard at `tests/contracts/test_setup_pricing_ban.py::test_baseline_setup_fuzzing_strict_ban_zero` — 125 combinations (5 sports × 25 fixtures × 5 coverage profiles) sweep every cell of the posture × signal × ev × score variant matrix, asserting both `_find_setup_strict_ban_violations` returns `[]` AND `"market architecture"` is absent (the latter is not in the strict-ban token list, so explicitly checked).
