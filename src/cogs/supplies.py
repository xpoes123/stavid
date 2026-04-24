# src/cogs/supplies.py
from __future__ import annotations

import asyncio
import json
import os
import typing as t
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import func, select

from src.db import SupplyCheckResult, SupplyItem

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "supply_items.json"


def _load_default_items(path: Path = _CONFIG_PATH) -> list[str]:
    """Return the default item names from the config file."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


async def seed_supply_items(session, guild_id: int, names: list[str]) -> int:
    """Insert items from *names* that have no existing row for *guild_id*.

    Rows that exist but are inactive (soft-deleted) are left untouched —
    the user removed them intentionally.  Returns the count of new rows added.
    """
    existing_names = {
        n.lower()
        for n in (
            await session.scalars(
                select(SupplyItem.name).where(SupplyItem.guild_id == guild_id)
            )
        ).all()
    }
    to_add = [n for n in names if n.lower() not in existing_names]
    for name in to_add:
        session.add(SupplyItem(guild_id=guild_id, name=name, active=True))
    if to_add:
        await session.commit()
    return len(to_add)

if t.TYPE_CHECKING:
    from src.main import StavidBot

ET = ZoneInfo("America/New_York")


def _this_sunday(d: date) -> date:
    """Return the most recent Sunday on or before d."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _build_status_embed(
    items: list[SupplyItem],
    flagged_item_ids: set[int],
    week_of: date,
) -> discord.Embed:
    """Build the supply check embed showing current flag status."""
    lines = []
    for item in items:
        if item.id in flagged_item_ids:
            lines.append(f"🔴 ~~{item.name}~~ _needs restock_")
        else:
            lines.append(f"• {item.name}")

    embed = discord.Embed(
        title=f"🛒 Weekly Supply Check — {week_of.strftime('week of %b %d')}",
        description="\n".join(lines) if lines else "_No items tracked yet._",
        color=discord.Color.blue(),
    )
    embed.set_footer(text="Select items below that are running low!")
    return embed


class SupplyCheckView(discord.ui.View):
    """Interactive dropdown view for the weekly supply check."""

    def __init__(
        self,
        items: list[SupplyItem],
        guild_id: int,
        week_of: date,
        db,  # sessionmaker
    ) -> None:
        super().__init__(timeout=86400)  # 24 hours
        self.items = items
        self.guild_id = guild_id
        self.week_of = week_of
        self.db = db

        if not items:
            return

        # Discord Select menus cap at 25 options per menu.
        # Split into chunks if needed.
        chunks = [items[i:i + 25] for i in range(0, len(items), 25)]
        for idx, chunk in enumerate(chunks):
            options = [
                discord.SelectOption(label=item.name, value=str(item.id))
                for item in chunk
            ]
            select = SupplySelectMenu(
                options=options,
                placeholder=(
                    "Select items that are running low…"
                    if idx == 0
                    else f"More items ({idx + 1}/{len(chunks)})…"
                ),
                guild_id=guild_id,
                week_of=week_of,
                db=db,
                view_ref=self,
                all_items=items,
            )
            self.add_item(select)


class SupplySelectMenu(discord.ui.Select):
    def __init__(
        self,
        options: list[discord.SelectOption],
        placeholder: str,
        guild_id: int,
        week_of: date,
        db,
        view_ref: SupplyCheckView,
        all_items: list[SupplyItem],
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=len(options),
            options=options,
        )
        self.guild_id = guild_id
        self.week_of = week_of
        self.db = db
        self.view_ref = view_ref
        self.all_items = all_items

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_ids = [int(v) for v in self.values]
        user_id = interaction.user.id

        newly_flagged: list[str] = []
        already_flagged: list[str] = []
        item_by_id = {item.id: item for item in self.all_items}

        async with self.db() as s:
            for item_id in selected_ids:
                existing = await s.scalar(
                    select(SupplyCheckResult).where(
                        SupplyCheckResult.guild_id == self.guild_id,
                        SupplyCheckResult.week_of == self.week_of,
                        SupplyCheckResult.item_id == item_id,
                        SupplyCheckResult.user_id == user_id,
                    )
                )
                if existing:
                    item = item_by_id.get(item_id)
                    if item:
                        already_flagged.append(item.name)
                    continue

                s.add(
                    SupplyCheckResult(
                        guild_id=self.guild_id,
                        week_of=self.week_of,
                        item_id=item_id,
                        user_id=user_id,
                    )
                )
                item = item_by_id.get(item_id)
                if item:
                    newly_flagged.append(item.name)

            await s.commit()

            # Fetch all flags so far to update the embed
            all_item_ids = [item.id for item in self.all_items]
            flagged_rows = (
                await s.scalars(
                    select(SupplyCheckResult).where(
                        SupplyCheckResult.guild_id == self.guild_id,
                        SupplyCheckResult.week_of == self.week_of,
                        SupplyCheckResult.item_id.in_(all_item_ids),
                    )
                )
            ).all()

        flagged_item_ids = {row.item_id for row in flagged_rows}

        # Build response message
        parts = []
        if newly_flagged:
            parts.append(f"Flagged for restock: {', '.join(newly_flagged)}")
        if already_flagged:
            parts.append(f"Already flagged (skipped): {', '.join(already_flagged)}")
        if not newly_flagged and not already_flagged:
            parts.append("Nothing selected — no changes made.")

        reply = "\n".join(parts)

        # Update the original message embed to reflect current flags
        updated_embed = _build_status_embed(self.all_items, flagged_item_ids, self.week_of)
        await interaction.response.edit_message(embed=updated_embed, view=self.view_ref)
        await interaction.followup.send(reply, ephemeral=True)


class Supplies(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot
        self._checked_sundays: set[date] = set()
        self.weekly_supply_check.start()

    def cog_unload(self) -> None:
        self.weekly_supply_check.cancel()

    async def cog_load(self) -> None:
        asyncio.create_task(self._seed_default_items())

    async def _seed_default_items(self) -> None:
        """Seed default items from config into every guild on startup."""
        await self.bot.wait_until_ready()
        names = _load_default_items()
        if not names:
            return
        for guild in self.bot.guilds:
            async with self.bot.db() as s:
                await seed_supply_items(s, guild.id, names)

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

    async def _build_checklist_embed(
        self, guild_id: int, week_of: date
    ) -> tuple[discord.Embed, SupplyCheckView]:
        """Return the embed and interactive view for the weekly checklist."""
        async with self.bot.db() as s:
            items = await self._active_items(guild_id, s)

        if not items:
            embed = discord.Embed(
                title="🛒 Weekly Supply Check",
                description="No items tracked yet.\nUse `/supply_add` to add household supplies!",
                color=discord.Color.blue(),
            )
            embed.set_footer(text="Select items below that are running low!")
            return embed, SupplyCheckView([], guild_id, week_of, self.bot.db)

        embed = _build_status_embed(items, set(), week_of)
        view = SupplyCheckView(items, guild_id, week_of, self.bot.db)
        return embed, view

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
        embed = _build_status_embed(items, flagged_item_ids, week_of)
        view = SupplyCheckView(items, guild_id, week_of, self.bot.db)
        await interaction.response.send_message(embed=embed, view=view)

    # ------------------------------------------------------------------ #
    # Background task                                                      #
    # ------------------------------------------------------------------ #

    @tasks.loop(hours=1)
    async def weekly_supply_check(self) -> None:
        """Every Sunday at 10am ET, post the supply checklist to the channel."""
        now_et = datetime.now(ET)
        today = now_et.date()

        # weekday() == 6 is Sunday; fire at 10:00
        if now_et.weekday() != 6 or now_et.hour != 10 or today in self._checked_sundays:
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
        embed, view = await self._build_checklist_embed(guild_id, week_of)
        await channel.send(embed=embed, view=view)

    @weekly_supply_check.before_loop
    async def before_weekly_supply_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Supplies(bot))
