from __future__ import annotations

import os
import typing as t

import discord
from discord import app_commands, Interaction
from discord.ext import commands

if t.TYPE_CHECKING:
    from src.main import StavidBot


# ---------- Static help page content ----------

# ---------- Static help page content ----------


def basic_help_embed() -> discord.Embed:
    e = discord.Embed(
        title="🤖 StavidBot — Basic",
        description="General utility commands.",
        color=discord.Color.green(),
    )
    e.add_field(
        name="/wifi",
        value="📶 Get the guest Wi-Fi network name and password.",
        inline=False,
    )
    e.set_footer(text="Use the buttons below to switch pages.")
    return e


def playoff_help_embed() -> discord.Embed:
    e = discord.Embed(
        title="🏆 StavidBot — Playoff Week",
        description="Track your weekly habit series. Win 4 days to win the week.",
        color=discord.Color.gold(),
    )
    e.add_field(
        name="/checkin pillar1:<yes/no> pillar2:<yes/no> pillar3:<yes/no>",
        value="Log your 3 pillars for today. A WIN requires all 3. Updates your series score automatically.",
        inline=False,
    )
    e.add_field(
        name="/playoff_status",
        value="See the current series score for both David and Stephanie, plus today's check-in status.",
        inline=False,
    )
    e.add_field(
        name="/series_history",
        value="View your last 8 series results (ephemeral).",
        inline=False,
    )
    e.add_field(
        name="How it works",
        value=(
            "Each week is a best-of-7 series. Win = all 3 pillars hit. "
            "First to 4 wins takes the week. "
            "The bot pings the check-in channel at 9 pm ET if you haven't logged yet."
        ),
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
        name="/venmo amount:<number> note:<text>",
        value="Create a ledger entry that your partner owes you. Example: `/venmo amount: 23.50 note: Dinner`",
        inline=False,
    )
    e.add_field(
        name="/pay amount:<number> [note:<text>]",
        value=(
            "Record a payment **you** made. Amount has autocomplete to suggest the exact net.\n"
            "Example: `/pay amount: 50 note: Rent share`"
        ),
        inline=False,
    )
    e.add_field(
        name="/rent",
        value="Post the monthly rent split (±MONTHLY_RENT/3 depending on who runs it) and show the new balance.",
        inline=False,
    )
    e.add_field(
        name="/wifi_bill",
        value="Post the monthly Wi-Fi split (±8000/3) and show the new balance.",
        inline=False,
    )
    e.add_field(
        name="/ledger",
        value="Show an itemized list of this month’s entries and the current net.",
        inline=False,
    )
    e.add_field(
        name="Setup",
        value="Set env `PARTNER_IDS` to a comma-sep list containing both users’ IDs so the bot can infer your partner.",
        inline=False,
    )
    e.set_footer(text="Use the buttons below to switch pages.")
    return e


# ---------- Paged view ----------


class HelpPager(discord.ui.View):
    def __init__(self, start_page: str = "basic"):
        super().__init__(timeout=120)
        self.page = start_page  # "basic" | "budget" | "playoff"
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
        self.playoff_button.style = (
            discord.ButtonStyle.primary
            if self.page == "playoff"
            else discord.ButtonStyle.secondary
        )

    def _current_embed(self) -> discord.Embed:
        if self.page == "basic":
            return basic_help_embed()
        if self.page == "budget":
            return budget_help_embed()
        return playoff_help_embed()

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

    @discord.ui.button(label="Playoff", style=discord.ButtonStyle.secondary)
    async def playoff_button(self, interaction: Interaction, _: discord.ui.Button):
        await self._switch(interaction, "playoff")


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
