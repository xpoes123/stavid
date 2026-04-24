"""Tests for the watchlist feature — models and core helpers."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.cogs.watchlist import _stars, _user_label
from src.db import WatchlistItem

GUILD_ID = 999_000_000_000_000_003
DAVID_ID = 240608458888445953
STEPH_ID = 694650702466908160
OTHER_ID = 111222333444555666


# ---------------------------------------------------------------------------
# Pure-unit helpers
# ---------------------------------------------------------------------------

def test_stars_none():
    assert _stars(None) == "—"


def test_stars_one():
    assert _stars(1) == "⭐☆☆☆☆"


def test_stars_five():
    assert _stars(5) == "⭐⭐⭐⭐⭐"


def test_stars_three():
    s = _stars(3)
    assert s.count("⭐") == 3
    assert s.count("☆") == 2


def test_user_label_david():
    assert _user_label(DAVID_ID) == "David"


def test_user_label_steph():
    assert _user_label(STEPH_ID) == "Steph"


def test_user_label_unknown():
    label = _user_label(OTHER_ID)
    assert str(OTHER_ID) in label


# ---------------------------------------------------------------------------
# Database: add / query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_movie(db_session):
    item = WatchlistItem(
        guild_id=GUILD_ID,
        title="Inception",
        media_type="movie",
        added_by=DAVID_ID,
        link="",
        note="mind-bending",
    )
    db_session.add(item)
    await db_session.commit()

    row = (
        await db_session.scalars(
            select(WatchlistItem).where(WatchlistItem.title == "Inception")
        )
    ).first()
    assert row is not None
    assert row.media_type == "movie"
    assert row.watched is False
    assert row.david_rating is None
    assert row.steph_rating is None
    assert row.note == "mind-bending"


@pytest.mark.asyncio
async def test_add_show(db_session):
    item = WatchlistItem(
        guild_id=GUILD_ID,
        title="The Bear",
        media_type="show",
        added_by=STEPH_ID,
    )
    db_session.add(item)
    await db_session.commit()

    row = (
        await db_session.scalars(
            select(WatchlistItem).where(WatchlistItem.title == "The Bear")
        )
    ).first()
    assert row is not None
    assert row.media_type == "show"
    assert row.added_by == STEPH_ID


# ---------------------------------------------------------------------------
# Database: mark watched + ratings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_watched(db_session):
    item = WatchlistItem(
        guild_id=GUILD_ID, title="Dune", media_type="movie", added_by=DAVID_ID
    )
    db_session.add(item)
    await db_session.commit()

    item.watched = True
    await db_session.commit()

    row = await db_session.get(WatchlistItem, item.id)
    assert row.watched is True


@pytest.mark.asyncio
async def test_david_rates(db_session):
    item = WatchlistItem(
        guild_id=GUILD_ID, title="Parasite", media_type="movie", added_by=STEPH_ID,
        watched=True,
    )
    db_session.add(item)
    await db_session.commit()

    item.david_rating = 5
    item.david_notes = "Masterpiece"
    await db_session.commit()

    row = await db_session.get(WatchlistItem, item.id)
    assert row.david_rating == 5
    assert row.david_notes == "Masterpiece"
    assert row.steph_rating is None  # Steph hasn't rated yet


@pytest.mark.asyncio
async def test_both_rate_independently(db_session):
    item = WatchlistItem(
        guild_id=GUILD_ID, title="Oppenheimer", media_type="movie", added_by=DAVID_ID,
        watched=True,
    )
    db_session.add(item)
    await db_session.commit()

    item.david_rating = 4
    item.david_notes = "Too long but great"
    item.steph_rating = 5
    item.steph_notes = "Cillian Murphy"
    await db_session.commit()

    row = await db_session.get(WatchlistItem, item.id)
    assert row.david_rating == 4
    assert row.steph_rating == 5
    assert row.david_notes == "Too long but great"
    assert row.steph_notes == "Cillian Murphy"


# ---------------------------------------------------------------------------
# Database: guild isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guild_isolation(db_session):
    OTHER_GUILD = GUILD_ID + 1
    item_a = WatchlistItem(
        guild_id=GUILD_ID, title="Shared Title", media_type="movie", added_by=DAVID_ID
    )
    item_b = WatchlistItem(
        guild_id=OTHER_GUILD, title="Shared Title", media_type="movie", added_by=DAVID_ID
    )
    db_session.add(item_a)
    db_session.add(item_b)
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(WatchlistItem).where(WatchlistItem.guild_id == GUILD_ID)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].guild_id == GUILD_ID


# ---------------------------------------------------------------------------
# Database: unwatched query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unwatched_filter(db_session):
    db_session.add(WatchlistItem(
        guild_id=GUILD_ID, title="Unwatched A", media_type="movie", added_by=DAVID_ID
    ))
    db_session.add(WatchlistItem(
        guild_id=GUILD_ID, title="Watched B", media_type="show", added_by=STEPH_ID,
        watched=True,
    ))
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(WatchlistItem).where(
                WatchlistItem.guild_id == GUILD_ID,
                WatchlistItem.watched == False,  # noqa: E712
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].title == "Unwatched A"


# ---------------------------------------------------------------------------
# Database: delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_item(db_session):
    item = WatchlistItem(
        guild_id=GUILD_ID, title="To Delete", media_type="movie", added_by=DAVID_ID
    )
    db_session.add(item)
    await db_session.commit()
    item_id = item.id

    await db_session.delete(item)
    await db_session.commit()

    gone = await db_session.get(WatchlistItem, item_id)
    assert gone is None


# ---------------------------------------------------------------------------
# Randomizer weighting logic (unit test — no Discord)
# ---------------------------------------------------------------------------

def test_tonight_weighting():
    """Partner-added items get 2× weight; self-added get 1×."""
    import random as _random

    # Simulate: caller is David, one item added by Steph, one by David
    class _FakeItem:
        def __init__(self, title, added_by):
            self.title = title
            self.added_by = added_by

    items = [
        _FakeItem("Steph's pick", STEPH_ID),
        _FakeItem("David's pick", DAVID_ID),
    ]
    caller_id = DAVID_ID
    weights = [2 if r.added_by != caller_id else 1 for r in items]

    assert weights == [2, 1]  # Steph's item has double weight

    # With seed, confirm random.choices respects weights
    _random.seed(42)
    picks = [_random.choices(items, weights=weights, k=1)[0].title for _ in range(300)]
    steph_count = picks.count("Steph's pick")
    david_count = picks.count("David's pick")
    # Steph's pick should appear roughly twice as often
    assert steph_count > david_count
