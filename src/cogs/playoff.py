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


def finalize_series_status(daily_results: list[DailyResult]) -> str:
    """Determine the final "won" or "lost" status for a completed week.

    Called at week end (Sunday review) to lock in the result.  A series
    is won only if 4 or more combined wins were recorded; anything less is
    a loss — the week is over and there are no more days to play.
    """
    wins = sum(1 for r in daily_results if r.won)
    return "won" if wins >= 4 else "lost"


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


_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def format_weekly_summary(daily_results: list[DailyResult], week_start: date) -> str:
    """Build a detailed weekly summary string from DailyResult rows.

    Args:
        daily_results: All DailyResult rows for the given week (any order).
        week_start: The Sunday that starts the week.
    """
    by_date = {r.result_date: r for r in daily_results}
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    david_days = sum(1 for r in daily_results if r.david_complete)
    steph_days = sum(1 for r in daily_results if r.steph_complete)
    combined_wins = sum(1 for r in daily_results if r.won)
    total_played = len(daily_results)

    # Build per-day lines and win sequence for streak calculation
    day_lines: list[str] = []
    win_sequence: list[bool] = []
    for i, d in enumerate(week_dates):
        label = f"{_DAY_NAMES[i]} {d.strftime('%m/%d')}"
        if d in by_date:
            r = by_date[d]
            d_icon = "✅" if r.david_complete else "❌"
            s_icon = "✅" if r.steph_complete else "❌"
            result_label = "🏆 Win" if r.won else "💔 Loss"
            day_lines.append(f"`{label}`  D:{d_icon} S:{s_icon} → {result_label}")
            win_sequence.append(r.won)
        else:
            day_lines.append(f"`{label}`  —")
            win_sequence.append(False)

    # Longest consecutive-win streak within the week
    max_streak = cur_streak = 0
    for w in win_sequence:
        if w:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0

    lines: list[str] = ["☀️ **Sunday Weekly Review**\n"]

    if total_played == 0:
        lines.append("No check-ins recorded for last week.")
    else:
        lines.append(f"**Series result: {combined_wins}–{total_played - combined_wins}**")
        lines.append("")
        lines.append("**Day-by-day breakdown:**")
        lines.extend(day_lines)
        lines.append("")
        lines.append(f"**David:** {david_days}/7 days complete")
        lines.append(f"**Steph:** {steph_days}/7 days complete")
        lines.append(f"**Combined wins:** {combined_wins}/7 days")
        if max_streak >= 2:
            lines.append(f"**Best streak this week:** {max_streak} days in a row 🔥")

    lines += [
        "",
        "Take a moment to reflect:",
        "• What went well this week?",
        "• What do you want to focus on next week?",
        "",
        "New series starts today — fresh slate. You've got this! 💪",
    ]
    return "\n".join(lines)


def build_weekly_embed(
    daily_results: list[DailyResult],
    week_start: date,
    checkin_rows: list[PlayoffCheckin] | None = None,
) -> discord.Embed:
    """Build a rich Discord embed for the Sunday weekly review.

    Args:
        daily_results: All DailyResult rows for the week (any order).
        week_start: The Sunday that starts the week.
        checkin_rows: Optional PlayoffCheckin rows for the week — used to
            compute per-pillar completion rates per person.
    """
    by_date = {r.result_date: r for r in daily_results}
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    david_days = sum(1 for r in daily_results if r.david_complete)
    steph_days = sum(1 for r in daily_results if r.steph_complete)
    combined_wins = sum(1 for r in daily_results if r.won)
    total_played = len(daily_results)

    # Series status colour
    final_status = finalize_series_status(daily_results) if daily_results else "lost"
    if final_status == "won":
        color = discord.Color.green()
        status_line = f"🏆 **{combined_wins}–{total_played - combined_wins} — WON!**"
    elif final_status == "lost":
        color = discord.Color.red()
        status_line = f"💀 **{combined_wins}–{total_played - combined_wins} — Lost**"
    else:
        color = discord.Color.blurple()
        status_line = f"🔄 **{combined_wins}–{total_played - combined_wins} — Ongoing**"

    week_end = week_start + timedelta(days=6)
    embed = discord.Embed(
        title=f"☀️ Sunday Weekly Review — {week_start.strftime('%b %d')}–{week_end.strftime('%b %d')}",
        color=color,
    )

    if total_played == 0:
        embed.description = "No check-ins recorded for last week."
    else:
        embed.description = status_line

    # Day-by-day breakdown
    day_lines: list[str] = []
    win_sequence: list[bool] = []
    for i, d in enumerate(week_dates):
        label = f"{_DAY_NAMES[i]} {d.strftime('%m/%d')}"
        if d in by_date:
            r = by_date[d]
            d_icon = "✅" if r.david_complete else "❌"
            s_icon = "✅" if r.steph_complete else "❌"
            result_label = "🏆" if r.won else "💔"
            day_lines.append(f"`{label}` D:{d_icon} S:{s_icon} {result_label}")
            win_sequence.append(r.won)
        else:
            day_lines.append(f"`{label}` —")
            win_sequence.append(False)

    if day_lines:
        embed.add_field(name="Day-by-Day", value="\n".join(day_lines), inline=False)

    # Best streak
    max_streak = cur_streak = 0
    for w in win_sequence:
        if w:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0

    # Per-person summaries (with optional per-pillar breakdown)
    checkins = checkin_rows or []
    david_checkins = [r for r in checkins if r.user_id == DAVID_ID]
    steph_checkins = [r for r in checkins if r.user_id == STEPH_ID]

    def _pillar_lines(user_checkins: list[PlayoffCheckin], pillars: list[str]) -> str:
        total = len(user_checkins)
        denom = total if total else 7
        p_counts = [
            sum(1 for r in user_checkins if getattr(r, f"pillar{j + 1}"))
            for j in range(3)
        ]
        lines = [f"{'✅' if p_counts[j] == denom else '🔸'} {pillars[j][:40]}: {p_counts[j]}/{denom}" for j in range(3)]
        return "\n".join(lines)

    david_header = f"**David — {david_days}/7 days complete**"
    if david_checkins:
        david_body = _pillar_lines(david_checkins, DAVID_PILLARS)
        embed.add_field(name=david_header, value=david_body, inline=True)
    else:
        embed.add_field(name=david_header, value=f"Days complete: {david_days}/7", inline=True)

    steph_header = f"**Steph — {steph_days}/7 days complete**"
    if steph_checkins:
        steph_body = _pillar_lines(steph_checkins, STEPH_PILLARS)
        embed.add_field(name=steph_header, value=steph_body, inline=True)
    else:
        embed.add_field(name=steph_header, value=f"Days complete: {steph_days}/7", inline=True)

    if max_streak >= 2:
        embed.add_field(
            name="Best Streak",
            value=f"🔥 {max_streak} days in a row!",
            inline=False,
        )

    embed.set_footer(text="Use /weekly_review to share your reflection • New series starts today — fresh slate! 💪")
    return embed


class WeeklyReviewModal(discord.ui.Modal, title="Weekly Review"):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback
        self.reflection = discord.ui.TextInput(
            label="Reflection & next week focus",
            placeholder="What went well? What to focus on next week?",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        self.add_item(self.reflection)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction, self.reflection.value)


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
                        DailyResult.result_date <= week_start + timedelta(days=6),
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
        today = today_et()

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

            # Fetch per-person completion data for all shown weeks in one query
            oldest_week = rows[-1].week_start
            newest_week_end = rows[0].week_start + timedelta(days=6)
            daily_rows = (
                await s.scalars(
                    select(DailyResult).where(
                        DailyResult.guild_id == guild_id,
                        DailyResult.result_date >= oldest_week,
                        DailyResult.result_date <= newest_week_end,
                    )
                )
            ).all()

            # Group DailyResult rows by the Sunday that started their week
            daily_by_week: dict[date, list[DailyResult]] = {}
            for dr in daily_rows:
                ws = week_start_for(dr.result_date)
                daily_by_week.setdefault(ws, []).append(dr)

            # Auto-heal stale "ongoing" status for fully completed past weeks.
            # If the bot missed a Sunday review, old weeks stay "ongoing" forever
            # unless we fix them here.
            needs_commit = False
            for row in rows:
                week_end = row.week_start + timedelta(days=6)
                if week_end < today and row.status == "ongoing":
                    week_daily = daily_by_week.get(row.week_start, [])
                    row.wins = sum(1 for dr in week_daily if dr.won)
                    row.losses = sum(1 for dr in week_daily if not dr.won)
                    row.status = finalize_series_status(week_daily)
                    needs_commit = True
            if needs_commit:
                await s.commit()

        icons = {"won": "🏆", "lost": "💀", "ongoing": "🔄"}
        lines = []
        for r in rows:
            icon = icons.get(r.status, "❓")
            week_daily = daily_by_week.get(r.week_start, [])
            david_days = sum(1 for dr in week_daily if dr.david_complete)
            steph_days = sum(1 for dr in week_daily if dr.steph_complete)
            lines.append(
                f"{icon} Week of {r.week_start.strftime('%b %d')} — "
                f"**{r.wins}–{r.losses}** ({r.status})"
                f"  D:{david_days}/7 S:{steph_days}/7"
            )

        won_count = sum(1 for r in rows if r.status == "won")
        embed = discord.Embed(
            title="📊 Stavid Series History",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Won {won_count} of {len(rows)} series shown")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="weekly_review",
        description="Record your weekly reflection and goals",
    )
    async def weekly_review_cmd(self, interaction: discord.Interaction) -> None:
        modal = WeeklyReviewModal(self._save_weekly_review)
        await interaction.response.send_modal(modal)

    async def _save_weekly_review(
        self, interaction: discord.Interaction, text: str
    ) -> None:
        week_of = week_start_for(today_et())
        guild_id = interaction.guild_id or 0
        user_id = interaction.user.id

        async with self.bot.db() as s:
            existing = await s.scalar(
                select(WeeklyReview).where(
                    WeeklyReview.guild_id == guild_id,
                    WeeklyReview.user_id == user_id,
                    WeeklyReview.week_of == week_of,
                )
            )
            if existing:
                existing.review_text = text
            else:
                s.add(
                    WeeklyReview(
                        guild_id=guild_id,
                        user_id=user_id,
                        week_of=week_of,
                        review_text=text,
                    )
                )
            await s.commit()

        await interaction.response.send_message(
            f"✅ Reflection saved for the week of {week_of.strftime('%b %d')}!",
            ephemeral=True,
        )

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

        async with self.bot.db() as s:
            rows = list(
                (
                    await s.execute(
                        select(DailyResult).where(
                            DailyResult.guild_id == guild_id,
                            DailyResult.result_date >= prev_week_start,
                            DailyResult.result_date
                            <= prev_week_start + timedelta(days=6),
                        )
                    )
                )
                .scalars()
                .all()
            )

            # Finalize the previous week's series record so history is accurate
            # even for weeks that didn't hit 4 wins/losses before the week ended.
            if rows:
                wins_final = sum(1 for r in rows if r.won)
                losses_final = sum(1 for r in rows if not r.won)
                final_status = finalize_series_status(rows)

                prev_series = await s.scalar(
                    select(PlayoffSeries).where(
                        PlayoffSeries.guild_id == guild_id,
                        PlayoffSeries.week_start == prev_week_start,
                    )
                )
                if prev_series:
                    prev_series.wins = wins_final
                    prev_series.losses = losses_final
                    prev_series.status = final_status
                else:
                    s.add(
                        PlayoffSeries(
                            guild_id=guild_id,
                            week_start=prev_week_start,
                            wins=wins_final,
                            losses=losses_final,
                            status=final_status,
                        )
                    )
                await s.commit()

            # Fetch per-person checkin rows for the detailed pillar breakdown
            checkin_rows = list(
                (
                    await s.execute(
                        select(PlayoffCheckin).where(
                            PlayoffCheckin.guild_id == guild_id,
                            PlayoffCheckin.checkin_date >= prev_week_start,
                            PlayoffCheckin.checkin_date
                            <= prev_week_start + timedelta(days=6),
                        )
                    )
                )
                .scalars()
                .all()
            )

        embed = build_weekly_embed(rows, prev_week_start, checkin_rows)
        await channel.send(embed=embed)

    @sunday_review.before_loop
    async def before_sunday_review(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Playoff(bot))
