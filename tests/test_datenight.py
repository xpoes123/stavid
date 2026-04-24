"""Tests for the date night tracker — models and core helpers."""
from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import select

from src.cogs.datenight import _days_until, _get_or_create_planner
from src.db import DateNightLog, DateNightPlanner, DateNightWishlist, SpecialDate

GUILD_ID = 999_000_000_000_000_002
DAVID_ID = 240608458888445953
STEPH_ID = 694650702466908160

TODAY = _dt.date(2026, 4, 24)  # fixed reference date for deterministic tests


# ---------------------------------------------------------------------------
# _days_until — countdown helper
# ---------------------------------------------------------------------------

def test_days_until_today():
    days, nxt = _days_until(4, 24, TODAY)
    assert days == 0
    assert nxt == TODAY


def test_days_until_tomorrow():
    days, nxt = _days_until(4, 25, TODAY)
    assert days == 1
    assert nxt == _dt.date(2026, 4, 25)


def test_days_until_yesterday_wraps_to_next_year():
    """Apr 23 is past today (Apr 24), so next occurrence is Apr 23 2027."""
    days, nxt = _days_until(4, 23, TODAY)
    assert nxt == _dt.date(2027, 4, 23)
    assert days == (nxt - TODAY).days


def test_days_until_jan_1_from_april():
    days, nxt = _days_until(1, 1, TODAY)
    assert nxt == _dt.date(2027, 1, 1)
    assert days > 200


def test_days_until_dec_31_from_april():
    days, nxt = _days_until(12, 31, TODAY)
    assert nxt == _dt.date(2026, 12, 31)
    assert days > 0


def test_days_until_leap_day_on_non_leap_year():
    """Feb 29 doesn't exist in 2026 — should fall back to Feb 28."""
    # 2026 is not a leap year
    days, nxt = _days_until(2, 29, TODAY)
    assert nxt.month == 2
    assert nxt.day == 28


# ---------------------------------------------------------------------------
# DateNightPlanner — get-or-create and planner logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_planner_creates_row(db_session):
    planner = await _get_or_create_planner(db_session, GUILD_ID)
    await db_session.commit()

    assert planner.guild_id == GUILD_ID
    assert planner.last_planner_id is None

    row = await db_session.scalar(
        select(DateNightPlanner).where(DateNightPlanner.guild_id == GUILD_ID)
    )
    assert row is not None


@pytest.mark.asyncio
async def test_get_or_create_planner_returns_existing(db_session):
    p1 = await _get_or_create_planner(db_session, GUILD_ID)
    p1.last_planner_id = DAVID_ID
    await db_session.commit()

    p2 = await _get_or_create_planner(db_session, GUILD_ID)
    assert p2.id == p1.id
    assert p2.last_planner_id == DAVID_ID


@pytest.mark.asyncio
async def test_planner_last_planner_update(db_session):
    planner = await _get_or_create_planner(db_session, GUILD_ID)
    planner.last_planner_id = DAVID_ID
    await db_session.commit()

    row = await db_session.scalar(
        select(DateNightPlanner).where(DateNightPlanner.guild_id == GUILD_ID)
    )
    assert row.last_planner_id == DAVID_ID


# ---------------------------------------------------------------------------
# DateNightWishlist — add, visit, notes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wishlist_add(db_session):
    item = DateNightWishlist(guild_id=GUILD_ID, name="Dinner at Nobu", added_by=DAVID_ID)
    db_session.add(item)
    await db_session.commit()

    row = await db_session.scalar(
        select(DateNightWishlist).where(DateNightWishlist.guild_id == GUILD_ID)
    )
    assert row is not None
    assert row.name == "Dinner at Nobu"
    assert row.visited is False
    assert row.visited_at is None


@pytest.mark.asyncio
async def test_wishlist_mark_visited(db_session):
    item = DateNightWishlist(guild_id=GUILD_ID, name="Broadway show", added_by=STEPH_ID)
    db_session.add(item)
    await db_session.commit()

    item.visited = True
    item.visited_at = TODAY
    item.notes = "Amazing!"
    await db_session.commit()

    row = await db_session.get(DateNightWishlist, item.id)
    assert row.visited is True
    assert row.visited_at == TODAY
    assert row.notes == "Amazing!"


@pytest.mark.asyncio
async def test_wishlist_unvisited_query(db_session):
    db_session.add(DateNightWishlist(guild_id=GUILD_ID, name="To do", added_by=DAVID_ID, visited=False))
    db_session.add(DateNightWishlist(guild_id=GUILD_ID, name="Done", added_by=STEPH_ID, visited=True))
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(DateNightWishlist)
                .where(DateNightWishlist.guild_id == GUILD_ID, DateNightWishlist.visited == False)  # noqa: E712
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].name == "To do"


@pytest.mark.asyncio
async def test_wishlist_delete(db_session):
    item = DateNightWishlist(guild_id=GUILD_ID, name="Remove me", added_by=DAVID_ID)
    db_session.add(item)
    await db_session.commit()
    item_id = item.id

    await db_session.delete(item)
    await db_session.commit()

    assert await db_session.get(DateNightWishlist, item_id) is None


# ---------------------------------------------------------------------------
# DateNightLog — persistence and rating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_entry_persists(db_session):
    entry = DateNightLog(
        guild_id=GUILD_ID,
        planned_by=DAVID_ID,
        date=TODAY,
        place="Carbone",
        notes="Best pasta ever",
        rating=5,
    )
    db_session.add(entry)
    await db_session.commit()

    row = await db_session.scalar(
        select(DateNightLog).where(DateNightLog.guild_id == GUILD_ID)
    )
    assert row is not None
    assert row.planned_by == DAVID_ID
    assert row.place == "Carbone"
    assert row.rating == 5
    assert row.notes == "Best pasta ever"


@pytest.mark.asyncio
async def test_log_optional_fields_default(db_session):
    entry = DateNightLog(guild_id=GUILD_ID, planned_by=STEPH_ID, date=TODAY)
    db_session.add(entry)
    await db_session.commit()

    row = await db_session.get(DateNightLog, entry.id)
    assert row.place == ""
    assert row.notes == ""
    assert row.rating is None
    assert row.wishlist_item_id is None


@pytest.mark.asyncio
async def test_log_links_wishlist_item(db_session):
    wish = DateNightWishlist(guild_id=GUILD_ID, name="Central Park picnic", added_by=STEPH_ID)
    db_session.add(wish)
    await db_session.commit()

    entry = DateNightLog(
        guild_id=GUILD_ID,
        planned_by=STEPH_ID,
        date=TODAY,
        place="Central Park",
        wishlist_item_id=wish.id,
    )
    db_session.add(entry)
    await db_session.commit()

    row = await db_session.get(DateNightLog, entry.id)
    assert row.wishlist_item_id == wish.id


@pytest.mark.asyncio
async def test_log_ordered_most_recent_first(db_session):
    dates = [_dt.date(2026, 4, d) for d in (1, 10, 20)]
    for d in dates:
        db_session.add(DateNightLog(guild_id=GUILD_ID, planned_by=DAVID_ID, date=d))
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(DateNightLog)
                .where(DateNightLog.guild_id == GUILD_ID)
                .order_by(DateNightLog.date.desc())
            )
        ).all()
    )
    assert [r.date for r in rows] == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# SpecialDate — countdowns and gift ideas
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_special_date_persists(db_session):
    sd = SpecialDate(guild_id=GUILD_ID, label="Anniversary", month=6, day=15, year=2019)
    db_session.add(sd)
    await db_session.commit()

    row = await db_session.scalar(
        select(SpecialDate).where(SpecialDate.guild_id == GUILD_ID)
    )
    assert row.label == "Anniversary"
    assert row.month == 6
    assert row.day == 15
    assert row.year == 2019
    assert row.gift_ideas == ""


@pytest.mark.asyncio
async def test_special_date_gift_ideas_append(db_session):
    sd = SpecialDate(guild_id=GUILD_ID, label="David's Birthday", month=3, day=7)
    db_session.add(sd)
    await db_session.commit()

    sd.gift_ideas = "• Whiskey tasting experience"
    await db_session.commit()

    sd.gift_ideas = sd.gift_ideas + "\n• New sneakers"
    await db_session.commit()

    row = await db_session.get(SpecialDate, sd.id)
    assert "Whiskey tasting experience" in row.gift_ideas
    assert "New sneakers" in row.gift_ideas


@pytest.mark.asyncio
async def test_special_date_no_year_optional(db_session):
    sd = SpecialDate(guild_id=GUILD_ID, label="Steph's Birthday", month=11, day=30)
    db_session.add(sd)
    await db_session.commit()

    row = await db_session.get(SpecialDate, sd.id)
    assert row.year is None


@pytest.mark.asyncio
async def test_multiple_special_dates_per_guild(db_session):
    for label, m, d in [("Anniversary", 6, 15), ("David's Birthday", 3, 7), ("Steph's Birthday", 11, 30)]:
        db_session.add(SpecialDate(guild_id=GUILD_ID, label=label, month=m, day=d))
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(SpecialDate).where(SpecialDate.guild_id == GUILD_ID)
            )
        ).all()
    )
    assert len(rows) == 3
    labels = {r.label for r in rows}
    assert "Anniversary" in labels
    assert "David's Birthday" in labels
    assert "Steph's Birthday" in labels


# ---------------------------------------------------------------------------
# days_until — year calculation correctness
# ---------------------------------------------------------------------------

def test_days_until_anniversary_upcoming():
    """Anniversary on June 15 — from Apr 24 2026, next is Jun 15 2026."""
    days, nxt = _days_until(6, 15, TODAY)
    assert nxt == _dt.date(2026, 6, 15)
    assert days == (nxt - TODAY).days


def test_days_until_anniversary_past_this_year():
    """Anniversary on Mar 7 — from Apr 24 2026, next is Mar 7 2027."""
    days, nxt = _days_until(3, 7, TODAY)
    assert nxt == _dt.date(2027, 3, 7)


def test_days_until_years_for_anniversary():
    """Year calculation: Jun 15 2019 anniversary → 7 years on Jun 15 2026."""
    _days, next_date = _days_until(6, 15, TODAY)
    birth_year = 2019
    years = next_date.year - birth_year
    assert years == 7
