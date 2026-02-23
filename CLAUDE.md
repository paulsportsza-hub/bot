# MzansiEdge — CLAUDE.md

## Overview
AI-powered sports betting Telegram bot for South Africa. Uses python-telegram-bot v20+ (PTB), Claude API for AI tips, The Odds API for live odds, and async SQLAlchemy for persistence.

## Architecture

```
bot.py              ← Main bot: handlers, onboarding, picks, callback routing
config.py           ← Environment config, sport/league definitions, TOP_TEAMS, aliases, risk profiles
db.py               ← Async SQLAlchemy models & helpers
scripts/
  odds_client.py    ← The Odds API client, EV calculation, value bet scanning, pick cards
tests/
  conftest.py       ← Pytest fixtures (mock bot, in-memory DB)
  test_config.py    ← Sport categories, leagues, fav types, aliases, risk profiles
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

## Picks / Value Bet Flow
1. User taps "Today's Picks" button or sends `/picks`
2. Bot shows loading message with randomised verb template
3. Loads user's risk profile from DB (conservative/moderate/aggressive)
4. Fetches live odds for user's preferred leagues via `fetch_odds()`
5. For each event, calculates fair probabilities (vig-removed market consensus)
6. Computes EV% for each outcome: `(best_odds × fair_prob - 1) × 100`
7. Filters to positive EV above profile's `min_ev` threshold
8. Computes Kelly criterion stake for each value bet
9. Ranks by EV descending, shows top 10 as pick cards
10. Pick cards show: match, outcome, best odds@bookmaker (🇿🇦 for SA books), EV%, confidence, Kelly stake

### Risk Profile Thresholds
| Profile      | min_ev | Kelly fraction | Max stake % |
|-------------|--------|----------------|-------------|
| Conservative | 5%     | 0.25           | 2%          |
| Moderate     | 3%     | 0.50           | 5%          |
| Aggressive   | 1%     | 1.00           | 10%         |

### SA Bookmakers (highlighted with 🇿🇦)
betway, hollywoodbets, supabets, sportingbet, sunbet, betxchange, playabets, gbets

## Admin Commands
- `/admin` — Dashboard showing Odds API quota (requests used/remaining) and bot stats
- `/stats` — Legacy stats command (user count, tip results)

## Onboarding Quiz Flow (7 steps)
1. **Experience level** — Experienced / Casual / Newbie (routes post-onboarding differently)
2. **Sports selection** — Category-based grid (Soccer, Rugby, Cricket, Tennis, Boxing, MMA, Basketball, American Football, Golf, Motorsport, Horse Racing)
3. **League selection** — Per selected sport, toggle leagues. **Single-league sports auto-select** (e.g. NFL, UFC).
4. **Favourites** — Multi-select buttons of top teams/players per sport. "Type manually" option with fuzzy matching. Horse racing skipped (fav_type="skip"). Sport-appropriate language (team/player/fighter/driver).
5. **Risk profile** — Conservative / Moderate / Aggressive
6. **Notification time** — 7 AM / 12 PM / 6 PM / 9 PM
7. **Summary** — Review all selections with **edit buttons**: "Edit Sports & Favourites" and "Edit Risk & Notifications". Confirm with "Let's go!"

### Post-onboarding routing by experience:
- **Experienced** → Straight to picks (auto-triggers `_do_picks`)
- **Casual** → Main menu
- **Newbie** → Mini-lesson explaining odds in Rands

### Fuzzy matching (manual favourite input)
Pipeline: alias check → exact match → partial match → `difflib.get_close_matches`. Shows "Did you mean?" with top 3 suggestions. Falls back to accepting raw input.

State tracked in `bot._onboarding_state[user_id]` dict.

## Profile Reset
Settings → "🔄 Reset Profile" → warning screen → "Yes, reset everything" → clears all prefs, risk, experience, onboarding_done in DB → redirects to onboarding. Betting history/stats NOT deleted.

## DB Models
- `User` — id, username, first_name, risk_profile, notification_hour, onboarding_done, experience_level, education_stage
- `UserSportPref` — user_id, sport_key, league, team_name
- `Tip` — sport, match, prediction, odds, result
- `Bet` — user_id, tip_id, stake

### Key DB helpers
- `reset_user_profile(user_id)` — Wipe all user preferences but keep account + history
- `clear_user_sport_prefs(user_id)` — Delete all sport prefs for a user

## Persistent Menu System
Main menu: `kb_main()` → Daily Briefing | My Bets | My Teams | Stats | Bookmakers | Settings

Sub-menus: `kb_bets()`, `kb_teams()`, `kb_stats()`, `kb_bookmakers()`, `kb_settings()`
Every sub-screen has "🔙 Back" + "🏠 Main Menu" via `kb_nav()`.

## Experience-Adapted Pick Cards
`format_pick_card(pick, experience="experienced")` in `scripts/odds_client.py`:
- **Experienced**: compact stats — odds, EV%, Kelly stake fraction
- **Casual**: narrative — "We like X", R100 payout, stake hint (no Kelly)
- **Newbie**: full hand-holding — bet type explained, payout in R20/R50, "Start small" advice

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
# Run all tests (209 tests)
pytest tests/ -x -q

# Run specific test file
pytest tests/test_onboarding.py -v

# Start the bot
python bot.py
```

## Environment Variables
See `.env.example` for required variables:
- `BOT_TOKEN` — Telegram bot token
- `ODDS_API_KEY` — The Odds API key
- `ANTHROPIC_API_KEY` — Claude API key
- `ADMIN_IDS` — Comma-separated Telegram user IDs
- `TZ` — Timezone (default: Africa/Johannesburg)
- `DATABASE_URL` — SQLAlchemy async URL
