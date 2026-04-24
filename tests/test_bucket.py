"""Tests for the bucket list feature."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from src.cogs.bucket import _cat_label, _user_label, CATEGORIES, _CAT_EMOJI
from src.db import BucketListItem

GUILD_ID = 999_000_000_000_000_004
DAVID_ID = 240608458888445953
STEPH_ID = 694650702466908160
OTHER_ID = 111222333444555777


# ---------------------------------------------------------------------------
# Pure-unit helpers
# ---------------------------------------------------------------------------

def test_cat_label_travel():
    label = _cat_label("travel")
    assert "travel" in label.lower()
    assert "✈️" in label


def test_cat_label_food():
    label = _cat_label("food")
    assert "food" in label.lower()
    assert "🍽️" in label


def test_cat_label_unknown():
    label = _cat_label("mystery")
    assert "Mystery" in label


def test_all_categories_have_emoji():
    for cat in CATEGORIES:
        assert cat in _CAT_EMOJI


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
async def test_add_travel_item(db_session):
    item = BucketListItem(
        guild_id=GUILD_ID,
        title="See the Northern Lights",
        category="travel",
        added_by=STEPH_ID,
        note="Iceland or Norway",
    )
    db_session.add(item)
    await db_session.commit()

    row = (
        await db_session.scalars(
            select(BucketListItem).where(BucketListItem.title == "See the Northern Lights")
        )
    ).first()
    assert row is not None
    assert row.category == "travel"
    assert row.completed is False
    assert row.completed_at is None
    assert row.note == "Iceland or Norway"
    assert row.completed_notes == ""


@pytest.mark.asyncio
async def test_add_food_item(db_session):
    item = BucketListItem(
        guild_id=GUILD_ID,
        title="Try omakase",
        category="food",
        added_by=DAVID_ID,
    )
    db_session.add(item)
    await db_session.commit()

    row = (
        await db_session.scalars(
            select(BucketListItem).where(BucketListItem.title == "Try omakase")
        )
    ).first()
    assert row is not None
    assert row.category == "food"
    assert row.added_by == DAVID_ID


@pytest.mark.asyncio
async def test_default_category_is_other(db_session):
    item = BucketListItem(
        guild_id=GUILD_ID,
        title="Generic dream",
        added_by=DAVID_ID,
    )
    db_session.add(item)
    await db_session.commit()

    row = await db_session.get(BucketListItem, item.id)
    assert row.category == "other"


# ---------------------------------------------------------------------------
# Database: mark completed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_completed(db_session):
    item = BucketListItem(
        guild_id=GUILD_ID,
        title="Skydiving",
        category="adventure",
        added_by=DAVID_ID,
    )
    db_session.add(item)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    item.completed = True
    item.completed_at = now
    item.completed_notes = "What a rush!"
    await db_session.commit()

    row = await db_session.get(BucketListItem, item.id)
    assert row.completed is True
    assert row.completed_at is not None
    assert row.completed_notes == "What a rush!"


@pytest.mark.asyncio
async def test_completed_at_stored(db_session):
    item = BucketListItem(
        guild_id=GUILD_ID,
        title="Pottery class",
        category="creative",
        added_by=STEPH_ID,
        completed=True,
        completed_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        completed_notes="So relaxing",
    )
    db_session.add(item)
    await db_session.commit()

    row = await db_session.get(BucketListItem, item.id)
    assert row.completed is True
    assert row.completed_at.year == 2026
    assert row.completed_at.month == 3


# ---------------------------------------------------------------------------
# Database: filtering by category and status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filter_by_category(db_session):
    db_session.add(BucketListItem(guild_id=GUILD_ID, title="Paris trip", category="travel", added_by=DAVID_ID))
    db_session.add(BucketListItem(guild_id=GUILD_ID, title="Sushi class", category="food", added_by=STEPH_ID))
    db_session.add(BucketListItem(guild_id=GUILD_ID, title="Bali trip", category="travel", added_by=STEPH_ID))
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(BucketListItem).where(
                BucketListItem.guild_id == GUILD_ID,
                BucketListItem.category == "travel",
            )
        )
    ).all()
    assert len(rows) == 2
    assert all(r.category == "travel" for r in rows)


@pytest.mark.asyncio
async def test_filter_todo_vs_completed(db_session):
    db_session.add(BucketListItem(guild_id=GUILD_ID, title="Pending item", category="other", added_by=DAVID_ID))
    db_session.add(BucketListItem(
        guild_id=GUILD_ID, title="Done item", category="other", added_by=STEPH_ID,
        completed=True, completed_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    todo = (
        await db_session.scalars(
            select(BucketListItem).where(
                BucketListItem.guild_id == GUILD_ID,
                BucketListItem.completed == False,  # noqa: E712
            )
        )
    ).all()
    done = (
        await db_session.scalars(
            select(BucketListItem).where(
                BucketListItem.guild_id == GUILD_ID,
                BucketListItem.completed == True,  # noqa: E712
            )
        )
    ).all()

    assert len(todo) == 1
    assert todo[0].title == "Pending item"
    assert len(done) == 1
    assert done[0].title == "Done item"


# ---------------------------------------------------------------------------
# Database: guild isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guild_isolation(db_session):
    OTHER_GUILD = GUILD_ID + 1
    db_session.add(BucketListItem(guild_id=GUILD_ID, title="Our dream", category="travel", added_by=DAVID_ID))
    db_session.add(BucketListItem(guild_id=OTHER_GUILD, title="Our dream", category="travel", added_by=DAVID_ID))
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(BucketListItem).where(BucketListItem.guild_id == GUILD_ID)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].guild_id == GUILD_ID


# ---------------------------------------------------------------------------
# Database: delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_item(db_session):
    item = BucketListItem(guild_id=GUILD_ID, title="To Delete", category="other", added_by=DAVID_ID)
    db_session.add(item)
    await db_session.commit()
    item_id = item.id

    await db_session.delete(item)
    await db_session.commit()

    gone = await db_session.get(BucketListItem, item_id)
    assert gone is None


# ---------------------------------------------------------------------------
# Progress logic (unit test — no Discord)
# ---------------------------------------------------------------------------

def test_progress_bar_math():
    """Verify progress percentage calculation logic."""
    total = 10
    done = 3
    pct = int(done / total * 100)
    assert pct == 30

    filled = pct // 10
    bar = "█" * filled + "░" * (10 - filled)
    assert bar.count("█") == 3
    assert bar.count("░") == 7
    assert len(bar) == 10


def test_progress_all_done():
    total = 5
    done = 5
    pct = int(done / total * 100)
    assert pct == 100
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    assert "░" not in bar


def test_progress_none_done():
    total = 4
    done = 0
    pct = int(done / total * 100)
    assert pct == 0
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    assert "█" not in bar


# ---------------------------------------------------------------------------
# Database: link field
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_item_with_link(db_session):
    item = BucketListItem(
        guild_id=GUILD_ID,
        title="Hot air balloon",
        category="adventure",
        added_by=STEPH_ID,
        link="https://example.com/balloon",
    )
    db_session.add(item)
    await db_session.commit()

    row = await db_session.get(BucketListItem, item.id)
    assert row.link == "https://example.com/balloon"
