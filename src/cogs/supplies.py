# src/cogs/supplies.py
from __future__ import annotations

import os
import typing as t
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import func, select

from src.db import SupplyCheckResult, SupplyItem

if t.TYPE_CHECKING:
    from src.main import StavidBot

ET = ZoneInfo("America/New_York")


def _this_sunday(d: date) -> date:
    """Return the most recent Sunday on or before d."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


class Supplies(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot
        self._checked_sundays: set[date] = set()
        self.weekly_supply_check.start()

    def cog_unload(self) -> None:
        self.weekly_supply_check.cancel()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    async def _active_items(self, guild_id: int, session) -> list[SupplyItem]:
        return list(
            (
                await session.scalars(
                    select(SupplyItem)
                    .where(
                        SupplyItem.guild_id == guild_id,
                        SupplyItem.active.is_(True),
                    )
                    .order_by(SupplyItem.name)
                )
            ).all()
        )

    async def _build_checklist_message(self, guild_id: int, week_of: date) -> str:
        """Return the formatted Sunday checklist string."""
        async with self.bot.db() as s:
            items = await self._active_items(guild_id, s)

        if not items:
            return (
                "🛒 **Weekly Supply Check** — no items tracked yet.\n"
                "Use `/supply_add` to add household supplies to the checklist!"
            )

        item_lines = "\n".join(f"• {item.name}" for item in items)
        return (
            f"🛒 **Weekly Supply Check** — {week_of.strftime('week of %b %d')}\n\n"
            f"{item_lines}\n\n"
            "Use `/supply_restock` to flag anything that's running low!"
        )

    # ------------------------------------------------------------------ #
    # Autocomplete                                                         #
    # ------------------------------------------------------------------ #

    async def _item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            items = await self._active_items(guild_id, s)
        return [
            app_commands.Choice(name=item.name, value=item.name)
            for item in items
            if current.lower() in item.name.lower()
        ][:25]

    # ------------------------------------------------------------------ #
    # Commands                                                             #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="supply_add",
        description="Add a household supply item to the weekly checklist",
    )
    async def supply_add(self, interaction: discord.Interaction, name: str) -> None:
        guild_id = interaction.guild_id or 0
        name = name.strip()
        if not name:
            await interaction.response.send_message(
                "Item name cannot be empty.", ephemeral=True
            )
            return

        async with self.bot.db() as s:
            existing = await s.scalar(
                select(SupplyItem).where(
                    SupplyItem.guild_id == guild_id,
                    func.lower(SupplyItem.name) == name.lower(),
                )
            )
            if existing:
                if not existing.active:
                    existing.active = True
                    await s.commit()
                    await interaction.response.send_message(
                        f"✅ **{existing.name}** re-added to the supply checklist!",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"**{existing.name}** is already on the checklist.",
                        ephemeral=True,
                    )
                return

            s.add(SupplyItem(guild_id=guild_id, name=name))
            await s.commit()

        await interaction.response.send_message(
            f"✅ Added **{name}** to the weekly supply checklist!", ephemeral=True
        )

    @app_commands.command(
        name="supply_remove",
        description="Remove an item from the supply checklist",
    )
    @app_commands.autocomplete(name=_item_autocomplete)
    async def supply_remove(self, interaction: discord.Interaction, name: str) -> None:
        guild_id = interaction.guild_id or 0

        async with self.bot.db() as s:
            item = await s.scalar(
                select(SupplyItem).where(
                    SupplyItem.guild_id == guild_id,
                    func.lower(SupplyItem.name) == name.strip().lower(),
                    SupplyItem.active.is_(True),
                )
            )
            if not item:
                await interaction.response.send_message(
                    f"**{name}** wasn't found on the active checklist.", ephemeral=True
                )
                return

            item.active = False
            await s.commit()

        await interaction.response.send_message(
            f"🗑️ **{item.name}** removed from the supply checklist.", ephemeral=True
        )

    @app_commands.command(
        name="supply_list",
        description="Show all tracked supply items and recent restock history",
    )
    async def supply_list(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        four_weeks_ago = _this_sunday(datetime.now(ET).date()) - timedelta(weeks=4)

        async with self.bot.db() as s:
            items = await self._active_items(guild_id, s)

            if not items:
                await interaction.response.send_message(
                    "No supply items tracked yet. Use `/supply_add` to get started!",
                    ephemeral=True,
                )
                return

            # Count restock flags per item over the last 4 weeks
            item_ids = [item.id for item in items]
            restock_rows = (
                await s.execute(
                    select(
                        SupplyCheckResult.item_id,
                        func.count(SupplyCheckResult.id).label("cnt"),
                    )
                    .where(
                        SupplyCheckResult.guild_id == guild_id,
                        SupplyCheckResult.item_id.in_(item_ids),
                        SupplyCheckResult.week_of >= four_weeks_ago,
                    )
                    .group_by(SupplyCheckResult.item_id)
                )
            ).all()

        restock_counts = {row.item_id: row.cnt for row in restock_rows}

        lines = []
        for item in items:
            count = restock_counts.get(item.id, 0)
            freq = f" _(restocked {count}x in last 4 wks)_" if count else ""
            lines.append(f"• {item.name}{freq}")

        embed = discord.Embed(
            title="🛒 Supply Checklist",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Use /supply_add or /supply_remove to manage items")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="supply_restock",
        description="Flag a supply item as needing restock this week",
    )
    @app_commands.autocomplete(name=_item_autocomplete)
    async def supply_restock(self, interaction: discord.Interaction, name: str) -> None:
        guild_id = interaction.guild_id or 0
        week_of = _this_sunday(datetime.now(ET).date())

        async with self.bot.db() as s:
            item = await s.scalar(
                select(SupplyItem).where(
                    SupplyItem.guild_id == guild_id,
                    func.lower(SupplyItem.name) == name.strip().lower(),
                    SupplyItem.active.is_(True),
                )
            )
            if not item:
                await interaction.response.send_message(
                    f"**{name}** wasn't found on the active checklist.", ephemeral=True
                )
                return

            # Idempotent — one record per (guild, week, item, user)
            existing = await s.scalar(
                select(SupplyCheckResult).where(
                    SupplyCheckResult.guild_id == guild_id,
                    SupplyCheckResult.week_of == week_of,
                    SupplyCheckResult.item_id == item.id,
                    SupplyCheckResult.user_id == interaction.user.id,
                )
            )
            if existing:
                await interaction.response.send_message(
                    f"You already flagged **{item.name}** for restock this week.",
                    ephemeral=True,
                )
                return

            s.add(
                SupplyCheckResult(
                    guild_id=guild_id,
                    week_of=week_of,
                    item_id=item.id,
                    user_id=interaction.user.id,
                )
            )
            await s.commit()

        await interaction.response.send_message(
            f"🛒 **{item.name}** flagged for restock this week!", ephemeral=True
        )

    @app_commands.command(
        name="supply_check",
        description="Post the weekly supply checklist now (or show this week's flags)",
    )
    async def supply_check(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        week_of = _this_sunday(datetime.now(ET).date())

        async with self.bot.db() as s:
            items = await self._active_items(guild_id, s)

            if not items:
                await interaction.response.send_message(
                    "No supply items tracked yet. Use `/supply_add` to get started!",
                    ephemeral=True,
                )
                return

            item_ids = [item.id for item in items]
            flagged_rows = (
                await s.scalars(
                    select(SupplyCheckResult).where(
                        SupplyCheckResult.guild_id == guild_id,
                        SupplyCheckResult.week_of == week_of,
                        SupplyCheckResult.item_id.in_(item_ids),
                    )
                )
            ).all()

        flagged_item_ids = {row.item_id for row in flagged_rows}
        item_by_id = {item.id: item for item in items}

        lines = []
        for item in items:
            flag = " 🔴 _needs restock_" if item.id in flagged_item_ids else ""
            lines.append(f"• {item.name}{flag}")

        embed = discord.Embed(
            title=f"🛒 Supply Check — {week_of.strftime('week of %b %d')}",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        if flagged_item_ids:
            flagged_names = ", ".join(
                item_by_id[fid].name
                for fid in flagged_item_ids
                if fid in item_by_id
            )
            embed.set_footer(text=f"Flagged for restock: {flagged_names}")
        else:
            embed.set_footer(text="Nothing flagged yet — use /supply_restock to log what's low")

        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------ #
    # Background task                                                      #
    # ------------------------------------------------------------------ #

    @tasks.loop(hours=1)
    async def weekly_supply_check(self) -> None:
        """Every Sunday at noon ET, post the supply checklist to the channel."""
        now_et = datetime.now(ET)
        today = now_et.date()

        # weekday() == 6 is Sunday; fire at 12:00
        if now_et.weekday() != 6 or now_et.hour != 12 or today in self._checked_sundays:
            return
        self._checked_sundays.add(today)

        channel_id = os.getenv("CHECKIN_CHANNEL_ID")
        if not channel_id or not channel_id.isdigit():
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            return

        guild_id = channel.guild.id if channel.guild else 0
        week_of = _this_sunday(today)
        message = await self._build_checklist_message(guild_id, week_of)
        await channel.send(message)

    @weekly_supply_check.before_loop
    async def before_weekly_supply_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Supplies(bot))
