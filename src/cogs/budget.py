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

    partner_ids = {int(x) for x in os.getenv("PARTNER_IDS", "").split(",") if x.strip().isdigit()}
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

# This class includes all of the basic commands like help and quote
class Budget(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @app_commands.command(name="venmo", description="Create a venmo request that gets resolved at the end of the month")
    @app_commands.describe(
        amount="Amount",
        note="For what?",
    )
    async def venmo(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.01, 10000.0], note: str, month: str | None = None) -> None:
        partner = await _resolve_partner(interaction)
        if not partner:
            return await interaction.response.send_message(
                "❌ I couldn’t infer who to request from (set `PARTNER_IDS`).",
                ephemeral=True,
            )
        cents = int(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
        
        async with self.bot.db() as s:
            s.add(LedgerEntry(
                guild_id=interaction.guild_id or 0,
                creditor_id=interaction.user.id,
                debtor_id=partner.id,
                amount_cents=cents,
                note=note,
            ))
            await s.commit()
            
            net = await _net_between(s, interaction.guild_id or 0, interaction.user.id, partner.id)
        dollars = Decimal(net) / Decimal(100)
        sign = "you’re owed" if net > 0 else ("you owe" if net < 0 else "square")
        await interaction.response.send_message(
            f"🧾 Logged **${Decimal(cents)/Decimal(100)}** from {partner.mention} for **{note}**.\n"
            f"Current net: **{abs(dollars)}** ({sign}).",
        )
        
    # TODO - Implement this
    @app_commands.command(name="balance", description="Check the balance")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.send_message("Check balance", ephemeral=True)
    # TODO - Implement this
    @app_commands.command(name="reset", description="Reset the current month's ledger")
    async def reset(self, interaction: discord.Interaction):
        await interaction.response.send_message("Reset database", ephemeral=True)

async def _net_between(s, guild_id: int, me_id: int, partner_id: int) -> int:
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