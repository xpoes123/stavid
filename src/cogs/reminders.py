from __future__ import annotations

import datetime
from dataclasses import dataclass
import os
import typing as t
from decimal import ROUND_HALF_UP, Decimal

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import case, func, select

from src.db import ReminderEntry
from src.utils import DAVID_ID, STEPH_ID, resolve_partner

if t.TYPE_CHECKING:
    from src.main import StavidBot


# This class includes all of the basic commands like help and quote
class Reminder(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    async def _create_reminder_entry(
        self,
        interaction: discord.Interaction,
        date: datetime,
        note: str,
        location: str,
    ) -> int:
        partner = await resolve_partner(interaction)
        if not partner:
            return await interaction.response.send_message(
                "❌ I couldn’t infer who to remind from (set `PARTNER_IDS`).",
                ephemeral=True,
            )
        async with self.bot.db() as s:
            s.add(
                ReminderEntry(
                    guild_id=interaction.guild_id or 0,
                    creator_id=interaction.user.id,
                    partner_id=partner.id,
                    time=date,
                    note=note,
                    location=location,
                    done=False,
                )
            )
            await s.commit()

    # TODO Implement this
    @app_commands.command(
        name="remind",
        description="Create a reminder (leave date/time blank for ASAP)",
    )
    @app_commands.describe(
        date="Date of the reminder (e.g. 2025-08-08)",
        time="Time of the reminder (e.g. 15:00 for 3pm)",
        note="What should I remind you about?",
        location="Optional location tied to the reminder",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        date: str,
        time: str,
        note: str,
        location: t.Optional[str] = None,
    ) -> None:
        await interaction.response.send_message("TODO Reminder", ephemeral=True)

    # TODO Implement this
    @app_commands.command(name="reminders", description="View all active reminders")
    async def reminders(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("TODO reminders", ephemeral=True)

    # TODO Implement this
    @app_commands.command(
        name="reset_reminders", description="Mark all reminders are done"
    )
    async def reset_reminders(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("TODO reset", ephemeral=True)
