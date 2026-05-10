# src/cogs/playoff.py
from __future__ import annotations

import logging
import os
import typing as t
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from src.db import PlayoffCheckin, UserPreference, WeeklyReview
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

log = logging.getLogger(__name__)

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
DEFAULT_PILLARS = ["Pillar 1", "Pillar 2", "Pillar 3"]

USER_NAMES = {DAVID_ID: "David", STEPH_ID: "Stephanie"}

WIN_THRESHOLD = 4  # individual wins needed to win the week
DEFAULT_CHECKIN_HOUR = 22  # 10pm ET when the user has no override
MIN_CHECKIN_HOUR = 0
MAX_CHECKIN_HOUR = 23


def get_default_pillars(user_id: int) -> list[str]:
    if user_id == DAVID_ID:
        return DAVID_PILLARS
    if user_id == STEPH_ID:
        return STEPH_PILLARS
    return DEFAULT_PILLARS


# Backwards-compatible alias — the old name is still used by tests and any
# external imports. Returns the hardcoded default pillars (no DB lookup).
get_pillar_names = get_default_pillars


def merge_user_pillars(pref: UserPreference | None, user_id: int) -> list[str]:
    """Apply non-NULL pillar overrides on top of the user's default pillars."""
    base = get_default_pillars(user_id)
    if pref is None:
        return base
    return [
        pref.pillar1 or base[0],
        pref.pillar2 or base[1],
        pref.pillar3 or base[2],
    ]


def merge_user_checkin_hour(pref: UserPreference | None) -> int:
    if pref is None or pref.checkin_hour is None:
        return DEFAULT_CHECKIN_HOUR
    return pref.checkin_hour


async def load_user_preference(
    session, guild_id: int, user_id: int
) -> UserPreference | None:
    return await session.scalar(
        select(UserPreference).where(
            UserPreference.guild_id == guild_id,
            UserPreference.user_id == user_id,
        )
    )


async def get_user_pillars(session, guild_id: int, user_id: int) -> list[str]:
    pref = await load_user_preference(session, guild_id, user_id)
    return merge_user_pillars(pref, user_id)


async def get_user_checkin_hour(session, guild_id: int, user_id: int) -> int:
    pref = await load_user_preference(session, guild_id, user_id)
    return merge_user_checkin_hour(pref)


def today_et() -> date:
    return datetime.now(ET).date()


def week_start_for(d: date) -> date:
    """Return the Sunday that starts the week containing d (weeks run Sun–Sat)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def is_full_day_win(c: PlayoffCheckin) -> bool:
    """A user wins their day iff they completed all 3 pillars."""
    return bool(c.pillar1 and c.pillar2 and c.pillar3)


def tally_user_week(checkins: list[PlayoffCheckin]) -> tuple[int, int]:
    """Return (wins, losses) for one user's week given their check-ins."""
    wins = sum(1 for c in checkins if is_full_day_win(c))
    losses = len(checkins) - wins
    return wins, losses


def finalize_user_status(checkins: list[PlayoffCheckin]) -> str:
    """Return 'won' if the user hit ≥ WIN_THRESHOLD individual wins, else 'lost'."""
    wins, _ = tally_user_week(checkins)
    return "won" if wins >= WIN_THRESHOLD else "lost"


def series_message(wins: int, losses: int) -> str:
    """Return motivational status text for an individual's W/L count."""
    if wins >= WIN_THRESHOLD:
        return "🏆 **Week Won!**"
    if losses >= WIN_THRESHOLD:
        return "💀 Week lost."

    wins_needed = WIN_THRESHOLD - wins
    games_left = 7 - wins - losses

    if losses >= 3 and wins < 2:
        return f"⚠️ {wins}–{losses} — need {wins_needed} straight. **Still alive!**"
    if losses > wins:
        return (
            f"📊 {wins}–{losses} — still in it. "
            f"Need {wins_needed} more "
            f"with {games_left} day{'s' if games_left != 1 else ''} left."
        )
    if wins > losses:
        return f"✅ {wins}–{losses} — keep the momentum! Need {wins_needed} more."
    if wins == 0 and losses == 0:
        return f"📅 Fresh week — need {wins_needed} wins."
    return f"⚖️ Tied {wins}–{losses}. Need {wins_needed} more."


_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _user_label(user_id: int) -> str:
    return USER_NAMES.get(user_id, f"<@{user_id}>")


def _longest_streak(seq: list[bool]) -> int:
    best = cur = 0
    for v in seq:
        if v:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def build_user_week_lines(
    checkins: list[PlayoffCheckin], week_start: date
) -> tuple[list[str], list[bool]]:
    """Return (per-day lines, win sequence) for a user's week of check-ins."""
    by_date = {c.checkin_date: c for c in checkins}
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    lines: list[str] = []
    seq: list[bool] = []
    for i, d in enumerate(week_dates):
        label = f"{_DAY_NAMES[i]} {d.strftime('%m/%d')}"
        c = by_date.get(d)
        if c is None:
            lines.append(f"`{label}` —")
            seq.append(False)
            continue
        if is_full_day_win(c):
            lines.append(f"`{label}` 🏆")
            seq.append(True)
        else:
            misses = sum(1 for v in (c.pillar1, c.pillar2, c.pillar3) if not v)
            lines.append(f"`{label}` 💔 ({misses} pillar{'s' if misses != 1 else ''} missed)")
            seq.append(False)
    return lines, seq


def build_user_weekly_embed(
    user_id: int,
    checkins: list[PlayoffCheckin],
    week_start: date,
    pillars: list[str] | None = None,
) -> discord.Embed:
    """Build a per-user weekly review embed.

    Pass ``pillars`` to override the default pillar names (e.g. when the user
    has set custom names via ``/set_pillar``).
    """
    if pillars is None:
        pillars = get_default_pillars(user_id)
    wins, losses = tally_user_week(checkins)
    status = finalize_user_status(checkins)
    week_end = week_start + timedelta(days=6)

    if status == "won":
        color = discord.Color.green()
        status_line = f"🏆 **{wins}–{losses} — WON!**"
    else:
        color = discord.Color.red()
        status_line = f"💀 **{wins}–{losses} — Lost**"

    if not checkins:
        color = discord.Color.greyple()
        status_line = "No check-ins recorded for last week."

    embed = discord.Embed(
        title=(
            f"☀️ Weekly Review — {_user_label(user_id)} — "
            f"{week_start.strftime('%b %d')}–{week_end.strftime('%b %d')}"
        ),
        description=status_line,
        color=color,
    )

    day_lines, win_seq = build_user_week_lines(checkins, week_start)
    if day_lines:
        embed.add_field(name="Day-by-Day", value="\n".join(day_lines), inline=False)

    if checkins:
        denom = len(checkins)
        p_counts = [
            sum(1 for c in checkins if c.pillar1),
            sum(1 for c in checkins if c.pillar2),
            sum(1 for c in checkins if c.pillar3),
        ]
        pillar_lines = [
            f"{'✅' if p_counts[i] == denom else '🔸'} {pillars[i][:40]}: {p_counts[i]}/{denom}"
            for i in range(3)
        ]
        embed.add_field(name="Per-Pillar", value="\n".join(pillar_lines), inline=False)

    streak = _longest_streak(win_seq)
    if streak >= 2:
        embed.add_field(name="Best Streak", value=f"🔥 {streak} days in a row!", inline=False)

    embed.set_footer(text="Use /weekly_review to share your reflection • New week starts today.")
    return embed


def format_user_weekly_summary(
    user_id: int, checkins: list[PlayoffCheckin], week_start: date
) -> str:
    """Plain-text version of the weekly review for a single user."""
    wins, losses = tally_user_week(checkins)
    lines: list[str] = [f"☀️ **Weekly Review — {_user_label(user_id)}**\n"]

    if not checkins:
        lines.append("No check-ins recorded for last week.")
    else:
        lines.append(f"**Week result: {wins}–{losses}** ({finalize_user_status(checkins)})")
        day_lines, win_seq = build_user_week_lines(checkins, week_start)
        lines.append("")
        lines.append("**Day-by-day:**")
        lines.extend(day_lines)
        streak = _longest_streak(win_seq)
        if streak >= 2:
            lines.append(f"**Best streak:** {streak} days 🔥")

    lines += [
        "",
        "Take a moment to reflect:",
        "• What went well this week?",
        "• What do you want to focus on next week?",
        "",
        "Fresh slate this week. 💪",
    ]
    return "\n".join(lines)


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
            label=pillar_names[0][:45], placeholder="y or n", max_length=3,
        )
        self.p2 = discord.ui.TextInput(
            label=pillar_names[1][:45], placeholder="y or n", max_length=3,
        )
        self.p3 = discord.ui.TextInput(
            label=pillar_names[2][:45], placeholder="y or n", max_length=3,
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
        # Per-user pinged dates so each user can have their own check-in hour
        # without re-pinging once they've already been hit today.
        self._pinged_dates: dict[int, set[date]] = {}
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
        async with self.bot.db() as s:
            pillars = await get_user_pillars(
                s, interaction.guild_id or 0, interaction.user.id
            )
        modal = CheckinModal(pillars, self._process_checkin)
        await interaction.response.send_modal(modal)

    async def _process_checkin(
        self,
        interaction: discord.Interaction,
        pillar1: bool,
        pillar2: bool,
        pillar3: bool,
    ) -> None:
        # Defer immediately so DB work has more than the 3-second interaction window.
        # Without this the modal silently fails when DB calls take >3s.
        try:
            await interaction.response.defer()
        except discord.errors.InteractionResponded:
            pass

        try:
            await self._do_checkin(interaction, pillar1, pillar2, pillar3)
        except Exception:
            log.exception("checkin failed for user %s", interaction.user.id)
            try:
                await interaction.followup.send(
                    "⚠️ Something went wrong saving your check-in. Try again in a moment.",
                    ephemeral=True,
                )
            except Exception:
                pass

    async def _do_checkin(
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
        won_today = pillar1 and pillar2 and pillar3

        async with self.bot.db() as s:
            pillar_names = await get_user_pillars(s, guild_id, user_id)
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

            my_checkins = list(
                (
                    await s.scalars(
                        select(PlayoffCheckin).where(
                            PlayoffCheckin.guild_id == guild_id,
                            PlayoffCheckin.user_id == user_id,
                            PlayoffCheckin.checkin_date >= week_start,
                            PlayoffCheckin.checkin_date <= week_start + timedelta(days=6),
                        )
                    )
                ).all()
            )

        wins, losses = tally_user_week(my_checkins)

        if won_today:
            headline = "🏆 Day Win"
            color = discord.Color.green()
        else:
            headline = "💔 Day Loss"
            color = discord.Color.red()

        embed = discord.Embed(
            title=f"{headline} — {today.strftime('%A, %b %d')}",
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
        embed.add_field(
            name=f"Your Week — {wins}W {losses}L",
            value=series_message(wins, losses),
            inline=False,
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="playoff_status",
        description="Check both players' individual weekly scoreboards",
    )
    async def playoff_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        today = today_et()
        week_start = week_start_for(today)
        guild_id = interaction.guild_id or 0
        week_end = week_start + timedelta(days=6)

        async with self.bot.db() as s:
            rows = list(
                (
                    await s.scalars(
                        select(PlayoffCheckin).where(
                            PlayoffCheckin.guild_id == guild_id,
                            PlayoffCheckin.checkin_date >= week_start,
                            PlayoffCheckin.checkin_date <= week_end,
                        )
                    )
                ).all()
            )

        by_user: dict[int, list[PlayoffCheckin]] = {}
        for r in rows:
            by_user.setdefault(r.user_id, []).append(r)

        embed = discord.Embed(
            title=f"🏆 Playoff Week — {week_start.strftime('Week of %b %d')}",
            color=discord.Color.blurple(),
        )

        # Always show David and Stephanie (and any other partners with rows)
        ordered_user_ids: list[int] = [DAVID_ID, STEPH_ID]
        for uid in by_user.keys():
            if uid not in ordered_user_ids:
                ordered_user_ids.append(uid)

        for uid in ordered_user_ids:
            user_rows = by_user.get(uid, [])
            wins, losses = tally_user_week(user_rows)
            today_row = next((c for c in user_rows if c.checkin_date == today), None)
            if today_row is None:
                today_line = "⏳ Hasn't checked in today"
            elif is_full_day_win(today_row):
                today_line = "✅ Today: complete"
            else:
                missed = sum(
                    1 for v in (today_row.pillar1, today_row.pillar2, today_row.pillar3) if not v
                )
                today_line = f"❌ Today: {missed} pillar{'s' if missed != 1 else ''} missed"
            embed.add_field(
                name=f"{_user_label(uid)} — {wins}W {losses}L",
                value=f"{series_message(wins, losses)}\n{today_line}",
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="series_history",
        description="View per-person weekly history (last 8 weeks)",
    )
    async def series_history(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id or 0
        today = today_et()
        oldest = week_start_for(today) - timedelta(weeks=7)

        async with self.bot.db() as s:
            rows = list(
                (
                    await s.scalars(
                        select(PlayoffCheckin).where(
                            PlayoffCheckin.guild_id == guild_id,
                            PlayoffCheckin.checkin_date >= oldest,
                        )
                    )
                ).all()
            )

        if not rows:
            await interaction.followup.send(
                "No check-ins yet. Use `/checkin` to get started!", ephemeral=True
            )
            return

        # Group: user -> week_start -> [checkins]
        by_user_week: dict[int, dict[date, list[PlayoffCheckin]]] = {}
        for r in rows:
            ws = week_start_for(r.checkin_date)
            by_user_week.setdefault(r.user_id, {}).setdefault(ws, []).append(r)

        ordered_user_ids: list[int] = [DAVID_ID, STEPH_ID]
        for uid in by_user_week.keys():
            if uid not in ordered_user_ids:
                ordered_user_ids.append(uid)

        embed = discord.Embed(
            title="📊 Weekly History (per person)",
            color=discord.Color.blurple(),
        )
        for uid in ordered_user_ids:
            weeks = by_user_week.get(uid, {})
            if not weeks:
                embed.add_field(name=_user_label(uid), value="No check-ins yet.", inline=False)
                continue
            ordered_weeks = sorted(weeks.keys(), reverse=True)[:8]
            lines = []
            won_count = 0
            for ws in ordered_weeks:
                w_checkins = weeks[ws]
                wins, losses = tally_user_week(w_checkins)
                status = finalize_user_status(w_checkins)
                icon = "🏆" if status == "won" else "💀"
                if status == "won":
                    won_count += 1
                lines.append(
                    f"{icon} Week of {ws.strftime('%b %d')} — **{wins}–{losses}** ({status})"
                )
            lines.append(f"_Won {won_count} of {len(ordered_weeks)} weeks shown_")
            embed.add_field(name=_user_label(uid), value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

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
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.InteractionResponded:
            pass

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

        await interaction.followup.send(
            f"✅ Reflection saved for the week of {week_of.strftime('%b %d')}!",
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # Preferences                                                          #
    # ------------------------------------------------------------------ #

    async def _upsert_preference(
        self,
        guild_id: int,
        user_id: int,
        *,
        pillar_idx: int | None = None,
        pillar_value: str | None = None,
        checkin_hour: int | None = None,
    ) -> None:
        """Upsert a UserPreference row, applying the given override.

        ``pillar_idx`` is 1-based (1, 2, or 3). Pass ``pillar_value=""`` to clear
        the override and revert to the default. ``checkin_hour=-1`` clears the
        hour override.
        """
        async with self.bot.db() as s:
            pref = await load_user_preference(s, guild_id, user_id)
            if pref is None:
                pref = UserPreference(guild_id=guild_id, user_id=user_id)
                s.add(pref)

            if pillar_idx is not None:
                value = pillar_value if pillar_value else None
                if pillar_idx == 1:
                    pref.pillar1 = value
                elif pillar_idx == 2:
                    pref.pillar2 = value
                elif pillar_idx == 3:
                    pref.pillar3 = value
            if checkin_hour is not None:
                pref.checkin_hour = None if checkin_hour < 0 else checkin_hour

            pref.updated_at = datetime.now(timezone.utc)
            await s.commit()

    @app_commands.command(
        name="set_pillar",
        description="Set one of your check-in pillars (clear by passing empty name)",
    )
    @app_commands.describe(
        number="Which pillar to set (1, 2, or 3)",
        name="New pillar text — leave empty to revert to your default",
    )
    async def set_pillar(
        self,
        interaction: discord.Interaction,
        number: app_commands.Range[int, 1, 3],
        name: str = "",
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._upsert_preference(
            interaction.guild_id or 0,
            interaction.user.id,
            pillar_idx=int(number),
            pillar_value=name.strip(),
        )
        if name.strip():
            msg = f"✅ Pillar {number} set to **{name.strip()}**."
        else:
            msg = f"✅ Pillar {number} reverted to your default."
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(
        name="set_checkin_time",
        description="Set the hour (0–23 ET) when the bot pings you for daily check-in",
    )
    @app_commands.describe(
        hour="Hour in America/New_York (0–23). Pass -1 to revert to the default (10pm).",
    )
    async def set_checkin_time(
        self,
        interaction: discord.Interaction,
        hour: app_commands.Range[int, -1, 23],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._upsert_preference(
            interaction.guild_id or 0,
            interaction.user.id,
            checkin_hour=int(hour),
        )
        # Clear any cached "already pinged today" entry for this user so a
        # newly-set earlier hour can fire today if it hasn't yet.
        self._pinged_dates.pop(interaction.user.id, None)
        if hour < 0:
            msg = f"✅ Check-in hour reverted to default ({DEFAULT_CHECKIN_HOUR}:00 ET)."
        else:
            msg = f"✅ Check-in hour set to {int(hour):02d}:00 ET."
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(
        name="my_preferences",
        description="Show your custom pillars and check-in hour",
    )
    async def my_preferences(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db() as s:
            pref = await load_user_preference(
                s, interaction.guild_id or 0, interaction.user.id
            )
        pillars = merge_user_pillars(pref, interaction.user.id)
        hour = merge_user_checkin_hour(pref)
        defaults = get_default_pillars(interaction.user.id)

        lines = [f"**Check-in time:** {hour:02d}:00 ET"]
        if pref is None or pref.checkin_hour is None:
            lines[0] += " _(default)_"
        for i, (custom, default) in enumerate(zip(pillars, defaults), start=1):
            tag = "" if custom == default else " _(custom)_"
            lines.append(f"**Pillar {i}:** {custom}{tag}")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------ #
    # Background tasks                                                     #
    # ------------------------------------------------------------------ #

    @tasks.loop(hours=1)
    async def daily_ping(self) -> None:
        """Each hour, remind any user whose configured check-in hour matches now."""
        now_et = datetime.now(ET)
        today = now_et.date()

        channel_id = os.getenv("CHECKIN_CHANNEL_ID")
        if not channel_id or not channel_id.isdigit():
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            return
        guild_id = channel.guild.id if channel.guild else 0

        for user_id in (DAVID_ID, STEPH_ID):
            already_pinged = today in self._pinged_dates.get(user_id, set())
            if already_pinged:
                continue

            async with self.bot.db() as s:
                pref = await load_user_preference(s, guild_id, user_id)
                hour = merge_user_checkin_hour(pref)
                if now_et.hour != hour:
                    continue
                pillars = merge_user_pillars(pref, user_id)
                already = await s.scalar(
                    select(PlayoffCheckin).where(
                        PlayoffCheckin.user_id == user_id,
                        PlayoffCheckin.checkin_date == today,
                    )
                )

            self._pinged_dates.setdefault(user_id, set()).add(today)

            if already:
                continue

            pillar_list = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(pillars))
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
        """On Sunday at 10 am ET, post a per-user weekly review embed for each player."""
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
                    await s.scalars(
                        select(PlayoffCheckin).where(
                            PlayoffCheckin.guild_id == guild_id,
                            PlayoffCheckin.checkin_date >= prev_week_start,
                            PlayoffCheckin.checkin_date
                            <= prev_week_start + timedelta(days=6),
                        )
                    )
                ).all()
            )
            user_pillars: dict[int, list[str]] = {}
            for uid in (DAVID_ID, STEPH_ID):
                user_pillars[uid] = await get_user_pillars(s, guild_id, uid)

        by_user: dict[int, list[PlayoffCheckin]] = {}
        for r in rows:
            by_user.setdefault(r.user_id, []).append(r)

        for uid in (DAVID_ID, STEPH_ID):
            embed = build_user_weekly_embed(
                uid, by_user.get(uid, []), prev_week_start, pillars=user_pillars.get(uid)
            )
            await channel.send(embed=embed)

    @sunday_review.before_loop
    async def before_sunday_review(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Playoff(bot))
