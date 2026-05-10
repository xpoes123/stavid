"""#bills → LedgerEntry with the dollar amount + due date in the note."""
from __future__ import annotations

import logging
import os
import re
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

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "bills"
log = logging.getLogger(__name__)

# Leading direction phrases that flip the default creditor/debtor roles.
# Default: author = creditor (partner owes author).
# Flip:    author = debtor  (author owes partner) — set when the author is
#          recording a payment they made or a debt they themselves carry.
_FLIP_PATTERNS = [
    re.compile(r"^\s*i\s+paid\b", re.IGNORECASE),
    re.compile(r"^\s*i\s+owe\b", re.IGNORECASE),
    re.compile(r"^\s*i\s+gave\b", re.IGNORECASE),
    re.compile(r"^\s*paid\s+\S+", re.IGNORECASE),
    re.compile(r"^\s*owe\s+\S+", re.IGNORECASE),
    re.compile(r"^\s*gave\s+\S+", re.IGNORECASE),
]


def author_is_debtor(content: str) -> bool:
    """True when the message starts with a phrase that flips the ledger direction.

    See ``_FLIP_PATTERNS`` for the recognised forms.
    """
    return any(p.match(content) for p in _FLIP_PATTERNS)


def _partner_id(creator_id: int) -> int:
    """Return the other partner's user ID, falling back to creator if alone."""
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
            partner_id = _partner_id(message.author.id)
            if author_is_debtor(content):
                creditor_id, debtor_id = partner_id, message.author.id
            else:
                creditor_id, debtor_id = message.author.id, partner_id

            async with self.bot.db() as s:
                s.add(
                    LedgerEntry(
                        guild_id=message.guild.id,
                        creditor_id=creditor_id,
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
