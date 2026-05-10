"""Reminders cog: a 60s firing loop plus /remind, /reminders, /remove_reminder."""
from __future__ import annotations

import logging
import os
import typing as t
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from src.db import ReminderEntry
from src.utils import DAVID_ID, STEPH_ID, resolve_partner

if t.TYPE_CHECKING:
    from src.main import StavidBot

log = logging.getLogger(__name__)

REMINDER_CHANNEL_NAME = "reminders"


def _fmt_dt(dt: datetime) -> str:
    """Format a UTC datetime for display."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return dt.strftime(f"%a, %b %-d at {hour}:{dt.minute:02d} {ampm} UTC")


def _parse_user_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse user-supplied date + time strings into a UTC datetime, or None."""
    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip() or "09:00"
    if not date_str:
        return None

    for date_fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d"):
        try:
            d = datetime.strptime(date_str, date_fmt).date()
            break
        except ValueError:
            continue
    else:
        return None

    for time_fmt in ("%H:%M", "%I:%M%p", "%I%p", "%H:%M:%S"):
        try:
            t_obj = datetime.strptime(time_str.replace(" ", ""), time_fmt).time()
            break
        except ValueError:
            continue
    else:
        return None

    return datetime.combine(d, t_obj).replace(tzinfo=timezone.utc)


class Reminder(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot
        self.fire_loop.start()

    def cog_unload(self) -> None:
        self.fire_loop.cancel()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _reminder_channel(self, guild_id: int) -> discord.abc.Messageable | None:
        """Return the channel reminders should fire into.

        Order: explicit ``REMINDER_CHANNEL_ID`` env var → ``#reminders`` in the
        guild → None (caller logs a warning).
        """
        chan_id = os.getenv("REMINDER_CHANNEL_ID")
        if chan_id and chan_id.isdigit():
            ch = self.bot.get_channel(int(chan_id))
            if ch is not None:
                return ch

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return None
        return discord.utils.get(guild.text_channels, name=REMINDER_CHANNEL_NAME)

    # ------------------------------------------------------------------ #
    # Background firing loop                                               #
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=60)
    async def fire_loop(self) -> None:
        """Poll for due reminders and post them in the apartment guild's #reminders channel."""
        now = datetime.now(timezone.utc)

        async with self.bot.db() as s:
            due = list(
                (
                    await s.scalars(
                        select(ReminderEntry).where(
                            ReminderEntry.done == False,  # noqa: E712
                            ReminderEntry.time <= now,
                        )
                    )
                ).all()
            )

        if not due:
            return

        fired_ids: list[int] = []
        for r in due:
            channel = self._reminder_channel(r.guild_id)
            if channel is None:
                log.warning("no reminder channel for guild %s — reminder #%d skipped", r.guild_id, r.id)
                continue

            mentions: list[str] = []
            for uid in (r.creator_id, r.partner_id):
                if uid and f"<@{uid}>" not in mentions:
                    mentions.append(f"<@{uid}>")
            mention_line = " ".join(mentions)
            body = f"⏰ {mention_line} **{r.note}**" if r.note else f"⏰ {mention_line} reminder"
            if r.location:
                body += f"\n📍 {r.location}"

            try:
                await channel.send(body)
                fired_ids.append(r.id)
            except Exception:
                log.exception("failed to send reminder #%d", r.id)

        if fired_ids:
            async with self.bot.db() as s:
                for rid in fired_ids:
                    row = await s.get(ReminderEntry, rid)
                    if row is not None:
                        row.done = True
                await s.commit()

        log.info("fired %d/%d due reminder(s)", len(fired_ids), len(due))

    @fire_loop.before_loop
    async def _before_fire_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # Slash commands                                                       #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="remind",
        description="Create a reminder that pings both partners at the given time",
    )
    @app_commands.describe(
        date="Date (YYYY-MM-DD or MM/DD/YYYY)",
        time="Time (HH:MM 24h or 9am / 3pm). Defaults to 09:00 UTC.",
        note="What to remind about",
        location="Optional location",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        date: str,
        note: str,
        time: str = "09:00",
        location: t.Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        due = _parse_user_datetime(date, time)
        if due is None:
            await interaction.followup.send(
                "❌ Could not parse date/time. Try `2026-05-12` and `15:00` (or `3pm`).",
                ephemeral=True,
            )
            return

        partner = await resolve_partner(interaction)
        partner_id = partner.id if partner else interaction.user.id

        async with self.bot.db() as s:
            row = ReminderEntry(
                guild_id=interaction.guild_id or 0,
                creator_id=interaction.user.id,
                partner_id=partner_id,
                time=due,
                note=note,
                location=location or "",
                done=False,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)

        await interaction.followup.send(
            f"✅ Reminder #{row.id} set for {_fmt_dt(due)} — **{note}**",
            ephemeral=True,
        )

    @app_commands.command(name="reminders", description="List active reminders for this guild")
    async def reminders(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db() as s:
            rows = list(
                (
                    await s.scalars(
                        select(ReminderEntry)
                        .where(
                            ReminderEntry.guild_id == (interaction.guild_id or 0),
                            ReminderEntry.done == False,  # noqa: E712
                        )
                        .order_by(ReminderEntry.time)
                    )
                ).all()
            )

        if not rows:
            await interaction.followup.send("No active reminders.", ephemeral=True)
            return

        lines = [
            f"**#{r.id}** — {r.note or '_(no note)_'}\n"
            f"  Due: {_fmt_dt(r.time)}"
            + (f" · 📍 {r.location}" if r.location else "")
            for r in rows
        ]
        text = "\n\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n…"
        await interaction.followup.send(f"**Active reminders:**\n\n{text}", ephemeral=True)

    @app_commands.command(
        name="remove_reminder",
        description="Mark a reminder as done by ID",
    )
    @app_commands.describe(reminder_id="ID of the reminder to mark done")
    async def remove_reminder(
        self, interaction: discord.Interaction, reminder_id: int
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db() as s:
            row = await s.get(ReminderEntry, reminder_id)
            if (
                row is None
                or row.done
                or row.guild_id != (interaction.guild_id or 0)
            ):
                await interaction.followup.send(
                    f"❌ No active reminder #{reminder_id} found.",
                    ephemeral=True,
                )
                return
            row.done = True
            await s.commit()

        await interaction.followup.send(
            f"✅ Reminder #{reminder_id} marked as done.",
            ephemeral=True,
        )

    @app_commands.command(
        name="reset_reminders", description="Mark all active reminders as done"
    )
    async def reset_reminders(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db() as s:
            rows = list(
                (
                    await s.scalars(
                        select(ReminderEntry).where(
                            ReminderEntry.guild_id == (interaction.guild_id or 0),
                            ReminderEntry.done == False,  # noqa: E712
                        )
                    )
                ).all()
            )
            for row in rows:
                row.done = True
            await s.commit()

        await interaction.followup.send(
            f"✅ Marked {len(rows)} reminder(s) as done.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminder(bot))
