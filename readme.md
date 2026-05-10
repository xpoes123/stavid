# StavidBot — Apartment & Habits Discord Bot

A Discord bot for David and Stephanie ("Stavid") to manage shared apartment life and personal habit tracking.

**Stack:** Python 3.12 · discord.py 2.5+ · SQLAlchemy async · PostgreSQL · FastAPI (local Sage API) · self-hosted on a Hetzner VPS under systemd.

---

## Setup (local dev)

1. Clone the repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your values:
   ```
   DISCORD_TOKEN=...
   DATABASE_URL=postgresql+asyncpg://localhost/stavid
   PARTNER_IDS=240608458888445953,694650702466908160
   wifi_name=...
   wifi_password=...
   ```

3. Run migrations:
   ```bash
   alembic upgrade head
   ```

4. Start the bot:
   ```bash
   python -m src.main
   ```

---

## Commands

### Utilities
- `/help` — paged help embed.
- `/wifi` — guest WiFi name + password (ephemeral).

### Budget & Expenses
- `/venmo amount:<n> note:<text>` — record that your partner owes you.
- `/pay amount:<n> [note]` — record a payment you made to your partner.
- `/rent`, `/wifi_bill` — add monthly splits.
- `/ledger` — this month's entries + current balance.

### Reminders
- `/remind date:<date> time:<time> note:<text> [location]` — schedule a reminder. Both partners get pinged.
- `/reminders` — list active reminders.
- `/remove_reminder reminder_id:<n>` — mark one done.
- `/reset_reminders` — mark all done.

A 60-second background loop polls due reminders and posts them into the
guild's `#reminders` channel (or `REMINDER_CHANNEL_ID` if set).

### Playoff Week (habit tracker)
- `/checkin` — open a modal to log your 3 daily pillars.
- `/playoff_status` — both partners' current weekly W/L scoreboards (independent).
- `/series_history` — last 8 weeks per person.
- `/weekly_review` — modal to record a written reflection for the week.

Scoring is **individual**: a user wins a day iff *they* completed all 3 of their own pillars. 4 wins out of 7 days clinches the week.

### Channel-as-Inbox
Plain messages in certain apartment-guild channels turn into rows automatically. ✅ on success, ⚠️ on parse failure.

| Channel | Behavior |
|---|---|
| `#groceries` | One `ShoppingItem` per comma- or newline-separated entry |
| `#things-to-purchase` | `ShoppingItem` with `note="non-food"` (Amazon URLs auto-fetch OG metadata via `/shopping_add`) |
| `#restaurants` | `OutingWishlistItem` (`italian: Carbone` syntax sets cuisine) |
| `#things-to-do`, `#local-events` | `OutingWishlistItem` (category `activity`) |
| `#reminders` | `ReminderEntry` (parses `<note> in <when>` plus natural phrases) |
| `#bills` | `LedgerEntry` (creditor=author, debtor=partner; due date appended) |

`#general`, `#dev`, `#dev2` are explicitly skipped.

---

## Sage integration

Sage runs on the same VPS and calls a small read/write HTTP API on `127.0.0.1:7780` (see [src/api.py](src/api.py)). Bearer auth via `STAVID_API_TOKEN`. Loopback only — no external traffic. The flow is one-directional: Sage → Stavid; Stavid never calls Sage.

---

## Deployment

Stavid runs on the Hetzner VPS at `/opt/stavid` as the systemd unit `stavid`.

The deploy pipeline is autonomous: when a PR is merged on GitHub,
[Sentinel](https://github.com/xpoes123/sentinel) (also on the same VPS) clones the repo, copies files into `/opt/stavid` (preserving `.env` + `venv`), runs `pip install -e .`, smoke-tests imports, and `systemctl restart stavid`. There is no Heroku, no Procfile, no release phase.

Migrations are not auto-applied. After a deploy that includes a new alembic revision:

```bash
ssh vps
cd /opt/stavid
venv/bin/alembic upgrade head
sudo systemctl restart stavid
sudo journalctl -u stavid -f
```

Config vars live in `/opt/stavid/.env` (the file is preserved across deploys). See the env table in [CLAUDE.md](CLAUDE.md) for the full list.
