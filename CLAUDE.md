# MzansiEdge — CLAUDE.md

## Overview
AI-powered sports betting Telegram bot for South Africa. Uses python-telegram-bot v20+ (PTB), Claude API for AI tips, The Odds API for live odds, and async SQLAlchemy for persistence.

## Architecture

```
bot.py              ← Main bot: handlers, onboarding, picks, callback routing
config.py           ← Environment config, sport definitions (SA + Global tiers), risk profiles
db.py               ← Async SQLAlchemy models & helpers
scripts/
  odds_client.py    ← The Odds API client, EV calculation, value bet scanning, pick cards
tests/
  conftest.py       ← Pytest fixtures (mock bot, in-memory DB)
  test_config.py    ← Sports structure, risk profile tests
  test_db.py        ← User CRUD, sport prefs, bet creation tests
  test_odds_client.py ← best_odds, format_odds (mocked HTTP)
  test_bot_handlers.py ← /start, /menu, /help handler tests
  test_onboarding.py   ← Full onboarding quiz state machine tests
  test_picks.py        ← EV calc, Kelly stake, value bet scanning, pick cards, /admin
  test_day1.py         ← Experience onboarding, persistent menu, adapted pick cards
```

## Sports Structure

### 🇿🇦 SA Sports (`config.SA_SPORTS`)
| Key          | Label         | API Key                        |
|-------------|---------------|--------------------------------|
| psl         | PSL           | None (not on Odds API)         |
| bafana      | Bafana Bafana | soccer_africa_cup_of_nations   |
| urc         | URC           | None                           |
| super_rugby | Super Rugby   | None                           |
| currie_cup  | Currie Cup    | None                           |
| csa_cricket | CSA Cricket   | cricket_international_t20      |

### 🌍 Global Sports (`config.GLOBAL_SPORTS`)
| Key         | Label              | API Key                            |
|------------|--------------------|------------------------------------|
| epl        | EPL                | soccer_epl                         |
| la_liga    | La Liga            | soccer_spain_la_liga               |
| bundesliga | Bundesliga         | soccer_germany_bundesliga          |
| serie_a    | Serie A            | soccer_italy_serie_a               |
| ligue_1    | Ligue 1            | soccer_france_ligue_one            |
| ucl        | Champions League   | soccer_uefa_champs_league          |
| nba        | NBA                | basketball_nba                     |
| nfl        | NFL                | americanfootball_ncaaf             |
| nhl        | NHL                | icehockey_nhl                      |
| mlb        | MLB                | baseball_mlb_preseason             |
| atp        | ATP Tennis         | tennis_atp_dubai                   |
| wta        | WTA Tennis         | None                               |
| mma        | UFC / MMA          | mma_mixed_martial_arts             |
| golf       | Golf Majors        | golf_masters_tournament_winner     |
| ipl        | IPL                | cricket_ipl                        |
| big_bash   | Big Bash           | cricket_big_bash                   |
| t20_wc     | T20 World Cup      | cricket_t20_world_cup              |
| six_nations| Six Nations        | rugbyunion_six_nations             |
| rwc        | Rugby World Cup    | None                               |

## Callback Data Pattern
All inline keyboard callbacks use `prefix:action` format:
- `sport:epl` — View odds for EPL
- `ai:nba` — AI tip for NBA
- `menu:home` — Main menu
- `picks:today` / `picks:go` — Today's value bet picks
- `ob_exp:experienced` / `ob_exp:casual` / `ob_exp:newbie` — Experience level
- `ob_sport:psl` — Toggle PSL in onboarding
- `ob_league:epl:English Premier League` — Toggle league
- `ob_risk:moderate` — Select risk profile
- `ob_notify:18` — Select 6 PM notifications
- `ob_done:finish` — Complete onboarding
- `bets:active` / `bets:history` — My Bets sub-menu
- `teams:view` / `teams:edit` — My Teams sub-menu
- `stats:overview` / `stats:leaderboard` — Stats sub-menu
- `affiliate:compare` / `affiliate:sa` / `affiliate:intl` — Bookmakers sub-menu
- `settings:home` / `settings:risk` / `settings:notify` / `settings:sports` — Settings sub-menu

## Picks / Value Bet Flow
1. User taps "Today's Picks" button or sends `/picks`
2. Bot shows loading message with randomised verb template
3. Loads user's risk profile from DB (conservative/moderate/aggressive)
4. Fetches live odds for user's preferred sports via `fetch_odds()`
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
2. **Sports selection** — Two-tier: SA first (🇿🇦 header), then Global (🌍 header)
3. **League selection** — Per selected sport, toggle leagues
4. **Team selection** — Type favourite team per sport (optional, skip available)
5. **Risk profile** — Conservative / Moderate / Aggressive
6. **Notification time** — 7 AM / 12 PM / 6 PM / 9 PM
7. **Summary** — Review all selections, confirm with "Let's go!"

### Post-onboarding routing by experience:
- **Experienced** → Straight to picks (auto-triggers `_do_picks`)
- **Casual** → Main menu
- **Newbie** → Mini-lesson explaining odds in Rands

State tracked in `bot._onboarding_state[user_id]` dict.

## DB Models
- `User` — id, username, first_name, risk_profile, notification_hour, onboarding_done, experience_level, education_stage
- `UserSportPref` — user_id, sport_key, league, team_name
- `Tip` — sport, match, prediction, odds, result
- `Bet` — user_id, tip_id, stake

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
- `prefix:action` callback_data routing in `on_button()`
- Loading messages use randomised verb templates

## Verification
```bash
# Run all tests (154 tests)
pytest tests/ -x -q

# Run specific test file
pytest tests/test_picks.py -v

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
