from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from .basic import Basic

TEST_GUILD_ID = 1401585357799292958

class StavidBot(commands.Bot):
    def __init__(self, intents: discord.Intents) -> None:
        super().__init__(command_prefix="!", intents=intents)
        intents = intents
        intents.message_content = True
    
    async def setup_hook(self) -> None:
        await self.add_cog(Basic(self))
        guild = discord.Object(id=TEST_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
    
    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, getattr(self.user, "id", "?"))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN in .env")
    bot = StavidBot(discord.Intents.default())
    async with bot:
        await bot.start(token)
        
if __name__ == "__main__":
    asyncio.run(main())