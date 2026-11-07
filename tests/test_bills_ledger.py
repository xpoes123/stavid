"""End-to-end #bills inbox tests: a fake message goes through the cog into a real
(SQLite) ledger, and we check the resulting balance."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from src import piggy
from src.cogs.inbox._utils import APARTMENT_GUILD_ID
from src.cogs.inbox.bills import BillsInbox, SettleConfirmView
from src.utils import DAVID_ID, STEPH_ID

G = APARTMENT_GUILD_ID


class FakePiggy:
    """In-memory stand-in for src.piggy: a list of (creditor, debtor, cents)."""

    def __init__(self):
        self.rows: list[tuple[int, int, int]] = []

    def _partner(self, me):
        return STEPH_ID if me == DAVID_ID else DAVID_ID

    async def add(self, creditor_id, cents, note, payment=False):
        self.rows.append((creditor_id, self._partner(creditor_id), cents))

    async def balance(self, me_id):
        return sum(c if cr == me_id else -c for cr, _d, c in self.rows)

    async def settle(self, me_id):
        net = await self.balance(me_id)
        if net:
            self.rows.append((self._partner(me_id), me_id, net) if net > 0 else (me_id, self._partner(me_id), -net))
        return abs(net)


@pytest_asyncio.fixture
async def bot(monkeypatch):
    monkeypatch.setenv("PARTNER_IDS", f"{DAVID_ID},{STEPH_ID}")
    fake = FakePiggy()
    for name in ("add", "balance", "settle"):
        monkeypatch.setattr(piggy, name, getattr(fake, name))
    yield SimpleNamespace(piggy=fake)


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
    return await bot.piggy.balance(me)


async def _seed(bot, creditor: int, debtor: int, cents: int) -> None:
    bot.piggy.rows.append((creditor, debtor, cents))


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


async def test_piggy_client_settle_posts_balancing_payment(monkeypatch):
    calls = []

    async def fake_call(method, path, as_id, json=None):
        calls.append((method, as_id, json))
        return {"balance_cents": 5000, "entries": []}

    monkeypatch.setattr(piggy, "_call", fake_call)
    assert await piggy.settle(DAVID_ID) == 5000
    assert calls[-1] == ("POST", DAVID_ID, {"amount_cents": 5000, "direction": "they_paid", "note": "settled up"})


async def test_piggy_client_refuses_unknown_user():
    with pytest.raises(piggy.PiggyError):
        await piggy._call("GET", "/api/v1/ledger", 12345)
