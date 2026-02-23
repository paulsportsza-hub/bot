# PaulSportSA — CLAUDE.md

## Overview
AI-powered sports betting Telegram bot for South Africa. Uses python-telegram-bot v20+ (PTB), Claude API for AI tips, The Odds API for live odds, and async SQLAlchemy for persistence.

## Architecture

```
bot.py              ← Main bot: handlers, onboarding, callback routing
config.py           ← Environment config, sport definitions (SA + Global tiers)
db.py               ← Async SQLAlchemy models & helpers
scripts/
  odds_client.py    ← The Odds API client (fetch_odds, best_odds, format_odds_message)
tests/
  conftest.py       ← Pytest fixtures (mock bot, in-memory DB)
  test_config.py    ← Sports structure, risk profile tests
  test_db.py        ← User CRUD, sport prefs, bet creation tests
  test_odds_client.py ← EV calc, best_odds, format_odds (mocked HTTP)
  test_bot_handlers.py ← /start, /menu, /help handler tests
  test_onboarding.py   ← Full onboarding quiz state machine tests
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
- `ob_sport:psl` — Toggle PSL in onboarding
- `ob_league:epl:English Premier League` — Toggle league
- `ob_risk:moderate` — Select risk profile
- `ob_notify:18` — Select 6 PM notifications
- `ob_done:finish` — Complete onboarding

## Onboarding Quiz Flow
1. **Sports selection** — Two-tier: SA first (🇿🇦 header), then Global (🌍 header)
2. **League selection** — Per selected sport, toggle leagues
3. **Team selection** — Type favourite team per sport (optional, skip available)
4. **Risk profile** — Conservative / Moderate / Aggressive
5. **Notification time** — 7 AM / 12 PM / 6 PM / 9 PM
6. **Summary** — Review all selections, confirm with "Let's go!"

State tracked in `bot._onboarding_state[user_id]` dict.

## DB Models
- `User` — id, username, first_name, risk_profile, notification_hour, onboarding_done
- `UserSportPref` — user_id, sport_key, league, team_name
- `Tip` — sport, match, prediction, odds, result
- `Bet` — user_id, tip_id, stake

## Conventions
- HTML parse_mode throughout all messages
- PTB v20+ async handlers
- Inline keyboards only (no reply keyboards)
- `prefix:action` callback_data routing in `on_button()`

## Verification
```bash
# Run all tests
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
