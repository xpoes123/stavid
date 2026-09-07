"""Budget Game cog — daily variable-spend streak for David & Steph.

Card-agnostic: pulls every connected card via SimpleFIN, classifies each txn's
money-type (only Variable counts), and posts one brief showing both players'
separate caps + streaks. Reuses Stavid's Postgres, Discord connection, and the
#bills ledger. Deploy note: run `alembic upgrade head` after deploying — the
game_* tables are new.
"""
from __future__ import annotations

import base64
import datetime as dt
import logging
import os
import typing as t
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from src.db import GameAccount, GamePlayer, GameRule, GameTxn
from src.game import classify, core, simplefin

if t.TYPE_CHECKING:
    from src.main import StavidBot

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
BRIEF_HOUR = 7                       # local ET
GAME_CHANNEL = os.getenv("GAME_CHANNEL", "budget")
FREEZES_PER_MONTH = 1
LOOKBACK_MIN = 21
SHADOW_START, SHADOW_END = "2026-09-01", "2026-09-07"


def _in_shadow(day: dt.date) -> bool:
    return SHADOW_START <= day.isoformat() <= SHADOW_END


def _money(cents: int) -> str:
    return f"${cents/100:,.0f}"


def _bar(cents: int, cap: int, width: int = 10) -> str:
    filled = max(0, min(round(cents / cap * width), width)) if cap else 0
    return "█" * filled + "░" * (width - filled)


class Game(commands.Cog):
    def __init__(self, bot: StavidBot) -> None:
        self.bot = bot
        self.daily.start()

    def cog_unload(self) -> None:
        self.daily.cancel()

    # ── daily loop ────────────────────────────────────────────────────────────
    @tasks.loop(minutes=30)
    async def daily(self) -> None:
        """Poll; post once per guild when it's the brief hour in ET (DST-safe)."""
        now = dt.datetime.now(ET)
        if now.hour != BRIEF_HOUR:
            return
        today = now.date()
        for guild in self.bot.guilds:
            async with self.bot.db() as s:
                players = list((await s.scalars(
                    select(GamePlayer).where(GamePlayer.guild_id == guild.id))).all())
                already = [p for p in players if p.last_brief_date == today.isoformat()]
            if players and len(already) < len(players):
                try:
                    await self._post_brief(guild, today)
                except Exception:
                    log.exception("budget game brief failed for guild %s", guild.id)

    @daily.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    # ── core run ──────────────────────────────────────────────────────────────
    async def _sync_and_score(self, player: GamePlayer, today: dt.date) -> core.Score | None:
        """Pull -> classify -> persist -> score one player. None if not set up."""
        if not player.access_url:
            return None
        async with self.bot.db() as s:
            accts = list((await s.scalars(select(GameAccount).where(
                GameAccount.user_id == player.user_id,
                GameAccount.active == True))).all())  # noqa: E712
        if not accts:
            return None
        card_ids = {a.simplefin_id for a in accts if a.kind == "card"}
        all_ids = [a.simplefin_id for a in accts]

        yesterday = today - dt.timedelta(days=1)
        lookback = max(LOOKBACK_MIN, yesterday.day + 1)   # cover MTD for the streak
        txns = await simplefin.fetch(player.access_url, all_ids, lookback)
        spend = simplefin.spendable(txns, card_ids)

        async with self.bot.db() as s:
            rules = {r.merchant_key: {"category": r.category, "money_type": r.money_type}
                     for r in (await s.scalars(select(GameRule).where(
                         GameRule.user_id == player.user_id))).all()}
        classed = await classify.classify(spend, rules)

        # Upsert classified txns (dedupe by simplefin_id; pendings update in place).
        async with self.bot.db() as s:
            existing = {r.simplefin_id: r for r in (await s.scalars(select(GameTxn).where(
                GameTxn.user_id == player.user_id))).all()}
            for c in classed:
                row = existing.get(c.txn.simplefin_id)
                if row is None:
                    row = GameTxn(user_id=player.user_id, simplefin_id=c.txn.simplefin_id)
                    s.add(row)
                row.account_id = c.txn.account_id
                row.posted_date = c.txn.date
                row.cents = c.txn.cents
                row.description = c.txn.description
                row.money_type = c.money_type
                row.category = c.category
                row.confidence = int(round(c.confidence * 100))
                row.needs_review = c.needs_review
                row.updated_at = dt.datetime.now(dt.timezone.utc)
            await s.commit()

            # Score off everything stored this month (spend-positive SpendItems).
            month_rows = list((await s.scalars(select(GameTxn).where(
                GameTxn.user_id == player.user_id))).all())
            items = [core.SpendItem(date=r.posted_date, cents=-r.cents,
                                    money_type=r.money_type, category=r.category)
                     for r in month_rows]
            by_day = core.variable_by_day(items)
            score, fields = core.score_day(
                yesterday, by_day, cap_cents=player.monthly_cap_cents,
                streak=player.streak, freezes_remaining=player.freezes_remaining,
                freeze_month=player.freeze_month or None, last_scored=player.last_scored or None,
                freezes_per_month=FREEZES_PER_MONTH, shadow=_in_shadow(yesterday))
            player.streak = fields["streak"]
            player.freezes_remaining = fields["freezes_remaining"]
            player.freeze_month = fields["freeze_month"] or ""
            player.last_scored = fields["last_scored"] or ""
            await s.merge(player)
            await s.commit()
        return score

    async def _player_block(self, guild: discord.Guild, player: GamePlayer,
                            score: core.Score | None, today: dt.date) -> tuple[str, list]:
        member = guild.get_member(player.user_id)
        name = member.display_name if member else f"user {player.user_id}"
        if score is None:
            return f"**{name}** — not set up (`/game connect`)", []

        cap = player.monthly_cap_cents
        pace = "ON PACE ✅" if score.on_pace else "OVER ⚠️"
        cat, review = await self._category_totals(player.user_id, today)
        lines = [f"**{name}** · 🔥 {score.streak}  {'(shadow)' if score.shadow else ''}",
                 f"{_money(score.spent_cents)} / {_money(cap)} · {_money(score.allowed_cents)} allowed → {pace}"]
        if score.froze:
            lines.append("❄️ freeze used — streak survived")
        for c, amt in sorted(cat.items(), key=lambda kv: -kv[1])[:4]:
            lines.append(f"`{c:<13}` {_bar(amt, cap)} {_money(amt)}")
        return "\n".join(lines), review

    async def _category_totals(self, user_id: int, today: dt.date):
        async with self.bot.db() as s:
            rows = list((await s.scalars(select(GameTxn).where(
                GameTxn.user_id == user_id))).all())
        cat: dict[str, int] = {}
        review = []
        for r in rows:
            if r.posted_date.month == today.month and r.posted_date.year == today.year:
                if r.money_type == core.VARIABLE:
                    cat[r.category] = cat.get(r.category, 0) - r.cents
                if r.needs_review:
                    review.append(r)
        return cat, review

    async def _post_brief(self, guild: discord.Guild, today: dt.date) -> None:
        channel = discord.utils.get(guild.text_channels, name=GAME_CHANNEL)
        if channel is None:
            log.warning("no #%s channel in guild %s", GAME_CHANNEL, guild.id)
            return
        async with self.bot.db() as s:
            players = list((await s.scalars(select(GamePlayer).where(
                GamePlayer.guild_id == guild.id))).all())

        blocks, all_review = [], []
        for p in players:
            score = await self._sync_and_score(p, today)
            block, review = await self._player_block(guild, p, score, today)
            blocks.append(block)
            all_review += [(p.user_id, r) for r in review]

        shadow = _in_shadow(today - dt.timedelta(days=1))
        title = f"{'[SHADOW] ' if shadow else ''}📊 Budget · {today:%b %d}"
        desc = "\n\n".join(blocks)
        if all_review:
            desc += f"\n\n⚠️ {len(all_review)} need review — `/game rule` to teach me:\n"
            desc += "\n".join(f"• {r.description[:34]} ({_money(-r.cents)})"
                              for _, r in all_review[:6])
        embed = discord.Embed(title=title, description=desc,
                              color=0x2ecc71 if all(("OVER" not in b) for b in blocks) else 0xf1c40f)
        await channel.send(embed=embed)

        async with self.bot.db() as s:
            for p in players:
                p.last_brief_date = today.isoformat()
                await s.merge(p)
            await s.commit()

    # ── slash commands ────────────────────────────────────────────────────────
    group = app_commands.Group(name="game", description="Budget Game")

    async def _get_or_create(self, s, guild_id: int, user_id: int) -> GamePlayer:
        p = (await s.scalars(select(GamePlayer).where(
            GamePlayer.guild_id == guild_id, GamePlayer.user_id == user_id))).first()
        if p is None:
            p = GamePlayer(guild_id=guild_id, user_id=user_id)
            s.add(p)
            await s.commit()
        return p

    @group.command(name="connect", description="Connect SimpleFIN (setup token or access URL). Private.")
    async def connect(self, interaction: discord.Interaction, token_or_url: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            access_url = await _claim_if_token(token_or_url.strip())
            accounts = await simplefin.discover_accounts(access_url)
        except Exception as e:
            await interaction.followup.send(f"❌ Couldn't connect: {type(e).__name__}", ephemeral=True)
            return
        async with self.bot.db() as s:
            p = await self._get_or_create(s, interaction.guild_id, interaction.user.id)
            p.access_url = access_url
            existing = {a.simplefin_id for a in (await s.scalars(select(GameAccount).where(
                GameAccount.user_id == interaction.user.id))).all()}
            for a in accounts:
                if a["id"] not in existing:
                    s.add(GameAccount(user_id=interaction.user.id, simplefin_id=a["id"],
                                      name=a["name"], kind=a["kind"]))
            await s.merge(p)
            await s.commit()
        listing = "\n".join(f"• {a['name']} ({a['kind']})" for a in accounts)
        await interaction.followup.send(
            f"✅ Connected {len(accounts)} accounts:\n{listing}\n\nCards count toward the "
            f"game; checking is for context. `/game cap` to set your monthly variable cap.",
            ephemeral=True)

    @group.command(name="cap", description="Set your monthly variable-spend cap (dollars).")
    async def cap(self, interaction: discord.Interaction,
                  amount: app_commands.Range[float, 1, 100000]) -> None:
        async with self.bot.db() as s:
            p = await self._get_or_create(s, interaction.guild_id, interaction.user.id)
            p.monthly_cap_cents = int(round(amount * 100))
            await s.merge(p)
            await s.commit()
        await interaction.response.send_message(
            f"✅ Monthly cap set to {_money(int(amount*100))}.", ephemeral=True)

    @group.command(name="rule", description="Teach a merchant's category + money-type.")
    @app_commands.describe(merchant="Text from the transaction (e.g. 'CHILIS')",
                           category="Category", money_type="Variable / Fixed / Sinking")
    @app_commands.choices(money_type=[
        app_commands.Choice(name=m, value=m) for m in core.MONEY_TYPES])
    async def rule(self, interaction: discord.Interaction, merchant: str,
                   category: str, money_type: app_commands.Choice[str]) -> None:
        key = classify.normalize(merchant)
        async with self.bot.db() as s:
            existing = (await s.scalars(select(GameRule).where(
                GameRule.user_id == interaction.user.id,
                GameRule.merchant_key == key))).first()
            if existing:
                existing.category, existing.money_type = category, money_type.value
            else:
                s.add(GameRule(user_id=interaction.user.id, merchant_key=key,
                               category=category, money_type=money_type.value))
            # Reclassify already-stored txns that match this merchant.
            for r in (await s.scalars(select(GameTxn).where(
                    GameTxn.user_id == interaction.user.id))).all():
                if classify.normalize(r.description) == key:
                    r.category, r.money_type = category, money_type.value
                    r.confidence, r.needs_review = 100, False
            await s.commit()
        await interaction.response.send_message(
            f"✅ `{key}` → {category} / {money_type.value} (applied to matching txns).",
            ephemeral=True)

    @group.command(name="status", description="Your current month spend, pace, and streak.")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        today = dt.datetime.now(ET).date()
        async with self.bot.db() as s:
            p = await self._get_or_create(s, interaction.guild_id, interaction.user.id)
        score = await self._sync_and_score(p, today)
        if score is None:
            await interaction.followup.send("Not set up yet — `/game connect`.", ephemeral=True)
            return
        pace = "ON PACE ✅" if score.on_pace else "OVER ⚠️"
        await interaction.followup.send(
            f"🔥 {score.streak} · {_money(score.spent_cents)}/{_money(p.monthly_cap_cents)} "
            f"· {_money(score.allowed_cents)} allowed → {pace} · freezes {score.freezes_remaining}",
            ephemeral=True)

    @group.command(name="run", description="Post today's brief now (testing).")
    async def run(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._post_brief(interaction.guild, dt.datetime.now(ET).date())
        await interaction.followup.send("Posted.", ephemeral=True)


async def _claim_if_token(value: str) -> str:
    """A SimpleFIN setup token is base64 of a claim URL; an access URL is https."""
    if value.startswith("http"):
        return value
    claim_url = base64.b64decode(value).decode()
    async with aiohttp.ClientSession() as sess:
        async with sess.post(claim_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            return (await resp.text()).strip()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Game(bot))
