"""#bills → LedgerEntry with the dollar amount + due date in the note."""
from __future__ import annotations

import logging
import typing as t

import discord
from discord.ext import commands

from src.cogs.inbox._utils import (
    ParseError,
    is_routable,
    parse_dollars_cents,
    parse_when,
    react_ok,
    react_warn,
    split_when_phrase,
)
from src.db import LedgerEntry
from src.utils import DAVID_ID, STEPH_ID
import os

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "bills"
log = logging.getLogger(__name__)


def _resolve_debtor_id(creator_id: int) -> int:
    """The creditor is the message author; the debtor is the other partner."""
    raw = os.getenv("PARTNER_IDS", "")
    ids: list[int] = []
    if raw:
        ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    if not ids:
        ids = [DAVID_ID, STEPH_ID]
    other = next((uid for uid in ids if uid != creator_id), None)
    return other if other is not None else creator_id


class BillsInbox(commands.Cog):
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

            amount_cents = parse_dollars_cents(content)
            if amount_cents is None:
                raise ParseError("no dollar amount found")

            note_parts = [content]

            split = split_when_phrase(content)
            if split is not None:
                _, when_str = split
                due_at = parse_when(when_str)
                if due_at is not None:
                    note_parts.append(f"(due {due_at.strftime('%Y-%m-%d')})")

            note = " ".join(note_parts)
            debtor_id = _resolve_debtor_id(message.author.id)

            async with self.bot.db() as s:
                s.add(
                    LedgerEntry(
                        guild_id=message.guild.id,
                        creditor_id=message.author.id,
                        debtor_id=debtor_id,
                        amount_cents=amount_cents,
                        note=note,
                    )
                )
                await s.commit()
            await react_ok(message)
        except Exception:
            log.exception("bills inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BillsInbox(bot))
