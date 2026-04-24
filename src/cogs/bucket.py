from __future__ import annotations

import typing as t
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from src.db import BucketListItem
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

CATEGORIES = ["travel", "experience", "food", "adventure", "creative", "learning", "other"]

_CAT_EMOJI: dict[str, str] = {
    "travel": "✈️",
    "experience": "🎡",
    "food": "🍽️",
    "adventure": "🏔️",
    "creative": "🎨",
    "learning": "📚",
    "other": "⭐",
}


def _cat_label(category: str) -> str:
    return f"{_CAT_EMOJI.get(category, '⭐')} {category.capitalize()}"


def _user_label(user_id: int) -> str:
    if user_id == DAVID_ID:
        return "David"
    if user_id == STEPH_ID:
        return "Steph"
    return f"<@{user_id}>"


class BucketList(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    bucket = app_commands.Group(name="bucket", description="Shared bucket list")

    # ------------------------------------------------------------------
    # /bucket add
    # ------------------------------------------------------------------
    @bucket.command(name="add", description="Add an item to the bucket list")
    @app_commands.describe(
        title="What do you want to do?",
        category="Category (default: other)",
        link="Optional link for reference",
        note="Optional note",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name=_cat_label(c), value=c) for c in CATEGORIES
    ])
    async def add(
        self,
        interaction: discord.Interaction,
        title: str,
        category: str = "other",
        link: str = "",
        note: str = "",
    ) -> None:
        async with self.bot.db() as s:
            item = BucketListItem(
                guild_id=interaction.guild_id or 0,
                title=title,
                category=category,
                added_by=interaction.user.id,
                link=link,
                note=note,
            )
            s.add(item)
            await s.commit()

        emoji = _CAT_EMOJI.get(category, "⭐")
        parts = [f"{emoji} **{title}** added to the bucket list!"]
        if category != "other":
            parts.append(f"Category: {_cat_label(category)}")
        if note:
            parts.append(f"_{note}_")
        if link:
            parts.append(f"[Link]({link})")
        await interaction.response.send_message("\n".join(parts))

    # ------------------------------------------------------------------
    # /bucket list
    # ------------------------------------------------------------------
    @bucket.command(name="list", description="Browse the bucket list")
    @app_commands.describe(
        category="Filter by category (default: all)",
        status="Filter by completion status (default: todo)",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name="All", value="all")]
        + [app_commands.Choice(name=_cat_label(c), value=c) for c in CATEGORIES],
        status=[
            app_commands.Choice(name="To Do", value="todo"),
            app_commands.Choice(name="Completed", value="completed"),
            app_commands.Choice(name="All", value="all"),
        ],
    )
    async def list(
        self,
        interaction: discord.Interaction,
        category: str = "all",
        status: str = "todo",
    ) -> None:
        async with self.bot.db() as s:
            q = select(BucketListItem).where(BucketListItem.guild_id == interaction.guild_id)
            if category != "all":
                q = q.where(BucketListItem.category == category)
            if status == "todo":
                q = q.where(BucketListItem.completed == False)  # noqa: E712
            elif status == "completed":
                q = q.where(BucketListItem.completed == True)  # noqa: E712
            q = q.order_by(BucketListItem.category, BucketListItem.created_at)
            rows = (await s.scalars(q)).all()

        if not rows:
            label = "bucket list items" if status == "all" else ("completed items" if status == "completed" else "items to do")
            await interaction.response.send_message(f"No {label}! Add something with `/bucket add`.", ephemeral=True)
            return

        title_map = {
            "todo": "Bucket List",
            "completed": "Completed",
            "all": "Bucket List — All",
        }
        embed = discord.Embed(
            title=f"🪣 {title_map[status]}" + (f" — {_cat_label(category)}" if category != "all" else ""),
            color=discord.Color.teal(),
        )

        for item in rows[:25]:
            emoji = _CAT_EMOJI.get(item.category, "⭐")
            check = "✅ " if item.completed else ""
            field_name = f"{check}{emoji} {item.title}"
            parts = [f"Added by {_user_label(item.added_by)}"]
            if item.completed and item.completed_at:
                parts.append(f"Completed {item.completed_at.strftime('%b %d, %Y')}")
            if item.completed_notes:
                parts.append(f"_{item.completed_notes}_")
            if item.note and not item.completed:
                parts.append(f"_{item.note}_")
            if item.link:
                parts.append(f"[Link]({item.link})")
            embed.add_field(name=field_name, value="\n".join(parts), inline=False)

        if len(rows) > 25:
            embed.set_footer(text=f"Showing 25 of {len(rows)} items")

        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /bucket done
    # ------------------------------------------------------------------
    @bucket.command(name="done", description="Mark a bucket list item as completed")
    @app_commands.describe(
        item="Item to mark as done",
        notes="Optional notes about the experience",
    )
    async def done(
        self,
        interaction: discord.Interaction,
        item: str,
        notes: str = "",
    ) -> None:
        try:
            item_id = int(item)
        except ValueError:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return

        async with self.bot.db() as s:
            row = await s.get(BucketListItem, item_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            if row.completed:
                await interaction.response.send_message(
                    f"**{row.title}** is already marked as completed!", ephemeral=True
                )
                return
            row.completed = True
            row.completed_at = datetime.now(timezone.utc)
            if notes:
                row.completed_notes = notes
            await s.commit()
            title = row.title
            emoji = _CAT_EMOJI.get(row.category, "⭐")

        parts = [f"✅ {emoji} **{title}** — bucket list item completed! 🎉"]
        if notes:
            parts.append(f"_{notes}_")
        await interaction.response.send_message("\n".join(parts))

    @done.autocomplete("item")
    async def done_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(BucketListItem)
                    .where(
                        BucketListItem.guild_id == interaction.guild_id,
                        BucketListItem.completed == False,  # noqa: E712
                    )
                    .order_by(BucketListItem.created_at)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(
                name=f"{_CAT_EMOJI.get(r.category, '⭐')} {r.title}",
                value=str(r.id),
            )
            for r in rows
            if not current or current.lower() in r.title.lower()
        ]

    # ------------------------------------------------------------------
    # /bucket progress
    # ------------------------------------------------------------------
    @bucket.command(name="progress", description="See bucket list progress by category")
    async def progress(self, interaction: discord.Interaction) -> None:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(BucketListItem)
                    .where(BucketListItem.guild_id == interaction.guild_id)
                    .order_by(BucketListItem.category)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                "No bucket list items yet! Start adding with `/bucket add`.", ephemeral=True
            )
            return

        total = len(rows)
        done = sum(1 for r in rows if r.completed)
        pct = int(done / total * 100) if total else 0

        # Build progress bar
        filled = pct // 10
        bar = "█" * filled + "░" * (10 - filled)

        embed = discord.Embed(
            title="🪣 Bucket List Progress",
            description=f"`{bar}` {pct}%  —  **{done}/{total}** completed",
            color=discord.Color.teal(),
        )

        # Per-category breakdown
        cat_stats: dict[str, tuple[int, int]] = {}  # category -> (done, total)
        for r in rows:
            d, t = cat_stats.get(r.category, (0, 0))
            cat_stats[r.category] = (d + (1 if r.completed else 0), t + 1)

        for cat in CATEGORIES:
            if cat not in cat_stats:
                continue
            d, t = cat_stats[cat]
            embed.add_field(
                name=_cat_label(cat),
                value=f"{d}/{t} done",
                inline=True,
            )

        # Recent completions
        recent = [r for r in rows if r.completed and r.completed_at]
        recent.sort(key=lambda r: r.completed_at, reverse=True)  # type: ignore[arg-type]
        if recent[:3]:
            lines = []
            for r in recent[:3]:
                date_str = r.completed_at.strftime("%b %d")  # type: ignore[union-attr]
                lines.append(f"✅ {r.title} ({date_str})")
            embed.add_field(name="Recent Wins", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /bucket remove
    # ------------------------------------------------------------------
    @bucket.command(name="remove", description="Remove an item from the bucket list")
    @app_commands.describe(item="Item to remove")
    async def remove(
        self,
        interaction: discord.Interaction,
        item: str,
    ) -> None:
        try:
            item_id = int(item)
        except ValueError:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return

        async with self.bot.db() as s:
            row = await s.get(BucketListItem, item_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            title = row.title
            await s.delete(row)
            await s.commit()

        await interaction.response.send_message(f"🗑️ **{title}** removed from the bucket list.")

    @remove.autocomplete("item")
    async def remove_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(BucketListItem)
                    .where(BucketListItem.guild_id == interaction.guild_id)
                    .order_by(BucketListItem.created_at)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(
                name=f"{'✅ ' if r.completed else ''}{_CAT_EMOJI.get(r.category, '⭐')} {r.title}",
                value=str(r.id),
            )
            for r in rows
            if not current or current.lower() in r.title.lower()
        ]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BucketList(bot))
