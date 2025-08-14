from __future__ import annotations

import os
import typing as t

import discord
from discord import app_commands, Interaction
from discord.ext import commands

if t.TYPE_CHECKING:
    from src.main import StavidBot


# ---------- Static help page content ----------


def basic_help_embed() -> discord.Embed:
    e = discord.Embed(
        title="🤖 StavidBot — Basic",
        description="General utility commands.",
        color=discord.Color.green(),
    )
    e.add_field(
        name="/wifi",
        value="📶 Get the guest Wi‑Fi network name and password.",
        inline=False,
    )
    e.set_footer(text="Use the buttons below to switch pages.")
    return e


def budget_help_embed() -> discord.Embed:
    e = discord.Embed(
        title="💸 StavidBot — Budget",
        description="Track shared expenses and payments.",
        color=discord.Color.blurple(),
    )
    e.add_field(
        name="/venmo",
        value="Log an expense owed by your partner. Example: `/venmo amount: 23.50 note: Dinner`",
        inline=False,
    )
    e.add_field(
        name="/pay",
        value="Record a payment you made. Example: `/pay amount: 50 note: Rent share`",
        inline=False,
    )
    e.add_field(
        name="/balance",
        value="Check the current net balance between you and your partner.",
        inline=False,
    )
    e.set_footer(text="Use the buttons below to switch pages.")
    return e


# ---------- Paged view ----------


class HelpPager(discord.ui.View):
    def __init__(self, start_page: str = "basic"):
        super().__init__(timeout=120)
        self.page = start_page  # "basic" | "budget"
        self._sync_button_styles()

    def _sync_button_styles(self):
        # Highlight the active page
        self.basic_button.style = (
            discord.ButtonStyle.primary
            if self.page == "basic"
            else discord.ButtonStyle.secondary
        )
        self.budget_button.style = (
            discord.ButtonStyle.primary
            if self.page == "budget"
            else discord.ButtonStyle.secondary
        )

    def _current_embed(self) -> discord.Embed:
        return basic_help_embed() if self.page == "basic" else budget_help_embed()

    async def _switch(self, interaction: Interaction, to: str):
        self.page = to
        self._sync_button_styles()
        await interaction.response.edit_message(embed=self._current_embed(), view=self)

    @discord.ui.button(label="Basic", style=discord.ButtonStyle.primary)
    async def basic_button(self, interaction: Interaction, _: discord.ui.Button):
        await self._switch(interaction, "basic")

    @discord.ui.button(label="Budget", style=discord.ButtonStyle.secondary)
    async def budget_button(self, interaction: Interaction, _: discord.ui.Button):
        await self._switch(interaction, "budget")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: Interaction, _: discord.ui.Button):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(
            content="Help closed.", embed=None, view=self
        )
        self.stop()


# ---------- Cog ----------


class Basic(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Find out what the bot can do")
    async def help(self, interaction: Interaction) -> None:
        view = HelpPager(start_page="basic")
        await interaction.response.send_message(
            embed=basic_help_embed(), view=view, ephemeral=True
        )

    @app_commands.command(
        name="wifi", description="Get the wifi information for guests"
    )
    async def wifi(self, interaction: Interaction) -> None:
        wifi_name = os.getenv("wifi_name") or "Unknown"
        wifi_password = os.getenv("wifi_password") or "Unknown"
        message = (
            "**📶 Guest Wi‑Fi Information**\n"
            "```ini\n"
            f"SSID     = {wifi_name}\n"
            f"Password = {wifi_password}\n"
            "```"
        )
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Basic(bot))
