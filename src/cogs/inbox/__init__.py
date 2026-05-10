"""Inbox routing — channel-as-inbox cogs.

Each module in this package is a small ``commands.Cog`` whose only job is to
listen to messages in one specific text channel of the apartment guild and
turn them into a domain row (ShoppingItem, OutingWishlistItem, ReminderEntry,
LedgerEntry, …). On success the cog reacts with ✅; on parse failure ⚠️.

The bot loader in ``src.main`` walks this package recursively, so adding a new
file here is enough to activate a new inbox channel — no central registry to
update.
"""


async def setup(bot):
    """No-op so the package itself loads cleanly when discovered as an extension."""
