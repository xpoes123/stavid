# StavidBot — Apartment & Habits Discord Bot

A Discord bot for David and Stephanie ("Stavid") to manage shared apartment life and personal habit tracking.

**Stack:** Python 3.12 · discord.py 2.5+ · SQLAlchemy async · PostgreSQL · Heroku

---

## Setup

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your values:
   ```
   DISCORD_TOKEN=...
   DATABASE_URL=postgresql+asyncpg://...
   PARTNER_IDS=240608458888445953,694650702466908160
   wifi_name=...
   wifi_password=...
   ```

3. Run migrations:
   ```bash
   alembic upgrade heads
   ```

4. Start the bot:
   ```bash
   python -m src.main
   ```

---

## Commands

### Utilities

#### `/help`
Shows a paged help embed covering all available commands.

#### `/wifi`
Displays the guest WiFi network name and password (ephemeral).

---

### Budget & Expenses

#### `/venmo amount:<number> note:<text>`
Creates a ledger entry recording that your partner owes you.
```
/venmo amount:23.50 note:Dinner
```

#### `/pay amount:<number> [note:<text>]`
Records a payment you made to your partner. Autocompletes the suggested net amount.
```
/pay amount:50 note:Rent share
```

#### `/rent`
Adds the monthly rent split to the ledger and shows the updated balance.

#### `/wifi_bill`
Adds the monthly WiFi split to the ledger and shows the updated balance.

#### `/ledger`
Shows an itemized list of this month's entries and the current net balance (ephemeral).

---

### Reminders *(coming soon)*

#### `/remind date:<date> time:<time> note:<text> [location:<text>]`
Creates a reminder that pings both users.

#### `/reminders`
Lists all active reminders.

#### `/reset_reminders`
Marks all reminders as done.

---

## Planned Features

| Feature | Description |
|---------|-------------|
| **Playoff Week** | Weekly habit tracking — each day is a win or loss based on personal pillars; need 4 wins to win the week |
| **Reminders** | Time-based pings for both users with optional location context |
| **Chores** | Rotating chore assignments with configurable frequency |
| **Grocery list** | Shared running grocery list |
| **Restaurant finder** | Random restaurant suggestions via Google Maps |

See the design docs (`00_overview.md` through `03_open_questions.md`) for the full Playoff Week spec.

---

## Deployment (Heroku)

The bot runs as a **worker dyno** (no web server). Migrations run automatically on each deploy via the release phase.

```bash
git push heroku main
```

Config vars to set on Heroku:
- `DISCORD_TOKEN`
- `DATABASE_URL` (set automatically by Heroku Postgres add-on)
- `PARTNER_IDS`
- `wifi_name`, `wifi_password`
