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
from src.cogs.budget import SETTLE_NOTE, _format_money, net_between_ids, settle_up
from src.db import LedgerEntry
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

CHANNEL = "bills"
log = logging.getLogger(__name__)

# Direction parsing. Default: author = creditor (partner owes author).
# The message's leading subject + verb decides who carries the debt:
#   subject owes ...          → subject is the debtor
#   subject paid/gave/... ... → subject is the creditor (a payment credits the
#                               payer, like /pay — never flip "I paid" to debt)
# Subject is "I"/implicit (author), "you/she/he" (partner), or a first name
# resolved to a user ID. Unknown subjects keep the default.
_NAMES = {
    "david": DAVID_ID, "dave": DAVID_ID,
    "stephanie": STEPH_ID, "steph": STEPH_ID, "steph's": STEPH_ID,
}
_PARTNER_PRONOUNS = {"you", "u", "she", "he"}
_PAY_VERBS = r"paid|pay|payed|gave|covered|bought|got|picked\s+up|fronted|spent"
_DIRECTION_RE = re.compile(
    rf"^\s*(?:(?P<subj>[a-z']+)\s+)?(?:(?P<owe>owes?\b)|(?P<pay>(?:{_PAY_VERBS})\b))",
    re.IGNORECASE,
)


def author_is_debtor(content: str, author_id: int | None = None) -> bool:
    """True when the message says the author carries the debt.

    Only the leading clause counts ("dinner — I owe you nothing" stays default).
    ``author_id`` lets a first name that refers to the author ("david owes
    stephanie 30" from David) count as first person.
    """
    m = _DIRECTION_RE.match(content)
    if not m:
        return False
    subj = (m.group("subj") or "i").lower()
    if subj == "i":
        author_is_subject = True
    elif subj in _PARTNER_PRONOUNS:
        author_is_subject = False
    elif subj in _NAMES:
        author_is_subject = author_id is not None and _NAMES[subj] == author_id
    else:
        return False  # "rent paid 1500", "netflix 15" etc. → default
    if m.group("owe"):
        # Bare "owe" with nothing after is too ambiguous to flip.
        if not content[m.end():].strip():
            return False
        return author_is_subject
    return not author_is_subject


# Amount-free phrases that mean "clear the whole balance" (same as /paid).
# A match only OFFERS a settle (confirm button) — it never wipes on its own,
# since "settle up later?" or "we're even right?" match too.
_SETTLE_PATTERNS = [
    re.compile(r"^\s*i?\s*settled?\s+up\b", re.IGNORECASE),
    re.compile(r"^\s*settle\s+up\b", re.IGNORECASE),
    re.compile(r"^\s*(i\s+)?paid\s+(all|everything|it\s+all|it\s+off|in\s+full)\b", re.IGNORECASE),
    re.compile(r"^\s*all\s+square\b", re.IGNORECASE),
    re.compile(r"^\s*we'?re\s+(even|square)\b", re.IGNORECASE),
]


def is_settle_phrase(content: str) -> bool:
    """True when the message means 'clear the whole balance' with no amount."""
    return any(p.match(content) for p in _SETTLE_PATTERNS)


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


class SettleConfirmView(discord.ui.View):
    """Confirm/Cancel buttons for a #bills settle-up. Either partner may click.

    The balance is re-read at click time, so a charge added between the prompt
    and the click is included (and shown) rather than silently dropped.
    """

    def __init__(self, bot: StavidBot, guild_id: int, me_id: int, partner_id: int) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.me_id = me_id
        self.partner_id = partner_id
        self.done = False

    async def _allowed(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in (self.me_id, self.partner_id):
            return True
        await interaction.response.send_message(
            "Only the two of you can settle this.", ephemeral=True
        )
        return False

    async def do_confirm(self, interaction: discord.Interaction) -> None:
        if not await self._allowed(interaction):
            return
        if self.done:
            await interaction.response.edit_message(content="Already handled.", view=None)
            return
        self.done = True
        self.stop()
        async with self.bot.db() as s:
            cleared = await settle_up(s, self.guild_id, self.me_id, self.partner_id)
            await s.commit()
        text = (
            f"🧹 Settled up — cleared {_format_money(cleared)}. All square."
            if cleared
            else "✅ Already all square."
        )
        await interaction.response.edit_message(content=text, view=None)

    async def do_cancel(self, interaction: discord.Interaction) -> None:
        if not await self._allowed(interaction):
            return
        self.done = True
        self.stop()
        await interaction.response.edit_message(
            content="Settle cancelled — balance unchanged.", view=None
        )

    @discord.ui.button(label="Confirm settle", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.do_confirm(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.do_cancel(interaction)


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

            partner_id = _partner_id(message.author.id)

            # "I settled up" / "all square" → offer to clear the balance; the
            # settle only happens when a partner clicks Confirm.
            if is_settle_phrase(content):
                async with self.bot.db() as s:
                    net = await net_between_ids(
                        s, message.guild.id, message.author.id, partner_id
                    )
                if net == 0:
                    await message.channel.send("✅ Already all square.")
                    return
                await message.channel.send(
                    f"Settle up and clear {_format_money(abs(net))}?",
                    view=SettleConfirmView(
                        self.bot, message.guild.id, message.author.id, partner_id
                    ),
                )
                return

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
            if author_is_debtor(content, message.author.id):
                creditor_id, debtor_id = partner_id, message.author.id
            else:
                creditor_id, debtor_id = message.author.id, partner_id

            cleared_to_zero = False
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
                await s.flush()
                # If this entry cleared the balance (e.g. "I paid <full amount>"),
                # drop a settle marker so the ledger view collapses.
                if await net_between_ids(
                    s, message.guild.id, message.author.id, partner_id
                ) == 0:
                    s.add(
                        LedgerEntry(
                            guild_id=message.guild.id,
                            creditor_id=message.author.id,
                            debtor_id=partner_id,
                            amount_cents=0,
                            note=SETTLE_NOTE,
                        )
                    )
                    cleared_to_zero = True
                await s.commit()
            await react_ok(message)
            if cleared_to_zero:
                await message.channel.send("🧹 That clears it — you're all square.")
        except Exception:
            log.exception("bills inbox failed for message %s", message.id)
            await react_warn(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BillsInbox(bot))
