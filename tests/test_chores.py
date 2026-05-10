"""Tests for chores cog (pure helpers + DB persistence + materialization)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.cogs.chores import next_due_for, pick_next_assignee
from src.db import ChoreInstance, ChoreTemplate
from src.utils import DAVID_ID, STEPH_ID

GUILD_ID = 999_000_000_000_000_000


# ---------------------------------------------------------------------------
# next_due_for — recurrence math
# ---------------------------------------------------------------------------


def test_weekly_from_sunday_lands_on_monday():
    sun = date(2026, 5, 10)  # Sunday
    assert next_due_for("weekly", sun) == date(2026, 5, 11)


def test_weekly_from_monday_is_today():
    mon = date(2026, 5, 11)
    assert next_due_for("weekly", mon) == mon


def test_weekly_from_tuesday_is_next_monday():
    tue = date(2026, 5, 12)
    assert next_due_for("weekly", tue) == date(2026, 5, 18)


def test_weekly_from_saturday_is_next_monday():
    sat = date(2026, 5, 16)
    assert next_due_for("weekly", sat) == date(2026, 5, 18)


def test_monthly_from_mid_month_is_first_of_next_month():
    assert next_due_for("monthly", date(2026, 5, 15)) == date(2026, 6, 1)


def test_monthly_from_first_is_first_of_next_month():
    """Standing rule: from first-of-month, the next due is first of NEXT month."""
    assert next_due_for("monthly", date(2026, 5, 1)) == date(2026, 6, 1)


def test_monthly_december_rolls_year():
    assert next_due_for("monthly", date(2026, 12, 15)) == date(2027, 1, 1)


def test_unknown_recurrence_raises():
    with pytest.raises(ValueError):
        next_due_for("daily", date(2026, 5, 10))


# ---------------------------------------------------------------------------
# pick_next_assignee
# ---------------------------------------------------------------------------


def test_fixed_default_assignee_always_wins():
    t = ChoreTemplate(
        guild_id=GUILD_ID, name="x", recurrence="weekly",
        default_assignee_id=DAVID_ID, last_assignee_id=STEPH_ID,
    )
    assert pick_next_assignee(t) == DAVID_ID


def test_alternate_starts_with_david_when_no_history():
    t = ChoreTemplate(
        guild_id=GUILD_ID, name="x", recurrence="weekly",
        default_assignee_id=None, last_assignee_id=None,
    )
    assert pick_next_assignee(t) == DAVID_ID


def test_alternate_flips_after_david():
    t = ChoreTemplate(
        guild_id=GUILD_ID, name="x", recurrence="weekly",
        default_assignee_id=None, last_assignee_id=DAVID_ID,
    )
    assert pick_next_assignee(t) == STEPH_ID


def test_alternate_flips_after_steph():
    t = ChoreTemplate(
        guild_id=GUILD_ID, name="x", recurrence="weekly",
        default_assignee_id=None, last_assignee_id=STEPH_ID,
    )
    assert pick_next_assignee(t) == DAVID_ID


def test_alternate_unknown_last_falls_back_to_david():
    """If last_assignee_id is some random user (e.g. a guest), fall back to David."""
    t = ChoreTemplate(
        guild_id=GUILD_ID, name="x", recurrence="weekly",
        default_assignee_id=None, last_assignee_id=12345,
    )
    assert pick_next_assignee(t) == DAVID_ID


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_persists(db_session):
    now = datetime.now(timezone.utc)
    t = ChoreTemplate(
        guild_id=GUILD_ID, name="vacuum", recurrence="weekly",
        active=True, created_at=now, updated_at=now,
    )
    db_session.add(t)
    await db_session.commit()

    row = await db_session.scalar(
        select(ChoreTemplate).where(ChoreTemplate.guild_id == GUILD_ID)
    )
    assert row is not None
    assert row.name == "vacuum"
    assert row.recurrence == "weekly"
    assert row.active is True


@pytest.mark.asyncio
async def test_instance_persists(db_session):
    now = datetime.now(timezone.utc)
    inst = ChoreInstance(
        guild_id=GUILD_ID, template_id=None, name="take out trash",
        assignee_id=DAVID_ID, due_date=date(2026, 5, 12),
        completed=False, created_at=now,
    )
    db_session.add(inst)
    await db_session.commit()

    row = await db_session.scalar(
        select(ChoreInstance).where(ChoreInstance.guild_id == GUILD_ID)
    )
    assert row is not None
    assert row.name == "take out trash"
    assert row.assignee_id == DAVID_ID
    assert row.due_date == date(2026, 5, 12)


@pytest.mark.asyncio
async def test_one_off_instance_has_null_template(db_session):
    """One-off chores (created via /chore add) have template_id=NULL."""
    now = datetime.now(timezone.utc)
    db_session.add(
        ChoreInstance(
            guild_id=GUILD_ID, template_id=None, name="ad-hoc",
            assignee_id=DAVID_ID, due_date=date(2026, 5, 15),
            completed=False, created_at=now,
        )
    )
    await db_session.commit()
    row = await db_session.scalar(
        select(ChoreInstance).where(ChoreInstance.name == "ad-hoc")
    )
    assert row.template_id is None


@pytest.mark.asyncio
async def test_active_chores_query_excludes_completed(db_session):
    now = datetime.now(timezone.utc)
    db_session.add(
        ChoreInstance(
            guild_id=GUILD_ID, template_id=None, name="done one",
            assignee_id=DAVID_ID, due_date=date(2026, 5, 1),
            completed=True, created_at=now,
        )
    )
    db_session.add(
        ChoreInstance(
            guild_id=GUILD_ID, template_id=None, name="open one",
            assignee_id=STEPH_ID, due_date=date(2026, 5, 12),
            completed=False, created_at=now,
        )
    )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(ChoreInstance).where(
                ChoreInstance.guild_id == GUILD_ID,
                ChoreInstance.completed == False,  # noqa: E712
            )
        )
    ).all()
    names = [r.name for r in rows]
    assert names == ["open one"]


@pytest.mark.asyncio
async def test_only_active_templates_picked_for_materialize(db_session):
    """Inactive templates must be excluded from the materialize query."""
    now = datetime.now(timezone.utc)
    db_session.add(
        ChoreTemplate(
            guild_id=GUILD_ID, name="active", recurrence="weekly",
            active=True, created_at=now, updated_at=now,
        )
    )
    db_session.add(
        ChoreTemplate(
            guild_id=GUILD_ID, name="paused", recurrence="weekly",
            active=False, created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(ChoreTemplate).where(
                ChoreTemplate.guild_id == GUILD_ID,
                ChoreTemplate.active == True,  # noqa: E712
            )
        )
    ).all()
    assert [r.name for r in rows] == ["active"]
