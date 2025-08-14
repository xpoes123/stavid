from __future__ import annotations

import os
import typing as t
from decimal import ROUND_HALF_UP, Decimal

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import case, func, select

from src.db import LedgerEntry

if t.TYPE_CHECKING:
    from src.main import StavidBot


async def _resolve_partner(interaction: discord.Interaction) -> discord.Member | None:
    me_id = interaction.user.id
    guild = interaction.guild
    if guild is None:
        return None

    partner_ids = {
        int(x) for x in os.getenv("PARTNER_IDS", "").split(",") if x.strip().isdigit()
    }
    other_id = next((uid for uid in partner_ids if uid != me_id), None)
    if other_id:
        m = guild.get_member(other_id)
        if m is None:
            try:
                m = await guild.fetch_member(other_id)
            except discord.NotFound:
                m = None
        if m and not m.bot:
            return m


def _format_money(cents: int) -> str:
    """Helper to format cents into a nice $xx.xx string."""
    return f"${Decimal(cents) / Decimal(100):,.2f}"


def _format_net_message(net_cents: int) -> str:
    """Return a pretty message describing the net balance."""
    net_abs = abs(net_cents)
    if net_cents > 0:
        return f"💰 You’re owed **{_format_money(net_abs)}**"
    elif net_cents < 0:
        return f"💸 You owe **{_format_money(net_abs)}**"
    else:
        return "✅ All square"


# This class includes all of the basic commands like help and quote
class Budget(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    async def _create_ledger_entry(
        self, interaction: discord.Interaction, cents: int, note: str
    ) -> int:
        partner = await _resolve_partner(interaction)
        if not partner:
            return await interaction.response.send_message(
                "❌ I couldn’t infer who to request from (set `PARTNER_IDS`).",
                ephemeral=True,
            )
        async with self.bot.db() as s:
            s.add(
                LedgerEntry(
                    guild_id=interaction.guild_id or 0,
                    creditor_id=interaction.user.id,
                    debtor_id=partner.id,
                    amount_cents=cents,
                    note=note,
                )
            )
            await s.commit()

            net = await _net_between(s, partner.id, interaction)
        return net

    @app_commands.command(
        name="venmo",
        description="Create a venmo request that gets resolved at the end of the month",
    )
    @app_commands.describe(
        amount="Amount",
        note="For what?",
    )
    async def venmo(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[float, 0.01, 10000.0],
        note: str,
    ) -> None:
        cents = int(
            Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100
        )
        net_cents = await self._create_ledger_entry(
            interaction=interaction, cents=cents, note=note
        )
        partner = await _resolve_partner(interaction)
        await interaction.response.send_message(
            (
                f"🧾 **Ledger Entry Created**\n"
                f"**From:** {partner.mention}\n"
                f"**Amount:** {_format_money(cents)}\n"
                f"**Note:** {note}\n\n"
                f"{_format_net_message(net_cents)}"
            ),
            ephemeral=False,
        )

    @app_commands.command(name="balance", description="Check the balance")
    async def balance(self, interaction: discord.Interaction):
        partner = await _resolve_partner(interaction)
        async with self.bot.db() as s:
            net_cents = await _net_between(s, partner.id, interaction)
        await interaction.response.send_message(
            f"📊 **Current Balance with {partner.mention}:**\n{_format_net_message(net_cents)}",
            ephemeral=True,
        )

    @app_commands.command(
        name="pay",
        description="Select an amount that you have paid the opposing person",
    )
    @app_commands.describe(amount="Amount", note="Note")
    async def pay(
        self,
        interaction: discord.Interaction,
        amount: float,
        note: str = "Payment made",
    ):
        cents = int(
            Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100
        )
        net_cents = await self._create_ledger_entry(
            interaction=interaction, cents=cents, note=note
        )
        await interaction.response.send_message(
            (
                f"💵 **Payment Recorded**\n"
                f"**Payer:** {interaction.user.mention}\n"
                f"**Amount:** {_format_money(cents)}\n"
                f"**Note:** {note}\n\n"
                f"{_format_net_message(net_cents)}"
            ),
            ephemeral=False,
        )

    @pay.autocomplete("amount")
    async def amount_autocomplete(self, interaction: discord.Interaction, current: str):
        partner = await _resolve_partner(interaction)
        if not partner:
            return [app_commands.Choice(name="Set PARTNER_IDS first", value=0.0)]

        async with self.bot.db() as s:
            net_cents = await _net_between(s, partner.id, interaction)

        label_sign = (
            "they owe you"
            if net_cents < 0
            else ("you owe them" if net_cents > 0 else "zip")
        )
        suggested_amount = abs(Decimal(net_cents) / Decimal(100))
        return [
            app_commands.Choice(
                name=f"${suggested_amount:.2f} ({label_sign})",
                value=float(suggested_amount),
            ),
        ]

    # TODO - Implement this
    @app_commands.command(
        name="rent", description="Run once a month to add rent payment"
    )
    async def rent(self, interaction: discord.Interaction):
        partner = await _resolve_partner(interaction)
        async with self.bot.db() as s:
            net_cents = await _net_between(s, partner.id, interaction)
        await interaction.response.send_message(
            f"📊 **Current Balance with {partner.mention}:**\n{_format_net_message(net_cents)}",
            ephemeral=True,
        )

    # TODO - Implement this
    @app_commands.command(
        name="ledger", description="See the itemized ledger for this month"
    )
    async def leder(self, interaction: discord.Interaction):
        partner = await _resolve_partner(interaction)
        async with self.bot.db() as s:
            net_cents = await _net_between(s, partner.id, interaction)
        await interaction.response.send_message(
            f"📊 **Current Balance with {partner.mention}:**\n{_format_net_message(net_cents)}",
            ephemeral=True,
        )


async def _net_between(s, partner_id: int, interaction: discord.Interaction) -> int:
    guild_id = interaction.guild_id
    me_id = interaction.user.id
    expr = case(
        (
            (LedgerEntry.settled.is_(False))
            & (LedgerEntry.creditor_id == me_id)
            & (LedgerEntry.debtor_id == partner_id),
            LedgerEntry.amount_cents,
        ),
        (
            (LedgerEntry.settled.is_(False))
            & (LedgerEntry.creditor_id == partner_id)
            & (LedgerEntry.debtor_id == me_id),
            -LedgerEntry.amount_cents,
        ),
        else_=0,
    )

    q = select(func.coalesce(func.sum(expr), 0)).where(LedgerEntry.guild_id == guild_id)

    res = await s.execute(q)
    return int(res.scalar_one())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Budget(bot))
