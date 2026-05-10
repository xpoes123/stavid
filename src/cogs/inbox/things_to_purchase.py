"""#things-to-purchase → ShoppingItem with note=\"non-food\"."""
from __future__ import annotations

import logging
import typing as t

import discord
from discord.ext import commands

from src.cogs.inbox._utils import ParseError, first_url, is_routable, react_ok, react_warn
from src.db import ShoppingItem

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "things-to-purchase"
NON_FOOD_NOTE = "non-food"
log = logging.getLogger(__name__)


class ThingsToPurchaseInbox(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not is_routable(message, CHANNEL):
            return
        try:
            content = message.content.strip()
            if not content:
                raise ParseError("empty message")

            link = first_url(content) or ""
            name = content
            if link:
                name = content.replace(link, "").strip() or link

            async with self.bot.db() as s:
                s.add(
                    ShoppingItem(
                        guild_id=message.guild.id,
                        name=name,
                        link=link,
                        note=NON_FOOD_NOTE,
                        added_by=message.author.id,
                    )
                )
                await s.commit()
            await react_ok(message)
        except Exception:
            log.exception("things-to-purchase inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ThingsToPurchaseInbox(bot))
