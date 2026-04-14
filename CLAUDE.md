# StavidBot — Claude Code Context

## Project Overview
Discord bot for David and Stephanie managing apartment life and personal habit tracking.
Named "Stavid" (Stephanie + David).

## Tech Stack
- **Python 3.12** (see `runtime.txt`)
- **discord.py 2.5+** — slash commands via `app_commands`
- **SQLAlchemy 2.0 async** + **asyncpg** — all DB ops are async
- **Alembic** — migrations (autogenerate-friendly)
- **PostgreSQL** — hosted on Heroku Postgres
- **Heroku** — worker dyno (`worker: python -m src.main`) + release phase (`alembic upgrade heads`)

## Project Structure
```
src/
  main.py        — Bot entrypoint; auto-loads all cogs in src/cogs/
  db.py          — SQLAlchemy engine, Base, all ORM models
  utils.py       — Shared helpers (resolve_partner, user IDs)
  cogs/
    basic.py     — /help, /wifi
    budget.py    — /venmo, /pay, /rent, /wifi_bill, /ledger
    reminders.py — /remind, /reminders, /reset_reminders (stubs)
migrations/
  versions/      — Alembic migration files
```

## Key Conventions

### Adding a New Feature
1. Add the ORM model to [src/db.py](src/db.py) (under the `Base` class)
2. Run `alembic revision --autogenerate -m "description"` to generate migration
3. Create or edit a cog in `src/cogs/` — the bot auto-loads everything in that package
4. Cogs must end with `async def setup(bot): await bot.add_cog(YourCog(bot))`

### Database Sessions
Always use `async with self.bot.db() as s:` — never create your own engine.

### Partner Resolution
Use `resolve_partner(interaction)` from `src/utils.py` to get the other user. Relies on `PARTNER_IDS` env var.

### Background Tasks
Use `discord.ext.tasks` loop decorators inside a cog. Start them in `cog_load` or `on_ready`.

## Environment Variables
| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `DATABASE_URL` | PostgreSQL connection string (Heroku sets this automatically) |
| `PARTNER_IDS` | Comma-separated Discord user IDs for David and Stephanie |
| `wifi_name` | Guest WiFi SSID |
| `wifi_password` | Guest WiFi password |
| `DB_SSLMODE` | Override SSL mode (optional; defaults to `require` for non-local hosts) |
| `DB_TRUST_PROXY` | Set `1` to skip cert verification (dev only) |

Copy `.env.example` to `.env` for local development. `.env.local` overrides `.env`.

## User IDs (hardcoded in utils.py)
- `DAVID_ID = 240608458888445953`
- `STEPH_ID = 694650702466908160`
- `TEST_GUILD_ID = 1401585357799292958` (in main.py)

## Deployment (Heroku)
- Dyno type: **worker** (not web — no HTTP server)
- Release phase runs `alembic -c alembic.ini upgrade heads` automatically on deploy
- Push to Heroku via `git push heroku main`
- Set config vars via `heroku config:set KEY=VALUE`

## Current Feature Status
| Feature | Status |
|---------|--------|
| `/help`, `/wifi` | Done |
| `/venmo`, `/pay`, `/rent`, `/wifi_bill`, `/ledger` | Done |
| `/remind`, `/reminders`, `/reset_reminders` | Stubbed — not implemented |
| Playoff Week habit tracker | Designed (see `00_overview.md`–`03_open_questions.md`) — not built |

## Active Design Docs
- [00_overview.md](00_overview.md) — Playoff Week concept and user profiles
- [01_win_conditions.md](01_win_conditions.md) — Per-person daily win pillars
- [02_system_design.md](02_system_design.md) — Bot behavior spec for habit tracker
- [03_open_questions.md](03_open_questions.md) — Unresolved product decisions
- [timeline.md](timeline.md) — Development timeline
