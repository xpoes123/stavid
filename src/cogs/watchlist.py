from __future__ import annotations

import random
import typing as t
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from src.db import WatchlistItem
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

_TYPE_EMOJI = {"movie": "🎬", "show": "📺"}


def _stars(rating: int | None) -> str:
    if rating is None:
        return "—"
    return "⭐" * rating + "☆" * (5 - rating)


def _user_label(user_id: int) -> str:
    if user_id == DAVID_ID:
        return "David"
    if user_id == STEPH_ID:
        return "Steph"
    return f"<@{user_id}>"


class Watchlist(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    watch = app_commands.Group(name="watch", description="Shared movie & show watchlist")

    # ------------------------------------------------------------------
    # /watch add
    # ------------------------------------------------------------------
    @watch.command(name="add", description="Add a movie or show to the watchlist")
    @app_commands.describe(
        title="Title of the movie or show",
        media_type="Movie or show (default: movie)",
        link="Optional streaming or IMDb link",
        note="Optional note",
    )
    @app_commands.choices(media_type=[
        app_commands.Choice(name="Movie", value="movie"),
        app_commands.Choice(name="Show", value="show"),
    ])
    async def add(
        self,
        interaction: discord.Interaction,
        title: str,
        media_type: str = "movie",
        link: str = "",
        note: str = "",
    ) -> None:
        async with self.bot.db() as s:
            item = WatchlistItem(
                guild_id=interaction.guild_id or 0,
                title=title,
                media_type=media_type,
                added_by=interaction.user.id,
                link=link,
                note=note,
            )
            s.add(item)
            await s.commit()

        emoji = _TYPE_EMOJI.get(media_type, "🎬")
        parts = [f"{emoji} **{title}** added to the watchlist"]
        if note:
            parts.append(f"_{note}_")
        if link:
            parts.append(f"[Link]({link})")
        await interaction.response.send_message("\n".join(parts))

    # ------------------------------------------------------------------
    # /watch list
    # ------------------------------------------------------------------
    @watch.command(name="list", description="Show the watchlist")
    @app_commands.describe(status="Filter by watch status (default: unwatched)")
    @app_commands.choices(status=[
        app_commands.Choice(name="Unwatched", value="unwatched"),
        app_commands.Choice(name="Watched", value="watched"),
        app_commands.Choice(name="All", value="all"),
    ])
    async def list(
        self,
        interaction: discord.Interaction,
        status: str = "unwatched",
    ) -> None:
        async with self.bot.db() as s:
            q = select(WatchlistItem).where(WatchlistItem.guild_id == interaction.guild_id)
            if status == "unwatched":
                q = q.where(WatchlistItem.watched == False)  # noqa: E712
            elif status == "watched":
                q = q.where(WatchlistItem.watched == True)  # noqa: E712
            q = q.order_by(WatchlistItem.created_at)
            rows = (await s.scalars(q)).all()

        if not rows:
            labels = {"unwatched": "unwatched titles", "watched": "watched titles", "all": "titles"}
            await interaction.response.send_message(
                f"No {labels[status]} in the watchlist!", ephemeral=True
            )
            return

        embed_titles = {
            "unwatched": "🎬 Watchlist",
            "watched": "✅ Watched",
            "all": "🎬 All Titles",
        }
        embed = discord.Embed(title=embed_titles[status], color=discord.Color.purple())

        for item in rows[:25]:
            emoji = _TYPE_EMOJI.get(item.media_type, "🎬")
            field_name = f"{'✅ ' if item.watched else ''}{emoji} {item.title}"
            parts = [f"Added by {_user_label(item.added_by)}"]
            if item.watched:
                parts.append(
                    f"David: {_stars(item.david_rating)}  Steph: {_stars(item.steph_rating)}"
                )
                if item.david_notes:
                    parts.append(f"David: _{item.david_notes}_")
                if item.steph_notes:
                    parts.append(f"Steph: _{item.steph_notes}_")
            if item.note:
                parts.append(f"_{item.note}_")
            if item.link:
                parts.append(f"[Link]({item.link})")
            embed.add_field(name=field_name, value="\n".join(parts), inline=False)

        if len(rows) > 25:
            embed.set_footer(text=f"Showing 25 of {len(rows)} titles")

        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /watch done
    # ------------------------------------------------------------------
    @watch.command(name="done", description="Mark a title as watched and leave a rating")
    @app_commands.describe(
        item="Title to mark as watched",
        rating="Your rating out of 5",
        review="Your notes or review",
    )
    async def done(
        self,
        interaction: discord.Interaction,
        item: str,
        rating: int | None = None,
        review: str = "",
    ) -> None:
        if rating is not None and not (1 <= rating <= 5):
            await interaction.response.send_message(
                "Rating must be between 1 and 5.", ephemeral=True
            )
            return
        try:
            item_id = int(item)
        except ValueError:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return

        async with self.bot.db() as s:
            row = await s.get(WatchlistItem, item_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            if not row.watched:
                row.watched = True
                row.watched_at = datetime.now(timezone.utc)
            if interaction.user.id == DAVID_ID:
                if rating is not None:
                    row.david_rating = rating
                if review:
                    row.david_notes = review
            else:
                if rating is not None:
                    row.steph_rating = rating
                if review:
                    row.steph_notes = review
            await s.commit()
            title = row.title

        parts = [f"✅ **{title}** marked as watched!"]
        if rating is not None:
            parts.append(_stars(rating))
        if review:
            parts.append(f"_{review}_")
        await interaction.response.send_message(" ".join(parts[:2]) + ("\n" + parts[2] if len(parts) > 2 else ""))

    @done.autocomplete("item")
    async def done_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(WatchlistItem)
                    .where(
                        WatchlistItem.guild_id == interaction.guild_id,
                        WatchlistItem.watched == False,  # noqa: E712
                    )
                    .order_by(WatchlistItem.created_at)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(name=r.title, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.title.lower()
        ]

    # ------------------------------------------------------------------
    # /watch rate
    # ------------------------------------------------------------------
    @watch.command(name="rate", description="Rate or leave notes on a title you've watched")
    @app_commands.describe(
        item="Title to rate",
        rating="Your rating out of 5",
        review="Your notes or review",
    )
    async def rate(
        self,
        interaction: discord.Interaction,
        item: str,
        rating: int | None = None,
        review: str = "",
    ) -> None:
        if rating is not None and not (1 <= rating <= 5):
            await interaction.response.send_message(
                "Rating must be between 1 and 5.", ephemeral=True
            )
            return
        if rating is None and not review:
            await interaction.response.send_message(
                "Provide a rating and/or review.", ephemeral=True
            )
            return
        try:
            item_id = int(item)
        except ValueError:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return

        async with self.bot.db() as s:
            row = await s.get(WatchlistItem, item_id)
            if row is None or row.guild_id != interaction.guild_id or not row.watched:
                await interaction.response.send_message(
                    "❌ Watched title not found.", ephemeral=True
                )
                return
            if interaction.user.id == DAVID_ID:
                if rating is not None:
                    row.david_rating = rating
                if review:
                    row.david_notes = review
            else:
                if rating is not None:
                    row.steph_rating = rating
                if review:
                    row.steph_notes = review
            await s.commit()
            title = row.title

        msg = f"⭐ Updated **{title}**"
        if rating is not None:
            msg += f" — {_stars(rating)}"
        await interaction.response.send_message(msg)

    @rate.autocomplete("item")
    async def rate_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(WatchlistItem)
                    .where(
                        WatchlistItem.guild_id == interaction.guild_id,
                        WatchlistItem.watched == True,  # noqa: E712
                    )
                    .order_by(WatchlistItem.watched_at.desc())
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(name=r.title, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.title.lower()
        ]

    # ------------------------------------------------------------------
    # /watch tonight
    # ------------------------------------------------------------------
    @watch.command(name="tonight", description="Pick something to watch tonight")
    @app_commands.describe(media_type="Filter by movie or show (default: either)")
    @app_commands.choices(media_type=[
        app_commands.Choice(name="Movie", value="movie"),
        app_commands.Choice(name="Show", value="show"),
        app_commands.Choice(name="Either", value="any"),
    ])
    async def tonight(
        self,
        interaction: discord.Interaction,
        media_type: str = "any",
    ) -> None:
        async with self.bot.db() as s:
            q = select(WatchlistItem).where(
                WatchlistItem.guild_id == interaction.guild_id,
                WatchlistItem.watched == False,  # noqa: E712
            )
            if media_type != "any":
                q = q.where(WatchlistItem.media_type == media_type)
            rows = (await s.scalars(q)).all()

        if not rows:
            label = f" {media_type}s" if media_type != "any" else ""
            await interaction.response.send_message(
                f"No unwatched{label} in the watchlist! Add something with `/watch add`.",
                ephemeral=True,
            )
            return

        # Items added by the other person get 2× weight — surface each other's picks
        caller_id = interaction.user.id
        weights = [2 if r.added_by != caller_id else 1 for r in rows]
        pick = random.choices(rows, weights=weights, k=1)[0]

        emoji = _TYPE_EMOJI.get(pick.media_type, "🎬")
        embed = discord.Embed(
            title=f"{emoji} Tonight's Pick",
            description=f"**{pick.title}**",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Type", value=pick.media_type.capitalize(), inline=True)
        embed.add_field(name="Added by", value=_user_label(pick.added_by), inline=True)
        if pick.note:
            embed.add_field(name="Note", value=pick.note, inline=False)
        if pick.link:
            embed.add_field(name="Link", value=pick.link, inline=False)
        total = len(rows)
        embed.set_footer(text=f"{total} unwatched title{'s' if total != 1 else ''} in the queue")

        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /watch remove
    # ------------------------------------------------------------------
    @watch.command(name="remove", description="Remove a title from the watchlist entirely")
    @app_commands.describe(item="Title to remove")
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
            row = await s.get(WatchlistItem, item_id)
            if row is None or row.guild_id != interaction.guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            title = row.title
            await s.delete(row)
            await s.commit()

        await interaction.response.send_message(f"🗑️ **{title}** removed from the watchlist.")

    @remove.autocomplete("item")
    async def remove_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(WatchlistItem)
                    .where(WatchlistItem.guild_id == interaction.guild_id)
                    .order_by(WatchlistItem.created_at)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(name=r.title, value=str(r.id))
            for r in rows
            if not current or current.lower() in r.title.lower()
        ]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Watchlist(bot))
