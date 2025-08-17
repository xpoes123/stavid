from __future__ import annotations

import datetime
import os
import typing as t
from decimal import ROUND_HALF_UP, Decimal

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import case, func, select

DAVID_ID = 240608458888445953
STEPH_ID = 694650702466908160


async def resolve_partner(interaction: discord.Interaction) -> discord.Member | None:
    me_id = interaction.user.id
    guild = interaction.guild
    if guild is None:
        return None

    partner_ids = {
        int(x) for x in os.getenv("PARTNER_IDS", "").split(",") if x.strip().isdigit()
    }
    other_id = next((uid for uid in partner_ids if uid != me_id), None)
    if other_id:
        m = guild.get_member(other_id)
        if m is None:
            try:
                m = await guild.fetch_member(other_id)
            except discord.NotFound:
                m = None
        if m and not m.bot:
            return m
