"""#weekly-chores → ChoreTemplate(recurrence='weekly').

Posting a chore name in this channel creates a recurring weekly template with
default alternating assignment. The first instance is materialized
immediately so it shows up in /chores.
"""
from __future__ import annotations

import logging
import typing as t

import discord
from discord.ext import commands

from src.cogs.chores import next_due_for, pick_next_assignee
from src.cogs.inbox._utils import ParseError, is_routable, react_ok, react_warn
from src.db import ChoreInstance, ChoreTemplate

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "weekly-chores"
RECURRENCE = "weekly"
log = logging.getLogger(__name__)


class WeeklyChoresInbox(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not is_routable(message, CHANNEL):
            return
        try:
            name = message.content.strip()
            if not name:
                raise ParseError("empty message")

            from datetime import date as _date

            async with self.bot.db() as s:
                template = ChoreTemplate(
                    guild_id=message.guild.id,
                    name=name,
                    recurrence=RECURRENCE,
                    default_assignee_id=None,  # alternate
                    active=True,
                )
                s.add(template)
                await s.flush()

                assignee_id = pick_next_assignee(template)
                due = next_due_for(RECURRENCE, _date.today())
                s.add(
                    ChoreInstance(
                        guild_id=message.guild.id,
                        template_id=template.id,
                        name=name,
                        assignee_id=assignee_id,
                        due_date=due,
                    )
                )
                template.last_assignee_id = assignee_id
                await s.commit()

            await react_ok(message)
        except Exception:
            log.exception("weekly-chores inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeeklyChoresInbox(bot))
