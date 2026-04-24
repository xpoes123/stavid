"""Tests for supply checklist persistence logic."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from src.cogs.supplies import _this_sunday
from src.db import SupplyCheckResult, SupplyItem

GUILD_ID = 999_000_000_000_000_001
USER_A = 240608458888445953
USER_B = 694650702466908160

# ---------------------------------------------------------------------------
# _this_sunday — week boundary helper
# ---------------------------------------------------------------------------

SUNDAY_APR_20 = date(2026, 4, 19)  # confirmed Sunday


@pytest.mark.parametrize("offset", range(7))
def test_this_sunday_all_days_in_week(offset):
    """Every day in a Sun–Sat week maps to the same Sunday."""
    day = SUNDAY_APR_20 + timedelta(days=offset)
    assert _this_sunday(day) == SUNDAY_APR_20


def test_this_sunday_is_itself():
    assert _this_sunday(SUNDAY_APR_20) == SUNDAY_APR_20


def test_this_sunday_saturday():
    sat = date(2026, 4, 25)
    assert _this_sunday(sat) == SUNDAY_APR_20


def test_this_sunday_crosses_month():
    """Tue Mar 31 2026 → week started Sun Mar 29."""
    assert _this_sunday(date(2026, 3, 31)) == date(2026, 3, 29)


# ---------------------------------------------------------------------------
# SupplyItem persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_supply_item(db_session):
    item = SupplyItem(guild_id=GUILD_ID, name="Toilet paper", active=True)
    db_session.add(item)
    await db_session.commit()

    row = await db_session.scalar(
        select(SupplyItem).where(SupplyItem.guild_id == GUILD_ID)
    )
    assert row is not None
    assert row.name == "Toilet paper"
    assert row.active is True


@pytest.mark.asyncio
async def test_soft_delete_item(db_session):
    item = SupplyItem(guild_id=GUILD_ID, name="Paper towels", active=True)
    db_session.add(item)
    await db_session.commit()

    item.active = False
    await db_session.commit()

    row = await db_session.scalar(
        select(SupplyItem).where(
            SupplyItem.guild_id == GUILD_ID,
            SupplyItem.name == "Paper towels",
        )
    )
    assert row is not None
    assert row.active is False


@pytest.mark.asyncio
async def test_multiple_items_ordered(db_session):
    for name in ("Sponges", "Dish soap", "Trash bags"):
        db_session.add(SupplyItem(guild_id=GUILD_ID, name=name, active=True))
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(SupplyItem)
                .where(SupplyItem.guild_id == GUILD_ID, SupplyItem.active.is_(True))
                .order_by(SupplyItem.name)
            )
        ).all()
    )
    assert [r.name for r in rows] == ["Dish soap", "Sponges", "Trash bags"]


# ---------------------------------------------------------------------------
# SupplyCheckResult — restock flagging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_item_for_restock(db_session):
    item = SupplyItem(guild_id=GUILD_ID, name="Hand soap", active=True)
    db_session.add(item)
    await db_session.commit()

    week_of = date(2026, 4, 19)
    result = SupplyCheckResult(
        guild_id=GUILD_ID,
        week_of=week_of,
        item_id=item.id,
        user_id=USER_A,
    )
    db_session.add(result)
    await db_session.commit()

    row = await db_session.scalar(
        select(SupplyCheckResult).where(
            SupplyCheckResult.guild_id == GUILD_ID,
            SupplyCheckResult.week_of == week_of,
        )
    )
    assert row is not None
    assert row.item_id == item.id
    assert row.user_id == USER_A


@pytest.mark.asyncio
async def test_both_users_can_flag_independently(db_session):
    item = SupplyItem(guild_id=GUILD_ID, name="Laundry detergent", active=True)
    db_session.add(item)
    await db_session.commit()

    week_of = date(2026, 4, 19)
    db_session.add(
        SupplyCheckResult(
            guild_id=GUILD_ID, week_of=week_of, item_id=item.id, user_id=USER_A
        )
    )
    db_session.add(
        SupplyCheckResult(
            guild_id=GUILD_ID, week_of=week_of, item_id=item.id, user_id=USER_B
        )
    )
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(SupplyCheckResult).where(
                    SupplyCheckResult.guild_id == GUILD_ID,
                    SupplyCheckResult.week_of == week_of,
                    SupplyCheckResult.item_id == item.id,
                )
            )
        ).all()
    )
    assert len(rows) == 2
    user_ids = {r.user_id for r in rows}
    assert user_ids == {USER_A, USER_B}


@pytest.mark.asyncio
async def test_restock_flags_are_week_scoped(db_session):
    """Flags from different weeks don't bleed into each other."""
    item = SupplyItem(guild_id=GUILD_ID, name="Dish soap", active=True)
    db_session.add(item)
    await db_session.commit()

    week1 = date(2026, 4, 12)
    week2 = date(2026, 4, 19)
    db_session.add(
        SupplyCheckResult(
            guild_id=GUILD_ID, week_of=week1, item_id=item.id, user_id=USER_A
        )
    )
    await db_session.commit()

    # Query for week2 — should find nothing
    row = await db_session.scalar(
        select(SupplyCheckResult).where(
            SupplyCheckResult.guild_id == GUILD_ID,
            SupplyCheckResult.week_of == week2,
        )
    )
    assert row is None


@pytest.mark.asyncio
async def test_inactive_items_excluded_from_active_list(db_session):
    db_session.add(SupplyItem(guild_id=GUILD_ID, name="Active item", active=True))
    db_session.add(SupplyItem(guild_id=GUILD_ID, name="Removed item", active=False))
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(SupplyItem).where(
                    SupplyItem.guild_id == GUILD_ID,
                    SupplyItem.active.is_(True),
                )
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].name == "Active item"
