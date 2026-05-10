"""#amazon-links → ShoppingItem with og_* fields populated by the OG scraper."""
from __future__ import annotations

import logging
import typing as t

import discord
from discord.ext import commands

from src.cogs.inbox._utils import ParseError, first_url, is_routable, react_ok, react_warn
from src.cogs.shopping import _fetch_og
from src.db import ShoppingItem

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "amazon-links"
log = logging.getLogger(__name__)


class AmazonLinksInbox(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not is_routable(message, CHANNEL):
            return
        try:
            url = first_url(message.content)
            if url is None:
                raise ParseError("no URL found")

            og = await _fetch_og(url)
            display_name = og.get("title") or url

            async with self.bot.db() as s:
                s.add(
                    ShoppingItem(
                        guild_id=message.guild.id,
                        name=display_name,
                        link=url,
                        note=message.content.replace(url, "").strip(),
                        added_by=message.author.id,
                        og_title=og.get("title"),
                        og_price=og.get("price"),
                        og_image=og.get("image"),
                    )
                )
                await s.commit()
            await react_ok(message)
        except Exception:
            log.exception("amazon-links inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AmazonLinksInbox(bot))
