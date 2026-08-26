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

from src.db import create_sessionmaker

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

    SessionLocal = create_sessionmaker(echo=False)

    bot = StavidBot(discord.Intents.default(), SessionLocal)

    # Optional local HTTP API for Sage. Bound to 127.0.0.1 only — only
    # processes on this same VPS can reach it. Skipped silently if no
    # STAVID_API_TOKEN is set so dev runs aren't forced to wire this up.
    api_task = None
    if os.getenv("STAVID_API_TOKEN"):
        import uvicorn

        from src.api import create_app

        api_host = os.getenv("STAVID_API_HOST", "127.0.0.1")
        api_port = int(os.getenv("STAVID_API_PORT", "7780"))
        app = create_app(SessionLocal)
        config = uvicorn.Config(
            app, host=api_host, port=api_port,
            log_level="warning", access_log=False,
        )
        server = uvicorn.Server(config)
        api_task = asyncio.create_task(server.serve())
        logging.info("Stavid API listening on %s:%d", api_host, api_port)

    # Budget Game dashboard (finance.djiang.xyz). Public, no auth for now —
    # point Caddy's vhost at FINANCE_PORT. Set FINANCE_DASHBOARD=0 to disable.
    dash_task = None
    if os.getenv("FINANCE_DASHBOARD", "1") != "0":
        import uvicorn

        from src.game.dashboard import create_dashboard_app

        dash_host = os.getenv("FINANCE_HOST", "127.0.0.1")
        dash_port = int(os.getenv("FINANCE_PORT", "7781"))
        dash_app = create_dashboard_app(SessionLocal, guild_id=TEST_GUILD_ID)
        dash_server = uvicorn.Server(uvicorn.Config(
            dash_app, host=dash_host, port=dash_port,
            log_level="warning", access_log=False))
        dash_task = asyncio.create_task(dash_server.serve())
        logging.info("Budget Game dashboard listening on %s:%d", dash_host, dash_port)

    try:
        async with bot:
            await bot.start(token)
    finally:
        if api_task is not None:
            api_task.cancel()
        if dash_task is not None:
            dash_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
