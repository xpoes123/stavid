"""#reminders → ReminderEntry. Parses ``<note> in <when>`` and natural phrases."""
from __future__ import annotations

import logging
import os
import typing as t

import discord
from discord.ext import commands

from src.cogs.inbox._utils import (
    ParseError,
    is_routable,
    parse_when,
    react_ok,
    react_warn,
    split_when_phrase,
)
from src.db import ReminderEntry
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "reminders"
log = logging.getLogger(__name__)


def _resolve_partner_id(creator_id: int) -> int:
    """Pick the other partner in the apartment guild, falling back to the creator.

    Reads PARTNER_IDS env var if set, otherwise uses the hardcoded David/Steph
    pair from src.utils. Falls back to the creator if no other partner is found.
    """
    raw = os.getenv("PARTNER_IDS", "")
    ids: list[int] = []
    if raw:
        ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    if not ids:
        ids = [DAVID_ID, STEPH_ID]
    other = next((uid for uid in ids if uid != creator_id), None)
    return other if other is not None else creator_id


class RemindersInbox(commands.Cog):
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

            split = split_when_phrase(content)
            if split is None:
                raise ParseError("no when found — say e.g. 'pay rent in 2 days'")
            note, when_str = split
            due_at = parse_when(when_str)
            if due_at is None:
                raise ParseError(f"could not parse when: {when_str!r}")

            partner_id = _resolve_partner_id(message.author.id)
            async with self.bot.db() as s:
                s.add(
                    ReminderEntry(
                        guild_id=message.guild.id,
                        creator_id=message.author.id,
                        partner_id=partner_id,
                        time=due_at,
                        note=note,
                        location="",
                        done=False,
                    )
                )
                await s.commit()
            await react_ok(message)
        except Exception:
            log.exception("reminders inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RemindersInbox(bot))
