from __future__ import annotations

import typing as t
from decimal import ROUND_HALF_UP, Decimal

import discord
from discord import app_commands
from discord.ext import commands

from src import piggy
from src.utils import resolve_partner

if t.TYPE_CHECKING:
    from src.main import StavidBot

# The ledger lives in Piggy (src/piggy.py). Rent and wifi are posted there
# automatically on the 1st, so /rent and /wifi_bill only say so.
PIGGY_DOWN = "❌ Couldn't reach Piggy, try again in a minute."


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


def _cents(amount: float) -> int:
    return int(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


class Budget(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="venmo",
        description="Your partner owes you this (settled whenever you settle up)",
    )
    @app_commands.describe(amount="Amount", note="For what?")
    async def venmo(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[float, 0.01, 10000.0],
        note: str,
    ) -> None:
        partner = await resolve_partner(interaction)
        cents = _cents(amount)
        try:
            await piggy.add(interaction.user.id, cents, note)
            net = await piggy.balance(interaction.user.id)
        except piggy.PiggyError:
            await interaction.response.send_message(PIGGY_DOWN, ephemeral=True)
            return
        await interaction.response.send_message(
            f"🧾 **Ledger Entry Created**\n"
            f"**From:** {partner.mention if partner else 'partner'}\n"
            f"**Amount:** {_format_money(cents)}\n"
            f"**Note:** {note}\n\n"
            f"{_format_net_message(net)}"
        )

    @app_commands.command(
        name="pay",
        description="Record an amount you paid your partner",
    )
    @app_commands.describe(amount="Amount", note="Note")
    async def pay(
        self,
        interaction: discord.Interaction,
        amount: float,
        note: str = "Payment made",
    ):
        cents = _cents(amount)
        if cents <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return
        try:
            await piggy.add(interaction.user.id, cents, note, payment=True)
            net = await piggy.balance(interaction.user.id)
        except piggy.PiggyError:
            await interaction.response.send_message(PIGGY_DOWN, ephemeral=True)
            return
        await interaction.response.send_message(
            f"💵 **Payment Recorded**\n"
            f"**Payer:** {interaction.user.mention}\n"
            f"**Amount:** {_format_money(cents)}\n"
            f"**Note:** {note}\n\n"
            f"{_format_net_message(net)}"
        )

    @pay.autocomplete("amount")
    async def amount_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            net_cents = await piggy.balance(interaction.user.id)
        except piggy.PiggyError:
            net_cents = 0
        label_sign = (
            "they owe you" if net_cents > 0 else ("you owe them" if net_cents < 0 else "zip")
        )
        suggested_amount = abs(Decimal(net_cents) / Decimal(100))
        choices = []
        # Echo whatever the user is typing so custom amounts are one click away.
        try:
            typed = float(current)
            if typed > 0:
                choices.append(app_commands.Choice(name=f"${typed:.2f}", value=typed))
        except ValueError:
            pass
        choices.append(
            app_commands.Choice(
                name=f"${suggested_amount:.2f} (settle all — {label_sign})",
                value=float(suggested_amount),
            )
        )
        return choices

    @app_commands.command(
        name="paid",
        description="Settle up — clears the full running balance to zero",
    )
    async def paid(self, interaction: discord.Interaction):
        partner = await resolve_partner(interaction)
        try:
            cleared = await piggy.settle(interaction.user.id)
        except piggy.PiggyError:
            await interaction.response.send_message(PIGGY_DOWN, ephemeral=True)
            return
        if cleared == 0:
            await interaction.response.send_message("✅ Already all square — nothing to settle.")
            return
        await interaction.response.send_message(
            f"🧹 **Settled up with {partner.mention if partner else 'partner'}** — "
            f"cleared {_format_money(cleared)}.\n{_format_net_message(0)}"
        )

    @app_commands.command(name="rent", description="Rent is added automatically by Piggy")
    async def rent(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Piggy adds rent to the ledger automatically on the 1st. Run `/ledger` to see it.",
            ephemeral=True,
        )

    @app_commands.command(name="wifi_bill", description="Wifi is added automatically by Piggy")
    async def wifi_bill(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Piggy adds wifi to the ledger automatically on the 1st. Run `/ledger` to see it.",
            ephemeral=True,
        )

    @app_commands.command(name="ledger", description="See the recent ledger and balance")
    async def leder(self, interaction: discord.Interaction):
        try:
            net = await piggy.balance(interaction.user.id)
            rows = await piggy.entries(interaction.user.id, 20)
        except piggy.PiggyError:
            await interaction.response.send_message(PIGGY_DOWN, ephemeral=True)
            return
        lines = []
        for e in rows:
            sign = "+" if e["signed_cents"] > 0 else "−"
            lines.append(f"{e['occurred_on'][5:].replace('-', '/')} • {sign}{_format_money(e['amount_cents'])} {e['note']}")
        embed = discord.Embed(
            title="📒 Ledger (latest 20, + means they owe you)",
            description="\n".join(lines) or "Nothing yet.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Balance", value=_format_net_message(net), inline=False)
        embed.set_footer(text="Full history: finance.djiang.xyz/ledger")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Budget(bot))
