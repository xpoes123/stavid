# Sentinel Learnings for xpoes123/stavid

Auto-maintained by Sentinel's memory system. Last updated: 2026-05-09 03:00 UTC

These are patterns learned from completed tasks on this repo.
Claude Code loads this file automatically.

## Warnings (avoid these)

- Test all combinations: field present/absent/empty (confidence: 10)
- Avoid querying unbounded historical data; use limits (confidence: 8)
- Don't settle results before all players check in (confidence: 6)
- Don't hardcode field inclusion; use None for clean omission (confidence: 6)
- Verify sort order (newest-first) in time-series displays (confidence: 6)
- Ensure parameter defaults don't break existing callers (confidence: 6)
- Don't count day as won if any player incomplete (confidence: 5)
- Avoid separate win tracking per player for same day (confidence: 5)
- Avoid showing individual results as the day verdict (confidence: 5)
- Don't miss notifying partner when day settles (confidence: 5)

## Conventions & Preferences

- Test edge cases: empty list, None, and populated scenarios (confidence: 10)
- Series logic derived from row counts, not separate tracking (confidence: 6)
- Use type unions (X | None) for optional parameters (confidence: 6)
- Include emoji indicators for visual hierarchy in embeds (confidence: 6)
- Format summaries with bold for emphasis (e.g. **2W – 1L**) (confidence: 6)
- Query limited lookback windows (e.g. 4 weeks) for performance (confidence: 6)
- DailyResult table for persisting shared outcomes (confidence: 5)
- Embed responses showing combined status first (confidence: 5)
- Cross-notification to alert partner of settlement (confidence: 5)
- Boolean field (won) for simple win/loss tracking (confidence: 5)

## Learned Patterns

- Omit optional sections cleanly with None checks (confidence: 9)
- Test both presence and absence of conditional fields (confidence: 7)
- Query historical data before rendering summary views (confidence: 7)
- Add optional parameters to builders for conditional content (confidence: 7)
- Settle daily results only when all participants ready (confidence: 6)
- Derive series score from daily results, not recalculated (confidence: 6)
- Sort by newest-first for time-series displays (confidence: 6)
- Check both players complete before marking day as won (confidence: 5)
- Use AND logic for multi-player win conditions (confidence: 5)
- Show combined verdict as primary, individual stats secondary (confidence: 5)
- Notify both players of shared outcome immediately (confidence: 5)
- Use helper functions to centralize complex calculation logic (confidence: 4)
- Auto-heal stale data during read operations when safe to do so (confidence: 4)
- Store per-pillar breakdowns alongside aggregate metrics (confidence: 4)
- Use same window logic for both computation and display (confidence: 4)
