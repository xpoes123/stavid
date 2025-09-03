# src/main.py
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pkgutil
from pathlib import Path
from urllib.parse import urlsplit

import discord
from discord.ext import commands
from dotenv import load_dotenv

from src.db import create_sessionmaker, init_db  # ← updated import

TEST_GUILD_ID = 1401585357799292958
COGS_PACKAGE = "src.cogs"


class StavidBot(commands.Bot):
    def __init__(self, intents: discord.Intents, db_sessionmaker) -> None:
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = db_sessionmaker

    async def setup_hook(self) -> None:
        await self._load_all_extensions(COGS_PACKAGE)
        guild = discord.Object(id=TEST_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def _load_all_extensions(self, package: str) -> None:
        pkg = importlib.import_module(package)
        for _, name, _ in pkgutil.walk_packages(pkg.__path__, package + "."):
            if name.rsplit(".", 1)[-1].startswith("_"):
                continue
            try:
                await self.load_extension(name)
                logging.info("Loaded extension: %s", name)
            except Exception:
                logging.exception("Failed loading extension %s", name)

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, getattr(self.user, "id", "?"))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ROOT = Path(__file__).resolve().parents[1]
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local", override=True)

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN in env")

    SessionLocal = create_sessionmaker(echo=False)  # ← no arg now
    await init_db(SessionLocal)  # ← create tables

    bot = StavidBot(discord.Intents.default(), SessionLocal)
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
