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


# ---------------------------------------------------------------------------
# bucket_by_recurrence — splits instances into (weekly, monthly)
# ---------------------------------------------------------------------------

from datetime import date as _date  # noqa: E402

from src.cogs.chores import bucket_by_recurrence, build_chore_digest  # noqa: E402


def _inst(template_id, name, assignee_id=DAVID_ID, due=None, instance_id=1):
    """Build an unsaved ChoreInstance for testing."""
    return ChoreInstance(
        id=instance_id,
        guild_id=GUILD_ID,
        template_id=template_id,
        name=name,
        assignee_id=assignee_id,
        due_date=due or _date(2026, 5, 12),
    )


def _tmpl(template_id, recurrence):
    return ChoreTemplate(
        id=template_id,
        guild_id=GUILD_ID,
        name=f"tmpl-{template_id}",
        recurrence=recurrence,
    )


def test_bucket_one_off_goes_to_weekly():
    rows = [_inst(template_id=None, name="ad-hoc")]
    weekly, monthly = bucket_by_recurrence(rows, {})
    assert [r.name for r in weekly] == ["ad-hoc"]
    assert monthly == []


def test_bucket_weekly_template_goes_to_weekly():
    rows = [_inst(template_id=10, name="vacuum")]
    templates = {10: _tmpl(10, "weekly")}
    weekly, monthly = bucket_by_recurrence(rows, templates)
    assert [r.name for r in weekly] == ["vacuum"]
    assert monthly == []


def test_bucket_monthly_template_goes_to_monthly():
    rows = [_inst(template_id=20, name="filter")]
    templates = {20: _tmpl(20, "monthly")}
    weekly, monthly = bucket_by_recurrence(rows, templates)
    assert weekly == []
    assert [r.name for r in monthly] == ["filter"]


def test_bucket_missing_template_falls_back_to_weekly():
    """If the template lookup is missing (deleted/orphaned), default to weekly."""
    rows = [_inst(template_id=99, name="orphan")]
    weekly, monthly = bucket_by_recurrence(rows, {})  # no template provided
    assert [r.name for r in weekly] == ["orphan"]
    assert monthly == []


def test_bucket_mixed():
    rows = [
        _inst(template_id=1, name="dishes", instance_id=1),
        _inst(template_id=2, name="filter", instance_id=2),
        _inst(template_id=None, name="grocery run", instance_id=3),
    ]
    templates = {1: _tmpl(1, "weekly"), 2: _tmpl(2, "monthly")}
    weekly, monthly = bucket_by_recurrence(rows, templates)
    assert [r.name for r in weekly] == ["dishes", "grocery run"]
    assert [r.name for r in monthly] == ["filter"]


# ---------------------------------------------------------------------------
# build_chore_digest — embed contents
# ---------------------------------------------------------------------------


def test_digest_groups_by_assignee():
    today = _date(2026, 5, 12)
    rows = [
        _inst(template_id=1, name="dishes", assignee_id=DAVID_ID, due=today, instance_id=1),
        _inst(template_id=1, name="trash", assignee_id=DAVID_ID, due=today, instance_id=2),
        _inst(template_id=1, name="laundry", assignee_id=STEPH_ID, due=today, instance_id=3),
    ]
    embed = build_chore_digest("Weekly", rows, today)
    field_names = [f.name for f in embed.fields]
    # Two fields, one per assignee, with count
    assert any(f"<@{DAVID_ID}> (2)" == n for n in field_names)
    assert any(f"<@{STEPH_ID}> (1)" == n for n in field_names)


def test_digest_overdue_marker():
    today = _date(2026, 5, 12)
    rows = [
        _inst(template_id=1, name="dishes", due=_date(2026, 5, 9), instance_id=1),
    ]
    embed = build_chore_digest("Weekly", rows, today)
    field = embed.fields[0]
    assert "3d overdue" in field.value


def test_digest_due_today_marker():
    today = _date(2026, 5, 12)
    rows = [_inst(template_id=1, name="dishes", due=today, instance_id=1)]
    embed = build_chore_digest("Weekly", rows, today)
    assert "due today" in embed.fields[0].value


def test_digest_summary_counts():
    today = _date(2026, 5, 12)
    rows = [
        _inst(template_id=1, name="a", due=today, instance_id=1),
        _inst(template_id=1, name="b", due=today, instance_id=2),
        _inst(template_id=1, name="c", due=_date(2026, 5, 10), instance_id=3),
    ]
    embed = build_chore_digest("Weekly", rows, today)
    desc = embed.description
    assert "2" in desc and "due today" in desc
    assert "1" in desc and "overdue" in desc


def test_digest_color_when_overdue_is_orange():
    import discord
    today = _date(2026, 5, 12)
    rows = [_inst(template_id=1, name="late", due=_date(2026, 5, 1), instance_id=1)]
    embed = build_chore_digest("Weekly", rows, today)
    assert embed.color == discord.Color.orange()


def test_digest_color_when_only_today_is_blurple():
    import discord
    today = _date(2026, 5, 12)
    rows = [_inst(template_id=1, name="a", due=today, instance_id=1)]
    embed = build_chore_digest("Weekly", rows, today)
    assert embed.color == discord.Color.blurple()


def test_digest_orders_within_assignee_by_due_date():
    """Within one user's bucket, oldest-due (most overdue) shows first."""
    today = _date(2026, 5, 12)
    rows = [
        _inst(template_id=1, name="newer", due=today, instance_id=1),
        _inst(template_id=1, name="older", due=_date(2026, 5, 5), instance_id=2),
    ]
    embed = build_chore_digest("Weekly", rows, today)
    field = embed.fields[0]
    # "older" appears before "newer" in the joined value
    older_idx = field.value.find("older")
    newer_idx = field.value.find("newer")
    assert older_idx < newer_idx


def test_digest_title_includes_kind():
    today = _date(2026, 5, 12)
    rows = [_inst(template_id=1, name="a", due=today, instance_id=1)]
    weekly_embed = build_chore_digest("Weekly", rows, today)
    monthly_embed = build_chore_digest("Monthly", rows, today)
    assert "Weekly" in weekly_embed.title
    assert "Monthly" in monthly_embed.title
