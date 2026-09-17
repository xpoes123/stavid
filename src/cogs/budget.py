from __future__ import annotations

import typing as t
from decimal import ROUND_HALF_UP, Decimal

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import case, func, select

from src.db import LedgerEntry
from src.utils import DAVID_ID, STEPH_ID, resolve_partner

if t.TYPE_CHECKING:
    from src.main import StavidBot

# Steph pays the full rent; David owes her his share = total - Steph's share.
RENT_TOTAL_CENTS = 333792
STEPH_RENT_SHARE_CENTS = 90000
DAVID_RENT_SHARE_CENTS = RENT_TOTAL_CENTS - STEPH_RENT_SHARE_CENTS  # 243792

# Note written by /paid; the ledger lists only activity after the latest one.
SETTLE_NOTE = "settled up"

# Steph's share of the monthly wifi bill (David pays it, she owes this back).
WIFI_SHARE_CENTS = 3000


class PartnerResolutionError(Exception):
    """Raised by _create_ledger_entry when the partner cannot be resolved."""


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
        self,
        interaction: discord.Interaction,
        cents: int,
        note: str,
    ) -> int:
        partner = await resolve_partner(interaction)
        if not partner:
            await interaction.response.send_message(
                "❌ I couldn’t infer who to request from (set `PARTNER_IDS`).",
                ephemeral=True,
            )
            raise PartnerResolutionError
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
        try:
            net_cents = await self._create_ledger_entry(
                interaction=interaction, cents=cents, note=note
            )
        except PartnerResolutionError:
            return
        partner = await resolve_partner(interaction)
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
        try:
            net_cents = await self._create_ledger_entry(
                interaction=interaction, cents=cents, note=note
            )
        except PartnerResolutionError:
            return
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
        partner = await resolve_partner(interaction)
        if not partner:
            return [app_commands.Choice(name="Set PARTNER_IDS first", value=0.0)]

        async with self.bot.db() as s:
            net_cents = await _net_between(s, partner.id, interaction)

        label_sign = (
            "they owe you"
            if net_cents > 0
            else ("you owe them" if net_cents < 0 else "zip")
        )
        suggested_amount = abs(Decimal(net_cents) / Decimal(100))
        choices = []
        # Echo whatever the user is typing so custom amounts are one click away.
        try:
            typed = float(current)
            if typed > 0:
                choices.append(
                    app_commands.Choice(name=f"${typed:.2f}", value=typed)
                )
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
        if not partner:
            await interaction.response.send_message(
                "❌ I couldn’t infer who to settle with (set `PARTNER_IDS`).",
                ephemeral=True,
            )
            return
        async with self.bot.db() as s:
            net = await _net_between(s, partner.id, interaction)
            if net == 0:
                await interaction.response.send_message(
                    "✅ Already all square — nothing to settle."
                )
                return
            # Post one balancing entry so net → 0. net > 0 means partner owes
            # me (they pay me back); net < 0 means I owe them (I pay).
            if net > 0:
                creditor, debtor = partner.id, interaction.user.id
            else:
                creditor, debtor = interaction.user.id, partner.id
            s.add(
                LedgerEntry(
                    guild_id=interaction.guild_id or 0,
                    creditor_id=creditor,
                    debtor_id=debtor,
                    amount_cents=abs(net),
                    note=SETTLE_NOTE,
                )
            )
            await s.commit()
            new_net = await _net_between(s, partner.id, interaction)
        await interaction.response.send_message(
            f"🧹 **Settled up with {partner.mention}** — cleared {_format_money(abs(net))}.\n"
            f"{_format_net_message(new_net)}"
        )

    @app_commands.command(
        name="rent", description="Run once a month to add rent payment"
    )
    async def rent(self, interaction: discord.Interaction):
        partner = await resolve_partner(interaction)
        # Either way the result is: David owes Steph his rent share (she fronts rent).
        if interaction.user.id == DAVID_ID:
            net_cents = await self._create_ledger_entry(
                interaction, -DAVID_RENT_SHARE_CENTS, "rent"
            )
        elif interaction.user.id == STEPH_ID:
            net_cents = await self._create_ledger_entry(
                interaction, DAVID_RENT_SHARE_CENTS, "rent"
            )
        else:
            await interaction.response.send_message(
                "This command is only available to David and Steph.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"📊 **Current Balance after rent {partner.mention}:**\n{_format_net_message(net_cents)}",
        )

    @app_commands.command(
        name="wifi_bill", description="Run once a month to add wifi payment"
    )
    async def wifi_bill(self, interaction: discord.Interaction):
        partner = await resolve_partner(interaction)
        if interaction.user.id == DAVID_ID:
            net_cents = await self._create_ledger_entry(interaction, WIFI_SHARE_CENTS, "wifi")
        elif interaction.user.id == STEPH_ID:
            net_cents = await self._create_ledger_entry(interaction, -WIFI_SHARE_CENTS, "wifi")
        else:
            await interaction.response.send_message(
                "This command is only available to David and Steph.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"📊 **Current Balance after wifi {partner.mention}:**\n{_format_net_message(net_cents)}",
        )

    @app_commands.command(
        name="ledger", description="See the itemized ledger for this month"
    )
    async def leder(self, interaction: discord.Interaction):
        partner = await resolve_partner(interaction)
        async with self.bot.db() as s:
            net_cents = await _net_between(s, partner.id, interaction)
            entries: list[LedgerEntry] = await _get_ledger_itemized(
                s, partner.id, interaction
            )
        # Discord embed descriptions cap at 4096 chars; show newest 25 and note
        # the rest (they shrink to nothing once /paid is run).
        MAX_LINES = 25
        entry_lines = []
        for entry in entries[:MAX_LINES]:
            direction = "←" if entry.creditor_id == interaction.user.id else "→"
            entry_lines.append(
                f"{entry.created_at:%m/%d} • {interaction.user.mention} {direction} {partner.mention} | {_format_money(entry.amount_cents)} - {entry.note}"
            )
        if len(entries) > MAX_LINES:
            entry_lines.append(
                f"…and {len(entries) - MAX_LINES} older entries — run `/paid` to clear the balance."
            )
        embed = discord.Embed(
            title=f"📒 Ledger with {partner.display_name} (since last settle-up)",
            description="\n".join(entry_lines),  # cap if you want
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Net (running total — /paid to clear)",
            value=_format_net_message(net_cents),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        async def _format_entry_line(
            self, me_id: int, partner_id: int, e: LedgerEntry
        ) -> str:
            direction = "→" if e.creditor_id == me_id else "←"
            who = "You" if e.creditor_id == me_id else "Partner"
            return f"{e.created_at:%Y-%m-%d} • {who} {direction} {_format_money(e.amount_cents)}"


async def _get_ledger_itemized(
    s, partner_id: int, interaction: discord.Interaction
) -> list[LedgerEntry]:
    guild_id = interaction.guild_id
    me_id = interaction.user.id
    pair = (
        (LedgerEntry.creditor_id == me_id) & (LedgerEntry.debtor_id == partner_id)
        | (LedgerEntry.creditor_id == partner_id) & (LedgerEntry.debtor_id == me_id)
    )
    # Show only activity since the last /paid so the list reconciles with Net
    # (everything before a settle-up nets to zero anyway).
    last_settle = await s.scalar(
        select(func.max(LedgerEntry.created_at)).where(
            LedgerEntry.guild_id == guild_id, pair, LedgerEntry.note == SETTLE_NOTE
        )
    )
    q = select(LedgerEntry).where(LedgerEntry.guild_id == guild_id, pair)
    if last_settle is not None:
        q = q.where(LedgerEntry.created_at > last_settle)
    q = q.order_by(LedgerEntry.created_at.desc()).limit(100)
    return (await s.scalars(q)).all()


async def _net_between(s, partner_id: int, interaction: discord.Interaction) -> int:
    guild_id = interaction.guild_id
    me_id = interaction.user.id
    expr = case(
        (
            (LedgerEntry.creditor_id == me_id) & (LedgerEntry.debtor_id == partner_id),
            LedgerEntry.amount_cents,
        ),
        (
            (LedgerEntry.creditor_id == partner_id) & (LedgerEntry.debtor_id == me_id),
            -LedgerEntry.amount_cents,
        ),
        else_=0,
    )

    # ponytail: all-time running balance (the `settled` column was dropped in
    # migration 1aa83cc20783). /paid posts a balancing entry to reset it to 0;
    # reintroduce a settled flag only if you need per-entry settlement history.
    q = select(func.coalesce(func.sum(expr), 0)).where(LedgerEntry.guild_id == guild_id)

    res = await s.execute(q)
    return int(res.scalar_one())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Budget(bot))
