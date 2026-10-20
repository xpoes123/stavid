"""End-to-end #bills inbox tests: a fake message goes through the cog into a real
(SQLite) ledger, and we check the resulting balance."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.cogs.budget import net_between_ids
from src.cogs.inbox._utils import APARTMENT_GUILD_ID
from src.cogs.inbox.bills import BillsInbox, SettleConfirmView
from src.db import Base, LedgerEntry
from src.utils import DAVID_ID, STEPH_ID

G = APARTMENT_GUILD_ID


@pytest_asyncio.fixture
async def bot(monkeypatch):
    monkeypatch.setenv("PARTNER_IDS", f"{DAVID_ID},{STEPH_ID}")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SimpleNamespace(db=async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def _msg(content: str, author_id: int = DAVID_ID):
    return SimpleNamespace(
        id=1,
        content=content,
        author=SimpleNamespace(id=author_id, bot=False),
        guild=SimpleNamespace(id=G),
        channel=SimpleNamespace(name="bills", send=AsyncMock()),
        add_reaction=AsyncMock(),
    )


async def _net(bot, me=DAVID_ID, partner=STEPH_ID) -> int:
    async with bot.db() as s:
        return await net_between_ids(s, G, me, partner)


async def _seed(bot, creditor: int, debtor: int, cents: int) -> None:
    async with bot.db() as s:
        s.add(LedgerEntry(guild_id=G, creditor_id=creditor, debtor_id=debtor,
                          amount_cents=cents, note="seed"))
        await s.commit()


# ---------------------------------------------------------------------------
# Direction: net is from David's side (+ = Steph owes David)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content,author,expected_net",
    [
        ("stephanie owes me 30", DAVID_ID, 3000),
        ("Stephanie owes me $30", DAVID_ID, 3000),
        ("you owe me 30", DAVID_ID, 3000),
        ("I owe stephanie 30", DAVID_ID, -3000),
        ("i owe you $30", DAVID_ID, -3000),
        ("I paid 30 for stephanie", DAVID_ID, 3000),
        ("I paid $30 for dinner", DAVID_ID, 3000),
        ("I paid stephanie 30", DAVID_ID, 3000),
        ("stephanie paid 30", DAVID_ID, -3000),
        ("steph paid $30 for dinner", DAVID_ID, -3000),
        ("you paid 30 for groceries", DAVID_ID, -3000),
        ("she covered $30", DAVID_ID, -3000),
        ("david owes me 30", STEPH_ID, -3000),
        ("david paid 30", STEPH_ID, 3000),
        ("I paid $30 for david", STEPH_ID, -3000),
        ("david owes stephanie 30", DAVID_ID, -3000),  # own name as subject
        ("david paid 30 for wifi", DAVID_ID, 3000),
        ("$30 dinner", DAVID_ID, 3000),
    ],
)
async def test_bills_direction(bot, content, author, expected_net):
    await BillsInbox(bot).on_message(_msg(content, author))
    assert await _net(bot) == expected_net


# ---------------------------------------------------------------------------
# Settle: never wipe on a text match; require a button click
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    ["settle up later?", "we're even right?", "settled up yet?", "all square?", "settle up"],
)
async def test_settle_text_does_not_wipe_ledger(bot, content):
    await _seed(bot, DAVID_ID, STEPH_ID, 5000)
    msg = _msg(content)
    await BillsInbox(bot).on_message(msg)
    assert await _net(bot) == 5000


async def test_settle_phrase_posts_confirm_view(bot):
    await _seed(bot, DAVID_ID, STEPH_ID, 5000)
    msg = _msg("settle up")
    await BillsInbox(bot).on_message(msg)
    msg.channel.send.assert_awaited_once()
    view = msg.channel.send.await_args.kwargs.get("view")
    assert isinstance(view, SettleConfirmView)


async def test_settle_phrase_when_square_sends_no_view(bot):
    msg = _msg("settle up")
    await BillsInbox(bot).on_message(msg)
    assert await _net(bot) == 0
    assert msg.channel.send.await_args.kwargs.get("view") is None


def _interaction(user_id: int):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
    )


async def test_confirm_button_settles(bot):
    await _seed(bot, DAVID_ID, STEPH_ID, 5000)
    view = SettleConfirmView(bot, G, DAVID_ID, STEPH_ID)
    inter = _interaction(STEPH_ID)  # either partner may confirm
    await view.do_confirm(inter)
    assert await _net(bot) == 0
    inter.response.edit_message.assert_awaited_once()


async def test_cancel_button_keeps_balance(bot):
    await _seed(bot, DAVID_ID, STEPH_ID, 5000)
    view = SettleConfirmView(bot, G, DAVID_ID, STEPH_ID)
    await view.do_cancel(_interaction(DAVID_ID))
    assert await _net(bot) == 5000


async def test_outsider_cannot_confirm(bot):
    await _seed(bot, DAVID_ID, STEPH_ID, 5000)
    view = SettleConfirmView(bot, G, DAVID_ID, STEPH_ID)
    inter = _interaction(12345)
    await view.do_confirm(inter)
    assert await _net(bot) == 5000
    inter.response.send_message.assert_awaited_once()


async def test_confirm_twice_only_settles_once(bot):
    await _seed(bot, DAVID_ID, STEPH_ID, 5000)
    view = SettleConfirmView(bot, G, DAVID_ID, STEPH_ID)
    await view.do_confirm(_interaction(DAVID_ID))
    await _seed(bot, DAVID_ID, STEPH_ID, 1000)  # new charge after the settle
    await view.do_confirm(_interaction(DAVID_ID))
    assert await _net(bot) == 1000
