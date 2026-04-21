"""Tests for daily pillar check-in persistence and playoff logic."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.cogs.playoff import get_pillar_names, series_message, week_start_for
from src.db import DailyResult, PlayoffCheckin, PlayoffSeries
from src.utils import DAVID_ID, STEPH_ID

GUILD_ID = 999_000_000_000_000_000

# ---------------------------------------------------------------------------
# week_start_for — must map every day in a Sun–Sat week to that week's Sunday
# ---------------------------------------------------------------------------

SUNDAY_APR_19 = date(2026, 4, 19)  # confirmed Sunday


@pytest.mark.parametrize("offset", range(7))
def test_week_start_for_all_days(offset):
    """Every day in a Sun–Sat week should map to the same Sunday."""
    day = SUNDAY_APR_19 + timedelta(days=offset)
    assert week_start_for(day) == SUNDAY_APR_19


def test_week_start_for_sunday_is_itself():
    assert week_start_for(SUNDAY_APR_19) == SUNDAY_APR_19


def test_week_start_for_saturday():
    saturday = date(2026, 4, 25)
    assert week_start_for(saturday) == SUNDAY_APR_19


def test_week_start_for_crosses_month():
    """Last day of March 2026 is a Tuesday → week started Sun Mar 29."""
    tue_mar_31 = date(2026, 3, 31)
    assert week_start_for(tue_mar_31) == date(2026, 3, 29)


# ---------------------------------------------------------------------------
# series_message — motivational copy for every score state
# ---------------------------------------------------------------------------


def test_series_message_won():
    msg = series_message(4, 0)
    assert "Won" in msg or "won" in msg


def test_series_message_lost():
    msg = series_message(0, 4)
    assert "lost" in msg.lower()


def test_series_message_tied():
    msg = series_message(2, 2)
    assert "Tied" in msg


def test_series_message_ahead():
    msg = series_message(3, 1)
    assert "Up" in msg


def test_series_message_behind_not_eliminated():
    msg = series_message(1, 3)
    # Should emphasise resilience rather than defeat
    assert "alive" in msg.lower() or "Down" in msg


def test_series_message_close_still_alive():
    msg = series_message(0, 3)
    assert "alive" in msg.lower()


# ---------------------------------------------------------------------------
# get_pillar_names — correct per-user pillars
# ---------------------------------------------------------------------------


def test_david_gets_his_pillars():
    pillars = get_pillar_names(DAVID_ID)
    assert any("steps" in p.lower() or "10,000" in p for p in pillars)
    assert len(pillars) == 3


def test_steph_gets_her_pillars():
    pillars = get_pillar_names(STEPH_ID)
    assert any("tiktok" in p.lower() for p in pillars)
    assert len(pillars) == 3


def test_unknown_user_gets_generic_pillars():
    pillars = get_pillar_names(0)
    assert pillars == ["Pillar 1", "Pillar 2", "Pillar 3"]


# ---------------------------------------------------------------------------
# DB persistence — PlayoffCheckin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_is_persisted(db_session):
    """A check-in row can be written and read back."""
    today = date(2026, 4, 21)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID,
            user_id=DAVID_ID,
            checkin_date=today,
            pillar1=True,
            pillar2=True,
            pillar3=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.guild_id == GUILD_ID,
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    assert row is not None
    assert row.pillar1 is True
    assert row.pillar2 is True
    assert row.pillar3 is False


@pytest.mark.asyncio
async def test_both_users_stored_independently(db_session):
    """David and Stephanie each get their own row per day."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=STEPH_ID, checkin_date=today,
            pillar1=False, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    david = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    steph = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.user_id == STEPH_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )

    assert david is not None and steph is not None
    assert david.pillar1 is True
    assert steph.pillar1 is False  # Steph missed pillar 1


@pytest.mark.asyncio
async def test_checkin_upsert_updates_values(db_session):
    """Re-submitting a check-in overwrites pillar values for that day."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    # Initial (all false)
    row = PlayoffCheckin(
        guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
        pillar1=False, pillar2=False, pillar3=False,
        created_at=now, updated_at=now,
    )
    db_session.add(row)
    await db_session.commit()

    # Upsert — same day, updated values
    existing = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.guild_id == GUILD_ID,
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    existing.pillar1 = True
    existing.pillar2 = True
    existing.pillar3 = True
    existing.updated_at = datetime.now(timezone.utc)
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.guild_id == GUILD_ID,
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    assert refreshed.pillar1 is True
    assert refreshed.pillar2 is True
    assert refreshed.pillar3 is True


@pytest.mark.asyncio
async def test_historical_checkins_queryable(db_session):
    """All 5 weekdays' check-ins for one user are retrievable as history."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(
            PlayoffCheckin(
                guild_id=GUILD_ID,
                user_id=DAVID_ID,
                checkin_date=week_start + timedelta(days=i),
                pillar1=True, pillar2=True, pillar3=True,
                created_at=now, updated_at=now,
            )
        )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(PlayoffCheckin).where(
                PlayoffCheckin.guild_id == GUILD_ID,
                PlayoffCheckin.user_id == DAVID_ID,
                PlayoffCheckin.checkin_date >= week_start,
            )
        )
    ).all()
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_series_win_requires_both_players(db_session):
    """A day only counts as a win when both David AND Steph hit all pillars."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    # David hits all; Steph only hits 2 — should be a loss
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=STEPH_ID, checkin_date=today,
            pillar1=False, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    wins, losses = _tally(
        (
            await db_session.scalars(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == GUILD_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
        ).all()
    )
    assert wins == 0
    assert losses == 1


@pytest.mark.asyncio
async def test_series_win_when_both_perfect(db_session):
    """Both players hitting all pillars = 1 series win."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    for uid in (DAVID_ID, STEPH_ID):
        db_session.add(
            PlayoffCheckin(
                guild_id=GUILD_ID, user_id=uid, checkin_date=today,
                pillar1=True, pillar2=True, pillar3=True,
                created_at=now, updated_at=now,
            )
        )
    await db_session.commit()

    wins, losses = _tally(
        (
            await db_session.scalars(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == GUILD_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
        ).all()
    )
    assert wins == 1
    assert losses == 0


@pytest.mark.asyncio
async def test_unsettled_day_not_counted(db_session):
    """A day where only one player has checked in is ignored by the tally."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    # Only David checks in
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    wins, losses = _tally(
        (
            await db_session.scalars(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == GUILD_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
        ).all()
    )
    assert wins == 0
    assert losses == 0


@pytest.mark.asyncio
async def test_full_week_series_accumulation(db_session):
    """4 shared-win days across a week results in a won series."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    for i in range(4):  # 4 days both perfect
        day = week_start + timedelta(days=i)
        for uid in (DAVID_ID, STEPH_ID):
            db_session.add(
                PlayoffCheckin(
                    guild_id=GUILD_ID, user_id=uid, checkin_date=day,
                    pillar1=True, pillar2=True, pillar3=True,
                    created_at=now, updated_at=now,
                )
            )
    # 1 day Steph misses
    bad_day = week_start + timedelta(days=4)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=bad_day,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=STEPH_ID, checkin_date=bad_day,
            pillar1=False, pillar2=False, pillar3=False,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    all_rows = (
        await db_session.scalars(
            select(PlayoffCheckin).where(
                PlayoffCheckin.guild_id == GUILD_ID,
                PlayoffCheckin.checkin_date >= week_start,
            )
        )
    ).all()
    wins, losses = _tally(all_rows)

    assert wins == 4
    assert losses == 1
    assert wins >= 4  # series won


# ---------------------------------------------------------------------------
# DB persistence — PlayoffSeries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_row_persisted(db_session):
    """PlayoffSeries aggregate can be written and read back."""
    now = datetime.now(timezone.utc)
    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=SUNDAY_APR_19,
            wins=3,
            losses=1,
            status="ongoing",
            created_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == SUNDAY_APR_19,
        )
    )
    assert row is not None
    assert row.wins == 3
    assert row.losses == 1
    assert row.status == "ongoing"


# ---------------------------------------------------------------------------
# DB persistence — DailyResult (combined win/loss, authoritative per day)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_result_persisted(db_session):
    """A DailyResult row can be written and read back."""
    now = datetime.now(timezone.utc)
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=date(2026, 4, 21),
            david_complete=True,
            steph_complete=True,
            won=True,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert row is not None
    assert row.won is True
    assert row.david_complete is True
    assert row.steph_complete is True


@pytest.mark.asyncio
async def test_daily_result_loss_when_one_incomplete(db_session):
    """won=False when either player is incomplete."""
    now = datetime.now(timezone.utc)
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=date(2026, 4, 21),
            david_complete=True,
            steph_complete=False,  # Steph didn't finish
            won=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert row is not None
    assert row.won is False
    assert row.david_complete is True
    assert row.steph_complete is False


@pytest.mark.asyncio
async def test_daily_result_upsert(db_session):
    """Re-settling a day (e.g., after a re-checkin) updates the existing row."""
    now = datetime.now(timezone.utc)
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=date(2026, 4, 21),
            david_complete=True,
            steph_complete=False,
            won=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    # Steph re-checks in — now both complete
    row = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    row.steph_complete = True
    row.won = True
    row.updated_at = datetime.now(timezone.utc)
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert refreshed.won is True
    assert refreshed.steph_complete is True


@pytest.mark.asyncio
async def test_series_tally_from_daily_results(db_session):
    """Series wins/losses derived from DailyResult rows match expected counts."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    # 3 wins, 1 loss over 4 days
    for i in range(3):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=week_start + timedelta(days=3),
            david_complete=True,
            steph_complete=False,
            won=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(DailyResult).where(
                DailyResult.guild_id == GUILD_ID,
                DailyResult.result_date >= week_start,
            )
        )
    ).all()

    wins = sum(1 for r in rows if r.won)
    losses = sum(1 for r in rows if not r.won)
    assert wins == 3
    assert losses == 1


@pytest.mark.asyncio
async def test_no_daily_result_until_both_checked_in(db_session):
    """DailyResult is absent when only one player has a PlayoffCheckin."""
    now = datetime.now(timezone.utc)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID,
            user_id=DAVID_ID,
            checkin_date=date(2026, 4, 21),
            pillar1=True,
            pillar2=True,
            pillar3=True,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    # No DailyResult should exist yet — Steph hasn't checked in
    result = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert result is None


@pytest.mark.asyncio
async def test_combined_win_requires_both_complete(db_session):
    """won=True only when david_complete AND steph_complete are both True."""
    now = datetime.now(timezone.utc)
    today = date(2026, 4, 21)

    cases = [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, True),
    ]
    for i, (dc, sc, expected_won) in enumerate(cases):
        result_date = today + timedelta(days=i)
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=result_date,
                david_complete=dc,
                steph_complete=sc,
                won=dc and sc,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    for i, (dc, sc, expected_won) in enumerate(cases):
        result_date = today + timedelta(days=i)
        row = await db_session.scalar(
            select(DailyResult).where(
                DailyResult.guild_id == GUILD_ID,
                DailyResult.result_date == result_date,
            )
        )
        assert row is not None
        assert row.won is expected_won, (
            f"dc={dc}, sc={sc}: expected won={expected_won}, got {row.won}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tally(checkins: list[PlayoffCheckin]) -> tuple[int, int]:
    """Mirror the win/loss accumulation logic from playoff._process_checkin."""
    by_date: dict[date, dict[int, PlayoffCheckin]] = {}
    for c in checkins:
        by_date.setdefault(c.checkin_date, {})[c.user_id] = c

    wins = 0
    losses = 0
    for day in by_date.values():
        if DAVID_ID not in day or STEPH_ID not in day:
            continue
        d, s = day[DAVID_ID], day[STEPH_ID]
        if d.pillar1 and d.pillar2 and d.pillar3 and s.pillar1 and s.pillar2 and s.pillar3:
            wins += 1
        else:
            losses += 1
    return wins, losses
