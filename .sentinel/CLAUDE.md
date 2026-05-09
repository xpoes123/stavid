# Sentinel Learnings for xpoes123/stavid

Auto-maintained by Sentinel's memory system. Last updated: 2026-05-09 01:47 UTC

These are patterns learned from completed tasks on this repo.
Claude Code loads this file automatically.

## Warnings (avoid these)

- Avoid querying unbounded historical data; use limits (confidence: 6)
- Test all combinations: field present/absent/empty (confidence: 5)
- Don't settle results before all players check in (confidence: 4)
- Don't hardcode field inclusion; use None for clean omission (confidence: 4)
- Verify sort order (newest-first) in time-series displays (confidence: 4)
- Ensure parameter defaults don't break existing callers (confidence: 4)
- Don't count day as won if any player incomplete (confidence: 3)
- Avoid separate win tracking per player for same day (confidence: 3)
- Avoid showing individual results as the day verdict (confidence: 3)
- Don't miss notifying partner when day settles (confidence: 3)

## Conventions & Preferences

- Test edge cases: empty list, None, and populated scenarios (confidence: 6)
- Series logic derived from row counts, not separate tracking (confidence: 4)
- Use type unions (X | None) for optional parameters (confidence: 4)
- Include emoji indicators for visual hierarchy in embeds (confidence: 4)
- Format summaries with bold for emphasis (e.g. **2W – 1L**) (confidence: 4)
- Query limited lookback windows (e.g. 4 weeks) for performance (confidence: 4)
- DailyResult table for persisting shared outcomes (confidence: 3)
- Embed responses showing combined status first (confidence: 3)
- Cross-notification to alert partner of settlement (confidence: 3)
- Boolean field (won) for simple win/loss tracking (confidence: 3)

## Learned Patterns

- Query historical data before rendering summary views (confidence: 5)
- Add optional parameters to builders for conditional content (confidence: 5)
- Settle daily results only when all participants ready (confidence: 4)
- Derive series score from daily results, not recalculated (confidence: 4)
- Sort by newest-first for time-series displays (confidence: 4)
- Omit optional sections cleanly with None checks (confidence: 4)
- Test both presence and absence of conditional fields (confidence: 4)
- Check both players complete before marking day as won (confidence: 3)
- Use AND logic for multi-player win conditions (confidence: 3)
- Show combined verdict as primary, individual stats secondary (confidence: 3)
- Notify both players of shared outcome immediately (confidence: 3)
- Use helper functions to centralize complex calculation logic
- Auto-heal stale data during read operations when safe to do so
- Store per-pillar breakdowns alongside aggregate metrics
- Use same window logic for both computation and display
