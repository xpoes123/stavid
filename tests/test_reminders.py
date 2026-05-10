"""Unit tests for reminders cog parsers + DB persistence (no Discord side)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.cogs.reminders import _fmt_dt, _parse_user_datetime
from src.db import ReminderEntry
from src.utils import DAVID_ID, STEPH_ID

GUILD_ID = 999_000_000_000_000_000


# ---------------------------------------------------------------------------
# _parse_user_datetime
# ---------------------------------------------------------------------------


def test_parse_iso_date_24h_time():
    dt = _parse_user_datetime("2026-05-12", "15:00")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 5 and dt.day == 12
    assert dt.hour == 15 and dt.minute == 0
    assert dt.tzinfo is not None


def test_parse_us_date():
    dt = _parse_user_datetime("05/12/2026", "09:00")
    assert dt is not None
    assert dt.month == 5 and dt.day == 12


def test_parse_short_date():
    dt = _parse_user_datetime("12/25", "12:00")
    assert dt is not None
    assert dt.month == 12 and dt.day == 25


def test_parse_12h_pm():
    dt = _parse_user_datetime("2026-05-12", "3pm")
    assert dt is not None
    assert dt.hour == 15


def test_parse_12h_am():
    dt = _parse_user_datetime("2026-05-12", "9am")
    assert dt is not None
    assert dt.hour == 9


def test_parse_default_time():
    dt = _parse_user_datetime("2026-05-12", "")
    assert dt is not None
    assert dt.hour == 9 and dt.minute == 0


def test_parse_garbage_date_returns_none():
    assert _parse_user_datetime("not a date", "09:00") is None


def test_parse_garbage_time_returns_none():
    assert _parse_user_datetime("2026-05-12", "tomorrow") is None


def test_parse_empty_date_returns_none():
    assert _parse_user_datetime("", "09:00") is None


# ---------------------------------------------------------------------------
# _fmt_dt
# ---------------------------------------------------------------------------


def test_fmt_dt_basic():
    dt = datetime(2026, 5, 12, 15, 30, tzinfo=timezone.utc)
    out = _fmt_dt(dt)
    assert "May" in out
    assert "12" in out
    assert "3:30 PM" in out


def test_fmt_dt_morning():
    dt = datetime(2026, 5, 12, 9, 0, tzinfo=timezone.utc)
    assert "9:00 AM" in _fmt_dt(dt)


def test_fmt_dt_naive_treated_as_utc():
    dt = datetime(2026, 5, 12, 12, 0)
    assert "12:00 PM" in _fmt_dt(dt)


def test_fmt_dt_midnight():
    dt = datetime(2026, 5, 12, 0, 30, tzinfo=timezone.utc)
    assert "12:30 AM" in _fmt_dt(dt)


# ---------------------------------------------------------------------------
# DB-side: due reminders are returned in time order; done ones are excluded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_due_reminders_ordered_by_time(db_session):
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    # Three reminders, intentionally inserted out of order
    db_session.add(
        ReminderEntry(
            guild_id=GUILD_ID, creator_id=DAVID_ID, partner_id=STEPH_ID,
            time=now + timedelta(minutes=30), note="C",
        )
    )
    db_session.add(
        ReminderEntry(
            guild_id=GUILD_ID, creator_id=DAVID_ID, partner_id=STEPH_ID,
            time=now - timedelta(minutes=10), note="A",
        )
    )
    db_session.add(
        ReminderEntry(
            guild_id=GUILD_ID, creator_id=DAVID_ID, partner_id=STEPH_ID,
            time=now + timedelta(minutes=5), note="B",
        )
    )
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(ReminderEntry)
                .where(
                    ReminderEntry.guild_id == GUILD_ID,
                    ReminderEntry.done == False,  # noqa: E712
                )
                .order_by(ReminderEntry.time)
            )
        ).all()
    )
    notes = [r.note for r in rows]
    assert notes == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_done_reminders_excluded(db_session):
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    db_session.add(
        ReminderEntry(
            guild_id=GUILD_ID, creator_id=DAVID_ID, partner_id=STEPH_ID,
            time=now, note="finished", done=True,
        )
    )
    db_session.add(
        ReminderEntry(
            guild_id=GUILD_ID, creator_id=DAVID_ID, partner_id=STEPH_ID,
            time=now, note="active", done=False,
        )
    )
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(ReminderEntry).where(
                    ReminderEntry.guild_id == GUILD_ID,
                    ReminderEntry.done == False,  # noqa: E712
                )
            )
        ).all()
    )
    assert [r.note for r in rows] == ["active"]


@pytest.mark.asyncio
async def test_due_query_filters_by_time(db_session):
    """The fire_loop query selects only reminders with time <= now."""
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    db_session.add(
        ReminderEntry(
            guild_id=GUILD_ID, creator_id=DAVID_ID, partner_id=STEPH_ID,
            time=now - timedelta(minutes=1), note="due now",
        )
    )
    db_session.add(
        ReminderEntry(
            guild_id=GUILD_ID, creator_id=DAVID_ID, partner_id=STEPH_ID,
            time=now + timedelta(hours=2), note="future",
        )
    )
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(ReminderEntry).where(
                    ReminderEntry.done == False,  # noqa: E712
                    ReminderEntry.time <= now,
                )
            )
        ).all()
    )
    assert [r.note for r in rows] == ["due now"]
