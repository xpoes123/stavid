"""#restaurants → OutingWishlistItem (category=\"other\" by default).

Optionally accepts a leading ``cuisine:`` prefix (``italian: Carbone``) to set
the category to one of the known cuisines.
"""
from __future__ import annotations

import logging
import typing as t

import discord
from discord.ext import commands

from src.cogs.inbox._utils import ParseError, first_url, is_routable, react_ok, react_warn
from src.cogs.outings import CATEGORIES
from src.db import OutingWishlistItem

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "restaurants"
DEFAULT_CATEGORY = "other"
log = logging.getLogger(__name__)


def _split_category_prefix(content: str) -> tuple[str, str]:
    """If ``content`` is ``"<cat>: <name>"`` and <cat> is a known category,
    return (category, name). Otherwise return (DEFAULT_CATEGORY, content)."""
    if ":" not in content:
        return DEFAULT_CATEGORY, content
    head, _, tail = content.partition(":")
    head = head.strip().lower()
    tail = tail.strip()
    if head in CATEGORIES and tail:
        return head, tail
    return DEFAULT_CATEGORY, content


class RestaurantsInbox(commands.Cog):
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
            text_for_name = content.replace(link, "").strip() if link else content
            category, name = _split_category_prefix(text_for_name or content)
            if not name:
                raise ParseError("no restaurant name")

            async with self.bot.db() as s:
                s.add(
                    OutingWishlistItem(
                        guild_id=message.guild.id,
                        name=name,
                        category=category,
                        link=link,
                        added_by=message.author.id,
                    )
                )
                await s.commit()
            await react_ok(message)
        except Exception:
            log.exception("restaurants inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RestaurantsInbox(bot))
