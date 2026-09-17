from __future__ import annotations

import html
import re
import typing as t
from html.parser import HTMLParser
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from src.db import ShoppingItem

if t.TYPE_CHECKING:
    from src.main import StavidBot

_AMAZON_HOSTS = {"amazon.com", "www.amazon.com", "smile.amazon.com", "amzn.to", "amzn.com"}

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; StavidBot/1.0; +https://github.com/xpoes123/stavid)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class _OGParser(HTMLParser):
    """Minimal parser that collects Open Graph and product meta tags."""

    def __init__(self) -> None:
        super().__init__()
        self.og: dict[str, str] = {}
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done or tag != "meta":
            return
        a = dict(attrs)
        prop = a.get("property") or a.get("name") or ""
        content = a.get("content") or ""
        if prop and content:
            self.og[prop] = html.unescape(content)

    def handle_starttag_end(self, tag: str) -> None:
        # Stop parsing once we've left <head>
        pass

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._done = True


def _is_amazon(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return host in _AMAZON_HOSTS or host.endswith(".amazon.com")
    except Exception:
        return False


async def _fetch_og(url: str) -> dict[str, str | None]:
    """Return {'title': ..., 'price': ..., 'image': ...} from OG meta tags.

    All values may be None. Never raises — failures return all-None dict.
    """
    result: dict[str, str | None] = {"title": None, "price": None, "image": None}
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, headers=_FETCH_HEADERS) as session:
            async with session.get(url, allow_redirects=True, max_redirects=5) as resp:
                if resp.status != 200:
                    return result
                # Only read up to 200 KB — enough to capture <head>
                raw = await resp.content.read(200_000)
                text = raw.decode("utf-8", errors="replace")

        parser = _OGParser()
        parser.feed(text)
        og = parser.og

        result["title"] = og.get("og:title") or None
        result["image"] = og.get("og:image") or None

        # Price: Amazon sometimes exposes via product meta tags
        price = (
            og.get("product:price:amount")
            or og.get("twitter:data1")
            or None
        )
        # twitter:data1 is sometimes "X ratings" not a price — only keep if it looks like money
        if price and re.match(r"^\$?[\d,]+(\.\d{1,2})?$", price.strip()):
            currency = og.get("product:price:currency", "USD")
            price = price.strip()
            if not price.startswith("$") and currency == "USD":
                price = f"${price}"
            result["price"] = price

    except Exception:
        pass

    return result


class Shopping(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot

    shopping = app_commands.Group(name="shopping", description="Shared shopping list")

    @shopping.command(name="add", description="Add an item to the shopping list")
    @app_commands.describe(
        name="Item name",
        link="Optional link (URL) — paste an Amazon URL to auto-fill details",
        note="Optional note",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        name: str,
        link: str = "",
        note: str = "",
    ) -> None:
        await interaction.response.defer()

        og_title: str | None = None
        og_price: str | None = None
        og_image: str | None = None

        if link and _is_amazon(link):
            og = await _fetch_og(link)
            og_title = og["title"]
            og_price = og["price"]
            og_image = og["image"]

        async with self.bot.db() as s:
            item = ShoppingItem(
                guild_id=interaction.guild_id or 0,
                name=name,
                link=link,
                note=note,
                added_by=interaction.user.id,
                og_title=og_title,
                og_price=og_price,
                og_image=og_image,
            )
            s.add(item)
            await s.commit()

        display_name = og_title or name
        parts = [f"✅ **{display_name}** added to the shopping list"]
        if og_price:
            parts.append(f"**Price:** {og_price}")
        if note:
            parts.append(f"**Note:** {note}")
        if link:
            parts.append(f"**Link:** {link}")
        await interaction.followup.send("\n".join(parts))

    @shopping.command(name="list", description="Show the current shopping list")
    async def list(self, interaction: discord.Interaction) -> None:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(ShoppingItem)
                    .where(
                        ShoppingItem.guild_id == interaction.guild_id,
                        ShoppingItem.bought == False,  # noqa: E712
                    )
                    .order_by(ShoppingItem.created_at)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                "Shopping list is empty!", ephemeral=False
            )
            return

        embed = discord.Embed(
            title="🛒 Shopping List",
            color=discord.Color.green(),
        )

        # Use the first item's image as the embed thumbnail if available
        first_with_image = next((r for r in rows if r.og_image), None)
        if first_with_image:
            embed.set_thumbnail(url=first_with_image.og_image)

        for item in rows:
            display_name = item.og_title or item.name
            value_parts = [f"Added by <@{item.added_by}>"]
            if item.og_price:
                value_parts.append(f"**{item.og_price}**")
            if item.note:
                value_parts.append(f"_{item.note}_")
            if item.link:
                value_parts.append(f"[Link]({item.link})")
            embed.add_field(
                name=display_name,
                value="\n".join(value_parts),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @shopping.command(name="remove", description="Mark an item as bought and remove it")
    @app_commands.describe(item="Item to remove")
    async def remove(self, interaction: discord.Interaction, item: str) -> None:
        try:
            item_id = int(item)
        except ValueError:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)
            return
        async with self.bot.db() as s:
            row = await s.get(ShoppingItem, item_id)
            if row is None or row.bought or row.guild_id != interaction.guild_id:
                await interaction.response.send_message(
                    "❌ Item not found.", ephemeral=True
                )
                return
            name = row.og_title or row.name
            row.bought = True
            await s.commit()

        await interaction.response.send_message(
            f"✅ **{name}** marked as bought and removed from the list.",
            ephemeral=False,
        )

    @remove.autocomplete("item")
    async def remove_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        async with self.bot.db() as s:
            rows = (
                await s.scalars(
                    select(ShoppingItem)
                    .where(
                        ShoppingItem.guild_id == interaction.guild_id,
                        ShoppingItem.bought == False,  # noqa: E712
                    )
                    .order_by(ShoppingItem.created_at)
                    .limit(25)
                )
            ).all()

        return [
            app_commands.Choice(name=(r.og_title or r.name), value=str(r.id))
            for r in rows
            if not current or current.lower() in (r.og_title or r.name).lower()
        ]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shopping(bot))
