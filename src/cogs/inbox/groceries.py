"""#groceries → ShoppingItem rows (one per comma- or newline-separated entry)."""
from __future__ import annotations

import logging
import typing as t

import discord
from discord.ext import commands

from src.cogs.inbox._utils import ParseError, is_routable, react_ok, react_warn
from src.db import ShoppingItem

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "groceries"
log = logging.getLogger(__name__)


def parse_grocery_message(content: str) -> list[str]:
    """Split a free-form message into one entry per item.

    Splits on commas and newlines, trims whitespace, drops empty parts.
    """
    parts: list[str] = []
    for line in content.splitlines():
        for chunk in line.split(","):
            chunk = chunk.strip()
            if chunk:
                parts.append(chunk)
    if not parts:
        raise ParseError("no items found")
    return parts


class GroceriesInbox(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not is_routable(message, CHANNEL):
            return
        try:
            items = parse_grocery_message(message.content)
            async with self.bot.db() as s:
                for name in items:
                    s.add(
                        ShoppingItem(
                            guild_id=message.guild.id,
                            name=name,
                            link="",
                            note="",
                            added_by=message.author.id,
                        )
                    )
                await s.commit()
            await react_ok(message)
        except Exception:
            log.exception("groceries inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GroceriesInbox(bot))
