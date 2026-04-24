"""Date night tracker — planner rotation, wishlist, log, and special-date countdowns."""
from __future__ import annotations

import datetime as _dt
import typing as t
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from src.db import DateNightLog, DateNightPlanner, DateNightWishlist, SpecialDate
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

# Map each partner to the other so we can resolve "whose turn next"
_PARTNER: dict[int, int] = {DAVID_ID: STEPH_ID, STEPH_ID: DAVID_ID}

_STARS = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_until(month: int, day: int, today: _dt.date) -> tuple[int, _dt.date]:
    """Return (days_remaining, next_occurrence_date) for a recurring annual date."""
    try:
        candidate = today.replace(month=month, day=day)
    except ValueError:
        # Feb 29 on a non-leap year — use Feb 28
        candidate = today.replace(month=month, day=28)

    if candidate >= today:
        return (candidate - today).days, candidate

    try:
        next_occ = candidate.replace(year=candidate.year + 1)
    except ValueError:
        next_occ = _dt.date(candidate.year + 1, month, 28)

    return (next_occ - today).days, next_occ


async def _get_or_create_planner(s, guild_id: int) -> DateNightPlanner:
    row = await s.scalar(
        select(DateNightPlanner).where(DateNightPlanner.guild_id == guild_id)
    )
    if row is None:
        row = DateNightPlanner(
            guild_id=guild_id,
            last_planner_id=None,
            updated_at=datetime.now(timezone.utc),
        )
        s.add(row)
        await s.flush()
    return row


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class DateNight(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    # -----------------------------------------------------------------------
    # /datenight group — core commands
    # -----------------------------------------------------------------------
    datenight = app_commands.Group(name="datenight", description="Date night tracker")

    @datenight.command(name="status", description="Who plans next + upcoming special dates")
    async def dn_status(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        today = _dt.date.today()

        async with self.bot.db() as s:
            planner = await _get_or_create_planner(s, guild_id)
            await s.commit()
            specials = (
                await s.scalars(
                    select(SpecialDate)
                    .where(SpecialDate.guild_id == guild_id)
                    .order_by(SpecialDate.month, SpecialDate.day)
                )
            ).all()

        if planner.last_planner_id is None:
            turn_text = "No date nights logged yet — either of you can plan the first one!"
        else:
            next_id = _PARTNER.get(planner.last_planner_id, planner.last_planner_id)
            turn_text = f"<@{next_id}>'s turn to plan! 🎉"

        embed = discord.Embed(title="💑 Date Night Status", color=discord.Color.from_str("#ff69b4"))
        embed.add_field(name="Next Planner", value=turn_text, inline=False)

        upcoming = []
        for sd in specials:
            days, _ = _days_until(sd.month, sd.day, today)
            if days <= 90:
                upcoming.append((days, sd))
        upcoming.sort(key=lambda x: x[0])

        if upcoming:
            lines = []
            for days, sd in upcoming[:5]:
                when = "today! 🎉" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
                lines.append(f"**{sd.label}** — {when}")
            embed.add_field(name="📅 Coming up (next 90 days)", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @datenight.command(name="log", description="Log a date night — you're the planner, swaps the turn")
    @app_commands.describe(
        date="Date of the date night (YYYY-MM-DD)",
        place="Where you went or what you did",
        notes="Any notes or memories",
        rating="Rating 1–5",
        wishlist_item="Wishlist item you crossed off (use autocomplete)",
    )
    async def dn_log(
        self,
        interaction: discord.Interaction,
        date: str,
        place: str = "",
        notes: str = "",
        rating: app_commands.Range[int, 1, 5] | None = None,
        wishlist_item: str = "",
    ) -> None:
        try:
            night_date = _dt.date.fromisoformat(date)
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid date — use YYYY-MM-DD (e.g. `2026-04-20`).", ephemeral=True
            )
            return

        guild_id = interaction.guild_id or 0
        planner_id = interaction.user.id

        wishlist_id: int | None = None
        if wishlist_item:
            try:
                wishlist_id = int(wishlist_item)
            except ValueError:
                pass

        async with self.bot.db() as s:
            planner = await _get_or_create_planner(s, guild_id)
            planner.last_planner_id = planner_id
            planner.updated_at = datetime.now(timezone.utc)

            wish_name: str | None = None
            if wishlist_id is not None:
                wrow = await s.get(DateNightWishlist, wishlist_id)
                if wrow and not wrow.visited and wrow.guild_id == guild_id:
                    wrow.visited = True
                    wrow.visited_at = night_date
                    wish_name = wrow.name

            entry = DateNightLog(
                guild_id=guild_id,
                planned_by=planner_id,
                date=night_date,
                place=place,
                notes=notes,
                rating=rating,
                wishlist_item_id=wishlist_id,
            )
            s.add(entry)
            await s.commit()

        next_id = _PARTNER.get(planner_id, planner_id)
        parts = [f"💑 Date night logged for **{night_date}**!"]
        if place:
            parts.append(f"**Where:** {place}")
        if rating is not None:
            parts.append(f"**Rating:** {_STARS[rating]}")
        if wish_name:
            parts.append(f"**Wishlist:** ✅ Crossed off _{wish_name}_!")
        if notes:
            parts.append(f"**Notes:** {notes}")
        parts.append(f"\n<@{next_id}> — you're planning the next one! 🎉")
        await interaction.response.send_message("\n".join(parts))

    @dn_log.autocomplete("wishlist_item")
    async def _log_wishlist_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(DateNightWishlist)
                    .where(
                        DateNightWishlist.guild_id == interaction.guild_id,
                        DateNightWishlist.visited == False,  # noqa: E712
                    )
                    .order_by(DateNightWishlist.name)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(name=r.name, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.name.lower()
        ]

    @datenight.command(name="swap", description="Manually swap whose turn it is to plan")
    async def dn_swap(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            planner = await _get_or_create_planner(s, guild_id)
            if planner.last_planner_id is None:
                # Bootstrap: treat the caller as having just planned, so partner is next
                planner.last_planner_id = interaction.user.id
            else:
                planner.last_planner_id = _PARTNER.get(
                    planner.last_planner_id, planner.last_planner_id
                )
            planner.updated_at = datetime.now(timezone.utc)
            await s.commit()

        next_id = _PARTNER.get(planner.last_planner_id, planner.last_planner_id)
        await interaction.response.send_message(
            f"🔄 Swapped! It's now <@{next_id}>'s turn to plan the next date night."
        )

    @datenight.command(name="history", description="Show the last 10 date nights")
    async def dn_history(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(DateNightLog)
                    .where(DateNightLog.guild_id == guild_id)
                    .order_by(DateNightLog.date.desc())
                    .limit(10)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                "No date nights logged yet. Use `/datenight log` to add your first one!"
            )
            return

        embed = discord.Embed(title="💑 Date Night History", color=discord.Color.from_str("#ff69b4"))
        for entry in rows:
            title = str(entry.date)
            if entry.place:
                title += f" — {entry.place}"
            value_parts = [f"Planned by <@{entry.planned_by}>"]
            if entry.rating:
                value_parts.append(_STARS[entry.rating])
            if entry.notes:
                value_parts.append(f"_{entry.notes}_")
            embed.add_field(name=title, value="\n".join(value_parts), inline=False)

        await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------------------------
    # /wish group — wishlist
    # -----------------------------------------------------------------------
    wish = app_commands.Group(name="wish", description="Date night wishlist")

    @wish.command(name="add", description="Add a place or activity to the date night wishlist")
    @app_commands.describe(name="Where do you want to go or what do you want to do?")
    async def wish_add(self, interaction: discord.Interaction, name: str) -> None:
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            item = DateNightWishlist(guild_id=guild_id, name=name, added_by=interaction.user.id)
            s.add(item)
            await s.commit()
        await interaction.response.send_message(f"✨ **{name}** added to the wishlist!")

    @wish.command(name="list", description="Show the date night wishlist")
    async def wish_list(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(DateNightWishlist)
                    .where(DateNightWishlist.guild_id == guild_id)
                    .order_by(DateNightWishlist.visited, DateNightWishlist.created_at)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                "Wishlist is empty! Add ideas with `/wish add`."
            )
            return

        embed = discord.Embed(title="✨ Date Night Wishlist", color=discord.Color.purple())

        unvisited = [r for r in rows if not r.visited]
        visited = [r for r in rows if r.visited]

        if unvisited:
            lines = []
            for item in unvisited[:20]:
                line = f"• **{item.name}**"
                if item.notes:
                    line += f" — _{item.notes}_"
                lines.append(line)
            if len(unvisited) > 20:
                lines.append(f"_…and {len(unvisited) - 20} more_")
            embed.add_field(name=f"To Try ({len(unvisited)})", value="\n".join(lines), inline=False)

        if visited:
            lines = []
            for item in visited[:10]:
                line = f"~~{item.name}~~"
                if item.visited_at:
                    line += f" ✅ {item.visited_at}"
                if item.notes:
                    line += f" — _{item.notes}_"
                lines.append(line)
            if len(visited) > 10:
                lines.append(f"_…and {len(visited) - 10} more_")
            embed.add_field(name=f"Done ({len(visited)})", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @wish.command(name="visit", description="Mark a wishlist item as visited")
    @app_commands.describe(item="Item to mark as visited", notes="Notes or memories from the visit")
    async def wish_visit(self, interaction: discord.Interaction, item: str, notes: str = "") -> None:
        try:
            item_id = int(item)
        except ValueError:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return

        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            row = await s.get(DateNightWishlist, item_id)
            if row is None or row.guild_id != guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            if row.visited:
                await interaction.response.send_message(
                    f"**{row.name}** was already marked as visited.", ephemeral=True
                )
                return
            name = row.name
            row.visited = True
            row.visited_at = _dt.date.today()
            if notes:
                row.notes = notes
            await s.commit()

        await interaction.response.send_message(f"✅ Marked **{name}** as visited!")

    @wish_visit.autocomplete("item")
    async def _wish_visit_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(DateNightWishlist)
                    .where(
                        DateNightWishlist.guild_id == interaction.guild_id,
                        DateNightWishlist.visited == False,  # noqa: E712
                    )
                    .order_by(DateNightWishlist.name)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(name=r.name, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.name.lower()
        ]

    @wish.command(name="remove", description="Remove a wishlist item")
    @app_commands.describe(item="Item to remove")
    async def wish_remove(self, interaction: discord.Interaction, item: str) -> None:
        try:
            item_id = int(item)
        except ValueError:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return

        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            row = await s.get(DateNightWishlist, item_id)
            if row is None or row.guild_id != guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            name = row.name
            await s.delete(row)
            await s.commit()

        await interaction.response.send_message(f"🗑️ Removed **{name}** from the wishlist.")

    @wish_remove.autocomplete("item")
    async def _wish_remove_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(DateNightWishlist)
                    .where(DateNightWishlist.guild_id == interaction.guild_id)
                    .order_by(DateNightWishlist.name)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(name=r.name, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.name.lower()
        ]

    # -----------------------------------------------------------------------
    # /special group — anniversaries, birthdays, gift brainstorm
    # -----------------------------------------------------------------------
    special = app_commands.Group(name="special", description="Anniversaries, birthdays, and gift ideas")

    @special.command(name="add", description="Add an anniversary, birthday, or other special date")
    @app_commands.describe(
        label="Name for the date (e.g. 'Anniversary', \"David's Birthday\")",
        month="Month (1–12)",
        day="Day of the month (1–31)",
        year="Optional year (e.g. birth year for age tracking)",
    )
    async def special_add(
        self,
        interaction: discord.Interaction,
        label: str,
        month: app_commands.Range[int, 1, 12],
        day: app_commands.Range[int, 1, 31],
        year: int | None = None,
    ) -> None:
        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            sd = SpecialDate(guild_id=guild_id, label=label, month=month, day=day, year=year)
            s.add(sd)
            await s.commit()

        try:
            month_name = _dt.date(2000, month, day).strftime("%B %-d")
        except ValueError:
            month_name = f"{month}/{day}"
        year_str = f" {year}" if year else ""
        await interaction.response.send_message(
            f"📅 Added **{label}** on **{month_name}{year_str}**!"
        )

    @special.command(name="gift", description="Add a gift idea to a special date")
    @app_commands.describe(label="Which special date (use autocomplete)", idea="Gift idea to add")
    async def special_gift(
        self, interaction: discord.Interaction, label: str, idea: str
    ) -> None:
        try:
            sd_id = int(label)
        except ValueError:
            await interaction.response.send_message("❌ Special date not found.", ephemeral=True)
            return

        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            row = await s.get(SpecialDate, sd_id)
            if row is None or row.guild_id != guild_id:
                await interaction.response.send_message("❌ Special date not found.", ephemeral=True)
                return
            name = row.label
            row.gift_ideas = (row.gift_ideas + f"\n• {idea}").lstrip()
            await s.commit()

        await interaction.response.send_message(f"🎁 Added gift idea for **{name}**: _{idea}_")

    @special_gift.autocomplete("label")
    async def _special_gift_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(SpecialDate)
                    .where(SpecialDate.guild_id == interaction.guild_id)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(name=r.label, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.label.lower()
        ]

    @special.command(name="list", description="Show all special dates with countdowns and gift ideas")
    async def special_list(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id or 0
        today = _dt.date.today()
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(SpecialDate).where(SpecialDate.guild_id == guild_id)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                "No special dates yet! Use `/special add` to add one."
            )
            return

        dated = [((_days_until(r.month, r.day, today)), r) for r in rows]
        dated.sort(key=lambda x: x[0][0])

        embed = discord.Embed(title="🎂 Special Dates", color=discord.Color.gold())
        for (days, next_date), sd in dated:
            when = "today! 🎉" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            field_name = f"{sd.label} — {when}"
            try:
                date_str = _dt.date(2000, sd.month, sd.day).strftime("%B %-d")
            except ValueError:
                date_str = f"{sd.month}/{sd.day}"
            if sd.year:
                years = next_date.year - sd.year
                date_str += f" ({years} year{'s' if years != 1 else ''})"
            value_parts = [date_str]
            if sd.gift_ideas:
                value_parts.append(f"\n**Gift ideas:**\n{sd.gift_ideas}")
            embed.add_field(name=field_name, value="\n".join(value_parts), inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DateNight(bot))
