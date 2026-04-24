"""Tests for the shared outing wishlist feature."""
from __future__ import annotations

import datetime
import typing as t
import pytest
from sqlalchemy import select

from src.cogs.outings import (
    CATEGORIES,
    _CAT_EMOJI,
    _BUDGET_LABEL,
    _NEVER_VISITED_WEIGHT,
    _cat_label,
    _user_label,
    _roulette_weights,
)
from src.db import OutingWishlistItem

GUILD_ID = 999_000_000_000_000_005
DAVID_ID = 240608458888445953
STEPH_ID = 694650702466908160
OTHER_ID = 111222333444555999

TODAY = datetime.date(2026, 4, 24)


# ---------------------------------------------------------------------------
# Pure-unit helpers
# ---------------------------------------------------------------------------

def test_all_categories_have_emoji():
    for cat in CATEGORIES:
        assert cat in _CAT_EMOJI


def test_cat_label_includes_emoji_and_name():
    label = _cat_label("japanese")
    assert "🍣" in label
    assert "Japanese" in label


def test_cat_label_unknown_falls_back():
    label = _cat_label("unknown")
    assert "📍" in label


def test_user_label_david():
    assert _user_label(DAVID_ID) == "David"


def test_user_label_steph():
    assert _user_label(STEPH_ID) == "Steph"


def test_user_label_unknown_mentions():
    label = _user_label(OTHER_ID)
    assert str(OTHER_ID) in label


def test_budget_labels_defined():
    assert "budget" in _BUDGET_LABEL
    assert "moderate" in _BUDGET_LABEL
    assert "splurge" in _BUDGET_LABEL


# ---------------------------------------------------------------------------
# Roulette weight logic
# ---------------------------------------------------------------------------

import types as _types


def _make_item(category: str) -> t.Any:
    """Lightweight stand-in for roulette weight tests — only needs .category."""
    return _types.SimpleNamespace(category=category)


def test_never_visited_category_gets_max_weight():
    candidates = [_make_item("italian")]
    weights = _roulette_weights(candidates, {}, TODAY)
    assert weights[0] == float(_NEVER_VISITED_WEIGHT)


def test_recently_visited_category_gets_low_weight():
    # Visited yesterday → 1 day
    last = {TODAY.category if hasattr(TODAY, "category") else "italian": TODAY - datetime.timedelta(days=1)}
    last = {"italian": TODAY - datetime.timedelta(days=1)}
    candidates = [_make_item("italian")]
    weights = _roulette_weights(candidates, last, TODAY)
    assert weights[0] == 1.0


def test_weight_reflects_days_since_visit():
    last = {"thai": TODAY - datetime.timedelta(days=30)}
    candidates = [_make_item("thai")]
    weights = _roulette_weights(candidates, last, TODAY)
    assert weights[0] == 30.0


def test_unvisited_category_outweighs_recently_visited():
    last = {"italian": TODAY - datetime.timedelta(days=5)}
    candidates = [_make_item("italian"), _make_item("japanese")]
    weights = _roulette_weights(candidates, last, TODAY)
    italian_w, japanese_w = weights
    # japanese never visited → max weight; italian visited 5 days ago → 5
    assert japanese_w == float(_NEVER_VISITED_WEIGHT)
    assert italian_w == 5.0
    assert japanese_w > italian_w


def test_roulette_weights_floor_at_one():
    # visited today → 0 days difference, floor should be 1
    last = {"mexican": TODAY}
    candidates = [_make_item("mexican")]
    weights = _roulette_weights(candidates, last, TODAY)
    assert weights[0] >= 1.0


def test_roulette_weights_length_matches_candidates():
    candidates = [_make_item("bar"), _make_item("cafe"), _make_item("activity")]
    weights = _roulette_weights(candidates, {}, TODAY)
    assert len(weights) == len(candidates)


# ---------------------------------------------------------------------------
# Database: add / query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_restaurant(db_session):
    item = OutingWishlistItem(
        guild_id=GUILD_ID,
        name="Sushi Nakazawa",
        category="japanese",
        budget="splurge",
        neighborhood="West Village",
        added_by=STEPH_ID,
        note="Omakase only",
    )
    db_session.add(item)
    await db_session.commit()

    row = (
        await db_session.scalars(
            select(OutingWishlistItem).where(OutingWishlistItem.name == "Sushi Nakazawa")
        )
    ).first()
    assert row is not None
    assert row.category == "japanese"
    assert row.budget == "splurge"
    assert row.neighborhood == "West Village"
    assert row.visited is False
    assert row.visited_at is None
    assert row.visited_notes == ""


@pytest.mark.asyncio
async def test_add_activity(db_session):
    item = OutingWishlistItem(
        guild_id=GUILD_ID,
        name="Escape Room",
        category="activity",
        budget="moderate",
        added_by=DAVID_ID,
    )
    db_session.add(item)
    await db_session.commit()

    row = await db_session.get(OutingWishlistItem, item.id)
    assert row.category == "activity"
    assert row.neighborhood == ""
    assert row.link == ""


@pytest.mark.asyncio
async def test_default_category_is_other(db_session):
    item = OutingWishlistItem(guild_id=GUILD_ID, name="Random Place", added_by=DAVID_ID)
    db_session.add(item)
    await db_session.commit()

    row = await db_session.get(OutingWishlistItem, item.id)
    assert row.category == "other"


# ---------------------------------------------------------------------------
# Database: mark visited
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_visited(db_session):
    item = OutingWishlistItem(
        guild_id=GUILD_ID,
        name="Tacos El Pastor",
        category="mexican",
        added_by=DAVID_ID,
    )
    db_session.add(item)
    await db_session.commit()

    item.visited = True
    item.visited_at = TODAY
    item.visited_notes = "Amazing al pastor!"
    await db_session.commit()

    row = await db_session.get(OutingWishlistItem, item.id)
    assert row.visited is True
    assert row.visited_at == TODAY
    assert row.visited_notes == "Amazing al pastor!"


@pytest.mark.asyncio
async def test_visited_at_stored(db_session):
    visit_date = datetime.date(2026, 3, 10)
    item = OutingWishlistItem(
        guild_id=GUILD_ID,
        name="Pasta Place",
        category="italian",
        added_by=STEPH_ID,
        visited=True,
        visited_at=visit_date,
    )
    db_session.add(item)
    await db_session.commit()

    row = await db_session.get(OutingWishlistItem, item.id)
    assert row.visited_at == visit_date


# ---------------------------------------------------------------------------
# Database: filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filter_by_category(db_session):
    db_session.add(OutingWishlistItem(guild_id=GUILD_ID, name="Ramen place", category="japanese", added_by=DAVID_ID))
    db_session.add(OutingWishlistItem(guild_id=GUILD_ID, name="Taco spot", category="mexican", added_by=STEPH_ID))
    db_session.add(OutingWishlistItem(guild_id=GUILD_ID, name="Sushi bar", category="japanese", added_by=STEPH_ID))
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(OutingWishlistItem).where(
                OutingWishlistItem.guild_id == GUILD_ID,
                OutingWishlistItem.category == "japanese",
            )
        )
    ).all()
    assert len(rows) == 2
    assert all(r.category == "japanese" for r in rows)


@pytest.mark.asyncio
async def test_filter_by_budget(db_session):
    db_session.add(OutingWishlistItem(guild_id=GUILD_ID, name="Fancy", category="italian", budget="splurge", added_by=DAVID_ID))
    db_session.add(OutingWishlistItem(guild_id=GUILD_ID, name="Cheap", category="american", budget="budget", added_by=STEPH_ID))
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(OutingWishlistItem).where(
                OutingWishlistItem.guild_id == GUILD_ID,
                OutingWishlistItem.budget == "splurge",
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].name == "Fancy"


@pytest.mark.asyncio
async def test_filter_unvisited(db_session):
    db_session.add(OutingWishlistItem(guild_id=GUILD_ID, name="New place", category="thai", added_by=DAVID_ID))
    db_session.add(OutingWishlistItem(
        guild_id=GUILD_ID, name="Old fave", category="korean",
        added_by=STEPH_ID, visited=True, visited_at=TODAY,
    ))
    await db_session.commit()

    unvisited = (
        await db_session.scalars(
            select(OutingWishlistItem).where(
                OutingWishlistItem.guild_id == GUILD_ID,
                OutingWishlistItem.visited == False,  # noqa: E712
            )
        )
    ).all()
    assert len(unvisited) == 1
    assert unvisited[0].name == "New place"


# ---------------------------------------------------------------------------
# Database: guild isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guild_isolation(db_session):
    OTHER_GUILD = GUILD_ID + 1
    db_session.add(OutingWishlistItem(guild_id=GUILD_ID, name="Our spot", category="italian", added_by=DAVID_ID))
    db_session.add(OutingWishlistItem(guild_id=OTHER_GUILD, name="Their spot", category="italian", added_by=DAVID_ID))
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(OutingWishlistItem).where(OutingWishlistItem.guild_id == GUILD_ID)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].name == "Our spot"


# ---------------------------------------------------------------------------
# Database: delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_item(db_session):
    item = OutingWishlistItem(guild_id=GUILD_ID, name="To Remove", category="bar", added_by=DAVID_ID)
    db_session.add(item)
    await db_session.commit()
    item_id = item.id

    await db_session.delete(item)
    await db_session.commit()

    gone = await db_session.get(OutingWishlistItem, item_id)
    assert gone is None


# ---------------------------------------------------------------------------
# Roulette: last-visit-by-category from real rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roulette_weight_uses_most_recent_visit(db_session):
    """Items visited more recently in a category produce lower weights."""
    earlier = datetime.date(2026, 1, 1)
    later = datetime.date(2026, 3, 1)

    # Two visited italian items; the later one should be used for the weight calc
    db_session.add(OutingWishlistItem(
        guild_id=GUILD_ID, name="Old Italian", category="italian",
        added_by=DAVID_ID, visited=True, visited_at=earlier,
    ))
    db_session.add(OutingWishlistItem(
        guild_id=GUILD_ID, name="Newer Italian", category="italian",
        added_by=STEPH_ID, visited=True, visited_at=later,
    ))
    unvisited = OutingWishlistItem(
        guild_id=GUILD_ID, name="Try This Italian", category="italian", added_by=DAVID_ID
    )
    db_session.add(unvisited)
    await db_session.commit()

    # Build last_visit_by_category the same way the cog does
    visited_rows = (
        await db_session.scalars(
            select(OutingWishlistItem).where(
                OutingWishlistItem.guild_id == GUILD_ID,
                OutingWishlistItem.visited == True,  # noqa: E712
                OutingWishlistItem.visited_at != None,  # noqa: E711
            )
        )
    ).all()

    last_visit_by_category: dict[str, datetime.date] = {}
    for row in visited_rows:
        current = last_visit_by_category.get(row.category)
        if current is None or row.visited_at > current:
            last_visit_by_category[row.category] = row.visited_at

    assert last_visit_by_category["italian"] == later

    weights = _roulette_weights([unvisited], last_visit_by_category, TODAY)
    expected_days = (TODAY - later).days
    assert weights[0] == float(expected_days)
