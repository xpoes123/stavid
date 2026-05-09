# Sentinel Learnings for xpoes123/stavid

Auto-maintained by Sentinel's memory system. Last updated: 2026-05-09 01:49 UTC

These are patterns learned from completed tasks on this repo.
Claude Code loads this file automatically.

## Warnings (avoid these)

- Test all combinations: field present/absent/empty (confidence: 9)
- Avoid querying unbounded historical data; use limits (confidence: 7)
- Don't settle results before all players check in (confidence: 5)
- Don't hardcode field inclusion; use None for clean omission (confidence: 5)
- Verify sort order (newest-first) in time-series displays (confidence: 5)
- Ensure parameter defaults don't break existing callers (confidence: 5)
- Don't count day as won if any player incomplete (confidence: 4)
- Avoid separate win tracking per player for same day (confidence: 4)
- Avoid showing individual results as the day verdict (confidence: 4)
- Don't miss notifying partner when day settles (confidence: 4)

## Conventions & Preferences

- Test edge cases: empty list, None, and populated scenarios (confidence: 9)
- Series logic derived from row counts, not separate tracking (confidence: 5)
- Use type unions (X | None) for optional parameters (confidence: 5)
- Include emoji indicators for visual hierarchy in embeds (confidence: 5)
- Format summaries with bold for emphasis (e.g. **2W – 1L**) (confidence: 5)
- Query limited lookback windows (e.g. 4 weeks) for performance (confidence: 5)
- DailyResult table for persisting shared outcomes (confidence: 4)
- Embed responses showing combined status first (confidence: 4)
- Cross-notification to alert partner of settlement (confidence: 4)
- Boolean field (won) for simple win/loss tracking (confidence: 4)

## Learned Patterns

- Omit optional sections cleanly with None checks (confidence: 8)
- Test both presence and absence of conditional fields (confidence: 6)
- Query historical data before rendering summary views (confidence: 6)
- Add optional parameters to builders for conditional content (confidence: 6)
- Settle daily results only when all participants ready (confidence: 5)
- Derive series score from daily results, not recalculated (confidence: 5)
- Sort by newest-first for time-series displays (confidence: 5)
- Check both players complete before marking day as won (confidence: 4)
- Use AND logic for multi-player win conditions (confidence: 4)
- Show combined verdict as primary, individual stats secondary (confidence: 4)
- Notify both players of shared outcome immediately (confidence: 4)
- Use helper functions to centralize complex calculation logic (confidence: 3)
- Auto-heal stale data during read operations when safe to do so (confidence: 3)
- Store per-pillar breakdowns alongside aggregate metrics (confidence: 3)
- Use same window logic for both computation and display (confidence: 3)
