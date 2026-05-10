"""Chore tracker — recurring templates that materialize into instances.

Schema is two tables:
  ChoreTemplate    — recurring rule (weekly / monthly), assignment strategy
  ChoreInstance   — actual assignments with due dates

One-off chores are ChoreInstance rows with template_id=NULL — no template
needed. Recurring instances are materialized by a daily background task.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import typing as t
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from src.db import ChoreInstance, ChoreTemplate
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

ALLOWED_RECURRENCES = ("weekly", "monthly")
WEEKLY_CHANNEL_NAME = "weekly-chores"
MONTHLY_CHANNEL_NAME = "monthly-chores"

# Map each partner to the other so "alternate" rotation works without env config.
_PARTNER: dict[int, int] = {DAVID_ID: STEPH_ID, STEPH_ID: DAVID_ID}


# ---------------------------------------------------------------------------
# Recurrence helpers (pure)
# ---------------------------------------------------------------------------


def next_due_for(recurrence: str, today: _dt.date) -> _dt.date:
    """Return the next due date for a recurrence rule starting from ``today``.

    weekly  → next Monday (or today if today is Monday)
    monthly → first of next month
    """
    if recurrence == "weekly":
        days_ahead = (0 - today.weekday()) % 7  # 0 = Monday
        return today + _dt.timedelta(days=days_ahead)
    if recurrence == "monthly":
        if today.month == 12:
            return _dt.date(today.year + 1, 1, 1)
        return _dt.date(today.year, today.month + 1, 1)
    raise ValueError(f"unknown recurrence: {recurrence!r}")


def pick_next_assignee(template: ChoreTemplate) -> int:
    """Return the user_id who should be assigned the next instance.

    - If ``default_assignee_id`` is set, always return that.
    - Otherwise alternate from ``last_assignee_id`` using the David/Steph pair.
      First-time templates (last_assignee_id is None) start with David.
    """
    if template.default_assignee_id is not None:
        return template.default_assignee_id
    if template.last_assignee_id is None:
        return DAVID_ID
    return _PARTNER.get(template.last_assignee_id, DAVID_ID)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class Chores(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot
        self._materialized_dates: set[_dt.date] = set()
        self.materialize_loop.start()

    def cog_unload(self) -> None:
        self.materialize_loop.cancel()

    chore = app_commands.Group(name="chore", description="Chore tracker")

    # ------------------------------------------------------------------ #
    # /chore add — one-off                                                 #
    # ------------------------------------------------------------------ #

    @chore.command(name="add", description="Add a one-off chore (no recurrence)")
    @app_commands.describe(
        name="What needs to be done",
        due="Due date (YYYY-MM-DD)",
        assignee="Who should do it (defaults to you)",
    )
    async def chore_add(
        self,
        interaction: discord.Interaction,
        name: str,
        due: str,
        assignee: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer()
        try:
            due_date = _dt.date.fromisoformat(due)
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid date — use YYYY-MM-DD (e.g. `2026-05-15`).",
                ephemeral=True,
            )
            return

        guild_id = interaction.guild_id or 0
        assignee_id = (assignee.id if assignee else interaction.user.id)

        async with self.bot.db() as s:
            row = ChoreInstance(
                guild_id=guild_id,
                template_id=None,
                name=name,
                assignee_id=assignee_id,
                due_date=due_date,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)

        await interaction.followup.send(
            f"✅ Chore #{row.id} added — **{name}**, due {due_date}, assigned to <@{assignee_id}>."
        )

    # ------------------------------------------------------------------ #
    # /chore template — recurring                                          #
    # ------------------------------------------------------------------ #

    @chore.command(name="template", description="Create a recurring chore template")
    @app_commands.describe(
        name="Chore name",
        recurrence="weekly or monthly",
        assignee="Default assignee (omit to alternate between partners)",
    )
    @app_commands.choices(
        recurrence=[
            app_commands.Choice(name="weekly", value="weekly"),
            app_commands.Choice(name="monthly", value="monthly"),
        ]
    )
    async def chore_template(
        self,
        interaction: discord.Interaction,
        name: str,
        recurrence: app_commands.Choice[str],
        assignee: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer()
        guild_id = interaction.guild_id or 0
        rec = recurrence.value
        default_assignee_id = assignee.id if assignee else None

        async with self.bot.db() as s:
            template = ChoreTemplate(
                guild_id=guild_id,
                name=name,
                recurrence=rec,
                default_assignee_id=default_assignee_id,
                active=True,
            )
            s.add(template)
            await s.flush()
            # Materialize the first instance immediately so the chore shows up
            # in /chores without waiting for the daily loop.
            await self._materialize_template(s, template)
            await s.commit()
            await s.refresh(template)

        rotation = (
            f"<@{default_assignee_id}> (fixed)"
            if default_assignee_id
            else "alternating between David & Stephanie"
        )
        await interaction.followup.send(
            f"✅ Template #{template.id} created — **{name}** ({rec}), {rotation}."
        )

    # ------------------------------------------------------------------ #
    # /chore complete                                                      #
    # ------------------------------------------------------------------ #

    @chore.command(name="complete", description="Mark a chore instance as done")
    @app_commands.describe(chore_id="ID of the chore (from /chores)")
    async def chore_complete(
        self, interaction: discord.Interaction, chore_id: int
    ) -> None:
        await interaction.response.defer()
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            row = await s.get(ChoreInstance, chore_id)
            if row is None or row.guild_id != guild_id:
                await interaction.followup.send(
                    f"❌ No chore #{chore_id} found.", ephemeral=True
                )
                return
            if row.completed:
                await interaction.followup.send(
                    f"**{row.name}** was already marked done.", ephemeral=True
                )
                return
            row.completed = True
            row.completed_at = datetime.now(timezone.utc)
            row.completed_by = interaction.user.id
            await s.commit()

        await interaction.followup.send(
            f"✅ **{row.name}** marked done by <@{interaction.user.id}>."
        )

    @chore_complete.autocomplete("chore_id")
    async def _complete_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        async with self.bot.db() as s:
            rows = list(
                (
                    await s.scalars(
                        select(ChoreInstance)
                        .where(
                            ChoreInstance.guild_id == (interaction.guild_id or 0),
                            ChoreInstance.completed == False,  # noqa: E712
                        )
                        .order_by(ChoreInstance.due_date)
                        .limit(25)
                    )
                ).all()
            )
        return [
            app_commands.Choice(
                name=f"#{r.id} {r.name} (due {r.due_date})",
                value=r.id,
            )
            for r in rows
            if not current or current.lower() in r.name.lower()
        ]

    # ------------------------------------------------------------------ #
    # /chores — list active                                                #
    # ------------------------------------------------------------------ #

    @app_commands.command(name="chores", description="List active (incomplete) chores")
    async def list_chores(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        guild_id = interaction.guild_id or 0
        today = _dt.date.today()

        async with self.bot.db() as s:
            rows = list(
                (
                    await s.scalars(
                        select(ChoreInstance)
                        .where(
                            ChoreInstance.guild_id == guild_id,
                            ChoreInstance.completed == False,  # noqa: E712
                        )
                        .order_by(ChoreInstance.due_date)
                    )
                ).all()
            )

        if not rows:
            await interaction.followup.send(
                "🎉 No active chores. Use `/chore add` or `/chore template` to set some up."
            )
            return

        embed = discord.Embed(title="🧹 Active Chores", color=discord.Color.blurple())
        overdue: list[ChoreInstance] = []
        today_rows: list[ChoreInstance] = []
        upcoming: list[ChoreInstance] = []
        for r in rows:
            if r.due_date < today:
                overdue.append(r)
            elif r.due_date == today:
                today_rows.append(r)
            else:
                upcoming.append(r)

        def _fmt(r: ChoreInstance) -> str:
            return f"`#{r.id}` **{r.name}** — due {r.due_date} · <@{r.assignee_id}>"

        if overdue:
            embed.add_field(
                name=f"🔴 Overdue ({len(overdue)})",
                value="\n".join(_fmt(r) for r in overdue[:10]),
                inline=False,
            )
        if today_rows:
            embed.add_field(
                name=f"📅 Today ({len(today_rows)})",
                value="\n".join(_fmt(r) for r in today_rows[:10]),
                inline=False,
            )
        if upcoming:
            embed.add_field(
                name=f"📆 Upcoming ({len(upcoming)})",
                value="\n".join(_fmt(r) for r in upcoming[:10]),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    # /chore_templates — list templates                                    #
    # ------------------------------------------------------------------ #

    @chore.command(name="templates", description="List recurring chore templates")
    async def list_templates(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            rows = list(
                (
                    await s.scalars(
                        select(ChoreTemplate)
                        .where(
                            ChoreTemplate.guild_id == guild_id,
                            ChoreTemplate.active == True,  # noqa: E712
                        )
                        .order_by(ChoreTemplate.recurrence, ChoreTemplate.name)
                    )
                ).all()
            )

        if not rows:
            await interaction.followup.send(
                "No chore templates yet. Use `/chore template` to add one."
            )
            return

        embed = discord.Embed(title="🔁 Chore Templates", color=discord.Color.blurple())
        for r in rows:
            assignee = (
                f"<@{r.default_assignee_id}>"
                if r.default_assignee_id
                else "alternating"
            )
            last = (
                f" · last did: <@{r.last_assignee_id}>" if r.last_assignee_id else ""
            )
            embed.add_field(
                name=f"#{r.id} {r.name} ({r.recurrence})",
                value=f"Assignee: {assignee}{last}",
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    @chore.command(
        name="template_remove", description="Deactivate a chore template (keeps history)"
    )
    @app_commands.describe(template_id="ID of the template to deactivate")
    async def template_remove(
        self, interaction: discord.Interaction, template_id: int
    ) -> None:
        await interaction.response.defer()
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            row = await s.get(ChoreTemplate, template_id)
            if row is None or row.guild_id != guild_id or not row.active:
                await interaction.followup.send(
                    f"❌ No active template #{template_id} found.", ephemeral=True
                )
                return
            row.active = False
            row.updated_at = datetime.now(timezone.utc)
            await s.commit()

        await interaction.followup.send(
            f"🗑️ Template #{template_id} (**{row.name}**) deactivated. Existing instances stay active."
        )

    # ------------------------------------------------------------------ #
    # Materialization                                                      #
    # ------------------------------------------------------------------ #

    async def _materialize_template(
        self, session, template: ChoreTemplate
    ) -> ChoreInstance | None:
        """Create the next instance for a template if one isn't already pending.

        Returns the new (or existing pending) instance, or None if the template
        is inactive.
        """
        if not template.active:
            return None

        existing = await session.scalar(
            select(ChoreInstance).where(
                ChoreInstance.template_id == template.id,
                ChoreInstance.completed == False,  # noqa: E712
            )
        )
        if existing is not None:
            return existing

        today = datetime.now(ET).date()
        due = next_due_for(template.recurrence, today)
        assignee_id = pick_next_assignee(template)

        instance = ChoreInstance(
            guild_id=template.guild_id,
            template_id=template.id,
            name=template.name,
            assignee_id=assignee_id,
            due_date=due,
        )
        session.add(instance)
        template.last_assignee_id = assignee_id
        template.updated_at = datetime.now(timezone.utc)
        return instance

    @tasks.loop(hours=6)
    async def materialize_loop(self) -> None:
        """Periodically ensure each active template has a pending instance.

        Runs every 6 hours; first pass after startup creates anything missed
        while the bot was offline. Idempotent — _materialize_template returns
        the existing instance if one is already pending.
        """
        today = datetime.now(ET).date()
        if today in self._materialized_dates:
            return

        async with self.bot.db() as s:
            templates = list(
                (
                    await s.scalars(
                        select(ChoreTemplate).where(
                            ChoreTemplate.active == True,  # noqa: E712
                        )
                    )
                ).all()
            )
            for tmpl in templates:
                await self._materialize_template(s, tmpl)
            await s.commit()

        self._materialized_dates.add(today)
        # Cap memory: keep last 30 days only
        if len(self._materialized_dates) > 30:
            self._materialized_dates = {
                d for d in self._materialized_dates if (today - d).days < 30
            }
        log.info("chores materialize_loop ran for %d templates", len(templates))

    @materialize_loop.before_loop
    async def _before_materialize_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chores(bot))
