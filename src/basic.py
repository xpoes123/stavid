from __future__ import annotations

import os
import typing as t

import discord
from discord import app_commands
from discord.ext import commands

if t.TYPE_CHECKING:
    from src.main import StavidBot


# This class includes all of the basic commands like help and quote
class Basic(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Find out what the bot can do")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🤖 StavidBot Commands",
            description="Here are the commands you can use:",
            color=discord.Color.green(),
        )

        embed.add_field(
            name="/wifi",
            value="📶 Get the guest WiFi network name and password.",
            inline=False,
        )

        embed.set_footer(text="More commands coming soon!")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="wifi", description="Get the wifi information for guests"
    )
    async def wifi(self, interaction: discord.Interaction) -> None:
        wifi_name = os.getenv("wifi_name")
        wifi_password = os.getenv("wifi_password")
        message = (
            "**📶 Guest WiFi Information**\n"
            "```ini\n"
            f"SSID     = {wifi_name}\n"
            f"Password = {wifi_password}\n"
            "```"
        )
        await interaction.response.send_message(message, ephemeral=True)
