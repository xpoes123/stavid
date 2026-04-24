from __future__ import annotations

import typing as t

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from src.db import ShoppingItem

if t.TYPE_CHECKING:
    from src.main import StavidBot


class Shopping(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    shopping = app_commands.Group(name="shopping", description="Shared shopping list")

    @shopping.command(name="add", description="Add an item to the shopping list")
    @app_commands.describe(
        name="Item name",
        link="Optional link (URL)",
        note="Optional note",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        name: str,
        link: str = "",
        note: str = "",
    ) -> None:
        async with self.bot.db() as s:
            item = ShoppingItem(
                guild_id=interaction.guild_id or 0,
                name=name,
                link=link,
                note=note,
                added_by=interaction.user.id,
            )
            s.add(item)
            await s.commit()

        parts = [f"✅ **{name}** added to the shopping list"]
        if note:
            parts.append(f"**Note:** {note}")
        if link:
            parts.append(f"**Link:** {link}")
        await interaction.response.send_message("\n".join(parts), ephemeral=False)

    @shopping.command(name="list", description="Show the current shopping list")
    async def list(self, interaction: discord.Interaction) -> None:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(ShoppingItem)
                    .where(
                        ShoppingItem.guild_id == interaction.guild_id,
                        ShoppingItem.bought == False,  # noqa: E712
                    )
                    .order_by(ShoppingItem.created_at)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                "Shopping list is empty!", ephemeral=False
            )
            return

        embed = discord.Embed(
            title="🛒 Shopping List",
            color=discord.Color.green(),
        )
        for item in rows:
            value_parts = [f"Added by <@{item.added_by}>"]
            if item.note:
                value_parts.append(f"_{item.note}_")
            if item.link:
                value_parts.append(f"[Link]({item.link})")
            embed.add_field(
                name=item.name,
                value="\n".join(value_parts),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @shopping.command(name="remove", description="Mark an item as bought and remove it")
    @app_commands.describe(item="Item to remove")
    async def remove(self, interaction: discord.Interaction, item: str) -> None:
        async with self.bot.db() as s:
            row = await s.get(ShoppingItem, int(item))
            if row is None or row.bought or row.guild_id != interaction.guild_id:
                await interaction.response.send_message(
                    "❌ Item not found.", ephemeral=True
                )
                return
            name = row.name
            row.bought = True
            await s.commit()

        await interaction.response.send_message(
            f"✅ **{name}** marked as bought and removed from the list.",
            ephemeral=False,
        )

    @remove.autocomplete("item")
    async def remove_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(ShoppingItem)
                    .where(
                        ShoppingItem.guild_id == interaction.guild_id,
                        ShoppingItem.bought == False,  # noqa: E712
                    )
                    .order_by(ShoppingItem.created_at)
                    .limit(25)
                )
            ).all()

        return [
            app_commands.Choice(name=r.name, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.name.lower()
        ]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shopping(bot))
