# Stavid — Vision & Backlog

> Low-priority project, but here's the plan when we pick it up. Written 2026-09-17
> from a full ecosystem review (Stavid + Sage + the finance app + the VPS).

## North star

Stavid's proven DNA: **ambient capture + the bot remembers.** The killer pattern
is "type plain English in a channel, get a ✅" (`#bills` → ledger is the exemplar).
Every feature that demands disciplined daily manual logging (Playoff Week pillars,
date-night stats) has been or will be trimmed — couples don't sustain that.

**Design rule:** capture must be effortless (channel message, one tap, one reaction);
the bot does the remembering, not us. Build with that grain; be ruthless about
anything needing daily upkeep.

The one hard constraint: the **Sage HTTP API contract** (`src/api.py`, loopback :7780)
is load-bearing. Additive changes only; never break a response shape without updating
Sage in lockstep.

---

## Strategic decisions (resolve these first — they gate everything below)

### D1. The finance app exists twice — pick one home. ⭐ highest leverage
- **Standalone `finance/` repo** (`xpoes123/finance`, live at **finance.djiang.xyz**,
  `/opt/finance-hub`): mature Budget Game v1. SimpleFIN pull, Haiku classification,
  per-person variable-spend caps + streaks + freezes, Gmail-receipt enrichment,
  sinking funds, David↔Steph reconcile, git-as-database (state.json via Actions cron).
- **Stavid `budget-game` branch** (6 commits, unmerged): leaner re-port *into* Stavid
  — shares Postgres, the one Discord connection, and the `#bills` NLP ledger. Adds
  `src/game/{core,classify,simplefin,dashboard}.py`, `src/cogs/game.py`, game tables.
- **Recommendation:** fold into Stavid (branch approach). Postgres > git-as-database,
  one bot, one deploy, and it can reconcile against the shared ledger natively. Then
  migrate the standalone's richer bits (Gmail enrichment, sinking funds, reconcile) as
  follow-ups. **Decision needed before investing more in either.**

### D2. Make Stavid the deterministic source of truth; Sage the natural-language front door.
Sage's *read* integration is mature; the unlock is a *writable* Stavid API so Sage can
capture by voice/chat while Stavid stays the system of record. See T2.

### D3. Decide the fate of the 3 dormant features (watchlist / bucket / outings).
They're in limbo: no Discord surface, but Sage still nags their `/summary` counts and
they're the only remaining interface. Either re-surface as *decision tools* (T4) or drop
them and their `/summary` fields (updating Sage). Pick per-feature; don't leave limbo.

---

## Backlog (themed, with specs)

### T1 — Weekly order list / shopping redesign  ·  P1 · the live ask
Problem to optimize for: **the list never leads to an actual order.** Success metric =
taps that reach Amazon checkout.
- **One-tap reorder links.** Store an item's **ASIN** on add; render each as a pre-filled
  cart deep link `https://www.amazon.com/gp/aws/cart/add.html?ASIN.1=<ASIN>&Quantity.1=1`.
  Human taps → cart preloaded → they confirm. No creds, no ToS issue. (There is **no**
  legitimate Amazon consumer purchase API — do NOT build headless auto-buy.)
- **Subscribe & Save handoff.** Truly recurring items (paper towels, detergent) → move to
  Amazon's own auto-ship; Stavid just tracks/reminds ("S&S ships Tue, add anything?").
- **One list, a flag.** Merge the old "supplies" idea back in: `shopping_items` gains
  `recurring` + `cadence`; recurring items resurface a reorder link on cadence via a
  weekly `#things-to-purchase` digest. (Answers "one list vs split" = one list.)
- Fix the fragile Amazon OG-scrape (`shopping.py:_fetch_og`) — it mostly fails against
  Amazon bot-detection. ASIN capture replaces the need for it.

### T2 — Sage-writable API + household proactivity  ·  P1
- `POST /ledger` on Stavid → `stavid_add_expense` action in Sage: "I paid $40 groceries,
  split with Steph" logs to the ledger with `added_by`/split. (Sage already has the
  fuzzy-match + confirm UX.) Ledger is read-only today (`api.py`).
- `POST /reminder` → `stavid_add_reminder`: "remind us both to call the landlord Friday"
  lands in the shared apartment channel, not just David's solo Sage reminders.
- Expose **chores** on the API (`GET /chores`) → `stavid_chores` tool: "whose turn for
  trash?" + fold overdue chores into the brief. Advertised in docs, not on the API yet.
- Add `stavid_ledger` read tool + a "who owes whom" line to Sage's morning brief
  (GET /ledger already exists — pure Sage-side add).
- **Household proactive sensor** (`sage/proactive/sensors/apartment.py`): poll `/summary`
  + `/reminders` (+ ledger once writable) → Observations ("5 groceries open near a store",
  "shared reminder overdue", "rent due in 3 days"). Sage's scoring/quiet-hours/cap/dedup
  engine already exists and ships dry-run — this is its intended extension point.

### T3 — In-Discord morning brief  ·  P2
`/summary` aggregation already exists server-side. Add a daily digest loop posting one
embed to the apartment channel: reminders due, chores today, ledger balance, special
dates within 14 days, shopping count. The "one bot that quietly tracks shared life"
identity, reusing written code. (Complements Sage's 8am brief; this one lives in Stavid.)

### T4 — Rework the dormant features as *decision tools* (not passive lists)  ·  P2
- **Outings → "date roulette"** (highest-leverage re-add). `OutingWishlistItem` already
  has `budget`/`neighborhood`/`category`. `/outing roll [budget] [neighborhood]` picks a
  place respecting filters — solves the real recurring "where Saturday?" problem. Feed via
  `#restaurants` / `#things-to-do` inbox again.
- **Watchlist → "what do we watch tonight."** Schema already has per-person ratings
  (`david_rating`/`steph_rating`). `/watch pick` (weighted-random suggestion), `/watch rate`,
  and a `#watchlist` inbox that OG-scrapes a pasted title/link.
- **Bucket → fold into date night.** Low engagement standalone. Monthly "3 ideas you could
  do this month" digest; let `/datenight log` cross off a bucket item (mirrors the existing
  wishlist cross-off). Reuse, don't rebuild.

### T5 — Foundation / hygiene  ·  P2 (do while touching the above)
- **Fix `/help`:** generate from `bot.tree` introspection instead of the hand-maintained
  2-page pager (only shows Basic + Budget today; reminders/chores/datenight/shopping are
  undiscoverable). Kills the staleness bug class permanently.
- **Migrate to pydantic-settings** (house convention; Stavid is the drift). Centralize the
  guild ID (hardcoded in 3 places), user IDs, financial constants, channel names.
- **Centralized error handling:** add `on_app_command_error`; slash commands currently
  surface raw "interaction failed". Ideally import `toolkit/djtoolkit/discord_kit.py`
  (extracted from Sage for exactly this). Also harden `resolve_partner` None cases.
- **Doc rot:** `readme.md`, `CLAUDE.md` feature table, and deploy notes still describe
  Playoff Week, removed inbox channels, user-prefs commands, and autonomous Sentinel
  deploys — none live. `04_feature_roadmap.md` is a stale wishlist. Prune to reality.
- **Ledger categories:** add a `category` to `LedgerEntry` + a monthly `/budget` summary
  ("this month: $X groceries, $Y eating out"). One column answers a recurring real question.
- **Recurring bills:** generalize `/rent` + `/wifi_bill` into `/bill add` (auto-posts a
  ledger entry + reminder on a schedule). Removes a monthly manual step.

### T6 — Cleanup (safe, low-priority)
- Drop the fully-orphaned tables once we're sure the rework won't reuse them:
  `playoff_checkins`, `weekly_reviews`, `user_preferences`, `supply_items`,
  `supply_check_results`. (`playoff_series`/`daily_results` already dropped.)
- **CSS drift:** the budget-game branch *vendored* a copy of `toolkit/web/tokyo-night.css`
  (now 3+ copies across finance/share/stavid). Depend on the toolkit source instead.
- **VPS hygiene** (from the server inventory): stale `/opt/finance` + orphan
  `/opt/finance-dash` (live app is `/opt/finance-hub`); ~18 Caddyfile backups; two
  services bound to `0.0.0.0` instead of loopback (port 7890, sage on 7779).
- **Disk is the box's ceiling: `/` at 87% (4.7 GB free).** Watch it; it'll bite before
  CPU/RAM does.

---

## Daily-goals reframe (parked)
Playoff Week removed 2026-09-17; tables orphaned. If it returns, the one genuinely good
idea was **anti-quit messaging** ("still alive — win 3 straight") — but make check-in a
single daily 👍/👎 reaction, not a 3-pillar modal. Friction killed v1. Could reuse
`playoff_checkins`/`user_preferences`. Lowest priority.

---

## The ecosystem (context)
- **Stavid** (this, Postgres, apartment) — shared ledger + reminders + chores + datenight
  + shopping; loopback API for Sage.
- **Sage** (SQLite, personal assistant) — NL chat gateway, calendar/email/reminders,
  8am shared morning brief; the natural NL front door + notification hub.
- **Finance app / Budget Game** (finance.djiang.xyz) — gamified personal-spend tracker;
  see D1. Conceptually adjacent to Stavid's ledger (shared vs personal money).
- **Design system:** personal single-user tools → Tokyo Night dark via
  `toolkit/web/tokyo-night.css`; public products keep own branding. Stavid dashboards
  belong in the Tokyo Night family. Long-term: one internal dashboard hub on djiang.xyz.
