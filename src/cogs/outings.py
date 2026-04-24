"""Shared outing wishlist — restaurants and activities to try, with a weighted roulette."""
from __future__ import annotations

import datetime as _dt
import random
import typing as t
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from src.db import OutingWishlistItem
from src.utils import DAVID_ID, STEPH_ID

if t.TYPE_CHECKING:
    from src.main import StavidBot

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

CATEGORIES = [
    "italian", "japanese", "thai", "american", "mexican",
    "korean", "indian", "chinese", "mediterranean",
    "bar", "cafe", "activity", "other",
]

_CAT_EMOJI: dict[str, str] = {
    "italian": "🍝",
    "japanese": "🍣",
    "thai": "🍜",
    "american": "🍔",
    "mexican": "🌮",
    "korean": "🥩",
    "indian": "🍛",
    "chinese": "🥟",
    "mediterranean": "🫒",
    "bar": "🍸",
    "cafe": "☕",
    "activity": "🎯",
    "other": "📍",
}

BUDGETS = ["budget", "moderate", "splurge"]

_BUDGET_LABEL: dict[str, str] = {
    "budget": "$ Budget",
    "moderate": "$$ Moderate",
    "splurge": "$$$ Splurge",
}

# Weight floor for items whose category has never been visited (days equivalent)
_NEVER_VISITED_WEIGHT = 365


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cat_label(category: str) -> str:
    return f"{_CAT_EMOJI.get(category, '📍')} {category.capitalize()}"


def _user_label(user_id: int) -> str:
    if user_id == DAVID_ID:
        return "David"
    if user_id == STEPH_ID:
        return "Steph"
    return f"<@{user_id}>"


def _roulette_weights(
    candidates: list[OutingWishlistItem],
    last_visit_by_category: dict[str, _dt.date],
    today: _dt.date,
) -> list[float]:
    """Return a weight for each candidate based on how long since that category was visited.

    Categories visited recently get lower weight; categories never visited or visited
    long ago get higher weight (up to _NEVER_VISITED_WEIGHT days).
    """
    weights: list[float] = []
    for item in candidates:
        last = last_visit_by_category.get(item.category)
        if last is None:
            days = _NEVER_VISITED_WEIGHT
        else:
            days = max(1, (today - last).days)
        weights.append(float(days))
    return weights


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Outings(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    outing = app_commands.Group(name="outing", description="Shared restaurant & activity wishlist")

    # ------------------------------------------------------------------
    # /outing add
    # ------------------------------------------------------------------
    @outing.command(name="add", description="Add a restaurant or activity to the wishlist")
    @app_commands.describe(
        name="Name of the place or activity",
        category="Type of cuisine or activity",
        budget="Rough price range",
        neighborhood="Neighborhood or area (optional)",
        link="Link for reference (optional)",
        note="Any extra notes (optional)",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name=_cat_label(c), value=c) for c in CATEGORIES],
        budget=[app_commands.Choice(name=v, value=k) for k, v in _BUDGET_LABEL.items()],
    )
    async def add(
        self,
        interaction: discord.Interaction,
        name: str,
        category: str = "other",
        budget: str = "",
        neighborhood: str = "",
        link: str = "",
        note: str = "",
    ) -> None:
        async with self.bot.db() as s:
            item = OutingWishlistItem(
                guild_id=interaction.guild_id or 0,
                name=name,
                category=category,
                budget=budget,
                neighborhood=neighborhood,
                link=link,
                note=note,
                added_by=interaction.user.id,
            )
            s.add(item)
            await s.commit()

        emoji = _CAT_EMOJI.get(category, "📍")
        parts = [f"{emoji} **{name}** added to the outing wishlist!"]
        meta: list[str] = []
        if category != "other":
            meta.append(_cat_label(category))
        if budget:
            meta.append(_BUDGET_LABEL.get(budget, budget))
        if neighborhood:
            meta.append(f"📍 {neighborhood}")
        if meta:
            parts.append(" · ".join(meta))
        if note:
            parts.append(f"_{note}_")
        if link:
            parts.append(f"[More info]({link})")
        await interaction.response.send_message("\n".join(parts))

    # ------------------------------------------------------------------
    # /outing list
    # ------------------------------------------------------------------
    @outing.command(name="list", description="Browse the outing wishlist")
    @app_commands.describe(
        category="Filter by category (default: all)",
        budget="Filter by budget (default: all)",
        neighborhood="Filter by neighborhood (partial match)",
        status="Show visited, unvisited, or all (default: unvisited)",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name="All", value="all")]
        + [app_commands.Choice(name=_cat_label(c), value=c) for c in CATEGORIES],
        budget=[app_commands.Choice(name="All", value="all")]
        + [app_commands.Choice(name=v, value=k) for k, v in _BUDGET_LABEL.items()],
        status=[
            app_commands.Choice(name="Unvisited", value="unvisited"),
            app_commands.Choice(name="Visited", value="visited"),
            app_commands.Choice(name="All", value="all"),
        ],
    )
    async def list(
        self,
        interaction: discord.Interaction,
        category: str = "all",
        budget: str = "all",
        neighborhood: str = "",
        status: str = "unvisited",
    ) -> None:
        async with self.bot.db() as s:
            q = select(OutingWishlistItem).where(
                OutingWishlistItem.guild_id == interaction.guild_id
            )
            if category != "all":
                q = q.where(OutingWishlistItem.category == category)
            if budget != "all":
                q = q.where(OutingWishlistItem.budget == budget)
            if status == "unvisited":
                q = q.where(OutingWishlistItem.visited == False)  # noqa: E712
            elif status == "visited":
                q = q.where(OutingWishlistItem.visited == True)  # noqa: E712
            q = q.order_by(OutingWishlistItem.category, OutingWishlistItem.created_at)
            rows = (await s.scalars(q)).all()

        # Neighborhood filter (case-insensitive substring) done in Python to keep
        # the query backend-agnostic (SQLite vs Postgres ILIKE differences).
        if neighborhood:
            needle = neighborhood.lower()
            rows = [r for r in rows if needle in r.neighborhood.lower()]

        if not rows:
            label = "visited places" if status == "visited" else ("places to try" if status == "unvisited" else "places")
            await interaction.response.send_message(
                f"No {label} found! Add one with `/outing add`.", ephemeral=True
            )
            return

        title_map = {"unvisited": "To Try", "visited": "Visited", "all": "All"}
        embed = discord.Embed(
            title=f"📍 Outings — {title_map[status]}"
            + (f" · {_cat_label(category)}" if category != "all" else ""),
            color=discord.Color.from_str("#e67e22"),
        )

        for item in rows[:25]:
            emoji = _CAT_EMOJI.get(item.category, "📍")
            check = "✅ " if item.visited else ""
            field_name = f"{check}{emoji} {item.name}"
            meta: list[str] = [f"Added by {_user_label(item.added_by)}"]
            if item.budget:
                meta.append(_BUDGET_LABEL.get(item.budget, item.budget))
            if item.neighborhood:
                meta.append(f"📍 {item.neighborhood}")
            if item.visited and item.visited_at:
                meta.append(f"Visited {item.visited_at}")
            if item.visited_notes:
                meta.append(f"_{item.visited_notes}_")
            elif item.note:
                meta.append(f"_{item.note}_")
            if item.link:
                meta.append(f"[Link]({item.link})")
            embed.add_field(name=field_name, value="\n".join(meta), inline=False)

        if len(rows) > 25:
            embed.set_footer(text=f"Showing 25 of {len(rows)} places")

        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------
    # /outing visited
    # ------------------------------------------------------------------
    @outing.command(name="visited", description="Mark a place or activity as visited")
    @app_commands.describe(
        item="Place or activity to mark as visited",
        notes="Notes or memories from the visit",
    )
    async def visited(
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

        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            row = await s.get(OutingWishlistItem, item_id)
            if row is None or row.guild_id != guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            if row.visited:
                await interaction.response.send_message(
                    f"**{row.name}** is already marked as visited.", ephemeral=True
                )
                return
            name = row.name
            emoji = _CAT_EMOJI.get(row.category, "📍")
            row.visited = True
            row.visited_at = _dt.date.today()
            if notes:
                row.visited_notes = notes
            await s.commit()

        parts = [f"✅ {emoji} **{name}** — visited! Nice one! 🎉"]
        if notes:
            parts.append(f"_{notes}_")
        await interaction.response.send_message("\n".join(parts))

    @visited.autocomplete("item")
    async def _visited_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(OutingWishlistItem)
                    .where(
                        OutingWishlistItem.guild_id == interaction.guild_id,
                        OutingWishlistItem.visited == False,  # noqa: E712
                    )
                    .order_by(OutingWishlistItem.name)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(
                name=f"{_CAT_EMOJI.get(r.category, '📍')} {r.name}",
                value=str(r.id),
            )
            for r in rows
            if not current or current.lower() in r.name.lower()
        ]

    # ------------------------------------------------------------------
    # /outing remove
    # ------------------------------------------------------------------
    @outing.command(name="remove", description="Remove an item from the wishlist")
    @app_commands.describe(item="Place or activity to remove")
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

        guild_id = interaction.guild_id or 0
        async with self.bot.db() as s:
            row = await s.get(OutingWishlistItem, item_id)
            if row is None or row.guild_id != guild_id:
                await interaction.response.send_message("❌ Item not found.", ephemeral=True)
                return
            name = row.name
            await s.delete(row)
            await s.commit()

        await interaction.response.send_message(f"🗑️ **{name}** removed from the outing wishlist.")

    @remove.autocomplete("item")
    async def _remove_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(OutingWishlistItem)
                    .where(OutingWishlistItem.guild_id == interaction.guild_id)
                    .order_by(OutingWishlistItem.name)
                    .limit(25)
                )
            ).all()
        return [
            app_commands.Choice(
                name=f"{'✅ ' if r.visited else ''}{_CAT_EMOJI.get(r.category, '📍')} {r.name}",
                value=str(r.id),
            )
            for r in rows
            if not current or current.lower() in r.name.lower()
        ]

    # ------------------------------------------------------------------
    # /outing roulette
    # ------------------------------------------------------------------
    @outing.command(
        name="roulette",
        description="Pick a random outing, weighted toward under-visited categories",
    )
    @app_commands.describe(
        category="Limit to a specific category (default: any)",
        budget="Limit to a budget tier (default: any)",
        neighborhood="Limit to a neighborhood (partial match)",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name="Any", value="any")]
        + [app_commands.Choice(name=_cat_label(c), value=c) for c in CATEGORIES],
        budget=[app_commands.Choice(name="Any", value="any")]
        + [app_commands.Choice(name=v, value=k) for k, v in _BUDGET_LABEL.items()],
    )
    async def roulette(
        self,
        interaction: discord.Interaction,
        category: str = "any",
        budget: str = "any",
        neighborhood: str = "",
    ) -> None:
        guild_id = interaction.guild_id or 0
        today = _dt.date.today()

        async with self.bot.db() as s:
            # All unvisited candidates (pre-filter by category/budget if set)
            q = select(OutingWishlistItem).where(
                OutingWishlistItem.guild_id == guild_id,
                OutingWishlistItem.visited == False,  # noqa: E712
            )
            if category != "any":
                q = q.where(OutingWishlistItem.category == category)
            if budget != "any":
                q = q.where(OutingWishlistItem.budget == budget)
            candidates = list((await s.scalars(q)).all())

            # Most-recent visit date per category across the whole guild
            visited_rows = (
                await s.scalars(
                    select(OutingWishlistItem).where(
                        OutingWishlistItem.guild_id == guild_id,
                        OutingWishlistItem.visited == True,  # noqa: E712
                        OutingWishlistItem.visited_at != None,  # noqa: E711
                    )
                )
            ).all()

        # Neighborhood filter (Python-side for backend compat)
        if neighborhood:
            needle = neighborhood.lower()
            candidates = [c for c in candidates if needle in c.neighborhood.lower()]

        if not candidates:
            await interaction.response.send_message(
                "No unvisited places match those filters. Add more with `/outing add`!",
                ephemeral=True,
            )
            return

        # Build last-visit-by-category lookup
        last_visit_by_category: dict[str, _dt.date] = {}
        for row in visited_rows:
            if row.visited_at is None:
                continue
            current = last_visit_by_category.get(row.category)
            if current is None or row.visited_at > current:
                last_visit_by_category[row.category] = row.visited_at

        weights = _roulette_weights(candidates, last_visit_by_category, today)
        (pick,) = random.choices(candidates, weights=weights, k=1)

        emoji = _CAT_EMOJI.get(pick.category, "📍")
        embed = discord.Embed(
            title=f"🎲 Tonight: {pick.name}",
            color=discord.Color.from_str("#e67e22"),
        )
        embed.add_field(name="Category", value=_cat_label(pick.category), inline=True)
        if pick.budget:
            embed.add_field(name="Budget", value=_BUDGET_LABEL.get(pick.budget, pick.budget), inline=True)
        if pick.neighborhood:
            embed.add_field(name="Neighborhood", value=f"📍 {pick.neighborhood}", inline=True)
        if pick.note:
            embed.add_field(name="Notes", value=pick.note, inline=False)
        if pick.link:
            embed.add_field(name="Link", value=pick.link, inline=False)
        embed.set_footer(
            text=f"Added by {_user_label(pick.added_by)} · "
            f"Use /outing visited to mark it done!"
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Outings(bot))
