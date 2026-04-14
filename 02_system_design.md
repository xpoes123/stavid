# System Design — Discord Bot

## Existing Infrastructure
- David has already built a Discord bot that tracks a shared ledger between him and Stephanie
- The bot should be extended (not replaced) to handle the playoff week system

---

## Core Bot Behaviors

### Daily Check-in Ping
- Bot pings both users at a set time (configurable per user)
- Asks each person to log their 3 pillars: did you hit them or not?
- Should be fast and frictionless — ideally 3 yes/no responses or emoji reactions
- Bot calculates win/loss for the day automatically based on responses

### Win/Loss Display
- Show current series score (e.g. "David: 2-1 | Stephanie: 1-2")
- **Critical UX requirement**: When someone is losing (e.g. 1-3), the bot must actively fight the "I give up" instinct
  - Do NOT just show a discouraging score
  - Show something like "Still alive — need 3 straight to win the series"
  - Stephanie specifically identified early-week losses as her quitting trigger
- Streak info could help: "You've won the last 2 days"

### Sunday Weekly Review
- On Sundays, bot prompts both users to:
  - Review last week's series result
  - Set any adjusted goals or notes for the coming week
  - Optionally: name one thing they want to focus on beyond the pillars

---

## Shared Ledger Integration
- The existing shared ledger should be extended to store:
  - Per-day win/loss per person
  - Per-pillar data (which pillars were hit/missed — useful for patterns)
  - Weekly series results over time
- This creates a historical record: "You've won 3 of the last 5 series"

---

## Incentive Structure

### Why pure gamification isn't enough
- Novelty wears off in 2-3 weeks
- Need deeper hooks: visibility, shared stakes, reflection

### What actually motivates each person
- **David**: Gamification, seeing patterns, compounding progress
- **Stephanie**: Social accountability, mild social anxiety about "looking bad" — she was motivated in school by not wanting to seem unprepared

### Consequence for losing a series (still to be decided — see open questions)
- One idea: loser has to do something outside their social comfort zone
  - Stephanie has bad social anxiety, so this has teeth for her
  - Risk: makes losing feel scary rather than just motivating — could cause avoidance of the whole system
  - Should feel like a challenge they opted into, not a punishment
- Alternative: winner picks the Saturday date activity

### Reward for winning
- TBD — could be as simple as bragging rights or a shared treat
- May not need explicit rewards if the intrinsic value of the pattern is visible

---

## Technical Notes
- Bot should handle the case where someone doesn't respond to the daily ping (treat as no data, not a loss — or prompt again)
- Time zones: both users are in New York (ET)
- Pillar check-in should be editable within a window (e.g. if you logged wrong)
