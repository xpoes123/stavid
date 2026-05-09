# Sentinel Learnings for xpoes123/stavid

Auto-maintained by Sentinel's memory system. Last updated: 2026-05-09 01:34 UTC

These are patterns learned from completed tasks on this repo.
Claude Code loads this file automatically.

## Warnings (avoid these)

- Avoid querying unbounded historical data; use limits
- Don't hardcode field inclusion; use None for clean omission
- Verify sort order (newest-first) in time-series displays
- Test all combinations: field present/absent/empty
- Ensure parameter defaults don't break existing callers
- Don't count day as won if any player incomplete
- Avoid separate win tracking per player for same day
- Don't settle results before all players check in
- Avoid showing individual results as the day verdict
- Don't miss notifying partner when day settles

## Conventions & Preferences

- Use type unions (X | None) for optional parameters
- Include emoji indicators for visual hierarchy in embeds
- Format summaries with bold for emphasis (e.g. **2W – 1L**)
- Query limited lookback windows (e.g. 4 weeks) for performance
- Test edge cases: empty list, None, and populated scenarios
- DailyResult table for persisting shared outcomes
- Embed responses showing combined status first
- Cross-notification to alert partner of settlement
- Boolean field (won) for simple win/loss tracking
- Series logic derived from row counts, not separate tracking

## Learned Patterns

- Add optional parameters to builders for conditional content
- Query historical data before rendering summary views
- Sort by newest-first for time-series displays
- Omit optional sections cleanly with None checks
- Test both presence and absence of conditional fields
- Check both players complete before marking day as won
- Use AND logic for multi-player win conditions
- Settle daily results only when all participants ready
- Show combined verdict as primary, individual stats secondary
- Notify both players of shared outcome immediately
- Derive series score from daily results, not recalculated
