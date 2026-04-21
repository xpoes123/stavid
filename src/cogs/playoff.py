# src/cogs/playoff.py
from __future__ import annotations

import os
import typing as t
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from src.db import DailyResult, PlayoffCheckin, PlayoffSeries, WeeklyReview
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

ET = ZoneInfo("America/New_York")

DAVID_PILLARS = [
    "Write & reflect on daily priorities",
    "10,000 steps",
    "Max Claude usage or 30min on personal project",
]
STEPH_PILLARS = [
    "TikTok ≤ 90 minutes",
    "Some form of movement",
    "At least 15 min on a finite project",
]


def get_pillar_names(user_id: int) -> list[str]:
    if user_id == DAVID_ID:
        return DAVID_PILLARS
    if user_id == STEPH_ID:
        return STEPH_PILLARS
    return ["Pillar 1", "Pillar 2", "Pillar 3"]


def today_et() -> date:
    return datetime.now(ET).date()


def week_start_for(d: date) -> date:
    """Return the Sunday that starts the week containing d (weeks run Sun–Sat)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def series_message(wins: int, losses: int) -> str:
    """Return motivational / status text for current series score."""
    if wins >= 4:
        return "🏆 **Series Won!** You won the week!"
    if losses >= 4:
        return "💀 Series lost. Better luck next week."

    wins_needed = 4 - wins
    games_left = 7 - wins - losses

    if losses >= 3 and wins < 2:
        return (
            f"⚠️ Down {wins}–{losses} — need {wins_needed} straight. **Still alive!**"
        )
    if losses > wins:
        return (
            f"📊 Down {wins}–{losses} — still in it. "
            f"Need {wins_needed} more win{'s' if wins_needed != 1 else ''} "
            f"with {games_left} left."
        )
    if wins > losses:
        return f"✅ Up {wins}–{losses} — keep the momentum! Need {wins_needed} more."
    return f"⚖️ Tied {wins}–{losses} — anyone's series. Need {wins_needed} more."


class CheckinModal(discord.ui.Modal, title="Daily Check-in"):
    def __init__(self, pillar_names: list[str], callback) -> None:
        super().__init__()
        self._callback = callback
        self.p1 = discord.ui.TextInput(
            label=pillar_names[0][:45],
            placeholder="y or n",
            max_length=3,
        )
        self.p2 = discord.ui.TextInput(
            label=pillar_names[1][:45],
            placeholder="y or n",
            max_length=3,
        )
        self.p3 = discord.ui.TextInput(
            label=pillar_names[2][:45],
            placeholder="y or n",
            max_length=3,
        )
        self.add_item(self.p1)
        self.add_item(self.p2)
        self.add_item(self.p3)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        def parse(val: str) -> bool:
            return val.strip().lower() in ("y", "yes", "1", "true")

        await self._callback(
            interaction,
            parse(self.p1.value),
            parse(self.p2.value),
            parse(self.p3.value),
        )


class Playoff(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot
        self._pinged_dates: set[date] = set()
        self._reviewed_dates: set[date] = set()
        self.daily_ping.start()
        self.sunday_review.start()

    def cog_unload(self) -> None:
        self.daily_ping.cancel()
        self.sunday_review.cancel()

    # ------------------------------------------------------------------ #
    # Commands                                                             #
    # ------------------------------------------------------------------ #

    @app_commands.command(name="checkin", description="Log your daily pillars")
    async def checkin(self, interaction: discord.Interaction) -> None:
        modal = CheckinModal(get_pillar_names(interaction.user.id), self._process_checkin)
        await interaction.response.send_modal(modal)

    async def _process_checkin(
        self,
        interaction: discord.Interaction,
        pillar1: bool,
        pillar2: bool,
        pillar3: bool,
    ) -> None:
        today = today_et()
        week_start = week_start_for(today)
        user_id = interaction.user.id
        guild_id = interaction.guild_id or 0
        pillar_names = get_pillar_names(user_id)
        individual_win = pillar1 and pillar2 and pillar3

        async with self.bot.db() as s:
            # --- Step 1: upsert this user's individual check-in ---
            existing = await s.scalar(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == guild_id,
                    PlayoffCheckin.user_id == user_id,
                    PlayoffCheckin.checkin_date == today,
                )
            )
            if existing:
                existing.pillar1 = pillar1
                existing.pillar2 = pillar2
                existing.pillar3 = pillar3
                existing.updated_at = datetime.now(timezone.utc)
            else:
                s.add(
                    PlayoffCheckin(
                        guild_id=guild_id,
                        user_id=user_id,
                        checkin_date=today,
                        pillar1=pillar1,
                        pillar2=pillar2,
                        pillar3=pillar3,
                    )
                )
            await s.commit()

            # --- Step 2: if both players have checked in, settle today's combined result ---
            david_checkin = await s.scalar(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == guild_id,
                    PlayoffCheckin.user_id == DAVID_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
            steph_checkin = await s.scalar(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == guild_id,
                    PlayoffCheckin.user_id == STEPH_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )

            today_result: DailyResult | None = None
            if david_checkin and steph_checkin:
                david_complete = (
                    david_checkin.pillar1 and david_checkin.pillar2 and david_checkin.pillar3
                )
                steph_complete = (
                    steph_checkin.pillar1 and steph_checkin.pillar2 and steph_checkin.pillar3
                )
                won_shared = david_complete and steph_complete

                existing_result = await s.scalar(
                    select(DailyResult).where(
                        DailyResult.guild_id == guild_id,
                        DailyResult.result_date == today,
                    )
                )
                if existing_result:
                    existing_result.david_complete = david_complete
                    existing_result.steph_complete = steph_complete
                    existing_result.won = won_shared
                    existing_result.updated_at = datetime.now(timezone.utc)
                    today_result = existing_result
                else:
                    today_result = DailyResult(
                        guild_id=guild_id,
                        result_date=today,
                        david_complete=david_complete,
                        steph_complete=steph_complete,
                        won=won_shared,
                    )
                    s.add(today_result)
                await s.commit()

            # --- Step 3: derive series tally from DailyResult rows (authoritative) ---
            daily_results = (
                await s.scalars(
                    select(DailyResult).where(
                        DailyResult.guild_id == guild_id,
                        DailyResult.result_date >= week_start,
                    )
                )
            ).all()

            wins = sum(1 for r in daily_results if r.won)
            losses = sum(1 for r in daily_results if not r.won)

            if wins >= 4:
                status = "won"
            elif losses >= 4:
                status = "lost"
            else:
                status = "ongoing"

            # --- Step 4: upsert shared series record ---
            series = await s.scalar(
                select(PlayoffSeries).where(
                    PlayoffSeries.guild_id == guild_id,
                    PlayoffSeries.week_start == week_start,
                )
            )
            if series:
                series.wins = wins
                series.losses = losses
                series.status = status
            else:
                s.add(
                    PlayoffSeries(
                        guild_id=guild_id,
                        week_start=week_start,
                        wins=wins,
                        losses=losses,
                        status=status,
                    )
                )
            await s.commit()

        # --- Build response embed ---
        individual_label = "✅ WIN" if individual_win else "❌ LOSS"
        if today_result is not None:
            color = discord.Color.green() if today_result.won else discord.Color.red()
        else:
            color = discord.Color.blurple()

        embed = discord.Embed(
            title=f"{individual_label} — {today.strftime('%A, %b %d')}",
            color=color,
        )
        embed.add_field(
            name="Your Pillars",
            value="\n".join(
                f"{'✅' if v else '❌'} {name}"
                for name, v in zip(pillar_names, [pillar1, pillar2, pillar3])
            ),
            inline=False,
        )

        # Combined result — only available once both players have checked in
        if today_result is not None:
            if today_result.won:
                combined_text = "🏆 **Shared WIN** — both complete!"
            else:
                missed = []
                if not today_result.david_complete:
                    missed.append("David")
                if not today_result.steph_complete:
                    missed.append("Stephanie")
                combined_text = f"💀 **Shared LOSS** — {', '.join(missed)} didn't complete all pillars"
        else:
            combined_text = "⏳ Waiting for other player to check in..."

        embed.add_field(name="Combined Result", value=combined_text, inline=False)
        embed.add_field(
            name=f"Series — {wins}W {losses}L",
            value=series_message(wins, losses),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="playoff_status",
        description="Check current series scores for both players",
    )
    async def playoff_status(self, interaction: discord.Interaction) -> None:
        today = today_et()
        week_start = week_start_for(today)
        guild_id = interaction.guild_id or 0

        async with self.bot.db() as s:
            series = await s.scalar(
                select(PlayoffSeries).where(
                    PlayoffSeries.guild_id == guild_id,
                    PlayoffSeries.week_start == week_start,
                )
            )
            wins = series.wins if series else 0
            losses = series.losses if series else 0

            today_result = await s.scalar(
                select(DailyResult).where(
                    DailyResult.guild_id == guild_id,
                    DailyResult.result_date == today,
                )
            )

            # Only needed for the "waiting" state when no combined result yet
            david_checkin = await s.scalar(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == guild_id,
                    PlayoffCheckin.user_id == DAVID_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
            steph_checkin = await s.scalar(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == guild_id,
                    PlayoffCheckin.user_id == STEPH_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )

        embed = discord.Embed(
            title=f"🏆 Playoff Week — {week_start.strftime('Week of %b %d')}",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name=f"Stavid Series — {wins}W {losses}L",
            value=series_message(wins, losses),
            inline=False,
        )

        # Combined day result is authoritative once both players have checked in
        if today_result is not None:
            if today_result.won:
                today_text = "🏆 **Shared WIN** — both complete!"
            else:
                missed = []
                if not today_result.david_complete:
                    missed.append("David")
                if not today_result.steph_complete:
                    missed.append("Stephanie")
                today_text = f"💀 **Shared LOSS** — {', '.join(missed)} didn't complete all pillars"
            embed.add_field(name="Today's Combined Result", value=today_text, inline=False)
        else:
            # Day not yet settled — show individual check-in status
            embed.add_field(
                name="Today's Check-ins",
                value=(
                    f"David: {'✅ checked in' if david_checkin else '⏳ not yet'}\n"
                    f"Stephanie: {'✅ checked in' if steph_checkin else '⏳ not yet'}"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="series_history",
        description="View past series results",
    )
    async def series_history(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0

        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(PlayoffSeries)
                    .where(PlayoffSeries.guild_id == guild_id)
                    .order_by(PlayoffSeries.week_start.desc())
                    .limit(8)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                "No series history yet. Use `/checkin` to get started!",
                ephemeral=True,
            )
            return

        icons = {"won": "🏆", "lost": "💀", "ongoing": "🔄"}
        lines = [
            f"{icons.get(r.status, '❓')} Week of {r.week_start.strftime('%b %d')} — "
            f"**{r.wins}–{r.losses}** ({r.status})"
            for r in rows
        ]
        won_count = sum(1 for r in rows if r.status == "won")

        embed = discord.Embed(
            title="📊 Stavid Series History",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Won {won_count} of {len(rows)} series shown")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # Background tasks                                                     #
    # ------------------------------------------------------------------ #

    @tasks.loop(hours=1)
    async def daily_ping(self) -> None:
        """At 10 pm ET, remind users who haven't checked in yet."""
        now_et = datetime.now(ET)
        today = now_et.date()

        if now_et.hour != 22 or today in self._pinged_dates:
            return
        self._pinged_dates.add(today)

        channel_id = os.getenv("CHECKIN_CHANNEL_ID")
        if not channel_id or not channel_id.isdigit():
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            return

        for user_id in (DAVID_ID, STEPH_ID):
            async with self.bot.db() as s:
                already = await s.scalar(
                    select(PlayoffCheckin).where(
                        PlayoffCheckin.user_id == user_id,
                        PlayoffCheckin.checkin_date == today,
                    )
                )
            if already:
                continue

            pillar_list = "\n".join(
                f"{i + 1}. {p}" for i, p in enumerate(get_pillar_names(user_id))
            )
            member = channel.guild.get_member(user_id)
            mention = member.mention if member else f"<@{user_id}>"
            await channel.send(
                f"⏰ {mention} — daily check-in time!\n"
                f"Your pillars:\n{pillar_list}\n\n"
                f"Use `/checkin` to log your results!"
            )

    @daily_ping.before_loop
    async def before_daily_ping(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def sunday_review(self) -> None:
        """On Sunday at 10 am ET, post a weekly review prompt."""
        now_et = datetime.now(ET)
        today = now_et.date()

        if now_et.weekday() != 6 or now_et.hour != 10 or today in self._reviewed_dates:
            return
        self._reviewed_dates.add(today)

        channel_id = os.getenv("CHECKIN_CHANNEL_ID")
        if not channel_id or not channel_id.isdigit():
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            return

        prev_week_start = week_start_for(today) - timedelta(weeks=1)

        guild_id = channel.guild.id if channel.guild else 0
        lines = ["☀️ **Sunday Weekly Review**\n"]
        async with self.bot.db() as s:
            series = await s.scalar(
                select(PlayoffSeries).where(
                    PlayoffSeries.guild_id == guild_id,
                    PlayoffSeries.week_start == prev_week_start,
                )
            )
            if series:
                result = f"**{series.wins}–{series.losses}** ({series.status})"
            else:
                result = "No data"
            lines.append(f"Last week's series: {result}")

        lines += [
            "",
            "Take a moment to reflect:",
            "• What went well this week?",
            "• What do you want to focus on next week?",
            "",
            "New series starts today — fresh slate. You've got this! 💪",
        ]
        await channel.send("\n".join(lines))

    @sunday_review.before_loop
    async def before_sunday_review(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Playoff(bot))
