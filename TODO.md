# Stavid — TODO / Rework Backlog

> Low-priority project. Parking lot for ideas; not a commitment. Last updated 2026-09-17.

## Weekly order list / shopping redesign
The old weekly "supplies check" was removed (felt like it wasn't pulling its
weight). Rework the shopping/ordering flow so it actually leads to a purchase.

- **Decide the core question:** is the problem the *format*, the *nagging
  cadence*, or that the list never leads to an actual order? (Answer drives the design.)
- **One list vs split:** merge shopping + recurring supplies into a single list,
  or keep them separate?
- **"Auto-purchase on Amazon" — reality:** no official consumer purchase API.
  True auto-buy = headless browser + stored Amazon creds + unattended spend
  (ToS violation, fragile, risky). Don't build that. Realistic options:
  - **One-tap reorder links** — bot posts each item with a pre-filled Amazon
    cart/reorder URL; human taps to confirm. No creds, no ToS issue. (Leading idea.)
  - **Subscribe & Save** — move recurring items to Amazon's own auto-ship; bot
    just tracks/reminds. Zero purchasing code.
  - Merge supplies into the shopping list with reorder links.

## Rework (removed from Discord, data preserved)
These had their cogs + inbox channels removed 2026-09-17 to cut bloat, but the
ORM models, DB tables, and Sage API endpoints were **kept** so they can be
reworked without data loss (and Sage keeps working).
- **Watchlist** (movies/shows) — reframe then re-add a Discord surface.
- **Bucket list** — same.
- **Outings** (restaurants / activities, was fed by #restaurants,
  #local-events, #things-to-do) — same.

## Daily goals reframe
Playoff Week / daily-goals feature removed 2026-09-17; being reframed, shape
TBD. Tables (`playoff_checkins`, `weekly_reviews`, `user_preferences`) left
orphaned in case the reframe reuses them.

## Cleanup (someday)
- Orphaned tables from the trims above can be dropped once we're sure the
  rework won't reuse them: `playoff_checkins`, `weekly_reviews`,
  `user_preferences`, `supply_items`, `supply_check_results`.
